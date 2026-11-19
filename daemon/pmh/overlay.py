"""Push painted pixels to FPP through a Pixel Overlay Model.

The plugin owns one overlay model of type "Channel" (default name
``PaintMyHouse``) that spans every channel in the layout, laid out as a single
horizontal string with 3 channels per node.  For that shape FPP's channel map is
the identity, so byte ``k`` of the model buffer is output channel
``StartChannel + k`` -- which lets us place each layout pixel by its channel
number without knowing the per-model wiring.

Unpainted bytes stay 0, and the model is put in TransparentRGB state, so the
running sequence shows through everywhere the house isn't painted.
"""

from __future__ import annotations

import json
import logging
import mmap
import os
import threading
import urllib.error
import urllib.request

from .layout import Layout

log = logging.getLogger("pmh.overlay")

STATE_DISABLED = 0
STATE_ENABLED = 1
STATE_TRANSPARENT_RGB = 3


def model_definition(name: str, start_channel0: int, count: int) -> dict:
    return {
        "Name": name,
        "Type": "Channel",
        "StartChannel": start_channel0 + 1,
        "ChannelCount": count,
        "ChannelCountPerNode": 3,
        "Orientation": "horizontal",
        "StartCorner": "TL",
        "StringCount": 1,
        "StrandsPerString": 1,
        "BufferStyle": "Default",
        "Width": 0,
        "Height": 0,
        "PixelSize": 0,
        "autoCreate": False,
    }


def build_frame(layout: Layout, rgb: bytes, alpha: bytes, start: int, count: int) -> bytearray:
    """Map per-pixel colors to the overlay model's channel buffer."""
    out = bytearray(count)
    chans, cpn = layout.chans, layout.cpn
    for i in range(layout.count):
        if not alpha[i]:
            continue
        o = chans[i] - start
        r, g, b = rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]
        n = cpn[i]
        if n >= 3:
            if o + 3 <= count:
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
            if n == 4 and o + 4 <= count:
                out[o + 3] = 0  # leave the white channel alone
        elif 0 <= o < count:
            out[o] = max(r, g, b)
        # n == 2 is unusual; treat first channel as intensity
    return out


class OverlayWriter:
    def __init__(self, fpp_api: str, model_name: str, config_dir: str, shm_dir: str = "/dev/shm"):
        self.api = fpp_api.rstrip("/")
        self.model = model_name
        self.config_dir = config_dir
        self.shm_dir = shm_dir
        self.start = 0
        self.count = 0
        self._mm = None
        self._state = None
        self._lock = threading.Lock()
        self.last_error = ""

    # ------------------------------------------------------------------ http
    def _req(self, method, path, body=None, ctype="application/json", timeout=3):
        data = None
        if body is not None:
            data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
        req = urllib.request.Request(self.api + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    # --------------------------------------------------------------- set up
    def configure(self, layout: Layout):
        with self._lock:
            self.start, self.count = layout.channel_span()
            self._close_mm()
            self._state = None

    def model_status(self) -> dict:
        """Does FPP have our overlay model, and does it match the layout?"""
        try:
            info = json.loads(self._req("GET", f"/api/models/{self.model}"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"exists": False, "matches": False}
            return {"exists": False, "matches": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 - report any connection failure
            return {"exists": False, "matches": False, "error": str(e)}
        sc = int(info.get("StartChannel", 0)) - 1
        cc = int(info.get("ChannelCount", 0))
        return {
            "exists": True,
            "matches": sc == self.start and cc == self.count and info.get("Type") == "Channel",
            "startChannel": sc + 1,
            "channelCount": cc,
        }

    def install_model(self) -> dict:
        """Add/replace our model in config/model-overlays.json via FPP's API.

        FPP's POST /api/models replaces the whole file, so we read the current
        file and only touch our own entry.  fppd must restart to load it.
        """
        path = os.path.join(self.config_dir, "model-overlays.json")
        doc = {"models": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            raise RuntimeError(f"cannot read {path}: {e}") from e
        if not isinstance(doc, dict) or not isinstance(doc.get("models", []), list):
            raise RuntimeError("model-overlays.json has an unexpected shape; not touching it")
        models = [m for m in doc.get("models", []) if not (isinstance(m, dict) and m.get("Name") == self.model)]
        if self.count <= 0:
            raise RuntimeError("layout has no pixels")
        models.append(model_definition(self.model, self.start, self.count))
        doc["models"] = models
        self._req("POST", "/api/models", doc)
        return {"ok": True, "restartRequired": True}

    # --------------------------------------------------------------- output
    def _shm_path(self):
        return os.path.join(self.shm_dir, f"FPP-Model-Data-{self.model}")

    def _close_mm(self):
        if self._mm is not None:
            try:
                self._mm.close()
            except Exception:  # noqa: BLE001
                pass
        self._mm = None

    def _open_mm(self):
        if self._mm is not None:
            return self._mm
        p = self._shm_path()
        try:
            fd = os.open(p, os.O_RDWR)
        except OSError:
            return None
        try:
            if os.fstat(fd).st_size < self.count:
                return None
            self._mm = mmap.mmap(fd, self.count)
        except (OSError, ValueError):
            self._mm = None
        finally:
            os.close(fd)
        return self._mm

    def set_state(self, state: int):
        if state == self._state:
            return
        self._req("PUT", f"/api/overlays/model/{self.model}/state", {"State": state})
        self._state = state

    def write(self, frame: bytes, active: bool, opaque_background: bool):
        """Send one frame. ``active`` False releases the lights to the show."""
        with self._lock:
            try:
                if not active:
                    self.set_state(STATE_DISABLED)
                    self.last_error = ""
                    return
                mm = self._open_mm()
                if mm is not None:
                    mm.seek(0)
                    mm.write(frame)
                else:
                    w = max(1, self.count // 3)
                    self._req(
                        "PUT",
                        f"/api/overlays/model/{self.model}/data?x=0&y=0&w={w}&h=1&fmt=rgb&stopEffect=true",
                        bytes(frame[: w * 3]),
                        ctype="application/octet-stream",
                    )
                self.set_state(STATE_ENABLED if opaque_background else STATE_TRANSPARENT_RGB)
                self.last_error = ""
            except Exception as e:  # noqa: BLE001 - keep the render loop alive
                self._state = None
                self._close_mm()
                if str(e) != self.last_error:
                    log.warning("overlay write failed: %s", e)
                self.last_error = str(e)
