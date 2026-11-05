"use strict";
/* evo_boids 3-D Ocean: the render profiler and the benchmark controls
 * (window.EvoOceanPerf; in node, module.exports, for tests/ocean_perf_tests.cjs).
 *
 * Measurement only. Nothing here reaches the simulation, and the page draws
 * the same without it: by default the page holds EvoOceanPerf.disabled,
 * whose methods are empty (no clock read, no allocation, no GL call). A real
 * profiler exists only when the link asks for one:
 *   ?renderBench=1  the benchmark (EvoOcean.bench, EvoOcean.perf): the page
 *                   starts paused, before its first frame, with Hold 60 fps off
 *   ?perf=1         a profiler on the running page (EvoOcean.perf); it records
 *                   nothing until configured
 * Even then it records only while configured to (configure, resetCapture,
 * stopSampling, drain).
 *
 * create(): one profiler.
 *   CPU spans (SPANS, fixed indices): raw samples in a preallocated ring of
 *     16,384 frames (two minutes at 60 Hz), with the frame's raw rAF interval
 *     (before the page's 100 ms clamp) and its counters (COUNTERS). A capture
 *     that overflows the ring says so and is invalid. No per-frame logging,
 *     JSON or sorting: summarize() computes percentiles afterwards. cpu
 *     "frame" times only the whole frame (two clock reads); cpu true times
 *     every span; off reads no clock at all.
 *   GPU timing (GpuTimer, EXT_disjoint_timer_query_webgl2 on the drawing
 *     context), optional and asynchronous: gpu "frame" is one elapsed query
 *     around the scene's submission, "draws" one per watched object (watch:
 *     the object's onBeforeRender / onAfterRender, chained), never both and
 *     never nested; every sampleEvery-th submission (6), at most 64 queries
 *     outstanding (a full pool skips the sample and counts it; rendering never
 *     waits). Results are read on later frames, only once available, in ms
 *     (ns / 1e6, never truncated); a disjoint event discards every outstanding
 *     one, a lost context discards them and starts a new generation (fresh
 *     queries and extension after the restore). Unsupported, skipped and
 *     invalid samples are statuses, never 0 ms. A draw scope covers that
 *     object's submission (its uploads included), not pure shader time; three
 *     draws a transparent double-sided object twice inside one scope, so draw
 *     counts come from renderer.info, not from scopes.
 * summarize(capture), exportCapture(capture): FPS (scene submissions over
 *   wall time), rAF cadence, span and GPU percentiles, CSV text.
 * visualRandom(seed): xorshift32, for the scene's snow and current streaks in
 *   the benchmark (opts.visualRandom); Math.random and the engine's RNG are
 *   untouched.
 * bench(hooks): EvoOcean.bench (see there). */
(function (root) {
  /* [name, exact boundary, inclusive of other spans] */
  var SPANS = [
    ["step", "M._oc_step(steps): the page's own timing of it, reused (no extra clock read)", false],
    ["sync", "M._oc_sync()", false],
    ["snapshot", "snapshot() after the sync; also fresh()'s rare rebuild after memory growth (that one nests inside its caller's span)", false],
    ["dashboard", "takeSample() and the fresh() after it", false],
    ["controller", "the pitch estimate, the movement axes, the selected fish by id and its death hand-over", false],
    ["cameraPick", "scene.render: animation, follow, flight, controls, near / far, hover picking", false],
    ["fishPack", "fillFish(): the fish's instance attributes; inclusive of appearanceRows and geneRanges", true],
    ["appearanceRows", "the gene slots' reconciliation (EvoAppearanceSlots.prepare: ids matched, the dead released, the new fish's genes copied into their slots, iGeneSlot written); inside fishPack", false],
    ["geneRanges", "planning the gene texture's upload (the dirty slots' ranges, or nothing); inside fishPack", false],
    ["otherPack", "predators, food, currents, trail and rings, the snow switch, the caustic fade, the flashlight's aim", false],
    ["submit", "renderer.render(scene, camera), with the GPU frame query's begin / end", false],
    ["card", "updateCard()", false],
    ["hud", "the fps count and the governor, updateHud()", false],
    ["gpuPoll", "the GPU queries' availability and disjoint processing (at the frame's start)", false],
    ["frameCpu", "the whole application frame callback; inclusive of every span above", true]
  ];
  var COUNTERS = [
    ["epoch", "the world's epoch (ocean.js afterNewWorld; Turbo keeps it)"],
    ["turbo", "0 live, 1 entering, 2 turbo, 3 exiting"],
    ["paused", "1 when paused"],
    ["simN", "fish in the simulation (the snapshot's n)"],
    ["tick", "the engine's frame (stats[1]) after this frame's steps"],
    ["stepsReq", "steps asked of oc_step this frame"],
    ["submitted", "1 when renderer.render completed this frame"],
    ["hidden", "1 when the dashboards hid the tank (no render)"],
    ["lost", "1 when the WebGL context was lost (no render)"],
    ["diag", "1 when a diagnostic (a parity probe) ran in this frame; summaries leave it out"],
    ["bodyInst", "body instances submitted (each fish once)"],
    ["barbelInst", "barbel-strip instances submitted"],
    ["shadowInst", "fish-shadow instances submitted"],
    ["lod", "0 the plain fish mesh, 1 coarse, 2 medium appearance template"],
    ["tplVerts", "the body template's vertices"],
    ["tplTris", "the body template's triangles"],
    ["calls", "renderer.info.render.calls"],
    ["triangles", "renderer.info.render.triangles"],
    ["points", "renderer.info.render.points"],
    ["lines", "renderer.info.render.lines"],
    ["instBytes", "fish instance-attribute bytes queued for upload (update ranges)"],
    ["instAllocBytes", "fish instance-attribute bytes allocated (a rebuilt geometry, uploaded whole)"],
    ["geneSrcBytes", "gene bytes copied into the gene slots (63 floats a fish new to the renderer; 0 when the fish are the last frame's)"],
    ["genePadBytes", "padding bytes written (one float a new fish)"],
    ["geneDirtySlots", "gene slots outstanding for upload (the plan's)"],
    ["geneRanges", "gene upload ranges planned (0: none, or one full upload: geneFull)"],
    ["geneUploads", "gene texture updates three performed (DataTexture.onUpdate; one per consumed texture version)"],
    ["geneUploadBytes", "bytes of those uploads (the consumed plan's)"],
    ["texAllocs", "gene textures allocated"],
    ["texCapacity", "gene texture capacity, fish slots"],
    ["geneFull", "1 when a whole-texture gene upload was planned (new GPU storage, or the full policy)"],
    ["geneUploadCalls", "gene texSubImage2D calls of the consumed uploads (one per range, one for a whole upload)"],
    ["gpuIssued", "GPU elapsed queries begun this frame"]
  ];
  var LABELS = ["frame", "fishBody", "barbels", "fishShadow", "predBody", "predShadow", "floor", "surface", "food", "snow", "other"];
  var STATUS = ["ok", "disjoint", "aborted", "lost"];
  var TURBO = { live: 0, entering: 1, turbo: 2, exiting: 3 };
  function index(list) { var o = {}; list.forEach(function (e, i) { o[typeof e === "string" ? e : e[0]] = i; }); return o; }
  var SPAN = index(SPANS), K = index(COUNTERS), LABEL = index(LABELS);

  function perfNow() { return typeof performance !== "undefined" ? performance.now() : Date.now(); }

  /* ---------------- GPU timer: EXT_disjoint_timer_query_webgl2 ---------------- */
  function GpuTimer(gl, o) {
    o = o || {};
    this.gl = gl;
    this.max = o.maxQueries || 64;
    this.resCap = o.results || 65536;
    this.ext = null; this.generation = 0; this.lost = false;
    this.capture = 0;                 /* the capture a query belongs to: a later capture never takes an earlier one's result */
    this.pool = []; this.live = 0;    /* query objects of this generation: pooled, outstanding or active */
    this.out = []; this.active = null;
    this.rFrame = new Float64Array(this.resCap); this.rLabel = new Uint8Array(this.resCap);
    this.rMs = new Float64Array(this.resCap); this.rStatus = new Uint8Array(this.resCap); this.rGen = new Uint32Array(this.resCap);
    this.resetStats();
    this.acquire();
  }
  GpuTimer.prototype.resetStats = function () {
    this.rN = 0;
    this.st = { attempted: 0, issued: 0, ok: 0, unsupported: 0, skippedPool: 0, refusedNest: 0, disjointEvents: 0,
                discardedDisjoint: 0, aborted: 0, discardedLost: 0, resultOverflow: 0, droppedEarlier: 0 };
  };
  /* a new capture: fresh results and counts; queries still outstanding from
   * an earlier one are dropped when they complete, never recorded here */
  GpuTimer.prototype.newCapture = function () { this.capture++; this.resetStats(); };
  GpuTimer.prototype.current = function (r) { return r.cap === this.capture; };
  /* outstanding queries: this capture's (all: any capture's) */
  GpuTimer.prototype.pending = function (all) {
    var n = this.active && (all || this.current(this.active)) ? 1 : 0;
    for (var i = 0; i < this.out.length; i++) if (all || this.current(this.out[i])) n++;
    return n;
  };
  GpuTimer.prototype.acquire = function () {
    var gl = this.gl;
    this.ext = gl && !(gl.isContextLost && gl.isContextLost()) ? gl.getExtension("EXT_disjoint_timer_query_webgl2") || null : null;
    if (this.ext) gl.getParameter(this.ext.GPU_DISJOINT_EXT);   /* clear a stale disjoint flag */
  };
  GpuTimer.prototype.supported = function () { return !!this.ext && !this.lost; };
  GpuTimer.prototype.busy = function () { return this.out.length > 0 || !!this.active; };
  GpuTimer.prototype.isActive = function () { return !!this.active; };
  GpuTimer.prototype.record = function (r, status, ms) {
    if (this.rN >= this.resCap) { this.st.resultOverflow++; return; }
    var i = this.rN++;
    this.rFrame[i] = r.frame; this.rLabel[i] = r.label; this.rMs[i] = status === 0 ? ms : NaN;
    this.rStatus[i] = status; this.rGen[i] = r.gen;
  };
  /* one elapsed query from here to end(); false (and counted) when it can't */
  GpuTimer.prototype.begin = function (frame, label) {
    this.st.attempted++;
    if (this.lost || !this.ext) { this.st.unsupported++; return false; }
    if (this.active) { this.st.refusedNest++; return false; }   /* never nested */
    var q = this.pool.length ? this.pool.pop() : null;
    if (!q && this.live < this.max) { q = this.gl.createQuery(); if (q) this.live++; }
    if (!q) { this.st.skippedPool++; return false; }
    if (!this.out.length) this.gl.getParameter(this.ext.GPU_DISJOINT_EXT);   /* nothing outstanding: start clean */
    this.gl.beginQuery(this.ext.TIME_ELAPSED_EXT, q);
    this.active = { q: q, frame: frame, label: label, gen: this.generation, cap: this.capture, aborted: false, disjoint: false };
    this.st.issued++;
    return true;
  };
  GpuTimer.prototype.end = function () {
    if (!this.active) return;
    this.gl.endQuery(this.ext.TIME_ELAPSED_EXT);
    this.out.push(this.active);
    this.active = null;
  };
  /* the submission threw: close the query, and never accept its result */
  GpuTimer.prototype.abort = function () {
    if (!this.active) return;
    try { this.gl.endQuery(this.ext.TIME_ELAPSED_EXT); } catch (e) { /* the context may be gone */ }
    this.active.aborted = true;
    this.out.push(this.active);
    this.active = null;
  };
  /* read what is available (in order), unless the GPU reported a disjoint
   * event: then every outstanding measurement is discarded. Never blocks. */
  GpuTimer.prototype.poll = function () {
    var gl = this.gl;
    if (gl && gl.isContextLost && gl.isContextLost()) { if (!this.lost) this.onLost(); return 0; }
    if (this.lost || !this.ext || !this.out.length) return 0;
    var ready = 0;
    while (ready < this.out.length && gl.getQueryParameter(this.out[ready].q, gl.QUERY_RESULT_AVAILABLE)) ready++;
    if (gl.getParameter(this.ext.GPU_DISJOINT_EXT)) {
      this.st.disjointEvents++;
      for (var i = 0; i < this.out.length; i++) {
        if (this.current(this.out[i])) { this.record(this.out[i], 1); this.st.discardedDisjoint++; }
        else this.st.droppedEarlier++;
        this.pool.push(this.out[i].q);
      }
      this.out.length = 0;
      if (this.active) this.active.disjoint = true;
      return 0;
    }
    for (var j = 0; j < ready; j++) {
      var r = this.out[j];
      if (!this.current(r)) this.st.droppedEarlier++;   /* an earlier capture's: not this one's */
      else if (r.aborted) { this.st.aborted++; this.record(r, 2); }
      else if (r.disjoint) { this.st.discardedDisjoint++; this.record(r, 1); }
      else { this.st.ok++; this.record(r, 0, gl.getQueryParameter(r.q, gl.QUERY_RESULT) / 1e6); }
      this.pool.push(r.q);
    }
    this.out.splice(0, ready);
    return ready;
  };
  /* the context is gone: its queries with it (their handles are dead). Once
   * per loss: the poll's isContextLost() and the event may both report it */
  GpuTimer.prototype.onLost = function () {
    if (this.lost) return;
    var self = this, mine = this.out.concat(this.active ? [this.active] : []).filter(function (r) { return self.current(r); });
    mine.forEach(function (r) { self.record(r, 3); });
    this.st.discardedLost += mine.length;
    this.out = []; this.active = null; this.pool = []; this.live = 0;
    this.ext = null; this.lost = true; this.generation++;
  };
  GpuTimer.prototype.onRestored = function () {
    if (!this.lost) return;
    this.lost = false; this.pool = []; this.live = 0;
    this.acquire();
  };
  GpuTimer.prototype.results = function () {
    var n = this.rN;
    return { n: n, frame: this.rFrame.slice(0, n), label: this.rLabel.slice(0, n), ms: this.rMs.slice(0, n),
             status: this.rStatus.slice(0, n), generation: this.rGen.slice(0, n) };
  };

  /* ---------------- the profiler ---------------- */
  function create(o) {
    o = o || {};
    var now = o.now || perfNow;
    var CAP = o.frames || 16384, NS = SPANS.length, NK = COUNTERS.length, FRAME = SPAN.frameCpu;
    var ts = new Float64Array(CAP), raw = new Float64Array(CAP);
    var cpu = new Float64Array(CAP * NS), cnt = new Float64Array(CAP * NK);
    var count = 0, row = 0, open = false, overflow = false, prevTs = NaN, frameT0 = 0;
    var cpuMode = 0, gpuMode = 0, sampleEvery = 6, recording = false;
    var submissions = 0, sampled = false, inSub = false, attached = null;
    var timer = o.timer || null;   /* a GpuTimer (tests may hand one in) */
    var watched = [];

    function addCpu(k, v) { var i = row * NS + k, c = cpu[i]; cpu[i] = c === c ? c + v : v; }
    function poll() {
      if (!timer || !timer.busy()) return;
      var t = recording && open && cpuMode === 2 ? now() : 0;
      timer.poll();
      if (t) addCpu(SPAN.gpuPoll, now() - t);
    }
    function closeRow() {
      if (cpuMode) cpu[row * NS + FRAME] = now() - frameT0;
      count++; open = false;
    }
    function copyRing(src, width) {
      var n = Math.min(count, CAP), out = new src.constructor(n * width);
      var first = count > CAP ? count % CAP : 0;
      for (var i = 0; i < n; i++) {
        var r = (first + i) % CAP;
        for (var k = 0; k < width; k++) out[i * width + k] = src[r * width + k];
      }
      return out;
    }

    var P = {
      enabled: true,
      /* true while a frame is being recorded: the scene's counters are worth computing */
      active: false,
      SPAN: SPAN, K: K, LABEL: LABEL,
      configure: function (c) {
        c = c || {};
        cpuMode = c.cpu === "frame" ? 1 : (c.cpu ? 2 : 0);
        gpuMode = c.gpu === "frame" ? 1 : (c.gpu === "draws" ? 2 : 0);
        sampleEvery = Math.max(1, Math.floor(c.sampleEvery || 6));
        recording = !!(cpuMode || gpuMode);
        P.active = recording;
        return P.config();
      },
      config: function () { return { cpu: ["off", "frame", "spans"][cpuMode], gpu: ["off", "frame", "draws"][gpuMode], sampleEvery: sampleEvery }; },
      /* the frame callback's first statement: its rAF time, the world's epoch, Turbo's state, paused */
      beginFrame: function (rafTs, epoch, turbo, paused) {
        if (!recording) { poll(); return; }
        if (open) closeRow();   /* the last frame never ended (it threw): kept as it is */
        row = count % CAP;
        if (count >= CAP) overflow = true;
        ts[row] = rafTs; raw[row] = prevTs === prevTs ? rafTs - prevTs : NaN; prevTs = rafTs;
        cpu.fill(NaN, row * NS, row * NS + NS); cnt.fill(NaN, row * NK, row * NK + NK);
        var b = row * NK;
        cnt[b + K.epoch] = epoch; cnt[b + K.turbo] = TURBO[turbo] !== undefined ? TURBO[turbo] : -1; cnt[b + K.paused] = paused ? 1 : 0;
        cnt[b + K.submitted] = 0; cnt[b + K.diag] = 0;
        open = true;
        frameT0 = cpuMode ? now() : 0;
        poll();
      },
      /* oc_step's time as the page measured it (no clock read here) */
      recordStep: function (ms, steps) {
        if (!open) return;
        if (cpuMode) addCpu(SPAN.step, ms);
        cnt[row * NK + K.stepsReq] = steps;
      },
      /* a span's start: a clock reading, or 0 (no reading) unless spans are on */
      beginCpu: function () { return cpuMode === 2 && open ? now() : 0; },
      endCpu: function (k, tok) { if (tok > 0 && open) addCpu(k, now() - tok); },
      /* end span k and start the next with the same reading */
      lap: function (k, tok) {
        if (!(tok > 0) || !open) return 0;
        var t = now();
        addCpu(k, t - tok);
        return t;
      },
      count: function (k, v) { if (open) cnt[row * NK + k] = v; },
      add: function (k, v) { if (!open) return; var i = row * NK + k, c = cnt[i]; cnt[i] = c === c ? c + v : v; },
      markDiagnostic: function () { if (open) cnt[row * NK + K.diag] = 1; },
      endFrame: function (n, tick, hidden) {
        if (!open) return;
        var b = row * NK;
        cnt[b + K.simN] = n; cnt[b + K.tick] = tick; cnt[b + K.hidden] = hidden ? 1 : 0;
        closeRow();
      },
      /* the drawing context: its timer extension, and its loss / restoration */
      attachGL: function (gl) {
        if (!gl || attached === gl) return;
        attached = gl;
        if (!timer) timer = new GpuTimer(gl, { maxQueries: o.maxQueries || 64 });
        var cv = gl.canvas;
        if (cv && cv.addEventListener) {
          cv.addEventListener("webglcontextlost", function () { timer.onLost(); });
          cv.addEventListener("webglcontextrestored", function () { timer.onRestored(); });
        }
      },
      /* an object's own draw scope (gpu "draws"); chains its existing callbacks */
      watch: function (obj, label) {
        if (!obj || watched.indexOf(obj) >= 0) return;
        watched.push(obj);
        var li = LABEL[label] !== undefined ? LABEL[label] : LABEL.other;
        var before = obj.onBeforeRender, after = obj.onAfterRender;
        obj.onBeforeRender = function () {
          if (gpuMode === 2 && sampled && inSub && timer && timer.begin(count, li)) cnt[row * NK + K.gpuIssued] = (cnt[row * NK + K.gpuIssued] || 0) + 1;
          return before.apply(this, arguments);
        };
        obj.onAfterRender = function () {
          var r = after.apply(this, arguments);
          if (gpuMode === 2 && timer && timer.isActive()) timer.end();
          return r;
        };
      },
      beginSubmission: function () {
        if (!open) return;
        inSub = true;
        sampled = gpuMode !== 0 && !!timer && (submissions++ % sampleEvery) === 0;
        if (sampled && gpuMode === 1 && timer.begin(count, LABEL.frame)) cnt[row * NK + K.gpuIssued] = 1;
      },
      /* ok false: the submission threw; an open query is closed and invalidated */
      endSubmission: function (ok) {
        if (timer && timer.isActive()) { if (ok) timer.end(); else timer.abort(); }
        inSub = false; sampled = false;
        if (open) cnt[row * NK + K.submitted] = ok ? 1 : 0;
      },
      /* run fn outside the capture (a diagnostic): no spans, no queries; the frame is marked */
      suspend: function (fn) {
        var c = cpuMode, g = gpuMode;
        P.markDiagnostic();
        cpuMode = 0; gpuMode = 0;
        try { return fn(); } finally { cpuMode = c; gpuMode = g; }
      },
      capabilities: function () {
        return { gpuTimer: !!(timer && timer.supported()), timerGeneration: timer ? timer.generation : 0, lost: !!(timer && timer.lost),
                 maxQueries: o.maxQueries || 64, ringFrames: CAP,
                 crossOriginIsolated: root && "crossOriginIsolated" in root ? !!root.crossOriginIsolated : null };
      },
      /* stop recording frames and starting queries; outstanding ones are still polled */
      stopSampling: function () { recording = false; P.active = false; if (open) closeRow(); },
      /* queries still outstanding, of any capture (drain waits for these) */
      pending: function () { return timer ? timer.pending(true) : 0; },
      /* a new capture: an earlier one's queries, if any are still outstanding, are dropped, never counted here */
      resetCapture: function () {
        count = 0; row = 0; open = false; overflow = false; prevTs = NaN; submissions = 0;
        if (timer) timer.newCapture();
      },
      /* the capture so far, in time order (typed arrays; exportCapture makes text) */
      drain: function () {
        if (open) closeRow();
        var g = timer ? timer.results() : { n: 0 };
        return {
          schema: { spans: SPANS, counters: COUNTERS, labels: LABELS, statuses: STATUS },
          config: P.config(), capabilities: P.capabilities(),
          frames: Math.min(count, CAP), recorded: count, overflow: overflow, valid: !overflow,
          ts: copyRing(ts, 1), raw: copyRing(raw, 1), cpu: copyRing(cpu, NS), cnt: copyRing(cnt, NK),
          /* complete: none of this capture's queries still outstanding (else its GPU data is incomplete) */
          gpu: { results: g, stats: timer ? Object.assign({}, timer.st) : null, pending: timer ? timer.pending(false) : 0,
                 complete: !timer || timer.pending(false) === 0,
                 generation: timer ? timer.generation : 0, supported: !!(timer && timer.supported()) }
        };
      }
    };
    return P;
  }

  /* the page's profiler when none is asked for: nothing recorded, no clock read */
  function noop() {}
  function zero() { return 0; }
  var disabled = {
    enabled: false, active: false, SPAN: SPAN, K: K, LABEL: LABEL,
    configure: noop, config: function () { return { cpu: "off", gpu: "off", sampleEvery: 6 }; },
    beginFrame: noop, recordStep: noop, beginCpu: zero, endCpu: noop, lap: zero, count: noop, add: noop,
    markDiagnostic: noop, endFrame: noop, attachGL: noop, watch: noop, beginSubmission: noop, endSubmission: noop,
    suspend: function (fn) { return fn(); }, capabilities: function () { return { gpuTimer: false, disabled: true }; },
    stopSampling: noop, pending: zero, resetCapture: noop, drain: function () { return null; }
  };
  /* the page's: a real profiler for ?renderBench=1 / ?perf=1, else disabled */
  function forPage(on) { return on ? create() : disabled; }

  /* ---------------- after the capture ---------------- */
  function quantiles(values) {
    var a = Float64Array.from(values).sort(), n = a.length;
    function q(p) { return n ? a[Math.min(n - 1, Math.max(0, Math.ceil(p * n) - 1))] : null; }
    var sum = 0;
    for (var i = 0; i < n; i++) sum += a[i];
    return { n: n, mean: n ? sum / n : null, p50: q(0.5), p95: q(0.95), p99: q(0.99), max: n ? a[n - 1] : null };
  }
  /* FPS = successful scene submissions over the wall time; rAF cadence
   * separately; percentiles of every span (diagnostic frames left out) and of
   * the GPU samples, with their attempted / valid / skipped / discarded counts */
  function summarize(cap) {
    if (!cap) return null;
    var NS = cap.schema.spans.length, NK = cap.schema.counters.length, n = cap.frames;
    var KX = index(cap.schema.counters), keep = [];
    for (var f = 0; f < n; f++) if (cap.cnt[f * NK + KX.diag] !== 1) keep.push(f);
    var wallMs = n > 1 ? cap.ts[n - 1] - cap.ts[0] : 0, subs = 0, raf = [], hidden = 0, lost = 0, slow = 0;
    for (f = 1; f < n; f++) {
      subs += cap.cnt[f * NK + KX.submitted] === 1 ? 1 : 0;
      hidden += cap.cnt[f * NK + KX.hidden] === 1 ? 1 : 0;
      lost += cap.cnt[f * NK + KX.lost] === 1 ? 1 : 0;
      var r = cap.raw[f];
      if (r === r) { raf.push(r); if (r > 25) slow++; }
    }
    var spans = {};
    cap.schema.spans.forEach(function (s, k) {
      var v = [];
      keep.forEach(function (fr) { var x = cap.cpu[fr * NS + k]; if (x === x) v.push(x); });
      if (v.length) spans[s[0]] = quantiles(v);
    });
    var pop = [], ticks = [];
    keep.forEach(function (fr) { pop.push(cap.cnt[fr * NK + KX.simN]); ticks.push(cap.cnt[fr * NK + KX.tick]); });
    var counters = {};
    cap.schema.counters.forEach(function (c, k) {
      var v = [];
      keep.forEach(function (fr) { var x = cap.cnt[fr * NK + k]; if (x === x) v.push(x); });
      if (v.length) { var qq = quantiles(v); counters[c[0]] = { mean: qq.mean, min: Float64Array.from(v).sort()[0], max: qq.max }; }
    });
    var g = cap.gpu && cap.gpu.results, gpu = null;
    if (cap.gpu) {
      var st = cap.gpu.stats || {}, byLabel = {}, perFrame = {};
      for (var i = 0; g && i < g.n; i++) {
        if (g.status[i] !== 0) continue;
        var L = cap.schema.labels[g.label[i]];
        (byLabel[L] = byLabel[L] || []).push(g.ms[i]);
        var key = L + "@" + g.frame[i];
        perFrame[key] = (perFrame[key] || 0) + g.ms[i];
      }
      var labels = {};
      Object.keys(byLabel).forEach(function (L) {
        var sums = Object.keys(perFrame).filter(function (k) { return k.indexOf(L + "@") === 0; }).map(function (k) { return perFrame[k]; });
        labels[L] = { scopes: quantiles(byLabel[L]), perFrame: quantiles(sums) };
      });
      gpu = { supported: cap.gpu.supported, stats: st, pending: cap.gpu.pending, complete: cap.gpu.complete !== false, labels: labels,
              validFraction: st.attempted ? st.ok / st.attempted : null };
    }
    var t0 = ticks.length ? ticks[0] : 0, t1 = ticks.length ? ticks[ticks.length - 1] : 0;
    return {
      valid: cap.valid, overflow: cap.overflow, frames: n, diagnosticFrames: n - keep.length, wallMs: wallMs, config: cap.config,
      fps: wallMs > 0 ? subs / (wallMs / 1000) : null, rafFps: wallMs > 0 ? raf.length / (wallMs / 1000) : null,
      raf: quantiles(raf), over25ms: raf.length ? slow / raf.length : null, hiddenFrames: hidden, lostFrames: lost,
      stepsPerSec: wallMs > 0 ? (t1 - t0) / (wallMs / 1000) : null,
      population: pop.length ? { first: pop[0], last: pop[pop.length - 1], min: Math.min.apply(null, pop), max: Math.max.apply(null, pop) } : null,
      spans: spans, counters: counters, gpu: gpu
    };
  }
  function csvNum(x) { return x === x && x !== undefined && x !== null ? String(Math.round(x * 1e6) / 1e6) : ""; }
  /* plain data for the runner: frames.csv, gpu.csv and the summary */
  function exportCapture(cap) {
    if (!cap) return null;
    var NS = cap.schema.spans.length, NK = cap.schema.counters.length;
    var head = ["frame", "rafTs", "rafInterval"].concat(cap.schema.spans.map(function (s) { return s[0]; }),
                                                        cap.schema.counters.map(function (c) { return c[0]; }));
    var lines = [head.join(",")];
    for (var f = 0; f < cap.frames; f++) {
      var l = [f, csvNum(cap.ts[f]), csvNum(cap.raw[f])];
      for (var k = 0; k < NS; k++) l.push(csvNum(cap.cpu[f * NS + k]));
      for (k = 0; k < NK; k++) l.push(csvNum(cap.cnt[f * NK + k]));
      lines.push(l.join(","));
    }
    var g = cap.gpu && cap.gpu.results, gl = ["submittingFrame,label,ms,status,generation"];
    for (var i = 0; g && i < g.n; i++)
      gl.push([g.frame[i], cap.schema.labels[g.label[i]], g.status[i] === 0 ? csvNum(g.ms[i]) : "", cap.schema.statuses[g.status[i]], g.generation[i]].join(","));
    return { framesCsv: lines.join("\n") + "\n", gpuCsv: gl.join("\n") + "\n", summary: summarize(cap),
             schema: { spans: cap.schema.spans, counters: cap.schema.counters }, config: cap.config, capabilities: cap.capabilities,
             gpuStats: cap.gpu ? cap.gpu.stats : null };
  }

  /* xorshift32 (the benchmark's snow and current streaks): deterministic, [0, 1) */
  function visualRandom(seed) {
    var x = (seed >>> 0) || 2463534242;
    return function () {
      x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0;
      return x / 4294967296;
    };
  }

  /* ---------------- the benchmark controls (EvoOcean.bench, ?renderBench=1) ----------------
   * hooks (from web/ocean.js): module, scene, profiler, page (EvoOcean), last()
   * (the current snapshot; none once the engine stopped), step(n) (oc_step,
   * oc_sync, fenced: false when it could not), epoch(), initArgs(), importWorld(...) (the page's
   * own setup import: oc_init, the sheet, afterNewWorld; fenced: "" or why
   * not, a stopped engine's too, and prepare rejects), setPaused(on),
   * setColourMode(mode) / colourMode() (the page's own colour switch, the View
   * menu's buttons' too, and the mode it is in), dashOpen() (the charts are up).
   *   prepare(case)   the world (through importWorld when it differs), paused,
   *                   colour mode (setColourMode), detail, Hold 60 fps off,
   *                   the tick, then the camera case: "whole", "dense" or
   *                   "follow"; resolves with what it set (the manifest's case)
   *   capture(o)      {durationMs, cpu, gpu, sampleEvery, drainMs}: record, stop
   *                   sampling, drain the GPU queries (up to drainMs), the capture
   *   snapshotCopy()  owned copies of the current snapshot (ids, genes, bodies)
   *   textureParity(o) scene.appearanceTextureParity against snapshotCopy()
   *   stepToTick(t)   step the paused engine to frame t
   *   rafProbe(ms)    rAF timestamps only (the profiler-off baseline)
   *   info()          the drawing context, the page's display state */
  function bench(h) {
    var scene = h.scene, prof = h.profiler, api = h.page;
    var doc = root.document;
    function frames(k) {
      return new Promise(function (res) { var i = 0; (function f() { if (i++ >= k) res(); else root.requestAnimationFrame(f); })(); });
    }
    function wait(ms) { return new Promise(function (res) { setTimeout(res, ms); }); }
    /* the case's colour mode through the page's own switch; the mode the page is then in */
    function setColour(mode) {
      if (!h.setColourMode(mode) || h.colourMode() !== mode) throw new Error("the page has no colour mode " + mode);
    }
    function setCheck(id, on) {
      var e = doc.getElementById(id);
      if (!e) throw new Error("no #" + id);
      if (e.checked !== on) { e.checked = on; e.dispatchEvent(new Event("change")); }
    }
    /* the frame the page's snapshot is at; no snapshot (its reader is fenced: the engine stopped while it was cut again) is an
     * error, never frame 0 (review of #44, round 5) */
    function tick() {
      var s = h.last();
      if (!s) throw new Error("the benchmark has no snapshot of the world (the engine stopped)");
      return s.stats[1];
    }
    /* every step, the first and each one after a frame, through the page's fenced hook (h.step: nothing into a stopped or
     * restarting engine, a trap stops it there); a step it could not take rejects, and no further step is tried */
    function stepToTick(t) {
      t = Math.floor(t);
      function go() {
        var left = t - tick();
        if (left <= 0) return frames(2);
        if (!h.step(Math.min(64, left))) throw new Error("stepToTick: the engine could not step (it stopped, or is restarting)");
        return frames(1).then(go);
      }
      return Promise.resolve().then(go);
    }
    function snapshotCopy() {
      var s = h.last();
      if (!s) return null;
      return { worldEpoch: h.epoch(), tick: s.stats[1], n: s.n, ids: Float64Array.from(s.ids),
               app: s.app ? Float32Array.from(s.app) : null, body: Float32Array.from(s.body),
               segs: Float32Array.from(s.segs), depth: Float32Array.from(s.depth) };
    }
    /* the head of fish c in three's coordinates */
    function head(s, c, W, H) { return [s.segs[12 * c] - W / 2, -s.depth[c], s.segs[12 * c + 1] - H / 2]; }
    function camera(kind) {
      var st = api.state(), s = h.last(), W = st.W, H = st.H, out = { kind: kind };
      if (kind === "dense") {
        var cells = {}, best = null;
        for (var c = 0; c < s.n; c++) {
          var cx = Math.floor(s.segs[12 * c] / 256), cy = Math.floor(s.segs[12 * c + 1] / 256), key = cy * 1e6 + cx;
          var e = cells[key] || (cells[key] = { cx: cx, cy: cy, n: 0, x: 0, y: 0, d: 0 });
          e.n++; e.x += s.segs[12 * c]; e.y += s.segs[12 * c + 1]; e.d += s.depth[c];
        }
        Object.keys(cells).forEach(function (k) {   /* most fish; row-major tie break */
          var e = cells[k];
          if (!best || e.n > best.n || (e.n === best.n && (e.cy < best.cy || (e.cy === best.cy && e.cx < best.cx)))) best = e;
        });
        var tgt = [best.x / best.n - W / 2, -best.d / best.n, best.y / best.n - H / 2];
        api.scene.lookFrom([tgt[0] + 180, tgt[1] + 80, tgt[2] + 240], tgt);
        out.cell = { cx: best.cx, cy: best.cy, occupancy: best.n }; out.target = tgt;
      } else if (kind === "follow") {
        var pick = -1, pickBarb = -1, EA = root.EvoAppearance;
        for (var i = 0; i < s.n; i++) {
          if (pick < 0 || s.ids[i] < s.ids[pick]) pick = i;
          var barb = s.app && EA && s.app[EA.STRIDE * i + EA.MO + 26] > 0.2;
          if (barb && (pickBarb < 0 || s.ids[i] < s.ids[pickBarb])) pickBarb = i;
        }
        var idx = pickBarb >= 0 ? pickBarb : pick, hp = head(s, idx, W, H);
        api.scene.lookFrom([hp[0] + 85, hp[1] + 32, hp[2] + 100], hp);
        api.select(idx);
        api.follow();
        out.selectedId = s.ids[idx]; out.barbels = pickBarb >= 0;
      } else {
        api.scene.lookFrom([0, 920, 1620], [0, -120, 0]);
      }
      return out;
    }
    function rafProbe(ms) {
      var t = [], t0 = 0;
      return new Promise(function (res) {
        (function f(now) {
          if (!t0) t0 = now;
          t.push(now);
          if (now - t0 < ms) root.requestAnimationFrame(f);
          else res(t);
        })(perfNow());
      }).then(function (list) {
        var iv = [];
        for (var i = 2; i < list.length; i++) iv.push(list[i] - list[i - 1]);
        var wall = list.length > 2 ? list[list.length - 1] - list[1] : 0, slow = iv.filter(function (x) { return x > 25; }).length;
        return { frames: iv.length, wallMs: wall, rafFps: wall > 0 ? iv.length / (wall / 1000) : null, raf: quantiles(iv), over25ms: iv.length ? slow / iv.length : null };
      });
    }
    var B = {
      frames: frames, wait: wait, stepToTick: stepToTick, snapshotCopy: snapshotCopy, rafProbe: rafProbe,
      prepare: function (cd) {
        cd = cd || {};
        /* the case's world, or (a case without one) the running world's set-up */
        var ia = h.initArgs() || {}, has = cd.worldSeed !== undefined, world = cd.world || [ia.width, ia.height, ia.depth];
        var want = has ? { seed: cd.worldSeed >>> 0, pop: cd.population, cfg: cd.config || {} } : { seed: ia.seed, pop: ia.population, cfg: ia.cfg || {} };
        var same = ia.seed === want.seed && ia.population === want.pop && ia.width === world[0] && ia.height === world[1] &&
          ia.depth === world[2] && JSON.stringify(ia.cfg || {}) === JSON.stringify(want.cfg);
        var target = Math.floor(cd.tick || 0);
        h.setPaused(true);
        /* another world, or this one already past the case's tick: start it again (the page's own import) */
        if (!same || tick() > target) {
          var why = h.importWorld(want.seed, want.pop, world[2], want.cfg, undefined, [], [world[0], world[1]]);
          if (why) return Promise.reject(new Error("the case's world was refused: " + why));
        }
        if (cd.colourMode) setColour(cd.colourMode);
        if (cd.quality) scene.setQuality(cd.quality);
        setCheck("governor", cd.governor === true);
        return stepToTick(target).then(function () { return frames(3); }).then(function () {
          if (tick() !== target) throw new Error("prepare: the world is at tick " + tick() + ", the case asks for " + target);
          var cam = camera(cd.camera || "whole");
          return wait(cd.settleMs === undefined ? 1500 : cd.settleMs).then(function () {
            var st = api.state();
            cam.view = st.view; cam.flashlightLevel = st.flashlightLevel; cam.following = st.following; cam.selectedId = st.selectedId;
            return { world: [st.W, st.H, st.D], walls: st.walls, n: st.n, tick: st.frame, worldEpoch: h.epoch(), seed: st.seed,
                     colourMode: h.colourMode(), quality: scene.quality(), paused: st.paused,
                     governor: doc.getElementById("governor").checked, camera: cam, appearance: scene.appearance() };
          });
        });
      },
      /* live: one step a frame from here (speed 1), or paused again */
      live: function (on) { h.setPaused(!on); return frames(2); },
      capture: function (c) {
        c = c || {};
        prof.resetCapture();
        prof.configure({ cpu: c.cpu === undefined ? true : c.cpu, gpu: c.gpu || "off", sampleEvery: c.sampleEvery || 6 });
        return wait(c.durationMs || 120000).then(function () {
          prof.stopSampling();
          var t0 = perfNow(), lim = c.drainMs === undefined ? 5000 : c.drainMs;
          return new Promise(function (res) {
            (function drain() { if (!prof.pending() || perfNow() - t0 > lim) res(); else setTimeout(drain, 16); })();
          });
        }).then(function () {
          var cap = prof.drain();
          prof.configure({ cpu: false, gpu: "off" });
          return c.raw ? cap : exportCapture(cap);
        });
      },
      textureParity: function (o) {
        o = o || {};
        return scene.appearanceTextureParity(o.expected === undefined ? snapshotCopy() : o.expected, o);
      },
      info: function () {
        var cv = doc.getElementById("tank"), drawer = doc.querySelector(".drawer, #drawer");
        return { context: scene.contextInfo ? scene.contextInfo() : null, dpr: root.devicePixelRatio,
                 canvasCss: cv ? [cv.clientWidth, cv.clientHeight] : null, crossOriginIsolated: !!root.crossOriginIsolated,
                 userAgent: root.navigator.userAgent, hardwareConcurrency: root.navigator.hardwareConcurrency,
                 colourMode: h.colourMode(), quality: scene.quality(), clarity: scene.clarity ? scene.clarity() : null,
                 /* the charts' own state (EvoOceanDash.isOpen: the page stops drawing the tank under them) */
                 dashboardOpen: !!h.dashOpen(),
                 drawerOpen: !!(drawer && drawer.classList.contains("open")),
                 reducedMotion: root.matchMedia ? root.matchMedia("(prefers-reduced-motion: reduce)").matches : null,
                 profiler: prof.capabilities(), appearance: scene.appearance(), state: api.state() };
      }
    };
    return B;
  }

  var API = {
    SPANS: SPANS, COUNTERS: COUNTERS, LABELS: LABELS, STATUS: STATUS, SPAN: SPAN, K: K, LABEL: LABEL,
    create: create, disabled: disabled, forPage: forPage, GpuTimer: GpuTimer,
    summarize: summarize, exportCapture: exportCapture, quantiles: quantiles, visualRandom: visualRandom, bench: bench
  };
  if (typeof module === "object" && module.exports) module.exports = API;
  if (root && root.document) root.EvoOceanPerf = API;
})(typeof window !== "undefined" ? window : this);
