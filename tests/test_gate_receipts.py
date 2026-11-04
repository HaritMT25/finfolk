#!/usr/bin/env python3
"""Planted-fault suite for tools/gate_receipts.{sh,py}: temp git repos and fake tools only.
No Emscripten, no simulation gate. Run: python3 -I tests/test_gate_receipts.py"""
import contextlib, importlib.util, json, os, pwd, shutil, signal, stat, subprocess, tempfile, time, unittest

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
FAKE_EMCONFIG = ('#!/bin/sh\ncase "$1" in LLVM_ROOT) echo "$EMSDK/llvm";; BINARYEN_ROOT) echo "$EMSDK/binaryen";; '
                 'NODE_JS) if [ -f "$EMSDK/nodehook" ]; then echo "[\'$EMSDK/node\', \'--require\', \'$EMSDK/hook.cjs\']"; else echo "[\'$EMSDK/node\']"; fi;; EMSCRIPTEN_ROOT) echo "$EMSDK/em";; CLANG_ADD_VERSION|LLVM_ADD_VERSION) echo None;; '
                 'COMPILER_WRAPPER) if [ -f "$EMSDK/wrapper" ]; then echo /usr/local/bin/ccache; else echo None; fi;; *) exit 1;; esac\n')
SDK_FILES = ["llvm/clang", "llvm/clang++", "llvm/wasm-ld", "llvm/llvm-ar", "llvm/llvm-nm", "binaryen/bin/wasm-opt", "node", "em/emscripten-version.txt", "em/emcc.py"]
GATE = ('echo $PPID > "$HOME/ppid"\n'
        'echo "run ${0##*/} FAST=${FAST:-} JOBS=${JOBS:-} KEEP_OUT=${KEEP_OUT:-} opts=${NODE_OPTIONS:-none} bashenv=${BASH_ENV:-none} ld=${LD_PRELOAD:-none}">> "$HOME/count"\n'
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
        self.t = os.path.realpath(tempfile.mkdtemp(dir=pwd.getpwuid(os.getuid()).pw_dir))  # reuse is only allowed on the home filesystem
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home, self.repo, self.bin = (os.path.join(self.t, d) for d in ("home", "repo", "bin"))
        self.store = os.path.join(self.home, "store")
        for d in (self.home, self.repo, self.bin, os.path.join(self.t, "emsdk")): os.makedirs(d)
        wr(os.path.join(self.t, "emsdk", ".emscripten"), "LLVM_ROOT='/x'\n")
        for f in SDK_FILES: self.put(os.path.join(self.t, "emsdk", f), "sdk " + f)
        for n, body in (("node", FAKE_NODE), ("g++", FAKE_CC), ("em++", FAKE_CC), ("em-config", FAKE_EMCONFIG)): self.put(os.path.join(self.bin, n), body, True)
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
        cmd = 'source "%s/tools/gate_receipts.sh"; gate_%s %s -- "$@"' % (self.repo, fn, gate)  # always sourced from the main repo
        return subprocess.Popen(["bash", "-c", cmd, "x", *argv], cwd=cwd or self.repo, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    def go(self, fn, gate, argv=(), **kw):
        p = self.start(fn, gate, argv, **kw)
        out, err = p.communicate()
        return p.returncode, out, err
    def run_(self, gate, argv, **env): return self.go("run", gate, argv, **env)[0]
    def check(self, gate, argv=(), **env):
        rc, out, err = self.go("check", gate, argv, **env)
        if rc in (0, 1): self.assertTrue(out.strip(), "check must print a status object: " + err)  # a traceback is not a miss
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
        for i, rel in enumerate(("binaryen/bin/wasm-opt", "llvm/clang++", "node", "em/emcc.py"), 4):  # the tools Emscripten's config selects
            wr(os.path.join(self.t, "emsdk", rel), "changed", "a"); self.pass_once("ocean-fast", OCEAN, **fast); self.assertEqual(self.n(), i)
        self.put(os.path.join(self.bin, "sed"), "#!/bin/sh\nexec /usr/bin/sed \"$@\"\n", True)  # a shell helper earlier on PATH
        self.pass_once("ocean-fast", OCEAN, **fast); self.assertEqual(self.n(), 8)
        self.pass_once("ocean-fast", OCEAN, **fast, TMPDIR=self.t); self.assertEqual(self.n(), 9)  # every retained variable is keyed
        os.remove(os.path.join(self.bin, "em-config"))  # SDK unverifiable: runs, but never reusable
        for _ in range(2): self.pass_once("ocean-fast", OCEAN, **fast)
        self.assertEqual((self.n(), self.check("ocean-fast", OCEAN, **fast)[1]["reason"]), (11, "nonreusable"))
        os.remove(os.path.join(self.bin, "em++"))
        self.assertEqual(self.run_("ocean-fast", OCEAN, **fast), 125); self.assertEqual(self.check("ocean-fast", OCEAN, **fast)[0], 2)
        self.assertEqual(self.n(), 11)
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
        def ref(k, v): d = json.loads(rd(keyfile())); d.pop(k) if v is None else d.__setitem__(k, v); wr(keyfile(), json.dumps(d))
        def result(k, v): d = json.loads(rd(find(".json"))); d["result"][k] = v; wr(find(".json"), json.dumps(d))
        cases = {"truncated key": (lambda: truncate(keyfile()), "malformed"), "truncated run": (lambda: truncate(find(".json")), "malformed"),
                 "schema": (lambda: alter("schema", 9), "malformed"), "wrong key": (lambda: alter("key", "0" * 64), "malformed"),
                 "missing log": (lambda: os.remove(find(".stdout")), "malformed"), "altered log": (lambda: wr(find(".stderr"), "x", "a"), "evidence"),
                 "no state": (lambda: ref("state", None), "malformed"), "reusable string": (lambda: result("reusable", "false"), "malformed"),
                 "complete truthy": (lambda: result("complete", 1), "malformed"), "wrong run id": (lambda: ref("run", "nope"), "malformed"),
                 "tested null": (lambda: alter("tested", None), "malformed"), "schema true": (lambda: alter("schema", True), "malformed"),
                 "bad duration": (lambda: alter("run", {"id": "x", "duration_ms": "1"}), "malformed")}
        for name, (act, reason) in cases.items():
            with self.subTest(name):
                self.pass_once(GATE_FORCE="1"); act(); rc, st = self.check("turbo", TURBO)
                self.assertEqual((rc, st["reason"]), (1, reason))
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
        self.pass_once("ocean-fast", OCEAN, FAST="1", NODE_OPTIONS="--inspect", BASH_ENV="/nonexistent", LD_PRELOAD="/nonexistent")
        self.assertTrue(self.lines()[0].endswith("opts=none bashenv=none ld=none"))
    def test_keep_out_auto_reaches_the_gate(self):
        self.pass_once("ocean-fast", OCEAN, FAST="1", KEEP_OUT="auto"); self.assertIn("KEEP_OUT=auto", self.lines()[0])
    def test_record_only_gates_never_skip(self):
        def smoke(ok, base="u"): return ["sh", "-c", 'echo run >> "$HOME/count"; echo \'{"ok":%s,"base":"%s"}\'' % (ok, base), "sh", "u"]
        self.assertEqual(self.run_("merged-smoke", smoke("false")), 1)  # exit 0 but ok:false
        self.assertEqual(self.run_("merged-smoke", smoke("true", "other")), 1)  # it visited a different URL than the one passed
        self.assertEqual(self.run_("merged-smoke", ["sh", "-c", "echo not json"]), 1)
        for _ in range(2): self.assertEqual(self.run_("merged-smoke", smoke("true")), 0)
        self.assertEqual(self.n(), 4); self.assertEqual(self.check("merged-smoke")[0], 1)  # the 2 passes both executed
        self.assertEqual(self.run_("browser", ["true"], BASE="http://x"), 0)
    def test_lock_outlives_a_killed_coordinator(self):
        wr(os.path.join(self.home, "slow"), "1.5"); e = dict(FAST="1", OCEAN_PARITY_DIR=self.t + "/o")
        a = self.start("run", "ocean-fast", OCEAN, JOBS="1", **e)
        while not self.lines(): time.sleep(0.05)
        os.kill(int(rd(os.path.join(self.home, "ppid"))), signal.SIGKILL)  # only the coordinator; its gate keeps running
        fin(a); b = self.start("run", "ocean-fast", OCEAN, JOBS="2", **e)  # same output dir, different key
        self.assertEqual(fin(b), 0); time.sleep(0.2)
        self.assertEqual([l.split()[0] for l in self.lines("")], ["run", "end", "run", "end"])  # B started only after A's gate ended
    def test_inputs_are_refreshed_after_waiting_for_the_lock(self):
        wt = os.path.join(self.t, "wt"); self.git("worktree", "add", "-q", "--detach", wt)
        wr(os.path.join(self.home, "slow"), "1.5")
        a = self.start("run", "turbo", TURBO); time.sleep(0.4)
        b = self.start("run", "turbo", TURBO, cwd=wt); time.sleep(0.6)  # B is now blocked on A's key lock
        wr(os.path.join(wt, "web/ocean.js"), "edited while waiting")
        self.assertEqual(fin(a), 0); out, err = b.communicate()
        self.assertEqual((b.returncode, "fresh" in err, self.n()), (0, False, 2))  # B re-checked, saw a dirty tree, and ran
    def test_helper_comes_from_the_candidate_not_from_where_it_was_sourced(self):
        wt = os.path.join(self.t, "wt"); self.git("worktree", "add", "-q", "-b", "b", wt)
        py = os.path.join(wt, "tools/gate_receipts.py"); wr(py, rd(py).replace("SCHEMA, REPO_ID", 'sys.stderr.write("HELPER-B\\n")\nSCHEMA, REPO_ID', 1))
        self.git("commit", "-qam", "other helper", cwd=wt)
        rc, out, err = self.go("run", "turbo", TURBO, cwd=wt)  # sourced from self.repo, run in wt
        self.assertEqual((rc, "HELPER-B" in err), (0, True))
    def test_helper_bytes_are_keyed(self):
        self.pass_once(); self.edit("tools/gate_receipts.py", rd(os.path.join(self.repo, "tools/gate_receipts.py")) + "# edit\n"); self.commit("helper")
        self.pass_once(); self.assertEqual(self.n(), 2)
    def test_case_collisions_and_aliases(self):
        self.edit("web/OCEAN.js", "other"); self.git("add", "-A"); self.commit("collide")
        self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "dirty")
        self.git("reset", "-q", "--hard", "HEAD~1"); os.symlink(self.t + "/o", self.t + "/alias"); wr(os.path.join(self.home, "slow"), "0.5")
        ps = [self.start("run", "ocean-fast", OCEAN, FAST="1", JOBS=str(j), OCEAN_PARITY_DIR=d) for j, d in ((1, self.t + "/o"), (2, self.t + "/alias"))]
        self.assertEqual([fin(p) for p in ps], [0, 0])
        self.assertEqual([l.split()[0] for l in self.lines("")], ["run", "end", "run", "end"])  # same directory by identity, one at a time
    def test_filesystem_support_and_durable_publication(self):
        m = self.mod()
        info = "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n2 1 0:5 / /mnt/a\\011b rw - 9p drvfs rw\n"  # matched by device id: no path escapes to decode
        self.assertEqual([m.dev_fstype(os.makedev(*d), info) for d in ((8, 1), (0, 5), (0, 9))], ["ext4", "9p", None])
        shm = "/dev/shm/gate_receipts_test_%d" % os.getpid(); self.addCleanup(shutil.rmtree, shm, True)  # not the home filesystem
        self.assertEqual(self.check("turbo", TURBO, GATE_RECEIPTS_DIR=shm)[1]["reason"], "nonreusable")
        self.pass_once(GATE_RECEIPTS_DIR=shm); self.pass_once(GATE_RECEIPTS_DIR=shm); self.assertEqual(self.n(), 2)  # runs, never reused
        self.assertIsNotNone(m.fs_reason(["/proc"], "x")); self.assertIsNone(m.fs_reason([self.t], "x"))
        synced, real = [], os.fsync
        m.os.fsync = lambda fd: (synced.append(stat.S_ISDIR(os.fstat(fd).st_mode)), real(fd))[1]
        self.addCleanup(setattr, m.os, "fsync", real)
        os.environ["GATE_RECEIPTS_DIR"] = self.store; self.addCleanup(os.environ.pop, "GATE_RECEIPTS_DIR")
        m.Store().write("keys/k.json", b"{}", True)
        self.assertEqual(synced, [False, True])  # the file, then its directory
    def mod(self):
        spec = importlib.util.spec_from_file_location("gate_receipts", os.path.join(TOOLS, "gate_receipts.py")); m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m); return m
    def test_configured_compiler_wrapper_makes_parity_record_only(self):
        wr(os.path.join(self.t, "emsdk", "wrapper"), "x")
        for _ in range(2): self.pass_once("ocean-fast", OCEAN, FAST="1")
        self.assertEqual((self.n(), self.check("ocean-fast", OCEAN, FAST="1")[1]["reason"]), (2, "nonreusable"))
    def test_configured_node_arguments_make_parity_record_only(self):
        wr(os.path.join(self.t, "emsdk", "nodehook"), "x"); self.put(os.path.join(self.t, "emsdk", "hook.cjs"), "v1")
        self.pass_once("ocean-fast", OCEAN, FAST="1")
        wr(os.path.join(self.t, "emsdk", "hook.cjs"), "v2 changes compilation")  # a preload the SDK identity cannot see
        self.pass_once("ocean-fast", OCEAN, FAST="1")
        self.assertEqual((self.n(), self.check("ocean-fast", OCEAN, FAST="1")[1]["reason"]), (2, "nonreusable"))
    def test_casefold_on_any_ancestor_refuses_reuse(self):
        m = self.mod(); real = m.casefold; self.addCleanup(setattr, m, "casefold", real)
        deep = os.path.join(self.t, "a", "b", "c"); os.makedirs(deep); self.assertIsNone(m.fs_reason([deep], "x", self.t))
        for flagged in (self.t + "/a/b", self.t + "/a", self.t):  # an intermediate directory only, and the top itself
            m.casefold = lambda q, f=flagged: q == f
            self.assertIn(flagged, m.fs_reason([deep], "x", self.t) or "")
        m.casefold = lambda q: q == self.t + "/a"
        self.assertIsNone(m.fs_reason([deep], "x"))  # without `top` only the nearest existing directory is inspected
    @contextlib.contextmanager
    def deadline(self, secs):
        def boom(*_): raise AssertionError("timed out after %d s (hang)" % secs)
        old = signal.signal(signal.SIGALRM, boom); signal.alarm(secs)
        try: yield
        finally: signal.alarm(0); signal.signal(signal.SIGALRM, old)
    def test_pipe_read_failure_terminates_the_gate(self):
        m = self.mod(); real = m.subprocess.Popen
        class P(real):
            def __init__(s, *a, **k):
                super().__init__(*a, **k); raw = s.stdout
                class Bad:
                    def read(self, n): raise OSError("injected read failure")
                    def close(self): raw.close()
                s.stdout = Bad()
        m.subprocess.Popen = P; self.addCleanup(setattr, m.subprocess, "Popen", real)
        t0 = time.time()
        with self.deadline(25): code, clean = m.execute(["sleep", "60"], dict(os.environ), self.fake_store(), "x", [])
        self.assertEqual((code, clean), (137, False)); self.assertLess(time.time() - t0, 20)
    def fake_store(self):
        d = os.path.join(self.t, "evidence"); os.makedirs(os.path.join(d, "runs"), exist_ok=True)
        class S:
            def path(self, *a): return os.path.join(d, *a)
        return S()
    def test_escaped_descendant_holding_the_pipes_cannot_hang_the_coordinator(self):
        m = self.mod(); m.JOIN_S = 1; pidf = os.path.join(self.t, "daemon.pid")
        self.addCleanup(lambda: os.path.exists(pidf) and os.kill(int(rd(pidf)), signal.SIGKILL))
        with self.deadline(25):  # setsid: leaves the gate's process group but keeps stdout/stderr open and writes nothing
            code, clean = m.execute(["sh", "-c", "setsid sh -c 'echo $$ > %s; exec sleep 60' & sleep 0.3; echo hi" % pidf], dict(os.environ), self.fake_store(), "y", [])
        self.assertEqual((code, clean), (0, False))
    def test_noexec_output_mount_refuses_reuse(self):
        out = self.t + "/o"; os.makedirs(out); st = os.stat(out); m = self.mod()
        real = m.noexec; self.addCleanup(setattr, m, "noexec", real)
        self.assertIsNone(m.exec_reason(out + "/new", "x")); m.noexec = lambda q: q == out  # same device and inode, only the mount flag differs
        self.assertIn("noexec", m.exec_reason(out + "/new", "x") or ""); self.assertEqual((os.stat(out).st_dev, os.stat(out).st_ino), (st.st_dev, st.st_ino))
        m.noexec = lambda q: q == "/tmp"; self.assertIn("noexec", m.exec_reason("/tmp", "x") or "")  # the automatic scratch location
        m.noexec = lambda q: os.stat("/nonexistent/x"); self.assertIn("cannot verify", m.exec_reason(out, "x"))
        e = dict(FAST="1", OCEAN_PARITY_DIR=out); self.pass_once("ocean-fast", OCEAN, **e)  # real mount: exec allowed, fresh on repeat
        self.pass_once("ocean-fast", OCEAN, **e); self.assertEqual(self.n(), 1)
    def test_relative_store_override_does_not_loop(self):
        for fn in ("run", "check"):
            p = self.start(fn, "turbo", TURBO, GATE_RECEIPTS_DIR="rel-store")  # no such directory, relative to the repository root
            try: p.communicate(timeout=30)
            except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL); p.communicate(); self.fail("%s hung on a relative store path" % fn)
            self.assertIn(p.returncode, (0, 1))
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "rel-store", "keys")))
    def test_helper_replaced_while_waiting_is_refused(self):
        wt = os.path.join(self.t, "wt"); self.git("worktree", "add", "-q", "--detach", wt); wr(os.path.join(self.home, "slow"), "1.5")
        a = self.start("run", "turbo", TURBO); time.sleep(0.4); b = self.start("run", "turbo", TURBO, cwd=wt); time.sleep(0.6)
        py = os.path.join(wt, "tools/gate_receipts.py"); wr(py, rd(py) + "# new implementation\n"); self.git("commit", "-qam", "helper", cwd=wt)
        self.assertEqual(fin(a), 0); self.assertEqual(fin(b), 125); self.assertEqual(self.n(), 1)  # clean new tree, but never the old code
    def test_output_failures_are_never_reusable_and_never_hang(self):
        wr(os.path.join(self.home, "hook"), "head -c 3000000 /dev/zero\n")
        p = self.start("run", "turbo", TURBO); p.stdout.close()  # the consumer goes away
        self.assertEqual(fin(p), 125); self.assertEqual(self.check("turbo", TURBO)[1]["reason"], "failed")
        class Dead:  # evidence cannot be written
            def path(self, *a): return "/dev/full"
        code, clean = self.mod().execute(["sh", "-c", "echo hi; head -c 3000000 /dev/zero"], dict(os.environ), Dead(), "x", [])
        self.assertEqual((code, clean), (0, False))
    def test_cancellation_and_leftover_processes(self):
        wr(os.path.join(self.home, "slow"), "30"); t0 = time.time()
        a = self.start("run", "turbo", TURBO)
        while not self.lines(): time.sleep(0.05)
        os.kill(int(rd(os.path.join(self.home, "ppid"))), signal.SIGINT)  # Ctrl-C reaches the gate, not just the coordinator
        self.assertNotEqual(fin(a), 0); self.assertEqual((self.lines("end"), self.check("turbo", TURBO)[1]["reason"]), ([], "failed")); self.assertLess(time.time() - t0, 20)
        os.remove(os.path.join(self.home, "slow")); wr(os.path.join(self.home, "hook"), "sleep 60 >/dev/null 2>&1 &\n")  # a leftover background process
        t0 = time.time(); self.pass_once(); self.pass_once(GATE_FORCE="1"); self.assertLess(time.time() - t0, 30)  # reaped: the key lock is free again
    def test_unreadable_record_is_a_storage_error(self):
        self.pass_once(); k = os.path.join(self.store, "keys"); f = os.path.join(k, os.listdir(k)[0]); os.chmod(f, 0)
        rc, st = self.check("turbo", TURBO); self.assertEqual((rc, st["reason"]), (2, "error"))
    def test_storage_failure_follows_the_protocol(self):
        wr(self.t + "/afile", "x"); bad = dict(GATE_RECEIPTS_DIR=self.t + "/afile/store")
        self.assertEqual(self.run_("turbo", TURBO, **bad), 125); self.assertEqual(self.n(), 0)
        rc, st = self.check("turbo", TURBO, **bad); self.assertEqual((rc, st["status"]), (2, "stale"))
    def test_sourcing_is_inert_and_syntax_ok(self):
        r = subprocess.run(["bash", "-c", "source tools/gate_receipts.sh"], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(subprocess.run(["bash", "-n", "tools/gate_receipts.sh"], cwd=self.repo).returncode, 0)
        self.assertEqual(subprocess.run(["python3", "-I", "-m", "py_compile", "tools/gate_receipts.py"], cwd=self.repo).returncode, 0)

if __name__ == "__main__":
    unittest.main()
