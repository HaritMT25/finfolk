"use strict";
/* evo_boids page controller: the simulation loop, the world canvas, and every control.
 * World: 1 unit = 1 px, origin top-left, +y down (canvas-native).
 * No interpolation, no trails, no wrap ghosts. Typed-array views are re-created
 * after every _evo_sync/_evo_inspect (memory growth invalidates buffers).
 *
 * The world canvas (scene, selection ring, HUD, inspector) is drawn the way the
 * native SFML window draws it. Compact screens leave the HUD and the inspector
 * off the canvas and show them as DOM instead (the readout and the fish card).
 * Everything around the world (top bar, dock, settings, Turbo, toasts) is DOM,
 * laid out in CSS px.
 *
 * The tank view (the default; the Run tab's switch, or ?view=flat / ?view=3d)
 * draws the same world as a 3D picture instead (web/scene3d.js, three.js,
 * loaded when first needed) on its own canvas; the selected fish is then the
 * card on every screen. The flat view is the native window's picture. */
(function () {
  var DEFAULT_W = 1920, DEFAULT_H = 1080, TAU = Math.PI * 2;
  var WORLD_W = DEFAULT_W, WORLD_H = DEFAULT_H; /* may change on checkpoint load */
  var RADII = [5, 3.5, 3, 2.5, 2, 1.5];
  var SEG_ALPHA = [255, 225, 195, 165, 135, 105].map(function (a) { return a / 255; });
  /* Drawn radius = RADII[seg] * bodyScale(bodySize), floored at MIN_RADIUS so a
   * small body still has a visible tail. bodySize is core-clamped to [0.5, 2],
   * but its realised standing spread is narrow (sd ~0.08 about 1.0), so a plain
   * multiply would separate two typical neighbours by a couple of tenths of a
   * pixel. tanh gives slope BODY_SPAN*BODY_GAIN = 2 where the population
   * actually sits and saturates at +/-BODY_SPAN, so the rails stay sane — a 2.0
   * body draws 1.4x, not 2x. tanh(0) is exactly 0, so a default 1.0 body
   * multiplies by exactly 1.0 and draws the pixels it always did. */
  var BODY_GAIN = 5, BODY_SPAN = 0.4, MIN_RADIUS = 1;
  /* Same formula as SfmlRenderer::drawCreatures — the two frontends must match. */
  function bodyScale(b) {
    if (!(b > 0)) return 1;  /* absent buffer (older wasm blob) or NaN */
    return 1 + BODY_SPAN * Math.tanh(BODY_GAIN * (b - 1));
  }
  /* evo_inspect_info(): id, speed, foodReserves, age, bodySize, bodyElong, generation, lineageId. */
  var INSPECT_INFO_LEN = 8;
  var CUR_TAIL = "rgba(110,170,215," + (60 / 255).toFixed(4) + ")";
  var CUR_HEAD = "rgba(150,205,235," + (130 / 255).toFixed(4) + ")";
  var RING_STYLE = "rgba(255,235,120," + (230 / 255).toFixed(4) + ")";
  var ACTION_NAMES = ["steerX", "steerY", "moveFwd", "moveRnd", "speed", "signal",
                      "oscPer", "resp", "share", "repro", "fight", "ignore"];
  /* the fish card's names for the same actions (compact screens) */
  var ACTION_LABELS = ["steer x", "steer y", "swim forward", "wander", "speed", "signal",
                       "oscillator period", "respond", "share food", "reproduce", "fight", "ignore"];
  var ACTION_SHORT = ["steer x", "steer y", "forward", "wander", "speed", "signal",
                      "osc", "respond", "share", "breed", "fight", "ignore"];

  /* Advanced config, grouped: [sectionName, [[key, default, {step,min,options}], ...]] */
  var ADV_SECTIONS = [
    ["food", [
      ["targetFood", 600], ["foodSpawnBase", 3], ["foodSpawnAmp", 2], ["foodEnergy", 5],
      ["foodPatchRadius", 120], ["foodDrift", false]
    ]],
    ["energy & life", [
      ["metabolicRate", 1.5], ["moveCost", 0, { step: 0.00001 }],
      ["geneCost", 0, { step: 0.001 }], ["maxAge", 120],
      ["reproEnergy", 20], ["newbornEnergy", 25]
    ]],
    ["population", [
      ["maxPopulation", 0, { step: 1, min: 0 }],
      ["minPopulation", 50, { step: 1, min: 0 }]
    ]],
    ["motion", [
      ["minSpeed", 30], ["maxSpeed", 150], ["maxTurnRate", 4], ["triangularMotion", false]
    ]],
    ["perception & social", [
      ["perceptionRadius", 80], ["interactRadius", 20],
      ["maxNeighbors", 0, { step: 1 }]
    ]],
    ["genome", [
      ["mutationMultiplier", 1, { step: 0.1 }], ["genomeInitMin", 24], ["genomeInitMax", 48],
      ["genomeMinLength", 16], ["genomeMaxLength", 80],
      ["reproMaxDistance", -1, { step: 0.5 }],
      ["reproSoftWidth", 0, { step: 0.5, min: 0 }],
      ["reproGracePeriod", 0, { step: 10, min: 0 }],
      ["bodyMutation", 0.1, { step: 0.01, min: 0 }]
    ]],
    ["predators", [
      ["predatorSpeed", 110], ["predatorPerception", 150], ["predatorCaptureRadius", 14],
      ["predatorCooldown", 3, { step: 0.5, min: 0 }],
      ["predatorMeal", -1, { step: 0.5 }],
      ["predatorMetabolism", 2], ["predatorReproEnergy", 60], ["predatorMaxAge", 0],
      ["predatorMinPopulation", 0, { step: 1, min: 0 }], ["predatorMaxPopulation", 0, { step: 1, min: 0 }],
      ["predatorInheritance", false], ["predatorTraitMutation", 0.1, { step: 0.01, min: 0 }]
    ]],
    ["currents", [
      ["currentMode", 0, { options: ["Eddies", "Gyre"] }],
      ["currentEddies", 5], ["currentCore", 150], ["currentDrift", 1]
    ]],
    ["numerics", [
      ["fastTanh", false]
    ]]
  ];
  /* Flat view: readAdvanced/resetAdvanced iterate every key regardless of section. */
  var ADV = ADV_SECTIONS.reduce(function (acc, sec) { return acc.concat(sec[1]); }, []);
  var ADV_BY_KEY = {};
  ADV.forEach(function (a) { ADV_BY_KEY[a[0]] = a; });
  /* The basic settings: ids without the adv_ prefix (readForm, the randomizer
   * and the guide use them by id). */
  var BASIC = {
    seed: [42, { step: 1, min: 0 }], population: [300, { step: 1, min: 1 }],
    toroidal: [false], bodyModel: [false],
    predators: [0, { step: 1, min: 0 }], predatorEconomy: [false],
    foodPatches: [0, { step: 1, min: 0 }], currentStrength: [0, { step: 1, min: 0 }]
  };
  /* Keys the running world accepts mid-run (evo_set_param's whitelist in
   * wasm/evo_wasm.cpp). Editing one applies immediately; every other key
   * applies on Restart. */
  var LIVE = { maxPopulation: 1, minPopulation: 1, targetFood: 1, foodSpawnBase: 1,
               foodSpawnAmp: 1, foodEnergy: 1, metabolicRate: 1, moveCost: 1, geneCost: 1,
               maxAge: 1, reproEnergy: 1, newbornEnergy: 1, mutationMultiplier: 1,
               minSpeed: 1, maxSpeed: 1,
               predatorMinPopulation: 1, predatorMaxPopulation: 1, predatorTraitMutation: 1 };

  /* The settings: tabs, then groups of keys ("b:" = a basic setting). */
  var SETTINGS_TABS = [
    { id: "run", title: "Run" },
    { id: "world", title: "World", groups: [
      ["The world", ["b:seed", "b:population", "b:toroidal", "b:bodyModel"]],
      ["Population limits", ["maxPopulation", "minPopulation"]],
      ["Movement", ["minSpeed", "maxSpeed", "triangularMotion", "maxTurnRate"]],
      ["Senses", ["perceptionRadius", "interactRadius", "maxNeighbors"]],
      ["Numerics", ["fastTanh"]]] },
    { id: "food", title: "Food", groups: [
      ["Food", ["b:foodPatches", "foodPatchRadius", "targetFood", "foodSpawnBase", "foodSpawnAmp", "foodEnergy", "foodDrift"]]] },
    { id: "life", title: "Life", groups: [
      ["Energy and age", ["metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy", "newbornEnergy"]],
      ["Genes", ["mutationMultiplier", "genomeInitMin", "genomeInitMax", "genomeMinLength", "genomeMaxLength"]],
      ["Who can breed", ["reproMaxDistance", "reproSoftWidth", "reproGracePeriod"]],
      ["Bodies", ["bodyMutation"]]] },
    { id: "predators", title: "Predators", groups: [
      ["Predators", ["b:predators", "b:predatorEconomy"]],
      ["Hunting", ["predatorSpeed", "predatorPerception", "predatorCaptureRadius", "predatorCooldown"]],
      ["Their economy", ["predatorMeal", "predatorMetabolism", "predatorReproEnergy", "predatorMaxAge"]],
      ["Limits and inheritance", ["predatorMinPopulation", "predatorMaxPopulation", "predatorInheritance", "predatorTraitMutation"]]] },
    { id: "ocean", title: "Ocean", groups: [
      ["Currents", ["b:currentStrength", "currentMode", "currentEddies", "currentCore", "currentDrift"]]] }
  ];
  /* Display names; the config key is shown under each one. */
  var LABELS = {
    seed: "Seed", population: "Starting fish", toroidal: "Senses wrap around the edges", bodyModel: "Evolving bodies",
    predators: "Predators", predatorEconomy: "Predators eat, breed and starve",
    foodPatches: "Food patches", currentStrength: "Current strength",
    targetFood: "Food target", foodSpawnBase: "Food per step", foodSpawnAmp: "Food swing",
    foodEnergy: "Energy per food", foodPatchRadius: "Patch radius", foodDrift: "Food drifts with the current",
    metabolicRate: "Energy burned per second", moveCost: "Swimming cost", geneCost: "Cost per gene",
    maxAge: "Lifespan (s)", reproEnergy: "Energy needed to breed", newbornEnergy: "Newborn energy",
    maxPopulation: "Population cap", minPopulation: "Reseed floor",
    minSpeed: "Slowest speed", maxSpeed: "Fastest speed", maxTurnRate: "Turn rate",
    triangularMotion: "Fast swims straight, slow turns",
    perceptionRadius: "Sight radius", interactRadius: "Touch radius", maxNeighbors: "Neighbours watched",
    mutationMultiplier: "Mutation rate ×", genomeInitMin: "Starting genes, fewest",
    genomeInitMax: "Starting genes, most", genomeMinLength: "Genes, minimum", genomeMaxLength: "Genes, maximum",
    reproMaxDistance: "Breeding distance limit", reproSoftWidth: "Soft limit width",
    reproGracePeriod: "Founder grace (s)", bodyMutation: "Body mutation",
    predatorSpeed: "Predator speed", predatorPerception: "Predator sight", predatorCaptureRadius: "Catch distance",
    predatorCooldown: "Digesting time (s)", predatorMeal: "Energy per catch",
    predatorMetabolism: "Predator energy burn", predatorReproEnergy: "Energy to bud a child",
    predatorMaxAge: "Predator lifespan", predatorMinPopulation: "Predator floor",
    predatorMaxPopulation: "Predator cap", predatorInheritance: "Hunters inherit traits",
    predatorTraitMutation: "Trait mutation", currentMode: "Current shape", currentEddies: "Eddies",
    currentCore: "Eddy radius", currentDrift: "How fast the flow changes", fastTanh: "Fast tanh"
  };
  var HINTS = {
    maxPopulation: "0 = none", minPopulation: "founders added below this",
    maxNeighbors: "0 = everyone in range", reproMaxDistance: "-1 = off",
    reproSoftWidth: "0 = a hard limit", reproGracePeriod: "0 = off", predatorMeal: "-1 = the prey's whole store",
    predatorMaxAge: "0 = until it starves", predatorMinPopulation: "0 = off; put back below this",
    predatorMaxPopulation: "0 = none", currentDrift: "0 = a still pattern", fastTanh: "changes the numbers"
  };
  /* what one press of − / + changes */
  var BTN_STEP = {
    seed: 1, population: 50, predators: 1, foodPatches: 1, currentStrength: 10,
    targetFood: 50, foodSpawnBase: 1, foodSpawnAmp: 0.5, foodEnergy: 0.5, foodPatchRadius: 10,
    metabolicRate: 0.1, moveCost: 0.00001, geneCost: 0.001, maxAge: 10, reproEnergy: 1, newbornEnergy: 1,
    maxPopulation: 50, minPopulation: 10, minSpeed: 5, maxSpeed: 5, maxTurnRate: 0.5,
    perceptionRadius: 5, interactRadius: 1, maxNeighbors: 1, mutationMultiplier: 0.1,
    genomeInitMin: 1, genomeInitMax: 1, genomeMinLength: 1, genomeMaxLength: 1,
    reproMaxDistance: 0.5, reproSoftWidth: 0.5, reproGracePeriod: 10, bodyMutation: 0.01,
    predatorSpeed: 5, predatorPerception: 5, predatorCaptureRadius: 1, predatorCooldown: 0.5,
    predatorMeal: 0.5, predatorMetabolism: 0.1, predatorReproEnergy: 5, predatorMaxAge: 10,
    predatorMinPopulation: 1, predatorMaxPopulation: 5, predatorTraitMutation: 0.01,
    currentEddies: 1, currentCore: 10, currentDrift: 0.1
  };

  /* Hover info per parameter: d = what it is, t = suggested values (docs/evo_boids_flags.md). */
  var TIPS = {
    seed: { get d() {
      return "RNG seed — on the single-threaded module the same seed and the same settings replay a run step for step, as long as no " +
        "live setting changes during it and Hold 60 fps removes no fish. " + (threaded
          ? "This page runs the threaded module: fast, but its runs do not replay from the seed."
          : "This page runs the single-threaded module" + (threadWhy ? " (" + threadWhy + ")" : "") + ".");
    }, t: "try: any uint32; keep it to reproduce a run" },
    population: { get d() {
      /* the floor the running world took (runCfg: a start's, a loaded world's, an applied live edit's), not the form's */
      var floor = runFloor(), form = intVal("adv_minPopulation", floor);
      return "Starting creature count. " + (floor > 0
        ? "Whenever fewer than the reseed floor (" + floor + " in this run, under World → Population limits) are alive, random founders are added."
        : "This run's reseed floor is 0 (World → Population limits): no founders are added, so the population can die out.") +
        (form !== floor ? " The form's " + form + " is not in this run: Restart starts a world with it." : "");
    }, t: "try: 200-800; >2000 gets slow in-browser" },
    predators: { d: "Number of scripted hunters chasing prey (0 = none).", t: "try: 3-4 with predator economy on" },
    foodPatches: { d: "Cluster food into N spatial patches (0 = uniform scatter).", t: "try: 5-6; patchy food makes currents matter" },
    currentStrength: { d: "Peak ocean-flow speed in world units/sec (0 = still water).", t: "try: 80 with eddies = a lively ocean" },
    predatorEconomy: { d: "Predators eat, breed and starve (Stage B) instead of being immortal.", t: "try: on with 4 predators, energy per catch 9 and a predator cap of 15 (held both sides in 12 of 12 measured runs at 9-11)" },
    toroidal: { d: "Senses wrap across the world seam — no walls, no sensory dead zone at edges.", t: "try: on; cures the wall-hugger phenotype" },
    reproMaxDistance: { d: "Reproductive isolation: parents farther apart than this in wiring space cannot breed (-1 = off).", t: "try: 18 bites gently, 14 hard; below 12 breeding stops" },
    reproSoftWidth: { d: "Softens the isolation gate into a ramp: past the gate distance breeding fades out over this width instead of stopping dead (0 = hard cliff).", t: "try: 4-5 with the gate at 14-16; needs the gate on" },
    reproGracePeriod: { d: "Founders — the first generation and every reseeded refill — ignore the gate while younger than this, so a fresh genome can breed once (0 = off).", t: "try: 60; 5 or below does nothing (breeding already needs age > 5)" },
    bodyModel: { d: "Heritable body size + elongation: bigger = slower and costlier, longer = turns worse.", t: "try: on; founders start at 1.0 and bodies drift from births" },
    bodyMutation: { d: "Body-model only: uniform jitter half-width added to each inherited body parameter.", t: "try: 0.1 default; 0 freezes drift, 0.3 explores fast" },
    targetFood: { d: "Baseline food count the world regrows toward (hard cap 2x).", t: "try: 300 scarcity, 1200 abundance" },
    foodSpawnBase: { d: "Mean food items spawned per step.", t: "try: 2-12; higher = richer world" },
    foodSpawnAmp: { d: "Sinusoidal swing of food abundance around the base rate.", t: "try: 0 for a steady food supply" },
    foodEnergy: { d: "Energy gained per food item eaten.", t: "try: 3-8 around the default 5" },
    foodPatchRadius: { d: "Spread of food around each patch centre.", t: "try: 60 tight, 240 loose" },
    foodDrift: { d: "Food is advected with the current into drifting filaments.", t: "try: on — pairs well with currents" },
    metabolicRate: { d: "Fixed energy burned per second by every creature.", t: "try: toward 3 for harsher starvation" },
    moveCost: { d: "Kinetic cost: energy/sec = F x speed^2 — makes thrust expensive.", t: "try: 0.00007 -> cruise ~82; 0 = free" },
    geneCost: { d: "Extra energy/sec per gene — parsimony pressure against bloat.", t: "try: 0.005 makes big genomes costly" },
    maxAge: { d: "Age in seconds at which a creature dies of old age.", t: "try: 60-240 around the default 120" },
    reproEnergy: { d: "Energy a parent needs before it can reproduce.", t: "try: 15-40; higher = slower breeding" },
    newbornEnergy: { d: "Starting energy of a newborn child.", t: "try: 15-35 around the default 25" },
    minSpeed: { d: "Minimum swim speed.", t: "try: 0 when moveCost > 0 (drifting allowed)" },
    maxSpeed: { d: "Maximum swim speed — the sprint ceiling.", t: "try: 150; sprinting escapes predators at 110" },
    maxTurnRate: { d: "Turn ceiling (rad/s) at zero drive — triangular motion only.", t: "try: 2-6 around the default 4" },
    triangularMotion: { d: "Couple drive and turn: fast = straight, slow = agile.", t: "try: on for strike-vs-reorient bouts" },
    perceptionRadius: { d: "Sensing radius for neighbours, food and predators.", t: "try: 160 = high-density schooling regime" },
    interactRadius: { d: "Range for social interactions (share / fight).", t: "try: 10-40 around the default 20" },
    maxNeighbors: { d: "Attend to only the N nearest neighbours; 0 = everyone in range.", t: "try: 7 — starlings track ~6-7" },
    mutationMultiplier: { d: "Multiplier on the per-birth mutation rate.", t: "try: 0.5 conservative, 2 fast drift" },
    genomeInitMin: { d: "Low end of the initial gene-count range.", t: "try: init 24-48 inside bounds 16-80" },
    genomeInitMax: { d: "High end of the initial gene-count range.", t: "try: init 24-48 inside bounds 16-80" },
    genomeMinLength: { d: "Hard lower bound on gene count.", t: "try: 16 (the default)" },
    genomeMaxLength: { d: "Hard upper bound on gene count.", t: "try: 80 (the default)" },
    predatorSpeed: { d: "Predator cruise speed.", t: "try: 110 vs prey max 150 = escapable" },
    predatorPerception: { d: "Predator's prey-detection radius; above prey's 80 = ambush edge.", t: "try: 80 for symmetric sight" },
    predatorCaptureRadius: { d: "Contact distance at which a prey is caught.", t: "try: 10-20 around the default 14" },
    predatorCooldown: { d: "Seconds a predator digests after a catch before it can catch again — caps its kill rate.", t: "try: 3-5; 5 eases the chase" },
    predatorMeal: { d: "Energy a predator gains per catch (economy on). -1 = it absorbs the prey's whole reserve, which lets predators explode.", t: "try: 1.2 × break-even, which is cooldown × (metabolism + thrust cost × 110²) = 6 at the defaults, so 7; at 1.0 hunters never bud, and richer than ~1.3 they over-eat the fish unless a predator cap holds them" },
    predatorMetabolism: { d: "Predator energy burn per second (economy on); prey burn 1.5.", t: "try: 2-3; higher = must hunt more" },
    predatorReproEnergy: { d: "Energy a predator needs to bud a child (economy on).", t: "try: 40-80; higher = slower breeding" },
    predatorMaxAge: { d: "Predator death age; 0 = immortal until starved.", t: "try: 0, or 120 to age them out" },
    predatorMinPopulation: { d: "Predator floor: fresh hunters are put back whenever fewer than this are alive, so they can't die out (economy on; 0 = off). The Predators chart counts how many it put back. Applies live.", t: "try: 2; it stops extinction but not a crash (the fish stay low while it feeds hunters), so pair it with a cap" },
    predatorMaxPopulation: { d: "Predator cap: a well-fed hunter doesn't bud while this many are alive; it keeps the energy and buds once there is room (economy on; 0 = none). Applies live.", t: "try: 15 with the default 3 s digesting time. Each capped hunter catches about once per digesting time, so keep cap ÷ digesting time below the fish births per second (Dashboards → Population)" },
    predatorInheritance: { d: "Each bud inherits its parent's speed and budding threshold (×0.5 to ×2), each with a small mutation, so hunters evolve. Speed only costs energy when the swimming cost (moveCost) is above 0.", t: "try: on with a swimming cost (0.00007), a predator lifespan (120) and a cap; measured that way, hunters evolved slower (×0.83) and quicker to bud (×0.85). With free swimming, speed climbs toward ×2 and they over-eat" },
    predatorTraitMutation: { d: "How far a bud's traits can stray from its parent's, per trait per bud. Applies live.", t: "try: 0.1 (the default); 0 copies exactly" },
    currentMode: { d: "eddies = moving vortices; gyre = two counter-rotating basins.", t: "try: eddies with strength 80" },
    currentEddies: { d: "Number of vortices in eddies mode.", t: "try: 3-8 around the default 5" },
    currentCore: { d: "Eddy radius — the distance of peak flow speed.", t: "try: 100-250 around the default 150" },
    currentDrift: { d: "How fast the flow field evolves (0 = static).", t: "try: 0.5-2 around the default 1" },
    fastTanh: { d: "~1.25x faster tanh approximation — changes the numbers.", t: "try: off to reproduce native runs" },
    maxPopulation: { d: "Birth cap: no births while the population is at or above it (0 = none). Applies live.", t: "try: 0; the frame-budget governor may set a lower one" },
    minPopulation: { d: "Reseed floor: random founders are added when the population falls below it. Applies live.", t: "try: 50 (the default)" },
    governor: { d: "When frames take too long: first lower the speed (in the tank view, first draw the tank with less detail), then remove creatures at random (no trait favoured) and cap births at what this machine can run at 60 fps. Each step is reported; a governed run no longer replays from its seed.", t: "try: on; off to see the uncapped run (it may stutter)" },
    fishShape: { d: "Draws each fish as one smooth body over the six spine points the simulation keeps, instead of a circle at each point. Its half-width at each point is that point's circle radius and its length is the spine itself, so body size and elongation show as they do with circles; the tail fin is an addition that grows with body size. Needs WebGL2 (the canvas-2D fallback keeps the circles); the native app draws circles.", t: "try: on for a fish look; off to match the native window" },
    colourBrain: { d: "Off: each family line (every fish descended from the same starting fish) has its own colour, the one it has in the dashboards, so you can watch families spread and take over. On: the colour comes from the genome's wiring, so similar brains look alike. Long runs tend to turn blue there, because evolution keeps finding the same rules for using a fish's own energy, and those happen to point at blue (README).", t: "try: off to follow families, on to see what their brains converged on" },
    view3d: { d: "Draws the same world as a 3D tank seen at an angle: fish bent along their spine in their genome colour, lit and shaded, plus motion the simulation does not have (tail beats, swim heights, drifting specks, caustic light). Distances look shorter far away, and the world still wraps at its edges. The simulation and every setting are unchanged.", t: "try: on for looks; off to see the world as the simulation sees it" }
  };

  var ASSETS = window.EVO_ASSETS;
  var Module = null;
  var threaded = false;      /* which module EvoLoader picked */
  var threadWhy = "";
  var moduleUrls = null;     /* {js, wasm} of the loaded module, for the Turbo worker */
  var STATS_LEN = 9;         /* replaced by _evo_stats_len() once loaded */
  var paused = false;
  var simSpeed = 1;
  var selectedId = null;
  /* the running world's config (non-default keys), for the dashboards and the fish card */
  var runCfg = {};
  /* the dashboards (web/dashboard.js), when the page has them */
  function dash() { return window.EvoDash || null; }
  function cfgVal(key, def) { return Object.prototype.hasOwnProperty.call(runCfg, key) ? runCfg[key] : def; }

  var canvas = document.getElementById("canvas");
  var ctx = canvas.getContext("2d", { alpha: false });
  /* the tank view: off by default; scene3d.js and three.js load on first use */
  var PARAMS = new URLSearchParams(location.search);
  var VIEW_KEY = "evo_boids.view";
  var view3d = false, scene = null, sceneLoad = null, sceneW = 0, sceneH = 0;
  var sceneCanvas = document.getElementById("scene3d");
  var animT = 0;   /* the tank's animation clock: runs with the world, stops when it stops */
  var reducedMQ = window.matchMedia("(prefers-reduced-motion: reduce)");
  var bgImage = new Image();  /* background texture — shared with the native app (img/rocks.jpg) */
  bgImage.src = ASSETS.background;
  function el(id) { return document.getElementById(id); }
  var errEl = el("err");

  /* Compact screens (phones, touch devices, narrow windows): the world-space
   * overlays — HUD text, inspector panel — shrink with the canvas until they
   * are unreadable, so there the inspector is the fish card, laid out in CSS
   * px, and the HUD is left to the readout. Elsewhere the canvas versions
   * stay, matching the native SFML window. */
  /* short windows too: an embed (the portfolio's is 890x453) would otherwise
   * spend a third of its height on the bars around the world */
  var compactMQ = window.matchMedia("(max-width: 700px), (max-height: 560px), (pointer: coarse)");
  var coarseMQ = window.matchMedia("(pointer: coarse)");
  /* the settings sit beside the world from here up, and are a bottom sheet below */
  var wideMQ = window.matchMedia("(min-width: 960px)");
  /* Kind of the last pointer seen. Hover tooltips are for the mouse; a touch
   * tap on a parameter name toggles its tooltip instead (attachTip), and a
   * touch tap selects a fish from farther away (the canvas click handler). */
  var lastPointer = "mouse";
  ["pointerover", "pointerdown"].forEach(function (type) {
    window.addEventListener(type, function (e) { lastPointer = e.pointerType || "mouse"; }, true);
  });
  /* CSS px per world unit at the canvas's current on-screen size. */
  function cssPerWorld() {
    var r = canvas.getBoundingClientRect();
    return r.width > 0 ? r.width / canvas.width : 1;
  }

  /* The wasm heap. In the threaded module it is a growable SharedArrayBuffer,
   * and a growth triggered on another thread leaves Module.HEAP* pointing at
   * the old, shorter buffer — so views are always cut from wasmMemory.buffer,
   * which reflects the current length. Re-created per frame, never cached. */
  function heap() {
    return Module.wasmMemory ? Module.wasmMemory.buffer : Module.HEAPU8.buffer;
  }

  /* ---- messages: the settings footer line, plus a toast seen from anywhere ---- */
  var toastsEl = el("toasts");
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
  function showError(msg) { errEl.textContent = msg; errEl.className = "error"; toast(msg, "error"); }
  function showNote(msg) { errEl.textContent = msg; errEl.className = ""; toast(msg); }
  function clearError() { errEl.textContent = ""; errEl.className = ""; }

  function intVal(id, def) {
    var v = parseInt(el(id).value, 10);
    return Number.isFinite(v) ? v : def;
  }
  function floatVal(id, def) {
    var v = parseFloat(el(id).value);
    return Number.isFinite(v) ? v : def;
  }

  /* ---- settings (built from SETTINGS_TABS) ---- */
  function decimals(x) { var s = String(x); var i = s.indexOf("."); return i < 0 ? (s.indexOf("e-") > 0 ? +s.split("e-")[1] : 0) : s.length - i - 1; }
  function makeStepper(input, key, min) {
    var wrap = document.createElement("span");
    wrap.className = "stepper";
    function button(sign, icon, label) {
      var b = document.createElement("button");
      b.type = "button";
      b.tabIndex = -1;   /* the input itself takes arrow keys */
      b.setAttribute("aria-label", label);
      b.innerHTML = "<svg class='i'><use href='#i-" + icon + "'/></svg>";
      b.addEventListener("click", function () {
        var st = BTN_STEP[key] || 1, v = parseFloat(input.value);
        if (!Number.isFinite(v)) v = 0;
        v = +(v + sign * st).toFixed(Math.max(decimals(st), 0) + 2);
        v = +v.toFixed(Math.max(decimals(st), decimals(v) > 6 ? 6 : decimals(v)));
        if (min !== undefined && v < min) v = min;
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
  function makeField(key, def, opt, basic) {
    opt = opt || {};
    var id = basic ? key : "adv_" + key;
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
    keyEl.textContent = key + (HINTS[key] ? " · " + HINTS[key] : "");
    left.appendChild(name);
    left.appendChild(keyEl);
    var ctl = document.createElement("span");
    ctl.className = "ctl";
    var input;
    if (typeof def === "boolean") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.className = "switch";
      input.setAttribute("role", "switch");
      input.checked = def;
      ctl.appendChild(input);
    } else if (opt.options) {
      input = document.createElement("select");
      opt.options.forEach(function (label, i) {
        var o = document.createElement("option");
        o.value = String(i);
        o.textContent = label;
        input.appendChild(o);
      });
      input.value = String(def);
      ctl.appendChild(input);
    } else {
      input = document.createElement("input");
      input.type = "number";
      input.inputMode = "decimal";
      input.step = opt.step !== undefined ? String(opt.step) : "any";
      /* A lower bound the spinner has no reason to go below: either evo_init
         refuses the value rather than clamping it (bodyMutation), or everything
         under the bound is a synonym for it (a <=0 knob that means "off"). */
      if (opt.min !== undefined) input.min = String(opt.min);
      input.value = String(def);
      ctl.appendChild(makeStepper(input, key, opt.min));
    }
    input.id = id;
    if (LIVE[key]) input.addEventListener("change", function () { applyLive(key, def, input); });
    row.appendChild(left);
    row.appendChild(ctl);
    attachTip(row, key);
    return row;
  }
  /* Push one live-capable knob into the running world. maxPopulation goes
   * through the governor so a user cap and the frame-budget cap combine. */
  function applyLive(key, def, input) {
    if (!Module || turboState !== "live") return;
    var v = parseFloat(input.value);
    if (!Number.isFinite(v)) v = def;
    /* (the run's history changes only with a value: a stepper clamped at its bound still fires change) */
    if (key === "maxPopulation") {
      var cap = Math.max(0, Math.round(v));
      if (cap !== userCap) liveEdited = true;
      userCap = cap; applyCap(); updateModeline(); return;
    }
    if (!Module._evo_set_param) return;
    var ok = withCString(key, function (ptr) { return Module._evo_set_param(ptr, v); });
    if (ok) {
      if (v !== (key in runCfg ? runCfg[key] : def)) liveEdited = true;
      runCfg[key] = v; updateModeline(); showNote((LABELS[key] || key) + " is now " + v + " (live)");
    }
    else showError(Module.UTF8ToString(Module._evo_last_error()));
  }
  var tabsEl = el("tabs"), panelsEl = el("panels"), currentTab = "run";
  function buildSettings() {
    SETTINGS_TABS.forEach(function (tab) {
      var b = document.createElement("button");
      b.type = "button";
      b.id = "tab-" + tab.id;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "panel-" + tab.id);
      b.textContent = tab.title;
      b.addEventListener("click", function () { setSheetTab(tab.id); });
      tabsEl.appendChild(b);
      if (!tab.groups) return;   /* "run" is static HTML */
      var panel = document.createElement("section");
      panel.className = "panel";
      panel.id = "panel-" + tab.id;
      panel.dataset.tab = tab.id;
      panel.setAttribute("role", "tabpanel");
      tab.groups.forEach(function (g) {
        var h = document.createElement("h3");
        h.textContent = g[0];
        panel.appendChild(h);
        g[1].forEach(function (k) {
          if (k.indexOf("b:") === 0) {
            var key = k.slice(2), d = BASIC[key];
            panel.appendChild(makeField(key, d[0], d[1], true));
          } else {
            var a = ADV_BY_KEY[k];
            panel.appendChild(makeField(a[0], a[1], a[2], false));
          }
        });
      });
      panelsEl.appendChild(panel);
    });
    el("panel-run").setAttribute("role", "tabpanel");
    attachTip(el("f_governor"), "governor");
    attachTip(el("f_view3d"), "view3d");
    attachTip(el("f_fishShape"), "fishShape");
    attachTip(el("f_colourBrain"), "colourBrain");
    var saved = null;
    try { saved = localStorage.getItem("evo_boids.tab"); } catch (e) { /* private mode */ }
    setSheetTab(saved && el("panel-" + saved) ? saved : "run");
  }
  function setSheetTab(id) {
    currentTab = id;
    SETTINGS_TABS.forEach(function (tab) {
      var on = tab.id === id;
      el("tab-" + tab.id).setAttribute("aria-selected", on ? "true" : "false");
      el("tab-" + tab.id).tabIndex = on ? 0 : -1;
      el("panel-" + tab.id).hidden = !on;
    });
    panelsEl.scrollTop = 0;
    hideTip();
    try { localStorage.setItem("evo_boids.tab", id); } catch (e) { /* private mode */ }
  }
  tabsEl.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var ids = SETTINGS_TABS.map(function (t) { return t.id; });
    var i = ids.indexOf(currentTab) + (e.key === "ArrowRight" ? 1 : -1);
    i = (i + ids.length) % ids.length;
    setSheetTab(ids[i]);
    el("tab-" + ids[i]).focus();
    e.preventDefault();
  });
  /* a dot on each tab that holds a setting changed from its default */
  function updateTabDots() {
    SETTINGS_TABS.forEach(function (tab) {
      if (!tab.groups) return;
      var changed = tab.groups.some(function (g) {
        return g[1].some(function (k) {
          var basic = k.indexOf("b:") === 0, key = basic ? k.slice(2) : k;
          if (key === "seed" || key === "population") return false;
          var def = basic ? BASIC[key][0] : ADV_BY_KEY[key][1];
          var input = el(basic ? key : "adv_" + key);
          if (typeof def === "boolean") return input.checked !== def;
          var v = parseFloat(input.value);
          return Number.isFinite(v) && v !== def;
        });
      });
      var b = el("tab-" + tab.id), dot = b.querySelector(".dot");
      if (changed && !dot) { dot = document.createElement("span"); dot.className = "dot"; dot.title = "changed from the default"; b.appendChild(dot); }
      else if (!changed && dot) b.removeChild(dot);
    });
  }
  function resetAdvanced() {
    ADV.forEach(function (a) {
      var input = el("adv_" + a[0]);
      if (typeof a[1] === "boolean") input.checked = a[1];
      else input.value = String(a[1]);
    });
  }
  function readAdvanced(cfg) {
    ADV.forEach(function (a) {
      var key = a[0], def = a[1], input = el("adv_" + key);
      if (typeof def === "boolean") {
        if (input.checked !== def) cfg[key] = input.checked;
      } else {
        var v = parseFloat(input.value);
        if (!Number.isFinite(v)) v = def;
        if (v !== def) cfg[key] = v;
      }
    });
  }

  /* Build config JSON with only the non-default keys. */
  function readForm() {
    var cfg = {};
    var predators = intVal("predators", 0);
    var foodPatches = intVal("foodPatches", 0);
    var currentStrength = floatVal("currentStrength", 0);
    if (el("toroidal").checked) cfg.toroidal = true;
    if (el("bodyModel").checked) cfg.bodyModel = true;
    if (predators !== 0) cfg.predatorCount = predators;
    if (el("predatorEconomy").checked) cfg.predatorEconomy = true;
    if (currentStrength !== 0) cfg.currentStrength = currentStrength;
    if (foodPatches !== 0) cfg.foodPatches = foodPatches;
    readAdvanced(cfg);
    return { seed: intVal("seed", 42) >>> 0, population: intVal("population", 300), cfg: cfg };
  }

  function withCString(str, fn) {
    var size = Module.lengthBytesUTF8(str) + 1;
    var ptr = Module._malloc(size);
    Module.stringToUTF8(str, ptr, size);
    var r = fn(ptr);
    Module._free(ptr);
    return r;
  }

  /* World size for a (re)start. A landscape screen with a mouse keeps the
   * native 1920x1080. A portrait screen, or any touch screen, gets a world of
   * the same area (so food density and crowding stay the same) shaped like
   * the stage, so the world fills a phone instead of a 16:9 strip across it.
   * A loaded checkpoint carries its own size. */
  function fittedWorld() {
    var r = el("stage").getBoundingClientRect();
    /* the stage's width with the settings closed (on wide screens the open
     * settings narrow it): 6 px a side, none on compact screens */
    var aspect = (document.documentElement.clientWidth - (compactMQ.matches ? 0 : 12)) / r.height;
    if (!(aspect > 0) || (aspect >= 1 && !coarseMQ.matches)) return [DEFAULT_W, DEFAULT_H];
    aspect = Math.max(0.4, Math.min(2.5, aspect));
    var w = Math.round(Math.sqrt(DEFAULT_W * DEFAULT_H * aspect));
    return [w, Math.round(DEFAULT_W * DEFAULT_H / w)];
  }
  /* After a rotation or resize the running world keeps its shape
   * (letterboxed). A button offers to restart with a fitted one on compact
   * screens, and wherever the world was, or would now be, fitted; a
   * landscape desktop window running the native 1920x1080 never shows it. */
  var worldFitted = false;  /* the running world came from fittedWorld(), not the default */
  function updateFitButton() {
    var f = fittedWorld(), a = f[0] / f[1], b = WORLD_W / WORLD_H;
    var fits = compactMQ.matches || worldFitted || f[0] !== DEFAULT_W || f[1] !== DEFAULT_H;
    el("fitbtn").hidden = !!bench || !fits || Math.max(a, b) / Math.min(a, b) < 1.15;
  }

  function restart() {
    if (!Module) return false;
    if (guardTurbo()) return false;
    clearError();
    var f = readForm();
    var size = fittedWorld();
    WORLD_W = size[0]; WORLD_H = size[1];
    worldFitted = WORLD_W !== DEFAULT_W || WORLD_H !== DEFAULT_H;
    if (canvas.width !== WORLD_W) canvas.width = WORLD_W;
    if (canvas.height !== WORLD_H) canvas.height = WORLD_H;
    var ok = initWorld(f.seed, f.population, f.cfg);
    updateFitButton();
    setPending(false);
    el("randnote").textContent = "";  /* randomize() fills it in after a pick */
    return ok;
  }

  /* ---- Randomize: a whole setup drawn from tested ranges ----
   * The ranges, and the rules that keep coupled knobs together, live in
   * web/randomizer.js. This fills the form with the draw (everything else
   * back to its default), restarts, and lists what it picked. */
  var BASIC_DEFAULTS = { toroidal: false, bodyModel: false, predators: 0,
                         predatorEconomy: false, foodPatches: 0, currentStrength: 0 };
  var basePop = 0;   /* this device's default population; set at boot */
  function setField(input, v) {
    if (input.type === "checkbox") input.checked = !!v;
    else input.value = String(v);
  }
  function randomize() {
    if (!Module || !window.EvoRandom || guardTurbo()) return;
    var pick = EvoRandom.draw(Math.random, basePop);
    resetAdvanced();
    Object.keys(BASIC_DEFAULTS).forEach(function (id) {
      setField(el(id), id in pick.form ? pick.form[id] : BASIC_DEFAULTS[id]);
    });
    Object.keys(pick.adv).forEach(function (key) {
      var input = el("adv_" + key);
      if (input) setField(input, pick.adv[key]);
    });
    el("population").value = String(pick.population);
    el("seed").value = String((Math.random() * 0x100000000) >>> 0);
    updateNeeds();
    updateTabDots();
    if (restart()) {
      var what = pick.population + " fish" +
        (pick.labels.length ? " · " + pick.labels.join(" · ") : " · the default world");
      el("randnote").textContent = "Picked: " + what + ". Every setting is in the tabs above.";
      toast("New world: " + what);
    }
  }
  function initWorld(seed, population, cfg) {
    var ok;
    if (Object.keys(cfg).length > 0) {
      ok = withCString(JSON.stringify(cfg), function (ptr) {
        return Module._evo_init(seed, WORLD_W, WORLD_H, population, ptr);
      });
    } else {
      ok = Module._evo_init(seed, WORLD_W, WORLD_H, population, 0);
    }
    selectedId = null;
    if (glScene && glScene.forgetFish) glScene.forgetFish();
    userCap = cfg.maxPopulation || 0;
    autoCap = 0;
    resetGovernor();
    if (!ok) showError("evo_init failed: " + Module.UTF8ToString(Module._evo_last_error()));
    else { runCfg = cfg; governed = false; liveEdited = false; loadedRun = false; updateModeline(); if (dash()) dash().reset(); }   /* a new run: new charts */
    return !!ok;
  }

  /* ---- per-frame data: resolve selection + _evo_inspect BEFORE creating views ---- */
  function resolveSelection() {
    if (selectedId === null) return -1;
    var n = Module._evo_creature_count();
    var ids = new Float64Array(heap(), Module._evo_creature_ids(), n);
    var idx = -1;
    for (var i = 0; i < n; i++) if (ids[i] === selectedId) { idx = i; break; }
    if (idx >= 0 && !Module._evo_inspect(idx)) idx = -1;
    if (idx < 0) selectedId = null;
    return idx;
  }

  function snapshot(selIdx) {
    var n = Module._evo_creature_count();
    var fc = Module._evo_food_count();
    var pc = Module._evo_predator_count();
    var s = {
      n: n, fc: fc, pc: pc, selIdx: selIdx,
      segs: new Float32Array(heap(), Module._evo_creature_segments(), n * 12),
      /* the tank keys each fish's swim height, tail phase and trail to its id */
      ids: new Float64Array(heap(), Module._evo_creature_ids(), n),
      /* N*2 alongside segs, same creature order; absent from pre-0.24 blobs */
      body: Module._evo_body_params
              ? new Float32Array(heap(), Module._evo_body_params(), n * 2)
              : null,
      colors: new Uint8Array(heap(), Module._evo_creature_colors(), n * 3),
      food: new Float32Array(heap(), Module._evo_food_xy(), fc * 2),
      preds: new Float32Array(heap(), Module._evo_predator_data(), pc * 3),
      stats: new Float64Array(heap(), Module._evo_stats(), STATS_LEN),
      curActive: Module._evo_current_active() !== 0,
      curGrid: null, curCols: 0, curRows: 0
    };
    if (s.curActive) {
      s.curCols = Module._evo_current_cols();
      s.curRows = Module._evo_current_rows();
      s.curGrid = new Float32Array(heap(), Module._evo_current_grid(),
                                   s.curCols * s.curRows * 2);
    }
    if (selIdx >= 0) {
      s.info = new Float64Array(heap(), Module._evo_inspect_info(), INSPECT_INFO_LEN);
      s.sensors = new Float32Array(heap(), Module._evo_inspect_sensors(), 41);
      s.hidden = new Float32Array(heap(), Module._evo_inspect_hidden(), 12);
      s.actions = new Float32Array(heap(), Module._evo_inspect_actions(), 12);
      s.connCount = Module._evo_inspect_conn_count();
      s.conns = new Float32Array(heap(), Module._evo_inspect_conns(), s.connCount * 5);
    }
    return s;
  }

  /* ---- neural inspector panel (drawn last, above HUD) ---- */
  function colY(i, n, yTop, yBot) {
    return n <= 1 ? (yTop + yBot) / 2 : yTop + (yBot - yTop) * i / (n - 1);
  }
  function activationColor(v) {
    var m = Math.min(1, Math.abs(v));
    var lo = 45;
    var hot = lo + Math.round((235 - lo) * m);
    var mid = Math.round(lo + (v >= 0 ? 60 : 90) * (1 - m));
    return v >= 0 ? "rgb(" + hot + "," + mid + "," + lo + ")"
                  : "rgb(" + lo + "," + mid + "," + hot + ")";
  }
  /* Canvas x of the settings panel's left edge (WORLD_W when it is closed, a
   * bottom sheet, or off the canvas). The inspector's default home is the
   * canvas's top-right, so it has to step aside if the panel overlaps it. */
  function drawerLeftInCanvas() {
    if (!drawerEl.classList.contains("open") || !wideMQ.matches) return WORLD_W;
    var cr = canvas.getBoundingClientRect();
    if (cr.width <= 0) return WORLD_W;
    var x = (drawerEl.getBoundingClientRect().left - cr.left) * (canvas.width / cr.width);
    return Math.min(WORLD_W, x);
  }
  /* The network: 1. connections, under 2. the nodes. sen/hid/act map a node
   * index to its [x, y]; g is the 2D context to draw into. */
  function drawNet(g, s, sen, hid, act, rSen, rNode) {
    g.lineWidth = 1;
    for (var k = 0; k < s.connCount; k++) {
      var o = k * 5;
      var srcSen = s.conns[o] !== 0;
      var srcNum = s.conns[o + 1] | 0;
      var sinkAct = s.conns[o + 2] !== 0;
      var sinkNum = s.conns[o + 3] | 0;
      var w = s.conns[o + 4];
      var a = srcSen ? sen(srcNum) : hid(srcNum);
      var b = sinkAct ? act(sinkNum) : hid(sinkNum);
      var srcAct = srcSen ? s.sensors[srcNum] : s.hidden[srcNum];
      var mag = Math.min(1, Math.abs(w) * Math.abs(srcAct) * 1.5);
      var alpha = ((25 + Math.round(180 * mag)) / 255).toFixed(4);
      g.strokeStyle = (w >= 0 ? "rgba(120,200,130," : "rgba(210,120,120,") + alpha + ")";
      g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
    }
    function node(p, r, v) {
      g.fillStyle = activationColor(v);
      g.beginPath(); g.arc(p[0], p[1], r, 0, TAU); g.fill();
      g.strokeStyle = "rgba(0,0,0," + (160 / 255).toFixed(4) + ")";
      g.lineWidth = 1;
      g.stroke();
    }
    var i;
    for (i = 0; i < 41; i++) node(sen(i), rSen, s.sensors[i]);
    for (i = 0; i < 12; i++) node(hid(i), rNode, s.hidden[i]);
    for (i = 0; i < 12; i++) node(act(i), rNode, s.actions[i]);
  }
  /* Canvas inspector panel, in world px: top-right by default; with the
   * settings panel over the canvas, just left of its edge (follows it while it
   * slides), never off the canvas's left side. */
  var INSP_W = 340, INSP_H = 560, INSP_Y = 44;
  function inspectorX() {
    return Math.max(12, Math.min(WORLD_W - INSP_W - 12, drawerLeftInCanvas() - INSP_W - 12));
  }
  function drawInspector(s) {
    var pw = INSP_W, ph = INSP_H, py = INSP_Y;
    var px = inspectorX();
    ctx.fillStyle = "rgba(10,22,30," + (205 / 255).toFixed(4) + ")";
    ctx.fillRect(px, py, pw, ph);
    ctx.strokeStyle = "rgba(90,140,150," + (220 / 255).toFixed(4) + ")";
    ctx.lineWidth = 1;
    ctx.strokeRect(px + 0.5, py + 0.5, pw - 1, ph - 1);
    var xS = px + 30, xH = px + 170, xA = px + 310;
    var yTop = py + 46, yBot = py + ph - 22;
    var i;

    drawNet(ctx, s,
            function (n) { return [xS, colY(n, 41, yTop, yBot)]; },
            function (n) { return [xH, colY(n, 12, yTop, yBot)]; },
            function (n) { return [xA, colY(n, 12, yTop, yBot)]; }, 3, 5);

    /* 3. text */
    ctx.font = "13px monospace";
    ctx.fillStyle = "rgba(220,235,240," + (235 / 255).toFixed(4) + ")";
    ctx.fillText("Fish #" + Math.round(s.info[0]) + "   spd " + Math.round(s.info[1]) +
                 "   E " + Math.round(s.info[2]) + "   age " + Math.round(s.info[3]),
                 px + 12, py + 19);
    /* Body params get their own line at the panel foot — appended to the title
     * they would run past the 340px panel. Always drawn: the page has no view of
     * cfg.bodyModel, and a fixed 1.00 / 1.00 is itself the readout for a run
     * with the model off. */
    ctx.font = "11px monospace";
    ctx.fillStyle = "rgba(190,205,210," + (220 / 255).toFixed(4) + ")";
    ctx.fillText("body " + s.info[4].toFixed(2) + "   elong " + s.info[5].toFixed(2) +
                 "   gen " + Math.round(s.info[6]),
                 px + 12, py + ph - 8);
    ctx.fillStyle = "rgba(150,175,180," + (200 / 255).toFixed(4) + ")";
    var hy = yTop - 18 + 11; /* text top at yTop-18, ~11px to baseline */
    ctx.fillText("in", xS - 8, hy);
    ctx.fillText("hidden", xH - 20, hy);
    ctx.fillText("out", xA - 12, hy);
    ctx.font = "10px monospace";
    ctx.fillStyle = "rgba(190,205,210," + (220 / 255).toFixed(4) + ")";
    for (i = 0; i < 12; i++) ctx.fillText(ACTION_NAMES[i], xA + 8, colY(i, 12, yTop, yBot) + 3);
  }

  /* ---- compact screens: the selected fish as a card ----
   * Its numbers, with bars against the run's settings, and its live brain,
   * drawn in CSS px at devicePixelRatio so the text stays readable however
   * small the world is on screen. Tapping (or pointing at) a node names it. */
  var cardEl = el("fishcard"), inetCanvas = el("inetc"), inetCtx = inetCanvas.getContext("2d");
  var portrait = el("iportrait"), portraitCtx = portrait.getContext("2d");
  var cardExpanded = window.innerWidth >= 600, cardCache = {}, cardFor = null;
  el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");   /* the tour reads it */
  var sensorNames = null, netNodes = [], netHover = -1, uiFont = "";
  function prettyName(n) {
    return String(n).replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  }
  function senseName(i) {
    if (!sensorNames && Module && Module._evo_sensor_names) {
      sensorNames = Module.UTF8ToString(Module._evo_sensor_names()).split(",").map(prettyName);
    }
    return sensorNames && sensorNames[i] ? sensorNames[i] : "sense " + (i + 1);
  }
  function setText(id, v) { if (cardCache[id] !== v) { cardCache[id] = v; el(id).textContent = v; } }
  function setBar(id, f, tick) {
    f = Math.max(0, Math.min(1, f));
    var key = id + "|" + f.toFixed(3) + "|" + (tick === undefined ? "" : tick.toFixed(3));
    if (cardCache[id + "bar"] === key) return;
    cardCache[id + "bar"] = key;
    var bar = el(id);
    bar.firstElementChild.style.transform = "scaleX(" + f.toFixed(3) + ")";
    var t = bar.querySelector(".tick");
    if (t) t.style.left = "calc(" + ((tick || 0) * 100).toFixed(1) + "% - 1px)";
  }
  function showCard() {
    cardEl.hidden = false;
    document.body.classList.add("card-open");   /* hides the fit button under it */
    cardEl.classList.toggle("expanded", cardExpanded);
    el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    cardCache = {};
  }
  function hideCard() {
    if (cardEl.hidden) return;
    if (scene && scene.following()) scene.setFollow(false);
    cardEl.hidden = true;
    cardFor = null;
    netHover = -1;
    cardFlip = false;
    cardEl.classList.remove("flip");
    document.body.classList.remove("card-open");
  }
  /* The card's home is the bottom of a narrow screen (the right of a wider
   * one); .flip puts it at the top (the left). Like a docked panel it moves
   * only when the selected fish swims under it, to the side away from it. */
  var cardFlip = false;
  function placeCard(fx, fy) {   /* the selected fish, in CSS px */
    var r = cardEl.getBoundingClientRect(), m = 24;
    if (fx < r.left - m || fx > r.right + m || fy < r.top - m || fy > r.bottom + m) return;
    var narrow = window.innerWidth < 600;
    var flip = narrow ? fy > window.innerHeight / 2 : fx > window.innerWidth / 2;
    if (flip === cardFlip) return;
    cardFlip = flip;
    cardEl.classList.toggle("flip", flip);
  }
  function drawPortrait(rgb, size, elong) {
    var dpr = window.devicePixelRatio || 1, w = 56, h = 40;
    if (portrait.width !== w * dpr) { portrait.width = w * dpr; portrait.height = h * dpr; }
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
    g.beginPath(); g.arc(-6.2 * k / 1.2, -1.2, 1.1, 0, TAU); g.fill();
    g.setTransform(1, 0, 0, 1, 0, 0);
  }
  function updateCard(s) {
    if (s.selIdx < 0 || !s.info) { hideCard(); return; }
    if (cardEl.hidden) showCard();
    /* layout reads first, DOM writes last, so a frame never forces a
     * synchronous reflow (except right after a rare side change) */
    if (view3d) {
      var p = scene.project(s, s.selIdx);   /* null: behind the camera */
      if (p) placeCard(p.x, p.y);
    } else {
      var cr = canvas.getBoundingClientRect(), c = cr.width / canvas.width;
      placeCard(cr.left + s.segs[12 * s.selIdx] * c, cr.top + s.segs[12 * s.selIdx + 1] * c);
    }
    var info = s.info, id = Math.round(info[0]);
    var rgb = [s.colors[3 * s.selIdx], s.colors[3 * s.selIdx + 1], s.colors[3 * s.selIdx + 2]];
    var pkey = id + "|" + rgb.join() + "|" + info[4].toFixed(2) + "|" + info[5].toFixed(2);
    if (cardFor !== pkey) { cardFor = pkey; drawPortrait(rgb, info[4], info[5]); }
    setText("ititle", "Fish #" + id);
    setText("isub", "Generation " + Math.round(info[6]) + " · family #" + Math.round(info[7]) +
            (cfgVal("bodyModel", false) ? " · body " + info[4].toFixed(2) + " × " + info[5].toFixed(2) : ""));
    var reproE = cfgVal("reproEnergy", 20), maxAge = cfgVal("maxAge", 120), maxSpd = cfgVal("maxSpeed", 150);
    setText("ienergyv", info[2].toFixed(1));
    setBar("ienergy", info[2] / (reproE * 2), 0.5);
    el("ienergy").title = info[2] >= reproE ? "enough energy to breed" : "needs " + reproE + " to breed";
    setText("iagev", Math.round(info[3]) + " s");
    setBar("iage", info[3] / maxAge);
    setText("ispeedv", String(Math.round(info[1])));
    setBar("ispeed", info[1] / maxSpd);
    if (cardExpanded) drawBrain(s);
  }

  /* The card's network: senses -> hidden -> actions. Links are drawn first,
   * nodes on top; nodes keep their screen positions for the tap-to-name line. */
  function brainColor(v, a) {
    var m = Math.min(1, Math.abs(v));
    return v >= 0 ? "rgba(" + Math.round(70 + 130 * m) + "," + Math.round(90 + 150 * m) + "," + Math.round(60 + 10 * m) + "," + a + ")"
                  : "rgba(" + Math.round(80 + 175 * m) + "," + Math.round(90 + 20 * m) + "," + Math.round(70 + 10 * m) + "," + a + ")";
  }
  function drawBrain(s) {
    var box = inetCanvas.parentNode, w = box.clientWidth, h = box.clientHeight;
    if (w < 60 || h < 60) return;
    var dpr = window.devicePixelRatio || 1, bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (inetCanvas.width !== bw) inetCanvas.width = bw;
    if (inetCanvas.height !== bh) inetCanvas.height = bh;
    var g = inetCtx, i;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    var wide = w > h * 1.15, pos = { sen: [], hid: [], act: [] };
    var m = 14;
    if (wide) {
      var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
      for (i = 0; i < 41; i++) pos.sen.push([m + (w - 2 * m) * i / 40, yIn]);
      for (i = 0; i < 12; i++) { var x = m + 18 + (w - 2 * m - 36) * i / 11; pos.hid.push([x, yHid]); pos.act.push([x, yOut]); }
    } else {
      var yTop = 26, yBot = h - 12, xS = 18, xA = w - 92, xH = (xS + xA) / 2;
      for (i = 0; i < 41; i++) pos.sen.push([xS, yTop + (yBot - yTop) * i / 40]);
      for (i = 0; i < 12; i++) { var y = yTop + (yBot - yTop) * i / 11; pos.hid.push([xH, y]); pos.act.push([xA, y]); }
    }
    /* links: curved, brighter and thicker the more they carry right now */
    var hoverKey = netHover >= 0 && netNodes[netHover] ? netNodes[netHover].kind + netNodes[netHover].i : null;
    for (var k = 0; k < s.connCount; k++) {
      var o = k * 5;
      var srcSen = s.conns[o] !== 0, srcNum = s.conns[o + 1] | 0;
      var sinkAct = s.conns[o + 2] !== 0, sinkNum = s.conns[o + 3] | 0, wgt = s.conns[o + 4];
      var a = srcSen ? pos.sen[srcNum] : pos.hid[srcNum];
      var b = sinkAct ? pos.act[sinkNum] : pos.hid[sinkNum];
      if (!a || !b) continue;
      var srcAct = srcSen ? s.sensors[srcNum] : s.hidden[srcNum];
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
      g.beginPath(); g.arc(p[0], p[1], r, 0, TAU); g.fill();
      g.strokeStyle = "rgba(4,14,16,0.85)";
      g.lineWidth = 1;
      g.stroke();
      netNodes.push({ x: p[0], y: p[1], kind: kind, i: idx, v: v });
    }
    var rs = Math.max(2, Math.min(3.2, (wide ? w : h) / 41 * 0.36));
    for (i = 0; i < 41; i++) node(pos.sen[i], rs, s.sensors[i], "Sense", i);
    for (i = 0; i < 12; i++) node(pos.hid[i], 5, s.hidden[i], "Hidden neuron", i);
    for (i = 0; i < 12; i++) node(pos.act[i], 5.5, s.actions[i], "Action", i);
    if (netHover >= 0 && netNodes[netHover]) {
      var hn = netNodes[netHover];
      g.strokeStyle = "rgba(230,255,160,0.95)"; g.lineWidth = 2;
      g.beginPath(); g.arc(hn.x, hn.y, 8, 0, TAU); g.stroke();
    }
    if (!uiFont) uiFont = getComputedStyle(document.body).fontFamily;
    g.font = "11px " + uiFont;
    g.fillStyle = "rgba(190,210,205,0.9)";
    function tag(text, x, y) {   /* a label on a small backing, readable over the links */
      var tw = g.measureText(text).width;
      g.fillStyle = "rgba(15,39,39,0.92)";
      g.fillRect(x - 3, y - 10, tw + 6, 14);
      g.fillStyle = "rgba(190,210,205,0.95)";
      g.fillText(text, x, y);
    }
    if (wide) {
      tag("senses", m, 13);
      tag("hidden", m, (26 + h - 40) / 2 - 9);
      g.fillStyle = "rgba(190,210,205,0.9)";
      g.textAlign = "center";
      for (i = 0; i < 12; i++) g.fillText(ACTION_SHORT[i], pos.act[i][0], h - 40 + (i % 2 ? 30 : 18));
      g.textAlign = "left";
    } else {
      g.fillText("senses", 6, 13);
      g.fillText("hidden", (18 + w - 92) / 2 - 18, 13);
      g.fillText("actions", w - 98, 13);
      for (i = 0; i < 12; i++) g.fillText(ACTION_LABELS[i], pos.act[i][0] + 10, pos.act[i][1] + 4);
    }
    updateSenseLine();
  }
  var DEFAULT_SENSE = "Senses on one side, actions on the other. Lime links excite, orange ones inhibit; brighter = stronger right now. Tap a dot to name it.";
  function updateSenseLine() {
    var html;
    if (netHover >= 0 && netNodes[netHover]) {
      var n = netNodes[netHover];
      var label = n.kind === "Sense" ? senseName(n.i) : n.kind === "Action" ? ACTION_LABELS[n.i] : "neuron " + (n.i + 1);
      html = n.kind + ": <b></b> " + (n.v >= 0 ? "+" : "") + n.v.toFixed(2);
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

  /* Scene layer (background, currents, food, creatures, predators): WebGL2
   * when available (web/gl_renderer.js; one instanced draw per kind), else the
   * 2D path below. Both read the same constants, so they draw the same scene;
   * ?gl=0 forces 2D. Overlays (ring, HUD, inspector) are always 2D, on top. */
  var LOOK = {
    radii: RADII, segAlpha: SEG_ALPHA, minRadius: MIN_RADIUS, bodyScale: bodyScale,
    /* fish shapes (opt-in): one body over the six spine points; the fin's
     * length and spread are world px at body scale 1 */
    fishShape: false, fin: { len: 6, spread: 4.5, alpha: 0.55 },
    clear: [0x0F / 255, 0x1E / 255, 0x19 / 255],
    food: [0x97 / 255, 0xC6 / 255, 0x32 / 255],
    predDigesting: [150 / 255, 60 / 255, 60 / 255],
    predHunting: [220 / 255, 50 / 255, 50 / 255],
    curTail: [110 / 255, 170 / 255, 215 / 255, 60 / 255],
    curHead: [150 / 255, 205 / 255, 235 / 255, 130 / 255]
  };
  var glScene = null;
  if (window.EvoGL && new URLSearchParams(location.search).get("gl") !== "0") {
    glScene = EvoGL.create(WORLD_W, WORLD_H, bgImage, LOOK);
  }

  function draw(s, stepped) {
    if (view3d) {   /* the tank view: no canvas overlays, the card on every screen */
      if (sceneW !== WORLD_W || sceneH !== WORLD_H) { sceneW = WORLD_W; sceneH = WORLD_H; scene.setWorld(WORLD_W, WORLD_H); }
      scene.render(s, { animT: animT, dtSim: stepped / 60, selIdx: s.selIdx });
      updateCard(s);
      return;
    }
    if (glScene) glScene.resize(WORLD_W, WORLD_H);  /* world size changes on checkpoint load */
    var layer = glScene ? glScene.draw(s, WORLD_W, WORLD_H) : null;
    if (layer) ctx.drawImage(layer, 0, 0);
    else drawScene2D(s);
    drawOverlays(s);
  }

  function drawScene2D(s) {
    ctx.fillStyle = "#0F1E19";
    ctx.fillRect(0, 0, WORLD_W, WORLD_H);
    /* Background texture under everything, cover-scaled to the world (works at
     * any image resolution and after a checkpoint changes the world size); the
     * flat clear colour stays as the fallback while it loads or if missing. */
    if (bgImage.complete && bgImage.naturalWidth > 0) {
      var bs = Math.max(WORLD_W / bgImage.naturalWidth, WORLD_H / bgImage.naturalHeight);
      var bw = bgImage.naturalWidth * bs, bh = bgImage.naturalHeight * bs;
      ctx.drawImage(bgImage, (WORLD_W - bw) / 2, (WORLD_H - bh) / 2, bw, bh);
    }

    if (s.curActive) {
      ctx.lineWidth = 1;
      for (var j = 0; j < s.curRows; j++) {
        for (var i = 0; i < s.curCols; i++) {
          var k = (j * s.curCols + i) * 2;
          var vx = s.curGrid[k], vy = s.curGrid[k + 1];
          if (vx * vx + vy * vy < 1) continue;
          var x0 = 32 + 64 * i, y0 = 32 + 64 * j;
          var x1 = x0 + vx * 0.45, y1 = y0 + vy * 0.45;
          var grad = ctx.createLinearGradient(x0, y0, x1, y1);
          grad.addColorStop(0, CUR_TAIL);
          grad.addColorStop(1, CUR_HEAD);
          ctx.strokeStyle = grad;
          ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
        }
      }
    }

    ctx.fillStyle = "#97C632";
    ctx.beginPath();
    for (var fi = 0; fi < s.fc; fi++) {
      var fx = s.food[2 * fi], fy = s.food[2 * fi + 1];
      ctx.moveTo(fx + 2.5, fy);
      ctx.arc(fx, fy, 2.5, 0, TAU);
    }
    ctx.fill();

    for (var c = 0; c < s.n; c++) {
      var rgb = s.colors[3 * c] + "," + s.colors[3 * c + 1] + "," + s.colors[3 * c + 2];
      var bs = bodyScale(s.body ? s.body[2 * c] : 1);
      for (var seg = 0; seg < 6; seg++) {
        ctx.fillStyle = "rgba(" + rgb + "," + SEG_ALPHA[seg] + ")";
        ctx.beginPath();
        ctx.arc(s.segs[12 * c + 2 * seg], s.segs[12 * c + 2 * seg + 1],
                Math.max(MIN_RADIUS, RADII[seg] * bs), 0, TAU);
        ctx.fill();
      }
    }

    for (var p = 0; p < s.pc; p++) {
      ctx.fillStyle = s.preds[3 * p + 2] > 0 ? "rgb(150,60,60)" : "rgb(220,50,50)";
      ctx.beginPath();
      ctx.arc(s.preds[3 * p], s.preds[3 * p + 1], 6.5, 0, TAU);
      ctx.fill();
    }
  }

  function drawOverlays(s) {
    var compact = compactMQ.matches;
    if (s.selIdx >= 0) {
      /* on compact screens the ring keeps a ~14 CSS px radius on screen */
      var k = compact ? Math.max(1, 0.9 / cssPerWorld()) : 1;
      ctx.strokeStyle = RING_STYLE;
      ctx.lineWidth = 2 * k;
      ctx.beginPath();
      ctx.arc(s.segs[12 * s.selIdx], s.segs[12 * s.selIdx + 1], 16 * k, 0, TAU);
      ctx.stroke();
    }
    if (compact) {  /* no HUD or canvas inspector: the readout and the fish card */
      updateCard(s);
      return;
    }
    hideCard();

    var st = s.stats, fmt = function (v) { return String(Math.round(v)); };
    ctx.font = "14px monospace";
    ctx.fillStyle = "rgba(200,200,200,0.78)";
    ctx.fillText(
      "pop " + fmt(st[0]) + "  food " + fmt(st[1]) + "  pred " + fmt(st[2]) +
      "  frame " + fmt(st[3]) + "  total births " + fmt(st[6]) + "  total deaths " + fmt(st[7]) +
      "  gLen " + st[8].toFixed(1) +
      (STATS_LEN > 10 ? "  gen " + fmt(st[10]) + " (avg " + st[9].toFixed(1) + ")" : "") +
      "  speed " + simSpeed + "x" + (paused ? " [PAUSED]" : ""),
      10, 18);
    ctx.fillText("[Space] pause  [Up/Down] speed  [R] restart  [click] inspect", 10, 36);

    if (s.selIdx >= 0) drawInspector(s); /* last: above HUD */
  }

  /* ---- frame budget: degrade agent count rather than stutter ----
   * workMs = step + sync + draw for one frame. When its moving average stays
   * over BUDGET_MS (of a 16.7 ms frame), first the speed steps back toward 1x;
   * at 1x a target count is sized from the measured cost per creature, the
   * surplus is removed uniformly at random (_evo_cull_to: favours no trait),
   * and a birth cap (maxPopulation) holds it there. A birth cap alone is too
   * slow — it only bites as creatures die, which takes up to maxAge (120 sim
   * seconds). With sustained headroom and the population pressing on the cap,
   * the cap is raised again. A governed run no longer replays from its seed;
   * the readout marks it, and the governor can be switched off. */
  var BUDGET_MS = 12;
  var MIN_CAP = 60;
  /* Starting population per module (README.md, "Benchmarks"). Touch devices
   * (phones, tablets) start lighter, on at most TOUCH_THREADS threads, to go
   * easier on battery and heat; the governor still fits the run to the
   * device, and the settings can raise the population. */
  var DEFAULT_POP_SINGLE = 300, DEFAULT_POP_THREADED = 600;
  var TOUCH_POP_SINGLE = 200, TOUCH_POP_THREADED = 400, TOUCH_THREADS = 4;
  var workEma = 0, overFrames = 0, underFrames = 0;
  var userCap = 0, autoCap = 0;
  var governorOn = true;
  var govNote = "";
  /* This run's history, for what its seed replays. Set as it happens; cleared only when a new world is
   * accepted (initWorld's evo_init, a loaded file): a refused Restart or file leaves the run, and them, as they were. */
  var governed = false;   /* the governor has changed this run (its cap and cull) */
  var liveEdited = false;  /* a live setting's value changed during this run (applyLive) */
  var loadedRun = false;   /* this run carries on from a loaded checkpoint */
  /* the reasons this single-threaded run does not replay from its seed: [key, words] */
  function replayReasons() {
    var not = [];
    if (governed) not.push(["governed", "the frame budget removed fish from it"]);
    if (liveEdited) not.push(["live", "a live setting changed during it"]);
    if (loadedRun) not.push(["loaded", "it carries on from a loaded world"]);
    return not;
  }
  /* the reseed floor the running world took: runCfg's (a start's non-default keys, a loaded world's config,
   * an applied live edit), else the default */
  function runFloor() {
    var v = runCfg ? runCfg.minPopulation : undefined;
    if (typeof v === "number" && Number.isFinite(v)) return v;
    for (var i = 0; i < ADV.length; i++) if (ADV[i][0] === "minPopulation") return ADV[i][1];
    return 50;
  }
  function replayClaim() {
    var not = replayReasons();
    return "the same seed and settings replay a run step for step" +
      (not.length ? ", but not this one: " + not.map(function (r) { return r[1]; }).join("; ") : "");
  }
  function replayNote() {
    return threaded ? "Threaded runs are fast but do not replay from the seed." : "Single-threaded (" + threadWhy + "): " + replayClaim() + ".";
  }
  /* Time ignored after a (re)start: JIT warm-up and buffer growth would
   * otherwise read as "this machine is too slow". Measured in time, not
   * frames — an overloaded page draws few frames, and waiting for N of them
   * is exactly the stutter this exists to avoid. */
  var WARMUP_MS = 1500, warmupUntil = 0;
  /* Step cost grows faster than the creature count (more creatures = denser
   * water = more neighbours each): fitting wasm/bench.sh's single-threaded
   * column, cost ~ N^1.4. Sizing the cut with that exponent instead of a
   * linear one avoids cutting far deeper than needed. */
  var COST_EXPONENT = 1.4;
  /* Frames must actually be late, not just busy: work over budget can still
   * fit in a frame (seen in headless Firefox, whose software WebGL makes the
   * per-frame JS ~14 ms while it holds 60 fps). intervalEma tracks the time
   * between frames; displayMs is the display's interval, taken as the
   * shortest one seen and never above 60 Hz's, so a page that is overloaded
   * from its first frame is still recognised as late. */
  var intervalEma = 0, lastFrameAt = 0, displayMs = 1000 / 60;
  function trackInterval(now) {
    if (lastFrameAt) {
      var iv = now - lastFrameAt;
      intervalEma = intervalEma ? intervalEma * 0.9 + iv * 0.1 : iv;
      if (intervalEma < displayMs) displayMs = Math.max(4, intervalEma);
    }
    lastFrameAt = now;
  }
  function framesLate() { return intervalEma > displayMs * 1.2; }
  /* the governor's timing and note start over (`governed`, the run's history, stays: an accepted new world clears it) */
  function resetGovernor() {
    workEma = 0; overFrames = 0; underFrames = 0; govNote = "";
    intervalEma = 0;
    warmupUntil = performance.now() + WARMUP_MS;
    restoreDetail();
  }
  /* the tank's full detail again (a restart, a load, the governor off) */
  function restoreDetail() {
    if (scene && scene.setQuality(coarseMQ.matches ? 2 : 3) && Module) updateModeline();
  }
  /* After any action: forget the moving averages (they still remember the
   * frames before the action and would trigger a second, too-deep cut) and
   * let the page run half a second before judging again. */
  function settle() {
    workEma = 0;
    intervalEma = 0;
    warmupUntil = performance.now() + 500;
  }
  function applyCap() {
    if (!Module || !Module._evo_set_param) return;
    var eff = userCap > 0 && autoCap > 0 ? Math.min(userCap, autoCap) : (userCap || autoCap);
    withCString("maxPopulation", function (ptr) { return Module._evo_set_param(ptr, eff); });
  }
  function govern(workMs, pop) {
    if (performance.now() < warmupUntil) return;
    workEma = workEma ? workEma * 0.9 + workMs * 0.1 : workMs;
    if (!governorOn || paused || turboState !== "live" || bench) return;
    if (workEma > BUDGET_MS && framesLate()) { overFrames++; underFrames = 0; }
    else if (workEma < BUDGET_MS * 0.5) { underFrames++; overFrames = 0; }
    else { overFrames = 0; underFrames = 0; }
    /* ~0.5 s of evidence normally; far over budget, a handful of frames */
    if (overFrames >= (workEma > 2 * BUDGET_MS ? 8 : 30)) {
      overFrames = 0;
      var ema = workEma;  /* settle() clears it; size the cut first */
      settle();
      if (view3d && scene.degrade()) {
        /* the tank first: fewer pixels, then no shadows; the run is untouched */
        setGovNote("drew the tank with less detail to hold 60 fps");
        updateModeline();
      } else if (simSpeed > 1) {
        /* work per frame is proportional to steps per frame, so the speed
         * that fits can be computed rather than found one notch at a time */
        setSpeed(Math.min(simSpeed - 1, Math.floor(simSpeed * (BUDGET_MS * 0.8) / ema)));
        setGovNote("speed lowered to " + simSpeed + "× to hold 60 fps");
      } else if (!autoCap || pop <= autoCap * 1.02) {
        /* only tighten once the population has come down to the last cap */
        var target = Math.max(MIN_CAP, Math.floor(
          pop * Math.pow((BUDGET_MS * 0.8) / ema, 1 / COST_EXPONENT)));
        if (Number.isFinite(target) && target < pop && (!autoCap || target < autoCap)) {
          autoCap = target;
          applyCap();
          var removed = Module._evo_cull_to ? Module._evo_cull_to(autoCap) : 0;
          selectedId = null;  /* the inspected creature may be gone */
          governed = true;
          updateModeline();
          setGovNote((removed ? "removed " + removed + " fish at random, " : "") +
                     "capped at " + autoCap + " to hold 60 fps; this run no longer replays from its seed");
        }
      }
    } else if (underFrames >= 180 && autoCap && pop >= autoCap * 0.95) {
      underFrames = 0;
      settle();
      autoCap = Math.round(autoCap * 1.15);
      applyCap();
      setGovNote("population cap raised to " + autoCap);
    }
  }
  function setGovNote(msg) {
    govNote = msg;
    if (msg) toast(msg.charAt(0).toUpperCase() + msg.slice(1) + ".");
  }

  /* ---- live numbers: the readout chip, and its detail panel ---- */
  var fpsFrames = 0, fpsT0 = 0, fps = 0;
  var stepEma = 0;   /* ms per sim step */
  var everSelected = false;  /* a one-time hint until a fish has been picked */
  var statOpen = false, lastStats = null;
  function fmtNum(v) { return Number.isFinite(v) ? Math.round(v).toLocaleString() : "–"; }
  function updateStatus(st) {
    lastStats = st;
    el("ro-fish").textContent = fmtNum(st[0]);
    el("ro-gen").textContent = STATS_LEN > 10 ? fmtNum(st[10]) : "–";
    el("ro-fps").textContent = String(fps);
    el("ro-fps").classList.toggle("warn", fps > 0 && fps < 40);
    el("ro-gov").hidden = !governed;
    if (statOpen) renderStatPanel();
  }
  function renderStatPanel() {
    var st = lastStats, p = el("statpanel");
    if (!st || !Module) { p.textContent = "Starting…"; return; }
    var mode = threaded ? "threaded × " + (Module._evo_threads ? Module._evo_threads() : "?") : "single-threaded";
    var cap = userCap > 0 && autoCap > 0 ? Math.min(userCap, autoCap) : (userCap || autoCap);
    var rows = [
      ["Fish", fmtNum(st[0])], ["Food", fmtNum(st[1])], ["Predators", fmtNum(st[2])],
      ["Births (total)", fmtNum(st[6])], ["Deaths (total)", fmtNum(st[7])],
      ["Generation", STATS_LEN > 10 ? fmtNum(st[10]) + " (avg " + st[9].toFixed(1) + ")" : "–"],
      ["Genes per fish", st[8].toFixed(1)],
      ["Frame", fmtNum(st[3])],
      ["Speed", (paused ? "paused" : simSpeed + "×")],
      ["Step time", stepEma ? stepEma.toFixed(2) + " ms" : "–"],
      ["Frames per second", String(fps)],
      ["Module", mode],
      ["Drawing", drawingName()]
    ];
    if (cap) rows.push(["Population cap", cap + (autoCap && cap === autoCap ? " (auto)" : "")]);
    var html = "<dl>" + rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("") + "</dl>";
    var notes = [];
    if (govNote) notes.push(govNote.charAt(0).toUpperCase() + govNote.slice(1) + ".");
    notes.push(replayNote());
    html += "<div class='notes'>" + notes.map(function () { return "<p></p>"; }).join("") + "</div>";
    p.innerHTML = html;
    p.querySelectorAll(".notes p").forEach(function (node, i) { node.textContent = notes[i]; });
  }
  function setStatPanel(open) {
    statOpen = open;
    el("statpanel").hidden = !open;
    el("readout").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) renderStatPanel();
  }
  el("readout").addEventListener("click", function () { setStatPanel(!statOpen); this.blur(); });
  document.addEventListener("pointerdown", function (e) {
    if (statOpen && !e.target.closest("#statpanel, #readout")) setStatPanel(false);
  });

  function drawingName() {
    return (view3d ? "3D tank, detail " + scene.quality() + " of 3"
                   : (glScene ? "WebGL2" : "canvas 2D") + (LOOK.fishShape ? ", fish shapes" : "")) +
           (colourBrain ? ", coloured by brain" : ", coloured by family");
  }

  var splashDone = false, turboPaint = 0, lastNow = 0;
  function frame(now) {
    if (Module) {
      var dt = lastNow ? Math.min(0.1, (now - lastNow) / 1000) : 0;
      lastNow = now;
      var t0 = performance.now();
      var stepped = 0;
      if (turboState === "live" && !paused) {
        stepped = bench ? 1 : simSpeed;
        Module._evo_step(stepped);
        animT += dt * Math.min(simSpeed, 2);
      }
      if (dash()) dash().pump();   /* what the recorder saw (also a restart's first sample) */
      var t1 = performance.now();
      /* while not 'live' the main sim is frozen: re-sync repacks the same
       * state, so this keeps drawing the last frame (never stale-black) */
      Module._evo_sync();
      var s = snapshot(turboState === "live" ? resolveSelection() : -1);
      /* the dashboards cover the whole page: no point drawing the ocean */
      var covered = dash() && dash().isOpen();
      if (!covered) draw(s, stepped);
      if (turboState !== "live" && now - turboPaint > 250) { turboPaint = now; paintTurbo(); }
      var t2 = performance.now();
      if (stepped) {
        var per = (t1 - t0) / stepped;
        stepEma = stepEma ? stepEma * 0.9 + per * 0.1 : per;
      }
      trackInterval(now);
      govern(t2 - t0, s.n);
      if (bench) benchFrame(now, t1 - t0, t2 - t1, s.n);
      fpsFrames++;
      if (!fpsT0) fpsT0 = now;
      if (now - fpsT0 >= 500) {
        fps = Math.round(fpsFrames * 1000 / (now - fpsT0));
        fpsFrames = 0;
        fpsT0 = now;
        updateStatus(s.stats);
      }
      if (!splashDone) { splashDone = true; el("splash").classList.add("done"); }
    }
    requestAnimationFrame(frame);
  }

  /* ---- ?bench: agents at a stable 60 fps, measured in this browser ----
   * Pins the population at N (reseed floor = birth cap = N, so the count holds
   * at N), steps once per frame, warms up, then records frame intervals, step
   * time and draw time; repeats for growing N until the frame rate falls under
   * 30. Results go to an overlay, the console, and window.EVO_BENCH.
   * Keep the tab visible while it runs (hidden tabs throttle rAF).
   * ?bench&threads=0 measures the single-threaded module on an isolated page. */
  var bench = /[?&]bench(=|&|$)/.test(location.search) ? { results: [] } : null;
  var BENCH_NS = [250, 500, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 10000, 12000, 16000];
  var BENCH_WARM = 90, BENCH_MEASURE = 300;
  function benchNext() {
    var b = bench;
    if (b.i >= BENCH_NS.length) { benchDone(); return; }
    b.n = BENCH_NS[b.i];
    initWorld(42, b.n, { minPopulation: b.n, maxPopulation: b.n });
    b.frame = 0; b.prev = 0; b.iv = []; b.step = []; b.draw = []; b.pop = [];
  }
  function quantile(a, q) {
    var s = a.slice().sort(function (x, y) { return x - y; });
    return s[Math.min(s.length - 1, Math.floor(q * s.length))];
  }
  function mean(a) { var t = 0; for (var i = 0; i < a.length; i++) t += a[i]; return t / a.length; }
  function benchFrame(now, stepMs, drawMs, pop) {
    var b = bench;
    if (b.done) return;
    b.frame++;
    if (b.frame > BENCH_WARM) {
      if (b.prev) b.iv.push(now - b.prev);
      b.step.push(stepMs); b.draw.push(drawMs); b.pop.push(pop);
    }
    b.prev = now;
    if (b.iv.length < BENCH_MEASURE) return;
    var r = {
      agents: Math.round(mean(b.pop)),
      fps: +(1000 / mean(b.iv)).toFixed(1),
      p95FrameMs: +quantile(b.iv, 0.95).toFixed(2),
      stepMsMedian: +quantile(b.step, 0.5).toFixed(3),
      drawMsMedian: +quantile(b.draw, 0.5).toFixed(3)
    };
    /* The lightest load (the first N) shows the display's own refresh rate.
     * On a display at or above 60 Hz "stable" means 60 fps; on a slower one
     * (some laptops drop to ~57 Hz on battery or when idle) 60 fps cannot be
     * measured, so it means holding the display rate instead, and the report
     * says which. */
    if (!b.displayFps) b.displayFps = r.fps;
    r.stable60 = b.displayFps >= 58
      ? r.fps >= 58 && r.p95FrameMs <= 20
      : r.fps >= 0.97 * b.displayFps && r.p95FrameMs <= 1.2 * 1000 / b.displayFps;
    b.results.push(r);
    benchShow();
    if (r.fps < 30) { benchDone(); return; }
    b.i++;
    benchNext();
  }
  function benchEnv() {
    return {
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
      crossOriginIsolated: self.crossOriginIsolated === true,
      module: threaded ? "threaded" : "single-threaded",
      threads: Module._evo_threads ? Module._evo_threads() : 1,
      renderer: view3d ? scene.renderer + ", detail " + scene.quality()
                       : (glScene ? "webgl2" : "canvas2d") + (LOOK.fishShape ? "+fish" : ""),
      canvas: canvas.width + "x" + canvas.height,
      devicePixelRatio: window.devicePixelRatio
    };
  }
  function benchShow() {
    var out = el("benchout");
    if (!out) {
      out = document.createElement("pre");
      out.id = "benchout";
      document.body.appendChild(out);
    }
    var lines = ["Finfolk ?bench   " + JSON.stringify(benchEnv()), "",
                 "agents     fps   p95 frame ms   step ms   draw ms   stable 60"];
    bench.results.forEach(function (r) {
      lines.push(String(r.agents).padStart(6) + String(r.fps).padStart(8) +
                 String(r.p95FrameMs).padStart(15) + String(r.stepMsMedian).padStart(10) +
                 String(r.drawMsMedian).padStart(10) + "   " + (r.stable60 ? "yes" : "no"));
    });
    if (bench.done) {
      var best = bench.results.filter(function (r) { return r.stable60; }).pop();
      var at = bench.displayFps >= 58 ? "a stable 60 fps"
             : "the display's " + bench.displayFps + " Hz (it cannot show 60 fps)";
      lines.push("", "max agents at " + at + ": " + (best ? best.agents : "none measured"));
    } else {
      lines.push("", "measuring " + bench.n + " agents…");
    }
    out.textContent = lines.join("\n");
  }
  function benchDone() {
    bench.done = true;
    window.EVO_BENCH = { env: benchEnv(), displayFps: bench.displayFps, results: bench.results };
    console.log("EVO_BENCH " + JSON.stringify(window.EVO_BENCH));
    benchShow();
  }

  /* ---- control state helpers ---- */
  function setPaused(p) {
    paused = p;
    var b = el("pausebtn");
    b.querySelector("use").setAttribute("href", paused ? "#i-play" : "#i-pause");
    b.setAttribute("aria-label", paused ? "play" : "pause");
    b.title = (paused ? "Play" : "Pause") + " (Space)";
  }
  function setSpeed(n) {
    simSpeed = Math.max(1, Math.min(50, n));
    el("speedlabel").textContent = simSpeed + "×";
  }

  /* ---- checkpoint save/load ---- */
  function saveCheckpoint() {
    if (!Module) return;
    if (guardTurbo()) return;
    var str = Module.UTF8ToString(Module._evo_checkpoint());
    var frameNo = Math.round(new Float64Array(heap(), Module._evo_stats(), STATS_LEN)[3]);
    var blob = new Blob([str], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "evo_checkpoint_f" + frameNo + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Saved the world at frame " + frameNo.toLocaleString() + ".");
  }
  /* fromTurbo: the Turbo worker handing the same run back, so the dashboards
   * carry on; a file is a new run, so they start over. Returns whether the
   * module took it (a refusal leaves the running world, and its history, as they were). */
  function loadCheckpointText(text, fromTurbo) {
    var ok = withCString(text, function (ptr) { return Module._evo_load_checkpoint(ptr); });
    if (!ok) {
      showError("Couldn't load that checkpoint: " + Module.UTF8ToString(Module._evo_last_error()));
      return false;
    }
    if (!fromTurbo) {
      governed = false; liveEdited = false; loadedRun = true;   /* (updateModeline: the caller's, after the governor's reset) */
      try { runCfg = JSON.parse(text).config || {}; } catch (e) { runCfg = {}; }
      if (dash()) dash().reset();
      if (Module._evo_rec_reset) Module._evo_rec_reset(1);   /* the loaded fish, as the tree's roots */
    }
    selectedId = null;
    if (glScene && glScene.forgetFish) glScene.forgetFish();
    warmupUntil = performance.now() + WARMUP_MS;  /* a load is a restart for frame timing */
    workEma = 0;
    var w = Module._evo_width(), h = Module._evo_height();
    if (w !== WORLD_W || h !== WORLD_H) {
      WORLD_W = w; WORLD_H = h;
      canvas.width = w; canvas.height = h;
    }
    worldFitted = false;
    updateFitButton();
    el("randnote").textContent = "";  /* the Randomize pick no longer describes this world */
    if (!fromTurbo) showNote("Checkpoint loaded.");
    return true;
  }

  /* ---- TURBO (headless worker) mode ----
   * live -> entering -> turbo -> exiting -> live. Handoff both ways is by
   * checkpoint string (bit-exact through the shim), so the trajectory is
   * preserved. While not 'live' the main module is frozen: the rAF loop stops
   * stepping but keeps re-syncing/drawing the same frame, under the Turbo card. */
  var turboState = "live";
  var turboWorker = null;
  var turboStats = null;

  function guardTurbo() {
    if (turboState === "live") return false;
    showNote("Stop Turbo first.");
    return true;
  }
  function updateLocks() {
    var tb = el("turbobtn"), on = turboState === "turbo" || turboState === "exiting";
    tb.setAttribute("aria-pressed", on ? "true" : "false");
    tb.disabled = turboState === "entering" || turboState === "exiting";
    var locked = turboState !== "live";
    ["restart", "savecp", "loadcp", "pausebtn", "slower", "faster", "randombtn", "randombig"].forEach(function (id) {
      el(id).classList.toggle("locked", locked);
    });
    el("turbo").hidden = turboState === "live";
    el("turboexit").disabled = turboState !== "turbo";
    el("turboexit").textContent = turboState === "exiting" ? "Syncing back…" : turboState === "entering" ? "Starting…" : "Stop Turbo and watch";
    if (turboState !== "live") paintTurbo();
  }
  function paintTurbo() {
    var t = turboStats;
    el("ts-rate").textContent = t ? Math.round(t.stepsPerSec).toLocaleString() : "–";
    el("ts-steps").textContent = t ? t.totalSteps.toLocaleString() : "–";
    el("ts-pop").textContent = t ? Math.round(t.pop).toLocaleString() : "–";
    el("ts-food").textContent = t ? Math.round(t.food).toLocaleString() : "–";
  }
  function onTurboMessage(e) {
    var msg = e.data || {};
    if (msg.type === "stats") {
      turboStats = msg;
      if (turboState === "entering") { turboState = "turbo"; updateLocks(); }
    } else if (msg.type === "rec") {
      /* what the worker's recorder saw: same run, so straight into the dashboards */
      if (dash()) dash().ingest(new Float64Array(msg.s), new Float64Array(msg.b), new Float64Array(msg.c));
    } else if (msg.type === "checkpoint") {
      if (turboState !== "exiting") return;
      turboState = "live";
      loadCheckpointText(msg.json, true); /* reuses the width/height re-read + selection clear */
      setPaused(false);             /* turbo implies running; come back un-paused */
      updateLocks();
      showNote("Turbo ran " + (turboStats ? turboStats.totalSteps.toLocaleString() : 0) + " steps.");
    } else if (msg.type === "error") {
      showError("Turbo stopped: " + (msg.message || "unknown error"));
      turboState = "live"; /* main module still holds its last state; nothing lost */
      updateLocks();
    }
  }
  function enterTurbo() {
    if (turboState !== "live" || !Module) return;
    turboState = "entering";
    turboStats = null;
    selectedId = null; /* ids will be stale by exit */
    updateLocks();
    if (!turboWorker) { /* created once, reused across sessions */
      turboWorker = new Worker(ASSETS.worker);
      turboWorker.onmessage = onTurboMessage;
      turboWorker.onerror = function (ev) {
        showError("The Turbo worker failed: " + (ev.message || "could not load worker.js"));
        turboState = "live";
        updateLocks();
      };
    }
    /* everything recorded up to the hand-off goes to the dashboards first;
     * the worker records on from here at the same interval */
    if (Module._evo_rec_flush) { Module._evo_rec_flush(); if (dash()) dash().pump(); }
    turboWorker.postMessage({ cmd: "start",
                              checkpoint: Module.UTF8ToString(Module._evo_checkpoint()),
                              js: moduleUrls.js, wasm: moduleUrls.wasm,
                              threads: Module._evo_threads ? Module._evo_threads() : 1,
                              recEvery: dash() ? dash().every() : 60,
                              culled: Module._evo_rec_culled ? Module._evo_rec_culled() : 0 });
  }
  function exitTurbo() {
    if (turboState !== "turbo") return;
    turboState = "exiting";
    updateLocks();
    turboWorker.postMessage({ cmd: "stop" });
  }

  /* ---- input ---- */
  canvas.addEventListener("click", function (e) {
    if (!Module || turboState !== "live") return;
    var rect = canvas.getBoundingClientRect();
    var wx = (e.clientX - rect.left) * (canvas.width / rect.width);
    var wy = (e.clientY - rect.top) * (canvas.height / rect.height);
    /* the mouse picks within 25 world px; a finger within ~24 CSS px, which
     * on a phone-sized canvas is several times farther */
    var reach = lastPointer === "mouse" ? 25 : Math.max(25, 24 * canvas.width / rect.width);
    var best = nearestFish(wx, wy, reach * reach);
    selectedId = best >= 0 ? fishId(best) : null;
    if (best >= 0) everSelected = true;
  });
  /* Index of the creature whose head is nearest (wx, wy), at most
   * sqrt(maxD2) away, or -1. Ties go to the later creature. */
  function nearestFish(wx, wy, maxD2) {
    var n = Module._evo_creature_count();
    var segs = new Float32Array(heap(), Module._evo_creature_segments(), n * 12);
    var best = -1, bestD2 = maxD2;
    for (var i = 0; i < n; i++) {
      var dx = segs[12 * i] - wx, dy = segs[12 * i + 1] - wy;
      var d2 = dx * dx + dy * dy;
      if (d2 <= bestD2) { bestD2 = d2; best = i; }
    }
    return best;
  }
  function fishId(index) {
    return new Float64Array(heap(), Module._evo_creature_ids(), index + 1)[index];
  }
  /* The tank: a short tap or click picks the fish nearest it on screen, empty
   * water lets go; a drag, pinch or long press belongs to the camera. */
  var tap = null;
  sceneCanvas.addEventListener("pointerdown", function (e) {
    /* only the primary button picks; right and middle drag the camera */
    tap = e.isPrimary && e.button === 0 ? { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId } : null;
  });
  sceneCanvas.addEventListener("pointercancel", function () { tap = null; });
  sceneCanvas.addEventListener("pointerup", function (e) {
    if (!tap || e.pointerId !== tap.id) return;
    var moved = Math.hypot(e.clientX - tap.x, e.clientY - tap.y), held = performance.now() - tap.t;
    tap = null;
    if (moved > 8 || held > 600 || !view3d || !Module || turboState !== "live") return;
    var best = scene.pick(snapshot(-1), e.clientX, e.clientY, e.pointerType === "mouse" ? 18 : 30);
    selectedId = best >= 0 ? fishId(best) : null;
    if (best >= 0) everSelected = true;
  });
  function toggleFollow() {
    if (!view3d || selectedId === null) return;
    scene.setFollow(!scene.following());
  }
  function onFollowChange(on) {
    el("followbtn").setAttribute("aria-pressed", on ? "true" : "false");
    el("followbtn").title = on ? "Stop following (F)" : "Follow this fish (F)";
    if (on) toast(coarseMQ.matches ? "Following. Drag to circle around it." : "Following. Drag to circle around it; F stops.");
  }

  /* The part of the screen the tank is framed in: below the top bar and above
   * the dock on a desktop (like the flat world's stage), the whole screen on
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
      /* a phone's sheet leaves a strip too small to frame the whole tank
       * in; then the view stays put and the sheet simply covers its foot */
      var sheetTop = drawerEl.getBoundingClientRect().top;
      bottom = sheetTop - top >= vh * 0.3 ? vh - sheetTop : bottom;
    }
    scene.setInsets({ top: Math.round(top), right: Math.round(right), bottom: Math.round(Math.max(0, bottom)), left: 0 });
  }

  /* ---- switching between the flat world and the tank ---- */
  function remember(on) { try { localStorage.setItem(VIEW_KEY, on ? "3d" : "flat"); } catch (e) { /* private mode */ } }
  function loadScene() {
    if (sceneLoad) return sceneLoad;
    sceneLoad = (window.EvoScene ? EvoScene.load() : Promise.reject(new Error("scene3d.js missing")))
      .then(function () {
        scene = EvoScene.create(sceneCanvas, {
          coarse: coarseMQ.matches, reducedMotion: reducedMQ.matches,
          bodyScale: bodyScale, onFollowChange: onFollowChange
        });
        if (!scene) throw new Error("no WebGL2");
        return scene;
      })
      .catch(function (e) {
        console.warn("evo_boids: tank view unavailable", e);
        sceneLoad = null;
        return null;
      });
    return sceneLoad;
  }
  /* fromUser: the switch was flipped, so the choice is remembered. A start
   * from ?view= or from the remembered choice doesn't write it again; a
   * tank that fails to start forgets it, so later visits don't retry. */
  function setView(on, fromUser) {
    el("view3d").checked = on;
    if (!on) {
      if (fromUser) remember(false);
      if (!view3d) return;
      if (scene.following()) scene.setFollow(false);
      view3d = false;
      document.body.classList.remove("view-3d");
      updateModeline();
      return;
    }
    if (view3d) return;
    el("view3d").disabled = true;
    return loadScene().then(function (sc) {
      el("view3d").disabled = false;
      if (!sc) {
        el("view3d").checked = false;
        remember(false);
        showError("The tank view couldn't start here (it needs WebGL2, and three.js has to load).");
        return;
      }
      if (!el("view3d").checked) return;   /* switched off again while loading */
      view3d = true;
      document.body.classList.add("view-3d");
      sceneW = sceneH = 0;   /* (re)frame the tank on the next frame */
      scene.resize();
      updateInsets();
      if (fromUser) remember(true);
      updateModeline();
    });
  }

  /* Escape also closes the dashboards (dashboard.js) and ends the tour
   * (guide.js), in their own keydown handlers. Seen here first, in the
   * capture phase, so the same press doesn't also let go of the fish. */
  var escHandledElsewhere = false;
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") escHandledElsewhere = !!(dash() && dash().isOpen()) || !!document.getElementById("guide");
  }, true);
  window.addEventListener("keydown", function (e) {
    /* Escape always closes what is open, regardless of what has focus —
     * blurring the focused control so the sim shortcuts work again. */
    if (e.key === "Escape") {
      /* one owner for each Esc: the tour or the charts take theirs, and
       * nothing behind them closes with it */
      if (!escHandledElsewhere) {
        if (drawerEl.classList.contains("open")) setDrawer(false);
        else if (statOpen) setStatPanel(false);
        else selectedId = null;
      }
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      return;
    }
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "BUTTON" ||
              t.tagName === "SELECT" || t.tagName === "SUMMARY")) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    /* the tank's camera */
    if (view3d && (e.key === "c" || e.key === "C")) { scene.resetView(true); return; }
    if (view3d && (e.key === "f" || e.key === "F")) { toggleFollow(); return; }
    /* sim-mutating shortcuts are locked while turbo owns the trajectory
     * (Escape above stays live) */
    if (turboState !== "live") {
      if (e.code === "Space" || e.key === "ArrowUp" || e.key === "ArrowDown" ||
          e.key === "+" || e.key === "=" || e.key === "-" ||
          e.key === "r" || e.key === "R") {
        showNote("Stop Turbo first.");
        e.preventDefault();
      }
      return;
    }
    if (e.code === "Space") {
      setPaused(!paused);
      e.preventDefault();
    } else if (e.key === "ArrowUp" || e.key === "+" || e.key === "=") {
      setSpeed(simSpeed + 1);
      e.preventDefault();
    } else if (e.key === "ArrowDown" || e.key === "-") {
      setSpeed(simSpeed - 1);
      e.preventDefault();
    } else if (e.key === "r" || e.key === "R") {
      el("seed").value = String((Math.random() * 0x100000000) >>> 0);
      restart();
    }
  });

  /* ---- settings: a bottom sheet on narrow screens, a side panel on wide ones ---- */
  var drawerEl = el("drawer"), menuBtn = el("menubtn");
  function setDrawer(open) {
    if (open && dash()) dash().close();
    drawerEl.classList.toggle("open", open);
    document.body.classList.toggle("sheet-open", open);
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) hideTip();
    if (open) setStatPanel(false);
    if (scene) { updateInsets(); setTimeout(updateInsets, 320); }   /* and after the slide */
  }
  menuBtn.addEventListener("click", function () {
    setDrawer(!drawerEl.classList.contains("open"));
    this.blur();
  });
  el("drawerclose").addEventListener("click", function () { setDrawer(false); this.blur(); });
  /* drag the sheet's grip (or header) down to close it */
  (function () {
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
      n.addEventListener("pointerdown", down);
      n.addEventListener("pointermove", move);
      n.addEventListener("pointerup", up);
      n.addEventListener("pointercancel", up);
    });
  })();

  /* ---- shared hover tooltip (one fixed div, styled in index.html) ---- */
  var tipEl = document.createElement("div");
  tipEl.id = "tooltip";
  var tipDesc = document.createElement("div");
  tipDesc.className = "tipd";
  var tipTry = document.createElement("div");
  tipTry.className = "tipt";
  tipEl.appendChild(tipDesc);
  tipEl.appendChild(tipTry);
  document.body.appendChild(tipEl);
  var tipTimer = 0;
  var tipFor = null;  /* the row whose tip is showing */
  function hideTip() {
    clearTimeout(tipTimer);
    tipEl.style.display = "none";
    tipFor = null;
  }
  function showTip(rowEl, tip) {
    tipDesc.textContent = tip.d;
    tipTry.textContent = tip.t;
    tipEl.style.display = "block";
    tipFor = rowEl;
    var dr = drawerEl.getBoundingClientRect();
    var lr = rowEl.getBoundingClientRect();
    var left, top;
    if (wideMQ.matches && dr.left >= tipEl.offsetWidth + 16) {
      /* to the LEFT of the side panel, centred on the row */
      left = Math.max(6, dr.left - 10 - tipEl.offsetWidth);
      top = lr.top + lr.height / 2 - tipEl.offsetHeight / 2;
    } else {
      /* over the sheet: below the row, or above it near the bottom */
      left = Math.max(8, Math.min(lr.left, window.innerWidth - tipEl.offsetWidth - 8));
      top = lr.bottom + 4;
      if (top + tipEl.offsetHeight > window.innerHeight - 6) top = lr.top - 4 - tipEl.offsetHeight;
    }
    top = Math.max(6, Math.min(top, window.innerHeight - tipEl.offsetHeight - 6));
    tipEl.style.left = left + "px";
    tipEl.style.top = top + "px";
  }
  /* Mouse: the tip shows on hover. Touch: tapping the setting's name toggles
   * it (and does not toggle the switch or focus the input). */
  function attachTip(rowEl, key) {
    var tip = TIPS[key];
    if (!tip) return;
    rowEl.addEventListener("mouseenter", function () {
      if (lastPointer !== "mouse") return;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(function () { showTip(rowEl, tip); }, 200);
    });
    rowEl.addEventListener("mouseleave", function () {
      if (lastPointer === "mouse") hideTip();
    });
    var name = rowEl.querySelector(".lt");
    if (name) name.addEventListener("click", function (e) {
      if (lastPointer === "mouse") return;
      e.preventDefault();
      if (tipFor === rowEl) hideTip();
      else showTip(rowEl, tip);
    });
  }
  panelsEl.addEventListener("scroll", hideTip);
  /* a touch anywhere but on a setting's name closes an open tip */
  document.addEventListener("pointerdown", function (e) {
    if (tipFor && e.pointerType !== "mouse" && !(e.target.closest && e.target.closest(".lt"))) hideTip();
  });

  function btn(id, fn) {
    el(id).addEventListener("click", function () { fn(); this.blur(); });
  }

  /* Settings that only matter while another one is on are dimmed, with the
   * reason under their name; they still save and restart as usual. */
  function hasPredators() { return intVal("predators", 0) > 0; }
  function hasCurrent() { return floatVal("currentStrength", 0) > 0; }
  var NEEDS = [
    [["adv_foodPatchRadius"], "needs food patches above 0", function () { return intVal("foodPatches", 0) > 0; }],
    [["adv_foodDrift", "adv_currentMode", "adv_currentDrift"], "needs a current (strength above 0)", hasCurrent],
    [["adv_currentEddies", "adv_currentCore"], "needs a current in the eddies shape",
      function () { return hasCurrent() && el("adv_currentMode").value === "0"; }],
    [["predatorEconomy", "adv_predatorSpeed", "adv_predatorPerception", "adv_predatorCaptureRadius",
      "adv_predatorCooldown"], "needs predators above 0", hasPredators],
    [["adv_predatorMeal", "adv_predatorMetabolism", "adv_predatorReproEnergy", "adv_predatorMaxAge",
      "adv_predatorMinPopulation", "adv_predatorMaxPopulation", "adv_predatorInheritance"],
      "needs predators, with their economy on", function () { return hasPredators() && el("predatorEconomy").checked; }],
    [["adv_predatorTraitMutation"], "needs hunters inherit traits on",
      function () { return hasPredators() && el("predatorEconomy").checked && el("adv_predatorInheritance").checked; }],
    [["adv_maxTurnRate"], "needs fast-swims-straight on", function () { return el("adv_triangularMotion").checked; }],
    [["adv_reproSoftWidth", "adv_reproGracePeriod"], "needs a breeding distance limit of 0 or more",
      function () { return floatVal("adv_reproMaxDistance", -1) >= 0; }],
    [["adv_bodyMutation"], "needs evolving bodies on", function () { return el("bodyModel").checked; }]
  ];
  function updateNeeds() {
    NEEDS.forEach(function (rule) {
      var on = rule[2]();
      rule[0].forEach(function (id) {
        var row = el(id).closest(".field");
        var hint = row.querySelector(".needs");
        if (!hint) {
          hint = document.createElement("span");
          hint.className = "needs";
          row.appendChild(hint);
        }
        row.classList.toggle("inert", !on);
        hint.textContent = on ? "" : rule[1];
      });
    });
  }
  /* Everything but the live settings applies on Restart: say so as soon as
   * one changes, so a change never looks ignored. */
  function setPending(on) {
    var b = el("restart");
    b.classList.toggle("pending", on);
    b.querySelector("span").textContent = on ? "Restart to apply" : "Restart";
  }
  function onEdit(e) {
    var t = e.target;
    updateNeeds();
    updateTabDots();
    if (!t || !t.id || (t.id.indexOf("adv_") === 0 && LIVE[t.id.slice(4)])) return;  /* applies by itself */
    if (t.id === "governor" || t.id === "view3d" || t.id === "fishShape" || t.id === "colourBrain" || t.id === "cpfile") return;   /* not settings Restart applies */
    setPending(true);
  }

  buildSettings();
  panelsEl.addEventListener("input", onEdit);   /* while typing */
  panelsEl.addEventListener("change", onEdit);  /* switches, selects, steppers */
  btn("restart", restart);
  btn("pausebtn", function () { if (guardTurbo()) return; setPaused(!paused); });
  btn("slower", function () { if (guardTurbo()) return; setSpeed(simSpeed - 1); });
  btn("faster", function () { if (guardTurbo()) return; setSpeed(simSpeed + 1); });
  btn("turbobtn", function () {
    if (turboState === "live") enterTurbo();
    else if (turboState === "turbo") exitTurbo();
  });
  btn("turboexit", exitTurbo);
  btn("advreset", function () {
    resetAdvanced();
    Object.keys(BASIC_DEFAULTS).forEach(function (id) { setField(el(id), BASIC_DEFAULTS[id]); });
    setPending(true); updateNeeds(); updateTabDots();
    showNote("Every setting is back to its default. Restart to apply.");
  });
  btn("iclose", function () { selectedId = null; });
  btn("iexpand", function () {
    cardExpanded = !cardExpanded;
    cardEl.classList.toggle("expanded", cardExpanded);
    el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    el("iexpand").title = cardExpanded ? "Hide its brain" : "Show its brain";
    cardCache.sense = null;
  });
  btn("fitbtn", restart);
  btn("randombtn", randomize);
  btn("randombig", randomize);
  btn("guidebtn", function () { if (window.EvoGuide) EvoGuide.start(); });
  btn("followbtn", toggleFollow);
  btn("viewbtn", function () { if (view3d) scene.resetView(true); });
  el("view3d").addEventListener("change", function () { setView(this.checked, true); this.blur(); });
  el("fishShape").addEventListener("change", function () { setFishShape(this.checked); this.blur(); });
  /* Fish shapes: ?fish=1 / ?fish=0, else this visitor's last choice; off the
   * first time. WebGL2 only: in canvas 2D, Chrome fills the outlines at less
   * than half the frame rate it fills circles, so the 2D fallback keeps the
   * circles and the switch says why. */
  var FISH_KEY = "evo_boids.fishShape";
  function setFishShape(on) {
    if (!glScene || !glScene.fishShapes) return;
    if (on && !LOOK.fishShape) glScene.forgetFish();   /* history from before is stale */
    LOOK.fishShape = on;
    el("fishShape").checked = on;
    try { localStorage.setItem(FISH_KEY, on ? "1" : "0"); } catch (e) { /* private mode */ }
    if (Module) updateModeline();
  }
  (function () {
    var want = PARAMS.get("fish"), saved = null;
    try { saved = localStorage.getItem(FISH_KEY); } catch (e) { /* private mode */ }
    if (want !== "1" && want !== "0") want = saved === "1" ? "1" : "0";
    if (!glScene || !glScene.fishShapes) {
      var row = el("f_fishShape"), hint = document.createElement("span");
      el("fishShape").disabled = true;
      row.classList.add("inert");
      hint.className = "needs";
      hint.textContent = glScene ? "the fish-shape shader didn't compile in this browser; circles stay"
                                 : "needs WebGL2: this page is drawing with canvas 2D, which keeps the circles";
      row.appendChild(hint);
      return;
    }
    LOOK.fishShape = want === "1";
    el("fishShape").checked = LOOK.fishShape;
  })();
  /* Fish colour: by family line (the default) or by brain similarity — the
   * genome colour the native app draws. ?colour=brain / ?colour=family, else
   * this visitor's last choice (remembered only when they flip the switch).
   * The key is shared with the Ocean, whose "appearance" (its default) and
   * anything else but "brain" read as family here.
   * Display only: the shim fills the one colour buffer every renderer reads
   * from one or the other (evo_set_colour_mode), and the run is the same. */
  var COLOUR_KEY = "evo_boids.colourBy", colourBrain = false;
  function applyColourMode() {
    if (!Module || !Module._evo_set_colour_mode) return;
    Module._evo_set_colour_mode(colourBrain ? 0 : 1);
    Module._evo_sync();
  }
  function setColourBrain(on, remember) {
    colourBrain = on;
    el("colourBrain").checked = on;
    if (remember) {
      try { localStorage.setItem(COLOUR_KEY, on ? "brain" : "family"); } catch (e) { /* private mode */ }
    }
    applyColourMode();
    if (Module) updateModeline();
  }
  (function () {
    var want = PARAMS.get("colour"), saved = null;
    try { saved = localStorage.getItem(COLOUR_KEY); } catch (e) { /* private mode */ }
    if (want !== "brain" && want !== "family") want = saved === "brain" ? "brain" : "family";
    colourBrain = want === "brain";
    el("colourBrain").checked = colourBrain;
  })();
  el("colourBrain").addEventListener("change", function () { setColourBrain(this.checked, true); this.blur(); });
  var fitTimer = 0;
  window.addEventListener("resize", function () {
    if (scene) { scene.resize(); updateInsets(); }
    clearTimeout(fitTimer);
    fitTimer = setTimeout(function () { if (Module) updateFitButton(); if (scene) updateInsets(); }, 250);
  });
  if (reducedMQ.addEventListener) reducedMQ.addEventListener("change", function () {
    if (scene) scene.setReducedMotion(reducedMQ.matches);
  });
  btn("savecp", saveCheckpoint);
  btn("loadcp", function () { if (guardTurbo()) return; el("cpfile").click(); });
  el("cpfile").addEventListener("change", function () {
    var file = this.files && this.files[0];
    this.value = "";
    if (!file || !Module || guardTurbo()) return;
    file.text().then(function (text) {
      if (!loadCheckpointText(text)) return;   /* refused: the running world, its cap and its governor stay */
      /* the file's own cap becomes the user cap; the governor starts fresh */
      var cap = 0;
      try { cap = (JSON.parse(text).config || {}).maxPopulation || 0; } catch (e) { /* load reported it */ }
      userCap = cap;
      autoCap = 0;
      el("adv_maxPopulation").value = String(cap);
      resetGovernor();
      updateModeline();
      updateNeeds();
      updateTabDots();
    }, function (err) { showError("Couldn't read that file: " + err); });
  });
  el("governor").addEventListener("change", function () {
    governorOn = this.checked;
    if (!governorOn && autoCap) { autoCap = 0; applyCap(); }
    if (!governorOn) restoreDetail();
    govNote = "";
    this.blur();
  });

  updateNeeds();
  updateTabDots();
  setSpeed(simSpeed);
  setPaused(false);

  /* ---- hooks for the first-visit guide (web/guide.js) ---- */
  var guideFish = null;   /* the fish the guide selected, released after its step */
  window.EvoApp = {
    ready: false,   /* the world is running; "evo:ready" fires on window then */
    touch: function () { return coarseMQ.matches; },
    /* the selected fish is the card (compact screens, and the tank view) */
    compact: function () { return compactMQ.matches || view3d; },
    has3D: function () { return view3d; },
    /* fish coloured by brain similarity (else by family line) */
    colourByBrain: function () { return colourBrain; },
    /* the Turbo intro's "Try Turbo" */
    startTurbo: function () { if (Module && turboState === "live") enterTurbo(); },
    setDrawer: setDrawer,
    setSheetTab: setSheetTab,
    /* Selects a fish for the guide to show, unless one is selected: the one
     * nearest a point left of centre, clear of the desktop inspector. Leaves
     * everSelected alone, so the one-time hint still comes until the visitor
     * picks one. */
    inspectSomeFish: function () {
      if (!Module || turboState !== "live") return false;
      if (selectedId !== null) return true;
      var best = nearestFish(WORLD_W * (view3d ? 0.4 : 0.35), WORLD_H * (view3d ? 0.45 : 0.5), Infinity);
      if (best < 0) return false;
      selectedId = guideFish = fishId(best);
      return true;
    },
    releaseFish: function () {
      if (guideFish !== null && selectedId === guideFish) selectedId = null;
      guideFish = null;
    },
    /* CSS rect of the inspector being shown (the fish card on compact
     * screens, the canvas panel elsewhere), or null */
    inspectorRect: function () {
      if (selectedId === null || turboState !== "live") return null;
      if (compactMQ.matches || view3d) return cardEl.hidden ? null : cardEl.getBoundingClientRect();
      var cr = canvas.getBoundingClientRect(), c = cr.width / canvas.width;
      return { left: cr.left + inspectorX() * c, top: cr.top + INSP_Y * c,
               width: INSP_W * c, height: INSP_H * c };
    }
  };

  /* ---- boot ---- */
  function splashSay(msg) { el("splashstate").textContent = msg; }
  if (!window.EvoLoader || !ASSETS) {
    splashSay("This page is missing loader.js.");
    showError("loader.js / EVO_ASSETS missing from the page");
    return;
  }
  EvoLoader.load().then(function (r) {
    Module = r.Module;
    threaded = r.threaded;
    threadWhy = r.why;
    moduleUrls = { js: r.js, wasm: r.wasm };
    if (Module._evo_stats_len) STATS_LEN = Module._evo_stats_len();
    applyColourMode();
    if (dash() && Module._evo_rec_take) dash().attach({
      module: Module, heap: heap, actionNames: ACTION_NAMES, setDrawer: setDrawer,
      runConfig: function () { return runCfg; },
      /* fish drawn by brain (genome colour) instead of by family line */
      colourByBrain: function () { return colourBrain; },
      /* what the fish wear now ("family" or "brain"), and the charts' way to show their family colours in the tank */
      colourMode: function () { return colourBrain ? "brain" : "family"; },
      showFamilyColours: function () { setColourBrain(false, true); },
      /* the sampling interval, here and in a running Turbo worker */
      setRecEvery: function (every) {
        Module._evo_rec_config(every, -1);
        if (turboWorker && (turboState === "entering" || turboState === "turbo"))
          turboWorker.postMessage({ cmd: "rec", every: every });
      }
    });
    /* Thread count: ?nthreads=N, else every pre-spawned worker plus this
     * thread (EvoLoader.poolThreads() — the -sPTHREAD_POOL_SIZE formula),
     * at most TOUCH_THREADS on a touch device. */
    var nt = parseInt(new URLSearchParams(location.search).get("nthreads"), 10);
    var touch = coarseMQ.matches;
    var pool = EvoLoader.poolThreads();
    if (threaded) Module._evo_set_threads(nt > 0 ? Math.min(nt, pool) : (touch ? Math.min(TOUCH_THREADS, pool) : pool));
    /* The single-threaded module starts with fewer creatures (see the
     * benchmark in README.md); either default can be changed in the settings. */
    basePop = threaded ? (touch ? TOUCH_POP_THREADED : DEFAULT_POP_THREADED)
                       : (touch ? TOUCH_POP_SINGLE : DEFAULT_POP_SINGLE);
    el("population").value = String(basePop);
    el("turbobtn").title = threaded
      ? "Turbo: run headless in a worker at full speed. Keeps running in background tabs; the hand-off is exact, but a threaded run is not reproducible."
      : "Turbo: run headless in a worker at full speed. Keeps running in background tabs; switching is bit-exact.";
    updateModeline();
    /* the tank view: ?view=3d / ?view=flat, else this visitor's last choice,
     * else the tank (?bench: the flat view, so its numbers compare with the
     * README's); never with ?gl=0, which forces the flat canvas-2D view */
    var want = PARAMS.get("view"), saved = null;
    try { saved = localStorage.getItem(VIEW_KEY); } catch (e) { /* private mode */ }
    if (want !== "3d" && want !== "flat") want = saved === "3d" || saved === "flat" ? saved : (bench ? "flat" : "3d");
    if (PARAMS.get("gl") === "0") {
      want = "flat";
      el("view3d").disabled = true;
      var row = el("f_view3d"), hint = document.createElement("span");
      row.classList.add("inert");
      hint.className = "needs";
      hint.textContent = "off with ?gl=0, which forces the flat canvas-2D view";
      row.appendChild(hint);
    }
    /* ?bench measures the view it starts in, so that one is loaded first */
    return Promise.resolve(want === "3d" ? setView(true) : null).then(start);
  }).catch(function (err) {
    splashSay("The simulation couldn't start: " + err);
    showError("failed to load wasm module: " + err);
  });
  function updateModeline() {
    /* the claim as data too (data-replay "yes" / "no", data-why: the reasons' keys) */
    var ml = el("modeline"), why = threaded ? ["threaded"] : replayReasons().map(function (r) { return r[0]; });
    ml.dataset.replay = why.length ? "no" : "yes";
    ml.dataset.why = why.join(" ");
    ml.textContent = (threaded
      ? "Running the threaded module (" + Module._evo_threads() + " threads): fast, not reproducible from the seed."
      : "Running the single-threaded module (" + threadWhy + "): " + replayClaim() + ".") +
      " Drawing: " + drawingName() + ".";
  }
  function start() {
    if (bench) {
      bench.i = 0;
      benchNext();
      clearError();
    } else if (restart()) {
      clearError();
    }
    requestAnimationFrame(frame);
    if (!bench) {
      window.EvoApp.ready = true;
      window.dispatchEvent(new Event("evo:ready"));
      /* one quiet hint, once, for visitors who skip the tour */
      setTimeout(function () {
        if (!everSelected && selectedId === null && !document.getElementById("guide"))
          toast((coarseMQ.matches ? "Tap" : "Click") + " any fish to see its brain.");
      }, 9000);
    }
  }
})();
