"use strict";
/* evo_boids 3-D Ocean: the dashboards (📊), charts of the running world,
 * recorded on this device only. Classic's are web/dashboard.js; these share
 * its chart kit (web/charts.js), its look (the #dash styles) and its tabs and
 * buttons, over the Ocean's own recorder:
 *
 * A sample ("row") is {st, su, fam}: oc_stats (pop, frame, cumulative
 * births / deaths / reseeds, depth mean and sd, the eight depth bins),
 * oc_summary (food, predators, causes of death, means, family lines) and
 * oc_families (the biggest lines: id, fish). The page takes one whenever the
 * frame crosses a multiple of every() (web/ocean.js), the Turbo worker on each
 * multiple (web/ocean_worker.js); both arrive through push() / ingest().
 * History is bounded: when full, every other row goes and the interval
 * doubles (setRecEvery tells the page, which tells a running worker).
 * The Brains tab reads host.wiring() when its copy is 2 s old, only while it
 * shows: the page's own world's, or during Turbo the worker's (the page asks
 * the worker; null until it answers, and the panel keeps what it has).
 *
 * Page hooks: attach(host), push(row), ingest(rows), reset(), origin(text)
 * (a history that starts mid-run: a saved world opened), every(), open() /
 * close() / isOpen(). Charts redraw at most twice a second, only while
 * open. */
(function () {
  var C = window.EvoCharts;
  if (!C) return;
  var T = C.T, S = T.series, DT = 0.016, MAX_ROWS = 1200, FAM_K = 8;
  var host = null, rows = [], every = 60, version = 0;
  var isOpen = false, tab = "pop", timer = 0, lastKey = "", cards = {}, view = {};
  var wireCache = null, WIRE_EVERY_MS = 2000;

  function el(id) { return document.getElementById(id); }
  var dashEl = el("dash"), btn = el("dashbtn");
  if (!dashEl || !btn) return;

  /* ---- data in ---- */
  function frameOf(r) { return r.st[1]; }
  function push(r) {
    if (!r || !r.st) return;
    if (rows.length && frameOf(r) <= frameOf(rows[rows.length - 1])) return;   /* a repeat, or out of order */
    rows.push(r);
    if (rows.length > MAX_ROWS) {
      rows = rows.filter(function (_, i) { return i % 2 === 0 || i === rows.length - 1; });
      every *= 2;
      if (host && host.setRecEvery) host.setRecEvery(every);
    }
    version++;
  }
  function ingest(list) { (list || []).forEach(push); }
  function reset() {
    rows = []; every = 60; version++; wireCache = null; lastKey = ""; origin = "";
    if (host && host.setRecEvery) host.setRecEvery(every);
  }
  /* where this history starts, when not at a world's start: a saved world
   * opened (its file carries no charts, so its history starts at the frame
   * it opened at), until the next reset */
  var origin = "";
  function setOrigin(text) { origin = String(text || ""); version++; lastKey = ""; }
  /* the history as it is, and that history back (a saved world that failed
   * to open puts the run back: its charts too; web/ocean.js runNow / pageBack) */
  function save() { return { rows: rows.slice(), every: every, origin: origin }; }
  function restore(s) {
    if (!s) return;
    rows = s.rows.slice(); every = s.every; origin = s.origin; version++; wireCache = null; lastKey = "";
    if (host && host.setRecEvery) host.setRecEvery(every);
  }
  /* the run went back to an earlier frame (a Turbo run that was lost): the
   * samples after it, and the wiring the worker had, are of a future that
   * did not happen */
  function rewind(frame) {
    var n = rows.length;
    rows = rows.filter(function (r) { return frameOf(r) <= frame; });
    if (rows.length !== n) version++;
    wireCache = null; lastKey = "";
  }

  /* ---- columns ---- */
  function times() { return rows.map(function (r) { return r.st[1] * DT; }); }
  function st(k) { return rows.map(function (r) { return r.st[k]; }); }
  function su(k) { return rows.map(function (r) { return r.su[k]; }); }
  /* a per-second rate of a cumulative counter, averaged over ~5 simulated s */
  function rate(get) {
    var n = rows.length, raw = new Array(n), out = new Array(n);
    for (var i = 0; i < n; i++) {
      if (!i) { raw[i] = NaN; continue; }
      var df = (rows[i].st[1] - rows[i - 1].st[1]) * DT, dv = get(rows[i]) - get(rows[i - 1]);
      raw[i] = df > 0 && dv >= 0 ? dv / df : NaN;
    }
    var k = Math.max(1, Math.round(5 / (every * DT)));
    for (i = 0; i < n; i++) {
      var sum = 0, c = 0;
      for (var j = Math.max(1, i - k + 1); j <= i; j++) if (Number.isFinite(raw[j])) { sum += raw[j]; c++; }
      out[i] = c ? sum / c : NaN;
    }
    return out;
  }
  function line(name, y, color) { return { name: name, y: y, color: color }; }
  function D() { return host && host.depth ? host.depth() : 240; }
  function any(fn) { for (var i = 0; i < rows.length; i++) if (fn(rows[i])) return true; return false; }
  function flags() {
    return {
      pred: any(function (r) { return r.su[1] > 0; }),
      body: any(function (r) { return Math.abs(r.su[16] - 1) > 1e-6 || Math.abs(r.su[17] - 1) > 1e-6; }),
      predEnergy: any(function (r) { return r.su[1] > 0 && r.su[20] !== 0; })
    };
  }
  /* depth bin i (0 = the surface eighth) as a colour: light near the top, deep blue below */
  function binColor(i) { return C.seq(0.92 - 0.78 * i / 7); }
  var famColor = new Map();
  function lineColor(id) {
    var c = famColor.get(id);
    if (c === undefined) {
      c = host && host.familyColor ? "#" + (0x1000000 | host.familyColor(id)).toString(16).slice(1) : T.other;
      famColor.set(id, c);
    }
    return c;
  }
  /* Muller layers: each line ever among the biggest, its share per sample,
   * stacked in order of first appearance; everyone else on top */
  function mullerData() {
    var order = [], seen = new Map();
    rows.forEach(function (r) {
      for (var k = 0; k + 1 < r.fam.length; k += 2) if (!seen.has(r.fam[k])) { seen.set(r.fam[k], order.length); order.push(r.fam[k]); }
    });
    if (order.length > 24) order = order.slice(order.length - 24);   /* the most recent lines to rise */
    var idx = new Map(order.map(function (id, k) { return [id, k]; }));
    var n = rows.length, ys = order.map(function () { return new Array(n).fill(0); }), other = new Array(n);
    rows.forEach(function (r, i) {
      var pop = r.st[0] || 1, sum = 0;
      for (var k = 0; k + 1 < r.fam.length; k += 2) {
        var j = idx.get(r.fam[k]);
        if (j !== undefined) { ys[j][i] = r.fam[k + 1] / pop; sum += ys[j][i]; }
      }
      other[i] = Math.max(0, 1 - sum);
    });
    var layers = order.map(function (id, k) { return { name: "line #" + id, y: ys[k], color: lineColor(id) }; });
    layers.push({ name: "other lines", y: other, color: T.other });
    return { t: view.t, layers: layers, empty: "family lines appear after a few seconds" };
  }
  function band(mean, sd, color, name, fmt) {
    return { t: view.t, zero: false, valFmt: fmt, series: [line(name, mean, color)],
             bands: [{ lo: mean.map(function (m, i) { return m - sd[i]; }), hi: mean.map(function (m, i) { return m + sd[i]; }),
                       color: color, alpha: 0.2, label: "± one sd" }] };
  }
  function wiring() {
    if (!host || !host.wiring) return wireCache;
    if (!wireCache || performance.now() - wireCache.at >= WIRE_EVERY_MS) {
      var w = host.wiring();
      if (w) wireCache = w;
    }
    return wireCache;
  }
  function pretty(n) { return String(n).replace(/_/g, " ").toLowerCase(); }
  function fmtDeg(v) { return Number.isFinite(v) ? v.toFixed(1) + "°" : "–"; }
  function fmtD(v) { return Number.isFinite(v) ? Math.round(v) + "" : "–"; }

  var TABS = [
    { id: "pop", name: "Population", cards: [
      { id: "fish", title: "Fish", draw: C.lines,
        cap: "How many fish are alive. Below the reseed floor, random founders are added.",
        data: function () { return { t: view.t, series: [line("fish", st(0), S[0])] }; } },
      { id: "food", title: "Food", draw: C.lines,
        cap: "Food items in the water. Fish eat it faster than it regrows when they boom.",
        data: function () { return { t: view.t, series: [line("food", su(0), S[2])] }; } },
      { id: "flow", title: "Births and deaths per second", draw: C.lines,
        cap: "Averaged over about five simulated seconds. Births above deaths: the population grows.",
        legend: function () { return [{ name: "births", color: S[0] }, { name: "deaths", color: S[1] }, { name: "founders added", color: S[6] }]; },
        data: function () {
          return { t: view.t, series: [line("births", rate(function (r) { return r.st[2]; }), S[0]),
                                       line("deaths", rate(function (r) { return r.st[3]; }), S[1]),
                                       line("founders added", rate(function (r) { return r.st[4]; }), S[6])] };
        } },
      { id: "causes", title: "How fish die", draw: C.stack,
        cap: "Deaths per second by cause, stacked: starved, old age, caught by a predator.",
        legend: function () { return [{ name: "starved", color: S[1], square: true }, { name: "old age", color: S[0], square: true }, { name: "caught", color: S[7], square: true }]; },
        data: function () {
          return { t: view.t, abs: true, layers: [
            { name: "starved", y: rate(function (r) { return r.su[3]; }).map(z), color: S[1] },
            { name: "old age", y: rate(function (r) { return r.su[4]; }).map(z), color: S[0] },
            { name: "caught", y: rate(function (r) { return r.su[2]; }).map(z), color: S[7] }] };
        } },
      { id: "preds", title: "Predators", draw: C.lines, when: function () { return view.f.pred; },
        needs: "Shows up when the world has predators (Settings → Predators).",
        cap: "Hunters alive. With their economy on they breed when well fed and starve when not.",
        data: function () { return { t: view.t, series: [line("predators", su(1), S[7])] }; } },
      /* Classic's two phase portraits (web/dashboard.js), over the same columns */
      { id: "phase", title: "The boom-and-bust loop", draw: C.phase,
        cap: "Fish against food, one point per moment, the bright end now. Going round a loop is the cycle: food piles up, fish boom and eat it down, fish crash, food recovers.",
        data: function () { return { x: st(0), y: su(0), t: view.t, xName: "fish", yName: "food", color: S[2] }; } },
      { id: "phase2", title: "Hunters and fish", draw: C.phase, when: function () { return view.f.pred; },
        needs: "Shows up when the world has predators (Settings → Predators).",
        cap: "Fish against predators, the bright end now. With the predator economy on, a loop is the classic predator–prey cycle: hunters boom after the fish, then starve.",
        data: function () { return { x: st(0), y: su(1), t: view.t, xName: "fish", yName: "predators", color: S[7] }; } }
    ] },
    { id: "depth", name: "Depth", cards: [
      { id: "where", title: "Where the fish swim", wide: true, tall: true, draw: C.stack,
        cap: "The share of fish in each eighth of the depth, the surface on top, the floor at the bottom. A band widening is the population moving there.",
        legend: function () {
          return [0, 1, 2, 3, 4, 5, 6, 7].map(function (i) {
            return { name: Math.round(D() * i / 8) + "–" + Math.round(D() * (i + 1) / 8), color: binColor(i), square: true };
          });
        },
        data: function () {
          var layers = [];
          for (var i = 7; i >= 0; i--) layers.push({ name: "depth " + Math.round(D() * i / 8) + "–" + Math.round(D() * (i + 1) / 8), y: st(7 + i), color: binColor(i) });
          return { t: view.t, layers: layers };
        } },
      { id: "mean", title: "Average depth", draw: C.lines,
        cap: "The fish's mean depth (0 = the surface, higher = deeper), with one standard deviation around it.",
        data: function () { return band(st(5), st(6), S[0], "mean depth", fmtD); } },
      { id: "buoy", title: "Neutral depth", draw: C.lines,
        cap: "Where the fish float without effort (inherited, with a small mutation per birth). It drifting is evolution choosing a depth.",
        data: function () {
          var d = D();
          return band(su(14).map(function (v) { return v * d; }), su(15).map(function (v) { return v * d; }), S[2], "neutral depth", fmtD);
        } },
      { id: "pitch", title: "Climbing and diving", draw: C.lines,
        cap: "How steeply the fish swim up or down on average (0° = level). It rises when depth starts to matter to them.",
        data: function () { return { t: view.t, yFmt: fmtDeg, valFmt: fmtDeg, series: [line("mean pitch", su(21).map(function (v) { return Math.atan(v) * 180 / Math.PI; }), S[4])] }; } }
    ] },
    { id: "families", name: "Family lines", cards: [
      { id: "muller", title: "Family lines over time", wide: true, tall: true, draw: C.stack,
        cap: "Each band is a family line (every fish descended from one starting fish), its share of the population, in the colour its fish have in the tank. Lines that take over are selection at work.",
        data: mullerData },
      { id: "lines", title: "Family lines alive", draw: C.lines,
        cap: "Lines die out one by one until a few remain. Founders added below the reseed floor start new lines.",
        data: function () { return { t: view.t, series: [line("lines alive", su(19), S[0])] }; } },
      { id: "gens", title: "Generations", draw: C.lines,
        cap: "The longest line of descent alive, and the average. They climb as evolution runs.",
        legend: function () { return [{ name: "longest", color: S[1] }, { name: "average", color: S[0] }]; },
        data: function () { return { t: view.t, series: [line("longest", su(13), S[1]), line("average", su(12), S[0])] }; } }
    ] },
    { id: "bodies", name: "Bodies", cards: [
      { id: "energy", title: "Energy", draw: C.lines,
        cap: "The fish's average energy store. Breeding takes it; food brings it back.",
        data: function () { return { t: view.t, series: [line("energy", su(9), S[2])] }; } },
      { id: "age", title: "Age", draw: C.lines,
        cap: "The average age in simulated seconds. Low means a fast turnover of generations.",
        data: function () { return { t: view.t, series: [line("age (s)", su(10), S[0])] }; } },
      { id: "speed", title: "Speed", draw: C.lines,
        cap: "How fast the fish swim on average. A swimming cost pulls it down.",
        data: function () { return { t: view.t, series: [line("speed", su(11), S[3])] }; } },
      { id: "genes", title: "Genome length", draw: C.lines,
        cap: "Genes per fish, on average: the size of its brain's wiring list.",
        data: function () { return { t: view.t, series: [line("genes", su(18), S[6])] }; } },
      { id: "body", title: "Body size and shape", draw: C.lines, when: function () { return view.f.body; },
        needs: "Shows up when bodies evolve (Settings → World → Evolving bodies).",
        cap: "Average body size and elongation (both start at 1).",
        legend: function () { return [{ name: "size", color: S[0] }, { name: "elongation", color: S[1] }]; },
        data: function () { return { t: view.t, zero: false, series: [line("size", su(16), S[0]), line("elongation", su(17), S[1])] }; } },
      { id: "predE", title: "Predator energy", draw: C.lines, when: function () { return view.f.predEnergy; },
        needs: "Shows up when predators eat, breed and starve (Settings → Predators).",
        cap: "The hunters' average energy store.",
        data: function () { return { t: view.t, series: [line("predator energy", su(20), S[7])] }; } }
    ] },
    { id: "brains", name: "Brains", cards: [
      { id: "wires", title: "Which senses drive which actions", wide: true, xtall: true, draw: C.heat,
        cap: "The share of fish whose brain links each sense (rows) to each action (columns), directly or through hidden neurons. The Ocean's fish have depth senses (loc z, own vel z, nearest food dz, avg neighbor dz, boundary dist z) and a depth action (steer z).",
        data: function () {
          var w = wiring();
          if (!w) return null;
          var S_ = w.senses, A = w.actions, nm = w.senseNames.map(pretty), act = w.actionNames.map(pretty), max = 0;
          for (var k = 0; k < S_ * A; k++) max = Math.max(max, w.path[k]);
          max = max || 1;
          return { rows: S_, cols: A, labelW: 150, labelH: 64, max: max,
                   v: function (r, c) { return w.path[r * A + c] / max; },
                   rowLabel: function (r) { return nm[r] || ""; }, colLabel: function (c) { return act[c]; },
                   cellTip: function (r, c) {
                     return "<div class='th'>" + C.esc(nm[r]) + " → " + C.esc(act[c]) + "</div>" +
                       C.tipRow(C.seq(w.path[r * A + c] / max), "any path", Math.round(w.path[r * A + c] * 100) + "% of fish", true) +
                       C.tipRow(C.seq(w.direct[r * A + c] / max), "a direct link", Math.round(w.direct[r * A + c] * 100) + "% of fish", true);
                   } };
        },
        legendScale: true,
        note: function (d) {
          if (!d) return "Waiting for the world…";
          return "From " + (wireCache ? wireCache.n : 0) + " fish" + (wireCache && wireCache.turbo ? " in the Turbo run" : "") +
                 "; refreshes every 2 s.";
        } }
    ] }
  ];
  function z(v) { return Number.isFinite(v) ? v : 0; }

  /* ---- DOM ---- */
  var tabsEl = el("dtabs"), gridEl = el("dgrid"), noteEl = el("dnote");
  TABS.forEach(function (tb) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = tb.name;
    b.setAttribute("role", "tab");
    b.dataset.tab = tb.id;
    /* a pointer's press lets the focus go (Space pauses again); the keyboard's keeps it */
    b.addEventListener("click", function () { showTab(tb.id); if (!this.matches(":focus-visible")) this.blur(); });
    tabsEl.appendChild(b);
  });
  /* the tabs from the keyboard (the page leaves a focused tab its arrows):
   * Left / Right the next one round, Home / End the first and last; the
   * focus goes with the selection, and Tab lands on the selected one */
  tabsEl.addEventListener("keydown", function (e) {
    var ids = TABS.map(function (t) { return t.id; }), i = ids.indexOf(tab), n = ids.length;
    var j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j < 0) return;
    showTab(ids[j]);
    tabsEl.children[j].focus();
    e.preventDefault();
  });
  function showTab(id) {
    tab = id;
    Array.prototype.forEach.call(tabsEl.children, function (b) {
      b.setAttribute("aria-selected", b.dataset.tab === id ? "true" : "false");
      b.tabIndex = b.dataset.tab === id ? 0 : -1;
    });
    C.tip(null);
    gridEl.innerHTML = "";
    cards = {};
    TABS.filter(function (t) { return t.id === id; })[0].cards.forEach(function (cd) {
      var sec = document.createElement("section");
      sec.className = "dcard" + (cd.wide ? " wide" : "");
      sec.innerHTML = "<h3></h3><p class='cap'></p><div class='cbox'></div><div class='legend'></div><p class='cnote'></p>";
      sec.querySelector("h3").textContent = cd.title;
      sec.querySelector(".cap").textContent = cd.cap;
      var box = sec.querySelector(".cbox");
      box.className = "cbox" + (cd.tall ? " tall" : "") + (cd.xtall ? " xtall" : "");
      gridEl.appendChild(sec);
      cards[cd.id] = { def: cd, el: sec, box: box, legend: sec.querySelector(".legend"), note: sec.querySelector(".cnote"),
                       chart: new C.Chart(box, cd.draw) };
    });
    gridEl.scrollTop = 0;
    update(true);
  }
  function rampLegend(e, from, to) {
    var key = "ramp" + from + "|" + to;
    if (e.__html === key) return;
    e.__html = key;
    e.innerHTML = "<span class='li'></span><span class='scale'></span><span class='li'></span>";
    e.children[0].textContent = from; e.children[2].textContent = to;
    e.querySelector(".scale").style.background = "linear-gradient(90deg," + [0, 0.17, 0.33, 0.5, 0.67, 0.83, 1].map(C.seq).join(",") + ")";
  }
  function update(force) {
    if (!isOpen) return;
    var due = tab === "brains" && (!wireCache || performance.now() - wireCache.at >= WIRE_EVERY_MS);
    var key = tab + "|" + version + "|" + gridEl.clientWidth;
    if (!force && key === lastKey && !due) return;
    lastKey = key;
    view = { t: times(), f: flags() };
    Object.keys(cards).forEach(function (id) {
      var c = cards[id], cd = c.def, on = !cd.when || cd.when();
      c.el.classList.toggle("off", !on);
      if (!on) { c.note.textContent = cd.needs || ""; c.legend.innerHTML = ""; c.legend.__html = ""; return; }
      var data = cd.data();
      c.chart.draw(data || null);
      if (cd.legend) C.legend(c.legend, cd.legend());
      else if (cd.legendScale && data) rampLegend(c.legend, "0%", Math.round(data.max * 100) + "% of fish");
      c.note.textContent = cd.note ? cd.note(data) : "";
    });
    var span = rows.length ? (frameOf(rows[rows.length - 1]) - frameOf(rows[0])) * DT : 0;
    noteEl.textContent = noteText(span);
  }
  function noteText(span) {
    if (origin) return rows.length
      ? "A fresh history, recorded on this device since " + origin + " (a saved world carries no charts): " + C.fmtTime(span) +
        " of simulated time, " + rows.length + " samples (one every " + +(every * DT).toFixed(2) + " s). Nothing is uploaded; Restart clears it."
      : "A fresh history: a saved world carries no charts, so recording starts at " + origin + ". Nothing is uploaded; Restart clears it.";
    return rows.length
      ? "Recorded on this device since the last restart: " + C.fmtTime(span) + " of simulated time, " + rows.length +
        " samples (one every " + +(every * DT).toFixed(2) + " s). Nothing is uploaded; Restart clears it."
      : "Recording starts with the world. Nothing is uploaded; Restart clears it.";
  }

  function csv() {
    var head = ["frame", "time_s", "fish", "births", "deaths", "founders_added", "depth_mean", "depth_sd"];
    for (var i = 0; i < 8; i++) head.push("depth_bin" + i);
    head = head.concat(["food", "predators", "deaths_caught", "deaths_starved", "deaths_old_age", "predator_births",
                        "predator_deaths_starved", "predator_deaths_old_age", "predators_added", "energy_mean", "age_mean",
                        "speed_mean", "generation_mean", "generation_max", "neutral_depth_frac_mean", "neutral_depth_frac_sd",
                        "body_size_mean", "body_elong_mean", "genes_mean", "family_lines", "predator_energy_mean", "abs_vz_mean"]);
    var out = [head.join(",")];
    rows.forEach(function (r) {
      var v = [r.st[1], (r.st[1] * DT).toFixed(3)].concat(r.st.slice(0, 1), r.st.slice(2, 15), r.su.slice(0, 22));
      out.push(v.map(function (x) { return typeof x === "number" && !Number.isInteger(x) ? +x.toFixed(6) : x; }).join(","));
    });
    return out.join("\n") + "\n";
  }
  el("dcsv").addEventListener("click", function () {
    var url = URL.createObjectURL(new Blob([csv()], { type: "text/csv" }));
    var a = document.createElement("a");
    a.href = url; a.download = "evo_ocean_dashboard_f" + (rows.length ? frameOf(rows[rows.length - 1]) : 0) + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    this.blur();
  });

  function open() {
    if (isOpen) return;
    isOpen = true;
    if (host && host.setDrawer) host.setDrawer(false);
    if (host && host.onOpen) host.onOpen();   /* the page's: no popover under the charts, the coach mark gone */
    dashEl.hidden = false;
    document.body.classList.add("dash-open");
    btn.setAttribute("aria-expanded", "true");
    showTab(tab);
    timer = setInterval(update, 500);
  }
  function close() {
    if (!isOpen) return;
    isOpen = false;
    dashEl.hidden = true;
    document.body.classList.remove("dash-open");
    btn.setAttribute("aria-expanded", "false");
    clearInterval(timer);
    C.tip(null);
    gridEl.innerHTML = "";
    cards = {};
  }
  btn.addEventListener("click", function () { if (isOpen) close(); else open(); this.blur(); });
  el("dclose").addEventListener("click", close);
  /* One owner for each Esc, the top layer: the tour (web/guide.js), then the
   * charts, then the page's own. Seen in the capture phase, before any
   * handler has closed anything: with the tour open, its Esc is the tour's */
  var escTour = false;
  window.addEventListener("keydown", function (e) { if (e.key === "Escape") escTour = !!document.getElementById("guide"); }, true);
  window.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen && !escTour) close(); });
  var resizeTimer = 0;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(function () { update(true); }, 150); });

  window.EvoOceanDash = {
    attach: function (h) { host = h; if (h.setRecEvery) h.setRecEvery(every); },
    push: push, ingest: ingest, reset: reset, rewind: rewind, origin: setOrigin, save: save, restore: restore,
    /* the charts' note as it reads now (the tests; the page shows it when open) */
    note: function () { var span = rows.length ? (frameOf(rows[rows.length - 1]) - frameOf(rows[0])) * DT : 0; return noteText(span); },
    every: function () { return every; }, famK: FAM_K,
    open: open, close: close, isOpen: function () { return isOpen; },
    showTab: function (id) { if (isOpen) showTab(id); else { tab = id; open(); } },
    _rows: function () { return rows; }
  };
})();
