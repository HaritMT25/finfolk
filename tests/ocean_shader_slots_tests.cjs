// tests/ocean_shader_slots_tests.cjs: the fish programs' named slots and the assembler (web/ocean_shaders.js:
// EvoOceanShaders.program / feature / core, SLOTS, PROGRAMS), in node.
//   node tests/ocean_shader_slots_tests.cjs
// Source-level contract checks, no browser and no GLSL compiler:
//   - every program's parts carry its slots in order; with no feature each program is the plain one, and
//     each replacement slot replaced by its own fallback gives the same bytes (its "must" declared)
//   - the swim polish as a feature: its lite / full modes are the variants the builders draw; registration
//     order and the order features are listed in change nothing
//   - each assembly error, with a planted mistake: a missing, duplicate, unknown or misplaced slot; an
//     unknown program or feature; an unsupported target or ABI; a misspelled slot; a slot none of a
//     feature's targets has; append to a replacement slot, replace an additive one; two providers of a
//     replacement; declaration collisions (global, in main(), between two features); a replacement that
//     does not declare what its slot must; text that is not GLSL
//   - the appends' order (order, then id), whatever the registration or the listing order
//   - a look on the slots (the porting guide's shape: surface, lighting, water, eyes, highlights, fog, and
//     the vertex stage's eye geometry): it assembles plain and with the lite polish, and is refused with the
//     full polish (both replace the lighting); its vertex stage composes with the full polish's
//   - the light terms and the water (review of #57, P2-1): the pre-water slot sits between the lit colour and
//     the water in every fragment stage; the polish's flashlight term moved there gives the same bytes, its
//     terms as pure light terms compose with a look's lighting; the water replaced by a look's own depth
//   - a pass a look owns on a kind (fish.attach.vs, P2-2): posed as its kind, the pose read first
//   - the strings the scene draws, by digest (P2-3): a builder edit that changes them fails here, even when
//     it changes the builder and the assembler alike; a deliberate change updates SCENE_SHA256 with it
//   - declarations(), the scan the collision checks use, on a sample
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), crypto = require("crypto");

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 400) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }
/* fn must throw an Error whose message contains each of the strings in want */
function throws(fn, want, what) {
  let msg = null;
  try { fn(); } catch (e) { msg = String(e && e.message || e); }
  ok(msg !== null && want.every((w) => msg.includes(w)), what, msg === null ? "did not throw" : msg);
}

const WEB = path.join(__dirname, "..", "web");
const ctx = vm.createContext({ console });
ctx.window = ctx; ctx.globalThis = ctx;
for (const f of ["ocean_appearance.js", "ocean_shaders.js"]) vm.runInContext(fs.readFileSync(path.join(WEB, f), "utf8"), ctx, { filename: f });
const SH = ctx.EvoOceanShaders, EA = ctx.EvoAppearance;
if (!SH || !EA) { console.log("FAIL: EvoOceanShaders / EvoAppearance did not load"); process.exit(1); }
const L = SH.POLISH.lite, F = SH.POLISH.full, env = { EA };
const PT = SH.parts;
/* a look's own pass on the legacy fish's instances (as #47's predator faces): its declarations and main() */
const ATT_DECL = "attribute vec3 aLoc;\nvarying vec3 vWorld; varying vec3 vLoc; varying float vEmber;";
const ATT_BODY = "  vec3 w = fishWorld(); vWorld = w; vLoc = aLoc; vEmber = iBody.w;\n  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);";
const PARTS = { "fish.vs": () => PT.fishVs(), "fish.fs": () => PT.fishFs(), "fish.shadow.vs": () => PT.shadowVs(),
  "fish.attach.vs": () => PT.fishAttach(ATT_DECL, ATT_BODY),
  "app.body.vs": () => PT.appBodyVs(EA), "app.body.fs": () => PT.appBodyFs(EA), "app.shadow.vs": () => PT.appShadowVs(EA) };
const NAMES = Object.keys(PARTS);
const app = (P) => SH.appearanceShaders(EA, P);
/* the builders' strings, program by program, for a variant P (the one each program draws for it) */
function built(name, P) {
  switch (name) {
    case "fish.vs": return SH.fishVs(P);
    case "fish.fs": return SH.fishFs(P === "lite" ? false : P);
    case "fish.shadow.vs": return SH.shadowVs(P);
    /* the common part posed as the kind's, the look's declarations, main() with the pose read first */
    case "fish.attach.vs": return SH.fishCore(P) + "\n" + ATT_DECL + "\nvoid main() {\n" + (P ? "  iPose = poseOf(iX.y);\n" : "") + ATT_BODY + "\n}";
    case "app.body.vs": return app(P).vs;
    case "app.body.fs": return app(P).fs;
    case "app.shadow.vs": return P === "lite" ? app(true).shadowVs : app(P).shadowVs;
  }
  throw new Error(name);
}
const idsOf = (P) => (P === "lite" ? [L] : P ? [F] : []);
const slotsIn = (parts) => parts.filter((x) => x && typeof x === "object").map((x) => x.slot);

section("the programs and their slots");
ok(NAMES.join() === Object.keys(SH.PROGRAMS).join(), "the programs with slots: " + NAMES.join(", "));
ok(Object.isFrozen(SH.SLOTS) && Object.isFrozen(SH.PROGRAMS) && Object.isFrozen(SH.SLOTS["app.rest"]), "the contracts are frozen");
const used = new Set();
for (const name of NAMES) {
  const p = PARTS[name](), C = SH.PROGRAMS[name];
  ok(slotsIn(p).join() === C.slots.join(), name + ": its parts carry its slots in order (" + C.slots.join(", ") + ")");
  C.slots.forEach((s) => { used.add(s); });
  ok(C.slots.every((s) => SH.SLOTS[s].stage === C.stage), name + ": every slot is a " + C.stage + " slot");
  ok(SH.program(name, PARTS[name]()) === built(name, false) && SH.program(name, PARTS[name](), [], env) === built(name, false),
     name + ": with no feature, the plain program");
}
ok(Object.keys(SH.SLOTS).every((s) => used.has(s)), "every slot is in a program (" + Object.keys(SH.SLOTS).length + " slots)");
ok(Object.keys(SH.SLOTS).every((s) => { const x = SH.SLOTS[s]; return x.at && x.reads.length && x.writes.length && (x.kind === "append" || x.kind === "replace") && (x.kind === "replace" || !x.must.length); }),
   "every slot documents where it is, what it may read and what it writes");
/* each replacement slot, replaced by its own fallback: the same bytes, and the fallback declares the slot's must */
{
  const A = SH.assembler();
  for (const name of NAMES) {
    for (const x of PARTS[name]()) {
      if (!x || typeof x !== "object" || SH.SLOTS[x.slot].kind !== "replace") continue;
      const id = "same." + name + "." + x.slot;
      A.feature({ id, abi: SH.ABI, targets: [name], replace: { [x.slot]: x.fallback } });
      let out = null, msg = "";
      try { out = A.program(name, PARTS[name](), [id], env); } catch (e) { msg = e.message; }
      const must = SH.SLOTS[x.slot].must;
      ok(out === built(name, false), name + ": " + x.slot + " replaced by its own fallback: the same program (" + (must.length ? "it declares " + must.join(", ") : "nothing it must declare") + ")", msg || undefined);
    }
  }
}

section("the swim polish as a feature");
const DEC = SH.DECODED;
ok(SH.features().join() === [DEC, F, L].join(), "the module registers the polish's two modes and the render optimization's decoded constants: " + SH.features().join(", "));
for (const name of NAMES) for (const P of [true, "lite"]) {
  if (name === "app.shadow.vs" && P === true) continue;   /* (the builders give a shadow the lite polish) */
  ok(SH.program(name, PARTS[name](), idsOf(P), env) === built(name, P), name + " [" + idsOf(P) + "]: the " + (P === true ? "full" : "lite") + " variant");
}
ok(SH.program("fish.fs", PT.fishFs(), [L]) === SH.fishFs(false), "fish.fs [lite]: the plain fragment stage (the lite polish targets none)");
ok(SH.FISH_VS[1] === SH.program("fish.vs", PT.fishVs(), [F]) && SH.FISH_VS[2] === SH.program("fish.vs", PT.fishVs(), [L]) && SH.SHADOW_VS[1] === SH.program("fish.shadow.vs", PT.shadowVs(), [L]),
   "FISH_VS / SHADOW_VS are the polish's programs");
ok(SH.fishCore(true) === SH.core("fish.vs", PT.fishCore(), [F]) && SH.appCore(EA, "lite") === SH.core("app.body.vs", PT.appCore(EA), [L], env),
   "the common parts (core) are the polish's too");
{
  const A = SH.assembler(), B = SH.assembler();
  A.feature(SH.polishFeature("lite")); A.feature(SH.polishFeature("full"));
  B.feature(SH.polishFeature("full")); B.feature(SH.polishFeature("lite"));
  let same = true;
  for (const name of NAMES) for (const ids of [[], [L], [F]]) {
    const x = A.program(name, PARTS[name](), ids, env), y = B.program(name, PARTS[name](), ids, env), z = SH.program(name, PARTS[name](), ids, env);
    if (x !== y || x !== z) same = false;
  }
  ok(same, "registered lite-first, full-first or by the module: the same programs");
}
throws(() => SH.program("app.body.vs", PT.appBodyVs(EA), [L, F], env), ["app.world has 2 providers", L, F], "lite and full together: refused (two providers of app.world)");
throws(() => SH.program("app.body.vs", PT.appBodyVs(EA), [F]), ["needs the appearance law"], "the full polish's app.world without env.EA: refused");

section("assembly errors, each with a planted mistake");
const T = () => SH.assembler();
const fishVsWith = (f) => { const p = PT.fishVs(); f(p); return p; };
const at = (p, s) => p.findIndex((x) => x && x.slot === s);
throws(() => SH.program("fish.vs", fishVsWith((p) => p.splice(at(p, "fish.pose"), 1))), ["fish.vs: missing slot fish.pose"], "a missing slot");
throws(() => SH.program("fish.vs", fishVsWith((p) => p.push(SH.slot("fish.pose", null)))), ["fish.vs: duplicate slot fish.pose"], "a duplicate slot");
throws(() => SH.program("fish.vs", fishVsWith((p) => { p[at(p, "fish.pose")] = SH.slot("fish.posee", null); })), ["fish.vs: unknown slot fish.posee"], "a misspelled slot in the parts");
throws(() => SH.program("fish.vs", fishVsWith((p) => { const i = at(p, "fish.pose"), j = at(p, "fish.varyings"), t = p[i]; p[i] = p[j]; p[j] = t; })),
       ["fish.vs: its slots are out of order"], "slots out of order");
throws(() => SH.program("fish.shadow.vs", PT.fishVs()), ["fish.shadow.vs: unknown slot fish.vs.decl"], "another program's parts");
throws(() => SH.program("fish.vs", fishVsWith((p) => p.push(42))), ["neither GLSL, null nor a slot"], "a part that is not GLSL");
throws(() => SH.program("fish.gill.vs", PT.fishVs()), ["unknown program fish.gill.vs"], "an unknown program");
throws(() => SH.program("fish.vs", PT.fishVs(), ["reef"]), ["fish.vs: unknown feature reef"], "an unknown feature");
throws(() => T().feature({ id: "x", abi: 1, targets: ["fish.gill.vs"], append: { "fish.pose": "" } }), ["feature x: unsupported target fish.gill.vs"], "an unsupported target");
throws(() => T().feature({ id: "x", abi: 2, targets: ["fish.vs"], append: { "fish.pose": "" } }), ["feature x: ABI 2 is not supported"], "an unsupported ABI");
throws(() => T().feature({ id: "x", abi: 1, targets: ["app.body.vs"], append: { "app.rst": "  geo.y *= 1.1;" } }), ["feature x: unknown slot app.rst"], "a misspelled slot in a feature");
throws(() => T().feature({ id: "x", abi: 1, targets: ["app.body.fs"], append: { "app.rest": "  geo.y *= 1.1;" } }), ["slot app.rest is in none of its targets (app.body.fs)"], "a slot none of its targets has");
throws(() => T().feature({ id: "x", abi: 1, targets: ["app.body.fs"], append: { "app.lighting": "  col *= 0.5;" } }), ["app.lighting is a replacement slot, not one to append"], "append to a replacement slot");
throws(() => T().feature({ id: "x", abi: 1, targets: ["app.body.vs"], replace: { "app.rest": "  geo.y *= 1.1;" } }), ["app.rest is an additive slot, not one to replace"], "replace an additive slot");
throws(() => { const A = T(); A.feature({ id: "x", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" } }); A.feature({ id: "x", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" } }); },
       ["feature x is registered already"], "a feature registered twice");
throws(() => SH.feature(SH.polishFeature("lite")), ["feature swimPolish.lite is registered already"], "the polish registered again");
throws(() => T().feature({ abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" } }), ["a feature needs an id"], "a feature without an id");
throws(() => T().feature({ id: "x", abi: 1, targets: [], append: { "fish.pose": "" } }), ["feature x has no targets"], "a feature without targets");
throws(() => T().feature({ id: "x", abi: 1, targets: ["fish.vs"] }), ["feature x appends and replaces nothing"], "a feature that does nothing");
throws(() => T().feature({ id: "x", abi: 1, targets: ["fish.vs"], append: { "fish.pose": 7 } }), ["neither GLSL nor a function giving it"], "a feature's text that is not GLSL");
throws(() => T().feature({ id: "x", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" }, order: "first" }), ["its order is not a number"], "an order that is not a number");
{
  const A = T();
  A.feature({ id: "fogA", abi: 1, targets: ["app.body.fs"], replace: { "app.fog": "  vec3 murky = col;" } });
  A.feature({ id: "fogB", abi: 1, targets: ["app.body.fs"], replace: { "app.fog": "  vec3 murky = mix(col, uFog, 0.5);" } });
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["fogB", "fogA"], env), ["app.body.fs: app.fog has 2 providers (fogA, fogB)"], "two providers of a replacement slot");
  ok(A.program("app.body.fs", PT.appBodyFs(EA), ["fogA"], env).includes("  vec3 murky = col;\n  if (bk > 0.0) {"), "one provider: its replacement in the slot's place");
  A.feature({ id: "uTime2", abi: 1, targets: ["app.body.fs"], append: { "app.fs.decl": "uniform float uTime;" } });
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["uTime2"], env), ["declaration collision: uTime (global), declared by the program and uTime2 (app.fs.decl)"], "a declaration collision with the program (a global)");
  A.feature({ id: "rim2", abi: 1, targets: ["app.body.fs"], append: { "app.lightMods": "  float rim = 0.0;" } });
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["rim2"], env), ["declaration collision: rim in main(), declared by the program and rim2 (app.lightMods)"], "a declaration collision in main()");
  A.feature({ id: "kA", abi: 1, targets: ["fish.fs"], append: { "fish.fs.decl": "float lookK(float x) { return x; }" } });
  A.feature({ id: "kB", abi: 1, targets: ["fish.fs"], append: { "fish.fs.lib": "const float lookK = 1.0;" } });
  throws(() => A.program("fish.fs", PT.fishFs(), ["kA", "kB"]), ["declaration collision: lookK (global)", "kB (fish.fs.lib)", "kA (fish.fs.decl)"], "a declaration collision between two features");
  A.feature({ id: "own", abi: 1, targets: ["fish.fs"], append: { "fish.lightMods": "  vec3 tint = vec3(1.0);\n  col *= tint;" } });
  ok(A.program("fish.fs", PT.fishFs(), ["own"]).includes("  vec3 tint = vec3(1.0);"), "a new local in main() of a name nobody declares: fine");
  A.feature({ id: "haze", abi: 1, targets: ["app.body.fs"], replace: { "app.fog": "  vec3 haze = col;" } });
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["haze"], env), ["haze's app.fog does not declare murky"], "a replacement that does not declare what its slot must");
  A.feature({ id: "lightNoBk", abi: 1, targets: ["fish.fs"], replace: { "fish.lighting": "  float rim = 0.0;\n  vec3 col = vCol, clear = col;" } });
  throws(() => A.program("fish.fs", PT.fishFs(), ["lightNoBk"]), ["lightNoBk's fish.lighting does not declare bk"], "a lighting replacement without bk");
  A.feature({ id: "worldX", abi: 1, targets: ["fish.vs", "fish.shadow.vs"], replace: { "fish.world": "vec3 fishWorldX() { return vec3(0.0); }" } });
  throws(() => A.program("fish.shadow.vs", PT.shadowVs(), ["worldX"]), ["worldX's fish.world does not declare fishWorld"], "a world replacement without fishWorld()");
  A.feature({ id: "fnBad", abi: 1, targets: ["app.body.vs"], append: { "app.rest": () => 3 } });
  throws(() => A.program("app.body.vs", PT.appBodyVs(EA), ["fnBad"], env), ["fnBad's text for app.rest is not GLSL"], "a text function that does not give GLSL");
  A.feature({ id: "fnEnv", abi: 1, targets: ["app.body.vs"], append: { "app.rest": (e) => "  geo.y *= " + SH.glslF(e.EA.PHI_I) + ";" } });
  ok(A.program("app.body.vs", PT.appBodyVs(EA), ["fnEnv"], env).includes("  geo.y *= " + SH.glslF(EA.PHI_I) + ";\n  vec3 w = appWorld(geo);"), "a text function gets the program's environment (EA)");
  ok(A.program("app.body.vs", PT.appBodyVs(EA), ["fogA", "uTime2"], env) === built("app.body.vs", false), "features that target other programs add nothing (and are not checked there)");
}

section("the appends' order: (order, id), never registration or listing");
{
  const mk = (ids) => { const A = T(); for (const id of ids) A.feature(Object.assign({ id, abi: 1, targets: ["app.body.vs", "app.shadow.vs"], append: { "app.rest": "  // " + id } }, id === "zFirst" ? { order: -1 } : {})); return A; };
  const outs = [["b", "a", "zFirst"], ["zFirst", "a", "b"], ["a", "zFirst", "b"]].map((reg) =>
    [["a", "b", "zFirst"], ["b", "zFirst", "a"]].map((listed) => mk(reg).program("app.body.vs", PT.appBodyVs(EA), listed, env)));
  const flat = [].concat.apply([], outs);
  ok(flat.every((x) => x === flat[0]), "3 registration orders x 2 listing orders: one program");
  ok(flat[0].includes("mBuild(M, aT, aPattern, uTime, uWag, minWidth(), geo, mat, mar);\n  // zFirst\n  // a\n  // b\n  vec3 w = appWorld(geo);"),
     "order -1 first, then by id, after the slot's place (after mBuild, before appWorld)");
  const A = mk(["a"]); A.feature(SH.polishFeature("full"));
  ok(A.program("app.body.vs", PT.appBodyVs(EA), [F, "a"], env).includes("  // a\n  geo = finPose(M, geo);\n  vec3 w = appWorld(geo);"),
     "with the full polish: a before swimPolish.full (by id)");
  const H = T(); H.feature({ id: "glow", abi: 1, targets: ["fish.fs"], append: { "fish.highlights": "  add += vec3(0.1) * rim;" } });
  ok(H.program("fish.fs", PT.fishFs(), ["glow"]).includes("  else if (vSel > 0.25) add += uSelect * 0.4 * rim;\n  add += vec3(0.1) * rim;\n  col += add;"),
     "an additive slot's fallback (the selection) stays, the append after it");
}

section("a look on the slots (the porting guide's shape)");
{
  /* a look as #47 (Reef) would write it on the slots: its varyings and functions (decl), the family colour
   * exactly (surface), its own banded light, without the water's grading (lighting), a cartoon eye (eyes), a
   * family glow (highlights), its haze (fog), and the eye's geometry in the vertex stage (rest). The GLSL is
   * a small stand-in for the look's own. */
  const A = T();
  A.feature(SH.polishFeature("lite")); A.feature(SH.polishFeature("full"));
  A.feature({
    id: "look", abi: 1, targets: ["app.body.vs", "app.body.fs"],
    append: {
      "app.vs.decl": "uniform float uBlinkOn;\nvarying vec4 vEye; varying float vBlink;",
      "app.rest": ["  vEye = vec4(0.0); vBlink = 0.0;", "  if (aPattern.x > 3.5 && aPattern.x < 4.5) { vEye = vec4(aT.xy, 0.0, 0.0); vBlink = uBlinkOn; }"].join("\n"),
      "app.fs.decl": ["varying vec4 vEye; varying float vBlink;", "uniform float uLookDepthK; uniform float uGlowOn; uniform vec3 uGlowCol;",
                      "float lookBand(vec3 N) { float l = max(dot(N, uLight), 0.0); return mix(0.74, 1.0, smoothstep(0.30, 0.62, l)); }",
                      "vec3 lookHaze(vec3 c, vec3 w) { return mix(c, uFog, 0.2 * fogOf(w)); }"].join("\n"),
      "app.surface": "  if (uColourBy > 0.5) { float pc = vPart.w, pr = floor(pc / 65536.0), pg = floor((pc - 65536.0 * pr) / 256.0); base = vec3(pr, pg, pc - 65536.0 * pr - 256.0 * pg) / 255.0; }",
      "app.highlights": "  if (uGlowOn > 0.5 && vSel > 0.18 && vSel < 0.26) add += uGlowCol * (0.16 + 0.75 * rim);"
    },
    replace: {
      "app.lighting": ["  float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);", "  float bk = beamOf(vWorld);",
                       "  vec3 rlit = base * lookBand(N);", "  vec3 col = rlit;", "  vec3 clear = rlit;"].join("\n"),
      "app.water": "  col *= 1.0 - uLookDepthK * depthOf(vWorld.y);",   /* the look's own depth, not the water's grading */
      "app.eyes": ["  if (fin == 4) {", "    if (length(vEye.xy) > 1.0) discard;", "    col = mix(vec3(0.98), vec3(0.05), step(0.6, length(vEye.xy - vEye.zw))); clear = col;", "  }"].join("\n"),
      "app.fog": "  vec3 murky = lookHaze(col, vWorld);"
    }
  });
  for (const ids of [["look"], ["look", L]]) {
    let vs = null, fs = null, msg = "";
    try { vs = A.program("app.body.vs", PT.appBodyVs(EA), ids, env); fs = A.program("app.body.fs", PT.appBodyFs(EA), ids, env); } catch (e) { msg = e.message; }
    ok(vs && fs && fs.includes("  vec3 murky = lookHaze(col, vWorld);") && !fs.includes("mix(col, uFog, fogOf(vWorld))") && !fs.includes("underwaterAt(vivid(col)") &&
       fs.includes("  vec3 clear = rlit;\n  col *= 1.0 - uLookDepthK * depthOf(vWorld.y);\n  vec3 add") &&
       vs.includes("vBlink = uBlinkOn; }\n  vec3 w = appWorld(geo);"), "the look [" + ids.join(", ") + "]: assembles; its fog, its light, its own depth for the water, its eye geometry before appWorld", msg || undefined);
  }
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["look", F], env), ["app.lighting has 2 providers (look, swimPolish.full)"],
         "the look with the full polish's fragment stage: refused (both replace the lighting; the polish's light terms would be lost)");
  ok(A.program("app.body.vs", PT.appBodyVs(EA), ["look", F], env).includes("vBlink = uBlinkOn; }\n  geo = finPose(M, geo);\n  vec3 w = appWorld(geo);"),
     "[full, look] for the vertex stage, [look] for the fragment stage: the eye's geometry, then the fins' fold (the polish's swim kept)");
}

section("the light terms and the water (review P2-1)");
{
  const A = T();
  A.feature({ id: "mark", abi: 1, targets: ["fish.fs", "app.body.fs"], append: { "fish.lightTerms": "  // terms", "app.lightTerms": "  // terms" } });
  A.feature(SH.polishFeature("full"));
  const WATER = "  col = underwaterAt(vivid(col), vWorld.y);";
  for (const [name, ids] of [["fish.fs", []], ["fish.fs", [F]], ["app.body.fs", []], ["app.body.fs", [F]]]) {
    const s = A.program(name, PARTS[name](), ["mark"].concat(ids), env), lit = name === "fish.fs" ? "  vec3 clear = " : "  vec3 clear = ";
    ok(s.includes("  // terms\n" + WATER) && s.indexOf(lit) < s.indexOf("  // terms"), name + " [" + ids + "]: the pre-water slot sits after the lit colour, before the water's grading");
  }
  /* the full polish's flashlight term (the clear light's polish terms) moved from its lighting to the light terms:
   * the same bytes; the rest of its light (the wrapped diffuse, polishOn and the sheen inside lit()'s
   * expression) cannot move without changing them */
  const full = SH.polishFeature("full"), split = Object.assign({}, full, { id: "split.full", append: Object.assign({}, full.append), replace: Object.assign({}, full.replace) });
  for (const [s, cut] of [["fish.lighting", "\n  if (bk > 0.0) { vec3 bt"], ["app.lighting", "\n  if (bk > 0.0) {\n    vec3 bt"]]) {
    const t = full.replace[s], i = t.lastIndexOf(cut);
    split.replace[s] = t.slice(0, i);
    split.append[s.split(".")[0] + ".lightTerms"] = t.slice(i + 1);
  }
  const B = T(); B.feature(split);
  ok(B.program("fish.fs", PT.fishFs(), ["split.full"]) === SH.FISH_FS[1] && B.program("app.body.fs", PT.appBodyFs(EA), ["split.full"], env) === app(true).fs,
     "the full polish with its flashlight term in the light terms: FISH_FS[1] and the full appearance stage, byte for byte");
  /* the polish's light as pure terms on any lighting (a look change for the full polish: its own PR): with a look
   * that replaces the lighting and the water, it composes */
  B.feature({ id: "polishTerms", abi: 1, targets: ["app.body.fs"], append: {
    "app.fs.lib": SH.POLISH_FN, "app.fs.decl": "flat varying float vPw; varying float vCaus;",
    "app.lightTerms": ["  float tn = dot(N, uLight);", "  vec3 tk = polishK(N, V, 0.0, tn, vPw, vCaus);", "  col += polishOn(base, tk); clear += polishOn(base, tk);"].join("\n") } });
  B.feature({ id: "look2", abi: 1, targets: ["app.body.fs"], replace: {
    "app.lighting": ["  float rim = 0.0;", "  float bk = beamOf(vWorld);", "  vec3 col = base, clear = base;"].join("\n"), "app.water": "" } });
  const both = B.program("app.body.fs", PT.appBodyFs(EA), ["look2", "polishTerms"], env);
  ok(both.includes("  vec3 col = base, clear = base;\n  float tn = dot(N, uLight);") && !both.includes("underwaterAt(vivid(col)") && both !== app(true).fs,
     "the polish's light as light terms composes with a look's lighting and no water (a look change, not this PR's)");
  throws(() => B.program("app.body.fs", PT.appBodyFs(EA), ["look2", "split.full"], env), ["app.lighting has 2 providers (look2, split.full)"],
         "while the polish keeps its lighting, a look's lighting is refused with it");
  const W = T(); W.feature({ id: "dry", abi: 1, targets: ["fish.fs"], replace: { "fish.water": "" } });
  ok(W.program("fish.fs", PT.fishFs(), ["dry"]) === SH.fishFs(false).replace(WATER + "\n", ""), "the water replaced by \"\": no line (the rest byte for byte)");
}

section("a pass a look owns on a kind: fish.attach.vs (review P2-2)");
{
  const old = SH.core("fish.vs", PT.fishCore(), [F]) + "\n" + ATT_DECL + "\nvoid main() {\n" + ATT_BODY + "\n}";
  ok(old.includes("vec4 iPose;") && !old.includes("iPose = poseOf"), "the common part posed plus a look's own main (#47's faces today): iPose declared, never read (the faces would collapse onto the spine)");
  for (const P of [true, "lite"]) {
    const s = SH.program("fish.attach.vs", PT.fishAttach(ATT_DECL, ATT_BODY), idsOf(P));
    ok(s.includes("void main() {\n  iPose = poseOf(iX.y);\n  vec3 w = fishWorld();") && s.includes("rollTo(") && (P !== true || s.includes("wagAt(u")),
       "fish.attach.vs [" + idsOf(P) + "]: the pose read first, then the look's body; the world posed as the kind's");
  }
  ok(SH.program("fish.attach.vs", PT.fishAttach(ATT_DECL, ATT_BODY), []) === SH.fishCore(false) + "\n" + ATT_DECL + "\nvoid main() {\n" + ATT_BODY + "\n}",
     "fish.attach.vs plain: the plain common part and the look's main, as today");
}

section("the strings the scene draws, by digest (review P2-3)");
{
  /* sha256 of each string, as main 57a6d6e built them (and this module does): a change to one of them (a builder,
   * a slot's fallback, the polish, the appearance law's GLSL) fails here until this table changes with it */
  const SCENE_SHA256 = {
    "FISH_VS[0]": "c659473471314811b0b30f944a483d184bf537d07315e90ad7c72169f8ad21e1",
    "FISH_VS[1]": "37f0563135c545920153d6ec6ccefc1e0da532ef6adac2f87368c4964723c528",
    "FISH_VS[2]": "38f443c709b60778a884c5b53dfb6343f3a99f02eb2c37a614175a4511ce1608",
    "FISH_FS[0]": "3149e2477d08a5ccfc80271560528a1cb9f72f4c2e01ace8bb55bae9190fb74b",
    "FISH_FS[1]": "4ecf9fbb8b107a07dfca9737fc9627dd90b126c01b8ff5d47caea940d890b274",
    "FISH_FS[2]": "3149e2477d08a5ccfc80271560528a1cb9f72f4c2e01ace8bb55bae9190fb74b",
    "SHADOW_VS[0]": "344381da16771cac5e79a0d628eef02d1d00a65b480b75036cc4240a68e8f3f8",
    "SHADOW_VS[1]": "23885b939229d7c03e8d11ce8f33c2b9713e0e30a31f6901e6855756755197fa",
    "SHADOW_FS": "7fce8373adf0da358ce576a3e1e787d7080ea8794f5ef27772b7e8bd2ac316c0",
    "app(false).vs": "6209ba4f3154be9324de9183d7173c04bede4acaf23d451e1f71e33795016581",
    "app(false).fs": "6c62521d6e35fc2170d227050614a969a72fc0a61f05cb3dd5c37ef1ae8d750a",
    "app(false).shadowVs": "7e8d247592bfeaa7c4a3ac452f23f9bd06c882b5cf5dbbf0e5338636ddac4524",
    "app(false).chartVs": "535990558ade8ed90c94529e47f66289acf852338454cbdb115dc7011e727e45",
    "app(false).chartFs": "fb64f803b71f3b372a1fde4b91acdfc4ab187deb3e9493c9f7f0320743f6eae7",
    "app(false).probeRawVs": "0c69e428b553157676e8acf8d34261dd3734cdb638f51240b7c9f5074d12d467",
    "app(false).probeRawFs": "99e98f0d9636c8958a291f7224f316c1e866780e1efeb57f66dd5added925066",
    "app(false).probeChartVs": "6022cf89e7f3230e4c487a6fa494a461a54df9d8e07d8489aba27c302ca54444",
    "app(true).vs": "02aeb58c48bdd601abd77a61a7cceed95e72bfe68455d13a9135e45e00fdb40c",
    "app(true).fs": "e017ca301d55e517108088ca824ff734c98a0bb878f71fbc46dc2d7d58cd1603",
    "app(true).shadowVs": "eaf2bc949295fa422e8cd77f086753dc232123ec2038ea2fc458f2262f129749",
    "app(true).chartVs": "535990558ade8ed90c94529e47f66289acf852338454cbdb115dc7011e727e45",
    "app(true).chartFs": "fb64f803b71f3b372a1fde4b91acdfc4ab187deb3e9493c9f7f0320743f6eae7",
    "app(true).probeRawVs": "0c69e428b553157676e8acf8d34261dd3734cdb638f51240b7c9f5074d12d467",
    "app(true).probeRawFs": "99e98f0d9636c8958a291f7224f316c1e866780e1efeb57f66dd5added925066",
    "app(true).probeChartVs": "6022cf89e7f3230e4c487a6fa494a461a54df9d8e07d8489aba27c302ca54444",
    "app(lite).vs": "de843cf3cb6961d50a6839401800eddf50c8746c27b64036451f23d1d390e0ce",
    "app(lite).fs": "6c62521d6e35fc2170d227050614a969a72fc0a61f05cb3dd5c37ef1ae8d750a",
    "app(lite).shadowVs": "eaf2bc949295fa422e8cd77f086753dc232123ec2038ea2fc458f2262f129749",
    "app(lite).chartVs": "535990558ade8ed90c94529e47f66289acf852338454cbdb115dc7011e727e45",
    "app(lite).chartFs": "fb64f803b71f3b372a1fde4b91acdfc4ab187deb3e9493c9f7f0320743f6eae7",
    "app(lite).probeRawVs": "0c69e428b553157676e8acf8d34261dd3734cdb638f51240b7c9f5074d12d467",
    "app(lite).probeRawFs": "99e98f0d9636c8958a291f7224f316c1e866780e1efeb57f66dd5added925066",
    "app(lite).probeChartVs": "6022cf89e7f3230e4c487a6fa494a461a54df9d8e07d8489aba27c302ca54444",
    "litSkip(app(false).vs)": "5b97846d859a8c573438b7a5c7d8cc62afc3ca7378ac1de14b2b26264a6b7b8a"
  };
  const sha = (s) => crypto.createHash("sha256").update(s, "utf8").digest("hex");
  const drawn = {};
  SH.FISH_VS.forEach((s, i) => { drawn["FISH_VS[" + i + "]"] = s; });
  SH.FISH_FS.forEach((s, i) => { drawn["FISH_FS[" + i + "]"] = s; });
  SH.SHADOW_VS.forEach((s, i) => { drawn["SHADOW_VS[" + i + "]"] = s; });
  drawn.SHADOW_FS = SH.SHADOW_FS;
  for (const P of [false, true, "lite"]) { const a = app(P); for (const k of Object.keys(a)) drawn["app(" + P + ")." + k] = a[k]; }
  drawn["litSkip(app(false).vs)"] = SH.litSkip(app(false).vs);
  const keys = Object.keys(SCENE_SHA256), differ = keys.filter((k) => drawn[k] === undefined || sha(drawn[k]) !== SCENE_SHA256[k]);
  ok(Object.keys(drawn).join() === keys.join() && !differ.length, keys.length + " strings the scene draws, each its committed sha256", differ.length ? differ : undefined);
}

section("the rest of the review's checks (P3)");
{
  throws(() => SH.program("fish.vs", (() => { const p = PT.fishVs(); p[p.findIndex((x) => x && x.slot === "fish.pose")] = { slot: "fish.pose", fallback: 3 }; return p; })()),
         ["fish.vs: slot fish.pose's fallback is neither GLSL nor null"], "a fallback that is not GLSL");
  ok(SH.core("fish.vs", PT.fishCore(), []) === SH.fishCore(false), "core(): the slots the part has, the program's others not required");
  throws(() => SH.core("fish.vs", PT.fishCore().concat([SH.slot("fish.world", null)])), ["fish.vs: duplicate slot fish.world"], "core(): a duplicate slot");
  throws(() => SH.core("fish.vs", PT.fishCore().concat([SH.slot("app.rest", null)])), ["fish.vs: unknown slot app.rest"], "core(): an unknown slot");
  throws(() => SH.core("fish.vs", [SH.slot("fish.pose", null), SH.slot("fish.world", null)]), ["fish.vs: its slots are out of order"], "core(): slots out of order");
  const A = T();
  A.feature({ id: "boom", abi: 1, targets: ["app.body.vs"], append: { "app.rest": () => { throw new Error("no EA here"); } } });
  throws(() => A.program("app.body.vs", PT.appBodyVs(EA), ["boom"], env), ["app.body.vs: boom's text for app.rest threw: no EA here"], "a text function that throws: named with its feature, slot and program");
  A.feature({ id: "noFog", abi: 1, targets: ["fish.fs"], replace: { "fish.fog": "" } });
  throws(() => A.program("fish.fs", PT.fishFs(), ["noFog"]), ["noFog's fish.fog is empty: it does not declare murky"], "an empty replacement of a slot that must declare: refused");
  A.feature({ id: "glow.emit", abi: 1, targets: ["fish.fs", "app.body.fs"], append: { "fish.emissive": "  murky += vec3(0.0, 0.1, 0.2) * vEmber;", "app.emissive": "  murky += vec3(0.0);" } });
  ok(A.program("fish.fs", PT.fishFs(), ["glow.emit"]).includes("    murky = mix(murky, clear, bk);\n  }\n  murky += vec3(0.0, 0.1, 0.2) * vEmber;\n  gl_FragColor = vec4(murky, 1.0);") &&
     A.program("app.body.fs", PT.appBodyFs(EA), ["glow.emit"], env).includes("  }\n  murky += vec3(0.0);\n  gl_FragColor"),
     "the emissive slot: after the fog and the flashlight's blend, before the output");
}

section("the render optimization's decoded constants (render.decoded)");
{
  const f = SH.featureOf(DEC);
  ok(DEC === "render.decoded" && f && f.version === 1 && f.targets.join() === "app.body.vs,app.shadow.vs,app.body.fs" && f.order === 0,
     "a registered feature: render.decoded, version 1, the appearance fish's body and shadow vertex stages and body fragment stage", f && f.targets);
  ok(Object.keys(f.replace).sort().join() === "app.fetch.body,app.fetch.shadow,app.morph,app.pattern.fs,app.pattern.vs" && Object.keys(f.append).sort().join() === "app.cache.vs,app.pattern.load",
     "it replaces the five slots that hold the raw fetch, the body plan decode and the pattern law's varyings, and appends the readers and the fragment load");
  /* with it, each program: the raw fetch and decode gone, the readers in, the polish's variants composing with it */
  const vs = (P) => SH.program("app.body.vs", PT.appBodyVs(EA), idsOf(P).concat([DEC]), env);
  const sh = (P) => SH.program("app.shadow.vs", PT.appShadowVs(EA), idsOf(P === true ? "lite" : P).concat([DEC]), env);
  const fs = (P) => SH.program("app.body.fs", PT.appBodyFs(EA), idsOf(P).concat([DEC]), env);
  const mainOf = (s) => s.slice(s.lastIndexOf("void main() {"));
  for (const P of [false, "lite", true]) {
    const a = vs(P), m = mainOf(a), tag = "[" + idsOf(P).concat([DEC]) + "]";
    ok(m.includes("  vDecoded = vec2(iGeneSlot, iX.z);") && m.includes("  Morph M = mLoad(iX.z);") && !m.includes("fetchGenes(") && !m.includes("patternDecode(") && !m.includes("mDecode("),
       "app.body.vs " + tag + ": main reads the decoded constants, no raw fetch, no pattern decode, no mDecode");
    ok(a.includes("Morph mLoad(float lam)") && a.includes("vec4 decodedTexel(int slot, int k)") && a.includes("flat varying vec2 vDecoded;") && !/flat varying vec4 vG0/.test(a) && !a.includes("void patternDecode("),
       "app.body.vs " + tag + ": the readers and the one flat varying; none of the pattern law's ten flat vec4s, no patternDecode");
    ok(P !== true || (m.includes("geo = finPose(M, geo);") && a.includes("vec3 finPose(Morph M, vec3 geo)") && m.indexOf("iPose = poseOf(iBody.w);") < m.indexOf("vDecoded =")),
       "app.body.vs " + tag + ": the polish composes with it (the pose read first, finPose on the loaded M)");
    const s = sh(P), ms = mainOf(s);
    ok(ms.includes("  Morph M = mLoad(iX.z);") && !ms.includes("fetchGenes(") && !ms.includes("vDecoded") && s.includes("Morph mLoad(float lam)"),
       "app.shadow.vs " + tag.replace("[swimPolish.full", "[swimPolish.lite") + ": mLoad, no raw fetch, and no varying");
    const q = fs(P), mq = mainOf(q);
    ok(q.includes("flat varying vec2 vDecoded;") && q.includes("void loadPattern(int slot, float lam)") && !/flat varying vec4 vG0/.test(q) && /\nvec4 vG0; vec4 vG1;/.test(q) &&
       /\n  else \{\n    loadPattern\(int\(vDecoded.x\), vDecoded.y\);\n    base = patternSkinM\(/.test(mq),
       "app.body.fs " + tag + ": the pattern's constants are globals loaded in the skin-from-genes branch, before patternSkinM (Family / Brain read none)");
  }
  /* the layout the three readers share: Morph's fields in the texel order mLoad reads, then the pattern's texels */
  const G = EA.GLSL, st = /struct Morph \{([\s\S]*?)\};/.exec(G.MORPH)[1].replace(/;/g, ",").split(",").map((x) => x.trim().split(/\s+/).pop()).filter(Boolean);
  ok(st.length === 33 && st[32] === "lam" && st.slice(0, 32).join() === EA.DECODED_MORPH_FIELDS.join(), "DECODED_MORPH_FIELDS are Morph's 32 fields (all but lambda) in the struct's order", st);
  const reads = EA.DECODED_MORPH_FIELDS.map((n, j) => "  M." + n + " = d" + (j >> 2) + "." + "xyzw"[j & 3] + ";");
  ok(reads.every((r) => G.DECODED_MORPH.includes(r)) && G.DECODED_MORPH.includes("  M.lam = lam;") && /decodedTexel\(s, 7\)/.test(G.DECODED_MORPH) && !/decodedTexel\(s, 8\)/.test(G.DECODED_MORPH),
     "mLoad reads field j from texel j / 4, component j % 4, from texels 0 .. 7 only, and takes lambda from the caller");
  ok(EA.DECODED_TEXELS === 18 && EA.DECODED_FLOATS === 72 && EA.DECODED_ROW_SLOTS === 32 && EA.DECODED_WIDTH === 576 && G.DECODED_READ.includes("18 * (slot % 32) + k, slot / 32"),
     "the texture's layout: 18 texels, 72 floats a slot, 32 slots a row, 576 wide; the reader's address matches");
  ok([8, 9, 10, 11, 12, 13, 14, 15, 16, 17].every((k) => G.DECODED_PATTERN.includes("decodedTexel(slot, " + k + ")")) && G.DECODED_PATTERN.includes("vAux = vec4(aux.xyz, lam);"),
     "loadPattern reads texels 8 .. 17 (vG0 .. vG7, vAux.xyz, vMeta) and sets vAux.w to the caller's lambda");
  /* without the law, the feature is refused (a text function that throws names itself) */
  throws(() => SH.program("app.body.vs", PT.appBodyVs(EA), [DEC], {}), ["render.decoded", "env.EA"], "the feature without the appearance law (env.EA): refused, naming itself");
  /* a feature that reads raw genes or the pattern varyings in a vertex slot does not compose: the declaration check names the collision or the missing name */
  const A = SH.assembler();
  A.feature(SH.polishFeature("lite")); A.feature(SH.polishFeature("full")); A.feature(SH.decodedFeature());
  ok(A.program("app.body.vs", PT.appBodyVs(EA), [F, DEC], env) === vs(true), "a fresh assembler gives the same program (registration order changes nothing)");
  A.feature({ id: "mock.rawgenes", abi: SH.ABI, targets: ["app.body.vs"], append: { "app.rest": "  float rawGene = GT[0].x;" } });
  ok(A.program("app.body.vs", PT.appBodyVs(EA), ["mock.rawgenes"], env).includes("GT[0].x") && A.program("app.body.vs", PT.appBodyVs(EA), ["mock.rawgenes", DEC], env).includes("GT[0].x"),
     "a look reading raw genes still assembles (GT stays declared): the binder, not the assembler, keeps the cache from running under it");
}

section("declarations(), the checks' scan");
{
  const src = ["// a comment: uniform float notMe;", "uniform vec3 uA; uniform float uB, uC[4];", "attribute vec4 aX;", "flat varying vec4 vF;",
               "const vec3 K1 = vec3(1.0, 2.0, 3.0), K2 = vec3(min(1.0, 2.0), 0.0, 0.0);", "struct Thing { float a; vec3 b; };", "vec4 gGlobal;",
               "float proto(float x);", "/* uniform float notMe2; */", "#define NOT_ME 1",
               "vec3 f(vec3 p, float q) {", "  float a = q, b = max(q, 1.0);", "  if (a > b) { float inner = 1.0; a += inner; }", "  for (int i = 0; i < 3; i++) { b += float(i); }",
               "  Thing t; vec2 uv = p.xy;", "  return p * a;", "}", "void main() {", "  vec3 col = f(uA, uB);", "  col *= 2.0;", "}"].join("\n");
  const D = SH.declarations(src);
  const glob = D.filter((d) => !d.scope).map((d) => d.kind + " " + d.name).join(", ");
  ok(glob === "uniform uA, uniform uB, uniform uC, attribute aX, varying vF, const K1, const K2, struct Thing, global gGlobal, function f, function main", "the globals: " + glob);
  const loc = D.filter((d) => d.scope).map((d) => d.scope + " " + d.name).join(", ");
  ok(loc === "f#1 a, f#1 b, f#1 t, f#1 uv, main#2 col", "each function's top-level locals: " + loc);
  ok(D.every((d) => src.slice(d.at).search(/\S/) === 0), "each at the start of its statement");
  const P = SH.declarations(SH.appearanceShaders(EA, true).fs), names = new Set(P.filter((d) => !d.scope).map((d) => d.name));
  ok(["uLight", "uTime", "uFog", "fogOf", "underwaterAt", "lit", "beamOf", "polishK", "thinOf", "sheenOf", "colourBase", "main", "vPw", "vCaus"].every((x) => names.has(x)),
     "the full appearance fragment stage: its globals found (" + names.size + ")");
  const mainLocals = P.filter((d) => d.scope.startsWith("main#")).map((d) => d.name).join(", ");
  ok(mainLocals === "fin, bodyLike, sn, u, v, zL, base, oyL, N, V, thin, nl, diff, rim, pk, sheen, col, bk, clear, add, vSel, murky", "its main()'s locals: " + mainLocals);
}

console.log((fails ? "FAIL" : "ok") + ": " + (checks - fails) + "/" + checks + " checks");
process.exit(fails ? 1 : 0);
