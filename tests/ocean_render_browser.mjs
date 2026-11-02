// tests/ocean_render_browser.mjs: the Ocean's render checks and benchmark on the real page, in headless Brave.
//
//   node tests/ocean_render_browser.mjs --base http://localhost:8152 [--out DIR]
//        [--parts correctness,noperf,faults,timer,beam,iframe,perf] [--counts 500,1500,2500]
//        [--dur 15000] [--warm 10000] [--rounds 2] [--headed]
//        [--cameras whole,dense,follow] [--colours appearance,family,brain]   (perf; default whole, appearance)
//   env: PLAYWRIGHT  the playwright module (default C:/Users/harit/gemini_bridge/node_modules/playwright)
//        BRAVE_EXE   the browser (default C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe)
//
// Serve web/ (or a built site) with the production isolation headers first
// (wasm/serve.py), with the matching evo_ocean.wasm. Every part is an
// independent run: a fresh browser and temporary profile, one at a time.
//   correctness  the production checks (appearancePathCheck: the fixed
//                fixture through the vertex shader in both colour modes and
//                the fragment shader), the attribute-fed reference
//                (appearanceParity), the live gene texture (appearance-,
//                family- and brain-colour frames), and the profiler's
//                gene-upload counters against intercepted WebGL uploads; the
//                bench itself (a case's tick restored, its colour modes not
//                stored, a Restart's link without renderBench / perf)
//   noperf       web/ocean_perf.js blocked (a normal link, ?renderBench=1):
//                the page starts and draws with no other error
//   faults       each planted fault must be caught (and compile and run):
//                the texture lookup (row0, nextRow, slot) and vPart.w in both
//                vertex reports; red / blue unpacking and the colour-mode
//                branch in the fragment report; NaN / +-Inf in every captured
//                component; on the live texture, a wrong slot, a pending
//                upload the probe would perform, and a held-back upload under
//                a new world
//   timer        GPU timing on the real context: frame and draw scopes, a lost
//                and restored context (WEBGL_lose_context), and the extension
//                hidden (absent timer); none may raise an error or a 0 ms sample
//   beam         the flashlight's full-strength floor (caustics included) is
//                the same in Realistic and Clear water (deployed-audit PR #30-31,
//                finding 5), and its caustics are there (they move with the clock)
//   iframe       the page at 890 x 453 in a non-isolated parent: colours,
//                select / follow, a restart, Turbo there and back, the live
//                texture check
//   perf         per fish count: the benchmark case (paused at tick 0), A/B
//                interleaved profiler modes (off: rAF only; frame; spans;
//                spans + GPU frame queries every 6th), a draw-scope
//                diagnostic, a live one-step-a-frame capture
// Writes manifest.json, report.json, parity.json, errors.json and per-capture
// frames / gpu CSVs into --out; exits 1 on any failed check.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : (i >= 0 ? true : def); }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = String(arg("base", "http://localhost:8152")).replace(/\/$/, "");
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "ocean_render_" + Date.now()))));
const PARTS = String(arg("parts", "correctness,noperf,faults,timer,beam,iframe,perf")).split(",");
const COUNTS = String(arg("counts", "500,1500,2500")).split(",").map(Number);
const DUR = Number(arg("dur", 15000)), WARM = Number(arg("warm", 10000)), ROUNDS = Number(arg("rounds", 2));
const CAMERAS = String(arg("cameras", "whole")).split(","), COLOURS = String(arg("colours", "appearance")).split(",");
const HEADED = !!arg("headed", false);
const CASES = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/ocean_render_cases.json"), "utf8"));
const { chromium } = require(PW);
fs.mkdirSync(OUT, { recursive: true });

let fails = 0;
const report = { started: new Date().toISOString(), parts: {}, checks: [] };
const parity = {}, errorsAll = {};
function check(name, cond, info) {
  report.checks.push({ name, ok: !!cond });
  console.log((cond ? "  ok   " : "  FAIL ") + name + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 600) : ""));
  if (!cond) fails++;
}
const LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"];
async function launch(label, opts = {}) {
  /* "": a temporary profile, made and removed by Playwright */
  const ctx = await chromium.launchPersistentContext("", {
    executablePath: BRAVE, headless: !HEADED, viewport: opts.viewport || { width: 1920, height: 1080 }, deviceScaleFactor: 1,
    reducedMotion: "no-preference", args: LAUNCH_ARGS
  });
  if (opts.init) await ctx.addInitScript(opts.init);
  const page = ctx.pages()[0] || await ctx.newPage();
  const errors = (errorsAll[label] = []);
  page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text() + (m.location() && m.location().url ? " @ " + m.location().url : "")); });
  page.on("requestfailed", (r) => errors.push("requestfailed: " + r.url() + " " + (r.failure() && r.failure().errorText)));
  page.on("response", (r) => { if (r.status() >= 400) errors.push("http " + r.status() + ": " + r.url()); });
  return { ctx, page, errors, browserVersion: ctx.browser() ? ctx.browser().version() : null };
}
function benchUrl(c, extra = {}) {
  const q = new URLSearchParams(Object.assign({ renderBench: "1", guide: "0", intro: "0", seed: String(c.worldSeed), pop: String(c.population),
    w: String(c.world[0]), h: String(c.world[1]), depth: String(c.world[2]), speed: String(c.speed), colour: c.colourMode || "appearance",
    walls: c.config.walls ? "1" : "0", cfg: JSON.stringify(Object.assign({}, c.config, { walls: undefined })) }, extra));
  return BASE + "/ocean.html?" + q.toString();
}
async function ready(page, bench) {
  await page.waitForFunction((b) => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && (!b || window.EvoOcean.bench),
                             bench, { timeout: 90000, polling: 200 });
  if (bench) await page.evaluate(() => EvoOcean.bench.frames(10));
  else await page.waitForFunction(() => EvoOcean.state() && EvoOcean.state().frame > 20, null, { timeout: 60000 });
}
function save(name, text) { fs.writeFileSync(path.join(OUT, name), text); }
function sha(file) { try { return crypto.createHash("sha256").update(fs.readFileSync(path.join(ROOT, file))).digest("hex"); } catch (e) { return null; } }
function caseFor(pop, over = {}) { return Object.assign({}, CASES.benchmark, { population: pop, config: Object.assign({}, CASES.benchmark.config) }, over); }
function pathSummary(r) {
  if (!r || r.error) return r;
  const v = (x) => x && (x.error ? { error: x.error } : { ok: x.ok, fish: x.fish, components: x.components, allParts: x.allParts, barbelFish: x.barbelFish,
    templates: Object.fromEntries(Object.entries(x.templates || {}).map(([k, t]) => [k, { pass: t.pass, world: +t.maxWorld.toExponential(2), mat: +t.maxMat.toExponential(2),
      mar: +t.maxMar.toExponential(2), decode: +t.maxDecode.toExponential(2), nan: t.nan, partBad: t.partBad, worst: t.pass ? undefined : t.worst }])),
    sweep: x.sweep ? { tried: x.sweep.tried, killed: x.sweep.killed, baselinePass: x.sweep.baselinePass, survivors: x.sweep.survivors } : undefined });
  const f = r.fragment && (r.fragment.error ? { error: r.fragment.error } : { ok: r.fragment.ok, cases: r.fragment.cases, failures: r.fragment.failures,
    maxErr: r.fragment.maxErr, nonFinite: r.fragment.nonFinite, modes: r.fragment.modes, worst: r.fragment.worst });
  return { ok: r.ok, error: r.error, fixture: r.fixture, fish: r.fish, appearance: v(r.appearance), recolour: v(r.recolour), fragment: f };
}
function texSummary(r) {
  if (!r) return r;
  return { ok: r.ok, error: r.error, failures: r.failures, fish: r.fish, worldEpoch: r.worldEpoch, tick: r.tick, extraUploads: r.extraUploads,
           rawGenes: r.rawGenes, intrinsic: r.intrinsic && Object.assign({}, r.intrinsic, { draws: undefined, ids: undefined, charted: r.intrinsic.draws }),
           texture: r.texture, mutate: r.mutate, pendingUpload: r.pendingUpload };
}

/* the upload interceptor: texImage2D / texSubImage2D / texStorage2D calls whose
 * pixels are the gene texture's staging array (window.__geneBuf), while __up.on */
const INTERCEPT = () => {
  window.__up = { on: false, n: 0, bytes: 0, other: 0 };
  const P = WebGL2RenderingContext.prototype;
  for (const name of ["texImage2D", "texSubImage2D"]) {
    const f = P[name];
    P[name] = function () {
      const a = arguments, u = window.__up;
      if (u && u.on) {
        const px = a[a.length - 1];
        if (px && px.buffer && window.__geneBuf && px.buffer === window.__geneBuf) {
          const w = name === "texImage2D" ? a[3] : a[4], h = name === "texImage2D" ? a[4] : a[5];
          u.n++; u.bytes += w * h * 16;
        } else u.other++;
      }
      return f.apply(this, a);
    };
  }
};

async function manifestOf(page, label, extra = {}) {
  const info = await page.evaluate(() => EvoOcean.bench ? EvoOcean.bench.info() : null);
  return Object.assign({ label, base: BASE, launchArgs: LAUNCH_ARGS, headless: !HEADED, playwright: require(PW + "/package.json").version,
    hashes: { "web/evo_ocean.wasm": sha("web/evo_ocean.wasm"), "web/ocean_scene.js": sha("web/ocean_scene.js"), "web/ocean_perf.js": sha("web/ocean_perf.js"),
              "web/ocean.js": sha("web/ocean.js"), "web/vendor/three.bundle.min.js": sha("web/vendor/three.bundle.min.js") },
    host: { platform: process.platform, cpus: os.cpus().length, cpuModel: os.cpus()[0] && os.cpus()[0].model, totalMemGB: Math.round(os.totalmem() / 1e9) },
    info }, extra);
}

/* ---------------- correctness ---------------- */
async function partCorrectness() {
  console.log("== correctness (2,500 fish, paused at tick 0)");
  const c = caseFor(2500);
  const L = await launch("correctness", { init: INTERCEPT });
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  const prep = await L.page.evaluate((cd) => EvoOcean.bench.prepare(cd), Object.assign({}, c, { camera: "whole", colourMode: "appearance" }));
  report.parts.correctness = { manifest: await manifestOf(L.page, "correctness", { browserVersion: L.browserVersion, case: prep }) };
  const ctx = report.parts.correctness.manifest.info.context;
  console.log("  gpu " + ctx.renderer + "; drawing buffer " + ctx.drawingBuffer.join(" x ") + "; timer " + ctx.timerQuery);
  check("the bench case: 2,500 fish, appearance, detail 3, paused at tick 0, Hold 60 fps off",
        prep.n === 2500 && prep.colourMode === "appearance" && prep.quality === 3 && prep.paused && prep.tick === 0 && prep.governor === false && prep.appearance.drawing,
        { n: prep.n, colour: prep.colourMode, q: prep.quality, paused: prep.paused, tick: prep.tick, gov: prep.governor });
  check("the drawing buffer is 1920 x 1080, not software rendering", ctx.drawingBuffer[0] === 1920 && ctx.drawingBuffer[1] === 1080 && !/swiftshader|llvmpipe|software/i.test(ctx.renderer), ctx.renderer);

  const pathRes = await L.page.evaluate(() => EvoOcean.scene.appearancePathCheck());
  parity.path = pathSummary(pathRes);
  check("production programs (fixture: 65 fish, vertex in both colour modes, fragment)", pathRes.ok === true && !pathRes.error, parity.path);
  check("  vertex, appearance mode: 51 components, every part, barbels", pathRes.appearance.ok && pathRes.appearance.components === 51 && pathRes.appearance.allParts);
  check("  vertex, recolour mode: 11 components, nonzero packed colours reach vPart.w", pathRes.recolour.ok && pathRes.recolour.components === 11);
  check("  fragment: recolour (Family + Brain palettes, parts 0..7) and skin within .003",
        pathRes.fragment.ok && pathRes.fragment.modes.recolour.cases === 240 && pathRes.fragment.modes.appearance.cases === 9, pathRes.fragment.modes);

  const ref = await L.page.evaluate(() => {
    const s = EvoOcean.bench.snapshotCopy(), rows = [], lams = [];
    for (let i = 0; i < 64; i++) {
      rows.push(Array.from(s.app.subarray(63 * i, 63 * i + 63)));
      lams.push(EvoAppearance.lambdaOf(s.body[2 * i], s.body[2 * i + 1]));
    }
    return EvoOcean.scene.appearanceParity(rows, lams);
  });
  parity.attributeReference = ref;
  check("attribute-fed reference chart (64 live fish): p99.9 <= .002, finite", ref && !ref.error && ref.p999 <= 0.002 && Number.isFinite(ref.maxErr), ref);

  /* each mode as the page really is in it (post-merge audit 43fedc0, finding 1: the
   * case once named a mode the page never took): the controller's mode, the View
   * menu's pressed button, state().colourBrain, the scene's skin, the case's and
   * info()'s report; then the texture in that mode */
  for (const mode of ["family", "brain", "appearance"]) {
    const prepM = await L.page.evaluate(([cd, m]) => EvoOcean.bench.prepare(Object.assign({}, cd, { colourMode: m, camera: "whole", settleMs: 300 })), [c, mode]);
    const st = await L.page.evaluate(() => ({ mode: EvoOcean.state().colourMode, brain: EvoOcean.state().colourBrain, skin: EvoOcean.scene.appearance().skin,
      pressed: [...document.querySelectorAll("#colourMode button[aria-pressed='true']")].map((b) => b.dataset.c).join(), info: EvoOcean.bench.info().colourMode }));
    check("bench in " + mode + " colours: the page's mode, its pressed button, colourBrain " + (mode === "brain") + ", the scene's skin " + (mode === "appearance") + ", the case's and info()'s report",
          st.mode === mode && st.pressed === mode && st.brain === (mode === "brain") && st.skin === (mode === "appearance") && st.info === mode && prepM.colourMode === mode,
          Object.assign({ case: prepM.colourMode }, st));
    const t = await L.page.evaluate(() => EvoOcean.bench.textureParity());
    parity["texture_" + mode] = texSummary(t);
    check("live gene texture, " + mode + " colours: raw genes bit-exact, charts p99.9 <= .002, no probe upload",
          t.ok === true && t.rawGenes.mismatches === 0 && t.rawGenes.paddingMismatches === 0 && t.extraUploads === 0, texSummary(t));
  }
  /* bench.info().dashboardOpen against the charts' own state (finding 12): closed, open, a capture with them open, closed */
  const dsh = await L.page.evaluate(async () => {
    const seen = [], look = () => seen.push([EvoOcean.bench.info().dashboardOpen, EvoOceanDash.isOpen()]);
    look(); EvoOceanDash.open(); look();
    await EvoOcean.bench.capture({ durationMs: 300, cpu: true, gpu: "off", drainMs: 0, raw: true }); look();
    EvoOceanDash.close(); look();
    return seen;
  });
  check("bench.info().dashboardOpen is EvoOceanDash.isOpen(): closed, open, after a capture with them open, closed",
        dsh.map(String).join(" ") === "false,false true,true true,true false,false", dsh);
  const t0 = parity.texture_appearance;
  check("  charted slots include both sides of 31/32 and 2047/2048", t0 && [31, 32, 2047, 2048].every((d) => t0.intrinsic.charted.includes(d)), t0 && t0.intrinsic.charted);
  check("  the texture: 512 x 128 RGBA float, nearest, no mipmaps, capacity 4,096", t0 && t0.texture.width === 512 && t0.texture.height === 128 &&
        t0.texture.type === 1015 && t0.texture.format === 1023 && t0.texture.minFilter === 1003 && t0.texture.magFilter === 1003 && !t0.texture.mipmaps && t0.texture.capacity === 4096, t0 && t0.texture);

  /* the profiler's gene-upload counters against the WebGL calls themselves (outside any timed run) */
  const up = await L.page.evaluate(async () => {
    window.__geneBuf = EvoOcean.scene.geneTexture().data.buffer;
    const io0 = EvoOcean.scene.geneTexture();
    window.__up.n = 0; window.__up.bytes = 0; window.__up.other = 0; window.__up.on = true;
    const cap = await EvoOcean.bench.capture({ durationMs: 2000, cpu: true, gpu: "off", drainMs: 0, raw: true });
    window.__up.on = false;
    const io1 = EvoOcean.scene.geneTexture(), NK = cap.schema.counters.length, K = EvoOceanPerf.K;
    let n = 0, bytes = 0, frames = 0, sub = 0;
    for (let f = 0; f < cap.frames; f++) {
      const a = cap.cnt[f * NK + K.geneUploads], b = cap.cnt[f * NK + K.geneUploadBytes];
      if (a === a) n += a; if (b === b) bytes += b;
      frames++; if (cap.cnt[f * NK + K.submitted] === 1) sub++;
    }
    return { profiler: { uploads: n, bytes: bytes, frames: frames, submitted: sub }, intercepted: { calls: window.__up.n, bytes: window.__up.bytes },
             sceneIO: { uploads: io1.uploads - io0.uploads, bytes: io1.bytes - io0.bytes }, perFrameBytes: io1.data.byteLength };
  });
  report.parts.correctness.uploads = up;
  check("gene-upload counters == intercepted WebGL uploads (calls and bytes)",
        up.profiler.uploads > 0 && up.profiler.uploads === up.intercepted.calls && up.profiler.bytes === up.intercepted.bytes && up.sceneIO.uploads === up.intercepted.calls, up);
  check("  PR1 baseline: one full 1 MiB gene upload a submitted frame", up.perFrameBytes === 1048576 && up.profiler.uploads === up.profiler.submitted, up.profiler);

  /* the bench itself: a case's tick restored after stepping; the colour modes it used not stored; a Restart's link clean */
  const b = await L.page.evaluate(async (cd) => {
    const B = EvoOcean.bench, at = () => ({ tick: EvoOcean.state().frame, n: EvoOcean.state().n, epoch: EvoOcean.state().worldEpoch });
    const a0 = at();
    await B.stepToTick(60);
    const a1 = at();
    await B.prepare(Object.assign({}, cd, { camera: "whole", colourMode: "appearance", settleMs: 200 }));
    const a2 = at();
    const stored = localStorage.getItem("evo_boids.colourBy");
    document.getElementById("restart").click();
    if (!document.getElementById("startask").hidden) document.getElementById("startconfirm").click();   /* (asked: a run with something to lose) */
    await B.frames(5);
    const q = new URLSearchParams(location.search);
    return { a0, a1, a2, stored, link: { renderBench: q.get("renderBench"), perf: q.get("perf"), seed: q.get("seed") } };
  }, c);
  report.parts.correctness.bench = b;
  check("prepare() of the same case after stepping to tick 60: back at tick 0, a new epoch, 2,500 fish",
        b.a1.tick === 60 && b.a2.tick === 0 && b.a2.epoch === b.a1.epoch + 1 && b.a2.n === 2500, b);
  check("the benchmark's colour modes (Appearance, Family, Brain) were not stored as the visitor's", b.stored === null, b.stored);
  check("a Restart's setup link has no renderBench / perf", b.link.renderBench === null && b.link.perf === null && b.link.seed === "42", b.link);
  check("no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- the page without web/ocean_perf.js ---------------- */
/* ocean_perf.js blocked (a route abort): the page and the scene fall back to
 * profilers that record nothing; ?renderBench=1 is then off */
async function partNoPerf() {
  console.log("== the page without ocean_perf.js (blocked)");
  for (const bench of [false, true]) {
    const label = "noperf" + (bench ? "-bench" : "");
    const L = await launch(label);
    let blocked = 0;
    await L.ctx.route(/ocean_perf(\.[0-9a-f]+)?\.js(\?.*)?$/, (r) => { blocked++; return r.abort(); });
    const url = bench ? benchUrl(caseFor(1500)) : BASE + "/ocean.html?guide=0&intro=0&seed=7";
    await L.page.goto(url);
    /* running, or the splash saying why not */
    await L.page.waitForFunction(() => (window.EvoApp && EvoApp.ready === true && EvoOcean.state() && EvoOcean.state().frame > 30) ||
                                       /could not start/.test(document.body.textContent), null, { timeout: 90000 });
    const r = await L.page.evaluate(async () => {
      if (!(window.EvoApp && EvoApp.ready === true)) return { started: false, splash: (document.getElementById("splashstate") || {}).textContent || "", app: {} };
      const f0 = EvoOcean.state().frame;
      await new Promise((res) => setTimeout(res, 1000));
      return { started: true, perfFile: !!window.EvoOceanPerf, perf: !!EvoOcean.perf, bench: !!EvoOcean.bench, paused: EvoOcean.state().paused,
               advancing: EvoOcean.state().frame > f0, app: EvoOcean.scene.appearance(), n: EvoOcean.state().n,
               splash: (document.getElementById("splashstate") || {}).textContent || "" };
    });
    /* the blocked script's own failure is expected; nothing else may fail */
    const other = L.errors.filter((e) => !/ocean_perf/.test(e));
    report.parts[label] = Object.assign({ blocked, errors: L.errors }, r);
    check((bench ? "?renderBench=1, " : "") + "ocean_perf.js blocked: the page starts, runs and draws the fish's bodies (no profiler, no bench)",
          r.started && blocked >= 1 && !r.perfFile && !r.perf && !r.bench && !r.paused && r.advancing && r.app.drawing && r.n > 0, r);
    check("  no other console / page / network error", other.length === 0, other.slice(0, 5));
    await L.ctx.close();
  }
}

/* ---------------- planted faults ---------------- */
async function partFaults() {
  console.log("== planted faults (each must compile, run, and fail)");
  const c = caseFor(2500);
  const L = await launch("faults");
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", colourMode: "appearance", settleMs: 300 })), c);
  const pf = (parity.faults = {});
  const clean = await L.page.evaluate(() => EvoOcean.scene.appearancePathCheck());
  check("unmutated first: the production checks pass", clean.ok === true, pathSummary(clean));
  for (const m of ["row0", "nextRow", "slot", "partW"]) {
    const r = await L.page.evaluate((mm) => EvoOcean.scene.appearancePathCheck(null, null, { mutate: mm }), m);
    pf["vertex_" + m] = { appearance: r.appearance.ok, recolour: r.recolour.ok, error: r.error,
                          worst: (r.appearance.templates && r.appearance.templates.medium.worst) || r.appearance.error };
    check("vertex mutation " + m + ": compiles, runs, fails both colour modes", !r.error && r.appearance.ok === false && r.recolour.ok === false && r.fragment.ok === true, pf["vertex_" + m]);
  }
  for (const m of ["swapRB", "branch"]) {
    const r = await L.page.evaluate((mm) => EvoOcean.scene.appearancePathCheck(null, null, { fsMutate: mm }), m);
    pf["fragment_" + m] = { fragment: r.fragment.ok, failures: r.fragment.failures, modes: r.fragment.modes, worst: r.fragment.worst, error: r.error };
    check("fragment mutation " + m + ": compiles, runs, fails", !r.error && r.fragment.ok === false && r.appearance.ok && r.recolour.ok, pf["fragment_" + m]);
  }
  const sw = await L.page.evaluate(() => EvoOcean.scene.appearancePathCheck(null, null, { injectSweep: true }));
  pf.injectSweep = { appearance: sw.appearance.sweep, recolour: sw.recolour.sweep };
  check("NaN / +Inf / -Inf in each of the 51 appearance-mode components (2 fish): every one fails, naming it",
        sw.appearance.sweep.tried === 51 * 3 * 2 && sw.appearance.sweep.killed === sw.appearance.sweep.tried && sw.appearance.sweep.baselinePass, sw.appearance.sweep);
  check("... and each of the 11 recolour-mode components", sw.recolour.sweep.tried === 11 * 3 * 2 && sw.recolour.sweep.killed === sw.recolour.sweep.tried && sw.recolour.sweep.baselinePass, sw.recolour.sweep);

  const good = await L.page.evaluate(() => EvoOcean.bench.textureParity());
  check("live texture, unplanted: passes", good.ok === true, texSummary(good));
  const slot = await L.page.evaluate(() => EvoOcean.bench.textureParity({ mutate: "slot" }));
  pf.texture_slot = texSummary(slot);
  check("live texture, a wrong slot in the probes: fails (raw mismatches)", !slot.error && slot.ok === false && slot.rawGenes.mismatches > 0, pf.texture_slot);
  const pend = await L.page.evaluate(() => EvoOcean.bench.textureParity({ pendingUpload: true }));
  pf.texture_pendingUpload = texSummary(pend);
  check("live texture, a production upload left pending: the probe's own upload fails it", !pend.error && pend.ok === false && pend.extraUploads >= 1, pf.texture_pendingUpload);
  /* held-back uploads under a new world (same count: no new texture): stale genes on the GPU */
  const stale = await L.page.evaluate(async (cd) => {
    EvoOcean.scene.testFaults.holdGeneUploads = true;
    await EvoOcean.bench.prepare(Object.assign({}, cd, { worldSeed: 43, camera: "whole", settleMs: 200 }));
    const held = await EvoOcean.bench.textureParity();
    EvoOcean.scene.testFaults.holdGeneUploads = false;
    await EvoOcean.bench.frames(3);
    const after = await EvoOcean.bench.textureParity();
    return { held, after, epoch: EvoOcean.state().worldEpoch };
  }, c);
  pf.texture_heldUpload = texSummary(stale.held);
  check("live texture, a new world's uploads held back: fails against the new world's genes", !stale.held.error && stale.held.ok === false && stale.held.rawGenes.mismatches > 0, pf.texture_heldUpload);
  check("  released, the next frame's upload passes (epoch " + stale.epoch + ")", stale.after.ok === true, texSummary(stale.after));
  check("no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- GPU timer on the real context ---------------- */
async function partTimer() {
  console.log("== GPU timing: scopes, context loss and restoration, the extension absent");
  const c = caseFor(1500);
  let L = await launch("timer");
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", settleMs: 500 })), c);
  const fr = await L.page.evaluate(() => EvoOcean.bench.capture({ durationMs: 4000, cpu: true, gpu: "frame", sampleEvery: 6 }));
  const g = fr.summary.gpu, hasTimer = g.supported;
  report.parts.timer = { frame: { gpu: g, fps: fr.summary.fps }, timerAvailable: hasTimer };
  if (!hasTimer) {
    /* a GPU / browser without EXT_disjoint_timer_query_webgl2: GPU timing is unavailable, which is a status, not a failure */
    console.log("  (this context has no EXT_disjoint_timer_query_webgl2: GPU timing unavailable; its quantitative checks are skipped)");
    check("timer unavailable: reported as such, no samples, the CPU capture fine",
          g.stats.ok === 0 && g.stats.unsupported > 0 && Object.keys(g.labels).length === 0 && fr.summary.fps > 0, g.stats);
  } else {
    check("frame scope: >= 90 % of attempted samples valid, ms > 0, the capture complete",
          g.validFraction >= 0.9 && g.labels.frame && g.labels.frame.scopes.p50 > 0 && g.complete,
          { valid: g.validFraction, stats: g.stats, p50: g.labels.frame && g.labels.frame.scopes.p50, complete: g.complete });
    const dr = await L.page.evaluate(() => EvoOcean.bench.capture({ durationMs: 3000, cpu: true, gpu: "draws", sampleEvery: 6 }));
    report.parts.timer.draws = { labels: Object.fromEntries(Object.entries(dr.summary.gpu.labels).map(([k, v]) => [k, v.perFrame])), stats: dr.summary.gpu.stats };
    check("draw scopes: fish bodies, shadows, floor, surface, food, snow labelled; >= 90 % valid",
          ["fishBody", "fishShadow", "floor", "food"].every((k) => dr.summary.gpu.labels[k]) && dr.summary.gpu.validFraction >= 0.9 && dr.summary.gpu.stats.refusedNest === 0,
          { labels: Object.keys(dr.summary.gpu.labels), valid: dr.summary.gpu.validFraction, stats: dr.summary.gpu.stats });
  }
  /* lose the context mid-capture, restore it, carry on */
  const lost = await L.page.evaluate(async () => {
    const gl = document.getElementById("tank").getContext("webgl2"), lc = gl.getExtension("WEBGL_lose_context");
    if (!lc) return { skipped: "no WEBGL_lose_context" };
    const p = EvoOcean.bench.capture({ durationMs: 7000, cpu: true, gpu: "frame", sampleEvery: 2, raw: true });
    await EvoOcean.bench.wait(2000); lc.loseContext();
    await EvoOcean.bench.wait(1500); lc.restoreContext();
    const cap = await p, s = EvoOceanPerf.summarize(cap), r = cap.gpu.results;
    const after = [];
    for (let i = 0; i < r.n; i++) if (r.status[i] === 0) after.push(r.generation[i]);
    const tex = await EvoOcean.bench.textureParity();
    return { stats: cap.gpu.stats, generation: cap.gpu.generation, validGens: Array.from(new Set(after)), lostFrames: s.lostFrames,
             fps: s.fps, supported: cap.gpu.supported, texture: { ok: tex.ok, error: tex.error, failures: tex.failures } };
  });
  report.parts.timer.contextLoss = lost;
  check("context lost and restored: no error" + (hasTimer ? ", a new generation, valid samples after" : "") + ", the page draws on",
        lost.skipped || (lost.lostFrames > 0 && lost.texture.ok &&
                         (!hasTimer || (lost.generation >= 1 && lost.supported && lost.validGens.includes(lost.generation)))), lost);
  check("no console / page / network errors (context loss)", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
  /* the timer extension absent */
  L = await launch("timer-absent", { init: () => {
    const f = WebGL2RenderingContext.prototype.getExtension;
    WebGL2RenderingContext.prototype.getExtension = function (n) { return n === "EXT_disjoint_timer_query_webgl2" ? null : f.call(this, n); };
  } });
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  const ab = await L.page.evaluate(() => EvoOcean.bench.capture({ durationMs: 2000, cpu: true, gpu: "frame" }));
  report.parts.timer.absent = { gpu: ab.summary.gpu, fps: ab.summary.fps };
  check("timer absent: GPU unsupported, every attempt a status, no samples, CPU capture fine",
        ab.summary.gpu.supported === false && ab.summary.gpu.stats.ok === 0 && ab.summary.gpu.stats.unsupported > 0 && Object.keys(ab.summary.gpu.labels).length === 0 && ab.summary.fps > 0,
        ab.summary.gpu.stats);
  check("no console / page / network errors (timer absent)", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- the flashlight's floor in any water ---------------- */
/* deployed-audit PR #30-31 finding 5: inside the beam's full-strength core the
 * floor (its caustics too) is the same in Realistic and Clear water. A static
 * frame (paused, no fish: their shadows are the water's; reduced motion: no
 * snow, an instant light), canvas pixels read right after the app's render */
const AFTER_FRAME = () => {
  const raf = window.requestAnimationFrame.bind(window);
  window.__after = [];
  window.requestAnimationFrame = (cb) => raf((t) => { cb(t); if (cb.name === "frame" && window.__after.length) { const q = window.__after; window.__after = []; q.forEach((f) => f()); } });
};
async function partBeam() {
  console.log("== the flashlight's floor: the same in any water at full beam");
  const c = caseFor(0, { config: Object.assign({}, CASES.benchmark.config, { minPopulation: 0 }) });
  const L = await launch("beam", { init: AFTER_FRAME });
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  const r = await L.page.evaluate(async () => {
    const B = EvoOcean.bench, S = EvoOcean.scene;
    S.setReducedMotion(true);
    await B.prepare({ camera: "whole", settleMs: 2500 });   /* the caustics fade in over ~1.4 s */
    const gl = document.getElementById("tank").getContext("webgl2"), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
    const grab = () => new Promise((res) => window.__after.push(() => { const px = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px); res(px); }));
    const shot = {};
    for (const light of [false, true]) for (const u of [0, 1]) { S.setClarity(u); S.setFlashlight(light); await B.frames(4); shot[(light ? "on" : "off") + u] = await grab(); }
    /* and the beam keeps its caustics (not just equally none): run the clock
     * on (their pattern slides with it; the sand does not), Clear water, light on */
    await B.live(true); await B.frames(30); await B.live(false); await B.frames(4);
    shot.later = await grab();
    S.setClarity(1); S.setFlashlight(false);
    /* the core's lower half: the floor there is nearer than the beam's reach, so its strength is 1 */
    function diff(a, b) {
      let n = 0, d = 0, max = 0;
      for (let y = 0; y <= H / 2; y++) for (let x = 0; x < W; x++) {
        if (Math.hypot(x - W / 2, y - H / 2) >= 90) continue;
        const p = 4 * (y * W + x), m = Math.max(Math.abs(a[p] - b[p]), Math.abs(a[p + 1] - b[p + 1]), Math.abs(a[p + 2] - b[p + 2]));
        n++; if (m) { d++; max = Math.max(max, m); }
      }
      return { pixels: n, differing: d, maxDiff: max };
    }
    return { n: EvoOcean.state().n, pc: EvoOcean.state().pc, on: diff(shot.on0, shot.on1), off: diff(shot.off0, shot.off1),
             live: diff(shot.on1, shot.later) };
  });
  report.parts.beam = r;
  check("no fish or predators in the frame (no water-shaded shadows)", r.n === 0 && r.pc === 0, { n: r.n, pc: r.pc });
  check("the water changes the floor without the light (the probe sees clarity)", r.off.differing > r.off.pixels * 0.9, r.off);
  check("at full beam the floor, caustics included, is the same in Realistic and Clear", r.on.pixels > 10000 && r.on.differing === 0, r.on);
  check("  and keeps its caustics: they slide with the clock over most of the full-beam floor", r.live.differing > r.live.pixels * 0.5, r.live);
  check("no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- the embed: 890 x 453 in a non-isolated parent ---------------- */
async function partIframe() {
  console.log("== iframe 890 x 453 under a non-isolated parent");
  const L = await launch("iframe", { viewport: { width: 1000, height: 600 } });
  /* the parent: about:blank, no COOP / COEP (a routed parent counts as a public
   * address, and Chrome's local-network-access check then blocks a localhost child) */
  await L.page.setContent("<!doctype html><title>parent</title><body style='margin:0'><iframe id=f src='" + BASE +
                          "/ocean.html?guide=0&intro=0&seed=7' width=890 height=453 style='border:0'></iframe></body>");
  const handle = await L.page.waitForSelector("#f");
  const fr = await handle.contentFrame();
  await fr.waitForFunction(() => window.EvoApp && EvoApp.ready === true && EvoOcean.state() && EvoOcean.state().frame > 20, null, { timeout: 90000 });
  const r = await fr.evaluate(async () => {
    const out = { coi: self.crossOriginIsolated, parentCoi: null, size: [innerWidth, innerHeight] };
    const wait = (ms) => new Promise((res) => setTimeout(res, ms));
    /* the View menu's colour buttons, as a visitor presses them; each mode as the page is then in it */
    out.colours = {};
    for (const m of ["family", "brain", "appearance"]) {
      document.querySelector("#colourMode button[data-c='" + m + "']").click();
      await wait(400);
      out.colours[m] = { mode: EvoOcean.state().colourMode, brain: EvoOcean.state().colourBrain, skin: EvoOcean.scene.appearance().skin,
                         pressed: [...document.querySelectorAll("#colourMode button[aria-pressed='true']")].map((b) => b.dataset.c).join() };
    }
    out.colour = EvoOcean.state().colourMode;
    EvoOcean.select(0); EvoOcean.follow(); await wait(800);
    out.following = EvoOcean.state().following;
    out.texFollow = await EvoOcean.scene.appearanceTextureParity();
    const e0 = EvoOcean.state().worldEpoch;
    /* Start (the start bar's): it asks first when the run has something to lose (UI-3), answered here */
    const asked = () => !document.getElementById("startask").hidden;
    document.getElementById("restart").click();
    if (asked()) document.getElementById("startconfirm").click();
    await wait(1200);
    out.epochAfterRestart = [e0, EvoOcean.state().worldEpoch];
    EvoApp.startTurbo();
    const t0 = Date.now();
    while (EvoOcean.state().turbo !== "turbo" && Date.now() - t0 < 20000) await wait(100);
    out.turbo = EvoOcean.state().turbo;
    const e1 = EvoOcean.state().worldEpoch;
    await wait(2000);
    document.getElementById("turboexit").click();
    while (EvoOcean.state().turbo !== "live" && Date.now() - t0 < 40000) await wait(100);
    await wait(800);
    out.back = EvoOcean.state().turbo; out.epochAcrossTurbo = [e1, EvoOcean.state().worldEpoch];
    out.texAfterTurbo = await EvoOcean.scene.appearanceTextureParity();
    out.frame = EvoOcean.state().frame;
    /* Stop Turbo & start (UI-4): Turbo used, so Start asks; the answer hands the world back, then exactly one new world */
    const e2 = EvoOcean.state().worldEpoch, t1 = Date.now();
    EvoApp.startTurbo();
    while (EvoOcean.state().turbo !== "turbo" && Date.now() - t1 < 20000) await wait(100);
    await wait(800);
    document.getElementById("restart").click(); await wait(200);
    out.replaceAsked = asked();
    document.getElementById("startconfirm").click();
    while ((EvoOcean.state().turbo !== "live" || EvoOcean.state().worldEpoch === e2) && Date.now() - t1 < 40000) await wait(100);
    await wait(600);
    out.replace = { epoch: [e2, EvoOcean.state().worldEpoch], turbo: EvoOcean.state().turbo, frame: EvoOcean.state().frame };
    return out;
  });
  r.parentCoi = await L.page.evaluate(() => self.crossOriginIsolated);
  const brief = (t) => ({ ok: t.ok, error: t.error, failures: t.failures, fish: t.fish });
  report.parts.iframe = Object.assign({}, r, { texFollow: brief(r.texFollow), texAfterTurbo: brief(r.texAfterTurbo) });
  check("the child is not cross-origin isolated, at 890 x 453", r.coi === false && r.parentCoi === false && r.size[0] === 890 && r.size[1] === 453, { coi: r.coi, size: r.size });
  check("the colour buttons in the embed: each mode, its pressed button, colourBrain, the scene's skin",
        ["family", "brain", "appearance"].every((m) => { const x = r.colours[m]; return x.mode === m && x.pressed === m && x.brain === (m === "brain") && x.skin === (m === "appearance"); }),
        r.colours);
  check("colours, select + follow, restart (new epoch), Turbo there and back (same epoch)",
        r.colour === "appearance" && r.following && r.epochAfterRestart[1] === r.epochAfterRestart[0] + 1 && r.turbo === "turbo" && r.back === "live" &&
        r.epochAcrossTurbo[0] === r.epochAcrossTurbo[1], report.parts.iframe);
  check("live texture check in the embed, following and after Turbo", r.texFollow.ok && r.texAfterTurbo.ok, { a: brief(r.texFollow), b: brief(r.texAfterTurbo) });
  check("Stop Turbo & start in the embed: asked first (Turbo used), then exactly one new world, live",
        r.replaceAsked === true && r.replace.turbo === "live" && r.replace.epoch[1] === r.replace.epoch[0] + 1, r.replace);
  check("no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- performance ---------------- */
const MODES = {
  off: { cpu: false, gpu: "off" },
  frame: { cpu: "frame", gpu: "off" },
  spans: { cpu: true, gpu: "off" },
  spansGpu: { cpu: true, gpu: "frame", sampleEvery: 6 }
};
async function capture(page, mode, ms) {
  const m = MODES[mode];
  return page.evaluate(async ([m, ms, off]) => {
    /* rAF timestamps in every mode (a common, tiny cost); "off" leaves the profiler off */
    const rp = EvoOcean.bench.rafProbe(ms);
    const cap = off ? null : EvoOcean.bench.capture(Object.assign({ durationMs: ms }, m));
    return { raf: await rp, cap: cap ? await cap : null };
  }, [m, ms, mode === "off"]);
}
async function partPerf() {
  console.log("== performance (the machine is shared with a parallel build: compare interleaved modes, not absolutes)");
  report.parts.perf = { note: "Headless Brave; rAF-paced (vsync-like 60 Hz cap); another builder compiling in parallel. Modes interleaved A/B so drift cancels.",
                        cells: {} };
  for (const pop of COUNTS) {
    const c = caseFor(pop);
    const L = await launch("perf-" + pop);
    await L.page.goto(benchUrl(c));
    await ready(L.page, true);
    for (const cam of CAMERAS) for (const colour of COLOURS) {
      const key = `${pop}_${cam}_${colour}`;
      const prep = await L.page.evaluate((cd) => EvoOcean.bench.prepare(cd), Object.assign({}, c, { camera: cam, colourMode: colour }));
      save("manifest_" + key + ".json", JSON.stringify(await manifestOf(L.page, "perf-" + key, { browserVersion: L.browserVersion, case: prep }), null, 1));
      await L.page.evaluate((ms) => EvoOcean.bench.wait(ms), WARM);
      const rows = { off: [], frame: [], spans: [], spansGpu: [] };
      for (let round = 0; round < ROUNDS; round++) {
        const order = round % 2 ? ["spansGpu", "spans", "frame", "off"] : ["off", "frame", "spans", "spansGpu"];
        for (const mode of order) {
          const r = await capture(L.page, mode, DUR);
          if (r.cap) { save(`frames_${key}_${mode}_${round}.csv`, r.cap.framesCsv); if (mode === "spansGpu") save(`gpu_${key}_${mode}_${round}.csv`, r.cap.gpuCsv); }
          rows[mode].push({ raf: r.raf, summary: r.cap ? r.cap.summary : null });
          console.log(`  ${key} ${mode.padEnd(8)} r${round}: rAF fps ${r.raf.rafFps.toFixed(1)} p95 ${r.raf.raf.p95.toFixed(2)} ms` +
                      (r.cap ? `, frameCpu p50 ${r.cap.summary.spans.frameCpu.p50.toFixed(3)} p95 ${r.cap.summary.spans.frameCpu.p95.toFixed(3)} ms, fps ${r.cap.summary.fps.toFixed(1)}` : ""));
        }
      }
      /* draw scopes apart from frame timing (never combined) */
      const dr = await L.page.evaluate((ms) => EvoOcean.bench.capture({ durationMs: ms, cpu: true, gpu: "draws", sampleEvery: 6 }), Math.min(DUR, 10000));
      save(`gpu_${key}_draws.csv`, dr.gpuCsv);
      report.parts.perf.cells[key] = { fish: pop, camera: cam, colour, case: prep.camera, rows, draws: dr.summary.gpu };
    }
    /* live: one step a frame from tick 0 (the population is recorded every frame) */
    await L.page.evaluate((cd) => EvoOcean.bench.prepare(cd), Object.assign({}, c, { camera: "whole", colourMode: "appearance" }));
    await L.page.evaluate(() => EvoOcean.bench.live(true));
    const live = await L.page.evaluate((ms) => EvoOcean.bench.capture({ durationMs: ms, cpu: true, gpu: "frame", sampleEvery: 6 }), DUR);
    save(`frames_${pop}_live.csv`, live.framesCsv);
    report.parts.perf.cells[`${pop}_live`] = { fish: pop, live: live.summary };
    check("perf " + pop + ": no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
    await L.ctx.close();
  }
}

const RUN = { correctness: partCorrectness, noperf: partNoPerf, faults: partFaults, timer: partTimer, beam: partBeam, iframe: partIframe, perf: partPerf };
(async () => {
  for (const p of PARTS) {
    if (!RUN[p]) { console.log("unknown part " + p); fails++; continue; }
    try { await RUN[p](); }
    catch (e) { fails++; console.log("  FAIL part " + p + " threw: " + (e && e.stack || e)); report.parts[p] = Object.assign(report.parts[p] || {}, { threw: String(e && e.message || e) }); }
  }
  report.finished = new Date().toISOString(); report.fails = fails;
  save("report.json", JSON.stringify(report, null, 1));
  save("parity.json", JSON.stringify(parity, null, 1));
  save("errors.json", JSON.stringify(errorsAll, null, 1));
  console.log((fails ? "FAILED: " + fails : "all passed") + " (" + report.checks.length + " checks); output in " + OUT);
  process.exit(fails ? 1 : 0);
})();
