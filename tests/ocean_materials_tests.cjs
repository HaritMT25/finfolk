// tests/ocean_materials_tests.cjs: the fish's material binder (web/ocean_materials.js: EvoOceanMaterials), in node.
//   node tests/ocean_materials_tests.cjs
// Over web/ocean_shaders.js's assembler, with a stand-in for three's ShaderMaterial (no browser, no GLSL compiler):
//   - every program the binder draws, kind by kind, pass by pass, variant by variant, against the committed sha256
//     of the strings the scene drew before it (the slot test's 34; main's builders): byte for byte
//   - the shadow's polish is the lite one (app(true).shadowVs, eaf2bc94...: the full polish given to the appearance
//     shadow silently gives the plain one)
//   - the split's skip as a feature (app.pose, order -1): byte for byte the old text insert litSkip(vs)
//   - the cache's keys: the ABI, the kind, the pass, the layout, the variant, the Look, the features' ids and
//     versions per stage (vs and fs apart); listing order and uniform values are not in them; one material per key
//   - one writer of mesh.material (bind), and what it bound (bound, variantOf)
//   - the declared attribute layouts: the pose's components reserved (and read by the polish's pose slot), the
//     instance attributes the vertex stages declare, claims of spare components only
//   - the predators' faces (a Look's attached pass) follow the predators' vertex features; a feature that poses the
//     predators without targeting fish.attach.vs is refused
//   - atomic activation: every reachable variant assembled and compiled before a set takes effect; a planted
//     compile failure and a planted assembly error each keep the previous set and drop what they made
//   - lazy assembly: prepare() makes the materials (in the scene's old order) without assembling; a planted
//     scan failure in the polish (a declaration collision) no longer fails ocean_shaders.js as it loads, and the
//     binder draws the plain programs for that variant, said once
//   - the review of #58: the legacy fish and the predators share one material per pass and variant (main's 4, in
//     main's order: three's opaque sort is material id, then depth); a Look's faces keyed by their GLSL; a Look
//     activated again draws its new uniform objects; a kind defined while a Look is active (its clarity uniforms
//     in, its own activation, the base set until then); the compile's check without three's checkShaderErrors, a
//     check that throws, its budget and its timer; material() refuses when not even the plain programs assemble;
//     has() for the split's skip; features() once a set; the replaced sets' materials freed; a pre-existing entry
//     failing in an activation said; no feature ahead of the split's skip; one writer of .material in web/
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), crypto = require("crypto");

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 400) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }
function throws(fn, want, what) {
  let msg = null;
  try { fn(); } catch (e) { msg = String(e && e.message || e); }
  ok(msg !== null && want.every((w) => msg.includes(w)), what, msg === null ? "did not throw" : msg);
}
const sha = (s) => crypto.createHash("sha256").update(s, "utf8").digest("hex");

const WEB = path.join(__dirname, "..", "web");
/* the scripts in a fresh context (ocean.html's order); edit: a planted change to a file's text */
function load(edit) {
  const ctx = vm.createContext({ console });
  ctx.window = ctx; ctx.globalThis = ctx;
  for (const f of ["ocean_appearance.js", "ocean_shaders.js", "ocean_materials.js"]) {
    let src = fs.readFileSync(path.join(WEB, f), "utf8");
    if (edit && edit[f]) src = edit[f](src);
    vm.runInContext(src, ctx, { filename: f });
  }
  return ctx;
}
/* a stand-in for three: ShaderMaterial keeps what it is given (three's defaults until the binder assembles) */
function fakeThree() {
  let id = 0;
  function ShaderMaterial(p) {
    this.id = id++; this.vertexShader = "three's default vertex shader"; this.fragmentShader = "three's default fragment shader";
    this.uniforms = {}; this.disposed = false; Object.assign(this, p || {});
  }
  ShaderMaterial.prototype.dispose = function () { this.disposed = true; };
  return { ShaderMaterial, DoubleSide: 2, LessDepth: 2 };
}
/* a binder with the scene's kinds defined (uniform objects of its own), and what it warned */
function sceneBinder(ctx, compile) {
  const M = ctx.EvoOceanMaterials, warned = [];
  const U = { fish: { uTime: { value: 0 } }, shadow: { uAlpha: { value: 0.4 } }, app: { uGenes: { value: null } }, appShadow: { uAlpha: { value: 0.4 } } };
  const B = M.create({ THREE: fakeThree(), compile, warn: (m) => warned.push(m) });
  B.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } });
  B.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
  B.prepare(["fish", "pred"]);
  B.define("app", { uniforms: { body: U.app, shadow: U.appShadow }, env: { EA: ctx.EvoAppearance } });
  B.prepare(["app"]);
  return { B, U, warned };
}

async function main() {
const ctx = load();
const SH = ctx.EvoOceanShaders, EA = ctx.EvoAppearance, M = ctx.EvoOceanMaterials;
if (!SH || !EA || !M) { console.log("FAIL: EvoOceanShaders / EvoAppearance / EvoOceanMaterials did not load"); process.exit(1); }
const L = SH.POLISH.lite, F = SH.POLISH.full, SKIP = M.LIT_SKIP_FEATURE, env = { EA };
const app = (P) => SH.appearanceShaders(EA, P);

/* the slot test's table (tests/ocean_shader_slots_tests.cjs): main's 34 drawn strings */
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

section("the module");
ok(SH.features().join() === [SKIP, F, L].join(), "it registers the split's skip as a feature, beside the polish's two modes: " + SH.features().join(", "));
const skipF = SH.featureOf(SKIP);
ok(skipF && skipF.order === -1 && skipF.targets.join() === "app.body.vs" && Object.keys(skipF.append).join() === "app.pose" && skipF.append["app.pose"] === SH.LIT_SKIP_GLSL && skipF.version === 1,
   "scene.litSkip: app.body.vs's app.pose, order -1, the skip's line (LIT_SKIP_GLSL), version 1");
ok(Object.keys(M.KINDS).join() === "app,fish,pred,face" && M.PASSES.join() === "body,shadow,litSkip" && M.VARIANTS.join() === "0,1",
   "the kinds (app, fish, pred, face), the passes (body, shadow, litSkip), the variants (0 plain, 1 polished)");
ok(SH.featureOf(F).version === 1 && SH.featureOf("nope") === null, "featureOf(): a registered feature (its version), null for none");
throws(() => SH.assembler().feature({ id: "v0", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" }, version: 0 }), ["v0: its version is not a whole number from 1"], "a feature's version below 1: refused");
throws(() => SH.assembler().feature({ id: "v15", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "" }, version: 1.5 }), ["v15: its version is not a whole number from 1"], "a fractional version: refused");

section("every program the binder draws, against main's drawn strings (sha256)");
{
  const { B } = sceneBinder(ctx);
  /* [kind, pass, variant] -> [the vertex stage's digest name, the fragment stage's] */
  const WANT = [
    ["fish", "body", 0, "FISH_VS[0]", "FISH_FS[0]"], ["fish", "body", 1, "FISH_VS[1]", "FISH_FS[1]"],
    ["fish", "shadow", 0, "SHADOW_VS[0]", "SHADOW_FS"], ["fish", "shadow", 1, "SHADOW_VS[1]", "SHADOW_FS"],
    ["pred", "body", 0, "FISH_VS[0]", "FISH_FS[0]"], ["pred", "body", 1, "FISH_VS[1]", "FISH_FS[1]"],
    ["pred", "shadow", 0, "SHADOW_VS[0]", "SHADOW_FS"], ["pred", "shadow", 1, "SHADOW_VS[1]", "SHADOW_FS"],
    ["app", "body", 0, "app(false).vs", "app(false).fs"], ["app", "body", 1, "app(true).vs", "app(true).fs"],
    ["app", "shadow", 0, "app(false).shadowVs", "SHADOW_FS"], ["app", "shadow", 1, "app(true).shadowVs", "SHADOW_FS"],
    ["app", "litSkip", 0, "litSkip(app(false).vs)", "app(false).fs"]
  ];
  for (const [k, p, v, wv, wf] of WANT) {
    const g = B.programs(k, p, v);
    ok(g.own && sha(g.vs) === SCENE_SHA256[wv] && sha(g.fs) === SCENE_SHA256[wf], k + " " + p + " variant " + v + ": " + wv + " / " + wf + " (" + g.key + ")",
       { vs: sha(g.vs).slice(0, 8), fs: sha(g.fs).slice(0, 8), own: g.own });
  }
  ok(B.programs("app", "shadow", 1).key.includes("|vs:" + L + "@1|"), "the appearance shadow's polish is the lite one (eaf2bc94: app(true).shadowVs)");
  ok(sha(SH.program("app.shadow.vs", SH.parts.appShadowVs(EA), [F], env)) === SCENE_SHA256["app(false).shadowVs"],
     "(why it matters: the full polish given to the appearance shadow is silently the plain shadow, 7e8d2475, as it does not target app.shadow.vs)");
  /* the 34 strings themselves (the slot test's table) are unchanged */
  const drawn = {};
  SH.FISH_VS.forEach((s, i) => { drawn["FISH_VS[" + i + "]"] = s; });
  SH.FISH_FS.forEach((s, i) => { drawn["FISH_FS[" + i + "]"] = s; });
  SH.SHADOW_VS.forEach((s, i) => { drawn["SHADOW_VS[" + i + "]"] = s; });
  drawn.SHADOW_FS = SH.SHADOW_FS;
  for (const P of [false, true, "lite"]) { const a = app(P); for (const k of Object.keys(a)) drawn["app(" + P + ")." + k] = a[k]; }
  drawn["litSkip(app(false).vs)"] = SH.litSkip(app(false).vs);
  const keys = Object.keys(SCENE_SHA256), differ = keys.filter((k) => drawn[k] === undefined || sha(drawn[k]) !== SCENE_SHA256[k]);
  ok(Object.keys(drawn).join() === keys.join() && !differ.length, "the " + keys.length + " strings the scene drew before the binder: each its committed sha256", differ.length ? differ : undefined);
  ok(SH.FISH_VS === SH.FISH_VS && SH.SHADOW_VS === SH.SHADOW_VS, "FISH_VS / FISH_FS / SHADOW_VS: built on first read, once (the same arrays after)");
}

section("the split's skip, a feature (byte for byte litSkip(vs))");
{
  const plainSkip = SH.program("app.body.vs", SH.parts.appBodyVs(EA), [SKIP], env);
  ok(plainSkip === SH.litSkip(app(false).vs) && sha(plainSkip) === SCENE_SHA256["litSkip(app(false).vs)"], "app.body.vs [scene.litSkip] === litSkip(app(false).vs) (5b97846d)");
  const fullSkip = SH.program("app.body.vs", SH.parts.appBodyVs(EA), [F, SKIP], env);
  ok(fullSkip === SH.litSkip(app(true).vs) && fullSkip.includes("void main() {\n" + SH.LIT_SKIP_GLSL + "\n  iPose = poseOf(iBody.w);"),
     "with the full polish too (order -1): the skip first in main(), then the pose read; === litSkip(app(true).vs)");
  ok(SH.program("app.body.vs", SH.parts.appBodyVs(EA), [SKIP, F], env) === fullSkip, "listed after the polish: the same program");
}

section("the cache's keys");
{
  const { B, U } = sceneBinder(ctx);
  const k0 = B.key("fish", "body", 0), k1 = B.key("fish", "body", 1);
  ok(k0 === "abi1|fish|body|fish/1|v0|look:-|vs:-|fs:-", "fish body plain: " + k0);
  ok(k1 === "abi1|fish|body|fish/1|v1|look:-|vs:" + F + "@1|fs:" + F + "@1", "fish body polished: " + k1);
  ok(B.key("pred", "body", 1) === k1.replace("|fish|body|fish/1|", "|pred|body|pred/1|"), "the predators: their own kind and layout in the key");
  ok(B.key("app", "litSkip", 0) === "abi1|app|litSkip|app/1|v0|look:-|vs:" + SKIP + "@1|fs:-", "the split's main draw: " + B.key("app", "litSkip", 0));
  ok(B.key("fish", "shadow", 1) === "abi1|fish|shadow|fish/1|v1|look:-|vs:" + L + "@1|fs:(SHADOW_FS)", "a shadow: the lite polish, SHADOW_FS (no slots)");
  const mats = new Set();
  for (const k of ["fish", "pred", "app"]) for (const p of M.KINDS[k].passes) for (const v of [0, 1]) { if (p === "litSkip" && v) continue; mats.add(B.material(k, p, v)); }
  ok(mats.size === 9 && B.state().entries.length === 13 && B.state().materials === 9, "13 keys, 9 materials (the legacy fish and the predators share their 4; app 5)",
     { mats: mats.size, entries: B.state().entries.length, materials: B.state().materials });
  ok(B.material("fish", "body", 1) === B.material("fish", "body", 1), "one material per key (asked again: the same)");
  U.fish.uTime.value = 123;
  ok(B.key("fish", "body", 1) === k1 && B.material("fish", "body", 1).uniforms === U.fish, "uniform values are not in the key; a kind's materials share its uniform objects");
  /* a Look: per stage */
  ctx.EvoOceanShaders.feature({ id: "keys.look", abi: 1, version: 3, targets: ["fish.fs", "app.body.fs"], append: { "fish.emissive": "  murky += vec3(0.0);", "app.emissive": "  murky += vec3(0.0);" } });
  ctx.EvoOceanShaders.feature({ id: "keys.pose", abi: 1, targets: ["fish.vs", "app.body.vs"], append: { "fish.varyings": "  // keys.pose", "app.varyings": "  // keys.pose" } });
  const look = (order) => ({ look: "keys", features: (q) => {
    const add = q.stage === "fs" ? ["keys.look"] : ["keys.pose"];
    const ids = q.stage === "fs" && q.variant === 1 ? add : q.base.concat(add);   /* (as Reef: the polish's light out of the fragment stage) */
    return order ? ids.slice().reverse() : ids; } });
  const C = M.create({ THREE: fakeThree() });
  C.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } });
  C.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
  {
    const r = await C.activate(look(false));
    const kl = C.key("fish", "body", 1);
    ok(r.ok && kl === "abi1|fish|body|fish/1|v1|look:keys|vs:keys.pose@1+" + F + "@1|fs:keys.look@3", "a Look, per stage: vs [keys.pose, swimPolish.full], fs [keys.look] (versions in the key): " + kl, r);
    const g = C.programs("fish", "body", 1);
    ok(g.vs === SH.program("fish.vs", SH.parts.fishVs(), [F, "keys.pose"]) && g.fs === SH.program("fish.fs", SH.parts.fishFs(), ["keys.look"]) && !g.fs.includes("polishK"),
       "its programs: each stage assembled with its own features (no polish light in the fragment stage)");
    const D = M.create({ THREE: fakeThree() });
    D.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); D.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
    await D.activate(look(true));
    ok(D.key("fish", "body", 1) === kl, "the features listed in another order: the same key");
    const E = M.create({ THREE: fakeThree() });
    E.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); E.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
    const re = await E.activate(Object.assign(look(false), { claims: { fish: { "iX.z": "keys.blink" } } }));
    ok(re.ok && E.key("fish", "body", 1) === kl.replace("|fish/1|", "|fish/1+iX.z=keys.blink|") && E.key("pred", "body", 1).includes("|pred/1|"),
       "a claim of a spare component: in the kind's layout id, so in its keys (fish only)");
    ok(C.key("fish", "body", 0) === "abi1|fish|body|fish/1|v0|look:keys|vs:keys.pose@1|fs:keys.look@3" && C.key("fish", "body", 0) !== k0, "the Look is in the key (its plain variant too)");
  }
}

section("one writer of mesh.material (bind)");
{
  const { B } = sceneBinder(ctx);
  let writes = 0, cur = null;
  const mesh = { get material() { return cur; }, set material(m) { writes++; cur = m; } };
  const e0 = B.bind(mesh, "fish", "body", 0), m0 = mesh.material;
  const e1 = B.bind(mesh, "fish", "body", 1), m1 = mesh.material;
  B.bind(mesh, "fish", "body", 1);
  ok(e0 === 0 && e1 === 1 && m0 === B.material("fish", "body", 0) && m1 === B.material("fish", "body", 1) && writes === 2,
     "bind assigns the key's material, and only when it changes (3 binds, 2 writes)", { writes });
  const b = B.bound(mesh);
  ok(b && b.kind === "fish" && b.pass === "body" && b.variant === 1 && b.effective === 1 && b.key === B.key("fish", "body", 1) && !b.fallback && B.variantOf(mesh) === 1,
     "bound(): kind, pass, the variant asked and drawn, the key; variantOf()", b);
  ok(B.variantOf({}) === 0 && B.bound({}) === null, "a mesh never bound: variant 0 (made with the plain material), no record");
  const skip = { material: null };
  ok(B.bind(skip, "app", "litSkip", 0) === 0 && skip.material.vertexShader === SH.litSkip(app(false).vs), "the split's main draw: the litSkip pass, variant 0");
  throws(() => B.bind({ material: null }, "face", "body", 0), ["no attached pass"], "the faces without a Look: refused (no attached pass)");
  throws(() => B.bind({ material: null }, "fish", "litSkip", 0), ["fish has no litSkip pass"], "a pass the kind does not have: refused");
}

section("the declared attribute layouts");
{
  const LA = M.LAYOUTS;
  ok(LA.app.pose === "iBody.w" && LA.fish.pose === "iX.y" && LA.pred.pose === "iX.y" && Object.keys(LA.app.reserved).join() === "iBody.w" && Object.keys(LA.fish.reserved).join() === "iX.y",
     "the pose's component reserved: appearance iBody.w, legacy fish and predators iX.y");
  const pf = SH.polishFeature("full"), pl = SH.polishFeature("lite");
  ok(pf.append["app.pose"] === "  iPose = poseOf(" + LA.app.pose + ");" && pf.append["fish.pose"] === "  iPose = poseOf(" + LA.fish.pose + ");" && pl.append["app.pose"] === pf.append["app.pose"],
     "the polish's pose slot reads exactly the reserved component (poseOf(iBody.w), poseOf(iX.y)), lite and full");
  const attrsOf = (src) => SH.declarations(src).filter((d) => d.kind === "attribute").map((d) => d.name).sort().join();
  const lay = (k) => LA[k].template.concat(Object.keys(LA[k].attributes)).sort().join();
  ok(attrsOf(app(false).vs) === lay("app") && attrsOf(app(false).shadowVs) === lay("app") && attrsOf(SH.FISH_VS[0]) === lay("fish") && attrsOf(SH.SHADOW_VS[0]) === lay("pred"),
     "the attributes the vertex stages declare are the layouts' (template + instance): " + lay("app") + " / " + lay("fish"));
  ok(Object.values(LA.app.attributes).every((a) => a.length === 4 || a.length === 1) && LA.app.attributes.iGeneSlot.length === 1 && LA.fish.spare.join() === "iX.z,iX.w" && LA.app.spare.length === 0,
     "every component documented; spare: legacy fish and predators iX.z, iX.w; the appearance fish none");
  throws(() => M.layout("app", { "iBody.w": "reef.blink" }), ["iBody.w is reserved for", "reef.blink cannot claim it"], "claiming the appearance pose (iBody.w): refused");
  throws(() => M.layout("fish", { "iX.y": "reef.blink" }), ["iX.y is reserved for"], "claiming the legacy pose (iX.y): refused");
  throws(() => M.layout("pred", { "iBody.w": "reef.blink" }), ["iBody.w is the scene's (ember (1 hunting))"], "claiming a used component (the ember): refused");
  throws(() => M.layout("fish", { "iQ.z": "reef.blink" }), ["iQ.z is not a component of its layout"], "an unknown component: refused");
  const c = M.layout("fish", { "iX.z": "reef.blink" });
  ok(c.id === "fish/1+iX.z=reef.blink" && c.claims["iX.z"] === "reef.blink" && c.spare.join() === "iX.w" && Object.isFrozen(c), "a spare component claimed: its own layout id, the spare one left");
}

section("the predators' faces (a Look's attached pass) follow the predators' vertex features");
{
  const DECL = "attribute vec3 aLoc;\nvarying vec3 vWorld; varying vec3 vLoc; varying float vEmber;";
  const BODY = "  vec3 w = fishWorld(); vWorld = w; vLoc = aLoc; vEmber = iBody.w;\n  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);";
  const FS = "varying vec3 vWorld; varying vec3 vLoc; varying float vEmber;\nvoid main() { gl_FragColor = vec4(vLoc, 1.0); }";
  const S = ctx.EvoOceanShaders;
  S.feature({ id: "faces.sway", abi: 1, targets: ["fish.vs", "fish.shadow.vs", "fish.attach.vs"], append: { "fish.pose": "  // sway" } });
  S.feature({ id: "faces.bad", abi: 1, targets: ["fish.vs"], append: { "fish.pose": "  // posed, not on the faces" } });
  const face = { decl: DECL, body: BODY, fs: FS, uniforms: { uBlinkOn: { value: 0 } } };
  {
    const { B, U } = sceneBinder(ctx, () => ({ ok: true }));
    const predVs = (q) => (q.kind === "pred" && q.stage === "vs" ? q.base.concat(["faces.sway"]) : q.base);
    const r = await B.activate({ look: "faces", features: predVs, attach: { face } });
    ok(r.ok, "a Look with an attached pass on the predators: activated", r);
    for (const v of [0, 1]) {
      const g = B.programs("face", "body", v), pv = B.key("pred", "body", v).split("|vs:")[1].split("|")[0];
      const want = SH.program("fish.attach.vs", SH.parts.fishAttach(DECL, BODY), v ? [F, "faces.sway"] : ["faces.sway"]);
      ok(g.own && g.vs === want && g.fs === FS && g.key.includes("|vs:" + pv + "|") && /\|fs:\(faces:[0-9a-f]{8}\)\|u\d+$/.test(g.key),
         "faces variant " + v + ": fish.attach.vs with the predators' vertex features [" + pv + "], the Look's fragment stage", g.key);
    }
    const v1 = B.programs("face", "body", 1).vs;
    ok(v1.includes("void main() {\n  // sway\n  iPose = poseOf(iX.y);\n" + BODY) && v1.includes("rollTo(") && v1.includes("wagAt(u"),
       "posed as the predators: the pose slot (the Look's line, then the polish's pose read: by id) before the Look's body; the roll and the tail's lag");
    ok(B.material("face", "body", 1).uniforms.uBlinkOn === face.uniforms.uBlinkOn && B.material("face", "body", 1).uniforms.uTime === U.fish.uTime,
       "its uniforms: the Look's beside the predators' (the same objects)");
    const n0 = B.state().entries.length;
    const bad = await B.activate({ look: "faces2", features: (q) => (q.kind === "pred" && q.stage === "vs" ? q.base.concat(["faces.bad"]) : q.base), attach: { face } });
    ok(!bad.ok && bad.stage === "assembly" && /faces.bad poses the predators .* does not target fish.attach.vs/.test(bad.error) && B.state().look === "faces" && B.state().entries.length === n0,
       "a feature posing the predators without targeting fish.attach.vs: refused (the faces would not swim with the body); the set before stays, nothing kept", bad);
  }
}

section("atomic activation");
{
  const S = ctx.EvoOceanShaders;
  S.feature({ id: "glow.emit", abi: 1, targets: ["fish.fs", "app.body.fs"], append: { "fish.emissive": "  murky += vec3(0.0, 0.1, 0.2) * vEmber;", "app.emissive": "  murky += vec3(0.0);" } });
  S.feature({ id: "planted.emit", abi: 1, targets: ["fish.fs", "app.body.fs"], append: { "fish.emissive": "  murky += PLANTED;", "app.emissive": "  murky += PLANTED;" } });
  S.feature({ id: "planted.clash", abi: 1, targets: ["app.body.fs"], append: { "app.fs.decl": "uniform float uTime;" } });
  const compiled = [];
  /* the stand-in compile: fails on a program with PLANTED in it (as a GLSL compile would on the undeclared name) */
  const compile = (items) => { compiled.push(items); const bad = items.filter((x) => /PLANTED/.test(x.material.fragmentShader)).map((x) => x.key);
    return Promise.resolve(bad.length ? { ok: false, error: "did not compile: " + bad.join(", ") } : { ok: true }); };
  const { B } = sceneBinder(ctx, compile);
  const mesh = { material: null };
  B.bind(mesh, "fish", "body", 1);
  const before = mesh.material, n0 = B.state().entries.length;
  ok(B.state().entries.filter((e) => e.state === "reserved").length === 13 - 2, "prepare() made 13 keys' materials and assembled none; one bound: assembled (lazy; its material the predators' too)",
     B.state().entries.map((e) => e.state));
  const emit = (id) => ({ look: "glow", features: (q) => (q.stage === "fs" && q.pass === "body" ? q.base.concat([id]) : q.base) });
  {
    const r1 = await B.activate(emit("planted.emit"));
    B.bind(mesh, "fish", "body", 1);
    ok(!r1.ok && r1.stage === "compile" && /did not compile/.test(r1.error) && compiled.length === 1 && compiled[0].length === 9,
       "a planted compile failure: refused at the compile, which had every reachable variant (13 keys, 9 materials: app 5, fish and pred 4)", { r1, n: compiled[0] && compiled[0].length });
    ok(B.state().look === "" && B.state().version === 0 && mesh.material === before && B.state().entries.length === n0 && B.bound(mesh).key === B.key("fish", "body", 1),
       "  the previous set stays (the mesh bound as before); the failed set's materials dropped", { look: B.state().look, entries: B.state().entries.length, n0 });
    ok(compiled[0].filter((x) => x.key.includes("look:glow")).every((x) => x.material.disposed), "  and disposed");
    const r2 = await B.activate(emit("planted.clash"));
    ok(!r2.ok && r2.stage === "assembly" && /declaration collision: uTime/.test(r2.error) && compiled.length === 1 && B.state().look === "" && B.state().entries.length === n0,
       "a planted assembly error (a declaration collision): refused before any compile; the previous set stays, nothing kept", r2);
    const r3 = await B.activate(emit("glow.emit"));
    B.bind(mesh, "fish", "body", 1);
    ok(r3.ok && r3.keys.length === 13 && r3.materials === 9 && compiled.length === 2 && compiled[1].length === 9 && B.state().look === "glow" && B.state().version === 1,
       "a good set: every reachable variant assembled and compiled (13 keys, 9 materials), then it takes effect", r3);
    ok(mesh.material !== before && mesh.material.fragmentShader === SH.program("fish.fs", SH.parts.fishFs(), [F, "glow.emit"]) && B.bound(mesh).key.includes("look:glow"),
       "  the next bind draws the set's material (fish.fs [full, glow.emit])");
    let release;
    const slow = M.create({ THREE: fakeThree(), compile: () => new Promise((res) => { release = res; }) });
    slow.define("fish", { uniforms: { body: {}, shadow: {} } });
    const p1 = slow.activate(emit("glow.emit")), r4 = await slow.activate(null);
    release({ ok: true });
    const r5 = await p1;
    ok(!r4.ok && /in progress/.test(r4.error) && r5.ok && slow.state().look === "glow", "one activation at a time (a second, while the first compiles: refused)");
    const r6 = await B.activate(null);
    B.bind(mesh, "fish", "body", 1);
    ok(r6.ok && B.state().look === "" && mesh.material === before, "activate(null): back to no Look, the base materials again (cached)");
    const r7 = await B.activate({ look: "x", features: 3 });
    ok(!r7.ok && r7.stage === "spec", "a set that is not one: refused (spec)", r7);
  }
}

section("lazy assembly, and the plain programs on an assembly error");
{
  /* planted: a scan's false positive in the full polish's fragment stage of the legacy fish (a declaration collision
   * only fish.fs [swimPolish.full] has); main built FISH_FS[1] as ocean_shaders.js loaded, so the module (and every
   * fish, plain included) failed */
  const at = 'append["fish.fs.decl"] = POLISH_VARY;';
  const edit = { "ocean_shaders.js": (s) => { if (s.split(at).length !== 2) throw new Error("plant: the anchor moved"); return s.replace(at, 'append["fish.fs.decl"] = POLISH_VARY + "\\nuniform float uTime;";'); } };
  const pc = load(edit);
  ok(!!pc.EvoOceanShaders && !!pc.EvoOceanMaterials, "with the planted collision ocean_shaders.js and ocean_materials.js still load (the polished programs are no longer built as the module loads)");
  throws(() => pc.EvoOceanShaders.FISH_FS, ["fish.fs: declaration collision: uTime", "swimPolish.full (fish.fs.decl)"], "  reading FISH_FS (the eager build main did at load) throws the collision");
  const { B, warned } = sceneBinder(pc);
  const fishBody = { material: null }, predBody = { material: null }, fishShadow = { material: null }, appBody = { material: null };
  const e = [B.bind(fishBody, "fish", "body", 1), B.bind(predBody, "pred", "body", 1), B.bind(fishShadow, "fish", "shadow", 1), B.bind(appBody, "app", "body", 1)];
  ok(e.join() === "0,0,1,1" && fishBody.material === B.material("fish", "body", 0) && predBody.material === B.material("pred", "body", 0),
     "the polished legacy fish and predators: the plain programs drawn (variant 0); their shadow (lite) and the appearance fish polished", e);
  const pv = pc.EvoOceanShaders;
  ok(sha(fishBody.material.vertexShader) === SCENE_SHA256["FISH_VS[0]"] && sha(fishBody.material.fragmentShader) === SCENE_SHA256["FISH_FS[0]"] &&
     sha(fishShadow.material.vertexShader) === SCENE_SHA256["SHADOW_VS[1]"] && sha(appBody.material.fragmentShader) === SCENE_SHA256["app(true).fs"],
     "  byte for byte main's plain fish (c6594734 / 3149e247); the lite shadow and the full appearance fish as main's");
  const b = B.bound(fishBody), st = B.state();
  ok(b.fallback && b.variant === 1 && b.effective === 0 && st.failed.length === 2 && st.failed.every((k) => /\|(fish|pred)\|body\|.*\|v1\|/.test(k)) &&
     st.entries.filter((x) => x.state === "failed").every((x) => /declaration collision: uTime/.test(x.error)),
     "  bound(): asked 1, drew 0 (fallback); state(): the two failed keys and why", { b, failed: st.failed });
  B.bind(fishBody, "fish", "body", 1); B.bind(predBody, "pred", "body", 1);
  ok(warned.length === 1 && warned.every((w) => /could not be assembled: .*declaration collision: uTime.*The plain programs are drawn instead/.test(w)),
     "  said once on the console (one material for both kinds; binding again: no more)", warned);
  const w = B.warm(["fish", "pred"]);
  ok(w.length === 2 && w[0] === B.material("fish", "body", 0) && w[0] === B.material("pred", "body", 0) && w[1] === B.material("fish", "shadow", 1) && w[1] === B.material("pred", "shadow", 1),
     "  the warm list: the plain body stands in for the failed full one (nothing more to compile), then the polished shadow");
  ok(pv.program("fish.fs", pv.parts.fishFs(), []) === SH.FISH_FS[0], "  (the plain fish.fs is the same text: the planted collision is only in the polish)");
  /* lazy: prepare() makes the materials in the scene's old order, assembles none */
  const { B: C } = sceneBinder(ctx);
  const st2 = C.state();
  ok(st2.entries.map((x) => x.key.split("|").slice(1, 3).concat(x.key.split("|")[4]).join(" ")).join(", ") ===
     "fish body v0, pred body v0, fish body v1, pred body v1, fish shadow v0, pred shadow v0, fish shadow v1, pred shadow v1, app body v0, app body v1, app shadow v0, app shadow v1, app litSkip v0",
     "prepare(): the materials made pass by pass, plain then polished, in the scene's old order (three sorts opaque draws by material id)");
  ok(st2.entries.every((x) => x.state === "reserved"), "  none assembled until first drawn, warmed or activated");
  const wa = C.warm(["app"]);
  ok(wa.length === 3 && C.state().entries.filter((x) => x.state === "ready").map((x) => x.key.split("|").slice(1, 3).concat(x.key.split("|")[4]).join(" ")).join(", ") === "app body v1, app shadow v1, app litSkip v0",
     "  warm(app): its full body, its polished shadow and the split's main draw (as the scene warmed them), assembled then");
}

const S = ctx.EvoOceanShaders;
const tick = () => new Promise((r) => setImmediate(r));
section("review P1-1: the legacy fish and the predators share their materials, as on main");
{
  const { B } = sceneBinder(ctx);
  const same = ["body", "shadow"].every((p) => [0, 1].every((v) => B.material("fish", p, v) === B.material("pred", p, v)));
  ok(same && B.state().materials === 9, "fish and pred: one material per pass and variant (main's fishMats[v] / shadowMats[v]); 9 materials in all");
  const ids = [["fish", "body", 0], ["fish", "body", 1], ["fish", "shadow", 0], ["fish", "shadow", 1], ["app", "body", 0], ["app", "body", 1], ["app", "shadow", 0], ["app", "shadow", 1], ["app", "litSkip", 0]]
    .map(([k, p, v]) => B.material(k, p, v).id);
  ok(ids.every((x, i) => i === 0 || x === ids[i - 1] + 1), "made in main's order, one id after another: legacy body 0, body 1, shadow 0, shadow 1; app body 0, 1, shadow 0, 1, the split's", ids);
  const mf = { material: null }, mp = { material: null };
  B.bind(mf, "fish", "body", 1); B.bind(mp, "pred", "body", 1);
  ok(mf.material === mp.material && B.bound(mf).key.includes("|fish|") && B.bound(mp).key.includes("|pred|"), "bound(): the kinds keep their own keys over the one material");
  S.feature({ id: "share.pred", abi: 1, targets: ["fish.vs"], append: { "fish.varyings": "  // share.pred" } });
  const U2 = { b: { uTime: { value: 0 } }, s: {} };
  const mk = () => { const C = M.create({ THREE: fakeThree() }); C.define("fish", { uniforms: { body: U2.b, shadow: U2.s } }); C.define("pred", { uniforms: { body: U2.b, shadow: U2.s } }); return C; };
  const C1 = mk();
  await C1.activate({ look: "share", features: (q) => (q.kind === "pred" && q.stage === "vs" && q.pass === "body" ? q.base.concat(["share.pred"]) : q.base) });
  ok(C1.material("fish", "body", 1) !== C1.material("pred", "body", 1) && C1.material("fish", "shadow", 1) === C1.material("pred", "shadow", 1),
     "a Look with features for the predators only: their bodies' materials apart, the shadows still one");
  const C2 = mk();
  await C2.activate({ look: "share", uniforms: { pred: { uEye: { value: 1 } } } });
  ok(C2.material("fish", "body", 0) !== C2.material("pred", "body", 0) && C2.material("pred", "body", 0).uniforms.uEye, "uniforms of their own for the predators: apart");
  const C3 = mk();
  await C3.activate({ look: "share", claims: { fish: { "iX.z": "share.x" } } });
  ok(C3.material("fish", "body", 0) !== C3.material("pred", "body", 0), "a claim on the legacy fish's layout only: apart");
  const C4 = mk();
  await C4.activate({ look: "share" });
  ok(C4.material("fish", "body", 1) === C4.material("pred", "body", 1) && C4.state().materials === 4, "a Look that changes neither: one again (4 materials for the 8 keys)", C4.state().materials);
}

section("review P2-1, re-check P2-R1: a Look's faces keyed by their GLSL; a Look's own uniform objects in its keys");
{
  const DECL = "attribute vec3 aLoc;\nvarying vec3 vLoc;", BODY = "  vec3 w = fishWorld(); vLoc = aLoc;\n  gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);";
  const FS1 = "varying vec3 vLoc;\nvoid main() { gl_FragColor = vec4(vLoc, 1.0); }", FS2 = "varying vec3 vLoc;\nvoid main() { gl_FragColor = vec4(vLoc * 0.5, 1.0); }";
  const face = (fs, u, o) => Object.assign({ decl: DECL, body: BODY, fs: fs, uniforms: u }, o ? { options: o } : {});
  const { B } = sceneBinder(ctx, () => ({ ok: true }));
  const holderA = { value: 1 }, faceA = { value: 2 }, fishUA = { uRf: holderA }, faceUA = { uFace: faceA };
  await B.activate({ look: "rf", uniforms: { fish: fishUA }, attach: { face: face(FS1, faceUA) } });
  const k1 = B.key("face", "body", 0), kf1 = B.key("fish", "body", 0), mesh = { material: null }, fm = { material: null };
  B.bind(mesh, "fish", "body", 0); B.bind(fm, "face", "body", 0);
  const mA = mesh.material, fA = fm.material;
  ok(mA.uniforms.uRf === holderA && fA.uniforms.uFace === faceA && /\|u\d+$/.test(kf1) && /\|u\d+$/.test(k1) && !/\|u\d+$/.test(B.key("pred", "body", 0)),
     "on: the Look's uniform objects in its materials (legacy fish, faces); in their keys by identity (the predators, with none, without)", { kf1, k1 });
  await B.activate(null);
  ok(!mA.disposed && !fA.disposed, "off: the Look's materials kept for one switch");
  await B.activate({ look: "rf", uniforms: { fish: fishUA }, attach: { face: face(FS1, faceUA) } });
  B.bind(mesh, "fish", "body", 0); B.bind(fm, "face", "body", 0);
  ok(B.key("face", "body", 0) === k1 && mesh.material === mA && fm.material === fA, "on again with the same objects: the same keys, its kept materials (nothing made, nothing compiled anew)");
  await B.activate(null);
  const holderB = { value: 3 }, faceB = { value: 4 }, fishUB = { uRf: holderB }, faceUB = { uFace: faceB };
  await B.activate({ look: "rf", uniforms: { fish: fishUB }, attach: { face: face(FS1, faceUB) } });
  B.bind(mesh, "fish", "body", 0); B.bind(fm, "face", "body", 0);
  ok(B.key("face", "body", 0) !== k1 && mesh.material !== mA && mesh.material.uniforms.uRf === holderB && fm.material.uniforms.uFace === faceB &&
     mesh.material.vertexShader === mA.vertexShader && mesh.material.fragmentShader === mA.fragmentShader,
     "off, then on with new uniform objects (the same Look id): new keys, new materials holding them, the same programs");
  ok(mA.uniforms.uRf === holderA && fA.uniforms.uFace === faceA, "  the first materials never written (no uniform object is)");
  const holderC = { value: 5 };
  await B.activate({ look: "rf", uniforms: { fish: { uRf: holderC } }, attach: { face: face(FS1, faceUB) } });
  B.bind(mesh, "fish", "body", 0);
  ok(mesh.material.uniforms.uRf === holderC, "on again straight from on (no off between) with others: the new ones too");
  await B.activate({ look: "rf", uniforms: { fish: fishUB }, attach: { face: face(FS2, faceUB) } });
  const k2 = B.key("face", "body", 0);
  ok(k2 !== k1 && B.programs("face", "body", 0).fs.includes("vLoc * 0.5"), "the same Look id with other faces' GLSL (the same uniform objects): another key, its own program");
  await B.activate({ look: "rf", uniforms: { fish: fishUB }, attach: { face: face(FS2, faceUB, { side: 0 }) } });
  ok(B.key("face", "body", 0) !== k2, "... and with other material options: another key");
}

section("re-check P2-R1: the binder never writes the scene's uniform objects (a Look's uniforms for a kind appearing on re-activation)");
{
  const sceneSelect = { value: "the scene's" };
  const fishU = { uTime: { value: 0 }, uSelect: sceneSelect }, shadowU = { uAlpha: { value: 0.4 } };
  const before = Object.keys(fishU).join();
  const B = M.create({ THREE: fakeThree(), compile: () => ({ ok: true }) });
  B.define("fish", { uniforms: { body: fishU, shadow: shadowU } }); B.define("pred", { uniforms: { body: fishU, shadow: shadowU } });
  B.prepare(["fish", "pred"]);
  const base = B.material("fish", "body", 0);
  await B.activate({ look: "x" });
  ok(B.material("pred", "body", 0).uniforms === fishU && B.material("fish", "body", 0) === B.material("pred", "body", 0), "a Look without uniforms of its own: the scene's object, fish and predators sharing");
  const lookSelect = { value: "the Look's" };
  await B.activate({ look: "x", uniforms: { pred: { uSelect: lookSelect, uEye: { value: 1 } } } });
  ok(fishU.uSelect === sceneSelect && Object.keys(fishU).join() === before, "the same Look again, now with predator uniforms: the scene's fishUniforms untouched (its uSelect, no uEye)");
  ok(B.material("fish", "body", 0) !== B.material("pred", "body", 0) && B.material("pred", "body", 0).uniforms.uSelect === lookSelect && B.material("fish", "body", 0).uniforms.uSelect === sceneSelect,
     "  fish and predators apart under it: the predators draw the Look's uSelect, the fish the scene's");
  await B.activate(null);
  ok(B.material("fish", "body", 0) === base && base.uniforms === fishU && fishU.uSelect === sceneSelect && !("uEye" in fishU), "back to no Look: the base material, the scene's own uSelect");
}

section("re-check P3-R1: a failing one-kind activation never drops what a newer activation took up");
{
  let hold = null;
  /* the appearance kind's own activation held (its compile a promise released later); every other compile at once */
  const compile = (items) => (hold === null && items.every((x) => x.kind === "app") ? new Promise((res) => { hold = res; }) : Promise.resolve({ ok: true }));
  const U = { fish: { uTime: { value: 0 } }, shadow: {}, app: { uGenes: { value: null } }, appShadow: {} };
  const B = M.create({ THREE: fakeThree(), compile, warn: () => {} });
  B.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); B.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } }); B.prepare(["fish", "pred"]);
  const features = (q) => q.base;
  await B.activate({ look: "k", features });
  B.define("app", { uniforms: { body: U.app, shadow: U.appShadow }, env: { EA } });
  B.prepare(["app"]);   /* (its own activation of "k" starts, and waits) */
  await tick();
  const r = await B.activate({ look: "k", features });   /* a newer activation, the same keys: it takes up the app entries */
  const m = { material: null };
  B.bind(m, "app", "body", 1);
  const taken = m.material, n = B.state().entries.length;
  hold({ ok: false, error: "planted" });   /* the older one fails now */
  await tick(); await tick();
  B.bind(m, "app", "body", 1);
  ok(r.ok && hold && /look:k/.test(B.bound(m).key) && m.material === taken && !taken.disposed && B.state().entries.length === n,
     "the newer set's entries kept (not dropped, not disposed) when the older one-kind activation fails after it", { ok: r.ok, entries: [n, B.state().entries.length], disposed: taken.disposed });
}

section("review P2-2: a kind defined while a Look is active");
{
  const compiled = [];
  const compile = (items) => { compiled.push(items.map((x) => x.key)); return Promise.resolve({ ok: true }); };
  S.feature({ id: "later.app", abi: 1, targets: ["app.body.fs"], append: { "app.emissive": "  murky += vec3(0.0);" } });
  const extra = { uLook: { value: 7 } };
  const B = M.create({ THREE: fakeThree(), compile });
  const U = { fish: { uTime: { value: 0 } }, shadow: {}, app: { uGenes: { value: null } }, appShadow: {} };
  B.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); B.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } }); B.prepare(["fish", "pred"]);
  await B.activate({ look: "later", uniforms: { app: extra }, features: (q) => (q.kind === "app" && q.stage === "fs" && q.pass === "body" ? q.base.concat(["later.app"]) : q.base) });
  U.app.uClarityLike = { value: 0.5 };   /* (the scene's clarityUniforms(U), before define: AppKind's) */
  B.define("app", { uniforms: { body: U.app, shadow: U.appShadow }, env: { EA } });
  B.prepare(["app"]);
  const m = { material: null };
  B.bind(m, "app", "body", 1);
  const before = B.bound(m).key;
  await tick(); await tick();
  B.bind(m, "app", "body", 1);
  ok(/look:-/.test(before) && /look:later/.test(B.bound(m).key) && m.material.fragmentShader.includes("murky += vec3(0.0);"),
     "drawn under the base set until its own activation of the Look compiled, then the Look's", { before, after: B.bound(m).key });
  ok(compiled.length === 2 && compiled[1].length === 5 && compiled[1].every((k) => k.includes("|app|")) && B.state().covered.indexOf("app") >= 0,
     "its own activation: the kind's variants alone (5), compiled; then covered", compiled[1]);
  ok(m.material.uniforms.uClarityLike === U.app.uClarityLike && m.material.uniforms.uLook === extra.uLook && B.material("app", "litSkip", 0).uniforms.uClarityLike === U.app.uClarityLike &&
     B.material("app", "body", 0).uniforms.uClarityLike === U.app.uClarityLike,
     "its uniforms: the kind's (with what the scene added before define: its clarity) and the Look's, in every body material");
  const warned = [];
  const B2 = M.create({ THREE: fakeThree(), compile, warn: (x) => warned.push(x) });
  B2.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); B2.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
  await B2.activate({ look: "throws", features: (q) => { if (q.kind === "app") throw new Error("no app here"); return q.base; } });
  let threw = null;
  try { B2.define("app", { uniforms: { body: U.app, shadow: U.appShadow }, env: { EA } }); B2.prepare(["app"]); } catch (e) { threw = e.message; }
  await tick(); await tick();
  const m2 = { material: null };
  ok(threw === null && B2.bind(m2, "app", "body", 0) === 0 && /look:-/.test(B2.bound(m2).key) && m2.material.vertexShader === app(false).vs &&
     warned.length === 1 && /could not be made for the appearance fish: .*no app here/.test(warned[0]),
     "a Look whose features() throw for the new kind: prepare() does not throw, the kind is drawn without it, said once", { threw, warned });
  /* a key that cannot be worked out at bind time (not reachable, so not activated): said once, not each frame */
  const B3 = M.create({ THREE: fakeThree(), compile, warn: (x) => warned.push(x) });
  B3.define("fish", { uniforms: { body: U.fish, shadow: U.shadow } }); B3.define("pred", { uniforms: { body: U.fish, shadow: U.shadow } });
  B3.define("app", { uniforms: { body: U.app, shadow: U.appShadow }, env: { EA } });
  const odd = { on: false };   /* (an impure features(): fine while the set is activated, throwing after) */
  await B3.activate({ look: "odd", features: (q) => { if (q.pass === "body" && q.kind === "app" && q.variant === 1 && q.stage === "vs" && odd.on) throw new Error("odd"); return q.base; } });
  odd.on = true;
  const n0 = warned.length;
  for (let i = 0; i < 5; i++) B3.bind({ material: null }, "app", "litSkip", 1);
  ok(warned.length === n0 + 1 && /could not be keyed: .*odd/.test(warned[n0]), "a key that throws at bind time: the plain programs, said once (5 binds, 1 line)", warned.slice(n0));
}

section("review P3-1: the compile's check (compiler())");
{
  function fakeRenderer(progs, opts) {
    opts = opts || {};
    const gl = { LINK_STATUS: 0x8B82, getProgramParameter: (p, k) => (k === 0x8B82 ? p.linked : null) };
    return { debug: { checkShaderErrors: !!opts.checkShaderErrors }, getContext: () => gl,
             properties: { get: (m) => ({ currentProgram: progs.get(m) }) },
             compileAsync: opts.hang ? () => new Promise(() => {}) : () => Promise.resolve() };
  }
  const T3 = { Scene: function () { this.add = function () {}; }, Mesh: function (g, m) { this.material = m; } };
  const timers = { sets: 0, clears: 0, last: null, set(f) { this.sets++; this.last = f; return 1; }, clear() { this.clears++; } };
  const mat = (k) => ({ key: k });
  const prog = (linked, extra) => Object.assign({ program: { linked }, getUniforms() {}, diagnostics: null }, extra || {});
  const items = (ms) => ms.map((m) => ({ key: m.key, kind: "fish", pass: "body", variant: 0, material: m, geometry: null }));
  const a = mat("a"), b = mat("b");
  const geometry = () => ({});
  let r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, prog(true)], [b, prog(true)]])), geometry, timers })(items([a, b]));
  ok(r.ok && timers.sets === 1 && timers.clears === 1, "linked and runnable: ok; the budget's timer cleared once settled", { r, timers: [timers.sets, timers.clears] });
  r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, prog(true)], [b, prog(false)]]), { checkShaderErrors: false }), geometry, timers })(items([a, b]));
  ok(!r.ok && r.error === "did not compile: b", "three's checkShaderErrors off (no diagnostics): the GL link status still refuses a broken program", r);
  r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, prog(true, { diagnostics: { runnable: false } })]])), geometry, timers })(items([a]));
  ok(!r.ok && /did not compile: a/.test(r.error), "three's diagnostics not runnable: refused", r);
  r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, prog(true, { getUniforms() { throw new Error("moved"); } })]])), geometry, timers })(items([a]));
  ok(!r.ok && /could not be checked: moved/.test(r.error), "a check that throws (say three moved getUniforms): a refusal, not an unhandled rejection", r);
  r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, undefined]])), geometry, timers })(items([a]));
  ok(!r.ok, "no program for a material: refused", r);
  const p = M.compiler({ THREE: T3, renderer: fakeRenderer(new Map(), { hang: true }), geometry, timers, budgetMs: 60000 })(items([a]));
  timers.last();
  r = await p;
  ok(!r.ok && /did not finish in 60 s/.test(r.error), "a compile that never finishes: refused at the budget", r);
  r = await M.compiler({ THREE: T3, renderer: fakeRenderer(new Map()), geometry, timers, lost: () => true })(items([a]));
  ok(!r.ok && /lost/.test(r.error), "a lost context: refused", r);
  /* the default timers against the browser's rule: setTimeout / clearTimeout called with any `this` but the global (or none)
   * throw "Illegal invocation" (node's do not care, so a detached native only failed in the browser: g3 at 33fd919) */
  {
    const calls = { set: 0, clear: 0 };
    const strict = vm.createContext({ console });
    strict.window = strict; strict.globalThis = strict;
    strict.setTimeout = function (f, ms) { if (this !== undefined && this !== strict) throw new TypeError("Illegal invocation"); calls.set++; return setTimeout(f, ms); };
    strict.clearTimeout = function (t) { if (this !== undefined && this !== strict) throw new TypeError("Illegal invocation"); calls.clear++; clearTimeout(t); };
    for (const f of ["ocean_appearance.js", "ocean_shaders.js", "ocean_materials.js"]) vm.runInContext(fs.readFileSync(path.join(WEB, f), "utf8"), strict, { filename: f });
    const rs = await strict.EvoOceanMaterials.compiler({ THREE: T3, renderer: fakeRenderer(new Map([[a, prog(true)]])), geometry })(items([a]));
    ok(rs.ok && calls.set === 1 && calls.clear === 1, "the default timers (no opts.timers) under a this-strict setTimeout / clearTimeout, as a browser's: ok, set and cleared",
       { rs, calls });
  }
}

section("review P3: the plain fallback, the split's skip, features() once, freeing, a said failure, the skip first");
{
  /* P3-2: not even the plain programs: material() throws (the scene's "unavailable" path, not three's default shader) */
  const B = M.create({ THREE: fakeThree(), warn: () => {} });
  B.define("app", { uniforms: { body: {}, shadow: {} }, env: {} });
  throws(() => B.material("app", "body", 0), ["could not be assembled, nor their plain ones", "appearance law"], "P3-2: no plain programs: material() throws");
  const mesh = { material: "before" };
  B.bind(mesh, "app", "body", 0);
  ok(mesh.material === "before", "  bind() leaves the mesh's material as it was");
  /* P3-3: the split's skip not assembling (planted: the skip's line declares a name main() has): has() says so; the scene then
   * draws the whole kind on the full programs instead of drawing the lit fish twice */
  const sk = load({ "ocean_shaders.js": (s) => s.replace('var LIT_SKIP_GLSL = "  if (iBody.z < 0.0)', 'var LIT_SKIP_GLSL = "  vec3 w = vec3(0.0); if (iBody.z < 0.0)') });
  const { B: K } = sceneBinder(sk);
  const ms = { material: null };
  ok(K.has("app", "body", 1) && !K.has("app", "litSkip", 0) && K.bind(ms, "app", "litSkip", 0) === 0 && K.bound(ms).fallback,
     "P3-3: has(app, litSkip, 0) false when the skip does not assemble (its bind a fallback); has() true for the full body");
  /* P3-4: features() runs while a set is worked out, never per bind */
  let calls = 0;
  const { B: F2 } = sceneBinder(ctx, () => ({ ok: true }));
  await F2.activate({ look: "count", features: (q) => { calls++; return q.base; } });
  const c0 = calls, mm = { material: null };
  for (let i = 0; i < 200; i++) { F2.bind(mm, "fish", "body", i & 1); F2.bind(mm, "app", "body", i & 1); F2.bind(mm, "app", "litSkip", 0); F2.bind(mm, "pred", "shadow", i & 1); }
  ok(c0 > 0 && calls === c0, "P3-4: features() ran " + c0 + " times for the activation, none for 800 binds");
  /* P3-5 (and the re-check's P3-R2): the replaced sets' materials freed, the one replaced right now kept for one switch */
  const { B: E } = sceneBinder(ctx, () => ({ ok: true }));
  await E.activate({ look: "one", uniforms: { fish: { u1: { value: 1 } } } });
  const one = E.material("fish", "body", 0);
  await E.activate({ look: "two", uniforms: { fish: { u2: { value: 2 } } } });
  const two = E.material("fish", "body", 0), nTwo = E.state().entries.length;
  ok(!one.disposed && !two.disposed && nTwo === 13 * 3, "P3-5, P3-R2: a set replaced by another: kept for this one switch (off and on again relinks its programs)", nTwo);
  await E.activate(null);
  const base = E.material("fish", "body", 0);
  ok(one.disposed && !two.disposed && E.state().entries.every((x) => !/look:one/.test(x.key)) && E.state().entries.length === 13 * 2,
     "  one switch later: its materials disposed, its keys gone; the set replaced now kept", E.state().entries.length);
  await E.activate(null);
  ok(two.disposed && !base.disposed && E.state().entries.length === 13 && E.state().materials === 9, "  and the next: the base set's 13 keys and 9 materials alone");
  /* P3-7: an entry made before (reserved), failing in an activation: said, as its binds will fall back */
  const pc = load({ "ocean_shaders.js": (s) => s.replace('append["fish.fs.decl"] = POLISH_VARY;', 'append["fish.fs.decl"] = POLISH_VARY + "\\nuniform float uTime;";') });
  const { B: P, warned: pw } = sceneBinder(pc, () => ({ ok: true }));
  const rp = await P.activate(null);
  ok(!rp.ok && rp.stage === "assembly" && pw.length === 1 && /\|fish\|body\|.*\|v1\|.*could not be assembled/.test(pw[0]), "P3-7: a base entry failing in an activation: refused, and said on the console", { rp, pw });
  /* P3-8: no feature ahead of the split's skip in app.pose */
  S.feature({ id: "early.pose", abi: 1, targets: ["app.body.vs"], order: -2, append: { "app.pose": "  // early" } });
  S.feature({ id: "a.pose", abi: 1, targets: ["app.body.vs"], order: -1, append: { "app.pose": "  // a" } });
  S.feature({ id: "z.pose", abi: 1, targets: ["app.body.vs"], order: -1, append: { "app.pose": "  // z" } });
  for (const [id, good] of [["early.pose", false], ["a.pose", false], ["z.pose", true]]) {
    const { B: Q } = sceneBinder(ctx, () => ({ ok: true }));
    const rq = await Q.activate({ look: "order", features: (q) => (q.kind === "app" && q.stage === "vs" && q.pass === "body" ? q.base.concat([id]) : q.base) });
    ok(good ? rq.ok && Q.programs("app", "litSkip", 0).vs.includes(SH.LIT_SKIP_GLSL + "\n  // z") : !rq.ok && /ahead of the split's skip/.test(rq.error),
       "P3-8: " + id + (good ? " (order -1, its id after scene.litSkip): after the skip" : ": refused (it would run ahead of the skip)"), rq);
  }
}

section("review P3-9: one writer of .material in web/ (a source scan)");
{
  const files = fs.readdirSync(WEB).filter((f) => f.endsWith(".js") && f !== "scene3d.js" && f !== "ocean_materials.js");
  const hits = [];
  for (const f of files) fs.readFileSync(path.join(WEB, f), "utf8").split("\n").forEach((l, i) => { if (/\.material\s*=(?!=)/.test(l)) hits.push(f + ":" + (i + 1)); });
  const own = fs.readFileSync(path.join(WEB, "ocean_materials.js"), "utf8").split("\n").filter((l) => /\.material\s*=(?!=)/.test(l));
  ok(hits.length === 0 && own.length === 1 && /mesh\.material = u\.e\.rec\.material/.test(own[0]),
     "no .material = in web/*.js (" + files.length + " files; vendor/ and Classic's scene3d.js aside) but the binder's one, in bind()", { hits, own });
}

console.log((fails ? "FAIL" : "ok") + ": " + (checks - fails) + "/" + checks + " checks");
process.exit(fails ? 1 : 0);
}
main().catch((e) => { console.log("FAIL: " + (e && e.stack || e)); process.exit(1); });
