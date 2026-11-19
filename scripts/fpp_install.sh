#!/bin/bash
# Paint My House install script
. ${FPPDIR}/scripts/common
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${MEDIADIR}/plugindata/fpp-paint-my-house/looks"
chmod +x "${PLUGIN_DIR}/scripts/"*.sh
# Start the visitor/owner service now; postStart.sh starts it on every fppd start.
/bin/bash "${PLUGIN_DIR}/scripts/pmh_service.sh" restart
