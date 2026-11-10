"""Tests fuer das CLI-Subcommand 'analyze' (Phase 2).

Es wird ausschliesslich der ``--in``-Pfad geprueft (Laden aus gespeicherter
JSON), damit der Test ohne Netz-/Notion-Abhaengigkeit laeuft. Eine synthetische
data.json wird in tmp_path geschrieben, dann main(['analyze', ...]) aufgerufen.
"""
import json

from vereinsstatistik.cli import main


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
    assert report["gesamtkennzahlen"]["anzahl_mitglieder_gesamt"] == 3

    # Eine deutsche Zusammenfassung landet auf der Konsole.
    ausgabe = capsys.readouterr().out
    assert "Zusammenfassung:" in ausgabe
    assert f"Gespeichert nach {report_datei}" in ausgabe


def test_analyze_in_ohne_out(tmp_path, capsys):
    daten_datei = tmp_path / "data.json"
    daten_datei.write_text(
        json.dumps(_synthetische_daten(), ensure_ascii=False), encoding="utf-8"
    )

    rc = main(["analyze", "--in", str(daten_datei)])

    assert rc == 0
    ausgabe = capsys.readouterr().out
    assert "Zusammenfassung:" in ausgabe
