"""Tests fuer das CLI-Subcommand 'analyze' (Phase 2).

Es wird ausschliesslich der ``--in``-Pfad geprueft (Laden aus gespeicherter
JSON), damit der Test ohne Netz-/Notion-Abhaengigkeit laeuft. Eine synthetische
data.json wird in tmp_path geschrieben, dann main(['analyze', ...]) aufgerufen.
"""
import json

import pytest

from vereinsstatistik import cli
from vereinsstatistik.cli import main
from vereinsstatistik.notion_client import NotionError


def _synthetische_daten():
    return {
        "mitglieder": [
            {"_id": "m1", "name": "Anna", "eintrittsdatum": "2024-01-01"},
            {"_id": "m2", "name": "Bernd", "eintrittsdatum": "2024-01-01"},
            {"_id": "m3", "name": "Clara", "eintrittsdatum": "2024-01-01"},
        ],
        "gruppenstunden": [
            {"_id": "g1", "datum": "2024-01-05", "titel": "Spiele", "teilnehmer": ["m1", "m2"]},
            {"_id": "g2", "datum": "2024-02-12", "titel": "Basteln", "teilnehmer": ["m1"]},
            {"_id": "g3", "datum": "2024-03-01", "titel": "Spiele", "teilnehmer": ["m1", "m3"]},
        ],
        "lager": [
            {"_id": "l1", "name": "Sommerlager", "datum": "2024-07-01", "teilnehmer": ["m1", "m2"]},
        ],
        "_meta": {"quelle": "synthetisch"},
    }


def test_analyze_in_schreibt_report(tmp_path, capsys):
    daten_datei = tmp_path / "data.json"
    report_datei = tmp_path / "report.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    rc = main(["analyze", "--in", str(daten_datei), "--out", str(report_datei)])

    # Exit-Code 0 und Report wurde geschrieben.
    assert rc == 0
    assert report_datei.exists()

    report = json.loads(report_datei.read_text(encoding="utf-8"))
    # Der Report enthaelt die erwarteten Kennzahlen-Schluessel.
    assert "gesamtkennzahlen" in report
    assert "top_flop_anwesenheit" in report
    # Gesamtkennzahlen sind seit der Jahres-Dimension eine Liste; das
    # "alle Jahre"-Aggregat (jahr is None) traegt die Vereinszahlen.
    gk_alle = [g for g in report["gesamtkennzahlen"] if g.get("jahr") is None]
    assert len(gk_alle) == 1
    assert gk_alle[0]["anzahl_mitglieder_gesamt"] == 3

    # Eine deutsche Zusammenfassung landet auf der Konsole.
    ausgabe = capsys.readouterr().out
    assert "Zusammenfassung (alle Jahre):" in ausgabe
    assert f"Gespeichert nach {report_datei}" in ausgabe


def test_analyze_in_ohne_out(tmp_path, capsys):
    daten_datei = tmp_path / "data.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    rc = main(["analyze", "--in", str(daten_datei)])

    assert rc == 0
    ausgabe = capsys.readouterr().out
    assert "Zusammenfassung (alle Jahre):" in ausgabe


# ---------------------------------------------------------------------------
# Live-Notion-Pfad von analyze (ohne --in), ueber gemockte Notion-Zugaenge.
# Es wird KEIN echter Netz-/Notion-Zugriff ausgefuehrt: load_config, _client und
# fetch_all werden ersetzt. Geprueft werden Dispatch (Erfolgsfall) und die
# Fehlerbehandlung (NotionError -> 'FEHLER: ...' auf stderr, Exit 1).
# ---------------------------------------------------------------------------

class _FakeConfig:
    analysis = None


class _FakeClientCtx:
    """Minimaler Kontextmanager-Ersatz fuer _client(cfg)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_analyze_live_pfad_erfolg(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: _FakeConfig())
    monkeypatch.setattr(cli, "_client", lambda cfg: _FakeClientCtx())
    monkeypatch.setattr(cli, "fetch_all", lambda cfg, client: _synthetische_daten())

    rc = main(["analyze"])  # kein --in -> Live-Pfad

    assert rc == 0
    ausgabe = capsys.readouterr().out
    assert "Zusammenfassung (alle Jahre):" in ausgabe


def test_analyze_live_pfad_notion_fehler(monkeypatch, capsys):
    def _boom(cfg, client):
        raise NotionError("Token ungueltig")

    monkeypatch.setattr(cli, "load_config", lambda: _FakeConfig())
    monkeypatch.setattr(cli, "_client", lambda cfg: _FakeClientCtx())
    monkeypatch.setattr(cli, "fetch_all", _boom)

    rc = main(["analyze"])  # kein --in -> Live-Pfad, Fehlerfall

    assert rc == 1
    err = capsys.readouterr().err
    assert "FEHLER:" in err
    assert "Token ungueltig" in err
