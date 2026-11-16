#!/bin/sh
# =============================================================================
# Einstiegsskript fuer das Vereinsstatistik-Image.
# =============================================================================
# Waehlt den Betriebsmodus anhand des ersten Arguments:
#   * kein Argument oder "web" -> Web-UI starten (python -m vereinsstatistik.web)
#   * alles andere             -> an die CLI durchreichen
#       Beispiele:
#         init-db
#         sync
#         sync --init-db
#         sync --in data.json
# =============================================================================
set -e

if [ "$#" -eq 0 ] || [ "$1" = "web" ]; then
    exec python -m vereinsstatistik.web
fi

exec python -m vereinsstatistik.cli "$@"
