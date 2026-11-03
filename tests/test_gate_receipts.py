#!/usr/bin/env python3
"""Planted-fault suite for tools/gate_receipts.{sh,py}: temp git repos and fake tools only.
No Emscripten, no simulation gate. Run: python3 -I tests/test_gate_receipts.py"""
import json, os, shutil, signal, subprocess, tempfile, time, unittest

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
GATE = ('echo "run ${0##*/} FAST=${FAST:-} JOBS=${JOBS:-} opts=${NODE_OPTIONS:-none}" >> "$HOME/count"\n'
        '[ -f "$HOME/slow" ] && sleep "$(cat "$HOME/slow")"\n[ -f "$HOME/hook" ] && sh "$HOME/hook"\n'
        'echo end >> "$HOME/count"\n[ -f "$HOME/fail" ] && exit "$(cat "$HOME/fail")"\nexit 0\n')
FAKE_NODE = '#!/bin/sh\ncase "$1" in -p) echo \'{"node":"fake"}\';; --version) echo v0;; *) exec sh "$@";; esac\n'
FAKE_CC = '#!/bin/sh\necho "fake 1.0"\n'
OCEAN, TURBO = ["bash", "wasm/ocean_parity.sh"], ["node", "tests/ocean_turbo_handoff.js"]

def wr(p, s, mode="w"):
    with open(p, mode) as f: f.write(s)

def fin(p):
    p.communicate()
    return p.returncode

def rd(p):
    with open(p) as f: return f.read()

class Base(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home, self.repo, self.bin = (os.path.join(self.t, d) for d in ("home", "repo", "bin"))
        self.store = os.path.join(self.home, "store")
        for d in (self.home, self.repo, self.bin, os.path.join(self.t, "emsdk")): os.makedirs(d)
        wr(os.path.join(self.t, "emsdk", ".emscripten"), "LLVM_ROOT='/x'\n")
        for n, body in (("node", FAKE_NODE), ("g++", FAKE_CC), ("em++", FAKE_CC)): self.put(os.path.join(self.bin, n), body, True)
        self.env = dict(PATH=self.bin + ":/usr/bin:/bin", HOME=self.home, GATE_RECEIPTS_DIR=self.store, EMSDK=os.path.join(self.t, "emsdk"))
        files = {"tests/ocean_turbo_handoff.js": GATE, "wasm/parity.sh": GATE, "wasm/ocean_parity.sh": GATE, "web/evo_boids.wasm": "a",
                 "web/evo_boids_mt.wasm": "b", "web/ocean.js": "js", "tests/ocean_baseline/c.txt": "1", "tests/ocean_appearance_vectors.txt": "v",
                 "docs/x.md": "doc", "web/evo_ocean.wasm": "w", ".gitignore": "build/\nsecret.txt\n"}
        for n in ("sh", "py"): files["tools/gate_receipts." + n] = rd(os.path.join(TOOLS, "gate_receipts." + n))
        for n, body in files.items(): self.put(os.path.join(self.repo, n), body)
        for a in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "base"]): self.git(*a)
        self.pin = os.path.join(self.t, "pin.sha256")
        self.write_pin(["web/evo_boids.wasm", "web/evo_boids_mt.wasm"])
    def put(self, path, body, exe=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wr(path, body)
        if exe or path.endswith(".sh"): os.chmod(path, 0o755)
    def write_pin(self, names):
        sums = {n: subprocess.run(["sha256sum", n], cwd=self.repo, capture_output=True, text=True).stdout.split()[0] for n in names}
        wr(self.pin, "".join("%s  %s\n" % (h, n) for n, h in sums.items()))
    def git(self, *a, cwd=None):
        e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(["git", *a], cwd=cwd or self.repo, env=e, check=True, capture_output=True, text=True).stdout.strip()
    def start(self, fn, gate, argv=(), cwd=None, **env):
        e = dict(self.env, **env)
        cmd = 'source tools/gate_receipts.sh; gate_%s %s -- "$@"' % (fn, gate)
        return subprocess.Popen(["bash", "-c", cmd, "x", *argv], cwd=cwd or self.repo, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    def go(self, fn, gate, argv=(), **kw):
        p = self.start(fn, gate, argv, **kw)
        out, err = p.communicate()
        return p.returncode, out, err
    def run_(self, gate, argv, **env): return self.go("run", gate, argv, **env)[0]
    def check(self, gate, argv=(), **env):
        rc, out, _ = self.go("check", gate, argv, **env)
        return rc, (json.loads(out) if out.strip() else {})
    def lines(self, prefix="run"):
        try: return [l for l in rd(os.path.join(self.home, "count")).splitlines() if l.startswith(prefix)]
        except OSError: return []
    def n(self): return len(self.lines())
    def commit(self, msg="m", empty=False): self.git("commit", "-qam", msg, *(["--allow-empty"] if empty else []))
    def edit(self, rel, body):
        self.put(os.path.join(self.repo, rel), body)
    def pass_once(self, gate="turbo", argv=TURBO, **env):
        self.assertEqual(self.run_(gate, argv, **env), 0)

class Receipts(Base):
    def test_repeat_hits(self):
        self.pass_once(); self.pass_once(); self.assertEqual(self.n(), 1)
        rc, st = self.check("turbo", TURBO)
        self.assertEqual((rc, st["status"], st["reason"]), (0, "fresh", "hit"))
    def test_two_worktrees_one_execution(self):
        wt = os.path.join(self.t, "wt"); self.git("worktree", "add", "-q", "--detach", wt)
        wr(os.path.join(self.home, "slow"), "1")
        ps = [self.start("run", "turbo", TURBO), self.start("run", "turbo", TURBO, cwd=wt)]
        self.assertEqual([fin(p) for p in ps], [0, 0]); self.assertEqual(self.n(), 1)
    def test_tree_changes_miss_and_revert_hits(self):
        self.pass_once(); base = self.git("rev-parse", "HEAD"); runs = 1
        muts = {"baseline": ("tests/ocean_baseline/c.txt", "2"), "vector": ("tests/ocean_appearance_vectors.txt", "w"), "js": ("web/ocean.js", "j2"),
                "wasm": ("web/evo_ocean.wasm", "w2"), "harness": ("wasm/ocean_parity.sh", GATE + "# h\n"), "docs": ("docs/x.md", "doc2")}
        for name, (rel, body) in muts.items():
            with self.subTest(name):
                self.edit(rel, body); self.commit(name); self.pass_once(); runs += 1; self.assertEqual(self.n(), runs)
                self.git("reset", "-q", "--hard", base); self.pass_once(); self.assertEqual(self.n(), runs)  # same tree again: hit
        for name, act in (("mode", lambda: os.chmod(os.path.join(self.repo, "web/ocean.js"), 0o755)), ("delete", lambda: os.remove(os.path.join(self.repo, "docs/x.md")))):
            with self.subTest(name):
                act(); self.commit(name); self.pass_once(); runs += 1; self.assertEqual(self.n(), runs); self.git("reset", "-q", "--hard", base)
    def test_identical_tree_new_commit_hits_and_keeps_tested_sha(self):
        self.pass_once(); tested = self.git("rev-parse", "HEAD"); self.commit("empty", empty=True)
        self.pass_once(); self.assertEqual(self.n(), 1)
        rc, st = self.check("turbo", TURBO)
        self.assertEqual((rc, st["tested_commit"], st["identical_tree"]), (0, tested, True)); self.assertNotEqual(st["candidate_commit"], tested)
    def test_scope_knobs(self):
        fast = dict(FAST="1", JOBS="2", BUILD_JOBS="2")
        self.pass_once("ocean-fast", OCEAN, **fast)
        self.assertEqual(self.run_("ocean-fast", OCEAN, FAST="0"), 2)            # "0" is still FAST in the script: refuse
        self.assertEqual(self.run_("ocean-full", OCEAN, FAST="0"), 2)
        self.assertEqual(self.run_("ocean-full", OCEAN, ONLY="x"), 2)
        self.assertEqual(self.run_("ocean-all-twins", OCEAN), 2)
        self.assertEqual(self.check("ocean-full", OCEAN, **fast)[0], 2)
        self.assertEqual(self.check("ocean-full", OCEAN)[0], 1)                  # FAST pass does not satisfy full
        self.pass_once("ocean-full", OCEAN); self.assertEqual(self.n(), 2)
        self.assertEqual(self.check("ocean-all-twins", OCEAN, APP_TWINS="all")[0], 1)  # full does not satisfy all-twins
        self.pass_once("ocean-all-twins", OCEAN, APP_TWINS="all"); self.assertEqual(self.n(), 3)
        self.pass_once("ocean-fast", OCEAN, **fast); self.assertEqual(self.n(), 3)
        for extra in (dict(JOBS="3"), dict(BUILD_JOBS="1"), dict(OCEAN_PARITY_DIR=self.t + "/o1"), dict(KEEP_OUT="1")):
            with self.subTest(extra):
                before = self.n(); self.pass_once("ocean-fast", OCEAN, **dict(fast, **extra)); self.assertEqual(self.n(), before + 1)
        self.assertEqual(self.run_("ocean-fast", OCEAN, FAST="1", JOBS="0"), 2)
    def test_explicit_output_dir_serialises(self):
        wr(os.path.join(self.home, "slow"), "0.5")
        e = dict(FAST="1", OCEAN_PARITY_DIR=self.t + "/o")
        ps = [self.start("run", "ocean-fast", OCEAN, JOBS=str(j), **e) for j in (1, 2)]
        self.assertEqual([fin(p) for p in ps], [0, 0])
        self.assertEqual([l.split()[0] for l in self.lines("")], ["run", "end", "run", "end"])
    def test_tool_and_config_identity(self):
        fast = dict(FAST="1"); self.pass_once("ocean-fast", OCEAN, **fast)
        self.put(os.path.join(self.bin, "g++"), FAKE_CC + "# same version text, different bytes\n", True)
        self.pass_once("ocean-fast", OCEAN, **fast); self.assertEqual(self.n(), 2)
        wr(os.path.join(self.t, "emsdk", ".emscripten"), "# changed\n", "a")
        self.pass_once("ocean-fast", OCEAN, **fast); self.assertEqual(self.n(), 3)
        os.remove(os.path.join(self.bin, "em++"))
        self.assertEqual(self.run_("ocean-fast", OCEAN, **fast), 125); self.assertEqual(self.check("ocean-fast", OCEAN, **fast)[0], 2)
        self.assertEqual(self.n(), 3)
    def test_classic_sha_pin(self):
        cmd = ["sha256sum", "-c", self.pin]
        self.pass_once("classic-sha", cmd); self.assertEqual(self.check("classic-sha", cmd)[0], 0)
        self.write_pin(["web/evo_boids_mt.wasm", "web/evo_boids.wasm"]); self.assertEqual(self.check("classic-sha", cmd)[0], 1)  # pin bytes changed
        for bad in ("%s  /elsewhere/web/evo_boids.wasm\n" % ("0" * 64), "garbage\n", ""):
            with self.subTest(bad):
                wr(self.pin, bad)
                self.assertEqual(self.check("classic-sha", cmd)[1]["reason"], "nonreusable")
        self.write_pin(["web/evo_boids.wasm"]); self.assertEqual(self.check("classic-sha", cmd)[1]["reason"], "nonreusable")
        self.assertEqual(self.check("classic-sha", ["sha256sum", "-c", self.t + "/missing"])[1]["reason"], "nonreusable")
    def test_wrong_commands_publish_nothing(self):
        for gate, argv in (("ocean-full", ["true"]), ("ocean-full", OCEAN + ["--help"]), ("ocean-full", OCEAN + ["--rebaseline"]),
                           ("ocean-full", ["bash", "-c", "wasm/ocean_parity.sh | cat"]), ("turbo", TURBO + ["section"]), ("turbo", ["true"]), ("nope", ["true"])):
            with self.subTest(argv): self.assertEqual(self.run_(gate, argv), 2)
        self.assertEqual((self.n(), os.path.exists(self.store)), (0, False))
    def test_failure_supersedes_pass(self):
        self.pass_once(); wr(os.path.join(self.home, "fail"), "7")
        self.assertEqual(self.run_("turbo", TURBO, GATE_FORCE="1"), 7)
        self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "failed"); os.remove(os.path.join(self.home, "fail"))
        self.pass_once(); self.assertEqual(self.n(), 3)
    def test_kill_and_publication_failure(self):
        wr(os.path.join(self.home, "slow"), "30")
        for sig in (signal.SIGKILL, signal.SIGTERM):
            p = self.start("run", "turbo", TURBO, GATE_FORCE="1")
            while not self.lines(): time.sleep(0.05)
            os.killpg(p.pid, sig); fin(p)
            self.assertEqual(self.check("turbo", TURBO)[0], 1); os.remove(os.path.join(self.home, "count"))
        os.remove(os.path.join(self.home, "slow"))
        wr(os.path.join(self.home, "hook"), 'chmod 500 "$HOME/store/keys"\n')
        self.assertEqual(self.run_("turbo", TURBO), 125); os.chmod(os.path.join(self.store, "keys"), 0o755); os.remove(os.path.join(self.home, "hook"))
        self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "running")
        self.pass_once()  # lock recovery: the next run proceeds and publishes
    def test_dirty_checkout_never_reusable(self):
        shadow = os.path.join(self.repo, "secret.txt")
        muts = {"file": lambda: self.edit("web/ocean.js", "dirty"), "index": lambda: (self.edit("web/ocean.js", "dirty"), self.git("add", "-A")),
                "untracked": lambda: self.edit("new.js", "x"), "ignored shadow": lambda: self.edit("secret.txt", "x")}
        for name, act in muts.items():
            with self.subTest(name):
                act(); self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "dirty")
                before = self.n(); self.pass_once(); self.pass_once(); self.assertEqual(self.n(), before + 2)  # runs, never reuses
                self.git("reset", "-q", "--hard"); self.git("clean", "-qfdx", "-e", "store")
        self.assertEqual(self.check("turbo", TURBO)[0], 1)  # nothing was published for the clean tree
    def test_mutation_during_run(self):
        wr(os.path.join(self.home, "hook"), 'echo more >> "%s/docs/x.md"\n' % self.repo)
        self.pass_once(); os.remove(os.path.join(self.home, "hook")); self.git("checkout", "-q", "--", "docs/x.md")
        self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "nonreusable")
    def test_corrupt_receipts_miss(self):
        def runs(): return os.path.join(self.store, "runs")
        def keyfile(): return os.path.join(self.store, "keys", os.listdir(os.path.join(self.store, "keys"))[0])
        def find(suffix): return os.path.join(runs(), [f for f in os.listdir(runs()) if f.endswith(suffix)][0])
        def truncate(p): wr(p, rd(p)[:20])
        def alter(k, v): d = json.loads(rd(find(".json"))); d[k] = v; wr(find(".json"), json.dumps(d))
        cases = {"truncated key": lambda: truncate(keyfile()), "truncated run": lambda: truncate(find(".json")), "schema": lambda: alter("schema", 9),
                 "wrong key": lambda: alter("key", "0" * 64), "missing log": lambda: os.remove(find(".stdout")),
                 "altered log": lambda: wr(find(".stderr"), "x", "a")}
        for name, act in cases.items():
            with self.subTest(name):
                self.pass_once(GATE_FORCE="1"); act(); self.assertEqual(self.check("turbo", TURBO)[0], 1)
                shutil.rmtree(self.store)
    def test_timestamps_do_not_matter(self):
        self.pass_once()
        for dp, _, fs in os.walk(self.store):
            for f in fs: os.utime(os.path.join(dp, f), (4102444800, 4102444800))
        self.assertEqual(self.check("turbo", TURBO)[0], 0)
    def test_ci_and_force_execute_again(self):
        self.pass_once()
        for env in (dict(CI="1"), dict(GITHUB_ACTIONS="true"), dict(GATE_FORCE="1")):
            with self.subTest(env):
                before = self.n(); self.pass_once(**env); self.assertEqual(self.n(), before + 1)
                self.assertEqual(self.check("turbo", TURBO, **env)[0], 1)
    def test_child_environment_is_closed(self):
        self.pass_once(NODE_OPTIONS="--inspect", BASH_ENV="/nonexistent")
        self.assertTrue(self.lines()[0].endswith("opts=none"))
    def test_record_only_gates_never_skip(self):
        ok = ["sh", "-c", 'echo run >> "$HOME/count"; echo \'{"ok":%s}\'']
        self.assertEqual(self.run_("merged-smoke", [ok[0], ok[1], ok[2] % "false"]), 1)  # exit 0 but ok:false
        self.assertEqual(self.run_("merged-smoke", ["sh", "-c", "echo not json"]), 1)
        for _ in range(2): self.assertEqual(self.run_("merged-smoke", [ok[0], ok[1], ok[2] % "true"]), 0)
        self.assertEqual(self.n(), 3); self.assertEqual(self.check("merged-smoke")[0], 1)  # the 2 passes both executed
        self.assertEqual(self.run_("browser", ["true"], BASE="http://x"), 0)
    def test_sourcing_is_inert_and_syntax_ok(self):
        r = subprocess.run(["bash", "-c", "source tools/gate_receipts.sh"], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(subprocess.run(["bash", "-n", "tools/gate_receipts.sh"], cwd=self.repo).returncode, 0)
        self.assertEqual(subprocess.run(["python3", "-I", "-m", "py_compile", "tools/gate_receipts.py"], cwd=self.repo).returncode, 0)

if __name__ == "__main__":
    unittest.main()
