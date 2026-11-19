"""Weboberfläche zum Pflegen von Token und Konfiguration.

Eine kleine FastAPI-App. Du kannst:
  * den Notion-Token eintragen (-> .env),
  * die Verbindung testen,
  * sichtbare Datenbanken auflisten und je Rolle (Mitglieder/Gruppenstunden/
    Lager) zuordnen,
  * die Struktur inspizieren und das Feld-Mapping prüfen,
  * alles in config.yaml speichern.

Start:  python -m vereinsstatistik.web   ->  http://localhost:8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import sync as sync_modul
from .analysis import analyze
from .config import ensure_config_initialized, load_config, save_config, save_token
from .fetch import fetch_all
from .inspector import inspect
from .notion_client import NotionClient, NotionError
from .sync import SyncError

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Beim Start eine fehlende config.yaml aus der Vorlage anlegen.

    Nötig für die reine TrueNAS-App-Variante, in der der Nutzer nie eine Shell
    öffnet und daher keine config.yaml anlegen kann. Idempotent; eine
    bestehende Datei wird nicht angetastet.
    """
    ensure_config_initialized()
    yield


app = FastAPI(title="Vereinsstatistik — Konfiguration", lifespan=lifespan)


def _client():
    cfg = load_config()
    if not cfg.notion_token:
        raise NotionError("Kein NOTION_TOKEN gesetzt. Bitte oben eintragen und speichern.")
    return cfg, NotionClient(cfg.notion_token, api_version=cfg.notion.api_version)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "cfg": cfg,
            "has_token": bool(cfg.notion_token),
        },
    )


@app.post("/api/token")
def set_token(token: str = Form(...)):
    token = token.strip()
    if not token:
        return JSONResponse({"ok": False, "error": "Token ist leer."}, status_code=400)
    save_token(token)
    return {"ok": True}


@app.get("/api/test")
def test_connection():
    try:
        cfg, client = _client()
        with client:
            dbs = client.search_databases()
        out = []
        for db in dbs:
            title = ""
            if isinstance(db.get("title"), list):
                title = "".join(t.get("plain_text", "") for t in db["title"])
            out.append(
                {
                    "id": db.get("id"),
                    "title": title or "(ohne Titel)",
                    "object": db.get("object"),
                    "database_id": (db.get("parent") or {}).get("database_id", ""),
                }
            )
        return {"ok": True, "databases": out}
    except NotionError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/inspect")
def api_inspect():
    try:
        cfg, client = _client()
        with client:
            report = inspect(cfg, client)
        return {"ok": True, "report": report}
    except NotionError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/config")
async def save_configuration(request: Request):
    """Komplette Konfiguration (ohne Token) aus der UI übernehmen."""
    payload: Dict[str, Any] = await request.json()
    cfg = load_config()

    for key in ("mitglieder", "gruppenstunden", "lager"):
        incoming = payload.get("databases", {}).get(key)
        if incoming is None:
            continue
        dbcfg = cfg.databases.setdefault(
            key, cfg.databases.get(key)  # type: ignore[arg-type]
        )
        if dbcfg is None:
            from .config import DatabaseConfig

            dbcfg = DatabaseConfig()
            cfg.databases[key] = dbcfg
        dbcfg.database_id = incoming.get("database_id", dbcfg.database_id) or ""
        dbcfg.data_source_id = incoming.get("data_source_id", dbcfg.data_source_id) or ""
        if "fields" in incoming and isinstance(incoming["fields"], dict):
            dbcfg.fields = {k: v for k, v in incoming["fields"].items()}

    analysis = payload.get("analysis")
    if isinstance(analysis, dict):
        cfg.analysis.only_active_members = bool(
            analysis.get("only_active_members", cfg.analysis.only_active_members)
        )
        cfg.analysis.bundesland = analysis.get("bundesland", cfg.analysis.bundesland) or ""

    save_config(cfg)
    return {"ok": True}


@app.post("/api/sync")
def api_sync():
    """Einen kompletten Sync per Klick auslösen: fetch -> analyze -> PostgreSQL.

    Serverseitiger Ablauf (synchron, für dieses Tool ausreichend; die UI zeigt
    währenddessen "läuft…"):

      1. Konfiguration laden und Notion-Client bauen (wirft NotionError ohne
         Token).
      2. Alle drei Notion-Datenbanken abrufen (``fetch_all``).
      3. Kennzahlen berechnen (``analyze``).
      4. Datenbankschema idempotent anlegen (``sync.init_db``), damit auch der
         allererste Klick ohne vorher angelegtes Schema funktioniert.
      5. Report als neuen Lauf nach PostgreSQL schreiben (``sync.write_report``).

    Fehler werden als ``{"ok": false, "error": "..."}`` mit HTTP 400 und
    verständlicher deutscher Meldung zurückgegeben (NotionError, SyncError).
    """
    try:
        cfg, client = _client()
        with client:
            daten = fetch_all(cfg, client)
        report = analyze(daten, cfg)

        verbindung = sync_modul.connect(cfg)
        try:
            sync_modul.init_db(cfg, conn=verbindung)
            run_id = sync_modul.write_report(report, cfg, conn=verbindung)
        finally:
            verbindung.close()

        meta = daten.get("_meta") or {}
        top_flop = report.get("top_flop_anwesenheit") or []
        top1 = top_flop[0] if top_flop else None
        flop1 = top_flop[-1] if top_flop else None

        return {
            "ok": True,
            "run_id": run_id,
            "zusammenfassung": {
                "anzahl_mitglieder": meta.get("mitglieder"),
                "anzahl_gruppenstunden": meta.get("gruppenstunden"),
                "anzahl_lager": meta.get("lager"),
                "top_1": top1,
                "flop_1": flop1,
                "run_id": run_id,
            },
        }
    except (NotionError, SyncError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
