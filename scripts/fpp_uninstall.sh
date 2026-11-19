#!/bin/bash
# Paint My House uninstall script
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
/bin/bash "${PLUGIN_DIR}/scripts/pmh_service.sh" stop
# Keep settings/looks across a Reinstall (FPP 10.4+); remove them otherwise.
if [ "${FPP_PLUGIN_REINSTALL:-0}" != "1" ]; then
    rm -rf "${MEDIADIR:-/home/fpp/media}/plugindata/fpp-paint-my-house"
fi
# The PaintMyHouse overlay model (if you created one) stays in Pixel Overlay
# Models; delete it there if you no longer want it.
