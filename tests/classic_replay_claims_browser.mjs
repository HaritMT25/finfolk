// tests/classic_replay_claims_browser.mjs: what the Classic page says about its run, checked in the real page (the wasm
// module, headless Brave, one page at a time under tools/ocean_render_perf/lock.mjs): the numbers panel's cumulative
// births and deaths, what the seed replays (the modeline's data-replay / data-why) through a governor cull, refused files,
// a refused Restart and a stepper clamped at its bound, and the reseed floor's tip for a loaded world and for an edit
// Turbo did not take. A local check: it needs a browser and a served tree, so it is not a CI step.
//   python3 wasm/serve.py . 8191            (from the repository root: COOP/COEP, the root's ../img for Classic)
//   node tests/classic_replay_claims_browser.mjs [--base http://localhost:8191] [--only totals,stepper,refusals,floor,fractional,turbo]
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length ? args[i + 1] : def; }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = arg("base", "http://localhost:8191").replace(/\/$/, "");
const ONLY = arg("only", "").split(",").filter(Boolean);
const { acquire } = await import(new URL("../tools/ocean_render_perf/lock.mjs", import.meta.url).href);
const { chromium } = require(PW);

let checks = 0, failures = 0;
function ok(c, msg) { checks++; if (!c) failures++; console.log((c ? "  ok   " : "  FAIL ") + msg); }
function section(s) { console.log("\n" + s); }

/* the module, for the test's own reads: loader.js's EvoLoader.load wrapped as it is defined (no page change) */
const SHIM = `(() => { let L; Object.defineProperty(window, "EvoLoader", { configurable: true, get() { return L; },
  set(v) { const load = v.load; v.load = function () { return load.apply(this, arguments).then((r) => { window.__evoModule = r.Module; return r; }); }; L = v; } }); })();`;

async function launch() {
  return chromium.launchPersistentContext("", { executablePath: BRAVE, headless: true, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1,
                                                acceptDownloads: true, args: ["--no-first-run", "--no-default-browser-check"] });
}
async function open(ctx, q) {
  const page = ctx.pages()[0] || await ctx.newPage();
  page.__errs = [];
  page.on("pageerror", (e) => page.__errs.push(String(e)));
  await page.addInitScript(SHIM);
  await page.goto(BASE + "/web/index.html?guide=0&intro=0" + (q || ""));
  await page.waitForFunction(() => window.EvoApp && EvoApp.ready === true && window.__evoModule, null, { timeout: 120000, polling: 250 });
  return page;
}
const claim = (p) => p.evaluate(() => { const d = document.getElementById("modeline").dataset; return (d.replay || "?") + (d.why ? ":" + d.why : ""); });
const stats = (p) => p.evaluate(() => {
  const M = window.__evoModule, buf = M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer;
  return Array.from(new Float64Array(buf, M._evo_stats(), M._evo_stats_len ? M._evo_stats_len() : 12));
});
const govShown = (p) => p.evaluate(() => !document.getElementById("ro-gov").hidden);
async function drawer(p, tab) {
  if ((await p.getAttribute("#menubtn", "aria-expanded")) !== "true") await p.click("#menubtn");
  if (tab) await p.click("#tab-" + tab);
}
async function closeDrawer(p) { if ((await p.getAttribute("#menubtn", "aria-expanded")) === "true") await p.click("#menubtn"); }
/* a field typed and left (its change: the live ones apply on change) */
async function setField(p, id, v) { await p.fill("#" + id, String(v)); await p.dispatchEvent("#" + id, "change"); }
async function tipOf(p, rowId) {
  await p.mouse.move(5, 5);
  await p.waitForTimeout(150);
  const b = await p.locator("#" + rowId + " .lt").first().boundingBox();
  await p.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 4 });
  await p.waitForFunction(() => { const t = document.getElementById("tooltip"); return t && t.style.display === "block"; }, null, { timeout: 5000 });
  return p.evaluate(() => document.querySelector("#tooltip .tipd").textContent);
}
/* the floor the tip says this run has, and the form's value it says is not in it (null: none) */
function floorSaid(tip) {
  const run = /\((\d+) in this run/.exec(tip) || /reseed floor is (\d+)/.exec(tip), form = /form's (\d+) is not in this run/.exec(tip);
  return { run: run ? +run[1] : null, form: form ? +form[1] : null };
}
async function say(p) { return p.evaluate(() => document.getElementById("err").textContent); }
async function loadFile(p, name, text) {
  await p.evaluate(() => { document.getElementById("err").textContent = ""; });
  await p.setInputFiles("#cpfile", { name, mimeType: "application/json", buffer: Buffer.from(text) });
  await p.waitForFunction(() => document.getElementById("err").textContent !== "", null, { timeout: 15000 });
  return say(p);
}
const errsOk = (p, what) => ok(p.__errs.length === 0, what + ": no page error" + (p.__errs.length ? " (" + p.__errs[0] + ")" : ""));

const CASES = {
  /* U22: the panel's births and deaths are the module's totals (evo_stats 6 / 7), not the last step's (4 / 5) */
  async totals() {
    section("The numbers panel shows the run's total births and deaths");
    const ctx = await launch();
    try {
      const p = await open(ctx, "&threads=0");
      /* (until births have added up: the first ones come a few hundred frames in) */
      await p.waitForFunction(() => { const M = window.__evoModule, buf = M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer;
        return new Float64Array(buf, M._evo_stats(), 8)[6] >= 10; }, null, { timeout: 180000, polling: 100 });
      await p.click("#pausebtn");
      await p.click("#readout");
      await p.waitForTimeout(300);
      const r = await p.evaluate(() => {
        const dt = Array.from(document.querySelectorAll("#statpanel dt")), dd = document.querySelectorAll("#statpanel dd");
        const val = (name) => { const i = dt.findIndex((d) => d.textContent === name); return i < 0 ? null : Number(dd[i].textContent.replace(/,/g, "")); };
        return { births: val("Births (total)"), deaths: val("Deaths (total)") };
      });
      const st = await stats(p);
      ok(r.births === st[6] && r.deaths === st[7] && st[6] > 0 && st[6] !== st[4],
         "paused at frame " + st[3] + ": the panel's births " + r.births + " / deaths " + r.deaths + " are the totals (" + st[6] + " / " + st[7] +
         "), not the last step's (" + st[4] + " / " + st[5] + ")");
      errsOk(p, "totals");
    } finally { await ctx.close(); }
  },
  /* review of #88, P3-4: a stepper clamped at its bound applies the value the world runs: no live change */
  async stepper() {
    section("A live field set to the value the run already has is not a live change");
    const ctx = await launch();
    try {
      const p = await open(ctx, "&threads=0");
      const c0 = await claim(p);
      await drawer(p, "world");
      await p.click('#f_maxPopulation .stepper button[aria-label="less"]');   /* 0, clamped at 0: still fires change */
      await p.waitForTimeout(200);
      const cSame = await claim(p), cap = await p.inputValue("#adv_maxPopulation");
      await setField(p, "adv_maxPopulation", 500);
      await p.waitForTimeout(200);
      const cChanged = await claim(p);
      ok(c0 === "yes" && cap === "0" && cSame === "yes" && cChanged === "no:live",
         "a fresh single-threaded run replays (" + c0 + "); the cap's minus at " + cap + ": still (" + cSame + "); the cap set to 500: not (" + cChanged + ")");
      errsOk(p, "stepper");
    } finally { await ctx.close(); }
  },
  /* review of #88, P2-2: a refused file or Restart leaves the run as it was, and what it says about its seed with it */
  async refusals() {
    section("After a governor cull, refused files and a refused Restart keep the run's history; an accepted Restart clears it");
    const ctx = await launch();
    try {
      const p = await open(ctx, "&threads=0");
      await drawer(p, "world");
      await setField(p, "population", 2500);
      await p.click("#restart");
      await closeDrawer(p);
      const cdp = await p.context().newCDPSession(p);
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 8 });   /* slow frames: Hold 60 fps cuts the population */
      let culled = true;
      await p.waitForFunction(() => !document.getElementById("ro-gov").hidden, null, { timeout: 180000, polling: 250 }).catch(() => { culled = false; });
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
      await p.click("#pausebtn");
      const c1 = await claim(p), n1 = (await stats(p))[0];
      ok(culled && c1 === "no:governed", "Hold 60 fps cut the population (to " + n1 + " fish): the run does not replay (" + c1 + ")");
      const said2 = await loadFile(p, "empty.json", "{}");
      const c2 = await claim(p), g2 = await govShown(p);
      const said3 = await loadFile(p, "broken.json", "{ not json");
      const c3 = await claim(p), g3 = await govShown(p), n3 = (await stats(p))[0];
      await drawer(p, "world");
      await p.evaluate(() => { document.getElementById("err").textContent = ""; });
      await p.fill("#population", "-1");
      await p.click("#restart");
      await p.waitForFunction(() => document.getElementById("err").textContent !== "", null, { timeout: 10000 });
      const said4 = await say(p), c4 = await claim(p), g4 = await govShown(p), n4 = (await stats(p))[0];
      ok(/load that checkpoint/.test(said2) && /load that checkpoint/.test(said3) && /evo_init failed/.test(said4) &&
         c2 === "no:governed" && c3 === "no:governed" && c4 === "no:governed" && g2 && g3 && g4 && n3 === n1 && n4 === n1,
         "refused: {} (" + c2 + ", badge " + g2 + "), malformed JSON (" + c3 + ", " + g3 + "), Restart with -1 fish (" + c4 + ", " + g4 +
         "); the world kept its " + n1 + " fish (" + n3 + ", " + n4 + ")");
      await p.fill("#population", "300");
      await p.click("#restart");
      await p.waitForTimeout(300);
      const c5 = await claim(p), g5 = await govShown(p);
      ok(c5 === "yes" && !g5, "an accepted Restart is a new run: it replays (" + c5 + "), the governed badge is gone (" + g5 + ")");
      errsOk(p, "refusals");
    } finally { await ctx.close(); }
  },
  /* review of #88, P2-3: the floor's tip says the floor the running world took; a form value it did not take is named as such */
  async floor() {
    section("The reseed floor's tip: a loaded world's floor, not the form's");
    let text = "";
    {
      const ctx = await launch();
      try {
        const p = await open(ctx, "&threads=0");
        await drawer(p, "world");
        await setField(p, "adv_minPopulation", 0);   /* live: this run's floor is 0 */
        await p.waitForTimeout(200);
        const tip0 = floorSaid(await tipOf(p, "f_population"));
        await drawer(p, "run");
        const [dl] = await Promise.all([p.waitForEvent("download"), p.click("#savecp")]);
        text = fs.readFileSync(await dl.path(), "utf8");
        const cfg = (JSON.parse(text).config || {});
        ok(tip0.run === 0 && tip0.form === null && cfg.minPopulation === 0,
           "floor 0 applied live: the tip says this run's 0, no pending value (" + JSON.stringify(tip0) + "); the saved world's floor is " + cfg.minPopulation);
        errsOk(p, "floor (save)");
      } finally { await ctx.close(); }
    }
    {
      const ctx = await launch();
      try {
        const p = await open(ctx, "&threads=0");
        await drawer(p, "world");
        const before = floorSaid(await tipOf(p, "f_population"));
        const said = await loadFile(p, "floor0.json", text);
        await p.waitForTimeout(200);
        const after = floorSaid(await tipOf(p, "f_population")), form = await p.inputValue("#adv_minPopulation"), c = await claim(p);
        ok(before.run === 50 && /Checkpoint loaded/.test(said) && after.run === 0 && after.form === 50 && form === "50" && c === "no:loaded",
           "a fresh page says 50 (" + JSON.stringify(before) + "); the world with floor 0 loaded: the tip says this run's 0 and that the form's 50 " +
           "is not in it (" + JSON.stringify(after) + "; " + c + ")");
        errsOk(p, "floor (load)");
      } finally { await ctx.close(); }
    }
  },
  /* review of #88, round 2: the floor is a whole number to the engine (an (int) cast): a fractional live edit is refused,
   * and one that reaches a start (typed during Turbo, which takes no edit, then Restart) is said as the engine runs it */
  async fractional() {
    section("A fractional reseed floor: refused live; a start takes it as the engine reads it (0.5 runs as 0)");
    const ctx = await launch();
    try {
      const p = await open(ctx, "&threads=0");
      await drawer(p, "world");
      const tries = [];
      for (const typed of ["0.5", "49.9"]) {
        await p.evaluate(() => { document.getElementById("err").textContent = ""; });
        await setField(p, "adv_minPopulation", typed);
        await p.waitForTimeout(200);
        tries.push({ typed, said: await say(p), field: await p.inputValue("#adv_minPopulation"), tip: floorSaid(await tipOf(p, "f_population")), claim: await claim(p) });
      }
      ok(tries.every((t) => /whole number/.test(t.said) && t.field === "50" && t.tip.run === 50 && t.tip.form === null && t.claim === "yes"),
         "typed live: " + tries.map((t) => t.typed + " refused (\"" + t.said.slice(0, 45) + "…\"), the field back to " + t.field + ", the tip " +
         JSON.stringify(t.tip) + ", " + t.claim).join("; "));
      await closeDrawer(p);
      await p.click("#turbobtn");
      await p.waitForFunction(() => !document.getElementById("turboexit").disabled, null, { timeout: 60000, polling: 100 });
      await drawer(p, "world");
      await setField(p, "adv_minPopulation", "0.5");   /* (Turbo takes no live edit: it stays in the form) */
      await closeDrawer(p);
      await p.click("#turboexit");
      await p.waitForFunction(() => document.getElementById("turbobtn").getAttribute("aria-pressed") === "false" &&
                                    !document.getElementById("turbobtn").disabled, null, { timeout: 60000, polling: 100 });
      await drawer(p, "world");
      await p.click("#restart");
      await p.waitForTimeout(300);
      const tip = floorSaid(await tipOf(p, "f_population")), field = await p.inputValue("#adv_minPopulation");
      await drawer(p, "run");
      const [dl] = await Promise.all([p.waitForEvent("download"), p.click("#savecp")]);
      const engine = (JSON.parse(fs.readFileSync(await dl.path(), "utf8")).config || {}).minPopulation;
      ok(field === "0.5" && engine === 0 && tip.run === 0 && tip.form === null,
         "0.5 typed during Turbo, then Restart: the engine runs floor " + engine + " (its saved world); the tip says " + JSON.stringify(tip) +
         " (the form's " + field + " is what runs, as a whole number), not 0.5");
      errsOk(p, "fractional");
    } finally { await ctx.close(); }
  },
  /* review of #88, P2-3: Classic's Turbo takes no live edit, so the form's value is not the run's */
  async turbo() {
    section("The reseed floor's tip: an edit made during Turbo, which Turbo does not take");
    const ctx = await launch();
    try {
      const p = await open(ctx, "&threads=0");
      await p.click("#turbobtn");
      await p.waitForFunction(() => !document.getElementById("turboexit").disabled, null, { timeout: 60000, polling: 100 });
      await drawer(p, "world");
      await setField(p, "adv_minPopulation", 0);
      await p.waitForTimeout(200);
      const during = floorSaid(await tipOf(p, "f_population"));
      await closeDrawer(p);
      await p.click("#turboexit");
      await p.waitForFunction(() => document.getElementById("turbobtn").getAttribute("aria-pressed") === "false" &&
                                    !document.getElementById("turbobtn").disabled, null, { timeout: 60000, polling: 100 });
      await drawer(p, "world");
      const back = floorSaid(await tipOf(p, "f_population"));
      ok(during.run === 50 && during.form === 0 && back.run === 50 && back.form === 0,
         "floor 0 typed during Turbo: the tip says this run's 50 and the form's 0 not in it (" + JSON.stringify(during) + "), and after Turbo (" + JSON.stringify(back) + ")");
      errsOk(p, "turbo");
    } finally { await ctx.close(); }
  }
};

const names = Object.keys(CASES).filter((n) => !ONLY.length || ONLY.includes(n));
const t0 = Date.now();
const release = await acquire("classic replay claims");
try {
  console.log("Classic at " + BASE + "/web/index.html");
  for (const n of names) {
    try { await CASES[n](); } catch (e) { ok(false, n + " threw: " + String(e && e.message || e).split("\n")[0]); }
  }
} finally { release(); }
console.log("\n" + (checks - failures) + " / " + checks + " checks passed in " + ((Date.now() - t0) / 1000).toFixed(1) + " s");
process.exit(failures ? 1 : 0);
