#!/bin/sh
# =============================================================================
# Einstiegsskript fuer das Vereinsstatistik-Image.
# =============================================================================
# Waehlt den Betriebsmodus anhand des ersten Arguments:
#   * kein Argument oder "web" -> Web-UI starten (python -m vereinsstatistik.web)
#   * alles andere             -> an die CLI durchreichen
#       Beispiele: init-db | sync | sync --init-db | sync --in data.json
#
# Besonderheit TrueNAS-App:
# Das Konfig-Verzeichnis (VEREINSSTATISTIK_CONFIG_DIR) ist ein zur Laufzeit
# gemountetes Volume und gehoert zunaechst root - der unprivilegierte appuser
# koennte dort sonst keine config.yaml anlegen (fuehrte zur Crash-/Restart-
# Schleife). Laeuft das Entrypoint als root, legen wir das Verzeichnis an,
# uebergeben es an appuser und lassen den eigentlichen Prozess per gosu als
# appuser laufen. Laeuft der Container ohnehin als Nicht-Root (z. B. die
# klassische docker-compose.yml), entfaellt dieser Schritt.
# =============================================================================
set -e

CONFIG_DIR="${VEREINSSTATISTIK_CONFIG_DIR:-/app}"

# Den eigentlichen Python-Aufruf anhand des Modus bestimmen.
if [ "$#" -eq 0 ] || [ "$1" = "web" ]; then
    set -- python -m vereinsstatistik.web
else
    set -- python -m vereinsstatistik.cli "$@"
fi

# Als root: Konfig-Verzeichnis beschreibbar machen und auf appuser wechseln.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$CONFIG_DIR"
    chown -R appuser:appuser "$CONFIG_DIR" 2>/dev/null || true
    exec gosu appuser "$@"
fi

# Bereits als Nicht-Root gestartet: direkt ausfuehren.
exec "$@"
