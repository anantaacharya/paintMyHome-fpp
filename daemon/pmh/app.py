"""Paint My House core: visitor queue, timers, looks, render loop."""

from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import logging
import os
import re
import secrets
import threading
import time

from . import auth
from .canvas import Canvas, OpError
from .layout import load_layout
from .overlay import OverlayWriter, build_frame
from .settings import Settings

log = logging.getLogger("pmh")
LOOK_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,40}$")


class JoinError(Exception):
    def __init__(self, msg, status=403, retry_after=0):
        super().__init__(msg)
        self.status, self.retry_after = status, retry_after


class App:
    def __init__(self, data_dir: str, fpp_config_dir: str, fpp_api: str, shm_dir: str = "/dev/shm"):
        self.data_dir = data_dir
        self.fpp_config_dir = fpp_config_dir
        self.settings = Settings(data_dir)
        self.looks_dir = os.path.join(data_dir, "looks")
        os.makedirs(self.looks_dir, exist_ok=True)
        self.admin_token = self._admin_token()

        self.layout = load_layout(os.path.join(fpp_config_dir, "virtualdisplaymap"))
        self.canvas = Canvas(self.layout)
        self.overlay = OverlayWriter(fpp_api, self.settings["model_name"], fpp_config_dir, shm_dir)
        self.overlay.configure(self.layout)

        self.sessions = auth.SessionStore()
        self.lockout = auth.Lockout(max_fail=5, window=600, lock_for=300)
        self.join_limiter = auth.TokenBucket(rate=6 / 60, burst=6)  # join attempts per IP
        self.req_limiter = auth.TokenBucket(rate=10, burst=40)  # visitor requests per IP
        self.paint_limiter = auth.TokenBucket(rate=15, burst=30)  # paint calls per session

        self.lock = threading.RLock()
        self.queue: list[str] = []  # session tokens waiting
        self.active: str | None = None
        self.active_until = 0.0
        self.cooldown: dict[str, float] = {}  # device id -> earliest rejoin time
        self.events = collections.deque(maxlen=200)
        self.changed = threading.Condition()
        self._stop = threading.Event()

        if self.settings["startup_look"]:
            try:
                self.load_look(self.settings["startup_look"])
            except Exception as e:  # noqa: BLE001
                log.warning("startup look failed: %s", e)

    # ------------------------------------------------------------- utilities
    def _admin_token(self) -> str:
        p = os.path.join(self.data_dir, "admin.token")
        try:
            with open(p, "r") as f:
                t = f.read().strip()
            if len(t) >= 32:
                return t
        except OSError:
            pass
        t = secrets.token_urlsafe(32)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            f.write(t)
        return t

    def log_event(self, kind: str, msg: str):
        self.events.append({"t": time.time(), "kind": kind, "msg": msg})
        log.info("%s: %s", kind, msg)

    def notify(self):
        with self.changed:
            self.changed.notify_all()

    def in_show_hours(self, now: dt.datetime | None = None) -> bool:
        s = self.settings
        if not s["hours_enabled"]:
            return True
        now = now or dt.datetime.now()
        cur = now.hour * 60 + now.minute
        a = int(s["hours_start"][:2]) * 60 + int(s["hours_start"][3:])
        b = int(s["hours_end"][:2]) * 60 + int(s["hours_end"][3:])
        return a <= cur < b if a <= b else (cur >= a or cur < b)

    def visitors_open(self) -> tuple[bool, str]:
        if not self.settings["visitor_enabled"]:
            return False, "Painting is closed right now."
        if not self.in_show_hours():
            s = self.settings
            return False, f"Painting is open {s['hours_start']}–{s['hours_end']}."
        if not self.layout.count:
            return False, "The house layout hasn't been set up yet."
        return True, ""

    # -------------------------------------------------------------- codes
    def current_code(self) -> str:
        return auth.rotating_code(self.settings.secret, self.settings["code_period_seconds"])

    def check_credentials(self, code: str, pin: str) -> bool:
        s = self.settings
        if s["code_enabled"] and code and auth.code_valid(s.secret, s["code_period_seconds"], code):
            return True
        if s["pin_enabled"] and pin and auth.pin_valid(pin, s["pin_hash"], s["pin_salt"]):
            return True
        return False

    # --------------------------------------------------------------- visitors
    def join(self, ip: str, device: str, code: str, pin: str, nick: str) -> auth.Session:
        ok, why = self.visitors_open()
        if not ok:
            raise JoinError(why, 403)
        wait = self.lockout.locked_for(ip)
        if wait:
            raise JoinError("Too many wrong codes. Try again later.", 429, wait)
        if not self.join_limiter.allow(ip):
            raise JoinError("Slow down a little and try again.", 429, 30)
        s = self.settings
        if not (s["code_enabled"] or s["pin_enabled"]):
            raise JoinError("Painting is closed right now.", 403)
        if not self.check_credentials(code, pin):
            self.lockout.fail(ip)
            self.log_event("deny", f"bad code from {ip}")
            raise JoinError("That code didn't work. Check the sign and try again.", 403)
        self.lockout.success(ip)
        with self.lock:
            device = device or ip
            until = self.cooldown.get(device, 0)
            if until > time.time():
                raise JoinError("Give someone else a turn — you can paint again soon.", 429, int(until - time.time()) + 1)
            if len(self.queue) >= s["max_queue"]:
                raise JoinError("The line is full right now. Try again in a few minutes.", 429, 60)
            nick = re.sub(r"[^\w .\-']", "", nick or "", flags=re.UNICODE)[:20].strip() or "Visitor"
            sess = self.sessions.create(ip, nick, device)
            self.queue.append(sess.token)
            self.log_event("join", f"{nick} ({ip}) joined the line")
        self.notify()
        return sess

    def leave(self, token: str):
        with self.lock:
            if self.active == token:
                self._end_active("left")
            elif token in self.queue:
                self.queue.remove(token)
            self.sessions.drop(token)
        self.notify()

    def visitor_status(self, token: str) -> dict:
        with self.lock:
            st = {"state": "none", "queueLength": len(self.queue) + (1 if self.active else 0)}
            if token and token == self.active:
                st.update(state="active", timeLeft=max(0, int(self.active_until - time.time())))
            elif token in self.queue:
                ahead = self.queue.index(token) + (1 if self.active else 0)
                st.update(state="queued", position=ahead + 1,
                          waitSeconds=ahead * self.settings["session_seconds"])
            return st

    def visitor_paint(self, token: str, ops) -> None:
        with self.lock:
            if token != self.active:
                raise JoinError("It's not your turn yet.", 409)
        self.canvas.apply(ops, owner=False,
                          allowed_models=self.settings["allowed_models"] or None,
                          max_brightness=self.settings["visitor_max_brightness"])
        self.notify()

    def _end_active(self, why: str):
        """Caller holds self.lock."""
        tok = self.active
        if tok is None:
            return
        sess = self.sessions.get(tok)
        if sess:
            dev = sess.device or sess.ip
            self.cooldown[dev] = time.time() + self.settings["cooldown_seconds"]
            self.log_event("end", f"{sess.nick}'s turn ended ({why})")
        self.sessions.drop(tok)
        self.active = None
        if self.settings["visitor_end"] == "clear":
            with self.canvas.lock:
                self.canvas.visitor.clear()
                self.canvas.version += 1

    def tick(self):
        """Advance the queue. Called from the render loop."""
        changed = False
        with self.lock:
            now = time.time()
            if self.active and now >= self.active_until:
                self._end_active("time up")
                changed = True
            if self.active and not self.sessions.get(self.active):
                self.active = None
                changed = True
            # drop queued sessions that expired
            alive = [t for t in self.queue if self.sessions.get(t)]
            if alive != self.queue:
                self.queue = alive
                changed = True
            ok, _ = self.visitors_open()
            if not ok and self.active:
                self._end_active("painting closed")
                changed = True
            if not self.active and self.queue and ok:
                self.active = self.queue.pop(0)
                self.active_until = now + self.settings["session_seconds"]
                sess = self.sessions.get(self.active)
                if sess:
                    sess.created = now  # give them the full session TTL from here
                    self.log_event("turn", f"{sess.nick} is painting")
                changed = True
            if len(self.cooldown) > 2000:
                self.cooldown = {k: v for k, v in self.cooldown.items() if v > now}
        if changed:
            self.notify()

    # ------------------------------------------------------------------ owner
    def owner_paint(self, ops):
        self.canvas.apply(ops, owner=True)
        self.notify()

    def owner_action(self, action: str, arg=None) -> dict:
        res = {"ok": True}
        with self.lock:
            if action == "kick":
                self._end_active("removed by owner")
            elif action == "clear_queue":
                for t in self.queue:
                    self.sessions.drop(t)
                self.queue.clear()
                self.log_event("owner", "cleared the line")
            elif action == "clear_visitor":
                with self.canvas.lock:
                    self.canvas.visitor.clear()
                    self.canvas.version += 1
            elif action in ("clear_all", "release"):
                with self.canvas.lock:
                    self.canvas.visitor.clear()
                    self.canvas.base.clear()
                    self.canvas.anim = None
                    self.canvas.version += 1
                self.log_event("owner", "released lights back to the show")
            elif action == "extend":
                if self.active:
                    self.active_until += 60
            elif action == "regen_secret":
                self.settings.regenerate_secret()
                self.lockout.clear()
                self._end_active("codes reset")
                for t in self.queue:
                    self.sessions.drop(t)
                self.queue.clear()
                self.sessions.clear()
                self.log_event("owner", "reset visitor codes; all visitors signed out")
            elif action == "reload_layout":
                self.reload_layout()
                res["count"] = self.layout.count
            elif action == "install_model":
                res.update(self.overlay.install_model())
                self.log_event("owner", "installed overlay model; restart fppd to load it")
            else:
                raise ValueError("unknown action")
        self.notify()
        return res

    def reload_layout(self):
        with self.lock:
            self._end_active("layout reloaded")
            self.layout = load_layout(os.path.join(self.fpp_config_dir, "virtualdisplaymap"))
            self.canvas.set_layout(self.layout)
            self.overlay.configure(self.layout)
            self.log_event("owner", f"layout reloaded: {self.layout.count} pixels")

    def owner_status(self) -> dict:
        s = self.settings
        with self.lock:
            q = []
            for t in self.queue:
                sess = self.sessions.get(t)
                if sess:
                    q.append({"nick": sess.nick, "ip": sess.ip})
            act = None
            if self.active:
                sess = self.sessions.get(self.active)
                if sess:
                    act = {"nick": sess.nick, "ip": sess.ip, "timeLeft": max(0, int(self.active_until - time.time()))}
        open_, why = self.visitors_open()
        return {
            "settings": s.public(),
            "code": self.current_code() if s["code_enabled"] else "",
            "codeExpiresIn": auth.code_expires_in(s["code_period_seconds"]),
            "visitorsOpen": open_,
            "closedReason": why,
            "active": act,
            "queue": q,
            "layout": {"count": self.layout.count, "models": len(self.layout.models),
                       "width": self.layout.width, "height": self.layout.height,
                       "source": self.layout.source,
                       "channelStart": self.overlay.start + 1, "channelCount": self.overlay.count},
            "overlayError": self.overlay.last_error,
            "events": list(self.events)[-50:],
            "looks": self.list_looks(),
        }

    # ------------------------------------------------------------------ looks
    def _look_path(self, name: str) -> str:
        if not isinstance(name, str) or not LOOK_RE.match(name):
            raise ValueError("look names: letters, digits, space, _ and - (max 40)")
        return os.path.join(self.looks_dir, name.replace(" ", "_") + ".json")

    def list_looks(self) -> list[str]:
        out = []
        try:
            for f in sorted(os.listdir(self.looks_dir)):
                if f.endswith(".json"):
                    out.append(f[:-5].replace("_", " "))
        except OSError:
            pass
        return out

    def save_look(self, name: str):
        p = self._look_path(name)
        snap = self.canvas.snapshot_base()
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f)
        os.replace(tmp, p)
        self.log_event("owner", f"saved look '{name}'")

    def load_look(self, name: str):
        p = self._look_path(name)
        with open(p) as f:
            snap = json.load(f)
        self.canvas.restore_base(snap)
        self.notify()

    def delete_look(self, name: str):
        os.remove(self._look_path(name))

    # ----------------------------------------------------------- frame export
    def frame_b64(self) -> dict:
        rgb, al = self.canvas.composite()
        return {"v": self.canvas.version, "rgb": base64.b64encode(bytes(rgb)).decode(),
                "alpha": base64.b64encode(bytes(al)).decode()}

    # ------------------------------------------------------------ render loop
    def render_loop(self):
        last_version = -1
        last_push = 0.0
        while not self._stop.is_set():
            self.tick()
            now = time.monotonic()
            animating = self.canvas.animating()
            if self.canvas.version != last_version or animating or now - last_push > 2.0:
                last_version = self.canvas.version
                rgb, al = self.canvas.composite()
                active = any(al)
                frame = build_frame(self.layout, rgb, al, self.overlay.start, self.overlay.count) if active else b""
                self.overlay.write(frame, active, self.settings["background"] == "black")
                last_push = now
            time.sleep(0.05 if animating else 0.1)

    def stop(self):
        self._stop.set()
        try:
            self.overlay.write(b"", False, False)
        except Exception:  # noqa: BLE001
            pass
