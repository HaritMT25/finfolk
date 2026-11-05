// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the scene's GLSL that comes in no variants (window.EvoOceanShaders).
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
 * The uniforms' values are the scene's (its colours C, the water's CLARITY,
 * setClarity, setLight, setFlashlight); only their declarations are here. The
 * fish programs, which come in variants (plain, full and lite: the swim
 * polish), stay in the scene with the pose math they share with the CPU
 * (POSE_GLSL, POLISH_FN, fishVs / fishFs / shadowVs, the appearance programs).
 *
 * Moved from web/ocean_scene.js unchanged, every string byte for byte (the
 * structure pass's first extraction: renderer_seams_plan_codex.md, module
 * ocean_shaders.js). Plain strings, no WebGL: node can load it. Display only:
 * the simulation never reads any of it. */
(function (root) {
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

  /** @type {EvoOceanShadersApi} */
  var API = {
    FOG_FN: FOG_FN, BEAM_FN: BEAM_FN, DEPTH_FN: DEPTH_FN, CLARITY_FN: CLARITY_FN,
    FLOOR_VS: FLOOR_VS, FLOOR_FS: FLOOR_FS, SURF_FS: SURF_FS, FOOD_VS: FOOD_VS, FOOD_FS: FOOD_FS,
    GLOW_VS: GLOW_VS, GLOW_FS: GLOW_FS, SNOW_VS: SNOW_VS, SNOW_FS: SNOW_FS, GLASS_VS: GLASS_VS, GLASS_FS: GLASS_FS,
    LINE_VS: LINE_VS, LINE_FS: LINE_FS, RING_VS: RING_VS, RING_FS: RING_FS
  };
  root.EvoOceanShaders = API;
})(typeof window !== "undefined" ? window : globalThis);
