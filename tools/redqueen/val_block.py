#!/usr/bin/env python3
"""val_block.py: the worlds block (finfolk.redqueen.worldsblock/1, as worlds.py design-block writes it)
of the floor-free validation run, which runs under ~/finfolk/validation/runner_val.py with its own
layout rather than worlds.py's: the validation-layout adapter that refsel.py (reference selection) and
noisebank.py plans read (their "val_block" identity of a restarted attempt is this module's recipe).
Read-only; stdlib only. (Extracted from #69, whose allocation pilot was withdrawn by Annex H AMENDMENT D7
rule 39.)

THE LAYOUT (runner_val.py): config/worlds.json (a worlds.py registry: id, uuid, treatment, block);
worlds/<id>/state.json {"attempt": k}; the current attempt's directory worlds/<id>/a<k>/ holds every
periodic checkpoint end.<frame>.json, the main CSVs runs/segNNN.csv, and a marker done / extinct /
failed when it has ended. (A restarted attempt's files stay in a<k-1>/.)

THE BLOCK, per world (the current attempt only):
  uuid       the registry's for attempt 0; for attempt k > 0 a distinct one, uuid5(NAMESPACE_URL,
             "finfolk:attempt:<registry uuid>:<k>") (another history, so other snapshot identities);
  pattern    <abs a<k>>/end.{frame}.json;
  archived   the frames f (multiples of 1M up to 200M) whose end.<f>.json exists and parses with
             world.frame == f (every listed checkpoint is opened), and frame 1 when the attempt's founding
             snapshot F1.json (runner_val's one-step replay) parses with world.frame == 1;
  paths      {"F1": <abs a<k>/F1.json>} when it is archived (the F1 label's path override; refsel.py);
  valid_before  the FIRST main-CSV row (any segment of the attempt) at which either guild is 0, or None:
             a snapshot at or after it is not valid (design §2.3; the burn-in rule restarted any world
             whose zero came before 5M, so a zero here is data);
  treatment, block, status (done / extinct / failed / running), attempt.
times: "F1" -> 1 and "<t>M" -> t x 1,000,000 for t = 1..200.

    val_block.py --root ~/finfolk/validation --out block.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.worldsblock/1"
MAX_M = 200
CK_RE = re.compile(r"^end\.(\d+)\.json$")
SEG_RE = re.compile(r"^seg(\d{3})\.csv$")


class BlockError(Exception):
    pass


def first_zero(adir):
    """The first main-CSV frame (over the attempt's segments) at which either guild is 0, or None."""
    runs = os.path.join(adir, "runs")
    best = None
    if not os.path.isdir(runs):
        return None
    for name in sorted(os.listdir(runs)):
        if not SEG_RE.match(name):
            continue
        with open(os.path.join(runs, name)) as fh:
            head = fh.readline().strip().split(",")
            if "population" not in head or "predator_pop" not in head:
                raise BlockError(f"{name}: no population / predator_pop columns")
            ip, iq = head.index("population"), head.index("predator_pop")
            for ln in fh:
                p = ln.strip().split(",")
                if len(p) != len(head) or not p[0].isdigit():
                    continue                              # (a torn last line)
                if int(p[ip]) == 0 or int(p[iq]) == 0:
                    f = int(p[0])
                    best = f if best is None else min(best, f)
                    break
    return best


def archived(adir):
    out = []
    for name in os.listdir(adir):
        m = CK_RE.match(name)
        if not m:
            continue
        f = int(m.group(1))
        if f % 1_000_000 or f > MAX_M * 1_000_000:
            continue
        try:
            with open(os.path.join(adir, name)) as fh:
                ok = json.load(fh).get("world", {}).get("frame") == f
        except (OSError, ValueError):
            ok = False
        if ok:
            out.append(f)
    return sorted(out)


def founding(adir):
    """{"F1": path} when a<k>/F1.json parses with world.frame == 1, else {}."""
    p = os.path.join(adir, "F1.json")
    try:
        with open(p) as fh:
            ok = json.load(fh).get("world", {}).get("frame") == 1
    except (OSError, ValueError):
        ok = False
    return {"F1": p} if ok else {}


def attempt_uuid(base, k):
    return base if k == 0 else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


def block(root):
    root = os.path.abspath(root)
    rp = os.path.join(root, "config", "worlds.json")
    reg = rqlib.read_json(rp)
    ws = {}
    for w in reg["worlds"]:
        base = os.path.join(root, "worlds", w["id"])
        st = os.path.join(base, "state.json")
        k = int(rqlib.read_json(st)["attempt"]) if os.path.isfile(st) else 0
        adir = os.path.join(base, f"a{k}")
        if not os.path.isdir(adir):
            raise BlockError(f"{w['id']}: no directory for its attempt {k}")
        status = next((m for m in ("done", "extinct", "failed") if os.path.exists(os.path.join(adir, m))), "running")
        paths = founding(adir)
        ws[w["id"]] = {"uuid": attempt_uuid(w["uuid"], k), "treatment": w["treatment"], "block": w["block"],
                       "status": status, "attempt": k, "pattern": os.path.join(adir, "end.{frame}.json"), "paths": paths,
                       "valid_before": first_zero(adir), "archived": ([1] if paths else []) + archived(adir)}
    return {"schema": SCHEMA, "registry_sha256": rqlib.sha256_file(rp), "source": "runner_val", "root": root,
            "times": dict({"F1": 1}, **{f"{t}M": t * 1_000_000 for t in range(1, MAX_M + 1)}), "worlds": ws}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        b = block(a.root)
    except BlockError as e:
        print(f"val_block.py: {e}", file=sys.stderr)
        return 2
    rqlib.write_json_durable(a.out, b)
    for w, v in sorted(b["worlds"].items()):
        print(f"{w} {v['treatment']} a{v['attempt']} {v['status']}: {len(v['archived'])} checkpoints, "
              f"valid before {v['valid_before']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
