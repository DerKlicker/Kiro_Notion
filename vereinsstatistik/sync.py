"""Analyse-Reports nach PostgreSQL schreiben (Phase 3).

Dieses Modul uebernimmt den Report aus ``analysis.analyze`` und speichert ihn
als Snapshot in einer PostgreSQL-Datenbank. Jeder Lauf erhaelt eine eigene
``run_id`` (Zeile in der Tabelle ``laeufe``); alle Kennzahl-Zeilen verweisen
per run_id auf diesen Lauf. So entstehen Zeitreihen, die sich in Grafana
auswerten lassen.

Entwurfsgrundsaetze:

* Alle SQL-Werte werden ausschliesslich parametrisiert uebergeben (keine
  String-Interpolation von Werten). Nur der Schema-Qualifier wird kontrolliert
  gesetzt und vorher gegen eine Whitelist validiert.
* Die Transaktion wird am Ende committet; bei einem Fehler erfolgt ein
  Rollback und es wird eine ``SyncError`` mit deutscher Meldung geworfen.
* Das SQL-Schema liegt als Package-Ressource ``db/schema.sql`` und wird mit
  dem konfigurierten Schemanamen formatiert.
"""
from __future__ import annotations

import re
from importlib import resources
from typing import Any, Dict, Optional

import psycopg

# Erlaubte Zeichen fuer einen Schemanamen. Bewusst eng gehalten, damit der Name
# gefahrlos in das SQL interpoliert werden kann (Schutz vor SQL-Injection).
_SCHEMA_REGEX = re.compile(r"^[A-Za-z0-9_]+$")


class SyncError(Exception):
    """Fehler beim Synchronisieren nach PostgreSQL.

    Analog zu ``NotionError`` traegt diese Ausnahme eine deutsche Meldung, die
    in der CLI direkt mit dem Praefix ``FEHLER:`` ausgegeben werden kann.
    """


def _validierter_schemaname(cfg: Any) -> str:
    """Den konfigurierten Schemanamen pruefen und zurueckgeben.

    Nur Namen aus Buchstaben, Ziffern und Unterstrichen sind erlaubt. Alles
    andere fuehrt zu einer ``SyncError``, damit der Name sicher in das SQL
    interpoliert werden kann.
    """
    schema = cfg.postgres.schema_
    if not schema or not _SCHEMA_REGEX.match(schema):
        raise SyncError(
            "Ungueltiger Schemaname in der config.yaml (postgres.schema). "
            "Erlaubt sind nur Buchstaben, Ziffern und Unterstriche."
        )
    return schema


def _pruefe_voraussetzungen(cfg: Any) -> None:
    """Vorab-Pruefungen mit klaren deutschen Fehlermeldungen.

    Prueft, ob PostgreSQL aktiviert ist und ob ein Passwort vorliegt. Bei
    Verstoessen wird eine ``SyncError`` geworfen.
    """
    if not cfg.postgres.enabled:
        raise SyncError(
            "PostgreSQL ist in der config.yaml deaktiviert (postgres.enabled=false)."
        )
    if not cfg.pg_password:
        raise SyncError("Kein PG_PASSWORD gesetzt (.env oder Umgebung).")


def connect(cfg: Any):
    """Eine psycopg-Verbindung aus PostgresConfig und cfg.pg_password aufbauen.

    Fuehrt zuvor die Vorab-Pruefungen aus (aktiviert, Passwort vorhanden).
    Schlaegt der Verbindungsaufbau fehl, wird eine ``SyncError`` mit deutscher
    Meldung geworfen.
    """
    _pruefe_voraussetzungen(cfg)
    pg = cfg.postgres
    try:
        return psycopg.connect(
            host=pg.host,
            port=pg.port,
            dbname=pg.database,
            user=pg.user,
            password=cfg.pg_password,
        )
    except psycopg.Error as exc:
        raise SyncError(f"Verbindung zur PostgreSQL-Datenbank fehlgeschlagen: {exc}") from exc


def _schema_sql(schema: str) -> str:
    """Das SQL-Schema laden und {schema} durch den validierten Namen ersetzen."""
    roh = resources.files(__package__).joinpath("db/schema.sql").read_text(encoding="utf-8")
    return roh.replace("{schema}", schema)


def init_db(cfg: Any, conn=None) -> None:
    """Das Schema in der Datenbank anlegen (idempotent).

    Liest ``db/schema.sql``, ersetzt den Platzhalter {schema} durch den
    validierten Schemanamen und fuehrt das Skript in einer Transaktion aus. Wird
    keine Verbindung uebergeben, wird selbst eine aufgebaut und wieder
    geschlossen.
    """
    schema = _validierter_schemaname(cfg)
    sql = _schema_sql(schema)

    eigene_verbindung = conn is None
    verbindung = conn or connect(cfg)
    try:
        with verbindung.cursor() as cur:
            cur.execute(sql)
        verbindung.commit()
    except psycopg.Error as exc:
        verbindung.rollback()
        raise SyncError(f"Schema konnte nicht initialisiert werden: {exc}") from exc
    finally:
        if eigene_verbindung:
            verbindung.close()


def _q(schema: str, tabelle: str) -> str:
    """Einen kontrolliert qualifizierten Tabellennamen bauen.

    ``schema`` ist bereits validiert und ``tabelle`` stammt ausschliesslich aus
    konstanten Literalen in diesem Modul - es fliessen keine Nutzerwerte ein.
    """
    return f"{schema}.{tabelle}"


def write_report(report: Dict[str, Any], cfg: Any, conn=None) -> int:
    """Einen Analyse-Report als neuen Snapshot schreiben und run_id liefern.

    Oeffnet eine Transaktion, legt eine Zeile in ``laeufe`` an (run_id per
    RETURNING), und schreibt anschliessend alle Kennzahl-Zeilen mit dieser
    run_id. Jeder Aufruf erzeugt einen neuen Lauf (kein Upsert); historische
    Laeufe bleiben erhalten.

    Alle Werte werden parametrisiert uebergeben; nur der Schema-Qualifier wird
    kontrolliert gesetzt. Bei Fehlern erfolgt ein Rollback und es wird eine
    ``SyncError`` mit deutscher Meldung geworfen.
    """
    schema = _validierter_schemaname(cfg)

    eigene_verbindung = conn is None
    verbindung = conn or connect(cfg)
    try:
        with verbindung.cursor() as cur:
            run_id = _schreibe_lauf(cur, schema, report)
            _schreibe_kennzahlen(cur, schema, run_id, report)
        verbindung.commit()
        return run_id
    except SyncError:
        verbindung.rollback()
        raise
    except psycopg.Error as exc:
        verbindung.rollback()
        raise SyncError(f"Lauf konnte nicht gespeichert werden: {exc}") from exc
    finally:
        if eigene_verbindung:
            verbindung.close()


def _schreibe_lauf(cur, schema: str, report: Dict[str, Any]) -> int:
    """Die Lauf-Zeile einfuegen und die erzeugte run_id zurueckgeben."""
    meta = report.get("_meta") or {}
    cur.execute(
        f"INSERT INTO {_q(schema, 'laeufe')} "
        "(only_active_members, bundesland, anzahl_mitglieder, "
        "anzahl_gruppenstunden, anzahl_lager) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING run_id",
        (
            meta.get("only_active_members"),
            meta.get("bundesland"),
            meta.get("anzahl_mitglieder"),
            meta.get("anzahl_gruppenstunden"),
            meta.get("anzahl_lager"),
        ),
    )
    zeile = cur.fetchone()
    if not zeile:
        raise SyncError("Konnte keine run_id aus der laeufe-Tabelle lesen.")
    return zeile[0]


def _schreibe_kennzahlen(cur, schema: str, run_id: int, report: Dict[str, Any]) -> None:
    """Alle Kennzahl-Zeilen mit der gegebenen run_id einfuegen."""
    # Kennzahl 1: Top/Flop-Anwesenheit (mit Jahres-Dimension; jahr=None schreibt
    # SQL NULL = "alle Jahre"-Aggregat, sonst das konkrete Kalenderjahr).
    zeilen = [
        (run_id, z.get("jahr"), z.get("mitglied_id"), z.get("name"), z.get("anwesend_absolut"), z.get("rang"))
        for z in report.get("top_flop_anwesenheit") or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_top_flop_anwesenheit')} "
            "(run_id, jahr, mitglied_id, name, anwesend_absolut, rang) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            zeilen,
        )

    # Kennzahl 2: Faire Beteiligung (quote_prozent kann None sein; mit
    # Jahres-Dimension, jahr=None = "alle Jahre").
    zeilen = [
        (
            run_id,
            z.get("jahr"),
            z.get("mitglied_id"),
            z.get("name"),
            z.get("moegliche_stunden"),
            z.get("anwesend"),
            z.get("quote_prozent"),
        )
        for z in report.get("faire_beteiligung") or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_faire_beteiligung')} "
            "(run_id, jahr, mitglied_id, name, moegliche_stunden, anwesend, quote_prozent) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            zeilen,
        )

    # Kennzahl 3: Risiko (mehrere Felder koennen None sein).
    zeilen = [
        (
            run_id,
            z.get("mitglied_id"),
            z.get("name"),
            z.get("bewertbar"),
            z.get("quote_letzte_n"),
            z.get("quote_davor"),
            z.get("stunden_seit_letzter_anwesenheit"),
            z.get("risiko_score"),
            z.get("risiko_stufe"),
        )
        for z in report.get("risiko_score") or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_risiko')} "
            "(run_id, mitglied_id, name, bewertbar, quote_letzte_n, quote_davor, "
            "stunden_seit_letzter_anwesenheit, risiko_score, risiko_stufe) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            zeilen,
        )

    # Kennzahl 4: Saisonalitaet pro Monat. Eine Auswertung pro Wochentag gibt es
    # bewusst nicht mehr (Gruppenstunden sind immer samstags), daher wird nur
    # noch pro_monat geschrieben.
    saison = report.get("saisonalitaet") or {}
    zeilen = [
        (run_id, z.get("jahr"), z.get("monat"), z.get("anzahl_stunden"), z.get("summe_anwesend"), z.get("schnitt_anwesend"))
        for z in saison.get("pro_monat") or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_saisonalitaet_monat')} "
            "(run_id, jahr, monat, anzahl_stunden, summe_anwesend, schnitt_anwesend) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            zeilen,
        )

    # Kennzahl 5: Thema-Ranking (thema_key traegt im Normalfall den lesbaren
    # Themennamen aus dem Rollup "Grafana_Name"; thema_quelle dokumentiert die
    # Herkunft: 'name' | 'relation' | 'titel').
    zeilen = [
        (run_id, z.get("jahr"), z.get("thema_key"), z.get("thema_quelle"), z.get("anzahl_stunden"), z.get("schnitt_anwesend"))
        for z in report.get("thema_ranking") or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_thema_ranking')} "
            "(run_id, jahr, thema_key, thema_quelle, anzahl_stunden, schnitt_anwesend) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            zeilen,
        )

    # Kennzahl 6: Lager-Korrelation (zwei Gruppen-Zeilen, differenz je gleich).
    lager = report.get("lager_korrelation") or {}
    differenz = lager.get("differenz")
    zeilen = []
    for gruppe in ("lagerteilnehmer", "nicht_teilnehmer"):
        eintrag = lager.get(gruppe) or {}
        zeilen.append(
            (run_id, gruppe, eintrag.get("anzahl"), eintrag.get("schnitt_quote"), differenz)
        )
    cur.executemany(
        f"INSERT INTO {_q(schema, 'kennzahl_lager_korrelation')} "
        "(run_id, gruppe, anzahl, schnitt_quote, differenz) "
        "VALUES (%s, %s, %s, %s, %s)",
        zeilen,
    )

    # Kennzahl 7: Puenktlichkeit. Ist verfuegbar=false, wird eine einzelne Zeile
    # ohne Mitglied geschrieben, damit der Zustand im Snapshot erhalten bleibt.
    puenktlichkeit = report.get("puenktlichkeit") or {}
    verfuegbar = bool(puenktlichkeit.get("verfuegbar"))
    pro_mitglied = puenktlichkeit.get("pro_mitglied") or []
    if verfuegbar and pro_mitglied:
        zeilen = [
            (run_id, True, z.get("mitglied_id"), z.get("name"), z.get("verspaetungen"))
            for z in pro_mitglied
        ]
    else:
        zeilen = [(run_id, verfuegbar, None, None, None)]
    cur.executemany(
        f"INSERT INTO {_q(schema, 'kennzahl_puenktlichkeit')} "
        "(run_id, verfuegbar, mitglied_id, name, verspaetungen) "
        "VALUES (%s, %s, %s, %s, %s)",
        zeilen,
    )

    # Kennzahl 8: Gesamtkennzahlen (je Jahr eine Zeile plus "alle Jahre"-Aggregat
    # mit jahr=None). Seit der Jahres-Dimension ist dies eine Liste von dicts.
    gesamt_liste = report.get("gesamtkennzahlen")
    if isinstance(gesamt_liste, dict):
        # Ruecksicht auf aeltere Report-Form (ein einzelnes dict ohne Jahr).
        gesamt_liste = [dict(gesamt_liste, jahr=gesamt_liste.get("jahr"))]
    zeilen = [
        (
            run_id,
            g.get("jahr"),
            g.get("anzahl_aktive_mitglieder"),
            g.get("anzahl_mitglieder_gesamt"),
            g.get("anzahl_gruppenstunden"),
            g.get("anzahl_lager"),
            g.get("schnitt_anwesend_pro_stunde"),
            g.get("gesamtbeteiligungsquote"),
            g.get("gesamtbeteiligungsquote_roh"),
        )
        for g in gesamt_liste or []
    ]
    if zeilen:
        cur.executemany(
            f"INSERT INTO {_q(schema, 'kennzahl_gesamt')} "
            "(run_id, jahr, anzahl_aktive_mitglieder, anzahl_mitglieder_gesamt, "
            "anzahl_gruppenstunden, anzahl_lager, schnitt_anwesend_pro_stunde, "
            "gesamtbeteiligungsquote, gesamtbeteiligungsquote_roh) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            zeilen,
        )
