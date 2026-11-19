(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var screens = ["loading", "closed", "join", "queue", "paint", "bye"];
  var painter = null, es = null, current = "loading", wasActive = false, lastFrame = null;
  var SWATCHES = ["#ff2a2a", "#ff8a00", "#ffd400", "#2ad04b", "#00c8ff", "#2a6bff", "#9b3cff", "#ff3cc8", "#ffffff", "#ffb36b"];

  function show(name) {
    current = name;
    screens.forEach(function (s) { $("screen-" + s).hidden = s !== name; });
    document.body.classList.toggle("painting", name === "paint");
    if (name === "paint" && painter) painter.fit();
  }

  function api(path, body) {
    var o = { credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      o.method = "POST";
      o.headers["Content-Type"] = "application/json";
      o.headers["X-PMH"] = "1";
      o.body = JSON.stringify(body);
    }
    return fetch(path, o).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { j._status = r.status; return j; });
    });
  }

  function fmt(sec) {
    sec = Math.max(0, sec | 0);
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function onStatus(st) {
    if (st.state === "active") {
      wasActive = true;
      $("timer").hidden = false;
      $("timer").textContent = fmt(st.timeLeft) + " left";
      $("timer").classList.toggle("warn", st.timeLeft <= 15);
      if (current !== "paint") startPainting();
    } else if (st.state === "queued") {
      $("timer").hidden = true;
      $("queue-pos").textContent = "#" + st.position;
      $("queue-wait").textContent = st.position <= 1 ? "You're next!" : "About " + Math.ceil(st.waitSeconds / 60) + " min to go";
      if (current !== "queue") show("queue");
    } else {
      $("timer").hidden = true;
      if (es) { es.close(); es = null; }
      if (wasActive) { wasActive = false; show("bye"); } else if (current === "queue" || current === "paint") show("bye");
    }
  }

  function connect() {
    if (es) es.close();
    es = new EventSource("/api/events");
    es.addEventListener("status", function (e) { onStatus(JSON.parse(e.data)); });
    es.addEventListener("frame", function (e) {
      lastFrame = JSON.parse(e.data);
      if (painter) painter.setFrame(lastFrame);
    });
    es.onerror = function () {
      // the server closes the stream when our turn ends; check where we stand
      setTimeout(function () {
        api("/api/status").then(function (st) {
          if (st.state === "active" || st.state === "queued") connect(); else onStatus(st);
        });
      }, 1500);
      es.close(); es = null;
    };
  }

  function startPainting() {
    if (painter) { show("paint"); return; }
    api("/api/layout").then(function (L) {
      if (L._status !== 200) { show("join"); return; }
      show("paint");
      painter = PMH.createPainter($("house"), {
        layout: L,
        fitAspect: true,
        maxBrightness: L.maxBrightness,
        send: function (ops) {
          return api("/api/paint", { ops: ops }).then(function (r) {
            if (r._status === 409 || r._status === 401) onStatus({ state: "none" });
          });
        },
      });
      if (lastFrame) painter.setFrame(lastFrame);
      wireTools();
    });
  }

  function wireTools() {
    var st = painter.state;
    var sw = $("swatches");
    SWATCHES.forEach(function (c) {
      var b = document.createElement("button");
      b.style.background = c; b.title = c; b.setAttribute("aria-label", "color " + c);
      b.addEventListener("click", function () { st.color = c; $("color").value = c; mark(); });
      sw.appendChild(b);
    });
    function mark() {
      Array.prototype.forEach.call(sw.children, function (b) { b.classList.toggle("on", b.title === st.color); });
    }
    mark();
    Array.prototype.forEach.call($("tools").querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () {
        st.tool = b.dataset.tool;
        Array.prototype.forEach.call($("tools").children, function (x) { x.classList.toggle("on", x === b); });
        $("color2-wrap").hidden = st.tool !== "gradient";
      });
    });
    $("color").addEventListener("input", function (e) { st.color = e.target.value; mark(); });
    $("color2").addEventListener("input", function (e) { st.color2 = e.target.value; });
    $("size").addEventListener("input", function (e) { st.size = +e.target.value; });
    st.size = +$("size").value;
    $("fill").addEventListener("change", function (e) { st.fill = e.target.checked; });
    $("all").addEventListener("click", function () { painter.fillAll(); });
    $("clear").addEventListener("click", function () { painter.clear(); });
    $("done").addEventListener("click", leave);
  }

  function leave() {
    api("/api/leave", {}).then(function () { wasActive = false; onStatus({ state: "none" }); show("bye"); });
  }
  $("leave-q").addEventListener("click", leave);

  $("join-form").addEventListener("submit", function (e) {
    e.preventDefault();
    $("join-error").textContent = "";
    var btn = e.target.querySelector("button");
    btn.disabled = true;
    api("/api/join", { code: $("code").value.trim(), pin: $("pin").value.trim(), nick: $("nick").value.trim() })
      .then(function (r) {
        btn.disabled = false;
        if (!r.ok) { $("join-error").textContent = r.error || "Couldn't join."; return; }
        history.replaceState(null, "", "/");
        onStatus(r);
        connect();
      })
      .catch(function () { btn.disabled = false; $("join-error").textContent = "Network problem — try again."; });
  });

  function boot() {
    var q = new URLSearchParams(location.search);
    var c = q.get("c");
    if (c && /^\d{6}$/.test(c)) $("code").value = c;
    api("/api/status").then(function (st) {
      if (st.state === "active" || st.state === "queued") { onStatus(st); connect(); return; }
      if (!st.open) { $("closed-msg").textContent = st.closedReason || "Painting isn't open right now."; show("closed"); return; }
      $("code-wrap").hidden = !st.needCode;
      $("pin-wrap").hidden = !st.pinAllowed;
      if (!st.needCode) $("pin").placeholder = "PIN from the sign";
      show("join");
      // QR code already carried the code: join in one tap
      if (c && st.needCode) $("nick").focus();
    }).catch(function () { $("closed-msg").textContent = "Can't reach the lights. Are you on the right Wi-Fi?"; show("closed"); });
  }
  boot();
})();
