// tools/ocean_render_perf/cycle.mjs: the cycled, drift-cancelling GPU-frame harness for the Ocean page (headless Brave, Playwright).
//
// One page per cell; the arms run in short blocks, cycled (the order reversed on odd cycles), each block with a settle
// first, a rAF probe, a capture (cpu spans + GPU frame queries every EVERY-th submission, or per-draw scopes) and a draw
// census (every instanced draw's index count and instance count, so verts per frame and draw counts are counted, not
// assumed); the q3 anchor (arm q3, and q3z last in the cycle) brackets every cycle and deltas are paired against that
// cycle's anchor. Ported from the render-perf measurement's cycle2.mjs (report.md, 2026-11-10); the corrections the
// code-level plan asked for: the fixtures come from --root (a repository root, not the script's directory), the
// census counts every instanced draw (mixed LOD buckets, one-instance draws) with explicit index-count -> vertex maps,
// the render policy (scene.setRenderOptimization) is reset COMPLETELY before each arm, and the browser lock is
// taken per cell and waited for, never broken.
//
//   node cycle.mjs --base http://localhost:8182 --root REPO --out DIR [--counts 2000] [--cameras whole,fit,dense,follow]
//        [--colour appearance|family] [--viewport 1400x900@1] [--arms q3,lod,...] [--rounds 6] [--dur 5000] [--warm 10000]
//        [--settle 1500] [--every 4] [--name builder-render] [--live]
//
// arms: q3 / q3z / q2 / q1 (quality, reference policy: lod "quality", decoded off, barbels "body": the page as on main),
// q3ns q3nb q3nf (hidden passes), vertex-only scissored arms (q3vall, ...), the d-arms (per-draw GPU scopes), and the
// policy arms (q3 quality, the policy set explicitly; on a build without scene.setRenderOptimization they are refused):
//   lod        screen-size body buckets only
//   cache      decoded appearance constants only
//   barb       gated barbels only
//   lodCache   lod + cache
//   all        lod + cache + gated barbels (the production default)
//   allns / allnb / allnf   `all` with the shadow / barbel / every fish draw hidden
//   allvall    `all` with every fish draw through a 1 x 1 scissor (vertex-only)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { acquire } from "./lock.mjs";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : (i >= 0 ? true : def); }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = String(arg("base", "http://localhost:8182")).replace(/\/$/, "");
const ROOT = path.resolve(String(arg("root", ".")));
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "render_cycle_" + Date.now()))));
const COUNTS = String(arg("counts", "2000")).split(",").map(Number);
const CAMERAS = String(arg("cameras", "whole,fit")).split(",");
const EVERY = Number(arg("every", 4));
const DUR = Number(arg("dur", 5000)), WARM = Number(arg("warm", 10000)), ROUNDS = Number(arg("rounds", 6)), SETTLE = Number(arg("settle", 1500));
const NAME = String(arg("name", "builder-render"));
const LIVE = !!arg("live", false);   /* --live: the world running one step a frame (the static cells are paused at tick 0) */
const COLOUR = String(arg("colour", "appearance"));
const ARMS = String(arg("arms", "q3,q2,q1,q3ns,q3nb,q3nf,q3z")).split(",");
const VIEWPORT = (() => { const m = /^(\d+)x(\d+)(?:@([\d.]+))?$/.exec(String(arg("viewport", "1400x900@1")));
  if (!m) throw new Error("--viewport WxH[@dpr]"); return { width: +m[1], height: +m[2], dpr: m[3] ? +m[3] : 1 }; })();
const CASES = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/ocean_render_cases.json"), "utf8"));
const { chromium } = require(PW);
fs.mkdirSync(OUT, { recursive: true });

/* the render policies (scene.setRenderOptimization): the reference is the page as on main */
const REF = { lod: "quality", decoded: false, barbels: "body" };
const POL = {
  ref: REF,
  lod: { lod: "screen", decoded: false, barbels: "body" },
  cache: { lod: "quality", decoded: true, barbels: "body" },
  barb: { lod: "quality", decoded: false, barbels: "gated" },
  lodCache: { lod: "screen", decoded: true, barbels: "body" },
  all: { lod: "screen", decoded: true, barbels: "gated" }
};
const ALLF = ["fishBody", "barbels", "fishShadow", "predBody", "predShadow"];
const ARM = {
  q3: { q: 3, gpu: "frame" }, q2: { q: 2, gpu: "frame" }, q1: { q: 1, gpu: "frame" },
  q3ns: { q: 3, hide: ["fishShadow", "predShadow"], gpu: "frame" },
  q3nb: { q: 3, hide: ["barbels"], gpu: "frame" },
  q3nf: { q: 3, hide: ALLF, gpu: "frame" },
  q2ns: { q: 2, hide: ["fishShadow", "predShadow"], gpu: "frame" },
  q3d: { q: 3, gpu: "draws" }, q2d: { q: 2, gpu: "draws" }, q1d: { q: 1, gpu: "draws" },
  q3z: { q: 3, gpu: "frame" },
  q3vall: { q: 3, sc: ALLF, gpu: "frame" }, q3vbody: { q: 3, sc: ["fishBody", "predBody"], gpu: "frame" },
  q3vshad: { q: 3, sc: ["fishShadow", "predShadow"], gpu: "frame" }, q3vfloor: { q: 3, sc: ["floor"], gpu: "frame" },
  q3vbarb: { q: 3, sc: ["barbels"], gpu: "frame" }, q2vall: { q: 2, sc: ALLF, gpu: "frame" }, q1vall: { q: 1, sc: ALLF, gpu: "frame" },
  q3dv: { q: 3, sc: ALLF, gpu: "draws" },
  lod: { q: 3, pol: "lod", gpu: "frame" }, cache: { q: 3, pol: "cache", gpu: "frame" }, barb: { q: 3, pol: "barb", gpu: "frame" },
  lodCache: { q: 3, pol: "lodCache", gpu: "frame" }, all: { q: 3, pol: "all", gpu: "frame" },
  allns: { q: 3, pol: "all", hide: ["fishShadow", "predShadow"], gpu: "frame" },
  allnb: { q: 3, pol: "all", hide: ["barbels"], gpu: "frame" },
  allnf: { q: 3, pol: "all", hide: ALLF, gpu: "frame" },
  allvall: { q: 3, pol: "all", sc: ALLF, gpu: "frame" },
  lodCachenb: { q: 3, pol: "lodCache", hide: ["barbels"], gpu: "frame" },
  alld: { q: 3, pol: "all", gpu: "draws" }, lodd: { q: 3, pol: "lod", gpu: "draws" },
  allq2: { q: 2, pol: "all", gpu: "frame" }
};
for (const a of Object.values(ARM)) { a.hide = a.hide || []; a.sc = a.sc || []; }
for (const a of ARMS) if (!ARM[a]) throw new Error("unknown arm " + a);

/* init script: capture the watched meshes by label; hide / scissor chosen labels; GL draw census on demand */
const INIT = () => {
  const W = (window.__probe = { meshes: {}, hide: [], sc: [], census: null, renders: 0 });
  let perf;
  Object.defineProperty(window, "EvoOceanPerf", {
    configurable: true, get() { return perf; },
    set(v) {
      perf = v;
      const wrapProfiler = (P) => {
        if (!P || P.__wrapped) return P;
        const w0 = P.watch, b0 = P.beginSubmission;
        if (w0) P.watch = function (obj, label) {
          (W.meshes[label] = W.meshes[label] || []).push(obj);
          const r = w0.apply(this, arguments);
          const ob = obj.onBeforeRender, oa = obj.onAfterRender;   /* the profiler's scope chain is inside this one */
          obj.onBeforeRender = function (renderer) { if (W.sc.length && W.sc.indexOf(label) >= 0) { const gl = renderer.getContext(); gl.enable(gl.SCISSOR_TEST); gl.scissor(0, 0, 1, 1); } return ob.apply(this, arguments); };
          obj.onAfterRender = function (renderer) { const x = oa.apply(this, arguments); if (W.sc.length && W.sc.indexOf(label) >= 0) { const gl = renderer.getContext(); gl.disable(gl.SCISSOR_TEST); } return x; };
          return r;
        };
        if (b0) P.beginSubmission = function () {
          W.renders++;
          /* the hidden labels' meshes: only the ones the page itself left visible this frame stay so after the toggle */
          for (const l of W.hide) for (const m of (W.meshes[l] || [])) m.visible = false;
          return b0.apply(this, arguments);
        };
        P.__wrapped = true;
        return P;
      };
      const c0 = v.create;
      v.forPage = function (on) { return on ? wrapProfiler(c0.call(v)) : v.disabled; };
      v.create = function () { return wrapProfiler(c0.apply(this, arguments)); };
    }
  });
  const proto = WebGL2RenderingContext.prototype;
  const tally = (kind, n, inst) => { const c = W.census; if (!c) return; const k = kind + ":" + n + "x" + inst; c.t[k] = (c.t[k] || 0) + 1; c.calls++; };
  const dei = proto.drawElementsInstanced, dai = proto.drawArraysInstanced, de = proto.drawElements, da = proto.drawArrays;
  proto.drawElementsInstanced = function (m, n, t, o, inst) { tally("E", n, inst); return dei.apply(this, arguments); };
  proto.drawArraysInstanced = function (m, f, n, inst) { tally("A", n, inst); return dai.apply(this, arguments); };
  proto.drawElements = function (m, n, t, o) { tally("E", n, 1); return de.apply(this, arguments); };
  proto.drawArrays = function (m, f, n) { tally("A", n, 1); return da.apply(this, arguments); };
};

const LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"];
async function launch(opts) {
  const ctx = await chromium.launchPersistentContext("", {
    executablePath: BRAVE, headless: true, viewport: opts.viewport, deviceScaleFactor: opts.dpr, reducedMotion: "no-preference", args: LAUNCH_ARGS });
  await ctx.addInitScript(INIT);
  const page = ctx.pages()[0] || await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  page.on("requestfailed", (r) => errors.push("requestfailed: " + r.url()));
  page.on("response", (r) => { if (r.status() >= 400) errors.push("http " + r.status() + ": " + r.url()); });
  return { ctx, page, errors };
}
function benchUrl(c) {
  const q = new URLSearchParams({ renderBench: "1", guide: "0", intro: "0", seed: String(c.worldSeed), pop: String(c.population),
    w: String(c.world[0]), h: String(c.world[1]), depth: String(c.world[2]), speed: String(c.speed), colour: c.colourMode || "appearance",
    walls: c.config.walls ? "1" : "0", cfg: JSON.stringify(Object.assign({}, c.config, { walls: undefined })) });
  return BASE + "/ocean.html?" + q.toString();
}
async function ready(page) {
  await page.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && window.EvoOcean.bench, null, { timeout: 120000, polling: 200 });
  await page.evaluate(() => EvoOcean.bench.frames(10));
}
function caseFor(pop) { return Object.assign({}, CASES.benchmark, { population: pop, colourMode: COLOUR, config: Object.assign({}, CASES.benchmark.config) }); }

const result = { started: new Date().toISOString(), viewport: VIEWPORT, colour: COLOUR, dur: DUR, warm: WARM, settle: SETTLE, rounds: ROUNDS, arms: ARMS, base: BASE, policies: POL, cells: {}, errors: [] };
(async () => {
  for (const pop of COUNTS) for (const cam of CAMERAS) {
    const key = `${pop}_${cam}`, cell = { fish: pop, camera: cam, obs: [] };
    result.cells[key] = cell;
    const release = await acquire(`${NAME} render perf ${key} ${COLOUR} ${VIEWPORT.width}x${VIEWPORT.height}@${VIEWPORT.dpr}`);
    let L = null;
    try {
      L = await launch({ viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, dpr: VIEWPORT.dpr });
      const c = caseFor(pop);
      await L.page.goto(benchUrl(c));
      await ready(L.page);
      const prep = await L.page.evaluate(async ([cd, camKind]) => {
        const p = await EvoOcean.bench.prepare(Object.assign({}, cd, { camera: camKind === "fit" ? "whole" : camKind }));
        if (camKind === "fit") { EvoOcean.scene.resetView(false); await EvoOcean.bench.wait(500); p.camera = { kind: "fit", view: EvoOcean.scene.view() }; }
        return p;
      }, [c, cam]);
      const info = await L.page.evaluate(() => ({ ctx: EvoOcean.scene.contextInfo(), ua: navigator.userAgent, hw: navigator.hardwareConcurrency,
                                                   policy: typeof EvoOcean.scene.setRenderOptimization === "function",
                                                   meshes: Object.fromEntries(Object.entries(window.__probe.meshes).map(([k, v]) => [k, v.length])) }));
      if (!result.env) result.env = { renderer: info.ctx.renderer, timerQuery: info.ctx.timerQuery, ua: info.ua, hw: info.hw, meshLabels: info.meshes, policyApi: info.policy };
      console.log(`== ${key} ${COLOUR} (cycles): n ${prep.n}, colour ${prep.colourMode}, buffer ${info.ctx.drawingBuffer.join("x")} dpr ${info.ctx.pixelRatio}; policy api ${info.policy}; watched ${JSON.stringify(info.meshes)}`);
      if (LIVE) await L.page.evaluate(() => EvoOcean.bench.live(true));   /* one step a frame from here: births and deaths, decoded and uploaded as they come */
      await L.page.evaluate((ms) => EvoOcean.bench.wait(ms), WARM);
      for (let round = 0; round < ROUNDS; round++) {
        const order = round % 2 ? ARMS.slice().reverse() : ARMS.slice();
        for (const arm of order) {
          const A = ARM[arm], pol = A.pol ? POL[A.pol] : (info.policy ? REF : null);
          const r = await L.page.evaluate(async ([A, pol, ms, settle, EVERY]) => {
            const S = EvoOcean.scene, W = window.__probe;
            W.hide = A.hide.slice(); W.sc = A.sc.slice();
            let polRes = null;
            if (pol) polRes = await S.setRenderOptimization(pol);   /* the whole policy, every arm (a promise: shader changes resolve once compiled) */
            S.setQuality(A.q);
            await EvoOcean.bench.wait(settle);
            const rp = EvoOcean.bench.rafProbe(ms), r0 = W.renders;
            const cap = await EvoOcean.bench.capture({ durationMs: ms, cpu: true, gpu: A.gpu, sampleEvery: EVERY });
            const raf = await rp, renders = W.renders - r0;
            W.census = { t: {}, calls: 0 }; const rc0 = W.renders;
            await EvoOcean.bench.wait(1000);
            const census = { tally: W.census.t, calls: W.census.calls, frames: W.renders - rc0 }; W.census = null;
            const ci = S.contextInfo();
            return { raf, cap, renders, census, polRes: polRes && polRes.ok !== undefined ? polRes : null,
                     opt: S.renderOptimization ? S.renderOptimization() : null,
                     state: { quality: S.quality(), dpr: devicePixelRatio, pixelRatio: ci.pixelRatio, drawingBuffer: ci.drawingBuffer,
                              polish: S.polish(), appearance: S.appearance(), n: EvoOcean.state().n, hide: A.hide, sc: A.sc, colour: EvoOcean.bench ? null : null } };
          }, [A, pol, DUR, SETTLE, EVERY]);
          const sm = r.cap.summary, g = sm.gpu.labels;
          const rec = { arm, round, state: r.state, raf: r.raf, summary: sm, renders: r.renders, census: r.census, opt: r.opt, order };
          cell.obs.push(rec);
          const f = g.frame ? g.frame.scopes : null;
          const dr = A.gpu === "draws" ? Object.entries(g).map(([k, v]) => `${k} ${v.perFrame.p50.toFixed(2)}`).join(" ") : "";
          console.log(`  ${key} ${arm.padEnd(8)} r${round}: rAF ${r.raf.rafFps.toFixed(1)} fps, cpu p50 ${sm.spans.frameCpu.p50.toFixed(2)}` +
                      (f ? `, gpu p50 ${f.p50.toFixed(2)} p95 ${f.p95.toFixed(2)} (valid ${(100 * sm.gpu.validFraction).toFixed(0)}%)` : ", draws: " + dr + ` (valid ${(100 * sm.gpu.validFraction).toFixed(0)}%)`) +
                      `; lod ${r.state.appearance.lod} verts ${r.state.appearance.verts} barbels ${r.state.appearance.barbels}; buf ${r.state.drawingBuffer.join("x")} census ${r.census.calls}/${r.census.frames}f`);
          fs.writeFileSync(path.join(OUT, `result.json`), JSON.stringify(result));
        }
      }
      if (L.errors.length) { result.errors.push({ key, errors: L.errors.slice(0, 8) }); console.log("  page errors:", L.errors.slice(0, 3)); }
    } finally {
      if (L) { try { await L.ctx.close(); } catch (e) { /* closed */ } }
      release();
    }
  }
  result.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify(result));
  console.log("done; output in " + OUT);
  process.exit(0);
})().catch((e) => { console.log("THREW " + (e && e.stack || e)); result.threw = String(e && e.stack || e); fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify(result)); process.exit(1); });
