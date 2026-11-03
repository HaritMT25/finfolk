#!/usr/bin/env python3
"""Gate receipts: a local record of a passed gate so an unchanged candidate is not re-gated.

Usage (via tools/gate_receipts.sh): gate_receipts.py run|check GATE [-- ARGV...]
A receipt is fresh only when every member of its key matches (docs/gate_receipts.md).
It is a trusted local optimisation, never an attestation: CI runs every gate itself.
"""
import ast, fcntl, hashlib, json, os, platform, re, shutil, signal, stat, subprocess, sys, tempfile, threading, time, uuid

SCHEMA, REPO_ID = 1, "github.com/HaritMT25/finfolk"
KEPT = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "EMSDK", "EMSDK_NODE", "EMSDK_PYTHON", "EM_CONFIG", "EM_CACHE")  # all keyed
FS_OK = ("ext4", "tmpfs", "xfs", "btrfs", "overlay")  # local filesystems with the flock/rename/case semantics receipts rely on
HELPERS = ("awk", "sed", "grep", "sort", "xargs", "mktemp", "cat", "head", "tail", "timeout", "nproc", "uname", "rm", "mkdir", "cp", "mv",
           "wc", "tr", "cut", "date", "find", "nice", "env", "ln", "tee", "basename", "dirname", "readlink", "realpath", "stat", "touch",
           "/usr/bin/time")  # shell helpers the parity scripts call: executable bytes are keyed (absent is recorded as absent)
FIXED = {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"}
SEL = ("FAST", "ONLY", "NO_EYE", "NO_TESTS", "APP_TWINS")
OCEAN_KNOBS = SEL + ("JOBS", "BUILD_JOBS", "OCEAN_PARITY_DIR", "KEEP_OUT")
BUILD = ("bash", "g++", "em++", "node", "sha256sum", "cmp", "diff")
PROBES = {"node": (["-p", "JSON.stringify(process.versions)"],), "g++": (["--version"], ["-dumpmachine"]),
          "em++": (["--version"], ["-v"])}
IGNORED_OK = re.compile(r"^(build(_[^/]*)?|dist|\.vercel|runs)/|^docs/evo_boids_(context|perf)\.md$")
SDK_FILES = (("LLVM_ROOT", ("clang", "clang++", "wasm-ld", "llvm-ar", "llvm-nm")), ("BINARYEN_ROOT", ("bin/wasm-opt",)))
PIN_FILES = ("web/evo_boids.wasm", "web/evo_boids_mt.wasm")

def _ocean(req):  # a registered Ocean parity profile: selection knobs must equal `req` exactly
    return dict(argv=["bash", "wasm/ocean_parity.sh"], knobs=OCEAN_KNOBS, dir="OCEAN_PARITY_DIR", tools=BUILD,
                emsdk=True, pkgs=True, req=dict({k: None for k in SEL}, **req))

PROFILES = {
    "classic-parity": dict(argv=["bash", "wasm/parity.sh"], knobs=("PARITY_DIR", "KEEP_OUT"), dir="PARITY_DIR",
                           tools=BUILD, emsdk=True, pkgs=True, req={}),
    "ocean-fast": _ocean({"FAST": "1"}),
    "ocean-full": _ocean({}),
    "ocean-all-twins": _ocean({"APP_TWINS": "all"}),
    "ocean-app-live-twin": _ocean({"APP_TWINS": "all", "ONLY": "app_live_s21", "NO_TESTS": "1", "NO_EYE": "1"}),
    "turbo": dict(argv=["node", "tests/ocean_turbo_handoff.js"], knobs=(), tools=("node",), req={}),
    "classic-sha": dict(argv=["sha256sum", "-c", None], knobs=(), tools=("sha256sum",), pin=True, req={}),
    # record-only: observed and logged, never a skip
    "browser": dict(record=True, observe=("BASE", "PLAYWRIGHT", "BRAVE_EXE")),
    "merged-smoke": dict(record=True, observe=("BASE", "PLAYWRIGHT", "BRAVE_EXE"), json_ok=True),
    "native-parallel": dict(record=True, observe=()),
    "deploy": dict(record=True, observe=()),
}

class Invalid(Exception): pass    # bad invocation (exit 2)
class Identity(Exception): pass   # required identity could not be collected (check 2, run 125)

def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def sha_file(p):
    with open(p, "rb") as f: return sha(f.read())

def git(root, *a):
    r = subprocess.run(["git", *a], cwd=root, capture_output=True)
    if r.returncode: raise Identity("git %s failed: %s" % (a[0], r.stderr.decode(errors="replace").strip()))
    return r.stdout

def repo_state(root):
    """Commit, tree, and every reason the checkout is not exactly its HEAD tree."""
    st = dict(commit=git(root, "rev-parse", "HEAD").decode().strip(),
              tree=git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
              fmt=git(root, "rev-parse", "--show-object-format").decode().strip(), problems=[])
    p = st["problems"]
    if subprocess.run(["git", "diff-index", "--cached", "--quiet", "HEAD"], cwd=root).returncode: p.append("index differs from HEAD")
    for m in git(root, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0"):
        if m: p.append("untracked " + m.decode(errors="replace"))
    for m in git(root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory").split(b"\0"):
        if m and not IGNORED_OK.match(m.decode(errors="replace")): p.append("ignored shadow " + m.decode(errors="replace"))
    seen = {}
    for e in git(root, "ls-files", "-z", "--stage").split(b"\0"):
        if not e: continue
        meta, path = e.decode(errors="surrogateescape").split("\t", 1)
        if seen.setdefault(path.lower(), path) != path: p.append("case-colliding paths %s / %s" % (seen[path.lower()], path))
        mode, oid, stage = meta.split()
        full = os.path.join(root, path)
        try:
            s = os.lstat(full)
            if stage != "0" or not stat.S_ISREG(s.st_mode) or mode not in ("100644", "100755"): raise ValueError
            if (mode == "100755") != bool(s.st_mode & 0o100): raise ValueError
            with open(full, "rb") as f: data = f.read()
            if hashlib.new("sha256" if st["fmt"] == "sha256" else "sha1", b"blob %d\0" % len(data) + data).hexdigest() != oid: raise ValueError
        except (OSError, ValueError):
            p.append("tracked file differs: " + path)
    return st

def tool_identity(tool, env, helper=False):
    path = shutil.which(tool, path=env["PATH"])
    if not path:
        if helper: return None
        raise Identity("tool not found: " + tool)
    out = []
    for args in () if helper else PROBES.get(tool, (["--version"],)):
        try: r = subprocess.run([path, *args], env=env, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e: raise Identity("probe %s failed: %s" % (tool, e))
        out.append([r.returncode, (r.stdout + r.stderr).decode(errors="replace")[:4000]])
    real = os.path.realpath(path)
    return dict(path=path, real=real, sha256=sha_file(real), probes=out)

def fstype(path, mountinfo=None):
    try: text = mountinfo if mountinfo is not None else open("/proc/self/mountinfo").read()
    except OSError: return None
    path, best = os.path.realpath(path), ("", None)
    for line in text.splitlines():
        left, _, right = line.partition(" - ")
        mp = left.split()[4].replace("\\040", " ")
        if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best[0]) and right.split(): best = (mp, right.split()[0])
    return best[1]

def fs_reason(path, label):
    t = fstype(path)
    return None if t in FS_OK else "unsupported filesystem for %s: %s" % (label, t)

def host_identity(root):
    osr = {}
    try:
        for line in open("/etc/os-release"):
            k, _, v = line.strip().partition("=")
            if k in ("ID", "VERSION_ID"): osr[k] = v.strip('"')
    except OSError: pass
    return dict(machine=platform.machine(), system=platform.system(), os=osr, repo_fs=fstype(root))

def sdk_identity(env):
    """The tools Emscripten's own configuration selects (via em-config), not whatever is on PATH."""
    cfg = shutil.which("em-config", path=env["PATH"])
    if not cfg: raise Identity("em-config not found")
    v, files = {}, {}
    for k in ("EMSCRIPTEN_ROOT", "LLVM_ROOT", "BINARYEN_ROOT", "NODE_JS"):
        r = subprocess.run([cfg, k], env=env, capture_output=True, timeout=60)
        txt = r.stdout.decode().strip()
        if r.returncode or not txt: raise Identity("em-config %s failed" % k)
        try: txt = ast.literal_eval(txt)
        except (ValueError, SyntaxError): pass
        v[k] = txt[0] if isinstance(txt, list) else txt
    paths = [os.path.join(v["LLVM_ROOT"], f) for f in SDK_FILES[0][1]] + [os.path.join(v["BINARYEN_ROOT"], f) for f in SDK_FILES[1][1]] + [v["NODE_JS"]]
    root = v["EMSCRIPTEN_ROOT"]
    for d in (root, os.path.join(root, "tools")):
        paths += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py")] if os.path.isdir(d) else []
    paths.append(os.path.join(root, "emscripten-version.txt"))
    for f in paths:
        if not os.path.isfile(f): raise Identity("configured SDK file missing: " + f)
        files[f] = sha_file(os.path.realpath(f))
    return dict(roots=v, files=files)

def pin_identity(pin, root):
    """Hash the pin on every lookup; its entries must be the candidate's own committed artifacts."""
    try:
        data = open(pin, "rb").read()
    except OSError as e: raise Identity("pin unreadable: %s" % e)
    arts = {}
    for line in data.decode(errors="replace").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
        if not m: raise Identity("unexpected pin line: %r" % line)
        name = m.group(2)
        real = os.path.realpath(os.path.join(root, name))
        if name not in PIN_FILES or not real.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(real):
            raise Identity("pin entry does not resolve to a candidate artifact: " + name)
        arts[name] = sha_file(real)
    if sorted(arts) != sorted(PIN_FILES): raise Identity("pin must name exactly " + ", ".join(PIN_FILES))
    return dict(pin_path=os.path.realpath(pin), pin_sha256=sha(data), artifacts=arts)

def prepare(gate, argv, root, parent):
    """Validate the request and compute (profile, child env, key material, reasons the run is not reusable)."""
    prof = PROFILES.get(gate)
    if prof is None: raise Invalid("unknown gate %r (known: %s)" % (gate, ", ".join(PROFILES)))
    if prof.get("record"):
        return prof, dict(parent), None, ["record-only gate"]
    if not argv: raise Invalid("a command is required after --")
    want = [a if a is not None else argv[i] for i, a in enumerate(prof["argv"])] if len(argv) == len(prof["argv"]) else None
    if argv != want: raise Invalid("%s requires exactly: %s" % (gate, " ".join(a or "<pin-file>" for a in prof["argv"])))
    if "PATH" not in parent: raise Invalid("PATH is not set")
    env = {k: parent[k] for k in KEPT if k in parent}
    env.update(FIXED)
    knobs = {k: (parent.get(k) or None) for k in prof["knobs"]}
    for k, v in prof["req"].items():
        if knobs[k] != v: raise Invalid("%s requires %s=%s (got %s)" % (gate, k, v, knobs[k]))
    if "JOBS" in knobs:
        for k in ("JOBS", "BUILD_JOBS"):
            if knobs[k] is not None and not re.fullmatch(r"[1-9][0-9]*", knobs[k]): raise Invalid(k + " must be a positive integer")
        knobs["JOBS"] = knobs["JOBS"] or "4"
        knobs["BUILD_JOBS"] = knobs["BUILD_JOBS"] or str(min(int(knobs["JOBS"]), 2))
    reasons, ext, d = [], {}, prof.get("dir")
    if d and knobs[d]: knobs[d] = os.path.realpath(knobs[d])
    elif d: knobs[d] = "auto"
    env.update({k: v for k, v in knobs.items() if v is not None and not (k == d and v == "auto")})
    if d and knobs[d] != "auto": reasons.append(fs_reason(knobs[d], "output dir"))
    reasons += [fs_reason(root, "repository"), fs_reason(Store.default_root(), "receipt store")]
    if prof.get("emsdk"):
        cfg = env.get("EM_CONFIG") or (os.path.join(env["EMSDK"], ".emscripten") if env.get("EMSDK") else "")
        if not shutil.which("em++", path=env["PATH"]): raise Identity("em++ not on PATH: source emsdk_env.sh first")
        if cfg and os.path.isfile(cfg): ext["emscripten_config"] = [os.path.realpath(cfg), sha_file(cfg)]
        else: reasons.append("emscripten config file not found")
        try: ext["emscripten_sdk"] = sdk_identity(env)
        except (Identity, OSError, subprocess.TimeoutExpired) as e: reasons.append("emscripten SDK unverifiable: %s" % e)
    if prof.get("pkgs"):
        r = subprocess.run(["dpkg-query", "-W", "-f", "${Package} ${Version}\\n"], env=env, capture_output=True) if shutil.which("dpkg-query", path=env["PATH"]) else None
        if r and r.returncode == 0: ext["dpkg_inventory"] = sha(r.stdout)
        else: reasons.append("package inventory unavailable")
        ext["helpers"] = {h: tool_identity(h, env, True) for h in HELPERS}
    if prof.get("pin"):
        try: ext["pin"] = pin_identity(argv[2], root)
        except Identity as e: reasons.append(str(e))
    tools = {t: tool_identity(t, env) for t in prof["tools"]}
    return prof, env, dict(
        schema=SCHEMA, receipt_definition_digest=sha(canon([prof, sha_file(__file__)])), repository_id=REPO_ID, gate_name=gate,
        argv=argv, coverage_profile=gate, effective_child_environment=dict(env, knobs=knobs),
        toolchain_identity=tools, external_input_hashes=ext, host_identity=host_identity(root)), [r for r in reasons if r]


class Store:
    @staticmethod
    def default_root(): return os.environ.get("GATE_RECEIPTS_DIR") or os.path.expanduser("~/wasm_parity/receipts_store/finfolk/v1")

    def __init__(self):
        self.root = self.default_root()
        for d in ("locks", "keys", "runs"): os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def path(self, *a): return os.path.join(self.root, *a)

    def lock(self, name):  # flock; the gate inherits the descriptor, so the lock outlives a killed coordinator
        fd = os.open(self.path("locks", name + ".lock"), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.set_inheritable(fd, True)
        return fd

    def write(self, rel, data, replace):  # temp file in the same directory, fsync, atomic rename, fsync the directory
        d = os.path.dirname(self.path(rel))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.path(rel)) if replace else os.rename(tmp, self.path(rel))
        dfd = os.open(d, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)

    def lookup(self, key):
        """(reason, receipt): reason is 'hit' only for an intact terminal success with this exact key."""
        try:
            ref = json.load(open(self.path("keys", key + ".json")))
        except FileNotFoundError: return "missing", None
        except (OSError, ValueError): return "malformed", None
        if not isinstance(ref, dict) or ref.get("schema") != SCHEMA or ref.get("key") != key: return "malformed", None
        if ref.get("state") == "running": return "running", None
        if ref.get("state") != "done" or not isinstance(ref.get("run"), str): return "malformed", None
        try:
            rc = json.load(open(self.path("runs", "%s.json" % ref["run"])))
            if rc["schema"] != SCHEMA or rc["key"] != key or sha(canon(rc["inputs"])) != key or rc["run"]["id"] != ref["run"]: return "malformed", None
            res = rc["result"]
            if res["complete"] is not True or type(res["exit_code"]) is not int or type(res["reusable"]) is not bool: return "malformed", None
            if res["exit_code"] != 0: return "failed", rc
            if not res["reusable"]: return "nonreusable", rc
            for s in ("stdout", "stderr"):
                if sha_file(self.path(rc["evidence"][s])) != rc["evidence"][s + "_sha256"]: return "evidence", rc
        except (OSError, ValueError, KeyError, TypeError): return "malformed", None
        return "hit", rc


def execute(argv, env, store, run_id, fds):
    """Run argv (holding the lock descriptors `fds`); output streams to the terminal and the evidence files."""
    out = {s: open(store.path("runs", "%s.%s" % (run_id, s)), "wb") for s in ("stdout", "stderr")}
    try: p = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, pass_fds=fds)
    except OSError as e:
        out["stderr"].write(("cannot execute %s: %s\n" % (argv[0], e)).encode())
        for f in out.values(): f.close()
        return 127
    old = signal.signal(signal.SIGTERM, lambda *_: os.killpg(p.pid, signal.SIGTERM))
    def pump(src, log, sink):
        for chunk in iter(lambda: src.read1(65536), b""):
            log.write(chunk); sink.write(chunk); sink.flush()
    ts = [threading.Thread(target=pump, args=(p.stdout, out["stdout"], sys.stdout.buffer)),
          threading.Thread(target=pump, args=(p.stderr, out["stderr"], sys.stderr.buffer))]
    [t.start() for t in ts]; rc = p.wait(); [t.join() for t in ts]
    signal.signal(signal.SIGTERM, old)
    for f in out.values(): f.flush(); os.fsync(f.fileno()); f.close()
    return 128 - rc if rc < 0 else rc


def smoke_ok(stdout, base):
    """merged_smoke.cjs exits 0 even when an assertion failed: stdout JSON must say ok === true for the URL we passed."""
    text = stdout.decode(errors="replace")
    try: r = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    except (ValueError, AttributeError): return False
    return r.get("ok") is True and r.get("base") == base


def status(gate, key, rc, reason, cand):
    t = rc["tested"] if rc else {}
    return dict(gate=gate, status="fresh" if reason == "hit" else "stale", reason=reason, key=key,
                tested_commit=t.get("commit"), candidate_commit=cand["commit"] if cand else None,
                identical_tree=bool(rc and cand and t.get("tree") == cand["tree"]),
                duration_s=round(rc["run"]["duration_ms"] / 1000, 1) if rc else None,
                log=rc and rc["evidence"]["stdout"])


def snapshot(gate, rest, root):
    """Everything that decides freshness, collected at one moment (and again after every lock wait)."""
    prof, env, material, reasons = prepare(gate, rest, root, os.environ)
    cand = repo_state(root)
    if cand["problems"]: reasons.append("dirty: " + "; ".join(cand["problems"][:3]))
    key = None
    if not reasons:
        material.update(source_tree=cand["tree"], git_object_format=cand["fmt"])
        key = sha(canon(material))
    return dict(prof=prof, env=env, material=material, reasons=reasons, cand=cand, key=key)


def lock_names(s):
    names, d = [], s["prof"].get("dir")
    if s["key"]: names.append(s["key"])
    if d and s["material"] and s["material"]["effective_child_environment"]["knobs"][d] != "auto":
        path = s["material"]["effective_child_environment"]["knobs"][d]
        os.makedirs(path, exist_ok=True)  # the gate clears and reuses it; identify it by device+inode, not spelling
        i = os.stat(path)
        names.append("output-%d-%d" % (i.st_dev, i.st_ino))
    return names


def main(argv):
    if len(argv) < 2 or argv[0] not in ("run", "check"): raise Invalid("usage: gate_receipts.py run|check GATE [-- ARGV...]")
    mode, gate, rest = argv[0], argv[1], argv[2:]
    if rest[:1] == ["--"]: rest = rest[1:]
    root = os.getcwd()
    if os.path.realpath(git(root, "rev-parse", "--show-toplevel").decode().strip()) != os.path.realpath(root):
        raise Invalid("run from the repository root")
    if os.path.realpath(__file__) != os.path.realpath(os.path.join(root, "tools", "gate_receipts.py")):
        raise Invalid("not the candidate's helper: %s" % __file__)
    if mode == "check":
        rest = rest or PROFILES.get(gate, {}).get("argv") or []
        if None in rest: raise Invalid("%s needs its command: gate_check %s -- sha256sum -c PINFILE" % (gate, gate))
    skip_why = "ci" if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") else "forced" if os.environ.get("GATE_FORCE") == "1" else None
    s = snapshot(gate, rest, root)
    st = Store()
    if mode == "check":
        reason = "dirty" if any(r.startswith("dirty") for r in s["reasons"]) else "nonreusable" if s["reasons"] else skip_why
        rc = None
        if reason is None: reason, rc = st.lookup(s["key"])
        print(json.dumps(status(gate, s["key"], rc, reason, s["cand"])))
        return 0 if reason == "hit" else 1
    for _ in range(4):  # take the locks, then re-collect everything: what we waited for may have changed
        names = lock_names(s)
        fds = [st.lock(n) for n in names]
        s2 = snapshot(gate, rest, root)
        if lock_names(s2) == names: s = s2; break
        for fd in fds: os.close(fd)
        s = s2
    else: raise Identity("the candidate or its output directory kept changing while waiting for locks")
    prof, env, material, reasons, cand, key = (s[k] for k in ("prof", "env", "material", "reasons", "cand", "key"))
    if key and not skip_why:
        reason, rc = st.lookup(key)
        if reason == "hit":
            t = status(gate, key, rc, reason, cand)
            print("%s: fresh; tested %s; candidate %s; %s tree; %s s; log %s" % (gate, t["tested_commit"][:8], cand["commit"][:8],
                  "identical" if t["identical_tree"] else "DIFFERENT", t["duration_s"], st.path(t["log"])), file=sys.stderr)
            return 0
    run_id = "%s-%s" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime()), uuid.uuid4().hex[:8])
    keyref = lambda state: canon(dict(schema=SCHEMA, key=key, state=state, run=run_id))
    if key: st.write("keys/%s.json" % key, keyref("running"), True)  # durably supersedes any earlier success
    started, t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), time.monotonic()
    code = execute(rest, env, st, run_id, fds)
    dur = int((time.monotonic() - t0) * 1000)
    if prof.get("json_ok") and code == 0 and not smoke_ok(open(st.path("runs", run_id + ".stdout"), "rb").read(), rest[-1]): code = 1
    reusable = bool(key) and snapshot(gate, rest, root)["key"] == key  # the candidate must not have changed while the gate ran
    inputs = material if key else dict(gate_name=gate, argv=rest, observed={k: os.environ.get(k) for k in prof.get("observe", ())}, reasons=reasons)
    rec = dict(schema=SCHEMA, gate=gate, key=key, tested=dict(commit=cand["commit"], tree=cand["tree"], dirty=bool(cand["problems"]), worktree=root),
               inputs=inputs, run=dict(id=run_id, started_utc=started, finished_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), duration_ms=dur),
               result=dict(complete=True, exit_code=code, reusable=bool(reusable and code == 0)),
               evidence={x: "runs/%s.%s" % (run_id, x) for x in ("stdout", "stderr")})
    for x in ("stdout", "stderr"): rec["evidence"][x + "_sha256"] = sha_file(st.path(rec["evidence"][x]))
    st.write("runs/%s.json" % run_id, json.dumps(rec, indent=1, sort_keys=True).encode(), False)  # logs and receipt durable first
    if key: st.write("keys/%s.json" % key, keyref("done"), True)
    for fd in fds: os.close(fd)
    return code


if __name__ == "__main__":
    a = sys.argv[1:]
    try: sys.exit(main(a))
    except Invalid as e: print("gate_receipts: %s" % e, file=sys.stderr); sys.exit(2)
    except (Identity, OSError, subprocess.TimeoutExpired) as e:
        print("gate_receipts: %s: %s" % ("identity" if isinstance(e, Identity) else "storage/system", e), file=sys.stderr)
        if a[:1] == ["check"]:
            print(json.dumps(dict(gate=a[1] if len(a) > 1 else None, status="stale", reason="error", key=None)))
        sys.exit(2 if a[:1] == ["check"] else 125)
