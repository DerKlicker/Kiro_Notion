"""Tests fuer das Auswertungs-Modul (Phase 2).

Die Fixtures sind synthetische dicts im internen Datenmodell (siehe fetch.py).
Es gibt keine Netz-/Notion-Abhaengigkeit. Jeder Test uebt die fachliche Logik
wirklich aus und schlaegt fehl, wenn die jeweilige Logik entfernt/reverted wird.
"""
import json
from datetime import date

import pytest

from vereinsstatistik.analysis import (
    BEREICH_STAMM_GRUPPENSTUNDE,
    RISIKO_FENSTER_N,
    analyze,
    faire_beteiligung,
    gesamtkennzahlen,
    ist_ausgeschieden,
    lager_korrelation,
    load_data,
    mitglieder_fuer_statistik,
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

def test_saisonalitaet_monat_und_ferien_uebersprungen():
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["a", "b"]},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["a"]},
        {"_id": "g3", "datum": "2024-03-05", "teilnehmer": ["a", "b", "c"]},
    ]
    res = saisonalitaet(gruppenstunden, bundesland="")
    monate = {m["monat"]: m for m in res["pro_monat"]}
    assert monate[1]["anzahl_stunden"] == 2
    assert monate[1]["summe_anwesend"] == 3
    assert monate[1]["schnitt_anwesend"] == 1.5
    assert monate[3]["summe_anwesend"] == 3

    # Eine Wochentags-Auswertung gibt es bewusst nicht mehr.
    assert "pro_wochentag" not in res
    # Ohne Bundesland wird die Ferien-Korrelation sauber uebersprungen.
    assert res["ferien_korrelation"] is None


# ---------------------------------------------------------------------------
# KENNZAHL 5 - Thema-Ranking
# ---------------------------------------------------------------------------

def test_thema_ranking_lesbarer_name_aus_rollup():
    # Normalfall: lesbarer Name aus dem Rollup "Grafana_Name" (Feld thema_name).
    # Trotz vorhandener thema_relation wird der Name bevorzugt.
    gruppenstunden = [
        {
            "_id": "g1",
            "datum": "2024-01-01",
            "teilnehmer": ["a", "b", "c", "d"],
            "thema_relation": ["tA"],
            "thema_name": ["Lagerfeuer"],
        },
        {
            "_id": "g2",
            "datum": "2024-01-08",
            "teilnehmer": ["a", "b"],
            "thema_relation": ["tA"],
            "thema_name": "Lagerfeuer",  # auch als einzelner String robust
        },
    ]
    rows = {r["thema_key"]: r for r in thema_ranking(gruppenstunden)}
    assert "Lagerfeuer" in rows
    assert rows["Lagerfeuer"]["thema_quelle"] == "name"
    assert rows["Lagerfeuer"]["anzahl_stunden"] == 2
    assert rows["Lagerfeuer"]["schnitt_anwesend"] == 3.0  # (4+2)/2
    # Die Page-ID taucht nicht als Schluessel auf, wenn ein Name existiert.
    assert "tA" not in rows


def test_thema_ranking_fallback_relation_dann_titel():
    gruppenstunden = [
        # thema_name leer -> Fallback auf relation.
        {"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["a", "b", "c", "d"], "thema_relation": ["tA"], "thema_name": []},
        {"_id": "g2", "datum": "2024-01-08", "teilnehmer": ["a", "b"], "thema_relation": ["tA"]},
        # Weder Name noch Relation -> Fallback auf Titel.
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
    assert gk["anzahl_mitglieder_statistik"] == 2  # m3 (ausgeschieden) faellt raus
    assert gk["anzahl_gruppenstunden"] == 2
    assert gk["anzahl_lager"] == 1
    assert gk["schnitt_anwesend_pro_stunde"] == 1.5  # (2+1)/2 - stundenbasiert, alle
    # Beteiligungsquoten rechnen NUR ueber die Statistik-Mitglieder (m1, m2);
    # das ausgeschiedene m3 (0 %) drueckt die Quote nicht mehr.
    # m1 100 %, m2 50 % -> Durchschnitt 75 %.
    assert gk["gesamtbeteiligungsquote"] == 75.0
    # Ungewichtete Rohquote auf Statistik-Basis: Anwesenheiten von m1,m2 = 3;
    # Nenner 2 Mitglieder * 2 Stunden = 4 -> 3/4*100 = 75 %.
    assert gk["gesamtbeteiligungsquote_roh"] == 75.0


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


def test_analyze_filtert_ausgeschiedene_immer():
    # Ausgeschiedene werden jetzt generell aus den mitgliederbezogenen
    # Auswertungen entfernt (unabhaengig von einer Config-Option).
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

    report = analyze(data)
    # Mit der Jahres-Dimension tragen die Zeilen ein Feld ``jahr``; das
    # "alle Jahre"-Aggregat (jahr is None) entspricht dem bisherigen Ergebnis.
    top_alle = [z for z in report["top_flop_anwesenheit"] if z.get("jahr") is None]
    fair_alle = [z for z in report["faire_beteiligung"] if z.get("jahr") is None]
    ids_top = {z["mitglied_id"] for z in top_alle}
    ids_fair = {z["mitglied_id"] for z in fair_alle}
    # Ausgeschiedenes m2 taucht in mitgliederbezogenen Auswertungen nicht auf.
    assert ids_top == {"m1"}
    assert ids_fair == {"m1"}
    # _meta weist die gefilterte Statistik-Basis separat aus.
    assert report["_meta"]["anzahl_mitglieder"] == 2
    assert report["_meta"]["anzahl_mitglieder_statistik"] == 1
    # Gesamtkennzahlen bleiben auf voller Basis (alle Jahre-Aggregat).
    gk_alle = [g for g in report["gesamtkennzahlen"] if g.get("jahr") is None]
    assert gk_alle[0]["anzahl_mitglieder_gesamt"] == 2
    # Stundenbasierte Saisonalitaet unberuehrt (Stunde zaehlt beide Teilnehmer).
    monate = {
        m["monat"]: m
        for m in report["saisonalitaet"]["pro_monat"]
        if m.get("jahr") is None
    }
    assert monate[1]["summe_anwesend"] == 2


def test_gesamtbeteiligungsquote_nur_statistik_mitglieder():
    """Vereinsmitglieder ohne Gruppenstunden-Bezug duerfen die Quote nicht druecken.

    Bildet das reale Problem ab: viele Karteileichen (Bereich/Stamm !=
    "Gruppenstunde"), die nie an Gruppenstunden teilnehmen, zogen die
    Gesamtbeteiligungsquote kuenstlich nach unten (~16 %). Erwartet: Die Quote
    rechnet nur ueber die Statistik-Mitglieder (hier m1, 100 %), die Nicht-
    Gruppenstunden-Mitglieder (m2..m5) bleiben aussen vor.
    """
    mitglieder = [
        {"_id": "m1", "name": "Aktiv", "bereich_stamm": "Gruppenstunde",
         "eintrittsdatum": "2024-01-01"},
    ] + [
        {"_id": f"k{i}", "name": f"Karteileiche {i}", "bereich_stamm": "Intern Stamm",
         "eintrittsdatum": "2024-01-01"}
        for i in range(4)
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-02-01", "teilnehmer": ["m1"]},
        {"_id": "g2", "datum": "2024-03-01", "teilnehmer": ["m1"]},
    ]

    report = analyze({"mitglieder": mitglieder, "gruppenstunden": gruppenstunden, "lager": []})
    gk_liste = [g for g in report["gesamtkennzahlen"] if g.get("jahr") is None]
    gk = gk_liste[0]

    # Nur m1 zaehlt zur Statistik; er war bei beiden moeglichen Stunden da -> 100 %.
    assert gk["anzahl_mitglieder_gesamt"] == 5
    assert gk["anzahl_mitglieder_statistik"] == 1
    assert gk["gesamtbeteiligungsquote"] == 100.0
    assert gk["gesamtbeteiligungsquote_roh"] == 100.0


def test_analyze_ohne_config_serialisierbar_und_filtert():
    data = {
        "mitglieder": [{"_id": "m1", "name": "M1", "eintrittsdatum": "2024-01-01", "ausgeschieden": True}],
        "gruppenstunden": [{"_id": "g1", "datum": "2024-01-01", "teilnehmer": ["m1"]}],
        "lager": [],
    }
    report = analyze(data)
    # Ausgeschiedenes Mitglied wird generell herausgefiltert.
    assert report["faire_beteiligung"] == []
    # Report muss JSON-serialisierbar sein.
    json.dumps(report)


# ---------------------------------------------------------------------------
# Mitglieder-Filter fuer die Statistik (ausgeschieden + Bereich/Stamm)
# ---------------------------------------------------------------------------

def test_mitglieder_filter_bereich_stamm_nur_gruppenstunde():
    mitglieder = [
        {"_id": "m1", "name": "A", "bereich_stamm": BEREICH_STAMM_GRUPPENSTUNDE},
        {"_id": "m2", "name": "B", "bereich_stamm": "Intern Stamm"},
        {"_id": "m3", "name": "C", "bereich_stamm": None},
        {"_id": "m4", "name": "D", "bereich_stamm": "Gruppenstunde"},
    ]
    ids = {m["_id"] for m in mitglieder_fuer_statistik(mitglieder)}
    # Nur Mitglieder mit Bereich/Stamm == "Gruppenstunde".
    assert ids == {"m1", "m4"}


def test_mitglieder_filter_ausgeschieden_greift_immer():
    mitglieder = [
        {"_id": "m1", "name": "A", "bereich_stamm": "Gruppenstunde"},
        {"_id": "m2", "name": "B", "bereich_stamm": "Gruppenstunde", "ausgeschieden": True},
        {"_id": "m3", "name": "C", "bereich_stamm": "Gruppenstunde", "austrittsdatum": "2000-01-01"},
    ]
    ids = {m["_id"] for m in mitglieder_fuer_statistik(mitglieder, stichtag=date(2024, 6, 1))}
    # Ausgeschiedene (Feld bzw. vergangenes Austrittsdatum) fallen immer raus.
    assert ids == {"m1"}


def test_mitglieder_filter_bereich_stamm_fallback_wenn_ungepflegt():
    # Spalte Bereich/Stamm (noch) ungepflegt: alle Werte leer/None. Dann darf
    # der Filter NICHT die ganze Liste leeren - er wird uebersprungen.
    mitglieder = [
        {"_id": "m1", "name": "A"},
        {"_id": "m2", "name": "B", "bereich_stamm": None},
        {"_id": "m3", "name": "C", "bereich_stamm": ""},
        {"_id": "m4", "name": "D", "ausgeschieden": True},
    ]
    ids = {m["_id"] for m in mitglieder_fuer_statistik(mitglieder)}
    # Bereich/Stamm-Filter uebersprungen, aber ausgeschiedenes m4 faellt raus.
    assert ids == {"m1", "m2", "m3"}


def test_mitglieder_filter_bereich_stamm_greift_sobald_gepflegt():
    # Sobald mindestens ein Mitglied einen Bereich/Stamm-Wert hat, greift der
    # Filter normal - auch die leeren fallen dann raus.
    mitglieder = [
        {"_id": "m1", "name": "A", "bereich_stamm": "Gruppenstunde"},
        {"_id": "m2", "name": "B", "bereich_stamm": None},
        {"_id": "m3", "name": "C"},
    ]
    ids = {m["_id"] for m in mitglieder_fuer_statistik(mitglieder)}
    assert ids == {"m1"}


def test_mitglieder_filter_bereich_stamm_als_liste():
    # Notion kann einen Select-Wert als Liste liefern - robust behandeln.
    mitglieder = [
        {"_id": "m1", "name": "A", "bereich_stamm": ["Gruppenstunde"]},
        {"_id": "m2", "name": "B", "bereich_stamm": ["Intern Stamm"]},
    ]
    ids = {m["_id"] for m in mitglieder_fuer_statistik(mitglieder)}
    assert ids == {"m1"}


# ---------------------------------------------------------------------------
# Moegliche Stunden variieren mit dem Eintrittsdatum (nicht fuer alle gleich)
# ---------------------------------------------------------------------------

def test_moegliche_stunden_variieren_mit_eintrittsdatum():
    # Vier Stunden ueber vier Monate; drei Mitglieder mit unterschiedlichem
    # Eintrittsdatum muessen UNTERSCHIEDLICH viele moegliche Stunden haben.
    mitglieder = [
        {"_id": "frueh", "name": "Frueh", "eintrittsdatum": "2023-12-01"},
        {"_id": "mitte", "name": "Mitte", "eintrittsdatum": "2024-02-15"},
        {"_id": "spaet", "name": "Spaet", "eintrittsdatum": "2024-04-01"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-10", "teilnehmer": []},
        {"_id": "g2", "datum": "2024-02-10", "teilnehmer": []},
        {"_id": "g3", "datum": "2024-03-10", "teilnehmer": []},
        {"_id": "g4", "datum": "2024-04-10", "teilnehmer": []},
    ]
    rows = {r["mitglied_id"]: r for r in faire_beteiligung(mitglieder, gruppenstunden)}
    # Frueh: alle vier moeglich. Mitte: nur ab Maerz (g3, g4). Spaet: nur g4.
    assert rows["frueh"]["moegliche_stunden"] == 4
    assert rows["mitte"]["moegliche_stunden"] == 2
    assert rows["spaet"]["moegliche_stunden"] == 1
    # Die Werte duerfen gerade NICHT alle gleich sein.
    werte = {rows[mid]["moegliche_stunden"] for mid in ("frueh", "mitte", "spaet")}
    assert len(werte) == 3


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
