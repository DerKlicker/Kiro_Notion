"""Kommandozeilen-Interface.

Beispiele:
    python -m vereinsstatistik.cli inspect
    python -m vereinsstatistik.cli fetch --out data.json
    python -m vereinsstatistik.cli test-connection
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .fetch import fetch_all
from .inspector import inspect
from .notion_client import NotionClient, NotionError


def _client(cfg) -> NotionClient:
    return NotionClient(cfg.notion_token, api_version=cfg.notion.api_version)


def cmd_test_connection(args) -> int:
    cfg = load_config()
    if not cfg.notion_token:
        print("FEHLER: Kein NOTION_TOKEN gesetzt (.env oder Umgebung).", file=sys.stderr)
        return 2
    try:
        with _client(cfg) as client:
            dbs = client.search_databases()
        print(f"OK — Verbindung steht. {len(dbs)} Datenbank(en) für die Integration sichtbar:")
        for db in dbs:
            title = ""
            if isinstance(db.get("title"), list):
                title = "".join(t.get("plain_text", "") for t in db["title"])
            print(f"  - {title or '(ohne Titel)'}  [{db.get('id')}]")
        return 0
    except NotionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


def cmd_inspect(args) -> int:
    cfg = load_config()
    try:
        with _client(cfg) as client:
            report = inspect(cfg, client)
    except NotionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    for key, entry in report["databases"].items():
        print(f"\n=== {key} ===")
        if not entry.get("configured"):
            print(f"  {entry.get('note')}")
            continue
        if entry.get("error"):
            print(f"  FEHLER: {entry['error']}")
            continue
        ds = entry["data_source"]
        print(f"  Data Source: {ds['title']}  [{ds['id']}]")
        print("  Properties:")
        for f in ds["fields"]:
            print(f"    - {f['name']}  ({f['type']})")
        print("  Mapping-Check:")
        for m in entry["mapping"]:
            if m["optional"]:
                mark = "·"
            else:
                mark = "✓" if m["exists"] else "✗"
            print(f"    {mark} {m['internal']} -> {m['notion'] or '(leer)'}")
    return 0


def cmd_fetch(args) -> int:
    cfg = load_config()
    try:
        with _client(cfg) as client:
            data = fetch_all(cfg, client)
    except NotionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print("Abgerufen:", data["_meta"])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"Gespeichert nach {args.out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vereinsstatistik")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("test-connection", help="Token & Sichtbarkeit der DBs prüfen")
    sub.add_parser("inspect", help="Struktur & Feld-Mapping der DBs anzeigen")

    p_fetch = sub.add_parser("fetch", help="Daten abrufen")
    p_fetch.add_argument("--out", help="Pfad für JSON-Ausgabe", default=None)

    args = parser.parse_args(argv)
    return {
        "test-connection": cmd_test_connection,
        "inspect": cmd_inspect,
        "fetch": cmd_fetch,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
