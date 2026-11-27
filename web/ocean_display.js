// @ts-check
"use strict";
/* The Ocean display controls: the colour mode, the flashlight, the water's clarity and the modeline. Evaluation only
 * registers the factory; explicit phases retain page order. */
(function () {
  /** @param {OceanDisplayPorts} ports @returns {OceanDisplay} */
  function create(ports) {
  var colourBrain = false, colourMode = "family";
  /** @type {boolean} */
  var followLight, lightNow, lightBeforeFollow;
  /** @type {number} */
  var clarity;
  /** @type {number} */
  var modelineDetail;
  /* the shim's display switches: the colour mode is the shim's (memory), the
   * capture flag the world's, so both are set again after every new world and
   * every Turbo hand-off, and whenever the colour mode changes (setColourMode).
   * None changes a step's activations: the card's clock hears only of a capture
   * that switched (none, when the selection already set it); a new world resets
   * it (afterNewWorld) */
  function applyDisplaySwitches() {
    if (ports.has("oc_set_colour_mode")) ports.M._oc_set_colour_mode(colourBrain ? 0 : 1);
    if (ports.scene && ports.scene.setAppearance) ports.scene.setAppearance(colourMode === "appearance");
    if (ports.has("oc_set_capture")) {
      var cap = ports.inspector.selectedId !== null;
      ports.M._oc_set_capture(cap ? 1 : 0);
      ports.inspector.captureBrainClock(cap, ports.syncedFrame());
    }
  }
  function onFollowChange(on) {
    ports.el("followbtn").setAttribute("aria-pressed", on ? "true" : "false");
    ports.el("followbtn").title = on ? "Stop following (F or Esc)" : "Follow this fish (F)";
    if (!on) ports.inspector.wantFollow = false;
    if (on) ports.toast(ports.coarseMQ.matches ? "Following. Drag to circle around it."
                                   : "Following. Drag or A / D to circle it, W / S to come closer or back off; Esc stops.");
    /* Light while following: on as the follow starts, back as it was when it ends */
    if (on) { lightBeforeFollow = lightNow; if (followLight) lightNow = true; }
    else lightNow = lightBeforeFollow;
    updateLight();
    ports.updateKeysLegend();
  }
  /* ---- the flashlight (drawing only; scene.setFlashlight) ----
   * One light, on or off now: the dock's button, L and the View menu's
   * switch turn it on and off, and nothing else changes it but a follow. One
   * preference, "Light while following" (the View menu's switch, stored):
   * following a fish turns the light on, letting go puts it back as it was
   * (onFollowChange). L never writes the preference. */
  function initLight() {
  followLight = ports.store("evo_boids.ocean.followLight") !== "0", lightNow = false, lightBeforeFollow = false;
  }
  function lightOn() { return lightNow; }
  function updateLight() {
    var on = lightNow;
    if (ports.scene) ports.scene.setFlashlight(on);
    var b = ports.el("lightbtn");
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.title = (on ? "Flashlight on (L)" : "Flashlight (L)") + ": clear light where you look, in true colours";
    ports.el("lightnow").checked = on;
  }
  function toggleLight() {
    lightNow = !lightNow;
    if (lightNow && !(ports.scene && ports.scene.following())) ports.toast("Flashlight on: true colours where you look, without the water's tint.");
    updateLight();
  }
  function wireLightSwitch() {
  ports.el("lightnow").addEventListener("change", function () {
    lightNow = this.checked;
    updateLight();
    ports.pointerBlur(this);
  });
  }
  function wireFollowLight() {
  ports.el("followLight").addEventListener("change", function () {   /* the preference; following now, it applies now */
    followLight = this.checked;
    ports.store("evo_boids.ocean.followLight", followLight ? "1" : "0");
    if (ports.scene && ports.scene.following()) lightNow = followLight || lightBeforeFollow;
    updateLight();
    ports.pointerBlur(this);
  });
  ports.el("followLight").checked = followLight;
  }
  /* Fish colour: the fish's own appearance genome (its skin pattern; the
   * Ocean only, and the default), by family line, or by brain similarity.
   * Every mode draws each fish in its inherited body shape when the module
   * exports the genome (HAS_APP); family and brain only recolour the skin.
   * ?colour= wins, then the visitor's own last choice (stored only when they
   * pick one), else appearance. The key and ?colour= are shared with
   * Classic, which reads "appearance" as family. Display only. */
  function initColourMode() {
  (function () {
    var want = ports.P.get("colour"), saved = ports.store("evo_boids.colourBy");
    if (want !== "brain" && want !== "family" && want !== "appearance")
      want = saved === "brain" || saved === "family" ? saved : "appearance";
    colourMode = want;
    colourBrain = want === "brain";
    showColourMode();
  })();
  }
  /* the View menu's three buttons; the line under them says what the mode
   * shows, or why Appearance can't (updateModeline), with the way to fix it */
  function showColourMode() {
    ports.el("colourMode").querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.c === colourMode ? "true" : "false"); });
  }
  /* The one way the colour mode changes: the View menu's buttons and the
   * benchmark's cases (web/ocean_perf.js prepare) both come here, so a case
   * runs in the mode it names. false: no such mode (nothing changes). The
   * visitor's choice is stored, never a benchmark's. */
  function setColourMode(mode) {
    if (mode !== "appearance" && mode !== "family" && mode !== "brain") return false;
    colourMode = mode;
    colourBrain = colourMode === "brain";
    if (!ports.BENCH) ports.store("evo_boids.colourBy", colourMode);   /* a benchmark's cases are not the visitor's choice */
    showColourMode();
    if (ports.M) ports.engineCall(applyDisplaySwitches);   /* (a stopped engine: the view's choice is kept; a restarted one gets it with its run) */
    ports.engineCall(updateModeline);
    return true;
  }
  function wireColourControls() {
  ports.el("colourMode").addEventListener("click", function (e) {
    var b = /** @type {HTMLElement | null} */ (/** @type {Element} */ (e.target).closest("button[data-c]"));
    if (!b) return;
    setColourMode(b.dataset.c);
    ports.pointerBlur(b);
  });
  ports.el("colourwhy").addEventListener("click", function (e) {   /* "Setup › Life › Appearance genes" */
    if (!/** @type {Element} */ (e.target).closest("#colourfix")) return;
    ports.layers.setPop(null); ports.layers.setDrawer(true); ports.setSheetTab("life");
    var row = ports.el("f_appearance");
    if (row) row.scrollIntoView({ block: "center" });
  });
  }
  /* Water clarity: how murky the water is drawn (scene.setClarity; drawing
   * only, live), 0 realistic (the Ocean's first look, kept for reference)
   * .. 1 clear (the default). ?clarity= (clear, realistic, 0..1 or a
   * percentage) wins and is not stored; then the visitor's own last choice
   * (stored when they move the slider); else clear. */
  function initClarity() {
  clarity = 1;
  }
  function parseClarity(v) {
    if (v === null || v === undefined) return null;
    v = String(v).trim().toLowerCase();
    if (v === "clear") return 1;
    if (v === "realistic") return 0;
    var x = v === "" ? NaN : Number(v);
    if (!isFinite(x)) return null;
    if (x > 1) x /= 100;   /* a percentage */
    return Math.max(0, Math.min(1, x));
  }
  function clarityLabel(u) { return u >= 1 ? "Clear" : u <= 0 ? "Realistic" : Math.round(u * 100) + " % clear"; }
  function applyClarity() {
    var inp = ports.el("clarity");
    inp.value = String(Math.round(clarity * 100));
    inp.setAttribute("aria-valuetext", clarityLabel(clarity));
    ports.el("clarityval").textContent = clarityLabel(clarity);
    if (ports.scene && ports.scene.setClarity) ports.scene.setClarity(clarity);
  }
  function loadClarity() {
  (function () {
    var want = parseClarity(ports.P.get("clarity")), saved = parseClarity(ports.store("evo_boids.ocean.clarity"));
    clarity = want !== null ? want : saved !== null ? saved : 1;
    applyClarity();
  })();
  }
  function wireClarity() {
  ports.el("clarity").addEventListener("input", function () {
    clarity = Math.max(0, Math.min(1, (+this.value || 0) / 100));
    ports.store("evo_boids.ocean.clarity", String(clarity));
    applyClarity();
  });
  ports.el("clarity").addEventListener("pointerup", function () { this.blur(); });   /* the keys go back to the tank; arrow keys keep it */
  }
  /* the tank draws family colours: Family, or Appearance where the world has no appearance genes (updateModeline's rule) */
  function tankShowsFamily() {
    if (colourMode !== "appearance") return colourMode === "family";
    return !ports.engineCall(function () { return ports.HAS_APP ? (ports.has("oc_appearance_flags") ? ports.M._oc_appearance_flags() : 3) : 0; }, 3);
  }
  function initModeline() {
  modelineDetail = 0;   /* the detail level the modeline says */
  }
  function updateModeline() {
    /* the world's appearance genes (bit 1 patterns, bit 2 shapes; 0 = off, or a module without them) */
    var flags = ports.HAS_APP ? (ports.has("oc_appearance_flags") ? ports.M._oc_appearance_flags() : 3) : 0;
    var what = colourMode === "appearance"
      ? (flags ? ", each fish drawn from its appearance genes (skin pattern and body shape)"
               : ", coloured by family (" + (ports.HAS_APP ? "the appearance genes are off in this world" : "this module has no appearance genes") + ")")
      : (flags & 2 ? ", each fish in its inherited body shape" : "") + (colourBrain ? ", coloured by brain" : ", coloured by family");
    /* what replays: the module is serial and Hold 60 fps never changes the run; a live change is not part of the setup,
     * set back or not (changedKeys: the run's history); a world opened from a file, its history unknown (historyUnknown).
     * As data too: data-replay "yes" / "no" / "unknown", data-why "live" and / or "opened". */
    var tw = ports.changedKeys().length, ml = ports.el("modeline");
    modelineDetail = ports.scene ? ports.scene.quality() : 0;
    ml.dataset.replay = tw ? "no" : ports.historyUnknown ? "unknown" : "yes";
    ml.dataset.why = [tw ? "live" : "", ports.historyUnknown ? "opened" : ""].filter(Boolean).join(" ");
    ml.textContent = "Running the single-threaded Ocean module" + (ports.HAS_EYE ? " (the eye build)" : "") +
      ": the same seed and setup replay a run step for step" +
      (tw ? "; " + (tw === 1 ? "a setting was" : tw + " settings were") + " changed live during this run, which is not part of its setup" +
            " (even if set back), so Replay starts it again without " + (tw === 1 ? "that change" : "those changes")
          : ports.historyUnknown ? "; this world was opened from a file, which does not record what changed live before it was saved, so whether" +
            " Replay repeats this run is unknown (Start or Replay begins one that does)" : "") +
      ". The tank: " + ports.W + " × " + ports.H + " × " + ports.D +
      (ports.WALLS ? ", glass walls" : ", the sides wrap around") +
      ". Drawing: the 3D tank" + (ports.scene ? ", detail " + ports.scene.quality() + " of 3" : "") +
      what + ".";
    var noApp = !!ports.M && colourMode === "appearance" && !flags;   /* the View menu: what the colours show, or why not */
    ports.el("colourwhy").classList.toggle("why", noApp);
    ports.setHtml("colourwhy", noApp
      ? (ports.HAS_APP ? "Appearance genes are off in this world, so the fish show family colours. To turn them on: " +
                   "<button type='button' class='linkbtn' id='colourfix'>Setup › Life › Appearance genes</button>, then Start."
                 : "This engine build has no appearance genes, so the fish show family colours.")
      : colourMode === "appearance" ? "Each fish wears the skin pattern and body shape it inherited."
      : colourMode === "brain" ? "Fish with similar brains get similar colours."
      : "Each family line has its own colour, the same one it has in the charts.");
  }
  return { initLight: initLight, wireLightSwitch: wireLightSwitch, wireFollowLight: wireFollowLight, initColourMode: initColourMode, wireColourControls: wireColourControls,
    initClarity: initClarity, loadClarity: loadClarity, wireClarity: wireClarity, initModeline: initModeline,
    applyDisplaySwitches: applyDisplaySwitches, onFollowChange: onFollowChange, lightOn: lightOn, updateLight: updateLight, toggleLight: toggleLight,
    setColourMode: setColourMode, applyClarity: applyClarity, tankShowsFamily: tankShowsFamily, updateModeline: updateModeline,
    get colourMode() { return colourMode; }, get colourBrain() { return colourBrain; }, get modelineDetail() { return modelineDetail; } };
  }
  window.EvoOceanDisplay = { create: create };
})();
