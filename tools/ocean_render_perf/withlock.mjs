// tools/ocean_render_perf/withlock.mjs NAME -- COMMAND ARGS...: run a command while holding the machine-wide browser lock
// (lock.mjs: waits for it, never breaks it, refreshes it while held, releases it when the command ends or the process is killed).
//   node tools/ocean_render_perf/withlock.mjs "builder-render browser tests" -- node tests/ocean_render_browser.mjs --base http://localhost:8182
import { spawn } from "node:child_process";
import { acquire } from "./lock.mjs";

const argv = process.argv.slice(2), cut = argv.indexOf("--");
if (cut < 1 || cut === argv.length - 1) { console.error("usage: withlock.mjs NAME -- COMMAND ARGS..."); process.exit(2); }
const name = argv.slice(0, cut).join(" "), cmd = argv.slice(cut + 1);
const release = await acquire(name);
const child = spawn(cmd[0], cmd.slice(1), { stdio: "inherit", shell: false });
const done = (code) => { release(); process.exit(code === null ? 1 : code); };
child.on("exit", done);
child.on("error", (e) => { console.error("withlock: " + e.message); done(1); });
