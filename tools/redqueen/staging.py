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
Every registered artifact a stage uses (the configuration, the manifest, the fork registry) is read ONCE:
its byte hash is compared with the registered one and the stage is built from those same bytes.

IDENTITIES AND ROLES. A row names {"world", "t" (M)} and optionally its "uuid" / "snapshot"; its role is
COMPUTED from the split manifest (sealing.resolve: a fork branch resolves to its root world's split, a
training world's held-out snapshot to its holdout role) and the identities are checked against the
registered UUIDs. A caller-supplied split / role label is refused: roles are never taken from the input.

VERIFIED READS. A committed prediction file is read ONCE; its bytes must hash to the registered marker
(VAL_PRED_SHA / TEST_PRED_SHA, itself bound to its record) and are parsed from those same bytes. The
validation selection is read once and must be the scores recorded by open-validation. Test scoring passes
through sealing.require_test_freeze with the evaluator's IMPLEMENTATION MANIFEST (implementation_manifest:
the entry script and every module of the tool as actually LOADED, RQ_PYLIB included, the interpreter and
numpy), frozen as the "evaluation script" of the test commitment; it consumes the verified bytes the gate
returns, the validation-evaluation record included, never the paths again.
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
IMPL_SCHEMA = "finfolk.redqueen.implementation/1"
TOOL_MODULES = ("staging", "sealing", "rqlib")


class StageError(Exception):
    pass


# ================================================================== documents and bytes
def parse_doc(data, name):
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise StageError(f"{name} is not JSON") from None


def read_doc(path):
    """-> (bytes, parsed JSON, sha256 of the bytes): one read."""
    data = rqlib.read_bytes(path)
    return data, parse_doc(data, path), rqlib.sha256_bytes(data)


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


def read_registered(root, names):
    """ROOT/config/<name> for each name, each read ONCE -> {name: (bytes, doc, sha256)}."""
    out = {}
    for n in names:
        p = config_path(root, n)
        if not os.path.isfile(p):
            raise StageError(f"{p} is missing")
        out[n] = read_doc(p)
    return out


def register_config(root, name, data, validate, files=()):
    """Publish the analysis configuration ROOT/config/<name> exclusively under ROOT's registration lock
    (the same bytes again: accepted; other bytes: refused). It precedes the candidate predictions: refused
    once VAL_PRED_SHA is committed (unless these exact bytes are the registered ones). validate(root, cfg,
    docs) sees the registered artifacts as read once."""
    root = os.path.abspath(root)
    cfg = parse_doc(data, name)
    validate(root, cfg, read_registered(root, ("splits.json",) + tuple(files)))
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


def load_root(root, name, schema, validate, files=()):
    """The commitment root's registered artifacts, each read ONCE -> {"root", "cfg", "cfg_sha", "manifest",
    "manifest_sha", "docs" {name: (bytes, doc, sha256)}}. The configuration must name the manifest's sha256;
    validate(root, cfg, docs) checks the rest against the same bytes."""
    root = os.path.abspath(root)
    p = config_path(root, name)
    if not os.path.isfile(p):
        raise StageError(f"{p}: no registered analysis configuration (register it first)")
    _, cfg, sha = read_doc(p)
    if cfg.get("schema") != schema:
        raise StageError(f"{p}: schema {cfg.get('schema')!r}")
    docs = read_registered(root, ("splits.json",) + tuple(files))
    _, man, msha = docs["splits.json"]
    if man.get("schema") != sealing.SPLITS_SCHEMA:
        raise StageError(f"splits.json: schema {man.get('schema')!r}")
    if cfg.get("split_manifest_sha256") != msha:
        raise StageError(f"config/splits.json is not the split manifest the configuration registers "
                         f"({str(cfg.get('split_manifest_sha256'))[:12]} registered, {msha[:12]} found)")
    validate(root, cfg, docs)
    return {"root": root, "cfg": cfg, "cfg_sha": sha, "manifest": man, "manifest_sha": msha, "docs": docs}


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
    committed VAL_PRED_SHA -> (doc, sha256). The record is read once too."""
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
    _, rec, _ = read_doc(ve)
    sha = rqlib.sha256_bytes(data)
    if rec.get("VAL_PRED_SHA") != val or rec.get("scores_sha256") != sha:
        raise StageError(f"{path} is not the validation scores recorded by open-validation")
    doc = parse_doc(data, path)
    if doc.get("VAL_PRED_SHA") != val:
        raise StageError(f"{path}: its VAL_PRED_SHA is not the committed one")
    return doc, sha


def check_selection_record(rec, lines):
    """Test lines name the selection of the VERIFIED validation-evaluation record (as the gate returned it):
    its scores' sha256 and VAL_PRED_SHA."""
    for r in lines:
        p = r.get("provenance") or {}
        if p.get("selection_sha256") != rec.get("scores_sha256") or p.get("VAL_PRED_SHA") != rec.get("VAL_PRED_SHA"):
            raise StageError(f"{r.get('target_id')}: not predicted from the validation selection the freeze recorded")


def test_gate(root, pred_path, impl_bytes):
    """sealing.require_test_freeze with the evaluator's implementation manifest; the verified bytes parsed
    -> {"rows", "TEST_PRED_SHA", "freeze_sha256", "validation_evaluation", "implementation_sha256"}."""
    try:
        got = sealing.require_test_freeze(root, pred_path, None, script_bytes=impl_bytes)
    except sealing.SealError as e:
        raise StageError(str(e)) from None
    return {"rows": parse_jsonl(got["predictions"], pred_path), "TEST_PRED_SHA": rqlib.sha256_bytes(got["predictions"]),
            "freeze_sha256": rqlib.sha256_bytes(got["freeze_bytes"]), "validation_evaluation": got["validation_evaluation"],
            "implementation_sha256": rqlib.sha256_bytes(impl_bytes)}


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
    """The numerical environment of the running stage (fitting, or scoring)."""
    env = {"python": platform.python_version(), "python_implementation": platform.python_implementation(),
           "platform": platform.platform(), "machine": platform.machine(), "byteorder": sys.byteorder,
           "float_epsilon": sys.float_info.epsilon, "executable": sys.executable,
           "modules": {n: os.path.abspath(getattr(sys.modules.get(n), "__file__", "") or "") for n in TOOL_MODULES}}
    try:
        import numpy
        env["numpy"] = numpy.__version__
        env["numpy_file"] = os.path.abspath(numpy.__file__)
    except ImportError:
        env["numpy"] = None
    return env


def implementation_manifest(entry_file, modules=TOOL_MODULES):
    """The implementation that runs, as LOADED (sys.modules: an RQ_PYLIB copy is the one hashed) -> canonical
    bytes: the entry script, every tool module, the interpreter and numpy (version and its compiled core).
    Frozen as the test commitment's "evaluation script"; recomputed in-process by the evaluator."""
    mods = {}
    for name in modules:
        f = getattr(sys.modules.get(name), "__file__", None)
        if not f:
            raise StageError(f"implementation module {name} is not loaded")
        mods[name] = rqlib.sha256_file(f)
    doc = {"schema": IMPL_SCHEMA, "entry": {"name": os.path.basename(entry_file), "sha256": rqlib.sha256_file(entry_file)},
           "modules": mods, "python": {"version": platform.python_version(),
                                       "implementation": platform.python_implementation()},
           "machine": platform.machine(), "numpy": None}
    try:                                     # (imported here: the manifest never depends on import timing)
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        core = next((m for n, m in sorted(sys.modules.items()) if n.endswith("._multiarray_umath")
                     and getattr(m, "__file__", None)), None)
        doc["numpy"] = {"version": np.__version__, "core_sha256": rqlib.sha256_file(core.__file__) if core else None}
    return rqlib.canonical(doc)
