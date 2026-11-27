// tests/classic_safety_tests.cjs: 2-D Classic's run safety (web/renderer.js, web/worker.js), in node with the real
// single-threaded module and the real Turbo worker (web/worker.js in a vm context with a worker's globals), no browser:
//   node tests/classic_safety_tests.cjs   (exit 0 = pass)
//   1. the worker's "set" command: no world (before a start, after a stop), a live value applied between chunks, the
//      engine's refusals (not a live key, a negative value), and the hand-back's checkpoint carrying the applied value
//   2. the replace rule (the Ocean's): a fresh run starts at once (R, Restart with the running seed and fish, as the UI
//      parity harness sets them); five simulated minutes ask before R, the dice, Randomize the world and Load world, Keep
//      it and Esc keep the run, Replace it starts a new seed; edits waiting and a live tweak ask, in the Ocean's words; a
//      question the keyboard opened takes the focus and gives it back; a live value the engine refuses goes back in its
//      field (the value that runs, said so), and is no tweak
//   3. a live edit during Turbo: forwarded to the worker and confirmed, a whole-number key refused as it is live, a value
//      the worker's engine refuses put back in its field, edits made while Turbo starts or hands back held and applied,
//      every value read back from the engine after the hand-back; Turbo's world lost (its worker failed): the page's own
//      copy takes the values the worker had applied; Turbo used asks before the next start
//   4. the failure screens: a start that fails (the loading bar stopped, the error, Open 3-D Ocean and Reload; no Ocean
//      without WebAssembly SIMD), and an engine trap mid-run (the engine stopped, Reload; nothing more reaches the module)
//   5. the review of PR #104 (each case fails on 25413b1): a file JSON.parse refuses but the engine's reader takes
//      ("formatVersion": +N) is refused before the engine, never loaded unasked; after a trap no call reaches the module from
//      any path (a file read on its way, Save world, the switches, the canvas, the keys) and the page behind the screen is
//      inert; values a failed worker never answered are applied to the recovered world or refused and put back; held values
//      in order (an older refusal leaves a newer value's field alone); a frame error that persists is said once, retried
//      once a second, and the tank falls back to the flat view; the record of what runs is the engine's (a loaded floor of
//      0.5 runs as 0, the speeds the engine put in order, a float said as typed)
//   6. the second review of PR #104 (6a and 6c fail on fe5f9e6): two values that print the same at seven digits but run as
//      two (1.5, 1.5000001) are a live tweak and a change of history; the page's record of every live value is the engine's,
//      value for value (the rule it keeps it by, with no read of the world but for the speeds and the predator floor);
//      values the engine cannot keep (past float32, ten-digit whole numbers) refused first, here and in Turbo; a world whose
//      checkpoint stopped being JSON (a fish's energy overflowed) contained here, in the worker, in its recovery, at the hand-back
//   7. the third review of PR #104 (Hydrogen; 7a, 7b and 7c fail on 56418d1): an engine trap outside the frame (Restart, R,
//      Save world, Load world after its read, a live value, Turbo's start and hand-back, the colour switch, a tap on the world,
//      the tour's fish, the dashboards' module) stops the engine, nothing escapes, nothing reaches the module after; Reset
//      every setting withdraws an open question; no key acts behind the failure screen; a refused Restart keeps what waits;
//      Fit asks and 299.98 simulated seconds do not; a file read a newer pick or a new world overtook is dropped; each
//      fallback step's failure is logged and the fish-shapes switch follows WebGL's
//   8. the fourth review of PR #104 (Codex; 8a and 8b fail on 0c99c69, 8c on 56418d1): decisions on what was submitted, so a
//      %.9g decimal tie the page's rounding breaks the other way (100000004.5) is a change (history, the question); the
//      record read once at the first edit after a load (a loaded floor of 2001, clamped to 2000 by an unrelated edit's
//      setter: a refusal says 2000), later ordinary edits reading nothing; a trap in evo_checkpoint itself during a read the
//      clamps asked for stops the engine here and kills the worker there, the page taking its world back; the worker's own
//      whole-number checks (section 1)
//   9. the fifth reviews of PR #104 (Codex and Hydrogen, 6fdf8d0; each case fails there): live tweaks are a flag, any
//      accepted live edit since the start whatever its value (the speeds' swap then one set back, the value that runs
//      typed), cleared by a start or a load, while a stepper pressed at its bound edits nothing; a refused value's field
//      goes back to what the engine runs, read from it (the decimal tie after an earlier edit, a record made wrong; here
//      and in Turbo, a refusal the page made there put right by the worker's config); a trap inside a nested fence (the
//      real dashboards' reset) ends the whole operation; a trap in the worker stops its pump at once; a cap below 0 and a
//      predator floor past 2000 refused, not clamped; a Turbo start that throws goes back to live; a world never drawn
//      shows the failure screen; R whose start is refused keeps the seed
//   (round 5 changed what three earlier cases asserted: a live value set back to the one it started with, or the same
//   value, is a live tweak now; the question's words for the tweaks; a refusal reads the engine once: 2, 6a, 8a, 8b)
// The page runs on tests/ui_inspector_tests.cjs's small DOM and window (its ids from web/index.html).
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { pageIds, makeDom, makeWindow, recorder } = require("./ui_inspector_tests.cjs");
const WEB = path.join(__dirname, "..", "web");
const read = (f) => fs.readFileSync(path.join(WEB, f), "utf8");
const createClassic = require(path.join(WEB, "evo_boids.js"));
const mkClassic = () => createClassic({ locateFile: (p) => path.join(WEB, p) });
const buf = (M) => (M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer);

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 600) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }
const until = async (pred, what, ms) => {
  const t0 = Date.now();
  while (!pred()) { if (Date.now() - t0 > (ms || 60000)) throw new Error("timed out: " + what); await new Promise((r) => setTimeout(r, 5)); }
};
const tickOf = (M) => { M._evo_sync(); return new Float64Array(buf(M), M._evo_stats(), 4)[3]; };
const configOf = (M) => JSON.parse(M.UTF8ToString(M._evo_checkpoint())).config;

/* web/worker.js in a vm context: a dedicated worker's globals; its module script is the node factory (importScripts
 * loads nothing), its messages go to onPost; its MessageChannel a macrotask per message, as in a browser (node's own
 * drains a port that posts to itself before any timer runs) */
function makeWorker(onPost) {
  class Chan {
    constructor() {
      const p1 = { onmessage: null };
      this.port1 = p1;
      this.port2 = { postMessage: (d) => setImmediate(() => { if (p1.onmessage) p1.onmessage({ data: d }); }) };
    }
  }
  /* (WebAssembly: the host's, as the module the worker runs is the host's: its traps are that realm's RuntimeError) */
  const ctx = { console, performance, MessageChannel: Chan, setTimeout, clearTimeout, WebAssembly, onmessage: null };
  ctx.importScripts = () => {};
  ctx.createEvoBoids = () => mkClassic();
  ctx.postMessage = (m) => onPost(m);
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(read("worker.js"), ctx, { filename: "worker.js" });
  return { ctx, send: (m) => ctx.onmessage({ data: m }) };
}
/* the page's Worker: the vm worker, messages both ways a task later (as a browser's); terminate stops both */
const workers = [];
class FakeWorker {
  constructor() {
    this.dead = false; this.onmessage = null; this.onerror = null;
    this.w = makeWorker((m) => setImmediate(() => { if (!this.dead && this.onmessage) this.onmessage({ data: m }); }));
    workers.push(this);
  }
  postMessage(m) {
    if (m && m.cmd === "set") this.sets = (this.sets || 0) + 1;
    const c = structuredClone(m);
    setImmediate(() => {   /* (an exception in the worker's handler is its error event, as a browser's: the page's onerror) */
      if (this.dead) return;
      try { this.w.send(c); }
      catch (e) { if (this.onerror) this.onerror({ message: "Uncaught " + (e && e.message || e), preventDefault() {} }); }
    });
  }
  terminate() { this.dead = true; if (this.w.ctx.running !== undefined) vm.runInContext("running = false;", this.w.ctx); }
}

/* ======================================================== 1. the worker ======================================================== */
async function workerSet() {
  section("1. web/worker.js: the live-setting command");
  const got = [];
  const W = makeWorker((m) => got.push(m));
  const last = (type) => got.filter((m) => m.type === type).pop();
  W.send({ cmd: "set", key: "targetFood", value: 900 });
  ok(got.length === 1 && got[0].type === "set" && got[0].ok === false && got[0].notRunning === true && got[0].key === "targetFood",
     "before any start: refused as notRunning (no world here), so the page keeps the value", got[0]);
  const A = await mkClassic();
  ok(A._evo_init(42, 1920, 1080, 300, 0) === 1, "a world to hand over: seed 42, 300 fish");
  W.send({ cmd: "start", checkpoint: A.UTF8ToString(A._evo_checkpoint()), js: "evo_boids.js", wasm: "evo_boids.wasm", threads: 1, recEvery: 60 });
  await until(() => got.some((m) => m.type === "stats"), "the worker's first stats");
  await until(() => (last("stats") || {}).totalSteps > 0, "the worker stepping");
  const n0 = got.length;
  W.send({ cmd: "set", key: "targetFood", value: 900, quiet: false });
  W.send({ cmd: "set", key: "foodPatches", value: 3 });
  W.send({ cmd: "set", key: "foodEnergy", value: -1 });
  W.send({ cmd: "set", key: "maxPopulation", value: 400, quiet: true });
  W.send({ cmd: "set", key: "minSpeed", value: 200, readback: true });
  W.send({ cmd: "set", key: "metabolicRate", value: 1e39 });
  W.send({ cmd: "set", key: "targetFood", value: 0.5 });
  W.send({ cmd: "set", key: "minPopulation", value: 1e12 });
  const sets = got.slice(n0).filter((m) => m.type === "set");
  ok(sets.length === 8 && sets[0].ok === true && sets[0].value === 900 && sets[0].quiet === false && !sets[0].notRunning,
     "Turbo running: targetFood 900 applied between chunks, answered ok", sets[0]);
  ok(sets[0].config === null && sets[4].ok === true && sets[4].config && sets[4].config.minSpeed === 150 && sets[4].config.maxSpeed === 200 && !sets[4].configError,
     "  asked to read back (minSpeed 200, a key the engine's clamps move): its answer carries the world's config as the engine holds it " +
     "(the speeds swapped: 150 / 200); a plain value's answer reads nothing (config null)", [sets[0].config, sets[4].config && [sets[4].config.minSpeed, sets[4].config.maxSpeed]]);
  ok(sets[5].ok === false && /metabolicRate is too large for the engine/.test(sets[5].error),
     "  metabolicRate 1e39 (finite, but past float32: it would run as infinity and break every checkpoint): refused before it is applied", sets[5]);
  ok(sets[6].ok === false && sets[6].error === "targetFood must be a whole number" &&
     sets[7].ok === false && sets[7].error === "minPopulation is too large for the engine (it keeps whole numbers of up to nine digits)",
     "  the page's whole-number checks, made by the worker too: targetFood 0.5 and minPopulation 1e12 refused there", [sets[6].error, sets[7].error]);
  ok(sets[1].ok === false && /not a live parameter/.test(sets[1].error) && !sets[1].notRunning,
     "  foodPatches (not live): the engine refuses it, with its reason", sets[1]);
  ok(sets[2].ok === false && /finite and >= 0/.test(sets[2].error), "  foodEnergy -1: the engine refuses it", sets[2]);
  ok(sets[3].ok === true && sets[3].quiet === true, "  maxPopulation 400 (quiet: the governor's cap), applied and the quiet flag echoed", sets[3]);
  W.send({ cmd: "stop" });
  await until(() => got.some((m) => m.type === "checkpoint"), "the hand-back's checkpoint");
  const cp = JSON.parse(last("checkpoint").json);
  ok(cp.config.targetFood === 900 && cp.config.maxPopulation === 400 && cp.config.foodEnergy === 5 && cp.config.metabolicRate === 1.5 && cp.config.minPopulation === 50 && cp.world.frame > 0,
     "the hand-back's checkpoint carries the applied values (targetFood 900, maxPopulation 400; foodEnergy still 5) at frame " + cp.world.frame,
     [cp.config.targetFood, cp.config.maxPopulation, cp.config.foodEnergy]);
  W.send({ cmd: "set", key: "targetFood", value: 700 });
  const after = last("set");
  ok(after.ok === false && after.notRunning === true, "after the stop: notRunning again", after);
}

/* ======================================================== the page ======================================================== */
/* o: a loader to use instead of the module's (a start that fails), a canvas context factory (the world's 2D drawing),
 * the view (flat by default), a stand-in tank scene (web/scene3d.js), a stand-in dashboard (dash) or the real one
 * (realDash: web/dash_data.js, charts.js, dashboard.js) */
async function bootPage(o) {
  o = typeof o === "function" ? { load: o } : (o || {});
  const D = makeDom(pageIds(read("index.html")), o.canvas || ((c) => (c.id === "canvas" || c.id === "inetc" ? recorder() : null)));
  const P = makeWindow(D, "http://classic.test/web/index.html?threads=0&view=" + (o.view || "flat") + "&guide=0&intro=0", { media: ["min-width: 960px"] });
  const box = { M: null };
  if (o.scene) P.ctx.EvoScene = o.scene;
  if (o.gl) P.ctx.EvoGL = o.gl;   /* (a stand-in for web/gl_renderer.js: the flat view's WebGL drawing) */
  if (o.dash) {   /* (the dashboards' attach gets runConfig: the page's record of what runs) */
    P.ctx.EvoDash = { attach: (h) => { box.host = h; }, pump() {}, reset() {}, ingest() {}, every: () => 60, open() {}, close() {}, isOpen: () => false };
  }
  const load = o.load;
  P.ctx.EVO_ASSETS = { st: "evo_boids.js", stWasm: "evo_boids.wasm", mt: "evo_boids_mt.js", mtWasm: "evo_boids_mt.wasm", worker: "worker.js", background: "rocks.jpg", three: "three.js" };
  P.ctx.EvoLoader = { load: load || (() => mkClassic().then((m) => { box.M = m; return { Module: m, threaded: false, why: "the test", js: "evo_boids.js", wasm: "evo_boids.wasm" }; })),
                      poolThreads: () => 1 };
  P.ctx.Worker = FakeWorker;
  vm.createContext(P.ctx);
  const files = ["ui_common.js", "randomizer.js"].concat(o.realDash ? ["dash_data.js", "charts.js", "dashboard.js"] : [], ["renderer.js"]);
  for (const f of files) vm.runInContext(read(f), P.ctx, { filename: f });
  const el = (id) => D.doc.getElementById(id);
  const fire = (e, type) => e.dispatchEvent(new D.Ev(type, { bubbles: true }));
  /* a field typed and left: input while typing, then change (the live ones apply on change) */
  const setField = (id, v) => { const e = el(id); e.value = String(v); fire(e, "input"); fire(e, "change"); };
  return { D, P, box, el, fire, setField };
}

async function pageRules() {
  section("2. the replace rule: a fresh run starts at once; a run with something to lose asks first");
  const G = await bootPage();
  const { D, P, box, el, setField } = G;
  await until(() => P.ctx.EvoApp && P.ctx.EvoApp.ready, "Classic's page to start");
  const M = box.M;
  let inits = 0;
  const init0 = M._evo_init;
  M._evo_init = function () { inits++; return init0.apply(this, arguments); };
  const asked = () => !el("startask").hidden;
  const msg = () => el("startaskmsg").textContent;
  const said = () => el("err").textContent;
  const drawerOpen = () => el("drawer").classList.contains("open");
  const why = () => el("modeline").dataset.why || "";
  const paused = () => el("pausebtn").getAttribute("aria-label") === "play";
  const settle = () => { for (let i = 0; i < 2; i++) P.frame(); };
  const age = (steps) => { M._evo_step(steps); M._evo_sync(); settle(); };
  el("pausebtn").click(); settle();
  ok(paused() && tickOf(M) === 0 && !asked(), "booted: seed 42, 300 fish, paused at tick 0, no question");

  /* the UI parity harness's start: the running seed and fish typed (input events), then Restart */
  el("seed").value = "42"; G.fire(el("seed"), "input"); el("population").value = "300"; G.fire(el("population"), "input");
  el("restart").click(); settle();
  ok(inits === 1 && !asked() && tickOf(M) === 0, "the harness's start (seed 42 and 300 typed, the values that run, then Restart): it starts at once, no question", [inits, asked()]);

  const seed0 = el("seed").value;
  P.key("r"); settle();
  ok(inits === 2 && !asked() && el("seed").value !== seed0 && tickOf(M) === 0, "a fresh run: R starts a new seed at once (" + seed0 + " -> " + el("seed").value + ")");

  age(18750);   /* 18750 steps of 0.016 s: five simulated minutes */
  const seed1 = el("seed").value, t1 = tickOf(M);
  P.key("r"); settle();
  ok(asked() && inits === 2 && t1 === 18750 && tickOf(M) === t1 && el("seed").value === seed1 && drawerOpen(),
     "five simulated minutes: R asks (the settings open), nothing replaced yet", [asked(), inits, t1]);
  ok(msg() === "This replaces your run, and 5 min 0 s of evolution with it." && el("startconfirm").textContent === "Replace it" &&
     el("startcancel").textContent === "Keep it", "  in the Ocean's words: " + JSON.stringify(msg()) + ", Replace it / Keep it");
  ok(D.doc.activeElement === el("startconfirm"), "  R is the keyboard: the question takes the focus (its Replace it)");
  P.key("Escape"); settle();
  ok(!asked() && inits === 2 && tickOf(M) === t1 && el("seed").value === seed1 && said() === "Kept your run.",
     "Esc: the question goes, the run is kept (tick " + tickOf(M) + ", seed " + seed1 + "), and it says so", [said()]);
  el("randombtn").click(); settle();
  const pop0 = el("population").value, form0 = el("adv_targetFood").value;
  ok(asked() && inits === 2 && /^This replaces your run, and 5 min 0 s of evolution with it\. It starts a new random world \(\d+ fish/.test(msg()) &&
     el("population").value === pop0, "the dice, same state: asks, naming the random world it would start; the form untouched until then", msg());
  el("startcancel").click(); settle();
  ok(!asked() && inits === 2 && el("population").value === pop0 && el("adv_targetFood").value === form0 && tickOf(M) === t1, "  Keep it: the run and the form stay");
  el("randombig").click(); settle();
  ok(asked() && /It starts a new random world/.test(msg()), "Randomize the world (the Run tab's): asks the same");
  el("startcancel").click(); settle();
  const json = M.UTF8ToString(M._evo_checkpoint());
  el("cpfile").files = [{ name: "w.json", text: () => Promise.resolve(json) }];
  G.fire(el("cpfile"), "change");
  await new Promise((r) => setTimeout(r, 20)); settle();
  ok(asked() && msg() === "This replaces your run, and 5 min 0 s of evolution with it. It opens the saved world w.json (frame " + (18750).toLocaleString() + ", " +
     M._evo_creature_count().toLocaleString() + " fish, 1920 × 1080)." && el("startconfirm").textContent === "Open it" && !/loaded/.test(why()),
     "Load world, same state: asks before opening, naming the saved world (Open it / Keep it)", msg());
  P.key("Escape"); settle();
  ok(!asked() && !/loaded/.test(why()) && said() === "Kept your run.", "  Esc: not opened");
  P.key("r"); settle();
  el("startconfirm").click(); settle();
  ok(!asked() && inits === 3 && tickOf(M) === 0 && el("seed").value !== seed1, "R again, Replace it: a new world with a new seed (" + el("seed").value + "), at tick 0", [inits, tickOf(M)]);

  /* a question a button opened from the keyboard (a click no pointer made): the focus to the answer, and back */
  age(18750);
  D.doc.modality = "keyboard"; el("restart").focus();
  el("restart").dispatchEvent(new D.Ev("click", { bubbles: true, detail: 0 })); settle();
  ok(asked() && D.doc.activeElement === el("startconfirm"), "Restart pressed from the keyboard: asks, the focus on Replace it");
  P.key("Escape");
  ok(!asked() && D.doc.activeElement === el("restart"), "  Esc: kept, the focus back on Restart");
  D.doc.modality = "pointer";   /* (a pointer's press: no focus ring) */
  el("restart").click(); settle();
  ok(asked() && D.doc.activeElement !== el("startconfirm"), "Restart pressed with a pointer: asks, the focus stays where it was (a stray Space must not replace the run)");
  if (el("drawer").classList.contains("open")) el("drawerclose").click();
  settle();
  ok(!asked() && inits === 3, "  closing the settings: the question goes, the run is kept");
  el("restart").click(); settle();
  el("startconfirm").click(); settle();
  ok(inits === 4 && tickOf(M) === 0, "  Restart, Replace it: started");

  /* edits waiting */
  setField("predators", 3); settle();
  el("restart").click(); settle();
  ok(asked() && msg() === "This replaces your run. It starts with what waits: Predators 3." && el("restart").querySelector("span").textContent === "Restart to apply",
     "an edit waiting (Predators 3), Restart to apply: asks, naming what waits", msg());
  setField("foodPatches", 2); settle();
  ok(!asked() && said() === "The setup changed: start again to review it.", "  an edit while it asks: the question goes (never a start other than the one asked about)");
  el("restart").click(); settle();
  ok(asked() && msg() === "This replaces your run. It starts with what waits: Predators 3, Food patches 2.", "  asked again, with both", msg());
  el("startconfirm").click(); settle();
  ok(inits === 5 && M._evo_predator_count() === 3, "  Replace it: the new world has its 3 predators", M._evo_predator_count());
  setField("predators", 3); settle();
  el("restart").click(); settle();
  ok(!asked() && inits === 6, "a field set to the value the run has: nothing waits, Restart starts at once");

  /* a live value the engine refuses: the field back to what runs, and said */
  setField("adv_targetFood", -5); settle();
  ok(said() === "targetFood must be finite and >= 0 (the running world keeps 600)." && el("adv_targetFood").value === "600" && configOf(M).targetFood === 600,
     "a live value the engine refuses (Food target -5): the field back to the 600 that runs, the error says so", [said(), el("adv_targetFood").value]);
  ok(el("startask").hidden, "  (a refused value is no live tweak: nothing to ask about)");
  /* a live tweak */
  setField("adv_targetFood", 900); settle();
  ok(said() === "Food target is now 900 (live)" && configOf(M).targetFood === 900, "a live edit applies at once (Food target 900)", said());
  el("restart").click(); settle();
  /* (round 5: a Restart starts from the sheet, which shows the tweaks; the dice's world has its own settings) */
  ok(asked() && msg() === "This replaces your run. Your live tweak (Food target 900) carries over to the new world, as the sheet shows it.",
     "  Restart: asks (a live tweak), and says it carries over", msg());
  el("startcancel").click();
  el("randombtn").click(); settle();
  ok(asked() && /Your live tweak \(Food target 900\) goes: the random world has its own settings\.$/.test(msg()),
     "  the dice: the tweak goes, the random world has its own settings", msg());
  el("startcancel").click();
  el("cpfile").files = [{ name: "w.json", text: () => Promise.resolve(json) }];
  G.fire(el("cpfile"), "change");
  await new Promise((r) => setTimeout(r, 20)); settle();
  ok(asked() && /Your live tweak \(Food target 900\) goes: the saved world has its own settings\.$/.test(msg()), "  Load world: the tweak goes with the run", msg());
  el("startconfirm").click(); settle();
  ok(!asked() && /loaded/.test(why()) && tickOf(M) === 18750 && configOf(M).targetFood === 600, "  Open it: the saved world (frame 18,750, its own Food target 600)");
  ok(D.errors.length === 0 && P.logs.filter((l) => l[0] === "error").length === 0, "no handler threw, nothing logged as an error", D.errors.slice(0, 2));
  return G;
}

async function turboEdits(G) {
  section("3. a live edit during Turbo reaches the world");
  const { D, P, box, el, setField } = G, M = box.M;
  const said = () => el("err").textContent;
  const state = () => el("turbobtn").disabled ? "moving" : el("turbobtn").getAttribute("aria-pressed") === "true" ? "turbo" : "live";
  const settle = () => { for (let i = 0; i < 2; i++) P.frame(); };
  el("startcancel").click();
  el("restart").click(); settle();
  if (!el("startask").hidden) el("startconfirm").click();
  settle();
  const cfg0 = configOf(M);
  el("turbobtn").click();
  setField("adv_metabolicRate", 1.75);   /* while Turbo starts (a float the engine keeps exactly) */
  ok(said() === "Energy burned per second 1.75 applies as soon as Turbo has started." && configOf(M).metabolicRate === cfg0.metabolicRate,
     "typed while Turbo starts: held (it says when it applies), not lost", said());
  await until(() => state() === "turbo", "Turbo running");
  await until(() => said() === "Energy burned per second is now 1.75 (live)", "the held value confirmed by the worker");
  ok(true, "  Turbo started: the held value went to the worker and it confirmed it");
  setField("adv_targetFood", 777);
  ok(configOf(M).targetFood === cfg0.targetFood, "typed during Turbo (Food target 777): sent to the worker, not this page's frozen copy");
  await until(() => said() === "Food target is now 777 (live)", "the worker's confirmation");
  ok(true, "  confirmed: " + said());
  setField("adv_minPopulation", 0.5);
  ok(/must be a whole number/.test(said()) && el("adv_minPopulation").value === "50", "  0.5 for the reseed floor: refused as it is live, the field back to 50", said());
  setField("adv_maxPopulation", 400);
  await until(() => said() === "Population cap is now 400 (live)", "the cap's confirmation");
  ok(true, "  the population cap 400: confirmed");
  setField("adv_foodEnergy", -1);
  await until(() => /foodEnergy must be finite/.test(said()), "the worker's refusal");
  ok(said() === "foodEnergy must be finite and >= 0 (the running world keeps 5)." && el("adv_foodEnergy").value === "5",
     "  Energy per food -1 during Turbo: the worker's engine refuses it, the field back to the 5 that runs", [said(), el("adv_foodEnergy").value]);
  el("turboexit").click();
  setField("adv_foodEnergy", 6);   /* while Turbo hands back */
  ok(said() === "Energy per food 6 applies as soon as Turbo hands the world back.", "typed while Turbo hands back: held", said());
  await until(() => state() === "live", "the hand-back");
  await until(() => said() === "Energy per food is now 6 (live)", "the held value applied after the hand-back");
  const back = configOf(M);
  ok(back.targetFood === 777 && back.metabolicRate === 1.75 && back.maxPopulation === 400 && back.foodEnergy === 6 && back.minPopulation === 50,
     "read back from the engine after the hand-back: Food target 777, energy burn 1.75, cap 400 (the worker's), Energy per food 6 (held), floor 50",
     [back.targetFood, back.metabolicRate, back.maxPopulation, back.foodEnergy, back.minPopulation]);
  ok(/live/.test(el("modeline").dataset.why), "  the run says a live setting changed during it", el("modeline").dataset.why);
  P.key("r"); settle();
  ok(!el("startask").hidden && /what Turbo ran/.test(el("startaskmsg").textContent), "Turbo used: R asks, naming what Turbo ran", el("startaskmsg").textContent);
  P.key("Escape");

  /* Turbo's world lost: its worker fails after it applied a value */
  el("turbobtn").click();
  await until(() => state() === "turbo", "Turbo running again");
  setField("adv_targetFood", 333);
  await until(() => said() === "Food target is now 333 (live)", "the worker's confirmation (333)");
  const w = workers[workers.length - 1];
  w.onerror({ message: "injected: the worker died" });
  ok(state() === "live" && /The Turbo worker failed: injected/.test(said()) && w.dead, "the worker fails: Turbo ends, said, the worker goes", said());
  ok(configOf(M).targetFood === 333, "  this page's copy (from where Turbo took it) took the value the worker had applied: Food target 333", configOf(M).targetFood);
  el("turbobtn").click();
  await until(() => state() === "turbo", "a fresh worker");
  ok(workers.length >= 2 && workers[workers.length - 1] !== w, "  the next Turbo starts a new worker");
  el("turboexit").click();
  await until(() => state() === "live", "the hand-back");
  ok(D.errors.length === 0 && P.logs.filter((l) => l[0] === "error").length === 0, "no handler threw, nothing logged as an error", D.errors.slice(0, 2));
}

async function engineTrap(G) {
  section("4b. an engine trap mid-run: the engine stopped, Reload");
  const { D, P, box, el } = G, M = box.M;
  if (el("pausebtn").getAttribute("aria-label") === "play") el("pausebtn").click();
  let steps = 0, syncs = 0, inits = 0;
  const sync0 = M._evo_sync, init0 = M._evo_init;
  M._evo_step = () => { steps++; throw new WebAssembly.RuntimeError("unreachable"); };
  M._evo_sync = function () { syncs++; return sync0.apply(this, arguments); };
  M._evo_init = function () { inits++; return init0.apply(this, arguments); };
  P.frame();
  const sp = el("splash"), st = el("splashstate");
  ok(steps === 1 && sp.classList.contains("failed") && !sp.classList.contains("done") && st.className === "error" &&
     st.textContent === "The engine stopped (unreachable), so this world can't go on.\nReload the page to go on.",
     "the step traps: the screen says the engine stopped, and to reload", st.textContent);
  const r = el("splashreload"), o = el("splashocean");
  ok(r && o && r.className === "btn primary" && o.className === "btn" && D.doc.activeElement === r && r.textContent === "Reload" && o.textContent === "Open 3-D Ocean",
     "  its ways on: Reload (first, focused), Open 3-D Ocean");
  ok(/The engine stopped/.test(el("err").textContent), "  and the status line says it too");
  const s0 = syncs;
  for (let i = 0; i < 5; i++) P.frame();
  P.key("r"); el("restart").click(); P.ctx.EvoApp.startTurbo();
  ok(steps === 1 && syncs === s0 && inits === 0 && P.ctx.EvoApp.inspectSomeFish() === false && el("turbobtn").getAttribute("aria-pressed") === "false",
     "  then nothing more reaches the module: five frames, R, Restart, the tour's Turbo and its fish", [steps, syncs - s0, inits]);
  ok(P.logs.some((l) => l[0] === "error" && /the engine stopped: unreachable/.test(l[1])), "  logged once to the console");
}

async function startFailures() {
  section("4a. a start that fails: the error, Open 3-D Ocean and Reload");
  for (const [what, err, ocean] of [["the module did not load", new Error("could not load evo_boids.js"), true],
                                    ["no WebAssembly SIMD", Object.assign(new Error("this browser has no WebAssembly SIMD"), { noSimd: true }), false]]) {
    const G = await bootPage(() => Promise.reject(err));
    const { D, P, el } = G;
    await new Promise((r) => setTimeout(r, 20));
    const sp = el("splash"), st = el("splashstate"), o = el("splashocean"), r = el("splashreload");
    ok(sp.classList.contains("failed") && !sp.classList.contains("done") && st.className === "error" && st.textContent === "The simulation couldn't start.\n" + err.message,
       what + ": the loading bar stops (.failed), the error in red", st.textContent);
    if (ocean) ok(o && r && o.className === "btn primary" && o.href === "ocean.html" && r.className === "btn" && D.doc.activeElement === o,
                  "  Open 3-D Ocean (first, focused; #to3d's address) and Reload", [o && o.className, o && o.href, r && r.className]);
    else ok(!o && r && r.className === "btn primary" && D.doc.activeElement === r, "  no Ocean offered (it needs SIMD too): Reload only");
    ok(!P.ctx.EvoApp.ready && P.logs.some((l) => l[0] === "error"), "  the page never says ready; the error is logged");
  }
}

/* ======================================================== 5. the review of PR #104 ======================================================== */
/* a started page, paused at tick 0: its module, helpers and a counter of every call into the module (count: the calls since) */
async function startedPage(o) {
  const G = await bootPage(o);
  await until(() => G.P.ctx.EvoApp && G.P.ctx.EvoApp.ready, "Classic's page to start");
  const { P, el, box } = G, M = box.M;
  if (el("pausebtn").getAttribute("aria-label") !== "play") el("pausebtn").click();
  G.settle = (n) => { for (let i = 0; i < (n || 2); i++) P.frame(); };
  G.settle();
  G.said = () => el("err").textContent;
  G.asked = () => !el("startask").hidden;
  G.state = () => (el("turbobtn").disabled ? "moving" : el("turbobtn").getAttribute("aria-pressed") === "true" ? "turbo" : "live");
  G.calls = 0;
  G.watchModule = () => {   /* every export of the module counted from here on */
    for (const k of Object.keys(M)) if (/^_evo_/.test(k) && typeof M[k] === "function") {
      const f = M[k];
      M[k] = function () { G.calls++; return f.apply(this, arguments); };
    }
  };
  G.load = async (name, text) => {
    el("cpfile").files = [{ name, text: () => Promise.resolve(text) }];
    G.fire(el("cpfile"), "change");
    await new Promise((r) => setTimeout(r, 20));
    G.settle();
  };
  return G;
}

/* P1: a file JSON.parse refuses but the engine's reader takes (std::strtod: "+1") never replaces a run unasked */
async function reviewLoadBypass() {
  section("5a. P1: a file the page cannot read never reaches the engine unasked");
  const G = await startedPage(), { box, el } = G, M = box.M;
  const cp = M.UTF8ToString(M._evo_checkpoint());
  const plus = cp.replace(/("formatVersion"\s*:\s*)(\d+)/, "$1+$2");
  let jsRefuses = false;
  try { JSON.parse(plus); } catch (e) { jsRefuses = true; }
  const B = await mkClassic();
  const engineTakes = (() => { const n = B.lengthBytesUTF8(plus) + 1, p = B._malloc(n); B.stringToUTF8(plus, p, n); const r = B._evo_load_checkpoint(p); B._free(p); return r; })();
  ok(plus !== cp && jsRefuses && engineTakes === 1, "the file: \"formatVersion\": +N, which JSON.parse refuses and the engine's own reader loads", [jsRefuses, engineTakes]);
  M._evo_step(18750); M._evo_sync(); G.settle();
  let loads = 0;
  const load0 = M._evo_load_checkpoint;
  M._evo_load_checkpoint = function () { loads++; return load0.apply(this, arguments); };
  await G.load("plus.json", plus);
  ok(loads === 0 && !G.asked() && tickOf(M) === 18750 && /^Couldn't load that checkpoint: it is not valid JSON \(.*\)\. Nothing changed\.$/.test(G.said()),
     "five simulated minutes, then that file: refused before the engine, nothing replaced, and said: " + JSON.stringify(G.said()), [loads, G.asked(), tickOf(M)]);
  await G.load("n.json", "42");
  ok(loads === 0 && G.said() === "Couldn't load that checkpoint: it is not a saved world. Nothing changed.", "  JSON that is no saved world (42): refused the same way", G.said());
  await G.load("cp.json", cp);
  ok(loads === 0 && G.asked() && /It opens the saved world cp\.json/.test(el("startaskmsg").textContent), "  the same world as plain JSON: asked about first, as every saved world is");
}

/* P2: once the engine stopped, nothing reaches the module, from any path; the page behind the screen is inert */
async function reviewStoppedFence() {
  section("5b. P2: the stopped engine is fenced on every way into the module");
  const G = await startedPage(), { D, P, box, el } = G, M = box.M;
  /* the page's top-level parts, there before the trap as the page's HTML has them (this small DOM makes an element on
   * its first use, straight under body) */
  const parts = ["stage", "scene3d", "topbar", "statpanel", "fitbtn", "toasts", "fishcard", "dock", "drawer", "turbo", "dash", "tooltip"];
  parts.forEach((id) => el(id));
  M._evo_step(18750); M._evo_sync(); G.settle();
  const cp = M.UTF8ToString(M._evo_checkpoint());
  let release = null;
  el("cpfile").files = [{ name: "late.json", text: () => new Promise((r) => { release = r; }) }];
  G.fire(el("cpfile"), "change");   /* (a read still on its way when the engine stops) */
  el("pausebtn").click();
  M._evo_step = () => { throw new WebAssembly.RuntimeError("unreachable"); };
  P.frame();
  ok(el("splash").classList.contains("failed"), "the step traps: the engine-stopped screen");
  G.watchModule();
  release(cp);
  await new Promise((r) => setTimeout(r, 20));
  const tries = [];
  const press = (id) => { el(id).click(); tries.push(id); };
  press("savecp"); press("restart"); press("fitbtn"); press("randombtn"); press("randombig"); press("turbobtn"); press("readout");
  for (const id of ["colourBrain", "fishShape", "governor", "view3d"]) { const e = el(id); e.checked = !e.checked; G.fire(e, "change"); tries.push(id); }
  G.setField("adv_targetFood", 900); tries.push("adv_targetFood");
  const cv = el("canvas"); cv._rect = { left: 0, top: 0, right: 100, bottom: 100 };
  cv.dispatchEvent(new D.Ev("click", { bubbles: true, clientX: 10, clientY: 10 })); tries.push("canvas click");
  D.doc.activeElement = null;   /* (the keys from the page itself, not the screen's Reload) */
  P.key("r"); P.key(" "); tries.push("R", "Space");
  P.ctx.EvoApp.startTurbo(); P.ctx.EvoApp.inspectSomeFish(); tries.push("tour hooks");
  for (let i = 0; i < 5; i++) P.frame();
  ok(G.calls === 0 && !G.asked(), "after the trap: the file read that was on its way, " + tries.join(", ") + ", five frames: no call reaches the module (" + G.calls + ")", G.calls);
  ok(parts.every((id) => el(id) && el(id).getAttribute("inert") !== null) && el("splash").getAttribute("inert") === null,
     "  the page behind the screen is inert (" + parts.join(", ") + "); the screen itself is not", parts.filter((id) => !el(id) || el(id).getAttribute("inert") === null));
}

/* P2: Turbo's worker fails with live values it never answered: the recovered world takes them, or refuses them and says so */
async function reviewUnanswered() {
  section("5c. P2: a worker that fails before it answers: its values are applied to the recovered world, or refused");
  const G = await startedPage(), { el, box } = G, M = box.M;
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo running");
  G.setField("adv_targetFood", 777);
  workers[workers.length - 1].onerror({ message: "injected: the worker died" });   /* (before its answer: it never gets the value) */
  await new Promise((r) => setTimeout(r, 20));
  ok(G.state() === "live" && configOf(M).targetFood === 777 && el("adv_targetFood").value === "777" && G.said() === "Food target is now 777 (live)",
     "Food target 777 sent, the worker dead before its answer: this page's world runs 777, the field says 777, and so does the note", [configOf(M).targetFood, el("adv_targetFood").value, G.said()]);
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo running again");
  G.setField("adv_foodEnergy", -1);
  workers[workers.length - 1].onerror({ message: "injected: the worker died" });
  await new Promise((r) => setTimeout(r, 20));
  ok(configOf(M).foodEnergy === 5 && el("adv_foodEnergy").value === "5" && G.said() === "foodEnergy must be finite and >= 0 (the running world keeps 5).",
     "Energy per food -1 sent, the worker dead before its answer: the recovered world refuses it, the field back to 5, said", [el("adv_foodEnergy").value, G.said()]);
}

/* P2: values held while Turbo starts or hands back: an older refusal never overwrites a newer value of its key */
async function reviewHeldOrder() {
  section("5d. P2: held values in order: a refused one leaves a newer one's field alone");
  const G = await startedPage(), { el, box } = G, M = box.M;
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo running");
  el("turboexit").click();
  G.setField("adv_foodEnergy", -1);
  G.setField("adv_foodEnergy", 6);   /* (both held: Turbo is handing back) */
  await until(() => G.state() === "live", "the hand-back");
  await until(() => G.said() === "Energy per food is now 6 (live)", "the held values applied");
  ok(configOf(M).foodEnergy === 6 && el("adv_foodEnergy").value === "6", "while Turbo hands back, -1 then 6: the world runs 6 and the field says 6 (the refusal of -1 left it alone)",
     [configOf(M).foodEnergy, el("adv_foodEnergy").value]);
  el("turbobtn").click();   /* while Turbo starts, the worker then failing: the same, applied here */
  G.setField("adv_foodEnergy", -1);
  G.setField("adv_foodEnergy", 7);
  workers[workers.length - 1].onerror({ message: "injected: the worker died" });
  await new Promise((r) => setTimeout(r, 20));
  ok(G.state() === "live" && configOf(M).foodEnergy === 7 && el("adv_foodEnergy").value === "7", "while Turbo starts, -1 then 7, the worker failing: the world runs 7, the field says 7",
     [configOf(M).foodEnergy, el("adv_foodEnergy").value]);
}

/* P2: a frame that keeps failing (not the engine): said once, tried once a second, said again when it works; the tank falls back */
async function reviewFrameErrors() {
  section("5e. P2: a frame error that persists: said once, retried once a second, the picture back after");
  let boom = false;
  const throwing = () => { const r = recorder(); return new Proxy({}, { get: (t, k) => (k === "fillRect" && boom ? () => { throw new TypeError("boom"); } : r[k]), set: (t, k, v) => { r[k] = v; return true; } }); };
  const G = await startedPage({ canvas: (c) => (c.id === "canvas" ? throwing() : c.id === "inetc" ? recorder() : null) });
  const { P, el, box } = G, M = box.M;
  el("pausebtn").click();   /* (running: a frame steps once) */
  G.settle(3);
  const t0 = tickOf(M), errs = () => P.logs.filter((l) => l[0] === "error").length;
  boom = true;
  let threw = null;
  try { for (let i = 0; i < 30; i++) P.frame(); } catch (e) { threw = e; }
  const t1 = tickOf(M);
  ok(!threw && errs() === 1 && G.said() === "Drawing the world failed (boom); the page tries again once a second." && t1 === t0 + 1,
     "the 2D canvas throws every frame: no error escapes the loop, it is logged once and said once, and the frame is not run again within the second (" + t0 + " -> " + t1 + ")",
     [threw && String(threw), errs(), G.said(), t0, t1]);
  for (let i = 0; i < 61; i++) P.frame();
  ok(tickOf(M) === t1 + 1 && errs() === 1, "  a second later: tried once (tick " + tickOf(M) + "), failing still, nothing more logged");
  boom = false;
  for (let i = 0; i < 61; i++) P.frame();
  const t2 = tickOf(M);
  P.frame(); P.frame();
  ok(G.said() === "The picture is back." && tickOf(M) === t2 + 2 && errs() === 1, "  the canvas works again: the next try draws, it says so, and every frame runs again (" + t2 + " -> " + tickOf(M) + ")");
  /* the tank: its render throws, so the flat view takes over at once */
  let sceneBoom = false;
  const scene = { load: () => Promise.resolve(), create: () => new Proxy({}, { get: (t, k) => {
    if (k === "then" || typeof k === "symbol") return undefined;
    if (k === "render") return () => { if (sceneBoom) throw new TypeError("tank boom"); };
    if (k === "following") return () => false;
    if (k === "project") return () => null;
    if (k === "pick") return () => -1;
    if (k === "quality") return () => 3;
    if (k === "setQuality" || k === "degrade") return () => false;
    return () => {};
  } }) };
  const T = await startedPage({ view: "3d", scene });
  await until(() => T.D.doc.body.classList.contains("view-3d"), "the tank view");
  T.el("pausebtn").click();
  sceneBoom = true;
  let threw2 = null;
  try { for (let i = 0; i < 5; i++) T.P.frame(); } catch (e) { threw2 = e; }
  ok(!threw2 && !T.D.doc.body.classList.contains("view-3d") && T.said() === "The tank view failed (tank boom), so this is the flat view now." &&
     T.P.logs.filter((l) => l[0] === "error").length === 1 && tickOf(T.box.M) >= 4,
     "the tank's render throws: logged once, the flat view takes over at once and runs every frame (tick " + tickOf(T.box.M) + ")", [threw2 && String(threw2), T.said()]);
}

/* P2: the record of what runs is the engine's: a loaded floor of 0.5 runs as 0; the speeds the engine put in order */
async function reviewRecord() {
  section("5f. P2: the record of what runs is the engine's own (reverts and notes say it)");
  const G = await startedPage(), { el, box } = G, M = box.M;
  const cp = JSON.parse(M.UTF8ToString(M._evo_checkpoint()));
  cp.config.minPopulation = 0.5;
  await G.load("half.json", JSON.stringify(cp));
  ok(/Checkpoint loaded/.test(G.said()) && configOf(M).minPopulation === 0, "a saved world whose floor is 0.5: loaded, and the engine runs floor 0");
  G.setField("adv_minPopulation", -1);
  ok(G.said() === "minPopulation must be finite and >= 0 (the running world keeps 0)." && el("adv_minPopulation").value === "0",
     "  -1 refused: the field back to 0 and the error says 0, the floor that runs (not the file's 0.5)", [G.said(), el("adv_minPopulation").value]);
  G.setField("adv_minSpeed", 200);
  const c = configOf(M);
  ok(c.minSpeed === 150 && c.maxSpeed === 200 && G.said() === "Slowest speed is now 150 (live)" && el("adv_minSpeed").value === "150" && el("adv_maxSpeed").value === "200",
     "Slowest speed 200 (above the fastest, 150): the engine puts them in order (150 / 200), and the note and both fields say so", [c.minSpeed, c.maxSpeed, G.said(), el("adv_minSpeed").value, el("adv_maxSpeed").value]);
  G.setField("adv_metabolicRate", 1.7);
  ok(G.said() === "Energy burned per second is now 1.7 (live)" && Math.abs(configOf(M).metabolicRate - 1.7) < 1e-6, "  1.7 (a float the engine keeps as 1.70000005): said as 1.7", G.said());
}

/* ================================================ 6. the second review of PR #104 (fe5f9e6) ================================================ */
const LIVE_FLOATS = ["foodSpawnBase", "foodSpawnAmp", "foodEnergy", "metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy",
                     "newbornEnergy", "mutationMultiplier", "minSpeed", "maxSpeed", "predatorTraitMutation"];
const LIVE_INTS = ["maxPopulation", "minPopulation", "targetFood", "predatorMinPopulation", "predatorMaxPopulation"];
/* the engine's own number for a key, from its checkpoint's text (no JSON.parse: a world that overflowed writes "inf") */
const engineNum = (M, k) => { const m = new RegExp('"' + k + '":\\s*([^,}\\s]+)').exec(M.UTF8ToString(M._evo_checkpoint())); return m ? Number(m[1]) : NaN; };
/* two values the engine keeps as the same number: a float32 for the float keys, a whole number for the others */
const sameKept = (k, a, b) => (LIVE_INTS.indexOf(k) >= 0 ? a === b : Math.fround(a) === Math.fround(b));

/* P1: a live change the seven-digit display hides is still a change: the run's history and the question count it */
async function reviewRounding() {
  section("6a. P1: two values that print the same at seven digits but run as two (1.5 and 1.5000001)");
  const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
  ok(Math.fround(1.5) !== Math.fround(1.5000001) && +Math.fround(1.5000001).toPrecision(7) === 1.5, "the pair: float32 1.5 and 1.50000012, both 1.5 at seven digits");
  G.setField("adv_metabolicRate", 1.5000001);
  ok(engineNum(M, "metabolicRate") === 1.50000012 && G.said() === "Energy burned per second is now 1.5000001 (live)",
     "Energy burned per second 1.5000001: the engine runs 1.50000012 (another number than 1.5), and the note says 1.5000001, not 1.5", G.said());
  ok(/live/.test(el("modeline").dataset.why || ""), "  the run's history has it: it no longer replays from its seed (data-why " + JSON.stringify(el("modeline").dataset.why) + ")");
  G.P.key("r"); G.settle();
  ok(G.asked() && el("startaskmsg").textContent === "This replaces your run. Your live tweak (Energy burned per second 1.5000001) carries over to the new world, as the sheet shows it.",
     "  R on that fresh run asks (a live tweak), and names it as it runs", el("startaskmsg").textContent);
  G.P.key("Escape");
  G.setField("adv_metabolicRate", 1.5);
  G.P.key("r"); G.settle();
  /* (round 5: this asserted "no live tweak, R starts at once"; any accepted edit is a tweak now, whatever its value) */
  ok(G.asked() && /Your live tweak \(Energy burned per second 1\.5\)/.test(el("startaskmsg").textContent),
     "set back to 1.5 (the value it started with): still a live tweak (an accepted edit), R asks, naming 1.5", el("startaskmsg").textContent);
}

/* the page's record of what runs, after every live value, against the engine's own (the rule the page keeps it by:
 * renderer.js engineVal / applyRule, with no read of the world but for the speeds and the predator floor) */
async function reviewRecordRule() {
  section("6b. the page's record of each live value is the engine's, value for value (read back only where the engine's clamps can move it)");
  const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
  const floats = [0.1, 1.7, 1.5000001, 123456.789, 0.00007, 7.000000000001, 0.00006103515625, 1e-40, 3.4e38, 40, 175];
  const ints = [0, 7, 123456789, 999999999, 30];
  let n = 0;
  const bad = [];
  for (const k of LIVE_FLOATS.concat(LIVE_INTS)) {
    for (const v of (LIVE_INTS.indexOf(k) >= 0 ? ints : floats)) {
      G.setField("adv_" + k, v);
      n++;
      const rec = box.host.runConfig(), cfg = configOf(M);
      for (const kk of LIVE_FLOATS.concat(LIVE_INTS)) {
        if (kk === "maxPopulation") continue;   /* (its record is the user's cap, the governor's combined into the engine's) */
        const r = Object.prototype.hasOwnProperty.call(rec, kk) ? rec[kk] : undefined;
        if (r === undefined || !sameKept(kk, r, cfg[kk])) bad.push([k, v, kk, r, cfg[kk]]);
      }
    }
  }
  ok(n > 100 && bad.length === 0, "after each of " + n + " live values (every live key, floats from 1e-40 to 3.4e38, nine-digit whole numbers): every live key of the page's record is the engine's", bad.slice(0, 4));
}

/* P2: a value the engine cannot keep is refused before it is applied, here and in Turbo; a world whose state overflowed
 * (a checkpoint that is not JSON) is contained on every path: here, in the worker, in its recovery, at the hand-back */
async function reviewOverflow() {
  section("6c. P2: values the engine cannot keep are refused first; a world that overflowed is contained everywhere");
  const G = await startedPage({ dash: true }), { D, el, box } = G, M = box.M;
  G.setField("adv_metabolicRate", 1e39);
  ok(G.said() === "Energy burned per second is too large for the engine (it keeps 32-bit numbers, at most about 3.4e38) (the running world keeps 1.5)." &&
     el("adv_metabolicRate").value === "1.5" && configOf(M).metabolicRate === 1.5 && D.errors.length === 0,
     "here: Energy burned per second 1e39 (finite, past float32) refused before it reaches the engine, the field back to 1.5, the world's checkpoint still JSON", [G.said(), D.errors.slice(0, 1)]);
  G.setField("adv_targetFood", 1e12);
  ok(G.said() === "Food target is too large for the engine (it keeps whole numbers of up to nine digits) (the running world keeps 600)." && configOf(M).targetFood === 600,
     "  Food target 1e12 (the engine would cap it at 2147483647 without a word): refused the same way", G.said());
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo running");
  const w = workers[workers.length - 1], sets0 = w.sets || 0;
  G.setField("adv_metabolicRate", 1e39);
  ok((w.sets || 0) === sets0 && /too large for the engine/.test(G.said()) && el("adv_metabolicRate").value === "1.5", "in Turbo: refused by the page, nothing sent to the worker");
  el("turboexit").click();
  await until(() => G.state() === "live", "the hand-back");
  ok(configOf(M).metabolicRate === 1.5 && D.errors.length === 0, "  after the hand-back the engine runs 1.5");

  /* a world whose state overflowed: a food energy near float32's top, a few meals later "inf" in the checkpoint */
  G.setField("adv_foodEnergy", 3e38);
  const playing = () => el("pausebtn").getAttribute("aria-label") !== "play";
  if (!playing()) el("pausebtn").click();
  let steps = 0, json = true;
  for (; steps < 600 && json; steps++) { G.P.frame(); try { JSON.parse(M.UTF8ToString(M._evo_checkpoint())); } catch (e) { json = false; } }
  if (playing()) el("pausebtn").click();
  G.settle();
  ok(!json, "Energy per food 3e38 (finite, accepted), " + steps + " frames: a fish's energy overflowed, the world's checkpoint is not JSON any more");
  G.setField("adv_targetFood", 700);
  ok(G.said() === "Food target is now 700 (live)" && engineNum(M, "targetFood") === 700 && box.host.runConfig().targetFood === 700 && D.errors.length === 0,
     "here, a plain value (Food target 700): applied and said, nothing read, nothing thrown");
  /* (the speeds as the page records them and as the engine runs them: the same pair) */
  const speeds = () => { const r = box.host.runConfig(); return [Math.fround(r.minSpeed), Math.fround(r.maxSpeed), Math.fround(engineNum(M, "minSpeed")), Math.fround(engineNum(M, "maxSpeed"))]; };
  const agree = () => { const v = speeds(); return v[0] === v[2] && v[1] === v[3]; };
  G.setField("adv_minSpeed", 200);   /* (above Fastest, 150: the engine swaps them, so the page reads its config, which fails) */
  ok(/^The engine took Slowest speed, but its state can't be read back \(.*a number in the world overflowed\): the page goes by what it gave it\.$/.test(G.said()) &&
     agree() && speeds()[0] === 150 && speeds()[1] === 200 && D.errors.length === 0,
     "here, a value the engine's clamps move (Slowest speed 200, above 150): the read fails, contained and said; the record mirrors the swap (150 / 200), as the engine runs", [G.said(), speeds(), D.errors.slice(0, 1)]);
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo running on the overflowed world");
  G.setField("adv_maxSpeed", 140);   /* (below Slowest, 150: swapped; the worker reads back, which fails there) */
  await until(() => Math.fround(box.host.runConfig().minSpeed) === Math.fround(140), "the worker's answer (Fastest speed 140)");
  ok(D.errors.length === 0 && speeds()[0] === Math.fround(140) && speeds()[1] === 150,
     "in Turbo, Fastest speed 140 (below 150): the worker's read fails there, contained (no throw); the record mirrors the swap (140 / 150)", speeds());
  G.setField("adv_minSpeed", 175);   /* (above Fastest: swapped, read back; the worker dies before it answers) */
  workers[workers.length - 1].onerror({ message: "injected: the worker died" });
  await new Promise((r) => setTimeout(r, 20));
  ok(G.state() === "live" && agree() && speeds()[0] === 150 && speeds()[1] === 175 && D.errors.length === 0,
     "the worker dead before its answer: the recovered world takes Slowest speed 175 (its read fails: contained), the record and the engine agree (150 / 175)", [speeds(), D.errors.slice(0, 1)]);
  el("turbobtn").click();
  await until(() => G.state() === "turbo", "Turbo once more");
  el("turboexit").click();
  await until(() => G.state() === "live", "a hand-back of the overflowed world");
  ok(D.errors.length === 0 && agree() && /^Turbo ran [\d,]+ steps\.$|can't be read back/.test(G.said()),
     "  its hand-back: the world loads, its unreadable config contained (the record stays the page's, and agrees), nothing thrown", G.said());
}

/* ================================================ 7. the third review of PR #104 (Hydrogen, fe5f9e6) ================================================ */
/* errors that escaped to node (a rejection no one handled, an exception thrown in a worker's message or a timer): recorded,
 * so a case that lets one escape fails instead of ending the run */
const escaped = [];
process.on("unhandledRejection", (e) => escaped.push("unhandled rejection: " + String(e && e.message || e)));
process.on("uncaughtException", (e) => escaped.push("uncaught: " + String(e && e.message || e)));
const trapErr = (what) => new WebAssembly.RuntimeError("injected trap in " + what);

/* P2-1: a trap from any way into the module, not only the frame's, stops the engine (the screen, the fence) */
async function reviewTrapsOutsideFrame() {
  section("7a. P2-1: an engine trap outside the frame stops the engine, from every way in");
  const cases = [
    ["Restart (evo_init)", "_evo_init", async (G) => { G.el("restart").click(); }],
    ["R (evo_init)", "_evo_init", async (G) => { G.P.key("r"); }],
    ["Save world (evo_checkpoint)", "_evo_checkpoint", async (G) => { G.el("savecp").click(); }],
    ["Load world (evo_load_checkpoint, after the read)", "_evo_load_checkpoint", async (G) => { await G.load("w.json", G.cp); }],
    ["a live value (evo_set_param)", "_evo_set_param", async (G) => { G.setField("adv_targetFood", 700); }],
    ["Turbo's start (evo_checkpoint)", "_evo_checkpoint", async (G) => { G.el("turbobtn").click(); }],
    ["the colour switch (evo_set_colour_mode)", "_evo_set_colour_mode", async (G) => { const e = G.el("colourBrain"); e.checked = !e.checked; G.fire(e, "change"); }],
    ["a tap on the world (evo_creature_count)", "_evo_creature_count", async (G) => {
      const cv = G.el("canvas"); cv._rect = { left: 0, top: 0, right: 100, bottom: 100 };
      cv.dispatchEvent(new G.D.Ev("click", { bubbles: true, clientX: 10, clientY: 10 })); }],
    ["the tour's fish (evo_creature_count)", "_evo_creature_count", async (G) => { G.P.ctx.EvoApp.inspectSomeFish(); }],
    ["the dashboards' module (evo_similarity)", "_evo_similarity", async (G) => { G.dashAnswer = G.box.host.module._evo_similarity(50); }],
    ["Turbo's hand-back (evo_load_checkpoint, in the worker's message)", null, async (G) => {
      G.el("turbobtn").click();
      await until(() => G.state() === "turbo", "Turbo running");
      G.box.M._evo_load_checkpoint = () => { throw trapErr("the hand-back"); };
      G.el("turboexit").click();
      await until(() => G.el("splash").classList.contains("failed") || escaped.length > 0, "the hand-back", 30000).catch(() => {});
    }]
  ];
  for (const [what, fn, act] of cases) {
    const e0 = escaped.length;
    const G = await startedPage({ dash: true }), { D, el, box } = G, M = box.M;
    G.cp = M.UTF8ToString(M._evo_checkpoint());
    if (fn) M[fn] = () => { throw trapErr(what); };
    let threw = null;
    try { await act(G); } catch (e) { threw = e; }
    await new Promise((r) => setTimeout(r, 20));
    const sp = el("splash"), st = el("splashstate").textContent;
    G.watchModule();
    for (let i = 0; i < 3; i++) G.P.frame();
    ok(!threw && D.errors.length === 0 && escaped.length === e0 && sp.classList.contains("failed") && /^The engine stopped \(injected trap in /.test(st) &&
       G.calls === 0 && G.state() === "live",
       what + ": the engine stopped (its screen), nothing escaped, and no call reaches the module after (" + G.calls + ")",
       [threw && String(threw), D.errors.slice(0, 1), escaped.slice(e0, e0 + 1), sp.classList.contains("failed"), st.slice(0, 60), G.calls, G.state()]);
    if (what.indexOf("dashboards") >= 0) ok(G.dashAnswer === 0, "  the dashboards' read answers 0 (an empty answer), not the trap");
  }
}

/* P2-2: Reset every setting withdraws an open question, as an edit does */
async function reviewResetWithdraws() {
  section("7b. P2-2: Reset every setting withdraws the question (never a start other than the one asked about)");
  const G = await startedPage(), { el, box } = G, M = box.M;
  G.setField("predators", 3);
  el("restart").click(); G.settle();
  ok(G.asked() && /It starts with what waits: Predators 3\./.test(el("startaskmsg").textContent), "an edit waiting (Predators 3), Restart: asked");
  el("advreset").click(); G.settle();
  ok(!G.asked() && el("predators").value === "0" && G.said() === "Every setting is back to its default. Start again to review it.",
     "Reset every setting: the question about Predators 3 goes, and says so; the form is the defaults", [G.asked(), el("predators").value, G.said()]);
  let inits = 0;
  const init0 = M._evo_init;
  M._evo_init = function () { inits++; return init0.apply(this, arguments); };
  el("restart").click(); G.settle();
  ok(!G.asked() && inits === 1 && M._evo_predator_count() === 0, "  Restart now: nothing waits (the defaults run), it starts at once, no predators");
}

/* the review's P3s that this round fixes */
async function reviewP3() {
  section("7c. P3s: keys behind the failure screen; a refused Restart keeps what waits; Fit and the five-minute edge; stale file reads; each fallback logged");
  {   /* P3-1 */
    const G = await startedPage(), { D, el, box } = G, M = box.M;
    el("pausebtn").click();
    M._evo_step = () => { throw trapErr("a step"); };
    G.P.frame();
    const f0 = D.doc.activeElement;
    G.P.key("Escape"); G.P.key("f");
    ok(el("splash").classList.contains("failed") && f0 === el("splashreload") && D.doc.activeElement === el("splashreload"),
       "P3-1: behind the engine-stopped screen, Esc and F do nothing: the focus stays on Reload", [f0 && f0.id, D.doc.activeElement && D.doc.activeElement.id]);
  }
  {   /* P3-4 */
    const G = await startedPage(), { el, box } = G, M = box.M;
    G.setField("population", -1);
    el("restart").click(); G.settle();
    if (G.asked()) el("startconfirm").click();
    G.settle();
    ok(/^evo_init failed/.test(G.said()) && el("restart").querySelector("span").textContent === "Restart to apply" && el("population").value === "-1",
       "P3-4: a Restart the engine refuses (-1 fish) leaves its edit waiting: still Restart to apply", [G.said(), el("restart").querySelector("span").textContent]);
    G.setField("population", 300);
    M._evo_step(18749); M._evo_sync(); G.settle();
    G.P.key("r"); G.settle();
    ok(!G.asked() && tickOf(M) === 0, "  18749 steps (299.98 simulated seconds): R starts at once, under the five minutes");
    M._evo_step(18750); M._evo_sync(); G.settle();
    el("fitbtn").click(); G.settle();
    ok(G.asked() && /^This replaces your run, and 5 min 0 s of evolution with it\.$/.test(el("startaskmsg").textContent), "  Fit the world to this screen, five minutes on: asks", el("startaskmsg").textContent);
    el("startcancel").click();
  }
  {   /* P3-3 */
    const G = await startedPage(), { el, box } = G, M = box.M;
    const cp = M.UTF8ToString(M._evo_checkpoint());
    let loads = 0;
    const load0 = M._evo_load_checkpoint;
    M._evo_load_checkpoint = function () { loads++; return load0.apply(this, arguments); };
    let releaseA = null;
    el("cpfile").files = [{ name: "a.json", text: () => new Promise((r) => { releaseA = r; }) }];
    G.fire(el("cpfile"), "change");
    await G.load("b.json", cp);
    const afterB = loads;
    releaseA(cp);
    await new Promise((r) => setTimeout(r, 20));
    ok(afterB === 1 && loads === 1, "P3-3: a.json picked (its read slow), then b.json: b opens; a's read, arriving after, is dropped", [afterB, loads]);
    let releaseC = null;
    el("cpfile").files = [{ name: "c.json", text: () => new Promise((r) => { releaseC = r; }) }];
    G.fire(el("cpfile"), "change");
    G.P.key("r"); G.settle();   /* (a new world while c.json is read) */
    const t = tickOf(M);
    releaseC(cp);
    await new Promise((r) => setTimeout(r, 20));
    ok(loads === 1 && tickOf(M) === t && G.said() === "A new world started while c.json was read, so it was not opened: pick it again.",
       "  c.json picked, a new world started (R) before its read arrived: not opened over it, and said", [loads, G.said()]);
  }
  {   /* P3-2 */
    let boom = false;
    const scene = { load: () => Promise.resolve(), create: () => new Proxy({}, { get: (t, k) => {
      if (k === "then" || typeof k === "symbol") return undefined;
      if (k === "render") return () => { if (boom) throw new TypeError("tank boom"); };
      if (k === "following") return () => false;
      if (k === "quality") return () => 3;
      if (k === "project") return () => null;
      if (k === "setQuality" || k === "degrade") return () => false;
      return () => {};
    } }) };
    const gl = { create: () => ({ fishShapes: true, resize() {}, forgetFish() {}, draw: () => { if (boom) throw new TypeError("webgl boom"); return null; } }) };
    const G = await startedPage({ view: "3d", scene, gl });
    await until(() => G.D.doc.body.classList.contains("view-3d"), "the tank view");
    const fs = G.el("fishShape");
    ok(!fs.disabled, "P3-2: a page with the tank and WebGL (fish shapes on offer)");
    boom = true;
    G.el("pausebtn").click();
    for (let i = 0; i < 4; i++) G.P.frame();
    const logs = G.P.logs.filter((l) => l[0] === "error" && /a frame failed/.test(l[1]));
    ok(logs.length === 2 && /tank boom/.test(logs[0][1]) && /webgl boom/.test(logs[1][1]) && !G.D.doc.body.classList.contains("view-3d"),
       "  the tank fails, then WebGL: both logged (once each), the flat view in canvas 2D runs", logs.map((l) => l[1].slice(0, 50)));
    ok(fs.disabled && !fs.checked && /canvas 2D/.test(G.el("modeline").textContent) && /canvas 2D now/.test(G.el("f_fishShape").querySelector(".needs").textContent),
       "  the fish-shapes switch follows: off, disabled, with why; the modeline says canvas 2D", [fs.disabled, fs.checked, G.el("modeline").textContent.slice(-60)]);
  }
}

/* ================================================ 8. the fourth review of PR #104 (Codex, 56418d1) ================================================ */
/* decisions on what was submitted: a %.9g tie the page's own rounding breaks the other way is still a change */
async function reviewTie() {
  section("8a. a decimal tie (100000004.5): the engine keeps 100000000, a mirror said 100000008; the change is a change");
  const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
  ok((100000004.5).toPrecision(9) === "100000005" && Math.fround(100000005) === 100000008,
     "the tie: JavaScript's toPrecision(9) rounds 100000004.5 up (100000005, float32 100000008), C's %.9g to even (100000004, float32 100000000)");
  G.setField("adv_maxAge", 100000008);
  el("restart").click(); G.settle();
  if (G.asked()) el("startconfirm").click();
  G.settle();
  ok(!G.asked() && configOf(M).maxAge === 100000008 && !/live/.test(el("modeline").dataset.why || ""), "a fresh world started with Lifespan 100000008 (no history yet)");
  G.setField("adv_maxAge", 100000004.5);
  ok(configOf(M).maxAge === 100000000 && /live/.test(el("modeline").dataset.why || ""),
     "Lifespan 100000004.5: the engine keeps 100000000, and the run's history has the change (it no longer replays)", [configOf(M).maxAge, el("modeline").dataset.why]);
  G.P.key("r"); G.settle();
  ok(G.asked() && /Your live tweak \(Lifespan \(s\) 100000000\) carries over to the new world, as the sheet shows it\./.test(el("startaskmsg").textContent),
     "  R asks (a live tweak), naming the value the engine runs", el("startaskmsg").textContent);
  G.P.key("Escape");
  G.setField("adv_maxAge", 100000008);
  G.P.key("r"); G.settle();
  /* (round 5: this asserted "no live tweak, R starts at once"; any accepted edit is a tweak now, whatever its value) */
  ok(G.asked() && /Your live tweak \(Lifespan \(s\) 100000008\)/.test(el("startaskmsg").textContent),
     "  set back to the very value it started with (100000008): still a live tweak, R asks, naming 100000008", el("startaskmsg").textContent);
}

/* the record is the engine's: read once at the first edit after a load (the setter clamps the whole config), so a revert says what runs */
async function reviewCanonical() {
  section("8b. a loaded floor of 2001, an unrelated edit (the setter clamps it to 2000), then a refused floor: the field and the words say 2000");
  const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
  const cp = JSON.parse(M.UTF8ToString(M._evo_checkpoint()));
  cp.config.predatorMinPopulation = 2001;
  await G.load("floor2001.json", JSON.stringify(cp));
  ok(/Checkpoint loaded/.test(G.said()) && configOf(M).predatorMinPopulation === 2001, "the file loads: the engine runs a predator floor of 2001 (a load clamps nothing)");
  let reads = 0;
  const cp0 = M._evo_checkpoint;
  M._evo_checkpoint = function () { reads++; return cp0.apply(this, arguments); };
  G.setField("adv_foodEnergy", 6);
  const r1 = reads;
  ok(configOf(M).predatorMinPopulation === 2000 && box.host.runConfig().predatorMinPopulation === 2000 && r1 === 1,
     "Energy per food 6 (unrelated): the setter clamps the floor to 2000; this first edit after the load reads the engine once, and the record says 2000", [r1, box.host.runConfig().predatorMinPopulation]);
  reads = 0;
  G.setField("adv_predatorMinPopulation", -1);
  ok(el("adv_predatorMinPopulation").value === "2000" && G.said() === "predatorMinPopulation must be finite and >= 0 (the running world keeps 2000).",
     "  a floor of -1 refused: the field back to 2000 and the error says 2000, the floor that runs (not the file's 2001)", [el("adv_predatorMinPopulation").value, G.said()]);
  /* (round 5: a refusal reads the engine once, for the value it puts back; this counted it among "nothing") */
  ok(reads === 1, "  the refusal read the engine once (the value it puts back is the engine's own)", reads);
  reads = 0;
  G.setField("adv_targetFood", 700);
  G.setField("adv_targetFood", 701);
  const rr = reads;
  ok(rr === 0 && configOf(M).targetFood === 701, "  later ordinary edits read nothing (Food target 700, then 701): " + rr + " reads", rr);
}

/* a trap in the engine's checkpoint during a read the clamps asked for: the engine stops, the operation ends, nothing escapes */
async function reviewReadbackTrap() {
  section("8c. a trap in evo_checkpoint itself, during a read the engine's clamps asked for: here and in the worker");
  {
    const e0 = escaped.length;
    const G = await startedPage(), { D, el, box } = G, M = box.M;
    G.setField("adv_targetFood", 700);   /* (the first edit after the start: its read is done) */
    M._evo_checkpoint = () => { throw trapErr("evo_checkpoint"); };
    G.setField("adv_minSpeed", 200);   /* (above Fastest: the engine swaps them, the page reads its config) */
    ok(el("splash").classList.contains("failed") && /^The engine stopped \(injected trap in evo_checkpoint\)/.test(G.said()) && !/is now/.test(G.said()) &&
       D.errors.length === 0 && escaped.length === e0,
       "here: the read traps; the engine stops (its screen), the edit's operation ends there (no note it applied), nothing escapes", [G.said(), D.errors.slice(0, 1), escaped.slice(e0)]);
  }
  {
    const e0 = escaped.length;
    const G = await startedPage({ dash: true }), { D, el, box } = G, M = box.M;
    el("turbobtn").click();
    await until(() => G.state() === "turbo", "Turbo running");
    G.setField("adv_targetFood", 700);
    await until(() => G.said() === "Food target is now 700 (live)", "the worker's first answer (its read)");
    const w = workers[workers.length - 1];
    w.w.ctx.Module._evo_checkpoint = () => { throw trapErr("the worker's evo_checkpoint"); };
    G.setField("adv_minSpeed", 200);
    await until(() => G.state() === "live", "the worker's failure");
    await new Promise((r) => setTimeout(r, 20));
    const c = configOf(M), r = box.host.runConfig();
    ok(/The Turbo worker failed: .*injected trap in the worker's evo_checkpoint/.test(D.doc.getElementById("toasts").textContent + " " + G.said()) || w.dead,
       "in the worker: its read traps, the worker dies (it reported nothing as applied), and the page takes the world back", [G.said()]);
    ok(!el("splash").classList.contains("failed") && c.minSpeed === 150 && c.maxSpeed === 200 && Math.fround(r.minSpeed) === 150 && Math.fround(r.maxSpeed) === 200 &&
       c.targetFood === 700 && D.errors.length === 0 && escaped.length === e0,
       "  the page's own engine runs on: it takes Food target 700 (answered) and Slowest speed 200 (unanswered: swapped, 150 / 200), the record agrees, nothing escapes",
       [c.minSpeed, c.maxSpeed, r.minSpeed, r.maxSpeed, c.targetFood, D.errors.slice(0, 1), escaped.slice(e0)]);
  }
}

/* ================================================ 9. the fifth reviews of PR #104 (Codex and Hydrogen, 6fdf8d0) ================================================ */
const quick = async (pred, ms) => { try { await until(pred, "", ms || 5000); return true; } catch (e) { return false; } };

/* P1 (both): any accepted live edit since the world started is a live tweak, whatever its value; a start or a load clears it */
async function reviewTweakFlag() {
  section("9a. P1: any accepted live edit is a live tweak, whatever its value (the speeds' swap, a value set back, the value that runs)");
  {
    const G = await startedPage(), { el, box } = G, M = box.M;
    const c0 = configOf(M);
    ok(c0.minSpeed === 30 && c0.maxSpeed === 150, "a fresh default run: speeds 30 / 150", [c0.minSpeed, c0.maxSpeed]);
    G.setField("adv_minSpeed", 200);
    G.setField("adv_minSpeed", 30);
    const c1 = configOf(M);
    ok(c1.minSpeed === 30 && c1.maxSpeed === 200 && el("adv_maxSpeed").value === "200",
       "Slowest speed 200 (the engine swaps them: 150 / 200), then back to 30: the engine runs 30 / 200, Fastest speed's field says 200", [c1.minSpeed, c1.maxSpeed, el("adv_maxSpeed").value]);
    G.P.key("r"); G.settle();
    ok(G.asked() && el("startaskmsg").textContent === "This replaces your run. Your live tweaks (Slowest speed 30, Fastest speed 200) carry over to the new world, as the sheet shows them.",
       "  R asks (the reviews' case), naming both speeds as the engine runs them", el("startaskmsg").textContent);
    ok(/live/.test(el("modeline").dataset.why || ""), "  the run's history has it: it does not replay");
    el("startconfirm").click(); G.settle();
    G.P.key("r"); G.settle();
    ok(!G.asked() && tickOf(M) === 0 && !/live/.test(el("modeline").dataset.why || ""), "  Replace it, then R: a new run has no live tweak, so R starts at once, and it replays");
    G.setField("adv_targetFood", 600);
    ok(configOf(M).targetFood === 600 && G.said() === "Food target is now 600 (live)", "Food target 600 typed, the value that runs: accepted");
    G.P.key("r"); G.settle();
    ok(G.asked() && el("startaskmsg").textContent === "This replaces your run. Your live tweak (Food target 600) carries over to the new world, as the sheet shows it.",
       "  R asks: an accepted edit is a live tweak whatever its value (it may ask when nothing changed)", el("startaskmsg").textContent);
    G.P.key("Escape");
    await G.load("w.json", M.UTF8ToString(M._evo_checkpoint()));
    if (G.asked()) el("startconfirm").click();
    G.settle();
    G.P.key("r"); G.settle();
    ok(!G.asked(), "  a load clears it: the loaded world has no live tweak, R starts at once");
  }
  {
    const G = await startedPage(), { el } = G;
    const input = el("adv_maxPopulation"), less = input.parentNode.children[0];
    ok(input.value === "0" && less.getAttribute("aria-label") === "less", "a fresh run with no cap (0), and the cap's minus");
    less.dispatchEvent(new G.D.Ev("click", { bubbles: true }));
    G.P.key("r"); G.settle();
    ok(!G.asked() && input.value === "0", "the cap's minus at its bound (0 stays 0): the field unchanged, no edit, so R starts at once");
    G.setField("adv_maxPopulation", 0);
    G.P.key("r"); G.settle();
    ok(G.asked() && /Your live tweak \(Population cap 0\)/.test(el("startaskmsg").textContent), "  0 typed into it: an accepted edit, a live tweak: R asks", el("startaskmsg").textContent);
  }
  {
    const G = await startedPage(), { el, box } = G, M = box.M;
    el("turbobtn").click();
    await until(() => G.state() === "turbo", "Turbo running");
    G.setField("adv_minSpeed", 200);
    const a1 = await quick(() => G.said() === "Slowest speed is now 150 (live)");
    G.setField("adv_minSpeed", 30);
    const a2 = await quick(() => G.said() === "Slowest speed is now 30 (live)");
    el("turboexit").click();
    await until(() => G.state() === "live", "the hand-back");
    const c = configOf(M);
    G.P.key("r"); G.settle();
    ok(a1 && a2 && c.minSpeed === 30 && c.maxSpeed === 200 && G.asked() &&
       / Your live tweaks \(Slowest speed 30, Fastest speed 200\) carry over to the new world, as the sheet shows them\.$/.test(el("startaskmsg").textContent),
       "in Turbo, the same two edits: the world runs 30 / 200 after the hand-back, and R names both tweaks", [a1, a2, c.minSpeed, c.maxSpeed, el("startaskmsg").textContent]);
  }
}

/* P2 (Codex): what a refusal puts back is read from the engine: exact where the page's rule is not (a decimal tie), and
 * whatever the page's record says */
async function reviewAuthoritativeRevert() {
  section("9b. P2: a refused value's field goes back to what the engine runs, read from it (the decimal tie after an earlier edit; a record made wrong)");
  const tieWorld = async (G) => {
    G.setField("adv_maxAge", 100000008);
    G.el("restart").click(); G.settle();
    if (G.asked()) G.el("startconfirm").click();
    G.settle();
  };
  {
    const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
    await tieWorld(G);
    G.setField("adv_foodEnergy", 5);   /* (an ordinary edit first: the record's read after the start is done) */
    G.setField("adv_maxAge", 100000004.5);
    ok(configOf(M).maxAge === 100000000 && el("adv_maxAge").value === "100000000" && G.said() === "Lifespan (s) is now 100000000 (live)" &&
       box.host.runConfig().maxAge === 100000000,
       "Lifespan 100000004.5 after an earlier edit (the Codex case): the engine keeps 100000000; the field, the note and the record say so",
       [configOf(M).maxAge, el("adv_maxAge").value, G.said(), box.host.runConfig().maxAge]);
    G.setField("adv_maxAge", -1);
    ok(el("adv_maxAge").value === "100000000" && G.said() === "maxAge must be finite and >= 0 (the running world keeps 100000000).",
       "  Lifespan -1 refused: the field back to 100000000, the value that runs, and said so", [el("adv_maxAge").value, G.said()]);
    box.host.runConfig().targetFood = 123;   /* (the record made wrong on purpose: a refusal must not go by it) */
    G.setField("adv_targetFood", -5);
    ok(el("adv_targetFood").value === "600" && G.said() === "targetFood must be finite and >= 0 (the running world keeps 600).",
       "a record made wrong (Food target 123) and an engine's refusal: the field and the words say the 600 the engine runs", [el("adv_targetFood").value, G.said()]);
    box.host.runConfig().metabolicRate = 9;
    G.setField("adv_metabolicRate", 1e39);
    ok(el("adv_metabolicRate").value === "1.5" && /\(the running world keeps 1\.5\)\.$/.test(G.said()),
       "  and a page's refusal (1e39): the 1.5 the engine runs, not the record's 9", [el("adv_metabolicRate").value, G.said()]);
  }
  {
    const G = await startedPage({ dash: true }), { el, box } = G, M = box.M;
    await tieWorld(G);
    el("turbobtn").click();
    await until(() => G.state() === "turbo", "Turbo running");
    G.setField("adv_foodEnergy", 5);
    await until(() => G.said() === "Energy per food is now 5 (live)", "the worker's first answer");
    G.setField("adv_maxAge", 100000004.5);
    const tie = await quick(() => /^Lifespan \(s\) is now/.test(G.said()));
    ok(tie && G.said() === "Lifespan (s) is now 100000000 (live)" && el("adv_maxAge").value === "100000000",
       "in Turbo, the tie after an earlier edit: the note and the field say 100000000, as the worker's engine runs", [G.said(), el("adv_maxAge").value]);
    G.setField("adv_maxAge", -1);
    const ref = await quick(() => /^maxAge must be/.test(G.said()));
    ok(ref && el("adv_maxAge").value === "100000000" && G.said() === "maxAge must be finite and >= 0 (the running world keeps 100000000).",
       "  Lifespan -1, refused by the worker's engine: the field back to 100000000 (its config came with the refusal)", [G.said(), el("adv_maxAge").value]);
    box.host.runConfig().metabolicRate = 9;   /* (the record made wrong: the page's own refusal asks the worker what runs) */
    G.setField("adv_metabolicRate", 1e39);
    const first = el("adv_metabolicRate").value;
    const fixed = await quick(() => el("adv_metabolicRate").value === "1.5");
    ok(fixed && /\(the running world keeps 1\.5\)\.$/.test(G.said()),
       "  a page's refusal in Turbo (1e39) with the record made wrong: the field (" + first + " at once) put right to the 1.5 the worker's engine runs, and said", [first, el("adv_metabolicRate").value, G.said()]);
    el("turboexit").click();
    await until(() => G.state() === "live", "the hand-back");
    ok(configOf(M).maxAge === 100000000 && configOf(M).metabolicRate === 1.5, "  after the hand-back the engine runs 100000000 and 1.5");
  }
}

/* P2 (Codex): a trap inside a fence inside another (the real dashboards' reset calls host.setRecEvery, itself fenced)
 * goes on to the outermost, which ends its operation: nothing reaches the module after it */
async function reviewNestedFence() {
  section("9c. P2: a trap inside a nested fence (the real dashboards' reset: host.setRecEvery) ends the whole operation");
  for (const [what, act] of [["Restart", async (G) => { G.el("restart").click(); }],
                             ["R", async (G) => { G.P.key("r"); }],
                             ["Load world", async (G) => { await G.load("w.json", G.cp); }]]) {
    const e0 = escaped.length;
    const G = await startedPage({ realDash: true }), { D, el, box } = G, M = box.M;
    G.cp = M.UTF8ToString(M._evo_checkpoint());
    G.watchModule();
    G.trapped = false;
    M._evo_rec_config = function () { G.calls = 0; G.trapped = true; throw trapErr("evo_rec_config"); };
    let threw = null;
    try { await act(G); } catch (e) { threw = e; }
    const after = G.calls;
    for (let i = 0; i < 3; i++) G.P.frame();
    ok(G.P.ctx.EvoDash && G.P.ctx.EvoDash._data && G.trapped && !threw && after === 0 && G.calls === 0 && el("splash").classList.contains("failed") &&
       D.errors.length === 0 && escaped.length === e0,
       what + " with the real dashboards: their reset's evo_rec_config traps; the engine stops, the operation ends there (" + after + " calls after the trap), nothing escapes",
       [G.trapped, threw && String(threw), after, G.calls, el("splash").classList.contains("failed"), D.errors.slice(0, 1), escaped.slice(e0)]);
  }
}

/* P2 (Codex): a trap in the worker stops its pump before anything else reaches its module */
async function reviewWorkerFatal() {
  section("9d. P2: a trap in the worker (the read for a live value) stops its pump at once: no chunk after it, nothing answered");
  const got = [];
  const W = makeWorker((m) => got.push(m));
  const A = await mkClassic();
  A._evo_init(42, 1920, 1080, 300, 0);
  W.send({ cmd: "start", checkpoint: A.UTF8ToString(A._evo_checkpoint()), js: "evo_boids.js", wasm: "evo_boids.wasm", threads: 1, recEvery: 60 });
  await until(() => got.some((m) => m.type === "stats" && m.totalSteps > 0), "the worker stepping");
  const WM = W.ctx.Module;
  let trapped = false, after = 0;
  for (const k of Object.keys(WM)) if (/^_evo_/.test(k) && typeof WM[k] === "function") {
    const f = WM[k];
    WM[k] = function () { if (trapped) after++; return f.apply(this, arguments); };
  }
  WM._evo_checkpoint = () => { trapped = true; throw trapErr("the worker's evo_checkpoint"); };
  let threw = null;
  try { W.send({ cmd: "set", key: "minSpeed", value: 200, readback: true }); } catch (e) { threw = e; }
  const errs = got.filter((m) => m.type === "error"), n = got.length;
  await new Promise((r) => setTimeout(r, 60));
  try { W.send({ cmd: "set", key: "targetFood", value: 700 }); W.send({ cmd: "config" }); W.send({ cmd: "stop" }); } catch (e) { threw = threw || e; }
  await new Promise((r) => setTimeout(r, 60));
  ok(trapped && !threw && errs.length === 1 && /its engine stopped \(injected trap in the worker's evo_checkpoint\)/.test(errs[0].message) &&
     after === 0 && got.length === n,
     "the read traps: the worker says so at once (its error), no chunk steps after it and no call reaches its module (" + after + "), the next set, config and stop get no answer",
     [trapped, threw && String(threw), errs[0], after, got.length - n]);
}

/* P2 (Hydrogen): no silent clamp of a live value: a cap below 0 (the page's own clamp), a predator floor past 2000 (the engine's) */
async function reviewNoSilentClamps() {
  section("9e. P2: a cap below 0 and a predator floor past 2000 are refused, not clamped (here, in Turbo, in the worker)");
  {
    const G = await startedPage(), { el, box } = G, M = box.M;
    const pf = configOf(M).predatorMinPopulation;
    G.setField("adv_maxPopulation", 500);
    G.setField("adv_maxPopulation", -5);
    ok(configOf(M).maxPopulation === 500 && el("adv_maxPopulation").value === "500" && G.said() === "Population cap must be 0 or more (0: no cap) (the running world keeps 500).",
       "a cap of 500, then -5: refused (on 6fdf8d0 it ran as 0, no cap, without a word), the field back to 500, said so", [configOf(M).maxPopulation, el("adv_maxPopulation").value, G.said()]);
    G.setField("adv_predatorMinPopulation", 2001);
    ok(configOf(M).predatorMinPopulation === pf && el("adv_predatorMinPopulation").value === String(pf) &&
       G.said() === "Predator floor is at most 2000 (the engine caps the predator floor there) (the running world keeps " + pf + ").",
       "a predator floor of 2001: refused (the engine would cap it at 2000 without a word), the field back to " + pf, [configOf(M).predatorMinPopulation, G.said()]);
    G.setField("adv_predatorMinPopulation", 2000);
    ok(configOf(M).predatorMinPopulation === 2000 && G.said() === "Predator floor is now 2000 (live)", "  2000 itself: applied");
    el("turbobtn").click();
    await until(() => G.state() === "turbo", "Turbo running");
    const w = workers[workers.length - 1], sets0 = w.sets || 0;
    G.setField("adv_maxPopulation", -5);
    const s1 = G.said();
    G.setField("adv_predatorMinPopulation", 2500);
    ok((w.sets || 0) === sets0 && /^Population cap must be 0 or more/.test(s1) && /^Predator floor is at most 2000/.test(G.said()) &&
       el("adv_maxPopulation").value === "500" && el("adv_predatorMinPopulation").value === "2000",
       "in Turbo: both refused by the page, nothing sent to the worker, the fields back", [s1, G.said(), (w.sets || 0) - sets0]);
    el("turboexit").click();
    await until(() => G.state() === "live", "the hand-back");
  }
  {
    const got = [];
    const W = makeWorker((m) => got.push(m));
    const A = await mkClassic();
    A._evo_init(42, 1920, 1080, 300, 0);
    W.send({ cmd: "start", checkpoint: A.UTF8ToString(A._evo_checkpoint()), js: "evo_boids.js", wasm: "evo_boids.wasm", threads: 1, recEvery: 60 });
    await until(() => got.some((m) => m.type === "stats"), "the worker's first stats");
    const n0 = got.length;
    W.send({ cmd: "set", key: "maxPopulation", value: -5 });
    W.send({ cmd: "set", key: "predatorMinPopulation", value: 2001 });
    W.send({ cmd: "config" });
    const a = got.slice(n0);
    ok(a.length === 3 && a[0].ok === false && a[0].error === "maxPopulation must be 0 or more (0: no cap)" &&
       a[1].ok === false && a[1].error === "predatorMinPopulation is at most 2000 (the engine caps the predator floor there)" &&
       a[0].config && a[0].config.maxPopulation === 0 && a[1].config && a[1].config.predatorMinPopulation === 0 &&
       a[2].type === "config" && a[2].config && a[2].config.predatorMinPopulation === 0,
       "the worker: the same two refused, each with the config that runs instead; its config command answers it", a.map((m) => [m.type, m.error, m.config && m.config.predatorMinPopulation]));
    W.send({ cmd: "stop" });
    await until(() => got.some((m) => m.type === "checkpoint"), "the hand-back");
  }
}

/* P2 (Hydrogen): a Turbo start that throws (the Worker refused, its first message refused) goes back to live, said */
async function reviewTurboStartThrows() {
  section("9f. P2: a Turbo start that throws (new Worker, its first postMessage): back to live, said, the controls free");
  {
    const G = await startedPage(), { D, el, box, P } = G, M = box.M;
    P.ctx.Worker = function () { throw new Error("worker-src blocked"); };
    el("turbobtn").click(); G.settle();
    ok(G.state() === "live" && !el("turbobtn").disabled && G.said() === "Turbo couldn't start (worker-src blocked): your run carries on here." && D.errors.length === 0,
       "new Worker throws (a page's CSP): live again, Turbo's button free, said", [G.state(), G.said(), D.errors.slice(0, 1)]);
    G.setField("adv_targetFood", 700);
    ok(configOf(M).targetFood === 700 && G.said() === "Food target is now 700 (live)", "  a live edit after it applies at once (nothing held for a Turbo that never started)");
    P.ctx.Worker = FakeWorker;
    el("turbobtn").click();
    const on = await quick(() => G.state() === "turbo");
    el("turboexit").click();
    const back = await quick(() => G.state() === "live");
    ok(on && back && configOf(M).targetFood === 700, "  with a Worker again: Turbo starts and hands back");
  }
  {
    const G = await startedPage(), { D, el, P } = G;
    class Refusing extends FakeWorker { postMessage(m) { if (m && m.cmd === "start") throw new Error("the checkpoint could not be cloned"); super.postMessage(m); } }
    P.ctx.Worker = Refusing;
    el("turbobtn").click(); G.settle();
    const w = workers[workers.length - 1];
    ok(G.state() === "live" && !el("turbobtn").disabled && G.said() === "Turbo couldn't start (the checkpoint could not be cloned): your run carries on here." &&
       w instanceof Refusing && w.dead && D.errors.length === 0,
       "its first postMessage throws: live again, the worker dropped, said", [G.state(), G.said(), w.dead, D.errors.slice(0, 1)]);
  }
}

/* P3 (Hydrogen): a world never drawn (no fallback left) shows the failure screen instead of a splash that loads forever */
async function reviewFirstDraw() {
  section("9g. P3: a world never drawn (canvas 2D fails from the first frame): the failure screen, not a splash that loads forever");
  let boom = false;
  const canvas = (c) => c.id === "inetc" ? recorder() : c.id !== "canvas" ? null : new Proxy(recorder(), {
    get: (t, k) => { const v = t[k]; return boom && typeof v === "function" ? () => { throw new TypeError("2d boom"); } : v; } });
  const G = await bootPage({ canvas });
  await until(() => G.P.ctx.EvoApp && G.P.ctx.EvoApp.ready, "Classic's page to start");
  const sp = G.el("splash");
  ok(!sp.classList.contains("done") && !sp.classList.contains("failed"), "booted, no frame drawn yet: the splash loads");
  boom = true;
  for (let i = 0; i < 3; i++) G.P.frame();
  ok(sp.classList.contains("failed") && /^The world couldn't be drawn \(2d boom\)\./.test(G.el("splashstate").textContent) &&
     G.D.doc.activeElement === G.el("splashreload") && G.P.logs.filter((l) => l[0] === "error" && /a frame failed/.test(l[1])).length === 1,
     "the first frame's drawing throws, no fallback left: the failure screen (Reload focused), logged once", [sp.className, G.el("splashstate").textContent.slice(0, 60)]);
}

/* P3 (Hydrogen): R whose start the engine refuses keeps the seed the sheet had */
async function reviewSeedKept() {
  section("9h. P3: R whose start the engine refuses keeps the sheet's seed");
  const G = await startedPage(), { el } = G;
  const seed0 = el("seed").value;
  G.setField("population", -1);
  G.P.key("r"); G.settle();
  if (G.asked()) el("startconfirm").click();
  G.settle();
  ok(/^evo_init failed/.test(G.said()) && el("seed").value === seed0, "R with -1 fish waiting: the engine refuses the start, and the seed field still says " + seed0, [G.said(), el("seed").value]);
}

(async () => {
  /* each section on its own: one section's throw never hides the next (sections 3 and 4b go on section 2's page) */
  const run = async (name, f) => { try { return await f(); } catch (e) { ok(false, name + " threw: " + (e && e.stack || e)); return null; } };
  await run("workerSet", workerSet);
  const G = await run("pageRules", pageRules);
  if (G) { await run("turboEdits", () => turboEdits(G)); await run("engineTrap", () => engineTrap(G)); }
  await run("startFailures", startFailures);
  for (const t of [reviewLoadBypass, reviewStoppedFence, reviewUnanswered, reviewHeldOrder, reviewFrameErrors, reviewRecord,
                   reviewRounding, reviewRecordRule, reviewOverflow, reviewTrapsOutsideFrame, reviewResetWithdraws, reviewP3,
                   reviewTie, reviewCanonical, reviewReadbackTrap,
                   reviewTweakFlag, reviewAuthoritativeRevert, reviewNestedFence, reviewWorkerFatal, reviewNoSilentClamps,
                   reviewTurboStartThrows, reviewFirstDraw, reviewSeedKept]) await run(t.name, t);
  ok(escaped.length === 0, "nothing escaped to node in the whole run (no unhandled rejection, no uncaught exception)", escaped.slice(0, 3));
  for (const w of workers) w.terminate();
  console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
  process.exit(fails ? 1 : 0);
})();
