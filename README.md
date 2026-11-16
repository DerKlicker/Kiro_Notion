# Vereinsstatistik (Notion → Grafana)

Ein Tool, das Mitglieder-, Gruppenstunden- und Lager-Daten aus **Notion** ausliest,
daraus Anwesenheits- und Beteiligungskennzahlen berechnet und sie in **PostgreSQL**
schreibt, damit **Grafana** (z. B. auf TrueNAS) sie visualisieren kann.

Es gibt eine **Weboberfläche**, über die du den Notion-Token eintragen, die
Datenbank-/Feld-Zuordnung konfigurieren und die Verbindung testen kannst — oder
du pflegst alles direkt über die `config.yaml` (praktisch auf TrueNAS).

```
┌─────────────┐      ┌──────────────────┐      ┌────────────┐      ┌──────────┐
│  Notion API │ ───► │  Python ETL      │ ───► │ PostgreSQL │ ◄─── │ Grafana  │
│  (3 DBs)    │      │  + Web-UI        │      │ (TrueNAS)  │      │(TrueNAS) │
└─────────────┘      └──────────────────┘      └────────────┘      └──────────┘
```

## Projektstatus

- [x] **Phase 1** — Notion-Anbindung, konfigurierbares Mapping, Web-UI, Struktur-Inspektor
- [x] **Phase 2** — Kennzahlen-Logik (Anwesenheit, relative Beteiligung, Risiko, Saisonalität …)
- [x] **Phase 3** — PostgreSQL-Schema + ETL-Sync + Grafana-Dashboards (TrueNAS)

## Schnellstart (lokal)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Web-UI starten (Token & Mapping im Browser pflegen):
python -m vereinsstatistik.web
# -> http://localhost:8000
```

Alternativ ohne Web-UI, direkt per CLI:

```bash
# Notion-Struktur inspizieren (zeigt alle DBs, Data Sources, Properties):
python -m vereinsstatistik.cli inspect

# Daten aus Notion abrufen und als JSON ausgeben:
python -m vereinsstatistik.cli fetch --out data.json
```

## Phase 2 — Auswertung

Das Modul `vereinsstatistik/analysis.py` berechnet aus den abgerufenen Daten
(entweder live aus Notion oder aus einer per `fetch --out` gespeicherten JSON)
acht Kennzahlen. Alle arbeiten rein mit der Standardbibliothek und ohne
Netz-/Notion-Zugriff, sodass die Auswertung auch offline aus gespeicherten
Daten läuft.

Was berechnet wird:

1. **Top/Flop-Anwesenheit** — absolute Gruppenstunden-Teilnahmen pro Mitglied
   mit dichtem Rang, optional nach Jahr gefiltert.
2. **Faire relative Beteiligung** — Beteiligungsquote pro Mitglied, die nur die
   Stunden im aktiven Zeitraum (Eintritt bis Austritt) zählt, damit Neuzugänge
   nicht benachteiligt werden.
3. **Risiko-/Dropout-Score** — schätzt pro Mitglied das Abbruchrisiko aus dem
   Abfall der Anwesenheit und der Dauer seit der letzten Anwesenheit.
4. **Saisonalität** — durchschnittliche Anwesenheit je Monat und je Wochentag.
5. **Thema-Ranking** — durchschnittliche Anwesenheit pro Thema (Themen-Relation
   bevorzugt, sonst Titel als Fallback).
6. **Lager-Korrelation** — Vergleich der fairen Beteiligungsquote von
   Lagerteilnehmern gegenüber Nicht-Teilnehmern.
7. **Pünktlichkeit** — Verspätungen pro Mitglied, sofern das Feld `zu_spaet`
   auswertbar strukturiert ist (sonst sauber übersprungen).
8. **Gesamtkennzahlen** — Mitglieder gesamt/aktiv, Anzahl Gruppenstunden/Lager,
   Schnitt anwesend pro Stunde und Gesamtbeteiligungsquote. Die
   Gesamtbeteiligungsquote ist der Durchschnitt der fairen Einzelquoten
   (Kennzahl 2) und folgt damit demselben Fairness-Prinzip; die ungewichtete
   Rohquote (alle Mitglieder mal alle Stunden) wird zusaetzlich als
   `gesamtbeteiligungsquote_roh` ausgewiesen.

`analyze` aufrufen (gibt eine deutsche Zusammenfassung auf der Konsole aus und
schreibt mit `--out` den vollständigen Report als JSON):

```bash
# Variante A: live aus Notion abrufen und auswerten:
python -m vereinsstatistik.cli analyze --out report.json

# Variante B: aus einer zuvor gespeicherten JSON auswerten (ohne Notion-Abruf):
python -m vereinsstatistik.cli fetch --out data.json
python -m vereinsstatistik.cli analyze --in data.json --out report.json
```

### Dokumentierte fachliche Annahmen

Diese Annahmen sind als benannte Konstanten in `vereinsstatistik/analysis.py`
hinterlegt und können dort leicht an den Verein angepasst werden:

- **Risiko-Score-Konstanten:** Das Risiko-Fenster umfasst die letzten
  `RISIKO_FENSTER_N = 5` stattgefundenen Gruppenstunden. Der Score (0.0 bis 1.0)
  setzt sich je zur Hälfte aus dem Abfall der Anwesenheitsquote
  (`RISIKO_GEWICHT_ABFALL = 0.5`) und der Dauer seit der letzten Anwesenheit
  (`RISIKO_GEWICHT_ABWESENHEIT = 0.5`) zusammen; die Abwesenheits-Komponente
  erreicht nach `RISIKO_ABWESENHEIT_MAX = 5` verpassten Stunden ihren Maximalwert.
  Die Einstufung erfolgt über `RISIKO_SCHWELLE_NIEDRIG = 0.34` und
  `RISIKO_SCHWELLE_HOCH = 0.67` in niedrig/mittel/hoch. Hat ein Mitglied keine
  Stunden im aktiven Zeitraum, ist es nicht bewertbar: der Score ist dann
  `None`, die Stufe lautet `"unbekannt"` und `bewertbar` ist `False`. So wird
  dieser Fall klar vom echten Nullrisiko (Score 0.0, Stufe "niedrig") eines
  treuen Mitglieds unterschieden.
- **Faire Beteiligung / letzte N Stunden:** Pro Mitglied zählen nur die
  Gruppenstunden, deren Datum im aktiven Zeitraum liegt (ab `eintrittsdatum`,
  bis `austrittsdatum` bzw. bis zur letzten vorhandenen Stunde). Hat ein
  Mitglied keine möglichen Stunden, ist die Quote `None` (nicht bewertbar) statt
  fälschlich 0 %. Der Risiko-Score betrachtet nur die letzten
  `RISIKO_FENSTER_N` dieser aktiven Stunden gegen die davorliegenden.
- **`only_active_members`-Verhalten:** Ist `analysis.only_active_members` in der
  `config.yaml` auf `true` gesetzt, werden ausgeschiedene Mitglieder (Feld
  `ausgeschieden` oder ein vergangenes `austrittsdatum`) aus den
  **mitgliederbezogenen** Auswertungen ausgenommen (Top/Flop-Anwesenheit, faire
  Beteiligung, Risiko-Score, Lager-Korrelation, Pünktlichkeit). Die
  **stundenbasierten** Auswertungen (Saisonalität, Thema-Ranking) bleiben
  unberührt, und die Gesamtkennzahlen weisen aktive und gesamte Mitgliederzahl
  ohnehin getrennt aus.

## Phase 3 - PostgreSQL, Container und Grafana (TrueNAS)

Phase 3 macht das Tool auf TrueNAS SCALE deploybar: die in Phase 2 berechneten
Kennzahlen werden je Lauf nach PostgreSQL geschrieben und mit Grafana
visualisiert.

**Neue CLI-Commands:**

```bash
# Datenbankschema anlegen (idempotent, kann wiederholt werden):
python -m vereinsstatistik.cli init-db

# Auswerten und das Ergebnis als neuen Lauf nach PostgreSQL schreiben:
python -m vereinsstatistik.cli sync

# Varianten von sync:
python -m vereinsstatistik.cli sync --init-db     # Schema vorher anlegen
python -m vereinsstatistik.cli sync --in data.json  # aus gespeicherter JSON statt live aus Notion
```

**Schema:** Das versionierte SQL-Schema (`vereinsstatistik/db/schema.sql`) legt
eine Lauf-/Snapshot-Tabelle `laeufe` (ein Eintrag je `run_id` mit Zeitstempel)
sowie je eine Tabelle pro Kennzahl an. Jeder Sync erzeugt einen neuen `run_id`;
historische Laeufe bleiben fuer Zeitreihen erhalten. Der Schemaname ist
konfigurierbar (`postgres.schema` in der `config.yaml`, Standard `public`).

**Container:** Der Stack ist in der `docker-compose.yml` beschrieben und umfasst
die Dienste `postgres` (Datenbank), `app` (Web-UI, Port 8000), `etl-cron`
(periodischer Sync im einstellbaren Intervall) und `grafana` (Port 3000).
Persistente Volumes und Secrets (`NOTION_TOKEN`, `PG_PASSWORD`) kommen aus der
`.env` (Vorlage: `.env.example`).

**Grafana:** Datenquelle und Dashboards werden per Provisioning aus
`grafana/provisioning/` automatisch geladen. Das Dashboard `Vereinsstatistik`
zeigt Top/Flop-Anwesenheit, faire Beteiligung, Risiko-Liste, Saisonalitaet pro
Monat und Wochentag, Thema-Ranking und Gesamtkennzahlen (jeweils gefiltert auf
den juengsten Lauf) sowie die Gesamtbeteiligungsquote im Zeitverlauf.

Die vollstaendige Schritt-fuer-Schritt-Anleitung steht in
[docs/TRUENAS.md](docs/TRUENAS.md).

**Zwei Annahmen** (dort im Detail begruendet):

1. Zielplattform ist TrueNAS SCALE mit Docker/Apps, nicht CORE/FreeBSD.
2. Es wird eine dedizierte eigene PostgreSQL-Instanz nur fuer dieses Tool
   genutzt. Eine bestehende PostgreSQL waere via `host`/`port`/`database`/`user`
   in der `config.yaml` (plus `PG_PASSWORD` in der `.env`) ebenfalls nutzbar;
   dann den `postgres`-Dienst in der `docker-compose.yml` weglassen und den
   `host` entsprechend setzen.

## Konfiguration

Zwei Wege, dieselbe Datei (`config.yaml`):

1. **Web-UI** — unter `http://localhost:8000` Token eintragen, Datenbanken
   auswählen, Felder zuordnen, „Verbindung testen", speichern.
2. **YAML direkt** — `config.example.yaml` nach `config.yaml` kopieren und
   ausfüllen. Ideal für TrueNAS / Docker (per Volume einhängen).

Der **Token** wird nicht in der `config.yaml` gespeichert, sondern in einer
`.env`-Datei (bzw. als Umgebungsvariable `NOTION_TOKEN`) — die `.env` steht in
`.gitignore` und landet nicht im Repo.

Siehe `config.example.yaml` für alle Felder inkl. Erklärungen.
