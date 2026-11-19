# Paint My House (FPP 10+ plugin)

Paint your xLights layout live from a canvas, and let visitors at your house take timed turns painting the lights from their phones.

- **Owner mode** (inside FPP's UI): brush, eraser, fill-a-prop, line, box, circle, star, fade, plus **text** (still or scrolling, solid/rainbow/fade) and **pictures** (PNG/JPEG/WebP, animated GIF). Save and load *looks*, choose a look to load at startup, and release the lights back to the show.
- **Visitor mode** (a phone page on port 8099): the same painting tools except text and pictures. Visitors get in through a **rotating code/QR sign** and/or a **static PIN**, wait in a queue, paint for a set time, and the show takes over again when their turn ends.

Painted pixels go to FPP through a **Pixel Overlay Model** in *TransparentRGB* mode, so anything that isn't painted keeps playing your sequence.

## How it works

```
 phones ──► :8099  visitor server ─┐                       ┌─► PUT /api/overlays/model/PaintMyHouse/state
                                   ├─ pmh daemon (Python) ─┤
 FPP UI ─► /api/plugin/…/ (api.php)│  127.0.0.1:8098 admin  └─► /dev/shm/FPP-Model-Data-PaintMyHouse (or PUT …/data)
           proxies with admin token┘
```

* `daemon/` – Python 3, standard library only. `layout.py` reads `config/virtualdisplaymap` (written by xLights); `canvas.py` rasterizes shapes by hit-testing each real pixel position; `overlay.py` maps pixels to channels and writes the overlay model; `app.py` holds the queue, timers and looks; `server.py` is the visitor and admin HTTP layer.
* The overlay model is of type *Channel*, one horizontal string, 3 channels per node, spanning the layout's lowest to highest channel. For that shape FPP's channel map is the identity, so each layout pixel is written at `channel − StartChannel`, whatever the prop's wiring.
* `api.php` adds the owner routes under `/api/plugin/fpp-paint-my-house/` and forwards them to the daemon's admin port, which only listens on 127.0.0.1 and also checks a token kept in `plugindata/fpp-paint-my-house/admin.token`.

## Security model

| Threat | Mitigation |
|---|---|
| Someone off-site joins | Rotating 6-digit HMAC code (current + previous window), shown on the QR sign; optional PBKDF2-hashed PIN; owner can reset the secret, which signs everyone out |
| Code guessing | 5 failures → 5-minute lockout per IP; join attempts rate-limited per IP; 1-in-a-million guess odds per try |
| Visitor reaching FPP | Visitor server is a separate process and port with only visitor routes; never proxies to FPP; strict CSP, no framing |
| Cross-site requests | `SameSite=Strict` HttpOnly session cookie, required `X-PMH: 1` header, JSON-only bodies, `Origin` check |
| Abuse while painting | Server-side validation of every op; visitors can't send text/picture/bulk ops; allowed-props mask and brightness cap applied on the server; ops/body/point-count limits; per-session paint rate limit |
| Hogging | One painter at a time, timed turns, queue limit, per-device cooldown, show hours, owner kick/clear/close |

Owner routes live on FPP's web server and are protected the same way FPP's UI is — set an FPP UI password if your network is shared. The visitor page is plain HTTP for the local network.

## Install

In FPP: *Content Setup → Plugin Manager*, paste the URL of this repo's `pluginInfo.json` (after you push it to GitHub and replace `OWNER` in `pluginInfo.json`). Then follow *Help → Paint My House – Help*.

## Develop and test

```bash
python3 -m pytest tests/
```

Run against a fake FPP (no hardware needed):

```bash
python3 tests/dev_server.py
```

That starts a mock fppd, the daemon with the sample layout in `tests/fixtures/`, and an owner-page harness at http://127.0.0.1:8090/ (visitor page at http://127.0.0.1:8099/).
