"""A tiny stand-in for fppd's overlay API, for local testing.

Run: python3 tests/mock_fpp.py 8780
Records the last state and data written to each overlay model; GET /mock/log
returns them.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

STATE = {"models": {}, "writes": 0, "states": [], "posted": None}
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, status=200):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n)

    def do_GET(self):
        p = urlsplit(self.path).path
        if p == "/mock/log":
            with LOCK:
                return self._send({k: v for k, v in STATE.items()})
        if p.startswith("/api/models/"):
            name = p.split("/")[3]
            with LOCK:
                m = STATE["models"].get(name)
            return self._send(m) if m else self._send({"error": "nf"}, 404)
        self._send({}, 404)

    def do_POST(self):
        p = urlsplit(self.path).path
        if p == "/api/models":
            doc = json.loads(self._body())
            with LOCK:
                STATE["posted"] = doc
                for m in doc["models"]:
                    STATE["models"][m["Name"]] = m
            return self._send({"Status": "OK"})
        self._send({}, 404)

    def do_PUT(self):
        p = urlsplit(self.path).path
        parts = p.split("/")
        body = self._body()
        if p.startswith("/api/overlays/model/"):
            name, what = parts[4], parts[5]
            with LOCK:
                if what == "state":
                    STATE["states"].append(json.loads(body)["State"])
                    STATE["states"] = STATE["states"][-20:]
                elif what == "data":
                    STATE["writes"] += 1
                    STATE["last_nonzero"] = sum(1 for b in body if b)
                    STATE["last_len"] = len(body)
            return self._send({"Status": "OK"})
        self._send({}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
