"""Load the house layout that xLights exports to FPP.

Primary source is FPP's ``config/virtualdisplaymap`` (written by xLights when you
upload a layout / configure a Virtual Display).  Format::

    # Model: 'Arch 1'
    <previewWidth>,<previewHeight>
    x,y,z,channel,channelsPerNode,colorOrder[,size]
    x,y,channel,channelsPerNode,colorOrder            (older 2D form)

``channel`` is 0-based, ``y`` grows upward (we flip it so y grows downward
like a canvas).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_PIXELS = 400_000
MAX_CHANNEL = 8_000_000


@dataclass
class Model:
    name: str
    first: int  # index of first pixel in Layout.pixels
    count: int = 0

    def to_json(self):
        return {"name": self.name, "first": self.first, "count": self.count}


@dataclass
class Layout:
    width: int = 0
    height: int = 0
    xs: list = field(default_factory=list)  # canvas x per pixel
    ys: list = field(default_factory=list)  # canvas y per pixel (down)
    chans: list = field(default_factory=list)  # 0-based first channel
    cpn: list = field(default_factory=list)  # channels per node
    model_of: list = field(default_factory=list)  # model index per pixel
    models: list = field(default_factory=list)
    source: str = ""

    @property
    def count(self) -> int:
        return len(self.xs)

    def channel_span(self):
        """(first channel, channel count) covering every pixel, count % 3 == 0."""
        if not self.chans:
            return 0, 0
        lo = min(self.chans)
        hi = max(c + max(1, n) for c, n in zip(self.chans, self.cpn))
        n = hi - lo
        n += (-n) % 3
        return lo, n

    def model_index(self, name: str) -> int:
        for i, m in enumerate(self.models):
            if m.name == name:
                return i
        return -1

    def to_json(self):
        return {
            "width": self.width,
            "height": self.height,
            "count": self.count,
            "source": self.source,
            "xs": self.xs,
            "ys": self.ys,
            "model": self.model_of,
            "models": [m.to_json() for m in self.models],
        }


_MODEL_RE = re.compile(r"Model:\s*'(.*)'")


def parse_virtualdisplaymap(text: str) -> Layout:
    lay = Layout(source="virtualdisplaymap")
    seen_header = False
    raw = []  # (x, y, ch, cpn, model)
    model_idx = -1
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _MODEL_RE.search(line)
            if m:
                lay.models.append(Model(name=m.group(1), first=len(raw)))
                model_idx = len(lay.models) - 1
            continue
        parts = line.split(",")
        if not seen_header:
            if len(parts) == 2:
                try:
                    lay.width = int(float(parts[0]))
                    lay.height = int(float(parts[1]))
                except ValueError:
                    pass
                seen_header = True
                continue
            seen_header = True
        try:
            if len(parts) >= 6:
                x, y, ch, cpn = int(float(parts[0])), int(float(parts[1])), int(parts[3]), int(parts[4])
            elif len(parts) >= 5:
                x, y, ch, cpn = int(float(parts[0])), int(float(parts[1])), int(parts[2]), int(parts[3])
            else:
                continue
        except ValueError:
            continue
        if ch < 0 or ch > MAX_CHANNEL or cpn < 1 or cpn > 4:
            continue
        if x < -100000 or x > 100000 or y < -100000 or y > 100000:
            continue  # unplaced models export as INT_MIN
        if model_idx < 0:
            lay.models.append(Model(name="Pixels", first=0))
            model_idx = 0
        raw.append((x, y, ch, cpn, model_idx))
        if len(raw) >= MAX_PIXELS:
            break

    if not raw:
        return lay
    if lay.width <= 0 or lay.height <= 0:
        lay.width = max(r[0] for r in raw) + 1
        lay.height = max(r[1] for r in raw) + 1
    # drop models that ended up with no placed pixels and re-index
    used = sorted({r[4] for r in raw})
    remap = {old: new for new, old in enumerate(used)}
    lay.models = [Model(name=lay.models[old].name, first=0) for old in used]
    for x, y, ch, cpn, mi in raw:
        idx = remap[mi]
        m = lay.models[idx]
        if m.count == 0:
            m.first = len(lay.xs)
        m.count += 1
        lay.xs.append(x)
        lay.ys.append(lay.height - 1 - y)
        lay.chans.append(ch)
        lay.cpn.append(cpn)
        lay.model_of.append(idx)
    return lay


def load_layout(path: str) -> Layout:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_virtualdisplaymap(f.read())
    except OSError:
        return Layout(source="missing")
