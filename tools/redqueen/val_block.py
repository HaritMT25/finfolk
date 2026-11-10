#!/usr/bin/env python3
"""val_block.py: the worlds block (finfolk.redqueen.worldsblock/1, as worlds.py design-block writes it)
of the floor-free validation run, which runs under ~/finfolk/validation/runner_val.py with its own
layout rather than worlds.py's: the validation-layout adapter that refsel.py (reference selection) and
noisebank.py plans read (their "val_block" identity of a restarted attempt is this module's recipe).
Read-only; stdlib only. (Extracted from #69, whose allocation pilot was withdrawn by Annex H AMENDMENT D7
rule 39.)

THE LAYOUT (runner_val.py): config/worlds.json (a worlds.py registry: id, uuid, treatment, block);
worlds/<id>/state.json {"attempt": k}; the current attempt's directory worlds/<id>/a<k>/ holds every
periodic checkpoint end.<frame>.json, each segment's command line segNNN.cmd (a resumed segment's has
--load-checkpoint end.<frame>.json: the frame it resumed from; a fresh one has none) and its main CSV
runs/segNNN.csv (every --log-every frames), and a marker done / extinct / failed when it has ended. (A
restarted attempt's files stay in a<k-1>/; an attempt started over for want of a checkpoint is moved to
a<k>.restart<time>.)

THE OBSERVATION CHAIN (Annex H D6 rule 24; Codex #74 r1 P2-1/2). From the last segment back, each
segment covers its main-CSV rows from its own start frame up to the frame the next chain segment
resumed from (a segment wholly superseded by a later resume from an earlier checkpoint is skipped),
back to a fresh segment (frame 0). Its rows are evidence only as COMPLETE records (an unterminated
trailing record is discarded before parsing, whatever its width), each of the header's width with
integral counts, in exactly the --log-every sequence from the segment's start: superseded tails are
not evidence. The chain's observations end (observed_through) at the first gap: a missing runs/ or
main CSV, a damaged or out-of-sequence row inside a segment's covered span, rows that stop before the
frame the next segment resumed from, or a chain that does not reach a fresh segment. Every such gap
is listed in "technical"; what lies past it is TECHNICALLY UNAVAILABLE, never "no zero". The rules are
evidence.py's (the one implementation worlds.py's ecology export shares): also, the first sampled zero of
either guild ends the observations (later overshoot rows never resolve the other guild), and a predator
refill (predator_reseeds_cum above the founders' 0) ends them at the sample before it (a protocol-
integrity event, listed in "technical").

THE BLOCK, per world (the current attempt only):
  uuid       the registry's for attempt 0; for attempt k > 0 a distinct one, uuid5(NAMESPACE_URL,
             "finfolk:attempt:<registry uuid>:<k>") (another history, so other snapshot identities);
  pattern    <abs a<k>>/end.{frame}.json;
  archived   the frames f (multiples of 1M up to 200M, f <= observed_through) whose end.<f>.json exists
             and parses with world.frame == f (every listed checkpoint is opened), and frame 1 when the
             attempt's founding snapshot F1.json (runner_val's one-step replay) parses with
             world.frame == 1; a valid checkpoint past observed_through is listed in "unobserved"
             instead (its history is not evidenced);
  paths      {"F1": <abs a<k>/F1.json>} when it is archived (the F1 label's path override; refsel.py);
  valid_before  the FIRST sampled zero of either guild over the observation chain, or None (no zero
             through observed_through): a snapshot at or after it is not valid (design §2.3; the
             burn-in rule restarted any world whose zero came before 5M, so a zero here is data);
  observed_through, technical, chain (each chain segment's start, covered frames and main-CSV prefix
             sha256), treatment, block, status (done / extinct / failed / running), attempt.
times: "F1" -> 1 and "<t>M" -> t x 1,000,000 for t = 1..200.

    val_block.py --root ~/finfolk/validation --out block.json [--log-every 5000]
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
import evidence  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.worldsblock/1"
MAX_M = 200
LOG_EVERY = 5000                       # (runner_val.py's --log-every)
CK_RE = re.compile(r"^end\.(\d+)\.json$")
CMD_RE = re.compile(r"^seg(\d{3})\.cmd$")
LOAD_RE = re.compile(r"--load-checkpoint\s+end\.(\d+)\.json(\s|$)")


class BlockError(Exception):
    pass


def _segments(adir):
    """[(index, start frame)] of the attempt's segments from their command lines (a fresh one starts at 0)."""
    out = []
    for name in sorted(os.listdir(adir)):
        m = CMD_RE.match(name)
        if not m:
            continue
        with open(os.path.join(adir, name)) as fh:
            lm = LOAD_RE.search(fh.read())
        out.append((int(m.group(1)), int(lm.group(1)) if lm else 0))
    return out


def observations(adir, log_every=LOG_EVERY):
    """The attempt's observation chain (see THE OBSERVATION CHAIN; the rules are evidence.py's, shared with
    worlds.py's ecology export) -> (first zero frame or None, observed_through, technical problems, chain
    evidence)."""
    segs = _segments(adir)
    if not segs:
        return None, 0, ["no segment command lines (segNNN.cmd)"], []
    chain, prob = evidence.chain_cuts([(f"seg{k:03d}", s) for k, s in segs], 0)
    if prob:
        return None, 0, [prob], []
    tech, ev, samples = [], [], []
    for name, s, upto in chain:
        p = os.path.join(adir, "runs", f"{name}.csv")
        if not os.path.isfile(p):
            tech.append(f"{name}: no main CSV (runs/{name}.csv)")
            break
        raw = rqlib.read_bytes(p)
        try:
            rows, why = evidence.segment_rows(raw, s, log_every, upto, cols=(evidence.REFILL_COL,))
        except evidence.EvidenceError as e:
            raise BlockError(f"{p}: {e}")
        ev.append({"segment": name, "start_frame": s, "until": upto, "rows": len(rows),
                   "through": rows[-1][0] if rows else s, "csv_sha256": rqlib.sha256_bytes(evidence.complete(raw))})
        samples += rows
        if why:
            tech.append(f"{name}: {why}")
            break
    obs = evidence.terminal(samples)                    # (the first absorbing terminal; refills vs the founders' 0)
    if obs["refill"]:
        r = obs["refill"]
        tech.append(f"an unreadable predator refill counter at frame {r['frame']}: the integrity check cannot be made"
                    if r.get("unreadable") else
                    f"a predator refill at frame {r['frame']} (predator_reseeds_cum {r['value']} > {r['baseline']}): "
                    "a protocol-integrity event; nothing after it is evidence of natural coexistence")
    zero = obs["first_terminal"]["frame"] if obs["first_terminal"] else None
    return zero, obs["frontier"], tech, ev


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


def block(root, log_every=LOG_EVERY):
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
        zero, through, tech, chain = observations(adir, log_every)
        ck = archived(adir)
        ws[w["id"]] = {"uuid": attempt_uuid(w["uuid"], k), "treatment": w["treatment"], "block": w["block"],
                       "status": status, "attempt": k, "pattern": os.path.join(adir, "end.{frame}.json"), "paths": paths,
                       "valid_before": zero, "observed_through": through, "technical": tech, "chain": chain,
                       "archived": ([1] if paths else []) + [f for f in ck if f <= through],
                       "unobserved": [f for f in ck if f > through]}
    return {"schema": SCHEMA, "registry_sha256": rqlib.sha256_file(rp), "source": "runner_val", "root": root,
            "log_every": log_every,
            "times": dict({"F1": 1}, **{f"{t}M": t * 1_000_000 for t in range(1, MAX_M + 1)}), "worlds": ws}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log-every", type=int, default=LOG_EVERY, help="the runner's main-CSV interval (5000)")
    a = ap.parse_args(argv)
    try:
        b = block(a.root, a.log_every)
    except BlockError as e:
        print(f"val_block.py: {e}", file=sys.stderr)
        return 2
    rqlib.write_json_durable(a.out, b)
    for w, v in sorted(b["worlds"].items()):
        print(f"{w} {v['treatment']} a{v['attempt']} {v['status']}: {len(v['archived'])} checkpoints, "
              f"valid before {v['valid_before']}, observed through {v['observed_through']}"
              + (f"; TECHNICAL: {'; '.join(v['technical'])}" if v["technical"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
