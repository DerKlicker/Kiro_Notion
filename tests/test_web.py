"""Tests fuer die Web-UI (Phase 4).

Es wird KEIN echter Notion-Zugriff und KEINE echte PostgreSQL verwendet. Die
im web-Modul genutzten Namen werden per monkeypatch durch Fakes ersetzt und die
Endpunkte ueber den FastAPI-TestClient (in-process, ohne echten HTTP-Server)
aufgerufen. Geprueft werden der Erfolgsfall von /api/sync inklusive der
deutschen Zusammenfassung sowie die Fehlerpfade (kein Token, SyncError) und die
Selbstinitialisierung der config.yaml.
"""
import pytest
from fastapi.testclient import TestClient

from vereinsstatistik import config as config_modul
from vereinsstatistik import web
from vereinsstatistik.notion_client import NotionError
from vereinsstatistik.sync import SyncError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeClientCM:
    """Notion-Client-Ersatz mit Context-Manager-Protokoll (ohne Netz)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConfig:
    """Minimaler Config-Ersatz; die echten Werte sind fuer den Sync egal,
    da fetch_all/analyze/sync gemockt werden."""


class _FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _daten():
    """Kleiner fetch_all-Output mit _meta-Zaehlungen."""
    return {
        "mitglieder": [{"_id": "m1"}, {"_id": "m2"}],
        "gruppenstunden": [{"_id": "g1"}],
        "lager": [{"_id": "l1"}],
        "_meta": {"mitglieder": 2, "gruppenstunden": 1, "lager": 1},
    }


def _report():
    """Analyze-Ersatz-Report mit Top/Flop-Zeilen."""
    return {
        "_meta": {"anzahl_mitglieder": 2},
        "top_flop_anwesenheit": [
            {"mitglied_id": "m1", "name": "Anna", "anwesend_absolut": 5, "rang": 1},
            {"mitglied_id": "m2", "name": "Bernd", "anwesend_absolut": 0, "rang": 2},
        ],
    }


@pytest.fixture
def client():
    return TestClient(web.app)


# ---------------------------------------------------------------------------
# /api/sync - Erfolgsfall
# ---------------------------------------------------------------------------

def test_api_sync_erfolg(client, monkeypatch):
    aufrufe = {"init_db": 0, "write_report": 0}

    monkeypatch.setattr(web, "_client", lambda: (_FakeConfig(), _FakeClientCM()))
    monkeypatch.setattr(web, "fetch_all", lambda cfg, c: _daten())
    monkeypatch.setattr(web, "analyze", lambda daten, cfg: _report())
    monkeypatch.setattr(web.sync_modul, "connect", lambda cfg: _FakeConnection())
    monkeypatch.setattr(
        web.sync_modul, "init_db",
        lambda cfg, conn=None: aufrufe.__setitem__("init_db", aufrufe["init_db"] + 1),
    )
    monkeypatch.setattr(
        web.sync_modul, "write_report",
        lambda report, cfg, conn=None: aufrufe.__setitem__(
            "write_report", aufrufe["write_report"] + 1
        ) or 123,
    )

    r = client.post("/api/sync")

    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["run_id"] == 123
    # init_db muss idempotent vor write_report laufen (erster Klick).
    assert aufrufe["init_db"] == 1
    assert aufrufe["write_report"] == 1

    z = j["zusammenfassung"]
    assert z["anzahl_mitglieder"] == 2
    assert z["anzahl_gruppenstunden"] == 1
    assert z["anzahl_lager"] == 1
    assert z["run_id"] == 123
    assert z["top_1"]["name"] == "Anna"
    assert z["flop_1"]["name"] == "Bernd"


# ---------------------------------------------------------------------------
# /api/sync - Fehlerpfade
# ---------------------------------------------------------------------------

def test_api_sync_ohne_token_400(client, monkeypatch):
    def _kein_token():
        raise NotionError("Kein NOTION_TOKEN gesetzt. Bitte oben eintragen und speichern.")

    monkeypatch.setattr(web, "_client", _kein_token)

    r = client.post("/api/sync")

    assert r.status_code == 400
    j = r.json()
    assert j["ok"] is False
    assert "NOTION_TOKEN" in j["error"]


def test_api_sync_sync_error_400(client, monkeypatch):
    monkeypatch.setattr(web, "_client", lambda: (_FakeConfig(), _FakeClientCM()))
    monkeypatch.setattr(web, "fetch_all", lambda cfg, c: _daten())
    monkeypatch.setattr(web, "analyze", lambda daten, cfg: _report())

    def _boom(cfg):
        raise SyncError("PostgreSQL ist in der config.yaml deaktiviert (postgres.enabled=false).")

    monkeypatch.setattr(web.sync_modul, "connect", _boom)

    r = client.post("/api/sync")

    assert r.status_code == 400
    j = r.json()
    assert j["ok"] is False
    assert "deaktiviert" in j["error"]


def test_api_sync_write_error_schliesst_verbindung(client, monkeypatch):
    """Auch bei SyncError in write_report muss die Verbindung geschlossen und
    400 zurueckgegeben werden."""
    verbindung = _FakeConnection()

    monkeypatch.setattr(web, "_client", lambda: (_FakeConfig(), _FakeClientCM()))
    monkeypatch.setattr(web, "fetch_all", lambda cfg, c: _daten())
    monkeypatch.setattr(web, "analyze", lambda daten, cfg: _report())
    monkeypatch.setattr(web.sync_modul, "connect", lambda cfg: verbindung)
    monkeypatch.setattr(web.sync_modul, "init_db", lambda cfg, conn=None: None)

    def _boom(report, cfg, conn=None):
        raise SyncError("Lauf konnte nicht gespeichert werden: x")

    monkeypatch.setattr(web.sync_modul, "write_report", _boom)

    r = client.post("/api/sync")

    assert r.status_code == 400
    assert r.json()["ok"] is False
    assert verbindung.closed is True


# ---------------------------------------------------------------------------
# GET / rendert die Seite inkl. Sync-Button
# ---------------------------------------------------------------------------

def test_index_enthaelt_sync_button(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Jetzt synchronisieren" in r.text
    assert 'id="sync-btn"' in r.text


# ---------------------------------------------------------------------------
# Selbstinitialisierung der config.yaml (Feature B)
# ---------------------------------------------------------------------------

def test_ensure_config_initialized_aus_vorlage(tmp_path):
    ziel = tmp_path / "config_dir" / "config.yaml"
    vorlage = tmp_path / "config.example.yaml"
    vorlage.write_text("notion:\n  api_version: \"2025-09-03\"\n", encoding="utf-8")

    neu = config_modul.ensure_config_initialized(config_path=ziel, example_path=vorlage)

    assert neu is True
    assert ziel.exists()
    assert "api_version" in ziel.read_text(encoding="utf-8")


def test_ensure_config_initialized_ueberschreibt_nicht(tmp_path):
    ziel = tmp_path / "config.yaml"
    ziel.write_text("bestehend: true\n", encoding="utf-8")
    vorlage = tmp_path / "config.example.yaml"
    vorlage.write_text("notion:\n  api_version: \"x\"\n", encoding="utf-8")

    neu = config_modul.ensure_config_initialized(config_path=ziel, example_path=vorlage)

    assert neu is False
    # Inhalt bleibt unveraendert.
    assert ziel.read_text(encoding="utf-8") == "bestehend: true\n"


def test_ensure_config_initialized_ohne_vorlage_default(tmp_path):
    """Fehlt die Vorlage, wird eine gueltige Default-Struktur geschrieben."""
    ziel = tmp_path / "config.yaml"
    fehlende_vorlage = tmp_path / "gibtsnicht.yaml"

    neu = config_modul.ensure_config_initialized(
        config_path=ziel, example_path=fehlende_vorlage
    )

    assert neu is True
    cfg = config_modul.load_config(path=ziel, load_env=False)
    assert set(cfg.databases) == {"mitglieder", "gruppenstunden", "lager"}
