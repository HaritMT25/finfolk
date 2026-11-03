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
 * the spine points (20 floats per fish) into instance buffers; the bending,
 * shading and tail beat happen in the vertex/fragment shaders.
 *
 * World coordinates: sim (x right, y down, origin top-left) -> three
 * (X = x - W/2, Z = y - H/2, Y up = -depth).
 *
 * EvoOceanScene.load() -> Promise (imports the trimmed three bundle,
 * window.EVO_ASSETS.three); EvoOceanScene.create(canvas, opts) -> scene or null. */
(function () {
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
  /* The swim polish (uPolish: 1 from detail 2 up, setQuality; 0 draws the
   * fish exactly as before it). Vertex stage, from what the instance buffers
   * already hold (after seg(), in both fish programs and their shadows):
   *   turnOf()   how hard the fish turns: the sines of the angles between
   *              its spine's first three links (0.65 / 0.35), + = turning
   *              toward its +side
   *   bankOf()   the roll into that turn, its back toward the turn's centre,
   *              1.6 x the turn, at most 0.6 rad; rollTo() turns a point's
   *              (side, up) offset from the spine by it, so the spine, the
   *              head (trail, rings, picking) and the pitch are unchanged
   *   causOf()   faint caustic light at a point: an analytic two-wave network
   *              (no texture), per vertex, fading over the top ~50 units of
   *              water; the fragment stage keeps it to up-facing facets
   * The tail's trailing edge lags the peduncle (appWorld / fishWorld: a phase
   * lag and a second harmonic over the caudal fin, with the tail beat, so
   * reduced motion has none), and (appearance fish) the paired fins fold back
   * along the flank at speed (finPose). */
  var POSE_GLSL = [
    "uniform float uPolish;",
    "float turnOf() {",
    "  vec2 d0 = seg(0) - seg(1), d1 = seg(1) - seg(2), d2 = seg(2) - seg(3);",
    "  float t1 = (d1.x * d0.y - d1.y * d0.x) / max(length(d0) * length(d1), 1e-6);",
    "  float t2 = (d2.x * d1.y - d2.y * d1.x) / max(length(d1) * length(d2), 1e-6);",
    "  return 0.65 * t1 + 0.35 * t2;",
    "}",
    "float bankOf(float turn) { return uPolish * clamp(1.6 * turn, -0.6, 0.6); }",
    "vec2 rollTo(vec2 a, float b) { float cb = cos(b), sb = sin(b); return vec2(a.x * cb + a.y * sb, a.y * cb - a.x * sb); }",
    "float causOf(vec3 w) {",
    "  float fade = uPolish * exp(-0.022 * max(-w.y, 0.0));",
    "  if (fade < 0.02) return 0.0;",
    "  vec2 p = w.xz * 0.10; float t = uTime * 0.45;",
    "  float a = sin(p.x + 1.6 * sin(0.57 * p.y + t));",
    "  float b = sin(1.17 * p.y + 1.4 * sin(0.69 * p.x - 0.8 * t) + 0.5 * t);",
    "  float r = 1.0 - 0.5 * abs(a + b); r *= r;",
    "  return fade * r * r;",
    "}"
  ].join("\n");
  /* the tail beat's lateral offset at u (body lengths from the head), phase
   * ph: the caudal fin's trailing edge lags (e: 0 at the peduncle .. 1 half a
   * body behind it, 0 without the polish, where this is the old beat) */
  var WAG_GLSL = [
    "float wagAt(float u, float ph, float R) {",
    "  float e = uPolish * clamp(2.0 * (u - 1.0), 0.0, 1.0);",
    "  return (sin(ph - 0.9 * e) * (1.0 + 0.25 * e) + 0.14 * e * sin(2.0 * ph - 0.6)) * uWag * smoothstep(0.1, 1.3, u) * R * 0.3;",
    "}"
  ].join("\n");
  var FISH_CORE = [
    "attribute float part;",
    "attribute vec4 iA;", "attribute vec4 iB;", "attribute vec4 iC;",
    "attribute vec4 iCol;",   /* rgb, tail-beat phase */
    "attribute vec4 iBody;",  /* radius, height, highlight (1 selected, .5 hover), ember */
    "attribute vec4 iX;",     /* x: pitch as tan(angle) = vz, + = sinking (head down); yzw spare */
    "uniform vec2 uHalf;", "uniform float uTime;", "uniform float uWag;",
    /* glass walls (1): every vertex held inside the glass, so a fish against a
     * pane flattens on it instead of poking through (the engine holds its
     * spine inside; this clips the body's width, fins and wag) */
    "uniform float uWalls;",
    "vec3 inGlass(vec3 w) {",
    "  if (uWalls > 0.5) { w.x = clamp(w.x, -uHalf.x, uHalf.x); w.z = clamp(w.z, -uHalf.y, uHalf.y); }",
    "  return w;",
    "}",
    "vec2 seg(int i) {",
    "  if (i <= 0) return iA.xy; if (i == 1) return iA.zw; if (i == 2) return iB.xy;",
    "  if (i == 3) return iB.zw; if (i == 4) return iC.xy; return iC.zw;",
    "}",
    /* Catmull-Rom through the six spine points; straight beyond the ends */
    "vec2 spine(float s) {",
    "  if (s <= 0.0) return seg(0) + (seg(0) - seg(1)) * (-s);",
    "  if (s >= 5.0) return seg(5) + (seg(5) - seg(4)) * (s - 5.0);",
    "  int i = int(floor(s)); float t = s - float(i);",
    "  vec2 p0 = seg(max(i - 1, 0)), p1 = seg(i), p2 = seg(min(i + 1, 5)), p3 = seg(min(i + 2, 5));",
    "  float t2 = t * t, t3 = t2 * t;",
    "  return 0.5 * ((2.0 * p1) + (-p0 + p2) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2",
    "              + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3);",
    "}",
    POSE_GLSL,
    WAG_GLSL,
    /* nW: the body's smooth outward normal (the ring's, about 1 : 0.84
     * across; the nose tip's and tail cap's along the spine), rolled and
     * placed with it; zero on fins and eyes (the fragment stage then uses
     * the facet's) */
    "vec3 fishPose(out vec3 nW) {",
    "  float u = position.x, R = iBody.x;",
    "  float s = clamp(u, -0.5, 1.6) * 5.0;",
    "  vec2 c = spine(s);",
    "  vec2 f = spine(s - 0.15) - spine(s + 0.15);",
    "  float fl = length(f);",
    "  f = fl > 1e-4 ? f / fl : vec2(1.0, 0.0);",
    "  vec2 side = vec2(-f.y, f.x);",
    "  float wag = wagAt(u, uTime * 7.5 + iCol.w * 6.2831 - u * 4.5, R);",
    "  float bank = bankOf(turnOf());",
    "  vec2 lu = rollTo(vec2(position.y * R + wag, position.z * R), bank);",
    "  vec2 p = c + side * lu.x;",
    /* pitch: the head stays at the fish's depth and every point behind it
     * rises (sinking) or falls (rising) by its distance along the spine times
     * tan(pitch), so trail, rings and picking (all at the head) stay right and
     * the shadow follows the tilted body */
    "  float along = length(c - seg(0)) * (s < 0.0 ? -1.0 : 1.0);",
    "  float lift = along * clamp(iX.x, -1.2, 1.2);",
    "  vec2 q = vec2(position.y, 1.4 * position.z); float ql = length(q);",
    "  vec3 nl = part > 0.5 ? vec3(0.0) : (ql > 1e-4 ? vec3(0.0, q / ql) : vec3(u < 0.4 ? -1.0 : 1.0, 0.0, 0.0));",
    "  vec2 nr = rollTo(nl.yz, bank);",
    "  nW = vec3(side.x * nr.x - f.x * nl.x, nr.y, side.y * nr.x - f.y * nl.x);",
    "  return inGlass(vec3(p.x - uHalf.x, iBody.y + lu.y + lift, p.y - uHalf.y));",
    "}",
    "vec3 fishWorld() { vec3 n; return fishPose(n); }"
  ].join("\n");

  var FISH_VS = FISH_CORE + "\n" + [
    "varying vec3 vWorld; varying vec3 vCol; varying float vPart; varying float vOy;",
    "varying float vSel; varying float vEmber; varying vec4 vNs;",
    "void main() {",
    "  vec3 n;",
    "  vec3 w = fishPose(n);",
    "  vWorld = w; vCol = iCol.rgb; vPart = part; vOy = position.z; vSel = iBody.z; vEmber = iBody.w;",
    "  vNs = vec4(n, causOf(w));",
    "  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);",
    "}"
  ].join("\n");

  var FOG_FN = [
    "uniform vec3 uFog; uniform float uFogDensity;",
    "float fogOf(vec3 w) { float d = length(cameraPosition - w) * uFogDensity; return 1.0 - exp(-d * d); }"
  ].join("\n");

  /* The flashlight (setFlashlight; viewer only, the simulation never sees
   * it): a cone of clear light from the camera along uBeamDir, half-angle
   * atan(uBeamTan), soft at its rim, fading out past uBeamReach along the
   * axis. Inside it the fish, the food and the sand show their true colours:
   * no depth fall-off, no water tint, no fog. beamOf() is that share, 0..1
   * (times uBeamOn, the fade); 0 leaves every pixel exactly as without it. */
  var BEAM_FN = [
    "uniform float uBeamOn; uniform vec3 uBeamDir; uniform float uBeamTan; uniform float uBeamReach;",
    "float beamOf(vec3 w) {",
    "  if (uBeamOn <= 0.001) return 0.0;",
    "  vec3 d = w - cameraPosition;",
    "  float along = dot(d, uBeamDir);",
    "  if (along <= 0.0) return 0.0;",
    "  float r = along * uBeamTan;",
    "  float perp = length(d - uBeamDir * along);",
    "  return uBeamOn * (1.0 - smoothstep(0.45 * r, r, perp)) * (1.0 - smoothstep(uBeamReach, uBeamReach * 1.6, along));",
    "}"
  ].join("\n");

  /* Light under water: dimmer and bluer with depth (0 at the surface, 1 at
   * the tank's floor depth D), shared by the fish, their shadows and the food.
   * With the engine's light field on (E1: oc_light_enabled, setLight), the
   * fall-off is the engine's L(d) = L0·exp(−kWater·d) instead: brightness
   * L(d) and a blue shift of 1 − exp(−kWater·d); off, the preview's branch.
   * The water's clarity (setClarity, CLARITY) sets how much: at the floor
   * the colour keeps uDeepTint·(1 − uDeepDim), the light field keeps uLKeep
   * of what L(d) takes away, and no channel falls below uFloorMin. */
  var DEPTH_FN = [
    "uniform float uDepth;",
    "uniform float uLightOn; uniform float uL0; uniform float uKWater;",
    "uniform vec3 uDeepTint; uniform float uDeepDim; uniform vec3 uDeepAdd; uniform float uLKeep; uniform float uFloorMin;",
    "float depthOf(float y) { return clamp(-y / uDepth, 0.0, 1.0); }",
    /* how far into the dark a point is: depth / D, or 1 − L(d)/L0 with light on */
    "float shadeOf(float y) {",
    "  if (uLightOn < 0.5) return depthOf(y);",
    "  return clamp(1.0 - exp(-uKWater * max(-y, 0.0)), 0.0, 1.0);",
    "}",
    "vec3 underwater(vec3 col, float dz) {",
    "  col *= max(mix(vec3(1.0), uDeepTint, dz) * (1.0 - uDeepDim * dz), vec3(uFloorMin));",
    "  return col + uDeepAdd * dz;",
    "}",
    "vec3 underwaterAt(vec3 col, float y) {",
    "  if (uLightOn < 0.5) return underwater(col, depthOf(y));",
    "  float t = shadeOf(y);",
    "  float L = mix(uL0 * exp(-uKWater * max(-y, 0.0)), 1.0, uLKeep);",   /* the engine's lightAt(d), clarity applied */
    "  col *= max(mix(vec3(1.0), uDeepTint, t) * clamp(L, 0.05, 1.6), vec3(uFloorMin));",
    "  return col + uDeepAdd * t;",
    "}"
  ].join("\n");

  /* The water's clarity on the fish's own colour (setClarity): the back's
   * darkening (uBack: its share kept), the ambient light (uAmbLo facing down
   * .. uAmbHi facing up) and a display-only lift, vivid(): saturation, gain
   * and a gamma below 1 that lifts dark skins more than bright ones (uVivid;
   * (1, 1, 1) leaves the colour as it is). Never on the genes, the fish
   * card's swatch or the flashlight's clear light: lit() is the one light
   * model, and in the beam the fish is lit with the true-colour constants
   * (BACK_TRUE, ambTrue: the realistic ones), the same in any water. */
  var CLARITY_FN = [
    "uniform float uBack; uniform vec3 uAmbLo; uniform vec3 uAmbHi; uniform vec3 uVivid;",
    "const float BACK_TRUE = 0.56;",
    "vec3 ambOf(float ny) { return mix(uAmbLo, uAmbHi, 0.5 + 0.5 * ny); }",
    "vec3 ambTrue(float ny) { return mix(vec3(0.07, 0.13, 0.14), vec3(0.36, 0.48, 0.46), 0.5 + 0.5 * ny); }",
    "vec3 lit(vec3 b, vec3 amb, float diff, float rim) {",
    "  vec3 c = b * (amb + diff * vec3(1.0, 0.96, 0.86) * 0.92);",
    "  return c + rim * mix(b, vec3(0.6, 1.0, 0.92), 0.55) * 0.35;",
    "}",
    "vec3 vivid(vec3 c) {",
    "  if (uVivid == vec3(1.0)) return c;",
    "  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));",
    "  return pow(max(mix(vec3(l), c, uVivid.x), vec3(0.0)), vec3(uVivid.z)) * uVivid.y;",
    "}"
  ].join("\n");

  /* The swim polish's light (uPolish; POSE_GLSL), added to lit()'s, on the
   * murky and the flashlight's clear colour alike (polishOn(b, k): linear in
   * the skin b). thin: 1 on fins, less on barbels and the peduncle, 0 on the
   * body; with it the diffuse wraps a little past the terminator (the
   * caller's), the sunlight on a fin's far side shows through it, and a fin
   * seen against the light glows in its own colour (a view-dependent back
   * light, no texture). ns: the vertex stage's smooth normal (zero on fins:
   * the facet's) for a tight wet highlight, and in w its caustic light, kept
   * to up-facing facets. k = (transmitted, caustic, highlight). */
  var POLISH_FN = [
    "uniform float uPolish;",
    "const vec3 P_SUN = vec3(1.0, 0.96, 0.86), P_WET = vec3(1.0, 0.98, 0.92), P_CAUS = vec3(0.70, 0.95, 0.84);",
    "float wrapDiff(float nl, float thin) { float w = 0.45 * thin; return max((nl + w) / (1.0 + w), 0.0); }",
    "vec3 polishK(vec3 N, vec3 V, vec4 ns, float thin, float nl) {",
    "  if (uPolish < 0.5) return vec3(0.0);",
    "  vec3 Ns = ns.xyz; float l2 = dot(Ns, Ns);",
    "  Ns = l2 > 0.25 ? Ns * inversesqrt(l2) : N;",
    "  if (dot(Ns, V) < 0.0) Ns = N;",
    "  float s = clamp(dot(V, -normalize(uLight + 0.3 * N)), 0.0, 1.0); s *= s; s *= s;",
    "  float trans = thin * (0.40 * max(-nl, 0.0) + 0.60 * s);",
    "  float sp = pow(max(dot(Ns, normalize(uLight + V)), 0.0), 40.0) * 0.30 * (1.0 - 0.5 * thin);",
    "  return vec3(trans, 1.0 * ns.w * max(N.y, 0.0), sp);",
    "}",
    "vec3 polishOn(vec3 b, vec3 k) { return b * (P_SUN * k.x + P_CAUS * k.y) + P_WET * k.z; }"
  ].join("\n");

  var FISH_FS = [
    "uniform vec3 uLight; uniform float uTime; uniform vec3 uSelect;",
    FOG_FN,
    DEPTH_FN,
    CLARITY_FN,
    BEAM_FN,
    POLISH_FN,
    "varying vec3 vWorld; varying vec3 vCol; varying float vPart; varying float vOy;",
    "varying float vSel; varying float vEmber; varying vec4 vNs;",
    "vec3 baseOf(float back) {",
    "  vec3 base = vCol;",
    "  float body = 1.0 - step(0.5, vPart);",
    "  base = mix(base, base * back, smoothstep(0.30, 0.85, vOy) * body);",           /* darker back */
    "  base = mix(base, mix(base, vec3(0.93, 0.97, 0.90), 0.5), 1.0 - smoothstep(-0.7, -0.15, vOy));", /* pale belly */
    "  if (vPart > 0.5 && vPart < 1.5) base = mix(base, vec3(0.92, 0.98, 0.95), 0.22);", /* fins */
    "  return base;",
    "}",
    "void main() {",
    /* flat facets: the triangle's own normal, from screen-space derivatives */
    "  vec3 N = normalize(cross(dFdx(vWorld), dFdy(vWorld)));",
    "  vec3 V = normalize(cameraPosition - vWorld);",
    "  if (dot(N, V) < 0.0) N = -N;",
    "  float thin = uPolish * (vPart > 0.5 && vPart < 1.5 ? 1.0 : 0.0);",   /* fins */
    "  float nl = dot(N, uLight);",
    "  float diff = wrapDiff(nl, thin);",
    "  float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);",
    "  vec3 pk = polishK(N, V, vNs, thin, nl);",
    "  vec3 b = baseOf(uBack);",
    "  vec3 col = lit(b, ambOf(N.y), diff, rim) + polishOn(b, pk);",
    "  float bk = beamOf(vWorld);",
    /* in the flashlight's clear light: the true colours, the same in any water */
    "  vec3 clear = col;",
    "  if (bk > 0.0) { vec3 bt = baseOf(BACK_TRUE); clear = lit(bt, ambTrue(N.y), diff, rim) + polishOn(bt, pk); }",
    "  col = underwaterAt(vivid(col), vWorld.y);",
    "  vec3 ember = vec3(1.0, 0.38, 0.16) * (0.8 + 0.2 * sin(uTime * 6.0));",
    "  vec3 add = vec3(0.0);",
    "  if (vPart > 1.5) {",                                                            /* eyes */
    "    col = vEmber > 0.5 ? ember * 1.2 : vec3(0.02, 0.03, 0.03);",
    "    col += pow(max(dot(reflect(-uLight, N), V), 0.0), 20.0) * 0.8;",
    "    clear = col;",
    "  } else if (vEmber > 0.5) {",
    "    add += ember * rim * 0.55;",
    "  }",
    "  if (vSel > 0.75) add += uSelect * (0.16 + 0.55 * rim);",
    "  else if (vSel > 0.25) add += uSelect * 0.4 * rim;",
    "  col += add;",
    "  vec3 murky = mix(col, uFog, fogOf(vWorld));",
    "  if (bk > 0.0) {",
    "    clear = (clear + add) * (1.0 + 0.2 * max(dot(N, -uBeamDir), 0.0));",        /* the beam's own light on the side facing it */
    "    murky = mix(murky, clear, bk);",
    "  }",
    "  gl_FragColor = vec4(murky, 1.0);",
    "}"
  ].join("\n");

  /* a fish high above the floor casts a fainter shadow (vLift: 0 at the floor) */
  var SHADOW_VS = FISH_CORE + "\n" + [
    "uniform vec3 uLight; uniform float uFloorY; uniform float uDepth;",
    "varying vec3 vWorld; varying float vLift;",
    "void main() {",
    "  vec3 w = fishWorld();",
    "  vec3 s = w - uLight * ((w.y - uFloorY) / uLight.y);",
    "  s.y = uFloorY + 0.8;",
    "  vWorld = s;",
    "  vLift = clamp((w.y - uFloorY) / uDepth, 0.0, 1.0);",
    "  gl_Position = projectionMatrix * viewMatrix * vec4(s, 1.0);",
    "}"
  ].join("\n");
  var SHADOW_FS = [
    FOG_FN,
    "uniform float uAlpha;",
    "varying vec3 vWorld; varying float vLift;",
    "void main() { gl_FragColor = vec4(0.008, 0.04, 0.05, uAlpha * (1.0 - 0.7 * vLift) * (1.0 - fogOf(vWorld))); }"
  ].join("\n");

  /* ---- the appearance genome's fish (web/ocean_appearance.js: EvoAppearance) ----
   * The same spine, tail beat, pitch, lighting, depth, fog, selection and
   * flashlight as FISH_VS / FISH_FS; every gene comes from uGenes (a fish's
   * 63 floats in 16 RGBA32F texels, fetched by appearanceSlot()): the body is
   * the M1 template deformed by the 30 shape genes and its skin is pattern
   * law 3 from the 33 pattern floats, at the vertex's canonical material
   * site, evaluated before the bend and the swim, so the pattern never
   * slides. 7 vertex attributes. The legacy base / countershade / fin tint stage is not
   * applied to the skin (the genes carry their own).
   * uColourBy = 1 (the page's Family / Brain colours) keeps the body and
   * swaps only the skin: the fish's family / brain colour, packed 0xRRGGBB in
   * iX.w (exact in a float: < 2^24) and passed on in the flat vPart.w (no
   * extra attribute or varying), through the plain fish's base stage (darker
   * back, pale belly, paler fins) at the legacy template's height, (1 − 2v)
   * times the canonical profile, which equals FISH_FS's vOy on a neutral
   * body. The lighting, eyes, selection, fog and flashlight are shared. */
  /* An instance's gene slot: the 16-texel row of the gene texture its genes
   * are in (EvoAppearance GENES fetchGenes). One string for every program
   * that reads genes (the fish and its shadow, the transform-feedback check,
   * the live-texture probes), so that a change of ownership changes them all
   * at once. Today the slot is the draw index. */
  var GENE_SLOT_GLSL = "int appearanceSlot() { return gl_InstanceID; }";
  /* the pattern genes of the fetched slot -> the flat pattern varyings (the
   * fish's vertex shader and the texture-backed chart probe) */
  var DECODE_CALL = "patternDecode(GT[0], GT[1], GT[2], GT[3], GT[4], GT[5], GT[6], GT[7].xyz, vec2(GT[7].w, GT[8].x), iX.z);";
  /* a float32 constant as a GLSL float literal (as ocean_appearance.js writes its own) */
  function glslF(x) { var s = Math.fround(x).toPrecision(9); return s.indexOf(".") >= 0 || s.indexOf("e") >= 0 ? s : s + ".0"; }
  function appearanceShaders(EA) {
    var G = EA.GLSL;
    var CORE = [
      "attribute vec4 aT; attribute vec4 aPattern;",
      "attribute vec4 iA; attribute vec4 iB; attribute vec4 iC;",
      "attribute vec4 iBody;",  /* radius, height, highlight, swimming speed (the pose: / 150, smoothed; fillApp) */
      "attribute vec4 iX;",     /* pitch (vz), tail-beat phase, lambda, family / brain colour 0xRRGGBB */
      "uniform vec2 uHalf; uniform float uTime; uniform float uWag; uniform float uPxPerUnit;",
      "uniform float uWalls;",   /* glass walls: as FISH_CORE's inGlass (0 in the parity check: unset) */
      "uniform float uColourBy;",   /* 0: the skin from the genes (pattern law 3); 1: the family / brain colour */
      G.COMMON,
      G.GENES,
      GENE_SLOT_GLSL,
      G.MORPH,
      "vec2 seg(int i) {",
      "  if (i <= 0) return iA.xy; if (i == 1) return iA.zw; if (i == 2) return iB.xy;",
      "  if (i == 3) return iB.zw; if (i == 4) return iC.xy; return iC.zw;",
      "}",
      "vec2 spine(float s) {",
      "  if (s <= 0.0) return seg(0) + (seg(0) - seg(1)) * (-s);",
      "  if (s >= 5.0) return seg(5) + (seg(5) - seg(4)) * (s - 5.0);",
      "  int i = int(floor(s)); float t = s - float(i);",
      "  vec2 p0 = seg(max(i - 1, 0)), p1 = seg(i), p2 = seg(min(i + 1, 5)), p3 = seg(min(i + 2, 5));",
      "  float t2 = t * t, t3 = t2 * t;",
      "  return 0.5 * ((2.0 * p1) + (-p0 + p2) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2",
      "              + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3);",
      "}",
      POSE_GLSL,
      WAG_GLSL,
      /* fishWorld with the deformed rest point geo (body radii; x = lambda·u along
       * the spine): the extrapolation past the spine's ends is bounded, not
       * clamped to the legacy template's [-.5, 1.6] (long fins and barbels);
       * rolled by bank (bankOf); nl: the rest point's outward normal (x along
       * the spine to the tail, y the side, z up; zero: none) -> nW, in the world */
      "vec3 appPose(vec3 geo, vec3 nl, float bank, out vec3 nW) {",
      "  float R = iBody.x, u = geo.x / iX.z;",
      "  float s = clamp(u, -1.5, 3.0) * 5.0;",
      "  vec2 c = spine(s);",
      "  vec2 f = spine(s - 0.15) - spine(s + 0.15);",
      "  float fl = length(f);",
      "  f = fl > 1e-4 ? f / fl : vec2(1.0, 0.0);",
      "  vec2 side = vec2(-f.y, f.x);",
      "  float wag = wagAt(u, uTime * 7.5 + iX.y * 6.2831 - u * 4.5, R);",
      "  vec2 lu = rollTo(vec2(geo.y * R + wag, geo.z * R), bank);",
      "  vec2 p = c + side * lu.x;",
      "  float along = length(c - seg(0)) * (s < 0.0 ? -1.0 : 1.0);",
      "  float lift = along * clamp(iX.x, -1.2, 1.2);",
      "  vec3 w = vec3(p.x - uHalf.x, iBody.y + lu.y + lift, p.y - uHalf.y);",
      "  if (uWalls > 0.5) { w.x = clamp(w.x, -uHalf.x, uHalf.x); w.z = clamp(w.z, -uHalf.y, uHalf.y); }",
      "  vec2 nr = rollTo(nl.yz, bank);",
      "  nW = vec3(side.x * nr.x - f.x * nl.x, nr.y, side.y * nr.x - f.y * nl.x);",
      "  return w;",
      "}",
      /* the paired fins' pose (pectoral 3, pelvic 6: mBuild puts a fin point
       * at root + w d): folded back along the flank by k (0 spread, 1 folded;
       * the pelvics half as far), w d turned toward the tail at its length, the
       * root unmoved; spread, they scull a little with the tail beat's clock */
      "vec3 finPose(Morph M, vec3 geo, float k) {",
      "  int fin = int(aPattern.x + 0.5);",
      "  if (uPolish < 0.5 || (fin != 3 && fin != 6)) return geo;",
      "  bool pec = fin == 3; float side = aPattern.z;",
      "  float chord = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, sweep = pec ? M.pSweep : M.vSweep;",
      "  float dih = pec ? M.pDih : -0.25 * P_PI, kk = pec ? k : 0.5 * k;",
      "  float w = area / (chord * " + glslF(EA.PHI_I) + ") * aT.y * 4.0 * aT.x * (1.0 - aT.x);",
      "  vec3 d = vec3(sweep, side * cos(dih), sin(dih));",
      "  float sc = 0.22 * uWag * (1.0 - kk) * sin(uTime * 4.2 + iX.y * 6.2831 + 1.3 * side);",
      "  vec3 dS = vec3(sweep, side * cos(dih + sc), sin(dih + sc));",
      "  vec3 dT = normalize(vec3(1.0, 0.22 * side, -0.18)) * length(d);",
      "  return geo + w * (mix(dS, dT, kk) - d);",
      "}",
      /* the fold: with speed (iBody.w, / 150), less in a hard turn (the fins steer) */
      "float tuckOf(float turn) { return uPolish * pS(0.40, 0.90, iBody.w) * (1.0 - pS(0.10, 0.35, abs(turn))); }",
      /* the body's smooth outward normal at a rest point (an ellipse of its
       * depth and width genes; the nose tip and the tail cap: along the spine);
       * zero on the fins, eyes and barbels (the facet's is used) */
      "vec3 restNormal(Morph M, vec3 geo) {",
      "  if (int(aPattern.x + 0.5) != 0) return vec3(0.0);",
      "  vec2 q = vec2(geo.y * M.depth * M.depth, geo.z * M.width * M.width); float ql = length(q);",
      "  return ql > 1e-6 ? vec3(0.0, q / ql) : vec3(aT.x < 0.4 ? -1.0 : 1.0, 0.0, 0.0);",
      "}",
      "vec3 appWorld(vec3 geo, float bank) { vec3 n; return appPose(geo, vec3(0.0), bank, n); }",
      /* the barbels' screen-space minimum half-width (0.7 px), in body radii */
      "float minWidth() {",
      "  vec3 head = vec3(iA.x - uHalf.x, iBody.y, iA.y - uHalf.y);",
      "  return 0.7 * max(1.0, length(cameraPosition - head)) / max(1e-3, iBody.x * uPxPerUnit);",
      "}"
    ].join("\n");
    var vs = [
      CORE, G.VARY, G.DECODE,
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart; varying vec4 vNs;",
      "void main() {",
      "  fetchGenes(appearanceSlot());",
      "  if (uColourBy < 0.5) " + DECODE_CALL,
      "  Morph M = mDecode(iX.z);",
      "  vec3 geo, mat; float mar;",
      "  mBuild(M, aT, aPattern, uTime, uWag, minWidth(), geo, mat, mar);",
      /* the swim pose (POSE_GLSL): the paired fins' fold, the roll into the turn */
      "  float turn = turnOf();",
      "  geo = finPose(M, geo, tuckOf(turn));",
      "  vec3 nW;",
      "  vec3 w = appPose(geo, restNormal(M, geo), bankOf(turn), nW);",
      /* vPart: fin, side, highlight, the packed family / brain colour (the FS reads x, z, w) */
      "  vWorld = w; vMatV = vec4(mat, mar); vPart = vec4(aPattern.x, aPattern.z, iBody.z, iX.w);",
      "  vNs = vec4(nW, causOf(w));",   /* the smooth normal (the wet highlight), the caustic light */
      "  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);",
      "}"
    ].join("\n");
    var fs = [
      "uniform vec3 uLight; uniform float uTime; uniform vec3 uSelect; uniform float uColourBy;",
      FOG_FN, DEPTH_FN, CLARITY_FN, BEAM_FN, POLISH_FN,
      G.COMMON, G.VARY, G.SKIN,
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart; varying vec4 vNs;",
      /* the polish's thinness (POLISH_FN): the fins 1, the barbels .6, the
       * peduncle a little, the body and eyes 0 */
      "float thinOf(int fin, float u) { return fin == 0 ? 0.25 * pS(0.80, 1.0, u) : (fin == 7 ? 0.6 : (fin == 4 ? 0.0 : 1.0)); }",
      /* the skin's sheen (the polish; the genes' skin only, so Family / Brain
       * colours keep their hue): the structural colour of the scales at
       * grazing angles, a hue a little past the skin's own (vG0.x) that turns
       * with the angle, stronger on a pale unsaturated (silvery) skin, faint
       * on the fins */
      "vec3 sheenOf(float ndv, float thin, float nl) {",
      "  if (uPolish < 0.5) return vec3(0.0);",
      "  float silver = (1.0 - vG0.y) * vG0.z, g = 1.0 - ndv; g *= g;",
      "  return pHSV(pWrap01(vG0.x + 0.10 + 0.25 * g), 0.55, 1.0) * g * (0.12 + 0.30 * silver) * (1.0 - 0.6 * thin) * (0.55 + 0.45 * max(nl, 0.0));",
      "}",
      /* the family / brain colour (vPart.w = 0xRRGGBB) through FISH_FS's base
       * stage; oy = the legacy template's height in body radii */
      "vec3 colourBase(int fin, float oy, float back) {",
      "  float c = vPart.w;",
      "  float r = floor(c / 65536.0);",
      "  float g = floor((c - 65536.0 * r) / 256.0);",
      "  vec3 base = vec3(r, g, c - 65536.0 * r - 256.0 * g) / 255.0;",
      "  base = mix(base, base * back, smoothstep(0.30, 0.85, oy) * (fin == 0 ? 1.0 : 0.0));",        /* darker back */
      "  base = mix(base, mix(base, vec3(0.93, 0.97, 0.90), 0.5), 1.0 - smoothstep(-0.7, -0.15, oy));", /* pale belly */
      "  if (fin != 0) base = mix(base, vec3(0.92, 0.98, 0.95), 0.22);",                              /* fins, barbels */
      "  return base;",
      "}",
      "void main() {",
      "  int fin = int(vPart.x + 0.5);",
      /* the material site: body (t, θ, ρ) and barbels (root t, θ) use v = .5(1 − ρ sin θ) */
      "  bool bodyLike = fin == 0 || fin == 7;",
      "  float sn = (fin == 0 ? vMatV.z : 1.0) * sin(vMatV.y);",
      "  float u = vMatV.x;",
      "  float v = bodyLike ? 0.5 * (1.0 - sn) : vMatV.y;",
      "  float zL = bodyLike ? sn * pProfileH(u) : 0.0;",
      "  vec3 base;",
      "  float oyL = (1.0 - 2.0 * v) * pProfileH(u);",
      "  if (uColourBy > 0.5) base = colourBase(fin, oyL, uBack);",
      "  else {",
      "    base = patternSkinM(u, v, zL, fin == 7 ? 0 : fin, vMatV.w);",
      "    if (fin == 7) base = mix(base, patternBase(u, v), pS(0.0, 1.0, vMatV.z));",
      "  }",
      "  vec3 N = normalize(cross(dFdx(vWorld), dFdy(vWorld)));",
      "  vec3 V = normalize(cameraPosition - vWorld);",
      "  if (dot(N, V) < 0.0) N = -N;",
      "  float thin = uPolish * thinOf(fin, u);",
      "  float nl = dot(N, uLight);",
      "  float diff = wrapDiff(nl, thin);",
      "  float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);",
      "  vec3 pk = polishK(N, V, vNs, thin, nl);",
      "  vec3 sheen = fin != 4 && uColourBy < 0.5 ? sheenOf(max(dot(N, V), 0.0), thin, nl) : vec3(0.0);",
      "  vec3 col = lit(base, ambOf(N.y), diff, rim) + polishOn(base, pk) + sheen;",
      "  float bk = beamOf(vWorld);",
      /* in the flashlight's clear light: the true colours, the same in any water (the skin never sees the water) */
      "  vec3 clear = col;",
      "  if (bk > 0.0) {",
      "    vec3 bt = uColourBy > 0.5 ? colourBase(fin, oyL, BACK_TRUE) : base;",
      "    clear = lit(bt, ambTrue(N.y), diff, rim) + polishOn(bt, pk) + sheen;",
      "  }",
      "  col = underwaterAt(vivid(col), vWorld.y);",
      "  vec3 add = vec3(0.0);",
      "  float vSel = vPart.z;",
      "  if (fin == 4) {",
      "    col = vec3(0.02, 0.03, 0.03);",
      "    col += pow(max(dot(reflect(-uLight, N), V), 0.0), 20.0) * 0.8;",
      "    clear = col;",
      "  }",
      "  if (vSel > 0.75) add += uSelect * (0.16 + 0.55 * rim);",
      "  else if (vSel > 0.25) add += uSelect * 0.4 * rim;",
      "  col += add;",
      "  vec3 murky = mix(col, uFog, fogOf(vWorld));",
      "  if (bk > 0.0) {",
      "    clear = (clear + add) * (1.0 + 0.2 * max(dot(N, -uBeamDir), 0.0));",
      "    murky = mix(murky, clear, bk);",
      "  }",
      "  gl_FragColor = vec4(murky, 1.0);",
      "}"
    ].join("\n");
    var shadowVs = [
      CORE,
      "uniform vec3 uLight; uniform float uFloorY; uniform float uDepth;",
      "varying vec3 vWorld; varying float vLift;",
      "void main() {",
      "  fetchGenes(appearanceSlot());",
      "  Morph M = mDecode(iX.z);",
      "  vec3 geo, mat; float mar;",
      "  mBuild(M, aT, aPattern, uTime, uWag, minWidth(), geo, mat, mar);",
      "  float turn = turnOf();",   /* the swim pose, as the fish's own */
      "  vec3 w = appWorld(finPose(M, geo, tuckOf(turn)), bankOf(turn));",
      "  vec3 s = w - uLight * ((w.y - uFloorY) / uLight.y);",
      "  s.y = uFloorY + 0.8;",
      "  vWorld = s;",
      "  vLift = clamp((w.y - uFloorY) / uDepth, 0.0, 1.0);",
      "  gl_Position = projectionMatrix * viewMatrix * vec4(s, 1.0);",
      "}"
    ].join("\n");
    /* the GPU == CPU check: one canonical flank chart (u, v in [0, 1]²) per
     * instance in its own cell of a float target, unlit and unfiltered
     * (uIntrinsic = 1), against EvoAppearance.flankAt */
    var chartVs = [
      "attribute vec4 iG0; attribute vec4 iG1; attribute vec4 iG2; attribute vec4 iG3;",
      "attribute vec4 iG4; attribute vec4 iG5; attribute vec4 iG6; attribute vec4 iCol; attribute vec4 iX;",
      "attribute vec4 iCell;",   /* the cell's x0, y0, w, h in NDC */
      G.COMMON, G.VARY, G.DECODE,
      "varying vec2 vUV;",
      "void main() {",
      "  patternDecode(iG0, iG1, iG2, iG3, iG4, iG5, iG6, iCol.xyz, iX.yz, iX.w);",
      "  vUV = position.xy;",
      "  gl_Position = vec4(iCell.xy + position.xy * iCell.zw, 0.0, 1.0);",
      "}"
    ].join("\n");
    var chartFs = [
      G.COMMON, G.VARY, G.SKIN,
      "varying vec2 vUV;",
      "void main() { float u = vUV.x, v = vUV.y; gl_FragColor = vec4(patternSkinM(u, v, pProfileH(u) * (1.0 - 2.0 * v), 0, 1000.0), 1.0); }"
    ].join("\n");
    /* the live gene texture's probes (appearanceTextureParity), with the
     * fish's own GENES, GENE_SLOT_GLSL and DECODE_CALL. probeRawVs: an
     * instance's 16 texels as fetched, onto 16 pixels of a float target
     * (placed by draw index, read through appearanceSlot()); probeChartVs: the
     * chart above, fed from the gene texture and the production iX, in the
     * cell iCell gives it (off the target for an instance not charted) */
    var probeRawVs = [
      G.GENES, GENE_SLOT_GLSL,
      "attribute float aTexel;",   /* 0..15, the same over a pixel's quad */
      "uniform vec2 uProbeSize;",
      "flat varying vec4 vRaw;",
      "void main() {",
      "  fetchGenes(appearanceSlot());",
      "  int k = int(aTexel + 0.5);",
      "  vRaw = GT[k];",
      "  int o = 16 * gl_InstanceID + k;",
      "  vec2 px = vec2(float(o % 512), float(o / 512)) + position.xy;",
      "  gl_Position = vec4(2.0 * px / uProbeSize - 1.0, 0.0, 1.0);",
      "}"
    ].join("\n");
    var probeRawFs = "flat varying vec4 vRaw;\nvoid main() { gl_FragColor = vRaw; }";
    var probeChartVs = [
      "attribute vec4 iX;", "attribute vec4 iCell;",
      G.COMMON, G.VARY, G.DECODE, G.GENES, GENE_SLOT_GLSL,
      "varying vec2 vUV;",
      "void main() {",
      "  fetchGenes(appearanceSlot());",
      "  " + DECODE_CALL,
      "  vUV = position.xy;",
      "  gl_Position = vec4(iCell.xy + position.xy * iCell.zw, 0.0, 1.0);",
      "}"
    ].join("\n");
    return { vs: vs, fs: fs, shadowVs: shadowVs, chartVs: chartVs, chartFs: chartFs,
             probeRawVs: probeRawVs, probeRawFs: probeRawFs, probeChartVs: probeChartVs };
  }

  /* The appearance checks: three layers, each against the CPU mirror
   * (web/ocean_appearance.js), each a Promise of a report whose read-back
   * waits on a fence, polled (at most 10 s), so it never stalls the pipeline.
   * A report with .error did not run (a missing extension, a compile error,
   * a timeout): that is never a pass, and never a planted fault caught.
   *   appearanceParity (in create): pattern law 3 alone, the pattern genes
   *     fed as attributes (the gallery's K12 reference); no gene texture.
   *   appearancePathCheck: a fixed 65-fish fixture (pathFixture: it crosses
   *     the texture's 32-fish rows twice, every fish distinct, all with
   *     barbels; the caller's rows, if any, are added) through the production
   *     programs, on a texture packed and laid out as the renderer packs it:
   *     the fish's vertex shader in both colour modes by transform feedback
   *     (appearanceVertexCheck: appearance, and recolour, whose nonzero packed
   *     colours must reach vPart.w), and its fragment shader on known inputs
   *     (appearanceFragmentCheck: the recolour path, Family's and Brain's
   *     palettes, and the skin).
   *   appearanceTextureParity (in create): the live gene texture itself, as
   *     three uploaded it, read through the same slot selector right after a
   *     production draw: its raw genes bit for bit, and the pattern charts.
   * They share what the fish reads (GENE_SLOT_GLSL, DECODE_CALL, GENES), the
   * WebGL2 prefixes (VS3, FS3) and the fence polling (fenceDone). */
  var VS3 = "#version 300 es\n#define attribute in\n#define varying out\nprecision highp float;\nprecision highp int;\n" +
            "uniform mat4 projectionMatrix;\nuniform mat4 viewMatrix;\nuniform vec3 cameraPosition;\n";
  var FS3 = "#version 300 es\n#define varying in\nprecision highp float;\nprecision highp int;\nuniform vec3 cameraPosition;\n" +
            "out highp vec4 pcFrag;\n#define gl_FragColor pcFrag\n";
  function compileProgram(gl, vs, fs, feedback) {
    function compile(type, src) {
      var o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
      if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) { var log = gl.getShaderInfoLog(o); gl.deleteShader(o); throw new Error("compile: " + log); }
      return o;
    }
    var prog = gl.createProgram(), a = compile(gl.VERTEX_SHADER, vs), b;
    try { b = compile(gl.FRAGMENT_SHADER, fs); } catch (e) { gl.deleteShader(a); gl.deleteProgram(prog); throw e; }
    gl.attachShader(prog, a); gl.attachShader(prog, b);
    if (feedback) gl.transformFeedbackVaryings(prog, feedback, gl.INTERLEAVED_ATTRIBS);
    gl.linkProgram(prog);
    gl.deleteShader(a); gl.deleteShader(b);   /* freed with the program */
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { var l = gl.getProgramInfoLog(prog); gl.deleteProgram(prog); throw new Error("link: " + l); }
    return prog;
  }
  /* resolves null once the GPU passed sync, else why not (lost, failed, 10 s) */
  function fenceDone(gl, sync, ms) {
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function poll() {
        if (gl.isContextLost && gl.isContextLost()) { resolve("the WebGL context was lost"); return; }
        var st = gl.clientWaitSync(sync, 0, 0);
        if (st === gl.TIMEOUT_EXPIRED && Date.now() - t0 < ms) { setTimeout(poll, 2); return; }
        resolve(st === gl.WAIT_FAILED || st === gl.TIMEOUT_EXPIRED ? "the GPU did not finish (" + st + ")" : null);
      })();
    });
  }
  function occurrences(s, sub) { return s.split(sub).length - 1; }
  /* a planted fault: its site must occur exactly once */
  function plant(src, name, table) {
    var m = table[name];
    if (!m) return { error: "unknown mutation " + name };
    if (occurrences(src, m[0]) !== 1) return { error: "mutation " + name + ": its site occurs " + occurrences(src, m[0]) + " times" };
    return { src: src.split(m[0]).join(m[1]) };
  }

  /* The genes' GPU layout (EvoAppearance GENES fetchGenes): a fish's 63
   * floats and one zero in 16 RGBA32F texels, 512 texels a texture row. The
   * renderer (AppKind, fillApp) and the production-path check pack it with these. */
  var GENES_W = 512, GENE_TEXELS = 16;
  function genesRows(cap) { return Math.ceil(cap * GENE_TEXELS / GENES_W); }
  function packGenes(T, R, r, c, ST) {
    var to = 4 * GENE_TEXELS * c;
    for (var j = 0; j < ST; j++) T[to + j] = R[r + j];
    T[to + 63] = 0;
  }
  /* the renderer's capacity for n fish (AppKind ensure) */
  function capFor(n) { var cap = 256; while (cap < n) cap *= 2; return cap; }

  /* The fixed fixture of appearancePathCheck, whatever the caller's world:
   * 65 distinct fish (two texture-row crossings), every one with barbels */
  function pathFixture(EA) {
    var rows = [], lams = [];
    for (var c = 0; c < 65; c++) {
      var g = [];
      for (var j = 0; j < EA.STRIDE; j++) g.push(Math.fround(0.05 + 0.90 * ((37 * c + 17 * j + 13) % 251) / 250));
      g[EA.MO + 26] = Math.fround(0.75);
      rows.push(g); lams.push(Math.fround(3.5 + 0.05 * c));
    }
    return { rows: rows, lams: lams };
  }

  /* GPU == CPU through the production vertex path (appearanceVertexCheck).
   * appearanceParity feeds the pattern genes as attributes and checks the
   * skin only, so a wrong gene-texture row or slot would pass it. Here the
   * fish program's own vertex shader (appearanceShaders vs, with three's
   * WebGL2 prefix) runs on a gene texture packed and laid out as the
   * renderer packs it (packGenes, genesRows at the renderer's capacity), for
   * the medium and coarse bodies and the barbel strips (every part: body,
   * tail, dorsal, pectoral, eye, anal, pelvic fins, barbels). Transform
   * feedback reads back every vertex of every fish: its world position,
   * material site and fin margin, its part (all four vPart components: fin,
   * side, highlight, packed colour), and in appearance mode (opts.colourBy 0)
   * the pattern varyings it decoded from the texture; each is compared with
   * the CPU mirror (EvoAppearance morphDecode / morphBuild / patternVaryings,
   * appWorldCPU). Recolour mode (colourBy 1, Family / Brain) skips
   * patternDecode, so its pattern varyings are unwritten: they are neither
   * captured nor checked. Every captured component must be finite before any
   * arithmetic (a NaN fails no |a - b| > tol test, and min(x, 10) hides an
   * infinity); report.nan counts the vertices with any non-finite output.
   * opts.mutate plants a fault ("row0", "nextRow", "slot": the texture
   * lookup; "partW": vPart.w loses the packed colour): the check must then
   * fail. opts.injectSweep: after the run, NaN / +Inf / -Inf put into each
   * captured component in turn (of two fish of the medium body, one on the
   * second texture row) must each fail with that component named. */
  var PATH_TOL = { world: 0.02, mat: 0.005, mar: 0.005, decode: 0.0005 };
  var TF_OUT = [["vWorld", 3], ["vMatV", 4], ["vPart", 4], ["vG0", 4], ["vG1", 4], ["vG2", 4], ["vG3", 4],
                ["vG4", 4], ["vG5", 4], ["vG6", 4], ["vG7", 4], ["vAux", 4], ["vMeta", 4]];
  var PATH_COLOURS = [0x123456, 0xe32791, 0x07c15a, 0x010203, 0xfedcba];
  var PATH_FETCH = "int li = 16 * inst + k;";
  var PATH_MUT = {
    row0: [PATH_FETCH, "int li = 16 * 0 + k;"],
    nextRow: [PATH_FETCH, "int li = 16 * (inst + 1) + k;"],
    slot: [PATH_FETCH, "int li = 16 * inst + (k ^ 1);"],
    partW: ["vPart = vec4(aPattern.x, aPattern.z, iBody.z, iX.w);", "vPart = vec4(aPattern.x, aPattern.z, iBody.z, 0.0);"]
  };
  function componentNames(layout) {
    var out = [];
    layout.forEach(function (v) { for (var i = 0; i < v[1]; i++) out.push(v[0] + "." + "xyzw"[i]); });
    return out;
  }
  function appearanceVertexCheck(gl, EA, rows, lams, opts) {
    opts = opts || {};
    if (!EA || !EA.morphBuild) return Promise.resolve({ error: "web/ocean_appearance.js (with its CPU mirror) not loaded" });
    var colourBy = opts.colourBy === 1 ? 1 : 0;
    var feedback = colourBy ? TF_OUT.slice(0, 3) : TF_OUT, names = componentNames(feedback);
    var vsrc = appearanceShaders(EA).vs;
    if (vsrc.indexOf(PATH_FETCH) < 0) return Promise.resolve({ error: "the gene fetch is not where the check expects it" });
    if (opts.mutate) {
      var pm = plant(vsrc, opts.mutate, PATH_MUT);
      if (pm.error) return Promise.resolve({ error: pm.error });
      vsrc = pm.src;
    }
    var fsrc = "#version 300 es\nprecision highp float;\nout vec4 pcOut;\nvoid main() { pcOut = vec4(0.0); }\n";
    var NC = names.length;
    if (gl.getParameter(gl.MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS) < NC) return Promise.resolve({ error: "transform feedback holds fewer than " + NC + " floats" });
    var prog;
    try { prog = compileProgram(gl, VS3 + vsrc, fsrc, feedback.map(function (v) { return v[0]; })); }
    catch (e) { return Promise.resolve({ error: e.message || String(e) }); }

    /* the fish: their genes in the renderer's texture, a bent spine each, a packed colour each */
    var n = rows.length, ST = EA.STRIDE, cap = capFor(n), texRows = genesRows(cap);
    var T = new Float32Array(GENES_W * texRows * 4), R = new Float32Array(n * ST);
    for (var c = 0; c < n; c++) { for (var j = 0; j < ST; j++) R[c * ST + j] = rows[c][j]; packGenes(T, R, c * ST, c, ST); }
    var U = { half: [960, 540], px: 500, cam: [120, 380, 900], colourBy: colourBy };
    var inst = { iA: new Float32Array(4 * n), iB: new Float32Array(4 * n), iC: new Float32Array(4 * n), iBody: new Float32Array(4 * n), iX: new Float32Array(4 * n) };
    for (c = 0; c < n; c++) {
      var lam = Math.fround(lams[c]), Rb = Math.fround(4.6 * (0.8 + 0.4 * ((c * 0.37) % 1))), sp = lam * Rb / 5;
      var a = c * 0.7, bend = 0.15 * Math.sin(c), px = 300 + (37 * c) % 1300, py = 200 + (53 * c) % 700, pts = [px, py];
      for (var k = 1; k < 6; k++) { px -= sp * Math.cos(a + bend * k); py -= sp * Math.sin(a + bend * k); pts.push(px, py); }
      inst.iA.set(pts.slice(0, 4), 4 * c); inst.iB.set(pts.slice(4, 8), 4 * c); inst.iC.set(pts.slice(8, 12), 4 * c);
      inst.iBody.set([Rb, -20 - (3 * c) % 200, 0, Math.fround(1.2 * ((c * 0.29) % 1))], 4 * c);   /* w: a swimming speed (the fin fold) */
      inst.iX.set([0.3 * Math.sin(c * 1.3), (c * 0.618) % 1, lam, PATH_COLOURS[c % PATH_COLOURS.length]], 4 * c);
    }
    var tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, GENES_W, texRows, 0, gl.RGBA, gl.FLOAT, T);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.useProgram(prog);
    function uni(name) { return gl.getUniformLocation(prog, name); }
    var I4 = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    gl.uniformMatrix4fv(uni("projectionMatrix"), false, I4); gl.uniformMatrix4fv(uni("viewMatrix"), false, I4);
    gl.uniform3fv(uni("cameraPosition"), U.cam); gl.uniform2fv(uni("uHalf"), U.half);
    gl.uniform1f(uni("uTime"), 0); gl.uniform1f(uni("uWag"), 0); gl.uniform1f(uni("uPxPerUnit"), U.px);
    gl.uniform1f(uni("uColourBy"), colourBy); gl.uniform1i(uni("uGenes"), 0);
    gl.uniform1f(uni("uPolish"), 1);   /* the swim pose on: the roll and the fin fold, mirrored by appWorldCPU / finPoseCPU */

    var tpls = [["medium", EA.buildTemplate("medium")], ["coarse", EA.buildTemplate("coarse")], ["barbels", EA.buildBarbels("medium")]];
    var bufs = [], jobs = [];
    gl.enable(gl.RASTERIZER_DISCARD);
    var tfo = gl.createTransformFeedback();
    tpls.forEach(function (tp) {
      var tpl = tp[1];
      if (!tpl) return;
      var ringT = new Float32Array(16);
      for (var i = 0; i < 16; i++) ringT[i] = i < tpl.ringT.length ? tpl.ringT[i] : 0;
      gl.uniform1fv(uni("uRingT[0]") || uni("uRingT"), ringT); gl.uniform1i(uni("uRingN"), tpl.ringT.length); gl.uniform1f(uni("uHalfRing"), tpl.half);
      var vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      function attr(name, data, divisor) {
        var loc = gl.getAttribLocation(prog, name);
        if (loc < 0) return;
        var b = gl.createBuffer(); bufs.push(b);
        gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(loc, divisor);
      }
      attr("aT", tpl.pos, 0); attr("aPattern", tpl.pat, 0);
      Object.keys(inst).forEach(function (nm) { attr(nm, inst[nm], 1); });
      var out = gl.createBuffer(); bufs.push(out);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, out);
      gl.bufferData(gl.TRANSFORM_FEEDBACK_BUFFER, tpl.verts * n * NC * 4, gl.STREAM_READ);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, tfo);
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, out);
      gl.beginTransformFeedback(gl.POINTS);
      gl.drawArraysInstanced(gl.POINTS, 0, tpl.verts, n);
      gl.endTransformFeedback();
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
      gl.bindVertexArray(null);
      gl.deleteVertexArray(vao);
      jobs.push({ name: tp[0], tpl: tpl, ringT: ringT, buf: out });
    });
    gl.disable(gl.RASTERIZER_DISCARD);
    var sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    gl.flush();
    /* leave nothing bound (a renderer resets its own state after this);
     * the read-back later binds only COPY_READ_BUFFER, which three never uses */
    gl.useProgram(null); gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindTexture(gl.TEXTURE_2D, null);
    function cleanup() {
      gl.bindBuffer(gl.COPY_READ_BUFFER, null);
      gl.deleteSync(sync); gl.deleteTransformFeedback(tfo); gl.deleteTexture(tex); gl.deleteProgram(prog);
      bufs.forEach(function (b) { gl.deleteBuffer(b); });
    }
    return fenceDone(gl, sync, 10000).then(function (why) {
      if (why) { cleanup(); return { error: why, colourBy: colourBy }; }
      var res = { fish: n, texRows: texRows, colourBy: colourBy, components: NC, mutate: opts.mutate || "", tol: PATH_TOL, templates: {}, ok: true };
      var datas = {};
      jobs.forEach(function (jb) {
        var V = jb.tpl.verts, data = new Float32Array(V * n * NC);
        gl.bindBuffer(gl.COPY_READ_BUFFER, jb.buf);
        gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, data);
        datas[jb.name] = data;
        res.templates[jb.name] = compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, null, names);
      });
      cleanup();
      var fins = {};
      Object.keys(res.templates).forEach(function (k) {
        var r = res.templates[k];
        if (!r.pass) res.ok = false;
        Object.keys(r.fins).forEach(function (f) { fins[f] = (fins[f] || 0) + r.fins[f]; });
      });
      res.fins = fins;
      res.allParts = [0, 1, 2, 3, 4, 5, 6, 7].every(function (f) { return fins[f] > 0; });
      res.barbelFish = rows.filter(function (g) { return g[EA.MO + 26] > 0.2; }).length;
      if (!res.allParts || !res.barbelFish) res.ok = false;
      if (opts.injectSweep && jobs.length) res.sweep = injectSweep(EA, jobs[0], datas[jobs[0].name], n, NC, rows, lams, inst, U, names);
      return res;
    });
  }
  /* NaN, +Inf and -Inf into each captured component of one vertex at a time
   * (in place, restored after), compared on that fish alone: each must fail,
   * naming its component */
  function injectSweep(EA, jb, data, n, NC, rows, lams, inst, U, names) {
    var V = jb.tpl.verts, at = [[0, 0], [Math.min(n - 1, 40), Math.min(V - 1, 7)]];
    var out = { template: jb.name, positions: at, values: ["NaN", "Infinity", "-Infinity"], tried: 0, killed: 0, survivors: [], baselinePass: true };
    at.forEach(function (p) {
      var c = p[0], v = p[1], only = [c, c + 1];
      if (!compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names).pass) out.baselinePass = false;
      for (var k = 0; k < NC; k++) {
        [NaN, Infinity, -Infinity].forEach(function (x) {
          var o = (c * V + v) * NC + k, keep = data[o];
          data[o] = x;
          var r = compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names);
          data[o] = keep;
          out.tried++;
          if (r.pass === false && r.nan > 0 && r.worst.indexOf("non-finite feedback component " + k + " (") >= 0) out.killed++;
          else if (out.survivors.length < 12) out.survivors.push({ fish: c, vertex: v, component: k, name: names[k], value: String(x), worst: r.worst });
        });
      }
    });
    return out;
  }

  /* GPU == CPU through the production fragment shader (appearanceFragmentCheck):
   * appearanceShaders(EA).fs unchanged (FS3: the WebGL2 dialect prefix of
   * appearanceParity), linked to a diagnostic quad whose vertex shader hands
   * it known material / part inputs and the decoded pattern varyings (it
   * does no shading of its own). A 17 x 17 RGBA32F target; its centre pixel,
   * where vWorld = (0, 0, 0) under a camera at (0, 10, 0) and a light straight
   * down: N = V = (0, 1, 0), no rim, no depth tint (uDepth 240, the light
   * field off), no fog, no flashlight, realistic water (CLARITY [0]: vivid
   * off), so lit skin is base x (1.28, 1.3632, 1.2512) and an eye
   * (0.82, 0.83, 0.83); with the swim polish on (uPolish 1, POLISH_FN) the
   * wet highlight's peak on top, 0.30 x (1 - thin / 2) x P_WET (a smooth
   * normal straight up; nothing shows through, no sheen, no caustic light
   * when the light is behind the camera). Recolour (uColourBy 1): Family's and Brain's packed
   * palettes, parts 0..7, heights v = 0, .5, 1 at u = .42 (profile height
   * .72), against recolourBase, an independent statement of the base stage;
   * appearance (uColourBy 0): body part 0 against EvoAppearance.flankAt.
   * Constant material inputs make the derivative filters vanish. Max |error|
   * over RGB <= .003, alpha 1. opts.fsMutate ("swapRB": red and blue
   * exchanged in the unpacking; "branch": the colour-mode branch reversed)
   * must fail it. */
  var FRAG_TOL = 0.003;
  var FRAG_MUL = [0.36 + 0.92, 0.48 + 0.92 * 0.96, 0.46 + 0.92 * 0.86];   /* ambient straight up + full diffuse */
  var FRAG_EYE = [0.82, 0.83, 0.83];
  /* the polish's wet highlight at its peak on part fin (POLISH_FN polishK, thinOf at u = .42) */
  function fragWet(fin) { var t = fin === 0 ? 0 : (fin === 7 ? 0.6 : 1), k = 0.30 * (1 - 0.5 * t); return [k, k * 0.98, k * 0.92]; }
  var FRAG_PALETTES = { family: PATH_COLOURS, brain: [0xff0000, 0x00ff00, 0x0000ff, 0x808080, 0x3c9ae1] };
  var FRAG_MUT = {
    swapRB: ["vec3 base = vec3(r, g, c - 65536.0 * r - 256.0 * g) / 255.0;", "vec3 base = vec3(c - 65536.0 * r - 256.0 * g, g, r) / 255.0;"],
    branch: ["if (uColourBy > 0.5) base = colourBase(fin, oyL, uBack);", "if (uColourBy < 0.5) base = colourBase(fin, oyL, uBack);"]
  };
  function recolourBase(rgb, fin, v) {
    var base = [(rgb >>> 16) & 255, (rgb >>> 8) & 255, rgb & 255].map(function (x) { return x / 255; });
    function smooth(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
    function mix(a, b, t) { return a.map(function (x, i) { return x + (b[i] - x) * t; }); }
    var oy = (1 - 2 * v) * 0.72;
    base = mix(base, base.map(function (x) { return x * 0.56; }), smooth(0.30, 0.85, oy) * (fin === 0 ? 1 : 0));
    base = mix(base, mix(base, [0.93, 0.97, 0.90], 0.5), 1 - smooth(-0.7, -0.15, oy));
    if (fin !== 0) base = mix(base, [0.92, 0.98, 0.95], 0.22);
    return base;
  }
  function appearanceFragmentCheck(gl, EA, opts) {
    opts = opts || {};
    if (!EA || !EA.flankAt) return Promise.resolve({ error: "web/ocean_appearance.js not loaded" });
    var fsrc = appearanceShaders(EA).fs;
    if (opts.fsMutate) {
      var pm = plant(fsrc, opts.fsMutate, FRAG_MUT);
      if (pm.error) return Promise.resolve({ error: pm.error });
      fsrc = pm.src;
    }
    if (!gl.getExtension("EXT_color_buffer_float")) return Promise.resolve({ error: "no float render targets (EXT_color_buffer_float)" });
    var G = EA.GLSL;
    var vsrc = [
      G.COMMON, G.VARY, G.DECODE,
      "attribute vec2 aXY;",
      "uniform vec4 uG[9]; uniform float uLam;",
      "uniform vec4 uMaterial; uniform float uFin; uniform float uPacked;",
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart; varying vec4 vNs;",
      "void main() {",
      "  patternDecode(uG[0], uG[1], uG[2], uG[3], uG[4], uG[5], uG[6], uG[7].xyz, vec2(uG[7].w, uG[8].x), uLam);",
      "  vWorld = vec3(aXY.x, 0.0, aXY.y);",
      "  vMatV = uMaterial;",
      "  vPart = vec4(uFin, 1.0, 0.0, uPacked);",
      "  vNs = vec4(0.0, 1.0, 0.0, 0.0);",   /* a smooth normal straight up, no caustic light */
      "  gl_Position = vec4(aXY, 0.0, 1.0);",
      "}"
    ].join("\n");
    var prog;
    try { prog = compileProgram(gl, VS3 + vsrc, FS3 + fsrc); }
    catch (e) { return Promise.resolve({ error: e.message || String(e) }); }
    for (var guard = 0; guard < 32 && gl.getError() !== gl.NO_ERROR; guard++);   /* not ours */

    /* the cases: [colourBy, fin, packed colour, gene row, lambda, material, expected] */
    var U0 = Math.fround(0.42), cases = [];
    function material(fin, v) {   /* body / barbels: v = .5(1 - rho sin(theta)); the fins: v itself */
      if (fin === 0 || fin === 7) return [U0, Math.fround(Math.asin(1 - 2 * v)), 1, 1000];
      return [U0, Math.fround(v), 0, 1000];
    }
    function vOf(fin, m) { return fin === 0 || fin === 7 ? 0.5 * (1 - m[2] * Math.sin(m[1])) : m[1]; }
    function lit(b, fin) { var h = fragWet(fin); return [b[0] * FRAG_MUL[0] + h[0], b[1] * FRAG_MUL[1] + h[1], b[2] * FRAG_MUL[2] + h[2]]; }
    var skin = [0.13, 0.43, 0.71].map(function (hue) {
      var g = []; for (var j = 0; j < EA.STRIDE; j++) g.push(Math.fround(0.5));
      g[0] = Math.fround(hue); g[1] = Math.fround(0.7); g[2] = Math.fround(0.6);
      return g;
    });
    Object.keys(FRAG_PALETTES).forEach(function (pal) {
      FRAG_PALETTES[pal].forEach(function (rgb) {
        for (var fin = 0; fin < 8; fin++) [0, 0.5, 1].forEach(function (v) {
          var m = material(fin, v);
          cases.push({ mode: "recolour", palette: pal, colourBy: 1, fin: fin, packed: rgb, row: skin[0], lam: 4, m: m,
                       want: fin === 4 ? FRAG_EYE : lit(recolourBase(rgb, fin, vOf(fin, m)), fin) });
        });
      });
    });
    skin.forEach(function (row, i) {
      [0, 0.5, 1].forEach(function (v) {
        var m = material(0, v), out = [0, 0, 0];
        EA.flankAt(EA.decode(row, 4), U0, vOf(0, m), out);
        cases.push({ mode: "appearance", palette: "skin " + i, colourBy: 0, fin: 0, packed: PATH_COLOURS[i], row: row, lam: 4, m: m, want: lit(out, 0) });
      });
    });

    var S = 17, tex = gl.createTexture(), fb = gl.createFramebuffer(), vao = gl.createVertexArray(), quad = gl.createBuffer(), pbo = gl.createBuffer();
    function cleanup() {
      gl.bindBuffer(gl.COPY_READ_BUFFER, null);
      gl.deleteTexture(tex); gl.deleteFramebuffer(fb); gl.deleteVertexArray(vao); gl.deleteBuffer(quad); gl.deleteBuffer(pbo); gl.deleteProgram(prog);
    }
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, S, S, 0, gl.RGBA, gl.FLOAT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    var fbs = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (fbs !== gl.FRAMEBUFFER_COMPLETE) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); cleanup(); return Promise.resolve({ error: "the float target is incomplete (" + fbs + ")" }); }
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "aXY");
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.useProgram(prog);
    function uni(name) { return gl.getUniformLocation(prog, name); }
    var W = CLARITY;   /* realistic water: the [0] column */
    gl.uniform3fv(uni("uLight"), [0, 1, 0]); gl.uniform1f(uni("uTime"), 0); gl.uniform3fv(uni("uSelect"), C.select);
    gl.uniform3fv(uni("uFog"), W.fog[0]); gl.uniform1f(uni("uFogDensity"), 0);
    gl.uniform1f(uni("uDepth"), 240); gl.uniform1f(uni("uLightOn"), 0); gl.uniform1f(uni("uL0"), 1); gl.uniform1f(uni("uKWater"), 0);
    gl.uniform3fv(uni("uDeepTint"), W.deepTint[0]); gl.uniform1f(uni("uDeepDim"), W.deepDim[0]); gl.uniform3fv(uni("uDeepAdd"), W.deepAdd[0]);
    gl.uniform1f(uni("uLKeep"), W.lKeep[0]); gl.uniform1f(uni("uFloorMin"), W.floorMin[0]); gl.uniform1f(uni("uBack"), W.back[0]);
    gl.uniform3fv(uni("uAmbLo"), W.ambLo[0]); gl.uniform3fv(uni("uAmbHi"), W.ambHi[0]); gl.uniform3fv(uni("uVivid"), W.vivid[0]);
    gl.uniform1f(uni("uBeamOn"), 0); gl.uniform3fv(uni("uBeamDir"), [0, -1, 0]); gl.uniform1f(uni("uBeamTan"), 0.2); gl.uniform1f(uni("uBeamReach"), 1000);
    gl.uniform1f(uni("uIntrinsic"), 0); gl.uniform3fv(uni("cameraPosition"), [0, 10, 0]);
    gl.uniform1f(uni("uPolish"), 1);
    gl.viewport(0, 0, S, S);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.CULL_FACE); gl.colorMask(true, true, true, true);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, pbo);
    gl.bufferData(gl.PIXEL_PACK_BUFFER, cases.length * 16, gl.STREAM_READ);
    var uG = new Float32Array(36), half = Math.floor(S / 2);
    cases.forEach(function (cs, i) {
      for (var j = 0; j < 36; j++) uG[j] = j < cs.row.length ? cs.row[j] : 0;
      gl.uniform4fv(uni("uG[0]") || uni("uG"), uG); gl.uniform1f(uni("uLam"), cs.lam);
      gl.uniform4fv(uni("uMaterial"), cs.m); gl.uniform1f(uni("uFin"), cs.fin); gl.uniform1f(uni("uPacked"), cs.packed);
      gl.uniform1f(uni("uColourBy"), cs.colourBy);
      gl.clearBufferfv(gl.COLOR, 0, [-9, -9, -9, -9]);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.readPixels(half, half, 1, 1, gl.RGBA, gl.FLOAT, i * 16);
    });
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    var glErr = gl.getError();
    var sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    gl.flush();
    gl.useProgram(null); gl.bindVertexArray(null); gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (glErr !== gl.NO_ERROR) { gl.deleteSync(sync); cleanup(); return Promise.resolve({ error: "GL error " + glErr }); }
    return fenceDone(gl, sync, 10000).then(function (why) {
      gl.deleteSync(sync);
      if (why) { cleanup(); return { error: why }; }
      var px = new Float32Array(cases.length * 4);
      gl.bindBuffer(gl.COPY_READ_BUFFER, pbo);
      gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, px);
      cleanup();
      var res = { cases: cases.length, tol: FRAG_TOL, fsMutate: opts.fsMutate || "", failures: 0, nonFinite: 0, alphaBad: 0,
                  maxErr: 0, worst: "", modes: {} };
      cases.forEach(function (cs, i) {
        var got = [px[4 * i], px[4 * i + 1], px[4 * i + 2], px[4 * i + 3]];
        var md = res.modes[cs.mode] || (res.modes[cs.mode] = { cases: 0, maxErr: 0, failures: 0 });
        md.cases++;
        if (!got.every(Number.isFinite)) { res.nonFinite++; res.failures++; md.failures++; if (!res.worst) res.worst = cs.mode + " " + cs.palette + " part " + cs.fin + ": non-finite"; return; }
        var e = Math.max(Math.abs(got[0] - cs.want[0]), Math.abs(got[1] - cs.want[1]), Math.abs(got[2] - cs.want[2]));
        if (got[3] !== 1) res.alphaBad++;
        md.maxErr = Math.max(md.maxErr, e);
        if (e > FRAG_TOL || got[3] !== 1) { res.failures++; md.failures++; }
        if (e > res.maxErr) {
          res.maxErr = e;
          res.worst = cs.mode + " " + cs.palette + " #" + cs.packed.toString(16) + " part " + cs.fin + " v " + vOf(cs.fin, cs.m).toFixed(3) +
                      ": got " + got.slice(0, 3).map(function (x) { return x.toFixed(4); }).join(" ") +
                      ", want " + cs.want.map(function (x) { return x.toFixed(4); }).join(" ");
        }
      });
      res.ok = res.failures === 0 && cases.length > 0;
      return res;
    });
  }

  /* The production checks together: the fixed fixture (and the caller's
   * rows) through the vertex shader in both colour modes, and the fragment
   * shader. opts.mutate / opts.fsMutate / opts.injectSweep as above. */
  function appearancePathCheck(gl, EA, rows, lams, opts) {
    opts = opts || {};
    if (!EA || !EA.morphBuild) return Promise.resolve({ error: "web/ocean_appearance.js (with its CPU mirror) not loaded" });
    var fx = pathFixture(EA), R = fx.rows.concat(rows || []), L = fx.lams.concat(lams || []);
    var a = Object.assign({}, opts, { colourBy: 0 }), b = Object.assign({}, opts, { colourBy: 1 });
    return Promise.all([appearanceVertexCheck(gl, EA, R, L, a), appearanceVertexCheck(gl, EA, R, L, b), appearanceFragmentCheck(gl, EA, opts)])
      .then(function (r) {
        var errs = [];
        ["appearance", "recolour", "fragment"].forEach(function (k, i) { if (r[i].error) errs.push(k + ": " + r[i].error); });
        var out = { ok: errs.length === 0 && r.every(function (x) { return x.ok === true; }), fixture: fx.rows.length, fish: R.length,
                    appearance: r[0], recolour: r[1], fragment: r[2] };
        if (errs.length) out.error = errs.join("; ");
        return out;
      });
  }
  /* the vertex stage's spine and placement (CORE seg / spine / appWorld /
   * minWidth) for instance c, at uWag = 0 */
  function instSeg(inst, c, i) {
    var a = i < 2 ? inst.iA : (i < 4 ? inst.iB : inst.iC), o = 4 * c + 2 * (i % 2);
    return [a[o], a[o + 1]];
  }
  function spineCPU(inst, c, s) {
    var seg = function (i) { return instSeg(inst, c, i); };
    if (s <= 0) { var a0 = seg(0), a1 = seg(1); return [a0[0] + (a0[0] - a1[0]) * (-s), a0[1] + (a0[1] - a1[1]) * (-s)]; }
    if (s >= 5) { var b5 = seg(5), b4 = seg(4); return [b5[0] + (b5[0] - b4[0]) * (s - 5), b5[1] + (b5[1] - b4[1]) * (s - 5)]; }
    var i = Math.floor(s), t = s - i, p0 = seg(Math.max(i - 1, 0)), p1 = seg(i), p2 = seg(Math.min(i + 1, 5)), p3 = seg(Math.min(i + 2, 5));
    var t2 = t * t, t3 = t2 * t, out = [0, 0];
    for (var q = 0; q < 2; q++)
      out[q] = 0.5 * ((2 * p1[q]) + (-p0[q] + p2[q]) * t + (2 * p0[q] - 5 * p1[q] + 4 * p2[q] - p3[q]) * t2 + (-p0[q] + 3 * p1[q] - 3 * p2[q] + p3[q]) * t3);
    return out;
  }
  /* the swim pose (POSE_GLSL turnOf / bankOf, tuckOf, finPose) for instance c, uPolish 1, uWag 0 */
  function turnCPU(inst, c) {
    var p0 = instSeg(inst, c, 0), p1 = instSeg(inst, c, 1), p2 = instSeg(inst, c, 2), p3 = instSeg(inst, c, 3);
    var d0 = [p0[0] - p1[0], p0[1] - p1[1]], d1 = [p1[0] - p2[0], p1[1] - p2[1]], d2 = [p2[0] - p3[0], p2[1] - p3[1]];
    function sinT(a, b) { return (a[0] * b[1] - a[1] * b[0]) / Math.max(Math.hypot(a[0], a[1]) * Math.hypot(b[0], b[1]), 1e-6); }
    return 0.65 * sinT(d1, d0) + 0.35 * sinT(d2, d1);
  }
  function smoothCPU(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
  function tuckCPU(inst, c, turn) { return smoothCPU(0.40, 0.90, inst.iBody[4 * c + 3]) * (1 - smoothCPU(0.10, 0.35, Math.abs(turn))); }
  function finPoseCPU(EA, M, aT, pat, geo, k) {
    var fin = Math.floor(pat[0] + 0.5);
    if (fin !== 3 && fin !== 6) return geo;
    var pec = fin === 3, side = pat[2];
    var chord = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, sweep = pec ? M.pSweep : M.vSweep;
    var dih = pec ? M.pDih : -0.25 * Math.PI, kk = pec ? k : 0.5 * k;
    var w = area / (chord * Math.fround(EA.PHI_I)) * aT[1] * 4 * aT[0] * (1 - aT[0]);
    var d = [sweep, side * Math.cos(dih), Math.sin(dih)], L = Math.hypot(d[0], d[1], d[2]);
    var t = [1, 0.22 * side, -0.18], tl = Math.hypot(t[0], t[1], t[2]);
    return [0, 1, 2].map(function (i) { return geo[i] + w * (d[i] + (t[i] / tl * L - d[i]) * kk - d[i]); });
  }
  function appWorldCPU(inst, c, geo, U) {
    var Rb = inst.iBody[4 * c], u = geo[0] / inst.iX[4 * c + 2];
    var s = Math.min(3, Math.max(-1.5, u)) * 5, cc = spineCPU(inst, c, s);
    var f1 = spineCPU(inst, c, s - 0.15), f2 = spineCPU(inst, c, s + 0.15), f = [f1[0] - f2[0], f1[1] - f2[1]], fl = Math.hypot(f[0], f[1]);
    f = fl > 1e-4 ? [f[0] / fl, f[1] / fl] : [1, 0];
    var bank = Math.min(0.6, Math.max(-0.6, 1.6 * turnCPU(inst, c))), cb = Math.cos(bank), sb = Math.sin(bank);
    var lat = geo[1] * Rb, up = geo[2] * Rb, lu = [lat * cb + up * sb, up * cb - lat * sb];   /* rollTo */
    var side = [-f[1], f[0]], p = [cc[0] + side[0] * lu[0], cc[1] + side[1] * lu[0]];
    var s0 = instSeg(inst, c, 0), along = Math.hypot(cc[0] - s0[0], cc[1] - s0[1]) * (s < 0 ? -1 : 1);
    var lift = along * Math.min(1.2, Math.max(-1.2, inst.iX[4 * c]));
    var w = [p[0] - U.half[0], inst.iBody[4 * c + 1] + lu[1] + lift, p[1] - U.half[1]];
    if (U.walls) {   /* the shader's glass clamp (uWalls) */
      w[0] = Math.min(U.half[0], Math.max(-U.half[0], w[0]));
      w[2] = Math.min(U.half[1], Math.max(-U.half[1], w[2]));
    }
    return w;
  }
  function minWidthCPU(inst, c, U) {
    var hx = inst.iA[4 * c] - U.half[0], hy = inst.iBody[4 * c + 1], hz = inst.iA[4 * c + 1] - U.half[1];
    var d = Math.hypot(U.cam[0] - hx, U.cam[1] - hy, U.cam[2] - hz);
    return 0.7 * Math.max(1, d) / Math.max(1e-3, inst.iBody[4 * c] * U.px);
  }
  /* one template's feedback against the CPU mirror. only: [c0, c1) the fish
   * compared (all when absent); names: the captured components' names */
  function compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names) {
    var V = jb.tpl.verts, rings = { ringT: Array.prototype.slice.call(jb.ringT, 0, jb.tpl.ringT.length), half: jb.tpl.half };
    var r = { verts: V, maxWorld: 0, maxMat: 0, maxMar: 0, maxDecode: 0, partBad: 0, nan: 0, fins: {}, worst: "" }, worstE = 0;
    var VN = ["vG0", "vG1", "vG2", "vG3", "vG4", "vG5", "vG6", "vG7", "vAux", "vMeta"];
    var c0 = only ? only[0] : 0, c1 = only ? only[1] : n;
    for (var c = c0; c < c1; c++) {
      var lam = Math.fround(lams[c]), M = EA.morphDecode(rows[c], lam), P = U.colourBy ? null : EA.patternVaryings(rows[c], lam), minW = minWidthCPU(inst, c, U);
      var tuck = tuckCPU(inst, c, turnCPU(inst, c));
      for (var v = 0; v < V; v++) {
        var o = (c * V + v) * NC;
        var aT = [jb.tpl.pos[4 * v], jb.tpl.pos[4 * v + 1], jb.tpl.pos[4 * v + 2], jb.tpl.pos[4 * v + 3]];
        var pat = [jb.tpl.pat[4 * v], jb.tpl.pat[4 * v + 1], jb.tpl.pat[4 * v + 2], jb.tpl.pat[4 * v + 3]];
        var fin = Math.floor(pat[0] + 0.5);
        r.fins[fin] = (r.fins[fin] || 0) + 1;
        var where = "fish " + c + " vertex " + v + " (part " + fin + ")";
        /* every captured component finite, before any arithmetic: |NaN - x| >
         * tol is false, and min(Infinity, 10) would hide an infinity */
        var badComponent = -1;
        for (var component = 0; component < NC; component++) {
          if (!Number.isFinite(data[o + component])) { badComponent = component; break; }
        }
        if (badComponent >= 0) {
          if (!r.nan++) r.worst = where + ": non-finite feedback component " + badComponent + " (" + (names ? names[badComponent] : "?") + ")";
          continue;
        }
        var b = EA.morphBuild(M, rings, aT, pat, 0, 0, minW), w = appWorldCPU(inst, c, finPoseCPU(EA, M, aT, pat, b.geo, tuck), U);
        var eW = Math.max(Math.abs(data[o] - w[0]), Math.abs(data[o + 1] - w[1]), Math.abs(data[o + 2] - w[2]));
        var eM = Math.max(Math.abs(data[o + 3] - b.mat[0]), Math.abs(data[o + 4] - b.mat[1]), Math.abs(data[o + 5] - b.mat[2]));
        var eR = Math.abs(Math.min(data[o + 6], 10) - Math.min(b.mar, 10));
        if (Math.abs(data[o + 7] - pat[0]) > 1e-6 || Math.abs(data[o + 8] - pat[2]) > 1e-6 || data[o + 9] !== inst.iBody[4 * c + 2] || data[o + 10] !== inst.iX[4 * c + 3]) r.partBad++;
        var eD = 0;
        if (P) for (var q = 0; q < VN.length; q++) for (var k = 0; k < 4; k++) {   /* appearance mode: the decoded pattern */
          var g = data[o + 11 + 4 * q + k], ref = P[VN[q]][k], d = Math.abs(g - ref);
          if (q === 0 && k === 0) d = Math.min(d, 1 - d);   /* a hue: circular */
          eD = Math.max(eD, d / Math.max(1, Math.abs(ref)));
        }
        if (![eW, eM, eR, eD].every(Number.isFinite)) { if (!r.nan++) r.worst = where + ": NaN"; continue; }
        r.maxWorld = Math.max(r.maxWorld, eW); r.maxMat = Math.max(r.maxMat, eM);
        r.maxMar = Math.max(r.maxMar, eR); r.maxDecode = Math.max(r.maxDecode, eD);
        var score = Math.max(eW / PATH_TOL.world, eM / PATH_TOL.mat, eR / PATH_TOL.mar, eD / PATH_TOL.decode);
        if (score > worstE && !r.nan) { worstE = score; r.worst = where + ": world " + eW.toExponential(2) + ", mat " + eM.toExponential(2) + ", mar " + eR.toExponential(2) + ", decode " + eD.toExponential(2); }
      }
    }
    r.pass = !r.nan && r.maxWorld <= PATH_TOL.world && r.maxMat <= PATH_TOL.mat && r.maxMar <= PATH_TOL.mar && r.maxDecode <= PATH_TOL.decode && r.partBad === 0;
    return r;
  }

  var FLOOR_VS = [
    "varying vec3 vWorld;",
    "void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;",
    "  gl_Position = projectionMatrix * viewMatrix * w; }"
  ].join("\n");
  /* The seabed: sand under deep water, procedural and non-repeating: every
   * noise is value noise on a sin-free hash, each octave on its own rotated,
   * offset lattice, so nothing tiles or lines up. Three octaves of a
   * four-channel noise (broad L, mid M, small S, with their derivatives) drive:
   *  - tone: broad soft drifts of lighter and darker sand, a faint drift
   *    toward grey, a mid-scale mottle and, up close, a fine one
   *  - ripples: two trains ~50 degrees apart, each domain-warped by all three
   *    octaves, so crests curve, kink and bunch and their spacing and heading
   *    wander; each lies only in large patches (flat sand between, a crossing
   *    where they meet) and is broken into runs; an asymmetric profile with
   *    sharp crests and broad troughs
   *  - grains: up close, two jittered layers of round grains of varied size,
   *    tone and hue, a few dark specks and pale bits
   *  - light: the ripples' and grains' slopes (exact, from the noise
   *    derivatives) tilt the normal, lit from above (uLight), so they read as
   *    relief; troughs a shade darker
   *  - each detail fades out where a pixel spans a large part of its period
   *    (fwidth), so nothing aliases into lines far away or at grazing angles;
   *    far crests soften to bands, and the relief fades with distance (haze)
   * The water above tints it (uWater), then the caustics (two copies of the
   * tileable pattern sliding over each other, one rotated, both bent by the
   * broad noise, so their tiles never line up) and the fog go on top. */
  var FLOOR_FS = [
    FOG_FN,
    BEAM_FN,
    "uniform vec2 uHalf; uniform float uTime; uniform float uCausticAmt;",
    "uniform float uCausticTrue;",   /* the flashlight's: the caustics' realistic strength, in any water */
    "uniform sampler2D uCaustic; uniform vec3 uSand; uniform vec3 uSandDark; uniform vec3 uWater;",
    "uniform vec3 uCausticCol; uniform vec3 uEdge; uniform vec3 uLight;",
    "varying vec3 vWorld;",
    /* Dave Hoskins' "Hash without Sine": no patterns at large coordinates */
    "vec4 hash42(vec2 p) { vec4 p4 = fract(p.xyxy * vec4(0.1031, 0.1030, 0.0973, 0.1099));",
    "  p4 += dot(p4, p4.wzxy + 33.33); return fract((p4.xxyz + p4.yzzw) * p4.zywx); }",
    "float hash12(vec2 p) { vec3 p3 = fract(p.xyx * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }",
    /* value noise, four independent channels, with each one's derivatives along p.x (gx) and p.y (gy) */
    "vec4 vnoise4(vec2 p, out vec4 gx, out vec4 gy) {",
    "  vec2 i = floor(p), f = fract(p), u = f * f * (3.0 - 2.0 * f), du = 6.0 * f * (1.0 - f);",
    "  vec4 a = hash42(i), b = hash42(i + vec2(1.0, 0.0)), c = hash42(i + vec2(0.0, 1.0)), d = hash42(i + vec2(1.0, 1.0));",
    "  vec4 k1 = b - a, k2 = c - a, k3 = a - b - c + d;",
    "  gx = du.x * (k1 + k3 * u.y); gy = du.y * (k2 + k3 * u.x);",
    "  return a + k1 * u.x + k2 * u.y + k3 * u.x * u.y;",
    "}",
    "float vnoise1(vec2 p) { vec2 i = floor(p), f = fract(p), u = f * f * (3.0 - 2.0 * f);",
    "  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y); }",
    /* one layer of grains, q in grain cells: a round grain in each cell at a
     * random spot (wholly inside it), of random size, tone and hue; returns
     * (tone, hue, its outward direction x coverage) */
    "vec4 grains(vec2 q) {",
    "  vec4 h = hash42(floor(q) + 113.0);",
    "  vec2 v = fract(q) - 0.35 - 0.3 * h.xy;",
    "  float r = 0.2 + 0.15 * h.z, m = 1.0 - smoothstep(0.45 * r, r, length(v));",
    "  float tone = h.w < 0.035 ? -0.42 : (h.w > 0.965 ? 0.3 : (h.w - 0.5) * 0.44);",   /* dark specks, pale bits */
    "  return vec4(tone, h.z - 0.5, v / r) * m;",
    "}",
    "void main() {",
    "  vec2 p = vWorld.xz;",
    "  vec2 q = abs(p) - uHalf;",
    "  float dOut = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);",   /* > 0 outside the tank */
    "  float inside = 1.0 - smoothstep(-40.0, 120.0, dOut);",
    "  float fw = length(fwidth(p));",                                  /* world units per pixel */
    "  const mat2 R1 = mat2(0.80, 0.60, -0.60, 0.80), R2 = mat2(0.28, -0.96, 0.96, 0.28), R3 = mat2(-0.53, 0.848, -0.848, -0.53);",
    "  vec4 lx, ly, mx, my, sx, sy;",
    "  vec4 L = vnoise4(R1 * p * 0.0024 + vec2(17.3, -41.9), lx, ly);",  /* broad, ~420 across */
    "  vec4 M = vnoise4(R2 * p * 0.0075 + vec2(-7.1, 23.4), mx, my);",   /* mid, ~130 */
    "  vec4 S = vnoise4(R3 * p * 0.031 + vec2(5.7, 3.1), sx, sy);",      /* small, ~32 */
    /* the ripple trains' warps (x: the first, y: the second) and their
     * gradients: d/dp n(R p f) = f (grad n) R */
    "  float w1 = 130.0 * L.x + 38.0 * M.x + 7.0 * S.x, w2 = 110.0 * L.y + 32.0 * M.y + 6.0 * S.y;",
    "  vec2 g1 = 0.312 * (vec2(lx.x, ly.x) * R1) + 0.285 * (vec2(mx.x, my.x) * R2) + 0.217 * (vec2(sx.x, sy.x) * R3);",
    "  vec2 g2 = 0.264 * (vec2(lx.y, ly.y) * R1) + 0.24 * (vec2(mx.y, my.y) * R2) + 0.186 * (vec2(sx.y, sy.y) * R3);",
    "  const vec2 D1 = vec2(0.82, 0.57), D2 = vec2(0.11, 0.99);",
    "  const float K1 = 6.2831 / 17.0, K2 = 6.2831 / 12.5;",           /* crests ~17 and ~12.5 apart */
    "  float t1 = K1 * (dot(p, D1) + w1), t2 = K2 * (dot(p, D2) + w2);",
    "  g1 = K1 * (D1 + g1); g2 = K2 * (D2 + g2);",                      /* each phase's gradient */
    /* ripple fields in broad patches (stronger on lighter sand), flat sand
     * between; which train in mid patches (both where they meet); crests
     * broken into runs; gone where a pixel spans much of a period */
    "  float haze = (1.0 - smoothstep(900.0, 2800.0, length(cameraPosition - vWorld))) * mix(0.3, 1.0, inside);",   /* far off, and beyond the glass, the relief softens */
    "  float field = smoothstep(0.42, 0.70, 0.72 * L.w + 0.28 * M.x) * (0.4 + 0.6 * smoothstep(0.2, 0.7, M.z)) * haze;",
    "  float which = smoothstep(0.36, 0.64, M.w);",
    "  float a1 = field * (1.0 - which) * smoothstep(0.25, 0.65, S.z) * (1.0 - smoothstep(0.3, 1.1, fwidth(t1)));",
    "  float a2 = field * 0.75 * which * smoothstep(0.25, 0.65, S.w) * (1.0 - smoothstep(0.3, 1.1, fwidth(t2)));",
    /* the profile in s = t + 0.5 cos t (a long gentle side, a short steep one):
     * height c^2, c = (1 + cos s) / 2: sharp crests, broad troughs; eased to
     * c as a period shrinks below ~50 px (all c by ~15 px), so far crests are
     * soft bands, not thin dark lines */
    "  float s1 = t1 + 0.5 * cos(t1), c1 = 0.5 + 0.5 * cos(s1), e1 = 1.0 - smoothstep(0.12, 0.45, fwidth(t1));",
    "  float s2 = t2 + 0.5 * cos(t2), c2 = 0.5 + 0.5 * cos(s2), e2 = 1.0 - smoothstep(0.12, 0.45, fwidth(t2));",
    "  float hgt = a1 * (mix(c1, c1 * c1, e1) - 0.5 + 0.125 * e1) + a2 * (mix(c2, c2 * c2, e2) - 0.5 + 0.125 * e2);",   /* about its mean */
    "  vec2 slope = 2.0 * (a1 * mix(0.5, c1, e1) * sin(s1) * (0.5 * sin(t1) - 1.0) * g1",
    "                    + a2 * mix(0.5, c2, e2) * sin(s2) * (0.5 * sin(t2) - 1.0) * g2);",
    /* tone: broad drifts, a faint drift toward grey, mottles mid and fine */
    "  float tone = clamp(0.55 + 1.25 * (0.62 * L.z + 0.38 * M.z - 0.5), 0.0, 1.0);",
    "  vec3 base = mix(uSandDark, uSand, tone) * mix(vec3(1.0), vec3(0.94, 0.985, 1.02), smoothstep(0.35, 0.85, M.y));",
    "  float detail = 0.10 * (vnoise1(R2 * p * 0.07 + 31.0) - 0.5) * (1.0 - smoothstep(2.5, 6.0, fw))",
    "               + 0.08 * (vnoise1(R1 * p * 0.33 - 17.0) - 0.5) * (1.0 - smoothstep(0.5, 1.3, fw));",
    /* grains, up close only (none once a grain is under ~2 px) */
    "  float gA = 1.0 - smoothstep(0.08, 0.2, fw);",
    "  vec4 gr = vec4(0.0);",
    "  if (gA > 0.0) {",
    "    vec4 ga = grains(R1 * p * 4.5), gb = grains(R3 * p * 3.1 + 37.0);",
    "    gr = vec4(ga.xy + gb.xy, ga.zw * R1 + gb.zw * R3) * gA;",
    "  }",
    /* light from above on the relief: ripples, grains (domes) */
    "  slope -= 0.45 * gr.zw;",
    "  vec3 N = normalize(vec3(-slope.x, 1.0, -slope.y));",
    "  float lit = max(dot(N, uLight), 0.0) / uLight.y;",               /* 1 on flat sand */
    "  vec3 dry = base * (1.0 + detail + gr.x) * lit * (1.0 + 0.16 * hgt);",   /* the sand in clear light */
    "  dry *= vec3(1.0 + 0.06 * gr.y, 1.0, 1.0 - 0.06 * gr.y);",
    "  vec3 sand = dry * uWater;",
    "  vec3 col = sand * mix(0.36, 1.0, inside);",                      /* beyond the glass it is unlit */
    "  vec2 uv = p / 420.0 + (L.xy - 0.5) * 0.2;",
    "  float cA = texture2D(uCaustic, uv + vec2(uTime * 0.013, uTime * 0.008)).r;",
    "  float cB = texture2D(uCaustic, R1 * uv * 1.31 + vec2(-uTime * 0.010, uTime * 0.012)).r;",
    "  vec3 caus = uCausticCol * min(cA, cB) * uCausticAmt * (0.25 + 0.75 * inside) * (0.55 + 0.45 * lit);",
    "  vec3 edge = uEdge * (1.0 - smoothstep(0.0, 4.0, abs(dOut))) * 0.22;",   /* where the glass meets the floor */
    "  col += caus;",
    "  col += edge;",
    "  col = mix(col, uFog, max(fogOf(vWorld), smoothstep(0.0, 1100.0, dOut)));",
    "  float bk = beamOf(vWorld);",
    /* in the flashlight's clear light: the sand's true colour, and its caustics
     * at their realistic strength (uCausticTrue), the same in any water */
    "  if (bk > 0.0) {",
    "    vec3 causTrue = uCausticCol * min(cA, cB) * uCausticTrue * (0.25 + 0.75 * inside) * (0.55 + 0.45 * lit);",
    "    col = mix(col, dry * mix(0.36, 1.0, inside) + causTrue + edge, bk);",
    "  }",
    "  gl_FragColor = vec4(col, 1.0);",
    "}"
  ].join("\n");

  /* The surface, seen from below (from above it draws nothing, so the view
   * into the tank is unchanged). Inside Snell's window — rays within ~49
   * degrees of straight up — the sky's light comes through, brightest
   * overhead, with a bright rim at the window's edge; outside it the surface
   * mirrors the dark water. A shimmer (the caustic pattern, sliding) moves
   * over both. Additive, so it only ever adds light. */
  var SURF_FS = [
    FOG_FN,
    "uniform vec2 uHalf; uniform float uTime; uniform sampler2D uCaustic;",
    "uniform vec3 uSky; uniform vec3 uMirror;",
    "varying vec3 vWorld;",
    "void main() {",
    "  if (cameraPosition.y >= vWorld.y) discard;",
    "  vec3 V = normalize(vWorld - cameraPosition);",                   /* the view ray, looking up */
    "  float win = smoothstep(0.60, 0.70, V.y);",
    "  float rim = 1.0 - smoothstep(0.0, 0.035, abs(V.y - 0.66));",
    "  vec2 uv = vWorld.xz / 150.0;",
    "  float c1 = texture2D(uCaustic, uv + vec2(uTime * 0.021, -uTime * 0.016)).r;",
    "  float c2 = texture2D(uCaustic, uv * 0.73 + vec2(-uTime * 0.017, uTime * 0.019)).r;",
    "  float sh = 0.3 * (c1 + c2) + 0.8 * min(c1, c2);",                /* soft swell plus a bright network */
    "  vec2 q = abs(vWorld.xz) - uHalf;",
    "  float inside = 1.0 - smoothstep(0.0, 300.0, length(max(q, 0.0)));",
    "  vec3 col = uMirror * (0.55 + 0.9 * sh) * (1.0 - win)",
    "           + uSky * (0.40 + 0.8 * smoothstep(0.72, 1.0, V.y) + 0.75 * sh) * win",
    "           + uSky * rim * 0.4;",
    "  col *= (0.45 + 0.55 * inside) * (1.0 - fogOf(vWorld));",
    "  gl_FragColor = vec4(col, 1.0);",
    "}"
  ].join("\n");

  /* plankton glows on its own, so depth only dims and cools it a little
   * (uFoodShade: how much, and uFoodGain: its glow outside the flashlight,
   * the water's clarity; 1 = realistic) */
  var FOOD_VS = [
    "attribute float seed;",
    "uniform float uPx; uniform float uTime; uniform float uSize; uniform float uFoodShade; uniform float uFoodGain;",
    DEPTH_FN,
    BEAM_FN,
    "varying float vTw; varying float vDz;",
    "void main() {",
    "  vec4 mv = viewMatrix * vec4(position, 1.0);",
    "  gl_Position = projectionMatrix * mv;",
    "  float bk = beamOf(position);",                                   /* in the flashlight: its true colour */
    "  vDz = shadeOf(position.y) * uFoodShade * (1.0 - bk);",
    "  vTw = (0.78 + 0.22 * sin(uTime * 2.3 + seed * 6.2831)) * (1.0 - 0.3 * vDz) * (1.0 + 0.25 * bk);",
    "  if (uFoodGain != 1.0) vTw *= uFoodGain + (1.0 - uFoodGain) * bk;",
    "  gl_PointSize = max(2.0, uSize * uPx / -mv.z);",
    "}"
  ].join("\n");
  var FOOD_FS = [
    "uniform vec3 uCore; uniform vec3 uGlow;",
    "varying float vTw; varying float vDz;",
    "void main() {",
    "  float r = length(gl_PointCoord - 0.5) * 2.0;",
    "  if (r > 1.0) discard;",
    "  vec3 col = uCore * smoothstep(0.34, 0.0, r) + uGlow * pow(1.0 - r, 2.4) * 0.6;",
    "  col = mix(col, col.gbr * vec3(0.55, 0.9, 1.0), 0.45 * vDz);",
    "  gl_FragColor = vec4(col * vTw, 1.0);",
    "}"
  ].join("\n");

  /* a soft ember glow under each predator: readable at any zoom */
  var GLOW_VS = [
    "attribute float amt;",
    "uniform float uPx; uniform float uSize;",
    "varying float vAmt;",
    "void main() {",
    "  vec4 mv = viewMatrix * vec4(position, 1.0);",
    "  gl_Position = projectionMatrix * mv;",
    "  vAmt = amt;",
    "  gl_PointSize = max(6.0, uSize * uPx / -mv.z);",
    "}"
  ].join("\n");
  var GLOW_FS = [
    "uniform vec3 uCol; uniform float uTime;",
    "varying float vAmt;",
    "void main() {",
    "  float r = length(gl_PointCoord - 0.5) * 2.0;",
    "  if (r > 1.0) discard;",
    "  float pulse = 0.85 + 0.15 * sin(uTime * 4.0);",
    "  gl_FragColor = vec4(uCol * pow(1.0 - r, 2.2) * vAmt * pulse * 0.55, 1.0);",
    "}"
  ].join("\n");

  var SNOW_VS = [
    "attribute float seed;",
    "uniform float uPx; uniform float uTime; uniform vec2 uHalf; uniform float uFloorY; uniform float uFall;",
    "varying float vA;",
    "void main() {",
    "  vec3 p = position;",
    /* from just above the surface (y = 10) to just under the floor: the whole depth */
    "  float L = uFall + 40.0;",
    "  float fall = mod(uTime * (2.0 + seed * 3.0) + seed * 300.0 * (L / 170.0), L);",
    "  p.y = uFloorY + uFall + 24.0 - fall;",
    "  p.x += sin(uTime * 0.21 + seed * 40.0) * 14.0;",
    "  p.z += cos(uTime * 0.17 + seed * 23.0) * 14.0;",
    "  vec4 mv = viewMatrix * vec4(p, 1.0);",
    "  gl_Position = projectionMatrix * mv;",
    "  vA = smoothstep(0.0, 20.0, fall) * (1.0 - smoothstep(L - 30.0, L, fall)) * (0.35 + 0.65 * seed);",
    "  gl_PointSize = max(1.0, 3.2 * uPx / -mv.z);",
    "}"
  ].join("\n");
  var SNOW_FS = [
    "uniform vec3 uCol; varying float vA;",
    "void main() { float r = length(gl_PointCoord - 0.5) * 2.0; if (r > 1.0) discard;",
    "  gl_FragColor = vec4(uCol * (1.0 - r) * vA * 0.32, 1.0); }"
  ].join("\n");

  /* the glass walls (setWorld's walls on): four side panes, faint seen
   * face-on and brighter at grazing angles (the rim), a little fainter toward
   * the floor and at the surface / floor seams; blended over the water and
   * never written to the depth buffer (fish in front stay in front) */
  var GLASS_VS = [
    "varying vec3 vWorld; varying vec3 vN;",
    "void main() {",
    "  vec4 w = modelMatrix * vec4(position, 1.0);",
    "  vWorld = w.xyz; vN = normal;",
    "  gl_Position = projectionMatrix * viewMatrix * w;",
    "}"
  ].join("\n");
  var GLASS_FS = [
    "uniform vec3 uCol; uniform float uFloorY;",
    "varying vec3 vWorld; varying vec3 vN;",
    "void main() {",
    "  vec3 v = normalize(cameraPosition - vWorld);",
    "  float c = abs(dot(normalize(vN), v));",
    "  float rim = pow(1.0 - c, 4.0);",
    "  float h = clamp(vWorld.y / uFloorY, 0.0, 1.0);",
    "  float seam = smoothstep(0.0, 6.0, -vWorld.y) * smoothstep(0.0, 6.0, vWorld.y - uFloorY);",
    "  float a = (0.035 + 0.26 * rim) * (1.0 - 0.4 * h) * (0.4 + 0.6 * seam);",
    "  gl_FragColor = vec4(uCol, a);",
    "}"
  ].join("\n");

  var LINE_VS = [
    "attribute float alpha;", "varying float vA;",
    "void main() { vA = alpha; gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0); }"
  ].join("\n");
  var LINE_FS = [
    "uniform vec3 uCol; varying float vA;",
    "void main() { gl_FragColor = vec4(uCol * vA, 1.0); }"
  ].join("\n");

  var RING_VS = [
    "varying vec2 vUv;",
    "void main() { vUv = uv; gl_Position = projectionMatrix * viewMatrix * modelMatrix * vec4(position, 1.0); }"
  ].join("\n");
  var RING_FS = [
    "uniform vec3 uCol; uniform float uTime; uniform float uStrength;",
    "varying vec2 vUv;",
    "void main() {",
    "  float r = length(vUv - 0.5) * 2.0;",
    "  float ring = 1.0 - smoothstep(0.0, 0.07, abs(r - 0.72));",
    "  float wave = fract(uTime * 0.6);",
    "  float pulse = (1.0 - smoothstep(0.0, 0.05, abs(r - (0.72 + wave * 0.28)))) * (1.0 - wave);",
    "  float a = (ring + pulse * 0.6) * uStrength;",
    "  if (a < 0.01) discard;",
    "  gl_FragColor = vec4(uCol * a, 1.0);",
    "}"
  ].join("\n");

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
    /* the gene texture's uploads as three performed them (DataTexture.onUpdate),
     * kept with or without a profiler: the live-texture probe asserts it
     * caused none */
    var geneIO = { uploads: 0, bytes: 0, allocs: 0 };
    /* test-only: holdGeneUploads leaves the gene texture's upload out, so a
     * stale texture can be shown to fail appearanceTextureParity */
    var testFaults = { holdGeneUploads: false };
    /* the shaders write sRGB as-is, but three colour-manages the clear colour:
     * hand it over as sRGB ("srgb" = THREE.SRGBColorSpace) so the water above
     * the horizon (seen from a low camera) is the fog colour, not a pale teal */
    renderer.setClearColor(new THREE.Color().setRGB(C.fog[0], C.fog[1], C.fog[2], "srgb"), 1);
    var lost = false;
    canvas.addEventListener("webglcontextlost", function (e) { e.preventDefault(); lost = true; });
    canvas.addEventListener("webglcontextrestored", function () { lost = false; });

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
    var polishWant = true;   /* the swim polish (setPolish; polishUniform) */
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
      uWalls: { value: 0 },
      /* the swim polish (POSE_GLSL, POLISH_FN): 1 from detail 2 up (setQuality), 0 below */
      uPolish: { value: 1 }
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

    /* fish + predators: instanced templates sharing one shader */
    var fishUniforms = beamUniforms({
      uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
      uLight: common.uLight, uWag: { value: reduced ? 0 : 1 }, uSelect: { value: v3(C.select) },
      uDepth: common.uDepth, uLightOn: common.uLightOn, uL0: common.uL0, uKWater: common.uKWater,
      uWalls: common.uWalls, uPolish: common.uPolish
    });
    var fishMat = new THREE.ShaderMaterial({ vertexShader: FISH_VS, fragmentShader: FISH_FS,
                                             uniforms: fishUniforms, side: THREE.DoubleSide });
    var shadowMat = new THREE.ShaderMaterial({
      vertexShader: SHADOW_VS, fragmentShader: SHADOW_FS,
      uniforms: { uHalf: common.uHalf, uTime: common.uTime, uWag: fishUniforms.uWag, uLight: common.uLight,
                  uFloorY: common.uFloorY, uDepth: common.uDepth, uFog: common.uFog, uFogDensity: common.uFogDensity,
                  uAlpha: { value: 0.40 }, uWalls: common.uWalls, uPolish: common.uPolish },
      transparent: true, depthWrite: true, depthFunc: THREE.LessDepth, side: THREE.DoubleSide
    });

    /* One instanced kind: template + six per-instance attributes (iX: the
     * pitch). The geometry is rebuilt (and the old one disposed) only when it
     * has to grow. */
    function Kind(pred) {
      var tpl = fishTemplate(pred);
      var self = { cap: 0, n: 0, geo: null, mesh: null, shadow: null, attrs: null, verts: tpl.pos.length / 3, tris: tpl.idx.length / 3 };
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
          self.mesh = new THREE.Mesh(g, fishMat);
          self.shadow = new THREE.Mesh(g, shadowMat);
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
      self.commit = function (n) {
        self.n = n;
        self.geo.instanceCount = n;
        Object.keys(self.attrs).forEach(function (name) {
          var a = self.attrs[name];
          a.clearUpdateRanges();
          a.addUpdateRange(0, n * 4);
          a.needsUpdate = true;
        });
        self.mesh.visible = n > 0;
        self.shadow.visible = n > 0 && quality >= 2;
      };
      self.ensure(pred ? 64 : 2048);
      return self;
    }
    var fish = Kind(false), preds = Kind(true);

    /* The appearance genome's fish (built on the first snapshot with s.app;
     * null without web/ocean_appearance.js or float textures): the M1
     * template at two qualities (medium; coarse while the tank's detail is
     * below 3), the barbel strips as a second instanced draw sharing every
     * instance attribute, and a fish's 63 genes in a RGBA32F texture (16
     * texels a fish, 512 wide). Rebuilt only when it has to grow. appSkin
     * (setAppearance): the skin from the genes, else the family / brain colour. */
    var EA = window.EvoAppearance || null;
    var appSkin = false, appStatus = EA ? "ready" : "web/ocean_appearance.js not loaded";
    var appKind = null;
    function AppKind() {
      var sh = appearanceShaders(EA);
      var tpls = { medium: EA.buildTemplate("medium"), coarse: EA.buildTemplate("coarse") };
      var barbTpl = EA.buildBarbels("medium");
      var U = beamUniforms({
        uHalf: common.uHalf, uTime: common.uTime, uFog: common.uFog, uFogDensity: common.uFogDensity,
        uLight: common.uLight, uWag: fishUniforms.uWag, uSelect: fishUniforms.uSelect,
        uDepth: common.uDepth, uLightOn: common.uLightOn, uL0: common.uL0, uKWater: common.uKWater,
        uIntrinsic: { value: 0 }, uPxPerUnit: { value: 500 }, uColourBy: { value: 0 },
        uGenes: { value: null }, uRingT: { value: new Float32Array(16) }, uRingN: { value: 0 }, uHalfRing: { value: 4 },
        uWalls: common.uWalls, uPolish: common.uPolish
      });
      var mat = new THREE.ShaderMaterial({ vertexShader: sh.vs, fragmentShader: sh.fs, uniforms: U, side: THREE.DoubleSide });
      var shadowU = { uHalf: common.uHalf, uTime: common.uTime, uWag: fishUniforms.uWag, uLight: common.uLight,
                      uFloorY: common.uFloorY, uDepth: common.uDepth, uFog: common.uFog, uFogDensity: common.uFogDensity,
                      uAlpha: shadowMat.uniforms.uAlpha, uPxPerUnit: U.uPxPerUnit,
                      uGenes: U.uGenes, uRingT: U.uRingT, uRingN: U.uRingN, uHalfRing: U.uHalfRing, uWalls: common.uWalls,
                      uPolish: common.uPolish };
      var shMat = new THREE.ShaderMaterial({ vertexShader: sh.shadowVs, fragmentShader: SHADOW_FS, uniforms: shadowU,
                                             transparent: true, depthWrite: true, depthFunc: THREE.LessDepth, side: THREE.DoubleSide });
      var self = { cap: 0, n: 0, lod: "", attrs: null, geo: null, bgeo: null, mesh: null, bmesh: null, shadow: null,
                   tex: null, texData: null, mat: mat, shaders: sh, barbels: false, tpls: tpls, barbTpl: barbTpl, planBytes: 0 };
      var INST = ["iA", "iB", "iC", "iBody", "iX"];
      self.inst = INST;   /* the instance attributes the probes share */
      /* three uploaded the gene texture (DataTexture.onUpdate): the pending
       * upload's bytes (a number: nothing allocated a frame) */
      function onGeneUpload() {
        var bytes = self.planBytes || self.texData.byteLength;
        self.planBytes = 0;
        geneIO.uploads++; geneIO.bytes += bytes;
        profiler.add(PK.geneUploads, 1); profiler.add(PK.geneUploadBytes, bytes);
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
      function build(cap, lod) {
        var at = {};
        INST.forEach(function (name) {
          var a = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4);
          a.setUsage(THREE.DynamicDrawUsage);
          at[name] = a;
        });
        var g = geometry(tpls[lod], at), bg = barbTpl ? geometry(barbTpl, at) : null;
        var rows = genesRows(cap);   /* 16 texels a fish */
        var data = new Float32Array(GENES_W * rows * 4);
        /* RGBA32F, nearest, no mipmaps (three's RGBAFormat 1023, FloatType 1015,
         * NearestFilter 1003: the trimmed bundle does not export the names) */
        var tex = new THREE.DataTexture(data, GENES_W, rows, 1023, 1015);
        tex.magFilter = tex.minFilter = 1003;
        tex.generateMipmaps = false;
        tex.needsUpdate = true;
        tex.onUpdate = onGeneUpload;
        self.planBytes = data.byteLength;   /* its allocation's upload */
        geneIO.allocs++;
        profiler.add(PK.texAllocs, 1); profiler.add(PK.instAllocBytes, INST.length * cap * 16);
        if (self.geo) {
          self.geo.dispose(); if (self.bgeo) self.bgeo.dispose(); self.tex.dispose();
          self.mesh.geometry = g; self.shadow.geometry = g;
          if (self.bmesh && bg) self.bmesh.geometry = bg;
        } else {
          self.mesh = new THREE.Mesh(g, mat);
          self.shadow = new THREE.Mesh(g, shMat);
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
        U.uGenes.value = tex;
        setRings(tpls[lod]);
        self.geo = g; self.bgeo = bg; self.attrs = at; self.cap = cap; self.lod = lod; self.tex = tex; self.texData = data;
      }
      self.ensure = function (n, lod) {
        if (n <= self.cap && lod === self.lod) return;
        var cap = Math.max(256, self.cap);
        while (cap < n) cap *= 2;
        build(cap, lod);
      };
      self.commit = function (n, barbels) {
        self.n = n;
        self.geo.instanceCount = n;
        if (self.bgeo) self.bgeo.instanceCount = n;
        Object.keys(self.attrs).forEach(function (name) {
          var a = self.attrs[name];
          a.clearUpdateRanges();
          a.addUpdateRange(0, n * 4);
          a.needsUpdate = true;
        });
        /* the gene texture's upload: the whole texture every frame (one full
         * upload, no ranges); planBytes is what onGeneUpload counts */
        var tg = profiler.beginCpu();
        if (!testFaults.holdGeneUploads) {
          self.planBytes = self.texData.byteLength;
          self.tex.needsUpdate = true;
        }
        profiler.endCpu(SP.geneRanges, tg);
        if (profiler.active) {
          profiler.count(PK.instBytes, INST.length * n * 16); profiler.count(PK.geneDirtySlots, n);
          profiler.count(PK.geneRanges, 0); profiler.count(PK.texCapacity, self.cap);
        }
        self.mesh.visible = n > 0;
        self.shadow.visible = n > 0 && quality >= 2;
        if (self.bmesh) self.bmesh.visible = n > 0 && !!barbels && self.lod === "medium";
      };
      self.hide = function () { if (self.mesh) { self.mesh.visible = self.shadow.visible = false; if (self.bmesh) self.bmesh.visible = false; } };
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
     * appearance genome, one row per fish, and the kind could be built), in
     * every colour mode; the skin is appSkin's */
    function appearanceDrawn(s) {
      if (!EA || !s.app || s.app.length < s.n * EA.STRIDE) return false;
      if (!appKind) {
        try { appKind = AppKind(); clarityUniforms(appKind.mat.uniforms); appStatus = "drawing"; }
        catch (e) { appStatus = "unavailable: " + (e && e.message || e); EA = null; console.warn("evo_boids: appearance renderer", e); return false; }
      }
      return true;
    }
    /* Each fish's swimming speed, for the swim pose (iBody.w: the paired
     * fins' fold, finPose): its head's travel since the last drawn frame over
     * the simulated time between them (ticks x SIM_DT), / 150 (the engine's
     * default top speed), smoothed over ~0.3 simulated seconds; matched to the
     * last frame's fish by id with a merge (both lists in the engine's order,
     * ids rising; nothing allocated a frame), a fish not matched (born, or a
     * new world) starting at a cruising 0.55. Paused it holds, so a still
     * picture keeps its pose; a jump (a wrap, a Turbo run) keeps the old value.
     * Display only: nothing here reaches the simulation. */
    var SIM_DT = 0.016;   /* oc_step's fixed step (web/ocean.js DT) */
    function swimBufs(cap) { return { n: 0, epoch: -1, tick: 0, ids: new Float64Array(cap), x: new Float32Array(cap), y: new Float32Array(cap), v: new Float32Array(cap) }; }
    var swimA = swimBufs(2048), swimB = swimBufs(2048);
    function fillApp(s, selIdx, hovIdx) {
      var n = s.n, lod = quality >= 3 ? "medium" : "coarse";
      appKind.ensure(n, lod);
      var at = appKind.attrs;
      var A = at.iA.array, B = at.iB.array, Cc = at.iC.array, BODY = at.iBody.array, X = at.iX.array;
      var T = appKind.texData, R = s.app, ST = EA.STRIDE, MO = EA.MO;
      var segs = s.segs, cols = s.colors, body = s.body, ids = s.ids, depth = s.depth, vz = s.vz;
      if (!heights || heights.length < n) heights = new Float32Array(Math.max(n, 2048));
      var xs = SX, ys = SY, barbels = false;
      var SP0 = swimA, SP1 = swimB.ids.length >= n ? swimB : (swimB = swimBufs(Math.max(2048, 2 * n)));
      var tick = s.stats ? s.stats[1] : 0, dT = SP0.epoch === s.worldEpoch ? tick - SP0.tick : 0, sj = 0;
      if (SP0.epoch !== s.worldEpoch) SP0.n = 0;
      var sa = dT > 0 && dT <= 30 ? 1 - Math.exp(-dT * SIM_DT / 0.3) : 0, sinv = sa > 0 ? 1 / (150 * dT * SIM_DT) : 0;
      var sjump = (3.5 * dT + 5) * (3.5 * dT + 5);
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
        /* the swimming speed (above): this fish in the last frame's list */
        var sv = 0.55, hx = segs[b], hy = segs[b + 1];
        while (sj < SP0.n && SP0.ids[sj] < id) sj++;
        if (sj < SP0.n && SP0.ids[sj] === id) {
          sv = SP0.v[sj];
          var ex = hx - SP0.x[sj], ey = hy - SP0.y[sj], e2 = ex * ex + ey * ey;
          if (sa > 0 && e2 < sjump) sv += (Math.min(1.5, Math.sqrt(e2) * sinv) - sv) * sa;
          sj++;
        }
        SP1.ids[c] = id; SP1.x[c] = hx; SP1.y[c] = hy; SP1.v[c] = sv;
        BODY[o + 3] = sv;
        var t = vz ? vz[c] : 0;
        X[o] = t === t ? t : 0; X[o + 1] = hash01(id);
        X[o + 2] = 20 * size * elong / BODY[o];   /* lambda: body length / radius */
        X[o + 3] = cols ? cols[3 * c] * 65536 + cols[3 * c + 1] * 256 + cols[3 * c + 2] : 0;   /* the family / brain colour */
      }
      SP1.n = n; SP1.epoch = s.worldEpoch; SP1.tick = tick;
      swimA = SP1; swimB = SP0;
      /* the genes, by draw index: 16 texels a fish, the 63 genes and one zero */
      var tg = profiler.beginCpu();
      for (c = 0; c < n; c++) {
        packGenes(T, R, ST * c, c, ST);
        if (R[ST * c + MO + 26] > 0.2) barbels = true;
      }
      profiler.endCpu(SP.appearanceRows, tg);
      var tanHalf = Math.tan(camera.fov * Math.PI / 360);
      appKind.mat.uniforms.uPxPerUnit.value = ch / (2 * tanHalf);
      appKind.mat.uniforms.uColourBy.value = appSkin ? 0 : 1;
      appKind.commit(n, barbels);
      if (profiler.active) {
        var tp = appKind.tpls[appKind.lod];
        profiler.count(PK.lod, appKind.lod === "medium" ? 2 : 1); profiler.count(PK.bodyInst, n);
        profiler.count(PK.shadowInst, appKind.shadow.visible ? n : 0); profiler.count(PK.barbelInst, appKind.bmesh && appKind.bmesh.visible ? n : 0);
        profiler.count(PK.tplVerts, tp.verts); profiler.count(PK.tplTris, tp.idx.length / 3);
        profiler.count(PK.geneSrcBytes, n * ST * 4); profiler.count(PK.genePadBytes, n * 4);
      }
    }
    var appDrawn = false;   /* this frame drew the appearance fish (the probes need it) */
    function fillFish(s, selIdx, hovIdx) {
      appDrawn = appearanceDrawn(s);
      if (appDrawn) {
        fillApp(s, selIdx, hovIdx);
        fish.commit(0);
        return;
      }
      if (appKind) appKind.hide();
      var n = s.n;
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
      }
      fish.commit(n);
      if (profiler.active) {
        profiler.count(PK.lod, 0); profiler.count(PK.bodyInst, n); profiler.count(PK.barbelInst, 0);
        profiler.count(PK.shadowInst, fish.shadow.visible ? n : 0);
        profiler.count(PK.tplVerts, fish.verts); profiler.count(PK.tplTris, fish.tris);
        profiler.count(PK.instBytes, 6 * n * 16);
      }
    }

    /* Predators carry only a position: a short history of where each one has
     * been becomes its spine, so it bends through its turns like the fish. */
    var predTrails = [];
    function fillPreds(s) {
      var n = s.pc;
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
        if (i < GLOW_MAX) {
          var gp = glowGeo.attributes.position.array, ga = glowGeo.attributes.amt.array;
          gp[3 * i] = x - halfW; gp[3 * i + 1] = py - 2; gp[3 * i + 2] = y - halfH;
          ga[i] = hunting ? 1 : 0.35;
        }
      }
      preds.commit(n);
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

    /* GPU == CPU (the gallery's K12): each row's canonical flank chart,
     * rendered unlit and unfiltered (uIntrinsic = 1) into a float target and
     * read back, against the CPU mirror EvoAppearance.flankAt at every pixel
     * centre. Raw WebGL2 on three's context (the same GLSL as the fish, with
     * its own prefix; three's state is reset after). Returns the error
     * statistics (max over r, g, b per pixel). Display code only. */
    function appearanceParity(rows, lams, cellW, cellH) {
      if (!EA) return { error: appStatus };
      var gl = renderer.getContext();
      if (!gl.getExtension("EXT_color_buffer_float")) return { error: "no float render targets (EXT_color_buffer_float)" };
      var sh = appearanceShaders(EA);
      var pre = "#version 300 es\nprecision highp float;\nprecision highp int;\n";
      function compile(type, src) {
        var o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
        if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o));
        return o;
      }
      var prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, pre + "#define attribute in\n#define varying out\nin vec3 position;\n" + sh.chartVs));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, pre + "#define varying in\nout highp vec4 pcFrag;\n#define gl_FragColor pcFrag\n" + sh.chartFs));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return { error: gl.getProgramInfoLog(prog) };
      var n = rows.length, cols = Math.min(8, n), nr = Math.ceil(n / cols);
      var w = cellW || 96, h = cellH || 48, TW = cols * w, TH = nr * h;
      var tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, TW, TH, 0, gl.RGBA, gl.FLOAT, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      var fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      var vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      var bufs = [];
      function attr(name, data, size, divisor) {
        var loc = gl.getAttribLocation(prog, name);
        if (loc < 0) return;
        var b = gl.createBuffer(); bufs.push(b);
        gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(loc, divisor);
      }
      attr("position", new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), 3, 0);
      var names = ["iG0", "iG1", "iG2", "iG3", "iG4", "iG5", "iG6", "iCol", "iX", "iCell"], arr = {};
      names.forEach(function (nm) { arr[nm] = new Float32Array(n * 4); });
      for (var k = 0; k < n; k++) {
        var R = rows[k], o = 4 * k;
        for (var q = 0; q < 7; q++) for (var c = 0; c < 4; c++) arr["iG" + q][o + c] = R[4 * q + c];
        arr.iCol[o] = R[28]; arr.iCol[o + 1] = R[29]; arr.iCol[o + 2] = R[30]; arr.iCol[o + 3] = 0;
        arr.iX[o] = 0; arr.iX[o + 1] = R[31]; arr.iX[o + 2] = R[32]; arr.iX[o + 3] = lams[k];
        var cx = k % cols, cy = Math.floor(k / cols);
        arr.iCell[o] = -1 + 2 * cx / cols; arr.iCell[o + 1] = -1 + 2 * cy / nr; arr.iCell[o + 2] = 2 / cols; arr.iCell[o + 3] = 2 / nr;
      }
      names.forEach(function (nm) { attr(nm, arr[nm], 4, 1); });
      gl.useProgram(prog);
      gl.uniform1f(gl.getUniformLocation(prog, "uIntrinsic"), 1);
      gl.viewport(0, 0, TW, TH);
      gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.CULL_FACE);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, n);
      var px = new Float32Array(TW * TH * 4);
      gl.readPixels(0, 0, TW, TH, gl.RGBA, gl.FLOAT, px);
      gl.bindVertexArray(null); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.deleteVertexArray(vao); bufs.forEach(function (b) { gl.deleteBuffer(b); });
      gl.deleteFramebuffer(fb); gl.deleteTexture(tex); gl.deleteProgram(prog);
      renderer.resetState();
      var errs = [], sum = 0, maxErr = 0, over = 0, out = [0, 0, 0], worst = "";
      for (k = 0; k < n; k++) {
        var D = EA.decode(rows[k], lams[k]), x0 = (k % cols) * w, y0 = Math.floor(k / cols) * h;
        for (var j = 0; j < h; j++) for (var i = 0; i < w; i++) {
          EA.flankAt(D, (i + 0.5) / w, (j + 0.5) / h, out);
          var p = ((y0 + j) * TW + x0 + i) * 4;
          var e = Math.max(Math.abs(px[p] - out[0]), Math.abs(px[p + 1] - out[1]), Math.abs(px[p + 2] - out[2]));
          errs.push(e); sum += e; if (e > 0.002) over++;
          if (e > maxErr) { maxErr = e; worst = "row " + k + " u " + ((i + 0.5) / w).toFixed(3) + " v " + ((j + 0.5) / h).toFixed(3); }
        }
      }
      errs.sort(function (a, b) { return a - b; });
      return { fish: n, samples: errs.length, maxErr: maxErr, meanErr: sum / errs.length, p99: errs[Math.floor(errs.length * 0.99)],
               p999: errs[Math.floor(errs.length * 0.999)], over002: over / errs.length, worst: worst };
    }

    /* ---- the live gene texture, checked (appearanceTextureParity) ----
     * Right after a production draw of the appearance fish, two diagnostic
     * draws read appKind.tex itself, bound through the fish material's own
     * uGenes uniform (so three's uploader is what is tested), with the
     * production instance attributes (iX) and the same slot selector
     * (GENE_SLOT_GLSL), into RGBA32F targets (nearest, no mipmaps, no MSAA,
     * no depth) read back through pixel-pack buffers and a fence (polled,
     * 10 s; three's state is restored before anything waits):
     *   raw: every fish's 16 texels, bit for bit, against owned copies of
     *     the snapshot's 63 genes and the zero after them (never re-packed)
     *   intrinsic: pattern charts, 96 x 48 a fish, at most 64 a batch, the
     *     whole instance sequence drawn with the uncharted fish off the
     *     target, of fish on both sides of the 32-fish rows and of slot 2048,
     *     against EvoAppearance.decode / flankAt of the original rows (p99.9
     *     <= .002, nothing non-finite)
     * The probe must upload nothing: one that did would have repaired a
     * missed production upload, and that fails. expected: owned copies
     * {worldEpoch, n, ids, app, body} (EvoOcean.bench.snapshotCopy), which
     * must be the snapshot drawn; absent, that snapshot's own copies.
     * o.mutate "slot": the probes read a wrong slot; o.pendingUpload: a
     * production upload left pending (the probe would perform it); both must
     * fail. o.charts: how many fish to chart (24). A diagnostic: the frame is
     * marked, never part of a timed capture. */
    var probes = [];
    var PROBE_SENTINEL = new Float32Array([-9, -9, -9, -9]);
    var RAW_QUADS = (function () {   /* 16 pixel quads, one a gene texel */
      var pos = new Float32Array(16 * 6 * 3), tx = new Float32Array(16 * 6), Q = [[0, 0], [1, 0], [0, 1], [0, 1], [1, 0], [1, 1]];
      for (var k = 0; k < 16; k++) for (var v = 0; v < 6; v++) { var i = 6 * k + v; pos[3 * i] = Q[v][0]; pos[3 * i + 1] = Q[v][1]; tx[i] = k; }
      return { pos: pos, texel: tx };
    })();
    function appearanceTextureParity(expected, o) {
      return new Promise(function (resolve) {
        var rq = { expected: expected || null, o: o || {}, resolve: resolve };
        rq.timer = setTimeout(function () {
          var i = probes.indexOf(rq);
          if (i >= 0) { probes.splice(i, 1); resolve({ ok: false, error: "no production draw of the appearance fish within 10 s" }); }
        }, 10000);
        probes.push(rq);
      });
    }
    function failProbes(why) {
      var list = probes; probes = [];
      list.forEach(function (rq) { clearTimeout(rq.timer); rq.resolve({ ok: false, error: why }); });
    }
    function runProbes(s) {
      if (!appDrawn || !appKind || !appKind.mesh.visible) { failProbes("the appearance fish were not drawn this frame (" + appStatus + ")"); return; }
      var list = probes; probes = [];
      list.forEach(function (rq) {
        clearTimeout(rq.timer);
        var p;
        try { p = profiler.suspend(function () { return textureProbe(rq, s); }); }
        catch (e) { p = Promise.resolve({ ok: false, error: "probe: " + (e && e.message || e) }); }
        p.then(rq.resolve, function (e) { rq.resolve({ ok: false, error: "probe: " + (e && e.message || e) }); });
      });
    }
    /* the draw indices charted: both sides of the 32-fish rows and of 2048, the last, then spread */
    function chartPicks(n, want) {
      var pick = [], seen = {};
      function add(i) { if (i >= 0 && i < n && !seen[i]) { seen[i] = true; pick.push(i); } }
      [0, 1, 31, 32, 33, 63, 64, 2047, 2048, 2049, n - 1].forEach(add);
      for (var k = 1; pick.length < Math.min(want, n) && k < 64 * want; k++) add(Math.floor((k * 0.6180339887 % 1) * n));
      return pick.sort(function (a, b) { return a - b; });
    }
    function floatTarget(w, h) {
      return new THREE.WebGLRenderTarget(w, h, { type: 1015, format: 1023, minFilter: 1003, magFilter: 1003, generateMipmaps: false,
                                                 depthBuffer: false, stencilBuffer: false, samples: 0 });
    }
    function textureProbe(rq, s) {
      var o = rq.o, gl = renderer.getContext(), n = appKind.n, ST = EA.STRIDE, inst = appKind.inst;
      var res = { ok: false, worldEpoch: s.worldEpoch, tick: s.stats ? s.stats[1] : null, fish: n,
                  mutate: o.mutate || "", pendingUpload: !!o.pendingUpload, failures: [] };
      if (!THREE.WebGLRenderTarget) { res.error = "the three bundle has no WebGLRenderTarget (tools/three_bundle)"; return Promise.resolve(res); }
      /* what was drawn: owned copies, before any probe work */
      var drawnIds = Float64Array.from(s.ids.subarray(0, n));
      var exp = rq.expected || { worldEpoch: s.worldEpoch, tick: res.tick, n: n, ids: drawnIds,
                                 app: Float32Array.from(s.app.subarray(0, n * ST)), body: Float32Array.from(s.body.subarray(0, 2 * n)) };
      var why = null;
      if (exp.n !== n) why = "it has " + exp.n + " fish, " + n + " were drawn";
      else if (exp.worldEpoch !== undefined && s.worldEpoch !== undefined && exp.worldEpoch !== s.worldEpoch) why = "world epoch " + exp.worldEpoch + ", drawn " + s.worldEpoch;
      else for (var i = 0; i < n; i++) if (exp.ids[i] !== drawnIds[i]) { why = "draw " + i + " is fish " + exp.ids[i] + ", drawn " + drawnIds[i]; break; }
      if (!why && (!exp.app || exp.app.length < n * ST || !exp.body || exp.body.length < 2 * n)) why = "it has no appearance rows or bodies";
      if (why) { res.error = "the expected snapshot is not the one drawn: " + why; return Promise.resolve(res); }
      var app = exp.app instanceof Float32Array ? exp.app : Float32Array.from(exp.app), body = exp.body;
      var tex = appKind.tex;
      res.texture = { width: tex.image.width, height: tex.image.height, type: tex.type, format: tex.format,
                      internalFormat: tex.internalFormat || "RGBA32F (three: RGBAFormat + FloatType)", capacity: appKind.cap,
                      minFilter: tex.minFilter, magFilter: tex.magFilter, mipmaps: tex.generateMipmaps };
      var sh = appKind.shaders, rawVs = sh.probeRawVs, chartVs = sh.probeChartVs;
      if (o.mutate === "slot") {
        var wrong = "int appearanceSlot() { return gl_InstanceID ^ 1; }";
        rawVs = rawVs.split(GENE_SLOT_GLSL).join(wrong); chartVs = chartVs.split(GENE_SLOT_GLSL).join(wrong);
      } else if (o.mutate) { res.error = "unknown mutation " + o.mutate; return Promise.resolve(res); }
      var picks = chartPicks(n, o.charts || 24), CW = 96, CH = 48, PER = 64, COLS = 8;
      var geos = [], mats = [], rts = [], reads = [], batches = [], err = null, shaderErr = null;
      var keepRT = renderer.getRenderTarget(), keepClear = renderer.autoClear, keepOnErr = renderer.debug.onShaderError;
      var cam = new THREE.PerspectiveCamera(), up0 = geneIO.uploads;
      function geometry() {   /* shares the fish's instance attributes (and their GL buffers) */
        var g = new THREE.InstancedBufferGeometry();
        inst.forEach(function (nm) { g.setAttribute(nm, appKind.attrs[nm]); });
        g.instanceCount = n;
        geos.push(g);
        return g;
      }
      function material(vs, fs, extra) {
        var u = { uGenes: appKind.mat.uniforms.uGenes };   /* the fish material's own uniform: appKind.tex */
        Object.keys(extra).forEach(function (k) { u[k] = extra[k]; });
        var m = new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, uniforms: u, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
        mats.push(m);
        return m;
      }
      function draw(rt, g, m) {
        var mesh = new THREE.Mesh(g, m), sc = new THREE.Scene();
        mesh.frustumCulled = false; sc.add(mesh);
        renderer.setRenderTarget(rt);
        var st = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
        if (st !== gl.FRAMEBUFFER_COMPLETE) throw new Error("the probe's float target is incomplete (" + st + ")");
        renderer.state.buffers.color.setMask(true);
        renderer.state.setScissorTest(false);
        gl.clearBufferfv(gl.COLOR, 0, PROBE_SENTINEL);
        renderer.render(sc, cam);
        renderer.setRenderTarget(rt);
        var b = gl.createBuffer();   /* the target -> a pixel-pack buffer; nothing waits here */
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, b);
        gl.bufferData(gl.PIXEL_PACK_BUFFER, rt.width * rt.height * 16, gl.STREAM_READ);
        gl.readPixels(0, 0, rt.width, rt.height, gl.RGBA, gl.FLOAT, 0);
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
        reads.push(b);
        return { buf: b, w: rt.width, h: rt.height };
      }
      var raw = null;
      if (o.pendingUpload) tex.needsUpdate = true;   /* a production upload left undone */
      try {
        renderer.autoClear = false;
        renderer.debug.onShaderError = function (g, prog, vs, fs) {
          shaderErr = ((g.getShaderInfoLog(vs) || "") + " " + (g.getShaderInfoLog(fs) || "") + " " + (g.getProgramInfoLog(prog) || "")).trim() || "the probe's program did not link";
        };
        /* raw genes: 16 pixels a fish, 512 a row */
        var rawH = Math.ceil(16 * n / GENES_W), rawRT = floatTarget(GENES_W, rawH), rg = geometry();
        rts.push(rawRT);
        rg.setAttribute("position", new THREE.BufferAttribute(RAW_QUADS.pos, 3));
        rg.setAttribute("aTexel", new THREE.BufferAttribute(RAW_QUADS.texel, 1));
        raw = draw(rawRT, rg, material(rawVs, sh.probeRawFs, { uProbeSize: { value: new THREE.Vector2(GENES_W, rawH) } }));
        /* the charts, a batch of at most 64 at a time */
        var cg = geometry(), cell = new THREE.InstancedBufferAttribute(new Float32Array(n * 4), 4);
        cg.setAttribute("position", new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), 3));
        cg.setIndex([0, 1, 2, 2, 1, 3]);
        cg.setAttribute("iCell", cell);
        var cm = material(chartVs, sh.chartFs, { uIntrinsic: { value: 1 } });
        for (var b0 = 0; b0 < picks.length; b0 += PER) {
          var part = picks.slice(b0, b0 + PER), rowsN = Math.ceil(part.length / COLS), A = cell.array;
          for (var q = 0; q < n; q++) { A[4 * q] = 4; A[4 * q + 1] = 4; A[4 * q + 2] = 0; A[4 * q + 3] = 0; }   /* off the target */
          part.forEach(function (c, k) {
            var cx = k % COLS, cy = Math.floor(k / COLS);
            A[4 * c] = -1 + 2 * cx / COLS; A[4 * c + 1] = -1 + 2 * cy / rowsN; A[4 * c + 2] = 2 / COLS; A[4 * c + 3] = 2 / rowsN;
          });
          cell.needsUpdate = true;
          var rt = floatTarget(COLS * CW, rowsN * CH);
          rts.push(rt);
          batches.push({ fish: part, read: draw(rt, cg, cm) });
        }
      } catch (e) { err = e; }
      finally {
        renderer.setRenderTarget(keepRT);
        renderer.autoClear = keepClear;
        renderer.debug.onShaderError = keepOnErr;
      }
      res.extraUploads = geneIO.uploads - up0;
      var sync = err || shaderErr ? null : gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
      if (sync) gl.flush();
      function cleanup() {
        gl.bindBuffer(gl.COPY_READ_BUFFER, null);
        reads.forEach(function (b) { gl.deleteBuffer(b); });
        if (sync) gl.deleteSync(sync);
        geos.forEach(function (g) { inst.forEach(function (nm) { g.deleteAttribute(nm); }); g.dispose(); });   /* the fish keep theirs */
        mats.forEach(function (m) { m.dispose(); }); rts.forEach(function (t) { t.dispose(); });
      }
      if (err || shaderErr) { cleanup(); res.error = shaderErr ? "probe shader: " + shaderErr : "probe: " + (err.message || err); return Promise.resolve(res); }
      return fenceDone(gl, sync, 10000).then(function (why) {
        if (why) { cleanup(); res.error = why; return res; }
        function fetch(rd) {
          var px = new Float32Array(rd.w * rd.h * 4);
          gl.bindBuffer(gl.COPY_READ_BUFFER, rd.buf);
          gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, px);
          return px;
        }
        /* raw: the genes' bit patterns, then the zero */
        var rp = fetch(raw), gotU = new Uint32Array(rp.buffer), appU = new Uint32Array(app.buffer, app.byteOffset, n * ST);
        var R = { compared: n * 64, mismatches: 0, paddingMismatches: 0, nonFinite: 0, examples: [] };
        for (var c = 0; c < n; c++) for (var j = 0; j < 64; j++) {
          var gi = 64 * c + j;
          if (!Number.isFinite(rp[gi])) R.nonFinite++;
          if (j < 63) {
            if (gotU[gi] !== appU[ST * c + j]) {
              R.mismatches++;
              if (R.examples.length < 6) R.examples.push({ draw: c, id: exp.ids[c], gene: j, want: app[ST * c + j], got: rp[gi] });
            }
          } else if (gotU[gi] !== 0) R.paddingMismatches++;
        }
        res.rawGenes = R;
        /* the charts against the CPU mirror of the original rows */
        var errs = [], nonFinite = 0, over = 0, maxErr = 0, worst = "", out = [0, 0, 0];
        batches.forEach(function (bt) {
          var px = fetch(bt.read), TW = bt.read.w;
          bt.fish.forEach(function (c, k) {
            var size = body[2 * c], elong = body[2 * c + 1];
            var lam = Math.fround(20 * size * elong / Math.fround(4.6 * bodyScale(size)));   /* fillApp's iX.z */
            var D = EA.decode(app.subarray(ST * c, ST * c + ST), lam), x0 = (k % COLS) * CW, y0 = Math.floor(k / COLS) * CH;
            for (var jj = 0; jj < CH; jj++) for (var ii = 0; ii < CW; ii++) {
              EA.flankAt(D, (ii + 0.5) / CW, (jj + 0.5) / CH, out);
              var p = ((y0 + jj) * TW + x0 + ii) * 4;
              if (!Number.isFinite(px[p]) || !Number.isFinite(px[p + 1]) || !Number.isFinite(px[p + 2])) { nonFinite++; continue; }
              var e = Math.max(Math.abs(px[p] - out[0]), Math.abs(px[p + 1] - out[1]), Math.abs(px[p + 2] - out[2]));
              errs.push(e); if (e > 0.002) over++;
              if (e > maxErr) { maxErr = e; worst = "draw " + c + " (fish " + exp.ids[c] + ") u " + ((ii + 0.5) / CW).toFixed(3) + " v " + ((jj + 0.5) / CH).toFixed(3); }
            }
          });
        });
        cleanup();
        var E = Float64Array.from(errs).sort();
        res.intrinsic = { fish: picks.length, draws: picks, ids: picks.map(function (c) { return exp.ids[c]; }), samples: E.length,
                          p99: E.length ? E[Math.floor(E.length * 0.99)] : null, p999: E.length ? E[Math.floor(E.length * 0.999)] : null,
                          maxErr: maxErr, over002: E.length ? over / E.length : null, nonFinite: nonFinite, worst: worst };
        if (res.extraUploads) res.failures.push("the probe uploaded the gene texture " + res.extraUploads + "x (a production upload was pending)");
        if (R.mismatches) res.failures.push(R.mismatches + " raw gene mismatches");
        if (R.paddingMismatches) res.failures.push(R.paddingMismatches + " padding mismatches");
        if (R.nonFinite) res.failures.push(R.nonFinite + " non-finite raw components");
        if (nonFinite) res.failures.push(nonFinite + " non-finite chart pixels");
        if (!E.length || !(res.intrinsic.p999 <= 0.002)) res.failures.push("chart p99.9 " + res.intrinsic.p999 + " > .002");
        if (tex.type !== 1015 || tex.format !== 1023) res.failures.push("the gene texture is not RGBA float");
        res.ok = res.failures.length === 0;
        return res;
      });
    }
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
      polishUniform();
      resize();
      return true;
    }
    /* the swim polish: on from detail 2 up (the lowest detail, where Hold
     * 60 fps ends up on a slow device, draws the fish as before it); off
     * altogether only for measurements (setPolish, the render benchmark's A/B;
     * polishWant is set with quality, at the top) */
    function polishUniform() { common.uPolish.value = polishWant && quality >= 2 ? 1 : 0; }

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
      setPolish: function (on) { polishWant = !!on; polishUniform(); },
      polish: function () { return common.uPolish.value === 1; },
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
      /* the gene texture and its upload counts (tests: upload interception) */
      geneTexture: function () {
        return appKind ? { texture: appKind.tex, data: appKind.texData, capacity: appKind.cap, n: appKind.n,
                           uploads: geneIO.uploads, bytes: geneIO.bytes, allocs: geneIO.allocs } : null;
      },
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
    /* the shared slot selector (the probes and PR2's ownership change read it) */
    GENE_SLOT_GLSL: GENE_SLOT_GLSL
  };
})();
