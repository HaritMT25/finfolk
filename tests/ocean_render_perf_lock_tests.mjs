// tests/ocean_render_perf_lock_tests.mjs: the render-perf tools' browser lock (tools/ocean_render_perf/lock.mjs), in node.
//   node tests/ocean_render_perf_lock_tests.mjs [--module PATH_TO_A_LOCK.MJS]
// The review of PR #85 (P2): acquiring was a stat, an unconditional delete and an exclusive create, so contenders could delete each
// other's fresh lock and both run a browser. Checked here: (1) deterministic interleavings through an fs whose calls start another
// contender at the racy moment (a fresh lock appearing between a contender's look and its create; a stale lock two contenders both
// saw; a stale lock replaced by a fresh one before the reclaimer deletes it), the 40-minute convention, release only of one's own
// lock, a dead reclaimer's mutex; (2) real processes, started at the same instant, from nothing and from a stale lock: never two
// inside their critical sections at once, all of them get through, no file left behind. --module: another lock.mjs (the old one, to
// see (2) fail on it: it exports only acquire(name, log), which is all (2) uses).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const opt = (k) => (argv.indexOf(k) >= 0 ? argv[argv.indexOf(k) + 1] : null);
const MODULE = path.resolve(opt("--module") || path.join(HERE, "..", "tools", "ocean_render_perf", "lock.mjs"));

/* ---- a worker process (below: the parent spawns these) ---- */
if (argv[0] === "--worker") {
  const [, modPath, marker, results, startAt, id] = argv;
  const lock = await import(pathToFileURL(modPath).href);
  const lead = +startAt - Date.now() - 15;
  if (lead > 0) await new Promise((r) => setTimeout(r, lead));
  while (Date.now() < +startAt) { /* all workers at the lock at the same instant (the last milliseconds spun) */ }
  const release = await lock.acquire("worker " + id, () => {});
  let inside = false;
  try { fs.writeFileSync(marker, "worker " + id + "\n", { flag: "wx" }); inside = true; } catch (e) { /* somebody is inside */ }
  await new Promise((r) => setTimeout(r, 40));
  if (inside) fs.rmSync(marker, { force: true });
  fs.appendFileSync(results, JSON.stringify({ id, alone: inside }) + "\n");
  release();
  process.exit(0);
}

const { createLock } = await import(pathToFileURL(path.resolve(HERE, "..", "tools", "ocean_render_perf", "lock.mjs")).href);
let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 500) : "")); }
  else console.log("  ok   " + what);
}
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "lock-tests-"));
let seq = 0;
const fresh = () => path.join(TMP, "case" + (++seq), "browser.lock");
function mk(file) { fs.mkdirSync(path.dirname(file), { recursive: true }); return file; }
const setAge = (file, ms) => { const t = new Date(Date.now() - ms); fs.utimesSync(file, t, t); };
const first = (file) => { try { return fs.readFileSync(file, "utf8").split("\n")[0]; } catch (e) { return null; } };
const MIN = 60 * 1000;
/* fs with a hook: onCall(method, args) runs just before the call is made */
const hooked = (onCall) => {
  const w = {};
  for (const m of ["statSync", "writeFileSync", "readFileSync", "rmSync", "utimesSync"]) w[m] = (...a) => { onCall(m, a); return fs[m](...a); };
  return w;
};

console.log("== the lock, deterministic interleavings");
{
  const f = mk(fresh()), A = createLock({ path: f }), B = createLock({ path: f });
  const a = A.tryAcquire("job A");
  ok(a.held && first(f) === "job A", "taken when absent: the file's first line is the holder's name (the convention the PowerShell jobs read)");
  const b = B.tryAcquire("job B");
  ok(!b.held && first(f) === "job A" && b.age !== null && b.age < 5000, "held by another job: not taken, the file untouched", { held: b.held, age: b.age });
  const text2 = fs.readFileSync(f, "utf8").split("\n");
  ok(/^\d{4}-\d\d-\d\dT/.test(text2[1]) && /^pid \d+ [0-9a-f]{12}$/.test(text2[2]), "name, ISO time, then the holder's pid and a random token (its identity for release and refresh)", text2);
  a.release();
  ok(!fs.existsSync(f) && !fs.existsSync(f + ".reclaim"), "released: the file is gone, no mutex left");
  ok(B.tryAcquire("job B").held && first(f) === "job B", "then another job takes it");
}
{
  /* the review's first interleaving: B looked and saw no lock, A takes it, then B goes on to create */
  const f = mk(fresh()), A = createLock({ path: f });
  let a = null;
  const B = createLock({ path: f, fs: hooked((m, args) => { if (m === "writeFileSync" && args[0] === f && args[2] && args[2].flag === "wx" && !a) a = A.tryAcquire("job A"); }) });
  const b = B.tryAcquire("job B");
  ok(a && a.held && !b.held && first(f) === "job A", "A takes the lock just before B's create: B does not get it, and A's lock is still A's (nothing of A's is deleted)", { a: a && a.held, b: b.held, first: first(f) });
  ok(first(f) === "job A" && !fs.existsSync(f + ".reclaim"), "  and B left no mutex behind");
}
{
  /* a stale lock both B and C found: B reclaims and takes it while C is about to take the mutex; C must leave B's fresh lock alone */
  const f = mk(fresh()); fs.writeFileSync(f, "dead job\n2026-01-01T00:00:00.000Z\n"); setAge(f, 3 * 60 * MIN);
  const B = createLock({ path: f });
  let b = null;
  const C = createLock({ path: f, fs: hooked((m, args) => { if (m === "writeFileSync" && args[0] === f + ".reclaim" && !b) b = B.tryAcquire("job B"); }) });
  const c = C.tryAcquire("job C");
  ok(b && b.held && !c.held && first(f) === "job B", "two contenders find a stale lock: the one that reclaims and takes it keeps it; the other, looking again under the mutex, finds a fresh lock and deletes nothing", { b: b && b.held, c: c.held, first: first(f) });
  b.release();
  ok(!fs.existsSync(f), "  and B's release removes it");
}
{
  const f = mk(fresh()), A = createLock({ path: f });
  fs.writeFileSync(f, "someone\n2026-01-01T00:00:00.000Z\n"); setAge(f, 39 * MIN);
  ok(!A.tryAcquire("job A").held && first(f) === "someone", "a lock 39 minutes old is held (the convention: younger than 40 minutes)");
  setAge(f, 41 * MIN);
  const a = A.tryAcquire("job A");
  ok(a.held && first(f) === "job A", "a lock 41 minutes old is stale: reclaimed and taken");
  ok(!fs.existsSync(f + ".reclaim"), "  without a mutex left behind");
}
{
  /* release deletes only its own lock */
  const f = mk(fresh()), A = createLock({ path: f }), B = createLock({ path: f });
  const a = A.tryAcquire("job A");
  fs.rmSync(f); const b = B.tryAcquire("job B");   /* (A's lock was reclaimed as stale in the meantime, B took it) */
  a.release();
  ok(b.held && first(f) === "job B", "a holder whose lock was reclaimed releases: the new holder's lock stays");
  b.release();
  ok(!fs.existsSync(f), "  the owner's release removes it");
}
{
  /* the mutex: one a dead reclaimer left FAILS CLOSED (the re-review of PR #85: clearing it by age let two contenders both reclaim);
     a live one is waited for (the stale lock stays, nothing is taken) */
  const f = mk(fresh()); fs.writeFileSync(f, "dead job\n"); setAge(f, 3 * 60 * MIN);
  fs.writeFileSync(f + ".reclaim", "pid 1\n"); setAge(f + ".reclaim", 5 * MIN);
  const A = createLock({ path: f });
  let ea = null; try { A.tryAcquire("job A"); } catch (e) { ea = e; }
  ok(ea && ea.code === "ELOCKMUTEX" && ea.message.includes(f + ".reclaim") && first(f) === "dead job" && fs.readFileSync(f + ".reclaim", "utf8") === "pid 1\n",
     "a reclaim mutex a dead process left (older than 30 s) is not cleared: ELOCKMUTEX naming the file; the stale lock and the mutex are untouched",
     { code: ea && ea.code, msg: ea && ea.message });
  const g = mk(fresh()); fs.writeFileSync(g, "dead job\n"); setAge(g, 3 * 60 * MIN); fs.writeFileSync(g + ".reclaim", "pid 1\n");
  const B = createLock({ path: g, mutexWaitMs: 50 });
  const t0 = Date.now(), b = B.tryAcquire("job B");
  ok(!b.held && first(g) === "dead job" && fs.existsSync(g + ".reclaim") && Date.now() - t0 < 5000, "a live reclaimer's mutex: not taken over, the stale lock not deleted under it; the attempt gives up (waits at its next poll)", { held: b.held, ms: Date.now() - t0 });
}
{
  /* the re-review's interleaving: a crash left a stale lock AND a stale mutex; A and B both look at the mutex's age. Before, A cleared
     it and took its own, B's earlier-authorised delete removed A's mutex, and both went on to reclaim and run. Here: B is started at the
     moment A looks at the mutex's age; neither deletes anything (no rmSync of the lock or the mutex at all), both get ELOCKMUTEX. */
  const f = mk(fresh()), M = f + ".reclaim";
  fs.writeFileSync(f, "dead job\n2026-01-01T00:00:00.000Z\n"); setAge(f, 3 * 60 * MIN);
  fs.writeFileSync(M, "pid 1\n"); setAge(M, 5 * MIN);
  const rms = [];
  let eb = null, started = false;
  const rec = (m, args) => { if (m === "rmSync") rms.push(String(args[0])); };
  const B = createLock({ path: f, fs: hooked(rec) });
  const A = createLock({ path: f, fs: hooked((m, args) => {
    rec(m, args);
    if (m === "statSync" && args[0] === M && !started) { started = true; try { B.tryAcquire("job B"); } catch (e) { eb = e; } }
  }) });
  let ea = null; try { A.tryAcquire("job A"); } catch (e) { ea = e; }
  ok(started && ea && ea.code === "ELOCKMUTEX" && eb && eb.code === "ELOCKMUTEX", "two contenders, a stale lock and a stale mutex (B started while A looks at the mutex): both fail closed with ELOCKMUTEX",
     { started, a: ea && ea.code, b: eb && eb.code });
  ok(rms.length === 0 && first(f) === "dead job" && fs.readFileSync(M, "utf8") === "pid 1\n", "  and nothing was deleted: the stale lock and the mutex are as the crash left them", { rms });
  /* acquire fails closed too (it does not wait forever); once a person deletes the mutex, the stale lock is reclaimed and taken */
  const C = createLock({ path: f, pollMs: 10 });
  let ec = null; try { await C.acquire("job C", () => {}); } catch (e) { ec = e; }
  ok(ec && ec.code === "ELOCKMUTEX", "  acquire() rejects with ELOCKMUTEX", { code: ec && ec.code });
  fs.rmSync(M);
  const c = C.tryAcquire("job C");
  ok(c.held && first(f) === "job C" && !fs.existsSync(M), "  after the mutex is deleted by hand, the stale lock is reclaimed and taken");
  c.release();
}
{
  /* a holder releasing while an abandoned mutex is there: its own lock is still removed (the plain content check), the mutex stays */
  const f = mk(fresh()), A = createLock({ path: f });
  const a = A.tryAcquire("job A");
  fs.writeFileSync(f + ".reclaim", "pid 1\n"); setAge(f + ".reclaim", 5 * MIN);
  a.release();
  ok(!fs.existsSync(f) && fs.existsSync(f + ".reclaim"), "a holder's release with an abandoned mutex there: its lock is removed, the mutex is left for a person");
}
{
  /* EACCES/EPERM with no lock file: a permission problem fails after deniedMs instead of waiting forever; a brief EPERM (a Windows
     pending delete) is waited through */
  const f = mk(fresh());
  const denied = (m, args) => { if (m === "writeFileSync" && args[0] === f) throw Object.assign(new Error("EACCES: permission denied"), { code: "EACCES" }); };
  const A = createLock({ path: f, pollMs: 10, deniedMs: 100, fs: hooked(denied) });
  const t0 = Date.now();
  let ea = null; try { await A.acquire("job A", () => {}); } catch (e) { ea = e; }
  ok(ea && ea.code === "ELOCKDENIED" && Date.now() - t0 < 5000 && !fs.existsSync(f), "a create refused with EACCES and no lock file there: acquire rejects with ELOCKDENIED after deniedMs, not waiting forever",
     { code: ea && ea.code, ms: Date.now() - t0 });
  let n = 0;
  const brief = (m, args) => { if (m === "writeFileSync" && args[0] === f && n++ < 6) throw Object.assign(new Error("EPERM: operation not permitted"), { code: "EPERM" }); };
  const B = createLock({ path: f, pollMs: 10, deniedMs: 2000, fs: hooked(brief) });
  const rel = await B.acquire("job B", () => {});
  ok(first(f) === "job B", "a brief EPERM (six refused creates) is waited through and the lock is then taken");
  rel();
}
{
  const f = mk(fresh()), A = createLock({ path: f, pollMs: 10 });
  const rel = await A.acquire("job A", () => {});
  let took = null;
  const B = createLock({ path: f, pollMs: 10 });
  const pend = B.acquire("job B", () => {}).then((r) => { took = r; return r; });
  await new Promise((r) => setTimeout(r, 120));
  ok(took === null && first(f) === "job A", "acquire waits while the lock is held");
  rel();
  const relB = await pend;
  ok(first(f) === "job B", "and takes it once it is released");
  relB();
  ok(!fs.existsSync(f), "  and releases it");
}

console.log("== the lock, real processes at the same instant");
async function round(label, n, pre) {
  const f = mk(fresh()), marker = f + ".inside", results = f + ".results";
  if (pre) pre(f);
  const startAt = Date.now() + 1800;
  const env = Object.assign({}, process.env, { BROWSER_LOCK: f, BROWSER_LOCK_POLL_MS: "10" });
  const kids = [];
  for (let i = 0; i < n; i++) kids.push(new Promise((res) => {
    const p = spawn(process.execPath, [fileURLToPath(import.meta.url), "--worker", MODULE, marker, results, String(startAt), String(i)], { env, stdio: ["ignore", "ignore", "pipe"] });
    let err = ""; p.stderr.on("data", (d) => { err += d; });
    p.on("exit", (code) => res({ code, err }));
  }));
  const ex = await Promise.all(kids);
  const rows = fs.existsSync(results) ? fs.readFileSync(results, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [];
  return { label, n, rows, alone: rows.filter((r) => r.alone).length, bad: ex.filter((x) => x.code !== 0), left: [f, f + ".reclaim", marker].filter((p) => fs.existsSync(p)) };
}
{
  const rs = [];
  for (let k = 0; k < 3; k++) rs.push(await round("from nothing " + k, 8));
  for (let k = 0; k < 3; k++) rs.push(await round("from a stale lock " + k, 8, (f) => { fs.writeFileSync(f, "dead job\n2026-01-01T00:00:00.000Z\n"); setAge(f, 2 * 60 * MIN); }));
  ok(rs.every((r) => r.rows.length === r.n && r.alone === r.n),
     "8 processes at the lock at once, three rounds from nothing and three from a stale lock: each one was alone in its critical section, every one got through",
     rs.map((r) => [r.label, r.rows.length + "/" + r.n, "alone " + r.alone, r.bad.slice(0, 1).map((x) => x.err.slice(0, 200))]));
  ok(rs.every((r) => r.left.length === 0), "  and no lock, mutex or marker file left behind", rs.filter((r) => r.left.length).map((r) => r.left));
  /* a stale lock and an abandoned mutex: every process fails closed; none runs; the files stay for a person */
  const z = await round("from a stale lock and an abandoned mutex", 8, (f) => {
    fs.writeFileSync(f, "dead job\n2026-01-01T00:00:00.000Z\n"); setAge(f, 2 * 60 * MIN);
    fs.writeFileSync(f + ".reclaim", "pid 1\n"); setAge(f + ".reclaim", 5 * MIN);
  });
  ok(z.rows.length === 0 && z.bad.length === z.n && z.bad.every((x) => /ELOCKMUTEX|reclaim mutex/.test(x.err)),
     "8 processes at a stale lock with an abandoned mutex: none got the lock, every one stopped with the mutex error",
     { rows: z.rows.length, bad: z.bad.length, err: z.bad.slice(0, 1).map((x) => x.err.slice(0, 300)) });
  ok(z.left.length === 2 && z.left.every((p) => !p.endsWith(".inside")), "  the stale lock and the mutex are left as they were (no marker: nobody was inside)", z.left);
}

fs.rmSync(TMP, { recursive: true, force: true });
console.log(fails ? "FAIL: " + fails + "/" + checks + " checks" : "ok: " + checks + "/" + checks + " checks");
process.exit(fails ? 1 : 0);
