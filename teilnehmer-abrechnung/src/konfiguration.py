"""Lädt die YAML-Konfigurationen und wandelt Roh-Datensätze in Teilnehmer um.

Der Kern der "Zukunftssicherheit": Das Mapping (welche Quell-Spalte -> welches
interne Feld) steckt komplett in config/mapping.yaml. Dieser Code liest nur das
Mapping aus und wendet es an.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from modell import Teilnehmer, datum_parsen


class Konfiguration:
    """Hält Mapping- und Veranstaltungs-Konfiguration."""

    def __init__(self, mapping: dict, veranstaltung: dict):
        self.mapping = mapping
        self.veranstaltung = veranstaltung

    # ---- Laden ----------------------------------------------------------

    @classmethod
    def laden(cls, config_ordner: Path) -> "Konfiguration":
        mapping = _yaml_laden(config_ordner / "mapping.yaml")
        veranstaltung = _yaml_laden(config_ordner / "veranstaltung.yaml")
        return cls(mapping, veranstaltung)

    # ---- Zugriffs-Helfer ------------------------------------------------

    @property
    def feld_namen(self) -> dict:
        return self.mapping.get("felder", {})

    @property
    def name_format(self) -> str:
        return self.mapping.get("name_format", "vorname_nachname")

    @property
    def name_trennzeichen(self) -> str:
        return self.mapping.get("name_trennzeichen", ",")

    @property
    def betreuer_funktionsstufen(self) -> list[str]:
        werte = self.mapping.get("betreuer_funktionsstufen", []) or []
        return [str(w).strip().lower() for w in werte]

    # ---- Mapping: Roh-Datensatz -> Teilnehmer ---------------------------

    def zu_teilnehmer(self, roh: dict) -> Teilnehmer:
        """Wandelt einen Roh-Datensatz (dict mit Quell-Spaltennamen als Keys)
        in ein Teilnehmer-Objekt um, gemäß dem Mapping.
        """
        f = self.feld_namen

        def hole(feld_key: str) -> str:
            """Holt den Wert für ein internes Feld anhand des gemappten Spaltennamens."""
            spalte = f.get(feld_key)
            if not spalte:
                return ""
            wert = roh.get(spalte, "")
            return "" if wert is None else str(wert).strip()

        vorname, nachname = self._name_aufteilen(hole("name"))

        funktionsstufe = hole("funktionsstufe")
        ist_betreuer = funktionsstufe.strip().lower() in self.betreuer_funktionsstufen

        return Teilnehmer(
            vorname=vorname,
            nachname=nachname,
            strasse=hole("strasse"),
            plz=hole("plz"),
            ort=hole("ort"),
            bundesland=hole("bundesland"),
            geburtstag=datum_parsen(hole("geburtstag")),
            funktionsstufe=funktionsstufe,
            geschlecht=hole("geschlecht").lower(),
            juleica=_als_boolean(hole("juleica")),
            ist_betreuer=ist_betreuer,
            rohdaten=roh,
        )

    def _name_aufteilen(self, name: str) -> tuple[str, str]:
        """Teilt das kombinierte Namensfeld in (Vorname, Nachname) auf."""
        if not name:
            return "", ""
        trenn = self.name_trennzeichen
        if trenn in name:
            teil_a, teil_b = [t.strip() for t in name.split(trenn, 1)]
        else:
            # Kein Trennzeichen -> nur ein Wort, als Nachname behandeln
            return "", name.strip()

        if self.name_format == "nachname_vorname":
            nachname, vorname = teil_a, teil_b
        else:  # vorname_nachname (Standard)
            vorname, nachname = teil_a, teil_b
        return vorname, nachname


def _yaml_laden(pfad: Path) -> dict:
    if not pfad.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {pfad}")
    with open(pfad, "r", encoding="utf-8") as fh:
        daten = yaml.safe_load(fh)
    return daten or {}


def _als_boolean(wert: str) -> bool:
    return str(wert).strip().lower() in ("true", "wahr", "ja", "yes", "x", "1")
