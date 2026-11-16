"""Datenquelle Notion — der Hauptweg (API-Abruf).

Holt alle Einträge einer Notion-Datenbank und wandelt sie in Roh-Datensätze
(dicts mit Spaltennamen -> Wert als Text), sodass die Konfiguration sie genauso
mappen kann wie CSV-Daten.

Zugangsdaten kommen aus Umgebungsvariablen (.env-Datei), NICHT aus dem Code:
    NOTION_TOKEN        = secret_...   (Integration-Token)
    NOTION_DATABASE_ID  = ...          (ID der Datenbank)

Alle Property-Typen werden zu Text normalisiert. Dadurch ist es egal, ob eine
Spalte in Notion ein "Select", "Rich Text", "Date", "Checkbox" usw. ist —
das Mapping in mapping.yaml arbeitet immer gegen den Spalten-Titel.
"""
from __future__ import annotations

import os

import requests

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def lade_rohdaten(token: str | None = None, database_id: str | None = None) -> list[dict]:
    token = token or os.environ.get("NOTION_TOKEN")
    database_id = database_id or os.environ.get("NOTION_DATABASE_ID")

    if not token or not database_id:
        raise RuntimeError(
            "Notion-Zugang fehlt. Bitte NOTION_TOKEN und NOTION_DATABASE_ID "
            "in der .env-Datei setzen (siehe .env.example)."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    seiten = _alle_seiten_abfragen(database_id, headers)
    return [_seite_zu_rohdaten(seite) for seite in seiten]


def _alle_seiten_abfragen(database_id: str, headers: dict) -> list[dict]:
    """Ruft alle Zeilen der Datenbank ab (mit Paginierung)."""
    url = f"{NOTION_API}/databases/{database_id}/query"
    ergebnisse: list[dict] = []
    payload: dict = {"page_size": 100}

    while True:
        antwort = requests.post(url, headers=headers, json=payload, timeout=30)
        if antwort.status_code != 200:
            raise RuntimeError(
                f"Notion-API Fehler {antwort.status_code}: {antwort.text}"
            )
        daten = antwort.json()
        ergebnisse.extend(daten.get("results", []))
        if not daten.get("has_more"):
            break
        payload["start_cursor"] = daten["next_cursor"]

    return ergebnisse


def _seite_zu_rohdaten(seite: dict) -> dict:
    """Wandelt eine Notion-Seite in ein flaches dict {Spaltentitel: Text}."""
    roh: dict = {}
    for titel, prop in seite.get("properties", {}).items():
        roh[titel] = _property_zu_text(prop)
    return roh


def _property_zu_text(prop: dict) -> str:
    """Normalisiert einen beliebigen Notion-Property-Typ zu Text."""
    typ = prop.get("type")

    if typ in ("title", "rich_text"):
        return "".join(t.get("plain_text", "") for t in prop.get(typ, []))
    if typ == "select":
        auswahl = prop.get("select")
        return auswahl.get("name", "") if auswahl else ""
    if typ == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
    if typ == "status":
        status = prop.get("status")
        return status.get("name", "") if status else ""
    if typ == "date":
        datum = prop.get("date")
        return datum.get("start", "") if datum else ""
    if typ == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    if typ == "number":
        zahl = prop.get("number")
        return "" if zahl is None else str(zahl)
    if typ in ("phone_number", "email", "url"):
        return prop.get(typ) or ""
    if typ == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    if typ == "formula":
        formel = prop.get("formula", {})
        return _formel_zu_text(formel)

    # Unbekannter Typ -> leer
    return ""


def _formel_zu_text(formel: dict) -> str:
    typ = formel.get("type")
    if typ == "string":
        return formel.get("string") or ""
    if typ == "number":
        zahl = formel.get("number")
        return "" if zahl is None else str(zahl)
    if typ == "boolean":
        return "true" if formel.get("boolean") else "false"
    if typ == "date":
        datum = formel.get("date")
        return datum.get("start", "") if datum else ""
    return ""
