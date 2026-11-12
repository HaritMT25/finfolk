// tests/ui_parity_harness_tests.mjs: the paired browser harness's parts that need no browser (tests/ui_parity_browser.mjs), in node;
// CI's "web ui" job. node tests/ui_parity_harness_tests.mjs  (exit 0 = pass)
//   - the selection (--plan): unknown worlds, sets and cases, and a selection that runs nothing (a case whose worlds the
//     --worlds filter leaves out), with or without --smoke, are refused (exit 2) before any browser; the real fixture's plan
//   - the fixture's own checks: a case id used twice, a shot name used twice in a case and world, an unknown step or
//     expectation, a selector missing for a world the step runs on, a world without a shot, a policy without its why
//   - --out: a run never writes into a directory with older pictures; --clean refuses a directory with files it did not write
//   - --compare as a gate, on synthetic runs: identical and noise-only pictures pass; a picture beyond its policy and a size
//     change fail (and are only listed with --report); a missing manifest, an incomplete run, a capture missing or changed
//     since its run, a stale PNG, captures on one side only, different harness or fixture files and an empty comparison are
//     INVALID in both modes; --sets / --cases / --worlds narrow it; a shot's own policy is honoured
// The review of PR #89 (729b5ba): --compare compared whatever PNG names two directories shared and always exited 0; a world
// filter could leave nothing to run and still succeed.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HARNESS = path.join(HERE, "ui_parity_browser.mjs");
const FIXTURE = path.join(HERE, "fixtures", "ui_parity_cases.json");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "ui-parity-harness-"));
let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "\n       " + String(typeof info === "string" ? info : JSON.stringify(info)).slice(0, 900) : "")); }
  else console.log("  ok   " + what);
}
const section = (s) => console.log("== " + s);
/* the harness with these flags: {code, out} (stdout and stderr together); no browser is ever reached in these tests */
function harness(...args) {
  const r = spawnSync(process.execPath, [HARNESS, ...args], { encoding: "utf8", timeout: 60000, env: Object.assign({}, process.env, { PLAYWRIGHT: path.join(TMP, "no-playwright-here") }) });
  return { code: r.status, out: (r.stdout || "") + (r.stderr || "") };
}

section("the selection (--plan): refused before any browser when it is not valid or runs nothing");
{
  let r = harness("--plan", "--sets", "S0,S2");
  ok(r.code === 0 && /plan: 10 case runs, 41 captures, 0 smoke runs/.test(r.out), "the real fixture's S0 + S2: 10 case runs, 41 captures", r.out);
  r = harness("--plan", "--cases", "s0_classic_flat", "--worlds", "ocean");
  ok(r.code === 2 && /runs no case/.test(r.out), "a Classic-only case with --worlds ocean: refused (it ran nothing and said ok before)", r.out);
  r = harness("--plan", "--smoke", "--cases", "s0_classic_flat", "--worlds", "ocean");
  ok(r.code === 2 && /runs no case/.test(r.out), "  the same with --smoke: refused too (cases were asked for)", r.out);
  r = harness("--plan", "--worlds", "ocen");
  ok(r.code === 2 && /no world "ocen"/.test(r.out), "a misspelt world: refused", r.out);
  r = harness("--plan", "--worlds", "classic,classic");
  ok(r.code === 2 && /twice/.test(r.out), "a world named twice: refused", r.out);
  r = harness("--plan", "--worlds", ",");
  ok(r.code === 2 && /no world/.test(r.out), "--worlds naming no world: refused", r.out);
  r = harness("--plan", "--sets", "S9");
  ok(r.code === 2 && /no case is in set "S9"/.test(r.out), "a set no case is in: refused", r.out);
  r = harness("--plan", "--cases", "s0_shel");
  ok(r.code === 2 && /no case "s0_shel"/.test(r.out), "an unknown case: refused", r.out);
  r = harness("--plan", "--layout", "sight");
  ok(r.code === 2 && /--layout/.test(r.out), "an unknown layout: refused", r.out);
  r = harness("--plan", "--smoke");
  ok(r.code === 0 && /0 case runs, 0 captures, 2 smoke runs/.test(r.out), "--smoke alone: the two routes' smoke, no case", r.out);
  r = harness("--plan", "--smoke", "--layout", "site", "--worlds", "ocean");
  ok(r.code === 0 && /2 smoke runs/.test(r.out) && /ocean_alias_site \/ocean\.html/.test(r.out), "--smoke on the site's Ocean: / and its old name /ocean.html", r.out);
  r = harness("--plan", "--sets", "S0", "--bogus");
  ok(r.code === 2 && /unknown flag --bogus/.test(r.out), "an unknown flag: refused", r.out);
  r = harness("--plan", "--sets");
  ok(r.code === 2 && /needs a value/.test(r.out), "a flag without its value: refused", r.out);
  r = harness("--report", "--sets", "S0");
  ok(r.code === 2 && /--report goes with --compare/.test(r.out), "--report without --compare: refused", r.out);
  r = harness("--sets", "S0");
  ok(r.code === 2 && /--out DIR is needed/.test(r.out), "a run without --out: refused", r.out);
}

section("the fixture's own checks");
{
  const base = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  const tryFix = (name, mutate) => {
    const f = JSON.parse(JSON.stringify(base));
    mutate(f);
    const p = path.join(TMP, name + ".json");
    fs.writeFileSync(p, JSON.stringify(f));
    return harness("--plan", "--cases-file", p);
  };
  let r = tryFix("plain", () => {});
  ok(r.code === 0, "the fixture as committed passes its checks", r.out);
  r = tryFix("dup_case", (f) => f.cases.push(JSON.parse(JSON.stringify(f.cases[0]))));
  ok(r.code === 2 && /used twice/.test(r.out), "a case id used twice: refused (its pictures would overwrite each other)", r.out);
  r = tryFix("dup_shot", (f) => f.cases[0].steps.push({ do: "shot", name: f.cases[0].steps[1].name }));
  ok(r.code === 2 && /twice on classic/.test(r.out), "a shot name used twice in a case and world: refused", r.out);
  r = tryFix("dup_shot_worlds", (f) => { const c = f.cases.find((x) => x.id === "s2_controls"); c.steps.push({ do: "shot", name: "pausebtn_focus", world: "ocean" }); });
  ok(r.code === 2 && /twice on ocean/.test(r.out), "  also when the second is limited to one world", r.out);
  r = tryFix("same_name_other_world", (f) => { const c = f.cases.find((x) => x.id === "s2_controls"); c.steps.push({ do: "shot", name: "view_kb_open", world: "classic", expect: {} }); });
  ok(r.code === 0, "  the same name on the other world only is not a collision (its file names the world)", r.out);
  r = tryFix("bad_step", (f) => f.cases[0].steps.push({ do: "hover", sel: "#x" }));
  ok(r.code === 2 && /unknown step/.test(r.out), "an unknown step: refused", r.out);
  r = tryFix("bad_key", (f) => f.cases[0].steps.push({ do: "settle", franes: 3 }));
  ok(r.code === 2 && /unknown key franes/.test(r.out), "a misspelt step key: refused", r.out);
  r = tryFix("sel_world", (f) => f.cases.find((x) => x.id === "s2_tabs").steps.push({ do: "click", sel: { classic: "#x" } }));
  ok(r.code === 2 && /no selector for ocean/.test(r.out), "a selector missing for a world the step runs on: refused", r.out);
  r = tryFix("bad_expect", (f) => { f.cases[0].steps[1].expect = { focused: null }; });
  ok(r.code === 2 && /unknown expectation focused/.test(r.out), "an unknown expectation: refused", r.out);
  r = tryFix("no_shot", (f) => { const c = f.cases.find((x) => x.id === "s0_family"); c.steps = c.steps.filter((s) => s.do !== "shot"); c.steps.push({ do: "shot", name: "x", world: "ocean" }); });
  ok(r.code === 2 && /no shot on classic/.test(r.out), "a world of a case without a shot: refused", r.out);
  r = tryFix("policy_why", (f) => { f.defaults.compare = { tolerance: 1, maxPixels: 8 }; });
  ok(r.code === 2 && /says why/.test(r.out), "a difference policy without its why: refused", r.out);
  r = tryFix("step_world", (f) => f.cases.find((x) => x.id === "s0_classic_flat").steps.push({ do: "settle", world: "ocean" }));
  ok(r.code === 2 && /not one of the case's/.test(r.out), "a step limited to a world the case does not run: refused", r.out);
}

section("--out: never a directory with an older run's pictures");
{
  const d = path.join(TMP, "old_run");
  fs.mkdirSync(d);
  fs.writeFileSync(path.join(d, "s0_shell__classic__live.png"), "old");
  let r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", d);
  ok(r.code === 2 && /is not empty/.test(r.out) && fs.existsSync(path.join(d, "s0_shell__classic__live.png")), "a run into a directory with an older picture: refused, the picture left", r.out);
  fs.writeFileSync(path.join(d, "notes.txt"), "mine");
  r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", d, "--clean");
  ok(r.code === 2 && /does not write/.test(r.out) && fs.existsSync(path.join(d, "notes.txt")) && fs.existsSync(path.join(d, "s0_shell__classic__live.png")),
     "--clean with a file the harness did not write: refused, nothing removed", r.out);
}

/* ---------------- synthetic runs for --compare ---------------- */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(b) { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function chunk(type, data) { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; }
/* a w x h picture, grey 100, with edits: [[x, y, value], ...] */
function png(w, h, edits) {
  const px = Buffer.alloc(w * h * 4, 100);
  for (let i = 3; i < px.length; i += 4) px[i] = 255;
  for (const [x, y, v] of edits || []) { const o = (y * w + x) * 4; px[o] = px[o + 1] = px[o + 2] = v; }
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) px.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4);
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
const POLICY = { tolerance: 1, maxPixels: 8, why: "test" };
/* a run directory as the harness writes it: pictures {file: {set, buf, policy}} and its manifest */
let runN = 0;
function makeRun(pics, o) {
  o = o || {};
  const dir = path.join(TMP, "run" + (++runN));
  fs.mkdirSync(dir);
  const captures = {};
  for (const [file, p] of Object.entries(pics)) {
    const [c, world, shot] = file.replace(/\.png$/, "").split("__");
    fs.writeFileSync(path.join(dir, file), p.buf);
    captures[file] = { file, kind: "case", case: c, set: p.set || "S0", world, shot, sha256: sha(p.buf), size: [p.buf.readUInt32BE(16), p.buf.readUInt32BE(20)], bytes: p.buf.length, policy: p.policy || POLICY };
  }
  const m = { format: "ui-parity-run", version: 1, harness: o.harness || "h1", fixture: o.fixture || "f1", status: o.complete === false ? "failed: 1 runs" : "complete",
              complete: o.complete !== false, policy: POLICY, expected: o.expected || Object.keys(pics), captures, runs: [{ case: "x", world: "classic", ok: o.complete !== false }], smoke: [] };
  if (o.mutate) o.mutate(m, dir);
  fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(m));
  return dir;
}
const base = () => ({ "s0_shell__classic__live.png": { set: "S0", buf: png(20, 10) }, "s0_shell__ocean__live.png": { set: "S0", buf: png(20, 10) },
                      "s2_tabs__classic__tab.png": { set: "S2", buf: png(20, 10) } });
const withPic = (file, buf, o) => { const p = base(); p[file] = Object.assign({}, p[file], { buf }, o || {}); return p; };
const cmp = (...a) => harness("--compare", ...a);

section("--compare: a gate on two complete runs");
{
  const A = makeRun(base());
  let r = cmp(A, makeRun(base()));
  ok(r.code === 0 && /PASS: 3 pictures: 3 identical/.test(r.out), "two runs, the same pictures: PASS", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [[1, 1, 101], [2, 2, 99], [3, 3, 101]]))));
  ok(r.code === 0 && /noise  s0_shell__classic__live\.png/.test(r.out) && /1 within their policy/.test(r.out), "3 pixels a channel off by 1 (the tolerance): PASS, listed as noise", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [[1, 1, 117], [2, 1, 117], [3, 1, 117]]))));
  ok(r.code === 0 && /PASS/.test(r.out), "3 pixels off by 17 (at most maxPixels 8 beyond the tolerance): PASS", r.out);
  const big = png(20, 10, Array.from({ length: 10 }, (_, i) => [i, 5, 200]));
  const B = makeRun(withPic("s2_tabs__classic__tab.png", big));
  r = cmp(A, B);
  ok(r.code === 1 && /DIFF   s2_tabs__classic__tab\.png/.test(r.out) && /^FAIL/m.test(r.out), "10 pixels beyond the tolerance (policy: at most 8): FAIL, exit 1 (it exited 0 before)", r.out);
  r = cmp(A, B, "--report");
  ok(r.code === 0 && /^REPORT/m.test(r.out) && /DIFF   s2_tabs__classic__tab\.png/.test(r.out), "  --report: listed, exit 0 (a PR that changes the UI on purpose)", r.out);
  r = cmp(A, B, "--sets", "S0");
  ok(r.code === 0 && /PASS: 2 pictures/.test(r.out), "  --sets S0: only S0 compared, PASS (the shell must not change)", r.out);
  r = cmp(A, B, "--cases", "s2_tabs");
  ok(r.code === 1 && /FAIL: 1 pictures/.test(r.out), "  --cases s2_tabs: that case only, FAIL", r.out);
  r = cmp(A, B, "--worlds", "ocean");
  ok(r.code === 0 && /PASS: 1 pictures/.test(r.out), "  --worlds ocean: the Ocean's only, PASS", r.out);
  r = cmp(A, B, "--worlds", "ocen");
  ok(r.code === 2, "  --worlds with a misspelt world: refused", r.out);
  r = cmp(A, B, "--sets", "S9");
  ok(r.code === 1 && /INVALID nothing to compare/.test(r.out), "  a filter that leaves nothing: INVALID, exit 1", r.out);
  const own = makeRun(withPic("s2_tabs__classic__tab.png", big, { policy: { tolerance: 1, maxPixels: 20, why: "this shot's own" } }));
  r = cmp(makeRun(base()), own);
  ok(r.code === 0 && /policy: at most 20/.test(r.out), "a shot's own policy (maxPixels 20): honoured, PASS", r.out);
  const S = makeRun(withPic("s0_shell__ocean__live.png", png(22, 10)));
  r = cmp(A, S);
  ok(r.code === 1 && /SIZE   s0_shell__ocean__live\.png  20x10 -> 22x10/.test(r.out), "a picture of another size: FAIL", r.out);
  r = cmp(A, S, "--report");
  ok(r.code === 0 && /SIZE/.test(r.out), "  --report: listed, exit 0", r.out);
}

section("--compare: evidence that is not a complete run is INVALID (both modes)");
{
  const A = makeRun(base());
  const empty = path.join(TMP, "empty");
  fs.mkdirSync(empty);
  let r = cmp(A, empty);
  ok(r.code === 1 && /INVALID AFTER .*no manifest\.json/.test(r.out) && !/PASS/.test(r.out), "a complete BEFORE against an empty AFTER: INVALID (it said \"0 of 0 identical\" and exited 0)", r.out);
  r = cmp(A, empty, "--report");
  ok(r.code === 1 && /INVALID/.test(r.out), "  --report as well", r.out);
  r = cmp(A, path.join(TMP, "nowhere"));
  ok(r.code === 1 && /is not a directory/.test(r.out), "an AFTER that does not exist: INVALID", r.out);
  r = cmp(A, makeRun(base(), { complete: false }));
  ok(r.code === 1 && /the run is not complete/.test(r.out), "an AFTER whose run did not complete (a failed or interrupted case): INVALID", r.out);
  r = cmp(A, makeRun(base(), { expected: Object.keys(base()).concat(["s2_tabs__ocean__tab.png"]) }));
  ok(r.code === 1 && /s2_tabs__ocean__tab\.png was to be taken and was not/.test(r.out), "a capture the run was to take and did not: INVALID", r.out);
  r = cmp(A, makeRun(base(), { mutate: (m, d) => fs.rmSync(path.join(d, "s0_shell__ocean__live.png")) }));
  ok(r.code === 1 && /in the manifest but not in/.test(r.out), "a capture deleted after its run: INVALID", r.out);
  r = cmp(A, makeRun(base(), { mutate: (m, d) => fs.writeFileSync(path.join(d, "s0_shell__classic__live.png"), png(20, 10, [[0, 0, 0]])) }));
  ok(r.code === 1 && /not the picture its run took/.test(r.out), "a capture replaced after its run (its sha256): INVALID", r.out);
  r = cmp(A, makeRun(base(), { mutate: (m, d) => fs.writeFileSync(path.join(d, "s2_old__classic__x.png"), png(20, 10)) }));
  ok(r.code === 1 && /s2_old__classic__x\.png is not a capture of this run/.test(r.out), "a stale PNG of an older run in the directory: INVALID", r.out);
  const fewer = base(); delete fewer["s2_tabs__classic__tab.png"];
  r = cmp(A, makeRun(fewer));
  ok(r.code === 1 && /s2_tabs__classic__tab\.png: in BEFORE, not in AFTER/.test(r.out), "a capture on one side only: INVALID (it was skipped before)", r.out);
  r = cmp(A, makeRun(base(), { fixture: "f2" }));
  ok(r.code === 1 && /different cases files/.test(r.out), "runs of different cases files: INVALID", r.out);
  r = cmp(A, makeRun(base(), { harness: "h2" }));
  ok(r.code === 1 && /different harness files/.test(r.out), "runs of different harness files: INVALID", r.out);
  const junk = path.join(TMP, "junk"); fs.mkdirSync(junk); fs.writeFileSync(path.join(junk, "manifest.json"), "{\"format\":\"other\"}");
  r = cmp(A, junk);
  ok(r.code === 1 && /not a ui-parity-run v1 manifest/.test(r.out), "a manifest of something else: INVALID", r.out);
}

section("--compare --out: never into older output");
{
  const A = makeRun(base()), B = makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10, [[0, 0, 50]])));
  const d = path.join(TMP, "diff");
  let r = cmp(A, B, "--out", d);
  ok(r.code === 0 && fs.existsSync(path.join(d, "compare.json")) && fs.existsSync(path.join(d, "s2_tabs__classic__tab_diff16x.png")),
     "a new directory: compare.json and the difference picture written", r.out);
  const j = JSON.parse(fs.readFileSync(path.join(d, "compare.json"), "utf8"));
  ok(j.verdict === "PASS" && j.mode === "check" && j.files.length === 3 && j.counts.within === 1, "  compare.json: the verdict, the mode, each file's result", j);
  r = cmp(A, B, "--out", d);
  ok(r.code === 2 && /is not empty/.test(r.out), "the same directory again: refused", r.out);
  r = cmp(A, B, "--out", d, "--clean");
  ok(r.code === 0, "  --clean: its own files removed, written again", r.out);
}

fs.rmSync(TMP, { recursive: true, force: true });
console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);
