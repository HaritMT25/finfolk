#!/usr/bin/env python3
"""worlds.py: register the Red Queen study's 48 evolutionary histories and run them (design v3 §2, §13).

    worlds.py register --arena config/arena.selected.json --namespace NS --out config/worlds.json
                       [--blocks 8] [--per-block C=4,A=1,B=1] [--avoid FILE ...] [--total-steps N]
                       [--checkpoint-every N] [--log-every N] [--allow-placeholder]
    worlds.py f1 --root STUDY --binary EVO_BOIDS [--archive-root DIR] [--world ID ...]
    worlds.py launch --root STUDY --binary EVO_BOIDS [--archive-root DIR] [--workers 10]
                     [--mem-min-mb 8192] [--disk-min PATH:MB ...] [--retries 3]
                     [--on-extinction stop|continue] [--prune-local] [--retry-failed] [--poll 30]
    worlds.py verify-f1 --root STUDY [--world ID ...]
    worlds.py stitch --root STUDY --world ID
    worlds.py status --root STUDY
    worlds.py design-block --root STUDY [--archive-root DIR] --out worlds_block.json

THE REGISTRY (register; deterministic: the same inputs give the same bytes). Eight randomized
blocks of four C, one A and one B history (48 worlds; --per-block for tests). Within each block
the treatment order is a seeded permutation (namespace, "block-order", block), so a world's id
does not reveal its treatment by position. Each world has an id (w01..w48), a UUID (uuid5 of the
namespace and id), and a founder seed derived from (namespace, "founder", id), unique, and refused
if it occurs in any --avoid file (integers, or any JSON / JSONL whose keys contain "seed": the
archived plans and reservations of other streams). Its engine flags are the arena's "common"
block overlaid with its treatment's block (config/arena.selected.json, schema
finfolk.redqueen.arena/1: {"status": "selected" | "placeholder", "common": {...}, "treatments":
{"C": {...}, "A": {...}, "B": {...}}}, CLI flag name -> value, true for a bare switch). Refused:
an unresolved "SELECTED_*" value (unless --allow-placeholder, and then launch refuses the registry
too unless it is also given the flag), a positive prey or predator floor (both floors zero, §2.2),
for C anything but predator-brain + predator-economy + a positive predator-max-age, and
--predator-primer / --predator-inherit / --body-model; for B a brain; for A the economy; and any
flag this tool sets itself (seed, schedule, logging, checkpoints).

THE HISTORIES (launch: a resumable supervisor; one runner per root, flock). Every world runs as a
sequence of SEGMENTS in STUDY/worlds/<id>/: seg000 from the founder seed, and after an
interruption the next segment resumes the last GOOD checkpoint without reseeding (the random
streams continue from the checkpoint, so the history is the uninterrupted one, bit for bit, in
the serial build). Engine flags: the registry's, plus --headless (total - start), --no-render,
--log-every, --flush-every 1, --checkpoint-every, --save-checkpoint ckpt/end.json, --csv
segNNN/run.csv, --wiring-log, and for C --predator-log (its lineage log, never overwritten:
each segment has its own). A good checkpoint is one that parses and validates (ckpt.py), is at
its frame, matches its archived copy if there is one, and through whose frame every log of
its segment is complete (contiguous rows); otherwise an earlier checkpoint is used. Up to
--workers engines run at once, each in its own process group with PR_SET_PDEATHSIG = SIGKILL
(none outlives the supervisor), at nice 19, admitted only while the memory and disk guards
pass (as run.py's, fail closed). A failed segment is resumed up to --retries times in a row
without progress, then the world is "failed". STOP (STUDY/STOP) stops admission; SIGTERM stops
every engine (they resume at the next start) and exits 130.

ARCHIVE. Every complete periodic checkpoint (and F1) is copied verified into
ARCHIVE/worlds/<id>/ (a temporary file, fsync'd, hashed, read-only 0444, renamed, directory
fsync'd) and recorded in STUDY/worlds/<id>/archive.jsonl. A checkpoint rewritten by a resumed
segment must have its archived bytes (determinism; a difference stops the world as "failed").
When a world ends, its archive directory gets a FINALIZED marker and is made read-only (0555):
the contract run.py --link-sources checks. --prune-local deletes local copies of archived
checkpoints except the two latest.

BIOLOGY. A guild that reaches zero in the main CSV (prey: population; predators of C and B:
predator_pop) is recorded once in STUDY/availability.jsonl (immutable, append-only, fsync'd:
world, guild, first frame, the archived frames before it). Extinction is absorbing (both
floors are zero); --on-extinction stop (default) then ends the world as "extinct" (its valid
pre-extinction snapshots stay archived; nothing is refilled or replaced).

F1 (f1, verify-f1). F1 is the first step of an identically seeded founder replay (the same flags,
--headless 1), archived as F1.json. verify-f1 resumes it for checkpoint_every - 1 steps and
requires the result to be byte-identical to the history's archived first periodic checkpoint:
F1 then lies on the history's own trajectory.

STITCH. The logs of a world's segments joined into the uninterrupted run's logs, by the rule of
docs/evo_boids_flags.md: segment k keeps its rows with frame <= the start of segment k + 1;
segment k + 1 drops its lineage log's L rows. Corrections: the main CSV's first row of a resumed
segment carries the loaded world's history in its eight interval columns (a v0.26 convention),
so the counters of the checkpoint it resumed are subtracted; the prey wiring log's step column
is segment-relative and becomes the frame. Every log is checked contiguous. The stitched files
equal the uninterrupted run's except the main CSV's two timing columns and repro_components (a
trailing pairing window that restarts empty on a resume), as stitched/manifest.json records.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import rqlib  # noqa: E402
import run as runlib  # noqa: E402

WORLDS_SCHEMA = "finfolk.redqueen.worlds/1"
ARENA_SCHEMA = "finfolk.redqueen.arena/1"
STATE_SCHEMA = "finfolk.redqueen.worldstate/1"
AVAIL_SCHEMA = "finfolk.redqueen.availability/1"
TREATMENTS = ("C", "A", "B")
DEFAULT_SCHEDULE = {"total_steps": 200_000_000, "checkpoint_every": 1_000_000, "log_every": 5000}
# flags this tool sets itself, never taken from the arena
RESERVED = {"seed", "headless", "no-render", "log-every", "flush-every", "checkpoint-every", "save-checkpoint",
            "load-checkpoint", "csv", "name", "predator-log", "wiring-log", "reseed-after-load", "predators-from",
            "transplant-count", "transplant-seed", "transplant-out", "assay", "repro-log", "repro-log-max",
            "death-log", "cluster-map", "profile"}
FORBIDDEN_C = ("predator-primer", "predator-inherit", "body-model")
# main CSV interval columns and the checkpoint counters a resumed segment's first row must lose
INTERVAL_FIX = (("births_interval", "totalBirths"), ("deaths_interval", "totalDeaths"),
                ("kills_interval", "totalDeathsPredation"), ("deaths_starvation", "totalDeathsStarvation"),
                ("deaths_age", "totalDeathsAge"), ("predator_births_interval", "totalPredatorBirths"),
                ("predator_deaths_starv", "totalPredatorDeathsStarvation"),
                ("predator_deaths_age", "totalPredatorDeathsAge"))
NON_CONTINUABLE = ("elapsed_s", "steps_per_sec", "repro_components")
CKPT_RE = re.compile(r"^end\.(\d+)\.json$")


class WorldsError(Exception):
    pass


# ================================================================== registry
def _placeholder(v):
    return isinstance(v, str) and v.startswith("SELECTED_")


def flags_to_args(flags):
    """{"population": 600, "predator-brain": True, ...} -> ["--population", "600", "--predator-brain", ...]."""
    out = []
    for k, v in flags.items():
        if v is True:
            out.append("--" + k)
        elif v is False or v is None:
            continue
        elif isinstance(v, bool):
            continue
        elif isinstance(v, int):
            out += ["--" + k, str(v)]
        elif isinstance(v, float):
            out += ["--" + k, repr(v)]
        else:
            out += ["--" + k, str(v)]
    return out


def treatment_flags(arena, t):
    f = dict(arena.get("common") or {})
    f.update((arena.get("treatments") or {}).get(t) or {})
    return f


def arena_problems(arena, treatments_used, allow_placeholder=False):
    probs = []
    if arena.get("schema") != ARENA_SCHEMA:
        probs.append(f"arena schema {arena.get('schema')!r}, expected {ARENA_SCHEMA}")
    if arena.get("status") not in ("selected", "placeholder"):
        probs.append("arena status must be 'selected' or 'placeholder'")
    if arena.get("status") == "placeholder" and not allow_placeholder:
        probs.append("the arena is a placeholder (the sweep has not selected it): --allow-placeholder only for tests")
    for t in treatments_used:
        if t not in (arena.get("treatments") or {}):
            probs.append(f"the arena has no treatment {t}")
            continue
        f = treatment_flags(arena, t)
        for k, v in f.items():
            if k in RESERVED:
                probs.append(f"{t}: --{k} is set by worlds.py, not the arena")
            if _placeholder(v) and not allow_placeholder:
                probs.append(f"{t}: --{k} is unresolved ({v})")
        if f.get("min-pop", 0) not in (0, "0"):
            probs.append(f"{t}: the prey floor --min-pop must be 0 (design §2.2)")
        if f.get("predator-min-pop", 0) not in (0, "0"):
            probs.append(f"{t}: the predator floor --predator-min-pop must be 0 (design §2.2)")
        if t == "C":
            if f.get("predator-brain") is not True or f.get("predator-economy") is not True:
                probs.append("C: needs --predator-brain and --predator-economy")
            age = f.get("predator-max-age")
            if not (_placeholder(age) or (isinstance(age, (int, float)) and not isinstance(age, bool) and age > 0)):
                probs.append("C: needs a positive --predator-max-age (turnover under the cap)")
            for k in FORBIDDEN_C:
                if f.get(k):
                    probs.append(f"C: --{k} must stay off (design §2.1)")
        if t == "B":
            if f.get("predator-brain"):
                probs.append("B: scripted predators (no --predator-brain)")
            if f.get("predator-economy") is not True:
                probs.append("B: needs --predator-economy")
        if t == "A":
            if f.get("predator-brain") or f.get("predator-economy"):
                probs.append("A: scripted, immortal, fixed-count predators (no economy, no brain)")
            n = f.get("predators")
            if not (_placeholder(n) or (isinstance(n, int) and not isinstance(n, bool) and n > 0)):
                probs.append("A: needs a fixed positive --predators count")
    return probs


def collect_seeds(obj, out=None, key_hint=False):
    """Every integer at or below a key containing "seed" (recursively: {"seeds": {"x": 5}} counts 5)."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect_seeds(v, out, key_hint or "seed" in str(k).lower())
    elif isinstance(obj, list):
        for v in obj:
            collect_seeds(v, out, key_hint)
    elif isinstance(obj, int) and not isinstance(obj, bool) and key_hint:
        out.add(obj)
    return out


def read_avoid(path):
    """Seeds reserved elsewhere: a file of integers (one per line), a JSON document or JSONL lines."""
    text = rqlib.read_text(path)
    seeds = set()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and all(re.fullmatch(r"\d+", ln) for ln in lines):
        return {int(ln) for ln in lines}
    try:
        collect_seeds(json.loads(text), seeds)
    except ValueError:
        for ln in lines:
            collect_seeds(json.loads(ln), seeds)
    return seeds


def parse_per_block(spec):
    out = {}
    for part in spec.split(","):
        t, _, n = part.partition("=")
        if t not in TREATMENTS or not n.isdigit():
            raise WorldsError(f"--per-block {spec!r}: expected e.g. C=4,A=1,B=1")
        out[t] = int(n)
    return {t: out.get(t, 0) for t in TREATMENTS}


def register(arena_path, namespace, blocks=8, per_block=None, avoid_paths=(), schedule=None,
             allow_placeholder=False):
    per_block = per_block or {"C": 4, "A": 1, "B": 1}
    schedule = dict(DEFAULT_SCHEDULE, **(schedule or {}))
    if not namespace or not re.fullmatch(r"[A-Za-z0-9._-]+", namespace):
        raise WorldsError("--namespace: letters, digits, '.', '_' and '-'")
    s = schedule
    if s["total_steps"] % s["checkpoint_every"] or s["checkpoint_every"] % s["log_every"]:
        raise WorldsError("the schedule needs total_steps % checkpoint_every == 0 == checkpoint_every % log_every")
    raw = rqlib.read_bytes(arena_path)
    arena = json.loads(raw.decode("utf-8"))
    used = [t for t in TREATMENTS if per_block[t] > 0]
    probs = arena_problems(arena, used, allow_placeholder)
    if probs:
        raise WorldsError("arena refused: " + "; ".join(probs))
    avoid, avoid_rec = set(), []
    for p in avoid_paths:
        a = read_avoid(p)
        avoid |= a
        avoid_rec.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p), "seeds": len(a)})
    worlds, used_seeds, idx = [], set(), 0
    for b in range(1, blocks + 1):
        order = [t for t in TREATMENTS for _ in range(per_block[t])]
        rqlib.SplitMix64(rqlib.derive64(namespace, "block-order", b)).shuffle(order)
        for slot, t in enumerate(order):
            idx += 1
            wid = f"w{idx:02d}"
            k = 0
            while True:
                seed = rqlib.derive_seed(namespace, "founder", wid, *([k] if k else []))
                if seed not in used_seeds and seed not in avoid and seed != 0:
                    break
                k += 1
            used_seeds.add(seed)
            flags = treatment_flags(arena, t)
            worlds.append({
                "id": wid, "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{namespace}:{wid}")),
                "index": idx, "block": b, "slot": slot, "treatment": t, "founder_seed": seed,
                "seed_rederived": k, "flags": flags, "config_args": flags_to_args(flags) + ["--seed", str(seed)],
                "predator_log": t == "C"})
    return {"schema": WORLDS_SCHEMA, "namespace": namespace, "blocks": blocks, "per_block": per_block,
            "schedule": schedule,
            "arena": {"path": os.path.abspath(arena_path), "sha256": rqlib.sha256_bytes(raw),
                      "status": arena.get("status")},
            "avoid": avoid_rec, "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)), "worlds": worlds}


def load_registry(root, allow_placeholder=False):
    reg = rqlib.read_json(os.path.join(root, "config", "worlds.json"))
    if reg.get("schema") != WORLDS_SCHEMA:
        raise WorldsError(f"config/worlds.json schema {reg.get('schema')!r}")
    if reg["arena"]["status"] != "selected" and not allow_placeholder:
        raise WorldsError("the registry was made from a placeholder arena: --allow-placeholder only for tests")
    return reg


# ================================================================== layout
def wdir(root, wid):
    return os.path.join(root, "worlds", wid)


def adir(archive_root, wid):
    return os.path.join(archive_root, "worlds", wid)


def read_state(root, wid):
    p = os.path.join(wdir(root, wid), "state.json")
    if os.path.isfile(p):
        return rqlib.read_json(p)
    return {"schema": STATE_SCHEMA, "id": wid, "status": "pending", "segments": [], "failures": 0}


def write_state(root, wid, st):
    os.makedirs(wdir(root, wid), exist_ok=True)
    rqlib.write_json_durable(os.path.join(wdir(root, wid), "state.json"), st)


def read_jsonl(path, repair=False):
    """The records of an append-only JSONL file: every newline-terminated line must parse (a
    malformed interior line is damage: WorldsError); bytes after the last newline are a torn
    final record (an append the crash interrupted: never acknowledged), ignored, and with repair
    (under the root lock, before any further append) cut off durably."""
    if not os.path.isfile(path):
        return []
    raw = rqlib.read_bytes(path)
    cut = raw.rfind(b"\n") + 1
    out = []
    for k, ln in enumerate(raw[:cut].split(b"\n")[:-1], 1):
        try:
            out.append(json.loads(ln.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            raise WorldsError(f"{path}: line {k} is malformed (not a torn tail): repair by hand")
    if repair and cut < len(raw):
        rqlib.write_durable(path, raw[:cut])
    return out


def archive_records(root, wid, repair=False):
    """{label: record} of a world's archive.jsonl (a re-archived label keeps its first record)."""
    out = {}
    for r in read_jsonl(os.path.join(wdir(root, wid), "archive.jsonl"), repair):
        out.setdefault(r["label"], r)
    return out


def _append_durable(path, rec):
    with open(path, "ab") as f:
        f.write(rqlib.canonical(rec))
        f.flush()
        os.fsync(f.fileno())
    rqlib.fsync_dir(os.path.dirname(path))


def label_of(frame):
    return "F1" if frame == 1 else f"end.{frame}"


# ================================================================== logs
def _rows(path):
    """(header, [rows as lists]) of a CSV; a torn last line (no newline) is dropped."""
    if not os.path.isfile(path):
        return None, []
    raw = rqlib.read_text(path)
    if raw and not raw.endswith("\n"):
        raw = raw[: raw.rfind("\n") + 1]
    rows = list(csv.reader(io.StringIO(raw)))
    return (rows[0], rows[1:]) if rows else (None, [])


def _last_row(path, tail=65536):
    """(header, last complete row) of a CSV, reading only its first line and last `tail` bytes."""
    if not os.path.isfile(path):
        return None, None
    with open(path, "rb") as f:
        head = f.readline().decode("utf-8", "replace").rstrip("\n")
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail))
        data = f.read().decode("utf-8", "replace")
    lines = data.split("\n")[:-1]          # the part after the last newline is torn or empty
    if size > tail:
        lines = lines[1:]                  # the first piece may be a partial line
    hdr = next(csv.reader([head])) if head else None
    for ln in reversed(lines):
        if ln and ln != head:
            return hdr, next(csv.reader([ln]))
    return hdr, None


class Tail:
    """New complete lines of a growing file since the last call (a torn last line waits)."""

    def __init__(self, path):
        self.path, self.offset, self.header = path, 0, None

    def lines(self):
        if not os.path.isfile(self.path):
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        self.offset += cut + 1
        out = data[:cut].decode("utf-8").split("\n")
        if self.header is None and out:
            self.header = next(csv.reader([out[0]]))
            out = out[1:]
        return [next(csv.reader([ln])) for ln in out if ln]


def _contiguous_until(frames, start, step):
    """The last frame of the run start + step, start + 2 step, ... that `frames` contains in order."""
    last = start
    for f in frames:
        if f != last + step:
            break
        last = f
    return last


def segment_log_frontier(root, wid, seg, start, log_every, treatment):
    """The last frame through which every log of a segment is contiguous (main CSV, wiring, and for C
    predators.csv and pwiring; the lineage log is drained at every sample and checkpoint)."""
    d = os.path.join(wdir(root, wid), seg)
    fronts = []
    _, rows = _rows(os.path.join(d, "run.csv"))
    fronts.append(_contiguous_until([int(r[0]) for r in rows], start, log_every))
    _, rows = _rows(os.path.join(d, "run.wiring.csv"))           # segment-relative steps
    fronts.append(start + _contiguous_until([int(r[0]) for r in rows], 0, log_every))
    if treatment == "C":
        for f in ("run.predators.csv", "run.pwiring.csv"):
            _, rows = _rows(os.path.join(d, f))
            fronts.append(_contiguous_until([int(r[0]) for r in rows], start, log_every))
    return min(fronts)


# ================================================================== archive
def local_ckpts(root, wid):
    d = os.path.join(wdir(root, wid), "ckpt")
    out = {}
    for f in os.listdir(d) if os.path.isdir(d) else []:
        m = CKPT_RE.match(f)
        if m:
            out[int(m.group(1))] = os.path.join(d, f)
    return out


def archive_one(root, wid, archive_root, frame, src, log):
    """Verified copy of checkpoint `src` (at `frame`) into the archive -> its record. Raises WorldsError
    on an invalid file or on bytes that differ from an earlier archived copy of the same frame."""
    raw = rqlib.read_bytes(src)
    sha = rqlib.sha256_bytes(raw)
    cp = ckpt.loads(raw.decode("utf-8"), src)
    ckpt.validate(cp, src)
    if int(cp["world"]["frame"]) != frame:
        raise WorldsError(f"{src} is at frame {cp['world']['frame']}, not {frame}")
    lab = label_of(frame)
    recs = archive_records(root, wid)
    if lab in recs:
        if recs[lab]["sha256"] != sha:
            raise WorldsError(f"{wid} {lab}: rewritten with other bytes than its archived copy "
                              f"({sha[:12]} != {recs[lab]['sha256'][:12]}): the history is not deterministic")
        return recs[lab]
    ad = adir(archive_root, wid)
    os.makedirs(ad, exist_ok=True)
    name = "F1.json" if frame == 1 else f"end.{frame}.json"
    dst = os.path.join(ad, name)
    tmp = dst + f".tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)
    if rqlib.sha256_file(tmp) != sha:
        os.remove(tmp)
        raise WorldsError(f"{dst}: the archived copy does not hash to its source")
    os.replace(tmp, dst)
    rqlib.fsync_dir(ad)
    m = ckpt.meta(cp)
    rec = {"label": lab, "frame": frame, "sha256": sha, "bytes": len(raw), "path": os.path.abspath(dst),
           "prey": m["prey_alive"], "predators": m["predators"], "utc": rqlib.now_utc()}
    _append_durable(os.path.join(wdir(root, wid), "archive.jsonl"), rec)
    log(f"{wid}: archived {name} ({len(raw) / 1e6:.2f} MB, prey {m['prey_alive']}, predators {m['predators']})")
    return rec


def finalize_archive(root, wid, archive_root, st):
    ad = adir(archive_root, wid)
    if not os.path.isdir(ad) or os.path.isfile(os.path.join(ad, "FINALIZED")):
        return
    recs = archive_records(root, wid)
    with open(os.path.join(ad, "FINALIZED"), "wb") as f:
        f.write(rqlib.canonical({"world": wid, "status": st["status"], "frames": sorted(r["frame"] for r in recs.values()),
                                 "utc": rqlib.now_utc()}))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(os.path.join(ad, "FINALIZED"), 0o444)
    os.chmod(ad, 0o555)
    rqlib.fsync_dir(os.path.dirname(ad))


# ================================================================== engine
def segment_args(world, sched, seg, start, ckpt_path=None):
    args = ["--no-render", "--headless", str(sched["total_steps"] - start), "--log-every", str(sched["log_every"]),
            "--flush-every", "1", "--checkpoint-every", str(sched["checkpoint_every"]),
            "--save-checkpoint", "ckpt/end.json", "--csv", f"{seg}/run.csv", "--wiring-log"]
    if world["predator_log"]:
        args.append("--predator-log")
    if ckpt_path is None:
        return world["config_args"] + args
    return ["--load-checkpoint", ckpt_path] + args


def pin_binary(root, binary):
    bdir = os.path.join(root, "bin")
    os.makedirs(bdir, exist_ok=True)
    pinned = os.path.join(bdir, "evo_boids")
    want = rqlib.sha256_file(binary)
    if not os.path.exists(pinned):
        tmp = pinned + ".tmp"
        shutil.copy2(binary, tmp)
        rqlib.fsync_file(tmp)
        os.replace(tmp, pinned)
        rqlib.write_durable(pinned + ".sha256", f"{want}  {os.path.abspath(binary)}\n")
    have = rqlib.read_text(pinned + ".sha256").split()[0]
    if have != want or rqlib.sha256_file(pinned) != have:
        raise WorldsError(f"{root} runs another binary ({have[:12]}); this one is {want[:12]}")
    return pinned


def _good_copy(root, wid, f, recs):
    """A path holding a good checkpoint of frame f (it parses, validates, is at f, and matches its
    archived bytes if archived): the local copy first, else the archived one; None if neither."""
    lab = label_of(f)
    for path in [x for x in (local_ckpts(root, wid).get(f), recs.get(lab, {}).get("path")) if x]:
        try:
            raw = rqlib.read_bytes(path)
            cp = ckpt.loads(raw.decode("utf-8"), path)
            ckpt.validate(cp, path)
        except (OSError, ckpt.CheckpointError, UnicodeDecodeError, ValueError):
            continue
        if int(cp["world"]["frame"]) == f and (lab not in recs or recs[lab]["sha256"] == rqlib.sha256_bytes(raw)):
            return path
    return None


def good_resume_frame(root, wid, world, sched, st):
    """-> (the frame the next segment starts from, 0 = afresh from the founder seed; its checkpoint path):
    the latest good checkpoint at or after the last segment's start through which the last segment's
    logs are complete; else that segment's own start again."""
    segs = st["segments"]
    if not segs:
        return 0, None
    last = segs[-1]
    front = segment_log_frontier(root, wid, last["name"], last["start_frame"], sched["log_every"], world["treatment"])
    recs = archive_records(root, wid)
    cands = sorted(set(local_ckpts(root, wid)) | {r["frame"] for r in recs.values() if r["frame"] > 1}, reverse=True)
    for f in cands:
        if last["start_frame"] <= f <= front and f > 0:
            p = _good_copy(root, wid, f, recs)
            if p:
                return f, p
    if last["start_frame"] == 0:
        return 0, None
    p = _good_copy(root, wid, last["start_frame"], recs)
    if p is None:
        raise WorldsError(f"{wid}: no good checkpoint to resume from (frame {last['start_frame']} is gone or damaged)")
    return last["start_frame"], p


# ================================================================== supervisor
def launch(a, log):
    root = os.path.abspath(a.root)
    reg = load_registry(root, a.allow_placeholder)
    sched = reg["schedule"]
    archive_root = os.path.abspath(a.archive_root or os.path.join(root, "archive"))
    exe = pin_binary(root, a.binary)
    guards = runlib.disk_guards(a.disk_min, root)
    worlds = {w["id"]: w for w in reg["worlds"]}
    avail_p = os.path.join(root, "availability.jsonl")
    running = {}      # wid -> (Popen, segment name)
    tails = {}        # wid -> Tail of the running segment's main CSV
    last_frame = {}   # wid -> the last main-CSV frame seen
    extinct = {}      # wid -> the reason we stopped it
    seen = {}         # (wid, frame) -> (mtime_ns, size) of a local checkpoint already checked against its archive
    stop_reason = None
    mem_bad = 0

    def ledger():
        return read_jsonl(avail_p)

    read_jsonl(avail_p, repair=True)     # under the lock: torn final records cut before any append
    for wid in worlds:   # a previous supervisor's segments are gone (their engines died with it)
        archive_records(root, wid, repair=True)
        st = read_state(root, wid)
        if st["status"] == "running" or (st["status"] == "failed" and a.retry_failed):
            if st["status"] == "failed":
                log(f"{wid}: retrying a failed world (--retry-failed; it was: {st.get('end_reason') or st.get('error')})")
                st["failures"] = 0
            st["status"] = "interrupted"
            write_state(root, wid, st)
        for f, p in local_ckpts(root, wid).items():
            s_ = os.stat(p)
            seen[(wid, f)] = (s_.st_mtime_ns, s_.st_size)

    def terminate(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        runlib.stop_groups([p for p, _ in running.values()], log)
        for wid in list(running):
            st = read_state(root, wid)
            st["status"] = "interrupted"
            write_state(root, wid, st)
        log(f"signal {signum}: stopped {len(running)} histories (they resume at the next start)")
        sys.exit(130)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    def archive_pass(wid, alive):
        """Archive every complete, unarchived local checkpoint; check a rewritten one against its archive."""
        loc = local_ckpts(root, wid)
        recs = archive_records(root, wid)
        frames = sorted(loc)
        for f in frames:
            complete = (not alive) or f != frames[-1] or last_frame.get(wid, -1) > f
            if not complete:
                continue
            try:
                s_ = os.stat(loc[f])
            except FileNotFoundError:
                continue
            key = (s_.st_mtime_ns, s_.st_size)
            if label_of(f) in recs and seen.get((wid, f)) == key:
                continue
            archive_one(root, wid, archive_root, f, loc[f], log)   # (compares a rewritten file's bytes)
            seen[(wid, f)] = key
        if a.prune_local:
            recs = archive_records(root, wid)
            keep = set(sorted(f for f in loc if label_of(f) in recs)[-2:])
            for f, p in loc.items():
                if label_of(f) in recs and f not in keep and rqlib.sha256_file(p) == recs[label_of(f)]["sha256"]:
                    os.remove(p)
                    seen.pop((wid, f), None)

    def watch(wid):
        """New main-CSV rows of a running world: the frame reached, and a guild at zero -> (guild, frame)."""
        t = tails[wid]
        found = None
        for r in t.lines():
            fr = int(r[0])
            last_frame[wid] = fr
            row = dict(zip(t.header, r))
            for guild, col in (("prey", "population"), ("predators", "predator_pop")):
                if guild == "predators" and worlds[wid]["treatment"] == "A":
                    continue
                if int(float(row[col])) == 0:
                    if not any(e["world"] == wid and e["guild"] == guild for e in ledger()):
                        recs = archive_records(root, wid)
                        _append_durable(avail_p, {"schema": AVAIL_SCHEMA, "world": wid, "uuid": worlds[wid]["uuid"],
                                                  "treatment": worlds[wid]["treatment"], "guild": guild,
                                                  "first_zero_frame": fr, "detected_utc": rqlib.now_utc(),
                                                  "archived_frames_before": sorted(x["frame"] for x in recs.values()
                                                                                   if x["frame"] < fr)})
                        log(f"BIOLOGICAL: {wid} ({worlds[wid]['treatment']}): the {guild} reached 0 at frame {fr} "
                            "(availability ledger)")
                    found = found or (guild, fr)
        return found

    def end_world(wid, status, reason):
        st = read_state(root, wid)
        st["status"] = status
        st["end_reason"] = reason
        write_state(root, wid, st)
        if status in ("done", "extinct"):
            finalize_archive(root, wid, archive_root, st)

    while True:
        # reap the segments that ended
        for wid in list(running):
            p, seg = running[wid]
            rc = p.poll()
            if rc is None:
                continue
            del running[wid]
            ext = watch(wid)
            if ext and a.on_extinction == "stop" and wid not in extinct:   # (it ended before we could stop it)
                extinct[wid] = f"the {ext[0]} reached 0 at frame {ext[1]}"
            st = read_state(root, wid)
            st["segments"][-1].update(ended_utc=rqlib.now_utc(), rc=rc)
            write_state(root, wid, st)
            try:
                archive_pass(wid, alive=False)
            except (WorldsError, ckpt.CheckpointError, OSError, ValueError) as e:
                end_world(wid, "failed", str(e))
                log(f"FAILED {wid}: {e}")
                continue
            if wid in extinct:
                end_world(wid, "extinct", extinct.pop(wid))
                log(f"{wid}: ended as extinct ({read_state(root, wid)['end_reason']})")
            elif rc == 0 and label_of(sched["total_steps"]) in archive_records(root, wid):
                end_world(wid, "done", f"{sched['total_steps']} steps")
                log(f"{wid}: history complete ({sched['total_steps']} steps)")
            else:
                st = read_state(root, wid)
                start = st["segments"][-1]["start_frame"]
                st["failures"] = st.get("failures", 0) + 1 if st.get("last_failed_start") == start else 1
                st["last_failed_start"] = start
                st["status"] = "failed" if st["failures"] > a.retries else "interrupted"
                write_state(root, wid, st)
                log(f"{wid}: {seg} ended with exit {rc}; "
                    + ("FAILED (no progress after retries)" if st["status"] == "failed" else "it will resume"))
        # archive and watch the running ones
        for wid in list(running):
            ext = watch(wid)
            try:
                archive_pass(wid, alive=True)
            except (WorldsError, ckpt.CheckpointError, ValueError) as e:
                log(f"FAILED {wid}: {e}; stopping it")
                runlib.stop_groups([running.pop(wid)[0]], log)
                end_world(wid, "failed", str(e))
                continue
            if ext and a.on_extinction == "stop" and wid not in extinct:
                extinct[wid] = f"the {ext[0]} reached 0 at frame {ext[1]}"
                try:
                    os.killpg(running[wid][0].pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        # admission
        if os.path.exists(os.path.join(root, "STOP")) and stop_reason is None:
            stop_reason = "STOP"
            log(f"STOP file: no new segments; {len(running)} histories keep running")
        todo = [wid for wid in worlds
                if wid not in running and read_state(root, wid)["status"] in ("pending", "interrupted")]
        while stop_reason is None and todo and len(running) < a.workers:
            why = runlib.disk_problem(guards)
            if why:
                stop_reason = f"disk guard: {why}"
                log(stop_reason)
                break
            head = runlib.mem_headroom_mb()
            if head is None:
                mem_bad += 1
                if mem_bad >= 20 and not running:
                    log("memory reading unavailable with nothing running: exiting (fail closed)")
                    return 2
                break
            mem_bad = 0
            if head < a.mem_min_mb + 300:
                break
            wid = todo.pop(0)
            w = worlds[wid]
            st = read_state(root, wid)
            try:
                start, cpath = good_resume_frame(root, wid, w, sched, st)
            except WorldsError as e:
                end_world(wid, "failed", str(e))
                log(f"FAILED {wid}: {e}")
                continue
            seg = f"seg{len(st['segments']):03d}"
            d = wdir(root, wid)
            os.makedirs(os.path.join(d, seg), exist_ok=True)
            os.makedirs(os.path.join(d, "ckpt"), exist_ok=True)
            if cpath and os.path.abspath(cpath).startswith(d + os.sep):
                cpath = os.path.relpath(os.path.abspath(cpath), d)
            args = segment_args(w, sched, seg, start, cpath)
            st["segments"].append({"name": seg, "start_frame": start, "resumed_from": cpath,
                                   "started_utc": rqlib.now_utc(), "args": args})
            st["status"] = "running"
            write_state(root, wid, st)
            so = open(os.path.join(d, seg, "stdout.log"), "w")
            se = open(os.path.join(d, seg, "stderr.log"), "w")
            try:
                p = subprocess.Popen([exe] + args, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                     start_new_session=True, preexec_fn=rqlib.death_signal())
            except (OSError, subprocess.SubprocessError) as e:
                end_world(wid, "failed", f"the engine could not start: {e}")
                log(f"FAILED {wid}: the engine could not start ({e})")
                continue
            finally:
                so.close()
                se.close()
            running[wid] = (p, seg)
            tails[wid] = Tail(os.path.join(d, seg, "run.csv"))
            last_frame[wid] = start
            log(f"{wid} ({w['treatment']}): {seg} from frame {start}" + (f" ({cpath})" if cpath else " (founder seed)"))
        if not running and (stop_reason or not todo):
            break
        t_end = time.monotonic() + a.poll
        while time.monotonic() < t_end and all(p.poll() is None for p, _ in running.values()):
            time.sleep(min(0.2, a.poll))
    states = {wid: read_state(root, wid)["status"] for wid in worlds}
    counts = {s: sum(1 for v in states.values() if v == s) for s in sorted(set(states.values()))}
    log(f"supervisor exits: {counts}")
    if stop_reason:
        return 75
    return 1 if counts.get("failed") else 0


# ================================================================== F1
def f1(a, log):
    root = os.path.abspath(a.root)
    reg = load_registry(root, a.allow_placeholder)
    archive_root = os.path.abspath(a.archive_root or os.path.join(root, "archive"))
    exe = pin_binary(root, a.binary)
    sched = reg["schedule"]
    rc = 0
    for w in reg["worlds"]:
        if a.world and w["id"] not in a.world:
            continue
        d = os.path.join(wdir(root, w["id"]), "f1")
        if "F1" in archive_records(root, w["id"], repair=True):
            continue
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        args = segment_args(w, sched, "f1", 0)
        i = args.index("--headless")
        args[i + 1] = "1"
        args[args.index("--save-checkpoint") + 1] = "f1/F1.json"
        args[args.index("--csv") + 1] = "f1/f1.csv"
        with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
            r = subprocess.call([exe] + args, cwd=wdir(root, w["id"]), stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, preexec_fn=rqlib.death_signal())
        if r != 0:
            log(f"{w['id']}: the F1 replay exited {r}")
            rc = 1
            continue
        archive_one(root, w["id"], archive_root, 1, os.path.join(d, "F1.json"), log)
    return rc


def verify_f1(a, log):
    root = os.path.abspath(a.root)
    reg = load_registry(root, a.allow_placeholder)
    sched = reg["schedule"]
    exe = os.path.join(root, "bin", "evo_boids")
    first = sched["checkpoint_every"]
    rc = 0
    for w in reg["worlds"]:
        if a.world and w["id"] not in a.world:
            continue
        recs = archive_records(root, w["id"])
        if "F1" not in recs or label_of(first) not in recs:
            log(f"{w['id']}: F1 or the first checkpoint ({first}) is not archived yet")
            rc = rc or 3
            continue
        d = os.path.join(wdir(root, w["id"]), "f1verify")
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        args = ["--load-checkpoint", recs["F1"]["path"], "--no-render", "--headless", str(first - 1),
                "--log-every", str(first - 1), "--save-checkpoint", "v.json"]
        with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
            r = subprocess.call([exe] + args, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                preexec_fn=rqlib.death_signal())
        same = r == 0 and rqlib.sha256_file(os.path.join(d, "v.json")) == recs[label_of(first)]["sha256"]
        rqlib.write_json_durable(os.path.join(wdir(root, w["id"]), "f1_verify.json"), {
            "world": w["id"], "f1_sha256": recs["F1"]["sha256"], "first_checkpoint": first,
            "first_checkpoint_sha256": recs[label_of(first)]["sha256"], "engine_rc": r, "identical": same,
            "utc": rqlib.now_utc()})
        log(f"{w['id']}: F1 {'lies on' if same else 'DOES NOT lie on'} the history's trajectory "
            f"(resumed to frame {first}: {'identical' if same else 'different'})")
        if same:
            shutil.rmtree(d)
        else:
            rc = 1
    return rc


# ================================================================== stitch
def stitch(root, wid, sched, treatment):
    """Join a world's segments (see the module doc) into STUDY/worlds/<id>/stitched/ -> manifest.
    Segment k contributes its rows with frame <= the start of segment k + 1; a segment the next one
    restarted from its own start contributes nothing; a resumed segment's lineage log loses its
    L rows (the predators it loaded, already in the earlier log)."""
    st = read_state(root, wid)
    segs = st["segments"]
    if not segs:
        raise WorldsError(f"{wid}: no segments")
    d = wdir(root, wid)
    out = os.path.join(d, "stitched")
    os.makedirs(out, exist_ok=True)
    L = sched["log_every"]
    bounds = [s["start_frame"] for s in segs[1:]] + [None]
    live = [k for k, s in enumerate(segs) if bounds[k] is None or bounds[k] > s["start_frame"]]
    recs = archive_records(root, wid)
    man = {"world": wid, "files": {}}
    kinds = [("run.csv", "frame"), ("run.wiring.csv", "steps")]
    if treatment == "C":
        kinds += [("run.predators.csv", "frame"), ("run.pwiring.csv", "frame"), ("run.predlog.csv", "log")]
    for name, kind in kinds:
        header, rows_out = None, []
        for k in live:
            s, hi = segs[k], bounds[k]
            hdr, rows = _rows(os.path.join(d, s["name"], name))
            header = header or hdr
            keep = []
            for r in rows:
                if kind == "log":
                    if (hi is None or int(r[0]) <= hi) and not (s["start_frame"] > 0 and r[1] == "L"):
                        keep.append(r)
                    continue
                fr = int(r[0]) + (s["start_frame"] if kind == "steps" else 0)
                if hi is not None and fr > hi:
                    break
                keep.append([str(fr)] + r[1:] if kind == "steps" else r)
            if name == "run.csv" and s["start_frame"] > 0 and keep:
                # the resumed segment's first row counts the loaded world's history in its interval columns
                src = _good_copy(root, wid, s["start_frame"], recs)
                if src is None:
                    raise WorldsError(f"{wid}: the checkpoint segment {s['name']} resumed (frame {s['start_frame']}) is gone")
                ctr = ckpt.load(src)["counters"]
                first = list(keep[0])
                for col, key in INTERVAL_FIX:
                    i = hdr.index(col)
                    first[i] = str(int(first[i]) - int(ctr.get(key, 0)))
                keep[0] = first
            rows_out += keep
        if header is None:
            continue
        if kind != "log":
            frames = [int(r[0]) for r in rows_out]
            if frames != list(range(L, L * len(frames) + 1, L)):
                raise WorldsError(f"{wid} {name}: the stitched rows are not contiguous every {L} steps")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows_out)
        data = buf.getvalue().encode()
        rqlib.write_durable(os.path.join(out, name), data)
        man["files"][name] = {"sha256": rqlib.sha256_bytes(data), "rows": len(rows_out),
                              "last_frame": int(rows_out[-1][0]) if rows_out else None}
    man["segments"] = [{"name": s["name"], "start_frame": s["start_frame"], "kept_until": b, "used": k in live}
                       for k, (s, b) in enumerate(zip(segs, bounds))]
    man["corrections"] = {"run.csv": f"the first row of every resumed segment: {[c for c, _ in INTERVAL_FIX]} minus "
                                     "the counters of the checkpoint it resumed", "run.wiring.csv": "step -> frame"}
    man["not_continuable"] = {"run.csv": list(NON_CONTINUABLE)}
    rqlib.write_json_durable(os.path.join(out, "manifest.json"), man)
    return man


# ================================================================== design block, status
def design_block(root, archive_root):
    reg = load_registry(root, allow_placeholder=True)
    s = reg["schedule"]
    times = {"F1": 1}
    for f in range(s["checkpoint_every"], s["total_steps"] + 1, s["checkpoint_every"]):
        times[f"{f // 1_000_000}M" if f % 1_000_000 == 0 else f"f{f}"] = f
    ws = {}
    led = read_jsonl(os.path.join(root, "availability.jsonl"))
    for w in reg["worlds"]:
        ad = adir(archive_root, w["id"])
        zeros = [e["first_zero_frame"] for e in led if e["world"] == w["id"]]
        st = read_state(root, w["id"])
        ws[w["id"]] = {"uuid": w["uuid"], "treatment": w["treatment"], "block": w["block"], "status": st["status"],
                       "pattern": os.path.join(ad, "end.{frame}.json"), "paths": {"F1": os.path.join(ad, "F1.json")},
                       # snapshots at or after a guild's first zero are not valid challengers (design §2.3)
                       "valid_before": min(zeros) if zeros else None,
                       "archived": sorted(r["frame"] for r in archive_records(root, w["id"]).values())}
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": rqlib.sha256_file(
        os.path.join(root, "config", "worlds.json")), "times": times, "worlds": ws}


def status(root):
    reg = load_registry(root, allow_placeholder=True)
    out = {"root": root, "worlds": {}}
    for w in reg["worlds"]:
        st = read_state(root, w["id"])
        recs = archive_records(root, w["id"])
        last = None
        if st["segments"]:
            hdr, rows = _rows(os.path.join(wdir(root, w["id"]), st["segments"][-1]["name"], "run.csv"))
            if rows:
                r = dict(zip(hdr, rows[-1]))
                last = {k: r.get(k) for k in ("step", "population", "predator_pop", "steps_per_sec")}
        out["worlds"][w["id"]] = {"treatment": w["treatment"], "status": st["status"], "segments": len(st["segments"]),
                                  "archived": len(recs), "last_row": last}
    counts = {}
    for v in out["worlds"].values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    out["counts"] = counts
    p = os.path.join(root, "availability.jsonl")
    out["availability"] = read_jsonl(p)
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--arena", required=True)
    r.add_argument("--namespace", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--blocks", type=int, default=8)
    r.add_argument("--per-block", default="C=4,A=1,B=1")
    r.add_argument("--avoid", action="append", default=[])
    r.add_argument("--total-steps", type=int, default=DEFAULT_SCHEDULE["total_steps"])
    r.add_argument("--checkpoint-every", type=int, default=DEFAULT_SCHEDULE["checkpoint_every"])
    r.add_argument("--log-every", type=int, default=DEFAULT_SCHEDULE["log_every"])
    r.add_argument("--allow-placeholder", action="store_true")
    for name in ("f1", "launch", "verify-f1", "stitch", "status", "design-block"):
        s = sub.add_parser(name)
        s.add_argument("--root", required=True)
        s.add_argument("--allow-placeholder", action="store_true")
        s.add_argument("--archive-root")
        if name in ("f1", "launch"):
            s.add_argument("--binary", required=True)
        if name in ("f1", "verify-f1"):
            s.add_argument("--world", action="append")
        if name == "stitch":
            s.add_argument("--world", required=True)
        if name == "design-block":
            s.add_argument("--out", required=True)
        if name == "launch":
            s.add_argument("--workers", type=int, default=10)
            s.add_argument("--mem-min-mb", type=int, default=8192)
            s.add_argument("--disk-min", action="append", metavar="PATH:MB")
            s.add_argument("--retries", type=int, default=3)
            s.add_argument("--on-extinction", choices=("stop", "continue"), default="stop")
            s.add_argument("--prune-local", action="store_true")
            s.add_argument("--retry-failed", action="store_true",
                           help="put the worlds marked failed back in the queue (after the cause is fixed)")
            s.add_argument("--poll", type=float, default=30.0)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "register":
            reg = register(a.arena, a.namespace, a.blocks, parse_per_block(a.per_block), a.avoid,
                           {"total_steps": a.total_steps, "checkpoint_every": a.checkpoint_every,
                            "log_every": a.log_every}, a.allow_placeholder)
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            rqlib.write_durable(a.out, rqlib.canonical(reg))
            n = {t: sum(1 for w in reg["worlds"] if w["treatment"] == t) for t in TREATMENTS}
            print(f"registered {len(reg['worlds'])} worlds {n} in {a.blocks} blocks -> {a.out} "
                  f"(sha256 {rqlib.sha256_file(a.out)})", file=sys.stderr)
            return 0
        root = os.path.abspath(a.root)
        if a.cmd == "status":
            return status(root)
        if a.cmd == "design-block":
            blk = design_block(root, os.path.abspath(a.archive_root or os.path.join(root, "archive")))
            rqlib.write_durable(a.out, rqlib.canonical(blk))
            return 0
        if a.cmd == "stitch":
            reg = load_registry(root, a.allow_placeholder)
            w = {x["id"]: x for x in reg["worlds"]}[a.world]
            man = stitch(root, a.world, reg["schedule"], w["treatment"])
            print(json.dumps(man["files"], indent=1, sort_keys=True))
            return 0
        lock = open(os.path.join(root, ".worlds.lock"), "w")
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(f"another worlds.py holds {root}", file=sys.stderr)
            return 73
        os.nice(19 - os.nice(0))
        with open(os.path.join(root, "supervisor.log"), "a") as logf:
            def log(msg):
                line = f"{rqlib.now_utc()} {msg}"
                for o in (sys.stdout, logf):
                    try:
                        o.write(line + "\n")
                        o.flush()
                    except (OSError, ValueError):
                        pass
            if a.cmd == "f1":
                return f1(a, log)
            if a.cmd == "verify-f1":
                return verify_f1(a, log)
            return launch(a, log)
    except (WorldsError, ckpt.CheckpointError, OSError, KeyError, ValueError) as e:
        print(f"worlds.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
