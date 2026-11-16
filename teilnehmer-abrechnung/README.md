# Teilnehmer-Abrechnung

Erzeugt aus **einer** Datenquelle (Notion-Datenbank, alternativ CSV) automatisch
die **drei Teilnehmerlisten** für die Lager-/Event-Abrechnung:

1. **RJBH** (Ring junger Bünde Hessen) – als **Excel**, befüllt in die Original-Vorlage
2. **Kreis Offenbach** – „Liste der Teilnehmenden" als **PDF**
3. **Einfache Teilnehmerliste** – als **PDF**

Die Teilnehmer müssen danach **nur noch unterschreiben**. Alle Daten werden
**ausschließlich lokal** auf deinem Rechner verarbeitet (DSGVO).

---

## Der Grundgedanke: Single Point of Truth

Deine **Notion-Datenbank** ist die einzige Quelle. Aus ihr werden alle drei
Listen befüllt. Ändert sich etwas an den Daten, änderst du es nur in Notion.

```
Notion-DB  ──┐
             ├─►  Spalten-Mapping  ─►  internes Modell  ─►  RJBH-Excel
CSV (Backup) ─┘   (config/mapping.yaml)                      Kreis-Offenbach-PDF
                                                             Einfache-Liste-PDF
```

---

## Einrichtung (einmalig)

Voraussetzung: Python 3.10 oder neuer.

```bash
cd teilnehmer-abrechnung
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

(Unter Windows: `python -m venv .venv` und `.venv\Scripts\pip install -r requirements.txt`.)

### RJBH-Vorlage ablegen

Lege die aktuelle RJBH-Excel-Datei unter `templates/rjbh_vorlage.xlsx` ab.
**Neue Version vom RJBH?** Einfach diese Datei ersetzen – sonst nichts.

### Notion-Zugang (für den Hauptweg)

1. Integration erstellen: <https://www.notion.so/my-integrations> → Token kopieren.
2. Die Integration in deiner Datenbank verbinden (in Notion: `•••` → „Verbindungen").
3. `.env.example` zu `.env` kopieren und die beiden Werte eintragen:
   - `NOTION_TOKEN`
   - `NOTION_DATABASE_ID` (steht in der Datenbank-URL)

Die `.env` wird **nicht** in Git eingecheckt.

---

## Benutzung

Veranstaltungsdaten (Titel, An-/Abreisetag usw.) zuerst in
`config/veranstaltung.yaml` eintragen. Dann:

```bash
# Hauptweg: aus Notion
.venv/bin/python src/main.py --quelle notion

# Backup-Weg: aus einer CSV
.venv/bin/python src/main.py --quelle csv --csv input/teilnehmer.csv

# Nur eine Liste erzeugen
.venv/bin/python src/main.py --quelle notion --nur rjbh    # oder: kreis | einfach
```

Die fertigen Dateien landen im Ordner **`output/`**.

---

## Zukunftssicher: Spalten anpassen

Wenn sich in Notion ein Spaltenname ändert (oder du eine Spalte neu anlegst),
passt du **nur** `config/mapping.yaml` an. Beispiel:

```yaml
felder:
  geburtstag: "Geburtstag"     # heißt die Spalte jetzt "Geburtsdatum"?
                               # -> einfach hier den neuen Namen eintragen
```

Weitere Einstellungen in `config/mapping.yaml`:

- **`name_format`** – ob das Feld „Name" als `Vorname, Nachname` oder
  `Nachname, Vorname` aufgebaut ist (aktuell: `vorname_nachname`).
- **`betreuer_funktionsstufen`** – welche Werte der Spalte „Funktionsstufe" als
  Betreuer (PM) gelten (aktuell: nur `Gruppenleiter`; `Mitglied` und
  `Sippenführer` zählen als Teilnehmer).

---

## Der CSV-Backup-Weg

Falls die Notion-API mal nicht erreichbar ist, kannst du die Daten aus Notion
kopieren/exportieren. Die CSV braucht in der ersten Zeile die Spaltenüberschriften,
die in `config/mapping.yaml` stehen. Ein Beispiel liegt in
`input/teilnehmer_beispiel.csv`.

---

## Was wird automatisch berechnet?

- **Alter** (einfache Liste): aus Geburtsdatum zum **Anreisetag**.
- **Anzahl Tage** (Kreis Offenbach): aus An-/Abreisetag (für alle gleich).
- **Vorname/Nachname**: automatisch aus dem Feld „Name" getrennt.
- **PM/TN** und **B-Kästchen**: aus der Funktionsstufe.

Verschiedene Geburtsdatums-Schreibweisen (`16. November 2004`, `16.11.2004`,
`2004-11-16`) werden erkannt.

---

## Ordnerstruktur

```
teilnehmer-abrechnung/
├── config/
│   ├── mapping.yaml          ← Spalten-Mapping (dein Anpass-Punkt)
│   └── veranstaltung.yaml    ← Event-Daten pro Lager
├── templates/
│   └── rjbh_vorlage.xlsx     ← RJBH-Vorlage (austauschbar; selbst ablegen)
├── input/
│   └── teilnehmer_beispiel.csv
├── output/                   ← erzeugte Listen
├── src/                      ← Programmcode
└── .env                      ← Notion-Zugang (nicht in Git)
```
