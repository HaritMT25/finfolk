// tools/ocean_render_perf/decode_bench.cjs: the decoded cache's per-birth cost, measured (docs/ocean_render_perf.md quotes it).
//   node tools/ocean_render_perf/decode_bench.cjs [N=2000] [BATCHES=15] [REPS=10]
// EvoAppearance.writeDecoded (web/ocean_appearance.js) is what the scene runs once for each newborn's gene row (the slot store's
// onInstall hook; the same function writes a restored context's whole cache, a Look change's and a new world's): 18 RGBA32F texels,
// 72 floats, of the morph fields, the pattern varyings and the body plan. The benchmark times it over N random rows (genes uniform in
// [0, 1], float32, the cache's own layout: slot i at row i) BATCHES times after a warm-up and reports the median and the range of the
// per-fish cost. It is the decoder alone, in node's V8 (the browser's engine; its JIT warm), on one thread: a microbenchmark, not a
// frame time. The page-level cost of births is in the cycled harness's CPU spans (docs/ocean_render_perf.md).
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const N = +process.argv[2] || 2000, BATCHES = +process.argv[3] || 15, REPS = +process.argv[4] || 10;
const ctx = vm.createContext({ console, Math, Float32Array, Float64Array, Object, Array, JSON });
ctx.window = ctx; ctx.globalThis = ctx;
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "..", "web", "ocean_appearance.js"), "utf8"), ctx, { filename: "ocean_appearance.js" });
const EA = ctx.EvoAppearance;
let s = 1; const rnd = () => { s = (Math.imul(s, 1664525) + 1013904223) | 0; return (s >>> 0) / 4294967296; };
const rows = []; for (let i = 0; i < N; i++) rows.push(Float32Array.from({ length: 63 }, rnd));
const out = new Float32Array(N * EA.DECODED_FLOATS);
for (let w = 0; w < 5; w++) for (let i = 0; i < N; i++) EA.writeDecoded(rows[i], out, i);   /* warm-up: the JIT */
const per = [];
for (let b = 0; b < BATCHES; b++) {
  const t0 = process.hrtime.bigint();
  for (let r = 0; r < REPS; r++) for (let i = 0; i < N; i++) EA.writeDecoded(rows[i], out, i);
  per.push(Number(process.hrtime.bigint() - t0) / 1e3 / (REPS * N));   /* microseconds a fish */
}
per.sort((a, b) => a - b);
const med = per[per.length >> 1];
console.log(JSON.stringify({ node: process.version, N, floatsPerFish: EA.DECODED_FLOATS, batches: BATCHES, repsPerBatch: REPS,
  usPerFish: { min: +per[0].toFixed(2), median: +med.toFixed(2), max: +per[per.length - 1].toFixed(2) }, msFor2000Births: +(med * 2).toFixed(2) }));
console.log("writeDecoded: " + med.toFixed(2) + " us a fish (median of " + BATCHES + " batches; " + per[0].toFixed(2) + " to " + per[per.length - 1].toFixed(2) + "); " + (med * 2000 / 1000).toFixed(2) + " ms for 2,000 births");
