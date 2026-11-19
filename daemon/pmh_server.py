#!/usr/bin/env python3
"""Paint My House daemon. Started by scripts/postStart.sh, stopped by preStop.sh."""

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pmh.app import App  # noqa: E402
from pmh.server import make_servers  # noqa: E402

PLUGIN = "fpp-paint-my-house"


def main():
    media = os.environ.get("MEDIADIR", "/home/fpp/media")
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(media, "plugindata", PLUGIN))
    ap.add_argument("--fpp-config", default=os.path.join(media, "config"))
    ap.add_argument("--fpp-api", default="http://127.0.0.1")
    ap.add_argument("--www", default=os.path.join(os.path.dirname(here), "www"))
    ap.add_argument("--shm-dir", default="/dev/shm")
    ap.add_argument("--log", default=os.path.join(media, "logs", PLUGIN + ".log"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    handlers = [logging.StreamHandler()]
    try:
        os.makedirs(os.path.dirname(a.log), exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(a.log, maxBytes=512_000, backupCount=2))
    except OSError:
        pass
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=handlers)

    app = App(a.data_dir, a.fpp_config, a.fpp_api, a.shm_dir)
    vs, ad = make_servers(app, a.www, a.host)
    logging.info("Paint My House: visitors on :%d, admin on 127.0.0.1:%d, %d pixels",
                 app.settings["visitor_port"], app.settings["admin_port"], app.layout.count)

    threading.Thread(target=app.render_loop, name="render", daemon=True).start()
    threading.Thread(target=ad.serve_forever, name="admin", daemon=True).start()

    def stop(*_):
        logging.info("stopping")
        app.stop()
        threading.Thread(target=vs.shutdown, daemon=True).start()
        threading.Thread(target=ad.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    vs.serve_forever()


if __name__ == "__main__":
    main()
