# Deployment auf TrueNAS SCALE

Diese Anleitung beschreibt Schritt fuer Schritt, wie du die Vereinsstatistik
(Notion-ETL + PostgreSQL + Grafana) auf TrueNAS SCALE in Betrieb nimmst. Der
komplette Stack ist in der `docker-compose.yml` im Projekt-Root definiert und
besteht aus vier Diensten: `postgres` (Datenbank), `app` (Web-UI), `etl-cron`
(periodischer Sync) und `grafana` (Dashboards).

## Zwei Annahmen dieser Anleitung

1. **Annahme Zielplattform:** Es wird TrueNAS SCALE mit Docker/Apps
   vorausgesetzt (die Linux-Variante), nicht TrueNAS CORE auf FreeBSD. Nur
   SCALE kann Docker-Container bzw. Compose-Stacks ausfuehren. Auf CORE laeuft
   dieser Stack nicht.
2. **Annahme Datenbank:** Es wird eine dedizierte eigene PostgreSQL-Instanz nur
   fuer dieses Tool verwendet (der Dienst `postgres` aus der
   `docker-compose.yml`). Eine bereits vorhandene PostgreSQL waere grundsaetzlich
   ebenfalls nutzbar: dazu in der `config.yaml` unter `postgres` den
   passenden `host`, `port`, `database`, `user` (plus Schema) eintragen und das
   Passwort ueber `PG_PASSWORD` in der `.env` setzen. In diesem Fall den
   `postgres`-Dienst in der `docker-compose.yml` weglassen und `postgres.host`
   auf den Hostnamen bzw. die IP der bestehenden Datenbank zeigen lassen.

## 1. Voraussetzungen

- TrueNAS SCALE mit aktivierter Docker-/Apps-Funktion.
- Zugriff auf die TrueNAS-Weboberflaeche und auf eine Shell (SSH oder die
  eingebaute Shell) fuer die Compose- und CLI-Kommandos.
- Ein Notion-Integration-Token (beginnt mit `ntn_` oder `secret_`), siehe
  <https://www.notion.so/my-integrations>. Die Integration muss Zugriff auf die
  drei Notion-Datenbanken (Mitglieder, Gruppenstunden, Lager) haben.
- Die IDs bzw. Data-Source-IDs der drei Notion-Datenbanken.

## 2. Datasets / Volumes anlegen

Lege auf einem Pool je ein Dataset an, damit die Daten Neustarts und Updates
ueberstehen. Empfohlen (Namen sind Beispiele):

- `.../vereinsstatistik/postgres` - Postgres-Datenverzeichnis.
- `.../vereinsstatistik/grafana` - Grafana-Datenverzeichnis.
- `.../vereinsstatistik/config` - Ablage fuer `config.yaml` und `.env`.

Die `docker-compose.yml` nutzt standardmaessig die benannten Docker-Volumes
`postgres-data` und `grafana-data`. Wenn du stattdessen die oben angelegten
Datasets direkt einhaengen willst, ersetze in der `docker-compose.yml` die
benannten Volumes durch Bind-Mounts auf deine Dataset-Pfade, zum Beispiel:

```yaml
    volumes:
      - /mnt/pool/vereinsstatistik/postgres:/var/lib/postgresql/data
```

Das `config`-Dataset ist der Arbeitsordner, in dem `docker-compose.yml`,
`config.yaml` und `.env` liegen und aus dem du die Kommandos ausfuehrst.

## 3. .env und config.yaml bereitstellen

Wechsle in den Arbeitsordner (das `config`-Dataset) und lege die beiden
Dateien an.

`.env` (Vorlage: `.env.example`):

```ini
NOTION_TOKEN=ntn_dein_token
PG_PASSWORD=ein_starkes_passwort
SYNC_INTERVALL_SEKUNDEN=86400
```

`config.yaml` aus der Vorlage erzeugen und ausfuellen:

```bash
cp config.example.yaml config.yaml
```

Danach in `config.yaml` anpassen:

- Unter `databases` die `database_id` (oder `data_source_id`) der drei Notion-
  Datenbanken eintragen und die Feldzuordnungen pruefen.
- Unter `postgres`:
  - `enabled: true` setzen.
  - `host: "postgres"` setzen (der Compose-Service-Name, NICHT `localhost`),
    damit `app` und `etl-cron` die Datenbank im Compose-Netzwerk erreichen.
  - `database: "vereinsstatistik"` und `user: "verein"` passend zu den Werten
    im `postgres`-Dienst der `docker-compose.yml` lassen.
  - `schema` bei Bedarf anpassen (Standard `public`). Wenn du ein anderes Schema
    waehlst, musst du die SQL-Abfragen im Grafana-Dashboard entsprechend
    anpassen (siehe Abschnitt 7).

Das Postgres-Passwort steht nur in der `.env` (`PG_PASSWORD`), nie in der
`config.yaml`.

## 4. Stack starten

Auf TrueNAS SCALE kannst du den Stack als Custom App (YAML einfuegen) anlegen
oder direkt per Compose in der Shell starten:

```bash
docker compose up -d
```

Der `postgres`-Dienst hat einen Healthcheck; `app`, `etl-cron` und `grafana`
starten erst, sobald die Datenbank Verbindungen annimmt.

## 5. Schema initialisieren

Lege die Tabellen einmalig an (idempotent, kann gefahrlos wiederholt werden):

```bash
docker compose run --rm app python -m vereinsstatistik.cli init-db
```

Alternativ kannst du den Sync direkt mit Schema-Initialisierung starten:

```bash
docker compose run --rm app python -m vereinsstatistik.cli sync --init-db
```

Hinweis: Der `etl-cron`-Dienst ruft `init-db` beim Start ohnehin automatisch
auf. Dieser Schritt ist nuetzlich, wenn du den Sync manuell kontrollieren
moechtest.

## 6. Ersten Sync ausfuehren

Daten aus Notion abrufen, auswerten und als neuen Lauf nach PostgreSQL
schreiben:

```bash
docker compose run --rm app python -m vereinsstatistik.cli sync
```

Jeder Sync legt einen neuen `run_id` in `public.laeufe` an und schreibt die
Kennzahlen dieses Laufs. Historische Laeufe bleiben erhalten, sodass Grafana
Zeitreihen ueber mehrere Laeufe zeigen kann.

## 7. Grafana oeffnen und Dashboards pruefen

Rufe Grafana im Browser auf: `http://<truenas-ip>:3000` (Standard-Login
`admin` / `admin`, beim ersten Login aenderst du das Passwort).

Datenquelle und Dashboard werden automatisch per Provisioning geladen (die
`docker-compose.yml` mountet `./grafana/provisioning` read-only nach
`/etc/grafana/provisioning`):

- Datenquelle `Vereinsstatistik PostgreSQL` zeigt auf den `postgres`-Dienst.
  Das Passwort kommt ueber `${PG_PASSWORD}` aus der `.env`.
- Dashboard `Vereinsstatistik` (Ordner `Vereinsstatistik`) mit Panels fuer
  Top/Flop-Anwesenheit, faire Beteiligung, Risiko-Liste, Saisonalitaet pro
  Monat und Wochentag, Thema-Ranking, Gesamtkennzahlen und der
  Gesamtbeteiligungsquote im Zeitverlauf.

Alle Panels filtern auf den juengsten Lauf via
`run_id = (SELECT max(run_id) FROM public.laeufe)`. Verwendest du in der
`config.yaml` ein anderes Schema als `public`, ersetze in den Panel-Abfragen
(Dashboard bearbeiten) `public.` durch deinen Schemanamen, oder passe die Datei
`grafana/provisioning/dashboards/vereinsstatistik.json` vor dem Start an.

## 8. Periodischen Sync einrichten

Gewaehlte Loesung: der Dienst `etl-cron` in der `docker-compose.yml`. Er legt
beim Start einmalig das Schema an (`init-db`) und ruft danach in einer
Endlosschleife `sync` auf, jeweils gefolgt von einer Pause von
`SYNC_INTERVALL_SEKUNDEN` Sekunden (Standard `86400`, also einmal taeglich).
Das Intervall stellst du in der `.env` ein. Damit braucht TrueNAS keinen
externen Cron-Job.

Wer stattdessen den TrueNAS-eigenen Cron nutzen moechte, laesst den
`etl-cron`-Dienst in der `docker-compose.yml` weg und legt unter
**System Settings -> Advanced -> Cron Jobs** einen naechtlichen Job an, der den
Sync einmalig startet:

```bash
docker compose -f /mnt/pool/vereinsstatistik/config/docker-compose.yml run --rm app python -m vereinsstatistik.cli sync
```

Beide Wege erzeugen pro Lauf einen neuen `run_id`; Grafana zeigt dann stets den
aktuellsten Lauf und zusaetzlich die Entwicklung ueber die Zeit.
