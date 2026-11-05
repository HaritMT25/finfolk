// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the appearance genome's renderer law (window.EvoAppearance).
 *
 * Every fish carries 63 appearance floats (src/ocean/appearance_model.hpp,
 * exported by oc_creature_appearance): 31 skin-pattern genes, the two maternal
 * phases, 30 body-shape genes. This file is the law that turns them into a
 * fish, ported from the accepted prototype (gallery v3,
 * ocean_handoff/patterns_gallery/gallery_v3.html):
 *   - GLSL: pattern law 3 (one shared field of eight detuned waves plus two
 *     oriented carriers, thresholded by balance; countershading; landmarks;
 *     fin margins) and the M1 deformable template (morphology law 2 = M1 law 1
 *     with the gallery's recommendations: shoulder h = .08 + .24g, so the
 *     neutral longitudinal warp is the identity; pelvic centre .20 + .40g, clear
 *     of the anal fin; the caudal chord capped at 3 body radii; barbel width
 *     with a screen-space minimum and sway proportional to reach; paired-fin
 *     root angles frozen at −.30 / −1.20 rad; per-vertex fin-margin distances).
 *   - the shared templates (medium and coarse qualities, the barbel strips);
 *   - the genes' GPU layout: a fish's 63 floats (oc_creature_appearance's row,
 *     plus one zero) in 16 RGBA32F texels of one texture (512 texels wide),
 *     fetched from the fish's gene slot (fetchGenes(slot): the slot the
 *     renderer keeps for the fish's id, web/ocean_appearance_slots.js, read
 *     from its scalar iGeneSlot attribute), so the fish program needs only 8
 *     vertex attributes (WebGL2 guarantees 16; ANGLE on D3D11 refused 15);
 *   - a CPU mirror of the pattern law (the colour a material site gets), for
 *     the GPU == CPU check (EvoOceanScene's appearanceParity: the K12 check of
 *     the gallery, p99.9 <= .002) and the fish card's swatch.
 * Display only: the simulation never reads any of it. */
(function () {
  var TAU = 6.283185307179586, PI = Math.PI;
  var f32 = Math.fround;
  var NG = 31, MO = 33, NM = 30, STRIDE = 63;
  var LAWS = { abi: 3, schema: 3, patternLaw: 3, morphLaw: 2, chartLaw: 1 };

  /* ---------------- GLSL (three.js ShaderMaterial dialect: attribute / varying) ---------------- */
  var g9 = function (x) { var s = f32(x).toPrecision(9); return s.indexOf(".") >= 0 || s.indexOf("e") >= 0 ? s : s + ".0"; };
  var WAVE_DEG = [3.8, 18.8, 53.9, 69.3, 90.4, 107.5, 142.9, 162.4];
  var WAVE_PH = [0, 0.137, 0.311, 0.503, 0.677, 0.839, 0.229, 0.953];
  var KW = WAVE_DEG.map(function (d, k) { return [f32(Math.cos(d * PI / 180)), f32(Math.sin(d * PI / 180)), WAVE_PH[k]]; });
  var ISO_A = 0.364;
  var WAVES = KW.map(function (k) { return "cos(P_TAU * (dot(vec2(" + g9(k[0]) + ", " + g9(k[1]) + "), zf) + " + g9(k[2]) + "))"; })
    .join("\n           + ");
  var CAUD_I = [0.6740740741, 0.2912962963, 1.8648148148, 1.5130584482, 1.0648148148];   /* canonical 12-interval ∫(TE−LE)dη */
  var PHI_I = 0.6620370370;                                                             /* canonical 12-interval ∫4s(1−s)ds */
  var PEC_THETA = -0.30, PEL_THETA = -1.20, EYE_T = 0.03, EYE_TH = 0.43, CHORD_CAP = 3.0;

  var COMMON = [
    "const float P_TAU = 6.283185307179586;",
    "const float P_PI = 3.141592653589793;",
    "float pS(float a, float b, float x) { float t = clamp((x - a) / (b - a), 0.0, 1.0); return t * t * (3.0 - 2.0 * t); }",
    "float pE(float g) { return max(0.0, (g - 0.40) / 0.60); }",
    "float pWrap01(float x) { float y = x - floor(x); return (y >= 1.0 || y == 0.0) ? 0.0 : y; }",
    "vec3 pHSV(float h, float s, float v) {",
    "  vec3 q = clamp(abs(mod(6.0 * h + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);",
    "  return v * mix(vec3(1.0), q, s);",
    "}",
    "float pProfileH(float u) {",
    "  if (u <= -0.20) return 0.0;",
    "  if (u < -0.10) return mix(0.00, 0.42, (u + 0.20) / 0.10);",
    "  if (u <  0.04) return mix(0.42, 0.74, (u + 0.10) / 0.14);",
    "  if (u <  0.20) return mix(0.74, 0.84, (u - 0.04) / 0.16);",
    "  if (u <  0.42) return mix(0.84, 0.72, (u - 0.20) / 0.22);",
    "  if (u <  0.64) return mix(0.72, 0.52, (u - 0.42) / 0.22);",
    "  if (u <  0.84) return mix(0.52, 0.33, (u - 0.64) / 0.20);",
    "  if (u <  1.00) return mix(0.33, 0.20, (u - 0.84) / 0.16);",
    "  return 0.20;",
    "}",
    "float pProfileY(float u) {",
    "  if (u <= -0.20) return 0.0;",
    "  if (u < -0.10) return mix(0.00, 0.50, (u + 0.20) / 0.10);",
    "  if (u <  0.04) return mix(0.50, 0.88, (u + 0.10) / 0.14);",
    "  if (u <  0.20) return mix(0.88, 1.00, (u - 0.04) / 0.16);",
    "  if (u <  0.42) return mix(1.00, 0.86, (u - 0.20) / 0.22);",
    "  if (u <  0.64) return mix(0.86, 0.60, (u - 0.42) / 0.22);",
    "  if (u <  0.84) return mix(0.60, 0.36, (u - 0.64) / 0.20);",
    "  if (u <  1.00) return mix(0.36, 0.20, (u - 0.84) / 0.16);",
    "  return 0.20;",
    "}"
  ].join("\n");

  var VARY = [
    "flat varying vec4 vG0; flat varying vec4 vG1; flat varying vec4 vG2; flat varying vec4 vG3;",
    "flat varying vec4 vG4; flat varying vec4 vG5; flat varying vec4 vG6; flat varying vec4 vG7;",
    "flat varying vec4 vAux; flat varying vec4 vMeta;"
  ].join("\n");

  /* vertex stage: the 33 pattern floats -> flat varyings (gallery PATTERN_VS) */
  var DECODE = [
    "void patternDecode(vec4 g0, vec4 g1, vec4 g2, vec4 g3, vec4 g4, vec4 g5, vec4 g6, vec3 g7, vec2 ph, float lam) {",
    "  vec2 bc = 2.0 * g0.xy - 1.0;",
    "  float bcc = dot(bc, bc);",
    "  vG0 = vec4(bcc == 0.0 ? 0.0 : pWrap01(atan(bc.y, bc.x) / P_TAU), min(1.0, sqrt(bcc)), g0.z, g0.w);",
    "  vG1 = vec4(0.15 + 0.70 * g1.x, g1.y, g1.z, g1.w);",
    "  vec2 o = 2.0 * g2.yz - 1.0;",
    "  float oo = dot(o, o);",
    "  float a = min(1.0, sqrt(oo));",
    "  float th = oo == 0.0 ? 0.0 : 0.5 * atan(o.y, o.x);",
    "  float del = P_PI * g2.w;",
    "  vG2 = vec4(1.5 * exp(2.0794415416798359 * g2.x), a, cos(th), sin(th));",
    "  float w = g3.x;",
    "  float coh = 1.0 - pS(0.02, 0.20, abs(sin(del)));",
    "  float q0 = " + g9(ISO_A) + " * (1.0 - a), q1 = 0.95 * a;",
    "  float A = sqrt(q0 * q0 + q1 * q1 * (1.0 + w * w + 2.0 * w * coh) / ((1.0 + w) * (1.0 + w)));",
    "  vG3 = vec4(w, g3.y, max(0.0, 2.0 * g3.z - 1.0), 0.0);",
    "  vec2 fc = vec2(2.0 * g3.w - 1.0, 2.0 * g4.x - 1.0);",
    "  float fcc = dot(fc, fc);",
    "  vG4 = vec4(pHSV(fcc == 0.0 ? 0.0 : pWrap01(atan(fc.y, fc.x) / P_TAU), min(1.0, sqrt(fcc)), g4.y), g4.z);",
    "  vG5 = vec4(g4.w, g5.x, g5.y, g5.z);",
    "  vG6 = vec4(g5.w, g6.x, g6.y, g6.z);",
    "  vG7 = vec4(g6.w, g7.x, g7.y, g7.z);",
    "  vAux = vec4(cos(th + del), sin(th + del), A, lam);",
    "  vMeta = vec4(0.35 * sin(P_TAU * ph.x), 0.25 * sin(P_TAU * ph.y), 0.0, 0.0);",
    "}"
  ].join("\n");

  /* fragment stage: one shared field, then anatomical overlays (gallery PATTERN_FS) */
  var SKIN = [
    "uniform float uIntrinsic;",
    "float pD(float d, float r, float aaM) { return 1.0 - pS(r - aaM, r + aaM, d); }",
    "vec3 patternBase(float u, float v) {",
    "  float vc = clamp(v, 0.0, 1.0);",
    "  float H = pWrap01(vG0.x + 0.25 * (2.0 * vG1.y - 1.0) * clamp(u, 0.0, 1.0) + 0.50 * (2.0 * vG1.z - 1.0) * (1.0 - pS(0.10, 0.25, u)));",
    "  vec3 base = pHSV(H, vG0.y, vG0.z);",
    "  float s = vG0.w, L = vG1.x, wcs = 0.35 * exp(-3.2188758248682006 * vG5.w);",
    "  return mix(base * (1.0 - 0.50 * s), mix(base, pHSV(H, 0.18 * vG0.y, 0.65 + 0.35 * vG0.z), 0.85 * s), pS(L - wcs, L + wcs, vc));",
    "}",
    /* the field's opacity at a material site (also the phase-B glow layout) */
    "float patternField(float u, float v, out vec2 zfOut) {",
    "  float vc = clamp(v, 0.0, 1.0);",
    "  float vf = mix(v, 0.5 - abs(v - 0.5), vG5.z);",
    "  vec2 p = vec2(2.0 * u - 1.0, vf - 0.5);",
    "  vec2 x = vG2.x * (p - vMeta.xy);",
    "  vec2 zf = x + 0.65 * vG3.y * vec2(sin(P_TAU * ( 0.31 * x.x + 0.23 * x.y + 0.17)),",
    "                                    sin(P_TAU * (-0.19 * x.x + 0.29 * x.y + 0.43)));",
    "  zfOut = zf;",
    "  float N = (" + WAVES + ") / 8.0;",
    "  float w = vG3.x, a = vG2.y;",
    "  float C = (cos(P_TAU * dot(vG2.zw, zf)) + w * cos(P_TAU * dot(vAux.xy, zf))) / (1.0 + w);",
    "  return (1.0 - a) * N + a * C;",
    "}",
    "vec3 patternSkinM(float u, float v, float z, int fin, float dMar) {",
    "  float lam = vAux.w;",
    "  bool intr = uIntrinsic > 0.5;",
    "  float vc = clamp(v, 0.0, 1.0);",
    "  vec2 zf;",
    "  float F = patternField(u, v, zf);",
    "  float b = clamp(vG1.w + 0.5 * (2.0 * vG5.x - 1.0) * (vc - 0.5), 0.0, 1.0);",
    "  float t = vAux.z * (1.0 - 2.0 * b);",
    "  float dEye = abs(lam * (u - 0.03));",
    "  float dSh = length(vec2(lam * (u - 0.24), z - 0.10 * pProfileH(0.24)));",
    "  float dOc = length(vec2(lam * (u - 0.72), z));",
    "  float aa = max(0.005, 0.75 * fwidth(F - t));",
    "  float rho = max(length(dFdx(zf)), length(dFdy(zf)));",
    "  float detail = 1.0 - pS(0.25, 0.60, rho);",
    "  float wcsMin = 0.75 * fwidth(vc);",
    "  float aaEye = max(0.005, 0.75 * fwidth(dEye)), aaSh = max(0.005, 0.75 * fwidth(dSh));",
    "  float aaOc = max(0.005, 0.75 * fwidth(dOc)), aaMar = max(0.005, 0.75 * fwidth(dMar));",
    "  if (intr) { aa = 0.005; detail = 1.0; wcsMin = 0.0; aaEye = 0.005; aaSh = 0.005; aaOc = 0.005; aaMar = 0.005; }",
    "  float fill = pS(t - aa, t + aa, F);",
    "  float ol = vG5.y;",
    "  float hband = 0.025 + 0.18 * (1.0 - ol) * (1.0 - ol);",
    "  float band = pS(t - hband - aa, t - hband + aa, F) - pS(t + hband - aa, t + hband + aa, F);",
    "  float mark = mix(fill, max(0.0, band), ol);",
    "  float cut = -0.15 + 1.30 * vG4.w;",
    "  float cover = 1.0 - pS(cut - 0.05, cut + 0.05, vc);",
    "  float fieldOpacity = vG3.z * cover * mark * detail;",
    "  float headWindow = 1.0 - pS(0.10, 0.25, u);",
    "  float H = pWrap01(vG0.x + 0.25 * (2.0 * vG1.y - 1.0) * clamp(u, 0.0, 1.0) + 0.50 * (2.0 * vG1.z - 1.0) * headWindow);",
    "  vec3 base = pHSV(H, vG0.y, vG0.z);",
    "  vec3 markColour = vG4.rgb;",
    "  vec3 pale = pHSV(H, 0.12 * vG0.y, 0.97);",
    "  float s = vG0.w, L = vG1.x;",
    "  float wcs = max(0.35 * exp(-3.2188758248682006 * vG5.w), wcsMin);",
    "  float below = pS(L - wcs, L + wcs, vc);",
    "  vec3 dorsal = base * (1.0 - 0.50 * s);",
    "  vec3 bellyTarget = pHSV(H, 0.18 * vG0.y, 0.65 + 0.35 * vG0.z);",
    "  vec3 belly = mix(base, bellyTarget, 0.85 * s);",
    "  vec3 col = mix(dorsal, belly, below);",
    "  col = mix(col, markColour, fieldOpacity);",
    "  if (fin == 0) {",
    "    col = mix(col, markColour, pE(vG6.x) * pD(dEye, 0.08 + 0.42 * vG6.y, aaEye));",
    "    col = mix(col, markColour, pE(vG6.z) * pD(dSh, 0.08 + 0.22 * vG6.w, aaSh));",
    "    float r = 0.12 + 0.34 * vG7.y, rw = 0.04 + 0.08 * vG7.z;",
    "    col = mix(col, pale, pE(vG7.x) * vG7.z * max(0.0, pD(dOc, r + rw, aaOc) - pD(dOc, r, aaOc)));",
    "    col = mix(col, markColour, pE(vG7.x) * pD(dOc, r, aaOc));",
    "  } else if (fin == 1 || fin == 2 || fin == 3 || fin == 5 || fin == 6) {",
    "    col = mix(col, pale, 0.12);",
    "    col = mix(col, pale, pE(vG7.w) * pD(dMar, 0.08, aaMar));",
    "  }",
    "  return col;",
    "}"
  ].join("\n");

  /* the M1 deformable template (gallery MORPH_COMMON; morphology law 2) */
  /* the genes: GT[k] = genes 4k .. 4k+3 of this instance (GENES_FETCH fills it) */
  var GENES = [
    "uniform highp sampler2D uGenes;",
    "vec4 GT[16];",
    "void fetchGenes(int inst) {",
    "  for (int k = 0; k < 16; k++) { int li = 16 * inst + k; GT[k] = texelFetch(uGenes, ivec2(li % 512, li / 512), 0); }",
    "}",
    /* shape gene j (0..29) = gene 33 + j; j is a constant at every call */
    "float mg(int j) { int i = 33 + j; vec4 t = GT[i / 4]; int c = i - 4 * (i / 4); return c == 0 ? t.x : (c == 1 ? t.y : (c == 2 ? t.z : t.w)); }"
  ].join("\n");
  var MORPH = [
    "uniform float uRingT[16];",
    "uniform int uRingN;",
    "uniform float uHalfRing;",
    "struct Morph {",
    "  float depth, width, n, fexp, sh, hbulk, sn, nexp, ped;",
    "  float outline, AR, cA, span, cx;",
    "  float dH, dL, dS, dSplit, aH, aL, aS;",
    "  float pA, pT, pSweep, pDih, vA, vT, vSweep;",
    "  float bD, bReach, bBeta, eye, lam;",
    "};",
    "float mH(float g, float a, float b, float c) { return b + (2.0 * g - 1.0) * (g < 0.5 ? b - a : c - b); }",
    "float mPw(float x, float p) { return x > 0.0 ? pow(x, p) : 0.0; }",
    "float mSc(float c, float e) { float a = abs(c); return a > 0.0 ? sign(c) * pow(a, e) : 0.0; }",
    "float mCaudLEk(int k, float a) { return k < 2 ? a * a : 0.2 * a * a; }",
    "float mCaudTEk(int k, float a) {",
    "  if (k == 0) return 0.35 + 0.65 * a;",
    "  if (k == 1) return 0.22 + 0.78 * a * a;",
    "  if (k == 2) return 1.0;",
    "  if (k == 3) return 0.25 + 0.75 * sqrt(max(0.0, 1.0 - a * a));",
    "  return 0.20 + 0.80 * (1.0 - a);",
    "}",
    "float mCaudIk(int k) { return k == 0 ? " + g9(CAUD_I[0]) + " : k == 1 ? " + g9(CAUD_I[1]) + " : k == 2 ? " + g9(CAUD_I[2]) +
      " : k == 3 ? " + g9(CAUD_I[3]) + " : " + g9(CAUD_I[4]) + "; }",
    "float mCaudLE(float o, float a) { int k = min(3, int(floor(o * 4.0))); float w = pS(0.0, 1.0, o * 4.0 - float(k)); return mix(mCaudLEk(k, a), mCaudLEk(k + 1, a), w); }",
    "float mCaudTE(float o, float a) { int k = min(3, int(floor(o * 4.0))); float w = pS(0.0, 1.0, o * 4.0 - float(k)); return mix(mCaudTEk(k, a), mCaudTEk(k + 1, a), w); }",
    "float mCaudI(float o) { int k = min(3, int(floor(o * 4.0))); float w = pS(0.0, 1.0, o * 4.0 - float(k)); return mix(mCaudIk(k), mCaudIk(k + 1), w); }",
    "Morph mDecode(float lam) {",   /* after fetchGenes */
    "  Morph M;",
    "  M.depth = mH(mg(0), 0.22, 1.0, 2.40); M.width = mH(mg(1), 0.18, 1.0, 1.90); M.n = 1.0 + 2.0 * mg(2); M.fexp = mH(mg(3), 0.55, 1.0, 1.60);",
    "  M.sh = 0.08 + 0.24 * mg(4); M.hbulk = mH(mg(5), 0.60, 1.0, 1.60); M.sn = mH(mg(6), 0.08, 0.20, 0.40); M.nexp = mH(mg(7), 1.80, 1.0, 0.40);",
    "  M.ped = mH(mg(8), 0.45, 1.0, 1.70); M.outline = mg(9); M.AR = mH(mg(10), 0.50, 2.80, 8.0); M.cA = mH(mg(11), 0.0, 1.20, 3.20);",
    "  M.span = M.cA > 1e-6 ? sqrt(M.AR * M.cA) : 0.0;",
    "  M.cx = M.cA > 1e-6 ? min(" + g9(CHORD_CAP) + ", 2.0 * M.cA / (M.span * mCaudI(M.outline))) : 0.0;",
    "  M.dH = 1.60 * mg(12); M.dL = 0.10 + 0.60 * mg(13); M.dS = mg(14); M.dSplit = mg(15);",
    "  M.aH = 1.20 * mg(16); M.aL = 0.10 + 0.45 * mg(17); M.aS = mg(18);",
    "  M.pA = mH(mg(19), 0.0, 0.45, 1.20); M.pT = 0.06 + 0.28 * mg(20); M.pSweep = mH(mg(21), -0.25, 0.50, 1.25); M.pDih = radians(-70.0 + 110.0 * mg(22));",
    "  M.vA = mH(mg(23), 0.0, 0.20, 0.90); M.vT = 0.20 + 0.40 * mg(24); M.vSweep = mH(mg(25), 0.0, 0.50, 1.0);",
    "  M.bD = mg(26); M.bReach = mH(mg(27), 0.10, 1.20, 3.0); M.bBeta = mg(28); M.eye = mH(mg(29), 0.40, 1.0, 1.80);",
    "  M.lam = lam;",
    "  return M;",
    "}",
    "float mWarp(Morph M, float t) { return t <= 0.2 ? -M.sn + (t + 0.2) / 0.4 * (M.sh + M.sn) : M.sh + (t - 0.2) / 0.8 * (1.0 - M.sh); }",
    "float mInvWarp(Morph M, float u) { return u <= M.sh ? -0.2 + 0.4 * (u + M.sn) / (M.sh + M.sn) : 0.2 + 0.8 * (u - M.sh) / (1.0 - M.sh); }",
    "vec2 mHalfAxes(Morph M, float t) {",
    "  float headMask = 1.0 - pS(0.04, 0.30, t), noseMask = 1.0 - pS(-0.16, 0.04, t), rearMask = pS(0.65, 1.0, t);",
    "  float p = M.fexp * (1.0 + (M.nexp - 1.0) * noseMask);",
    "  float sc = (1.0 + (M.hbulk - 1.0) * headMask) * (1.0 + (M.ped - 1.0) * rearMask);",
    "  return vec2(M.width * mPw(pProfileY(t), p) * sc, M.depth * 0.84 * mPw(pProfileH(t) / 0.84, p) * sc);",
    "}",
    "vec3 mSurf(Morph M, float t, float th, float side) {",
    "  vec2 ab = mHalfAxes(M, t); float e = 2.0 / M.n;",
    "  return vec3(M.lam * mWarp(M, t), side * ab.x * mSc(max(cos(th), 0.0), e), ab.y * mSc(sin(th), e));",
    "}",
    "vec3 mFacet(Morph M, float t, float th, float side) {",
    "  int i = 0;",
    "  for (int k = 1; k < 16; k++) { if (k < uRingN && t >= uRingT[k]) i = k; }",
    "  i = min(i, uRingN - 2);",
    "  float t0 = uRingT[i], t1 = uRingT[i + 1];",
    "  float al = clamp((t - t0) / (t1 - t0), 0.0, 1.0);",
    "  float stp = P_PI / uHalfRing, q = (th + 0.5 * P_PI) / stp;",
    "  float k0 = clamp(floor(q), 0.0, uHalfRing - 1.0), be = clamp(q - k0, 0.0, 1.0);",
    "  float th0 = -0.5 * P_PI + k0 * stp, th1 = th0 + stp;",
    "  vec3 P10 = mSurf(M, t1, th0, side), P11 = mSurf(M, t1, th1, side);",
    "  vec3 r;",   /* one return (ANGLE's HLSL flags an early return) */
    "  if (i == 0) { vec3 P0 = mSurf(M, t0, 0.0, side); r = P0 + al * (P10 + be * (P11 - P10) - P0); }",
    "  else {",
    "    vec3 P00 = mSurf(M, t0, th0, side), P01 = mSurf(M, t0, th1, side);",
    "    r = al >= be ? P00 + al * (P10 - P00) + be * (P11 - P10) : P00 + be * (P01 - P00) + al * (P11 - P01);",
    "  }",
    "  return r;",
    "}",
    "float mFinH(float H, float split, float s) { return H * 4.0 * s * (1.0 - s) * (1.0 - split * (1.0 - pS(0.08, 0.20, abs(s - 0.5)))); }",
    "float mSeg2(vec2 p, vec2 a, vec2 b) { vec2 u = b - a; float L2 = dot(u, u); float t = L2 > 0.0 ? clamp(dot(p - a, u) / L2, 0.0, 1.0) : 0.0; return length(p - a - t * u); }",
    "void mBuild(Morph M, vec4 a, vec4 pat, float time, float wag, float minW, out vec3 geo, out vec3 mat, out float mar) {",
    "  int fin = int(pat.x + 0.5); float side = pat.z;",
    "  mar = 1000.0;",
    "  if (fin == 0) {",
    "    vec3 p = mSurf(M, a.x, a.y, side);",
    "    geo = vec3(p.x, a.z * p.y, a.z * p.z); mat = a.xyz;",
    "  } else if (fin == 1) {",
    "    float eta = a.x, row = a.y, ae = abs(eta);",
    "    float LE = mCaudLE(M.outline, ae), TE = mCaudTE(M.outline, ae), r = clamp(row, 0.0, 1.0);",
    "    float x = M.cx * (LE + r * (TE - LE));",
    "    float z = 0.5 * M.span * eta;",
    "    float B1 = mHalfAxes(M, 1.0).y, xLE = M.cx * LE;",
    "    if (row < -0.5) { float wc = 1.0 - pS(0.75 * B1, B1, abs(z)); x = xLE + wc * (-0.12 - xLE); }",
    "    geo = vec3(M.lam + x, 0.0, z);",
    "    float vLE = 0.5 * (1.0 - sign(z) * pow(min(1.0, abs(z) / max(B1, 1e-6)), 0.5 * M.n));",
    "    float vTE = 0.5 * (1.0 - eta);",
    "    mat = vec3(1.0 + x / M.lam, row < -0.5 ? vLE : vLE + r * (vTE - vLE), 0.0);",
    "    float chord = M.cx * (TE - LE), hh = 0.01;",
    "    float a1 = min(ae + hh, 1.0), a0 = max(ae - hh, 0.0), dz = (a1 - a0) * 0.5 * M.span + 1e-6;",
    "    float sTE = M.cx * (mCaudTE(M.outline, a1) - mCaudTE(M.outline, a0)) / dz, sLE = M.cx * (mCaudLE(M.outline, a1) - mCaudLE(M.outline, a0)) / dz;",
    "    float nTE = inversesqrt(1.0 + sTE * sTE), nLE = inversesqrt(1.0 + sLE * sLE);",
    "    float fr = pS(0.9 * B1, 1.2 * B1, abs(z));",
    "    if (row < -0.5) mar = 1000.0;",
    "    else if (row < 0.25) mar = min(chord * nTE, (1.0 - fr) * 1000.0);",
    "    else if (row < 0.75) mar = min(0.5 * chord * nTE, 0.5 * chord * nLE + (1.0 - fr) * 1000.0);",
    "    else mar = 0.0;",
    "  } else if (fin == 2 || fin == 5) {",
    "    float s = a.x, q = a.y; bool dors = fin == 2; float up = dors ? 1.0 : -1.0;",
    "    float ell = dors ? M.dL : M.aL, H = dors ? M.dH : M.aH, start = 0.04 + (0.92 - ell) * (dors ? M.dS : M.aS), split = dors ? M.dSplit : 0.0;",
    "    float t = start + ell * s;",
    "    vec3 root = mFacet(M, t, up * 0.5 * P_PI, 1.0);",
    "    float ht = mFinH(H, split, s);",
    "    geo = vec3(root.x, 0.0, root.z + up * q * ht);",
    "    float b0 = max(pProfileH(t), 1e-3);",
    "    mat = vec3(t, dors ? -0.5 * q * ht / b0 : 1.0 + 0.5 * q * ht / b0, 0.0);",
    "    float X0 = M.lam * mWarp(M, t), d = 1000.0;",
    "    vec2 pp = vec2(M.lam * mWarp(M, start), mFinH(H, split, 0.0));",
    "    for (int k = 1; k <= 16; k++) { float sk = float(k) / 16.0; vec2 qq = vec2(M.lam * mWarp(M, start + ell * sk), mFinH(H, split, sk)); d = min(d, mSeg2(vec2(X0, 0.0), pp, qq)); pp = qq; }",
    "    mar = (1.0 - q) * d;",
    "  } else if (fin == 3 || fin == 6) {",
    "    float s = a.x, r = a.y; bool pec = fin == 3;",
    "    float chord = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, tc = pec ? M.pT : M.vT, sweep = pec ? M.pSweep : M.vSweep;",
    "    float dih = pec ? M.pDih : -0.25 * P_PI, thr = pec ? " + g9(PEC_THETA) + " : " + g9(PEL_THETA) + ";",
    "    float span = area / (chord * " + g9(PHI_I) + ");",
    "    float X = M.lam * mWarp(M, tc) + chord * (s - 0.5);",
    "    float t = mInvWarp(M, X / M.lam);",
    "    vec3 root = mFacet(M, t, thr, side);",
    "    float phi = 4.0 * s * (1.0 - s), w = span * r * phi;",
    "    geo = root + vec3(sweep * w, side * w * cos(dih), w * sin(dih));",
    "    mat = vec3(t + sweep * w / M.lam, 0.5 * (1.0 - sin(thr)) + 0.21 * r * phi, 0.0);",
    "    float x0 = chord * (s - 0.5), d = 1000.0;",
    "    vec2 pp = vec2(-0.5 * chord, 0.0);",
    "    for (int k = 1; k <= 16; k++) { float sk = float(k) / 16.0, wk = span * 4.0 * sk * (1.0 - sk); vec2 qq = vec2(chord * (sk - 0.5) + sweep * wk, wk); d = min(d, mSeg2(vec2(x0, 0.0), pp, qq)); pp = qq; }",
    "    mar = (1.0 - r) * d;",
    "  } else if (fin == 4) {",
    "    float kE = min(M.eye, 0.32 * mHalfAxes(M, " + g9(EYE_T) + ").y / 0.14);",
    "    vec3 c = mSurf(M, " + g9(EYE_T) + ", " + g9(EYE_TH) + ", side);",
    "    float X = c.x + a.x * 0.24 * kE, Z = c.z + a.y * 0.14 * kE;",
    "    float t = mInvWarp(M, X / M.lam); vec2 ab = mHalfAxes(M, t);",
    "    float sn = sign(Z) * pow(min(1.0, abs(Z) / max(ab.y, 1e-6)), 0.5 * M.n);",
    "    vec3 p = mSurf(M, t, asin(clamp(sn, -1.0, 1.0)), side);",
    "    geo = vec3(p.x, side * (abs(p.y) + 0.04 + 0.05 * ab.x), p.z); mat = vec3(0.0);",
    "  } else {",
    "    float q = a.x, ws = a.y, j = a.z, rib = a.w;",
    "    float d = max(0.0, (M.bD - 0.2) / 0.8), wj = pS(0.0, 1.0, 3.0 * d - j);",
    "    float tj = -0.16 + 0.18 * M.bBeta + 0.015 * j, thj = -P_PI * (0.06 + 0.25 * M.bBeta + 0.055 * j);",
    "    vec3 P0 = mFacet(M, tj, thj, 1.0);",
    "    float L = M.bReach * (1.0 - 0.15 * j) * wj;",
    "    vec3 P1 = P0 + L * vec3(-0.30, 0.40, -0.20), P2 = P0 + L * vec3(0.25, 0.70, -0.55);",
    "    vec3 C = (1.0 - q) * (1.0 - q) * P0 + 2.0 * q * (1.0 - q) * P1 + q * q * P2;",
    "    vec3 T = 2.0 * (1.0 - q) * (P1 - P0) + 2.0 * q * (P2 - P1);",
    "    float tl = length(T); T = tl > 1e-9 ? T / tl : vec3(1.0, 0.0, 0.0);",
    "    vec3 n1 = vec3(T.y, -T.x, 0.0); float nl = length(n1.xy); n1 = nl > 1e-6 ? n1 / nl : vec3(0.0, 1.0, 0.0);",
    "    vec3 n2 = cross(T, n1);",
    "    float sw = wag * 0.10 * L * q * q * sin(5.5 * time + 2.0 * j + (side > 0.0 ? 0.0 : 1.3));",
    "    float hw = wj > 0.0 ? max(0.04 * (1.0 - 0.6 * q) * min(1.0, 4.0 * wj), minW) : 0.0;",
    "    geo = C + n2 * sw + (rib < 0.5 ? n1 : n2) * ws * hw;",
    "    geo.y *= side;",
    "    mat = vec3(tj, thj, q);",
    "  }",
    "}"
  ].join("\n");

  /* ---------------- templates (gallery buildM1Template / buildBarbelTemplate) ---------------- */
  var LODS = {
    full:   { rings: [-0.20, -0.16, -0.10, -0.03, 0.04, 0.12, 0.20, 0.31, 0.42, 0.53, 0.64, 0.74, 0.84, 0.92, 1], half: 4, caud: 12, collar: 1, dors: 9, pec: 9, pel: 7, eyes: 1, barb: 6, dupEnds: 1 },
    medium: { rings: [-0.20, -0.12, 0.00, 0.20, 0.36, 0.53, 0.70, 0.86, 1], half: 4, caud: 8, collar: 1, dors: 7, pec: 5, pel: 4, eyes: 1, barb: 4, dupEnds: 1 },
    coarse: { rings: [-0.20, -0.05, 0.20, 0.55, 1], half: 4, caud: 4, collar: 0, dors: 4, pec: 3, pel: 3, eyes: 0, barb: 0, dupEnds: 0 }
  };
  function buildTemplate(lodName) {
    var L = LODS[lodName], pos = [], pat = [], idx = [];
    function V(a0, a1, a2, a3, fin, side) { pos.push(a0, a1, a2, a3); pat.push(fin, 0, side, 0); return pos.length / 4 - 1; }
    function T(a, b, c) { idx.push(a, b, c); }
    var half = L.half, step = PI / half, R = L.rings, nr = R.length, i, k, s0;
    var ring = [];
    for (i = 1; i < nr; i++) {
      var row = /** @type {{"1": number[], "-1": number[]}} */ ({ "1": [], "-1": [] });
      for (k = 0; k <= half; k++) {
        var th = -0.5 * PI + k * step;
        if (k === 0 || k === half) { var vv = V(R[i], th, 1, 0, 0, 1); row["1"][k] = vv; row["-1"][k] = vv; }
        else { row["1"][k] = V(R[i], th, 1, 0, 0, 1); row["-1"][k] = V(R[i], th, 1, 0, 0, -1); }
      }
      ring.push(row);
    }
    var tipV = -1, capV = -1;
    [1, -1].forEach(function (s) {
      for (var ii = 0; ii + 1 < ring.length; ii++) for (var kk = 0; kk < half; kk++) {
        var P00 = ring[ii][s][kk], P10 = ring[ii + 1][s][kk], P11 = ring[ii + 1][s][kk + 1], P01 = ring[ii][s][kk + 1];
        T(P00, P10, P11); T(P00, P11, P01);
      }
      var first = ring[0][s], last = ring[ring.length - 1][s];
      for (var k2 = 0; k2 < half; k2++) {
        var thm = -0.5 * PI + (k2 + 0.5) * step, tip, cap;
        if (L.dupEnds) { tip = V(R[0], thm, 0, 0, 0, s); cap = V(1, thm, 0, 0, 0, s); }
        else {
          if (tipV < 0) { tipV = V(R[0], 0, 0, 0, 0, 1); capV = V(1, 0, 0, 0, 0, 1); }
          tip = tipV; cap = capV;
        }
        T(tip, first[k2], first[k2 + 1]);
        T(cap, last[k2], last[k2 + 1]);
      }
    });
    var rows = L.collar ? [-1, 0, 0.5, 1] : [0, 0.5, 1], ce = [], j, r;
    for (j = 0; j <= L.caud; j++) { var eta = -1 + 2 * j / L.caud; ce.push(rows.map(function (rr) { return V(eta, rr, 0, 0, 1, 1); })); }
    for (j = 0; j < L.caud; j++) for (r = 0; r + 1 < rows.length; r++) { T(ce[j][r], ce[j + 1][r], ce[j + 1][r + 1]); T(ce[j][r], ce[j + 1][r + 1], ce[j][r + 1]); }
    [2, 5].forEach(function (fin) {
      var n = L.dors, c = [];
      for (var q = 0; q < n; q++) { var s = q / (n - 1); c.push([V(s, 0, 0, 0, fin, 1), V(s, 1, 0, 0, fin, 1)]); }
      for (q = 0; q + 1 < n; q++) { T(c[q][0], c[q + 1][0], c[q + 1][1]); T(c[q][0], c[q + 1][1], c[q][1]); }
    });
    [[3, L.pec], [6, L.pel]].forEach(function (fn) {
      [1, -1].forEach(function (sd) {
        var c = [];
        for (var q = 0; q < fn[1]; q++) { var s = q / (fn[1] - 1); c.push([V(s, 0, sd, 0, fn[0], sd), V(s, 1, sd, 0, fn[0], sd)]); }
        for (q = 0; q + 1 < fn[1]; q++) { T(c[q][0], c[q + 1][0], c[q + 1][1]); T(c[q][0], c[q + 1][1], c[q][1]); }
      });
    });
    if (L.eyes) for (s0 = 0; s0 < 2; s0++) {
      var sd = s0 ? -1 : 1;
      var e = [[-1, 0], [0, 1], [1, 0], [0, -1]].map(function (d) { return V(d[0], d[1], sd, 0, 4, sd); }), cc = V(0, 0, sd, 0, 4, sd);
      for (k = 0; k < 4; k++) T(cc, e[k], e[(k + 1) % 4]);
    }
    return { lod: lodName, pos: new Float32Array(pos), pat: new Float32Array(pat), idx: idx, verts: pos.length / 4, tris: idx.length / 3, ringT: R, half: half };
  }
  function buildBarbels(lodName) {
    var L = LODS[lodName], pos = [], pat = [], idx = [];
    if (!L.barb) return null;
    function V(a0, a1, a2, a3, side) { pos.push(a0, a1, a2, a3); pat.push(7, 0, side, 0); return pos.length / 4 - 1; }
    for (var j = 0; j < 3; j++) for (var s0 = 0; s0 < 2; s0++) for (var rib = 0; rib < 2; rib++) {
      var sd = s0 ? -1 : 1, c = [];
      for (var i = 0; i <= L.barb; i++) { var q = i / L.barb; c.push([V(q, -1, j, rib, sd), V(q, 1, j, rib, sd)]); }
      for (i = 0; i < L.barb; i++) { idx.push(c[i][0], c[i + 1][0], c[i + 1][1]); idx.push(c[i][0], c[i + 1][1], c[i][1]); }
    }
    return { lod: lodName, pos: new Float32Array(pos), pat: new Float32Array(pat), idx: idx, verts: pos.length / 4, tris: idx.length / 3, ringT: L.rings, half: L.half };
  }

  /* ---------------- CPU mirror of pattern law 3 (gallery decode / fieldF / markOf / skinMat) ---------------- */
  function S3(a, b, x) { var t = (x - a) / (b - a); t = t < 0 ? 0 : (t > 1 ? 1 : t); return t * t * (3 - 2 * t); }
  var clamp01 = function (x) { return x < 0 ? 0 : (x > 1 ? 1 : x); };
  var Edz = function (g) { return Math.max(0, (g - 0.40) / 0.60); };
  function wrap01(x) { var y = x - Math.floor(x); return (y >= 1 || y === 0) ? 0 : y; }
  var PU = [-0.20, -0.10, 0.04, 0.20, 0.42, 0.64, 0.84, 1.00];
  var PZ = [0, 0.42, 0.74, 0.84, 0.72, 0.52, 0.33, 0.20];
  function hOf(u) {
    if (u <= PU[0]) return PZ[0];
    for (var i = 1; i < 8; i++) if (u < PU[i]) return PZ[i - 1] + (PZ[i] - PZ[i - 1]) * (u - PU[i - 1]) / (PU[i] - PU[i - 1]);
    return PZ[7];
  }
  var SH_Z = 0.10 * hOf(0.24);
  function hsvInto(h, s, v, out) {
    for (var c = 0; c < 3; c++) {
      var x = 6 * h + (c === 0 ? 0 : (c === 1 ? 4 : 2)); x = x - 6 * Math.floor(x / 6);
      var q = Math.abs(x - 3) - 1; q = q < 0 ? 0 : (q > 1 ? 1 : q);
      out[c] = v * (1 + s * (q - 1));
    }
    return out;
  }
  function chroma(gx, gy) { var x = 2 * gx - 1, y = 2 * gy - 1, cc = x * x + y * y; return { hue: cc === 0 ? 0 : wrap01(Math.atan2(y, x) / TAU), sat: Math.min(1, Math.sqrt(cc)) }; }
  /* row: an array-like of 63 floats (oc_creature_appearance's layout); lam: the fish's λ */
  function decode(g, lam) {
    var D = {};
    var bc = chroma(g[0], g[1]); D.bHue = bc.hue; D.bSat = bc.sat; D.bVal = g[2];
    D.cs = g[3]; D.L = 0.15 + 0.70 * g[4]; D.ax = g[5]; D.hd = g[6]; D.bal = g[7];
    D.f = 1.5 * Math.exp(2.0794415416798359 * g[8]);
    var ox = 2 * g[9] - 1, oy = 2 * g[10] - 1, oo = ox * ox + oy * oy;
    D.a = Math.min(1, Math.sqrt(oo)); var th = oo === 0 ? 0 : 0.5 * Math.atan2(oy, ox);
    D.n0x = Math.cos(th); D.n0y = Math.sin(th);
    var del = PI * g[11]; D.n1x = Math.cos(th + del); D.n1y = Math.sin(th + del);
    var w = g[12], a = D.a; D.w = w;
    var coh = 1 - S3(0.02, 0.20, Math.abs(Math.sin(del)));
    D.A = Math.sqrt(Math.pow(ISO_A * (1 - a), 2) + Math.pow(0.95 * a, 2) * (1 + w * w + 2 * w * coh) / ((1 + w) * (1 + w)));
    D.warp = g[13]; D.contrast = Math.max(0, 2 * g[14] - 1);
    var mc = chroma(g[15], g[16]);
    D.mark = hsvInto(mc.hue, mc.sat, g[17], [0, 0, 0]);
    D.cut = -0.15 + 1.30 * g[18]; D.dg = g[19]; D.outline = g[20]; D.fold = g[21];
    D.hband = 0.025 + 0.18 * (1 - g[20]) * (1 - g[20]);
    D.wcs = 0.35 * Math.exp(-3.2188758248682006 * g[22]);
    D.ebS = Edz(g[23]); D.ebW = 0.08 + 0.42 * g[24]; D.shS = Edz(g[25]); D.shR = 0.08 + 0.22 * g[26];
    D.ocS = Edz(g[27]); D.ocR = 0.12 + 0.34 * g[28]; D.ocRing = g[29]; D.ocW = 0.04 + 0.08 * g[29]; D.fm = Edz(g[30]);
    D.Tx = 0.35 * Math.sin(TAU * g[31]); D.Ty = 0.25 * Math.sin(TAU * g[32]);
    D.lam = lam;
    return D;
  }
  function fieldF(D, u, v) {
    var vf = v + ((0.5 - Math.abs(v - 0.5)) - v) * D.fold;
    var x = D.f * (2 * u - 1 - D.Tx), y = D.f * (vf - 0.5 - D.Ty);
    var zx = x, zy = y;
    if (D.warp !== 0) {
      zx += 0.65 * D.warp * Math.sin(TAU * (0.31 * x + 0.23 * y + 0.17));
      zy += 0.65 * D.warp * Math.sin(TAU * (-0.19 * x + 0.29 * y + 0.43));
    }
    var N = 0, C = 0, k;
    if (D.a < 1) { for (k = 0; k < 8; k++) N += Math.cos(TAU * (KW[k][0] * zx + KW[k][1] * zy + KW[k][2])); N /= 8; }
    if (D.a > 0) {
      C = Math.cos(TAU * (D.n0x * zx + D.n0y * zy));
      if (D.w !== 0) C = (C + D.w * Math.cos(TAU * (D.n1x * zx + D.n1y * zy))) / (1 + D.w);
    }
    return (1 - D.a) * N + D.a * C;
  }
  function markOf(D, F, vc) {
    var b = clamp01(D.bal + 0.5 * (2 * D.dg - 1) * (vc - 0.5));
    var t = D.A * (1 - 2 * b), aa = 0.005;
    var fill = S3(t - aa, t + aa, F);
    if (D.outline === 0) return fill;
    var hb = D.hband;
    var band = S3(t - hb - aa, t - hb + aa, F) - S3(t + hb - aa, t + hb + aa, F);
    return fill + (Math.max(0, band) - fill) * D.outline;
  }
  var Dm = function (d, r) { return 1 - S3(r - 0.005, r + 0.005, d); };
  var _b = [0, 0, 0], _p = [0, 0, 0], _bt = [0, 0, 0];
  /* the unlit (intrinsic) skin colour of the body flank at (u, v): the GPU's uIntrinsic = 1 path */
  function flankAt(D, u, v, out) {
    var vc = clamp01(v), zL = hOf(u) * (1 - 2 * v);
    var F = fieldF(D, u, v);
    var fo = D.contrast * (1 - S3(D.cut - 0.05, D.cut + 0.05, vc)) * markOf(D, F, vc);
    var headW = 1 - S3(0.10, 0.25, u);
    var H = wrap01(D.bHue + 0.25 * (2 * D.ax - 1) * clamp01(u) + 0.50 * (2 * D.hd - 1) * headW);
    hsvInto(H, D.bSat, D.bVal, _b);
    hsvInto(H, 0.12 * D.bSat, 0.97, _p);
    hsvInto(H, 0.18 * D.bSat, 0.65 + 0.35 * D.bVal, _bt);
    var s = D.cs, below = S3(D.L - D.wcs, D.L + D.wcs, vc), c;
    for (c = 0; c < 3; c++) {
      var dors = _b[c] * (1 - 0.5 * s), bel = _b[c] + (_bt[c] - _b[c]) * 0.85 * s;
      var col = dors + (bel - dors) * below;
      out[c] = col + (D.mark[c] - col) * fo;
    }
    var lam = D.lam, z = zL, op;
    op = D.ebS * Dm(Math.abs(lam * (u - 0.03)), D.ebW);
    if (op > 0) for (c = 0; c < 3; c++) out[c] += (D.mark[c] - out[c]) * op;
    var sx = lam * (u - 0.24), sz = z - SH_Z;
    op = D.shS * Dm(Math.sqrt(sx * sx + sz * sz), D.shR);
    if (op > 0) for (c = 0; c < 3; c++) out[c] += (D.mark[c] - out[c]) * op;
    var qx = lam * (u - 0.72), dO = Math.sqrt(qx * qx + z * z);
    op = D.ocS * D.ocRing * Math.max(0, Dm(dO, D.ocR + D.ocW) - Dm(dO, D.ocR));
    if (op > 0) for (c = 0; c < 3; c++) out[c] += (_p[c] - out[c]) * op;
    op = D.ocS * Dm(dO, D.ocR);
    if (op > 0) for (c = 0; c < 3; c++) out[c] += (D.mark[c] - out[c]) * op;
    return out;
  }
  /* a fish's flank as an image (the card's swatch): RGBA8, row 0 = the back */
  function flankImage(row, lam, W, H) {
    var D = decode(row, lam), img = new Uint8ClampedArray(W * H * 4), c = [0, 0, 0];
    for (var j = 0; j < H; j++) for (var i = 0; i < W; i++) {
      flankAt(D, (i + 0.5) / W, (j + 0.5) / H, c);
      var o = (j * W + i) * 4;
      img[o] = Math.round(255 * clamp01(c[0])); img[o + 1] = Math.round(255 * clamp01(c[1]));
      img[o + 2] = Math.round(255 * clamp01(c[2])); img[o + 3] = 255;
    }
    return img;
  }
  /* λ = body length / radius: 20·size·elongation / (4.6·B(size)), B = the tank's body-radius curve */
  function lambdaOf(size, elong) { return 20 * size * elong / (4.6 * (1 + 0.4 * Math.tanh(5 * (size - 1)))); }

  /* ---------------- CPU mirror of the vertex stage (MORPH mDecode / mBuild, DECODE) ----------------
   * Line for line the GLSL above, in doubles, with its constants as the GLSL
   * has them (float32), for the production-path check (EvoOceanScene
   * appearancePathCheck): the fish program run on the real gene texture,
   * its outputs read back and compared with these. */
  var C32 = { caud: CAUD_I.map(f32), phi: f32(PHI_I), pec: f32(PEC_THETA), pel: f32(PEL_THETA), eyeT: f32(EYE_T), eyeTh: f32(EYE_TH), iso: f32(ISO_A) };
  function pS(a, b, x) { var t = (x - a) / (b - a); t = t < 0 ? 0 : (t > 1 ? 1 : t); return t * t * (3 - 2 * t); }
  function clampv(x, a, b) { return x < a ? a : (x > b ? b : x); }
  function mixv(x, y, a) { return x + (y - x) * a; }
  function profileY(u) {
    var U = [-0.20, -0.10, 0.04, 0.20, 0.42, 0.64, 0.84, 1.00], Y = [0, 0.50, 0.88, 1.00, 0.86, 0.60, 0.36, 0.20];
    if (u <= U[0]) return 0;
    for (var i = 1; i < 8; i++) if (u < U[i]) return mixv(Y[i - 1], Y[i], (u - U[i - 1]) / (U[i] - U[i - 1]));
    return 0.20;
  }
  function hsv3(h, s, v) { var o = [0, 0, 0]; hsvInto(h, s, v, o); return o; }
  /* DECODE: the flat varyings vG0..vG7, vAux, vMeta of one row (63 floats) */
  function patternVaryings(g, lam) {
    var bcx = 2 * g[0] - 1, bcy = 2 * g[1] - 1, bcc = bcx * bcx + bcy * bcy;
    var vG0 = [bcc === 0 ? 0 : wrap01(Math.atan2(bcy, bcx) / TAU), Math.min(1, Math.sqrt(bcc)), g[2], g[3]];
    var vG1 = [0.15 + 0.70 * g[4], g[5], g[6], g[7]];
    var ox = 2 * g[9] - 1, oy = 2 * g[10] - 1, oo = ox * ox + oy * oy;
    var a = Math.min(1, Math.sqrt(oo)), th = oo === 0 ? 0 : 0.5 * Math.atan2(oy, ox), del = PI * g[11];
    var vG2 = [1.5 * Math.exp(2.0794415416798359 * g[8]), a, Math.cos(th), Math.sin(th)];
    var w = g[12], coh = 1 - pS(0.02, 0.20, Math.abs(Math.sin(del)));
    var q0 = C32.iso * (1 - a), q1 = 0.95 * a;
    var A = Math.sqrt(q0 * q0 + q1 * q1 * (1 + w * w + 2 * w * coh) / ((1 + w) * (1 + w)));
    var vG3 = [w, g[13], Math.max(0, 2 * g[14] - 1), 0];
    var fx = 2 * g[15] - 1, fy = 2 * g[16] - 1, fcc = fx * fx + fy * fy;
    var mc = hsv3(fcc === 0 ? 0 : wrap01(Math.atan2(fy, fx) / TAU), Math.min(1, Math.sqrt(fcc)), g[17]);
    return { vG0: vG0, vG1: vG1, vG2: vG2, vG3: vG3, vG4: [mc[0], mc[1], mc[2], g[18]], vG5: [g[19], g[20], g[21], g[22]],
             vG6: [g[23], g[24], g[25], g[26]], vG7: [g[27], g[28], g[29], g[30]],
             vAux: [Math.cos(th + del), Math.sin(th + del), A, lam], vMeta: [0.35 * Math.sin(TAU * g[31]), 0.25 * Math.sin(TAU * g[32]), 0, 0] };
  }
  function mH(g, a, b, c) { return b + (2 * g - 1) * (g < 0.5 ? b - a : c - b); }
  function mPw(x, p) { return x > 0 ? Math.pow(x, p) : 0; }
  function mSc(c, e) { var a = Math.abs(c); return a > 0 ? Math.sign(c) * Math.pow(a, e) : 0; }
  function caudLEk(k, a) { return k < 2 ? a * a : 0.2 * a * a; }
  function caudTEk(k, a) {
    if (k === 0) return 0.35 + 0.65 * a;
    if (k === 1) return 0.22 + 0.78 * a * a;
    if (k === 2) return 1;
    if (k === 3) return 0.25 + 0.75 * Math.sqrt(Math.max(0, 1 - a * a));
    return 0.20 + 0.80 * (1 - a);
  }
  function caudMix(f, o, a) { var k = Math.min(3, Math.floor(o * 4)), w = pS(0, 1, o * 4 - k); return mixv(f(k, a), f(k + 1, a), w); }
  function caudLE(o, a) { return caudMix(caudLEk, o, a); }
  function caudTE(o, a) { return caudMix(caudTEk, o, a); }
  function caudI(o) { return caudMix(function (k) { return C32.caud[k]; }, o, 0); }
  /* mDecode: the body plan of one row (genes 33..62) at λ */
  function morphDecode(g, lam) {
    var mg = function (j) { return g[MO + j]; }, M = {};
    M.depth = mH(mg(0), 0.22, 1.0, 2.40); M.width = mH(mg(1), 0.18, 1.0, 1.90); M.n = 1 + 2 * mg(2); M.fexp = mH(mg(3), 0.55, 1.0, 1.60);
    M.sh = 0.08 + 0.24 * mg(4); M.hbulk = mH(mg(5), 0.60, 1.0, 1.60); M.sn = mH(mg(6), 0.08, 0.20, 0.40); M.nexp = mH(mg(7), 1.80, 1.0, 0.40);
    M.ped = mH(mg(8), 0.45, 1.0, 1.70); M.outline = mg(9); M.AR = mH(mg(10), 0.50, 2.80, 8.0); M.cA = mH(mg(11), 0.0, 1.20, 3.20);
    M.span = M.cA > 1e-6 ? Math.sqrt(M.AR * M.cA) : 0;
    M.cx = M.cA > 1e-6 ? Math.min(CHORD_CAP, 2 * M.cA / (M.span * caudI(M.outline))) : 0;
    M.dH = 1.60 * mg(12); M.dL = 0.10 + 0.60 * mg(13); M.dS = mg(14); M.dSplit = mg(15);
    M.aH = 1.20 * mg(16); M.aL = 0.10 + 0.45 * mg(17); M.aS = mg(18);
    M.pA = mH(mg(19), 0.0, 0.45, 1.20); M.pT = 0.06 + 0.28 * mg(20); M.pSweep = mH(mg(21), -0.25, 0.50, 1.25); M.pDih = (-70 + 110 * mg(22)) * PI / 180;
    M.vA = mH(mg(23), 0.0, 0.20, 0.90); M.vT = 0.20 + 0.40 * mg(24); M.vSweep = mH(mg(25), 0.0, 0.50, 1.0);
    M.bD = mg(26); M.bReach = mH(mg(27), 0.10, 1.20, 3.0); M.bBeta = mg(28); M.eye = mH(mg(29), 0.40, 1.0, 1.80);
    M.lam = lam;
    return M;
  }
  function mWarp(M, t) { return t <= 0.2 ? -M.sn + (t + 0.2) / 0.4 * (M.sh + M.sn) : M.sh + (t - 0.2) / 0.8 * (1 - M.sh); }
  function mInvWarp(M, u) { return u <= M.sh ? -0.2 + 0.4 * (u + M.sn) / (M.sh + M.sn) : 0.2 + 0.8 * (u - M.sh) / (1 - M.sh); }
  function mHalfAxes(M, t) {
    var headMask = 1 - pS(0.04, 0.30, t), noseMask = 1 - pS(-0.16, 0.04, t), rearMask = pS(0.65, 1.0, t);
    var p = M.fexp * (1 + (M.nexp - 1) * noseMask);
    var sc = (1 + (M.hbulk - 1) * headMask) * (1 + (M.ped - 1) * rearMask);
    return [M.width * mPw(profileY(t), p) * sc, M.depth * 0.84 * mPw(hOf(t) / 0.84, p) * sc];
  }
  function mSurf(M, t, th, side) {
    var ab = mHalfAxes(M, t), e = 2 / M.n;
    return [M.lam * mWarp(M, t), side * ab[0] * mSc(Math.max(Math.cos(th), 0), e), ab[1] * mSc(Math.sin(th), e)];
  }
  function add3(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
  function sub3(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function mul3(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
  /* rings: {ringT (float32 values, as the uniform holds them), half} */
  function mFacet(M, rings, t, th, side) {
    var R = rings.ringT, N = R.length, i = 0, k;
    for (k = 1; k < 16; k++) if (k < N && t >= R[k]) i = k;
    i = Math.min(i, N - 2);
    var t0 = R[i], t1 = R[i + 1], al = clampv((t - t0) / (t1 - t0), 0, 1);
    var stp = PI / rings.half, q = (th + 0.5 * PI) / stp;
    var k0 = clampv(Math.floor(q), 0, rings.half - 1), be = clampv(q - k0, 0, 1);
    var th0 = -0.5 * PI + k0 * stp, th1 = th0 + stp;
    var P10 = mSurf(M, t1, th0, side), P11 = mSurf(M, t1, th1, side);
    if (i === 0) { var P0 = mSurf(M, t0, 0, side); return add3(P0, mul3(sub3(add3(P10, mul3(sub3(P11, P10), be)), P0), al)); }
    var P00 = mSurf(M, t0, th0, side), P01 = mSurf(M, t0, th1, side);
    return al >= be ? add3(add3(P00, mul3(sub3(P10, P00), al)), mul3(sub3(P11, P10), be))
                    : add3(add3(P00, mul3(sub3(P01, P00), be)), mul3(sub3(P11, P01), al));
  }
  function mFinH(H, split, s) { return H * 4 * s * (1 - s) * (1 - split * (1 - pS(0.08, 0.20, Math.abs(s - 0.5)))); }
  function mSeg2(px, py, ax, ay, bx, by) {
    var ux = bx - ax, uy = by - ay, L2 = ux * ux + uy * uy;
    var t = L2 > 0 ? clampv(((px - ax) * ux + (py - ay) * uy) / L2, 0, 1) : 0;
    return Math.hypot(px - ax - t * ux, py - ay - t * uy);
  }
  /* mBuild: one template vertex (a = aT, pat = aPattern) of one body ->
   * {geo, mat, mar} (rest point in body radii, material site, fin margin) */
  function morphBuild(M, rings, a, pat, time, wag, minW) {
    var fin = Math.floor(pat[0] + 0.5), side = pat[2], mar = 1000, geo, mat, k, d, pp, qq, sk;
    if (fin === 0) {
      var p = mSurf(M, a[0], a[1], side);
      geo = [p[0], a[2] * p[1], a[2] * p[2]]; mat = [a[0], a[1], a[2]];
    } else if (fin === 1) {
      var eta = a[0], row = a[1], ae = Math.abs(eta);
      var LE = caudLE(M.outline, ae), TE = caudTE(M.outline, ae), r = clampv(row, 0, 1);
      var x = M.cx * (LE + r * (TE - LE)), z = 0.5 * M.span * eta;
      var B1 = mHalfAxes(M, 1)[1], xLE = M.cx * LE;
      if (row < -0.5) { var wc = 1 - pS(0.75 * B1, B1, Math.abs(z)); x = xLE + wc * (-0.12 - xLE); }
      geo = [M.lam + x, 0, z];
      var vLE = 0.5 * (1 - Math.sign(z) * Math.pow(Math.min(1, Math.abs(z) / Math.max(B1, 1e-6)), 0.5 * M.n)), vTE = 0.5 * (1 - eta);
      mat = [1 + x / M.lam, row < -0.5 ? vLE : vLE + r * (vTE - vLE), 0];
      var chord = M.cx * (TE - LE), hh = 0.01;
      var a1 = Math.min(ae + hh, 1), a0 = Math.max(ae - hh, 0), dz = (a1 - a0) * 0.5 * M.span + 1e-6;
      var sTE = M.cx * (caudTE(M.outline, a1) - caudTE(M.outline, a0)) / dz, sLE = M.cx * (caudLE(M.outline, a1) - caudLE(M.outline, a0)) / dz;
      var nTE = 1 / Math.sqrt(1 + sTE * sTE), nLE = 1 / Math.sqrt(1 + sLE * sLE);
      var fr = pS(0.9 * B1, 1.2 * B1, Math.abs(z));
      if (row < -0.5) mar = 1000;
      else if (row < 0.25) mar = Math.min(chord * nTE, (1 - fr) * 1000);
      else if (row < 0.75) mar = Math.min(0.5 * chord * nTE, 0.5 * chord * nLE + (1 - fr) * 1000);
      else mar = 0;
    } else if (fin === 2 || fin === 5) {
      var s = a[0], q = a[1], dors = fin === 2, up = dors ? 1 : -1;
      var ell = dors ? M.dL : M.aL, H = dors ? M.dH : M.aH, start = 0.04 + (0.92 - ell) * (dors ? M.dS : M.aS), split = dors ? M.dSplit : 0;
      var t = start + ell * s, root = mFacet(M, rings, t, up * 0.5 * PI, 1), ht = mFinH(H, split, s);
      geo = [root[0], 0, root[2] + up * q * ht];
      var b0 = Math.max(hOf(t), 1e-3);
      mat = [t, dors ? -0.5 * q * ht / b0 : 1 + 0.5 * q * ht / b0, 0];
      var X0 = M.lam * mWarp(M, t);
      d = 1000; pp = [M.lam * mWarp(M, start), mFinH(H, split, 0)];
      for (k = 1; k <= 16; k++) { sk = k / 16; qq = [M.lam * mWarp(M, start + ell * sk), mFinH(H, split, sk)]; d = Math.min(d, mSeg2(X0, 0, pp[0], pp[1], qq[0], qq[1])); pp = qq; }
      mar = (1 - q) * d;
    } else if (fin === 3 || fin === 6) {
      var s2 = a[0], r2 = a[1], pec = fin === 3;
      var chord2 = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, tc = pec ? M.pT : M.vT, sweep = pec ? M.pSweep : M.vSweep;
      var dih = pec ? M.pDih : -0.25 * PI, thr = pec ? C32.pec : C32.pel;
      var span = area / (chord2 * C32.phi);
      var X = M.lam * mWarp(M, tc) + chord2 * (s2 - 0.5), t2 = mInvWarp(M, X / M.lam);
      var root2 = mFacet(M, rings, t2, thr, side), phi = 4 * s2 * (1 - s2), w = span * r2 * phi;
      geo = add3(root2, [sweep * w, side * w * Math.cos(dih), w * Math.sin(dih)]);
      mat = [t2 + sweep * w / M.lam, 0.5 * (1 - Math.sin(thr)) + 0.21 * r2 * phi, 0];
      var x0 = chord2 * (s2 - 0.5);
      d = 1000; pp = [-0.5 * chord2, 0];
      for (k = 1; k <= 16; k++) { sk = k / 16; var wk = span * 4 * sk * (1 - sk); qq = [chord2 * (sk - 0.5) + sweep * wk, wk]; d = Math.min(d, mSeg2(x0, 0, pp[0], pp[1], qq[0], qq[1])); pp = qq; }
      mar = (1 - r2) * d;
    } else if (fin === 4) {
      var kE = Math.min(M.eye, 0.32 * mHalfAxes(M, C32.eyeT)[1] / 0.14);
      var c = mSurf(M, C32.eyeT, C32.eyeTh, side);
      var Xe = c[0] + a[0] * 0.24 * kE, Ze = c[2] + a[1] * 0.14 * kE;
      var te = mInvWarp(M, Xe / M.lam), ab = mHalfAxes(M, te);
      var sn = Math.sign(Ze) * Math.pow(Math.min(1, Math.abs(Ze) / Math.max(ab[1], 1e-6)), 0.5 * M.n);
      var pe = mSurf(M, te, Math.asin(clampv(sn, -1, 1)), side);
      geo = [pe[0], side * (Math.abs(pe[1]) + 0.04 + 0.05 * ab[0]), pe[2]]; mat = [0, 0, 0];
    } else {
      var qb = a[0], ws = a[1], j = a[2], rib = a[3];
      var db = Math.max(0, (M.bD - 0.2) / 0.8), wj = pS(0, 1, 3 * db - j);
      var tj = -0.16 + 0.18 * M.bBeta + 0.015 * j, thj = -PI * (0.06 + 0.25 * M.bBeta + 0.055 * j);
      var P0 = mFacet(M, rings, tj, thj, 1), L = M.bReach * (1 - 0.15 * j) * wj;
      var P1 = add3(P0, mul3([-0.30, 0.40, -0.20], L)), P2 = add3(P0, mul3([0.25, 0.70, -0.55], L));
      var C = add3(add3(mul3(P0, (1 - qb) * (1 - qb)), mul3(P1, 2 * qb * (1 - qb))), mul3(P2, qb * qb));
      var T = add3(mul3(sub3(P1, P0), 2 * (1 - qb)), mul3(sub3(P2, P1), 2 * qb)), tl = Math.hypot(T[0], T[1], T[2]);
      T = tl > 1e-9 ? mul3(T, 1 / tl) : [1, 0, 0];
      var n1 = [T[1], -T[0], 0], nl = Math.hypot(n1[0], n1[1]);
      n1 = nl > 1e-6 ? mul3(n1, 1 / nl) : [0, 1, 0];
      var n2 = [T[1] * n1[2] - T[2] * n1[1], T[2] * n1[0] - T[0] * n1[2], T[0] * n1[1] - T[1] * n1[0]];
      var sw = wag * 0.10 * L * qb * qb * Math.sin(5.5 * time + 2 * j + (side > 0 ? 0 : 1.3));
      var hw = wj > 0 ? Math.max(0.04 * (1 - 0.6 * qb) * Math.min(1, 4 * wj), minW) : 0;
      geo = add3(add3(C, mul3(n2, sw)), mul3(rib < 0.5 ? n1 : n2, ws * hw));
      geo[1] *= side;
      mat = [tj, thj, qb];
    }
    return { geo: geo, mat: mat, mar: mar };
  }

  window.EvoAppearance = {
    LAWS: LAWS, NG: NG, MO: MO, NM: NM, STRIDE: STRIDE,
    /* the paired fins' span law's constant (mBuild: span = area / (chord PHI_I)),
     * for the renderer's fin pose (web/ocean_scene.js finPose: the fold keeps the root) */
    PHI_I: PHI_I,
    GLSL: { COMMON: COMMON, VARY: VARY, DECODE: DECODE, SKIN: SKIN, GENES: GENES, MORPH: MORPH },
    LODS: LODS, buildTemplate: buildTemplate, buildBarbels: buildBarbels,
    decode: decode, flankAt: flankAt, flankImage: flankImage, lambdaOf: lambdaOf,
    patternVaryings: patternVaryings, morphDecode: morphDecode, morphBuild: morphBuild
  };
})();
