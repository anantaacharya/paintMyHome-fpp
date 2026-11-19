"""Plugin settings: defaults, validation, persistence."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading

from .auth import hash_pin

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")

DEFAULTS = {
    "visitor_enabled": True,
    "visitor_port": 8099,
    "admin_port": 8098,
    "public_url": "",
    "hours_enabled": False,
    "hours_start": "17:00",
    "hours_end": "22:30",
    "session_seconds": 120,
    "max_queue": 20,
    "cooldown_seconds": 60,
    "code_enabled": True,
    "code_period_seconds": 300,
    "pin_enabled": False,
    "pin_hash": "",
    "pin_salt": "",
    "visitor_max_brightness": 200,
    "allowed_models": [],
    "background": "show",  # "show" = sequence shows through, "black" = everything else off
    "visitor_end": "clear",  # "clear" or "keep" the visitor's painting when their time ends
    "model_name": "PaintMyHouse",
    "startup_look": "",
}

# field -> validator returning the cleaned value or raising ValueError
def _bool(v):
    if isinstance(v, bool):
        return v
    raise ValueError("expected true/false")


def _int(lo, hi):
    def f(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("expected a number")
        v = int(v)
        if not lo <= v <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return v
    return f


def _time(v):
    if isinstance(v, str) and TIME_RE.match(v):
        return v
    raise ValueError("expected HH:MM")


def _choice(*opts):
    def f(v):
        if v in opts:
            return v
        raise ValueError(f"must be one of {', '.join(opts)}")
    return f


def _url(v):
    if v == "" or (isinstance(v, str) and re.match(r"^https?://[A-Za-z0-9.\-:\[\]]+(/[A-Za-z0-9._~/\-]*)?$", v) and len(v) < 200):
        return v
    raise ValueError("expected an http(s) URL")


def _models(v):
    if isinstance(v, list) and len(v) <= 2000 and all(isinstance(s, str) and len(s) < 200 for s in v):
        return v
    raise ValueError("expected a list of model names")


def _model_name(v):
    if isinstance(v, str) and MODEL_NAME_RE.match(v):
        return v
    raise ValueError("letters, digits and _ only")


def _look_name(v):
    if v == "" or (isinstance(v, str) and re.match(r"^[A-Za-z0-9 _\-]{1,40}$", v)):
        return v
    raise ValueError("bad look name")


VALIDATORS = {
    "visitor_enabled": _bool,
    "visitor_port": _int(1024, 65535),
    "admin_port": _int(1024, 65535),
    "public_url": _url,
    "hours_enabled": _bool,
    "hours_start": _time,
    "hours_end": _time,
    "session_seconds": _int(15, 1800),
    "max_queue": _int(1, 500),
    "cooldown_seconds": _int(0, 3600),
    "code_enabled": _bool,
    "code_period_seconds": _int(30, 86400),
    "pin_enabled": _bool,
    "visitor_max_brightness": _int(10, 255),
    "allowed_models": _models,
    "background": _choice("show", "black"),
    "visitor_end": _choice("clear", "keep"),
    "model_name": _model_name,
    "startup_look": _look_name,
}

RESTART_KEYS = {"visitor_port", "admin_port", "model_name"}


class Settings:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, "settings.json")
        self.secret_path = os.path.join(data_dir, "secret.key")
        self._lock = threading.Lock()
        self.values = dict(DEFAULTS)
        os.makedirs(data_dir, exist_ok=True)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for k, v in stored.items():
                if k in ("pin_hash", "pin_salt") and isinstance(v, str):
                    self.values[k] = v
                elif k in VALIDATORS:
                    try:
                        self.values[k] = VALIDATORS[k](v)
                    except ValueError:
                        pass
        except (OSError, ValueError):
            pass
        self.secret = self._load_secret()

    def __getitem__(self, k):
        return self.values[k]

    def public(self) -> dict:
        d = {k: v for k, v in self.values.items() if k not in ("pin_hash", "pin_salt")}
        d["pin_set"] = bool(self.values["pin_hash"])
        return d

    def update(self, changes: dict) -> list[str]:
        """Apply validated changes. Returns names that need a daemon restart."""
        if not isinstance(changes, dict):
            raise ValueError("expected an object")
        cleaned = {}
        errors = {}
        for k, v in changes.items():
            if k == "pin":
                if v in ("", None):
                    cleaned["pin_hash"], cleaned["pin_salt"] = "", ""
                elif isinstance(v, str) and re.match(r"^[0-9A-Za-z]{4,32}$", v):
                    cleaned["pin_hash"], cleaned["pin_salt"] = hash_pin(v)
                else:
                    errors[k] = "PIN must be 4-32 letters/digits"
                continue
            if k not in VALIDATORS:
                errors[k] = "unknown setting"
                continue
            try:
                cleaned[k] = VALIDATORS[k](v)
            except ValueError as e:
                errors[k] = str(e)
        if errors:
            raise ValueError(json.dumps(errors))
        with self._lock:
            restart = [k for k in cleaned if k in RESTART_KEYS and cleaned[k] != self.values.get(k)]
            self.values.update(cleaned)
            self._save()
        return restart

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.values, f, indent=1)
        os.replace(tmp, self.path)

    def _load_secret(self) -> bytes:
        try:
            with open(self.secret_path, "rb") as f:
                s = f.read()
            if len(s) >= 32:
                return s
        except OSError:
            pass
        return self.regenerate_secret()

    def regenerate_secret(self) -> bytes:
        s = secrets.token_bytes(32)
        fd = os.open(self.secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(s)
        self.secret = s
        return s
