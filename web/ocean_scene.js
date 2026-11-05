"use strict";
/* evo_boids 3-D Ocean: the 3D tank, deep (three.js).
 *
 * A copy of web/scene3d.js (the Classic tank) for the Ocean preview page
 * (web/ocean.html), registered as window.EvoOceanScene; to be folded back into
 * scene3d.js at E6 (PLAN_ocean_preview.md §5). What differs from scene3d.js:
 *   - the world has a real depth: s.depth (per fish), s.foodDepth, s.predDepth
 *     place everything at three Y = -depth (0 = surface .. D); without them
 *     the old hash height / fixed heights are used, as in scene3d.js
 *   - opts.tankDepth = D: the floor sits at -(D + 14), the glass box is a full
 *     box (top + bottom rectangles + verticals), marine snow falls the whole D
 *   - the camera looks more from the side (POLAR 1.0) and frames all eight
 *     corners of the box around y = -D/2; following a fish follows its depth.
 *     It is free: it orbits below the horizontal (to nearly straight up),
 *     moves in depth (moveView, and screen-plane panning from the side), and
 *     clampView keeps it out of the sand and its centre within the water.
 *     setMove (the page's W A S D, Q / E, Shift) flies it smoothly; while
 *     following a fish the same keys dolly, circle and raise the camera
 *     around the fish and the follow stays on (stepFly)
 *   - light fades and shifts blue with depth (fish, shadows, food); the floor
 *     is sand (grain, ripples) under the caustics; seen from below, the
 *     surface shows Snell's window and a shimmer (SURF_FS). setLight({on, L0,
 *     k}) (E1: the engine's light field) makes the fish / food fall-off the
 *     engine's L(d) = L0·exp(−k·d); off, the preview's linear depth / D.
 *     How much is the water's clarity (setClarity(u), drawing only; CLARITY):
 *     0 realistic, the water as the preview drew it; 1 clear (the page's
 *     default), about half the darkening, a lighter teal water above a
 *     deeper teal floor (as Classic's tank), brighter backs and ambient,
 *     softer caustics, dimmer marine snow and plankton glow, and a lift of
 *     the fish's colours outside the flashlight
 *   - each body pitches by s.vz (+ = sinking, head down), pivoting at the head
 *   - the flashlight (setFlashlight, viewer only): a cone of clear light from
 *     the camera onto the followed fish or the point it looks at; inside it
 *     the fish, food and sand show their true colours (BEAM_FN)
 *   - the appearance genome (web/ocean_appearance.js): whenever the snapshot
 *     carries s.app (oc_creature_appearance's 63 floats per fish), every fish
 *     is drawn in its own inherited body: the M1 deformable template (shape,
 *     fins, barbels), lit and fogged exactly like the plain fish, in one
 *     instanced draw (plus one for the barbels when a fish has any, and the
 *     shadow). setAppearance(on) picks its skin: on, pattern law 3 from its
 *     genes; off, its family / brain colour (s.colors) with the plain fish's
 *     darker back, pale belly and paler fins. Without s.app the plain fish
 *     mesh is drawn instead. appearanceParity() is the GPU == CPU check of
 *     the pattern law (the gallery's K12); appearancePathCheck() that of the
 *     production programs (a fixed fixture through the vertex shader in both
 *     colour modes: the gene texture's slot lookup, every body part's
 *     position and material site, the decoded pattern genes, the packed
 *     colour; and the fragment shader); appearanceTextureParity() that of
 *     the live gene texture as three uploaded it (raw genes, pattern charts)
 *   - measurement (opts.profiler, web/ocean_perf.js): spans, counters and
 *     optional GPU timing; the default profiler records nothing
 *   - glass walls (setWorld(w, h, d, {walls})): the four side panes drawn as
 *     faint glass (brighter at grazing angles, GLASS_FS; not depth-written),
 *     every fish vertex held inside them (a fish against a pane flattens on
 *     it), no seam unwrapping and no wrap jumps, the snow kept inside; off,
 *     the wrapping world as before. Any tank size: the camera's fit starts
 *     outside the box's bounding sphere and the far plane covers the depth
 *   - the swim polish (POSE_GLSL, POLISH_FN; drawn from detail 2 up): the
 *     fish roll into their turns; on a fish big enough on screen to show it
 *     (swimPose's size weight), the appearance fish's paired fins fold back
 *     at speed (the renderer's estimate, fillApp), the tail's
 *     trailing edge lags, thin fins let the light through and glow against
 *     it, a wet highlight runs on the facets, the genes' skin has a sheen at
 *     grazing angles, and backs near the surface catch faint caustics. Every
 *     fish program has a plain variant, the fish exactly as before (its
 *     GLSL byte for byte, its cost), drawn at detail 1 and whenever no fish
 *     of its kind is lit (a whole-tank view: main's programs and cost; the
 *     roll scales with the size weight too, so nothing pops); optionally
 *     (setLitSplit(true); off: it measured slower), only the lit appearance
 *     fish drawn on the full programs, apart, the rest plain (AppKind's
 *     split). Display only,
 *     like everything here
 *
 * Big tanks: the sand, caustics and surface are world-unit procedural
 * patterns (no bitmap stretched over the area), so their grain and ripples
 * keep their size; the snow keeps its fixed budget of flakes.
 *
 * Every fish is a faceted low-poly body bent along the six spine points the
 * core exports; the floor below catches its shadow and slow caustic light.
 * Food is glowing plankton, predators are larger dark hunters whose eyes burn
 * while they hunt, and ocean currents (when the snapshot has them) show as
 * drifting streaks.
 *
 * Cost model: one instanced draw for all fish, one for their shadows, one each
 * for predators, food, currents and the floor. Per frame the CPU only packs
 * the spine points (20 floats per fish) into instance buffers (the appearance
 * genes only of the fish new to the renderer, into their gene slots, and
 * only those slots are uploaded: web/ocean_appearance_slots.js; and, with the
 * polish, each lit fish's swim pose: one packed float, from its spine, a swimming-speed
 * estimate (a merge by id, no allocation) and its size on screen); the
 * bending, shading and tail beat happen in the shaders.
 *
 * World coordinates: sim (x right, y down, origin top-left) -> three
 * (X = x - W/2, Z = y - H/2, Y up = -depth).
 *
 * The GLSL is web/ocean_shaders.js's (window.EvoOceanShaders): the chunks the
 * programs share (FOG_FN, BEAM_FN, DEPTH_FN, CLARITY_FN), the environment's
 * programs (the floor, surface, food, glow, snow, glass, lines, rings) and
 * the fish programs in their variants (FISH_VS / FISH_FS, SHADOW_VS /
 * SHADOW_FS, appearanceShaders). The swim pose the CPU packs for them is
 * web/ocean_pose.js's (window.EvoOceanPose: swimPose and its parts, the
 * reach). The appearance checks and probes (appearancePathCheck and its
 * parts, appearanceParity, appearanceTextureParity) are
 * web/ocean_scene_parity.js's (window.EvoOceanSceneParity). The fish kinds'
 * materials are web/ocean_materials.js's binder (window.EvoOceanMaterials):
 * it makes them, assembles their programs variant by variant (the swim
 * polish and the split's skip as features) and is the one writer of a fish
 * mesh's material (bind: a kind's commit hands it the variant settle()
 * chose). All four load first; this file reads them under the names they
 * had here.
 *
 * EvoOceanScene.load() -> Promise (imports the trimmed three bundle,
 * window.EVO_ASSETS.three); EvoOceanScene.create(canvas, opts) -> scene or null. */
(function () {
  /* the GLSL (web/ocean_shaders.js), the swim pose's CPU half (web/ocean_pose.js), the fish's
   * materials (web/ocean_materials.js, which reads the GLSL as it loads) and the diagnostics
   * (web/ocean_scene_parity.js, which reads the first two), all loaded before this file; without any
   * of them there is no scene to offer: the page then says the 3-D tank can't start, and why
   * (EvoOceanSceneMissing): a file missing (its namespace undefined: it never ran), or one that failed
   * to run (null: each sets its namespace null first, so a throw before it registers leaves null). The
   * materials and the diagnostics are not blamed for a file they need */
  var SHADERS = window.EvoOceanShaders, POSE = window.EvoOceanPose, PARITY = window.EvoOceanSceneParity, MISSING = [], FAILED = [];
  var MATERIALS = window.EvoOceanMaterials;
  function need(api, file) { if (api === null) FAILED.push(file); else if (!api) MISSING.push(file); }
  need(SHADERS, "ocean_shaders.js"); need(POSE, "ocean_pose.js");
  if (SHADERS) need(MATERIALS, "ocean_materials.js");
  if (SHADERS && POSE) need(PARITY, "ocean_scene_parity.js");
  if (MISSING.length || FAILED.length) {
    var WHY = [];
    if (MISSING.length) WHY.push(MISSING.join(" and ") + " missing");
    if (FAILED.length) WHY.push(FAILED.join(" and ") + " failed to run");
    window.EvoOceanSceneMissing = WHY.join("; ");
    console.error("evo_boids: the 3-D tank cannot be drawn: web/" + WHY.join("; web/") + (FAILED.length ? " (threw as it loaded)" : ""));
    return;
  }
  var THREE = null;
  var TANK_D = 240;          /* default tank depth when opts.tankDepth is absent; FLOOR_Y = -(D + 14), per scene */
  var TAU = Math.PI * 2;
  var POLAR = 1.0;           /* default camera tilt from straight down, radians: a deep tank wants a side view */
  var FOV = 38;

  /* sRGB colours, authored for this scene (no colour management in the shaders) */
  var C = {
    fog: [0.027, 0.122, 0.125],
    sand: [0.72, 0.63, 0.48],       /* dry sand, lighter and darker drifts ... */
    sandDark: [0.56, 0.49, 0.38],
    water: [0.52, 0.57, 0.57],      /* ... under the deep water's blue-green */
    surfSky: [0.20, 0.36, 0.38],    /* the surface from below: Snell's window ... */
    surfMirror: [0.035, 0.085, 0.09], /* ... and the mirrored water around it */
    caustic: [0.70, 0.95, 0.84],
    edge: [0.55, 0.85, 0.78],
    glass: [0.70, 0.92, 0.90],     /* the glass walls' panes (a pale aqua sheen) */
    foodCore: [0.93, 1.0, 0.62],
    foodGlow: [0.55, 0.86, 0.18],
    current: [0.55, 0.86, 0.98],
    select: [0.78, 0.95, 0.30],
    predator: [0.16, 0.18, 0.22],
    snow: [0.78, 0.90, 0.86]
  };
  var LIGHT = (function () { var v = [-0.38, 1.0, -0.30], l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; })();

  /* The water's clarity (setClarity(u), drawing only: the page's "Water
   * clarity"). Each entry is [realistic, clear]; u = 0 is realistic, the
   * water exactly as the preview drew it (these are its old constants),
   * u = 1 clear, the page's default; in between, a straight blend.
   *   deepTint, deepDim, deepAdd: the colour kept at the floor's depth,
   *     tint x (1 - dim), plus a little blue (DEPTH_FN); clear: about half
   *     the darkening and a gentler blue shift
   *   lKeep: the share of the light field's loss (E1, L(d)) given back
   *   floorMin: no channel kept below this (clear: 45 % at the floor)
   *   back, ambLo, ambHi, vivid: the fish's back (its share kept), ambient
   *     light, and the display-only lift [saturation, gain, gamma]
   *     (CLARITY_FN)
   *   fog, fogK: the water's colour (and the clear colour above the tank)
   *     and its density; clear: a lighter teal, thinner
   *   water, causticK: the tint on the sand and the caustics' strength;
   *     clear: a deeper teal floor (as Classic's tank) with softer caustics,
   *     so bright fish read against it rather than dark ones against bright
   *     sand
   *   snow: the marine snow's brightness and the share of its flakes drawn;
   *     shadow: the fish's shadows' opacity; foodShade, foodGain: how much
   *     depth dims and cools the plankton, and its glow outside the
   *     flashlight (the specks crowd the fish) */
  var CLARITY = {
    deepTint: [[0.28, 0.50, 0.90], [0.62, 0.78, 0.96]],
    deepDim: [0.42, 0.21],
    deepAdd: [[0.0, 0.02, 0.055], [0.0, 0.012, 0.03]],
    lKeep: [0, 0.5],
    floorMin: [0, 0.45],
    back: [0.56, 0.88],
    ambLo: [[0.07, 0.13, 0.14], [0.14, 0.20, 0.21]],
    ambHi: [[0.36, 0.48, 0.46], [0.46, 0.57, 0.55]],
    vivid: [[1, 1, 1], [1.25, 1.15, 0.65]],
    fog: [[0.027, 0.122, 0.125], [0.085, 0.215, 0.225]],
    fogK: [1, 0.6],
    water: [[0.52, 0.57, 0.57], [0.24, 0.38, 0.42]],
    causticK: [1, 0.65],
    snow: [[1, 1], [0.45, 0.5]],
    shadow: [0.40, 0.30],
    foodShade: [1, 0.5],
    foodGain: [1, 0.65]
  };

  function load() {
    if (THREE) return Promise.resolve(window.EvoOceanScene);
    var url = window.EVO_ASSETS && window.EVO_ASSETS.three;
    if (!url) return Promise.reject(new Error("EVO_ASSETS.three missing"));
    /* resolved against the page, like the other assets */
    return import(new URL(url, document.baseURI).href).then(function (m) { THREE = m; return window.EvoOceanScene; });
  }

  /* ---------------- shaders ---------------- */
  /* The chunks the programs share: the water's fog (FOG_FN), the flashlight's clear
   * light (BEAM_FN), light under water (DEPTH_FN) and the water's clarity on a
   * fish's own colour (CLARITY_FN): web/ocean_shaders.js says what each does */
  var FOG_FN = SHADERS.FOG_FN, BEAM_FN = SHADERS.BEAM_FN, DEPTH_FN = SHADERS.DEPTH_FN, CLARITY_FN = SHADERS.CLARITY_FN;

  /* The fish programs, in their variants (the swim polish: plain, full, lite;
   * web/ocean_shaders.js says what each draws and reads), are the binder's
   * (web/ocean_materials.js: assembled variant by variant, when first drawn or
   * warmed); here the appearance fish's probes' programs (appearanceShaders(EA,
   * false)), the gene slot every gene-reading program shares (GENE_SLOT_GLSL)
   * and the split's sentinel (LIT_SKIP: the skip itself is the binder's
   * feature) */
  var appearanceShaders = SHADERS.appearanceShaders, GENE_SLOT_GLSL = SHADERS.GENE_SLOT_GLSL;
  var LIT_SKIP = SHADERS.LIT_SKIP;
  /* The swim pose each lit fish's programs read, packed on the CPU
   * (web/ocean_pose.js): swimPose and its parts (posePx, poseVisibleQ, posePack;
   * POSE0 unlit), the float's layout (packPose, unpackPose) and the reach
   * (REACH_APP, reachOfTemplate, reachRadius) */
  var swimPose = POSE.swimPose, posePx = POSE.posePx, poseVisibleQ = POSE.poseVisibleQ, posePack = POSE.posePack, POSE0 = POSE.POSE0;
  var packPose = POSE.packPose, unpackPose = POSE.unpackPose;
  var REACH_APP = POSE.REACH_APP, reachOfTemplate = POSE.reachOfTemplate, reachRadius = POSE.reachRadius;

  /* The genes' GPU layout (EvoAppearance GENES fetchGenes): a fish's 63
   * floats and one zero in 16 RGBA32F texels at its slot, 512 texels a
   * texture row (32 slots). The renderer's storage is the slot store's
   * (web/ocean_appearance_slots.js, the same layout); the production-path
   * check packs its fixture at its slots with these. */
  var GENES_W = 512, GENE_TEXELS = 16;
  function genesRows(cap) { return Math.ceil(cap * GENE_TEXELS / GENES_W); }
  function packGenes(T, R, r, slot, ST) {
    var to = 4 * GENE_TEXELS * slot;
    for (var j = 0; j < ST; j++) T[to + j] = R[r + j];
    T[to + 63] = 0;
  }
  /* a power-of-two capacity (256 up) for n: the instance buffers' (AppKind ensure), the fixture's texture */
  function capFor(n) { var cap = 256; while (cap < n) cap *= 2; return cap; }

  /* The appearance checks (web/ocean_scene_parity.js, window.EvoOceanSceneParity, which says what
   * each checks): appearancePathCheck, appearanceVertexCheck and appearanceFragmentCheck on any WebGL2
   * context, against the CPU mirror. They take the gene texture's layout above and the water's
   * constants (CLARITY, C.select) from here (bind) */
  PARITY.bind({ GENES_W: GENES_W, genesRows: genesRows, packGenes: packGenes, capFor: capFor, CLARITY: CLARITY, C: C });
  var appearanceVertexCheck = PARITY.appearanceVertexCheck, appearanceFragmentCheck = PARITY.appearanceFragmentCheck;
  var appearancePathCheck = PARITY.appearancePathCheck;

  /* The environment's programs (web/ocean_shaders.js): the seabed and the surface seen
   * from below (FLOOR_VS with FLOOR_FS / SURF_FS), the plankton, the predators' glow,
   * the marine snow, the glass walls, the current streaks and the trail, the rings */
  var FLOOR_VS = SHADERS.FLOOR_VS, FLOOR_FS = SHADERS.FLOOR_FS, SURF_FS = SHADERS.SURF_FS;
  var FOOD_VS = SHADERS.FOOD_VS, FOOD_FS = SHADERS.FOOD_FS, GLOW_VS = SHADERS.GLOW_VS, GLOW_FS = SHADERS.GLOW_FS;
  var SNOW_VS = SHADERS.SNOW_VS, SNOW_FS = SHADERS.SNOW_FS, GLASS_VS = SHADERS.GLASS_VS, GLASS_FS = SHADERS.GLASS_FS;
  var LINE_VS = SHADERS.LINE_VS, LINE_FS = SHADERS.LINE_FS, RING_VS = SHADERS.RING_VS, RING_FS = SHADERS.RING_FS;

  /* ---------------- geometry ---------------- */
  /* A fish in body units: x = position along the spine (0 head .. 1 last
   * segment; < 0 snout, > 1 tail fin), y = sideways, z = up, both in body
   * radii. part: 0 body, 1 fin, 2 eye. */
  function fishTemplate(pred) {
    var rings = pred
      ? [[-0.34, 0, 0], [-0.17, 0.40, 0.34], [0.02, 0.80, 0.66], [0.22, 1.0, 0.82],
         [0.46, 0.90, 0.70], [0.68, 0.62, 0.50], [0.86, 0.36, 0.32], [1.0, 0.18, 0.18]]
      : [[-0.20, 0, 0], [-0.10, 0.50, 0.42], [0.04, 0.88, 0.74], [0.20, 1.0, 0.84],
         [0.42, 0.86, 0.72], [0.64, 0.60, 0.52], [0.84, 0.36, 0.33], [1.0, 0.20, 0.20]];
    var SIDES = 6, pos = [], part = [], idx = [];
    function v(u, y, z, p) { pos.push(u, y, z); part.push(p); return part.length - 1; }
    function tri(a, b, c) { idx.push(a, b, c); }
    var tip = v(rings[0][0], 0, 0, 0), prev = null, k, r;
    for (r = 1; r < rings.length; r++) {
      var ring = [];
      for (k = 0; k < SIDES; k++) {
        var a = k / SIDES * TAU;
        ring.push(v(rings[r][0], Math.cos(a) * rings[r][1], Math.sin(a) * rings[r][2], 0));
      }
      for (k = 0; k < SIDES; k++) {
        var k1 = (k + 1) % SIDES;
        if (!prev) tri(tip, ring[k], ring[k1]);
        else { tri(prev[k], ring[k], ring[k1]); tri(prev[k], ring[k1], prev[k1]); }
      }
      prev = ring;
    }
    var cap = v(1.0, 0, 0, 0);
    for (k = 0; k < SIDES; k++) tri(prev[k], cap, prev[(k + 1) % SIDES]);
    /* tail: a horizontal forked fin, read clearly from above */
    var tw = pred ? 1.28 : 1.02, tl = pred ? 1.40 : 1.32, tn = pred ? 1.20 : 1.17;
    var c0 = v(1.0, 0, 0, 1), lb = v(0.99, -0.2, 0, 1), rb = v(0.99, 0.2, 0, 1);
    var lt = v(tl, -tw, 0, 1), rt = v(tl, tw, 0, 1), notch = v(tn, 0, 0, 1);
    tri(c0, lb, lt); tri(c0, lt, notch); tri(c0, notch, rt); tri(c0, rt, rb);
    /* dorsal fin */
    var dh = pred ? 1.95 : 1.45;
    var d0 = v(pred ? 0.18 : 0.26, 0, 0.80, 1), d1 = v(pred ? 0.62 : 0.60, 0, 0.55, 1);
    var d2 = v(pred ? 0.40 : 0.50, 0, dh, 1);
    tri(d0, d1, d2);
    /* pectoral fins */
    var pl = pred ? 2.1 : 1.7;
    [-1, 1].forEach(function (sd) {
      var p0 = v(0.14, sd * 0.84, -0.12, 1), p1 = v(0.34, sd * 0.70, -0.20, 1);
      var p2 = v(0.40, sd * pl, -0.40, 1);
      tri(p0, p1, p2);
      /* eye: a small diamond standing on the flank */
      var u0 = pred ? -0.02 : 0.03, ex = sd * (pred ? 0.70 : 0.78);
      var e0 = v(u0 - 0.055, ex, 0.30, 2), e1 = v(u0, ex * 1.04, 0.44, 2);
      var e2 = v(u0 + 0.055, ex, 0.30, 2), e3 = v(u0, ex * 1.04, 0.16, 2);
      tri(e0, e1, e2); tri(e0, e2, e3);
    });
    return { pos: new Float32Array(pos), part: new Float32Array(part), idx: idx };
  }

  /* A tileable caustic pattern (after Dave Hoskins' "Tileable Water
   * Caustic"), computed once; the floor animates it by sliding two copies
   * across each other and keeping the darker. */
  function causticTexture(size) {
    var data = new Uint8Array(size * size * 4), t = 0.85, inten = 0.005;
    for (var y = 0; y < size; y++) {
      for (var x = 0; x < size; x++) {
        var px = (x / size) * TAU - 250, py = (y / size) * TAU - 250;
        var ix = px, iy = py, c = 1;
        for (var n = 0; n < 5; n++) {
          var tt = t * (1 - 3.5 / (n + 1));
          var nx = px + Math.cos(tt - ix) + Math.sin(tt + iy);
          var ny = py + Math.sin(tt - iy) + Math.cos(tt + ix);
          ix = nx; iy = ny;
          c += 1 / Math.hypot(px / (Math.sin(ix + tt) / inten), py / (Math.cos(iy + tt) / inten));
        }
        c /= 5;
        c = 1.17 - Math.pow(c, 1.4);
        var val = Math.min(1, Math.pow(Math.abs(c), 8));
        var o = (y * size + x) * 4;
        data[o] = data[o + 1] = data[o + 2] = Math.round(val * 255);
        data[o + 3] = 255;
      }
    }
    var tex = new THREE.DataTexture(data, size, size);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.generateMipmaps = true;
    tex.needsUpdate = true;
    return tex;
  }

  function hash01(n) { var s = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return s - Math.floor(s); }

  /* without web/ocean_perf.js: a profiler that records nothing */
  var NO_PROFILER = (function () {
    function no() {} function zero() { return 0; }
    return { active: false, SPAN: {}, K: {}, beginCpu: zero, lap: zero, endCpu: no, count: no, add: no, markDiagnostic: no,
             attachGL: no, watch: no, beginSubmission: no, endSubmission: no, suspend: function (f) { return f(); } };
  })();

  /* ---------------- the scene ---------------- */
  function create(canvas, opts) {
    if (!THREE) return null;
    opts = opts || {};
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: !opts.coarse, alpha: false,
                                           powerPreference: "high-performance", stencil: false });
    } catch (e) {
      console.warn("evo_boids: WebGL2 unavailable: the 3-D tank cannot be drawn (the page offers 2-D Classic)", e);
      return null;
    }
    renderer.toneMapping = THREE.NoToneMapping;
    /* measurement (web/ocean_perf.js): opts.profiler, else one that records
     * nothing; and the snow's and the current streaks' generator
     * (opts.visualRandom: the benchmark's seeded one; else Math.random) */
    var profiler = opts.profiler || (window.EvoOceanPerf && window.EvoOceanPerf.disabled) || NO_PROFILER;
    var SP = profiler.SPAN || {}, PK = profiler.K || {};
    profiler.attachGL(renderer.getContext());
    var vrand = opts.visualRandom || Math.random;
    /* the gene texture's uploads as three performed them (DataTexture.onUpdate:
     * uploads, one per consumed texture update; calls, its texSubImage2D calls,
     * one per range or one for the whole texture; bytes), kept with or without
     * a profiler: the live-texture probe asserts it caused none */
    var geneIO = { uploads: 0, calls: 0, bytes: 0, allocs: 0, rowChanges: 0, full: { storage: 0, bytes: 0, ranges: 0, policy: 0 } };
    /* the shaders write sRGB as-is, but three colour-manages the clear colour:
     * hand it over as sRGB ("srgb" = THREE.SRGBColorSpace) so the water above
     * the horizon (seen from a low camera) is the fog colour, not a pale teal */
    renderer.setClearColor(new THREE.Color().setRGB(C.fog[0], C.fog[1], C.fog[2], "srgb"), 1);
    var lost = false;
    canvas.addEventListener("webglcontextlost", function (e) { e.preventDefault(); lost = true; });
    canvas.addEventListener("webglcontextrestored", function () {
      lost = false;
      /* three made new GPU storage for the gene texture: one whole upload (the slots keep their owners and data) */
      if (appKind) { appKind.slots.requireFull(); appKind.pending = null; }
    });

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(FOV, 1, 4, 20000);
    var W = 1920, H = 1080, halfW = 960, halfH = 540;
    var WALLS = false;   /* the tank's sides: glass (setWorld's opts.walls) or wrapping */
    /* the tank's depth D (sim units, the world's oc_depth_max) and its floor,
     * a little below the deepest a fish can swim */
    var TD = opts.tankDepth > 0 ? +opts.tankDepth : TANK_D;
    var FLOOR_Y = -(TD + 14);
    var reduced = !!opts.reducedMotion;
    var quality = opts.coarse ? 2 : 3;
    /* the swim polish (POSE_GLSL): "on" (drawn from detail 2 up), "off", or
     * "ungated" (every fish at full weight: the measurements' reference);
     * setPolish. polishNow(): the polished programs this frame */
    var polishWant = "on";
    function polishNow() { return polishWant !== "off" && quality >= 2; }
    var insets = { top: 0, right: 0, bottom: 0, left: 0 };
    var cw = 1, ch = 1;

    function v3(a) { return new THREE.Vector3(a[0], a[1], a[2]); }
    var common = {
      uHalf: { value: new THREE.Vector2(halfW, halfH) },
      uTime: { value: 0 },
      uFog: { value: v3(C.fog) },
      uFogDensity: { value: 0.0003 },
      uLight: { value: v3(LIGHT) },
      uDepth: { value: TD },
      uFloorY: { value: FLOOR_Y },
      /* the engine's light field (setLight); off = the preview's depth shading */
      uLightOn: { value: 0 }, uL0: { value: 1 }, uKWater: { value: 0 },
      /* the flashlight (setFlashlight, BEAM_FN): its fade 0..1, axis, cone, reach */
      uBeamOn: { value: 0 }, uBeamDir: { value: new THREE.Vector3(0, -1, 0) },
      uBeamTan: { value: 0.2 }, uBeamReach: { value: 1000 },
      /* the tank's sides: 1 = glass walls (setWorld), 0 = wrapping */
      uWalls: { value: 0 }
    };
    function beamUniforms(u) {
      u.uBeamOn = common.uBeamOn; u.uBeamDir = common.uBeamDir;
      u.uBeamTan = common.uBeamTan; u.uBeamReach = common.uBeamReach;
      return u;
    }
    /* the water's clarity (setClarity; DEPTH_FN, CLARITY_FN), shared by every
     * material that shades with depth: the fish, the predators, the
     * appearance fish and the food (clarityUniforms adds them to one) */
    var clarityU = {
      uDeepTint: { value: v3(CLARITY.deepTint[1]) }, uDeepDim: { value: CLARITY.deepDim[1] },
      uDeepAdd: { value: v3(CLARITY.deepAdd[1]) }, uLKeep: { value: CLARITY.lKeep[1] },
      uFloorMin: { value: CLARITY.floorMin[1] }, uBack: { value: CLARITY.back[1] },
      uAmbLo: { value: v3(CLARITY.ambLo[1]) }, uAmbHi: { value: v3(CLARITY.ambHi[1]) },
      uVivid: { value: v3(CLARITY.vivid[1]) }
    };
    function clarityUniforms(u) {
      Object.keys(clarityU).forEach(function (k) { u[k] = clarityU[k]; });
      return u;
    }

    /* floor */
    var floorMat = new THREE.ShaderMaterial({
      vertexShader: FLOOR_VS, fragmentShader: FLOOR_FS,
      uniforms: beamUniforms({
        uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
        uCaustic: { value: (function () { var t = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1); t.needsUpdate = true; return t; })() },
        uCausticAmt: { value: 0 }, uCausticTrue: { value: 0 },
        uSand: { value: v3(C.sand) }, uSandDark: { value: v3(C.sandDark) }, uWater: { value: v3(C.water) },
        uCausticCol: { value: v3(C.caustic) }, uEdge: { value: v3(C.edge) }, uLight: common.uLight
      })
    });
    var floor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = FLOOR_Y;
    floor.renderOrder = 0;
    scene.add(floor);
    profiler.watch(floor, "floor");

    /* the surface, lit from above when seen from below (SURF_FS); it shares
     * the floor's caustic texture uniform, so it shimmers once that is built */
    var surfMat = new THREE.ShaderMaterial({
      vertexShader: FLOOR_VS, fragmentShader: SURF_FS,
      uniforms: { uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
                  uCaustic: floorMat.uniforms.uCaustic, uSky: { value: v3(C.surfSky) }, uMirror: { value: v3(C.surfMirror) } },
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide
    });
    var surface = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), surfMat);
    surface.rotation.x = -Math.PI / 2;
    surface.position.y = 0.5;
    surface.renderOrder = 7;
    surface.frustumCulled = false;
    scene.add(surface);
    profiler.watch(surface, "surface");

    /* fish + predators: instanced templates sharing one shader (in its plain
     * and polished variants, which share their uniforms) */
    var fishUniforms = beamUniforms({
      uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
      uLight: common.uLight, uWag: { value: reduced ? 0 : 1 }, uSelect: { value: v3(C.select) },
      uDepth: common.uDepth, uLightOn: common.uLightOn, uL0: common.uL0, uKWater: common.uKWater,
      uWalls: common.uWalls
    });
    var shadowU = { uHalf: common.uHalf, uTime: common.uTime, uWag: fishUniforms.uWag, uLight: common.uLight,
                    uFloorY: common.uFloorY, uDepth: common.uDepth, uFog: common.uFog, uFogDensity: common.uFogDensity,
                    uAlpha: { value: 0.40 }, uWalls: common.uWalls };
    /* The fish kinds' materials: the binder (web/ocean_materials.js) makes
     * them, assembles each variant's programs when it is first drawn or
     * warmed (an assembly error: the plain programs), and assigns them (bind:
     * the kinds' commits below hand it the variant settle() chose); a feature
     * set (setFeatures: a Look's) takes effect only once every reachable
     * variant compiled (compileMaterials). The legacy fish and the predators:
     * the plain [0] and full [1] programs (the lite one is the shadows' only),
     * sharing their uniforms; made here in the order their materials were made
     * before the binder (plain, then full; body, then shadow), so three's draw
     * order is the same; fishMat, shadowMat: the legacy fish's plain ones */
    var binder = MATERIALS.create({ THREE: THREE, compile: compileMaterials });
    binder.define("fish", { uniforms: { body: fishUniforms, shadow: shadowU } });
    binder.define("pred", { uniforms: { body: fishUniforms, shadow: shadowU } });
    binder.prepare(["fish", "pred"]);
    var fishMat = binder.material("fish", "body", 0), shadowMat = binder.material("fish", "shadow", 0);
    /* Which programs a kind draws: 0 plain (main's, at main's cost), 1 full
     * (the polish; its shadow the lite one, the roll). The shader compiler
     * flattens the size weight's guards (a weight 0 costs the full programs
     * as much as 1), and the roll is scaled by the weight (posePack), so an
     * unlit fish looks the same in either: a kind draws its full programs
     * only while one of its fish is lit (weight > 0) and for HOLD frames after
     * the last one (hysteresis: a fish at the 6 px threshold does not switch
     * the whole draw's cost every frame), and only once they are compiled
     * (warm); plain otherwise. With setLitSplit(true) (off by default: see
     * litSplit) the appearance fish (render PR2, their genes in
     * their own slots) then draw only the lit ones on the full programs, in a
     * draw of their own, the rest on the plain ones (AppKind's split; unless
     * more than half are lit), and none on the full ones while none is lit
     * (their hold only keeps the poses packed). A gate per kind (the fish, the predators):
     * hold; lit, this frame's lit fish; posing, whether this frame packed the
     * swim poses (with no fish able to be lit, mayLight, nothing is
     * computed); and the last frame's extent of the fish (mayLight's). */
    var HOLD = 30;
    function Gate() { return { hold: 0, lit: 0, posing: false, bound: 0, rMax: 0, cMax: 0, yMin: 0, yMax: 0, epoch: -1 }; }
    var gateFish = Gate(), gatePred = Gate();
    function settle(g, pose, lit, ready) {
      g.lit = lit;
      if (!pose) g.hold = 0;
      else if (lit > 0) g.hold = HOLD;
      else if (g.hold > 0) g.hold--;
      return g.hold > 0 && ready ? 1 : 0;
    }
    /* Could a fish of this kind be lit this frame? Its weight needs
     * R x focal / (its centre's depth - rb) > 6 px (poseWeight). Every head is
     * in the tank's [-W/2, W/2] x [-H/2, H/2], so a centre is within half a
     * chord of the box of the tank's sides and the fish's heights, and its
     * body sphere within a chord + 2 R: from the last frame's largest radius
     * and chord (|dx| + |dy| >= the chord) and its heights, with room for a
     * frame's change (5 % on the radius, 8 units of swimming on the rest),
     * the nearest any fish can be (8 corners) and the largest it can look.
     * Unknown (a first frame, a new world): yes. (A jump the margins miss, a
     * Turbo return, costs at most one frame of a lit fish drawn plain.) */
    function mayLight(G, g) {
      if (!(g.rMax > 0)) { g.bound = Infinity; return true; }
      var V = G.view, dmin = Infinity;
      for (var i = 0; i < 8; i++) {
        var x = i & 1 ? halfW : -halfW, y = i & 2 ? g.yMax + 8 : g.yMin - 8, z = i & 4 ? halfH : -halfH;
        var d = -(V[2] * x + V[6] * y + V[10] * z + V[14]);
        if (d < dmin) dmin = d;
      }
      g.bound = 1.05 * g.rMax * G.focal / Math.max(dmin - (g.cMax + 2.1 * g.rMax + 8), G.near);
      return g.bound > 6;
    }
    /* The polished programs compiled ahead, off the frame: the first time a
     * kind draws with the polish on, a timeout hands its full and lite
     * programs to renderer.compileAsync (with KHR_parallel_shader_compile the
     * driver compiles them off the main thread; three polls them ready), so
     * the first lit fish never stalls a frame on a compile; until they are
     * ready (or 5 s passed) the kind keeps its plain programs. mats: the
     * binder's materials for them (binder.warm: assembled then, not before) */
    function Warm(mats, geo) { return { mats: mats, geo: geo, asked: false, ready: false }; }
    function warmUp(wm) {
      if (wm.asked) return wm.ready;
      wm.asked = true;
      setTimeout(function () {
        var done = function () { wm.ready = true; };
        if (lost) { wm.asked = false; return; }
        var ws = new THREE.Scene();
        wm.mats().forEach(function (m) { var o = new THREE.Mesh(wm.geo(), m); o.frustumCulled = false; ws.add(o); });
        try {
          if (renderer.compileAsync) { renderer.compileAsync(ws, camera, scene).then(done, done); setTimeout(done, 5000); }
          else { renderer.compile(ws, camera, scene); done(); }
        } catch (e) { done(); }
      }, 0);
      return false;
    }
    /* A feature set's activation (binder.activate, setFeatures): its
     * materials compiled as warmUp does (on their kind's geometry, the faces'
     * on the Look's), then each program checked runnable (three checks a
     * program's link when it is first used: getUniforms; diagnostics). A
     * Promise of {ok, error}; the binder switches to the set only on ok */
    function compileMaterials(items) {
      return new Promise(function (resolve) {
        if (lost) { resolve({ ok: false, error: "the WebGL context is lost" }); return; }
        var ws = new THREE.Scene(), settled = false;
        function end(r) { if (!settled) { settled = true; resolve(r); } }
        items.forEach(function (x) {
          var g = x.geometry ? x.geometry() : x.kind === "app" ? appKind && appKind.geo : x.kind === "pred" ? preds.geo : fish.geo;
          var o = new THREE.Mesh(g || fish.geo, x.material); o.frustumCulled = false; ws.add(o);
        });
        function verify() {
          var bad = items.filter(function (x) {
            var p = renderer.properties.get(x.material).currentProgram;
            if (!p) return true;
            p.getUniforms();
            return !!(p.diagnostics && p.diagnostics.runnable === false);
          }).map(function (x) { return x.key; });
          end(bad.length ? { ok: false, error: "did not compile: " + bad.join(", ") } : { ok: true });
        }
        function fail(e) { end({ ok: false, error: String(e && e.message || e) }); }
        setTimeout(function () { end({ ok: false, error: "the compile did not finish in 10 s" }); }, 10000);
        try {
          if (renderer.compileAsync) renderer.compileAsync(ws, camera, scene).then(verify, fail);
          else { renderer.compile(ws, camera, scene); verify(); }
        } catch (e) { fail(e); }
      });
    }
    /* the instance attributes' uploads for n instances (but skip's); returns
     * the bytes queued (item-size aware) */
    function commitInstances(attrs, n, skip) {
      var bytes = 0;
      Object.keys(attrs).forEach(function (name) {
        if (name === skip) return;
        var a = attrs[name];
        a.clearUpdateRanges();
        a.addUpdateRange(0, n * a.itemSize);
        a.needsUpdate = true;
        bytes += n * a.itemSize * 4;
      });
      return bytes;
    }
    function allocBytes(attrs, cap) { var b = 0; Object.keys(attrs).forEach(function (k) { b += cap * attrs[k].itemSize * 4; }); return b; }

    /* One instanced kind: template + six per-instance attributes (iX: the
     * pitch; iX.y the packed swim pose, POSE_GLSL; the binder's layout, fish
     * or pred). The geometry is rebuilt (and the old one disposed) only when
     * it has to grow. */
    function Kind(pred) {
      var tpl = fishTemplate(pred), name = pred ? "pred" : "fish";
      var self = { cap: 0, n: 0, geo: null, mesh: null, shadow: null, attrs: null, verts: tpl.pos.length / 3, tris: tpl.idx.length / 3, bytes: 0,
                   reach: reachOfTemplate(tpl.pos) };
      function build(cap) {
        var g = new THREE.InstancedBufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(tpl.pos, 3));
        g.setAttribute("part", new THREE.BufferAttribute(tpl.part, 1));
        g.setIndex(tpl.idx);
        var at = {};
        ["iA", "iB", "iC", "iCol", "iBody", "iX"].forEach(function (name) {
          var a = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4);
          a.setUsage(THREE.DynamicDrawUsage);
          g.setAttribute(name, a);
          at[name] = a;
        });
        g.instanceCount = 0;
        if (self.geo) {
          self.geo.dispose();
          self.mesh.geometry = g;
          self.shadow.geometry = g;
        } else {
          /* (made with the binder's plain materials; from the first commit on, the binder binds them) */
          self.mesh = new THREE.Mesh(g, binder.material(name, "body", 0));
          self.shadow = new THREE.Mesh(g, binder.material(name, "shadow", 0));
          self.mesh.frustumCulled = self.shadow.frustumCulled = false;
          self.shadow.renderOrder = 1;
          self.mesh.renderOrder = 2;
          scene.add(self.shadow);
          scene.add(self.mesh);
          profiler.watch(self.mesh, pred ? "predBody" : "fishBody");
          profiler.watch(self.shadow, pred ? "predShadow" : "fishShadow");
        }
        self.geo = g; self.attrs = at; self.cap = cap;
      }
      self.ensure = function (n) {
        if (n <= self.cap) return;
        var cap = Math.max(256, self.cap);
        while (cap < n) cap *= 2;
        build(cap);
      };
      /* v: the programs drawn (settle; the fill packed the swim pose for 1),
       * handed to the binder, which assigns the materials */
      self.commit = function (n, v) {
        self.n = n;
        self.geo.instanceCount = n;
        self.bytes = commitInstances(self.attrs, n);
        binder.bind(self.mesh, name, "body", v ? 1 : 0);
        binder.bind(self.shadow, name, "shadow", v ? 1 : 0);
        self.mesh.visible = n > 0;
        self.shadow.visible = n > 0 && quality >= 2;
      };
      /* the programs the last commit drew (1 full; 0 plain, or the plain ones a failed assembly fell back to) */
      self.variant = function () { return binder.variantOf(self.mesh); };
      self.ensure(pred ? 64 : 2048);
      return self;
    }
    var fish = Kind(false), preds = Kind(true);
    /* the legacy fish's and the predators' polished programs (one pair of programs for both kinds) */
    var warmFish = Warm(function () { return binder.warm(["fish", "pred"]); }, function () { return fish.geo; });

    /* The appearance genome's fish (built on the first snapshot with s.app;
     * null without web/ocean_appearance.js, web/ocean_appearance_slots.js or
     * float textures): the M1 template at two qualities (medium; coarse while
     * the tank's detail is below 3), the barbel strips as a second instanced
     * draw sharing every instance attribute, and a fish's 63 genes in a
     * RGBA32F texture (16 texels a fish, 512 wide) at the fish's own gene
     * slot (render PR2): AppKind.slots (EvoAppearanceSlots) owns the slots and
     * the texture's storage, keyed by the fish's id and the world's epoch;
     * reconcile(s) hands it each snapshot (a fish's genes are copied once,
     * when it is first seen) and writes each draw's slot into iGeneSlot. Two
     * lifetimes: the instance buffers and geometries (rebuildGeometry: on
     * growth of the draw, or a quality change: the gene texture stays), and
     * the gene texture (ensureGeneTexture: new GPU storage only when the
     * slots' storage grew). The upload (commit) is the slots' plan: nothing
     * on a frame whose fish are the last frame's, the dirty slots' ranges
     * after births, the whole texture for new GPU storage; a plan counts as
     * done only when three performed it (onUpdate). appSkin (setAppearance):
     * the skin from the genes, else the family / brain colour. */
    var EA = window.EvoAppearance || null, SLOTS = window.EvoAppearanceSlots || null;
    var appSkin = false, appStatus = !EA ? "web/ocean_appearance.js not loaded" : (SLOTS ? "ready" : "web/ocean_appearance_slots.js not loaded");
    var appKind = null;
    /* the gene uploads: "dirty" (the slots' plans), or "full" (the whole
     * texture every frame, as before PR2, through the same slots: measurements
     * and the dirty-vs-full reference only; setGeneUploads) */
    var genePolicy = "dirty";
    /* the lit fish drawn apart (AppKind's split): OFF by default, setLitSplit(true)
     * to draw it. Measured on Iris Xe (render PR2's perf, headless Brave / ANGLE
     * D3D11, 1400 x 900) it never paid: +0.4 ms GPU at 300 fish following one
     * (67 lit), +1.8 ms at 2,000 (375 lit), +0.8 / +1.2 ms with 274 / 491 lit
     * in nearer whole-tank views. The skipped instances still run the plain
     * vertex stage (the compiler flattens the early return, as it does the size
     * weight's guards), so each lit fish pays two vertex passes, while drawing
     * the many small unlit fish plain saves little; and this tank's fish cross
     * the 6 px threshold together (0 lit, then hundreds), so the "a few lit
     * fish" case it was for barely occurs. A compacted draw (a base instance,
     * or the lit fish moved out of the main draw) would be its next form. The
     * look is the same either way (0 differing pixels) */
    var litSplit = false;
    function AppKind() {
      if (!SLOTS) throw new Error("web/ocean_appearance_slots.js not loaded");
      var gl0 = renderer.getContext(), maxTex = gl0.getParameter(gl0.MAX_TEXTURE_SIZE);
      if (!(maxTex >= GENES_W)) throw new Error("MAX_TEXTURE_SIZE " + maxTex + " is below the gene texture's width " + GENES_W);
      /* at most MAX_TEXTURE_SIZE rows of 32 slots (and 2^24: a slot is exact in a float) */
      var slots = SLOTS.create({ stride: EA.STRIDE, barbelGene: EA.MO + 26, barbelMin: 0.2, initialCapacity: 256,
                                 maxCapacity: Math.min(SLOTS.MAX_CAPACITY, maxTex * (GENES_W / GENE_TEXELS)) });
      var sh = appearanceShaders(EA, false);   /* (the probes' programs: chart, raw genes, texture-fed chart) */
      var tpls = { medium: EA.buildTemplate("medium"), coarse: EA.buildTemplate("coarse") };
      var barbTpl = EA.buildBarbels("medium");
      var U = beamUniforms({
        uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
        uLight: common.uLight, uWag: fishUniforms.uWag, uSelect: fishUniforms.uSelect,
        uDepth: common.uDepth, uLightOn: common.uLightOn, uL0: common.uL0, uKWater: common.uKWater,
        uIntrinsic: { value: 0 }, uPxPerUnit: { value: 500 }, uColourBy: { value: 0 },
        uGenes: { value: null }, uRingT: { value: new Float32Array(16) }, uRingN: { value: 0 }, uHalfRing: { value: 4 },
        uWalls: common.uWalls
      });
      var shadowU = { uHalf: common.uHalf, uTime: common.uTime, uWag: fishUniforms.uWag, uLight: common.uLight,
                      uFloorY: common.uFloorY, uDepth: common.uDepth, uFog: common.uFog, uFogDensity: common.uFogDensity,
                      uAlpha: shadowMat.uniforms.uAlpha, uPxPerUnit: U.uPxPerUnit,
                      uGenes: U.uGenes, uRingT: U.uRingT, uRingN: U.uRingN, uHalfRing: U.uHalfRing, uWalls: common.uWalls };
      /* its materials (the binder's): the body's plain and full programs (settle), the shadow's plain and
       * polished (the roll only: the lite polish), sharing their uniforms, and the split's main draw (below);
       * made in that order, as before the binder. mat: the plain body's (the probes bind its uGenes) */
      binder.define("app", { uniforms: { body: U, shadow: shadowU }, env: { EA: EA } });
      binder.prepare(["app"]);
      var mat = binder.material("app", "body", 0);
      /* The lit fish drawn apart (render PR2's stretch; option 2 of the #48
       * review). While the full programs are due (settle) and some fish, at
       * most half of them, are lit (commit: 60 % once split; none lit, e.g.
       * the hold after the last one, draws the plain programs), the lit fish's
       * bodies and barbels are copied into a small
       * draw of their own (lit: its own instance buffers, the same gene
       * texture through their slots) on the full programs, and the main draw
       * keeps every fish in snapshot order on the plain body program plus one
       * line (the binder's litSkip pass, its skip feature first in main(): an
       * instance whose iBody.z is the LIT_SKIP sentinel is
       * clipped before any gene fetch): so a close view's few lit fish no
       * longer put every other fish on the full programs. The shadows are not
       * split: every fish's in the main draw on the lite shadow program, as
       * without the split. An unlit fish looks the same on either body
       * program (the roll, the fold and the polish terms scale with its size
       * weight, 0). setLitSplit(false): the whole kind on the full programs,
       * as before (measurements). */
      /* cap: the draw's capacity (instance buffers); slots.capacity: the gene texture's (gene slots) */
      var self = { cap: 0, n: 0, lod: "", attrs: null, geo: null, bgeo: null, mesh: null, bmesh: null, shadow: null,
                   tex: null, texData: null, slots: slots, pending: null, slotAttrFresh: false, last: null, litIdx: new Int32Array(0),
                   lit: { cap: 0, n: 0, on: false, lod: "", attrs: null, geo: null, bgeo: null, mesh: null, bmesh: null, bytes: 0 },
                   mat: mat, shaders: sh, barbels: false, tpls: tpls, barbTpl: barbTpl, bytes: 0 };
      var lit = self.lit;
      /* its polished programs and the split's plain body one with the skip (warmUp) */
      self.warm = Warm(function () { return binder.warm(["app"]); }, function () { return self.geo; });
      var INST = ["iA", "iB", "iC", "iBody", "iX", "iGeneSlot"];
      self.inst = INST;   /* the instance attributes the probes share (iGeneSlot: the slots they read through) */
      /* three uploaded the gene texture (DataTexture.onUpdate, after its
       * texSubImage2D calls): the pending plan is done (its slots clean, its
       * calls and bytes counted); an upload no plan asked for (a probe's
       * planted needsUpdate) was the whole texture */
      function onGeneUpload(t) {
        if (t && t !== self.tex) return;   /* (a texture replaced on growth) */
        var p = self.pending, calls = 1, bytes = self.texData.byteLength;
        self.pending = null;
        if (p) {
          calls = p.calls; bytes = p.bytes; slots.acknowledge(p);
          if (p.full) geneIO.full[genePolicy === "full" ? "policy" : p.reason]++;   /* why a whole upload: new storage, over an eighth dirty, over 32 ranges */
        }
        geneIO.uploads++; geneIO.calls += calls; geneIO.bytes += bytes;
        profiler.add(PK.geneUploads, 1); profiler.add(PK.geneUploadCalls, calls); profiler.add(PK.geneUploadBytes, bytes);
      }
      function geometry(tpl, at) {
        var g = new THREE.InstancedBufferGeometry();
        var p3 = new Float32Array(tpl.verts * 3);
        for (var i = 0; i < tpl.verts; i++) { p3[3 * i] = tpl.pos[4 * i]; p3[3 * i + 1] = tpl.pos[4 * i + 1]; p3[3 * i + 2] = tpl.pos[4 * i + 2]; }
        g.setAttribute("position", new THREE.BufferAttribute(p3, 3));   /* for three's bookkeeping; the shader reads aT */
        g.setAttribute("aT", new THREE.BufferAttribute(tpl.pos, 4));
        g.setAttribute("aPattern", new THREE.BufferAttribute(tpl.pat, 4));
        g.setIndex(tpl.idx);
        INST.forEach(function (name) { g.setAttribute(name, at[name]); });
        g.instanceCount = 0;
        return g;
      }
      function setRings(tpl) {
        for (var i = 0; i < 16; i++) U.uRingT.value[i] = i < tpl.ringT.length ? tpl.ringT[i] : 0;
        U.uRingN.value = tpl.ringT.length; U.uHalfRing.value = tpl.half;
      }
      /* the instance buffers (four floats a fish, one for the slot) and the
       * geometries for a draw of cap fish at quality lod; the gene texture is not touched */
      function rebuildGeometry(cap, lod) {
        var at = {};
        INST.forEach(function (name) {
          var k = name === "iGeneSlot" ? 1 : 4;
          var a = new THREE.InstancedBufferAttribute(new Float32Array(cap * k), k);
          a.setUsage(THREE.DynamicDrawUsage);
          at[name] = a;
        });
        var g = geometry(tpls[lod], at), bg = barbTpl ? geometry(barbTpl, at) : null;
        profiler.add(PK.instAllocBytes, allocBytes(at, cap));
        if (self.geo) {
          self.geo.dispose(); if (self.bgeo) self.bgeo.dispose();
          self.mesh.geometry = g; self.shadow.geometry = g;
          if (self.bmesh && bg) self.bmesh.geometry = bg;
        } else {
          /* (made with the binder's plain materials; from the first commit on, the binder binds them) */
          self.mesh = new THREE.Mesh(g, mat);
          self.shadow = new THREE.Mesh(g, binder.material("app", "shadow", 0));
          self.mesh.frustumCulled = self.shadow.frustumCulled = false;
          self.shadow.renderOrder = 1; self.mesh.renderOrder = 2;
          scene.add(self.shadow); scene.add(self.mesh);
          profiler.watch(self.mesh, "fishBody"); profiler.watch(self.shadow, "fishShadow");
          if (bg) {
            self.bmesh = new THREE.Mesh(bg, mat);
            self.bmesh.frustumCulled = false; self.bmesh.renderOrder = 2;
            scene.add(self.bmesh);
            profiler.watch(self.bmesh, "barbels");
          }
        }
        setRings(tpls[lod]);
        self.geo = g; self.bgeo = bg; self.attrs = at; self.cap = cap; self.lod = lod;
        if (self.litIdx.length < cap) self.litIdx = new Int32Array(cap);
        self.slotAttrFresh = true;   /* the slots are written into the new iGeneSlot: upload it */
      }
      /* the lit draw's instance buffers (cap fish) and geometries (body, barbels; their shadows stay in the main draw) */
      function rebuildLit(cap, lod) {
        var at = {};
        INST.forEach(function (name) {
          var k = name === "iGeneSlot" ? 1 : 4;
          var a = new THREE.InstancedBufferAttribute(new Float32Array(cap * k), k);
          a.setUsage(THREE.DynamicDrawUsage);
          at[name] = a;
        });
        var g = geometry(tpls[lod], at), bg = barbTpl ? geometry(barbTpl, at) : null;
        if (lit.geo) {
          lit.geo.dispose(); if (lit.bgeo) lit.bgeo.dispose();
          lit.mesh.geometry = g;
          if (lit.bmesh && bg) lit.bmesh.geometry = bg;
        } else {
          /* drawn before the main fish draw (renderOrder 1.5 < 2): the lit fish are the large close ones, so
           * the depth test then rejects the fragments of the fish behind them before they are shaded (as the
           * single draw does when the close fish come first) (the binder's full body material; drawLit binds it) */
          lit.mesh = new THREE.Mesh(g, binder.material("app", "body", 1));
          lit.mesh.frustumCulled = false; lit.mesh.renderOrder = 1.5; lit.mesh.visible = false;
          scene.add(lit.mesh);
          profiler.watch(lit.mesh, "fishBody");
          if (bg) {
            lit.bmesh = new THREE.Mesh(bg, binder.material("app", "body", 1));
            lit.bmesh.frustumCulled = false; lit.bmesh.renderOrder = 1.5; lit.bmesh.visible = false;
            scene.add(lit.bmesh);
            profiler.watch(lit.bmesh, "barbels");
          }
        }
        lit.geo = g; lit.bgeo = bg; lit.attrs = at; lit.cap = cap; lit.lod = lod;
        profiler.add(PK.instAllocBytes, allocBytes(at, cap));
      }
      /* the k lit fish (litIdx: their draw indices, fillApp's) into the lit
       * draw, in their order; their main instances get the skip sentinel in
       * iBody.z (after the copy: the lit draw keeps their highlight; the
       * main shadow draw never reads it) */
      function drawLit(k, barbels) {
        if (k > lit.cap || self.lod !== lit.lod) { var cap = Math.max(64, lit.cap); while (cap < k) cap *= 2; rebuildLit(cap, self.lod); }
        var m = self.attrs, L = lit.attrs, idx = self.litIdx;
        var mA = m.iA.array, mB = m.iB.array, mC = m.iC.array, mY = m.iBody.array, mX = m.iX.array, mS = m.iGeneSlot.array;
        var lA = L.iA.array, lB = L.iB.array, lC = L.iC.array, lY = L.iBody.array, lX = L.iX.array, lS = L.iGeneSlot.array;
        for (var j = 0; j < k; j++) {
          var c = idx[j], o = 4 * c, q = 4 * j;
          for (var t = 0; t < 4; t++) { lA[q + t] = mA[o + t]; lB[q + t] = mB[o + t]; lC[q + t] = mC[o + t]; lY[q + t] = mY[o + t]; lX[q + t] = mX[o + t]; }
          lS[j] = mS[c];
          mY[o + 2] = LIT_SKIP;
        }
        lit.n = k; lit.on = true;
        lit.geo.instanceCount = k;
        if (lit.bgeo) lit.bgeo.instanceCount = k;
        lit.bytes = commitInstances(L, k);
        binder.bind(lit.mesh, "app", "body", 1);
        if (lit.bmesh) binder.bind(lit.bmesh, "app", "body", 1);
        lit.mesh.visible = k > 0;
        if (lit.bmesh) lit.bmesh.visible = k > 0 && !!barbels && self.lod === "medium";
      }
      function hideLit() {
        lit.n = 0; lit.on = false; lit.bytes = 0;
        if (lit.mesh) { lit.mesh.visible = false; if (lit.bmesh) lit.bmesh.visible = false; }
      }
      /* draw index c's lit-draw index, or -1 (tests: poseOf) */
      self.litIndexOf = function (c) { for (var j = 0; j < lit.n; j++) if (self.litIdx[j] === c) return j; return -1; };
      /* the gene texture over the slots' storage: new GPU storage (one whole
       * upload) the first time and whenever the slots' storage grew; the
       * uniform then names the new texture before the old one is disposed */
      function ensureGeneTexture() {
        if (self.tex && self.texData === slots.data) return;
        var data = slots.data, old = self.tex;
        /* RGBA32F, nearest, no mipmaps (three's RGBAFormat 1023, FloatType 1015,
         * NearestFilter 1003: the trimmed bundle does not export the names) */
        var tex = new THREE.DataTexture(data, GENES_W, genesRows(slots.capacity), 1023, 1015);
        tex.magFilter = tex.minFilter = 1003;
        tex.generateMipmaps = false;
        tex.onUpdate = onGeneUpload;
        U.uGenes.value = tex;
        self.tex = tex; self.texData = data; self.pending = null;
        slots.requireFull();
        if (old) old.dispose();
        geneIO.allocs++;
        profiler.add(PK.texAllocs, 1);
      }
      self.ensure = function (n, lod) {
        if (n <= self.cap && lod === self.lod) return;
        var cap = Math.max(256, self.cap);
        while (cap < n) cap *= 2;
        rebuildGeometry(cap, lod);
      };
      /* One complete snapshot (fillFish, before any packing): the draw's
       * buffers for its n fish at quality lod, the slots reconciled (births
       * copied in, the dead released) and each draw's slot in iGeneSlot, the
       * gene texture for the slots' storage. Returns the slots' result (ok
       * false: the snapshot was refused, e.g. a repeated id, and its fish are
       * drawn the plain way; the ownership is forgotten). A row is copied
       * once, when its fish is first seen (the engine's rows never change
       * under an id and epoch); VERIFY owners a frame, in turn, are compared
       * with their snapshot rows all the same, and a difference forgets the
       * ownership and installs every fish again in this frame (warned once) */
      var VERIFY = 2, warnedRows = false;
      self.reconcile = function (s, lod) {
        var n = s.n;
        self.ensure(n, lod);
        var tg = profiler.beginCpu();
        var r = slots.prepare(s.worldEpoch, s.ids, s.app, n, self.attrs.iGeneSlot.array);
        var bad = r.ok ? slots.verify(s.ids, s.app, n, VERIFY) : null;
        if (bad) {
          geneIO.rowChanges++;
          if (!warnedRows) { warnedRows = true; console.warn("evo_boids: fish " + bad.id + "'s appearance genes changed under the same id and world epoch (gene " + bad.gene + "): every fish's genes are installed again"); }
          slots.invalidate();
          r = slots.prepare(s.worldEpoch, s.ids, s.app, n, self.attrs.iGeneSlot.array);
        }
        profiler.endCpu(SP.appearanceRows, tg);
        self.last = r;
        if (!r.ok) { slots.invalidate(); return r; }
        ensureGeneTexture();
        return r;
      };
      /* v: the programs due (settle; fillApp packed the swim pose in iBody.w
       * for 1); slotsMoved: reconcile's changed (iGeneSlot is uploaded only
       * then); nLit: how many fish fillApp lit (litIdx). With the split on
       * (litSplit) and v 1: no fish lit (the hold after the last one: with
       * the lit fish drawn apart there is no whole-draw cost to hold) draws
       * the plain programs; some lit, at most half of the fish (60 % once
       * split: a little hysteresis), the split (above): the lit fish's own
       * draw on the full programs, the main one on the plain programs with
       * the skip; more, the whole kind on the full programs */
      self.splitOn = false;
      self.commit = function (n, barbels, v, slotsMoved, nLit) {
        var full = v === 1, split = false;
        if (full && litSplit) {
          if (nLit === 0) full = false;
          else split = self.splitOn ? nLit * 5 <= n * 3 : nLit * 2 <= n;
        }
        self.splitOn = split;
        var w = full ? 1 : 0;
        if (split) drawLit(nLit, barbels); else hideLit();
        self.n = n;
        self.geo.instanceCount = n;
        if (self.bgeo) self.bgeo.instanceCount = n;
        self.bytes = commitInstances(self.attrs, n, slotsMoved || self.slotAttrFresh ? null : "iGeneSlot") + lit.bytes;
        self.slotAttrFresh = false;
        /* the programs due, handed to the binder (the split's main draw: the plain body with the skip) */
        binder.bind(self.mesh, "app", split ? "litSkip" : "body", split ? 0 : w); binder.bind(self.shadow, "app", "shadow", w);
        if (self.bmesh) binder.bind(self.bmesh, "app", split ? "litSkip" : "body", split ? 0 : w);
        /* the gene texture's upload: the slots' plan, if any (none: the
         * texture's version stays, three uploads nothing); "full" policy: the
         * whole texture every frame */
        var tg = profiler.beginCpu(), plan = null;
        if (genePolicy === "full") slots.requireFull();
        if (!testFaults.holdGeneUploads) plan = slots.plan();
        if (plan) {
          var tex = self.tex;
          tex.clearUpdateRanges();   /* none: the whole texture */
          for (var i = 0; i < plan.ranges.length; i++) tex.addUpdateRange(plan.ranges[i].start, plan.ranges[i].count);
          tex.needsUpdate = true;
          self.pending = plan;
        }
        profiler.endCpu(SP.geneRanges, tg);
        if (profiler.active) {
          profiler.count(PK.instBytes, self.bytes); profiler.count(PK.geneDirtySlots, plan ? plan.slots : slots.dirtyCount);
          profiler.count(PK.geneRanges, plan ? plan.ranges.length : 0); profiler.count(PK.geneFull, plan && plan.full ? 1 : 0);
          profiler.count(PK.texCapacity, slots.capacity);
        }
        self.mesh.visible = n > 0;
        self.shadow.visible = n > 0 && quality >= 2;
        if (self.bmesh) self.bmesh.visible = n > 0 && !!barbels && self.lod === "medium";
      };
      self.hide = function () { if (self.mesh) { self.mesh.visible = self.shadow.visible = false; if (self.bmesh) self.bmesh.visible = false; } hideLit(); };
      /* 1: the full programs drawn (all the fish, or the lit ones apart: lit.on); 0 plain, or the plain
       * ones a failed assembly fell back to */
      self.variant = function () { return self.mesh ? binder.variantOf(lit.on ? lit.mesh : self.mesh) : 0; };
      return self;
    }

    /* food: glowing plankton */
    var foodGeo = new THREE.BufferGeometry(), foodCap = 0;
    var foodMat = new THREE.ShaderMaterial({
      vertexShader: FOOD_VS, fragmentShader: FOOD_FS,
      uniforms: beamUniforms({ uPx: { value: 500 }, uTime: common.uTime, uSize: { value: 11 }, uDepth: common.uDepth,
                  uLightOn: common.uLightOn, uL0: common.uL0, uKWater: common.uKWater,
                  uCore: { value: v3(C.foodCore) }, uGlow: { value: v3(C.foodGlow) } }),
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
    });
    var food = new THREE.Points(foodGeo, foodMat);
    food.frustumCulled = false;
    food.renderOrder = 3;
    scene.add(food);
    profiler.watch(food, "food");
    function ensureFood(n) {
      if (n <= foodCap) return;
      var cap = Math.max(1024, foodCap);
      while (cap < n) cap *= 2;
      var p = new THREE.BufferAttribute(new Float32Array(cap * 3), 3);
      var sd = new THREE.BufferAttribute(new Float32Array(cap), 1);
      p.setUsage(THREE.DynamicDrawUsage); sd.setUsage(THREE.DynamicDrawUsage);
      foodGeo.dispose();
      foodGeo.setAttribute("position", p);
      foodGeo.setAttribute("seed", sd);
      foodCap = cap;
    }
    ensureFood(1024);

    /* predator glow */
    var GLOW_MAX = 512;
    var glowGeo = new THREE.BufferGeometry();
    glowGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(GLOW_MAX * 3), 3).setUsage(THREE.DynamicDrawUsage));
    glowGeo.setAttribute("amt", new THREE.BufferAttribute(new Float32Array(GLOW_MAX), 1).setUsage(THREE.DynamicDrawUsage));
    glowGeo.setDrawRange(0, 0);
    var glowMat = new THREE.ShaderMaterial({
      vertexShader: GLOW_VS, fragmentShader: GLOW_FS,
      uniforms: { uPx: foodMat.uniforms.uPx, uSize: { value: 70 }, uTime: common.uTime,
                  uCol: { value: v3([1.0, 0.42, 0.18]) } },
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
    });
    var glow = new THREE.Points(glowGeo, glowMat);
    glow.frustumCulled = false;
    glow.renderOrder = 1;
    scene.add(glow);
    profiler.watch(glow, "other");

    /* marine snow: a fixed buffer, animated entirely in the shader (more of
     * it than in the shallow tank: it falls through the whole depth) */
    var snowGeo = new THREE.BufferGeometry(), SNOW = 900;
    (function () {
      var p = new Float32Array(SNOW * 3), sd = new Float32Array(SNOW);
      for (var i = 0; i < SNOW; i++) { p[3 * i] = vrand() - 0.5; p[3 * i + 2] = vrand() - 0.5; sd[i] = vrand(); }
      snowGeo.setAttribute("position", new THREE.BufferAttribute(p, 3));
      snowGeo.setAttribute("seed", new THREE.BufferAttribute(sd, 1));
    })();
    var snowUnit = snowGeo.attributes.position.array.slice();
    var snowMat = new THREE.ShaderMaterial({
      vertexShader: SNOW_VS, fragmentShader: SNOW_FS,
      uniforms: { uPx: foodMat.uniforms.uPx, uTime: common.uTime, uHalf: common.uHalf,
                  uFloorY: common.uFloorY, uFall: common.uDepth, uCol: { value: v3(C.snow) } },
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
    });
    var snow = new THREE.Points(snowGeo, snowMat);
    snow.frustumCulled = false;
    snow.renderOrder = 6;
    scene.add(snow);
    profiler.watch(snow, "snow");
    function placeSnow() {
      /* a fixed budget of flakes over the tank (more area: sparser, never
       * more); with glass walls inside the panes, clear of their 14-unit sway */
      var p = snowGeo.attributes.position.array;
      var sx = WALLS ? Math.max(0, W - 30) : W * 1.1, sz = WALLS ? Math.max(0, H - 30) : H * 1.1;
      for (var i = 0; i < SNOW; i++) { p[3 * i] = snowUnit[3 * i] * sx; p[3 * i + 2] = snowUnit[3 * i + 2] * sz; }
      snowGeo.attributes.position.needsUpdate = true;
    }

    /* line layers: currents, the selected fish's trail, the tank outline */
    function LineLayer(cap, col, order) {
      var g = new THREE.BufferGeometry();
      var p = new THREE.BufferAttribute(new Float32Array(cap * 3), 3);
      var a = new THREE.BufferAttribute(new Float32Array(cap), 1);
      p.setUsage(THREE.DynamicDrawUsage); a.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("position", p);
      g.setAttribute("alpha", a);
      g.setDrawRange(0, 0);
      var m = new THREE.ShaderMaterial({ vertexShader: LINE_VS, fragmentShader: LINE_FS,
                                         uniforms: { uCol: { value: v3(col) } },
                                         transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      var obj = new THREE.LineSegments(g, m);
      obj.frustumCulled = false;
      obj.renderOrder = order;
      scene.add(obj);
      profiler.watch(obj, "other");
      return { obj: obj, p: p.array, a: a.array, geo: g,
               commit: function (verts) {
                 g.setDrawRange(0, verts);
                 g.attributes.position.needsUpdate = true;
                 g.attributes.alpha.needsUpdate = true;
               } };
    }
    var STREAKS = 900;
    var currents = LineLayer(STREAKS * 2, C.current, 4);
    var trail = LineLayer(240 * 2, C.select, 5);
    var outline = LineLayer(24, C.edge, 4);   /* the glass box: top, bottom, four verticals */
    /* the glass walls' four side panes (built by setWorld; shown with walls on) */
    var glassGeo = new THREE.BufferGeometry();
    glassGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(24 * 3), 3));
    glassGeo.setAttribute("normal", new THREE.BufferAttribute(new Float32Array(24 * 3), 3));
    var glassMat = new THREE.ShaderMaterial({ vertexShader: GLASS_VS, fragmentShader: GLASS_FS,
      uniforms: { uCol: { value: v3(C.glass) }, uFloorY: common.uFloorY },
      transparent: true, depthWrite: false, side: THREE.DoubleSide });
    var glass = new THREE.Mesh(glassGeo, glassMat);
    glass.frustumCulled = false;
    glass.renderOrder = 8;   /* after the fish, the food and the snow */
    glass.visible = false;
    scene.add(glass);
    profiler.watch(glass, "other");
    function buildGlass() {
      var P = glassGeo.attributes.position.array, N = glassGeo.attributes.normal.array, k = 0;
      var top = -0.5, bot = FLOOR_Y + 0.6;
      function quad(ax, az, bx, bz, nx, nz) {   /* two triangles from (a, top) to (b, bottom) */
        var v = [[ax, top, az], [bx, top, bz], [bx, bot, bz], [ax, top, az], [bx, bot, bz], [ax, bot, az]];
        for (var i = 0; i < 6; i++) {
          P[3 * k] = v[i][0]; P[3 * k + 1] = v[i][1]; P[3 * k + 2] = v[i][2];
          N[3 * k] = nx; N[3 * k + 1] = 0; N[3 * k + 2] = nz; k++;
        }
      }
      quad(-halfW, -halfH, -halfW, halfH, 1, 0);
      quad(halfW, -halfH, halfW, halfH, -1, 0);
      quad(-halfW, -halfH, halfW, -halfH, 0, 1);
      quad(-halfW, halfH, halfW, halfH, 0, -1);
      glassGeo.attributes.position.needsUpdate = true;
      glassGeo.attributes.normal.needsUpdate = true;
    }
    var streak = new Float32Array(STREAKS * 4);   /* x, y, age, life */
    for (var si = 0; si < STREAKS; si++) streak[4 * si + 2] = streak[4 * si + 3] = 1;

    /* selection and hover rings */
    function Ring(strength) {
      var m = new THREE.ShaderMaterial({ vertexShader: RING_VS, fragmentShader: RING_FS,
        uniforms: { uCol: { value: v3(C.select) }, uTime: common.uTime, uStrength: { value: strength } },
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide });   /* seen from below too */
      var mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), m);
      mesh.rotation.x = -Math.PI / 2;
      mesh.renderOrder = 5;
      mesh.visible = false;
      scene.add(mesh);
      profiler.watch(mesh, "other");
      return mesh;
    }
    var selRing = Ring(1), hoverRing = Ring(0.45);

    /* ---------------- camera ---------------- */
    var controls = new THREE.MapControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.screenSpacePanning = false;
    /* A free camera: it may orbit below the horizontal, up to nearly straight
     * up, so from near the floor you can look up at the surface; clampView
     * keeps it out of the sand. */
    controls.maxPolarAngle = Math.PI - 0.08;
    controls.minDistance = 40;
    controls.zoomToCursor = true;
    var MOUSE = { ROTATE: 0, DOLLY: 1, PAN: 2 }, TOUCH = { ROTATE: 0, PAN: 1, DOLLY_ROTATE: 3 };
    var fitDist = 1500, userMoved = false, anim = null;
    var follow = false, onFollow = opts.onFollowChange || function () {};
    var SURF_TOP = 30;   /* the view's centre may rise this far above the surface */
    /* A drag pans over the sea floor when the camera looks down into the tank,
     * and in the screen's plane (so up/down moves the view to another depth)
     * when it looks through the side or up; chosen as each drag starts. */
    controls.addEventListener("start", function () {
      userMoved = true; anim = null;
      controls.screenSpacePanning = controls.getPolarAngle() > 1.2;
    });
    controls.addEventListener("change", clampView);
    /* the view's centre stays near the tank: x/z a little beyond the glass,
     * y between just above the floor and a bit above the surface; the camera
     * never goes under the sand (it slides in along its line of sight) */
    function clampView() {
      var t = controls.target, cp = camera.position, mx = halfW + 80, mz = halfH + 80;
      var x = Math.max(-mx, Math.min(mx, t.x)), z = Math.max(-mz, Math.min(mz, t.z));
      var y = Math.max(FLOOR_Y + 8, Math.min(SURF_TOP, t.y));
      if (x !== t.x || y !== t.y || z !== t.z) {
        cp.x += x - t.x; cp.y += y - t.y; cp.z += z - t.z;
        t.set(x, y, z);
      }
      var minY = FLOOR_Y + 5;
      if (cp.y < minY) {
        var oy = cp.y - t.y, f = oy < -1e-6 ? (minY - t.y) / oy : 1;
        cp.set(t.x + (cp.x - t.x) * f, minY, t.z + (cp.z - t.z) * f);
      }
    }
    /* move the view (target and camera together) up or down, in sim units */
    function moveView(dy) {
      if (follow) { follow = false; setFollowControls(false); onFollow(false); }
      anim = null; userMoved = true;
      controls.target.y += dy; camera.position.y += dy;
      clampView();
    }
    function setFollowControls(on) {
      controls.enablePan = !on;
      controls.mouseButtons.LEFT = on ? MOUSE.ROTATE : MOUSE.PAN;
      controls.touches.ONE = on ? TOUCH.ROTATE : TOUCH.PAN;
    }

    /* ---- keyboard flight (the page's W A S D, Q / E; setMove) ----
     * moveIn: the held keys as axes in -1..1: f forward (W) / back (S), r right
     * (D) / left (A), u up (E) / down (Q); boost = Shift (2.5x).
     * Free camera: the camera and the point it orbits move together, W / S
     * along the line of sight, A / D sideways (level), Q / E straight up and
     * down, so clampView keeps the view at the tank exactly as for a drag.
     * Following a fish: W / S dolly toward / away from it (40 units up to the
     * whole-tank distance), A / D circle it, Q / E lower / raise the camera
     * around it; the follow stays on. Velocities ease in and out (time
     * constant 0.12 s), per frame time, so a held key glides instead of jumping.
     * Speed: a share of the tank's size, less near what the camera looks at. */
    var moveIn = { f: 0, r: 0, u: 0, boost: false };
    var flyVel = new THREE.Vector3(), flyWant = new THREE.Vector3();
    var flyFwd = new THREE.Vector3(), flyRight = new THREE.Vector3(), flyOff = new THREE.Vector3();
    var orbitVel = { az: 0, pol: 0, dolly: 0 };
    var FLY = { span: 0.22, near: 0.15, depth: 0.6, az: 1.3, pol: 0.8, dolly: 1.2, boost: 2.5, tIn: 0.12, tOut: 0.12 };
    function flyLevel() {
      var r = camera.position.distanceTo(controls.target);
      return Math.max(FLY.near, Math.min(1, r / Math.max(1, fitDist)));
    }
    function stepFly(dt) {
      if (!(dt > 0)) return;
      var m = moveIn, any = !!(m.f || m.r || m.u), boost = m.boost ? FLY.boost : 1;
      var k = 1 - Math.exp(-dt / (any ? FLY.tIn : FLY.tOut));
      var t = controls.target, cp = camera.position;
      if (follow) {
        flyVel.set(0, 0, 0);
        orbitVel.az += (m.r * FLY.az * boost - orbitVel.az) * k;
        orbitVel.pol += (-m.u * FLY.pol * boost - orbitVel.pol) * k;
        orbitVel.dolly += (-m.f * FLY.dolly * boost - orbitVel.dolly) * k;
        if (!any && Math.abs(orbitVel.az) + Math.abs(orbitVel.pol) + Math.abs(orbitVel.dolly) < 1e-3) {
          orbitVel.az = orbitVel.pol = orbitVel.dolly = 0;
          return;
        }
        if (m.f) followDive = false;   /* the keys take over from the first close-up */
        flyOff.copy(cp).sub(t);
        var r = flyOff.length();
        if (!(r > 1e-6)) return;
        var theta = Math.atan2(flyOff.x, flyOff.z) + orbitVel.az * dt;
        var phi = Math.acos(Math.max(-1, Math.min(1, flyOff.y / r))) + orbitVel.pol * dt;
        phi = Math.max(0.05, Math.min(controls.maxPolarAngle, phi));
        r = Math.max(controls.minDistance, Math.min(Math.max(controls.minDistance, fitDist), r * Math.exp(orbitVel.dolly * dt)));
        cp.set(t.x + r * Math.sin(phi) * Math.sin(theta), t.y + r * Math.cos(phi), t.z + r * Math.sin(phi) * Math.cos(theta));
        anim = null; userMoved = true;
        return;
      }
      orbitVel.az = orbitVel.pol = orbitVel.dolly = 0;
      flyWant.set(0, 0, 0);
      if (m.f || m.r) {
        camera.getWorldDirection(flyFwd);
        flyRight.setFromMatrixColumn(camera.matrixWorld, 0);
        flyRight.y = 0;
        if (flyRight.lengthSq() > 1e-8) flyRight.normalize();
        flyWant.addScaledVector(flyFwd, m.f).addScaledVector(flyRight, m.r);
        if (flyWant.lengthSq() > 1) flyWant.normalize();
        flyWant.multiplyScalar(Math.max(W, H) * FLY.span * flyLevel() * boost);
      }
      flyWant.y += m.u * TD * FLY.depth * boost;
      flyVel.lerp(flyWant, k);
      if (!any && flyVel.lengthSq() < 1) { flyVel.set(0, 0, 0); return; }   /* below 1 unit / s: stopped */
      t.addScaledVector(flyVel, dt);
      cp.addScaledVector(flyVel, dt);
      anim = null; userMoved = true;
      clampView();
    }

    function dir() { return new THREE.Vector3(0, Math.cos(POLAR), Math.sin(POLAR)); }
    function applyViewOffset() {
      var vw = Math.max(1, cw - insets.left - insets.right), vh = Math.max(1, ch - insets.top - insets.bottom);
      var cx = insets.left + vw / 2, cy = insets.top + vh / 2;
      camera.aspect = cw / ch;
      if (Math.abs(cx - cw / 2) < 0.5 && Math.abs(cy - ch / 2) < 0.5) {
        camera.clearViewOffset();
      } else {
        var fw = 2 * Math.max(cx, cw - cx), fh = 2 * Math.max(cy, ch - cy);
        camera.setViewOffset(fw, fh, fw / 2 - cx, fh / 2 - cy, cw, ch);
      }
      camera.updateProjectionMatrix();
      var fullH = camera.view && camera.view.enabled ? camera.view.fullHeight : ch;
      foodMat.uniforms.uPx.value = fullH * renderer.getPixelRatio() / (2 * Math.tan(FOV * Math.PI / 360));
    }
    /* Distance at which the whole tank fits the visible part of the canvas
     * (the canvas minus the panels' insets), found by projecting the eight
     * corners of its box (surface and floor), aimed at its middle depth. The
     * search starts outside the box's bounding sphere (radius r: at d >=
     * r / sin(fov/2) every corner is in front of the camera), so a big or a
     * deep tank never starts with corners behind it. */
    function computeFit() {
      var r = Math.sqrt(halfW * halfW + halfH * halfH + 0.25 * FLOOR_Y * FLOOR_Y);
      var target = new THREE.Vector3(0, -TD / 2, 0), d = Math.max(1500, 1.05 * r / Math.sin(FOV * Math.PI / 360)), D = dir();
      var vw = Math.max(1, cw - insets.left - insets.right), vh = Math.max(1, ch - insets.top - insets.bottom);
      var bx = insets.left + vw / 2, by = insets.top + vh / 2;
      var corners = [[-halfW, 0, -halfH], [halfW, 0, -halfH], [halfW, 0, halfH], [-halfW, 0, halfH],
                     [-halfW, FLOOR_Y, -halfH], [halfW, FLOOR_Y, -halfH], [halfW, FLOOR_Y, halfH], [-halfW, FLOOR_Y, halfH]];
      var p = new THREE.Vector3();
      var keepPos = camera.position.clone(), keepRot = camera.quaternion.clone();
      for (var it = 0; it < 8; it++) {
        camera.position.copy(target).addScaledVector(D, d);
        camera.lookAt(target);
        camera.updateMatrixWorld();
        var m = 0;
        for (var k = 0; k < 8; k++) {
          p.set(corners[k][0], corners[k][1], corners[k][2]).project(camera);
          var sx = (p.x * 0.5 + 0.5) * cw, sy = (0.5 - p.y * 0.5) * ch;
          m = Math.max(m, Math.abs(sx - bx) / (vw / 2), Math.abs(sy - by) / (vh / 2));
        }
        d *= m / 0.92;
      }
      camera.position.copy(keepPos);
      camera.quaternion.copy(keepRot);
      camera.updateMatrixWorld();
      return { target: target, pos: target.clone().addScaledVector(D, d), dist: d };
    }
    function resetView(animated) {
      var f = computeFit();
      fitDist = f.dist;
      controls.maxDistance = fitDist * 1.9;
      common.uFogDensity.value = 0.42 / fitDist * fogK;   /* fogK: the water's clarity */
      if (follow) { follow = false; setFollowControls(false); onFollow(false); }
      userMoved = false;
      if (animated && !reduced) {
        anim = { t: 0, ft: controls.target.clone(), fp: camera.position.clone(), tt: f.target, tp: f.pos };
      } else {
        anim = null;
        controls.target.copy(f.target);
        camera.position.copy(f.pos);
        camera.lookAt(f.target);
        controls.update();
      }
    }
    function stepAnim(dt) {
      if (!anim) return;
      anim.t = Math.min(1, anim.t + dt / 0.65);
      var e = 1 - Math.pow(1 - anim.t, 4);
      controls.target.lerpVectors(anim.ft, anim.tt, e);
      camera.position.lerpVectors(anim.fp, anim.tp, e);
      if (anim.t >= 1) anim = null;
    }

    function resize() {
      var r = canvas.getBoundingClientRect();
      cw = Math.max(1, Math.round(r.width)); ch = Math.max(1, Math.round(r.height));
      var dpr = Math.min(window.devicePixelRatio || 1, [1, 1.5, 2][quality - 1]);
      renderer.setPixelRatio(dpr);
      renderer.setSize(cw, ch, false);
      applyViewOffset();
      if (!userMoved && !follow) resetView(false);
    }

    /* depth (optional): a new tank depth D; the floor, shading and snow follow.
     * o.walls (optional): the sides are glass (panes drawn, fish held inside
     * them, no seam unwrapping) or wrap; left out, the mode stays. */
    function setWorld(w, h, depth, o) {
      W = w; H = h; halfW = w / 2; halfH = h / 2;
      if (o && typeof o.walls === "boolean") WALLS = o.walls;
      common.uWalls.value = WALLS ? 1 : 0;
      if (depth > 0) {
        TD = +depth; FLOOR_Y = -(TD + 14);
        common.uDepth.value = TD; common.uFloorY.value = FLOOR_Y;
        floor.position.y = FLOOR_Y;
      }
      common.uHalf.value.set(halfW, halfH);
      var span = Math.max(w, h) * 6;
      floor.scale.set(span, span, 1);
      surface.scale.set(span, span, 1);
      placeSnow();
      /* the glass box: the surface rectangle, the one on the floor, and the
       * four vertical edges between them (the verticals a little fainter) */
      var o = outline, k = 0;
      var cs = [[-halfW, -halfH], [halfW, -halfH], [halfW, halfH], [-halfW, halfH]];
      function seg(ax, ay, az, bx, by, bz, al) {
        o.p[k * 3] = ax; o.p[k * 3 + 1] = ay; o.p[k * 3 + 2] = az; o.a[k++] = al;
        o.p[k * 3] = bx; o.p[k * 3 + 1] = by; o.p[k * 3 + 2] = bz; o.a[k++] = al;
      }
      for (var i = 0; i < 4; i++) {
        var a = cs[i], b = cs[(i + 1) % 4];
        seg(a[0], -1, a[1], b[0], -1, b[1], 0.16);
        seg(a[0], FLOOR_Y + 0.6, a[1], b[0], FLOOR_Y + 0.6, b[1], 0.16);
        seg(a[0], -1, a[1], a[0], FLOOR_Y + 0.6, a[1], 0.12);
      }
      o.commit(k);
      buildGlass();
      glass.visible = WALLS;
      for (var s = 0; s < STREAKS; s++) streak[4 * s + 2] = streak[4 * s + 3] = 1;   /* respawn */
      trailLen = 0;
      resetView(false);
    }

    /* ---------------- per-frame packing ---------------- */
    var bodyScale = opts.bodyScale || function () { return 1; };
    /* per-instance swim height: -depth when the snapshot has depths (s.depth),
     * else keyed off the fish id as in the shallow tank */
    var heights = null;
    var SX = new Float64Array(6), SY = new Float64Array(6);
    /* Is this snapshot drawn in the fish's own bodies? (the module exports the
     * appearance genome, one row per fish, the kind could be built, and its
     * gene slots took the snapshot), in every colour mode; the skin is
     * appSkin's. Returns the slots' reconciliation (AppKind.reconcile: the
     * draw's buffers ready, each fish's slot in iGeneSlot), or null: the
     * plain fish are drawn */
    function appearanceDrawn(s) {
      if (!EA || !s.app || s.app.length < s.n * EA.STRIDE) return null;
      if (!appKind) {
        try { appKind = AppKind(); clarityUniforms(appKind.mat.uniforms); appStatus = "drawing"; }
        catch (e) { appStatus = "unavailable: " + (e && e.message || e); EA = null; console.warn("evo_boids: appearance renderer", e); return null; }
      }
      var r = appKind.reconcile(s, quality >= 3 ? "medium" : "coarse");
      if (!r.ok) {
        var why = "the plain fish (the gene slots refused the snapshot: " + r.error + ")";
        if (appStatus !== why) { appStatus = why; console.warn("evo_boids: " + why); }
        return null;
      }
      appStatus = "drawing";
      return r;
    }
    /* The swim pose's camera for this frame (swimPose's G; after updateVP),
     * and what the last frame's fish got: how many, how many with any of the
     * polish (weight > 0) and how many all of it (polishState) */
    var poseCam = { gate: true, zero: false, view: null, proj: null, focal: 1, near: 1, halfW: 0, halfH: 0, planes: new Float64Array(8) };
    var poseLast = { fish: 0, any: 0, full: 0, sum: 0 };
    /* the frustum's side planes in camera space (x or y, and the depth d):
     * right / left NDC x = P0 x / d - P8 = +-1, top / bottom with P5, P9 (the
     * view offset); unit normals, + outside (poseWeight) */
    function sidePlanes(Pm, F) {
      var q = [[Pm[0], -(1 + Pm[8])], [-Pm[0], Pm[8] - 1], [Pm[5], -(1 + Pm[9])], [-Pm[5], Pm[9] - 1]];
      for (var i = 0; i < 4; i++) { var l = Math.hypot(q[i][0], q[i][1]) || 1; F[2 * i] = q[i][0] / l; F[2 * i + 1] = q[i][1] / l; }
    }
    function poseCamera() {
      var Pm = camera.projectionMatrix.elements;
      poseCam.gate = polishWant !== "ungated"; poseCam.zero = polishWant === "zero";
      poseCam.view = camera.matrixWorldInverse.elements; poseCam.proj = Pm;
      poseCam.focal = 0.5 * ch * Math.abs(Pm[5]); poseCam.near = camera.near;
      poseCam.halfW = halfW; poseCam.halfH = halfH;
      sidePlanes(Pm, poseCam.planes);
      return poseCam;
    }
    function poseCount(p) { var q = p % 128; poseLast.sum += q / 127; if (q > 0) poseLast.any++; if (q >= 127) poseLast.full++; }
    /* a gate's frame start (polish on): a new world forgets the extent; are the
     * swim poses packed this frame? (held full programs need them; ungated, every
     * fish is lit; else mayLight) */
    function gateStart(g, s, G) {
      if (g.epoch !== s.worldEpoch) { g.epoch = s.worldEpoch; g.rMax = 0; }
      var may = mayLight(G, g);   /* (g.bound: the largest a fish can look, CSS px) */
      g.posing = g.hold > 0 || !G.gate || G.zero || may;
      return g.posing;
    }
    /* Each lit fish's swimming speed, for the paired fins' fold (posePack;
     * kept for the fish lit in the last frame, nothing while no pose is
     * packed; a fish lit anew starts at the cruising value below): its
     * head's travel since the last drawn frame over the simulated time between
     * them (ticks x SIM_DT), / 150 (the engine's default top speed), smoothed
     * over ~0.3 simulated seconds; matched to the last frame's fish by id with
     * a merge (both lists in the engine's order, ids rising: the engine keeps
     * its creatures in birth order; nothing allocated a frame), a fish not
     * matched (born, or a new world) starting at a cruising 0.55. Paused it
     * holds, so a still picture keeps its pose; a jump (a wrap, a Turbo run)
     * keeps the old value. A future reordering of the draw (LOD buckets) must
     * merge in the engine's order, before it. Display only: nothing here
     * reaches the simulation. */
    var SIM_DT = 0.016;   /* oc_step's fixed step (web/ocean.js DT) */
    function swimBufs(cap) { return { n: 0, epoch: -1, tick: 0, ids: new Float64Array(cap), x: new Float32Array(cap), y: new Float32Array(cap), v: new Float32Array(cap) }; }
    var swimA = swimBufs(2048), swimB = swimBufs(2048);
    /* rec: this snapshot's reconciliation (appearanceDrawn): the buffers are
     * sized, the genes in their slots; here the poses, colours and highlights */
    function fillApp(s, selIdx, hovIdx, rec) {
      var n = s.n, pose = polishNow();
      var at = appKind.attrs;
      var A = at.iA.array, B = at.iB.array, Cc = at.iC.array, BODY = at.iBody.array, X = at.iX.array, LIT = appKind.litIdx;
      var segs = s.segs, cols = s.colors, body = s.body, ids = s.ids, depth = s.depth, vz = s.vz;
      if (!heights || heights.length < n) heights = new Float32Array(Math.max(n, 2048));
      var xs = SX, ys = SY;
      var SP0 = swimA, SP1 = null, G = null, tick = 0, sj = 0, sk = 0, sa = 0, sinv = 0, sjump = 0, lit = 0;
      var gt = gateFish, posing = false, rMax = 0, cMax = 0, yMin = Infinity, yMax = -Infinity;
      if (pose) { G = poseCamera(); posing = gateStart(gt, s, G); warmUp(appKind.warm); }
      if (posing) {
        SP1 = swimB.ids.length >= n ? swimB : (swimB = swimBufs(Math.max(2048, 2 * n)));
        tick = s.stats ? s.stats[1] : 0;
        var dT = SP0.epoch === s.worldEpoch ? tick - SP0.tick : 0;
        if (SP0.epoch !== s.worldEpoch) SP0.n = 0;
        sa = dT > 0 && dT <= 30 ? 1 - Math.exp(-dT * SIM_DT / 0.3) : 0; sinv = sa > 0 ? 1 / (150 * dT * SIM_DT) : 0;
        sjump = (3.5 * dT + 5) * (3.5 * dT + 5);
      } else swimA.epoch = -1;   /* the history restarts when the poses come back */
      for (var c = 0; c < n; c++) {
        var b = 12 * c, px = segs[b], py = segs[b + 1], o = 4 * c;
        xs[0] = px; ys[0] = py;
        for (var k = 1; k < 6; k++) {
          var x = segs[b + 2 * k], y = segs[b + 2 * k + 1];
          if (!WALLS) {   /* the seam (glass walls have none) */
            if (x - px > halfW) x -= W; else if (px - x > halfW) x += W;
            if (y - py > halfH) y -= H; else if (py - y > halfH) y += H;
          }
          xs[k] = x; ys[k] = y; px = x; py = y;
        }
        A[o] = xs[0]; A[o + 1] = ys[0]; A[o + 2] = xs[1]; A[o + 3] = ys[1];
        B[o] = xs[2]; B[o + 1] = ys[2]; B[o + 2] = xs[3]; B[o + 3] = ys[3];
        Cc[o] = xs[4]; Cc[o + 1] = ys[4]; Cc[o + 2] = xs[5]; Cc[o + 3] = ys[5];
        var id = ids ? ids[c] : c;
        var hgt = depth ? -depth[c] : (hash01(id * 1.7 + 3.1) - 0.5) * 8;
        heights[c] = hgt;
        var size = body ? body[2 * c] : 1, elong = body ? body[2 * c + 1] : 1;
        BODY[o] = 4.6 * bodyScale(size);
        BODY[o + 1] = hgt;
        BODY[o + 2] = c === selIdx ? 1 : (c === hovIdx ? 0.5 : 0);
        BODY[o + 3] = 0;
        var t = vz ? vz[c] : 0;
        X[o] = t === t ? t : 0; X[o + 1] = hash01(id);
        X[o + 2] = 20 * size * elong / BODY[o];   /* lambda: body length / radius */
        X[o + 3] = cols ? cols[3 * c] * 65536 + cols[3 * c + 1] * 256 + cols[3 * c + 2] : 0;   /* the family / brain colour */
        if (pose) {   /* the fish's extent, for the next frame's mayLight */
          var cx = xs[0] - xs[5], cy = ys[0] - ys[5], cl = (cx < 0 ? -cx : cx) + (cy < 0 ? -cy : cy);
          if (cl > cMax) cMax = cl;
          if (BODY[o] > rMax) rMax = BODY[o];
          if (hgt < yMin) yMin = hgt;
          if (hgt > yMax) yMax = hgt;
        }
        if (posing) {
          var qw = 0;   /* the weight in 7 bits (poseQ, its size test inlined: posePx) */
          if (!G.gate) qw = G.zero ? 0 : 127;
          else if (!G.zero) {
            var cxw = 0.5 * (xs[0] + xs[5]) - G.halfW, czw = 0.5 * (ys[0] + ys[5]) - G.halfH, exw = xs[0] - xs[5], eyw = ys[0] - ys[5], GV = G.view;
            var dnw = -(GV[2] * cxw + GV[6] * hgt + GV[10] * czw + GV[14]) - 0.5 * Math.sqrt(exw * exw + eyw * eyw) - 2 * BODY[o];
            var pxw = BODY[o] * G.focal / (dnw > G.near ? dnw : G.near);
            if (pxw > 6) qw = poseVisibleQ(xs, ys, BODY[o], hgt, G, X[o], X[o + 2], REACH_APP, pxw);
          }
          if (qw > 0) {
            /* the swimming speed (above): this fish in the last frame's list of lit fish */
            var sv = 0.55, hx = segs[b], hy = segs[b + 1];
            while (sj < SP0.n && SP0.ids[sj] < id) sj++;
            if (sj < SP0.n && SP0.ids[sj] === id) {
              sv = SP0.v[sj];
              var ex = hx - SP0.x[sj], ey = hy - SP0.y[sj], e2 = ex * ex + ey * ey;
              if (sa > 0 && e2 < sjump) sv += (Math.min(1.5, Math.sqrt(e2) * sinv) - sv) * sa;
              sj++;
            }
            SP1.ids[sk] = id; SP1.x[sk] = hx; SP1.y[sk] = hy; SP1.v[sk] = sv; sk++;
            poseCount(BODY[o + 3] = posePack(xs, ys, sv, qw));
            LIT[lit++] = c;   /* (the split's lit draw, commit) */
          } else BODY[o + 3] = POSE0;
        }
      }
      if (posing) { SP1.n = sk; SP1.epoch = s.worldEpoch; SP1.tick = tick; swimA = SP1; swimB = SP0; }
      if (pose) { gt.rMax = rMax; gt.cMax = cMax; gt.yMin = yMin; gt.yMax = yMax; }
      /* (the genes are in their slots already: reconcile copied the new fish's, and only theirs) */
      var tanHalf = Math.tan(camera.fov * Math.PI / 360);
      appKind.mat.uniforms.uPxPerUnit.value = ch / (2 * tanHalf);
      appKind.mat.uniforms.uColourBy.value = appSkin ? 0 : 1;
      appKind.commit(n, rec.hasBarbels, settle(gt, pose, lit, appKind.warm.ready), rec.changed, lit);
      if (profiler.active) {
        var tp = appKind.tpls[appKind.lod], ST = EA.STRIDE;
        profiler.count(PK.lod, appKind.lod === "medium" ? 2 : 1); profiler.count(PK.bodyInst, n);
        profiler.count(PK.shadowInst, appKind.shadow.visible ? n : 0); profiler.count(PK.barbelInst, appKind.bmesh && appKind.bmesh.visible ? n : 0);
        profiler.count(PK.tplVerts, tp.verts); profiler.count(PK.tplTris, tp.idx.length / 3);
        profiler.count(PK.geneSrcBytes, rec.newRows * ST * 4); profiler.count(PK.genePadBytes, rec.newRows * (64 - ST) * 4);
        profiler.count(PK.litInst, appKind.lit.n);
      }
    }
    var appDrawn = false;   /* this frame drew the appearance fish (the probes need it) */
    function fillFish(s, selIdx, hovIdx) {
      poseLast.fish = s.n; poseLast.any = poseLast.full = poseLast.sum = 0;   /* poseCount, this frame */
      var rec = appearanceDrawn(s);
      appDrawn = !!rec;
      if (appDrawn) {
        fillApp(s, selIdx, hovIdx, rec);
        fish.commit(0);
        return;
      }
      if (appKind) appKind.hide();
      var n = s.n, pose = polishNow(), G = null, gt = gateFish, posing = false, lit = 0, rMax = 0, cMax = 0, yMin = Infinity, yMax = -Infinity;
      if (pose) { G = poseCamera(); posing = gateStart(gt, s, G); warmUp(warmFish); }
      fish.ensure(n);
      var A = fish.attrs.iA.array, B = fish.attrs.iB.array, Cc = fish.attrs.iC.array;
      var COL = fish.attrs.iCol.array, BODY = fish.attrs.iBody.array, X = fish.attrs.iX.array;
      var segs = s.segs, cols = s.colors, body = s.body, ids = s.ids, depth = s.depth, vz = s.vz;
      if (!heights || heights.length < n) heights = new Float32Array(Math.max(n, 2048));
      var xs = SX, ys = SY;
      for (var c = 0; c < n; c++) {
        var b = 12 * c, px = segs[b], py = segs[b + 1];
        var o = 4 * c;
        /* unwrap a body that straddles the world's seam (glass walls have none) */
        xs[0] = px; ys[0] = py;
        for (var k = 1; k < 6; k++) {
          var x = segs[b + 2 * k], y = segs[b + 2 * k + 1];
          if (!WALLS) {
            if (x - px > halfW) x -= W; else if (px - x > halfW) x += W;
            if (y - py > halfH) y -= H; else if (py - y > halfH) y += H;
          }
          xs[k] = x; ys[k] = y; px = x; py = y;
        }
        A[o] = xs[0]; A[o + 1] = ys[0]; A[o + 2] = xs[1]; A[o + 3] = ys[1];
        B[o] = xs[2]; B[o + 1] = ys[2]; B[o + 2] = xs[3]; B[o + 3] = ys[3];
        Cc[o] = xs[4]; Cc[o + 1] = ys[4]; Cc[o + 2] = xs[5]; Cc[o + 3] = ys[5];
        var id = ids ? ids[c] : c;
        COL[o] = cols[3 * c] / 255; COL[o + 1] = cols[3 * c + 1] / 255; COL[o + 2] = cols[3 * c + 2] / 255;
        COL[o + 3] = hash01(id);
        var hgt = depth ? -depth[c] : (hash01(id * 1.7 + 3.1) - 0.5) * 8;
        heights[c] = hgt;
        BODY[o] = 4.6 * bodyScale(body ? body[2 * c] : 1);
        BODY[o + 1] = hgt;
        BODY[o + 2] = c === selIdx ? 1 : (c === hovIdx ? 0.5 : 0);
        BODY[o + 3] = 0;
        /* s.vz: + = sinking, as tan(pitch); absent (or NaN) = level */
        var t = vz ? vz[c] : 0;
        X[o] = t === t ? t : 0; X[o + 1] = 0; X[o + 2] = 0; X[o + 3] = 0;
        if (pose) {   /* the fish's extent, for the next frame's mayLight */
          var cx = xs[0] - xs[5], cy = ys[0] - ys[5], cl = (cx < 0 ? -cx : cx) + (cy < 0 ? -cy : cy);
          if (cl > cMax) cMax = cl;
          if (BODY[o] > rMax) rMax = BODY[o];
          if (hgt < yMin) yMin = hgt;
          if (hgt > yMax) yMax = hgt;
        }
        if (posing) {
          var qw = 0;   /* the weight in 7 bits (poseQ, its size test inlined: posePx) */
          if (!G.gate) qw = G.zero ? 0 : 127;
          else if (!G.zero) {
            var cxw = 0.5 * (xs[0] + xs[5]) - G.halfW, czw = 0.5 * (ys[0] + ys[5]) - G.halfH, exw = xs[0] - xs[5], eyw = ys[0] - ys[5], GV = G.view;
            var dnw = -(GV[2] * cxw + GV[6] * hgt + GV[10] * czw + GV[14]) - 0.5 * Math.sqrt(exw * exw + eyw * eyw) - 2 * BODY[o];
            var pxw = BODY[o] * G.focal / (dnw > G.near ? dnw : G.near);
            if (pxw > 6) qw = poseVisibleQ(xs, ys, BODY[o], hgt, G, X[o], 1, fish.reach, pxw);
          }
          if (qw > 0) { poseCount(X[o + 1] = posePack(xs, ys, 0, qw)); lit++; }   /* no paired fins to fold */
          else X[o + 1] = POSE0;
        }
      }
      if (pose) { gt.rMax = rMax; gt.cMax = cMax; gt.yMin = yMin; gt.yMax = yMax; }
      fish.commit(n, settle(gt, pose, lit, warmFish.ready));
      if (profiler.active) {
        profiler.count(PK.lod, 0); profiler.count(PK.bodyInst, n); profiler.count(PK.barbelInst, 0);
        profiler.count(PK.shadowInst, fish.shadow.visible ? n : 0);
        profiler.count(PK.tplVerts, fish.verts); profiler.count(PK.tplTris, fish.tris);
        profiler.count(PK.instBytes, fish.bytes);
      }
    }

    /* Predators carry only a position: a short history of where each one has
     * been becomes its spine, so it bends through its turns like the fish. */
    var predTrails = [];
    function fillPreds(s) {
      var n = s.pc, pose = polishNow() && n > 0, predLit = 0, G = null;
      if (pose) { G = poseCamera(); warmUp(warmFish); }
      preds.ensure(n);
      var A = preds.attrs.iA.array, B = preds.attrs.iB.array, Cc = preds.attrs.iC.array;
      var COL = preds.attrs.iCol.array, BODY = preds.attrs.iBody.array, X = preds.attrs.iX.array;
      predTrails.length = Math.min(predTrails.length, n);
      var SP = 7;
      for (var i = 0; i < n; i++) {
        var x = s.preds[3 * i], y = s.preds[3 * i + 1], hunting = !(s.preds[3 * i + 2] > 0);
        var pdep = s.predDepth ? s.predDepth[i] : 0;
        var tr = predTrails[i];
        if (!tr || Math.hypot(tr[0] - x, tr[1] - y) > 60) { tr = predTrails[i] = [x, y, x - 1, y]; tr.d = pdep; tr.vz = 0; }
        else {
          var mv = Math.hypot(tr[0] - x, tr[1] - y);
          if (mv > 1.2) {
            /* its pitch, as for the fish: depth change over distance swum, smoothed */
            var inst = Math.max(-1.2, Math.min(1.2, (pdep - tr.d) / mv));
            tr.vz += (inst - tr.vz) * 0.25; tr.d = pdep;
            tr.unshift(x, y);
            if (tr.length > 40) tr.length = 40;
          }
        }
        X[4 * i] = tr.vz; X[4 * i + 1] = X[4 * i + 2] = X[4 * i + 3] = 0;
        /* points every SP px along the history; straight on past its end */
        var pts = [x, y], acc = 0, want = SP, j = 0;
        var lx = x, ly = y;
        while (pts.length < 12 && j + 3 < tr.length) {
          var ax = tr[j], ay = tr[j + 1], bx = tr[j + 2], by = tr[j + 3];
          var d = Math.hypot(bx - ax, by - ay);
          if (acc + d >= want && d > 0) {
            var f = (want - acc) / d;
            lx = ax + (bx - ax) * f; ly = ay + (by - ay) * f;
            pts.push(lx, ly);
            want += SP;
          } else { acc += d; j += 2; }
        }
        var dx = tr.length >= 4 ? tr[0] - tr[2] : 1, dy = tr.length >= 4 ? tr[1] - tr[3] : 0;
        var dl = Math.hypot(dx, dy) || 1;
        if (pts.length >= 4) { dx = pts[pts.length - 4] - pts[pts.length - 2]; dy = pts[pts.length - 3] - pts[pts.length - 1]; dl = Math.hypot(dx, dy) || 1; }
        while (pts.length < 12) {
          lx = pts[pts.length - 2] - dx / dl * SP; ly = pts[pts.length - 1] - dy / dl * SP;
          pts.push(lx, ly);
        }
        var o = 4 * i;
        A[o] = pts[0]; A[o + 1] = pts[1]; A[o + 2] = pts[2]; A[o + 3] = pts[3];
        B[o] = pts[4]; B[o + 1] = pts[5]; B[o + 2] = pts[6]; B[o + 3] = pts[7];
        Cc[o] = pts[8]; Cc[o + 1] = pts[9]; Cc[o + 2] = pts[10]; Cc[o + 3] = pts[11];
        COL[o] = C.predator[0]; COL[o + 1] = C.predator[1]; COL[o + 2] = C.predator[2]; COL[o + 3] = hash01(i + 0.5);
        var py = s.predDepth ? -s.predDepth[i] : 3;
        BODY[o] = hunting ? 7.2 : 8.2;   /* a fed predator looks fuller */
        BODY[o + 1] = py;
        BODY[o + 2] = 0;
        BODY[o + 3] = hunting ? 1 : 0;
        if (pose) {   /* every predator's weight (a few: no frame test) */
          for (var q = 0; q < 6; q++) { SX[q] = pts[2 * q]; SY[q] = pts[2 * q + 1]; }
          X[o + 1] = swimPose(SX, SY, BODY[o], py, 0, G, tr.vz, 1, preds.reach);
          if (X[o + 1] % 128) predLit++;
        }
        if (i < GLOW_MAX) {
          var gp = glowGeo.attributes.position.array, ga = glowGeo.attributes.amt.array;
          gp[3 * i] = x - halfW; gp[3 * i + 1] = py - 2; gp[3 * i + 2] = y - halfH;
          ga[i] = hunting ? 1 : 0.35;
        }
      }
      gatePred.posing = pose;
      preds.commit(n, settle(gatePred, pose, predLit, warmFish.ready));
      glowGeo.setDrawRange(0, Math.min(n, GLOW_MAX));
      glowGeo.attributes.position.needsUpdate = true;
      glowGeo.attributes.amt.needsUpdate = true;
    }

    function fillFood(s) {
      var n = s.fc;
      ensureFood(n);
      var p = foodGeo.attributes.position.array, sd = foodGeo.attributes.seed.array, fd = s.foodDepth;
      for (var i = 0; i < n; i++) {
        var x = s.food[2 * i], y = s.food[2 * i + 1];
        p[3 * i] = x - halfW; p[3 * i + 1] = fd ? -fd[i] : -3; p[3 * i + 2] = y - halfH;
        sd[i] = hash01(Math.floor(x / 9) * 131 + Math.floor(y / 9));
      }
      foodGeo.setDrawRange(0, n);
      foodGeo.attributes.position.clearUpdateRanges();
      foodGeo.attributes.position.addUpdateRange(0, n * 3);
      foodGeo.attributes.position.needsUpdate = true;
      foodGeo.attributes.seed.clearUpdateRanges();
      foodGeo.attributes.seed.addUpdateRange(0, n);
      foodGeo.attributes.seed.needsUpdate = true;
    }

    /* currents: streaks advected through the flow grid */
    function sampleCurrent(s, x, y, out) {
      var gx = (x - 32) / 64, gy = (y - 32) / 64;
      var i0 = Math.max(0, Math.min(s.curCols - 1, Math.floor(gx))), j0 = Math.max(0, Math.min(s.curRows - 1, Math.floor(gy)));
      var i1 = Math.min(s.curCols - 1, i0 + 1), j1 = Math.min(s.curRows - 1, j0 + 1);
      var fx = Math.max(0, Math.min(1, gx - i0)), fy = Math.max(0, Math.min(1, gy - j0));
      var g = s.curGrid, q00 = (j0 * s.curCols + i0) * 2, q10 = (j0 * s.curCols + i1) * 2;
      var q01 = (j1 * s.curCols + i0) * 2, q11 = (j1 * s.curCols + i1) * 2;
      for (var c = 0; c < 2; c++) {
        var a = g[q00 + c] + (g[q10 + c] - g[q00 + c]) * fx;
        var b = g[q01 + c] + (g[q11 + c] - g[q01 + c]) * fx;
        out[c] = a + (b - a) * fy;
      }
    }
    var vel = [0, 0];
    function fillCurrents(s, dtSim) {
      if (!s.curActive || !s.curGrid) { currents.commit(0); return; }
      var k = 0, P = currents.p, Aa = currents.a;
      for (var i = 0; i < STREAKS; i++) {
        var o = 4 * i;
        if (streak[o + 2] >= streak[o + 3]) {
          streak[o] = vrand() * W; streak[o + 1] = vrand() * H;
          streak[o + 2] = 0; streak[o + 3] = 1.5 + vrand() * 3;
        }
        sampleCurrent(s, streak[o], streak[o + 1], vel);
        if (dtSim > 0) {
          streak[o] += vel[0] * dtSim; streak[o + 1] += vel[1] * dtSim;
          streak[o + 2] += dtSim;
          if (streak[o] < 0 || streak[o] > W || streak[o + 1] < 0 || streak[o + 1] > H) streak[o + 2] = streak[o + 3];
        }
        var sp = Math.hypot(vel[0], vel[1]);
        if (sp < 2) continue;
        var life = streak[o + 2] / streak[o + 3];
        var a = Math.sin(Math.PI * Math.min(1, life)) * Math.min(1, sp / 70) * 0.85;
        var x = streak[o] - halfW, z = streak[o + 1] - halfH;
        P[3 * k] = x; P[3 * k + 1] = 6; P[3 * k + 2] = z; Aa[k++] = a;
        P[3 * k] = x - vel[0] * 0.28; P[3 * k + 1] = 6; P[3 * k + 2] = z - vel[1] * 0.28; Aa[k++] = 0;
      }
      currents.commit(k);
    }

    /* the selected fish's recent path */
    var trailLen = 0, trailId = null, TRAIL_MAX = 240;
    var trailPts = new Float32Array(TRAIL_MAX * 3);
    function fillTrail(s, selIdx, stepped) {
      var id = selIdx >= 0 && s.ids ? s.ids[selIdx] : null;
      if (id === null) { trailLen = 0; trailId = null; trail.commit(0); selRing.visible = false; return; }
      if (id !== trailId) { trailLen = 0; trailId = id; }
      var x = s.segs[12 * selIdx] - halfW, z = s.segs[12 * selIdx + 1] - halfH, y = fishY(s, selIdx);
      if (trailLen > 0) {
        var lx = trailPts[0], lz = trailPts[2];
        if (!WALLS && (Math.abs(x - lx) > halfW || Math.abs(z - lz) > halfH)) trailLen = 0;   /* wrapped: start over */
      }
      if (stepped && (trailLen === 0 || Math.hypot(x - trailPts[0], y - trailPts[1], z - trailPts[2]) > 3)) {
        trailPts.copyWithin(3, 0, (TRAIL_MAX - 1) * 3);
        trailPts[0] = x; trailPts[1] = y; trailPts[2] = z;
        trailLen = Math.min(TRAIL_MAX, trailLen + 1);
      }
      var P = trail.p, Aa = trail.a, k = 0;
      for (var i = 0; i + 1 < trailLen; i++) {
        var f = 1 - i / TRAIL_MAX;
        P[3 * k] = trailPts[3 * i]; P[3 * k + 1] = trailPts[3 * i + 1]; P[3 * k + 2] = trailPts[3 * i + 2]; Aa[k++] = 0.55 * f * f;
        P[3 * k] = trailPts[3 * i + 3]; P[3 * k + 1] = trailPts[3 * i + 4]; P[3 * k + 2] = trailPts[3 * i + 5]; Aa[k++] = 0.55 * f * f;
      }
      trail.commit(k);
      selRing.visible = true;
      selRing.position.set(x, y - 1.5, z);
      selRing.scale.set(44, 44, 1);
    }

    /* ---------------- picking ---------------- */
    var vpm = new Float32Array(16);
    function updateVP() {
      camera.updateMatrixWorld();
      var a = camera.projectionMatrix.elements, b = camera.matrixWorldInverse.elements;
      for (var i = 0; i < 4; i++) for (var j = 0; j < 4; j++) {
        vpm[j * 4 + i] = a[i] * b[j * 4] + a[4 + i] * b[j * 4 + 1] + a[8 + i] * b[j * 4 + 2] + a[12 + i] * b[j * 4 + 3];
      }
    }
    function toScreen(x, y, z, out) {
      var m = vpm;
      var cx = m[0] * x + m[4] * y + m[8] * z + m[12];
      var cy = m[1] * x + m[5] * y + m[9] * z + m[13];
      var cwv = m[3] * x + m[7] * y + m[11] * z + m[15];
      if (cwv <= 0) return false;
      out[0] = (cx / cwv * 0.5 + 0.5) * cw;
      out[1] = (0.5 - cy / cwv * 0.5) * ch;
      return true;
    }
    var scr = [0, 0];
    /* a fish's swim height (three Y): from this snapshot's depths when it has
     * them, so picking and the rings never lag a frame behind fillFish */
    function fishY(s, i) {
      if (s.depth) return -s.depth[i];
      return heights && i < heights.length ? heights[i] : 0;
    }
    /* index of the fish whose head is nearest a canvas point (CSS px), or -1 */
    function pickAt(s, px, py, reach) {
      if (!s || !s.n) return -1;
      var best = -1, bestD2 = reach * reach;
      for (var i = 0; i < s.n; i++) {
        if (!toScreen(s.segs[12 * i] - halfW, fishY(s, i), s.segs[12 * i + 1] - halfH, scr)) continue;
        var dx = scr[0] - px, dy = scr[1] - py, d2 = dx * dx + dy * dy;
        if (d2 <= bestD2) { bestD2 = d2; best = i; }
      }
      return best;
    }

    var hoverPt = null, hoverIdx = -1, lastS = null, lastT = 0;
    canvas.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse") { hoverPt = null; return; }
      var r = canvas.getBoundingClientRect();
      hoverPt = [e.clientX - r.left, e.clientY - r.top];
    });
    canvas.addEventListener("pointerleave", function () { hoverPt = null; });

    function render(s, info) {
      if (lost) { profiler.count(PK.lost, 1); if (probes.length) failProbes("the WebGL context is lost"); return; }
      var pt = profiler.beginCpu();
      var now = performance.now();
      var dt = lastT ? Math.min(0.1, (now - lastT) / 1000) : 0.016;
      lastT = now;
      lastS = s;
      common.uTime.value = info.animT;
      stepAnim(dt);
      var sel = info.selIdx;
      if (follow) {
        if (sel < 0) { follow = false; setFollowControls(false); onFollow(false); }
        else {
          /* the target follows the fish's depth too */
          var tx = s.segs[12 * sel] - halfW, tz = s.segs[12 * sel + 1] - halfH, ty = fishY(s, sel);
          var t = controls.target, jump = !WALLS && (Math.abs(tx - t.x) > halfW || Math.abs(tz - t.z) > halfH);   /* a wrap */
          var kk = jump ? 1 : 1 - Math.exp(-dt * 5);
          var dx = (tx - t.x) * kk, dz = (tz - t.z) * kk, dy = (ty - t.y) * (1 - Math.exp(-dt * 5));
          t.x += dx; t.z += dz; t.y += dy;
          camera.position.x += dx; camera.position.z += dz; camera.position.y += dy;
          /* ease in to a close-up on the first frames of a follow */
          var off = camera.position.clone().sub(t), dist = off.length(), want = Math.min(fitDist * 0.32, 420);
          if (dist > want * 1.02 && followDive) camera.position.copy(t).addScaledVector(off, (dist + (want - dist) * (1 - Math.exp(-dt * 3))) / dist);
          else followDive = false;
        }
      }
      stepFly(dt);   /* the held W A S D / Q E keys */
      controls.update(dt);
      clampView();   /* after follow, damping and animation alike */
      /* near/far follow the zoom, so a close-up keeps its depth precision and
       * a far view never clips the tank */
      var cd = camera.position.distanceTo(controls.target);
      var nearW = Math.max(1, cd * 0.02), farW = cd * 4 + (Math.max(W, H) + TD) * 4;   /* the depth too */
      if (Math.abs(camera.near - nearW) > nearW * 0.2 || Math.abs(camera.far - farW) > farW * 0.2) {
        camera.near = nearW; camera.far = farW;
        camera.updateProjectionMatrix();
      }
      updateVP();
      hoverIdx = hoverPt ? pickAt(s, hoverPt[0], hoverPt[1], 16) : -1;
      if (hoverIdx === sel) hoverIdx = -1;
      canvas.style.cursor = hoverIdx >= 0 ? "pointer" : "";
      pt = profiler.lap(SP.cameraPick, pt);
      fillFish(s, sel, hoverIdx);
      pt = profiler.lap(SP.fishPack, pt);
      fillPreds(s);
      fillFood(s);
      fillCurrents(s, info.dtSim);
      fillTrail(s, sel, info.dtSim > 0);
      if (hoverIdx >= 0) {
        hoverRing.visible = true;
        hoverRing.position.set(s.segs[12 * hoverIdx] - halfW, fishY(s, hoverIdx) - 1.5, s.segs[12 * hoverIdx + 1] - halfH);
        hoverRing.scale.set(34, 34, 1);
      } else hoverRing.visible = false;
      snow.visible = quality >= 3 && !reduced;
      if (causticFade < 1 && causticReady) {
        causticFade = Math.min(1, causticFade + dt / 1.4);
        floorMat.uniforms.uCausticAmt.value = causticAmt();   /* strong enough to read on the sand */
        floorMat.uniforms.uCausticTrue.value = causticTrue();
      }
      aimBeam(s, sel, dt);
      profiler.lap(SP.otherPack, pt);
      var submitT = profiler.beginCpu(), ok = false;
      profiler.beginSubmission();
      try {
        renderer.render(scene, camera);
        ok = true;
      } finally {
        profiler.endSubmission(ok);   /* a query left open by a throw is closed and invalidated */
        profiler.endCpu(SP.submit, submitT);
      }
      if (profiler.active) {
        var ri = renderer.info.render;
        profiler.count(PK.calls, ri.calls); profiler.count(PK.triangles, ri.triangles);
        profiler.count(PK.points, ri.points); profiler.count(PK.lines, ri.lines);
      }
      if (probes.length) runProbes(s);
    }
    var followDive = false;

    /* The flashlight (viewer only; BEAM_FN). On, a cone of clear light from
     * the camera: at the followed fish while following (a circle about 70
     * units across it, more from far away), else at the point the camera
     * looks at (the orbit centre; a ~11 degree cone). It reaches past its
     * target by the tank's depth, so the sand behind a fish near the floor
     * lights up too. Fades in and out over ~0.3 s. */
    var beamWant = false, beamAmt = 0;
    var beamTgt = new THREE.Vector3(), beamDir = new THREE.Vector3();
    function aimBeam(s, sel, dt) {
      var goal = beamWant ? 1 : 0;
      beamAmt = reduced ? goal : beamAmt + (goal - beamAmt) * (1 - Math.exp(-dt * 10));
      if (Math.abs(beamAmt - goal) < 0.002) beamAmt = goal;
      common.uBeamOn.value = beamAmt;
      if (beamAmt <= 0) return;
      var onFish = follow && sel >= 0 && s && sel < s.n;
      if (onFish) beamTgt.set(s.segs[12 * sel] - halfW, fishY(s, sel), s.segs[12 * sel + 1] - halfH);
      else beamTgt.copy(controls.target);
      beamDir.copy(beamTgt).sub(camera.position);
      var dist = beamDir.length();
      if (!(dist > 1e-3)) return;
      beamDir.multiplyScalar(1 / dist);
      common.uBeamDir.value.copy(beamDir);
      common.uBeamTan.value = Math.max(70, dist * (onFish ? 0.12 : 0.2)) / dist;
      common.uBeamReach.value = dist + TD * 1.2;
    }
    /* The caustic pattern costs ~40 ms of JS on a laptop (more on a phone), so
     * it is built after the first frames, in idle time, and the light fades in. */
    var causticReady = false, causticFade = 0;
    function causticAmt() { return 0.5 * causticK * (1 - Math.pow(1 - causticFade, 3)); }   /* causticK: the water's clarity */
    function causticTrue() { return 0.5 * (1 - Math.pow(1 - causticFade, 3)); }   /* in the flashlight: realistic, in any water; the same fade */
    (window.requestIdleCallback || function (f) { return setTimeout(f, 300); })(function () {
      floorMat.uniforms.uCaustic.value.dispose();
      floorMat.uniforms.uCaustic.value = causticTexture(256);
      causticReady = true;
    }, { timeout: 1200 });

    /* The probes (web/ocean_scene_parity.js attach, which says what each
     * checks): appearanceParity, appearanceTextureParity and its queue (probes:
     * runProbes right after a production draw, render; failProbes when there
     * is none), testFaults (holdGeneUploads: the gene upload above). They read
     * this renderer and what it drew through these live getters, never copies,
     * and upload nothing */
    var parity = PARITY.attach({
      THREE: THREE, renderer: renderer, profiler: profiler, geneIO: geneIO, bodyScale: bodyScale,
      ea: function () { return EA; }, status: function () { return appStatus; },
      appKind: function () { return appKind; }, drawn: function () { return appDrawn; }
    });
    var testFaults = parity.testFaults, probes = parity.probes, failProbes = parity.failProbes, runProbes = parity.runProbes;
    var appearanceParity = parity.appearanceParity, appearanceTextureParity = parity.appearanceTextureParity;
    function contextInfo() {
      var gl = renderer.getContext(), d = gl.getExtension("WEBGL_debug_renderer_info");
      return { version: gl.getParameter(gl.VERSION), glsl: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
               vendor: d ? gl.getParameter(d.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
               renderer: d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
               attributes: gl.getContextAttributes(), extensions: gl.getSupportedExtensions(),
               drawingBuffer: [gl.drawingBufferWidth, gl.drawingBufferHeight], pixelRatio: renderer.getPixelRatio(),
               maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE), lost: gl.isContextLost(),
               timerQuery: !!gl.getExtension("EXT_disjoint_timer_query_webgl2") };
    }

    function setQuality(q) {
      q = Math.max(1, Math.min(3, q | 0));
      if (q === quality) return false;
      quality = q;
      resize();
      return true;
    }
    /* the swim polish: drawn from detail 2 up (the lowest detail, where Hold
     * 60 fps ends up on a slow device, draws the fish as before it, at its
     * old cost); setPolish only for measurements. polishState: what the last
     * frame drew (variant: its fish's programs, plain or full; hold: frames
     * the full ones are kept after the last lit fish; posing: the swim poses
     * were packed; bound: the largest any fish could look, CSS px (mayLight);
     * ready: the polished programs are compiled (warmUp)) and what its fish got */
    function setPolish(on) { polishWant = on === "ungated" || on === "zero" ? on : (on === false || on === "off" ? "off" : "on"); }
    var VARIANT = ["plain", "full"];
    /* split: the appearance fish's lit ones drawn apart on the full programs
     * (litDrawn of them), the rest on the plain ones (AppKind's split) */
    function polishState() {
      var k = appKind && appDrawn ? appKind : fish;
      return { want: polishWant, on: polishNow(), gated: polishWant !== "ungated", quality: quality,
               variant: VARIANT[k.variant()], split: k === appKind && appKind.lit.on, litDrawn: k === appKind ? appKind.lit.n : 0, splitEnabled: litSplit,
               hold: gateFish.hold, posing: gateFish.posing, bound: gateFish.bound,
               ready: (k === fish ? warmFish : appKind.warm).ready,
               fish: poseLast.fish, any: poseLast.any, full: poseLast.full, meanWeight: poseLast.fish ? poseLast.sum / poseLast.fish : 0,
               preds: { n: preds.n, variant: VARIANT[preds.variant()], lit: gatePred.lit, hold: gatePred.hold },
               focalCss: poseCam.focal, canvasCss: [cw, ch] };
    }

    /* The water's clarity, 0 (realistic: the water exactly as the preview
     * drew it) .. 1 (clear; the default), drawing only (CLARITY). Live: it
     * sets uniforms and the snow's draw range, no shader is rebuilt. The
     * flashlight's clear light, the fish card's swatch and the genes never
     * see it. */
    var clarity = 1, fogK = 1, causticK = 1;
    function setClarity(u) {
      u = +u;
      u = u >= 0 ? Math.min(1, u) : (u < 0 ? 0 : 1);   /* NaN: clear */
      clarity = u;
      function mix(k) { var a = CLARITY[k][0], b = CLARITY[k][1]; return a + (b - a) * u; }
      function mixA(k) { var a = CLARITY[k][0], b = CLARITY[k][1]; return a.map(function (x, i) { return x + (b[i] - x) * u; }); }
      var t = mixA("deepTint"), d = mixA("deepAdd"), lo = mixA("ambLo"), hi = mixA("ambHi");
      var vv = mixA("vivid"), f = mixA("fog"), w = mixA("water"), sn = mixA("snow");
      clarityU.uDeepTint.value.set(t[0], t[1], t[2]);
      clarityU.uDeepDim.value = mix("deepDim");
      clarityU.uDeepAdd.value.set(d[0], d[1], d[2]);
      clarityU.uLKeep.value = mix("lKeep");
      clarityU.uFloorMin.value = mix("floorMin");
      clarityU.uBack.value = mix("back");
      clarityU.uAmbLo.value.set(lo[0], lo[1], lo[2]);
      clarityU.uAmbHi.value.set(hi[0], hi[1], hi[2]);
      clarityU.uVivid.value.set(vv[0], vv[1], vv[2]);
      common.uFog.value.set(f[0], f[1], f[2]);
      renderer.setClearColor(new THREE.Color().setRGB(f[0], f[1], f[2], "srgb"), 1);   /* the water above the tank */
      fogK = mix("fogK");
      common.uFogDensity.value = 0.42 / fitDist * fogK;
      floorMat.uniforms.uWater.value.set(w[0], w[1], w[2]);
      snowMat.uniforms.uCol.value.set(C.snow[0] * sn[0], C.snow[1] * sn[0], C.snow[2] * sn[0]);
      snowGeo.setDrawRange(0, Math.round(SNOW * sn[1]));
      shadowMat.uniforms.uAlpha.value = mix("shadow");   /* shared with the appearance fish's shadows */
      foodMat.uniforms.uFoodShade.value = mix("foodShade");
      foodMat.uniforms.uFoodGain.value = mix("foodGain");
      causticK = mix("causticK");
      if (causticReady) floorMat.uniforms.uCausticAmt.value = causticAmt();
    }
    clarityUniforms(fishMat.uniforms);
    clarityUniforms(foodMat.uniforms);
    foodMat.uniforms.uFoodShade = { value: 1 };
    foodMat.uniforms.uFoodGain = { value: 1 };
    setClarity(1);

    resize();
    setWorld(W, H);

    /* the engine's light field {on, L0, k} (oc_light_*): with on, the fish /
     * food depth shading follows L(d) = L0·exp(−k·d); off = the preview's */
    function setLight(l) {
      var on = !!(l && l.on);
      common.uLightOn.value = on ? 1 : 0;
      common.uL0.value = on && isFinite(l.L0) ? +l.L0 : 1;
      common.uKWater.value = on && isFinite(l.k) ? +l.k : 0;
    }

    return {
      renderer: "three.js (WebGL2)",
      setWorld: setWorld,
      walls: function () { return WALLS; },   /* the sides drawn as glass (setWorld's walls) */
      setLight: setLight,
      light: function () { return { on: common.uLightOn.value > 0.5, L0: common.uL0.value, k: common.uKWater.value }; },
      resize: resize,
      render: render,
      resetView: function (animated) { resetView(animated); },
      setInsets: function (ins) {
        var changed = ["top", "right", "bottom", "left"].some(function (k) { return (ins[k] || 0) !== insets[k]; });
        if (!changed) return;
        insets = { top: ins.top || 0, right: ins.right || 0, bottom: ins.bottom || 0, left: ins.left || 0 };
        applyViewOffset();
        if (!userMoved && !follow) resetView(true);
      },
      /* index of the fish nearest a viewport point (client px), or -1 */
      pick: function (s, clientX, clientY, reach) {
        var r = canvas.getBoundingClientRect();
        updateVP();
        return pickAt(s || lastS, clientX - r.left, clientY - r.top, reach);
      },
      /* client px of a fish's head, or null when it is behind the camera */
      project: function (s, idx) {
        if (!s || idx < 0 || idx >= s.n) return null;
        var r = canvas.getBoundingClientRect();
        if (!toScreen(s.segs[12 * idx] - halfW, fishY(s, idx), s.segs[12 * idx + 1] - halfH, scr)) return null;
        return { x: r.left + scr[0], y: r.top + scr[1] };
      },
      setFollow: function (on) {
        on = !!on;
        if (on === follow) return;
        follow = on;
        followDive = on;
        anim = null;
        userMoved = true;
        setFollowControls(on);
        onFollow(on);
      },
      following: function () { return follow; },
      depth: function () { return TD; },
      /* the view up (+) or down (-) by dy sim units, kept between just above
       * the floor and a bit above the surface; stops a follow */
      moveView: moveView,
      /* the held movement keys (stepFly): f forward / back, r right / left,
       * u up / down, each -1..1; boost (Shift) 2.5x. Free camera: fly; while
       * following: dolly (f), circle (r) and raise / lower (u) around the fish */
      setMove: function (f, r, u, boost) {
        function ax(v) { v = +v || 0; return v > 1 ? 1 : v < -1 ? -1 : v; }
        moveIn.f = ax(f); moveIn.r = ax(r); moveIn.u = ax(u); moveIn.boost = !!boost;
      },
      /* the flight's state, for the tests: speeds now (free: units / s;
       * following: rad / s, rad / s, 1 / s) */
      motion: function () {
        return { vel: flyVel.toArray(), orbit: { az: orbitVel.az, pol: orbitVel.pol, dolly: orbitVel.dolly },
                 dist: camera.position.distanceTo(controls.target), fitDist: fitDist };
      },
      /* put the camera at pos looking at target (three coords, [x, y, z]) */
      lookFrom: function (pos, target) {
        if (follow) { follow = false; setFollowControls(false); onFollow(false); }
        anim = null; userMoved = true;
        controls.target.set(target[0], target[1], target[2]);
        camera.position.set(pos[0], pos[1], pos[2]);
        clampView();
        camera.lookAt(controls.target);
        controls.update();
      },
      /* where the camera is: {pos, target, polar}, three coords */
      view: function () {
        return { pos: camera.position.toArray(), target: controls.target.toArray(), polar: controls.getPolarAngle() };
      },
      quality: function () { return quality; },
      setQuality: setQuality,
      /* one step down: fewer pixels, then no shadows. false at the floor */
      degrade: function () { return setQuality(quality - 1); },
      setReducedMotion: function (on) { reduced = !!on; fishUniforms.uWag.value = reduced ? 0 : 1; },
      /* the swim polish (POSE_GLSL, POLISH_FN) on / off, for measurements; polish(): is it drawn */
      /* the swim polish (POSE_GLSL): setPolish(true | false | "ungated"), for
       * measurements; polish(): its state (polishState) */
      setPolish: setPolish,
      polish: polishState,
      /* the swim pose's camera terms for tests (swimPose G): the view and
       * projection matrices, the focal length in CSS px, the canvas */
      poseCamera: function () {
        camera.updateMatrixWorld();
        return { view: Array.from(camera.matrixWorldInverse.elements), proj: Array.from(camera.projectionMatrix.elements),
                 near: camera.near, focalCss: 0.5 * ch * Math.abs(camera.projectionMatrix.elements[5]), canvasCss: [cw, ch],
                 halfW: halfW, halfH: halfH, drawingBuffer: [renderer.getContext().drawingBufferWidth, renderer.getContext().drawingBufferHeight] };
      },
      /* fish i as the last frame uploaded it (tests): its iPose (POSE0's when
       * that frame packed no poses: posed false, none could be lit), radius,
       * height, pitch, lambda, its kind's reach and unwrapped spine (the
       * appearance or the plain fish's buffers) */
      poseOf: function (i) {
        var app = appDrawn && appKind, at = app ? appKind.attrs : fish.attrs, o = 4 * i, A = at.iA.array, B = at.iB.array, Cc = at.iC.array;
        var raw = app ? at.iBody.array[o + 3] : at.iX.array[o + 1], posed = gateFish.posing;
        var litAt = app && at.iBody.array[o + 2] < 0 ? appKind.litIndexOf(i) : -1;   /* drawn apart (the split: its lit-draw index) */
        return { pose: unpackPose(posed ? raw : POSE0), packed: raw, posed: posed, apart: litAt,
                 R: at.iBody.array[o], y: at.iBody.array[o + 1], vz: at.iX.array[o], lam: app ? at.iX.array[o + 2] : 1, reach: app ? REACH_APP : fish.reach,
                 spine: [A[o], A[o + 1], A[o + 2], A[o + 3], B[o], B[o + 1], B[o + 2], B[o + 3], Cc[o], Cc[o + 1], Cc[o + 2], Cc[o + 3]] };
      },
      /* the flashlight: clear light on the followed fish, or where the camera
       * looks (aimBeam). Viewer only: nothing here reaches the simulation. */
      /* the appearance genome (web/ocean_appearance.js): each fish is drawn in
       * its own body whenever the snapshot has s.app; on, its skin is pattern
       * law 3 from its genes, off, its family / brain colour (s.colors) */
      setAppearance: function (on) { appSkin = !!on; },
      /* want / skin: the skin from the genes; shapes: the inherited bodies are
       * drawn (any colour mode); drawing: both */
      appearance: function () {
        var shapes = !!(appKind && appKind.mesh && appKind.mesh.visible);
        return { want: appSkin, skin: appSkin, shapes: shapes, drawing: appSkin && shapes,
                 status: appStatus, lod: appKind ? appKind.lod : "", verts: appKind ? appKind.tpls[appKind.lod || "medium"].verts : 0,
                 barbels: !!(appKind && appKind.bmesh && appKind.bmesh.visible) };
      },
      appearanceParity: function (rows, lams, cellW, cellH) { return appearanceParity(rows, lams, cellW, cellH); },
      /* GPU == CPU through the production programs (appearancePathCheck: the
       * fixed fixture, and rows / lams if given, through the vertex shader in
       * both colour modes and the fragment shader): a Promise of the report */
      appearancePathCheck: function (rows, lams, opts) {
        var p = appearancePathCheck(renderer.getContext(), window.EvoAppearance, rows, lams, opts);
        renderer.resetState();
        return p;
      },
      /* the live gene texture after the next production draw (see there): a Promise of the report */
      appearanceTextureParity: appearanceTextureParity,
      /* the gene texture and its upload counts (tests: upload interception):
       * capacity, the gene slots' (the texture's); drawCapacity, the instance
       * buffers'; slots, the owners (EvoAppearanceSlots stats); policy */
      geneTexture: function () {
        return appKind && appKind.tex ? { texture: appKind.tex, data: appKind.texData, capacity: appKind.slots.capacity, drawCapacity: appKind.cap, n: appKind.n,
                                          uploads: geneIO.uploads, calls: geneIO.calls, bytes: geneIO.bytes, allocs: geneIO.allocs,
                                          fullUploads: Object.assign({}, geneIO.full), rowChanges: geneIO.rowChanges,
                                          slots: appKind.slots.stats(), policy: genePolicy, last: appKind.last && Object.assign({}, appKind.last) } : null;
      },
      /* the gene slot of each fish as the last frame drew them (draw order; tests) */
      geneSlots: function () { return appKind && appDrawn ? Array.from(appKind.attrs.iGeneSlot.array.subarray(0, appKind.n)) : null; },
      /* the gene uploads: "dirty" (the default: what changed) or "full" (the
       * whole texture every frame, through the same slots: measurements and
       * the dirty-vs-full reference only) */
      setGeneUploads: function (p) { genePolicy = p === "full" ? "full" : "dirty"; },
      /* true: the lit appearance fish drawn apart on the full programs, the
       * rest plain (AppKind's split); false (the default: see litSplit), the
       * whole kind on the full programs while any is lit, as before */
      setLitSplit: function (on) { litSplit = on === true; },
      /* the fish's materials (web/ocean_materials.js): the binder's state
       * (its Look, every cached material by key: reserved, ready or failed);
       * setFeatures(set): a feature set (a Look's: web/ocean_materials.js says
       * its shape; null, none), a Promise of the outcome: it takes effect only
       * once every reachable variant assembled and compiled, else the previous
       * set stays */
      materials: function () { return binder.state(); },
      setFeatures: function (set) { return binder.activate(set); },
      testFaults: testFaults,
      /* the drawing context: renderer strings, extensions, attributes, drawing buffer */
      contextInfo: contextInfo,
      /* the water's clarity, 0 realistic .. 1 clear (drawing only; CLARITY) */
      setClarity: setClarity,
      clarity: function () { return clarity; },
      setFlashlight: function (on) { beamWant = !!on; },
      flashlight: function () { return beamWant; },
      flashlightLevel: function () { return beamAmt; },
      zoomBy: function (f) {
        var t = controls.target, off = camera.position.clone().sub(t);
        var d = Math.max(controls.minDistance, Math.min(controls.maxDistance, off.length() * f));
        camera.position.copy(t).addScaledVector(off.normalize(), d);
        userMoved = true;
      }
    };
  }

  window.EvoOceanScene = {
    load: load, create: create,
    /* the production-path checks on any WebGL2 context (no three needed) */
    appearancePathCheck: function (gl, rows, lams, opts) { return appearancePathCheck(gl, window.EvoAppearance, rows, lams, opts); },
    appearanceVertexCheck: function (gl, rows, lams, opts) { return appearanceVertexCheck(gl, window.EvoAppearance, rows, lams, opts); },
    appearanceFragmentCheck: function (gl, opts) { return appearanceFragmentCheck(gl, window.EvoAppearance, opts); },
    /* the shared slot selector (every gene-reading program and probe) */
    GENE_SLOT_GLSL: GENE_SLOT_GLSL,
    /* the swim pose of one fish (tests) and the fish programs' GLSL, plain
     * (P false: as before the polish) or polished */
    swimPose: swimPose, packPose: packPose, unpackPose: unpackPose, POSE0: POSE0,
    /* swimPose's parts (the fills' own: the size, the visibility, the pack), its visibility
     * sphere (its radius) and the appearance fish's reach */
    posePx: posePx, poseVisibleQ: poseVisibleQ, posePack: posePack, reachRadius: reachRadius, REACH_APP: REACH_APP,
    shaderSources: function (P) {
      var i = P === "lite" ? 2 : P ? 1 : 0, EA = window.EvoAppearance, a = EA ? appearanceShaders(EA, P === "lite" ? "lite" : !!P) : null;
      return { fishVs: SHADERS.FISH_VS[i], fishFs: SHADERS.FISH_FS[i], shadowVs: SHADERS.SHADOW_VS[i ? 1 : 0], shadowFs: SHADERS.SHADOW_FS,
               app: a ? { vs: a.vs, fs: a.fs, shadowVs: a.shadowVs } : null };
    }
  };
})();
