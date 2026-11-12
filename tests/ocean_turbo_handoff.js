// ocean_turbo_handoff.js — the 3-D Ocean page's Turbo hand-off, in node, against
// the real module (web/evo_ocean.{js,wasm}, two and more instances) and the
// real worker (web/ocean_worker.js, in a vm context with a worker's globals),
// through the helpers the page and the worker share (web/ocean_handoff.js).
// No npm, no browser:
//
//   node tests/ocean_turbo_handoff.js        (from anywhere; exit 0 = all pass)
//
// It checks:
//   * the hand-off with unequal memories, both ways, with plenty of free space
//     in the receiver (main's takeMemory, kept here as legacyTake, is shown
//     failing on the same images first);
//   * memory growth forced inside oc_summary / oc_families / oc_inspect /
//     oc_sensor_names, on both sides, while Turbo samples the dashboards;
//   * an exception in a chunk: with the world whole (it comes back), and out
//     of oc_step (the page keeps its own copy); then a second Turbo session,
//     in a fresh worker and in the failed one; a refused hand-back (the page
//     can't grow) resumes and hands back on the next Stop;
//   * that after a round trip with live edits (on the page before, in the
//     worker, on the page after) N further steps are bit-identical to an
//     uninterrupted run with the same edits at the same frames (a fingerprint
//     of every oc_* export: positions, depths, bodies, colours, ids, food,
//     predators, stats, the summary, every family line, the appearance
//     genome's rows (its owner-bound side array lives in module memory and
//     must come across whole), and oc_inspect of every fish: its numbers,
//     hidden neurons and wiring);
//   * Randomize (web/ocean_config.js draw) against oc_init at small and
//     default world sizes, and the refusals of imported values the sheet
//     would otherwise round or drop;
//   * the page's live edits around Turbo (web/ocean_handoff.js ledger, as
//     web/ocean.js uses it): dependent edits acknowledged in Turbo and then
//     a worker failure that loses the world (minSpeed 0, maxSpeed 300,
//     minSpeed 200 come back in that order, bit-identical to applying them
//     directly; main's key-order recovery ran 30-300), and an unanswered
//     edit with a newer one held after Stop (the newer wins: field, runCfg
//     and world agree; main's ran the older one);
//   * a repeated key in ?cfg= or a setup file (parseFirst / cfgJson): the
//     page and oc_init accept or refuse the same documents and run the same
//     world (JSON.parse's page did neither).
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto'), os = require('os');
const { resolveObjectURL } = require('buffer');

const ROOT = path.resolve(__dirname, '..'), WEB = path.join(ROOT, 'web');
const WASM = path.join(WEB, 'evo_ocean.wasm');
const create = require(path.join(WEB, 'evo_ocean.js'));
const HO = require(path.join(WEB, 'ocean_handoff.js'));
require(path.join(WEB, 'ocean_config.js'));
const CFG = globalThis.EvoOceanConfig;
const MB = 1 << 20;
/* the engine build's bytes, as the page fetches them (its identity in a world file: their sha-256) */
const WASM_BYTES = (() => { const b = fs.readFileSync(WASM); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); })();
const WASM_SHA = crypto.createHash('sha256').update(Buffer.from(WASM_BYTES)).digest('hex');

let failures = 0, checks = 0;
function ok(cond, what) {
    checks++;
    if (cond) console.log('  ok   ' + what);
    else { failures++; console.log('  FAIL ' + what); }
}
function section(t) { console.log('\n' + t); }

async function mk(seed, cfg, w, h, pop) {
    const M = await create({ locateFile: p => p.endsWith('.wasm') ? WASM : p });
    const json = cfg && Object.keys(cfg).length ? JSON.stringify(cfg) : '';
    const r = HO.withCString(M, json, p => M._oc_init(seed, w || 1920, h || 1080, 240, pop === undefined ? 300 : pop, p));
    if (!r) throw new Error('oc_init: ' + HO.cString(M, M._oc_last_error()));
    return M;
}
function frame(M) { M._oc_sync(); return HO.f64(M, M._oc_stats(), M._oc_stats_len())[1]; }
function setParam(M, key, v) {
    const r = HO.withCString(M, key, p => M._oc_set_param(p, v));
    if (!r) throw new Error('oc_set_param ' + key + ': ' + HO.cString(M, M._oc_last_error()));
}
/* grow M's memory through its own allocator (a block as big as the memory:
 * it doubles), as an export that allocates does when the heap is full */
function growInside(M) { const p = M._malloc(HO.buffer(M).byteLength); if (!p) throw new Error('malloc'); M._free(p); }
/* grow it by a MiB: the buffer is replaced (every view cut before is
 * detached), as with any growth, without doubling the memory each time */
function growMiB(M) { M.wasmMemory.grow(16); }
function memMB(M) { return (HO.buffer(M).byteLength / MB).toFixed(2); }

/* every oc_* export of the world now, hashed */
function fingerprint(M) {
    M._oc_sync();
    const h = crypto.createHash('sha256');
    const put = (Ctor, ptr, len) => { if (len > 0) h.update(Buffer.from(new Ctor(HO.buffer(M), ptr, len).slice().buffer)); };
    const n = M._oc_creature_count(), fc = M._oc_food_count(), pc = M._oc_predator_count();
    put(Float64Array, M._oc_stats(), M._oc_stats_len());
    put(Float32Array, M._oc_creature_segments(), n * 12);
    put(Float32Array, M._oc_creature_depth(), n);
    put(Float32Array, M._oc_creature_vz(), n);
    put(Float32Array, M._oc_body_params(), n * 2);
    put(Uint8Array, M._oc_creature_colors(), n * 3);
    put(Float64Array, M._oc_creature_ids(), n);
    put(Float32Array, M._oc_food_xy(), fc * 2);
    put(Float32Array, M._oc_food_depth(), fc);
    put(Float32Array, M._oc_predator_data(), pc * 3);
    put(Float32Array, M._oc_predator_depth(), pc);
    if (M._oc_creature_appearance) {   /* the appearance genome: its owner-bound side array, in module memory */
        h.update(Buffer.from(new Int32Array([M._oc_appearance_count(), M._oc_appearance_flags(), M._oc_appearance_broken()]).buffer));
        put(Float32Array, M._oc_creature_appearance(), M._oc_appearance_count() * M._oc_appearance_stride());
    }
    h.update(Buffer.from(new Float64Array(HO.f64(M, M._oc_summary(), M._oc_summary_len())).buffer));
    const k = M._oc_families(1 << 20);
    h.update(Buffer.from(new Float64Array(HO.f64(M, M._oc_families_data(), 2 * k)).buffer));
    const nH = M._oc_num_hidden(), nS = M._oc_num_senses(), nA = M._oc_num_actions();
    for (let i = 0; i < n; i++) {
        if (!M._oc_inspect(i)) throw new Error('oc_inspect ' + i);
        put(Float64Array, M._oc_inspect_info(), M._oc_inspect_len());
        put(Float32Array, M._oc_inspect_sensors(), nS);
        put(Float32Array, M._oc_inspect_hidden(), nH);
        put(Float32Array, M._oc_inspect_actions(), nA);
        put(Float32Array, M._oc_inspect_conns(), M._oc_inspect_conn_count() * 5);
    }
    return h.digest('hex');
}
/* M's world after `steps` more steps (60), fingerprinted: what a setting changes that the first
 * frame does not show (a radius, a gate, a switch that only steers) shows by then */
function stepped(M, steps) { M._oc_step(steps === undefined ? 60 : steps); return fingerprint(M); }
/* the appearance genome rows of this sync, with their count and state */
function appRows(M) {
    M._oc_sync();
    const n = M._oc_appearance_count();
    return { n, flags: M._oc_appearance_flags(), broken: M._oc_appearance_broken(),
             rows: n ? Array.from(new Float32Array(HO.buffer(M), M._oc_creature_appearance(), n * M._oc_appearance_stride())) : [] };
}
/* compare a and b over `steps` further steps, one at a time */
function sameFor(a, b, steps) {
    let fa = fingerprint(a), fb = fingerprint(b);
    if (fa !== fb) return 'differ at frame ' + frame(a) + ' / ' + frame(b);
    for (let s = 0; s < steps; s++) {
        a._oc_step(1); b._oc_step(1);
        fa = fingerprint(a); fb = fingerprint(b);
        if (fa !== fb) return 'differ at frame ' + frame(a) + ' (step ' + (s + 1) + ' after the hand-off)';
    }
    return '';
}

/* main's takeMemory (web/ocean.js / web/ocean_worker.js at 9a351d8), for the record */
function legacyTake(M, src) {
    const heap = () => HO.buffer(M);
    const need = src.byteLength, have = heap().byteLength;
    if (have < need) {
        const p = M._malloc(need - have + 65536);
        if (p) M._free(p);
        if (heap().byteLength < need) throw new Error('could not grow the memory to ' + need + ' bytes');
    }
    const dst = new Uint8Array(heap());
    dst.set(new Uint8Array(src));
    if (dst.length > need) dst.fill(0, need);
}
function throws(fn) { try { fn(); return ''; } catch (e) { return String(e && e.message || e); } }

/* main's Turbo recovery (web/ocean.js turboFailed / turboBack / flushHeld at
 * fb976b2), for the record: the live keys where runCfg differs from the
 * entry config, in object-key order, skipping held keys; then every
 * unanswered edit copied over the held ones; then all of it in key order */
function legacyRecovery(runCfg, entryCfg, held, inflight) {
    const heldLive = Object.assign({}, held);
    if (runCfg) Object.keys(Object.assign({}, runCfg, entryCfg)).forEach(k => {
        const a = Object.prototype.hasOwnProperty.call(runCfg, k) ? runCfg[k] : CFG.KEYS[k] && CFG.KEYS[k][0];
        const b = Object.prototype.hasOwnProperty.call(entryCfg, k) ? entryCfg[k] : CFG.KEYS[k] && CFG.KEYS[k][0];
        if (CFG.LIVE[k] && a !== b && !(k in heldLive)) heldLive[k] = a;
    });
    inflight.forEach(([k, v]) => { heldLive[k] = v; });
    return Object.keys(heldLive).map(k => [k, heldLive[k]]);
}
/* the page's liveApplied: runCfg keeps what differs from the default */
function liveApplied(runCfg, key, v) { if (v === CFG.KEYS[key][0]) delete runCfg[key]; else runCfg[key] = v; }
/* the page's replayEdits (web/ocean.js) of a ledger plan on its own world: each
 * edit with oc_set_param, in order; runCfg follows what is accepted */
function replayOnPage(M, plan, runCfg) {
    return plan.map(e => {
        const r = HO.withCString(M, e.key, p => M._oc_set_param(p, e.num));
        if (r) liveApplied(runCfg, e.key, e.num);
        return r ? '' : e.key + ' ' + e.num + ': ' + HO.cString(M, M._oc_last_error());
    });
}
/* a worker whose oc_step traps on its `at`th chunk (its world is lost) */
function trapAt(w, at) {
    const real = w.M._oc_step;
    let k = 0;
    w.M._oc_step = function (s) { if (++k === at) throw new WebAssembly.RuntimeError('injected: a trap mid-step'); return real(s); };
}

/* web/ocean_worker.js in a vm context: a dedicated worker's globals, its
 * MessageChannel a macrotask per message (as in a browser), importScripts
 * loading ocean_handoff.js into the context and handing it the module factory.
 * opts.out: where its messages go instead of the inbox (the page's Worker
 * below); kill(): terminated, it neither runs nor posts again. */
function makeWorker(opts) {
    const inbox = [], waiters = [], out = opts && opts.out;
    let dead = false;
    function Chan() {
        const p1 = { onmessage: null };
        this.port1 = p1;
        this.port2 = { postMessage: d => setImmediate(() => { if (!dead && p1.onmessage) p1.onmessage({ data: d }); }) };
    }
    const ctx = {
        console, performance, setTimeout, clearTimeout, TextEncoder, TextDecoder, WebAssembly,
        MessageChannel: Chan, onmessage: null,
        postMessage: (m) => { if (dead) return; if (out) { out(m); return; } inbox.push(m); pump(); }
    };
    ctx.self = ctx;
    ctx.importScripts = function () {
        for (const u of arguments) {
            if (/ocean_handoff\.js$/.test(u)) vm.runInContext(fs.readFileSync(u, 'utf8'), ctx, { filename: u });
            else if (/evo_ocean\.js$/.test(u)) ctx.createEvoOcean = create;
            else throw new Error('importScripts: ' + u);
        }
    };
    vm.createContext(ctx);
    const src = path.join(WEB, 'ocean_worker.js');
    vm.runInContext(fs.readFileSync(src, 'utf8'), ctx, { filename: src });
    function pump() {
        for (let w = 0; w < waiters.length; w++) {
            const i = inbox.findIndex(waiters[w].pred);
            if (i < 0) continue;
            const m = inbox[i];
            /* drop the stats and samples before it: a later wait wants later ones */
            for (let j = i; j >= 0; j--) if (j === i || inbox[j].type === 'stats') inbox.splice(j, 1);
            const wt = waiters.splice(w, 1)[0];
            clearTimeout(wt.timer);
            wt.resolve(m);
            w--;
        }
    }
    return {
        ctx,
        get M() { return ctx.M; },
        send(m) { setImmediate(() => { if (!dead) ctx.onmessage({ data: m }); }); },
        kill() { dead = true; },
        wait(pred, what, ms) {
            return new Promise((resolve, reject) => {
                const wt = { pred, resolve };
                wt.timer = setTimeout(() => {
                    waiters.splice(waiters.indexOf(wt), 1);
                    reject(new Error('timed out waiting for ' + what + '; inbox: ' +
                                     inbox.map(m => m.type + (m.message ? '(' + m.message + ')' : '')).join(',')));
                }, ms || 20000);
                waiters.push(wt);
                pump();
            });
        },
        rows() { const r = []; for (let i = inbox.length - 1; i >= 0; i--) if (inbox[i].type === 'rec') r.unshift(...inbox.splice(i, 1)[0].rows); return r; },
        errors() { return inbox.filter(m => m.type === 'error'); }
    };
}
const startMsg = (mem) => ({ cmd: 'start', js: path.join(WEB, 'evo_ocean.js'), wasm: WASM,
                             handoff: path.join(WEB, 'ocean_handoff.js'), mem, recEvery: 60, famK: 8 });
const isType = (t) => (m) => m.type === t;
const statsAt = (f) => (m) => m.type === 'stats' && m.frame >= f;

/* ---------------------------------------------------------------------
 * The page itself. web/ui_common.js, web/ocean_handoff.js, web/ocean_config.js,
 * web/ocean_dash.js and web/ocean.js, as they are and in ocean.html's order,
 * in one vm context over a small DOM: the elements ocean.html declares (made
 * on first use) and the ones the page makes, events that bubble, listeners
 * whose exceptions are reported, not thrown (as a browser's). The real
 * module (a fresh instance per page, its oc_init / oc_set_param calls
 * logged) and the real worker (makeWorker) behind the page's Worker, whose
 * messages to the page can be held and let through in their order (a slow
 * channel, as a busy page or worker makes it). Stubs only where the page
 * draws (the 3-D scene, the charts) and schedules (requestAnimationFrame:
 * the test runs a frame when it wants one). The page's lexical state is
 * read through an accessor appended inside its closure (__oceanPage), with
 * its start-up's URL-import block, a verbatim slice, as a function of the
 * query (urlImport); each marker must occur exactly once.
 * --------------------------------------------------------------------- */
const PAGE_IDS = (() => {   /* id -> {tag, type, href}: ocean.html's elements, as the page finds them */
    const m = new Map(), html = fs.readFileSync(path.join(WEB, 'ocean.html'), 'utf8');
    for (const x of html.matchAll(/<([a-zA-Z][\w-]*)\b([^>]*)>/g)) {
        const id = /\sid="([^"]+)"/.exec(x[2]);
        if (!id || m.has(id[1])) continue;
        const type = /\stype="([^"]+)"/.exec(x[2]), href = /\shref="([^"]+)"/.exec(x[2]);
        m.set(id[1], { tag: x[1], type: type ? type[1] : '', href: href ? new URL(href[1], 'http://ocean.test/ocean.html').href : null, colours: [] });
    }
    /* the View menu's colour buttons (their data-c), the one group the page reads by its children */
    const cm = /<span id="colourMode"[^>]*>([\s\S]*?)<\/span>/.exec(html);
    if (cm && m.has('colourMode')) m.get('colourMode').colours = [...cm[1].matchAll(/data-c="([^"]+)"/g)].map(x => x[1]);
    return m;
})();
function onceIn(src, marker, file) {
    const i = src.indexOf(marker);
    if (i < 0 || src.indexOf(marker, i + 1) >= 0) throw new Error(file + ': ' + JSON.stringify(marker) + ' is not there exactly once');
    return i;
}
const PAGE_SRC = (() => {
    const src = fs.readFileSync(path.join(WEB, 'ocean.js'), 'utf8');
    const a = onceIn(src, '    var rawCfg = P.get("cfg") || ""', 'web/ocean.js');
    const b = onceIn(src, '    scene = EvoOceanScene.create(canvas, {', 'web/ocean.js');
    const end = onceIn(src, '\n})();\n', 'web/ocean.js');
    if (!(a < b && b < end)) throw new Error('web/ocean.js: the markers are out of order');
    const access = '\n  globalThis.__oceanPage = {\n' +
        '    get M() { return M; }, get turboState() { return turboState; }, get turboWorker() { return turboWorker; },\n' +
        '    get runCfg() { return runCfg; }, get initArgs() { return initArgs; }, get live() { return live; },\n' +
        '    get W() { return W; }, get H() { return H; }, get D() { return D; }, get WALLS() { return WALLS; },\n' +
        '    get paused() { return paused; }, get openPop() { return openPop; }, get statOpen() { return statOpen; },\n' +
        /* (typeof: a page from before UI-4 / UI-3 has none of these, so the new sections run against it and fail, not throw) */
        '    get worldEpoch() { return worldEpoch; }, get pendingStart() { return typeof pendingStart === "undefined" ? null : pendingStart; },\n' +
        '    get asking() { return typeof asking === "undefined" ? null : asking; },\n' +
        '    get usedTurbo() { return typeof usedTurbo === "undefined" ? null : usedTurbo; }, get turboStats() { return turboStats; },\n' +
        '    get turboReturn() { return typeof turboReturn === "undefined" ? null : turboReturn; },\n' +
        '    set turboReturn(v) { if (typeof turboReturn !== "undefined") turboReturn = v; },\n' +
        '    get lastS() { return fresh(lastS); }, inspect: inspect,\n' +
        '    get draft() { return typeof draft === "undefined" ? null : draft; }, get draftGen() { return typeof draftGen === "undefined" ? 0 : draftGen; },\n' +
        '    pendingDiff: typeof pendingDiff === "function" ? pendingDiff : function () { return []; }, readForm: readForm,\n' +
        '    getVal: getVal, importWorld: importWorld, wiringNow: wiringNow, frame: frame,\n' +
        '    get worldSave() { return typeof worldSave === "undefined" ? null : worldSave; }, get selectedId() { return selectedId; },\n' +
        '    get engineState() { return typeof engineState === "undefined" ? null : engineState; },\n' +
        '    get filesRead() { return typeof filesRead === "undefined" ? null : filesRead; }, get fileReq() { return fileReq; },\n' +
        '    answered: function (id) { return typeof fileAnswered === "undefined" ? null : fileAnswered.indexOf(id) >= 0; },\n' +
        '    get rebuilds() { return typeof rebuilds === "undefined" ? 0 : rebuilds; }, get pinned() { return typeof pinned === "undefined" ? null : pinned; },\n' +
        '    urlImport: function (P) {\n' + src.slice(a, b) + '    }\n  };';
    return src.slice(0, end) + access + src.slice(end);
})();
/* the scene: fixed answers, but the skin it was last told to draw (setAppearance -> appearance().skin), and a
 * follow and a flashlight with state: setFollow tells the page (onFollowChange) as ocean_scene.js does, at once */
const SCENE_STUB = `window.EvoOceanScene = { load: function () { return Promise.resolve(); }, create: function (canvas, opts) {
  var fixed = { following: false, flashlight: false, quality: 3, flashlightLevel: 0, pick: -1, project: null, view: null, degrade: false,
                appearance: { want: false, skin: false, shapes: true, drawing: false } };
  return new Proxy({}, { get: function (t, k) {
    if (k === "setAppearance") return function (on) { fixed.appearance = { want: !!on, skin: !!on, shapes: true, drawing: !!on }; };
    if (k === "setFollow") return function (on) {
      on = !!on;
      if (on === fixed.following) return;
      fixed.following = on;
      if (opts && opts.onFollowChange) opts.onFollowChange(on);
    };
    if (k === "resetView") return function () { if (fixed.following) { fixed.following = false; if (opts && opts.onFollowChange) opts.onFollowChange(false); } };
    if (k === "setFlashlight") return function (on) { fixed.flashlight = !!on; };
    return function () { return fixed[k]; };
  } });
} };`;
/* a browser whose WebGL2 context can't be made: ocean_scene.js's create() returns null */
const SCENE_NOGL = `window.EvoOceanScene = { load: function () { return Promise.resolve(); }, create: function () { return null; } };`;
const CHARTS_STUB = `(function () {
  var charts = [];
  function Chart(box, kind) { this.box = box; this.kind = kind; this.data = undefined; charts.push(this); }
  Chart.prototype.draw = function (d) { this.data = d; };
  window.EvoCharts = { T: { series: ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8"], other: "#9" }, Chart: Chart,
    lines: "lines", stack: "stack", phase: "phase", heat: "heat", legend: function () {}, tip: function () {},
    seq: function () { return "#0"; }, esc: function (s) { return String(s); }, tipRow: function () { return ""; },
    fmtTime: function (s) { return s + " s"; }, charts: charts };
})();`;

function makeDom(page) {
    const byId = new Map();
    const parse = (s) => {
        const m = /^([a-zA-Z][\w-]*)?((?:[#.][\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/.exec(s);
        if (!m) throw new Error('the test DOM has no selector ' + JSON.stringify(s));
        const parts = m[2].match(/[#.][\w-]+|\[[^\]]+\]/g) || [];
        return { tag: (m[1] || '').toUpperCase(), id: (parts.find(x => x[0] === '#') || '#').slice(1),
                 cls: parts.filter(x => x[0] === '.').map(x => x.slice(1)),
                 attrs: parts.filter(x => x[0] === '[').map(x => { const a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(x); return [a[1], a[2]]; }) };
    };
    /* an attribute: data-* from the dataset (the page sets those as properties) */
    const attrOf = (e, k) => k.startsWith('data-') ? (e.dataset[k.slice(5).replace(/-(\w)/g, (x, c) => c.toUpperCase())] ?? null) : e.getAttribute(k);
    const one = (e, p) => (!p.tag || e.tagName === p.tag) && (!p.id || e._id === p.id) && p.cls.every(c => e._cls.has(c)) &&
                          p.attrs.every(([k, v]) => { const a = attrOf(e, k); return v === undefined ? a !== null : a === v; });
    const matches = (e, sel) => sel.split(',').some(alt => {
        const chain = alt.trim().split(/\s+/).map(parse);
        if (!one(e, chain[chain.length - 1])) return false;
        let k = chain.length - 2;
        for (let n = e.parentNode; n && k >= 0; n = n.parentNode) if (one(n, chain[k])) k--;
        return k < 0;
    });
    function* walk(e) { for (const c of e.children) { yield c; yield* walk(c); } }
    /* type: the listener list (a window's capture listeners are "keydown:capture") */
    function fireOn(n, ev, type) {
        ev.currentTarget = n;
        for (const f of (n._ls[type || ev.type] || []).slice()) {
            try { f.call(n, ev); } catch (e) { page.uncaught.push(e); }   /* a browser reports it and goes on */
        }
    }
    class Ev {
        constructor(type, o) { this.type = type; this.bubbles = !!(o && o.bubbles); this.defaultPrevented = false; this.target = null; }
        preventDefault() { this.defaultPrevented = true; }
        stopPropagation() { this.stopped = true; }
    }
    const ctx2d = new Proxy({}, { get: (t, k) => (k in t ? t[k] : k === 'measureText' ? () => ({ width: 0 }) : () => {}),
                                  set: (t, k, v) => { t[k] = v; return true; } });
    let head = null;
    class El {
        constructor(tag) {
            this.tagName = this.nodeName = String(tag).toUpperCase();
            this.children = []; this.parentNode = null; this.dataset = {}; this.attrs = {};
            this.style = Object.defineProperties({}, {   /* custom properties (the Turbo coach's --arrow-x) */
                setProperty: { value(k, v) { this[k] = String(v); } }, removeProperty: { value(k) { delete this[k]; } } });
            this._cls = new Set(); this._ls = {}; this._id = ''; this._text = ''; this._html = ''; this._auto = false;
            this.hidden = false; this.disabled = false; this.checked = false; this.value = ''; this.type = '';
            this.width = 0; this.height = 0; this.tabIndex = 0; this.scrollTop = 0;
        }
        get id() { return this._id; }
        set id(v) { this._id = String(v); byId.set(this._id, this); }
        get className() { return Array.from(this._cls).join(' '); }
        set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
        get classList() {
            const s = this._cls;
            return { add: (...c) => c.forEach(x => s.add(x)), remove: (...c) => c.forEach(x => s.delete(x)),
                     toggle: (c, on) => { if (on === undefined) on = !s.has(c); if (on) s.add(c); else s.delete(c); return !!on; },
                     contains: c => s.has(c) };
        }
        get textContent() { return this._text; }
        set textContent(v) { for (const c of this.children) c.parentNode = null; this.children = []; this._text = String(v); this._html = ''; }
        get innerHTML() { return this._html; }
        set innerHTML(v) {   /* the elements in it, flat (the page reads them by id, class or tag) */
            v = String(v);
            for (const c of this.children) c.parentNode = null;
            this.children = []; this._html = v; this._text = v.replace(/<[^>]*>/g, '');
            for (const m of v.matchAll(/<([a-zA-Z][\w-]*)([^>]*)>/g)) {
                const c = new El(m[1]), cl = /\sclass=(['"])(.*?)\1/.exec(m[2]), id = /\sid=(['"])(.*?)\1/.exec(m[2]);
                if (cl) c.className = cl[2];
                if (id) c.id = id[2];
                this.appendChild(c);
            }
        }
        get firstChild() { return this.firstElementChild; }
        get firstElementChild() {
            if (!this.children.length && this._auto) this.appendChild(new El('i'));   /* ocean.html's own child */
            return this.children[0] || null;
        }
        get parentElement() { return this.parentNode; }
        get offsetWidth() { return 0; } get offsetHeight() { return 0; } get clientWidth() { return 0; } get clientHeight() { return 0; }
        appendChild(c) {
            if (c.parentNode) c.parentNode.removeChild(c);
            c.parentNode = this;
            this.children.push(c);
            if (this === head && c.tagName === 'SCRIPT') page.onScript(c);
            return c;
        }
        removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
        remove() { if (this.parentNode) this.parentNode.removeChild(this); }
        setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = v; else if (k === 'class') this.className = v; }
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
        removeAttribute(k) { delete this.attrs[k]; }
        addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }
        removeEventListener(t, f) { const l = this._ls[t] || [], i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
        dispatchEvent(ev) {
            if (!ev.target) ev.target = this;
            for (let n = this; n; n = ev.bubbles && !ev.stopped ? n.parentNode : null) fireOn(n, ev);
            return !ev.defaultPrevented;
        }
        click() {   /* a disabled control can't be pressed; a link with a download saves its file (page.downloads) */
            if (this.disabled) return;
            if (this.tagName === 'A' && this.download) page.downloads.push({ name: this.download, href: this.href });
            this.dispatchEvent(new Ev('click', { bubbles: true }));
        }
        focus() { doc.activeElement = this; }
        blur() { if (doc.activeElement === this) doc.activeElement = null; }
        /* no layout: a zero box, unless a test gives the element one (_rect: {left, top, right, bottom}) */
        getBoundingClientRect() {
            const r = this._rect;
            return r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.right - r.left, height: r.bottom - r.top, x: r.left, y: r.top }
                     : { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 };
        }
        getContext() { return ctx2d; }
        setPointerCapture() {}
        releasePointerCapture() {}
        querySelectorAll(sel) { const out = []; for (const e of walk(this)) if (matches(e, sel)) out.push(e); return out; }
        querySelector(sel) {
            for (const e of walk(this)) if (matches(e, sel)) return e;
            if (!this._auto) return null;
            const p = parse(sel.split(',')[0].trim().split(/\s+/).pop());   /* ocean.html's own child */
            const c = new El(p.tag || 'div');
            if (p.cls.length) c.className = p.cls.join(' ');
            if (p.id) c.id = p.id;
            c._auto = true;
            return this.appendChild(c);
        }
        closest(sel) { for (let n = this; n; n = n.parentNode) if (matches(n, sel)) return n; return null; }
        /* :focus-visible: focused while the keyboard is in use (page.key / page.tabTo; a click, page.pointer, ends it) */
        matches(sel) { return sel === ':focus-visible' ? doc.activeElement === this && !!page.focusVisible : matches(this, sel); }
        contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
        get isConnected() { return docEl.contains(this); }
        scrollIntoView() {}
    }
    const docEl = new El('html'), body = new El('body');
    head = new El('head');
    docEl.appendChild(head); docEl.appendChild(body);
    const doc = {
        documentElement: docEl, head, body, activeElement: null, hidden: false, _ls: {},
        createElement: t => new El(t),
        getElementById(id) {
            let e = byId.get(id);
            if (e && !e.isConnected) e = null;   /* removed (the tour's root once it ends) */
            if (!e && PAGE_IDS.has(id)) {
                const d = PAGE_IDS.get(id);
                e = new El(d.tag); e._auto = true; e.id = id;
                if (d.type) e.type = d.type;
                if (d.href !== null) e.href = d.href;
                for (const c of d.colours) {   /* #colourMode's buttons */
                    const b = new El('button'); b.type = 'button'; b.dataset.c = c; b.setAttribute('aria-pressed', 'false'); e.appendChild(b);
                }
                body.appendChild(e);
            }
            return e || null;
        },
        querySelector: s => docEl.querySelector(s),
        querySelectorAll: s => docEl.querySelectorAll(s),
        addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); },
        removeEventListener() {},
        dispatchEvent(ev) { fireOn(doc, ev); return true; }
    };
    return { doc, Ev, fireOn };
}

const tick = () => new Promise(r => setImmediate(r));
async function until(pred, what, ms) {
    const t0 = Date.now();
    while (!pred()) {
        if (Date.now() - t0 > (ms || 30000)) throw new Error('timed out waiting for ' + what);
        await new Promise(r => setTimeout(r, 2));
    }
}
const unref = (t) => { if (t && t.unref) t.unref(); return t; };

/* A page at ocean.html?query, started (or refused: page.failed). opts: perf
 * (web/ocean_perf.js loaded, as ocean.html loads it), guide (web/guide.js
 * after ocean.js, as ocean.html), nogl (no WebGL2: the scene can't be made),
 * nosimd (WebAssembly without SIMD), media {query: true} (matchMedia; every
 * other query false; page.setMedia changes one and tells its listeners). */
/* every page booted (the runner stops their Turbo workers when their section ends: in node a worker shares the
 * one event loop, and one left running slows every section after it) */
const PAGES = [];
/* The engine file a module of the page (or one of its workers) instantiates, from the wasm URL the page's
 * locateFile gives: the page pins the bytes it fetched as a Blob URL (web/ocean.js pinEngine), whose bytes
 * are written to a file of their own unless they are the real module's; a page that pins nothing (an http
 * URL: main's) gets the file on disk. page.loads: what each instance got. */
async function wasmFile(page, url) {
    if (!url || !/^blob:/.test(url)) { page.loads.push({ url, sha: null }); return WASM; }
    if (!page.pinnedFiles.has(url)) {
        const blob = resolveObjectURL(url);
        if (!blob) throw new Error('createEvoOcean: an unknown Blob URL ' + url);
        const bytes = Buffer.from(await blob.arrayBuffer()), sha = crypto.createHash('sha256').update(bytes).digest('hex');
        let file = WASM;
        if (sha !== WASM_SHA) { file = path.join(os.tmpdir(), 'ocean_pinned_' + sha.slice(0, 16) + '.wasm'); fs.writeFileSync(file, bytes); }
        page.pinnedFiles.set(url, { file, sha, type: blob.type });
    }
    const p = page.pinnedFiles.get(url);
    page.loads.push({ url, sha: p.sha, type: p.type });
    return p.file;
}
/* the file a worker's module loads, for the wasm URL in its message (synchronous: the page's own module pinned it first) */
function workerWasm(page, url) {
    if (!/^blob:/.test(String(url))) return WASM;
    const p = page.pinnedFiles.get(url);
    if (!p) throw new Error('a worker given a Blob URL the page never loaded: ' + url);
    return p.file;
}
async function bootPage(query, opts) {
    opts = opts || {};
    const page = { hooks: {}, workers: [], probes: [], uncaught: [], logs: [], inits: [], sets: [], blobs: [], downloads: [], raf: null, focusVisible: false,
                   wasmBytes: WASM_BYTES, wasmFetches: 0, loads: [], pinnedFiles: new Map() };
    PAGES.push(page);
    const { doc, Ev, fireOn } = makeDom(page);
    const loc = {};
    const setLoc = (u) => { const x = new URL(u); Object.assign(loc, { href: x.href, search: x.search, origin: x.origin, protocol: x.protocol, pathname: x.pathname }); };
    setLoc('http://ocean.test/ocean.html' + (query || ''));
    const storage = new Map(), winLs = {}, mqs = new Map();
    const say = (level) => (...a) => page.logs.push([level, a.map(String).join(' ')]);
    /* one MediaQueryList per query, as a browser's: its matches can change, and it tells its listeners */
    const matchMedia = (q) => {
        if (!mqs.has(q)) mqs.set(q, { media: q, matches: !!(opts.media && opts.media[q]), _ls: [],
                                      addEventListener(t, f) { if (t === 'change') this._ls.push(f); }, removeEventListener() {},
                                      addListener(f) { this._ls.push(f); } });
        return mqs.get(q);
    };
    const wasm = opts.nosimd ? Object.assign(Object.create(WebAssembly), { validate: () => false }) : WebAssembly;
    const ctx = {
        /* opts.deviceMemory: navigator.deviceMemory (Chrome's GB; none: a browser that doesn't say) */
        document: doc, location: loc, navigator: Object.assign({ userAgent: 'node' }, opts.deviceMemory ? { deviceMemory: opts.deviceMemory } : {}),
        history: { replaceState: (s, t, u) => setLoc(String(u)) },
        localStorage: { getItem: k => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)), removeItem: k => storage.delete(k) },
        matchMedia,
        getComputedStyle: () => ({ fontFamily: 'sans-serif', getPropertyValue: () => '' }),
        requestAnimationFrame: (cb) => { page.raf = cb; return 1; }, cancelAnimationFrame() {},
        innerWidth: 1920, innerHeight: 1080, devicePixelRatio: 1, _ls: winLs,
        /* a capture listener ("keydown:capture") runs before the bubbling ones, as on a browser's window */
        addEventListener: (t, f, o) => { const k = o === true || (o && o.capture) ? t + ':capture' : t; (winLs[k] = winLs[k] || []).push(f); },
        removeEventListener() {},
        dispatchEvent: (ev) => { fireOn(ctx, ev, ev.type + ':capture'); fireOn(ctx, ev); return true; },
        Event: Ev, URL, URLSearchParams, ImageData: class {}, performance, WebAssembly: wasm, TextEncoder, TextDecoder,
        /* Save setup's file (its text) and Save world's (the Blob itself) */
        Blob: function (parts, o) { const b = new Blob(parts, o); page.blobs.push(parts.every(x => typeof x === 'string') ? parts.join('') : b); return b; },
        /* Save world / From a file: the browser's gzip streams and SHA-256 (opts.nocrypto: an insecure context's
         * page, no crypto.subtle; opts.nogzip: a browser without the streams), and fetch for the engine's
         * own wasm (its build: page.wasmBytes, the real file unless a test swaps it) */
        crypto: opts.nocrypto ? undefined : globalThis.crypto,
        CompressionStream: opts.nogzip ? undefined : CompressionStream, DecompressionStream: opts.nogzip ? undefined : DecompressionStream,
        fetch: (u) => {
            if (!/evo_ocean\.wasm$/.test(String(u))) return Promise.resolve({ ok: false, status: 404 });
            page.wasmFetches++;
            return Promise.resolve({ ok: true, status: 200, arrayBuffer: () => Promise.resolve(page.wasmBytes.slice(0)) });
        },
        console: { log: say('log'), info: say('info'), warn: say('warn'), error: say('error'), debug: say('debug') },
        /* hooks.timer(ms): the delay a page's timer really gets (a test shortens a watchdog with it); an
         * exception in a timer is reported, as a browser's (page.uncaught), not node's crash */
        setTimeout: (f, ms) => unref(setTimeout(() => { try { f(); } catch (e) { page.uncaught.push('timer: ' + String(e && e.stack || e)); } },
                                                page.hooks.timer ? page.hooks.timer(ms) : ms)), clearTimeout,
        setInterval: (f, ms) => unref(setInterval(() => { try { f(); } catch (e) { page.uncaught.push('timer: ' + String(e && e.stack || e)); } },
                                                  page.hooks.timer ? page.hooks.timer(ms) : ms)), clearInterval,
        EVO_ASSETS: { ocean: 'evo_ocean.js', oceanWasm: 'evo_ocean.wasm', worker: 'ocean_worker.js', handoff: 'ocean_handoff.js', mock: 'ocean_mock.js' },
        /* a saved world's test run gets a worker of its own (web/ocean.js probeWorld: named "ocean-probe") */
        Worker: function (url, o) { return o && o.name === 'ocean-probe' ? page.newProbe() : page.newWorker(); }
    };
    ctx.window = ctx.self = ctx;
    vm.createContext(ctx);
    /* the module: ocean.html's script tag for it, loaded as the real one, its init and live calls logged */
    page.onScript = (s) => setImmediate(() => {
        if (!/evo_ocean\.js$/.test(s.src)) { if (s.onerror) s.onerror(); return; }
        /* the glue's factory: the wasm the page's locateFile names (wasmFile), every instance's init and live calls logged */
        ctx.createEvoOcean = (o) => wasmFile(page, o && typeof o.locateFile === 'function' ? o.locateFile('evo_ocean.wasm', '') : null)
          .then((file) => create({ locateFile: p => p.endsWith('.wasm') ? file : p })).then((M) => {
            const init = M._oc_init, set = M._oc_set_param;
            M._oc_init = function (seed, w, h, d, pop, p) { page.inits.push(HO.cString(M, p)); return init.apply(this, arguments); };
            M._oc_set_param = function (p, v) {
                const key = HO.cString(M, p), r = set(p, v);
                if (r) page.sets.push([frame(M), key, v]);
                return r;
            };
            return M;
        });
        if (s.onload) s.onload();
    });
    /* the page's Worker: web/ocean_worker.js (makeWorker), its messages to the page through an
     * ordered channel the test can pause (they queue) and let through up to a message (release).
     * Turbo's in page.workers (hooks.onWorker), a saved world's test runs in page.probes (hooks.onProbe);
     * sh.rewrite(m): what the page gets instead of a message (null: nothing) */
    page.newWorker = () => {
        if (page.hooks.ctor) { const h = page.hooks.ctor; page.hooks.ctor = null; h(); }
        return shim(page.workers, 'onWorker');
    };
    page.newProbe = () => shim(page.probes, 'onProbe');
    const shim = (list, hook) => {
        const sh = { onmessage: null, onerror: null, terminated: 0, toWorker: [], fromWorker: [], delivered: [], queue: [], paused: false, rewrite: null };
        /* (an exception in the page's handler is reported, as a browser's, page.uncaught: not node's crash) */
        const deliver = (m) => {
            if (sh.terminated || !sh.onmessage) return;
            sh.delivered.push(m);
            try { sh.onmessage({ data: m }); } catch (e) { page.uncaught.push('worker message: ' + String(e && e.stack || e)); }
        };
        const w = makeWorker({ out: (m) => {
            if (sh.terminated) return;
            if (sh.rewrite) m = sh.rewrite(m);
            if (!m) return;
            sh.fromWorker.push(m);
            if (sh.paused) sh.queue.push(m); else setImmediate(() => deliver(m));
        } });
        Object.defineProperty(sh, 'M', { get: () => w.M });
        sh.postMessage = (msg) => {
            if (msg && msg.cmd === 'start' && page.hooks.post) { const h = page.hooks.post; page.hooks.post = null; h(); }
            if (sh.terminated) return;
            sh.toWorker.push(msg);
            /* a message that loads the module (start, probe): the scripts from web/, the wasm the page pinned */
            w.send(msg.js === undefined ? msg : Object.assign({}, msg, { js: path.join(WEB, 'evo_ocean.js'), wasm: workerWasm(page, msg.wasm),
                                                                          handoff: path.join(WEB, 'ocean_handoff.js') }));
        };
        sh.terminate = () => { sh.terminated++; w.kill(); };
        sh.pause = () => { sh.paused = true; };
        sh.resume = () => { sh.paused = false; for (const m of sh.queue.splice(0)) deliver(m); };
        sh.queued = (pred) => sh.queue.some(pred);
        sh.release = async (pred, what) => {   /* everything queued up to and with the first message pred takes */
            await until(() => sh.queue.some(pred), what || 'a queued message');
            while (sh.queue.length) { const m = sh.queue.shift(); deliver(m); if (pred(m)) return m; }
            return null;
        };
        list.push(sh);
        if (page.hooks[hook]) page.hooks[hook](sh);
        return sh;
    };
    const run = (name, src) => vm.runInContext(src !== undefined ? src : fs.readFileSync(path.join(WEB, name), 'utf8'), ctx, { filename: path.join(WEB, name) });
    run('ui_common.js'); run('ocean_handoff.js');
    if (opts.perf) run('ocean_perf.js');
    run('ocean_scene_stub.js', opts.nogl ? SCENE_NOGL : SCENE_STUB); run('ocean_config.js');
    run('charts_stub.js', CHARTS_STUB); run('ocean_dash.js'); run('ocean.js', PAGE_SRC);
    if (opts.guide) run('guide.js');
    page.ctx = ctx; page.doc = doc; page.Ev = Ev; page.T = ctx.__oceanPage; page.KEYS = ctx.EvoOceanConfig.KEYS;
    page.el = (id) => doc.getElementById(id);
    page.shown = (id) => { const e = page.el(id); return !!e && !e.hidden; };
    page.setMedia = (q, on) => { const m = matchMedia(q); if (m.matches === on) return; m.matches = on; for (const f of m._ls.slice()) f.call(m, { matches: on, media: q }); };
    /* the window at w x h: the wide layout's query from 960 px (ocean.js wideMQ), then a resize */
    page.resize = (w, h) => {
        ctx.innerWidth = w; ctx.innerHeight = h;
        page.setMedia('(min-width: 960px)', w >= 960);
        ctx.dispatchEvent(new Ev('resize'));
    };
    /* the keyboard: focus moved by Tab (its ring showing) */
    page.tabTo = (id) => { page.focusVisible = true; page.el(id).focus(); };
    /* a pointer's press: no focus ring */
    page.pointer = () => { page.focusVisible = false; };
    /* a key pressed where the focus is (else on the body), as a browser dispatches it: the
     * window's capture listeners, the target and its ancestors, the document, the window; then,
     * not prevented, what the focused control does itself: Enter or Space presses a button,
     * Space turns a switch */
    page.key = (key, o) => {
        o = o || {};
        page.focusVisible = true;
        const t = doc.activeElement || doc.body, ev = new Ev('keydown', { bubbles: true });
        Object.assign(ev, { key, code: o.code || (/^[a-z]$/i.test(key) ? 'Key' + key.toUpperCase() : key === ' ' ? 'Space' : ''),
                            shiftKey: !!o.shift, ctrlKey: false, metaKey: false, altKey: false, repeat: false, target: t });
        fireOn(ctx, ev, 'keydown:capture');
        for (let n = t; n && !ev.stopped; n = n.parentNode) fireOn(n, ev);
        fireOn(doc, ev);
        fireOn(ctx, ev);
        if (ev.defaultPrevented) return ev;
        if (t.tagName === 'BUTTON' && (key === 'Enter' || key === ' ')) t.click();
        else if (t.tagName === 'INPUT' && t.type === 'checkbox' && key === ' ') {
            t.checked = !t.checked;
            t.dispatchEvent(new Ev('input', { bubbles: true }));
            t.dispatchEvent(new Ev('change', { bubbles: true }));
        }
        return ev;
    };
    /* run the queued animation frames until p settles (EvoOcean.bench's frames(); the page's loop) */
    page.pump = async (p) => {
        let done = false;
        p.then(() => { done = true; }, () => { done = true; });
        while (!done) { const cb = page.raf; page.raf = null; if (cb) cb(performance.now()); await tick(); }
        return p;
    };
    await until(() => (ctx.EvoApp && ctx.EvoApp.ready) || page.el('splashstate').className === 'error', 'the page to start', 60000);
    page.failed = page.el('splashstate').className === 'error' ? page.el('splashstate').textContent : '';
    page.M = page.T.M;
    page.click = (id) => page.el(id).click();
    /* Start, and Replace it when the page asks (a run with a live tweak, Turbo used, 5 minutes): for the tests about what starts, not whether */
    page.start = () => { page.click('restart'); if (page.T.asking) page.click('startconfirm'); };
    page.msg = () => page.el('err').textContent;
    page.worker = () => page.workers[page.workers.length - 1];
    /* a field changed by hand: its input, then its change (the live ones apply on change) */
    page.edit = (key, v) => {
        const i = page.el('o_' + key);
        if (i.type === 'checkbox') i.checked = v === true || v === 1; else i.value = String(v);
        i.dispatchEvent(new Ev('input', { bubbles: true }));
        i.dispatchEvent(new Ev('change', { bubbles: true }));
    };
    page.note = (key) => { const r = page.el('f_' + key), n = r && r.querySelector('.pendnote'); return n ? n.textContent : ''; };
    page.form = () => JSON.stringify(Object.keys(page.KEYS).filter(k => page.el('o_' + k)).map(k => [k, page.T.getVal(k)]));
    /* Load setup's file input, given a file */
    page.loadFile = (file) => { const i = page.el('cpfile'); i.files = [file]; i.dispatchEvent(new Ev('change', { bubbles: true })); };
    /* UI-3: a setup file stages (it starts nothing); then Start. The answer: the file's refusal, or the start's */
    page.loadSetup = async (text) => {
        page.el('err').textContent = '';
        const g = page.T.draftGen;
        page.loadFile({ name: 'setup.json', text: () => Promise.resolve(text) });
        await until(() => page.T.draftGen !== g || page.msg() !== '' || page.T.asking, 'the setup\'s answer');
        if (page.T.asking && page.T.asking.replace) page.click('startconfirm');   /* it replaces edits that waited: Replace */
        if (page.T.draft && page.T.draft.kind === 'file' && page.T.draftGen !== g) { page.el('err').textContent = ''; page.start(); }
        return page.msg();
    };
    page.state = () => JSON.stringify({ initArgs: page.T.initArgs, runCfg: page.T.runCfg, W: page.T.W, H: page.T.H, D: page.T.D,
                                        walls: page.T.WALLS, url: loc.href, form: page.form() });
    /* the running world and the address, not the sheet (UI-3: a setup file the engine refuses stays staged in the sheet, to be fixed) */
    page.world = () => JSON.stringify({ initArgs: page.T.initArgs, runCfg: page.T.runCfg, W: page.T.W, H: page.T.H, D: page.T.D,
                                        walls: page.T.WALLS, url: loc.href });
    page.loc = loc;
    return page;
}
/* the Turbo controls, as they read: off ("live") or on (card: the dock's Turbo strip, which replaced the card) */
function turboControls(p) {
    const locked = ['restart', 'savecp', 'loadcp', 'pausebtn', 'slower', 'faster', 'stepbtn', 'randombig', 'newworld', 'replay']
        .filter(id => p.el(id).classList.contains('locked'));
    return { card: !p.el('turbo-strip').hidden || p.doc.body.classList.contains('turbo-on'), button: !p.el('turbobtn').disabled, locked };
}
/* the page's mode as it reads (UI-4): the state, the readout's badge, the dimmed tank, the strip and the two bars, Stop */
const modeOf = (p) => ({ state: p.T.turboState, rs: p.el('runstate').dataset.s, on: p.doc.body.classList.contains('turbo-on'),
                         strip: !p.el('turbo-strip').hidden, setup: !p.el('setup-turbo').hidden, dash: !p.el('dash-turbo').hidden,
                         stop: !p.el('turboexit').disabled });
const toastText = (p) => p.el('toasts').children.map(c => c.textContent).join(' | ');
/* a world like the page's from an image of its memory (the control's start),
 * edits [frame, key, value] applied at their frames, stepped to toFrame */
async function controlRun(img, edits, toFrame) {
    const ref = await mk(1, {}, 300, 300, 0);
    HO.take(ref, img.slice(0), 'the control');
    for (const [f, key, v] of edits) {
        if (f < frame(ref)) throw new Error('control: an edit at frame ' + f + ' before ' + frame(ref));
        ref._oc_step(f - frame(ref)); setParam(ref, key, v);
    }
    if (toFrame < frame(ref)) throw new Error('control: frame ' + toFrame + ' before ' + frame(ref));
    ref._oc_step(toFrame - frame(ref));
    return ref;
}
/* the edits a page's worker applied: [frame, key, value] */
const workerEdits = (sh) => sh.fromWorker.filter(m => m.type === 'set' && m.ok).map(m => [m.frame, m.key, m.value]);
/* the worker's next oc_step traps (its world is lost: no memory comes with the error) */
function trapNext(sh) { sh.M._oc_step = function () { throw new WebAssembly.RuntimeError('injected: a trap mid-step'); }; }
const PAGE_Q = '?seed=4242&pop=60&w=1920&h=1080&walls=1';
/* a page in Turbo, its world's image and frame from just before */
async function pageInTurbo(q) {
    const p = await bootPage(q || PAGE_Q);
    const img = HO.buffer(p.M).slice(0), f0 = frame(p.M), sets0 = p.sets.length;
    p.click('turbobtn');
    await until(() => p.T.turboState === 'turbo', 'Turbo to start');
    const sh = p.worker();
    await until(() => sh.fromWorker.some(m => m.type === 'stats' && m.frame >= f0 + 120), 'Turbo to run a while');
    return { p, img, f0, sets0, sh };
}

/* --------------------------------------------------------------------- */
async function roundTrip(label, cfg) {
    section('Round trip, live edits, unequal memories both ways: ' + label);
    const SEED = 20261029;
    const edits = [];   /* [frame, key, value]: replayed on the reference */
    const page = await mk(SEED, cfg);
    /* the page grew once (a big allocation, freed): a big memory, mostly free */
    const p = page._malloc(40 * MB); page._free(p);
    page._oc_step(150);
    setParam(page, 'foodEnergy', 7); edits.push([frame(page), 'foodEnergy', 7]);
    page._oc_step(90);
    const entryFrame = frame(page), entryPrint = fingerprint(page);
    const imgA = HO.buffer(page).slice(0);
    console.log('  page ' + memMB(page) + ' MiB at frame ' + entryFrame + ' -> a fresh worker');
    {   /* main's code on the same image, into a fresh module like the worker's */
        const fresh = await mk(1);
        const err = throws(() => legacyTake(fresh, imgA));
        ok(err !== '', 'main\'s takeMemory fails page -> worker (' + (err || 'it did not') + ')');
    }
    const w = makeWorker();
    w.send(startMsg(imgA));
    const first = await w.wait(isType('stats'), 'the first stats');
    ok(first.frame === entryFrame, 'the worker took the page\'s world (frame ' + first.frame + ')');
    ok(+memMB(w.M) >= +(imgA.byteLength / MB).toFixed(2), 'the worker grew to the image exactly (' + memMB(w.M) + ' MiB)');
    /* the module's own views are now stale (a grow from outside), and nothing reads them */
    ok(w.M.HEAPU8.buffer !== w.M.wasmMemory.buffer, 'the module\'s cached HEAPU8 is stale after the grow (why ocean_handoff.js does its own UTF-8)');

    /* growth forced inside every allocating export the worker calls while sampling */
    const W = w.M, realSu = W._oc_summary, realFam = W._oc_families;
    let grown = 0;
    W._oc_summary = function () { if (grown < 2) { growMiB(W); grown++; } return realSu(); };
    W._oc_families = function (k) { if (grown >= 2 && grown < 4) { growMiB(W); grown++; } return realFam(k); };

    w.send({ cmd: 'set', key: 'kBuoy', value: 0.5 });
    const s1 = await w.wait(isType('set'), 'the kBuoy reply');
    ok(s1.ok && s1.frame >= entryFrame, 'kBuoy 0.5 applied in the worker at frame ' + s1.frame);
    edits.push([s1.frame, 'kBuoy', 0.5]);
    w.send({ cmd: 'set', key: 'kBuoy', value: -0.5 });
    const s2 = await w.wait(isType('set'), 'the refused reply');
    ok(!s2.ok && /kBuoy/.test(s2.error), 'a refused live value is answered with the engine\'s reason: "' + s2.error + '"');
    await w.wait(statsAt(s1.frame + 600), 'frame ' + (s1.frame + 600));
    w.send({ cmd: 'set', key: 'maxSpeed', value: 140 });
    const s3 = await w.wait(isType('set'), 'the maxSpeed reply');
    ok(s3.ok, 'maxSpeed 140 applied in the worker at frame ' + s3.frame);
    edits.push([s3.frame, 'maxSpeed', 140]);
    if (cfg.patternMutation === undefined && W._oc_creature_appearance && label !== 'the default world') {
        w.send({ cmd: 'set', key: 'patternMutation', value: 0.1 });   /* an appearance knob, live in Turbo */
        const s4 = await w.wait(isType('set'), 'the patternMutation reply');
        ok(s4.ok, 'patternMutation 0.1 (the appearance genome) applied in the worker at frame ' + s4.frame);
        edits.push([s4.frame, 'patternMutation', 0.1]);
    }
    await w.wait(statsAt(s3.frame + 600), 'frame ' + (s3.frame + 600));
    ok(grown === 4, 'the worker\'s memory grew inside oc_summary and oc_families while sampling (' + grown + ' times, now ' + memMB(W) + ' MiB)');
    const rows = w.rows();
    ok(rows.length > 5 && rows.every(r => r.st.length === 15 && r.su.length === 22 && r.fam.length > 0 && r.st[1] % 60 === 0 &&
                                         r.su.every(Number.isFinite)),
       rows.length + ' dashboard samples arrived whole (stats, summary, family lines; frames on the 60-step grid)');
    W._oc_summary = realSu; W._oc_families = realFam;
    /* the worker now has the bigger memory; the page has lots of free space but less room */
    w.send({ cmd: 'stop' });
    const back = await w.wait(isType('memory'), 'the memory');
    console.log('  worker ' + (back.mem.byteLength / MB).toFixed(2) + ' MiB -> the page (' + memMB(page) + ' MiB, mostly free)');
    ok(back.mem.byteLength > HO.buffer(page).byteLength, 'the image coming back is bigger than the page\'s memory');
    {   /* main's code on the same image, into a module grown and freed as the page's was */
        const twin = await mk(SEED, cfg);
        const q = twin._malloc(40 * MB); twin._free(q);
        const err = throws(() => legacyTake(twin, back.mem));
        ok(err !== '', 'main\'s takeMemory fails worker -> page (' + (err || 'it did not') + ')');
    }
    HO.take(page, back.mem, "the page's");
    const backFrame = frame(page);
    ok(backFrame > s3.frame, 'the page took the world back at frame ' + backFrame + ' (' + back.totalSteps + ' Turbo steps)');
    if (page._oc_creature_appearance) {
        const a = appRows(page), b = appRows(W);   /* the worker, stopped: its world is the image */
        ok(a.n > 0 && a.n === page._oc_creature_count() && !a.broken && a.flags === b.flags && a.n === b.n &&
           a.rows.length === b.rows.length && a.rows.every((v, i) => Object.is(v, b.rows[i])),
           'the appearance genome came across whole: ' + a.n + ' fish x ' + page._oc_appearance_stride() + ' floats, flags ' + a.flags +
           ', bit-identical to the worker\'s, its side array still bound (broken 0)');
    }
    page._oc_step(45);
    setParam(page, 'metabolicRate', 1.6); edits.push([frame(page), 'metabolicRate', 1.6]);
    page._oc_step(15);

    /* the reference: the same world, uninterrupted, the same edits at the same frames */
    const ref = await mk(SEED, cfg);
    for (const [f, key, v] of edits) { ref._oc_step(f - frame(ref)); setParam(ref, key, v); }
    ref._oc_step(frame(page) - frame(ref));
    const diff = sameFor(page, ref, 300);
    ok(diff === '', 'after the round trip, 300 further steps are bit-identical to the uninterrupted run' + (diff ? ': ' + diff : ''));
    ok(w.errors().length === 0, 'no worker errors');
    return { page, entryFrame, entryPrint };
}

async function failures_() {
    section('An exception in a chunk -> recovery -> a second Turbo session');
    const SEED = 777;
    const page = await mk(SEED);
    page._oc_step(120);

    /* (a) a throw outside oc_step: the world is whole and comes back */
    let w = makeWorker();
    w.send(startMsg(HO.buffer(page).slice(0)));
    await w.wait(isType('stats'), 'the first stats');
    const realFam = w.M._oc_families;
    let n = 0;
    w.M._oc_families = function (k) { if (++n === 3) throw new TypeError('injected: a sampling bug'); return realFam(k); };
    const e1 = await w.wait(isType('error'), 'the error');
    ok(!!e1.mem && /injected/.test(e1.message), 'a throw while sampling stops the run with the world attached ("' + e1.message + '")');
    ok(vm.runInContext('running', w.ctx) === false, 'the worker is no longer "running" (main left it true and ignored the next start)');
    HO.take(page, e1.mem, "the page's");
    const f1 = frame(page);
    const ref = await mk(SEED);
    ref._oc_step(f1);
    ok(sameFor(page, ref, 100) === '', 'the world it handed back (frame ' + f1 + ') is the uninterrupted run\'s, bit for bit, 100 steps on');
    /* the same worker again: a start always begins afresh */
    w.M._oc_families = realFam;
    w.send(startMsg(HO.buffer(page).slice(0)));
    const again = await w.wait(isType('stats'), 'stats from the failed worker');
    ok(again.frame === frame(page), 'the failed worker takes a new start (no wedge)');
    w.send({ cmd: 'stop' });
    const m2 = await w.wait(isType('memory'), 'its memory');
    HO.take(page, m2.mem, "the page's");
    ref._oc_step(frame(page) - frame(ref));
    ok(sameFor(page, ref, 50) === '', 'and its round trip is bit-identical (frame ' + frame(page) + ')');

    /* (b) a throw out of oc_step: nothing of the worker's world is trusted */
    w = makeWorker();
    const before = frame(page), beforePrint = fingerprint(page);
    w.send(startMsg(HO.buffer(page).slice(0)));
    await w.wait(isType('stats'), 'the first stats');
    const realStep = w.M._oc_step;
    let k = 0;
    w.M._oc_step = function (s) { if (++k === 4) throw new WebAssembly.RuntimeError('injected: a trap mid-step'); return realStep(s); };
    const e2 = await w.wait(isType('error'), 'the error');
    ok(!e2.mem, 'a throw out of oc_step stops the run without a world ("' + e2.message + '")');
    ok(frame(page) === before && fingerprint(page) === beforePrint, 'the page still has its own copy, as Turbo took it (frame ' + before + ')');

    /* (c) a fresh worker: the second session works and round-trips exactly */
    w = makeWorker();
    w.send(startMsg(HO.buffer(page).slice(0)));
    const st = await w.wait(isType('stats'), 'stats');
    await w.wait(statsAt(st.frame + 400), 'progress');
    w.send({ cmd: 'stop' });
    const m3 = await w.wait(isType('memory'), 'the memory');
    HO.take(page, m3.mem, "the page's");
    ref._oc_step(frame(page) - frame(ref));
    ok(sameFor(page, ref, 100) === '', 'a second Turbo session in a fresh worker round-trips bit-identically (frame ' + frame(page) + ')');

    /* (d) the page can't take the world back: the worker keeps it and resumes */
    const big = makeWorker();
    big.send(startMsg(HO.buffer(page).slice(0)));
    const bs = await big.wait(isType('stats'), 'stats');
    big.M.wasmMemory.grow(160);   /* the worker's memory outgrows the page's (+10 MiB) */
    await big.wait(statsAt(bs.frame + 200), 'progress');
    big.send({ cmd: 'stop' });
    const m4 = await big.wait(isType('memory'), 'the memory');
    const realGrow = page.wasmMemory.grow;
    page.wasmMemory.grow = function () { throw new RangeError('injected: out of address space'); };
    const frameBefore = frame(page), printBefore = fingerprint(page);
    const err = throws(() => HO.take(page, m4.mem, "the page's"));
    ok(/could not grow/.test(err) && frame(page) === frameBefore && fingerprint(page) === printBefore,
       'a hand-back the page can\'t grow for throws and leaves the page\'s world untouched (' + err + ')');
    delete page.wasmMemory.grow;
    ok(page.wasmMemory.grow === realGrow, '(the page\'s grow restored)');
    big.send({ cmd: 'resume' });
    const rs = await big.wait(isType('stats'), 'stats after resume');
    const resumedFrom = rs.frame;
    await big.wait(statsAt(resumedFrom + 300), 'progress after resume');
    ok(true, 'the worker resumed its world (frame ' + resumedFrom + ' on)');
    big.send({ cmd: 'stop' });
    const m5 = await big.wait(isType('memory'), 'the memory, again');
    HO.take(page, m5.mem, "the page's");
    ref._oc_step(frame(page) - frame(ref));
    ok(sameFor(page, ref, 100) === '', 'the next Stop hands it back, bit-identical to the uninterrupted run (frame ' + frame(page) + ')');

    /* (e) a set with no world, a stop with no run: answered, never dropped */
    const idle = makeWorker();
    idle.send({ cmd: 'set', key: 'foodEnergy', value: 6 });
    const r = await idle.wait(isType('set'), 'a reply');
    ok(r.ok === false && /not running/.test(r.error), 'a live setting with no run is answered ok=false ("' + r.error + '")');
    idle.send({ cmd: 'stop' });
    const r2 = await idle.wait(isType('error'), 'a reply');
    ok(/not running/.test(r2.message), 'a stop with no run is answered ("' + r2.message + '")');
}

async function growthPage() {
    section('Memory growth inside the exports the page calls (summary, families, inspection, names)');
    const M = await mk(5), twin = await mk(5);
    M._oc_step(200); twin._oc_step(200);
    M._oc_sync(); twin._oc_sync();
    const len = M._oc_summary_len();
    const real = { su: M._oc_summary, fam: M._oc_families, insp: M._oc_inspect, names: M._oc_sensor_names };
    let viaMalloc = true;   /* the first growth through the allocator, the rest by a MiB */
    const grow = () => { if (viaMalloc) { viaMalloc = false; growInside(M); } else growMiB(M); };
    M._oc_summary = function () { grow(); return real.su(); };
    ok(/detached/.test(throws(() => new Float64Array(HO.buffer(M), M._oc_summary(), len))),
       'main\'s summary expression (the buffer taken before the call) fails when the call grows the memory');
    M._oc_families = function (k) { grow(); return real.fam(k); };
    const a = HO.row(M, 8, M._oc_stats_len()), b = HO.row(twin, 8, twin._oc_stats_len());
    ok(JSON.stringify(a) === JSON.stringify(b) && a.st.length === 15,
       'a dashboard row (ocean_handoff.js row) is whole and right with the memory growing in oc_summary and oc_families');
    M._oc_inspect = function (i) { grow(); return real.insp(i); };
    M._oc_sensor_names = function () { grow(); return real.names(); };
    /* the page's order (web/ocean.js inspect): the names first, then oc_inspect, then the views */
    const names = HO.cString(M, M._oc_sensor_names());
    const okI = M._oc_inspect(3);
    const info = HO.f64(M, M._oc_inspect_info(), M._oc_inspect_len());
    twin._oc_inspect(3);
    const info2 = HO.f64(twin, twin._oc_inspect_info(), twin._oc_inspect_len());
    ok(okI && names.split(',').length === M._oc_num_senses() && JSON.stringify(info) === JSON.stringify(info2),
       'the fish card\'s numbers and the sense names read right with the memory growing in oc_inspect and oc_sensor_names');
    Object.assign(M, { _oc_summary: real.su, _oc_families: real.fam, _oc_inspect: real.insp, _oc_sensor_names: real.names });
    ok(sameFor(M, twin, 50) === '', 'the growth changed nothing in the world (50 steps, bit-identical to the twin)');
}

async function randomize() {
    section('Randomize (web/ocean_config.js draw) against oc_init');
    let s = 12345;
    const rand = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    const M = await mk(1);
    const e1 = JSON.parse(HO.cString(M, M._oc_e1_preset()));
    const tryInit = (pick, w, h) => HO.withCString(M, JSON.stringify(pick.set), p => M._oc_init(7, w, h, 240, pick.population, p));
    let legacyBad = 0;
    for (let i = 0; i < 100; i++) if (!tryInit(CFG.draw(rand, 300, e1), 300, 300)) legacyBad++;
    ok(legacyBad > 0, 'without the world\'s size, draws for a 300 x 300 world are refused (' + legacyBad + ' of 100)');
    for (const [w, h] of [[100, 100], [130, 400], [300, 300], [301, 301], [1920, 1080], [1080, 1920], [5000, 2000]]) {
        let bad = 0, torus = 0, why = '';
        for (let i = 0; i < 150; i++) {
            const pick = CFG.draw(rand, 300, e1, [w, h]);
            if (pick.set.toroidal) torus++;
            if (!tryInit(pick, w, h)) { bad++; why = HO.cString(M, M._oc_last_error()); }
        }
        ok(bad === 0, w + ' x ' + h + ': 150 draws, all accepted (' + torus + ' toroidal)' + (why ? ' — ' + why : ''));
    }
}

async function imports() {
    section('Imported values the sheet would round or drop are refused by oc_init (web/ocean.js importWorld)');
    const M = await mk(1);
    for (const cfg of [{ maxPopulation: 0.5 }, { eye: 2 }, { deepCurrent: 2 }, { foodDepthMode: 2 }, { eyeCode: 32 },
                       { steerFrame: 2 }, { currentMode: 2 }, { minPopulation: -0.5 }]) {
        const r = HO.withCString(M, JSON.stringify(cfg), p => M._oc_init(1, 1920, 1080, 240, 300, p));
        ok(!r && HO.cString(M, M._oc_last_error()) !== '', JSON.stringify(cfg) + ' refused: ' + HO.cString(M, M._oc_last_error()));
    }
    /* Classic's switches used to be read only as JSON booleans, anything else
     * passed over ({"toroidal":1} ran with walls while the sheet showed it on).
     * The engine now refuses a switch that is not true / false (ocean_config.hpp
     * readOceanJson), and the page leaves that to it (pageBools). */
    const one = HO.withCString(M, '{"toroidal":1}', p => M._oc_init(1, 1920, 1080, 240, 50, p));
    const why = HO.cString(M, M._oc_last_error());
    const yes = HO.withCString(M, '{"toroidal":true}', p => M._oc_init(1, 1920, 1080, 240, 50, p));
    ok(one === 0 && /toroidal/.test(why) && yes === 1,
       'the engine refuses {"toroidal":1} ("' + why + '") and takes {"toroidal":true}');
    ok(CFG.KEYS.eyeCode[1].max === 31, 'the eye-code field runs 0..31 (the engine\'s eyeCodeValid; cloak bits 8 and 16)');
    const neg = HO.withCString(M, JSON.stringify({ kBuoy: -0.5 }), p => M._oc_init(1, 1920, 1080, 240, 300, p));
    ok(neg === 1 && CFG.NEG_ON_RESTART.kBuoy, 'kBuoy -0.5 starts a new world (so the sheet keeps it for a Restart)');
    const live = HO.withCString(M, 'kBuoy', p => M._oc_set_param(p, -0.5));
    ok(live === 0, 'and a running world refuses it live: "' + HO.cString(M, M._oc_last_error()) + '"');
    for (const k of Object.keys(CFG.NEG_ON_RESTART)) {
        const r = HO.withCString(M, JSON.stringify({ [k]: -1 }), p => M._oc_init(1, 1920, 1080, 240, 300, p));
        ok(r === 1 && CFG.LIVE[k], k + ' -1: a new world takes it (NEG_ON_RESTART, a live key)');
    }
}

/* The page's live edits around Turbo (web/ocean_handoff.js ledger, which
 * web/ocean.js turboBack / turboFailed / replayEdits use as they are): the edits
 * the page applies when the world comes back, or doesn't, in the order they
 * were made. Driven here as the page drives it, against the real worker and
 * the real module, with a worker failure that loses the world. */
async function liveLedger() {
    section('Live edits around Turbo: the page applies them in the order they were made (ledger)');
    {   /* the ledger alone: order, a newer edit never under an older one */
        const L = HO.ledger();
        L.start();
        L.sent('a', 1); L.sent('b', 2); L.answered('a', true); L.hold('a', 3);
        const kept = L.back(false).map(e => e.key + e.num + e.from).join(' ');
        ok(kept === 'b2sent a3held', 'with the worker\'s world: the unanswered and held edits, oldest first (' + kept + ')');
        L.start();
        L.sent('a', 1); L.answered('a', true); L.sent('a', 5); L.answered('a', false); L.sent('b', 2); L.hold('a', 3); L.hold('a', 4);
        const lost = L.back(true).map(e => e.key + e.num + e.from).join(' ');
        ok(lost === 'a1acked b2sent a3held a4held', 'without it: the acknowledged ones first, a refused one never, every held edit in order (' + lost + ')');
        L.start();
        L.hold('x', 1); L.hold('y', 2);
        const fl = L.takeHeld(); fl.forEach(e => L.sent(e.key, e.num, e.seq));
        L.hold('x', 9);
        const pendX = L.pending('x');
        const order = L.back(true).map(e => e.key + e.num).join(' ');
        ok(order === 'x1 y2 x9' && pendX === true && L.pending('x') === false,
           'a held edit flushed to the worker keeps its place (' + order + '); x is pending until the world is back');
        /* pending(key, seq): a NEWER edit of key, held or in flight, than the answered one */
        L.start();
        L.sent('k', 1); L.hold('k', 2);
        const refusedK = L.answered('k', false);
        const newerHeld = L.pending('k', refusedK.seq);
        L.back(false);
        L.start();
        L.hold('m', 1); L.sent('m', 2);
        const refusedM = L.answered('m', false);
        const olderHeld = L.pending('m', refusedM.seq);
        L.sent('m', 3);
        const newerSent = L.pending('m', refusedM.seq), notAfterItself = L.pending('m', 99);
        L.back(false);
        ok(newerHeld === true && olderHeld === false && newerSent === true && notAfterItself === false,
           'pending(key, seq): a newer held edit counts (' + newerHeld + '), an older held one does not (' + olderHeld +
           '), a newer one in flight does (' + newerSent + '), nothing after the newest (' + notAfterItself + ')');
    }

    const SEED = 4242;
    /* (#2) dependent edits, acknowledged in Turbo, then the worker dies without its world */
    {
        const page = await mk(SEED);
        page._oc_step(100);
        const entryFrame = frame(page), entryImg = HO.buffer(page).slice(0), entryCfg = {};
        const L = HO.ledger(), runCfg = {};
        L.start();
        const w = makeWorker();
        w.send(startMsg(entryImg.slice(0)));
        await w.wait(isType('stats'), 'the first stats');
        for (const [k, v] of [['minSpeed', 0], ['maxSpeed', 300], ['minSpeed', 200]]) {
            L.sent(k, v);
            w.send({ cmd: 'set', key: k, value: v });
            const r = await w.wait(isType('set'), 'the ' + k + ' reply');
            L.answered(r.key, !!r.ok);
            if (r.ok) liveApplied(runCfg, k, v);
            ok(r.ok, 'in Turbo: ' + k + ' ' + v + ' acknowledged');
        }
        trapAt(w, 2);
        const e = await w.wait(isType('error'), 'the error');
        ok(!e.mem && frame(page) === entryFrame, 'the worker dies without its world; the page has its copy from Turbo\'s start (frame ' + entryFrame + ')');
        /* main's recovery first, on a copy of the same world */
        const legacy = await mk(1);
        HO.take(legacy, entryImg.slice(0), 'the legacy');
        const lplan = legacyRecovery(runCfg, entryCfg, {}, []);
        const lres = lplan.map(([k, v]) => HO.withCString(legacy, k, p => legacy._oc_set_param(p, v)) ? '' : k + ' ' + v + ': ' + HO.cString(legacy, legacy._oc_last_error()));
        ok(lplan.map(x => x.join('=')).join(',') === 'minSpeed=200,maxSpeed=300' && lres[0] !== '' && lres[1] === '',
           'main\'s recovery (the config difference in key order) is refused minSpeed 200 against the old maximum (' + lres[0] + '), then sets the maximum: 30-300');
        /* the page's: the ledger's plan, replayed in order */
        const plan = L.back(true), pRun = Object.assign({}, entryCfg);
        const res = replayOnPage(page, plan, pRun);
        ok(plan.map(x => x.key + '=' + x.num).join(',') === 'minSpeed=0,maxSpeed=300,minSpeed=200' && res.every(x => x === ''),
           'the page replays them as the worker applied them (' + plan.map(x => x.key + '=' + x.num).join(', ') + '), each accepted');
        ok(pRun.minSpeed === 200 && pRun.maxSpeed === 300 && JSON.stringify(pRun) === JSON.stringify(runCfg),
           'runCfg after the recovery is what Turbo acknowledged (' + JSON.stringify(pRun) + ')');
        const ref = await mk(SEED);
        ref._oc_step(entryFrame);
        setParam(ref, 'minSpeed', 0); setParam(ref, 'maxSpeed', 300); setParam(ref, 'minSpeed', 200);
        const ref2 = await mk(1);
        HO.take(ref2, HO.buffer(ref).slice(0), 'the reference copy');
        ok(sameFor(page, ref, 150) === '', 'the recovered world runs 200-300: 150 steps bit-identical to the same edits applied directly');
        ok(sameFor(legacy, ref2, 150) !== '', 'and main\'s recovered world is another one (it runs 30-300)');
    }
    /* (#3) an edit sent in Turbo, not answered yet; Stop; a newer edit of it held; the worker dies */
    {
        const page = await mk(SEED);
        page._oc_step(100);
        const entryFrame = frame(page);
        const L = HO.ledger(), runCfg = {}, form = {};
        L.start();
        const w = makeWorker();
        w.send(startMsg(HO.buffer(page).slice(0)));
        await w.wait(isType('stats'), 'the first stats');
        L.sent('minSpeed', 10); form.minSpeed = 10;
        w.send({ cmd: 'set', key: 'minSpeed', value: 10 });   /* its answer: never read (the worker is dropped first) */
        /* Stop: "exiting"; the field changes again and is held */
        L.hold('minSpeed', 20); form.minSpeed = 20;
        trapAt(w, 1);
        await w.wait(isType('error'), 'the error');
        const lplan = legacyRecovery(null, {}, { minSpeed: 20 }, L.inflight());
        ok(lplan.length === 1 && lplan[0][1] === 10 && form.minSpeed === 20,
           'main\'s turboBack copies the unanswered 10 over the held 20: the world would run 10 under a field showing 20');
        const plan = L.back(true);
        const res = replayOnPage(page, plan, runCfg);
        ok(plan.map(x => x.num).join(',') === '10,20' && res.every(x => x === ''), 'the page applies 10, then the newer 20');
        ok(form.minSpeed === 20 && runCfg.minSpeed === 20, 'the field, runCfg and the world agree: minSpeed 20');
        const ref = await mk(SEED);
        ref._oc_step(entryFrame);
        setParam(ref, 'minSpeed', 20);
        ok(sameFor(page, ref, 150) === '', 'the world runs minSpeed 20: 150 steps bit-identical to that edit applied directly (frame ' + entryFrame + ')');
    }
}

/* a number too big for a double, in either occurrence of a repeated key (int, Ocean int, Ocean bool),
 * and in a float the engine clamps (perceptionRadius: only a finite one is raised to 1; -1e400 was
 * stored as 1, PR #34's review) — every one of them refused by oc_init */
const OVERFLOW_DOCS = ['{"maxPopulation":300,"maxPopulation":1e400}', '{"maxPopulation":1e400,"maxPopulation":300}',
                       '{"maxPopulation":300,"maxPopulation":-1e400}', '{"maxPopulation":-1e400,"maxPopulation":300}',
                       '{"appearance":3,"appearance":1e400}', '{"appearance":1e400,"appearance":3}',
                       '{"lightEnabled":true,"lightEnabled":1e400}', '{"lightEnabled":1e400,"lightEnabled":true}',
                       '{"perceptionRadius":-1e400}', '{"perceptionRadius":-1e400,"perceptionRadius":100}'];
/* A key twice in ?cfg= or a setup file: the page now follows the engine's
 * rule (web/ocean_handoff.js parseFirst / cfgJson, as web/ocean.js
 * importWorld / loadSetup use them): the first occurrence counts, every one
 * is checked. JSON.parse kept the last and dropped the rest unchecked. */
async function repeatedKeys() {
    section('A repeated key in ?cfg= or a setup file: the engine\'s rule on the page (parseFirst / cfgJson)');
    const same = ['{}', '[]', '{"a":1,"b":[1,2,{"c":"x\\"y\\\\"}],"d":{"e":null,"f":true,"g":false}}', '"\\u00e9\\ud83d\\ude00"',
                  '-0', '1e-7', ' {\n "a" : [ ] ,\t"b" : { } } ', '{"__proto__":{"x":1},"y":-12.5e3}', '[{"a":{"b":[[]]}}]'];
    const deq = (a, b) => JSON.stringify(a) === JSON.stringify(b) && (typeof a !== 'number' || Object.is(a, b));   /* -0 too */
    ok(same.every(t => { const p = HO.parseFirst(t); return deq(p.value, JSON.parse(t)) && !p.repeats.length; }),
       'parseFirst is JSON.parse on documents without a repeated key (' + same.length + ' of them, escapes and nesting)');
    const proto = HO.parseFirst('{"__proto__":{"x":1}}').value;
    ok(Object.getPrototypeOf(proto) === Object.prototype && Object.prototype.hasOwnProperty.call(proto, '__proto__'),
       'a "__proto__" key is an own property, as JSON.parse makes it (no prototype change)');
    ok(['{', '{"a":1,}', '[1,]', '{\'a\':1}', '{"a":01}', ''].every(t => throws(() => HO.parseFirst(t)) === throws(() => JSON.parse(t)) && throws(() => JSON.parse(t)) !== ''),
       'it refuses what JSON.parse refuses, with the same message');
    const nest = HO.parseFirst('{"a":1,"b":{"c":1,"c":2},"a":[3],"a":4}');
    ok(nest.value.a === 1 && nest.value.b.c === 1 && nest.repeats.map(r => r.path.join('.') + ':' + r.key + '=' + JSON.stringify(r.value)).join(' ') === 'b:c=2 :a=[3] :a=4',
       'a repeated key keeps its first value and lists the later ones with where they are');

    const M = await mk(1);
    const init = (json) => {
        const r = HO.withCString(M, json, p => M._oc_init(3, 1920, 1080, 240, 60, p));
        return { ok: r === 1, why: r ? '' : HO.cString(M, M._oc_last_error()), print: r ? stepped(M) : '' };
    };
    /* what cfgJson writes for finite values is JSON.stringify's, byte for byte (every sheet,
     * preset and finite import reaches oc_init as it did) */
    const finite = [{}, { a: 1, b: -0, c: 0.006, d: 1e21, e: -2.5e-7, f: true, g: null, h: 'x"y\\zé', i: [1, [2, { j: 3 }], null], k: {} },
                    CFG.BIG_TANK.cfg, JSON.parse(HO.cString(M, M._oc_e1_preset())), { walls: true, maxPopulation: 2147483647 }];
    ok(finite.every(c => !Object.keys(c).length ? HO.cfgJson(c) === '' : HO.cfgJson(c) === JSON.stringify(c)),
       'cfgJson writes finite values as JSON.stringify does (' + finite.length + ' configs: nesting, -0, exponents, escapes, the Big tank, E1)');
    /* the URL's text (URLSearchParams decodes it), and a setup file with it as its config */
    for (const doc of ['{"toroidal":1,"toroidal":true}', '{"toroidal":true,"toroidal":1}', '{"toroidal":false,"toroidal":true}',
                       '{"foodEnergy":5,"foodEnergy":9}', '{"maxPopulation":300,"maxPopulation":0.5}', '{"maxPopulation":0.5,"maxPopulation":300}']
                      .concat(OVERFLOW_DOCS)) {
        const direct = init(doc);
        const url = new URLSearchParams('cfg=' + encodeURIComponent(doc)).get('cfg');
        const pf = HO.parseFirst(url), top = pf.repeats.filter(r => !r.path.length);
        const page = init(HO.cfgJson(pf.value, top));
        const file = HO.parseFirst('{"format":"evo_ocean_setup","seed":3,"config":' + doc + '}');
        const fileCfg = init(HO.cfgJson(file.value.config, file.repeats.filter(r => r.path.length === 1 && r.path[0] === 'config')));
        const legacy = init(JSON.stringify(JSON.parse(url)));
        const agree = page.ok === direct.ok && page.print === direct.print && fileCfg.ok === direct.ok && fileCfg.print === direct.print;
        ok(agree, doc + ': the page (?cfg= and setup file) and oc_init agree: ' + (direct.ok ? 'accepted, the same world' : 'refused (' + direct.why + ')') +
           (legacy.ok !== direct.ok || legacy.print !== direct.print ? '; JSON.parse\'s page ' + (legacy.ok ? 'ran another world' : 'refused it') : ''));
    }
    const off = init('{"toroidal":false}'), twice = init(HO.cfgJson(HO.parseFirst('{"toroidal":false,"toroidal":true}').value,
                                                                     HO.parseFirst('{"toroidal":false,"toroidal":true}').repeats));
    ok(off.ok && twice.ok && off.print === twice.print, '{"toroidal":false,"toroidal":true} runs with walls on the page too (the first: false), as in oc_init');
}

/* ---- the page itself (bootPage): its live edits around Turbo ---- */

/* the three edits whose order matters: from 30-150, minSpeed 0, maxSpeed 10,
 * minSpeed 5 is valid only as a sequence (maxSpeed 10 is refused against 30) */
const SEQ3 = [['minSpeed', 0], ['maxSpeed', 10], ['minSpeed', 5]];
function edit3(p) { for (const [k, v] of SEQ3) p.edit(k, v); }
/* the page after the three edits: 5-10 in the world's bookkeeping and the fields, no note left */
function at5to10(p) {
    return p.T.runCfg.minSpeed === 5 && p.T.runCfg.maxSpeed === 10 && p.T.getVal('minSpeed') === 5 && p.T.getVal('maxSpeed') === 10 &&
           p.note('minSpeed') === '' && p.note('maxSpeed') === '' && JSON.stringify(p.T.live.held()) === '{}';
}
const speeds = (p) => 'runCfg ' + p.T.runCfg.minSpeed + '-' + p.T.runCfg.maxSpeed + ', fields ' + p.T.getVal('minSpeed') + '-' + p.T.getVal('maxSpeed') +
                      (p.note('minSpeed') || p.note('maxSpeed') ? ', notes "' + p.note('minSpeed') + '" / "' + p.note('maxSpeed') + '"' : '');
const setsTo = (sh) => sh.toWorker.filter(m => m.cmd === 'set').map(m => m.key + '=' + m.value).join(',');

/* (#1) Every held edit is applied, in order: edits made while Turbo is
 * starting or stopping (neither side owns the world) are held; main kept
 * only the newest of each key, so minSpeed 0, maxSpeed 10, minSpeed 5 lost
 * the 0, maxSpeed 10 was refused against 30 and the run went on at 5-150.
 * Through the page itself, entering, after a Stop, after a lost world and
 * after a hand-back the page could not take (Turbo resumes). */
async function pageHeld() {
    section('The page: every held live edit applies, in order (entering, Stop, a lost world, a resumed hand-back)');
    {   /* entering: the first stats held, so the worker has the world and the page does not know yet */
        const p = await bootPage(PAGE_Q);
        const img = HO.buffer(p.M).slice(0), f0 = frame(p.M);
        p.hooks.onWorker = (sh) => sh.pause();
        p.click('turbobtn');
        const sh = p.worker();
        await until(() => sh.queued(isType('stats')), 'the first stats');
        const entering = p.T.turboState;
        edit3(p);
        const notes = p.note('minSpeed') + ' | ' + p.note('maxSpeed');
        sh.resume();
        await until(() => p.T.turboState === 'turbo' && sh.delivered.filter(isType('set')).length === sh.toWorker.filter(m => m.cmd === 'set').length,
                    'the edits\' answers');
        ok(entering === 'entering' && /as soon as Turbo has started/.test(notes), 'entering: the edits are held ("' + notes + '")');
        ok(setsTo(sh) === 'minSpeed=0,maxSpeed=10,minSpeed=5' && sh.fromWorker.filter(isType('set')).every(m => m.ok),
           'entering: the worker receives all three in order, each accepted (' + setsTo(sh) + ')');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        ok(at5to10(p), 'entering, after Stop: 5-10 in runCfg and the fields, no note left (' + speeds(p) + ')');
        const ref = await controlRun(img, workerEdits(sh), frame(p.M));
        const d = sameFor(p.M, ref, 150);
        ok(f0 < frame(p.M) && d === '', 'entering: 150 further steps bit-identical to the edits applied at the worker\'s frames' + (d ? ': ' + d : ''));
    }
    {   /* a Stop: the memory held, the edits made while it comes */
        const { p, img, sets0, sh } = await pageInTurbo();
        sh.pause();
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the memory');
        edit3(p);
        const notes = p.note('minSpeed') + ' | ' + p.note('maxSpeed');
        sh.resume();
        await until(() => p.T.turboState === 'live', 'the hand-back');
        ok(/as soon as Turbo hands the world back/.test(notes) && at5to10(p),
           'Stop: the three held edits apply on the world handed back, in order (' + speeds(p) + ')');
        const ref = await controlRun(img, workerEdits(sh).concat(p.sets.slice(sets0)), frame(p.M));
        const d = sameFor(p.M, ref, 150);
        ok(p.sets.slice(sets0).map(e => e[1] + '=' + e[2]).join(',') === 'minSpeed=0,maxSpeed=10,minSpeed=5' && d === '',
           'Stop: the page applied 0, 10, 5; 150 further steps bit-identical to that' + (d ? ': ' + d : ''));
    }
    {   /* a lost world: the worker traps (no memory comes back); the edits held while that is on its way */
        const { p, img, f0, sets0, sh } = await pageInTurbo();
        sh.pause();
        trapNext(sh);
        await until(() => sh.queued(isType('error')), 'the trap');
        p.click('turboexit');
        edit3(p);
        await sh.release(isType('error'), 'the error');
        await until(() => p.T.turboState === 'live', 'the recovery');
        ok(frame(p.M) === f0 && at5to10(p), 'a lost world: the page goes on from its own copy (frame ' + f0 + ') with all three, in order (' + speeds(p) + ')');
        const ref = await controlRun(img, p.sets.slice(sets0), f0);
        const d = sameFor(p.M, ref, 150);
        ok(d === '', 'a lost world: 150 further steps bit-identical to the three edits applied at frame ' + f0 + (d ? ': ' + d : ''));
    }
    {   /* a hand-back the page cannot take: Turbo resumes, then the held edits go to the worker */
        const { p, img, sh } = await pageInTurbo();
        sh.pause();
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the memory');
        edit3(p);
        const H = p.ctx.EvoOceanHandoff, take = H.take;
        H.take = function () { H.take = take; throw new Error('injected: the page could not grow its memory'); };
        sh.resume();
        await until(() => p.T.turboState === 'turbo' && sh.toWorker.some(m => m.cmd === 'resume') &&
                          sh.delivered.filter(isType('set')).length === sh.toWorker.filter(m => m.cmd === 'set').length, 'the resumed run\'s answers');
        const order = sh.toWorker.filter(m => m.cmd !== 'rec').map(m => m.cmd === 'set' ? m.key + '=' + m.value : m.cmd).join(',');
        ok(order === 'start,stop,resume,minSpeed=0,maxSpeed=10,minSpeed=5' && sh.fromWorker.filter(isType('set')).every(m => m.ok),
           'a refused hand-back: the page resumes Turbo, then sends the three in order, each accepted (' + order + ')');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the second hand-back');
        ok(at5to10(p), 'a refused hand-back: the next Stop returns 5-10 (' + speeds(p) + ')');
        const ref = await controlRun(img, workerEdits(sh), frame(p.M));
        const d = sameFor(p.M, ref, 150);
        ok(d === '', 'a refused hand-back: 150 further steps bit-identical to the edits at the worker\'s frames' + (d ? ': ' + d : ''));
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ': ' + p.uncaught[0] : ''));
    }
}

/* (#2) An answer to an older edit must not undo a newer one. The worker
 * refuses minSpeed 200 (the maximum is 150); before the refusal reaches the
 * page, Stop, and minSpeed 20 is held. main's handler asked only whether a
 * newer edit was in flight: it reset the field to 30 and cleared its note,
 * then the recovery applied the held 20 under a field showing 30. Through
 * the page's own handler, with the world handed back and with it lost; the
 * controls: no newer edit (the field goes back to 30), a newer one in
 * flight (it stays); and with the held three-edit sequence after it. */
async function pageRefusal() {
    section('The page: an older edit\'s refusal leaves a newer held or in-flight edit alone');
    const refusal = (m) => m.type === 'set' && !m.ok;
    for (const how of ['handed back', 'lost']) {
        const { p, img, f0, sets0, sh } = await pageInTurbo();
        sh.pause();
        p.edit('minSpeed', 200);
        await until(() => sh.queued(refusal), 'the refusal');
        if (how === 'lost') { trapNext(sh); await until(() => sh.queued(isType('error')), 'the trap'); }
        p.click('turboexit');
        if (how !== 'lost') await until(() => sh.queued(isType('memory')), 'the memory');
        p.edit('minSpeed', 20);
        const held = p.note('minSpeed');
        await sh.release(refusal, 'the refusal');
        const field = p.T.getVal('minSpeed'), note = p.note('minSpeed');
        ok(held !== '' && field === 20 && note === held,
           how + ': the old refusal leaves the held 20 in its field, its note unchanged (field ' + field + ', note "' + note + '")');
        sh.resume();
        await until(() => p.T.turboState === 'live', 'the world back');
        ok(p.T.runCfg.minSpeed === 20 && p.T.getVal('minSpeed') === 20 && p.note('minSpeed') === '',
           how + ': the world, runCfg and the field agree on 20, no note left (runCfg ' + p.T.runCfg.minSpeed + ', field ' + p.T.getVal('minSpeed') + ')');
        const edits = (how === 'lost' ? [] : workerEdits(sh)).concat(p.sets.slice(sets0)), at = frame(p.M);
        const ref = await controlRun(img, edits, at);
        const d = sameFor(p.M, ref, 150);
        ok((how !== 'lost' || at === f0) && d === '', how + ': 150 further steps bit-identical to minSpeed 20 applied where the page applied it (frame ' +
           at + ')' + (d ? ': ' + d : ''));
    }
    {   /* controls: no newer edit (back to 30); a newer one in flight (the field stays) */
        const { p, sh } = await pageInTurbo();
        sh.pause();
        p.edit('minSpeed', 200);
        await sh.release(refusal, 'the refusal');
        ok(p.T.getVal('minSpeed') === 30 && p.note('minSpeed') === '' && !('minSpeed' in p.T.runCfg) && /back to 30/.test(p.msg()),
           'no newer edit: the refused field goes back to 30 ("' + p.msg() + '")');
        p.edit('minSpeed', 200);
        await until(() => sh.queued(refusal), 'the second refusal');
        p.edit('minSpeed', 20);
        await sh.release(refusal, 'the refusal');
        const kept = p.T.getVal('minSpeed');
        sh.resume();
        await until(() => sh.delivered.filter(isType('set')).length === 3, 'the answer to 20');
        ok(kept === 20 && p.T.getVal('minSpeed') === 20 && p.T.runCfg.minSpeed === 20,
           'a newer edit in flight: the field stays 20 through the old refusal, then 20 applies (' + kept + ', runCfg ' + p.T.runCfg.minSpeed + ')');
    }
    {   /* with #1: a refused older edit, then the held three-edit sequence */
        const { p, img, sets0, sh } = await pageInTurbo();
        sh.pause();
        p.edit('minSpeed', 200);
        await until(() => sh.queued(refusal), 'the refusal');
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the memory');
        edit3(p);
        await sh.release(refusal, 'the refusal');
        const fields = p.T.getVal('minSpeed') + '-' + p.T.getVal('maxSpeed');
        sh.resume();
        await until(() => p.T.turboState === 'live', 'the world back');
        ok(fields === '5-10' && at5to10(p), 'a refusal before the held 0, 10, 5: the fields stay 5-10 through it, and 5-10 is what runs (' + speeds(p) + ')');
        const ref = await controlRun(img, workerEdits(sh).concat(p.sets.slice(sets0)), frame(p.M));
        const d = sameFor(p.M, ref, 150);
        ok(d === '' && p.uncaught.length === 0, 'and 150 further steps are bit-identical to that' + (d ? ': ' + d : ''));
    }
}

/* (#3) Load setup reads the file asynchronously; the page checked who owns
 * the world before the read, not when it completed. A read started while
 * the page ran and finished during Turbo replaced the page's copy (the one
 * a lost Turbo world falls back to) and its seed and settings while the
 * worker went on with the old world. Through the page's own file-input
 * callback, the read completing while Turbo starts, runs and stops; then
 * the same file while the page runs. */
const SETUP99 = JSON.stringify({ format: 'evo_ocean_setup', seed: 99, population: 12, depth: 200, width: 800, height: 600,
                                 config: { minPopulation: 0, targetFood: 0, foodSpawnBase: 0, foodSpawnAmp: 0, foodEnergy: 9 } });
function deferredFile(text) {
    let resolve;
    const pr = new Promise((r) => { resolve = r; });
    return { file: { name: 'setup.json', text: () => pr }, resolve: () => resolve(text) };
}
/* UI-3: a read completing while Turbo starts, runs or stops now stages
 * the file (it starts and stops nothing: the page's copy, the worker, the
 * seed, settings, size and address stay; the sheet shows the file); the
 * explicit Start then stops Turbo and starts it. A slow older read never
 * overwrites a newer file, a Discard or a world started meanwhile. */
async function pageAsyncSetup() {
    section('The page: a setup file whose read completes during Turbo is staged then (nothing started or stopped), and starts only on Start');
    for (const when of ['entering', 'turbo', 'exiting']) {
        const p = await bootPage(PAGE_Q);
        const f0 = frame(p.M), print0 = fingerprint(p.M), world0 = p.world(), inits0 = p.inits.length;
        const img = HO.buffer(p.M).slice(0);
        const f = deferredFile(SETUP99);
        p.loadFile(f.file);   /* the page runs: the read starts */
        if (when === 'entering') p.hooks.onWorker = (sh) => sh.pause();
        p.click('turbobtn');
        const sh = p.worker();
        if (when === 'entering') await until(() => sh.queued(isType('stats')), 'the first stats');
        else await until(() => p.T.turboState === 'turbo', 'Turbo');
        if (when === 'exiting') { sh.pause(); trapNext(sh); await until(() => sh.queued(isType('error')), 'the trap'); p.click('turboexit'); }
        const st = p.T.turboState, stops0 = sh.toWorker.filter(m => m.cmd === 'stop').length;
        f.resolve();
        for (let i = 0; i < 4; i++) await tick();
        const kept = p.inits.length === inits0 && fingerprint(p.M) === print0 && p.world() === world0 && p.T.turboState === st &&
                     sh.toWorker.filter(m => m.cmd === 'stop').length === stops0;
        ok(st === when && kept && p.T.draft && p.T.draft.kind === 'file' && p.el('o_seed').value === '99' && p.el('o_width').value === '800',
           when + ': the read completing then stages the file (the sheet: seed 99, 800 wide): no oc_init, no Stop, the page\'s copy, seed, settings, ' +
           'size and address as they were ("' + p.msg() + '")');
        if (when === 'entering') { sh.resume(); await until(() => p.T.turboState === 'turbo', 'Turbo'); }
        if (when === 'exiting') { sh.resume(); await until(() => p.T.turboState === 'live', 'the recovery'); }
        const back = when === 'exiting' ? (await controlRun(img, [], frame(p.M)), frame(p.M) === f0) : true;
        p.start();   /* entering / turbo: Stop Turbo & start (asked); exiting: the recovered page starts it */
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart && p.T.initArgs.seed === 99, 'the file\'s world');
        ok(back && p.inits.length === inits0 + 1 && p.T.initArgs.population === 12 && p.T.W === 800 && p.T.H === 600 && p.T.D === 200 &&
           p.T.runCfg.foodEnergy === 9 && !p.T.WALLS && !p.T.draft,
           when + ': then Start' + (when === 'exiting' ? '' : ' (Stop Turbo & start)') + ' starts the file\'s world once: seed 99, 12 fish, 800 x 600 x 200, foodEnergy 9');
    }
    {   /* stale reads: an older read finishing after a newer one, after Discard, after a start */
        const p = await bootPage(PAGE_Q);
        const a = deferredFile(SETUP99), b = deferredFile(SETUP99.replace('"seed":99', '"seed":98'));
        p.loadFile(a.file); p.loadFile(b.file);
        b.resolve(); for (let i = 0; i < 4; i++) await tick();
        a.resolve(); for (let i = 0; i < 4; i++) await tick();
        const newer = p.el('o_seed').value;
        const c = deferredFile(SETUP99);
        p.loadFile(c.file); p.click('startdiscard');
        c.resolve(); for (let i = 0; i < 4; i++) await tick();
        const afterDiscard = p.T.draft === null && p.el('o_seed').value === '4242';
        const d = deferredFile(SETUP99);
        p.loadFile(d.file); p.key('r');
        d.resolve(); for (let i = 0; i < 4; i++) await tick();
        const afterStart = p.T.draft === null && p.T.initArgs.seed !== 99 && p.el('o_seed').value === String(p.T.initArgs.seed);
        ok(newer === '98' && afterDiscard && afterStart,
           'a slower older read is dropped: after a newer file (seed ' + newer + ' stays), after Discard, after a start (R)');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
    }
}

/* (#4) A Turbo start that throws on the page (the Worker constructor, the
 * first postMessage, the copy of the memory) left main's page "entering"
 * for good: controls locked, no Stop. Each injected failure first makes the
 * held three-edit sequence (as an edit landing in that moment would be
 * held), so the recovery must apply it too; then a second start must work. */
/* Post-merge audit 43fedc0, finding 6: a start that fails also left a
 * paused world running (turboBack's setPaused(false)); each failure now
 * runs from a paused page too, which must stay paused, and the worker's
 * asynchronous load failure (its onerror, while starting) joins them. */
async function pageStartFailures() {
    section('The page: a Turbo start that throws or fails to load recovers, paused or running as it was (the Worker, its first message, the memory copy, its load)');
    const injections = [
        ['the Worker constructor throws', (p) => { p.hooks.ctor = () => { edit3(p); throw new Error('injected: no worker'); }; }],
        ['the first postMessage throws', (p) => { p.hooks.post = () => { edit3(p); throw new Error('injected: could not post'); }; }],
        ['the memory copy throws', (p) => {
            const b = HO.buffer(p.M);
            Object.defineProperty(b, 'slice', { configurable: true, value: () => { delete b.slice; edit3(p); throw new RangeError('injected: out of memory'); } });
        }],
        ['the worker fails to load', (p) => {   /* its script: the Worker is made, then its error event, before any answer */
            p.hooks.onWorker = (sh) => {
                p.hooks.onWorker = null;
                sh.pause();
                edit3(p);
                setImmediate(() => { if (sh.onerror) sh.onerror({ message: 'injected: could not load ocean_worker.js', preventDefault() {} }); });
            };
        }]
    ];
    for (const paused of [false, true]) for (const [what0, arm] of injections) {
        const p = await bootPage(PAGE_Q), what = (paused ? 'paused, ' : '') + what0;
        if (paused) p.click('pausebtn');
        const img = HO.buffer(p.M).slice(0), f0 = frame(p.M), sets0 = p.sets.length, nW = p.workers.length;
        arm(p);
        p.click('turbobtn');
        for (let i = 0; i < 4; i++) await tick();
        const sh = p.workers.length > nW ? p.worker() : null, c = turboControls(p);
        ok(p.T.turboState === 'live' && p.T.turboWorker === null && !c.card && c.button && !c.locked.length &&
           /Turbo could not start|The Turbo worker failed/.test(p.msg()),
           what + ': the page is live again, no worker, the Turbo card hidden, its button on, nothing locked ("' + p.msg() + '"; state ' +
           p.T.turboState + (c.locked.length ? ', locked ' + c.locked.join(' ') : '') + ')');
        const playing = p.el('pausebtn').getAttribute('aria-label') === 'pause';
        ok(p.T.paused === paused && playing === !paused && p.el('stepbtn').hidden === !paused,
           what + ': ' + (paused ? 'still paused (▶ and the step button showing)' : 'still running') + ' (paused ' + p.T.paused + ')');
        if (sh) ok(sh.terminated === 1 && sh.onmessage === null && sh.onerror === null,
                   what + ': the worker it had made is terminated once, its handlers detached (' + sh.terminated + ')');
        ok(at5to10(p), what + ': the edits held in that moment apply, in order (' + speeds(p) + ')');
        const ref = await controlRun(img, p.sets.slice(sets0), f0), d = sameFor(p.M, ref, 50);
        ok(d === '', what + ': the page\'s world is its own, untouched but for those edits (50 steps bit-identical)' + (d ? ': ' + d : ''));
        if (p.T.turboState === 'live') {
            const f1 = frame(p.M);
            p.click('turbobtn');
            await until(() => p.T.turboState === 'turbo', 'the second start');
            await until(() => p.worker().fromWorker.some(m => m.type === 'stats' && m.frame >= f1 + 60), 'the second run');
            p.click('turboexit');
            await until(() => p.T.turboState === 'live', 'the second hand-back');
            ok(frame(p.M) > f1 && at5to10(p) && !p.T.paused,
               what + ': a second Turbo starts and hands back, and the world runs on, as after any Stop (frame ' + f1 + ' -> ' + frame(p.M) + ')');
        } else ok(false, what + ': a second Turbo start (the page is stuck "' + p.T.turboState + '")');
        ok(p.uncaught.length === 0, what + ': no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
}

/* oc_init of doc as it is, on module M: {ok, why, print} */
function directInit(M, doc) {
    const r = HO.withCString(M, doc, ptr => M._oc_init(7, 1920, 1080, 240, 12, ptr));
    return { ok: r === 1, why: r ? '' : HO.cString(M, M._oc_last_error()), print: r ? stepped(M) : '' };
}
const PAGE_Q7 = '?seed=7&pop=12&w=1920&h=1080&walls=0';
/* A cfg document into a running page by one of its three ways in:
 * importWorld (as its callers call it: parseFirst, the top-level repeats),
 * the start-up's URL-import block (?cfg=; seed 7, 12 fish, 1920 x 1080),
 * Load setup (a version-1 file, the document its config). {ok, why} */
async function viaPage(p, how, doc) {
    if (how === 'importWorld') {
        const pf = p.ctx.EvoOceanHandoff.parseFirst(doc);
        const why = p.T.importWorld(7, 12, 240, pf.value, undefined, pf.repeats.filter(r => !r.path.length), [1920, 1080]);
        return { ok: why === '', why };
    }
    if (how === 'url') {
        try { p.T.urlImport(new URLSearchParams('seed=7&pop=12&w=1920&h=1080&cfg=' + encodeURIComponent(doc))); return { ok: true, why: '' }; }
        catch (e) { return { ok: false, why: String(e && e.message || e) }; }
    }
    const said = await p.loadSetup('{"format":"evo_ocean_setup","seed":7,"population":12,"depth":240,' +
                                   '"width":1920,"height":1080,"config":' + doc + '}');
    return { ok: /^Setup loaded/.test(said), why: said };
}
const PAGE_WAYS = ['importWorld', 'url', 'setup'];

/* (#5) A number too big for a double (1e400) parses to Infinity, which
 * JSON.stringify wrote as null on the page's way to oc_init:
 * {"maxPopulation":300,"maxPopulation":1e400} went as ...:null, which the
 * engine's whole-number check passes over, and ran with 300 (the other order
 * with the default). Now the infinity goes on as a number, and oc_init
 * refuses it as it does in its own JSON. Through the page's three ways in,
 * on a running page (a refusal changes nothing), against oc_init itself. */
async function pageOverflow() {
    section('The page: a number too big for a double reaches oc_init as a number, and is refused there');
    {
        const p = await bootPage('?seed=7&pop=12&w=1920&h=1080&cfg=' + encodeURIComponent(OVERFLOW_DOCS[0]));
        const sent = p.inits[0] || '';
        ok(/This link's settings were refused/.test(p.failed) && /maxPopulation/.test(p.failed) && /1e400/.test(sent) && !/null/.test(sent),
           'a link with ' + OVERFLOW_DOCS[0] + ' is refused at start-up ("' + (p.failed.split('\n').pop() || 'it started') + '"); oc_init got ' + sent);
    }
    const direct = await mk(1, {}, 300, 300, 0);
    const p = await bootPage(PAGE_Q7);
    /* the controls: valid repeats; and a float key's later occurrence, which oc_init does not read (nor
     * check: which occurrences it checks is the engine's), so the first runs, as the page shows and writes out */
    for (const doc of OVERFLOW_DOCS.concat(['{"maxPopulation":300,"maxPopulation":400}', '{"foodEnergy":5,"foodEnergy":9}',
                                            '{"lightEnabled":true,"lightEnabled":false}', '{"perceptionRadius":100,"perceptionRadius":-1e400}'])) {
        const d = directInit(direct, doc), bad = [];
        if (OVERFLOW_DOCS.includes(doc) && d.ok) bad.push('oc_init accepted it');   /* an overflow is never a value */
        for (const how of PAGE_WAYS) {
            const print0 = fingerprint(p.M), state0 = how === 'setup' ? p.world() : p.state(), n0 = p.inits.length;
            const r = await viaPage(p, how, doc), sent = p.inits.slice(n0);
            if (sent.some(s => /null/.test(s) || (/e400/.test(doc) && !/1e400/.test(s)))) bad.push(how + ' sent ' + sent.join(' | '));
            if (r.ok !== d.ok) bad.push(how + (r.ok ? ' accepted it' : ' refused it: ' + r.why));
            else if (!d.ok && (fingerprint(p.M) !== print0 || (how === 'setup' ? p.world() : p.state()) !== state0)) bad.push(how + ' changed the page');
            else if (d.ok && stepped(p.M) !== d.print) bad.push(how + ' ran another world');
        }
        ok(!bad.length, doc + ': ' + (d.ok ? 'accepted, the same world' : 'refused (' + d.why + ')') + ' by oc_init, importWorld, ?cfg= and a setup file' +
           (bad.length ? ' — ' + bad.join('; ') : ''));
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
}

/* (#6) Which values an on / off key takes is the engine's rule, and only
 * the engine's: a SimConfig switch a JSON true / false, an Ocean switch
 * also the number 0 / 1, every occurrence checked (ocean_config.hpp
 * readOceanJson). main's importWorld had a narrower rule of its own (only
 * true / false for every switch), so {"lightEnabled":true,"lightEnabled":0}
 * or {"mouthGate":0,"mouthGate":1}, valid to oc_init, were refused on the
 * page; a version-1 setup took config.walls only as true. Every switch key,
 * every value (alone, after a valid one, before one), through the page's
 * three ways in, against oc_init itself: the same verdict, the same world,
 * the first value in the sheet, true / false in the page's bookkeeping. */
async function pageBools() {
    section('The page: on / off keys take what oc_init takes (SimConfig: true / false; the Ocean\'s: also 0 / 1)');
    const SIM = ['toroidal', 'bodyModel', 'triangularMotion', 'foodDrift', 'predatorEconomy', 'predatorInheritance', 'fastTanh'];
    const OCEAN = ['deepCurrent', 'lightEnabled', 'depthCostScaled', 'sizeDrift', 'sizeFight', 'mouthGate', 'walls'];
    const truth = (t) => t === 'true' || Number(t) === 1;
    /* [doc, the table's verdict, key, its first value's text] */
    const docs = (key, good, bad) => {
        const out = good.map(g => ['{"' + key + '":' + g + '}', true, key, g]);
        for (const b of bad)
            for (const form of [0, 1, 2]) {
                const kb = '"' + key + '":' + b, kg = '"' + key + '":true';
                out.push(['{' + (form === 0 ? kb : form === 1 ? kg + ',' + kb : kb + ',' + kg) + '}', false, key, form === 1 ? 'true' : b]);
            }
        return out;
    };
    const groups = SIM.map(k => [k + ' (SimConfig)', docs(k, ['true', 'false'], ['0', '1', '1.0', '-0', '2', '"true"', 'null'])])
        .concat(OCEAN.map(k => [k + ' (Ocean)', docs(k, ['true', 'false', '0', '1', '1.0', '-0'], ['2', '0.5', '-1', '"true"', 'null'])]))
        .concat([['mixed repeats', [['{"lightEnabled":true,"lightEnabled":0}', true, 'lightEnabled', 'true'],
                                    ['{"mouthGate":0,"mouthGate":1}', true, 'mouthGate', '0'],
                                    ['{"deepCurrent":1,"deepCurrent":false}', true, 'deepCurrent', '1']]],
                 ['walls with wrap-around senses', [['{"walls":true,"toroidal":true}', false, 'walls', 'true'],
                                                    ['{"walls":1,"toroidal":true}', false, 'walls', '1']]]]);
    const direct = await mk(1, {}, 300, 300, 0);
    const p = await bootPage(PAGE_Q7);
    const KEYS = p.KEYS;
    for (const [what, list] of groups) {
        const bad = [];
        let acc = 0, ref = 0;
        for (const [doc, table, key, first] of list) {
            const d = directInit(direct, doc);
            if (d.ok !== table) bad.push('oc_init ' + (d.ok ? 'accepts ' : 'refuses ') + doc + ' (the fixture says otherwise' + (d.why ? ': ' + d.why : '') + ')');
            d.ok ? acc++ : ref++;
            for (const how of PAGE_WAYS) {
                const print0 = fingerprint(p.M), state0 = how === 'setup' ? p.world() : p.state();
                const r = await viaPage(p, how, doc);
                if (r.ok !== d.ok) { bad.push(how + (r.ok ? ' accepted ' : ' refused ') + doc + (r.ok ? '' : ' (' + r.why + ')')); continue; }
                if (!d.ok) { if (fingerprint(p.M) !== print0 || (how === 'setup' ? p.world() : p.state()) !== state0) bad.push(how + ' changed the page on ' + doc); continue; }
                if (stepped(p.M) !== d.print) bad.push(how + ' ran another world for ' + doc);
                if (KEYS[key]) {
                    const want = truth(first), box = p.el('o_' + key).checked, a = p.T.initArgs.cfg[key], b = p.T.runCfg[key];
                    if (box !== want || a !== want || b !== want)
                        bad.push(how + ' ' + doc + ': the sheet ' + box + ', initArgs ' + JSON.stringify(a) + ', runCfg ' + JSON.stringify(b) + ' (want ' + want + ')');
                }
            }
        }
        ok(!bad.length, what + ': ' + list.length + ' documents (' + acc + ' accepted, ' + ref + ' refused by oc_init), the same through importWorld, ' +
           '?cfg= and a setup file' + (bad.length ? ' — ' + bad.length + ' differ: ' + bad.slice(0, 4).join('; ') : ''));
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
}

/* Turbo dashboards. While Turbo owned the world, the Brains dashboard
 * showed "Waiting for the world…" (or the wiring from before Turbo) and the
 * readout and stat panel the page's frozen copy. Now the worker's stats
 * messages carry its oc_stats / oc_summary, and it answers the page's
 * wiring questions (asked only while Brains shows, every 2 s at most); after
 * the hand-back (or a lost world) the page's own world is the source again.
 * Through the page and the real dashboards (charts stubbed): the Brains
 * panel opened first during Turbo (an empty cache) and before it (a
 * cache of the page's world), the readout, a Stop and a lost world; and the
 * round trip stays bit-identical to a run without any of this. */
async function waitFor(pred, ms) {
    try { await until(pred, '', ms); return true; } catch (e) { return false; }
}
function hud(p, now) {   /* one frame of the page at time now: the readout and the stat panel */
    p.raf(now);
    const m = /frame ([\d,]+)/.exec(p.el('statlist').innerHTML);
    return { fish: Number(p.el('ro-fish').textContent.replace(/,/g, '')), frame: m ? Number(m[1].replace(/,/g, '')) : NaN,
             notes: p.el('statnotes').textContent };
}
const brainsNote = (p) => { const n = p.el('dgrid').querySelector('.cnote'); return n ? n.textContent : ''; };
async function wiringOf(img, f) {   /* oc_wiring of the world from img, stepped to frame f */
    const ref = await controlRun(img, [], f), nS = ref._oc_num_senses(), nA = ref._oc_num_actions(), n = ref._oc_wiring();
    const data = HO.f32(ref, ref._oc_wiring_data(), 2 * nS * nA);
    return { n, path: data.slice(0, nS * nA), direct: data.slice(nS * nA) };
}
async function pageDashboards() {
    section('The page: the readout and the Brains dashboard show the Turbo world, then the page\'s again');
    let now = 1e6;
    for (const end of ['handed back', 'lost']) {
        const p = await bootPage(PAGE_Q);
        const img = HO.buffer(p.M).slice(0), f0 = frame(p.M), dash = p.ctx.EvoOceanDash;
        p.click('readout');
        if (end === 'lost') {   /* Brains opened before Turbo: its cache holds the page's world */
            dash.showTab('brains');
            await waitFor(() => /^From \d+ fish;/.test(brainsNote(p)), 5000);
        }
        const before = brainsNote(p);
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        await until(() => sh.delivered.some(m => m.type === 'stats' && m.frame >= f0 + 300), 'Turbo to run a while');
        if (end !== 'lost') dash.showTab('brains');   /* opened first during Turbo: an empty cache */
        const first = brainsNote(p);
        const turboNote = await waitFor(() => / in the Turbo run/.test(brainsNote(p)), 8000);
        const got = sh.delivered.filter(isType('wiring')), w = got[got.length - 1];
        const shown = Number((/^From (\d+)/.exec(brainsNote(p)) || [])[1]);
        let same = false;
        if (w) {
            const ref = await wiringOf(img, w.frame);
            same = w.frame > f0 && ref.n === w.n && w.path.length === ref.path.length && w.path.every((v, i) => Object.is(v, ref.path[i])) &&
                   w.direct.every((v, i) => Object.is(v, ref.direct[i])) && got.some(m => m.n === shown);
        }
        ok(turboNote && same, end + ': the Brains panel ' + (end === 'lost' ? 'kept "' + before + '", then' : 'said "' + first + '", then') +
           ' shows the worker\'s wiring ("' + brainsNote(p) + '"; ' + got.length + ' asked for, the last at frame ' + (w ? w.frame : '–') +
           ' equal to oc_wiring of that frame\'s world)');
        const asks = sh.toWorker.filter(m => m.cmd === 'wiring').length;
        const stats = sh.delivered.filter(isType('stats')), last = stats[stats.length - 1];
        const h = hud(p, now += 1000);
        ok(h.frame === last.frame && h.frame > f0 && last.st && h.fish === last.st[0] && h.fish === last.pop && /its numbers/.test(h.notes),
           end + ': the readout and stat panel show the worker\'s world: frame ' + h.frame + ' (its latest stats ' + (last && last.frame) + ', Turbo took ' + f0 +
           '), ' + h.fish + ' fish');
        {   /* one question at a time: an answer held up (the channel held 5.5 s, as behind a long chunk) is not asked again */
            const q0 = sh.toWorker.filter(m => m.cmd === 'wiring').length;
            sh.pause();
            await new Promise(r => setTimeout(r, 5500));
            const q1 = sh.toWorker.filter(m => m.cmd === 'wiring').length;
            sh.resume();
            await waitFor(() => / in the Turbo run/.test(brainsNote(p)) && sh.delivered.filter(isType('wiring')).length > got.length, 5000);
            ok(q1 - q0 === 1, end + ': while an answer is held up the page asks once, not every 2 s (' + (q1 - q0) + ' questions in 5.5 s)');
        }
        dash.showTab('pop');   /* Brains hidden: no more questions */
        const asks2 = sh.toWorker.filter(m => m.cmd === 'wiring').length;
        await new Promise(r => setTimeout(r, 2600));
        ok(asks >= 1 && asks <= 3 && sh.toWorker.filter(m => m.cmd === 'wiring').length === asks2,
           end + ': the page asked for the wiring only while Brains showed (' + asks + ' times), not after');
        dash.showTab('brains');
        if (end === 'lost') {
            sh.pause(); trapNext(sh);
            await sh.release(isType('error'), 'the trap');
        } else p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the world back');
        const at = frame(p.M);
        const own = p.T.wiringNow();
        const back = await waitFor(() => /^From \d+ fish;/.test(brainsNote(p)), 5000);
        ok(back && own && !own.turbo && (end !== 'lost' || at === f0),
           end + ': back on the page, the Brains panel reads its own world again ("' + brainsNote(p) + '")');
        const h2 = hud(p, now += 1000);
        ok(h2.frame === frame(p.M) && !/Turbo/.test(h2.notes), end + ': and the readout too (frame ' + h2.frame + ')');
        if (end !== 'lost') {
            const ref = await controlRun(img, [], frame(p.M)), d = sameFor(p.M, ref, 150);
            ok(d === '', 'the round trip with the dashboards reading the worker is bit-identical to the run without (150 steps)' + (d ? ': ' + d : ''));
        }
        dash.close();
        ok(p.uncaught.length === 0 && !p.logs.some(l => l[0] === 'error'), end + ': no exception escaped the page, no console error');
    }
}

/* Deployed-audit PR #30-31, finding 2: ?walls=0 (or a version-2 setup's
 * "walls": false) deleted the cfg's own "walls", so a later "walls" in the
 * same cfg became the first occurrence and the one oc_init ran:
 * ?walls=0&cfg={"walls":false,"walls":true} ran glass walls under an
 * unchecked switch, with runCfg missing walls. walls= now writes the first
 * occurrence; the later ones still go to oc_init to be checked. Through the
 * link and a setup file, then Replay, Save setup and loading that file. */
async function pageWallsOverride() {
    section('The page: walls=0 and a setup\'s "walls": false win over a later "walls" in the cfg (deployed audit #30-31, finding 2)');
    const DUP = '{"walls":false,"walls":true}';
    const sides = (p) => ({ engine: p.M._oc_walls_enabled(), page: p.T.WALLS, box: p.el('o_walls').checked, run: p.T.runCfg.walls,
                            init: p.T.initArgs.cfg.walls });
    const off = (s) => s.engine === 0 && s.page === false && s.box === false && s.run === false && s.init === false;
    const show = (s) => JSON.stringify(s);
    const v2 = (walls, config) => '{"format":"evo_ocean_setup","version":2,"seed":7,"population":12,"depth":240,"width":1920,' +
                                  '"height":1080,"walls":' + walls + ',"config":' + config + '}';
    const load = (p, text) => p.loadSetup(text);
    for (const how of ['link', 'setup']) {
        const p = await bootPage(how === 'link' ? '?seed=7&pop=12&w=1920&h=1080&walls=0&cfg=' + encodeURIComponent(DUP) : PAGE_Q7);
        const said = how === 'link' ? p.failed : await load(p, v2('false', DUP));
        const s1 = sides(p), sent = p.inits[p.inits.length - 1];
        ok(!/refused|can't/.test(said) && off(s1) && /^\{"walls":false,.*"walls":true\}$/.test(sent),
           how + ': ' + (how === 'link' ? '?walls=0&cfg=' + DUP : 'a version-2 setup, walls false, config ' + DUP) +
           ' runs without walls, the switch off, runCfg / initArgs walls false (' + show(s1) + '; oc_init got ' + sent + ')');
        p.click('replay');
        const s2 = sides(p);
        ok(off(s2), how + ': Replay keeps it without walls (' + show(s2) + ')');
        p.click('savecp');
        const saved = JSON.parse(p.blobs[p.blobs.length - 1] || '{}');
        ok(saved.walls === false && !('walls' in (saved.config || {})), how + ': Save setup writes walls false (' + JSON.stringify({ walls: saved.walls, config: saved.config }) + ')');
        await load(p, p.blobs[p.blobs.length - 1]);
        const s3 = sides(p);
        ok(off(s3) && /^Setup loaded/.test(p.msg()), how + ': and that file loads without walls (' + show(s3) + ')');
    }
    {   /* the other way, and a later occurrence that is not a switch: still checked, still refused */
        const p = await bootPage(PAGE_Q7);
        await load(p, v2('true', '{"walls":true,"walls":false}'));
        const on = sides(p);
        ok(on.engine === 1 && on.box === true && on.run === true, 'a version-2 setup, walls true, config {"walls":true,"walls":false}: glass walls (' + show(on) + ')');
        const why = await load(p, v2('false', '{"walls":false,"walls":2}'));
        ok(/refused/.test(why) && /walls/.test(why) && sides(p).engine === 1, 'walls false over a later "walls": 2 is refused by oc_init, the world kept ("' + why + '")');
        let refused = '';
        try { p.T.urlImport(new URLSearchParams('seed=7&pop=12&w=1920&h=1080&walls=0&cfg=' + encodeURIComponent('{"walls":false,"walls":"x"}'))); }
        catch (e) { refused = String(e.message); }
        ok(/walls/.test(refused), 'and so is ?walls=0&cfg={"walls":false,"walls":"x"} ("' + refused + '")');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
    }
}

/* Deployed-audit PR #30-31, finding 3: a link from before walls keeps
 * wrapping, a new visit gets glass walls. The page took a link with only
 * ?speed=2 (an Ocean key since before walls) for a new visit. The keys that
 * make a link the Ocean's are ocean.html's OCEAN_ONLY (its redirect's list),
 * and web/ocean.js uses that same list. */
async function pageFreshVisit() {
    section('The page: glass walls for a new visit, wrapping for a link from before them (deployed audit #30-31, finding 3)');
    const list = (src, name) => { const m = new RegExp('var ' + name + ' = (\\[[^\\]]*\\])').exec(src); return m ? JSON.parse(m[1]) : null; };
    const html = list(fs.readFileSync(path.join(WEB, 'ocean.html'), 'utf8'), 'OCEAN_ONLY');
    const js = list(fs.readFileSync(path.join(WEB, 'ocean.js'), 'utf8'), 'OCEAN_KEYS');
    ok(html && js && JSON.stringify(html) === JSON.stringify(js) && js.includes('speed'),
       'web/ocean.js\'s link keys are ocean.html\'s OCEAN_ONLY (' + JSON.stringify(js) + ')');
    for (const [q, want] of [['', 1], ['?seed=4242', 0], ['?speed=2', 0], ['?speed=2&colour=family', 0], ['?e1=1', 0],
                             ['?colour=family', 1], ['?guide=0', 1], ['?clarity=realistic', 1], ['?seed=4242&walls=1', 1]]) {
        const p = await bootPage(q);
        const got = p.failed ? 'refused: ' + p.failed : p.M._oc_walls_enabled();
        ok(got === want && p.el('o_walls').checked === !!want,
           (q || 'a bare address') + ': ' + (want ? 'glass walls' : 'wrapping, as before walls') + ' (walls ' + got + ')');
    }
}

/* Deployed-audit PR #30-31, finding 4: the sheet's oc_init arguments were
 * read rounded (getVal: int keys), so Restart with a tank width of 99.6 ran
 * width 100 under a field showing 99.6 (3840.5 ran 3841), where a link or a
 * setup with those numbers is refused. Now they are read as typed and
 * checked as such: refused with the reason, nothing changed; whole numbers
 * in range (and a fractional depth, which oc_init takes) run as shown. */
async function pageSizeFields() {
    section('The page: Restart checks the tank size, depth, fish and seed as typed (deployed audit #30-31, finding 4)');
    const p = await bootPage(PAGE_Q7);
    const bad = [];
    for (const [key, typed] of [['width', '99.6'], ['width', '3840.5'], ['height', '1080.25'], ['population', '12.5'], ['seed', '1.5'],
                                ['seed', '-1'], ['seed', '4294967296'], ['width', ''], ['depth', '9.5']]) {
        const was = p.el('o_' + key).value, print0 = fingerprint(p.M), n0 = p.inits.length, W0 = p.T.W;
        p.edit(key, typed);
        p.click('restart');
        const shown = p.el('o_' + key).value;
        if (p.inits.length !== n0 || fingerprint(p.M) !== print0 || p.T.W !== W0 || shown !== typed || !/Couldn't start that world/.test(p.msg()))
            bad.push(key + ' ' + JSON.stringify(typed) + ': ' + (p.inits.length !== n0 ? 'oc_init ran (width ' + p.T.W + ')' : 'shown ' + shown) + ' — "' + p.msg() + '"');
        p.edit(key, was);
    }
    ok(!bad.length, 'Restart refuses a tank size, fish count or seed that is not a whole number in range, as typed (99.6, 3840.5, ' +
       '1080.25, 12.5 fish, seed 1.5 / -1 / 2^32, an empty width, depth 9.5): no oc_init, the field as typed' + (bad.length ? ' — ' + bad.join('; ') : ''));
    p.edit('width', '3840'); p.edit('depth', '237.5');
    p.click('restart');
    const askedFirst = asked(p);   /* (edits wait: the approved rule asks first, review of #39 finding 8) */
    if (askedFirst) p.click('startconfirm');
    ok(askedFirst && p.T.W === 3840 && p.T.D === 237.5 && /[?&]w=3840/.test(p.loc.href) && p.T.initArgs.depth === 237.5,
       'whole numbers in range run as shown (asked first: they wait): width 3840, depth 237.5 (a depth need not be whole) (' + p.T.W + ' x ' + p.T.H + ' x ' + p.T.D + ')');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
}

/* PR #34 review: what the page writes out (Save setup's file, the address
 * a load or Restart writes) must start the world it ran. perceptionRadius
 * -1e400 (now reaching oc_init as a number) was raised to 1 by the
 * engine's clamp before its finite check, so it ran radius 1, while the
 * page kept -Infinity and wrote it out as null: reloaded, the default 100.
 * Now the clamp raises only a finite radius and oc_init refuses -inf. Here:
 * the review's file (refused, nothing changed); every key the engine reads
 * as a number at +-1e400 is refused or not read at all (so no accepted
 * setup holds a non-finite value that matters); and accepted setups,
 * clamped and repeated values among them, come back as the same world and
 * sheet from Save setup's file and from their address on a new page. */
async function pageRoundTrip() {
    section('The page: Save setup\'s file and the address start the world that ran (PR #34 review)');
    const setup = (config) => '{"format":"evo_ocean_setup","version":1,"seed":7,"population":12,"width":300,"height":300,"depth":240,' +
                              '"config":' + config + '}';
    const load = (p, text) => p.loadSetup(text);
    const REVIEW = '{"perceptionRadius":-1e400}';
    {   /* every number key the engine's readers know (SimConfig's and the Ocean's) */
        const keys = [...new Set(['src/core/checkpoint_io.hpp', 'src/ocean/ocean_config.hpp'].flatMap(f =>
            [...fs.readFileSync(path.join(ROOT, f), 'utf8').matchAll(/(?:floatOr|numOr|intOr|doubleOr|readFloat|readNum)\("([A-Za-z0-9_]+)"/g)].map(m => m[1])))];
        const M = await mk(1, {}, 300, 300, 0), base = directInit(M, '{}').print, bad = [];
        let refused = 0, unread = 0;
        for (const k of keys)
            for (const v of ['1e400', '-1e400']) {
                const r = directInit(M, '{"' + k + '":' + v + '}');
                if (!r.ok) refused++;
                else if (r.print === base) unread++;
                else bad.push(k + '=' + v);
            }
        ok(keys.length > 60 && !bad.length, keys.length + ' number keys the engine reads, at +-1e400: ' + refused + ' refused, ' + unread +
           ' accepted only where oc_init does not read the key (the world is {}\'s)' + (bad.length ? ' — accepted and run: ' + bad.join(' ') : ''));
    }
    const p = await bootPage(PAGE_Q7);
    {
        const print0 = fingerprint(p.M), state0 = p.world();
        const why = await load(p, setup(REVIEW));
        ok(/refused/.test(why) && /perceptionRadius/.test(why) && fingerprint(p.M) === print0 && p.world() === state0 && p.T.draft && p.T.draft.kind === 'file',
           'the review\'s setup (version 1, 300 x 300, perceptionRadius -1e400) is refused, the world and address kept, the file still staged to fix ("' + why + '")');
    }
    const probe = await mk(1, {}, 300, 300, 0), e1 = HO.cString(probe, probe._oc_e1_preset());
    for (const config of ['{}', '{"perceptionRadius":0}', '{"perceptionRadius":0.5,"interactRadius":0}', '{"perceptionRadius":-5}',
                          '{"perceptionRadius":120}', '{"foodEnergy":5,"foodEnergy":9}', '{"lightEnabled":true,"lightEnabled":0}',
                          '{"mouthGate":1,"kMouth":1.5}', '{"walls":1}', '{"bodyLen":1e400}', '{"perceptionRadius":100,"perceptionRadius":-1e400}',
                          e1, REVIEW]) {
        const said = await load(p, setup(config));
        if (!/^Setup loaded/.test(said)) {
            ok(config === REVIEW, config + ': ' + (config === REVIEW ? 'refused (above)' : 'not loaded: "' + said + '"'));
            continue;
        }
        const print1 = stepped(p.M), form1 = p.form(), href = p.loc.href;
        p.click('savecp');
        const said2 = await load(p, p.blobs[p.blobs.length - 1]);
        const print2 = stepped(p.M), form2 = p.form();
        const fresh = await bootPage(new URL(href).search);
        const print3 = fresh.failed ? 'refused: ' + fresh.failed : stepped(fresh.M), form3 = fresh.failed ? '' : fresh.form();
        ok(/^Setup loaded/.test(said2) && print2 === print1 && form2 === form1 && print3 === print1 && form3 === form1,
           config.slice(0, 60) + (config.length > 60 ? '…' : '') + ': Save setup -> load, and its address -> a new page: the same world and sheet' +
           (print2 !== print1 ? ' — the saved file runs another world' : '') + (form2 !== form1 ? ' — the saved file shows another sheet' : '') +
           (print3 !== print1 ? ' — the address runs another world (' + print3.slice(0, 40) + ')' : '') + (form3 !== form1 && print3 === print1 ? ' — the address shows another sheet' : ''));
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers');
}

/* ---------------------------------------------------------------------
 * Post-merge audit of main 43fedc0 (#32-#35), its findings on the page's
 * controls. These run the real ocean.js (and ocean_perf.js / guide.js
 * where ocean.html loads them) on the test DOM: keys dispatched as a
 * browser does (the window's capture listeners first, a focused control's
 * own keys), :focus-visible while the keyboard is in use, the 960 px media
 * query as a list that changes and tells its listeners. Layout, stacking
 * and real focus are the browser script's (pagefix4/ui_matrix.cjs).
 * --------------------------------------------------------------------- */
const sheetOpen = (p) => p.el('drawer').classList.contains('open');
const dashUp = (p) => p.ctx.EvoOceanDash.isOpen();
const focused = (p) => (p.doc.activeElement && p.doc.activeElement.id) || null;

/* Finding 1: the benchmark's colour mode went to a <span>'s .value (the
 * View menu's buttons replaced the select), so a case "in Brain" ran in
 * Appearance. Finding 12: bench.info() read a class #dash never has. */
async function pageColourBench() {
    section('The page: the benchmark runs in the colour mode it names, and reads the charts\' state (audit 43fedc0, findings 1 and 12)');
    const p = await bootPage('?renderBench=1&' + PAGE_Q.slice(1), { perf: true });
    const B = p.ctx.EvoOcean && p.ctx.EvoOcean.bench;
    if (!B) { ok(false, 'EvoOcean.bench with ?renderBench=1 and ocean_perf.js (' + (p.failed || 'none') + ')'); return; }
    const look = () => {
        const st = p.ctx.EvoOcean.state();
        return { mode: st.colourMode, brain: st.colourBrain, skin: p.ctx.EvoOcean.scene.appearance().skin,
                 pressed: p.el('colourMode').querySelectorAll('button[aria-pressed="true"]').map(b => b.dataset.c).join() };
    };
    for (const m of ['brain', 'family', 'appearance']) {
        let prep = null, err = '';
        try { prep = await p.pump(B.prepare({ colourMode: m, settleMs: 0 })); } catch (e) { err = String(e && e.message || e); }
        const l = look(), info = B.info();
        ok(prep && prep.colourMode === m && info.colourMode === m && l.mode === m && l.pressed === m && l.brain === (m === 'brain') &&
           l.skin === (m === 'appearance'),
           'prepare({colourMode: "' + m + '"}): the page is in it — the controller, its pressed button, colourBrain ' + (m === 'brain') +
           ', the scene\'s skin ' + (m === 'appearance') + '; the case and info() report it (' +
           (err || 'case ' + (prep && prep.colourMode) + ', info ' + info.colourMode + ', page ' + JSON.stringify(l)) + ')');
    }
    ok(p.ctx.localStorage.getItem('evo_boids.colourBy') === null, 'the benchmark\'s colour modes were not stored as the visitor\'s choice');
    {
        let bad = false;
        try { await p.pump(B.prepare({ colourMode: 'rainbow', settleMs: 0 })); } catch (e) { bad = /colour mode rainbow/.test(String(e && e.message)); }
        ok(bad && look().mode === 'appearance', 'a case with an unknown colour mode is refused, the mode kept');
    }
    const seen = [];
    seen.push([B.info().dashboardOpen, dashUp(p)]);
    p.ctx.EvoOceanDash.open();
    seen.push([B.info().dashboardOpen, dashUp(p)]);
    await p.pump(B.capture({ durationMs: 30, drainMs: 0, raw: true }));
    seen.push([B.info().dashboardOpen, dashUp(p)]);
    p.ctx.EvoOceanDash.close();
    seen.push([B.info().dashboardOpen, dashUp(p)]);
    ok(seen.map(String).join(' ') === 'false,false true,true true,true false,false',
       'bench.info().dashboardOpen is EvoOceanDash.isOpen() closed, open, after a capture with them open, closed again (' + seen.map(s => s.join('/')).join(' ') + ')');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 2: I opened the live numbers under the charts or a narrow
 * screen's settings, and the charts' Esc closed them too. Finding 8: an
 * open coach mark stayed over the fish card, the live numbers, the charts. */
async function pageLayers() {
    section('The page: the live numbers open on top, the charts\' Esc leaves them, the coach mark gives way (audit 43fedc0, findings 2 and 8)');
    const p = await bootPage(PAGE_Q);   /* a narrow screen: matchMedia false */
    p.key('g');
    const g1 = dashUp(p);
    p.key('i');
    ok(g1 && !dashUp(p) && p.shown('statpanel') && p.T.statOpen, 'G then I: the charts close and the live numbers show (charts ' + g1 + ' -> ' + dashUp(p) + ')');
    ok(p.doc.body.classList.contains('stat-open'), '  the body says so (stat-open: the Fit button waits, rather than cover their first rows)');
    p.key('Escape');
    p.key('o');
    const o1 = sheetOpen(p);
    p.key('i');
    ok(o1 && !sheetOpen(p) && p.shown('statpanel'), 'O then I below 960 px: the settings sheet closes, the live numbers show (sheet ' + o1 + ' -> ' + sheetOpen(p) + ')');
    p.key('Escape');
    p.key('v');
    p.key('i');
    ok(p.T.openPop === null && p.shown('statpanel'), 'V then I: the View menu closes, the live numbers show');
    p.key('Escape');
    p.key('i'); p.key('g');
    const both = p.shown('statpanel') && dashUp(p);
    p.key('Escape');
    ok(both && !dashUp(p) && p.shown('statpanel'), 'I, G, Esc: Esc closes the charts and only them: the live numbers are still there (' + p.shown('statpanel') + ')');
    p.key('Escape');
    ok(!p.shown('statpanel'), 'a second Esc closes the live numbers');
    p.resize(1400, 900);
    p.key('o'); p.key('i');
    ok(sheetOpen(p) && p.shown('statpanel'), 'O then I on a wide screen: the settings panel stays beside the live numbers');
    p.key('Escape'); p.key('Escape');
    p.resize(1920, 1080); p.resize(800, 900);
    /* the coach mark, shown, then each surface that opens where it sits */
    const surfaces = [['selecting a fish', () => p.ctx.EvoOcean.select(0)], ['I', () => p.key('i')], ['the readout', () => p.click('readout')],
                      ['G', () => p.key('g')], ['the charts button', () => p.click('dashbtn')]];
    for (const [what, act] of surfaces) {
        p.ctx.EvoOceanDash.close(); if (p.T.statOpen) p.click('readout'); p.ctx.EvoOcean.select(-1);
        p.el('coach').hidden = false;
        act();
        ok(!p.shown('coach'), 'the coach mark goes when ' + what + ' opens ' + (what === 'selecting a fish' ? 'its card' : what === 'G' || what === 'the charts button' ? 'the charts' : 'the live numbers'));
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 3: Settings beside a popover (or the live numbers) on a wide
 * screen, then narrower than 960 px: the sheet covered them. */
async function pageResize() {
    section('The page: crossing 960 px with the settings and a popover or the live numbers open (audit 43fedc0, finding 3)');
    for (const [w, h] of [[890, 453], [390, 844]]) {
        const p = await bootPage(PAGE_Q, { media: { '(min-width: 960px)': true } });
        p.ctx.innerWidth = 1000; p.ctx.innerHeight = 700;
        for (const pop of ['view', 'help']) {
            p.click('menubtn');
            p.click(pop === 'view' ? 'viewmenubtn' : 'helpbtn');
            const before = sheetOpen(p) && p.T.openPop === pop;
            p.resize(w, h);
            ok(before && !sheetOpen(p) && p.T.openPop === pop && p.shown(pop + 'pop'),
               'wide, Settings and ' + pop + ' open, then ' + w + ' x ' + h + ': the sheet closes, ' + pop + ' stays (sheet ' + sheetOpen(p) + ', popover ' + p.T.openPop + ')');
            p.click(pop + 'close');
            ok(p.T.openPop === null, '  and its × closes it');
            p.resize(1000, 700);
        }
        p.click('menubtn'); p.click('readout');
        const before = sheetOpen(p) && p.shown('statpanel');
        p.resize(w, h);
        ok(before && !sheetOpen(p) && p.shown('statpanel'), 'wide, Settings and the live numbers open, then ' + w + ' x ' + h + ': the sheet closes, the numbers stay');
        p.resize(1000, 700);
        p.click('readout'); p.click('menubtn');
        p.resize(w, h);
        ok(sheetOpen(p), 'the settings alone stay open across the breakpoint');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
}

/* Finding 4: with a button focused (as Esc leaves the View button) every
 * letter shortcut was ignored; V and ? opened without the focus. */
async function pageKeys() {
    section('The page: shortcuts with a control focused, and V / ? opening with the focus (audit 43fedc0, finding 4)');
    const p = await bootPage(PAGE_Q);
    p.tabTo('viewmenubtn');
    p.key('Enter');
    const opened = p.T.openPop === 'view' && focused(p) === 'lightnow';
    p.key('Escape');
    ok(opened && p.T.openPop === null && focused(p) === 'viewmenubtn',
       'Tab to View, Enter: it opens with the focus on its first switch; Esc: closed, the focus back on View (' + focused(p) + ')');
    const light0 = p.el('lightbtn').getAttribute('aria-pressed');
    p.key('l');
    const light1 = p.el('lightbtn').getAttribute('aria-pressed');
    p.key('f');
    const sel = p.ctx.EvoOcean.state().selectedId;
    p.key('+');
    const spd = p.el('speedlabel').textContent;
    p.key('c');
    ok(light0 === 'false' && light1 === 'true' && sel !== null && spd === '2×' && p.uncaught.length === 0,
       'then, View still focused: L turns the light on (' + light0 + ' -> ' + light1 + '), F follows a fish (' + sel + '), + speeds up (' + spd + '), C fits the view');
    p.key('Escape');
    p.key('v');
    const v1 = p.T.openPop === 'view' && focused(p) === 'lightnow';
    p.key('v');
    ok(v1 && p.T.openPop === null && focused(p) === 'viewmenubtn', 'V opens View with the focus inside; V again closes it, the focus back on View (' + focused(p) + ')');
    p.key('?', { shift: true });
    const h1 = p.T.openPop === 'help' && focused(p) === 'tourbtn';
    p.key('Escape');
    ok(h1 && p.T.openPop === null && focused(p) === 'helpbtn', '? opens Help with the focus on its first button; Esc closes it, the focus back on Help (' + focused(p) + ')');
    p.key('v');
    const paused0 = p.T.paused, sw0 = p.el('lightnow').checked;
    p.key(' ');
    ok(p.T.paused === paused0 && p.el('lightnow').checked !== sw0 && p.el('lightbtn').getAttribute('aria-pressed') === String(!sw0),
       'Space on the focused flashlight switch turns it, and does not pause (switch ' + sw0 + ' -> ' + p.el('lightnow').checked + ')');
    p.key('l');
    ok(p.el('lightnow').checked === sw0, '  L there turns the light back (a switch is not a text field)');
    p.key('Escape');
    p.key(' ');
    ok(p.T.paused === paused0 && p.T.openPop === 'view', 'Space on the focused View button presses it (View opens), and does not pause');
    p.key('Escape');
    p.tabTo('o_kBuoy');
    p.key('l');
    ok(p.el('lightnow').checked === sw0, 'a number field keeps its keys: L typed there is no shortcut');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 5: no WebGL2, and the landing page's error splash had no way on;
 * finding 11: "Open it with the default settings" kept ?speed=, so it
 * started a wrapping world where a fresh visit has glass walls. */
async function pageStartupFailures() {
    section('The page: a start that fails offers 2-D Classic, and "default settings" is a fresh visit (audit 43fedc0, findings 5 and 11)');
    {
        const p = await bootPage(PAGE_Q, { nogl: true });
        const c = p.el('splashclassic');
        ok(/WebGL2/.test(p.failed) && c && c.isConnected && c.href === p.el('to2d').href && /\/index\.html$/.test(c.href),
           'no WebGL2: the splash says why and offers "Open 2-D Classic", at #to2d\'s address (' + (c ? c.href : 'none') + '; "' + p.failed.split('\n').pop() + '")');
    }
    {
        const p = await bootPage(PAGE_Q, { nosimd: true });
        ok(/SIMD/.test(p.failed) && !p.el('splashclassic'), 'no WebAssembly SIMD: no Classic offered (its modules need SIMD too)');
    }
    {
        const p = await bootPage('?speed=2&colour=family&cfg=' + encodeURIComponent('{"maxPopulation":0.5}'));
        const a = p.el('splashplain'), c = p.el('splashclassic'), u = a ? new URL(a.href) : null;
        const left = u ? ['seed', 'pop', 'depth', 'w', 'h', 'cfg', 'speed', 'e1', 'mock', 'walls'].filter(k => u.searchParams.has(k)) : null;
        ok(/refused/.test(p.failed) && u && left.length === 0 && u.searchParams.get('colour') === 'family' && c,
           'a refused link with ?speed=: "Open it with the default settings" drops every world key (' + (u ? u.search : 'no link') + '), and Classic is offered too');
        const q = await bootPage(u ? u.search : '?speed=2');
        ok(!q.failed && q.M._oc_walls_enabled() === 1 && q.el('o_walls').checked, 'that link starts as a bare address does: glass walls (' + (q.failed || 'walls ' + q.M._oc_walls_enabled()) + ')');
    }
}

/* Finding 9: in the tour's "Your own settings", Esc in a number field
 * closed the settings (the page's) but not the tour (guide.js's typing
 * guard came first), which then pointed at nothing. */
async function pageTourEscape() {
    section('The page: Esc in a field during the tour ends the tour, once (audit 43fedc0, finding 9)');
    const p = await bootPage(PAGE_Q, { guide: true });
    const title = () => { const g = p.el('guide'), h = g && g.querySelector('h2'); return h ? h.textContent : ''; };
    p.ctx.EvoGuide.start();
    for (let i = 0; i < 20 && title() !== 'Your own settings'; i++) p.key('ArrowRight');
    ok(title() === 'Your own settings' && sheetOpen(p), 'the tour is at "Your own settings", its settings open');
    p.tabTo('o_kBuoy');
    p.key('ArrowRight');
    ok(title() === 'Your own settings', '  an arrow key in its number field stays the field\'s (the tour waits)');
    p.key('Escape');
    ok(!p.el('guide') && !sheetOpen(p) && focused(p) === null,
       'Esc in that field ends the tour, which closes its settings: no tour left pointing at a closed sheet (tour ' + !!p.el('guide') + ', sheet ' + sheetOpen(p) + ')');
    p.ctx.EvoGuide.start();
    p.key('i');
    const both = !!p.el('guide') && p.shown('statpanel');
    p.key('Escape');
    ok(both && !p.el('guide') && p.shown('statpanel'), 'the live numbers opened during the tour: Esc ends the tour and leaves them (' + p.shown('statpanel') + ')');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 10: a whole-number setting typed 300.5 ran as 301 (live, and on
 * Restart) under a field showing 300.5. */
async function pageWholeFields() {
    section('The page: whole-number settings typed with a fraction are refused, not rounded (audit 43fedc0, finding 10)');
    const p = await bootPage(PAGE_Q7);
    const sets0 = p.sets.length, run0 = JSON.stringify(p.T.runCfg), print0 = fingerprint(p.M);
    p.edit('maxPopulation', '300.5');
    ok(p.sets.length === sets0 && JSON.stringify(p.T.runCfg) === run0 && fingerprint(p.M) === print0 && p.el('o_maxPopulation').value === '0' &&
       /whole number/.test(p.msg()),
       'live: the population cap (maxPopulation) 300.5 is refused visibly, nothing sent to the world, the field back to what runs ("' + p.msg() + '"; field ' +
       p.el('o_maxPopulation').value + ')');
    p.edit('maxPopulation', '300');
    ok(p.T.runCfg.maxPopulation === 300 && p.sets.length === sets0 + 1 && p.sets[sets0][1] === 'maxPopulation' && p.sets[sets0][2] === 300,
       '  300 applies live');
    for (const [key, typed, def] of [['predatorCount', '1.5', '0'], ['genomeMaxLength', '80.5', '80'], ['foodPatches', '0.5', '0']]) {
        const n0 = p.inits.length, pr0 = fingerprint(p.M);
        p.edit(key, typed);
        p.click('restart');
        ok(p.inits.length === n0 && fingerprint(p.M) === pr0 && p.el('o_' + key).value === typed && /whole number/.test(p.msg()) &&
           new RegExp('got ' + typed.replace('.', '\\.')).test(p.msg()),
           'Restart with ' + key + ' ' + typed + ': refused with the reason, no oc_init, the field as typed ("' + p.msg() + '")');
        p.edit(key, def);
    }
    p.edit('predatorCount', '2');
    p.start();   /* (the live 300 above: the page asks first) */
    ok(p.T.initArgs.cfg.predatorCount === 2 && p.T.runCfg.predatorCount === 2, 'a whole number runs as typed (predatorCount 2)');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* ---------------------------------------------------------------------
 * Review of PR #37 (Codex, 2026-11-01): its findings, and the coverage it
 * asked for where the test DOM can show it.
 * --------------------------------------------------------------------- */

/* Review finding 1: a valid edit of a key on its way to the world (held
 * while Turbo starts or stops, or sent and not yet answered), then a
 * fraction of the same key, refused: the field went back to what ran
 * before and lost the held edit's note, and the valid edit then applied
 * under a field showing the old value. */
async function pageTurboFraction() {
    section('The page: a fraction refused while a valid edit of the key is on its way keeps that edit in the field (review of PR #37, finding 1)');
    const look = (p) => ({ field: p.el('o_maxPopulation').value, note: p.note('maxPopulation') });
    const twoEdits = (p) => { p.edit('maxPopulation', '300'); p.edit('maxPopulation', '300.5'); return Object.assign(look(p), { msg: p.msg() }); };
    const answered = (sh) => sh.delivered.filter(isType('set')).length === sh.toWorker.filter(m => m.cmd === 'set').length;
    {   /* entering: the first stats held */
        const p = await bootPage(PAGE_Q);
        p.hooks.onWorker = (sh) => sh.pause();
        p.click('turbobtn');
        const sh = p.worker();
        await until(() => sh.queued(isType('stats')), 'the first stats');
        const mid = twoEdits(p);
        sh.resume();
        await until(() => p.T.turboState === 'turbo' && answered(sh) && sh.toWorker.some(m => m.cmd === 'set'), 'the held edit\'s answer');
        const after = look(p);
        ok(p.T.turboState === 'turbo' && mid.field === '300' && /as soon as Turbo has started/.test(mid.note) && /whole number/.test(mid.msg) &&
           setsTo(sh) === 'maxPopulation=300' && p.T.runCfg.maxPopulation === 300 && after.field === '300' && after.note === '',
           'entering: 300 held, 300.5 refused: the field shows the held 300 with its note ("' + mid.note + '"); the worker gets 300 alone; then 300, no note (' +
           JSON.stringify({ mid, after, sent: setsTo(sh) }) + ')');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        ok(p.T.runCfg.maxPopulation === 300 && look(p).field === '300', '  handed back: 300 runs and shows');
    }
    {   /* exiting: the memory held */
        const { p, sets0, sh } = await pageInTurbo();
        sh.pause();
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the memory');
        const mid = twoEdits(p);
        sh.resume();
        await until(() => p.T.turboState === 'live', 'the hand-back');
        const after = look(p), applied = p.sets.slice(sets0).map(e => e[1] + '=' + e[2]).join(',');
        ok(mid.field === '300' && /as soon as Turbo hands the world back/.test(mid.note) && applied === 'maxPopulation=300' &&
           p.T.runCfg.maxPopulation === 300 && after.field === '300' && after.note === '',
           'exiting: 300 held, 300.5 refused: the field keeps 300 and its note; the page applies 300 alone on the world handed back (' +
           JSON.stringify({ mid, after, applied }) + ')');
    }
    {   /* an acknowledgment outstanding: 300 sent, its answer held */
        const { p, sh } = await pageInTurbo();
        sh.pause();
        p.edit('maxPopulation', '300');
        await until(() => sh.queued((m) => m.type === 'set'), 'its answer');
        p.edit('maxPopulation', '300.5');
        const mid = look(p);
        p.el('o_maxPopulation').value = '0';   /* and the field shown stale, as a refusal before this fix left it */
        sh.resume();
        await until(() => answered(sh) && sh.delivered.some(isType('set')), 'the answer');
        const after = look(p);
        ok(mid.field === '300' && mid.note === '' && setsTo(sh) === 'maxPopulation=300' && p.T.runCfg.maxPopulation === 300 && after.field === '300',
           'an answer outstanding: 300.5 refused leaves the field at the 300 on its way; the answer, with nothing newer on its way, puts the field right (' +
           JSON.stringify({ mid, after }) + ')');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        ok(p.T.runCfg.maxPopulation === 300 && look(p).field === '300' && p.uncaught.length === 0, '  handed back: 300 runs and shows; no exception escaped');
    }
}

/* Review finding 2: the live numbers opened under a fish card where the two
 * overlap (a phone; a card flipped to the top, its brain open). The newer
 * of the two shows; the fish stays selected while its card waits. Boxes
 * given here (the test DOM has no layout). */
async function pageCardNumbers() {
    section('The page: the live numbers and a fish card, where they overlap: the newer shows (review of PR #37, finding 2)');
    const p = await bootPage(PAGE_Q);
    const run = () => p.T.frame(performance.now());
    const box = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b });
    p.click('pausebtn');
    p.el('statpanel')._rect = box(10, 64, 350, 654);
    p.el('fishcard')._rect = box(10, 64, 380, 520);   /* a phone's card flipped to the top, its brain open */
    p.ctx.EvoOcean.select(0); run();
    if (p.el('iexpand').getAttribute('aria-expanded') !== 'true') p.click('iexpand');
    p.el('fishcard').classList.add('flip'); run();
    const id0 = p.ctx.EvoOcean.state().selectedId, card0 = p.shown('fishcard');
    p.key('i'); run(); run();
    ok(card0 && p.shown('statpanel') && !p.shown('fishcard') && p.ctx.EvoOcean.state().selectedId === id0 &&
       p.el('iexpand').getAttribute('aria-expanded') === 'true',
       'a flipped card with its brain open, then I: the numbers show, the card waits, its fish still selected (' + id0 + ')');
    p.key('Escape'); run();
    ok(!p.shown('statpanel') && p.shown('fishcard') && p.ctx.EvoOcean.state().selectedId === id0,
       '  Esc closes the numbers (the visible layer), and the card is back');
    p.click('readout'); run();
    const held = p.shown('statpanel') && !p.shown('fishcard');
    p.ctx.EvoOcean.select(1); run();
    const id1 = p.ctx.EvoOcean.state().selectedId;
    ok(held && id1 !== id0 && !p.shown('statpanel') && p.shown('fishcard'),
       'the numbers open (the readout), then another fish picked: its card shows and the numbers close (' + id0 + ' -> ' + id1 + ')');
    p.el('fishcard')._rect = box(1530, 76, 1910, 600);   /* a wide screen's card, at the right */
    p.key('i'); run(); run();
    ok(p.shown('statpanel') && p.shown('fishcard'), 'where they do not overlap (a wide screen), both stay');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Review finding 3: "Open it with the default settings" kept Classic's
 * routing keys, so a refused link with ?threads= (or view, bench, ...) and
 * Ocean keys went, once they were dropped, to Classic (ocean.html's head). */
async function pageMixedRecovery() {
    section('The page: the default-settings recovery of a link with Classic\'s keys stays on the Ocean (review of PR #37, finding 3)');
    const html = fs.readFileSync(path.join(WEB, 'ocean.html'), 'utf8'), js = fs.readFileSync(path.join(WEB, 'ocean.js'), 'utf8');
    const list = (src, name) => { const m = new RegExp('var ' + name + ' = (\\[[^\\]]*\\])').exec(src); return m ? JSON.parse(m[1]) : null; };
    const CLASSIC_ONLY = list(html, 'CLASSIC_ONLY'), OCEAN_ONLY = list(html, 'OCEAN_ONLY'), CLASSIC_KEYS = list(js, 'CLASSIC_KEYS');
    ok(CLASSIC_ONLY && JSON.stringify(CLASSIC_KEYS) === JSON.stringify(CLASSIC_ONLY), 'web/ocean.js\'s CLASSIC_KEYS are ocean.html\'s CLASSIC_ONLY (' + JSON.stringify(CLASSIC_KEYS) + ')');
    /* ocean.html's head: a query with a Classic-only key and no Ocean-only one goes to Classic */
    const toClassic = (q) => CLASSIC_ONLY.some(k => q.has(k)) && !OCEAN_ONLY.some(k => q.has(k));
    for (const extra of ['threads=0', 'view=flat', 'bench=1', 'threads=0&view=flat&fish=500&gl=0&nthreads=2&bench=1']) {
        const p = await bootPage('?speed=2&' + extra + '&colour=family&clarity=realistic&cfg=' + encodeURIComponent('{"maxPopulation":0.5}'));
        const a = p.el('splashplain'), u = a ? new URL(a.href) : null;
        const left = u ? [...u.searchParams.keys()] : null;
        ok(/refused/.test(p.failed) && u && !toClassic(u.searchParams) && left.join() === 'colour,clarity',
           '?speed=2&' + extra + ' refused: the recovery keeps only colour and clarity (' + (u ? u.search : 'no link') + ') and stays on the Ocean');
    }
    const q = await bootPage('?colour=family&clarity=realistic');
    ok(!q.failed && q.M._oc_walls_enabled() === 1, '  it starts as a fresh visit: glass walls');
}

/* Review finding 4: one owner for each Esc. The tour (on top), then the
 * charts, then the page's own; with the tour and the charts open, one Esc
 * closed both. */
async function pageEscOwner() {
    section('The page: one Esc, one owner: the tour, then the charts, then the page (review of PR #37, finding 4)');
    const p = await bootPage(PAGE_Q, { guide: true });
    p.ctx.EvoGuide.start();
    p.key('g');
    const both = !!p.el('guide') && dashUp(p);
    p.key('Escape');
    const one = !p.el('guide') && dashUp(p);
    p.key('Escape');
    ok(both && one && !dashUp(p), 'the tour and the charts open: the first Esc ends the tour only, the second closes the charts');
    p.key('i'); p.key('g');
    p.ctx.EvoGuide.start();
    const three = !!p.el('guide') && dashUp(p) && p.shown('statpanel');
    p.key('Escape');
    const s1 = [!!p.el('guide'), dashUp(p), p.shown('statpanel')].join();
    p.key('Escape');
    const s2 = [!!p.el('guide'), dashUp(p), p.shown('statpanel')].join();
    p.key('Escape');
    const s3 = [!!p.el('guide'), dashUp(p), p.shown('statpanel')].join();
    ok(three && s1 === 'false,true,true' && s2 === 'false,false,true' && s3 === 'false,false,false',
       'the live numbers, the charts and the tour: three presses, one layer each, from the top (tour, charts, numbers left: ' + [s1, s2, s3].join(' | ') + ')');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Review findings 5 and 6: a focused settings tab's arrows also paged the
 * tour; the charts' tabs reserved the arrows (role tab) without moving. */
async function pageTabKeys() {
    section('The page: the tabs\' own arrow keys (settings, charts), during the tour too (review of PR #37, findings 5 and 6)');
    const p = await bootPage(PAGE_Q, { guide: true });
    const title = () => { const g = p.el('guide'), h = g && g.querySelector('h2'); return h ? h.textContent : ''; };
    const dt = () => p.el('dtabs').children, sel = () => dt().findIndex(b => b.getAttribute('aria-selected') === 'true');
    /* the charts' tabs, no tour */
    p.key('g');
    const n = dt().length;
    p.focusVisible = true; dt()[sel()].focus();
    const s0 = sel(), spd0 = p.el('speedlabel').textContent;
    p.key('ArrowRight');
    const s1 = sel(), f1 = p.doc.activeElement === dt()[s1];
    p.key('End'); const s2 = sel();
    p.key('Home'); const s3 = sel();
    p.key('ArrowLeft'); const s4 = sel();
    p.key('ArrowUp');
    ok(n > 2 && s1 === (s0 + 1) % n && f1 && s2 === n - 1 && s3 === 0 && s4 === n - 1 && p.doc.activeElement === dt()[n - 1] &&
       p.el('speedlabel').textContent === spd0,
       'the charts\' tabs: Right, End, Home, Left move the selection and the focus (' + [s0, s1, s2, s3, s4].join(' -> ') + ' of ' + n + '); the arrows are not speed keys there');
    ok(dt().every((b, i) => b.tabIndex === (i === sel() ? 0 : -1)), '  Tab lands on the selected one (roving tabindex)');
    p.key('Enter');
    ok(p.doc.activeElement === dt()[sel()], '  Enter on a focused tab keeps the focus there');
    p.key('Escape');
    /* the tour: a focused settings tab's arrows are the tab's */
    p.ctx.EvoGuide.start();
    for (let i = 0; i < 20 && title() !== 'Your own settings'; i++) { p.doc.activeElement = null; p.key('ArrowRight'); }
    const at = title(), tabSel = () => p.el('tabs').children.findIndex(b => b.getAttribute('aria-selected') === 'true');
    const t0 = tabSel();
    p.tabTo(p.el('tabs').children[t0].id);
    p.key('ArrowRight');
    ok(at === 'Your own settings' && tabSel() === t0 + 1 && title() === 'Your own settings',
       'the tour at "Your own settings", a settings tab focused: Right moves the tab (' + t0 + ' -> ' + tabSel() + ') and the tour stays (' + title() + ')');
    p.key('g');
    p.focusVisible = true; dt()[sel()].focus();
    const c0 = sel();
    p.key('ArrowRight');
    ok(sel() === (c0 + 1) % n && title() === 'Your own settings', '  a chart tab focused: Right moves the chart tab, the tour stays');
    p.doc.activeElement = null;
    p.key('ArrowRight');
    ok(title() === 'You\'re set', '  with nothing focused, Right pages the tour (' + title() + ')');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* The review's coverage: a whole number written 300.0 (a float that is
 * whole) is accepted as 300 by the field, a setup file and the link. */
async function pageIntegralFloats() {
    section('The page: 300.0 is a whole number: the field, a setup file and the link take it (review of PR #37, coverage)');
    const p = await bootPage(PAGE_Q7);
    const sets0 = p.sets.length;
    p.edit('maxPopulation', '300.0');
    ok(p.T.runCfg.maxPopulation === 300 && p.sets.length === sets0 + 1 && p.sets[sets0][2] === 300, 'live: 300.0 applies as 300');
    p.edit('predatorCount', '2.0'); p.start();   /* (the live 300.0 above: the page asks first) */
    ok(p.T.initArgs.cfg.predatorCount === 2, 'Restart: predatorCount 2.0 runs as 2 ("' + p.msg() + '")');
    await p.loadSetup('{"format":"evo_ocean_setup","version":1,"seed":7,"population":12.0,"width":1920,' +
                      '"height":1080,"depth":240,"config":{"maxPopulation":300.0}}');
    ok(/^Setup loaded/.test(p.msg()) && p.T.runCfg.maxPopulation === 300 && p.T.initArgs.population === 12, 'a setup file: maxPopulation 300.0, 12.0 fish load ("' + p.msg() + '")');
    const q = await bootPage('?seed=7&pop=12&w=1920&h=1080&walls=0&cfg=' + encodeURIComponent('{"maxPopulation":300.0}'));
    ok(!q.failed && q.T.initArgs.cfg.maxPopulation === 300 && q.el('o_maxPopulation').value === '300', 'the link: cfg maxPopulation 300.0 starts (' + (q.failed || 'field ' + q.el('o_maxPopulation').value) + ')');
}

/* ---------------------------------------------------------------------
 * UI-4 (Turbo as a mode) and UI-3 (one door to a new world): the page's
 * modes and transitions, edits during Turbo, every world start through
 * one commit (startWorld), the draft for the next world and the Start bar.
 * Layout, stacking, touch sizes and real focus are the browser script's
 * (ui_redesign/shots_ui34/ui34_matrix.cjs).
 * --------------------------------------------------------------------- */

/* Live -> Paused -> one step -> Turbo -> Stop, by Space, T and each Stop
 * button alike; a focused field or button keeps Space; speed keys and F in
 * Turbo say why not; the picture's light follows a light edit the worker
 * acknowledged (the page's own module is the world as Turbo took it). */
async function pageTurboMode() {
    section('UI-4: Turbo is a mode of the dock: Live, Paused, a step, Turbo, Stop (Space, T, the strip\'s and the bars\' Stop)');
    const p = await bootPage(PAGE_Q);
    const m0 = modeOf(p);
    p.key(' ');
    const m1 = modeOf(p), f1 = frame(p.M);
    p.key('.'); p.raf(performance.now());
    const f2 = frame(p.M);
    p.raf(performance.now());
    const f3 = frame(p.M);
    ok(m0.rs === 'live' && !m0.on && !m0.strip && m1.rs === 'paused' && p.T.paused && f2 === f1 + 1 && f3 === f2,
       'Live, then Space: Paused (the readout says so); . steps exactly once (frame ' + f1 + ' -> ' + f2 + ' -> ' + f3 + ')');
    p.key('t');
    const m2 = modeOf(p);
    await until(() => p.T.turboState === 'turbo', 'Turbo');
    const sh = p.worker();
    await until(() => sh.delivered.filter(isType('stats')).length >= 3, 'its stats');
    const m3 = modeOf(p);
    ok(m2.state === 'entering' && m2.rs === 'entering' && m2.on && m2.strip && !m2.stop && m3.rs === 'turbo' && m3.on && m3.strip &&
       m3.setup && m3.dash && m3.stop && p.el('ts-gen').textContent !== '–' && p.el('ts-rate').textContent !== '–' && p.ctx.EvoApp.turboActive(),
       'T, paused: Starting Turbo (its Stop waits), then Turbo: the dock\'s strip, the setup sheet\'s and the charts\' bars with Stop, the tank dimmed, ' +
       'generation ' + p.el('ts-gen').textContent + ' and ' + p.el('ts-rate').textContent + ' steps/s (' + JSON.stringify(m3) + ')');
    const spd0 = p.el('speedlabel').textContent;
    p.key('+');
    const note = p.msg();
    p.key('f');
    ok(p.el('speedlabel').textContent === spd0 && /as fast as it can/.test(note) && /picture waits while Turbo runs/.test(toastText(p)),
       'in Turbo, + says Turbo runs at its own speed (the speed stays ' + spd0 + '), F that the picture waits ("' + note + '")');
    p.tabTo('o_kBuoy'); p.key(' ');
    const typed = p.T.turboState;
    p.tabTo('viewmenubtn'); p.key(' ');
    const pressed = p.T.openPop === 'view' && p.T.turboState === 'turbo';
    p.key('Escape'); p.el('viewmenubtn').blur(); p.pointer();
    ok(typed === 'turbo' && pressed, 'Space in a number field types, Space on a focused button presses it: neither stops Turbo');
    {   /* a light edit the worker acknowledges: the picture's light is the acknowledged one */
        const on0 = p.ctx.EvoOcean.state().light.on;
        p.edit('lightEnabled', true);
        await until(() => sh.delivered.some(m => m.type === 'set' && m.key === 'lightEnabled'), 'the answer');
        ok(on0 === false && p.ctx.EvoOcean.state().light.on === true && p.T.runCfg.lightEnabled === true,
           'in Turbo, the light field turned on and acknowledged: the picture is drawn in it (light ' + on0 + ' -> ' + p.ctx.EvoOcean.state().light.on + ')');
    }
    p.key(' ');
    const m4 = modeOf(p);
    await until(() => p.T.turboState === 'live', 'the hand-back');
    const m5 = modeOf(p);
    ok(m4.rs === 'exiting' && m4.strip && !m4.stop && m5.rs === 'live' && !m5.on && !m5.strip && !m5.setup && !m5.dash && !p.T.paused &&
       p.ctx.EvoOcean.state().light.on === true && !p.ctx.EvoApp.turboActive(),
       'Space in Turbo: Stopping Turbo, then Live (running, as after every Stop), strip and bars gone, the light as acknowledged (' + JSON.stringify(m5) + ')');
    const ways = [['T', () => p.key('t')], ['the strip\'s Stop', () => p.click('turboexit')], ['the setup sheet\'s Stop', () => p.click('setup-turbo-stop')],
                  ['the charts\' Stop', () => p.click('dash-turbo-stop')]];
    const stopped = [];
    for (const [what, act] of ways) {
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        act();
        const st = p.T.turboState;
        await until(() => p.T.turboState === 'live', 'the hand-back');
        if (st === 'exiting') stopped.push(what);
    }
    ok(stopped.length === ways.length, 'each Stop stops it the same way: ' + stopped.join(', '));
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* the page's world starts so far: oc_init calls (refused ones too), oc_reset calls, the epoch */
function startCounter(p) {
    if (p.resets === undefined) {
        p.resets = 0;
        const r = p.M._oc_reset;
        p.M._oc_reset = function () { p.resets++; return r.apply(this, arguments); };
    }
    return () => ({ inits: p.inits.length, resets: p.resets, epoch: p.T.worldEpoch });
}
const delta = (a, b) => ({ inits: b.inits - a.inits, resets: b.resets - a.resets, epoch: b.epoch - a.epoch });
const asked = (p) => !!p.T.asking && !p.el('startask').hidden;

/* UI-4 / UI-3, one door: every world-starting path reaches startWorld and
 * moves the epoch exactly once; the only oc_init / oc_reset calls are
 * startWorld's; the inline question before a run with something to lose
 * (a live tweak, five simulated minutes, Turbo); and during Turbo, Stop
 * Turbo & start: the ordinary hand-back first, then the start, or no start
 * (a refused edit or a change meanwhile, Stop, a failing worker, a refused
 * hand-back, a world the engine refuses), never a stale message's. */
async function pageStartDoor() {
    section('UI-4: one door to a new world: every start through startWorld, the question before losing a run, Stop Turbo & start');
    {   /* the only world-changing calls are startWorld's */
        const src = fs.readFileSync(path.join(WEB, 'ocean.js'), 'utf8');
        const where = (re) => [...src.matchAll(re)].map(m => { const f = src.lastIndexOf('\n  function ', m.index); return /function (\w+)/.exec(src.slice(f, f + 60))[1]; });
        const init = where(/M\._oc_init\(/g), reset = where(/M\._oc_reset\(/g), iw = where(/[!\s]initWorld\(/g).filter(n => n !== 'initWorld');
        ok(init.join() === 'initWorld' && reset.join() === 'startWorld' && iw.join() === 'startWorld',
           'web/ocean.js calls oc_init only in initWorld, oc_reset and initWorld only in startWorld (' + init + ' / ' + reset + ' / ' + iw + ')');
    }
    const p = await bootPage(PAGE_Q7);
    const c = startCounter(p);
    const v1 = '{"format":"evo_ocean_setup","version":1,"seed":11,"population":20,"depth":200,"width":1920,"height":1080,"config":{"foodEnergy":6}}';
    const ways = [
        ['Start (the bar)', () => p.click('restart'), 'init'],
        ['Start again (same fish), the menu', () => { p.click('startmenubtn'); p.click('startsame'); }, 'init'],
        ['Start fresh (new fish), the menu', () => { p.click('startmenubtn'); p.click('newworld'); }, 'init'],
        ['R (a new seed)', () => p.key('r'), 'init'],
        ['Shift+R (Replay)', () => p.key('R', { shift: true }), 'reset'],
        ['Replay from start (the button)', () => p.click('replay'), 'reset'],
        ['Surprise me, then its Start', () => { p.click('randombig'); p.click('scenario-start'); }, 'init'],
        ['Living water, then its Start', () => { p.click('e1btn'); p.click('scenario-start'); }, 'init'],
        ['Hunters, then the bar\'s Start', () => { p.click('huntersbtn'); p.click('restart'); }, 'init'],
        ['Currents & patches, then its Start', () => { p.click('currentsbtn'); p.click('scenario-start'); }, 'init'],
        ['Standard, then its Start', () => { p.click('advreset'); p.click('scenario-start'); }, 'init'],
        ['Fit the world to this screen, then Start (asked: its size waits)', () => { p.ctx.innerWidth = 800; p.ctx.innerHeight = 1200; p.click('fitbtn'); p.ctx.innerWidth = 1920; p.ctx.innerHeight = 1080; p.click('restart'); }, 'init', true],
        ['Load setup, then Start', () => p.loadSetup(v1), 'init'],
        ['the link\'s import (start-up, benchmark)', () => p.T.importWorld(7, 12, 240, { walls: true }, undefined, [], [1920, 1080]), 'init'],
        ['Big tank, then its Start', () => { p.click('bigbtn'); p.click('scenario-start'); }, 'init']
    ];
    const bad = [];
    for (const [what, act, kind, asks] of ways) {
        const a = c();
        await act();
        const q = asked(p);   /* (edits waiting ask first: review of #39, finding 8) */
        if (q) p.click('startconfirm');
        const d = delta(a, c());
        if (d.epoch !== 1 || d.inits !== (kind === 'init' ? 1 : 0) || d.resets !== (kind === 'reset' ? 1 : 0) || q !== !!asks || asked(p))
            bad.push(what + ' ' + JSON.stringify(d) + (q !== !!asks ? (q ? ' asked' : ' not asked') : '') + ' "' + p.msg() + '"');
    }
    ok(!bad.length, 'each start moves the epoch once, through one oc_init (Replay: oc_reset), with nothing to ask on a fresh run but an edit waiting: ' +
       ways.map(w => w[0]).join(', ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* a live tweak: asked, Keep it, an edit meanwhile, then Replace it (the tweak carries over) */
        const q = await bootPage(PAGE_Q7), cq = startCounter(q), a = cq();
        q.edit('minSpeed', 40);
        q.click('restart');
        const ask1 = asked(q) && sheetOpen(q) && /live tweak/.test(q.el('startaskmsg').textContent), d1 = delta(a, cq());
        q.click('startcancel');
        q.click('restart');
        const ask2 = asked(q);
        q.edit('population', 50);
        const gone = !asked(q) && delta(a, cq()).inits === 0;
        q.click('restart');
        q.click('startconfirm');
        const d3 = delta(a, cq());
        ok(ask1 && d1.inits === 0 && ask2 && gone && d3.inits === 1 && d3.epoch === 1 && q.T.initArgs.cfg.minSpeed === 40 && q.T.initArgs.population === 50,
           'a live tweak: Restart asks ("' + q.el('startaskmsg').textContent + '"); Keep it starts nothing; an edit while asked takes the question away; ' +
           'Replace it starts once, the tweak (40) and the edit (50 fish) in the new world (' + JSON.stringify(d3) + ')');
    }
    {   /* five simulated minutes: R asks, R again asks nothing more, Enter on the focused confirm starts once */
        const q = await bootPage(PAGE_Q7), cq = startCounter(q);
        q.M._oc_step(18760); q.raf(performance.now());
        const a = cq();
        q.key('r');
        const ask = asked(q) && /of evolution/.test(q.el('startaskmsg').textContent) && focused(q) === 'startconfirm';
        q.key('r');
        const d1 = delta(a, cq());
        q.key('Enter');
        const d2 = delta(a, cq());
        ok(ask && d1.inits === 0 && d2.inits === 1 && d2.epoch === 1 && !asked(q),
           '5 simulated minutes: R asks ("' + q.el('startaskmsg').textContent + '"), its confirm focused; R again starts nothing; Enter starts once (' + JSON.stringify(d2) + ')');
    }
    {   /* Turbo: a restart-only edit stages (no Stop, no oc_init); Start asks; the ordinary hand-back, then the start */
        const { p: q, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        q.edit('population', 40);
        const staged = q.T.turboState === 'turbo' && !sh.toWorker.some(m => m.cmd === 'stop') && delta(a, cq()).inits === 0;
        const handler = sh.onmessage;
        q.click('restart');
        const ask = asked(q) && q.el('startconfirm').textContent === 'Stop Turbo & start';
        q.click('startconfirm');
        const st = q.T.turboState, pend = !!q.T.pendingStart;
        await until(() => q.T.turboState === 'live' && !q.T.pendingStart, 'the hand-back and the start');
        const d = delta(a, cq());
        ok(staged && ask && st === 'exiting' && pend && d.inits === 1 && d.epoch === 1 && q.T.initArgs.population === 40 && sh.terminated === 1 &&
           q.T.turboWorker === null && !q.T.paused && !q.T.usedTurbo,
           'in Turbo: a restart-only edit only stages; Start asks "Stop Turbo & start", then Stopping Turbo, the hand-back, and one start with 40 fish; ' +
           'the old worker terminated, the new world running (' + JSON.stringify(d) + ')');
        /* its late messages, delivered anyway (as a captured handler would): none reaches the world */
        const e0 = q.T.worldEpoch, cfg0 = JSON.stringify(q.T.runCfg);
        const stale = [{ type: 'stats', frame: 1e6, pop: 1, st: [1, 1e6], su: [] }, { type: 'set', key: 'minSpeed', value: 99, ok: true },
                       { type: 'rec', rows: [] }, { type: 'wiring', n: 1 }, { type: 'memory', mem: new ArrayBuffer(8) }, { type: 'error', message: 'stale' }];
        for (const m of stale) handler.call(sh, { data: m });
        const quiet = q.T.turboState === 'live' && q.T.worldEpoch === e0 && JSON.stringify(q.T.runCfg) === cfg0 && !(q.T.turboStats && q.T.turboStats.frame === 1e6);
        q.click('turbobtn');
        await until(() => q.T.turboState === 'turbo', 'a second Turbo');
        for (const m of stale.slice(0, 4)) handler.call(sh, { data: m });
        const quiet2 = q.T.turboState === 'turbo' && JSON.stringify(q.T.runCfg) === cfg0 && !(q.T.turboStats && q.T.turboStats.frame === 1e6);
        q.click('turboexit');
        await until(() => q.T.turboState === 'live', 'its hand-back');
        ok(quiet && quiet2 && q.T.worldEpoch === e0 && q.uncaught.length === 0,
           'the old worker\'s stats, set, rec, wiring, memory and error, delivered after the start and during the next Turbo: ignored; that Turbo runs and hands back');
    }
    {   /* an edit on its way to the worker: settled by the hand-back, then in the new world */
        const { p: q, sh } = await pageInTurbo();
        sh.pause();
        q.edit('minSpeed', 40);
        q.click('restart'); q.click('startconfirm');
        sh.resume();
        await until(() => q.T.turboState === 'live' && !q.T.pendingStart, 'the start');
        ok(q.T.initArgs.cfg.minSpeed === 40 && q.T.runCfg.minSpeed === 40, 'a live edit still in flight when Stop Turbo & start is pressed: answered, then started with it (minSpeed ' + q.T.initArgs.cfg.minSpeed + ')');
    }
    {   /* a refused edit changes the plan meanwhile: no start, the run carries on */
        const { p: q, img, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        sh.pause();
        q.edit('minSpeed', 200);
        q.click('restart'); q.click('startconfirm');
        sh.resume();
        await until(() => q.T.turboState === 'live' && !q.T.pendingStart, 'the hand-back');
        const d = delta(a, cq()), ref = await controlRun(img, workerEdits(sh), frame(q.M)), diff = sameFor(q.M, ref, 100);
        ok(d.inits === 0 && d.epoch === 0 && /setup changed/.test(q.msg()) && diff === '',
           'an edit refused during the hand-back (minSpeed 200): the plan asked about is gone, so no start; the run handed back carries on, 100 steps bit-identical ("' + q.msg() + '")' + (diff ? ': ' + diff : ''));
    }
    {   /* Stop (here: Cancel) while the hand-back is on its way: an ordinary Stop */
        const { p: q, f0, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        sh.pause();
        q.click('restart'); q.click('startconfirm');
        await until(() => sh.queued(isType('memory')), 'the memory');
        const label = q.el('turboexit').getAttribute('aria-label');
        q.click('turboexit');
        sh.resume();
        await until(() => q.T.turboState === 'live', 'the hand-back');
        const d = delta(a, cq());
        ok(label === 'cancel the new world' && d.inits === 0 && d.epoch === 0 && frame(q.M) > f0 && !q.T.pendingStart,
           'Stop Turbo & start, then Cancel while the world comes back: no start, the run handed back as by Stop (frame ' + f0 + ' -> ' + frame(q.M) + ')');
    }
    {   /* asked while Turbo is still starting: its first stats stop it, then the start */
        const q = await bootPage(PAGE_Q);
        const cq = startCounter(q), a = cq();
        q.hooks.onWorker = (sh) => sh.pause();
        q.click('turbobtn');
        const sh = q.worker();
        q.click('restart');
        const ask = asked(q);
        q.click('startconfirm');
        const st = q.T.turboState;
        sh.resume();
        await until(() => q.T.turboState === 'live' && !q.T.pendingStart, 'the start');
        const d = delta(a, cq());
        ok(ask && st === 'entering' && d.inits === 1 && d.epoch === 1 && sh.toWorker.some(m => m.cmd === 'stop'),
           'Stop Turbo & start while Turbo is starting: it starts, stops at once, hands back, and the new world starts (' + JSON.stringify(d) + ')');
    }
    {   /* the worker fails meanwhile: its world recovered, no start */
        const { p: q, f0, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        sh.pause();
        trapNext(sh);
        await until(() => sh.queued(isType('error')), 'the trap');
        q.click('restart'); q.click('startconfirm');
        await sh.release(isType('error'), 'the error');
        await until(() => q.T.turboState === 'live', 'the recovery');
        const d = delta(a, cq());
        ok(d.inits === 0 && d.epoch === 0 && !q.T.pendingStart && frame(q.M) === f0 && /new world did not start/.test(q.msg()),
           'the worker fails during Stop Turbo & start: the run recovered (its own copy, frame ' + f0 + '), no start ("' + q.msg().slice(0, 90) + '…")');
    }
    {   /* a hand-back the page can't take: Turbo resumes, no start; the next Stop works */
        const { p: q, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        sh.pause();
        q.click('restart'); q.click('startconfirm');
        await until(() => sh.queued(isType('memory')), 'the memory');
        const H = q.ctx.EvoOceanHandoff, take = H.take;
        H.take = function () { H.take = take; throw new Error('injected: no room'); };
        sh.resume();
        await until(() => q.T.turboState === 'turbo', 'Turbo resumed');
        const d = delta(a, cq()), said = q.msg();
        q.click('turboexit');
        await until(() => q.T.turboState === 'live', 'the second Stop');
        ok(d.inits === 0 && !q.T.pendingStart && /did not start/.test(said) && delta(a, cq()).epoch === 0,
           'a refused hand-back during Stop Turbo & start: Turbo keeps running, no start ("' + said.slice(0, 80) + '…"); the next Stop hands back');
    }
    {   /* a world the engine refuses (walls and wrap-around together): Turbo stopped, the run carries on */
        const { p: q, img, sh } = await pageInTurbo();
        const cq = startCounter(q), a = cq();
        q.edit('toroidal', true);
        q.click('restart'); q.click('startconfirm');
        await until(() => q.T.turboState === 'live' && !q.T.pendingStart, 'the hand-back');
        const d = delta(a, cq()), ref = await controlRun(img, workerEdits(sh), frame(q.M)), diff = sameFor(q.M, ref, 100);
        const said = q.msg();
        q.edit('toroidal', false);
        q.click('turbobtn');
        await until(() => q.T.turboState === 'turbo', 'Turbo again');
        q.click('turboexit');
        await until(() => q.T.turboState === 'live', 'its hand-back');
        ok(d.inits === 1 && d.epoch === 0 && /your run carries on, but that world was refused/.test(said) && diff === '' && q.uncaught.length === 0,
           'a world oc_init refuses after the hand-back: one oc_init attempt, no new epoch, the handed-back run goes on (100 steps bit-identical); ' +
           'a second Turbo works ("' + said.slice(0, 100) + '…")' + (diff ? ': ' + diff : ''));
    }
    {   /* Save during Turbo: the accepted setup only */
        const { p: q, sh } = await pageInTurbo();
        q.edit('maxPopulation', 200);
        await until(() => sh.delivered.some(m => m.type === 'set' && m.key === 'maxPopulation'), 'its answer');
        sh.pause();
        q.edit('minSpeed', 40);
        q.edit('population', 50);
        q.click('savecp');
        const f = JSON.parse(q.blobs[q.blobs.length - 1]), t = toastText(q);
        sh.resume();
        ok(q.T.turboState === 'turbo' && f.config.maxPopulation === 200 && !('minSpeed' in f.config) && f.population === 60 &&
           /still on the way/.test(t) && /waits for the next start/.test(t),
           'Save during Turbo: the acknowledged maxPopulation 200, not the minSpeed still on its way nor the 50 fish waiting; it says both ("' + t.slice(-160) + '")');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* UI-4: the picked or followed fish after Turbo. The same fish when it
 * lives (followed again, the lamp by the follow's own rule, the stored
 * preference never written); else its family line's nearest (world
 * distance, the lower id on a tie); else none, said so; a selection
 * without a follow stays one; C during Turbo drops the follow, Esc the
 * fish; a lost world's recovery picks it up from the page's own copy;
 * never across a new world (Stop Turbo & start). The round trip with the
 * fish picked up again stays bit-identical (the capture switch as the page
 * sets it: off during Turbo, on again after). */
async function pageFollowBack() {
    section('UI-4: the picked or followed fish comes back after Turbo (alive, its family\'s nearest, none), the lamp as it was, never across a new world');
    const st = (p) => p.ctx.EvoOcean.state();
    const pick = (p, follow) => { p.ctx.EvoOcean.select(0); if (follow) p.click('followbtn'); return st(p).selectedId; };
    async function trip(p, during, stop) {
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        await until(() => sh.delivered.some(isType('stats')), 'its stats');
        const mid = st(p);
        if (during) await during(sh);
        if (stop !== false) { p.click('turboexit'); await until(() => p.T.turboState === 'live', 'the hand-back'); }
        return { sh, mid };
    }
    {   /* followed, alive: followed again; bit-identical with the capture as the page sets it */
        const p = await bootPage(PAGE_Q);
        const id = pick(p, true), lit = st(p).flashlight;
        const img = HO.buffer(p.M).slice(0);
        const { sh, mid } = await trip(p);
        const s = p.T.lastS, alive = Array.prototype.includes.call(s.ids.subarray(0, s.n), id), after = st(p);
        ok(lit && mid.selectedId === null && !mid.following && !mid.flashlight && alive && after.selectedId === id && after.following && after.flashlight &&
           p.ctx.localStorage.getItem('evo_boids.ocean.followLight') === null,
           'followed fish #' + id + ': let go while Turbo runs (the lamp back off), then followed again after Stop with the lamp on; the preference never written');
        const ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img.slice(0), 'the control');
        ref._oc_set_capture(0); ref._oc_step(frame(p.M) - frame(ref)); ref._oc_set_capture(1);
        const d = sameFor(p.M, ref, 150);
        ok(workerEdits(sh).length === 0 && d === '', '  and the run is bit-identical to one without Turbo (150 steps, the capture off during Turbo, on after)' + (d ? ': ' + d : ''));
    }
    {   /* a selection without a follow; C during Turbo; Esc during Turbo */
        const p = await bootPage(PAGE_Q);
        const id = pick(p, false);
        await trip(p);
        const a = st(p);
        pick(p, true);
        await trip(p, () => p.key('c'));
        const b = st(p);
        pick(p, true);
        await trip(p, () => p.key('Escape'));
        const c = st(p);
        ok(a.selectedId === id && !a.following && b.selectedId !== null && !b.following && c.selectedId === null && !c.following,
           'picked, not followed: picked again, not followed; C during Turbo: picked again, the follow dropped; Esc during Turbo: let go (' +
           [a.selectedId, a.following, b.selectedId, b.following, c.selectedId].join(' ') + ')');
    }
    {   /* dead: the nearest of its family line; extinct: none, said so */
        const p = await bootPage(PAGE_Q);
        const s0 = p.T.lastS, k = 3, fam = Math.round(p.T.inspect(k).info[7]);
        const at = { x: p.T.lastS.segs[12 * k] + 37, y: p.T.lastS.segs[12 * k + 1] - 21, d: p.T.lastS.depth[k] };
        void s0;
        await trip(p, () => { p.T.turboReturn = { id: 1e9, follow: true, epoch: p.T.worldEpoch, family: fam, x: at.x, y: at.y, d: at.d }; });
        const s = p.T.lastS, n = s.n, ids = Array.from(s.ids.subarray(0, n)), xs = [], ys = [], ds = [];
        for (let i = 0; i < n; i++) { xs.push(s.segs[12 * i]); ys.push(s.segs[12 * i + 1]); ds.push(s.depth[i]); }
        let want = null, bd = Infinity;
        for (let i = 0; i < n; i++) {
            if (Math.round(p.T.inspect(i).info[7]) !== fam) continue;
            const d2 = (xs[i] - at.x) ** 2 + (ys[i] - at.y) ** 2 + (ds[i] - at.d) ** 2;   /* walls=1: no wrap */
            if (d2 < bd || (d2 === bd && ids[i] < want)) { bd = d2; want = ids[i]; }
        }
        const a = st(p), t1 = toastText(p);
        await trip(p, () => { p.T.turboReturn = { id: 1e9, follow: true, epoch: p.T.worldEpoch, family: -77, x: 0, y: 0, d: 0 }; });
        const b = st(p), t2 = toastText(p);
        ok(want !== null && a.selectedId === want && a.following && /died during Turbo/.test(t1) && b.selectedId === null && !b.following &&
           /nor did any of its family line/.test(t2),
           'a fish that died during Turbo: its family line\'s nearest (#' + want + ') is followed instead, said so; a family line gone: none, said so');
    }
    {   /* the family scan with the memory growing inside oc_inspect (review of the brief, Gemini q25): ids and places
         * copied first, a fresh view after each call: the same nearest, nothing read from a detached view */
        const p = await bootPage(PAGE_Q);
        const k = 5, fam = Math.round(p.T.inspect(k).info[7]);
        const at = { x: p.T.lastS.segs[12 * k] - 19, y: p.T.lastS.segs[12 * k + 1] + 44, d: p.T.lastS.depth[k] };
        const real = p.M._oc_inspect, mb0 = HO.buffer(p.M).byteLength;
        let grown = 0;
        await trip(p, () => {
            p.T.turboReturn = { id: 1e9, follow: false, epoch: p.T.worldEpoch, family: fam, x: at.x, y: at.y, d: at.d };
            p.M._oc_inspect = function (i) { if (grown < 3) { growMiB(p.M); grown++; } return real.call(this, i); };
        });
        p.M._oc_inspect = real;
        const a = st(p), s = p.T.lastS, n = s.n, ids = Array.from(s.ids.subarray(0, n)), xs = [], ys = [], ds = [];
        for (let i = 0; i < n; i++) { xs.push(s.segs[12 * i]); ys.push(s.segs[12 * i + 1]); ds.push(s.depth[i]); }
        let want = null, bd = Infinity;
        for (let i = 0; i < n; i++) {
            if (Math.round(p.T.inspect(i).info[7]) !== fam) continue;
            const d2 = (xs[i] - at.x) ** 2 + (ys[i] - at.y) ** 2 + (ds[i] - at.d) ** 2;
            if (d2 < bd || (d2 === bd && ids[i] < want)) { bd = d2; want = ids[i]; }
        }
        ok(grown === 3 && HO.buffer(p.M).byteLength > mb0 && want !== null && a.selectedId === want && !a.following && p.uncaught.length === 0,
           'the family scan with the memory growing inside oc_inspect (' + grown + ' times): the same nearest (#' + want + '), picked, not followed; no exception' +
           (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
    {   /* the preference off: the follow leaves the lamp alone, before and after */
        const p = await bootPage(PAGE_Q);
        const sw = p.el('followLight');
        sw.checked = false; sw.dispatchEvent(new p.Ev('change', { bubbles: true }));
        pick(p, true);
        const lit = st(p).flashlight;
        await trip(p);
        const a = st(p);
        ok(!lit && a.following && !a.flashlight && p.ctx.localStorage.getItem('evo_boids.ocean.followLight') === '0',
           'Light while following off: followed again after Turbo with the lamp still off, the preference still off');
    }
    {   /* a lost world: picked up from the page's own copy */
        const p = await bootPage(PAGE_Q);
        const id = pick(p, true);
        await trip(p, async (sh) => { sh.pause(); trapNext(sh); await until(() => sh.queued(isType('error')), 'the trap'); sh.resume(); }, false);
        await until(() => p.T.turboState === 'live', 'the recovery');
        const a = st(p);
        ok(a.selectedId === id && a.following, 'Turbo\'s world lost: the page goes on from its own copy, and fish #' + id + ' is followed again');
    }
    {   /* never across a new world */
        const p = await bootPage(PAGE_Q);
        pick(p, true);
        await trip(p, () => { p.click('restart'); p.click('startconfirm'); }, false);
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the new world');
        const a = st(p);
        ok(a.selectedId === null && !a.following && p.T.turboReturn === null, 'Stop Turbo & start: the new world starts with no fish picked or followed');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
    {   /* a Stop Turbo & start that does not start (the engine refuses the world): the run carries on, its fish picked up again */
        const p = await bootPage(PAGE_Q);
        const id = pick(p, true), e0 = p.T.worldEpoch;
        await trip(p, () => { p.edit('toroidal', true); p.click('restart'); p.click('startconfirm'); }, false);
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back');
        const a = st(p), said = p.msg();
        ok(p.T.worldEpoch === e0 && /that world was refused/.test(said) && a.selectedId === id && a.following && a.flashlight && p.T.turboReturn === null,
           'Stop Turbo & start refused by the engine: the run carries on and fish #' + id + ' is followed again, the lamp on (' +
           [a.selectedId, a.following, a.flashlight].join(' ') + ')');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
}

/* UI-3: the draft. What waits is derived from values (a field changed back
 * waits no more; a live tweak never waits; a negative value a running world
 * can't take waits); Discard drops what waits and keeps the live tweaks;
 * Replay drops the live tweaks and keeps what waits (raw input, keys the
 * sheet has no field for); a staged file's live fields, by typing or by
 * the steppers, never reach the running world or the worker, and an
 * acknowledgement never overwrites them; a live setting dims only when it
 * does nothing in the running world nor in the next one. */
async function pageDraft() {
    section('UI-3: the draft for the next world: value-derived waiting edits, Discard, Replay, staged files, both worlds\' dimming');
    const waiting = (p) => p.el('waitingcount').hidden ? 0 : parseInt(p.el('waitingcount').textContent, 10);
    {
        const p = await bootPage(PAGE_Q7 + '&cfg=' + encodeURIComponent('{"zzzUnknown":1}'));
        p.edit('population', 50);
        const w1 = waiting(p), s1 = p.el('startsummary').textContent, lab1 = p.el('restart').querySelector('span').textContent;
        p.edit('population', 12);
        const w2 = waiting(p);
        p.edit('minSpeed', 40);
        const w3 = waiting(p), s3 = p.el('startsummary').textContent;
        p.edit('kBuoy', -0.5);
        const w4 = waiting(p), neg = p.note('kBuoy');
        ok(w1 === 1 && /Starting fish 50|fish 50/.test(s1) && /Start with the change/.test(lab1) && w2 === 0 && w3 === 0 && /1 live tweak/.test(s3) &&
           w4 === 1 && /next start/.test(neg),
           'waiting edits are values: 50 fish waits (' + w1 + ', "' + s1 + '"), back to 12 waits no more (' + w2 + '); a live tweak applies, never waits (' + w3 +
           '); kBuoy -0.5 waits for the next start (' + w4 + ', "' + neg + '")');
        p.click('startdiscard');
        ok(waiting(p) === 0 && p.T.getVal('kBuoy') === p.KEYS.kBuoy[0] && p.T.getVal('minSpeed') === 40 && p.T.runCfg.minSpeed === 40,
           'Discard: kBuoy back to what runs, the live tweak (minSpeed 40) stays, nothing waits');
        p.edit('predatorCount', 3);
        p.el('o_width').value = ''; p.el('o_width').dispatchEvent(new p.Ev('input', { bubbles: true }));
        const w5 = waiting(p);
        p.key('R', { shift: true });
        const ask = asked(p) && /dropped/.test(p.el('startaskmsg').textContent) && /stays waiting/.test(p.el('startaskmsg').textContent);
        p.click('startconfirm');
        ok(w5 === 2 && ask && p.T.getVal('minSpeed') === 30 && !('minSpeed' in p.T.runCfg) && p.el('o_predatorCount').value === '3' &&
           p.el('o_width').value === '' && waiting(p) === 2 && p.T.readForm().cfg.zzzUnknown === 1,
           'Replay (asked: the live tweak is dropped, what waits stays): minSpeed back to 30, predatorCount 3 and the empty width still waiting, ' +
           'the unknown key kept (' + waiting(p) + ' waiting; "' + p.el('startaskmsg').textContent + '")');
    }
    {   /* a staged file: its live fields are the next world's, live and during Turbo */
        const p = await bootPage(PAGE_Q);
        const sets0 = p.sets.length;
        await (async () => { const g = p.T.draftGen; p.loadFile({ name: 's.json', text: () => Promise.resolve(SETUP99) }); await until(() => p.T.draftGen !== g, 'staged'); })();
        p.edit('foodEnergy', 7);
        const plus = p.el('f_targetFood').querySelectorAll('button')[1];
        plus.click();
        const staging = p.el('drawer').classList.contains('staging');
        ok(p.sets.length === sets0 && p.T.getVal('foodEnergy') === 7 && p.T.getVal('targetFood') === 100 && staging &&
           /modified \(2\)/.test(p.el('startsummary').textContent),
           'a staged file, the page running: foodEnergy typed and targetFood\'s + pressed change the next world only (no oc_set_param; "' +
           p.el('startsummary').textContent + '"); the live tags hide');
        p.click('startdiscard');
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        sh.pause();
        p.edit('minSpeed', 40);   /* nothing staged: to the worker */
        await (async () => { const g = p.T.draftGen; p.loadFile({ name: 's.json', text: () => Promise.resolve(SETUP99) }); await until(() => p.T.draftGen !== g, 'staged'); })();
        p.edit('foodEnergy', 7);
        p.el('f_targetFood').querySelectorAll('button')[1].click();
        sh.resume();
        await until(() => sh.delivered.some(m => m.type === 'set' && m.key === 'minSpeed'), 'the answer');
        ok(setsTo(sh) === 'minSpeed=40' && p.T.runCfg.minSpeed === 40 && p.T.getVal('minSpeed') === 30 && p.T.getVal('foodEnergy') === 7,
           'during Turbo: the staged file\'s edits send nothing to the worker (' + setsTo(sh) + '); the earlier live edit\'s answer reaches the running world ' +
           '(runCfg 40) and leaves the staged field alone (' + p.T.getVal('minSpeed') + ')');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
    }
    {   /* both worlds' dimming: predators in the running world, 0 typed for the next */
        const p = await bootPage(PAGE_Q7 + '&cfg=' + encodeURIComponent('{"predatorCount":3,"predatorEconomy":true,"currentStrength":5}'));
        const inert = (k) => p.el('f_' + k).classList.contains('inert');
        p.edit('predatorCount', 0); p.edit('currentStrength', 0);
        const live = !inert('predatorMaxPopulation') && !inert('deepCurrent'), restartOnly = inert('predatorMeal') && inert('currentMode');
        const sets0 = p.sets.length;
        p.edit('predatorMaxPopulation', 9);
        const applied = p.sets.length === sets0 + 1 && p.T.runCfg.predatorMaxPopulation === 9;
        p.click('startdiscard');
        p.edit('predatorEconomy', false);
        const both = inert('predatorMeal');
        ok(live && restartOnly && applied && both,
           'predators and a current running, 0 typed for the next world: the live predator cap and deep current stay usable (and the cap applies), ' +
           'the next world\'s own settings dim');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
}

/* UI-3: Start from. Every scenario (and Surprise me's draws) starts in
 * oc_init on ordinary, portrait, small and large tanks; Surprise me's
 * labels are written after its one volume scaling; picking a card only
 * stages (no oc_init, in Turbo no Stop either), its Start and the bar's are
 * one start; Reroll draws again; a card over edits that wait asks first;
 * the Fit button and the Water tab's E1 water stage only; the Start menu's
 * same fish / new fish. */
async function pageScenarios() {
    section('UI-3: scenarios: recipes oc_init takes, labels after scaling, a card stages and its Start starts, Reroll, Replace / Keep editing');
    {   /* the recipes themselves, through oc_init */
        const M = await mk(1), e1 = JSON.parse(HO.cString(M, M._oc_e1_preset()));
        let s = 777;
        const rand = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
        const init = (r) => HO.withCString(M, HO.cfgJson(r.cfg), p => M._oc_init(r.seed, r.width, r.height, r.depth, r.population, p));
        const bad = [];
        for (const screen of [[1920, 1080], [1080, 1920]])
            for (const id of ['standard', 'bigtank', 'e1', 'hunters', 'currents']) {
                const r = CFG.scenario(id, { seed: 9, screen, walls: true, e1, rand, tank: null });
                if (!r || !init(r)) bad.push(id + ' ' + screen.join('x') + ': ' + (r ? HO.cString(M, M._oc_last_error()) : 'none'));
            }
        const big = CFG.scenario('bigtank', { seed: 9, screen: [1920, 1080], walls: true, e1, rand });
        let draws = 0, scaled = [];
        for (const [w, h, d, walls] of [[1920, 1080, 240, true], [1080, 1920, 240, true], [300, 300, 60, true], [300, 300, 240, false],
                                         [5000, 3000, 400, true], [3840, 2160, 240, false]]) {
            for (let i = 0; i < 40; i++) {
                const r = CFG.scenario('surprise', { seed: 1 + i, screen: [1920, 1080], walls: true, e1, rand,
                                                     tank: { width: w, height: h, depth: d, walls, sideWallBand: 40, sideWallTurnRate: 3 } });
                draws++;
                if (!init(r)) bad.push('surprise ' + [w, h, d, walls].join('/') + ': ' + HO.cString(M, M._oc_last_error()));
                const cap = /at most (\d+) fish/.exec(r.summary), hunters = /(\d+) (?:hunting )?predators/.exec(r.summary);
                if (cap && +cap[1] !== r.cfg.maxPopulation) bad.push('surprise label "' + cap[0] + '" but the cap is ' + r.cfg.maxPopulation);
                if (hunters && +hunters[1] !== r.cfg.predatorCount) bad.push('surprise label "' + hunters[0] + '" but ' + r.cfg.predatorCount + ' predators');
                if (!r.summary.startsWith(r.width + ' × ' + r.height + ' × ' + r.depth + ' · ' + r.population + ' fish')) bad.push('surprise summary ' + r.summary);
                if (r.cfg.maxPopulation > 0 && r.population > r.cfg.maxPopulation) bad.push('surprise: ' + r.population + ' fish over its cap ' + r.cfg.maxPopulation);
                if (w * h * d === 5000 * 3000 * 400) {   /* x12 the standard volume: 210-420 fish, scaled once (twice would be ~145 x) */
                    const vol = w * h * d / (1920 * 1080 * 240);
                    scaled.push(/x[\d.]+\)/.test(r.summary) && r.population <= Math.ceil(420 * vol) ? 'once' : 'not once (' + r.population + ')');
                }
            }
        }
        ok(!bad.length && JSON.stringify(big.cfg) === JSON.stringify(CFG.BIG_TANK.cfg) && big.population === CFG.BIG_TANK.population && scaled.every(x => x === 'once'),
           'Standard, Big tank (its recipe verbatim), Living water, Hunters, Currents & patches on landscape and portrait screens, and ' + draws +
           ' Surprise me draws on ordinary, portrait, small, large and wrapping tanks: oc_init takes every one; the labels (caps, predators, fish) ' +
           'are the final recipe\'s, scaled once' + (bad.length ? ' — ' + bad.slice(0, 4).join('; ') : ''));
    }
    {   /* on the page: a card stages, its Start and the bar's start the same world; Reroll; Replace / Keep editing */
        const p = await bootPage(PAGE_Q);
        const c = startCounter(p), a = c();
        p.click('huntersbtn');
        const staged = p.T.draft && p.T.draft.id === 'hunters' && delta(a, c()).inits === 0 && p.shown('scenario-acts') &&
                       p.el('huntersbtn').getAttribute('aria-pressed') === 'true' && p.T.getVal('predatorCount') === 4;
        p.click('scenario-start');
        const viaCard = JSON.stringify(p.T.initArgs);
        p.click('huntersbtn'); p.click('restart');
        const viaBar = JSON.stringify(p.T.initArgs);
        ok(staged && viaCard === viaBar && p.T.initArgs.cfg.predatorCount === 4 && delta(a, c()).inits === 2 && !p.T.draft,
           'Hunters: the card stages (4 predators in the tabs, no oc_init), its Start starts it; the card again and the bar\'s Start start the very same world');
        p.click('randombig');
        const s1 = p.T.draft.seed, f1 = p.form();
        p.click('rerollbtn');
        const s2 = p.T.draft.seed, n1 = delta(a, c()).inits;
        ok(p.T.draft.id === 'surprise' && s1 !== s2 && f1 !== p.form() && n1 === 2 && /Picked:/.test(p.el('randnote').textContent),
           'Surprise me stages a draw (seed ' + s1 + '), Reroll another (seed ' + s2 + '); neither starts anything');
        p.click('startdiscard');
        p.edit('population', 77);
        p.click('bigbtn');
        const ask = asked(p) && /Big tank replaces the change/.test(p.el('startaskmsg').textContent);
        p.click('startcancel');
        const kept = !p.T.draft && p.T.getVal('population') === 77;
        p.click('bigbtn'); p.click('startconfirm');
        ok(ask && kept && p.T.draft && p.T.draft.id === 'bigtank' && p.T.getVal('population') === 2000 && delta(a, c()).inits === 2,
           'a card over an edit that waits asks ("' + p.el('startaskmsg').textContent + '"); Keep editing keeps 77 fish; Replace stages the Big tank');
        p.click('startdiscard');
        p.edit('predatorCount', 2);
        p.click('e1add');
        ok(!p.T.draft && p.T.getVal('predatorCount') === 2 && p.T.getVal('lightEnabled') === true && delta(a, c()).inits === 2,
           'the Water tab\'s "Add the tuned E1 water": the E1 keys join the waiting edits (the 2 predators stay), nothing starts');
        p.click('startdiscard');
        p.ctx.innerWidth = 800; p.ctx.innerHeight = 1200;
        p.click('fitbtn');
        p.ctx.innerWidth = 1920; p.ctx.innerHeight = 1080;
        ok(sheetOpen(p) && p.T.getVal('width') === 1080 && p.T.getVal('height') === 1920 && p.T.W === 1920 && delta(a, c()).inits === 2,
           'Fit the world to this screen: 1080 x 1920 waits in the opened setup sheet; the world is still 1920 x 1080');
        p.click('startdiscard');
        const seed0 = p.T.initArgs.seed;
        p.click('startmenubtn');
        const menu = p.shown('startmenu') && p.el('startmenubtn').getAttribute('aria-expanded') === 'true';
        p.key('Escape');
        const menuEsc = !p.shown('startmenu') && sheetOpen(p);
        p.click('startmenubtn'); p.click('startsame');
        const same = p.T.initArgs.seed === seed0;
        p.click('startmenubtn'); p.click('newworld');
        ok(menu && menuEsc && same && p.T.initArgs.seed !== seed0 && !p.shown('startmenu'),
           'the start menu: Esc closes it (not the sheet); Start again (same fish) keeps seed ' + seed0 + ', Start fresh draws ' + p.T.initArgs.seed);
    }
    {   /* in Turbo: a card stages (no Stop); its Start is Stop Turbo & start */
        const { p, sh } = await pageInTurbo();
        const c = startCounter(p), a = c();
        p.click('currentsbtn');
        const staged = p.T.draft && p.T.draft.id === 'currents' && !sh.toWorker.some(m => m.cmd === 'stop') && p.T.turboState === 'turbo';
        const label = p.el('scenario-start').querySelector('span').textContent;
        p.click('scenario-start');
        const ask = asked(p);
        p.click('startconfirm');
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the start');
        ok(staged && label === 'Stop & start' && ask && delta(a, c()).inits === 1 && p.T.initArgs.cfg.currentStrength === 80,
           'in Turbo: Currents & patches stages without stopping Turbo; its Start reads "Stop & start", asks, then starts it once');
        ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
    }
}

/* ---- Codex's review of PR #39 (round 1): one section per finding ---- */

/* the page live (Turbo stopped, nothing queued) */
async function toLive(p) {
    if (p.T.turboWorker) p.worker().resume();
    if (p.T.turboState === 'turbo') p.click('turboexit');
    await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the page live');
}
/* the page with Turbo starting, its first stats held (starting), or running: its worker */
async function turboHeld(p, starting) {
    await toLive(p);
    if (p.T.turboWorker) p.worker().pause(); else p.hooks.onWorker = (sh) => { p.hooks.onWorker = null; sh.pause(); };
    p.click('turbobtn');
    const sh = p.worker();
    if (starting) { await until(() => sh.queued(isType('stats')), 'the first stats'); return sh; }
    sh.resume();
    await until(() => p.T.turboState === 'turbo', 'Turbo');
    return sh;
}

/* Finding 2: T took its "Turbo is starting / stopping: a moment" branch, so a
 * confirmed Stop Turbo & start stayed armed and replaced the run. T, Space
 * and each Cancel (the strip's, the Setup bar's, the charts bar's), while
 * Turbo starts and while it stops: the new world is cancelled; Turbo carries
 * on (starting) or hands the run back as by Stop (stopping). */
async function pageCancelQueued() {
    section('Review of #39, finding 2: T, Space and every Cancel cancel a queued Stop Turbo & start, while Turbo starts and while it stops');
    const p = await bootPage(PAGE_Q);
    const c = startCounter(p);
    const ways = [['T', () => p.key('t')], ['Space', () => p.key(' ')], ['the strip\'s Cancel', () => p.click('turboexit')],
                  ['the Setup bar\'s Cancel', () => p.click('setup-turbo-stop')], ['the charts bar\'s Cancel', () => p.click('dash-turbo-stop')]];
    for (const [what, act] of ways) {
        {   /* Starting Turbo */
            const sh = await turboHeld(p, true), a = c();
            p.click('restart'); const ask = asked(p); p.click('startconfirm');
            const queued = !!p.T.pendingStart && p.T.turboState === 'entering';
            act();
            const gone = !p.T.pendingStart, n0 = sh.delivered.length;
            sh.resume();
            /* Turbo running on, or (the start not cancelled) the new world */
            await until(() => (p.T.turboState === 'turbo' && sh.delivered.slice(n0).filter(isType('stats')).length >= 3) ||
                              (p.T.turboState === 'live' && !p.T.pendingStart), 'Turbo to run on, or the start');
            const d = delta(a, c());
            ok(ask && queued && gone && p.T.turboState === 'turbo' && d.inits === 0 && d.epoch === 0,
               'Starting Turbo, Stop Turbo & start queued, then ' + what + ': the new world is cancelled, Turbo runs on (' + p.T.turboState + ', ' + JSON.stringify(d) + ')');
        }
        {   /* Stopping Turbo */
            const sh = await turboHeld(p, false), a = c(), f0 = frame(p.M);
            sh.pause();
            p.click('restart'); const ask = asked(p); p.click('startconfirm');
            await until(() => sh.queued(isType('memory')), 'the memory');
            const queued = !!p.T.pendingStart && p.T.turboState === 'exiting';
            act();
            const gone = !p.T.pendingStart;
            sh.resume();
            await until(() => p.T.turboState === 'live', 'the hand-back');
            const d = delta(a, c());
            ok(ask && queued && gone && d.inits === 0 && d.epoch === 0 && frame(p.M) > f0 && !p.T.paused,
               'Stopping Turbo, Stop Turbo & start queued, then ' + what + ': no new world, the run handed back as by Stop (frame ' + f0 + ' -> ' + frame(p.M) + ', ' + JSON.stringify(d) + ')');
        }
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* a setup file staged through the page's own file input (read at once) */
async function stageFile(p, text) {
    const g = p.T.draftGen;
    p.loadFile({ name: 's.json', text: () => Promise.resolve(text) });
    await until(() => p.T.draftGen !== g || p.T.asking, 'the file staged');
}
/* Finding 1: a staged, untouched setup file's plan is its own recipe (it
 * reads no field), so a start queued for Turbo's hand-back (or asked about)
 * kept starting the file after the sheet changed meanwhile, and the start
 * then cleared the draft: a population typed, another card picked, Discard,
 * Fit, all lost. Now the sheet is part of what was asked about: the queued
 * start does not happen (Turbo's Stop completes as an ordinary Stop, said
 * so) and the changed draft stays. */
async function pageQueuedFile() {
    section('Review of #39, finding 1: a queued or asked start of a staged file does not survive a change of the sheet (edit, another card, Discard, Fit)');
    const p = await bootPage(PAGE_Q);
    const c = startCounter(p);
    /* [what, while: 'starting' | 'stopping', the change] */
    const cases = [
        ['50 fish typed', 'starting', () => p.edit('population', 50), () => p.T.draft && p.T.draft.kind === 'file' && p.T.getVal('population') === 50],
        ['Hunters picked', 'stopping', () => p.click('huntersbtn'), () => p.T.draft && p.T.draft.id === 'hunters'],
        ['Discard', 'stopping', () => p.click('startdiscard'), () => !p.T.draft],
        ['the E1 water added', 'starting', () => p.click('e1add'), () => p.T.draft && p.T.draft.kind === 'file' && p.T.getVal('lightEnabled') === true]
    ];
    for (const [what, when, change, kept] of cases) {
        const sh = await turboHeld(p, when === 'starting');
        await stageFile(p, SETUP99);
        if (when === 'stopping') sh.pause();
        const a = c(), seed0 = p.T.initArgs.seed;
        p.click('restart'); const ask = asked(p); p.click('startconfirm');
        if (when === 'stopping') await until(() => sh.queued(isType('memory')), 'the memory');
        const queued = !!p.T.pendingStart && p.T.turboState === (when === 'starting' ? 'entering' : 'exiting');
        change();
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back');
        const d = delta(a, c());
        ok(ask && queued && d.inits === 0 && d.epoch === 0 && p.T.initArgs.seed === seed0 && /setup changed/.test(p.msg()) && kept(),
           (when === 'starting' ? 'Starting' : 'Stopping') + ' Turbo, the staged file\'s start queued, then ' + what + ': Turbo stops as by Stop, the file does not start, ' +
           'the sheet keeps the change (' + JSON.stringify(d) + '; "' + p.msg().slice(0, 70) + '…")');
        p.click('startdiscard');
    }
    {   /* asked (a live tweak), then Fit: Replace it starts nothing */
        const q = await bootPage(PAGE_Q);
        const cq = startCounter(q), a = cq();
        q.edit('minSpeed', 40);
        await stageFile(q, SETUP99);
        q.click('restart');
        const ask = asked(q);
        q.ctx.innerWidth = 800; q.ctx.innerHeight = 1200; q.click('fitbtn'); q.ctx.innerWidth = 1920; q.ctx.innerHeight = 1080;
        q.click('startconfirm');
        const d = delta(a, cq());
        ok(ask && d.inits === 0 && q.T.draft && q.T.draft.kind === 'file' && q.T.getVal('width') === 1080 && /setup changed/.test(q.msg()),
           'a staged file asked about (a live tweak), then Fit to this screen: Replace it starts nothing, the fitted size stays staged ("' + q.msg() + '")');
        ok(q.uncaught.length === 0, 'no exception escaped the page\'s handlers (the Fit case)' + (q.uncaught.length ? ' (' + q.uncaught[0] + ')' : ''));
    }
    {   /* the control: nothing changed meanwhile, the file starts (Stopping Turbo) */
        const sh = await turboHeld(p, false);
        await stageFile(p, SETUP99);
        sh.pause();
        const a = c();
        p.click('restart'); p.click('startconfirm');
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the start');
        const d = delta(a, c());
        ok(d.inits === 1 && d.epoch === 1 && p.T.initArgs.seed === 99 && p.T.W === 800 && !p.T.draft,
           'the control: the file\'s start queued and nothing changed meanwhile: Turbo hands back, then the file\'s world starts once (seed 99, 800 wide)');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 3: a live setting's newer value for the next world only (kBuoy
 * below 0) is no ledger entry, so an older edit of the key still on its way
 * hid it from what waits, and that edit's answer wrote over it: the
 * acknowledgement put 0.5 back in the field, a refusal the running value.
 * Now the answer changes the running world's bookkeeping only; the newer
 * value stays in the field with its note, counts as waiting, and the next
 * world gets it. While Turbo runs (in flight) and while it starts (held). */
async function pageNextBehindLive() {
    section('Review of #39, finding 3: a newer next-world value (kBuoy below 0) behind an older live edit of the key is not lost to that edit\'s answer');
    const waiting = (p) => p.el('waitingcount').hidden ? 0 : parseInt(p.el('waitingcount').textContent, 10);
    const answer = (sh, key, n0) => until(() => sh.delivered.slice(n0).some(m => m.type === 'set' && m.key === key), key + '\'s answer');
    const { p, sh } = await pageInTurbo();
    {   /* acknowledged */
        sh.pause();
        const n0 = sh.delivered.length;
        p.edit('kBuoy', 0.5);
        p.edit('kBuoy', -0.5);
        const w1 = waiting(p), note1 = p.note('kBuoy');
        sh.resume();
        await answer(sh, 'kBuoy', n0);
        ok(w1 === 1 && /next start/.test(note1) && p.el('o_kBuoy').value === '-0.5' && p.T.runCfg.kBuoy === 0.5 && waiting(p) === 1 &&
           /next start/.test(p.note('kBuoy')) && p.T.pendingDiff().includes('kBuoy'),
           'in Turbo, kBuoy 0.5 sent, then -0.5 for the next world: it waits at once (' + w1 + ' waiting, "' + note1 + '"); 0.5\'s acknowledgement ' +
           'sets the running world (runCfg ' + p.T.runCfg.kBuoy + ') and leaves the field at ' + p.el('o_kBuoy').value + ', still waiting (' + waiting(p) + ')');
    }
    {   /* refused */
        sh.pause();
        const n0 = sh.delivered.length;
        p.edit('kBuoy', 2000);   /* outside [-1000, 1000]: the worker refuses it */
        p.edit('kBuoy', -0.7);
        sh.resume();
        await answer(sh, 'kBuoy', n0);
        const refused = sh.delivered.slice(n0).some(m => m.type === 'set' && m.key === 'kBuoy' && !m.ok);
        ok(refused && p.el('o_kBuoy').value === '-0.7' && p.T.runCfg.kBuoy === 0.5 && waiting(p) === 1 && /keeps 0.5/.test(p.msg()),
           'kBuoy 2000 sent, then -0.7 for the next world: the worker\'s refusal of 2000 leaves the field at ' + p.el('o_kBuoy').value +
           ' ("' + p.msg() + '")');
    }
    {   /* the next world gets it */
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        const kept = p.el('o_kBuoy').value === '-0.7' && waiting(p) === 1;
        p.start();
        ok(kept && p.T.initArgs.cfg.kBuoy === -0.7 && p.T.runCfg.kBuoy === -0.7,
           'after the hand-back -0.7 still waits; Start: the new world has kBuoy ' + p.T.initArgs.cfg.kBuoy);
    }
    {   /* held while Turbo starts, then flushed and acknowledged */
        const q = await bootPage(PAGE_Q);
        const sq = await turboHeld(q, true);
        q.edit('kBuoy', 0.5);
        q.edit('kBuoy', -0.5);
        const w1 = waiting(q);
        const n0 = sq.delivered.length;
        sq.resume();
        await answer(sq, 'kBuoy', n0);
        ok(w1 === 1 && q.el('o_kBuoy').value === '-0.5' && q.T.runCfg.kBuoy === 0.5 && waiting(q) === 1 && /next start/.test(q.note('kBuoy')),
           'Starting Turbo: kBuoy 0.5 held, then -0.5 for the next world: 0.5 is applied when Turbo has started and acknowledged (runCfg ' +
           q.T.runCfg.kBuoy + '); the field keeps ' + q.el('o_kBuoy').value + ' and its note ("' + q.note('kBuoy') + '")');
        ok(q.uncaught.length === 0, 'no exception escaped the page\'s handlers (held)' + (q.uncaught.length ? ' (' + q.uncaught[0] + ')' : ''));
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 4: a staged setup file started untouched hands oc_init its own
 * values (a repeated key's later occurrences, values the sheet can't hold);
 * one unrelated field edited, Start built the world from the sheet instead,
 * which dropped those: {"maxPopulation":300,"maxPopulation":1e400} ran with
 * a cap of 300, a switch written 2 ran as off. Now an edited file is the
 * file with the edited fields only: the untouched values still reach
 * oc_init (and are refused), the keys without a field stay, an edited key's
 * later occurrences are replaced with it. */
async function pageEditedFile() {
    section('Review of #39, finding 4: a staged file with an unrelated field edited still hands oc_init its untouched values (repeats, overflow, unrepresentable)');
    const p = await bootPage(PAGE_Q7);
    const c = startCounter(p);
    const file = (cfg) => '{"format":"evo_ocean_setup","seed":11,"population":20,"depth":240,"width":1920,"height":1080,"config":' + cfg + '}';
    const direct = await mk(1, {}, 300, 300, 0);
    const bad = [];
    for (const doc of ['{"maxPopulation":300,"maxPopulation":1e400}', '{"maxPopulation":1e400,"maxPopulation":300}', '{"appearance":3,"appearance":1e400}',
                       '{"lightEnabled":true,"lightEnabled":1e400}', '{"bodyModel":2}', '{"toroidal":true,"toroidal":1}', '{"maxPopulation":300,"maxPopulation":0.5}']) {
        if (directInit(direct, doc).ok) { bad.push(doc + ': oc_init accepts it (the fixture says refused)'); continue; }
        p.click('startdiscard');
        await stageFile(p, file(doc));
        p.edit('population', 13);   /* an unrelated field */
        const a = c(), world0 = p.world(), print0 = fingerprint(p.M);
        p.el('err').textContent = '';
        p.start();
        const d = delta(a, c());
        if (d.epoch !== 0 || p.world() !== world0 || fingerprint(p.M) !== print0 || !/That setup was refused/.test(p.msg()))
            bad.push(doc + ': ' + JSON.stringify(d) + ' "' + p.msg().slice(0, 80) + '"' + (d.epoch ? ' (ran with cap ' + p.T.runCfg.maxPopulation + ')' : ''));
        else if (!(p.T.draft && p.T.draft.kind === 'file' && p.T.getVal('population') === 13)) bad.push(doc + ': the edited file did not stay staged');
    }
    ok(!bad.length, 'seven files oc_init refuses (a later 1e400, a first 1e400, an Ocean int and switch overflowing, a switch as 2, a SimConfig switch as 1, a later 0.5), ' +
       'each with only Starting fish edited: refused, the run unchanged, the edited file still staged' + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* accepted: the edit and the file's own keys (one without a field) */
        p.click('startdiscard');
        await stageFile(p, file('{"foodEnergy":6,"zzzUnknown":1,"maxPopulation":300,"maxPopulation":400}'));
        p.edit('population', 13);
        p.start();
        const i = p.T.initArgs;
        ok(i.seed === 11 && i.population === 13 && i.cfg.foodEnergy === 6 && i.cfg.zzzUnknown === 1 && i.cfg.maxPopulation === 300 && !p.T.draft &&
           /\(edited\)/.test(p.msg()) && /"maxPopulation":400/.test(p.inits[p.inits.length - 1]),
           'a file oc_init takes, Starting fish edited: seed 11, 13 fish, foodEnergy 6, the key without a field (zzzUnknown) and the later maxPopulation ' +
           'still sent (oc_init ran ' + p.inits[p.inits.length - 1] + ')');
    }
    {   /* an edited key's own later occurrences go with the edit */
        p.click('startdiscard');
        await stageFile(p, file('{"maxPopulation":300,"maxPopulation":1e400}'));
        p.edit('maxPopulation', 400);
        p.start();
        ok(p.T.initArgs.seed === 11 && p.T.initArgs.cfg.maxPopulation === 400 && !/1e400/.test(p.inits[p.inits.length - 1]),
           'the repeated key itself edited (400): the edit replaces it and its later occurrence; the world runs with cap ' + p.T.initArgs.cfg.maxPopulation);
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 7: a successful start makes an older setup-file read stale (it
 * must not stage over the world started since), but Replay moved the epoch
 * and not the read's generation, so a read begun before it staged the file
 * after it. Now Replay ends older reads too, and keeps what was staged. */
async function pageReplayStaleRead() {
    section('Review of #39, finding 7: Replay makes an older setup-file read stale, and keeps what is staged');
    const p = await bootPage(PAGE_Q);
    const c = startCounter(p);
    {   /* nothing staged: Shift+R, then the read finishes */
        const f = deferredFile(SETUP99), a = c();
        p.loadFile(f.file);
        p.key('R', { shift: true });
        const d = delta(a, c());
        f.resolve(); for (let i = 0; i < 4; i++) await tick();
        ok(d.resets === 1 && d.epoch === 1 && !p.T.draft && p.el('o_seed').value === '4242' && !/Ready/.test(p.msg()),
           'a read begun, then Shift+R (Replay, ' + JSON.stringify(d) + '), then the read finishes: nothing staged, the sheet still the replayed world (seed ' + p.el('o_seed').value + ')');
    }
    {   /* Hunters staged: the Replay button, then the read finishes */
        p.click('huntersbtn');
        const f = deferredFile(SETUP99), a = c();
        p.loadFile(f.file);
        p.click('replay');
        if (p.T.asking) p.click('startconfirm');
        const d = delta(a, c());
        f.resolve(); for (let i = 0; i < 4; i++) await tick();
        ok(d.resets === 1 && p.T.draft && p.T.draft.id === 'hunters' && p.T.getVal('predatorCount') === 4,
           'Hunters staged, a read begun, then Replay (' + JSON.stringify(d) + '), then the read finishes: Hunters still staged, the file not');
    }
    {   /* the control: a read with nothing in between stages */
        p.click('startdiscard');
        const f = deferredFile(SETUP99);
        p.loadFile(f.file);
        f.resolve(); for (let i = 0; i < 4; i++) await tick();
        ok(p.T.draft && p.T.draft.kind === 'file' && p.el('o_seed').value === '99', 'the control: a read with nothing in between stages the file (seed 99)');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 6: the question promised "your live tweak carries over" for every
 * start but Replay; a scenario or a file is a whole recipe, and Standard
 * puts Slowest speed back to 30. Now it reads the new world's recipe: a
 * tweak it has too carries over, one it sets otherwise is said so. */
async function pageAskTarget() {
    section('Review of #39, finding 6: the question says which live tweaks the new world keeps, and what a scenario, a file or a typed value sets instead');
    const p = await bootPage(PAGE_Q);
    const msg = () => p.el('startaskmsg').textContent;
    p.edit('minSpeed', 40);
    p.click('advreset');
    p.click('restart');
    const m1 = msg();
    p.click('startconfirm');
    ok(!/carr/.test(m1) && /Standard sets Slowest speed 30 instead of your live tweak \(Slowest speed 40\)/.test(m1) && p.T.getVal('minSpeed') === 30 && !('minSpeed' in p.T.runCfg),
       'Slowest speed 40 live, Standard picked, Start: "' + m1 + '"; the new world has 30');
    p.edit('minSpeed', 40); p.edit('maxPopulation', 350);
    p.click('huntersbtn');
    p.click('restart');
    const m2 = msg();
    p.click('startcancel');
    ok(/Your live tweak \(Population cap 350\) carries over/.test(m2) && /Hunters sets Slowest speed 0 instead of your live tweak \(Slowest speed 40\)/.test(m2),
       'Slowest speed 40 and Population cap 350 live, Hunters picked (its cap 350, its slowest speed 0): "' + m2 + '"');
    p.click('startdiscard');
    p.click('restart');
    const m3 = msg();
    p.click('startcancel');
    p.edit('foodEnergy', 7); p.edit('foodEnergy', -1);
    p.click('restart');
    const m4 = msg();
    p.click('startconfirm');
    ok(/Your live tweaks \(Slowest speed 40, Population cap 350\) carry over/.test(m3) &&
       /The new world's setup sets Energy per food -1 instead of your live tweak \(Energy per food 7\)/.test(m4) && p.T.initArgs.cfg.foodEnergy === -1,
       'nothing staged: both carry over ("' + m3 + '"); Energy per food 7 live, then -1 typed for the next world: "' + m4 + '"');
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 8: the approved rule asks before a start when the run has
 * something to lose: five minutes, Turbo, live tweaks, or edits waiting.
 * The last was left out. Now a young run with an edit waiting (a field, Fit,
 * a staged card changed, or a card staged over edits that waited) asks;
 * a card or file picked on an untouched sheet still starts at once. */
async function pagePendingAsk() {
    section('Review of #39, finding 8: edits waiting are a reason to ask (the approved rule); a card picked on an untouched sheet is not');
    const p = await bootPage(PAGE_Q7);
    const c = startCounter(p), msg = () => p.el('startaskmsg').textContent;
    const fit = () => { p.ctx.innerWidth = 800; p.ctx.innerHeight = 1200; p.click('fitbtn'); p.ctx.innerWidth = 1920; p.ctx.innerHeight = 1080; };
    /* [what, make the edits, how to start, starts at once?, the question says] */
    const cases = [
        ['50 fish typed, then Start', () => p.edit('population', 50), () => p.click('restart'), false, /It starts with what waits: Starting fish 50/],
        ['Fit to this screen, then Start', fit, () => p.click('restart'), false, /Tank width 1080/],
        ['Big tank over 51 fish typed (Replace), then its Start', () => { p.edit('population', 51); p.click('bigbtn'); p.click('startconfirm'); },
         () => p.click('scenario-start'), false, /It starts Big tank\./],
        ['Hunters with its fish changed to 9, then the bar\'s Start', () => { p.click('huntersbtn'); p.edit('population', 9); },
         () => p.click('restart'), false, /It starts Hunters as you changed it \(Starting fish 9\)/],
        ['an edit waiting, then R', () => p.edit('foodEnergy', -2), () => p.key('r'), false, /It starts with what waits: Energy per food -2/],
        ['an edit waiting, then Shift+R (Replay keeps it)', () => p.edit('population', 40), () => p.key('R', { shift: true }), false, /stays waiting/],
        ['nothing waiting, Hunters picked, then its Start', () => p.click('huntersbtn'), () => p.click('scenario-start'), true, null],
        ['nothing waiting, a setup file staged, then Start', null, () => p.click('restart'), true, null],
        ['nothing waiting, Start', () => {}, () => p.click('restart'), true, null]
    ];
    const bad = [], said = [];
    for (const [what, make, go, atOnce, says] of cases) {
        if (p.T.draft || p.T.pendingDiff().length) p.click('startdiscard');
        if (make) make(); else await stageFile(p, '{"format":"evo_ocean_setup","seed":11,"population":20,"depth":240,"width":1920,"height":1080,"config":{}}');
        const a = c();
        go();
        const q = asked(p), m = q ? msg() : '', d1 = delta(a, c());
        if (q) { if (p.T.asking.replace) bad.push(what + ': asked Replace / Keep editing'); p.click('startconfirm'); }
        const d2 = delta(a, c());
        if (atOnce ? q || d1.epoch !== 1 : !q || d1.epoch !== 0 || d2.epoch !== 1 || (says && !says.test(m))) bad.push(what + ': ' + (q ? 'asked "' + m + '"' : 'not asked') + ' ' + JSON.stringify(d2));
        else said.push(what + (q ? ': "' + m + '"' : ': at once'));
    }
    ok(!bad.length, 'on a young run (no Turbo, no live tweak): ' + said.join('; ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* Keep it keeps the edit waiting; the run goes on */
        p.edit('population', 33);
        const a = c();
        p.click('restart'); p.click('startcancel');
        ok(delta(a, c()).epoch === 0 && p.T.getVal('population') === 33 && p.T.pendingDiff().includes('population'), 'Keep it: no start, 33 fish still waiting');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* Finding 9: Start pressed from the keyboard when the question was needed:
 * the start row hid (the question takes its place) and the button handler
 * blurred it, so the keyboard's focus was lost (R had its own answer focus,
 * buttons not). Now a keyboard press focuses the answer, Keep it brings the
 * focus back to the button (the menu's items: to the menu's button); a
 * pointer's press still leaves no focus behind. */
async function pageKeyboardAsk() {
    section('Review of #39, finding 9: a question opened from the keyboard has the focus on its answer, and Keep gives it back');
    const p = await bootPage(PAGE_Q7);
    p.edit('minSpeed', 40);   /* a live tweak: every start asks */
    const c = startCounter(p), a = c();
    /* [the button, what opens it, where Keep puts the focus] */
    const ways = [['restart', () => {}, 'restart'], ['newworld', () => p.click('startmenubtn'), 'startmenubtn'],
                  ['startsame', () => p.click('startmenubtn'), 'startmenubtn'], ['replay', () => {}, 'replay'],
                  ['scenario-start', () => p.click('huntersbtn'), 'scenario-start']];
    const bad = [], fine = [];
    for (const [id, open, back] of ways) {
        open();
        p.tabTo(id); p.key('Enter');
        const q = asked(p), f1 = focused(p);
        p.tabTo('startcancel'); p.key('Enter');
        const f2 = focused(p);
        if (!q || f1 !== 'startconfirm' || f2 !== back || asked(p)) bad.push(id + ': asked ' + q + ', focus ' + f1 + ', after Keep ' + f2);
        else fine.push(id + ' -> startconfirm -> ' + back);
        if (p.T.draft) p.click('startdiscard');
    }
    {   /* a card over an edit that waits: Replace / Keep editing */
        p.edit('population', 33);
        p.tabTo('bigbtn'); p.key('Enter');
        const q = !!(p.T.asking && p.T.asking.replace), f1 = focused(p);
        p.tabTo('startcancel'); p.key('Enter');
        const f2 = focused(p);
        if (!q || f1 !== 'startconfirm' || f2 !== 'bigbtn') bad.push('bigbtn: asked ' + q + ', focus ' + f1 + ', after Keep editing ' + f2);
        else fine.push('a card over an edit -> startconfirm -> bigbtn');
        p.click('startdiscard');
    }
    ok(!bad.length && delta(a, c()).epoch === 0, 'from the keyboard: ' + fine.join('; ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* Enter on the answer starts once; a pointer's press: no focus left behind */
        p.tabTo('restart'); p.key('Enter'); p.key('Enter');
        const d = delta(a, c());
        p.pointer(); p.click('restart');
        ok(d.epoch === 1 && !asked(p) && focused(p) === null,
           'Enter on Start, then Enter on the focused answer: one start; a pointer\'s press on Start (no tweak now): no focus left behind (' + focused(p) + ')');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* ---------------------------------------------------------------------
 * Save world / From a file: the world file (web/ocean_handoff.js
 * encodeWorld / decodeWorld; web/ocean.js saveWorld, openWorldFile,
 * startWorld's "open"). The file is the module's memory image (the one the
 * Turbo hand-off moves) with a header; opened, the world carries on bit for
 * bit as if it had never been saved: in a fresh module, in one whose memory
 * is bigger (the rest zeroed) or smaller (grown), from a page, from Turbo
 * (the worker's copy, Turbo running on), in the Big tank. Anything else is
 * refused before it reaches a module: a file cut short or with bytes after
 * its end, a damaged stream, a bad checksum, another version, another
 * engine build (its setup offered instead), a setup handed to the world
 * reader and a world to the setup reader.
 * --------------------------------------------------------------------- */
const worldHead = (h) => Object.assign({ format: 'evo_ocean_world', version: 1, engine: { module: 'evo_ocean', wasmSha256: WASM_SHA } }, h || {});
async function fileOf(w) { return new Uint8Array(await new Blob(w.parts).arrayBuffer()); }
/* a File whose reads wait for gate (a slow disk), but those pass(start, end) lets through (default: the
 * magic, which From a file reads first); reads: every [start, end) asked for */
function gated(f, gate, pass) {
    const g = { name: f.name, size: f.size, reads: [] };
    pass = pass || ((x, y) => y <= HO.WORLD.MAGIC.length);
    g.slice = (x, y) => ({ arrayBuffer: () => { g.reads.push([x, y]); return pass(x, y) ? f.slice(x, y).arrayBuffer() : gate.then(() => f.slice(x, y).arrayBuffer()); } });
    return g;
}
async function encoded(M, header, opts) { const w = await HO.encodeWorld(worldHead(header), HO.buffer(M).slice(0), opts); return { w, bytes: await fileOf(w) }; }
async function refusal(bytes) { try { await HO.decodeWorld(bytes); return ''; } catch (e) { return String(e && e.message || e); } }
/* a world file from its header h (an object: written as it is) and body bytes */
function fileFrom(h, body) {
    const hb = Buffer.from(JSON.stringify(h), 'utf8'), len = Buffer.alloc(4);
    len.writeUInt32LE(hb.length, 0);
    return new Uint8Array(Buffer.concat([Buffer.from(HO.WORLD.MAGIC, 'latin1'), len, hb, Buffer.from(body || [])]));
}
/* a world file with its header changed by fn (the body as it was): its checksum now stale (damaged) */
function reheader(bytes, fn) {
    const r = HO.worldHeader(bytes), h = JSON.parse(JSON.stringify(r.header));
    fn(h);
    return fileFrom(h, bytes.subarray(r.at));
}
/* the same, the header's checksum made again (a file written so: only the header's own checks can stop it) */
async function resealed(bytes, fn) {
    const r = HO.worldHeader(bytes), h = JSON.parse(JSON.stringify(r.header));
    fn(h);
    return fileFrom(await HO.sealHeader(h), bytes.subarray(r.at));
}
/* a fresh module (a small memory, its own world) with the image of a world file in it; grow: MiB more
 * memory first, filled with junk past the image (as a module that ran a bigger world has it) */
async function opened(bytes, grow) {
    const M = await mk(1, {}, 300, 300, 0);
    const w = await HO.decodeWorld(bytes);
    if (grow) { for (let i = 0; i < grow; i++) growMiB(M); new Uint8Array(HO.buffer(M)).fill(0xab, w.bytes); }
    HO.take(M, w.data, 'the test', w.bytes);
    return { M, image: HO.wholeImage(w), header: w.header };
}
const zeroFrom = (M, at) => { const u = new Uint8Array(HO.buffer(M)); for (let i = at; i < u.length; i++) if (u[i]) return i; return -1; };
const sizeOf = (n) => (n / MB).toFixed(2) + ' MB';
/* every named condition true, else ' (not: names)' for the message */
const all = (c) => Object.keys(c).every(k => c[k]);
const nots = (c) => { const n = Object.keys(c).filter(k => !c[k]); return n.length ? ' (not: ' + n.join(', ') + ')' : ''; };
const FRESH_MEM = 16.25 * MB;   /* a fresh module's memory */

async function worldCodec() {
    section('Save world, the file: SHA-256, the image trimmed and gzipped, and back bit for bit');
    {   /* the JS SHA-256 (an insecure context's) against node's, at every padding boundary */
        const bad = [];
        for (const n of [0, 1, 3, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 1000, 65536, 100003]) {
            const b = crypto.randomBytes(n), want = crypto.createHash('sha256').update(b).digest('hex');
            if (HO.sha256js(new Uint8Array(b)) !== want || await HO.sha256(new Uint8Array(b)) !== want) bad.push(n);
        }
        ok(!bad.length && HO.sha256js(new Uint8Array(0)) === 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
           'sha256js and sha256 (crypto.subtle) equal node\'s for 16 lengths around the 55 / 56 / 64 byte boundaries' + (bad.length ? ': ' + bad : ''));
    }
    const SEED = 20261102, A = await mk(SEED, { walls: true });
    A._oc_step(300); setParam(A, 'minSpeed', 40); A._oc_step(300);
    const f0 = frame(A), imgA = HO.buffer(A).slice(0);   /* (the frame first: its oc_sync changes the memory) */
    const enc = async (img, opts) => { const w = await HO.encodeWorld(worldHead({ frame: f0 }), img, opts); return { w, bytes: await fileOf(w) }; };
    const gz = await enc(imgA), raw = await enc(imgA, { raw: true });
    {
        const a = await HO.decodeWorld(gz.bytes), b = await HO.decodeWorld(raw.bytes), im = gz.w.header.image;
        const c = { gzipSame: Buffer.compare(Buffer.from(HO.wholeImage(a)), Buffer.from(imgA)) === 0, rawSame: Buffer.compare(Buffer.from(HO.wholeImage(b)), Buffer.from(imgA)) === 0,
                    bytes: im.bytes === imgA.byteLength, trimmed: im.stored < im.bytes && im.stored % 4 === 0,
                    zeroTail: zeroFrom({ wasmMemory: { buffer: imgA } }, im.stored) < 0, kinds: im.body === 'gzip' && raw.w.header.image.body === 'raw',
                    smaller: gz.bytes.length < raw.bytes.length, frame: a.header.frame === f0, magic: HO.isWorldFile(gz.bytes), size: gz.bytes.length === gz.w.size };
        ok(all(c), 'a ' + sizeOf(im.bytes) + ' image (' + sizeOf(im.stored) + ' up to its zero tail): gzip ' + sizeOf(gz.bytes.length) + ', raw ' + sizeOf(raw.bytes.length) +
           '; both decode to the very image' + nots(c));
    }
    {   /* opened in a fresh module, and in one whose memory is bigger: the rest zeroed; both run on as the original */
        const B = await opened(gz.bytes), C = await opened(raw.bytes, 48);
        const tail = zeroFrom(C.M, imgA.byteLength), grownC = HO.buffer(C.M).byteLength > imgA.byteLength;
        let diff = '';
        for (let s = 0; s < 60 && !diff; s++) {
            const fa = fingerprint(A), fb = fingerprint(B.M), fc = fingerprint(C.M);
            if (fa !== fb || fa !== fc) diff = 'differ at frame ' + frame(A) + ' (step ' + s + ')';
            A._oc_step(1); B.M._oc_step(1); C.M._oc_step(1);
        }
        ok(!diff && grownC && tail < 0 && frame(B.M) === f0 + 60,
           'saved at frame ' + f0 + ' (a live minSpeed 40 in it), opened in a fresh module and in a ' + memMB(C.M) + ' MB one (its junk past the image zeroed): ' +
           '60 steps bit-identical to the world never saved' + (diff ? ': ' + diff : ''));
    }
    {   /* memory growth: a world whose memory grew, opened in a fresh (16 MB) module, which grows to it */
        const G = await mk(SEED + 1, { walls: true }, 1920, 1080, 300);
        G._oc_step(200); growInside(G); growInside(G); G._oc_step(100);
        const e = await encoded(G, { frame: frame(G) }), O = await opened(e.bytes);
        const diff = sameFor(G, O.M, 30);
        const c = { grewSaver: HO.buffer(G).byteLength > FRESH_MEM, openerToImage: HO.buffer(O.M).byteLength === HO.buffer(G).byteLength, same: !diff };
        ok(all(c), 'a world whose memory grew to ' + memMB(G) + ' MB, opened in a 16 MB module: it grows to the image, then 30 steps bit-identical' +
           ' (file ' + sizeOf(e.bytes.length) + ')' + (diff ? ': ' + diff : '') + nots(c));
    }
    {   /* the sizes, and the Big tank opened */
        const big = CFG.BIG_TANK, T = await mk(9, big.cfg, big.width, big.height, big.population);
        T._oc_step(120);
        const e = await encoded(T, { frame: frame(T) }), O = await opened(e.bytes), diff = sameFor(T, O.M, 6);
        const K = await mk(4242, { walls: true, maxPopulation: 2000, targetFood: 4800 }, 1920, 1080, 2000);
        K._oc_step(60);
        const k = await encoded(K, { frame: frame(K) });
        ok(!diff && T._oc_creature_count() > 1500, 'the Big tank (' + T._oc_creature_count() + ' fish, frame ' + frame(T) + '): file ' + sizeOf(e.bytes.length) +
           ', opened: 6 steps bit-identical; 2,000 fish in the standard tank: ' + sizeOf(k.bytes.length) + '; 300 fish (above): ' + sizeOf(gz.bytes.length) +
           (diff ? ': ' + diff : ''));
    }
    {   /* refusals, each before anything reaches a module */
        const r = HO.worldHeader(gz.bytes), at = r.at, n = gz.bytes.length;
        const cut = (k) => gz.bytes.slice(0, k);
        const flip = (b, i) => { const c = b.slice(); c[i] ^= 0x5a; return c; };
        const cases = [
            ['the magic only', cut(10), /not a saved world/],
            ['cut inside the header length', cut(18), /cut short.*header/],
            ['cut inside the header', cut(at - 5), /cut short.*header/],
            ['cut inside the body', cut(at + 100), /cut short/],
            ['its last byte missing', cut(n - 1), /cut short/],
            ['a byte after its end', new Uint8Array(Buffer.concat([Buffer.from(gz.bytes), Buffer.from([0])])), /after its end/],
            ['a raw body byte flipped', flip(raw.bytes, raw.bytes.length - 4000), /does not match its checksum/],
            ['a gzip body byte flipped', flip(gz.bytes, at + Math.floor((n - at) / 2)), /damaged/],
            ['its checksum changed', reheader(gz.bytes, (h) => { h.image.sha256 = '0'.repeat(64); }), /does not match its checksum/],
            ['its stored length a byte short', reheader(raw.bytes, (h) => { h.image.stored -= 4; h.image.bodyBytes -= 4; }), /after its end/],
            ['an image not whole pages', reheader(gz.bytes, (h) => { h.image.bytes += 4; }), /does not describe a memory image/],
            ['version 2', reheader(gz.bytes, (h) => { h.version = 2; }), /version 2; this page reads version 1/],
            ['another format', reheader(gz.bytes, (h) => { h.format = 'evo_ocean_setup'; }), /not a saved world/],
            ['a setup file', new Uint8Array(Buffer.from(SETUP99)), /is a setup \(Save setup makes those\), not a saved world/],
            ['a picture', new Uint8Array(crypto.randomBytes(5000)), /not a saved world/],
            ['nothing', new Uint8Array(0), /not a saved world/]
        ];
        const bad = [];
        for (const [what, bytes, re] of cases) { const why = await refusal(bytes); if (!re.test(why)) bad.push(what + ': "' + why + '"'); }
        ok(!bad.length, 'refused, each with its reason: ' + cases.map(c => c[0]).join(', ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    }
    {   /* a browser without the gzip streams: it writes the image raw, and reads a raw file; a gzip one it can't */
        const CS = globalThis.CompressionStream, DS = globalThis.DecompressionStream;
        globalThis.CompressionStream = undefined; globalThis.DecompressionStream = undefined;
        let w, why, back;
        try {
            w = await HO.encodeWorld(worldHead({ frame: f0 }), imgA);
            back = await HO.decodeWorld(await fileOf(w));
            why = await refusal(gz.bytes);
        } finally { globalThis.CompressionStream = CS; globalThis.DecompressionStream = DS; }
        ok(w.header.image.body === 'raw' && Buffer.compare(Buffer.from(HO.wholeImage(back)), Buffer.from(imgA)) === 0 && /can't decompress a world file/.test(why),
           'no CompressionStream: Save world writes the trimmed image raw (' + sizeOf(w.size) + '), which opens; a gzip file is refused ("' + why + '")');
    }
}

/* the page's Save world: its file's name and bytes */
async function savedWorld(p) {
    const n = p.downloads.length;
    p.el('err').textContent = '';   /* (an earlier refusal's text is not this save's answer) */
    p.click('saveworld');
    await until(() => p.downloads.length > n || /Couldn't save|not saved/.test(p.msg()), 'Save world\'s file', 120000);
    if (p.downloads.length === n) throw new Error('Save world: ' + p.msg());
    const blob = p.blobs[p.blobs.length - 1];
    return { name: p.downloads[p.downloads.length - 1].name, bytes: new Uint8Array(await blob.arrayBuffer()) };
}
/* From a file with a world file (a real File: its first bytes say what it is); the page's answer */
async function openWorld(p, bytes, name) {
    const e0 = p.T.worldEpoch, id = p.T.fileReq + 1;
    p.el('err').textContent = '';
    p.loadFile(new File([bytes], name || 'saved.oceanworld'));
    /* (a page in Turbo shares node's one event loop with its worker: the decompression waits behind its chunks)
     * The page's own record that this read answered, when it has one (review of #44, round 2, finding 6: a
     * status can change twice between two polls, a rebuild's "The engine restarted" matching none of these) */
    await until(() => p.T.answered(id) !== null ? p.T.answered(id) : p.T.worldEpoch !== e0 || p.T.asking || /That|Couldn't|not opened/.test(p.msg()),
                'the world file\'s answer', 120000).catch((e) => { throw new Error(e.message + ' (the page says "' + p.msg() + '"; test runs ' + p.probes.length + ')'); });
    return p.msg();
}
/* the page's frame, its world stepped n (paused: the frame loop syncs, steps nothing) */
function runPage(p, n) { if (!p.T.paused) p.key(' '); p.M._oc_step(n); p.raf(performance.now()); return frame(p.M); }

async function pageWorldFile() {
    section('Save world / From a file on the page: the file, opened through the door (one epoch, asked when the run has something to lose), bit-identical');
    const p = await bootPage(PAGE_Q);
    runPage(p, 400);
    p.edit('minSpeed', 40);   /* a live tweak: in the file's settings, not its start */
    p.ctx.EvoOcean.select(0); p.click('followbtn');
    const picked = p.T.selectedId, f0 = frame(p.M), print0 = fingerprint(p.M);
    const s = await savedWorld(p);
    p.click('savecp');
    const setup = JSON.parse(p.blobs[p.blobs.length - 1]), h = HO.worldHeader(s.bytes).header;
    ok(/^finfolk_seed4242_frame\d+\.oceanworld$/.test(s.name) && h.frame === f0 && h.engine.wasmSha256 === WASM_SHA &&
       JSON.stringify(h.start) === JSON.stringify(p.T.initArgs) && h.runCfg.minSpeed === 40 && !('minSpeed' in h.start.cfg) &&
       JSON.stringify(h.setup) === JSON.stringify(setup) && h.picked && h.picked.id === picked && h.picked.follow === true &&
       fingerprint(p.M) === print0 && /Saved the world at frame/.test(toastText(p)) && p.T.worldSave === null,
       'Save world: ' + s.name + ' (' + sizeOf(s.bytes.length) + '): frame ' + h.frame + ', the engine build ' + h.engine.wasmSha256.slice(0, 8) +
       ', the setup it started from, its settings now (minSpeed 40), its Save setup file, the fish followed; the world itself untouched');
    /* opened on a fresh page, nothing to lose there: at once, one epoch, no oc_init / oc_reset */
    const q = await bootPage(PAGE_Q7), cq = startCounter(q), a = cq();
    const said = await openWorld(q, s.bytes, s.name);
    const d = delta(a, cq());
    ok(d.epoch === 1 && d.inits === 0 && d.resets === 0 && !q.T.asking && JSON.stringify(q.T.initArgs) === JSON.stringify(p.T.initArgs) &&
       q.T.runCfg.minSpeed === 40 && q.T.getVal('minSpeed') === 40 && q.el('o_seed').value === '4242' && q.T.W === p.T.W && q.T.H === p.T.H &&
       q.T.D === p.T.D && q.T.WALLS === p.T.WALLS && frame(q.M) === f0 && q.T.selectedId === picked && q.ctx.EvoOcean.state().following &&
       /Opened the saved world/.test(said) && /seed=4242/.test(q.loc.href) && !q.T.draft,
       'opened on a fresh page: one epoch, no oc_init, no oc_reset (' + JSON.stringify(d) + '); its start, settings (minSpeed 40 in the sheet), size, ' +
       'frame ' + frame(q.M) + ' and followed fish, the address its setup\'s ("' + said.slice(0, 70) + '…")');
    const diff = sameFor(p.M, q.M, 60);
    ok(!diff, 'the opened world and the one that saved it: 60 steps bit-identical' + (diff ? ': ' + diff : ''));
    {   /* Replay after an opened world: its setup from its start (frame 0), as a fresh oc_init of it */
        q.key('R', { shift: true });
        const asked1 = asked(q) && /live tweak/.test(q.el('startaskmsg').textContent);
        if (asked1) q.click('startconfirm');
        const ref = await mk(4242, p.T.initArgs.cfg, 1920, 1080, 60), dr = delta(a, cq());
        ok(asked1 && dr.resets === 1 && dr.epoch === 2 && frame(q.M) === 0 && fingerprint(q.M) === fingerprint(ref) && !('minSpeed' in q.T.runCfg),
           'Replay on the opened world (asked: its live tweak goes): oc_reset, its setup from frame 0, the same as a fresh oc_init of it; minSpeed back to its start\'s');
    }
    {   /* something to lose (a live tweak): asked; Keep it keeps the run; again, Open it: one epoch */
        const r = await bootPage(PAGE_Q7), cr = startCounter(r);
        r.edit('minSpeed', 35);
        const w0 = r.world(), b = cr();
        await openWorld(r, s.bytes, s.name);
        const msg = r.el('startaskmsg').textContent, label = r.el('startconfirm').textContent;
        r.click('startcancel');
        const kept = r.world() === w0 && delta(b, cr()).epoch === 0 && /Kept your run/.test(r.msg());
        await openWorld(r, s.bytes, s.name);
        r.click('startconfirm');
        const d2 = delta(b, cr());
        ok(/This replaces your run\. It opens the saved world saved\.oceanworld|This replaces your run\. It opens the saved world finfolk_seed4242/.test(msg) &&
           /Slowest speed 35\) goes: the saved world has its own settings/.test(msg) && label === 'Open it' && kept && d2.epoch === 1 && d2.inits === 0 &&
           r.T.initArgs.seed === 4242 && frame(r.M) === f0 && r.uncaught.length === 0,
           'a run with a live tweak: asked ("' + msg + '"), Keep it keeps the run; Open it opens it once (' + JSON.stringify(d2) + ')');
    }
    {   /* the keyboard: From a file pressed with Enter, the question's answer has the focus, Keep gives it back; Esc closes it unopened */
        const k = await bootPage(PAGE_Q7), ck = startCounter(k), b = ck();
        k.edit('minSpeed', 35);
        k.tabTo('loadcp'); k.key('Enter');
        await openWorld(k, s.bytes, s.name);
        const f1 = focused(k);
        k.tabTo('startcancel'); k.key('Enter');
        const f2 = focused(k);
        k.tabTo('loadcp'); k.key('Enter');
        await openWorld(k, s.bytes, s.name);
        const q2 = asked(k);
        k.key('Escape');
        ok(f1 === 'startconfirm' && f2 === 'loadcp' && q2 && !asked(k) && !sheetOpen(k) && delta(b, ck()).epoch === 0,
           'From a file from the keyboard: the question\'s answer focused (' + f1 + '), Keep gives the focus back (' + f2 + '); Esc closes the sheet and the question, nothing opens');
    }
    ok(p.uncaught.length === 0 && q.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.concat(q.uncaught).length ? ' (' + p.uncaught.concat(q.uncaught)[0] + ')' : ''));
}

async function pageWorldTurbo() {
    section('Save world during Turbo (the worker\'s copy, Turbo runs on) and a world opened during Turbo (Stop Turbo & open); after Turbo; memory growth; the Big tank');
    {   /* Save world in Turbo: the acknowledged edit in, the one sent after the question out; Turbo never stops */
        const { p, img, sh } = await pageInTurbo();
        p.edit('maxPopulation', 200);
        await until(() => sh.delivered.some(m => m.type === 'set' && m.key === 'maxPopulation'), 'its answer');
        sh.pause();
        p.click('saveworld');
        p.edit('minSpeed', 40);   /* after the question: not in the copy */
        const waiting = !!p.T.worldSave && p.T.turboState === 'turbo';
        sh.resume();
        const n = p.downloads.length;
        await until(() => p.downloads.length > n || /Couldn't save/.test(p.msg()), 'the file');
        const bytes = new Uint8Array(await p.blobs[p.blobs.length - 1].arrayBuffer()), h = HO.worldHeader(bytes).header;
        const snap = sh.fromWorker.findIndex(m => m.type === 'snapshot'), before = sh.fromWorker.slice(0, snap).filter(m => m.type === 'set' && m.ok).map(m => [m.frame, m.key, m.value]);
        await until(() => p.T.turboStats && p.T.turboStats.frame > h.frame + 60, 'Turbo to run on');
        const ran = p.T.turboState === 'turbo' && !sh.toWorker.some(m => m.cmd === 'stop');
        /* Turbo goes before its copy: the save is cancelled, said so; the next one works (and this page's worker is gone
         * before another page opens the file: in node it would share that page's event loop) */
        sh.pause();
        p.click('saveworld');
        sh.onerror({ message: 'injected: the worker died' });
        await until(() => p.T.turboState === 'live', 'the recovery');
        const t = toastText(p), none = p.T.worldSave === null, n2 = p.downloads.length;
        const again = await savedWorld(p);
        const q = await bootPage(PAGE_Q7);
        await openWorld(q, bytes);
        const fq = frame(q.M), ref = await controlRun(img, before, h.frame), diff = sameFor(q.M, ref, 60);
        const c = { waiting, ran, ackIn: h.runCfg.maxPopulation === 200, laterOut: !('minSpeed' in h.runCfg), ackBefore: before.some(e => e[1] === 'maxPopulation'),
                    laterAfter: !before.some(e => e[1] === 'minSpeed'), frame: fq === h.frame, same: !diff };
        ok(all(c), 'Save world in Turbo: the worker copied its world at frame ' + h.frame + ' and ran on (no Stop); the maxPopulation 200 it acknowledged is in the file, ' +
           'the minSpeed sent after is not; opened, 60 steps bit-identical to the page\'s image with the worker\'s edits replayed' + (diff ? ': ' + diff : '') + nots(c));
        ok(none && /The world was not saved: Turbo stopped before it could copy the world/.test(t) && p.downloads.length === n2 + 1 && again.bytes.length > 0,
           'the worker fails with Save world waiting for its copy: not saved, said so ("' + t.slice(0, 90) + '…"); the next Save world works');
        ok(p.uncaught.length === 0 && q.uncaught.length === 0, 'no exception escaped the page\'s handlers (Turbo save)');
    }
    {   /* a world opened during Turbo: Stop Turbo & open; the hand-back first, then one epoch; the old worker gone */
        const src = await bootPage(PAGE_Q);
        runPage(src, 200);
        const s = await savedWorld(src), f = HO.worldHeader(s.bytes).header.frame;
        const { p, sh } = await pageInTurbo('?seed=7&pop=12&w=1920&h=1080&walls=1');
        const c = startCounter(p), a = c();
        await openWorld(p, s.bytes, s.name);
        const ask = asked(p) && p.el('startconfirm').textContent === 'Stop Turbo & open' && /This stops Turbo and replaces your run, and (.* of evolution and )?what Turbo ran with it\. It opens the saved world/.test(p.el('startaskmsg').textContent);
        p.click('startconfirm');
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back and the open');
        const d = delta(a, c()), f1 = frame(p.M), diff = sameFor(src.M, p.M, 40);
        const k = { ask, oneEpoch: d.epoch === 1 && d.inits === 0 && d.resets === 0, terminated: sh.terminated === 1, seed: p.T.initArgs.seed === 4242,
                    frame: f1 === f, same: !diff };
        ok(all(k), 'From a file in Turbo: asked "Stop Turbo & open"; the hand-back, then the saved world, one epoch (' + JSON.stringify(d) + '), the old worker terminated; ' +
           '40 steps bit-identical to the page that saved it' + (diff ? ': ' + diff : '') + nots(k) + (k.frame ? '' : ' (frame ' + f1 + ', saved ' + f + ')'));
    }
    {   /* after a Turbo round trip; the saver's memory grown (the opener grows); the opener's bigger (the rest zeroed) */
        const p = await bootPage(PAGE_Q);
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        await until(() => p.T.turboStats && p.T.turboStats.frame > 300, 'Turbo to run');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        growInside(p.M); growInside(p.M); p.raf(performance.now());
        const s = await savedWorld(p), im = HO.worldHeader(s.bytes).header.image;
        const small = await bootPage(PAGE_Q7), big = await bootPage(PAGE_Q7);
        for (let i = 0; i < 40; i++) growMiB(big.M);
        new Uint8Array(HO.buffer(big.M)).fill(0xab, im.bytes);   /* junk past the image, as a page that ran a bigger world has */
        big.raf(performance.now());
        await openWorld(small, s.bytes); await openWorld(big, s.bytes);
        const tail = zeroFrom(big.M, im.bytes);
        let diff = '';
        for (let k = 0; k < 40 && !diff; k++) {
            const a = fingerprint(p.M);
            if (a !== fingerprint(small.M) || a !== fingerprint(big.M)) diff = 'differ at frame ' + frame(p.M);
            p.M._oc_step(1); small.M._oc_step(1); big.M._oc_step(1);
        }
        const c = { grewSaver: im.bytes > FRESH_MEM, smallToImage: HO.buffer(small.M).byteLength === im.bytes, bigBigger: HO.buffer(big.M).byteLength > im.bytes,
                    zeroTail: tail < 0, same: !diff };
        ok(all(c), 'saved after a Turbo round trip, its memory grown to ' + (im.bytes / MB) + ' MB: opened on a fresh page (grown to it, ' + memMB(small.M) + ' MB) and a ' +
           memMB(big.M) + ' MB one (its junk past the image zeroed): 40 steps bit-identical to the saver' + (diff ? ': ' + diff : '') + nots(c));
    }
    {   /* the Big tank, through the page */
        const b = await bootPage(PAGE_Q);
        b.click('bigbtn'); b.click('scenario-start');
        runPage(b, 60);
        const s = await savedWorld(b), o = await bootPage(PAGE_Q7);
        await openWorld(o, s.bytes);
        const diff = sameFor(b.M, o.M, 4);
        ok(b.T.W === 3840 && o.T.W === 3840 && o.M._oc_creature_count() > 1500 && !diff,
           'the Big tank (' + o.M._oc_creature_count() + ' fish): saved (' + sizeOf(s.bytes.length) + '), opened on another page, 4 steps bit-identical' + (diff ? ': ' + diff : ''));
    }
}

async function pageWorldRefusals() {
    section('From a file refuses a bad world file with nothing changed; another engine build offers its setup; a setup and a world each go their own way');
    const src = await bootPage(PAGE_Q);
    runPage(src, 100);
    src.edit('minSpeed', 40);
    const s = await savedWorld(src), at = HO.worldHeader(s.bytes).at;
    const p = await bootPage(PAGE_Q7), c = startCounter(p);
    runPage(p, 50);
    const world0 = p.world(), print0 = fingerprint(p.M), a = c();
    const flip = (i) => { const b = s.bytes.slice(); b[i] ^= 0x5a; return b; };
    const cases = [
        ['cut short', s.bytes.slice(0, s.bytes.length - 100), /cut short/],
        ['a damaged body', flip(at + 50), /damaged/],
        ['a bad checksum', reheader(s.bytes, (h) => { h.image.sha256 = 'a'.repeat(64); }), /does not match its checksum/],
        ['version 2', reheader(s.bytes, (h) => { h.version = 2; }), /version 2/],
        ['a header without its world (its checksum made again)', await resealed(s.bytes, (h) => { delete h.start; }), /its start \(the setup it began from\) is not one/]
    ];
    const bad = [];
    for (const [what, bytes, re] of cases) {
        const said = await openWorld(p, bytes);
        if (!re.test(said) || p.world() !== world0 || fingerprint(p.M) !== print0 || p.T.draft || p.T.asking || delta(a, c()).epoch !== 0)
            bad.push(what + ': "' + said + '"');
    }
    ok(!bad.length, 'refused with the run, the sheet and the address as they were: ' + cases.map(x => x[0]).join(', ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* another engine build: its fish can't come; its setup can (Not now: nothing; Use its setup: staged, then Start) */
        const other = await resealed(s.bytes, (h) => { h.engine.wasmSha256 = 'f'.repeat(64); });
        await openWorld(p, other, 'old.oceanworld');
        const m1 = p.el('startaskmsg').textContent, l1 = p.el('startconfirm').textContent;
        p.click('startcancel');
        const none = !p.T.draft && p.world() === world0 && /The saved world was not opened/.test(p.msg());
        await openWorld(p, other, 'old.oceanworld');
        p.click('startconfirm');
        const staged = p.T.draft && p.T.draft.kind === 'file' && p.el('o_seed').value === '4242' && p.T.getVal('minSpeed') === 40 && p.world() === world0;
        p.click('restart');
        if (asked(p)) p.click('startconfirm');
        const d = delta(a, c());
        ok(/another engine build \(ffffffff; this page runs [0-9a-f]{8}\), so its fish can't come back here\. Its setup can: seed 4242/.test(m1) && l1 === 'Use its setup' &&
           none && staged && d.epoch === 1 && d.inits === 1 && p.T.initArgs.seed === 4242 && frame(p.M) === 0 && p.T.runCfg.minSpeed === 40,
           'another engine build: "' + m1.slice(0, 120) + '…"; Not now opens nothing; Use its setup stages its setup (seed 4242, minSpeed 40), which Start starts from frame 0 (' + JSON.stringify(d) + ')');
    }
    {   /* a setup file through From a file (a real file): staged, not opened; a world through the setup reader: refused */
        const q = await bootPage(PAGE_Q7), cq = startCounter(q), b = cq();
        q.loadFile(new File([SETUP99], 'mine.json'));
        await until(() => q.T.draft || /That/.test(q.msg()), 'the setup staged');
        const st = q.T.draft && q.T.draft.kind === 'file' && /Ready: the setup file mine\.json/.test(q.msg()) && delta(b, cq()).epoch === 0;
        q.click('startdiscard');
        q.loadFile({ name: 'w.oceanworld', text: () => Promise.resolve(Buffer.from(s.bytes).toString('latin1')) });
        await until(() => /That/.test(q.msg()), 'the answer');
        ok(st && /That file is a saved world \(Save world makes those\), not a setup/.test(q.msg()) && !q.T.draft && delta(b, cq()).epoch === 0,
           'a setup file (mine.json) through From a file: staged as a setup ("Ready…"), nothing opened; a world file read as text by the setup reader: refused ("' + q.msg() + '")');
    }
    {   /* a read overtaken: a world file read, then R starts a world before it is in: not opened, said so */
        const q = await bootPage(PAGE_Q7), cq = startCounter(q), b = cq();
        let release;
        const gate = new Promise((r) => { release = r; });
        const f = new File([s.bytes], 'slow.oceanworld');
        q.loadFile(gated(f, gate));
        await tick(); await tick();
        q.key('r');
        release();
        await until(() => /not opened/.test(q.msg()) || delta(b, cq()).epoch > 1, 'the overtaken read');
        ok(delta(b, cq()).epoch === 1 && q.T.initArgs.seed !== 4242, 'a world file still being read when R starts a world: the file is dropped ("' + q.msg() + '"), one epoch (R\'s)');
    }
    {   /* an insecure context (no crypto.subtle: the JS SHA-256) and a browser without the gzip streams (raw): both save and open */
        const n = await bootPage(PAGE_Q, { nocrypto: true, nogzip: true });
        runPage(n, 80);
        const w = await savedWorld(n), h = HO.worldHeader(w.bytes).header;
        const o = await bootPage(PAGE_Q7, { nocrypto: true });
        await openWorld(o, w.bytes);
        const fo = frame(o.M), diff = sameFor(n.M, o.M, 20);
        const c = { raw: h.image.body === 'raw', id: h.engine.wasmSha256 === WASM_SHA, frame: fo === h.frame, same: !diff };
        ok(all(c), 'no crypto.subtle, no CompressionStream: Save world writes a raw file (' + sizeOf(w.bytes.length) + ') with the same engine id (the JS SHA-256); ' +
           'it opens, 20 steps bit-identical' + (diff ? ': ' + diff : '') + nots(c) + (all(c) ? '' : ' "' + o.msg() + '"'));
    }
    {   /* the source: an image goes into this page's module only in startWorld (a saved world), the open's undo
         * (restoreRun; rebuildEngine, into a new module) and the Turbo hand-back */
        const srcJs = fs.readFileSync(path.join(WEB, 'ocean.js'), 'utf8');
        const where = [...srcJs.matchAll(/[^.\w]takeMemory\(|HO\.take\(/g)].map(m => { const f = srcJs.lastIndexOf('\n  function ', m.index); return /function (\w+)/.exec(srcJs.slice(f, f + 60))[1]; })
            .filter(n => n !== 'takeMemory');
        const want = 'onTurboMessage,rebuildEngine,restoreRun,startWorld,turboFailed';
        ok(where.sort().join() === want, 'web/ocean.js puts a memory image into its module only in ' + want.replace(/,/g, ', ') + ' (' + where + ')');
    }
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

/* ---------------------------------------------------------------------
 * Codex's review of #44 (codex_reviews/2026-11-03_review_pr44_world-file.md):
 * one section per finding, and the open questions it answered. Each check
 * fails with its fix taken out (the PR lists the planted runs).
 * --------------------------------------------------------------------- */
/* a source readWorld reads from that counts what is read; size: what it says it is */
function countingSource(u8, size) {
    const s = { size: size === undefined ? u8.length : size, reads: [],
                read(a, b) { s.reads.push([a, b]); return Promise.resolve(u8.subarray(a, Math.min(b, u8.length))); } };
    return s;
}
const readBytes = (s) => s.reads.reduce((n, r) => n + (r[1] - r[0]), 0);
async function refusalOf(src, L) { try { await HO.readWorld(src, L).then(r => r.body()); return ''; } catch (e) { return String(e && e.message || e); } }
/* a page's saved world (query: PAGE_Q's, seed 4242, 60 fish), frame 100, a live minSpeed 40; pick: {idx, follow}, a fish picked */
async function aSavedWorld(pick, query) {
    const p = await bootPage(query || PAGE_Q);
    runPage(p, 100);
    p.edit('minSpeed', 40);
    if (pick) { p.ctx.EvoOcean.select(pick.idx); if (pick.follow) p.click('followbtn'); }
    const s = await savedWorld(p);
    return { p, s, h: HO.worldHeader(s.bytes).header, at: HO.worldHeader(s.bytes).at };
}
/* the run as it is: the world, the module's state, the epoch, the selection */
const runOf = (p) => ({ world: p.world(), print: fingerprint(p.T.M), epoch: p.T.worldEpoch, sel: p.T.selectedId, M: p.T.M });
const sameRun = (p, r) => p.world() === r.world && fingerprint(p.T.M) === r.print && p.T.worldEpoch === r.epoch && p.T.selectedId === r.sel;
/* a file of the same header with another image (its checksums made for it): a crafted world */
async function craftedFile(h, image) {
    const c = JSON.parse(JSON.stringify(h));
    delete c.image; delete c.sha256;
    return fileOf(await HO.encodeWorld(c, image));
}

async function reviewLimits() {
    section('Review of #44, finding 1: a world file\'s limits, each checked before the bytes it bounds are read or allocated');
    const L = HO.worldLimits(HO.wasmMemoryMax(WASM_BYTES));
    ok(L.engine === 2048 * MB && L.image === 512 * MB && L.header === MB && L.file > 512 * MB && L.file < 520 * MB,
       'the limits: this build\'s own maximum memory, from its wasm memory section, ' + L.engine / MB + ' MB; an image at most ' + L.image / MB +
       ' MB (what a page opens); a header ' + L.header / MB + ' MB; a file ' + sizeOf(L.file));
    const A = await mk(7, { walls: true });
    A._oc_step(50);
    const real = (await encoded(A, { frame: frame(A) })).bytes, r0 = HO.worldHeader(real), h0 = r0.header;
    const forged = async (fn, body) => { const h = JSON.parse(JSON.stringify(h0)); fn(h); return fileFrom(await HO.sealHeader(h), body === undefined ? real.subarray(r0.at) : body); };
    const cases = [
        ['an image of 1 GiB (more than a page opens)', await forged(h => { h.image.bytes = 1024 * MB; }), /more than this page opens \(512 MB at most\)/],
        ['an image of 4 GiB (more than this engine build can have)', await forged(h => { h.image.bytes = 4096 * MB; }), /more than this engine build can have \(2048 MB\)/],
        ['an image of 2^53 + 64 kB (an integer, not a safe one)', await forged(h => { h.image.bytes = 2 ** 53 + 65536; }), /does not describe a memory image/],
        ['512 MB stored behind a 20 kB gzip body (deflate unpacks at most 1032 bytes from one)',
         await forged(h => { h.image.bytes = 512 * MB; h.image.stored = 512 * MB; h.image.bodyBytes = 20000; }, new Uint8Array(20000)), /can't hold the 536870912 bytes/],
        ['a raw body longer than its stored bytes', await forged(h => { h.image.body = 'raw'; h.image.bodyBytes = h.image.stored + 4; }, new Uint8Array(h0.image.stored + 4)), /can't hold/],
        ['a gzip body bigger than its stored bytes can be', await forged(h => { h.image.bodyBytes = 2 * h.image.stored + 8192; }, new Uint8Array(2 * h0.image.stored + 8192)), /can't hold/],
        ['a header nested 10 deep', await forged(h => { h.x = { a: { b: { c: { d: { e: { f: { g: { k: 1 } } } } } } } }; }), /nested deeper or holds more/],
        ['a header length of 2 MB', (() => { const b = real.slice(0, 24); new DataView(b.buffer).setUint32(16, 2 * MB, true); return b; })(), /header length \(2097152 bytes\)/]
    ];
    const bad = [];
    for (const [what, bytes, re] of cases) {
        const src = countingSource(bytes), why = await refusalOf(src, L);
        if (!re.test(why) || readBytes(src) > 4096) bad.push(what + ': "' + why + '", ' + readBytes(src) + ' bytes read');
    }
    ok(!bad.length, 'refused from the header, the body never read (4 kB read at most): ' + cases.map(c => c[0]).join('; ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* a file whose size alone is too much: nothing of it read */
        const src = countingSource(real, 600 * MB), why = await refusalOf(src, L);
        ok(/600 MB, more than any saved world this page opens/.test(why) && src.reads.length === 0, 'a 600 MB file: refused by its size, not a byte read ("' + why + '")');
    }
    {   /* a gzip world longer than its header says: refused at the first chunk too many, its stream cancelled; shorter: refused */
        const over = await forged(h => { h.image.stored -= 4096; }), under = await forged(h => { h.image.stored += 4096; });
        const proto = globalThis.ReadableStreamDefaultReader.prototype, cancel = proto.cancel;
        let cancels = 0, w1 = '', w2 = '';
        proto.cancel = function () { cancels++; return cancel.apply(this, arguments); };
        try { w1 = await refusalOf(HO.bytesSource(over), L); } finally { proto.cancel = cancel; }
        w2 = await refusalOf(HO.bytesSource(under), L);
        ok(/longer than its header says/.test(w1) && cancels === 1 && /unpacks to \d+ of \d+ bytes/.test(w2),
           'gzip overrun: refused, the decompression cancelled (' + cancels + ' cancel) ("' + w1 + '"); underrun: refused ("' + w2 + '")');
    }
    {   /* on the page: a 600 MB "world" refused before it is read; a 3 MB file that isn't one refused before it is read as text */
        const p = await bootPage(PAGE_Q7), r = runOf(p);
        const big = { name: 'huge.oceanworld', size: 600 * MB, reads: [], slice(x, y) { big.reads.push([x, y]); return new Blob([real]).slice(x, y); } };
        p.el('err').textContent = '';
        p.loadFile(big);
        await until(() => /That/.test(p.msg()), 'the big file\'s answer');
        const m1 = p.msg(), reads = JSON.stringify(big.reads);
        let texts = 0;
        const film = { name: 'film.mp4', size: 3 * MB, slice: (x, y) => new Blob([new Uint8Array(64)]).slice(x, y), text: () => { texts++; return Promise.resolve(''); } };
        p.loadFile(film);
        await until(() => /too big to be a setup/.test(p.msg()), 'the film\'s answer');
        ok(/600 MB, more than any saved world this page opens/.test(m1) && reads === '[[0,16]]' && texts === 0 && /3\.0 MB: not a saved world/.test(p.msg()) && sameRun(p, r),
           'From a file: a 600 MB world file refused after its 16-byte magic only (' + reads + '); a 3 MB file that is not one refused unread ("' + p.msg() + '"); the run as it was');
    }
}

async function reviewHeader() {
    section('Review of #44, finding 3: the header under its own checksum, checked whole and strictly before anything is installed');
    const { s } = await aSavedWorld();
    const p = await bootPage(PAGE_Q7);
    runPage(p, 30);
    const r = runOf(p);
    {   /* a setting changed in the header only (minSpeed 40 -> 41): the image's checksum still holds, the header's doesn't */
        const f = reheader(s.bytes, (h) => { h.runCfg.minSpeed = 41; h.setup.config.minSpeed = 41; });
        const why = await refusal(f), said = await openWorld(p, f);
        const g = reheader(s.bytes, (h) => { h.start.seed = 4243; h.setup.seed = 4243; });
        const said2 = await openWorld(p, g);
        ok(/its header does not match its checksum/.test(why) && /its header does not match its checksum/.test(said) && /its header does not match its checksum/.test(said2) &&
           sameRun(p, r) && !p.T.asking,
           'the header\'s minSpeed 40 -> 41, or its seed 4242 -> 4243, its body untouched: refused as damaged ("' + said + '"), nothing changed');
    }
    const cases = [
        ['a setting as text', (h) => { h.runCfg.minSpeed = '40'; h.setup.config.minSpeed = '40'; }, /have minSpeed as text/],
        ['a setting as a record', (h) => { h.runCfg.foodEnergy = { a: 1 }; }, /have foodEnergy as a record/],
        ['its start\'s settings a list', (h) => { h.start.cfg = []; }, /its start's settings are not a list of settings/],
        ['a picked fish\'s id as text', (h) => { h.picked = { id: '3', follow: true }; }, /its picked fish is not one/],
        ['its setup another seed\'s', (h) => { h.setup.seed = 1; }, /its setup is not this world's/],
        ['its setup another setting\'s', (h) => { h.setup.config.minSpeed = 41; }, /its setup's settings are not this world's/],
        ['a restart-only setting changed while it ran (walls)', (h) => { h.runCfg.walls = !h.runCfg.walls; }, /its settings change walls/],
        ['a field a world file has not', (h) => { h.comment = 'hi'; }, /a field a world file has not/],
        ['no eye in its engine record', (h) => { delete h.engine.eye; }, /its engine record is not one/],
        ['a frame of 2^60 (not a safe integer)', (h) => { h.frame = 2 ** 60; }, /its frame \(1152921504606847000\) is not a whole number/],
        ['a frame of 100.5', (h) => { h.frame = 100.5; }, /its frame \(100.5\) is not a whole number/],
        ['-1 fish', (h) => { h.fish = -1; }, /counts of fish, food and predators/]
    ];
    const bad = [];
    for (const [what, fn, re] of cases) {
        const said = await openWorld(p, await resealed(s.bytes, fn));
        if (!re.test(said) || !sameRun(p, r) || p.T.asking || p.probes.length) bad.push(what + ': "' + said + '"');
    }
    ok(!bad.length, 'a well-sealed header that is not a world\'s, refused before its body is read or tried (no test run), nothing changed: ' +
       cases.map(c => c[0]).join(', ') + (bad.length ? ' — ' + bad.join('; ') : ''));
    ok(p.uncaught.length === 0, 'no exception escaped the page\'s handlers' + (p.uncaught.length ? ' (' + p.uncaught[0] + ')' : ''));
}

async function reviewTransaction() {
    section('Review of #44, finding 2: a saved world tried in a module of its own first; once in, any failure puts the run back (a trap: a new module)');
    const { p: src, s, h } = await aSavedWorld();
    const img0Of = (p) => HO.buffer(p.T.M).slice(0);
    {   /* checksum-valid images that are no world: a zero one (a null world) and a junk one (a trap in the test run) */
        const q = await bootPage(PAGE_Q7);
        runPage(q, 40);
        const r = runOf(q), mem = h.image.bytes;
        const zero = await craftedFile(h, new ArrayBuffer(mem)), junk = await craftedFile(h, new Uint8Array(mem).fill(0xab).buffer);
        const z = await openWorld(q, zero, 'zero.oceanworld'), j = await openWorld(q, junk, 'junk.oceanworld');
        const probes = q.probes.length, done = q.probes.every(sh => sh.terminated === 1);
        ok(/failed its test run \(it holds no world \(its tank is 0 × 0 × 0\)\), so it was not opened\. Nothing changed\./.test(z) &&
           /failed its test run \(the engine stopped on it \(.*(out of bounds|unreachable)/.test(j) && sameRun(q, r) && q.T.M === r.M && probes === 2 && done && !q.T.asking,
           'a zero image and a 0xAB image with valid checksums: each refused by its test run (a worker\'s module of its own, terminated after: ' + probes + ') ("' +
           z.slice(0, 80) + '…"; "' + j.slice(0, 100) + '…"), the run and its module untouched');
    }
    {   /* a test run that never answers: the watchdog terminates it, nothing opens */
        const q = await bootPage(PAGE_Q7), r = runOf(q);
        q.hooks.onProbe = (sh) => sh.pause();
        q.hooks.timer = (ms) => ms === 20000 ? 40 : ms;
        const said = await openWorld(q, s.bytes);
        q.hooks.onProbe = null; q.hooks.timer = null;
        ok(/did not finish one step in 20 s\), so it was not opened/.test(said) && q.probes.length === 1 && q.probes[0].terminated === 1 && sameRun(q, r),
           'a test run that never answers: terminated by the watchdog ("' + said.slice(0, 110) + '…"), nothing changed');
    }
    {   /* something throws once the image is in (a display switch): the run back as it was, bit for bit; the immediate path */
        const q = await bootPage(PAGE_Q7);
        runPage(q, 60);
        const r = runOf(q), img = img0Of(q), real = q.M._oc_set_colour_mode;
        let n = 0;
        q.M._oc_set_colour_mode = function (m) { if (!n++) throw new Error('injected: a display switch fails'); return real.call(this, m); };
        const said = await openWorld(q, s.bytes);
        q.M._oc_set_colour_mode = real;
        const ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img.slice(0), 'the control');
        const k = { said: /couldn't open: injected: a display switch fails\. Your run carries on, as it was/.test(said), world: q.world() === r.world,
                    print: fingerprint(q.T.M) === r.print, epoch: q.T.worldEpoch === r.epoch, sel: q.T.selectedId === r.sel, module: q.T.M === r.M,
                    uncaught: q.uncaught.length === 0 };
        const diff = sameFor(q.T.M, ref, 30);
        ok(all(k) && !diff,
           'a throw after the image went in (nothing to lose: opened at once): "' + said.slice(0, 100) + '…"; the run, the sheet, the epoch as they were, ' +
           '30 steps bit-identical to the run never touched' + (diff ? ': ' + diff : '') + nots(k) + (k.world ? '' : ' ' + q.world() + ' vs ' + r.world) +
           (q.uncaught.length ? ' ' + q.uncaught[0] : ''));
    }
    {   /* the same through the question's answer (a live tweak: asked, Open it): the same recovery, nothing escapes the click */
        const q = await bootPage(PAGE_Q7);
        runPage(q, 60);
        q.edit('minSpeed', 35);
        q.ctx.EvoOcean.select(2);
        const r = runOf(q), img = img0Of(q), real = q.M._oc_set_colour_mode;
        await openWorld(q, s.bytes);
        const wasAsked = asked(q);
        let n = 0;
        q.M._oc_set_colour_mode = function (m) { if (!n++) throw new Error('injected: a display switch fails'); return real.call(this, m); };
        q.el('err').textContent = '';
        q.click('startconfirm');
        q.M._oc_set_colour_mode = real;
        const ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img.slice(0), 'the control');
        const k = { wasAsked, said: /Your run carries on, as it was/.test(q.msg()), world: q.world() === r.world, print: fingerprint(q.T.M) === r.print,
                    epoch: q.T.worldEpoch === r.epoch, tweak: q.T.runCfg.minSpeed === 35, sel: q.T.selectedId === r.sel, uncaught: q.uncaught.length === 0 };
        const diff = sameFor(q.T.M, ref, 30);
        ok(all(k) && !diff,
           'the same failure after Open it (the button path): the run back, its live tweak and its picked fish too, 30 steps bit-identical, no exception from the click' +
           (diff ? ': ' + diff : '') + nots(k) + (all(k) ? '' : ' "' + q.msg().slice(0, 120) + '"') + (q.uncaught.length ? ' ' + q.uncaught[0] : ''));
    }
    {   /* a real trap once the image is in (the test run's answer forged): a new module of the same build, the run put back into it */
        const q = await bootPage(PAGE_Q7);
        runPage(q, 60);
        const r = runOf(q), img = img0Of(q);
        const junk = await craftedFile(h, new Uint8Array(h.image.bytes).fill(0xab).buffer);
        q.hooks.onProbe = (sh) => { sh.rewrite = (m) => m.type === 'probe' ? Object.assign({}, m, { ok: true, why: '', trap: false }) : m; };
        const c = startCounter(q), a = c();
        await openWorld(q, junk, 'junk.oceanworld');
        await until(() => q.T.engineState === 'ok' && q.T.rebuilds === 1, 'the engine to restart');
        q.hooks.onProbe = null;
        const t = toastText(q), msg2 = q.msg(), M1 = q.T.M, back = q.world() === r.world && q.T.worldEpoch === r.epoch;
        const ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img.slice(0), 'the control');
        const diff = sameFor(M1, ref, 30);
        q.key('r');
        const d = delta(a, c());
        const k = { newModule: M1 !== r.M, loads: q.loads.length === 2 && q.loads.every(l => l.sha === WASM_SHA && l.url === q.loads[0].url),
                    said1: /The engine stopped on it, so it is restarting with your run/.test(t), said2: /The engine restarted, and your run is back where it was/.test(msg2),
                    back, same: !diff, startAfter: d.inits === 1 && d.epoch === 1, uncaught: q.uncaught.length === 0 };
        ok(all(k),
           'a real trap after the image went in (memory access out of bounds, the test run told it was fine): a new module of the pinned build (' + q.loads.length +
           ' instances, one Blob URL), the run back in it, 30 steps bit-identical to the run never touched; R then starts a world in it' + (diff ? ': ' + diff : '') +
           nots(k) + (all(k) ? '' : ' "' + t.slice(0, 200) + '" / "' + msg2 + '"') + (q.uncaught.length ? ' ' + q.uncaught[0] : ''));
    }
    {   /* a trap while the page steps (a world that broke after its test run's one step): said once, nothing stepped or started after */
        const q = await bootPage(PAGE_Q7);
        let calls = 0;
        q.M._oc_step = function () { calls++; throw new WebAssembly.RuntimeError('injected: a trap mid-step'); };
        let threw = '';
        try { q.raf(performance.now()); q.raf(performance.now()); } catch (e) { threw = String(e); }
        const said = q.msg();
        q.key('r');
        ok(!threw && calls === 1 && q.T.engineState === 'down' && /The engine stopped \(injected: a trap mid-step\), so this world can't go on\. Reload the page/.test(said) &&
           /engine stopped: reload the page/.test(q.msg()) && q.uncaught.length === 0,
           'a trap in the frame\'s step: the engine stops once and says so ("' + said.slice(0, 90) + '…"), no further step, R refused; nothing thrown from the frame' + (threw ? ' (' + threw + ')' : ''));
    }
    ok(src.uncaught.length === 0, 'no exception escaped the saving page');
}

async function reviewEngineId() {
    section('Review of #44, finding 5: the engine build is the bytes the page fetched once, hashed, and instantiated from a Blob URL of them (the module, Turbo\'s worker, the test run)');
    const p = await bootPage(PAGE_Q);
    runPage(p, 40);
    const l0 = p.loads[0] || {};
    const pin = { fetches: p.wasmFetches, blob: /^blob:/.test(l0.url || ''), sha: l0.sha === WASM_SHA, type: l0.type === 'application/wasm',
                  id: p.T.pinned && p.T.pinned.sha256 === WASM_SHA, max: p.T.pinned && p.T.pinned.maxBytes === 2048 * MB };
    /* engine B on the server now (a rebuild, a deploy): nothing this page runs or writes changes */
    p.wasmBytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]).buffer;
    const s = await savedWorld(p), h = HO.worldHeader(s.bytes).header;
    p.click('turbobtn');
    await until(() => p.T.turboState === 'turbo', 'Turbo');
    const start = p.worker().toWorker.find(m => m.cmd === 'start');
    p.click('turboexit');
    await until(() => p.T.turboState === 'live', 'the hand-back');
    const q = await bootPage(PAGE_Q7);
    await openWorld(q, s.bytes);
    const probe = q.probes[0] && q.probes[0].toWorker[0];
    const c = Object.assign(pin, { saved: h.engine.wasmSha256 === WASM_SHA, oneFetch: p.wasmFetches === 1, turbo: !!start && start.wasm === l0.url,
                                   probe: !!probe && probe.wasm === q.loads[0].url && q.pinnedFiles.get(probe.wasm).sha === WASM_SHA, opened: q.T.initArgs.seed === 4242 });
    ok(all(c), 'one fetch of evo_ocean.wasm, its sha-256 the engine id, the module instantiated from a Blob URL of those bytes (application/wasm), its maximum memory read from them; ' +
       'the server\'s file replaced: Save world still names the build that runs, Turbo\'s worker and the test run get the same Blob URL' + nots(c));
    {   /* a world from engine B (its id that file's hash): its setup offered, its fish not opened */
        const B = crypto.createHash('sha256').update(Buffer.from(p.wasmBytes)).digest('hex');
        const other = await resealed(s.bytes, (x) => { x.engine.wasmSha256 = B; });
        const e0 = q.T.worldEpoch;
        await openWorld(q, other, 'fromB.oceanworld');
        const m = q.el('startaskmsg').textContent;
        q.click('startcancel');
        /* the page names the build it runs: the committed module's own hash (was the literal 040d633c,
           which every rebuild of web/evo_ocean.wasm broke) */
        const runs = new RegExp('another engine build \\([0-9a-f]{8}; this page runs ' + WASM_SHA.slice(0, 8) + '\\)');
        ok(runs.test(m) && q.T.worldEpoch === e0, 'a world saved by engine B: its setup offered, not its fish ("' + m.slice(0, 90) + '…")');
    }
}

async function reviewDraft() {
    section('Review of #44, finding 4: opening a saved world asks over every staged recipe, an untouched one too, and names it');
    const { s } = await aSavedWorld();
    const ways = [
        ['Surprise me', (p) => p.click('randombig')],
        ['Hunters', (p) => p.click('huntersbtn')],
        ['a setup file', (p) => stageFile(p, SETUP99)]
    ];
    const bad = [], fine = [];
    for (const [what, stage] of ways) {
        const p = await bootPage(PAGE_Q7), c = startCounter(p), a = c();
        await stage(p);
        const d0 = p.T.draft, title = d0 && d0.title;
        await openWorld(p, s.bytes);
        const q1 = asked(p), msg = p.el('startaskmsg').textContent;
        p.click('startcancel');
        const kept = p.T.draft === d0 && delta(a, c()).epoch === 0;
        await openWorld(p, s.bytes);
        p.click('startconfirm');
        const d = delta(a, c());
        if (!d0 || !q1 || msg.indexOf('What waits for the next start (' + title + ') is dropped.') < 0 || !kept || d.epoch !== 1 || p.T.draft || p.T.initArgs.seed !== 4242)
            bad.push(what + ': asked ' + q1 + ' "' + msg + '" kept ' + kept + ' ' + JSON.stringify(d));
        else fine.push(what + ' ("' + msg.slice(msg.indexOf('What waits')) + '")');
    }
    ok(!bad.length, 'nothing else to lose, a staged untouched recipe: asked, named; Keep it keeps it staged; Open it drops it and opens: ' + fine.join('; ') + (bad.length ? ' — ' + bad.join('; ') : ''));
}

async function reviewCapture() {
    section('Review of #44, finding 6 and open question 8: the selection first, then the capture; the picked fish of a file, alive, its kin or none, said so; the charts\' fresh history');
    {   /* an unpicked world (capture off) opened over a page with a fish picked (capture on): nothing picked after, and the capture off */
        const { p, s } = await aSavedWorld();
        const q = await bootPage(PAGE_Q7);
        q.ctx.EvoOcean.select(1);
        const had = q.T.selectedId !== null;
        await openWorld(q, s.bytes);
        const diff = sameFor(p.M, q.M, 30);
        ok(had && q.T.selectedId === null && !diff, 'an unpicked world opened over a picked fish: nothing picked, the senses not captured: 30 steps bit-identical, ' +
           'every fish\'s oc_inspect senses included' + (diff ? ': ' + diff : ''));
        const note = q.ctx.EvoOceanDash.note();
        q.key('r');
        if (asked(q)) q.click('startconfirm');
        const note2 = q.ctx.EvoOceanDash.note();
        ok(/^A fresh history: a saved world carries no charts, so recording starts at the saved world opened at frame 1[0-9]{2}\./.test(note) && /^Recording starts with the world/.test(note2),
           'the charts after an open: "' + note + '"; after the next start, as before ("' + note2.slice(0, 40) + '…")');
    }
    {   /* the fish a file picked is not in it (gone during Turbo before the save): the nearest of its family line, said so; its line gone: none, said so */
        const { s, h } = await aSavedWorld({ idx: 3, follow: true });
        const fam = h.picked.family;
        const q = await bootPage(PAGE_Q7);
        const gone = await resealed(s.bytes, (x) => { x.picked = { id: 999999999, follow: true, family: fam, x: h.picked.x + 37, y: h.picked.y - 21, d: h.picked.d }; });
        const said = await openWorld(q, gone);
        const s1 = q.T.lastS, ids = Array.from(s1.ids.subarray(0, s1.n));
        let want = null, bd = Infinity;
        for (let i = 0; i < s1.n; i++) {
            if (Math.round(q.T.inspect(i).info[7]) !== fam) continue;
            const d2 = (s1.segs[12 * i] - h.picked.x - 37) ** 2 + (s1.segs[12 * i + 1] - h.picked.y + 21) ** 2 + (s1.depth[i] - h.picked.d) ** 2;   /* walls: no wrap */
            if (d2 < bd || (d2 === bd && ids[i] < want)) { bd = d2; want = ids[i]; }
        }
        const k = q.ctx.EvoOcean.state();
        const r = await bootPage(PAGE_Q7);
        const none = await resealed(s.bytes, (x) => { x.picked = { id: 999999999, follow: true, family: -77, x: 0, y: 0, d: 0 }; });
        const said2 = await openWorld(r, none);
        const alive = await bootPage(PAGE_Q7);
        await openWorld(alive, s.bytes);
        ok(typeof fam === 'number' && want !== null && k.selectedId === want && k.following &&
           new RegExp('Fish #999999999 is not in it \\(it died during Turbo before the save\\): following #' + want + ', the nearest of its family line').test(said) &&
           r.T.selectedId === null && /nor is any of its family line: nothing followed/.test(said2) && alive.T.selectedId === h.picked.id && alive.ctx.EvoOcean.state().following,
           'a file\'s followed fish gone: its family line\'s nearest followed, said so (#' + want + '); its line gone too: none, said so; alive: itself, followed (#' + h.picked.id + ')');
    }
    {   /* Save world in Turbo: the fish as when Save world was pressed (Esc before the copy comes back changes nothing in the file) */
        const p = await bootPage(PAGE_Q);
        p.ctx.EvoOcean.select(0); p.click('followbtn');
        const id = p.T.selectedId;
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        sh.pause();
        const n = p.downloads.length;
        p.click('saveworld');
        p.key('Escape');
        const let_go = p.T.turboReturn === null;
        sh.resume();
        await until(() => p.downloads.length > n, 'the file');
        const h = HO.worldHeader(new Uint8Array(await p.blobs[p.blobs.length - 1].arrayBuffer())).header;
        ok(let_go && h.picked && h.picked.id === id && h.picked.follow === true && typeof h.picked.family === 'number',
           'Save world in Turbo, then Esc (let go) before the worker\'s copy arrives: the file has the fish as it was when Save world was pressed (#' + id + ', followed, its family line)');
    }
}

async function reviewStaleRead() {
    section('Review of #44, finding 7: a world file\'s refusal that arrives after something newer says nothing over it');
    const { s, at } = await aSavedWorld();
    const damaged = s.bytes.slice();
    damaged[at + 60] ^= 0x5a;
    {   /* the body still being read when R starts a world: no "damaged" over the new world, only that the file was not opened */
        const q = await bootPage(PAGE_Q7), c = startCounter(q), a = c();
        let release;
        const gate = new Promise((r) => { release = r; }), g = gated(new File([damaged], 'bad.oceanworld'), gate, (x) => x < at);
        q.el('err').textContent = '';
        q.loadFile(g);
        await until(() => g.reads.some(r => r[0] === at), 'its body asked for');
        q.key('r');
        release();
        await until(() => /not opened/.test(q.msg()), 'the overtaken read');
        await tick(); await tick();
        const t = toastText(q);
        ok(delta(a, c()).epoch === 1 && !/damaged/.test(q.msg() + t) && /something newer started or was picked while it was read/.test(q.msg()),
           'a damaged world file still being read when R starts a world: its refusal is not shown, only that it was not opened ("' + q.msg() + '")');
    }
    {   /* a newer file meanwhile: the older file's refusal says nothing at all; the newer one's answer stands */
        const q = await bootPage(PAGE_Q7);
        let release;
        const gate = new Promise((r) => { release = r; }), g = gated(new File([damaged], 'bad.oceanworld'), gate, (x) => x < at);
        q.loadFile(g);
        await until(() => g.reads.some(r => r[0] === at), 'its body asked for');
        await openWorld(q, s.bytes, 'good.oceanworld');
        const opened = q.msg();
        release();
        await tick(); await tick(); await new Promise(r => setTimeout(r, 30));
        ok(/^Opened the saved world good\.oceanworld/.test(opened) && q.msg() === opened && !/damaged|not opened/.test(toastText(q)),
           'a newer file opened while a damaged one was read: its answer stands ("' + opened.slice(0, 60) + '…"), the older one says nothing');
    }
}

async function reviewTurboStates() {
    section('Review of #44, coverage: a world opened while Turbo starts and while it stops; cancelled; a refused edit, a refused hand-back, a failing worker meanwhile');
    const { s, h } = await aSavedWorld(null, '?seed=99&pop=40&w=1920&h=1080&walls=1');   /* (seed 99: opened = seed 99) */
    {   /* Starting: asked, Stop Turbo & open queued; its first stats stop it; the hand-back; the open */
        const p = await bootPage(PAGE_Q), c = startCounter(p), a = c();
        p.hooks.onWorker = (sh) => { p.hooks.onWorker = null; sh.pause(); };
        p.click('turbobtn');
        const sh = p.worker();
        await openWorld(p, s.bytes);
        const ask = asked(p) && p.el('startconfirm').textContent === 'Stop Turbo & open';
        p.click('startconfirm');
        const queued = !!p.T.pendingStart && p.T.turboState === 'entering';
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back and the open');
        const d = delta(a, c());
        ok(ask && queued && d.epoch === 1 && d.inits === 0 && frame(p.M) === h.frame && p.T.initArgs.seed === 99 && sh.terminated === 1 && sh.toWorker.some(m => m.cmd === 'stop'),
           'a world file while Turbo starts: asked (Stop Turbo & open), queued; its first stats stop it, then the saved world, one epoch (' + JSON.stringify(d) + ')');
    }
    {   /* Starting, queued, then T: no open, Turbo runs on */
        const p = await bootPage(PAGE_Q), c = startCounter(p), a = c();
        const sh = await turboHeld(p, true);
        await openWorld(p, s.bytes);
        p.click('startconfirm');
        p.key('t');
        const gone = !p.T.pendingStart;
        sh.resume();
        await until(() => p.T.turboState === 'turbo' && sh.delivered.filter(isType('stats')).length >= 3, 'Turbo to run on');
        ok(gone && delta(a, c()).epoch === 0 && p.T.turboState === 'turbo', 'queued while Turbo starts, then T: the open is cancelled, Turbo runs on');
        await toLive(p);
    }
    {   /* Stopping: the open waits for the hand-back already on its way */
        const p = await bootPage(PAGE_Q), c = startCounter(p);
        const sh = await turboHeld(p, false), a = c();
        sh.pause();
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the memory');
        await openWorld(p, s.bytes);
        const ask = asked(p);
        p.click('startconfirm');
        const queued = !!p.T.pendingStart && p.T.turboState === 'exiting';
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the open');
        const d = delta(a, c());
        ok(ask && queued && d.epoch === 1 && frame(p.M) === h.frame && p.T.initArgs.seed === 99,
           'a world file while Turbo stops: asked, queued on the hand-back on its way, then opened (' + JSON.stringify(d) + ')');
    }
    {   /* a live edit refused during the hand-back: the sheet the question was about changed, so no open; the run carries on */
        const { p, sh } = await pageInTurbo();
        const c = startCounter(p), a = c();
        sh.pause();
        p.edit('minSpeed', 200);
        await openWorld(p, s.bytes);
        p.click('startconfirm');
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back');
        const d = delta(a, c());
        ok(!asked(p) && d.epoch === 0 && /setup changed/.test(p.msg()) && p.T.initArgs.seed === 4242 && frame(p.M) !== h.frame,
           'Stop Turbo & open with an edit meanwhile (minSpeed 200, refused): no open, the run handed back carries on ("' + p.msg().slice(0, 80) + '…")');
    }
    {   /* a hand-back the page can't take: Turbo resumes, no open; a worker that fails: its world recovered, no open */
        const { p, sh } = await pageInTurbo();
        const c = startCounter(p), a = c();
        await openWorld(p, s.bytes);
        sh.pause();
        p.click('startconfirm');
        await until(() => sh.queued(isType('memory')), 'the memory');
        const H = p.ctx.EvoOceanHandoff, take = H.take;
        H.take = function () { H.take = take; throw new Error('injected: no room'); };
        sh.resume();
        await until(() => p.T.turboState === 'turbo', 'Turbo resumed');
        const said = p.msg(), d = delta(a, c());
        const sh2 = p.worker();
        sh2.pause();
        trapNext(sh2);
        await until(() => sh2.queued(isType('error')), 'the trap');
        await openWorld(p, s.bytes);
        p.click('startconfirm');
        await sh2.release(isType('error'), 'the error');
        await until(() => p.T.turboState === 'live', 'the recovery');
        ok(d.epoch === 0 && /did not start/.test(said) && delta(a, c()).epoch === 0 && !p.T.pendingStart && /new world did not start/.test(p.msg()) && p.T.initArgs.seed === 4242,
           'Stop Turbo & open with a hand-back the page can\'t take: Turbo runs on, no open ("' + said.slice(0, 60) + '…"); with a worker that fails: recovered, no open');
    }
}

/* ---------------------------------------------------------------------
 * Codex's second review of #44 (codex_reviews/2026-11-03_rereview2_pr44_world-file.md):
 * a section per finding; each check fails with its fix taken out (the PR lists the planted runs).
 * --------------------------------------------------------------------- */
/* a sealed world file of a saved header h with a zero image of `bytes` (all of it stored but its last word: gzip
 * makes it small): what a small file can ask a page to hold */
async function zeroWorld(h, bytes) {
    const img = new Uint8Array(bytes);
    img[bytes - 1] = 1;   /* (a last word not zero: all of it is stored) */
    return craftedFile(h, img.buffer);
}
/* a File whose reads are counted (start, end) */
function countedFile(bytes, name) {
    const f = new File([bytes], name), g = { name, size: f.size, reads: [] };
    g.slice = (x, y) => { g.reads.push([x, y]); return f.slice(x, y); };
    return g;
}
/* the page's Uint8Arrays of length n made from now on (a body's buffer: readParts'), counted; undo() puts the page's own
 * constructor back and answers the count */
function bodyBuffers(p, n) {
    const Real = vm.runInContext('Uint8Array', p.ctx);
    let made = 0;
    p.ctx.Uint8Array = new Proxy(Real, { construct(t, a, nt) { if (a[0] === n) made++; return Reflect.construct(t, a, nt); } });
    return { undo: () => { delete p.ctx.Uint8Array; return made; } };
}
async function answerOf(p, file) {
    const id = p.T.fileReq + 1;
    p.el('err').textContent = '';
    p.loadFile(file);
    await until(() => p.T.answered(id), 'the file\'s answer', 120000);
    return p.msg();
}
const bodyRead = (g, at) => g.reads.some(r => r[0] >= at);

async function review2Budget() {
    section('Second review of #44, finding 1: what an open holds at once, against this device\'s budget, before the body is read; one decode and test run at a time, a superseded one cancelled');
    const { s, h, at } = await aSavedWorld();
    const big = await zeroWorld(h, 64 * MB), bigAt = HO.worldHeader(big).at;
    {   /* a small device (deviceMemory 0.5: a 64 MB image cap, a 192 MB budget): a page whose run uses 40 MB opens a 64 MB world
         * only outside Turbo (in Turbo its worker's copy counts too); grown to 64 MB, not at all; each refusal before the body is read.
         * After Stop Turbo the worker is gone, its memory with it (round 3, finding 1: a stopped worker kept its 40 MB, uncounted):
         * the open after it is admitted without Turbo's copy, and while its test run holds the image no Turbo worker lives */
        const p = await bootPage(PAGE_Q7, { deviceMemory: 0.5 });
        while (HO.buffer(p.M).byteLength < 40 * MB) growMiB(p.M);
        p.raf(performance.now());
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo' && p.T.turboStats && p.T.turboStats.memBytes, 'Turbo');
        const sh = p.worker();
        const g1 = countedFile(big, 'big.oceanworld'), m1 = await answerOf(p, g1);
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        const dropped = sh.terminated === 1 && sh.onmessage === null && p.T.turboWorker === null;
        let alive = null;
        p.hooks.onProbe = () => { alive = p.workers.filter(w => !w.terminated).length; };
        const g2 = countedFile(big, 'big.oceanworld'), m2 = await answerOf(p, g2);
        p.hooks.onProbe = null;
        while (HO.buffer(p.M).byteLength < 70 * MB) growMiB(p.M);
        p.raf(performance.now());
        const g3 = countedFile(big, 'big.oceanworld'), m3 = await answerOf(p, g3);
        const c = { turbo: /would hold about [\d.]+ MB at once with your run and Turbo's copy of it, more than this page lets itself use on this device \(192\.0 MB\)/.test(m1) && /Stop Turbo first/.test(m1) && !bodyRead(g1, bigAt),
                    dropped, live: /failed its test run \(it holds no world/.test(m2) && bodyRead(g2, bigAt) && alive === 0,
                    grown: /would hold about [\d.]+ MB at once with your run, more than this page lets itself use on this device \(192\.0 MB\)/.test(m3) && !bodyRead(g3, bigAt) };
        ok(all(c), 'deviceMemory 0.5, a run of 40 MB, a sealed 64 MB zero world (' + sizeOf(big.length) + '): in Turbo refused unread ("' + m1.slice(0, 150) + '…"); ' +
           'Stop Turbo: its worker terminated at the hand-back (' + sh.terminated + '), its memory with it; live, read and refused by its test run, ' +
           'no Turbo worker alive meanwhile (' + alive + '); the run grown to 70 MB, refused unread' + nots(c));
    }
    {   /* the device's image cap: deviceMemory 2 opens images up to 128 MB, 8 up to 512 MB; a browser that doesn't say: 256 MB (a desktop), 128 MB (a phone) */
        const f = await resealed(big, (x) => { x.image.bytes = 200 * MB; });   /* (refused from its header: its body never read) */
        const p2 = await bootPage(PAGE_Q7, { deviceMemory: 2 }), m2 = await answerOf(p2, countedFile(f, 'a.oceanworld'));
        const pp = await bootPage(PAGE_Q7, { media: { '(pointer: coarse)': true } }), mp = await answerOf(pp, countedFile(f, 'a.oceanworld'));
        const g = await resealed(big, (x) => { x.image.bytes = 300 * MB; });
        const pd = await bootPage(PAGE_Q7), md = await answerOf(pd, countedFile(g, 'b.oceanworld'));
        ok(/needs 200 MB of memory, more than this device opens \(128 MB at most here\)/.test(m2) && /more than this device opens \(128 MB at most here\)/.test(mp) &&
           /needs 300 MB of memory, more than this device opens \(256 MB at most here\)/.test(md),
           'the image cap by device: deviceMemory 2 refuses 200 MB ("' + m2 + '"), a phone that doesn\'t say too, a desktop that doesn\'t say refuses 300 MB');
    }
    {   /* superseded work: a test run held, a newer file meanwhile: the held one is terminated before the newer one's test run starts, and the newer opens */
        const p = await bootPage(PAGE_Q7);
        const runs = [];
        let aliveAtSecond = null;
        p.hooks.timer = (ms) => ms === 50 ? 1500 : ms;   /* (the page notices the superseded run slowly: one at a time must hold anyway) */
        p.hooks.onProbe = (sh) => { runs.push(sh); if (runs.length === 1) sh.pause(); else aliveAtSecond = runs[0].terminated === 0; };
        p.loadFile(new File([s.bytes], 'first.oceanworld'));
        await until(() => runs.length === 1 && runs[0].queue.length, 'the first test run, held');
        const t0 = Date.now(), said = await openWorld(p, s.bytes, 'second.oceanworld'), took = Date.now() - t0;
        p.hooks.timer = null; p.hooks.onProbe = null;
        ok(runs.length === 2 && aliveAtSecond === false && runs[0].terminated === 1 && took < 10000 && /^Opened the saved world second\.oceanworld/.test(said) && !/first/.test(toastText(p)),
           'a newer file while a test run is held: that run terminated (at the page\'s next look, not by the 20 s watchdog: ' + took + ' ms) before the newer one\'s starts ' +
           '(one at a time), the newer opened ("' + said.slice(0, 50) + '…")');
    }
    {   /* the unpacking itself, superseded: cancelled at its next chunk, its stream cancelled (cancelled() is asked before the
         * body's buffer, before its one part is read and before the unpacking: 3 times; then at each chunk: the 2nd one is superseded) */
        const proto = globalThis.ReadableStreamDefaultReader.prototype, cancel = proto.cancel;
        let cancels = 0, why = '', chunks = 0;
        proto.cancel = function () { cancels++; return cancel.apply(this, arguments); };
        try {
            const r = await HO.readWorld(HO.bytesSource(big));
            why = await r.body(() => ++chunks > 4).then(() => '', (e) => String(e.message));
        } finally { proto.cancel = cancel; }
        ok(why === HO.CANCELLED && cancels === 1 && chunks === 5, 'a decode superseded mid-way: it stops at its next chunk (' + chunks + ' asked), its stream cancelled (' + cancels + ')');
    }
    {   /* a question about one saved world, then another file: the question (and its image) goes, the newer file answers */
        const p = await bootPage(PAGE_Q7);
        p.edit('minSpeed', 35);
        await openWorld(p, s.bytes, 'one.oceanworld');
        const first = p.T.asking && p.T.asking.plan;
        let release;
        const gate = new Promise((r) => { release = r; }), g = gated(new File([s.bytes], 'two.oceanworld'), gate);
        const id = p.T.fileReq + 1;
        p.loadFile(g);
        await until(() => g.reads.length >= 2, 'the newer file being read (its magic, then its header)');
        const goneWhileRead = p.T.asking === null;
        release();
        await until(() => p.T.answered(id), 'its answer');
        const second = p.T.asking && p.T.asking.plan;
        ok(first && goneWhileRead && second && first !== second && /two\.oceanworld/.test(p.el('startaskmsg').textContent),
           'a question about one saved world, then another world file: the question (and the image it held) goes as soon as the newer file is picked, before it is read; its own question follows');
    }
    void at;
}

async function review2LateFailure() {
    section('Second review of #44, finding 2: a failure late in an open (after the charts, Turbo\'s history and the draft\'s generation were reset) puts every one of them back');
    const { s } = await aSavedWorld({ idx: 3, follow: true });   /* (its fish followed: the open follows it, the undo must stop that) */
    const rowsOf = (p) => JSON.stringify(p.ctx.EvoOceanDash._rows().map(r => r.st[1]));
    const lateFail = (p) => { const o = p.ctx.EvoOceanDash.origin; p.ctx.EvoOceanDash.origin = function () { p.ctx.EvoOceanDash.origin = o; throw new Error('injected: a late failure'); }; };
    {   /* live: a run with chart history, Turbo used, a fish picked (not followed) */
        const p = await bootPage(PAGE_Q);
        for (let i = 0; i < 4; i++) runPage(p, 61);
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        await until(() => p.T.turboStats && p.T.turboStats.frame > frame(p.M) + 130, 'Turbo to run');
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        p.ctx.EvoOcean.select(2);
        p.raf(performance.now());
        const before = { rows: rowsOf(p), note: p.ctx.EvoOceanDash.note(), used: p.T.usedTurbo, gen: p.T.draftGen, epoch: p.T.worldEpoch, sel: p.T.selectedId,
                         world: p.world(), print: fingerprint(p.M) };
        const img = HO.buffer(p.M).slice(0);
        await openWorld(p, s.bytes);
        const wasAsked = asked(p);
        lateFail(p);
        p.click('startconfirm');
        const ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img.slice(0), 'the control');
        const diff = sameFor(p.M, ref, 30);
        const k = { wasAsked, said: /injected: a late failure\. Your run carries on, as it was/.test(p.msg()), rows: rowsOf(p) === before.rows && JSON.parse(before.rows).length >= 4,
                    note: p.ctx.EvoOceanDash.note() === before.note, usedTurbo: p.T.usedTurbo === true, gen: p.T.draftGen === before.gen, epoch: p.T.worldEpoch === before.epoch,
                    sel: p.T.selectedId === before.sel, notFollowing: !p.ctx.EvoOcean.state().following, world: p.world() === before.world, same: !diff };
        ok(all(k), 'live, a late failure (in the open\'s last step, after its fish was followed): the charts (' + JSON.parse(before.rows).length + ' samples) and their note, Turbo\'s history, ' +
           'the draft\'s generation, the epoch, the picked fish, the follow (off again), the world: all as before; 30 steps bit-identical' + (diff ? ': ' + diff : '') + nots(k));
    }
    {   /* the confirmed Turbo path: Stop Turbo & open with chart history and a followed fish Turbo will pick up again */
        const p = await bootPage(PAGE_Q);
        for (let i = 0; i < 3; i++) runPage(p, 61);
        p.ctx.EvoOcean.select(1); p.click('followbtn');
        const id = p.T.selectedId;
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        await until(() => p.T.turboStats && p.T.turboStats.frame > 600, 'Turbo to run');
        const gen = p.T.draftGen, epoch = p.T.worldEpoch;
        await openWorld(p, s.bytes);
        const wasAsked = asked(p) && p.el('startconfirm').textContent === 'Stop Turbo & open';
        lateFail(p);
        p.click('startconfirm');
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart, 'the hand-back and the open');
        const rows = JSON.parse(rowsOf(p)), st = p.ctx.EvoOcean.state();
        const k = { wasAsked, said: /injected: a late failure\. Your run carries on, as it was/.test(p.msg() + ' ' + toastText(p)), rows: rows.length >= 8 && rows[rows.length - 1] >= 600,
                    note: /^Recorded on this device since the last restart/.test(p.ctx.EvoOceanDash.note()), usedTurbo: p.T.usedTurbo === true, gen: p.T.draftGen === gen,
                    epoch: p.T.worldEpoch === epoch, frame: frame(p.M) >= 600,
                    /* picked up again as after any Stop: itself or its nearest kin, followed; or, its line gone in the long Turbo, said so */
                    fish: st.selectedId !== null ? st.following : /did not survive Turbo/.test(toastText(p)), seed: p.T.initArgs.seed === 4242 && frame(p.M) !== HO.worldHeader(s.bytes).header.frame };
        ok(all(k), 'Stop Turbo & open, a late failure: the run Turbo handed back carries on with its charts (' + rows.length + ' samples, to frame ' + rows[rows.length - 1] + '), ' +
           'Turbo\'s history, the draft\'s generation, the epoch, and its followed fish (#' + id + ') picked up again, as after any Stop (#' + st.selectedId + ')' + nots(k));
    }
    {   /* a real trap after Stop Turbo & open (the test run's answer forged): a new module, the run Turbo handed back in it, its fish picked up again */
        const { h } = await aSavedWorld();
        /* junk in its first MiB only (the static data, where the world's pointer lives: a trap), zeros after; a small stored part
         * (in node a running Turbo worker shares the event loop: a big one unpacks slowly) */
        const junk = await craftedFile(h, new Uint8Array(h.image.bytes).fill(0xab, 0, MB).buffer);
        const p = await bootPage(PAGE_Q);
        p.ctx.EvoOcean.select(1);
        const id = p.T.selectedId;
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        await until(() => p.T.turboStats && p.T.turboStats.frame > 200, 'Turbo to run');
        p.hooks.onProbe = (x) => { x.rewrite = (m) => m.type === 'probe' ? Object.assign({}, m, { ok: true, why: '', trap: false }) : m; };
        await openWorld(p, junk, 'junk.oceanworld');
        p.hooks.onProbe = null;
        sh.pause();
        p.click('startconfirm');
        await until(() => sh.queued(isType('memory')), 'the hand-back');
        const handed = sh.queue.find(isType('memory')), img = handed.mem.slice(0);
        sh.resume();
        await until(() => p.T.turboState === 'live' && !p.T.pendingStart && p.T.engineState === 'ok' && p.T.rebuilds === 1, 'the rebuild');
        const st = p.ctx.EvoOcean.state(), ref = await mk(1, {}, 300, 300, 0);
        HO.take(ref, img, 'the control');
        ref._oc_set_capture(0);
        const fishBack = st.selectedId !== null || /did not survive Turbo/.test(toastText(p));
        if (st.selectedId !== null) ref._oc_set_capture(1);
        const diff = sameFor(p.T.M, ref, 20);
        const k = { rebuilt: p.T.M !== p.M, used: p.T.usedTurbo === true, fish: fishBack, same: !diff, uncaught: p.uncaught.length === 0 };
        ok(all(k), 'Stop Turbo & open with a real trap once the image is in: a new module, the run Turbo handed back put into it (20 steps bit-identical to that hand-back), ' +
           'Turbo\'s history kept, its picked fish (#' + id + ') picked up again (#' + st.selectedId + ')' + (diff ? ': ' + diff : '') + nots(k) + (p.uncaught.length ? ' ' + p.uncaught[0] : ''));
    }
    {   /* a throw while the image is copied in (after writing): the run back too */
        const q = await bootPage(PAGE_Q7);
        runPage(q, 40);
        const r = runOf(q), H = q.ctx.EvoOceanHandoff, take = H.take;
        H.take = function () { H.take = take; take.apply(this, arguments); throw new Error('injected: a copy that failed half-way'); };
        const said = await openWorld(q, s.bytes);
        ok(/injected: a copy that failed half-way\. Your run carries on, as it was/.test(said) && sameRun(q, r), 'a throw from the copy itself, after it wrote: the run back as it was ("' + said.slice(0, 90) + '…")');
    }
}

/* The engine fence's tests (review of #44, round 2 finding 3; round 3 finding 3). FENCE_EXPORTS: the exports counted */
const FENCE_EXPORTS = ['_oc_step', '_oc_sync', '_oc_inspect', '_oc_summary', '_oc_wiring', '_oc_set_param', '_oc_set_capture', '_oc_set_colour_mode', '_oc_families',
                       '_oc_creature_count', '_oc_reset', '_oc_init', '_oc_width', '_oc_light_enabled', '_oc_e1_preset', '_oc_last_error', '_oc_num_senses',
                       '_oc_sensor_names', '_malloc', '_free'];
/* a page whose `name` traps from now on (after setup); calls: every listed export's calls counted; trapAt: the counts when it
 * first trapped (what reached the engine after that, in the same operation too, is what the fence must stop) */
async function fenceTrapping(name, setup, query) {
    const p = await bootPage(query || PAGE_Q7);
    if (setup) await setup(p);
    const calls = {}, t = { at: null };
    for (const f of FENCE_EXPORTS) {
        const real = p.M[f];
        calls[f] = 0;
        p.M[f] = function () {
            calls[f]++;
            if (f === name) { if (!t.at) t.at = Object.assign({}, calls); throw new WebAssembly.RuntimeError('injected: a trap in ' + name); }
            return real.apply(this, arguments);
        };
    }
    return { p, calls, trapAt: () => t.at };
}
/* a tap on the tank's empty water (it lets the picked fish go) */
function tapTank(p) {
    const tap = (type) => { const e = new p.Ev(type, { bubbles: true }); Object.assign(e, { isPrimary: true, button: 0, clientX: 600, clientY: 400, pointerId: 7, pointerType: 'mouse' });
                            p.el('tank').dispatchEvent(e); };
    tap('pointerdown'); tap('pointerup');
}
/* what a visitor does after: frames, the console's state (the memory grown), a tap on the tank, a fish picked, its card closed, Esc,
 * the follow button, a live setting, a colour, follow, Turbo, Save world, R, Replay, a scenario card, the charts' wiring */
async function fenceAfterwards(p) {
    for (let i = 0; i < 3; i++) p.raf(performance.now() + 1000 * i);
    growMiB(p.M);   /* (the views out of date: a fresh() would cut new ones, from the engine) */
    p.ctx.EvoOcean.state();
    tapTank(p);
    p.ctx.EvoOcean.select(0);
    p.click('iclose'); p.key('Escape'); p.click('followbtn');   /* (a fish still picked when it stopped: Close and Esc let it go) */
    p.edit('minSpeed', 33); p.edit('L0', 3);
    p.ctx.EvoOcean.set('minSpeed', 34);
    const b = p.el('colourMode').children.find(c => c.dataset && c.dataset.c === 'brain');
    if (b) b.click();
    p.key('f'); p.key('t'); p.click('saveworld'); p.key('r'); p.click('replay'); p.click('advreset');
    p.ctx.EvoOceanDash.showTab('brains');
    await new Promise(r => setTimeout(r, 700));
    p.ctx.EvoOceanDash.close();
}
/* each way [what, export, setup, trigger, check(p)?]: the trap stops the engine once, said so; nothing reaches it after, nothing throws.
 * Returns [the fine ones, the bad ones (why)] */
async function fenceWays(ways) {
    const bad = [], fine = [];
    for (const [what, name, setup, trigger, check] of ways) {
        const { p, calls, trapAt } = await fenceTrapping(name, setup);
        let threw = '';
        try { await trigger(p); } catch (e) { threw = String(e); }
        const down = p.T.engineState === 'down', said = p.msg(), at = trapAt() || Object.assign({}, calls);
        try { await fenceAfterwards(p); } catch (e) { threw += ' / after: ' + String(e); }
        const more = FENCE_EXPORTS.filter(f => calls[f] !== at[f]).map(f => f + ' ' + (calls[f] - at[f]));
        const once = calls[name] === 1, extra = check ? check(p) : '';
        const stops = p.logs.filter(l => /^ocean: The engine stopped \(/.test(l[1])).length;   /* (said once: an inner fence and the operation's own are one stop) */
        if (threw || !down || !once || more.length || p.uncaught.length || !/[Tt]he engine stopped/.test(said) || !/injected: a trap in /.test(said) ||
            p.T.runCfg.minSpeed === 33 || stops !== 1 || extra)
            bad.push(what + ': ' + JSON.stringify({ threw, down, once: calls[name], more, uncaught: p.uncaught.slice(0, 1), said: said.slice(0, 100), stops, extra }));
        else fine.push(what);
    }
    return [fine, bad];
}

async function review2Fence() {
    section('Second review of #44, finding 3: a trap anywhere the page reads the engine (the sync, a fish card, the readout, the charts\' wiring) stops it once; nothing reaches it after');
    const ways = [
        ['the frame\'s sync', '_oc_sync', null, (p) => p.raf(performance.now())],
        ['a fish card\'s oc_inspect', '_oc_inspect', (p) => { p.ctx.EvoOcean.select(0); }, (p) => p.raf(performance.now())],
        ['the readout\'s summary', '_oc_summary', null, (p) => p.raf(performance.now() + 5000)],
        ['the charts\' wiring (their timer)', '_oc_wiring', null, async (p) => { p.ctx.EvoOceanDash.showTab('brains'); await new Promise(r => setTimeout(r, 700)); p.ctx.EvoOceanDash.close(); }]
    ];
    const [fine, bad] = await fenceWays(ways);
    ok(!bad.length, 'a trap in ' + fine.join(', ') + ': the engine stops once, said so; then frames, a fish picked, a live setting (refused), the console\'s set, a colour, F, T, ' +
       'Save world, R and the charts\' timer reach no export, and nothing throws' + (bad.length ? ' — ' + bad.join('; ') : ''));
}

async function review2SaveLimits() {
    section('Second review of #44, finding 4: Save world refuses, before copying, a world whose memory is more than a world file holds here');
    const slices = (buf) => {   /* ArrayBuffer slices of buf (the module's memory) counted, until undone */
        const proto = ArrayBuffer.prototype, real = proto.slice, n = { count: 0 };
        proto.slice = function () { if (this === buf()) n.count++; return real.apply(this, arguments); };
        n.undo = () => { proto.slice = real; };
        return n;
    };
    {   /* live: a cap below this run's memory (as after a world that grew it: memory never shrinks), then back */
        const p = await bootPage(PAGE_Q7), W = p.ctx.EvoOceanHandoff.WORLD, cap = W.MAX_IMAGE;
        W.MAX_IMAGE = 8 * MB;
        const n = slices(() => HO.buffer(p.M)), blobs = p.blobs.length;
        p.click('saveworld');
        await tick(); await tick();
        n.undo();
        const said = p.msg(), copied = n.count;
        W.MAX_IMAGE = cap;
        const again = await savedWorld(p);
        ok(/Couldn't save the world: it uses 16\.3 MB of memory, more than a world file holds on this device \(8\.0 MB\), so it could not be opened again/.test(said) &&
           copied === 0 && p.blobs.length === blobs + 1 && again.bytes.length > 0 && p.T.worldSave === null,
           'a run whose memory is more than a world file holds here: refused before any copy ("' + said.slice(0, 120) + '…"); with the cap back, Save world writes the file');
    }
    {   /* in Turbo: the worker checks before its copy, Turbo runs on */
        const { p, sh } = await pageInTurbo();
        const W = p.ctx.EvoOceanHandoff.WORLD, cap = W.MAX_IMAGE;
        W.MAX_IMAGE = 8 * MB;
        const n = slices(() => sh.M.wasmMemory.buffer), f0 = p.T.turboStats.frame;
        p.click('saveworld');
        await until(() => !p.T.worldSave, 'the worker\'s answer');
        n.undo();
        const said = p.msg(), copied = n.count;
        W.MAX_IMAGE = cap;
        await until(() => p.T.turboStats.frame > f0 + 60, 'Turbo to run on');
        const k = { said: /more than a world file holds on this device \(8\.0 MB\)/.test(said), notCopied: copied === 0, tooBig: sh.fromWorker.some(m => m.type === 'snapshot' && m.tooBig),
                    running: p.T.turboState === 'turbo' && !sh.toWorker.some(m => m.cmd === 'stop') };
        const again = await savedWorld(p);
        ok(all(k) && again.bytes.length > 0, 'in Turbo: the worker refuses before its copy, Turbo runs on; with the cap back, Save world in Turbo writes the file' + nots(k));
    }
}

async function review2SaveFailures() {
    section('Second review of #44, finding 5: a failed save (the copy, the download, Turbo\'s copy) says so and can be retried; Turbo keeps its world');
    const failOnce = (buf, err) => {   /* the next slice of buf throws */
        const proto = ArrayBuffer.prototype, real = proto.slice;
        proto.slice = function () { if (this === buf()) { proto.slice = real; throw err; } return real.apply(this, arguments); };
        return () => { proto.slice = real; };
    };
    {   /* live: no room for the copy; then the download fails; each time Save world works again */
        const p = await bootPage(PAGE_Q7);
        const undo = failOnce(() => HO.buffer(p.M), new RangeError('injected: Array buffer allocation failed'));
        p.click('saveworld');
        undo();
        const m1 = p.msg(), free1 = p.T.worldSave === null;
        const URLc = p.ctx.URL, create = URLc.createObjectURL;
        URLc.createObjectURL = function () { URLc.createObjectURL = create; throw new Error('injected: no download'); };
        const n = p.downloads.length;
        p.click('saveworld');
        await until(() => !p.T.worldSave, 'the failed download');
        URLc.createObjectURL = create;
        const m2 = p.msg(), free2 = p.T.worldSave === null && p.downloads.length === n;
        const again = await savedWorld(p);
        ok(/Couldn't save the world: injected: Array buffer allocation failed\. Nothing was written/.test(m1) && free1 && /Couldn't save the world: injected: no download/.test(m2) && free2 &&
           again.bytes.length > 0, 'no room for the copy ("' + m1.slice(0, 80) + '…"), then a download that fails ("' + m2.slice(0, 60) + '…"): each said, Save world free again; the third writes the file');
    }
    {   /* Turbo: no room for the worker's copy: said, Turbo runs on with its world (its steps kept), Save world works again */
        const { p, sh } = await pageInTurbo();
        const f0 = p.T.turboStats.frame;
        const undo = failOnce(() => sh.M.wasmMemory.buffer, new RangeError('injected: Array buffer allocation failed'));
        p.click('saveworld');
        await until(() => !p.T.worldSave, 'the worker\'s answer');
        undo();
        const said = p.msg();
        await until(() => p.T.turboStats.frame > f0 + 120, 'Turbo to run on');
        const again = await savedWorld(p), h = HO.worldHeader(again.bytes).header;
        p.click('turboexit');
        await until(() => p.T.turboState === 'live', 'the hand-back');
        const k = { said: /there was no room for a copy of the world \(injected: Array buffer allocation failed\)\. Turbo runs on with its world/.test(said),
                    running: !sh.fromWorker.some(m => m.type === 'error'), saved: h.frame > f0, kept: frame(p.M) > h.frame && sh.fromWorker.some(isType('memory')) };
        ok(all(k), 'in Turbo, no room for the worker\'s copy: said ("' + said.slice(0, 90) + '…"), Turbo runs on, a second Save world in Turbo works (frame ' + h.frame +
           '), and Stop hands back its progress (frame ' + frame(p.M) + ')' + nots(k));
    }
}

async function review2Canon() {
    section('Second review of #44, the canonical form: fixed vectors (keys in UTF-16 order, numbers and strings as JSON.stringify writes them)');
    const v = { b: [1, 1.5, -0, 1e21, 1e-7, 100], a: 'é 🐟"\\', 'é': true, A: null, _: { z: false, y: [] } };
    const want = '{"A":null,"_":{"y":[],"z":false},"a":"é 🐟\\"\\\\","b":[1,1.5,0,1e+21,1e-7,100],"é":true}';
    const d = await HO.headerDigest(v), node = crypto.createHash('sha256').update(Buffer.from('evo_ocean_world 1\n' + want, 'utf8')).digest('hex');
    ok(HO.canon(v) === want && d === node, 'canon of keys A, _, a, b, é (UTF-16 order), -0, 1e21, 1e-7, U+2028, a surrogate pair, a quote and a backslash: "' + want +
       '"; the header digest is node\'s sha-256 of "evo_ocean_world 1\\n" + it (' + d.slice(0, 12) + ')');
}

/* ---------------------------------------------------------------------
 * Codex's third review of #44 (codex_reviews/2026-11-03_rereview3_pr44_world-file.md):
 * a section per finding; each check fails with its fix taken out (the PR lists the planted runs).
 * --------------------------------------------------------------------- */
async function review3Worker() {
    section('Third review of #44, finding 1: the Turbo worker goes at its hand-back, its memory with it (an open never runs beside an uncounted one); the next Turbo gets a fresh one');
    /* (the budget with it: review2Budget's first check, a 40 MB run on a small device after Stop Turbo) */
    const { p, sh } = await pageInTurbo(PAGE_Q7);
    p.click('turboexit');
    await until(() => p.T.turboState === 'live', 'the hand-back');
    const f1 = frame(p.M);
    const first = { terminated: sh.terminated === 1, detached: sh.onmessage === null && sh.onerror === null, none: p.T.turboWorker === null, back: f1 > 120 };
    p.click('turbobtn');
    await until(() => p.T.turboState === 'turbo', 'Turbo again');
    const sh2 = p.worker();
    await until(() => p.T.turboStats && p.T.turboStats.frame > f1 + 120, 'Turbo to run again');
    p.click('turboexit');
    await until(() => p.T.turboState === 'live', 'the second hand-back');
    const k = Object.assign(first, { fresh: sh2 !== sh && p.workers.length === 2, again: sh2.terminated === 1 && p.T.turboWorker === null && frame(p.M) > f1 + 120 });
    ok(all(k), 'Stop Turbo: its worker terminated once at the hand-back, its handlers detached, none left; T again: a fresh worker runs and hands back (frame ' + f1 + ' -> ' + frame(p.M) + '), terminated in turn' + nots(k));
}

async function review3Reads() {
    section('Third review of #44, finding 2: no body read before its turn, a part at a time; a superseded read lets the turn go (a slow part too); the budget again when its turn comes');
    const { s } = await aSavedWorld();
    const at = HO.worldHeader(s.bytes).at;
    {   /* overlapping body reads on a slow disk: A holds the turn, its body read in parts, its first part never coming; B, then C,
         * picked meanwhile (the page's 50 ms look at a superseded read slowed to 1.5 s: A holds the turn that long) */
        const p = await bootPage(PAGE_Q7), W = p.ctx.EvoOceanHandoff.WORLD, part = W.READ_PART;
        W.READ_PART = 64 * 1024;   /* (this file's body: several parts) */
        const parts = Math.ceil((s.bytes.length - at) / W.READ_PART);
        p.hooks.timer = (ms) => ms === 50 ? 1500 : ms;
        const bodies = bodyBuffers(p, s.bytes.length - at);   /* (round 4, finding 2: a body's buffer counted, not only its disk reads) */
        let release;
        const gate = new Promise((r) => { release = r; });
        const a = gated(new File([s.bytes], 'first.oceanworld'), gate, (x) => x < at), b = countedFile(s.bytes, 'second.oceanworld'), c = countedFile(s.bytes, 'third.oceanworld');
        p.loadFile(a);
        await until(() => bodyRead(a, at), 'A\'s first part asked for');
        const t0 = Date.now();
        p.loadFile(b);
        await until(() => b.reads.length >= 2, 'B\'s header read');
        await new Promise(r => setTimeout(r, 80));   /* (B waiting for its turn) */
        const idC = p.T.fileReq + 1;
        p.loadFile(c);
        await until(() => c.reads.length >= 2, 'C\'s header read');
        await new Promise(r => setTimeout(r, 80));
        const waiting = { b: bodyRead(b, at), c: bodyRead(c, at), held: Date.now() - t0 < 1500 };
        await until(() => p.T.answered(idC), 'C\'s answer (A\'s part still on its way)', 120000);
        const opened = p.msg();
        release();   /* A's part comes now: dropped */
        await new Promise(r => setTimeout(r, 100));
        p.hooks.timer = null; W.READ_PART = part;
        const made = bodies.undo();
        const aParts = a.reads.filter(r => r[0] >= at);
        const k = { parts: parts > 2, noBodyWhileHeld: !waiting.b && !waiting.c && waiting.held, aOnePart: aParts.length === 1 && aParts[0][1] - aParts[0][0] === 64 * 1024,
                    bNever: !bodyRead(b, at) && made === 2, cOpened: /^Opened the saved world third\.oceanworld/.test(opened) && bodyRead(c, at),
                    quiet: p.msg() === opened && !/first|second/.test(opened + toastText(p)) };
        ok(all(k), 'A\'s body (' + parts + ' parts of 64 kB) stuck at its first part; B and C picked meanwhile: no body read while A holds the turn; A lets it go with that one part ' +
           'on its way (' + aParts.length + ' asked for, dropped when it came), B (superseded when its turn came) reads none and makes no buffer for it (' + made +
           ' body buffers: A\'s and C\'s), C opens' + nots(k));
    }
    {   /* the budget again when its turn comes: B fits when picked, but the run grows while it waits (deviceMemory 0.5, 40 MB -> 70 MB;
         * A, superseded, holds the turn 1.5 s, its body stuck) */
        const big = await zeroWorld(HO.worldHeader(s.bytes).header, 64 * MB), bigAt = HO.worldHeader(big).at;
        const p = await bootPage(PAGE_Q7, { deviceMemory: 0.5 });
        while (HO.buffer(p.M).byteLength < 40 * MB) growMiB(p.M);
        p.raf(performance.now());
        p.hooks.timer = (ms) => ms === 50 ? 1500 : ms;
        let release;
        const gate = new Promise((r) => { release = r; });
        const a = gated(new File([big], 'a.oceanworld'), gate, (x) => x < bigAt), b = countedFile(big, 'b.oceanworld');
        p.loadFile(a);
        await until(() => bodyRead(a, bigAt), 'A\'s body asked for');
        const idB = p.T.fileReq + 1;
        p.loadFile(b);
        await until(() => b.reads.length >= 2, 'B\'s header read');
        await new Promise(r => setTimeout(r, 80));
        const early = bodyRead(b, bigAt);
        while (HO.buffer(p.M).byteLength < 70 * MB) growMiB(p.M);   /* (the run grew meanwhile: its memory never shrinks) */
        await until(() => p.T.answered(idB), 'B\'s answer', 120000);
        release();
        p.hooks.timer = null;
        const said = p.msg();
        ok(!early && !bodyRead(b, bigAt) && /would hold about [\d.]+ MB at once with your run, more than this page lets itself use on this device \(192\.0 MB\), so it was not read/.test(said),
           'a read admitted after the run grew (40 -> 70 MB while it waited): refused by the budget again when its turn came, its body never read ("' + said.slice(0, 120) + '…")');
    }
}

async function review3Fence() {
    section('Third review of #44, finding 3: Close, Esc, a tap, follow, Replay, a scenario card, the E1 button, a live setting\'s light read, T, Turbo\'s hand-back and failure, ' +
            'an open\'s request: each fenced whole, a first trap there stops the engine once');
    const { s } = await aSavedWorld();
    const picked = async (p) => { p.ctx.EvoOcean.select(0); p.raf(performance.now()); if (p.el('drawer').classList.contains('open')) p.click('drawerclose'); };
    const turbo = async (p) => { p.click('turbobtn'); await until(() => p.T.turboState === 'turbo', 'Turbo'); };
    const turboGone = (p) => p.T.turboState === 'live' && p.workers.every(w => w.terminated) ? '' : 'Turbo left ' + p.T.turboState;
    const ways = [
        ['the fish card\'s Close', '_oc_set_capture', picked, (p) => p.click('iclose')],
        ['Esc letting the fish go', '_oc_set_capture', picked, (p) => p.key('Escape')],
        ['a tap on empty water letting the fish go', '_oc_set_capture', picked, (p) => tapTank(p)],
        ['the console\'s select picking a fish', '_oc_set_capture', null, (p) => p.ctx.EvoOcean.select(0)],
        ['follow (the console\'s and the tour\'s, as F) picking a fish', '_oc_set_capture', null, (p) => p.ctx.EvoOcean.follow()],
        ['Replay (oc_reset)', '_oc_reset', null, (p) => p.click('replay')],
        ['a scenario card (the E1 preset)', '_oc_e1_preset', null, (p) => p.click('advreset')],
        ['the E1 water button', '_oc_e1_preset', null, (p) => p.click('e1add')],
        ['a live light setting (its light read back)', '_oc_light_enabled', null, (p) => p.edit('L0', 2)],
        ['T picking up its fish', '_oc_inspect', picked, (p) => p.key('t'), turboGone],
        ['Turbo\'s hand-back (the world read back)', '_oc_width', turbo, async (p) => {
            p.click('turboexit');
            await until(() => p.T.engineState === 'down' || p.uncaught.length, 'the hand-back');
        }, turboGone],
        ['Turbo\'s worker failing (the run read back)', '_oc_width', turbo, (p) => p.worker().onerror({ message: 'injected: the worker failed' }), turboGone],
        ['an open\'s request after its read (the run\'s age, from views out of date)', '_oc_creature_count', (p) => { growMiB(p.M); }, async (p) => {
            const id = p.T.fileReq + 1;
            p.loadFile(new File([s.bytes], 'w.oceanworld'));
            await until(() => p.T.answered(id), 'the file\'s answer', 120000);
        }]
    ];
    const [fine, bad] = await fenceWays(ways);
    ok(!bad.length, 'a first trap in ' + fine.join(', ') + ': the engine stops once, said so, nothing after it in that operation; then frames, Close, Esc, the follow button, ' +
       'F, a live setting (refused), a colour, T, Save world, R, Replay, a scenario card and the charts\' timer reach no export, and nothing throws' + (bad.length ? ' — ' + bad.join('; ') : ''));
    {   /* the engine stops while Turbo runs (a trap in the waiting picture's sync): Stop's hand-back puts nothing into it, the Brains
         * chart's wiring from Turbo names nothing from it; Turbo keeps the world, running */
        const { p, calls } = await fenceTrapping('_oc_sync', turbo);
        p.raf(performance.now());
        const down = p.T.engineState === 'down', at = Object.assign({}, calls), sh = p.worker();
        p.ctx.EvoOceanDash.showTab('brains');
        await until(() => sh.fromWorker.some(isType('wiring')), 'Turbo\'s wiring');
        await new Promise(r => setTimeout(r, 100));
        p.ctx.EvoOceanDash.close();
        p.click('turboexit');
        await until(() => sh.fromWorker.some(isType('memory')) && p.T.turboState === 'turbo', 'the hand-back refused, Turbo running on');
        const said = p.msg(), f0 = p.T.turboStats.frame;
        await until(() => p.T.turboStats.frame > f0 + 60, 'Turbo to run on');
        const more = FENCE_EXPORTS.filter(f => calls[f] !== at[f]);
        const k = { down, once: calls._oc_sync === 1, none: !more.length, said: /Turbo could not hand the world back \(the engine stopped: reload the page\), so it keeps running\.$/.test(said),
                    running: sh.terminated === 0, uncaught: p.uncaught.length === 0 };
        ok(all(k), 'the engine stopped while Turbo ran: the Brains chart\'s wiring and Stop\'s hand-back reach no export (' + more.join(', ') + '), said ("' + said.slice(0, 100) +
           '…"), Turbo runs on with the world' + nots(k));
    }
}

async function review3Save() {
    section('Third review of #44, finding 4: Save world checks the memory again right before its copy, and the copy itself before the file; encodeWorld keeps the reader\'s cap');
    const slices = (buf) => {   /* ArrayBuffer slices of buf (the module's memory) counted, until undone */
        const proto = ArrayBuffer.prototype, real = proto.slice, n = { count: 0 };
        proto.slice = function () { if (this === buf()) n.count++; return real.apply(this, arguments); };
        n.undo = () => { proto.slice = real; };
        return n;
    };
    {   /* live: the memory within the cap when Save world starts, the picked fish's inspection grows it past (oc_inspect allocates) */
        const p = await bootPage(PAGE_Q7), W = p.ctx.EvoOceanHandoff.WORLD, cap = W.MAX_IMAGE;
        p.ctx.EvoOcean.select(0);
        p.raf(performance.now());
        W.MAX_IMAGE = HO.buffer(p.M).byteLength;   /* (the cap: the memory as it is) */
        const real = p.M._oc_inspect;
        let grew = 0;
        p.M._oc_inspect = function () { if (!grew++) growMiB(p.M); return real.apply(this, arguments); };
        const n = slices(() => HO.buffer(p.M)), downloads = p.downloads.length;
        p.click('saveworld');
        await tick(); await tick();
        n.undo(); p.M._oc_inspect = real;
        const said = p.msg(), copied = n.count, saving = p.T.worldSave;
        await new Promise(r => setTimeout(r, 200));
        const k = { grew: grew >= 1, said: /^Couldn't save the world: it uses [\d.]+ MB of memory, more than a world file holds on this device \([\d.]+ MB\), so it could not be opened again/.test(said),
                    notCopied: copied === 0, notDownloaded: p.downloads.length === downloads, free: saving === null };
        W.MAX_IMAGE = cap;
        const again = await savedWorld(p);
        ok(all(k) && again.bytes.length > 0, 'the picked fish\'s inspection grows the memory past the cap after the first check: refused before the copy ("' + said.slice(0, 100) +
           '…"), nothing downloaded, Save world free; with the cap back it saves' + nots(k));
    }
    {   /* the copy checked before the file, whoever made it: Turbo's answer bigger than the save's limit (as a worker that didn't check would send) */
        const { p, sh } = await pageInTurbo(PAGE_Q7);
        const W = p.ctx.EvoOceanHandoff.WORLD, cap = W.MAX_IMAGE;
        W.MAX_IMAGE = 24 * MB;
        sh.rewrite = (m) => m.type === 'snapshot' && m.mem ? Object.assign({}, m, { mem: new ArrayBuffer(32 * MB) }) : m;
        const downloads = p.downloads.length;
        p.click('saveworld');
        await until(() => !p.T.worldSave, 'the worker\'s answer');
        await new Promise(r => setTimeout(r, 200));
        sh.rewrite = null; W.MAX_IMAGE = cap;
        const said = p.msg();
        ok(/^Couldn't save the world: it uses 32\.0 MB of memory, more than a world file holds on this device \(24\.0 MB\)/.test(said) && p.downloads.length === downloads &&
           p.T.turboState === 'turbo', 'a copy bigger than the save\'s limit (32 MB, 24 MB): refused before its file is made ("' + said.slice(0, 100) + '…"), nothing downloaded, Turbo runs on');
    }
    {   /* encodeWorld: the reader's cap (opts.limits) */
        const M0 = await mk(1, {}, 300, 300, 0), img = HO.buffer(M0).slice(0);
        const why = await HO.encodeWorld(worldHead({}), img, { limits: HO.worldLimits(null, 8 * MB) }).then(() => '', (e) => String(e.message));
        const fits = await HO.encodeWorld(worldHead({}), img, { limits: HO.worldLimits(null, 32 * MB) }).then((w) => w.size > 0, () => false);
        ok(/^its memory \([\d.]+ MB\) is more than a world file holds \(8\.00 MB at most\), so it could not be opened again$/.test(why) && fits,
           'encodeWorld refuses an image over the reader\'s cap ("' + why + '"), writes one within it');
    }
}

/* ---------------------------------------------------------------------
 * Codex's fourth review of #44 (codex_reviews/2026-11-04_rereview4_pr44_world-file.md):
 * each check fails with its fix taken out (the PR lists the planted runs).
 * --------------------------------------------------------------------- */
async function review4Fence() {
    section('Fourth review of #44, findings 1 and 3: a trap in an inner fence ends the whole operation, no allocator call after it (an edit held for ' +
            'Turbo\'s hand-back, replayed; Turbo\'s worker failing meanwhile); the console\'s readers fenced (their snapshot cut again)');
    /* Turbo; Stop, its hand-back held (the worker's answer queued); a live edit meanwhile: held for the hand-back */
    const held = async (p) => {
        p.click('turbobtn');
        await until(() => p.T.turboState === 'turbo', 'Turbo');
        const sh = p.worker();
        sh.pause();
        p.click('turboexit');
        await until(() => sh.queued(isType('memory')), 'the hand-back, held');
        p.edit('minSpeed', 36);
        if (!Object.keys(p.T.live.held()).length) throw new Error('the edit was not held');
    };
    const gone = (p) => p.T.turboState === 'live' && p.workers.every(w => w.terminated) ? '' : 'Turbo left ' + p.T.turboState;
    const stale = (p) => { growMiB(p.M); };   /* (the views out of date: a reader cuts a new snapshot, from the engine) */
    const ways = [
        ['the edit held for Turbo\'s hand-back, replayed (oc_set_param)', '_oc_set_param', held, (p) => p.worker().resume(), gone],
        ['the edit held, replayed as Turbo\'s worker fails (oc_set_param)', '_oc_set_param', held, (p) => p.worker().onerror({ message: 'injected: the worker failed' }), gone],
        ['the console\'s state', '_oc_creature_count', stale, (p) => p.ctx.EvoOcean.state()],
        ['the console\'s deepest', '_oc_creature_count', stale, (p) => p.ctx.EvoOcean.deepest()],
        ['the console\'s steepest', '_oc_creature_count', stale, (p) => p.ctx.EvoOcean.steepest()]
    ];
    const [fine, bad] = await fenceWays(ways);
    ok(!bad.length, 'a first trap in ' + fine.join(', ') + ': the engine stops once, said once; from the trap on nothing reaches the module (no free of the ' +
       'setting\'s C string, no oc_last_error, no frame read), and nothing after it does' + (bad.length ? ' — ' + bad.join('; ') : ''));
}

async function review4Reads() {
    section('Fourth review of #44, finding 2: a read superseded before its body is read makes no buffer for it (the page\'s queued read: review3Reads)');
    const { s } = await aSavedWorld();
    const at = HO.worldHeader(s.bytes).at, len = s.bytes.length - at, part = HO.WORLD.READ_PART, Real = globalThis.Uint8Array;
    let made = 0, reads = 0, why = '';
    HO.WORLD.READ_PART = 64 * 1024;   /* (this body: several parts, one buffer for them) */
    try {
        const src = HO.bytesSource(s.bytes), counted = { size: src.size, read: (x, y) => { if (x >= at) reads++; return src.read(x, y); } };
        const r = await HO.readWorld(counted);
        globalThis.Uint8Array = new Proxy(Real, { construct(t, a, nt) { if (a[0] === len) made++; return Reflect.construct(t, a, nt); } });
        why = await r.body(() => true).then(() => '', (e) => String(e.message));
    } finally { globalThis.Uint8Array = Real; HO.WORLD.READ_PART = part; }
    ok(why === HO.CANCELLED && made === 0 && reads === 0 && len > 2 * 64 * 1024,
       'a body of ' + Math.ceil(len / 65536) + ' parts, superseded before it is read: cancelled with no buffer made (' + made + ') and no part read (' + reads + ')');
    {   /* superseded between two parts that come at once (before the 50 ms look at a part on its way): no further part is read */
        let stale = false, n = 0, why2 = '';
        HO.WORLD.READ_PART = 64 * 1024;
        try {
            const src = HO.bytesSource(s.bytes), counted = { size: src.size, read: (x, y) => { if (x >= at) { n++; stale = true; } return src.read(x, y); } };
            const r = await HO.readWorld(counted);
            why2 = await r.body(() => stale).then(() => '', (e) => String(e.message));
        } finally { HO.WORLD.READ_PART = part; }
        ok(why2 === HO.CANCELLED && n === 1, 'a read superseded while its first part is read (that part comes at once): no further part is read (' + n + ' of ' +
           Math.ceil(len / 65536) + ')');
    }
}

/* ---------------------------------------------------------------------
 * Codex's fifth review of #44 (codex_reviews/2026-11-04_rereview5_pr44_world-file.md)
 * --------------------------------------------------------------------- */
async function review5Bench() {
    section('Fifth review of #44: the benchmark\'s stepToTick steps through the page\'s fenced hook, every step; a trap while its snapshot is cut again, ' +
            'or in a later step, stops the engine once and the stepping with it, nothing reaching the module after');
    /* a paused benchmark page (its own frames step nothing); from the `from`th call of `name` on, it traps; then stepToTick far ahead,
     * its frames run (at most 300) until it settles */
    async function run(name, from, grow) {
        const p = await bootPage('?renderBench=1&' + PAGE_Q7.slice(1), { perf: true });
        p.click('pausebtn');
        const f0 = frame(p.M);
        if (grow) growMiB(p.M);   /* (the views out of date: the benchmark's snapshot is cut again, from the engine) */
        const calls = {};
        let n = 0, at = null, settled = null;
        for (const f of FENCE_EXPORTS) {
            const real = p.M[f];
            calls[f] = 0;
            p.M[f] = function () {
                calls[f]++;
                if (f === name && ++n >= from) { if (!at) at = Object.assign({}, calls); throw new WebAssembly.RuntimeError('injected: a trap in ' + name); }
                return real.apply(this, arguments);
            };
        }
        p.raf = null;   /* (the page's own frame let go: only the benchmark's frames run here, so the trap comes in its path) */
        try {
            p.ctx.EvoOcean.bench.stepToTick(f0 + 600).then(() => { settled = 'resolved'; }, (e) => { settled = 'rejected: ' + String(e && e.message || e); });
        } catch (e) { settled = 'threw: ' + String(e && e.message || e); }
        for (let i = 0; i < 300 && settled === null; i++) { const cb = p.raf; p.raf = null; if (cb) cb(performance.now()); await tick(); }
        const more = at ? FENCE_EXPORTS.filter(f => calls[f] !== at[f]).map(f => f + ' ' + (calls[f] - at[f])) : ['no trap'];
        const stops = p.logs.filter(l => /^ocean: The engine stopped \(/.test(l[1])).length;
        return { settled: settled || 'still stepping after 300 frames', down: p.T.engineState === 'down', more, stops, said: p.msg().slice(0, 80), uncaught: p.uncaught.length };
    }
    const a = await run('_oc_creature_count', 1, true), b = await run('_oc_step', 2, false);
    const k = { snapshot: /^rejected: the benchmark has no snapshot/.test(a.settled) && a.down && !a.more.length && a.stops === 1 && !a.uncaught,
                laterStep: /^rejected: stepToTick: the engine could not step/.test(b.settled) && b.down && !b.more.length && b.stops === 1 && !b.uncaught };
    ok(all(k), 'a first trap while stepToTick\'s snapshot is cut again (' + JSON.stringify(a) + '), and in its second step, after a frame (' + JSON.stringify(b) +
       '): the engine stops once, said once; stepToTick rejects; from the trap on nothing reaches the module' + nots(k));
}

/* Codex's sixth review of #44 (codex_reviews/2026-11-04_rereview6_pr44_world-file.md) */
async function review6BenchImport() {
    section('Sixth review of #44: the benchmark\'s prepare imports a case\'s world through the page\'s fenced hook; a first trap in its oc_init stops the engine once, prepare rejects, the next frame reads nothing');
    const p = await bootPage('?renderBench=1&' + PAGE_Q7.slice(1), { perf: true });
    const calls = {};
    let at = null, settled = null;
    for (const f of FENCE_EXPORTS) {
        const real = p.M[f];
        calls[f] = 0;
        p.M[f] = function () {
            calls[f]++;
            if (f === '_oc_init') { if (!at) at = Object.assign({}, calls); throw new WebAssembly.RuntimeError('injected: a trap in _oc_init'); }
            return real.apply(this, arguments);
        };
    }
    try {   /* (another seed: prepare imports the case's world) */
        p.ctx.EvoOcean.bench.prepare({ worldSeed: 99, population: 12, settleMs: 0 })
            .then(() => { settled = 'resolved'; }, (e) => { settled = 'rejected: ' + String(e && e.message || e); });
    } catch (e) { settled = 'threw: ' + String(e && e.message || e); }
    for (let i = 0; i < 5 && settled === null; i++) await tick();
    for (let i = 0; i < 3; i++) if (p.raf) p.raf(performance.now() + 1000 * i);   /* the next frames (paused: a sync and a snapshot, were the engine running) */
    const more = at ? FENCE_EXPORTS.filter(f => calls[f] !== at[f]).map(f => f + ' ' + (calls[f] - at[f])) : ['no trap'];
    const stops = p.logs.filter(l => /^ocean: The engine stopped \(injected: a trap in _oc_init\)/.test(l[1])).length;
    const k = { rejected: /^rejected: the case's world was refused: the engine stopped/.test(settled || ''), down: p.T.engineState === 'down', once: calls._oc_init === 1,
                said: stops === 1, none: !more.length, uncaught: p.uncaught.length === 0 };
    ok(all(k), 'prepare with another seed, a first trap in its oc_init: the engine stops once, said once; prepare rejects ("' + String(settled).slice(0, 90) +
       '"); nothing reaches the module after, the next frames\' sync included (' + more.join(', ') + ')' + nots(k));
}

/* Every section, in order; `node tests/ocean_turbo_handoff.js NAME...` runs only those. */
const SECTIONS = {
    repeatedKeys, liveLedger, growthPage, randomize, imports,
    roundTripDefault: () => roundTrip('the default world', {}),
    roundTripE1: async () => {
        const probe = await mk(1);
        const e1 = JSON.parse(HO.cString(probe, probe._oc_e1_preset()));
        await roundTrip('E1 physics, 3 predators with their economy, patchy food',
                        Object.assign({}, e1, { predatorCount: 3, predatorEconomy: true, predatorMeal: 7, predatorMaxPopulation: 12,
                                                foodPatches: 5, foodDepthMode: 1, bodyModel: true }));
    },
    failures: failures_,
    pageHeld, pageRefusal, pageAsyncSetup, pageStartFailures, pageOverflow, pageBools, pageDashboards,
    pageWallsOverride, pageFreshVisit, pageSizeFields, pageRoundTrip,
    pageColourBench, pageLayers, pageResize, pageKeys, pageStartupFailures, pageTourEscape, pageWholeFields,
    pageTurboFraction, pageCardNumbers, pageMixedRecovery, pageEscOwner, pageTabKeys, pageIntegralFloats,
    pageTurboMode, pageStartDoor, pageFollowBack, pageDraft, pageScenarios,
    pageCancelQueued, pageQueuedFile, pageNextBehindLive, pageEditedFile, pageReplayStaleRead, pageAskTarget, pagePendingAsk,
    pageKeyboardAsk,
    worldCodec, pageWorldFile, pageWorldTurbo, pageWorldRefusals,
    reviewLimits, reviewHeader, reviewTransaction, reviewEngineId, reviewDraft, reviewCapture, reviewStaleRead, reviewTurboStates,
    review2Budget, review2LateFailure, review2Fence, review2SaveLimits, review2SaveFailures, review2Canon,
    review3Worker, review3Reads, review3Fence, review3Save,
    review4Fence, review4Reads, review5Bench, review6BenchImport
};
const unhandled = [];
process.on('unhandledRejection', (e) => { unhandled.push(e); });
(async () => {
    const t0 = Date.now(), only = process.argv.slice(2);
    const bad = only.filter(n => !SECTIONS[n]);
    if (bad.length) throw new Error('no section ' + bad.join(', ') + ' (sections: ' + Object.keys(SECTIONS).join(', ') + ')');
    for (const name of Object.keys(SECTIONS)) {
        if (only.length && !only.includes(name)) continue;
        /* a section that throws is one failed check, and the others still run */
        try { await SECTIONS[name](); } catch (e) { ok(false, name + ' threw: ' + String(e && e.stack || e).split('\n').slice(0, 3).join(' | ')); }
        for (const p of PAGES.splice(0)) for (const sh of p.workers.concat(p.probes)) if (!sh.terminated) sh.terminate();   /* its pages' Turbo stops with it */
    }
    ok(unhandled.length === 0, 'no unhandled promise rejection' + (unhandled.length ? ': ' + unhandled[0] : ''));
    console.log('\n' + (checks - failures) + ' / ' + checks + ' checks passed in ' + ((Date.now() - t0) / 1000).toFixed(1) + ' s');
    process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
