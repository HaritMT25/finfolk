// @ts-check
"use strict";
/* The Ocean readouts. Evaluation only registers the factory; explicit phases retain page order. */
(function () {
  /** @param {OceanReadoutsPorts} ports @returns {OceanReadouts} */
  function create(ports) {
  /** @type {number[] | null} */
  var summary = null, summaryT = 0;   /* oc_summary, refreshed twice a second for the readout */
  /** @type {boolean} */
  var dirtyHud;
  /** @type {number} */
  var hudT;
  /** @type {{ lab: HTMLElement; bar: HTMLElement; pct: HTMLElement }[]} */
  var histRows;
  /** @type {OceanRateHistory} */
  var rates;
  /** @type {number} */
  var sampleBucket;
  function initHud() {
  dirtyHud = true, hudT = 0, histRows = [];
  }
  function buildHist() {
    var box = ports.el("hist");
    for (var i = 0; i < 8; i++) {
      var row = document.createElement("div"); row.className = "row";
      var lab = document.createElement("span");
      var track = document.createElement("div"); track.className = "track";
      var bar = document.createElement("div"); bar.className = "bar";
      var t = i / 7;
      bar.style.background = "oklch(" + (0.84 - 0.30 * t).toFixed(3) + " " + (0.15 - 0.04 * t).toFixed(3) + " " + (150 + 90 * t).toFixed(0) + ")";
      var pct = document.createElement("b");
      track.appendChild(bar); row.appendChild(lab); row.appendChild(track); row.appendChild(pct);
      box.appendChild(row);
      histRows.push({ lab: lab, bar: bar, pct: pct });
    }
  }
  function labelHist() {
    for (var i = 0; i < 8; i++) histRows[i].lab.textContent = /** @type {string} */ (/** @type {unknown} */ (Math.round(ports.D * i / 8)));
    histRows[0].lab.title = "surface";
  }
  function initRates() {
  /* births / deaths per simulated second over a sliding window (the counters
   * are cumulative; a drop means a new world) */
  rates = {
    q: [],
    reset: function () { this.q.length = 0; },
    push: function (frame, b, d) {
      var q = this.q, last = q[q.length - 1];
      if (last && (frame < last.f || b < last.b)) q.length = 0;
      if (!last || frame !== last.f) q.push({ f: frame, b: b, d: d });
      while (q.length > 2 && q[q.length - 1].f - q[0].f > 6000) q.shift();
    },
    perSec: function (key) {
      var q = this.q;
      if (q.length < 2) return null;
      var a = q[0], b = q[q.length - 1], df = (b.f - a.f) * ports.DT;
      return df > 0 ? (b[key] - a[key]) / df : null;
    }
  };
  }
  /** @param {OceanSnapshot} s @param {number} now */
  function updateHud(s, now) {
    if (!dirtyHud && now - hudT < 500) return;
    dirtyHud = false; hudT = now;
    /* while Turbo owns the world, its numbers: the worker's latest stats and
     * summary (turboView); this page's copy is the world as Turbo took it */
    var tv = ports.turboState !== "live" ? ports.turboView : null;
    if (!tv && ports.has("oc_summary") && (!summary || now - summaryT > 450)) {
      summary = ports.HO.f64(ports.M, ports.M._oc_summary(), ports.M._oc_summary_len());   /* it allocates: the views after it */
      summaryT = now;
      s = ports.fresh(s);
    }
    var st = tv ? tv.st : s.stats, su = tv ? tv.su : summary, g = function (k) { return ports.STATS[k] < st.length ? st[ports.STATS[k]] : NaN; };
    var nFish = tv ? g("pop") : s.n, nFood = tv ? /** @type {number[]} */ (su)[0] : s.fc, nPred = tv ? /** @type {number[]} */ (su)[1] : s.pc;
    var frame = g("frame");
    rates.push(frame, g("births"), g("deaths"));
    ports.setTxt("ro-fish", ports.fmtInt(nFish));
    ports.setTxt("ro-gen", su ? String(Math.round(su[13])) : "–");
    ports.setTxt("ro-depth", g("depthMean").toFixed(0));
    ports.setTxt("ro-fps", String(ports.fps));
    ports.el("ro-fps").className = "num" + (ports.fps && ports.fps < 45 ? " warn" : "");
    ports.updateKeysLegend(); ports.showSpeedCap();
    if (!ports.statOpen) return;
    var rb = rates.perSec("b"), rd = rates.perSec("d");
    var rows = [
      ["fish", ports.fmtInt(nFish)],
      ["food", ports.fmtInt(nFood)],
      ["predators", String(nPred)],
      ["time", ports.fmtTime(frame * ports.DT) + " <small>· frame " + ports.fmtInt(frame) + "</small>"],
      ["seed", ports.initArgs ? String(ports.initArgs.seed) : "–"],
      ["births", ports.fmtInt(g("births")) + (rb !== null ? " <small>· " + rb.toFixed(1) + "/s</small>" : "")],
      ["deaths", ports.fmtInt(g("deaths")) + (rd !== null ? " <small>· " + rd.toFixed(1) + "/s</small>" : "")],
      ["founders added", ports.fmtInt(g("reseeds"))]
    ];
    if (su) {
      rows.push(["died", "<small>starved </small>" + ports.fmtInt(su[3]) + "<small> · old </small>" + ports.fmtInt(su[4]) + "<small> · caught </small>" + ports.fmtInt(su[2])]);
      rows.push(["generation", su[12].toFixed(1) + " <small>avg · " + Math.round(su[13]) + " max</small>"]);
      rows.push(["family lines", ports.fmtInt(su[19])]);
      rows.push(["neutral depth", (su[14] * ports.D).toFixed(0) + " <small>± " + (su[15] * ports.D).toFixed(0) + "</small>"]);
    }
    rows.push(["depth", g("depthMean").toFixed(0) + " ± " + g("depthSd").toFixed(0) + " <small>of " + ports.D.toFixed(0) + "</small>"]);
    var ask = ports.speed(), ran = ports.paused ? ask : ports.lastSteps;
    if (tv && ports.turboStats) rows.push(["steps / s", ports.fmtInt(ports.turboStats.stepsPerSec) + " <small>· Turbo</small>"]);
    else rows.push(["steps / frame", ran + (ran !== ask ? "<small>/" + ask + "</small>" : "") + " <small>· " + ports.fps + " fps</small>"]);
    ports.setHtml("statlist", rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join(""));
    for (var i = 0; i < 8; i++) {
      var k = ports.STATS.hist0 + i, v = k < st.length ? st[k] : 0;
      v = isFinite(v) ? v : 0;
      histRows[i].bar.style.width = Math.min(100, v * 200).toFixed(1) + "%";   /* full track = 50 % */
      histRows[i].pct.textContent = Math.round(v * 100) + "%";
    }
    var notes = [];
    if (ports.paused) notes.push("Paused. Space or ▶ runs it; . steps once.");
    if (ports.turboState !== "live") notes.push(tv ? "Turbo is running: these are its numbers; the picture waits for it." : "Turbo is running: this picture waits for it.");
    if (ports.scene && ports.scene.following()) notes.push("Following a fish" + (ports.display.lightOn() ? ", with the flashlight on." : "."));
    ports.setTxt("statnotes", notes.join(" "));
  }
  function initRecorder() {
    sampleBucket = -1;
  }
  /* ---------------- the dashboards' recorder ---------------- */
  function dash() { return window.EvoOceanDash || null; }
  /* one sample of this frame's synced world: the row the Turbo worker records
   * too (web/ocean_handoff.js row(): the stats copied before the summary and
   * the family lines allocate) */
  /** @param {ArrayLike<number>} st */
  function takeSample(st) {
    if (!dash() || !ports.has("oc_summary")) return;
    var every = /** @type {OceanDashboard} */ (dash()).every(), b = Math.floor(st[1] / every);
    if (b === sampleBucket) return;
    sampleBucket = b;
    /** @type {OceanDashboard} */ (dash()).push(ports.HO.row(ports.M, /** @type {OceanDashboard} */ (dash()).famK, ports.statsLen));
  }
  /* the Brains dashboard's wiring: this world's, or, while Turbo owns the
   * world, the worker's (turboWiring) */
  function wiringNow() {
    if (!ports.M || !ports.has("oc_wiring")) return null;
    if (ports.turboState !== "live") return ports.turboWiring();
    var sh = ports.inspector.brainShape(), n = ports.M._oc_wiring();   /* both allocate: the view after them */
    var data = new Float32Array(ports.heap(), ports.M._oc_wiring_data(), 2 * sh.nS * sh.nA);
    return { at: performance.now(), n: n, senses: sh.nS, actions: sh.nA,
             path: Array.prototype.slice.call(data, 0, sh.nS * sh.nA), direct: Array.prototype.slice.call(data, sh.nS * sh.nA),
             senseNames: ports.cString(ports.M._oc_sensor_names()).split(","), actionNames: ports.cString(ports.M._oc_action_names()).split(",") };
  }
  function attach() {
    if (dash()) /** @type {OceanDashboard} */ (dash()).attach({
      depth: function () { return ports.D; },
      /* (the charts' timer: never into a stopped or restarting engine; a trap here stops it once) */
      familyColor: function (id) { return ports.engineCall(function () { return ports.has("oc_family_color") ? ports.M._oc_family_color(id) : 0x3b5957; }, 0x3b5957); },
      /* what the tank's fish wear now: "family" (Family, or Appearance in a world without appearance genes), "appearance" or
       * "brain"; and the charts' way to show their family colours in the tank */
      colourMode: function () { return ports.display.tankShowsFamily() ? "family" : ports.display.colourMode; },
      showFamilyColours: function () { ports.display.setColourMode("family"); },
      wiring: function () { return ports.turboState !== "live" ? wiringNow() : ports.engineCall(wiringNow, null); },
      setDrawer: ports.setDrawer,
      /* the charts cover the page: no popover left open under them, and the coach mark goes */
      onOpen: function () { ports.setPop(null); ports.hideCoach(); },
      setRecEvery: function (every) {
        if (ports.turboWorker && (ports.turboState === "entering" || ports.turboState === "turbo")) ports.turboWorker.postMessage({ cmd: "rec", every: every });
      }
    });
  }
  return { initHud: initHud, initRates: initRates, initRecorder: initRecorder, attach: attach,
    buildHist: buildHist, labelHist: labelHist, updateHud: updateHud, dash: dash, takeSample: takeSample, wiringNow: wiringNow,
    get summary() { return summary; }, set summary(v) { summary = v; },
    get dirtyHud() { return dirtyHud; }, set dirtyHud(v) { dirtyHud = v; },
    get sampleBucket() { return sampleBucket; }, set sampleBucket(v) { sampleBucket = v; },
    get rates() { return rates; } };
  }
  window.EvoOceanReadouts = { create: create };
})();
