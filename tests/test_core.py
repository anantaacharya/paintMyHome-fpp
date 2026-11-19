import base64
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "daemon"))

from pmh import auth  # noqa: E402
from pmh.app import App, JoinError  # noqa: E402
from pmh.canvas import Canvas, OpError  # noqa: E402
from pmh.layout import load_layout, parse_virtualdisplaymap  # noqa: E402
from pmh.overlay import build_frame, model_definition  # noqa: E402
from pmh.settings import Settings  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "virtualdisplaymap")


@pytest.fixture
def layout():
    return load_layout(FIXTURE)


# --------------------------------------------------------------------- layout
def test_layout_parses_models_and_flips_y(layout):
    assert layout.count == 1138
    assert [m.name for m in layout.models][:3] == ["Roof Left", "Roof Right", "Eave"]
    assert (layout.width, layout.height) == (800, 500)
    # first roof pixel is at y=300 from the bottom -> 199 from the top
    assert layout.ys[0] == 500 - 1 - 300
    assert layout.channel_span() == (0, 1138 * 3)


def test_layout_handles_2d_form_unplaced_and_garbage():
    text = "# Model: 'A'\n100,50\n1,2,30,3,RGB\n-2147483648,5,33,3,RGB\nnot,a,line\n5,6,36,1,W\n# Model: 'Empty'\n"
    lay = parse_virtualdisplaymap(text)
    assert lay.count == 2
    assert [m.name for m in lay.models] == ["A"]
    assert lay.chans == [30, 36]
    start, count = lay.channel_span()
    assert start == 30 and count % 3 == 0 and count >= 7


# --------------------------------------------------------------------- canvas
def test_brush_hits_only_nearby_pixels(layout):
    c = Canvas(layout)
    c.apply([{"t": "brush", "pts": [[400, 40]], "r": 20, "c": "#00ff00"}], owner=False)
    rgb, al = c.composite()
    hits = [i for i in range(layout.count) if al[i]]
    assert hits
    for i in hits:
        assert (layout.xs[i] - 400) ** 2 + (layout.ys[i] - 40) ** 2 <= 20 ** 2
        assert tuple(rgb[i * 3:i * 3 + 3]) == (0, 255, 0)


def test_visitor_cannot_use_owner_ops(layout):
    c = Canvas(layout)
    with pytest.raises(OpError):
        c.apply([{"t": "pixels", "rgb": "", "alpha": ""}], owner=False)
    with pytest.raises(OpError):
        c.apply([{"t": "anim", "frames": [], "alphas": [], "delays": []}], owner=False)


def test_visitor_brightness_and_allowed_models(layout):
    c = Canvas(layout)
    c.apply([{"t": "all", "c": "#ffffff"}], owner=False, allowed_models=["Eave"], max_brightness=128)
    rgb, al = c.composite()
    eave = layout.model_index("Eave")
    for i in range(layout.count):
        if layout.model_of[i] == eave:
            assert al[i] and rgb[i * 3] == 128
        else:
            assert not al[i]


def test_validation_rejects_bad_input(layout):
    c = Canvas(layout)
    bad = [
        [{"t": "brush", "pts": [[1, 2]], "r": 3, "c": "red"}],
        [{"t": "brush", "pts": [[1, "x"]], "r": 3, "c": "#ffffff"}],
        [{"t": "brush", "pts": [[1, 1]] * 1000, "r": 3, "c": "#ffffff"}],
        [{"t": "model", "m": 999, "c": "#ffffff"}],
        [{"t": "rm -rf"}],
        [],
        "nope",
        [{"t": "all", "c": "#ffffff"}] * 100,
    ]
    for ops in bad:
        with pytest.raises(OpError):
            c.apply(ops, owner=False)


def test_owner_pixels_and_anim_layer_under_visitor(layout):
    n = layout.count
    c = Canvas(layout)
    rgb = bytes([10, 20, 30]) * n
    al = bytes([1]) * n
    c.apply([{"t": "pixels", "rgb": base64.b64encode(rgb).decode(), "alpha": base64.b64encode(al).decode()}], owner=True)
    c.apply([{"t": "model", "m": 0, "c": "#ff0000"}], owner=False)
    out, a = c.composite()
    assert all(a)
    assert tuple(out[0:3]) == (255, 0, 0)  # visitor on top
    last = n - 1
    assert tuple(out[last * 3:last * 3 + 3]) == (10, 20, 30)

    frames = [base64.b64encode(bytes([k]) * (n * 3)).decode() for k in (50, 60)]
    alphas = [base64.b64encode(bytes([1]) * n).decode()] * 2
    c.apply([{"t": "anim", "frames": frames, "alphas": alphas, "delays": [100, 100]}], owner=True)
    t0 = c.anim.start
    out1, _ = c.composite(now=t0 + 0.05)
    out2, _ = c.composite(now=t0 + 0.15)
    assert out1[last * 3] == 50 and out2[last * 3] == 60


def test_shapes(layout):
    c = Canvas(layout)
    for op in (
        {"t": "line", "a": [0, 0], "b": [800, 500], "r": 5, "c": "#ffffff"},
        {"t": "rect", "a": [200, 290], "b": [320, 390], "fill": False, "r": 4, "c": "#ffffff"},
        {"t": "ellipse", "a": [600, 150], "b": [800, 480], "fill": True, "c": "#ffffff"},
        {"t": "star", "a": [400, 300], "rad": 150, "fill": True, "c": "#ffffff"},
        {"t": "gradient", "a": [0, 0], "b": [800, 0], "c": "#ff0000", "c2": "#0000ff"},
        {"t": "erase", "pts": [[400, 300], [500, 300]], "r": 30},
        {"t": "clear"},
    ):
        c.apply([op], owner=False)
    _, al = c.composite()
    assert not any(al)


# -------------------------------------------------------------------- overlay
def test_build_frame_places_bytes_by_channel():
    lay = parse_virtualdisplaymap("# Model: 'A'\n10,10\n0,0,0,3,3,RGB\n1,0,0,9,3,RGB\n2,0,0,12,1,W\n")
    start, count = lay.channel_span()
    assert start == 3
    rgb = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9])
    frame = build_frame(lay, rgb, bytes([1, 1, 1]), start, count)
    assert list(frame[0:3]) == [1, 2, 3]
    assert list(frame[6:9]) == [4, 5, 6]
    assert frame[9] == 9  # single-channel node gets max(r,g,b)
    d = model_definition("PaintMyHouse", start, count)
    assert d["StartChannel"] == 4 and d["ChannelCount"] == count and d["Type"] == "Channel"


# ----------------------------------------------------------------------- auth
def test_rotating_code_windows():
    s = b"k" * 32
    t = 1_000_000.0
    code = auth.rotating_code(s, 300, t)
    assert len(code) == 6 and code.isdigit()
    assert auth.code_valid(s, 300, code, t)
    assert auth.code_valid(s, 300, code, t + 300)  # previous window still accepted
    assert not auth.code_valid(s, 300, code, t + 600)
    assert not auth.code_valid(b"x" * 32, 300, code, t)
    assert not auth.code_valid(s, 300, "12345", t)


def test_pin_hashing():
    h, salt = auth.hash_pin("2468")
    assert auth.pin_valid("2468", h, salt)
    assert not auth.pin_valid("2469", h, salt)
    assert "2468" not in h


def test_lockout_and_bucket():
    lo = auth.Lockout(max_fail=3, window=60, lock_for=100)
    for _ in range(3):
        lo.fail("1.2.3.4", now=1000)
    assert lo.locked_for("1.2.3.4", now=1001) > 0
    assert lo.locked_for("1.2.3.4", now=1200) == 0
    b = auth.TokenBucket(rate=1, burst=2)
    assert b.allow("a", now=0) and b.allow("a", now=0) and not b.allow("a", now=0)
    assert b.allow("a", now=1.1)


# ------------------------------------------------------------------- settings
def test_settings_validate_and_hash_pin(tmp_path):
    s = Settings(str(tmp_path))
    with pytest.raises(ValueError):
        s.update({"session_seconds": 5})
    with pytest.raises(ValueError):
        s.update({"bogus": 1})
    with pytest.raises(ValueError):
        s.update({"public_url": "javascript:alert(1)"})
    s.update({"pin": "abcd12", "pin_enabled": True})
    assert s["pin_hash"] and "abcd12" not in json.dumps(s.public())
    assert Settings(str(tmp_path))["pin_enabled"] is True
    assert oct(os.stat(tmp_path / "secret.key").st_mode & 0o777) == "0o600"


# ------------------------------------------------------------------------ app
@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "virtualdisplaymap").write_text(open(FIXTURE).read())
    return App(str(tmp_path / "data"), str(cfg), "http://127.0.0.1:9", str(tmp_path))


def test_visitor_flow(app):
    with pytest.raises(JoinError):
        app.join("10.0.0.5", "dev1", "000000", "", "x")
    s1 = app.join("10.0.0.5", "dev1", app.current_code(), "", "Ann")
    s2 = app.join("10.0.0.6", "dev2", app.current_code(), "", "Bo")
    app.tick()
    assert app.visitor_status(s1.token)["state"] == "active"
    assert app.visitor_status(s2.token)["state"] == "queued"
    with pytest.raises(JoinError):
        app.visitor_paint(s2.token, [{"t": "all", "c": "#ffffff"}])
    app.visitor_paint(s1.token, [{"t": "all", "c": "#ffffff"}])
    assert any(app.canvas.visitor.alpha)
    app.active_until = time.time() - 1  # time up
    app.tick()
    assert app.visitor_status(s1.token)["state"] == "none"
    assert app.visitor_status(s2.token)["state"] == "active"
    assert not any(app.canvas.visitor.alpha)  # cleared at turn end
    with pytest.raises(JoinError):  # cooldown
        app.join("10.0.0.5", "dev1", app.current_code(), "", "Ann")


def test_lockout_after_bad_codes(app):
    for _ in range(5):
        with pytest.raises(JoinError):
            app.join("10.0.0.9", "d", "123456" if app.current_code() != "123456" else "654321", "", "")
    with pytest.raises(JoinError) as e:
        app.join("10.0.0.9", "d", app.current_code(), "", "")
    assert e.value.status == 429


def test_regen_secret_signs_everyone_out(app):
    s = app.join("10.0.0.5", "dev1", app.current_code(), "", "Ann")
    app.tick()
    old_secret = app.settings.secret
    app.owner_action("regen_secret")
    assert app.visitor_status(s.token)["state"] == "none"
    assert app.sessions.get(s.token) is None
    assert app.settings.secret != old_secret


def test_closed_hours_and_disabled(app):
    app.settings.update({"visitor_enabled": False})
    with pytest.raises(JoinError):
        app.join("10.0.0.5", "dev1", app.current_code(), "", "Ann")


def test_looks_roundtrip(app):
    app.owner_paint([{"t": "model", "m": 2, "c": "#123456"}])
    app.save_look("Red Roof")
    app.owner_action("release")
    assert not any(app.canvas.base.alpha)
    app.load_look("Red Roof")
    assert any(app.canvas.base.alpha)
    with pytest.raises(ValueError):
        app.save_look("../../etc/passwd")
    assert app.list_looks() == ["Red Roof"]


def test_overlay_writes_shared_memory(tmp_path):
    from pmh.overlay import OverlayWriter
    lay = load_layout(FIXTURE)
    w = OverlayWriter("http://127.0.0.1:9", "PaintMyHouse", str(tmp_path), shm_dir=str(tmp_path))
    w.configure(lay)
    shm = tmp_path / "FPP-Model-Data-PaintMyHouse"
    shm.write_bytes(bytes(w.count))
    frame = bytearray(w.count)
    frame[0:3] = b"\x01\x02\x03"
    w.write(frame, True, False)  # state PUT fails (no fppd) but data lands in shm
    assert shm.read_bytes()[0:3] == b"\x01\x02\x03"
    assert w.last_error
