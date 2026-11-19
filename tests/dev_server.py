"""Run the whole plugin locally without FPP.

    python3 tests/dev_server.py [--data DIR]

* mock fppd overlay API on 127.0.0.1:8780
* the Paint My House daemon (visitor :8099, admin 127.0.0.1:8098) using the
  sample layout in tests/fixtures/
* an "FPP UI" harness on http://127.0.0.1:8090/ that serves owner.php /
  sign.php and proxies /api/plugin/fpp-paint-my-house/* the way api.php does.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CTYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".png": "image/png"}

ROUTES = {
    ("GET", "status"): ("GET", "/admin/status"),
    ("GET", "layout"): ("GET", "/admin/layout"),
    ("GET", "frame"): ("GET", "/admin/frame"),
    ("GET", "model"): ("GET", "/admin/model"),
    ("PUT", "settings"): ("PUT", "/admin/settings"),
    ("POST", "paint"): ("POST", "/admin/paint"),
    ("POST", "action"): ("POST", "/admin/action"),
    ("POST", "looks/save"): ("POST", "/admin/looks/save"),
    ("POST", "looks/load"): ("POST", "/admin/looks/load"),
    ("POST", "looks/delete"): ("POST", "/admin/looks/delete"),
}


def render_php(name):
    with open(os.path.join(ROOT, name)) as f:
        s = f.read()
    s = re.sub(r"<\?php.*?\?>", "", s, count=1, flags=re.S)
    s = s.replace("<?= $pmhBase ?>", "/f/")
    if not s.lstrip().startswith("<!doctype"):
        s = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             "<title>FPP harness</title><style>body{font-family:system-ui,sans-serif;margin:16px}</style></head><body>"
             + s + "</body></html>")
    return s.encode()


def make_handler(data_dir):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype="text/html", status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self, method):
            u = urlsplit(self.path)
            sub = u.path[len("/api/plugin/fpp-paint-my-house/"):]
            if sub == "service/restart":
                return self._send(b'{"ok":true}', "application/json")
            r = ROUTES.get((method, sub))
            if not r:
                return self._send(b'{"ok":false}', "application/json", 404)
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n) if n else None
            with open(os.path.join(data_dir, "admin.token")) as f:
                tok = f.read().strip()
            req = urllib.request.Request("http://127.0.0.1:8098" + r[1], data=body, method=r[0])
            req.add_header("X-PMH-Admin", tok)
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return self._send(resp.read(), "application/json", resp.status)
            except urllib.error.HTTPError as e:
                return self._send(e.read(), "application/json", e.code)

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path.startswith("/api/plugin/fpp-paint-my-house/"):
                return self._proxy("GET")
            if u.path in ("/", "/owner"):
                return self._send(render_php("owner.php"))
            if u.path == "/plugin.php":
                page = parse_qs(u.query).get("page", [""])[0]
                if page in ("sign.php", "help.php", "owner.php"):
                    return self._send(render_php(page))
            if u.path.startswith("/f/"):
                rel = os.path.normpath(u.path[3:])
                if rel.startswith("..") or not rel.startswith("www/"):
                    return self._send(b"no", status=404)
                p = os.path.join(ROOT, rel)
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        return self._send(f.read(), CTYPES.get(os.path.splitext(p)[1], "text/plain"))
            self._send(b"not found", status=404)

        def do_POST(self):
            self._proxy("POST")

        def do_PUT(self):
            self._proxy("PUT")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    a = ap.parse_args()
    base = a.data or tempfile.mkdtemp(prefix="pmh-dev-")
    data, config, shm = (os.path.join(base, d) for d in ("data", "config", "shm"))
    for d in (data, config, shm):
        os.makedirs(d, exist_ok=True)
    shutil.copy(os.path.join(HERE, "fixtures", "virtualdisplaymap"), config)
    procs = [
        subprocess.Popen([sys.executable, os.path.join(HERE, "mock_fpp.py"), "8780"]),
        subprocess.Popen([sys.executable, os.path.join(ROOT, "daemon", "pmh_server.py"), "--data-dir", data,
                          "--fpp-config", config, "--fpp-api", "http://127.0.0.1:8780", "--shm-dir", shm,
                          "--log", os.path.join(base, "pmh.log")]),
    ]
    for _ in range(50):
        if os.path.exists(os.path.join(data, "admin.token")):
            break
        time.sleep(0.1)
    srv = ThreadingHTTPServer(("127.0.0.1", 8090), make_handler(data))
    print(f"owner harness: http://127.0.0.1:8090/   visitor: http://127.0.0.1:8099/   data: {base}", flush=True)
    try:
        srv.serve_forever()
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
