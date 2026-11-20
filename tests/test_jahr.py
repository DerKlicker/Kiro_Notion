"""Tests fuer die Jahres-Dimension der Kennzahlen.

Die Jahres-Dimension fuegt den betroffenen Kennzahlen (Top/Flop-Anwesenheit,
faire Beteiligung, Gesamtkennzahlen, Thema-Ranking, Saisonalitaet pro Monat)
pro vorkommendem Kalenderjahr einen Satz Zeilen hinzu PLUS ein Aggregat
"alle Jahre" (Sentinel ``jahr=None``, in der DB SQL NULL). Diese Tests nutzen
synthetische Fixtures mit Stunden ueber mehrere Jahre und schlagen fehl, wenn
die Jahres-Logik entfernt oder falsch berechnet wird.
"""
from vereinsstatistik.analysis import (
    JAHR_ALLE,
    analyze,
    faire_beteiligung,
    gesamtkennzahlen,
    saisonalitaet,
    thema_ranking,
    top_flop_anwesenheit,
    vorkommende_jahre,
)


def _daten_mehrere_jahre():
    """Zwei Mitglieder, Stunden in 2023 und 2024.

    2023: g1 (m1, m2), g2 (m1)      -> m1 2x, m2 1x
    2024: g3 (m2), g4 (m2), g5 (m1) -> m2 2x, m1 1x
    Dadurch wird 2023 von m1 angefuehrt, 2024 von m2 ("jedes Jahr ein anderer").
    """
    return {
        "mitglieder": [
            {"_id": "m1", "name": "Anna", "bereich_stamm": "Gruppenstunde", "eintrittsdatum": "2023-01-01"},
            {"_id": "m2", "name": "Bernd", "bereich_stamm": "Gruppenstunde", "eintrittsdatum": "2023-01-01"},
        ],
        "gruppenstunden": [
            {"_id": "g1", "datum": "2023-01-07", "titel": "Spiele", "teilnehmer": ["m1", "m2"], "thema_name": ["Spiele"]},
            {"_id": "g2", "datum": "2023-02-04", "titel": "Basteln", "teilnehmer": ["m1"], "thema_name": ["Basteln"]},
            {"_id": "g3", "datum": "2024-01-06", "titel": "Spiele", "teilnehmer": ["m2"], "thema_name": ["Spiele"]},
            {"_id": "g4", "datum": "2024-02-03", "titel": "Spiele", "teilnehmer": ["m2"], "thema_name": ["Spiele"]},
            {"_id": "g5", "datum": "2024-03-02", "titel": "Basteln", "teilnehmer": ["m1"], "thema_name": ["Basteln"]},
        ],
        "lager": [],
    }


# ---------------------------------------------------------------------------
# vorkommende_jahre
# ---------------------------------------------------------------------------

def test_vorkommende_jahre_kalenderjahr_aus_datum():
    gruppenstunden = [
        {"_id": "a", "datum": "2023-01-07"},
        {"_id": "b", "datum": "2024-12-31"},
        {"_id": "c", "datum": "2024-01-01"},
        {"_id": "d", "datum": None},  # ohne Datum -> ignoriert
        {"_id": "e", "datum": "2022-06-15", "jahr": 1999},  # Feld 'jahr' wird NICHT genutzt
    ]
    assert vorkommende_jahre(gruppenstunden) == [2022, 2023, 2024]


# ---------------------------------------------------------------------------
# Top/Flop je Jahr: unterschiedliche Sieger
# ---------------------------------------------------------------------------

def test_top_flop_unterschiedliche_sieger_je_jahr():
    daten = _daten_mehrere_jahre()
    mitglieder = daten["mitglieder"]
    gruppenstunden = daten["gruppenstunden"]

    tf_2023 = {z["mitglied_id"]: z for z in top_flop_anwesenheit(mitglieder, gruppenstunden, jahr=2023)}
    tf_2024 = {z["mitglied_id"]: z for z in top_flop_anwesenheit(mitglieder, gruppenstunden, jahr=2024)}

    # 2023 fuehrt m1 (2 Teilnahmen vor m2s 1).
    assert tf_2023["m1"]["anwesend_absolut"] == 2
    assert tf_2023["m2"]["anwesend_absolut"] == 1
    assert tf_2023["m1"]["rang"] == 1
    # 2024 fuehrt m2 (2 Teilnahmen vor m1s 1) -> anderer "Gekroenter".
    assert tf_2024["m2"]["anwesend_absolut"] == 2
    assert tf_2024["m1"]["anwesend_absolut"] == 1
    assert tf_2024["m2"]["rang"] == 1

    # "alle Jahre": beide 3 Teilnahmen -> gleicher Rang 1.
    tf_alle = {z["mitglied_id"]: z for z in top_flop_anwesenheit(mitglieder, gruppenstunden, jahr=JAHR_ALLE)}
    assert tf_alle["m1"]["anwesend_absolut"] == 3
    assert tf_alle["m2"]["anwesend_absolut"] == 3


# ---------------------------------------------------------------------------
# Faire Jahresquote: Eintritt mitten im Jahr -> anteilige moegliche Stunden
# ---------------------------------------------------------------------------

def test_faire_jahresquote_eintritt_mitten_im_jahr_anteilig():
    mitglieder = [
        {"_id": "m1", "name": "Alt", "bereich_stamm": "Gruppenstunde", "eintrittsdatum": "2023-01-01"},
        # m2 tritt mitten in 2024 ein -> nur Stunden ab Maerz 2024 sind moeglich.
        {"_id": "m2", "name": "Neu", "bereich_stamm": "Gruppenstunde", "eintrittsdatum": "2024-03-01"},
    ]
    gruppenstunden = [
        {"_id": "g1", "datum": "2024-01-10", "teilnehmer": ["m1"]},
        {"_id": "g2", "datum": "2024-02-10", "teilnehmer": ["m1"]},
        {"_id": "g3", "datum": "2024-03-10", "teilnehmer": ["m1", "m2"]},
        {"_id": "g4", "datum": "2024-04-10", "teilnehmer": ["m2"]},
    ]
    rows_2024 = {r["mitglied_id"]: r for r in faire_beteiligung(mitglieder, gruppenstunden, jahr=2024)}

    # m1: alle 4 Stunden 2024 moeglich, bei 3 anwesend -> 75 %.
    assert rows_2024["m1"]["moegliche_stunden"] == 4
    assert rows_2024["m1"]["anwesend"] == 3
    assert rows_2024["m1"]["quote_prozent"] == 75.0

    # m2: nur g3 und g4 moeglich (ab Eintritt 01.03.2024), beide anwesend -> 100 %.
    # Entscheidend: m2 wird NICHT fuer g1/g2 vor seinem Eintritt bestraft.
    assert rows_2024["m2"]["moegliche_stunden"] == 2
    assert rows_2024["m2"]["anwesend"] == 2
    assert rows_2024["m2"]["quote_prozent"] == 100.0


# ---------------------------------------------------------------------------
# Gesamtkennzahlen je Jahr
# ---------------------------------------------------------------------------

def test_gesamtkennzahlen_je_jahr_stundenbezug():
    daten = _daten_mehrere_jahre()
    mitglieder = daten["mitglieder"]
    gruppenstunden = daten["gruppenstunden"]

    gk_2023 = gesamtkennzahlen(mitglieder, gruppenstunden, [], jahr=2023)
    gk_2024 = gesamtkennzahlen(mitglieder, gruppenstunden, [], jahr=2024)
    gk_alle = gesamtkennzahlen(mitglieder, gruppenstunden, [], jahr=JAHR_ALLE)

    # 2023: 2 Stunden; 2024: 3 Stunden; alle: 5.
    assert gk_2023["anzahl_gruppenstunden"] == 2
    assert gk_2024["anzahl_gruppenstunden"] == 3
    assert gk_alle["anzahl_gruppenstunden"] == 5

    # Mitgliederzahlen bleiben die vereinsweite Basis, nicht jahresabhaengig.
    assert gk_2023["anzahl_mitglieder_gesamt"] == gk_alle["anzahl_mitglieder_gesamt"] == 2


# ---------------------------------------------------------------------------
# Saisonalitaet je Jahr + "alle Jahre"-Aggregat
# ---------------------------------------------------------------------------

def test_saisonalitaet_je_jahr_und_alle_jahre():
    daten = _daten_mehrere_jahre()
    gruppenstunden = daten["gruppenstunden"]

    jan_2023 = {m["monat"]: m for m in saisonalitaet(gruppenstunden, jahr=2023)["pro_monat"]}
    jan_2024 = {m["monat"]: m for m in saisonalitaet(gruppenstunden, jahr=2024)["pro_monat"]}
    alle = {m["monat"]: m for m in saisonalitaet(gruppenstunden, jahr=JAHR_ALLE)["pro_monat"]}

    # Januar 2023: g1 mit 2 Teilnehmern -> Schnitt 2.0.
    assert jan_2023[1]["anzahl_stunden"] == 1
    assert jan_2023[1]["schnitt_anwesend"] == 2.0
    # Januar 2024: g3 mit 1 Teilnehmer -> Schnitt 1.0.
    assert jan_2024[1]["schnitt_anwesend"] == 1.0
    # "alle Jahre" Januar: g1 (2) und g3 (1) -> (2+1)/2 = 1.5.
    assert alle[1]["anzahl_stunden"] == 2
    assert alle[1]["schnitt_anwesend"] == 1.5


# ---------------------------------------------------------------------------
# "alle Jahre"-Aggregat entspricht der bisherigen Gesamtauswertung
# ---------------------------------------------------------------------------

def test_alle_jahre_aggregat_entspricht_ungefiltert():
    daten = _daten_mehrere_jahre()
    mitglieder = daten["mitglieder"]
    gruppenstunden = daten["gruppenstunden"]

    # Top/Flop: jahr=None muss dem ungefilterten Aufruf entsprechen.
    assert top_flop_anwesenheit(mitglieder, gruppenstunden, jahr=JAHR_ALLE) == \
        top_flop_anwesenheit(mitglieder, gruppenstunden)
    # Faire Beteiligung: jahr=None == ungefiltert.
    assert faire_beteiligung(mitglieder, gruppenstunden, jahr=JAHR_ALLE) == \
        faire_beteiligung(mitglieder, gruppenstunden)
    # Thema-Ranking: jahr=None == ungefiltert.
    assert thema_ranking(gruppenstunden, jahr=JAHR_ALLE) == thema_ranking(gruppenstunden)
    # Saisonalitaet pro Monat: jahr=None == ungefiltert.
    assert saisonalitaet(gruppenstunden, jahr=JAHR_ALLE)["pro_monat"] == \
        saisonalitaet(gruppenstunden)["pro_monat"]
    # Gesamtkennzahlen: jahr=None == ungefiltert.
    assert gesamtkennzahlen(mitglieder, gruppenstunden, [], jahr=JAHR_ALLE) == \
        gesamtkennzahlen(mitglieder, gruppenstunden, [])


# ---------------------------------------------------------------------------
# analyze(): Jahres-Dimension im Report-dict
# ---------------------------------------------------------------------------

def test_analyze_report_traegt_jahres_dimension():
    report = analyze(_daten_mehrere_jahre())

    # _meta listet die vorkommenden Jahre auf.
    assert report["_meta"]["jahre"] == [2023, 2024]

    # Jede Top/Flop-Zeile traegt ein Feld 'jahr' (None oder konkretes Jahr).
    jahre_tf = {z["jahr"] for z in report["top_flop_anwesenheit"]}
    assert jahre_tf == {None, 2023, 2024}

    # Das "alle Jahre"-Aggregat der fairen Beteiligung deckt beide Mitglieder ab.
    report_alle = [z for z in report["faire_beteiligung"] if z["jahr"] is None]
    ids = {z["mitglied_id"] for z in report_alle}
    assert ids == {"m1", "m2"}

    # Gesamtkennzahlen: genau eine Aggregat-Zeile plus je Jahr eine Zeile.
    gk = report["gesamtkennzahlen"]
    gk_jahre = sorted(
        (g["jahr"] for g in gk), key=lambda j: (j is not None, j)
    )
    assert gk_jahre == [None, 2023, 2024]

    # Risiko/Dropout bleibt ohne Jahres-Dimension (keine 'jahr'-Felder).
    assert all("jahr" not in z for z in report["risiko_score"])
