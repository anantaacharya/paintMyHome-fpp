/* Paint My House – shared canvas painter (visitor + owner pages).
 *
 * PMH.createPainter(canvas, opts) draws the house pixels and turns pointer
 * input into paint "ops" that are sent to the daemon. The daemon rasterizes
 * ops against the real pixel positions; we mirror that math locally so the
 * picture reacts instantly, then the server frame replaces it.
 */
(function (global) {
  "use strict";

  function b64ToBytes(s) {
    var bin = atob(s || ""), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function bytesToB64(bytes) {
    var s = "", CH = 0x8000;
    for (var i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return btoa(s);
  }
  function hexToRgb(h) {
    var m = /^#?([0-9a-f]{6})$/i.exec(h || "");
    if (!m) return [255, 255, 255];
    var v = parseInt(m[1], 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }
  function segDist2(px, py, ax, ay, bx, by) {
    var dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy;
    if (!L) return (px - ax) * (px - ax) + (py - ay) * (py - ay);
    var t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L));
    var cx = ax + t * dx, cy = ay + t * dy;
    return (px - cx) * (px - cx) + (py - cy) * (py - cy);
  }
  function starPoly(cx, cy, r) {
    var pts = [];
    for (var i = 0; i < 10; i++) {
      var rr = i % 2 ? r * 0.45 : r, a = -Math.PI / 2 + i * Math.PI / 5;
      pts.push([cx + rr * Math.cos(a), cy + rr * Math.sin(a)]);
    }
    return pts;
  }
  function inPoly(x, y, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi) inside = !inside;
    }
    return inside;
  }

  /* Hit test mirroring daemon/pmh/canvas.py so local preview matches. */
  function hitFn(op, L) {
    var xs = L.xs, ys = L.ys, t = op.t;
    if (t === "brush" || t === "erase") {
      var pts = op.pts.length === 1 ? [op.pts[0], op.pts[0]] : op.pts, r2 = op.r * op.r;
      return function (i) {
        for (var k = 0; k + 1 < pts.length; k++)
          if (segDist2(xs[i], ys[i], pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]) <= r2) return true;
        return false;
      };
    }
    if (t === "line") {
      var lr2 = op.r * op.r;
      return function (i) { return segDist2(xs[i], ys[i], op.a[0], op.a[1], op.b[0], op.b[1]) <= lr2; };
    }
    if (t === "rect" || t === "ellipse") {
      var x0 = Math.min(op.a[0], op.b[0]), x1 = Math.max(op.a[0], op.b[0]);
      var y0 = Math.min(op.a[1], op.b[1]), y1 = Math.max(op.a[1], op.b[1]), w = op.r;
      if (t === "rect") return function (i) {
        var x = xs[i], y = ys[i], inside = x >= x0 && x <= x1 && y >= y0 && y <= y1;
        if (op.fill || !inside) return inside;
        return Math.min(x - x0, x1 - x, y - y0, y1 - y) <= w;
      };
      var cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = Math.max((x1 - x0) / 2, 0.5), ry = Math.max((y1 - y0) / 2, 0.5);
      return function (i) {
        var dx = (xs[i] - cx) / rx, dy = (ys[i] - cy) / ry, d = dx * dx + dy * dy;
        if (op.fill) return d <= 1;
        var ix = Math.max(rx - w, 0.1), iy = Math.max(ry - w, 0.1);
        var di = Math.pow((xs[i] - cx) / ix, 2) + Math.pow((ys[i] - cy) / iy, 2);
        return d <= 1 && di >= 1;
      };
    }
    if (t === "star") {
      var poly = starPoly(op.a[0], op.a[1], op.rad), sw2 = op.r * op.r;
      return function (i) {
        if (op.fill) return inPoly(xs[i], ys[i], poly);
        for (var k = 0; k < poly.length; k++) {
          var a = poly[k], b = poly[(k + 1) % poly.length];
          if (segDist2(xs[i], ys[i], a[0], a[1], b[0], b[1]) <= sw2) return true;
        }
        return false;
      };
    }
    if (t === "model") return function (i) { return L.model[i] === op.m; };
    if (t === "all") return function () { return true; };
    return function () { return false; };
  }

  function createPainter(canvas, opts) {
    var L = opts.layout, n = L.count;
    var ctx = canvas.getContext("2d");
    var rgb = new Uint8Array(n * 3), alpha = new Uint8Array(n);
    var allowed = null;
    if (L.allowedModels && L.allowedModels.length) {
      var names = {};
      L.allowedModels.forEach(function (s) { names[s] = 1; });
      allowed = new Uint8Array(n);
      for (var i = 0; i < n; i++) allowed[i] = names[L.models[L.model[i]].name] ? 1 : 0;
    }
    var bright = (opts.maxBrightness || 255) / 255;
    var state = {
      tool: "brush", color: "#ff2a2a", color2: "#2a6bff", size: 12, fill: true, enabled: true,
    };
    var view = { s: 1, ox: 0, oy: 0, dpr: 1 };
    var drag = null, queue = [], flushTimer = null, preview = null, overlayDraw = null;

    function fit() {
      var r = canvas.getBoundingClientRect();
      view.dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(r.width * view.dpr));
      canvas.height = Math.max(1, Math.round(r.height * view.dpr));
      var pad = 12 * view.dpr;
      var s = Math.min((canvas.width - 2 * pad) / (L.width || 1), (canvas.height - 2 * pad) / (L.height || 1));
      view.s = s;
      view.ox = (canvas.width - L.width * s) / 2;
      view.oy = (canvas.height - L.height * s) / 2;
      draw();
    }

    function toLayout(ev) {
      var r = canvas.getBoundingClientRect();
      var x = (ev.clientX - r.left) * view.dpr, y = (ev.clientY - r.top) * view.dpr;
      return [Math.round((x - view.ox) / view.s * 10) / 10, Math.round((y - view.oy) / view.s * 10) / 10];
    }

    function nearestPixel(p) {
      var best = -1, bd = Infinity;
      for (var i = 0; i < n; i++) {
        var dx = L.xs[i] - p[0], dy = L.ys[i] - p[1], d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = i; }
      }
      return bd <= Math.pow(30 / view.s * view.dpr, 2) ? best : -1;
    }

    function draw() {
      ctx.fillStyle = "#07080c";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      var dot = Math.max(1.6 * view.dpr, Math.min(6 * view.dpr, view.s * 3.2));
      for (var i = 0; i < n; i++) {
        var x = view.ox + L.xs[i] * view.s, y = view.oy + L.ys[i] * view.s;
        if (alpha[i]) {
          var r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
          ctx.fillStyle = "rgb(" + r + "," + g + "," + b + ")";
          ctx.globalAlpha = 0.35;
          ctx.beginPath(); ctx.arc(x, y, dot * 2.2, 0, 6.2832); ctx.fill();
          ctx.globalAlpha = 1;
          ctx.beginPath(); ctx.arc(x, y, dot, 0, 6.2832); ctx.fill();
        } else {
          ctx.fillStyle = allowed && !allowed[i] ? "#1a1b22" : "#3a3d4a";
          ctx.beginPath(); ctx.arc(x, y, dot * 0.7, 0, 6.2832); ctx.fill();
        }
      }
      if (preview) drawPreview(preview);
      if (overlayDraw) overlayDraw(ctx, view);
    }

    function P(p) { return [view.ox + p[0] * view.s, view.oy + p[1] * view.s]; }
    function drawPreview(op) {
      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.setLineDash([6 * view.dpr, 4 * view.dpr]);
      ctx.lineWidth = 1.5 * view.dpr;
      ctx.beginPath();
      if (op.t === "line" || op.t === "gradient") {
        var a = P(op.a), b = P(op.b); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
      } else if (op.t === "rect") {
        var a2 = P(op.a), b2 = P(op.b); ctx.rect(a2[0], a2[1], b2[0] - a2[0], b2[1] - a2[1]);
      } else if (op.t === "ellipse") {
        var a3 = P(op.a), b3 = P(op.b);
        ctx.ellipse((a3[0] + b3[0]) / 2, (a3[1] + b3[1]) / 2, Math.abs(b3[0] - a3[0]) / 2 + 0.1, Math.abs(b3[1] - a3[1]) / 2 + 0.1, 0, 0, 6.2832);
      } else if (op.t === "star") {
        starPoly(op.a[0], op.a[1], op.rad).forEach(function (p, k) { var q = P(p); k ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); });
        ctx.closePath();
      } else if (op.t === "imagebox") {
        var a4 = P(op.a), b4 = P(op.b); ctx.rect(a4[0], a4[1], b4[0] - a4[0], b4[1] - a4[1]);
      }
      ctx.stroke();
      ctx.restore();
    }

    function localApply(op) {
      var c = hexToRgb(op.c), c2 = hexToRgb(op.c2);
      if (bright < 1) { c = c.map(function (v) { return Math.floor(v * bright); }); c2 = c2.map(function (v) { return Math.floor(v * bright); }); }
      if (op.t === "clear") { for (var i = 0; i < n; i++) if (!allowed || allowed[i]) alpha[i] = 0; return; }
      if (op.t === "gradient") {
        var dx = op.b[0] - op.a[0], dy = op.b[1] - op.a[1], LL = dx * dx + dy * dy || 1;
        for (var j = 0; j < n; j++) {
          if (allowed && !allowed[j]) continue;
          var t = Math.max(0, Math.min(1, ((L.xs[j] - op.a[0]) * dx + (L.ys[j] - op.a[1]) * dy) / LL));
          for (var k = 0; k < 3; k++) rgb[j * 3 + k] = Math.floor(c[k] + (c2[k] - c[k]) * t);
          alpha[j] = 1;
        }
        return;
      }
      var hit = hitFn(op, L);
      for (var p = 0; p < n; p++) {
        if (allowed && !allowed[p]) continue;
        if (!hit(p)) continue;
        if (op.t === "erase") { alpha[p] = 0; continue; }
        rgb[p * 3] = c[0]; rgb[p * 3 + 1] = c[1]; rgb[p * 3 + 2] = c[2]; alpha[p] = 1;
      }
    }

    function emit(op) {
      localApply(op);
      queue.push(op);
      draw();
      if (!flushTimer) flushTimer = setTimeout(flush, 70);
    }
    function flush() {
      flushTimer = null;
      if (!queue.length) return;
      var ops = queue.splice(0, 60);
      Promise.resolve(opts.send(ops)).catch(function () {});
      if (queue.length) flushTimer = setTimeout(flush, 70);
    }

    function radius() { return state.size / view.s * view.dpr / 2 + 0.5; }

    canvas.addEventListener("pointerdown", function (ev) {
      if (!state.enabled) return;
      if (opts.onPointer && opts.onPointer(state.tool, toLayout(ev), "down")) return;
      ev.preventDefault();
      canvas.setPointerCapture(ev.pointerId);
      var p = toLayout(ev), t = state.tool;
      if (t === "brush" || t === "erase") {
        drag = { t: t, last: p };
        emit({ t: t, pts: [p], r: radius(), c: state.color });
      } else if (t === "fillmodel") {
        var px = nearestPixel(p);
        if (px >= 0) emit({ t: "model", m: L.model[px], c: state.color });
      } else {
        drag = { t: t, a: p };
      }
    });
    canvas.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      ev.preventDefault();
      var p = toLayout(ev);
      if (drag.t === "brush" || drag.t === "erase") {
        var l = drag.last;
        if (Math.abs(l[0] - p[0]) + Math.abs(l[1] - p[1]) < 2 / view.s) return;
        emit({ t: drag.t, pts: [l, p], r: radius(), c: state.color });
        drag.last = p;
      } else {
        preview = shapeOp(drag.a, p);
        draw();
      }
    });
    function end(ev) {
      if (!drag) return;
      var d = drag; drag = null;
      if (d.t !== "brush" && d.t !== "erase") {
        var op = shapeOp(d.a, toLayout(ev));
        preview = null;
        if (op.t === "imagebox") { if (opts.onImageBox) opts.onImageBox(op.a, op.b); draw(); return; }
        if (op) emit(op);
      }
    }
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", function () { drag = null; preview = null; draw(); });

    function shapeOp(a, b) {
      var t = state.tool, w = Math.max(1, radius());
      if (t === "line") return { t: "line", a: a, b: b, r: w, c: state.color };
      if (t === "rect" || t === "ellipse") return { t: t, a: a, b: b, r: w, fill: state.fill, c: state.color };
      if (t === "star") {
        var rad = Math.max(2, Math.hypot(b[0] - a[0], b[1] - a[1]));
        return { t: "star", a: a, rad: rad, r: w, fill: state.fill, c: state.color };
      }
      if (t === "gradient") return { t: "gradient", a: a, b: b, c: state.color, c2: state.color2 };
      if (t === "imagebox") return { t: "imagebox", a: a, b: b };
      return { t: "line", a: a, b: b, r: w, c: state.color };
    }

    if (opts.fitAspect && L.width && L.height) {
      // size the canvas to the house so phones don't waste half the screen
      canvas.style.aspectRatio = Math.max(0.6, Math.min(3, L.width / L.height)).toFixed(3);
    }
    window.addEventListener("resize", fit);
    fit();

    return {
      state: state,
      layout: L,
      redraw: draw,
      fit: fit,
      setOverlay: function (f) { overlayDraw = f; draw(); },
      setFrame: function (fr) {
        if (drag || queue.length || flushTimer) return; // don't fight the user's stroke
        var r = b64ToBytes(fr.rgb), a = b64ToBytes(fr.alpha);
        if (r.length === rgb.length && a.length === alpha.length) { rgb.set(r); alpha.set(a); draw(); }
      },
      fillAll: function () { emit({ t: "all", c: state.color }); },
      clear: function () { emit({ t: "clear" }); },
      sendRaw: function (ops) { return opts.send(ops); },
    };
  }

  global.PMH = { createPainter: createPainter, b64ToBytes: b64ToBytes, bytesToB64: bytesToB64, hexToRgb: hexToRgb };
})(window);
