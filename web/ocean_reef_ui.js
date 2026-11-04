"use strict";
/* finfolk 3-D Ocean: the Reef look's own gestures (web/ocean_reef.js draws it).
 *
 * Only while the Reef look is on, and none of it moves the camera (the scene
 * does that) or reaches the simulation:
 *   - double-tap (double-click) a fish: swim with it (the page's follow);
 *     double-tap empty water while following: let go
 *   - press and hold a fish (650 ms, longer than a tap): light up its whole
 *     family line: its relatives get a coral edge and the others dim; a chip
 *     says how many glow, × (or Esc, or holding empty water) puts it out.
 *     H, or the fish card's family button, does the same for the selected fish
 *
 * Who is family: the founder line (oc_inspect's lineage), exact. While the
 * fish wear their family colour (Appearance and Family colours) only the
 * fish of the line's colour are inspected (the colour is a hash of the line,
 * so a fish of another colour is never family; one of the same colour is
 * checked, since two lines can share a colour); with Brain colours every fish
 * is checked, a few dozen a frame. A fish's line never changes, so each is
 * looked up once (forgotten with the world).
 *
 * The page attaches it with EvoReefUI.attach(api) after its own input (so its
 * tap selection runs first); api: canvas, scene(), fresh(s), last(), epoch(),
 * live(), selectedId(), follow(), unfollow(), following(), lineOf(i),
 * familyColor(line), colourByFamily(), toast(msg), pictureHint(), coarse(),
 * reduced(). */
(function () {
  var HOLD_MS = 650, DOUBLE_MS = 350, SWEEP = 128;
  var api = null, active = false;
  var glow = null;                 /* { line, colour } while a family glows */
  var lineOfId = new Map(), epoch = -1;
  var mask = new Uint8Array(0), shown = -1, gone = false;
  var chip = null, ring = null;

  function el(id) { return document.getElementById(id); }
  function scene() { return api && api.scene(); }

  /* ---- the family glow ---- */
  function startGlowAt(idx) {
    var s = api.last();
    if (!s || idx < 0 || idx >= s.n) return false;
    var id = s.ids[idx], line = api.lineOf(idx);
    if (line === null || line === undefined) return false;
    lineOfId.set(id, line);
    glow = { line: line, colour: api.familyColor(line) };
    shown = -1; gone = false;
    paintChip(0, s.n);
    return true;
  }
  function clearGlow() {
    if (!glow) return;
    glow = null;
    if (scene() && scene().setGlow) scene().setGlow(null);
    paintChip();
  }
  function toggleGlowSelected() {
    if (glow) { clearGlow(); return; }
    if (!api.live()) { api.pictureHint(); return; }
    var s = api.last(), id = api.selectedId();
    if (!s || id === null) { api.toast("Pick a fish first, then H lights up its family."); return; }
    for (var i = 0; i < s.n; i++) if (s.ids[i] === id) { startGlowAt(i); return; }
  }
  function paintChip(count, n) {
    if (!chip) return;
    var on = !!glow && active;
    chip.hidden = !on;
    var btn = el("ifamily");
    if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
    if (!on) return;
    var t = chip.querySelector(".gt");
    t.textContent = "Family #" + glow.line + " · " + (count === undefined ? "…" : count + " of " + n + " glowing");
  }

  /* each frame (the page's loop, after the snapshot): the mask of who is
   * family, handed to the scene; returns s again (inspecting may grow the
   * memory, so the views are cut afresh) */
  function frame(s) {
    if (!active || !s) return s;
    if (api.epoch() !== epoch) { epoch = api.epoch(); lineOfId.clear(); if (glow) clearGlow(); }
    if (!glow) return s;
    var n = s.n;
    if (mask.length < n) mask = new Uint8Array(Math.max(256, n * 2));
    if (!api.live()) { scene().setGlow(mask.subarray(0, n)); return s; }   /* Turbo: the frozen picture keeps its glow */
    var byFam = api.colourByFamily(), want = glow.colour, line = glow.line;
    var ids = s.ids, cols = s.colors, pending = [], count = 0, i;
    for (i = 0; i < n; i++) {
      var L = lineOfId.get(ids[i]);
      if (L !== undefined) { mask[i] = L === line ? 1 : 0; count += mask[i]; continue; }
      mask[i] = 0;
      if (byFam && cols && ((cols[3 * i] << 16) | (cols[3 * i + 1] << 8) | cols[3 * i + 2]) !== want) continue;   /* another line's colour: never family */
      pending.push(i);
    }
    if (pending.length) {
      var take = byFam ? pending.length : Math.min(pending.length, SWEEP);
      var idsCopy = [];
      for (i = 0; i < take; i++) idsCopy.push(ids[pending[i]]);
      for (i = 0; i < take; i++) {
        var li = api.lineOf(pending[i]);
        if (li === null || li === undefined) continue;
        lineOfId.set(idsCopy[i], li);
        if (li === line) { mask[pending[i]] = 1; count++; }
      }
      s = api.fresh(s);
    }
    if (lineOfId.size > Math.max(4096, 4 * n)) lineOfId.clear();   /* the dead, forgotten */
    var settled = pending.length <= (byFam ? pending.length : SWEEP);
    if (count === 0 && settled && !gone) {
      gone = true;
      api.toast("Family #" + line + " has no one left alive.");
      clearGlow();
      return s;
    }
    scene().setGlow(mask.subarray(0, n));
    if (count !== shown) { shown = count; paintChip(count, n); }
    return s;
  }

  /* ---- gestures on the tank ---- */
  function wire() {
    var c = api.canvas, press = null, lastTap = null, timer = 0;
    function reach(e) { return e.pointerType === "mouse" ? 16 : 30; }
    function cancelHold() {
      clearTimeout(timer); timer = 0;
      if (ring) { ring.style.opacity = "0"; ring.style.transform = "translate(-50%, -50%) scale(0.4)"; }
    }
    c.addEventListener("pointerdown", function (e) {
      if (!active) return;
      if (press && press.id !== e.pointerId) { press = null; cancelHold(); return; }   /* a second finger: a pinch */
      if (!e.isPrimary || (e.pointerType === "mouse" && e.button !== 0)) return;
      press = { id: e.pointerId, x: e.clientX, y: e.clientY, t: performance.now(), held: false };
      cancelHold();
      if (ring) {
        ring.style.left = e.clientX + "px"; ring.style.top = e.clientY + "px";
        ring.style.transition = api.reduced() ? "none" : "transform " + HOLD_MS + "ms linear, opacity 120ms";
        ring.style.opacity = "1";
        ring.style.transform = "translate(-50%, -50%) scale(1)";
      }
      var px = e.clientX, py = e.clientY, r = reach(e);
      timer = setTimeout(function () {
        timer = 0;
        if (!press) return;
        press.held = true;
        if (ring) ring.style.opacity = "0";
        if (!api.live()) { api.pictureHint(); return; }
        var s = api.last(), idx = s ? scene().pick(s, px, py, r) : -1;
        if (idx >= 0) startGlowAt(idx);
        else clearGlow();
      }, HOLD_MS);
    });
    c.addEventListener("pointermove", function (e) {
      if (!press || e.pointerId !== press.id || !timer) return;
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 8) cancelHold();
    });
    c.addEventListener("pointercancel", function () { press = null; cancelHold(); });
    c.addEventListener("pointerup", function (e) {
      var p = press;
      press = null;
      cancelHold();
      if (!active || !p || e.pointerId !== p.id || p.held) return;
      var moved = Math.hypot(e.clientX - p.x, e.clientY - p.y), held = performance.now() - p.t;
      if (moved > 8 || held > 600) { lastTap = null; return; }
      var now = performance.now();
      var dbl = lastTap && now - lastTap.t < DOUBLE_MS && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) <= reach(e);
      lastTap = dbl ? null : { t: now, x: e.clientX, y: e.clientY };
      if (!dbl) return;
      /* the page's tap (it ran first) selected the fish under it */
      var s = api.last(), idx = s ? scene().pick(s, e.clientX, e.clientY, reach(e)) : -1;
      if (idx >= 0 && s.ids[idx] === api.selectedId()) { if (!api.following()) api.follow(); }
      else if (idx < 0 && api.following()) api.unfollow();
    });
  }
  function build() {
    chip = el("glowchip");
    if (chip) {
      var x = chip.querySelector("button");
      if (x) x.addEventListener("click", function () { clearGlow(); x.blur(); });
    }
    var fb = el("ifamily");
    if (fb) fb.addEventListener("click", function () { toggleGlowSelected(); fb.blur(); });
    ring = document.createElement("div");
    ring.id = "holdring";
    ring.setAttribute("aria-hidden", "true");
    document.body.appendChild(ring);
  }

  window.EvoReefUI = {
    attach: function (a) { api = a; build(); wire(); },
    setActive: function (on) {
      active = !!on;
      if (!active) clearGlow();
      paintChip();
    },
    frame: frame,
    glowing: function () { return !!glow; },
    clearGlow: clearGlow,
    toggleGlowSelected: toggleGlowSelected,
    /* for the tests: the family now glowing (its line), or null */
    glowLine: function () { return glow ? glow.line : null; }
  };
})();
