"""Erzeugt eine vereinfachte RJBH-Test-Vorlage zum Prüfen der Spaltenerkennung.

NICHT die echte Vorlage — nur zum Testen, dass liste_rjbh die Überschriften
findet und in die richtigen Spalten schreibt. Die echte Vorlage legst du selbst
unter templates/rjbh_vorlage.xlsx ab.
"""
from pathlib import Path

import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "TN-Liste"

# Kopfbereich mit Labels (wie in der echten Vorlage)
ws["A2"] = "Mitgliedsbund"
ws["B4"] = "Titel d. Maßnahme"
ws["B5"] = "Programmbeginn"
ws["B6"] = "Programmende"

# Überschriftenzeile der Tabelle in Zeile 9
kopf = ["Nr.", "Nachname", "Vorname", "Straße", "PLZ", "Ort",
        "Bundesland", "Geburtstag", "Unterschrift", "PM", "TN", "m/w/d"]
for spalte, titel in enumerate(kopf, start=1):
    ws.cell(row=9, column=spalte, value=titel)

ziel = Path(__file__).resolve().parent.parent / "templates" / "rjbh_TESTvorlage.xlsx"
ziel.parent.mkdir(parents=True, exist_ok=True)
wb.save(ziel)
print(f"Testvorlage erzeugt: {ziel}")
