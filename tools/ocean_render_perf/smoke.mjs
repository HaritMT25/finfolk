// tools/ocean_render_perf/smoke.mjs: console / page / network errors of the site's pages in headless Brave, one page at a time under
// the browser lock: the Ocean page (the default policy, then the reference pipeline: ?renderOpt=0, then with the page's own
// colour modes), the Classic page and the body plan's check page. A page passes when it reaches its ready state with no console
// error or warning, page error, failed request or HTTP error status.
//   node smoke.mjs --web http://localhost:8182 [--root http://localhost:8183]   (--web: web/ as the root; --root: the repository root, for the body plan)
import { createRequire } from "node:module";
import { acquire } from "./lock.mjs";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : def; }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const WEB = arg("web", "http://localhost:8182").replace(/\/$/, ""), ROOT = arg("root", "").replace(/\/$/, "");
const { chromium } = require(PW);

const PAGES = [
  ["ocean (default policy)", WEB + "/ocean.html?guide=0&intro=0&seed=42&pop=600", async (p) => { await p.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && EvoOcean.state() && EvoOcean.state().frame > 30, null, { timeout: 90000, polling: 250 }); await p.waitForTimeout(6000);
    return await p.evaluate(() => ({ policy: EvoOcean.scene.renderOptimization().effective, failures: EvoOcean.scene.renderOptimization().failures, appearance: EvoOcean.scene.appearance(), n: EvoOcean.state().n })); }],
  ["ocean (?renderOpt=0, the reference pipeline)", WEB + "/ocean.html?guide=0&intro=0&seed=42&pop=600&renderOpt=0", async (p) => { await p.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && EvoOcean.state() && EvoOcean.state().frame > 30, null, { timeout: 90000, polling: 250 }); await p.waitForTimeout(3000);
    return await p.evaluate(() => ({ policy: EvoOcean.scene.renderOptimization(), n: EvoOcean.state().n })); }],
  ["ocean (family colours)", WEB + "/ocean.html?guide=0&intro=0&seed=7&pop=400&colour=family", async (p) => { await p.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && EvoOcean.state() && EvoOcean.state().frame > 30, null, { timeout: 90000, polling: 250 }); await p.waitForTimeout(5000);
    return await p.evaluate(() => ({ policy: EvoOcean.scene.renderOptimization().effective, mode: EvoOcean.state().colourMode })); }],
  /* (Classic's background is ../img/rocks.jpg: served from the repository root, as the built site does; under a web/ root it is a 404 on any commit) */
  ["classic", (ROOT ? ROOT + "/web" : WEB) + "/index.html", async (p) => { await p.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true, null, { timeout: 90000, polling: 250 }).catch(() => {}); await p.waitForTimeout(5000); return {}; }]
];
if (ROOT) PAGES.push(["body plan (check page)", ROOT + "/web/ocean_bodyplan.html?check=1", async (p) => { await p.waitForTimeout(15000); return await p.evaluate(() => ({ title: document.title, status: (document.getElementById("status") || {}).textContent || "" })); }]);

const release = await acquire("builder-render smoke");
let fails = 0;
try {
  for (const [name, url, run] of PAGES) {
    const ctx = await chromium.launchPersistentContext("", { executablePath: BRAVE, headless: true, viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, args: ["--no-first-run", "--no-default-browser-check"] });
    const page = ctx.pages()[0] || await ctx.newPage(), errs = [];
    page.on("pageerror", (e) => errs.push("pageerror: " + String(e)));
    page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errs.push(m.type() + ": " + m.text()); });
    page.on("requestfailed", (r) => errs.push("requestfailed: " + r.url()));
    page.on("response", (r) => { if (r.status() >= 400) errs.push("http " + r.status() + ": " + r.url()); });
    let info = null;
    try { await page.goto(url); info = await run(page); } catch (e) { errs.push("threw: " + String(e && e.message || e)); }
    const ok = errs.length === 0;
    if (!ok) fails++;
    console.log((ok ? "  ok   " : "  FAIL ") + name + "  " + JSON.stringify(info).slice(0, 400) + (ok ? "" : "\n         " + errs.slice(0, 6).join("\n         ")));
    await ctx.close();
  }
} finally { release(); }
console.log(fails ? "FAIL: " + fails + " pages" : "ok: " + PAGES.length + " pages without a console message");
process.exit(fails ? 1 : 0);
