#!/bin/bash
# Start/stop the Paint My House daemon.  Usage: pmh_service.sh start|stop|restart|status
PLUGIN=fpp-paint-my-house
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEDIA="${MEDIADIR:-/home/fpp/media}"
DATA="${MEDIA}/plugindata/${PLUGIN}"
PIDFILE="${DATA}/daemon.pid"
LOG="${MEDIA}/logs/${PLUGIN}.log"

mkdir -p "${DATA}"

running() {
    [ -f "${PIDFILE}" ] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null
}

start() {
    if running; then
        echo "${PLUGIN}: already running"
        return 0
    fi
    nohup /usr/bin/python3 -I "${PLUGIN_DIR}/daemon/pmh_server.py" \
        --data-dir "${DATA}" --fpp-config "${MEDIA}/config" --log "${LOG}" \
        > /dev/null 2>> "${LOG}" &
    echo $! > "${PIDFILE}"
    echo "${PLUGIN}: started (pid $(cat "${PIDFILE}"))"
}

stop() {
    if running; then
        PID=$(cat "${PIDFILE}")
        kill "${PID}" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "${PID}" 2>/dev/null || break
            sleep 0.3
        done
        kill -9 "${PID}" 2>/dev/null
    fi
    rm -f "${PIDFILE}"
    echo "${PLUGIN}: stopped"
}

case "$1" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) if running; then echo running; else echo stopped; exit 1; fi ;;
    *) echo "usage: $0 start|stop|restart|status"; exit 2 ;;
esac
