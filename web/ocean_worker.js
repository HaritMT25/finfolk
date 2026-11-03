"use strict";
/* evo_boids 3-D Ocean: the TURBO worker — steps the world headless at full
 * speed, nothing drawn (web/ocean.js; Classic's is web/worker.js).
 *
 * Hand-off is the module's whole linear memory. The page and this worker run
 * the SAME single-threaded module (web/evo_ocean.{js,wasm}), and everything
 * the world is — every C++ object, the allocator's state, the rng — lives in
 * its linear memory; between calls the only other state, the stack pointer,
 * is the same in every instance. So a byte copy of the memory, from the page
 * to here and back, carries the run on exactly, step for step (no checkpoint
 * format needed; the Ocean has none). The receiving memory is grown to the
 * sender's size first and anything past the sender's end is zeroed, as fresh
 * pages are (web/ocean_handoff.js take(), shared with the page).
 *
 * Protocol:
 *   in : {cmd:'start', js, wasm, handoff, mem: ArrayBuffer, recEvery, famK}
 *        -> load the module and web/ocean_handoff.js (once), take the
 *           memory, run in chunks. A start always begins afresh.
 *   in : {cmd:'set', key, value}   -> oc_set_param (a live setting, mid-Turbo)
 *   in : {cmd:'rec', every}        -> the dashboards' sampling interval
 *   in : {cmd:'stop'}              -> finish the chunk, post the memory back
 *   in : {cmd:'resume'}            -> the page could not take the memory
 *                                     back: carry on running this world
 *   in : {cmd:'wiring'}            -> the Brains dashboard's wiring of the
 *                                     world now (oc_wiring), answered between
 *                                     chunks; the page asks only while that
 *                                     panel shows, every 2 s at most, one
 *                                     question at a time
 *   in : {cmd:'snapshot', id}      -> Save world while Turbo runs: a copy of
 *                                     the world now, between chunks; Turbo
 *                                     carries on
 *   out: {type:'snapshot', id, mem: ArrayBuffer, frame, pop, food, pred,
 *        totalSteps}, or {type:'snapshot', id, none: true} with no world here
 *   in : {cmd:'probe', id, js, wasm, handoff, data: Uint8Array, bytes, expect}
 *        -> a saved world tried in this worker's module before the page
 *           opens it (a worker made only for that: web/ocean.js probeWorld)
 *   out: {type:'probe', id, ok, at, why, trap, data} (data: the image, back)
 * The page hands every worker the module's wasm as the Blob URL of the
 * bytes it pinned at start-up (web/ocean.js pinEngine): the same build the
 * page runs and names in its world files, whatever the server has now.
 *   out: {type:'stats', frame, pop, food, pred, stepsPerSec, totalSteps, st, su}
 *        ~4x/s; st: oc_stats, su: oc_summary of the world now (the page's
 *        readout and stat panel show them while Turbo owns the world)
 *   out: {type:'wiring', n, senses, actions, path, direct, frame}, or
 *        {type:'wiring', none: true} with no world here: every question is answered
 *   out: {type:'rec', rows}        -> dashboard samples (web/ocean_dash.js row())
 *   out: {type:'set', key, value, ok, error, frame}  (frame: the world's frame
 *        it applied at; every 'set' gets one, ok false when nothing runs)
 *   out: {type:'memory', mem: ArrayBuffer, totalSteps}
 *   out: {type:'error', message, totalSteps, mem?} — the run stopped. mem:
 *        the world as far as it got, when it is whole (the throw did not come
 *        out of oc_step part-way through a step); without it, only the page's
 *        own copy (the world as Turbo took it) is left. Either way this worker
 *        is done: the page terminates it and starts a fresh one next time.
 * The step is oc_step's fixed dt: no wall-clock time reaches the world. */
var M = null, H = null, modulePromise = null;
var running = false, stopRequested = false, owns = false, stepping = false, session = 0;
var chunkSteps = 60, totalSteps = 0, samples = [], lastStats = 0;
var recEvery = 60, famK = 8, rows = [];
var pump = new MessageChannel();   /* not throttled like timers in a background tab */
pump.port1.onmessage = function (e) { if (e.data === session) guarded(runChunk); };
function scheduleChunk() { pump.port2.postMessage(session); }

function heap() { return H.buffer(M); }
function ensureModule(msg) {
  if (!modulePromise) {
    importScripts(msg.handoff, msg.js);
    H = self.EvoOceanHandoff;
    modulePromise = createEvoOcean({
      locateFile: function (p) { return p.slice(-5) === ".wasm" ? msg.wasm : p; },
      mainScriptUrlOrBlob: msg.js
    }).then(function (m) { M = m; return m; });
  }
  return modulePromise;
}
function statsLen() { return M._oc_stats_len(); }

/* Something threw: stop, and hand the page what can be saved. The world is
 * whole unless the throw came out of oc_step (a trap or an abort part-way
 * through a step); the read-only exports and oc_set_param (which changes the
 * config only once it has passed every check) leave it as it was. */
function fail(err, what) {
  var whole = owns && !stepping;
  running = false; stopRequested = false; stepping = false; session++;
  var msg = { type: "error", message: (what ? what + ": " : "") + String(err && err.message || err), totalSteps: totalSteps };
  var transfer = [];
  if (whole) {
    try { postRows(); msg.mem = heap().slice(0); transfer.push(msg.mem); } catch (e) { delete msg.mem; }
  }
  rows = [];
  owns = false;
  postMessage(msg, transfer);
}
function guarded(fn) { try { fn(); } catch (err) { fail(err, ""); } }

onmessage = function (e) {
  var msg = e.data || {};
  if (msg.cmd === "start") {
    running = false; stopRequested = false; owns = false; session++;
    recEvery = msg.recEvery || 60;
    famK = msg.famK || 8;
    var my = session, p;
    try { p = ensureModule(msg); }
    catch (err) { postMessage({ type: "error", message: "the Ocean module did not load: " + err }); return; }
    p.then(function () {
      if (my !== session) return;   /* a newer start took over */
      try { H.take(M, msg.mem, "the worker's"); }
      catch (err) { postMessage({ type: "error", message: String(err && err.message || err) }); return; }
      owns = true;
      totalSteps = 0; samples = []; chunkSteps = 60; lastStats = 0; rows = [];
      running = true;
      guarded(function () { postStats(performance.now()); });   /* the page flips to 'turbo' on the first stats */
      if (running) scheduleChunk();
    }, function (err) { postMessage({ type: "error", message: "the Ocean module did not load: " + err }); });
  } else if (msg.cmd === "stop") {
    if (running) stopRequested = true;   /* honoured at the next chunk boundary */
    else if (owns) guarded(finishStop);
    else postMessage({ type: "error", message: "Turbo was not running" });
  } else if (msg.cmd === "resume") {
    if (!owns || running) return;
    running = true; stopRequested = false; session++; samples = []; chunkSteps = 60;
    guarded(function () { postStats(performance.now()); });
    if (running) scheduleChunk();
  } else if (msg.cmd === "rec") {
    recEvery = msg.every || recEvery;
  } else if (msg.cmd === "set") {
    var key = String(msg.key), value = +msg.value;
    if (!M || !owns) { postMessage({ type: "set", key: key, value: value, ok: false, error: "Turbo is not running" }); return; }
    try {
      var ok = H.withCString(M, key, function (ptr) { return M._oc_set_param(ptr, value); });
      postMessage({ type: "set", key: key, value: value, ok: !!ok, error: ok ? "" : H.cString(M, M._oc_last_error()),
                    frame: frameNow() });
    } catch (err) { fail(err, "on a live setting"); }
  } else if (msg.cmd === "wiring") {
    if (!M || !owns) { postMessage({ type: "wiring", none: true }); return; }   /* no world here (yet, or any more) */
    try { postMessage(wiring()); } catch (err) { fail(err, "on the wiring"); }
  } else if (msg.cmd === "snapshot") {
    /* Save world while Turbo runs: a copy of the world as it is now, between
     * two chunks (no step is part-way), and Turbo carries on. Every live
     * setting sent before this question is in it (their answers go out
     * first), none sent after. */
    if (!M || !owns) { postMessage({ type: "snapshot", id: msg.id, none: true }); return; }
    try {
      var copy = heap().slice(0), f = frameNow();   /* the copy first, untouched by the sync that reads its frame (a sync never steps) */
      postMessage({ type: "snapshot", id: msg.id, mem: copy, frame: f, pop: M._oc_creature_count(), food: M._oc_food_count(),
                    pred: M._oc_predator_count(), totalSteps: totalSteps }, [copy]);
    } catch (err) { fail(err, "on Save world"); }
  } else if (msg.cmd === "probe") {
    /* A saved world tried before the page opens it, in this worker's own
     * module (a worker made for it: it never runs Turbo, and the page
     * terminates it after the answer, or when it takes too long): the image
     * in, checked against its header, the page's calls, one step, checked
     * again (web/ocean_handoff.js probeWorld). The image goes back with the
     * answer (transferred both ways: no copy). A trap is an answer too. */
    var answer = function (r) {
      r.type = "probe"; r.id = msg.id; r.data = msg.data;
      postMessage(r, msg.data && msg.data.buffer ? [msg.data.buffer] : []);
    };
    var q;
    try { q = ensureModule(msg); } catch (err) { answer({ ok: false, why: "the engine did not load (" + err + ")" }); return; }
    q.then(function () {
      var r;
      try { r = H.probeWorld(M, msg.data, msg.bytes, msg.expect); }
      catch (err) {
        r = { ok: false, trap: err instanceof WebAssembly.RuntimeError,
              why: (err instanceof WebAssembly.RuntimeError ? "the engine stopped on it (" : "") + String(err && err.message || err) + (err instanceof WebAssembly.RuntimeError ? ")" : "") };
      }
      answer(r);
    }, function (err) { answer({ ok: false, why: "the engine did not load (" + err + ")" }); });
  }
};

/* the Brains dashboard's wiring of the world now (web/ocean.js wiringNow's
 * numbers): oc_wiring allocates, so the view is cut after it */
function wiring() {
  var nS = M._oc_num_senses(), nA = M._oc_num_actions(), n = M._oc_wiring();
  var data = H.f32(M, M._oc_wiring_data(), 2 * nS * nA);
  return { type: "wiring", n: n, senses: nS, actions: nA, path: data.slice(0, nS * nA), direct: data.slice(nS * nA), frame: frameNow() };
}

/* the frame counter, from the stats (oc_stats needs an oc_sync) */
function frameNow() { M._oc_sync(); return H.f64(M, M._oc_stats(), statsLen())[1]; }
/* one dashboard sample: the same row the page records (web/ocean_handoff.js row()) */
function sample() { M._oc_sync(); rows.push(H.row(M, famK, statsLen())); }
function runChunk() {
  if (!running) return;
  if (stopRequested) { finishStop(); return; }
  var t0 = performance.now(), left = chunkSteps;
  /* step to each sampling boundary exactly, so the samples land on the frames
   * the page would sample */
  var f = frameNow();
  while (left > 0) {
    var toNext = recEvery - (f % recEvery);
    var n = Math.min(left, toNext);
    stepping = true;
    M._oc_step(n);
    stepping = false;
    left -= n; f += n;
    if (f % recEvery === 0) sample();
  }
  var t1 = performance.now(), elapsed = Math.max(1, t1 - t0);
  totalSteps += chunkSteps;
  samples.push([t0, chunkSteps]);
  while (samples.length > 1 && samples[0][0] < t1 - 1000) samples.shift();
  chunkSteps = Math.max(10, Math.min(20000, Math.round(chunkSteps * 150 / elapsed)));
  if (t1 - lastStats >= 250) postStats(t1);
  scheduleChunk();
}
function postRows() {
  if (!rows.length) return;
  postMessage({ type: "rec", rows: rows });
  rows = [];
}
function postStats(now) {
  lastStats = now;
  postRows();
  var sps = 0;
  if (samples.length) {
    var span = (now - samples[0][0]) / 1000, sum = 0;
    for (var i = 0; i < samples.length; i++) sum += samples[i][1];
    if (span > 0.05) sps = sum / span;
  }
  /* the world's numbers now, for the page's readout: the stats copied
   * before oc_summary allocates (web/ocean_handoff.js row's order) */
  M._oc_sync();
  var st = H.f64(M, M._oc_stats(), statsLen()), su = H.f64(M, M._oc_summary(), M._oc_summary_len());
  postMessage({ type: "stats", frame: st[1], pop: M._oc_creature_count(), food: M._oc_food_count(),
                pred: M._oc_predator_count(), stepsPerSec: Math.round(sps), totalSteps: totalSteps, st: st, su: su });
}
function finishStop() {
  running = false;
  stopRequested = false;
  postRows();
  var copy = heap().slice(0);
  postMessage({ type: "memory", mem: copy, totalSteps: totalSteps }, [copy]);
}
