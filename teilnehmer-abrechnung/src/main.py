"""Hauptprogramm — erzeugt aus einer Datenquelle die drei Teilnehmerlisten.

Aufruf (Beispiele):

    # Aus Notion (Standard; braucht NOTION_TOKEN + NOTION_DATABASE_ID in .env)
    python src/main.py --quelle notion

    # Aus einer CSV (Backup-Weg)
    python src/main.py --quelle csv --csv input/teilnehmer.csv

    # Nur eine bestimmte Liste erzeugen
    python src/main.py --quelle csv --csv input/teilnehmer.csv --nur rjbh

Ergebnis landet im Ordner  output/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# src/ zum Importpfad hinzufügen, damit das Skript aus jedem Ordner läuft
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

import datenquelle_csv  # noqa: E402
import datenquelle_notion  # noqa: E402
import liste_einfach  # noqa: E402
import liste_kreis_of  # noqa: E402
import liste_rjbh  # noqa: E402
from konfiguration import Konfiguration  # noqa: E402

# Projekt-Wurzel (ein Ordner über src/)
WURZEL = Path(__file__).resolve().parent.parent
CONFIG = WURZEL / "config"
TEMPLATES = WURZEL / "templates"
OUTPUT = WURZEL / "output"


def main() -> int:
    load_dotenv(WURZEL / ".env")

    args = argumente_parsen()
    konfig = Konfiguration.laden(CONFIG)

    # --- Rohdaten aus der gewählten Quelle holen ---
    try:
        if args.quelle == "notion":
            print("→ Lade Daten aus Notion ...")
            rohdaten = datenquelle_notion.lade_rohdaten()
        else:
            csv_pfad = Path(args.csv) if args.csv else (WURZEL / "input" / "teilnehmer.csv")
            print(f"→ Lade Daten aus CSV: {csv_pfad}")
            rohdaten = datenquelle_csv.lade_rohdaten(csv_pfad)
    except Exception as fehler:  # noqa: BLE001
        print(f"\nFEHLER beim Laden der Daten: {fehler}", file=sys.stderr)
        return 1

    teilnehmer = [konfig.zu_teilnehmer(r) for r in rohdaten]
    if not teilnehmer:
        print("Keine Teilnehmer gefunden — nichts zu tun.")
        return 1

    anzahl_tn = sum(1 for p in teilnehmer if not p.ist_betreuer)
    anzahl_pm = sum(1 for p in teilnehmer if p.ist_betreuer)
    print(f"→ {len(teilnehmer)} Personen gelesen "
          f"({anzahl_tn} Teilnehmer, {anzahl_pm} Betreuer)")

    _hinweise_pruefen(teilnehmer)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    erzeugte: list[Path] = []

    # --- Listen erzeugen ---
    if args.nur in (None, "rjbh"):
        try:
            pfad = liste_rjbh.erzeugen(
                teilnehmer,
                vorlage=TEMPLATES / "rjbh_vorlage.xlsx",
                ziel=OUTPUT / "RJBH_Teilnehmendenliste.xlsx",
                konfig=konfig,
            )
            erzeugte.append(pfad)
            print(f"✓ RJBH-Excel:          {pfad}")
        except Exception as fehler:  # noqa: BLE001
            print(f"✗ RJBH-Excel übersprungen: {fehler}", file=sys.stderr)

    if args.nur in (None, "kreis"):
        pfad = liste_kreis_of.erzeugen(
            teilnehmer, ziel=OUTPUT / "KreisOffenbach_Teilnehmendenliste.pdf", konfig=konfig)
        erzeugte.append(pfad)
        print(f"✓ Kreis-Offenbach-PDF: {pfad}")

    if args.nur in (None, "einfach"):
        pfad = liste_einfach.erzeugen(
            teilnehmer, ziel=OUTPUT / "Einfache_Teilnehmerliste.pdf", konfig=konfig)
        erzeugte.append(pfad)
        print(f"✓ Einfache Liste-PDF:  {pfad}")

    print(f"\nFertig. {len(erzeugte)} Datei(en) im Ordner 'output/'.")
    print("Die Teilnehmer müssen jetzt nur noch unterschreiben.")
    return 0


def _hinweise_pruefen(teilnehmer: list) -> None:
    """Warnt bei fehlenden Pflichtangaben, ohne abzubrechen."""
    ohne_geburtstag = [p for p in teilnehmer if p.geburtstag is None]
    ohne_ort = [p for p in teilnehmer if not p.ort and not p.plz]
    if ohne_geburtstag:
        namen = ", ".join(p.name_nachname_vorname or "?" for p in ohne_geburtstag[:5])
        print(f"  ⚠ {len(ohne_geburtstag)} Person(en) ohne Geburtsdatum: {namen}"
              + (" ..." if len(ohne_geburtstag) > 5 else ""))
    if ohne_ort:
        namen = ", ".join(p.name_nachname_vorname or "?" for p in ohne_ort[:5])
        print(f"  ⚠ {len(ohne_ort)} Person(en) ohne Wohnort/PLZ: {namen}"
              + (" ..." if len(ohne_ort) > 5 else ""))


def argumente_parsen() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erzeugt die drei Teilnehmerlisten aus Notion oder CSV.")
    parser.add_argument("--quelle", choices=["notion", "csv"], default="notion",
                        help="Datenquelle (Standard: notion)")
    parser.add_argument("--csv", help="Pfad zur CSV-Datei (bei --quelle csv)")
    parser.add_argument("--nur", choices=["rjbh", "kreis", "einfach"],
                        help="Nur eine bestimmte Liste erzeugen")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
