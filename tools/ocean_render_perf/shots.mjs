// tools/ocean_render_perf/shots.mjs: before / after pictures of the Ocean page under the render policies, and their differences
// (headless Brave, Playwright). The same paused world (seed 42, the benchmark case), the same camera, the animation clock frozen
// (the page's render wrapped to a fixed animT, as tests/ocean_render_browser.mjs's offimage part does), the framebuffer read back
// right after the page's own frame (rAF wrapped; RGBA8, bottom row first, flipped here); each arm sets the whole policy, awaits it
// (decoded programs compile first), settles, and grabs. Per cell (fish count x colour x camera) every arm is compared with the
// reference arm pixel for pixel: pixels differing, the largest channel difference, the mean absolute difference, and the bounding
// box of the differences; PNGs of the arms and of the differences (x16) are written for the cells and arms asked for.
//
//   node shots.mjs --base http://localhost:8182 --root REPO --out DIR [--counts 300,2000] [--colours appearance,family]
//        [--cameras whole,fit,dense,follow] [--arms ref,all,...] [--png ref,all] [--crop x,y,w,h] [--viewport 1400x900@1]
//
// arms (a policy each; ref is the reference pipeline's policy, in a scene that has the optimized one):
//   ref      lod quality, decoded off, barbels body
//   lod / cache / barb / lodCache / all   as in cycle.mjs
//   medium       every fish in the medium bucket (decoded off, barbels body): the bucket machinery alone: must equal ref
//   mediumCache  the same with the decoded cache: must equal cache
//   coarse       every fish in the coarse bucket (decoded off): equals the quality's coarse template (detail 2 draws it)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import zlib from "node:zlib";
import { acquire } from "./lock.mjs";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : (i >= 0 ? true : def); }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = String(arg("base", "http://localhost:8182")).replace(/\/$/, "");
const ROOT = path.resolve(String(arg("root", ".")));
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "render_shots_" + Date.now()))));
const COUNTS = String(arg("counts", "300,2000")).split(",").map(Number);
const COLOURS = String(arg("colours", "appearance,family")).split(",");
const CAMERAS = String(arg("cameras", "whole,fit,dense,follow")).split(",");
const ARMS = String(arg("arms", "ref,lod,cache,barb,all,medium,mediumCache")).split(",");
const PNG_ARMS = String(arg("png", "ref,all")).split(",").filter(Boolean);
const CROP = arg("crop", null) ? String(arg("crop")).split(",").map(Number) : null;
const QUERY = String(arg("query", ""));
const NAME = String(arg("name", "builder-render"));
const VIEWPORT = (() => { const m = /^(\d+)x(\d+)(?:@([\d.]+))?$/.exec(String(arg("viewport", "1400x900@1")));
  if (!m) throw new Error("--viewport WxH[@dpr]"); return { width: +m[1], height: +m[2], dpr: m[3] ? +m[3] : 1 }; })();
const CASES = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/ocean_render_cases.json"), "utf8"));
const { chromium } = require(PW);
fs.mkdirSync(OUT, { recursive: true });

const POL = {
  ref: { lod: "quality", decoded: false, barbels: "body" },
  lod: { lod: "screen", decoded: false, barbels: "body" },
  cache: { lod: "quality", decoded: true, barbels: "body" },
  barb: { lod: "quality", decoded: false, barbels: "gated" },
  lodCache: { lod: "screen", decoded: true, barbels: "body" },
  all: { lod: "screen", decoded: true, barbels: "gated" },
  medium: { lod: "medium", decoded: false, barbels: "body" },
  mediumCache: { lod: "medium", decoded: true, barbels: "body" },
  coarse: { lod: "coarse", decoded: false, barbels: "body" }
};
for (const a of ARMS) if (!POL[a]) throw new Error("unknown arm " + a);

/* a PNG (RGBA8, filter 0) */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(buf) { let c = 0xFFFFFFFF; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function chunk(type, data) { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; }
function png(w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 6 })), chunk("IEND", Buffer.alloc(0))]);
}
function crop(w, h, px, c) {
  if (!c) return { w, h, px };
  const [x0, y0, cw, ch] = c, out = new Uint8Array(cw * ch * 4);
  for (let y = 0; y < ch; y++) out.set(px.subarray(((y0 + y) * w + x0) * 4, ((y0 + y) * w + x0 + cw) * 4), y * cw * 4);
  return { w: cw, h: ch, px: out };
}
function diff(a, b) {
  let n = 0, max = 0, sum = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
  const W = a.w, img = new Uint8Array(a.px.length);
  for (let i = 0; i < a.px.length; i += 4) {
    const d = Math.max(Math.abs(a.px[i] - b.px[i]), Math.abs(a.px[i + 1] - b.px[i + 1]), Math.abs(a.px[i + 2] - b.px[i + 2]));
    sum += Math.abs(a.px[i] - b.px[i]) + Math.abs(a.px[i + 1] - b.px[i + 1]) + Math.abs(a.px[i + 2] - b.px[i + 2]);
    if (d) { n++; if (d > max) max = d; const p = i / 4, x = p % W, y = (p / W) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    const v = Math.min(255, d * 16); img[i] = v; img[i + 1] = v; img[i + 2] = v; img[i + 3] = 255;
  }
  return { pixels: a.px.length / 4, differing: n, maxDiff: max, meanAbs: sum / (a.px.length / 4 * 3), box: n ? [x0, y0, x1 - x0 + 1, y1 - y0 + 1] : null, img };
}

const INIT = () => {
  const raf = window.requestAnimationFrame.bind(window);
  window.__after = [];
  window.requestAnimationFrame = (cb) => raf((t) => { cb(t); if (cb.name === "frame" && window.__after.length) { const q = window.__after; window.__after = []; q.forEach((f) => f()); } });
};
async function launch(opts) {
  const ctx = await chromium.launchPersistentContext("", { executablePath: BRAVE, headless: true, viewport: opts.viewport, deviceScaleFactor: opts.dpr, reducedMotion: "no-preference",
                                                         args: ["--no-first-run", "--no-default-browser-check"] });
  await ctx.addInitScript(INIT);
  const page = ctx.pages()[0] || await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  page.on("requestfailed", (r) => errors.push("requestfailed: " + r.url()));
  page.on("response", (r) => { if (r.status() >= 400) errors.push("http " + r.status() + ": " + r.url()); });
  return { ctx, page, errors };
}
function benchUrl(c) {
  const q = new URLSearchParams({ renderBench: "1", guide: "0", intro: "0", seed: String(c.worldSeed), pop: String(c.population),
    w: String(c.world[0]), h: String(c.world[1]), depth: String(c.world[2]), speed: String(c.speed), colour: c.colourMode || "appearance",
    walls: c.config.walls ? "1" : "0", cfg: JSON.stringify(Object.assign({}, c.config, { walls: undefined })) });
  return BASE + "/ocean.html?" + q.toString() + (QUERY ? "&" + QUERY : "");
}

const summary = { started: new Date().toISOString(), base: BASE, viewport: VIEWPORT, arms: ARMS, cells: {}, errors: [] };
(async () => {
  for (const pop of COUNTS) for (const colour of COLOURS) {
    const release = await acquire(`${NAME} shots ${pop} ${colour}`);
    let L = null;
    try {
      L = await launch({ viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, dpr: VIEWPORT.dpr });
      const c = Object.assign({}, CASES.benchmark, { population: pop, colourMode: colour, config: Object.assign({}, CASES.benchmark.config) });
      await L.page.goto(benchUrl(c));
      await L.page.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && window.EvoOcean.bench, null, { timeout: 120000, polling: 200 });
      await L.page.evaluate(() => EvoOcean.bench.frames(10));
      /* the animation clock frozen for every grab */
      await L.page.evaluate(() => { const S = EvoOcean.scene, orig = S.render; S.render = function (s, inf) { return orig.call(this, s, Object.assign({}, inf, { animT: 20.0 })); }; });
      for (const cam of CAMERAS) {
        const key = `${pop}_${colour}_${cam}`, cell = { fish: pop, colour, camera: cam, arms: {} };
        summary.cells[key] = cell;
        const prep = await L.page.evaluate(async ([cd, camKind]) => {
          await EvoOcean.scene.setRenderOptimization({ lod: "quality", decoded: false, barbels: "body" });
          const p = await EvoOcean.bench.prepare(Object.assign({}, cd, { camera: camKind === "fit" ? "whole" : camKind, settleMs: 500 }));
          if (camKind === "fit") { EvoOcean.scene.resetView(false); await EvoOcean.bench.wait(500); }
          return { n: p.n, camera: p.camera.kind, view: EvoOcean.scene.view(), selected: p.camera.selectedId };
        }, [c, cam]);
        cell.view = prep.view; cell.n = prep.n;
        const px = {};
        for (const arm of ARMS) {
          const r = await L.page.evaluate(async ([pol, settle]) => {
            const S = EvoOcean.scene;
            const res = await S.setRenderOptimization(pol);
            await EvoOcean.bench.wait(settle);
            await EvoOcean.bench.frames(6);
            const gl = document.getElementById("tank").getContext("webgl2"), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
            const b64 = await new Promise((resolve) => window.__after.push(() => {
              const p = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, p);
              let s = ""; for (let i = 0; i < p.length; i += 0x8000) s += String.fromCharCode.apply(null, p.subarray(i, i + 0x8000));
              resolve(btoa(s));
            }));
            const st = S.renderOptimization();
            return { ok: res.ok, error: res.error, W, H, b64, effective: st.effective, buckets: st.buckets, barbels: st.barbels, appearance: S.appearance(), view: S.view(), tick: EvoOcean.state().frame };
          }, [POL[arm], arm === "ref" ? 300 : 1800]);
          const buf = Buffer.from(r.b64, "base64"), W = r.W, H = r.H, flip = new Uint8Array(W * H * 4);
          for (let y = 0; y < H; y++) flip.set(buf.subarray((H - 1 - y) * W * 4, (H - y) * W * 4), y * W * 4);
          px[arm] = { w: W, h: H, px: flip };
          cell.arms[arm] = { ok: r.ok, error: r.error, effective: r.effective, buckets: r.buckets, barbels: r.barbels, lod: r.appearance.lod, tick: r.tick, view: JSON.stringify(r.view) === JSON.stringify(prep.view) };
          console.log(`  ${key} ${arm.padEnd(11)} ${r.ok ? "ok" : "REFUSED " + r.error} effective ${JSON.stringify(r.effective)} buckets ${JSON.stringify(r.buckets)} barbels ${r.barbels}`);
        }
        const ref = px.ref || px[ARMS[0]];
        for (const arm of ARMS) {
          const d = diff(ref, px[arm]), rec = cell.arms[arm];
          rec.vsRef = { differing: d.differing, pixels: d.pixels, maxDiff: d.maxDiff, meanAbs: +d.meanAbs.toFixed(6), box: d.box };
          console.log(`  ${key} ${arm.padEnd(11)} vs ${ARMS[0]}: ${d.differing} px differ (${(100 * d.differing / d.pixels).toFixed(4)} %), max ${d.maxDiff}, mean ${d.meanAbs.toFixed(5)}${d.box ? ", box " + d.box.join("x") : ""}`);
          if (PNG_ARMS.indexOf(arm) >= 0) {
            const cc = crop(px[arm].w, px[arm].h, px[arm].px, CROP);
            fs.writeFileSync(path.join(OUT, `${key}_${arm}.png`), png(cc.w, cc.h, cc.px));
            if (arm !== ARMS[0]) { const dd = crop(px[arm].w, px[arm].h, d.img, CROP); fs.writeFileSync(path.join(OUT, `${key}_${arm}_diff16x.png`), png(dd.w, dd.h, dd.px)); }
          }
        }
        fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(summary, null, 1));
      }
      if (L.errors.length) { summary.errors.push({ pop, colour, errors: L.errors.slice(0, 10) }); console.log("  page messages:", L.errors.slice(0, 4)); }
    } finally {
      if (L) { try { await L.ctx.close(); } catch (e) { /* closed */ } }
      release();
    }
  }
  summary.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(summary, null, 1));
  console.log("done; output in " + OUT);
  process.exit(0);
})().catch((e) => { console.log("THREW " + (e && e.stack || e)); summary.threw = String(e && e.stack || e); fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(summary, null, 1)); process.exit(1); });
