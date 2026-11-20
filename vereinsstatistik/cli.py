"""Kommandozeilen-Interface.

Beispiele:
    python -m vereinsstatistik.cli inspect
    python -m vereinsstatistik.cli fetch --out data.json
    python -m vereinsstatistik.cli analyze --out report.json
    python -m vereinsstatistik.cli analyze --in data.json --out report.json
    python -m vereinsstatistik.cli test-connection
"""
from __future__ import annotations

import argparse
import json
import sys

from . import sync
from .analysis import analyze, load_data
from .config import load_config
from .fetch import fetch_all
from .inspector import inspect
from .notion_client import NotionClient, NotionError
from .sync import SyncError


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


WOCHENTAGE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]


def _print_analyse_zusammenfassung(report) -> None:
    """Lesbare deutsche Zusammenfassung des Reports auf der Konsole ausgeben.

    Stil konsistent mit cmd_inspect/cmd_fetch (einfache print-Ausgaben).
    """
    # Die mitgliederbezogenen Kennzahlen tragen seit der Jahres-Dimension ein
    # Feld ``jahr`` (None = "alle Jahre"-Aggregat). Die Konsolen-Zusammenfassung
    # zeigt bewusst das "alle Jahre"-Aggregat (jahr is None).
    def _nur_alle_jahre(zeilen):
        gefiltert = [z for z in zeilen or [] if z.get("jahr") is None]
        # Fallback fuer aeltere Reports ohne Jahres-Feld: alles nehmen.
        return gefiltert if gefiltert else list(zeilen or [])

    gesamt_liste = report.get("gesamtkennzahlen") or []
    gk_alle = _nur_alle_jahre(gesamt_liste)
    gk = gk_alle[0] if gk_alle else {}
    print("Zusammenfassung (alle Jahre):")
    print(f"  Mitglieder gesamt:        {gk.get('anzahl_mitglieder_gesamt')}")
    print(f"  davon aktiv:              {gk.get('anzahl_aktive_mitglieder')}")
    print(f"  Gruppenstunden:           {gk.get('anzahl_gruppenstunden')}")
    print(f"  Lager:                    {gk.get('anzahl_lager')}")
    print(f"  Schnitt anwesend/Stunde:  {gk.get('schnitt_anwesend_pro_stunde')}")
    print(f"  Gesamtbeteiligungsquote:  {gk.get('gesamtbeteiligungsquote')} %")

    # Top-3 und Flop-3 Anwesenheit (absteigend sortierte Liste, alle Jahre).
    top_flop = _nur_alle_jahre(report.get("top_flop_anwesenheit"))
    if top_flop:
        print("\nTop-3 Anwesenheit:")
        for z in top_flop[:3]:
            print(f"  {z['rang']}. {z['name']}: {z['anwesend_absolut']} Teilnahme(n)")
        print("Flop-3 Anwesenheit:")
        for z in list(reversed(top_flop))[:3]:
            print(f"  {z['name']}: {z['anwesend_absolut']} Teilnahme(n)")

    # Hoechste Risiko-Mitglieder. Nicht bewertbare Mitglieder (Score None)
    # werden hier nicht als Hochrisiko einsortiert, sondern ans Ende gestellt.
    risiko = sorted(
        report.get("risiko_score") or [],
        key=lambda z: (-(z["risiko_score"] if z.get("risiko_score") is not None else -1.0), z["name"]),
    )
    if risiko:
        print("\nHoechstes Dropout-Risiko:")
        for z in risiko[:3]:
            score_text = z["risiko_score"] if z["risiko_score"] is not None else "n/a"
            print(
                f"  {z['name']}: Score {score_text} ({z['risiko_stufe']}), "
                f"{z['stunden_seit_letzter_anwesenheit']} Stunde(n) seit letzter Anwesenheit"
            )

    # Kurze Saison-Hinweise (staerkster Monat und Wochentag, alle Jahre).
    saison = report.get("saisonalitaet") or {}
    pro_monat = _nur_alle_jahre(saison.get("pro_monat"))
    pro_wochentag = saison.get("pro_wochentag") or []
    if pro_monat or pro_wochentag:
        print("\nSaison-Hinweise:")
        if pro_monat:
            bester_monat = max(pro_monat, key=lambda m: m["schnitt_anwesend"])
            print(
                f"  Staerkster Monat: {bester_monat['monat']:02d} "
                f"(Schnitt {bester_monat['schnitt_anwesend']} anwesend)"
            )
        if pro_wochentag:
            bester_wtag = max(pro_wochentag, key=lambda w: w["schnitt_anwesend"])
            name = WOCHENTAGE[bester_wtag["wochentag"]] if 0 <= bester_wtag["wochentag"] < 7 else str(bester_wtag["wochentag"])
            print(
                f"  Staerkster Wochentag: {name} "
                f"(Schnitt {bester_wtag['schnitt_anwesend']} anwesend)"
            )

    # Kurze Thema-Hinweise (bestes Thema nach Durchschnitt, alle Jahre).
    themen = _nur_alle_jahre(report.get("thema_ranking"))
    if themen:
        bestes = themen[0]
        print("\nThema-Hinweise:")
        print(
            f"  Bestbesuchtes Thema ({bestes['thema_quelle']}): "
            f"{bestes['thema_key']} (Schnitt {bestes['schnitt_anwesend']} anwesend)"
        )


def cmd_analyze(args) -> int:
    cfg = load_config()

    if args.in_path:
        # Aus gespeichertem JSON laden - kein Notion-Abruf.
        try:
            data = load_data(args.in_path)
        except (OSError, ValueError) as exc:
            print(f"FEHLER: Daten konnten nicht geladen werden: {exc}", file=sys.stderr)
            return 1
    else:
        # Live aus Notion abrufen, analog cmd_fetch.
        try:
            with _client(cfg) as client:
                data = fetch_all(cfg, client)
        except NotionError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1

    report = analyze(data, cfg)
    _print_analyse_zusammenfassung(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"Gespeichert nach {args.out}")
    return 0


def cmd_init_db(args) -> int:
    """Das PostgreSQL-Schema anlegen (idempotent)."""
    cfg = load_config()
    try:
        sync.init_db(cfg)
    except SyncError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    print(
        f"Schema initialisiert in Datenbank {cfg.postgres.database}, "
        f"Schema {cfg.postgres.schema_}."
    )
    return 0


def cmd_sync(args) -> int:
    """Kennzahlen berechnen und als Lauf nach PostgreSQL schreiben."""
    cfg = load_config()

    if args.in_path:
        # Aus gespeichertem JSON laden - kein Notion-Abruf.
        try:
            data = load_data(args.in_path)
        except (OSError, ValueError) as exc:
            print(f"FEHLER: Daten konnten nicht geladen werden: {exc}", file=sys.stderr)
            return 1
    else:
        # Live aus Notion abrufen, analog cmd_fetch.
        try:
            with _client(cfg) as client:
                data = fetch_all(cfg, client)
        except NotionError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1

    report = analyze(data, cfg)

    try:
        if args.init_db:
            sync.init_db(cfg)
        run_id = sync.write_report(report, cfg)
    except SyncError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(
        f"Lauf gespeichert (run_id={run_id}) nach PostgreSQL "
        f"{cfg.postgres.database}@{cfg.postgres.host}:{cfg.postgres.port}."
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vereinsstatistik")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("test-connection", help="Token & Sichtbarkeit der DBs prüfen")
    sub.add_parser("inspect", help="Struktur & Feld-Mapping der DBs anzeigen")

    p_fetch = sub.add_parser("fetch", help="Daten abrufen")
    p_fetch.add_argument("--out", help="Pfad für JSON-Ausgabe", default=None)

    p_analyze = sub.add_parser("analyze", help="Kennzahlen berechnen (live aus Notion oder aus JSON)")
    p_analyze.add_argument(
        "--in",
        dest="in_path",
        default=None,
        help="Pfad zu zuvor per fetch gespeicherter JSON (ohne Notion-Abruf)",
    )
    p_analyze.add_argument("--out", default=None, help="Pfad für JSON-Report")

    sub.add_parser("init-db", help="PostgreSQL-Schema anlegen (idempotent)")

    p_sync = sub.add_parser(
        "sync",
        help="Kennzahlen berechnen und als Lauf nach PostgreSQL schreiben",
    )
    p_sync.add_argument(
        "--in",
        dest="in_path",
        default=None,
        help="Pfad zu zuvor per fetch gespeicherter JSON (ohne Notion-Abruf)",
    )
    p_sync.add_argument(
        "--init-db",
        dest="init_db",
        action="store_true",
        help="Vor dem Schreiben das Schema initialisieren",
    )

    args = parser.parse_args(argv)
    return {
        "test-connection": cmd_test_connection,
        "inspect": cmd_inspect,
        "fetch": cmd_fetch,
        "analyze": cmd_analyze,
        "init-db": cmd_init_db,
        "sync": cmd_sync,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
