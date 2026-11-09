#!/usr/bin/env python3
"""sealing.py: the simplified commitment and evaluation order (design v4 §7.1-7.2, (d) item 4).
One split manifest, role-based evaluation filters, plain prediction hashes and a public freeze
record. There is no access-control service, no sealed directory tree and no unlock manager.

    sealing.py manifest --graph-meta graph.meta.json --worlds config/worlds.json [--forks config/forks.json]
                        [--references config/references.json] --out STUDY/config/splits.json
    sealing.py check    --manifest config/splits.json --records RECORDS.jsonl
    sealing.py filter   --manifest config/splits.json --records RECORDS.jsonl
                        --stage fit|nuisance|validation|test|audit|diagnostic --out OUT.jsonl
    sealing.py commit   --study STUDY --stage validation|test --predictions PRED.jsonl [--eval-script FILE]
    sealing.py open-validation --study STUDY --scores VALIDATION_SCORES.json
    sealing.py freeze   --study STUDY --preregistration FILE --eval-script FILE (--osf-url URL | --doi DOI)
                        --registered-utc YYYY-MM-DDTHH:MM:SSZ
    sealing.py verify-test --study STUDY --predictions PRED.jsonl --eval-script FILE

THE SPLIT MANIFEST (config/splits.json, schema finfolk.redqueen.splits/2; deterministic, published
once, never replaced). Built from graph.py's graph (its meta and edges: their sha256), the histories'
registry (every world's UUID: endpoints are bound to it) and, when given, the fork registry (every
branch's root world and UUID). It holds every world's split (C 20/6/6, A and B 5/1/2: training /
validation / test), the training C worlds' snapshot holdouts (t in M -> validation | test), the fork
and intensive sets, the REGISTERED SUPPORT EXCEPTIONS: the graph's support pairs (endpoint keys
"Q:<world>:<t>", "P:<world>:<t>", references "RQ:<k>" / "RP:<k>"), and the REGISTERED REFERENCE
ASSIGNMENT (config/references.json, finfolk.redqueen.references/1: the SENTINEL namespace and the eight
prey and eight predator references selected, slot -> {"world" (a sentinel world id), "frame", "uuid" =
uuid5(URL, "finfolk:redqueen:<sentinel namespace>:<world>"), "snapshot" = the snapshot UUID recipe of
that uuid and frame, "archive", "sha256"}); the sentinel namespace differs from the main registry's,
and no reference's uuid or snapshot UUID may be any study identity: a main world's, a fork branch's or
its root's, at any snapshot frame (all identities are loaded before the references are checked);
without an assignment no endpoint is a reference.

ENDPOINTS. A record's endpoint is {"world", "frame"} and, as the plan carries them, "uuid" (its
world's) and/or "snapshot" (uuid5(URL, "finfolk:snapshot:<world uuid>:<frame>")); or a REFERENCE
{"ref": "RP:<k>"} (optionally its "uuid" / "snapshot", which must be the registered reference's), granted
only for a registered slot of the endpoint's guild and refused when mixed with any world, frame or
other identity key; or, for predators, the documented random-founder source {"source": "random"}
(no held-out role: the edge's role is its prey's). The labels must agree with the identities: a world's UUID is the registry's;
a fork branch (or a technical segment of one) resolves to its ROOT world (its own UUID binds its
snapshots) and takes the root's split; a contradiction is refused before any role is computed.
A snapshot's role is its world's split, or its holdout role in a training world. An EDGE's role is
its most held-out endpoint, test before validation before training (references count as training).

ROLES OF RECORDS (check, filter). A record carries "role", "prey" and "predators" (an endpoint or
null). Its identity is its endpoint pair (replicates, horizons and condition versions are copies of
one identity). check refuses: a computed role that is not the edge's; a "support" record whose pair is
not a registered support exception; a non-support record whose pair is one (a target cannot be both
evaluated and support); copies of one identity with different roles. Audit and diagnostic are
declared roles. filter (after a full check) keeps what a stage may use: fit -> training + support
(map placement); nuisance -> training only (Annex H.8: the backbone's calibration nuisance is fitted
on training-world observations, never on held-out populations' support); validation; test; audit
(scoring only); diagnostic.

COMMITMENTS. Every artifact below, the split manifest included, is PUBLISHED EXCLUSIVELY (a temporary
file, fsync'd, hard-linked to its name, which fails if it exists, the directory fsync'd; the same bytes
again are accepted, other bytes refused) under STUDY/registration/.lock, one transaction at a time; the
directory setup happens INSIDE the lock and every directory from the target up to the filesystem
root is fsync'd unconditionally (whoever created it, wherever a missing chain began). commit reads the predictions ONCE (one JSONL file, a unique "target_id" per line), validates
and hashes those bytes: registration/<stage>_predictions.json (the record, its sha256) and then the
marker VAL_PRED_SHA / TEST_PRED_SHA (that sha256). open-validation records the validation evaluation
(the sha256 of the validation scores, the time) after VAL_PRED_SHA; the test commitment requires it
and names the frozen evaluation script. freeze (after TEST_PRED_SHA) requires the split manifest and
records the public registration (OSF URL and/or DOI, and its registration time: a real UTC time, not
in the future, not before the validation evaluation was opened), the
sha256 of the preregistration, the evaluation script, the split manifest, VAL_PRED_SHA and
TEST_PRED_SHA. Every marker must equal its record's sha256 (checked by freeze and by the gate).
require_test_freeze (verify-test) reads the predictions, the script and the manifest ONCE, verifies
them against the freeze record (itself read ONCE) and returns those verified bytes and the freeze
record parsed from the checked bytes: scoring consumes them, never the paths again.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

SPLITS_SCHEMA = "finfolk.redqueen.splits/2"
FREEZE_SCHEMA = "finfolk.redqueen.freeze/2"
COMMIT_SCHEMA = "finfolk.redqueen.predcommit/2"
VALEVAL_SCHEMA = "finfolk.redqueen.valeval/1"
REFS_SCHEMA = "finfolk.redqueen.references/1"
REF_SLOT = re.compile(r"^R[QP]:\d+$")
ENDPOINT_IDENTITY = ("world", "frame", "uuid", "snapshot", "source")
ROLES = ("training", "validation", "test", "support", "audit", "diagnostic")
COMPUTED = ("training", "validation", "test")
DECLARED = ("support", "audit", "diagnostic")
RANK = {"training": 0, "validation": 1, "test": 2}
SPLIT = {"train": "training", "val": "validation", "test": "test",
         "training": "training", "validation": "validation"}
STAGES = {"fit": ("training", "support"), "nuisance": ("training",), "validation": ("validation",),
          "test": ("test",), "audit": ("audit",), "diagnostic": ("diagnostic",)}
UNIT = 1_000_000
OSF_URL = re.compile(r"^https://osf\.io/[a-z0-9]{5,}/?$")
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
SHA = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SealError(Exception):
    pass


# ================================================================== durable, exclusive publication
def mkdirs_durable(path, root):
    """Make `path` (inside `root`) and fsync it and EVERY ancestor up to the filesystem root,
    UNCONDITIONALLY (another writer may have created a directory and not yet fsync'd its parent; a
    missing chain may begin above the study)."""
    path, root = os.path.abspath(path), os.path.abspath(root)
    if os.path.commonpath([path, root]) != root:
        raise SealError(f"{path} is not inside {root}")
    os.makedirs(path, exist_ok=True)
    p = path                                 # every ancestor, up to the filesystem root: whoever created a
    while True:                              # directory (and wherever the chain began), its entry is durable
        rqlib.fsync_dir(p)
        if os.path.dirname(p) == p:
            break
        p = os.path.dirname(p)


def publish(path, data, root=None):
    """Publish `data` at `path` exclusively: a temporary file, fsync'd, hard-linked to `path` (which fails
    if any file is there), the directory fsync'd. The same bytes already there: accepted (True if this
    call published). Other bytes: SealError (never replaced)."""
    d = os.path.dirname(os.path.abspath(path))
    mkdirs_durable(d, root or d)
    if os.path.exists(path):
        if rqlib.read_bytes(path) == data:
            return False
        raise SealError(f"{path} exists with other bytes: it is never replaced")
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    except FileExistsError:
        os.remove(tmp)
        if rqlib.read_bytes(path) == data:
            return False
        raise SealError(f"{path} was published by another writer with other bytes")
    rqlib.fsync_dir(d)
    os.remove(tmp)
    rqlib.fsync_dir(d)
    return True


@contextlib.contextmanager
def transaction(study):
    """One commitment / freeze transaction at a time per study (a blocking flock)."""
    import fcntl
    d = reg_dir(study)
    os.makedirs(d, exist_ok=True)                    # (the lock's own directory; made durable under the lock)
    with open(os.path.join(d, ".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            mkdirs_durable(d, study)
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def publish_manifest(study, data):
    """The split manifest, published at STUDY/config/splits.json under the registration lock."""
    study = os.path.abspath(study)
    with transaction(study):
        return publish(os.path.join(study, "config", "splits.json"), data, study)


# ================================================================== the split manifest
def snapshot_uuid(world_uuid, frame):
    """The snapshot UUID recipe of plan.py (#63): uuid5(URL, "finfolk:snapshot:<world uuid>:<frame>")."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:snapshot:{world_uuid}:{int(frame)}"))


MAX_FRAME_INDEX = 400            # snapshot frames F1, 1M .. 400M: the identity space checked for collisions


def study_identities(uuids, branches):
    """Every study identity: {uuid: owner} of the main worlds, the fork branches and their roots, and
    {snapshot uuid: owner} of all of them at every snapshot frame (F1 and k x 1M up to 400M)."""
    ids = {u: f"world {w}" for w, u in uuids.items()}
    for b, v in branches.items():
        ids[v["uuid"]] = f"fork branch {b}"
    snaps = {}
    for u, owner in ids.items():
        for f in [1] + [k * UNIT for k in range(1, MAX_FRAME_INDEX + 1)]:
            snaps[snapshot_uuid(u, f)] = f"{owner}@{f}"
    return ids, snaps


def load_references(path, uuids, branches=None, main_namespace=None):
    """The registered reference assignment: slot -> {"world", "frame", "uuid", "snapshot", "archive",
    "sha256"}, the references from the SENTINEL namespace only, never a study identity (see the doc)."""
    r = rqlib.read_json(path)
    if r.get("schema") != REFS_SCHEMA:
        raise SealError(f"{path}: schema {r.get('schema')!r}")
    ns = r.get("namespace")
    if not isinstance(ns, str) or not ns:
        raise SealError(f"{path}: the sentinel namespace the references come from is required")
    if main_namespace is not None and ns == main_namespace:
        raise SealError(f"{path}: the references' namespace {ns!r} is the main registry's")
    ids, snaps = study_identities(uuids, branches or {})
    out, seen = {}, {}
    for slot, v in sorted((r.get("references") or {}).items()):
        if not REF_SLOT.match(slot):
            raise SealError(f"{path}: {slot!r} is not a reference slot (RQ:<k> / RP:<k>)")
        if (not isinstance(v, dict) or not isinstance(v.get("uuid"), str) or not SHA.match(str(v.get("sha256", "")))
                or not isinstance(v.get("world"), str) or not isinstance(v.get("frame"), int)):
            raise SealError(f"{path}: {slot} needs its sentinel world, frame, uuid and archive sha256")
        want = str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{ns}:{v['world']}"))
        if v["uuid"] != want:
            raise SealError(f"{path}: {slot}'s uuid is not sentinel world {v['world']}'s in namespace {ns}")
        snap = snapshot_uuid(v["uuid"], v["frame"])
        if v.get("snapshot") not in (None, snap):
            raise SealError(f"{path}: {slot}'s snapshot UUID is not {v['world']}@{v['frame']}'s")
        if v["uuid"] in ids or snap in snaps or v.get("snapshot") in snaps:
            owner = ids.get(v["uuid"]) or snaps.get(snap) or snaps.get(v.get("snapshot"))
            raise SealError(f"{path}: {slot} collides with a study identity ({owner})")
        key = (slot[1], snap)                # (#71 r1 P2-4: one SNAPSHOT per guild; a sentinel world may give
        if key in seen:                      #  several references at different frames)
            raise SealError(f"{path}: {slot} and {seen[key]} are one reference (the same snapshot in one guild)")
        seen[key] = slot
        out[slot] = dict({k: v[k] for k in ("world", "frame", "uuid", "archive", "sha256")}, snapshot=snap)
    for g in "QP":
        if sum(1 for s_ in out if s_[1] == g) != 8:
            raise SealError(f"{path}: eight R{g} references are registered, not {sum(1 for s_ in out if s_[1] == g)}")
    return out


def manifest(meta_path, worlds_path, forks_path=None, refs_path=None):
    import gzip
    m = rqlib.read_json(meta_path)
    edges_path = os.path.join(os.path.dirname(os.path.abspath(meta_path)), "graph.jsonl.gz")
    split = {w: SPLIT[s] for w, s in sorted(m["split"].items())}
    hold = {}
    for key, s in sorted(m.get("holdout", {}).items()):
        w, _, t = key.rpartition(":")
        if split.get(w) != "training":
            raise SealError(f"holdout {key}: {w} is not a training world")
        hold.setdefault(w, {})[str(int(t))] = SPLIT[s]
    reg = rqlib.read_json(worlds_path)
    uuids = {w["id"]: w["uuid"] for w in reg["worlds"]}
    if set(uuids) != set(split):
        raise SealError(f"the graph's worlds are not the registry's ({sorted(set(uuids) ^ set(split))[:5]})")
    support = []
    with gzip.open(edges_path, "rt") as f:
        for ln in f:
            e = json.loads(ln)
            if e.get("role") == "support":
                support.append([e["prey"], e["pred"]])
    out = {"schema": SPLITS_SCHEMA, "time_unit": UNIT, "precedence": ["test", "validation", "training"],
           "graph": {"meta_sha256": rqlib.sha256_file(meta_path), "edges_sha256": rqlib.sha256_file(edges_path),
                     "namespace": m.get("namespace"), "graph_edges_sha256": m.get("edges_sha256")},
           "worlds_registry_sha256": rqlib.sha256_file(worlds_path),
           "worlds": split, "uuids": uuids, "snapshot_holdouts": hold, "fork": sorted(m.get("fork", [])),
           "intensive": sorted(m.get("intensive", [])), "support_exceptions": sorted(support), "branches": {},
           "references": {}}
    if forks_path:                           # (every study identity first: the references are checked against all)
        fk = rqlib.read_json(forks_path)
        for b in fk["worlds"]:
            if b["root"] not in uuids or b.get("root_uuid") not in (None, uuids[b["root"]]):
                raise SealError(f"fork branch {b['id']}: its root {b['root']} is not the registry's")
            if b["id"] in uuids:
                raise SealError(f"fork branch {b['id']} reuses a world id")
            if b["uuid"] in set(uuids.values()):
                raise SealError(f"fork branch {b['id']} reuses a world's uuid")
            out["branches"][b["id"]] = {"root": b["root"], "uuid": b["uuid"]}
        out["forks_sha256"] = rqlib.sha256_file(forks_path)
    if refs_path:
        out["references"] = load_references(refs_path, uuids, out["branches"], reg.get("namespace"))
        out["references_sha256"] = rqlib.sha256_file(refs_path)
        for pair in support:
            for k in pair:
                if REF_SLOT.match(k) and k not in out["references"]:
                    raise SealError(f"support pair {pair}: reference {k} is not registered")
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


def resolve(m, e, guild):
    """An endpoint -> (key, role): its identity checked against the registered UUIDs (a fork branch's
    snapshot resolves to its ROOT world's split), its support-exception key ("Q:<world>:<t>" /
    "P:<world>:<t>"; a branch keys by its own id and frame) and its role. SealError on a contradiction."""
    if "ref" in e:
        ref = e["ref"]
        mixed = sorted(k for k in ("world", "frame", "source") if k in e)
        if mixed:
            raise SealError(f"reference endpoint {ref!r} mixed with {mixed}: an endpoint is a world snapshot or a "
                            "registered reference, never both")
        if not isinstance(ref, str) or not REF_SLOT.match(ref) or ref[1] != guild:
            raise SealError(f"reference endpoint {ref!r} is not a {guild} reference slot")
        reg = m.get("references", {}).get(ref)
        if reg is None:
            raise SealError(f"reference {ref} is not in the registered reference assignment")
        for k in ("uuid", "snapshot"):
            if e.get(k) is not None and e[k] != reg.get(k, reg["uuid"] if k == "uuid" else None):
                raise SealError(f"reference {ref}: its {k} {e[k]} is not the registered reference's")
        return ref, "training"
    if "source" in e:
        if guild != "P" or e != {"source": "random"}:
            raise SealError(f"endpoint {e}: only a predator endpoint may be exactly {{'source': 'random'}}")
        return "random", None
    w, frame = e.get("world"), e.get("frame")
    if frame is None:
        raise SealError(f"endpoint {w}: no frame")
    if w in m["branches"]:
        b = m["branches"][w]
        own_uuid, role = b["uuid"], m["worlds"][b["root"]]        # (descendants keep their root's split)
        key = f"{guild}:{w}:{int(frame)}"
    elif w in m["worlds"]:
        own_uuid, role = m["uuids"][w], m["worlds"][w]
        if role == "training":
            role = m["snapshot_holdouts"].get(w, {}).get(str(t_of(frame)), "training")
        key = f"{guild}:{w}:{t_of(frame)}"
    else:
        raise SealError(f"world {w} is not in the split manifest (nor a registered fork branch)")
    if e.get("uuid") is not None and e["uuid"] != own_uuid:
        raise SealError(f"endpoint {w}@{frame}: its UUID {e['uuid']} is not {w}'s ({own_uuid})")
    if e.get("snapshot") is not None and e["snapshot"] != snapshot_uuid(own_uuid, frame):
        raise SealError(f"endpoint {w}@{frame}: its snapshot UUID belongs to another world or frame")
    return key, role


def node_role(m, world, frame):
    return resolve(m, {"world": world, "frame": frame}, "Q")[1]


def edge_role(m, prey, predators):
    """The most held-out endpoint's role (test before validation before training)."""
    roles = [resolve(m, prey, "Q")[1]]
    if predators:
        roles.append(resolve(m, predators, "P")[1])
    return max((r for r in roles if r), key=RANK.__getitem__)


def record_problems(m, rows):
    """Why records disagree with the manifest (see ROLES OF RECORDS)."""
    probs = []
    support = {tuple(x) for x in m.get("support_exceptions", [])}
    seen = {}
    for k, r in enumerate(rows):
        rid = r.get("id") or r.get("target_id") or f"record {k + 1}"
        role = r.get("role")
        if role not in ROLES:
            probs.append(f"{rid}: role {role!r}")
            continue
        try:
            q, rq = resolve(m, r["prey"], "Q")
            p, rp = resolve(m, r["predators"], "P") if r.get("predators") else ("none", None)
        except (SealError, KeyError, TypeError, ValueError) as e:
            probs.append(f"{rid}: {e}")
            continue
        key = (q, p)
        if key in seen and seen[key][0] != role:
            probs.append(f"{rid}: role {role}, but a copy of the same target ({seen[key][1]}) is {seen[key][0]}")
        seen.setdefault(key, (role, rid))
        if role == "support":
            if key not in support:
                probs.append(f"{rid}: a support record whose pair is not a registered support exception")
            continue
        if key in support:
            probs.append(f"{rid}: role {role}, but its pair is a registered support exception (a target cannot "
                         "be both evaluated and support)")
            continue
        if role in DECLARED:
            continue
        want = max([rq] + ([rp] if rp else []), key=RANK.__getitem__)      # (a random source has no role)
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


def _jsonl_bytes(data, name):
    rows = []
    for k, ln in enumerate(data.decode("utf-8").split("\n"), 1):
        if ln.strip():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                raise SealError(f"{name}: line {k} is not JSON")
    return rows


def _check_predictions(data, name):
    rows = _jsonl_bytes(data, name)
    ids = [r.get("target_id") for r in rows if isinstance(r, dict)]
    if len(ids) != len(rows) or not rows or any(not isinstance(i, str) or not i for i in ids):
        raise SealError(f"{name}: every line is an object with a target_id")
    if len(set(ids)) != len(ids):
        raise SealError(f"{name}: a target_id occurs twice")
    return ids


def _marker(study, name):
    p = os.path.join(reg_dir(study), name)
    return rqlib.read_text(p).split()[0] if os.path.isfile(p) else None


def _bound(study, stage):
    """(marker, its record) of a stage, the marker equal to the record's sha256 (SealError otherwise)."""
    name = "VAL_PRED_SHA" if stage == "validation" else "TEST_PRED_SHA"
    mk = _marker(study, name)
    rp = os.path.join(reg_dir(study), f"{stage}_predictions.json")
    rec = rqlib.read_json(rp) if os.path.isfile(rp) else None
    if mk is None:
        return None, rec
    if rec is None or rec.get("sha256") != mk:
        raise SealError(f"{name} ({mk[:12]}) is not bound to its record {rp}")
    return mk, rec


def commit(study, stage, pred_path, eval_script=None):
    """Record a stage's plain prediction hash (VAL_PRED_SHA / TEST_PRED_SHA) -> its record."""
    if stage not in ("validation", "test"):
        raise SealError(f"stage {stage!r}: validation or test")
    data = rqlib.read_bytes(pred_path)                     # read ONCE: the validated and hashed bytes
    ids = _check_predictions(data, pred_path)
    sha = rqlib.sha256_bytes(data)
    name = "VAL_PRED_SHA" if stage == "validation" else "TEST_PRED_SHA"
    with transaction(study):
        d = reg_dir(study)
        have, rec = _bound(study, stage)
        if have is not None:
            if have != sha:
                raise SealError(f"{name} is already committed ({have[:12]}); a commitment is never replaced")
            return rec
        rec = {"schema": COMMIT_SCHEMA, "stage": stage, "name": name, "sha256": sha,
               "file": os.path.abspath(pred_path), "bytes": len(data), "targets": len(ids),
               "target_ids_sha256": rqlib.canonical_sha(sorted(ids)), "utc": rqlib.now_utc()}
        if stage == "test":
            val, _ = _bound(study, "validation")
            if val is None:
                raise SealError("the test predictions are committed after the validation predictions (VAL_PRED_SHA)")
            ve = os.path.join(d, "validation_evaluation.json")
            if not os.path.isfile(ve) or rqlib.read_json(ve).get("VAL_PRED_SHA") != val:
                raise SealError("the validation evaluation is recorded (open-validation) before the test commitment")
            if not eval_script:
                raise SealError("the test commitment names the frozen evaluation script (--eval-script)")
            rec.update(evaluation_script_sha256=rqlib.sha256_file(eval_script), VAL_PRED_SHA=val,
                       validation_evaluation_sha256=rqlib.sha256_file(ve))
        rp = os.path.join(d, f"{stage}_predictions.json")
        if os.path.exists(rp) and rqlib.read_json(rp).get("sha256") != sha:
            raise SealError(f"{rp} records other predictions (an interrupted commitment): resolve it by hand")
        if not os.path.exists(rp):
            publish(rp, rqlib.canonical(rec), study)
        rec = rqlib.read_json(rp)
        publish(os.path.join(d, name), (sha + "\n").encode(), study)
        return rec


def open_validation(study, scores_path):
    """Record the validation evaluation (the scores' sha256, the time), after VAL_PRED_SHA, before TEST."""
    data = rqlib.read_bytes(scores_path)
    with transaction(study):
        val, _ = _bound(study, "validation")
        if val is None:
            raise SealError("the validation evaluation follows VAL_PRED_SHA")
        if _marker(study, "TEST_PRED_SHA"):
            raise SealError("TEST_PRED_SHA is already committed: the validation evaluation came first or not at all")
        p = os.path.join(reg_dir(study), "validation_evaluation.json")
        rec = {"schema": VALEVAL_SCHEMA, "VAL_PRED_SHA": val, "scores_sha256": rqlib.sha256_bytes(data),
               "scores": os.path.abspath(scores_path), "utc": rqlib.now_utc()}
        if os.path.exists(p):
            have = rqlib.read_json(p)
            if have.get("scores_sha256") != rec["scores_sha256"] or have.get("VAL_PRED_SHA") != val:
                raise SealError(f"{p} exists with other contents: never replaced")
            return have
        publish(p, rqlib.canonical(rec), study)
        return rec


def parse_utc(text):
    """A real UTC time YYYY-MM-DDTHH:MM:SSZ -> datetime (SealError otherwise)."""
    import datetime
    if not isinstance(text, str) or not UTC.match(text):
        raise SealError(f"{text!r} is not a UTC time YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise SealError(f"{text!r} is not a real date and time") from None


def registration_time_problem(text, opened_utc, now=None):
    """Why the public registration time is not acceptable (None: it is): a real UTC time, not in the
    future (60 s of clock tolerance), not before the validation evaluation was opened."""
    import datetime
    try:
        t = parse_utc(text)
    except SealError as e:
        return str(e)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if t > now + datetime.timedelta(seconds=60):
        return f"the registration time {text} is in the future"
    if opened_utc is None:
        return "no recorded validation evaluation to order the registration after"
    if t < parse_utc(opened_utc):
        return f"the registration time {text} precedes the validation evaluation ({opened_utc})"
    return None


def freeze(study, preregistration, eval_script, osf_url=None, doi=None, registered_utc=None):
    """The public freeze record (after TEST_PRED_SHA) -> its record (published once; never replaced)."""
    if not osf_url and not doi:
        raise SealError("the freeze record names the public registration: --osf-url and/or --doi")
    if osf_url and not OSF_URL.match(osf_url):
        raise SealError(f"--osf-url {osf_url!r}: expected https://osf.io/<id>")
    if doi and not DOI.match(doi):
        raise SealError(f"--doi {doi!r}: expected 10.<registrant>/<suffix>")
    if not registered_utc or not UTC.match(registered_utc):
        raise SealError("--registered-utc: the public registration's time (YYYY-MM-DDTHH:MM:SSZ), from OSF")
    with transaction(study):
        d = reg_dir(study)
        val, _ = _bound(study, "validation")
        test, trec = _bound(study, "test")
        if val is None or test is None:
            raise SealError("VAL_PRED_SHA and TEST_PRED_SHA are committed before the freeze")
        es = rqlib.sha256_file(eval_script)
        if es != trec["evaluation_script_sha256"]:
            raise SealError("the evaluation script differs from the one the test commitment named")
        ve = os.path.join(d, "validation_evaluation.json")
        why = registration_time_problem(registered_utc, rqlib.read_json(ve).get("utc") if os.path.isfile(ve) else None)
        if why:
            raise SealError(f"--registered-utc: {why}")
        mp = os.path.join(study, "config", "splits.json")
        if not os.path.isfile(mp):
            raise SealError("the freeze requires the split manifest (config/splits.json)")
        load_manifest(mp)
        rec = {"schema": FREEZE_SCHEMA, "osf": {"url": osf_url, "doi": doi, "registered_utc": registered_utc},
               "preregistration_sha256": rqlib.sha256_file(preregistration), "evaluation_script_sha256": es,
               "split_manifest_sha256": rqlib.sha256_file(mp), "VAL_PRED_SHA": val, "TEST_PRED_SHA": test,
               "validation_evaluation_sha256": trec.get("validation_evaluation_sha256")}
        p = os.path.join(d, "freeze.json")
        if os.path.isfile(p):
            have = rqlib.read_json(p)
            if {k: v for k, v in have.items() if k != "utc"} != rec:
                raise SealError(f"{p} exists with other contents: a freeze record is never replaced")
            return have
        rec["utc"] = rqlib.now_utc()
        publish(p, rqlib.canonical(rec), study)
        return rec


def test_problems(study, pred_bytes, script_bytes, manifest_bytes, freeze_bytes=None):
    """Why test scoring may not start on these exact bytes (empty: it may). freeze_bytes: the freeze
    record as read once by the caller (else read here)."""
    d = reg_dir(study)
    p = os.path.join(d, "freeze.json")
    if freeze_bytes is None:
        if not os.path.isfile(p):
            return ["no public freeze record (sealing.py freeze, after the OSF deposit)"]
        freeze_bytes = rqlib.read_bytes(p)
    try:
        f = json.loads(freeze_bytes.decode("utf-8"))
    except ValueError:
        return ["freeze.json is not JSON"]
    probs = []
    if f.get("schema") != FREEZE_SCHEMA:
        probs.append(f"freeze.json: schema {f.get('schema')!r}")
    o = f.get("osf") or {}
    if not ((o.get("url") and OSF_URL.match(o["url"])) or (o.get("doi") and DOI.match(o["doi"]))):
        probs.append("the freeze record names no public registration (OSF URL or DOI)")
    ve = os.path.join(d, "validation_evaluation.json")
    try:
        why = registration_time_problem(o.get("registered_utc"),
                                        rqlib.read_json(ve).get("utc") if os.path.isfile(ve) else None,
                                        parse_utc(f["utc"]) if f.get("utc") else None)
    except SealError as e:
        why = str(e)
    if why:
        probs.append(f"the freeze record's public registration time: {why}")
    for k in ("preregistration_sha256", "evaluation_script_sha256", "split_manifest_sha256", "VAL_PRED_SHA",
              "TEST_PRED_SHA"):
        if not SHA.match(str(f.get(k) or "")):
            probs.append(f"the freeze record lacks {k}")
    for stage, name in (("validation", "VAL_PRED_SHA"), ("test", "TEST_PRED_SHA")):
        try:
            mk, _ = _bound(study, stage)
        except SealError as e:
            probs.append(str(e))
            continue
        if mk != f.get(name):
            probs.append(f"{name} differs from the freeze record")
    if rqlib.sha256_bytes(pred_bytes) != f.get("TEST_PRED_SHA"):
        probs.append("these are not the committed test predictions")
    if rqlib.sha256_bytes(script_bytes) != f.get("evaluation_script_sha256"):
        probs.append("this is not the frozen evaluation script")
    if manifest_bytes is None or rqlib.sha256_bytes(manifest_bytes) != f.get("split_manifest_sha256"):
        probs.append("config/splits.json is not the frozen split manifest")
    return probs


def require_test_freeze(study, pred_path, eval_script):
    """The gate a test-scoring script calls first: the predictions, the script and the manifest read ONCE,
    verified against the freeze record -> {"predictions": bytes, "manifest": bytes, "freeze": record}:
    scoring consumes these verified bytes, never the paths again."""
    fp = os.path.join(reg_dir(study), "freeze.json")
    if not os.path.isfile(fp):
        raise SealError("test evaluation refused: no public freeze record (sealing.py freeze, after the OSF deposit)")
    fb = rqlib.read_bytes(fp)                         # read ONCE: the record checked is the record returned
    pred = rqlib.read_bytes(pred_path)
    script = rqlib.read_bytes(eval_script)
    mp = os.path.join(study, "config", "splits.json")
    man = rqlib.read_bytes(mp) if os.path.isfile(mp) else None
    probs = test_problems(study, pred, script, man, fb)
    if probs:
        raise SealError("test evaluation refused: " + "; ".join(probs))
    return {"predictions": pred, "manifest": man, "freeze": json.loads(fb.decode("utf-8")), "freeze_bytes": fb}


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("manifest")
    s.add_argument("--graph-meta", required=True)
    s.add_argument("--worlds", required=True)
    s.add_argument("--forks")
    s.add_argument("--references")
    s.add_argument("--out", required=True, help="STUDY/config/splits.json (published under STUDY's lock)")
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
    s = sub.add_parser("open-validation")
    s.add_argument("--study", required=True)
    s.add_argument("--scores", required=True)
    s = sub.add_parser("freeze")
    s.add_argument("--study", required=True)
    s.add_argument("--preregistration", required=True)
    s.add_argument("--eval-script", required=True)
    s.add_argument("--osf-url")
    s.add_argument("--doi")
    s.add_argument("--registered-utc", required=True)
    s = sub.add_parser("verify-test")
    s.add_argument("--study", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--eval-script", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "manifest":
            data = rqlib.canonical(manifest(a.graph_meta, a.worlds, a.forks, a.references))
            out = os.path.abspath(a.out)
            if os.path.basename(out) != "splits.json" or os.path.basename(os.path.dirname(out)) != "config":
                raise SealError("--out: the split manifest lives at STUDY/config/splits.json")
            publish_manifest(os.path.dirname(os.path.dirname(out)), data)
            print(f"split manifest {a.out}: sha256 {rqlib.sha256_bytes(data)}", file=sys.stderr)
            return 0
        if a.cmd in ("check", "filter"):
            m = load_manifest(a.manifest)
            rows = _jsonl_bytes(rqlib.read_bytes(a.records), a.records)
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
        if a.cmd == "open-validation":
            rec = open_validation(study, a.scores)
            print(f"validation evaluation recorded: scores {rec['scores_sha256']}")
            return 0
        if a.cmd == "freeze":
            rec = freeze(study, a.preregistration, a.eval_script, a.osf_url, a.doi, a.registered_utc)
            print(f"freeze record {os.path.join(reg_dir(study), 'freeze.json')}: sha256 "
                  f"{rqlib.sha256_file(os.path.join(reg_dir(study), 'freeze.json'))} (OSF {rec['osf']})")
            return 0
        try:
            require_test_freeze(study, a.predictions, a.eval_script)
        except SealError as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 2
        print("test evaluation may start: the freeze record, predictions, script and manifest verify")
        return 0
    except (SealError, OSError, KeyError, ValueError) as e:
        print(f"sealing.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
