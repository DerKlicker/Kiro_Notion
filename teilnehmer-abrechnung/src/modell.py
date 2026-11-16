"""Internes Datenmodell und Hilfsfunktionen.

Hier wird definiert, wie ein Teilnehmer intern aussieht — unabhängig davon,
ob die Daten aus Notion oder einer CSV kommen. Die Datenquellen liefern
immer dieses einheitliche Format, die Listen-Generatoren lesen daraus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Datumsformate, die wir beim Einlesen akzeptieren (robust gegen verschiedene
# Schreibweisen aus Notion / CSV).
_DATUMSFORMATE = (
    "%d.%m.%Y",   # 16.11.2004
    "%Y-%m-%d",   # 2004-11-16  (Notion-API Standard)
    "%d.%m.%y",   # 16.11.04
    "%d/%m/%Y",   # 16/11/2004
)

# Deutsche Monatsnamen -> für "16. November 2004" (Notion-Anzeigeformat)
_MONATE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}


def datum_parsen(wert: str | date | datetime | None) -> date | None:
    """Wandelt eine Datumsangabe (verschiedene Formate) in ein date-Objekt um.

    Gibt None zurück, wenn kein Datum erkannt werden kann.
    """
    if wert is None or wert == "":
        return None
    if isinstance(wert, datetime):
        return wert.date()
    if isinstance(wert, date):
        return wert

    text = str(wert).strip()

    # Zuerst die Standardformate probieren
    for fmt in _DATUMSFORMATE:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # Deutsches Anzeigeformat: "16. November 2004"
    teile = text.replace(".", "").split()
    if len(teile) == 3:
        tag, monat_name, jahr = teile
        monat = _MONATE.get(monat_name.lower())
        if monat and tag.isdigit() and jahr.isdigit():
            try:
                return date(int(jahr), monat, int(tag))
            except ValueError:
                return None

    return None


def alter_berechnen(geburtstag: date | None, stichtag: date) -> int | None:
    """Berechnet das Alter in vollen Jahren am Stichtag (z.B. Anreisetag)."""
    if geburtstag is None:
        return None
    alter = stichtag.year - geburtstag.year
    # Geburtstag im Stichtagsjahr noch nicht erreicht? -> ein Jahr abziehen
    if (stichtag.month, stichtag.day) < (geburtstag.month, geburtstag.day):
        alter -= 1
    return alter


@dataclass
class Teilnehmer:
    """Ein einzelner Teilnehmer oder Betreuer — datenquellen-unabhängig."""

    vorname: str = ""
    nachname: str = ""
    strasse: str = ""          # Straße + Hausnummer
    plz: str = ""
    ort: str = ""
    bundesland: str = ""
    geburtstag: date | None = None
    funktionsstufe: str = ""   # Mitglied / Sippenführer / Gruppenleiter
    geschlecht: str = ""       # m / w / d
    juleica: bool = False
    ist_betreuer: bool = False

    # Rohdaten (für Fehlersuche): das unverarbeitete Herkunfts-Dict
    rohdaten: dict = field(default_factory=dict)

    # ---- abgeleitete Darstellungen -------------------------------------

    @property
    def name_nachname_vorname(self) -> str:
        """'Nachname, Vorname' — Format für die Kreis-Offenbach-Liste."""
        if self.nachname and self.vorname:
            return f"{self.nachname}, {self.vorname}"
        return self.nachname or self.vorname

    @property
    def plz_ort(self) -> str:
        """'PLZ Ort' — kompakte Wohnort-Angabe."""
        return " ".join(p for p in (self.plz, self.ort) if p).strip()

    @property
    def wohnort_strasse(self) -> str:
        """'Ort, Straße Nr.' — Format für die einfache Liste (Spalte 'Wohnort, Straße, Nr.')."""
        teile = [t for t in (self.plz_ort, self.strasse) if t]
        return ", ".join(teile)

    def geburtstag_text(self, fmt: str = "%d.%m.%Y") -> str:
        return self.geburtstag.strftime(fmt) if self.geburtstag else ""

    def alter(self, stichtag: date) -> int | None:
        return alter_berechnen(self.geburtstag, stichtag)
