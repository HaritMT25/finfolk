// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the M2a body plan's fixture viewer (window.EvoBodyPlanViewer;
 * web/ocean_bodyplan.html).
 *
 * The C++ body-plan law (src/ocean/body_plan.hpp, geometry law 1), run by this
 * page's own Ocean module (web/evo_ocean.wasm: oc_body_preview, oc_body_rest,
 * oc_body_samples, oc_body_tris, oc_body_metrics_layout; no world is made),
 * drawn at rest in four views (side, dorsal, frontal, orbit: drag to turn)
 * with overlays (the hull, the mouth, the fin roots, areas, the hull's
 * centroid and its inertia ellipse), and every coefficient listed with its
 * units. A body comes from the fixture (tests/fixtures/ocean_body_fixture.json,
 * when the page is served with the repository: python3 wasm/serve.py), from a
 * fish of the Ocean page (its card's "viewer" link: #fish=ID:WORDS, the float
 * bits of its 63 appearance genes, 5 physical alleles, size and elongation)
 * or from the sliders. The load sliders preview the torso's inflation by gas
 * and fuel (a diagnostic compile; the birth coefficients are unloaded).
 *
 * The GPU check (?check=1, or the button; the headless test
 * tests/ocean_body_gpu.mjs reads window.__bodyPlanCheck): for every fixture
 * body, the Wasm law's rest points and coefficients against the NATIVE law's
 * digests in the fixture (bit for bit), then the renderer's own GLSL
 * (EvoAppearance.GLSL.MORPH) through transform feedback at the same canonical
 * samples (EvoOceanSceneParity.bodyPlanVertexCheck) with identity, permuted
 * and sparse gene slots, within its locked tolerance; then each planted GLSL
 * fault (radius, root, caudalClip) must fail it. Display only: nothing here
 * reaches a simulation. */
(function (root) {
  root.EvoBodyPlanViewer = null;
  var A = root.EVO_ASSETS || {}, EA = root.EvoAppearance, PAR = root.EvoOceanSceneParity;
  /** @type {any} */
  var M = null;
  var layout = null, samples = null, tris = null, NS = 0, NT = 0, fixture = null;
  var PART_COLOURS = ["#6fa8c9", "#e0a050", "#c97fd0", "#7fd08a", "#f2f2f2", "#d0c07f", "#7fc9c4", "#d06f6f", "#8a6f4f"];
  var PART_NAMES = ["hull", "caudal", "dorsal", "pectoral", "eye", "anal", "pelvic", "barbel", "collar"];
  /* body: {name, genes (63), physical (5), size, elong, lambda}; compiled: {ok, metrics, points} */
  /** @type {{body: any, load: {gas: number, fuel: number}, yaw: number, pitch: number, compiled: any, overlays: Record<string, boolean>}} */
  var state = { body: null, load: { gas: 0, fuel: 0 }, yaw: -0.6, pitch: 0.35, compiled: null, overlays: { mouth: true, roots: true, areas: true, centroid: true, inertia: true } };
  function el(id) { return document.getElementById(id); }
  function status(msg) { var s = el("bpstatus"); if (s) s.textContent = msg; }

  /* ---------------- the module ---------------- */
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script"); s.src = src; s.onload = function () { resolve(null); };
      s.onerror = function () { reject(new Error(src + " did not load")); }; document.head.appendChild(s);
    });
  }
  function loadModule() {
    var js = A.ocean || "evo_ocean.js", wasm = A.oceanWasm || "evo_ocean.wasm";
    return loadScript(js).then(function () {
      var f = /** @type {any} */ (root).createEvoOcean;
      if (typeof f !== "function") throw new Error(js + " defines no createEvoOcean()");
      return f({ locateFile: function (p) { return p.slice(-5) === ".wasm" ? wasm : p; } });
    });
  }
  function heap() { return M.HEAPU8.buffer; }
  function cStr(ptr) { var u = new Uint8Array(heap()), e = ptr; while (u[e]) e++; return new TextDecoder().decode(u.subarray(ptr, e)); }
  function withFloats(arrays, fn) {   /* each array copied into the module's memory, fn(pointers), freed */
    var ptrs = arrays.map(function (a) { var p = M._malloc(4 * a.length); new Float32Array(heap(), p, a.length).set(a); return p; });
    try { return fn(ptrs); } finally { ptrs.forEach(function (p) { M._free(p); }); }
  }
  function readF32(ptr, n) { return new Float32Array(heap(), ptr, n).slice(); }
  /** @returns {{ok: boolean, metrics: Float32Array, points: Float32Array}} */
  function compileBody(b, load) {
    return withFloats([b.genes, b.physical], function (p) {
      var ok = M._oc_body_preview(p[0], b.size, b.elong, p[1], load ? load.gas : 0, load ? load.fuel : 0);
      return { ok: !!ok, metrics: readF32(M._oc_body_preview_metrics(), layout.stride), points: readF32(M._oc_body_preview_points(), 3 * NS) };
    });
  }
  function restBody(b) {
    return withFloats([b.genes], function (p) { M._oc_body_rest(p[0], b.lambda); return readF32(M._oc_body_rest_points(), 3 * NS); });
  }
  /* the fixture's loaded compile (tools/ocean_body_fixture.cpp kLoad: gas .5, fuel .25 of the capacities) */
  var FIXTURE_LOAD = { gas: 0.5, fuel: 0.25 };
  /* the fixture driver's H32 (tools/ocean_body_fixture.cpp): two 32-bit lanes over the float bits */
  function digest(f32) {
    var u = new Uint32Array(f32.buffer, f32.byteOffset, f32.length), a = 0x811c9dc5, b = 0x01234567;
    for (var i = 0; i < u.length; i++) { a = Math.imul((a ^ u[i]) >>> 0, 16777619) >>> 0; b = (Math.imul(b, 0x9E3779B1) + u[i]) >>> 0; }
    return ("00000000" + a.toString(16)).slice(-8) + ("00000000" + b.toString(16)).slice(-8);
  }

  /* ---------------- bodies ---------------- */
  function neutralGenes() {
    var g = new Float32Array(63), NM = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0, 0.5, 0.5, 0.5, 0.5, 0.5, 0, 0.25, 0.4, 0.7, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0, 0.5, 0.5, 0.5];
    for (var j = 0; j < 30; j++) g[33 + j] = NM[j];
    return g;
  }
  /* lambda as the C++ law computes it: L = (20f·S)·E, R = 4.6f·S, L / R, every step rounded to binary32
   * (4.6f first: fround(4.6 * S) would round once from the double 4.6) */
  function makeBody(name, genes, physical, size, elong) {
    var f = Math.fround, S = f(size), E = f(elong);
    return { name: name, genes: Float32Array.from(genes), physical: Float32Array.from(physical), size: S, elong: E,
             lambda: f(f(f(20 * S) * E) / f(f(4.6) * S)) };
  }
  function fromHash() {
    var m = /#fish=(\d+):([0-9a-f]{560})/.exec(location.hash || "");
    if (!m) return null;
    var words = new Uint32Array(70), f = new Float32Array(words.buffer);
    for (var i = 0; i < 70; i++) words[i] = parseInt(m[2].substr(8 * i, 8), 16);
    return makeBody("fish #" + m[1], f.subarray(0, 63), f.subarray(63, 68), f[68], f[69]);
  }
  function fixtureBodies() {
    if (fixture) return fixture.bodies.map(function (b) { return makeBody(b.name, b.genes, b.physical, b.size, b.elong); });
    var out = [makeBody("neutral", neutralGenes(), [0.5, 0.5, 0, 0.4, 0.5], 1, 1)];
    for (var j = 0; j < 30; j++) for (var v = 0; v < 2; v++) { var g = neutralGenes(); g[33 + j] = v; out.push(makeBody("morph" + j + "=" + v, g, [0.5, 0.5, 0, 0.4, 0.5], 1, 1)); }
    return out;
  }

  /* ---------------- drawing ---------------- */
  function project(view, p) {   /* -> [screen x, screen y, depth] in world units */
    if (view === "side") return [p[0], -p[2], -p[1]];
    if (view === "dorsal") return [p[0], p[1], -p[2]];
    if (view === "frontal") return [p[1], -p[2], p[0]];
    var cy = Math.cos(state.yaw), sy = Math.sin(state.yaw), cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
    var x = cy * p[0] - sy * p[1], y = sy * p[0] + cy * p[1], z = p[2];
    return [x, -(cp * z - sp * y), cp * y + sp * z];
  }
  function drawView(cv, view) {
    var c = state.compiled;
    if (!c || !cv) return;
    var ctx = cv.getContext("2d");
    if (!ctx) return;
    var W = cv.width, H = cv.height, P = c.points, mm = c.metrics;
    ctx.fillStyle = "#08161a"; ctx.fillRect(0, 0, W, H);
    var lo = [Infinity, Infinity], hi = [-Infinity, -Infinity], pr = new Array(NS), i;
    for (i = 0; i < NS; i++) {
      var q = project(view, [P[3 * i], P[3 * i + 1], P[3 * i + 2]]); pr[i] = q;
      if (q[0] < lo[0]) lo[0] = q[0]; if (q[0] > hi[0]) hi[0] = q[0]; if (q[1] < lo[1]) lo[1] = q[1]; if (q[1] > hi[1]) hi[1] = q[1];
    }
    var sc = 0.9 * Math.min(W / Math.max(1e-6, hi[0] - lo[0]), H / Math.max(1e-6, hi[1] - lo[1]));
    var ox = W / 2 - sc * (lo[0] + hi[0]) / 2, oy = H / 2 - sc * (lo[1] + hi[1]) / 2;
    function sx(q) { return ox + sc * q[0]; }
    function sy(q) { return oy + sc * q[1]; }
    var order = [];
    for (i = 0; i < NT; i++) {
      var t = tris.subarray(4 * i, 4 * i + 4);
      order.push([(pr[t[0]][2] + pr[t[1]][2] + pr[t[2]][2]) / 3, i]);
    }
    order.sort(function (a, b) { return b[0] - a[0]; });   /* far first */
    order.forEach(function (o) {
      var t = tris.subarray(4 * o[1], 4 * o[1] + 4), a = pr[t[0]], b = pr[t[1]], d = pr[t[2]];
      ctx.beginPath(); ctx.moveTo(sx(a), sy(a)); ctx.lineTo(sx(b), sy(b)); ctx.lineTo(sx(d), sy(d)); ctx.closePath();
      ctx.fillStyle = PART_COLOURS[t[3]] + (t[3] === 0 ? "cc" : "aa"); ctx.fill();
      ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.lineWidth = 0.5; ctx.stroke();
    });
    var at = layout.at, O = state.overlays;
    function m3(name) { var f = at[name]; return [mm[f.offset], mm[f.offset + 1], mm[f.offset + 2]]; }
    function v1(name) { return mm[at[name].offset]; }
    if (O.roots) {   /* the paired and median fins' root rows */
      ctx.strokeStyle = "#ffe066"; ctx.lineWidth = 2;
      [samplesBase("dorsal"), samplesBase("anal"), samplesBase("pecR"), samplesBase("pecL"), samplesBase("pelR"), samplesBase("pelL")].forEach(function (b0) {
        ctx.beginPath();
        for (var q = 0; q <= 16; q++) { var p = pr[b0 + 2 * q]; if (q) ctx.lineTo(sx(p), sy(p)); else ctx.moveTo(sx(p), sy(p)); }
        ctx.stroke();
      });
    }
    if (O.mouth) {
      var mc = project(view, m3("mouthCentre")), r = 0.5 * v1("gapeDiameter");
      ctx.strokeStyle = "#ff6b6b"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(sx(mc), sy(mc), Math.max(2, sc * r), 0, 2 * Math.PI); ctx.stroke();
    }
    var cen = project(view, m3("hullCentroid"));
    if (O.inertia) {   /* the solid ellipsoid with the hull's volume and inertia: a² = 5 (Iy + Iz − Ix) / (2V) */
      var I = mm.subarray(at.hullInertia.offset, at.hullInertia.offset + 6), V = v1("hullVolume");
      var ax = [Math.sqrt(Math.max(0, 5 * (I[1] + I[2] - I[0]) / (2 * V))), Math.sqrt(Math.max(0, 5 * (I[0] + I[2] - I[1]) / (2 * V))),
                Math.sqrt(Math.max(0, 5 * (I[0] + I[1] - I[2]) / (2 * V)))];
      ctx.strokeStyle = "#9be7ff"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]); ctx.beginPath();
      for (var k = 0; k <= 64; k++) {   /* the ellipsoid's outline in this view: its principal sections' projections, sampled */
        var th = 2 * Math.PI * k / 64, pts3;
        if (view === "side") pts3 = [ax[0] * Math.cos(th), 0, ax[2] * Math.sin(th)];
        else if (view === "dorsal") pts3 = [ax[0] * Math.cos(th), ax[1] * Math.sin(th), 0];
        else if (view === "frontal") pts3 = [0, ax[1] * Math.cos(th), ax[2] * Math.sin(th)];
        else pts3 = [ax[0] * Math.cos(th), ax[1] * Math.sin(th), 0];
        var cc = m3("hullCentroid"), qq = project(view, [cc[0] + pts3[0], cc[1] + pts3[1], cc[2] + pts3[2]]);
        if (k) ctx.lineTo(sx(qq), sy(qq)); else ctx.moveTo(sx(qq), sy(qq));
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
    if (O.centroid) {
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5; ctx.beginPath();
      ctx.moveTo(sx(cen) - 6, sy(cen)); ctx.lineTo(sx(cen) + 6, sy(cen)); ctx.moveTo(sx(cen), sy(cen) - 6); ctx.lineTo(sx(cen), sy(cen) + 6); ctx.stroke();
    }
    if (O.areas && view !== "frontal") {
      ctx.fillStyle = "#e8f4f6"; ctx.font = "11px system-ui, sans-serif";
      var F = layout.fins, f0 = at.fins.offset;
      F.names.forEach(function (nm, fi) {
        var base = f0 + F.stride * fi, area = mm[base + F.values.area];
        if (!(area > 0) || (view === "side" && /L$/.test(nm))) return;
        var cp = project(view, [mm[base + F.values.centroid], mm[base + F.values.centroid + 1], mm[base + F.values.centroid + 2]]);
        ctx.fillText(nm + " " + area.toFixed(1), sx(cp) + 4, sy(cp) - 4);
      });
    }
    ctx.fillStyle = "#9fb7bd"; ctx.font = "12px system-ui, sans-serif"; ctx.fillText(view, 8, 16);
  }
  function samplesBase(which) {   /* the canonical sample ranges (body_plan.hpp kDorsal0 ..): from the sample table */
    var want = { dorsal: [2, 1], anal: [5, 1], pecR: [3, 1], pecL: [3, -1], pelR: [6, 1], pelL: [6, -1] }[which];
    for (var i = 0; i < NS; i++) if (samples[6 * i + 4] === want[0] && samples[6 * i + 5] === want[1]) return i;
    return 0;
  }
  function readout() {
    var tb0 = el("bpmetrics"), c = state.compiled;
    if (!tb0 || !c) return;
    var tb = /** @type {HTMLElement} */ (tb0);
    tb.textContent = "";
    var mm = c.metrics;
    Object.keys(layout.at).forEach(function (name) {
      var f = layout.at[name], tr = document.createElement("tr"), a = document.createElement("th"), b = document.createElement("td"), u = document.createElement("td");
      a.textContent = name; a.title = f.what || "";
      if (name === "fins") {   /* every fin value, each with its own units (the layout's fins.units) */
        var F = layout.fins, U = F.units || {}, parts = [];
        F.names.forEach(function (nm, fi) {
          var o = f.offset + F.stride * fi, vals = [];
          Object.keys(F.values).forEach(function (k) {
            var n = k === "normal" || k === "centroid" || k === "lever" ? 3 : 1, xs = [];
            for (var q = 0; q < n; q++) xs.push(Number(mm[o + F.values[k] + q].toPrecision(4)));
            vals.push(k + " " + (n > 1 ? "(" + xs.join(", ") + ")" : xs[0]) + (U[k] ? " " + U[k] : ""));
          });
          parts.push(nm + ": " + vals.join(", "));
        });
        b.textContent = parts.join("; ");
      } else {
        var vals = [];
        for (var k = 0; k < f.count; k++) vals.push(Number(mm[f.offset + k].toPrecision(6)));
        b.textContent = vals.join(", ");
      }
      u.textContent = f.units === "" ? "–" : f.units;   /* (– dimensionless; "mixed": per value, in the row) */
      tr.appendChild(a); tr.appendChild(b); tr.appendChild(u); tb.appendChild(tr);
    });
  }
  function redraw() {
    if (!state.body) return;
    var c = compileBody(state.body, state.load);
    var desc = state.body.name + " · S " + state.body.size.toFixed(3) + " E " + state.body.elong.toFixed(3) +
               (state.load.gas || state.load.fuel ? " · load: gas " + state.load.gas + ", fuel " + state.load.fuel : " · unloaded (birth)");
    if (!c.ok) {   /* a refused compile: nothing drawn or listed from it (its outputs are zeros) */
      state.compiled = null;
      ["side", "dorsal", "frontal", "orbit"].forEach(function (v) {
        var cv = /** @type {HTMLCanvasElement|null} */ (el("bp_" + v)), g = cv && cv.getContext("2d");
        if (cv && g) { g.fillStyle = "#08161a"; g.fillRect(0, 0, cv.width, cv.height); g.fillStyle = "#ff8a8a"; g.font = "13px system-ui, sans-serif"; g.fillText("compile refused: inputs outside the law's domain", 12, 22); }
      });
      var tb = el("bpmetrics");
      if (tb) tb.textContent = "";
      status("COMPILE REFUSED · " + desc);
      return;
    }
    state.compiled = c;
    ["side", "dorsal", "frontal", "orbit"].forEach(function (v) { drawView(/** @type {HTMLCanvasElement} */ (el("bp_" + v)), v); });
    readout();
    status(desc);
  }

  /* ---------------- the GPU check ---------------- */
  function gpuCheck() {
    /** @type {any} */
    var out = { ok: false, error: null, native: null, slots: {}, faults: {}, started: new Date().toISOString() };
    root.__bodyPlanCheck = null;
    if (!PAR || !PAR.bodyPlanVertexCheck) { out.error = "web/ocean_scene_parity.js (bodyPlanVertexCheck) not loaded"; root.__bodyPlanCheck = out; return Promise.resolve(out); }
    if (!fixture) { out.error = "no fixture (serve the repository: tests/fixtures/ocean_body_fixture.json)"; root.__bodyPlanCheck = out; return Promise.resolve(out); }
    var cv = document.createElement("canvas"), gl = /** @type {WebGL2RenderingContext|null} */ (cv.getContext("webgl2"));
    if (!gl) { out.error = "no WebGL2"; root.__bodyPlanCheck = out; return Promise.resolve(out); }
    /* native (the fixture's digests) == Wasm (this module), bit for bit */
    var restBad = [], metricBad = [], loadBad = [], bodies = fixture.bodies.map(function (fb) {
      var b = makeBody(fb.name, fb.genes, fb.physical, fb.size, fb.elong);
      if (Math.fround(fb.lambda) !== b.lambda) restBad.push(fb.name + " (lambda)");
      var r = restBody(b), c = compileBody(b, null), cl = compileBody(b, FIXTURE_LOAD);
      if (digest(r) !== fb.restDigest) restBad.push(fb.name);
      if (!c.ok || digest(c.metrics) !== fb.metricsDigest) metricBad.push(fb.name);
      if (!cl.ok || digest(cl.metrics) !== fb.loadedDigest) loadBad.push(fb.name);
      return { name: fb.name, genes: b.genes, lambda: b.lambda, rest: r };
    });
    out.native = { bodies: bodies.length, restMismatch: restBad, metricsMismatch: metricBad, loadedMismatch: loadBad,
                   ok: !restBad.length && !metricBad.length && !loadBad.length };
    var fx = { samples: fixture.samples, bodies: bodies };
    var runs = ["identity", "permuted", "sparse"].map(function (sm) { return PAR.bodyPlanVertexCheck(gl, EA, fx, { slotMap: sm }); });
    var faults = (PAR.BODY_MUT || []).map(function (mu) { return PAR.bodyPlanVertexCheck(gl, EA, fx, { mutate: mu }); });
    return Promise.all(runs.concat(faults)).then(function (r) {
      ["identity", "permuted", "sparse"].forEach(function (sm, i) { out.slots[sm] = r[i]; });
      (PAR.BODY_MUT || []).forEach(function (mu, i) { var x = r[3 + i]; out.faults[mu] = { caught: !x.error && x.ok === false, worst: x.worst, error: x.error || null }; });
      var slotsOk = ["identity", "permuted", "sparse"].every(function (sm) { return out.slots[sm].ok === true; });
      var faultsOk = (PAR.BODY_MUT || []).length === 3 && Object.keys(out.faults).every(function (k) { return out.faults[k].caught; });
      out.ok = out.native.ok && slotsOk && faultsOk;
      root.__bodyPlanCheck = out;
      var pre = el("bpcheck");
      if (pre) pre.textContent = (out.ok ? "PASS" : "FAIL") + "\n" + JSON.stringify(out, null, 1);
      return out;
    }, function (e) { out.error = String(e && e.message || e); root.__bodyPlanCheck = out; return out; });
  }

  /* ---------------- the page ---------------- */
  function slider(parent, label, min, max, step, value, on) {
    var row = document.createElement("label"), s = document.createElement("input"), v = document.createElement("span");
    row.className = "bprow"; s.type = "range"; s.min = String(min); s.max = String(max); s.step = String(step); s.value = String(value);
    v.textContent = Number(value).toFixed(3);
    s.addEventListener("input", function () { v.textContent = Number(s.value).toFixed(3); on(Number(s.value)); });
    row.appendChild(document.createTextNode(label + " ")); row.appendChild(s); row.appendChild(v); parent.appendChild(row);
    return s;
  }
  function buildControls(list) {
    var sel = /** @type {HTMLSelectElement} */ (el("bpbody")), box0 = el("bpsliders");
    if (!sel || !box0) return;
    var box = /** @type {HTMLElement} */ (box0);
    sel.textContent = "";
    list.forEach(function (b, i) { var o = document.createElement("option"); o.value = String(i); o.textContent = b.name; sel.appendChild(o); });
    function choose(i) {
      var b = list[i];
      state.body = makeBody(b.name, b.genes, b.physical, b.size, b.elong);
      box.textContent = "";
      slider(box, "size S", 0.5, 2, 0.01, b.size, function (x) { state.body = makeBody(b.name + "*", state.body.genes, state.body.physical, x, state.body.elong); redraw(); });
      slider(box, "elongation E", 0.5, 2, 0.01, b.elong, function (x) { state.body = makeBody(b.name + "*", state.body.genes, state.body.physical, state.body.size, x); redraw(); });
      (layout.genes || []).forEach(function (nm, k) { slider(box, nm, 0, 1, 0.01, b.physical[k], function (x) { state.body.physical[k] = Math.fround(x); redraw(); }); });
      for (var j = 0; j < 30; j++) (function (jj) { slider(box, "shape " + jj, 0, 1, 0.01, b.genes[33 + jj], function (x) { state.body.genes[33 + jj] = Math.fround(x); redraw(); }); })(j);
      redraw();
    }
    sel.onchange = function () { choose(Number(sel.value)); };
    choose(0);
  }
  function start() {
    status("loading the Ocean module…");
    var fixtureUrl = A.fixture || "../tests/fixtures/ocean_body_fixture.json";
    var fx = fetch(fixtureUrl).then(function (r) { return r.ok ? r.json() : null; }, function () { return null; });
    return Promise.all([loadModule(), fx]).then(function (r) {
      M = r[0]; fixture = r[1];
      var need = ["oc_body_preview", "oc_body_rest", "oc_body_samples", "oc_body_tris", "oc_body_metrics_layout", "oc_body_sample_count", "oc_body_tri_count"];
      var miss = need.filter(function (f) { return typeof M["_" + f] !== "function"; });
      if (miss.length) throw new Error("this Ocean module has no body plan (" + miss.join(", ") + ")");
      layout = JSON.parse(cStr(M._oc_body_metrics_layout()));
      var at = {};
      layout.fields.forEach(function (f) { at[f.name] = f; });
      layout.at = at;
      NS = M._oc_body_sample_count(); NT = M._oc_body_tri_count();
      samples = readF32(M._oc_body_samples(), 6 * NS);
      var trisPtr = M._oc_body_tris();   /* (first: it allocates, and may grow the memory heap() then views) */
      tris = new Uint16Array(heap(), trisPtr, 4 * NT).slice();
      if (fixture && (fixture.sampleCount !== NS || fixture.geometryLaw !== layout.law || fixture.metrics !== layout.stride)) {
        status("the fixture is for another law or layout: not used"); fixture = null;
      }
      var list = fixtureBodies(), mine = fromHash();
      if (mine) list.unshift(mine);
      buildControls(list);
      ["gas", "fuel"].forEach(function (k) {
        var s = /** @type {HTMLInputElement} */ (el("bpload_" + k)), sv = el("bpload_" + k + "v");
        if (s) s.addEventListener("input", function () { state.load[k] = Number(s.value); if (sv) sv.textContent = Number(s.value).toFixed(2); redraw(); });
      });
      Object.keys(state.overlays).forEach(function (k) {
        var c = /** @type {HTMLInputElement} */ (el("bpo_" + k));
        if (c) { c.checked = state.overlays[k]; c.addEventListener("change", function () { state.overlays[k] = c.checked; redraw(); }); }
      });
      var orbit = el("bp_orbit"), drag = null;
      if (orbit) {
        orbit.addEventListener("pointerdown", function (e) { drag = [e.clientX, e.clientY]; });
        root.addEventListener("pointerup", function () { drag = null; });
        orbit.addEventListener("pointermove", function (e) {
          if (!drag) return;
          state.yaw += 0.01 * (e.clientX - drag[0]); state.pitch = Math.max(-1.5, Math.min(1.5, state.pitch + 0.01 * (e.clientY - drag[1])));
          drag = [e.clientX, e.clientY]; drawView(/** @type {HTMLCanvasElement} */ (orbit), "orbit");
        });
      }
      var btn = el("bpgpu");
      if (btn) btn.addEventListener("click", function () { gpuCheck(); });
      if (/[?&]check=1/.test(location.search)) return gpuCheck();
      return null;
    }).catch(function (e) {
      status("could not start: " + (e && e.message || e));
      root.__bodyPlanCheck = { ok: false, error: "could not start: " + (e && e.message || e) };
    });
  }
  root.EvoBodyPlanViewer = { start: start, gpuCheck: gpuCheck, digest: digest, redraw: redraw };
  if (typeof document !== "undefined" && document.readyState !== "loading") start();
  else if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", start);
})(typeof window !== "undefined" ? window : /** @type {any} */ (globalThis));
