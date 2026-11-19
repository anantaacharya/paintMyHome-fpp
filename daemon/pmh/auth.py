"""Visitor authentication: rotating codes, static PIN, sessions, rate limits."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import threading
import time


# ---------------------------------------------------------------- rotating code
def rotating_code(secret: bytes, period: int, now: float | None = None, offset: int = 0) -> str:
    """6-digit HOTP-style code for the time window containing ``now``."""
    now = time.time() if now is None else now
    counter = int(now // max(30, period)) + offset
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha256).digest()
    o = digest[-1] & 0x0F
    val = (struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{val:06d}"


def code_valid(secret: bytes, period: int, code: str, now: float | None = None) -> bool:
    """Accept the current and previous window (people scan just before it flips)."""
    if not code or len(code) != 6 or not code.isdigit():
        return False
    ok = False
    for off in (0, -1):
        ok |= hmac.compare_digest(rotating_code(secret, period, now, off), code)
    return ok


def code_expires_in(period: int, now: float | None = None) -> int:
    now = time.time() if now is None else now
    period = max(30, period)
    return int(period - (now % period))


# ------------------------------------------------------------------------- PIN
PBKDF2_ROUNDS = 120_000


def hash_pin(pin: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return h.hex(), salt


def pin_valid(pin: str, pin_hash: str, salt: str) -> bool:
    if not pin or not pin_hash or not salt or len(pin) > 32:
        return False
    h, _ = hash_pin(pin, salt)
    return hmac.compare_digest(h, pin_hash)


# --------------------------------------------------------------- rate limiting
class TokenBucket:
    """Per-key token buckets: ``rate`` tokens/sec, up to ``burst``."""

    def __init__(self, rate: float, burst: int):
        self.rate, self.burst = rate, burst
        self._b: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._b.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < cost:
                self._b[key] = (tokens, now)
                return False
            self._b[key] = (tokens - cost, now)
            if len(self._b) > 5000:  # bound memory
                cutoff = now - 600
                self._b = {k: v for k, v in self._b.items() if v[1] > cutoff}
            return True


class Lockout:
    """Lock an IP out after ``max_fail`` bad codes within ``window`` seconds."""

    def __init__(self, max_fail: int = 5, window: int = 600, lock_for: int = 600):
        self.max_fail, self.window, self.lock_for = max_fail, window, lock_for
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked_for(self, ip: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            until = self._locked.get(ip, 0)
            if until > now:
                return int(until - now) + 1
            self._locked.pop(ip, None)
            return 0

    def fail(self, ip: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            lst = [t for t in self._fails.get(ip, []) if t > now - self.window]
            lst.append(now)
            if len(lst) >= self.max_fail:
                self._locked[ip] = now + self.lock_for
                lst = []
            self._fails[ip] = lst

    def success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)

    def clear(self) -> None:
        with self._lock:
            self._fails.clear()
            self._locked.clear()


# -------------------------------------------------------------------- sessions
class Session:
    __slots__ = ("token", "ip", "created", "last_seen", "nick", "device")

    def __init__(self, token: str, ip: str, nick: str, device: str = ""):
        self.token, self.ip, self.nick, self.device = token, ip, nick, device
        self.created = self.last_seen = time.time()


class SessionStore:
    """Server-side visitor sessions. Tokens are random 256-bit values."""

    TTL = 2 * 60 * 60  # a joined visitor has 2 h to reach the front of the line

    def __init__(self):
        self._s: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, ip: str, nick: str = "", device: str = "") -> Session:
        s = Session(secrets.token_urlsafe(32), ip, nick, device)
        with self._lock:
            self._gc()
            self._s[s.token] = s
        return s

    def get(self, token: str | None) -> Session | None:
        if not token or len(token) > 100:
            return None
        with self._lock:
            s = self._s.get(token)
            if s and time.time() - s.created > self.TTL:
                self._s.pop(token, None)
                return None
            if s:
                s.last_seen = time.time()
            return s

    def drop(self, token: str) -> None:
        with self._lock:
            self._s.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._s.clear()

    def _gc(self):
        now = time.time()
        for t in [t for t, s in self._s.items() if now - s.created > self.TTL]:
            del self._s[t]
