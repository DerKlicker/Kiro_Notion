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
- [ ] **Phase 2** — Kennzahlen-Logik (Anwesenheit, relative Beteiligung, Risiko, Saisonalität …)
- [ ] **Phase 3** — PostgreSQL-Schema + ETL-Sync + Grafana-Dashboards (TrueNAS)

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
