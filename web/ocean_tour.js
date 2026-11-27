// @ts-check
"use strict";
/* The Ocean tour and first-visit coach. Evaluation only registers the factory. */
(function () {
  /** @param {OceanTourPorts} p @returns {OceanTour} */
  function create(p) {
  /* ---- a first visit: the tank, then one hint (load + 9 s, a fish), then
   * this small Turbo coach mark, after a minute or once generation 1 is
   * born (25 s at the least), on a screen with nothing else open (no fish
   * card, popover, live numbers, settings, charts or tour) in a tab in view.
   * Once per visitor; not after Turbo has been used or its card seen (Help's
   * "What is Turbo?" too); ?guide=0 none (the tests). ---- */
  var COACH_KEY = "evo_boids.ocean.turboHintSeen.v1", coachTimer = 0, coachHideT = 0;
  function coachDone() { return p.store(COACH_KEY) === "1" || p.store(window.EvoGuideConfig.introKey) === "1"; }
  function startCoach() {
    if (p.P.get("guide") === "0" || p.P.has("renderBench") || coachDone()) return;
    var t0 = performance.now();
    coachTimer = setInterval(function () {
      var t = (performance.now() - t0) / 1000, gen = p.readouts.summary ? p.readouts.summary[13] : 0;
      if (coachDone()) { clearInterval(coachTimer); return; }   /* Turbo used, or its card seen, meanwhile */
      if (!(t >= 60 || (gen >= 1 && t >= 25)) || p.turboState !== "live" || p.openPop || p.statOpen || p.inspector.selectedId !== null || document.hidden ||
          document.getElementById("guide") || p.drawerEl.classList.contains("open") || (p.readouts.dash() && /** @type {{ isOpen(): boolean }} */ (p.readouts.dash()).isOpen())) return;
      clearInterval(coachTimer);
      p.store(COACH_KEY, "1");
      p.el("coach").hidden = false;
      placeCoach();
      coachHideT = setTimeout(hideCoach, 25000);
    }, 1000);
  }
  function hideCoach() { p.el("coach").hidden = true; clearTimeout(coachHideT); }
  function placeCoach() {   /* above the Turbo button, its arrow on it */
    var c = p.el("coach");
    if (c.hidden) return;
    var r = p.el("turbobtn").getBoundingClientRect(), w = c.offsetWidth, mid = r.left + r.width / 2;
    var left = Math.round(Math.max(10, Math.min(innerWidth - w - 10, mid - w / 2)));
    c.style.left = left + "px";
    c.style.setProperty("--arrow-x", Math.round(mid - left) + "px");
  }

  function installGuide() {
  /* ---------------- the tour (web/guide.js reads this) ---------------- */
  /** @type {number | null} */
  var guideFish = null;
  window.EvoGuideConfig = {
    key: "evo_boids.ocean.guideSeen.v1", introKey: "evo_boids.ocean.turboIntroSeen.v1",
    quiet: true,   /* a first visit opens on the tank: the tour and the Turbo card wait in Help */
    steps: function (h) {
      var tap = function () { return h.touch() ? "Tap" : "Click"; };
      return [
        { welcome: true, drawer: false, title: "Welcome to Finfolk",
          body: function () {
            return "Each fish has a tiny neural network wired by its genes. Fish that eat enough have children with " +
                   "slightly mutated genes. This is the 3-D Ocean, a sea with real depth: they sense up and down and " +
                   "steer in it, and each inherits the depth it floats at. Nobody programs what they do: their " +
                   "behaviour evolves.<br>Take the one-minute tour?";
          } },
        { drawer: false, title: "The tank",
          target: function () { return h.rectOf("#tank"); },
          body: function () {
            var looks = p.display.colourMode === "appearance" && p.HAS_APP
              ? "each fish wears the skin pattern and body shape it inherited from its parents"
              : p.display.colourBrain ? "a fish's colour follows its brain's wiring" : "each family has its own colour";
            return "Glowing specks are food, " + looks + ", and the dark fish with glowing eyes are " +
                   "predators. <b>View</b>, in the dock, colours them by family or brain and makes the water realistic. " +
                   (h.touch() ? "Drag to move, pinch to zoom, twist with two fingers to turn (below the horizon too)."
                              : "Drag to move, scroll to zoom, right-drag to turn (below the horizon too). Or fly: " +
                                "<kbd>W</kbd> <kbd>A</kbd> <kbd>S</kbd> <kbd>D</kbd> move where you look, <kbd>Q</kbd> " +
                                "<kbd>E</kbd> go down and up, <kbd>Shift</kbd> faster.");
          } },
        { drawer: false, title: "A fish's brain", fish: true,
          enter: function () {
            if (h.app().inspectSomeFish) h.app().inspectSomeFish();
            var b = h.q("#iexpand");
            if (b && b.getAttribute("aria-expanded") === "false") b.click();
          },
          target: function () { return h.app().inspectorRect ? h.app().inspectorRect() : null; },
          body: function () {
            return tap() + " any fish to see its energy, age, speed, depth, the depth it floats at and its pitch, and " +
                   "its brain, live: senses on one side, actions on the other (steer z is the depth one). " +
                   "<b>Follow</b> (F) keeps the camera on it, with a flashlight that shows its true colours" +
                   (h.touch() ? "." : "; then W and S come closer or back off, A and D circle it, Q and E lower or " +
                                      "raise the camera, and the follow stays on.");
          } },
        { drawer: false, title: "Live numbers",
          target: function () { return h.rectOf("#readout"); },
          body: function () {
            return "Fish, generations, their average depth and the frame rate. " + tap() + " it (or press I) for the " +
                   "rest: food, births and deaths, family lines, and where in the depth the fish are.";
          } },
        { drawer: false, title: "Two worlds",   /* a phone: the switch is in the live numbers' panel (ocean.html #worlds-alt) */
          target: function () { return h.rectOf(innerWidth < 600 ? "#readout" : "#worlds"); },
          body: function () {
            return "You are in the <b>3-D Ocean</b>. <b>2-D Classic</b>" +
                   (innerWidth < 600 ? " (tap the live numbers here; it is at the bottom)" : "") + " opens the original " +
                   "flat world on its own page; the native app runs it too. Each world runs on its own, so switching " +
                   "starts the other one fresh.";
          } },
        { desktopOnly: true, drawer: false, title: "Keyboard",
          body: function () {
            return "<kbd>W</kbd> <kbd>A</kbd> <kbd>S</kbd> <kbd>D</kbd> fly · <kbd>Space</kbd> pause · <kbd>T</kbd> " +
                   "Turbo · <kbd>F</kbd> follow · <kbd>L</kbd> flashlight · <kbd>V</kbd> view · <kbd>G</kbd> charts · " +
                   "<kbd>O</kbd> setup · <kbd>?</kbd> help, with every key. Try one now; the tour waits. " +
                   "(<kbd>Esc</kbd> closes things, and this tour.)";
          } },
        { drawer: false, title: "Playback",
          target: function () { return h.rectOf("#dock"); },
          body: function () {
            return "Pause and change speed; while paused, the step button moves one step at a time. <b>Turbo</b> " +
                   "runs this same world many times faster without drawing it, and hands it back exactly. Then the " +
                   "flashlight, <b>View</b> (how the tank looks: the light, the water, the fish colours) and the " +
                   "tank button, which fits the whole tank back on screen. Nothing here replaces your world.";
          } },
        { drawer: false, title: "Dashboards",
          target: function () { return h.rectOf("#dashbtn"); },
          body: function () {
            return "Charts of this run as it happens: population, where in the depth the fish live and the depth they " +
                   "float at, family lines, bodies, and which senses their brains use. Recorded on your device only.";
          } },
        { drawer: false, title: "Setup",
          target: function () { return h.rectOf("#menubtn"); },
          body: function () {
            return "New worlds, every rule of this one, and saving a setup or the whole world (O). Nothing in it replaces your run until you press " +
                   "<b>Start</b>, or open a saved world (<b>From a file</b>; asked first when your run has something to lose).";
          } },
        { drawer: true, tab: "run", scroll: "#scenarios", place: h.drawerSides, title: "Start from",
          target: function () { return h.rectOf("#scenarios"); },
          body: function () {
            return "Pick a world: Big tank, Living water, Hunters, Currents & patches, or <b>Surprise me</b>, which draws a " +
                   "setup from ranges that worked in experiments. The card fills the tabs with it; its <b>Start</b> starts it. " +
                   "<b>From a file</b> takes a saved setup the same way, or opens a saved world where it was saved.";
          } },
        { drawer: true, tab: "depth", scroll: "#f_kBuoy", place: h.drawerSides, title: "Your own settings",
          target: function () { return h.rectOf("#f_kBuoy"); },
          body: function () {
            return "Change anything by hand: the depth physics here, waves, light and currents under Water (E1). " +
                   (h.touch() ? "Tap" : "Hover over") + " a setting's name to see what it does. Changes wait for " +
                   "<b>Start</b>, at the bottom; settings marked <i>live</i> apply at once.";
          } },
        { last: true, drawer: false, title: "You're set",
          body: function () { return "Take this tour again any time from <b>Help</b> (?), with every key. Enjoy!"; } }
      ];
    },
    intro: function (h) {
      return { intro: true, drawer: false, title: "Turbo: evolution, fast-forwarded",
        target: function () { return h.rectOf("#turbobtn"); },
        place: ["above", "below", "left", "right"],
        body: function () {
          return "Behaviour evolves over many generations, which is slow to watch. <b>Turbo</b> runs the world " +
                 "headless, in a background thread, many times faster, and keeps going in a background tab. Stop it " +
                 "whenever you like: the world comes back exactly where Turbo got it.";
        } };
    }
  };
  window.EvoApp = {
    ready: false,
    touch: function () { return p.coarseMQ.matches; },
    compact: function () { return true; },
    has3D: function () { return true; },
    colourByBrain: function () { return p.display.colourBrain; },
    colourMode: function () { return p.display.colourMode; },
    startTurbo: function () { if (p.M && p.turboState === "live") p.enterTurbo(); },
    /* the Turbo card's tour step (web/guide.js) asks this; Classic's page has its #turbo card instead */
    turboActive: function () { return p.turboState !== "live"; },
    setDrawer: p.setDrawer,
    setSheetTab: p.setSheetTab,
    inspectSomeFish: function () {
      return p.engineCall(function () {
        var s = p.fresh(p.lastS);
        if (p.turboState !== "live" || !s || !s.n) return false;
        if (p.inspector.selectedId !== null) return true;
        var best = p.scene.pick(s, innerWidth * 0.4, innerHeight * 0.45, 4000);
        if (best < 0) best = 0;
        p.inspector.select(guideFish = s.ids[best]);
        return true;
      }, false);
    },
    releaseFish: function () {
      if (guideFish !== null && p.inspector.selectedId === guideFish) p.engineCall(function () { p.inspector.select(null); });
      guideFish = null;
    },
    inspectorRect: function () { return p.inspector.selectedId === null || p.inspector.cardEl.hidden ? null : p.inspector.cardEl.getBoundingClientRect(); }
  };

  }
  return { installGuide: installGuide, startCoach: startCoach, hideCoach: hideCoach, placeCoach: placeCoach,
    markCoachSeen: function () { p.store(COACH_KEY, "1"); } };
  }
  window.EvoOceanTour = { create: create };
})();
