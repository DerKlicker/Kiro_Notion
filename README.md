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
- [x] **Phase 4** — TrueNAS-App ohne Shell: GHCR-Image, Registry-Compose,
  Selbstinitialisierung der `config.yaml` und „Jetzt synchronisieren"-Button in
  der Web-UI

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
4. **Saisonalität** — durchschnittliche Anwesenheit je Monat. Eine Auswertung
   je Wochentag gibt es bewusst nicht: Gruppenstunden finden immer samstags
   statt, nur das Sommerlager fällt auf andere Tage.
5. **Thema-Ranking** — durchschnittliche Anwesenheit pro Thema. Angezeigt wird
   der lesbare Themenname aus dem Notion-Rollup `thema_name` ("Grafana_Name").
   Fehlt dieser, greift als Fallback die Themen-Relation (Page-ID), sonst der
   Titel der Gruppenstunde.
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
- **Faire Beteiligung / mögliche Stunden:** Pro Mitglied zählen nur die
  Gruppenstunden, deren Datum im aktiven Zeitraum liegt (ab `eintrittsdatum`,
  bis `austrittsdatum` bzw. bis zur letzten vorhandenen Stunde). Die möglichen
  Stunden variieren also mit dem Eintrittsdatum und sind nicht für alle gleich.
  Hat ein Mitglied keine möglichen Stunden, ist die Quote `None` (nicht
  bewertbar) statt fälschlich 0 %. Der Risiko-Score betrachtet nur die letzten
  `RISIKO_FENSTER_N` dieser aktiven Stunden gegen die davorliegenden.
- **Mitglieder-Filter für die Statistik:** Die **mitgliederbezogenen**
  Auswertungen (Top/Flop-Anwesenheit, faire Beteiligung, Risiko-Score,
  Lager-Korrelation, Pünktlichkeit) rechnen auf einer gefilterten
  Mitgliederliste (`mitglieder_fuer_statistik`):
  - **Ausgeschiedene werden immer ausgeschlossen** (Feld `ausgeschieden` oder
    ein vergangenes `austrittsdatum`).
  - Zusätzlich zählen nur Mitglieder mit **Bereich/Stamm = "Gruppenstunde"**
    (Notion-Select, intern `bereich_stamm`). Andere oder leere Werte werden
    ausgeschlossen. Defensiver Fallback: Ist die Spalte bei keinem (noch nicht
    ausgeschiedenen) Mitglied gepflegt, wird der Bereich/Stamm-Filter
    übersprungen, damit nicht versehentlich die ganze Liste herausfällt.

  Die **stundenbasierten** Auswertungen (Saisonalität, Thema-Ranking) bleiben
  unberührt, und die Gesamtkennzahlen weisen aktive und gesamte Mitgliederzahl
  ohnehin getrennt aus.

### Jahres-Dimension (pro Jahr auswerten)

Mehrere Kennzahlen lassen sich zusätzlich **pro Kalenderjahr** auswerten, damit
sichtbar wird, wie sich die Beteiligung von Jahr zu Jahr verändert und jedes
Jahr jemand anderes vorne liegen kann. Betroffen sind: **Top/Flop-Anwesenheit,
faire relative Beteiligung, Gesamtkennzahlen, Thema-Ranking** und die
**Saisonalität pro Monat**. **Risiko/Dropout, Lager-Korrelation und
Pünktlichkeit** bleiben bewusst "alle Zeit" (keine Jahres-Dimension).

- **Jahr = Kalenderjahr ab 01.01.**, abgeleitet aus dem Feld `datum` der
  Gruppenstunde (nicht aus dem Notion-Rollup `jahr`).
- **Faire Jahresquote:** Die möglichen Stunden eines Mitglieds im Jahr sind die
  Stunden dieses Jahres mit Datum **ab dem Eintrittsdatum** (und bis Austritt
  bzw. letzter Stunde). Ein Mitglied, das mitten im Jahr eintritt, wird also
  nur anteilig ab seinem Eintritt bewertet.
- **Sentinel-Konvention "alle Jahre":** Der Report liefert pro Kennzahl je
  vorkommendem Jahr einen Satz Zeilen **mit** einem Feld `jahr` **plus** einen
  Aggregat-Satz "alle Jahre". Das Aggregat trägt `jahr = None` (Python) bzw.
  **SQL `NULL`** in der Spalte `jahr` (die Konstante heißt `JAHR_ALLE` in
  `analysis.py`). Das "alle Jahre"-Aggregat entspricht exakt der bisherigen
  Gesamtauswertung, sodass nichts verloren geht.

Im Grafana-Dashboard gibt es dafür die Variable **`$jahr`** (oben im Dashboard).
Sie listet die vorkommenden Jahre plus **"Alle Jahre" (Wert `0`)**. Die
jahresgefilterten Panels filtern mit `COALESCE(jahr, 0) = $jahr`, sodass der
Wert `0` das Aggregat mit `jahr IS NULL` trifft. Das Saisonalitäts-Panel
kombiniert beides in **einer** Grafik: Balken = Schnitt je Monat im gewählten
Jahr, Linie = Gesamtschnitt je Monat über alle Jahre als Vergleich. Bei Auswahl
"Alle Jahre" liefert die Balken-Query ebenfalls das Gesamtaggregat, Balken und
Linie sind dann bewusst identisch.

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
Monat (gewaehltes Jahr vs. Gesamtschnitt), Thema-Ranking, Lager-Korrelation,
Puenktlichkeit und Gesamtkennzahlen (jeweils gefiltert auf den juengsten Lauf)
sowie die Gesamtbeteiligungsquote im Zeitverlauf. Oben im Dashboard waehlt die
Variable `$jahr` das Kalenderjahr (oder "Alle Jahre"); siehe Abschnitt
"Jahres-Dimension" weiter oben.

**Wichtig nach dem Deploy dieser Version (neue Spalte `jahr`):** Die
jahresbezogenen Kennzahl-Tabellen haben eine neue Spalte `jahr` bekommen. Fuehre
nach dem Update einmal `init-db` und danach `sync` aus (bzw.
`sync --init-db`). Das Schema ist idempotent und zieht die Spalte in
bestehenden Datenbanken defensiv per `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
nach; ein frischer Lauf fuellt anschliessend die Jahres-Zeilen. Notion bleibt
die Datenquelle, es gehen also keine Daten verloren.

Die vollstaendige Schritt-fuer-Schritt-Anleitung steht in
[docs/TRUENAS.md](docs/TRUENAS.md).

**Zwei Annahmen** (dort im Detail begruendet):

1. Zielplattform ist TrueNAS SCALE mit Docker/Apps, nicht CORE/FreeBSD.
2. Es wird eine dedizierte eigene PostgreSQL-Instanz nur fuer dieses Tool
   genutzt. Eine bestehende PostgreSQL waere via `host`/`port`/`database`/`user`
   in der `config.yaml` (plus `PG_PASSWORD` in der `.env`) ebenfalls nutzbar;
   dann den `postgres`-Dienst in der `docker-compose.yml` weglassen und den
   `host` entsprechend setzen.

## Phase 4 — Als TrueNAS-App (ohne Shell)

Phase 4 macht den Stack App-Store-tauglich für TrueNAS SCALE, **ohne dass du je
eine Shell öffnen musst**:

- **Fertiges Image aus GHCR:** `app` und `etl-cron` ziehen das Image
  `ghcr.io/derklicker/kiro_notion:latest` statt es lokal zu bauen. Das Image
  enthält nur Programmcode und `config.example.yaml` — **keine** Secrets, keine
  `config.yaml`, keine `.env`, keine Mitgliederdaten (siehe `.dockerignore`),
  darf also öffentlich liegen. Gebaut und veröffentlicht wird es per
  GitHub-Actions-Workflow (`.github/workflows/docker-publish.yml`).
- **Registry-Compose:** [`docker-compose.truenas.yml`](docker-compose.truenas.yml)
  ist die App-Variante zum Einfügen in eine TrueNAS **Custom App**. Statt einer
  vorab angelegten `config.yaml` wird ein persistentes **Konfig-Verzeichnis**
  eingehängt (`VEREINSSTATISTIK_CONFIG_DIR` → `/app/config_dir`); die Web-UI legt
  die `config.yaml` beim ersten Start selbst aus der Vorlage an. Das
  Grafana-Provisioning liegt im Image und wird per Init-Container bereitgestellt,
  sodass kein geklontes Repo nötig ist.
- **„Jetzt synchronisieren"-Button:** In der Web-UI (Port 8000) löst ein Klick
  einen kompletten Sync aus (Notion abrufen → Kennzahlen berechnen → Schema
  idempotent anlegen → nach PostgreSQL schreiben). So funktionieren der
  allererste Lauf und Ad-hoc-Auswertungen ganz ohne Konsole.

Die komplette Schritt-für-Schritt-Anleitung für den rein grafischen Weg steht in
[docs/TRUENAS-APP.md](docs/TRUENAS-APP.md). Den klassischen Shell-/Build-Weg
beschreibt weiterhin [docs/TRUENAS.md](docs/TRUENAS.md).

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
