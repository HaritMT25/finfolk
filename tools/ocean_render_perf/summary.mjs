// tools/ocean_render_perf/summary.mjs RESULT.json ...: the condensed before / after table of cycle.mjs runs, one row a cell: the
// reference arm (q3: the reference policy) and each optimized arm's GPU frame time (p50, median over the cycles, with the IQR of the
// cycles' paired differences against that cycle's anchor), the vertices and fish draws a frame, the CPU frame time (p50).
//   node summary.mjs a1/*/result.json > summary.md
import fs from "node:fs";
const files = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const qt = (a, p) => { if (!a.length) return NaN; const s = a.slice().sort((x, y) => x - y), i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
const med = (a) => qt(a, 0.5), mean = (a) => a.reduce((x, y) => x + y, 0) / (a.length || 1);
const f = (x, d = 2) => (Number.isFinite(x) ? x.toFixed(d) : "-");
const IDX = { 708: 190, 324: 89, 288: 120 };
const COLS = ["lod", "cache", "barb", "all"];
console.log("| cell | arm | GPU p50 ms | paired change vs the reference (median; IQR) | ratio | verts / frame | fish draws | CPU frame p50 ms |");
console.log("|---|---|---|---|---|---|---|---|");
for (const file of files) {
  const R = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const [key, cell] of Object.entries(R.cells)) {
    if (!cell.obs.length) continue;
    const cycles = [...new Set(cell.obs.map((o) => o.round))].sort((a, b) => a - b);
    const gp = (arm, c) => { const o = cell.obs.find((x) => x.arm === arm && x.round === c); const g = o && o.summary.gpu.labels.frame; return g ? g.scopes.p50 : NaN; };
    const anchor = (c) => mean([gp("q3", c), gp("q3z", c)].filter(Number.isFinite));
    const tag = `${R.colour === "family" ? "Family" : "Appearance"} ${cell.fish} fish ${cell.camera}${R.viewport.dpr > 1 ? " DPR " + R.viewport.dpr : ""}${file.indexOf("live") >= 0 ? " (live)" : ""}`;
    const arms = ["q3"].concat(COLS.concat(["lodCache"]).filter((a) => cell.obs.some((o) => o.arm === a)));
    for (const arm of arms) {
      const os = cell.obs.filter((o) => o.arm === arm), o0 = os[0], st = o0.state, fr = Math.max(1, o0.census.frames);
      let verts = 0, draws = 0;
      for (const [k, cn] of Object.entries(o0.census.tally)) { const m = /^E:(\d+)x(\d+)$/.exec(k); if (!m || !IDX[+m[1]]) continue; draws += cn / fr; verts += (cn / fr) * IDX[+m[1]] * +m[2]; }
      const diffs = cycles.map((c) => gp(arm, c) - anchor(c)), ratios = cycles.map((c) => gp(arm, c) / anchor(c));
      console.log(`| ${arm === "q3" ? tag : ""} | ${arm === "q3" ? "reference" : arm} | ${f(med(cycles.map((c) => gp(arm, c))))} | ${arm === "q3" ? "-" : `${f(med(diffs))} (${f(qt(diffs, 0.25))}..${f(qt(diffs, 0.75))})`} | ${arm === "q3" ? "1" : f(med(ratios), 3)} | ${f(verts / 1e6, 3)}M | ${f(draws, 1)} | ${f(med(os.map((o) => o.summary.spans.frameCpu.p50)))} |`);
    }
  }
}
