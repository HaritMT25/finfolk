// The render browser harness's URL and effective-policy seams, without a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const src = fs.readFileSync(path.join(__dirname, "ocean_render_browser.mjs"), "utf8");
const start = src.indexOf("function benchUrl("), end = src.indexOf("/* The swim polish's size weights", start);
assert(start > 0 && end > start);
const ctx = vm.createContext({ URLSearchParams, BASE: "http://candidate", MAIN_QUERY: "renderOpt=0", QUERY: "renderOpt=0" });
vm.runInContext(src.slice(start, end), ctx);
const c = { worldSeed: 42, population: 10, world: [100, 100, 80], speed: 1, config: {} };
for (const base of ["http://candidate", "http://main"]) {
  assert.equal(new URL(ctx.benchUrl(c, {}, base)).searchParams.get("renderOpt"), "0");
}
// Same-origin A/A still distinguishes the explicitly selected side's query.
assert.equal(new URL(ctx.benchUrl(c, {}, "http://candidate", "renderOpt=1")).searchParams.get("renderOpt"), "1");
assert.equal(new URL(ctx.benchUrl(c, {}, "http://candidate", "")).searchParams.has("renderOpt"), false);
const ref = { lod: "quality", decoded: false, barbels: "body" };
assert(ctx.sameOffImagePolicy(ref, { ...ref }));
for (const [key, value] of [["lod", "screen"], ["decoded", true], ["barbels", "gated"]]) {
  assert.equal(ctx.sameOffImagePolicy(ref, { ...ref, [key]: value }), false);
}
assert.equal(ctx.sameOffImagePolicy(null, ref), false);
assert.equal(ctx.sameOffImagePolicy(ref, null), false);
assert.equal(ctx.sameOffImagePolicy({}, {}), false);
assert.equal(ctx.sameOffImagePolicy({ ...ref, lod: "unknown" }, { ...ref, lod: "unknown" }), false);
console.log("all 12 render query / effective-policy checks passed");
