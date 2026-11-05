// tests/ocean_render_browser.mjs: the Ocean's render checks and benchmark on the real page, in headless Brave.
//
//   node tests/ocean_render_browser.mjs --base http://localhost:8152 [--out DIR]
//        [--parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate,offimage,perf] [--counts 500,1500,2500]
//        [--dur 15000] [--warm 10000] [--rounds 2] [--headed]
//        [--cameras whole,dense,follow,fit] [--colours appearance,family,brain]   (perf; default whole, appearance)
//        [--modes off,frame,spans,spansGpu] [--viewport 1920x1080[@1]]       (perf; the default: all four, 1920 x 1080 at DPR 1)
//        [--arms main,off,on,ungated --main-base URL]   (perf by arms, below; offimage needs --main-base)
//   --counts takes "big" too: the Big tank (EvoOceanConfig.BIG_TANK: its size, population and set-up)
//   --cameras fit: the page's own fit of the whole tank (scene.resetView), where whole is a fixed camera
//   --arms: instead of profiler modes, the swim polish's arms, each capture spansGpu (cpu spans, GPU frame
//        queries every 6th) with rAF timestamps: main (--main-base's site: before the polish), off / on /
//        ungated / zero (this site with scene.setPolish false / true / "ungated": every fish at full weight, the
//        reference that shows what the size gate saves; "zero": every weight 0, so none lit: the plain programs; "fullUp": the polish on with
//        the whole gene texture uploaded every frame, as before render PR2; "split": the polish on with the lit fish drawn apart,
//        render PR2's opt-in split). Per cell, each round runs the arms in order
//        (reversed on odd rounds, so drift cancels), a fresh page per site, a warm-up after each load and a
//        settle after each switch; every observation records the arm, the effective polish state
//        (scene.polish(): programs, gate, the last frame's weights), quality, DPR, the drawing buffer, the
//        camera and the served asset names (content-hashed)
//   env: PLAYWRIGHT  the playwright module (default C:/Users/harit/gemini_bridge/node_modules/playwright)
//        BRAVE_EXE   the browser (default C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe)
//
// Serve web/ (or a built site) with the production isolation headers first
// (wasm/serve.py), with the matching evo_ocean.wasm. Every part is an
// independent run: a fresh browser and temporary profile, one at a time.
//   correctness  the production checks (appearancePathCheck: the fixed
//                fixture through the vertex shader in both colour modes and
//                the fragment shader, and with permuted / sparse gene slots),
//                the attribute-fed reference
//                (appearanceParity), the live gene texture (appearance-,
//                family- and brain-colour frames), and the profiler's
//                gene-upload counters against intercepted WebGL uploads
//                (paused: none at all; stepping: the new fish's slots only); the
//                bench itself (a case's tick restored, its colour modes not
//                stored, a Restart's link without renderBench / perf)
//   slots        render PR2's gene slots through the real render path:
//                synthetic snapshots of a 2,048-fish world (reordered, deaths
//                and births, the owners of slots 31 / 32 / 63 / 64 and 2047 /
//                2048, growth to 2,049 then 2,500, shrink and refill, detail
//                and colour changes, held uploads, a new epoch with the same
//                ids, a refused snapshot), each checked by the live-texture
//                probe, with its uploads counted (calls, bytes, rectangles,
//                allocations); the dirty uploads' texture word for word
//                against the whole-texture policy's
//   noperf       web/ocean_perf.js blocked (a normal link, ?renderBench=1):
//                the page starts and draws with no other error
//   missing      a script the 3-D scene needs blocked (ocean_shaders.js,
//                ocean_pose.js, both, ocean_scene_parity.js, or ocean_scene.js
//                itself): the page stops, and its splash names the file, with
//                no other error; one of the first three throwing as it loads:
//                its splash says it failed to run
//   faults       each planted fault must be caught (and compile and run):
//                the texture lookup (row0, nextRow, slot) and vPart.w in both
//                vertex reports; the slot selector on the draw index again
//                (drawIndex: the slot maps); red / blue unpacking and the colour-mode
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
//                texture check, the swim polish's size weights (GATE_CHECK)
//   gate         the swim polish's size weights (GATE_CHECK: every fish's
//                uploaded weight against an independent projection of its
//                bounding sphere) at 390 x 844 DPR 3 (drawn at DPR 2) and
//                1400 x 900 DPR 2, whole and close views, a panel's inset
//                (view offset), a resize; and the swim pose on known spines
//   offimage     (--main-base) the polish off draws exactly main's image:
//                the same paused, clock-frozen frames on both sites (Appearance,
//                Family, Brain colours, close up with the flashlight, the plain
//                bodies of appearance 0, predators), RGBA8 read back after
//                the app's render, compared pixel for pixel; and the polish on
//                differs (the test can see it)
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
const COUNTS = String(arg("counts", "500,1500,2500")).split(",").map((x) => (x === "big" ? x : Number(x)));
const DUR = Number(arg("dur", 15000)), WARM = Number(arg("warm", 10000)), ROUNDS = Number(arg("rounds", 2));
const CAMERAS = String(arg("cameras", "whole")).split(","), COLOURS = String(arg("colours", "appearance")).split(",");
const PERF_MODES = String(arg("modes", "off,frame,spans,spansGpu")).split(",");
const MAIN_BASE = arg("main-base", null) ? String(arg("main-base")).replace(/\/$/, "") : null;
const ARMS = arg("arms", null) ? String(arg("arms")).split(",") : null;
const VIEWPORT = (() => { const m = /^(\d+)x(\d+)(?:@([\d.]+))?$/.exec(String(arg("viewport", "1920x1080@1")));
  if (!m) throw new Error("--viewport WxH[@dpr]"); return { width: +m[1], height: +m[2], dpr: m[3] ? +m[3] : 1 }; })();
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
    executablePath: BRAVE, headless: !HEADED, viewport: opts.viewport || { width: 1920, height: 1080 }, deviceScaleFactor: opts.dpr || 1,
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
function benchUrl(c, extra = {}, base = BASE) {
  const q = new URLSearchParams(Object.assign({ renderBench: "1", guide: "0", intro: "0", seed: String(c.worldSeed), pop: String(c.population),
    w: String(c.world[0]), h: String(c.world[1]), depth: String(c.world[2]), speed: String(c.speed), colour: c.colourMode || "appearance",
    walls: c.config.walls ? "1" : "0", cfg: JSON.stringify(Object.assign({}, c.config, { walls: undefined })) }, extra));
  return base + "/ocean.html?" + q.toString();
}
/* The swim polish's size weights against an independent projection (in the
 * page): for every fish as the last frame uploaded it (scene.poseOf: its
 * unwrapped spine, radius, height, pitch, lambda and iPose; POSE0's when the
 * frame packed none, posed false: then every expected weight must be 0), the
 * body's sphere (centre between head and tail, radius half their distance +
 * 2 R) in camera space through the full view matrix; the radius R projected
 * through the full projection matrix at the sphere's nearest depth, in CSS
 * px of the canvas's own rectangle: at most 6 px, 0 (below); else 0 when the
 * fish's whole reach (EvoOceanScene.reachRadius about the same centre, whose
 * enclosure of every drawn vertex the vertex check proves) is behind the near
 * plane or wholly outside a side plane of the frustum (the planes taken from
 * the projection matrix's rows, Gribb-Hartmann: row 3 +- rows 0, 1), else
 * smoothstep(6, 11, px). The uploaded weight has 7 bits (|err| <= 1 / 254).
 * Reports the worst |uploaded - expected| over all fish, how many are at most
 * 6 px, in between, above 11 and outside, the canvas and the drawing buffer,
 * and checks every uploaded pose is finite with a unit sin / cos and a roll
 * within the clamp times the fish's weight (the roll scales with it). */
const GATE_CHECK = async (label) => {
  const S = EvoOcean.scene;
  for (let k = 0; k < 3; k++) await new Promise((res) => requestAnimationFrame(res));   /* (no bench in a plain page) */
  const G = S.poseCamera(), st = S.polish(), n = EvoOcean.state().n, V = G.view, P = G.proj;
  const rect = document.getElementById("tank").getBoundingClientRect();
  const out = { label, n, maxErr: 0, worst: null, below: 0, mid: 0, above: 0, outside: 0, nonFinite: 0, badRoll: 0, posed: 0, apart: 0, apartUnlit: 0,
                canvasCss: [rect.width, rect.height], drawingBuffer: G.drawingBuffer, dpr: devicePixelRatio, focalCss: G.focalCss, state: st };
  const clip = (q) => { const w = P[3] * q[0] + P[7] * q[1] + P[11] * q[2] + P[15];
    return [(P[0] * q[0] + P[4] * q[1] + P[8] * q[2] + P[12]) / w, (P[1] * q[0] + P[5] * q[1] + P[9] * q[2] + P[13]) / w]; };
  const row = (r) => [P[r], P[4 + r], P[8 + r], P[12 + r]];
  const planes = [[3, 0, 1], [3, 0, -1], [3, 1, 1], [3, 1, -1]].map(([a, b, sg]) => { const A = row(a), B = row(b), q = A.map((x, k) => x + sg * B[k]);
    const l = Math.hypot(q[0], q[1], q[2]); return q.map((x) => x / l); });   /* inside: q . (x, y, z, 1) >= 0 */
  const sm = (x) => { const t = Math.max(0, Math.min(1, (x - 6) / 5)); return t * t * (3 - 2 * t); };
  for (let i = 0; i < n; i++) {
    const f = S.poseOf(i), p = f.pose;
    if (f.posed) out.posed++;
    if (f.apart >= 0) { out.apart++; if (!(p[3] > 0)) out.apartUnlit++; }   /* drawn apart (render PR2's split): lit fish only */
    if (!p.every(Number.isFinite)) { out.nonFinite++; continue; }
    if (Math.abs(p[0] * p[0] + p[1] * p[1] - 1) > 1e-5 || Math.abs(Math.atan2(p[0], p[1])) > 0.6 * p[3] + 2e-3) out.badRoll++;
    const xs = [0, 2, 4, 6, 8, 10].map((k) => f.spine[k]), ys = [1, 3, 5, 7, 9, 11].map((k) => f.spine[k]);
    const c = [(xs[0] + xs[5]) / 2 - G.halfW, f.y, (ys[0] + ys[5]) / 2 - G.halfH];
    const rb = 0.5 * Math.hypot(xs[0] - xs[5], ys[0] - ys[5]) + 2 * f.R;
    const v = [0, 1, 2].map((r) => V[r] * c[0] + V[4 + r] * c[1] + V[8 + r] * c[2] + V[12 + r]), dz = -v[2];
    const dn = Math.max(dz - rb, G.near);
    const a = clip([v[0], v[1], -dn]), b = clip([v[0], v[1] + f.R, -dn]);
    const px = Math.abs(b[1] - a[1]) * 0.5 * rect.height;
    let want;
    if (!(px > 6)) { want = 0; out.below++; }
    else {
      const rv = EvoOceanScene.reachRadius(xs, ys, f.R, f.vz, f.lam, f.reach);
      const outside = dz + rv <= G.near || planes.some((q) => q[0] * v[0] + q[1] * v[1] + q[2] * v[2] + q[3] < -rv);
      if (outside) { want = 0; out.outside++; }
      else { want = sm(px); if (px >= 11) out.above++; else out.mid++; }
    }
    const e = Math.abs(want - p[3]);
    if (e > out.maxErr) { out.maxErr = e; out.worst = { fish: i, want, got: p[3], px, posed: f.posed }; }
  }
  return out;
};
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
           texture: r.texture, slots: r.slots, mutate: r.mutate, pendingUpload: r.pendingUpload };
}

/* the upload interceptor, while __up.on: texImage2D / texSubImage2D calls whose
 * pixels are the gene texture's storage (the scene's current one, asked at the
 * call: it is replaced when the slots grow; a typed array, the last argument, or
 * the one before a WebGL2 source offset), with each rectangle (x, y, w, h: a
 * range is one texture row) and its bytes; texStorage2D allocations of a
 * 512-wide RGBA32F texture (the gene texture's GPU storage) apart */
const INTERCEPT = () => {
  window.__up = { on: false, n: 0, bytes: 0, other: 0, allocs: 0, rects: [], reset() { this.n = this.bytes = this.other = this.allocs = 0; this.rects = []; } };
  const P = WebGL2RenderingContext.prototype;
  const geneBuf = () => { const S = window.EvoOcean && EvoOcean.scene, g = S && S.geneTexture && S.geneTexture(); return g && g.data ? g.data.buffer : null; };
  for (const name of ["texImage2D", "texSubImage2D"]) {
    const f = P[name];
    P[name] = function () {
      const a = arguments, u = window.__up;
      if (u && u.on) {
        let px = a[a.length - 1];
        if (typeof px === "number" && a.length >= 2) px = a[a.length - 2];   /* (pixels, srcOffset) */
        const buf = geneBuf();
        if (px && px.buffer && buf && px.buffer === buf) {
          const sub = name === "texSubImage2D", w = sub ? a[4] : a[3], h = sub ? a[5] : a[4];
          u.n++; u.bytes += w * h * 16;
          if (u.rects.length < 4096) u.rects.push(sub ? [a[2], a[3], w, h] : [0, 0, w, h]);
        } else u.other++;
      }
      return f.apply(this, a);
    };
  }
  const st = P.texStorage2D;
  P.texStorage2D = function (target, levels, fmt, w, h) {
    const u = window.__up;
    if (u && u.on && fmt === 0x8814 && w === 512) u.allocs++;   /* RGBA32F, 512 wide */
    return st.apply(this, arguments);
  };
};

async function manifestOf(page, label, extra = {}) {
  const info = await page.evaluate(() => EvoOcean.bench ? EvoOcean.bench.info() : null);
  return Object.assign({ label, base: BASE, launchArgs: LAUNCH_ARGS, headless: !HEADED, playwright: require(PW + "/package.json").version,
    hashes: { "web/evo_ocean.wasm": sha("web/evo_ocean.wasm"), "web/ocean_scene.js": sha("web/ocean_scene.js"), "web/ocean_perf.js": sha("web/ocean_perf.js"),
              "web/ocean_appearance_slots.js": sha("web/ocean_appearance_slots.js"), "web/ocean_shaders.js": sha("web/ocean_shaders.js"),
              "web/ocean_pose.js": sha("web/ocean_pose.js"), "web/ocean_scene_parity.js": sha("web/ocean_scene_parity.js"),
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
  /* render PR2's split (the lit fish apart: off by default, it measured slower) on for this part, so its checks see it */
  await L.page.evaluate(() => EvoOcean.scene.setLitSplit(true));
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
  /* render PR2: the genes read from each fish's own slot (iGeneSlot), whatever the draw order */
  const sl = pathRes.slots || {};
  check("  gene slots apart from the draw order (iGeneSlot): a permuted map and a sparse one (31 / 32, 63 / 64, 2047 / 2048 on both sides; a 4,096-slot texture), every part",
        sl.ok === true && sl.permuted.slotMap === "permuted" && sl.permuted.allParts && sl.sparse.slotMap === "sparse" && sl.sparse.maxSlot >= 2048 && sl.sparse.texRows === 128,
        sl.permuted && { permuted: pathSummary({ appearance: sl.permuted }).appearance, sparse: pathSummary({ appearance: sl.sparse }).appearance, maxSlot: sl.sparse.maxSlot });
  /* the swim polish's programs: animated, walled, posed (POSE_SPECIAL: a pane, a collapsed spine, sharp turns, genes 0 / 1) */
  const pp = pathRes.polish || {};
  check("  polished vertex, appearance mode: 71 fish (65 + 6 special), 51 components, every part, animated and walled",
        pp.appearance && pp.appearance.ok && pp.appearance.fish === 71 && pp.appearance.components === 51 && pp.appearance.allParts && pp.appearance.polish === true,
        pp.appearance && pathSummary({ appearance: pp.appearance }).appearance);
  check("  polished vertex, recolour mode: 11 components", pp.recolour && pp.recolour.ok && pp.recolour.components === 11 && pp.recolour.polish === true,
        pp.recolour && pathSummary({ recolour: pp.recolour }).recolour);
  /* the size gate's visibility sphere (reachRadius) holds every vertex the GPU placed: plain, polished and lite, both colour modes */
  const reachOf = (r) => r && r.templates ? Object.fromEntries(Object.entries(r.templates).map(([k, t]) => [k, t.reach && { verts: t.reach.verts, outside: t.reach.outside, maxRatio: +t.reach.maxRatio.toFixed(3), worst: t.reach.outside ? t.reach.worst : undefined }])) : null;
  const reachRuns = { plain: pathRes.appearance, plainRecolour: pathRes.recolour, polished: pp.appearance, polishedRecolour: pp.recolour, lite: pp.lite && pp.lite.appearance, liteRecolour: pp.lite && pp.lite.recolour };
  const reachRep = Object.fromEntries(Object.entries(reachRuns).map(([k, r]) => [k, reachOf(r)]));
  check("  the size gate's reach sphere holds every vertex drawn (bent, rolled, folded, wagging, pitched, walled; genes 0 / 1, long fins and barbels): plain, polished, lite",
        Object.values(reachRep).every((r) => r && Object.values(r).length === 3 && Object.values(r).every((t) => t && t.verts > 0 && t.outside === 0)), reachRep);
  check("  lite vertex (the roll only: the polished shadows' stage), both colour modes: 71 fish, animated and walled",
        pp.lite && pp.lite.appearance.ok && pp.lite.recolour.ok && pp.lite.appearance.fish === 71 && pp.lite.appearance.components === 51 && pp.lite.recolour.components === 11,
        pp.lite && { appearance: pathSummary({ appearance: pp.lite.appearance }).appearance, recolour: pathSummary({ recolour: pp.lite.recolour }).recolour });
  check("  polished fragment: front-lit with the highlight, weight 0 == plain, backlit (zero half vector: finite, no highlight; fins glow through)",
        pp.fragment && pp.fragment.ok && ["recolour", "recolourW0", "recolourBack"].every((m) => pp.fragment.modes[m] && pp.fragment.modes[m].cases === 240) &&
        ["appearance", "appearanceW0", "appearanceBack"].every((m) => pp.fragment.modes[m] && pp.fragment.modes[m].cases === 9) && pp.fragment.nonFinite === 0,
        pp.fragment && { modes: pp.fragment.modes, worst: pp.fragment.worst, nonFinite: pp.fragment.nonFinite });
  /* the plain programs are the ones before the polish: no pose attribute, no polish terms */
  const src = await L.page.evaluate(() => { const a = EvoOceanScene.shaderSources(false), b = EvoOceanScene.shaderSources(true), l = EvoOceanScene.shaderSources("lite");
    const all = (x) => [x.fishVs, x.fishFs, x.shadowVs, x.app.vs, x.app.fs, x.app.shadowVs].join("\n");
    return { plainPose: /iPose|polishK|wagAt|finPose|causOf/.test(all(a)),
             polishPose: ["fishVs", "shadowVs"].every((k) => b[k].includes("poseOf(iX.y)")) && b.app.vs.includes("finPose(M, geo)") && b.app.shadowVs.includes("poseOf(iBody.w)") && !b.app.shadowVs.includes("finPose(M, geo)"),
             lite: l.app.fs === a.app.fs && l.fishFs === a.fishFs && l.app.vs.includes("poseOf(iBody.w)") && !l.app.vs.includes("finPose(M, geo)") && !/polishK|vCaus/.test(l.app.vs + l.fishVs) }; });
  check("the plain programs read no pose and draw no polish; the full ones unpack the pose (body and shadow; the shadow the roll only); the lite ones the roll only, with the plain fragment stage",
        !src.plainPose && src.polishPose && src.lite, src);
  /* the swim pose on known spines (EvoOceanScene.swimPose, ungated) */
  const sp = await L.page.evaluate(() => {
    const f = EvoOceanScene.swimPose, r = {};
    function spine(a, bend, len) { const xs = [500], ys = [500]; for (let k = 1; k < 6; k++) { xs.push(xs[k - 1] - len * Math.cos(a + bend * k)); ys.push(ys[k - 1] - len * Math.sin(a + bend * k)); } return [xs, ys]; }
    for (const [name, a, b, l, v] of [["straight", 0.3, 0, 4, 1], ["left", 0.3, 0.25, 4, 1], ["right", 0.3, -0.25, 4, 1], ["sharpL", 0.3, 1.2, 4, 1], ["sharpR", 0.3, -1.2, 4, 1],
                                       ["collapsed", 0, 0, 0, 1], ["slow", 0.3, 0, 4, 0.2], ["still", 0.3, 0, 4, 0]]) {
      const [xs, ys] = spine(a, b, l); const p = f(xs, ys, 4.6, -50, v, { gate: false });
      r[name] = EvoOceanScene.unpackPose(p).concat([p, Number.isInteger(p) && p >= 0 && p < 16777216 ? 1 : 0]);
    }
    return r;
  });
  const bankOf = (p) => Math.atan2(p[0], p[1]);
  check("swimPose (packed in one float, an integer < 2^24): straight 0 roll, full fold at speed; turns roll opposite ways, equally; sharp turns at the 0.6 clamp with the fold eased; a collapsed spine finite and level; slow / still: no fold",
        Object.values(sp).every((p) => p.every(Number.isFinite) && p[3] === 1 && p[5] === 1) && bankOf(sp.straight) === 0 && sp.straight[2] === 1 &&
        bankOf(sp.left) * bankOf(sp.right) < 0 && Math.abs(bankOf(sp.left) + bankOf(sp.right)) < 2e-3 &&
        Math.abs(Math.abs(bankOf(sp.sharpL)) - 0.6) < 2e-3 && Math.abs(Math.abs(bankOf(sp.sharpR)) - 0.6) < 2e-3 && sp.sharpL[2] < 0.05 &&
        bankOf(sp.collapsed) === 0 && sp.slow[2] === 0 && sp.still[2] === 0, sp);
  /* the roll scales with the size weight (option 1 of #48: no pop when a kind switches between its plain and full programs) */
  const sw = await L.page.evaluate(() => {
    const S = EvoOceanScene, xs = [500], ys = [500];
    for (let k = 1; k < 6; k++) { xs.push(xs[k - 1] - 4 * Math.cos(0.3 + 1.2 * k)); ys.push(ys[k - 1] - 4 * Math.sin(0.3 + 1.2 * k)); }
    /* a camera looking down -z from z = d at the fish (three: X = x - halfW, Z = y - halfH), focal 500 css px, so R = 4.6 shows at 2300 / d px */
    const G = (d) => ({ gate: true, view: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -d, 1], proj: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0],
                        focal: 500, near: 1, halfW: 498, halfH: 498, planes: [0.7071, -0.7071, -0.7071, -0.7071, 0.7071, -0.7071, -0.7071, -0.7071] });
    return [600, 300, 250, 210].map((d) => { const p = S.unpackPose(S.swimPose(xs, ys, 4.6, 0, 1, G(d), 0, 4, S.REACH_APP)); return [d, Math.atan2(p[0], p[1]), p[2], p[3]]; });
  });
  check("  the roll and the fold scale with the size weight: unlit (under 6 px) level and spread (POSE0), then growing with it up to the clamp",
        sw[0][1] === 0 && sw[0][3] === 0 && sw[0][2] === 0 && sw.slice(1).every((r) => r[3] > 0 && Math.abs(Math.abs(r[1]) - 0.6 * r[3]) < 4e-3) && sw[3][3] === 1, sw);
  /* the size weights in the production frame: whole tank, close up (following), a panel's inset, zoomed out; ungated; off */
  const gw = await L.page.evaluate(GATE_CHECK, "whole 1920x1080@1");
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "follow", colourMode: "appearance", settleMs: 1500 })), c);
  const gf = await L.page.evaluate(GATE_CHECK, "follow 1920x1080@1");
  const gi = await L.page.evaluate(async (g) => { EvoOcean.scene.setInsets({ top: 0, right: 420, bottom: 0, left: 0 }); await EvoOcean.bench.wait(800); const r = await (0, eval)("(" + g + ")")("follow + right inset 420 (view offset)"); EvoOcean.scene.setInsets({}); return r; }, GATE_CHECK.toString());
  const gz = await L.page.evaluate(async (g) => { EvoOcean.scene.zoomBy(2.5); await EvoOcean.bench.wait(800); return (0, eval)("(" + g + ")")("follow, zoomed out x2.5"); }, GATE_CHECK.toString());
  const gu = await L.page.evaluate(async (g) => { EvoOcean.scene.setPolish("ungated"); await EvoOcean.bench.frames(4); const r = await (0, eval)("(" + g + ")")("ungated"); EvoOcean.scene.setPolish(true); return r; }, GATE_CHECK.toString());
  const goff = await L.page.evaluate(async () => { EvoOcean.scene.setPolish(false); await EvoOcean.bench.frames(4); const r = EvoOcean.scene.polish(); EvoOcean.scene.setPolish(true); await EvoOcean.bench.frames(4); return r; });
  report.parts.correctness.gate = { whole: gw, follow: gf, inset: gi, zoomed: gz, ungated: { state: gu.state, n: gu.n }, off: goff };
  const gok = (g) => g.nonFinite === 0 && g.badRoll === 0 && g.maxErr <= 4e-3;
  check("size weights == the independent projection (|err| <= .004: 7-bit weights), finite, unit rolls within 0.6: whole, follow, inset, zoomed",
        [gw, gf, gi, gz].every(gok), [gw, gf, gi, gz].map((g) => ({ label: g.label, maxErr: g.maxErr, worst: g.worst, below: g.below, mid: g.mid, above: g.above, outside: g.outside, focal: g.focalCss, canvas: g.canvasCss })));
  check("  the whole view: fish under 6 px, none at 11, and with none lit main's plain programs; close up: in the 6 .. 11 ramp, above 11, and the rest outside the view (0), the full programs (compiled ahead)",
        gw.below > 0 && gw.above === 0 && gw.state.variant === (gw.mid ? "full" : "plain") &&
        gf.mid > 0 && gf.above > 0 && gf.outside > 0 && gf.state.variant === "full" && gf.state.ready === true,
        { whole: [gw.below, gw.mid, gw.above, gw.outside], wholeState: gw.state, follow: [gf.below, gf.mid, gf.above, gf.outside], followState: gf.state });
  check("  the whole view packs no swim pose when no fish can be lit (the frame's bound under 6 px), and close up every fish's",
        (gw.state.bound > 6 || (gw.state.posing === false && gw.posed === 0)) && gf.state.posing === true && gf.posed === gf.n,
        { whole: { bound: gw.state.bound, posing: gw.state.posing, posed: gw.posed }, follow: { bound: gf.state.bound, posing: gf.state.posing, posed: gf.posed } });
  check("  the panel's inset changes the projection (view offset) and the weights follow it; zooming out brings fish into the view",
        gi.focalCss !== gf.focalCss && gz.outside < gf.outside, { focal: [gf.focalCss, gi.focalCss], outside: [gf.outside, gi.outside, gz.outside], mean: [gf.state.meanWeight, gi.state.meanWeight, gz.state.meanWeight] });
  check("  ungated: every fish at full weight; off: the plain programs (no weights)",
        gu.state.gated === false && gu.state.full === gu.state.fish && gu.state.fish === 2500 && goff.on === false && goff.any === 0 && goff.variant === "plain", { ungated: gu.state, off: goff });
  /* render PR2's split: close up, the lit fish (and only they) drawn apart on the full programs, the rest plain; every fish lit
   * (ungated): no split (the whole kind on the full programs); the whole view: nothing apart */
  check("  close up: the lit fish drawn apart on the full programs (each one lit, all of them), the rest plain; ungated (all lit): no split; whole view: none apart",
        gf.state.split === true && gf.state.litDrawn === gf.state.any && gf.apart === gf.state.any && gf.apartUnlit === 0 && gf.state.any > 0 && gf.state.any * 2 <= gf.n &&
        gu.state.split === false && gu.state.litDrawn === 0 && gw.apart === 0 && gw.state.litDrawn === 0,
        { follow: { split: gf.state.split, litDrawn: gf.state.litDrawn, lit: gf.state.any, apart: gf.apart, apartUnlit: gf.apartUnlit, n: gf.n },
          ungated: { split: gu.state.split, litDrawn: gu.state.litDrawn }, whole: { apart: gw.apart, litDrawn: gw.state.litDrawn } });
  /* hysteresis: from the close view (lit fish, full programs) straight to the whole view (none lit). Without the split
   * (setLitSplit(false): the whole kind on the full programs while any fish is lit) the full programs are held 30 frames,
   * then main's plain ones for good, no switching back and forth; with the split (the default: only lit fish on the full
   * programs, apart) there is no whole-draw cost to hold: plain from the first frame with no fish lit (review of #53,
   * P3-2), while the hold still keeps the poses packed */
  const HYST = async (split) => {
    const S = EvoOcean.scene, B = EvoOcean.bench, seq = [];
    S.setLitSplit(split);
    await B.prepare({ camera: "follow", settleMs: 600 });
    const before = S.polish();
    S.resetView(false);
    for (let k = 0; k < 50; k++) { await B.frames(1); const p = S.polish(); seq.push([p.variant === "full" ? 1 : 0, p.any, p.hold, p.posing ? 1 : 0, p.split ? 1 : 0]); }
    S.setLitSplit(true);
    return { before: { variant: before.variant, split: before.split, lit: before.any }, seq };
  };
  const hyU = await L.page.evaluate(HYST, false), hyS = await L.page.evaluate(HYST, true);
  const hy = hyU.seq, flips = hy.slice(1).filter((r, k) => r[0] !== hy[k][0]).length, firstPlain = hy.findIndex((r) => r[0] === 0);
  check("  hysteresis without the split: leaving a close view, the full programs are held ~30 frames after the last lit fish, then plain, switching once",
        hyU.before.variant === "full" && hyU.before.split === false && flips === 1 && firstPlain >= 25 && firstPlain <= 34 && hy.slice(firstPlain).every((r) => r[0] === 0 && r[1] === 0),
        { flips, firstPlain, seq: hy.map((r) => r.join("")).join(" ") });
  const sPlain = hyS.seq.findIndex((r) => r[0] === 0 && r[1] === 0), sHold = hyS.seq.filter((r) => r[0] === 0 && r[2] > 0 && r[3] === 1).length;
  check("  with the split: the close view's lit fish apart, then plain from the first frame with none lit (no 30-frame hold of the full programs), for good; the hold keeps the poses packed",
        hyS.before.variant === "full" && hyS.before.split === true && sPlain >= 0 && sPlain <= 2 && hyS.seq.slice(sPlain).every((r) => r[0] === 0 && r[4] === 0) && sHold >= 20,
        { before: hyS.before, firstPlain: sPlain, plainWhileHeld: sHold, seq: hyS.seq.map((r) => r.join("")).join(" ") });
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", colourMode: "appearance", settleMs: 300 })), c);

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
  check("  charted slots include both sides of 31/32 and 2047/2048 (their owners' draws)", t0 && [31, 32, 2047, 2048].every((d) => t0.intrinsic.slots.includes(d)), t0 && { slots: t0.intrinsic.slots, draws: t0.intrinsic.charted });
  check("  the texture: 512 x 128 RGBA float, nearest, no mipmaps, gene-slot capacity 4,096 (draw capacity apart: 4,096)", t0 && t0.texture.width === 512 && t0.texture.height === 128 &&
        t0.texture.type === 1015 && t0.texture.format === 1023 && t0.texture.minFilter === 1003 && t0.texture.magFilter === 1003 && !t0.texture.mipmaps &&
        t0.texture.capacity === 4096 && t0.texture.drawCapacity === 4096 && t0.slots && t0.slots.owners === 2500, t0 && { texture: t0.texture, slots: t0.slots });

  /* the profiler's gene-upload counters against the WebGL calls themselves (outside any timed run): paused (the
   * same fish every frame: nothing), then stepping 64 ticks a frame (births and deaths: the dirty slots only) */
  const UPLOADS = async (stepTo) => {
    const S = EvoOcean.scene, io0 = S.geneTexture();
    window.__up.reset(); window.__up.on = true;
    const dur = stepTo ? 16000 : 2000, t0 = performance.now();   /* (a loaded machine steps 64 ticks of 2,500 fish in ~1 s) */
    const capP = EvoOcean.bench.capture({ durationMs: dur, cpu: true, gpu: "off", drainMs: 0, raw: true });
    let stepMs = 0;
    if (stepTo) { await EvoOcean.bench.wait(300); await EvoOcean.bench.stepToTick(EvoOcean.state().frame + stepTo); await EvoOcean.bench.frames(3); stepMs = performance.now() - t0; }
    const cap = await capP;
    window.__up.on = false;
    const io1 = S.geneTexture(), NK = cap.schema.counters.length, K = EvoOceanPerf.K, texBytes = io1.data.byteLength;
    const sum = { uploads: 0, calls: 0, bytes: 0, src: 0, pad: 0, frames: 0, submitted: 0, framesUploading: 0, maxBytes: 0, maxCalls: 0, full: 0, rangeFrames: 0, badFrames: 0, bad: [] };
    for (let f = 0; f < cap.frames; f++) {
      const g = (k) => { const v = cap.cnt[f * NK + K[k]]; return v === v ? v : 0; };
      sum.uploads += g("geneUploads"); sum.calls += g("geneUploadCalls"); sum.bytes += g("geneUploadBytes");
      sum.src += g("geneSrcBytes"); sum.pad += g("genePadBytes"); sum.full += g("geneFull");
      sum.frames++; if (g("submitted") === 1) sum.submitted++;
      sum.maxBytes = Math.max(sum.maxBytes, g("geneUploadBytes")); sum.maxCalls = Math.max(sum.maxCalls, g("geneUploadCalls"));
      if (!g("geneUploads")) continue;
      sum.framesUploading++;
      /* each uploading frame: its new fish's slots in at most 32 ranges (256 bytes each), or one whole upload */
      const ok = g("geneUploads") === 1 && (g("geneFull") ? g("geneUploadCalls") === 1 && g("geneUploadBytes") === texBytes
                                                          : g("geneUploadCalls") <= 32 && g("geneUploadBytes") === g("geneSrcBytes") / 252 * 256);
      if (!g("geneFull")) sum.rangeFrames++;
      if (!ok) { sum.badFrames++; if (sum.bad.length < 4) sum.bad.push({ f, uploads: g("geneUploads"), calls: g("geneUploadCalls"), bytes: g("geneUploadBytes"), src: g("geneSrcBytes"), full: g("geneFull") }); }
    }
    return { durMs: dur, stepMs, inside: stepMs < dur - 200, profiler: sum, intercepted: { calls: window.__up.n, bytes: window.__up.bytes, allocs: window.__up.allocs, other: window.__up.other },
             sceneIO: { uploads: io1.uploads - io0.uploads, calls: io1.calls - io0.calls, bytes: io1.bytes - io0.bytes, allocs: io1.allocs - io0.allocs },
             capacity: io1.capacity, slots: io1.slots, textureBytes: io1.data.byteLength };
  };
  const still = await L.page.evaluate(UPLOADS, 0);
  const moving = await L.page.evaluate(UPLOADS, 512);
  const movingTex = await L.page.evaluate(() => EvoOcean.bench.textureParity());
  report.parts.correctness.uploads = { paused: still, stepping: moving };
  parity.texture_afterBirths = texSummary(movingTex);
  check("paused (the same fish every frame): no gene copy, no upload, no call, no byte (profiler, scene and intercepted)",
        still.profiler.frames > 30 && still.profiler.submitted > 30 && still.profiler.uploads === 0 && still.profiler.calls === 0 && still.profiler.bytes === 0 &&
        still.profiler.src === 0 && still.profiler.pad === 0 && still.sceneIO.uploads === 0 && still.intercepted.calls === 0 && still.intercepted.bytes === 0, still);
  check("stepping 64 ticks a frame (births, deaths): gene-upload counters == intercepted WebGL calls and bytes; 252 bytes copied a new fish; no allocation",
        moving.inside && moving.profiler.uploads > 0 && moving.profiler.calls === moving.intercepted.calls && moving.profiler.bytes === moving.intercepted.bytes &&
        moving.sceneIO.calls === moving.intercepted.calls && moving.sceneIO.uploads === moving.profiler.uploads &&
        moving.profiler.pad * 63 === moving.profiler.src && moving.intercepted.allocs === 0 && moving.sceneIO.allocs === 0, moving);
  check("  each uploading frame: its new fish's slots (256 bytes each) in at most 32 ranges, or one whole upload (review of #53, P3-1); the live texture bit-exact after the births",
        moving.profiler.badFrames === 0 && moving.profiler.maxCalls <= 32 && movingTex.ok === true && movingTex.rawGenes.mismatches === 0,
        { framesUploading: moving.profiler.framesUploading, rangeFrames: moving.profiler.rangeFrames, wholeFrames: moving.profiler.full, maxCalls: moving.profiler.maxCalls,
          maxBytes: moving.profiler.maxBytes, bad: moving.profiler.bad, texture: texSummary(movingTex) });
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", colourMode: "appearance", settleMs: 200 })), c);   /* back to tick 0 */

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

/* ---------------- the gene slots' lifecycle through the real render path ---------------- */
/* render PR2. A real world of 2,048 fish (paused at tick 0), then synthetic
 * snapshots made from it (its fish reordered, dropped, replaced by new ids
 * with other genes, added; a new epoch with the same ids; a refused one),
 * handed to the page's own scene.render in place of the real snapshot (the
 * whole fillFish / fillApp / commit path and three's submission and upload),
 * each followed by the live-texture probe against owned copies of that
 * synthetic snapshot (bit-exact genes and padding, charts, no probe upload),
 * with the gene uploads counted three ways (the scene's onUpdate tallies, the
 * intercepted texSubImage2D calls with their rectangles, texStorage2D
 * allocations). */
async function partSlots() {
  console.log("== the gene slots' lifecycle, through the real render path (synthetic snapshots of a 2,048-fish world)");
  const c = caseFor(2048);
  const L = await launch("slots", { init: INTERCEPT });
  await L.page.goto(benchUrl(c));
  await ready(L.page, true);
  await L.page.evaluate((cd) => EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", colourMode: "appearance", settleMs: 300 })), c);
  const r = await L.page.evaluate(async () => {
    const B = EvoOcean.bench, S = EvoOcean.scene, ST = 63, out = { steps: {} };
    const base = B.snapshotCopy(), nb = base.n;
    let maxId = 0; for (let i = 0; i < nb; i++) maxId = Math.max(maxId, base.ids[i]);
    let synth = null;
    const orig = S.render;
    S.render = function (s, inf) { return orig.call(this, synth ? Object.assign({}, s, synth) : s, Object.assign({}, inf, { selIdx: -1 })); };
    /* a snapshot of list's fish: [base fish to copy the body / place from, its id, its genes' variant (0: the base fish's own)] */
    function make(list, epoch) {
      const n = list.length, f = { n, worldEpoch: epoch, ids: new Float64Array(n), app: new Float32Array(n * ST), body: new Float32Array(2 * n),
                                   segs: new Float32Array(12 * n), depth: new Float32Array(n), colors: new Uint8Array(3 * n), vz: new Float32Array(n) };
      list.forEach(([from, id, v], k) => {
        f.ids[k] = id; f.depth[k] = base.depth[from];
        f.body[2 * k] = base.body[2 * from]; f.body[2 * k + 1] = base.body[2 * from + 1];
        for (let j = 0; j < 12; j++) f.segs[12 * k + j] = base.segs[12 * from + j];
        for (let j = 0; j < ST; j++) { const g = base.app[ST * from + j]; f.app[ST * k + j] = v ? Math.fround(((g * 0.61 + 0.173 * v + 0.0137 * j) % 1)) : g; }
        f.colors[3 * k] = (id * 37) & 255; f.colors[3 * k + 1] = (id * 91) & 255; f.colors[3 * k + 2] = (id * 13) & 255;
      });
      return f;
    }
    const io = () => { const g = S.geneTexture(); return { uploads: g.uploads, calls: g.calls, bytes: g.bytes, allocs: g.allocs, tex: g.texture, cap: g.capacity, slots: g.slots }; };
    /* show snapshot f for k frames; the gene uploads it caused; the probe against it; each fish's slot */
    async function show(name, f, k, probe = true) {
      const a = io();
      window.__up.reset(); window.__up.on = true;
      synth = f;
      await B.frames(k);
      window.__up.on = false;
      const b = io(), slots = S.geneSlots();
      const t = probe ? await B.textureParity({ expected: { worldEpoch: f.worldEpoch, n: f.n, ids: f.ids, app: f.app, body: f.body } }) : null;
      const st = { n: f.n, uploads: b.uploads - a.uploads, calls: b.calls - a.calls, bytes: b.bytes - a.bytes, allocs: b.allocs - a.allocs,
                   sameTexture: a.tex === b.tex, capacity: b.cap, owners: b.slots.owners, nextSlot: b.slots.nextSlot,
                   intercepted: { calls: window.__up.n, bytes: window.__up.bytes, allocs: window.__up.allocs, rects: window.__up.rects.slice(0, 12) },
                   drawn: S.appearance().shapes, status: S.appearance().status,
                   probe: t && { ok: t.ok, error: t.error, failures: t.failures, mismatches: t.rawGenes && t.rawGenes.mismatches, padding: t.rawGenes && t.rawGenes.paddingMismatches,
                                 extraUploads: t.extraUploads, p999: t.intrinsic && t.intrinsic.p999, chartedSlots: t.intrinsic && t.intrinsic.slots } };
      out.steps[name] = st;
      return { st, slots };
    }
    const E = base.worldEpoch, all = Array.from({ length: nb }, (_, i) => [i, base.ids[i], 0]);
    const slotOfId = (slots, f) => { const m = new Map(); for (let k = 0; k < f.n; k++) m.set(f.ids[k], slots[k]); return m; };
    /* 0. the real world itself, as the page draws it */
    let f0 = make(all, E), s0 = await show("same", f0, 6);
    const own0 = slotOfId(s0.slots, f0);
    out.identity = s0.slots.every((x, k) => x === k);
    /* 1. reversed: every fish keeps its slot, nothing uploaded */
    let f1 = make(all.slice().reverse(), E), s1 = await show("reversed", f1, 4);
    out.reversedKeeps = Array.from(f1.ids).every((id, k) => s1.slots[k] === own0.get(id));
    /* 2. one died, one born (other genes): the birth takes the freed slot, 256 bytes */
    const gone = 700, born = maxId + 1;
    let list2 = all.filter((x) => x[0] !== gone).concat([[gone, born, 1]]), f2 = make(list2, E), s2 = await show("oneReplaced", f2, 4);
    out.bornSlot = s2.slots[f2.n - 1]; out.goneSlot = own0.get(base.ids[gone]);
    /* 3. the owners of slots 31, 32, 63, 64 replaced: four ranges, one per side of the rows */
    const own2 = slotOfId(s2.slots, f2), bySlot = new Map(); own2.forEach((s, id) => bySlot.set(s, id));
    const kill = new Set([31, 32, 63, 64].map((s) => bySlot.get(s)));
    let list3 = list2.filter((x) => !kill.has(x[1])).concat([[10, born + 1, 2], [11, born + 2, 2], [12, born + 3, 2], [13, born + 4, 2]]);
    let f3 = make(list3, E), s3 = await show("rowPairs", f3, 4);
    /* 4. 2,048 -> 2,049: one growth (4,096 slots), one whole upload; -> 2,500: the new slots only */
    let list4 = list3.concat([[20, born + 5, 3]]), f4 = make(list4, E), s4a = await show("grow2049", f4, 4);
    const own4 = slotOfId(s4a.slots, f4);
    out.survivorsKept = Array.from(f3.ids).every((id) => own4.get(id) === slotOfId(s3.slots, f3).get(id));
    let list5 = list4.concat(Array.from({ length: 451 }, (_, k) => [(k * 7) % nb, born + 6 + k, 4])), f5 = make(list5, E), s5 = await show("to2500", f5, 4);
    /* 5. the owners of slots 2047 and 2048 replaced: two ranges, rows 63 and 64 */
    const own5 = slotOfId(s5.slots, f5), by5 = new Map(); own5.forEach((s, id) => by5.set(s, id));
    const kill5 = new Set([2047, 2048].map((s) => by5.get(s)));
    let list6 = list5.filter((x) => !kill5.has(x[1])).concat([[30, born + 500, 5], [31, born + 501, 5]]), f6 = make(list6, E), s6 = await show("pair2047", f6, 4);
    /* 6. shrink to 1,000, refill to 2,500 with new fish: freed slots reused, no growth, survivors in place */
    let list7 = list6.filter((x, k) => k % 5 < 2), f7 = make(list7, E), s7 = await show("shrink", f7, 4);
    out.shrinkKeeps = Array.from(f7.ids).every((id, k) => s7.slots[k] === slotOfId(s6.slots, f6).get(id));
    let list8 = list7.concat(Array.from({ length: f6.n - f7.n }, (_, k) => [(k * 11) % nb, born + 1000 + k, 6])), f8 = make(list8, E), s8 = await show("refill", f8, 4);
    /* 7. quality 3 -> 2 -> 1 -> 3 and the colour modes: the same texture, the same owners, no upload */
    const q0 = io();
    for (const q of [2, 1, 3]) { S.setQuality(q); await B.frames(3); }
    for (const m of [false, true]) { S.setAppearance(m); await B.frames(3); }
    const q1 = io();
    out.qualityColour = { uploads: q1.uploads - q0.uploads, allocs: q1.allocs - q0.allocs, sameTexture: q0.tex === q1.tex, quality: S.quality(), slotsSame: S.geneSlots().every((x, k) => x === s8.slots[k]) };
    const sq = await show("afterQuality", f8, 3);
    /* 8. a frame not drawn (uploads held) while fish are born: nothing lost, the next upload covers them */
    S.testFaults.holdGeneUploads = true;
    let list9 = list8.concat([[40, born + 3000, 7], [41, born + 3001, 7]]), f9 = make(list9, E);
    await show("held", f9, 3, false);
    let list10 = list9.concat([[42, born + 3002, 7]]), f10 = make(list10, E);
    synth = f10; await B.frames(2);
    S.testFaults.holdGeneUploads = false;
    await show("released", f10, 3);
    /* 9. the dirty uploads' texture == the whole-texture policy's, word for word */
    const dirtyW = await B.textureParity({ expected: { worldEpoch: f10.worldEpoch, n: f10.n, ids: f10.ids, app: f10.app, body: f10.body }, rawWords: true });
    S.setGeneUploads("full"); await B.frames(3);
    const fullIo0 = io(); await B.frames(6); const fullIo1 = io();
    const fullW = await B.textureParity({ expected: { worldEpoch: f10.worldEpoch, n: f10.n, ids: f10.ids, app: f10.app, body: f10.body }, rawWords: true });
    S.setGeneUploads("dirty"); await B.frames(3);
    const quiet0 = io(); await B.frames(6); const quiet1 = io();
    let diffWords = 0; for (let i = 0; i < f10.n * 64; i++) if (dirtyW.rawWords[i] !== fullW.rawWords[i]) diffWords++;
    out.dirtyVsFull = { words: f10.n * 64, differing: diffWords, dirtyOk: dirtyW.ok, fullOk: fullW.ok, fullUploads: fullIo1.uploads - fullIo0.uploads,
                        fullBytesPerUpload: (fullIo1.bytes - fullIo0.bytes) / Math.max(1, fullIo1.uploads - fullIo0.uploads), dirtyAgainUploads: quiet1.uploads - quiet0.uploads };
    /* 9b. a Turbo-like hand-back: every other fish replaced (births in freed slots all over the texture): one whole upload, not hundreds of ranges */
    const half = list10.filter((x, k) => k % 2 === 0);
    let listT = half.concat(Array.from({ length: list10.length - half.length }, (_, k) => [(k * 13) % nb, born + 5000 + k, 9])), fT = make(listT, E);
    await show("turnover", fT, 4);
    /* 9c. every fish's genes changed under its id (the engine never does this): found by the per-frame row check, every fish installed again */
    const rc0 = S.geneTexture().rowChanges;
    let fR = make(listT.map(([i, id, v]) => [i, id, v + 20]), E);
    await show("rowsChanged", fR, 4);
    out.rowChanges = S.geneTexture().rowChanges - rc0;
    /* 10. a new world's epoch with the same ids and other genes (a Restart): every fish new */
    let list11 = all.map(([i, id]) => [i, id, 8]), f11 = make(list11, E + 1000), s11 = await show("newEpoch", f11, 4);
    out.newEpochIdentity = s11.slots.every((x, k) => x === k);
    /* 11. a snapshot with a repeated id: refused, the plain fish drawn, no error; then a good one: every fish installed again */
    let f12 = make(all.slice(0, 100).concat([[5, base.ids[3], 0]]), E + 1000);
    const s12 = await show("repeatedId", f12, 3, false);
    let f13 = make(all.map(([i, id]) => [i, id, 8]), E + 1000), s13 = await show("afterRefusal", f13, 4);
    synth = null; S.render = orig; await B.frames(3);
    out.final = await B.textureParity();
    out.final = { ok: out.final.ok, failures: out.final.failures };
    return out;
  });
  report.parts.slots = r;
  const st = r.steps, P = (x) => x.probe && x.probe.ok === true && x.probe.mismatches === 0 && x.probe.padding === 0 && x.probe.extraUploads === 0;
  const none = (x) => x.uploads === 0 && x.calls === 0 && x.bytes === 0 && x.allocs === 0 && x.intercepted.calls === 0 && x.intercepted.allocs === 0;
  check("the real world (2,048 fish, a new epoch): identity slots, then nothing uploaded frame after frame; exact", r.identity && st.same.n === 2048 && none(st.same) && P(st.same), st.same);
  check("reversed draw order: every fish keeps its slot, no gene upload, exact", r.reversedKeeps && none(st.reversed) && P(st.reversed), st.reversed);
  check("one died, one born with other genes: the birth takes the freed slot; one upload, one call, 256 bytes (intercepted too), no allocation; exact",
        r.bornSlot === r.goneSlot && st.oneReplaced.uploads === 1 && st.oneReplaced.calls === 1 && st.oneReplaced.bytes === 256 && st.oneReplaced.intercepted.calls === 1 &&
        st.oneReplaced.intercepted.bytes === 256 && st.oneReplaced.allocs === 0 && P(st.oneReplaced), { born: r.bornSlot, gone: r.goneSlot, step: st.oneReplaced });
  const rects = JSON.stringify(st.rowPairs.intercepted.rects.slice().sort((a, b) => a[1] - b[1] || a[0] - b[0]));
  check("the owners of slots 31, 32, 63, 64 replaced: one upload of four ranges, each inside a texture row (496,0 / 0,1 / 496,1 / 0,2, 16 texels), 1 KiB; exact",
        st.rowPairs.uploads === 1 && st.rowPairs.calls === 4 && st.rowPairs.bytes === 1024 && rects === "[[496,0,16,1],[0,1,16,1],[496,1,16,1],[0,2,16,1]]" && P(st.rowPairs), { rects, step: st.rowPairs });
  check("2,048 -> 2,049: one growth to 4,096 slots (a new texture, one 512 x 128 RGBA32F allocation), one whole 1 MiB upload, every survivor's slot kept; exact",
        st.grow2049.capacity === 4096 && st.grow2049.allocs === 1 && st.grow2049.intercepted.allocs === 1 && !st.grow2049.sameTexture && st.grow2049.uploads === 1 &&
        st.grow2049.bytes === 1048576 && st.grow2049.intercepted.bytes === 1048576 && r.survivorsKept && P(st.grow2049), st.grow2049);
  check("  -> 2,500: no allocation, the 451 new slots only (451 x 256 bytes) in ranges; exact",
        st.to2500.allocs === 0 && st.to2500.sameTexture && st.to2500.uploads === 1 && st.to2500.bytes === 451 * 256 && st.to2500.intercepted.bytes === 451 * 256 &&
        st.to2500.calls === st.to2500.intercepted.calls && P(st.to2500), st.to2500);
  check("the owners of slots 2047 and 2048 replaced: two ranges, the ends of rows 63 and 64; exact",
        st.pair2047.calls === 2 && JSON.stringify(st.pair2047.intercepted.rects.slice().sort((a, b) => a[1] - b[1])) === "[[496,63,16,1],[0,64,16,1]]" && P(st.pair2047), st.pair2047);
  const whole = (x) => x.uploads === 1 && x.calls === 1 && x.bytes === 1048576 && x.intercepted.calls === 1 && x.intercepted.bytes === 1048576 && x.allocs === 0 && x.intercepted.allocs === 0;
  check("shrink to 1,000: no upload, no repacking (the survivors in place); refill to 2,500 (1,500 births: over an eighth of the texture): the freed slots reused, no growth, one whole upload; exact",
        r.shrinkKeeps && none(st.shrink) && P(st.shrink) && st.refill.capacity === 4096 && st.refill.nextSlot === st.shrink.nextSlot && whole(st.refill) && P(st.refill),
        { shrink: st.shrink, refill: st.refill });
  check("detail 3 -> 2 -> 1 -> 3 and the colours (skin off, on): the same gene texture and slots, no gene upload; exact after",
        r.qualityColour.uploads === 0 && r.qualityColour.allocs === 0 && r.qualityColour.sameTexture && r.qualityColour.quality === 3 && r.qualityColour.slotsSame && none(st.afterQuality) && P(st.afterQuality), r.qualityColour);
  check("uploads held for frames with births: nothing lost; released, one upload of the outstanding slots; exact",
        st.held.uploads === 0 && st.released.uploads === 1 && st.released.bytes === 3 * 256 && P(st.released), { held: st.held, released: st.released });
  check("the dirty uploads' texture == the whole-texture policy's, every word of every fish (both exact); the full policy uploads 1 MiB every frame, the dirty one nothing",
        r.dirtyVsFull.differing === 0 && r.dirtyVsFull.dirtyOk && r.dirtyVsFull.fullOk && r.dirtyVsFull.fullUploads >= 5 && r.dirtyVsFull.fullBytesPerUpload === 1048576 &&
        r.dirtyVsFull.dirtyAgainUploads === 0, r.dirtyVsFull);
  check("a Turbo-like turnover (every other fish replaced): one whole 1 MiB upload in one call (not hundreds of ranges), no allocation; exact",
        whole(st.turnover) && P(st.turnover), st.turnover);
  check("every fish's genes changed under its id: caught by the per-frame row check (review of #53, P3-4), every fish installed again (one whole upload); exact against the changed genes",
        r.rowChanges >= 1 && whole(st.rowsChanged) && P(st.rowsChanged), { rowChanges: r.rowChanges, step: st.rowsChanged });
  check("a new epoch with the same ids and other genes: every fish new (identity slots), one whole upload (no allocation); exact against the new genes",
        r.newEpochIdentity && whole(st.newEpoch) && P(st.newEpoch), st.newEpoch);
  check("a repeated id: refused, the plain fish drawn (no error); the good snapshot again: all reinstalled (one whole upload), exact",
        st.repeatedId.drawn === false && /refused/.test(st.repeatedId.status) && st.afterRefusal.drawn === true && whole(st.afterRefusal) && P(st.afterRefusal),
        { refused: { drawn: st.repeatedId.drawn, status: st.repeatedId.status }, after: st.afterRefusal });
  check("the real snapshot again: exact", r.final.ok === true, r.final);
  check("no console / page / network errors", L.errors.filter((e) => !/gene slots refused/.test(e)).length === 0, L.errors.slice(0, 5));
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

/* ---------------- a script the scene needs, missing ---------------- */
/* web/ocean_shaders.js, web/ocean_pose.js, both, web/ocean_scene_parity.js or
 * web/ocean_scene.js itself blocked (a route abort): the page does not start,
 * and its splash names the file (the scene's EvoOceanSceneMissing; without the
 * scene, ocean_scene.js). Then each of the first three throwing as it loads:
 * the splash says it failed to run */
async function partMissing() {
  console.log("== a script the 3-D scene needs, missing (blocked): the splash names it");
  for (const files of [["ocean_shaders"], ["ocean_pose"], ["ocean_shaders", "ocean_pose"], ["ocean_scene_parity"], ["ocean_scene"]]) {
    const label = "missing-" + files.join("+");
    const L = await launch(label);
    let blocked = 0;
    await L.ctx.route(new RegExp("/(" + files.join("|") + ")(\\.[0-9a-f]+)?\\.js(\\?.*)?$"), (r) => { blocked++; return r.abort(); });
    await L.page.goto(BASE + "/ocean.html?guide=0&intro=0&seed=7");
    await L.page.waitForFunction(() => /could not start/.test(document.body.textContent) || (window.EvoApp && EvoApp.ready === true), null, { timeout: 90000 });
    const r = await L.page.evaluate(() => ({ started: !!(window.EvoApp && EvoApp.ready === true), scene: !!window.EvoOceanScene,
                                             flag: window.EvoOceanSceneMissing === undefined ? null : window.EvoOceanSceneMissing,
                                             splash: (document.getElementById("splashstate") || {}).textContent || "" }));
    const want = (files.includes("ocean_scene") ? "ocean_scene.js" : files.map((f) => f + ".js").join(" and ")) + " missing";
    /* the blocked scripts' own failures, and the scene saying which, are expected; nothing else may fail */
    const other = L.errors.filter((e) => !files.some((f) => e.includes(f + ".")));
    report.parts[label] = Object.assign({ blocked, want, errors: L.errors }, r);
    check(files.map((f) => f + ".js").join(" + ") + " blocked: the page stops, its splash says \"" + want + "\"",
          !r.started && !r.scene && blocked === files.length && r.splash.includes(want), r);
    check("  no other console / page / network error", other.length === 0, other.slice(0, 5));
    await L.ctx.close();
  }
  /* a script that loads but throws as it runs (its own text served, a throw
   * planted just before it registers its namespace): the splash says it failed
   * to run, not that it is missing */
  const NS = { ocean_shaders: "EvoOceanShaders", ocean_pose: "EvoOceanPose", ocean_scene_parity: "EvoOceanSceneParity" };
  for (const f of Object.keys(NS)) {
    const label = "throws-" + f;
    const L = await launch(label);
    let planted = 0;
    await L.ctx.route(new RegExp("/" + f + "(\\.[0-9a-f]+)?\\.js(\\?.*)?$"), async (rt) => {
      const resp = await rt.fetch(), body = await resp.text(), at = "\n  root." + NS[f] + " = API;\n";
      if (body.split(at).length === 2) planted++;
      return rt.fulfill({ response: resp, body: body.replace(at, "\n  throw new Error(\"planted: " + f + ".js throws as it loads\");" + at) });
    });
    await L.page.goto(BASE + "/ocean.html?guide=0&intro=0&seed=7");
    await L.page.waitForFunction(() => /could not start/.test(document.body.textContent) || (window.EvoApp && EvoApp.ready === true), null, { timeout: 90000 });
    const r = await L.page.evaluate((ns) => ({ started: !!(window.EvoApp && EvoApp.ready === true), scene: !!window.EvoOceanScene,
                                               namespace: window[ns] === null ? "null" : typeof window[ns],
                                               flag: window.EvoOceanSceneMissing === undefined ? null : window.EvoOceanSceneMissing,
                                               splash: (document.getElementById("splashstate") || {}).textContent || "" }), NS[f]);
    const want = f + ".js failed to run";
    /* the planted throw, and the scene saying which, are expected; nothing else may fail */
    const other = L.errors.filter((e) => !e.includes(f + "."));
    report.parts[label] = Object.assign({ planted, want, errors: L.errors }, r);
    check(f + ".js throws as it loads: the page stops, its splash says \"" + want + "\"",
          !r.started && !r.scene && planted === 1 && r.namespace === "null" && r.flag === want && r.splash.includes(want), r);
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
    pf["vertex_" + m] = { appearance: r.appearance.ok, recolour: r.recolour.ok, polishAppearance: r.polish.appearance.ok, polishRecolour: r.polish.recolour.ok,
                          slots: [r.slots.permuted.ok, r.slots.sparse.ok], error: r.error,
                          worst: (r.appearance.templates && r.appearance.templates.medium.worst) || r.appearance.error };
    check("vertex mutation " + m + ": compiles, runs, fails both colour modes, plain and polished" + (m === "partW" ? "" : ", and both slot maps"),
          !r.error && r.appearance.ok === false && r.recolour.ok === false && r.fragment.ok === true &&
          r.polish.appearance.ok === false && r.polish.recolour.ok === false && r.polish.fragment.ok === true &&
          (m === "partW" || (r.slots.permuted.ok === false && r.slots.sparse.ok === false)), pf["vertex_" + m]);
  }
  /* the slot selector back on the draw index (before PR2): the identity map cannot see it, the permuted and sparse ones must */
  {
    const r = await L.page.evaluate(() => EvoOcean.scene.appearancePathCheck(null, null, { mutate: "drawIndex" }));
    pf.vertex_drawIndex = { identity: r.appearance.ok, permuted: r.slots.permuted.ok, sparse: r.slots.sparse.ok, error: r.error,
                            worst: r.slots.permuted.templates && r.slots.permuted.templates.medium.worst };
    check("vertex mutation drawIndex (genes by gl_InstanceID): compiles, runs; the identity map passes, the permuted and sparse slot maps fail",
          !r.error && r.appearance.ok === true && r.slots.permuted.ok === false && r.slots.sparse.ok === false, pf.vertex_drawIndex);
  }
  for (const m of ["swapRB", "branch"]) {
    const r = await L.page.evaluate((mm) => EvoOcean.scene.appearancePathCheck(null, null, { fsMutate: mm }), m);
    pf["fragment_" + m] = { fragment: r.fragment.ok, polishFragment: r.polish.fragment.ok, failures: r.fragment.failures, modes: r.fragment.modes, worst: r.fragment.worst, error: r.error };
    check("fragment mutation " + m + ": compiles, runs, fails, plain and polished",
          !r.error && r.fragment.ok === false && r.polish.fragment.ok === false && r.appearance.ok && r.recolour.ok && r.polish.appearance.ok && r.polish.recolour.ok && r.slots.ok, pf["fragment_" + m]);
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
  const r = await fr.evaluate(async (gateSrc) => {
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
    await wait(800);
    out.gate = EvoOcean.scene.poseOf ? await (0, eval)("(" + gateSrc + ")")("iframe 890x453, following") : null;
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
  }, GATE_CHECK.toString());
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
  if (r.gate) check("the swim polish's size weights in the embed (890 x 453 canvas rectangle, following) == the independent projection",
                    r.gate.nonFinite === 0 && r.gate.badRoll === 0 && r.gate.maxErr <= 4e-3 && r.gate.state.on === true,
                    { maxErr: r.gate.maxErr, worst: r.gate.worst, below: r.gate.below, mid: r.gate.mid, above: r.gate.above, canvas: r.gate.canvasCss, buffer: r.gate.drawingBuffer, focal: r.gate.focalCss });
  check("no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
  await L.ctx.close();
}

/* ---------------- the swim polish's size weights at other sizes and pixel ratios ---------------- */
async function partGate() {
  console.log("== the swim polish's size weights: DPR 3 and 2, whole and close, a resize");
  const c = caseFor(1500);
  report.parts.gate = {};
  for (const vp of [{ width: 390, height: 844, dpr: 3 }, { width: 1400, height: 900, dpr: 2 }]) {
    const label = vp.width + "x" + vp.height + "@" + vp.dpr;
    const L = await launch("gate-" + label, { viewport: { width: vp.width, height: vp.height }, dpr: vp.dpr });
    await L.page.goto(benchUrl(c));
    await ready(L.page, true);
    const res = {};
    for (const cam of ["whole", "follow"]) {
      await L.page.evaluate((cd) => EvoOcean.bench.prepare(cd), Object.assign({}, c, { camera: cam, colourMode: "appearance", settleMs: 1500 }));
      res[cam] = await L.page.evaluate(GATE_CHECK, label + " " + cam);
    }
    await L.page.setViewportSize({ width: vp.height, height: vp.width });   /* turned on its side */
    await L.page.evaluate(() => EvoOcean.bench.wait(1500));
    res.resized = await L.page.evaluate(GATE_CHECK, label + " resized to " + vp.height + "x" + vp.width + ", follow");
    report.parts.gate[label] = res;
    const all = [res.whole, res.follow, res.resized];
    check(label + ": size weights == the independent projection (|err| <= .004: 7-bit weights), finite, unit rolls: whole, follow, resized",
          all.every((g) => g.nonFinite === 0 && g.badRoll === 0 && g.maxErr <= 4e-3 && g.state.on === true),
          all.map((g) => ({ label: g.label, maxErr: g.maxErr, worst: g.worst, below: g.below, mid: g.mid, above: g.above, outside: g.outside, canvas: g.canvasCss, focal: g.focalCss })));
    check(label + ":   the drawing buffer is the canvas x min(DPR, 2) (detail 3), and the weights are in CSS px (the same focal length as CSS height x P[5] / 2)",
          all.every((g) => g.drawingBuffer[0] === Math.floor(Math.round(g.canvasCss[0]) * Math.min(g.dpr, 2)) && g.drawingBuffer[1] === Math.floor(Math.round(g.canvasCss[1]) * Math.min(g.dpr, 2))),
          all.map((g) => ({ canvas: g.canvasCss, buffer: g.drawingBuffer, dpr: g.dpr })));
    check(label + ":   the whole view: under 6 px or outside, none at 11; close up, fish in the 6 .. 11 ramp and above 11, the rest outside the view",
          res.whole.below > 0 && res.whole.above === 0 && res.follow.mid > 0 && res.follow.above > 0 && res.follow.outside > 0,
          { whole: [res.whole.below, res.whole.mid, res.whole.above, res.whole.outside], follow: [res.follow.below, res.follow.mid, res.follow.above, res.follow.outside] });
    check(label + ": no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
    await L.ctx.close();
  }
}

/* ---------------- the polish off draws main's image ---------------- */
/* The same paused frames on main's site (--main-base) and this one with the
 * polish off: one world per state, stepped to tick 180 (one stepToTick
 * sequence, so the predators' trails match), the clock frozen (animT 20), a
 * static camera, the flashlight's and the caustics' fades settled; the
 * canvas read back (RGBA8) right after the app's render. This site twice:
 * "fresh", the plain programs from the scene's creation (setPolish(false)
 * before its first frame: the polished ones never draw), which must be main's
 * image exactly; and "switched", the page as it opens (polished) switched
 * to plain after its first frames, which may differ from main's by 1 / 255
 * on a few pixels and no more (on this GPU, 24-30 px of one food particle's
 * additive glow in the Family and Brain close-ups after the polished
 * programs drew in Appearance colours; no fish pixel: the fish programs and
 * inputs are main's). Then the polish on (switched): it must differ where a
 * fish is close (the comparison can see it).
 * A main with the polish (after #48: its scene has setPolish; render PR2's
 * reference) is captured twice too: "main" as it opens (the polish on, its
 * default look) and "mainFresh" (plain from the start); then this site's
 * look as it opens ("switched" before it is switched off) must be main's
 * default look exactly, its plain programs from the start main's plain ones
 * exactly, and switched off within the 1 / 255 tolerance of mainFresh. */
const PLAIN_FROM_START = () => {
  Object.defineProperty(window, "EvoOceanScene", { configurable: true, get() { return undefined; }, set(v) {
    const c = v.create;
    v.create = function () { const sc = c.apply(this, arguments); if (sc && sc.setPolish) sc.setPolish(false); return sc; };
    Object.defineProperty(window, "EvoOceanScene", { value: v, writable: true, configurable: true });
  } });
};
const OFF_STATES = [
  { name: "appearance-whole", cfg: { appearance: 3, walls: true }, colour: "appearance", cam: "whole" },
  { name: "appearance-close-flashlight", cfg: { appearance: 3, walls: true }, colour: "appearance", cam: "close", beam: true },
  { name: "family-close", cfg: { appearance: 3, walls: true }, colour: "family", cam: "close" },
  { name: "brain-close", cfg: { appearance: 3, walls: true }, colour: "brain", cam: "close" },
  { name: "plain-bodies-close", cfg: { appearance: 0, walls: true }, colour: "family", cam: "close" },
  /* the close fish selected and the one nearest the view's centre hovered (render PR2's split copies their highlights into the lit draw) */
  { name: "appearance-close-select-hover", cfg: { appearance: 3, walls: true }, colour: "appearance", cam: "close", pickHover: true },
  { name: "predators-wrapping", cfg: { appearance: 3, walls: false, predatorCount: 4 }, colour: "appearance", cam: "whole" }
];
async function partOffImage() {
  console.log("== the polish off draws main's image, pixel for pixel (main " + MAIN_BASE + ")");
  if (!MAIN_BASE) { check("offimage: --main-base given", false); return; }
  const VP = { width: 1280, height: 720 }, got = { main: {}, mainFresh: {}, fresh: {}, switched: {} };
  report.parts.offimage = { viewport: VP, states: {} };
  const sites = ["main", "fresh", "switched"];
  let polishedMain = false;
  for (let si = 0; si < sites.length; si++) {
    const site = sites[si], ofMain = site === "main" || site === "mainFresh";
    const base = ofMain ? MAIN_BASE : BASE;
    const init = site === "fresh" || site === "mainFresh" ? "(" + AFTER_FRAME.toString() + ")(); (" + PLAIN_FROM_START.toString() + ")();" : AFTER_FRAME;
    const L = await launch("offimage-" + site, { viewport: VP, init });
    for (const st of OFF_STATES) {
      const c = caseFor(600, { config: Object.assign({}, st.cfg) });
      await L.page.goto(benchUrl(c, {}, base));
      await ready(L.page, true);
      const r = await L.page.evaluate(async ([st, cd, cand]) => {
        const B = EvoOcean.bench, S = EvoOcean.scene;
        const gl = document.getElementById("tank").getContext("webgl2"), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
        const grab = () => new Promise((res) => window.__after.push(() => {
          const px = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
          let s = ""; for (let i = 0; i < px.length; i += 0x8000) s += String.fromCharCode.apply(null, px.subarray(i, i + 0x8000));
          res(btoa(s));
        }));
        if (cand === "fresh") S.setPolish(false);   /* (the init's already) */
        const orig = S.render;
        S.render = function (s, inf) { return orig.call(this, s, Object.assign({}, inf, { animT: 20.0 })); };
        await B.prepare(Object.assign({}, cd, { camera: "whole", colourMode: st.colour, settleMs: 200 }));
        await B.stepToTick(180);
        const s = B.snapshotCopy(), wW = EvoOcean.state().W, wH = EvoOcean.state().H;
        let pick = -1;
        if (st.cam === "close") {
          for (let i = 0; i < s.n; i++) if (pick < 0 || s.ids[i] < s.ids[pick]) pick = i;
          const hp = (k) => [s.segs[12 * pick + 2 * k] - wW / 2, -s.depth[pick], s.segs[12 * pick + 2 * k + 1] - wH / 2];
          const h0 = hp(0), h2 = hp(2), mid = hp(1), fl = Math.hypot(h0[0] - h2[0], h0[2] - h2[2]) || 1, fx = (h0[0] - h2[0]) / fl, fz = (h0[2] - h2[2]) / fl;
          S.lookFrom([mid[0] - fz * 46 - fx * 8, mid[1] + 16, mid[2] + fx * 46 - fz * 8], mid);
        }
        S.setFlashlight(!!st.beam);
        /* the close fish selected; hovered (a mouse pointermove on its head), the fish nearest the camera whose head is on the
         * canvas (40 px in) and 40 px or more from every other fish's head on screen (so the pick is it) */
        let pickHover = null;
        if (st.pickHover) {
          await B.frames(3);   /* (project() uses the last drawn frame's camera: after lookFrom) */
          const cv = document.getElementById("tank"), rc = cv.getBoundingClientRect(), cam = S.view().pos;
          const scr = [];
          for (let i = 0; i < s.n; i++) scr.push(S.project(s, i));
          let hov = -1, best = Infinity;
          for (let i = 0; i < s.n; i++) {
            const p = scr[i];
            if (i === pick || !p || p.x < rc.left + 40 || p.x > rc.right - 40 || p.y < rc.top + 40 || p.y > rc.bottom - 40) continue;
            if (scr.some((q, j) => j !== i && q && Math.hypot(q.x - p.x, q.y - p.y) < 40)) continue;
            const d = Math.hypot(s.segs[12 * i] - wW / 2 - cam[0], -s.depth[i] - cam[1], s.segs[12 * i + 1] - wH / 2 - cam[2]);
            if (d < best) { best = d; hov = i; }
          }
          EvoOcean.select(pick);
          const hp = S.project(s, hov);
          cv.dispatchEvent(new PointerEvent("pointermove", { clientX: hp.x, clientY: hp.y, pointerType: "mouse", bubbles: true }));
          pickHover = { selected: pick, hovered: hov, at: [hp.x, hp.y] };
        }
        await B.wait(2600);   /* the caustics' and the flashlight's fades */
        await B.frames(4);
        const out = { n: EvoOcean.state().n, pc: EvoOcean.state().pc, tick: EvoOcean.state().frame, view: S.view(), size: [W, H],
                      polishApi: !!S.setPolish, appearance: S.appearance(), pickHover };
        if (pickHover) pickHover.hovering = document.getElementById("tank").style.cursor === "pointer";
        /* switched: the page as it opens (its default look), then switched to plain */
        if (cand === "switched") { out.polishOn0 = S.polish(); out.on0 = await grab(); S.setPolish(false); await B.wait(1500); await B.frames(4); }
        out.polish = S.polish ? S.polish() : null;
        out.off = await grab();
        if (cand === "switched") { S.setPolish(true); await B.wait(1500); await B.frames(4); out.polishOn = S.polish(); out.on = await grab(); }
        /* render PR2's split (opt-in: setLitSplit(true)): the same frame with the lit fish drawn apart */
        if (cand === "switched" && st.cam === "close" && S.setLitSplit) {
          S.setLitSplit(true); await B.wait(300); await B.frames(4); out.polishOnSplit = S.polish(); out.onSplit = await grab();
          if (pickHover) { const a = S.poseOf(pickHover.selected), b = S.poseOf(pickHover.hovered);
                           out.pickApart = { selected: { weight: a.pose[3], apart: a.apart }, hovered: { weight: b.pose[3], apart: b.apart } }; }
          S.setLitSplit(false); await B.frames(2);
        }
        S.render = orig;
        return out;
      }, [st, c, ofMain ? false : site]);
      got[site][st.name] = r;
    }
    check("offimage " + site + ": no console / page / network errors", L.errors.length === 0, L.errors.slice(0, 5));
    await L.ctx.close();
    if (site === "main" && Object.values(got.main).every((x) => x.polishApi)) { polishedMain = true; sites.splice(si + 1, 0, "mainFresh"); }
  }
  report.parts.offimage.polishedMain = polishedMain;
  function diff(a64, b64) {
    const a = Buffer.from(a64, "base64"), b = Buffer.from(b64, "base64");
    if (a.length !== b.length) return { sizeMismatch: [a.length, b.length] };
    let px = 0, max = 0;
    for (let i = 0; i < a.length; i += 4) {
      const m = Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2]), Math.abs(a[i + 3] - b[i + 3]));
      if (m) { px++; if (m > max) max = m; }
    }
    return { pixels: a.length / 4, differing: px, maxDiff: max, sha: [crypto.createHash("sha256").update(a).digest("hex").slice(0, 16), crypto.createHash("sha256").update(b).digest("hex").slice(0, 16)] };
  }
  const sameView = (m, c) => m.tick === c.tick && m.n === c.n && JSON.stringify(m.view) === JSON.stringify(c.view);
  const same = (m, c) => sameView(m, c) && c.polish && c.polish.on === false;
  for (const st of OFF_STATES) {
    /* m: main's plain image (pre-polish main as it is; a polished main's plain from the start) */
    const m = polishedMain ? got.mainFresh[st.name] : got.main[st.name], f = got.fresh[st.name], c = got.switched[st.name];
    const d0 = diff(m.off, f.off), d1 = diff(m.off, c.off), d2 = diff(m.off, c.on);
    report.parts.offimage.states[st.name] = { main: { tick: m.tick, n: m.n, pc: m.pc, view: m.view, appearance: m.appearance, polish: m.polish },
      fresh: { tick: f.tick, n: f.n, polish: f.polish }, switched: { tick: c.tick, n: c.n, pc: c.pc, view: c.view, polishOff: c.polish, polishOn: c.polishOn, polishOn0: c.polishOn0, appearance: c.appearance },
      mainVsFresh: d0, mainVsSwitched: d1, mainVsOn: d2 };
    if (polishedMain) {
      /* the default look: this page as it opens (the polish on) == main's as it opens */
      const md = got.main[st.name], dd = diff(md.off, c.on0);
      report.parts.offimage.states[st.name].mainDefault = { polish: md.polish, view: md.view };
      report.parts.offimage.states[st.name].defaultVsMain = dd;
      check("offimage " + st.name + ": the look as the page opens (the polish on) == main's, every RGBA8 pixel (tick " + md.tick + ", " + md.n + " fish, " + md.pc + " predators, same camera)",
            sameView(md, c) && md.polish && md.polish.on === true && c.polishOn0 && c.polishOn0.on === true && dd.differing === 0,
            Object.assign({ main: md.polish && { variant: md.polish.variant, lit: md.polish.any }, pr2: c.polishOn0 && { variant: c.polishOn0.variant, lit: c.polishOn0.any, split: c.polishOn0.split, apart: c.polishOn0.litDrawn } }, dd));
    }
    check("offimage " + st.name + ": the plain programs from the start == main" + (polishedMain ? "'s plain programs from the start" : "") + ", every RGBA8 pixel (tick " + m.tick + ", " + m.n + " fish, " + m.pc + " predators, same camera)",
          same(m, f) && d0.differing === 0, d0);
    check("offimage " + st.name + ":   switched off at run time: within 1 / 255, on under 0.01 % of the pixels", same(m, c) && d1.maxDiff <= 1 && d1.differing <= d1.pixels * 1e-4, d1);
    if (st.cam === "close") check("offimage " + st.name + ":   and the polish on differs (the comparison can see it)", c.polishOn.on === true && d2.differing > 0, d2);
    if (st.pickHover) {
      check("offimage " + st.name + ":   the same fish selected and hovered on every site (the pointer on it), both lit and drawn apart by the split",
            ["main", "fresh", "switched"].every((k) => got[k][st.name].pickHover && JSON.stringify(got[k][st.name].pickHover) === JSON.stringify(c.pickHover)) && c.pickHover.hovering &&
            c.pickApart && c.pickApart.selected.weight > 0 && c.pickApart.hovered.weight > 0 && c.pickApart.selected.apart >= 0 && c.pickApart.hovered.apart >= 0,
            { pick: c.pickHover, apart: c.pickApart });
    }
    if (st.cam === "close" && c.onSplit) {
      /* the lit fish apart (the opt-in split) vs the default, the whole kind on the full programs: an unlit fish looks the same on either */
      const d3 = diff(c.on, c.onSplit);
      report.parts.offimage.states[st.name].splitVsUnsplit = Object.assign({ split: { split: c.polishOnSplit.split, litDrawn: c.polishOnSplit.litDrawn, lit: c.polishOnSplit.any, fish: c.polishOnSplit.fish },
                                                                             unsplit: { split: c.polishOn.split, variant: c.polishOn.variant } }, d3);
      check("offimage " + st.name + ":   the polish on with the lit fish apart (setLitSplit(true)) == the default (the whole kind on the full programs), every RGBA8 pixel",
            (c.polishOnSplit.split === true || c.polishOnSplit.variant === "plain" || !(c.appearance && c.appearance.shapes)) && c.polishOn.split === false && d3.differing === 0,
            report.parts.offimage.states[st.name].splitVsUnsplit);
    }
  }
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
                        viewport: VIEWPORT, modes: PERF_MODES, cells: {} };
  for (const pop of COUNTS) {
    let c = caseFor(pop === "big" ? 300 : pop);
    const L = await launch("perf-" + pop, { viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, dpr: VIEWPORT.dpr });
    await L.page.goto(benchUrl(c));
    await ready(L.page, true);
    if (pop === "big") {   /* the page's own preset: its size, founders and set-up (appearance as the case's) */
      const B = await L.page.evaluate(() => EvoOceanConfig.BIG_TANK);
      c = caseFor(B.population, { world: [B.width, B.height, B.depth], config: Object.assign({}, CASES.benchmark.config, B.cfg) });
    }
    for (const cam of CAMERAS) for (const colour of COLOURS) {
      const key = `${pop}_${cam}_${colour}`;
      const prep = await L.page.evaluate((cd) => EvoOcean.bench.prepare(cd), Object.assign({}, c, { camera: cam, colourMode: colour }));
      save("manifest_" + key + ".json", JSON.stringify(await manifestOf(L.page, "perf-" + key, { browserVersion: L.browserVersion, case: prep, viewport: VIEWPORT }), null, 1));
      await L.page.evaluate((ms) => EvoOcean.bench.wait(ms), WARM);
      const rows = Object.fromEntries(PERF_MODES.map((m) => [m, []]));
      for (let round = 0; round < ROUNDS; round++) {
        const order = round % 2 ? PERF_MODES.slice().reverse() : PERF_MODES;
        for (const mode of order) {
          const r = await capture(L.page, mode, DUR);
          if (r.cap) { save(`frames_${key}_${mode}_${round}.csv`, r.cap.framesCsv); if (MODES[mode].gpu === "frame") save(`gpu_${key}_${mode}_${round}.csv`, r.cap.gpuCsv); }
          rows[mode].push({ raf: r.raf, summary: r.cap ? r.cap.summary : null });
          console.log(`  ${key} ${mode.padEnd(8)} r${round}: rAF fps ${r.raf.rafFps.toFixed(1)} p95 ${r.raf.raf.p95.toFixed(2)} ms` +
                      (r.cap ? `, frameCpu p50 ${r.cap.summary.spans.frameCpu.p50.toFixed(3)} p95 ${r.cap.summary.spans.frameCpu.p95.toFixed(3)} ms, fps ${r.cap.summary.fps.toFixed(1)}` : "") +
                      (r.cap && r.cap.summary.gpu.labels.frame ? `, gpu frame p50 ${r.cap.summary.gpu.labels.frame.scopes.p50.toFixed(3)} p95 ${r.cap.summary.gpu.labels.frame.scopes.p95.toFixed(3)} ms` : ""));
        }
      }
      /* draw scopes apart from frame timing (never combined) */
      const dr = await L.page.evaluate((ms) => EvoOcean.bench.capture({ durationMs: ms, cpu: true, gpu: "draws", sampleEvery: 6 }), Math.min(DUR, 10000));
      save(`gpu_${key}_draws.csv`, dr.gpuCsv);
      report.parts.perf.cells[key] = { fish: prep.n, world: prep.world, camera: cam, colour, case: prep.camera, rows, draws: dr.summary.gpu };
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

/* ---------------- performance by arms (--arms) ---------------- */
const ARM_MODE = { cpu: true, gpu: "frame", sampleEvery: 6 };
async function partPerfArms() {
  const siteOf = (arm) => (arm === "main" ? "main" : "cand");
  if (ARMS.includes("main") && !MAIN_BASE) { check("perf arms: main needs --main-base", false); return; }
  console.log("== performance by arms " + ARMS.join(" / ") + " (rounds " + ROUNDS + ", " + DUR + " ms each, warm " + WARM + " ms; viewport " + JSON.stringify(VIEWPORT) + ")");
  report.parts.perf = { mode: "arms", arms: ARMS, viewport: VIEWPORT, dur: DUR, warm: WARM, rounds: ROUNDS, mainBase: MAIN_BASE, base: BASE,
                        note: "Headless Brave, rAF-paced; arms alternate per round (order reversed on odd rounds), a fresh page per site and round", cells: {} };
  let big = null;
  for (const pop of COUNTS) for (const cam of CAMERAS) for (const colour of COLOURS) {
    const key = `${pop}_${cam}_${colour}`, cell = { fish: pop, camera: cam, colour, obs: [] };
    report.parts.perf.cells[key] = cell;
    for (let round = 0; round < ROUNDS; round++) {
      const order = round % 2 ? ARMS.slice().reverse() : ARMS.slice();
      for (let i = 0; i < order.length;) {
        const site = siteOf(order[i]), group = [];
        while (i < order.length && siteOf(order[i]) === site) group.push(order[i++]);
        const base = site === "main" ? MAIN_BASE : BASE;
        const L = await launch("perf-" + key + "-r" + round + "-" + site, { viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, dpr: VIEWPORT.dpr });
        let c = caseFor(pop === "big" ? 300 : pop);
        await L.page.goto(benchUrl(c, {}, base));
        await ready(L.page, true);
        if (pop === "big") {
          big = big || await L.page.evaluate(() => EvoOceanConfig.BIG_TANK);
          c = caseFor(big.population, { world: [big.width, big.height, big.depth], config: Object.assign({}, CASES.benchmark.config, big.cfg) });
        }
        const prep = await L.page.evaluate(async ([cd, cam]) => {
          const p = await EvoOcean.bench.prepare(Object.assign({}, cd, { camera: cam === "fit" ? "whole" : cam }));
          if (cam === "fit") { EvoOcean.scene.resetView(false); await EvoOcean.bench.wait(500); p.camera = { kind: "fit", view: EvoOcean.scene.view() }; }
          return p;
        }, [Object.assign({}, c, { colourMode: colour }), cam]);
        const assets = await L.page.evaluate(() => performance.getEntriesByType("resource").map((e) => e.name.replace(/^.*\//, "")).filter((n) => /\.[0-9a-f]{12}\.(js|wasm)$/.test(n)).sort());
        await L.page.evaluate((ms) => EvoOcean.bench.wait(ms), WARM);
        for (const arm of group) {
          const r = await L.page.evaluate(async ([arm, m, ms]) => {
            const S = EvoOcean.scene;
            if (arm !== "main") {   /* fullUp: the polish on, the whole gene texture uploaded every frame (PR2's slots, main's upload); split: the polish
                                       on, the lit fish drawn apart (setLitSplit(true): opt-in) */
              S.setPolish(arm === "on" || arm === "fullUp" || arm === "split" ? true : arm === "off" ? false : arm);
              if (S.setGeneUploads) S.setGeneUploads(arm === "fullUp" ? "full" : "dirty");
              if (S.setLitSplit) S.setLitSplit(arm === "split");
              await EvoOcean.bench.wait(2500);   /* a switch compiles once: settle */
            }
            const rp = EvoOcean.bench.rafProbe(ms), cap = EvoOcean.bench.capture(Object.assign({ durationMs: ms }, m));
            const out = { raf: await rp, cap: await cap };
            const gt = S.geneTexture ? S.geneTexture() : null;
            out.state = { polish: S.polish ? S.polish() : null, quality: S.quality(), dpr: devicePixelRatio, drawingBuffer: S.contextInfo().drawingBuffer,
                          view: S.view(), n: EvoOcean.state().n, tick: EvoOcean.state().frame, paused: EvoOcean.state().paused,
                          genes: gt ? { policy: gt.policy || "full (before PR2)", capacity: gt.capacity, uploads: gt.uploads, bytes: gt.bytes } : null };
            return out;
          }, [arm, ARM_MODE, DUR]);
          const tag = `${key}_${arm}_${round}`;
          save(`frames_${tag}.csv`, r.cap.framesCsv); save(`gpu_${tag}.csv`, r.cap.gpuCsv);
          const sm = r.cap.summary, g = sm.gpu.labels.frame ? sm.gpu.labels.frame.scopes : null;
          cell.obs.push({ arm, round, site, base, assets, prep: { n: prep.n, world: prep.world, camera: prep.camera, quality: prep.quality, colourMode: prep.colourMode },
                          state: r.state, raf: r.raf, summary: sm });
          console.log(`  ${key} ${arm.padEnd(7)} r${round}: rAF ${r.raf.rafFps.toFixed(1)} fps (p95 ${r.raf.raf.p95.toFixed(2)} ms, >25ms ${(100 * r.raf.over25ms).toFixed(1)}%)` +
                      `, frameCpu p50 ${sm.spans.frameCpu.p50.toFixed(3)} p95 ${sm.spans.frameCpu.p95.toFixed(3)}, fishPack p50 ${sm.spans.fishPack.p50.toFixed(3)}` +
                      (g ? `, gpu p50 ${g.p50.toFixed(3)} p95 ${g.p95.toFixed(3)} (valid ${(100 * sm.gpu.validFraction).toFixed(0)}%)` : ", no gpu") +
                      (r.state.polish ? `, polish ${r.state.polish.want}/${r.state.polish.variant || (r.state.polish.on ? "on" : "off")} lit ${r.state.polish.any}/${r.state.polish.fish} full ${r.state.polish.full}` +
                                        (r.state.polish.split !== undefined ? ` apart ${r.state.polish.split ? r.state.polish.litDrawn : "-"}` : "") : ", (main)") +
                      (r.state.genes ? `, genes ${r.state.genes.policy}` : ""));
        }
        check(`perf ${key} r${round} ${site}: no console / page / network errors`, L.errors.length === 0, L.errors.slice(0, 5));
        await L.ctx.close();
      }
    }
  }
}

const RUN = { correctness: partCorrectness, slots: partSlots, noperf: partNoPerf, missing: partMissing, faults: partFaults, timer: partTimer, beam: partBeam, iframe: partIframe,
              gate: partGate, offimage: partOffImage, perf: () => (ARMS ? partPerfArms() : partPerf()) };
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
