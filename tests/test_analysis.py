"""Tests fuer das Auswertungs-Modul (Phase 2).

Die Fixtures sind synthetische dicts im internen Datenmodell (siehe fetch.py).
Es gibt keine Netz-/Notion-Abhaengigkeit. Jeder Test uebt die fachliche Logik
wirklich aus und schlaegt fehl, wenn die jeweilige Logik entfernt/reverted wird.
"""
import json
from datetime import date

import pytest

from vereinsstatistik.analysis import (
    RISIKO_FENSTER_N,
    analyze,
    faire_beteiligung,
    gesamtkennzahlen,
    ist_ausgeschieden,
    lager_korrelation,
    load_data,
    parse_date,
    puenktlichkeit,
    risiko_score,
    saisonalitaet,
    thema_ranking,
    top_flop_anwesenheit,
)


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

def test_parse_date_reines_datum():
    assert parse_date("2026-03-01") == date(2026, 3, 1)


def test_parse_date_mit_zeit_und_zeitzone():
    assert parse_date("2026-03-01T10:00:00+02:00") == date(2026, 3, 1)
    assert parse_date("2026-03-01 08:30:00") == date(2026, 3, 1)


def test_parse_date_none_und_ungueltig():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("kein-datum") is None
    assert parse_date(12345) is None


# ---------------------------------------------------------------------------
# KENNZAHL 1 - Top/Flop-Anwesenheit
# ---------------------------------------------------------------------------

def _basis_mitglieder():
    return [
        {"_id": "m1", "name": "Anna", "eintrittsdatum": "2024-01-01"},
        {"_id": "m2", "name": "Bernd", "eintrittsdatum": "2024-01-01"},
        {"_id": "m3", "name": "Clara", "eintrittsdatum": "2024-01-01"},
    ]


def test_top_flop_rang_und_jahresfilter():
    mitglieder = _basis_mitglieder()
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-05", "teilnehmer": ["m1", "m2"]},
        {"_id": "g2", "datum": "2024-01-12", "teilnehmer": ["m1"]},
        {"_id": "g3", "datum": "2025-02-01", "teilnehmer": ["m1", "m3"]},
    ]
    alle = top_flop_anwesenheit(mitglieder, gruppenstunden)
    by_id = {z["mitglied_id"]: z for z in alle}
    assert by_id["m1"]["anwesend_absolut"] == 3
    assert by_id["m2"]["anwesend_absolut"] == 1
    assert by_id["m3"]["anwesend_absolut"] == 1
    # Dichter Rang: m1 Rang 1, m2 und m3 gleich -> Rang 2.
    assert by_id["m1"]["rang"] == 1
    assert by_id["m2"]["rang"] == 2
    assert by_id["m3"]["rang"] == 2

    # Jahresfilter 2024: m3 war nur 2025 da -> 0.
    nur2024 = {z["mitglied_id"]: z for z in top_flop_anwesenheit(mitglieder, gruppenstunden, jahr=2024)}
    assert nur2024["m1"]["anwesend_absolut"] == 2
    assert nur2024["m3"]["anwesend_absolut"] == 0


# ---------------------------------------------------------------------------
# KENNZAHL 2 - Faire relative Beteiligung (zentrale Logik)
# ---------------------------------------------------------------------------

def test_faire_beteiligung_neuzugang_nicht_benachteiligt():
    # 4 Gruppenstunden; m_neu tritt erst zur 3. Stunde ein.
    mitglieder = [
        {"_id": "alt", "name": "Alt", "eintrittsdatum": "2024-01-01"},
        {"_id": "neu", "name": "Neu", "eintrittsdatum": "2024-03-01"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-10", "teilnehmer": ["alt"]},
        {"_id": "g2", "datum": "2024-02-10", "teilnehmer": ["alt"]},
        {"_id": "g3", "datum": "2024-03-10", "teilnehmer": ["alt", "neu"]},
        {"_id": "g4", "datum": "2024-04-10", "teilnehmer": ["neu"]},
    ]
    rows = {r["mitglied_id"]: r for r in faire_beteiligung(mitglieder, gruppenstunden)}
    # Alt: 4 moeglich, 3 anwesend = 75 %.
    assert rows["alt"]["moegliche_stunden"] == 4
    assert rows["alt"]["anwesend"] == 3
    assert rows["alt"]["quote_prozent"] == 75.0
    # Neu: nur g3 und g4 moeglich (nach Eintritt), beide anwesend = 100 %.
    assert rows["neu"]["moegliche_stunden"] == 2
    assert rows["neu"]["anwesend"] == 2
    assert rows["neu"]["quote_prozent"] == 100.0


def test_faire_beteiligung_austritt_begrenzt_zeitraum():
    mitglieder = [
        {"_id": "aus", "name": "Aus", "eintrittsdatum": "2024-01-01", "austrittsdatum": "2024-02-15"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-10", "teilnehmer": ["aus"]},
        {"_id": "g2", "datum": "2024-02-10", "teilnehmer": []},
        {"_id": "g3", "datum": "2024-03-10", "teilnehmer": []},  # nach Austritt, zaehlt nicht
    ]
    rows = {r["mitglied_id"]: r for r in faire_beteiligung(mitglieder, gruppenstunden)}
    assert rows["aus"]["moegliche_stunden"] == 2
    assert rows["aus"]["anwesend"] == 1
    assert rows["aus"]["quote_prozent"] == 50.0


def test_faire_beteiligung_null_moegliche_stunden_ist_none():
    mitglieder = [{"_id": "x", "name": "X", "eintrittsdatum": "2030-01-01"}]
    gruppenstunden = [{"_id": "g1", "datum": "2024-01-10", "teilnehmer": []}]
    rows = faire_beteiligung(mitglieder, gruppenstunden)
    assert rows[0]["moegliche_stunden"] == 0
    assert rows[0]["quote_prozent"] is None


# ---------------------------------------------------------------------------
# KENNZAHL 3 - Risiko-Score
# ---------------------------------------------------------------------------

def test_risiko_score_erkennt_abfall_und_abwesenheit():
    # Mitglied war frueher immer da, in den letzten N Stunden nie -> hohes Risiko.
    mitglieder = [{"_id": "r", "name": "R", "eintrittsdatum": "2024-01-01"}]
    gruppenstunden = []
    # 5 Stunden anwesend (davor), danach RISIKO_FENSTER_N Stunden abwesend.
    tag = 1
    for i in range(5):
        gruppenstunden.append({"_id": f"a{i}", "datum": f"2024-01-{tag:02d}", "teilnehmer": ["r"]})
        tag += 1
    for i in range(RISIKO_FENSTER_N):
        gruppenstunden.append({"_id": f"b{i}", "datum": f"2024-02-{tag:02d}", "teilnehmer": []})
        tag += 1

    rows = {z["mitglied_id"]: z for z in risiko_score(mitglieder, gruppenstunden)}
    row = rows["r"]
    assert row["quote_letzte_n"] == 0.0
    assert row["quote_davor"] == 1.0
    assert row["stunden_seit_letzter_anwesenheit"] == RISIKO_FENSTER_N
    assert row["risiko_score"] == pytest.approx(1.0)
    assert row["risiko_stufe"] == "hoch"


def test_risiko_score_treuer_besucher_niedrig():
    mitglieder = [{"_id": "t", "name": "T", "eintrittsdatum": "2024-01-01"}]
    gruppenstunden = [
        {"_id": f"g{i}", "datum": f"2024-01-{i + 1:02d}", "teilnehmer": ["t"]}
        for i in range(8)
    ]
    rows = {z["mitglied_id"]: z for z in risiko_score(mitglieder, gruppenstunden)}
    row = rows["t"]
    assert row["bewertbar"] is True
    assert row["stunden_seit_letzter_anwesenheit"] == 0
    assert row["risiko_score"] == pytest.approx(0.0)
    assert row["risiko_stufe"] == "niedrig"


def test_risiko_score_ohne_aktive_stunden_ist_unbekannt():
    # Neuzugang tritt nach der letzten vorhandenen Stunde ein -> keine aktiven
    # Stunden. Das darf NICHT wie ein echtes Nullrisiko (0.0/"niedrig")
    # aussehen, sondern muss als nicht bewertbar markiert sein.
    mitglieder = [{"_id": "neu", "name": "Neu", "eintrittsdatum": "2030-01-01"}]
    gruppenstunden = [{"_id": "g1", "datum": "2024-01-01", "teilnehmer": []}]
    rows = {z["mitglied_id"]: z for z in risiko_score(mitglieder, gruppenstunden)}
    row = rows["neu"]
    assert row["bewertbar"] is False
    assert row["risiko_score"] is None
    assert row["risiko_stufe"] == "unbekannt"
    assert row["quote_letzte_n"] is None
    assert row["quote_davor"] is None


# ---------------------------------------------------------------------------
# KENNZAHL 4 - Saisonalitaet
# ---------------------------------------------------------------------------

def test_saisonalitaet_monat_wochentag_und_ferien_uebersprungen():
    gruppenstunden = [
        # 2024-01-01 ist ein Montag (weekday 0).
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["a", "b"]},
        # 2024-01-08 ist ebenfalls Montag.
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["a"]},
        # 2024-03-05 ist ein Dienstag (weekday 1).
        {"_id": "g3", "datum": "2024-03-05", "teilnehmer": ["a", "b", "c"]},
    ]
    res = saisonalitaet(gruppenstunden, bundesland="")
    monate = {m["monat"]: m for m in res["pro_monat"]}
    assert monate[1]["anzahl_stunden"] == 2
    assert monate[1]["summe_anwesend"] == 3
    assert monate[1]["schnitt_anwesend"] == 1.5
    assert monate[3]["summe_anwesend"] == 3

    wtage = {w["wochentag"]: w for w in res["pro_wochentag"]}
    assert wtage[0]["anzahl_stunden"] == 2  # zwei Montage
    assert wtage[1]["summe_anwesend"] == 3  # Dienstag
    # Ohne Bundesland wird die Ferien-Korrelation sauber uebersprungen.
    assert res["ferien_korrelation"] is None


# ---------------------------------------------------------------------------
# KENNZAHL 5 - Thema-Ranking
# ---------------------------------------------------------------------------

def test_thema_ranking_relation_und_titel_fallback():
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["a", "b", "c", "d"], "thema_relation": ["tA"]},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["a", "b"], "thema_relation": ["tA"]},
        # Keine Relation -> Fallback auf Titel.
        {"_id": "g3", "datum": "2024-01-15", "teilnehmer": ["a"], "thema_relation": None, "titel": "Spiele"},
    ]
    rows = {r["thema_key"]: r for r in thema_ranking(gruppenstunden)}
    assert rows["tA"]["thema_quelle"] == "relation"
    assert rows["tA"]["anzahl_stunden"] == 2
    assert rows["tA"]["schnitt_anwesend"] == 3.0  # (4+2)/2
    assert rows["Spiele"]["thema_quelle"] == "titel"
    assert rows["Spiele"]["schnitt_anwesend"] == 1.0


def test_thema_ranking_mehrere_relationen_zaehlen_je_id():
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["a", "b"], "thema_relation": ["tX", "tY"]},
    ]
    rows = {r["thema_key"]: r for r in thema_ranking(gruppenstunden)}
    assert rows["tX"]["anzahl_stunden"] == 1
    assert rows["tY"]["anzahl_stunden"] == 1
    assert rows["tX"]["schnitt_anwesend"] == 2.0


# ---------------------------------------------------------------------------
# KENNZAHL 6 - Lager-Korrelation
# ---------------------------------------------------------------------------

def test_lager_korrelation_teilnehmer_vs_rest():
    mitglieder = [
        {"_id": "m1", "name": "M1", "eintrittsdatum": "2024-01-01"},
        {"_id": "m2", "name": "M2", "eintrittsdatum": "2024-01-01"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1", "m2"]},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["m1"]},
    ]
    # m1 war im Lager, m2 nicht.
    lager = [{"_id": "l1", "datum": "2024-07-01", "teilnehmer": ["m1"]}]
    res = lager_korrelation(mitglieder, gruppenstunden, lager)
    assert res["lagerteilnehmer"]["anzahl"] == 1
    assert res["nicht_teilnehmer"]["anzahl"] == 1
    # m1: 100 %, m2: 50 %.
    assert res["lagerteilnehmer"]["schnitt_quote"] == 100.0
    assert res["nicht_teilnehmer"]["schnitt_quote"] == 50.0
    assert res["differenz"] == 50.0


# ---------------------------------------------------------------------------
# KENNZAHL 7 - Puenktlichkeit
# ---------------------------------------------------------------------------

def test_puenktlichkeit_vorhanden():
    mitglieder = [
        {"_id": "m1", "name": "M1"},
        {"_id": "m2", "name": "M2"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1", "m2"], "zu_spaet": ["m1"]},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["m1"], "zu_spaet": ["m1", "m2"]},
    ]
    res = puenktlichkeit(mitglieder, gruppenstunden)
    assert res["verfuegbar"] is True
    by_id = {r["mitglied_id"]: r for r in res["pro_mitglied"]}
    assert by_id["m1"]["verspaetungen"] == 2
    assert by_id["m2"]["verspaetungen"] == 1


def test_puenktlichkeit_nicht_brauchbar_uebersprungen():
    mitglieder = [{"_id": "m1", "name": "M1"}]
    for zs in (None, True, "ein paar kamen zu spaet"):
        gruppenstunden = [{"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1"], "zu_spaet": zs}]
        res = puenktlichkeit(mitglieder, gruppenstunden)
        assert res["verfuegbar"] is False
        assert res["pro_mitglied"] == []


# ---------------------------------------------------------------------------
# KENNZAHL 8 - Gesamtkennzahlen
# ---------------------------------------------------------------------------

def test_gesamtkennzahlen():
    mitglieder = [
        {"_id": "m1", "name": "M1"},
        {"_id": "m2", "name": "M2"},
        {"_id": "m3", "name": "M3", "ausgeschieden": True},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1", "m2"]},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["m1"]},
    ]
    lager = [{"_id": "l1", "datum": "2024-07-01", "teilnehmer": ["m1"]}]
    gk = gesamtkennzahlen(mitglieder, gruppenstunden, lager)
    assert gk["anzahl_mitglieder_gesamt"] == 3
    assert gk["anzahl_aktive_mitglieder"] == 2
    assert gk["anzahl_gruppenstunden"] == 2
    assert gk["anzahl_lager"] == 1
    assert gk["schnitt_anwesend_pro_stunde"] == 1.5  # (2+1)/2
    # Faire Gesamtquote = Durchschnitt der fairen Einzelquoten. Ohne Ein-/
    # Austrittsdaten zaehlen fuer jedes Mitglied beide Stunden als moeglich:
    # m1 100 %, m2 50 %, m3 0 % -> Durchschnitt 50 %.
    assert gk["gesamtbeteiligungsquote"] == 50.0
    # Ungewichtete Rohquote als bewusster Zusatz: 3 / (3 * 2) * 100 = 50 %.
    assert gk["gesamtbeteiligungsquote_roh"] == 50.0


def test_gesamtbeteiligungsquote_fair_vs_roh_bei_fluktuation():
    # Neuzugang "neu" tritt erst zur letzten Stunde ein. Die faire Quote darf
    # ihn nicht fuer fruehere Stunden bestrafen, die Rohquote hingegen schon.
    mitglieder = [
        {"_id": "alt", "name": "Alt", "eintrittsdatum": "2024-01-01"},
        {"_id": "neu", "name": "Neu", "eintrittsdatum": "2024-03-01"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-10", "teilnehmer": ["alt"]},
        {"_id": "g2", "datum": "2024-02-10", "teilnehmer": ["alt"]},
        {"_id": "g3", "datum": "2024-03-10", "teilnehmer": ["alt", "neu"]},
    ]
    gk = gesamtkennzahlen(mitglieder, gruppenstunden, [])
    # Fair: alt 100 % (3/3), neu 100 % (1/1 moeglich) -> Durchschnitt 100 %.
    assert gk["gesamtbeteiligungsquote"] == 100.0
    # Roh: 4 Anwesenheiten / (2 Mitglieder * 3 Stunden) * 100 = 66.67 %.
    assert gk["gesamtbeteiligungsquote_roh"] == 66.67


# ---------------------------------------------------------------------------
# ist_ausgeschieden / only_active_members
# ---------------------------------------------------------------------------

def test_ist_ausgeschieden_feld_und_datum():
    stichtag = date(2024, 6, 1)
    assert ist_ausgeschieden({"ausgeschieden": True}, stichtag) is True
    assert ist_ausgeschieden({"austrittsdatum": "2024-01-01"}, stichtag) is True
    assert ist_ausgeschieden({"austrittsdatum": "2030-01-01"}, stichtag) is False
    assert ist_ausgeschieden({}, stichtag) is False


def test_only_active_members_filtert_mitgliederbezogene_auswertungen():
    data = {
        "mitglieder": [
            {"_id": "m1", "name": "Aktiv", "eintrittsdatum": "2024-01-01"},
            {"_id": "m2", "name": "Weg", "eintrittsdatum": "2024-01-01", "ausgeschieden": True},
        ],
        "gruppenstunden": [
            {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1", "m2"]},
        ],
        "lager": [],
    }

    class _Analysis:
        only_active_members = True
        bundesland = ""

    class _Cfg:
        analysis = _Analysis()

    report = analyze(data, _Cfg())
    ids_top = {z["mitglied_id"] for z in report["top_flop_anwesenheit"]}
    ids_fair = {z["mitglied_id"] for z in report["faire_beteiligung"]}
    # Ausgeschiedenes m2 taucht in mitgliederbezogenen Auswertungen nicht auf.
    assert ids_top == {"m1"}
    assert ids_fair == {"m1"}
    # Gesamtkennzahlen bleiben auf voller Basis.
    assert report["gesamtkennzahlen"]["anzahl_mitglieder_gesamt"] == 2
    # Stundenbasierte Saisonalitaet unberuehrt (Stunde zaehlt beide Teilnehmer).
    monate = {m["monat"]: m for m in report["saisonalitaet"]["pro_monat"]}
    assert monate[1]["summe_anwesend"] == 2


def test_analyze_ohne_config_nutzt_defaults():
    data = {
        "mitglieder": [{"_id": "m1", "name": "M1", "eintrittsdatum": "2024-01-01", "ausgeschieden": True}],
        "gruppenstunden": [{"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1"]}],
        "lager": [],
    }
    report = analyze(data)
    # Default only_active_members=False -> ausgeschiedenes Mitglied bleibt drin.
    assert len(report["faire_beteiligung"]) == 1
    # Report muss JSON-serialisierbar sein.
    json.dumps(report)


# ---------------------------------------------------------------------------
# load_data
# ---------------------------------------------------------------------------

def test_load_data_ergaenzt_fehlende_schluessel(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"mitglieder": [{"_id": "m1"}]}), encoding="utf-8")
    data = load_data(str(p))
    assert data["mitglieder"] == [{"_id": "m1"}]
    assert data["gruppenstunden"] == []
    assert data["lager"] == []
