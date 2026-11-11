// tests/ocean_body_gpu.mjs: the M2a body plan's CPU == GPU geometry check on the real fixture viewer, in
// headless Brave (Playwright), as tests/ocean_render_browser.mjs runs its checks.
//
//   python3 wasm/serve.py . 8123                   (the REPOSITORY root: the page reads ../tests/fixtures/)
//   node tests/ocean_body_gpu.mjs --base http://localhost:8123 [--page /web/ocean_bodyplan.html] [--headed]
//   env: PLAYWRIGHT  the playwright module (default C:/Users/harit/gemini_bridge/node_modules/playwright)
//        BRAVE_EXE   the browser (default C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe)
//
// web/ocean_bodyplan.html?check=1 runs, and leaves in window.__bodyPlanCheck:
//   native   every fixture body's rest points and birth coefficients from this page's Wasm module
//            (oc_body_rest, oc_body_preview) against the NATIVE fixture driver's digests
//            (tests/fixtures/ocean_body_fixture.json): bit for bit
//   slots    the renderer's GLSL (EvoAppearance.GLSL.MORPH, the production template's mDecode / mBuild) at
//            the canonical samples by transform feedback, gene slots identity / permuted / sparse (the
//            texture's row crossings), against the Wasm law's rest points: every output finite and within
//            the locked tolerance (EvoOceanSceneParity.BODY_TOL, body radii)
//   faults   each planted GLSL fault (radius: the depth law; root: a paired fin's root off its facet;
//            caudalClip: the chord cap raised) must FAIL the same check
// and then, through the REAL page controller (web/ocean.html, its snapshot -> the scene), with non-unit
// inherited bodies (bodyModel, bodyMutation .4, 1,500 steps) and the preview off, then on:
//   page     every drawn fish's radius and lambda (scene.poseOf, as the frame uploaded them) are the ones
//            its module row gives (oc_body_params: R = 4.6 bodyScale(S), lambda = 20 S E / R), all finite:
//            the snapshot's `body` stays the size / elongation pairs, never the diagnostics (round 1,
//            finding 1: a second `body` key in snapshot() overwrote them). With the preview on, the card's
//            body plan shows; off, it does not
// Exit 0 = every check passed. Browser-only; not in CI.
import { createRequire } from "module";
import fs from "fs";
import os from "os";
import path from "path";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : (i >= 0 ? true : def); }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = String(arg("base", "http://localhost:8123")).replace(/\/$/, "");
const PAGE = String(arg("page", "/web/ocean_bodyplan.html"));
const HEADED = !!arg("headed", false);
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "ocean_body_gpu_" + Date.now() + ".json"))));
const { chromium } = require(PW);

let fails = 0;
function check(name, cond, info) {
  console.log((cond ? "  ok   " : "  FAIL ") + name + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 500) : ""));
  if (!cond) fails++;
}
const ctx = await chromium.launchPersistentContext("", { executablePath: BRAVE, headless: !HEADED, viewport: { width: 1400, height: 900 },
  args: ["--no-first-run", "--no-default-browser-check"] });
const page = ctx.pages()[0] || await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("response", (r) => { if (r.status() >= 400) errors.push("http " + r.status() + ": " + r.url()); });
try {
  await page.goto(BASE + PAGE + "?check=1", { waitUntil: "load" });
  await page.waitForFunction(() => window.__bodyPlanCheck && (window.__bodyPlanCheck.ok !== undefined), null, { timeout: 120000 });
  const r = await page.evaluate(() => window.__bodyPlanCheck);
  const gl = await page.evaluate(() => { const g = document.createElement("canvas").getContext("webgl2"); if (!g) return null;
    const d = g.getExtension("WEBGL_debug_renderer_info"); return { renderer: d ? g.getParameter(d.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER), version: g.getParameter(g.VERSION) }; });
  fs.writeFileSync(OUT, JSON.stringify({ gl, result: r, errors }, null, 1));
  console.log("GPU: " + JSON.stringify(gl) + "\nreport: " + OUT);
  check("the check ran", !r.error, r.error);
  if (!r.error) {
    check("native == Wasm (every fixture body's rest points, birth and loaded coefficients, bit for bit)", r.native && r.native.ok,
          r.native && { bodies: r.native.bodies, rest: r.native.restMismatch.slice(0, 5), metrics: r.native.metricsMismatch.slice(0, 5),
                        loaded: (r.native.loadedMismatch || ["(not compared)"]).slice(0, 5) });
    ["identity", "permuted", "sparse"].forEach((sm) => {
      const x = r.slots[sm] || {};
      check("GPU == C++ at the canonical samples, slots " + sm, x.ok === true,
            { worst: x.worst, at: x.worstAt, tol: x.tol, nonFinite: x.nonFinite, vertices: x.vertices, maxSlot: x.maxSlot, error: x.error,
              parts: x.parts && Object.fromEntries(Object.entries(x.parts).map(([k, v]) => [k, Number(v.worst.toExponential(2))])) });
    });
    Object.keys(r.faults || {}).forEach((f) => check("planted fault " + f + " is caught", r.faults[f].caught, r.faults[f]));
    check("three planted faults", Object.keys(r.faults || {}).length === 3);
  }
  check("no page errors", errors.length === 0, errors.slice(0, 5));

  // ---- the real page controller, preview off and on ----
  for (const preview of [false, true]) {
    const label = "page, preview " + (preview ? "on" : "off");
    errors.length = 0;
    const cfg = Object.assign({ bodyModel: true, bodyMutation: 0.4 }, preview ? { bodyPlanPreviewEnabled: true } : {});
    await page.goto(BASE + "/web/ocean.html?guide=0&intro=0&seed=11&pop=200&cfg=" + encodeURIComponent(JSON.stringify(cfg)), { waitUntil: "load" });
    await page.waitForFunction(() => window.EvoOcean && EvoOcean.state && EvoOcean.state() && EvoOcean.state().n > 0, null, { timeout: 60000 });
    await page.evaluate(() => { EvoOcean.module._oc_step(1500); });   /* births: inherited, non-unit sizes */
    await page.waitForTimeout(800);   /* the page's own frames step, sync, snapshot and draw */
    await page.evaluate(() => { const b = document.getElementById("pausebtn"); if (b && !EvoOcean.state().paused) b.click(); });
    await page.waitForFunction(() => EvoOcean.state().paused === true, null, { timeout: 10000 });
    await page.waitForTimeout(500);   /* a few paused frames: the last snapshot drawn again */
    const r = await page.evaluate(() => {
      const M = EvoOcean.module, n = M._oc_creature_count(), S = EvoOcean.scene;
      const bp = new Float32Array(M.HEAPU8.buffer, M._oc_body_params(), 2 * n);
      const f = Math.fround, scale = (b) => (b > 0 ? 1 + 0.4 * Math.tanh(5 * (b - 1)) : 1);
      let nonUnit = 0, nonFinite = 0, worstR = 0, worstLam = 0, at = -1;
      for (let i = 0; i < n; i++) {
        const s = bp[2 * i], e = bp[2 * i + 1], p = S.poseOf(i);
        if (s !== 1 || e !== 1) nonUnit++;
        if (!Number.isFinite(p.R) || !Number.isFinite(p.lam)) { nonFinite++; continue; }
        const R = f(4.6 * scale(s)), lam = f(20 * s * e / R);
        const eR = Math.abs(p.R - R) / R, eL = Math.abs(p.lam - lam) / lam;
        if (eR > worstR) { worstR = eR; at = i; }
        if (eL > worstLam) worstLam = eL;
      }
      EvoOcean.select(0);
      return { n, nonUnit, nonFinite, worstR, worstLam, at, preview: M._oc_body_plan_enabled(), bodyRows: M._oc_body_count() };
    });
    await page.waitForTimeout(400);
    const cardShown = await page.evaluate(() => { const b = document.getElementById("ibody"); return !!b && !b.hidden && /not calibrated/.test(b.innerText); });
    check(label + ": the module's preview state", r.preview === (preview ? 1 : 0) && r.bodyRows === (preview ? r.n : 0), { preview: r.preview, rows: r.bodyRows, n: r.n });
    check(label + ": inherited non-unit bodies exist", r.nonUnit > 0, { nonUnit: r.nonUnit, n: r.n });
    check(label + ": every drawn fish's radius and lambda are its module row's (snapshot body = size / elongation)",
          r.nonFinite === 0 && r.worstR < 1e-6 && r.worstLam < 1e-5, r);
    check(label + ": the card's body plan " + (preview ? "shows" : "stays hidden"), cardShown === preview, { cardShown });
    check(label + ": no page errors", errors.length === 0, errors.slice(0, 5));
  }
} catch (e) {
  check("the page ran", false, String(e && e.message || e));
} finally {
  await ctx.close();
}
console.log(fails ? "BODY GPU CHECK: " + fails + " FAILED" : "BODY GPU CHECK: all passed");
process.exit(fails ? 1 : 0);
