<?php
$pmhBase = 'plugin.php?plugin=fpp-paint-my-house&nopage=1&file=';
?>
<link rel="stylesheet" href="<?= $pmhBase ?>www/owner.css">
<div id="pmh" class="pmh">
  <div class="pmh-head">
    <h2>Paint My House</h2>
    <div class="pmh-head-right">
      <span id="pmh-service" class="pmh-badge">connecting…</span>
      <button class="buttons" id="pmh-restart" title="Restart the Paint My House service">Restart service</button>
    </div>
  </div>

  <div id="pmh-alert" class="pmh-alert" hidden></div>

  <nav class="pmh-tabs" role="tablist">
    <button class="on" data-tab="paint">Paint</button>
    <button data-tab="visitors">Visitors &amp; security</button>
    <button data-tab="settings">Settings &amp; setup</button>
  </nav>

  <!-- ============================================================ PAINT -->
  <section class="pmh-tab" id="tab-paint">
    <div class="pmh-paint">
      <div class="pmh-stage">
        <canvas id="pmh-canvas" aria-label="House layout canvas"></canvas>
        <p class="pmh-hint" id="pmh-hint"></p>
      </div>
      <aside class="pmh-side">
        <div class="pmh-group">
          <h4>Tools</h4>
          <div class="pmh-tools" id="pmh-tools">
            <button data-tool="brush" class="on">Brush</button>
            <button data-tool="erase">Erase</button>
            <button data-tool="fillmodel">Fill prop</button>
            <button data-tool="line">Line</button>
            <button data-tool="rect">Box</button>
            <button data-tool="ellipse">Circle</button>
            <button data-tool="star">Star</button>
            <button data-tool="gradient">Fade</button>
            <button data-tool="text">Text</button>
            <button data-tool="image">Picture</button>
          </div>
          <div class="pmh-row">
            <label>Color <input type="color" id="pmh-color" value="#ff2a2a"></label>
            <label id="pmh-color2-wrap" hidden>to <input type="color" id="pmh-color2" value="#2a6bff"></label>
            <label class="pmh-grow">Size <input type="range" id="pmh-size" min="2" max="80" value="14"></label>
            <label><input type="checkbox" id="pmh-fill" checked> Solid</label>
          </div>
        </div>

        <div class="pmh-group" id="pmh-text-panel" hidden>
          <h4>Text <span class="pmh-muted">(owner only)</span></h4>
          <input type="text" id="pmh-text" maxlength="200" placeholder="Merry Christmas!" class="pmh-input">
          <div class="pmh-row">
            <label>Font
              <select id="pmh-font">
                <option value="bold {s}px sans-serif">Sans bold</option>
                <option value="{s}px sans-serif">Sans</option>
                <option value="bold {s}px serif">Serif bold</option>
                <option value="bold {s}px monospace">Mono bold</option>
                <option value="italic bold {s}px cursive">Script</option>
              </select>
            </label>
            <label>Height <input type="number" id="pmh-text-size" min="4" max="2000" value="120" class="pmh-num"></label>
          </div>
          <div class="pmh-row">
            <label>Color
              <select id="pmh-text-colormode">
                <option value="solid">Solid</option>
                <option value="rainbow">Rainbow</option>
                <option value="gradient">Fade (color → to)</option>
              </select>
            </label>
            <label>Motion
              <select id="pmh-text-motion">
                <option value="static">Still</option>
                <option value="left">Scroll left</option>
                <option value="right">Scroll right</option>
                <option value="up">Scroll up</option>
              </select>
            </label>
            <label>Speed <input type="number" id="pmh-text-speed" min="10" max="2000" value="150" class="pmh-num"></label>
          </div>
          <p class="pmh-muted">Tap the house where the text should be centered (for scrolling text, tap sets the line it scrolls on).</p>
        </div>

        <div class="pmh-group" id="pmh-image-panel" hidden>
          <h4>Picture <span class="pmh-muted">(owner only)</span></h4>
          <input type="file" id="pmh-image-file" accept="image/png,image/jpeg,image/gif,image/webp">
          <div class="pmh-row">
            <label><input type="checkbox" id="pmh-image-dark" checked> Let the show through dark areas</label>
          </div>
          <div class="pmh-row">
            <label>Fit
              <select id="pmh-image-fit">
                <option value="contain">Whole picture</option>
                <option value="cover">Fill the box</option>
                <option value="stretch">Stretch</option>
              </select>
            </label>
            <button id="pmh-image-whole" disabled>Put on whole house</button>
          </div>
          <p class="pmh-muted" id="pmh-image-info">Choose a picture, then drag a box on the house (or use the whole house). Animated GIFs play as a loop where your browser supports it.</p>
        </div>

        <div class="pmh-group">
          <h4>Lights</h4>
          <div class="pmh-row">
            <button id="pmh-all">Paint everything</button>
            <button id="pmh-clear">Clear my painting</button>
          </div>
          <div class="pmh-row">
            <button id="pmh-release" class="pmh-danger">Release all to show</button>
          </div>
        </div>

        <div class="pmh-group">
          <h4>Looks</h4>
          <div class="pmh-row">
            <input type="text" id="pmh-look-name" maxlength="40" placeholder="Look name" class="pmh-input pmh-grow">
            <button id="pmh-look-save">Save</button>
          </div>
          <ul id="pmh-looks" class="pmh-list"></ul>
        </div>
      </aside>
    </div>
  </section>

  <!-- ========================================================= VISITORS -->
  <section class="pmh-tab" id="tab-visitors" hidden>
    <div class="pmh-cards">
      <div class="pmh-card">
        <h3>Visitor access</h3>
        <p id="pmh-open-state" class="pmh-state"></p>
        <div class="pmh-code" id="pmh-code-wrap">
          <div class="pmh-muted">Current code</div>
          <div id="pmh-code" class="pmh-code-digits">------</div>
          <div class="pmh-muted">changes in <span id="pmh-code-ttl">–</span></div>
        </div>
        <p class="pmh-muted">Visitor page: <a id="pmh-join-url" target="_blank" rel="noopener"></a></p>
        <div class="pmh-row">
          <a class="buttons" id="pmh-sign" target="_blank" rel="noopener">Open QR sign (for a TV / tablet)</a>
          <button id="pmh-toggle-visitors"></button>
        </div>
        <div class="pmh-row">
          <button id="pmh-regen" class="pmh-danger" title="New secret: all old codes, QR codes and visitor sessions stop working">Reset codes &amp; sign everyone out</button>
        </div>
      </div>

      <div class="pmh-card">
        <h3>Painting now</h3>
        <div id="pmh-active" class="pmh-muted">Nobody</div>
        <div class="pmh-row">
          <button id="pmh-extend">+1 minute</button>
          <button id="pmh-kick" class="pmh-danger">End their turn</button>
          <button id="pmh-clear-visitor">Clear visitor paint</button>
        </div>
        <h3>In line</h3>
        <ol id="pmh-queue" class="pmh-list"></ol>
        <button id="pmh-clear-queue">Clear the line</button>
      </div>

      <div class="pmh-card pmh-wide">
        <h3>Activity</h3>
        <ul id="pmh-events" class="pmh-list pmh-events"></ul>
      </div>
    </div>
  </section>

  <!-- ========================================================= SETTINGS -->
  <section class="pmh-tab" id="tab-settings" hidden>
    <div class="pmh-cards">
      <div class="pmh-card">
        <h3>1. House layout</h3>
        <p id="pmh-layout-info" class="pmh-muted"></p>
        <p class="pmh-muted">Comes from xLights: set up a Virtual Display / upload your layout with FPP Connect so FPP has <code>config/virtualdisplaymap</code>.</p>
        <button id="pmh-reload-layout">Reload layout</button>
      </div>
      <div class="pmh-card">
        <h3>2. Overlay model</h3>
        <p id="pmh-model-info" class="pmh-muted">Checking…</p>
        <label>Model name <input type="text" id="set-model_name" class="pmh-input" maxlength="40"></label>
        <button id="pmh-install-model">Create / update overlay model</button>
        <p class="pmh-muted">Adds one Pixel Overlay Model covering your layout's channels. FPP must restart (fppd) to load it.</p>
      </div>

      <form class="pmh-card pmh-wide" id="pmh-settings-form">
        <h3>Visitor rules</h3>
        <div class="pmh-grid">
          <label><input type="checkbox" id="set-visitor_enabled"> Visitors can paint</label>
          <label>Turn length (seconds) <input type="number" id="set-session_seconds" min="15" max="1800" class="pmh-num"></label>
          <label>Wait before painting again (s) <input type="number" id="set-cooldown_seconds" min="0" max="3600" class="pmh-num"></label>
          <label>Max people in line <input type="number" id="set-max_queue" min="1" max="500" class="pmh-num"></label>
          <label>Max visitor brightness (10–255) <input type="number" id="set-visitor_max_brightness" min="10" max="255" class="pmh-num"></label>
          <label>When a turn ends
            <select id="set-visitor_end"><option value="clear">Clear their painting</option><option value="keep">Keep it until the next person</option></select></label>
          <label>Unpainted lights
            <select id="set-background"><option value="show">Keep playing the show</option><option value="black">Turn off</option></select></label>
        </div>
        <h3>Hours</h3>
        <div class="pmh-grid">
          <label><input type="checkbox" id="set-hours_enabled"> Only during these hours</label>
          <label>From <input type="time" id="set-hours_start"></label>
          <label>Until <input type="time" id="set-hours_end"></label>
        </div>
        <h3>Security</h3>
        <div class="pmh-grid">
          <label><input type="checkbox" id="set-code_enabled"> Rotating code / QR</label>
          <label>Code changes every (s) <input type="number" id="set-code_period_seconds" min="30" max="86400" class="pmh-num"></label>
          <label><input type="checkbox" id="set-pin_enabled"> Static PIN also works</label>
          <label>New PIN <input type="password" id="pmh-pin" maxlength="32" autocomplete="new-password" placeholder="leave blank to keep" class="pmh-input"></label>
          <label><span id="pmh-pin-state" class="pmh-muted"></span> <button type="button" id="pmh-pin-clear">Remove PIN</button></label>
        </div>
        <h3>Network</h3>
        <div class="pmh-grid">
          <label>Visitor port <input type="number" id="set-visitor_port" min="1024" max="65535" class="pmh-num"></label>
          <label>Public URL for the QR (optional) <input type="text" id="set-public_url" class="pmh-input" placeholder="http://192.168.1.50:8099"></label>
          <label>Load this look at startup <select id="set-startup_look"></select></label>
        </div>
        <h3>Props visitors may paint</h3>
        <p class="pmh-muted">None ticked = all props.</p>
        <div id="pmh-models" class="pmh-models"></div>
        <div class="pmh-row">
          <button type="submit" class="buttons btn-success">Save settings</button>
          <span id="pmh-settings-msg" class="pmh-muted"></span>
        </div>
      </form>
    </div>
  </section>
</div>
<script src="<?= $pmhBase ?>www/paint.js"></script>
<script src="<?= $pmhBase ?>www/owner.js"></script>
