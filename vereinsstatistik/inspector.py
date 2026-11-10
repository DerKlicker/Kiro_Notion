"""Notion-Struktur inspizieren.

Liest die konfigurierten Datenbanken aus und beschreibt deren Data Sources
und Properties (Name + Typ). Das erlaubt dir und der Web-UI zu sehen, was
tatsächlich verfügbar ist — ohne zu raten — und ob das Feld-Mapping passt.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .config import Config
from .notion_client import NotionClient


def describe_data_source(client: NotionClient, data_source_id: str) -> Dict[str, Any]:
    ds = client.get_data_source(data_source_id)
    props = ds.get("properties", {})
    fields = [
        {"name": name, "type": meta.get("type")}
        for name, meta in sorted(props.items())
    ]
    title = ""
    if isinstance(ds.get("title"), list):
        title = "".join(t.get("plain_text", "") for t in ds["title"])
    return {"id": data_source_id, "title": title, "fields": fields}


def inspect(cfg: Config, client: NotionClient) -> Dict[str, Any]:
    """Alle konfigurierten DBs beschreiben und Mapping-Probleme markieren."""
    report: Dict[str, Any] = {"databases": {}}

    for key, dbcfg in cfg.databases.items():
        entry: Dict[str, Any] = {"configured": dbcfg.is_configured()}
        if not dbcfg.is_configured():
            entry["note"] = "Keine database_id/data_source_id gesetzt."
            report["databases"][key] = entry
            continue
        try:
            dsid = client.resolve_data_source_id(
                dbcfg.database_id, dbcfg.data_source_id
            )
            described = describe_data_source(client, dsid)
            entry["data_source"] = described

            # Mapping prüfen: Zeigt jedes gemappte Feld auf eine echte Property?
            available = {f["name"] for f in described["fields"]}
            mapping_check: List[Dict[str, Any]] = []
            for internal, notion_name in dbcfg.fields.items():
                mapping_check.append(
                    {
                        "internal": internal,
                        "notion": notion_name,
                        "exists": bool(notion_name) and notion_name in available,
                        "optional": notion_name == "",
                    }
                )
            entry["mapping"] = mapping_check
        except Exception as exc:  # NotionError o. ä. -> im Report zeigen
            entry["error"] = str(exc)
        report["databases"][key] = entry

    return report
