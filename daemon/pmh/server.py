"""HTTP servers.

* Visitor server: listens on all interfaces (default :8099). Serves the phone UI
  and the visitor API only. Nothing here can reach FPP or the file system.
* Admin server: listens on 127.0.0.1 only (default :8098) and additionally
  requires the admin token that FPP's api.php reads from the plugin data dir.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .app import App, JoinError
from .canvas import OpError

log = logging.getLogger("pmh.http")

MAX_VISITOR_BODY = 64 * 1024
EVENT_STREAMS = threading.BoundedSemaphore(64)  # cap long-lived SSE threads
MAX_ADMIN_BODY = 40 * 1024 * 1024
COOKIE = "pmh_s"
DEVICE_COOKIE = "pmh_d"

STATIC = {
    "/": ("visitor.html", "text/html; charset=utf-8"),
    "/join": ("visitor.html", "text/html; charset=utf-8"),
    "/static/visitor.js": ("visitor.js", "text/javascript; charset=utf-8"),
    "/static/paint.js": ("paint.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class _Base(BaseHTTPRequestHandler):
    app: App = None  # type: ignore[assignment]
    www_dir: str = ""
    protocol_version = "HTTP/1.1"
    server_version = "PaintMyHouse"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet default stderr logging
        log.debug("%s " + fmt, self.client_address[0], *args)

    def send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, status, retry_after=0):
        h = {"Retry-After": str(retry_after)} if retry_after else None
        self.send_json({"ok": False, "error": msg, "retryAfter": retry_after}, status, h)

    def read_json(self, limit):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > limit:
            self.close_connection = True
            raise ValueError("request too large")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            raise ValueError("expected application/json")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw)
        except ValueError as e:
            raise ValueError("bad JSON") from e


# =============================================================== visitor server
class VisitorHandler(_Base):
    def _ip(self):
        return self.client_address[0]

    def _cookies(self):
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            pass
        return c

    def _token(self):
        c = self._cookies().get(COOKIE)
        return c.value if c else None

    def _device(self):
        c = self._cookies().get(DEVICE_COOKIE)
        v = c.value if c else ""
        return v if re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", v) else ""

    def _rate_ok(self, cost=1.0):
        if self.app.req_limiter.allow(self._ip(), cost):
            return True
        self.send_error_json("Too many requests", 429, 5)
        return False

    def _same_origin(self):
        """CSRF guard for state-changing requests."""
        if self.headers.get("X-PMH") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            return urlsplit(origin).netloc == host
        return True

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        if not self._rate_ok(0.5):
            return
        path = urlsplit(self.path).path
        if path in STATIC:
            return self._static(*STATIC[path])
        if path == "/api/status":
            ok, why = self.app.visitors_open()
            st = self.app.visitor_status(self._token())
            st.update(open=ok, closedReason=why,
                      needCode=self.app.settings["code_enabled"],
                      pinAllowed=self.app.settings["pin_enabled"],
                      sessionSeconds=self.app.settings["session_seconds"])
            return self.send_json(st)
        sess = self.app.sessions.get(self._token())
        if not sess:
            return self.send_error_json("Please enter the code first.", 401)
        if path == "/api/layout":
            d = self.app.layout.to_json()
            allowed = self.app.settings["allowed_models"]
            d["allowedModels"] = allowed
            d["maxBrightness"] = self.app.settings["visitor_max_brightness"]
            return self.send_json(d)
        if path == "/api/frame":
            return self.send_json(self.app.frame_b64())
        if path == "/api/events":
            return self._events(sess.token)
        self.send_error_json("Not found", 404)

    def _static(self, name, ctype):
        p = os.path.join(self.www_dir, name)
        try:
            with open(p, "rb") as f:
                body = f.read()
        except OSError:
            return self.send_error_json("Not found", 404)
        self.send_response(200)
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if not self._device():
            dev = secrets.token_urlsafe(18)
            self.send_header("Set-Cookie", f"{DEVICE_COOKIE}={dev}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def _events(self, token):
        """Server-sent events: status every ~0.5 s, frames when they change."""
        if not EVENT_STREAMS.acquire(blocking=False):
            return self.send_error_json("Busy, try again", 503, 5)
        try:
            self._events_inner(token)
        finally:
            EVENT_STREAMS.release()

    def _events_inner(self, token):
        self.send_response(200)
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        last_v = -1
        last_frame = 0.0
        frame_interval = 0.2 if self.app.layout.count < 10000 else 0.5
        deadline = time.time() + 15 * 60
        try:
            while time.time() < deadline:
                st = self.app.visitor_status(token)
                self.wfile.write(b"event: status\ndata: " + json.dumps(st).encode() + b"\n\n")
                now = time.monotonic()
                if (self.app.canvas.version != last_v or self.app.canvas.animating()) and now - last_frame >= frame_interval:
                    fr = self.app.frame_b64()
                    last_v, last_frame = fr["v"], now
                    self.wfile.write(b"event: frame\ndata: " + json.dumps(fr).encode() + b"\n\n")
                self.wfile.flush()
                if st["state"] == "none":
                    break
                with self.app.changed:
                    self.app.changed.wait(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # --------------------------------------------------------------- POST
    def do_POST(self):
        if not self._rate_ok():
            return
        if not self._same_origin():
            return self.send_error_json("Forbidden", 403)
        path = urlsplit(self.path).path
        try:
            body = self.read_json(MAX_VISITOR_BODY)
        except ValueError as e:
            return self.send_error_json(str(e), 400)
        if not isinstance(body, dict):
            return self.send_error_json("bad request", 400)
        try:
            if path == "/api/join":
                code = str(body.get("code", ""))[:12].strip()
                pin = str(body.get("pin", ""))[:32].strip()
                nick = str(body.get("nick", ""))[:40]
                sess = self.app.join(self._ip(), self._device(), code, pin, nick)
                ck = f"{COOKIE}={sess.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=7200"
                return self.send_json({"ok": True, **self.app.visitor_status(sess.token)},
                                      extra_headers={"Set-Cookie": ck})
            sess = self.app.sessions.get(self._token())
            if not sess:
                return self.send_error_json("Please enter the code first.", 401)
            if path == "/api/paint":
                if not self.app.paint_limiter.allow(sess.token):
                    return self.send_error_json("Painting too fast", 429, 1)
                self.app.visitor_paint(sess.token, body.get("ops"))
                return self.send_json({"ok": True})
            if path == "/api/leave":
                self.app.leave(sess.token)
                return self.send_json({"ok": True}, extra_headers={
                    "Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
            return self.send_error_json("Not found", 404)
        except JoinError as e:
            return self.send_error_json(str(e), e.status, e.retry_after)
        except OpError as e:
            return self.send_error_json(str(e), 400)


# ================================================================ admin server
class AdminHandler(_Base):
    def _authorized(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return False
        tok = self.headers.get("X-PMH-Admin", "")
        return hmac.compare_digest(tok.encode(), self.app.admin_token.encode())

    def _route(self, method):
        if not self._authorized():
            return self.send_error_json("Forbidden", 403)
        u = urlsplit(self.path)
        path = u.path
        body = None
        if method in ("POST", "PUT"):
            try:
                body = self.read_json(MAX_ADMIN_BODY)
            except ValueError as e:
                return self.send_error_json(str(e), 400)
        try:
            if method == "GET" and path == "/admin/status":
                return self.send_json(self.app.owner_status())
            if method == "GET" and path == "/admin/layout":
                return self.send_json(self.app.layout.to_json())
            if method == "GET" and path == "/admin/frame":
                return self.send_json(self.app.frame_b64())
            if method == "GET" and path == "/admin/model":
                return self.send_json(self.app.overlay.model_status())
            if method == "PUT" and path == "/admin/settings":
                restart = self.app.settings.update(body)
                self.app.notify()
                return self.send_json({"ok": True, "restartDaemon": restart, "settings": self.app.settings.public()})
            if method == "POST" and path == "/admin/paint":
                self.app.owner_paint(body.get("ops") if isinstance(body, dict) else None)
                return self.send_json({"ok": True})
            if method == "POST" and path == "/admin/action":
                return self.send_json(self.app.owner_action(str(body.get("action", ""))))
            if method == "POST" and path == "/admin/looks/save":
                self.app.save_look(body.get("name"))
                return self.send_json({"ok": True, "looks": self.app.list_looks()})
            if method == "POST" and path == "/admin/looks/load":
                self.app.load_look(body.get("name"))
                return self.send_json({"ok": True})
            if method == "POST" and path == "/admin/looks/delete":
                self.app.delete_look(body.get("name"))
                return self.send_json({"ok": True, "looks": self.app.list_looks()})
            return self.send_error_json("Not found", 404)
        except OpError as e:
            return self.send_error_json(str(e), 400)
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            return self.send_error_json(str(e), 400)
        except Exception as e:  # noqa: BLE001
            log.exception("admin error")
            return self.send_error_json(f"internal error: {e}", 500)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")


def make_servers(app: App, www_dir: str, visitor_host="0.0.0.0"):
    VisitorHandler.app = AdminHandler.app = app
    VisitorHandler.www_dir = www_dir
    vs = ThreadingHTTPServer((visitor_host, app.settings["visitor_port"]), VisitorHandler)
    vs.daemon_threads = True
    ad = ThreadingHTTPServer(("127.0.0.1", app.settings["admin_port"]), AdminHandler)
    ad.daemon_threads = True
    return vs, ad
