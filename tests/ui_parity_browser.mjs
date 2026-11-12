// tests/ui_parity_browser.mjs: the UI parity plan's paired browser harness (docs/ui_parity.md). Classic and the Ocean in the same
// state, one case at a time, each world in a fresh headless Brave (a temporary profile: clean storage) under the machine-wide
// browser lock (tools/ocean_render_perf/lock.mjs), with full-page screenshots that include the DOM chrome (not the WebGL
// framebuffer alone). A local tool, not a CI job (CI has no browser); the cases are tests/fixtures/ui_parity_cases.json.
//
//   node tests/ui_parity_browser.mjs --base http://localhost:8123 --out DIR [--layout source|site] [--sets S0,S2]
//        [--cases s0_shell,...] [--worlds classic,ocean] [--name WHO] [--smoke] [--headed] [--list]
//   node tests/ui_parity_browser.mjs --compare BEFORE_DIR AFTER_DIR [--out DIFF_DIR]
//
// --layout source (the default): --base serves the repository root (python3 wasm/serve.py, its default root), so Classic is
//          /web/index.html and the Ocean /web/ocean.html (and Classic's ../img/rocks.jpg resolves). --layout site: --base serves
//          a built site (bash wasm/build_site.sh; SITE_DIR=/x), so Classic is /classic.html and the Ocean /; --smoke there also
//          loads the Ocean's old name /ocean.html. Never /index.html for Classic: on the site that is the Ocean.
// --smoke (alone: only these; with --sets / --cases: those cases too): each route loaded as a visitor would (no held clock), its
//          ready state, no console error / warning, page error,
//          failed request or HTTP error; one picture each.
// --compare: the same-named PNGs of two runs (before / after), pixel for pixel: pixels differing, the largest channel
//          difference, the box of the differences; a x16 difference picture for each that differs (into --out). Exit 0.
//
// The state (the plan's capture rules): seed 42 and 300 founders on both pages (Classic ignores setup URL parameters: its own
// form's seed and population fields and its Restart; the Ocean: its link's seed= and pop=), Classic's single-threaded module
// (?threads=0: the reproducible one), no tour (?guide=0&intro=0). The page's animation frames are held from the start, so the
// new world waits at tick 0; a case's "run" step lets the page's own frame loop go at speed 1 (one step a frame) and, after the
// frame that reaches the tick, presses the page's own Pause button ("pause") or holds the frames there ("freeze": the live UI).
// Then the same pictures are possible on any commit:
//   - the clock: performance.now() and the frames' timestamps advance exactly 1/60 s per animation frame (a frame-locked clock):
//     the frame rate reads 60, no governor (Hold 60 fps, Classic's detail / cap) ever acts, camera eases end the same way
//   - the frames: held between steps; a step that needs the page to draw lets an exact number run (settle), so every run of a
//     case draws the same frames (the live numbers' half-second refresh included)
//   - the animation time: each scene's render gets a fixed animT (both scenes' create(), wrapped as they register)
//   - the visual RNG: Math.random is a seeded xorshift32 (snow, streaks; nothing in a case draws a seed from it)
//   - fonts loaded (document.fonts.ready), the CSS animations and transitions finished (the screenshot's animations: disabled),
//     the caret hidden, the 9 s "click a fish" hint and every toast gone before a picture (a shot's toasts: "keep" keeps them)
//   - locale en-US, timezone UTC, DPR and viewport from the case (1440 x 900 at 1 by default), prefers-reduced-motion off
// Numerical claims belong in node tests, not in these pictures.
//
// Steps (a case's "steps"; "world" limits a step to one world; "sel" is a selector or {classic, ocean}):
//   run {tick, then: pause|freeze}   the frame loop to the tick, as above
//   pause                            the page's Pause pressed (if it runs), then settle
//   release / freeze                 the frames let go with no count (not reproducible: not before a shot) / held
//   settle {frames}                  exactly that many frames (the default's settleFrames), then held
//   select                           a fish selected through the page: Classic's EvoApp.inspectSomeFish (the fish nearest
//                                    (0.4 W, 0.45 H)), the Ocean's EvoOcean.select of the fish nearest the same point (plan view)
//   click {sel}                      a pointer's click at the element (Playwright: a real mouse press; :focus-visible off)
//   press {sel}                      element.click(): a click no pointer made (detail 0)
//   key {key, times}                 a key pressed where the focus is (Playwright's keyboard)
//   tabTo {sel, max}                 Tab pressed until the focus is on the element (the keyboard's way there: its ring shows)
//   focus {sel} / blur               element.focus() / the focused element's blur()
//   wait {ms}                        real time (a CSS transition)
//   shot {name, toasts}              the picture, CASE__WORLD__NAME.png, and the page's state then (summary.json)
// Output: DIR/*.png, DIR/summary.json (per case and world: the URL, the build's asset names, every shot's state, the page's
// errors), DIR/index.md (case -> world -> shot -> file -> state).
//
//   env: PLAYWRIGHT  the playwright module (default C:/Users/harit/gemini_bridge/node_modules/playwright)
//        BRAVE_EXE   the browser (default C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe)
//        BROWSER_LOCK the lock file (lock.mjs; default: the machine-wide one)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import { acquire } from "../tools/ocean_render_perf/lock.mjs";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function arg(name, def) {
  const i = args.indexOf("--" + name);
  if (i < 0) return def;
  return i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : true;
}
const list = (v) => (v === undefined || v === true ? null : String(v).split(",").map((x) => x.trim()).filter(Boolean));

/* ---------------- PNG (8-bit RGB / RGBA, not interlaced: what the browser writes) ---------------- */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(buf) { let c = 0xFFFFFFFF; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function chunk(type, data) { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; }
function encodePng(w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 6 })), chunk("IEND", Buffer.alloc(0))]);
}
function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let off = 8, w = 0, h = 0, depth = 0, type = 0, lace = 0;
  const idat = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off), t = buf.toString("ascii", off + 4, off + 8), d = buf.subarray(off + 8, off + 8 + len);
    if (t === "IHDR") { w = d.readUInt32BE(0); h = d.readUInt32BE(4); depth = d[8]; type = d[9]; lace = d[12]; }
    else if (t === "IDAT") idat.push(d);
    else if (t === "IEND") break;
    off += 12 + len;
  }
  if (depth !== 8 || lace !== 0 || (type !== 6 && type !== 2)) throw new Error("PNG kind not handled (depth " + depth + ", colour type " + type + ", interlace " + lace + ")");
  const bpp = type === 6 ? 4 : 3, stride = w * bpp, raw = zlib.inflateSync(Buffer.concat(idat)), px = new Uint8Array(w * h * 4);
  let prev = new Uint8Array(stride), cur = new Uint8Array(stride);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0, x = line[i];
      let v;
      if (f === 0) v = x; else if (f === 1) v = x + a; else if (f === 2) v = x + b; else if (f === 3) v = x + ((a + b) >> 1);
      else if (f === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); v = x + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c); }
      else throw new Error("PNG filter " + f);
      cur[i] = v & 255;
    }
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      px[o] = cur[x * bpp]; px[o + 1] = cur[x * bpp + 1]; px[o + 2] = cur[x * bpp + 2]; px[o + 3] = bpp === 4 ? cur[x * bpp + 3] : 255;
    }
    const t = prev; prev = cur; cur = t;
  }
  return { w, h, px };
}
function diffImages(a, b) {
  if (a.w !== b.w || a.h !== b.h) return { sizeDiffers: true, a: [a.w, a.h], b: [b.w, b.h] };
  let n = 0, max = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
  const img = new Uint8Array(a.px.length);
  for (let i = 0; i < a.px.length; i += 4) {
    const d = Math.max(Math.abs(a.px[i] - b.px[i]), Math.abs(a.px[i + 1] - b.px[i + 1]), Math.abs(a.px[i + 2] - b.px[i + 2]));
    if (d) { n++; if (d > max) max = d; const p = i / 4, x = p % a.w, y = (p / a.w) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    const v = Math.min(255, d * 16); img[i] = v; img[i + 1] = v; img[i + 2] = v; img[i + 3] = 255;
  }
  return { pixels: a.px.length / 4, differing: n, maxDiff: max, box: n ? [x0, y0, x1 - x0 + 1, y1 - y0 + 1] : null, img, w: a.w, h: a.h };
}

/* ---------------- --compare ---------------- */
if (arg("compare") !== undefined) {
  const i = args.indexOf("--compare"), A = args[i + 1], B = args[i + 2], OUTD = arg("out", null);
  if (!A || !B || A.startsWith("--") || B.startsWith("--")) { console.error("usage: --compare BEFORE_DIR AFTER_DIR [--out DIFF_DIR]"); process.exit(2); }
  if (OUTD && OUTD !== true) fs.mkdirSync(OUTD, { recursive: true });
  const names = fs.readdirSync(A).filter((f) => f.endsWith(".png") && fs.existsSync(path.join(B, f))).sort();
  const only = (d, e) => fs.readdirSync(d).filter((f) => f.endsWith(".png") && !fs.existsSync(path.join(e, f)));
  const rows = [];
  for (const f of names) {
    const d = diffImages(decodePng(fs.readFileSync(path.join(A, f))), decodePng(fs.readFileSync(path.join(B, f))));
    rows.push({ file: f, ...d, img: undefined });
    console.log((d.sizeDiffers ? "  SIZE " : d.differing ? "  diff " : "  same ") + f + (d.sizeDiffers ? "  " + d.a.join("x") + " vs " + d.b.join("x")
      : d.differing ? "  " + d.differing + " px (" + (100 * d.differing / d.pixels).toFixed(3) + " %), max " + d.maxDiff + ", box " + d.box.join(",") : ""));
    if (OUTD && OUTD !== true && d.differing) fs.writeFileSync(path.join(OUTD, f.replace(/\.png$/, "_diff16x.png")), encodePng(d.w, d.h, d.img));
  }
  for (const f of only(A, B)) console.log("  only in " + A + ": " + f);
  for (const f of only(B, A)) console.log("  only in " + B + ": " + f);
  if (OUTD && OUTD !== true) fs.writeFileSync(path.join(OUTD, "compare.json"), JSON.stringify({ before: A, after: B, files: rows, onlyBefore: only(A, B), onlyAfter: only(B, A) }, null, 1));
  console.log(rows.filter((r) => !r.differing && !r.sizeDiffers).length + " of " + rows.length + " pictures identical");
  process.exit(0);
}

/* ---------------- the cases ---------------- */
const CASES_FILE = path.resolve(String(arg("cases-file", path.join(HERE, "fixtures", "ui_parity_cases.json"))));
const FIX = JSON.parse(fs.readFileSync(CASES_FILE, "utf8"));
const DEF = FIX.defaults;
const LAYOUT = String(arg("layout", "source"));
if (!FIX.routes[LAYOUT]) { console.error("--layout source|site"); process.exit(2); }
const ROUTES = FIX.routes[LAYOUT];
const SETS = list(arg("sets")), IDS = list(arg("cases")), WORLDS = list(arg("worlds")) || ["classic", "ocean"];
const SMOKE = arg("smoke") !== undefined;   /* (alone: the smoke runs only; with --sets / --cases: those cases too) */
const SELECTED = SMOKE && !SETS && !IDS ? [] : FIX.cases.filter((c) => (!SETS || SETS.indexOf(c.set) >= 0) && (!IDS || IDS.indexOf(c.id) >= 0));
if (arg("list") !== undefined) {
  for (const c of FIX.cases) console.log(c.id.padEnd(20) + c.set.padEnd(4) + c.worlds.join("+").padEnd(15) + c.title);
  process.exit(0);
}
if (IDS) for (const id of IDS) if (!FIX.cases.some((c) => c.id === id)) { console.error("no case " + id + " (--list)"); process.exit(2); }
if (!SELECTED.length && !SMOKE) { console.error("no case selected (--list)"); process.exit(2); }
const BASE = String(arg("base", "http://localhost:8123")).replace(/\/$/, "");
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "ui_parity_" + Date.now()))));
const NAME = String(arg("name", "ui-parity harness"));
const HEADED = arg("headed") !== undefined;
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const { chromium } = require(PW);
fs.mkdirSync(OUT, { recursive: true });

const fill = (s) => String(s).replace(/\{(\w+)\}/g, (m, k) => (k in DEF ? String(DEF[k]) : m));
function urlOf(world, c, route) {
  const q = [fill(FIX.query[world])];
  const extra = c && c.query ? (typeof c.query === "string" ? c.query : c.query[world]) : null;
  if (extra) q.push(fill(extra));
  return BASE + (route || ROUTES[world]) + "?" + q.filter(Boolean).join("&");
}
const selOf = (sel, world) => (sel && typeof sel === "object" ? sel[world] : sel);

/* ---------------- the page side: installed before any of the page's scripts ---------------- */
const INIT = (cfg) => {
  if (window.__ui || window.top !== window) return;
  const U = window.__ui = { cfg, vt: 1000, hold: !!cfg.hold, frames: 0, pending: new Map(), nextId: 1, after: [], module: null,
                            animT: cfg.animT, scheduled: false, stopAt: null, budget: null };
  /* the visual RNG: a seeded xorshift32 */
  let x = (cfg.visualSeed >>> 0) || 2463534242;
  Math.random = function () { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
  /* the clock: 1/60 s per animation frame, the same inside a frame. The frames are held (hold) or let go: for a
   * number of them (runFrames: held again after the last, so every run takes the same frames) or until held */
  if (cfg.clock) {
    const raf = window.requestAnimationFrame.bind(window);
    Object.defineProperty(performance, "now", { configurable: true, writable: true, value: function () { return U.vt; } });
    const dispatch = () => {
      U.scheduled = false;
      if (U.hold || !U.pending.size) return;
      U.vt += 1000 / 60; U.frames++;
      const cbs = Array.from(U.pending.values());
      U.pending.clear();
      for (const cb of cbs) { try { cb(U.vt); } catch (e) { setTimeout(() => { throw e; }); } }
      for (const h of U.after.slice()) { try { h(); } catch (e) { setTimeout(() => { throw e; }); } }
      if (U.budget !== null && --U.budget <= 0) { U.budget = null; U.hold = true; }
      schedule();
    };
    const schedule = () => { if (!U.scheduled && !U.hold && U.pending.size) { U.scheduled = true; raf(dispatch); } };
    window.requestAnimationFrame = function (cb) { const id = U.nextId++; U.pending.set(id, cb); schedule(); return id; };
    window.cancelAnimationFrame = function (id) { U.pending.delete(id); };
    U.release = () => { U.budget = null; U.hold = false; schedule(); };
    U.freeze = () => { U.budget = null; U.hold = true; };
    U.runFrames = (k) => { U.budget = k > 0 ? k : null; U.hold = !(k > 0); schedule(); };
  } else { U.release = () => {}; U.freeze = () => {}; U.runFrames = () => {}; }
  /* Classic's module: as EvoLoader.load() hands it to the page (web/loader.js) */
  let loader;
  Object.defineProperty(window, "EvoLoader", { configurable: true, get: () => loader, set: (v) => {
    if (v && typeof v.load === "function" && !v.__ui) {
      const load = v.load;
      v.load = function () { return load.apply(this, arguments).then((r) => { U.module = r && r.Module; return r; }); };
      v.__ui = true;
    }
    loader = v;
  } });
  /* each scene's render at the fixed animation time (web/scene3d.js EvoScene, web/ocean_scene.js EvoOceanScene) */
  for (const name of ["EvoScene", "EvoOceanScene"]) {
    let api;
    Object.defineProperty(window, name, { configurable: true, get: () => api, set: (v) => {
      if (v && typeof v.create === "function" && !v.__ui) {
        const create = v.create;
        v.create = function () {
          const sc = create.apply(this, arguments);
          if (sc && typeof sc.render === "function") {
            const render = sc.render;
            sc.render = function (s, info) { return render.call(this, s, U.animT === null || !info ? info : Object.assign({}, info, { animT: U.animT })); };
          }
          return sc;
        };
        v.__ui = true;
      }
      api = v;
    } });
  }
  /* the world's tick and state, either page */
  U.isOcean = () => !!(window.EvoOcean && window.EvoOcean.state);
  U.tick = () => {
    if (U.isOcean()) { const s = window.EvoOcean.state(); return s ? s.frame : NaN; }
    const M = U.module;
    if (!M || !M._evo_stats) return NaN;
    return new Float64Array(M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer, M._evo_stats(), 4)[3];
  };
  U.fish = () => {
    if (U.isOcean()) { const s = window.EvoOcean.state(); return s ? s.n : NaN; }
    return U.module && U.module._evo_creature_count ? U.module._evo_creature_count() : NaN;
  };
  U.paused = () => { const b = document.getElementById("pausebtn"); return !!b && b.getAttribute("aria-label") === "play"; };
  /* after the frame that reaches the tick: the frames held, and (pause) the page's Pause pressed */
  U.after.push(() => {
    const st = U.stopAt;
    if (!st || st.done) return;
    const t = U.tick();
    if (!(t >= st.tick)) return;
    st.done = true; st.at = t; st.frames = U.frames;
    U.freeze();
    if (st.then !== "freeze" && !U.paused()) document.getElementById("pausebtn").click();
  });
};

/* the page's state for a shot */
const STATE = () => {
  const U = window.__ui, a = document.activeElement;
  const desc = (e) => (e && e !== document.body ? { tag: e.tagName.toLowerCase(), id: e.id || null, role: e.getAttribute("role"),
    text: (e.textContent || "").trim().slice(0, 40) || null, focusVisible: e.matches(":focus-visible") } : null);
  const tabsOf = (id) => {
    const l = document.getElementById(id);
    if (!l) return null;
    const t = Array.from(l.querySelectorAll("[role=tab]"));
    return { selected: t.filter((b) => b.getAttribute("aria-selected") === "true").map((b) => (b.dataset.tab || b.id)),
             tabbable: t.filter((b) => b.tabIndex >= 0).map((b) => (b.dataset.tab || b.id)), n: t.length };
  };
  const speed = document.getElementById("speedlabel");
  return { tick: U.tick(), fish: U.fish(), paused: U.paused(), frames: U.frames, held: U.hold, focus: desc(a),
           dashTabs: tabsOf("dtabs"), setupTabs: tabsOf("tabs"), speed: speed ? speed.textContent : null,
           dashOpen: !!(document.getElementById("dash") && !document.getElementById("dash").hidden),
           sheetOpen: !!(document.getElementById("drawer") && document.getElementById("drawer").classList.contains("open")),
           toasts: Array.from((document.getElementById("toasts") || { children: [] }).children).map((t) => t.textContent),
           ui: !!window.EvoUI };
};

/* ---------------- one case on one world ---------------- */
async function launch(viewport, dpr) {
  const ctx = await chromium.launchPersistentContext("", {
    executablePath: BRAVE, headless: !HEADED, viewport: { width: viewport[0], height: viewport[1] }, deviceScaleFactor: dpr,
    locale: DEF.locale, timezoneId: DEF.timezone, reducedMotion: "no-preference",
    args: ["--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling", "--disable-renderer-backgrounding"]
  });
  const page = ctx.pages()[0] || await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + String(e && e.message || e)));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  page.on("requestfailed", (r) => errors.push("requestfailed: " + r.url() + " " + ((r.failure() || {}).errorText || "")));
  page.on("response", (r) => { if (r.status() >= 400) errors.push("http " + r.status() + ": " + r.url()); });
  return { ctx, page, errors };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/* exactly k frames, then held (with the clock: every run of a case draws the same frames) */
async function frames(page, k) {
  const clock = await page.evaluate((n) => { const U = window.__ui; if (!U.cfg.clock) return false; U.runFrames(n); return true; }, k);
  if (clock) await page.waitForFunction(() => window.__ui.hold && window.__ui.budget === null, null, { timeout: 120000, polling: 50 });
  else await sleep(k * 17);
}
async function tabTo(page, sel, max) {
  for (let i = 0; i <= max; i++) {
    if (await page.evaluate((s) => { const a = document.activeElement; return !!(a && a !== document.body && a.matches(s)); }, sel)) return i;
    if (i < max) await page.keyboard.press("Tab");
  }
  throw new Error("tabTo: the focus never reached " + sel + " in " + max + " Tab presses (it is on " +
                  await page.evaluate(() => { const a = document.activeElement; return a ? a.tagName + "#" + a.id : "nothing"; }) + ")");
}
/* the world: seed and founders, at tick 0, paused, then let go (paused) to check it */
async function setupWorld(L, world) {
  const p = L.page;
  await p.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true, null, { timeout: 120000, polling: 100 });
  L.readyAt = Date.now();
  if (world === "classic") {
    await p.evaluate(([seed, n]) => {
      const s = document.getElementById("seed"), q = document.getElementById("population");
      if (!s || !q) throw new Error("Classic's form has no #seed / #population");
      s.value = String(seed); q.value = String(n);
      s.dispatchEvent(new Event("input", { bubbles: true })); q.dispatchEvent(new Event("input", { bubbles: true }));
      document.getElementById("restart").click();
    }, [DEF.seed, DEF.founders]);
  }
  await p.evaluate(() => { if (!window.__ui.paused()) document.getElementById("pausebtn").click(); });
  await frames(p, 5);
  const w = await p.evaluate(() => ({ tick: window.__ui.tick(), fish: window.__ui.fish(), paused: window.__ui.paused(),
                                      seed: window.EvoOcean && window.EvoOcean.state ? (window.EvoOcean.state() || {}).seed : null }));
  if (w.tick !== 0 || w.fish !== DEF.founders || !w.paused || (world === "ocean" && w.seed !== DEF.seed))
    throw new Error("the world is not seed " + DEF.seed + " with " + DEF.founders + " founders at tick 0, paused: " + JSON.stringify(w));
  return w;
}
const STEPS = {
  async run(L, st) {
    const p = L.page, tick = st.tick === undefined ? DEF.tick : st.tick;
    await p.evaluate(([t, then]) => {
      const U = window.__ui;
      U.stopAt = { tick: t, then, done: false };
      if (U.paused()) document.getElementById("pausebtn").click();
      U.release();
    }, [tick, st.then || "pause"]);
    await p.waitForFunction(() => window.__ui.stopAt.done, null, { timeout: 300000, polling: 50 });
    const r = await p.evaluate(() => window.__ui.stopAt);
    if (r.at !== tick) throw new Error("run: the frame loop stopped at tick " + r.at + ", not " + tick);
    if ((st.then || "pause") === "pause") await frames(p, DEF.settleFrames);
  },
  async pause(L) {
    await L.page.evaluate(() => { if (!window.__ui.paused()) document.getElementById("pausebtn").click(); });
    await frames(L.page, DEF.settleFrames);
  },
  async release(L) { await L.page.evaluate(() => window.__ui.release()); },
  async freeze(L) { await L.page.evaluate(() => window.__ui.freeze()); },
  async settle(L, st) { await frames(L.page, st.frames || DEF.settleFrames); },
  async select(L, st, world) {
    const ok = await L.page.evaluate((w) => {
      if (w === "classic") return window.EvoApp.inspectSomeFish();
      const O = window.EvoOcean, s = O.state(), M = O.module;
      if (!s || !M) return false;
      const n = M._oc_creature_count(), buf = M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer;
      const segs = new Float32Array(buf, M._oc_creature_segments(), 12 * n);
      let best = -1, bd = Infinity;
      for (let i = 0; i < n; i++) { const d = Math.hypot(segs[12 * i] - 0.4 * s.W, segs[12 * i + 1] - 0.45 * s.H); if (d < bd) { bd = d; best = i; } }
      if (best < 0) return false;
      O.select(best);
      return true;
    }, world);
    if (!ok) throw new Error("select: no fish selected");
    await frames(L.page, DEF.settleFrames);
  },
  async click(L, st, world) { await L.page.click(selOf(st.sel, world), { timeout: 10000 }); await sleep(60); },
  async press(L, st, world) { await L.page.evaluate((s) => { const e = document.querySelector(s); if (!e) throw new Error("no " + s); e.click(); }, selOf(st.sel, world)); },
  async key(L, st) { for (let i = 0; i < (st.times || 1); i++) await L.page.keyboard.press(st.key); await sleep(60); },
  async tabTo(L, st, world) { L.tabs.push(await tabTo(L.page, selOf(st.sel, world), st.max || 150)); },
  async focus(L, st, world) { await L.page.evaluate((s) => { const e = document.querySelector(s); if (!e) throw new Error("no " + s); e.focus(); }, selOf(st.sel, world)); },
  async blur(L) { await L.page.evaluate(() => { const a = document.activeElement; if (a && a.blur) a.blur(); }); },
  async wait(L, st) { await sleep(st.ms || 300); },
  async shot(L, st, world, c) {
    const p = L.page;
    await p.evaluate(() => document.fonts.ready.then(() => true));
    if (st.toasts !== "keep") {
      await sleep(Math.max(0, L.readyAt + DEF.hintMs - Date.now()));   /* the page's one-time hint comes at 9 s */
      await p.waitForFunction(() => { const t = document.getElementById("toasts"); return !t || t.children.length === 0; }, null, { timeout: 12000, polling: 100 })
        .catch(() => {});
    }
    if (await p.evaluate(() => window.__ui.paused())) await frames(p, 2);   /* (a frozen live page stays at its tick) */
    const file = c.id + "__" + world + "__" + st.name + ".png";
    await p.screenshot({ path: path.join(OUT, file), fullPage: true, animations: "disabled", caret: "hide" });
    const state = await p.evaluate(STATE);
    L.shots.push({ name: st.name, file, state });
    console.log("    shot " + file + "  tick " + state.tick + (state.paused ? " paused" : " live") + (state.held ? " (held)" : "") +
                "  focus " + (state.focus ? state.focus.tag + (state.focus.id ? "#" + state.focus.id : "") + (state.focus.role ? "[" + state.focus.role + "]" : "") +
                (state.focus.focusVisible ? " ring" : "") : "none") + (state.dashOpen ? "  dash " + JSON.stringify(state.dashTabs.selected) : "") +
                (state.sheetOpen ? "  setup " + JSON.stringify(state.setupTabs.selected) : "") + (state.toasts.length ? "  toasts " + JSON.stringify(state.toasts) : ""));
  }
};
async function runCase(c, world) {
  const vp = c.viewport || DEF.viewport, dpr = c.dpr || DEF.dpr, url = urlOf(world, c);
  const rec = { case: c.id, set: c.set, world, url, viewport: vp, dpr, shots: [], errors: [], ok: false };
  const release = await acquire(NAME + " " + c.id + " " + world);
  let L = null;
  try {
    L = await launch(vp, dpr);
    L.shots = rec.shots; L.tabs = [];
    await L.ctx.addInitScript(INIT, { hold: true, clock: true, animT: DEF.animT, visualSeed: DEF.visualSeed });
    await L.page.goto(url, { waitUntil: "load", timeout: 120000 });
    rec.assets = await L.page.evaluate(() => Array.from(document.scripts).map((s) => s.getAttribute("src")).filter(Boolean));
    rec.world0 = await setupWorld(L, world);
    for (const st of c.steps) {
      if (st.world && st.world !== world) continue;
      if (!STEPS[st.do]) throw new Error("unknown step " + st.do);
      await STEPS[st.do](L, st, world, c);
    }
    rec.tabPresses = L.tabs;
    rec.ok = true;
  } catch (e) {
    rec.threw = String(e && e.stack || e);
    console.log("    THREW " + String(e && e.message || e));
    if (L) { try { await L.page.screenshot({ path: path.join(OUT, c.id + "__" + world + "__THREW.png") }); } catch (e2) { /* closed */ } }
  } finally {
    if (L) { rec.errors = L.errors.slice(0, 40); try { await L.ctx.close(); } catch (e) { /* closed */ } }
    release();
  }
  if (rec.errors.length) { rec.ok = false; console.log("    page messages: " + JSON.stringify(rec.errors.slice(0, 4))); }
  return rec;
}
/* a route loaded as a visitor would: its ready state and a few seconds of frames, without a console message */
async function smoke(world, route, label) {
  const url = urlOf(world, null, route), rec = { smoke: label, world, url, errors: [], ok: false };
  const release = await acquire(NAME + " smoke " + label);
  let L = null;
  try {
    L = await launch(DEF.viewport, DEF.dpr);
    await L.ctx.addInitScript(INIT, { hold: false, clock: false, animT: null, visualSeed: DEF.visualSeed });
    await L.page.goto(url, { waitUntil: "load", timeout: 120000 });
    await L.page.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true, null, { timeout: 120000, polling: 100 });
    await sleep(5000);
    rec.title = await L.page.title();
    rec.page = await L.page.evaluate(() => ({ ocean: !!window.EvoOcean, classic: !window.EvoOcean && !!window.EvoApp, tick: window.__ui.tick(), ui: !!window.EvoUI }));
    if ((world === "ocean") !== rec.page.ocean) L.errors.push("route " + route + " opened the " + (rec.page.ocean ? "Ocean" : "Classic") + " page, not " + world);
    const file = "smoke__" + label + ".png";
    await L.page.screenshot({ path: path.join(OUT, file), fullPage: true, animations: "disabled", caret: "hide" });
    rec.file = file;
    rec.ok = true;
  } catch (e) { rec.threw = String(e && e.stack || e); }
  finally {
    if (L) { rec.errors = L.errors.slice(0, 40); try { await L.ctx.close(); } catch (e) { /* closed */ } }
    release();
  }
  if (rec.errors.length) rec.ok = false;
  console.log((rec.ok ? "  ok   " : "  FAIL ") + "smoke " + label + " " + url + "  " + JSON.stringify(rec.page || null) + (rec.ok ? "" : "\n         " + (rec.threw || rec.errors.slice(0, 6).join("\n         "))));
  return rec;
}

const summary = { started: new Date().toISOString(), base: BASE, layout: LAYOUT, routes: ROUTES, defaults: DEF, cases: [], smoke: [] };
const save = () => fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(summary, null, 1));
try {
  if (SMOKE) {
    for (const w of WORLDS) summary.smoke.push(await smoke(w, ROUTES[w], w + (LAYOUT === "site" ? "_site" : "_source")));
    if (LAYOUT === "site" && ROUTES.oceanAlias && WORLDS.indexOf("ocean") >= 0) summary.smoke.push(await smoke("ocean", ROUTES.oceanAlias, "ocean_alias_site"));
    save();
  }
  for (const c of SELECTED) {
    for (const w of c.worlds) {
      if (WORLDS.indexOf(w) < 0) continue;
      console.log("== " + c.id + " (" + c.set + ") on " + w + ": " + urlOf(w, c));
      summary.cases.push(await runCase(c, w));
      save();
    }
  }
} finally {
  summary.finished = new Date().toISOString();
  save();
  const md = ["# UI parity pictures", "", "Base " + BASE + " (" + LAYOUT + " layout), " + summary.started + ". Seed " + DEF.seed + ", " + DEF.founders +
              " founders, " + DEF.viewport.join(" x ") + " at DPR " + DEF.dpr + ". From tests/ui_parity_browser.mjs; the state of each picture is in summary.json.", "",
              "| case | world | shot | file | tick | paused | focus | tabs (dash / setup) |", "|---|---|---|---|---|---|---|---|"];
  for (const r of summary.cases) for (const s of r.shots) {
    const f = s.state.focus;
    md.push("| " + r.case + " | " + r.world + " | " + s.name + " | " + s.file + " | " + s.state.tick + " | " + (s.state.paused ? "yes" : "no") + " | " +
            (f ? f.tag + (f.id ? "#" + f.id : "") + (f.role ? "[" + f.role + "]" : "") + (f.focusVisible ? " (ring)" : "") : "-") + " | " +
            (s.state.dashOpen ? (s.state.dashTabs.selected || []).join(",") : "-") + " / " + (s.state.sheetOpen ? (s.state.setupTabs.selected || []).join(",") : "-") + " |");
  }
  for (const r of summary.cases) if (!r.ok) md.push("", "**" + r.case + " on " + r.world + ": " + (r.threw ? r.threw.split("\n")[0] : "page messages: " + r.errors.slice(0, 3).join("; ")) + "**");
  fs.writeFileSync(path.join(OUT, "index.md"), md.join("\n") + "\n");
}
const bad = summary.cases.filter((r) => !r.ok).length + summary.smoke.filter((r) => !r.ok).length;
console.log((bad ? "FAIL: " + bad + " runs" : "ok: " + summary.cases.length + " case runs" + (SMOKE ? ", " + summary.smoke.length + " smoke runs" : "")) + "; output in " + OUT);
process.exit(bad ? 1 : 0);
