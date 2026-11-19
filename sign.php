<?php
// Full-screen QR sign for a TV, tablet or monitor facing the street.
// Opened from the owner page with &nopage=1, so FPP's menus are not shown.
$pmhBase = 'plugin.php?plugin=fpp-paint-my-house&nopage=1&file=';
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paint My House – Sign</title>
<link rel="stylesheet" href="<?= $pmhBase ?>www/sign.css">
</head>
<body>
<main>
  <h1>Paint our house!</h1>
  <p class="sub">Scan with your phone camera to color the lights</p>
  <div id="qr" class="qr" aria-label="QR code to join"></div>
  <p class="code-line">or open <b id="url"></b> and enter <b id="code" class="code">------</b></p>
  <p id="pin-line" class="small" hidden>Have a PIN? You can use it instead.</p>
  <p id="closed" class="closed" hidden></p>
  <div class="bar"><div id="bar"></div></div>
</main>
<script src="<?= $pmhBase ?>www/qrcode.js"></script>
<script src="<?= $pmhBase ?>www/sign.js"></script>
</body>
</html>
