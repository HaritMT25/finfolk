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

console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);
