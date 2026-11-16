"""Einfache Teilnehmerliste — erzeugt ein befülltes PDF (Layout-Nachbau).

Spalten gemäß der Vorlage:
    Lfd Nr. | Name | Vorname | Wohnort, Straße, Nr. | Alter | Unterschrift des Teilnehmers

Das Alter wird automatisch aus dem Geburtsdatum zum Anreisetag berechnet.
Betreuer werden am Ende als eigene Zeilen ("Betreuer:") ausgewiesen.
Die Unterschrift-Spalte bleibt leer (handschriftlich).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from konfiguration import Konfiguration
from modell import Teilnehmer, datum_parsen


def erzeugen(teilnehmer: list[Teilnehmer], ziel: Path, konfig: Konfiguration) -> Path:
    v = konfig.veranstaltung.get("veranstaltung", {})
    stichtag = datum_parsen(v.get("anreisetag"))

    ziel.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(ziel),
        pagesize=landscape(A4),
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    titel = ParagraphStyle("T", parent=styles["Normal"], fontSize=11, leading=14)
    zell = ParagraphStyle("Z", parent=styles["Normal"], fontSize=9, leading=11)

    an = v.get("anreisetag", "…")
    ab = v.get("abreisetag", "…")
    elemente = [
        Paragraph(f"Teilnehmerliste für die Maßnahme vom {an} bis {ab}", titel),
        Spacer(1, 6 * mm),
    ]

    kopf = ["Lfd\nNr.", "Name", "Vorname", "Wohnort, Straße, Nr.", "Alter",
            "Unterschrift des\nTeilnehmers"]
    daten = [kopf]

    # Erst Teilnehmer, dann Betreuer (werden unten separat gekennzeichnet)
    nur_tn = [p for p in teilnehmer if not p.ist_betreuer]
    nur_betreuer = [p for p in teilnehmer if p.ist_betreuer]

    nr = 1
    for person in nur_tn:
        daten.append([
            str(nr),
            Paragraph(person.nachname, zell),
            Paragraph(person.vorname, zell),
            Paragraph(person.wohnort_strasse, zell),
            _alter_text(person, stichtag),
            "",
        ])
        nr += 1

    # Betreuer-Zeilen
    for person in nur_betreuer:
        daten.append([
            Paragraph("<b>Betreuer:</b>", zell),
            Paragraph(person.nachname, zell),
            Paragraph(person.vorname, zell),
            Paragraph(person.wohnort_strasse, zell),
            _alter_text(person, stichtag),
            "",
        ])

    tabelle = Table(
        daten,
        colWidths=[16 * mm, 45 * mm, 45 * mm, 95 * mm, 18 * mm, 48 * mm],
        repeatRows=1,
    )
    tabelle.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))
    elemente.append(tabelle)

    doc.build(elemente)
    return ziel


def _alter_text(person: Teilnehmer, stichtag) -> str:
    if stichtag is None:
        return ""
    alter = person.alter(stichtag)
    return str(alter) if alter is not None else ""
