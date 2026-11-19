/* Paint My House – owner page (inside FPP's UI). */
(function () {
  "use strict";
  var API = "/api/plugin/fpp-paint-my-house/";
  var $ = function (id) { return document.getElementById(id); };
  var painter = null, status = null, layout = null, modelInfo = null;
  var image = null; // {frames:[{bmp, ms}], w, h}
  var settingsLoaded = false;

  function req(method, path, body) {
    var o = { method: method, headers: {}, credentials: "same-origin" };
    if (body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
    return fetch(API + path, o).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: "HTTP " + r.status }; }).then(function (j) {
        j._status = r.status; return j;
      });
    });
  }
  function alertMsg(msg, kind) {
    var a = $("pmh-alert");
    a.hidden = !msg; a.textContent = msg || ""; a.className = "pmh-alert " + (kind || "");
  }
  function el(tag, text, cls) { var e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
  function fmt(sec) { sec = Math.max(0, sec | 0); var m = Math.floor(sec / 60), s = sec % 60; return m + ":" + (s < 10 ? "0" : "") + s; }

  // ------------------------------------------------------------------ tabs
  Array.prototype.forEach.call(document.querySelectorAll(".pmh-tabs button"), function (b) {
    b.addEventListener("click", function () {
      Array.prototype.forEach.call(document.querySelectorAll(".pmh-tabs button"), function (x) { x.classList.toggle("on", x === b); });
      Array.prototype.forEach.call(document.querySelectorAll(".pmh-tab"), function (t) { t.hidden = t.id !== "tab-" + b.dataset.tab; });
      if (b.dataset.tab === "paint" && painter) painter.fit();
    });
  });

  // --------------------------------------------------------------- status
  function joinBase() {
    var s = status.settings;
    return s.public_url || ("http://" + location.hostname + ":" + s.visitor_port);
  }

  function renderStatus() {
    var s = status.settings;
    $("pmh-service").textContent = "running"; $("pmh-service").className = "pmh-badge ok";
    $("pmh-open-state").textContent = status.visitorsOpen ? "Open to visitors" : ("Closed — " + status.closedReason);
    $("pmh-open-state").className = "pmh-state " + (status.visitorsOpen ? "ok" : "off");
    $("pmh-code-wrap").hidden = !s.code_enabled;
    $("pmh-code").textContent = status.code || "------";
    $("pmh-code-ttl").textContent = fmt(status.codeExpiresIn);
    var url = joinBase() + "/";
    $("pmh-join-url").href = url; $("pmh-join-url").textContent = url;
    $("pmh-sign").href = "plugin.php?plugin=fpp-paint-my-house&page=sign.php&nopage=1";
    $("pmh-toggle-visitors").textContent = s.visitor_enabled ? "Close painting" : "Open painting";

    var act = $("pmh-active");
    act.textContent = status.active ? (status.active.nick + " (" + status.active.ip + ") — " + fmt(status.active.timeLeft) + " left") : "Nobody";
    var q = $("pmh-queue"); q.textContent = "";
    status.queue.forEach(function (v) { q.appendChild(el("li", v.nick + " (" + v.ip + ")")); });
    if (!status.queue.length) q.appendChild(el("li", "Empty", "pmh-muted"));

    var ev = $("pmh-events"); ev.textContent = "";
    status.events.slice().reverse().forEach(function (e) {
      var li = el("li"); li.appendChild(el("span", new Date(e.t * 1000).toLocaleTimeString(), "pmh-muted"));
      li.appendChild(document.createTextNode(" " + e.msg)); ev.appendChild(li);
    });

    var lay = status.layout;
    $("pmh-layout-info").textContent = lay.count
      ? lay.count + " pixels in " + lay.models + " props, channels " + lay.channelStart + "–" + (lay.channelStart + lay.channelCount - 1)
      : "No layout found yet.";
    renderLooks(status.looks);

    var problems = [];
    if (!lay.count) problems.push("No house layout found. Upload your layout from xLights (Virtual Display / FPP Connect), then press Reload layout in Settings & setup.");
    else if (modelInfo && !modelInfo.matches) problems.push("The lights can't show painting yet: create the overlay model in Settings & setup, then restart FPP.");
    if (status.overlayError) problems.push("FPP overlay: " + status.overlayError);
    alertMsg(problems.join(" "), problems.length ? "warn" : "");

    if (!settingsLoaded) fillSettings();
  }

  function poll() {
    req("GET", "status").then(function (s) {
      if (s._status !== 200) {
        $("pmh-service").textContent = "not running"; $("pmh-service").className = "pmh-badge bad";
        alertMsg(s.error || "Service not reachable.", "warn");
        return;
      }
      status = s;
      renderStatus();
      if (!layout || layout.count !== s.layout.count) loadLayout();
    }).catch(function () {}).then(function () { setTimeout(poll, 1000); });
  }
  function pollModel() {
    req("GET", "model").then(function (m) {
      modelInfo = m;
      $("pmh-model-info").textContent = m.exists
        ? (m.matches ? "Ready: channels " + m.startChannel + " + " + m.channelCount + "." : "Exists but doesn't match the layout (" + m.startChannel + " + " + m.channelCount + "). Update it.")
        : "Not created yet.";
    });
  }

  // --------------------------------------------------------------- canvas
  function loadLayout() {
    req("GET", "layout").then(function (L) {
      if (L._status !== 200) return;
      layout = L;
      if (!L.count) return;
      var c = $("pmh-canvas");
      var old = painter;
      painter = PMH.createPainter(c, {
        layout: L,
        send: function (ops) { return req("POST", "paint", { ops: ops }).then(function (r) { if (!r.ok) alertMsg(r.error, "warn"); }); },
        onPointer: onPointer,
        onImageBox: function (a, b) { placeImage(a, b); },
      });
      if (old) { painter.state.tool = old.state.tool; }
      syncToolState();
      fillModels();
    });
  }
  function pollFrame() {
    if (painter && !document.hidden && !$("tab-paint").hidden) {
      req("GET", "frame").then(function (f) { if (f._status === 200) painter.setFrame(f); }).catch(function () {}).then(function () { setTimeout(pollFrame, 350); });
    } else setTimeout(pollFrame, 700);
  }

  var currentTool = "brush";
  function syncToolState() {
    if (!painter) return;
    var st = painter.state;
    st.color = $("pmh-color").value; st.color2 = $("pmh-color2").value;
    st.size = +$("pmh-size").value; st.fill = $("pmh-fill").checked;
    st.tool = currentTool === "image" ? "imagebox" : currentTool;
    $("pmh-color2-wrap").hidden = !(currentTool === "gradient" || (currentTool === "text" && $("pmh-text-colormode").value === "gradient"));
    $("pmh-text-panel").hidden = currentTool !== "text";
    $("pmh-image-panel").hidden = currentTool !== "image";
    var hints = {
      brush: "Drag to paint.", erase: "Drag to let the show through again.", fillmodel: "Tap a prop to fill it.",
      line: "Drag to draw a line.", rect: "Drag a box.", ellipse: "Drag a circle.", star: "Drag from the center out.",
      gradient: "Drag across the house to fade from one color to the other.", text: "Type your text, then tap the house to place it.",
      image: image ? "Drag a box where the picture goes." : "Choose a picture first.",
    };
    $("pmh-hint").textContent = hints[currentTool] || "";
  }
  Array.prototype.forEach.call($("pmh-tools").querySelectorAll("button"), function (b) {
    b.addEventListener("click", function () {
      currentTool = b.dataset.tool;
      Array.prototype.forEach.call($("pmh-tools").children, function (x) { x.classList.toggle("on", x === b); });
      syncToolState();
    });
  });
  ["pmh-color", "pmh-color2", "pmh-size", "pmh-fill", "pmh-text-colormode"].forEach(function (id) {
    $(id).addEventListener("input", syncToolState); $(id).addEventListener("change", syncToolState);
  });

  function onPointer(tool, p, phase) {
    if (tool === "text" && phase === "down") { placeText(p); return true; }
    if (tool === "imagebox" && !image) { alertMsg("Choose a picture first.", "warn"); return true; }
    return false;
  }

  // ------------------------------------------------- offscreen sampling
  function work() {
    var k = Math.min(1, 1600 / Math.max(layout.width, layout.height));
    var W = Math.max(1, Math.ceil(layout.width * k)), H = Math.max(1, Math.ceil(layout.height * k));
    var cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    return { k: k, W: W, H: H, cv: cv, ctx: cv.getContext("2d", { willReadFrequently: true }) };
  }
  function sample(w, opts) {
    var n = layout.count, d = w.ctx.getImageData(0, 0, w.W, w.H).data;
    var rgb = new Uint8Array(n * 3), al = new Uint8Array(n);
    for (var i = 0; i < n; i++) {
      var x = Math.round(layout.xs[i] * w.k), y = Math.round(layout.ys[i] * w.k);
      if (x < 0 || y < 0 || x >= w.W || y >= w.H) continue;
      var o = (y * w.W + x) * 4;
      if (d[o + 3] < 110) continue;
      var r = d[o], g = d[o + 1], b = d[o + 2];
      if (opts && opts.skipDark && (0.2126 * r + 0.7152 * g + 0.0722 * b) < 28) continue;
      rgb[i * 3] = r; rgb[i * 3 + 1] = g; rgb[i * 3 + 2] = b; al[i] = 1;
    }
    return { rgb: rgb, alpha: al };
  }
  function sendPixels(s) {
    return req("POST", "paint", { ops: [{ t: "pixels", rgb: PMH.bytesToB64(s.rgb), alpha: PMH.bytesToB64(s.alpha) }] });
  }
  function sendAnim(frames, delays) {
    alertMsg("Uploading animation (" + frames.length + " frames)…", "");
    return req("POST", "paint", {
      ops: [{
        t: "anim",
        frames: frames.map(function (f) { return PMH.bytesToB64(f.rgb); }),
        alphas: frames.map(function (f) { return PMH.bytesToB64(f.alpha); }),
        delays: delays,
      }],
    }).then(function (r) { alertMsg(r.ok ? "" : r.error, r.ok ? "" : "warn"); });
  }

  // ----------------------------------------------------------------- text
  function placeText(p) {
    var text = $("pmh-text").value.trim();
    if (!text) { alertMsg("Type some text first.", "warn"); return; }
    var w = work(), k = w.k;
    var size = Math.max(4, +$("pmh-text-size").value) * k;
    var font = $("pmh-font").value.replace("{s}", Math.round(size));
    w.ctx.font = font; w.ctx.textBaseline = "middle"; w.ctx.textAlign = "center";
    var tw = w.ctx.measureText(text).width;
    var mode = $("pmh-text-colormode").value, c1 = $("pmh-color").value, c2 = $("pmh-color2").value;
    function paint(cx, cy) {
      w.ctx.clearRect(0, 0, w.W, w.H);
      w.ctx.font = font; w.ctx.textBaseline = "middle"; w.ctx.textAlign = "center";
      var fill = c1;
      if (mode !== "solid") {
        var g = w.ctx.createLinearGradient(cx - tw / 2, 0, cx + tw / 2, 0);
        if (mode === "rainbow") ["#ff0000", "#ff8800", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"].forEach(function (c, i) { g.addColorStop(i / 6, c); });
        else { g.addColorStop(0, c1); g.addColorStop(1, c2); }
        fill = g;
      }
      w.ctx.fillStyle = fill;
      w.ctx.fillText(text, cx, cy);
    }
    var motion = $("pmh-text-motion").value, cx = p[0] * k, cy = p[1] * k;
    if (motion === "static") { paint(cx, cy); sendPixels(sample(w)); return; }
    var speed = Math.max(10, +$("pmh-text-speed").value) * k; // canvas px per second
    var from, to, horiz = motion !== "up";
    if (motion === "left") { from = w.W + tw / 2; to = -tw / 2; }
    else if (motion === "right") { from = -tw / 2; to = w.W + tw / 2; }
    else { from = w.H + size; to = -size; }
    var dist = Math.abs(to - from);
    var step = Math.max(speed * 0.05, dist / 600), delay = Math.round(step / speed * 1000);
    var frames = [], delays = [];
    for (var pos = 0; pos <= dist; pos += step) {
      var v = from + (to > from ? pos : -pos);
      if (horiz) paint(v, cy); else paint(cx, v);
      frames.push(sample(w)); delays.push(Math.max(20, delay));
    }
    sendAnim(frames, delays);
  }

  // ---------------------------------------------------------------- image
  $("pmh-image-file").addEventListener("change", function (e) {
    var f = e.target.files[0];
    image = null; $("pmh-image-whole").disabled = true;
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { alertMsg("Picture is too big (max 8 MB).", "warn"); return; }
    $("pmh-image-info").textContent = "Loading…";
    decodeImage(f).then(function (img) {
      image = img;
      $("pmh-image-whole").disabled = false;
      $("pmh-image-info").textContent = img.w + "×" + img.h + (img.frames.length > 1 ? ", " + img.frames.length + " frames" : "") + ". Drag a box on the house, or use the whole house.";
      syncToolState();
    }).catch(function () { $("pmh-image-info").textContent = "Couldn't read that picture."; });
  });
  function decodeImage(file) {
    if (file.type === "image/gif" && window.ImageDecoder) {
      var dec = new ImageDecoder({ data: file.stream(), type: "image/gif" });
      return dec.tracks.ready.then(function () {
        var count = Math.min(dec.tracks.selectedTrack.frameCount, 200), frames = [];
        var chain = Promise.resolve();
        for (var i = 0; i < count; i++) (function (i) {
          chain = chain.then(function () { return dec.decode({ frameIndex: i }); }).then(function (r) {
            return createImageBitmap(r.image).then(function (bmp) {
              frames.push({ bmp: bmp, ms: Math.max(20, Math.round((r.image.duration || 100000) / 1000)) });
              r.image.close();
            });
          });
        })(i);
        return chain.then(function () { return { frames: frames, w: frames[0].bmp.width, h: frames[0].bmp.height }; });
      });
    }
    return createImageBitmap(file).then(function (bmp) { return { frames: [{ bmp: bmp, ms: 1000 }], w: bmp.width, h: bmp.height }; });
  }
  function placeImage(a, b) {
    if (!image || !layout) return;
    var w = work(), k = w.k;
    var x0 = Math.min(a[0], b[0]) * k, y0 = Math.min(a[1], b[1]) * k;
    var bw = Math.abs(b[0] - a[0]) * k, bh = Math.abs(b[1] - a[1]) * k;
    if (bw < 2 || bh < 2) return;
    var fit = $("pmh-image-fit").value, skipDark = $("pmh-image-dark").checked;
    var dx = x0, dy = y0, dw = bw, dh = bh;
    if (fit !== "stretch") {
      var s = fit === "contain" ? Math.min(bw / image.w, bh / image.h) : Math.max(bw / image.w, bh / image.h);
      dw = image.w * s; dh = image.h * s; dx = x0 + (bw - dw) / 2; dy = y0 + (bh - dh) / 2;
    }
    var frames = image.frames.map(function (f) {
      w.ctx.clearRect(0, 0, w.W, w.H);
      w.ctx.save(); w.ctx.beginPath(); w.ctx.rect(x0, y0, bw, bh); w.ctx.clip();
      w.ctx.drawImage(f.bmp, dx, dy, dw, dh); w.ctx.restore();
      return sample(w, { skipDark: skipDark });
    });
    if (frames.length === 1) sendPixels(frames[0]);
    else sendAnim(frames, image.frames.map(function (f) { return f.ms; }));
  }
  $("pmh-image-whole").addEventListener("click", function () { placeImage([0, 0], [layout.width, layout.height]); });

  // --------------------------------------------------------------- buttons
  function action(name, confirmMsg) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    req("POST", "action", { action: name }).then(function (r) {
      if (!r.ok) alertMsg(r.error, "warn");
      else if (r.restartRequired) alertMsg("Overlay model saved. Restart FPP (fppd) to load it — FPP shows a Restart button at the top of the page.", "");
      pollModel();
    });
  }
  $("pmh-all").addEventListener("click", function () { painter && painter.fillAll(); });
  $("pmh-clear").addEventListener("click", function () { painter && painter.clear(); });
  $("pmh-release").addEventListener("click", function () { action("release", "Clear all painting (yours and the visitor's) and give the lights back to the show?"); });
  $("pmh-kick").addEventListener("click", function () { action("kick"); });
  $("pmh-extend").addEventListener("click", function () { action("extend"); });
  $("pmh-clear-visitor").addEventListener("click", function () { action("clear_visitor"); });
  $("pmh-clear-queue").addEventListener("click", function () { action("clear_queue", "Remove everyone waiting in line?"); });
  $("pmh-regen").addEventListener("click", function () { action("regen_secret", "Make new codes? Printed/old QR codes stop working and everyone is signed out."); });
  $("pmh-reload-layout").addEventListener("click", function () { action("reload_layout"); layout = null; });
  $("pmh-install-model").addEventListener("click", function () {
    var name = $("set-model_name").value.trim();
    var p = name && status && name !== status.settings.model_name
      ? req("PUT", "settings", { model_name: name }).then(function () { alertMsg("Model name changed: press Restart service, then create the model again.", "warn"); return false; })
      : Promise.resolve(true);
    p.then(function (go) { if (go) action("install_model", "Add the overlay model to FPP's Pixel Overlay Models? FPP will need a restart."); });
  });
  $("pmh-toggle-visitors").addEventListener("click", function () {
    req("PUT", "settings", { visitor_enabled: !status.settings.visitor_enabled }).then(function () { settingsLoaded = false; });
  });
  $("pmh-restart").addEventListener("click", function () {
    req("POST", "service/restart").then(function () { alertMsg("Restarting service…", ""); setTimeout(function () { settingsLoaded = false; layout = null; pollModel(); }, 2500); });
  });

  // ---------------------------------------------------------------- looks
  function renderLooks(looks) {
    var ul = $("pmh-looks"), key = looks.join("|");
    if (ul.dataset.key === key) return;
    ul.dataset.key = key; ul.textContent = "";
    var sel = $("set-startup_look"), cur = status.settings.startup_look;
    sel.textContent = ""; sel.appendChild(new Option("(none)", ""));
    looks.forEach(function (name) {
      var li = el("li"); li.appendChild(el("span", name, "pmh-grow"));
      var load = el("button", "Load"), del = el("button", "Delete", "pmh-danger");
      load.addEventListener("click", function () { req("POST", "looks/load", { name: name }).then(function (r) { if (!r.ok) alertMsg(r.error, "warn"); }); });
      del.addEventListener("click", function () { if (confirm("Delete look '" + name + "'?")) req("POST", "looks/delete", { name: name }); });
      li.appendChild(load); li.appendChild(del); ul.appendChild(li);
      sel.appendChild(new Option(name, name, false, name === cur));
    });
    if (!looks.length) ul.appendChild(el("li", "No saved looks yet.", "pmh-muted"));
  }
  $("pmh-look-save").addEventListener("click", function () {
    var name = $("pmh-look-name").value.trim();
    if (!name) return;
    req("POST", "looks/save", { name: name }).then(function (r) { if (!r.ok) alertMsg(r.error, "warn"); else $("pmh-look-name").value = ""; });
  });

  // -------------------------------------------------------------- settings
  var FIELDS = {
    visitor_enabled: "bool", session_seconds: "int", cooldown_seconds: "int", max_queue: "int",
    visitor_max_brightness: "int", visitor_end: "str", background: "str", hours_enabled: "bool",
    hours_start: "str", hours_end: "str", code_enabled: "bool", code_period_seconds: "int",
    pin_enabled: "bool", visitor_port: "int", public_url: "str", startup_look: "str",
  };
  function fillSettings() {
    var s = status.settings;
    Object.keys(FIELDS).forEach(function (k) {
      var e = $("set-" + k); if (!e) return;
      if (FIELDS[k] === "bool") e.checked = !!s[k]; else e.value = s[k];
    });
    $("set-model_name").value = s.model_name;
    $("pmh-pin-state").textContent = s.pin_set ? "A PIN is set." : "No PIN set.";
    settingsLoaded = true;
    fillModels();
  }
  function fillModels() {
    if (!layout || !status) return;
    var box = $("pmh-models"), allowed = {};
    (status.settings.allowed_models || []).forEach(function (m) { allowed[m] = 1; });
    box.textContent = "";
    layout.models.forEach(function (m) {
      var lab = el("label"), cb = el("input");
      cb.type = "checkbox"; cb.value = m.name; cb.checked = !!allowed[m.name];
      lab.appendChild(cb); lab.appendChild(document.createTextNode(" " + m.name + " (" + m.count + ")"));
      box.appendChild(lab);
    });
  }
  $("pmh-settings-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var ch = {};
    Object.keys(FIELDS).forEach(function (k) {
      var el2 = $("set-" + k); if (!el2) return;
      ch[k] = FIELDS[k] === "bool" ? el2.checked : FIELDS[k] === "int" ? parseInt(el2.value, 10) : el2.value;
    });
    ch.allowed_models = Array.prototype.filter.call($("pmh-models").querySelectorAll("input"), function (c) { return c.checked; }).map(function (c) { return c.value; });
    var pin = $("pmh-pin").value.trim();
    if (pin) ch.pin = pin;
    if (ch.pin_enabled && !pin && !status.settings.pin_set) { $("pmh-settings-msg").textContent = "Enter a PIN to turn on PIN access."; return; }
    req("PUT", "settings", ch).then(function (r) {
      if (!r.ok) {
        var msg = r.error; try { var errs = JSON.parse(r.error); msg = Object.keys(errs).map(function (k) { return k + ": " + errs[k]; }).join("; "); } catch (x) {}
        $("pmh-settings-msg").textContent = "Not saved — " + msg; return;
      }
      $("pmh-pin").value = "";
      $("pmh-settings-msg").textContent = r.restartDaemon && r.restartDaemon.length ? "Saved. Press Restart service to apply the new port." : "Saved.";
      settingsLoaded = false;
    });
  });
  $("pmh-pin-clear").addEventListener("click", function () {
    req("PUT", "settings", { pin: "", pin_enabled: false }).then(function () { settingsLoaded = false; });
  });

  poll(); pollModel(); pollFrame();
})();
