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
  const ctx = { console, performance, MessageChannel: Chan, setTimeout, clearTimeout, onmessage: null };
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
  postMessage(m) { const c = structuredClone(m); setImmediate(() => { if (!this.dead) this.w.send(c); }); }
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
  const sets = got.slice(n0).filter((m) => m.type === "set");
  ok(sets.length === 4 && sets[0].ok === true && sets[0].value === 900 && sets[0].quiet === false && !sets[0].notRunning,
     "Turbo running: targetFood 900 applied between chunks, answered ok", sets[0]);
  ok(sets[0].config && sets[0].config.targetFood === 900 && sets[0].config.minPopulation === 50 && sets[1].config === null,
     "  the answer carries the world's config as its engine now holds it (the page's record); a refusal none", sets[0].config && sets[0].config.targetFood);
  ok(sets[1].ok === false && /not a live parameter/.test(sets[1].error) && !sets[1].notRunning,
     "  foodPatches (not live): the engine refuses it, with its reason", sets[1]);
  ok(sets[2].ok === false && /finite and >= 0/.test(sets[2].error), "  foodEnergy -1: the engine refuses it", sets[2]);
  ok(sets[3].ok === true && sets[3].quiet === true, "  maxPopulation 400 (quiet: the governor's cap), applied and the quiet flag echoed", sets[3]);
  W.send({ cmd: "stop" });
  await until(() => got.some((m) => m.type === "checkpoint"), "the hand-back's checkpoint");
  const cp = JSON.parse(last("checkpoint").json);
  ok(cp.config.targetFood === 900 && cp.config.maxPopulation === 400 && cp.config.foodEnergy === 5 && cp.world.frame > 0,
     "the hand-back's checkpoint carries the applied values (targetFood 900, maxPopulation 400; foodEnergy still 5) at frame " + cp.world.frame,
     [cp.config.targetFood, cp.config.maxPopulation, cp.config.foodEnergy]);
  W.send({ cmd: "set", key: "targetFood", value: 700 });
  const after = last("set");
  ok(after.ok === false && after.notRunning === true, "after the stop: notRunning again", after);
}

/* ======================================================== the page ======================================================== */
/* o: a loader to use instead of the module's (a start that fails), a canvas context factory (the world's 2D drawing),
 * the view (flat by default) and a stand-in tank scene (web/scene3d.js) */
async function bootPage(o) {
  o = typeof o === "function" ? { load: o } : (o || {});
  const D = makeDom(pageIds(read("index.html")), o.canvas || ((c) => (c.id === "canvas" || c.id === "inetc" ? recorder() : null)));
  const P = makeWindow(D, "http://classic.test/web/index.html?threads=0&view=" + (o.view || "flat") + "&guide=0&intro=0", { media: ["min-width: 960px"] });
  const box = { M: null };
  if (o.scene) P.ctx.EvoScene = o.scene;
  const load = o.load;
  P.ctx.EVO_ASSETS = { st: "evo_boids.js", stWasm: "evo_boids.wasm", mt: "evo_boids_mt.js", mtWasm: "evo_boids_mt.wasm", worker: "worker.js", background: "rocks.jpg", three: "three.js" };
  P.ctx.EvoLoader = { load: load || (() => mkClassic().then((m) => { box.M = m; return { Module: m, threaded: false, why: "the test", js: "evo_boids.js", wasm: "evo_boids.wasm" }; })),
                      poolThreads: () => 1 };
  P.ctx.Worker = FakeWorker;
  vm.createContext(P.ctx);
  for (const f of ["ui_common.js", "randomizer.js", "renderer.js"]) vm.runInContext(read(f), P.ctx, { filename: f });
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
  ok(asked() && msg() === "This replaces your run. Your live tweak (Food target 900) carries over to the new world.", "  Restart: asks (a live tweak), and says it carries over", msg());
  el("startcancel").click();
  el("randombtn").click(); settle();
  ok(asked() && (/Your live tweak \(Food target 900\) carries over to the new world\.$/.test(msg()) ||
                 /The new world's setup sets Food target \d+ instead of your live tweak \(Food target 900\)\.$/.test(msg())),
     "  the dice: what the random world does with it", msg());
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

(async () => {
  try {
    await workerSet();
    const G = await pageRules();
    await turboEdits(G);
    await engineTrap(G);
    await startFailures();
    for (const t of [reviewLoadBypass, reviewStoppedFence, reviewUnanswered, reviewHeldOrder, reviewFrameErrors, reviewRecord]) {
      try { await t(); } catch (e) { ok(false, t.name + " threw: " + (e && e.stack || e)); }   /* (one case's throw never hides the next) */
    }
  } catch (e) { ok(false, "the run threw: " + (e && e.stack || e)); }
  for (const w of workers) w.terminate();
  console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
  process.exit(fails ? 1 : 0);
})();
