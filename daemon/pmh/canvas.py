"""Paint state: layers of per-pixel colors plus shape rasterization.

Shapes are rasterized by hit-testing each house pixel's (x, y) against the shape,
so painting works on sparse layouts where a bitmap would be mostly empty.
All coordinates are in layout space (Layout.width x Layout.height).
"""

from __future__ import annotations

import base64
import math
import re
import threading
import time

from .layout import Layout

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

VISITOR_OPS = {"brush", "erase", "line", "rect", "ellipse", "star", "gradient", "model", "all", "clear"}
OWNER_OPS = VISITOR_OPS | {"pixels", "anim"}

MAX_OPS_PER_MESSAGE = 64
MAX_POINTS = 512
MAX_ANIM_FRAMES = 600
MAX_ANIM_BYTES = 24 * 1024 * 1024


class OpError(ValueError):
    pass


def parse_color(v) -> tuple[int, int, int]:
    if isinstance(v, str):
        m = HEX_RE.match(v)
        if not m:
            raise OpError("bad color")
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, int) for c in v):
        return tuple(max(0, min(255, c)) for c in v)  # type: ignore[return-value]
    raise OpError("bad color")


def _num(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise OpError(f"bad {name}")
    return max(lo, min(hi, float(v)))


def _pt(v, lay: Layout, name="point"):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise OpError(f"bad {name}")
    m = max(lay.width, lay.height) * 2 + 10
    return _num(v[0], -m, m, name), _num(v[1], -m, m, name)


def _seg_dist2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _star_poly(cx, cy, r, points=5):
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / points
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


class Layer:
    """RGB + coverage per pixel. alpha 0 means "not painted, show through"."""

    def __init__(self, n: int):
        self.rgb = bytearray(n * 3)
        self.alpha = bytearray(n)

    def clear(self):
        self.rgb[:] = bytes(len(self.rgb))
        self.alpha[:] = bytes(len(self.alpha))

    def any(self) -> bool:
        return any(self.alpha)

    def set(self, i, c):
        self.rgb[i * 3:i * 3 + 3] = bytes(c)
        self.alpha[i] = 1

    def erase(self, i):
        self.alpha[i] = 0

    def snapshot(self):
        return {"rgb": base64.b64encode(bytes(self.rgb)).decode(), "alpha": base64.b64encode(bytes(self.alpha)).decode()}

    def restore(self, d):
        rgb = base64.b64decode(d.get("rgb", ""))
        al = base64.b64decode(d.get("alpha", ""))
        if len(rgb) == len(self.rgb) and len(al) == len(self.alpha):
            self.rgb[:] = rgb
            self.alpha[:] = al


class Animation:
    def __init__(self, frames, alphas, delays):
        self.frames, self.alphas, self.delays = frames, alphas, delays
        self.total = sum(delays) or 1
        self.start = time.monotonic()

    def frame_index(self, now=None):
        now = time.monotonic() if now is None else now
        t = int((now - self.start) * 1000) % self.total
        for i, d in enumerate(self.delays):
            if t < d:
                return i
            t -= d
        return len(self.delays) - 1

    def snapshot(self):
        return {
            "frames": [base64.b64encode(f).decode() for f in self.frames],
            "alphas": [base64.b64encode(a).decode() for a in self.alphas],
            "delays": self.delays,
        }


class Canvas:
    """Owner (base) layer + optional base animation + visitor layer on top."""

    def __init__(self, layout: Layout):
        self.lock = threading.RLock()
        self.set_layout(layout)

    def set_layout(self, layout: Layout):
        with getattr(self, "lock", threading.RLock()):
            self.layout = layout
            n = layout.count
            self.base = Layer(n)
            self.visitor = Layer(n)
            self.anim: Animation | None = None
            self.version = 0

    # ----------------------------------------------------------------- compose
    def composite(self, now=None):
        """Return (rgb bytes, alpha bytes) for the whole house."""
        with self.lock:
            rgb = bytearray(self.base.rgb)
            al = bytearray(self.base.alpha)
            if self.anim:
                k = self.anim.frame_index(now)
                f, a = self.anim.frames[k], self.anim.alphas[k]
                for i in range(len(al)):
                    if a[i]:
                        rgb[i * 3:i * 3 + 3] = f[i * 3:i * 3 + 3]
                        al[i] = 1
            v = self.visitor
            for i in range(len(al)):
                if v.alpha[i]:
                    rgb[i * 3:i * 3 + 3] = v.rgb[i * 3:i * 3 + 3]
                    al[i] = 1
            return rgb, al

    def animating(self) -> bool:
        return self.anim is not None

    # --------------------------------------------------------------------- ops
    def apply(self, ops, *, owner: bool, allowed_models=None, max_brightness=255):
        """Validate and apply a list of ops. Raises OpError on any bad op."""
        if not isinstance(ops, list) or not ops or len(ops) > MAX_OPS_PER_MESSAGE:
            raise OpError("ops must be a non-empty list")
        allowed_ops = OWNER_OPS if owner else VISITOR_OPS
        layer = self.base if owner else self.visitor
        lay = self.layout
        n = lay.count
        allow = None
        if allowed_models:
            names = set(allowed_models)
            ok_idx = {i for i, m in enumerate(lay.models) if m.name in names}
            allow = [lay.model_of[i] in ok_idx for i in range(n)]
        scale = max(0, min(255, int(max_brightness))) / 255.0

        def colour(c):
            r, g, b = parse_color(c)
            if scale < 1:
                r, g, b = int(r * scale), int(g * scale), int(b * scale)
            return r, g, b

        with self.lock:
            for op in ops:
                if not isinstance(op, dict):
                    raise OpError("op must be an object")
                t = op.get("t")
                if t not in allowed_ops:
                    raise OpError(f"op '{t}' not allowed")
                if t in ("pixels", "anim"):
                    self._apply_bulk(op)
                    continue
                if t == "clear":
                    if allow is None:
                        layer.clear()
                    else:
                        for i in range(n):
                            if allow[i]:
                                layer.erase(i)
                    if owner:
                        self.anim = None
                    continue
                if t == "erase":
                    hit = self._hit_fn(op, lay)
                    for i in range(n):
                        if (allow is None or allow[i]) and hit(i):
                            layer.erase(i)
                    continue
                if t == "gradient":
                    c1, c2 = colour(op.get("c")), colour(op.get("c2"))
                    ax, ay = _pt(op.get("a"), lay)
                    bx, by = _pt(op.get("b"), lay)
                    dx, dy = bx - ax, by - ay
                    L = dx * dx + dy * dy or 1
                    for i in range(n):
                        if allow is None or allow[i]:
                            tt = max(0.0, min(1.0, ((lay.xs[i] - ax) * dx + (lay.ys[i] - ay) * dy) / L))
                            layer.set(i, tuple(int(c1[k] + (c2[k] - c1[k]) * tt) for k in range(3)))
                    continue
                c = colour(op.get("c"))
                hit = self._hit_fn(op, lay)
                for i in range(n):
                    if (allow is None or allow[i]) and hit(i):
                        layer.set(i, c)
            self.version += 1

    def _hit_fn(self, op, lay: Layout):
        t = op["t"]
        xs, ys = lay.xs, lay.ys
        span = max(lay.width, lay.height, 1)
        if t in ("brush", "erase"):
            pts = op.get("pts")
            if not isinstance(pts, list) or not pts or len(pts) > MAX_POINTS:
                raise OpError("bad pts")
            pts = [_pt(p, lay) for p in pts]
            r = _num(op.get("r", 3), 0.5, span / 2, "r")
            r2 = r * r
            if len(pts) == 1:
                pts = pts * 2
            segs = list(zip(pts, pts[1:]))
            minx = min(p[0] for p in pts) - r
            maxx = max(p[0] for p in pts) + r
            miny = min(p[1] for p in pts) - r
            maxy = max(p[1] for p in pts) + r

            def hit(i):
                x, y = xs[i], ys[i]
                if x < minx or x > maxx or y < miny or y > maxy:
                    return False
                return any(_seg_dist2(x, y, a[0], a[1], b[0], b[1]) <= r2 for a, b in segs)
            return hit
        if t == "line":
            ax, ay = _pt(op.get("a"), lay)
            bx, by = _pt(op.get("b"), lay)
            r = _num(op.get("r", 2), 0.5, span / 2, "r")
            r2 = r * r
            return lambda i: _seg_dist2(xs[i], ys[i], ax, ay, bx, by) <= r2
        if t in ("rect", "ellipse"):
            ax, ay = _pt(op.get("a"), lay)
            bx, by = _pt(op.get("b"), lay)
            x0, x1 = sorted((ax, bx))
            y0, y1 = sorted((ay, by))
            fill = bool(op.get("fill", True))
            w = _num(op.get("r", 2), 0.5, span / 2, "r")
            if t == "rect":
                def hit(i):
                    x, y = xs[i], ys[i]
                    inside = x0 <= x <= x1 and y0 <= y <= y1
                    if fill or not inside:
                        return inside
                    return min(x - x0, x1 - x, y - y0, y1 - y) <= w
                return hit
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            rx, ry = max((x1 - x0) / 2, 0.5), max((y1 - y0) / 2, 0.5)

            def hit(i):
                dx, dy = (xs[i] - cx) / rx, (ys[i] - cy) / ry
                d = dx * dx + dy * dy
                if fill:
                    return d <= 1
                inner_x, inner_y = max(rx - w, 0.1), max(ry - w, 0.1)
                di = ((xs[i] - cx) / inner_x) ** 2 + ((ys[i] - cy) / inner_y) ** 2
                return d <= 1 and di >= 1
            return hit
        if t == "star":
            cx, cy = _pt(op.get("a"), lay)
            rad = _num(op.get("rad", 20), 1, span, "rad")
            poly = _star_poly(cx, cy, rad)
            fill = bool(op.get("fill", True))
            w = _num(op.get("r", 2), 0.5, span / 2, "r")
            edges = list(zip(poly, poly[1:] + poly[:1]))

            def hit(i):
                x, y = xs[i], ys[i]
                if abs(x - cx) > rad + w or abs(y - cy) > rad + w:
                    return False
                if fill:
                    return _point_in_poly(x, y, poly)
                return any(_seg_dist2(x, y, a[0], a[1], b[0], b[1]) <= w * w for a, b in edges)
            return hit
        if t == "model":
            mi = op.get("m")
            if not isinstance(mi, int) or isinstance(mi, bool) or not (0 <= mi < len(lay.models)):
                raise OpError("bad model")
            mo = lay.model_of
            return lambda i: mo[i] == mi
        if t == "all":
            return lambda i: True
        raise OpError("unknown op")

    def _apply_bulk(self, op):
        n = self.layout.count
        try:
            if op["t"] == "pixels":
                rgb = base64.b64decode(op.get("rgb", ""), validate=True)
                al = base64.b64decode(op.get("alpha", ""), validate=True)
                if len(rgb) != n * 3 or len(al) != n:
                    raise OpError("pixels size mismatch (layout changed?)")
                for i in range(n):
                    if al[i]:
                        self.base.set(i, rgb[i * 3:i * 3 + 3])
                return
            frames_b64 = op.get("frames")
            alphas_b64 = op.get("alphas")
            delays = op.get("delays")
            if not (isinstance(frames_b64, list) and isinstance(alphas_b64, list) and isinstance(delays, list)):
                raise OpError("bad anim")
            if not (0 < len(frames_b64) == len(alphas_b64) == len(delays) <= MAX_ANIM_FRAMES):
                raise OpError("bad anim frame count")
            if len(frames_b64) * n * 4 > MAX_ANIM_BYTES:
                raise OpError("animation too large")
            frames = [base64.b64decode(f, validate=True) for f in frames_b64]
            alphas = [base64.b64decode(a, validate=True) for a in alphas_b64]
            if any(len(f) != n * 3 for f in frames) or any(len(a) != n for a in alphas):
                raise OpError("anim size mismatch (layout changed?)")
            ds = [int(_num(d, 20, 60000, "delay")) for d in delays]
            self.anim = Animation(frames, alphas, ds)
        except (ValueError, TypeError) as e:
            if isinstance(e, OpError):
                raise
            raise OpError("bad base64 data") from e

    # ------------------------------------------------------------------- looks
    def snapshot_base(self):
        with self.lock:
            d = {"base": self.base.snapshot(), "count": self.layout.count}
            if self.anim:
                d["anim"] = self.anim.snapshot()
            return d

    def restore_base(self, d):
        with self.lock:
            if d.get("count") != self.layout.count:
                raise OpError("look was saved for a different layout")
            self.base.restore(d.get("base", {}))
            self.anim = None
            if d.get("anim"):
                a = d["anim"]
                self._apply_bulk({"t": "anim", "frames": a["frames"], "alphas": a["alphas"], "delays": a["delays"]})
            self.version += 1
