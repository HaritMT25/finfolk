"use strict";
/* evo_boids TURBO worker — steps the sim headless at full speed, no rendering.
 * Classic worker (no modules). Protocol:
 *   in : {cmd:'start', checkpoint: string, js, wasm, threads}
 *                                          -> load the module the page uses
 *                                             (once), load checkpoint, run
 *                                             chunked loop
 *   in : {cmd:'stop'}                      -> finish current chunk, post the
 *                                             checkpoint back, go idle
 *   in : {cmd:'rec', every}                -> the dashboards' sampling interval
 *   in : {cmd:'set', key, value, quiet, readback}
 *                                          -> a live setting into the running
 *                                             world, between two chunks (the
 *                                             module's evo_set_param: its own
 *                                             whitelist and checks; the page
 *                                             checks first, as for its own)
 *   out: {type:'set', key, value, quiet, ok, config, configError, error, notRunning}
 *                                          -> its answer: applied (config,
 *                                             when readback asked: the world's
 *                                             config as the engine now holds
 *                                             it, or configError: why it could
 *                                             not be read), refused (error), or
 *                                             no world here (notRunning: the
 *                                             page keeps it)
 *   out: {type:'stats', frame, pop, food, pred, stepsPerSec, totalSteps} ~4x/s
 *   out: {type:'rec', s, b, c}             -> what the dashboard recorder saw
 *                                             (samples, births, changes; see
 *                                             wasm/evo_wasm.cpp), with each
 *                                             stats message and before the
 *                                             checkpoint
 *   out: {type:'checkpoint', json}
 *   out: {type:'error', message}
 * Never calls _evo_sync or any render export; dt is fixed inside _evo_step —
 * no wall-clock time is ever passed to the sim.
 *
 * The page passes the module script/wasm URLs it loaded, so a threaded page
 * runs Turbo threaded too (a dedicated worker inherits the page's cross-origin
 * isolation). If the threaded module cannot start here, the single-threaded
 * one would need its own URLs, so the error is reported and the page keeps its
 * state — nothing is lost. */

var Module = null;
var modulePromise = null;
var running = false;
var stopRequested = false;
var chunkSteps = 60;   /* adaptive: targets ~200 ms of stepping per chunk */
var totalSteps = 0;
var startFrame = 0;
var samples = [];      /* [chunkStartMs, steps] pairs, rolling ~1 s window */
var lastStats = 0;
var recEvery = 60, recCulled = 0;
var rec = [[], [], []]; /* recorder output not yet posted: Float64Array pieces per stream */

/* MessageChannel pump: schedules the next chunk as a plain macrotask (worker
 * timers can be throttled in background tabs; a port message is not). A 'stop'
 * posted by the page queues BEFORE the pump's next self-message, so the
 * onmessage handler below always gets to set stopRequested first, and the
 * flag check at the top of runChunk honours it before any further stepping. */
var pump = new MessageChannel();
pump.port1.onmessage = runChunk;
function scheduleChunk() { pump.port2.postMessage(0); }

function ensureModule(msg) {
  if (!modulePromise) {
    var js = msg.js || "evo_boids.js", wasm = msg.wasm || "evo_boids.wasm";
    importScripts(js);
    modulePromise = createEvoBoids({
      locateFile: function (path) { return path.slice(-5) === ".wasm" ? wasm : path; },
      mainScriptUrlOrBlob: js
    }).then(function (m) {
      Module = m;
      if (msg.threads && Module._evo_set_threads) Module._evo_set_threads(msg.threads);
      return m;
    });
  }
  return modulePromise;
}

function withCString(str, fn) {
  var size = Module.lengthBytesUTF8(str) + 1;
  var ptr = Module._malloc(size);
  Module.stringToUTF8(str, ptr, size);
  var r = fn(ptr);
  Module._free(ptr);
  return r;
}

onmessage = function (e) {
  var msg = e.data || {};
  if (msg.cmd === "start") {
    if (running) return;
    recEvery = msg.recEvery || 60;
    recCulled = msg.culled || 0;
    var p;
    try { p = ensureModule(msg); }
    catch (err) { postMessage({ type: "error", message: "wasm load failed: " + err }); return; }
    p.then(
      function () { startRun(String(msg.checkpoint)); },
      function (err) { postMessage({ type: "error", message: "wasm load failed: " + err }); }
    );
  } else if (msg.cmd === "stop") {
    stopRequested = true; /* honoured at the next chunk boundary */
  } else if (msg.cmd === "rec") {
    recEvery = msg.every;
    if (Module && Module._evo_rec_config) Module._evo_rec_config(recEvery, -1);
  } else if (msg.cmd === "set") {
    /* (the checkpoint posted at the hand-off carries the world's config, so an applied value goes back with it) */
    var key = String(msg.key), value = +msg.value, quiet = !!msg.quiet;
    if (!Module || !running) {
      postMessage({ type: "set", key: key, value: value, quiet: quiet, ok: false, notRunning: true, error: "Turbo is not running" });
      return;
    }
    /* a value no field of the engine can keep (past float32's range: it would run as infinity) is refused before it
     * is applied, as the page refuses it (renderer.js tooBig) */
    if (!isFinite(Math.fround(+value.toPrecision(9)))) {
      postMessage({ type: "set", key: key, value: value, quiet: quiet, ok: false, config: null,
                    error: key + " is too large for the engine (it keeps 32-bit numbers, at most about 3.4e38)" });
      return;
    }
    var ok = Module._evo_set_param ? withCString(key, function (ptr) { return Module._evo_set_param(ptr, value); }) : 0;
    /* applied, and asked for (readback: a value the engine's clamps move, a speed past the other or a predator floor past 2000):
     * the world's whole config as the engine now holds it, the page's record of what runs (its checkpoint is the
     * module's only way to say it). A world whose state overflowed writes "inf", which is not JSON: configError
     * says why, the value is applied all the same, and the page goes by what it sent */
    var config = null, configError = "";
    if (ok && msg.readback) {
      try { config = JSON.parse(Module.UTF8ToString(Module._evo_checkpoint())).config; }
      catch (err) {
        if (err instanceof WebAssembly.RuntimeError) throw err;   /* (the engine trapped: the worker dies, the page's onerror recovers) */
        configError = String(err && err.message || err);
      }
    }
    postMessage({ type: "set", key: key, value: value, quiet: quiet, ok: !!ok, config: config, configError: configError,
                  error: ok ? "" : Module._evo_set_param ? Module.UTF8ToString(Module._evo_last_error()) : "this module has no live settings" });
  }
};

/* the dashboard recorder (absent from an older module): collect after each
 * chunk, post with the stats */
function heapBuf() { return Module.wasmMemory ? Module.wasmMemory.buffer : Module.HEAPU8.buffer; }
function takeRec() {
  if (!Module._evo_rec_take) return;
  Module._evo_rec_take();
  for (var k = 0; k < 3; k++) {
    var n = Module._evo_rec_count(k);
    if (n) rec[k].push(new Float64Array(heapBuf(), Module._evo_rec_data(k), n).slice());
  }
}
function postRec() {
  if (!rec[0].length && !rec[1].length && !rec[2].length) return;
  var out = rec.map(function (parts) {
    var len = 0, o = 0;
    parts.forEach(function (p) { len += p.length; });
    var a = new Float64Array(len);
    parts.forEach(function (p) { a.set(p, o); o += p.length; });
    return a;
  });
  rec = [[], [], []];
  postMessage({ type: "rec", s: out[0], b: out[1], c: out[2] }, [out[0].buffer, out[1].buffer, out[2].buffer]);
}

function startRun(checkpoint) {
  var ok = withCString(checkpoint, function (ptr) { return Module._evo_load_checkpoint(ptr); });
  if (!ok) {
    postMessage({ type: "error", message: Module.UTF8ToString(Module._evo_last_error()) });
    return;
  }
  /* absolute frame counter comes from the checkpoint; we advance it locally
   * (frame = startFrame + steps run) since _evo_stats needs _evo_sync */
  startFrame = 0;
  try {
    var cp = JSON.parse(checkpoint);
    if (cp && typeof cp.frame === "number") startFrame = cp.frame;
  } catch (err) { /* keep 0: frame becomes steps-this-session */ }
  totalSteps = 0;
  samples = [];
  chunkSteps = 60;
  lastStats = 0;
  rec = [[], [], []];
  if (Module._evo_rec_config) Module._evo_rec_config(recEvery, recCulled);
  running = true;
  stopRequested = false;
  postStats(performance.now()); /* immediate: the page flips to 'turbo' on first stats */
  scheduleChunk();
}

function runChunk() {
  if (!running) return;
  if (stopRequested) { finishStop(); return; }
  var t0 = performance.now();
  Module._evo_step(chunkSteps);
  takeRec();
  var t1 = performance.now();
  var elapsed = Math.max(1, t1 - t0);
  totalSteps += chunkSteps;
  samples.push([t0, chunkSteps]);
  while (samples.length > 1 && samples[0][0] < t1 - 1000) samples.shift();
  chunkSteps = Math.max(30, Math.min(20000, Math.round(chunkSteps * 200 / elapsed)));
  if (t1 - lastStats >= 250) postStats(t1);
  scheduleChunk();
}

function postStats(now) {
  lastStats = now;
  postRec();
  var sps = 0;
  if (samples.length) {
    var span = (now - samples[0][0]) / 1000;
    var sum = 0;
    for (var i = 0; i < samples.length; i++) sum += samples[i][1];
    if (span > 0.05) sps = sum / span;
  }
  postMessage({
    type: "stats",
    frame: startFrame + totalSteps,
    pop: Module._evo_creature_count(),
    food: Module._evo_food_count(),
    pred: Module._evo_predator_count(),
    stepsPerSec: Math.round(sps),
    totalSteps: totalSteps
  });
}

function finishStop() {
  running = false;
  stopRequested = false;
  /* every departure up to the hand-off, then the rest of the recording,
   * before the checkpoint (the page re-baselines when it loads it) */
  if (Module._evo_rec_flush) { Module._evo_rec_flush(); takeRec(); }
  postRec();
  postMessage({ type: "checkpoint", json: Module.UTF8ToString(Module._evo_checkpoint()) });
}
