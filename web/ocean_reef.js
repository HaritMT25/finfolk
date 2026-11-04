"use strict";
/* finfolk 3-D Ocean: the Reef look (opt-in: View › Look, ?look=reef).
 *
 * A sunlit aquarium seen through its front glass: sky and a far island above
 * a wavy waterline, bright blue water, a procedural reef around the tank, and
 * storybook fish with cartoon eyes. Drawing and camera only: nothing here
 * reaches the simulation, and with the look off nothing of it is in the
 * scene (no object, no uniform touched), so the default picture is unchanged.
 *
 * What is drawn from the simulation and what is added for looks:
 *   - the fish, food and predators are where the engine puts them (the same
 *     spines, depths, pitches, bodies and colours as the default look). A
 *     fish's lit side is exactly its family / brain colour: the storybook
 *     shading only steps its brightness (three soft bands), and distance and
 *     depth only darken it, so hue and saturation never shift
 *   - added for looks: the sky, the island, the waterline, the sea band, the
 *     reef (rocks, shells, coral, ruined columns), the cartoon eyes and the
 *     predators' brows. Decor inside the tank stays low (at most 6 units, on
 *     the sand); everything taller sits behind the back glass and beyond the
 *     ends, so no fish ever swims through it
 *
 * The camera ("aquarium walk"): it stands at the long front glass, just above
 * the water, and looks a little down, so the waterline sits near the top under
 * a band of sky and the sand at the bottom. Drag or the wheel's sideways
 * scroll glides along the glass; the wheel / pinch comes closer (through the
 * glass, into the water); A / D (and the arrows, from the page) glide, W / S
 * come closer / back off, Q / E lower / raise. Following a fish works as in
 * the default look (orbiting it), and letting go comes back to the glass.
 *
 * Code layout: everything lives here; web/ocean_scene.js calls in at a few
 * hooks (EvoReef.create(THREE, ctx), reef.on(), reef.rig(), reef.fit(),
 * reef.clamp(), reef.keys(), reef.frame(), reef.regrade(), reef.setWorld()).
 * The fish materials are the scene's own shaders with reef code spliced in at
 * fixed anchors (each must occur exactly once, or the fish keep the default
 * look: fail closed). */
(function () {
  var TAU = Math.PI * 2;
  var LUMA = "vec3(0.2126, 0.7152, 0.0722)";

  /* the reef's water: [realistic, clear], blended by the page's clarity like
   * the scene's CLARITY (drawing only) */
  var GRADE = {
    fog: [[0.045, 0.24, 0.40], [0.11, 0.42, 0.62]],         /* the water far off (and the fish's distance haze) */
    water: [[0.70, 0.82, 0.86], [0.92, 0.97, 0.94]],        /* the tint on the sand: sunlit */
    causticK: [1.1, 1.0],
    fogAt: [0.62, 0.48],                                     /* fog share at the back glass */
    deepTop: [[0.10, 0.44, 0.62], [0.24, 0.66, 0.80]],      /* the water's background just under the surface */
    deepBot: [[0.015, 0.10, 0.22], [0.04, 0.22, 0.42]]      /* ... and looking down */
  };
  var SKY = { top: [0.22, 0.52, 0.86], horizon: [0.74, 0.89, 0.97], cloud: [0.98, 0.99, 1.0], cloudShade: [0.80, 0.87, 0.95],
              hill: [0.24, 0.55, 0.30], hillDark: [0.14, 0.38, 0.24], beach: [0.93, 0.84, 0.62], rock: [0.52, 0.50, 0.47],
              sea: [0.14, 0.50, 0.70], seaHi: [0.62, 0.86, 0.94] };
  var EYE_H = 3;            /* the camera's height above the water at the glass: the surface nearly edge-on */
  var WATERLINE_NDC = 0.70; /* where the front waterline sits, up the visible area */
  var FLOOR_NDC = -0.97;    /* and the front floor edge */
  /* A long lens from far off: the tank seen nearly flat from the side (far
   * fish only a little smaller than near ones, the sand a strip at the
   * bottom), as an aquarium window reads. Following a fish uses the scene's
   * own lens. */
  var REEF_FOV = 6;
  var ZOOM_MAX = 9;         /* the wheel / pinch comes this much closer, at most */

  /* ---------------- shader splicing ---------------- */
  function occurrences(s, sub) { return s.split(sub).length - 1; }
  /* insert code before (or replace) an anchor that must occur exactly once */
  function splice(src, anchor, code, replace) {
    if (occurrences(src, anchor) !== 1) throw new Error("reef: anchor occurs " + occurrences(src, anchor) + " times: " + anchor.trim());
    return src.split(anchor).join(replace ? code : code + "\n" + anchor);
  }
  var A_MAIN = "void main() {";
  var A_ADD = "  vec3 add = vec3(0.0);";
  var A_SEL = "  if (vSel > 0.75) add += uSelect * (0.16 + 0.55 * rim);";
  var A_FOG = "  vec3 murky = mix(col, uFog, fogOf(vWorld));";
  var A_APPW = "  vec3 w = appWorld(geo);";
  var A_GLPOS = "  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);";

  /* the storybook light: three soft value bands of the fish's own colour (the
   * lit band is the colour itself), a darker silhouette edge, and a little
   * darkening with depth; the haze only moves brightness toward the water's */
  /* how far behind the front glass a point is, 0 at the glass .. 1 at the back glass */
  var BEHIND_FN = [
    "uniform vec2 uGlassN; uniform float uGlassC; uniform float uDp;",
    "float behindGlass(vec3 w) { return (uGlassC - dot(w.xz, uGlassN)) / uDp; }"
  ].join("\n");
  var BAND_FN = [
    "uniform float uReefDepthK;",
    BEHIND_FN,
    "float reefBand(vec3 N) {",
    "  float l = max(dot(N, uLight), 0.0) * 0.78 + 0.22 * (0.5 + 0.5 * N.y);",
    "  float b = mix(0.74, 0.88, smoothstep(0.30, 0.36, l));",
    "  return mix(b, 1.0, smoothstep(0.56, 0.62, l));",
    "}",
    "float reefEdge(vec3 N, vec3 V) { return 1.0 - 0.35 * smoothstep(0.62, 0.92, 1.0 - abs(dot(N, V))); }",
    "vec3 reefHaze(vec3 c, vec3 w) {",
    "  float f = 0.32 * clamp(behindGlass(w), 0.0, 1.0), lc = max(dot(c, " + LUMA + "), 1e-3);",
    "  return mix(c, c * (dot(uFog, " + LUMA + ") / lc), f);",
    "}"
  ].join("\n");

  /* the appearance fish (the scene's appearanceShaders): storybook body,
   * cartoon eyes (a round disc on the flank, white with a pupil that looks
   * ahead and down as it sinks, and a lid that blinks), value-only haze */
  function patchApp(vs, fs) {
    vs = splice(vs, A_MAIN, "uniform float uBlinkOn;\nvarying vec4 vEye; varying float vBlink;");
    vs = splice(vs, A_APPW, [
      "  vEye = vec4(0.0); vBlink = 0.0;",
      "  if (aPattern.x > 3.5 && aPattern.x < 4.5) {",
      "    vec3 gc, mc; float rc;",
      "    mBuild(M, vec4(0.0, 0.0, aT.z, aT.w), aPattern, uTime, uWag, minWidth(), gc, mc, rc);",
      "    float r = 0.30 * clamp(M.eye, 0.55, 1.6);",            /* bigger than the gene's eye, never tiny */
      "    geo = gc + vec3(aT.x * r * 1.42, aPattern.z * 0.06, aT.y * r * 1.42);",
      /* the pupil: ahead (toward the head), further ahead in a turn, down while sinking */
      "    vec2 h0 = iA.xy - iA.zw, h1 = iA.zw - iB.xy;",
      "    float turn = abs(h0.x * h1.y - h0.y * h1.x) / max(dot(h0, h0) + dot(h1, h1), 1e-4);",
      "    float ahead = 0.30 + 0.16 * clamp(turn * 6.0, 0.0, 1.0);",
      "    vEye = vec4(aT.xy * 1.42, -ahead + 0.05 * sin(uTime * 0.7 + iX.y * 40.0), -0.26 * clamp(iX.x, -1.0, 1.0));",
      /* a blink every 3.5 to 7.5 s, its own phase per fish */
      "    float per = 3.5 + 4.0 * fract(iX.y * 7.13), ph = fract(uTime / per + iX.y);",
      "    vBlink = uBlinkOn * (1.0 - smoothstep(0.0, 0.022, abs(ph - 0.03)));",
      "  }"
    ].join("\n"));
    fs = splice(fs, A_MAIN, "varying vec4 vEye; varying float vBlink;\n" + BAND_FN);
    fs = splice(fs, A_ADD, [
      "  vec3 rbase = base;",
      "  if (uColourBy > 0.5) {",                                /* the family / brain colour, exactly */
      "    float pc = vPart.w, pr = floor(pc / 65536.0), pg = floor((pc - 65536.0 * pr) / 256.0);",
      "    rbase = vec3(pr, pg, pc - 65536.0 * pr - 256.0 * pg) / 255.0;",
      "  }",
      "  if (fin != 0 && fin != 7) rbase = mix(rbase, vec3(1.0), 0.16 + 0.14 * max(dot(-N, uLight), 0.0));",   /* fins: lighter, lit through */
      "  vec3 rlit = rbase * reefBand(N) * reefEdge(N, V);",
      "  col = rlit * (1.0 - uReefDepthK * depthOf(vWorld.y));",
      "  clear = rlit;"
    ].join("\n"));
    fs = splice(fs, A_SEL, [
      "  if (fin == 4) {",
      "    vec2 e = vEye.xy; float d = length(e);",
      "    if (d > 1.0) discard;",
      "    vec3 ec = vec3(0.98, 0.98, 0.95) * (1.0 - 0.16 * smoothstep(0.70, 0.96, d));",
      "    float pd = length(e - vEye.zw);",
      "    ec = mix(ec, vec3(0.05, 0.06, 0.09), 1.0 - smoothstep(0.40, 0.46, pd));",
      "    ec = mix(ec, vec3(1.0), 1.0 - smoothstep(0.09, 0.14, length(e - vEye.zw - vec2(-0.15, 0.17))));",
      "    vec3 lid = rbase * 0.86;",
      "    ec = mix(ec, lid * 0.55, smoothstep(0.88, 0.97, d));",   /* a soft dark rim */
      "    if (e.y > 1.0 - 2.05 * vBlink) ec = lid;",
      "    col = ec * (1.0 - 0.5 * uReefDepthK * depthOf(vWorld.y)); clear = ec;",
      "  }"
    ].join("\n"));
    fs = splice(fs, A_FOG, "  vec3 murky = reefHaze(col, vWorld);", true);
    return { vs: vs, fs: fs };
  }

  /* the plain fish and the predators (the scene's FISH_VS / FISH_FS) */
  function patchPlain(fs) {
    fs = splice(fs, A_MAIN, BAND_FN);
    fs = splice(fs, A_ADD, [
      "  vec3 rbase = vCol;",
      "  if (vPart > 0.5 && vPart < 1.5) rbase = mix(rbase, vec3(1.0), 0.18);",
      "  vec3 rlit = rbase * reefBand(N) * reefEdge(N, V);",
      "  col = rlit * (1.0 - uReefDepthK * depthOf(vWorld.y));",
      "  clear = rlit;"
    ].join("\n"));
    fs = splice(fs, A_FOG, "  vec3 murky = reefHaze(col, vWorld);", true);
    return fs;
  }

  /* ---- the predators' faces: big ember eyes with a slit pupil while they
   * hunt (dull amber once fed) under a heavy brow sloping to the snout. Their
   * own small template bent along the predator's spine by the scene's
   * FISH_CORE (fishWorld), so they swim with the body ---- */
  function faceTemplate() {
    var pos = [], loc = [];
    function quad(u0, u1, z0, z1, y, kind, slope) {   /* u along the spine, z up, in body units; loc: local x, y, kind */
      var c = [[u0, z0, -1, -1], [u1, z0, 1, -1], [u1, z1, 1, 1], [u0, z1, -1, 1]];
      [0, 1, 2, 0, 2, 3].forEach(function (i) {
        var q = c[i], dz = slope ? slope * (q[2] + 1) * 0.5 : 0;
        pos.push(q[0], y, q[1] + dz); loc.push(q[2], q[3], kind);
      });
    }
    [1, -1].forEach(function (sd) {
      /* the eye: a disc (drawn round in the shader) on the flank */
      quad(-0.075, 0.075, 0.02, 0.62, sd * 0.80, 0, 0);
      /* the brow: a slab over the eye, lower toward the snout */
      quad(-0.09, 0.10, 0.52, 0.66, sd * 0.84, 1, 0.16);
    });
    return { pos: new Float32Array(pos), loc: new Float32Array(loc) };
  }
  var FACE_FS = [
    "uniform float uTime;",
    "varying vec3 vWorld; varying vec3 vLoc; varying float vEmber;",
    "void main() {",
    "  vec2 e = vLoc.xy;",
    "  if (vLoc.z > 0.5) {",                                   /* the brow */
    "    gl_FragColor = vec4(mix(vec3(0.08, 0.09, 0.12), vec3(0.22, 0.24, 0.30), smoothstep(0.2, 1.0, e.y)), 1.0);",
    "    return;",
    "  }",
    "  float d = length(e);",
    "  if (d > 1.0) discard;",
    "  vec3 iris = vEmber > 0.5 ? vec3(1.0, 0.46, 0.12) * (0.92 + 0.08 * sin(uTime * 6.0)) : vec3(0.62, 0.42, 0.16);",
    "  vec3 c = mix(iris * 1.12, iris * 0.72, smoothstep(0.1, 0.9, d));",
    "  float slit = abs(e.x) / max(0.04, 0.24 * (1.0 - e.y * e.y));",   /* a slit pupil, narrower at its ends */
    "  c = mix(c, vec3(0.03, 0.02, 0.02), 1.0 - smoothstep(0.85, 1.0, slit));",
    "  c = mix(c, vec3(1.0, 0.95, 0.85), 1.0 - smoothstep(0.09, 0.15, length(e - vec2(-0.32, 0.36))));",
    "  c = mix(c, vec3(0.05, 0.04, 0.05), smoothstep(0.86, 0.97, d));",
    "  gl_FragColor = vec4(c, 1.0);",
    "}"
  ].join("\n");

  /* ---------------- the sky, the sea band, the waterline ---------------- */
  var DOME_VS = [
    "varying vec3 vWorld;",
    "void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }"
  ].join("\n");
  var NOISE = [
    "float rh(vec2 p) { vec3 p3 = fract(p.xyx * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }",
    "float rn(vec2 p) { vec2 i = floor(p), f = fract(p), u = f * f * (3.0 - 2.0 * f);",
    "  return mix(mix(rh(i), rh(i + vec2(1.0, 0.0)), u.x), mix(rh(i + vec2(0.0, 1.0)), rh(i + vec2(1.0, 1.0)), u.x), u.y); }",
    "float rfbm(vec2 p) { return 0.55 * rn(p) + 0.28 * rn(p * 2.03 + 7.1) + 0.17 * rn(p * 4.11 - 3.7); }"
  ].join("\n");
  /* Seen from above the water: the sky (a gradient, the sun's glow, soft
   * drifting clouds) over an island on the horizon: green hills in two value
   * bands with a beach. Seen from below (or looking down through the glass):
   * the water's own light, brighter toward the surface. */
  var DOME_FS = [
    "uniform vec3 uSkyTop, uSkyHorizon, uCloud, uCloudShade, uHill, uHillDark, uBeach, uRock;",
    "uniform vec3 uDeepTop, uDeepBot, uSunDir, uSea; uniform float uTime; uniform float uAz0;",
    /* the sky band's height in the view (radians of elevation): the island and
     * the clouds are scaled to it, a backdrop sized for the window */
    "uniform float uSkySpan; uniform vec3 uFogC;",
    "uniform vec2 uGlassN; uniform float uGlassC;",
    "varying vec3 vWorld;",
    NOISE,
    /* the island's height (elevation, as V.y) at azimuth a (radians from the view's start) */
    "float hill(float a, float c, float w, float h) { float x = (a - c) / w; return h * max(0.0, 1.0 - x * x) * (0.85 + 0.15 * cos(x * 7.0)); }",
    "float island(float a, float k) {",                            /* k: the view's width in radians, so the island spans part of it */
    "  float h = max(hill(a, -0.18 * k, 0.26 * k, 0.62), hill(a, 0.02 * k, 0.14 * k, 0.44));",
    "  h = max(h, hill(a, 0.40 * k, 0.10 * k, 0.30));",
    "  return h > 0.0 ? h + 0.06 : 0.0;",                           /* the beach under the hills */
    "}",
    "void main() {",
    "  vec3 V = normalize(vWorld - cameraPosition);",
    /* below the horizon from above the water: the sea's top where the ray
     * meets the water behind the front glass (past the sea band's far edge),
     * else the water seen through the glass */
    "  bool under = cameraPosition.y < 0.0;",
    "  if (!under && V.y < 0.0) {",
    "    vec2 p0 = cameraPosition.xz + V.xz * (cameraPosition.y / -V.y);",
    "    if (dot(p0, uGlassN) - uGlassC < 0.0) { gl_FragColor = vec4(mix(uSea, uSkyHorizon, 0.55), 1.0); return; }",
    "    under = true;",
    "  }",
    /* under water: the water's own colour at eye level (the sand far off
     * fades into the same colour, so there is no seam), lighter looking up,
     * deeper looking down */
    "  if (under) {",
    "    vec3 c = V.y > 0.0 ? mix(uFogC, uDeepTop, smoothstep(0.0, 0.5, V.y)) : mix(uFogC, uDeepBot, smoothstep(0.0, 0.5, -V.y));",
    "    gl_FragColor = vec4(c, 1.0);",
    "    return;",
    "  }",
    "  float e = V.y / max(uSkySpan, 1e-4);",                     /* 0 at the horizon, 1 at the top of the view */
    "  vec3 col = mix(uSkyHorizon, uSkyTop, smoothstep(0.0, 1.1, e));",
    "  col += vec3(1.0, 0.94, 0.78) * pow(max(dot(V, uSunDir), 0.0), 4.0) * 0.10;",
    "  float a = atan(V.x, -V.z) - uAz0;",
    "  a = mod(a + 3.14159265, 6.2831853) - 3.14159265;",
    "  float k = uSkySpan * 4.0;",                                 /* about the view's width */
    /* clouds: soft puffs in the upper part of the band, drifting */
    /* a few soft puffs: broad blobs along the band, flat-bottomed, lit from above */
    "  vec2 cp = vec2(a / k * 2.2 + uTime * 0.004, e * 1.3);",
    "  float cl = rfbm(cp * vec2(1.0, 2.2)) * smoothstep(0.40, 0.70, e) * (1.0 - 0.35 * smoothstep(0.9, 1.3, e));",
    "  float cm = smoothstep(0.43, 0.47, cl);",
    "  vec3 cloudC = mix(uCloudShade, uCloud, smoothstep(0.44, 0.56, cl + 0.10 * (e - 0.55)));",
    "  col = mix(col, cloudC, cm * 0.95);",
    /* the island: hills in two value bands over a beach, a little hazed */
    "  float h = island(a, k);",
    "  if (h > 0.0 && e < h) {",
    "    float beach = 0.06;",
    "    float n = rn(vec2(a / k * 60.0, e * 9.0));",
    "    vec3 land = e < beach ? uBeach : mix(uHillDark, uHill, step(0.5, n * 0.55 + (e - beach) / max(h - beach, 1e-4) * 0.75));",
    "    col = mix(land, uSkyHorizon, 0.28);",
    "  }",
    "  gl_FragColor = vec4(col, 1.0);",
    "}"
  ].join("\n");
  /* the sea seen from just above it, behind the front glass: nearly a mirror
   * of the sky at grazing angles (the band under the horizon), with sparkles */
  var SEA_FS = [
    "uniform vec3 uSea, uSeaHi, uSkyHorizon; uniform float uTime; uniform sampler2D uCaustic;",
    "varying vec3 vWorld;",
    "void main() {",
    "  if (cameraPosition.y <= vWorld.y) discard;",
    "  vec3 V = normalize(vWorld - cameraPosition);",
    "  float g = 1.0 - smoothstep(0.0, 0.35, -V.y);",            /* 1 at grazing angles */
    "  vec2 uv = vWorld.xz / 90.0;",
    "  float s1 = texture2D(uCaustic, uv + vec2(uTime * 0.03, uTime * 0.017)).r;",
    "  float s2 = texture2D(uCaustic, uv * 0.61 + vec2(-uTime * 0.021, uTime * 0.026)).r;",
    "  vec3 col = mix(uSea, uSkyHorizon, 0.55 * g) + uSeaHi * smoothstep(0.55, 0.95, min(s1, s2) * 1.6) * (0.25 + 0.5 * g);",
    "  gl_FragColor = vec4(col, 0.55 + 0.42 * g);",
    "}"
  ].join("\n");
  /* the waterline on the front glass: a wavy bright meniscus, a pale band under it */
  var LINE_FS = [
    "uniform float uTime; uniform float uMove;",
    "varying vec3 vWorld; varying vec2 vUv;",
    "void main() {",
    "  float x = vUv.x;",
    "  float top = 0.5 + (0.55 * sin(x * 0.045 + uTime * 1.4 * uMove) + 0.35 * sin(x * 0.11 - uTime * 0.9 * uMove)) * 0.9;",
    "  float y = vUv.y;",
    "  if (y > top + 0.25) discard;",
    "  float line = 1.0 - smoothstep(0.0, 0.35, abs(y - top));",
    "  float band = smoothstep(top - 3.2, top - 0.2, y) * (1.0 - smoothstep(top - 0.2, top + 0.25, y));",
    "  vec3 col = mix(vec3(0.70, 0.93, 0.98), vec3(1.0), line);",
    "  float a = 0.20 * band + 0.75 * line;",
    "  if (a < 0.01) discard;",
    "  gl_FragColor = vec4(col, a);",
    "}"
  ].join("\n");
  var LINE_VS = [
    "attribute vec2 uv2; varying vec3 vWorld; varying vec2 vUv;",
    "void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; vUv = uv2; gl_Position = projectionMatrix * viewMatrix * w; }"
  ].join("\n");

  /* ---------------- the reef (one merged mesh) ---------------- */
  var DECOR_VS = [
    "attribute vec3 color; attribute float aOut;",
    "varying vec3 vWorld; varying vec3 vCol; varying float vOut;",
    "void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; vCol = color; vOut = aOut;",
    "  gl_Position = projectionMatrix * viewMatrix * w; }"
  ].join("\n");
  /* storybook light on flat facets, the water's haze (more for what stands
   * outside the tank, so it reads as the far reef); in the flashlight, true
   * colours */
  function decorFS(FOG_FN, BEAM_FN) {
    return [
      "uniform vec3 uLight;",
      FOG_FN, BEAM_FN, BEHIND_FN,
      "varying vec3 vWorld; varying vec3 vCol; varying float vOut;",
      "void main() {",
      "  vec3 N = normalize(cross(dFdx(vWorld), dFdy(vWorld)));",
      "  vec3 V = normalize(cameraPosition - vWorld);",
      "  if (dot(N, V) < 0.0) N = -N;",
      "  float l = max(dot(N, uLight), 0.0) * 0.75 + 0.25 * (0.5 + 0.5 * N.y);",
      "  float b = mix(0.62, 0.82, smoothstep(0.28, 0.34, l)); b = mix(b, 1.0, smoothstep(0.56, 0.62, l));",
      "  vec3 c = vCol * b;",
      /* the haze: by how far behind the front glass (the far reef fades to the water's blue), more outside the tank */
      "  float bg = behindGlass(vWorld);",
      "  float f = clamp(0.04 + 0.20 * clamp(bg, 0.0, 1.0) + 0.06 * vOut + 0.30 * clamp((bg - 1.0) * 2.5, 0.0, 1.0), 0.0, 0.7);",
      "  vec3 murky = mix(c, uFog, f);",
      "  float bk = beamOf(vWorld);",
      "  gl_FragColor = vec4(bk > 0.0 ? mix(murky, c, bk) : murky, 1.0);",
      "}"
    ].join("\n");
  }

  /* a seeded generator (the reef never draws from the simulation's random numbers) */
  function rng(seed) {
    var s = (seed >>> 0) || 0x9e3779b9;
    return function () { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
  }
  function hexc(h) { return [((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255]; }
  var PAL = {
    rock: [0x8c8478, 0x9a8f7f, 0x7d7a74, 0xa59a86], rockFar: [0x6f7b85, 0x7d8890, 0x66727c],
    pebble: [0xb9ab92, 0xa7987e, 0xcbbd9f, 0x8f8a80],
    shell: [0xf2dcc7, 0xf6c9b8, 0xeedfb6, 0xf3e7d8],
    crust: [0xe8836f, 0xc86fa6, 0xf0a648, 0x9b7fd1],
    coral: [0xf26b4f, 0xff9a3c, 0xe2559a, 0xb26be0, 0xffd34a, 0xf7836b, 0x47c3b0],
    brain: [0xd99a5b, 0xe7b46c, 0xc77c86, 0x9fbf6a],
    stone: [0xcfc6b3, 0xbdb39d, 0xd9d0bd]
  };

  /* builders: each appends flat triangles (position, colour, outside flag) */
  function Builder() {
    var P = [], Cc = [], O = [];
    function tri(a, b, c, col, out) {
      P.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
      for (var i = 0; i < 3; i++) { Cc.push(col[0], col[1], col[2]); O.push(out); }
    }
    return { tri: tri, P: P, C: Cc, O: O };
  }
  function shade(col, k) { return [col[0] * k, col[1] * k, col[2] * k]; }
  /* a lumpy faceted dome: rocks, pebbles, brain coral, crusts */
  function dome(B, r, x, y, z, rad, hgt, col, out, sides, rings) {
    sides = sides || 7; rings = rings || 3;
    var pts = [], i, j;
    for (j = 0; j <= rings; j++) {
      var t = j / rings, row = [];
      var rr = rad * Math.cos(t * Math.PI / 2) * (j === rings ? 0 : 1), yy = hgt * Math.sin(t * Math.PI / 2);
      for (i = 0; i < sides; i++) {
        var a = i / sides * TAU + r() * 0.35, jr = 0.78 + 0.44 * r();
        row.push([x + Math.cos(a) * rr * jr, y + yy * (0.85 + 0.3 * r()) * (j === 0 ? 0 : 1), z + Math.sin(a) * rr * jr]);
      }
      pts.push(row);
    }
    for (j = 0; j < rings; j++) for (i = 0; i < sides; i++) {
      var i1 = (i + 1) % sides, a0 = pts[j][i], a1 = pts[j][i1], b0 = pts[j + 1][i], b1 = pts[j + 1][i1];
      var c = shade(col, 0.9 + 0.2 * r());
      B.tri(a0, a1, b1, c, out);
      if (j + 1 < rings) B.tri(a0, b1, b0, c, out);
    }
  }
  /* a tapered branch (coral fingers, kelp-free): a hexagonal tube from p0 along dir */
  function branch(B, r, p0, dir, len, r0, r1, col, out) {
    var n = 5, i, ax = dir, up = Math.abs(ax[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
    var s = [ax[1] * up[2] - ax[2] * up[1], ax[2] * up[0] - ax[0] * up[2], ax[0] * up[1] - ax[1] * up[0]];
    var sl = Math.hypot(s[0], s[1], s[2]); s = [s[0] / sl, s[1] / sl, s[2] / sl];
    var t = [ax[1] * s[2] - ax[2] * s[1], ax[2] * s[0] - ax[0] * s[2], ax[0] * s[1] - ax[1] * s[0]];
    var p1 = [p0[0] + ax[0] * len, p0[1] + ax[1] * len, p0[2] + ax[2] * len];
    var A = [], Bb = [];
    for (i = 0; i < n; i++) {
      var a = i / n * TAU, ca = Math.cos(a), sa = Math.sin(a);
      A.push([p0[0] + (s[0] * ca + t[0] * sa) * r0, p0[1] + (s[1] * ca + t[1] * sa) * r0, p0[2] + (s[2] * ca + t[2] * sa) * r0]);
      Bb.push([p1[0] + (s[0] * ca + t[0] * sa) * r1, p1[1] + (s[1] * ca + t[1] * sa) * r1, p1[2] + (s[2] * ca + t[2] * sa) * r1]);
    }
    for (i = 0; i < n; i++) {
      var i1 = (i + 1) % n, c = shade(col, 0.88 + 0.24 * r());
      B.tri(A[i], A[i1], Bb[i1], c, out); B.tri(A[i], Bb[i1], Bb[i], c, out);
      B.tri(Bb[i], Bb[i1], p1, shade(col, 1.12), out);   /* the rounded tip, a little lighter */
    }
    return p1;
  }
  function coralTree(B, r, x, y, z, hgt, col, out) {
    var trunks = 3 + Math.floor(r() * 4);
    for (var k = 0; k < trunks; k++) {
      var a = r() * TAU, tilt = 0.15 + 0.45 * r();
      var dir = [Math.cos(a) * tilt, 1, Math.sin(a) * tilt], dl = Math.hypot(dir[0], dir[1], dir[2]);
      dir = [dir[0] / dl, dir[1] / dl, dir[2] / dl];
      var len = hgt * (0.45 + 0.35 * r()), base = [x + (r() - 0.5) * hgt * 0.25, y, z + (r() - 0.5) * hgt * 0.25];
      var tip = branch(B, r, base, dir, len, hgt * 0.07, hgt * 0.045, col, out);
      var forks = 1 + Math.floor(r() * 3);
      for (var f = 0; f < forks; f++) {
        var fa = r() * TAU, ft = 0.5 + 0.6 * r();
        var fd = [dir[0] + Math.cos(fa) * ft, dir[1] + 0.2, dir[2] + Math.sin(fa) * ft], fl = Math.hypot(fd[0], fd[1], fd[2]);
        branch(B, r, tip, [fd[0] / fl, fd[1] / fl, fd[2] / fl], hgt * (0.25 + 0.25 * r()), hgt * 0.045, hgt * 0.025, col, out);
      }
    }
  }
  /* a fan-shaped shell lying on the sand */
  function shell(B, r, x, y, z, s, col) {
    var a0 = r() * TAU, n = 6, apex = [x, y + s * 0.35, z];
    for (var i = 0; i < n; i++) {
      var a = a0 + (i / n - 0.5) * 2.2, b = a0 + ((i + 1) / n - 0.5) * 2.2;
      var p = [x + Math.cos(a) * s, y + 0.05, z + Math.sin(a) * s], q = [x + Math.cos(b) * s, y + 0.05, z + Math.sin(b) * s];
      B.tri(apex, p, q, shade(col, i % 2 ? 0.92 : 1.05), 0);
    }
  }
  /* an original ruined column: a fluted shaft broken at an angle, on a square base */
  function column(B, r, x, y, z, rad, hgt, col, out, fallen) {
    var n = 10, i, a, base = [], top = [];
    var ax = fallen ? [Math.cos(r() * TAU), 0.0, 0] : [0, 1, 0];
    if (fallen) { ax[2] = Math.sqrt(1 - ax[0] * ax[0]); }
    var brk = 0.10 * hgt * (r() - 0.5);
    for (i = 0; i < n; i++) {
      a = i / n * TAU;
      var fl = i % 2 ? 0.92 : 1.0, cx = Math.cos(a) * rad * fl, cz = Math.sin(a) * rad * fl;
      if (!fallen) {
        base.push([x + cx, y, z + cz]);
        top.push([x + cx, y + hgt + brk * Math.cos(a), z + cz]);
      } else {
        var px = [-ax[2], 0, ax[0]];
        base.push([x + px[0] * cx, y + rad + cz, z + px[2] * cx]);
        top.push([x + px[0] * cx + ax[0] * hgt, y + rad + cz, z + px[2] * cx + ax[2] * hgt]);
      }
    }
    for (i = 0; i < n; i++) {
      var i1 = (i + 1) % n, c = shade(col, 0.86 + 0.22 * r());
      B.tri(base[i], base[i1], top[i1], c, out); B.tri(base[i], top[i1], top[i], c, out);
      var ctr = fallen ? [x + ax[0] * hgt, y + rad, z + ax[2] * hgt] : [x, y + hgt, z];
      B.tri(top[i], top[i1], ctr, shade(col, 1.08), out);
    }
    if (!fallen) {   /* the plinth */
      var s = rad * 1.35, h = rad * 0.5;
      var q = [[x - s, y, z - s], [x + s, y, z - s], [x + s, y, z + s], [x - s, y, z + s]];
      var qt = q.map(function (p) { return [p[0], y + h, p[2]]; });
      for (i = 0; i < 4; i++) {
        var j = (i + 1) % 4;
        B.tri(q[i], q[j], qt[j], shade(col, 0.9), out); B.tri(q[i], qt[j], qt[i], shade(col, 0.9), out);
      }
      B.tri(qt[0], qt[1], qt[2], shade(col, 1.05), out); B.tri(qt[0], qt[2], qt[3], shade(col, 1.05), out);
    }
  }

  /* The reef, in the tank's own frame: a along the front glass (-L/2 .. L/2),
   * b behind it (0 at the front glass .. Dp at the back glass). Inside: low
   * things only (pebbles, shells, flat coral crusts, at most 6 units). Behind
   * the back glass and beyond the ends: rocks, coral trees, brain coral and a
   * few ruined columns, up to the surface. In front of the glass: a few low
   * rocks on the sand. */
  function buildReef(L, Dp, floorY, seed) {
    var r = rng(seed), B = Builder(), i;
    function pick(arr) { return hexc(arr[Math.floor(r() * arr.length) % arr.length]); }
    var put = [];
    function place(a, b, k) { put.push([a, b, k]); }
    /* inside the tank */
    var area = L * Dp / (1920 * 1080);
    for (i = 0; i < Math.round(150 * area); i++) place((r() - 0.5) * (L - 16), 8 + r() * (Dp - 16), "pebble");
    for (i = 0; i < Math.round(40 * area); i++) place((r() - 0.5) * (L - 16), 8 + r() * (Dp - 16), "shell");
    for (i = 0; i < Math.round(26 * area); i++) place((r() - 0.5) * (L - 30), 15 + r() * (Dp - 30), "crust");
    /* behind the back glass */
    var span = L + 900;
    for (i = 0; i < Math.round(span / 120); i++) place((r() - 0.5) * span, Dp + 40 + r() * 340, "rock");
    for (i = 0; i < Math.round(span / 50); i++) place((r() - 0.5) * span, Dp + 25 + r() * 260, "coral");
    for (i = 0; i < Math.round(span / 160); i++) place((r() - 0.5) * span, Dp + 30 + r() * 300, "brain");
    for (i = 0; i < 4; i++) place((r() - 0.5) * L * 0.9, Dp + 120 + r() * 220, "column");
    place((r() - 0.5) * L * 0.6, Dp + 90 + r() * 120, "fallen");
    /* beyond the ends */
    [-1, 1].forEach(function (sd) {
      for (var k = 0; k < 10; k++) place(sd * (L / 2 + 50 + r() * 380), -60 + r() * (Dp + 380), k % 3 ? "coral" : "rock");
      for (k = 0; k < 4; k++) place(sd * (L / 2 + 40 + r() * 300), -40 + r() * (Dp + 200), "brain");
    });
    /* in front of the glass: low rocks, framing the bottom of the view */
    for (i = 0; i < Math.round(L / 160); i++) place((r() - 0.5) * (L + 200), -(20 + r() * 110), "lowrock");
    var y = floorY;
    put.forEach(function (p) {
      var a = p[0], b = p[1], out = b > Dp || b < 0 || Math.abs(a) > L / 2 ? 1 : 0;
      switch (p[2]) {
        case "pebble": dome(B, r, a, y, b, 1.5 + 2.5 * r(), 0.8 + 1.6 * r(), pick(PAL.pebble), 0, 5, 2); break;
        case "shell": shell(B, r, a, y, b, 1.6 + 1.8 * r(), pick(PAL.shell)); break;
        case "crust": dome(B, r, a, y, b, 5 + 7 * r(), 2 + 3.5 * r(), pick(PAL.crust), 0, 8, 2); break;
        case "rock": dome(B, r, a, y, b, 30 + 60 * r(), 35 + 110 * r(), pick(PAL.rockFar), 1, 8, 4); break;
        case "lowrock": dome(B, r, a, y, b, 10 + 18 * r(), 6 + 12 * r(), pick(PAL.rock), 0, 7, 3); break;
        case "coral": coralTree(B, r, a, y, b, 35 + 75 * r(), pick(PAL.coral), out); break;
        case "brain": dome(B, r, a, y, b, 14 + 18 * r(), 12 + 16 * r(), pick(PAL.brain), out, 9, 3); break;
        case "column": column(B, r, a, y, b, 9 + 5 * r(), 90 + 150 * r(), pick(PAL.stone), 1, false); break;
        case "fallen": column(B, r, a, y, b, 10, 120 + 60 * r(), pick(PAL.stone), 1, true); break;
      }
    });
    return B;
  }

  /* ================= the reef object ================= */
  function create(THREE, ctx) {
    var cam = ctx.camera, controls = ctx.controls, canvas = ctx.canvas, common = ctx.common;
    var on = false, failed = "";
    var objs = [];   /* everything the reef added to the scene */
    function add(o, order) { o.renderOrder = order; o.frustumCulled = false; o.visible = false; ctx.scene.add(o); objs.push(o); ctx.watch(o, "other"); return o; }
    function v3(a) { return new THREE.Vector3(a[0], a[1], a[2]); }
    var U = {   /* the reef's own uniforms */
      uReefDepthK: { value: 0.22 }, uBlinkOn: { value: 0 },
      uSkyTop: { value: v3(SKY.top) }, uSkyHorizon: { value: v3(SKY.horizon) }, uCloud: { value: v3(SKY.cloud) },
      uCloudShade: { value: v3(SKY.cloudShade) }, uHill: { value: v3(SKY.hill) }, uHillDark: { value: v3(SKY.hillDark) },
      uBeach: { value: v3(SKY.beach) }, uRock: { value: v3(SKY.rock) }, uSea: { value: v3(SKY.sea) }, uSeaHi: { value: v3(SKY.seaHi) },
      uDeepTop: { value: v3(GRADE.deepTop[1]) }, uDeepBot: { value: v3(GRADE.deepBot[1]) },
      uSunDir: { value: v3(ctx.light) }, uAz0: { value: 0 }, uMove: { value: 1 },
      uGlassN: { value: new THREE.Vector2(0, 1) }, uGlassC: { value: 540 },   /* the front glass: dot(xz, N) = C */
      uDp: { value: 1080 }, uSkySpan: { value: 0.02 }
    };
    function glassU(u) { u.uGlassN = U.uGlassN; u.uGlassC = U.uGlassC; u.uDp = U.uDp; return u; }

    /* ---- the sky dome: an inside-out box around the camera, drawn first ---- */
    var dome0 = (function () {
      var s = 1, P = [], f = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]];
      [[0, 1, 2, 3], [5, 4, 7, 6], [4, 0, 3, 7], [1, 5, 6, 2], [3, 2, 6, 7], [4, 5, 1, 0]].forEach(function (q) {
        [q[0], q[1], q[2], q[0], q[2], q[3]].forEach(function (k) { P.push(f[k][0] * s, f[k][1] * s, f[k][2] * s); });
      });
      var g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(P), 3));
      var m = new THREE.ShaderMaterial({ vertexShader: DOME_VS, fragmentShader: DOME_FS, side: THREE.DoubleSide,
        uniforms: { uSkyTop: U.uSkyTop, uSkyHorizon: U.uSkyHorizon, uCloud: U.uCloud, uCloudShade: U.uCloudShade,
                    uHill: U.uHill, uHillDark: U.uHillDark, uBeach: U.uBeach, uRock: U.uRock,
                    uDeepTop: U.uDeepTop, uDeepBot: U.uDeepBot, uSunDir: U.uSunDir, uTime: common.uTime, uAz0: U.uAz0,
                    uSea: U.uSea, uGlassN: U.uGlassN, uGlassC: U.uGlassC, uSkySpan: U.uSkySpan, uFogC: common.uFog },
        depthWrite: false, depthTest: false });
      return add(new THREE.Mesh(g, m), -10);
    })();

    /* ---- the sea band: the water's top, from the front glass back ---- */
    var seaMat = new THREE.ShaderMaterial({ vertexShader: DOME_VS, fragmentShader: SEA_FS,
      uniforms: { uSea: U.uSea, uSeaHi: U.uSeaHi, uSkyHorizon: U.uSkyHorizon, uTime: common.uTime, uCaustic: ctx.caustic },
      transparent: true, depthWrite: false, side: THREE.DoubleSide });
    var sea = add(new THREE.Mesh(new THREE.PlaneGeometry(1, 1), seaMat), 7);
    sea.rotation.x = -Math.PI / 2;

    /* ---- the waterline on the front glass ---- */
    var lineGeo = new THREE.BufferGeometry();
    var lineMat = new THREE.ShaderMaterial({ vertexShader: LINE_VS, fragmentShader: LINE_FS,
      uniforms: { uTime: common.uTime, uMove: U.uMove }, transparent: true, depthWrite: false, side: THREE.DoubleSide });
    var waterline = add(new THREE.Mesh(lineGeo, lineMat), 9);

    /* ---- the reef: one merged mesh, rebuilt with the tank ---- */
    var decorMat = new THREE.ShaderMaterial({ vertexShader: DECOR_VS, fragmentShader: decorFS(ctx.FOG_FN, ctx.BEAM_FN),
      uniforms: glassU(ctx.beamUniforms({ uLight: common.uLight, uFog: common.uFog, uFogDensity: common.uFogDensity })) });
    var decor = add(new THREE.Mesh(new THREE.BufferGeometry(), decorMat), 0);

    /* ---- the predators' faces ---- */
    var faceTpl = faceTemplate();
    var faceMat = null, face = null, faceGeoFor = null;
    function buildFace() {
      var pk = ctx.preds();
      if (!pk || !pk.geo || faceGeoFor === pk.geo) return;
      if (!faceMat) {
        faceMat = new THREE.ShaderMaterial({
          vertexShader: ctx.FISH_CORE + "\nattribute vec3 aLoc;\nvarying vec3 vWorld; varying vec3 vLoc; varying float vEmber;\n" +
            "void main() { vec3 w = fishWorld(); vWorld = w; vLoc = aLoc; vEmber = iBody.w; gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0); }",
          fragmentShader: FACE_FS,
          uniforms: { uHalf: common.uHalf, uTime: common.uTime, uWag: ctx.fishUniforms.uWag, uWalls: common.uWalls },
          side: THREE.DoubleSide });
      }
      var g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(faceTpl.pos, 3));
      g.setAttribute("aLoc", new THREE.BufferAttribute(faceTpl.loc, 3));
      ["iA", "iB", "iC", "iCol", "iBody", "iX"].forEach(function (n) { g.setAttribute(n, pk.geo.attributes[n]); });
      g.setAttribute("part", new THREE.BufferAttribute(new Float32Array(faceTpl.pos.length / 3), 1));
      g.instanceCount = 0;
      if (face) { face.geometry.dispose(); face.geometry = g; }
      else face = add(new THREE.Mesh(g, faceMat), 2);
      faceGeoFor = pk.geo;
    }

    /* ---- the fish materials: the scene's shaders with the reef spliced in ---- */
    var mats = { app: null, appFor: null, plain: null };   /* reef copies */
    var saved = new Map();   /* mesh -> its own material */
    function reefCopy(base, vs, fs) {
      var u = glassU(Object.assign({}, base.uniforms, { uReefDepthK: U.uReefDepthK, uBlinkOn: U.uBlinkOn }));
      return new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, uniforms: u, side: base.side });
    }
    function swapIn(mesh, mat) {
      if (!mesh || !mat || mesh.material === mat) return;
      if (!saved.has(mesh)) saved.set(mesh, mesh.material);
      mesh.material = mat;
    }
    function swapOut() { saved.forEach(function (m, mesh) { mesh.material = m; }); saved.clear(); }
    function fishMaterials() {
      if (failed) return;
      try {
        var ak = ctx.appKind();
        if (ak && ak.mat && mats.appFor !== ak) {
          var p = patchApp(ak.shaders.vs, ak.shaders.fs);
          mats.app = reefCopy(ak.mat, p.vs, p.fs); mats.appFor = ak;
        }
        if (!mats.plain) mats.plain = reefCopy(ctx.fishMat, ctx.fishMat.vertexShader, patchPlain(ctx.fishMat.fragmentShader));
        if (ak) { swapIn(ak.mesh, mats.app); swapIn(ak.bmesh, mats.app); }
        var fk = ctx.fishKind(), pk = ctx.preds();
        if (fk) swapIn(fk.mesh, mats.plain);
        if (pk) swapIn(pk.mesh, mats.plain);
      } catch (e) {
        failed = String(e && e.message || e);
        console.warn("finfolk: the reef's fish shaders could not be built; the fish keep the default look", e);
        swapOut();
      }
    }

    /* ---- the tank's frame: the front glass on the long side ---- */
    var F = { land: true, L: 1920, Dp: 1080, glass: 540, along: new THREE.Vector3(1, 0, 0), out: new THREE.Vector3(0, 0, 1) };
    function frameOf() {
      var st = ctx.state();
      F.land = st.W >= st.H;
      F.L = F.land ? st.W : st.H; F.Dp = F.land ? st.H : st.W;
      F.glass = F.land ? st.halfH : st.halfW;
      if (F.land) { F.along.set(1, 0, 0); F.out.set(0, 0, 1); } else { F.along.set(0, 0, 1); F.out.set(-1, 0, 0); }
      return st;
    }
    /* a point in the tank's frame (a along the glass, b behind it, y up) -> three */
    function toWorld(a, b, y, out) {
      out = out || new THREE.Vector3();
      out.copy(F.along).multiplyScalar(a).addScaledVector(F.out, F.glass - b);
      out.y = y;
      return out;
    }
    var builtFor = "";
    function build() {
      var st = frameOf(), key = [st.W, st.H, st.TD, st.WALLS ? 1 : 0].join("x");
      if (key === builtFor) return;
      builtFor = key;
      /* the reef */
      var R = buildReef(F.L, F.Dp, st.FLOOR_Y, 0x5eef + st.W * 7 + st.H * 13);
      var n = R.P.length / 3, P = new Float32Array(R.P.length), tmp = new THREE.Vector3();
      for (var i = 0; i < n; i++) {
        toWorld(R.P[3 * i], R.P[3 * i + 2], R.P[3 * i + 1], tmp);
        P[3 * i] = tmp.x; P[3 * i + 1] = tmp.y; P[3 * i + 2] = tmp.z;
      }
      var g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(P, 3));
      g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(R.C), 3));
      g.setAttribute("aOut", new THREE.BufferAttribute(new Float32Array(R.O), 1));
      decor.geometry.dispose(); decor.geometry = g;
      /* the sea band: from the front glass back, far beyond the tank */
      var far = 30000;
      toWorld(0, far / 2, 0.3, tmp);
      sea.position.copy(tmp);
      sea.scale.set(F.land ? far * 2 : far, F.land ? far : far * 2, 1);   /* the plane's x is three's X, its y three's -Z */
      U.uGlassN.value.set(F.out.x, F.out.z);
      U.uGlassC.value = F.glass;
      U.uDp.value = Math.max(1, F.Dp);
      /* the waterline strip on the front glass: a along it, y in [-3.5, 1.5] */
      var half = F.L / 2 + 900, ys = [-3.5, 1.8], PL = [], UV = [];
      var c4 = [[-half, ys[0]], [half, ys[0]], [half, ys[1]], [-half, ys[1]]];
      [0, 1, 2, 0, 2, 3].forEach(function (k) {
        toWorld(c4[k][0], -0.6, c4[k][1], tmp);
        PL.push(tmp.x, tmp.y, tmp.z); UV.push(c4[k][0], c4[k][1]);
      });
      lineGeo.dispose();
      lineGeo = new THREE.BufferGeometry();
      lineGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(PL), 3));
      lineGeo.setAttribute("uv2", new THREE.BufferAttribute(new Float32Array(UV), 2));
      waterline.geometry = lineGeo;
      /* the island ahead-left of the view, whichever side the glass is on */
      U.uAz0.value = F.land ? 0 : Math.PI / 2;
    }

    /* ---- framing: the camera at the front glass ---- */
    var glideA = 0;   /* where along the glass the view is (the tank's frame) */
    function visible() {
      var st = ctx.state(), ins = st.insets;
      var vw = Math.max(1, st.cw - ins.left - ins.right), vh = Math.max(1, st.ch - ins.top - ins.bottom);
      var fullH = cam.view && cam.view.enabled ? cam.view.fullHeight : st.ch;
      var tf = Math.tan(cam.fov * Math.PI / 360);
      return { tv: tf * vh / fullH, th: tf * vw / fullH, st: st };
    }
    /* the distance from the glass and the tilt that put the front waterline
     * and floor edge where they belong (WATERLINE_NDC, FLOOR_NDC), and at
     * least 160 units of glass across on a narrow screen */
    function solve() {
      var v = visible(), st = v.st, h = EYE_H, depthH = h - st.FLOOR_Y;
      var K = Math.atan(-FLOOR_NDC * v.tv) + Math.atan(WATERLINE_NDC * v.tv);
      var lo = 5, hi = 20000;
      for (var it = 0; it < 60; it++) {
        var mid = 0.5 * (lo + hi);
        if (Math.atan(depthH / mid) - Math.atan(h / mid) > K) lo = mid; else hi = mid;
      }
      var d = 0.5 * (lo + hi);
      d = Math.max(d, 160 / (2 * Math.max(v.th, 1e-3)));
      var p = Math.atan(h / d) + Math.atan(WATERLINE_NDC * v.tv);
      return { d: d, p: p, st: st, tv: v.tv, th: v.th };
    }
    var lastFit = { d: 2900, p: 0.04, T: 3000, th: 0.08 };
    function clampGlide(a, d, th) {
      var halfView = d * th * 0.7, lim = Math.max(0, F.L / 2 - halfView);
      return Math.max(-lim, Math.min(lim, a));
    }
    function lens(fov) {
      if (cam.fov === fov) return;
      cam.fov = fov;
      cam.updateProjectionMatrix();
    }
    function fit() {
      frameOf();
      lens(REEF_FOV);
      var S = solve();
      glideA = clampGlide(glideA, S.d, S.th);
      var pos = toWorld(glideA, -S.d, EYE_H);
      var fwd = new THREE.Vector3().copy(F.out).multiplyScalar(-Math.cos(S.p)); fwd.y = -Math.sin(S.p);
      var T = (S.d + 120) / Math.cos(S.p);
      S.T = T;
      lastFit = S;
      controls.minDistance = Math.max(30, T / ZOOM_MAX);
      var target = pos.clone().addScaledVector(fwd, T);
      return { target: target, pos: pos, dist: T };
    }
    /* the water's haze for the sand (the fish and the reef have their own,
     * by distance behind the glass): light, about a quarter at the back glass */
    function fogDensity() {
      var c = ctx.clarity(), at = GRADE.fogAt[0] + (GRADE.fogAt[1] - GRADE.fogAt[0]) * c;
      var dist = Math.max(1, outOf(cam.position)) + F.Dp;
      return Math.sqrt(-Math.log(1 - at * 0.5)) / Math.max(1, dist);
    }
    /* sim units across one CSS pixel at the front glass, as the camera stands now */
    function unitsPerPx() {
      var st = ctx.state(), fullH = cam.view && cam.view.enabled ? cam.view.fullHeight : st.ch;
      return 2 * Math.max(20, outOf(cam.position)) * Math.tan(cam.fov * Math.PI / 360) / Math.max(1, fullH);
    }

    /* ---- the rig: glide along the glass, come closer, stay in the room ---- */
    var tmpV = new THREE.Vector3();
    function alongOf(p) { return p.dot(F.along); }
    function outOf(p) { return p.dot(F.out) - F.glass; }   /* > 0 in front of the glass */
    function clamp() {
      var st = ctx.state(), t = controls.target, cp = cam.position;
      /* along the glass: within the tank's length */
      var a = alongOf(t), lim = F.L / 2;
      var ca = Math.max(-lim, Math.min(lim, a));
      if (ca !== a) { tmpV.copy(F.along).multiplyScalar(ca - a); t.add(tmpV); cp.add(tmpV); }
      glideA = alongOf(cp);
      /* back no further than 1.4 fits, in no further than near the back glass */
      var o = outOf(cp), oMax = lastFit.d * 1.4, oMin = -(F.Dp - 40);
      var co = Math.max(oMin, Math.min(oMax, o));
      if (co !== o) { tmpV.copy(F.out).multiplyScalar(co - o); t.add(tmpV); cp.add(tmpV); }
      /* height: above the sand, not far above the water */
      var yMin = st.FLOOR_Y + 8, yMax = 140;
      if (cp.y < yMin) { t.y += yMin - cp.y; cp.y = yMin; }
      if (cp.y > yMax) { t.y -= cp.y - yMax; cp.y = yMax; }
      if (t.y < st.FLOOR_Y + 4) t.y = st.FLOOR_Y + 4;
    }
    /* the keys while walking: A / D glide, W / S closer / back, Q / E down / up */
    var kv = { a: 0, o: 0, y: 0 };
    function keys(m, dt) {
      if (!(dt > 0)) return true;
      var any = !!(m.f || m.r || m.u), boost = m.boost ? 2.5 : 1;
      var k = 1 - Math.exp(-dt / 0.12);
      var st = ctx.state(), across = unitsPerPx() * st.cw;   /* the glass's width in view */
      kv.a += (m.r * across * 0.6 * boost - kv.a) * k;
      kv.o += (-m.f * Math.max(200, outOf(cam.position)) * 0.8 * boost - kv.o) * k;
      kv.y += (m.u * 90 * boost - kv.y) * k;
      if (!any && Math.abs(kv.a) + Math.abs(kv.o) + Math.abs(kv.y) < 1) { kv.a = kv.o = kv.y = 0; return true; }
      tmpV.copy(F.along).multiplyScalar(kv.a * dt).addScaledVector(F.out, kv.o * dt);
      tmpV.y = kv.y * dt;
      controls.target.add(tmpV); cam.position.add(tmpV);
      ctx.moved();
      clamp();
      return true;
    }
    /* the wheel's sideways scroll (and Shift + wheel) glides along the glass */
    canvas.addEventListener("wheel", function (e) {
      if (!rig()) return;
      var dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : (e.shiftKey ? e.deltaY : 0);
      if (!dx) return;
      e.preventDefault(); e.stopImmediatePropagation();
      var px = e.deltaMode === 1 ? dx * 16 : e.deltaMode === 2 ? dx * 400 : dx;
      tmpV.copy(F.along).multiplyScalar(px * unitsPerPx());
      controls.target.add(tmpV); cam.position.add(tmpV);
      ctx.moved();
      clamp();
    }, { capture: true, passive: false });

    /* the controls while walking: pan in the screen's plane, no turning, the wheel / pinch comes closer */
    var keep = null;
    function rigControls(onRig) {
      if (onRig) {
        if (!keep) keep = { rot: controls.enableRotate, ztc: controls.zoomToCursor, minD: controls.minDistance };
        controls.enableRotate = false;
        controls.zoomToCursor = false;
        controls.screenSpacePanning = true;
        controls.minDistance = Math.max(30, lastFit.T / ZOOM_MAX);
        lens(REEF_FOV);
      } else if (keep) {
        controls.enableRotate = keep.rot; controls.zoomToCursor = keep.ztc; controls.minDistance = keep.minD;
        keep = null;
        lens(ctx.FOV);   /* following, or the default look: the scene's own lens */
      }
    }

    function rig() { return on && !ctx.state().follow; }
    function regrade() {
      if (!on) return;
      var u = ctx.clarity();
      function mixA(k) { var a = GRADE[k][0], b = GRADE[k][1]; return a.map(function (x, i) { return x + (b[i] - x) * u; }); }
      var f = mixA("fog"), w = mixA("water"), dt = mixA("deepTop"), db = mixA("deepBot");
      common.uFog.value.set(f[0], f[1], f[2]);
      ctx.setClearColor(f);
      ctx.floorMat.uniforms.uWater.value.set(w[0], w[1], w[2]);
      U.uDeepTop.value.set(dt[0], dt[1], dt[2]); U.uDeepBot.value.set(db[0], db[1], db[2]);
      common.uFogDensity.value = fogDensity();
    }

    var blink = 0, lastAnimT = null, sinceMove = 0;
    function frame(dt, s, info) {
      if (!on) return;
      build();
      fishMaterials();
      buildFace();
      dome0.position.copy(cam.position);
      dome0.scale.setScalar(Math.max(50, cam.far * 0.45));
      var st = ctx.state();
      if (face) {
        var pk = ctx.preds();
        face.geometry.instanceCount = pk ? pk.n : 0;
        face.visible = !!pk && pk.n > 0;
      }
      waterline.visible = cam.position.y > -1;
      /* the sky band: from the horizon to the top of the view (the island and clouds are sized to it) */
      var fullH = cam.view && cam.view.enabled ? cam.view.fullHeight : st.ch;
      var vh = Math.max(1, st.ch - st.insets.top - st.insets.bottom);
      cam.getWorldDirection(tmpV);
      U.uSkySpan.value = Math.max(0.004, Math.atan(Math.tan(cam.fov * Math.PI / 360) * vh / fullH) + Math.asin(Math.max(-1, Math.min(1, tmpV.y))));
      if (rig()) common.uFogDensity.value = fogDensity();
      /* the selection and hover rings lie flat for a view from above: from the side, they face the camera */
      ctx.rings().forEach(function (rg) { rg.quaternion.copy(cam.quaternion); });
      U.uMove.value = st.reduced ? 0 : 1;
      /* blinking only while the world runs (and never with reduced motion) */
      if (info && lastAnimT !== null && info.animT !== lastAnimT) sinceMove = 0; else sinceMove += dt;
      lastAnimT = info ? info.animT : lastAnimT;
      var want = !st.reduced && sinceMove < 0.4 ? 1 : 0;
      blink += (want - blink) * (1 - Math.exp(-dt * 6));
      U.uBlinkOn.value = blink;
    }

    function setActive(want, o) {
      want = !!want;
      if (want === on) return;
      on = want;
      if (on) {
        build();
        objs.forEach(function (x) { if (x !== face) x.visible = true; });
        if (face) face.visible = true;
        rigControls(true);
        regrade();
        fishMaterials();
      } else {
        objs.forEach(function (x) { x.visible = false; });
        swapOut();
        ctx.rings().forEach(function (rg) { rg.rotation.set(-Math.PI / 2, 0, 0); });
        rigControls(false);
        ctx.restoreGrade();
      }
      ctx.resetView(!!(o && o.animate));
    }

    return {
      on: function () { return on; },
      rig: rig,
      setActive: setActive,
      fit: fit,
      fogDensity: fogDensity,
      clamp: clamp,
      keys: keys,
      frame: frame,
      regrade: regrade,
      setWorld: function () { builtFor = ""; if (on) build(); },
      onFollow: function (following) {
        if (!on) return;
        rigControls(!following);
        if (!following) ctx.resetView(true);
      },
      status: function () { return failed ? "fish shaders: " + failed : (on ? "on" : "off"); }
    };
  }

  window.EvoReef = {
    create: create,
    /* for the tests: the splices alone (they throw when an anchor is missing or repeated) */
    patchApp: patchApp, patchPlain: patchPlain, buildReef: buildReef, GRADE: GRADE
  };
})();
