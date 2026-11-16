"""Datenquelle CSV — der Backup-Weg (Copy-Paste / Export aus Notion).

Liest eine CSV-Datei ein und liefert Roh-Datensätze (dicts mit den
Spaltennamen als Keys). Das Mapping auf Teilnehmer übernimmt die Konfiguration.

Unterstützt automatisch Komma und Semikolon als Trennzeichen (deutsches
Excel exportiert oft mit Semikolon).
"""
from __future__ import annotations

import csv
from pathlib import Path


def lade_rohdaten(pfad: Path) -> list[dict]:
    if not pfad.exists():
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {pfad}")

    text = pfad.read_text(encoding="utf-8-sig")  # -sig entfernt evtl. BOM aus Excel

    # Trennzeichen automatisch erkennen
    trennzeichen = _trennzeichen_erkennen(text)

    zeilen = list(csv.DictReader(text.splitlines(), delimiter=trennzeichen))
    # Spaltennamen von umgebenden Leerzeichen befreien
    bereinigt = []
    for zeile in zeilen:
        bereinigt.append({(k.strip() if k else k): v for k, v in zeile.items()})
    return bereinigt


def _trennzeichen_erkennen(text: str) -> str:
    erste_zeile = text.splitlines()[0] if text.splitlines() else ""
    if erste_zeile.count(";") > erste_zeile.count(","):
        return ";"
    return ","
