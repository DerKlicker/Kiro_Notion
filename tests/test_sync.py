"""Tests fuer das Sync-Modul (Phase 3).

Es wird KEINE echte PostgreSQL und KEIN Netz verwendet. Statt einer echten
Verbindung kommt ein FakeCursor/FakeConnection zum Einsatz, das execute,
executemany, fetchone und das Context-Manager-Protokoll bedient und die
ausgefuehrten SQL-Statements samt Parameter mitschreibt. So lassen sich die
erzeugten Statements, die Zeilenanzahl je Kennzahl, NULL-Faelle und die
Fehlerpfade pruefen.
"""
import json

import pytest

from vereinsstatistik import cli
from vereinsstatistik import sync
from vereinsstatistik.analysis import analyze
from vereinsstatistik.cli import main
from vereinsstatistik.sync import SyncError


# ---------------------------------------------------------------------------
# Fakes fuer Cursor und Verbindung
# ---------------------------------------------------------------------------

class FakeCursor:
    """Minimaler Cursor-Ersatz, der ausgefuehrtes SQL mitschreibt.

    ``fetchone`` liefert fuer ein RETURNING-INSERT eine feste run_id (hier 42).
    """

    def __init__(self, calls, run_id=42):
        self._calls = calls
        self._run_id = run_id
        self._letztes_war_returning = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append(("execute", sql, params))
        self._letztes_war_returning = "RETURNING" in sql

    def executemany(self, sql, seq):
        # seq in eine Liste materialisieren, damit sie auswertbar bleibt.
        self._calls.append(("executemany", sql, list(seq)))
        self._letztes_war_returning = False

    def fetchone(self):
        if self._letztes_war_returning:
            return (self._run_id,)
        return None


class FakeConnection:
    """Minimaler Verbindungs-Ersatz, der Cursor, commit und rollback zaehlt."""

    def __init__(self, run_id=42):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self._run_id = run_id

    def cursor(self):
        return FakeCursor(self.calls, run_id=self._run_id)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Konfig-Fakes
# ---------------------------------------------------------------------------

class _Analysis:
    only_active_members = False
    bundesland = ""


class _Postgres:
    def __init__(self, enabled=True, schema="public", database="vereinsstatistik",
                 host="localhost", port=5432, user="verein"):
        self.enabled = enabled
        self.schema_ = schema
        self.database = database
        self.host = host
        self.port = port
        self.user = user


class FakeConfig:
    """Config-Ersatz mit den von sync.py genutzten Attributen."""

    def __init__(self, enabled=True, pg_password="geheim", schema="public"):
        self.postgres = _Postgres(enabled=enabled, schema=schema)
        self.analysis = _Analysis()
        self.pg_password = pg_password


# ---------------------------------------------------------------------------
# Fixtures: kleiner, aber vollstaendiger analyze()-Report
# ---------------------------------------------------------------------------

def _synthetische_daten():
    """Kleine Daten mit NULL-Faellen: m3 hat keine moegliche Stunde (Eintritt
    nach der letzten Stunde) -> quote_prozent None und Risiko nicht bewertbar.
    """
    return {
        "mitglieder": [
            {"_id": "m1", "name": "Anna", "eintrittsdatum": "2024-01-01"},
            {"_id": "m2", "name": "Bernd", "eintrittsdatum": "2024-01-01"},
            {"_id": "m3", "name": "Clara", "eintrittsdatum": "2030-01-01"},
        ],
        "gruppenstunden": [
            {"_id": "g1", "datum": "2024-01-05", "titel": "Spiele", "teilnehmer": ["m1", "m2"]},
            {"_id": "g2", "datum": "2024-02-12", "titel": "Basteln", "teilnehmer": ["m1"]},
            {"_id": "g3", "datum": "2024-03-01", "titel": "Spiele", "teilnehmer": ["m1"]},
        ],
        "lager": [
            {"_id": "l1", "name": "Sommerlager", "datum": "2024-07-01", "teilnehmer": ["m1", "m2"]},
        ],
        "_meta": {"quelle": "synthetisch"},
    }


@pytest.fixture
def report():
    return analyze(_synthetische_daten(), cfg=None)


def _calls_fuer_tabelle(calls, tabelle):
    """Alle (art, sql, params)-Eintraege fuer eine Tabelle herausfiltern."""
    return [c for c in calls if tabelle in c[1]]


# ---------------------------------------------------------------------------
# write_report: Erfolgsfall
# ---------------------------------------------------------------------------

def test_write_report_schreibt_lauf_und_gibt_run_id(report):
    conn = FakeConnection(run_id=42)
    run_id = sync.write_report(report, FakeConfig(), conn=conn)

    # run_id stammt aus fetchone des RETURNING-INSERT.
    assert run_id == 42
    assert conn.commits == 1
    assert conn.rollbacks == 0

    # Genau ein INSERT in 'laeufe' mit RETURNING.
    lauf_inserts = [
        c for c in conn.calls
        if c[0] == "execute" and ".laeufe" in c[1] and "RETURNING" in c[1]
    ]
    assert len(lauf_inserts) == 1


def test_write_report_kennzahl_zeilenzahlen_und_null(report):
    conn = FakeConnection()
    sync.write_report(report, FakeConfig(), conn=conn)

    # Top/Flop: eine Zeile je Mitglied (3).
    tf = _calls_fuer_tabelle(conn.calls, "kennzahl_top_flop_anwesenheit")
    assert len(tf) == 1 and tf[0][0] == "executemany"
    assert len(tf[0][2]) == 3

    # Faire Beteiligung: 3 Zeilen, m3 hat quote_prozent None.
    fb = _calls_fuer_tabelle(conn.calls, "kennzahl_faire_beteiligung")
    assert len(fb[0][2]) == 3
    quoten = [zeile[-1] for zeile in fb[0][2]]
    assert None in quoten  # NULL-Fall vorhanden

    # Risiko: 3 Zeilen, m3 nicht bewertbar (bewertbar False, score None).
    ri = _calls_fuer_tabelle(conn.calls, "kennzahl_risiko")
    assert len(ri[0][2]) == 3
    # bewertbar ist Index 3, risiko_score Index 7.
    nicht_bewertbar = [z for z in ri[0][2] if z[3] is False]
    assert len(nicht_bewertbar) == 1
    assert nicht_bewertbar[0][7] is None

    # Lager-Korrelation: genau zwei Gruppen-Zeilen.
    lk = _calls_fuer_tabelle(conn.calls, "kennzahl_lager_korrelation")
    assert len(lk[0][2]) == 2
    gruppen = {z[1] for z in lk[0][2]}
    assert gruppen == {"lagerteilnehmer", "nicht_teilnehmer"}

    # Gesamt: genau eine Zeile (execute, kein executemany).
    ge = _calls_fuer_tabelle(conn.calls, "kennzahl_gesamt")
    assert len(ge) == 1 and ge[0][0] == "execute"

    # Puenktlichkeit: nicht verfuegbar -> eine Zeile mit verfuegbar False.
    pk = _calls_fuer_tabelle(conn.calls, "kennzahl_puenktlichkeit")
    assert len(pk[0][2]) == 1
    assert pk[0][2][0][1] is False


def test_write_report_alle_werte_parametrisiert(report):
    conn = FakeConnection()
    sync.write_report(report, FakeConfig(), conn=conn)

    # Jeder execute/executemany-Aufruf uebergibt Parameter getrennt vom SQL.
    for art, sql, params in conn.calls:
        assert params is not None
        # Keine Mitgliedsnamen o. ae. direkt im SQL interpoliert.
        assert "Anna" not in sql


def test_write_report_nutzt_konfiguriertes_schema(report):
    conn = FakeConnection()
    sync.write_report(report, FakeConfig(schema="statistik"), conn=conn)

    assert any("statistik.laeufe" in c[1] for c in conn.calls)


# ---------------------------------------------------------------------------
# write_report / connect: Fehlerpfade
# ---------------------------------------------------------------------------

def test_write_report_postgres_deaktiviert():
    # Ohne conn versucht write_report selbst zu verbinden -> Vorab-Pruefung.
    with pytest.raises(SyncError) as exc:
        sync.write_report({}, FakeConfig(enabled=False))
    assert "deaktiviert" in str(exc.value)


def test_write_report_ohne_passwort():
    with pytest.raises(SyncError) as exc:
        sync.write_report({}, FakeConfig(pg_password=None))
    assert "PG_PASSWORD" in str(exc.value)


def test_connect_deaktiviert_meldung():
    with pytest.raises(SyncError) as exc:
        sync.connect(FakeConfig(enabled=False))
    assert "postgres.enabled=false" in str(exc.value)


# ---------------------------------------------------------------------------
# init_db: schema.sql lesen und {schema} ersetzen
# ---------------------------------------------------------------------------

def test_init_db_ersetzt_schema_platzhalter():
    conn = FakeConnection()
    sync.init_db(FakeConfig(schema="statistik"), conn=conn)

    assert conn.commits == 1
    # Genau ein execute mit dem kompletten Skript.
    assert len(conn.calls) == 1
    _, sql, _ = conn.calls[0]
    # Platzhalter ersetzt, kein {schema} mehr enthalten.
    assert "{schema}" not in sql
    assert "CREATE SCHEMA IF NOT EXISTS statistik" in sql
    assert "statistik.laeufe" in sql


def test_init_db_unzulaessiger_schemaname():
    conn = FakeConnection()
    with pytest.raises(SyncError) as exc:
        sync.init_db(FakeConfig(schema="boese; DROP TABLE x"), conn=conn)
    assert "Schemaname" in str(exc.value)
    # Es darf nichts ausgefuehrt worden sein.
    assert conn.calls == []


# ---------------------------------------------------------------------------
# CLI: cmd_sync mit --in (gemocktes write_report)
# ---------------------------------------------------------------------------

def test_cmd_sync_in_erfolg(tmp_path, capsys, monkeypatch):
    daten_datei = tmp_path / "data.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(cli, "load_config", lambda: FakeConfig())
    monkeypatch.setattr(cli.sync, "write_report", lambda report, cfg: 7)

    rc = main(["sync", "--in", str(daten_datei)])

    assert rc == 0
    ausgabe = capsys.readouterr().out
    assert "run_id=7" in ausgabe
    assert "PostgreSQL" in ausgabe


def test_cmd_sync_in_init_db_flag(tmp_path, capsys, monkeypatch):
    daten_datei = tmp_path / "data.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    aufrufe = {"init_db": 0}
    monkeypatch.setattr(cli, "load_config", lambda: FakeConfig())
    monkeypatch.setattr(cli.sync, "init_db", lambda cfg: aufrufe.__setitem__("init_db", aufrufe["init_db"] + 1))
    monkeypatch.setattr(cli.sync, "write_report", lambda report, cfg: 9)

    rc = main(["sync", "--in", str(daten_datei), "--init-db"])

    assert rc == 0
    assert aufrufe["init_db"] == 1


def test_cmd_sync_in_sync_error(tmp_path, capsys, monkeypatch):
    daten_datei = tmp_path / "data.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    def _boom(report, cfg):
        raise SyncError("Verbindung weg")

    monkeypatch.setattr(cli, "load_config", lambda: FakeConfig())
    monkeypatch.setattr(cli.sync, "write_report", _boom)

    rc = main(["sync", "--in", str(daten_datei)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "FEHLER:" in err
    assert "Verbindung weg" in err


def test_cmd_init_db_erfolg(capsys, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: FakeConfig(schema="statistik"))
    monkeypatch.setattr(cli.sync, "init_db", lambda cfg: None)

    rc = main(["init-db"])

    assert rc == 0
    ausgabe = capsys.readouterr().out
    assert "Schema initialisiert" in ausgabe
    assert "statistik" in ausgabe


def test_cmd_init_db_sync_error(capsys, monkeypatch):
    def _boom(cfg):
        raise SyncError("PostgreSQL ist in der config.yaml deaktiviert (postgres.enabled=false).")

    monkeypatch.setattr(cli, "load_config", lambda: FakeConfig(enabled=False))
    monkeypatch.setattr(cli.sync, "init_db", _boom)

    rc = main(["init-db"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "FEHLER:" in err
    assert "deaktiviert" in err
