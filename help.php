<div class="pmh-help" style="max-width: 860px">
<h2>Paint My House – Help</h2>

<h3>Set up (once)</h3>
<ol>
  <li><b>Get your layout onto FPP.</b> In xLights, upload your layout to this FPP (FPP Connect, or set up a Virtual Display) so FPP has <code>config/virtualdisplaymap</code>. Then open <i>Status/Control → Paint My House → Settings &amp; setup</i> and press <b>Reload layout</b>.</li>
  <li><b>Create the overlay model.</b> Press <b>Create / update overlay model</b>. It adds one Pixel Overlay Model (default name <code>PaintMyHouse</code>) that covers your layout's channels. Restart FPP when it asks.</li>
  <li><b>Choose visitor rules</b> (turn length, hours, brightness cap, which props visitors may paint) and <b>Save settings</b>.</li>
  <li><b>Put up the sign.</b> Open <i>Visitors &amp; security → Open QR sign</i> on a TV or tablet people can see, or print the visitor address and use a PIN.</li>
</ol>

<h3>Owner mode</h3>
<p>The <b>Paint</b> tab is yours: brush, eraser, fill a prop, line, box, circle, star and fade, plus two tools only you have:</p>
<ul>
  <li><b>Text</b> – type, pick a font, height and colors (solid, rainbow or fade), then tap the house to place it. Choose a scroll direction to make it move.</li>
  <li><b>Picture</b> – choose a PNG, JPEG, GIF or WebP, then drag a box on the house or press <i>Put on whole house</i>. Animated GIFs loop (in browsers with ImageDecoder, e.g. Chrome/Edge). Tick “let the show through dark areas” so black parts of the picture don't blank the lights.</li>
</ul>
<p>Save what you made as a <b>Look</b> to bring it back later or load it at startup. <b>Release all to show</b> clears everything and hands the lights back to your sequence. Visitors paint on top of your painting; clearing theirs never touches yours.</p>

<h3>Visitor mode and security</h3>
<ul>
  <li>Visitors use their phone at <code>http://&lt;this FPP&gt;:8099</code> (they need to be on a network that can reach it – e.g. guest Wi-Fi at the house). They never see FPP's own pages.</li>
  <li><b>Rotating code / QR:</b> a 6-digit code changes every few minutes (default 5). The QR sign always shows the current one, so only people who can see your house can join. The previous code keeps working for one extra period.</li>
  <li><b>Static PIN:</b> optional, for when you'd rather tell people a PIN. Stored only as a salted hash.</li>
  <li>One person paints at a time; others wait in line and watch live. Turns end automatically, and there's a wait before the same phone can join again.</li>
  <li>Five wrong codes from one address lock it out for 5 minutes; requests are rate-limited; visitors can only use the basic tools, only on the props you allow, and only up to your brightness cap.</li>
  <li><b>Reset codes &amp; sign everyone out</b> makes a new secret: old QR codes stop working at once.</li>
  <li>Owner controls run through FPP's own web server. If other people share your network, set a UI password in FPP (<i>Settings → UI</i>).</li>
  <li>The visitor page is plain HTTP on your local network. Keep it off the open internet unless you put it behind HTTPS yourself.</li>
</ul>

<h3>Troubleshooting</h3>
<ul>
  <li><b>“Service is not running”</b> – press <i>Restart service</i>, or check <code>logs/fpp-paint-my-house.log</code>.</li>
  <li><b>Painting shows on the canvas but not on the lights</b> – create the overlay model and restart FPP. If you changed your layout in xLights, press Reload layout and then Create / update overlay model again.</li>
  <li><b>Painted black does nothing</b> – with “Unpainted lights: keep playing the show”, black means “let the show through”. Choose “Turn off” to make unpainted lights dark instead.</li>
</ul>
</div>
