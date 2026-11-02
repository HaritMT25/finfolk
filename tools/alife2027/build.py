#!/usr/bin/env python3
"""build.py: build the experiment executable and its build manifest.

    python3 tools/alife2027/build.py OUTDIR [--protocol experiments/alife2027/v2/protocol.json]

Run from the repository root. Compiles tools/ocean_eye_exp.cpp with the
protocol's flags and defines (single-threaded, no OpenMP), then writes
OUTDIR/ocean_eye_exp and OUTDIR/build_manifest.json:

  git commit / tree / dirty paths; the source inventory (every engine header,
  the driver and its support header, the fingerprint header, the analysis
  tools and the frozen inputs) with each file's SHA-256 and an inventory hash
  over the sorted (path, hash) list; the compiler's path, SHA-256, version
  and target; the complete argv; the executable's SHA-256 (computed after
  compilation, never embedded in itself) and its --capabilities (NUM_SENSES,
  label frame support, format numbers). Refuses to build from a tree whose
  inventoried files differ from HEAD unless --allow-dirty is given (the
  manifest then lists them).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

INVENTORY_DIRS = ["src", "experiments/alife2027", "tools/alife2027"]
INVENTORY_FILES = ["tools/ocean_eye_exp.cpp", "tools/ocean_eye_exp_support.hpp", "tools/ocean_fingerprint.hpp"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def inventory():
    files = []
    for d in INVENTORY_DIRS:
        for root, _dirs, names in os.walk(d):
            if "__pycache__" in root:
                continue
            for n in names:
                if n.endswith((".pyc",)):
                    continue
                files.append(os.path.join(root, n))
    files += INVENTORY_FILES
    files = sorted(set(p.replace(os.sep, "/") for p in files))
    entries = [{"path": p, "sha256": sha256(p)} for p in files]
    h = hashlib.sha256()
    for e in entries:   # unambiguous framing: path, NUL, hash, newline
        h.update(e["path"].encode() + b"\0" + e["sha256"].encode() + b"\n")
    return entries, h.hexdigest()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out = sys.argv[1]
    ppath = "experiments/alife2027/v2/protocol.json"
    if "--protocol" in sys.argv:
        ppath = sys.argv[sys.argv.index("--protocol") + 1]
    proto = json.load(open(ppath))
    os.makedirs(out, exist_ok=True)
    entries, inv_hash = inventory()
    dirty = [ln[3:] for ln in git("status", "--porcelain", "--", *INVENTORY_DIRS, *INVENTORY_FILES).splitlines() if ln]
    if dirty and "--allow-dirty" not in sys.argv:
        print("refusing to build: inventoried files differ from HEAD:\n  " + "\n  ".join(dirty), file=sys.stderr)
        return 3
    cxx = shutil.which(os.environ.get("CXX", "g++"))
    flags = list(proto["build"]["flags"]) + ["-D" + d for d in proto["build"]["required_defines"]]
    exe = os.path.join(out, "ocean_eye_exp")
    argv = [cxx, *flags, "-I", "src", "tools/ocean_eye_exp.cpp", "-o", exe]
    subprocess.run(argv, check=True)
    caps = json.loads(subprocess.run([exe, "--capabilities"], capture_output=True, text=True, check=True).stdout)
    if caps["NUM_SENSES"] != proto["build"]["required_num_senses"]:
        print(f"NUM_SENSES {caps['NUM_SENSES']} != {proto['build']['required_num_senses']}", file=sys.stderr)
        return 4
    real_cxx = os.path.realpath(cxx)
    manifest = {
        "schema": "finfolk.alife2027.build/1",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                "branch": git("rev-parse", "--abbrev-ref", "HEAD"), "dirty_inventoried_paths": dirty},
        "source_inventory": {"hash": inv_hash, "framing": "sha256 over sorted 'path\\0sha256\\n'", "files": entries},
        "compiler": {"path": cxx, "realpath": real_cxx, "sha256": sha256(real_cxx),
                     "version": subprocess.run([cxx, "--version"], capture_output=True, text=True).stdout.splitlines()[0],
                     "target": subprocess.run([cxx, "-dumpmachine"], capture_output=True, text=True).stdout.strip()},
        "argv": argv,
        "flags": flags,
        "executable": {"path": "ocean_eye_exp", "sha256": sha256(exe)},
        "capabilities": caps,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                     "python": platform.python_version()},
        "protocol": {"path": ppath, "sha256": sha256(ppath)},
    }
    tmp = os.path.join(out, "build_manifest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, os.path.join(out, "build_manifest.json"))
    print(f"built {exe} sha256 {manifest['executable']['sha256'][:16]}..., inventory {inv_hash[:16]}..., "
          f"NUM_SENSES {caps['NUM_SENSES']}, label_frame {caps['label_frame']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
