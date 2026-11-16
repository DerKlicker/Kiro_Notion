"""Kreis-Offenbach-Liste — erzeugt ein befülltes PDF (Layout-Nachbau).

Spalten gemäß der Vorlage "Liste der Teilnehmenden":
    Lfd.Nr. | B/Juleica | Name, Vorname | Wohnort oder PLZ | Geburtsdatum |
    Anzahl Tage | Unterschrift

'B' markiert Betreuende. 'Juleica' ist eine ankreuzbare Option.
Die Unterschrift-Spalte bleibt leer (handschriftlich).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from konfiguration import Konfiguration
from modell import Teilnehmer, datum_parsen

# Checkbox-Darstellung. Unicode-Kästchen (☐/☒) werden von den Standard-PDF-
# Schriften nicht abgedeckt und erscheinen als schwarze Blöcke, daher ASCII.
LEER = "[ ]"
KREUZ = "[X]"


def erzeugen(teilnehmer: list[Teilnehmer], ziel: Path, konfig: Konfiguration) -> Path:
    v = konfig.veranstaltung.get("veranstaltung", {})
    stichtag = datum_parsen(v.get("anreisetag")) or None

    ziel.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(ziel),
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    titel_style = ParagraphStyle(
        "Titel", parent=styles["Title"], fontSize=12, leading=15
    )
    klein = ParagraphStyle("Klein", parent=styles["Normal"], fontSize=7, leading=8)
    zell = ParagraphStyle("Zell", parent=styles["Normal"], fontSize=8, leading=9)

    elemente = []
    elemente.append(Paragraph(
        "Fachdienst Jugend und Familie — 51.4 Jugendförderung und Frühe Hilfen", klein))
    elemente.append(Spacer(1, 4 * mm))
    elemente.append(Paragraph("Liste der Teilnehmenden", titel_style))
    elemente.append(Paragraph(
        "zum Antrag auf Gewährung eines Zuschusses gemäß der Richtlinie zur "
        "Förderung der verbandlichen Jugendarbeit und Jugendgemeinschaften", klein))
    elemente.append(Spacer(1, 4 * mm))

    anzahl_tage = _anzahl_tage(konfig)

    # Tabellenkopf
    kopf = ["Lfd.\nNr.", "B", "Name,\nVorname", "Wohnort\noder PLZ",
            "Geburts-\ndatum", "Anzahl\nTage", "Unterschrift"]
    daten = [kopf]

    for i, person in enumerate(teilnehmer, start=1):
        b_zelle = (f"{KREUZ if person.ist_betreuer else LEER} B\n"
                   f"{KREUZ if person.juleica else LEER} Juleica")
        daten.append([
            str(i),
            Paragraph(b_zelle.replace("\n", "<br/>"), klein),
            Paragraph(person.name_nachname_vorname, zell),
            Paragraph(person.plz_ort, zell),
            person.geburtstag_text(),
            str(anzahl_tage) if anzahl_tage else "",
            "",  # Unterschrift leer
        ])

    # Mindestens 16 Zeilen (wie Vorlage), um Platz zum Nachtragen zu lassen
    while len(daten) - 1 < 16:
        n = len(daten)
        daten.append([str(n), Paragraph(f"{LEER} B<br/>{LEER} Juleica", klein),
                      "", "", "", "", ""])

    tabelle = Table(
        daten,
        colWidths=[12 * mm, 20 * mm, 45 * mm, 38 * mm, 24 * mm, 16 * mm, 31 * mm],
        repeatRows=1,
    )
    tabelle.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 0), (5, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))
    elemente.append(tabelle)

    elemente.append(Spacer(1, 12 * mm))
    unterschrift = Table(
        [["_______________________________", "________________________________________"],
         ["Ort, Datum", "Rechtsverbindliche Unterschrift des Veranstalters"]],
        colWidths=[70 * mm, 95 * mm],
    )
    unterschrift.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
    ]))
    elemente.append(unterschrift)

    doc.build(elemente)
    return ziel


def _anzahl_tage(konfig: Konfiguration) -> int:
    v = konfig.veranstaltung.get("veranstaltung", {})
    manuell = v.get("anzahl_tage") or 0
    if manuell:
        return int(manuell)
    an = datum_parsen(v.get("anreisetag"))
    ab = datum_parsen(v.get("abreisetag"))
    if an and ab:
        return (ab - an).days + 1
    return 0
