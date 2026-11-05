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
//   - a look on the slots (the porting guide's shape: surface, lighting, eyes, highlights, fog, and the
//     vertex stage's eye geometry): it assembles plain and with the lite polish, and is refused with the
//     full polish (both replace the lighting)
//   - declarations(), the scan the collision checks use, on a sample
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

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
const PARTS = { "fish.vs": () => PT.fishVs(), "fish.fs": () => PT.fishFs(), "fish.shadow.vs": () => PT.shadowVs(),
  "app.body.vs": () => PT.appBodyVs(EA), "app.body.fs": () => PT.appBodyFs(EA), "app.shadow.vs": () => PT.appShadowVs(EA) };
const NAMES = Object.keys(PARTS);
const app = (P) => SH.appearanceShaders(EA, P);
/* the builders' strings, program by program, for a variant P (the one each program draws for it) */
function built(name, P) {
  switch (name) {
    case "fish.vs": return SH.fishVs(P);
    case "fish.fs": return SH.fishFs(P === "lite" ? false : P);
    case "fish.shadow.vs": return SH.shadowVs(P);
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
ok(SH.features().join() === [F, L].join(), "the module registers the polish's two modes: " + SH.features().join(", "));
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
                       "  vec3 rlit = base * lookBand(N);", "  vec3 col = rlit * (1.0 - uLookDepthK * depthOf(vWorld.y));", "  vec3 clear = rlit;"].join("\n"),
      "app.eyes": ["  if (fin == 4) {", "    if (length(vEye.xy) > 1.0) discard;", "    col = mix(vec3(0.98), vec3(0.05), step(0.6, length(vEye.xy - vEye.zw))); clear = col;", "  }"].join("\n"),
      "app.fog": "  vec3 murky = lookHaze(col, vWorld);"
    }
  });
  for (const ids of [["look"], ["look", L]]) {
    let vs = null, fs = null, msg = "";
    try { vs = A.program("app.body.vs", PT.appBodyVs(EA), ids, env); fs = A.program("app.body.fs", PT.appBodyFs(EA), ids, env); } catch (e) { msg = e.message; }
    ok(vs && fs && fs.includes("  vec3 murky = lookHaze(col, vWorld);") && !fs.includes("mix(col, uFog, fogOf(vWorld))") && !fs.includes("underwaterAt(vivid(col)") &&
       vs.includes("vBlink = uBlinkOn; }\n  vec3 w = appWorld(geo);"), "the look [" + ids.join(", ") + "]: assembles; its fog, its light without the water, its eye geometry before appWorld", msg || undefined);
  }
  throws(() => A.program("app.body.fs", PT.appBodyFs(EA), ["look", F], env), ["app.lighting has 2 providers (look, swimPolish.full)"],
         "the look with the full polish: refused (both replace the lighting; the polish's light terms would be lost)");
  ok(A.program("app.body.vs", PT.appBodyVs(EA), ["look", F], env).includes("vBlink = uBlinkOn; }\n  geo = finPose(M, geo);\n  vec3 w = appWorld(geo);"),
     "its vertex stage composes with the full polish (the eye's geometry, then the fins' fold)");
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
