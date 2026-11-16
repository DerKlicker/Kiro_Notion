"""RJBH-Liste — befüllt die Original-Excel-Vorlage (Blatt "TN-Liste").

Robust gegen Vorlagen-Updates: Statt feste Zellkoordinaten zu verwenden, sucht
der Code die Überschriftenzeile ("Nachname", "Vorname", "Straße" ...) und ordnet
die Spalten dynamisch zu. Lädt der RJBH eine neue Version hoch, musst du nichts
im Code ändern — solange die Spaltenüberschriften gleich heißen.

Es werden NUR die Datenzellen beschrieben. Formeln (z.B. die "selbstzählende
Tabelle") und die übrige Formatierung bleiben unberührt.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from konfiguration import Konfiguration
from modell import Teilnehmer

# Blattname in der RJBH-Vorlage, der die Teilnehmerzeilen enthält.
BLATT_NAME = "TN-Liste"

# Welche Überschrift gehört zu welchem internen Feld?
# Keys = Suchbegriffe (klein, ohne Leerzeichen am Rand), Werte = internes Feld.
UEBERSCHRIFT_ZU_FELD = {
    "nr.": "nr",
    "nr": "nr",
    "nachname": "nachname",
    "vorname": "vorname",
    "straße": "strasse",
    "strasse": "strasse",
    "plz": "plz",
    "ort": "ort",
    "bundesland": "bundesland",
    "geburtstag": "geburtstag",
    "geburtsdatum": "geburtstag",
    "unterschrift": "unterschrift",
    "pm": "pm",
    "tn": "tn",
    "m/w/d": "geschlecht",
}


def erzeugen(
    teilnehmer: list[Teilnehmer],
    vorlage: Path,
    ziel: Path,
    konfig: Konfiguration,
) -> Path:
    if not vorlage.exists():
        raise FileNotFoundError(
            f"RJBH-Vorlage nicht gefunden: {vorlage}\n"
            "Bitte die aktuelle RJBH-Excel unter diesem Pfad ablegen "
            "(templates/rjbh_vorlage.xlsx)."
        )

    wb = openpyxl.load_workbook(vorlage)
    if BLATT_NAME not in wb.sheetnames:
        raise RuntimeError(
            f"Blatt '{BLATT_NAME}' nicht in der Vorlage gefunden. "
            f"Vorhandene Blätter: {wb.sheetnames}"
        )
    ws = wb[BLATT_NAME]

    kopf_zeile, spalten = _ueberschriften_finden(ws)
    if not spalten:
        raise RuntimeError(
            "Überschriftenzeile in der RJBH-Vorlage nicht erkannt. "
            "Erwartet werden Spalten wie 'Nachname', 'Vorname', 'Straße' ..."
        )

    # Kopfdaten (Mitgliedsbund, Titel, Daten) eintragen — best effort
    _kopf_ausfuellen(ws, konfig)

    start_zeile = kopf_zeile + 1
    for index, person in enumerate(teilnehmer):
        zeile = start_zeile + index
        _zeile_schreiben(ws, zeile, index + 1, person, spalten)

    ziel.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ziel)
    return ziel


def _ueberschriften_finden(ws) -> tuple[int, dict[str, int]]:
    """Durchsucht die ersten Zeilen nach der Überschriftenzeile der Tabelle.

    Gibt (zeilennummer, {internes_feld: spalten_index}) zurück.
    """
    max_suchzeilen = min(ws.max_row, 30)
    for zeile in range(1, max_suchzeilen + 1):
        gefunden: dict[str, int] = {}
        for spalte in range(1, min(ws.max_column, 40) + 1):
            wert = ws.cell(row=zeile, column=spalte).value
            if wert is None:
                continue
            schluessel = str(wert).strip().lower()
            feld = UEBERSCHRIFT_ZU_FELD.get(schluessel)
            if feld:
                gefunden.setdefault(feld, spalte)
        # Als Überschriftenzeile gilt sie, wenn die Kernspalten vorhanden sind
        if {"nachname", "vorname"}.issubset(gefunden.keys()):
            return zeile, gefunden
    return 0, {}


def _zeile_schreiben(ws, zeile: int, nr: int, person: Teilnehmer, spalten: dict[str, int]) -> None:
    def setze(feld: str, wert) -> None:
        spalte = spalten.get(feld)
        if spalte and wert not in (None, ""):
            ws.cell(row=zeile, column=spalte, value=wert)

    setze("nr", nr)
    setze("nachname", person.nachname)
    setze("vorname", person.vorname)
    setze("strasse", person.strasse)
    setze("plz", person.plz)
    setze("ort", person.ort)
    setze("bundesland", person.bundesland)
    setze("geburtstag", person.geburtstag_text())
    setze("geschlecht", person.geschlecht)
    # Unterschrift bleibt leer (wird handschriftlich ausgefüllt)
    if person.ist_betreuer:
        setze("pm", "x")
    else:
        setze("tn", "x")


def _kopf_ausfuellen(ws, konfig: Konfiguration) -> None:
    """Trägt Kopfinformationen ein, falls die passenden Label-Zellen existieren.

    Sucht nach Labels wie 'Mitgliedsbund', 'Titel d. Maßnahme' usw. und schreibt
    den Wert in die Zelle rechts daneben. Fehlt ein Label, wird es übersprungen.
    """
    v = konfig.veranstaltung.get("veranstaltung", {})
    rjbh = konfig.veranstaltung.get("rjbh", {})

    label_werte = {
        "mitgliedsbund": rjbh.get("mitgliedsbund", ""),
        "titel d. maßnahme": v.get("titel", ""),
        "programmbeginn": v.get("anreisetag", ""),
        "programmende": v.get("abreisetag", ""),
    }

    for zeile in range(1, min(ws.max_row, 15) + 1):
        for spalte in range(1, min(ws.max_column, 12) + 1):
            wert = ws.cell(row=zeile, column=spalte).value
            if wert is None:
                continue
            schluessel = str(wert).strip().lower().rstrip(":")
            if schluessel in label_werte and label_werte[schluessel]:
                ziel = ws.cell(row=zeile, column=spalte + 1)
                if ziel.value in (None, ""):
                    ziel.value = label_werte[schluessel]
