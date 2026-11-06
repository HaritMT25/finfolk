// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the scene's GLSL (window.EvoOceanShaders).
 *
 * web/ocean_scene.js builds its three.js ShaderMaterials (GLSL ES 1.0 as three
 * writes it: attribute / varying, three's own uniforms and attributes:
 * position, modelMatrix, viewMatrix, projectionMatrix, cameraPosition, uv,
 * normal) from these strings, as they are:
 *   - the chunks its programs share: FOG_FN (the water's fog), BEAM_FN (the
 *     flashlight's cone of clear light), DEPTH_FN (light under water: dimmer
 *     and bluer with depth, or the engine's light field), CLARITY_FN (the
 *     water's clarity on a fish's own colour, and lit(), the one light model);
 *     each declares the uniforms it reads
 *   - the environment's programs: the seabed (FLOOR_VS, FLOOR_FS), the surface
 *     seen from below (SURF_FS, with FLOOR_VS), the plankton (FOOD_VS, FOOD_FS),
 *     the predators' ember glow (GLOW_VS, GLOW_FS), the marine snow (SNOW_VS,
 *     SNOW_FS), the glass walls (GLASS_VS, GLASS_FS), the current streaks and
 *     the selected fish's trail (LINE_VS, LINE_FS), the selection and hover
 *     rings (RING_VS, RING_FS)
 *   - the fish programs, which come in variants (P: false plain, the fish
 *     exactly as before the swim polish, its GLSL byte for byte; true full;
 *     "lite" the roll only): the swim pose's GLSL (POSE_GLSL: poseOf unpacks
 *     the float web/ocean_pose.js packs) and the polish's light (POLISH_FN);
 *     the plain fish's and the predators' (fishCore, fishVs, fishFs,
 *     shadowVs, built on first read into FISH_VS / FISH_FS [plain, full, lite] and
 *     SHADOW_VS [plain, lite] / SHADOW_FS); the appearance fish's
 *     (appearanceShaders(EA, P): its body, its shadow, and the checks' and
 *     probes' programs, around web/ocean_appearance.js's GLSL), the gene slot
 *     every gene-reading program shares (GENE_SLOT_GLSL) and the lit fish's
 *     split (LIT_SKIP, litSkip); lines() and occurrences(), the strings'
 *     helpers
 *   - the fish programs' named slots and the features that fill them
 *     (structure pass step 4a): each program is a list of parts with named
 *     slots (slot(), PROGRAMS, SLOTS: where each is, what it may read and
 *     write); program(name, parts, features, env) assembles it with the
 *     enabled features (feature(): registered and checked), core() a vertex
 *     stage's common part; parts.* the programs' parts; declarations(), the
 *     source scan the checks use. The swim polish is a feature in two modes
 *     (POLISH, polishFeature: lite, full); with no feature every program is
 *     its fallbacks' text, the plain one
 * The uniforms' values are the scene's (its colours C, the water's CLARITY,
 * setClarity, setLight, setFlashlight); only their declarations are here.
 *
 * Moved from web/ocean_scene.js unchanged, every string byte for byte (the
 * structure pass: renderer_seams_plan_codex.md, module ocean_shaders.js; the
 * GLSL that comes in no variants first, the fish programs second); the fish
 * programs then put on named slots, every variant's string still byte for
 * byte (step 4a). Strings and the functions that build them, no WebGL: node
 * can load it. Display only: the simulation never reads any of it. */
(function (root) {
  root.EvoOceanShaders = null;   /* registered at the end: a throw on the way leaves null (the scene: "failed to run") */
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

  /* ---------------- the fish programs, in their variants ---------------- */
  /* The swim polish: every fish program comes in variants, assembled from
   * the same parts (named slots, below) with the swim polish's feature in
   * one of its modes, by a flag P (plain, full, lite: the roll only, now the
   * shadows' only, and the tests'). Plain (P false: no feature) is the fish
   * exactly as before the polish, its GLSL byte for byte, and its cost: no pose read,
   * no swimming-speed history kept. Polished (P true) reads each fish's swim
   * pose from one float the CPU packs once per fish (swimPose, from the
   * spine it uploads) into an instance component the plain programs leave
   * unread and main writes 0: the appearance fish's iBody.w, the plain fish's
   * and predators' iX.y. Not an attribute of its own: one more per-instance
   * vec4 cost ~1.3 ms of GPU time at 2,000 fish on the measured Iris Xe
   * (ANGLE / D3D11), more than all the polish's light. poseOf() unpacks it
   * (exact: an integer below 2^24) into iPose, a vertex-stage global set
   * first thing in main(), shared by the body, the barbels and the shadow:
   *   x, y  the sine and cosine of the roll into the turn: the back toward
   *         the turn's centre, 1.6 x the turn (the sines of the angles between
   *         the spine's first three links, 0.65 / 0.35), at most 0.6 rad, times w;
   *         rollTo() turns a point's (side, up) offset from the spine by it,
   *         so the spine, the head (trail, rings, picking) and the pitch stay
   *         (sin in steps of 0.6 / 511, 0 exact, 10 bits; cos = sqrt(1 - sin^2))
   *   z     the paired fins' fold back along the flank (finPose; appearance
   *         fish, by the renderer's speed estimate, less in a hard turn),
   *         times w (7 bits)
   *   w     the polish's share by the fish's size on screen (poseWeight: its
   *         body radius in CSS px at its nearest depth, none under 6 px, all
   *         from 11; 7 bits, 0 exactly 0). The roll, the tail's lag, the fins'
   *         fold, the caustics and the polish's light all scale with it, so
   *         an unlit fish is drawn as the plain programs draw it. Their
   *         guards are flattened by the shader compiler (measured: a weight 0
   *         costs as much as 1), so a kind draws its full programs only while
   *         a fish of it is lit (and HOLD frames after), its plain ones
   *         otherwise (settle); with no fish able to be lit (mayLight) no
   *         pose is computed at all
   * The scene draws the polished variants from detail 2 up (setQuality;
   * setPolish for measurements), the plain one at detail 1. */
  /** @param {(string | null)[]} a */
  function lines(a) { return a.filter(function (x) { return x !== null; }).join("\n"); }
  /* how often sub occurs in s (litSkip's one main; the scene's planted faults) */
  /** @param {string} s @param {string} sub */
  function occurrences(s, sub) { return s.split(sub).length - 1; }
  var POSE_GLSL = [
    "vec4 iPose;",   /* sin, cos of the roll; the fin fold; the size weight: poseOf(the packed float), set first in main() */
    "vec4 poseOf(float p) {",
    "  float qw = mod(p, 128.0), r = floor(p / 128.0), qt = mod(r, 128.0), s = (floor(r / 128.0) - 512.0) / 511.0 * 0.6;",
    "  return vec4(s, sqrt(max(1.0 - s * s, 0.0)), qt / 127.0, qw / 127.0);",
    "}",
    "vec2 rollTo(vec2 a) { return vec2(a.x * iPose.y + a.y * iPose.x, a.y * iPose.y - a.x * iPose.x); }",
    /* the tail beat's lateral offset at u (body lengths from the head), phase
     * ph: the caudal fin's trailing edge lags (e: 0 at the peduncle .. 1 half
     * a body behind it, by the size weight), a phase lag and a second
     * harmonic; with e = 0 it is the plain beat */
    "float wagAt(float u, float ph, float R) {",
    "  float e = iPose.w * clamp(2.0 * (u - 1.0), 0.0, 1.0);",
    "  float w = sin(ph - 0.9 * e) * (1.0 + 0.25 * e);",
    "  if (e > 0.0) w += 0.14 * e * sin(2.0 * ph - 0.6);",
    "  return w * uWag * smoothstep(0.1, 1.3, u) * R * 0.3;",
    "}",
    /* faint caustic light at a point near the surface: an analytic two-wave
     * network (no texture), per vertex, fading over the top ~50 units of
     * water (e-folding 45; nothing below 178, where it is under 2 %); the
     * fragment stage keeps it to up-facing facets. Not computed at all on a
     * fish too small on screen (iPose.w 0) or deeper */
    "float causOf(vec3 w) {",
    "  if (iPose.w <= 0.0 || w.y < -178.0) return 0.0;",
    "  vec2 p = w.xz * 0.10; float t = uTime * 0.45;",
    "  float a = sin(p.x + 1.6 * sin(0.57 * p.y + t));",
    "  float b = sin(1.17 * p.y + 1.4 * sin(0.69 * p.x - 0.8 * t) + 0.5 * t);",
    "  float r = 1.0 - 0.5 * abs(a + b); r *= r;",
    "  return exp(-0.022 * max(-w.y, 0.0)) * r * r;",
    "}"
  ].join("\n");
  /* The swim polish's light (the polished fragment stages), added to lit()'s,
   * on the murky and the flashlight's clear colour alike (polishOn(b, k):
   * linear in the skin b); pw: the fish's size weight (iPose.w, flat), every
   * term times it, none computed at 0. thin: 1 on fins, less on barbels and
   * the peduncle, 0 on the body; with it the diffuse wraps a little past the
   * terminator (wrapDiff, the caller's), the sunlight on a fin's far side
   * shows through it, and a fin seen against the light glows in its own
   * colour (a view-dependent back light, no texture). A wet highlight on the
   * facet's own normal N (the one every other light term uses, so it follows
   * the bent, rolled, pitched and wall-clamped surface; it is zero where the
   * camera looks straight into the light, where the half vector vanishes),
   * and the vertex stage's caustic light, kept to up-facing facets.
   * k = (transmitted, caustic, highlight). */
  var POLISH_FN = [
    "const vec3 P_SUN = vec3(1.0, 0.96, 0.86), P_WET = vec3(1.0, 0.98, 0.92), P_CAUS = vec3(0.70, 0.95, 0.84);",
    "float wrapDiff(float nl, float thin) { float w = 0.45 * thin; return max((nl + w) / (1.0 + w), 0.0); }",
    "vec3 polishK(vec3 N, vec3 V, float thin, float nl, float pw, float caus) {",
    "  if (pw <= 0.0) return vec3(0.0);",
    "  float s = clamp(-dot(V, uLight), 0.0, 1.0); s *= s; s *= s;",   /* looking into the light */
    "  float trans = thin * (0.40 * max(-nl, 0.0) + 0.60 * s);",
    "  vec3 H = uLight + V; float h2 = dot(H, H), x = h2 > 1e-6 ? max(dot(N, H), 0.0) * inversesqrt(h2) : 0.0;",
    "  x *= x; x *= x; x *= x; x *= x; x *= x;",   /* x^32 */
    "  float sp = x * 0.30 * (1.0 - 0.5 * thin);",
    "  return pw * vec3(trans, caus * max(N.y, 0.0), sp);",
    "}",
    "vec3 polishOn(vec3 b, vec3 k) { return b * (P_SUN * k.x + P_CAUS * k.y) + P_WET * k.z; }"
  ].join("\n");

  /* ---------------- named slots, features and the assembler ----------------
   * A fish program is a list of parts: GLSL strings (null: none, as lines()
   * drops it) and named slots, slot(name, fallback). program(name, parts,
   * features, env) assembles it: each slot becomes its fallback, or the text
   * an enabled feature replaces it with, followed by what the enabled
   * features append to it, in an order of their own (the feature's order,
   * then its id: never the order they registered or were listed in); the
   * result is lines() of all that, so with no feature every program is its
   * fallbacks' text, byte for byte. A feature, feature({id, abi, targets,
   * append, replace, order, version}), names the programs it supports (targets) and,
   * slot by slot, the GLSL it appends or the GLSL that replaces the fallback
   * (or a function of the program's environment env giving it: the
   * appearance programs pass {EA}; a function that throws is reported with
   * the feature, the slot and the program). A text of "" adds no line (a
   * replacement by "" removes the fallback). Registering enables nothing: a
   * program is assembled with the feature ids it is given (an id it does
   * not target adds nothing to it). Ids are namespaced by their owner
   * ("swimPolish.full", "reef.fish") and registered once, as their script
   * loads: a Look registers its features at load, never in attach() (a
   * second registration of an id throws, so a rebuild would). The swim
   * polish is two features (swimPolish.lite, swimPolish.full; plain is
   * neither).
   * The checks are on the source, as it is assembled (a GLSL compile and
   * link stays a separate check):
   *   - the parts hold each of the program's slots (PROGRAMS) once, in its
   *     order: a missing, duplicate, unknown or misplaced slot throws
   *   - a feature's ABI is the slots' (ABI); each target is a known program;
   *     each slot it names is a known one, in one of its targets, of the kind
   *     it uses (an additive slot takes append, a replacement slot replace)
   *   - a replacement slot has one provider among the enabled features, and
   *     the replacement declares what the slot must (SLOTS[name].must)
   *   - no name declared twice in one scope (the globals; a function's top
   *     level) where a feature made one of the declarations
   * SLOTS documents each slot: where it is, what it may read, what it
   * writes. The programs with slots: the legacy fish's and the predators'
   * body (fish.vs, fish.fs) and shadow (fish.shadow.vs), a pass a look owns
   * on their instances (fish.attach.vs: the common part, the pose read, the
   * look's own main(); #47's predator faces), the appearance fish's body
   * and barbels (app.body.vs, app.body.fs: one program) and shadow
   * (app.shadow.vs). The shadows' fragment stage (SHADOW_FS), the
   * environment's programs and the probes' come in no variants and have no
   * slots. A vertex stage's common part (fishCore, appCore) is assembled
   * alone with core(): the slots it has. */
  var ABI = 1;
  var hasOwn = Object.prototype.hasOwnProperty;
  /** @param {string} m */
  function err(m) { return new Error("EvoOceanShaders: " + m); }
  /** a named slot in a program's parts; fallback: its text when no enabled feature replaces it (null: none)
   * @param {string} name @param {string | null} fallback @returns {ShaderSlot} */
  function slot(name, fallback) { return { slot: name, fallback: fallback }; }
  /** @param {"append" | "replace"} kind @param {"vs" | "fs"} stage @param {string} at @param {string[]} reads
   * @param {string[]} writes @param {string[]} [must] @returns {ShaderSlotSpec} */
  function S(kind, stage, at, reads, writes, must) {
    return Object.freeze({ kind: kind, stage: stage, at: at, reads: Object.freeze(reads), writes: Object.freeze(writes), must: Object.freeze(must || []) });
  }
  var FISH_CORE_READS = ["position, part (the template)", "iA, iB, iC (the spine)", "iCol (rgb, tail-beat phase)",
    "iBody (radius, height, highlight, ember)", "iX (pitch; y the packed swim pose)", "uHalf, uTime, uWag, uWalls",
    "seg(), spine(), inGlass()"];
  var APP_CORE_READS = ["aT, aPattern (the template's site; fin, side)", "iA, iB, iC (the spine)",
    "iBody (radius, height, highlight; w the packed swim pose)", "iX (pitch, tail-beat phase, lambda, family / brain colour)",
    "uHalf, uTime, uWag, uPxPerUnit, uWalls, uColourBy", "the appearance law's COMMON, GENES (GT, fetchGenes), MORPH (Morph, mDecode, mBuild)",
    "appearanceSlot(), seg(), spine()"];
  var LIGHT_READS = ["uLight, uTime, uSelect", "FOG_FN (uFog, uFogDensity, fogOf)", "DEPTH_FN (depthOf, shadeOf, underwater, underwaterAt)",
    "CLARITY_FN (uBack, BACK_TRUE, ambOf, ambTrue, lit, vivid)", "BEAM_FN (uBeamOn, uBeamDir, uBeamTan, uBeamReach, beamOf)"];
  var FISH_VARY = "vWorld, vCol, vPart (0 body, 1 fin, 2 eye), vOy, vSel, vEmber (the body's varyings)";
  var APP_VARY = "vWorld, vMatV (the material site, margin), vPart (fin, side, highlight, colour); the pattern law's VARY";
  var LIGHTING_WRITES = ["float rim (the rim term)", "float bk (the flashlight's share, 0..1)",
    "vec3 col (the lit colour, before the water)", "vec3 clear (the colour in the flashlight's clear light)"];
  var TERMS_READS = ["rim, bk, col, clear and the lighting's other names (the polish's: diff, thin, nl, pk)", "N, V"];
  var WATER_READS = ["col (lit, before the water)", "vWorld", "DEPTH_FN (underwaterAt), CLARITY_FN (vivid)"];
  var EMISSIVE_READS = ["murky (final: the fog and the flashlight's light blended)", "clear, bk, add", "vWorld, N, V", "fogOf()"];
  /** Each slot: kind (append: additive, any number of features, in their order; replace: one provider),
   * stage, where it is, what it may read, what it writes; must: what a replacement declares.
   * @type {Object<string, ShaderSlotSpec>} */
  var SLOTS = {
    /* the legacy fish's and the predators' vertex stages */
    "fish.world": S("replace", "vs", "the vertex stages' common part, after seg(), spine() and inGlass(): the world position",
      FISH_CORE_READS, ["vec3 fishWorld(): the vertex's world point", "before it, the functions and globals it and main() call"], ["fishWorld"]),
    "fish.vs.decl": S("append", "vs", "the body's vertex stage, after its varyings, before main()",
      FISH_CORE_READS.concat(["fishWorld()", FISH_VARY]), ["uniforms, varyings, functions"]),
    "fish.pose": S("append", "vs", "first in main()",
      FISH_CORE_READS.concat(["the world slot's globals"]), ["the globals the world position reads (the polish: iPose)"]),
    "fish.varyings": S("append", "vs", "main(), after the body's varyings are written, before gl_Position",
      ["w (the world point)"].concat(FISH_CORE_READS, ["the declarations' functions"]), ["the feature's own varyings"]),
    /* their fragment stage */
    "fish.fs.lib": S("append", "fs", "after the scene's light chunks (FOG_FN, DEPTH_FN, CLARITY_FN, BEAM_FN), before the stage's varyings",
      LIGHT_READS, ["functions and constants of the light model"]),
    "fish.fs.decl": S("append", "fs", "after the stage's varyings, before baseOf()",
      LIGHT_READS.concat([FISH_VARY]), ["uniforms, varyings, functions"]),
    "fish.lighting": S("replace", "fs", "main(), after the facet's normal: the light model",
      ["N, V (the facet's normal, toward the camera)", "baseOf(back) (the skin: darker back, pale belly, paler fins)", FISH_VARY].concat(LIGHT_READS),
      LIGHTING_WRITES, ["rim", "bk", "col", "clear"]),
    "fish.lightTerms": S("append", "fs", "after the lighting, before the water: light terms added to the lit colour",
      TERMS_READS.concat([FISH_VARY, "baseOf()"], LIGHT_READS), ["col, clear (terms added in clear water)"]),
    "fish.water": S("replace", "fs", "after the light terms: the water's grading of the murky colour (its fallback: underwaterAt(vivid(col)))",
      WATER_READS, ["col"]),
    "fish.lightMods": S("append", "fs", "after the water, before the predator's ember colour and the eyes",
      ["rim, bk, col (graded), clear and the lighting's other names", "N, V", FISH_VARY], ["col, clear"]),
    "fish.eyes": S("replace", "fs", "after vec3 add and the predator's ember colour: the eyes, and a predator's ember rim",
      ["vPart (> 1.5: an eye), vEmber (> .5: a predator)", "ember", "N, V, rim, col"], ["col, clear (an eye's own colour)", "add (the ember rim)"]),
    "fish.highlights": S("append", "fs", "after the eyes (its fallback: the selection's and the hover's rim), before col += add",
      ["vSel (1 selected, .5 hover)", "rim, uSelect", "col, clear"], ["add", "col, clear (scaled)"]),
    "fish.fog": S("replace", "fs", "after col += add: the water's fog",
      ["col", "vWorld", "uFog, fogOf()"], ["vec3 murky (the colour in the fog)"], ["murky"]),
    "fish.emissive": S("append", "fs", "after the fog and the flashlight's blend, before the output: light the fish emits (bioluminescence)",
      EMISSIVE_READS.concat([FISH_VARY]), ["murky (light added)"]),
    /* the appearance fish's vertex stages */
    "app.world": S("replace", "vs", "the vertex stages' common part, after seg() and spine(), before minWidth(): the world position",
      APP_CORE_READS, ["vec3 appWorld(vec3 geo): the deformed rest point (body radii; x = lambda u) in the world",
        "before and after it, the functions and globals it and main() call"], ["appWorld"]),
    "app.vs.decl": S("append", "vs", "the body's vertex stage, after the pattern law's VARY, DECODE and its varyings, before main()",
      APP_CORE_READS.concat(["appWorld(), minWidth()", APP_VARY]), ["uniforms, varyings, functions"]),
    "app.pose": S("append", "vs", "first in main()",
      APP_CORE_READS.concat(["the world slot's globals"]), ["the globals the world position reads (the polish: iPose)"]),
    "app.rest": S("append", "vs", "main(), after mBuild, before appWorld(geo)",
      ["M (Morph: the decoded shape)", "geo, mat, mar (the rest point, the material site, its margin)", "aT, aPattern", "GT (the fetched genes)"].concat(APP_CORE_READS),
      ["geo", "the feature's own varyings"]),
    "app.varyings": S("append", "vs", "main(), after vWorld, vMatV, vPart are written, before gl_Position",
      ["w (the world point)", "M, geo, mat, mar"].concat(APP_CORE_READS), ["the feature's own varyings"]),
    /* the appearance fish's fragment stage */
    "app.fs.lib": S("append", "fs", "after the scene's light chunks (FOG_FN, DEPTH_FN, CLARITY_FN, BEAM_FN), before the pattern law's COMMON",
      LIGHT_READS.concat(["uColourBy"]), ["functions and constants of the light model"]),
    "app.fs.decl": S("append", "fs", "after the pattern law's COMMON, VARY, SKIN and the stage's varyings, before colourBase()",
      LIGHT_READS.concat(["uColourBy", APP_VARY, "the pattern law's functions (patternSkinM, patternBase, pProfileH, pS, pHSV)"]), ["uniforms, varyings, functions"]),
    "app.surface": S("append", "fs", "main(), after the skin's colour, before the facet's normal",
      ["fin (0 body, 1-3, 5, 6 fins, 4 eye, 7 barbel)", "u, v, zL, oyL (the material site)", "base", APP_VARY, "colourBase()"],
      ["base (the skin's colour before the light)"]),
    "app.lighting": S("replace", "fs", "main(), after the facet's normal: the light model",
      ["base, fin, u, oyL", "N, V (the facet's normal, toward the camera)", "colourBase(fin, oy, back)", APP_VARY].concat(LIGHT_READS),
      LIGHTING_WRITES, ["rim", "bk", "col", "clear"]),
    "app.lightTerms": S("append", "fs", "after the lighting, before the water: light terms added to the lit colour",
      TERMS_READS.concat(["base, fin, u, oyL", APP_VARY, "colourBase()"], LIGHT_READS), ["col, clear (terms added in clear water)"]),
    "app.water": S("replace", "fs", "after the light terms: the water's grading of the murky colour (its fallback: underwaterAt(vivid(col)))",
      WATER_READS.concat(["base, fin"]), ["col"]),
    "app.lightMods": S("append", "fs", "after the water, before vec3 add",
      ["rim, bk, col (graded), clear and the lighting's other names", "base, fin, N, V", APP_VARY], ["col, clear"]),
    "app.eyes": S("replace", "fs", "after vec3 add and float vSel: the eyes (fin 4)",
      ["fin", "N, V, rim, base, col", APP_VARY], ["col, clear (an eye's own colour)", "add; it may discard"]),
    "app.highlights": S("append", "fs", "after the eyes (its fallback: the selection's and the hover's rim), before col += add",
      ["vSel (1 selected, .5 hover)", "rim, uSelect", "col, clear", "fin"], ["add", "col, clear (scaled)"]),
    "app.fog": S("replace", "fs", "after col += add: the water's fog",
      ["col", "vWorld", "uFog, fogOf()"], ["vec3 murky (the colour in the fog)"], ["murky"]),
    "app.emissive": S("append", "fs", "after the fog and the flashlight's blend, before the output: light the fish emits (bioluminescence)",
      EMISSIVE_READS.concat(["fin", APP_VARY]), ["murky (light added)"])
  };
  /** @param {"vs" | "fs"} stage @param {string} doc @param {string[]} slots @returns {ShaderProgramSpec} */
  function C(stage, doc, slots) { return Object.freeze({ abi: ABI, stage: stage, doc: doc, slots: Object.freeze(slots) }); }
  /** The programs with slots, and their slots in order. @type {Object<string, ShaderProgramSpec>} */
  var PROGRAMS = {
    "fish.vs": C("vs", "the legacy fish's and the predators' body (fishVs; FISH_VS)", ["fish.world", "fish.vs.decl", "fish.pose", "fish.varyings"]),
    "fish.fs": C("fs", "their body's fragment stage (fishFs; FISH_FS)",
      ["fish.fs.lib", "fish.fs.decl", "fish.lighting", "fish.lightTerms", "fish.water", "fish.lightMods", "fish.eyes", "fish.highlights",
       "fish.fog", "fish.emissive"]),
    "fish.shadow.vs": C("vs", "their shadow (shadowVs; SHADOW_VS, with SHADOW_FS)", ["fish.world", "fish.pose"]),
    "fish.attach.vs": C("vs", "a pass a look owns on their instances (parts.fishAttach(decl, body): the common part, the look's " +
      "declarations, main() with the pose read first, then the look's body, which calls fishWorld(); #47's predator faces)", ["fish.world", "fish.pose"]),
    "app.body.vs": C("vs", "the appearance fish's body and barbels (appearanceShaders: vs)", ["app.world", "app.vs.decl", "app.pose", "app.rest", "app.varyings"]),
    "app.body.fs": C("fs", "their fragment stage (appearanceShaders: fs)",
      ["app.fs.lib", "app.fs.decl", "app.surface", "app.lighting", "app.lightTerms", "app.water", "app.lightMods", "app.eyes", "app.highlights",
       "app.fog", "app.emissive"]),
    "app.shadow.vs": C("vs", "their shadow (appearanceShaders: shadowVs, with SHADOW_FS)", ["app.world", "app.pose", "app.rest"])
  };
  Object.keys(PROGRAMS).forEach(function (p) {   /* the contracts agree with the slots (a typo here throws as the module loads) */
    PROGRAMS[p].slots.forEach(function (s) {
      if (!hasOwn.call(SLOTS, s) || SLOTS[s].stage !== PROGRAMS[p].stage) throw err(p + ": slot " + s + " is not a " + PROGRAMS[p].stage + " slot");
    });
  });
  Object.freeze(SLOTS); Object.freeze(PROGRAMS);

  /* The names a GLSL source declares, scope by scope (scope "": the globals;
   * else a function's top level, "name#k": its k-th definition in the
   * source): uniforms, attributes, varyings, constants, globals, structs and
   * functions (prototypes left out), and each function's top-level locals,
   * with the offset of each declaration's statement. A scan of statements
   * (comments and preprocessor lines blanked), not a parser: enough for the
   * fish programs' GLSL, whose declarations it finds all of. The subset a
   * feature keeps to, for the checks to hold:
   *   - no overloads: a function a feature defines under a name the program
   *     (or another feature) has is a collision, whatever its parameters
   *   - no declarations under #if / #ifdef: preprocessor lines are blanked,
   *     so both branches' declarations count (a false collision), and a
   *     #define is neither expanded nor seen as a declaration
   *   - three's own declarations (its prefix: position, modelMatrix,
   *     projectionMatrix, cameraPosition, ...) are not in the source: a
   *     feature redeclaring one is not caught here (the compile fails)
   *   - a struct's declarators (struct S { ... } s;) are not seen; declare
   *     the struct, then its variables
   *   - a slot's must is a name, not its kind: "float murky" passes as well
   *     as "vec3 murky" (the compile says which is wrong) */
  var GLSL_TYPE = /^(?:void|bool|int|uint|float|[biu]?vec[234]|mat[234](?:x[234])?|[iu]?sampler(?:2D|3D|Cube|2DArray)(?:Shadow)?)$/;
  var DECL = /^((?:(?:uniform|attribute|varying|flat|smooth|centroid|const|in|out|highp|mediump|lowp|invariant)\s+)*)([A-Za-z_]\w*)\s+([\s\S]+)$/;
  /** @param {string} src @returns {ShaderDeclaration[]} */
  function declarations(src) {
    var s = src.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*|^[ \t]*#[^\n]*/gm, function (m) { return m.replace(/[^\n]/g, " "); });
    /** @type {ShaderDeclaration[]} */
    var out = [];
    /** @type {Object<string, boolean>} */
    var structs = {};
    /** @type {{kind: string, scope: string}[]} */
    var stack = [];
    var start = 0, paren = 0, fns = 0;
    /** @param {string} stmt @param {string} scope @param {number} at */
    function decl(stmt, scope, at) {
      var m = DECL.exec(stmt);
      if (!m || !(GLSL_TYPE.test(m[2]) || hasOwn.call(structs, m[2]))) return;
      var rest = m[3];
      if (/^[A-Za-z_]\w*\s*\(/.test(rest)) return;   /* a prototype */
      var q = /\b(uniform|attribute|varying|const)\b/.exec(m[1]);
      var kind = scope ? "local" : q ? q[1] : "global";
      for (var i = 0, depth = 0, from = 0; i <= rest.length; i++) {
        var c = rest.charAt(i);
        if (c === "(" || c === "[") depth++;
        else if (c === ")" || c === "]") depth--;
        else if (i === rest.length || (c === "," && depth === 0)) {
          var n = /^\s*([A-Za-z_]\w*)/.exec(rest.slice(from, i));
          if (n) out.push({ name: n[1], scope: scope, kind: kind, at: at });
          from = i + 1;
        }
      }
    }
    for (var i = 0; i < s.length; i++) {
      var c = s.charAt(i);
      if (c === "(") paren++;
      else if (c === ")") paren--;
      if (paren > 0 || (c !== ";" && c !== "{" && c !== "}")) continue;
      var raw = s.slice(start, i), lead = raw.search(/\S/), at = lead < 0 ? i : start + lead, stmt = raw.trim();
      start = i + 1;
      if (c === "}") { stack.pop(); continue; }
      if (c === "{") {
        var kind = "block", scope = "";
        if (!stack.length) {
          var st = /^struct\s+([A-Za-z_]\w*)$/.exec(stmt), fn = /([A-Za-z_]\w*)\s*\([^()]*\)$/.exec(stmt);
          if (st) { kind = "struct"; structs[st[1]] = true; out.push({ name: st[1], scope: "", kind: "struct", at: at }); }
          else if (fn) { kind = "function"; scope = fn[1] + "#" + (++fns); out.push({ name: fn[1], scope: "", kind: "function", at: at }); }
        }
        stack.push({ kind: kind, scope: scope });
        continue;
      }
      if (!stmt) continue;
      if (!stack.length) decl(stmt, "", at);
      else if (stack.length === 1 && stack[0].kind === "function") decl(stmt, stack[0].scope, at);
    }
    return out;
  }
  /** @typedef {{ text: string, by: string, slot: string, replaces: boolean }} AsmPiece */
  /* the declarations' checks on an assembled program (pieces: its parts, each
   * slot's text with the feature that gave it): a name declared twice in one
   * scope where a feature made a declaration; a replacement that does not
   * declare what its slot must */
  /** @param {string} name @param {AsmPiece[]} pieces */
  function checkDecls(name, pieces) {
    /** @type {number[]} */
    var starts = [];
    var pos = 0;
    pieces.forEach(function (p) { starts.push(pos); pos += p.text.length + 1; });
    var D = declarations(pieces.map(function (p) { return p.text; }).join("\n"));
    /** @param {number} at */
    function pieceOf(at) { var lo = 0, hi = starts.length - 1; while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (starts[mid] <= at) lo = mid; else hi = mid - 1; } return lo; }
    /** @type {Object<string, { d: ShaderDeclaration, p: AsmPiece }[]>} */
    var groups = {};
    D.forEach(function (d) { var key = d.scope + " " + d.name; (groups[key] = groups[key] || []).push({ d: d, p: pieces[pieceOf(d.at)] }); });
    Object.keys(groups).forEach(function (key) {
      var g = groups[key], d = g[0].d;
      if (g.length < 2 || !g.some(function (x) { return x.p.by; })) return;
      throw err(name + ": declaration collision: " + d.name + (d.scope ? " in " + d.scope.split("#")[0] + "()" : " (global)") + ", declared by " +
                g.map(function (x) { return x.p.by ? x.p.by + " (" + x.p.slot + ")" : "the program"; }).join(" and "));
    });
    pieces.forEach(function (p, k) {
      if (!p.replaces) return;
      var have = D.filter(function (d) { return pieceOf(d.at) === k; }).map(function (d) { return d.name; });
      SLOTS[p.slot].must.forEach(function (m) {
        if (have.indexOf(m) < 0) throw err(name + ": " + p.by + "'s " + p.slot + " does not declare " + m + " (the slot's replacement must declare " + SLOTS[p.slot].must.join(", ") + ")");
      });
    });
  }
  /** @param {ShaderFeature} a @param {ShaderFeature} b */
  function byOrder(a, b) { return a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0); }

  /** A registry of features and the assembler over it: the module's own (feature, program, core below), or
   * a fresh one (assembler(): the tests'). @returns {ShaderAssembler} */
  function assembler() {
    /** @type {Object<string, ShaderFeature>} */
    var reg = {};
    /** @param {ShaderFeatureSpec} spec @returns {ShaderFeature} */
    function feature(spec) {
      var id = spec && spec.id;
      if (typeof id !== "string" || !id) throw err("a feature needs an id");
      if (hasOwn.call(reg, id)) throw err("feature " + id + " is registered already");
      if (spec.abi !== ABI) throw err("feature " + id + ": ABI " + spec.abi + " is not supported (the slots' is " + ABI + ")");
      var targets = spec.targets;
      if (!Array.isArray(targets) || !targets.length) throw err("feature " + id + " has no targets");
      targets.forEach(function (t) {
        if (!hasOwn.call(PROGRAMS, t)) throw err("feature " + id + ": unsupported target " + t + " (the programs with slots: " + Object.keys(PROGRAMS).join(", ") + ")");
      });
      var append = spec.append || {}, replace = spec.replace || {}, n = 0;
      /** @param {"append" | "replace"} kind @param {Object<string, ShaderText>} map */
      function check(kind, map) {
        Object.keys(map).forEach(function (s) {
          if (!hasOwn.call(SLOTS, s)) throw err("feature " + id + ": unknown slot " + s);
          if (SLOTS[s].kind !== kind) throw err("feature " + id + ": " + s + " is " + (SLOTS[s].kind === "append" ? "an additive" : "a replacement") + " slot, not one to " + kind);
          if (!targets.some(function (t) { return PROGRAMS[t].slots.indexOf(s) >= 0; })) throw err("feature " + id + ": slot " + s + " is in none of its targets (" + targets.join(", ") + ")");
          if (typeof map[s] !== "string" && typeof map[s] !== "function") throw err("feature " + id + ": its " + kind + " of " + s + " is neither GLSL nor a function giving it");
          n++;
        });
      }
      check("append", append);
      check("replace", replace);
      if (!n) throw err("feature " + id + " appends and replaces nothing");
      var order = spec.order === undefined ? 0 : spec.order;
      if (typeof order !== "number" || !isFinite(order)) throw err("feature " + id + ": its order is not a number");
      /* its version (default 1): the binder's material key holds id and version (web/ocean_materials.js) */
      var version = spec.version === undefined ? 1 : spec.version;
      if (typeof version !== "number" || !(version >= 1) || Math.floor(version) !== version) throw err("feature " + id + ": its version is not a whole number from 1");
      /** @type {ShaderFeature} */
      var f = Object.freeze({ id: id, abi: ABI, version: version, targets: Object.freeze(targets.slice()), append: Object.freeze(Object.assign({}, append)),
                              replace: Object.freeze(Object.assign({}, replace)), order: order });
      reg[id] = f;
      return f;
    }
    /** @param {string} name @param {ShaderPart[]} parts @param {string[] | undefined} ids @param {ShaderEnv | undefined} env
     * @param {boolean} partial @returns {string} */
    function assemble(name, parts, ids, env, partial) {
      if (!hasOwn.call(PROGRAMS, name)) throw err("unknown program " + name);
      var P = PROGRAMS[name];
      /** @type {Object<string, boolean>} */
      var seen = {};
      /** @type {string[]} */
      var got = [];
      parts.forEach(function (x) {
        if (x === null || typeof x === "string") return;
        if (!x || typeof x.slot !== "string") throw err(name + ": a part is neither GLSL, null nor a slot");
        if (P.slots.indexOf(x.slot) < 0) throw err(name + ": unknown slot " + x.slot + " (its slots: " + P.slots.join(", ") + ")");
        if (seen[x.slot]) throw err(name + ": duplicate slot " + x.slot);
        if (x.fallback !== null && typeof x.fallback !== "string") throw err(name + ": slot " + x.slot + "'s fallback is neither GLSL nor null");
        seen[x.slot] = true;
        got.push(x.slot);
      });
      var want = P.slots.filter(function (s) { return !partial || seen[s]; });
      want.forEach(function (s) { if (!seen[s]) throw err(name + ": missing slot " + s); });
      if (got.join() !== want.join()) throw err(name + ": its slots are out of order (" + got.join(", ") + "; the program's: " + want.join(", ") + ")");
      /* the enabled features that support this program, in their own order */
      /** @type {ShaderFeature[]} */
      var on = [];
      (ids || []).forEach(function (id) {
        if (!hasOwn.call(reg, id)) throw err(name + ": unknown feature " + id);
        if (reg[id].targets.indexOf(name) >= 0 && on.indexOf(reg[id]) < 0) on.push(reg[id]);
      });
      on.sort(byOrder);
      /** @param {ShaderFeature} f @param {string} s @param {ShaderText} v */
      function text(f, s, v) {
        var t = v;
        if (typeof v === "function") {
          try { t = v(env || {}); }
          catch (e) { throw err(name + ": " + f.id + "'s text for " + s + " threw: " + (e && e.message || e)); }
        }
        if (typeof t !== "string") throw err(name + ": " + f.id + "'s text for " + s + " is not GLSL");
        return t;
      }
      /** a feature's piece ("" adds no line) @param {AsmPiece} p */
      function add(p) { if (p.text !== "" || !p.by) pieces.push(p); }
      /** @type {AsmPiece[]} */
      var pieces = [];
      parts.forEach(function (x) {
        if (x === null) return;
        if (typeof x === "string") { pieces.push({ text: x, by: "", slot: "", replaces: false }); return; }
        var s = x.slot, rep = on.filter(function (f) { return hasOwn.call(f.replace, s); });
        if (rep.length > 1) throw err(name + ": " + s + " has " + rep.length + " providers (" + rep.map(function (f) { return f.id; }).join(", ") + "); a replacement slot takes one");
        if (rep.length) {
          var t = text(rep[0], s, rep[0].replace[s]);
          if (t === "" && SLOTS[s].must.length) throw err(name + ": " + rep[0].id + "'s " + s + " is empty: it does not declare " + SLOTS[s].must.join(", "));
          add({ text: t, by: rep[0].id, slot: s, replaces: true });
        } else if (x.fallback !== null) pieces.push({ text: x.fallback, by: "", slot: s, replaces: false });
        on.forEach(function (f) { if (hasOwn.call(f.append, s)) add({ text: text(f, s, f.append[s]), by: f.id, slot: s, replaces: false }); });
      });
      if (on.length) checkDecls(name, pieces);
      return pieces.map(function (p) { return p.text; }).join("\n");
    }
    return {
      feature: feature,
      program: function (name, parts, features, env) { return assemble(name, parts, features, env, false); },
      core: function (name, parts, features, env) { return assemble(name, parts, features, env, true); },
      features: function () { return Object.keys(reg).sort(); },
      get: function (id) { return hasOwn.call(reg, id) ? reg[id] : null; }
    };
  }
  var A0 = assembler();

  /* ---- the legacy fish's and the predators' programs: their parts ---- */
  /* the world position (fishWorld): its head and tail, around the swim's
   * lateral offset and height */
  var FISH_WORLD_HEAD = [
    "vec3 fishWorld() {",
    "  float u = position.x, R = iBody.x;",
    "  float s = clamp(u, -0.5, 1.6) * 5.0;",
    "  vec2 c = spine(s);",
    "  vec2 f = spine(s - 0.15) - spine(s + 0.15);",
    "  float fl = length(f);",
    "  f = fl > 1e-4 ? f / fl : vec2(1.0, 0.0);",
    "  vec2 side = vec2(-f.y, f.x);"
  ];
  var FISH_WAG = "  float wag = sin(uTime * 7.5 + iCol.w * 6.2831 - u * 4.5) * uWag * smoothstep(0.1, 1.3, u) * R * 0.3;";
  /* pitch: the head stays at the fish's depth and every point behind it
   * rises (sinking) or falls (rising) by its distance along the spine times
   * tan(pitch), so trail, rings and picking (all at the head) stay right and
   * the shadow follows the tilted body */
  var SPINE_LIFT = [
    "  float along = length(c - seg(0)) * (s < 0.0 ? -1.0 : 1.0);",
    "  float lift = along * clamp(iX.x, -1.2, 1.2);"
  ];
  var FISH_WORLD = lines(FISH_WORLD_HEAD.concat([
    FISH_WAG,
    "  vec2 p = c + side * (position.y * R + wag);"
  ], SPINE_LIFT, [
    "  return inGlass(vec3(p.x - uHalf.x, iBody.y + position.z * R + lift, p.y - uHalf.y));",
    "}"
  ]));
  /** the vertex stages' common part @returns {ShaderPart[]} */
  function fishCoreParts() {
    return [
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
      slot("fish.world", FISH_WORLD)
    ];
  }
  /** the body's vertex stage @returns {ShaderPart[]} */
  function fishVsParts() {
    return fishCoreParts().concat([
      "varying vec3 vWorld; varying vec3 vCol; varying float vPart; varying float vOy;",
      "varying float vSel; varying float vEmber;",
      slot("fish.vs.decl", null),
      "void main() {",
      slot("fish.pose", null),
      "  vec3 w = fishWorld();",
      "  vWorld = w; vCol = iCol.rgb; vPart = part; vOy = position.z; vSel = iBody.z; vEmber = iBody.w;",
      slot("fish.varyings", null),
      "  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);",
      "}"
    ]);
  }
  /* a fish high above the floor casts a fainter shadow (vLift: 0 at the floor) */
  /** the shadow's vertex stage @returns {ShaderPart[]} */
  function shadowVsParts() {
    return fishCoreParts().concat([
      "uniform vec3 uLight; uniform float uFloorY; uniform float uDepth;",
      "varying vec3 vWorld; varying float vLift;",
      "void main() {",
      slot("fish.pose", null),
      "  vec3 w = fishWorld();",
      "  vec3 s = w - uLight * ((w.y - uFloorY) / uLight.y);",
      "  s.y = uFloorY + 0.8;",
      "  vWorld = s;",
      "  vLift = clamp((w.y - uFloorY) / uDepth, 0.0, 1.0);",
      "  gl_Position = projectionMatrix * viewMatrix * vec4(s, 1.0);",
      "}"
    ]);
  }
  /* the fragment stages' shared lines: the facet's normal, the rim and the
   * flashlight's share, the water, the selection, the fog, the flashlight's
   * clear light blended in */
  var FACET = [
    /* flat facets: the triangle's own normal, from screen-space derivatives */
    "  vec3 N = normalize(cross(dFdx(vWorld), dFdy(vWorld)));",
    "  vec3 V = normalize(cameraPosition - vWorld);",
    "  if (dot(N, V) < 0.0) N = -N;"
  ];
  var RIM = "  float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);";
  var BEAM_AT = "  float bk = beamOf(vWorld);";
  var WATER = "  col = underwaterAt(vivid(col), vWorld.y);";
  var HIGHLIGHT = lines([
    "  if (vSel > 0.75) add += uSelect * (0.16 + 0.55 * rim);",
    "  else if (vSel > 0.25) add += uSelect * 0.4 * rim;"
  ]);
  var FOG_AT = "  vec3 murky = mix(col, uFog, fogOf(vWorld));";
  var BEAM_MIX = [
    "  if (bk > 0.0) {",
    "    clear = (clear + add) * (1.0 + 0.2 * max(dot(N, -uBeamDir), 0.0));",        /* the beam's own light on the side facing it */
    "    murky = mix(murky, clear, bk);",
    "  }"
  ];
  var FRAG_OUT = ["  gl_FragColor = vec4(murky, 1.0);", "}"];
  var FISH_LIGHT = lines([
    "  float diff = max(dot(N, uLight), 0.0);",
    RIM,
    "  vec3 col = lit(baseOf(uBack), ambOf(N.y), diff, rim);",
    BEAM_AT,
    /* in the flashlight's clear light: the true colours, the same in any water */
    "  vec3 clear = bk > 0.0 ? lit(baseOf(BACK_TRUE), ambTrue(N.y), diff, rim) : col;"
  ]);
  var FISH_EYES = lines([
    "  if (vPart > 1.5) {",                                                            /* eyes */
    "    col = vEmber > 0.5 ? ember * 1.2 : vec3(0.02, 0.03, 0.03);",
    "    col += pow(max(dot(reflect(-uLight, N), V), 0.0), 20.0) * 0.8;",
    "    clear = col;",
    "  } else if (vEmber > 0.5) {",
    "    add += ember * rim * 0.55;",
    "  }"
  ]);
  /** the body's fragment stage @returns {ShaderPart[]} */
  function fishFsParts() {
    return [
      "uniform vec3 uLight; uniform float uTime; uniform vec3 uSelect;",
      FOG_FN,
      DEPTH_FN,
      CLARITY_FN,
      BEAM_FN,
      slot("fish.fs.lib", null),
      "varying vec3 vWorld; varying vec3 vCol; varying float vPart; varying float vOy;",
      "varying float vSel; varying float vEmber;",
      slot("fish.fs.decl", null),
      "vec3 baseOf(float back) {",
      "  vec3 base = vCol;",
      "  float body = 1.0 - step(0.5, vPart);",
      "  base = mix(base, base * back, smoothstep(0.30, 0.85, vOy) * body);",           /* darker back */
      "  base = mix(base, mix(base, vec3(0.93, 0.97, 0.90), 0.5), 1.0 - smoothstep(-0.7, -0.15, vOy));", /* pale belly */
      "  if (vPart > 0.5 && vPart < 1.5) base = mix(base, vec3(0.92, 0.98, 0.95), 0.22);", /* fins */
      "  return base;",
      "}",
      "void main() {"
    ].concat(FACET, [
      slot("fish.lighting", FISH_LIGHT),
      slot("fish.lightTerms", null),
      slot("fish.water", WATER),
      slot("fish.lightMods", null),
      "  vec3 ember = vec3(1.0, 0.38, 0.16) * (0.8 + 0.2 * sin(uTime * 6.0));",
      "  vec3 add = vec3(0.0);",
      slot("fish.eyes", FISH_EYES),
      slot("fish.highlights", HIGHLIGHT),
      "  col += add;",
      slot("fish.fog", FOG_AT)
    ], BEAM_MIX, [slot("fish.emissive", null)], FRAG_OUT);
  }
  /** a pass a look owns on the legacy fish's / predators' instances (#47's predator faces): the vertex
   * stages' common part, the look's declarations (decl: attributes, varyings), main() with the swim pose
   * read first (fish.pose: the polish's iPose = poseOf(iX.y)), then the look's body (body: main()'s lines,
   * which call fishWorld()). program("fish.attach.vs", parts, the kind's features) poses it as its kind.
   * @param {string} decl @param {string} body @returns {ShaderPart[]} */
  function fishAttachParts(decl, body) {
    return fishCoreParts().concat([decl, "void main() {", slot("fish.pose", null), body, "}"]);
  }

  /* ---- the appearance genome's fish (web/ocean_appearance.js: EvoAppearance) ----
   * The same spine, tail beat, pitch, lighting, depth, fog, selection and
   * flashlight as FISH_VS / FISH_FS; every gene comes from uGenes (a fish's
   * 63 floats in 16 RGBA32F texels, fetched by appearanceSlot()): the body is
   * the M1 template deformed by the 30 shape genes and its skin is pattern
   * law 3 from the 33 pattern floats, at the vertex's canonical material
   * site, evaluated before the bend and the swim, so the pattern never
   * slides. 8 vertex attributes. The legacy base / countershade / fin tint stage is not
   * applied to the skin (the genes carry their own).
   * uColourBy = 1 (the page's Family / Brain colours) keeps the body and
   * swaps only the skin: the fish's family / brain colour, packed 0xRRGGBB in
   * iX.w (exact in a float: < 2^24) and passed on in the flat vPart.w (no
   * extra attribute or varying), through the plain fish's base stage (darker
   * back, pale belly, paler fins) at the legacy template's height, (1 − 2v)
   * times the canonical profile, which equals FISH_FS's vOy on a neutral
   * body. The lighting, eyes, selection, fog and flashlight are shared. */
  /* An instance's gene slot: the 16-texel run of the gene texture its genes
   * are in (EvoAppearance GENES fetchGenes). One string for every program
   * that reads genes (the fish and its shadow in every variant, the
   * transform-feedback check, the live-texture probes), so that a change of
   * ownership changes them all at once. The slot is the fish's own (render
   * PR2: web/ocean_appearance_slots.js keeps it for the fish's id while it
   * lives), handed over in the scalar instance attribute iGeneSlot: an
   * integer in a float (exact below 2^24), so int() needs no rounding. The
   * draw order is then free (gl_InstanceID no longer picks the genes). */
  var GENE_SLOT_RET = "return int(iGeneSlot);";
  var GENE_SLOT_GLSL = "attribute float iGeneSlot;\nint appearanceSlot() { " + GENE_SLOT_RET + " }";
  /* The lit fish drawn apart (AppKind's split): in the main draw a lit
   * fish's iBody.z (its highlight: 0, .5 or 1; read by the body programs
   * only, never by the shadows) is LIT_SKIP, and the plain body program
   * drawn beside the lit fish's own draw (litSkip: the plain vertex stage
   * plus this one line) puts all its vertices on one point past the far
   * plane, before any gene fetch: clipped, no fragment. The shadows stay in
   * the main draw, in instance order */
  var LIT_SKIP = -1;
  var LIT_SKIP_GLSL = "  if (iBody.z < 0.0) { gl_Position = vec4(0.0, 0.0, 2.0, 1.0); return; }";
  /** @param {string} vs */
  function litSkip(vs) {
    if (occurrences(vs, "void main() {") !== 1) throw new Error("litSkip: the vertex stage has " + occurrences(vs, "void main() {") + " mains");
    return vs.split("void main() {").join("void main() {\n" + LIT_SKIP_GLSL);
  }
  /* the pattern genes of the fetched slot -> the flat pattern varyings (the
   * fish's vertex shader and the texture-backed chart probe) */
  var DECODE_CALL = "patternDecode(GT[0], GT[1], GT[2], GT[3], GT[4], GT[5], GT[6], GT[7].xyz, vec2(GT[7].w, GT[8].x), iX.z);";
  /* a float32 constant as a GLSL float literal (as ocean_appearance.js writes its own) */
  /** @param {number} x */
  function glslF(x) { var s = Math.fround(x).toPrecision(9); return s.indexOf(".") >= 0 || s.indexOf("e") >= 0 ? s : s + ".0"; }
  /* the world position with the deformed rest point geo (body radii; x =
   * lambda·u along the spine): the extrapolation past the spine's ends is
   * bounded, not clamped to the legacy template's [-.5, 1.6] (long fins and
   * barbels); its head and tail, around the swim's lateral offset and height */
  var APP_WORLD_HEAD = [
    "vec3 appWorld(vec3 geo) {",
    "  float R = iBody.x, u = geo.x / iX.z;",
    "  float s = clamp(u, -1.5, 3.0) * 5.0;",
    "  vec2 c = spine(s);",
    "  vec2 f = spine(s - 0.15) - spine(s + 0.15);",
    "  float fl = length(f);",
    "  f = fl > 1e-4 ? f / fl : vec2(1.0, 0.0);",
    "  vec2 side = vec2(-f.y, f.x);"
  ];
  var APP_WAG = "  float wag = sin(uTime * 7.5 + iX.y * 6.2831 - u * 4.5) * uWag * smoothstep(0.1, 1.3, u) * R * 0.3;";
  var APP_WORLD_TAIL = [
    "  if (uWalls > 0.5) { w.x = clamp(w.x, -uHalf.x, uHalf.x); w.z = clamp(w.z, -uHalf.y, uHalf.y); }",
    "  return w;",
    "}"
  ];
  var APP_WORLD = lines(APP_WORLD_HEAD.concat([
    APP_WAG,
    "  vec2 p = c + side * (geo.y * R + wag);"
  ], SPINE_LIFT, [
    "  vec3 w = vec3(p.x - uHalf.x, iBody.y + geo.z * R + lift, p.y - uHalf.y);"
  ], APP_WORLD_TAIL));
  /** the vertex stages' common part @param {EvoAppearanceApi} EA @returns {ShaderPart[]} */
  function appCoreParts(EA) {
    var G = EA.GLSL;
    return [
      "attribute vec4 aT; attribute vec4 aPattern;",
      "attribute vec4 iA; attribute vec4 iB; attribute vec4 iC;",
      "attribute vec4 iBody;",  /* radius, height, highlight; w: 0, or (polished) the packed swim pose */
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
      slot("app.world", APP_WORLD),
      /* the barbels' screen-space minimum half-width (0.7 px), in body radii */
      "float minWidth() {",
      "  vec3 head = vec3(iA.x - uHalf.x, iBody.y, iA.y - uHalf.y);",
      "  return 0.7 * max(1.0, length(cameraPosition - head)) / max(1e-3, iBody.x * uPxPerUnit);",
      "}"
    ];
  }
  /* the rest point: the genes fetched, the shape decoded and built (mBuild:
   * geo, the material site mat and its margin mar) */
  var APP_REST = [
    "  Morph M = mDecode(iX.z);",
    "  vec3 geo, mat; float mar;",
    "  mBuild(M, aT, aPattern, uTime, uWag, minWidth(), geo, mat, mar);"
  ];
  /** the body's (and barbels') vertex stage @param {EvoAppearanceApi} EA @returns {ShaderPart[]} */
  function appBodyVsParts(EA) {
    var G = EA.GLSL;
    return appCoreParts(EA).concat([
      G.VARY, G.DECODE,
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart;",
      slot("app.vs.decl", null),
      "void main() {",
      slot("app.pose", null),
      "  fetchGenes(appearanceSlot());",
      "  if (uColourBy < 0.5) " + DECODE_CALL
    ], APP_REST, [
      slot("app.rest", null),
      "  vec3 w = appWorld(geo);",
      /* vPart: fin, side, highlight, the packed family / brain colour (the FS reads x, z, w) */
      "  vWorld = w; vMatV = vec4(mat, mar); vPart = vec4(aPattern.x, aPattern.z, iBody.z, iX.w);",
      slot("app.varyings", null),
      "  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);",
      "}"
    ]);
  }
  /** the shadow's vertex stage @param {EvoAppearanceApi} EA @returns {ShaderPart[]} */
  function appShadowVsParts(EA) {
    return appCoreParts(EA).concat([
      "uniform vec3 uLight; uniform float uFloorY; uniform float uDepth;",
      "varying vec3 vWorld; varying float vLift;",
      "void main() {",
      slot("app.pose", null),
      "  fetchGenes(appearanceSlot());"
    ], APP_REST, [
      slot("app.rest", null),
      "  vec3 w = appWorld(geo);",
      "  vec3 s = w - uLight * ((w.y - uFloorY) / uLight.y);",
      "  s.y = uFloorY + 0.8;",
      "  vWorld = s;",
      "  vLift = clamp((w.y - uFloorY) / uDepth, 0.0, 1.0);",
      "  gl_Position = projectionMatrix * viewMatrix * vec4(s, 1.0);",
      "}"
    ]);
  }
  var APP_LIGHT = lines([
    "  float diff = max(dot(N, uLight), 0.0);",
    RIM,
    "  vec3 col = lit(base, ambOf(N.y), diff, rim);",
    BEAM_AT,
    /* in the flashlight's clear light: the true colours, the same in any water (the skin never sees the water) */
    "  vec3 clear = bk > 0.0 ? lit(uColourBy > 0.5 ? colourBase(fin, oyL, BACK_TRUE) : base, ambTrue(N.y), diff, rim) : col;"
  ]);
  var APP_EYES = lines([
    "  if (fin == 4) {",
    "    col = vec3(0.02, 0.03, 0.03);",
    "    col += pow(max(dot(reflect(-uLight, N), V), 0.0), 20.0) * 0.8;",
    "    clear = col;",
    "  }"
  ]);
  /** the body's (and barbels') fragment stage @param {EvoAppearanceApi} EA @returns {ShaderPart[]} */
  function appBodyFsParts(EA) {
    var G = EA.GLSL;
    return [
      "uniform vec3 uLight; uniform float uTime; uniform vec3 uSelect; uniform float uColourBy;",
      FOG_FN, DEPTH_FN, CLARITY_FN, BEAM_FN,
      slot("app.fs.lib", null),
      G.COMMON, G.VARY, G.SKIN,
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart;",
      slot("app.fs.decl", null),
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
      slot("app.surface", null)
    ].concat(FACET, [
      slot("app.lighting", APP_LIGHT),
      slot("app.lightTerms", null),
      slot("app.water", WATER),
      slot("app.lightMods", null),
      "  vec3 add = vec3(0.0);",
      "  float vSel = vPart.z;",
      slot("app.eyes", APP_EYES),
      slot("app.highlights", HIGHLIGHT),
      "  col += add;",
      slot("app.fog", FOG_AT)
    ], BEAM_MIX, [slot("app.emissive", null)], FRAG_OUT);
  }

  /* ---- the swim polish, a feature in two modes ----
   * swimPolish.lite: the roll (POSE_GLSL, a posed world position, the pose
   * read first in main()); the shadows' (a shadow shows neither the fold nor
   * the lag), and the tests'. swimPolish.full: the roll, the tail's lag
   * (wagAt), the paired fins' fold (finPose, in app.rest) and the polish's
   * light (POLISH_FN; its terms in the lighting, which it replaces, so a look
   * that replaces the lighting too is refused while the full polish is on:
   * one provider). Plain is neither. Every text here is the polished
   * variants' as they were drawn before the slots, byte for byte, which is
   * why the light terms stay inside the lighting: the wrapped diffuse and the
   * terms added inside the lit colour's expression (lit(...) + polishOn(...)
   * + sheen) cannot move to *.lightTerms without changing the bytes (and the
   * rounding); that move, which would let a look's lighting keep them, is a
   * look change of its own. The passes each mode targets: lite, every
   * vertex stage the scene poses (the bodies, the shadows, a look's attached
   * pass); full, the bodies' stages, the legacy shadow (shadowVs(true), as
   * main built it; the scene draws the lite shadow) and a look's attached
   * pass, not the appearance shadow (always lite). */
  var POLISH = Object.freeze({ lite: "swimPolish.lite", full: "swimPolish.full" });
  var POLISH_VARY = "flat varying float vPw; varying float vCaus;";   /* the size weight, the caustic light */
  var POLISH_OUT = "  vPw = iPose.w; vCaus = causOf(w);";
  /** the polish's world position (POSE_GLSL, then fishWorld posed) @param {boolean} F */
  function polishFishWorld(F) {
    return lines([POSE_GLSL].concat(FISH_WORLD_HEAD, [
      F ? "  float wag = wagAt(u, uTime * 7.5 + iCol.w * 6.2831 - u * 4.5, R);" : FISH_WAG,
      "  vec2 lu = rollTo(vec2(position.y * R + wag, position.z * R));",   /* the roll: (side, up) */
      "  vec2 p = c + side * lu.x;"
    ], SPINE_LIFT, [
      "  return inGlass(vec3(p.x - uHalf.x, iBody.y + lu.y + lift, p.y - uHalf.y));",
      "}"
    ]));
  }
  /* the paired fins' pose (pectoral 3, pelvic 6: mBuild puts a fin point
   * at root + w d): folded back along the flank by k = iPose.z (0 spread,
   * 1 folded; the pelvics half as far), w d turned toward the tail
   * (normalize(1, .22 side, -.18)) and kept at its length (the blend
   * renormalized), the root unmoved. Nothing on a fish too small on
   * screen (iPose.w 0) or swimming slowly (iPose.z 0) */
  /** @param {EvoAppearanceApi} EA */
  function finPoseOf(EA) {
    return lines([
      "vec3 finPose(Morph M, vec3 geo) {",
      "  int fin = int(aPattern.x + 0.5);",
      "  if (iPose.z <= 0.0 || (fin != 3 && fin != 6)) return geo;",
      "  bool pec = fin == 3; float side = aPattern.z;",
      "  float chord = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, sweep = pec ? M.pSweep : M.vSweep;",
      "  float dih = pec ? M.pDih : -0.25 * P_PI, kk = pec ? iPose.z : 0.5 * iPose.z;",
      "  float w = area / (chord * " + glslF(EA.PHI_I) + ") * aT.y * 4.0 * aT.x * (1.0 - aT.x);",
      "  vec3 d = vec3(sweep, side * cos(dih), sin(dih));",
      "  float L = sqrt(sweep * sweep + 1.0);",   /* |d| */
      "  vec3 m = mix(d, vec3(0.961895, 0.211617 * side, -0.173141) * L, kk);",
      "  float ml = length(m);",
      "  return geo + w * ((ml > 1e-4 ? m * (L / ml) : d) - d);",
      "}"
    ]);
  }
  /** the polish's world position (POSE_GLSL, appWorld posed; full: then finPose) @param {boolean} F @param {ShaderEnv} env */
  function polishAppWorld(F, env) {
    if (F && !env.EA) throw err(POLISH.full + ": app.world needs the appearance law (env.EA)");
    return lines([POSE_GLSL].concat(APP_WORLD_HEAD, [
      F ? "  float wag = wagAt(u, uTime * 7.5 + iX.y * 6.2831 - u * 4.5, R);" : APP_WAG,
      "  vec2 lu = rollTo(vec2(geo.y * R + wag, geo.z * R));",
      "  vec2 p = c + side * lu.x;"
    ], SPINE_LIFT, [
      "  vec3 w = vec3(p.x - uHalf.x, iBody.y + lu.y + lift, p.y - uHalf.y);"
    ], APP_WORLD_TAIL, F && env.EA ? [finPoseOf(env.EA)] : []));
  }
  var POLISH_FISH_LIGHT = lines([
    "  float thin = vPart > 0.5 && vPart < 1.5 ? 1.0 : 0.0, nl = dot(N, uLight);",   /* fins */
    "  float diff = wrapDiff(nl, vPw * thin);",
    RIM,
    "  vec3 pk = polishK(N, V, thin, nl, vPw, vCaus), b = baseOf(uBack);",
    "  vec3 col = lit(b, ambOf(N.y), diff, rim) + polishOn(b, pk);",
    BEAM_AT,
    "  vec3 clear = col;",
    "  if (bk > 0.0) { vec3 bt = baseOf(BACK_TRUE); clear = lit(bt, ambTrue(N.y), diff, rim) + polishOn(bt, pk); }"
  ]);
  /* the polish's thinness (POLISH_FN): the fins 1, the barbels .6, the
   * peduncle a little, the body and eyes 0 */
  var THIN_OF = "float thinOf(int fin, float u) { return fin == 0 ? 0.25 * pS(0.80, 1.0, u) : (fin == 7 ? 0.6 : (fin == 4 ? 0.0 : 1.0)); }";
  /* the skin's sheen (the polish; the genes' skin only, so Family / Brain
   * colours keep their hue): the structural colour of the scales at
   * grazing angles, a hue a little past the skin's own (vG0.x) that turns
   * with the angle, stronger on a pale unsaturated (silvery) skin, faint
   * on the fins */
  var SHEEN_OF = lines([
    "vec3 sheenOf(float ndv, float thin, float nl, float pw) {",
    "  if (pw <= 0.0) return vec3(0.0);",
    "  float silver = (1.0 - vG0.y) * vG0.z, g = 1.0 - ndv; g *= g;",
    "  return pHSV(pWrap01(vG0.x + 0.10 + 0.25 * g), 0.55, 1.0) * (pw * g * (0.12 + 0.30 * silver) * (1.0 - 0.6 * thin) * (0.55 + 0.45 * max(nl, 0.0)));",
    "}"
  ]);
  var POLISH_APP_LIGHT = lines([
    "  float thin = thinOf(fin, u), nl = dot(N, uLight);",
    "  float diff = wrapDiff(nl, vPw * thin);",
    RIM,
    "  vec3 pk = polishK(N, V, thin, nl, vPw, vCaus);",
    "  vec3 sheen = fin != 4 && uColourBy < 0.5 ? sheenOf(max(dot(N, V), 0.0), thin, nl, vPw) : vec3(0.0);",
    "  vec3 col = lit(base, ambOf(N.y), diff, rim) + polishOn(base, pk) + sheen;",
    BEAM_AT,
    "  vec3 clear = col;",
    "  if (bk > 0.0) {",
    "    vec3 bt = uColourBy > 0.5 ? colourBase(fin, oyL, BACK_TRUE) : base;",
    "    clear = lit(bt, ambTrue(N.y), diff, rim) + polishOn(bt, pk) + sheen;",
    "  }"
  ]);
  /** the swim polish in one of its modes, as a feature (registered in the module's own assembler below; a
   * fresh assembler registers it from here) @param {"lite" | "full"} mode @returns {ShaderFeatureSpec} */
  function polishFeature(mode) {
    var F = mode === "full";
    /** @type {Object<string, ShaderText>} */
    var append = { "fish.pose": "  iPose = poseOf(iX.y);", "app.pose": "  iPose = poseOf(iBody.w);" };
    /** @type {Object<string, ShaderText>} */
    var replace = { "fish.world": polishFishWorld(F), "app.world": function (env) { return polishAppWorld(F, env); } };
    if (F) {
      append["fish.vs.decl"] = POLISH_VARY;
      append["fish.varyings"] = POLISH_OUT;
      append["fish.fs.lib"] = POLISH_FN;
      append["fish.fs.decl"] = POLISH_VARY;
      replace["fish.lighting"] = POLISH_FISH_LIGHT;
      append["app.vs.decl"] = POLISH_VARY;
      append["app.rest"] = "  geo = finPose(M, geo);";   /* (then the one appWorld line every variant shares) */
      append["app.varyings"] = POLISH_OUT;
      append["app.fs.lib"] = POLISH_FN;
      append["app.fs.decl"] = lines([POLISH_VARY, THIN_OF, SHEEN_OF]);
      replace["app.lighting"] = POLISH_APP_LIGHT;
    }
    return { id: F ? POLISH.full : POLISH.lite, abi: ABI, append: append, replace: replace,
             targets: F ? ["fish.vs", "fish.fs", "fish.shadow.vs", "fish.attach.vs", "app.body.vs", "app.body.fs"]
                        : ["fish.vs", "fish.shadow.vs", "fish.attach.vs", "app.body.vs", "app.shadow.vs"] };
  }
  A0.feature(polishFeature("lite"));
  A0.feature(polishFeature("full"));

  /* ---- the fish programs, built: a variant P -> the swim polish's feature ---- */
  /** The polish's feature for a variant P (plain: none; lite, full): for a fragment stage ("fs") any
   * polished P is the full one (as before the slots: the lite fish draws fishFs(false), FISH_FS[2]); for
   * an appearance shadow ("shadow") the lite one (a shadow shows neither the fold nor the lag)
   * @param {FishVariant | undefined} P @param {"fs" | "shadow"} [stage] @returns {string[]} */
  function polishFor(P, stage) {
    if (!P) return [];
    return [stage === "fs" ? POLISH.full : stage === "shadow" || P === "lite" ? POLISH.lite : POLISH.full];
  }
  /** @param {string[] | undefined} more @returns {string[]} */
  function also(more) { return more ? more.slice() : []; }
  /** @param {FishVariant} P */
  function fishCore(P) { return A0.core("fish.vs", fishCoreParts(), polishFor(P)); }
  /** @param {FishVariant} P @param {string[]} [more] */
  function fishVs(P, more) { return A0.program("fish.vs", fishVsParts(), polishFor(P).concat(also(more))); }
  /** @param {FishVariant} P @param {string[]} [more] */
  function fishFs(P, more) { return A0.program("fish.fs", fishFsParts(), polishFor(P, "fs").concat(also(more))); }
  /** @param {FishVariant} P @param {string[]} [more] */
  function shadowVs(P, more) { return A0.program("fish.shadow.vs", shadowVsParts(), polishFor(P).concat(also(more))); }
  /* the legacy fish (and predators): plain [0], full [1], lite [2] (the
   * roll only, the plain fragment stage); their shadows plain [0] or lite
   * [1] (a shadow shows neither the fold nor the lag). Built on first read
   * (API.FISH_VS, ...), not as the module loads: an assembly error in a
   * polished variant (a scan's false positive) then fails only what reads
   * them, never the module and so the plain fish (the scene's materials
   * assemble their own, variant by variant, falling back to the plain
   * programs: web/ocean_materials.js) */
  /** @type {{ FISH_VS: string[], FISH_FS: string[], SHADOW_VS: string[] } | null} */
  var BUILT = null;
  function built() {
    if (!BUILT) BUILT = { FISH_VS: [fishVs(false), fishVs(true), fishVs("lite")], FISH_FS: [fishFs(false), fishFs(true), fishFs(false)],
                          SHADOW_VS: [shadowVs(false), shadowVs("lite")] };
    return BUILT;
  }
  var SHADOW_FS = [
    FOG_FN,
    "uniform float uAlpha;",
    "varying vec3 vWorld; varying float vLift;",
    "void main() { gl_FragColor = vec4(0.008, 0.04, 0.05, uAlpha * (1.0 - 0.7 * vLift) * (1.0 - fogOf(vWorld))); }"
  ].join("\n");

  /* the fish's programs, plain (P false: as before the swim polish, byte for
   * byte), full (P true; POSE_GLSL, POLISH_FN) or lite (P "lite": the roll
   * only, the plain fragment stage; drawn while no fish is lit), and the
   * probes' (the same in all). The shadow of a posed fish is always lite.
   * more: other features' ids, for the programs they target */
  /** @param {EvoAppearanceApi} EA @param {FishVariant} [P] @param {string[]} [more] */
  function appearanceShaders(EA, P, more) {
    var G = EA.GLSL, env = { EA: EA }, m = also(more);
    var vs = A0.program("app.body.vs", appBodyVsParts(EA), polishFor(P).concat(m), env);
    var fs = A0.program("app.body.fs", appBodyFsParts(EA), polishFor(P).concat(m), env);   /* (the lite polish targets no fragment stage) */
    var shadowVs = A0.program("app.shadow.vs", appShadowVsParts(EA), polishFor(P, "shadow").concat(m), env);
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
     * (placed by draw index, read from its slot through appearanceSlot()); probeChartVs: the
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
  /* the vertex stages' common part (P as above) */
  /** @param {EvoAppearanceApi} EA @param {FishVariant} [P] */
  function appCore(EA, P) { return A0.core("app.body.vs", appCoreParts(EA), polishFor(P), { EA: EA }); }

  /** @type {EvoOceanShadersApi} */
  var API = {
    FOG_FN: FOG_FN, BEAM_FN: BEAM_FN, DEPTH_FN: DEPTH_FN, CLARITY_FN: CLARITY_FN,
    FLOOR_VS: FLOOR_VS, FLOOR_FS: FLOOR_FS, SURF_FS: SURF_FS, FOOD_VS: FOOD_VS, FOOD_FS: FOOD_FS,
    GLOW_VS: GLOW_VS, GLOW_FS: GLOW_FS, SNOW_VS: SNOW_VS, SNOW_FS: SNOW_FS, GLASS_VS: GLASS_VS, GLASS_FS: GLASS_FS,
    LINE_VS: LINE_VS, LINE_FS: LINE_FS, RING_VS: RING_VS, RING_FS: RING_FS,
    lines: lines, occurrences: occurrences, POSE_GLSL: POSE_GLSL, POLISH_FN: POLISH_FN,
    fishCore: fishCore, fishVs: fishVs, fishFs: fishFs, shadowVs: shadowVs,
    get FISH_VS() { return built().FISH_VS; }, get FISH_FS() { return built().FISH_FS; }, get SHADOW_VS() { return built().SHADOW_VS; },
    SHADOW_FS: SHADOW_FS,
    GENE_SLOT_RET: GENE_SLOT_RET, GENE_SLOT_GLSL: GENE_SLOT_GLSL, LIT_SKIP: LIT_SKIP, LIT_SKIP_GLSL: LIT_SKIP_GLSL, litSkip: litSkip,
    DECODE_CALL: DECODE_CALL, glslF: glslF, appearanceShaders: appearanceShaders, appCore: appCore,
    ABI: ABI, SLOTS: SLOTS, PROGRAMS: PROGRAMS, slot: slot, declarations: declarations,
    feature: A0.feature, program: A0.program, core: A0.core, features: A0.features, featureOf: A0.get, assembler: assembler,
    parts: Object.freeze({ fishCore: fishCoreParts, fishVs: fishVsParts, fishFs: fishFsParts, shadowVs: shadowVsParts, fishAttach: fishAttachParts,
                           appCore: appCoreParts, appBodyVs: appBodyVsParts, appBodyFs: appBodyFsParts, appShadowVs: appShadowVsParts }),
    POLISH: POLISH, polishFeature: polishFeature
  };
  root.EvoOceanShaders = API;
})(typeof window !== "undefined" ? window : globalThis);
