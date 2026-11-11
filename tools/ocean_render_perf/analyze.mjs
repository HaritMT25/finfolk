// tools/ocean_render_perf/analyze.mjs RESULT.json ...: the cycle design's tables (cycle.mjs): per cell, every arm against that cycle's q3
// anchor (the mean of q3 and q3z in the cycle), paired by cycle; medians and IQRs over the cycles; verts, triangles and draw
// counts per frame from the draw census (every instanced draw, one-instance draws included, with the index-count -> vertex
// maps below: the templates' known sizes), and the incremental pairs (lodCache - lod, all - lodCache, ...).
//   node analyze.mjs RESULT.json ... [--md]
import fs from "node:fs";
const files = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const qt = (a, p) => { if (!a.length) return NaN; const s = a.slice().sort((x, y) => x - y), i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
const med = (a) => qt(a, 0.5), mean = (a) => a.reduce((x, y) => x + y, 0) / (a.length || 1);
const f = (x, d = 2) => (Number.isFinite(x) ? x.toFixed(d) : "-");
/* index counts of the fish templates: medium 708 (190 verts), coarse 324 (89), barbels 288 (120) */
const IDX = { 708: 190, 324: 89, 288: 120 };
const PAIRS = [["lodCache", "lod"], ["all", "lodCache"], ["all", "barb"], ["all", "cache"], ["all", "q3"], ["lod", "q3"], ["cache", "q3"], ["barb", "q3"], ["lodCache", "q3"]];
const out = {};
for (const file of files) {
  const R = JSON.parse(fs.readFileSync(file, "utf8"));
  const tag = file.replace(/\\/g, "/").replace(/.*render_perf\//, "").replace(/\/result.json$/, "");
  console.log(`\n### ${tag}  (${R.colour || "appearance"}; viewport ${R.viewport.width}x${R.viewport.height}@${R.viewport.dpr}, block ${R.dur} ms + settle ${R.settle}, cycles ${R.rounds})`);
  for (const [key, cell] of Object.entries(R.cells)) {
    if (!cell.obs.length) continue;
    const arms = [...new Set(cell.obs.map((o) => o.arm))];
    const cycles = [...new Set(cell.obs.map((o) => o.round))].sort((a, b) => a - b);
    const gp = (arm, c, what) => { const o = cell.obs.find((x) => x.arm === arm && x.round === c); const g = o && o.summary.gpu.labels.frame; return g ? g.scopes[what] : NaN; };
    const anchor = (c) => mean([gp("q3", c, "p50"), gp("q3z", c, "p50")].filter(Number.isFinite));
    const aMed = med(cycles.map(anchor));
    console.log(`\n#### cell ${key}: q3 anchor p50 ${f(aMed)} ms (median over ${cycles.length} cycles; q3 vs q3z paired: ${f(med(cycles.map((c) => gp("q3", c, "p50") - gp("q3z", c, "p50"))))} ms, anchor p50 spread over cycles ${f(qt(cycles.map(anchor), 0))}..${f(qt(cycles.map(anchor), 1))})\n`);
    console.log("| arm | GPU p50 (median of blocks) | IQR of block p50 | GPU p95 | paired diff vs anchor, ms (median; IQR) | ratio to anchor | CPU frame p50 | rAF fps | buffer@DPR | fish draws/frame | verts/frame | tris/frame |");
    console.log("|---|---|---|---|---|---|---|---|---|---|---|---|");
    const sum = {};
    for (const arm of arms) {
      const os = cell.obs.filter((o) => o.arm === arm), o0 = os[0];
      if (o0.summary.gpu.labels.frame === undefined) continue;
      const blocks = cycles.map((c) => gp(arm, c, "p50"));
      const p50 = med(blocks), p95 = med(cycles.map((c) => gp(arm, c, "p95")));
      const diffs = cycles.map((c) => gp(arm, c, "p50") - anchor(c)), ratios = cycles.map((c) => gp(arm, c, "p50") / anchor(c));
      const cpu = med(os.map((o) => o.summary.spans.frameCpu.p50)), fps = med(os.map((o) => o.raf.rafFps));
      const st = o0.state, fr = Math.max(1, o0.census.frames);
      let draws = 0, verts = 0, tris = 0; const desc = [];
      for (const [k, cn] of Object.entries(o0.census.tally)) {
        const m = /^E:(\d+)x(\d+)$/.exec(k); if (!m) continue;
        const n = +m[1], inst = +m[2], per = cn / fr;
        if (IDX[n]) { draws += per; verts += per * IDX[n] * inst; tris += per * (n / 3) * inst; desc.push(`${per.toFixed(1)}x${n}x${inst}`); }
      }
      sum[arm] = { p50, ratio: med(ratios), diff: med(diffs), diffs, blocks };
      console.log(`| ${arm} | ${f(p50)} | ${f(qt(blocks, 0.25))}..${f(qt(blocks, 0.75))} | ${f(p95)} | ${f(med(diffs))} (${f(qt(diffs, 0.25))}..${f(qt(diffs, 0.75))}) | ${f(med(ratios), 3)} | ${f(cpu)} | ${f(fps, 1)} | ${st.drawingBuffer.join("x")}@${st.pixelRatio} | ${f(draws, 1)} | ${f(verts / 1e6, 3)}M | ${f(tris / 1e6, 3)}M |`);
    }
    const dArms = arms.filter((a) => cell.obs.find((o) => o.arm === a).summary.gpu.labels.frame === undefined);
    if (dArms.length) {
      const labels = [...new Set(dArms.flatMap((a) => Object.keys(cell.obs.find((o) => o.arm === a).summary.gpu.labels)))];
      console.log(`\nper-draw GPU scopes, ms per frame (median over cycles of each block's per-frame p50; a diagnostic, not additive with the frame timer):\n`);
      console.log("| arm | " + labels.join(" | ") + " | sum |");
      console.log("|---|" + labels.map(() => "---|").join("") + "---|");
      for (const a of dArms) {
        const os = cell.obs.filter((o) => o.arm === a);
        const vals = labels.map((l) => med(os.map((o) => o.summary.gpu.labels[l] ? o.summary.gpu.labels[l].perFrame.p50 : 0)));
        console.log(`| ${a} | ${vals.map((v) => f(v)).join(" | ")} | ${f(vals.reduce((x, y) => x + y, 0))} |`);
      }
    }
    const inc = PAIRS.filter(([a, b]) => sum[a] && sum[b]);
    if (inc.length) {
      console.log("\nincremental paired deltas (per cycle, then median; IQR), ms:\n");
      for (const [a, b] of inc) {
        const d = cycles.map((c, i) => gp(a, c, "p50") - gp(b, c, "p50")).filter(Number.isFinite);
        console.log(`- ${a} - ${b}: ${f(med(d))} (${f(qt(d, 0.25))}..${f(qt(d, 0.75))})`);
      }
    }
    const sc = (a) => sum[a] && sum[a].ratio * aMed;
    console.log("\nderived, anchor-scaled ms (1 - ratio) x anchor:");
    const d = (name, v) => console.log(`- ${name}: ${f(v)} ms`);
    if (sum.q3ns) d("shadow pass at q3 (q3 - q3ns)", aMed - sc("q3ns"));
    if (sum.q3nb) d("barbel draw at q3 (q3 - q3nb)", aMed - sc("q3nb"));
    if (sum.q3nf) d("all fish passes at q3 (q3 - q3nf)", aMed - sc("q3nf")), d("scene with no fish (q3nf): the fixed cost", sc("q3nf"));
    if (sum.q2) d("medium -> coarse (q3 - q2: also snow off, barbels off)", aMed - sc("q2"));
    if (sum.q3vall) d("fish passes, vertex/setup only (q3vall - q3nf)", sc("q3vall") - sc("q3nf")), d("fish passes, fragment part (q3 - q3vall)", aMed - sc("q3vall"));
    if (sum.all && sum.allnf) d("optimized fish passes (all - allnf)", sc("all") - sc("allnf"));
    if (sum.allvall && sum.allnf) d("optimized fish passes, vertex-only (allvall - allnf)", sc("allvall") - sc("allnf"));
    out[tag + "/" + key] = { anchor: aMed, sum };
  }
}
fs.writeFileSync(process.env.ANALYZE_JSON || "analyze_out.json", JSON.stringify(out));
