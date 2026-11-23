// tests/ui_parity_harness_tests.mjs: the paired browser harness's parts that need no browser (tests/ui_parity_browser.mjs), in node;
// CI's "web ui" job. node tests/ui_parity_harness_tests.mjs  (exit 0 = pass)
//   - the selection (--plan): unknown worlds, sets and cases, and a selection that runs nothing (a case whose worlds the
//     --worlds filter leaves out), with or without --smoke, are refused (exit 2) before any browser; the real fixture's plan
//   - the fixture's own checks: a case id used twice, a shot name used twice in a case and world, an unknown step or
//     expectation, a selector missing for a world the step runs on, a world without a shot, a policy without its why
//   - --out: a run never writes into a directory with older pictures; --clean removes only what an earlier run's manifest (or a
//     comparison's compare.json) lists, and refuses a folder without one or with any other file (the review of b408e60)
//   - --compare as a gate, on synthetic runs of a synthetic cases file: identical and noise-only pictures pass; a picture beyond
//     its policy and a size change fail (and are only listed with --report), and so does a one-level shift of the whole picture
//     (maxNoisePixels); evidence that is not a complete run (a missing manifest, an incomplete run, a capture missing or changed
//     since its run, a stale PNG, a capture the comparison plans on one side only) is INVALID in both modes; --sets / --cases /
//     --worlds narrow it; AFTER may miss only the expectations BEFORE missed too (--expect record: main's run before a PR that
//     brings the behaviour)
//   - the binding (the review of b442a92): a manifest without valid harness / cases-file identities, a run of another harness
//     file or another cases file than the comparison's, a run whose recorded selection does not give its expected captures
//     under that cases file (a later PR's new shot among them), a capture recorded with another case / set / policy, and a
//     comparison whose planned captures a run did not take are INVALID in both modes; --report --archival compares two runs of
//     an older harness as a record only; the saved policies: each checked (checkPolicy), BEFORE's and AFTER's the same and
//     the cases file's (a loose AFTER policy without its why passed before), while a cases file's own override, recorded
//     consistently by both runs, is honoured
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
  r = harness("--archival", "--sets", "S0");
  ok(r.code === 2 && /--archival goes with --compare --report/.test(r.out), "--archival without --compare: refused", r.out);
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
  r = tryFix("policy_why", (f) => { f.defaults.compare = { tolerance: 1, maxPixels: 8, maxNoisePixels: 32 }; });
  ok(r.code === 2 && /says why/.test(r.out), "a difference policy without its why: refused", r.out);
  r = tryFix("policy_noise", (f) => { delete f.defaults.compare.maxNoisePixels; });
  ok(r.code === 2 && /maxNoisePixels/.test(r.out), "a difference policy without a bound for the pixels within the tolerance: refused (the review of b408e60)", r.out);
  r = tryFix("policy_override", (f) => { f.cases[0].compare = { tolerance: 2, maxPixels: 8 }; });
  ok(r.code === 2 && /maxNoisePixels/.test(r.out) && /says why/.test(r.out), "  a case's own policy: the same fields, and its why", r.out);
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
  r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", d, "--clean");
  ok(r.code === 2 && /has no manifest\.json/.test(r.out) && fs.existsSync(path.join(d, "s0_shell__classic__live.png")),
     "--clean on a directory of PNGs with no run's manifest: refused, nothing removed (it took any .png as the harness's before)", r.out);
  const art = path.join(TMP, "artwork");
  fs.mkdirSync(art);
  for (const n of ["icon.png", "logo.png", "summary.json"]) fs.writeFileSync(path.join(art, n), "user's");
  r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", art, "--clean");
  ok(r.code === 2 && ["icon.png", "logo.png", "summary.json"].every((n) => fs.existsSync(path.join(art, n))), "  a folder of unrelated PNGs (and a summary.json): refused, all kept", r.out);
  /* an earlier run's directory: its manifest lists what it wrote */
  const prev = path.join(TMP, "prev_run");
  fs.mkdirSync(prev);
  const listed = ["s0_classic_canvas__classic__canvas_selected.png", "s0_classic_canvas__classic__THREW.png"];
  for (const n of listed.concat(["summary.json", "index.md"])) fs.writeFileSync(path.join(prev, n), "x");
  fs.writeFileSync(path.join(prev, "manifest.json"), JSON.stringify({ format: "ui-parity-run", version: 1, captures: { [listed[0]]: {} }, expected: [listed[0]], extra: [listed[1]] }));
  fs.writeFileSync(path.join(prev, "holiday.png"), "user's");
  r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", prev, "--clean");
  ok(r.code === 2 && /does not list \(holiday\.png\)/.test(r.out) && fs.readdirSync(prev).length === 6, "  an earlier run's directory with a PNG its manifest does not list: refused, nothing removed", r.out);
  fs.rmSync(path.join(prev, "holiday.png"), { force: true });
  r = harness("--base", "http://localhost:1", "--cases", "s0_classic_canvas", "--out", prev, "--clean");
  ok(fs.readdirSync(prev).length === 0 && /no-playwright-here/.test(r.out),
     "  an earlier run's own files only (captures, a failed step's picture, manifest, summary, index): removed (the run then stops at the missing browser module here)", r.out);
}

/* ---------------- synthetic runs for --compare, of a synthetic cases file ---------------- */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(b) { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function chunk(type, data) { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; }
/* a w x h picture, grey 100, with edits: [[x, y, value], ...] */
function png(w, h, edits, grey) {
  const px = Buffer.alloc(w * h * 4, grey === undefined ? 100 : grey);
  for (let i = 3; i < px.length; i += 4) px[i] = 255;
  for (const [x, y, v] of edits || []) { const o = (y * w + x) * 4; px[o] = px[o + 1] = px[o + 2] = v; }
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) px.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4);
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
const HARNESS_SHA = sha(fs.readFileSync(HARNESS));
const POLICY = { tolerance: 1, maxPixels: 8, maxNoisePixels: 32, why: "test" };
/* a small cases file the comparison reads (--cases-file): s0_shell (S0: shot live, both worlds), s2_tabs (S2: shot tab, Classic) */
let fixN = 0;
function synFixture(mutate) {
  const f = { about: "synthetic", version: 2,
              defaults: { seed: 42, founders: 300, tick: 600, viewport: [20, 10], dpr: 1, animT: 20, visualSeed: 1, settleFrames: 1, barrierFrames: 1,
                          locale: "en-US", timezone: "UTC", compare: POLICY },
              routes: { source: { classic: "/web/index.html", ocean: "/web/ocean.html" }, site: { classic: "/classic.html", ocean: "/" } },
              query: { classic: "", ocean: "" },
              cases: [{ id: "s0_shell", set: "S0", title: "t", worlds: ["classic", "ocean"], steps: [{ do: "shot", name: "live" }] },
                      { id: "s2_tabs", set: "S2", title: "t", worlds: ["classic"], steps: [{ do: "shot", name: "tab" }] }] };
  if (mutate) mutate(f);
  const text = JSON.stringify(f, null, 1), file = path.join(TMP, "cases_" + (++fixN) + ".json");
  fs.writeFileSync(file, text);
  return { fix: f, file, sha: sha(Buffer.from(text, "utf8")) };
}
const SYN = synFixture();
const FULL = { sets: null, cases: null, worlds: ["classic", "ocean"], smoke: false, layout: "source" };
/* what a selection takes from a cases file, as the harness plans it: file -> {case, set, world, shot, policy} */
function planOf(F, sel) {
  const out = {};
  for (const c of F.fix.cases) {
    if ((sel.sets && sel.sets.indexOf(c.set) < 0) || (sel.cases && sel.cases.indexOf(c.id) < 0)) continue;
    for (const w of c.worlds) {
      if (sel.worlds.indexOf(w) < 0) continue;
      for (const st of c.steps) if (st.do === "shot" && (!st.world || st.world === w))
        out[c.id + "__" + w + "__" + st.name + ".png"] = { case: c.id, set: c.set, world: w, shot: st.name, policy: Object.assign({}, F.fix.defaults.compare, c.compare || {}, st.compare || {}) };
    }
  }
  return out;
}
/* a run directory as the harness writes it: pictures {file: {buf, policy, unmet}} and its manifest, of cases file o.F (SYN) and
 * selection o.selection (everything), by this harness file; o.harness / o.fixture / o.expected / o.mutate to make it otherwise */
let runN = 0;
function makeRun(pics, o) {
  o = o || {};
  const F = o.F || SYN, sel = o.selection || FULL, plan = planOf(F, sel);
  const dir = path.join(TMP, "run" + (++runN));
  fs.mkdirSync(dir);
  const captures = {};
  for (const [file, p] of Object.entries(pics)) {
    const [c, world, shot] = file.replace(/\.png$/, "").split("__"), pl = plan[file];
    fs.writeFileSync(path.join(dir, file), p.buf);
    captures[file] = { file, kind: "case", case: c, set: pl ? pl.set : "S0", world, shot, sha256: sha(p.buf), size: [p.buf.readUInt32BE(16), p.buf.readUInt32BE(20)], bytes: p.buf.length,
                       policy: p.policy || (pl ? pl.policy : POLICY), unmet: p.unmet || [] };
  }
  const m = { format: "ui-parity-run", version: 1, harness: "harness" in o ? o.harness : HARNESS_SHA, fixture: "fixture" in o ? o.fixture : F.sha, fixtureFile: F.file,
              selection: sel, status: o.complete === false ? "failed: 1 runs" : "complete", complete: o.complete !== false, expectMode: "check", barrierTiming: "as-it-comes",
              policy: F.fix.defaults.compare, expected: o.expected || Object.keys(plan), captures, runs: [{ case: "x", world: "classic", ok: o.complete !== false }], smoke: [] };
  if (o.mutate) o.mutate(m, dir);
  fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(m));
  return dir;
}
const base = () => ({ "s0_shell__classic__live.png": { buf: png(20, 10) }, "s0_shell__ocean__live.png": { buf: png(20, 10) }, "s2_tabs__classic__tab.png": { buf: png(20, 10) } });
const withPic = (file, buf, o) => { const p = base(); p[file] = Object.assign({}, p[file], { buf }, o || {}); return p; };
/* the comparison of SYN's runs (cmp), or of another cases file's (cmpF) */
const cmpF = (F, A, B, ...rest) => harness("--compare", A, B, "--cases-file", F.file, ...rest);
const cmp = (A, B, ...rest) => cmpF(SYN, A, B, ...rest);
/* INVALID in both modes: exit 1, the verdict INVALID, the problem named */
function invalid(what, run, re) {
  for (const mode of [[], ["--report"]]) {
    const r = run(...mode);
    ok(r.code === 1 && /^INVALID: /m.test(r.out) && re.test(r.out) && !/^(PASS|REPORT|FAIL)/m.test(r.out), what + (mode.length ? " (--report too)" : ""), r.out);
  }
}

section("--compare: a gate on two complete runs");
{
  const A = makeRun(base());
  let r = cmp(A, makeRun(base()));
  ok(r.code === 0 && /PASS: 3 pictures: 3 identical/.test(r.out), "two runs, the same pictures: PASS", r.out);
  ok(/compare: 3 pictures planned by .*cases_1\.json/.test(r.out) && r.out.indexOf("this harness file " + HARNESS_SHA.slice(0, 12)) >= 0,
     "  it names the cases file it read and this harness file", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [[1, 1, 101], [2, 2, 99], [3, 3, 101]]))));
  ok(r.code === 0 && /noise  s0_shell__classic__live\.png/.test(r.out) && /1 within their policy/.test(r.out), "3 pixels a channel off by 1 (the tolerance): PASS, listed as noise", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [], 101))));
  ok(r.code === 1 && /DIFF   s0_shell__classic__live\.png  200 px differ: 0 beyond tolerance 1 \(policy: at most 8\), 200 within it \(policy: at most 32\)/.test(r.out),
     "the whole picture one level lighter (every pixel off by 1, none beyond the tolerance): FAIL (it passed as noise in b408e60)", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, Array.from({ length: 33 }, (_, i) => [i % 20, (i / 20) | 0, 101])))));
  ok(r.code === 1 && /33 within it \(policy: at most 32\)/.test(r.out), "  33 pixels off by 1 (one more than maxNoisePixels): FAIL", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, Array.from({ length: 32 }, (_, i) => [i % 20, (i / 20) | 0, 99])))));
  ok(r.code === 0 && /32 within it/.test(r.out), "  32 pixels off by 1 (maxNoisePixels): PASS, listed as noise", r.out);
  r = cmp(A, makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [], 101))), "--report");
  ok(r.code === 0 && /DIFF   s0_shell__classic__live\.png/.test(r.out), "  the one-level shift with --report: listed, exit 0", r.out);
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
  ok(r.code === 2 && /no world "ocen"/.test(r.out), "  --worlds with a misspelt world: refused (exit 2)", r.out);
  r = cmp(A, B, "--sets", "S9");
  ok(r.code === 2 && /no case is in set "S9"/.test(r.out), "  a set the cases file has no case in: refused (exit 2, as a run's selection)", r.out);
  r = cmp(A, B, "--cases", "s2_tabs", "--worlds", "ocean");
  ok(r.code === 2 && /runs no case/.test(r.out), "  a filter that leaves nothing to compare: refused (exit 2)", r.out);
  const S = makeRun(withPic("s0_shell__ocean__live.png", png(22, 10)));
  r = cmp(A, S);
  ok(r.code === 1 && /SIZE   s0_shell__ocean__live\.png  20x10 -> 22x10/.test(r.out), "a picture of another size: FAIL", r.out);
  r = cmp(A, S, "--report");
  ok(r.code === 0 && /SIZE/.test(r.out), "  --report: listed, exit 0", r.out);
}

section("--compare: evidence that is not a complete run is INVALID (each in both modes)");
{
  const A = makeRun(base());
  const empty = path.join(TMP, "empty");
  fs.mkdirSync(empty);
  invalid("a complete BEFORE against an empty AFTER (it said \"0 of 0 identical\" and exited 0)", (...m) => cmp(A, empty, ...m), /INVALID AFTER .*no manifest\.json/);
  invalid("an AFTER that does not exist", (...m) => cmp(A, path.join(TMP, "nowhere"), ...m), /is not a directory/);
  const incomplete = makeRun(base(), { complete: false });
  invalid("an AFTER whose run did not complete (a failed or interrupted case)", (...m) => cmp(A, incomplete, ...m), /the run is not complete/);
  const notTaken = makeRun((() => { const p = base(); delete p["s2_tabs__classic__tab.png"]; return p; })());
  invalid("a capture the run was to take and did not", (...m) => cmp(A, notTaken, ...m), /s2_tabs__classic__tab\.png was to be taken and was not/);
  const deleted = makeRun(base(), { mutate: (m, d) => fs.rmSync(path.join(d, "s0_shell__ocean__live.png")) });
  invalid("a capture deleted after its run", (...m) => cmp(A, deleted, ...m), /in the manifest but not in/);
  const replaced = makeRun(base(), { mutate: (m, d) => fs.writeFileSync(path.join(d, "s0_shell__classic__live.png"), png(20, 10, [[0, 0, 0]])) });
  invalid("a capture replaced after its run (its sha256)", (...m) => cmp(A, replaced, ...m), /not the picture its run took/);
  const stale = makeRun(base(), { mutate: (m, d) => fs.writeFileSync(path.join(d, "s2_old__classic__x.png"), png(20, 10)) });
  invalid("a stale PNG of an older run in the directory", (...m) => cmp(A, stale, ...m), /s2_old__classic__x\.png is not a capture of this run/);
  const fewer = base(); delete fewer["s2_tabs__classic__tab.png"];
  const oneSide = makeRun(fewer, { selection: Object.assign({}, FULL, { cases: ["s0_shell"] }) });
  invalid("a capture the comparison plans on one side only (AFTER's own selection left it out)", (...m) => cmp(A, oneSide, ...m),
          /s2_tabs__classic__tab\.png: the comparison plans it, AFTER did not take it \(its selection: --cases s0_shell/);
  const junk = path.join(TMP, "junk"); fs.mkdirSync(junk); fs.writeFileSync(path.join(junk, "manifest.json"), "{\"format\":\"other\"}");
  invalid("a manifest of something else", (...m) => cmp(A, junk, ...m), /not a ui-parity-run v1 manifest/);
}

section("--compare is bound to this harness file and the cases file it reads, not to what two manifests agree on (the review of b442a92)");
{
  const A = makeRun(base());
  const noIds = () => makeRun(base(), { mutate: (m) => { delete m.harness; delete m.fixture; } });
  invalid("two manifests without harness and cases-file identities (both undefined: they agreed, and it PASSED in b442a92)", (...m) => cmp(noIds(), noIds(), ...m),
          /BEFORE .*no valid harness identity[\s\S]*BEFORE .*no valid cases-file identity[\s\S]*AFTER .*no valid harness identity/);
  invalid("  identities that are not sha256s (\"h1\", \"f1\": the old tests' own)", (...m) => cmp(makeRun(base(), { harness: "h1", fixture: "f1" }), makeRun(base(), { harness: "h1", fixture: "f1" }), ...m),
          /no valid harness identity \(harness "h1"[\s\S]*no valid cases-file identity \(fixture "f1"/);
  const oldH = "a".repeat(64), oldA = makeRun(base(), { harness: oldH }), oldB = makeRun(base(), { harness: oldH });
  invalid("two runs of another harness file, agreeing with each other", (...m) => cmp(oldA, oldB, ...m), /BEFORE .*taken by another harness file \(sha256 aaaaaaaaaaaa\), not this one/);
  let r = cmp(oldA, oldB, "--report", "--archival");
  ok(r.code === 0 && /^REPORT: 3 pictures: 3 identical/m.test(r.out) && /--archival: runs of harness aaaaaaaaaaaa, a record, not a gate/.test(r.out),
     "  --report --archival --cases-file (their cases file): compared as a record, REPORT", r.out);
  r = cmp(oldA, oldB, "--archival");
  ok(r.code === 2 && /--archival goes with --report/.test(r.out), "  --archival without --report: refused (never a gate)", r.out);
  r = harness("--compare", oldA, oldB, "--report", "--archival");
  ok(r.code === 2 && /--archival needs --cases-file/.test(r.out), "  --archival without --cases-file: refused", r.out);
  r = cmp(oldA, makeRun(base(), { harness: "b".repeat(64) }), "--report", "--archival");
  ok(r.code === 1 && /^INVALID: /m.test(r.out) && /different harness files/.test(r.out), "  --archival of runs of two different harness files: INVALID", r.out);
  r = cmp(oldA, makeRun(base(), { harness: oldH, mutate: (mm) => { mm.captures["s2_tabs__classic__tab.png"].policy = { tolerance: 255, maxPixels: 0, maxNoisePixels: 200 }; } }), "--report", "--archival");
  ok(r.code === 1 && /^INVALID: /m.test(r.out) && /s2_tabs__classic__tab\.png's recorded policy: a policy says why/.test(r.out), "  --archival checks the rest as ever (an AFTER with a policy of its own, no why): INVALID", r.out);
  /* a later PR adds a shot (s2_tabs's tab2): two retained runs of the earlier cases file must not PASS against it */
  const V2 = synFixture((f) => f.cases[1].steps.push({ do: "shot", name: "tab2" }));
  invalid("two retained runs of an earlier cases file, against the cases file now (a later PR's new shot)", (...m) => cmpF(V2, A, makeRun(base()), ...m),
          /BEFORE .*used another cases file .* than this comparison's[\s\S]*AFTER .*used another cases file/);
  r = cmp(A, makeRun(base()));
  ok(r.code === 0 && /PASS/.test(r.out), "  the same runs against their own cases file: PASS", r.out);
  const forged = () => makeRun(base(), { fixture: V2.sha });
  invalid("  runs claiming the new cases file's sha256 with the old inventory: the new shot is in no expected list",
          (...m) => cmpF(V2, forged(), forged(), ...m), /s2_tabs__classic__tab2\.png is taken by its selection \(everything\) but not in its expected list[\s\S]*the comparison plans it, BEFORE did not take it/);
  invalid("a comparison without --cases-file is bound to the committed cases file (these synthetic runs are not its)", (...m) => harness("--compare", A, makeRun(base()), ...m),
          /used another cases file .*ui_parity_cases\.json/);
  /* each run's selection, run through the cases file, gives exactly its expected list */
  const S0 = Object.assign({}, FULL, { sets: ["S0"] }), s0pics = () => { const p = base(); delete p["s2_tabs__classic__tab.png"]; return p; };
  const a0 = makeRun(s0pics(), { selection: S0 }), b0 = makeRun(s0pics(), { selection: S0 });
  invalid("two consistent --sets S0 runs, compared with nothing narrowed (the cases file plans S2 too)", (...m) => cmp(a0, b0, ...m),
          /s2_tabs__classic__tab\.png: the comparison plans it, BEFORE did not take it \(its selection: --sets S0/);
  r = cmp(a0, b0, "--sets", "S0");
  ok(r.code === 0 && /PASS: 2 pictures/.test(r.out), "  the same with --sets S0: PASS, 2 pictures", r.out);
  invalid("a run whose recorded selection (--sets S0) does not take what it lists", (...m) => cmp(A, makeRun(base(), { selection: S0, expected: Object.keys(base()) }), ...m),
          /s2_tabs__classic__tab\.png is in its expected list, but its selection \(--sets S0.*\) does not take it[\s\S]*s2_tabs__classic__tab\.png is not a capture its selection/);
  invalid("a run whose selection the cases file cannot run (an unknown case)", (...m) => cmp(A, makeRun(base(), { selection: Object.assign({}, FULL, { cases: ["s9_gone"] }), expected: Object.keys(base()) }), ...m),
          /is not one this cases file runs: --cases: no case "s9_gone"/);
  invalid("a run that records no selection", (...m) => cmp(A, makeRun(base(), { mutate: (m) => { delete m.selection; } }), ...m), /records no selection/);
  invalid("a capture recorded with another set than its case's", (...m) => cmp(A, makeRun(base(), { mutate: (m) => { m.captures["s0_shell__ocean__live.png"].set = "S2"; } }), ...m),
          /s0_shell__ocean__live\.png is recorded with set "S2"; the cases file has "S0"/);
}

section("--compare: the saved policies are the cases file's, the same on both sides (the review of b442a92)");
{
  const A = makeRun(base());
  const lavish = { tolerance: 255, maxPixels: 0, maxNoisePixels: 1296000 };
  const changed = png(20, 10, [], 200);
  invalid("AFTER recording {tolerance 255, maxPixels 0, maxNoisePixels 1296000} and no why for a changed picture (it PASSED in b442a92)",
          (...m) => cmp(A, makeRun(withPic("s2_tabs__classic__tab.png", changed, { policy: lavish })), ...m),
          /AFTER .*s2_tabs__classic__tab\.png's recorded policy: a policy says why[\s\S]*is not the one the cases file gives it[\s\S]*BEFORE and AFTER record different policies/);
  invalid("  an AFTER policy of its own with every field and a why: not the cases file's, not BEFORE's",
          (...m) => cmp(A, makeRun(withPic("s2_tabs__classic__tab.png", changed, { policy: Object.assign({ why: "mine" }, lavish, { tolerance: 200 }) })), ...m),
          /AFTER .*s2_tabs__classic__tab\.png's recorded policy \{tolerance 200, maxPixels 0, maxNoisePixels 1296000, why "mine"\} is not the one the cases file gives it/);
  const same = { tolerance: 1, maxPixels: 8, maxNoisePixels: 999, why: "both" };
  invalid("  BEFORE and AFTER agreeing on a policy the cases file does not give",
          (...m) => cmp(makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { policy: same })), makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { policy: same })), ...m),
          /BEFORE .*s2_tabs__classic__tab\.png's recorded policy .* is not the one the cases file gives it/);
  invalid("  a recorded tolerance out of range (checkPolicy)", (...m) => cmp(A, makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { policy: Object.assign({}, POLICY, { tolerance: 256 }) })), ...m),
          /tolerance is a whole number 0\.\.255/);
  const noNoise = { tolerance: 1, maxPixels: 8, why: "b408e60" };
  invalid("  runs whose policy has no maxNoisePixels (an older harness)", (...m) => cmp(makeRun(withPic("s0_shell__ocean__live.png", png(20, 10), { policy: noNoise })), makeRun(withPic("s0_shell__ocean__live.png", png(20, 10), { policy: noNoise })), ...m),
          /maxNoisePixels \(the pixels that may differ within the tolerance\) is a whole number/);
  invalid("  a run whose recorded default policy is not the cases file's", (...m) => cmp(A, makeRun(base(), { mutate: (m) => { m.policy = lavish; } }), ...m), /recorded default policy/);
  /* a legitimate override: the cases file's own, recorded alike by both runs */
  const LOOSE = synFixture((f) => { f.cases[0].steps[0].compare = { tolerance: 1, maxPixels: 8, maxNoisePixels: 200, why: "a shot that may shift" }; });
  const shifted = withPic("s0_shell__classic__live.png", png(20, 10, [], 101));
  let r = cmpF(LOOSE, makeRun(base(), { F: LOOSE }), makeRun(shifted, { F: LOOSE }));
  ok(r.code === 0 && /noise  s0_shell__classic__live\.png .*policy: at most 200/.test(r.out), "a shot's own policy in the cases file (maxNoisePixels 200, its why), recorded by both runs: honoured, PASS", r.out);
  r = cmp(makeRun(base()), makeRun(shifted));
  ok(r.code === 1 && /DIFF   s0_shell__classic__live\.png/.test(r.out), "  the same pictures under the cases file without it: FAIL", r.out);
  invalid("  BEFORE of the cases file with the override, AFTER claiming it with the default policy", (...m) => cmpF(LOOSE, makeRun(base(), { F: LOOSE }), makeRun(withPic("s0_shell__classic__live.png", png(20, 10, [], 101), { policy: POLICY }), { F: LOOSE }), ...m),
          /AFTER .*s0_shell__classic__live\.png's recorded policy .* is not the one the cases file gives it/);
  const CASEPOL = synFixture((f) => { f.cases[1].compare = { tolerance: 1, maxPixels: 20, maxNoisePixels: 32, why: "this case's own" }; });
  const big = png(20, 10, Array.from({ length: 10 }, (_, i) => [i, 5, 200]));
  r = cmpF(CASEPOL, makeRun(base(), { F: CASEPOL }), makeRun(withPic("s2_tabs__classic__tab.png", big), { F: CASEPOL }));
  ok(r.code === 0 && /policy: at most 20/.test(r.out), "a case's own policy (maxPixels 20): honoured, PASS", r.out);
  const NOWHY = synFixture((f) => { f.cases[1].compare = { tolerance: 1, maxPixels: 20, maxNoisePixels: 32 }; });
  r = cmpF(NOWHY, makeRun(base(), { F: NOWHY }), makeRun(base(), { F: NOWHY }));
  ok(r.code === 2 && /says why/.test(r.out), "  a cases file whose override has no why: refused before anything is compared (exit 2)", r.out);
}

section("--compare and the cases' expectations (a run with --expect record keeps the ones it missed)");
{
  const miss = "dash.tabbable is [\"pop\",\"evo\"], expected [\"pop\"]";
  const before = makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { unmet: [miss] }));
  let r = cmp(before, makeRun(base()));
  ok(r.code === 0 && /unmet  s2_tabs__classic__tab\.png \(BEFORE only\)/.test(r.out) && /1 expectations BEFORE did not meet/.test(r.out),
     "BEFORE (main) missed an expectation AFTER meets: PASS, and the miss is listed (what the PR brings)", r.out);
  r = cmp(before, makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { unmet: [miss] })));
  ok(r.code === 0 && /both runs/.test(r.out), "two runs of main missing the same expectation the same way: PASS (a same-commit repeat)", r.out);
  invalid("AFTER missing an expectation BEFORE met", (...m) => cmp(makeRun(base()), makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10), { unmet: [miss] })), ...m),
          /does not meet its case's expectation/);
  r = harness("--plan", "--sets", "S0", "--expect", "loose");
  ok(r.code === 2 && /--expect is check/.test(r.out), "--expect other than check or record: refused", r.out);
  r = harness("--plan", "--sets", "S0", "--expect", "record");
  ok(r.code === 0, "--expect record: accepted", r.out);
}

section("--compare --out: never into older output");
{
  const A = makeRun(base()), B = makeRun(withPic("s2_tabs__classic__tab.png", png(20, 10, [[0, 0, 50]])));
  const d = path.join(TMP, "diff");
  let r = cmp(A, B, "--out", d);
  ok(r.code === 0 && fs.existsSync(path.join(d, "compare.json")) && fs.existsSync(path.join(d, "s2_tabs__classic__tab_diff16x.png")),
     "a new directory: compare.json and the difference picture written", r.out);
  let j = {};
  try { j = JSON.parse(fs.readFileSync(path.join(d, "compare.json"), "utf8")); } catch (e) { /* not written: the checks below fail */ }
  ok(j.verdict === "PASS" && j.mode === "check" && j.files.length === 3 && j.counts.within === 1 && j.planned === 3, "  compare.json: the verdict, the mode, each file's result", j);
  ok(j.harness === HARNESS_SHA && j.fixture === SYN.sha && j.casesFile === SYN.file, "  compare.json: the harness file and the cases file it was bound to", j);
  r = cmp(A, B, "--out", d);
  ok(r.code === 2 && /is not empty/.test(r.out), "the same directory again: refused", r.out);
  ok(Array.isArray(j.written) && j.written.join() === "s2_tabs__classic__tab_diff16x.png" && j.format === "ui-parity-compare", "  compare.json lists the pictures it wrote", j.written);
  r = cmp(A, B, "--out", d, "--clean");
  ok(r.code === 0, "  --clean: its own files removed, written again", r.out);
  fs.mkdirSync(d, { recursive: true });   /* (there already, unless the comparison above failed) */
  fs.writeFileSync(path.join(d, "someone_else_diff16x.png"), "x");
  r = cmp(A, B, "--out", d, "--clean");
  ok(r.code === 2 && /does not list \(someone_else_diff16x\.png\)/.test(r.out) && fs.existsSync(path.join(d, "compare.json")), "  a difference picture compare.json does not list: refused, nothing removed", r.out);
  const pics = path.join(TMP, "pics"); fs.mkdirSync(pics); fs.writeFileSync(path.join(pics, "a_diff16x.png"), "x");
  r = cmp(A, B, "--out", pics, "--clean");
  ok(r.code === 2 && /has no compare\.json/.test(r.out) && fs.existsSync(path.join(pics, "a_diff16x.png")), "  a folder with no compare.json: refused, nothing removed", r.out);
}

fs.rmSync(TMP, { recursive: true, force: true });
console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);
