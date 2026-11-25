// @ts-check
"use strict";
/* The Ocean inspector. Evaluation only registers the factory; explicit phases retain page order. */
(function () {
  /** @param {OceanInspectorPorts} ports @returns {OceanInspector} */
  function create(ports) {
  /** @type {OceanReturnPoint | null} */
  var turboReturn = null;    /* the fish to select / follow again after Turbo (restoreAfterTurbo) */
  /** @type {number | null} */
  var selectedId;
  /** @type {boolean} */
  var wantFollow, everSelected;
  function initSelection() {
  selectedId = null, wantFollow = false, everSelected = false;
  }
  /** @type {UiActivationClock} */
  var brainClock;
  function initBrainClock() {
  /* The fish card's live brain (EvoUI.activationClock): the senses and actions
   * the last step kept, which it keeps only while a fish is picked (the
   * capture, oc_set_capture: lazy, as it costs every fish its whole sensing).
   * A fish picked in a world that stepped without it waits for the next step,
   * which a paused world takes only when asked (Space, or . for one). */
  brainClock = EvoUI.activationClock();
  }
  /** @type {HTMLElement} */
  var cardEl;
  /** @type {HTMLCanvasElement} */
  var inetCanvas;
  /** @type {CanvasRenderingContext2D} */
  var inetCtx;
  /** @type {HTMLCanvasElement} */
  var portraitEl;
  /** @type {boolean} */
  var cardExpanded;
  /** @type {Record<string, string | null>} */
  var cardCache;
  /** @type {string | null} */
  var cardFor;
  /** @type {boolean} */
  var cardFlip;
  /** @type {string[] | null} */
  var sensorNames;
  /** @type {string[] | null} */
  var actionNames;
  /** @type {UiBrainNode[]} */
  var netNodes;
  /** @type {number} */
  var netHover;
  /** @type {string} */
  var uiFont;
  /** @type {boolean} */
  var cardFresh;
  /** @type {HTMLCanvasElement} */
  var swatchEl;
  /** @type {HTMLElement} */
  var skinEl;
  /** @type {HTMLElement} */
  var bodyEl;
  /** @type {HTMLElement} */
  var bodyTableEl;
  /** @type {HTMLAnchorElement} */
  var bodyLinkEl;
  /** @type {string} */
  var bodyFor;
  /* the fish picked (and followed) now, for the file, with its family line
   * and place (returnPoint's: what the open needs to pick its nearest
   * kin, as Turbo's hand-back does, if it is gone); in Turbo the one Turbo
   * will pick up again (its place when Turbo took the world) */
  function pickedNow() {
    var r = ports.turboState !== "live" ? turboReturn : returnPoint();
    return r ? { id: r.id, follow: !!r.follow, family: r.family, x: r.x, y: r.y, d: r.d } : null;
  }
  /** @param {OceanSnapshot | null} s @param {number | null} id */
  function indexOfId(s, id) {
    if (id === null || !s) return -1;
    for (var i = 0; i < s.n; i++) if (s.ids[i] === id) return i;
    return -1;
  }
  /** @param {OceanSnapshot | null} s @param {number | null} notId */
  function randomFish(s, notId) {
    if (!s || !s.n) return -1;
    var i = Math.floor(Math.random() * s.n);
    if (s.n > 1 && s.ids[i] === notId) i = (i + 1 + Math.floor(Math.random() * (s.n - 1))) % s.n;
    return i;
  }
  /* handover: a followed fish died and another takes its place (the frame
   * loop), not a fish the visitor picked */
  /** @param {number | null} id @param {boolean} [handover] */
  function select(id, handover) {
    var was = selectedId;
    selectedId = id;
    if (id !== null) { everSelected = true; ports.hideCoach(); }   /* its card opens where the coach mark sits */
    if (id !== null && id !== was && !handover) { ports.cardNewer = true; ports.cardHeld = false; }   /* its card, over the live numbers (updateCard) */
    /* the capture, only into a running engine (Close, Esc and the tour let go of a fish while it is stopped or
     * restarting too: review of #44, round 3, finding 3; a restarted one gets it with its run, applyDisplaySwitches) */
    if ((was === null) !== (id === null) && ports.M && ports.engineState === "ok" && ports.has("oc_set_capture")) {
      ports.M._oc_set_capture(id !== null ? 1 : 0);
      brainClock.capture(id !== null, ports.syncedFrame());
    }
    ports.dirtyHud = true;
  }
  /* F: follow the selected fish; again (or with none): a random one */
  function follow() {
    if (ports.turboState !== "live") { ports.turboPictureHint(); return; }
    ports.engineCall(function () {   /* (a stopped engine: says why; a trap: stops it once, from F, the console or the tour) */
      var s = ports.fresh(ports.lastS);
      if (!s || !s.n) return;
      var idx = !ports.scene.following() ? indexOfId(s, selectedId) : -1;
      if (idx < 0) idx = randomFish(s, selectedId);
      select(s.ids[idx]);
      wantFollow = true;
      if (!ports.scene.following()) ports.scene.setFollow(true);
    }, undefined, "Following a fish");
  }
  function unfollow() {
    wantFollow = false;
    if (ports.scene.following()) ports.scene.setFollow(false);
  }
  /* ---------------- the fish card ---------------- */
  function initCard() {
  cardEl = ports.el("fishcard"), inetCanvas = ports.el("inetc"), inetCtx = /** @type {CanvasRenderingContext2D} */ (inetCanvas.getContext("2d"));
  portraitEl = ports.el("iportrait");
  cardExpanded = window.innerWidth >= 600, cardCache = {}, cardFor = null, cardFlip = false;
  ports.el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
  sensorNames = null, actionNames = null, netNodes = [], netHover = -1, uiFont = "", cardFresh = false;
  }
  function prettyName(n) { return String(n).replace(/_/g, " ").toLowerCase(); }
  function brainShape() {
    if (!sensorNames) {
      sensorNames = ports.has("oc_sensor_names") ? ports.cString(ports.M._oc_sensor_names()).split(",").map(prettyName) : [];
      actionNames = ports.has("oc_action_names") ? ports.cString(ports.M._oc_action_names()).split(",").map(prettyName) : [];
    }
    return { nS: ports.has("oc_num_senses") ? ports.M._oc_num_senses() : sensorNames.length,
             nH: ports.has("oc_num_hidden") ? ports.M._oc_num_hidden() : 12,
             nA: ports.has("oc_num_actions") ? ports.M._oc_num_actions() : /** @type {string[]} */ (actionNames).length };
  }
  function cardText(id, v) { if (cardCache[id] !== v) { cardCache[id] = v; ports.el(id).textContent = v; } }
  /** @param {string} id @param {number} f @param {number} [tick] */
  function setBar(id, f, tick) {
    f = Math.max(0, Math.min(1, f));
    var key = f.toFixed(3) + "|" + (tick === undefined ? "" : tick.toFixed(3));
    if (cardCache[id + "bar"] === key) return;
    cardCache[id + "bar"] = key;
    var bar = ports.el(id);
    /** @type {HTMLElement} */ (bar.firstElementChild).style.transform = "scaleX(" + f.toFixed(3) + ")";
    var t = /** @type {HTMLElement | null} */ (bar.querySelector(".tick"));
    if (t) t.style.left = "calc(" + ((tick || 0) * 100).toFixed(1) + "% - 1px)";
  }
  function showCard() {
    cardEl.hidden = false;
    document.body.classList.add("card-open");
    cardEl.classList.toggle("expanded", cardExpanded);
    ports.el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    cardCache = {};
  }
  function hideCard() {
    if (cardEl.hidden) return;
    cardEl.hidden = true;
    cardFor = null; netHover = -1; cardFlip = false;
    cardEl.classList.remove("flip");
    document.body.classList.remove("card-open");
  }
  function placeCard(fx, fy) {
    var r = cardEl.getBoundingClientRect(), m = 24;
    if (fx < r.left - m || fx > r.right + m || fy < r.top - m || fy > r.bottom + m) return;
    var flip = window.innerWidth < 600 ? fy > window.innerHeight / 2 : fx > window.innerWidth / 2;
    if (flip === cardFlip) return;
    cardFlip = flip;
    cardEl.classList.toggle("flip", flip);
  }
  /* The card's two pictures of the fish (the UI parity plan's U45): the
   * colour key (EvoUI.drawPortrait), a generic silhouette in the colour the
   * charts and the colour modes give it, which is not its likeness (the tank
   * draws the shape and skin it inherited); and, under it, its skin itself:
   * the pattern on its flank, unlit, from its appearance genes
   * (web/ocean_appearance.js), when the module exports them. Both captioned
   * (ocean.html #ikey, #iskin). */
  function initSwatch() {
  swatchEl = ports.el("iswatch"), skinEl = ports.el("iskin");
  }
  /** @param {OceanSnapshot} s @param {number} idx @param {number} size @param {number} elong */
  function drawSwatch(s, idx, size, elong) {
    var EA = window.EvoAppearance;
    if (!swatchEl || !EA || !s.app) { if (swatchEl) swatchEl.hidden = true; if (skinEl) skinEl.hidden = true; return; }
    var W = 96, H = 24, row = s.app.subarray(63 * idx, 63 * idx + 63);
    swatchEl.width = W; swatchEl.height = H;
    var ctx = /** @type {CanvasRenderingContext2D} */ (swatchEl.getContext("2d"));
    ctx.putImageData(new ImageData(EA.flankImage(row, EA.lambdaOf(size, elong), W, H), W, H), 0, 0);
    swatchEl.hidden = false;
    if (skinEl) skinEl.hidden = false;
  }
  /* what the colour key's colour is, in this colour mode (its title) */
  function keyTitle() {
    return "A colour key, not a likeness: " + (ports.colourMode === "brain" ? "the colour of its brain (similar wiring, similar colour)"
      : ports.colourMode === "appearance" ? "the colour of its family line, as the charts show it; in the tank it wears its own skin (below)"
      : "the colour of its family line, as the charts show it") + ".";
  }
  /* oc_inspect(idx) right after the sync: its numbers, then the card */
  /** @param {number} idx @returns {OceanInspection | null} */
  function inspect(idx) {
    if (!ports.has("oc_inspect")) return null;
    var sh = brainShape();   /* first: the name lists allocate (once) */
    if (!ports.M._oc_inspect(idx)) return null;
    var buf = ports.heap(), nc = ports.M._oc_inspect_conn_count();   /* after oc_inspect, which allocates */
    return {
      info: new Float64Array(buf, ports.M._oc_inspect_info(), ports.M._oc_inspect_len()),
      sensors: new Float32Array(buf, ports.M._oc_inspect_sensors(), sh.nS),
      hidden: new Float32Array(buf, ports.M._oc_inspect_hidden(), sh.nH),
      actions: new Float32Array(buf, ports.M._oc_inspect_actions(), sh.nA),
      connCount: nc, conns: new Float32Array(buf, ports.M._oc_inspect_conns(), nc * 5), shape: sh
    };
  }
  function overlap(a, b) {
    return a.width > 0 && a.height > 0 && b.width > 0 && b.height > 0 &&
           a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  }
  /** @param {OceanSnapshot} s @returns {OceanSnapshot} */
  function updateCard(s) {
    if (ports.cardHeld && ports.statOpen) { hideCard(); return s; }   /* under the live numbers: the fish stays selected */
    var idx = s.selIdx, f = idx >= 0 && ports.turboState === "live" ? inspect(idx) : null;
    if (!f) { hideCard(); return s; }
    s = ports.fresh(s);   /* oc_inspect may have grown the memory */
    if (cardEl.hidden) showCard();
    var p = ports.scene.project(s, idx);
    if (p) placeCard(p.x, p.y);
    if (ports.statOpen && overlap(cardEl.getBoundingClientRect(), ports.el("statpanel").getBoundingClientRect())) {
      if (ports.cardNewer) ports.setStatPanel(false);   /* a fish picked over the numbers: its card */
      else { ports.cardHeld = true; hideCard(); return s; }   /* the numbers opened over the card: they */
    }
    var info = f.info, id = Math.round(info[0]);
    var rgb = [s.colors[3 * idx], s.colors[3 * idx + 1], s.colors[3 * idx + 2]];
    var pkey = id + "|" + rgb.join() + "|" + info[4].toFixed(2) + "|" + info[5].toFixed(2) + "|" + ports.colourMode;
    if (cardFor !== pkey) {
      cardFor = pkey;
      EvoUI.drawPortrait(portraitEl, rgb, info[4], info[5], window.devicePixelRatio || 1);
      drawSwatch(s, idx, info[4], info[5]);
      ports.el("ikey").title = keyTitle();
    }
    cardText("ititle", "Fish #" + id);
    /* the common fields, in their order (both pages: EvoUI.cardSubtitle); genes: its genome's length (oc_inspect), one link of its brain each */
    cardText("isub", EvoUI.cardSubtitle({ generation: info[6], family: info[7], genes: info[11],
                                          body: ports.cfgVal("bodyModel") ? [info[4], info[5]] : null }));
    /* its live brain: the last step's, or waiting for one (a fish just picked in a world that stepped without the
     * capture, a new or handed-back world, a fish born in the last step; EvoUI.activationClock). data-activations:
     * current or waiting; data-activations-at: the tick of the activations it shows, empty while it waits (stamp) */
    var tick = s.stats[ports.STATS.frame], state = brainClock.state(tick, info[3]), at = brainClock.stamp(tick, info[3]);
    cardFresh = state === "current";
    if (cardCache.acts !== state + "|" + at) {
      cardCache.acts = state + "|" + at;
      cardEl.dataset.activations = state;
      cardEl.dataset.activationsAt = at === null ? "" : String(at);
    }
    var reproE = ports.cfgVal("reproEnergy"), maxAge = ports.cfgVal("maxAge"), maxSpd = ports.cfgVal("maxSpeed"), pitchMax = ports.cfgVal("pitchMax");
    cardText("ienergyv", info[2].toFixed(1));
    setBar("ienergy", info[2] / (reproE * 2), 0.5);
    ports.el("ienergy").title = info[2] >= reproE ? "enough energy to breed" : "needs " + reproE + " to breed";
    cardText("iagev", Math.round(info[3]) + " s");
    setBar("iage", info[3] / maxAge);
    cardText("ispeedv", String(Math.round(info[1])));
    setBar("ispeed", info[1] / maxSpd);
    cardText("idepthv", info[8].toFixed(0) + " of " + ports.D.toFixed(0));
    setBar("idepth", info[8] / ports.D, info[9]);
    ports.el("idepth").title = "the tick: its neutral depth";
    cardText("ibuoyv", (info[9] * ports.D).toFixed(0));
    setBar("ibuoy", info[9]);
    var deg = Math.atan(info[10]) * 180 / Math.PI;
    cardText("ipitchv", Math.abs(deg) < 0.5 ? "level" : Math.abs(deg).toFixed(0) + "° " + (deg > 0 ? "down" : "up"));
    setBar("ipitch", 0.5 + 0.5 * Math.max(-1, Math.min(1, info[10] / (pitchMax || 0.5))), 0.5);
    drawBody(s, idx, id);
    if (cardExpanded) drawBrain(f);
    return s;
  }
  /* The card's body plan (the M2a preview, DIAGNOSTIC): what the fish
   * inherited (its five physical alleles), what it developed (expressed
   * values, with any developmental limit), what its body measures (the C++
   * law's closed-mesh geometry) and the unloaded material ESTIMATE; speed and
   * turning are not predicted until M2b calibrates them. Built once per fish
   * (its body never changes); hidden when the world has no preview. */
  function initBody() {
  bodyEl = ports.el("ibody"), bodyTableEl = ports.el("ibodyt"), bodyLinkEl = ports.el("ibodylink"), bodyFor = "";
  }
  /** @param {OceanSnapshot} s @param {number} idx @param {number} id */
  function drawBody(s, idx, id) {
    if (!bodyEl) return;
    var B = s.bodyPlan;
    if (!B || !ports.BODY_LAYOUT || idx < 0 || idx * 2 + 1 >= B.owners.length) { bodyEl.hidden = true; bodyFor = ""; return; }
    var owner = B.owners[2 * idx] + 4294967296 * B.owners[2 * idx + 1];
    if (owner !== id) { bodyEl.hidden = true; bodyFor = ""; return; }   /* (never a row of another fish) */
    bodyEl.hidden = false;
    var key = s.worldEpoch + ":" + id;   /* (a new world reuses ids) */
    if (bodyFor === key) return;
    bodyFor = key;
    var at = ports.BODY_LAYOUT.at, st = B.stride, base = idx * st, mm = B.metrics, g = B.genes;
    function v(name, k) { var f = at[name]; return f ? mm[base + f.offset + (k || 0)] : NaN; }
    function fin(i, k) { var f = at.fins; return f ? mm[base + f.offset + ports.BODY_LAYOUT.fins.stride * i + ports.BODY_LAYOUT.fins.values[k]] : NaN; }
    function num(x, d) { return isFinite(x) ? x.toFixed(d === undefined ? 2 : d) : "–"; }
    var lim = v("limits"), why = [];
    if (lim & 1) why.push("eye clipped to the head");
    if (lim & 2) why.push("tail chord capped");
    if (lim & 4) why.push("storage bounded");
    if (lim & 8) why.push("organs bounded");
    if (lim & 16) why.push("shell capped");
    var rows = [
      ["Inherited", "gape " + num(g[5 * idx]) + " · bladder " + num(g[5 * idx + 1]) + " · armour " + num(g[5 * idx + 2]) +
                    " · fat " + num(g[5 * idx + 3]) + " · fibre " + num(g[5 * idx + 4])],
      ["Developed", "mouth " + num(v("gapeDiameter")) + " u · bladder " + num(v("bladderCapacity"), 1) + " u³ · reserve " +
                    num(v("reserveEnergy"), 0) + " E · shell " + num(v("armourThickness")) + " u" + (why.length ? " (" + why.join(", ") + ")" : "")],
      ["Body", num(v("hullLength"), 1) + " u long · " + num(v("hullVolume"), 0) + " u³ · skin " + num(v("wettedArea"), 0) + " u²"],
      ["Silhouette", "front " + num(v("frontalArea"), 1) + " · side " + num(v("sideArea"), 1) + " · plan " + num(v("planArea"), 1) + " u²"],
      ["Tail", num(fin(0, "area"), 1) + " u² · aspect " + num(v("caudalActualAR")) + (lim & 2 ? " (genes ask " + num(v("caudalNominalAR")) + ")" : "")],
      ["Fins", "dorsal " + num(fin(1, "area"), 1) + " · anal " + num(fin(2, "area"), 1) + " · pectorals 2×" + num(fin(3, "area"), 1) +
               " · pelvics 2×" + num(fin(5, "area"), 1) + " u²"],
      ["Mass (est.)", num(v("unloadedMassEstimate")) + " × the neutral body, unloaded (an estimate, not the M2b law)"],
      ["Cruise speed", "not calibrated — M2b"],
      ["Turning radius", "not calibrated — M2b"]
    ];
    bodyTableEl.textContent = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr"), th = document.createElement("th"), td = document.createElement("td");
      th.textContent = r[0]; td.textContent = r[1];
      if (r[1].indexOf("not calibrated") === 0) td.className = "pending";
      tr.appendChild(th); tr.appendChild(td); bodyTableEl.appendChild(tr);
    });
    if (bodyLinkEl && s.app) {   /* the fixture viewer, with this fish's genes (float bits, hex) */
      var words = [], f32 = new Float32Array(1), u32 = new Uint32Array(f32.buffer), k;
      for (k = 0; k < 63; k++) { f32[0] = s.app[63 * idx + k]; words.push(("00000000" + u32[0].toString(16)).slice(-8)); }
      for (k = 0; k < 5; k++) { f32[0] = g[5 * idx + k]; words.push(("00000000" + u32[0].toString(16)).slice(-8)); }
      f32[0] = v("size"); words.push(("00000000" + u32[0].toString(16)).slice(-8));
      f32[0] = v("elong"); words.push(("00000000" + u32[0].toString(16)).slice(-8));
      var page = (window.EVO_ASSETS && window.EVO_ASSETS.bodyplan) || "ocean_bodyplan.html";
      bodyLinkEl.href = page + "#fish=" + id + ":" + words.join("");
      bodyLinkEl.hidden = false;
    } else if (bodyLinkEl) bodyLinkEl.hidden = true;
  }
  /* senses -> hidden -> actions (EvoUI.drawBrain, both pages' network; the Ocean's shape, its depth senses and steer z) */
  /** @param {OceanInspection} f */
  function drawBrain(f) {
    var box = /** @type {HTMLElement} */ (inetCanvas.parentNode), w = box.clientWidth, h = box.clientHeight;
    if (w < 60 || h < 60) return;
    var sh = f.shape;
    var dpr = window.devicePixelRatio || 1, bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (inetCanvas.width !== bw) inetCanvas.width = bw;
    if (inetCanvas.height !== bh) inetCanvas.height = bh;
    if (!uiFont) uiFont = getComputedStyle(document.body).fontFamily;
    netNodes = EvoUI.drawBrain(inetCtx, w, h, f, { nS: sh.nS, nH: sh.nH, nA: sh.nA, gutter: 100, actShort: ports.ACTION_SHORT, actLabels: ports.ACTION_LABELS,
                                                   font: uiFont, dpr: dpr, fresh: cardFresh, prev: netNodes, hover: netHover });
    updateSenseLine();
  }
  function updateSenseLine() {
    if (netHover >= 0 && netNodes[netHover]) {
      var n = netNodes[netHover];
      var label = n.kind === "Sense" ? (/** @type {string[]} */ (sensorNames)[n.i] || "sense " + (n.i + 1)) : n.kind === "Action" ? (ports.ACTION_LABELS[n.i] || /** @type {string[]} */ (actionNames)[n.i]) : "neuron " + (n.i + 1);
      var html = EvoUI.senseHtml(n, cardFresh);
      if (cardCache.sense !== html + label) {
        cardCache.sense = html + label;
        ports.el("isense").innerHTML = html;
        /** @type {HTMLElement} */ (ports.el("isense").querySelector("b")).textContent = label;
      }
    } else {
      var t = EvoUI.senseIdle(cardFresh, ports.coarseMQ.matches, ports.paused, "Space runs it; . steps once");
      if (cardCache.sense !== t) { cardCache.sense = t; ports.el("isense").textContent = t; }
    }
  }
  /** @param {PointerEvent} e */
  function nearestNode(e) {
    var r = inetCanvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    var best = -1, bd = e.pointerType === "mouse" ? 100 : 400;
    netNodes.forEach(function (n, i) { var d = (n.x - x) * (n.x - x) + (n.y - y) * (n.y - y); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  function registerNetwork() {
  inetCanvas.addEventListener("pointermove", function (e) { if (e.pointerType === "mouse") netHover = nearestNode(e); });
  inetCanvas.addEventListener("pointerdown", function (e) { if (e.pointerType !== "mouse") netHover = nearestNode(e); });
  inetCanvas.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") netHover = -1; });
  }
  /* The fish the visitor had picked (and followed) when Turbo took the world:
   * its id, family line, place and whether it was followed, in this world
   * (epoch). The picture can't show it during Turbo; the hand-back (or a
   * recovery) picks it up again: the same fish if it lives, else the nearest
   * of its family line (world distance, across the wrap without walls; the
   * lower id on a tie), else none, said so. Following resumes only if it was
   * on and not let go meanwhile (C, the fit button: no follow; Esc: nothing).
   * Never across a new world. The flashlight preference is never written:
   * the follow's own rule turns the lamp on and puts it back. */
  /** @returns {OceanReturnPoint | null} */
  function returnPoint() {
    if (selectedId === null) return null;
    var s = ports.fresh(ports.lastS), idx = indexOfId(s, selectedId);
    /** @type {OceanReturnPoint} */
    var r = { id: selectedId, follow: !!(ports.scene && ports.scene.following()), epoch: ports.worldEpoch, family: null, x: 0, y: 0, d: 0 };
    if (idx >= 0) {
      r.x = s.segs[12 * idx]; r.y = s.segs[12 * idx + 1]; r.d = s.depth[idx];   /* read before oc_inspect, which may grow the memory */
      var f = inspect(idx);
      if (f) r.family = Math.round(f.info[7]);
    }
    return r;
  }
  function restoreAfterTurbo() {
    if (ports.engineState !== "ok") return;   /* (restarting: rebuildEngine picks it up when the run is back) */
    var r = turboReturn;
    turboReturn = null;
    if (!r || r.epoch !== ports.worldEpoch || !ports.M || ports.turboState !== "live") return;
    var s = ports.fresh(ports.lastS), idx = indexOfId(s, r.id), id = /** @type {number | null} */ (r.id);
    if (idx < 0) { id = nearestOfFamily(s, r); }
    if (id === null) {
      ports.toast("Fish #" + r.id + " did not survive Turbo, nor did any of its family line" + (r.follow ? ": nothing to follow." : "."));
      return;
    }
    select(id, true);
    if (r.follow && ports.scene) { wantFollow = true; ports.scene.setFollow(true); }
    if (id !== r.id) ports.toast("Fish #" + r.id + " died during Turbo: " + (r.follow ? "following" : "showing") + " #" + id + ", the nearest of its family line.");
  }
  /* the nearest living member of r's family line, by id (one oc_inspect per fish: the ids and places copied first) */
  /** @param {OceanSnapshot | null} s @param {OceanPickedFish} r @returns {number | null} */
  function nearestOfFamily(s, r) {
    if (r.family === null || !s || !s.n || !ports.has("oc_inspect")) return null;
    var n = s.n, ids = Array.prototype.slice.call(s.ids, 0, n), xs = [], ys = [], ds = [], i;
    for (i = 0; i < n; i++) { xs.push(s.segs[12 * i]); ys.push(s.segs[12 * i + 1]); ds.push(s.depth[i]); }
    /** @type {number | null} */
    var best = null, bd = Infinity;
    for (i = 0; i < n; i++) {
      if (!ports.M._oc_inspect(i)) continue;
      var info = ports.HO.f64(ports.M, ports.M._oc_inspect_info(), ports.M._oc_inspect_len());   /* a fresh view: oc_inspect allocates */
      if (Math.round(info[7]) !== r.family) continue;
      var dx = xs[i] - r.x, dy = ys[i] - r.y, dz = ds[i] - r.d;
      if (!ports.WALLS) {
        if (dx > ports.W / 2) dx -= ports.W; else if (dx < -ports.W / 2) dx += ports.W;
        if (dy > ports.H / 2) dy -= ports.H; else if (dy < -ports.H / 2) dy += ports.H;
      }
      var d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < bd || (d2 === bd && ids[i] < /** @type {number} */ (best))) { bd = d2; best = ids[i]; }
    }
    return best;
  }
  function toggleExpanded() {
    cardExpanded = !cardExpanded;
    cardEl.classList.toggle("expanded", cardExpanded);
    ports.el("iexpand").setAttribute("aria-expanded", cardExpanded ? "true" : "false");
    ports.el("iexpand").title = cardExpanded ? "Hide its brain" : "Show its brain";
    cardCache.sense = null;
  }

  return { initSelection: initSelection, initBrainClock: initBrainClock, initCard: initCard, initSwatch: initSwatch, initBody: initBody, registerNetwork: registerNetwork,
    get selectedId() { return selectedId; }, get everSelected() { return everSelected; },
    get wantFollow() { return wantFollow; }, set wantFollow(v) { wantFollow = v; },
    get turboReturn() { return turboReturn; }, set turboReturn(v) { turboReturn = v; },
    get cardEl() { return cardEl; }, get sensorNames() { return sensorNames; }, get actionNames() { return actionNames; },
    resetSelection: function () { selectedId = null; wantFollow = false; },
    resetBrainClock: function (tick, on) { brainClock.reset(tick, on); },
    captureBrainClock: function (on, tick) { brainClock.capture(on, tick); },
    pickedNow: pickedNow, indexOfId: indexOfId, randomFish: randomFish, select: select, follow: follow, unfollow: unfollow,
    inspect: inspect, brainShape: brainShape, updateCard: updateCard, nearestOfFamily: nearestOfFamily,
    returnPoint: returnPoint, restoreAfterTurbo: restoreAfterTurbo, toggleExpanded: toggleExpanded };
  }
  window.EvoOceanInspector = { create: create };
})();
