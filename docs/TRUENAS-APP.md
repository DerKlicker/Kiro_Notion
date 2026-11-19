# TrueNAS SCALE als App betreiben (ohne Shell)

Diese Anleitung beschreibt den **rein grafischen** Weg: die Vereinsstatistik
läuft als **Custom App** in TrueNAS SCALE, und du brauchst **nie eine Konsole
oder Shell**. Das fertige App-Image wird aus der GitHub Container Registry
(GHCR) gezogen; der erste Lauf und Ad-hoc-Auswertungen werden per
**„Jetzt synchronisieren"-Button** in der Web-UI ausgelöst.

> Wenn du lieber den klassischen Weg über Shell/`docker compose` und ein selbst
> gebautes Image gehst, folge stattdessen [docs/TRUENAS.md](TRUENAS.md).

## Zwei Annahmen dieser Anleitung

Wie in Phase 3 (siehe [docs/TRUENAS.md](TRUENAS.md)):

1. **Zielplattform:** TrueNAS **SCALE** mit Docker/Apps (Linux), nicht
   TrueNAS CORE auf FreeBSD.
2. **Datenbank:** Es wird eine **dedizierte eigene PostgreSQL-Instanz** nur für
   dieses Tool verwendet (der Dienst `postgres` im Compose). Eine bestehende
   PostgreSQL ließe sich ebenfalls nutzen (dann den `postgres`-Dienst entfernen
   und in der Web-UI unter PostgreSQL `host`/`port`/`database`/`user` setzen).

## Was im Image steckt — und was nicht

Das Image `ghcr.io/derklicker/kiro_notion:latest` enthält **nur Programmcode**
und die Referenz-Vorlage `config.example.yaml`. Es enthält **keine** Secrets,
**keine** `config.yaml`, **keine** `.env` und **keine** Mitgliederdaten (siehe
`.dockerignore`). Deshalb darf es öffentlich auf GHCR liegen. Deine Zugangsdaten
(Notion-Token, DB-Passwort) trägst du erst in TrueNAS als Umgebungsvariablen
ein; deine Mapping-Konfiguration pflegst du über die Web-UI — beides landet in
einem **persistenten Host-Verzeichnis** auf deinem NAS, nicht im Image.

## 1. Voraussetzungen

- TrueNAS SCALE mit aktivierter Apps-/Docker-Funktion.
- Ein Notion-Integration-Token (beginnt mit `ntn_` oder `secret_`),
  <https://www.notion.so/my-integrations>. Die Integration muss mit den drei
  Notion-Datenbanken (Mitglieder, Gruppenstunden, Lager) geteilt sein.
- Die Datenbank-IDs der drei Notion-Datenbanken (hast du griffbereit, oder du
  wählst sie später in der Web-UI nach „Verbindung testen").
- Ein starkes PostgreSQL-Passwort, das du gleich vergibst.

## 2. Host-Verzeichnisse anlegen

Lege auf einem Pool drei Verzeichnisse (Datasets) an, damit Daten und
Konfiguration Neustarts und App-Updates überstehen. Namen sind Beispiele:

- `.../vereinsstatistik/postgres` — PostgreSQL-Datenverzeichnis.
- `.../vereinsstatistik/grafana` — Grafana-Datenverzeichnis.
- `.../vereinsstatistik/config` — **Konfig-Verzeichnis**. Hierhin legt die
  Web-UI beim ersten Start automatisch die `config.yaml` an; außerdem landet
  hier beim Token-Speichern eine `.env`.

## 3. Custom App in TrueNAS anlegen

1. In TrueNAS: **Apps → Discover Apps → Custom App** (bzw.
   „Install via YAML"/„Custom App").
2. Den **kompletten Inhalt** von
   [`docker-compose.truenas.yml`](../docker-compose.truenas.yml) in das
   Compose-/YAML-Feld einfügen.
3. Die drei Host-Verzeichnisse aus Schritt 2 den Volumes zuordnen. In der
   Compose-Datei sind sie als benannte Volumes vordefiniert; verbinde sie im
   TrueNAS-Formular mit deinen Host-Pfaden:
   - `postgres-data`  → `.../vereinsstatistik/postgres`
   - `grafana-data`   → `.../vereinsstatistik/grafana`
   - `config-dir`     → `.../vereinsstatistik/config`
     (wird im Container als `/app/config_dir` eingehängt — dort erwartet die App
     die `config.yaml` über die Variable `VEREINSSTATISTIK_CONFIG_DIR`).

   > Das Volume `grafana-provisioning` braucht **keinen** Host-Pfad. Ein kleiner
   > Init-Container kopiert die Grafana-Datenquelle und das Dashboard aus dem
   > App-Image in dieses Volume — so ist das Dashboard ohne Shell und ohne
   > geklontes Repo sofort verfügbar.

4. **Secrets eintragen.** Wichtig: Die TrueNAS-Custom-App füllt die
   `${...}`-Platzhalter in `docker-compose.truenas.yml` **nicht** aus dem
   „Environment"-Formular. Bleiben `NOTION_TOKEN`/`PG_PASSWORD` dadurch leer,
   startet PostgreSQL mit leerem Passwort und der Stack bricht ab
   (`container ... postgres ... is unhealthy`).

   **Deshalb für die Custom App die Datei
   [`docker-compose.truenas-inline.yml`](../docker-compose.truenas-inline.yml)
   verwenden** statt `docker-compose.truenas.yml`. Dort trägst du die Werte
   direkt ins YAML ein (zwei Platzhalter, per „Alle ersetzen"):
   - `HIER_DEIN_DB_PASSWORT` → ein starkes, selbst gewähltes PostgreSQL-Passwort
     (an allen Stellen identisch).
   - `HIER_DEIN_NOTION_TOKEN` → dein Notion-Integration-Token.
   - Das Sync-Intervall steht direkt im YAML (`SYNC_INTERVALL_SEKUNDEN`,
     Standard `86400` = täglich; `3600` = stündlich).

   Die Datei `docker-compose.truenas.yml` mit `${...}` bleibt für Umgebungen,
   die eine echte `.env` bereitstellen (z. B. der Shell-Weg in
   [docs/TRUENAS.md](TRUENAS.md)).

5. **Ports** (in der Compose-Datei vorgegeben, bei Bedarf im Formular anpassen):
   - `8000` → Web-UI (Konfiguration + „Jetzt synchronisieren").
   - `3000` → Grafana (Dashboards).

6. App **installieren**. TrueNAS zieht das Image aus GHCR und startet die
   Dienste `postgres`, `app`, `etl-cron` und `grafana`.

## 4. Konfiguration über die Web-UI (Port 8000)

Öffne `http://<TrueNAS-IP>:8000`:

1. **Notion-Token** eintragen und speichern.
2. **Verbindung testen** — die sichtbaren Notion-Datenbanken erscheinen.
3. Je Rolle (Mitglieder/Gruppenstunden/Lager) die passende Datenbank
   **zuordnen**.
4. **Struktur & Mapping prüfen** — die Feld-Zuordnung wird gegen Notion
   validiert (✓ vorhanden, ✗ fehlt, · optional).
5. **Konfiguration speichern** — schreibt die `config.yaml` ins Konfig-
   Verzeichnis.

> Damit der Sync auch wirklich nach PostgreSQL schreibt, muss PostgreSQL in der
> Konfiguration aktiviert sein (`postgres.enabled: true`) und `host` auf den
> Service-Namen `postgres` zeigen. Beim ersten Start wird die `config.yaml` aus
> der Vorlage erzeugt; passe diese Werte in der Web-UI bzw. (falls nötig) in der
> `config.yaml` im Konfig-Verzeichnis an.

## 5. Ersten Sync auslösen

In der Web-UI unten auf **„Jetzt synchronisieren"** klicken. Der Server holt die
Daten aus Notion, berechnet die Kennzahlen, legt bei Bedarf das Datenbankschema
an (idempotent) und schreibt einen neuen Lauf nach PostgreSQL. Danach siehst du
eine kurze Zusammenfassung (Anzahl Mitglieder/Gruppenstunden/Lager, Top-1 und
Flop-1, die `run_id`). Der Button ist während des Laufs deaktiviert und zeigt
„läuft …".

> Der Request ist synchron: Bei vielen Daten kann er einen Moment dauern. Für
> dieses Tool (ein Verein, überschaubare Datenmengen) ist das bewusst so
> gewählt — es braucht keinen Hintergrund-Job und keine Shell.

Der `etl-cron`-Dienst wiederholt den Sync anschließend automatisch im
eingestellten Intervall.

## 6. Grafana öffnen (Port 3000)

Öffne `http://<TrueNAS-IP>:3000` (Standard-Login `admin`/`admin`, danach ändern).
Die Datenquelle und das Dashboard „Vereinsstatistik" sind bereits provisioniert
und zeigen die Kennzahlen des jüngsten Laufs sowie die Gesamtbeteiligungsquote
im Zeitverlauf.

## Fehlersuche

- **„Kein NOTION_TOKEN gesetzt"** beim Sync: Token in der Web-UI (Schritt 4.1)
  oder als Env-Variable `NOTION_TOKEN` setzen.
- **„PostgreSQL ist in der config.yaml deaktiviert"**: `postgres.enabled: true`
  setzen und `host: postgres` wählen.
- **Dashboard leer**: Erst einmal „Jetzt synchronisieren" klicken — ohne Lauf
  gibt es noch keine Daten. Weicht dein Notion-Schema stark ab, musst du ggf.
  die SQL der Dashboard-Panels anpassen.
- **Image wird nicht gezogen**: Prüfe, ob das GHCR-Paket öffentlich ist (siehe
  unten).

## Hinweis zum GHCR-Paket (einmalig)

Nach dem allerersten Push durch den GitHub-Actions-Workflow
(`.github/workflows/docker-publish.yml`) ist das Paket ggf. zunächst privat.
Stelle es im GitHub-Projekt einmalig auf **public**
(Repo → Packages → `kiro_notion` → Package settings → Visibility → Public),
damit TrueNAS es ohne Login ziehen kann.
