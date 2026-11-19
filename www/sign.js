(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var lastKey = "", ttl = 0, period = 300;

  function draw(url) {
    var qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    var n = qr.getModuleCount(), cell = Math.max(4, Math.floor(Math.min(window.innerWidth * 0.8, window.innerHeight * 0.55) / (n + 8)));
    var cv = document.createElement("canvas"), size = (n + 8) * cell;
    cv.width = cv.height = size;
    var c = cv.getContext("2d");
    c.fillStyle = "#fff"; c.fillRect(0, 0, size, size);
    c.fillStyle = "#000";
    for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) if (qr.isDark(y, x)) c.fillRect((x + 4) * cell, (y + 4) * cell, cell, cell);
    $("qr").textContent = "";
    $("qr").appendChild(cv);
  }

  function refresh() {
    fetch("/api/plugin/fpp-paint-my-house/status", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var st = s.settings, base = st.public_url || ("http://" + location.hostname + ":" + st.visitor_port);
        $("url").textContent = base.replace(/^https?:\/\//, "");
        $("closed").hidden = s.visitorsOpen;
        $("closed").textContent = s.closedReason;
        $("qr").style.visibility = s.visitorsOpen ? "visible" : "hidden";
        $("pin-line").hidden = !st.pin_enabled;
        period = st.code_period_seconds; ttl = s.codeExpiresIn;
        var url = st.code_enabled ? base + "/join?c=" + s.code : base + "/";
        $("code").textContent = st.code_enabled ? s.code : "your PIN";
        var key = url + "|" + window.innerWidth + "x" + window.innerHeight;
        if (key !== lastKey) { draw(url); lastKey = key; }
      })
      .catch(function () {});
  }
  setInterval(function () {
    ttl = Math.max(0, ttl - 1);
    $("bar").style.width = (100 * ttl / period) + "%";
    if (ttl <= 0) refresh();
  }, 1000);
  setInterval(refresh, 15000);
  window.addEventListener("resize", function () { lastKey = ""; refresh(); });
  refresh();
})();
