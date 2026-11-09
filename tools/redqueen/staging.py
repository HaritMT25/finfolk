"""staging.py: the staged-analysis plumbing shared by forecast.py (Level 2) and probes.py (Level 3), in the
registration order of design v4 §7.2 (sealing.py's commitments).

THE COMMITMENT ROOT. sealing.py keeps ONE VAL_PRED_SHA / TEST_PRED_SHA pair per study directory, so each
registered analysis has its own commitment root ROOT (e.g. STUDY/analyses/forecast, STUDY/analyses/probes):
sealing.py's layout, with
  ROOT/config/splits.json   the study's split manifest, byte-identical (its sha256 is registered in the
                            analysis configuration; require_test_freeze checks it against the freeze record);
  ROOT/config/<analysis>    the REGISTERED ANALYSIS CONFIGURATION (forecast.json / probes.json), published once
                            under ROOT's registration lock (exclusive: never replaced), BEFORE any candidate
                            prediction is committed; every stage reads it and binds its sha256;
  ROOT/registration/        sealing.py's commitments: VAL_PRED_SHA, validation_evaluation.json, TEST_PRED_SHA,
                            freeze.json (sealing.py commit / open-validation / freeze).

IDENTITIES AND ROLES. A row names {"world", "t" (M)} and optionally its "uuid" / "snapshot"; its role is
COMPUTED from the split manifest (sealing.resolve: a fork branch resolves to its root world's split, a
training world's held-out snapshot to its holdout role) and the identities are checked against the
registered UUIDs. A caller-supplied split / role label is refused: roles are never taken from the input.

VERIFIED READS. A committed prediction file is read ONCE; its bytes must hash to the registered marker
(VAL_PRED_SHA / TEST_PRED_SHA, itself bound to its record) and are parsed from those same bytes. The
validation selection is read once and must be the scores recorded by open-validation. Test scoring passes
through sealing.require_test_freeze and consumes the verified bytes it returns, never the path again.
"""
from __future__ import annotations

import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import sealing  # noqa: E402

UNIT = sealing.UNIT
LABEL_KEYS = ("split", "role", "stage", "holdout")
STAGE_RANK = {"training": 0, "validation": 1, "test": 2}


class StageError(Exception):
    pass


# ================================================================== documents and bytes
def read_doc(path):
    """-> (bytes, parsed JSON, sha256 of the bytes): one read."""
    data = rqlib.read_bytes(path)
    try:
        return data, json.loads(data.decode("utf-8")), rqlib.sha256_bytes(data)
    except ValueError:
        raise StageError(f"{path} is not JSON") from None


def jsonl_bytes(rows):
    return b"".join(rqlib.canonical(r) for r in rows)


def parse_jsonl(data, name):
    try:
        return sealing._jsonl_bytes(data, name)
    except sealing.SealError as e:
        raise StageError(str(e)) from None


def most_held_out(*roles):
    return max((r for r in roles if r), key=STAGE_RANK.__getitem__)


# ================================================================== the registered configuration
def config_path(root, name):
    return os.path.join(root, "config", name)


def register_config(root, name, data, validate):
    """Publish the analysis configuration ROOT/config/<name> exclusively under ROOT's registration lock
    (the same bytes again: accepted; other bytes: refused). It precedes the candidate predictions: refused
    once VAL_PRED_SHA is committed (unless these exact bytes are the registered ones)."""
    root = os.path.abspath(root)
    cfg = json.loads(data.decode("utf-8"))
    validate(root, cfg)
    p = config_path(root, name)
    with sealing.transaction(root):
        have = rqlib.read_bytes(p) if os.path.isfile(p) else None
        if have is None and sealing._marker(root, "VAL_PRED_SHA"):
            raise StageError(f"VAL_PRED_SHA is committed: the analysis configuration is registered before the candidates")
        try:
            sealing.publish(p, data, root)
        except sealing.SealError as e:
            raise StageError(str(e)) from None
    return rqlib.sha256_bytes(data)


def load_root(root, name, schema, validate):
    """The commitment root's registered artifacts -> {"root", "cfg", "cfg_sha", "manifest", "manifest_sha"}.
    The configuration must be the published one and name the split manifest's sha256."""
    root = os.path.abspath(root)
    p = config_path(root, name)
    if not os.path.isfile(p):
        raise StageError(f"{p}: no registered analysis configuration (register it first)")
    data, cfg, sha = read_doc(p)
    if cfg.get("schema") != schema:
        raise StageError(f"{p}: schema {cfg.get('schema')!r}")
    mp = os.path.join(root, "config", "splits.json")
    if not os.path.isfile(mp):
        raise StageError(f"{mp}: the commitment root holds no split manifest")
    mdata, man, msha = read_doc(mp)
    if man.get("schema") != sealing.SPLITS_SCHEMA:
        raise StageError(f"{mp}: schema {man.get('schema')!r}")
    if cfg.get("split_manifest_sha256") != msha:
        raise StageError(f"{mp} is not the split manifest the configuration registers "
                         f"({str(cfg.get('split_manifest_sha256'))[:12]} registered, {msha[:12]} found)")
    validate(root, cfg)
    return {"root": root, "cfg": cfg, "cfg_sha": sha, "manifest": man, "manifest_sha": msha}


# ================================================================== identities and roles
def frame_of(t):
    """A snapshot's frame from its time in M: t = 0 is F1 (frame 1)."""
    if not isinstance(t, int) or isinstance(t, bool) or t < 0:
        raise StageError(f"t {t!r}: a snapshot time is a non-negative integer (M)")
    return t * UNIT if t else 1


def resolve_row(manifest, r, what="row"):
    """A row's identity -> {"world", "t", "root", "branch", "role", "world_role"}: the role computed from
    the split manifest (holdouts included), the identities checked. A split / role label is refused."""
    if not isinstance(r, dict):
        raise StageError(f"{what}: not an object")
    lab = sorted(k for k in LABEL_KEYS if k in r)
    if lab:
        raise StageError(f"{what} {r.get('world')}@{r.get('t')}: carries {lab}; roles come from the split "
                         "manifest, never from the input")
    w, t = r.get("world"), r.get("t")
    if not isinstance(w, str) or not w:
        raise StageError(f"{what}: no world")
    e = {"world": w, "frame": frame_of(t)}
    for k in ("uuid", "snapshot"):
        if r.get(k) is not None:
            e[k] = r[k]
    try:
        _, role = sealing.resolve(manifest, e, "Q")
    except (sealing.SealError, KeyError, TypeError, ValueError) as ex:
        raise StageError(f"{what} {w}@{t}: {ex}") from None
    br = manifest.get("branches", {}).get(w)
    root = br["root"] if br else w
    return {"world": w, "t": t, "root": root, "branch": br is not None, "role": role,
            "world_role": manifest["worlds"][root]}


# ================================================================== verified reads
def read_committed(root, stage, path):
    """The committed prediction file of a stage, read ONCE: its bytes must hash to the registered marker
    (bound to its record) -> (bytes, rows, marker)."""
    data = rqlib.read_bytes(path)
    try:
        mk, rec = sealing._bound(root, stage)
    except sealing.SealError as e:
        raise StageError(str(e)) from None
    name = "VAL_PRED_SHA" if stage == "validation" else "TEST_PRED_SHA"
    if mk is None:
        raise StageError(f"no {name} is committed (sealing.py commit --stage {stage}): refusing to score")
    if rqlib.sha256_bytes(data) != mk:
        raise StageError(f"{path} is not the committed {stage} predictions ({name} {mk[:12]})")
    rows = parse_jsonl(data, path)
    if rqlib.canonical_sha(sorted(r["target_id"] for r in rows)) != rec.get("target_ids_sha256"):
        raise StageError(f"{path}: its target_ids are not the committed record's")
    return data, rows, mk


def read_selection(root, path):
    """The validation selection: read ONCE, it must be the scores recorded by open-validation after the
    committed VAL_PRED_SHA -> (doc, sha256)."""
    data = rqlib.read_bytes(path)
    try:
        val, _ = sealing._bound(root, "validation")
    except sealing.SealError as e:
        raise StageError(str(e)) from None
    if val is None:
        raise StageError("no VAL_PRED_SHA is committed: there is no validation selection")
    ve = os.path.join(sealing.reg_dir(root), "validation_evaluation.json")
    if not os.path.isfile(ve):
        raise StageError("the validation evaluation is not recorded (sealing.py open-validation --scores ...)")
    rec = rqlib.read_json(ve)
    sha = rqlib.sha256_bytes(data)
    if rec.get("VAL_PRED_SHA") != val or rec.get("scores_sha256") != sha:
        raise StageError(f"{path} is not the validation scores recorded by open-validation")
    doc = json.loads(data.decode("utf-8"))
    if doc.get("VAL_PRED_SHA") != val:
        raise StageError(f"{path}: its VAL_PRED_SHA is not the committed one")
    return doc, sha


def check_selection_record(root, lines):
    """Test lines name the selection recorded by open-validation (its scores' sha256 and VAL_PRED_SHA)."""
    ve = os.path.join(sealing.reg_dir(root), "validation_evaluation.json")
    rec = rqlib.read_json(ve) if os.path.isfile(ve) else {}
    for r in lines:
        p = r.get("provenance") or {}
        if p.get("selection_sha256") != rec.get("scores_sha256") or p.get("VAL_PRED_SHA") != rec.get("VAL_PRED_SHA"):
            raise StageError(f"{r.get('target_id')}: not predicted from the validation selection recorded by open-validation")


def test_gate(root, pred_path, script):
    """sealing.require_test_freeze, then the verified bytes parsed -> (rows, TEST_PRED_SHA, freeze sha256)."""
    try:
        got = sealing.require_test_freeze(root, pred_path, script)
    except sealing.SealError as e:
        raise StageError(str(e)) from None
    rows = parse_jsonl(got["predictions"], pred_path)
    return rows, rqlib.sha256_bytes(got["predictions"]), rqlib.sha256_bytes(got["freeze_bytes"])


def committed_rows(root, stage, path, cfg_sha, want_stage):
    """read_committed + every row's provenance names this configuration and the stage it is scored at."""
    data, rows, mk = read_committed(root, stage, path)
    for r in rows:
        if (r.get("provenance") or {}).get("config_sha256") != cfg_sha:
            raise StageError(f"{r['target_id']}: predicted under another analysis configuration")
        if r.get("stage") not in want_stage:
            raise StageError(f"{r['target_id']}: a {r.get('stage')} target in the {stage} predictions")
    return rows, mk


# ================================================================== provenance
def environment():
    """The numerical environment the fits ran in."""
    env = {"python": platform.python_version(), "python_implementation": platform.python_implementation(),
           "platform": platform.platform(), "machine": platform.machine(), "byteorder": sys.byteorder,
           "float_epsilon": sys.float_info.epsilon}
    try:
        import numpy
        env["numpy"] = numpy.__version__
    except ImportError:
        env["numpy"] = None
    return env


def implementation(tool_file):
    """sha256 of the analysis script and every module it runs on."""
    out = {}
    for f in (tool_file, os.path.join(HERE, "staging.py"), os.path.join(HERE, "sealing.py"),
              os.path.join(HERE, "rqlib.py")):
        out[os.path.basename(f)] = rqlib.sha256_file(f)
    return out
