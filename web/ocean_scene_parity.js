// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the scene's diagnostics (window.EvoOceanSceneParity).
 *
 * The appearance fish's GPU == CPU checks, each against the CPU mirror of
 * web/ocean_appearance.js (EvoAppearance), each a Promise of a report whose
 * read-back waits on a fence, polled (fenceDone), so it never stalls the
 * pipeline; a report with .error did not run, and is never a pass. On any
 * WebGL2 context (no three needed; the scene exports them):
 * appearancePathCheck, the production programs on a fixed fixture
 * (pathFixture): their vertex stage by transform feedback
 * (appearanceVertexCheck, in both colour modes, plain, full and lite, and on
 * permuted and sparse gene slots; against the CPU mirror of the vertex
 * stage, compareTemplate, appWorldCPU and co.; the reach, reachCheck; the
 * non-finite sweep, injectSweep) and their fragment stage on known inputs
 * (appearanceFragmentCheck). Planted faults (plant: PATH_MUT, FRAG_MUT) must
 * fail them.
 *
 * On a live scene (attach(port), once a scene: web/ocean_scene.js create()):
 * appearanceParity, the pattern law alone on the scene's context, and
 * appearanceTextureParity, the live gene texture as three uploaded it, read
 * right after a production draw of the appearance fish (textureProbe; its
 * queue, runProbes and failProbes, the scene's render() drives); testFaults
 * (holdGeneUploads, which the scene's gene upload reads). The probe uploads
 * nothing: one that did fails.
 *
 * What they take: the appearance fish's programs, the gene slot and the
 * strings' helpers from web/ocean_shaders.js, the swim pose and the reach
 * from web/ocean_pose.js (both loaded first), under the names they had in
 * the scene; and from the scene, once, as it loads (bind), the gene
 * texture's layout as the renderer lays it out (GENES_W, genesRows,
 * packGenes; capFor, its capacities) and the water's constants the fragment
 * check sets (CLARITY's realistic column, C.select). Those are
 * production's, so they stay there. On a live scene, its renderer and what
 * it drew, through attach's port.
 *
 * Moved from web/ocean_scene.js unchanged (the structure pass's third
 * extraction: renderer_seams_plan_codex.md, "extract diagnostics as a pure
 * move"; module ocean_scene_parity.js). WebGL only through the context a
 * caller hands in. Display only: the simulation never reads any of it. */
(function (root) {
  root.EvoOceanSceneParity = null;   /* registered at the end: a throw on the way leaves null (the scene: "failed to run") */
  var SHADERS = root.EvoOceanShaders, POSE = root.EvoOceanPose;
  if (!SHADERS || !POSE) return;   /* (the scene names the file missing, or failed to run, not this one) */
  var lines = SHADERS.lines, occurrences = SHADERS.occurrences;
  /** @type {(EA: EvoAppearanceApi, P?: any, more?: string[]) => AppearancePrograms} (P: false, true or "lite", read off opts; more: feature ids) */
  var appearanceShaders = SHADERS.appearanceShaders;
  var DECODED = SHADERS.DECODED;   /* the render optimization's decoded constants (feature id) */
  var GENE_SLOT_GLSL = SHADERS.GENE_SLOT_GLSL, GENE_SLOT_RET = SHADERS.GENE_SLOT_RET;
  var packPose = POSE.packPose, unpackPose = POSE.unpackPose, smoothCPU = POSE.smoothCPU;
  /** @type {(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, y: number, v: number, G: any) => number} (G: {gate: false}, ungated) */
  var swimPose = POSE.swimPose;
  var reachRadius = POSE.reachRadius, REACH_APP = POSE.REACH_APP;

  /* The scene's own (bind(scene), once, as web/ocean_scene.js loads): the
   * gene texture's layout as the renderer lays it out (GENES_W, genesRows,
   * packGenes) and its capacities (capFor), for the fixture's texture; the
   * water's constants the fragment check sets (CLARITY's realistic [0]
   * column, C.select). A check run before bind has no layout: its report
   * says so (UNBOUND), as a check that could not run (.error, never a pass);
   * and bind names a member the scene left out, rather than a check failing
   * on it later */
  var BOUND = false;
  var UNBOUND = "EvoOceanSceneParity.bind() has not run: the checks need the scene's gene texture layout and water constants (web/ocean_scene.js binds them as it loads)";
  /** @type {number} */
  var GENES_W;
  /** @type {ParityScene["genesRows"]} */
  var genesRows;
  /** @type {ParityScene["packGenes"]} */
  var packGenes;
  /** @type {ParityScene["capFor"]} */
  var capFor;
  /** @type {ParityScene["CLARITY"]} */
  var CLARITY;
  /** @type {ParityScene["C"]} */
  var C;
  /** @param {ParityScene} scene */
  function bind(scene) {
    [["GENES_W", "number"], ["genesRows", "function"], ["packGenes", "function"], ["capFor", "function"], ["CLARITY", "object"], ["C", "object"]].forEach(function (m) {
      var v = scene ? /** @type {any} */ (scene)[m[0]] : undefined;
      if (typeof v !== m[1] || v === null) throw new Error("EvoOceanSceneParity.bind(): the scene's " + m[0] + " (" + (m[1] === "object" ? "an " : "a ") + m[1] + ") is missing");
    });
    GENES_W = scene.GENES_W; genesRows = scene.genesRows; packGenes = scene.packGenes; capFor = scene.capFor;
    CLARITY = scene.CLARITY; C = scene.C;
    BOUND = true;
  }

  /* The appearance checks: three layers, each against the CPU mirror
   * (web/ocean_appearance.js), each a Promise of a report whose read-back
   * waits on a fence, polled (at most 10 s), so it never stalls the pipeline.
   * A report with .error did not run (a missing extension, a compile error,
   * a timeout): that is never a pass, and never a planted fault caught.
   *   appearanceParity (in create): pattern law 3 alone, the pattern genes
   *     fed as attributes (the gallery's K12 reference); no gene texture.
   *   appearancePathCheck: a fixed 65-fish fixture (pathFixture: it crosses
   *     the texture's 32-fish rows twice, every fish distinct, all with
   *     barbels; the caller's rows, if any, are added) through the production
   *     programs, on a texture packed and laid out as the renderer packs it:
   *     the fish's vertex shader in both colour modes by transform feedback
   *     (appearanceVertexCheck: appearance, and recolour, whose nonzero packed
   *     colours must reach vPart.w), and its fragment shader on known inputs
   *     (appearanceFragmentCheck: the recolour path, Family's and Brain's
   *     palettes, and the skin).
   *   appearanceTextureParity (in create): the live gene texture itself, as
   *     three uploaded it, read through the same slot selector right after a
   *     production draw: its raw genes bit for bit, and the pattern charts.
   * They share what the fish reads (GENE_SLOT_GLSL, DECODE_CALL, GENES), the
   * WebGL2 prefixes (VS3, FS3) and the fence polling (fenceDone). */
  var VS3 = "#version 300 es\n#define attribute in\n#define varying out\nprecision highp float;\nprecision highp int;\n" +
            "uniform mat4 projectionMatrix;\nuniform mat4 viewMatrix;\nuniform vec3 cameraPosition;\n";
  var FS3 = "#version 300 es\n#define varying in\nprecision highp float;\nprecision highp int;\nuniform vec3 cameraPosition;\n" +
            "out highp vec4 pcFrag;\n#define gl_FragColor pcFrag\n";
  function compileProgram(gl, vs, fs, feedback) {
    function compile(type, src) {
      var o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
      if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) { var log = gl.getShaderInfoLog(o); gl.deleteShader(o); throw new Error("compile: " + log); }
      return o;
    }
    var prog = gl.createProgram(), a = compile(gl.VERTEX_SHADER, vs), b;
    try { b = compile(gl.FRAGMENT_SHADER, fs); } catch (e) { gl.deleteShader(a); gl.deleteProgram(prog); throw e; }
    gl.attachShader(prog, a); gl.attachShader(prog, b);
    if (feedback) gl.transformFeedbackVaryings(prog, feedback, gl.INTERLEAVED_ATTRIBS);
    gl.linkProgram(prog);
    gl.deleteShader(a); gl.deleteShader(b);   /* freed with the program */
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { var l = gl.getProgramInfoLog(prog); gl.deleteProgram(prog); throw new Error("link: " + l); }
    return prog;
  }
  /* resolves null once the GPU passed sync, else why not (lost, failed, 10 s) */
  function fenceDone(gl, sync, ms) {
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function poll() {
        if (gl.isContextLost && gl.isContextLost()) { resolve("the WebGL context was lost"); return; }
        var st = gl.clientWaitSync(sync, 0, 0);
        if (st === gl.TIMEOUT_EXPIRED && Date.now() - t0 < ms) { setTimeout(poll, 2); return; }
        resolve(st === gl.WAIT_FAILED || st === gl.TIMEOUT_EXPIRED ? "the GPU did not finish (" + st + ")" : null);
      })();
    });
  }
  /* a planted fault: its site must occur exactly once */
  function plant(src, name, table) {
    var m = table[name];
    if (!m) return { error: "unknown mutation " + name };
    if (occurrences(src, m[0]) !== 1) return { error: "mutation " + name + ": its site occurs " + occurrences(src, m[0]) + " times" };
    return { src: src.split(m[0]).join(m[1]) };
  }

  /* The fixed fixture of appearancePathCheck, whatever the caller's world:
   * 65 distinct fish (two texture-row crossings), every one with barbels */
  function pathFixture(EA) {
    var rows = [], lams = [];
    for (var c = 0; c < 65; c++) {
      var g = [];
      for (var j = 0; j < EA.STRIDE; j++) g.push(Math.fround(0.05 + 0.90 * ((37 * c + 17 * j + 13) % 251) / 250));
      g[EA.MO + 26] = Math.fround(0.75);
      rows.push(g); lams.push(Math.fround(3.5 + 0.05 * c));
    }
    return { rows: rows, lams: lams };
  }

  /* GPU == CPU through the production vertex path (appearanceVertexCheck).
   * appearanceParity feeds the pattern genes as attributes and checks the
   * skin only, so a wrong gene-texture row or slot would pass it. Here the
   * fish program's own vertex shader (appearanceShaders vs, with three's
   * WebGL2 prefix) runs on a gene texture packed and laid out as the
   * renderer packs it (packGenes, genesRows at the renderer's capacity), for
   * the medium and coarse bodies and the barbel strips (every part: body,
   * tail, dorsal, pectoral, eye, anal, pelvic fins, barbels). Transform
   * feedback reads back every vertex of every fish: its world position,
   * material site and fin margin, its part (all four vPart components: fin,
   * side, highlight, packed colour), and in appearance mode (opts.colourBy 0)
   * the pattern varyings it decoded from the texture; each is compared with
   * the CPU mirror (EvoAppearance morphDecode / morphBuild / patternVaryings,
   * appWorldCPU). Recolour mode (colourBy 1, Family / Brain) skips
   * patternDecode, so its pattern varyings are unwritten: they are neither
   * captured nor checked. Every captured component must be finite before any
   * arithmetic (a NaN fails no |a - b| > tol test, and min(x, 10) hides an
   * infinity); report.nan counts the vertices with any non-finite output.
   * opts.mutate plants a fault ("row0", "nextRow", "slot": the texture
   * lookup; "partW": vPart.w loses the packed colour; "drawIndex": the slot
   * selector back on gl_InstanceID, which only a nonidentity slot map
   * catches): the check must then fail.
   * opts.slotMap: the fish's gene slots (iGeneSlot), "identity" (the
   * default: slot = draw), "permuted" (a bijection of the draws) or "sparse"
   * (both sides of the texture rows' 31 / 32, 63 / 64 and 2047 / 2048, the
   * rest spread: a 4,096-slot texture); the genes are packed at their slots,
   * the expected rows stay in draw order. opts.injectSweep: after the run, NaN / +Inf / -Inf put into each
   * captured component in turn (of two fish of the medium body, one on the
   * second texture row) must each fail with that component named.
   * opts.polish: the polished program (POSE_GLSL) instead of the plain one,
   * animated (uWag 1, uTime .7: the tail beat and its lag, the barbels'
   * sway) inside glass walls (uWalls 1), every fish
   * with a packed swim pose in iBody.w (poseFixture: rolls of either sign
   * up to the clamp, folds, size weights 1, .6, .25 and 0, the plain pose),
   * and six more fish (POSE_SPECIAL) whose pose is swimPose's own: a straight spine nosing
   * into a pane (clamped), a collapsed spine (all six points one), sharp
   * turns both ways (the roll at its clamp, the fold eased), and genes all
   * 0 (zero-area fins) and all 1; the fold is mirrored by finPoseCPU. */
  var PATH_TOL = { world: 0.02, mat: 0.005, mar: 0.005, decode: 0.0005 };
  var TF_OUT = [["vWorld", 3], ["vMatV", 4], ["vPart", 4], ["vG0", 4], ["vG1", 4], ["vG2", 4], ["vG3", 4],
                ["vG4", 4], ["vG5", 4], ["vG6", 4], ["vG7", 4], ["vAux", 4], ["vMeta", 4]];
  var PATH_COLOURS = [0x123456, 0xe32791, 0x07c15a, 0x010203, 0xfedcba];
  var PATH_FETCH = "int li = 16 * inst + k;";
  var PATH_MUT = {
    row0: [PATH_FETCH, "int li = 16 * 0 + k;"],
    nextRow: [PATH_FETCH, "int li = 16 * (inst + 1) + k;"],
    slot: [PATH_FETCH, "int li = 16 * inst + (k ^ 1);"],
    partW: ["vPart = vec4(aPattern.x, aPattern.z, iBody.z, iX.w);", "vPart = vec4(aPattern.x, aPattern.z, iBody.z, 0.0);"],
    drawIndex: [GENE_SLOT_RET, "return gl_InstanceID;"]
  };
  /* planted faults in the decoded programs' reader (appearanceVertexCheck / appearanceFragmentCheck with opts.decoded): the texel index,
   * the row, a body-plan field */
  var DEC_MUT = {
    dtexel: ["ivec2(18 * (slot % 32) + k, slot / 32)", "ivec2(18 * (slot % 32) + (k ^ 1), slot / 32)"],
    drow: ["ivec2(18 * (slot % 32) + k, slot / 32)", "ivec2(18 * (slot % 32) + k, 0)"],
    dfield: ["  M.depth = d0.x;", "  M.depth = d0.y;"]
  };
  function gcd(a, b) { while (b) { var t = a % b; a = b; b = t; } return a; }
  /* the check's gene slots for n fish (opts.slotMap above) */
  function slotMap(kind, n) {
    var out = new Float32Array(n), c;
    if (kind === "permuted") {
      var m = [7, 11, 13, 17, 19, 23, 29, 31].filter(function (k) { return gcd(k, n) === 1; })[0] || 1;
      for (c = 0; c < n; c++) out[c] = (c * m + 3) % n;
    } else if (kind === "sparse") {
      var fixed = [2048, 31, 32, 2047, 63, 64, 0, 1], seen = {};
      for (c = 0; c < n; c++) { var sl = c < fixed.length ? fixed[c] : 100 + 29 * c; while (seen[sl]) sl++; seen[sl] = 1; out[c] = sl; }
    } else for (c = 0; c < n; c++) out[c] = c;
    return out;
  }
  var POSE_SPECIAL = ["straight, into a pane", "collapsed", "sharp left", "sharp right", "genes 0", "genes 1"];
  function poseFixture(c) {   /* packed (packPose) */
    var w = [1, 0.6, 0.25, 0][c % 4], bank = 0.6 * Math.sin(1.7 * c + 0.4);
    return packPose(Math.sin(bank), w * ((c * 0.29) % 1), w);
  }
  function componentNames(layout) {
    var out = [];
    layout.forEach(function (v) { for (var i = 0; i < v[1]; i++) out.push(v[0] + "." + "xyzw"[i]); });
    return out;
  }
  /** @returns {Promise<any>} */
  function appearanceVertexCheck(gl, EA, rows, lams, opts) {
    opts = opts || {};
    if (!BOUND) return Promise.resolve({ error: UNBOUND });
    if (!EA || !EA.morphBuild) return Promise.resolve({ error: "web/ocean_appearance.js (with its CPU mirror) not loaded" });
    var colourBy = opts.colourBy === 1 ? 1 : 0, P = opts.polish === "lite" ? "lite" : !!opts.polish;
    /* opts.decoded: the render optimization's decoded programs (render.decoded): the body plan from the decoded texture, not the raw genes.
     * They write no pattern varyings (the fragment stage loads the pattern's constants), so only the geometry, the material site and the
     * part are captured and compared (as in recolour mode: the body plan decoded on the GPU from the CPU's decode is tested through every
     * template vertex it places); the decoded texture's own texels, 18 a fish, are read back through the same slot selector and compared
     * with the CPU's decode (the pattern's constants through their texels, the layout, the upload and the sampling) */
    var D = !!opts.decoded;
    if (D && (!EA.writeDecoded || !DECODED)) return Promise.resolve({ error: "the decoded constants (EvoAppearance.writeDecoded) are not loaded" });
    var feedback = colourBy || D ? TF_OUT.slice(0, 3) : TF_OUT, names = componentNames(feedback);
    var vsrc = appearanceShaders(EA, P, D ? [DECODED] : []).vs;
    if (vsrc.indexOf(PATH_FETCH) < 0) return Promise.resolve({ error: "the gene fetch is not where the check expects it" });
    if (opts.mutate) {
      var pm = plant(vsrc, opts.mutate, D ? Object.assign({}, PATH_MUT, DEC_MUT) : PATH_MUT);
      if (pm.error) return Promise.resolve({ error: pm.error });
      vsrc = pm.src;
    }
    var fsrc = "#version 300 es\nprecision highp float;\nout vec4 pcOut;\nvoid main() { pcOut = vec4(0.0); }\n";
    var NC = names.length;
    if (gl.getParameter(gl.MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS) < NC) return Promise.resolve({ error: "transform feedback holds fewer than " + NC + " floats" });
    var prog;
    try { prog = compileProgram(gl, VS3 + vsrc, fsrc, feedback.map(function (v) { return v[0]; })); }
    catch (e) { return Promise.resolve({ error: e.message || String(e) }); }
    /* the decoded texels' reader: texel k (gl_VertexID, 0 .. 17) of the fish's slot (iGeneSlot), one vec4 a point, through the production
     * reader's own address (decodedTexel: here as its text, with the same mutation sites) */
    var dprog = null;
    if (D) {
      var rsrc = EA.GLSL.DECODED_READ;
      if (opts.mutate && DEC_MUT[opts.mutate]) { var rm = plant(rsrc, opts.mutate, DEC_MUT); if (!rm.error) rsrc = rm.src; }
      try {
        dprog = compileProgram(gl, VS3 + "attribute float iGeneSlot;\n" + rsrc + "\nvarying vec4 vT;\nvoid main() { vT = decodedTexel(int(iGeneSlot), gl_VertexID); gl_Position = vec4(0.0); }", fsrc, ["vT"]);
      } catch (e2) { gl.deleteProgram(prog); return Promise.resolve({ error: "the decoded texel reader: " + (e2.message || String(e2)) }); }
    }

    /* the fish: their genes in the renderer's texture, a bent spine each, a packed colour each */
    var nBase = rows.length;
    if (P) {   /* POSE_SPECIAL */
      var g0 = [], g1 = [];
      for (var j0 = 0; j0 < EA.STRIDE; j0++) { g0.push(0); g1.push(1); }
      rows = rows.concat([rows[0], rows[1], rows[2], rows[3], g0, g1]);
      lams = lams.concat([4, 4, 4, 4, 4, 4]);
    }
    var n = rows.length, ST = EA.STRIDE, slots = slotMap(opts.slotMap, n), top = 0;
    for (var c0 = 0; c0 < n; c0++) if (slots[c0] > top) top = slots[c0];
    var cap = capFor(top + 1), texRows = genesRows(cap);
    var T = new Float32Array(GENES_W * texRows * 4), R = new Float32Array(n * ST);
    for (var c = 0; c < n; c++) { for (var j = 0; j < ST; j++) R[c * ST + j] = rows[c][j]; packGenes(T, R, c * ST, slots[c], ST); }
    var U = { half: [960, 540], px: 500, cam: [120, 380, 900], colourBy: colourBy || (D ? 1 : 0),   /* (the decoded programs write no pattern: not compared) */
              polish: !!P, lite: P === "lite", time: P ? 0.7 : 0, wag: P ? 1 : 0, walls: !!P };
    var inst = { iA: new Float32Array(4 * n), iB: new Float32Array(4 * n), iC: new Float32Array(4 * n), iBody: new Float32Array(4 * n), iX: new Float32Array(4 * n),
                 iGeneSlot: slots };
    var poseG = { gate: false }, xs = [], ys = [];
    for (c = 0; c < n; c++) {
      var lam = Math.fround(lams[c]), Rb = Math.fround(4.6 * (0.8 + 0.4 * ((c * 0.37) % 1))), sp = lam * Rb / 5;
      var a = c * 0.7, bend = 0.15 * Math.sin(c), px = 300 + (37 * c) % 1300, py = 200 + (53 * c) % 700, sk = c - nBase;
      if (sk === 0) { a = 0; bend = 0; px = 1925; py = 540; }
      else if (sk === 2) { a = 0.3; bend = 0.8; }
      else if (sk === 3) { a = 2.0; bend = -0.8; }
      var pts = [px, py];
      for (var k = 1; k < 6; k++) {
        if (sk !== 1) { px -= sp * Math.cos(a + bend * k); py -= sp * Math.sin(a + bend * k); }
        pts.push(px, py);
      }
      inst.iA.set(pts.slice(0, 4), 4 * c); inst.iB.set(pts.slice(4, 8), 4 * c); inst.iC.set(pts.slice(8, 12), 4 * c);
      inst.iBody.set([Rb, -20 - (3 * c) % 200, 0, 0], 4 * c);
      inst.iX.set([0.3 * Math.sin(c * 1.3), (c * 0.618) % 1, lam, PATH_COLOURS[c % PATH_COLOURS.length]], 4 * c);
      if (!P) continue;
      if (sk < 0) { inst.iBody[4 * c + 3] = poseFixture(c); continue; }
      for (k = 0; k < 6; k++) { var sg = instSeg(inst, c, k); xs[k] = sg[0]; ys[k] = sg[1]; }
      inst.iBody[4 * c + 3] = swimPose(xs, ys, Rb, inst.iBody[4 * c + 1], 1.0, poseG);
    }
    var tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, GENES_W, texRows, 0, gl.RGBA, gl.FLOAT, T);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    /* the decoded cache's texture, packed as the renderer packs it (writeDecoded at each fish's slot), on unit 1 */
    var dtex = null, dData = null, dRows = 0;
    if (D) {
      dRows = genesRows(cap);
      dData = new Float32Array(EA.DECODED_WIDTH * dRows * 4);
      for (c = 0; c < n; c++) EA.writeDecoded(rows[c], dData, slots[c]);
      dtex = gl.createTexture();
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, dtex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, EA.DECODED_WIDTH, dRows, 0, gl.RGBA, gl.FLOAT, dData);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.activeTexture(gl.TEXTURE0);
    }
    gl.useProgram(prog);
    function uni(name) { return gl.getUniformLocation(prog, name); }
    if (D) gl.uniform1i(uni("uDecoded"), 1);
    var I4 = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    gl.uniformMatrix4fv(uni("projectionMatrix"), false, I4); gl.uniformMatrix4fv(uni("viewMatrix"), false, I4);
    gl.uniform3fv(uni("cameraPosition"), U.cam); gl.uniform2fv(uni("uHalf"), U.half);
    gl.uniform1f(uni("uTime"), U.time); gl.uniform1f(uni("uWag"), U.wag); gl.uniform1f(uni("uPxPerUnit"), U.px);
    gl.uniform1f(uni("uColourBy"), colourBy); gl.uniform1i(uni("uGenes"), 0);
    gl.uniform1f(uni("uWalls"), U.walls ? 1 : 0);

    var tpls = [["medium", EA.buildTemplate("medium")], ["coarse", EA.buildTemplate("coarse")], ["barbels", EA.buildBarbels("medium")]];
    var bufs = [], jobs = [];
    gl.enable(gl.RASTERIZER_DISCARD);
    var tfo = gl.createTransformFeedback();
    tpls.forEach(function (tp) {
      var tpl = tp[1];
      if (!tpl) return;
      var ringT = new Float32Array(16);
      for (var i = 0; i < 16; i++) ringT[i] = i < tpl.ringT.length ? tpl.ringT[i] : 0;
      gl.uniform1fv(uni("uRingT[0]") || uni("uRingT"), ringT); gl.uniform1i(uni("uRingN"), tpl.ringT.length); gl.uniform1f(uni("uHalfRing"), tpl.half);
      var vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      function attr(name, data, divisor, size) {
        var loc = gl.getAttribLocation(prog, name);
        if (loc < 0) return;
        var b = gl.createBuffer(); bufs.push(b);
        gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size || 4, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(loc, divisor);
      }
      attr("aT", tpl.pos, 0); attr("aPattern", tpl.pat, 0);
      Object.keys(inst).forEach(function (nm) { attr(nm, inst[nm], 1, nm === "iGeneSlot" ? 1 : 4); });
      var out = gl.createBuffer(); bufs.push(out);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, out);
      gl.bufferData(gl.TRANSFORM_FEEDBACK_BUFFER, tpl.verts * n * NC * 4, gl.STREAM_READ);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, tfo);
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, out);
      gl.beginTransformFeedback(gl.POINTS);
      gl.drawArraysInstanced(gl.POINTS, 0, tpl.verts, n);
      gl.endTransformFeedback();
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
      gl.bindVertexArray(null);
      gl.deleteVertexArray(vao);
      jobs.push({ name: tp[0], tpl: tpl, ringT: ringT, buf: out });
    });
    /* the decoded texels, 18 a fish (one point each, per instance): the GPU's reading of what was uploaded */
    var texelBuf = null;
    if (D) {
      gl.useProgram(dprog);
      gl.uniform1i(gl.getUniformLocation(dprog, "uDecoded"), 1);
      var dvao = gl.createVertexArray();
      gl.bindVertexArray(dvao);
      var sbuf = gl.createBuffer(); bufs.push(sbuf);
      gl.bindBuffer(gl.ARRAY_BUFFER, sbuf); gl.bufferData(gl.ARRAY_BUFFER, slots, gl.STATIC_DRAW);
      var sloc = gl.getAttribLocation(dprog, "iGeneSlot");
      gl.enableVertexAttribArray(sloc); gl.vertexAttribPointer(sloc, 1, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(sloc, 1);
      texelBuf = gl.createBuffer(); bufs.push(texelBuf);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, texelBuf);
      gl.bufferData(gl.TRANSFORM_FEEDBACK_BUFFER, n * EA.DECODED_TEXELS * 16, gl.STREAM_READ);
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, tfo);
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, texelBuf);
      gl.beginTransformFeedback(gl.POINTS);
      gl.drawArraysInstanced(gl.POINTS, 0, EA.DECODED_TEXELS, n);
      gl.endTransformFeedback();
      gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
      gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
      gl.bindVertexArray(null);
      gl.deleteVertexArray(dvao);
    }
    gl.disable(gl.RASTERIZER_DISCARD);
    var sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    gl.flush();
    /* leave nothing bound (a renderer resets its own state after this);
     * the read-back later binds only COPY_READ_BUFFER, which three never uses */
    gl.useProgram(null); gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindTexture(gl.TEXTURE_2D, null);
    if (D) { gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, null); gl.activeTexture(gl.TEXTURE0); }
    function cleanup() {
      gl.bindBuffer(gl.COPY_READ_BUFFER, null);
      gl.deleteSync(sync); gl.deleteTransformFeedback(tfo); gl.deleteTexture(tex); gl.deleteProgram(prog);
      if (dtex) gl.deleteTexture(dtex);
      if (dprog) gl.deleteProgram(dprog);
      bufs.forEach(function (b) { gl.deleteBuffer(b); });
    }
    return fenceDone(gl, sync, 10000).then(function (why) {
      if (why) { cleanup(); return { error: why, colourBy: colourBy }; }
      var res = { fish: n, texRows: texRows, slotMap: opts.slotMap || "identity", maxSlot: top, colourBy: colourBy, polish: P, special: P ? POSE_SPECIAL : undefined,
                  components: NC, mutate: opts.mutate || "", tol: PATH_TOL, templates: {}, ok: true };
      var datas = {};
      jobs.forEach(function (jb) {
        var V = jb.tpl.verts, data = new Float32Array(V * n * NC);
        gl.bindBuffer(gl.COPY_READ_BUFFER, jb.buf);
        gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, data);
        datas[jb.name] = data;
        res.templates[jb.name] = compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, null, names);
        res.templates[jb.name].reach = reachCheck(jb, data, n, NC, inst, U);
        if (res.templates[jb.name].reach.outside) res.ok = false;
      });
      if (D && texelBuf) {
        /* every fish's 72 decoded floats as the GPU read them (texel k, component j: float 4k + j) against the CPU's decode of its row, bit for bit */
        var td = new Float32Array(n * EA.DECODED_FLOATS), tmp = new Float32Array(EA.DECODED_FLOATS), bad = 0, worstT = "";
        gl.bindBuffer(gl.COPY_READ_BUFFER, texelBuf);
        gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, td);
        for (var cc = 0; cc < n; cc++) {
          EA.writeDecoded(rows[cc], tmp, 0);
          for (var q = 0; q < EA.DECODED_FLOATS; q++) {
            var gv = td[cc * EA.DECODED_FLOATS + q];
            if (!(gv === tmp[q] || (gv !== gv && tmp[q] !== tmp[q]))) { bad++; if (!worstT) worstT = "fish " + cc + " texel " + (q >> 2) + "." + "xyzw"[q & 3] + ": the GPU read " + gv + ", the CPU decoded " + tmp[q]; }
          }
        }
        res.decoded = { fish: n, texels: n * EA.DECODED_TEXELS, floats: n * EA.DECODED_FLOATS, mismatches: bad, worst: worstT, ok: bad === 0 };
        if (bad) res.ok = false;
      }
      cleanup();
      var fins = {};
      Object.keys(res.templates).forEach(function (k) {
        var r = res.templates[k];
        if (!r.pass) res.ok = false;
        Object.keys(r.fins).forEach(function (f) { fins[f] = (fins[f] || 0) + r.fins[f]; });
      });
      res.fins = fins;
      res.allParts = [0, 1, 2, 3, 4, 5, 6, 7].every(function (f) { return fins[f] > 0; });
      res.barbelFish = rows.filter(function (g) { return g[EA.MO + 26] > 0.2; }).length;
      if (!res.allParts || !res.barbelFish) res.ok = false;
      if (opts.injectSweep && jobs.length) res.sweep = injectSweep(EA, jobs[0], datas[jobs[0].name], n, NC, rows, lams, inst, U, names);
      return res;
    });
  }
  /* swimPose's visibility sphere holds the fish (P3 of the #48 review): every
   * vertex the GPU placed (vWorld, transform feedback: bent, rolled, folded,
   * wagging, pitched, walled) within reachRadius of the centre between head
   * and tail at the fish's height. maxRatio: the farthest vertex over the radius */
  function reachCheck(jb, data, n, NC, inst, U) {
    var V = jb.tpl.verts, out = { verts: 0, outside: 0, maxRatio: 0, worst: /** @type {object | null} */ (null) }, xs = [], ys = [];
    for (var c = 0; c < n; c++) {
      for (var k = 0; k < 6; k++) { var sg = instSeg(inst, c, k); xs[k] = sg[0]; ys[k] = sg[1]; }
      var R = inst.iBody[4 * c], y = inst.iBody[4 * c + 1], vz = inst.iX[4 * c], lam = inst.iX[4 * c + 2];
      var cx = 0.5 * (xs[0] + xs[5]) - U.half[0], cz = 0.5 * (ys[0] + ys[5]) - U.half[1];
      var rv = reachRadius(xs, ys, R, vz, lam, REACH_APP);
      for (var v = 0; v < V; v++) {
        var o = (c * V + v) * NC, d = Math.hypot(data[o] - cx, data[o + 1] - y, data[o + 2] - cz), q = d / rv;
        out.verts++;
        if (!(q <= 1)) out.outside++;
        if (q > out.maxRatio) { out.maxRatio = q; out.worst = { fish: c, vertex: v, dist: d, radius: rv }; }
      }
    }
    return out;
  }
  /* NaN, +Inf and -Inf into each captured component of one vertex at a time
   * (in place, restored after), compared on that fish alone: each must fail,
   * naming its component */
  function injectSweep(EA, jb, data, n, NC, rows, lams, inst, U, names) {
    var V = jb.tpl.verts, at = [[0, 0], [Math.min(n - 1, 40), Math.min(V - 1, 7)]];
    /** @type {{template: string, positions: number[][], values: string[], tried: number, killed: number, survivors: object[], baselinePass: boolean}} */
    var out = { template: jb.name, positions: at, values: ["NaN", "Infinity", "-Infinity"], tried: 0, killed: 0, survivors: [], baselinePass: true };
    at.forEach(function (p) {
      var c = p[0], v = p[1], only = [c, c + 1];
      if (!compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names).pass) out.baselinePass = false;
      for (var k = 0; k < NC; k++) {
        [NaN, Infinity, -Infinity].forEach(function (x) {
          var o = (c * V + v) * NC + k, keep = data[o];
          data[o] = x;
          var r = compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names);
          data[o] = keep;
          out.tried++;
          if (r.pass === false && r.nan > 0 && r.worst.indexOf("non-finite feedback component " + k + " (") >= 0) out.killed++;
          else if (out.survivors.length < 12) out.survivors.push({ fish: c, vertex: v, component: k, name: names[k], value: String(x), worst: r.worst });
        });
      }
    });
    return out;
  }

  /* GPU == CPU through the production fragment shader (appearanceFragmentCheck):
   * appearanceShaders(EA, P).fs unchanged (FS3: the WebGL2 dialect prefix of
   * appearanceParity), linked to a diagnostic quad whose vertex shader hands
   * it known material / part inputs and the decoded pattern varyings (it
   * does no shading of its own). A 17 x 17 RGBA32F target; its centre pixel,
   * where vWorld = (0, 0, 0) under a camera at (0, 10, 0) and a light straight
   * down: N = V = (0, 1, 0), no rim, no depth tint (uDepth 240, the light
   * field off), no fog, no flashlight, realistic water (CLARITY [0]: vivid
   * off), so lit skin is base x (1.28, 1.3632, 1.2512) and an eye
   * (0.82, 0.83, 0.83). Recolour (uColourBy 1): Family's and Brain's packed
   * palettes, parts 0..7, heights v = 0, .5, 1 at u = .42 (profile height
   * .72), against recolourBase, an independent statement of the base stage;
   * appearance (uColourBy 0): body part 0 against EvoAppearance.flankAt.
   * Constant material inputs make the derivative filters vanish. Max |error|
   * over RGB <= .003, alpha 1. opts.fsMutate ("swapRB": red and blue
   * exchanged in the unpacking; "branch": the colour-mode branch reversed)
   * must fail it.
   * opts.polish: the polished shader (POLISH_FN), its size weight 1 (vPw)
   * and no caustic light. The same cases gain the wet highlight's peak,
   * 0.30 x (1 - thin / 2) x P_WET (the facet faces the half vector; nothing
   * shows through, no sheen at normal incidence); then the same with the
   * weight 0 (recolourW0, appearanceW0: exactly the plain look); then
   * backlit (recolourBack, appearanceBack): the light straight up from
   * below, exactly opposite the view, so the half vector is zero (the
   * highlight must be 0, never NaN), no diffuse, and a thin part glows
   * through: base x (ambient up + P_SUN x thin), the eye its dark colour. */
  var FRAG_TOL = 0.003;
  var FRAG_MUL = [0.36 + 0.92, 0.48 + 0.92 * 0.96, 0.46 + 0.92 * 0.86];   /* ambient straight up + full diffuse */
  var FRAG_EYE = [0.82, 0.83, 0.83];
  var FRAG_AMB = [0.36, 0.48, 0.46], FRAG_SUN = [1.0, 0.96, 0.86];        /* ambient straight up; POLISH_FN's P_SUN */
  /* the polish's thinness at u = .42 (thinOf) and wet highlight at its peak (polishK) on part fin */
  function fragThin(fin) { return fin === 0 || fin === 4 ? 0 : (fin === 7 ? 0.6 : 1); }
  function fragWet(fin) { var k = 0.30 * (1 - 0.5 * fragThin(fin)); return [k, k * 0.98, k * 0.92]; }
  var FRAG_PALETTES = { family: PATH_COLOURS, brain: [0xff0000, 0x00ff00, 0x0000ff, 0x808080, 0x3c9ae1] };
  var FRAG_MUT = {
    swapRB: ["vec3 base = vec3(r, g, c - 65536.0 * r - 256.0 * g) / 255.0;", "vec3 base = vec3(c - 65536.0 * r - 256.0 * g, g, r) / 255.0;"],
    branch: ["if (uColourBy > 0.5) base = colourBase(fin, oyL, uBack);", "if (uColourBy < 0.5) base = colourBase(fin, oyL, uBack);"],
    /* (the decoded fragment stage only: the pattern's first texel read from the second) */
    dswap: ["vG0 = decodedTexel(slot, 8);", "vG0 = decodedTexel(slot, 9);"]
  };
  function recolourBase(rgb, fin, v) {
    var base = [(rgb >>> 16) & 255, (rgb >>> 8) & 255, rgb & 255].map(function (x) { return x / 255; });
    function smooth(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
    function mix(a, b, t) { return a.map(function (x, i) { return x + (b[i] - x) * t; }); }
    var oy = (1 - 2 * v) * 0.72;
    base = mix(base, base.map(function (x) { return x * 0.56; }), smooth(0.30, 0.85, oy) * (fin === 0 ? 1 : 0));
    base = mix(base, mix(base, [0.93, 0.97, 0.90], 0.5), 1 - smooth(-0.7, -0.15, oy));
    if (fin !== 0) base = mix(base, [0.92, 0.98, 0.95], 0.22);
    return base;
  }
  /** @returns {Promise<any>} */
  function appearanceFragmentCheck(gl, EA, opts) {
    opts = opts || {};
    if (!BOUND) return Promise.resolve({ error: UNBOUND });
    if (!EA || !EA.flankAt) return Promise.resolve({ error: "web/ocean_appearance.js not loaded" });
    /* opts.decoded: the render optimization's decoded fragment stage (render.decoded): the pattern's constants loaded per fragment from a
     * decoded texture (the case's row, decoded by writeDecoded and packed at its case number as its slot) instead of the flat varyings
     * the diagnostic vertex stage hands over; the expectations are the same as the raw stage's */
    var P = !!opts.polish, D = !!opts.decoded;
    if (D && (!EA.writeDecoded || !DECODED)) return Promise.resolve({ error: "the decoded constants (EvoAppearance.writeDecoded) are not loaded" });
    var fsrc = appearanceShaders(EA, P, D ? [DECODED] : []).fs;
    if (opts.fsMutate) {
      var pm = plant(fsrc, opts.fsMutate, FRAG_MUT);
      if (pm.error) return Promise.resolve({ error: pm.error });
      fsrc = pm.src;
    }
    if (!gl.getExtension("EXT_color_buffer_float")) return Promise.resolve({ error: "no float render targets (EXT_color_buffer_float)" });
    var G = EA.GLSL;
    var vsrc = lines(D ? [
      "attribute vec2 aXY;",
      "uniform float uSlot; uniform float uLam;",
      "uniform vec4 uMaterial; uniform float uFin; uniform float uPacked;",
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart; flat varying vec2 vDecoded;",
      P ? "uniform float uPw; flat varying float vPw; varying float vCaus;" : null,
      "void main() {",
      "  vDecoded = vec2(uSlot, uLam);",
      "  vWorld = vec3(aXY.x, 0.0, aXY.y);",
      "  vMatV = uMaterial;",
      "  vPart = vec4(uFin, 1.0, 0.0, uPacked);",
      P ? "  vPw = uPw; vCaus = 0.0;" : null,
      "  gl_Position = vec4(aXY, 0.0, 1.0);",
      "}"
    ] : [
      G.COMMON, G.VARY, G.DECODE,
      "attribute vec2 aXY;",
      "uniform vec4 uG[9]; uniform float uLam;",
      "uniform vec4 uMaterial; uniform float uFin; uniform float uPacked;",
      "varying vec3 vWorld; varying vec4 vMatV; flat varying vec4 vPart;",
      P ? "uniform float uPw; flat varying float vPw; varying float vCaus;" : null,
      "void main() {",
      "  patternDecode(uG[0], uG[1], uG[2], uG[3], uG[4], uG[5], uG[6], uG[7].xyz, vec2(uG[7].w, uG[8].x), uLam);",
      "  vWorld = vec3(aXY.x, 0.0, aXY.y);",
      "  vMatV = uMaterial;",
      "  vPart = vec4(uFin, 1.0, 0.0, uPacked);",
      P ? "  vPw = uPw; vCaus = 0.0;" : null,   /* the size weight as the case's, no caustic light */
      "  gl_Position = vec4(aXY, 0.0, 1.0);",
      "}"
    ]);
    var prog;
    try { prog = compileProgram(gl, VS3 + vsrc, FS3 + fsrc); }
    catch (e) { return Promise.resolve({ error: e.message || String(e) }); }
    for (var guard = 0; guard < 32 && gl.getError() !== gl.NO_ERROR; guard++);   /* not ours */

    /* the cases: [colourBy, fin, packed colour, gene row, lambda, material, light, size weight, expected] */
    var U0 = Math.fround(0.42), cases = [];
    function material(fin, v) {   /* body / barbels: v = .5(1 - rho sin(theta)); the fins: v itself */
      if (fin === 0 || fin === 7) return [U0, Math.fround(Math.asin(1 - 2 * v)), 1, 1000];
      return [U0, Math.fround(v), 0, 1000];
    }
    function vOf(fin, m) { return fin === 0 || fin === 7 ? 0.5 * (1 - m[2] * Math.sin(m[1])) : m[1]; }
    /* the expected colour of skin b on part fin: front-lit (plain, or with the highlight at weight pw), or backlit */
    function lit(b, fin, how, pw) {
      if (fin === 4) return how === "back" ? [0.02, 0.03, 0.03] : FRAG_EYE;
      if (how === "back") return [0, 1, 2].map(function (i) { return b[i] * (FRAG_AMB[i] + FRAG_SUN[i] * fragThin(fin) * pw); });
      var h = how === "polish" ? fragWet(fin) : [0, 0, 0];
      return [0, 1, 2].map(function (i) { return b[i] * FRAG_MUL[i] + h[i] * pw; });
    }
    var skin = [0.13, 0.43, 0.71].map(function (hue) {
      var g = []; for (var j = 0; j < EA.STRIDE; j++) g.push(Math.fround(0.5));
      g[0] = Math.fround(hue); g[1] = Math.fround(0.7); g[2] = Math.fround(0.6);
      return g;
    });
    var DOWN = [0, 1, 0], UP = [0, -1, 0];
    /* [suffix, light, size weight, expectation]: plain once; polished front-lit, weight 0, backlit */
    var sets = P ? [["", DOWN, 1, "polish"], ["W0", DOWN, 0, "plain"], ["Back", UP, 1, "back"]] : [["", DOWN, 1, "plain"]];
    sets.forEach(function (st) {
      Object.keys(FRAG_PALETTES).forEach(function (pal) {
        FRAG_PALETTES[pal].forEach(function (rgb) {
          for (var fin = 0; fin < 8; fin++) [0, 0.5, 1].forEach(function (v) {
            var m = material(fin, v);
            cases.push({ mode: "recolour" + st[0], palette: pal, colourBy: 1, fin: fin, packed: rgb, row: skin[0], lam: 4, m: m, light: st[1], pw: st[2],
                         want: lit(recolourBase(rgb, fin, vOf(fin, m)), fin, st[3], st[2]) });
          });
        });
      });
      skin.forEach(function (row, i) {
        [0, 0.5, 1].forEach(function (v) {
          var m = material(0, v), out = [0, 0, 0];
          EA.flankAt(EA.decode(row, 4), U0, vOf(0, m), out);
          cases.push({ mode: "appearance" + st[0], palette: "skin " + i, colourBy: 0, fin: 0, packed: PATH_COLOURS[i], row: row, lam: 4, m: m, light: st[1], pw: st[2],
                       want: lit(out, 0, st[3], st[2]) });
        });
      });
    });

    var S = 17, tex = gl.createTexture(), fb = gl.createFramebuffer(), vao = gl.createVertexArray(), quad = gl.createBuffer(), pbo = gl.createBuffer(), dtex = null;
    function cleanup() {
      gl.bindBuffer(gl.COPY_READ_BUFFER, null);
      gl.deleteTexture(tex); gl.deleteFramebuffer(fb); gl.deleteVertexArray(vao); gl.deleteBuffer(quad); gl.deleteBuffer(pbo); gl.deleteProgram(prog);
      if (dtex) gl.deleteTexture(dtex);
    }
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, S, S, 0, gl.RGBA, gl.FLOAT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    var fbs = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (fbs !== gl.FRAMEBUFFER_COMPLETE) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); cleanup(); return Promise.resolve({ error: "the float target is incomplete (" + fbs + ")" }); }
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "aXY");
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.useProgram(prog);
    function uni(name) { return gl.getUniformLocation(prog, name); }
    if (D) {   /* the cases' rows decoded and packed as the renderer packs them: case i at slot i */
      var dRows = Math.ceil(cases.length / EA.DECODED_ROW_SLOTS), dData = new Float32Array(EA.DECODED_WIDTH * dRows * 4);
      cases.forEach(function (cs, i) { EA.writeDecoded(cs.row, dData, i); });
      dtex = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, dtex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, EA.DECODED_WIDTH, dRows, 0, gl.RGBA, gl.FLOAT, dData);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.uniform1i(uni("uDecoded"), 0);
    }
    var W = CLARITY;   /* realistic water: the [0] column */
    gl.uniform3fv(uni("uLight"), [0, 1, 0]); gl.uniform1f(uni("uTime"), 0); gl.uniform3fv(uni("uSelect"), C.select);
    gl.uniform3fv(uni("uFog"), W.fog[0]); gl.uniform1f(uni("uFogDensity"), 0);
    gl.uniform1f(uni("uDepth"), 240); gl.uniform1f(uni("uLightOn"), 0); gl.uniform1f(uni("uL0"), 1); gl.uniform1f(uni("uKWater"), 0);
    gl.uniform3fv(uni("uDeepTint"), W.deepTint[0]); gl.uniform1f(uni("uDeepDim"), W.deepDim[0]); gl.uniform3fv(uni("uDeepAdd"), W.deepAdd[0]);
    gl.uniform1f(uni("uLKeep"), W.lKeep[0]); gl.uniform1f(uni("uFloorMin"), W.floorMin[0]); gl.uniform1f(uni("uBack"), W.back[0]);
    gl.uniform3fv(uni("uAmbLo"), W.ambLo[0]); gl.uniform3fv(uni("uAmbHi"), W.ambHi[0]); gl.uniform3fv(uni("uVivid"), W.vivid[0]);
    gl.uniform1f(uni("uBeamOn"), 0); gl.uniform3fv(uni("uBeamDir"), [0, -1, 0]); gl.uniform1f(uni("uBeamTan"), 0.2); gl.uniform1f(uni("uBeamReach"), 1000);
    gl.uniform1f(uni("uIntrinsic"), 0); gl.uniform3fv(uni("cameraPosition"), [0, 10, 0]);
    gl.viewport(0, 0, S, S);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.CULL_FACE); gl.colorMask(true, true, true, true);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, pbo);
    gl.bufferData(gl.PIXEL_PACK_BUFFER, cases.length * 16, gl.STREAM_READ);
    var uG = new Float32Array(36), half = Math.floor(S / 2);
    cases.forEach(function (cs, i) {
      for (var j = 0; j < 36; j++) uG[j] = j < cs.row.length ? cs.row[j] : 0;
      gl.uniform4fv(uni("uG[0]") || uni("uG"), uG); gl.uniform1f(uni("uLam"), cs.lam);
      gl.uniform4fv(uni("uMaterial"), cs.m); gl.uniform1f(uni("uFin"), cs.fin); gl.uniform1f(uni("uPacked"), cs.packed);
      gl.uniform1f(uni("uColourBy"), cs.colourBy);
      if (D) gl.uniform1f(uni("uSlot"), i);
      if (P) { gl.uniform3fv(uni("uLight"), cs.light); gl.uniform1f(uni("uPw"), cs.pw); }
      gl.clearBufferfv(gl.COLOR, 0, [-9, -9, -9, -9]);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.readPixels(half, half, 1, 1, gl.RGBA, gl.FLOAT, i * 16);
    });
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    var glErr = gl.getError();
    var sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    gl.flush();
    gl.useProgram(null); gl.bindVertexArray(null); gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (D) gl.bindTexture(gl.TEXTURE_2D, null);
    if (glErr !== gl.NO_ERROR) { gl.deleteSync(sync); cleanup(); return Promise.resolve({ error: "GL error " + glErr }); }
    return fenceDone(gl, sync, 10000).then(function (why) {
      gl.deleteSync(sync);
      if (why) { cleanup(); return { error: why }; }
      var px = new Float32Array(cases.length * 4);
      gl.bindBuffer(gl.COPY_READ_BUFFER, pbo);
      gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, px);
      cleanup();
      var res = { cases: cases.length, polish: P, tol: FRAG_TOL, fsMutate: opts.fsMutate || "", failures: 0, nonFinite: 0, alphaBad: 0,
                  maxErr: 0, worst: "", modes: {} };
      cases.forEach(function (cs, i) {
        var got = [px[4 * i], px[4 * i + 1], px[4 * i + 2], px[4 * i + 3]];
        var md = res.modes[cs.mode] || (res.modes[cs.mode] = { cases: 0, maxErr: 0, failures: 0 });
        md.cases++;
        if (!got.every(Number.isFinite)) { res.nonFinite++; res.failures++; md.failures++; if (!res.worst) res.worst = cs.mode + " " + cs.palette + " part " + cs.fin + ": non-finite"; return; }
        var e = Math.max(Math.abs(got[0] - cs.want[0]), Math.abs(got[1] - cs.want[1]), Math.abs(got[2] - cs.want[2]));
        if (got[3] !== 1) res.alphaBad++;
        md.maxErr = Math.max(md.maxErr, e);
        if (e > FRAG_TOL || got[3] !== 1) { res.failures++; md.failures++; }
        if (e > res.maxErr) {
          res.maxErr = e;
          res.worst = cs.mode + " " + cs.palette + " #" + cs.packed.toString(16) + " part " + cs.fin + " v " + vOf(cs.fin, cs.m).toFixed(3) +
                      ": got " + got.slice(0, 3).map(function (x) { return x.toFixed(4); }).join(" ") +
                      ", want " + cs.want.map(function (x) { return x.toFixed(4); }).join(" ");
        }
      });
      res.ok = res.failures === 0 && cases.length > 0;
      return res;
    });
  }

  /* The production checks together: the fixed fixture (and the caller's
   * rows) through the vertex shader in both colour modes, and the fragment
   * shader, for the plain programs (appearance, recolour, fragment), the
   * full ones (polish.appearance, polish.recolour, polish.fragment) and the
   * lite ones (polish.lite.appearance, .recolour; their fragment stage is
   * the plain one); and the gene slots apart from the draw order (slots:
   * the plain appearance mode with a permuted and a sparse slot map).
   * opts.mutate / opts.fsMutate as above (planted in all); opts.injectSweep
   * on the plain vertex checks. */
  function appearancePathCheck(gl, EA, rows, lams, opts) {
    opts = opts || {};
    if (!BOUND) return Promise.resolve({ ok: false, error: UNBOUND });
    if (!EA || !EA.morphBuild) return Promise.resolve({ error: "web/ocean_appearance.js (with its CPU mirror) not loaded" });
    var fx = pathFixture(EA), R = fx.rows.concat(rows || []), L = fx.lams.concat(lams || []);
    function o(x) { return Object.assign({}, opts, x); }
    return Promise.all([appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 0 })), appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 1 })),
                        appearanceFragmentCheck(gl, EA, opts),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 0, polish: true, injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 1, polish: true, injectSweep: false })),
                        appearanceFragmentCheck(gl, EA, o({ polish: true })),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 0, polish: "lite", injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 1, polish: "lite", injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 0, slotMap: "permuted", injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ colourBy: 0, slotMap: "sparse", injectSweep: false })),
                        /* the render optimization's decoded programs (render.decoded): plain, full and lite polish, permuted and sparse slots,
                         * and their fragment stages (plain, polished); the raw checks above stay the production reference they are held to */
                        appearanceVertexCheck(gl, EA, R, L, o({ decoded: true, injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ decoded: true, polish: true, injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ decoded: true, polish: "lite", injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ decoded: true, slotMap: "permuted", injectSweep: false })),
                        appearanceVertexCheck(gl, EA, R, L, o({ decoded: true, slotMap: "sparse", injectSweep: false })),
                        appearanceFragmentCheck(gl, EA, o({ decoded: true })),
                        appearanceFragmentCheck(gl, EA, o({ decoded: true, polish: true }))])
      .then(function (r) {
        var errs = [];
        ["appearance", "recolour", "fragment", "polish.appearance", "polish.recolour", "polish.fragment", "polish.lite.appearance", "polish.lite.recolour",
         "slots.permuted", "slots.sparse", "decoded.vertex", "decoded.polish", "decoded.lite", "decoded.permuted", "decoded.sparse", "decoded.fragment",
         "decoded.polish.fragment"].forEach(function (k, i) { if (r[i].error) errs.push(k + ": " + r[i].error); });
        var out = { ok: errs.length === 0 && r.every(function (x) { return x.ok === true; }), fixture: fx.rows.length, fish: R.length,
                    appearance: r[0], recolour: r[1], fragment: r[2],
                    polish: { ok: r[3].ok === true && r[4].ok === true && r[5].ok === true && r[6].ok === true && r[7].ok === true,
                              appearance: r[3], recolour: r[4], fragment: r[5], lite: { appearance: r[6], recolour: r[7] } },
                    slots: { ok: r[8].ok === true && r[9].ok === true, permuted: r[8], sparse: r[9] },
                    decoded: { ok: r.slice(10).every(function (x) { return x.ok === true; }), vertex: r[10], polish: r[11], lite: r[12], permuted: r[13], sparse: r[14],
                               fragment: r[15], polishFragment: r[16] } };
        if (errs.length) out.error = errs.join("; ");
        return out;
      });
  }
  /* the vertex stage's spine and placement (CORE seg / spine / appWorld /
   * minWidth) for instance c, at uWag = 0 */
  function instSeg(inst, c, i) {
    var a = i < 2 ? inst.iA : (i < 4 ? inst.iB : inst.iC), o = 4 * c + 2 * (i % 2);
    return [a[o], a[o + 1]];
  }
  function spineCPU(inst, c, s) {
    var seg = function (i) { return instSeg(inst, c, i); };
    if (s <= 0) { var a0 = seg(0), a1 = seg(1); return [a0[0] + (a0[0] - a1[0]) * (-s), a0[1] + (a0[1] - a1[1]) * (-s)]; }
    if (s >= 5) { var b5 = seg(5), b4 = seg(4); return [b5[0] + (b5[0] - b4[0]) * (s - 5), b5[1] + (b5[1] - b4[1]) * (s - 5)]; }
    var i = Math.floor(s), t = s - i, p0 = seg(Math.max(i - 1, 0)), p1 = seg(i), p2 = seg(Math.min(i + 1, 5)), p3 = seg(Math.min(i + 2, 5));
    var t2 = t * t, t3 = t2 * t, out = [0, 0];
    for (var q = 0; q < 2; q++)
      out[q] = 0.5 * ((2 * p1[q]) + (-p0[q] + p2[q]) * t + (2 * p0[q] - 5 * p1[q] + 4 * p2[q] - p3[q]) * t2 + (-p0[q] + 3 * p1[q] - 3 * p2[q] + p3[q]) * t3);
    return out;
  }
  /* the polished vertex stage's swim pose (POSE_GLSL wagAt, rollTo; finPose)
   * for instance c, from its iPose (U.polish; U.time, U.wag: the clock and
   * the tail beat). Plain (no U.polish): the old beat, no roll, no fold */
  function poseCPU(inst, c, U) {   /* lite: the roll only (no fold, no lag) */
    if (!U.polish) return null;
    var p = unpackPose(inst.iBody[4 * c + 3]);
    return U.lite ? [p[0], p[1], 0, 0] : p;
  }
  function wagCPU(u, ph, R, pose, U) {
    var e = pose ? pose[3] * Math.max(0, Math.min(1, 2 * (u - 1))) : 0;
    var w = Math.sin(ph - 0.9 * e) * (1 + 0.25 * e);
    if (e > 0) w += 0.14 * e * Math.sin(2 * ph - 0.6);
    return w * U.wag * smoothCPU(0.1, 1.3, u) * R * 0.3;
  }
  function finPoseCPU(EA, M, aT, pat, geo, pose) {   /* (lite: pose[2] 0, unmoved) */
    var fin = Math.floor(pat[0] + 0.5);
    if (!pose || pose[2] <= 0 || (fin !== 3 && fin !== 6)) return geo;
    var pec = fin === 3, side = pat[2];
    var chord = pec ? 0.80 : 0.55, area = pec ? M.pA : M.vA, sweep = pec ? M.pSweep : M.vSweep;
    var dih = pec ? M.pDih : -0.25 * Math.PI, kk = pec ? pose[2] : 0.5 * pose[2];
    var w = area / (chord * Math.fround(EA.PHI_I)) * aT[1] * 4 * aT[0] * (1 - aT[0]);
    var d = [sweep, side * Math.cos(dih), Math.sin(dih)], L = Math.hypot(d[0], d[1], d[2]);
    var t = [1, 0.22 * side, -0.18], tl = Math.hypot(t[0], t[1], t[2]);
    var m = [0, 1, 2].map(function (i) { return d[i] + (t[i] / tl * L - d[i]) * kk; }), ml = Math.hypot(m[0], m[1], m[2]);
    var dir = ml > 1e-4 ? m.map(function (x) { return x * L / ml; }) : d;
    return [0, 1, 2].map(function (i) { return geo[i] + w * (dir[i] - d[i]); });
  }
  function appWorldCPU(inst, c, geo, U, pose) {
    var Rb = inst.iBody[4 * c], u = geo[0] / inst.iX[4 * c + 2];
    var s = Math.min(3, Math.max(-1.5, u)) * 5, cc = spineCPU(inst, c, s);
    var f1 = spineCPU(inst, c, s - 0.15), f2 = spineCPU(inst, c, s + 0.15), f = [f1[0] - f2[0], f1[1] - f2[1]], fl = Math.hypot(f[0], f[1]);
    f = fl > 1e-4 ? [f[0] / fl, f[1] / fl] : [1, 0];
    var wag = U.wag ? wagCPU(u, U.time * 7.5 + inst.iX[4 * c + 1] * 6.2831 - u * 4.5, Rb, pose, U) : 0;
    var lat = geo[1] * Rb + wag, up = geo[2] * Rb;
    var lu = pose ? [lat * pose[1] + up * pose[0], up * pose[1] - lat * pose[0]] : [lat, up];   /* rollTo */
    var side = [-f[1], f[0]], p = [cc[0] + side[0] * lu[0], cc[1] + side[1] * lu[0]];
    var s0 = instSeg(inst, c, 0), along = Math.hypot(cc[0] - s0[0], cc[1] - s0[1]) * (s < 0 ? -1 : 1);
    var lift = along * Math.min(1.2, Math.max(-1.2, inst.iX[4 * c]));
    var w = [p[0] - U.half[0], inst.iBody[4 * c + 1] + lu[1] + lift, p[1] - U.half[1]];
    if (U.walls) {   /* the shader's glass clamp (uWalls) */
      w[0] = Math.min(U.half[0], Math.max(-U.half[0], w[0]));
      w[2] = Math.min(U.half[1], Math.max(-U.half[1], w[2]));
    }
    return w;
  }
  function minWidthCPU(inst, c, U) {
    var hx = inst.iA[4 * c] - U.half[0], hy = inst.iBody[4 * c + 1], hz = inst.iA[4 * c + 1] - U.half[1];
    var d = Math.hypot(U.cam[0] - hx, U.cam[1] - hy, U.cam[2] - hz);
    return 0.7 * Math.max(1, d) / Math.max(1e-3, inst.iBody[4 * c] * U.px);
  }
  /* one template's feedback against the CPU mirror. only: [c0, c1) the fish
   * compared (all when absent); names: the captured components' names */
  function compareTemplate(EA, jb, data, n, NC, rows, lams, inst, U, only, names) {
    var V = jb.tpl.verts, rings = { ringT: Array.prototype.slice.call(jb.ringT, 0, jb.tpl.ringT.length), half: jb.tpl.half };
    var r = { verts: V, maxWorld: 0, maxMat: 0, maxMar: 0, maxDecode: 0, partBad: 0, nan: 0, fins: {}, worst: "" }, worstE = 0;
    var VN = ["vG0", "vG1", "vG2", "vG3", "vG4", "vG5", "vG6", "vG7", "vAux", "vMeta"];
    var c0 = only ? only[0] : 0, c1 = only ? only[1] : n;
    for (var c = c0; c < c1; c++) {
      var lam = Math.fround(lams[c]), M = EA.morphDecode(rows[c], lam), P = U.colourBy ? null : EA.patternVaryings(rows[c], lam), minW = minWidthCPU(inst, c, U);
      var pose = poseCPU(inst, c, U);
      for (var v = 0; v < V; v++) {
        var o = (c * V + v) * NC;
        var aT = [jb.tpl.pos[4 * v], jb.tpl.pos[4 * v + 1], jb.tpl.pos[4 * v + 2], jb.tpl.pos[4 * v + 3]];
        var pat = [jb.tpl.pat[4 * v], jb.tpl.pat[4 * v + 1], jb.tpl.pat[4 * v + 2], jb.tpl.pat[4 * v + 3]];
        var fin = Math.floor(pat[0] + 0.5);
        r.fins[fin] = (r.fins[fin] || 0) + 1;
        var where = "fish " + c + " vertex " + v + " (part " + fin + ")";
        /* every captured component finite, before any arithmetic: |NaN - x| >
         * tol is false, and min(Infinity, 10) would hide an infinity */
        var badComponent = -1;
        for (var component = 0; component < NC; component++) {
          if (!Number.isFinite(data[o + component])) { badComponent = component; break; }
        }
        if (badComponent >= 0) {
          if (!r.nan++) r.worst = where + ": non-finite feedback component " + badComponent + " (" + (names ? names[badComponent] : "?") + ")";
          continue;
        }
        var b = EA.morphBuild(M, rings, aT, pat, U.time, U.wag, minW), w = appWorldCPU(inst, c, finPoseCPU(EA, M, aT, pat, b.geo, pose), U, pose);
        var eW = Math.max(Math.abs(data[o] - w[0]), Math.abs(data[o + 1] - w[1]), Math.abs(data[o + 2] - w[2]));
        var eM = Math.max(Math.abs(data[o + 3] - b.mat[0]), Math.abs(data[o + 4] - b.mat[1]), Math.abs(data[o + 5] - b.mat[2]));
        var eR = Math.abs(Math.min(data[o + 6], 10) - Math.min(b.mar, 10));
        if (Math.abs(data[o + 7] - pat[0]) > 1e-6 || Math.abs(data[o + 8] - pat[2]) > 1e-6 || data[o + 9] !== inst.iBody[4 * c + 2] || data[o + 10] !== inst.iX[4 * c + 3]) r.partBad++;
        var eD = 0;
        if (P) for (var q = 0; q < VN.length; q++) for (var k = 0; k < 4; k++) {   /* appearance mode: the decoded pattern */
          var g = data[o + 11 + 4 * q + k], ref = P[VN[q]][k], d = Math.abs(g - ref);
          if (q === 0 && k === 0) d = Math.min(d, 1 - d);   /* a hue: circular */
          eD = Math.max(eD, d / Math.max(1, Math.abs(ref)));
        }
        if (![eW, eM, eR, eD].every(Number.isFinite)) { if (!r.nan++) r.worst = where + ": NaN"; continue; }
        r.maxWorld = Math.max(r.maxWorld, eW); r.maxMat = Math.max(r.maxMat, eM);
        r.maxMar = Math.max(r.maxMar, eR); r.maxDecode = Math.max(r.maxDecode, eD);
        var score = Math.max(eW / PATH_TOL.world, eM / PATH_TOL.mat, eR / PATH_TOL.mar, eD / PATH_TOL.decode);
        if (score > worstE && !r.nan) { worstE = score; r.worst = where + ": world " + eW.toExponential(2) + ", mat " + eM.toExponential(2) + ", mar " + eR.toExponential(2) + ", decode " + eD.toExponential(2); }
      }
    }
    r.pass = !r.nan && r.maxWorld <= PATH_TOL.world && r.maxMat <= PATH_TOL.mat && r.maxMar <= PATH_TOL.mar && r.maxDecode <= PATH_TOL.decode && r.partBad === 0;
    return r;
  }

  /* The probes on a live scene (attach(port): web/ocean_scene.js create(),
   * once a scene). The port is the scene's renderer and live getters of what
   * it drew, read at each probe (never copies: a probe checks what production
   * uploaded):
   *   THREE, renderer, profiler: the scene's, fixed for its life
   *   geneIO: its gene texture's upload counts (live: a probe asserts it
   *     caused none), bodyScale: opts.bodyScale (fillApp's lambda)
   *   ea(), status(): EvoAppearance (null once the appearance renderer
   *     failed) and the appearance status
   *   appKind(), drawn(): the appearance fish's kind (its instance
   *     attributes, gene texture and slots, material and programs) and
   *     whether this frame drew it
   * It returns the probes and their queue: the scene's render() calls
   * runProbes(s) right after a production draw (and failProbes(why) when
   * the context is lost), so a probe always runs after the draw it checks;
   * testFaults is read by the scene's gene upload. */
  /** @param {ParityProbePort} port @returns {ParityProbes} */
  function attach(port) {
    if (!BOUND) throw new Error(UNBOUND);   /* (the texture probe reads the layout: bind first) */
    var THREE = port.THREE, renderer = port.renderer, profiler = port.profiler, geneIO = port.geneIO, bodyScale = port.bodyScale;
    /* test-only: holdGeneUploads leaves the gene texture's upload out, so a
     * stale texture can be shown to fail appearanceTextureParity */
    var testFaults = { holdGeneUploads: false };

    /* GPU == CPU (the gallery's K12): each row's canonical flank chart,
     * rendered unlit and unfiltered (uIntrinsic = 1) into a float target and
     * read back, against the CPU mirror EvoAppearance.flankAt at every pixel
     * centre. Raw WebGL2 on three's context (the same GLSL as the fish, with
     * its own prefix; three's state is reset after). Returns the error
     * statistics (max over r, g, b per pixel). Display code only. */
    function appearanceParity(rows, lams, cellW, cellH) {
      var EA = port.ea(), appStatus = port.status();   /* (the port's live getters, as the scene's names) */
      if (!EA) return { error: appStatus };
      var gl = renderer.getContext();
      if (!gl.getExtension("EXT_color_buffer_float")) return { error: "no float render targets (EXT_color_buffer_float)" };
      var sh = appearanceShaders(EA);
      var pre = "#version 300 es\nprecision highp float;\nprecision highp int;\n";
      function compile(type, src) {
        var o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
        if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o));
        return o;
      }
      var prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, pre + "#define attribute in\n#define varying out\nin vec3 position;\n" + sh.chartVs));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, pre + "#define varying in\nout highp vec4 pcFrag;\n#define gl_FragColor pcFrag\n" + sh.chartFs));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return { error: gl.getProgramInfoLog(prog) };
      var n = rows.length, cols = Math.min(8, n), nr = Math.ceil(n / cols);
      var w = cellW || 96, h = cellH || 48, TW = cols * w, TH = nr * h;
      var tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, TW, TH, 0, gl.RGBA, gl.FLOAT, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      var fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      var vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      var bufs = [];
      function attr(name, data, size, divisor) {
        var loc = gl.getAttribLocation(prog, name);
        if (loc < 0) return;
        var b = gl.createBuffer(); bufs.push(b);
        gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(loc, divisor);
      }
      attr("position", new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), 3, 0);
      var names = ["iG0", "iG1", "iG2", "iG3", "iG4", "iG5", "iG6", "iCol", "iX", "iCell"], arr = {};
      names.forEach(function (nm) { arr[nm] = new Float32Array(n * 4); });
      for (var k = 0; k < n; k++) {
        var R = rows[k], o = 4 * k;
        for (var q = 0; q < 7; q++) for (var c = 0; c < 4; c++) arr["iG" + q][o + c] = R[4 * q + c];
        arr.iCol[o] = R[28]; arr.iCol[o + 1] = R[29]; arr.iCol[o + 2] = R[30]; arr.iCol[o + 3] = 0;
        arr.iX[o] = 0; arr.iX[o + 1] = R[31]; arr.iX[o + 2] = R[32]; arr.iX[o + 3] = lams[k];
        var cx = k % cols, cy = Math.floor(k / cols);
        arr.iCell[o] = -1 + 2 * cx / cols; arr.iCell[o + 1] = -1 + 2 * cy / nr; arr.iCell[o + 2] = 2 / cols; arr.iCell[o + 3] = 2 / nr;
      }
      names.forEach(function (nm) { attr(nm, arr[nm], 4, 1); });
      gl.useProgram(prog);
      gl.uniform1f(gl.getUniformLocation(prog, "uIntrinsic"), 1);
      gl.viewport(0, 0, TW, TH);
      gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.CULL_FACE);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, n);
      var px = new Float32Array(TW * TH * 4);
      gl.readPixels(0, 0, TW, TH, gl.RGBA, gl.FLOAT, px);
      gl.bindVertexArray(null); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.deleteVertexArray(vao); bufs.forEach(function (b) { gl.deleteBuffer(b); });
      gl.deleteFramebuffer(fb); gl.deleteTexture(tex); gl.deleteProgram(prog);
      renderer.resetState();
      var errs = [], sum = 0, maxErr = 0, over = 0, out = [0, 0, 0], worst = "";
      for (k = 0; k < n; k++) {
        var D = EA.decode(rows[k], lams[k]), x0 = (k % cols) * w, y0 = Math.floor(k / cols) * h;
        for (var j = 0; j < h; j++) for (var i = 0; i < w; i++) {
          EA.flankAt(D, (i + 0.5) / w, (j + 0.5) / h, out);
          var p = ((y0 + j) * TW + x0 + i) * 4;
          var e = Math.max(Math.abs(px[p] - out[0]), Math.abs(px[p + 1] - out[1]), Math.abs(px[p + 2] - out[2]));
          errs.push(e); sum += e; if (e > 0.002) over++;
          if (e > maxErr) { maxErr = e; worst = "row " + k + " u " + ((i + 0.5) / w).toFixed(3) + " v " + ((j + 0.5) / h).toFixed(3); }
        }
      }
      errs.sort(function (a, b) { return a - b; });
      return { fish: n, samples: errs.length, maxErr: maxErr, meanErr: sum / errs.length, p99: errs[Math.floor(errs.length * 0.99)],
               p999: errs[Math.floor(errs.length * 0.999)], over002: over / errs.length, worst: worst };
    }

    /* ---- the live gene texture, checked (appearanceTextureParity) ----
     * Right after a production draw of the appearance fish, two diagnostic
     * draws read appKind.tex itself, bound through the fish material's own
     * uGenes uniform (so three's uploader is what is tested), with the
     * production instance attributes (iX) and the same slot selector
     * (GENE_SLOT_GLSL), into RGBA32F targets (nearest, no mipmaps, no MSAA,
     * no depth) read back through pixel-pack buffers and a fence (polled,
     * 10 s; three's state is restored before anything waits):
     *   raw: every fish's 16 texels, bit for bit, against owned copies of
     *     the snapshot's 63 genes and the zero after them (never re-packed)
     *   intrinsic: pattern charts, 96 x 48 a fish, at most 64 a batch, the
     *     whole instance sequence drawn with the uncharted fish off the
     *     target, of the fish whose slots are on both sides of the texture's
     *     32-slot rows and of slot 2048 (draws and slots reported),
     *     against EvoAppearance.decode / flankAt of the original rows (p99.9
     *     <= .002, nothing non-finite)
     *   decoded (the render optimization's cache, when the policy asks for it): the production decoded
     *     texture itself, read back from the GPU as it is (three's own upload of it), every drawn fish's 72
     *     floats at its own slot bit for bit against a fresh EvoAppearance.writeDecoded of its owned row;
     *     asked for but not uploaded fails (res.decoded; o.mutate "decoded": the read at a wrong slot)
     * The probe must upload nothing: one that did would have repaired a
     * missed production upload, and that fails. expected: owned copies
     * {worldEpoch, n, ids, app, body} (EvoOcean.bench.snapshotCopy), which
     * must be the snapshot drawn; absent, that snapshot's own copies.
     * o.mutate "slot": the probes read a wrong slot (each fish's own, xor 1);
     * o.pendingUpload: a production upload left pending (the probe would
     * perform it); both must fail. o.charts: how many fish to chart (24).
     * o.rawWords: the raw words read, in draw order (res.rawWords: n x 64
     * uint32), for the dirty-vs-full reference. A diagnostic: the frame is
     * marked, never part of a timed capture. */
    var probes = [];
    var PROBE_SENTINEL = new Float32Array([-9, -9, -9, -9]);
    var RAW_QUADS = (function () {   /* 16 pixel quads, one a gene texel */
      var pos = new Float32Array(16 * 6 * 3), tx = new Float32Array(16 * 6), Q = [[0, 0], [1, 0], [0, 1], [0, 1], [1, 0], [1, 1]];
      for (var k = 0; k < 16; k++) for (var v = 0; v < 6; v++) { var i = 6 * k + v; pos[3 * i] = Q[v][0]; pos[3 * i + 1] = Q[v][1]; tx[i] = k; }
      return { pos: pos, texel: tx };
    })();
    function appearanceTextureParity(expected, o) {
      return new Promise(function (resolve) {
        var rq = { expected: expected || null, o: o || {}, resolve: resolve };
        rq.timer = setTimeout(function () {
          var i = probes.indexOf(rq);
          if (i >= 0) { probes.splice(i, 1); resolve({ ok: false, error: "no production draw of the appearance fish within 10 s" }); }
        }, 10000);
        probes.push(rq);
      });
    }
    function failProbes(why) {
      var list = probes.splice(0);   /* (in place: the scene reads this array) */
      list.forEach(function (rq) { clearTimeout(rq.timer); rq.resolve({ ok: false, error: why }); });
    }
    function runProbes(s) {
      var appKind = port.appKind(), appDrawn = port.drawn(), appStatus = port.status();
      if (!appDrawn || !appKind || !appKind.drawing()) { failProbes("the appearance fish were not drawn this frame (" + appStatus + ")"); return; }
      var list = probes.splice(0);   /* (in place: the scene reads this array) */
      list.forEach(function (rq) {
        clearTimeout(rq.timer);
        var p;
        try { p = profiler.suspend(function () { return textureProbe(rq, s); }); }
        catch (e) { p = Promise.resolve({ ok: false, error: "probe: " + (e && e.message || e) }); }
        p.then(rq.resolve, function (e) { rq.resolve({ ok: false, error: "probe: " + (e && e.message || e) }); });
      });
    }
    /* the draw indices charted: the owners of the slots on both sides of the
     * texture's 32-slot rows and of slot 2048, of the highest slot, the last
     * draw, then spread (slotOf: each draw's slot, iGeneSlot) */
    function chartPicks(n, want, slotOf) {
      var pick = [], seen = {}, owner = new Map(), top = -1;
      for (var c = 0; c < n; c++) { owner.set(slotOf[c], c); if (slotOf[c] > top) top = slotOf[c]; }
      function add(i) { if (i >= 0 && i < n && !seen[i]) { seen[i] = true; pick.push(i); } }
      [0, 1, 31, 32, 33, 63, 64, 2047, 2048, 2049, top].forEach(function (sl) { if (owner.has(sl)) add(owner.get(sl)); });
      add(n - 1);
      for (var k = 1; pick.length < Math.min(want, n) && k < 64 * want; k++) add(Math.floor((k * 0.6180339887 % 1) * n));
      return pick.sort(function (a, b) { return a - b; });
    }
    function floatTarget(w, h) {
      return new THREE.WebGLRenderTarget(w, h, { type: 1015, format: 1023, minFilter: 1003, magFilter: 1003, generateMipmaps: false,
                                                 depthBuffer: false, stencilBuffer: false, samples: 0 });
    }
    function textureProbe(rq, s) {
      var appKind = /** @type {ParityAppKind} */ (port.appKind()), EA = /** @type {EvoAppearanceApi} */ (port.ea());   /* (runProbes: drawn) */
      var o = rq.o, gl = renderer.getContext(), n = appKind.n, ST = EA.STRIDE, inst = appKind.inst;
      /** @type {{failures: string[], [more: string]: any}} */
      var res = { ok: false, worldEpoch: s.worldEpoch, tick: s.stats ? s.stats[1] : null, fish: n,
                  mutate: o.mutate || "", pendingUpload: !!o.pendingUpload, failures: [] };
      if (!THREE.WebGLRenderTarget) { res.error = "the three bundle has no WebGLRenderTarget (tools/three_bundle)"; return Promise.resolve(res); }
      /* what was drawn: owned copies, before any probe work */
      var drawnIds = Float64Array.from(s.ids.subarray(0, n));
      var exp = rq.expected || { worldEpoch: s.worldEpoch, tick: res.tick, n: n, ids: drawnIds,
                                 app: Float32Array.from(s.app.subarray(0, n * ST)), body: Float32Array.from(s.body.subarray(0, 2 * n)) };
      var why = null;
      if (exp.n !== n) why = "it has " + exp.n + " fish, " + n + " were drawn";
      else if (exp.worldEpoch !== undefined && s.worldEpoch !== undefined && exp.worldEpoch !== s.worldEpoch) why = "world epoch " + exp.worldEpoch + ", drawn " + s.worldEpoch;
      else for (var i = 0; i < n; i++) if (exp.ids[i] !== drawnIds[i]) { why = "draw " + i + " is fish " + exp.ids[i] + ", drawn " + drawnIds[i]; break; }
      if (!why && (!exp.app || exp.app.length < n * ST || !exp.body || exp.body.length < 2 * n)) why = "it has no appearance rows or bodies";
      if (why) { res.error = "the expected snapshot is not the one drawn: " + why; return Promise.resolve(res); }
      var app = exp.app instanceof Float32Array ? exp.app : Float32Array.from(exp.app), body = exp.body;
      var tex = appKind.tex, slotOf = appKind.attrs.iGeneSlot.array;
      var slotNow = Float32Array.from(slotOf.subarray(0, n));   /* each draw's slot as drawn (the attribute changes in later frames) */
      res.texture = { width: tex.image.width, height: tex.image.height, type: tex.type, format: tex.format,
                      internalFormat: tex.internalFormat || "RGBA32F (three: RGBAFormat + FloatType)", capacity: appKind.slots.capacity,
                      drawCapacity: appKind.cap, minFilter: tex.minFilter, magFilter: tex.magFilter, mipmaps: tex.generateMipmaps };
      res.slots = appKind.slots.stats();
      var sh = appKind.shaders, rawVs = sh.probeRawVs, chartVs = sh.probeChartVs;
      if (o.mutate === "slot") {   /* the slot each fish really has, xor 1 (a permutation could equal gl_InstanceID ^ 1) */
        var wrong = GENE_SLOT_GLSL.split(GENE_SLOT_RET).join("return int(iGeneSlot) ^ 1;");
        rawVs = rawVs.split(GENE_SLOT_GLSL).join(wrong); chartVs = chartVs.split(GENE_SLOT_GLSL).join(wrong);
      } else if (o.mutate && o.mutate !== "decoded") { res.error = "unknown mutation " + o.mutate; return Promise.resolve(res); }
      var dmut = o.mutate === "decoded" ? 1 : 0;   /* "decoded": only the decoded cache's read is at the wrong slot (xor 1) */
      var picks = chartPicks(n, o.charts || 24, slotOf), pickSlots = picks.map(function (c) { return slotOf[c]; }), CW = 96, CH = 48, PER = 64, COLS = 8;
      var geos = [], mats = [], rts = [], reads = [], batches = [], err = null, shaderErr = null;
      var keepRT = renderer.getRenderTarget(), keepClear = renderer.autoClear, keepOnErr = renderer.debug.onShaderError;
      var cam = new THREE.PerspectiveCamera(), up0 = geneIO.uploads;
      function geometry() {   /* shares the fish's instance attributes (and their GL buffers) */
        var g = new THREE.InstancedBufferGeometry();
        inst.forEach(function (nm) { g.setAttribute(nm, appKind.attrs[nm]); });
        g.instanceCount = n;
        geos.push(g);
        return g;
      }
      function material(vs, fs, extra) {
        var u = { uGenes: appKind.mat.uniforms.uGenes };   /* the fish material's own uniform: appKind.tex */
        Object.keys(extra).forEach(function (k) { u[k] = extra[k]; });
        var m = new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, uniforms: u, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
        mats.push(m);
        return m;
      }
      function draw(rt, g, m) {
        var mesh = new THREE.Mesh(g, m), sc = new THREE.Scene();
        mesh.frustumCulled = false; sc.add(mesh);
        renderer.setRenderTarget(rt);
        var st = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
        if (st !== gl.FRAMEBUFFER_COMPLETE) throw new Error("the probe's float target is incomplete (" + st + ")");
        renderer.state.buffers.color.setMask(true);
        renderer.state.setScissorTest(false);
        gl.clearBufferfv(gl.COLOR, 0, PROBE_SENTINEL);
        renderer.render(sc, cam);
        renderer.setRenderTarget(rt);
        var b = gl.createBuffer();   /* the target -> a pixel-pack buffer; nothing waits here */
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, b);
        gl.bufferData(gl.PIXEL_PACK_BUFFER, rt.width * rt.height * 16, gl.STREAM_READ);
        gl.readPixels(0, 0, rt.width, rt.height, gl.RGBA, gl.FLOAT, 0);
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
        reads.push(b);
        return { buf: b, w: rt.width, h: rt.height };
      }
      var raw = null;
      if (o.pendingUpload) tex.needsUpdate = true;   /* a production upload left undone */
      try {
        renderer.autoClear = false;
        renderer.debug.onShaderError = function (g, prog, vs, fs) {
          shaderErr = ((g.getShaderInfoLog(vs) || "") + " " + (g.getShaderInfoLog(fs) || "") + " " + (g.getProgramInfoLog(prog) || "")).trim() || "the probe's program did not link";
        };
        /* raw genes: 16 pixels a fish, 512 a row */
        var rawH = Math.ceil(16 * n / GENES_W), rawRT = floatTarget(GENES_W, rawH), rg = geometry();
        rts.push(rawRT);
        rg.setAttribute("position", new THREE.BufferAttribute(RAW_QUADS.pos, 3));
        rg.setAttribute("aTexel", new THREE.BufferAttribute(RAW_QUADS.texel, 1));
        raw = draw(rawRT, rg, material(rawVs, sh.probeRawFs, { uProbeSize: { value: new THREE.Vector2(GENES_W, rawH) } }));
        /* the charts, a batch of at most 64 at a time */
        var cg = geometry(), cell = new THREE.InstancedBufferAttribute(new Float32Array(n * 4), 4);
        cg.setAttribute("position", new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), 3));
        cg.setIndex([0, 1, 2, 2, 1, 3]);
        cg.setAttribute("iCell", cell);
        var cm = material(chartVs, sh.chartFs, { uIntrinsic: { value: 1 } });
        for (var b0 = 0; b0 < picks.length; b0 += PER) {
          var part = picks.slice(b0, b0 + PER), rowsN = Math.ceil(part.length / COLS), A = cell.array;
          for (var q = 0; q < n; q++) { A[4 * q] = 4; A[4 * q + 1] = 4; A[4 * q + 2] = 0; A[4 * q + 3] = 0; }   /* off the target */
          part.forEach(function (c, k) {
            var cx = k % COLS, cy = Math.floor(k / COLS);
            A[4 * c] = -1 + 2 * cx / COLS; A[4 * c + 1] = -1 + 2 * cy / rowsN; A[4 * c + 2] = 2 / COLS; A[4 * c + 3] = 2 / rowsN;
          });
          cell.needsUpdate = true;
          var rt = floatTarget(COLS * CW, rowsN * CH);
          rts.push(rt);
          batches.push({ fish: part, read: draw(rt, cg, cm) });
        }
      } catch (e) { err = e; }
      finally {
        renderer.setRenderTarget(keepRT);
        renderer.autoClear = keepClear;
        renderer.debug.onShaderError = keepOnErr;
      }
      /* the decoded cache's production texture (the render optimization's policy decoded: appKind.decodedStats().texture, three's own upload
       * of it), as the GPU holds it now: read into a pixel-pack buffer here, right after the production draw and every upload it made,
       * and compared below, bit for bit, with a fresh EvoAppearance.writeDecoded of each drawn fish's owned row at the fish's own slot
       * (the texture's floats are slot x 72, row-major). Asked for but not uploaded fails; not asked for (the reference pipeline, the
       * policy off) is not checked. A diagnostic: nothing here uploads. */
      var dread = null, dst = appKind.decodedStats();
      res.decoded = { checked: false, reason: dst.live && dst.wanted ? "" : "the decoded cache is not asked for" };
      if (!err && !shaderErr && dst.live && dst.wanted) {
        try {
          var dpr = renderer.properties.get(dst.texture), dgl = dpr && dpr.__webglTexture;
          if (!dst.ready || !dgl) { res.decoded.reason = !dst.ready ? "the decoded cache is asked for but not uploaded (needFull)" : "the decoded texture has no GPU copy"; res.failures.push(res.decoded.reason); }
          else {
            var dW = dst.texture.image.width, dH = dst.texture.image.height, keepFB = gl.getParameter(gl.FRAMEBUFFER_BINDING), dfb = gl.createFramebuffer();
            try {
              gl.bindFramebuffer(gl.FRAMEBUFFER, dfb);
              gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, dgl, 0);
              var dfs = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
              if (dfs !== gl.FRAMEBUFFER_COMPLETE) throw new Error("the decoded texture's framebuffer is incomplete (" + dfs + ")");
              var db = gl.createBuffer();
              gl.bindBuffer(gl.PIXEL_PACK_BUFFER, db);
              gl.bufferData(gl.PIXEL_PACK_BUFFER, dW * dH * 16, gl.STREAM_READ);
              gl.readPixels(0, 0, dW, dH, gl.RGBA, gl.FLOAT, 0);
              reads.push(db);
              dread = { buf: db, w: dW, h: dH };
            } finally {
              gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
              gl.bindFramebuffer(gl.FRAMEBUFFER, keepFB);
              gl.deleteFramebuffer(dfb);
            }
          }
        } catch (e) { res.decoded.reason = "decoded readback: " + (e && e.message || e); res.failures.push(res.decoded.reason); }
      }
      res.extraUploads = geneIO.uploads - up0;
      var sync = err || shaderErr ? null : gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
      if (sync) gl.flush();
      function cleanup() {
        gl.bindBuffer(gl.COPY_READ_BUFFER, null);
        reads.forEach(function (b) { gl.deleteBuffer(b); });
        if (sync) gl.deleteSync(sync);
        geos.forEach(function (g) { inst.forEach(function (nm) { g.deleteAttribute(nm); }); g.dispose(); });   /* the fish keep theirs */
        mats.forEach(function (m) { m.dispose(); }); rts.forEach(function (t) { t.dispose(); });
      }
      if (err || shaderErr) { cleanup(); res.error = shaderErr ? "probe shader: " + shaderErr : "probe: " + (err.message || err); return Promise.resolve(res); }
      return fenceDone(gl, sync, 10000).then(function (why) {
        if (why) { cleanup(); res.error = why; return res; }
        function fetch(rd) {
          var px = new Float32Array(rd.w * rd.h * 4);
          gl.bindBuffer(gl.COPY_READ_BUFFER, rd.buf);
          gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, px);
          return px;
        }
        /* raw: the genes' bit patterns, then the zero */
        var rp = fetch(raw), gotU = new Uint32Array(rp.buffer), appU = new Uint32Array(app.buffer, app.byteOffset, n * ST);
        /** @type {{compared: number, mismatches: number, paddingMismatches: number, nonFinite: number, examples: object[]}} */
        var R = { compared: n * 64, mismatches: 0, paddingMismatches: 0, nonFinite: 0, examples: [] };
        for (var c = 0; c < n; c++) for (var j = 0; j < 64; j++) {
          var gi = 64 * c + j;
          if (!Number.isFinite(rp[gi])) R.nonFinite++;
          if (j < 63) {
            if (gotU[gi] !== appU[ST * c + j]) {
              R.mismatches++;
              if (R.examples.length < 6) R.examples.push({ draw: c, id: exp.ids[c], gene: j, want: app[ST * c + j], got: rp[gi] });
            }
          } else if (gotU[gi] !== 0) R.paddingMismatches++;
        }
        res.rawGenes = R;
        if (dread) {   /* the decoded cache's texture as the GPU held it: each drawn fish's 72 floats against a fresh decode of its row */
          var dp = fetch(dread), dU = new Uint32Array(dp.buffer), DF = EA.DECODED_FLOATS, tmp = new Float32Array(DF), tU = new Uint32Array(tmp.buffer);
          /** @type {{checked: boolean, fish: number, floats: number, mismatches: number, nonFinite: number, texels: string, mutate: string, examples: object[], reason?: string}} */
          var DR = { checked: true, fish: n, floats: n * DF, mismatches: 0, nonFinite: 0, texels: dread.w + "x" + dread.h, mutate: dmut ? "decoded" : "", examples: [] };
          for (var cd = 0; cd < n; cd++) {
            EA.writeDecoded(app.subarray(ST * cd, ST * cd + ST), tmp, 0);
            var base = (slotNow[cd] ^ dmut) * DF;
            if (base + DF > dp.length) { DR.mismatches += DF; if (DR.examples.length < 6) DR.examples.push({ draw: cd, slot: slotNow[cd], why: "past the texture" }); continue; }
            for (var jd = 0; jd < DF; jd++) {
              if (!Number.isFinite(dp[base + jd])) DR.nonFinite++;
              if (dU[base + jd] !== tU[jd]) { DR.mismatches++; if (DR.examples.length < 6) DR.examples.push({ draw: cd, id: exp.ids[cd], slot: slotNow[cd], float: jd, want: tmp[jd], got: dp[base + jd] }); }
            }
          }
          res.decoded = DR;
          if (DR.mismatches) res.failures.push(DR.mismatches + " decoded cache mismatches (the GPU copy against a fresh decode)");
          if (DR.nonFinite) res.failures.push(DR.nonFinite + " non-finite decoded cache floats");
        }
        if (o.rawWords) res.rawWords = gotU.slice(0, n * 64);   /* (tests: the words as read, in draw order; dirty vs full) */
        /* the charts against the CPU mirror of the original rows */
        var errs = [], nonFinite = 0, over = 0, maxErr = 0, worst = "", out = [0, 0, 0];
        batches.forEach(function (bt) {
          var px = fetch(bt.read), TW = bt.read.w;
          bt.fish.forEach(function (c, k) {
            var size = body[2 * c], elong = body[2 * c + 1];
            var lam = Math.fround(20 * size * elong / Math.fround(4.6 * bodyScale(size)));   /* fillApp's iX.z */
            var D = EA.decode(app.subarray(ST * c, ST * c + ST), lam), x0 = (k % COLS) * CW, y0 = Math.floor(k / COLS) * CH;
            for (var jj = 0; jj < CH; jj++) for (var ii = 0; ii < CW; ii++) {
              EA.flankAt(D, (ii + 0.5) / CW, (jj + 0.5) / CH, out);
              var p = ((y0 + jj) * TW + x0 + ii) * 4;
              if (!Number.isFinite(px[p]) || !Number.isFinite(px[p + 1]) || !Number.isFinite(px[p + 2])) { nonFinite++; continue; }
              var e = Math.max(Math.abs(px[p] - out[0]), Math.abs(px[p + 1] - out[1]), Math.abs(px[p + 2] - out[2]));
              errs.push(e); if (e > 0.002) over++;
              if (e > maxErr) { maxErr = e; worst = "draw " + c + " (fish " + exp.ids[c] + ") u " + ((ii + 0.5) / CW).toFixed(3) + " v " + ((jj + 0.5) / CH).toFixed(3); }
            }
          });
        });
        cleanup();
        var E = Float64Array.from(errs).sort();
        res.intrinsic = { fish: picks.length, draws: picks, slots: pickSlots, ids: picks.map(function (c) { return exp.ids[c]; }), samples: E.length,
                          p99: E.length ? E[Math.floor(E.length * 0.99)] : null, p999: E.length ? E[Math.floor(E.length * 0.999)] : null,
                          maxErr: maxErr, over002: E.length ? over / E.length : null, nonFinite: nonFinite, worst: worst };
        if (res.extraUploads) res.failures.push("the probe uploaded the gene texture " + res.extraUploads + "x (a production upload was pending)");
        if (R.mismatches) res.failures.push(R.mismatches + " raw gene mismatches");
        if (R.paddingMismatches) res.failures.push(R.paddingMismatches + " padding mismatches");
        if (R.nonFinite) res.failures.push(R.nonFinite + " non-finite raw components");
        if (nonFinite) res.failures.push(nonFinite + " non-finite chart pixels");
        if (!E.length || !(res.intrinsic.p999 <= 0.002)) res.failures.push("chart p99.9 " + res.intrinsic.p999 + " > .002");
        if (tex.type !== 1015 || tex.format !== 1023) res.failures.push("the gene texture is not RGBA float");
        res.ok = res.failures.length === 0;
        return res;
      });
    }
    return { testFaults: testFaults, probes: probes, failProbes: failProbes, runProbes: runProbes,
             appearanceParity: appearanceParity, appearanceTextureParity: appearanceTextureParity };
  }

  /* ---------------- the M2a body plan: the renderer's rest law (GPU) == C++ ----------------
   * bodyPlanVertexCheck(gl, EA, fixture, opts): the production GLSL of the
   * deformable template (EA.GLSL.COMMON + GENES + MORPH: mDecode, mBuild),
   * through transform feedback, at the body plan's CANONICAL samples
   * (src/ocean/body_plan.hpp sampleCoords: the full rings, 12 caudal and 16
   * fin intervals, 16 rim points an eye, 6 barbel segments; fixture.samples:
   * [a0, a1, a2, a3, part, side] each) and at the renderer's rest settings
   * (time 0, no wag, no width floor), for every fixture body (its 63 genes and
   * lambda), against the C++ law's rest points in body radii (body.rest: 3
   * floats a sample, from the Ocean module's oc_body_rest: the Wasm build of
   * the law, which the caller also holds to the native digest). The genes go
   * into a 512-wide RGBA32F texture, 16 texels a body, at slots from slotMap
   * (identity, permuted, sparse: the texture's row crossings 31 / 32, 63 / 64,
   * 2047 / 2048), the layout GENES' fetchGenes reads. Every output must be
   * finite, then within BODY_TOL of the C++ point (per part, the worst
   * reported). GPU outputs never reach the simulation. opts.mutate plants a
   * fault in the GLSL that the check must catch: "radius" (the depth law),
   * "root" (a paired fin's root moved off its facet), "caudalClip" (the chord
   * cap raised to 4 R). */
  var BODY_TOL = { geo: 0.002 };   /* body radii; locked before any fixture was recorded */
  var BODY_MUT = {
    radius: ["M.depth * 0.84 * mPw(", "M.depth * 0.80 * mPw("],
    root: ["vec3 root = mFacet(M, t, thr, side);", "vec3 root = mFacet(M, t + 0.03, thr, side);"],
    caudalClip: ["min(3.00000000, 2.0 * M.cA", "min(4.00000000, 2.0 * M.cA"]
  };
  var BODY_PARTS = ["body", "caudal", "dorsal", "pectoral", "eye", "anal", "pelvic", "barbel"];
  /** @returns {Promise<any>} */
  function bodyPlanVertexCheck(gl, EA, fixture, opts) {
    opts = opts || {};
    if (!EA || !EA.GLSL || !EA.GLSL.MORPH) return Promise.resolve({ error: "web/ocean_appearance.js not loaded" });
    if (!fixture || !fixture.samples || !fixture.bodies || !fixture.bodies.length) return Promise.resolve({ error: "no fixture" });
    var morph = EA.GLSL.MORPH;
    if (opts.mutate) {
      var pm = plant(morph, opts.mutate, BODY_MUT);
      if (pm.error) return Promise.resolve({ error: pm.error });
      morph = pm.src;
    }
    var vs = VS3 + EA.GLSL.COMMON + "\n" + EA.GLSL.GENES + "\n" + morph + "\n" + [
      "attribute vec4 aT;", "attribute vec4 aPat;", "attribute float aLam;", "attribute float aSlot;",
      "out vec3 vGeo;",
      "void main() {",
      "  fetchGenes(int(aSlot + 0.5));",
      "  Morph M = mDecode(aLam);",
      "  vec3 geo, mat; float mar;",
      "  mBuild(M, aT, aPat, 0.0, 0.0, 0.0, geo, mat, mar);",
      "  vGeo = geo;",
      "  gl_Position = vec4(0.0, 0.0, 0.0, 1.0); gl_PointSize = 1.0;",
      "}"].join("\n");
    var fs = "#version 300 es\nprecision highp float;\nout vec4 pcOut;\nvoid main() { pcOut = vec4(0.0); }\n";
    var prog;
    try { prog = compileProgram(gl, vs, fs, ["vGeo"]); }
    catch (e) { return Promise.resolve({ error: e.message || String(e) }); }
    var S = fixture.samples, ns = S.length, bodies = fixture.bodies, nb = bodies.length, N = ns * nb;
    var slots = slotMap(opts.slotMap, nb), top = 0, c, i, k;
    for (c = 0; c < nb; c++) if (slots[c] > top) top = slots[c];
    var W = 512, rowsTex = Math.ceil(16 * (top + 1) / W), T = new Float32Array(W * rowsTex * 4);
    for (c = 0; c < nb; c++) {
      var g = bodies[c].genes;
      if (!g || g.length !== EA.STRIDE) { gl.deleteProgram(prog); return Promise.resolve({ error: "fixture body " + c + " has no 63 genes" }); }
      for (k = 0; k < EA.STRIDE; k++) T[4 * 16 * slots[c] + k] = g[k];
    }
    var aT = new Float32Array(4 * N), aPat = new Float32Array(4 * N), aLam = new Float32Array(N), aSlot = new Float32Array(N);
    for (c = 0; c < nb; c++) for (i = 0; i < ns; i++) {
      var v = c * ns + i, s = S[i];
      aT[4 * v] = s[0]; aT[4 * v + 1] = s[1]; aT[4 * v + 2] = s[2]; aT[4 * v + 3] = s[3];
      aPat[4 * v] = s[4]; aPat[4 * v + 2] = s[5];
      aLam[v] = bodies[c].lambda; aSlot[v] = slots[c];
    }
    var tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, W, rowsTex, 0, gl.RGBA, gl.FLOAT, T);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.useProgram(prog);
    var ringT = new Float32Array(16), RINGS = EA.LODS.full.rings;
    for (k = 0; k < 16; k++) ringT[k] = k < RINGS.length ? RINGS[k] : 0;
    gl.uniform1fv(gl.getUniformLocation(prog, "uRingT[0]") || gl.getUniformLocation(prog, "uRingT"), ringT);
    gl.uniform1i(gl.getUniformLocation(prog, "uRingN"), RINGS.length);
    gl.uniform1f(gl.getUniformLocation(prog, "uHalfRing"), EA.LODS.full.half);
    gl.uniform1i(gl.getUniformLocation(prog, "uGenes"), 0);
    var bufs = [], vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    function attr(name, data, size) {
      var loc = gl.getAttribLocation(prog, name);
      if (loc < 0) return;
      var b = gl.createBuffer(); bufs.push(b);
      gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    }
    attr("aT", aT, 4); attr("aPat", aPat, 4); attr("aLam", aLam, 1); attr("aSlot", aSlot, 1);
    var out = gl.createBuffer(); bufs.push(out);
    gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, out);
    gl.bufferData(gl.TRANSFORM_FEEDBACK_BUFFER, N * 3 * 4, gl.STREAM_READ);
    gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, null);
    var tfo = gl.createTransformFeedback();
    gl.enable(gl.RASTERIZER_DISCARD);
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, tfo);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, out);
    gl.beginTransformFeedback(gl.POINTS);
    gl.drawArrays(gl.POINTS, 0, N);
    gl.endTransformFeedback();
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
    gl.disable(gl.RASTERIZER_DISCARD);
    gl.bindVertexArray(null);
    var sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    gl.flush();
    gl.useProgram(null); gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindTexture(gl.TEXTURE_2D, null);
    function cleanup() {
      gl.bindBuffer(gl.COPY_READ_BUFFER, null);
      gl.deleteSync(sync); gl.deleteTransformFeedback(tfo); gl.deleteTexture(tex); gl.deleteProgram(prog); gl.deleteVertexArray(vao);
      bufs.forEach(function (b) { gl.deleteBuffer(b); });
    }
    return fenceDone(gl, sync, 10000).then(function (why) {
      if (why) { cleanup(); return { error: why }; }
      var data = new Float32Array(N * 3);
      gl.bindBuffer(gl.COPY_READ_BUFFER, out);
      gl.getBufferSubData(gl.COPY_READ_BUFFER, 0, data);
      cleanup();
      var res = { bodies: nb, samples: ns, vertices: N, slotMap: opts.slotMap || "identity", maxSlot: top, texRows: rowsTex, mutate: opts.mutate || "",
                  tol: BODY_TOL, nonFinite: 0, missing: 0, worst: 0, worstAt: "", parts: {}, ok: true };
      BODY_PARTS.forEach(function (p) { res.parts[p] = { n: 0, worst: 0 }; });
      for (c = 0; c < nb; c++) {
        var rest = bodies[c].rest;
        if (!rest || rest.length !== 3 * ns) { res.missing++; continue; }
        for (i = 0; i < ns; i++) {
          var o = 3 * (c * ns + i), part = BODY_PARTS[S[i][4]] || "?", P = res.parts[part] || (res.parts[part] = { n: 0, worst: 0 });
          var gx = data[o], gy = data[o + 1], gz = data[o + 2];
          P.n++;
          if (!isFinite(gx) || !isFinite(gy) || !isFinite(gz)) { res.nonFinite++; continue; }
          var e = Math.max(Math.abs(gx - rest[3 * i]), Math.abs(gy - rest[3 * i + 1]), Math.abs(gz - rest[3 * i + 2]));
          if (e > P.worst) P.worst = e;
          if (e > res.worst) { res.worst = e; res.worstAt = (bodies[c].name || "body " + c) + " sample " + i + " (" + part + ")"; }
        }
      }
      res.ok = res.nonFinite === 0 && res.missing === 0 && res.worst <= BODY_TOL.geo;
      return res;
    });
  }

  /** @type {EvoOceanSceneParityApi} */
  var API = {
    bind: bind, attach: attach,
    appearancePathCheck: appearancePathCheck, appearanceVertexCheck: appearanceVertexCheck, appearanceFragmentCheck: appearanceFragmentCheck,
    bodyPlanVertexCheck: bodyPlanVertexCheck, BODY_TOL: BODY_TOL, BODY_MUT: Object.keys(BODY_MUT)
  };
  root.EvoOceanSceneParity = API;
})(typeof window !== "undefined" ? window : globalThis);
