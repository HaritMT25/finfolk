// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the fish's materials, one binder (window.EvoOceanMaterials).
 *
 * Structure pass, step 4b (PR #57's "Next: 4b, the one material binder"). The scene's fish kinds
 * (web/ocean_scene.js: the appearance fish, the legacy fish, the predators) draw the materials this
 * binder makes and assigns; none of them makes or swaps its own:
 *   - a material cache. A material's key is the program ABI (EvoOceanShaders.ABI), the kind (KINDS:
 *     app, the appearance fish's body and barbels; fish, the legacy fish; pred, the predators; face, a
 *     Look's attached pass on the predators, #47's faces), the pass (body, shadow, litSkip), the kind's
 *     declared attribute layout (LAYOUTS, with any claims), the variant (0 plain, 1 the swim polish),
 *     the Look (the faces: with a digest of their GLSL and options), and the enabled features' ids and
 *     versions stage by stage (the vertex and fragment stages may differ: under Reef, [swimPolish.full,
 *     reef.fish] / [reef.fish]). Uniform values are not in it: a kind's materials share its uniforms
 *     (the scene's objects, so setClarity, setLight and the rest reach every variant; a Look's merged
 *     with them into an object of the binder's, the Look's own objects by identity in its keys: the
 *     binder never writes a uniform object). Keys whose material would be identical (the
 *     legacy fish's and the predators': the same programs, options and uniforms) share one material
 *     object, as the scene's two kinds shared theirs before the binder. Each program is
 *     EvoOceanShaders.program(name, parts, the stage's features), so a feature that is not enabled
 *     contributes no GLSL
 *   - one writer of a fish mesh's material (bind): the scene's kinds commit the variant settle() chose
 *     (its prewarm and hysteresis unchanged) and the binder assigns the material
 *   - the lit fish's split is a feature (LIT_SKIP_FEATURE): it appends the skip to app.pose with order
 *     -1, so it is the first line of main(), byte for byte the old text insert litSkip(vs)
 *   - the declared attribute layouts (LAYOUTS, layout()): each kind's instance attributes, component
 *     by component, as the scene's fills write them, the swim pose's reserved (the appearance fish's
 *     iBody.w, the legacy fish's and the predators' iX.y). A Look claims a spare component (a feature
 *     set's claims), never a reserved or a used one; a claim is part of the key
 *   - atomic activation (activate(set)): every reachable variant of a new feature set (each defined
 *     kind's passes and variants, and the set's attached pass) is assembled, then compiled (compiler():
 *     three's compile, then each program checked linked and runnable), before the set takes effect; an
 *     assembly or compile failure keeps the previous set, and drops what it made. On success the
 *     materials of the sets it replaces are freed (the base set's stay, and the set replaced right
 *     now, for one switch: off and on again relinks its programs). A kind defined while a Look is
 *     active (the appearance fish, on their first snapshot) draws under the base set until its own
 *     activation of the Look compiled
 *   - lazy assembly: a variant's programs are assembled when it is first drawn, warmed or activated,
 *     never as the scripts load. An assembly error (say a scan's false positive in the polish) falls
 *     back to the plain programs (variant 0, no feature), said once on the console and kept in
 *     state(): the plain fish are always drawn (material() throws if even they cannot be: the scene's
 *     "unavailable" path, never three's default shader)
 * The material objects are made (reserved, prepare) where the scene made its own before the binder,
 * in the same order and as many (the legacy kinds sharing theirs), so three's draw order (opaque
 * objects sort by material id, then depth, within a render order) is main's; their GLSL is assembled
 * later, on first use. A set's keys are worked out once (features() runs once a set per stage).
 *
 * A feature set (activate): {look: "reef", features(q) -> ids, attach: {face: {decl, body, fs,
 * uniforms, options, geometry}}, uniforms: {kind: {name: {value}}}, claims: {kind: {component:
 * owner}}}. features gets q = {kind, pass, stage, variant, base} (base: the swim polish's ids for the
 * variant: the full polish on the bodies' stages, the lite one on a shadow's vertex stage) and gives
 * the stage's feature ids (absent: base). The faces' vertex stage is always the predators' body's
 * (the predators' vertex features: a feature that replaces fish.world or reads the pose on the
 * predators must target fish.attach.vs too, or the set is refused), so the faces swim with the body.
 * activate(null): back to no Look.
 *
 * Display only, like everything the scene draws: nothing here reaches the simulation. */
(function (root) {
  root.EvoOceanMaterials = null;   /* registered at the end: a throw on the way leaves null (the scene: "failed to run") */
  var SHADERS = root.EvoOceanShaders;
  if (!SHADERS) return;   /* (the scene names ocean_shaders.js missing, or failed to run, not this one) */
  var SH = SHADERS, PT = SH.parts, POLISH = SH.POLISH;
  var hasOwn = Object.prototype.hasOwnProperty;
  /** @param {string} m */
  function err(m) { return new Error("EvoOceanMaterials: " + m); }
  /** @param {any} x @returns {string} */
  function msg(x) { return String(x && x.message || x); }

  /* ---- the lit fish's split, a feature ----
   * In the split's main draw a lit appearance fish's highlight (iBody.z) is LIT_SKIP, and the plain
   * body program with this feature puts all its vertices on one point past the far plane first thing in
   * main(), before any gene fetch (EvoOceanShaders.LIT_SKIP_GLSL). Registered once, as this file loads */
  var LIT_SKIP_FEATURE = "scene.litSkip";
  SH.feature({ id: LIT_SKIP_FEATURE, abi: SH.ABI, targets: ["app.body.vs"], order: -1, append: { "app.pose": SH.LIT_SKIP_GLSL } });

  /* ---- the declared attribute layouts ----
   * Each kind's instance attributes, component by component, as the scene's fills write them
   * (fillApp, fillFish, fillPreds), and its template's attributes. The swim pose's component is
   * reserved: written only while the polish is drawn (POSE0 or 0 otherwise), read only by the polish's
   * pose slot (poseOf(iBody.w), poseOf(iX.y)). SPARE components are written 0 and read by no program:
   * the only ones a Look may claim */
  var LAYOUT_ABI = 1, SPARE = "spare (0)", XYZW = ["x", "y", "z", "w"];
  var POSE_DOC = "the swim pose, packed (web/ocean_pose.js posePack): reserved for the polish's pose slot";
  var SPINE = {
    iA: ["spine 0 x", "spine 0 y", "spine 1 x", "spine 1 y"],
    iB: ["spine 2 x", "spine 2 y", "spine 3 x", "spine 3 y"],
    iC: ["spine 4 x", "spine 4 y", "spine 5 x", "spine 5 y"]
  };
  /** @type {Object<string, { template: string[], pose: string, attributes: Object<string, string[]> }>} */
  var LAYOUT_SPECS = {
    app: { template: ["aT", "aPattern"], pose: "iBody.w", attributes: {
      iA: SPINE.iA, iB: SPINE.iB, iC: SPINE.iC,
      iBody: ["body radius", "height (three Y)", "highlight (1 selected, .5 hover; the split's LIT_SKIP)", POSE_DOC],
      iX: ["pitch (vz, as tan)", "tail-beat phase", "lambda (body length / radius)", "family / brain colour, 0xRRGGBB"],
      iGeneSlot: ["the fish's gene slot (web/ocean_appearance_slots.js)"] } },
    fish: { template: ["part"], pose: "iX.y", attributes: {
      iA: SPINE.iA, iB: SPINE.iB, iC: SPINE.iC,
      iCol: ["red", "green", "blue", "tail-beat phase"],
      iBody: ["body radius", "height (three Y)", "highlight (1 selected, .5 hover)", "ember (0: a fish)"],
      iX: ["pitch (vz, as tan)", POSE_DOC, SPARE, SPARE] } },
    pred: { template: ["part"], pose: "iX.y", attributes: {
      iA: SPINE.iA, iB: SPINE.iB, iC: SPINE.iC,
      iCol: ["red", "green", "blue", "tail-beat phase"],
      iBody: ["body radius (fuller when fed)", "height (three Y)", "highlight (0)", "ember (1 hunting)"],
      iX: ["pitch (vz, as tan)", POSE_DOC, SPARE, SPARE] } }
  };
  /** A kind's declared layout, with a Look's claims of spare components (owner by component, as
   * "iX.z"; a scalar attribute's one component is its name). Throws for a reserved, a used or an
   * unknown component. @param {string} kind @param {Object<string, string>} [claims] @returns {AttributeLayout} */
  function layout(kind, claims) {
    if (!hasOwn.call(LAYOUT_SPECS, kind)) throw err("no layout for kind " + kind + " (the layouts: " + Object.keys(LAYOUT_SPECS).join(", ") + ")");
    var s = LAYOUT_SPECS[kind];
    /** @type {Object<string, readonly string[]>} */
    var attributes = {};
    /** @type {Object<string, string>} */
    var reserved = {}, used = {}, cl = {};
    /** @type {string[]} */
    var spare = [], ids = [];
    Object.keys(s.attributes).forEach(function (a) {
      var comps = s.attributes[a];
      attributes[a] = Object.freeze(comps.slice());
      comps.forEach(function (doc, i) {
        var c = comps.length === 1 ? a : a + "." + XYZW[i];
        if (c === s.pose) reserved[c] = POLISH.lite + " / " + POLISH.full + " (the swim pose)";
        else if (doc === SPARE) spare.push(c);
        else used[c] = doc;
      });
    });
    var want = claims || {};
    Object.keys(want).sort().forEach(function (c) {
      var owner = want[c];
      if (typeof owner !== "string" || !owner) throw err(kind + ": a claim of " + c + " needs its owner (a feature or Look id)");
      if (hasOwn.call(reserved, c)) throw err(kind + ": " + c + " is reserved for " + reserved[c] + "; " + owner + " cannot claim it");
      if (hasOwn.call(used, c)) throw err(kind + ": " + c + " is the scene's (" + used[c] + "); " + owner + " cannot claim it");
      if (spare.indexOf(c) < 0) throw err(kind + ": " + c + " is not a component of its layout (spare: " + spare.join(", ") + "); " + owner + " cannot claim it");
      cl[c] = owner; ids.push(c + "=" + owner);
    });
    return Object.freeze({ id: kind + "/" + LAYOUT_ABI + (ids.length ? "+" + ids.join("+") : ""), kind: kind, template: Object.freeze(s.template.slice()),
                           attributes: Object.freeze(attributes), reserved: Object.freeze(reserved), used: Object.freeze(used),
                           spare: Object.freeze(spare.filter(function (c) { return !hasOwn.call(cl, c); })), claims: Object.freeze(cl), pose: s.pose });
  }
  /** @type {Object<string, AttributeLayout>} */
  var LAYOUTS = { app: layout("app"), fish: layout("fish"), pred: layout("pred") };
  Object.freeze(LAYOUTS);

  /* ---- the kinds, their passes ----
   * family: the programs a kind's passes draw (app: app.body.vs / app.body.fs, the shadow app.shadow.vs
   * with SHADOW_FS; fish: fish.vs / fish.fs, the shadow fish.shadow.vs with SHADOW_FS; attach:
   * fish.attach.vs with the Look's own fragment stage). The litSkip pass is the body's with the skip */
  var PASSES = Object.freeze(["body", "shadow", "litSkip"]);
  var VARIANTS = Object.freeze([0, 1]);
  /** @type {Object<string, MaterialKindSpec>} */
  var KINDS = {
    app: Object.freeze({ family: "app", layout: "app", passes: Object.freeze(["body", "shadow", "litSkip"]),
                         doc: "the appearance fish's body and barbels (one program; two meshes) and their shadow; litSkip: the split's main draw" }),
    fish: Object.freeze({ family: "fish", layout: "fish", passes: Object.freeze(["body", "shadow"]), doc: "the legacy fish (no appearance genome) and their shadow" }),
    pred: Object.freeze({ family: "fish", layout: "pred", passes: Object.freeze(["body", "shadow"]), doc: "the predators and their shadow" }),
    face: Object.freeze({ family: "attach", layout: "pred", passes: Object.freeze(["body"]),
                          doc: "a Look's attached pass on the predators' instances (#47's faces): fish.attach.vs, posed with the predators' vertex features" })
  };
  Object.freeze(KINDS);

  /* ---- a feature set ---- */
  /** a short digest of a text (FNV-1a, 32 bits, hex): the faces' GLSL and options in their key @param {string} s */
  function digest(s) {
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return ("0000000" + h.toString(16)).slice(-8);
  }
  /** @param {MaterialSetSpec | null | undefined} spec @returns {MaterialSet} */
  function normalize(spec) {
    if (spec === null || spec === undefined) return Object.freeze({ look: "", features: null, attach: null, uniforms: null, layouts: LAYOUTS, faceDigest: "" });
    if (typeof spec !== "object") throw err("a feature set is an object: {look, features, attach, uniforms, claims}");
    var look = spec.look;
    if (typeof look !== "string" || !/^[A-Za-z_][\w.-]*$/.test(look)) throw err("a feature set needs its Look's id (look: \"reef\")");
    if (spec.features !== undefined && typeof spec.features !== "function") throw err(look + ": features is a function of {kind, pass, stage, variant, base} giving the stage's feature ids");
    /** @type {{ face: MaterialAttach } | null} */
    var attach = null;
    if (spec.attach && spec.attach.face) {
      var a = spec.attach.face;
      ["decl", "body", "fs"].forEach(function (k) { if (typeof (/** @type {any} */ (a))[k] !== "string") throw err(look + ": its face pass needs " + k + " (GLSL)"); });
      attach = { face: a };
    }
    /** @type {Object<string, AttributeLayout>} */
    var layouts = {};
    var claims = spec.claims || {};
    Object.keys(claims).forEach(function (k) { if (!hasOwn.call(LAYOUTS, k)) throw err(look + ": claims for an unknown kind " + k); });
    Object.keys(LAYOUTS).forEach(function (k) { layouts[k] = hasOwn.call(claims, k) ? layout(k, claims[k]) : LAYOUTS[k]; });
    /* the faces' GLSL and material options, digested into their key: the same Look id with other faces is another material */
    var fd = "";
    if (attach) {
      var o = /** @type {Object<string, any>} */ (attach.face.options || {});
      fd = digest(JSON.stringify([attach.face.decl, attach.face.body, attach.face.fs, Object.keys(o).sort().map(function (k) { return [k, o[k]]; })]));
    }
    return Object.freeze({ look: look, features: spec.features || null, attach: attach, uniforms: spec.uniforms || null, layouts: Object.freeze(layouts), faceDigest: fd });
  }
  /** @param {string[]} ids @returns {string[]} one of each, sorted (the assembler's order is (order, id) whatever the list's) */
  function canon(ids) {
    /** @type {string[]} */
    var o = [];
    ids.forEach(function (id) { if (o.indexOf(id) < 0) o.push(id); });
    return o.sort();
  }
  /** a stage's feature ids under a set: the swim polish's for the variant (base), the set's choice (noSet: not asked), then the
   * pass's own (the skip)
   * @param {MaterialSet} set @param {string} kind @param {string} pass @param {"vs" | "fs"} stage @param {number} variant
   * @param {boolean} [noSet] @returns {string[]} */
  function featuresOf(set, kind, pass, stage, variant, noSet) {
    if (kind === "face") {
      /* the faces: the predators' vertex features, whatever the set says of the faces */
      var vs = featuresOf(set, "pred", "body", "vs", variant, noSet);
      vs.forEach(function (id) {
        var f = SH.featureOf(id);
        if (f && (hasOwn.call(f.replace, "fish.world") || hasOwn.call(f.append, "fish.pose")) && f.targets.indexOf("fish.attach.vs") < 0)
          throw err("feature " + id + " poses the predators (fish.world / fish.pose) but does not target fish.attach.vs: the faces would not swim with the body");
      });
      return stage === "vs" ? vs : [];
    }
    if (pass === "shadow" && stage === "fs") return [];   /* SHADOW_FS: no slots */
    /* the swim polish: the full one on the bodies' stages, the lite one on a shadow's vertex stage (a shadow shows neither
     * the fold nor the lag: main's SHADOW_VS[1] and app(true).shadowVs; the full one there would give the plain appearance
     * shadow, as it does not target app.shadow.vs) */
    /** @type {string[]} */
    var base = variant === 1 ? [pass === "shadow" ? POLISH.lite : POLISH.full] : [];
    var ids = set.features && !noSet ? set.features({ kind: kind, pass: pass === "litSkip" ? "body" : pass, stage: stage, variant: variant, base: base.slice() }) : base;
    if (!Array.isArray(ids) || ids.some(function (x) { return typeof x !== "string" || !x; }))
      throw err(set.look + ": its features for " + kind + " " + pass + " " + stage + " variant " + variant + " are not a list of feature ids");
    ids = ids.slice();
    if (pass === "litSkip" && stage === "vs") {
      /* the skip first in main(), before any gene fetch: no feature may append to app.pose ahead of it (order -1, then id) */
      ids.forEach(function (id) {
        var f = SH.featureOf(id);
        if (f && hasOwn.call(f.append, "app.pose") && (f.order < -1 || (f.order === -1 && id < LIT_SKIP_FEATURE)))
          throw err("feature " + id + " appends to app.pose ahead of the split's skip (" + LIT_SKIP_FEATURE + ", order -1): the skip must come first");
      });
      ids.push(LIT_SKIP_FEATURE);
    }
    return canon(ids);
  }
  /** @param {string[]} ids */
  function idsKey(ids) {
    return ids.length ? ids.map(function (id) { var f = SH.featureOf(id); return id + "@" + (f ? f.version : "?"); }).join("+") : "-";
  }
  /** the reachable (kind, pass, variant)s of these kinds, pass by pass, variant by variant, kind by kind (the scene's order of
   * old: plain, then polished; body, then shadow); the litSkip pass only plain (the split's main draw)
   * @param {MaterialSet} set @param {string[]} kinds @returns {{ kind: string, pass: string, variant: number }[]} */
  function reachable(set, kinds) {
    /** @type {{ kind: string, pass: string, variant: number }[]} */
    var out = [];
    PASSES.forEach(function (pass) {
      VARIANTS.forEach(function (v) {
        kinds.forEach(function (k) {
          if (!hasOwn.call(KINDS, k)) throw err("unknown kind " + k + " (the kinds: " + Object.keys(KINDS).join(", ") + ")");
          if (KINDS[k].passes.indexOf(pass) < 0 || (pass === "litSkip" && v !== 0) || (k === "face" && !set.attach)) return;
          out.push({ kind: k, pass: pass, variant: v });
        });
      });
    });
    return out;
  }

  /* the kinds' names, for the console (and their possessives) */
  /** @type {Object<string, string>} */
  var KIND_NAMES = { app: "appearance fish", fish: "legacy fish", pred: "predators", face: "predators' faces" };
  /** @type {Object<string, string>} */
  var KIND_OF = { app: "appearance fish's", fish: "legacy fish's", pred: "predators'", face: "predators' faces'" };

  /** The binder: the scene's one (create(), once a renderer). deps: THREE (its ShaderMaterial and constants), compile (the
   * activation's compile: a Promise of {ok, error}; compiler() makes the scene's), warn (the console's).
   * A cached material (an entry) is per key; the material object itself (its record: material, state, refs) is shared by the
   * keys whose material would be identical: the same family of programs, pass, variant, Look, features per stage, claims,
   * options and uniform object, so the legacy fish and the predators draw one material per variant and pass as before the
   * binder (three's opaque sort, material id then depth, as on main). @param {MaterialBinderDeps} deps @returns {MaterialBinder} */
  function create(deps) {
    var THREE = deps.THREE, warn = deps.warn || function (/** @type {string} */ m) { console.warn(m); };
    var BASE = normalize(null);
    var active = BASE, version = 0, pending = false;
    /** @type {Object<string, MaterialKindDef>} */
    var defs = {};
    /** @type {Object<string, BinderEntry>} */
    var cache = {};
    /** @type {string[]} the keys, in the order they were made */
    var order = [];
    /** @type {Object<string, BinderRecord>} the material records by share key */
    var shares = {};
    /** @type {WeakMap<object, MaterialBound>} */
    var bound = new WeakMap();
    /** @type {Object<string, boolean>} what the console was told (once each) */
    var said = {};
    /** @type {WeakMap<MaterialSet, Object<string, { d?: Described, error?: string }>>} each set's descriptions, made once */
    var descs = new WeakMap();
    /** @type {Object<string, boolean>} the kinds the active Look covers (its activation's, or a kind's own since); the base set covers all */
    var covered = {};
    /** @type {Object<string, boolean>} the keys the active Look drew in its activations (kept when another is activated) */
    var live = {};
    /** @type {WeakMap<object, number>} */
    var uids = new WeakMap();
    var uidN = 0;
    /** @type {WeakMap<object, WeakMap<object, object>>} a kind's uniforms merged with a set's, once per pair (neither kept alive) */
    var merges = new WeakMap();

    /** @param {string} key @param {string} text */
    function say(key, text) { if (!said[key]) { said[key] = true; warn(text); } }
    /** @param {object} o */
    function uid(o) { var n = uids.get(o); if (!n) { n = ++uidN; uids.set(o, n); } return n; }
    /** the uniforms a set adds to a kind (the faces: their attached pass's) @param {MaterialSet} set @param {string} kind */
    function extrasOf(set, kind) {
      return (kind === "face" ? set.attach && set.attach.face.uniforms : set.uniforms && set.uniforms[kind]) || null;
    }
    /** a kind's uniforms (the scene's objects), merged with the set's own for it into an object of the binder's (once per pair:
     * kinds with the same share it). Neither is ever written after: the set's own uniform objects are in its keys (describe),
     * so a Look activated again with others draws new materials (the same programs: three links them from its cache)
     * @param {MaterialSet} set @param {string} kind @param {string} pass @returns {object} */
    function uniformsOf(set, kind, pass) {
      var k = kind === "face" ? "pred" : kind;
      if (!hasOwn.call(defs, k)) throw err("kind " + k + " is not defined (define() it first)");
      var u = defs[k].uniforms[pass === "litSkip" || kind === "face" ? "body" : pass];
      if (!u) throw err(k + " has no uniforms for its " + pass + " pass");
      var extra = extrasOf(set, kind);
      if (!extra) return u;
      var m = merges.get(u);
      if (!m) { m = new WeakMap(); merges.set(u, m); }
      var x = m.get(extra);
      if (!x) { x = Object.assign({}, u, extra); m.set(extra, x); }
      return x;
    }
    /** a pass's material options (as the scene's were: double-sided; a shadow transparent, depth-written, LessDepth)
     * @param {MaterialSet} set @param {string} kind @param {string} pass */
    function optionsOf(set, kind, pass) {
      if (pass === "shadow") return { transparent: true, depthWrite: true, depthFunc: THREE.LessDepth, side: THREE.DoubleSide };
      if (kind === "face" && set.attach) return Object.assign({ side: THREE.DoubleSide }, set.attach.face.options || {});
      return { side: THREE.DoubleSide };
    }
    /** a (kind, pass, variant) the set has, else a throw @param {MaterialSet} set @param {string} kind @param {string} pass @param {number} variant */
    function asked(set, kind, pass, variant) {
      if (!hasOwn.call(KINDS, kind)) throw err("unknown kind " + kind + " (the kinds: " + Object.keys(KINDS).join(", ") + ")");
      if (KINDS[kind].passes.indexOf(pass) < 0) throw err(kind + " has no " + pass + " pass");
      if (VARIANTS.indexOf(variant) < 0) throw err("unknown variant " + variant + " (0 plain, 1 the swim polish)");
      if (kind === "face" && !set.attach) throw err("no attached pass: the faces are a Look's (activate a set with attach.face)");
    }
    /** what a (kind, pass, variant) draws under a set: its features stage by stage (mode "set"; "polish": the swim polish's
     * only, the faces' fallback; "plain": none), its layout, its key and its share key
     * @param {MaterialSet} set @param {string} kind @param {string} pass @param {number} variant @param {string} mode @returns {Described} */
    function describe(set, kind, pass, variant, mode) {
      asked(set, kind, pass, variant);
      var plain = mode === "plain", noSet = mode === "polish";
      var vs = plain ? [] : featuresOf(set, kind, pass, "vs", variant, noSet), fs = plain ? [] : featuresOf(set, kind, pass, "fs", variant, noSet);
      var lay = set.layouts[KINDS[kind].layout];
      var fsKey = pass === "shadow" ? "(SHADOW_FS)" : kind === "face" ? "(" + set.look + ":" + set.faceDigest + ")" : idsKey(fs);
      var rest = ["v" + variant, "look:" + (set.look || "-"), "vs:" + idsKey(vs), "fs:" + fsKey];
      /* the set's own uniform objects for the kind, by identity (none: no part; the base set never has any) */
      var extra = extrasOf(set, kind);
      if (extra) rest.push("u" + uid(extra));
      return { key: ["abi" + SH.ABI, kind, pass, lay.id].concat(rest).join("|"), kind: kind, pass: pass, variant: variant, vs: vs, fs: fs, layout: lay, set: set,
               share: ["abi" + SH.ABI, KINDS[kind].family, pass, "claims" + lay.id.slice(lay.id.indexOf("/"))].concat(rest).join("|") };
    }
    /** a set's description of a (kind, pass, variant), made once (an error too: features() runs once a set per stage, not a
     * frame) @param {MaterialSet} set @param {string} kind @param {string} pass @param {number} variant @param {string} mode */
    function resolve(set, kind, pass, variant, mode) {
      var m = descs.get(set);
      if (!m) { m = {}; descs.set(set, m); }
      var k = mode + "|" + kind + "|" + pass + "|" + variant;
      if (!hasOwn.call(m, k)) {
        try { m[k] = { d: describe(set, kind, pass, variant, mode) }; } catch (x) { m[k] = { error: msg(x) }; }
      }
      return m[k];
    }
    /** the cached entry of a description; new, its material record shared with the identical ones, or made (reserved: three's
     * default shaders until assembled) @param {Described} d @returns {BinderEntry} */
    function entry(d) {
      if (hasOwn.call(cache, d.key)) return cache[d.key];
      var u = uniformsOf(d.set, d.kind, d.pass), sk = d.share + "|u" + uid(u) + (d.kind === "face" ? "|face" : "");
      var rec = hasOwn.call(shares, sk) ? shares[sk] : null;
      if (!rec) {
        rec = { share: sk, material: new THREE.ShaderMaterial(Object.assign({ uniforms: u }, optionsOf(d.set, d.kind, d.pass))), state: "reserved", error: "", refs: 0 };
        shares[sk] = rec;
      }
      rec.refs++;
      /** @type {BinderEntry} */
      var e = { key: d.key, kind: d.kind, pass: d.pass, variant: d.variant, vs: d.vs, fs: d.fs, layout: d.layout, set: d.set, rec: rec };
      cache[d.key] = e; order.push(d.key);
      return e;
    }
    /** an entry out of the cache; its material disposed with the last key that drew it. Once only, and never one another
     * activation has taken up since (a one-kind activation failing after a newer set's success with the same keys)
     * @param {BinderEntry} e */
    function remove(e) {
      if (cache[e.key] !== e) return;
      delete cache[e.key];
      var i = order.indexOf(e.key);
      if (i >= 0) order.splice(i, 1);
      if (--e.rec.refs <= 0) { delete shares[e.rec.share]; if (e.rec.state !== "failed") e.rec.material.dispose(); }
    }
    /** assemble an entry's programs (once, its record's): the stage's program with its features; on an error the record fails
     * (its material disposed) and, unless quiet (an activation reports its own), the console says so once
     * @param {BinderEntry} e @param {boolean} quiet @returns {boolean} ready */
    function assemble(e, quiet) {
      var r = e.rec;
      if (r.state !== "reserved") return r.state === "ready";
      var k = e.kind === "face" ? "pred" : e.kind, env = (hasOwn.call(defs, k) && defs[k].env) || {};
      try {
        var fam = KINDS[e.kind].family, EA = env.EA, vs, fs;
        if (fam === "app") {
          if (!EA) throw err("the appearance fish's programs need the appearance law (env.EA)");
          vs = e.pass === "shadow" ? SH.program("app.shadow.vs", PT.appShadowVs(EA), e.vs, env) : SH.program("app.body.vs", PT.appBodyVs(EA), e.vs, env);
          fs = e.pass === "shadow" ? SH.SHADOW_FS : SH.program("app.body.fs", PT.appBodyFs(EA), e.fs, env);
        } else if (fam === "fish") {
          vs = e.pass === "shadow" ? SH.program("fish.shadow.vs", PT.shadowVs(), e.vs, env) : SH.program("fish.vs", PT.fishVs(), e.vs, env);
          fs = e.pass === "shadow" ? SH.SHADOW_FS : SH.program("fish.fs", PT.fishFs(), e.fs, env);
        } else {
          var a = /** @type {MaterialAttach} */ (e.set.attach && e.set.attach.face);
          vs = SH.program("fish.attach.vs", PT.fishAttach(a.decl, a.body), e.vs, env);
          fs = a.fs;
        }
        r.material.vertexShader = vs; r.material.fragmentShader = fs;
        r.state = "ready";
        return true;
      } catch (x) {
        r.state = "failed"; r.error = msg(x);
        r.material.dispose();
        if (!quiet) say("asm|" + e.key, "evo_boids: the " + KIND_OF[e.kind] + " material " + e.key + " could not be assembled: " + r.error +
                        ". " + (e.vs.length || e.fs.length ? "The plain programs are drawn instead" : "These fish cannot be drawn"));
        return false;
      }
    }
    /** the set a kind draws under: the active one, or (a kind defined while a Look is active, until its own activation
     * compiled) the base set @param {string} kind */
    function setFor(kind) { return active === BASE || covered[kind] ? active : BASE; }
    /** the plain programs a failed (kind, pass, variant) draws instead: the same kind and pass without a feature (the split's
     * main draw: the plain body; the faces: the predators' swim polish only, so they keep following the body)
     * @param {MaterialSet} set @param {string} kind @param {string} pass @param {number} variant @returns {BinderEntry | null} */
    function fallback(set, kind, pass, variant) {
      var r = kind === "face" ? resolve(set, "face", pass, variant, "polish") : resolve(BASE, kind, pass === "litSkip" ? "body" : pass, 0, "plain");
      if (!r.d) return null;
      var e = entry(r.d);
      assemble(e, false);
      return e;
    }
    /** the material a (kind, pass, variant) draws, assembled: its own, or on any error the plain programs'
     * @param {string} kind @param {string} pass @param {number} variant @returns {{ e: BinderEntry | null, own: boolean }} */
    function use(kind, pass, variant) {
      asked(active, kind, pass, variant);   /* (a kind, pass or variant that is not there: the caller's mistake, thrown) */
      var set = setFor(kind), r = resolve(set, kind, pass, variant, "set");
      if (r.d) {
        var e = entry(r.d);
        if (assemble(e, false)) return { e: e, own: true };
      } else say("key|" + set.look + "|" + kind + "|" + pass + "|" + variant, "evo_boids: the " + KIND_OF[kind] + " " + pass + " material (variant " + variant +
                 (set.look ? ", Look " + set.look : "") + ") could not be keyed: " + r.error + ". The plain programs are drawn instead");
      return { e: fallback(set, kind, pass, variant), own: false };
    }
    /** assemble and compile every reachable variant of these kinds under a set; a Promise of the outcome, what it made dropped
     * on a failure (but what a newer activation has taken up since: live) @param {MaterialSet} set @param {string[]} kinds
     * @returns {Promise<MaterialActivation>} */
    function run(set, kinds) {
      /** @type {BinderEntry[]} */
      var made = [], used = [];
      /** @type {MaterialCompileItem[]} */
      var items = [];
      function drop() { made.forEach(function (e) { if (!live[e.key]) remove(e); }); }
      try {
        reachable(set, kinds).forEach(function (r) {
          var rr = resolve(set, r.kind, r.pass, r.variant, "set");   /* (worked out once: the binds then look it up) */
          if (!rr.d) throw err(rr.error || "no key");
          var d = rr.d, had = hasOwn.call(cache, d.key), e = entry(d);
          if (!had) made.push(e);
          used.push(e);
          /* (an entry made before, now failing: the console says so, as its binds will fall back) */
          if (!assemble(e, !had)) throw err(e.key + ": " + e.rec.error);
          if (!items.some(function (x) { return x.material === e.rec.material; }))
            items.push({ key: e.key, kind: e.kind, pass: e.pass, variant: e.variant, material: e.rec.material,
                         geometry: e.kind === "face" && set.attach && set.attach.face.geometry || null });
        });
      } catch (x) {
        drop();
        return Promise.resolve({ ok: false, look: set.look, stage: "assembly", error: msg(x) });
      }
      /** @type {Promise<any>} */
      var p;
      try { p = Promise.resolve(deps.compile ? deps.compile(items) : { ok: true }); } catch (x) { p = Promise.reject(x); }
      return p.then(function (r) {
        if (!r || r.ok !== true) { drop(); return { ok: false, look: set.look, stage: "compile", error: (r && r.error) || "the programs did not compile" }; }
        used.forEach(function (e) { e.set = set; });   /* (the same key: the same programs and uniform objects; the set that drew it last) */
        return { ok: true, look: set.look, keys: used.map(function (e) { return e.key; }), materials: items.length };
      }, function (x) {
        drop();
        return { ok: false, look: set.look, stage: "compile", error: msg(x) };
      });
    }
    /** a kind defined while a Look is active: drawn under the base set until the Look's variants of it compiled
     * @param {string} kind */
    function activateKind(kind) {
      var set = active;
      run(set, [kind]).then(function (r) {
        if (active !== set) return;   /* (another set since: its activation, or its own for this kind, covers it) */
        if (r.ok) { covered[kind] = true; (r.keys || []).forEach(function (k) { live[k] = true; }); }
        else say("kind|" + set.look + "|" + kind, "evo_boids: the " + set.look + " Look could not be made for the " + KIND_NAMES[kind] + ": " + r.error +
                 ". They are drawn without it");
      });
    }

    /** @type {MaterialBinder} */
    var binder = {
      define: function (kind, def) {
        if (!hasOwn.call(KINDS, kind) || kind === "face") throw err("define(): unknown kind " + kind + " (the scene's: app, fish, pred; the faces are a Look's)");
        if (!def || !def.uniforms || !def.uniforms.body) throw err("define(" + kind + "): its uniforms by pass ({body, shadow})");
        if (hasOwn.call(defs, kind)) throw err("define(): " + kind + " is defined already");
        defs[kind] = def;
      },
      prepare: function (kinds) {
        kinds.forEach(function (k) { if (!hasOwn.call(defs, k)) throw err("prepare(): " + k + " is not defined"); });
        /* the materials made in the scene's old order (pass by pass, plain then polished, kind by kind); a kind the active Look
         * does not cover yet, under the base set (and its own activation started) */
        reachable(BASE, kinds).forEach(function (r) {
          var set = setFor(r.kind), d = resolve(set, r.kind, r.pass, r.variant, "set").d || resolve(BASE, r.kind, r.pass, r.variant, "set").d;
          if (d) entry(d);
        });
        if (active !== BASE) kinds.forEach(function (k) { if (!covered[k]) activateKind(k); });
      },
      material: function (kind, pass, variant) {
        var u = use(kind, pass, variant);
        if (!u.e || u.e.rec.state !== "ready") throw err("the " + KIND_OF[kind] + " " + pass + " programs could not be assembled, nor their plain ones" + (u.e ? ": " + u.e.rec.error : ""));
        return u.e.rec.material;
      },
      has: function (kind, pass, variant) {
        var set = setFor(kind), r = resolve(set, kind, pass, variant, "set");
        return !!r.d && assemble(entry(r.d), false);
      },
      bind: function (mesh, kind, pass, variant) {
        var u = use(kind, pass, variant), eff = u.own ? variant : 0;
        if (u.e && u.e.rec.state === "ready" && mesh.material !== u.e.rec.material) mesh.material = u.e.rec.material;   /* the one writer of a fish mesh's material */
        bound.set(mesh, { kind: kind, pass: pass, variant: variant, effective: eff, key: u.e ? u.e.key : "", fallback: !u.own });
        return eff;
      },
      bound: function (mesh) { var b = bound.get(mesh); return b ? Object.assign({}, b) : null; },
      variantOf: function (mesh) { var b = bound.get(mesh); return b ? b.effective : 0; },
      warm: function (kinds) {
        /** @type {any[]} */
        var out = [];
        reachable(active, kinds).forEach(function (r) {
          if (r.variant === 0 && r.pass !== "litSkip") return;   /* (the plain body and shadow draw from the first frame) */
          var u = use(r.kind, r.pass, r.variant);
          if (u.e && u.e.rec.state === "ready" && out.indexOf(u.e.rec.material) < 0) out.push(u.e.rec.material);
        });
        return out;
      },
      key: function (kind, pass, variant) {
        asked(active, kind, pass, variant);
        var r = resolve(setFor(kind), kind, pass, variant, "set");
        if (!r.d) throw err(r.error || "no key");
        return r.d.key;
      },
      programs: function (kind, pass, variant) {
        var u = use(kind, pass, variant), ok = !!u.e && u.e.rec.state === "ready";
        return { key: u.e ? u.e.key : "", own: u.own, vs: ok && u.e ? u.e.rec.material.vertexShader : "", fs: ok && u.e ? u.e.rec.material.fragmentShader : "",
                 material: u.e ? u.e.rec.material : null };
      },
      activate: function (spec) {
        if (pending) return Promise.resolve({ ok: false, look: "", stage: "spec", error: "an activation is in progress" });
        /** @type {MaterialSet} */
        var set;
        try { set = normalize(spec); } catch (x) { return Promise.resolve({ ok: false, look: "", stage: "spec", error: msg(x) }); }
        var kinds = Object.keys(defs).concat(set.attach ? ["face"] : []);
        pending = true;
        return run(set, kinds).then(function (r) {
          pending = false;
          if (!r.ok) return r;
          active = set.look ? set : BASE; version++;   /* (no Look: the base set itself) */
          var before = live;
          covered = {}; live = {};
          kinds.forEach(function (k) { covered[k] = true; });
          (r.keys || []).forEach(function (k) { live[k] = true; });
          /* the sets it replaces: their materials freed, but the base set's (the plain fallback, and back to no Look) and the
           * set it replaces right now (kept one switch: a Look turned off and on again links its programs from three's cache
           * rather than compiling them again, ~10 s on ANGLE) */
          Object.keys(cache).forEach(function (k) { var e = cache[k]; if (e.set.look && !live[k] && !before[k]) remove(e); });
          /* a kind defined while it compiled: its own activation */
          if (set !== BASE && set.look) Object.keys(defs).forEach(function (k) { if (!covered[k]) activateKind(k); });
          return r;
        });
      },
      state: function () {
        return { look: active.look, version: version, pending: pending, kinds: Object.keys(defs), covered: Object.keys(covered),
                 materials: Object.keys(shares).length,
                 entries: order.map(function (k) { return { key: k, state: cache[k].rec.state, error: cache[k].rec.error }; }),
                 failed: order.filter(function (k) { return cache[k].rec.state === "failed"; }) };
      }
    };
    return binder;
  }

  /** The scene's compile for an activation (deps.compile): the materials compiled as the scene warms them (three's
   * compileAsync on a scratch scene, each on its kind's geometry), then each program checked: linked (the GL status, so it
   * holds whatever three's checkShaderErrors) and runnable by three's own first-use check (getUniforms; diagnostics). A
   * check that throws is a failure, never a pass; the budget (60 s: ANGLE / D3D11 takes ~1.2 s a program) only bounds a hung
   * compile, its timer cleared once settled. @param {MaterialCompilerOptions} o */
  function compiler(o) {
    var budget = o.budgetMs || 60000, timers = o.timers || { set: setTimeout, clear: clearTimeout };
    /** @param {MaterialCompileItem[]} items @returns {Promise<{ ok: boolean, error?: string }>} */
    return function (items) {
      return new Promise(function (resolve) {
        if (o.lost && o.lost()) { resolve({ ok: false, error: "the WebGL context is lost" }); return; }
        var settled = false, /** @type {any} */ timer = null;
        /** @param {{ ok: boolean, error?: string }} r */
        function end(r) { if (settled) return; settled = true; if (timer !== null) timers.clear(timer); timer = null; resolve(r); }
        function verify() {
          try {
            var gl = o.renderer.getContext(), bad = /** @type {string[]} */ ([]);
            items.forEach(function (x) {
              var p = o.renderer.properties.get(x.material).currentProgram;
              var good = !!(p && p.program) && gl.getProgramParameter(p.program, gl.LINK_STATUS) === true;
              if (good) { p.getUniforms(); good = !(p.diagnostics && p.diagnostics.runnable === false); }
              if (!good) bad.push(x.key);
            });
            end(bad.length ? { ok: false, error: "did not compile: " + bad.join(", ") } : { ok: true });
          } catch (e) { end({ ok: false, error: "the programs could not be checked: " + msg(e) }); }
        }
        try {
          var ws = new o.THREE.Scene();
          items.forEach(function (x) { var m = new o.THREE.Mesh(x.geometry ? x.geometry() : o.geometry(x), x.material); m.frustumCulled = false; ws.add(m); });
          timer = timers.set(function () { timer = null; end({ ok: false, error: "the compile did not finish in " + Math.round(budget / 1000) + " s" }); }, budget);
          if (o.renderer.compileAsync) o.renderer.compileAsync(ws, o.camera, o.scene).then(verify, function (/** @type {any} */ e) { end({ ok: false, error: msg(e) }); });
          else { o.renderer.compile(ws, o.camera, o.scene); verify(); }
        } catch (e) { end({ ok: false, error: msg(e) }); }
      });
    };
  }

  /** @type {EvoOceanMaterialsApi} */
  var API = {
    KINDS: KINDS, PASSES: PASSES, VARIANTS: VARIANTS, LAYOUTS: LAYOUTS, LAYOUT_ABI: LAYOUT_ABI, LIT_SKIP_FEATURE: LIT_SKIP_FEATURE,
    layout: layout, create: create, compiler: compiler
  };
  root.EvoOceanMaterials = API;
})(typeof window !== "undefined" ? window : globalThis);
