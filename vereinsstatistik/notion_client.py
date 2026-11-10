"""Schlanker Notion-API-Client (REST, Version 2025-09-03 / Data Sources).

Seit dem Upgrade vom 2025-09-03 kann eine Notion-"Datenbank" mehrere
*Data Sources* enthalten. Der Abfrage-Endpunkt heißt jetzt
``POST /v1/data_sources/{data_source_id}/query`` statt
``POST /v1/databases/{database_id}/query``.

Workflow:
  1. ``GET /v1/databases/{database_id}``  -> liefert u. a. ``data_sources``
  2. ``GET /v1/data_sources/{data_source_id}`` -> Schema (Properties)
  3. ``POST /v1/data_sources/{data_source_id}/query`` -> Seiten (paginiert)

Der Client kümmert sich um Auth-Header, API-Version, Pagination und gibt
sprechende Fehlermeldungen (z. B. "DB nicht mit Integration geteilt").
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import httpx

API_BASE = "https://api.notion.com/v1"


class NotionError(RuntimeError):
    """Fehler bei einem Notion-API-Aufruf, mit nutzerfreundlichem Text."""


class NotionClient:
    def __init__(self, token: str, api_version: str = "2025-09-03", timeout: float = 30.0):
        if not token:
            raise NotionError(
                "Kein Notion-Token gesetzt. Trage ihn in der Web-UI ein oder "
                "setze die Umgebungsvariable NOTION_TOKEN."
            )
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": api_version,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    # -- Low level ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise NotionError(f"Netzwerkfehler beim Zugriff auf Notion: {exc}") from exc

        if resp.status_code == 401:
            raise NotionError(
                "Notion lehnt den Token ab (401). Ist NOTION_TOKEN korrekt und gültig?"
            )
        if resp.status_code == 404:
            raise NotionError(
                "Objekt nicht gefunden (404). Häufigste Ursache: Die Datenbank wurde "
                "nicht mit deiner Integration geteilt (••• → Connections) oder die ID "
                "ist falsch."
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except Exception:
                detail = resp.text[:300]
            raise NotionError(f"Notion-API-Fehler {resp.status_code}: {detail}")

        return resp.json()

    # -- High level ---------------------------------------------------------

    def get_database(self, database_id: str) -> Dict[str, Any]:
        """Datenbank-Metadaten inkl. Liste der Data Sources."""
        return self._request("GET", f"/databases/{database_id}")

    def get_data_source(self, data_source_id: str) -> Dict[str, Any]:
        """Schema (Properties, Titel, Parent) einer Data Source."""
        return self._request("GET", f"/data_sources/{data_source_id}")

    def resolve_data_source_id(
        self, database_id: str = "", data_source_id: str = ""
    ) -> str:
        """Eine abfragebare data_source_id ermitteln.

        Ist ``data_source_id`` gesetzt, wird sie direkt genutzt. Sonst wird die
        Datenbank aufgelöst; bei genau einer Data Source wird diese gewählt.
        """
        if data_source_id:
            return data_source_id
        if not database_id:
            raise NotionError("Weder database_id noch data_source_id angegeben.")

        db = self.get_database(database_id)
        sources = db.get("data_sources") or []
        if not sources:
            # Fallback für alte Workspaces: DB-ID == Data-Source-ID.
            return database_id
        if len(sources) == 1:
            return sources[0]["id"]
        names = ", ".join(f"{s.get('name', '?')} ({s['id']})" for s in sources)
        raise NotionError(
            "Diese Datenbank hat mehrere Data Sources. Bitte data_source_id in der "
            f"Konfiguration angeben. Verfügbar: {names}"
        )

    def iter_pages(
        self,
        data_source_id: str,
        page_size: int = 100,
        filter_: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Alle Seiten einer Data Source paginiert durchlaufen."""
        cursor: Optional[str] = None
        while True:
            body: Dict[str, Any] = {"page_size": page_size}
            if cursor:
                body["start_cursor"] = cursor
            if filter_:
                body["filter"] = filter_
            data = self._request(
                "POST", f"/data_sources/{data_source_id}/query", json=body
            )
            for page in data.get("results", []):
                yield page
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def fetch_all_pages(self, data_source_id: str, **kwargs) -> List[Dict[str, Any]]:
        return list(self.iter_pages(data_source_id, **kwargs))

    def search_databases(self) -> List[Dict[str, Any]]:
        """Alle für die Integration sichtbaren Datenbanken auflisten.

        Nützlich in der Web-UI, damit der Nutzer DBs per Dropdown wählen kann,
        statt IDs aus URLs zu kopieren.
        """
        results: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            body: Dict[str, Any] = {
                "filter": {"property": "object", "value": "data_source"},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            data = self._request("POST", "/search", json=body)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        # Fallback: ältere API-Versionen liefern "database"-Objekte.
        if not results:
            data = self._request(
                "POST",
                "/search",
                json={"filter": {"property": "object", "value": "database"}},
            )
            results = data.get("results", [])
        return results

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "NotionClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
