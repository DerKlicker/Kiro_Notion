-- Datenbank-Schema fuer die Vereinsstatistik (Phase 3).
--
-- Dieses Skript ist idempotent: Es verwendet durchgaengig
-- "CREATE ... IF NOT EXISTS" und kann daher gefahrlos mehrfach ausgefuehrt
-- werden. Der Platzhalter {schema} wird von sync.py durch den in der
-- config.yaml konfigurierten Schemanamen ersetzt. sync.py validiert den
-- Namen vorher gegen eine Whitelist ([A-Za-z0-9_]+), sodass hier keine
-- Injection moeglich ist.
--
-- Datenmodell: Jeder Analyse-Lauf ist ein eigener Snapshot. Die Tabelle
-- "laeufe" fuehrt einen Eintrag je Lauf (run_id). Alle Kennzahl-Tabellen
-- verweisen per run_id (ON DELETE CASCADE) auf diesen Lauf. So bleiben
-- historische Laeufe fuer Grafana-Zeitreihen erhalten und ein geloeschter
-- Lauf raeumt automatisch seine Kennzahl-Zeilen mit auf.

CREATE SCHEMA IF NOT EXISTS {schema};

-- Lauf-/Snapshot-Tabelle. Ein Eintrag je Analyse-Lauf.
CREATE TABLE IF NOT EXISTS {schema}.laeufe (
    run_id                BIGSERIAL PRIMARY KEY,
    erstellt_am           TIMESTAMPTZ NOT NULL DEFAULT now(),
    only_active_members   BOOLEAN,
    bundesland            TEXT,
    anzahl_mitglieder     INTEGER,
    anzahl_gruppenstunden INTEGER,
    anzahl_lager          INTEGER
);

-- Kennzahl 1: Top/Flop-Anwesenheit (absolute Teilnahmen je Mitglied).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_top_flop_anwesenheit (
    run_id            BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    mitglied_id       TEXT,
    name              TEXT,
    anwesend_absolut  INTEGER,
    rang              INTEGER
);
CREATE INDEX IF NOT EXISTS idx_top_flop_run ON {schema}.kennzahl_top_flop_anwesenheit (run_id);

-- Kennzahl 2: Faire relative Beteiligung. quote_prozent darf NULL sein
-- (Mitglied ohne moegliche Stunden ist nicht bewertbar).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_faire_beteiligung (
    run_id            BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    mitglied_id       TEXT,
    name              TEXT,
    moegliche_stunden INTEGER,
    anwesend          INTEGER,
    quote_prozent     NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_faire_beteiligung_run ON {schema}.kennzahl_faire_beteiligung (run_id);

-- Kennzahl 3: Dropout-Risiko. Mehrere Felder duerfen NULL sein, wenn ein
-- Mitglied nicht bewertbar ist (bewertbar=false).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_risiko (
    run_id                            BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    mitglied_id                       TEXT,
    name                              TEXT,
    bewertbar                         BOOLEAN,
    quote_letzte_n                    NUMERIC,
    quote_davor                       NUMERIC,
    stunden_seit_letzter_anwesenheit  INTEGER,
    risiko_score                      NUMERIC,
    risiko_stufe                      TEXT
);
CREATE INDEX IF NOT EXISTS idx_risiko_run ON {schema}.kennzahl_risiko (run_id);

-- Kennzahl 4a: Saisonalitaet pro Monat (1-12).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_saisonalitaet_monat (
    run_id          BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    monat           INTEGER,
    anzahl_stunden  INTEGER,
    summe_anwesend  INTEGER,
    schnitt_anwesend NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_saison_monat_run ON {schema}.kennzahl_saisonalitaet_monat (run_id);

-- Kennzahl 4b: Saisonalitaet pro Wochentag (0-6, Montag=0).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_saisonalitaet_wochentag (
    run_id          BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    wochentag       INTEGER,
    anzahl_stunden  INTEGER,
    summe_anwesend  INTEGER,
    schnitt_anwesend NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_saison_wtag_run ON {schema}.kennzahl_saisonalitaet_wochentag (run_id);

-- Kennzahl 5: Thema-Ranking (Durchschnittliche Anwesenheit je Thema).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_thema_ranking (
    run_id          BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    thema_key       TEXT,
    thema_quelle    TEXT,
    anzahl_stunden  INTEGER,
    schnitt_anwesend NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_thema_ranking_run ON {schema}.kennzahl_thema_ranking (run_id);

-- Kennzahl 6: Lager-Korrelation. Je Lauf zwei Gruppen-Zeilen
-- ('lagerteilnehmer' und 'nicht_teilnehmer'). schnitt_quote und differenz
-- duerfen NULL sein, wenn keine bewertbaren Quoten vorliegen.
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_lager_korrelation (
    run_id        BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    gruppe        TEXT,
    anzahl        INTEGER,
    schnitt_quote NUMERIC,
    differenz     NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_lager_korrelation_run ON {schema}.kennzahl_lager_korrelation (run_id);

-- Kennzahl 7: Puenktlichkeit (Verspaetungen je Mitglied). verfuegbar gibt an,
-- ob brauchbare zu_spaet-Daten vorlagen. Ist verfuegbar=false, gibt es keine
-- Mitglied-Zeilen.
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_puenktlichkeit (
    run_id        BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    verfuegbar    BOOLEAN,
    mitglied_id   TEXT,
    name          TEXT,
    verspaetungen INTEGER
);
CREATE INDEX IF NOT EXISTS idx_puenktlichkeit_run ON {schema}.kennzahl_puenktlichkeit (run_id);

-- Kennzahl 8: Gesamtkennzahlen (eine Zeile je Lauf).
CREATE TABLE IF NOT EXISTS {schema}.kennzahl_gesamt (
    run_id                        BIGINT NOT NULL REFERENCES {schema}.laeufe (run_id) ON DELETE CASCADE,
    anzahl_aktive_mitglieder      INTEGER,
    anzahl_mitglieder_gesamt      INTEGER,
    anzahl_gruppenstunden         INTEGER,
    anzahl_lager                  INTEGER,
    schnitt_anwesend_pro_stunde   NUMERIC,
    gesamtbeteiligungsquote       NUMERIC,
    gesamtbeteiligungsquote_roh   NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gesamt_run ON {schema}.kennzahl_gesamt (run_id);
