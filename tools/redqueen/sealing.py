#!/usr/bin/env python3
"""sealing.py: the simplified commitment and evaluation order (design v4 §7.1-7.2, (d) item 4).
One split manifest, role-based evaluation filters, plain prediction hashes and a public freeze
record. There is no access-control service, no sealed directory tree and no unlock manager.

    sealing.py manifest --graph-meta graph.meta.json [--worlds config/worlds.json] --out config/splits.json
    sealing.py check    --manifest config/splits.json --records RECORDS.jsonl
    sealing.py filter   --manifest config/splits.json --records RECORDS.jsonl --stage fit|validation|test|audit|diagnostic --out OUT.jsonl
    sealing.py commit   --study STUDY --stage validation|test --predictions PRED.jsonl [--eval-script FILE]
    sealing.py freeze   --study STUDY --preregistration FILE --eval-script FILE (--osf-url URL | --doi DOI) [--registered-utc T]
    sealing.py verify-test --study STUDY --predictions PRED.jsonl --eval-script FILE

THE SPLIT MANIFEST (config/splits.json, schema finfolk.redqueen.splits/1; deterministic, never
replaced by other bytes). Built from graph.py's meta (its sha256 and edges hash recorded): every
world's split (C 20/6/6, A and B 5/1/2 each: training / validation / test), the training C worlds'
snapshot holdouts (t in M steps -> validation | test; 400 joint states), the fork and intensive
sets. A snapshot's role is its world's split, or its holdout role in a training world (node_role).
An EDGE inherits its most held-out endpoint, test before validation before training (edge_role);
support, audit and diagnostic are declared roles, never computed (support is permitted calibration
information, audit is scoring-only, diagnostic outside the evaluation). Descendants, technical
segments and forks keep their root world's split (a record names its root world).

FILTERS (check, filter). A record (a plan row, a completion, a prediction target) carries "role",
"prey" {"world", "frame"} and "predators" {"world", "frame"} or null (frame 1 = F1, else frame / 1M
= t). check recomputes every computed role and refuses a disagreement. filter keeps what a stage
may use: fit -> training + support outcomes (never validation, test or audit); validation ->
validation targets; test -> test targets; audit -> audit (scoring only); diagnostic -> diagnostic.

COMMITMENTS (commit). The predictions of a stage are one JSONL file of objects with a unique
"target_id"; its plain SHA-256 is the commitment: STUDY/registration/VAL_PRED_SHA, then
TEST_PRED_SHA (one hex digest, newline) with a record (registration/<stage>_predictions.json:
bytes, targets, target-id hash, the evaluation script's sha256 for test, UTC). A commitment is
never replaced by other bytes; test requires the validation commitment first and the frozen
evaluation script.

THE PUBLIC FREEZE (freeze; registration/freeze.json, schema finfolk.redqueen.freeze/1). After
TEST_PRED_SHA: the public registration's OSF URL (https://osf.io/<id>) and/or DOI (10.<registrant>/
<suffix>), its registration time, and the sha256 of the preregistration, the frozen evaluation
script, the split manifest, VAL_PRED_SHA and TEST_PRED_SHA. The deposit itself is made by hand on
OSF (the record names it; a local hash alone is not a public timestamp). verify-test, run before any
test scoring, refuses unless the freeze record is complete and names a public registration, the
predictions are the committed bytes, and the evaluation script and split manifest are the frozen ones.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

SPLITS_SCHEMA = "finfolk.redqueen.splits/1"
FREEZE_SCHEMA = "finfolk.redqueen.freeze/1"
COMMIT_SCHEMA = "finfolk.redqueen.predcommit/1"
ROLES = ("training", "validation", "test", "support", "audit", "diagnostic")
COMPUTED = ("training", "validation", "test")
DECLARED = ("support", "audit", "diagnostic")
RANK = {"training": 0, "validation": 1, "test": 2}
SPLIT = {"train": "training", "val": "validation", "test": "test",
         "training": "training", "validation": "validation"}
STAGES = {"fit": ("training", "support"), "validation": ("validation",), "test": ("test",),
          "audit": ("audit",), "diagnostic": ("diagnostic",)}
UNIT = 1_000_000
OSF_URL = re.compile(r"^https://osf\.io/[a-z0-9]{5,}/?$")
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
SHA = re.compile(r"^[0-9a-f]{64}$")


class SealError(Exception):
    pass


# ================================================================== the split manifest
def manifest(meta_path, worlds_path=None):
    m = rqlib.read_json(meta_path)
    worlds = {w: SPLIT[s] for w, s in sorted(m["split"].items())}
    hold = {}
    for key, s in sorted(m.get("holdout", {}).items()):
        w, _, t = key.rpartition(":")
        if worlds.get(w) != "training":
            raise SealError(f"holdout {key}: {w} is not a training world")
        hold.setdefault(w, {})[str(int(t))] = SPLIT[s]
    out = {"schema": SPLITS_SCHEMA, "time_unit": UNIT, "precedence": ["test", "validation", "training"],
           "graph": {"path": os.path.abspath(meta_path), "sha256": rqlib.sha256_file(meta_path),
                     "namespace": m.get("namespace"), "edges_sha256": m.get("edges_sha256")},
           "worlds": worlds, "snapshot_holdouts": hold, "fork": sorted(m.get("fork", [])),
           "intensive": sorted(m.get("intensive", []))}
    if worlds_path:
        reg = rqlib.read_json(worlds_path)
        ids = {w["id"] for w in reg["worlds"]}
        if ids != set(worlds):
            raise SealError(f"the graph's worlds are not the registry's ({sorted(ids ^ set(worlds))[:5]})")
        out["worlds_registry"] = {"path": os.path.abspath(worlds_path), "sha256": rqlib.sha256_file(worlds_path)}
    return out


def load_manifest(path):
    m = rqlib.read_json(path)
    if m.get("schema") != SPLITS_SCHEMA:
        raise SealError(f"{path}: schema {m.get('schema')!r}")
    return m


def t_of(frame):
    """A snapshot's time index from its frame: F1 (frame 1) is 0, else frame / 1M."""
    frame = int(frame)
    if frame == 1:
        return 0
    if frame <= 0 or frame % UNIT:
        raise SealError(f"frame {frame} is not a snapshot time (F1 or a multiple of {UNIT})")
    return frame // UNIT


def node_role(m, world, frame):
    if world not in m["worlds"]:
        raise SealError(f"world {world} is not in the split manifest")
    split = m["worlds"][world]
    if split == "training":
        return m["snapshot_holdouts"].get(world, {}).get(str(t_of(frame)), "training")
    return split


def edge_role(m, prey, predators):
    """The most held-out endpoint's role (test before validation before training)."""
    roles = [node_role(m, prey["world"], prey["frame"])]
    if predators:
        roles.append(node_role(m, predators["world"], predators["frame"]))
    return max(roles, key=RANK.__getitem__)


def record_problems(m, rows):
    """Why records disagree with the manifest: an unknown role, or a computed role that is not the
    edge's (a declared role, support / audit / diagnostic, is kept as declared)."""
    probs = []
    for k, r in enumerate(rows):
        rid = r.get("id") or r.get("target_id") or f"record {k + 1}"
        role = r.get("role")
        if role not in ROLES:
            probs.append(f"{rid}: role {role!r}")
            continue
        if role in DECLARED:
            continue
        try:
            want = edge_role(m, r["prey"], r.get("predators"))
        except (SealError, KeyError, TypeError, ValueError) as e:
            probs.append(f"{rid}: {e}")
            continue
        if want != role:
            probs.append(f"{rid}: role {role}, but its most held-out endpoint makes it {want}")
    return probs


def stage_filter(m, rows, stage):
    """The records a stage may use (after a full check: any disagreement refuses the whole set)."""
    if stage not in STAGES:
        raise SealError(f"stage {stage!r}: one of {sorted(STAGES)}")
    probs = record_problems(m, rows)
    if probs:
        raise SealError(f"{len(probs)} records disagree with the split manifest: " + "; ".join(probs[:5]))
    return [r for r in rows if r["role"] in STAGES[stage]]


# ================================================================== commitments
def reg_dir(study):
    return os.path.join(study, "registration")


def _jsonl(path):
    rows = []
    for k, ln in enumerate(rqlib.read_text(path).split("\n"), 1):
        if ln.strip():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                raise SealError(f"{path}: line {k} is not JSON")
    return rows


def commit(study, stage, pred_path, eval_script=None):
    """Record a stage's plain prediction hash (VAL_PRED_SHA / TEST_PRED_SHA) -> its record."""
    if stage not in ("validation", "test"):
        raise SealError(f"stage {stage!r}: validation or test")
    rows = _jsonl(pred_path)
    ids = [r.get("target_id") for r in rows if isinstance(r, dict)]
    if len(ids) != len(rows) or not rows or any(not isinstance(i, str) or not i for i in ids):
        raise SealError(f"{pred_path}: every line is an object with a target_id")
    if len(set(ids)) != len(ids):
        raise SealError(f"{pred_path}: a target_id occurs twice")
    d = reg_dir(study)
    name = "VAL_PRED_SHA" if stage == "validation" else "TEST_PRED_SHA"
    sha = rqlib.sha256_file(pred_path)
    rec = {"schema": COMMIT_SCHEMA, "stage": stage, "name": name, "sha256": sha,
           "file": os.path.abspath(pred_path), "bytes": os.path.getsize(pred_path), "targets": len(ids),
           "target_ids_sha256": rqlib.canonical_sha(sorted(ids)), "utc": rqlib.now_utc()}
    if stage == "test":
        if not os.path.isfile(os.path.join(d, "VAL_PRED_SHA")):
            raise SealError("the test predictions are committed after the validation predictions (VAL_PRED_SHA)")
        if not eval_script:
            raise SealError("the test commitment names the frozen evaluation script (--eval-script)")
        rec["evaluation_script_sha256"] = rqlib.sha256_file(eval_script)
        rec["VAL_PRED_SHA"] = rqlib.read_text(os.path.join(d, "VAL_PRED_SHA")).split()[0]
    p = os.path.join(d, name)
    if os.path.isfile(p):
        have = rqlib.read_text(p).split()[0]
        if have != sha:
            raise SealError(f"{name} is already committed ({have[:12]}); a commitment is never replaced")
        return rqlib.read_json(os.path.join(d, f"{stage}_predictions.json"))
    os.makedirs(d, exist_ok=True)
    rqlib.write_json_durable(os.path.join(d, f"{stage}_predictions.json"), rec)
    rqlib.write_durable(p, sha + "\n")
    return rec


def freeze(study, preregistration, eval_script, osf_url=None, doi=None, registered_utc=None):
    """The public freeze record (after TEST_PRED_SHA) -> its record (written once; never replaced)."""
    if not osf_url and not doi:
        raise SealError("the freeze record names the public registration: --osf-url and/or --doi")
    if osf_url and not OSF_URL.match(osf_url):
        raise SealError(f"--osf-url {osf_url!r}: expected https://osf.io/<id>")
    if doi and not DOI.match(doi):
        raise SealError(f"--doi {doi!r}: expected 10.<registrant>/<suffix>")
    d = reg_dir(study)
    shas = {}
    for name in ("VAL_PRED_SHA", "TEST_PRED_SHA"):
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            raise SealError(f"{name} is not committed yet: the freeze follows both prediction commitments")
        shas[name] = rqlib.read_text(p).split()[0]
    test = rqlib.read_json(os.path.join(d, "test_predictions.json"))
    es = rqlib.sha256_file(eval_script)
    if es != test["evaluation_script_sha256"]:
        raise SealError("the evaluation script differs from the one the test commitment named")
    mp = os.path.join(study, "config", "splits.json")
    rec = {"schema": FREEZE_SCHEMA, "osf": {"url": osf_url, "doi": doi, "registered_utc": registered_utc},
           "preregistration_sha256": rqlib.sha256_file(preregistration), "evaluation_script_sha256": es,
           "split_manifest_sha256": rqlib.sha256_file(mp) if os.path.isfile(mp) else None,
           "VAL_PRED_SHA": shas["VAL_PRED_SHA"], "TEST_PRED_SHA": shas["TEST_PRED_SHA"], "utc": rqlib.now_utc()}
    p = os.path.join(d, "freeze.json")
    if os.path.isfile(p):
        have = rqlib.read_json(p)
        if {k: v for k, v in have.items() if k != "utc"} != {k: v for k, v in rec.items() if k != "utc"}:
            raise SealError(f"{p} exists with other contents: a freeze record is never replaced")
        return have
    rqlib.write_json_durable(p, rec)
    return rec


def test_problems(study, pred_path, eval_script):
    """Why test scoring may not start (empty: it may): the public freeze record, the committed test
    predictions, the frozen evaluation script and split manifest."""
    d = reg_dir(study)
    p = os.path.join(d, "freeze.json")
    if not os.path.isfile(p):
        return ["no public freeze record (sealing.py freeze, after the OSF deposit)"]
    f = rqlib.read_json(p)
    probs = []
    if f.get("schema") != FREEZE_SCHEMA:
        probs.append(f"freeze.json: schema {f.get('schema')!r}")
    o = f.get("osf") or {}
    if not ((o.get("url") and OSF_URL.match(o["url"])) or (o.get("doi") and DOI.match(o["doi"]))):
        probs.append("the freeze record names no public registration (OSF URL or DOI)")
    for k in ("preregistration_sha256", "evaluation_script_sha256", "VAL_PRED_SHA", "TEST_PRED_SHA"):
        if not SHA.match(str(f.get(k) or "")):
            probs.append(f"the freeze record lacks {k}")
    for name in ("VAL_PRED_SHA", "TEST_PRED_SHA"):
        q = os.path.join(d, name)
        if not os.path.isfile(q) or rqlib.read_text(q).split()[0] != f.get(name):
            probs.append(f"{name} differs from the freeze record")
    if rqlib.sha256_file(pred_path) != f.get("TEST_PRED_SHA"):
        probs.append(f"{pred_path} is not the committed test predictions")
    if rqlib.sha256_file(eval_script) != f.get("evaluation_script_sha256"):
        probs.append(f"{eval_script} is not the frozen evaluation script")
    mp = os.path.join(study, "config", "splits.json")
    if f.get("split_manifest_sha256") and (not os.path.isfile(mp) or rqlib.sha256_file(mp) != f["split_manifest_sha256"]):
        probs.append("config/splits.json is not the frozen split manifest")
    return probs


def require_test_freeze(study, pred_path, eval_script):
    """The gate a test-scoring script calls first."""
    probs = test_problems(study, pred_path, eval_script)
    if probs:
        raise SealError("test evaluation refused: " + "; ".join(probs))


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("manifest")
    s.add_argument("--graph-meta", required=True)
    s.add_argument("--worlds")
    s.add_argument("--out", required=True)
    for name in ("check", "filter"):
        s = sub.add_parser(name)
        s.add_argument("--manifest", required=True)
        s.add_argument("--records", required=True)
        if name == "filter":
            s.add_argument("--stage", required=True, choices=sorted(STAGES))
            s.add_argument("--out", required=True)
    s = sub.add_parser("commit")
    s.add_argument("--study", required=True)
    s.add_argument("--stage", required=True, choices=("validation", "test"))
    s.add_argument("--predictions", required=True)
    s.add_argument("--eval-script")
    s = sub.add_parser("freeze")
    s.add_argument("--study", required=True)
    s.add_argument("--preregistration", required=True)
    s.add_argument("--eval-script", required=True)
    s.add_argument("--osf-url")
    s.add_argument("--doi")
    s.add_argument("--registered-utc")
    s = sub.add_parser("verify-test")
    s.add_argument("--study", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--eval-script", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "manifest":
            data = rqlib.canonical(manifest(a.graph_meta, a.worlds))
            if os.path.exists(a.out) and rqlib.read_bytes(a.out) != data:
                raise SealError(f"{a.out} exists with other bytes: the split manifest is never replaced")
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            rqlib.write_durable(a.out, data)
            print(f"split manifest {a.out}: sha256 {rqlib.sha256_bytes(data)}", file=sys.stderr)
            return 0
        if a.cmd in ("check", "filter"):
            m = load_manifest(a.manifest)
            rows = _jsonl(a.records)
            if a.cmd == "check":
                probs = record_problems(m, rows)
                for p in probs[:20]:
                    print(p, file=sys.stderr)
                print(f"{len(rows)} records, {len(probs)} disagreements", file=sys.stderr)
                return 2 if probs else 0
            keep = stage_filter(m, rows, a.stage)
            rqlib.write_durable(a.out, b"".join(rqlib.canonical(r) for r in keep))
            print(f"{a.stage}: {len(keep)} of {len(rows)} records", file=sys.stderr)
            return 0
        study = os.path.abspath(a.study)
        if a.cmd == "commit":
            rec = commit(study, a.stage, a.predictions, a.eval_script)
            print(f"{rec['name']} = {rec['sha256']} ({rec['targets']} targets)")
            return 0
        if a.cmd == "freeze":
            rec = freeze(study, a.preregistration, a.eval_script, a.osf_url, a.doi, a.registered_utc)
            print(f"freeze record {os.path.join(reg_dir(study), 'freeze.json')}: sha256 "
                  f"{rqlib.sha256_file(os.path.join(reg_dir(study), 'freeze.json'))} (OSF {rec['osf']})")
            return 0
        probs = test_problems(study, a.predictions, a.eval_script)
        for p in probs:
            print(f"REFUSED: {p}", file=sys.stderr)
        if not probs:
            print("test evaluation may start: the freeze record, predictions, script and manifest verify")
        return 2 if probs else 0
    except (SealError, OSError, KeyError, ValueError) as e:
        print(f"sealing.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
