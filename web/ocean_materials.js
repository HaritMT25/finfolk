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
 *     the Look, and the enabled features' ids and versions stage by stage (the vertex and fragment
 *     stages may differ: under Reef, [swimPolish.full, reef.fish] / [reef.fish]). Uniform values are
 *     not in it: a kind's materials share its uniforms (the scene's objects, so setClarity, setLight
 *     and the rest reach every variant). Each program is EvoOceanShaders.program(name, parts, the
 *     stage's features), so a feature that is not enabled contributes no GLSL
 *   - one writer of a fish mesh's material (bind): the scene's kinds commit the variant settle() chose
 *     (its prewarm and hysteresis unchanged) and the binder assigns the material
 *   - the lit fish's split is a feature (LIT_SKIP_FEATURE): it appends the skip to app.pose with order
 *     -1, so it is the first line of main(), byte for byte the old text insert litSkip(vs)
 *   - the declared attribute layouts (LAYOUTS, layout()): each kind's instance attributes, component
 *     by component, as the scene's fills write them, the swim pose's reserved (the appearance fish's
 *     iBody.w, the legacy fish's and the predators' iX.y). A Look claims a spare component (a feature
 *     set's claims), never a reserved or a used one; a claim is part of the key
 *   - atomic activation (activate(set)): every reachable variant of a new feature set (each defined
 *     kind's passes and variants, and the set's attached pass) is assembled, then compiled (the
 *     scene's compile: three's, then each program checked runnable), before the set takes effect; an
 *     assembly or compile failure keeps the previous set, and drops what it made
 *   - lazy assembly: a variant's programs are assembled when it is first drawn, warmed or activated,
 *     never as the scripts load. An assembly error (say a scan's false positive in the polish) falls
 *     back to the plain programs (variant 0, no feature), said once on the console and kept in
 *     state(): the plain fish are always drawn
 * The material objects are made (reserved, prepare) where the scene made its own before the binder,
 * in the same order, so three's draw order (opaque objects sort by material id within a render order)
 * is main's; their GLSL is assembled later, on first use.
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
  /** @param {MaterialSetSpec | null | undefined} spec @returns {MaterialSet} */
  function normalize(spec) {
    if (spec === null || spec === undefined) return Object.freeze({ look: "", features: null, attach: null, uniforms: null, layouts: LAYOUTS });
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
    return Object.freeze({ look: look, features: spec.features || null, attach: attach, uniforms: spec.uniforms || null, layouts: Object.freeze(layouts) });
  }
  /** @param {string[]} ids @returns {string[]} one of each, sorted (the assembler's order is (order, id) whatever the list's) */
  function canon(ids) {
    /** @type {string[]} */
    var o = [];
    ids.forEach(function (id) { if (o.indexOf(id) < 0) o.push(id); });
    return o.sort();
  }
  /** a stage's feature ids under a set: the swim polish's for the variant (base), the set's choice, then the pass's own (the skip)
   * @param {MaterialSet} set @param {string} kind @param {string} pass @param {"vs" | "fs"} stage @param {number} variant @returns {string[]} */
  function featuresOf(set, kind, pass, stage, variant) {
    if (kind === "face") {
      /* the faces: the predators' vertex features, whatever the set says of the faces */
      var vs = featuresOf(set, "pred", "body", "vs", variant);
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
    var ids = set.features ? set.features({ kind: kind, pass: pass === "litSkip" ? "body" : pass, stage: stage, variant: variant, base: base.slice() }) : base;
    if (!Array.isArray(ids) || ids.some(function (x) { return typeof x !== "string" || !x; }))
      throw err(set.look + ": its features for " + kind + " " + pass + " " + stage + " variant " + variant + " are not a list of feature ids");
    ids = ids.slice();
    if (pass === "litSkip" && stage === "vs") ids.push(LIT_SKIP_FEATURE);
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

  /** The binder: the scene's one (create(), once a renderer). deps: THREE (its ShaderMaterial and constants), compile (the
   * activation's compile: a Promise of {ok, error}), warn (the console's). @param {MaterialBinderDeps} deps @returns {MaterialBinder} */
  function create(deps) {
    var THREE = deps.THREE, warn = deps.warn || function (/** @type {string} */ m) { console.warn(m); };
    var BASE = normalize(null);
    var active = BASE, version = 0, pending = false;
    /** @type {Object<string, MaterialKindDef>} */
    var defs = {};
    /** @type {Object<string, BinderEntry>} */
    var cache = {};
    /** @type {string[]} the keys, in the order their materials were made */
    var order = [];
    /** @type {WeakMap<object, MaterialBound>} */
    var bound = new WeakMap();

    /** a kind's uniforms (the scene's objects) and the set's own for it @param {MaterialSet} set @param {string} kind @param {string} pass */
    function uniformsOf(set, kind, pass) {
      var k = kind === "face" ? "pred" : kind;
      if (!hasOwn.call(defs, k)) throw err("kind " + k + " is not defined (define() it first)");
      var u = defs[k].uniforms[pass === "litSkip" || kind === "face" ? "body" : pass];
      if (!u) throw err(k + " has no uniforms for its " + pass + " pass");
      var extra = kind === "face" ? set.attach && set.attach.face.uniforms : set.uniforms && set.uniforms[kind];
      return extra ? Object.assign({}, u, extra) : u;
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
    /** what a (kind, pass, variant) draws under a set: its features stage by stage, its layout, its key (plain: no feature)
     * @param {MaterialSet} set @param {string} kind @param {string} pass @param {number} variant @param {boolean} plain */
    function describe(set, kind, pass, variant, plain) {
      asked(set, kind, pass, variant);
      var vs = plain ? [] : featuresOf(set, kind, pass, "vs", variant), fs = plain ? [] : featuresOf(set, kind, pass, "fs", variant);
      var lay = set.layouts[KINDS[kind].layout];
      var fsKey = pass === "shadow" ? "(SHADOW_FS)" : kind === "face" ? "(" + set.look + ")" : idsKey(fs);
      var key = ["abi" + SH.ABI, kind, pass, lay.id, "v" + variant, "look:" + (set.look || "-"), "vs:" + idsKey(vs), "fs:" + fsKey].join("|");
      return { key: key, kind: kind, pass: pass, variant: variant, vs: vs, fs: fs, layout: lay, set: set };
    }
    /** the cached entry of a description, its material made (reserved, its GLSL not yet assembled) if new
     * @param {ReturnType<typeof describe>} d @returns {BinderEntry} */
    function entry(d) {
      if (hasOwn.call(cache, d.key)) return cache[d.key];
      var p = Object.assign({ uniforms: uniformsOf(d.set, d.kind, d.pass) }, optionsOf(d.set, d.kind, d.pass));
      /** @type {BinderEntry} */
      var e = { key: d.key, kind: d.kind, pass: d.pass, variant: d.variant, vs: d.vs, fs: d.fs, layout: d.layout, set: d.set,
                material: new THREE.ShaderMaterial(p), state: "reserved", error: "" };
      cache[d.key] = e; order.push(d.key);
      return e;
    }
    /** assemble an entry's programs (once): the stage's program with its features; on an error the entry fails
     * (its material disposed) and, unless quiet (an activation reports its own), the console says so once
     * @param {BinderEntry} e @param {boolean} quiet @returns {boolean} ready */
    function assemble(e, quiet) {
      if (e.state !== "reserved") return e.state === "ready";
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
        e.material.vertexShader = vs; e.material.fragmentShader = fs;
        e.state = "ready";
        return true;
      } catch (x) {
        e.state = "failed"; e.error = msg(x);
        e.material.dispose();
        if (!quiet) warn("evo_boids: the " + e.kind + " fish's " + e.pass + " programs (variant " + e.variant + "; vs [" + e.vs.join(", ") + "], fs [" +
                         e.fs.join(", ") + "]) could not be assembled: " + e.error + ". The plain programs are drawn instead");
        return false;
      }
    }
    /** the material a (kind, pass, variant) draws under the active set, assembled: its own, or on any error the plain
     * programs' (the same kind and pass without a feature; the split's skip, the plain body) @returns {{ e: BinderEntry, own: boolean }} */
    function use(/** @type {string} */ kind, /** @type {string} */ pass, /** @type {number} */ variant) {
      asked(active, kind, pass, variant);   /* (a kind, pass or variant that is not there: the caller's mistake, thrown) */
      /** @type {BinderEntry | null} */
      var e = null;
      try { e = entry(describe(active, kind, pass, variant, false)); if (assemble(e, false)) return { e: e, own: true }; }
      catch (x) {
        warn("evo_boids: the " + kind + " fish's " + pass + " material (variant " + variant + ") could not be keyed: " + msg(x) + ". The plain programs are drawn instead");
      }
      var p = entry(describe(kind === "face" ? active : BASE, kind, pass === "litSkip" ? "body" : pass, 0, true));
      assemble(p, false);
      return { e: p, own: false };
    }

    /** @type {MaterialBinder} */
    var binder = {
      define: function (kind, def) {
        if (!hasOwn.call(KINDS, kind) || kind === "face") throw err("define(): unknown kind " + kind + " (the scene's: app, fish, pred; the faces are a Look's)");
        if (!def || !def.uniforms || !def.uniforms.body) throw err("define(" + kind + "): its uniforms by pass ({body, shadow})");
        defs[kind] = def;
      },
      prepare: function (kinds) {
        reachable(active, kinds).forEach(function (r) { entry(describe(active, r.kind, r.pass, r.variant, false)); });
      },
      material: function (kind, pass, variant) { return use(kind, pass, variant).e.material; },
      bind: function (mesh, kind, pass, variant) {
        var u = use(kind, pass, variant), eff = u.own ? variant : 0;
        if (u.e.state === "ready" && mesh.material !== u.e.material) mesh.material = u.e.material;   /* the one writer of a fish mesh's material */
        bound.set(mesh, { kind: kind, pass: pass, variant: variant, effective: eff, key: u.e.key, fallback: !u.own });
        return eff;
      },
      bound: function (mesh) { var b = bound.get(mesh); return b ? Object.assign({}, b) : null; },
      variantOf: function (mesh) { var b = bound.get(mesh); return b ? b.effective : 0; },
      warm: function (kinds) {
        /** @type {any[]} */
        var out = [];
        reachable(active, kinds).forEach(function (r) {
          if (r.variant === 0 && r.pass !== "litSkip") return;   /* (the plain body and shadow draw from the first frame) */
          var m = use(r.kind, r.pass, r.variant).e.material;
          if (out.indexOf(m) < 0) out.push(m);
        });
        return out;
      },
      key: function (kind, pass, variant) { return describe(active, kind, pass, variant, false).key; },
      programs: function (kind, pass, variant) {
        var u = use(kind, pass, variant), ok = u.e.state === "ready";
        return { key: u.e.key, own: u.own, vs: ok ? u.e.material.vertexShader : "", fs: ok ? u.e.material.fragmentShader : "", material: u.e.material };
      },
      activate: function (spec) {
        if (pending) return Promise.resolve({ ok: false, look: "", stage: "spec", error: "an activation is in progress" });
        /** @type {MaterialSet} */
        var set;
        try { set = normalize(spec); } catch (x) { return Promise.resolve({ ok: false, look: "", stage: "spec", error: msg(x) }); }
        var kinds = Object.keys(defs).concat(set.attach ? ["face"] : []);
        /** @type {BinderEntry[]} */
        var made = [];
        /** @type {MaterialCompileItem[]} */
        var items = [];
        function drop() {
          made.forEach(function (e) { delete cache[e.key]; order.splice(order.indexOf(e.key), 1); if (e.state !== "failed") e.material.dispose(); });
        }
        try {
          reachable(set, kinds).forEach(function (r) {
            var d = describe(set, r.kind, r.pass, r.variant, false), had = hasOwn.call(cache, d.key), e = entry(d);
            if (!had) made.push(e);
            if (!assemble(e, true)) throw err(e.key + ": " + e.error);
            items.push({ key: e.key, kind: e.kind, pass: e.pass, variant: e.variant, material: e.material,
                         geometry: e.kind === "face" && set.attach && set.attach.face.geometry || null });
          });
        } catch (x) {
          drop();
          return Promise.resolve({ ok: false, look: set.look, stage: "assembly", error: msg(x) });
        }
        pending = true;
        /** @type {Promise<any>} */
        var p;
        try { p = Promise.resolve(deps.compile ? deps.compile(items) : { ok: true }); } catch (x) { p = Promise.reject(x); }
        return p.then(function (r) {
          pending = false;
          if (!r || r.ok !== true) { drop(); return { ok: false, look: set.look, stage: "compile", error: (r && r.error) || "the programs did not compile" }; }
          active = set; version++;
          return { ok: true, look: set.look, keys: items.map(function (x) { return x.key; }) };
        }, function (x) {
          pending = false; drop();
          return { ok: false, look: set.look, stage: "compile", error: msg(x) };
        });
      },
      state: function () {
        return { look: active.look, version: version, pending: pending, kinds: Object.keys(defs),
                 entries: order.map(function (k) { return { key: k, state: cache[k].state, error: cache[k].error }; }),
                 failed: order.filter(function (k) { return cache[k].state === "failed"; }) };
      }
    };
    return binder;
  }

  /** @type {EvoOceanMaterialsApi} */
  var API = {
    KINDS: KINDS, PASSES: PASSES, VARIANTS: VARIANTS, LAYOUTS: LAYOUTS, LAYOUT_ABI: LAYOUT_ABI, LIT_SKIP_FEATURE: LIT_SKIP_FEATURE,
    layout: layout, create: create
  };
  root.EvoOceanMaterials = API;
})(typeof window !== "undefined" ? window : globalThis);
