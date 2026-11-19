"""Daten aus den drei Notion-Datenbanken abrufen und ins interne Format bringen.

Ergebnis ist ein einfaches dict mit Listen von Datensätzen (Mitglieder,
Gruppenstunden, Lager). Relations werden als Listen von Notion-Page-IDs
abgebildet; die Verknüpfung (welches Mitglied war in welcher Stunde) stellt
die Auswertung in Phase 2 über diese IDs her.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .config import Config
from .notion_client import NotionClient
from .properties import map_page


def _fetch_db(client: NotionClient, cfg: Config, key: str) -> List[Dict[str, Any]]:
    dbcfg = cfg.db(key)
    if not dbcfg.is_configured():
        return []
    dsid = client.resolve_data_source_id(dbcfg.database_id, dbcfg.data_source_id)
    pages = client.fetch_all_pages(dsid)
    return [map_page(p, dbcfg.fields) for p in pages]


def fetch_all(cfg: Config, client: NotionClient) -> Dict[str, Any]:
    """Alle drei Datenbanken abrufen.

    Rückgabe:
        {
          "mitglieder":     [ {...}, ... ],
          "gruppenstunden": [ {...}, ... ],
          "lager":          [ {...}, ... ],
          "_meta": { Zählungen }
        }
    """
    data: Dict[str, Any] = {}
    for key in ("mitglieder", "gruppenstunden", "lager"):
        data[key] = _fetch_db(client, cfg, key)
    data["_meta"] = {k: len(v) for k, v in data.items() if not k.startswith("_")}
    return data
