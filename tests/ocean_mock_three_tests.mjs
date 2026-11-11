// tests/ocean_mock_three_tests.mjs: the scene's fish materials, frame by frame, in node (no browser, no GPU).
//   node tests/ocean_mock_three_tests.mjs [--web DIR] [--against OLD_WEB] [--frames-out FILE]
// The page's scripts run in a vm context in ocean.html's order, with the real three bundle (web/vendor: its objects, math,
// materials and geometry) and a recording stand-in for WebGLRenderer. The scene is created and driven through a scripted
// session (#58's): appearance snapshots in a whole-tank view, close up (fish lit: the full programs once their prewarm
// compiled), the hold back to plain, the lit fish's split, the polish off / on, detail 1 / 3, the skin, legacy snapshots,
// predators close, the legacy fish and predators whole, back, then a panel's inset two ways (the view offset moves the
// frustum's side planes) and none. Each frame the recorder emulates three's render list
// (opaque by renderOrder, material id, then depth as three takes it: the geometry's bounding-sphere centre through
// matrixWorld and the projection; transparent by renderOrder, depth, object id) and records, draw by draw: the object (its
// place in the scene), the material by source text (sha256 of each stage), its options and uniforms (names and values),
// the instance count / draw range; the uploads three would make (each attribute and texture whose version moved, with its
// update ranges; a texture's onUpdate called as three does); the programs first used or compiled; the profiler's counters
// and the scene's polish() state. Checks:
//   1. every frame, every fish mesh draws the programs of the variant its kind committed (the variant the binder was last
//      handed for that mesh, and drew: EvoOceanMaterials' bind), by their source text against the shader module's own
//      strings (FISH_VS / FISH_FS / SHADOW_VS / SHADOW_FS, appearanceShaders, litSkip)
//   2. the session's recording against its committed sha256 (GOLDEN): any change in what the scene draws, in what order,
//      with what uniforms, what it uploads or compiles, shows here (an intended one updates GOLDEN, its reason in the commit)
//   3. planted: the appearance kind, or the legacy kinds, binding the variant a frame late; a second writer of .material;
//      the side planes never recomputed (the inset steps): each is seen
//   4. a WebGL context loss and the polished programs' prewarm (#50's review, P2): a compile started before the loss,
//      finishing after the restore (or the old 5 s fallback running out while the context was lost), never lets a kind
//      draw its polished programs in the restored context before a prewarm there has compiled them; a prewarm finished
//      before the loss counts for nothing after the restore (planted: main's readiness, which outlives it, is seen); a
//      feature set's activation the loss overtook is refused; a prewarm past its budget is asked again (planted: not)
//   5. the diagnostics before bind() (step 3's review)
//   --against OLD_WEB: both sides' sessions, frame by frame (the structure PRs' identity proof against main's web/)
//   --web DIR: another web/ (main's, to see checks 4 and 5 fail on it)
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import crypto from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const opt = (k) => (argv.indexOf(k) >= 0 ? argv[argv.indexOf(k) + 1] : null);
const WEB = path.resolve(opt("--web") || path.join(HERE, "..", "web"));
const AGAINST = opt("--against") ? path.resolve(opt("--against")) : null;
const OUTF = opt("--frames-out");
/* the recording of the session on this tree's web/ (sha256 of its frames, 16 hex). It changes only when what the scene draws
 * changes: then the new value goes here, with the reason in the commit. ff2f626dc192c801: main f2a16b4's recording of this
 * session (465 frames: #58's 415 (06d8477362e68680), then the inset steps), the same frame for frame on render-followups1 */
const GOLDEN = "ff2f626dc192c801";
const H = (s) => crypto.createHash("sha256").update(s).digest("hex").slice(0, 16);
/* planted reverts of render-followups1's fixes in web/ocean_scene.js (the review of #59): each must be seen */
const MUTANTS = {
  readyOutlives: ["function warm(wm) { return wm.ready === ctxGen; }", "function warm(wm) { return wm.ready >= 0; }"],   /* main's readiness: it outlives a restore */
  noRetry: ["if (r.timeout) wm.asked = -1;", ""],                                                                         /* a prewarm past its budget never asked again */
  planesOnce: ["if (p0 === K[0] && p5 === K[1] && p8 === K[2] && p9 === K[3]) return;", "if (K[0] === K[0]) return;"]    /* the side planes never recomputed */
};
const SCRIPTS = ["ocean_appearance.js", "ocean_appearance_slots.js", "ocean_shaders.js", "ocean_pose.js", "ocean_materials.js", "ocean_scene_parity.js", "ocean_scene.js"];

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 600) : "")); }
  else console.log("  ok   " + what);
}

/* ---- a deterministic world ---- */
function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const W = 1600, HH = 900, D = 240;
function World(n, pc, withApp, epoch) {
  const r = rng(7 + n), fish = [];
  for (let i = 0; i < n; i++) fish.push({ id: 10 + 3 * i, x: r() * W, y: r() * HH, a: r() * 6.283, d: 10 + r() * (D - 20), sz: 0.7 + r() * 0.8, el: 0.8 + r() * 0.5,
    c: [Math.floor(r() * 255), Math.floor(r() * 255), Math.floor(r() * 255)], genes: Array.from({ length: 63 }, () => r()) });
  const preds = []; for (let i = 0; i < pc; i++) preds.push({ x: r() * W, y: r() * HH, a: r() * 6.283, d: 20 + r() * 150, fed: i % 2 });
  return { fish, preds, tick: 0, epoch, withApp };
}
function step(w) {
  w.tick += 2;
  for (const f of w.fish) { f.a += 0.05 * Math.sin(w.tick * 0.03 + f.id); f.x = (f.x + 2.2 * Math.cos(f.a) + W) % W; f.y = (f.y + 2.2 * Math.sin(f.a) + HH) % HH; }
  for (const p of w.preds) { p.a += 0.04; p.x = (p.x + 3 * Math.cos(p.a) + W) % W; p.y = (p.y + 3 * Math.sin(p.a) + HH) % HH; }
}
function snap(w) {
  const n = w.fish.length, s = { n, segs: new Float32Array(12 * n), colors: new Uint8Array(3 * n), body: new Float32Array(2 * n), ids: new Float64Array(n),
    depth: new Float32Array(n), vz: new Float32Array(n), worldEpoch: w.epoch, stats: [0, w.tick], pc: w.preds.length, preds: new Float32Array(3 * w.preds.length),
    predDepth: new Float32Array(w.preds.length), fc: 40, food: new Float32Array(80), foodDepth: new Float32Array(40), curActive: false };
  if (w.withApp) s.app = new Float32Array(63 * n);
  w.fish.forEach((f, i) => {
    for (let k = 0; k < 6; k++) { s.segs[12 * i + 2 * k] = f.x - 6 * k * Math.cos(f.a + 0.1 * k * Math.sin(w.tick * 0.1 + i)); s.segs[12 * i + 2 * k + 1] = f.y - 6 * k * Math.sin(f.a + 0.1 * k * Math.sin(w.tick * 0.1 + i)); }
    s.colors.set(f.c, 3 * i); s.body[2 * i] = f.sz; s.body[2 * i + 1] = f.el; s.ids[i] = f.id; s.depth[i] = f.d; s.vz[i] = 0.2 * Math.sin(w.tick * 0.05 + i);
    if (s.app) s.app.set(f.genes, 63 * i);
  });
  w.preds.forEach((p, i) => { s.preds[3 * i] = p.x; s.preds[3 * i + 1] = p.y; s.preds[3 * i + 2] = p.fed; s.predDepth[i] = p.d; });
  for (let i = 0; i < 40; i++) { s.food[2 * i] = (i * 37) % W; s.food[2 * i + 1] = (i * 53) % HH; s.foodDepth[i] = (i * 7) % D; }
  return s;
}

/* ---- the recording renderer ----
 * compileAsync: resolved at once, or (hold) left pending until released, as a driver's parallel compile may be; the
 * programs it would compile, and those a draw first uses, recorded by source. properties / getContext: what the binder's
 * compiler() reads (a linked program); expect(o, m): check 1, per drawn fish mesh */
function recorder(rec, expect) {
  const seenProg = new Set(), versions = new WeakMap(), labels = new WeakMap();
  let frame = null;
  const MAXTEX = 0x0D33, LINK = 0x8B82;
  const TEXUNITS = 0x8872, VTEXUNITS = 0x8B4C;
  const gl = { MAX_TEXTURE_SIZE: MAXTEX, MAX_TEXTURE_IMAGE_UNITS: TEXUNITS, MAX_VERTEX_TEXTURE_IMAGE_UNITS: VTEXUNITS, LINK_STATUS: LINK,
               getParameter: (p) => (p === MAXTEX ? 16384 : p === TEXUNITS || p === VTEXUNITS ? 16 : 0), getExtension: () => null, getSupportedExtensions: () => [],
               getContextAttributes: () => ({}), drawingBufferWidth: 1280, drawingBufferHeight: 720, isContextLost: () => !!rec.lost,
               getProgramParameter: (p, k) => (k === LINK ? !!(p && p.linked) : null) };
  function progOf(m) { return H(m.vertexShader) + "/" + H(m.fragmentShader); }
  function compileMat(m, why) { const p = progOf(m); if (!seenProg.has(p)) { seenProg.add(p); (frame ? frame.programs : rec.early).push(why + ":" + p); } }
  function ser(v) {
    if (v === null || v === undefined) return String(v);
    if (typeof v === "number" || typeof v === "boolean") return v;
    if (v.isTexture) return "tex:" + (v.image ? v.image.width + "x" + v.image.height : "?") + ":v" + v.version;
    if (v.isVector2) return [v.x, v.y]; if (v.isVector3) return [v.x, v.y, v.z];
    if (ArrayBuffer.isView(v)) return "arr" + v.length + ":" + H(Buffer.from(v.buffer, v.byteOffset, v.byteLength));
    return "obj";
  }
  /* the GPU's copy of a data texture, as the uploads three performed leave it: the named update ranges (floats), or the whole image */
  const gpuTex = new WeakMap();
  function model(t) {
    const d = t.image && t.image.data;
    if (!d || !d.length) return;
    let g = gpuTex.get(t);
    if (!g || g.length !== d.length) { g = new Float32Array(d.length); gpuTex.set(t, g); }
    const rr = t.updateRanges || [];
    if (!rr.length) g.set(d); else for (const r of rr) g.set(d.subarray(r.start, r.start + r.count), r.start);
  }
  function upload(obj, name, a) {
    if (!a) return;
    const was = versions.get(a);
    if (was === a.version) return;
    versions.set(a, a.version);
    frame.uploads.push([obj, name, a.count, a.itemSize, JSON.stringify(a.updateRanges || [])]);
    if (a.clearUpdateRanges) a.clearUpdateRanges();
  }
  function renderer() {
    return {
      toneMapping: 0, info: { render: { calls: 0, triangles: 0, points: 0, lines: 0 }, programs: [] }, debug: { checkShaderErrors: true, onShaderError: null },
      /* (rec.failCached: the decoded programs fail to link, as a driver's compile error would: the binder must keep the raw ones) */
      properties: { get: (m) => ({ currentProgram: { program: { linked: !(rec.failCached && m && typeof m.vertexShader === "string" && m.vertexShader.indexOf("Morph M = mLoad(") >= 0) }, getUniforms() {}, diagnostics: null } }) },
      getContext: () => gl, setClearColor() {}, setPixelRatio(p) { this.pr = p; }, getPixelRatio() { return this.pr || 1; }, setSize() {}, resetState() {},
      /* three's initTexture: the texture uploaded now if its version moved (the decoded programs sample no raw genes, so the scene uploads
       * the textures itself); only the optimized session calls it */
      initTexture(t) {
        if (versions.get(t) === t.version) return;
        versions.set(t, t.version);
        frame.uploads.push(["init", "tex", ser(t), JSON.stringify(t.updateRanges || [])]);
        model(t);
        if (t.onUpdate) t.onUpdate(t);
        if (t.clearUpdateRanges) t.clearUpdateRanges();
      },
      compile(scene) { scene.children.forEach((o) => o.material && compileMat(o.material, "warm")); return new Set(); },
      compileAsync(scene, cam, target) {
        this.compile(scene, cam, target);
        const c = { frame: frame ? frame.n : -1, n: scene.children.length, done: false, resolve: null };
        rec.compiles.push(c);
        if (!rec.hold) { c.done = true; return Promise.resolve(scene); }
        return new Promise((res) => { c.resolve = () => { c.done = true; c.doneFrame = rec.frameNow(); res(scene); }; });
      },
      render(scene, camera) {
        scene.updateMatrixWorld(); if (camera.parent === null) camera.updateMatrixWorld();
        const P = camera.projectionMatrix.elements, V = camera.matrixWorldInverse.elements;
        const M = new Array(16).fill(0);
        for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) M[j * 4 + i] += P[k * 4 + i] * V[j * 4 + k];
        const items = [];
        scene.children.forEach((o, idx) => {
          if (!o.visible || !o.material || o.material.visible === false) return;
          /* three's sort depth (projectObject): the geometry's bounding-sphere centre, through matrixWorld, then the
           * projection-screen matrix (applyMatrix4: divided by w) */
          const g = o.geometry;
          if (g.boundingSphere === null) g.computeBoundingSphere();
          const c = g.boundingSphere.center, e = o.matrixWorld.elements;
          const w0 = e[3] * c.x + e[7] * c.y + e[11] * c.z + e[15];
          const x = (e[0] * c.x + e[4] * c.y + e[8] * c.z + e[12]) / w0, y = (e[1] * c.x + e[5] * c.y + e[9] * c.z + e[13]) / w0, z = (e[2] * c.x + e[6] * c.y + e[10] * c.z + e[14]) / w0;
          const wv = M[3] * x + M[7] * y + M[11] * z + M[15], zz = (M[2] * x + M[6] * y + M[10] * z + M[14]) / wv;
          items.push({ o, idx, z: zz });
        });
        const op = items.filter((t) => !t.o.material.transparent), tr = items.filter((t) => t.o.material.transparent);
        op.sort((a, b) => a.o.renderOrder - b.o.renderOrder || a.o.material.id - b.o.material.id || a.z - b.z || a.o.id - b.o.id);
        tr.sort((a, b) => a.o.renderOrder - b.o.renderOrder || b.z - a.z || a.o.id - b.o.id);
        let calls = 0, tris = 0;
        for (const t of op.concat(tr)) {
          const o = t.o, m = o.material, g = o.geometry, label = (labels.get(o) || "?") + "#" + t.idx;
          compileMat(m, "draw");
          const inst = g.isInstancedBufferGeometry ? g.instanceCount : 1, range = g.drawRange ? [g.drawRange.start, g.drawRange.count] : null;
          if (inst === 0) continue;
          calls++;
          if (g.index) tris += g.index.count / 3 * inst;
          if (expect) expect(o, m, label);
          /* the optimized session only: three calls a mesh's onBeforeRender just before its draw (the per-draw ring uniforms are set
           * there); the reference session's recording does not, and keeps its committed digest */
          if (rec.callBefore && o.onBeforeRender) o.onBeforeRender(this, scene, camera, g, m, null);
          if (rec.callBefore && m.uniforms.uRingN) frame.rings.push([label, inst, m.uniforms.uRingN.value, m.uniforms.uHalfRing.value, Array.from(m.uniforms.uRingT.value).slice(0, m.uniforms.uRingN.value).join()]);
          const un = Object.keys(m.uniforms).sort();
          frame.draws.push([label, H(m.vertexShader), H(m.fragmentShader), m.transparent, m.depthWrite, m.depthFunc, m.side, m.blending, inst, range,
                            H(JSON.stringify(un.map((k) => [k, ser(m.uniforms[k].value)])))]);
          if (g.index) upload(label, "index", g.index);
          Object.keys(g.attributes).forEach((k) => upload(label, k, g.attributes[k]));
          /* the raw gene texture is an inactive uniform in the decoded programs (never fetched): three would not upload it at the draw */
          const decodedProg = m.vertexShader.indexOf("Morph M = mLoad(") >= 0;
          un.forEach((k) => { const v = m.uniforms[k].value; if (v && v.isTexture && !(decodedProg && k === "uGenes") && versions.get(v) !== v.version) {
            versions.set(v, v.version); frame.uploads.push([label, "tex " + k, ser(v), JSON.stringify(v.updateRanges || [])]);
            model(v);
            if (v.onUpdate) v.onUpdate(v); if (v.clearUpdateRanges) v.clearUpdateRanges(); } });
        }
        this.info.render.calls = calls; this.info.render.triangles = tris;
      }
    };
  }
  return { renderer, begin(f) { frame = f; }, label(o, l) { labels.set(o, l); }, gpuOf: (t) => gpuTex.get(t) };
}

/* ---- one side: the page's scripts in a vm context, the scene, a session ---- */
async function side(web, tag, opts) {
  opts = opts || {};
  const THREE0 = await import(pathToFileURL(path.resolve(web, "vendor/three.bundle.min.js")).href + "?side=" + tag);
  let now = 1000, seq = 0, fr = 0;
  const rec = { early: [], compiles: [], hold: false, lost: false, frameNow: () => fr };
  /* check 1: the drawn programs of every fish mesh against the variant it was last bound to (kind, pass, the variant
   * drawn: bind's result, 0 on a fallback to the plain programs) */
  const binds = new WeakMap(), bad = [];
  let checked = 0, ctx = null;
  const want = {};
  function programsOf(kind, pass, v) {
    /* the appearance fish's programs under the render features in effect (the decoded constants), else the raw ones */
    const rf = kind === "app" && binder && binder.render ? binder.render() : null, cached = !!(rf && rf.ids.length && rf.applies);
    const k = kind + "|" + pass + "|" + v + "|" + cached;
    if (!want[k]) {
      const SH = ctx.EvoOceanShaders, EA = ctx.EvoAppearance, app = (P) => SH.appearanceShaders(EA, P, cached ? rf.ids : []);
      want[k] = kind === "app"
        ? (pass === "body" ? [app(v === 1).vs, app(v === 1).fs] : pass === "shadow" ? [app(v === 1).shadowVs, SH.SHADOW_FS] : [SH.litSkip(app(false).vs), app(false).fs])
        : (pass === "body" ? [SH.FISH_VS[v], SH.FISH_FS[v]] : [SH.SHADOW_VS[v], SH.SHADOW_FS]);
    }
    return want[k];
  }
  function expect(o, m, label) {
    const b = binds.get(o);
    if (!b) return;
    checked++;
    const pass = b.pass === "litSkip" && b.eff !== b.variant ? "body" : b.pass, w = programsOf(b.kind, pass, b.eff);
    if (m.vertexShader !== w[0] || m.fragmentShader !== w[1]) bad.push({ frame: fr, label, bound: b, drew: [H(m.vertexShader), H(m.fragmentShader)], want: [H(w[0]), H(w[1])] });
  }
  const R = recorder(rec, expect);
  const THREE = Object.assign({}, THREE0, { WebGLRenderer: function () { return R.renderer(); } });
  const timers = [], logs = [];
  ctx = vm.createContext({
    console: { log() {}, info() {}, warn: (...a) => logs.push("warn " + a.map(String).join(" ").slice(0, 300)), error: (...a) => logs.push("error " + a.map(String).join(" ").slice(0, 300)) },
    performance: { now: () => now }, setTimeout: (f, ms) => { timers.push({ f, at: now + (ms || 0), s: ++seq }); return seq; }, clearTimeout() {},
    devicePixelRatio: 1, Promise, Math, JSON, Float32Array, Float64Array, Int32Array, Uint8Array, Uint32Array, Array, Object, WeakMap, Map, Set, Error, TypeError, String, Number, isFinite, Infinity, NaN
  });
  ctx.window = ctx; ctx.globalThis = ctx; ctx.__THREE = THREE;
  ctx.document = { addEventListener() {}, removeEventListener() {}, body: {} };   /* (ocean_appearance_slots.js registers on a page: root.document) */
  for (const f of SCRIPTS) {
    let src = fs.readFileSync(path.join(web, f), "utf8");
    for (const [ef, a, b] of (opts.edits || [])) {   /* planted faults in any page script: each anchor occurs exactly once */
      if (ef !== f) continue;
      if (src.split(a).length !== 2) throw new Error("planted fault: its anchor is not once in " + f + ": " + a.slice(0, 60));
      src = src.replace(a, b);
    }
    if (f === "ocean_scene.js") {
      const a0 = "var THREE = null;";
      if (src.split(a0).length !== 2) throw new Error("hook: var THREE");
      src = src.replace(a0, "var THREE = window.__THREE;");
      if (opts.mutant === "lateApp") {   /* the appearance kind binds the variant a frame late */
        const a = 'binder.bind(self.mesh, "app", split ? "litSkip" : "body", split ? 0 : w);';
        if (src.split(a).length !== 2) throw new Error("mutant lateApp: anchor");
        src = src.replace(a, 'binder.bind(self.mesh, "app", self.lastSplit ? "litSkip" : "body", self.lastSplit ? 0 : (self.lastW || 0)); self.lastSplit = split; self.lastW = w;');
      }
      if (opts.mutant === "lateFish") {   /* the legacy kinds bind the variant a frame late */
        const a = 'binder.bind(self.mesh, name, "body", v ? 1 : 0);';
        if (src.split(a).length !== 2) throw new Error("mutant lateFish: anchor");
        src = src.replace(a, 'binder.bind(self.mesh, name, "body", self.lastV ? 1 : 0); self.lastV = v;');
      }
      if (opts.mutant === "strayWrite") {   /* a writer of .material besides the binder: the legacy bodies drawn plain while bound full */
        const a = 'binder.bind(self.mesh, name, "body", v ? 1 : 0);';
        if (src.split(a).length !== 2) throw new Error("mutant strayWrite: anchor");
        src = src.replace(a, a + ' if (v) self.mesh["mate" + "rial"] = binder.material(name, "body", 0);');
      }
      if (MUTANTS[opts.mutant]) {
        const [a, b] = MUTANTS[opts.mutant];
        if (src.split(a).length !== 2) throw new Error("mutant " + opts.mutant + ": its anchor is not in this web/");
        src = src.replace(a, b);
      }
    }
    vm.runInContext(src, ctx, { filename: tag + "/" + f });
  }
  /* the binder the scene makes: its bind() seen (check 1), and the binder itself (the activation of check 4) */
  const MAT = ctx.EvoOceanMaterials, create0 = MAT.create;
  let binder = null;
  MAT.create = function (deps) {
    binder = create0(deps);
    const bind0 = binder.bind;
    binder.bind = function (mesh, kind, pass, variant) { const eff = bind0.apply(this, arguments); binds.set(mesh, { kind, pass, variant, eff }); return eff; };
    return binder;
  };
  const S0 = ctx.EvoOceanScene;
  const doc = { addEventListener() {}, removeEventListener() {}, body: {} };
  const listeners = {};
  const canvas = { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); }, removeEventListener() {}, style: {}, ownerDocument: doc, getRootNode: () => doc,
                   clientWidth: 1280, clientHeight: 720, setPointerCapture() {}, releasePointerCapture() {},
                   getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 720, right: 1280, bottom: 720 }) };
  const fire = (t) => { if (t === "webglcontextlost") rec.lost = true; if (t === "webglcontextrestored") rec.lost = false; (listeners[t] || []).forEach((f) => f({ type: t, preventDefault() {} })); };
  const counts = {};
  const K = new Proxy({}, { get: (t, p) => p });
  const profiler = { active: true, SPAN: K, K, beginCpu: () => 0, lap: () => 0, endCpu() {}, count(k, v) { counts[k] = v; }, add(k, v) { counts["+" + k] = (counts["+" + k] || 0) + v; },
                     markDiagnostic() {}, attachGL() {}, watch: (o, l) => R.label(o, l), beginSubmission() {}, endSubmission() {}, suspend: (f) => f() };
  /* the recording is of the reference pipeline (renderOptimization: false: main's draws, byte for byte); the render
   * optimization has its own session below (opts.optimized), checked by assertions, never by a new recorded hash */
  const scene = S0.create(canvas, { profiler, visualRandom: rng(99), tankDepth: D, renderOptimization: opts.optimized ? undefined : false });
  if (!scene) throw new Error(tag + ": no scene");
  scene.setWorld(W, HH, D, { walls: false });
  const frames = [];
  const settleAll = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
  async function runTimers() {
    for (;;) {   /* the due timers, in order (the prewarm's, the caustics') */
      timers.sort((a, b) => a.at - b.at || a.s - b.s);
      if (!timers.length || timers[0].at > now) break;
      timers.shift().f();
    }
    await settleAll();
  }
  async function frame(w, sel) {
    const f = { n: fr, draws: [], uploads: [], programs: [] };
    if (rec.callBefore) f.rings = [];
    R.begin(f);
    for (const k of Object.keys(counts)) delete counts[k];
    scene.render(snap(w), { animT: fr * 0.016, selIdx: sel === undefined ? -1 : sel, dtSim: 0.032 });
    const st = scene.polish();
    f.counts = Object.assign({}, counts);
    f.polish = [st.variant, st.hold, st.posing, st.ready, st.split, st.litDrawn, st.any, st.full, st.preds.variant, st.preds.lit, st.preds.hold];
    frames.push(f);
    now += 16; fr++; step(w);
    await runTimers();
    return f;
  }
  const close = (w, i) => { const f = w.fish[i]; scene.lookFrom([f.x - W / 2 + 60, -f.d + 25, f.y - HH / 2 + 60], [f.x - W / 2, -f.d, f.y - HH / 2]); };
  const closeP = (w, i) => { const p = w.preds[i]; scene.lookFrom([p.x - W / 2 + 70, -p.d + 30, p.y - HH / 2 + 70], [p.x - W / 2, -p.d, p.y - HH / 2]); };
  const out = { frames, early: rec.early, logs, bad, binds: () => checked };
  if (opts.session === "policy") {
    /* the render optimization's policy API (scene.setRenderOptimization / renderOptimization): validation, refusal, the lock */
    const s0 = scene.renderOptimization();
    const refused = await scene.setRenderOptimization({ lod: "nonsense" });
    const refusedD = await scene.setRenderOptimization({ decoded: "yes" });
    const refusedB = await scene.setRenderOptimization({ barbels: 7 });
    const after = scene.renderOptimization();
    const refOk = await scene.setRenderOptimization({ lod: "quality", decoded: false, barbels: "body" });
    Object.assign(out, { s0, refused, refusedD, refusedB, after, refOk, final: scene.renderOptimization() });
    return out;
  }
  if (opts.session === "buckets") {
    /* the optimized body draws (policy lod: screen / medium / coarse) through the real scene: after each scripted state, the last
     * frame's batches and draws against the canonical staging and the snapshot (every fish in exactly one body draw, the fish's own
     * 21 floats in the batch, the shadow draw whole and in snapshot order, each draw's ring uniforms its own template's) */
    rec.callBefore = true;
    const app = World(300, 0, true, 1), N = 300, rep = [];
    const EA = ctx.EvoAppearance, ringStr = (lod) => Array.from(new Float32Array(EA.buildTemplate(lod).ringT)).join();
    const RING = { coarse: [EA.buildTemplate("coarse").ringT.length, ringStr("coarse")], medium: [EA.buildTemplate("medium").ringT.length, ringStr("medium")] };
    function inspect(tag, o) {
      o = o || {};
      const f = frames[frames.length - 1], st = scene.renderOptimization(), b = st.batches, q = scene.quality(), P = [];
      const res = { tag, quality: q, eff: st.effective, buckets: st.buckets, problems: P, rings: f.rings };
      const by = {};
      f.rings.forEach((r) => { (by[r[0].split("#")[0]] = by[r[0].split("#")[0]] || []).push(r); });
      const canonSlots = scene.geneSlots();
      if (!canonSlots || canonSlots.length !== N || canonSlots.some((s, i) => s !== i)) P.push("the canonical gene slots are not the snapshot's (identity): " + String(canonSlots && canonSlots.slice(0, 5)));
      const shadow = (by.fishShadow || []).map((r) => [r[1], r[2], r[4]].join("|")).join(";"), wantTpl = q >= 3 ? "medium" : "coarse";
      if (shadow !== [N, RING[wantTpl][0], RING[wantTpl][1]].join("|")) P.push("the shadow draw is not one draw of every fish on the " + wantTpl + " template's rings: " + shadow);
      if (!st.buckets) {   /* the canonical body draw: one draw of every fish (and the barbels) on the quality's template */
        /* one draw of every fish on the quality's template (with the lit split on, also the lit fish's own draw, on the same rings) */
        const bodies = (by.fishBody || []).map((r) => [r[1], r[2], r[4]].join("|"));
        if (bodies.indexOf([N, RING[wantTpl][0], RING[wantTpl][1]].join("|")) < 0 || (bodies.length > 1 && !o.split)) P.push("the canonical body draw: " + bodies.join(";"));
        res.barbels = (by.barbels || []).reduce((s, r) => s + r[1], 0);
        if (o.gated) {   /* the gated barbel draw under the canonical body draw: medium rings, its own instance count */
          if ((by.barbels || []).some((r) => r[2] !== RING.medium[0] || r[4] !== RING.medium[1])) P.push("a barbel draw is not on the medium template's rings");
          if (res.barbels !== st.barbels) P.push("the barbel draws hold " + res.barbels + " instances, the scene says " + st.barbels);
        }
        return res;
      }
      const seen = new Uint8Array(N), nb = { coarse: b.coarse.n, medium: b.medium.n };
      if (nb.coarse + nb.medium !== N) P.push("the buckets hold " + (nb.coarse + nb.medium) + " fish, not " + N);
      for (const k of ["coarse", "medium"]) {
        const B = b[k];
        for (let j = 0; j < B.n; j++) {
          const c = B.drawIdx[j];
          if (seen[c]) P.push("fish " + c + " is in two buckets"); seen[c] = 1;
          if (j && B.drawIdx[j - 1] >= c) P.push(k + " bucket is not in snapshot order at " + j);
          for (const a of ["iA", "iB", "iC", "iBody", "iX"]) for (let t = 0; t < 4; t++) if (B.attrs[a].array[4 * j + t] !== b.canon[a].array[4 * c + t]) P.push(k + "[" + j + "]." + a + "[" + t + "] differs from fish " + c);
          if (B.attrs.iGeneSlot.array[j] !== b.canon.iGeneSlot.array[c]) P.push(k + "[" + j + "] has the wrong gene slot");
        }
      }
      if (seen.some((x) => !x)) P.push("a fish is in no bucket");
      const bodies = (by.fishBody || []).map((r) => [r[1], r[2], r[4]].join("|")).sort().join(";");
      const want = ["coarse", "medium"].filter((k) => nb[k] > 0).map((k) => [nb[k], RING[k][0], RING[k][1]].join("|")).sort().join(";");
      if (bodies !== want) P.push("the body draws " + bodies + " are not the buckets' " + want);
      const barbs = (by.barbels || []).map((r) => [r[1], r[2], r[4]].join("|")).join(";");
      const wantB = st.buckets.barbels > 0 ? [st.buckets.barbels, RING.medium[0], RING.medium[1]].join("|") : "";
      if (barbs !== wantB) P.push("the barbel draw " + barbs + " is not " + wantB);
      res.nb = nb; res.medium = Array.from(b.medium.drawIdx); res.barbels = st.buckets.barbels;
      if (process.env.MOCK_DEBUG) {
        const pc = scene.poseCamera(), G = { view: pc.view, focal: pc.focalCss, near: pc.near, halfW: pc.halfW, halfH: pc.halfH }, pxs = [];
        for (let i = 0; i < N; i++) { const p = scene.poseOf(i), xs = [], ys = []; for (let k = 0; k < 6; k++) { xs.push(p.spine[2 * k]); ys.push(p.spine[2 * k + 1]); } pxs.push(S0.posePx(xs, ys, p.R, p.y, G)); }
        pxs.sort((a, b) => a - b);
        console.log("    [debug] " + tag + ": focal " + pc.focalCss.toFixed(1) + ", px min " + pxs[0].toFixed(2) + " median " + pxs[150].toFixed(2) + " max " + pxs[299].toFixed(2) + "; " + pxs.filter((x) => x >= 7).length + " >= 7");
      }
      return res;
    }
    const run = async (tag, k, w, sel, camera, o) => { for (let i = 0; i < k; i++) { if (camera) camera(); await frame(w, sel); } const r = inspect(tag, o); rep.push(r); return r; };
    scene.setAppearance(true);
    await scene.setRenderOptimization({ lod: "screen", decoded: false, barbels: "body" });   /* (the barbels' gate has its own states, below) */
    await run("whole, screen, q3", 4, app);
    await run("close to fish 5, screen, q3", 6, app, 5, () => close(app, 5));
    scene.resetView(false);
    await scene.setRenderOptimization({ lod: "quality" });
    await run("whole, quality (canonical)", 3, app);
    await scene.setRenderOptimization({ lod: "medium" });
    await run("forced medium", 3, app);
    await scene.setRenderOptimization({ lod: "coarse" });
    await run("forced coarse", 3, app);
    await scene.setRenderOptimization({ lod: "screen" });
    scene.setQuality(2);
    await run("close, screen, q2 (all coarse)", 4, app, 5, () => close(app, 5));
    scene.setQuality(3);
    scene.resetView(false);
    await run("whole, fish 7 selected (pinned medium)", 4, app, 7);
    scene.setLitSplit(true);
    await run("lit split on: the reference draws", 4, app, 5, () => close(app, 5), { split: true });
    scene.setLitSplit(false);
    await run("lit split off again: buckets", 4, app, 5, () => close(app, 5));
    await scene.setRenderOptimization({ barbels: "off" });
    await run("barbels off", 4, app, 5, () => close(app, 5));
    await scene.setRenderOptimization({ lod: "quality", barbels: "off" });
    await run("barbels off, quality", 3, app, 5, () => close(app, 5));
    /* the barbels' gate: only fish that have barbels (gene above float32 0.2), in the medium template, big enough on screen */
    const gated = [], POSEAPI = S0, fi = app.fish.findIndex((f, i) => i >= 5 && Math.fround(f.genes[59]) > 0.2);
    function gatedCheck(tag) {
      const st = scene.renderOptimization(), b = st.batches, q = scene.quality(), pc = scene.poseCamera();
      const G = { view: pc.view, focal: pc.focalCss, near: pc.near, halfW: pc.halfW, halfH: pc.halfH };
      const med = st.buckets ? new Set(b.medium.drawIdx) : null, enter = new Set(), keep = new Set(), P = [];
      for (let c = 0; c < N; c++) {
        const inMed = q >= 3 && (med ? med.has(c) : true), bD = Math.fround(app.fish[c].genes[59]);
        if (!inMed || !(bD > Math.fround(0.2))) continue;
        const p = scene.poseOf(c), xs = [], ys = [];
        for (let k = 0; k < 6; k++) { xs.push(p.spine[2 * k]); ys.push(p.spine[2 * k + 1]); }
        const px = POSEAPI.posePx(xs, ys, p.R, p.y, G);
        if (px >= 6) enter.add(c);
        if (px > 4.5) keep.add(c);
      }
      const got = new Set(b && b.barbels ? Array.from(b.barbels.drawIdx) : []), n = b && b.barbels ? b.barbels.n : 0;
      for (const c of enter) if (!got.has(c)) P.push("fish " + c + " (barbels, 6 px or more, medium) has no barbel strips");
      for (const c of got) if (!keep.has(c)) P.push("fish " + c + " has barbel strips but is not eligible (gene, template or under 4.5 px)");
      if (n !== got.size) P.push("the barbel draw's count " + n + " is not its fish list's " + got.size);
      gated.push({ tag, enter: enter.size, keep: keep.size, got: got.size, problems: P, quality: q, own: scene.renderOptimization().barbels });
    }
    await scene.setRenderOptimization({ lod: "screen", barbels: "gated" });
    await run("gated barbels, screen LOD, close to a fish with barbels", 6, app, fi, () => close(app, fi));
    gatedCheck("gated, screen LOD, close");
    await scene.setRenderOptimization({ lod: "quality" });
    await run("gated barbels, quality LOD, close", 6, app, fi, () => close(app, fi), { gated: true });
    gatedCheck("gated, quality LOD, close");
    scene.resetView(false);
    await run("gated barbels, whole tank", 4, app, undefined, undefined, { gated: true });
    gatedCheck("gated, whole tank");
    scene.setQuality(2);
    await scene.setRenderOptimization({ lod: "screen" });
    await run("gated barbels, q2", 4, app, fi, () => close(app, fi));
    gatedCheck("gated, q2");
    scene.setQuality(3);
    Object.assign(out, { rep, gated, fi, logs: logs.slice() });
    return out;
  }
  if (opts.session === "decoded") {
    /* the decoded constants' cache (policy decoded) through the real scene: its programs compiled before they take effect, the
     * cache made once at each fish's birth and kept in step through deaths, slot reuse, growth, a new epoch, the policy off and on, a
     * lost context, a Look that does not declare the contract, and a planted compile failure; after each state, the GPU's copy of
     * both gene textures (as the uploads three performed leave it) against a fresh decode of every owner's raw row */
    rec.callBefore = true;
    const EA = ctx.EvoAppearance, SH = ctx.EvoOceanShaders, w0 = World(300, 0, true, 1), checks2 = [];
    const decoded = () => scene.renderOptimization().decoded;
    const eff = () => scene.renderOptimization().effective;
    let nextId = 100000;
    const born = (k, seed) => { const W2 = World(k, 0, true, 1); return W2.fish.map((f, i) => Object.assign(f, { id: nextId++ })); };
    /* the owners' decoded floats (CPU and GPU model) against writeDecoded of their raw rows; the raw texture's GPU copy against its rows */
    function check(tag, o) {
      o = o || {};
      const g = scene.geneTexture(), d = decoded(), slots = scene.geneSlots(), P = [], tmp = new Float32Array(EA.DECODED_FLOATS);
      const gpuD = d && d.texture ? R.gpuOf(d.texture) : null, gpuR = R.gpuOf(g.texture);
      let owners = 0;
      for (const s of slots) {
        owners++;
        EA.writeDecoded(g.data.subarray(64 * s, 64 * s + 63), tmp, 0);
        for (let j = 0; j < EA.DECODED_FLOATS; j++) {
          if (!Object.is(tmp[j], d.data[EA.DECODED_FLOATS * s + j])) { P.push("cpu slot " + s + " float " + j); break; }
          if (o.gpu !== false && (!gpuD || !Object.is(tmp[j], gpuD[EA.DECODED_FLOATS * s + j]))) { P.push("gpu slot " + s + " float " + j); break; }
        }
        for (let j = 0; j < 63; j++) if (!gpuR || !Object.is(g.data[64 * s + j], gpuR[64 * s + j])) { P.push("raw gpu slot " + s + " gene " + j); break; }
        if (P.length > 4) break;
      }
      const r = { tag, owners, problems: P, eff: Object.assign({}, eff()), stats: { uploads: d.uploads, calls: d.calls, bytes: d.bytes, allocs: d.allocs, fullUploads: d.fullUploads, decodes: d.decodes, capacity: d.capacity } };
      checks2.push(r);
      return r;
    }
    const go = async (k, w, sel) => { for (let i = 0; i < k; i++) await frame(w, sel); };
    scene.setAppearance(true);
    await go(2, w0);
    const early = { eff: Object.assign({}, eff()), decoded: decoded() };
    await go(4, w0);
    check("compiled and in effect, the first fish decoded and uploaded whole");
    const base = decoded();
    await go(10, w0);
    const steady = decoded(); checks2.push({ tag: "steady frames", problems: steady.uploads === base.uploads && steady.decodes === base.decodes ? [] : ["uploads/decodes moved on unchanged frames"] });
    /* births and deaths: ten fish gone, twenty born (their slots: the lowest free ones first) */
    w0.fish.splice(5, 10); w0.fish.push(...born(20));
    await go(1, w0); const afterBirth = check("ten die, twenty are born: only their slots decoded and uploaded");
    checks2.push({ tag: "births: decoded once each, in ranges (no whole upload)", problems: decoded().decodes === base.decodes + 20 && decoded().fullUploads === base.fullUploads && afterBirth.stats.calls - base.calls <= 3 ? [] : ["decodes " + (decoded().decodes - base.decodes) + ", whole " + (decoded().fullUploads - base.fullUploads) + ", calls " + (afterBirth.stats.calls - base.calls)] });
    await go(3, w0);
    check("a few frames later");
    /* growth past 256 owners: new storage, a whole upload of both */
    const cap0 = decoded().capacity;
    w0.fish.push(...born(300));
    await go(2, w0); const grown = check("growth to " + w0.fish.length + " fish: both textures whole on new storage");
    checks2.push({ tag: "growth: the decoded storage grew with the slots", problems: grown.stats.capacity > cap0 && grown.stats.allocs >= 2 ? [] : ["capacity " + cap0 + " -> " + grown.stats.capacity + ", allocs " + grown.stats.allocs] });
    /* a new epoch with the same ids: every owner installed again, decoded again */
    const dBefore = decoded().decodes;
    w0.epoch = 2; await go(2, w0); const ep = check("a new world (epoch 2, the same ids)");
    checks2.push({ tag: "a new epoch decodes every fish again", problems: decoded().decodes - dBefore === w0.fish.length ? [] : ["decoded " + (decoded().decodes - dBefore) + " of " + w0.fish.length] });
    /* the policy off: the raw programs, births while off, then on again (a stale copy: whole upload) */
    const off = await scene.setRenderOptimization({ decoded: false });
    await go(3, w0);
    const offState = { ok: off.ok, eff: Object.assign({}, eff()) };
    w0.fish.splice(0, 12); w0.fish.push(...born(15));
    await go(3, w0);
    const on = await scene.setRenderOptimization({ decoded: true });
    await go(3, w0);
    check("off (births while off), then on again");
    checks2.push({ tag: "the policy off: the raw programs (effective.decoded false), then back on", problems: off.ok && offState.eff.decoded === false && on.ok && eff().decoded === true ? [] : ["off " + JSON.stringify(offState) + ", on " + JSON.stringify(on)] });
    /* a lost context and its restore: both textures uploaded whole again */
    const fullsBefore = decoded().fullUploads;
    fire("webglcontextlost"); await go(2, w0); fire("webglcontextrestored"); await go(3, w0);
    check("after a lost and restored context");
    checks2.push({ tag: "a restored context: the decoded texture uploaded whole again", problems: decoded().fullUploads > fullsBefore ? [] : ["no whole upload after the restore"] });
    /* a Look that did not declare the contract: raw programs; no Look: decoded again */
    const lk = await scene.setFeatures({ look: "mock2", features: (q) => q.base });
    await go(3, w0);
    const underLook = { ok: lk.ok, eff: Object.assign({}, eff()) };
    const lk2 = await scene.setFeatures(null);
    await go(3, w0);
    checks2.push({ tag: "a Look without appearanceCache keeps the raw programs; none again: decoded", problems: lk.ok && underLook.eff.decoded === false && lk2.ok && eff().decoded === true ? [] : ["under the Look " + JSON.stringify(underLook) + ", after " + JSON.stringify(eff())] });
    check("after the Look");
    /* a planted compile failure: the raw programs stay, said once, the failure kept */
    await scene.setRenderOptimization({ decoded: false });
    rec.failCached = true; logs.length = 0;
    const bad = await scene.setRenderOptimization({ decoded: true });
    await go(3, w0);
    const failed = { ok: bad.ok, error: bad.error, eff: Object.assign({}, eff()), failures: scene.renderOptimization().failures.slice(), logs: logs.slice() };
    rec.failCached = false;
    const retry = await scene.setRenderOptimization({ decoded: true });
    await go(3, w0);
    checks2.push({ tag: "a compile that fails: the raw programs stay, the failure is kept and said once; the next try works", problems:
      !failed.ok && failed.eff.decoded === false && failed.failures.length === 1 && /^decoded: /.test(failed.failures[0]) && failed.logs.length === 1 && /decoded appearance constants could not be used/.test(failed.logs[0]) && retry.ok && eff().decoded === true
        ? [] : [JSON.stringify(failed), JSON.stringify(retry.ok)] });
    check("after the retry");
    /* the decoded programs really drew (a frame's body draw with the decoded vertex stage), and the raw ones before and between */
    const dvs = H(SH.appearanceShaders(EA, false, [SH.DECODED]).vs), dvsP = H(SH.appearanceShaders(EA, true, [SH.DECODED]).vs), rvs = H(SH.appearanceShaders(EA, false).vs);
    const drew = (h) => frames.filter((f) => f.draws.some((d) => d[1] === h)).length;
    Object.assign(out, { checks2, early, drewDecoded: drew(dvs) + drew(dvsP), drewRaw: drew(rvs) });
    return out;
  }
  if (opts.session === "contextLoss") {
    /* check 4: the legacy fish close up (lit) with every compile held: the prewarm asks, and is pending; the context is lost
     * (frames go on: the page skips drawing), 6 s pass (main's prewarm marked itself ready at 5 s, compiled or not), the
     * context comes back, then the compile from before the loss finishes. A feature set's activation is overtaken alike */
    const legacy = World(250, 8, false, 2), seen = [];
    const variantNow = () => scene.polish().variant;
    rec.hold = true;
    for (let i = 0; i < 3; i++) { close(legacy, 3); await frame(legacy, 3); }
    const asked = rec.compiles.length;
    /* (first, a prewarm still compiling after 6 s: the plain programs, not the full ones compiled at the draw) */
    now += 6000; await runTimers();
    const slow = [];
    for (let i = 0; i < 2; i++) { close(legacy, 3); const f = await frame(legacy, 3); slow.push({ frame: f.n, variant: variantNow() }); }
    MAT.compiler && ctx.EvoOceanShaders.feature({ id: "mock.look", abi: ctx.EvoOceanShaders.ABI, targets: ["fish.fs"], append: { "fish.emissive": "  murky += vec3(0.0);" } });
    const act = scene.setFeatures ? scene.setFeatures({ look: "mock", features: (q) => (q.stage === "fs" && q.pass === "body" ? q.base.concat(["mock.look"]) : q.base) }) : null;
    await settleAll();
    const heldBefore = rec.compiles.filter((c) => !c.done);
    fire("webglcontextlost");
    for (let i = 0; i < 4; i++) { close(legacy, 3); await frame(legacy, 3); }
    now += 6000; await runTimers();
    fire("webglcontextrestored");
    const restoredAt = fr, nBefore = rec.compiles.length;
    heldBefore.forEach((c) => c.resolve());   /* the compiles from before the loss finish now (three polled its old programs) */
    await settleAll();
    const actResult = act ? await act : null;
    for (let i = 0; i < 8; i++) { close(legacy, 3); const f = await frame(legacy, 3); seen.push({ frame: f.n, variant: variantNow(), compilesDone: rec.compiles.slice(nBefore).filter((c) => c.done).length }); }
    rec.compiles.slice(nBefore).forEach((c) => { if (!c.done) c.resolve(); });   /* the restored context's own prewarm finishes */
    await settleAll();
    for (let i = 0; i < 4; i++) { close(legacy, 3); const f = await frame(legacy, 3); seen.push({ frame: f.n, variant: variantNow(), compilesDone: rec.compiles.slice(nBefore).filter((c) => c.done).length }); }
    Object.assign(out, { asked, slow, heldBefore: heldBefore.length, restoredAt, seen, actResult, after: rec.compiles.slice(nBefore).length, look: scene.materials ? scene.materials().look : null });
    return out;
  }
  if (opts.session === "staleReady") {
    /* check 4 (the review of #59, P2-1): the prewarm FINISHES, the legacy fish drawn full; then the context is lost and
     * restored with every compile held: until a compile in the restored context finished, plain and not ready */
    const legacy = World(250, 8, false, 2), seen = [], st = () => scene.polish();
    for (let i = 0; i < 6; i++) { close(legacy, 3); await frame(legacy, 3); }
    const before = { variant: st().variant, ready: st().ready };
    rec.hold = true;
    fire("webglcontextlost");
    for (let i = 0; i < 2; i++) { close(legacy, 3); await frame(legacy, 3); }
    fire("webglcontextrestored");
    const n0 = rec.compiles.length;
    const look = (f) => ({ frame: f.n, variant: st().variant, ready: st().ready, done: rec.compiles.slice(n0).filter((c) => c.done).length });
    for (let i = 0; i < 6; i++) { close(legacy, 3); seen.push(look(await frame(legacy, 3))); }
    rec.compiles.slice(n0).forEach((c) => { if (!c.done) c.resolve(); });   /* the restored context's prewarm finishes */
    await settleAll();
    for (let i = 0; i < 3; i++) { close(legacy, 3); seen.push(look(await frame(legacy, 3))); }
    Object.assign(out, { before, seen, asked: rec.compiles.length - n0 });
    return out;
  }
  if (opts.session === "timeout") {
    /* check 4 (the review of #59, P3-1): the prewarm's compile does not finish in its budget (60 s): plain, said once, and a
     * later frame asks again; once the driver is done, that compile finishes and the polish comes on */
    const legacy = World(250, 8, false, 2), seen = [], st = () => scene.polish();
    rec.hold = true;
    for (let i = 0; i < 3; i++) { close(legacy, 3); await frame(legacy, 3); }
    const n1 = rec.compiles.length;
    now += 61000; await runTimers();   /* the budget runs out */
    for (let i = 0; i < 3; i++) { close(legacy, 3); const f = await frame(legacy, 3); seen.push({ frame: f.n, variant: st().variant, asked: rec.compiles.length }); }
    const n2 = rec.compiles.length;
    rec.compiles.forEach((c) => { if (!c.done) c.resolve(); });   /* the driver finishes */
    await settleAll();
    for (let i = 0; i < 3; i++) { close(legacy, 3); const f = await frame(legacy, 3); seen.push({ frame: f.n, variant: st().variant, asked: rec.compiles.length }); }
    Object.assign(out, { n1, n2, seen });
    return out;
  }
  const app = World(300, 6, true, 1), legacy = World(250, 8, false, 2);
  for (let i = 0; i < 30; i++) await frame(app);                                   /* whole tank: plain */
  for (let i = 0; i < 60; i++) { close(app, 5); await frame(app, 5); }           /* close: lit, the full programs once warm */
  scene.resetView(false);
  for (let i = 0; i < 45; i++) await frame(app);                                   /* the hold, then plain */
  scene.setLitSplit(true);
  for (let i = 0; i < 40; i++) { close(app, 9); await frame(app, 9); }           /* the split: lit fish apart, the main draw with the skip */
  scene.resetView(false);
  for (let i = 0; i < 40; i++) await frame(app);
  scene.setLitSplit(false);
  close(app, 12); scene.setPolish(false);
  for (let i = 0; i < 15; i++) { close(app, 12); await frame(app); }             /* the polish off: plain */
  scene.setPolish(true);
  for (let i = 0; i < 20; i++) { close(app, 12); await frame(app); }
  scene.setQuality(1);
  for (let i = 0; i < 15; i++) { close(app, 12); await frame(app); }             /* detail 1: plain, coarse */
  scene.setQuality(3); scene.setAppearance(true);
  for (let i = 0; i < 20; i++) { close(app, 12); await frame(app); }             /* the genes' skin */
  scene.setAppearance(false);
  for (let i = 0; i < 25; i++) { close(legacy, 3); await frame(legacy, 3); }     /* legacy fish, close: their full programs */
  for (let i = 0; i < 35; i++) { closeP(legacy, 1); await frame(legacy); }       /* predators close */
  scene.resetView(false);
  for (let i = 0; i < 40; i++) await frame(legacy);
  for (let i = 0; i < 30; i++) { close(app, 20); await frame(app, 20); }         /* back to the appearance fish */
  scene.setInsets({ left: 420, right: 0, top: 0, bottom: 160 });                  /* a panel's inset: the view offset moves P8, P9 */
  for (let i = 0; i < 20; i++) { close(app, 5); await frame(app, 5); }
  scene.setInsets({ left: 0, right: 380, top: 120, bottom: 0 });
  for (let i = 0; i < 20; i++) { close(app, 5); await frame(app, 5); }
  scene.setInsets({});
  for (let i = 0; i < 10; i++) { close(app, 5); await frame(app, 5); }
  out.final = scene.polish();
  out.materials = scene.materials ? scene.materials() : null;
  return out;
}
const digest = (fr) => H(fr.map((f) => JSON.stringify(f)).join("\n"));
function states(frames) {
  const v = {};
  frames.forEach((f) => { const k = "app/legacy " + f.polish[0] + (f.polish[4] ? "+split" : "") + ", preds " + f.polish[8]; v[k] = (v[k] || 0) + 1; });
  return v;
}

console.log("== the session on " + WEB);
const A = await side(WEB, "web");
const sa = digest(A.frames);
const draws = A.frames.reduce((n, f) => n + f.draws.length, 0), ups = A.frames.reduce((n, f) => n + f.uploads.length, 0);
const progs = A.early.length + A.frames.reduce((n, f) => n + f.programs.length, 0);
console.log("  " + A.frames.length + " frames, " + draws + " draws, " + ups + " uploads, " + progs + " programs (first use or compile); states " + JSON.stringify(states(A.frames)));
ok(A.bad.length === 0 && A.binds() > 0, "1. every frame, every fish mesh drew the programs of the variant it was last bound to (" + A.binds() + " fish draws)", A.bad.slice(0, 3));
ok(A.logs.length === 0, "  and the console said nothing", A.logs.slice(0, 3));
ok(sa === GOLDEN, "2. the recording (every draw, upload, program, counter and polish() state of " + A.frames.length + " frames): sha256 " + sa + (sa === GOLDEN ? "" : " (committed " + GOLDEN + ")"));
for (const m of ["lateApp", "lateFish"]) {
  const B = await side(WEB, "mut-" + m, { mutant: m });
  const fa = A.frames.map((f) => JSON.stringify(f)), fb = B.frames.map((f) => JSON.stringify(f));
  const n = fa.filter((x, i) => x !== fb[i]).length;
  ok(n > 0, "3. planted: the " + (m === "lateApp" ? "appearance kind" : "legacy kinds") + " binding the variant a frame late: " + n + " frames differ from the recording");
}
{
  const B = await side(WEB, "mut-stray", { mutant: "strayWrite" });
  ok(B.bad.length > 0, "   planted: a second writer of the legacy bodies' material (plain while bound full): check 1 sees it in " + new Set(B.bad.map((x) => x.frame)).size + " frames", B.bad.slice(0, 1));
}
/* a planted revert of this tree's fix: run it, or say its anchor is not here (another web/, say main's) */
async function planted(mutant, session) {
  try { return await side(WEB, "mut-" + mutant, { mutant, session }); } catch (e) { return { error: String(e && e.message || e) }; }
}
{
  const B = await planted("planesOnce");
  const fa = A.frames.map((f) => JSON.stringify(f)), n = B.error ? 0 : fa.filter((x, i) => x !== JSON.stringify(B.frames[i])).length;
  ok(n > 0, "   planted: the side planes never recomputed (the review of #59, P3-3): " + (B.error || n + " frames differ from the recording (the inset steps)"));
}
console.log("== the render optimization's policy (scene.setRenderOptimization)");
{
  const lockedS = await side(WEB, "policyRef", { session: "policy" });                       /* the reference scene: renderOptimization: false */
  const P = await side(WEB, "policy", { session: "policy", optimized: true });
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  ok(lockedS.s0.enabled === false && same(lockedS.s0.effective, { lod: "quality", decoded: false, barbels: "body" }) && lockedS.refOk.ok === false && /renderOptimization: false/.test(lockedS.refOk.error),
     "renderOptimization: false: the reference pipeline, its policy locked (setRenderOptimization refuses)", { s0: lockedS.s0, refOk: lockedS.refOk });
  ok(P.s0.enabled === true && P.refused.ok === false && P.refusedD.ok === false && P.refusedB.ok === false && same(P.after.requested, P.s0.requested) && same(P.after.effective, P.s0.effective),
     "a bad policy value is refused, naming it, and changes nothing", { refused: P.refused.error, refusedD: P.refusedD.error, refusedB: P.refusedB.error });
  ok(P.refOk.ok === true && same(P.refOk.effective, { lod: "quality", decoded: false, barbels: "body" }) && P.final.failures.length === 0, "the reference policy can always be set", P.refOk);
}
console.log("== the optimized body draws (policy lod) through the real scene");
{
  const B = await side(WEB, "buckets", { session: "buckets", optimized: true });
  const rep = B.rep, by = (t) => rep.find((r) => r.tag === t) || { problems: ["no such state " + t] };
  ok(rep.length >= 10 && rep.every((r) => r.problems.length === 0), "every scripted state: every fish in exactly one body draw (snapshot order within it), the batch holds the fish's own 21 floats, the shadow is one whole draw, every draw's rings are its template's (" + rep.length + " states)", rep.filter((r) => r.problems.length).map((r) => [r.tag, r.problems.slice(0, 3)]));
  ok(B.bad.length === 0 && B.binds() > 0, "  every bucket mesh drew the programs of the variant it was bound (" + B.binds() + " fish draws)", B.bad.slice(0, 2));
  ok(B.logs.length === 0, "  and the console said nothing", B.logs.slice(0, 3));
  const w = by("whole, screen, q3"), c = by("close to fish 5, screen, q3");
  ok(w.buckets && w.buckets.medium === 0 && w.buckets.coarse === 300 && w.buckets.barbels === 0, "a whole-tank view: every fish coarse, no barbel draw (no medium fish)", w.buckets);
  ok(c.buckets && c.medium.indexOf(5) >= 0 && c.buckets.medium >= 1 && c.buckets.medium < 150 && c.buckets.coarse + c.buckets.medium === 300 && c.buckets.barbels === c.buckets.medium,
     "close to one fish: it is medium, most of the tank coarse (" + (c.buckets && c.buckets.medium) + " medium); barbel strips for the medium fish (reference policy)", c.buckets);
  ok(by("whole, quality (canonical)").buckets === null && by("whole, quality (canonical)").barbels === 300, "lod \"quality\": the canonical body and barbel draws of every fish, as the reference draws them", by("whole, quality (canonical)").barbels);
  const fm = by("forced medium"), fc = by("forced coarse");
  ok(fm.buckets && fm.buckets.medium === 300 && fm.buckets.coarse === 0 && fm.buckets.barbels === 300, "lod \"medium\": every fish in the medium bucket (and its barbels)", fm.buckets);
  ok(fc.buckets && fc.buckets.coarse === 300 && fc.buckets.medium === 0 && fc.buckets.barbels === 0, "lod \"coarse\": every fish in the coarse bucket, no barbels", fc.buckets);
  const q2 = by("close, screen, q2 (all coarse)");
  ok(q2.buckets && q2.buckets.medium === 0 && q2.buckets.coarse === 300, "detail 2 close to a fish: every body coarse (the screen LOD never raises detail past the setting)", q2.buckets);
  const pin = by("whole, fish 7 selected (pinned medium)");
  ok(pin.buckets && pin.medium.join() === "7", "a selected fish is medium wherever it is (pinned), the rest of the whole view coarse", pin.medium);
  ok(by("lit split on: the reference draws").buckets === null && by("lit split off again: buckets").buckets !== null, "the lit split is drawn by the reference pipeline: no buckets while it is on, buckets again once off");
  ok(by("barbels off").buckets && by("barbels off").buckets.barbels === 0 && by("barbels off, quality").barbels === 0, "barbels \"off\": no barbel draw, under buckets or the canonical draws");
  const g = (t) => B.gated.find((x) => x.tag === t) || { problems: ["no such state " + t] };
  ok(B.gated.length === 4 && B.gated.every((x) => x.problems.length === 0), "gated barbels: every fish with barbels (gene above float32 0.2), in the medium template and 6 px or more across has strips; none that is not eligible (4.5 px to keep them)", B.gated.filter((x) => x.problems.length).map((x) => [x.tag, x.problems.slice(0, 2)]));
  ok(g("gated, screen LOD, close").enter >= 1 && g("gated, screen LOD, close").got >= 1 && g("gated, screen LOD, close").got < by("gated barbels, screen LOD, close to a fish with barbels").buckets.medium,
     "close to a fish with barbels: its strips are drawn, and fewer than the body bucket has fish (the reference draws the strips of every fish of the draw)", g("gated, screen LOD, close"));
  ok(g("gated, quality LOD, close").got >= 1 && g("gated, quality LOD, close").own === g("gated, quality LOD, close").got, "gated under the canonical body draw (lod \"quality\"): the barbel draw is compacted too", g("gated, quality LOD, close"));
  ok(g("gated, whole tank").got === 0 && g("gated, q2").got === 0, "a whole-tank view (every fish a few pixels): no barbel strip at all; detail 2: none", [g("gated, whole tank").got, g("gated, q2").got]);
  /* planted faults: each must be seen */
  const BF = {
    "every bucket on the medium template's rings": ["ocean_scene.js", "bindRings(S.mesh, function () { return S.rings; });", "bindRings(S.mesh, function () { return ringsOfLod.medium; });"],
    "the shadow left on the last body draw's rings (no per-mesh rings)": ["ocean_scene.js", "if (renderOn) { bindRings(self.mesh, canonRings); bindRings(self.shadow, canonRings); }", "if (renderOn) { bindRings(self.mesh, canonRings); }"],
    "the barbels' gene threshold too low (a fish without barbels gets strips)": ["ocean_pose.js", "var BARBEL_GENE_MIN = Math.fround(0.2),", "var BARBEL_GENE_MIN = 0.1,"],
    "the barbel gate ignoring the size": ["ocean_pose.js", "return previous ? px > BARBEL_EXIT_CSS : px >= BARBEL_ENTER_CSS;", "return true;"],
    "a fish dropped from its bucket": ["ocean_scene.js", "for (c = 0; c < n; c++) { if (lodOf[c] === LOD_MEDIUM) M.idx[jm++] = c; else C.idx[jc++] = c; }", "for (c = 0; c < n; c++) { if (lodOf[c] === LOD_MEDIUM) M.idx[jm++] = c; else if (c !== 7) C.idx[jc++] = c; }"],
    "a bucket's gene slot off by one for a fish": ["ocean_scene.js", "dS[j] = sS[c];", "dS[j] = c === 3 ? j + 1 : sS[c];"]
  };
  for (const k of Object.keys(BF)) {
    let M;
    try { M = await side(WEB, "bk-fault", { session: "buckets", optimized: true, edits: [BF[k]] }); } catch (e) { M = { error: String(e && e.message || e) }; }
    const seen = !M.error && (M.rep.some((r) => r.problems.length > 0) || M.gated.some((r) => r.problems.length > 0));
    ok(seen, "planted: " + k + ": the session sees it" + (M.error ? " (" + M.error + ")" : ""), M.rep && M.rep.concat(M.gated).filter((r) => r.problems.length).slice(0, 1).map((r) => [r.tag, r.problems.slice(0, 2)]));
  }
}
console.log("== the decoded constants' cache (policy decoded) through the real scene");
{
  const D = await side(WEB, "decoded", { session: "decoded", optimized: true });
  ok(D.checks2.length >= 14 && D.checks2.every((c) => c.problems.length === 0), "every state: the cache decoded once per birth and kept through deaths, slot reuse, growth, a new epoch, the policy off and on, a restored context and a Look; both textures' GPU copies equal a fresh decode / the raw rows (" + D.checks2.length + " states)",
     D.checks2.filter((c) => c.problems.length).map((c) => [c.tag, c.problems.slice(0, 3)]));
  ok(D.checks2[0].eff.decoded === true && D.drewDecoded > 20 && D.drewRaw > 0, "its programs compiled first, then drew (" + D.drewDecoded + " frames of decoded body draws; the raw programs " + D.drewRaw + " frames: before it, while off, under the Look, after the failure)");
  ok(D.bad.length === 0 && D.binds() > 0, "  every fish mesh drew the programs of its variant, decoded or raw as the binder had them in effect (" + D.binds() + " fish draws)", D.bad.slice(0, 2));
  ok(D.logs.length === 1 && /decoded appearance constants could not be used/.test(D.logs[0]), "  the console said only the planted failure, once", D.logs.slice(0, 3));
  /* planted faults: each must be seen by the session's checks */
  const FAULTS = {
    "a slot never decoded (its owner's constants stale)": ["ocean_scene.js", "if (dec.live) decodeSlot(s, data, off); }", "if (dec.live && s % 5 !== 3) decodeSlot(s, data, off); }"],
    "the decoded upload's ranges shifted a slot": ["ocean_scene.js", "dt.addUpdateRange(dr.start / 64 * EA.DECODED_FLOATS, dr.count / 64 * EA.DECODED_FLOATS);", "dt.addUpdateRange(dr.start / 64 * EA.DECODED_FLOATS + 72, dr.count / 64 * EA.DECODED_FLOATS);"],
    "a decoded upload never queued": ["ocean_scene.js", "dt.needsUpdate = true; dec.queued = true;", "dt.needsUpdate = false; dec.queued = true;"],
    "a released slot's owner left in the cache after a new epoch": ["ocean_scene.js", "onReset: function () { lodSt.fill(0); barbSt.fill(0); },", "onReset: function () { lodSt.fill(0); barbSt.fill(0); dec.live = false; },"],
    "the decoded cache not grown with the slots": ["ocean_scene.js", "if (dec.live) growDec(cap); },", "},"]
  };
  for (const k of Object.keys(FAULTS)) {
    let M;
    try { M = await side(WEB, "dec-fault", { session: "decoded", optimized: true, edits: [FAULTS[k]] }); } catch (e) { M = { error: String(e && e.message || e) }; }
    ok(!M.error && M.checks2.some((c) => c.problems.length > 0), "planted: " + k + ": the session sees it" + (M.error ? " (" + M.error + ")" : ""),
       M.checks2 && M.checks2.filter((c) => c.problems.length).slice(0, 1).map((c) => [c.tag, c.problems.slice(0, 2)]));
  }
}
console.log("== a WebGL context loss during the prewarm (#50's review, P2)");
{
  const C = await side(WEB, "ctx", { session: "contextLoss" });
  const early = C.seen.filter((x) => x.compilesDone === 0 && x.variant === "full");
  ok(C.slow.every((x) => x.variant === "plain"), "a prewarm still compiling after 6 s: the plain programs drawn (not the full ones, compiled at the draw: a stalled frame)", C.slow);
  ok(C.heldBefore >= 1 && C.asked >= 1, "the prewarm had asked before the loss, and its compile was pending (" + C.heldBefore + " held)", { asked: C.asked, held: C.heldBefore });
  ok(early.length === 0, "  after the restore, no frame drew the legacy fish's polished programs before a compile in the restored context finished (a lit fish in view)", C.seen);
  ok(C.after >= 1 && C.seen[C.seen.length - 1].variant === "full", "  the restored context's own prewarm asked, and once it finished the polish came back", { after: C.after, last: C.seen[C.seen.length - 1] });
  ok(!C.actResult || (C.actResult.ok === false && C.look === ""), "  a feature set's activation the loss overtook: refused, no Look in effect", { act: C.actResult, look: C.look });
}
console.log("== the prewarm finished, then a loss and a restore (the review of #59, P2-1)");
{
  const staleOk = (S) => S.before.variant === "full" && S.before.ready === true && S.seen.some((x) => x.done === 0) &&
                         S.seen.filter((x) => x.done === 0).every((x) => x.variant === "plain" && x.ready === false);
  const S = await side(WEB, "stale", { session: "staleReady" });
  ok(S.before.variant === "full" && S.before.ready === true, "before the loss: compiled ahead, the full programs drawn", S.before);
  ok(staleOk(S), "  after the restore: the plain programs, and not ready, until the restored context's own compile finished (" + S.seen.filter((x) => x.done === 0).length + " frames)", S.seen);
  ok(S.asked >= 1 && S.seen[S.seen.length - 1].variant === "full" && S.seen[S.seen.length - 1].ready === true, "  the restored context's prewarm asked; full and ready once it finished", { asked: S.asked, last: S.seen[S.seen.length - 1] });
  const M = await planted("readyOutlives", "staleReady");
  ok(!M.error && !staleOk(M), "  planted: main's readiness (outliving the restore) is seen: " + (M.error || JSON.stringify(M.seen && M.seen[0])));
}
console.log("== a prewarm past its budget (the review of #59, P3-1)");
{
  const timeoutOk = (T) => T.seen.slice(0, 3).every((x) => x.variant === "plain") && T.n2 > T.n1 && T.seen[T.seen.length - 1].variant === "full";
  const T = await side(WEB, "timeout", { session: "timeout" });
  ok(timeoutOk(T) && T.logs.length === 1 && /did not finish in 60 s.*drawn plain until they are/.test(T.logs[0]),
     "the budget ran out: plain, said once, asked again by a later frame (" + T.n1 + " -> " + T.n2 + " compiles); full once the driver finished", { seen: T.seen, logs: T.logs });
  const M = await planted("noRetry", "timeout");
  ok(!M.error && !timeoutOk(M), "  planted: never asked again is seen: " + (M.error || JSON.stringify(M.seen && M.seen[M.seen.length - 1])));
}
console.log("== the diagnostics bound first (web/ocean_scene_parity.js; step 3's review)");
{
  /* the module without the scene: nothing bound its gene layout and water constants */
  const c = vm.createContext({ console: { log() {}, info() {}, warn() {}, error() {} }, Promise, Math, JSON, Float32Array, Float64Array, Int32Array, Uint8Array, Uint32Array,
                               Array, Object, WeakMap, Map, Set, Error, TypeError, String, Number, isFinite, Infinity, NaN });
  c.window = c; c.globalThis = c;
  for (const f of ["ocean_appearance.js", "ocean_shaders.js", "ocean_pose.js", "ocean_scene_parity.js"]) vm.runInContext(fs.readFileSync(path.join(WEB, f), "utf8"), c, { filename: "parity/" + f });
  const P = c.EvoOceanSceneParity, EA = c.EvoAppearance, said = [];
  const run = async (what, f) => { try { const r = await f(); said.push([what, r && r.error ? "error: " + r.error : JSON.stringify(r).slice(0, 80)]); return r; } catch (e) { said.push([what, "threw: " + e.message]); return null; } };
  const rv = await run("vertex", () => P.appearanceVertexCheck(null, EA, [], [], {}));
  const rf = await run("fragment", () => P.appearanceFragmentCheck(null, EA, {}));
  const rp = await run("path", () => P.appearancePathCheck(null, EA));
  const at = await run("attach", () => P.attach({}));
  const bd = await run("bind", () => P.bind({ GENES_W: 512 }));
  const bo = await run("bind2", () => P.bind({ GENES_W: 512, genesRows() { return 1; }, packGenes() {}, capFor() { return 32; } }));
  const unbound = (r) => !!r && /bind\(\) has not run/.test(r.error || "") && r.ok !== true;
  ok(unbound(rv) && unbound(rf) && unbound(rp) && at === null && /attach/.test(said[3][0]) && /bind\(\) has not run/.test(said[3][1]) && bd === null && /genesRows \(a function\) is missing/.test(said[4][1]) &&
     bo === null && /CLARITY \(an object\) is missing/.test(said[5][1]),
     "before bind(): each check's report says it could not run (never a pass), attach() refuses, and a bind() short of a member names it", said);
}
if (AGAINST) {
  console.log("== against " + AGAINST);
  const O = await side(AGAINST, "old");
  const fa = O.frames.map((f) => JSON.stringify(f)), fb = A.frames.map((f) => JSON.stringify(f));
  let differ = 0, first = -1;
  for (let i = 0; i < Math.max(fa.length, fb.length); i++) if (fa[i] !== fb[i]) { differ++; if (first < 0) first = i; }
  console.log("  old: " + digest(O.frames) + ", states " + JSON.stringify(states(O.frames)) + "; logs " + JSON.stringify(O.logs));
  if (differ) {
    const a = O.frames[first], b = A.frames[first];
    const where = ["draws", "uploads", "programs", "counts", "polish"].filter((k) => JSON.stringify(a && a[k]) !== JSON.stringify(b && b[k]));
    console.log("  DIFFER: " + differ + " frames, the first " + first + " (" + where.join(", ") + ")");
    for (const k of where) console.log("    " + k + "\n      old " + JSON.stringify(a && a[k]).slice(0, 700) + "\n      new " + JSON.stringify(b && b[k]).slice(0, 700));
    const list = []; for (let i = 0; i < fa.length; i++) if (fa[i] !== fb[i]) list.push(i);
    console.log("  differing frames: " + list.join(","));
  }
  ok(differ === 0, "the session frame by frame against " + AGAINST + ": " + (differ ? differ + " frames differ" : "the same " + fa.length + " frames"));
  if (OUTF) fs.writeFileSync(OUTF, JSON.stringify({ old: O.frames, new: A.frames }));
}
console.log((fails ? "FAIL" : "ok") + ": " + (checks - fails) + "/" + checks + " checks");
process.exit(fails ? 1 : 0);
