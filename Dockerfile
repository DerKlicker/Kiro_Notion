# =============================================================================
# Vereinsstatistik - Container-Image (Phase 3: Notion -> PostgreSQL -> Grafana)
# =============================================================================
# Schlankes Python-3.11-Image. Das gleiche Image bedient zwei Modi:
#   * Standard (CMD): die Web-UI auf Port 8000 (python -m vereinsstatistik.web).
#   * Ueberschrieben: ETL-Kommandos der CLI, z. B.
#       docker compose run --rm app init-db
#       docker compose run --rm app sync
#     Das ENTRYPOINT ist auf die CLI gesetzt, der Web-Start ist ein Sonderfall
#     (eigenes Unterkommando "web" am Ende dieses Files, siehe CMD).
# =============================================================================

FROM python:3.11-slim

# Python-Verhalten im Container: keine .pyc-Dateien, ungepufferte Ausgabe
# (damit Logs sofort in docker logs erscheinen).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Arbeitsverzeichnis. Hierher wird spaeter config.yaml gemountet (/app/config.yaml).
WORKDIR /app

# Abhaengigkeiten zuerst - nur requirements.txt kopieren, damit der pip-Layer
# im Cache bleibt, solange sich die Abhaengigkeiten nicht aendern.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode, Referenz-Konfiguration und Einstiegsskript kopieren.
# config.yaml wird bewusst NICHT ins Image gebacken - sie kommt zur Laufzeit
# per Volume-Mount. Nur config.example.yaml dient als Referenz im Image.
COPY vereinsstatistik/ ./vereinsstatistik/
COPY config.example.yaml ./config.example.yaml
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Nicht-Root-Benutzer anlegen, Einstiegsskript ausfuehrbar machen und
# Eigentum uebertragen. So laeuft der Prozess ohne Root-Rechte; das
# /app-Verzeichnis gehoert dem Benutzer, damit das Schreiben von config.yaml
# ueber die Web-UI (Bind-Mount) funktioniert.
RUN useradd --create-home --uid 10001 appuser \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R appuser:appuser /app
USER appuser

# Die Web-UI lauscht auf 8000 (siehe web.main: host 0.0.0.0, port 8000).
EXPOSE 8000

# Einstiegsskript waehlt den Modus:
#   * ohne Argumente / "web"  -> Web-UI
#   * sonst                   -> python -m vereinsstatistik.cli <args>
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Standardmodus: Web-UI. Wird durch ein Compose-/Run-Command ueberschrieben
# (z. B. "init-db" oder "sync").
CMD ["web"]
