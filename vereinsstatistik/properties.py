"""Notion-Property-Werte in einfache Python-Werte umwandeln.

Notion liefert jede Property als verschachteltes Objekt mit ``type``-Feld.
Diese Helfer extrahieren daraus den "nackten" Wert (Text, Datum, Liste von
Relations-IDs, Zahl, Bool …), damit die Auswertung mit normalen Werten rechnet.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def rich_text_to_plain(items: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in items or []).strip()


def extract_value(prop: Dict[str, Any]) -> Any:
    """Einen einzelnen Property-Wert extrahieren, abhängig vom Typ."""
    if not prop:
        return None
    ptype = prop.get("type")

    if ptype == "title":
        return rich_text_to_plain(prop.get("title", []))
    if ptype == "rich_text":
        return rich_text_to_plain(prop.get("rich_text", []))
    if ptype == "number":
        return prop.get("number")
    if ptype == "checkbox":
        return bool(prop.get("checkbox"))
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    if ptype == "status":
        st = prop.get("status")
        return st.get("name") if st else None
    if ptype == "multi_select":
        return [o.get("name") for o in prop.get("multi_select", [])]
    if ptype == "date":
        d = prop.get("date")
        if not d:
            return None
        # Start zurückgeben; Ende separat über extract_date_end() erreichbar.
        return d.get("start")
    if ptype == "relation":
        return [r.get("id") for r in prop.get("relation", [])]
    if ptype == "people":
        return [p.get("name") or p.get("id") for p in prop.get("people", [])]
    if ptype == "email":
        return prop.get("email")
    if ptype == "phone_number":
        return prop.get("phone_number")
    if ptype == "url":
        return prop.get("url")
    if ptype == "formula":
        f = prop.get("formula", {})
        return f.get(f.get("type"))
    if ptype == "rollup":
        r = prop.get("rollup", {})
        rtype = r.get("type")
        if rtype == "array":
            return [extract_value(x) for x in r.get("array", [])]
        return r.get(rtype)
    if ptype == "unique_id":
        uid = prop.get("unique_id", {})
        prefix = uid.get("prefix") or ""
        return f"{prefix}{uid.get('number')}"
    if ptype == "created_time":
        return prop.get("created_time")
    if ptype == "last_edited_time":
        return prop.get("last_edited_time")
    # Unbekannter Typ: Rohobjekt zurückgeben, damit nichts still verloren geht.
    return prop.get(ptype)


def extract_date_end(prop: Dict[str, Any]) -> Optional[str]:
    """Enddatum einer Date-Property (für Zeiträume, z. B. Lager)."""
    if prop and prop.get("type") == "date" and prop.get("date"):
        return prop["date"].get("end")
    return None


def page_title(page: Dict[str, Any]) -> str:
    """Titel einer Seite finden, egal wie die Title-Property heißt."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return rich_text_to_plain(prop.get("title", []))
    return ""


def map_page(page: Dict[str, Any], field_map: Dict[str, str]) -> Dict[str, Any]:
    """Eine Notion-Seite auf das interne Feld-Mapping reduzieren.

    ``field_map`` = {interner_name: notion_property_name}. Fehlende Properties
    (z. B. optionale Felder) ergeben ``None`` und führen nicht zum Fehler.
    """
    props = page.get("properties", {})
    out: Dict[str, Any] = {"_id": page.get("id")}
    for internal, notion_name in field_map.items():
        if not notion_name:
            out[internal] = None
            continue
        prop = props.get(notion_name)
        out[internal] = extract_value(prop) if prop else None
    return out
