"""Auswertung der Vereinsdaten (Phase 2).

Dieses Modul berechnet aus dem ``fetch_all``-Output (oder aus einem per
``cli fetch --out`` gespeicherten JSON) eine Reihe von Kennzahlen. Es arbeitet
bewusst nur mit der Standardbibliothek und ohne Netz-/Notion-Zugriff, damit die
Auswertung auch im Sandbox-/Offline-Betrieb aus gespeicherten Daten laeuft.

Entwurfsgrundsaetze:

* Reine, einzeln testbare Funktionen. Jede Kennzahl hat ihre eigene Funktion
  und gibt eine flache, tabellenartige Struktur (Listen von dicts bzw. dicts)
  zurueck. Diese sind JSON-serialisierbar, damit Phase 3 sie leicht nach
  PostgreSQL ueberfuehren kann.
* Defensiver Umgang mit fehlenden optionalen Feldern. Weder ``zu_spaet=None``
  noch ein leeres ``thema_relation``, ein fehlendes ``austrittsdatum`` oder ein
  nicht gesetztes ``bundesland`` duerfen zum Absturz fuehren. Es wird sauber
  uebersprungen bzw. ein Fallback genutzt.
* Fachliche Annahmen sind als benannte Konstanten mit Begruendung im Docstring
  hinterlegt, damit der Verein sie leicht anpassen kann.

Internes Datenmodell (siehe fetch.py / config.example.yaml):

* mitglieder:     name, spitzname, eintrittsdatum, austrittsdatum, ausgeschieden,
                  geburtsdatum, geschlecht, sippe, stufe, _id
* gruppenstunden: titel, datum, teilnehmer (Liste Mitglieder-IDs),
                  thema_relation (Liste IDs), zu_spaet (unbekannte Struktur),
                  jahr (optional), _id
* lager:          name, datum, teilnehmer (Liste Mitglieder-IDs),
                  teilnehmeranzahl, hat_stattgefunden, standort, motto, _id

Die Anwesenheit wird ueber die ``teilnehmer``-Listen (Mitglieder-Page-IDs)
gegen ``mitglieder[*]["_id"]`` hergestellt.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from statistics import mean
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Fachliche Konstanten (bewusst benannt und dokumentiert, leicht anpassbar)
# ---------------------------------------------------------------------------

# Anzahl der zuletzt stattgefundenen Gruppenstunden, die das "Risiko-Fenster"
# bilden. 5 ist ein nachvollziehbarer Default: genug, um einen Trend zu sehen,
# aber kurz genug, um auf aktuelle Veraenderungen zu reagieren.
RISIKO_FENSTER_N = 5

# Schwellen fuer die Risiko-Stufe anhand des Risiko-Scores (0.0 bis 1.0).
# Unter NIEDRIG -> "niedrig", bis HOCH -> "mittel", darueber -> "hoch".
RISIKO_SCHWELLE_NIEDRIG = 0.34
RISIKO_SCHWELLE_HOCH = 0.67

# Gewichtung der beiden Risiko-Komponenten im Gesamtscore. Der Abfall der
# Anwesenheitsquote (letzte N vs. davor) und die Dauer seit der letzten
# Anwesenheit werden je zur Haelfte gewichtet. Summe = 1.0.
RISIKO_GEWICHT_ABFALL = 0.5
RISIKO_GEWICHT_ABWESENHEIT = 0.5

# Ab wie vielen Stunden ohne Anwesenheit die Abwesenheits-Komponente ihren
# Maximalwert (1.0) erreicht. Nach RISIKO_FENSTER_N verpassten Stunden gilt ein
# Mitglied als vollstaendig abwesend im Sinne dieser Komponente.
RISIKO_ABWESENHEIT_MAX = RISIKO_FENSTER_N


# ---------------------------------------------------------------------------
# Laden / Einstieg
# ---------------------------------------------------------------------------

def load_data(path: str) -> Dict[str, Any]:
    """Ein per ``cli fetch --out`` erzeugtes JSON einlesen.

    Gibt das dict mit den Schluesseln mitglieder/gruppenstunden/lager/_meta
    zurueck. Fehlen einzelne Schluessel, werden sie als leere Listen ergaenzt,
    damit die Auswertung nie an fehlenden Datentoepfen scheitert.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("mitglieder", "gruppenstunden", "lager"):
        data.setdefault(key, [])
    return data


def parse_date(s: Any) -> Optional[date]:
    """ISO-Datums-String robust in ein ``datetime.date`` parsen.

    Akzeptiert reine Datumsangaben ('2026-03-01') ebenso wie Zeitstempel mit
    Uhrzeit und Zeitzone ('2026-03-01T10:00:00+02:00'). Bei None, leerem oder
    ungueltigem Wert wird None zurueckgegeben - es wird nie eine Exception
    geworfen.
    """
    if not s or not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None
    # Zeitteil abschneiden, falls vorhanden ('T' oder Leerzeichen als Trenner).
    for sep in ("T", "t", " "):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        # Letzter Versuch ueber den vollstaendigen String (z. B. Zeitzonen).
        try:
            return datetime.fromisoformat(s).date()
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Gemeinsame Helfer
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    """Ein (evtl. None) Feld robust als Liste liefern."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _display_name(m: Dict[str, Any]) -> str:
    """Anzeigename eines Mitglieds (Spitzname bevorzugt, sonst Name)."""
    return m.get("spitzname") or m.get("name") or m.get("_id") or "(unbekannt)"


def build_member_lookup(mitglieder: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Lookup _id -> Mitglieds-dict aufbauen (Mitglieder ohne _id ueberspringen)."""
    lookup: Dict[str, Dict[str, Any]] = {}
    for m in mitglieder or []:
        mid = m.get("_id")
        if mid:
            lookup[mid] = m
    return lookup


def ist_ausgeschieden(m: Dict[str, Any], stichtag: Optional[date] = None) -> bool:
    """Ob ein Mitglied als ausgeschieden gilt.

    Grundlage ist das Feld ``ausgeschieden`` (bool) ODER ein ``austrittsdatum``,
    das am Stichtag (Default: heute) bereits in der Vergangenheit liegt.
    """
    if m.get("ausgeschieden") is True:
        return True
    austritt = parse_date(m.get("austrittsdatum"))
    if austritt is not None:
        ref = stichtag or date.today()
        if austritt <= ref:
            return True
    return False


def _teilnehmer_ids(datensatz: Dict[str, Any]) -> List[str]:
    """Teilnehmer-IDs einer Gruppenstunde/eines Lagers robust als Liste."""
    return [t for t in _as_list(datensatz.get("teilnehmer")) if isinstance(t, str)]


def _stunden_jahr(stunde: Dict[str, Any]) -> Optional[int]:
    """Jahr einer Gruppenstunde bestimmen (Feld 'jahr' bevorzugt, sonst Datum)."""
    jahr = stunde.get("jahr")
    if isinstance(jahr, (int, float)) and not isinstance(jahr, bool):
        return int(jahr)
    d = parse_date(stunde.get("datum"))
    return d.year if d else None


def _aktive_mitglieder(
    mitglieder: List[Dict[str, Any]], only_active: bool, stichtag: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Mitgliederliste ggf. auf nicht-ausgeschiedene filtern."""
    if not only_active:
        return list(mitglieder or [])
    return [m for m in (mitglieder or []) if not ist_ausgeschieden(m, stichtag)]


# ---------------------------------------------------------------------------
# KENNZAHL 1 - Top/Flop-Anwesenheit (absolute Teilnahmen)
# ---------------------------------------------------------------------------

def top_flop_anwesenheit(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
    jahr: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Absolute Anzahl Gruppenstunden-Teilnahmen pro Mitglied mit Rang.

    Optional nach ``jahr`` filterbar (Jahr des Datums bzw. Feld 'jahr'). Der Rang
    ist ein dichter Rang (dense rank): gleiche Anwesenheit -> gleicher Rang, der
    naechste Rang folgt lueckenlos. Hoechste Anwesenheit = Rang 1.

    Rueckgabe: Liste flacher dicts
    {mitglied_id, name, anwesend_absolut, rang}, absteigend nach Anwesenheit.
    """
    stunden = gruppenstunden or []
    if jahr is not None:
        stunden = [s for s in stunden if _stunden_jahr(s) == jahr]

    zaehler: Dict[str, int] = {m.get("_id"): 0 for m in mitglieder or [] if m.get("_id")}
    for s in stunden:
        for mid in _teilnehmer_ids(s):
            if mid in zaehler:
                zaehler[mid] += 1

    zeilen = [
        {
            "mitglied_id": m.get("_id"),
            "name": _display_name(m),
            "anwesend_absolut": zaehler.get(m.get("_id"), 0),
        }
        for m in mitglieder or []
        if m.get("_id")
    ]
    zeilen.sort(key=lambda z: (-z["anwesend_absolut"], z["name"]))

    # Dichten Rang vergeben.
    letzter_wert: Optional[int] = None
    rang = 0
    for z in zeilen:
        if z["anwesend_absolut"] != letzter_wert:
            rang += 1
            letzter_wert = z["anwesend_absolut"]
        z["rang"] = rang
    return zeilen


# ---------------------------------------------------------------------------
# KENNZAHL 2 - Faire relative Beteiligung
# ---------------------------------------------------------------------------

def _moegliche_stunden_fuer(
    m: Dict[str, Any], stunden_mit_datum: List[Dict[str, Any]], max_datum: Optional[date]
) -> List[Dict[str, Any]]:
    """Gruppenstunden, die im aktiven Zeitraum eines Mitglieds liegen.

    Aktiver Zeitraum = von ``eintrittsdatum`` (falls gesetzt, sonst ab erster
    Stunde) bis ``austrittsdatum`` (falls gesetzt, sonst bis ``max_datum`` =
    letzte vorhandene Gruppenstunde). So werden Neuzugaenge nicht benachteiligt:
    Stunden vor ihrem Eintritt zaehlen gar nicht als "moeglich".
    """
    eintritt = parse_date(m.get("eintrittsdatum"))
    austritt = parse_date(m.get("austrittsdatum"))
    ende = austritt if austritt is not None else max_datum

    passend = []
    for s, d in stunden_mit_datum:
        if eintritt is not None and d < eintritt:
            continue
        if ende is not None and d > ende:
            continue
        passend.append(s)
    return passend


def faire_beteiligung(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Faire relative Beteiligungsquote pro Mitglied.

    Pro Mitglied werden nur die Gruppenstunden gezaehlt, deren Datum im aktiven
    Zeitraum des Mitglieds liegt (Eintritt bis Austritt bzw. letzte Stunde).
    Quote = anwesend_im_zeitraum / moegliche_stunden_im_zeitraum * 100.

    Umgang mit 0 moeglichen Stunden: Die Quote ist dann ``None`` (nicht 0.0),
    weil ein Mitglied ohne moegliche Stunden fachlich nicht bewertbar ist und
    nicht faelschlich als "0 % Beteiligung" erscheinen soll.

    Rueckgabe: Liste flacher dicts
    {mitglied_id, name, moegliche_stunden, anwesend, quote_prozent}.
    """
    stunden_mit_datum = [
        (s, parse_date(s.get("datum"))) for s in gruppenstunden or []
    ]
    stunden_mit_datum = [(s, d) for s, d in stunden_mit_datum if d is not None]
    max_datum = max((d for _, d in stunden_mit_datum), default=None)

    ergebnis = []
    for m in mitglieder or []:
        if not m.get("_id"):
            continue
        mid = m["_id"]
        moegliche = _moegliche_stunden_fuer(m, stunden_mit_datum, max_datum)
        anwesend = sum(1 for s in moegliche if mid in _teilnehmer_ids(s))
        anzahl_moeglich = len(moegliche)
        if anzahl_moeglich == 0:
            quote = None
        else:
            quote = round(anwesend / anzahl_moeglich * 100, 2)
        ergebnis.append(
            {
                "mitglied_id": mid,
                "name": _display_name(m),
                "moegliche_stunden": anzahl_moeglich,
                "anwesend": anwesend,
                "quote_prozent": quote,
            }
        )
    return ergebnis


# ---------------------------------------------------------------------------
# KENNZAHL 3 - Risiko-/Dropout-Score
# ---------------------------------------------------------------------------

def _risiko_stufe(score: Optional[float]) -> str:
    """Score (0.0 bis 1.0) in eine Stufe uebersetzen.

    Ist der Score ``None`` (keine aktiven Stunden, nicht bewertbar), lautet die
    Stufe ``"unbekannt"`` - so wird dieser Fall klar vom echten Nullrisiko
    ("niedrig") unterschieden.
    """
    if score is None:
        return "unbekannt"
    if score < RISIKO_SCHWELLE_NIEDRIG:
        return "niedrig"
    if score <= RISIKO_SCHWELLE_HOCH:
        return "mittel"
    return "hoch"


def risiko_score(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Dropout-Risiko pro Mitglied schaetzen.

    Nur Gruppenstunden im aktiven Zeitraum des Mitglieds (Eintritt bis Austritt
    bzw. letzte Stunde) werden beruecksichtigt. Diese werden chronologisch
    sortiert. Zwei Komponenten bilden den Score:

    * Abfall-Komponente: Anwesenheitsquote der letzten ``RISIKO_FENSTER_N``
      Stunden im Vergleich zur Quote der Stunden davor. Ein Rueckgang zaehlt als
      Risiko (positiver Abfall), eine Verbesserung zaehlt nicht negativ.
    * Abwesenheits-Komponente: Anzahl Stunden seit der letzten Anwesenheit,
      skaliert an ``RISIKO_ABWESENHEIT_MAX`` (ab dort maximal 1.0).

    Beide werden mit RISIKO_GEWICHT_ABFALL bzw. RISIKO_GEWICHT_ABWESENHEIT
    gewichtet (Summe 1.0). Der Score liegt zwischen 0.0 und 1.0 und wird ueber
    RISIKO_SCHWELLE_* in niedrig/mittel/hoch eingeteilt. Alle Konstanten sind am
    Modulkopf dokumentiert und koennen angepasst werden.

    Umgang mit 0 aktiven Stunden: Hat ein Mitglied keine Stunden im aktiven
    Zeitraum (z. B. ein Neuzugang mit Eintritt nach der letzten vorhandenen
    Stunde), ist es fachlich nicht bewertbar. Analog zur fairen Beteiligung
    wird dann ``bewertbar=False``, ``risiko_score=None`` und
    ``risiko_stufe="unbekannt"`` gesetzt - so wird dieser Fall klar vom echten
    Nullrisiko (Score 0.0, Stufe "niedrig") eines treuen Mitglieds abgegrenzt.

    Rueckgabe: Liste flacher dicts
    {mitglied_id, name, bewertbar, quote_letzte_n, quote_davor,
     stunden_seit_letzter_anwesenheit, risiko_score, risiko_stufe}.
    """
    stunden_mit_datum = [
        (s, parse_date(s.get("datum"))) for s in gruppenstunden or []
    ]
    stunden_mit_datum = [(s, d) for s, d in stunden_mit_datum if d is not None]
    stunden_mit_datum.sort(key=lambda sd: sd[1])
    max_datum = max((d for _, d in stunden_mit_datum), default=None)

    ergebnis = []
    for m in mitglieder or []:
        if not m.get("_id"):
            continue
        mid = m["_id"]
        aktive = _moegliche_stunden_fuer(m, stunden_mit_datum, max_datum)
        # aktive sind bereits chronologisch (Herkunft chronologisch sortiert).
        anwesenheiten = [1 if mid in _teilnehmer_ids(s) else 0 for s in aktive]

        # Keine aktiven Stunden -> nicht bewertbar (vom Nullrisiko abgrenzen).
        if not anwesenheiten:
            ergebnis.append(
                {
                    "mitglied_id": mid,
                    "name": _display_name(m),
                    "bewertbar": False,
                    "quote_letzte_n": None,
                    "quote_davor": None,
                    "stunden_seit_letzter_anwesenheit": 0,
                    "risiko_score": None,
                    "risiko_stufe": _risiko_stufe(None),
                }
            )
            continue

        letzte_n = anwesenheiten[-RISIKO_FENSTER_N:]
        davor = anwesenheiten[:-RISIKO_FENSTER_N] if len(anwesenheiten) > RISIKO_FENSTER_N else []

        quote_letzte_n = round(mean(letzte_n), 4) if letzte_n else None
        quote_davor = round(mean(davor), 4) if davor else None

        # Abfall-Komponente: nur Rueckgang zaehlt.
        if quote_letzte_n is not None and quote_davor is not None:
            abfall = max(0.0, quote_davor - quote_letzte_n)
        else:
            abfall = 0.0

        # Stunden seit letzter Anwesenheit (innerhalb des aktiven Zeitraums).
        if 1 in anwesenheiten:
            letzter_index = max(i for i, v in enumerate(anwesenheiten) if v == 1)
            stunden_seit = len(anwesenheiten) - 1 - letzter_index
        else:
            # Nie anwesend: alle aktiven Stunden gelten als "seit letzter".
            stunden_seit = len(anwesenheiten)

        abwesenheit = min(1.0, stunden_seit / RISIKO_ABWESENHEIT_MAX) if RISIKO_ABWESENHEIT_MAX else 0.0

        score = round(
            RISIKO_GEWICHT_ABFALL * abfall + RISIKO_GEWICHT_ABWESENHEIT * abwesenheit, 4
        )
        ergebnis.append(
            {
                "mitglied_id": mid,
                "name": _display_name(m),
                "bewertbar": True,
                "quote_letzte_n": quote_letzte_n,
                "quote_davor": quote_davor,
                "stunden_seit_letzter_anwesenheit": stunden_seit,
                "risiko_score": score,
                "risiko_stufe": _risiko_stufe(score),
            }
        )
    return ergebnis


# ---------------------------------------------------------------------------
# KENNZAHL 4 - Saisonalitaet / Muster
# ---------------------------------------------------------------------------

def saisonalitaet(
    gruppenstunden: List[Dict[str, Any]],
    bundesland: str = "",
) -> Dict[str, Any]:
    """Besucherzahlen pro Monat (1-12) und pro Wochentag (0-6, Montag=0).

    Je Gruppenstunde zaehlt die Anzahl der Teilnehmer (len(teilnehmer)).
    Aggregiert wird nach Monat und nach Wochentag des Datums.

    Ferien-Korrelation: Nur wenn ein ``bundesland`` gesetzt ist UND Feriendaten
    verfuegbar waeren, wuerde eine Korrelation versucht. Da im Projekt (noch)
    keine Feriendaten hinterlegt sind, wird dieser Teil sauber uebersprungen:
    das Flag ``ferien_korrelation`` ist dann ``None`` (uebersprungen). Es kommt
    nie zu einem Absturz, auch nicht ohne Bundesland.

    Rueckgabe:
    {pro_monat: [{monat, anzahl_stunden, summe_anwesend, schnitt_anwesend}],
     pro_wochentag: [... analog mit 'wochentag'],
     ferien_korrelation: None}
    """
    monat_summe: Dict[int, int] = {}
    monat_count: Dict[int, int] = {}
    wtag_summe: Dict[int, int] = {}
    wtag_count: Dict[int, int] = {}

    for s in gruppenstunden or []:
        d = parse_date(s.get("datum"))
        if d is None:
            continue
        anwesend = len(_teilnehmer_ids(s))
        monat_summe[d.month] = monat_summe.get(d.month, 0) + anwesend
        monat_count[d.month] = monat_count.get(d.month, 0) + 1
        wtag = d.weekday()
        wtag_summe[wtag] = wtag_summe.get(wtag, 0) + anwesend
        wtag_count[wtag] = wtag_count.get(wtag, 0) + 1

    pro_monat = [
        {
            "monat": monat,
            "anzahl_stunden": monat_count[monat],
            "summe_anwesend": monat_summe[monat],
            "schnitt_anwesend": round(monat_summe[monat] / monat_count[monat], 2),
        }
        for monat in sorted(monat_count)
    ]
    pro_wochentag = [
        {
            "wochentag": wtag,
            "anzahl_stunden": wtag_count[wtag],
            "summe_anwesend": wtag_summe[wtag],
            "schnitt_anwesend": round(wtag_summe[wtag] / wtag_count[wtag], 2),
        }
        for wtag in sorted(wtag_count)
    ]

    # Ferien-Korrelation mangels Feriendaten sauber ueberspringen.
    ferien_korrelation = None

    return {
        "pro_monat": pro_monat,
        "pro_wochentag": pro_wochentag,
        "ferien_korrelation": ferien_korrelation,
    }


# ---------------------------------------------------------------------------
# KENNZAHL 5 - Thema-Ranking
# ---------------------------------------------------------------------------

def thema_ranking(gruppenstunden: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Durchschnittliche Anwesenheit pro Thema.

    Primaer wird nach ``thema_relation`` (Liste von Page-IDs einer Themen-DB)
    gruppiert. Hat eine Stunde mehrere Themen-IDs, zaehlt sie fuer jede ID
    einzeln (jede ID erhaelt die Teilnehmerzahl dieser Stunde). Ist
    ``thema_relation`` leer oder None, wird auf das Textfeld ``titel``
    zurueckgegriffen. Themen-Namen der Relation muessen nicht aufloesbar sein -
    die Page-ID dient dann als Schluessel.

    Rueckgabe: Liste flacher dicts
    {thema_key, thema_quelle ('relation'|'titel'), anzahl_stunden,
     schnitt_anwesend}, absteigend nach Durchschnitt.
    """
    summe: Dict[Any, int] = {}
    count: Dict[Any, int] = {}
    quelle: Dict[Any, str] = {}

    for s in gruppenstunden or []:
        anwesend = len(_teilnehmer_ids(s))
        relationen = [r for r in _as_list(s.get("thema_relation")) if isinstance(r, str) and r]
        if relationen:
            for key in relationen:
                summe[key] = summe.get(key, 0) + anwesend
                count[key] = count.get(key, 0) + 1
                quelle[key] = "relation"
        else:
            titel = s.get("titel") or "(ohne Thema)"
            summe[titel] = summe.get(titel, 0) + anwesend
            count[titel] = count.get(titel, 0) + 1
            # Nur setzen, wenn noch nicht per Relation belegt.
            quelle.setdefault(titel, "titel")

    zeilen = [
        {
            "thema_key": key,
            "thema_quelle": quelle[key],
            "anzahl_stunden": count[key],
            "schnitt_anwesend": round(summe[key] / count[key], 2),
        }
        for key in count
    ]
    zeilen.sort(key=lambda z: (-z["schnitt_anwesend"], str(z["thema_key"])))
    return zeilen


# ---------------------------------------------------------------------------
# KENNZAHL 6 - Lager vs. Gruppenstunde
# ---------------------------------------------------------------------------

def lager_korrelation(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
    lager: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Vergleich der fairen Gruppenstunden-Quote: Lagerteilnehmer vs. Rest.

    Mitglieder werden in "mindestens ein Lager besucht" und "kein Lager" geteilt.
    Fuer beide Gruppen wird der Durchschnitt der fairen Beteiligungsquote
    (Kennzahl 2) gebildet; Mitglieder ohne bewertbare Quote (None) fliessen nicht
    in den Durchschnitt ein.

    Rueckgabe:
    {lagerteilnehmer: {anzahl, schnitt_quote},
     nicht_teilnehmer: {anzahl, schnitt_quote},
     differenz}
    """
    lager_ids = set()
    for l in lager or []:
        for mid in _teilnehmer_ids(l):
            lager_ids.add(mid)

    quoten = {
        row["mitglied_id"]: row["quote_prozent"]
        for row in faire_beteiligung(mitglieder, gruppenstunden)
    }

    teiln_quoten: List[float] = []
    nicht_quoten: List[float] = []
    anzahl_teiln = 0
    anzahl_nicht = 0
    for m in mitglieder or []:
        mid = m.get("_id")
        if not mid:
            continue
        q = quoten.get(mid)
        if mid in lager_ids:
            anzahl_teiln += 1
            if q is not None:
                teiln_quoten.append(q)
        else:
            anzahl_nicht += 1
            if q is not None:
                nicht_quoten.append(q)

    schnitt_teiln = round(mean(teiln_quoten), 2) if teiln_quoten else None
    schnitt_nicht = round(mean(nicht_quoten), 2) if nicht_quoten else None
    if schnitt_teiln is not None and schnitt_nicht is not None:
        differenz = round(schnitt_teiln - schnitt_nicht, 2)
    else:
        differenz = None

    return {
        "lagerteilnehmer": {"anzahl": anzahl_teiln, "schnitt_quote": schnitt_teiln},
        "nicht_teilnehmer": {"anzahl": anzahl_nicht, "schnitt_quote": schnitt_nicht},
        "differenz": differenz,
    }


# ---------------------------------------------------------------------------
# KENNZAHL 7 - Puenktlichkeit
# ---------------------------------------------------------------------------

def puenktlichkeit(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Verspaetungen pro Mitglied, falls das Feld 'zu_spaet' brauchbar ist.

    Das Feld ``zu_spaet`` ist in seiner Struktur nicht garantiert und wird
    defensiv behandelt:

    * Liste von Mitglieder-IDs (Strings) -> jede ID zaehlt eine Verspaetung in
      dieser Stunde. Dies ist die auswertbare Interpretation.
    * None, bool oder String -> nicht als strukturierte Verspaetung auswertbar;
      die Auswertung wird sauber uebersprungen.

    Es gilt als "verfuegbar", sobald mindestens eine Gruppenstunde eine Liste
    mit mindestens einer Mitglieder-ID in ``zu_spaet`` enthaelt. Andernfalls ist
    ``verfuegbar`` False und ``pro_mitglied`` leer - ohne Absturz.

    Rueckgabe:
    {verfuegbar: bool, pro_mitglied: [{mitglied_id, name, verspaetungen}]}
    """
    gueltige_ids = {m.get("_id") for m in mitglieder or [] if m.get("_id")}
    zaehler: Dict[str, int] = {}
    verfuegbar = False

    for s in gruppenstunden or []:
        zs = s.get("zu_spaet")
        if isinstance(zs, list):
            ids = [x for x in zs if isinstance(x, str)]
            if ids:
                verfuegbar = True
            for mid in ids:
                if mid in gueltige_ids:
                    zaehler[mid] = zaehler.get(mid, 0) + 1
        # None, bool, String: nicht strukturiert auswertbar -> ueberspringen.

    if not verfuegbar:
        return {"verfuegbar": False, "pro_mitglied": []}

    pro_mitglied = [
        {
            "mitglied_id": m.get("_id"),
            "name": _display_name(m),
            "verspaetungen": zaehler.get(m.get("_id"), 0),
        }
        for m in mitglieder or []
        if m.get("_id")
    ]
    pro_mitglied.sort(key=lambda z: (-z["verspaetungen"], z["name"]))
    return {"verfuegbar": True, "pro_mitglied": pro_mitglied}


# ---------------------------------------------------------------------------
# KENNZAHL 8 - Gesamtkennzahlen
# ---------------------------------------------------------------------------

def gesamtkennzahlen(
    mitglieder: List[Dict[str, Any]],
    gruppenstunden: List[Dict[str, Any]],
    lager: List[Dict[str, Any]],
    stichtag: Optional[date] = None,
) -> Dict[str, Any]:
    """Aggregierte Gesamtkennzahlen ueber alle Daten.

    * anzahl_aktive_mitglieder: nicht ausgeschieden (Feld bzw. Austrittsdatum)
    * anzahl_mitglieder_gesamt: alle Mitglieder
    * anzahl_gruppenstunden / anzahl_lager
    * schnitt_anwesend_pro_stunde: Durchschnitt der len(teilnehmer) je Stunde
    * gesamtbeteiligungsquote: Durchschnitt der fairen Beteiligungsquoten
      (Kennzahl 2) ueber alle bewertbaren Mitglieder. Diese Definition folgt
      demselben Fairness-Prinzip wie die uebrigen mitgliederbezogenen
      Kennzahlen: jedes Mitglied wird nur an den Stunden seines aktiven
      Zeitraums (Eintritt bis Austritt bzw. letzte Stunde) gemessen, sodass
      Zu- und Abgaenge die Quote nicht kuenstlich druecken. Mitglieder ohne
      bewertbare Quote (None) fliessen nicht in den Durchschnitt ein. Gibt es
      keine bewertbaren Mitglieder, ist die Quote 0.0.
    * gesamtbeteiligungsquote_roh: die fruehere ungewichtete Rohquote
      (Summe aller Anwesenheiten / (anzahl_mitglieder_gesamt *
      anzahl_gruppenstunden) * 100). Sie ignoriert aktive Zeitraeume und wird
      bewusst nur als ungewichtete Zusatzkennzahl mitgefuehrt.

    Rueckgabe: flaches dict.
    """
    alle = mitglieder or []
    aktive = [m for m in alle if not ist_ausgeschieden(m, stichtag)]

    anzahl_stunden = len(gruppenstunden or [])
    anwesenheiten = [len(_teilnehmer_ids(s)) for s in gruppenstunden or []]
    summe_anwesend = sum(anwesenheiten)
    schnitt = round(summe_anwesend / anzahl_stunden, 2) if anzahl_stunden else 0.0

    # Faire Gesamtquote: Durchschnitt der bewertbaren fairen Einzelquoten.
    faire_quoten = [
        row["quote_prozent"]
        for row in faire_beteiligung(alle, gruppenstunden)
        if row["quote_prozent"] is not None
    ]
    gesamtquote = round(mean(faire_quoten), 2) if faire_quoten else 0.0

    # Ungewichtete Rohquote (bewusst als Zusatz, ignoriert aktive Zeitraeume).
    nenner = len(alle) * anzahl_stunden
    gesamtquote_roh = round(summe_anwesend / nenner * 100, 2) if nenner else 0.0

    return {
        "anzahl_aktive_mitglieder": len(aktive),
        "anzahl_mitglieder_gesamt": len(alle),
        "anzahl_gruppenstunden": anzahl_stunden,
        "anzahl_lager": len(lager or []),
        "schnitt_anwesend_pro_stunde": schnitt,
        "gesamtbeteiligungsquote": gesamtquote,
        "gesamtbeteiligungsquote_roh": gesamtquote_roh,
    }


# ---------------------------------------------------------------------------
# Haupt-Einstieg
# ---------------------------------------------------------------------------

def analyze(data: Dict[str, Any], cfg: Any = None) -> Dict[str, Any]:
    """Gesamt-Report ueber alle acht Kennzahlen berechnen.

    ``data`` ist der fetch_all-Output (oder ein geladenes JSON) mit den
    Schluesseln mitglieder/gruppenstunden/lager. ``cfg`` ist optional das
    Config-Objekt; es wird ``cfg.analysis.only_active_members`` und
    ``cfg.analysis.bundesland`` genutzt. Ohne cfg gelten die Defaults
    (only_active_members=False, bundesland="").

    Wirkung von only_active_members: Ist es True, werden ausgeschiedene
    Mitglieder aus den MITGLIEDERBEZOGENEN Auswertungen ausgenommen
    (Top/Flop-Anwesenheit, faire Beteiligung, Risiko-Score, Lager-Korrelation,
    Puenktlichkeit). Die STUNDENBASIERTEN Auswertungen (Saisonalitaet,
    Thema-Ranking) bleiben unberuehrt, da sie nicht pro Mitglied rechnen. Die
    Gesamtkennzahlen weisen aktive und gesamte Mitgliederzahl ohnehin getrennt
    aus und bleiben daher ebenfalls auf der vollen Mitgliederbasis.

    Rueckgabe: ein flaches, JSON-serialisierbares Report-dict.
    """
    mitglieder = data.get("mitglieder") or []
    gruppenstunden = data.get("gruppenstunden") or []
    lager = data.get("lager") or []

    only_active = False
    bundesland = ""
    if cfg is not None and getattr(cfg, "analysis", None) is not None:
        only_active = bool(getattr(cfg.analysis, "only_active_members", False))
        bundesland = getattr(cfg.analysis, "bundesland", "") or ""

    mitglieder_ausw = _aktive_mitglieder(mitglieder, only_active)

    return {
        "_meta": {
            "anzahl_mitglieder": len(mitglieder),
            "anzahl_gruppenstunden": len(gruppenstunden),
            "anzahl_lager": len(lager),
            "only_active_members": only_active,
            "bundesland": bundesland,
        },
        "top_flop_anwesenheit": top_flop_anwesenheit(mitglieder_ausw, gruppenstunden),
        "faire_beteiligung": faire_beteiligung(mitglieder_ausw, gruppenstunden),
        "risiko_score": risiko_score(mitglieder_ausw, gruppenstunden),
        "saisonalitaet": saisonalitaet(gruppenstunden, bundesland),
        "thema_ranking": thema_ranking(gruppenstunden),
        "lager_korrelation": lager_korrelation(mitglieder_ausw, gruppenstunden, lager),
        "puenktlichkeit": puenktlichkeit(mitglieder_ausw, gruppenstunden),
        "gesamtkennzahlen": gesamtkennzahlen(mitglieder, gruppenstunden, lager),
    }
