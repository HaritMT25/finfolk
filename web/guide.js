"use strict";
/* evo_boids first-visit guide: a short spotlight tour of the page.
 *
 * A first visit starts with a single card that points at Turbo and says what
 * it does (Cancel / Try Turbo); after Cancel the tour offers itself (renderer.js
 * fires "evo:ready" once the world runs). "Tour" in the settings replays the
 * tour. ?guide=0 keeps both from starting on their own (tests), ?guide=1 always
 * starts the tour, ?intro=1 always shows the Turbo card. "Seen" lives in
 * localStorage; where that is unavailable the guide simply offers itself again
 * next visit. The shade takes no clicks, so the simulation keeps running and
 * every control still works mid-tour (the keyboard step invites trying them).
 * Page hooks it uses: window.EvoApp (renderer.js). */
(function () {
  /* Another page can bring its own tour: window.EvoGuideConfig = {key,
   * introKey, steps(h), intro(h), quiet} set before this file runs
   * (web/ocean.js, the 3-D Ocean), where h holds the helpers below. Classic
   * sets none. quiet: a first visit starts neither the Turbo card nor the
   * tour (the page opens them from its Help: EvoGuide.start(),
   * EvoGuide.turbo()), and the Turbo card's Cancel doesn't offer the tour;
   * ?guide=1 and ?intro=1 still start them. */
  var CFG = window.EvoGuideConfig || null;
  var QUIET = !!(CFG && CFG.quiet);
  var KEY = (CFG && CFG.key) || "evo_boids.guideSeen.v2";
  function app() { return window.EvoApp || {}; }
  function q(sel) { return document.querySelector(sel); }
  function rectOf(sel) { var e = q(sel); return e && !e.hidden ? e.getBoundingClientRect() : null; }
  function touch() { return !!(app().touch && app().touch()); }
  /* the tank view (renderer.js, opt-in) is showing */
  function tank() { return !!(app().has3D && app().has3D()); }
  /* compact screens and the tank view show the selected fish as a card instead of the canvas panel */
  function compact() { return !!(app().compact && app().compact()); }
  function seen() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } }
  function markSeen() { try { localStorage.setItem(KEY, "1"); } catch (e) { /* private mode */ } }
  var INTRO_KEY = (CFG && CFG.introKey) || "evo_boids.turboIntroSeen.v1";
  function introSeen() { try { return localStorage.getItem(INTRO_KEY) === "1"; } catch (e) { return false; } }
  function markIntroSeen() { try { localStorage.setItem(INTRO_KEY, "1"); } catch (e) { /* private mode */ } }
  function wide() { return window.matchMedia("(min-width: 960px)").matches; }

  /* One step: title, body() (trusted HTML), target() -> box or null (centred
   * card), drawer (open/close the settings on entry), tab (which settings tab),
   * scroll (bring into view in the settings), place (card sides to try, in
   * order), enter() (side effects). */
  function drawerSides() { return wide() ? ["left", "below", "above"] : ["above", "below"]; }
  var H = { app: app, q: q, rectOf: rectOf, touch: touch, tank: tank, compact: compact, wide: wide, drawerSides: drawerSides };
  var STEPS = CFG && CFG.steps ? CFG.steps(H) : [
    { welcome: true, drawer: false, title: "Welcome to Finfolk",
      body: function () {
        return "Each fish has a tiny neural network wired by its genes. Fish that eat enough " +
               "have children with slightly mutated genes. Nobody programs what they do: " +
               "their behaviour evolves.<br>Take the one-minute tour?";
      } },
    { drawer: false, title: function () { return tank() ? "The tank" : "The ocean"; },
      target: function () { return rectOf(tank() ? "#scene3d" : "#canvas"); },
      body: function () {
        var brain = app().colourByBrain && app().colourByBrain();
        if (tank()) {
          return "This is the tank view: this flat world drawn as a tank in perspective, for looks. Glowing specks are " +
                 "food, " + (brain ? "colour follows the brain's wiring" : "each family has its own colour") +
                 ", and the dark fish with glowing eyes are predators. " +
                 (touch() ? "Drag to look around, pinch to zoom, twist with two fingers to turn. "
                          : "Drag to look around, scroll to zoom, right-drag to tilt and turn. ") +
                 "The flat view, in the settings, shows the world as the simulation sees it.";
        }
        return "Green dots are food. Fish that find enough of it have children. " +
               (brain ? "Colour follows the brain's wiring, so look-alikes think alike. "
                      : "Each family (every fish descended from one starting fish) has its own colour; " +
                        "the Run settings can colour by brain instead. ") +
               "Red dots, when there are any, are " +
               "predators: bright while they hunt, dim while they digest.";
      } },
    { drawer: false, title: "A fish's brain", fish: true,
      enter: function () {
        if (app().inspectSomeFish) app().inspectSomeFish();
        var b = q("#iexpand");
        if (compact() && b && b.getAttribute("aria-expanded") === "false") b.click();
      },
      target: function () { return app().inspectorRect ? app().inspectorRect() : null; },
      body: function () {
        if (compact()) {
          var tap = touch() ? "Tap" : "Click";
          return tap + " any fish to see its energy, age and speed, and its brain, live: senses on " +
                 "one side, actions on the other. Lime links excite, orange ones inhibit; " +
                 "brighter means stronger right now. " + tap + " ✕ or empty water to let it go.";
        }
        return (touch() ? "Tap" : "Click") + " any fish to see its brain, live: senses on the " +
               "left, hidden neurons in the middle, actions on the right. Green links excite, " +
               "red ones inhibit; brighter means stronger right now. " +
               (touch() ? "Tap" : "Click") + " empty water to close it.";
      } },
    { drawer: false, title: "Live numbers",
      target: function () { return rectOf("#readout"); },
      body: function () {
        return "Fish, generations and frame rate. <b>gen</b> is the longest family line alive. " +
               (touch() ? "Tap" : "Click") + " it for the rest: food, births, deaths, and the " +
               "average generation, which climbs as evolution runs.";
      } },
    { drawer: false, title: "Two worlds",
      target: function () { return rectOf("#worlds"); },
      body: function () {
        return "You are in <b>2-D Classic</b>, the original flat world that the native app runs; the tank and " +
               "the flat view in the settings are two pictures of it. <b>3-D</b> opens the Ocean, where the fish " +
               "sense depth and steer in it. Each world runs on its own, so switching starts the other one fresh.";
      } },
    { desktopOnly: true, drawer: false, title: "Keyboard",
      body: function () {
        return "<kbd>Space</kbd> pause · <kbd>↑</kbd> <kbd>↓</kbd> speed · <kbd>R</kbd> a fresh " +
               "world" + (tank() ? " · <kbd>F</kbd> follow the selected fish · <kbd>C</kbd> fit the view" : "") +
               ". Try one now; the tour waits. (<kbd>Esc</kbd> closes things, and this tour.)";
      } },
    { drawer: false, title: "Playback",
      target: function () { return rectOf("#dock"); },
      body: function () {
        return "Pause and change speed. <b>Turbo</b> runs the simulation headless in a background " +
               "thread, many times faster; stop it to see how far evolution got. The dice draws a " +
               "new world" + (tank() ? ", and the corners fit the whole tank back on screen." : ".");
      } },
    { drawer: false, title: "Dashboards",
      target: function () { return rectOf("#dashbtn"); },
      body: function () {
        return "Charts of this run as it happens: population booms and crashes, family lines and a " +
               "family tree, how alike the fish are, and which senses their brains use. Each chart " +
               "says what to look for. Recorded on your device only.";
      } },
    { drawer: false, title: "Settings",
      target: function () { return rectOf("#menubtn"); },
      body: function () { return "Everything else lives behind this button."; } },
    { drawer: true, tab: "run", scroll: ".run-hero", place: drawerSides, title: "Randomize",
      target: function () { return rectOf(".run-hero"); },
      body: function () {
        return "The quickest way to explore. It draws a setup from ranges that worked in " +
               "experiments (predators, ocean currents, schooling rules), restarts, and lists " +
               "what it picked.";
      } },
    { drawer: true, tab: "world", scroll: "#f_population", place: drawerSides, title: "Your own settings",
      target: function () { return rectOf("#f_population"); },
      body: function () {
        return "Change anything by hand. " + (touch() ? "Tap" : "Hover over") + " a setting's " +
               "name to see what it does and good values to try. Changes apply on " +
               "<b>Restart</b>; settings marked <i>live</i> apply at once. A dot on a tab means " +
               "something in it differs from the default.";
      } },
    { drawer: true, tab: "run", scroll: ".row2", place: drawerSides, title: "Save & load",
      target: function () { return rectOf(".row2"); },
      body: function () {
        return "Save the whole world to a file and load it later; it carries on exactly where " +
               "it stopped.";
      } },
    { last: true, drawer: false, title: "You're set",
      body: function () { return "Replay this tour any time with <b>Tour</b> in the settings. Enjoy!"; } }
  ];

  /* The first-visit Turbo card: one step, its own buttons (show()). */
  var INTRO = CFG && CFG.intro ? CFG.intro(H) : { intro: true, drawer: false, title: "Turbo: evolution, fast-forwarded",
    target: function () { return rectOf("#turbobtn"); },
    place: ["above", "below", "left", "right"],
    body: function () {
      return "Behaviour evolves over many generations, which is slow to watch. <b>Turbo</b> runs the " +
             "simulation headless, in a background thread, many times faster, and it keeps going " +
             "in a background tab. Stop it whenever you like to see how far evolution got.";
    } };

  var root = null, spot = null, card = null;
  var steps = [], idx = -1, timer = 0, lastKey = "";
  function drawerOpen() { var d = q("#drawer"); return !!d && d.classList.contains("open"); }
  /* the fish the brain step selected goes back once that step is over */
  function releaseFish() { if (app().releaseFish) app().releaseFish(); }

  function build() {
    root = document.createElement("div");
    root.id = "guide";
    spot = document.createElement("div");
    spot.className = "spot none";
    card = document.createElement("div");
    card.className = "card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-live", "polite");
    root.appendChild(spot);
    root.appendChild(card);
  }
  function button(text, cls, fn) {
    var b = document.createElement("button");
    b.className = cls;
    b.textContent = text;
    /* blur: Space must keep pausing the simulation, not press this again */
    b.addEventListener("click", function () { fn(); b.blur(); });
    return b;
  }

  function show(i) {
    idx = i;
    var s = steps[i];
    if (!s.fish) releaseFish();
    if (s.drawer !== undefined && app().setDrawer) app().setDrawer(s.drawer);
    if (s.tab && app().setSheetTab) app().setSheetTab(s.tab);
    if (s.enter) s.enter();
    if (s.scroll) { var t = q(s.scroll); if (t) t.scrollIntoView({ block: "nearest" }); }
    card.innerHTML = "<h2></h2><p></p><div class='nav'></div>";
    card.querySelector("h2").textContent = typeof s.title === "function" ? s.title() : s.title;
    card.querySelector("p").innerHTML = s.body();
    var nav = card.querySelector(".nav");
    if (s.intro) {
      var gap = document.createElement("span");
      gap.className = "count";
      nav.appendChild(gap);
      nav.appendChild(button("Cancel", "skip", function () { endIntro(false); }));
      nav.appendChild(button("Try Turbo", "next", function () { endIntro(true); }));
    } else if (s.welcome) {
      var none = document.createElement("span");
      none.className = "count";
      nav.appendChild(none);
      nav.appendChild(button("Not now", "skip", finish));
      nav.appendChild(button("Show me around", "next", function () { show(i + 1); }));
    } else {
      var count = document.createElement("span");
      count.className = "count";
      count.textContent = i + " / " + (steps.length - 1);
      nav.appendChild(count);
      if (!s.last) nav.appendChild(button("Skip", "skip", finish));
      if (i > 1) nav.appendChild(button("Back", "back", function () { show(i - 1); }));
      nav.appendChild(button(s.last ? "Done" : "Next", "next", s.last ? finish : function () { show(i + 1); }));
    }
    lastKey = "";
    tick();
  }

  /* Re-measured ten times a second: targets move (the settings slide in, the
   * fish card appears or changes side, panels resize). A timer, not
   * requestAnimationFrame, so the reads land on a settled layout instead of
   * right after the simulation's per-frame DOM writes. */
  function tick() {
    var s = steps[idx];
    /* Turbo started some other way (its own button): the card has done its job */
    if (s.intro) {
      var tb = q("#turbo"), on = app().turboActive ? app().turboActive() : !!tb && !tb.hidden;   /* the Ocean asks its page; Classic shows #turbo */
      if (on) { endIntro(false, true); return; }
    }
    /* a settings step whose settings got closed: nothing to point at until they reopen */
    var r = s.target && !(s.drawer && !drawerOpen()) ? s.target() : null;
    if (r && !(r.width > 0 && r.height > 0)) r = null;
    var key = idx + "|" + innerWidth + "x" + innerHeight + "|" +
              (r ? [r.left, r.top, r.width, r.height].map(Math.round).join() : "none") +
              "|" + card.offsetWidth + "x" + card.offsetHeight;
    if (key === lastKey) return;
    lastKey = key;
    var sides = typeof s.place === "function" ? s.place() : (s.place || ["below", "above", "right", "left"]);
    place(r, sides);
  }
  function place(r, sides) {
    var pad = 6, gap = pad + 10, m = 12;
    var vw = innerWidth, vh = innerHeight, cw = card.offsetWidth, ch = card.offsetHeight;
    var x = (vw - cw) / 2, y = (vh - ch) / 2;
    if (r) {
      spot.className = "spot";
      spot.style.transform = "translate(" + Math.round(r.left - pad) + "px," + Math.round(r.top - pad) + "px)";
      spot.style.width = (r.width + 2 * pad) + "px";
      spot.style.height = (r.height + 2 * pad) + "px";
      var bottom = r.top + r.height, right = r.left + r.width;
      var cx = Math.max(m, Math.min(vw - cw - m, r.left + r.width / 2 - cw / 2));
      var cy = Math.max(m, Math.min(vh - ch - m, r.top + r.height / 2 - ch / 2));
      var at = {
        below: [cx, bottom + gap, bottom + gap + ch <= vh - m],
        above: [cx, r.top - gap - ch, r.top - gap - ch >= m],
        right: [right + gap, cy, right + gap + cw <= vw - m],
        left: [r.left - gap - cw, cy, r.left - gap - cw >= m]
      };
      for (var k = 0; k < sides.length; k++) {
        var a = at[sides[k]];
        if (a[2]) { x = a[0]; y = a[1]; break; }
      }
      /* nowhere beside it (a big target, such as the whole ocean): centred */
    } else {
      spot.className = "spot none";
      spot.style.transform = "translate(" + Math.round(vw / 2) + "px," + Math.round(vh / 2) + "px)";
      spot.style.width = "0px";
      spot.style.height = "0px";
    }
    card.style.left = Math.round(x) + "px";
    card.style.top = Math.round(y) + "px";
  }

  function finish() {
    markSeen();
    clearInterval(timer);
    releaseFish();
    if (root && root.parentNode) root.parentNode.removeChild(root);
    idx = -1;
    if (app().setDrawer) app().setDrawer(false);
  }
  /* replay: straight to the first real step; first visit: the welcome card */
  function start(replay) {
    if (idx >= 0) return;
    if (!root) build();
    document.body.appendChild(root);
    steps = STEPS.filter(function (s) { return !(s.desktopOnly && touch()); });
    show(replay ? 1 : 0);
    timer = setInterval(tick, 100);
  }
  function startIntro() {
    if (idx >= 0) return;
    if (!root) build();
    document.body.appendChild(root);
    steps = [INTRO];
    show(0);
    timer = setInterval(tick, 100);
  }
  /* tryIt: start Turbo; otherwise (Cancel) the tour offers itself next, as on
   * any first visit, unless it has been seen */
  function endIntro(tryIt, quiet) {
    markIntroSeen();
    clearInterval(timer);
    if (root && root.parentNode) root.parentNode.removeChild(root);
    idx = -1;
    if (tryIt) { if (app().startTurbo) app().startTurbo(); }
    else if (!quiet && !QUIET && !seen()) start(false);
  }
  window.addEventListener("keydown", function (e) {
    if (idx < 0) return;
    if (steps[idx] && steps[idx].intro) { if (e.key === "Escape") endIntro(false, true); return; }
    /* Esc ends the tour from anywhere, a settings field too (the tour is the
     * top layer: the pages and the charts leave this Esc to it). The arrows
     * page the tour unless a control has them: a field, a tab (the settings'
     * and the charts' tabs move with them), or any handler that took the key */
    if (e.key === "Escape") { finish(); return; }
    if (e.defaultPrevented) return;
    var tg = e.target, t = tg && tg.tagName;
    if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || (tg && tg.isContentEditable)) return;
    if (tg && tg.getAttribute && tg.getAttribute("role") === "tab") return;
    if (e.key === "ArrowRight" && !steps[idx].welcome && !steps[idx].last) show(idx + 1);
    else if (e.key === "ArrowLeft" && idx > 1) show(idx - 1);
  });

  window.EvoGuide = { start: function () { start(true); }, turbo: function () { startIntro(); } };
  /* renderer.js never fires evo:ready under ?bench, so no tour there */
  function auto() {
    var p = new URLSearchParams(location.search), g = p.get("guide");
    if (p.get("intro") === "1") { startIntro(); return; }
    if (g === "0") return;
    if (g === "1") { start(false); return; }
    if (QUIET) return;
    if (!introSeen()) startIntro();
    else if (!seen()) start(false);
  }
  if (app().ready) auto();
  else window.addEventListener("evo:ready", auto, { once: true });
})();
