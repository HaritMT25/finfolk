// The machine-wide browser lock (Downloads\fish runs\browser.lock) as the other browser jobs use it: a lock file younger than 40
// minutes is held (wait); the file's first line is the holder's name, the second the time (their PowerShell checks read the name's
// prefix and the file's age); the holder refreshes it while it works and deletes it when done. acquire(name) -> release(); the
// process's exit and signals release it too. Never kills anything: it only waits.
//
// Taking it is one atomic step: the file is CREATED EXCLUSIVELY (flag "wx") and nothing is deleted first, so a contender can never
// remove a lock another contender has just taken (a stat, then an unconditional delete, then a create did exactly that: A creates,
// B's delete removes A's file, B creates, both run). A lock older than 40 minutes (its holder died or hung: a live holder
// refreshes every 5) is reclaimed apart from acquiring, under a short-lived mutex file (<lock>.reclaim) that serialises reclaiming
// and releasing among these tools: the reclaimer looks at the lock's age again under the mutex and deletes it only if it is still
// stale, so a lock another contender created in between is left alone; the exclusive create after it decides who wins. The jobs
// that are PowerShell scripts check then create without exclusion (theirs to fix); this keeps this tool's side race-free.
//
// The mutex itself is never reclaimed, and only its creator deletes it. Its critical section is a few synchronous calls, so a mutex
// older than 30 s is POSSIBLY ABANDONED (its process died inside it, or is still alive but was descheduled that long: age cannot tell);
// clearing it by age would be the same look-then-delete race one level down (A and B both see it old, A clears it and takes its own,
// B's delete removes A's, both reclaim and both run: the re-review of PR #85). Such a mutex FAILS CLOSED: acquire throws an error
// (code ELOCKMUTEX) naming the file, which a person deletes once no browser job is running. Every deletion AND every refresh of the
// lock file happens under the mutex, as one check-then-act step (a release that cannot get it leaves the lock to go stale; a refresh
// that cannot is skipped: see releaser and refresher). A create refused with EACCES/EPERM while
// no lock file is there, for longer than a minute (a persistent create denial: permissions, or a delete held pending by an open
// handle), throws ELOCKDENIED instead of waiting forever.
import fs from "node:fs";
import crypto from "node:crypto";

const DEFAULT_LOCK = "C:/Users/harit/Downloads/fish runs/browser.lock";
const STALE_MS = 40 * 60 * 1000;
const sleepSync = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const CONTENDED = new Set(["EEXIST", "EPERM", "EBUSY", "EACCES"]);   /* (Windows: a file whose deletion is pending refuses a create with EPERM) */

/** createLock({ path, staleMs, pollMs, mutexStaleMs, mutexWaitMs, fs }): the tool's lock on `path` (the tests give their own file and
 * their own fs); the defaults are the machine-wide file (BROWSER_LOCK overrides) and the 40-minute convention. */
export function createLock(o = {}) {
  const LOCK = o.path || process.env.BROWSER_LOCK || DEFAULT_LOCK, MUTEX = LOCK + ".reclaim";
  const STALE = o.staleMs === undefined ? STALE_MS : o.staleMs;
  const POLL = o.pollMs || +process.env.BROWSER_LOCK_POLL_MS || 5000;
  const MUTEX_STALE = o.mutexStaleMs === undefined ? 30000 : o.mutexStaleMs, MUTEX_WAIT = o.mutexWaitMs === undefined ? 2000 : o.mutexWaitMs;
  const DENIED = o.deniedMs === undefined ? 60000 : o.deniedMs;
  const F = o.fs || fs;
  const fail = (code, msg) => Object.assign(new Error(msg), { code });

  /** a file's age in ms, null when it is not there */
  function ageOf(p) {
    try { return Date.now() - F.statSync(p).mtimeMs; } catch (e) { if (e && e.code === "ENOENT") return null; throw e; }
  }
  /** fn() with the reclaim mutex held: the mutex is created exclusively; busy for longer than MUTEX_WAIT: fn is not run; one older than
   * MUTEX_STALE (possibly abandoned: its critical section is a few synchronous calls) is NOT cleared (see the header): it throws
   * ELOCKMUTEX and nothing is deleted */
  function withMutex(fn) {
    const until = Date.now() + MUTEX_WAIT;
    for (;;) {
      try { F.writeFileSync(MUTEX, "pid " + process.pid + "\n", { flag: "wx" }); break; }
      catch (e) {
        if (!e || !CONTENDED.has(e.code)) throw e;
        const a = ageOf(MUTEX);
        if (a !== null && a > MUTEX_STALE)
          throw fail("ELOCKMUTEX", "browser lock: the reclaim mutex " + MUTEX + " is " + Math.round(a / 1000) + " s old: possibly abandoned " +
                     "by a process that died (or stalled) while reclaiming or releasing the lock. It is not cleared automatically (two contenders " +
                     "clearing it could both run a browser); delete it by hand once no browser job is running.");
        if (Date.now() >= until) return { ran: false };
        sleepSync(5);
      }
    }
    try { return { ran: true, value: fn() }; }
    finally { try { F.rmSync(MUTEX, { force: true }); } catch (e) { /* gone */ } }
  }
  /** delete the lock if it is still stale (looked at again under the mutex) */
  function reclaimStale() {
    return withMutex(() => { const a = ageOf(LOCK); if (a !== null && a > STALE) { F.rmSync(LOCK, { force: true }); return true; } return false; });
  }

  /** one attempt: { held: true, text, release, refresh } or { held: false, age, code } (age in ms of the lock in the way, null if
   * unknown; code: the last create's error code). Throws ELOCKMUTEX when a stale lock's reclaim finds an abandoned mutex. */
  function tryAcquire(name) {
    const text = name + "\n" + new Date().toISOString() + "\npid " + process.pid + " " + crypto.randomBytes(6).toString("hex") + "\n";
    let age = null, code = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      try { F.writeFileSync(LOCK, text, { flag: "wx" }); return { held: true, text, release: releaser(text), refresh: refresher(text) }; }
      catch (e) { if (!e || !CONTENDED.has(e.code)) throw e; code = e.code; }
      age = ageOf(LOCK);
      if (age !== null && age <= STALE) break;   /* held by a live job: wait */
      if (age !== null) reclaimStale();          /* stale: reclaim (or find a fresh lock there on the next create) */
    }
    return { held: false, age, code };
  }
  /** the lock is deleted only if its content is still this holder's, and ONLY with the mutex held: every deletion of the lock (this and
   * reclaimStale) is a check-then-delete, and only the mutex keeps the file from changing hands between the two. Without the mutex
   * (busy past MUTEX_WAIT, or ELOCKMUTEX), the lock is LEFT: it goes stale in 40 minutes and is reclaimed then (or, with an abandoned
   * mutex, removed by hand). Deleting it anyway let a reclaimer paused under an old mutex delete the next holder's fresh lock (the
   * second re-review of PR #85). */
  function releaser(text) {
    let done = false;
    return function release() {
      if (done) return; done = true;
      const mine = () => { try { if (F.readFileSync(LOCK, "utf8") === text) F.rmSync(LOCK, { force: true }); } catch (e) { /* gone already */ } };
      let r, why = "the reclaim mutex stayed busy";
      try { r = withMutex(mine); } catch (e) { r = { ran: false }; why = e && e.code === "ELOCKMUTEX" ? "the reclaim mutex is old (possibly abandoned)" : String(e && e.message || e); }
      if (!r.ran) { try { console.error("browser lock: not released (" + why + "); " + LOCK + " is left to go stale in 40 minutes or to be removed by hand"); } catch (e) { /* no stderr */ } }
    };
  }
  /** the heartbeat: the ownership check, the timestamp and the touch are ONE step under the mutex, so the file cannot change hands
   * between them. Unserialised, a holder stalled after its check could touch a replacement holder's file with its old timestamp,
   * making that live lock look stale to the next reclaimer (the third re-review of PR #85). Without the mutex (busy, or old), this
   * refresh is skipped; the next comes 5 minutes later, far inside the 40-minute lease. */
  function refresher(text) {
    return function refresh() {
      try {
        const r = withMutex(() => { if (F.readFileSync(LOCK, "utf8") !== text) return false; const t = new Date(); F.utimesSync(LOCK, t, t); return true; });
        return r.ran && r.value === true;
      } catch (e) { return false; /* not ours any more, gone, or the mutex is old: skipped */ }
    };
  }

  async function acquire(name, log = console.log) {
    let said = 0, deniedSince = 0, r;
    for (;;) {
      r = tryAcquire(name);
      if (r.held) break;
      /* refused with no lock file there (EACCES/EPERM): usually a Windows pending delete, which ends when the last handle closes; a
         denial that persists longer than DENIED (permissions, or a handle held open) is reported rather than waited on forever */
      if (r.age === null && (r.code === "EACCES" || r.code === "EPERM")) {
        if (!deniedSince) deniedSince = Date.now();
        else if (Date.now() - deniedSince > DENIED)
          throw fail("ELOCKDENIED", "browser lock: creating " + LOCK + " has been refused (" + r.code + ") for " + Math.round((Date.now() - deniedSince) / 1000) +
                     " s with no lock file there: a persistent create denial (permissions, or a delete held pending by an open handle), not another job holding it.");
      } else deniedSince = 0;
      if (Date.now() - said > 60000) { said = Date.now(); log("waiting for the browser lock (" + (r.age === null ? "?" : Math.round(r.age / 1000) + " s old") + ")"); }
      await new Promise((res) => setTimeout(res, POLL));
    }
    const release0 = r.release;
    const keep = setInterval(r.refresh, 5 * 60 * 1000);
    keep.unref();
    function release() { clearInterval(keep); release0(); }
    process.once("exit", release);
    for (const s of ["SIGINT", "SIGTERM"]) process.once(s, () => { release(); process.exit(130); });
    log("browser lock taken: " + name);
    return release;
  }
  return { path: LOCK, tryAcquire, acquire, reclaimStale };
}

/** the machine-wide lock (the environment read at each call) */
export function acquire(name, log = console.log) { return createLock().acquire(name, log); }
