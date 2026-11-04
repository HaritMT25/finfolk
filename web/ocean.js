"use strict";
/* evo_boids 3-D Ocean: the page controller (web/ocean.html).
 *
 * Runs the Ocean world (web/evo_ocean.{js,wasm}, factory createEvoOcean,
 * single-threaded; the C API is wasm/ocean_wasm.cpp's header) and draws it in
 * the deep tank (web/ocean_scene.js). Around it, the Classic page's controls
 * (web/renderer.js), so the two pages are one product:
 *   - the top bar (live readout -> the stat panel with the depth histogram;
 *     📊 dashboards, web/ocean_dash.js; Setup; Help: every key, the
 *     tour, "What is Turbo?") and the toasts
 *   - the dock: pause (one step while paused), speed (steps per frame),
 *     Turbo | the flashlight, View (the light while following, water clarity,
 *     fish colours, Hold 60 fps: drawing only), fit the tank. Nothing on it
 *     replaces the run.
 *   - Setup, the sheet built from web/ocean_config.js: the next world (the
 *     draft): every key the Ocean takes, "live" ones (oc_set_param) applying
 *     at once to the running world too, the rest waiting for Start;
 *     settings that do nothing with the others as they are are dimmed with
 *     the reason (NEEDS); the Run tab: Start from (scenario cards, Surprise
 *     me, a file: a setup, staged, or a saved world, opened), This run
 *     (Replay, Save setup, Save world: the fish themselves, mid-run); the
 *     start bar (what runs or what waits, Discard, Start: the same fish or
 *     new ones). One door: every world start is a plan for startWorld.
 *   - the fish card (click or tap a fish): oc_inspect's numbers and its live
 *     brain (oc_set_capture keeps its senses while a fish is selected)
 *   - Turbo: web/ocean_worker.js steps a copy of the module's memory at full
 *     speed; the copy comes back on Stop, so the run carries on exactly
 *     (web/ocean_handoff.js: the hand-off, shared with the worker)
 *   - Turbo is a mode of the dock (updateLocks): its strip takes the time
 *     group's place, with Stop (also Space and T), and the tank dims
 *   - the tour and the Turbo card (web/guide.js, steps below), from Help; a
 *     first visit opens on the tank, with one hint and later a Turbo coach mark
 * The flashlight (scene.setFlashlight) is drawing only: no engine call.
 *
 * Every pointer the module returns is valid until the next oc_sync / oc_init
 * (oc_inspect: until the next step or sync), and memory can grow — in any
 * export that allocates (oc_summary, oc_families, oc_inspect, oc_wiring, the
 * name lists, oc_sync itself) — so typed arrays are cut from the heap after
 * the call that fills them, and a frame's snapshot is cut again (fresh())
 * after anything that may have grown it.
 *
 * URL: ?seed=42 &pop=300 &depth=240 &w=1920 &h=1080 (1080 x 1920 on a
 *      portrait screen; each in oc_init's limits, or the link is refused)
 *      &walls=1|0 (glass walls or wrapping sides; every Restart writes it; a
 *      link without it — from before walls — wraps, a bare address starts
 *      with glass walls) &cfg={"key":value,...} (SimConfig + OceanConfig keys,
 *      as oc_init takes them; the settings show them) &speed=1 (steps per
 *      frame) &e1=1 (the E1 physics preset, oc_e1_preset, under &cfg)
 *      &colour=appearance|family|brain (else the visitor's last choice,
 *      appearance the first time) &guide=0|1 &intro=1 (web/guide.js)
 *      &clarity=clear|realistic|0..1 (the water's look, drawing only; else
 *      the visitor's last choice, clear the first time; never stored)
 *      ?mock=1 loads ocean_mock.js from beside the page instead of the engine
 *      (a JS stand-in for page development, not part of web/).
 *      ?renderBench=1 the render benchmark (web/ocean_perf.js: EvoOcean.bench,
 *      paused from the first frame, Hold 60 fps off); ?perf=1 its profiler only.
 *      The link's setup goes to oc_init as it is; one it refuses stops the
 *      page with the engine's reason (and a link without it).
 *      A Restart writes seed / pop / depth / w / h / cfg back, so a reload, or
 *      the link on another screen, is the same world.
 *      A query with only Classic's keys (?view, ?threads, ...) goes to Classic
 *      before this runs: the site's root was Classic (ocean.html's head).
 * Keys: space pause, + / - (or arrows) steps per frame, F follow (the selected
 *       fish, else a random one; again: another), Esc close / stop following
 *       / let go, R a new world (new seed), shift+R replay this one, C fit the
 *       view, L the flashlight (now; never "Light while following"), . one
 *       step while paused, T Turbo on / off, V the View menu, G the
 *       dashboards, O the settings, I the live numbers, ? Help (every key).
 *       Every dock and top-bar control has its key, and Help lists them.
 *       The camera, held (scene.setMove; by key position, never while a field
 *       has the focus): W / S forward / back along the view, A / D left /
 *       right, E / Q or PageUp / PageDown up / down, Shift faster. Following a
 *       fish they stay in the follow: W / S closer / farther, A / D circle it,
 *       E / Q raise / lower the camera around it.
 *
 * window.EvoOcean: a small handle for the console and the tests. */
(function () {
  /* the page is on its way to Classic (an old Classic link: ocean.html's head) */
  if (window.EVO_REDIRECT) return;
  var A = window.EVO_ASSETS, CFG = window.EvoOceanConfig;
  var P = new URLSearchParams(location.search);
  var MOCK = P.get("mock") === "1";
  var E1 = P.get("e1") === "1";
  /* measurement only (web/ocean_perf.js): off, a profiler that records nothing (also without the file) */
  var PERF = window.EvoOceanPerf, BENCH = !!PERF && P.get("renderBench") === "1";
  var PROF = PERF ? PERF.forPage(BENCH || P.get("perf") === "1") : { enabled: false, active: false, SPAN: {}, beginFrame: function () {},
    recordStep: function () {}, beginCpu: function () { return 0; }, lap: function () { return 0; }, endCpu: function () {} }, SP = PROF.SPAN;
  var DT = 0.016;                      /* oc_step's fixed step */
  var SPEEDS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64];
  var STEP_BUDGET_MS = 11;             /* of a 16.7 ms frame: what stepping may take (Hold 60 fps) */
  var STATS = { pop: 0, frame: 1, births: 2, deaths: 3, reseeds: 4, depthMean: 5, depthSd: 6, hist0: 7 };
  var REQUIRED = ["oc_init", "oc_reset", "oc_step", "oc_sync", "oc_creature_count", "oc_creature_segments",
                  "oc_creature_depth", "oc_body_params", "oc_creature_colors", "oc_creature_ids",
                  "oc_food_count", "oc_food_xy", "oc_food_depth", "oc_predator_count", "oc_predator_data",
                  "oc_predator_depth", "oc_stats", "oc_stats_len", "oc_width", "oc_height", "oc_depth_max"];
  var KEYS = CFG.KEYS, LIVE = CFG.LIVE, LABELS = CFG.LABELS;
  var ARGS = { seed: 1, population: 1, depth: 1, width: 1, height: 1 };   /* oc_init's own arguments, not cfg keys */
  var ACTION_LABELS = ["steer x", "steer y", "swim forward", "wander", "speed", "signal",
                       "oscillator period", "respond", "share food", "reproduce", "fight", "ignore", "steer z (depth)"];
  var ACTION_SHORT = ["steer x", "steer y", "forward", "wander", "speed", "signal",
                      "osc", "respond", "share", "breed", "fight", "ignore", "steer z"];

  /* the Classic tank's body-size curve (renderer.js bodyScale): the two must match */
  function bodyScale(b) { return b > 0 ? 1 + 0.4 * Math.tanh(5 * (b - 1)) : 1; }
  function el(id) { return document.getElementById(id); }
  var canvas = el("tank");
  var compactMQ = window.matchMedia("(max-width: 700px), (max-height: 560px), (pointer: coarse)");
  var coarseMQ = window.matchMedia("(pointer: coarse)");
  var wideMQ = window.matchMedia("(min-width: 960px)");
  var reducedMQ = window.matchMedia("(prefers-reduced-motion: reduce)");
  var lastPointer = "mouse";
  ["pointerover", "pointerdown"].forEach(function (type) {
    window.addEventListener(type, function (e) { lastPointer = e.pointerType || "mouse"; }, true);
  });
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private mode */ } return null; }

  /* ---------------- messages: the settings footer line, plus a toast ---------------- */
  var errEl = el("err"), toastsEl = el("toasts");
  function toast(msg, kind) {
    var t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
    t.textContent = msg;
    toastsEl.appendChild(t);
    while (toastsEl.children.length > 3) toastsEl.removeChild(toastsEl.firstChild);
    setTimeout(function () {
      t.classList.add("out");
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 220);
    }, kind === "error" ? 6000 : 3200);
  }
  function showError(msg) { errEl.textContent = msg; errEl.className = "error"; toast(msg, "error"); console.warn("ocean: " + msg); }
  function showNote(msg) { errEl.textContent = msg; errEl.className = ""; toast(msg); }
  function clearError() { errEl.textContent = ""; errEl.className = ""; }
  function splashSay(msg, isError) {
    var s = el("splashstate");
    s.textContent = msg;
    s.className = isError ? "error" : "";
    if (isError) el("splash").classList.add("failed");
  }

  /* ---------------- the module ---------------- */
  var SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0,
                                   10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);   /* loader.js's */
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("could not load " + src)); };
      document.head.appendChild(s);
    });
  }
  function abs(u) { return new URL(u, location.href).href; }
  var moduleUrls = null;   /* {js, wasm, handoff}: the Turbo worker (and a saved world's test run) load the same module */
  var noSimd = false;      /* Classic's modules need SIMD too: a start that fails for it offers no Classic */
  /* The engine build this page runs, pinned at start-up: the bytes of
   * evo_ocean.wasm fetched once, their sha-256 (the build's identity in a
   * world file), the module's own maximum memory (its wasm memory section:
   * a world file's limit) and a Blob URL of those very bytes, which is
   * what the module, the Turbo worker and a saved world's test run
   * instantiate (locateFile): so the build a world file names is the one
   * that ran it, even when the server's file changes meanwhile (a local
   * server without caching, a deploy while the page is open). */
  var pinned = null;   /* {bytes, sha256, maxBytes, url} */
  function pinEngine(url) {
    if (typeof fetch !== "function") return Promise.reject(new Error("this browser can't fetch " + url));
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("could not load " + url + " (HTTP " + r.status + ")");
      return r.arrayBuffer();
    }).then(function (b) {
      var bytes = new Uint8Array(b);
      return HO.sha256(bytes).then(function (sum) {
        return { bytes: bytes, sha256: sum, maxBytes: HO.wasmMemoryMax(bytes),
                 url: URL.createObjectURL(new Blob([bytes], { type: "application/wasm" })) };
      });
    });
  }
  /* a module instance of the pinned build (a new one after a trap: rebuildEngine) */
  function makeModule() {
    return createEvoOcean({ locateFile: function (path) { return path.slice(-5) === ".wasm" ? moduleUrls.wasm : path; } });
  }
  function loadModule() {
    if (!MOCK) {
      var simd = false;
      try { simd = typeof WebAssembly === "object" && WebAssembly.validate(SIMD_PROBE); } catch (e) { /* none */ }
      if (!simd) {
        noSimd = true;
        return Promise.reject(new Error("this browser has no WebAssembly SIMD, which the simulation needs (Chrome 91+, Firefox 89+ or Safari 16.4+)"));
      }
    }
    var js = abs(MOCK ? A.mock : A.ocean), wasm = abs(A.oceanWasm);
    moduleUrls = { js: js, wasm: wasm, handoff: abs(A.handoff || "ocean_handoff.js") };
    return Promise.all([MOCK ? null : pinEngine(wasm), loadScript(js)]).then(function (r) {
      pinned = r[0];
      if (pinned) moduleUrls.wasm = pinned.url;
      if (typeof createEvoOcean !== "function") throw new Error(js + " loaded but defines no createEvoOcean()");
      return makeModule();
    });
  }

  var M = null, HO = window.EvoOceanHandoff;
  /* The memory as it is now, strings in and out: web/ocean_handoff.js's, which
   * never read the module's own cached views (a Turbo hand-off grows the
   * memory from outside, and those stay behind until the module grows it
   * itself). */
  function heap() { return HO.buffer(M); }
  function has(fn) { return !!M && typeof M["_" + fn] === "function"; }
  function withCString(str, fn) { return HO.withCString(M, str, fn); }
  function cString(ptr) { return HO.cString(M, ptr); }
  /* a refusal the page made itself (before oc_init), read once by lastError */
  var pageError = "";
  function lastError() {
    if (pageError) { var e = pageError; pageError = ""; return e; }
    return M._oc_last_error ? cString(M._oc_last_error()) : "(no oc_last_error)";
  }
  /* Take a whole memory image of this same module (the Turbo hand-off; a
   * saved world, startWorld's "open"): grown to its size by exactly the
   * pages missing, copied in, the rest zeroed (web/ocean_handoff.js take();
   * web/ocean_worker.js says why this carries the run on exactly). full:
   * the image's length when src is its stored bytes only (a world file's,
   * an open's undo). Throws with this page's memory not overwritten. */
  function takeMemory(src, full) { HO.take(M, src, "the page's", full); }

  var W = 0, H = 0, D = 0, statsLen = 0, HAS_VZ = false, HAS_EYE = false, HAS_APP = false;
  var WALLS = false;   /* the running world has glass walls (oc_walls_enabled) */
  var LIGHT = { on: false, L0: 1, k: 0 };
  function readLight() {
    var on = has("oc_light_enabled") && !!M._oc_light_enabled();
    LIGHT = { on: on, L0: on ? M._oc_light_l0() : 1, k: on ? M._oc_light_kwater() : 0 };
    if (scene) scene.setLight(LIGHT);
  }
  function lightFromCfg() {
    var on = !!cfgVal("lightEnabled");
    LIGHT = { on: on, L0: on ? cfgVal("L0") : 1, k: on ? cfgVal("kWater") : 0 };
    if (scene) scene.setLight(LIGHT);
  }
  function readWorld() {
    W = M._oc_width(); H = M._oc_height(); D = M._oc_depth_max();
    statsLen = M._oc_stats_len();
    readLight();
  }
  /* the build's E1 preset (a copy each time), read from the engine once,
   * never from a stopped one (a scenario card asks it) */
  var e1Text = null;
  function e1Preset() {
    if (e1Text === null && has("oc_e1_preset") && engineState === "ok") e1Text = cString(M._oc_e1_preset());
    try { return e1Text === null ? null : JSON.parse(e1Text); } catch (e) { return null; }
  }

  /* ---------------- the world's settings ---------------- */
  var runCfg = {};           /* the running world's cfg (keys that differ from the default) */
  var initArgs = null;       /* the last successful oc_init's {seed, population, depth, cfg} (Replay) */
  var extraCfg = {};         /* cfg keys from ?cfg= or a setup file that the sheet has no field for */
  function cfgVal(key) { return Object.prototype.hasOwnProperty.call(runCfg, key) ? runCfg[key] : KEYS[key][0]; }
  /* The tank's size, oc_init's width / height (the sheet's Tank width /
   * length, like the depth): a new page's is the native 1920 x 1080, or the
   * same area on its side on a portrait screen (the same food density and
   * crowding, and a tank that fills a phone), unless ?w= / ?h= give it. Once
   * a world runs its size is explicit: a Restart writes it into the address
   * (so a shared link is the same world on a screen the other way up), Save
   * setup into the file. The size limits are oc_init's own (SIZE_LIMITS) and
   * the same for the link, the sheet and a setup file: a value outside them
   * is refused with the reason, never quietly changed. */
  var LIM = CFG.SIZE_LIMITS;
  function wholeIn(v, lim) { return typeof v === "number" && Number.isInteger(v) && v >= lim[0] && v <= lim[1]; }
  function depthOk(v) { return typeof v === "number" && isFinite(v) && v >= LIM.depth[0] && v <= LIM.depth[1]; }
  /* ?w= / ?h=: null when absent, else the number written (checked at start) */
  function urlNum(k) { return P.has(k) ? Number(P.get(k)) : null; }
  var URL_W = urlNum("w"), URL_H = urlNum("h");
  function isPortrait() { return innerHeight > innerWidth * 1.15; }
  function screenWorld() { return isPortrait() ? [1080, 1920] : [1920, 1080]; }
  function fittedWorld() {
    var f = screenWorld();
    return [URL_W !== null ? URL_W : f[0], URL_H !== null ? URL_H : f[1]];
  }
  /* "Fit the world to this screen": offered when the world has the other
   * orientation's size (the phone turned, or a link from a screen the other
   * way up); a size of its own (?w=300&h=300) stays as it is. Turning the
   * device only refits the camera: changing the world's orientation is this
   * explicit Restart. */
  function updateFitButton() {
    var f = screenWorld();
    el("fitbtn").hidden = !M || !(W === f[1] && H === f[0]);
  }
  /* the size only, for the next world (staged in the sheet, which opens on
   * it): Start starts it; the rest of the setup stays as it is */
  function fitToScreen() {
    if (!M) return;
    var f = screenWorld();
    setVal("width", f[0]); setVal("height", f[1]);
    updateNeeds(); updateTabDots(); renderStartBar();
    setDrawer(true);
    showNote("The tank's size for this screen, " + f[0] + " × " + f[1] + ", waits for the next start: Start applies it.");
  }
  /* the tank's sides: glass walls in the running world (oc_walls_enabled), and
   * whether this module knows them at all */
  function hasWalls() { return has("oc_walls_enabled"); }
  function wallsOn() { return hasWalls() && !!M._oc_walls_enabled(); }
  var worldReady = false, worldEpoch = 0;   /* epoch: a new world's (fish ids start over); Turbo keeps it */
  /* oc_init, and the bookkeeping of what it took: startWorld's alone.
   * repeats: the later occurrences of cfg's repeated keys (HO.parseFirst), so
   * oc_init checks each and takes the first, as it does for its own JSON.
   * size: [width, height] (the sheet's, the link's, a setup's). A refusal
   * changes nothing: oc_init checks everything before it replaces the world. */
  function initWorld(seed, population, depth, cfg, rawCfg, repeats, size) {
    if (cfg && (cfg.walls === true || cfg.walls === 1) && !hasWalls()) {   /* a stale module: it would ignore the key */
      pageError = "glass walls need a newer engine module (this one has no oc_walls_enabled: rebuild web/evo_ocean)";
      return false;
    }
    var json = rawCfg !== undefined ? rawCfg : HO.cfgJson(cfg, repeats);
    var ok = withCString(json, function (ptr) { return M._oc_init(seed >>> 0, size[0], size[1], depth, population, ptr); });
    if (!ok) return false;
    /* the bookkeeping, once the engine has taken it: an on / off key as
     * true / false (the Ocean's own also come as 0 / 1: oc_init takes those) */
    var accepted = Object.assign({}, cfg);
    Object.keys(accepted).forEach(function (k) {
      if (KEYS[k] && typeof KEYS[k][0] === "boolean") accepted[k] = accepted[k] === true || accepted[k] === 1;
    });
    initArgs = { seed: seed >>> 0, population: population, depth: depth, width: size[0], height: size[1], cfg: accepted };
    runCfg = Object.assign({}, accepted);
    return true;
  }

  /* ---------------- one door to a new world ----------------
   * Every world start is a plan, and only startWorld(plan) turns one into a
   * world: Start and its menu, R / Shift+R, Replay, a scenario, a setup
   * file, a saved world (From a file: op "open"), the link at start-up
   * (importWorld), the benchmark (importWorld).
   * A Turbo hand-back is not a start (the same world: no new epoch, the
   * charts kept). startWorld runs only while this page owns the world, and
   * at once, never from a frame: oc_init (or oc_reset for Replay), then the
   * page's bookkeeping, once — the epoch, the charts, the selection, the
   * sheet, the address. It answers {ok, why}; a refusal changes nothing.
   * requestStart (below) is the visitor's way to it: it checks the plan,
   * asks inline when the run has something to lose, and in Turbo stops it
   * first (the ordinary hand-back), then starts.
   * plan: {source, op: "init" | "replay" | "open", engine, build() -> {seed,
   *   population, depth, size: [w, h], cfg, raw, repeats}, url (write the
   *   address), check() -> "" or why not (before anything stops),
   *   done(), the toast on success, failed: the refusal's opening}
   * op "open": a saved world (Save world's file, checked whole, against this
   * engine build and in a test run of its own before it gets here:
   * openWorldFile): world {header, data, bytes, at (the test run's view of
   * it), initArgs, runCfg, picked, name, token}; its memory image goes in
   * (HO.take: grown, copied, the rest zeroed, as the Turbo hand-back)
   * instead of an oc_init, and the page's bookkeeping is the file's
   * (initArgs: the setup it started from, which Replay replays; runCfg: its
   * settings when saved), prepared before the image goes in. A new world
   * all the same: one epoch, the charts and the selection cleared. It is a
   * transaction: the running world's memory is copied first (undo), and
   * anything that throws once the image is in (the world read back and
   * compared with the test run's, the bookkeeping, the open's done()) puts
   * the run back as it was (restoreRun); a trap in the module (its stack
   * and globals can't be trusted after one) makes a new module of the same
   * build first (rebuildEngine), then puts the run back into it.
   * engine: the module the world runs in, "ocean" (this page's, the
   * default); a plan may name another, which this page refuses until it
   * can load one (the eye world will). */
  var ENGINE = "ocean";
  var usedTurbo = false;     /* Turbo ran this world (a reason to ask before replacing it) */
  var turboReturn = null;    /* the fish to select / follow again after Turbo (restoreAfterTurbo) */
  function startWorld(plan) {
    if (!M) return { ok: false, why: "the engine is not loaded" };
    if (engineState !== "ok") return { ok: false, why: engineBusyWhy() };
    if (turboState !== "live") return { ok: false, why: "Turbo owns the world" };
    if ((plan.engine || ENGINE) !== ENGINE)
      return { ok: false, why: "that world needs the " + plan.engine + " engine module, and this page runs the " + ENGINE + " one" };
    var a = plan.op === "init" ? plan.build() : null, undo = null;
    /* Replay keeps what waits (a staged recipe: the whole sheet; else the
     * fields that differ from this world, as typed), never the live tweaks
     * it drops: those fields equal this world, so they go back with it */
    var keep = plan.op === "replay" && !draft && initArgs ? pendingDiff().map(function (k) { return [k, rawOf(k)]; }) : null;
    if (plan.op === "replay") {
      if (!initArgs || !M._oc_reset()) return { ok: false, why: "oc_reset failed: " + lastError() };
      runCfg = Object.assign({}, initArgs.cfg);
    } else if (plan.op === "open") {
      var w = plan.world;
      if (!w.data) return { ok: false, why: "it was opened already (open its file again)" };
      try { undo = runNow(); }   /* the run as it is, before anything is overwritten */
      catch (err) { return { ok: false, why: "there is no room to keep your run while it opens (" + (err && err.message || err) + ")" }; }
      try {
        takeMemory(w.data, w.bytes);   /* (it throws before it overwrites anything when it can't grow; any throw: the run back) */
        var why = HO.worldMismatch(HO.worldNow(M), HO.worldExpect(w.header));   /* the module's world: the test run's */
        if (why) throw new Error(why);
      } catch (err) { return restoreRun(undo, err); }
      initArgs = w.initArgs; runCfg = Object.assign({}, w.runCfg);   /* (prepared when it was read) */
      w.data = null;   /* in the module now */
    } else if (!initWorld(a.seed, a.population, a.depth, a.cfg, a.raw, a.repeats, a.size)) {
      return { ok: false, why: lastError() };
    }
    /* committed: the page's bookkeeping, once */
    try {
      clearFieldNotes();
      afterNewWorld();
      stepOnce = false; summary = null; usedTurbo = false; turboReturn = null;
      if (plan.op === "init") { draft = null; projectForm(); }   /* a start consumes the draft */
      else if (plan.op === "open") { draft = null; projectRunning(); }   /* (its settings now: its live tweaks too) */
      else if (keep) { projectForm(); keep.forEach(function (e) { setRaw(e[0], e[1]); }); updateNeeds(); updateTabDots(); }
      draftGen++;   /* every new world, Replay too (which keeps the draft): a setup file read from before it is stale */
      if (plan.imported && a) warnOdd(a.cfg);   /* (a setup from outside the sheet: what it ran) */
      if (plan.url) writeUrl();
      hideAsk();
      renderStartBar();
    } catch (err) {
      if (!undo) throw err;
      return restoreRun(undo, err);
    }
    return { ok: true, why: "", undo: undo };
  }
  /* ---- the open's undo: the run as it was, and putting it back ----
   * runNow: the running world's memory (without its zero tail: a copy of
   * what it uses) and the page's bookkeeping of it, before a saved world's
   * image overwrites it. restoreRun(undo, err): the image failed once it
   * was in (err): the run goes back, the memory and the page as they were
   * (the epoch, the selection, the sheet, what waits); the answer is the
   * open's refusal. A trap (WebAssembly.RuntimeError) leaves a module
   * whose stack and globals can't be trusted, and a restore that throws
   * leaves one that can't be used: either way rebuildEngine makes a new
   * module of the same pinned build and puts the run into it. */
  var engineState = "ok";   /* "ok", "restarting" (rebuildEngine), "down" (it stopped: engineStopped) */
  function engineBusyWhy() {
    return engineState === "restarting" ? "the engine is restarting with your run: a moment" : "the engine stopped: reload the page";
  }
  /* Everything the commit changes is in it (review of #44, round 2, finding
   * 2): the memory, the world's bookkeeping, the epoch, the selection and
   * the follow, the sheet and what waits (the draft, its generation), the
   * charts' history (its rows, interval and origin), the sampling and the
   * rates, Turbo's history (usedTurbo: a reason to ask) and the fish Turbo
   * picks up again (turboReturn), the pause, the address. */
  function runNow() {
    var u8 = new Uint8Array(heap()), fields = {};
    Object.keys(KEYS).forEach(function (k) { if (el("o_" + k)) fields[k] = rawOf(k); });
    return { data: u8.slice(0, HO.storedLength(u8)), bytes: u8.length, initArgs: initArgs, runCfg: runCfg, epoch: worldEpoch,
             selectedId: selectedId, wantFollow: wantFollow, following: !!(scene && scene.following()), draft: draft, draftGen: draftGen,
             fields: fields, extraCfg: Object.assign({}, extraCfg), nextOnly: Object.assign({}, nextOnly), paused: paused, url: location.href,
             dash: dash() && dash().save ? dash().save() : null, sampleBucket: sampleBucket, rates: rates.q.slice(),
             usedTurbo: usedTurbo, turboReturn: turboReturn, stepOnce: stepOnce, summary: summary };
  }
  /* the page's side of a run put back (its memory is in the module again) */
  function pageBack(u) {
    initArgs = u.initArgs; runCfg = u.runCfg; worldEpoch = u.epoch; draft = u.draft; draftGen = u.draftGen;
    selectedId = null; wantFollow = false;
    afterNewWorld(true);   /* this world read again: no new epoch (the charts: below) */
    if (u.dash && dash() && dash().restore) dash().restore(u.dash);
    sampleBucket = u.sampleBucket; rates.q = u.rates.slice();
    usedTurbo = u.usedTurbo; turboReturn = u.turboReturn; stepOnce = u.stepOnce; summary = u.summary;
    Object.keys(u.fields).forEach(function (k) { setRaw(k, u.fields[k]); });
    extraCfg = u.extraCfg; nextOnly = u.nextOnly;
    updateNeeds(); updateTabDots();
    /* the fish and the follow as they were, both ways (the open may have followed one) */
    var back = u.selectedId !== null && indexOfId(fresh(lastS), u.selectedId) >= 0;
    if (back) select(u.selectedId, true);
    wantFollow = back && u.wantFollow;
    if (scene && scene.following() !== (back && u.following)) scene.setFollow(back && u.following);
    setPaused(u.paused);
    try { if (location.href !== u.url) history.replaceState(null, "", u.url); } catch (e) { /* file:// or a sandboxed frame */ }
    renderStartBar();
  }
  function restoreRun(u, err) {
    var why = String(err && err.message || err);
    if (!(err instanceof WebAssembly.RuntimeError)) {
      try {
        takeMemory(u.data, u.bytes);
        pageBack(u);
        return { ok: false, why: why + ". Your run carries on, as it was" };
      } catch (err2) { why += "; putting your run back failed too (" + (err2 && err2.message || err2) + ")"; }
    }
    rebuildEngine(u);
    return { ok: false, why: why + ". The engine stopped on it, so it is restarting with your run" };
  }
  /* a new module of the pinned build, the run u put into it (engineState
   * "restarting" meanwhile: no frame steps, nothing starts) */
  var rebuilds = 0;
  function rebuildEngine(u) {
    engineState = "restarting";
    rebuilds++;
    makeModule().then(function (m2) {
      HO.take(m2, u.data, "the page's", u.bytes);
      M = m2;
      if (window.EvoOcean) EvoOcean.module = M;
      engineState = "ok";
      pageBack(u);
      if (turboReturn) restoreAfterTurbo();   /* (Stop Turbo & open: the fish Turbo had, picked up again now the run is back) */
      showNote("The engine restarted, and your run is back where it was.");
    }).catch(function (e) {
      engineState = "down";
      showError("The engine could not restart (" + (e && e.message || e) + "). Reload the page to go on; Save setup still saves this world's setup.");
    });
  }
  /* the engine trapped while the page used it: nothing more is stepped, read or started (a reload is the way on) */
  function engineStopped(err) {
    engineState = "down";
    showError("The engine stopped (" + (err && err.message || err) + "), so this world can't go on. Reload the page to go on; Save setup still saves its setup.");
  }
  /* An engine call outside the frame and the transaction: a control, the
   * charts' timer, the console's handle. Nothing while the engine is
   * restarting or down (fallback; said so once a while for a visitor's
   * action: say); a trap in it stops the engine once (engineStopped)
   * instead of throwing at every use. */
  var busySaidT = -Infinity;
  function engineCall(fn, fallback, say) {
    if (!M || engineState !== "ok") {
      if (say && M && performance.now() - busySaidT > 2000) { busySaidT = performance.now(); showNote(say + ": " + engineBusyWhy() + "."); }
      return fallback;
    }
    try { return fn(); }
    catch (err) { if (err instanceof WebAssembly.RuntimeError) { engineStopped(err); return fallback; } throw err; }
  }
  /* A whole operation from outside (a button, a key, a field, Turbo's
   * messages), as one: a trap anywhere in it stops the engine once instead
   * of escaping, and nothing after it in the operation runs (review of #44,
   * round 3, finding 3). What it reaches while the engine is down is gated
   * where it reaches it (select, startWorld, follow, the hand-back, ...). */
  function fenced(fn) {
    return function () {
      try { return fn.apply(this, arguments); }
      catch (err) { if (err instanceof WebAssembly.RuntimeError) { engineStopped(err); return undefined; } throw err; }
    };
  }
  /* the sheet shows the world that now runs: its seed, size and settings
   * (initArgs; the keys it has no field for kept aside) */
  function projectForm() {
    resetForm();
    setVal("seed", initArgs.seed); setVal("population", initArgs.population); setVal("depth", initArgs.depth);
    setVal("width", W); setVal("height", H);
    cfgToForm(initArgs.cfg);
    updateNeeds(); updateTabDots();
  }
  /* A setup from outside the sheet (the link's, a setup file's), started as
   * it is: oc_init sees its values themselves, so a refusal says why, and
   * only a setup it accepts goes into the sheet, whose fields would round or
   * drop what they can't hold (0.5 for a count, 2 for an on / off key or a
   * choice). On a refusal nothing changes: the running world, the sheet.
   * raw: the cfg as text instead (a ?cfg= that is not JSON). Returns "", or
   * why not. The on / off keys are the engine's to check, as every value is
   * (one rule, in one place): a SimConfig switch (toroidal, bodyModel, ...)
   * must be a JSON true / false, the Ocean's own (lightEnabled, walls, ...)
   * may also be the number 0 / 1, and oc_init checks every occurrence before
   * it replaces the world (wasm/ocean_wasm.cpp). The sheet shows what it
   * runs (setVal: true or 1 is on); initWorld keeps true / false.
   * repeats: the later occurrences of a repeated key (HO.parseFirst; cfg
   * holds the first): they go on to oc_init, which checks each and runs the
   * first, as the sheet then shows. */
  /* (startWorld's adapter for the start-up's link and the benchmark, which
   * want its answer as "" or why; neither writes the address) */
  function importWorld(seed, population, depth, cfg, raw, repeats, size) {
    var r = startWorld(importPlan("import", seed, population, depth, cfg, raw, repeats, size, false));
    return r.ok ? "" : r.why;
  }
  function importPlan(source, seed, population, depth, cfg, raw, repeats, size, url) {
    var clean = {}, more = [];
    Object.keys(cfg || {}).forEach(function (k) { if (!ARGS[k]) clean[k] = cfg[k]; });
    (repeats || []).forEach(function (r) { if (!ARGS[r.key]) more.push(r); });
    return { source: source, op: "init", url: url, imported: clean,
             build: function () { return { seed: seed, population: population, depth: depth, cfg: clean, raw: raw, repeats: more, size: size }; } };
  }
  /* the sheet can't hold every value a setup may have (an on / off key as 2):
   * said in the console, the world runs what the setup says */
  function warnOdd(clean) {
    var odd = Object.keys(clean).filter(function (k) {
      if (!KEYS[k]) return false;
      var a = getVal(k), b = clean[k], bool = typeof KEYS[k][0] === "boolean" || (KEYS[k][1] || {}).bit;
      return bool ? !!a !== !!b : a !== b;
    });
    if (odd.length) console.warn("ocean: the sheet shows " + odd.join(", ") + " differently from the setup it runs");
  }
  /* a new world (oc_init or oc_reset; a saved world opened), or one handed back by Turbo */
  function afterNewWorld(fromTurbo) {
    if (!fromTurbo) worldEpoch++;
    var w0 = W, h0 = H, d0 = D, g0 = WALLS;
    readWorld();
    WALLS = wallsOn();
    M._oc_sync();         /* the last snapshot's views are the old world's: */
    lastS = snapshot();   /* the new world's now, not at the next frame */
    if (scene && (W !== w0 || H !== h0 || D !== d0 || WALLS !== g0)) { scene.setWorld(W, H, D, { walls: WALLS }); labelHist(); }
    /* a new world has nothing picked, BEFORE the capture is set from the
     * selection (applyDisplaySwitches): it was set from the old one, and
     * kept capturing senses with nothing selected (review of #44, finding 6;
     * a saved world picks its fish again after this, which sets it again) */
    if (!fromTurbo) {
      selectedId = null; wantFollow = false;
      if (scene && scene.following()) scene.setFollow(false);
    }
    applyDisplaySwitches();
    updateModeline();     /* the world's appearance genes may differ */
    estPrev.n = 0;
    stepMs = 0;
    if (!fromTurbo) {
      if (window.EvoOceanDash) EvoOceanDash.reset();
      sampleBucket = -1;
      rates.reset();
    }
    dirtyHud = true;
    updateFitButton();
  }
  /* the shim's display switches: the colour mode is the shim's (memory), the
   * capture flag the world's, so both are set again after every new world and
   * every Turbo hand-off */
  function applyDisplaySwitches() {
    if (has("oc_set_colour_mode")) M._oc_set_colour_mode(colourBrain ? 0 : 1);
    if (scene && scene.setAppearance) scene.setAppearance(colourMode === "appearance");
    if (has("oc_set_capture")) M._oc_set_capture(selectedId !== null ? 1 : 0);
  }

  /* ---- the sheet (built from EvoOceanConfig.TABS) ---- */
  function decimals(x) { var s = String(x); var i = s.indexOf("."); return i < 0 ? (s.indexOf("e-") > 0 ? +s.split("e-")[1] : 0) : s.length - i - 1; }
  function makeStepper(input, key, min, max) {
    var wrap = document.createElement("span");
    wrap.className = "stepper";
    function button(sign, icon, label) {
      var b = document.createElement("button");
      b.type = "button"; b.tabIndex = -1;
      b.setAttribute("aria-label", label);
      b.innerHTML = "<svg class='i'><use href='#i-" + icon + "'/></svg>";
      b.addEventListener("click", function () {
        var st = CFG.BTN_STEP[key] || 1, v = parseFloat(input.value);
        if (!Number.isFinite(v)) v = 0;
        v = +(v + sign * st).toFixed(Math.max(decimals(st), 0) + 2);
        v = +v.toFixed(Math.max(decimals(st), decimals(v) > 6 ? 6 : decimals(v)));
        if (min !== undefined && v < min) v = min;
        if (max !== undefined && v > max) v = max;
        input.value = String(v);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      return b;
    }
    wrap.appendChild(button(-1, "minus", "less"));
    wrap.appendChild(input);
    wrap.appendChild(button(1, "plus", "more"));
    return wrap;
  }
  function makeField(key) {
    var def = KEYS[key][0], opt = KEYS[key][1] || {}, id = "o_" + key;
    var row = document.createElement("div");
    row.className = "field";
    row.id = "f_" + key;
    var left = document.createElement("span");
    var name = document.createElement("label");
    name.className = "name";
    name.htmlFor = id;
    var lt = document.createElement("span");
    lt.className = "lt";
    lt.textContent = LABELS[key] || key;
    name.appendChild(lt);
    if (LIVE[key]) {
      var tag = document.createElement("span");
      tag.className = "livetag";
      tag.textContent = "live";
      tag.title = "applies to the running world at once";
      name.appendChild(tag);
    }
    var keyEl = document.createElement("span");
    keyEl.className = "key";
    keyEl.textContent = key + (CFG.HINTS[key] ? " · " + CFG.HINTS[key] : "");
    left.appendChild(name);
    left.appendChild(keyEl);
    var ctl = document.createElement("span");
    ctl.className = "ctl";
    var input;
    if (typeof def === "boolean" || opt.bit) {
      input = document.createElement("input");
      input.type = "checkbox";
      input.className = "switch";
      input.setAttribute("role", "switch");
      input.checked = !!def;
      ctl.appendChild(input);
    } else if (opt.options) {
      input = document.createElement("select");
      opt.options.forEach(function (label, i) {
        var o = document.createElement("option");
        o.value = String(i); o.textContent = label;
        input.appendChild(o);
      });
      input.value = String(def);
      ctl.appendChild(input);
    } else {
      input = document.createElement("input");
      input.type = "number";
      input.inputMode = "decimal";
      input.step = opt.step !== undefined ? String(opt.step) : "any";
      if (opt.min !== undefined) input.min = String(opt.min);
      if (opt.max !== undefined) input.max = String(opt.max);
      input.value = String(def);
      ctl.appendChild(makeStepper(input, key, opt.min, opt.max));
    }
    input.id = id;
    if (LIVE[key]) input.addEventListener("change", fenced(function () { applyLive(key); }));
    row.appendChild(left);
    row.appendChild(ctl);
    attachTip(row, key);
    return row;
  }
  /* a field's value as typed: a whole-number setting (opt.int) is never
   * rounded here, so 300.5 is refused (sizeProblem on Restart, applyLive
   * live), not run as 301 */
  function getVal(key) {
    var def = KEYS[key][0], opt = KEYS[key][1] || {}, input = el("o_" + key);
    if (typeof def === "boolean") return input.checked;
    if (opt.bit) return input.checked ? 1 : 0;
    var v = opt.options ? parseInt(input.value, 10) : parseFloat(input.value);
    if (!Number.isFinite(v)) return def;
    return v;
  }
  function wholeKey(key) { return !!(KEYS[key] && (KEYS[key][1] || {}).int); }
  function setVal(key, v) {
    var def = KEYS[key][0], opt = KEYS[key][1] || {}, input = el("o_" + key);
    if (!input) return;
    if (typeof def === "boolean" || opt.bit) input.checked = v === true || v === 1;
    else input.value = String(v);
  }
  function resetForm() { Object.keys(KEYS).forEach(function (k) { setVal(k, KEYS[k][0]); }); extraCfg = {}; nextOnly = {}; clearFieldNotes(); }
  /* a flat cfg object into the sheet: known keys into their fields, the rest kept aside */
  function cfgToForm(cfg) {
    Object.keys(cfg || {}).forEach(function (k) {
      if (KEYS[k] && !ARGS[k]) setVal(k, cfg[k]);
      else if (!ARGS[k]) extraCfg[k] = cfg[k];
    });
  }
  function readForm() {
    var cfg = {};
    Object.keys(KEYS).forEach(function (k) {
      if (ARGS[k]) return;
      var v = getVal(k), def = KEYS[k][0];
      if (typeof def === "boolean" ? v !== def : v !== def) cfg[k] = v;
    });
    Object.keys(extraCfg).forEach(function (k) { if (!(k in cfg)) cfg[k] = extraCfg[k]; });
    return { seed: argVal("seed"), population: argVal("population"), depth: argVal("depth"),
             width: argVal("width"), height: argVal("height"), cfg: cfg };
  }
  /* oc_init's own arguments as the sheet holds them: no rounding, no default
   * for an empty field (getVal's convenience for the other fields), so
   * sizeProblem checks the very number shown, as a link's or a setup's is
   * checked, and 99.6 is refused rather than run as 100 under a field
   * showing 99.6. (The steppers' clamping is theirs, before this.) */
  function argVal(key) {
    var s = String(el("o_" + key).value).trim();
    return s === "" ? NaN : Number(s);
  }
  /* the sheet's oc_init arguments against oc_init's limits: "" or why not */
  function sizeProblem(f) {
    var bad = [], got = function (v) { return " (got " + (v === v ? v : "no number") + ")"; };
    if (!wholeIn(f.seed, [0, 4294967295])) bad.push("the seed must be a whole number from 0 to 4294967295" + got(f.seed));
    if (!wholeIn(f.width, LIM.side)) bad.push("the tank width must be a whole number from " + LIM.side[0] + " to " + LIM.side[1] + got(f.width));
    if (!wholeIn(f.height, LIM.side)) bad.push("the tank length must be a whole number from " + LIM.side[0] + " to " + LIM.side[1] + got(f.height));
    if (!depthOk(f.depth)) bad.push("the sea depth must be from " + LIM.depth[0] + " to " + LIM.depth[1] + got(f.depth));
    if (!wholeIn(f.population, LIM.population)) bad.push("the starting fish must be a whole number from 0 to " + LIM.population[1] + got(f.population));
    /* the whole-number settings, as typed (the engine's own range checks follow in oc_init) */
    Object.keys(f.cfg).forEach(function (k) {
      if (wholeKey(k) && !Number.isInteger(f.cfg[k])) bad.push((LABELS[k] || k) + " must be a whole number" + got(f.cfg[k]));
    });
    return bad.join("; ");
  }
  /* ---- live settings ----
   * A live field shows what the running world uses, or says why not:
   *   - a value below 0: oc_set_param changes a running world only to 0 or
   *     more; where a new world takes it (CFG.NEG_ON_RESTART: kBuoy, the
   *     food rates, energies, ages) it waits for the Restart, marked so; for
   *     the rest it is outside the setting's range and the field goes back
   *   - while Turbo is starting or stopping (neither side owns the world for
   *     that moment) it is held, marked so, and applied as soon as one does
   *   - one the engine refuses: the field goes back to the running value,
   *     with the engine's reason. */
  /* the live edits around a Turbo session: held (waiting for Turbo's hand-off),
   * in flight (sent to the worker, not answered), acknowledged; in the order
   * they were made (web/ocean_handoff.js ledger, which the tests run) */
  var live = HO ? HO.ledger() : null;
  /* A live setting's value typed for the next world only (below 0: a
   * running world can't take it) is no ledger entry, and may be newer than
   * an edit of the key still on its way: that edit's answer (acknowledged or
   * refused) changes the running world's bookkeeping, never this field, and
   * the value counts as waiting meanwhile. Kept as typed; it holds while the
   * field still shows it (a newer edit, Discard or a start ends it). */
  var nextOnly = {};
  function nextOnlyNow(key) { return Object.prototype.hasOwnProperty.call(nextOnly, key) && !!el("o_" + key) && rawOf(key) === nextOnly[key]; }
  function numOf(key, v) { return typeof v === "boolean" ? (v ? 1 : 0) : v; }
  function valOf(key, num) { return typeof KEYS[key][0] === "boolean" ? num === 1 : num; }
  function shown(v) { return typeof v === "boolean" ? (v ? "on" : "off") : String(v); }
  /* the note under a field (why its value is not the running world's yet) */
  function fieldNote(key, text) {
    var row = el("f_" + key);
    if (!row) return;
    var n = row.querySelector(".pendnote");
    if (!n && !text) return;
    if (!n) { n = document.createElement("span"); n.className = "pendnote"; row.appendChild(n); }
    n.textContent = text;
  }
  function clearFieldNotes() {
    var notes = document.querySelectorAll(".field .pendnote");
    for (var i = 0; i < notes.length; i++) notes[i].textContent = "";
  }
  /* push one live knob into the running world (or the Turbo worker's) */
  function applyLive(key) {
    if (!M || draft) return;   /* a staged scenario's or file's settings are the next world's, live ones too */
    delete nextOnly[key];
    var num = numOf(key, getVal(key));
    if (wholeKey(key) && !Number.isInteger(num)) { refuse(key, "it must be a whole number"); return; }   /* 300.5: never run as 301 */
    if (num < 0) {
      if (CFG.NEG_ON_RESTART[key]) {
        nextOnly[key] = rawOf(key);
        fieldNote(key, "Applies at the next start: a running world takes only 0 or more.");
        renderStartBar();
        showNote((LABELS[key] || key) + " " + num + " waits for the next start (a running world takes only 0 or more).");
      } else refuse(key, "it must be 0 or more");
      return;
    }
    if (turboState === "entering" || turboState === "exiting") {
      live.hold(key, num);
      fieldNote(key, heldNote());
      return;
    }
    fieldNote(key, "");
    sendLive(key, num);
  }
  /* the note under a field whose edit is held for Turbo's hand-off */
  function heldNote() {
    return turboState === "entering" ? "Applies as soon as Turbo has started." : "Applies as soon as Turbo hands the world back.";
  }
  /* true: applied here; false: refused here (keep: the field stays, a newer
   * edit of the key follows); null: sent to the Turbo worker (seq: a held
   * edit's own sequence number, so it keeps its place) */
  function sendLive(key, num, quiet, keep, seq) {
    if (turboState === "turbo") {   /* Turbo owns the world: the worker applies it */
      live.sent(key, num, seq);
      turboWorker.postMessage({ cmd: "set", key: key, value: num });
      return null;
    }
    if (!has("oc_set_param")) return false;
    var ok = engineCall(function () { return withCString(key, function (p) { return M._oc_set_param(p, num); }); }, null);
    if (ok === null) { refuse(key, engineBusyWhy(), keep); return false; }   /* (it trapped, or the engine is not there) */
    /* (what follows, the light read back: inside the operation's fence, its field's change or Turbo's hand-back) */
    if (ok) liveApplied(key, valOf(key, num), quiet);
    else refuse(key, lastError(), keep);
    return !!ok;
  }
  /* seq: the worker's acknowledgment of that edit. With no newer edit of the
   * key on its way, the field shows what now runs (a refusal in between may
   * have set it back), unless the visitor is in it. */
  function liveApplied(key, v, quiet, seq) {
    if (v === KEYS[key][0]) delete runCfg[key]; else runCfg[key] = v;
    /* the light the picture is drawn in: this module's, or while Turbo owns
     * the world, what the worker acknowledged (this page's copy is the world
     * as Turbo took it; the hand-back reads the module again) */
    if (key === "lightEnabled" || key === "L0" || key === "kWater") { if (turboState === "live") readLight(); else lightFromCfg(); }
    var input = el("o_" + key);   /* (a staged recipe's field, or a newer value for the next world only: left alone) */
    if (input && !draft && !nextOnlyNow(key) && document.activeElement !== input && !(live && live.pending(key, seq)) && getVal(key) !== v) {
      setVal(key, v); updateNeeds(); updateTabDots();
    }
    renderStartBar();
    if (!quiet) showNote((LABELS[key] || key) + " is now " + shown(v) + " (live)");
  }
  /* a refused live value: the field goes back to the newest edit of it still
   * on its way to the world (held for Turbo's hand-off, with its note, or with
   * the worker), else to what the world runs with (keep: a newer edit of it
   * follows, so the field stays) */
  function refuse(key, why, keep) {
    var back = null, p = null, next = nextOnlyNow(key);
    if (!keep) {
      p = live ? live.latest(key) : null;
      back = p ? valOf(key, p.num) : cfgVal(key);
      if (!draft && !next) {   /* a staged recipe's field, or a newer value for the next world: left alone */
        setVal(key, back);
        fieldNote(key, p && p.from === "held" ? heldNote() : "");
        updateNeeds(); updateTabDots();
      }
      renderStartBar();
    }
    showError((LABELS[key] || key) + ": " + why + (keep ? "" : draft || next ? " (the running world keeps " + shown(back) + ")" :
              " (back to " + shown(back) + (p ? ", on its way" : "") + ")"));
  }
  /* Edits in the order they were made (ledger entries): to the worker while
   * Turbo owns the world, else to this one. A refused edit keeps its field
   * when a later edit of the key follows in the list. Returns what this
   * world did: {applied: [entry], refused: [[entry, why]]}. (Not "replay":
   * that is the page's Replay, oc_reset, below.) */
  function replayEdits(list, quiet) {
    var out = { applied: [], refused: [] };
    list.forEach(function (e, i) {
      if (!nextOnlyNow(e.key)) fieldNote(e.key, "");   /* (a newer value for the next world keeps its note) */
      var later = list.some(function (f, j) { return j > i && f.key === e.key; });
      var r = sendLive(e.key, e.num, quiet, later, e.seq);
      if (r === true) out.applied.push(e);
      else if (r === false) out.refused.push([e, lastError()]);
    });
    return out;
  }
  /* the held edits, now that one side owns the world */
  function flushHeld(quiet) { return replayEdits(live.takeHeld(), quiet); }

  var tabsEl = el("tabs"), panelsEl = el("panels"), currentTab = "run";
  function buildSettings() {
    CFG.TABS.forEach(function (tab) {
      var b = document.createElement("button");
      b.type = "button";
      b.id = "tab-" + tab.id;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "panel-" + tab.id);
      b.textContent = tab.title;
      b.addEventListener("click", function () { setSheetTab(tab.id); });
      tabsEl.appendChild(b);
      if (!tab.groups) return;
      var panel = document.createElement("section");
      panel.className = "panel";
      panel.id = "panel-" + tab.id;
      panel.dataset.tab = tab.id;
      panel.setAttribute("role", "tabpanel");
      if (tab.id === "ocean") panel.appendChild(presetBox());
      tab.groups.forEach(function (g) {
        var h = document.createElement("h3");
        h.textContent = g[0];
        panel.appendChild(h);
        g[1].forEach(function (k) { panel.appendChild(makeField(k)); });
      });
      panelsEl.appendChild(panel);
    });
    el("panel-run").setAttribute("role", "tabpanel");   /* (its view switches are in the View menu now) */
    var saved = store("evo_boids.ocean.tab");
    setSheetTab(saved && el("panel-" + saved) ? saved : "run");
  }
  /* the Water (E1) tab: the tuned E1 water added to what the tabs hold (the
   * next world; the rest kept). The whole Living water world is a scenario
   * in Run › Start from. */
  function presetBox() {
    var box = document.createElement("div");
    box.className = "preset";
    box.innerHTML = "<button type='button' class='btn' id='e1add'><svg class='i'><use href='#i-plus'/></svg>Add the tuned E1 water</button>" +
      "<p>Surface waves, a gentle deep current with food drifting in it, light that fades with depth, and depth costs scaled to each fish's " +
      "metabolism, put into these tabs on top of the rest (predators, food, ... stay). They wait for the next start. The whole " +
      "<b>Living water</b> world is in Run › Start from.</p>";
    box.querySelector("#e1add").addEventListener("click", fenced(function () {
      var p = e1Preset();
      if (!p) { showError(engineState !== "ok" ? "The E1 water: " + engineBusyWhy() + "." : "this module has no E1 preset (oc_e1_preset)"); return; }
      cfgToForm(p);
      updateNeeds(); updateTabDots(); renderStartBar();
      showNote("The E1 water is in the tabs: it waits for the next start.");
      this.blur();
    }));
    return box;
  }

  /* ---- Start from: scenarios (EvoOceanConfig.SCENARIOS) and a file ----
   * A card stages its whole recipe as the next world (stageDraft): the tabs
   * show it, and it starts only when its Start (or the start bar's) is
   * pressed: two presses in one place. Surprise me draws again with Reroll.
   * Picking one over edits that wait asks first (Replace / Keep editing). */
  var CARD_IDS = { standard: "advreset", bigtank: "bigbtn", e1: "e1btn", hunters: "huntersbtn", currents: "currentsbtn", surprise: "randombig", file: "loadcp" };
  function newSeed() { return (Math.random() * 0x100000000) >>> 0; }
  /* the seed the sheet shows (a scenario keeps it; Surprise me draws its own) */
  function shownSeed() { var s = formNum("seed"); return wholeIn(s, [0, 4294967295]) ? s : initArgs ? initArgs.seed : KEYS.seed[0]; }
  function scenarioOf(id) {
    var t = { width: formNum("width"), height: formNum("height"), depth: formNum("depth"), walls: !!getVal("walls"),
              sideWallBand: getVal("sideWallBand"), sideWallTurnRate: getVal("sideWallTurnRate") };
    if (!(t.width > 0) || !(t.height > 0) || !(t.depth > 0)) { t.width = W; t.height = H; t.depth = D; }
    return CFG.scenario(id, { seed: id === "surprise" ? newSeed() : shownSeed(), screen: screenWorld(), walls: hasWalls(), e1: e1Preset(),
                              rand: Math.random, tank: t });
  }
  /* what a new draft would replace: edits waiting, or a staged recipe's own edits */
  function atRisk() { return pendingDiff().length; }
  function pickScenario(id) {
    if (!M) return;
    if (id === "bigtank" && !hasWalls()) { showError("The Big tank needs glass walls: this engine module has none (rebuild web/evo_ocean)."); return; }
    if (id === "e1" && !e1Preset()) { showError("this module has no E1 preset (oc_e1_preset)"); return; }
    var n = atRisk(), title = (CFG.SCENARIOS.filter(function (s) { return s.id === id; })[0] || {}).title;
    if (draft && draft.id === id && id !== "surprise") { showNote(title + " is ready: its Start (or the start bar's) starts it."); return; }
    if (n) { askReplace(title, n, function () { stageScenario(id); }); return; }
    stageScenario(id);
  }
  function stageScenario(id) {
    var r = scenarioOf(id);
    if (!r) { showError("That scenario is not available here."); return; }
    stageDraft({ kind: "scenario", id: id, title: r.title, summary: r.summary, seed: r.seed }, function () {
      setVal("seed", r.seed); setVal("population", r.population); setVal("depth", r.depth); setVal("width", r.width); setVal("height", r.height);
      cfgToForm(r.cfg);
    });
    el("randnote").textContent = id === "surprise" ? "Picked: " + r.summary + ". Reroll draws again; every setting is in the tabs." : "";
    clearError();
    showNote(r.title + " is ready: Start starts it" + (turboState !== "live" ? " (and stops Turbo)." : "."));
  }
  /* a staged card's Start: the start bar's own dispatcher */
  function startStaged() { restart(); }
  function setSheetTab(id) {
    currentTab = id;
    CFG.TABS.forEach(function (tab) {
      var on = tab.id === id;
      el("tab-" + tab.id).setAttribute("aria-selected", on ? "true" : "false");
      el("tab-" + tab.id).tabIndex = on ? 0 : -1;
      el("panel-" + tab.id).hidden = !on;
    });
    panelsEl.scrollTop = 0;
    hideTip();
    store("evo_boids.ocean.tab", id);
  }
  tabsEl.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var ids = CFG.TABS.map(function (t) { return t.id; });
    var i = (ids.indexOf(currentTab) + (e.key === "ArrowRight" ? 1 : -1) + ids.length) % ids.length;
    setSheetTab(ids[i]);
    el("tab-" + ids[i]).focus();
    e.preventDefault();
  });
  function updateTabDots() {
    CFG.TABS.forEach(function (tab) {
      if (!tab.groups) return;
      /* against what a new page starts with: the screen's size, glass walls */
      var sw = screenWorld();
      var pageDef = function (k) {
        return k === "width" ? sw[0] : k === "height" ? sw[1] : (k in CFG.FRESH && hasWalls()) ? CFG.FRESH[k] : KEYS[k][0];
      };
      var changed = tab.groups.some(function (g) {
        return g[1].some(function (k) { return k !== "seed" && k !== "population" && getVal(k) !== pageDef(k); });
      });
      var b = el("tab-" + tab.id), dot = b.querySelector(".dot");
      if (changed && !dot) { dot = document.createElement("span"); dot.className = "dot"; dot.title = "changed from the default"; b.appendChild(dot); }
      else if (!changed && dot) b.removeChild(dot);
    });
  }
  /* Settings that do nothing with the others as they are: dimmed, with the
   * reason under their name. Each rule: [keys, () => "" (fine) or the reason],
   * reading the settings through nv: the sheet's (the next world), or the
   * running world's. A live setting with nothing staged acts on the running
   * world now and on the next one later, so it dims only when it does
   * nothing in either (predators 0 typed for the next world leaves the
   * three hunting now tunable). */
  var nvRunning = false;
  function nv(k) { return nvRunning ? runningVal(k) : getVal(k); }
  function hasCurrent() { return nv("currentStrength") > 0; }
  function hasPredators() { return nv("predatorCount") > 0; }
  var NEEDS = [
    [["walls"], function () { return M && !hasWalls() ? "needs a newer engine module (this one has no glass walls)" : ""; }],
    [["sideWallBand", "sideWallTurnRate"], function () { return nv("walls") ? "" : "needs glass walls on"; }],
    [["toroidal"], function () { return nv("walls") ? "off with glass walls: a walled tank has no seam to sense across" : ""; }],
    [["foodPatchRadius", "foodDepthMode"], function () { return nv("foodPatches") > 0 ? "" : "needs food patches above 0"; }],
    [["foodDepthSpread"], function () { return nv("foodPatches") > 0 && nv("foodDepthMode") === 1 ? "" : "needs food patches, each at its own depth"; }],
    [["foodDrift", "currentMode", "currentDrift", "deepCurrent"], function () { return hasCurrent() ? "" : "needs a current (strength above 0)"; }],
    [["currentEddies", "currentCore"], function () { return hasCurrent() && nv("currentMode") === 0 ? "" : "needs a current in the eddies shape"; }],
    [["predatorEconomy", "predatorSpeed", "predatorPerception", "predatorCaptureRadius", "predatorCooldown"],
      function () { return hasPredators() ? "" : "needs predators above 0"; }],
    [["predatorMeal", "predatorMetabolism", "predatorReproEnergy", "predatorMaxAge", "predatorMinPopulation",
      "predatorMaxPopulation", "predatorInheritance"],
      function () { return hasPredators() && nv("predatorEconomy") ? "" : "needs predators, with their economy on"; }],
    [["predatorTraitMutation"], function () {
      return hasPredators() && nv("predatorEconomy") && nv("predatorInheritance") ? "" : "needs hunters inherit traits on"; }],
    [["maxTurnRate"], function () { return nv("triangularMotion") ? "" : "needs fast-swims-straight on"; }],
    [["steerFrame"], function () { return nv("triangularMotion") ? "no effect with fast-swims-straight on: it turns by steer x already" : ""; }],
    [["reproSoftWidth", "reproGracePeriod"], function () { return nv("reproMaxDistance") >= 0 ? "" : "needs a breeding distance limit of 0 or more"; }],
    [["bodyMutation", "sizeFight"], function () { return nv("bodyModel") ? "" : "needs evolving bodies on (without them every fish is size 1)"; }],
    [["sizeDrift"], function () {
      if (!nv("bodyModel")) return "needs evolving bodies on (without them every fish is size 1)";
      return hasCurrent() || nv("waveSpeed") > 0 ? "" : "needs a current or waves to drift in";
    }],
    [["kMouth"], function () { return nv("mouthGate") ? "" : "needs the mouth gate on"; }],
    [["waveBand", "waveGravity"], function () { return nv("waveSpeed") > 0 ? "" : "needs waves (strength above 0)"; }],
    [["L0", "kWater"], function () { return nv("lightEnabled") ? "" : "needs the light field on"; }],
    [["depthCostScaled"], function () { return nv("cHold") > 0 || nv("cPress") > 0 ? "" : "needs a depth cost above 0"; }],
    [["eye", "eyeOnly"], function () { return HAS_EYE ? "" : "needs the eye build of the module; this page runs the plain Ocean build"; }],
    [["eyeCode"], function () {
      if (!HAS_EYE) return "needs the eye build of the module; this page runs the plain Ocean build";
      return nv("eye") ? "" : "needs the compound eye on";
    }]
  ];
  function updateNeeds() {
    NEEDS.forEach(function (rule) {
      var why = rule[1](), whyNow = "";
      if (why && !draft && initArgs && rule[0].some(function (k) { return LIVE[k]; })) {
        nvRunning = true;
        try { whyNow = rule[1](); } finally { nvRunning = false; }
      }
      rule[0].forEach(function (k) {
        var row = el("f_" + k);
        if (!row) return;
        var hint = row.querySelector(".needs");
        if (!hint) { hint = document.createElement("span"); hint.className = "needs"; row.appendChild(hint); }
        var inert = !!why && !(LIVE[k] && !draft && initArgs && !whyNow);
        row.classList.toggle("inert", inert);
        hint.textContent = inert ? why : why ? why.replace(/^needs/, "the next world needs") + "; it still acts on this one" : "";
      });
    });
    /* glass walls and wrap-around senses exclude each other (the engine
     * refuses both): with walls checked the wrap switch is off and locked */
    var tor = el("o_toroidal"), wl = el("o_walls");
    if (tor) tor.disabled = !!getVal("walls");
    if (wl) wl.disabled = !!M && !hasWalls();
  }
  /* ---- the draft: the next world (UI-3) ----
   * The sheet is the next world's setup. With nothing staged (draft null)
   * it is this world plus the edits waiting for the next start: live
   * settings apply at once (they are this world's too), the others wait. A
   * staged scenario or setup file (draft {kind, id, title, summary, base,
   * plan}) fills the whole sheet with its recipe: every edit of it, a live
   * setting's too, is the next world's, and nothing reaches the running one
   * (the "live" tags hide). What waits is derived from values, never
   * remembered (pendingDiff): a field changed back waits no more. Discard
   * drops what waits, never an accepted live tweak; a start consumes it;
   * Replay keeps it (and drops the live tweaks). draftGen moves with every
   * stage, discard and start: a file read from before is stale. */
  var draft = null, draftGen = 0;
  /* a field as typed: on / off, 0 / 1, an option's index, or a number (NaN: none) */
  function formNum(k) {
    var def = KEYS[k][0], opt = KEYS[k][1] || {}, input = el("o_" + k);
    if (typeof def === "boolean") return input.checked;
    if (opt.bit) return input.checked ? 1 : 0;
    if (opt.options) return parseInt(input.value, 10);
    var s = String(input.value).trim();
    return s === "" ? NaN : Number(s);
  }
  /* what the running world has for a field (the accepted live changes in it) */
  function runningVal(k) {
    if (k === "seed") return initArgs ? initArgs.seed : KEYS.seed[0];
    if (k === "population") return initArgs ? initArgs.population : KEYS.population[0];
    if (k === "depth") return initArgs ? initArgs.depth : KEYS.depth[0];
    if (k === "width") return W;
    if (k === "height") return H;
    var v = cfgVal(k), def = KEYS[k][0], opt = KEYS[k][1] || {};
    if (typeof def === "boolean") return v === true || v === 1;
    if (opt.bit) return v === true || v === 1 ? 1 : 0;
    return v;
  }
  /* NaN (an empty or unreadable field) differs from every number, not from
   * itself: a file's value the sheet can't show (an option 1e400) is not an edit */
  function differs(k, a, b) { return typeof KEYS[k][0] === "boolean" ? !!a !== !!b : !(a === b || (a !== a && b !== b)); }
  function snapForm() { var o = {}; Object.keys(KEYS).forEach(function (k) { if (el("o_" + k)) o[k] = formNum(k); }); return o; }
  /* the fields whose next value is not what runs now (nothing staged; an
   * edit on its way to the world has its own note), or not the staged
   * recipe's (a draft: "modified") */
  function pendingDiff() {
    var out = [];
    Object.keys(KEYS).forEach(function (k) {
      if (!el("o_" + k)) return;
      var a = formNum(k);
      if (draft) { if (differs(k, a, draft.base[k])) out.push(k); return; }
      if (LIVE[k] && live && live.pending(k) && !nextOnlyNow(k)) return;   /* (on its way: its own note; a newer next-world value waits) */
      if (differs(k, a, runningVal(k))) out.push(k);
    });
    return out;
  }
  function waitingNow() { return !!draft || pendingDiff().length > 0; }
  /* a field's raw content (Replay keeps what was typed, even a half-typed number) */
  function rawOf(k) { var i = el("o_" + k); return i.type === "checkbox" ? i.checked : i.value; }
  function setRaw(k, v) { var i = el("o_" + k); if (i.type === "checkbox") i.checked = !!v; else i.value = v; }
  function escHtml(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fieldText(k) {
    var v = formNum(k), opt = KEYS[k][1] || {};
    var shownV = typeof v === "boolean" ? (v ? "on" : "off") : opt.bit ? (v ? "on" : "off") : opt.options ? opt.options[v] : v === v ? String(v) : el("o_" + k).value || "(empty)";
    return (LABELS[k] || k) + " " + shownV;
  }
  function runSummary() {
    if (!initArgs) return "";
    var tw = liveTweaks().length;
    return "seed " + initArgs.seed + " · " + W + " × " + H + " × " + D + " · " + initArgs.population + " fish · " +
           (WALLS ? "glass walls" : "wrapping sides") + (tw ? " · " + tw + " live tweak" + (tw > 1 ? "s" : "") : "");
  }
  /* the start bar (and the readout's count): what runs, or what the next start is */
  function renderStartBar() {
    var diff = pendingDiff(), n = diff.length, turbo = turboState !== "live";
    var b = el("restart");
    b.querySelector("span").textContent = pendingStart ? "Stopping Turbo…" : turbo ? "Stop Turbo & start" :
      draft ? "Start " + draft.title : n ? "Start with " + (n === 1 ? "the change" : "the " + n + " changes") : "Start again";
    b.classList.toggle("pending", !!draft || n > 0 || turbo);
    el("startdiscard").hidden = !(draft || n);
    drawerEl.classList.toggle("staging", !!draft);
    setHtml("startsummary", draft
      ? "<b>Next world: " + escHtml(draft.title) + "</b> · " + escHtml(draft.summary) + (n ? " · modified (" + n + ")" : "") +
        ". Starting it replaces this run."
      : n ? "<b>Waiting for the next start:</b> " + diff.slice(0, 3).map(function (k) { return escHtml(fieldText(k)); }).join(" · ") +
            (n > 3 ? " · and " + (n - 3) + " more" : "")
      : "<b>Running</b> · " + escHtml(runSummary()));
    el("startsummary").title = el("startsummary").textContent;   /* (a short screen shows two lines of it) */
    var wc = el("waitingcount"), count = draft ? 1 + n : n;
    wc.hidden = !count;
    setHtml("waitingcount", count + "<span class='wc-word'> waiting</span>");
    wc.title = draft ? draft.title + " is ready for the next start (Setup)" : count + " edit" + (count > 1 ? "s" : "") + " waiting for the next start (Setup)";
    setTxt("startsame-sub", "seed " + shownSeed() + (draft ? ", " + draft.title : n ? ", with what waits" : ""));
    markCards();
  }
  /* the picked card wears its Start (and Surprise me its Reroll): the same start as the bar's */
  var cardShown = null;   /* the card last brought into view (a new pick scrolls to it, a Reroll doesn't) */
  function markCards() {
    var pickedId = draft ? (draft.kind === "file" ? "file" : draft.id) : null, acts = el("scenario-acts");
    Object.keys(CARD_IDS).forEach(function (id) {
      var b = el(CARD_IDS[id]), on = id === pickedId;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      if (b.parentNode && b.parentNode.classList) b.parentNode.classList.toggle("picked", on);
      if (on && b.parentNode && acts.parentNode !== b.parentNode) b.parentNode.appendChild(acts);
    });
    acts.hidden = !pickedId;
    el("rerollbtn").hidden = pickedId !== "surprise";
    var lab = el("scenario-start").querySelector("span");
    if (lab) lab.textContent = turboState !== "live" ? "Stop & start" : "Start";
    el("scenario-start").title = turboState !== "live" ? "Stops Turbo, then starts this world (asked first)" : "Starts this world";
    /* a phone's strip scrolls sideways: the picked card comes into view with
     * its Start, at a place the strip snaps to (its start), so it stays there */
    var card = pickedId ? el(CARD_IDS[pickedId]).parentNode : null;
    if (!card) cardShown = null;
    else if (pickedId !== cardShown && drawerEl.classList.contains("open") && card.scrollIntoView) {   /* (a closed sheet: nothing to scroll) */
      cardShown = pickedId;
      try { card.scrollIntoView({ block: "nearest", inline: "start" }); } catch (e) { /* old */ }
    }
  }
  /* the sheet back to the running world: its seed and size, its settings
   * with the live tweaks it accepted; an edit still on its way keeps its
   * field (and note) */
  function projectRunning() {
    resetForm();
    if (initArgs) { setVal("seed", initArgs.seed); setVal("population", initArgs.population); setVal("depth", initArgs.depth); }
    setVal("width", W); setVal("height", H);
    cfgToForm(runCfg);
    if (live) Object.keys(LIVE).forEach(function (k) {
      var p = live.latest(k);
      if (p) { setVal(k, valOf(k, p.num)); if (p.from === "held") fieldNote(k, heldNote()); }
    });
    updateNeeds(); updateTabDots();
  }
  /* a scenario or a setup file into the sheet, as the next world (fill:
   * puts its recipe in the fields; the edits waiting before are replaced) */
  function stageDraft(d, fill) {
    d.hadEdits = pendingDiff().length > 0 || !!(draft && draft.hadEdits);   /* (it replaces edits that waited: Start asks) */
    draft = null;
    resetForm();
    fill();
    updateNeeds(); updateTabDots();
    d.base = snapForm();
    draft = d; d.gen = ++draftGen;
    hideAsk();
    renderStartBar();
  }
  function discardDraft() {
    var had = waitingNow();
    draft = null; draftGen++;
    projectRunning();
    hideAsk();
    renderStartBar();
    showNote(had ? "Discarded what was waiting. Live tweaks stay: they already apply." : "Nothing was waiting.");
  }
  function setPending() { renderStartBar(); }
  function paintStart() { renderStartBar(); }
  function onEdit(e) {
    var t = e.target;
    if (asking) { hideAsk(); showNote("The setup changed: start again to review it."); }   /* never a start other than the one asked about */
    if (t && t.id === "o_walls" && t.checked) setVal("toroidal", false);   /* walls need toroidal off */
    updateNeeds();
    updateTabDots();
    renderStartBar();
  }

  /* ---- the visitor's starts: requestStart, its inline question ----
   * Ask first when the run has something to lose (the approved rule): five
   * simulated minutes or more, Turbo used (or running), live tweaks
   * accepted since it started, or edits waiting for the next start
   * (editsWaiting). During Turbo the start waits for the
   * ordinary hand-back (pendingStart): the progressed world comes back and
   * every edit on its way is settled, then the plan is built again and must
   * be the one that was asked about (a refused edit or a change made
   * meanwhile cancels it: the run carries on, and says so); then the old
   * worker goes and startWorld runs, in the hand-back's message, never in a
   * frame. A world the engine refuses then leaves the run going (Live).
   * Stop (or the question's Cancel) meanwhile cancels the start, not the
   * hand-back. A worker that fails meanwhile cancels it too. */
  var pendingStart = null;   /* {plan, key}: waiting for Turbo's hand-back */
  var asking = null;         /* {plan, key}: the inline question is showing */
  function guardTurbo() {
    if (turboState === "live") return false;
    showNote("Stop Turbo first.");
    return true;
  }
  /* The plan asked about, and the sheet it came from: an asked or queued
   * start is that one only while both stay the same. A staged file's plan
   * is its own recipe and does not read the sheet, so the sheet itself is
   * in the key: an edit, Discard, another card or file, Fit, the E1 water
   * made meanwhile is a change (the run carries on, and says so; the draft
   * stays). Replay keeps what waits, so only its world counts. */
  function sheetKey() {
    return JSON.stringify([draft ? draft.gen : 0, Object.keys(KEYS).map(function (k) { return el("o_" + k) ? rawOf(k) : null; }), extraCfg]);
  }
  function planKey(plan) {
    if (plan.op === "replay") return "replay " + (initArgs ? initArgs.seed : "");
    if (plan.op === "open") return "open " + plan.world.token + " " + sheetKey();   /* (the file as read; what waits, which it drops) */
    return JSON.stringify(plan.build()) + " " + sheetKey();
  }
  function runAge() {
    var f = turboState !== "live" && turboStats ? turboStats.frame : (lastS ? (fresh(lastS).stats[1] || 0) : 0);
    return f * DT;
  }
  /* the live settings changed since this world started (accepted ones) */
  function liveTweaks() {
    if (!initArgs) return [];
    var seen = {}, out = [];
    Object.keys(runCfg).concat(Object.keys(initArgs.cfg)).forEach(function (k) {
      if (seen[k] || !LIVE[k]) return;
      seen[k] = true;
      var a = k in runCfg ? runCfg[k] : KEYS[k][0], b = k in initArgs.cfg ? initArgs.cfg[k] : KEYS[k][0];
      if (a !== b) out.push(k);
    });
    return out;
  }
  /* Edits waiting for the next start (the approved rule's fourth reason to
   * ask): a field changed (Fit and the E1 water too), a staged recipe
   * modified, or a recipe staged over edits that waited (draft.hadEdits,
   * remembered when it was staged: a card picked on an untouched sheet adds
   * no question by itself) */
  function editsWaiting() { return pendingDiff().length > 0 || !!(draft && draft.hadEdits); }
  /* What a start would lose. Opening a saved world drops every staged
   * recipe, an untouched one too (a Surprise me drawn, Hunters, a setup
   * file picked): it is not the world that opens, so it is something to
   * lose (review of #44, finding 4). Starting a staged recipe needs no
   * question for itself: it is what was picked. */
  function loseReasons(plan) {
    var r = [], age = runAge(), tw = liveTweaks();
    if (age >= 300) r.push(fmtTime(age) + " of evolution");
    if (usedTurbo || turboState !== "live") r.push("Turbo's progress");
    if (tw.length) r.push(tw.length === 1 ? "a live tweak (" + (LABELS[tw[0]] || tw[0]) + ")" : tw.length + " live tweaks");
    if (editsWaiting()) r.push("edits waiting");
    else if (draft && plan && plan.op === "open") r.push("the staged " + draft.title);
    return r;
  }
  /* "started", "asked", "waiting" (for Turbo's hand-back) or "refused" */
  function requestStart(plan, confirmed) {
    if (!M) return "refused";
    var why = plan.check ? plan.check() : "";
    if (why) { showError("Couldn't start that world: " + why + "."); return "refused"; }
    if (pendingStart) { showNote("A new world is already waiting for Turbo to stop."); return "waiting"; }
    if (engineState !== "ok") { showError("Couldn't start that world: " + engineBusyWhy() + "."); return "refused"; }
    if (loseReasons(plan).length && !confirmed) { askStart(plan); return "asked"; }
    clearError();
    if (turboState === "live") return commitStart(plan) ? "started" : "refused";
    pendingStart = { plan: plan, key: planKey(plan) };
    if (turboState === "turbo") exitTurbo();   /* entering: its first stats stop it; exiting: on its way */
    updateLocks();
    showNote("Stopping Turbo, then starting the new world.");
    return "waiting";
  }
  function commitStart(plan) {
    var r = startWorld(plan);
    if (!r.ok) { showError((plan.failed || "Couldn't start that world: ") + r.why); return false; }
    if (plan.done && r.undo) {   /* an open's last step is part of it: its failure puts the run back too */
      try { plan.done(); }
      catch (err) { showError((plan.failed || "Couldn't start that world: ") + restoreRun(r.undo, err).why); return false; }
    } else if (plan.done) plan.done();
    return true;
  }
  /* Turbo handed the world back with a start waiting: the same plan, or none */
  function finishPendingStart(ps) {
    if (planKey(ps.plan) !== ps.key) {
      showError("The setup changed while Turbo stopped (an edit was refused, or the next world was edited, discarded or replaced meanwhile), " +
                "so the new world did not start: your run carries on. Check it and start again.");
      return false;
    }
    dropWorker();   /* a clean slate: the next Turbo gets a fresh worker */
    ps.plan.failed = "Turbo stopped and your run carries on, but that world was refused: ";
    return commitStart(ps.plan);
  }
  function cancelPendingStart(why) {
    if (!pendingStart) return;
    pendingStart = null;
    if (why) showNote(why);
    updateLocks();
  }
  /* a setting's value as the sheet says it (on / off, an option's name, a number) */
  function n01(v) { return v === true ? 1 : v === false ? 0 : v; }
  function valText(k, v) {
    var opt = KEYS[k][1] || {};
    if (typeof KEYS[k][0] === "boolean" || opt.bit) return n01(v) ? "on" : "off";
    return opt.options && opt.options[v] !== undefined ? opt.options[v] : String(v);
  }
  /* the inline question, in the start bar (the setup sheet opens for it).
   * What it says of the live tweaks is read from the world this start
   * makes (the plan's recipe): a tweak the new world has too carries over;
   * one a scenario or a file (or a value typed for the next world) sets
   * otherwise is said so, with what it sets; Replay drops them all. */
  function askStart(plan) {
    asking = { plan: plan, key: planKey(plan) };
    var turbo = turboState !== "live", replaying = plan.op === "replay", age = runAge(), lose = [], tw = liveTweaks();
    if (age >= 300) lose.push(fmtTime(age) + " of evolution");
    if (usedTurbo || turbo) lose.push("what Turbo ran");
    if (plan.op === "open") {   /* a saved world: its own settings, nothing of this run's */
      var dl = pendingDiff(), dlist = dl.slice(0, 3).map(fieldText).join(", ") + (dl.length > 3 ? " and " + (dl.length - 3) + " more" : "");
      showAsk((turbo ? "This stops Turbo and replaces your run" : "This replaces your run") + (lose.length ? ", and " + lose.join(" and ") + " with it" : "") +
        ". It opens " + worldText(plan.world) + "." +
        /* every staged recipe, untouched too (finding 4), and every edit that waits: named, and dropped */
        (draft || dl.length ? " What waits for the next start" + (draft ? " (" + draft.title + (dl.length ? ", changed: " + dlist : "") + ")" : " (" + dlist + ")") + " is dropped." : "") +
        (tw.length ? " Your live tweak" + (tw.length === 1 ? "" : "s") + " (" + tw.map(function (k) { return (LABELS[k] || k) + " " + valText(k, cfgVal(k)); }).join(", ") + ") " +
                     (tw.length === 1 ? "goes" : "go") + ": the saved world has its own settings." : ""),
        turbo ? "Stop Turbo & open" : "Open it", "Keep it");
      return;
    }
    var b = replaying ? null : plan.build(), kept = [], other = [];
    tw.forEach(function (k) {
      if (replaying) return;
      var next = Object.prototype.hasOwnProperty.call(b.cfg, k) ? b.cfg[k] : KEYS[k][0];
      (n01(next) === n01(cfgVal(k)) ? kept : other).push([k, next]);
    });
    var mine = function (l) { return l.map(function (k) { return (LABELS[k] || k) + " " + valText(k, cfgVal(k)); }).join(", "); };
    var keys = function (l) { return l.map(function (e) { return e[0]; }); }, s = function (n) { return n === 1 ? "" : "s"; };
    var who = draft ? draft.title.charAt(0).toUpperCase() + draft.title.slice(1) : "The new world's setup";
    /* what waits, which this start applies (Replay: keeps) */
    var diff = pendingDiff(), list = diff.slice(0, 3).map(fieldText).join(", ") + (diff.length > 3 ? " and " + (diff.length - 3) + " more" : "");
    var edits = replaying || !editsWaiting() ? "" : draft ? " It starts " + draft.title + (diff.length ? " as you changed it (" + list + ")" : "") + "." :
                " It starts with what waits: " + list + ".";
    showAsk((replaying ? "Replay starts this world again from its seed" : turbo ? "This stops Turbo and replaces your run" : "This replaces your run") +
      (lose.length ? ", and " + lose.join(" and ") + " with it" : "") + "." + edits +
      (replaying && tw.length ? " Your live tweak" + s(tw.length) + " (" + mine(tw) + ") " + (tw.length === 1 ? "is" : "are") + " dropped." : "") +
      (kept.length ? " Your live tweak" + s(kept.length) + " (" + mine(keys(kept)) + ") " + (kept.length === 1 ? "carries" : "carry") + " over to the new world." : "") +
      (other.length ? " " + who + " sets " + other.map(function (e) { return (LABELS[e[0]] || e[0]) + " " + valText(e[0], e[1]); }).join(", ") +
                      " instead of your live tweak" + s(other.length) + " (" + mine(keys(other)) + ")." : "") +
      (replaying && waitingNow() ? " What waits for the next start stays waiting." : ""),
      replaying ? "Replay" : turbo ? "Stop Turbo & start" : "Replace it", "Keep it");
  }
  /* a scenario or a file over edits that wait: asked in the same place */
  function askReplace(title, n, fn) {
    asking = { replace: fn };
    showAsk(title + " replaces " + (n === 1 ? "the change" : "the " + n + " changes") + " waiting for the next start.", "Replace", "Keep editing");
  }
  function showAsk(msg, yes, no) {
    if (errEl.className !== "error") clearError();   /* a note under the question would only repeat it */
    el("startaskmsg").textContent = msg;
    el("startconfirm").textContent = yes;
    el("startcancel").textContent = no;
    el("startask").hidden = false;
    el("applybar").classList.add("asking");
    setStartMenu(false);
    if (!drawerEl.classList.contains("open")) setDrawer(true);
  }
  function hideAsk() {
    asking = null;
    el("startask").hidden = true;
    el("applybar").classList.remove("asking");
  }
  function confirmAsk() {
    var a = asking;
    hideAsk();
    if (!a) return;
    if (a.replace) { a.replace(); return; }
    if (planKey(a.plan) !== a.key) { showNote("The setup changed: start again to review it."); return; }
    requestStart(a.plan, true);
  }
  function cancelAsk() {
    var a = asking;
    hideAsk();
    showNote(a && a.noNote ? a.noNote : a && a.replace ? "Kept your changes." : "Kept your run.");
    if (a && a.opener) a.opener.focus();   /* a question the keyboard opened: the focus back where it was (askBtn) */
  }
  /* the start bar's menu: Start again (same fish), Start fresh (new fish) */
  function setStartMenu(open) {
    var m = el("startmenu");
    if (!m) return;
    m.hidden = !open;
    el("startmenubtn").setAttribute("aria-expanded", open ? "true" : "false");
  }
  function startMenuOpen() { var m = el("startmenu"); return !!m && !m.hidden; }
  /* a plan from the sheet: its seed (or a new one, drawn once per request),
   * size and settings as typed, checked before anything stops */
  function formPlan(source, seed) {
    function f() { var x = readForm(); if (seed !== undefined) x.seed = seed; return x; }
    return { source: source, op: "init", url: true,
             check: function () { return sizeProblem(f()); },
             build: function () { var x = f(); return { seed: x.seed, population: x.population, depth: x.depth, size: [x.width, x.height], cfg: x.cfg }; } };
  }
  function restart(done) {
    var plan = startPlan(), d0 = plan.done, picked = !!draft && draft.id === "surprise";
    plan.done = function () {
      if (picked) el("randnote").textContent = el("randnote").textContent.replace(/ Reroll draws again;.*$/, " It runs now; every setting is in the tabs.");
      else el("randnote").textContent = "";
      if (d0) d0();
      if (done) done();
    };
    return requestStart(plan);
  }
  function newWorld() {
    var plan = startPlan((Math.random() * 0x100000000) >>> 0), d0 = plan.done;
    plan.done = function () { el("randnote").textContent = ""; if (d0) d0(); toast("A new world, seed " + initArgs.seed + "."); };
    requestStart(plan);
  }
  /* this world again from its start: oc_reset (the last init's seed and
   * config; live changes since are dropped), and the sheet back to them */
  function replay() {
    if (!initArgs) return;
    requestStart({ source: "replay", op: "replay", done: function () { clearError(); toast("Replaying seed " + initArgs.seed + " from its start."); } });
  }
  /* a Restart writes the setup into the address, so a reload or a shared
   * link is this world: its size too, on a screen of any shape */
  function writeUrl() {
    if (!initArgs) return;
    try {
      var u = new URL(location.href);
      u.searchParams.set("seed", String(initArgs.seed));
      u.searchParams.set("w", String(W)); u.searchParams.set("h", String(H));
      if (initArgs.population !== KEYS.population[0]) u.searchParams.set("pop", String(initArgs.population)); else u.searchParams.delete("pop");
      if (initArgs.depth !== KEYS.depth[0]) u.searchParams.set("depth", String(initArgs.depth)); else u.searchParams.delete("depth");
      /* the sides, always explicit (a link without walls= is an old one, which wraps) */
      if (hasWalls()) u.searchParams.set("walls", WALLS ? "1" : "0");
      var cfgOut = Object.assign({}, initArgs.cfg);
      delete cfgOut.walls;
      if (Object.keys(cfgOut).length) u.searchParams.set("cfg", JSON.stringify(cfgOut)); else u.searchParams.delete("cfg");
      u.searchParams.delete("e1");   /* its keys are in cfg now */
      u.searchParams.delete("renderBench"); u.searchParams.delete("perf");   /* measurement, never a setup's */
      history.replaceState(null, "", u);
    } catch (e) { /* file:// or a sandboxed frame */ }
  }
  /* Save setup: the running world's — its seed, size and settings, with the
   * live changes that applied since it started (in Turbo: those the worker
   * acknowledged). Edits still waiting for a start, or on their way to the
   * world, are not in it (they are not the running world's), and it says so. */
  /* Version 2 (glass walls): `walls` is its own field, always written; a
   * version-1 file (before walls existed) loads as a wrapping world. */
  var SETUP_VERSION = 2;
  /* the running world's setup, as Save setup writes it (a world file carries one too) */
  function setupNow() {
    var config = Object.assign({}, runCfg);
    delete config.walls;
    return { format: "evo_ocean_setup", version: SETUP_VERSION, seed: initArgs.seed, population: initArgs.population,
             depth: initArgs.depth, width: W, height: H, walls: WALLS, config: config };
  }
  function download(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);   /* (after the click has handed it over) */
  }
  /* the live edits not in a saved world or setup yet (held, or on their way to the worker) */
  function onTheWay() { return Object.keys(live.held()).concat(live.inflight().map(function (e) { return e[0]; })); }
  function saveSetup() {
    if (!initArgs) return;
    download(new Blob([JSON.stringify(setupNow(), null, 2)], { type: "application/json" }), "evo_ocean_setup_seed" + initArgs.seed + ".json");
    /* during Turbo too: runCfg is what the world accepted (the worker's acknowledgements) */
    var onWay = onTheWay();
    toast("Saved this world's setup (seed " + initArgs.seed + ")" +
          (waitingNow() ? ". What waits for the next start is not in it: start first to include it." : ".") +
          (onWay.length ? " Not in it yet: " + onWay.map(function (k) { return LABELS[k] || k; }).join(", ") + ", still on the way to the world." : ""));
  }

  /* ---- Save world, and a saved world opened (web/ocean_handoff.js: the file) ----
   * Save world writes the running world itself — every fish, its brain and
   * genes, the food, the predators, the rng, the frame — as the module's
   * memory image (the one the Turbo hand-off moves) with a header: the
   * engine build it ran on (the sha-256 of the evo_ocean.wasm this page
   * pinned and runs: pinEngine), the setup it started from (initArgs: what
   * Replay replays), its settings now (runCfg: the live tweaks accepted),
   * its Save setup file, and the fish picked (and followed) then, with its
   * family line and place. In Turbo the worker hands over a copy between
   * chunks and runs on (no Stop, nothing lost): the settings are the ones
   * it acknowledged before it copied, the fish the one picked when Save
   * world was pressed. View preferences (colours, clarity, the flashlight,
   * speed, pause) are the visitor's, never the world's, and stay out of it.
   * From a file opens one (the same card as a setup file, which it tells
   * apart by its first bytes), read part by part, each part checked before
   * the next is read (HO.readWorld: the size, the header and its checksum,
   * the lengths; HO.headerProblem: every field of it), against this engine
   * build (another build can't take the image: its setup, from the checked
   * header, is offered instead), the body unpacked and checked; then tried
   * in a module of its own, in a worker (probeWorld: the image in, checked
   * against its header, one step), so a file whose image is not a world
   * this engine can run is refused with the run untouched; then through the
   * one door (requestStart, op "open"): asked first when the run has
   * something to lose (a staged recipe included), Stop Turbo & open during
   * Turbo, one new epoch, a transaction (startWorld). Replay then replays
   * its setup from its start, frame 0; the file opened again goes back to
   * the saved moment. */
  /* this page's engine build: the sha-256 of the bytes it pinned and runs */
  function engineId() { return pinned ? Promise.resolve(pinned.sha256) : Promise.reject(new Error("this page runs no engine build of its own")); }
  function shortId(id) { return String(id || "?").slice(0, 8); }
  var RULES = { keys: KEYS, live: LIVE, lim: LIM, setupVersion: SETUP_VERSION };   /* a world file's header (HO.headerProblem) */
  var worldSave = null;   /* a Save world under way: {id, picked}; with a worker: waiting for its copy */
  var worldSaveSeq = 0;
  /* the fish picked (and followed) now, for the file, with its family line
   * and place (returnPoint's: what the open needs to pick its nearest
   * kin, as Turbo's hand-back does, if it is gone); in Turbo the one Turbo
   * will pick up again (its place when Turbo took the world) */
  function pickedNow() {
    var r = turboState !== "live" ? turboReturn : returnPoint();
    return r ? { id: r.id, follow: !!r.follow, family: r.family, x: r.x, y: r.y, d: r.d } : null;
  }
  /* What this device opens (and so saves): a world file's image at most
   * `image`, and an open holding at most `budget` at once (openNeeds), from
   * navigator.deviceMemory (Chrome's: GB, reported up to 8) or, where the
   * browser doesn't say (Firefox, Safari), the kind of device (a coarse
   * pointer: a phone or a tablet, the smaller). The largest world the page
   * can start uses 185 MiB; a phone's tab is closed well below 1 GB. */
  function deviceBudget() {
    var MiB = 1048576, nav = window.navigator, dm = nav && typeof nav.deviceMemory === "number" && nav.deviceMemory > 0 ? nav.deviceMemory : 0;
    if (dm >= 8) return { budget: 1536 * MiB, image: 512 * MiB };
    if (dm >= 4) return { budget: 768 * MiB, image: 256 * MiB };
    if (dm >= 2) return { budget: 384 * MiB, image: 128 * MiB };
    if (dm > 0) return { budget: 192 * MiB, image: 64 * MiB };
    return coarseMQ.matches ? { budget: 384 * MiB, image: 128 * MiB } : { budget: 768 * MiB, image: 256 * MiB };
  }
  function worldLimitsHere() { return HO.worldLimits(pinned ? pinned.maxBytes : null, deviceBudget().image); }
  /* a world whose memory is more than a world file holds here: never written (this page could not open it again) */
  function tooBigToSave(bytes, lim) {
    return "Couldn't save the world: it uses " + fmtMB(bytes) + " of memory, more than a world file holds on this device (" + fmtMB(lim.image) +
           "), so it could not be opened again. Save setup keeps its recipe; a reload starts the engine small again (its memory never shrinks).";
  }
  /* Save world: the reader's limits first, before anything is copied (in
   * Turbo the worker checks them before its copy); a failure anywhere (the
   * copy, the encoding, the download) says so and leaves Save world free to
   * press again (writeWorld; review of #44, round 2, findings 4 and 5) */
  function saveWorld() {
    if (!M || !initArgs) return;
    if (MOCK) { showNote("Save world needs the real engine."); return; }
    if (engineState !== "ok") { showNote("Save world: " + engineBusyWhy() + "."); return; }
    if (worldSave) { showNote("Saving the world: a moment."); return; }
    if (turboState === "entering" || turboState === "exiting") { turboWait(); return; }
    var lim = worldLimitsHere();
    if (turboState === "turbo") {   /* the worker's copy, between two of its chunks: Turbo runs on */
      worldSave = { id: ++worldSaveSeq, waiting: true, picked: pickedNow(), lim: lim };   /* (the fish as now, not when the copy comes) */
      turboWorker.postMessage({ cmd: "snapshot", id: worldSave.id, maxBytes: lim.image });
      errEl.textContent = "Saving the world from Turbo (it keeps running)…"; errEl.className = "";   /* (no toast: the saved one follows) */
      return;
    }
    if (heap().byteLength > lim.image) { showError(tooBigToSave(heap().byteLength, lim)); return; }
    var my = worldSave = { id: ++worldSaveSeq, picked: null, lim: lim }, mem, s;
    try {
      my.picked = pickedNow();   /* (first: its card's oc_inspect may allocate; the copy is the world after it, as it runs on) */
      s = fresh(lastS);   /* this frame's numbers: no step since its sync, so the image's */
      /* again, right before the copy: the inspection may have grown the memory past the limit (review of #44, round 3, finding 4) */
      if (heap().byteLength > lim.image) { worldSave = null; showError(tooBigToSave(heap().byteLength, lim)); return; }
      mem = heap().slice(0);
    } catch (err) {
      if (worldSave === my) worldSave = null;
      if (err instanceof WebAssembly.RuntimeError) { engineStopped(err); return; }
      showError("Couldn't save the world: " + (err && err.message || err) + ". Nothing was written; Save world again to retry.");
      return;
    }
    writeWorld(mem, { frame: s.stats[1], pop: s.n, food: s.fc, pred: s.pc }, my.picked);
  }
  /* the worker's answer to Save world: its copy; or none (it has no world any more), too big, or no room for the copy (Turbo runs on) */
  function onSnapshot(msg) {
    if (!worldSave || !worldSave.waiting || msg.id !== worldSave.id) return;
    var my = worldSave;
    my.waiting = false;
    if (msg.tooBig) { worldSave = null; showError(tooBigToSave(msg.tooBig, my.lim)); return; }
    if (msg.error) { worldSave = null; showError("Couldn't save the world: " + msg.error + ". Turbo runs on with its world; Save world again to retry."); return; }
    if (msg.none || !msg.mem) { worldSave = null; showError("Couldn't save the world: Turbo had no world to copy. Try again."); return; }
    writeWorld(msg.mem, msg, my.picked);
  }
  /* Turbo went (its worker failed or was dropped) with a Save world waiting for its copy */
  function cancelSnapshot(why) {
    if (!worldSave || !worldSave.waiting) return;
    worldSave = null;
    showError("The world was not saved: " + why + ". Save it again.");
  }
  function worldHeader(at, picked, id) {
    return { format: HO.WORLD.FORMAT, version: HO.WORLD.VERSION, app: "Finfolk Ocean", saved: new Date().toISOString(),
             engine: { module: "evo_ocean", wasmSha256: id, eye: HAS_EYE },
             frame: at.frame, fish: at.pop, food: at.food, predators: at.pred,
             start: JSON.parse(JSON.stringify(initArgs)), runCfg: Object.assign({}, runCfg), setup: setupNow(), picked: picked };
  }
  /* the file from its copy: a throw anywhere (the header, the encoding, the
   * Blob, the download) is reported, and the save is over either way (this
   * save's own: a newer one is never cleared). The copy itself is checked
   * against the reader's limits first (the save's, my.lim), whoever made
   * it, and encodeWorld checks them again: nothing this page could not open
   * again is downloaded. */
  function writeWorld(mem, at, picked) {
    var my = worldSave, header = null, onWay = [], waiting = false, lim = my && my.lim || worldLimitsHere();
    if (mem.byteLength > lim.image) { if (worldSave === my) worldSave = null; showError(tooBigToSave(mem.byteLength, lim)); return; }
    Promise.resolve().then(function () {
      onWay = onTheWay(); waiting = waitingNow();
      return engineId();
    }).then(function (id) {
      header = worldHeader(at, picked, id);
      /* the reader's rules for its own file: a world this page could not open again is not written */
      var bad = HO.headerProblem(header, RULES);
      if (bad) throw new Error("its record would not open again (" + bad + ")");
      return HO.encodeWorld(header, mem, { limits: lim });
    }).then(function (w) {
      mem = null;
      var name = "finfolk_seed" + header.start.seed + "_frame" + header.frame + HO.WORLD.EXT;
      download(new Blob(w.parts, { type: "application/octet-stream" }), name);
      toast("Saved the world at frame " + fmtInt(header.frame) + " (" + fmtInt(header.fish) + " fish) as " + name + ", " + fmtMB(w.size) +
            ". From a file opens it again, carrying on from there (on this engine build, " + shortId(header.engine.wasmSha256) + ")." +
            (waiting ? " What waits for the next start is not in it." : "") +
            (onWay.length ? " Not in it: " + onWay.map(function (k) { return LABELS[k] || k; }).join(", ") + ", still on the way to the world." : ""));
    }).catch(function (err) {
      showError("Couldn't save the world: " + (err && err.message || err) + ". Save world again to retry.");
    }).then(function () { if (worldSave === my) worldSave = null; });
  }
  function fmtMB(b) { return b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " kB"; }
  /* a saved world, as the question and the notes name it */
  function worldText(w) {
    var h = w.header;
    return "the saved world " + (w.name ? w.name + " " : "") + "(seed " + h.start.seed + ", frame " + fmtInt(h.frame) + ", " + fmtInt(h.fish) + " fish, " +
           h.start.width + " × " + h.start.height + ")";
  }
  /* A saved world tried before it opens (HO.probeWorld), in a module of the
   * pinned build in a worker of its own (ocean_worker.js "probe"): the
   * image goes there and back (transferred, img.data again after), the
   * worker is terminated after its answer. A worker that doesn't answer in
   * PROBE_MS (a world that loops or crawls) is terminated: refused; so is
   * one whose read is superseded (cancelled(): a newer file, a start), at
   * once, not when it answers. A Promise of {ok, at, why}. */
  var PROBE_MS = 20000;
  function probeWorld(img, header, cancelled) {
    return new Promise(function (resolve) {
      var w = null, done = false, timer = 0, watch = 0;
      function finish(r) {
        if (done) return;
        done = true;
        clearTimeout(timer); clearInterval(watch);
        if (w) { w.onmessage = null; w.onerror = null; try { w.terminate(); } catch (e) { /* gone */ } }
        resolve(r);
      }
      if (cancelled) watch = setInterval(function () { if (cancelled()) finish({ ok: false, cancelled: true, why: HO.CANCELLED }); }, 50);
      try { w = new Worker(A.worker, { name: "ocean-probe" }); }
      catch (err) { finish({ ok: false, why: "this page could not start a worker to try it in (" + (err && err.message || err) + ")" }); return; }
      w.onmessage = function (e) {
        var m = e.data || {};
        if (m.type !== "probe") return;
        if (m.data) img.data = m.data;
        finish(m);
      };
      w.onerror = function (ev) {
        if (ev && ev.preventDefault) ev.preventDefault();
        finish({ ok: false, why: "its test run failed (" + (ev && ev.message || "the worker failed") + ")" });
      };
      timer = setTimeout(function () { finish({ ok: false, why: "its test run did not finish one step in " + PROBE_MS / 1000 + " s" }); }, PROBE_MS);
      var data = img.data;
      if (data.byteOffset || data.byteLength !== data.buffer.byteLength) data = data.slice();   /* (only its own bytes travel) */
      img.data = null;
      try {
        w.postMessage({ cmd: "probe", id: 1, js: moduleUrls.js, wasm: moduleUrls.wasm, handoff: moduleUrls.handoff,
                        data: data, bytes: img.bytes, expect: HO.worldExpect(header) }, [data.buffer]);
      } catch (err) { finish({ ok: false, why: "its test run could not start (" + (err && err.message || err) + ")" }); }
    });
  }
  /* What From a file does with a saved world (file: a Blob): read and
   * checked part by part, tried, then opened through the door, or refused
   * with the reason (another engine build: its setup offered instead).
   * req.stale(): something newer came meanwhile (another file, a stage,
   * Discard, a start): what this read finds is dropped, a refusal too
   * (review of #44, finding 7: it would say so over the newer answer),
   * and said so only while this is the latest file (req.latest()). opener:
   * the card, when the keyboard pressed it (the question's focus). */
  /* What opening a saved world holds at once, at its peak (bytes): the run's
   * memory L, Turbo's copy of it T while a Turbo worker lives (it is
   * terminated when it hands the world back), the stored bytes S, the
   * gzip body B while it unpacks, a copy of S for its checksum (WebCrypto
   * takes one), the test run's module F (the image's full length) with S
   * in it, then the run's undo (at most L) beside the grown module and S;
   * and an open already queued (its S). The largest of the three phases. */
  function openNeeds(h) {
    var im = h.image, L = heap().byteLength, F = im.bytes, S = im.stored, B = im.body === "gzip" ? im.bodyBytes : 0;
    var T = turboWorker ? Math.max(L, turboStats && turboStats.memBytes || 0) : 0;
    var q = pendingStart && pendingStart.plan.op === "open" && pendingStart.plan.world.data ? pendingStart.plan.world.data.byteLength : 0;
    return q + Math.max(L + T + B + 2 * S, L + T + S + F, Math.max(L, F) + S + L);
  }
  /* One saved world read, unpacked and tried at a time (review of #44,
   * round 2, finding 1; round 3, finding 2): a read takes its turn before
   * any of its body is read (one waiting holds no body), is checked against
   * the budget again when its turn comes (the run may have grown, or Turbo
   * started, meanwhile), keeps the turn through its test run, and gives it
   * back whatever happens; a superseded one stops at once (at its turn,
   * its next part read, its unpacking's next chunk; its test run
   * terminated), so a newer file waits a part, a chunk or a moment, never
   * for an old file's work. */
  var heavy = Promise.resolve();
  function heavyTurn() {   /* a Promise of release() */
    var release, mine = new Promise(function (r) { release = r; }), before = heavy;
    heavy = before.then(function () { return mine; });
    return before.then(function () { return release; });
  }
  var worldToken = 0;
  function openWorldFile(file, name, req, opener) {
    if (!pinned) { showError("Opening a saved world needs the engine this page runs (it has none of its own here)."); return Promise.resolve(); }
    var header = null, dev = deviceBudget(), release = null;
    errEl.textContent = "Reading " + (name || "the saved world") + "…"; errEl.className = "";   /* (no toast: the answer follows) */
    return HO.readWorld(HO.blobSource(file), worldLimitsHere()).then(function (r) {
      if (req.stale()) return null;
      header = r.header;
      var bad = HO.headerProblem(header, RULES);
      if (bad) throw new Error("That world file is damaged: " + bad + ".");
      if (header.engine.wasmSha256 !== pinned.sha256) { offerSetup(header, name, pinned.sha256, opener); return null; }
      /* this device's budget, before the body is read (review of #44, round 2, finding 1), and again when its turn comes */
      var need = openNeeds(header);
      if (need > dev.budget) throw new Error(overBudget(header, need, dev));
      return r.body(req.stale, function () {
        return heavyTurn().then(function (rel) {
          release = rel;
          if (req.stale()) return;   /* (body() stops it) */
          var now = openNeeds(header);
          if (now > dev.budget) throw new Error(overBudget(header, now, dev));
        });
      });
    }).then(function (img) {
      if (!img || req.stale()) return null;
      errEl.textContent = "Trying " + (name || "the saved world") + " in a test run…"; errEl.className = "";
      return probeWorld(img, header, req.stale).then(function (rep) {
        if (!rep.ok) throw new Error("That saved world failed its test run (" + rep.why + "), so it was not opened. Nothing changed.");
        img.at = rep.at;
        return img;
      });
    }).then(function (img) {
      if (req.stale()) { worldOvertaken(req); return; }
      if (!img) return;
      var p = header.picked;
      var world = { header: header, data: img.data, bytes: img.bytes, at: img.at, name: name || "", token: ++worldToken,
                    initArgs: JSON.parse(JSON.stringify(header.start)), runCfg: JSON.parse(JSON.stringify(header.runCfg)),
                    picked: p ? { id: p.id, follow: p.follow, family: p.family === undefined ? null : p.family, x: p.x || 0, y: p.y || 0, d: p.d || 0 } : null };
      var plan = { source: "world", op: "open", url: true, world: world,
                   failed: "That saved world couldn't open: ",
                   done: function () { worldOpened(world); } };
      clearError();
      var how = fenced(requestStart)(plan);   /* (an operation of its own, after the read: fenced as a press is) */
      if (how === "asked" && opener) { asking.opener = opener; el("startconfirm").focus(); }
    }).catch(function (err) {
      if (req.stale()) { worldOvertaken(req); return; }
      showError(String(err && err.message || err));
    }).then(function () { if (release) release(); });
  }
  function overBudget(h, need, dev) {
    return "Opening that saved world (" + fmtMB(h.image.bytes) + " of memory) would hold about " + fmtMB(need) + " at once with your run" +
           (turboWorker ? " and Turbo's copy of it" : "") + ", more than this page lets itself use on this device (" + fmtMB(dev.budget) +
           "), so it was not read. " + (turboWorker ? "Stop Turbo first, or start a smaller world." : "Start a smaller world first (a reload starts the engine small).");
  }
  function worldOvertaken(req) {
    if (req.latest()) showNote("The saved world was not opened: something newer started or was picked while it was read.");
  }
  /* Opened: the fish it had picked (and followed), as Turbo's hand-back
   * picks it up again (restoreAfterTurbo's rule): itself, or, gone (it can
   * be: a Save world during Turbo records the fish Turbo will pick up
   * again, which may have died there before the copy), the nearest of its
   * family line, or none; said so. The charts start a fresh history here. */
  function worldOpened(world) {
    var p = world.picked, said = "";
    if (p) {
      var s = fresh(lastS), id = indexOfId(s, p.id) >= 0 ? p.id : nearestOfFamily(s, p);
      if (id === null) said = " Fish #" + p.id + ", " + (p.follow ? "followed" : "picked") + " when it was saved, is not in it (it died during Turbo before the save), " +
                              "nor is any of its family line: nothing " + (p.follow ? "followed" : "picked") + ".";
      else {
        select(id);
        if (p.follow && scene) { wantFollow = true; scene.setFollow(true); }
        if (id !== p.id) said = " Fish #" + p.id + " is not in it (it died during Turbo before the save): " + (p.follow ? "following" : "showing") + " #" + id +
                                ", the nearest of its family line.";
      }
    }
    if (dash() && dash().origin) dash().origin("the saved world opened at frame " + fmtInt(world.header.frame));
    showNote("Opened " + worldText(world) + ": it carries on from where it was saved (its charts start afresh). Replay starts its setup again from frame 0." + said);
  }
  /* a world from another engine build: its fish can't come here; its setup,
   * from its header (whose checksum the read has checked; its image is not
   * read), can (staged, as From a file stages one) */
  function offerSetup(h, name, mine, opener) {
    var theirs = h.engine && h.engine.wasmSha256;
    showAsk("That world was saved by another engine build (" + shortId(theirs) + "; this page runs " + shortId(mine) + "), so its fish can't come back " +
            "here. Its setup can: seed " + h.start.seed + ", " + h.start.width + " × " + h.start.height + ", " + fmtInt(h.start.population) +
            " fish, from its start (frame 0), staged for Start (read from the file's header, which its checksum confirms).", "Use its setup", "Not now");
    asking = { replace: function () { loadSetup(JSON.stringify(h.setup), (name ? name + ", " : "") + "its setup"); }, noNote: "The saved world was not opened." };
    if (opener) { asking.opener = opener; el("startconfirm").focus(); }
  }
  /* Load setup: that world from its start, at its size, exactly as saved
   * (importWorld: a value the engine refuses is reported, and nothing
   * changes). A setup without a size takes this screen's. */
  function loadSetup(text, name) {
    if (!M) return;
    if (String(text).slice(0, HO.WORLD.MAGIC.length) === HO.WORLD.MAGIC) {   /* (From a file tells them apart before this) */
      showError("That file is a saved world (Save world makes those), not a setup."); return;
    }
    var s, pf;
    try { pf = HO.parseFirst(text); s = pf.value; } catch (e) { showError("That file is not JSON: " + e.message); return; }
    /* a repeated key, as for ?cfg=: the first occurrence counts, every one is
     * checked (a setup's own keys here, its config's here and by oc_init); a
     * second config would be a second setup, so it is refused */
    var top = pf.repeats.filter(function (r) { return !r.path.length; });
    var cfgRepeats = pf.repeats.filter(function (r) { return r.path.length === 1 && r.path[0] === "config"; });
    if (top.some(function (r) { return r.key === "config"; })) { showError("That setup has more than one config; a setup has one."); return; }
    if (!s || s.format !== "evo_ocean_setup" || !s.config || typeof s.config !== "object" || Array.isArray(s.config) ||
        top.some(function (r) { return r.key === "format" && r.value !== "evo_ocean_setup"; })) {
      showError("That file is not an Ocean setup (Save setup makes one)."); return;
    }
    var version = s.version === undefined ? 1 : s.version;
    if (version !== 1 && version !== SETUP_VERSION) {
      showError("That setup is version " + JSON.stringify(s.version) + "; this page reads versions 1 and " + SETUP_VERSION + "."); return;
    }
    var bad = [];
    function arg(name, def, ok) {
      top.forEach(function (r) { if (r.key === name && r.value !== null && !ok(r.value)) bad.push(name + " " + JSON.stringify(r.value)); });
      if (s[name] === undefined || s[name] === null) return def;
      if (!ok(s[name])) bad.push(name + " " + JSON.stringify(s[name]));
      return s[name];
    }
    function whole(lo, hi) { return function (v) { return Number.isInteger(v) && v >= lo && v <= hi; }; }
    var seed = arg("seed", KEYS.seed[0], whole(0, 4294967295)), pop = arg("population", KEYS.population[0], whole(LIM.population[0], LIM.population[1]));
    var depth = arg("depth", KEYS.depth[0], depthOk);
    var fw = fittedWorld();
    var w = arg("width", fw[0], whole(LIM.side[0], LIM.side[1])), h = arg("height", fw[1], whole(LIM.side[0], LIM.side[1]));
    /* the sides: version 2 says (its own field, a bool, written as the
     * config's first "walls", never deleted: a later one in its config still
     * goes to oc_init to be checked, and would run if the first were gone);
     * version 1 is from before walls, so it wraps unless its config itself
     * asks for them, which oc_init checks as any Ocean switch (true / 1 on) */
    var walls = version === 1 ? null : arg("walls", null, function (v) { return typeof v === "boolean"; });
    if (version !== 1 && walls === null) bad.push("walls (missing: a version-2 setup says true or false)");
    if (bad.length) { showError("That setup can't start: " + bad.join(", ") + " (whole numbers in range; walls true or false)."); return; }
    var config = Object.assign({}, s.config);
    if (version !== 1) config.walls = walls;
    clearError();
    /* staged, never started here (and never while Turbo runs: the next world
     * waits in the sheet, the running one goes on); Start starts it, as it
     * is (importPlan: oc_init sees the file's own values, repeats and keys
     * the sheet has no field for), unless the sheet is edited first */
    var plan = importPlan("file", seed, pop, depth, config, undefined, cfgRepeats, [w, h], true);
    var title = "the setup file" + (name ? " " + name : "");
    function stage() {
      stageDraft({ kind: "file", id: "file", title: "the setup file", plan: plan, seed: seed >>> 0,
                   summary: (name ? name + ": " : "") + "seed " + (seed >>> 0) + " · " + w + " × " + h + " × " + depth + " · " + pop + " fish" +
                            (config.walls === true || config.walls === 1 ? " · glass walls" : config.walls === false || config.walls === 0 ? " · wrapping sides" : "") },
        function () {
          setVal("seed", seed >>> 0); setVal("population", pop); setVal("depth", depth); setVal("width", w); setVal("height", h);
          cfgToForm(plan.imported);
        });
      el("randnote").textContent = "";
      showNote("Ready: " + title + ". Start replaces this run with it, from its start.");
    }
    var n = pendingDiff().length;
    if (n) askReplace("The setup file", n, stage); else stage();
  }
  /* What Start starts: a staged file as it is (with a new seed for Start
   * fresh) while its fields are untouched; edited, the file with the edited
   * fields only (editedFile); else the sheet (seed: Start fresh's, drawn
   * once per request). */
  function startPlan(seed) {
    var plan;
    if (draft && draft.plan && !pendingDiff().length) {
      var fp = draft.plan, s0 = seed === undefined ? draft.seed : seed;
      plan = { source: fp.source, op: "init", url: true, imported: fp.imported,
               build: function () { var b = fp.build(); b.seed = s0; return b; } };
      plan.failed = "That setup was refused: ";
      plan.done = function () { showNote("Setup loaded: seed " + initArgs.seed + ", " + W + " × " + H + ", replaying from its start."); };
      return plan;
    }
    if (draft && draft.plan) {
      plan = editedFile(draft.plan, seed === undefined ? null : seed, draft.seed);
      plan.failed = "That setup was refused: ";
      plan.done = function () { showNote("Setup loaded (edited): seed " + initArgs.seed + ", " + W + " × " + H + "."); };
      return plan;
    }
    return formPlan(draft ? draft.kind : "start", seed);
  }
  /* A staged setup file with some fields edited: the file's own recipe
   * (fp.build: its values as written, a repeated key's later occurrences,
   * the keys the sheet has no field for) with only the edited fields
   * (pendingDiff against the file as staged) replaced by the sheet's. An
   * untouched value the sheet can't hold (2 for a switch, 1e400) or a later
   * occurrence of an untouched key still reaches oc_init, which checks it,
   * as it does when the file starts untouched; an edited key's value (and
   * its later occurrences: replaced) is the sheet's, checked as the sheet's
   * are (sizeProblem). seed: Start fresh's (null: the sheet's if edited,
   * else the file's, fileSeed). */
  function editedFile(fp, seed, fileSeed) {
    function resolve() {
      var b = fp.build(), on = {}, mine = {}, cfg = Object.assign({}, b.cfg);
      pendingDiff().forEach(function (k) { on[k] = true; });
      var arg = function (k, v) { return on[k] ? argVal(k) : v; };
      Object.keys(on).forEach(function (k) { if (!ARGS[k]) mine[k] = cfg[k] = getVal(k); });
      Object.keys(extraCfg).forEach(function (k) { if (!(k in cfg)) cfg[k] = extraCfg[k]; });   /* (a key the E1 water added without a field) */
      return { seed: seed !== null ? seed : arg("seed", fileSeed), population: arg("population", b.population), depth: arg("depth", b.depth),
               width: arg("width", b.size[0]), height: arg("height", b.size[1]), cfg: cfg, mine: mine,
               repeats: (b.repeats || []).filter(function (r) { return !on[r.key]; }) };
    }
    return { source: fp.source, op: "init", url: true, imported: true,
             check: function () { var r = resolve(); return sizeProblem({ seed: r.seed, population: r.population, depth: r.depth, width: r.width, height: r.height, cfg: r.mine }); },
             build: function () { var r = resolve(); return { seed: r.seed, population: r.population, depth: r.depth, size: [r.width, r.height], cfg: r.cfg, repeats: r.repeats }; } };
  }

  /* ---------------- per-frame data ---------------- */
  /* Called right after oc_sync: views over this sync's buffers only. */
  function snapshot() {
    var buf = heap();
    var n = M._oc_creature_count(), fc = M._oc_food_count(), pc = M._oc_predator_count();
    return {
      buf: buf, worldEpoch: worldEpoch, n: n, fc: fc, pc: pc, selIdx: -1,
      segs: new Float32Array(buf, M._oc_creature_segments(), n * 12),
      depth: new Float32Array(buf, M._oc_creature_depth(), n),
      ids: new Float64Array(buf, M._oc_creature_ids(), n),
      body: new Float32Array(buf, M._oc_body_params(), n * 2),
      colors: new Uint8Array(buf, M._oc_creature_colors(), n * 3),
      food: new Float32Array(buf, M._oc_food_xy(), fc * 2),
      foodDepth: new Float32Array(buf, M._oc_food_depth(), fc),
      preds: new Float32Array(buf, M._oc_predator_data(), pc * 3),
      predDepth: new Float32Array(buf, M._oc_predator_depth(), pc),
      stats: new Float64Array(buf, M._oc_stats(), statsLen),
      vz: HAS_VZ ? new Float32Array(buf, M._oc_creature_vz(), n) : null,
      app: appearanceView(buf, n),
      curActive: false, curGrid: null, curCols: 0, curRows: 0
    };
  }
  /* s again, if anything grew the memory since it was cut (an export that
   * allocates: the summary, the family lines, the fish card's, the wiring, a
   * name list, a C string): the same buffers (only oc_sync and a new world
   * rewrite them, and both cut a new snapshot), on the live memory */
  function fresh(s) {
    if (!s || s.buf === heap()) return s;   /* (the appearance rows: a view of this sync's too) */
    if (engineState !== "ok") return s;   /* (restarting or stopped: the last views, never the engine) */
    var pt = PROF.beginCpu();
    var t = snapshot();
    PROF.endCpu(SP.snapshot, pt);
    t.selIdx = s.selIdx;
    if (!HAS_VZ) t.vz = s.vz;   /* the estimate lives in JS */
    if (lastS === s) lastS = t;
    return t;
  }
  /* The appearance genome (oc_creature_appearance: 63 floats a fish, COSMETIC),
   * when this module exports it in a layout and laws web/ocean_appearance.js
   * knows, one row per fish of this sync; else null (the tank then draws the
   * family / brain colours). Views are made fresh after every sync. */
  function appearanceView(buf, n) {
    if (!HAS_APP || n <= 0 || M._oc_appearance_count() !== n) return null;
    var p = M._oc_creature_appearance();
    if (!p || (p & 3) || p + n * 63 * 4 > buf.byteLength) return null;
    return new Float32Array(buf, p, n * 63);
  }
  /* Without oc_creature_vz: each fish's pitch from how its depth changed over
   * the distance its head swam since the last frame, smoothed, keyed by id. */
  function vzBufs(cap) {
    return { n: 0, ids: new Float64Array(cap), x: new Float32Array(cap), y: new Float32Array(cap),
             d: new Float32Array(cap), vz: new Float32Array(cap) };
  }
  var estPrev = vzBufs(0), estNext = vzBufs(0);
  function vzEstimate(s, stepped) {
    var n = s.n, prev = estPrev, at = new Map();
    for (var j = 0; j < prev.n; j++) at.set(prev.ids[j], j);
    if (estNext.ids.length < n) estNext = vzBufs(Math.max(256, n * 2));
    var B = estNext;
    for (var c = 0; c < n; c++) {
      var id = s.ids[c], x = s.segs[12 * c], y = s.segs[12 * c + 1], d = s.depth[c], v = 0;
      var k = at.get(id);
      if (k !== undefined) {
        v = prev.vz[k];
        if (stepped) {
          var dx = x - prev.x[k], dy = y - prev.y[k];
          if (dx > W / 2) dx -= W; else if (dx < -W / 2) dx += W;
          if (dy > H / 2) dy -= H; else if (dy < -H / 2) dy += H;
          var h = Math.hypot(dx, dy);
          if (h > 0.05) v += (Math.max(-1.2, Math.min(1.2, (d - prev.d[k]) / h)) - v) * 0.25;
        }
      }
      B.ids[c] = id; B.x[c] = x; B.y[c] = y; B.d[c] = d; B.vz[c] = v;
    }
    B.n = n;
    estNext = estPrev; estPrev = B;
    return B.vz.subarray(0, n);
  }

  /* ---------------- state ---------------- */
  var scene = null, lastS = null;
  var paused = BENCH, stepOnce = false;
  var speedIdx = Math.max(0, SPEEDS.indexOf(Math.round(Math.max(1, Math.min(64, parseFloat(P.get("speed")) || 1)))));
  var stepMs = 0, lastSteps = 0;
  var selectedId = null, wantFollow = false, everSelected = false;
  var animT = 0, lastNow = 0;
  var fpsFrames = 0, fpsT = 0, fps = 0;
  var governorOn = !BENCH, colourBrain = false, colourMode = "family";
  var summary = null, summaryT = 0;   /* oc_summary, refreshed twice a second for the readout */
  function speed() { return SPEEDS[speedIdx]; }
  function stepsThisFrame() {
    var ask = speed();
    if (!governorOn || ask <= 1 || !(stepMs > 0)) return ask;
    return Math.max(1, Math.min(ask, Math.floor(STEP_BUDGET_MS / stepMs)));
  }
  function setPaused(on) {
    paused = on;
    var b = el("pausebtn");
    b.querySelector("use").setAttribute("href", paused ? "#i-play" : "#i-pause");
    b.setAttribute("aria-label", paused ? "play" : "pause");
    b.title = (paused ? "Play" : "Pause") + " (Space)";
    el("stepbtn").hidden = !paused;   /* one step: only while paused */
    paintRunState();
    dirtyHud = true;
  }
  function changeSpeed(d) {
    speedIdx = Math.max(0, Math.min(SPEEDS.length - 1, speedIdx + d));
    el("speedlabel").textContent = speed() + "×";
    dirtyHud = true;
  }
  /* Hold 60 fps may run fewer steps than asked: the label turns, and the
   * caption under it (#speedcap) says how many, on a touch screen too */
  function showSpeedCap() {
    var ask = speed(), ran = turboState === "live" && !paused && lastSteps > 0 ? lastSteps : ask, lab = el("speedlabel");
    lab.classList.toggle("capped", ran < ask);
    lab.title = ran < ask ? ask + "× asked; running " + ran + " steps per frame to hold 60 fps (View › Hold 60 fps)" : "steps per frame";
    el("speedcap").hidden = !(ran < ask);
    if (ran < ask) setTxt("speedcap", "runs " + ran);
  }
  function indexOfId(s, id) {
    if (id === null || !s) return -1;
    for (var i = 0; i < s.n; i++) if (s.ids[i] === id) return i;
    return -1;
  }
  function randomFish(s, notId) {
    if (!s || !s.n) return -1;
    var i = Math.floor(Math.random() * s.n);
    if (s.n > 1 && s.ids[i] === notId) i = (i + 1 + Math.floor(Math.random() * (s.n - 1))) % s.n;
    return i;
  }
  /* handover: a followed fish died and another takes its place (the frame
   * loop), not a fish the visitor picked */
  function select(id, handover) {
    var was = selectedId;
    selectedId = id;
    if (id !== null) { everSelected = true; hideCoach(); }   /* its card opens where the coach mark sits */
    if (id !== null && id !== was && !handover) { cardNewer = true; cardHeld = false; }   /* its card, over the live numbers (updateCard) */
    /* the capture, only into a running engine (Close, Esc and the tour let go of a fish while it is stopped or
     * restarting too: review of #44, round 3, finding 3; a restarted one gets it with its run, applyDisplaySwitches) */
    if ((was === null) !== (id === null) && M && engineState === "ok" && has("oc_set_capture")) M._oc_set_capture(id !== null ? 1 : 0);
    dirtyHud = true;
  }
  /* F: follow the selected fish; again (or with none): a random one */
  function follow() {
    if (turboState !== "live") { turboPictureHint(); return; }
    engineCall(function () {   /* (a stopped engine: says why; a trap: stops it once, from F, the console or the tour) */
      var s = fresh(lastS);
      if (!s || !s.n) return;
      var idx = !scene.following() ? indexOfId(s, selectedId) : -1;
      if (idx < 0) idx = randomFish(s, selectedId);
      select(s.ids[idx]);
      wantFollow = true;
      if (!scene.following()) scene.setFollow(true);
    }, undefined, "Following a fish");
  }
  function unfollow() {
    wantFollow = false;
    if (scene.following()) scene.setFollow(false);
  }
  function onFollowChange(on) {
    el("followbtn").setAttribute("aria-pressed", on ? "true" : "false");
    el("followbtn").title = on ? "Stop following (F or Esc)" : "Follow this fish (F)";
    if (!on) wantFollow = false;
    if (on) toast(coarseMQ.matches ? "Following. Drag to circle around it."
                                   : "Following. Drag or A / D to circle it, W / S to come closer or back off; Esc stops.");
    /* Light while following: on as the follow starts, back as it was when it ends */
    if (on) { lightBeforeFollow = lightNow; if (followLight) lightNow = true; }
    else lightNow = lightBeforeFollow;
    updateLight();
    updateKeysLegend();
  }

  /* ---- the keys legend (a wide screen with a mouse; ocean.html #keys) ----
   * One line for what is on screen now: the camera's keys (fly, or around the
   * followed fish), one step while paused, Stop in Turbo (no follow: the
   * picture waits for Turbo); ? opens Help, which has every key. */
  function updateKeysLegend() {
    var k = function (keys, what) { return "<span class='k'><kbd>" + keys.join("</kbd><kbd>") + "</kbd> " + what + "</span>"; };
    var live = turboState === "live", parts;
    if (live && scene && scene.following()) parts = [k(["W", "S"], "closer / farther"), k(["A", "D"], "circle"), k(["Esc"], "let go")];
    else parts = [k(["W", "A", "S", "D"], "fly"), live ? k(["F"], "follow a fish") : k(["Space"], "stop Turbo")];
    if (live && paused) parts.push(k(["."], "one step"));
    parts.push(k(["?"], "all keys"));
    setHtml("keys", parts.join(""));
  }

  /* ---- the flashlight (drawing only; scene.setFlashlight) ----
   * One light, on or off now: the dock's button, L and the View menu's
   * switch turn it on and off, and nothing else changes it but a follow. One
   * preference, "Light while following" (the View menu's switch, stored):
   * following a fish turns the light on, letting go puts it back as it was
   * (onFollowChange). L never writes the preference. */
  var followLight = store("evo_boids.ocean.followLight") !== "0", lightNow = false, lightBeforeFollow = false;
  function lightOn() { return lightNow; }
  function updateLight() {
    var on = lightNow;
    if (scene) scene.setFlashlight(on);
    var b = el("lightbtn");
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.title = (on ? "Flashlight on (L)" : "Flashlight (L)") + ": clear light where you look, in true colours";
    el("lightnow").checked = on;
  }
  function toggleLight() {
    lightNow = !lightNow;
    if (lightNow && !(scene && scene.following())) toast("Flashlight on: true colours where you look, without the water's tint.");
    updateLight();
  }

  /* ---- the View menu and Help: one popover at a time; ×, Esc, its key or a
   * press outside closes it. [popover, trigger, its first control] ---- */
  var POPS = { view: ["viewpop", "viewmenubtn", "lightnow"], help: ["helppop", "helpbtn", "tourbtn"] }, openPop = null, popOpener = null;
  /* A press by the keyboard (its focus ring showing) keeps the focus; a
   * pointer's lets it go, so Space goes back to pausing. */
  function pointerBlur(n) { if (!n.matches(":focus-visible")) n.blur(); }
  /* opener: the trigger, when the keyboard pressed it: the focus goes to the
   * popover's first control, and back to the trigger when the keyboard closes it */
  function setPop(name, opener) {
    openPop = POPS[name] ? name : null;
    popOpener = openPop && opener || null;
    Object.keys(POPS).forEach(function (n) {
      el(POPS[n][0]).hidden = n !== openPop;
      el(POPS[n][1]).setAttribute("aria-expanded", n === openPop ? "true" : "false");
    });
    document.body.classList.toggle("help-open", openPop === "help");
    if (openPop) {
      /* never under a layer above it: the charts, a narrow screen's settings sheet */
      if (dash() && dash().isOpen()) dash().close();
      if (!wideMQ.matches && drawerEl.classList.contains("open")) setDrawer(false);
      setStatPanel(false); hideCoach(); placePop();
      if (popOpener) el(POPS[openPop][2]).focus();
    }
  }
  function closePop(keyboard) {
    var back = popOpener;
    setPop(null);
    if (keyboard && back) back.focus();
  }
  function togglePop(name, opener, keyboard) { if (openPop === name) closePop(keyboard); else setPop(name, opener); }
  /* the View menu over its button, left of a wide screen's settings panel (a
   * phone: the screen's width, from the CSS) */
  function placePop() {
    var pop = el("viewpop");
    if (openPop !== "view" || innerWidth < 600) { pop.style.left = ""; return; }
    var r = el("viewmenubtn").getBoundingClientRect(), w = pop.offsetWidth;
    var right = wideMQ.matches && drawerEl.classList.contains("open") ? drawerEl.getBoundingClientRect().left : innerWidth;
    pop.style.left = Math.round(Math.max(10, Math.min(right - w - 10, r.left + r.width / 2 - w / 2))) + "px";
  }
  document.addEventListener("pointerdown", function (e) {
    if (openPop && !e.target.closest("#" + POPS[openPop][0] + ", #" + POPS[openPop][1])) setPop(null);
  });

  /* ---- a first visit: the tank, then one hint (load + 9 s, a fish), then
   * this small Turbo coach mark, after a minute or once generation 1 is
   * born (25 s at the least), on a screen with nothing else open (no fish
   * card, popover, live numbers, settings, charts or tour) in a tab in view.
   * Once per visitor; not after Turbo has been used or its card seen (Help's
   * "What is Turbo?" too); ?guide=0 none (the tests). ---- */
  var COACH_KEY = "evo_boids.ocean.turboHintSeen.v1", coachTimer = 0, coachHideT = 0;
  function coachDone() { return store(COACH_KEY) === "1" || store(window.EvoGuideConfig.introKey) === "1"; }
  function startCoach() {
    if (P.get("guide") === "0" || P.has("renderBench") || coachDone()) return;
    var t0 = performance.now();
    coachTimer = setInterval(function () {
      var t = (performance.now() - t0) / 1000, gen = summary ? summary[13] : 0;
      if (coachDone()) { clearInterval(coachTimer); return; }   /* Turbo used, or its card seen, meanwhile */
      if (!(t >= 60 || (gen >= 1 && t >= 25)) || turboState !== "live" || openPop || statOpen || selectedId !== null || document.hidden ||
          document.getElementById("guide") || drawerEl.classList.contains("open") || (dash() && dash().isOpen())) return;
      clearInterval(coachTimer);
      store(COACH_KEY, "1");
      el("coach").hidden = false;
      placeCoach();
      coachHideT = setTimeout(hideCoach, 25000);
    }, 1000);
  }
  function hideCoach() { el("coach").hidden = true; clearTimeout(coachHideT); }
  function placeCoach() {   /* above the Turbo button, its arrow on it */
    var c = el("coach");
    if (c.hidden) return;
    var r = el("turbobtn").getBoundingClientRect(), w = c.offsetWidth, mid = r.left + r.width / 2;
    var left = Math.round(Math.max(10, Math.min(innerWidth - w - 10, mid - w / 2)));
    c.style.left = left + "px";
    c.style.setProperty("--arrow-x", Math.round(mid - left) + "px");
  }

  /* ---------------- the readout and the stat panel ---------------- */
  var dirtyHud = true, hudT = 0, histRows = [];
  function buildHist() {
    var box = el("hist");
    for (var i = 0; i < 8; i++) {
      var row = document.createElement("div"); row.className = "row";
      var lab = document.createElement("span");
      var track = document.createElement("div"); track.className = "track";
      var bar = document.createElement("div"); bar.className = "bar";
      var t = i / 7;
      bar.style.background = "oklch(" + (0.84 - 0.30 * t).toFixed(3) + " " + (0.15 - 0.04 * t).toFixed(3) + " " + (150 + 90 * t).toFixed(0) + ")";
      var pct = document.createElement("b");
      track.appendChild(bar); row.appendChild(lab); row.appendChild(track); row.appendChild(pct);
      box.appendChild(row);
      histRows.push({ lab: lab, bar: bar, pct: pct });
    }
  }
  function labelHist() {
    for (var i = 0; i < 8; i++) histRows[i].lab.textContent = Math.round(D * i / 8);
    histRows[0].lab.title = "surface";
  }
  /* births / deaths per simulated second over a sliding window (the counters
   * are cumulative; a drop means a new world) */
  var rates = {
    q: [],
    reset: function () { this.q.length = 0; },
    push: function (frame, b, d) {
      var q = this.q, last = q[q.length - 1];
      if (last && (frame < last.f || b < last.b)) q.length = 0;
      if (!last || frame !== last.f) q.push({ f: frame, b: b, d: d });
      while (q.length > 2 && q[q.length - 1].f - q[0].f > 6000) q.shift();
    },
    perSec: function (key) {
      var q = this.q;
      if (q.length < 2) return null;
      var a = q[0], b = q[q.length - 1], df = (b.f - a.f) * DT;
      return df > 0 ? (b[key] - a[key]) / df : null;
    }
  };
  function fmtInt(v) { return Math.round(v).toLocaleString("en-US"); }
  function fmtTime(s) { s = Math.max(0, Math.round(s)); var m = Math.floor(s / 60); return m ? m + " min " + (s % 60) + " s" : s + " s"; }
  function setHtml(id, html) { var e = el(id); if (e && e._v !== html) { e._v = html; e.innerHTML = html; } }
  function setTxt(id, t) { var e = el(id); if (e && e._v !== t) { e._v = t; e.textContent = t; } }
  var statOpen = false;
  /* The live numbers and a fish card where they overlap (a phone; a card
   * flipped to the top; its brain open): the newer shows (updateCard). The
   * numbers opened over a card hide it until they close (cardHeld), its
   * fish still selected, followed and lit; a fish picked while they are open
   * (cardNewer) closes them. */
  var cardNewer = false, cardHeld = false;
  function setStatPanel(open) {
    statOpen = open;
    cardNewer = false; cardHeld = false;
    el("statpanel").hidden = !open;
    el("readout").setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("stat-open", open);   /* the Fit button, where it would cover its first rows, waits (ocean.html) */
    /* opening, as a popover does (setPop): never under the charts or a narrow
     * screen's settings sheet; no popover over it; the coach mark goes */
    if (open) {
      if (dash() && dash().isOpen()) dash().close();
      if (!wideMQ.matches && drawerEl.classList.contains("open")) setDrawer(false);
      setPop(null); hideCoach();
    }
    dirtyHud = true;
  }
  function updateHud(s, now) {
    if (!dirtyHud && now - hudT < 500) return;
    dirtyHud = false; hudT = now;
    /* while Turbo owns the world, its numbers: the worker's latest stats and
     * summary (turboView); this page's copy is the world as Turbo took it */
    var tv = turboState !== "live" ? turboView : null;
    if (!tv && has("oc_summary") && (!summary || now - summaryT > 450)) {
      summary = HO.f64(M, M._oc_summary(), M._oc_summary_len());   /* it allocates: the views after it */
      summaryT = now;
      s = fresh(s);
    }
    var st = tv ? tv.st : s.stats, su = tv ? tv.su : summary, g = function (k) { return STATS[k] < st.length ? st[STATS[k]] : NaN; };
    var nFish = tv ? g("pop") : s.n, nFood = tv ? su[0] : s.fc, nPred = tv ? su[1] : s.pc;
    var frame = g("frame");
    rates.push(frame, g("births"), g("deaths"));
    setTxt("ro-fish", fmtInt(nFish));
    setTxt("ro-gen", su ? String(Math.round(su[13])) : "–");
    setTxt("ro-depth", g("depthMean").toFixed(0));
    setTxt("ro-fps", String(fps));
    el("ro-fps").className = "num" + (fps && fps < 45 ? " warn" : "");
    updateKeysLegend(); showSpeedCap();
    if (!statOpen) return;
    var rb = rates.perSec("b"), rd = rates.perSec("d");
    var rows = [
      ["fish", fmtInt(nFish)],
      ["food", fmtInt(nFood)],
      ["predators", String(nPred)],
      ["time", fmtTime(frame * DT) + " <small>· frame " + fmtInt(frame) + "</small>"],
      ["seed", initArgs ? String(initArgs.seed) : "–"],
      ["births", fmtInt(g("births")) + (rb !== null ? " <small>· " + rb.toFixed(1) + "/s</small>" : "")],
      ["deaths", fmtInt(g("deaths")) + (rd !== null ? " <small>· " + rd.toFixed(1) + "/s</small>" : "")],
      ["founders added", fmtInt(g("reseeds"))]
    ];
    if (su) {
      rows.push(["died", "<small>starved </small>" + fmtInt(su[3]) + "<small> · old </small>" + fmtInt(su[4]) + "<small> · caught </small>" + fmtInt(su[2])]);
      rows.push(["generation", su[12].toFixed(1) + " <small>avg · " + Math.round(su[13]) + " max</small>"]);
      rows.push(["family lines", fmtInt(su[19])]);
      rows.push(["neutral depth", (su[14] * D).toFixed(0) + " <small>± " + (su[15] * D).toFixed(0) + "</small>"]);
    }
    rows.push(["depth", g("depthMean").toFixed(0) + " ± " + g("depthSd").toFixed(0) + " <small>of " + D.toFixed(0) + "</small>"]);
    var ask = speed(), ran = paused ? ask : lastSteps;
    if (tv && turboStats) rows.push(["steps / s", fmtInt(turboStats.stepsPerSec) + " <small>· Turbo</small>"]);
    else rows.push(["steps / frame", ran + (ran !== ask ? "<small>/" + ask + "</small>" : "") + " <small>· " + fps + " fps</small>"]);
    setHtml("statlist", rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join(""));
    for (var i = 0; i < 8; i++) {
      var k = STATS.hist0 + i, v = k < st.length ? st[k] : 0;
      v = isFinite(v) ? v : 0;
      histRows[i].bar.style.width = Math.min(100, v * 200).toFixed(1) + "%";   /* full track = 50 % */
      histRows[i].pct.textContent = Math.round(v * 100) + "%";
    }
    var notes = [];
    if (paused) notes.push("Paused. Space or ▶ runs it; . steps once.");
    if (turboState !== "live") notes.push(tv ? "Turbo is running: these are its numbers; the picture waits for it." : "Turbo is running: this picture waits for it.");
    if (scene && scene.following()) notes.push("Following a fish" + (lightOn() ? ", with the flashlight on." : "."));
    setTxt("statnotes", notes.join(" "));
  }

  /* ---------------- the fish card ---------------- */
  var cardEl = el("fishcard"), inetCanvas = el("inetc"), inetCtx = inetCanvas.getContext("2d");
  var portraitEl = el("iportrait"), portraitCtx = portraitEl.getContext("2d");
  var cardExpanded = window.innerWidth >= 600, cardCache = {}, cardFor = null, cardFlip = false;
  el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
  var sensorNames = null, actionNames = null, netNodes = [], netHover = -1, uiFont = "";
  function prettyName(n) { return String(n).replace(/_/g, " ").toLowerCase(); }
  function brainShape() {
    if (!sensorNames) {
      sensorNames = has("oc_sensor_names") ? cString(M._oc_sensor_names()).split(",").map(prettyName) : [];
      actionNames = has("oc_action_names") ? cString(M._oc_action_names()).split(",").map(prettyName) : [];
    }
    return { nS: has("oc_num_senses") ? M._oc_num_senses() : sensorNames.length,
             nH: has("oc_num_hidden") ? M._oc_num_hidden() : 12,
             nA: has("oc_num_actions") ? M._oc_num_actions() : actionNames.length };
  }
  function cardText(id, v) { if (cardCache[id] !== v) { cardCache[id] = v; el(id).textContent = v; } }
  function setBar(id, f, tick) {
    f = Math.max(0, Math.min(1, f));
    var key = f.toFixed(3) + "|" + (tick === undefined ? "" : tick.toFixed(3));
    if (cardCache[id + "bar"] === key) return;
    cardCache[id + "bar"] = key;
    var bar = el(id);
    bar.firstElementChild.style.transform = "scaleX(" + f.toFixed(3) + ")";
    var t = bar.querySelector(".tick");
    if (t) t.style.left = "calc(" + ((tick || 0) * 100).toFixed(1) + "% - 1px)";
  }
  function showCard() {
    cardEl.hidden = false;
    document.body.classList.add("card-open");
    cardEl.classList.toggle("expanded", cardExpanded);
    el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    cardCache = {};
  }
  function hideCard() {
    if (cardEl.hidden) return;
    cardEl.hidden = true;
    cardFor = null; netHover = -1; cardFlip = false;
    cardEl.classList.remove("flip");
    document.body.classList.remove("card-open");
  }
  function placeCard(fx, fy) {
    var r = cardEl.getBoundingClientRect(), m = 24;
    if (fx < r.left - m || fx > r.right + m || fy < r.top - m || fy > r.bottom + m) return;
    var flip = window.innerWidth < 600 ? fy > window.innerHeight / 2 : fx > window.innerWidth / 2;
    if (flip === cardFlip) return;
    cardFlip = flip;
    cardEl.classList.toggle("flip", flip);
  }
  function drawPortrait(rgb, size, elong) {
    var dpr = window.devicePixelRatio || 1, w = 56, h = 40;
    if (portraitEl.width !== w * dpr) { portraitEl.width = w * dpr; portraitEl.height = h * dpr; }
    var g = portraitCtx;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    var k = 3.0 * bodyScale(size), len = 1 + 0.35 * Math.tanh(4 * (elong - 1));
    g.translate(w / 2 + 4, h / 2);
    g.scale(len, 1);
    g.fillStyle = "rgb(" + rgb.join(",") + ")";
    g.beginPath();
    g.moveTo(-9 * k / 1.2, 0);
    g.bezierCurveTo(-7 * k / 1.2, -4.2 * k / 1.2, 2, -4.4 * k / 1.2, 6, -1.4);
    g.lineTo(11, -5.5); g.lineTo(9.5, 0); g.lineTo(11, 5.5); g.lineTo(6, 1.4);
    g.bezierCurveTo(2, 4.4 * k / 1.2, -7 * k / 1.2, 4.2 * k / 1.2, -9 * k / 1.2, 0);
    g.fill();
    g.fillStyle = "rgba(4,14,15,0.9)";
    g.beginPath(); g.arc(-6.2 * k / 1.2, -1.2, 1.1, 0, Math.PI * 2); g.fill();
    g.setTransform(1, 0, 0, 1, 0, 0);
  }
  /* The card's swatch: the fish's skin pattern on its flank (unlit, from its
   * appearance genes; web/ocean_appearance.js), when the module exports it. */
  var swatchEl = el("iswatch");
  function drawSwatch(s, idx, size, elong) {
    var EA = window.EvoAppearance;
    if (!swatchEl || !EA || !s.app) { if (swatchEl) swatchEl.hidden = true; return; }
    var W = 96, H = 24, row = s.app.subarray(63 * idx, 63 * idx + 63);
    swatchEl.width = W; swatchEl.height = H;
    var ctx = swatchEl.getContext("2d");
    ctx.putImageData(new ImageData(EA.flankImage(row, EA.lambdaOf(size, elong), W, H), W, H), 0, 0);
    swatchEl.hidden = false;
  }
  /* oc_inspect(idx) right after the sync: its numbers, then the card */
  function inspect(idx) {
    if (!has("oc_inspect")) return null;
    var sh = brainShape();   /* first: the name lists allocate (once) */
    if (!M._oc_inspect(idx)) return null;
    var buf = heap(), nc = M._oc_inspect_conn_count();   /* after oc_inspect, which allocates */
    return {
      info: new Float64Array(buf, M._oc_inspect_info(), M._oc_inspect_len()),
      sensors: new Float32Array(buf, M._oc_inspect_sensors(), sh.nS),
      hidden: new Float32Array(buf, M._oc_inspect_hidden(), sh.nH),
      actions: new Float32Array(buf, M._oc_inspect_actions(), sh.nA),
      connCount: nc, conns: new Float32Array(buf, M._oc_inspect_conns(), nc * 5), shape: sh
    };
  }
  function overlap(a, b) {
    return a.width > 0 && a.height > 0 && b.width > 0 && b.height > 0 &&
           a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  }
  function updateCard(s) {
    if (cardHeld && statOpen) { hideCard(); return s; }   /* under the live numbers: the fish stays selected */
    var idx = s.selIdx, f = idx >= 0 && turboState === "live" ? inspect(idx) : null;
    if (!f) { hideCard(); return s; }
    s = fresh(s);   /* oc_inspect may have grown the memory */
    if (cardEl.hidden) showCard();
    var p = scene.project(s, idx);
    if (p) placeCard(p.x, p.y);
    if (statOpen && overlap(cardEl.getBoundingClientRect(), el("statpanel").getBoundingClientRect())) {
      if (cardNewer) setStatPanel(false);   /* a fish picked over the numbers: its card */
      else { cardHeld = true; hideCard(); return s; }   /* the numbers opened over the card: they */
    }
    var info = f.info, id = Math.round(info[0]);
    var rgb = [s.colors[3 * idx], s.colors[3 * idx + 1], s.colors[3 * idx + 2]];
    var pkey = id + "|" + rgb.join() + "|" + info[4].toFixed(2) + "|" + info[5].toFixed(2);
    if (cardFor !== pkey) { cardFor = pkey; drawPortrait(rgb, info[4], info[5]); drawSwatch(s, idx, info[4], info[5]); }
    cardText("ititle", "Fish #" + id);
    cardText("isub", "Generation " + Math.round(info[6]) + " · family #" + Math.round(info[7]) + " · " + Math.round(info[11]) + " genes" +
             (cfgVal("bodyModel") ? " · body " + info[4].toFixed(2) + " × " + info[5].toFixed(2) : ""));
    var reproE = cfgVal("reproEnergy"), maxAge = cfgVal("maxAge"), maxSpd = cfgVal("maxSpeed"), pitchMax = cfgVal("pitchMax");
    cardText("ienergyv", info[2].toFixed(1));
    setBar("ienergy", info[2] / (reproE * 2), 0.5);
    el("ienergy").title = info[2] >= reproE ? "enough energy to breed" : "needs " + reproE + " to breed";
    cardText("iagev", Math.round(info[3]) + " s");
    setBar("iage", info[3] / maxAge);
    cardText("ispeedv", String(Math.round(info[1])));
    setBar("ispeed", info[1] / maxSpd);
    cardText("idepthv", info[8].toFixed(0) + " of " + D.toFixed(0));
    setBar("idepth", info[8] / D, info[9]);
    el("idepth").title = "the tick: its neutral depth";
    cardText("ibuoyv", (info[9] * D).toFixed(0));
    setBar("ibuoy", info[9]);
    var deg = Math.atan(info[10]) * 180 / Math.PI;
    cardText("ipitchv", Math.abs(deg) < 0.5 ? "level" : Math.abs(deg).toFixed(0) + "° " + (deg > 0 ? "down" : "up"));
    setBar("ipitch", 0.5 + 0.5 * Math.max(-1, Math.min(1, info[10] / (pitchMax || 0.5))), 0.5);
    if (cardExpanded) drawBrain(f);
    return s;
  }
  function brainColor(v, a) {
    var m = Math.min(1, Math.abs(v));
    return v >= 0 ? "rgba(" + Math.round(70 + 130 * m) + "," + Math.round(90 + 150 * m) + "," + Math.round(60 + 10 * m) + "," + a + ")"
                  : "rgba(" + Math.round(80 + 175 * m) + "," + Math.round(90 + 20 * m) + "," + Math.round(70 + 10 * m) + "," + a + ")";
  }
  /* senses -> hidden -> actions (renderer.js drawBrain, the Ocean's shape) */
  function drawBrain(f) {
    var box = inetCanvas.parentNode, w = box.clientWidth, h = box.clientHeight;
    if (w < 60 || h < 60) return;
    var sh = f.shape, nS = sh.nS, nH = sh.nH, nA = sh.nA;
    var dpr = window.devicePixelRatio || 1, bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (inetCanvas.width !== bw) inetCanvas.width = bw;
    if (inetCanvas.height !== bh) inetCanvas.height = bh;
    var g = inetCtx, i;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    var wide = w > h * 1.15, pos = { sen: [], hid: [], act: [] }, m = 14;
    if (wide) {
      var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
      for (i = 0; i < nS; i++) pos.sen.push([m + (w - 2 * m) * i / (nS - 1), yIn]);
      for (i = 0; i < nH; i++) pos.hid.push([m + 18 + (w - 2 * m - 36) * i / (nH - 1), yHid]);
      for (i = 0; i < nA; i++) pos.act.push([m + 18 + (w - 2 * m - 36) * i / (nA - 1), yOut]);
    } else {
      var yTop = 26, yBot = h - 12, xS = 18, xA = w - 100, xH = (xS + xA) / 2;
      for (i = 0; i < nS; i++) pos.sen.push([xS, yTop + (yBot - yTop) * i / (nS - 1)]);
      for (i = 0; i < nH; i++) pos.hid.push([xH, yTop + (yBot - yTop) * i / (nH - 1)]);
      for (i = 0; i < nA; i++) pos.act.push([xA, yTop + (yBot - yTop) * i / (nA - 1)]);
    }
    var hoverKey = netHover >= 0 && netNodes[netHover] ? netNodes[netHover].kind + netNodes[netHover].i : null;
    for (var k = 0; k < f.connCount; k++) {
      var o = k * 5;
      var srcSen = f.conns[o] !== 0, srcNum = f.conns[o + 1] | 0, sinkAct = f.conns[o + 2] !== 0, sinkNum = f.conns[o + 3] | 0, wgt = f.conns[o + 4];
      var a = srcSen ? pos.sen[srcNum] : pos.hid[srcNum], b = sinkAct ? pos.act[sinkNum] : pos.hid[sinkNum];
      if (!a || !b) continue;
      var srcAct = srcSen ? f.sensors[srcNum] : f.hidden[srcNum];
      var mag = Math.min(1, Math.abs(wgt) * Math.abs(srcAct) * 1.5);
      var hl = hoverKey !== null && ((srcSen ? "Sense" : "Hidden neuron") + srcNum === hoverKey ||
                                     (sinkAct ? "Action" : "Hidden neuron") + sinkNum === hoverKey);
      g.strokeStyle = (wgt >= 0 ? "rgba(180,235,80," : "rgba(255,120,80,") + (hl ? 0.9 : (0.10 + 0.7 * mag)).toFixed(3) + ")";
      g.lineWidth = hl ? 2 : 0.8 + 1.6 * mag;
      g.beginPath();
      g.moveTo(a[0], a[1]);
      if (wide) g.bezierCurveTo(a[0], (a[1] + b[1]) / 2, b[0], (a[1] + b[1]) / 2, b[0], b[1]);
      else g.bezierCurveTo((a[0] + b[0]) / 2, a[1], (a[0] + b[0]) / 2, b[1], b[0], b[1]);
      g.stroke();
    }
    netNodes = [];
    function node(p, r, v, kind, idx) {
      g.fillStyle = brainColor(v, 1);
      g.beginPath(); g.arc(p[0], p[1], r, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "rgba(4,14,16,0.85)"; g.lineWidth = 1; g.stroke();
      netNodes.push({ x: p[0], y: p[1], kind: kind, i: idx, v: v });
    }
    var rs = Math.max(2, Math.min(3.2, (wide ? w : h) / nS * 0.36));
    for (i = 0; i < nS; i++) node(pos.sen[i], rs, f.sensors[i], "Sense", i);
    for (i = 0; i < nH; i++) node(pos.hid[i], 5, f.hidden[i], "Hidden neuron", i);
    for (i = 0; i < nA; i++) node(pos.act[i], 5.5, f.actions[i], "Action", i);
    if (netHover >= 0 && netNodes[netHover]) {
      var hn = netNodes[netHover];
      g.strokeStyle = "rgba(230,255,160,0.95)"; g.lineWidth = 2;
      g.beginPath(); g.arc(hn.x, hn.y, 8, 0, Math.PI * 2); g.stroke();
    }
    if (!uiFont) uiFont = getComputedStyle(document.body).fontFamily;
    g.font = "11px " + uiFont;
    function tag(text, x, y) {
      var tw = g.measureText(text).width;
      g.fillStyle = "rgba(15,39,39,0.92)"; g.fillRect(x - 3, y - 10, tw + 6, 14);
      g.fillStyle = "rgba(190,210,205,0.95)"; g.fillText(text, x, y);
    }
    g.fillStyle = "rgba(190,210,205,0.9)";
    if (wide) {
      tag("senses", m, 13);
      tag("hidden", m, (26 + h - 40) / 2 - 9);
      g.fillStyle = "rgba(190,210,205,0.9)";
      g.textAlign = "center";
      for (i = 0; i < nA; i++) g.fillText(ACTION_SHORT[i] || "", pos.act[i][0], h - 40 + (i % 2 ? 30 : 18));
      g.textAlign = "left";
    } else {
      g.fillText("senses", 6, 13);
      g.fillText("hidden", (18 + w - 100) / 2 - 18, 13);
      g.fillText("actions", w - 106, 13);
      for (i = 0; i < nA; i++) g.fillText(ACTION_LABELS[i] || "", pos.act[i][0] + 10, pos.act[i][1] + 4);
    }
    updateSenseLine();
  }
  var DEFAULT_SENSE = "Senses on one side, actions on the other. Lime links excite, orange ones inhibit; brighter = stronger right now. Tap a dot to name it.";
  function updateSenseLine() {
    if (netHover >= 0 && netNodes[netHover]) {
      var n = netNodes[netHover];
      var label = n.kind === "Sense" ? (sensorNames[n.i] || "sense " + (n.i + 1)) : n.kind === "Action" ? (ACTION_LABELS[n.i] || actionNames[n.i]) : "neuron " + (n.i + 1);
      var html = n.kind + ": <b></b> " + (n.v >= 0 ? "+" : "") + n.v.toFixed(2);
      if (cardCache.sense !== html + label) {
        cardCache.sense = html + label;
        el("isense").innerHTML = html;
        el("isense").querySelector("b").textContent = label;
      }
    } else if (cardCache.sense !== "default") {
      cardCache.sense = "default";
      el("isense").textContent = coarseMQ.matches ? DEFAULT_SENSE : DEFAULT_SENSE.replace("Tap", "Point at");
    }
  }
  function nearestNode(e) {
    var r = inetCanvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    var best = -1, bd = e.pointerType === "mouse" ? 100 : 400;
    netNodes.forEach(function (n, i) { var d = (n.x - x) * (n.x - x) + (n.y - y) * (n.y - y); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  inetCanvas.addEventListener("pointermove", function (e) { if (e.pointerType === "mouse") netHover = nearestNode(e); });
  inetCanvas.addEventListener("pointerdown", function (e) { if (e.pointerType !== "mouse") netHover = nearestNode(e); });
  inetCanvas.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") netHover = -1; });

  /* ---------------- the dashboards' recorder ---------------- */
  var sampleBucket = -1;
  function dash() { return window.EvoOceanDash || null; }
  /* one sample of this frame's synced world: the row the Turbo worker records
   * too (web/ocean_handoff.js row(): the stats copied before the summary and
   * the family lines allocate) */
  function takeSample(st) {
    if (!dash() || !has("oc_summary")) return;
    var every = dash().every(), b = Math.floor(st[1] / every);
    if (b === sampleBucket) return;
    sampleBucket = b;
    dash().push(HO.row(M, dash().famK, statsLen));
  }
  /* the Brains dashboard's wiring: this world's, or, while Turbo owns the
   * world, the worker's (turboWiring) */
  function wiringNow() {
    if (!M || !has("oc_wiring")) return null;
    if (turboState !== "live") return turboWiring();
    var sh = brainShape(), n = M._oc_wiring();   /* both allocate: the view after them */
    var data = new Float32Array(heap(), M._oc_wiring_data(), 2 * sh.nS * sh.nA);
    return { at: performance.now(), n: n, senses: sh.nS, actions: sh.nA,
             path: Array.prototype.slice.call(data, 0, sh.nS * sh.nA), direct: Array.prototype.slice.call(data, sh.nS * sh.nA),
             senseNames: cString(M._oc_sensor_names()).split(","), actionNames: cString(M._oc_action_names()).split(",") };
  }

  /* ---------------- TURBO (web/ocean_worker.js) ----------------
   * live -> entering -> turbo -> exiting -> live. The worker gets a copy of
   * this module's memory and hands its own back on Stop; meanwhile this page
   * keeps drawing the frozen world, dimmed (updateLocks), live settings go
   * to the worker, and the readout and dashboards show the worker's world
   * (its stats messages, its samples, the wiring it is asked for). */
  var turboState = "live", turboWorker = null, turboStats = null;
  /* What the dashboards read while Turbo owns the world, from the worker:
   * turboView {st, su}, its latest oc_stats / oc_summary (each stats message
   * brings them: the readout and the stat panel); turboWire, the Brains
   * panel's wiring, which the worker computes when asked (the panel asks
   * when its copy is 2 s old, and only while it shows), stamped when it
   * arrives here; wireAsked: a question is out (one at a time: an answer
   * held up behind a long chunk is not asked for again, so the questions
   * never pile up; the worker answers every one, {none} without a world).
   * Cleared at each start and hand-back: the page's own world is the source
   * again. */
  var turboView = null, turboWire = null, wireAsked = false;
  function turboWiring() {
    var w = turboWire;
    turboWire = null;
    if (w) return w;   /* the panel keeps it until it wants a fresh one */
    if (turboState === "turbo" && turboWorker && !wireAsked) {
      wireAsked = true;
      turboWorker.postMessage({ cmd: "wiring" });
    }
    return null;   /* nothing new yet: the panel keeps what it shows */
  }
  /* The page's mode, drawn from who owns the world (UI-4): Live or Paused
   * (the page), or Turbo, starting, running or stopping (the worker). Turbo
   * is a mode of the dock's time group: pause, step, speed and the Turbo
   * button give way to its strip (Stop, a sparkline of the fish, its
   * numbers); the watch group, the View menu, the camera and the charts keep
   * working on the waiting picture, which is dimmed (body.turbo-on, the tank
   * only). Where the dock is covered (a narrow screen's setup sheet, the
   * charts) a bar there has the same Stop. The run's state shows in the
   * readout (#runstate). (The name is the old one: it locked the controls.) */
  var RUNSTATE = { live: ["Live", "The world is running"], paused: ["Paused", "Paused: Space or ▶ runs it"],
                   entering: ["Starting Turbo", "Turbo is taking the world"], turbo: ["Turbo", "Turbo is running the world without drawing it"],
                   exiting: ["Stopping Turbo", "Turbo is handing the world back"] };
  function runState() { return turboState === "live" ? (paused ? "paused" : "live") : turboState; }
  function paintRunState() {
    var s = runState(), r = el("runstate");
    if (!r || r.dataset.s === s) return;
    r.dataset.s = s;
    r.title = RUNSTATE[s][1];
    var w = r.querySelector(".rs-word");
    if (w) w.textContent = RUNSTATE[s][0];
  }
  /* what waits for Turbo to stop (every start goes through requestStart, which stops it first; Save reads what was accepted) */
  var LOCK_IDS = [];
  function updateLocks() {
    var s = turboState, on = s !== "live";
    document.body.classList.toggle("turbo-on", on);
    var tb = el("turbobtn");
    tb.setAttribute("aria-pressed", on ? "true" : "false");
    tb.disabled = s === "entering" || s === "exiting";
    LOCK_IDS.forEach(function (id) { var b = el(id); if (b) b.classList.toggle("locked", on); });
    el("turbo-strip").hidden = !on;
    el("setup-turbo").hidden = !on;
    el("dash-turbo").hidden = !on;
    /* Stop; with a new world waiting for the hand-back, Cancel (that start, not the hand-back) */
    var can = s === "turbo" || (on && !!pendingStart);
    var word = pendingStart ? "Cancel" : s === "entering" ? "Starting…" : s === "exiting" ? "Stopping…" : "Stop";
    var stop = el("turboexit");
    stop.disabled = !can;
    stop.setAttribute("aria-label", pendingStart ? "cancel the new world" : s === "turbo" ? "stop Turbo" : word.toLowerCase());
    var sw = stop.querySelector(".ts-word");
    if (sw) sw.textContent = word;
    ["setup-turbo-stop", "dash-turbo-stop"].forEach(function (id) {
      var b = el(id);
      b.disabled = !can;
      b.textContent = pendingStart ? "Cancel the new world" : s === "turbo" ? "Stop Turbo" : s === "entering" ? "Starting…" : "Stopping…";
    });
    paintRunState();
    paintStart();
    if (on) paintTurbo();
    updateKeysLegend();
    dirtyHud = true;
  }
  /* the strip's numbers (and the bars'), from the worker's latest stats */
  var SPARK_N = 90, spark = [];
  function paintTurbo() {
    var t = turboStats, rate = t ? Math.round(t.stepsPerSec).toLocaleString("en-US") : "–";
    setTxt("ts-rate", rate); setTxt("st-rate", rate); setTxt("dt-rate", rate);
    setTxt("ts-steps", t ? t.totalSteps.toLocaleString("en-US") : "–");
    setTxt("ts-pop", t ? Math.round(t.pop).toLocaleString("en-US") : "–");
    setTxt("ts-gen", t && t.su ? String(Math.round(t.su[13])) : "–");
    drawSpark();
  }
  /* a bounded sparkline of the fish, from the stats Turbo sends anyway (no
   * extra steps, no extra messages) */
  function drawSpark() {
    var c = el("turbo-sparkline"), g = c && c.getContext ? c.getContext("2d") : null;
    if (!g) return;
    var dpr = window.devicePixelRatio || 1, w = 64, h = 24;
    if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (spark.length < 2) return;
    var lo = Infinity, hi = -Infinity;
    spark.forEach(function (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    if (hi - lo < 2) { hi += 1; lo -= 1; }
    g.beginPath();
    var n = spark.length, step = (w - 2) / (Math.max(n, 16) - 1);   /* the newest on the right; a short run spreads over a quarter or more */
    spark.forEach(function (v, i) {
      var x = w - 1 - (n - 1 - i) * step, y = h - 2 - (v - lo) / (hi - lo) * (h - 4);
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    });
    g.strokeStyle = "#ef8a5a"; g.lineWidth = 1.5; g.lineJoin = "round";
    g.stroke();
  }
  /* T, the Turbo button, the coach mark's Try Turbo: on, or off. With a new
   * world waiting for Turbo (Stop Turbo & start, while it starts or stops),
   * T cancels that start, as Stop, Space and the bars' Cancel do */
  function toggleTurbo() {
    if (pendingStart) stopTurbo();
    else if (turboState === "live") enterTurbo();
    else if (turboState === "turbo") stopTurbo();
    else turboWait();
  }
  /* Stop Turbo (the strip's ■, the bars', Space, T): the ordinary hand-back.
   * With a new world waiting for it (Stop Turbo & start), Stop cancels that
   * start, not the hand-back: the run comes back as after any Stop. */
  function stopTurbo() {
    if (pendingStart) {
      cancelPendingStart("The new world is cancelled: " + (turboState === "entering" ? "Turbo carries on." : "Turbo hands your run back as usual."));
      return;
    }
    if (turboState === "turbo") exitTurbo();
    else if (turboState !== "live") turboWait();
  }
  function turboWait() { showNote(turboState === "entering" ? "Turbo is starting: a moment." : "Turbo is handing the world back: a moment."); }
  /* a tap on the waiting picture, or F, while Turbo runs: never silently ignored */
  var turboHintT = -Infinity;
  function turboPictureHint() {
    var now = performance.now();
    if (now - turboHintT < 2500) return;
    turboHintT = now;
    toast("The picture waits while Turbo runs. Stop Turbo (Space) to pick or follow a fish.");
  }
  var turboEntryCfg = null;   /* runCfg when Turbo took the world */
  var turboEntryPaused = false;   /* and whether it was paused then: a start that fails leaves it so */
  function onTurboMessage(e) {   /* (fenced whole where it is attached: the hand-back reads the world it puts in, then picks its fish again) */
    /* only the worker this page runs now: a dropped one's late messages (it
     * was detached and terminated: dropWorker) never reach the world */
    if (this !== turboWorker) return;
    var msg = e.data || {};
    if (msg.type === "stats") {
      turboStats = msg;
      if (msg.st && msg.su) turboView = { st: msg.st, su: msg.su };
      spark.push(msg.pop);
      if (spark.length > SPARK_N) spark.shift();
      if (turboState === "entering") {
        turboState = "turbo"; usedTurbo = true;
        updateLocks(); flushHeld();
        if (pendingStart) exitTurbo();   /* Stop Turbo & start, asked while it was starting */
      }
      paintTurbo();
    } else if (msg.type === "wiring") {
      wireAsked = false;   /* answered: the next one may be asked */
      if (msg.none || turboState === "live" || engineState !== "ok") return;   /* no world there; it is back here, the page's own the source; or no engine to name them */
      brainShape();   /* the names: this page's module is the same build */
      turboWire = { at: performance.now(), n: msg.n, senses: msg.senses, actions: msg.actions, path: msg.path, direct: msg.direct,
                    senseNames: sensorNames, actionNames: actionNames, frame: msg.frame, turbo: true };
    } else if (msg.type === "rec") {
      if (dash()) dash().ingest(msg.rows);
    } else if (msg.type === "snapshot") {
      onSnapshot(msg);   /* Save world's copy: every acknowledgement it holds came before it */
    } else if (msg.type === "set") {
      /* a refusal leaves the field alone when a newer edit of the key, in
       * flight or held for the hand-off, follows the one answered */
      var answered = live.answered(msg.key, !!msg.ok);
      if (!answered) return;
      if (msg.ok) liveApplied(msg.key, valOf(msg.key, msg.value), false, answered.seq);
      else refuse(msg.key, msg.error, live.pending(msg.key, answered.seq));
    } else if (msg.type === "memory") {
      if (turboState !== "exiting") return;
      try {
        if (engineState !== "ok") throw new Error(engineBusyWhy());   /* (the page's engine stopped meanwhile: nothing to put it into) */
        takeMemory(msg.mem);
      } catch (err) {
        /* the worker still has the world: it carries on, nothing is lost (a start waiting for it is cancelled) */
        var hadStart = !!pendingStart;
        pendingStart = null;
        turboWorker.postMessage({ cmd: "resume" });
        turboState = "turbo";
        updateLocks();
        showError("Turbo could not hand the world back (" + (err.message || err) + "), so it keeps running" +
                  (hadStart ? " and the new world did not start" : "") + (engineState === "ok" ? ". Stop it again to retry." : "."));
        flushHeld();
        return;
      }
      /* the world is here: the worker, idle now, goes with its memory (a
       * fresh one runs the next Turbo; review of #44, round 3, finding 1: a
       * stopped worker kept its whole memory, which no open counted) */
      dropWorker();
      var ps = pendingStart;
      pendingStart = null;
      /* a new world follows: the fish is picked up again only if it doesn't
       * start (the run carries on), in this message, before any frame steps
       * the world handed back */
      turboBack(false, false, false, !!ps);
      if (ps && !finishPendingStart(ps)) restoreAfterTurbo();
      if (!ps) showNote("Turbo ran " + (msg.totalSteps || 0).toLocaleString() + " steps.");
    } else if (msg.type === "error") {
      turboFailed("Turbo stopped: " + (msg.message || "unknown error"), msg.mem);
    }
  }
  /* The page owns the world again: its memory is the worker's, or (lost) its
   * own, from where Turbo took it. It applies, in the order they were made,
   * the edits never answered (never applied) and the held ones, and, lost,
   * the acknowledged ones before them (ledger back). Returns replayEdits'.
   * After a session the world runs on (Stop Turbo and watch); a start that
   * failed (startFailed: the worker never answered) leaves the playback as
   * it was, a paused world paused. */
  function turboBack(quiet, lost, startFailed, holdReturn) {
    turboState = "live";
    turboView = null; turboWire = null; wireAsked = false;
    summary = null;   /* the readout's summary: this world's again, at the next refresh */
    var plan = live.back(!!lost);
    afterNewWorld(true);
    sampleBucket = Math.floor(M._oc_stats ? frameNow() / (dash() ? dash().every() : 60) : -1);
    setPaused(startFailed ? turboEntryPaused : false);
    updateLocks();
    var res = replayEdits(plan, quiet);
    if (!holdReturn) restoreAfterTurbo();   /* (held: Stop Turbo & start decides first) */
    return res;
  }
  /* The worker stopped on an error, or died. With its memory (the world was
   * whole), the run goes on from where Turbo got it, as after a Stop.
   * Without, from where Turbo took it: this page's own copy, untouched
   * since; Turbo's steps are lost, and the live changes the worker applied
   * are applied again here, in the order it applied them (turboBack). Either
   * way the worker is done: a fresh one runs the next Turbo. */
  function turboFailed(why, mem) {
    var was = turboState;
    dropWorker();
    if (was === "live") return;
    if (pendingStart) { pendingStart = null; why = "The new world did not start. " + why; }   /* the recovered run is the visitor's to replace */
    if (engineState !== "ok") {   /* the page's engine stopped (meanwhile, or as Turbo started): nothing to put a world into, nothing read */
      turboState = "live"; turboView = null; turboWire = null; wireAsked = false;
      live.back(true);
      updateLocks();
      showError(why + ". Its world can't come back here: " + engineBusyWhy() + ".");
      return;
    }
    var back = false;
    if (mem && was !== "entering") {
      try { takeMemory(mem); back = true; } catch (err) { why += "; the world it had could not come back (" + (err.message || err) + ")"; }
    }
    var lost = !back && was !== "entering";
    if (lost && turboEntryCfg) runCfg = Object.assign({}, turboEntryCfg);
    var res = turboBack(true, lost, was === "entering");
    if (lost && dash() && dash().rewind) dash().rewind(frameNow());
    /* what this world took again (the acknowledged edits), and what it refused, truthfully */
    var again = [], seen = {};
    res.applied.forEach(function (e) {
      if (e.from === "acked" && !seen[e.key]) { seen[e.key] = true; again.push(LABELS[e.key] || e.key); }
    });
    var refused = res.refused.map(function (r) { return (LABELS[r[0].key] || r[0].key) + " " + shown(valOf(r[0].key, r[0].num)) + " (" + r[1] + ")"; });
    showError(why + (back ? ". The world is back where Turbo got it." :
              was === "entering" ? "." : ". Its steps are lost: the world is back where Turbo took it" +
              (again.length ? ", with " + again.join(", ") + " applied again." : ".")) +
              (refused.length ? " Refused: " + refused.join("; ") + "." : ""));
  }
  /* The fish the visitor had picked (and followed) when Turbo took the world:
   * its id, family line, place and whether it was followed, in this world
   * (epoch). The picture can't show it during Turbo; the hand-back (or a
   * recovery) picks it up again: the same fish if it lives, else the nearest
   * of its family line (world distance, across the wrap without walls; the
   * lower id on a tie), else none, said so. Following resumes only if it was
   * on and not let go meanwhile (C, the fit button: no follow; Esc: nothing).
   * Never across a new world. The flashlight preference is never written:
   * the follow's own rule turns the lamp on and puts it back. */
  function returnPoint() {
    if (selectedId === null) return null;
    var s = fresh(lastS), idx = indexOfId(s, selectedId);
    var r = { id: selectedId, follow: !!(scene && scene.following()), epoch: worldEpoch, family: null, x: 0, y: 0, d: 0 };
    if (idx >= 0) {
      r.x = s.segs[12 * idx]; r.y = s.segs[12 * idx + 1]; r.d = s.depth[idx];   /* read before oc_inspect, which may grow the memory */
      var f = inspect(idx);
      if (f) r.family = Math.round(f.info[7]);
    }
    return r;
  }
  function restoreAfterTurbo() {
    if (engineState !== "ok") return;   /* (restarting: rebuildEngine picks it up when the run is back) */
    var r = turboReturn;
    turboReturn = null;
    if (!r || r.epoch !== worldEpoch || !M || turboState !== "live") return;
    var s = fresh(lastS), idx = indexOfId(s, r.id), id = r.id;
    if (idx < 0) { id = nearestOfFamily(s, r); }
    if (id === null) {
      toast("Fish #" + r.id + " did not survive Turbo, nor did any of its family line" + (r.follow ? ": nothing to follow." : "."));
      return;
    }
    select(id, true);
    if (r.follow && scene) { wantFollow = true; scene.setFollow(true); }
    if (id !== r.id) toast("Fish #" + r.id + " died during Turbo: " + (r.follow ? "following" : "showing") + " #" + id + ", the nearest of its family line.");
  }
  /* the nearest living member of r's family line, by id (one oc_inspect per fish: the ids and places copied first) */
  function nearestOfFamily(s, r) {
    if (r.family === null || !s || !s.n || !has("oc_inspect")) return null;
    var n = s.n, ids = Array.prototype.slice.call(s.ids, 0, n), xs = [], ys = [], ds = [], i;
    for (i = 0; i < n; i++) { xs.push(s.segs[12 * i]); ys.push(s.segs[12 * i + 1]); ds.push(s.depth[i]); }
    var best = null, bd = Infinity;
    for (i = 0; i < n; i++) {
      if (!M._oc_inspect(i)) continue;
      var info = HO.f64(M, M._oc_inspect_info(), M._oc_inspect_len());   /* a fresh view: oc_inspect allocates */
      if (Math.round(info[7]) !== r.family) continue;
      var dx = xs[i] - r.x, dy = ys[i] - r.y, dz = ds[i] - r.d;
      if (!WALLS) {
        if (dx > W / 2) dx -= W; else if (dx < -W / 2) dx += W;
        if (dy > H / 2) dy -= H; else if (dy < -H / 2) dy += H;
      }
      var d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < bd || (d2 === bd && ids[i] < best)) { bd = d2; best = ids[i]; }
    }
    return best;
  }
  function dropWorker() {
    cancelSnapshot("Turbo stopped before it could copy the world");
    if (!turboWorker) return;
    turboWorker.onmessage = null;
    turboWorker.onerror = null;
    turboWorker.terminate();
    turboWorker = null;
  }
  function frameNow() { M._oc_sync(); return HO.f64(M, M._oc_stats(), statsLen)[1]; }
  /* A start that throws here (the Worker, the copy of the memory, the first
   * message) goes back to live through turboFailed, as a worker that fails
   * while starting does: the worker dropped, the held edits applied. The
   * worker always gets a copy: this page's memory stays the fallback. */
  function enterTurbo() {
    if (turboState !== "live" || !M || MOCK) { if (MOCK) showNote("Turbo needs the real engine."); return; }
    if (engineState !== "ok") { showNote("Turbo: " + engineBusyWhy() + "."); return; }
    store(COACH_KEY, "1"); hideCoach();   /* found it: no coach mark */
    try {
      turboState = "entering";
      turboStats = null; spark = [];
      turboView = null; turboWire = null; wireAsked = false;
      turboEntryCfg = Object.assign({}, runCfg);
      turboEntryPaused = paused;
      live.start();
      turboReturn = returnPoint();   /* the fish to pick up again after Turbo, before the picture lets it go */
      select(null);
      unfollow();
      updateLocks();
      if (!turboWorker) {
        turboWorker = new Worker(A.worker);
        turboWorker.onmessage = fenced(onTurboMessage);
        turboWorker.onerror = fenced(function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          turboFailed("The Turbo worker failed: " + (ev && ev.message || "could not load ocean_worker.js"), null);
        });
      }
      var mem = heap().slice(0);
      turboWorker.postMessage({ cmd: "start", js: moduleUrls.js, wasm: moduleUrls.wasm, handoff: moduleUrls.handoff, mem: mem,
                                recEvery: dash() ? dash().every() : 60, famK: dash() ? dash().famK : 8 }, [mem]);
    } catch (err) {
      if (err instanceof WebAssembly.RuntimeError) engineStopped(err);   /* (a trap picking up its fish: the engine stops once, and Turbo goes without a read) */
      turboFailed("Turbo could not start: " + (err && err.message || err), null);
    }
  }
  function exitTurbo() {
    if (turboState !== "turbo") return;
    turboState = "exiting";
    updateLocks();
    turboWorker.postMessage({ cmd: "stop" });
  }

  /* ---------------- Hold 60 fps ----------------
   * The step budget (stepsThisFrame) first; then, frames still slow at one
   * step, the tank's detail, a level at a time. Never the simulation. */
  var slowSince = 0, detail0 = 0;
  function govern(now) {
    if (!governorOn || paused || turboState !== "live" || !scene) { slowSince = 0; return; }
    if (fps && fps < 48 && lastSteps <= 1) {
      if (!slowSince) slowSince = now;
      else if (now - slowSince > 3000) {
        slowSince = 0;
        if (scene.degrade()) toast("Drawing the tank with less detail, to hold 60 fps.");
      }
    } else slowSince = 0;
  }
  function restoreDetail() { if (scene && detail0) scene.setQuality(detail0); }

  /* ---------------- the loop ---------------- */
  var splashDone = false;
  /* A trap anywhere in a frame (the step, the sync, the snapshot, the
   * charts' sample, the fish card's oc_inspect, the readout's summary: a
   * world that broke later than its test run's step, the limit of
   * raw-memory imports) stops the engine once, said so, rather than
   * throwing in every frame; nothing reads it after (engineState). */
  function frame(now) {
    requestAnimationFrame(frame);
    if (engineState !== "ok") return;   /* restarting (a new module on its way) or stopped: nothing to step or read */
    try { frameBody(now); }
    catch (err) { if (err instanceof WebAssembly.RuntimeError) { engineStopped(err); return; } throw err; }
  }
  function frameBody(now) {
    PROF.beginFrame(now, worldEpoch, turboState, paused);   /* the raw rAF interval, before the clamp below */
    var dt = lastNow ? Math.min(0.1, (now - lastNow) / 1000) : 0;
    lastNow = now;
    var steps = 0;
    if (turboState === "live" && (!paused || stepOnce)) {
      steps = stepOnce ? 1 : stepsThisFrame();
      stepOnce = false;
      var t0 = performance.now();
      M._oc_step(steps);
      var stepElapsed = performance.now() - t0;
      PROF.recordStep(stepElapsed, steps);
      var per = stepElapsed / steps;
      stepMs = stepMs ? stepMs * 0.9 + per * 0.1 : per;
      if (!paused) animT += dt * Math.min(steps, 2);
    }
    lastSteps = steps;
    var pt = PROF.beginCpu();
    M._oc_sync();
    pt = PROF.lap(SP.sync, pt);
    var s = snapshot();
    pt = PROF.lap(SP.snapshot, pt);
    if (turboState === "live") { takeSample(s.stats); s = fresh(s); }
    pt = PROF.lap(SP.dashboard, pt);
    if (!HAS_VZ) s.vz = vzEstimate(s, steps > 0);
    var ax = { f: 0, r: 0, u: 0 };
    for (var key in heldMoveKeys) ax[heldMoveKeys[key][0]] += heldMoveKeys[key][1];
    scene.setMove(ax.f, ax.r, ax.u, shiftHeld);
    /* the selected fish, by id; a followed fish that died hands over to another */
    var idx = turboState === "live" ? indexOfId(s, selectedId) : -1;
    if (idx < 0 && selectedId !== null && turboState === "live") {
      if (wantFollow && s.n) { idx = randomFish(s, null); select(s.ids[idx], true); }
      else select(null);
    }
    s.selIdx = idx;
    lastS = s;
    PROF.lap(SP.controller, pt);
    if (!(dash() && dash().isOpen())) scene.render(s, { animT: animT, dtSim: steps * DT, selIdx: idx });
    pt = PROF.beginCpu();
    s = updateCard(s);
    pt = PROF.lap(SP.card, pt);
    fpsFrames++;
    if (now - fpsT >= 1000) { fps = Math.round(fpsFrames * 1000 / (now - fpsT)); fpsFrames = 0; fpsT = now; dirtyHud = true; govern(now); }
    updateHud(s, now);
    PROF.lap(SP.hud, pt);
    if (!splashDone) { splashDone = true; el("splash").classList.add("done"); }
    if (PROF.active) PROF.endFrame(s.n, s.stats[1], !!(dash() && dash().isOpen()));
  }

  /* ---------------- input ---------------- */
  /* The camera's movement keys, held (scene.setMove): W A S D by their place
   * on the keyboard (e.code: the same four keys on any layout), Q / E and
   * PageDown / PageUp down / up, Shift faster. [axis, sign]: f forward, r
   * right, u up. Never while typing in a field. */
  var MOVE_CODES = { KeyW: ["f", 1], KeyS: ["f", -1], KeyD: ["r", 1], KeyA: ["r", -1], KeyE: ["u", 1], KeyQ: ["u", -1] };
  var MOVE_KEYS = { pageup: ["u", 1], pagedown: ["u", -1] };
  var heldMoveKeys = {}, shiftHeld = false;
  function releaseMoveKeys() { heldMoveKeys = {}; shiftHeld = false; }
  /* a focused field takes the keys: the text inputs, selects, text areas and
   * editable text (the settings' number fields among them). A switch or a
   * slider is not one: letters are shortcuts there too (ownKey keeps theirs). */
  function typingIn(t) {
    if (!t || !t.tagName) return false;
    if (t.tagName === "INPUT") return !/^(checkbox|radio|range|button|submit|reset|color|file|image)$/i.test(t.type || "text");
    return t.tagName === "TEXTAREA" || t.tagName === "SELECT" || !!t.isContentEditable;
  }
  /* the keys a focused control acts on itself: Space and Enter press a button
   * or turn a switch (Enter follows a link), a slider takes the arrows, Home,
   * End and Page Up / Down, a tab the arrows. Every other key stays a shortcut. */
  function ownKey(t, k) {
    if (!t || !t.tagName) return false;
    var press = k === " " || k === "Spacebar" || k === "Enter";
    if (t.tagName === "BUTTON") return press || (/^Arrow/.test(k) && t.getAttribute("role") === "tab");
    if (t.tagName === "A") return k === "Enter";
    if (t.tagName !== "INPUT") return false;
    if (t.type === "range") return /^(Arrow|Page)/.test(k) || k === "Home" || k === "End";
    return press && (t.type === "checkbox" || t.type === "radio");
  }
  /* One owner for each Esc, the top layer: the tour (web/guide.js), then the
   * charts (web/ocean_dash.js: it leaves an Esc to the tour), then this
   * page's own (a popover, the settings, the live numbers, the fish). Seen
   * here in the capture phase, before any handler has closed anything. */
  var escHandledElsewhere = false;
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") escHandledElsewhere = !!(dash() && dash().isOpen()) || !!document.getElementById("guide");
  }, true);
  function wireInput() {
    document.addEventListener("keyup", function (e) {
      delete heldMoveKeys["c:" + e.code];
      delete heldMoveKeys["k:" + String(e.key).toLowerCase()];
      if (e.key === "Shift") shiftHeld = false;
    });
    window.addEventListener("blur", releaseMoveKeys);
    document.addEventListener("visibilitychange", function () { if (document.hidden) releaseMoveKeys(); });
    document.addEventListener("focusin", function (e) { if (typingIn(e.target)) releaseMoveKeys(); });
    window.addEventListener("keydown", fenced(function (e) {   /* (each key fenced whole: Esc, F, R, T, ...) */
      if (e.key === "Escape") {
        /* the tour or the charts take this Esc themselves (escHandledElsewhere),
         * and nothing behind them closes with it; else the popover (back to its
         * opener), the settings, the live numbers, or the fish */
        if (openPop) { if (!escHandledElsewhere) closePop(true); return; }
        if (!escHandledElsewhere && startMenuOpen()) { setStartMenu(false); el("startmenubtn").focus(); return; }   /* the start menu first, then the sheet */
        if (!escHandledElsewhere) {
          if (drawerEl.classList.contains("open")) setDrawer(false);
          else if (statOpen) setStatPanel(false);
          else if (scene.following()) unfollow();
          else { select(null); if (turboReturn) { turboReturn = null; showNote("Let go: no fish to pick up after Turbo."); } }
        }
        if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
        return;
      }
      var t = e.target;
      if (typingIn(t)) return;
      if (e.key === "Shift") { shiftHeld = true; return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      var k = e.key, lk = String(k).toLowerCase();
      if (ownKey(t, k)) return;   /* Space / Enter press the focused button or switch; a slider's arrows move it */
      /* the camera's movement: also with a button focused (letters don't press it) */
      var mv = MOVE_CODES[e.code], mk = mv ? "c:" + e.code : null;
      if (!mv && MOVE_KEYS[lk]) { mv = MOVE_KEYS[lk]; mk = "k:" + lk; }
      if (mv) {
        heldMoveKeys[mk] = mv; shiftHeld = e.shiftKey;
        e.preventDefault();
        return;
      }
      /* the dock's and the top bar's own keys (Turbo's too: T stops it; letters press no button) */
      if (e.repeat && /^[?vtgoil]$/.test(lk)) return;   /* a held toggle acts once (the camera and speed keys repeat) */
      /* ? and V open as their buttons do from the keyboard: the focus into the
       * popover, and back to the button when it closes */
      if (k === "?") { togglePop("help", el(POPS.help[1]), true); return; }
      if (lk === "v") { togglePop("view", el(POPS.view[1]), true); return; }
      if (lk === "t") { toggleTurbo(); return; }
      if (lk === "g") { setPop(null); el("dashbtn").click(); return; }
      if (lk === "o") { setPop(null); setDrawer(!drawerEl.classList.contains("open")); return; }
      if (lk === "i") { setPop(null); setStatPanel(!statOpen); return; }
      /* the view: always */
      if (lk === "c") { wantFollow = false; scene.resetView(true); if (turboReturn) turboReturn.follow = false; return; }
      if (lk === "l") { toggleLight(); return; }
      if (lk === "f") { follow(); return; }
      /* Turbo: Space stops it (as T does); the speed and the step are Turbo's
       * own while it runs, and say so */
      if (turboState !== "live") {
        if (k === " " || k === "Spacebar") { if (!e.repeat) stopTurbo(); e.preventDefault(); }
        else if (k === "ArrowUp" || k === "ArrowDown" || k === "+" || k === "=" || k === "-" || k === "_" || k === ".") {
          showNote("Turbo runs as fast as it can: stop it (Space) to set the speed or step."); e.preventDefault();
        } else if (lk === "r") startKey(e);   /* Stop Turbo & start, asked first (Turbo used) */
        return;
      }
      if (k === " " || k === "Spacebar") { setPaused(!paused); e.preventDefault(); }
      else if (k === "+" || k === "=" || k === "ArrowUp") { changeSpeed(1); e.preventDefault(); }
      else if (k === "-" || k === "_" || k === "ArrowDown") { changeSpeed(-1); e.preventDefault(); }
      else if (lk === "r") startKey(e);
      else if (k === "." && paused) stepOnce = true;
    }));
    /* R a new world, Shift+R Replay: the same door as Start (the question in
     * the setup sheet when the run has something to lose, its confirm button
     * focused); a held key starts nothing twice, nor does R again while asked */
    function startKey(e) {
      if (e.repeat) return;
      if (asking) { el("startconfirm").focus(); return; }
      if (e.shiftKey) replay(); else newWorld();
      if (asking) el("startconfirm").focus();
    }
    /* a short tap or click selects the fish nearest it on screen; empty water
     * lets go. A drag, pinch or long press belongs to the camera. */
    var tap = null;
    canvas.addEventListener("pointerdown", function (e) {
      tap = e.isPrimary && e.button === 0 ? { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId } : null;
    });
    canvas.addEventListener("pointercancel", function () { tap = null; });
    canvas.addEventListener("pointerup", function (e) {
      if (!tap || e.pointerId !== tap.id) return;
      var moved = Math.hypot(e.clientX - tap.x, e.clientY - tap.y), held = performance.now() - tap.t;
      tap = null;
      if (moved > 8 || held > 600) return;
      engineCall(function () {
        var s = fresh(lastS);
        if (!s) return;
        if (turboState !== "live") { turboPictureHint(); return; }
        var best = scene.pick(s, e.clientX, e.clientY, e.pointerType === "mouse" ? 18 : 30);
        if (best < 0 && scene.following()) return;   /* a stray tap doesn't drop a follow */
        if (best >= 0 && scene.following() && s.ids[best] !== selectedId) unfollow();
        select(best >= 0 ? s.ids[best] : null);
      }, undefined, "Picking a fish");
    });
    var fitTimer = 0;
    window.addEventListener("resize", function () {
      scene.resize(); updateInsets();
      clearTimeout(fitTimer);
      fitTimer = setTimeout(function () { updateFitButton(); updateInsets(); placePop(); placeCoach(); }, 250);
    });
    if (reducedMQ.addEventListener) reducedMQ.addEventListener("change", function () { scene.setReducedMotion(reducedMQ.matches); });
  }
  /* The part of the screen the tank is framed in (renderer.js updateInsets):
   * below the top bar and above the dock on a desktop, the whole screen on
   * compact ones, where the controls float over it; less the open settings. */
  function updateInsets() {
    if (!scene) return;
    var vh = window.innerHeight, open = drawerEl.classList.contains("open");
    var top = 0, bottom = 0, right = 0;
    if (!compactMQ.matches) {
      top = el("topbar").getBoundingClientRect().bottom + 6;
      bottom = vh - el("dock").getBoundingClientRect().top + 6;
    }
    if (open && wideMQ.matches) right = drawerEl.getBoundingClientRect().width;
    else if (open) {
      var sheetTop = drawerEl.getBoundingClientRect().top;
      bottom = sheetTop - top >= vh * 0.3 ? vh - sheetTop : bottom;
    }
    scene.setInsets({ top: Math.round(top), right: Math.round(right), bottom: Math.round(Math.max(0, bottom)), left: 0 });
  }

  /* ---- settings: a bottom sheet on narrow screens, a side panel on wide ones ---- */
  var drawerEl = el("drawer"), menuBtn = el("menubtn");
  function setDrawer(open) {
    if (open && dash()) dash().close();
    drawerEl.classList.toggle("open", open);
    document.body.classList.toggle("sheet-open", open);
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) { hideTip(); setStartMenu(false); if (asking) hideAsk(); }   /* a question no one can see is no question: closing the sheet keeps the run */
    if (open) { setStatPanel(false); setPop(null); hideCoach(); }
    if (scene) { updateInsets(); setTimeout(updateInsets, 320); }
  }
  /* Crossing 960 px (a resize, a rotation): a wide screen lets the settings
   * panel stay beside a popover or the live numbers, a narrow one's sheet
   * would cover them (and hide the dock under the View menu). What opened
   * last stays — a popover or the live numbers, since opening the settings
   * closes both — so the sheet closes, as it would have on this screen
   * (setPop, setStatPanel); the focus, if it was in the sheet, goes to the
   * popover's first control, else to the settings button. */
  function onWideChange() {
    if (!wideMQ.matches && drawerEl.classList.contains("open") && (openPop || statOpen)) {
      var inSheet = drawerEl.contains(document.activeElement);
      setDrawer(false);
      if (inSheet) (openPop ? el(POPS[openPop][2]) : menuBtn).focus();
    }
    placePop();
  }
  if (wideMQ.addEventListener) wideMQ.addEventListener("change", onWideChange);
  else if (wideMQ.addListener) wideMQ.addListener(onWideChange);   /* Safari before 14 */
  menuBtn.addEventListener("click", function () { setDrawer(!drawerEl.classList.contains("open")); this.blur(); });
  el("drawerclose").addEventListener("click", function () { setDrawer(false); this.blur(); });
  (function () {   /* drag the sheet's grip (or header) down to close it */
    var start = null, grip = el("grip"), head = drawerEl.querySelector(".sheet-head");
    function down(e) {
      if (wideMQ.matches || e.target.closest("button")) return;
      start = { y: e.clientY, id: e.pointerId, dy: 0 };
      drawerEl.classList.add("dragging");
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    function move(e) {
      if (!start || e.pointerId !== start.id) return;
      start.dy = Math.max(0, e.clientY - start.y);
      drawerEl.style.transform = "translateY(" + start.dy + "px)";
    }
    function up(e) {
      if (!start || e.pointerId !== start.id) return;
      drawerEl.classList.remove("dragging");
      drawerEl.style.transform = "";
      if (start.dy > Math.min(120, drawerEl.offsetHeight * 0.25)) setDrawer(false);
      start = null;
    }
    [grip, head].forEach(function (n) {
      n.addEventListener("pointerdown", down); n.addEventListener("pointermove", move);
      n.addEventListener("pointerup", up); n.addEventListener("pointercancel", up);
    });
  })();
  el("readout").addEventListener("click", function () { setStatPanel(!statOpen); this.blur(); });
  document.addEventListener("pointerdown", function (e) {
    if (statOpen && !e.target.closest("#statpanel, #readout")) setStatPanel(false);
  });

  /* ---- the shared hover tooltip (renderer.js's) ---- */
  var tipEl = document.createElement("div");
  tipEl.id = "tooltip";
  var tipDesc = document.createElement("div"); tipDesc.className = "tipd";
  var tipTry = document.createElement("div"); tipTry.className = "tipt";
  tipEl.appendChild(tipDesc); tipEl.appendChild(tipTry);
  document.body.appendChild(tipEl);
  var tipTimer = 0, tipFor = null;
  function hideTip() { clearTimeout(tipTimer); tipEl.style.display = "none"; tipFor = null; }
  function showTip(rowEl, tip) {
    tipDesc.textContent = tip.d; tipTry.textContent = tip.t;
    tipEl.style.display = "block";
    tipFor = rowEl;
    var dr = drawerEl.getBoundingClientRect(), lr = rowEl.getBoundingClientRect(), left, top;
    if (wideMQ.matches && dr.left >= tipEl.offsetWidth + 16) {
      left = Math.max(6, dr.left - 10 - tipEl.offsetWidth);
      top = lr.top + lr.height / 2 - tipEl.offsetHeight / 2;
    } else {
      left = Math.max(8, Math.min(lr.left, window.innerWidth - tipEl.offsetWidth - 8));
      top = lr.bottom + 4;
      if (top + tipEl.offsetHeight > window.innerHeight - 6) top = lr.top - 4 - tipEl.offsetHeight;
    }
    top = Math.max(6, Math.min(top, window.innerHeight - tipEl.offsetHeight - 6));
    tipEl.style.left = left + "px"; tipEl.style.top = top + "px";
  }
  function attachTip(rowEl, key) {
    var tip = CFG.TIPS[key];
    if (!tip || !rowEl) return;
    rowEl.addEventListener("mouseenter", function () {
      if (lastPointer !== "mouse") return;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(function () { showTip(rowEl, tip); }, 200);
    });
    rowEl.addEventListener("mouseleave", function () { if (lastPointer === "mouse") hideTip(); });
    var name = rowEl.querySelector(".lt");
    if (name) name.addEventListener("click", function (e) {
      if (lastPointer === "mouse") return;
      e.preventDefault();
      if (tipFor === rowEl) hideTip(); else showTip(rowEl, tip);
    });
  }
  panelsEl.addEventListener("scroll", hideTip);
  document.addEventListener("pointerdown", function (e) {
    if (tipFor && e.pointerType !== "mouse" && !(e.target.closest && e.target.closest(".lt"))) hideTip();
  });

  /* ---- buttons ---- */
  /* (each button's press fenced whole: Close, Follow, Replay, Start, Turbo, ...) */
  function btn(id, fn) { el(id).addEventListener("click", fenced(function () { fn(); this.blur(); })); }
  /* A button that may open the start bar's question (Start, its menu's two,
   * a card, its Start, Reroll, Replay). Pressed from the keyboard (its focus
   * ring showing, or a click no pointer made: Enter / Space give detail 0),
   * the focus goes to the question's answer, as R's does, and comes back to
   * the button (back: the menu's own button for its items) when the
   * question is answered Keep; a pointer's press blurs it, as btn's. */
  function askBtn(id, fn, back) {
    el(id).addEventListener("click", fenced(function (e) {
      var kb = this.matches(":focus-visible") || (!!e && e.detail === 0);
      fn();
      if (kb && asking) { asking.opener = back ? el(back) : this; el("startconfirm").focus(); }
      else this.blur();
    }));
  }
  buildSettings();
  panelsEl.addEventListener("input", onEdit);
  panelsEl.addEventListener("change", onEdit);
  askBtn("restart", restart);
  btn("pausebtn", function () { if (guardTurbo()) return; setPaused(!paused); });
  btn("slower", function () { if (guardTurbo()) return; changeSpeed(-1); });
  btn("faster", function () { if (guardTurbo()) return; changeSpeed(1); });
  btn("turbobtn", toggleTurbo);
  /* Stop: the dock's strip, and the bars where the dock is covered (a narrow setup sheet, the charts) */
  ["turboexit", "setup-turbo-stop", "dash-turbo-stop"].forEach(function (id) { btn(id, stopTurbo); });
  btn("coachgo", function () { hideCoach(); toggleTurbo(); });
  btn("coachx", hideCoach);
  btn("stepbtn", function () { if (guardTurbo()) return; if (paused) stepOnce = true; });
  /* Start from: each card stages (pickScenario); the picked one's Start starts it */
  Object.keys(CARD_IDS).forEach(function (id) { if (id !== "file") askBtn(CARD_IDS[id], function () { pickScenario(id); }); });
  askBtn("scenario-start", startStaged);
  askBtn("rerollbtn", function () { pickScenario("surprise"); });
  /* the start bar: Start (the same fish: this seed), and its menu */
  btn("startmenubtn", function () { setStartMenu(!startMenuOpen()); });
  askBtn("startsame", function () { setStartMenu(false); restart(); }, "startmenubtn");
  askBtn("newworld", function () { setStartMenu(false); newWorld(); }, "startmenubtn");
  document.addEventListener("pointerdown", function (e) {
    if (startMenuOpen() && !(e.target.closest && e.target.closest("#startmenu, #startmenubtn"))) setStartMenu(false);
  });
  askBtn("replay", replay);
  btn("lightbtn", toggleLight);
  ["view", "help"].forEach(function (n) {   /* the triggers; × closes (pointerBlur, setPop: the focus) */
    el(POPS[n][1]).addEventListener("click", function () {
      var kb = this.matches(":focus-visible");
      togglePop(n, kb ? this : null, kb);
      if (!kb) this.blur();
    });
    el(n + "close").addEventListener("click", function () { closePop(this.matches(":focus-visible")); });
  });
  btn("tourbtn", function () { setPop(null); if (window.EvoGuide) EvoGuide.start(); });
  btn("whatturbo", function () { setPop(null); if (window.EvoGuide && EvoGuide.turbo) EvoGuide.turbo(); });
  el("to2dmenu").href = el("to2d").href;   /* the deploy build renames Classic's page in #to2d */
  el("lightnow").addEventListener("change", function () {
    lightNow = this.checked;
    updateLight();
    pointerBlur(this);
  });
  btn("viewbtn", function () { if (scene) { wantFollow = false; scene.resetView(true); if (turboReturn) turboReturn.follow = false; } });
  btn("fitbtn", fitToScreen);
  btn("followbtn", function () {
    if (!scene) return;
    if (scene.following()) unfollow();
    else if (selectedId !== null) { wantFollow = true; scene.setFollow(true); }
  });
  btn("iclose", function () { unfollow(); select(null); });
  btn("iexpand", function () {
    cardExpanded = !cardExpanded;
    cardEl.classList.toggle("expanded", cardExpanded);
    el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    el("iexpand").title = cardExpanded ? "Hide its brain" : "Show its brain";
    cardCache.sense = null;
  });
  btn("savecp", saveSetup);   /* in Turbo too: the accepted setup */
  btn("saveworld", saveWorld);   /* in Turbo too: the worker's copy, Turbo runs on */
  btn("startconfirm", confirmAsk);
  btn("startcancel", cancelAsk);
  /* From a file: a setup (staged) or a saved world (opened through the
   * door), told apart by the file's first bytes. Pressed from the keyboard,
   * a question the file brings has the focus on its answer (askBtn's rule;
   * the file dialog comes between, so it is remembered here) */
  var fileOpener = null;
  el("loadcp").addEventListener("click", function (e) {
    fileOpener = this.matches(":focus-visible") || (!!e && e.detail === 0) ? this : null;
    if (!fileOpener) this.blur();
    el("cpfile").click();
  });
  /* the read is asynchronous: its answer stages the setup (or opens the
   * world) only if nothing newer came meanwhile (another file, a scenario,
   * Discard, a start), and whoever owns the world then (staging changes no
   * world; a world opens through requestStart, which stops Turbo first) */
  var fileReq = 0;
  function isWorldBlob(file) {
    if (typeof file.slice !== "function") return Promise.resolve(false);   /* (a file that is only text) */
    return file.slice(0, HO.WORLD.MAGIC.length).arrayBuffer().then(function (b) { return HO.isWorldFile(new Uint8Array(b)); });
  }
  /* the file picker has no type filter (a phone's greys out .oceanworld),
   * so any file can come: a saved world is read part by part within its
   * limits (openWorldFile); anything else must be a setup, at most
   * HO.WORLD.MAX_SETUP, refused by its size before it is read */
  var tooBigForSetup = function (n) {
    return "That file is " + fmtMB(n) + ": not a saved world (Save world makes those), and too big to be a setup (Save setup's are a few kB).";
  };
  /* filesRead: how many From a file reads have answered, whatever the
   * answer, and which (fileAnswered: their request numbers, the latest 32):
   * the tests wait on them, not on a message */
  var filesRead = 0, fileAnswered = [];
  el("cpfile").addEventListener("change", function () {
    var file = this.files && this.files[0];
    this.value = "";
    if (!file || !M) return;
    var my = ++fileReq, gen = draftGen, opener = fileOpener;
    fileOpener = null;
    /* something newer is in the sheet (another file, a stage, Discard, a start); latest: no newer file */
    var req = { stale: function () { return my !== fileReq || gen !== draftGen; }, latest: function () { return my === fileReq; } };
    isWorldBlob(file).then(function (world) {
      if (req.stale()) return;
      if (world) {
        if (MOCK) { showNote("Opening a saved world needs the real engine."); return; }
        /* a question still open about another saved world: this file replaces it (and its image goes) */
        if (asking && asking.plan && asking.plan.op === "open") hideAsk();
        return openWorldFile(file, file.name, req, opener);
      }
      if (typeof file.size === "number" && file.size > HO.WORLD.MAX_SETUP) { showError(tooBigForSetup(file.size)); return; }
      return file.text().then(function (text) {
        if (req.stale()) return;
        if (text.length > HO.WORLD.MAX_SETUP) { showError(tooBigForSetup(text.length)); return; }
        loadSetup(text, file.name);
        if (asking && asking.replace && opener) { asking.opener = opener; el("startconfirm").focus(); }   /* it replaces edits that wait: asked */
      });
    }).catch(function (err) { if (!req.stale()) showError("Couldn't read that file: " + (err && err.message || err)); })   /* (finding 7: never over a newer answer) */
      .then(function () { filesRead++; fileAnswered.push(my); if (fileAnswered.length > 32) fileAnswered.shift(); });
  });
  btn("startdiscard", discardDraft);
  el("governor").addEventListener("change", function () {
    governorOn = this.checked;
    if (!governorOn) restoreDetail();
    pointerBlur(this);
  });
  el("followLight").addEventListener("change", function () {   /* the preference; following now, it applies now */
    followLight = this.checked;
    store("evo_boids.ocean.followLight", followLight ? "1" : "0");
    if (scene && scene.following()) lightNow = followLight || lightBeforeFollow;
    updateLight();
    pointerBlur(this);
  });
  el("followLight").checked = followLight;
  /* Fish colour: the fish's own appearance genome (its skin pattern; the
   * Ocean only, and the default), by family line, or by brain similarity.
   * Every mode draws each fish in its inherited body shape when the module
   * exports the genome (HAS_APP); family and brain only recolour the skin.
   * ?colour= wins, then the visitor's own last choice (stored only when they
   * pick one), else appearance. The key and ?colour= are shared with
   * Classic, which reads "appearance" as family. Display only. */
  (function () {
    var want = P.get("colour"), saved = store("evo_boids.colourBy");
    if (want !== "brain" && want !== "family" && want !== "appearance")
      want = saved === "brain" || saved === "family" ? saved : "appearance";
    colourMode = want;
    colourBrain = want === "brain";
    showColourMode();
  })();
  /* the View menu's three buttons; the line under them says what the mode
   * shows, or why Appearance can't (updateModeline), with the way to fix it */
  function showColourMode() {
    el("colourMode").querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.c === colourMode ? "true" : "false"); });
  }
  /* The one way the colour mode changes: the View menu's buttons and the
   * benchmark's cases (web/ocean_perf.js prepare) both come here, so a case
   * runs in the mode it names. false: no such mode (nothing changes). The
   * visitor's choice is stored, never a benchmark's. */
  function setColourMode(mode) {
    if (mode !== "appearance" && mode !== "family" && mode !== "brain") return false;
    colourMode = mode;
    colourBrain = colourMode === "brain";
    if (!BENCH) store("evo_boids.colourBy", colourMode);   /* a benchmark's cases are not the visitor's choice */
    showColourMode();
    if (M) engineCall(applyDisplaySwitches);   /* (a stopped engine: the view's choice is kept; a restarted one gets it with its run) */
    engineCall(updateModeline);
    return true;
  }
  el("colourMode").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-c]");
    if (!b) return;
    setColourMode(b.dataset.c);
    pointerBlur(b);
  });
  el("colourwhy").addEventListener("click", function (e) {   /* "Setup › Life › Appearance genes" */
    if (!e.target.closest("#colourfix")) return;
    setPop(null); setDrawer(true); setSheetTab("life");
    var row = el("f_appearance");
    if (row) row.scrollIntoView({ block: "center" });
  });
  /* Water clarity: how murky the water is drawn (scene.setClarity; drawing
   * only, live), 0 realistic (the Ocean's first look, kept for reference)
   * .. 1 clear (the default). ?clarity= (clear, realistic, 0..1 or a
   * percentage) wins and is not stored; then the visitor's own last choice
   * (stored when they move the slider); else clear. */
  var clarity = 1;
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
    var inp = el("clarity");
    inp.value = String(Math.round(clarity * 100));
    inp.setAttribute("aria-valuetext", clarityLabel(clarity));
    el("clarityval").textContent = clarityLabel(clarity);
    if (scene && scene.setClarity) scene.setClarity(clarity);
  }
  (function () {
    var want = parseClarity(P.get("clarity")), saved = parseClarity(store("evo_boids.ocean.clarity"));
    clarity = want !== null ? want : saved !== null ? saved : 1;
    applyClarity();
  })();
  el("clarity").addEventListener("input", function () {
    clarity = Math.max(0, Math.min(1, (+this.value || 0) / 100));
    store("evo_boids.ocean.clarity", String(clarity));
    applyClarity();
  });
  el("clarity").addEventListener("pointerup", function () { this.blur(); });   /* the keys go back to the tank; arrow keys keep it */
  function updateModeline() {
    /* the world's appearance genes (bit 1 patterns, bit 2 shapes; 0 = off, or a module without them) */
    var flags = HAS_APP ? (has("oc_appearance_flags") ? M._oc_appearance_flags() : 3) : 0;
    var what = colourMode === "appearance"
      ? (flags ? ", each fish drawn from its appearance genes (skin pattern and body shape)"
               : ", coloured by family (" + (HAS_APP ? "the appearance genes are off in this world" : "this module has no appearance genes") + ")")
      : (flags & 2 ? ", each fish in its inherited body shape" : "") + (colourBrain ? ", coloured by brain" : ", coloured by family");
    el("modeline").textContent = "Running the single-threaded Ocean module, reproducible from the seed" +
      (HAS_EYE ? " (the eye build)" : "") + ". The tank: " + W + " × " + H + " × " + D +
      (WALLS ? ", glass walls" : ", the sides wrap around") +
      ". Drawing: the 3D tank" + (scene ? ", detail " + scene.quality() + " of 3" : "") +
      what + ".";
    var noApp = !!M && colourMode === "appearance" && !flags;   /* the View menu: what the colours show, or why not */
    el("colourwhy").classList.toggle("why", noApp);
    setHtml("colourwhy", noApp
      ? (HAS_APP ? "Appearance genes are off in this world, so the fish show family colours. To turn them on: " +
                   "<button type='button' class='linkbtn' id='colourfix'>Setup › Life › Appearance genes</button>, then Start."
                 : "This engine build has no appearance genes, so the fish show family colours.")
      : colourMode === "appearance" ? "Each fish wears the skin pattern and body shape it inherited."
      : colourMode === "brain" ? "Fish with similar brains get similar colours."
      : "Each family line has its own colour, the same one it has in the charts.");
  }
  setPaused(BENCH);
  changeSpeed(0);
  updateLocks();   /* the mode the page starts in: Live (or Paused), no Turbo strip */
  setStartMenu(false); hideAsk();   /* the start bar's menu and question closed */

  /* ---------------- the tour (web/guide.js reads this) ---------------- */
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
            var looks = colourMode === "appearance" && HAS_APP
              ? "each fish wears the skin pattern and body shape it inherited from its parents"
              : colourBrain ? "a fish's colour follows its brain's wiring" : "each family has its own colour";
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
    touch: function () { return coarseMQ.matches; },
    compact: function () { return true; },
    has3D: function () { return true; },
    colourByBrain: function () { return colourBrain; },
    colourMode: function () { return colourMode; },
    startTurbo: function () { if (M && turboState === "live") enterTurbo(); },
    /* the Turbo card's tour step (web/guide.js) asks this; Classic's page has its #turbo card instead */
    turboActive: function () { return turboState !== "live"; },
    setDrawer: setDrawer,
    setSheetTab: setSheetTab,
    inspectSomeFish: function () {
      return engineCall(function () {
        var s = fresh(lastS);
        if (turboState !== "live" || !s || !s.n) return false;
        if (selectedId !== null) return true;
        var best = scene.pick(s, innerWidth * 0.4, innerHeight * 0.45, 4000);
        if (best < 0) best = 0;
        select(guideFish = s.ids[best]);
        return true;
      }, false);
    },
    releaseFish: function () {
      if (guideFish !== null && selectedId === guideFish) engineCall(function () { select(null); });
      guideFish = null;
    },
    inspectorRect: function () { return selectedId === null || cardEl.hidden ? null : cardEl.getBoundingClientRect(); }
  };

  /* ---------------- start ---------------- */
  buildHist();
  /* An Ocean link is one with any of the keys only the Ocean reads
   * (ocean.html's OCEAN_ONLY, the same list: tests/ocean_turbo_handoff.js
   * holds them equal), ?speed= among them; the keys both pages read (colour,
   * guide, intro) and those newer than walls (clarity) make no link old. A
   * link without any is a fresh visit (glass walls); a refused link's
   * "default settings" drops them all. */
  var OCEAN_KEYS = ["seed", "pop", "depth", "w", "h", "cfg", "speed", "e1", "mock", "walls"];
  /* and the keys only Classic reads (ocean.html's CLASSIC_ONLY, the same
   * list): left in a link without Ocean keys, the head sends it to Classic */
  var CLASSIC_KEYS = ["view", "fish", "gl", "bench", "threads", "nthreads"];
  var linkRefused = false;   /* oc_init refused the link's ?cfg= / ?e1=1 */
  splashSay(MOCK ? "Starting the ocean (mock engine)…" : "Starting the ocean…");
  var sceneReady = window.EvoOceanScene ? EvoOceanScene.load() : Promise.reject(new Error("ocean_scene.js missing"));
  Promise.all([loadModule().catch(function (e) {
    var why = String(e && e.message || e);
    if (/could not load/.test(why) && !MOCK) why += "\nThe Ocean module is web/evo_ocean.js + .wasm, built by wasm/build_ocean.sh.";
    throw new Error(why);
  }), sceneReady]).then(function (r) {
    M = r[0];
    var missing = REQUIRED.filter(function (f) { return typeof M["_" + f] !== "function"; });
    if (missing.length) throw new Error("the module lacks exports: " + missing.join(", "));
    if (!M.wasmMemory && !M.HEAPU8) throw new Error("the module exposes neither wasmMemory nor HEAPU8");
    if (!HO) throw new Error("ocean_handoff.js did not load");
    if (!M._malloc) throw new Error("the module does not export _malloc/_free");
    HAS_VZ = has("oc_creature_vz");
    /* the appearance genome: the exports, a layout and laws this page renders (web/ocean_appearance.js) */
    HAS_APP = ["oc_creature_appearance", "oc_appearance_count", "oc_appearance_abi", "oc_appearance_stride",
               "oc_pattern_law", "oc_morphology_law"].every(has) && !!window.EvoAppearance &&
              M._oc_appearance_abi() === EvoAppearance.LAWS.abi && M._oc_appearance_stride() === EvoAppearance.STRIDE &&
              M._oc_pattern_law() === EvoAppearance.LAWS.patternLaw && M._oc_morphology_law() === EvoAppearance.LAWS.morphLaw;
    HAS_EYE = has("oc_has_eye") && !!M._oc_has_eye();
    if (!HAS_EYE) ["eye", "eyeOnly", "eyeCode"].forEach(function (k) {
      var i = el("o_" + k); if (i) i.disabled = true;
      var row = el("f_" + k); if (row) row.querySelectorAll(".stepper button").forEach(function (b) { b.disabled = true; });
    });
    /* the URL's world: ?seed / ?pop / ?depth, ?cfg (JSON; one that is not
     * goes to oc_init as it is, so it says why), ?e1=1 under it. The setup
     * goes to oc_init as it is (importWorld), and into the sheet only once
     * accepted: a value the sheet would round or drop is refused with the
     * engine's reason, not quietly changed. A repeated key: the engine's
     * rule (HO.parseFirst), its first occurrence counts and every one is
     * checked, here and by oc_init. */
    var rawCfg = P.get("cfg") || "", userCfg = {}, cfgRepeats = [], badCfg = false;
    if (rawCfg) {
      try {
        var pf = HO.parseFirst(rawCfg);
        userCfg = pf.value;
        cfgRepeats = pf.repeats.filter(function (r) { return !r.path.length; });
        if (!userCfg || typeof userCfg !== "object" || Array.isArray(userCfg)) badCfg = true;
      } catch (e) { badCfg = true; }
    }
    if (E1 && !has("oc_e1_preset")) throw new Error("?e1=1 needs oc_e1_preset: rebuild web/evo_ocean (wasm/build_ocean.sh)");
    var cfg0 = badCfg ? {} : Object.assign({}, E1 ? e1Preset() : {}, userCfg);
    /* The link's numbers, as written: a value outside oc_init's limits (or
     * not a number) refuses the link with the reason, as a setup file does;
     * nothing is clamped into range. */
    var linkBad = [];
    var num = function (key, def, ok, what) {
      if (!P.has(key)) return def;
      var v = Number(P.get(key));
      if (!ok(v)) linkBad.push(key + "=" + P.get(key) + " (" + what + ")");
      return v;
    };
    var seed0 = num("seed", KEYS.seed[0], function (v) { return wholeIn(v, [0, 4294967295]); }, "a whole number from 0 to 4294967295");
    var pop0 = num("pop", KEYS.population[0], function (v) { return wholeIn(v, LIM.population); }, "a whole number from 0 to " + LIM.population[1]);
    var depth0 = num("depth", KEYS.depth[0], depthOk, "from " + LIM.depth[0] + " to " + LIM.depth[1]);
    var sideWhat = "a whole number from " + LIM.side[0] + " to " + LIM.side[1];
    num("w", 0, function (v) { return wholeIn(v, LIM.side); }, sideWhat);
    num("h", 0, function (v) { return wholeIn(v, LIM.side); }, sideWhat);
    /* the sides: ?walls=1 / 0 (written by every Restart); a link without it
     * from before walls existed wraps as it always did (and so does a ?cfg=
     * without "walls"); a bare address — a new visit — starts with glass
     * walls (CFG.FRESH), when this module has them. walls= is written into
     * the cfg's own (first) "walls" either way, never deleted: a later
     * "walls" in ?cfg= (cfgRepeats) still goes to oc_init to be checked, and
     * would be the one it runs if the first were gone. An Ocean link is one
     * with any of OCEAN_KEYS (below, at the start). */
    var freshVisit = OCEAN_KEYS.every(function (k) { return !P.has(k); });
    if (P.has("walls")) {
      var wv = P.get("walls");
      if (wv === "1") cfg0.walls = true;
      else if (wv === "0") cfg0.walls = false;
      else linkBad.push("walls=" + wv + " (1 or 0)");
    } else if (freshVisit && hasWalls()) {
      Object.keys(CFG.FRESH).forEach(function (k) { if (!(k in cfg0)) cfg0[k] = CFG.FRESH[k]; });
    }
    if (linkBad.length) {
      linkRefused = true;
      throw new Error("This link's setup was refused: " + linkBad.join("; ") + ".");
    }
    var refused = importWorld(seed0 >>> 0, pop0, depth0, cfg0, badCfg ? rawCfg : undefined, badCfg ? [] : cfgRepeats, fittedWorld());
    if (refused) {
      linkRefused = !!(rawCfg || E1 || P.has("walls"));
      throw new Error("This link's settings were refused: " + refused);
    }
    scene = EvoOceanScene.create(canvas, {
      tankDepth: D,
      coarse: coarseMQ.matches,
      reducedMotion: reducedMQ.matches,
      bodyScale: bodyScale, onFollowChange: onFollowChange,
      profiler: PERF ? PROF : null, visualRandom: BENCH ? PERF.visualRandom(2463534242) : null
    });
    if (!scene) throw new Error("This browser could not start WebGL2, which the 3-D tank needs. 2-D Classic draws its world without it.");
    detail0 = scene.quality();
    scene.setWorld(W, H, D, { walls: WALLS });
    scene.setLight(LIGHT);
    if (scene.setAppearance) scene.setAppearance(colourMode === "appearance");
    labelHist();
    wireInput();
    updateInsets();
    updateLight();
    updateModeline();
    applyClarity();
    if (dash()) dash().attach({
      depth: function () { return D; },
      /* (the charts' timer: never into a stopped or restarting engine; a trap here stops it once) */
      familyColor: function (id) { return engineCall(function () { return has("oc_family_color") ? M._oc_family_color(id) : 0x3b5957; }, 0x3b5957); },
      wiring: function () { return turboState !== "live" ? wiringNow() : engineCall(wiringNow, null); },
      setDrawer: setDrawer,
      /* the charts cover the page: no popover left open under them, and the coach mark goes */
      onOpen: function () { setPop(null); hideCoach(); },
      setRecEvery: function (every) {
        if (turboWorker && (turboState === "entering" || turboState === "turbo")) turboWorker.postMessage({ cmd: "rec", every: every });
      }
    });
    window.EvoOcean = {
      module: M, scene: scene,
      steepest: function (sinking) {
        var s = fresh(lastS), best = -1, bv = 0;
        if (!s || !s.vz) return null;
        for (var i = 0; i < s.n; i++) { var v = sinking ? s.vz[i] : Math.abs(s.vz[i]); if (v > bv) { bv = v; best = i; } }
        return best < 0 ? null : { idx: best, id: s.ids[best], vz: s.vz[best], x: s.segs[12 * best], y: s.segs[12 * best + 1],
                                   x1: s.segs[12 * best + 2], y1: s.segs[12 * best + 3], depth: s.depth[best] };
      },
      set: function (name, v) {
        return engineCall(function () {
          if (!has("oc_set_param")) return false;
          var ok = withCString(String(name), function (p) { return M._oc_set_param(p, +v); });
          if (!ok) console.warn("oc_set_param(" + name + "): " + lastError());
          readLight();
          return !!ok;
        }, false);
      },
      select: function (idx) { engineCall(function () { var s = fresh(lastS); if (s && idx >= 0 && idx < s.n) select(s.ids[idx]); }); },
      /* index of the deepest fish right now (-1 with none) */
      deepest: function () {
        var s = fresh(lastS), best = -1;
        if (s) for (var i = 0; i < s.n; i++) if (best < 0 || s.depth[i] > s.depth[best]) best = i;
        return best;
      },
      follow: follow,
      turbo: function () { return turboState; },
      state: function () {
        var s = fresh(lastS);
        if (!s) return null;
        var lo = Infinity, hi = -Infinity;
        for (var i = 0; i < s.n; i++) { lo = Math.min(lo, s.depth[i]); hi = Math.max(hi, s.depth[i]); }
        return { n: s.n, fc: s.fc, pc: s.pc, W: W, H: H, D: D, paused: paused, speed: speed(), steps: lastSteps,
                 hasVz: HAS_VZ, view: scene.view(), e1: E1, cfg: initArgs ? initArgs.cfg : null, seed: initArgs ? initArgs.seed : null,
                 runCfg: Object.assign({}, runCfg), light: LIGHT, flashlight: scene.flashlight(), flashlightLevel: scene.flashlightLevel(),
                 stepMs: stepMs, fps: fps, following: scene.following(), selectedId: selectedId, selIdx: s.selIdx,
                 turbo: turboState, colourMode: colourMode, colourBrain: colourBrain, frame: s.stats[1],
                 held: live.held(), inflight: live.inflight(), fixedSize: [URL_W, URL_H], walls: WALLS, hasWalls: hasWalls(),
                 stats: Array.prototype.slice.call(s.stats), depthMin: s.n ? lo : 0, depthMax: s.n ? hi : 0,
                 dashRows: dash() ? dash()._rows().length : 0, worldEpoch: worldEpoch,
                 engine: engineState, rebuilds: rebuilds, engineId: pinned ? pinned.sha256 : null };
      }
    };
    if (PROF.enabled) EvoOcean.perf = PROF;   /* ?renderBench=1 / ?perf=1 (web/ocean_perf.js) */
    if (BENCH) EvoOcean.bench = PERF.bench({ module: M, scene: scene, profiler: PROF, page: EvoOcean, setPaused: setPaused,
      last: function () { return fresh(lastS); }, epoch: function () { return worldEpoch; }, initArgs: function () { return initArgs; },
      importWorld: importWorld,
      /* the page's own colour switch and state, and whether the charts are up (they suspend the tank) */
      setColourMode: setColourMode, colourMode: function () { return colourMode; },
      dashOpen: function () { return !!(dash() && dash().isOpen()); } });
    requestAnimationFrame(frame);
    window.EvoApp.ready = true;
    window.dispatchEvent(new Event("evo:ready"));
    setTimeout(function () {
      if (!everSelected && selectedId === null && turboState === "live" && !document.getElementById("guide"))
        toast(coarseMQ.matches ? "Tap any fish to see its brain." : "Click any fish to see its brain; F follows one with a flashlight.");
    }, 9000);
    startCoach();   /* later: the Turbo coach mark, once */
  }).catch(function (e) {
    var why = String(e && e.message || e);
    splashSay("The 3-D Ocean could not start.\n" + why, true);
    /* the ways on, over the splash that covers the page: this link fresh,
     * and 2-D Classic (#to2d's address, which the deploy build rewrites) */
    var acts = document.createElement("div");
    acts.className = "splash-acts";
    if (linkRefused) {   /* this page with the default settings: a fresh visit's, every world key gone (glass walls) */
      var u = new URL(location.href), a = document.createElement("a");
      /* Classic's too, or the head would take what is left to Classic; the display ones (colour, clarity, ...) stay */
      OCEAN_KEYS.concat(CLASSIC_KEYS).forEach(function (k) { u.searchParams.delete(k); });
      a.href = u.href; a.id = "splashplain"; a.className = "btn";
      a.textContent = "Open it with the default settings";
      acts.appendChild(a);
    }
    if (!noSimd) {
      var c = document.createElement("a");
      c.href = el("to2d").href; c.id = "splashclassic"; c.className = "btn" + (linkRefused ? "" : " primary");
      c.textContent = "Open 2-D Classic";
      acts.appendChild(c);
    }
    if (acts.children.length) el("splashstate").parentNode.appendChild(acts);
    console.error("ocean: " + why);
  });
})();
