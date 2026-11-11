// The machine-wide browser lock (Downloads\fish runs\browser.lock) as the other browser jobs use it: wait while the
// file exists and is younger than 40 minutes, create it (name + time), refresh it while held, delete it on release.
// acquire(name) -> release(); the process's exit and signals release it too. Never kills anything: it only waits.
import fs from "node:fs";

const LOCK = process.env.BROWSER_LOCK || "C:/Users/harit/Downloads/fish runs/browser.lock";
const STALE_MS = 40 * 60 * 1000;

export async function acquire(name, log = console.log) {
  let said = 0;
  for (;;) {
    let age = null;
    try { age = Date.now() - fs.statSync(LOCK).mtimeMs; } catch (e) { age = null; }
    if (age === null || age > STALE_MS) {
      try { fs.rmSync(LOCK, { force: true }); fs.writeFileSync(LOCK, name + "\n" + new Date().toISOString() + "\n", { flag: "wx" }); break; }
      catch (e) { /* lost the race: wait again */ }
    }
    if (Date.now() - said > 60000) { said = Date.now(); log("waiting for the browser lock (" + (age === null ? "?" : Math.round(age / 1000) + " s old") + ")"); }
    await new Promise((r) => setTimeout(r, 5000));
  }
  const mine = fs.readFileSync(LOCK, "utf8");
  const keep = setInterval(() => { try { if (fs.readFileSync(LOCK, "utf8") === mine) { const t = new Date(); fs.utimesSync(LOCK, t, t); } } catch (e) { /* gone */ } }, 5 * 60 * 1000);
  let released = false;
  function release() {
    if (released) return; released = true; clearInterval(keep);
    try { if (fs.readFileSync(LOCK, "utf8") === mine) fs.rmSync(LOCK, { force: true }); } catch (e) { /* gone already */ }
  }
  process.once("exit", release);
  for (const s of ["SIGINT", "SIGTERM"]) process.once(s, () => { release(); process.exit(130); });
  log("browser lock taken: " + name);
  return release;
}
