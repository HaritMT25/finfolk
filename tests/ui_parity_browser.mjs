// tests/ui_parity_browser.mjs: the UI parity plan's paired browser harness (docs/ui_parity.md). Classic and the Ocean in the same
// state, one case at a time, each world in a fresh headless Brave (a temporary profile: clean storage) under the machine-wide
// browser lock (tools/ocean_render_perf/lock.mjs), with full-page screenshots that include the DOM chrome (not the WebGL
// framebuffer alone). A local tool, not a CI job (CI has no browser); the cases are tests/fixtures/ui_parity_cases.json. The
// selection checks (--plan) and the comparison gate (--compare) need no browser: tests/ui_parity_harness_tests.mjs runs them in CI.
//
//   node tests/ui_parity_browser.mjs --base http://localhost:8123 --out DIR [--clean] [--layout source|site] [--sets S0,S2]
//        [--cases s0_shell,...] [--worlds classic,ocean] [--expect check|record] [--name WHO] [--smoke] [--headed]
//   node tests/ui_parity_browser.mjs --plan [the same selection]          what a run would take (no browser), or why it is refused
//   node tests/ui_parity_browser.mjs --list                               the cases
//   node tests/ui_parity_browser.mjs --compare BEFORE_DIR AFTER_DIR [--report [--archival]] [--cases-file F] [--sets ..] [--cases ..]
//        [--worlds ..] [--out DIFF_DIR [--clean]]
//
// --layout source (the default): --base serves the repository root (python3 wasm/serve.py, its default root), so Classic is
//          /web/index.html and the Ocean /web/ocean.html (and Classic's ../img/rocks.jpg resolves). --layout site: --base serves
//          a built site (bash wasm/build_site.sh; SITE_DIR=/x), so Classic is /classic.html and the Ocean /; --smoke there also
//          loads the Ocean's old name /ocean.html. Never /index.html for Classic: on the site that is the Ocean.
// --smoke (alone: only these; with --sets / --cases: those cases too): each route loaded as a visitor would (no held clock), its
//          ready state, no console error / warning, page error, failed request or HTTP error; one picture each (not compared).
// The selection: every world named must be one (classic, ocean), every set and case must exist, and the case x world list it
//          gives must not be empty (also with --smoke); the fixture itself is checked first (unique case ids, unique shot names in
//          each case and world, known steps and expectations, a selector for every world a step runs on). Exit 2 otherwise.
// --out:   must be new or empty: a run never mixes with an older one's pictures. --clean empties it first, but only of the files
//          an earlier run's manifest.json lists (its captures, expected captures and failed steps' pictures, plus manifest.json,
//          summary.json, index.md): without such a manifest, or with any other file there, it refuses and removes nothing.
// --expect: check (the default): a shot whose state is not its case's "expect" fails the run. record: it is kept in the
//          manifest (the capture's "unmet") and the run goes on: main's run before a PR that brings the behaviour. --compare
//          lists BEFORE's unmet expectations; AFTER may miss only what BEFORE missed too, the same way (else INVALID).
// The run writes DIR/manifest.json (kept current after every case): the harness's and the fixture's sha256, the selection,
//          every capture it was to take, and every one it took (sha256, size, case, set, world, shot, the fixture's difference
//          policy for it); "complete" only once every run passed and every capture was taken. Exit 1 on any failed run.
// --compare: a gate on two runs' manifests (before, after), never on whatever PNGs happen to be in two directories. It is bound
//          to this harness file and to a cases file it reads itself (--cases-file, or the committed one, as a run): never to
//          what the two manifests say of each other. The comparison's selection (--sets / --cases / --worlds; none: every case
//          of the cases file) is checked against that cases file (exit 2 as a run's), and every capture it plans must be in
//          both runs. Refused (exit 1, INVALID): a directory without a manifest, a run that is not complete, a capture missing
//          or changed since its run (its sha256), a PNG the run did not write (stale); a manifest without a valid harness or
//          cases-file identity (sha256), a run of another harness file or another cases file than this comparison's; a run
//          whose recorded selection, run through the cases file, does not give exactly its expected captures, or whose
//          captures are not recorded with their case, set, world, shot and the policy the cases file gives them (checkPolicy:
//          every field in range and its why); BEFORE and AFTER recording different policies for a picture; a capture the
//          comparison plans that one run did not take. Then pixel for pixel, each picture under its policy (the fixture's
//          defaults.compare, a case's or shot's "compare"): a pixel differs when a channel differs by more than "tolerance";
//          a picture passes with at most "maxPixels" such pixels and at most "maxNoisePixels" pixels that differ within the
//          tolerance (so a shift of one level over the whole picture is a change, not noise). Exit 1 (FAIL) on a picture
//          beyond its policy or a size change;
//          exit 0 (PASS) otherwise. --report: the same checks of the evidence, but differences and size changes are listed, not
//          failed (a PR that changes the UI on purpose); exit 0 when the evidence is valid. --report --archival --cases-file F:
//          two runs of an older harness (both of one harness file, and of F, the cases file they used: e.g. git show
//          COMMIT:tests/fixtures/ui_parity_cases.json): every check but the binding to this harness file; a record, never a
//          gate (REPORT at best). --sets / --cases / --worlds narrow the comparison (e.g. --sets S0: the shell must not
//          change). --out: a x16 difference picture for each picture that differs at all, and compare.json (which lists them:
//          --clean there removes only those and itself).
//
// The state (the plan's capture rules): seed 42 and 300 founders on both pages (Classic ignores setup URL parameters: its own
// form's seed and population fields and its Restart; the Ocean: its link's seed= and pop=), Classic's single-threaded module
// (?threads=0: the reproducible one), no tour (?guide=0&intro=0). The page's animation frames are held from the start, so the
// new world waits at tick 0; a case's "run" step lets the page's own frame loop go at speed 1 (one step a frame) and, after the
// frame that reaches the tick, presses the page's own Pause button ("pause") or holds the frames there ("freeze": the live UI).
// What is controlled, so that the same picture comes out on any run of a commit:
//   - the clock: performance.now() and the frames' timestamps advance exactly 1/60 s per animation frame (a frame-locked clock):
//     the frame rate reads 60, no governor (Hold 60 fps, Classic's detail / cap) ever acts, camera eases end the same way
//   - the frames: held between steps; a step that needs the page to draw lets an exact number run (settle), so every run of a
//     case draws the same frames; a shot taken while the frames run free (release) is refused
//   - idle callbacks (requestIdleCallback: both scenes' caustic texture) are queued, never run by the browser's idle time: the
//     harness runs them before any frame (the barrier, and every settle), so the caustics fade in over the same frames
//   - the renderer barrier, before the first step: Classic's background image decoded; the Ocean's polished fish programs
//     compiled ahead (its swim polish ungated for one frame, so the warm-up is asked at once, then its setting back) and its
//     decoded programs in effect (or the run fails, naming why); then a fixed number of frames (barrierFrames). The frames
//     it runs depend on the page's settings only, never on how fast the GPU compiles: the Ocean's polish frame runs whenever
//     the polish is drawn (its want not off, detail 2 up), whether the programs were compiled already or not, so the clock
//     and every frame count after it are the same (it checks its own count: 1 + barrierFrames, or barrierFrames with no
//     polish). After it, nothing a picture shows waits on a compile; each shot checks it still holds
//   - the page's own timers stay real time but are waited out: before frames run, until no one-shot timer of up to 1 s is
//     pending (the setup sheet's insets 320 ms after its slide, a tip's 200 ms, a resize's 250 ms), so each one lands before
//     the frames, not among them; before a shot, every one-shot timer of up to 10 s (a toast's life) as well. The page's
//     one-time "click a fish" hint (9 s after ready) is waited out in the barrier, before any step, so it always shows with
//     nothing selected and is gone before the first shot. #toasts must be empty at each shot (a shot's toasts: "keep" is the
//     one exception), else the run fails. Intervals (setInterval) stay real time: no S0 / S2 picture depends on one (the charts
//     draw at once when shown; their 500 ms update() redraws only on new data, another tab or width, or Similarity / Brains' page clock,
//     none of which moves while paused and held: docs/ui_parity.md). A case that does depend on one must wait for it
//   - the animation time: each scene's render gets a fixed animT (both scenes' create(), wrapped as they register)
//   - the visual RNG: Math.random is a seeded xorshift32 (snow, streaks; nothing in a case draws a seed from it)
//   - fonts loaded (document.fonts.ready), the CSS animations and transitions finished (the screenshot's animations: disabled),
//     the caret hidden; locale en-US, timezone UTC, the sRGB colour profile, no partial raster, DPR and viewport from the case
//     (1440 x 900 at 1 by default), prefers-reduced-motion off
// Not controlled, and so the compare policy's tolerance: the GPU's and the compositor's anti-aliasing of rounded edges over the
// canvas (a channel off by 1 in a few pixels between two runs of one commit), and rarely a few pixels of a rounded bar's edge.
// Numerical claims belong in node tests, not in these pictures.
//
// Steps (a case's "steps"; "world" limits a step to one world; "sel" is a selector or {classic, ocean}):
//   run {tick, then: pause|freeze}   the frame loop to the tick, as above
//   pause                            the page's Pause pressed (if it runs), then settle
//   release / freeze                 the frames let go with no count (no shot until a settle) / held
//   settle {frames}                  exactly that many frames (the default's settleFrames), then held
//   select                           a fish selected through the page: Classic's EvoApp.inspectSomeFish (the fish nearest
//                                    (0.4 W, 0.45 H)), the Ocean's EvoOcean.select of the fish nearest the same point (plan view)
//   click {sel}                      a pointer's click at the element (Playwright: a real mouse press; :focus-visible off)
//   press {sel}                      element.click(): a click no pointer made (detail 0)
//   key {key, times}                 a key pressed where the focus is (Playwright's keyboard)
//   tabTo {sel, max}                 Tab pressed until the focus is on the element (the keyboard's way there: its ring shows)
//   focus {sel} / blur               element.focus() / the focused element's blur()
//   wait {ms}                        real time
//   shot {name, toasts, expect, compare}  the picture, CASE__WORLD__NAME.png, and the page's state then (summary.json);
//                                    expect: what the state must be ({tick, paused, held, speed, dashOpen, sheetOpen, toasts,
//                                    focus: null | {id, role, text, ring}, dash / setup: {selected, tabbable}}, and per world
//                                    under "classic" / "ocean"), else the run fails; compare: this picture's policy
// Output: DIR/*.png, DIR/manifest.json, DIR/summary.json (per case and world: the URL, the build's asset names, the renderer's
// state after the barrier, every shot's state, the page's errors), DIR/index.md (case -> world -> shot -> file -> state).
//
//   env: PLAYWRIGHT  the playwright module (default C:/Users/harit/gemini_bridge/node_modules/playwright)
//        BRAVE_EXE   the browser (default C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe)
//        BROWSER_LOCK the lock file (lock.mjs; default: the machine-wide one), BROWSER_LOCK_POLL_MS its poll
//        UI_PARITY_READY_FIRST=1  a check of the barrier: wait (frames held) until the Ocean's polished programs are compiled
//                     before it starts (the fast GPU's timing); its pictures must equal a run without it (the manifest's
//                     barrierTiming says which run this was)
// The lock is taken for each case and world (one browser), so other jobs can run between them; an interrupted run leaves a
// manifest that is not complete (and Playwright closes its browser as the process exits).
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { acquire } from "../tools/ocean_render_perf/lock.mjs";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SELF = fileURLToPath(import.meta.url);
const WORLD_NAMES = ["classic", "ocean"];
const FORMAT = "ui-parity-run", FORMAT_VERSION = 1;

/* ---------------- arguments: every flag known, a value where one is wanted ---------------- */
const FLAGS = { base: 1, out: 1, layout: 1, sets: 1, cases: 1, worlds: 1, name: 1, "cases-file": 1,
                expect: 1, smoke: 0, headed: 0, list: 0, plan: 0, clean: 0, report: 0, archival: 0, compare: 2 };
const DEFAULT_CASES = path.join(HERE, "fixtures", "ui_parity_cases.json");
const SHA_RE = /^[0-9a-f]{64}$/;
const READY_FIRST = process.env.UI_PARITY_READY_FIRST === "1";
function usage(msg) { console.error("ui_parity_browser: " + msg + "\n(the header of tests/ui_parity_browser.mjs lists the flags)"); process.exit(2); }
function parseArgs(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) usage("unexpected argument " + JSON.stringify(a));
    const k = a.slice(2);
    if (!(k in FLAGS)) usage("unknown flag --" + k);
    if (k in o) usage("--" + k + " given twice");
    const n = FLAGS[k];
    if (n === 0) { o[k] = true; continue; }
    const vals = argv.slice(i + 1, i + 1 + n);
    if (vals.length < n || vals.some((v) => v.startsWith("--"))) usage("--" + k + " needs " + (n === 1 ? "a value" : n + " values"));
    o[k] = n === 1 ? vals[0] : vals;
    i += n;
  }
  return o;
}
const ARGS = parseArgs(process.argv.slice(2));
const listOf = (v) => (v === undefined ? null : String(v).split(",").map((x) => x.trim()).filter(Boolean));
const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");

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
function pngSize(buf) {
  if (buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47 || buf.toString("ascii", 12, 16) !== "IHDR") throw new Error("not a PNG");
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
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
/* the difference of two pictures: every pixel that differs at all (any: within the tolerance too), those beyond it (differing),
 * the largest channel difference, the box of the pixels beyond the tolerance, and a x16 picture of every difference */
function diffImages(a, b, tolerance) {
  if (a.w !== b.w || a.h !== b.h) return { sizeDiffers: true, a: [a.w, a.h], b: [b.w, b.h] };
  let any = 0, n = 0, max = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
  const img = new Uint8Array(a.px.length);
  for (let i = 0; i < a.px.length; i += 4) {
    const d = Math.max(Math.abs(a.px[i] - b.px[i]), Math.abs(a.px[i + 1] - b.px[i + 1]), Math.abs(a.px[i + 2] - b.px[i + 2]), Math.abs(a.px[i + 3] - b.px[i + 3]));
    if (d) {
      any++; if (d > max) max = d;
      if (d > tolerance) { n++; const p = i / 4, x = p % a.w, y = (p / a.w) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    const v = Math.min(255, d * 16); img[i] = v; img[i + 1] = v; img[i + 2] = v; img[i + 3] = 255;
  }
  return { pixels: a.px.length / 4, any, differing: n, maxDiff: max, box: n ? [x0, y0, x1 - x0 + 1, y1 - y0 + 1] : null, img, w: a.w, h: a.h };
}

/* ---------------- an output directory: new, empty, or emptied of the harness's own files (--clean) ---------------- */
function prepareDir(dir, clean, ownedBy, what) {
  if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true }); return; }
  if (!fs.statSync(dir).isDirectory()) usage(what + " " + dir + " is not a directory");
  const entries = fs.readdirSync(dir);
  if (!entries.length) return;
  if (!clean) usage(what + " " + dir + " is not empty (" + entries.length + " entries, e.g. " + entries.slice(0, 3).join(", ") + "): pictures of " +
                    "two runs must never mix. Use a new directory, or --clean to remove an earlier run's own files there first");
  const owned = ownedBy(dir);
  if (!owned.files) usage("--clean: " + what + " " + dir + " has no " + owned.record + " of an earlier " + owned.kind + " (" + owned.why + "): only files such a record " +
                         "lists are ever removed, so nothing is");
  const other = entries.filter((f) => !owned.files.has(f));
  if (other.length) usage("--clean: " + what + " " + dir + " holds files its " + owned.record + " does not list (" + other.slice(0, 5).join(", ") + "): not removing anything");
  for (const f of entries) fs.rmSync(path.join(dir, f), { force: true });
}
const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch (e) { return null; } };
/* a run's files, as its manifest lists them (null: no manifest of this harness) */
function RUN_OWNED(dir) {
  const o = { record: "manifest.json", kind: "run", files: null, why: "" };
  const p = path.join(dir, "manifest.json");
  if (!fs.existsSync(p)) { o.why = "none there"; return o; }
  const m = readJson(p);
  if (!m || m.format !== FORMAT) { o.why = "it is not a " + FORMAT + " manifest"; return o; }
  o.files = new Set(["manifest.json", "summary.json", "index.md"].concat(Object.keys(m.captures || {}), m.expected || [], m.extra || []));
  return o;
}
/* a comparison's files, as its compare.json lists them */
function DIFF_OWNED(dir) {
  const o = { record: "compare.json", kind: "comparison", files: null, why: "" };
  const p = path.join(dir, "compare.json");
  if (!fs.existsSync(p)) { o.why = "none there"; return o; }
  const m = readJson(p);
  if (!m || m.format !== "ui-parity-compare" || !Array.isArray(m.written)) { o.why = "it is not a ui-parity-compare record listing what it wrote"; return o; }
  o.files = new Set(["compare.json"].concat(m.written));
  return o;
}

/* ---------------- the fixture: checked before anything runs ---------------- */
const STEP_NAMES = ["run", "pause", "release", "freeze", "settle", "select", "click", "press", "key", "tabTo", "focus", "blur", "wait", "shot"];
const SEL_STEPS = ["click", "press", "tabTo", "focus"];
const STEP_KEYS = { run: ["tick", "then"], settle: ["frames"], click: ["sel"], press: ["sel"], key: ["key", "times"], tabTo: ["sel", "max"],
                    focus: ["sel"], wait: ["ms"], shot: ["name", "toasts", "expect", "compare"] };
const EXPECT_KEYS = ["tick", "paused", "held", "speed", "dashOpen", "sheetOpen", "toasts", "focus", "dash", "setup"];
const NAME_RE = /^[a-z0-9][a-z0-9_]*$/;
const worldsOfStep = (c, st) => (st.world ? [st.world] : c.worlds);
function checkPolicy(p, where, bad) {
  if (!p || typeof p !== "object") { bad.push(where + ": a compare policy is an object {tolerance, maxPixels, maxNoisePixels, why}"); return; }
  if (!Number.isInteger(p.tolerance) || p.tolerance < 0 || p.tolerance > 255) bad.push(where + ": tolerance is a whole number 0..255");
  if (!Number.isInteger(p.maxPixels) || p.maxPixels < 0) bad.push(where + ": maxPixels is a whole number >= 0");
  if (!Number.isInteger(p.maxNoisePixels) || p.maxNoisePixels < 0) bad.push(where + ": maxNoisePixels (the pixels that may differ within the tolerance) is a whole number >= 0");
  if (typeof p.why !== "string" || !p.why.trim()) bad.push(where + ": a policy says why (\"why\")");
}
function checkExpectSpec(e, where, bad) {
  if (!e || typeof e !== "object" || Array.isArray(e)) { bad.push(where + ": expect is an object"); return; }
  for (const k of Object.keys(e)) {
    if (WORLD_NAMES.indexOf(k) >= 0) { checkExpectSpec(e[k], where + "." + k, bad); continue; }
    if (EXPECT_KEYS.indexOf(k) < 0) { bad.push(where + ": unknown expectation " + k + " (one of " + EXPECT_KEYS.join(", ") + ")"); continue; }
    const v = e[k];
    if (k === "focus" && v !== null && (typeof v !== "object" || Object.keys(v).some((x) => ["id", "role", "text", "ring", "tag"].indexOf(x) < 0)))
      bad.push(where + ": focus is null or {id, role, text, tag, ring}");
    if ((k === "dash" || k === "setup") && (typeof v !== "object" || Object.keys(v).some((x) => ["selected", "tabbable"].indexOf(x) < 0)))
      bad.push(where + ": " + k + " is {selected, tabbable}");
  }
}
function validateFixture(fix) {
  const bad = [];
  if (!fix || typeof fix !== "object") return ["the fixture is not a JSON object"];
  const D = fix.defaults || {};
  for (const k of ["seed", "founders", "tick", "viewport", "dpr", "animT", "visualSeed", "settleFrames", "barrierFrames", "locale", "timezone"])
    if (!(k in D)) bad.push("defaults." + k + " is missing");
  checkPolicy(D.compare, "defaults.compare", bad);
  for (const lay of ["source", "site"]) for (const w of WORLD_NAMES) if (!fix.routes || !fix.routes[lay] || typeof fix.routes[lay][w] !== "string") bad.push("routes." + lay + "." + w + " is missing");
  for (const w of WORLD_NAMES) if (!fix.query || typeof fix.query[w] !== "string") bad.push("query." + w + " is missing");
  if (!Array.isArray(fix.cases) || !fix.cases.length) { bad.push("cases: none"); return bad; }
  const ids = new Set();
  for (const [ci, c] of fix.cases.entries()) {
    const at = "case " + (c && c.id ? c.id : "#" + ci);
    if (!c || typeof c.id !== "string" || !NAME_RE.test(c.id)) { bad.push(at + ": id is a lower-case name (a-z, 0-9, _)"); continue; }
    if (ids.has(c.id)) bad.push(at + ": the id is used twice (its pictures would overwrite each other)");
    ids.add(c.id);
    if (typeof c.set !== "string" || !/^S\d$/.test(c.set)) bad.push(at + ": set is S0..S9");
    if (!Array.isArray(c.worlds) || !c.worlds.length || c.worlds.some((w) => WORLD_NAMES.indexOf(w) < 0) || new Set(c.worlds).size !== c.worlds.length)
      { bad.push(at + ": worlds is a list of distinct names from " + WORLD_NAMES.join(", ")); continue; }
    if (c.query !== undefined && typeof c.query !== "string" && (typeof c.query !== "object" || Object.keys(c.query).some((w) => WORLD_NAMES.indexOf(w) < 0)))
      bad.push(at + ": query is a string or {classic, ocean}");
    if (c.compare !== undefined) checkPolicy(c.compare, at + ".compare", bad);
    if (!Array.isArray(c.steps) || !c.steps.length) { bad.push(at + ": no steps"); continue; }
    const shots = {};
    for (const w of c.worlds) shots[w] = new Set();
    for (const [si, st] of c.steps.entries()) {
      const sat = at + " step " + (si + 1) + " (" + (st && st.do) + ")";
      if (!st || STEP_NAMES.indexOf(st.do) < 0) { bad.push(sat + ": unknown step (one of " + STEP_NAMES.join(", ") + ")"); continue; }
      for (const k of Object.keys(st)) if (k !== "do" && k !== "world" && (STEP_KEYS[st.do] || []).indexOf(k) < 0) bad.push(sat + ": unknown key " + k);
      if (st.world !== undefined && c.worlds.indexOf(st.world) < 0) { bad.push(sat + ": world " + st.world + " is not one of the case's"); continue; }
      const ws = worldsOfStep(c, st);
      if (SEL_STEPS.indexOf(st.do) >= 0) {
        if (typeof st.sel === "string") { if (!st.sel) bad.push(sat + ": empty selector"); }
        else if (!st.sel || typeof st.sel !== "object") bad.push(sat + ": sel is a selector or {classic, ocean}");
        else for (const w of ws) if (typeof st.sel[w] !== "string" || !st.sel[w]) bad.push(sat + ": no selector for " + w + " (the step runs there)");
      }
      if (st.do === "run" && ((st.tick !== undefined && !(Number.isInteger(st.tick) && st.tick >= 0)) || (st.then !== undefined && ["pause", "freeze"].indexOf(st.then) < 0)))
        bad.push(sat + ": tick is a whole number, then pause or freeze");
      if (st.do === "settle" && st.frames !== undefined && !(Number.isInteger(st.frames) && st.frames > 0)) bad.push(sat + ": frames is a whole number > 0");
      if (st.do === "key" && (typeof st.key !== "string" || !st.key)) bad.push(sat + ": no key");
      if (st.do === "wait" && !(st.ms > 0)) bad.push(sat + ": ms > 0");
      if (st.do === "shot") {
        if (typeof st.name !== "string" || !NAME_RE.test(st.name)) bad.push(sat + ": name is a lower-case name (a-z, 0-9, _)");
        else for (const w of ws) { if (shots[w].has(st.name)) bad.push(sat + ": shot " + st.name + " twice on " + w + " (the second would overwrite the first)"); shots[w].add(st.name); }
        if (st.toasts !== undefined && st.toasts !== "keep") bad.push(sat + ": toasts is \"keep\" or absent");
        if (st.expect !== undefined) checkExpectSpec(st.expect, sat + ".expect", bad);
        if (st.compare !== undefined) checkPolicy(st.compare, sat + ".compare", bad);
      }
    }
    for (const w of c.worlds) if (!shots[w].size) bad.push(at + ": no shot on " + w + " (a run must leave a picture)");
  }
  return bad;
}
function loadFixture(file) {
  let text, fix;
  try { text = fs.readFileSync(file, "utf8"); } catch (e) { usage("cannot read the cases file " + file + ": " + e.message); }
  try { fix = JSON.parse(text); } catch (e) { usage("the cases file " + file + " is not JSON: " + e.message); }
  const bad = validateFixture(fix);
  if (bad.length) usage("the cases file " + file + " is not valid:\n  " + bad.join("\n  "));
  return { fix, sha: sha256(Buffer.from(text, "utf8")), file };
}
const policyOf = (fix, c, st) => Object.assign({}, fix.defaults.compare, c.compare || {}, st.compare || {});
const fileOf = (caseId, world, shot) => caseId + "__" + world + "__" + shot + ".png";
/* the selection: validated, then the case x world list; never empty when cases are asked for (or no --smoke) */
function makePlan(fix, o) {
  const sets = listOf(o.sets), ids = listOf(o.cases), worlds = listOf(o.worlds) || WORLD_NAMES.slice(), smoke = !!o.smoke, layout = o.layout || "source";
  const bad = [];
  if (!fix.routes[layout]) bad.push("--layout is source or site, not " + JSON.stringify(layout));
  if (!worlds.length) bad.push("--worlds names no world");
  for (const w of worlds) if (WORLD_NAMES.indexOf(w) < 0) bad.push("--worlds: no world " + JSON.stringify(w) + " (" + WORLD_NAMES.join(", ") + ")");
  if (new Set(worlds).size !== worlds.length) bad.push("--worlds names a world twice");
  const knownSets = new Set(fix.cases.map((c) => c.set));
  if (sets) for (const s of sets) if (!knownSets.has(s)) bad.push("--sets: no case is in set " + JSON.stringify(s) + " (sets: " + Array.from(knownSets).join(", ") + ")");
  if (ids) for (const id of ids) if (!fix.cases.some((c) => c.id === id)) bad.push("--cases: no case " + JSON.stringify(id) + " (--list)");
  if (bad.length) return { bad };
  const wantCases = !smoke || !!sets || !!ids;
  const runs = [];
  if (wantCases) for (const c of fix.cases) {
    if ((sets && sets.indexOf(c.set) < 0) || (ids && ids.indexOf(c.id) < 0)) continue;
    for (const w of c.worlds) {
      if (worlds.indexOf(w) < 0) continue;
      const shots = c.steps.filter((st) => st.do === "shot" && (!st.world || st.world === w));
      runs.push({ c, world: w, captures: shots.map((st) => ({ file: fileOf(c.id, w, st.name), shot: st.name, policy: policyOf(fix, c, st) })) });
    }
  }
  if (wantCases && !runs.length)
    bad.push("the selection runs no case (" + [sets && "--sets " + sets.join(","), ids && "--cases " + ids.join(","), "--worlds " + worlds.join(",")].filter(Boolean).join(" ") +
             "): its cases are not on those worlds. Nothing would be tested");
  const smokes = [];
  if (smoke) {
    const R = fix.routes[layout];
    for (const w of worlds) smokes.push({ world: w, route: R[w], label: w + (layout === "site" ? "_site" : "_source") });
    if (layout === "site" && R.oceanAlias && worlds.indexOf("ocean") >= 0) smokes.push({ world: "ocean", route: R.oceanAlias, label: "ocean_alias_site" });
  }
  if (!runs.length && !smokes.length && !bad.length) bad.push("nothing selected");
  return { bad, runs, smokes, selection: { sets, cases: ids, worlds, smoke, layout } };
}

/* ---------------- --compare: the gate ---------------- */
/* a policy as text (its why shortened), and one key-order-free form of it to compare two by */
const polText = (p) => (p && typeof p === "object" ? "{tolerance " + p.tolerance + ", maxPixels " + p.maxPixels + ", maxNoisePixels " + p.maxNoisePixels +
  (typeof p.why === "string" && p.why.trim() ? ", why " + JSON.stringify(p.why.length > 40 ? p.why.slice(0, 40) + "..." : p.why) : ", no why") + "}" : JSON.stringify(p));
const polKey = (p) => JSON.stringify(p && typeof p === "object" && !Array.isArray(p) ? Object.keys(p).sort().map((k) => [k, p[k]]) : p);
const selText = (s) => (s && typeof s === "object" ? [s.sets && "--sets " + [].concat(s.sets).join(","), s.cases && "--cases " + [].concat(s.cases).join(","),
  s.worlds && [].concat(s.worlds).join(",") !== WORLD_NAMES.join(",") && "--worlds " + [].concat(s.worlds).join(","), s.smoke && "--smoke",
  s.layout && s.layout !== "source" && "--layout " + s.layout].filter(Boolean).join(" ") || "everything" : JSON.stringify(s));
/* what a run of this recorded selection takes, by this cases file (makePlan, as the run itself): {bad} or {files: file -> what it is} */
function inventory(fix, sel) {
  const names = (v) => (v === null || v === undefined ? undefined : Array.isArray(v) && v.every((x) => typeof x === "string" && x && x.indexOf(",") < 0) ? v.join(",") : false);
  if (!sel || typeof sel !== "object" || Array.isArray(sel)) return { bad: ["it records no selection {sets, cases, worlds, smoke, layout}"] };
  const o = { sets: names(sel.sets), cases: names(sel.cases), worlds: names(sel.worlds), smoke: sel.smoke, layout: sel.layout };
  if (o.sets === false || o.cases === false || !Array.isArray(sel.worlds) || o.worlds === false || typeof sel.smoke !== "boolean" || typeof sel.layout !== "string")
    return { bad: ["its selection " + JSON.stringify(sel) + " is not one a run records ({sets, cases: null or names; worlds: names; smoke; layout})"] };
  const plan = makePlan(fix, o);
  if (plan.bad.length) return { bad: ["its selection (" + selText(sel) + ") is not one this cases file runs: " + plan.bad.join("; ")] };
  const files = new Map();
  for (const r of plan.runs) for (const x of r.captures) files.set(x.file, { kind: "case", case: r.c.id, set: r.c.set, world: r.world, shot: x.shot, policy: x.policy });
  for (const s of plan.smokes) files.set("smoke__" + s.label + ".png", { kind: "smoke", world: s.world, smoke: s.label });
  return { bad: [], files };
}
/* one run's evidence, checked on its own and against this comparison (K: this harness's sha256, the cases file, archival) */
function readRun(dir, label, K) {
  const problems = [];
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return { problems: [label + ": " + dir + " is not a directory"] };
  const mp = path.join(dir, "manifest.json");
  if (!fs.existsSync(mp)) return { problems: [label + ": no manifest.json in " + dir + " (not a run of this harness, or one interrupted before it began)"] };
  let m;
  try { m = JSON.parse(fs.readFileSync(mp, "utf8")); } catch (e) { return { problems: [label + ": its manifest.json is not JSON (" + e.message + ")"] }; }
  if (!m || m.format !== FORMAT || m.version !== FORMAT_VERSION || !Array.isArray(m.expected) || !m.captures || typeof m.captures !== "object")
    return { problems: [label + ": manifest.json is not a " + FORMAT + " v" + FORMAT_VERSION + " manifest"] };
  if (m.complete !== true) {
    const failed = (m.runs || []).filter((r) => !r.ok).map((r) => r.case + " on " + r.world + ": " + String(r.error || "").split("\n")[0]);
    problems.push(label + ": the run is not complete (status " + m.status + (failed.length ? "; " + failed.slice(0, 3).join("; ") : "") + ")");
  }
  for (const f of m.expected) if (!m.captures[f]) problems.push(label + ": " + f + " was to be taken and was not");
  for (const [f, c] of Object.entries(m.captures)) {
    const p = path.join(dir, f);
    if (!fs.existsSync(p)) { problems.push(label + ": " + f + " is in the manifest but not in " + dir); continue; }
    if (sha256(fs.readFileSync(p)) !== c.sha256) problems.push(label + ": " + f + " is not the picture its run took (its sha256 changed since: stale or edited)");
  }
  for (const f of fs.readdirSync(dir)) if (/\.png$/i.test(f) && !m.captures[f]) problems.push(label + ": " + f + " is not a capture of this run (stale, or a failed step's picture)");
  /* its identities: valid, this harness file (unless archival) and this comparison's cases file (the review of b442a92: two
     manifests agreeing with each other, or both without one, said nothing of what they were taken with) */
  const hasH = typeof m.harness === "string" && SHA_RE.test(m.harness), hasF = typeof m.fixture === "string" && SHA_RE.test(m.fixture);
  if (!hasH) problems.push(label + ": its manifest has no valid harness identity (harness " + JSON.stringify(m.harness) + "; a sha256 is 64 hex digits)");
  if (!hasF) problems.push(label + ": its manifest has no valid cases-file identity (fixture " + JSON.stringify(m.fixture) + "; a sha256 is 64 hex digits)");
  if (hasH && !K.archival && m.harness !== K.harnessSha)
    problems.push(label + ": taken by another harness file (sha256 " + m.harness.slice(0, 12) + "), not this one (" + K.harnessSha.slice(0, 12) + "): take it again with this " +
                  "harness, or keep the two runs as a record (--report --archival --cases-file THEIR_CASES_FILE)");
  if (hasF && m.fixture !== K.fixSha)
    problems.push(label + ": it used another cases file (sha256 " + m.fixture.slice(0, 12) + ") than this comparison's, " + K.casesFile + " (" + K.fixSha.slice(0, 12) + "): " +
                  "what it was to take is not what this cases file plans");
  /* its inventory: the selection it recorded, run through this cases file, gives exactly its expected captures, and each capture
     is recorded as that file's (case, set, world, shot) with the policy it gives it */
  const inv = hasF && m.fixture === K.fixSha ? inventory(K.fix, m.selection) : null;
  if (inv && inv.bad.length) for (const b of inv.bad) problems.push(label + ": " + b);
  if (inv && !inv.bad.length) {
    const exp = new Set(m.expected);
    for (const f of inv.files.keys()) if (!exp.has(f)) problems.push(label + ": " + f + " is taken by its selection (" + selText(m.selection) + ") but not in its expected list");
    for (const f of m.expected) if (!inv.files.has(f)) problems.push(label + ": " + f + " is in its expected list, but its selection (" + selText(m.selection) + ") does not take it");
    if (polKey(m.policy) !== polKey(K.fix.defaults.compare)) problems.push(label + ": its recorded default policy " + polText(m.policy) + " is not the cases file's defaults.compare " + polText(K.fix.defaults.compare));
  }
  const checked = !!inv && !inv.bad.length;
  for (const [f, c] of Object.entries(m.captures)) {
    const want = checked ? inv.files.get(f) : undefined;
    if (checked && !want) { problems.push(label + ": " + f + " is not a capture its selection (" + selText(m.selection) + ") takes"); continue; }
    if (want) {
      const off = (want.kind === "case" ? ["kind", "case", "set", "world", "shot"] : ["kind", "world", "smoke"]).filter((k) => c[k] !== want[k]);
      if (off.length) problems.push(label + ": " + f + " is recorded with " + off.map((k) => k + " " + JSON.stringify(c[k])).join(", ") + "; the cases file has " + off.map((k) => JSON.stringify(want[k])).join(", "));
    }
    if ((want ? want.kind : c.kind) !== "case") continue;   /* a smoke picture: never compared, no policy */
    const pb = [];
    checkPolicy(c.policy, label + ": " + f + "'s recorded policy", pb);
    for (const b of pb) problems.push(b);
    if (want && polKey(c.policy) !== polKey(want.policy))
      problems.push(label + ": " + f + "'s recorded policy " + polText(c.policy) + " is not the one the cases file gives it, " + polText(want.policy));
  }
  return { m, problems };
}
function compareMain(o) {
  const [A, B] = o.compare, report = !!o.report, archival = !!o.archival;
  if (archival && !report) usage("--archival goes with --report: two runs of another harness file are a record, never a gate");
  if (archival && o["cases-file"] === undefined) usage("--archival needs --cases-file: the cases file both runs used (e.g. git show COMMIT:tests/fixtures/ui_parity_cases.json > F)");
  /* bound to this harness file and to the cases file read here, not to what the manifests say of each other */
  const L = loadFixture(path.resolve(String(o["cases-file"] || DEFAULT_CASES)));
  const K = { archival, harnessSha: sha256(fs.readFileSync(SELF)), fix: L.fix, fixSha: L.sha, casesFile: L.file };
  /* the comparison's selection, checked as a run's; every capture it plans must be in both runs */
  const scope = makePlan(K.fix, { sets: o.sets, cases: o.cases, worlds: o.worlds });
  if (scope.bad.length) usage("the comparison's selection: " + scope.bad.join("\n  "));
  const sets = scope.selection.sets, ids = scope.selection.cases, worlds = listOf(o.worlds);
  const planned = scope.runs.flatMap((r) => r.captures.map((x) => x.file)).sort();
  const OUTD = o.out ? path.resolve(o.out) : null;
  if (OUTD) prepareDir(OUTD, !!o.clean, DIFF_OWNED, "--out");
  console.log("compare: " + planned.length + " pictures planned by " + K.casesFile + " (sha256 " + K.fixSha.slice(0, 12) + ") for " +
              selText({ sets, cases: ids, worlds }) + "; " + (archival ? "--archival: a record, not bound to this harness file (" + K.harnessSha.slice(0, 12) + ")" :
              "this harness file " + K.harnessSha.slice(0, 12)));
  const ra = readRun(A, "BEFORE " + A, K), rb = readRun(B, "AFTER " + B, K), problems = ra.problems.concat(rb.problems);
  let files = [];
  const unmet = [];
  if (ra.m && rb.m) {
    if (archival && ra.m.harness !== rb.m.harness)
      problems.push("the two runs were taken by different harness files (sha256 " + String(ra.m.harness).slice(0, 12) + " vs " + String(rb.m.harness).slice(0, 12) + "): a record compares two runs of one");
    for (const f of planned) for (const [r, side] of [[ra, "BEFORE"], [rb, "AFTER"]])
      if (!r.m.captures[f]) problems.push(f + ": the comparison plans it, " + side + " did not take it (its selection: " + selText(r.m.selection) + "); narrow the comparison or take the run again");
    files = planned.filter((f) => ra.m.captures[f] && rb.m.captures[f]);
    if (!files.length) problems.push("nothing to compare" + (sets || ids || worlds ? " in the selection" : "") + " (no case capture on both sides)");
    for (const f of files) {
      const pa = ra.m.captures[f].policy, pb = rb.m.captures[f].policy;
      if (polKey(pa) !== polKey(pb)) problems.push(f + ": BEFORE and AFTER record different policies, " + polText(pa) + " and " + polText(pb));
    }
    /* the cases' expectations: a run with --expect record keeps the ones it did not meet (main, before a PR that brings the
       behaviour). AFTER may miss only what BEFORE missed too, the same way (two runs of one commit); anything else is INVALID */
    for (const f of files) {
      const ua = ra.m.captures[f].unmet || [], ub = rb.m.captures[f].unmet || [];
      for (const u of ub) if (ua.indexOf(u) < 0) problems.push("AFTER: " + f + " does not meet its case's expectation (" + u + ") and BEFORE did");
      for (const u of ua) unmet.push({ file: f, side: ub.indexOf(u) >= 0 ? "both" : "before", what: u });
    }
  }
  const rows = [], written = [];
  if (!problems.length) for (const f of files) {
    const ca = ra.m.captures[f], cb = rb.m.captures[f], pol = cb.policy;
    const d = diffImages(decodePng(fs.readFileSync(path.join(A, f))), decodePng(fs.readFileSync(path.join(B, f))), pol.tolerance);
    const row = { file: f, case: cb.case, set: cb.set, world: cb.world, shot: cb.shot, policy: pol, beforeSha: ca.sha256, afterSha: cb.sha256 };
    if (d.sizeDiffers) Object.assign(row, { verdict: "size", before: d.a, after: d.b });
    else {
      const noise = d.any - d.differing;   /* differ, but by no more than the tolerance */
      Object.assign(row, { verdict: !d.any ? "same" : d.differing <= pol.maxPixels && noise <= pol.maxNoisePixels ? "within" : "differs",
                           pixels: d.pixels, any: d.any, differing: d.differing, noise, maxDiff: d.maxDiff, box: d.box });
    }
    rows.push(row);
    const tag = { same: "  same   ", within: "  noise  ", differs: "  DIFF   ", size: "  SIZE   " }[row.verdict];
    console.log(tag + f + (row.verdict === "size" ? "  " + row.before.join("x") + " -> " + row.after.join("x")
      : row.verdict === "same" ? "" : "  " + row.any + " px differ: " + row.differing + " beyond tolerance " + pol.tolerance + " (policy: at most " + pol.maxPixels + "), " +
        row.noise + " within it (policy: at most " + pol.maxNoisePixels + "), max " + row.maxDiff + (row.box ? ", box " + row.box.join(",") : "")));
    if (OUTD && !d.sizeDiffers && d.any) { const w = f.replace(/\.png$/, "_diff16x.png"); fs.writeFileSync(path.join(OUTD, w), encodePng(d.w, d.h, d.img)); written.push(w); }
  }
  const beyond = rows.filter((r) => r.verdict === "differs" || r.verdict === "size");
  const verdict = problems.length ? "INVALID" : report ? "REPORT" : beyond.length ? "FAIL" : "PASS";
  for (const u of unmet) console.log("  unmet  " + u.file + " (" + (u.side === "both" ? "both runs" : "BEFORE only") + "): " + u.what);
  for (const p of problems) console.log("  INVALID " + p);
  const counts = ["same", "within", "differs", "size"].map((v) => rows.filter((r) => r.verdict === v).length);
  console.log(verdict + ": " + (problems.length ? problems.length + " problems with the evidence; nothing compared" :
              rows.length + " pictures: " + counts[0] + " identical, " + counts[1] + " within their policy, " + counts[2] + " beyond it, " + counts[3] + " of another size" +
              (report ? " (--report: differences listed, not failed)" : "") + (archival ? " (--archival: runs of harness " + String(ra.m.harness).slice(0, 12) + ", a record, not a gate)" : "") +
              (unmet.length ? "; " + unmet.length + " expectations BEFORE did not meet" + (unmet.some((u) => u.side === "both") ? " (some neither run met)" : "") : "")));
  if (OUTD) fs.writeFileSync(path.join(OUTD, "compare.json"), JSON.stringify({ format: "ui-parity-compare", written, before: path.resolve(A), after: path.resolve(B),
    mode: report ? (archival ? "report-archival" : "report") : "check", harness: K.harnessSha, fixture: K.fixSha, casesFile: K.casesFile,
    selection: { sets, cases: ids, worlds }, planned: planned.length, verdict, problems, unmet, expectModes: { before: ra.m && ra.m.expectMode, after: rb.m && rb.m.expectMode }, counts: { same: counts[0], within: counts[1], differs: counts[2], size: counts[3] }, files: rows }, null, 1));
  process.exit(verdict === "PASS" || verdict === "REPORT" ? 0 : 1);
}

/* ---------------- dispatch: compare, list, plan (no browser), then a run ---------------- */
if (ARGS.compare) {
  for (const k of Object.keys(ARGS)) if (["compare", "report", "archival", "cases-file", "sets", "cases", "worlds", "out", "clean"].indexOf(k) < 0) usage("--" + k + " is not a --compare flag");
  compareMain(ARGS);
}
if (ARGS.report) usage("--report goes with --compare");
if (ARGS.archival) usage("--archival goes with --compare --report");
const CASES_FILE = path.resolve(String(ARGS["cases-file"] || DEFAULT_CASES));
const { fix: FIX, sha: FIX_SHA } = loadFixture(CASES_FILE);
const DEF = FIX.defaults;
if (ARGS.list) {
  for (const c of FIX.cases) console.log(c.id.padEnd(20) + c.set.padEnd(4) + c.worlds.join("+").padEnd(15) + c.title);
  process.exit(0);
}
const PLAN = makePlan(FIX, ARGS);
if (PLAN.bad.length) usage(PLAN.bad.join("\n  "));
const EXPECT_MODE = ARGS.expect === undefined ? "check" : String(ARGS.expect);
if (EXPECT_MODE !== "check" && EXPECT_MODE !== "record") usage("--expect is check (the default: a shot that does not meet its case's expect fails the run) or record (kept in the manifest: main's run before a PR that brings the behaviour)");
const EXPECTED = PLAN.runs.flatMap((r) => r.captures.map((x) => x.file));
if (ARGS.plan) {
  for (const r of PLAN.runs) console.log("run   " + r.c.id + " on " + r.world + ": " + r.captures.length + " captures");
  for (const s of PLAN.smokes) console.log("smoke " + s.label + " " + s.route);
  console.log("plan: " + PLAN.runs.length + " case runs, " + EXPECTED.length + " captures, " + PLAN.smokes.length + " smoke runs");
  process.exit(0);
}
const LAYOUT = PLAN.selection.layout, ROUTES = FIX.routes[LAYOUT];
const BASE = String(ARGS.base || "http://localhost:8123").replace(/\/$/, "");
if (!ARGS.out) usage("--out DIR is needed for a run");
const OUT = path.resolve(String(ARGS.out));
const NAME = String(ARGS.name || "ui-parity harness");
const HEADED = !!ARGS.headed;
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
prepareDir(OUT, !!ARGS.clean, RUN_OWNED, "--out");
const { chromium } = require(PW);

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
                            animT: cfg.animT, scheduled: false, stopAt: null, budget: null, scenes: [], images: [], idle: [], idleRun: 0, timers: new Map() };
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
    /* idle callbacks: queued, run only by the harness (flushIdle: before frames), never by the browser's idle time */
    let idleId = 1;
    window.requestIdleCallback = function (cb) { const id = idleId++; U.idle.push({ id, cb }); return id; };
    window.cancelIdleCallback = function (id) { U.idle = U.idle.filter((q) => q.id !== id); };
    U.flushIdle = () => {
      let n = 0;
      while (U.idle.length) {
        const q = U.idle; U.idle = [];
        for (const it of q) { n++; U.idleRun++; try { it.cb({ didTimeout: true, timeRemaining: () => 0 }); } catch (e) { setTimeout(() => { throw e; }); } }
      }
      return n;
    };
    /* the page's one-shot timers, real time, but known: pendingTimers(maxMs) lists those of up to maxMs not yet fired */
    const rST = window.setTimeout.bind(window), rCT = window.clearTimeout.bind(window);
    window.setTimeout = function (fn, ms, ...rest) {
      const d = Math.max(0, +ms || 0);
      if (typeof fn !== "function") return rST(fn, d, ...rest);
      let id = 0;
      id = rST(function () { U.timers.delete(id); return fn.apply(this, rest); }, d);
      U.timers.set(id, { ms: d, due: Date.now() + d });
      return id;
    };
    window.clearTimeout = function (id) { U.timers.delete(id); return rCT(id); };
    U.pendingTimers = (maxMs) => Array.from(U.timers.values()).filter((t) => t.ms <= maxMs).map((t) => ({ ms: t.ms, dueInMs: t.due - Date.now() }));
    /* images loaded by script (Classic's background, img/rocks.jpg): the barrier decodes them */
    const src = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
    if (src && src.set) Object.defineProperty(HTMLImageElement.prototype, "src", { configurable: true, enumerable: src.enumerable,
      get() { return src.get.call(this); }, set(v) { if (U.images.indexOf(this) < 0) U.images.push(this); src.set.call(this, v); } });
  } else { U.release = () => {}; U.freeze = () => {}; U.runFrames = () => {}; U.flushIdle = () => 0; U.pendingTimers = () => []; }
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
  /* each scene as it is made (the barrier asks it), its render at the fixed animation time (web/scene3d.js EvoScene,
   * web/ocean_scene.js EvoOceanScene) */
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
          if (sc) U.scenes.push({ name, sc });
          return sc;
        };
        v.__ui = true;
      }
      api = v;
    } });
  }
  /* the Ocean's renderer: its polished programs compiled ahead (prewarmStart: the polish ungated so the next frame asks for
   * the warm-up; prewarmEnd: its setting back), its decoded programs settled, and what it is drawing with. Whether a scene
   * takes the polish frame is its settings' (the polish drawn: want not off, detail 2 up), never whether its programs happen
   * to be compiled already (the review of b442a92: a fast compile skipped the frame and moved every later frame count and
   * timestamp by one). polishReady: per scene, null (no polish drawn) or whether its programs are compiled */
  const oceans = () => U.scenes.filter((s) => s.name === "EvoOceanScene").map((s) => s.sc);
  const polishDrawn = (p) => !!p && p.want !== "off" && p.quality >= 2;
  U.polishReady = () => oceans().map((sc) => { const p = sc.polish ? sc.polish() : null; return polishDrawn(p) ? !!p.ready : null; });
  U.prewarmStart = () => oceans().map((sc) => {
    const p = sc.polish ? sc.polish() : null;
    if (!polishDrawn(p)) return null;
    sc.setPolish("ungated");
    return p.want;
  });
  U.prewarmReady = (wants) => oceans().every((sc, i) => !wants[i] || sc.polish().ready);
  U.prewarmEnd = (wants) => oceans().forEach((sc, i) => { if (wants[i]) sc.setPolish(wants[i]); });
  U.decodedSettled = () => oceans().every((sc) => {
    if (!sc.renderOptimization) return true;
    const r = sc.renderOptimization(), m = sc.materials ? sc.materials() : null;
    if (!r.enabled) return true;
    if (r.failures && r.failures.length) return true;
    return !(r.features && r.features.pending) && !(m && m.pending) && r.effective.decoded === r.requested.decoded;
  });
  U.rendererState = () => {
    const out = { scenes: [], failures: [] };
    for (const { name, sc } of U.scenes) {
      const e = { name };
      if (name === "EvoOceanScene") {
        const p = sc.polish(), r = sc.renderOptimization(), m = sc.materials();
        e.polish = { want: p.want, quality: p.quality, ready: p.ready, variant: p.variant };
        e.optimization = { enabled: r.enabled, requested: r.requested, effective: r.effective, failures: r.failures, pending: !!(r.features && r.features.pending) };
        e.materials = { pending: m.pending, failed: m.failed, look: m.look };
        e.lost = sc.contextInfo ? sc.contextInfo().lost : null;
        if (p.want !== "off" && p.quality >= 2 && !p.ready) out.failures.push(name + ": the polished programs are not compiled");
        if (r.enabled && r.effective.decoded !== r.requested.decoded) out.failures.push(name + ": the decoded programs are not in effect (" + (r.failures || []).join("; ") + ")");
        if (r.failures && r.failures.length) out.failures.push(name + ": " + r.failures.join("; "));
        if (m.failed && m.failed.length) out.failures.push(name + ": materials failed: " + m.failed.join(", "));
        if (e.lost) out.failures.push(name + ": the WebGL context is lost");
      }
      out.scenes.push(e);
    }
    out.images = U.images.map((i) => ({ src: i.currentSrc || i.src, complete: i.complete, width: i.naturalWidth }));
    for (const i of out.images) if (!i.complete || !(i.width > 0)) out.failures.push("the image " + i.src + " is not loaded");
    out.idlePending = U.idle.length; out.idleRun = U.idleRun;
    return out;
  };
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
  return { tick: U.tick(), fish: U.fish(), paused: U.paused(), frames: U.frames, held: U.hold, freeRunning: !U.hold && U.budget === null,
           focus: desc(a), dashTabs: tabsOf("dtabs"), setupTabs: tabsOf("tabs"), speed: speed ? speed.textContent : null,
           dashOpen: !!(document.getElementById("dash") && !document.getElementById("dash").hidden),
           sheetOpen: !!(document.getElementById("drawer") && document.getElementById("drawer").classList.contains("open")),
           toasts: Array.from((document.getElementById("toasts") || { children: [] }).children).map((t) => t.textContent),
           ui: !!window.EvoUI };
};
/* a shot's expectations against its state: the mismatches */
function checkExpect(state, exp, world) {
  if (!exp) return [];
  const e = Object.assign({}, exp, exp[world] || {});
  for (const w of WORLD_NAMES) delete e[w];
  const bad = [], same = (a, b) => JSON.stringify(a) === JSON.stringify(b), say = (k, got, want) => bad.push(k + " is " + JSON.stringify(got) + ", expected " + JSON.stringify(want));
  for (const [k, v] of Object.entries(e)) {
    if (k === "focus") {
      if (v === null) { if (state.focus) say("focus", state.focus, null); continue; }
      if (!state.focus) { say("focus", null, v); continue; }
      for (const [fk, fv] of Object.entries(v)) { const got = fk === "ring" ? state.focus.focusVisible : state.focus[fk]; if (!same(got, fv)) say("focus." + fk, got, fv); }
    } else if (k === "dash" || k === "setup") {
      const t = k === "dash" ? state.dashTabs : state.setupTabs;
      for (const [tk, tv] of Object.entries(v)) if (!same(t && t[tk], tv)) say(k + "." + tk, t && t[tk], tv);
    } else if (k === "toasts") { if (state.toasts.length !== v) say("toasts", state.toasts, v); }
    else if (!same(state[k], v)) say(k, state[k], v);
  }
  return bad;
}

/* ---------------- one case on one world ---------------- */
async function launch(viewport, dpr) {
  const ctx = await chromium.launchPersistentContext("", {
    executablePath: BRAVE, headless: !HEADED, viewport: { width: viewport[0], height: viewport[1] }, deviceScaleFactor: dpr,
    locale: DEF.locale, timezoneId: DEF.timezone, reducedMotion: "no-preference",
    args: ["--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
           "--force-color-profile=srgb", "--disable-partial-raster"]
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
/* a condition in the page, polled from here (no page timer or frame of its own), or an error saying what was waited for */
async function waitFor(page, fn, arg, timeoutMs, what, detail) {
  const until = Date.now() + timeoutMs;
  for (;;) {
    if (await page.evaluate(fn, arg)) return;
    if (Date.now() > until) throw new Error(what + ": not reached in " + Math.round(timeoutMs / 1000) + " s" + (detail ? " (" + JSON.stringify(await page.evaluate(detail, arg)).slice(0, 400) + ")" : ""));
    await sleep(50);
  }
}
/* the page's one-shot timers of up to maxMs: every one fired (a timer they schedule in turn included) */
async function waitTimers(page, maxMs, what, timeoutMs) {
  await waitFor(page, (m) => window.__ui.pendingTimers(m).length === 0, maxMs, timeoutMs || 3 * maxMs + 5000,
                what + ": the page's timers of up to " + maxMs + " ms still pending", (m) => window.__ui.pendingTimers(m));
}
/* exactly k frames, then held (with the clock: every run of a case draws the same frames); first the idle callbacks run and the
 * short timers land, so neither falls among the frames */
async function frames(page, k) {
  const clock = await page.evaluate(() => !!window.__ui.cfg.clock);
  if (!clock) { await sleep(k * 17); return; }
  await page.evaluate(() => window.__ui.flushIdle());
  await waitTimers(page, 1000, "before " + k + " frames");
  await page.evaluate((n) => window.__ui.runFrames(n), k);
  await waitFor(page, () => window.__ui.hold && window.__ui.budget === null, null, 120000, k + " frames");
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
  await waitFor(p, () => !!(window.EvoApp && window.EvoApp.ready === true), null, 120000, "the page's ready state");
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
/* the renderer barrier (the header): nothing a picture shows waits on a compile, an image or an idle callback, and the page's
 * one-time hint has come and gone; then a fixed number of frames. The frames it runs are the page's settings' alone (the polish
 * frame whenever the polish is drawn, compiled already or not), and it checks that count */
async function barrier(L) {
  const p = L.page, t0 = Date.now();
  await p.evaluate(() => window.__ui.flushIdle());
  await p.evaluate(() => Promise.all(window.__ui.images.map((i) => (i.decode ? i.decode().catch(() => null) : null))).then(() => true));
  if (READY_FIRST)   /* the fast GPU's timing, on purpose: the programs the setup's frames asked for, compiled before the barrier (no frame runs) */
    await waitFor(p, () => window.__ui.polishReady().every((r) => r !== false), null, 120000,
                  "UI_PARITY_READY_FIRST: the Ocean's polished programs compiled before the barrier, with the frames held", () => window.__ui.rendererState());
  const readyAtStart = await p.evaluate(() => window.__ui.polishReady());
  const f0 = await p.evaluate(() => window.__ui.frames);
  const wants = await p.evaluate(() => window.__ui.prewarmStart());
  const polishFrame = wants.some(Boolean);
  if (polishFrame) {
    await p.evaluate(() => window.__ui.runFrames(1));
    await waitFor(p, () => window.__ui.hold && window.__ui.budget === null, null, 60000, "the prewarm frame");
    await waitFor(p, (w) => window.__ui.prewarmReady(w), wants, 120000, "the barrier: the Ocean's polished programs compiled", () => window.__ui.rendererState());
    await p.evaluate((w) => window.__ui.prewarmEnd(w), wants);
  }
  await waitFor(p, () => window.__ui.decodedSettled(), null, 120000, "the barrier: the Ocean's decoded programs settled", () => window.__ui.rendererState());
  await waitTimers(p, 10000, "the barrier (the page's one-time hint and its toast)", 45000);
  await waitFor(p, () => { const t = document.getElementById("toasts"); return !t || t.children.length === 0; }, null, 15000, "the barrier: #toasts empty",
                () => Array.from((document.getElementById("toasts") || { children: [] }).children).map((t) => t.textContent));
  await frames(p, DEF.barrierFrames);
  const spent = (await p.evaluate(() => window.__ui.frames)) - f0, budget = (polishFrame ? 1 : 0) + DEF.barrierFrames;
  if (spent !== budget) throw new Error("the barrier ran " + spent + " frames, not its " + budget + " (" + (polishFrame ? "the polish frame + " : "") + "barrierFrames): " +
                                        "a picture's frame count and clock would depend on more than the page's settings");
  const st = await p.evaluate(() => window.__ui.rendererState());
  if (st.failures.length) throw new Error("the barrier: the renderer is not in its full state: " + st.failures.join("; "));
  return Object.assign(st, { prewarmed: polishFrame, readyAtStart, frames: spent, timing: READY_FIRST ? "ready-first" : "as-it-comes", ms: Date.now() - t0 });
}
const STEPS = {
  async run(L, st) {
    const p = L.page, tick = st.tick === undefined ? DEF.tick : st.tick;
    await p.evaluate(() => window.__ui.flushIdle());
    await waitTimers(p, 1000, "before the run");
    await p.evaluate(([t, then]) => {
      const U = window.__ui;
      U.stopAt = { tick: t, then, done: false };
      if (U.paused()) document.getElementById("pausebtn").click();
      U.release();
    }, [tick, st.then || "pause"]);
    await waitFor(p, () => window.__ui.stopAt.done, null, 300000, "run to tick " + tick);
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
  async shot(L, st, world, c, cap) {
    const p = L.page, keep = st.toasts === "keep", at = c.id + " on " + world + ", shot " + st.name;
    if (await p.evaluate(() => !window.__ui.hold && window.__ui.budget === null))
      throw new Error(at + ": the frames run free (a release step with no settle after it): such a picture is not reproducible");
    await p.evaluate(() => document.fonts.ready.then(() => true));
    await waitTimers(p, keep ? 1000 : 10000, at, 45000);
    if (await p.evaluate(() => window.__ui.paused())) await frames(p, 2);   /* (a frozen live page stays at its tick) */
    const rs = await p.evaluate(() => window.__ui.rendererState());
    if (rs.failures.length) throw new Error(at + ": the renderer left its full state: " + rs.failures.join("; "));
    if (!keep) {
      const t = await p.evaluate(() => Array.from((document.getElementById("toasts") || { children: [] }).children).map((x) => x.textContent));
      if (t.length) throw new Error(at + ": #toasts is not empty at the picture (" + JSON.stringify(t) + "); a shot keeps its toasts only with toasts: \"keep\"");
    }
    const file = cap.file;
    await p.screenshot({ path: path.join(OUT, file), fullPage: true, animations: "disabled", caret: "hide" });
    const state = await p.evaluate(STATE);
    const buf = fs.readFileSync(path.join(OUT, file));
    const bad = checkExpect(state, st.expect, world);
    L.shots.push({ name: st.name, file, state, unmet: bad });
    L.captured.push({ file, kind: "case", case: c.id, set: c.set, world, shot: st.name, sha256: sha256(buf), size: pngSize(buf), bytes: buf.length, policy: cap.policy, unmet: bad });
    console.log("    shot " + file + "  tick " + state.tick + (state.paused ? " paused" : " live") + (state.held ? " (held)" : "") +
                "  focus " + (state.focus ? state.focus.tag + (state.focus.id ? "#" + state.focus.id : "") + (state.focus.role ? "[" + state.focus.role + "]" : "") +
                (state.focus.focusVisible ? " ring" : "") : "none") + (state.dashOpen ? "  dash " + JSON.stringify(state.dashTabs.selected) : "") +
                (state.sheetOpen ? "  setup " + JSON.stringify(state.setupTabs.selected) : "") + "  speed " + state.speed + (state.toasts.length ? "  toasts " + JSON.stringify(state.toasts) : ""));
    if (bad.length && EXPECT_MODE === "check") throw new Error(at + ": the state is not what the case expects: " + bad.join("; "));
    if (bad.length) console.log("    expectation not met (--expect record: kept in the manifest): " + bad.join("; "));
  }
};
async function runCase(run, onCapture, onExtra) {
  const c = run.c, world = run.world;
  const vp = c.viewport || DEF.viewport, dpr = c.dpr || DEF.dpr, url = urlOf(world, c);
  const rec = { case: c.id, set: c.set, world, url, viewport: vp, dpr, shots: [], errors: [], ok: false };
  const caps = new Map(run.captures.map((x) => [x.shot, x]));
  const release = await acquire(NAME + " " + c.id + " " + world);
  let L = null;
  try {
    L = await launch(vp, dpr);
    L.shots = rec.shots; L.tabs = []; L.captured = [];
    await L.ctx.addInitScript(INIT, { hold: true, clock: true, animT: DEF.animT, visualSeed: DEF.visualSeed });
    await L.page.goto(url, { waitUntil: "load", timeout: 120000 });
    rec.assets = await L.page.evaluate(() => Array.from(document.scripts).map((s) => s.getAttribute("src")).filter(Boolean));
    rec.world0 = await setupWorld(L, world);
    rec.renderer = await barrier(L);
    console.log("    barrier: " + rec.renderer.ms + " ms, " + rec.renderer.frames + " frames, idle callbacks run (all before a frame) " + rec.renderer.idleRun +
                ", polish frame " + rec.renderer.prewarmed + " (programs compiled at its start: " + JSON.stringify(rec.renderer.readyAtStart) + ", " + rec.renderer.timing + ")" +
                ", scenes " + JSON.stringify(rec.renderer.scenes.map((s) => s.name + (s.polish ? " polish " + s.polish.variant + (s.polish.ready ? " ready" : "") : "") +
                (s.optimization ? " decoded " + s.optimization.effective.decoded : ""))));
    for (const st of c.steps) {
      if (st.world && st.world !== world) continue;
      try { await STEPS[st.do](L, st, world, c, st.do === "shot" ? caps.get(st.name) : null); }
      finally { while (L.captured.length) onCapture(L.captured.shift()); }
    }
    rec.tabPresses = L.tabs;
    rec.ok = true;
  } catch (e) {
    rec.threw = String(e && e.stack || e);
    console.log("    THREW " + String(e && e.message || e));
    if (L) { try { const t = c.id + "__" + world + "__THREW.png"; await L.page.screenshot({ path: path.join(OUT, t) }); onExtra(t); } catch (e2) { /* closed */ } }
  } finally {
    if (L) { rec.errors = L.errors.slice(0, 40); try { await L.ctx.close(); } catch (e) { /* closed */ } }
    release();
  }
  if (rec.errors.length) { rec.ok = false; console.log("    page messages: " + JSON.stringify(rec.errors.slice(0, 4))); }
  return rec;
}
/* a route loaded as a visitor would: its ready state and a few seconds of frames, without a console message */
async function smoke(s, onCapture) {
  const { world, route, label } = s, url = urlOf(world, null, route), rec = { smoke: label, world, url, errors: [], ok: false };
  const release = await acquire(NAME + " smoke " + label);
  let L = null;
  try {
    L = await launch(DEF.viewport, DEF.dpr);
    await L.ctx.addInitScript(INIT, { hold: false, clock: false, animT: null, visualSeed: DEF.visualSeed });
    await L.page.goto(url, { waitUntil: "load", timeout: 120000 });
    await waitFor(L.page, () => !!(window.EvoApp && window.EvoApp.ready === true), null, 120000, "the page's ready state");
    await sleep(5000);
    rec.title = await L.page.title();
    rec.page = await L.page.evaluate(() => ({ ocean: !!window.EvoOcean, classic: !window.EvoOcean && !!window.EvoApp, tick: window.__ui.tick(), ui: !!window.EvoUI }));
    if ((world === "ocean") !== rec.page.ocean) L.errors.push("route " + route + " opened the " + (rec.page.ocean ? "Ocean" : "Classic") + " page, not " + world);
    const file = "smoke__" + label + ".png";
    await L.page.screenshot({ path: path.join(OUT, file), fullPage: true, animations: "disabled", caret: "hide" });
    const buf = fs.readFileSync(path.join(OUT, file));
    onCapture({ file, kind: "smoke", world, smoke: label, sha256: sha256(buf), size: pngSize(buf), bytes: buf.length });
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

/* ---------------- the run: manifest first (not complete), kept current, complete only at a clean end ---------------- */
const summary = { started: new Date().toISOString(), base: BASE, layout: LAYOUT, routes: ROUTES, defaults: DEF, cases: [], smoke: [] };
const manifest = { format: FORMAT, version: FORMAT_VERSION, harness: sha256(fs.readFileSync(SELF)), fixture: FIX_SHA, fixtureFile: CASES_FILE,
                   base: BASE, layout: LAYOUT, selection: PLAN.selection, started: summary.started, finished: null, status: "running", complete: false,
                   expectMode: EXPECT_MODE, barrierTiming: READY_FIRST ? "ready-first" : "as-it-comes", policy: DEF.compare, expected: EXPECTED.concat(PLAN.smokes.map((s) => "smoke__" + s.label + ".png")), captures: {}, extra: [], runs: [], smoke: [] };
const save = () => {
  fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(summary, null, 1));
  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 1));
};
const onCapture = (cap) => { manifest.captures[cap.file] = cap; save(); };
const onExtra = (file) => { if (manifest.extra.indexOf(file) < 0) manifest.extra.push(file); save(); };
save();
let threw = null;
try {
  for (const s of PLAN.smokes) {
    const r = await smoke(s, onCapture);
    summary.smoke.push(r); manifest.smoke.push({ label: r.smoke, ok: r.ok, error: r.threw || r.errors[0] || null });
    save();
  }
  for (const run of PLAN.runs) {
    console.log("== " + run.c.id + " (" + run.c.set + ") on " + run.world + ": " + urlOf(run.world, run.c));
    const r = await runCase(run, onCapture, onExtra);
    summary.cases.push(r); manifest.runs.push({ case: r.case, world: r.world, ok: r.ok, error: r.threw ? r.threw.split("\n")[0] : r.errors[0] || null });
    save();
  }
} catch (e) { threw = e; }
finally {
  summary.finished = manifest.finished = new Date().toISOString();
  const missing = manifest.expected.filter((f) => !manifest.captures[f]);
  const failed = manifest.runs.filter((r) => !r.ok).length + manifest.smoke.filter((r) => !r.ok).length;
  manifest.complete = !threw && !failed && !missing.length && manifest.runs.length === PLAN.runs.length && manifest.smoke.length === PLAN.smokes.length;
  manifest.status = manifest.complete ? "complete" : threw ? "aborted: " + String(threw && threw.message || threw) : "failed: " + failed + " runs, " + missing.length + " captures missing";
  save();
  const md = ["# UI parity pictures", "", "Base " + BASE + " (" + LAYOUT + " layout), " + summary.started + ". Seed " + DEF.seed + ", " + DEF.founders +
              " founders, " + DEF.viewport.join(" x ") + " at DPR " + DEF.dpr + ". From tests/ui_parity_browser.mjs; the state of each picture is in summary.json, " +
              "the run's evidence in manifest.json (" + manifest.status + ").", "",
              "| case | world | shot | file | tick | paused | focus | tabs (dash / setup) | speed |", "|---|---|---|---|---|---|---|---|---|"];
  for (const r of summary.cases) for (const s of r.shots) {
    const f = s.state.focus;
    md.push("| " + r.case + " | " + r.world + " | " + s.name + " | " + s.file + " | " + s.state.tick + " | " + (s.state.paused ? "yes" : "no") + " | " +
            (f ? f.tag + (f.id ? "#" + f.id : "") + (f.role ? "[" + f.role + "]" : "") + (f.focusVisible ? " (ring)" : "") : "-") + " | " +
            (s.state.dashOpen ? (s.state.dashTabs.selected || []).join(",") : "-") + " / " + (s.state.sheetOpen ? (s.state.setupTabs.selected || []).join(",") : "-") + " | " + s.state.speed + " |");
  }
  for (const r of summary.cases) if (!r.ok) md.push("", "**" + r.case + " on " + r.world + ": " + (r.threw ? r.threw.split("\n")[0] : "page messages: " + r.errors.slice(0, 3).join("; ")) + "**");
  fs.writeFileSync(path.join(OUT, "index.md"), md.join("\n") + "\n");
}
if (threw) throw threw;
console.log((manifest.complete ? "ok: " : "FAIL (" + manifest.status + "): ") + summary.cases.length + " case runs, " + Object.values(manifest.captures).filter((x) => x.kind === "case").length +
            " captures" + (PLAN.smokes.length ? ", " + summary.smoke.length + " smoke runs" : "") + "; output in " + OUT);
process.exit(manifest.complete ? 0 : 1);
