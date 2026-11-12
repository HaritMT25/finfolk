"use strict";
/* evo_boids dashboards (📊): charts of the running world, recorded on this
 * device only. The wasm recorder (wasm/evo_wasm.cpp, "Dashboard recorder")
 * samples the world about once per simulated second and reports births and
 * departures; web/dash_data.js keeps them (bounded); web/charts.js draws.
 *
 * Page hooks (renderer.js): EvoDash.attach(host) once the module is loaded,
 * pump() after each step, reset() on a restart or a checkpoint loaded from a
 * file, ingest() for what the Turbo worker recorded, every() for the worker's
 * sampling interval. Charts redraw at most twice a second, only while open. */
(function () {
  var D = window.EvoDashData, C = window.EvoCharts, UI = window.EvoUI;
  if (!D || !C || !UI) return;
  var COL = D.COL, DT = D.DT, T = C.T, S = T.series;
  /* one colour per quantity, the same in every chart it appears in; the
   * causes of death stack as orange, blue, red, violet, an order validated
   * for colour-blind separation as neighbours */
  var K = { fish: S[0], food: S[2], pred: S[7], births: S[0], deaths: S[1],
            starved: S[1], aged: S[0], kills: S[7], culled: S[6], mean: S[0], max: S[1] };

  var hist = new D.History(60), fam = new D.Family(), lines = new D.Lines(8, 0.03);
  var host = null, M = null, sensorNames = null;
  var isOpen = false, tab = "pop", timer = 0, lastKey = "";
  var cards = {};           /* id -> {el, box, chart, legend, ...} for the current tab */
  var simCache = null, wireCache = null;

  function el(id) { return document.getElementById(id); }
  var dashEl = el("dash"), btn = el("dashbtn");
  if (!dashEl || !btn) return;

  /* ---- data in ---- */
  function heap() { return host.heap(); }
  function ingest(s, b, c) {
    if (hist.push(s) && host) host.setRecEvery(hist.every());
    fam.births(b);
    fam.changes(c);
  }
  function pump() {
    if (!M || !M._evo_rec_take) return;
    M._evo_rec_take();
    var ns = M._evo_rec_count(0), nb = M._evo_rec_count(1), nc = M._evo_rec_count(2);
    if (!ns && !nb && !nc) return;
    var buf = heap();
    ingest(new Float64Array(buf, M._evo_rec_data(0), ns), new Float64Array(buf, M._evo_rec_data(1), nb),
           new Float64Array(buf, M._evo_rec_data(2), nc));
  }
  function reset() {
    hist.clear(); fam.clear(); lines.clear();
    simCache = wireCache = null;
    if (host) host.setRecEvery(hist.every());
    lastKey = "";
  }

  /* ---- the charts ---- */
  var view = {};   /* per-update cache: t, flags */
  function col(c) { return hist.col(c); }
  function anyRow(fn) { for (var i = 0; i < hist.n; i++) if (fn(i)) return true; return false; }
  function flags() {
    var last = hist.n - 1;
    return {
      pred: anyRow(function (i) { return hist.get(i, COL.pred) > 0; }),
      current: last >= 0 && hist.get(last, COL.current) > 0,
      body: anyRow(function (i) { return hist.get(i, COL.q_body) !== 1 || hist.get(i, COL.q_body + 4) !== 1; }),
      culled: last >= 0 && hist.get(last, COL.culled) > 0,
      predFloor: last >= 0 && hist.get(last, COL.predReseeds) > 0,
      predTraits: anyRow(function (i) {
        return hist.get(i, COL.pred) > 0 && (hist.get(i, COL.predSpeed) !== 1 || hist.get(i, COL.predBudding) !== 1);
      })
    };
  }
  function line(name, y, color) { return { name: name, y: y, color: color }; }
  /* a per-second rate, averaged over about 5 simulated seconds (one sample's
   * births and deaths are a handful, so the raw rate is mostly noise) */
  function rate(c) {
    var r = hist.rate(c), k = Math.max(1, Math.round(5 / (hist.every() * DT))), out = new Array(r.length), sum = 0;
    for (var i = 0; i < r.length; i++) {
      sum += r[i];
      if (i >= k) sum -= r[i - k];
      out[i] = sum / Math.min(i + 1, k);
    }
    return out;
  }
  function fan(qc, color, fmt) {
    var q = [0, 1, 2, 3, 4].map(function (k) { return col(qc + k); });
    return { t: view.t, zero: false, valFmt: fmt,
             series: [line("median", q[2], color)],
             bands: [{ lo: q[0], hi: q[4], color: color, alpha: 0.13, label: "middle 80%" },
                     { lo: q[1], hi: q[3], color: color, alpha: 0.22, label: "middle half" }] };
  }
  var FAN_LEGEND = function (color) {
    return [{ name: "median", color: color }, { name: "middle half", color: C.alpha(color, 0.45), square: true },
            { name: "middle 80%", color: C.alpha(color, 0.22), square: true }];
  };
  function pct(v) { return Math.round(v * 100) + "%"; }
  function lineName(id) { return "line #" + id; }
  /* A family line's colour is the one its fish are drawn in by family
   * (evo_family_color: a hash of the line's id), so a band here and its fish
   * in the ocean match, and a line keeps its colour across restarts and
   * checkpoint loads. Before 2026-10-23 lines took the palette's slots first-come,
   * so whichever family was biggest when a recording began came out blue. */
  var famColor = new Map();
  function lineColor(lin) {
    var c = famColor.get(lin);
    if (c === undefined) {
      if (!M || !M._evo_family_color) {   /* an older module: the slot colour */
        var s = lines.slotOf.get(lin);
        return s === undefined ? T.other : S[s];
      }
      c = "#" + (0x1000000 | M._evo_family_color(lin)).toString(16).slice(1);
      famColor.set(lin, c);
    }
    return c;
  }

  /* Muller layers: each named family line's share per sample, stacked in the
   * order the lines were named (stable as the chart grows), the rest on top */
  function mullerData() {
    var ids = Array.from(lines.slotOf.keys()).sort(function (a, b) { return lines.slotOf.get(a) - lines.slotOf.get(b); });
    var n = hist.n, ys = ids.map(function () { return new Array(n).fill(0); }), other = new Array(n);
    var index = new Map(ids.map(function (id, k) { return [id, k]; }));
    for (var i = 0; i < n; i++) {
      var pop = hist.get(i, COL.pop) || 1, top = hist.top(i), sum = 0;
      for (var t = 0; t < top.length; t++) {
        var k = index.get(top[t][0]);
        if (k !== undefined) { ys[k][i] = top[t][1] / pop; sum += ys[k][i]; }
      }
      other[i] = Math.max(0, 1 - sum);
    }
    var layers = ids.map(function (id, k) { return { name: lineName(id), y: ys[k], color: lineColor(id) }; });
    layers.push({ name: "other lines", y: other, color: T.other });
    return { t: view.t, layers: layers, empty: "family lines appear after a few seconds" };
  }

  /* the family tree, drawn: each fish's line from where it branched to now
   * (or its death), children hanging below, joined by a connector */
  function drawTree(g, w, h, d, hover) {
    var rows = d.lay.rows, n = rows.length;
    if (!n) return C.empty(g, w, h, "the tree grows as fish are born");
    /* the whole recording, so young branches show as young */
    var x0 = hist.n ? hist.frame(0) : 0;
    rows.forEach(function (r) { if (r.x0 < x0) x0 = r.x0; });
    var f = C.frame(g, w, h, x0 * DT, d.lay.nowFrame * DT, 0, 1, { yTicks: [], padL: 14 });
    var rh = (f.B - f.T) / n, y = function (i) { return f.T + (i + 0.5) * rh; };
    var lw = rh >= 3 ? 1.5 : 1;
    g.lineWidth = lw;
    for (var i = 0; i < n; i++) {
      var r = rows[i], c = lineColor(r.node.lin);
      var xa = f.sx(r.x0 * DT), xb = f.sx(r.x1 * DT);
      g.strokeStyle = c;
      g.beginPath();
      if (r.parentRow >= 0) { g.moveTo(xa, y(r.parentRow)); g.lineTo(xa, y(i)); } else g.moveTo(xa, y(i));
      g.lineTo(Math.max(xb, xa + 1), y(i));
      g.stroke();
    }
    if (!hover || hover.y < f.T || hover.y > f.B) return null;
    var k = Math.max(0, Math.min(n - 1, Math.floor((hover.y - f.T) / rh)));
    var row = rows[k], nd = row.node;
    g.strokeStyle = T.ink; g.lineWidth = 2;
    g.beginPath(); g.moveTo(f.sx(row.x0 * DT), y(k)); g.lineTo(f.sx(row.x1 * DT), y(k)); g.stroke();
    var kids = rows.filter(function (r) { return r.parentRow === k; }).length;
    return "<div class='th'>fish #" + nd.id + "</div>" +
      C.tipRow(lineColor(nd.lin), "family line", "#" + nd.lin) +
      (Number.isFinite(nd.born) ? C.tipRow(T.axis, "born", C.fmtTime(nd.born * DT)) : "") +
      C.tipRow(T.axis, nd.alive ? "alive" : "died", nd.alive ? "now" : C.fmtTime(nd.died * DT)) +
      (kids ? C.tipRow(T.axis, "branches shown", String(kids)) : "");
  }

  /* similarity: UPGMA tree on the left, the ordered distance matrix beside it */
  function drawSim(g, w, h, d, hover) {
    var m = d.m;
    if (m < 3) return C.empty(g, w, h, "needs at least 3 fish");
    var side = Math.max(60, Math.min(w - 96, h - 8)), dw = Math.min(90, w - side - 8);
    var L = dw + 4, Tp = 4, cell = side / m;
    var pos = new Float64Array(2 * m - 1), hgt = new Float64Array(2 * m - 1), maxH = 0;
    d.order.forEach(function (leaf, i) { pos[leaf] = Tp + (i + 0.5) * cell; });
    d.merges.forEach(function (mg, k) {
      pos[m + k] = (pos[mg.a] + pos[mg.b]) / 2; hgt[m + k] = mg.h; if (mg.h > maxH) maxH = mg.h;
    });
    var hx = function (v) { return L - 4 - (maxH ? v / maxH : 0) * (dw - 8); };
    g.strokeStyle = T.ink2; g.lineWidth = 1;
    g.beginPath();
    d.merges.forEach(function (mg, k) {
      var c = m + k, xc = hx(hgt[c]);
      [mg.a, mg.b].forEach(function (ch) { g.moveTo(hx(hgt[ch]), pos[ch]); g.lineTo(xc, pos[ch]); });
      g.moveTo(xc, pos[mg.a]); g.lineTo(xc, pos[mg.b]);
    });
    g.stroke();
    var span = Math.max(1e-6, d.max - d.lo), shade = function (v) { return (v - d.lo) / span; };
    if (!d._img) d._img = C.matrixImage(m, m, function (i, j) { return shade(d.dist[d.order[i] * m + d.order[j]]); });
    C.drawMatrix(g, d._img, L, Tp, side, side);
    if (!hover) return null;
    var ci = Math.floor((hover.y - Tp) / cell), cj = Math.floor((hover.x - L) / cell);
    if (ci < 0 || cj < 0 || ci >= m || cj >= m) return null;
    g.strokeStyle = T.ink; g.lineWidth = 1.5;
    g.strokeRect(L + cj * cell, Tp + ci * cell, Math.max(2, cell), Math.max(2, cell));
    var a = d.order[ci], b = d.order[cj];
    return "<div class='th'>fish #" + d.ids[a] + " and #" + d.ids[b] + "</div>" +
      C.tipRow(C.seq(shade(d.dist[a * m + b])), "wiring distance", d.dist[a * m + b].toFixed(1), true) +
      C.tipRow(lineColor(d.lins[a]), "family lines", "#" + d.lins[a] + (d.lins[a] === d.lins[b] ? " (same)" : " / #" + d.lins[b]));
  }

  /* senses in use over time: one row per sense, history across */
  function drawSenses(g, w, h, d, hover) {
    var n = hist.n;
    if (n < 2) return C.empty(g, w, h);
    /* one spec per update, so hover redraws reuse its image */
    var max = d.max;
    if (!d.spec) d.spec = {
      rows: D.NSENS, cols: n, labelW: 150, labelH: 0, bottomH: 18,
      v: function (r, c) { return hist.get(c, COL.sensors + r) / max; },
      rowLabel: function (r) { return d.names[r]; },
      cellTip: function (r, c) {
        return "<div class='th'>" + C.fmtTime(hist.frame(c) * DT) + "</div>" +
          C.tipRow(C.seq(hist.get(c, COL.sensors + r) / max), d.names[r], pct(hist.get(c, COL.sensors + r)) + " of fish", true);
      }
    };
    var html = C.heat(g, w, h, d.spec, hover);
    g.fillStyle = T.muted; g.textBaseline = "top";
    g.textAlign = "left"; g.fillText(C.fmtTime(hist.frame(0) * DT), 150, h - 14);
    g.textAlign = "right"; g.fillText(C.fmtTime(hist.frame(n - 1) * DT) + " (now)", w - 6, h - 14);
    return html;
  }

  function prettySense(s) { return s.toLowerCase().replace(/_/g, " "); }
  function names() {
    if (!sensorNames && M && M._evo_sensor_names) sensorNames = M.UTF8ToString(M._evo_sensor_names()).split(",");
    return sensorNames || [];
  }

  /* on-demand analyses, refreshed while their tab is open */
  var SIM_N = 150, SIM_EVERY_MS = 10000, WIRE_EVERY_MS = 3000;
  function similarity(force) {
    if (!M || !M._evo_similarity) return null;
    if (simCache && !force && performance.now() - simCache.at < SIM_EVERY_MS) return simCache;
    var m = M._evo_similarity(SIM_N), buf = heap();
    var info = new Float64Array(buf, M._evo_similarity_info(), m * 6).slice();
    var dist = new Float32Array(buf, M._evo_similarity_dist(), m * m).slice();
    /* the colours span the distances actually present (diagonal aside), so
     * relatives stand out even when everyone is fairly far apart */
    var max = 0, lo = Infinity;
    for (var i = 0; i < m; i++) for (var j0 = 0; j0 < m; j0++) {
      if (i === j0) continue;
      var dv = dist[i * m + j0];
      if (dv > max) max = dv;
      if (dv < lo) lo = dv;
    }
    if (!Number.isFinite(lo)) lo = 0;
    var u = D.upgma(dist, m), xy = D.mds2(dist, m);
    var ids = [], lins = [], rgb = [];
    for (i = 0; i < m; i++) {
      ids.push(info[6 * i]); lins.push(info[6 * i + 1]);
      rgb.push("rgb(" + info[6 * i + 3] + "," + info[6 * i + 4] + "," + info[6 * i + 5] + ")");
    }
    var pairs = [];
    for (i = 0; i < m; i++) for (var j = i + 1; j < m; j++) pairs.push(dist[i * m + j]);
    simCache = { at: performance.now(), frame: hist.n ? hist.frame(hist.n - 1) : 0, m: m, dist: dist,
                 max: max || 1, lo: Math.min(lo, max), order: u.order, merges: u.merges, xy: xy, ids: ids, lins: lins, rgb: rgb,
                 hist: D.histogram(pairs, 30, 0, Math.max(1, max)) };
    return simCache;
  }
  function wiring(force) {
    if (!M || !M._evo_wiring) return null;
    if (wireCache && !force && performance.now() - wireCache.at < WIRE_EVERY_MS) return wireCache;
    var pop = M._evo_wiring();
    var data = new Float32Array(heap(), M._evo_wiring_data(), 2 * 41 * 12).slice();
    wireCache = { at: performance.now(), pop: pop, path: data.subarray(0, 492), direct: data.subarray(492) };
    return wireCache;
  }

  /* Tabs and cards. A card: title, one sentence on what to look for, and
   * data() -> what its chart draws. when() false shows `needs` instead. */
  var TABS = [
    { id: "pop", name: "Population", cards: [
      { id: "fishfood", title: "Fish and food", draw: C.lines,
        cap: "Fish multiply while food is plentiful, eat it down, then crash: boom and bust. Food is what lies uneaten.",
        data: function () { return { t: view.t, series: [line("fish", col(COL.pop), K.fish), line("food", col(COL.food), K.food)] }; },
        legend: function () { return [{ name: "fish", color: K.fish }, { name: "food", color: K.food }]; } },
      { id: "preds", title: "Predators", draw: C.lines, when: function () { return view.f.pred; },
        needs: "Shows up when the world has predators (Settings → Predators).",
        cap: "With the predator economy on, hunters breed when well fed and starve when fish are scarce, so their peaks trail the fish's. With a predator floor, the second line counts the hunters it has put back.",
        data: function () {
          var s = [line("predators", col(COL.pred), K.pred)];
          if (view.f.predFloor) s.push(line("put back by the floor (total)", col(COL.predReseeds), S[6]));
          return { t: view.t, series: s };
        },
        legend: function () {
          return view.f.predFloor ? [{ name: "predators", color: K.pred }, { name: "put back by the floor (total)", color: S[6] }] : [];
        } },
      { id: "flux", title: "Births and deaths per second (5 s average)", draw: C.lines,
        cap: "While births outrun deaths the population grows; the two lines crossing is a boom ending.",
        data: function () {
          return { t: view.t, series: [line("births", rate(COL.births), K.births), line("deaths", rate(COL.deaths), K.deaths)] };
        },
        legend: function () { return [{ name: "births", color: K.births }, { name: "deaths", color: K.deaths }]; } },
      { id: "causes", title: "What fish die of (per second, 5 s average)", draw: C.stack,
        cap: "Starvation surges mark the crashes; old age dominates in good times; predation needs hunters.",
        data: function () {
          var ly = [{ name: "starvation", y: rate(COL.starved), color: K.starved },
                    { name: "old age", y: rate(COL.aged), color: K.aged }];
          if (view.f.pred) ly.push({ name: "caught by predators", y: rate(COL.kills), color: K.kills });
          if (view.f.culled) ly.push({ name: "removed to hold 60 fps", y: rate(COL.culled), color: K.culled });
          return { t: view.t, layers: ly, abs: true };
        },
        legend: function () {
          var it = [{ name: "starvation", color: K.starved, square: true }, { name: "old age", color: K.aged, square: true }];
          if (view.f.pred) it.push({ name: "caught by predators", color: K.kills, square: true });
          if (view.f.culled) it.push({ name: "removed to hold 60 fps", color: K.culled, square: true });
          return it;
        } },
      { id: "phase", title: "The boom-and-bust loop", draw: C.phase,
        cap: "Fish against food, one point per moment, the bright end now. Going round a loop is the cycle: food piles up, fish boom and eat it down, fish crash, food recovers.",
        data: function () { return { x: col(COL.pop), y: col(COL.food), t: view.t, xName: "fish", yName: "food", color: K.food }; } },
      { id: "phase2", title: "Hunters and fish", draw: C.phase, when: function () { return view.f.pred; },
        needs: "Shows up when the world has predators (Settings → Predators).",
        cap: "Fish against predators, the bright end now. With the predator economy on, a loop is the classic predator–prey cycle: hunters boom after the fish, then starve.",
        data: function () { return { x: col(COL.pop), y: col(COL.pred), t: view.t, xName: "fish", yName: "predators", color: K.pred }; } }
    ] },
    { id: "evo", name: "Evolution", cards: [
      { id: "gens", title: "Generations", draw: C.lines,
        cap: "How many generations separate today's fish from the first ones. The average climbs as long as fish keep breeding.",
        data: function () { return { t: view.t, series: [line("average", col(COL.genMean), K.mean), line("longest line", col(COL.genMax), K.max)] }; },
        legend: function () { return [{ name: "average", color: K.mean }, { name: "longest line", color: K.max }]; } },
      { id: "div", title: "Genetic diversity", draw: C.lines,
        cap: "How far a typical fish's brain wiring is from the population's average. It falls when one design takes over and rises when groups drift apart.",
        data: function () { return { t: view.t, series: [line("diversity", col(COL.diversity), S[0])] }; } },
      { id: "glen", title: "Genome length (genes per fish)", draw: C.lines,
        cap: "Each gene is one brain connection. A rising median means bigger brains are paying for themselves.",
        data: function () { return fan(COL.q_glen, S[2]); }, legend: function () { return FAN_LEGEND(S[2]); } },
      { id: "speed", title: "Swim speed", draw: C.lines,
        cap: "How fast fish swim. Hunters push it up; a thrust cost (moveCost) pulls it down.",
        data: function () { return fan(COL.q_speed, S[0]); }, legend: function () { return FAN_LEGEND(S[0]); } },
      { id: "body", title: "Body size", draw: C.lines, when: function () { return view.f.body; },
        needs: "Shows up when the body model is on (Settings → World → Evolving bodies).",
        cap: "Inherited body size, 1 = the founders'. Bigger is slower and costs more energy, so watch which way it drifts.",
        data: function () { return fan(COL.q_body, S[3], function (v) { return v.toFixed(2); }); },
        legend: function () { return FAN_LEGEND(S[3]); } },
      { id: "predtraits", title: "Hunters' inherited traits (average)", draw: C.lines, when: function () { return view.f.predTraits; },
        needs: "Shows up once a hunter buds with inheritance on (Settings → Predators → Hunters inherit traits).",
        cap: "1 = the configured hunter. Speed above 1 catches more but burns more; a budding threshold below 1 breeds sooner on a thinner reserve. Hunters put back by a floor start at 1 again.",
        data: function () {
          /* the means are 0 while no hunter is alive: a gap, not a dive to 0;
           * and the axis hugs the data (at least 0.9-1.1), since the drift is small */
          var p = col(COL.pred), lo = 0.9, hi = 1.1;
          function live(y) {
            return y.map(function (v, i) {
              if (!(p[i] > 0)) return NaN;
              lo = Math.min(lo, v); hi = Math.max(hi, v);
              return v;
            });
          }
          var sp = live(col(COL.predSpeed)), bd = live(col(COL.predBudding));
          return { t: view.t, zero: false, yMin: Math.floor(lo * 20) / 20, yMax: Math.ceil(hi * 20) / 20,
                   yFmt: function (v) { return v.toFixed(2); },
                   series: [line("speed ×", sp, K.pred), line("energy to bud ×", bd, S[3])] };
        },
        legend: function () { return [{ name: "speed ×", color: K.pred }, { name: "energy to bud ×", color: S[3] }]; } },
      { id: "age", title: "Age of the living fish (s)", draw: C.lines,
        cap: "A young population is turning over fast, through starvation or hunters; an old one is living out its lifespan.",
        data: function () { return fan(COL.q_age, S[6]); }, legend: function () { return FAN_LEGEND(S[6]); } }
    ] },
    { id: "lines", name: "Family lines", cards: [
      { id: "muller", title: "Family lines over time (Muller plot)", wide: true, tall: true, draw: C.stack,
        cap: "Every fish belongs to the family line of its first parent's line, back to a starting fish. Each colour is one line's share of all fish, in the colour its fish have in the ocean; a colour spreading over the chart is a line taking over. Grey is all the smaller lines.",
        data: mullerData,
        legend: function () {
          var last = hist.n - 1, top = last >= 0 ? hist.top(last) : [], pop = last >= 0 ? hist.get(last, COL.pop) || 1 : 1;
          var share = new Map(top.map(function (p) { return [p[0], p[1] / pop]; }));
          var items = Array.from(lines.slotOf.keys()).map(function (id) {
            return { id: id, name: lineName(id), color: lineColor(id), square: true, share: share.get(id) || 0 };
          }).sort(function (a, b) { return b.share - a.share || a.id - b.id; });
          items.forEach(function (it) { it.value = it.share ? (it.share * 100).toFixed(0) + "%" : "gone"; });
          items.push({ name: "other lines", color: T.other, square: true });
          return items;
        },
        note: function () {
          return lines.slotOf.size ? "" : "No line holds 3% of the fish yet: at the start every fish is its own line, " +
            "and colours appear as some lines outbreed the rest.";
        } },
      { id: "nlines", title: "Family lines still alive", draw: C.lines,
        cap: "Lines die out one by one until a few, then one, remain. Fish added when the population falls below the floor start new lines.",
        data: function () { return { t: view.t, series: [line("lines alive", col(COL.lines), S[0])] }; } },
      { id: "groups", title: "Breeding groups", draw: C.lines,
        cap: "Groups of fish that have lately paired only among themselves. More than one means the population is splitting.",
        data: function () { return { t: view.t, series: [line("groups", col(COL.components), S[4])] }; } }
    ] },
    { id: "tree", name: "Family tree", cards: [
      { id: "tree", title: "Family tree of the living fish", wide: true, huge: true, draw: drawTree,
        cap: "Up to 300 living fish, spread over the tree, traced back through each one's first parent (like mitochondrial DNA). Time runs left to right; each split is a birth, and the colours match the family lines.",
        data: function () {
          return { lay: fam.layout(300, hist.n ? hist.frame(hist.n - 1) : 0) };
        },
        note: function (d) {
          var a = fam.commonAncestor(), live = d.lay.liveTotal;
          var s = "Showing " + d.lay.tips + " of " + live + " living fish. ";
          if (a && live > 1) s += "All of them descend, through first parents, from fish #" + a.id +
            (Number.isFinite(a.born) ? ", born at " + C.fmtTime(a.born * DT) : " (alive before recording began)") + ".";
          else if (live > 1) s += "They come from " + fam.roots().length + " separate starting fish.";
          if (fam.unknownSources) s += " " + fam.unknownSources + " births had no recorded parents.";
          return s;
        } }
    ] },
    { id: "sim", name: "Similarity", cards: [
      { id: "simmat", title: "Who resembles whom", tall: true, draw: drawSim, ondemand: true,
        cap: "Brain-wiring distance between " + SIM_N + " fish taken evenly from the population: dark = alike, light = different. The tree on the left (UPGMA) orders them, so groups of relatives show as dark blocks.",
        data: function () { return similarity(); },
        legendRange: function (d) { return d ? ["alike " + d.lo.toFixed(1), d.max.toFixed(1) + " different"] : null; },
        note: function (d) { return d ? d.m + " fish · sampled at " + C.fmtTime(d.frame * DT) + " · refreshes every 10 s" : ""; } },
      { id: "simmap", title: "Genome map", tall: true, draw: C.scatter, ondemand: true,
        cap: "The same fish, placed so similar brains sit close together (classical MDS), each in its colour from the ocean: by family line, or by brain with that switch on. Separate clouds are groups drifting apart; one family split across clouds is a family diverging.",
        data: function () {
          var d = similarity();
          if (!d) return null;
          var brain = host && host.colourByBrain && host.colourByBrain();
          return { x: Array.from({ length: d.m }, function (_, i) { return d.xy[2 * i]; }),
                   y: Array.from({ length: d.m }, function (_, i) { return d.xy[2 * i + 1]; }),
                   color: function (i) { return brain ? d.rgb[i] : lineColor(d.lins[i]); },
                   tip: function (i) {
                     return "<div class='th'>fish #" + d.ids[i] + "</div>" + C.tipRow(lineColor(d.lins[i]), "family line", "#" + d.lins[i]) +
                       C.tipRow(d.rgb[i], "brain colour", "", true);
                   } };
        } },
      { id: "simhist", title: "How far apart pairs are", tall: true, draw: C.hist, ondemand: true,
        cap: "Distances between all sampled pairs. One hump is one population; two humps are two groups. With the breeding gate on, pairs right of the line cannot have children.",
        data: function () {
          var d = similarity();
          if (!d) return null;
          var gate = host.runConfig().reproMaxDistance;
          return { lo: d.hist.lo, width: d.hist.width, counts: d.hist.counts, color: S[0], xName: "distance",
                   marker: gate >= 0 ? { x: gate, label: "breeding gate " + gate } : null };
        } }
    ] },
    { id: "brains", name: "Brains", cards: [
      { id: "wires", title: "Which senses drive which actions", wide: true, xtall: true, draw: C.heat, ondemand: true,
        cap: "The share of fish whose brain links each sense (rows) to each action (columns), directly or through hidden neurons. Bright cells are wiring that has spread through the population.",
        data: function () {
          var w = wiring(), nm = names().map(prettySense), act = host.actionNames;
          if (!w) return null;
          var max = maxOf(w.path);   /* brightest = the most widespread link */
          return { rows: 41, cols: 12, labelW: 150, labelH: 56, max: max,
                   v: function (r, c) { return w.path[r * 12 + c] / max; },
                   rowLabel: function (r) { return nm[r] || ""; }, colLabel: function (c) { return act[c]; },
                   cellTip: function (r, c) {
                     return "<div class='th'>" + C.esc(nm[r]) + " → " + C.esc(act[c]) + "</div>" +
                       C.tipRow(C.seq(w.path[r * 12 + c] / max), "any path", pct(w.path[r * 12 + c]) + " of fish", true) +
                       C.tipRow(C.seq(w.direct[r * 12 + c] / max), "a direct link", pct(w.direct[r * 12 + c]) + " of fish", true);
                   } };
        },
        legendScale: true },
      { id: "senses", title: "Senses in use over time", wide: true, xtall: true, draw: drawSenses,
        cap: "Each row is a sense, brighter = more fish wired to use it. A row lighting up is selection recruiting that sense, like the predator senses once hunters appear.",
        data: function () {
          var max = 0;
          for (var i = 0; i < hist.n; i++)
            for (var s = 0; s < D.NSENS; s++) max = Math.max(max, hist.get(i, COL.sensors + s));
          return { names: names().map(prettySense), max: max || 1 };
        }, legendScale: true }
    ] },
    { id: "behave", name: "Behaviour", cards: [
      { id: "school", title: "Schooling", draw: C.lines,
        cap: "How well each fish lines up with its neighbours: 1 = swimming as a school, near 0 = each its own way.",
        data: function () { return { t: view.t, yMin: 0, yMax: 1, series: [line("alignment", col(COL.neighAlign), S[0])] }; } },
      { id: "company", title: "Company", draw: C.lines,
        cap: "How many other fish each one can see. High alignment with lots of company is a school; with little, loose travel groups.",
        data: function () { return { t: view.t, series: [line("neighbours in sight", col(COL.neighCount), S[2])] }; } },
      { id: "flow", title: "Riding the current", draw: C.lines, when: function () { return view.f.current; },
        needs: "Shows up when the ocean has a current (Settings → Ocean → Current strength).",
        cap: "+1 = fish swim with the flow, −1 = against it. Rising above 0 means riding the current has been selected.",
        data: function () { return { t: view.t, yMin: -1, yMax: 1, series: [line("with the flow", col(COL.flowAlign), S[2])] }; } },
      { id: "flee", title: "Fleeing hunters", draw: C.lines, when: function () { return view.f.pred; },
        needs: "Shows up when the world has predators (Settings → Predators).",
        cap: "Among fish with a hunter in sight: +1 = swimming straight away from it. Rising means escape behaviour is evolving.",
        data: function () { return { t: view.t, yMin: -1, yMax: 1, series: [line("away from hunters", col(COL.predAlign), K.pred)] }; } }
    ] }
  ];

  /* ---- DOM ---- */
  var tabsEl = el("dtabs"), gridEl = el("dgrid"), noteEl = el("dnote");
  /* the tabs (web/ui_common.js tabs, as the Ocean's): a pointer's press lets
   * the focus go (the shortcuts work again), the keyboard's keeps it; Left /
   * Right the next one round, Home / End the first and last, the focus going
   * with the selection; Tab lands on the selected one */
  var tabIds = TABS.map(function (t) { return t.id; }), tabBtn = {};
  var dtabs = UI.tabs(tabsEl, { ids: function () { return tabIds; }, current: function () { return tab; },
                                button: function (id) { return tabBtn[id] || null; }, select: showTab });
  TABS.forEach(function (tb) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = tb.name;
    b.setAttribute("role", "tab");
    b.dataset.tab = tb.id;
    tabBtn[tb.id] = b;
    dtabs.bind(b, tb.id);
    tabsEl.appendChild(b);
  });
  function showTab(id) {
    tab = id;
    dtabs.mark(id);
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
      box.className = "cbox" + (cd.tall ? " tall" : "") + (cd.huge ? " huge" : "") + (cd.xtall ? " xtall" : "");
      gridEl.appendChild(sec);
      cards[cd.id] = { def: cd, el: sec, box: box, legend: sec.querySelector(".legend"),
                       note: sec.querySelector(".cnote"), chart: new C.Chart(box, cd.draw) };
    });
    gridEl.scrollTop = 0;
    update(true);
  }

  function update(force) {
    if (!isOpen) return;
    lines.update(hist);
    var key = tab + "|" + hist.version + "|" + fam.version + "|" + gridEl.clientWidth;
    var ondemandDue = (tab === "sim" && (!simCache || performance.now() - simCache.at >= SIM_EVERY_MS)) ||
                      (tab === "brains" && (!wireCache || performance.now() - wireCache.at >= WIRE_EVERY_MS));
    if (!force && key === lastKey && !ondemandDue) return;
    lastKey = key;
    view = { t: hist.times(), f: flags() };
    Object.keys(cards).forEach(function (id) {
      var c = cards[id], cd = c.def;
      var on = !cd.when || cd.when();
      c.el.classList.toggle("off", !on);
      if (!on) { c.note.textContent = cd.needs || ""; c.legend.innerHTML = ""; c.legend.__html = ""; return; }
      var data = cd.data();
      c.chart.draw(data || null);
      if (cd.legend) C.legend(c.legend, cd.legend());
      else if (cd.legendScale && data) rampLegend(c.legend, "0%", pct(data.max) + " of fish");
      else if (cd.legendRange && data) rampLegend.apply(null, [c.legend].concat(cd.legendRange(data)));
      c.note.textContent = cd.note ? cd.note(data) : "";
    });
    var span = hist.n ? (hist.frame(hist.n - 1) - hist.frame(0)) * DT : 0;
    noteEl.textContent = hist.n
      ? "Recorded on this device since the last restart: " + C.fmtTime(span) + " of simulated time, " +
        hist.n + " samples (one every " + +(hist.every() * DT).toFixed(2) + " s). Nothing is uploaded; Restart clears it."
      : "Recording starts with the world. Nothing is uploaded; Restart clears it.";
  }
  /* the colour ramp's key, darkest to brightest */
  function rampLegend(el, from, to) {
    var key = "ramp" + from + "|" + to;
    if (el.__html === key) return;
    el.__html = key;
    el.innerHTML = "<span class='li'></span><span class='scale'></span><span class='li'></span>";
    el.children[0].textContent = from;
    el.children[2].textContent = to;
    el.querySelector(".scale").style.background =
      "linear-gradient(90deg," + [0, 0.17, 0.33, 0.5, 0.67, 0.83, 1].map(C.seq).join(",") + ")";
  }
  function maxOf(a) { var m = 0; for (var i = 0; i < a.length; i++) if (a[i] > m) m = a[i]; return m || 1; }

  function download(name, text, type) {
    var url = URL.createObjectURL(new Blob([text], { type: type }));
    var a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }
  function frameNow() { return hist.n ? hist.frame(hist.n - 1) : 0; }
  el("dcsv").addEventListener("click", function () {
    download("evo_dashboard_f" + frameNow() + ".csv", hist.csv(names()), "text/csv");
    this.blur();
  });
  el("dtree").addEventListener("click", function () {
    download("evo_family_tree_f" + frameNow() + ".nwk", fam.newick(fam.layout(2000, frameNow())), "text/plain");
    this.blur();
  });

  function open() {
    if (isOpen) return;
    isOpen = true;
    if (host && host.setDrawer) host.setDrawer(false);
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
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { update(true); }, 150);
  });

  window.EvoDash = {
    attach: function (h) { host = h; M = h.module; if (M && M._evo_rec_config) h.setRecEvery(hist.every()); },
    pump: pump, reset: reset, ingest: ingest,
    every: function () { return hist.every(); },
    open: open, close: close, isOpen: function () { return isOpen; },
    /* for tests: the data model */
    _data: { hist: hist, fam: fam, lines: lines }
  };
})();
