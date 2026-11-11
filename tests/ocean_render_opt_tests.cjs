// tests/ocean_render_opt_tests.cjs: the Ocean render optimization's pure parts, in node (no browser, no GPU).
//   node tests/ocean_render_opt_tests.cjs
// The body LOD's decision (web/ocean_pose.js bodyLod: thresholds, hysteresis, pinned, detail) and the barbels'
// gate (barbelVisible: the float32 0.2 boundary, the size thresholds). The scene's use of them (bucketing,
// compaction, rings, the decoded cache) is tested through the real scene in tests/ocean_mock_three_tests.mjs and
// on the GPU in tests/ocean_render_browser.mjs.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const WEB = path.join(__dirname, "..", "web");

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 400) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }
function load(files) {
  const ctx = vm.createContext({ console, Math, JSON, Float32Array, Float64Array, Int32Array, Uint8Array, Array, Object, Error, Number, String, isFinite, Infinity, NaN });
  ctx.globalThis = ctx;
  for (const f of files) vm.runInContext(fs.readFileSync(path.join(WEB, f), "utf8"), ctx, { filename: f });
  return ctx;
}

const POSE = load(["ocean_pose.js"]).EvoOceanPose;
const { LOD_COARSE, LOD_MEDIUM, bodyLod, barbelVisible } = POSE;
const EN = POSE.LOD_MEDIUM_ENTER_CSS, EX = POSE.LOD_MEDIUM_EXIT_CSS;

section("body LOD (bodyLod)");
{
  ok(LOD_COARSE === 1 && LOD_MEDIUM === 2 && EX < EN, "buckets 1 coarse / 2 medium; the exit threshold is below the entry (a hysteresis band)", { EN, EX });
  ok(bodyLod(EN, 0, 3, false) === LOD_MEDIUM, "a new fish exactly at the entry threshold: medium (>=)");
  ok(bodyLod(EN - 1e-9, 0, 3, false) === LOD_COARSE, "a new fish just under the entry threshold: coarse");
  ok(bodyLod((EN + EX) / 2, 0, 3, false) === LOD_COARSE, "a new fish inside the band: coarse");
  ok(bodyLod((EN + EX) / 2, LOD_COARSE, 3, false) === LOD_COARSE, "a coarse fish inside the band stays coarse");
  ok(bodyLod((EN + EX) / 2, LOD_MEDIUM, 3, false) === LOD_MEDIUM, "a medium fish inside the band stays medium");
  ok(bodyLod(EX, LOD_MEDIUM, 3, false) === LOD_COARSE, "a medium fish exactly at the exit threshold: coarse (<=)");
  ok(bodyLod(EX + 1e-9, LOD_MEDIUM, 3, false) === LOD_MEDIUM, "a medium fish just over the exit threshold stays medium");
  ok(bodyLod(0, 0, 3, false) === LOD_COARSE && bodyLod(1e9, 0, 3, false) === LOD_MEDIUM && bodyLod(NaN, LOD_COARSE, 3, false) === LOD_COARSE,
     "extremes: nothing on screen, enormous; a NaN size keeps a coarse fish coarse");
  for (const q of [1, 2]) ok(bodyLod(1e9, LOD_MEDIUM, q, true) === LOD_COARSE, "detail " + q + ": every body coarse, a pinned or huge one too");
  ok(bodyLod(0.5, LOD_COARSE, 3, true) === LOD_MEDIUM && bodyLod(0, 0, 3, true) === LOD_MEDIUM, "detail 3: a selected / hovered fish is medium at any size");
  /* a walk across the band and back: one switch each way, none inside the band */
  let prev = 0, sw = 0, px = 0.5, path = [];
  for (let i = 0; i < 400; i++) {
    px = i < 200 ? 0.5 + i * 0.05 : 10.45 - (i - 200) * 0.05;   /* 0.5 -> 10.45 -> 0.5 */
    const l = bodyLod(px, prev, 3, false);
    if (prev && l !== prev) { sw++; path.push(+px.toFixed(2)); }
    prev = l;
  }
  ok(sw === 2 && path[0] >= EN - 0.06 && path[1] <= EX + 0.06, "a size walked up through the band and back switches once up (at the entry) and once down (at the exit)", { sw, path });
  /* jitter inside the band never flips a fish */
  let flips = 0; prev = LOD_MEDIUM;
  for (let i = 0; i < 100; i++) { const l = bodyLod(EX + 0.1 + (i % 7) * 0.25, prev, 3, false); if (l !== prev) flips++; prev = l; }
  ok(flips === 0, "jitter inside the band (a medium fish) flips nothing");
  /* q3 -> q2 -> q1 -> q3 */
  let l = bodyLod(9, LOD_MEDIUM, 3, false);
  const seq = [3, 2, 1, 3].map((q) => (l = bodyLod(9, l, q, false)));
  ok(seq.join() === [LOD_MEDIUM, LOD_COARSE, LOD_COARSE, LOD_MEDIUM].join(), "detail 3 -> 2 -> 1 -> 3 for a big fish: medium, coarse, coarse, medium again", seq);
}

section("visibility (poseVisible: the body LOD's out-of-view test, no size in it)");
{
  /* a 90 degree camera at the origin looking down -z (the view matrix the identity): the centre's depth is -z, side planes at 45 degrees */
  const s = Math.SQRT1_2, I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const G = { view: I, proj: I, focal: 500, near: 0.1, halfW: 0, halfH: 0, gate: true, zero: false, planes: [s, -s, -s, -s, s, -s, -s, -s] };
  const K = POSE.REACH_APP, spine = (x, z) => [[x, x + 1, x + 2, x + 3, x + 4, x + 5], [z, z, z, z, z, z]];
  const vis = (x, z, y) => { const [xs, ys] = spine(x, z); return POSE.poseVisible(xs, ys, 0.3, y || 0, G, 0, 3, K); };
  const visQ = (x, z, px) => { const [xs, ys] = spine(x, z); return POSE.poseVisibleQ(xs, ys, 0.3, 0, G, 0, 3, K, px); };
  ok(vis(0, -50) === true, "a fish in front of the camera, on its axis: visible");
  ok(vis(0, 50) === false, "a fish behind the camera: not visible");
  ok(vis(1000, -50) === false && vis(-1000, -50) === false, "a fish wholly outside a side plane (either side): not visible");
  ok(vis(0, -50, 900) === false && vis(0, -50, -900) === false, "a fish wholly above or below the view: not visible");
  const rv = POSE.reachRadius(spine(0, -50)[0], spine(0, -50)[1], 0.3, 0, 3, K), xAt = (m) => 50 + m / s - 2.5;   /* the x whose centre is m outside the right plane */
  ok(rv > 1 && vis(xAt(0.5 * rv), -50) === true && vis(xAt(2 * rv), -50) === false,
     "a fish whose centre is outside a side plane by half its reach: visible (its sphere comes back in); by twice its reach: not", { rv });
  /* the weight (poseVisibleQ) is the same test and the size ramp: zero up to about 6 px for a fish in view, the ramp's own value above;
   * poseVisible does not look at the size */
  ok(visQ(0, -50, 5.5) === 0 && vis(0, -50) === true, "a fish in view at 5.5 px: weight 0 (the polish's ramp) but visible (the LOD must keep its body)");
  ok(visQ(0, -50, 12) === 127 && visQ(0, -50, 8.5) > 0 && visQ(0, -50, 8.5) < 127, "in view: weight 127 from 11 px, a ramp between 6 and 11");
  ok(visQ(0, 50, 12) === 0 && visQ(1000, -50, 12) === 0, "out of view: weight 0 whatever the size (poseVisibleQ is poseVisible and the ramp)");
}

section("barbels' gate (barbelVisible)");
{
  const G = POSE.BARBEL_GENE_MIN, up = new Float32Array(new Uint32Array([new Uint32Array(new Float32Array([G]).buffer)[0] + 1]).buffer)[0];
  ok(G === Math.fround(0.2) && G !== 0.2, "the gene threshold is the float32 0.2 (the shader's literal), not the double");
  ok(up > G && Math.fround(up) === up, "the next float above it exists", { G, up });
  ok(!barbelVisible(G, 50, false, 3, LOD_MEDIUM), "a gene exactly at float32 0.2: no barbels (the shader's weights vanish there)");
  ok(barbelVisible(up, 50, false, 3, LOD_MEDIUM), "the next float above it: barbels");
  ok(0.2 < G && !barbelVisible(0.2, 50, false, 3, LOD_MEDIUM), "the double 0.2 is below the float32 one: none (a stored gene is a float32, so this value does not occur)");
  ok(!barbelVisible(0.9, 50, false, 2, LOD_MEDIUM) && !barbelVisible(0.9, 50, false, 1, LOD_MEDIUM), "detail below 3: none");
  ok(!barbelVisible(0.9, 50, false, 3, LOD_COARSE), "a coarse-bucket fish: none (the coarse template has no barbels)");
  const EN2 = POSE.BARBEL_ENTER_CSS, EX2 = POSE.BARBEL_EXIT_CSS;
  ok(EX2 < EN2 && EN2 <= EN, "its size band sits below the body's entry threshold (a medium fish can lose them first)", { EN2, EX2, EN });
  ok(barbelVisible(0.9, EN2, false, 3, LOD_MEDIUM) && !barbelVisible(0.9, EN2 - 1e-9, false, 3, LOD_MEDIUM), "entering at the threshold (>=)");
  ok(barbelVisible(0.9, EX2 + 1e-9, true, 3, LOD_MEDIUM) && !barbelVisible(0.9, EX2, true, 3, LOD_MEDIUM), "keeping them down to the exit threshold (>)");
  ok(!barbelVisible(0.9, (EN2 + EX2) / 2, false, 3, LOD_MEDIUM) && barbelVisible(0.9, (EN2 + EX2) / 2, true, 3, LOD_MEDIUM), "inside the band: they stay as they were");
}

section("the decoded constants' packer (EvoAppearance.writeDecoded)");
{
  const ctx = vm.createContext({ console, Math, JSON, Float32Array, Float64Array, Int32Array, Uint8Array, Array, Object, Error, Number, String, isFinite, Infinity, NaN });
  ctx.window = ctx; ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(WEB, "ocean_appearance.js"), "utf8"), ctx, { filename: "ocean_appearance.js" });
  const EA = ctx.EvoAppearance, FL = EA.DECODED_FLOATS, ST = EA.STRIDE;
  let seed = 12345;
  const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; };
  const rowOf = (f) => Float32Array.from({ length: ST }, (_, j) => Math.fround(f(j)));
  const rows = [rowOf(() => 0), rowOf(() => 1), rowOf(() => 0.5), rowOf((j) => (j % 2 ? 1 : 0)), rowOf((j) => (j === 0 || j === 1 ? 0.5 : 0.5)), rowOf((j) => (j === 9 || j === 10 ? 0.5 : rnd()))];
  for (let i = 0; i < 400; i++) rows.push(rowOf(() => rnd()));
  ok(FL === 72 && EA.DECODED_TEXELS === 18 && EA.DECODED_WIDTH === 576 && EA.DECODED_ROW_SLOTS === 32 && EA.DECODED_MORPH_FIELDS.length === 32, "the layout constants: 18 texels = 72 floats a slot, 32 slots a row, 576 wide, 32 body-plan fields");
  const out = new Float32Array(FL * 8);
  let bad = [], nonFinite = 0;
  rows.forEach((row, i) => {
    out.fill(7);
    const slot = i % 8;
    EA.writeDecoded(row, out, slot);
    const M = EA.morphDecode(row, 1), P = EA.patternVaryings(row, 1), o = slot * FL, want = [];
    EA.DECODED_MORPH_FIELDS.forEach((n) => want.push(M[n]));
    for (let k = 0; k < 8; k++) want.push(...P["vG" + k]);
    want.push(P.vAux[0], P.vAux[1], P.vAux[2], 0, P.vMeta[0], P.vMeta[1], 0, 0);
    for (let j = 0; j < FL; j++) {
      if (!Object.is(out[o + j], Math.fround(want[j]))) { bad.push("row " + i + " float " + j + ": " + out[o + j] + " vs " + Math.fround(want[j])); break; }
      if (!isFinite(out[o + j])) nonFinite++;
    }
    for (let s = 0; s < 8; s++) if (s !== slot) for (let j = 0; j < FL; j++) if (out[s * FL + j] !== 7) { bad.push("row " + i + " wrote outside its slot (" + s + ")"); s = 8; break; }
  });
  ok(bad.length === 0, "every row (" + rows.length + ": all 0, all 1, neutral, striped, random): the 72 floats are the CPU mirrors' (morphDecode, patternVaryings) rounded to float32, in the layout; no other slot touched", bad.slice(0, 3));
  ok(nonFinite === 0, "every decoded float finite, for neutral and extreme genes alike (zero chroma and orientation included)", nonFinite);
  /* lambda is not cached: vAux.w and Morph.lam come from the fish's current size, every frame */
  const a = new Float32Array(FL), b = new Float32Array(FL);
  EA.writeDecoded(rows[10], a, 0); EA.writeDecoded(rows[10], b, 0);
  ok(a.every((x, j) => Object.is(x, b[j])) && a[67] === 0 && a[70] === 0 && a[71] === 0, "deterministic; the padding (texel 16 w, texel 17 zw) is zero, lambda is not stored");
  /* the GLSL readers match the layout (also asserted by the shader-slot tests, against the assembled programs) */
  ok(EA.GLSL.DECODED_READ.includes("ivec2(18 * (slot % 32) + k, slot / 32)") && /decodedTexel\(s, 7\)/.test(EA.GLSL.DECODED_MORPH) && /decodedTexel\(slot, 17\)/.test(EA.GLSL.DECODED_PATTERN),
     "the readers' address math is the layout's");
}

console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);
