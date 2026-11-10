#!/usr/bin/env python3
"""forks.py: the Red Queen study's fork branches and their common-profile plans (design v4 §10.2-10.5,
(d) item 6).

    forks.py register --study STUDY --splits config/splits.json --namespace NS [--out STUDY/config/forks.json]
                      [--origins 30000000,100000000,185000000] [--horizon 10000000] [--seeds 4]
                      [--pilot-origin 50000000] [--pilot-seeds 6] [--pilot-first 4000000] [--pilot-horizon 10000000]
    forks.py launch --study STUDY --binary EVO_BOIDS [--archive-root DIR] [--extend-pilot] [--workers 4]
                    [--mem-min-mb 8192] [--disk-min PATH:MB ...] [--retries 3] [--retry-failed] [--poll 30]
    forks.py status --study STUDY
    forks.py stitch --study STUDY --branch ID [--partial]
    forks.py profile-design --study STUDY --references refs.json --out fork_profiles.json [--with-pilot-10m]
    forks.py outcomes --study STUDY --out fork_outcomes.json

THE REGISTRY (register: STUDY/config/forks.json, schema finfolk.redqueen.forks/1; deterministic, never
replaced by other bytes). Bound to the histories' registry (config/worlds.json, its sha256) and to the
splits file (its sha256; graph.py's meta works: "split", "fork"). MAIN branches: every fork world (12:
two training, four validation, the six test C worlds) x every origin (30M, 100M, 185M) x 4 seeds, each
running `horizon` (10M) steps from its origin: 144 branches. The PILOT: one validation C world OUTSIDE
the fork set (the first by a namespace hash: independent of the main forks) at 50M with 6 seeds, held
at +4M (pilot_first) until `launch --extend-pilot` lifts the hold to +10M: the same branches continue
(a technical resume, no reseed). A branch's fork seed is derive_seed(namespace, "fork", root world
uuid, origin, k) (32 bits, refused on a collision), its uuid uuid5(URL, "finfolk:fork:<ns>:<id>"); its
flags are its root's. Origins and horizons are multiples of the histories' checkpoint interval.

THE BRANCHES (launch: STUDY/forks is the branches' supervisor root, worlds.py's Supervisor generalized:
its own lock, study.json, pinned engine (the histories' engine: the same sha256, refused otherwise),
archive root, availability ledger). A branch's ROOT segment loads its origin and reseeds once:
`--load-checkpoint origin.json --reseed-after-load SEED` (full native state; only later stochastic
streams change); its technical resumes load its own latest accepted checkpoint and never reseed.
Acceptance, archive, finalization, extinction and stitching are the histories' (worlds.py), from the
origin's frame. ORIGINS are taken only from the histories' archive: the archived checkpoint of the
origin's label, its bytes verified against its record, then frozen in STUDY/forks/worlds/<id>/
origin.json (0444, its sha256 in origin.rec.json and STUDY/forks/origins.jsonl; never replaced). A
branch whose origin is not archived yet is "waiting" (a later launch takes it up); one whose root
world reached a zero at or before the origin (the histories' supported first zeros) is "unavailable",
recorded without replacement.

COMMON PROFILES (profile-design: a design/2 fragment for plan.py: worlds, times, edges). A measured
joint state is 16 reference matchups (its prey against the 8 predator references, its predators
against the 8 prey references) plus its prey's predator-free continuation. Families: fork_branch
(every main branch at +1M, +4M and +10M), fork_original (every fork world's ORIGINAL continuation at
+1M and +4M), native_panel (all 32 C worlds at the three primary target times, origin + 10M: it
includes the fork roots' original continuations at the primary horizon, never measured twice),
pilot_branch / pilot_original (+1M, +4M; +10M with --with-pilot-10m). Roles: a branch's or world's
split (training / validation / test); the pilot's "diagnostic". No (prey, predators) pair is listed
twice (a repeat is measured once, its first family kept; "deduplicated" counts them). AVAILABILITY
(Annex H D6 rule 27, §§10.1-10.4): a scheduled state that will never exist is OMITTED EXPLICITLY, never
emitted as a path to an absent future: a branch whose origin is unavailable or which was invalidated,
or a branch or history whose supported first zero (either guild; the branches' and the histories' own
ledgers) is at or before the target; each omission ("omitted": family, state, its 17 pairs, why) is
recorded without replacement. A state not reached yet is not absent.

OUTCOMES (outcomes, read-only): every branch's own absorbing ecological outcome from its origin,
independent of any profile's availability: its origin status, first zeros, verified acceptance
frontier, and at +1M / +4M / +10M alive, predator_extinct, prey_terminal (prey first: the predators'
later status unobserved), not_yet_observed, technical or unavailable_origin, counted per kind x split.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import run as runlib  # noqa: E402
import worlds  # noqa: E402

SCHEMA = "finfolk.redqueen.forks/1"
PROFILE_SCHEMA = "finfolk.redqueen.forkprofiles/1"
ORIGIN_SCHEMA = "finfolk.redqueen.forkorigin/1"
ORIGINS = (30_000_000, 100_000_000, 185_000_000)
HORIZON = 10_000_000
SEEDS = 4
PILOT = {"origin": 50_000_000, "seeds": 6, "first": 4_000_000, "horizon": 10_000_000}
SHORT = (1_000_000, 4_000_000)                 # the secondary measurement horizons (§10.2)
ROLE = {"train": "training", "val": "validation", "test": "test",
        "training": "training", "validation": "validation"}


class ForkError(Exception):
    pass


class OriginRaced(ForkError):
    """The root restarted between the admission and the copy: nothing frozen; the branch waits."""


def froot(study):
    return os.path.join(study, "forks")


def m_label(frame):
    return f"{frame // 1_000_000}M" if frame % 1_000_000 == 0 else str(frame)


# ================================================================== registry
def register(study, splits_path, ns, origins=ORIGINS, horizon=HORIZON, seeds=SEEDS, pilot=None, avoid_paths=()):
    wpath = os.path.join(study, "config", "worlds.json")
    hreg = rqlib.read_json(wpath)
    # reserved seeds: the histories' founder seeds and every --avoid input (worlds.read_avoid: integers,
    # or any JSON / JSONL whose keys contain "seed": archived plans, reservations)
    reserved = {int(w["founder_seed"]): f"the founder seed of history {w['id']}" for w in hreg["worlds"]
                if isinstance(w.get("founder_seed"), int)}
    for slot in hreg.get("reserved") or []:             # (every history reservation: restart seeds, unused slots)
        for k, x in enumerate(slot.get("seeds") or []):
            reserved.setdefault(int(x), f"history seed slot {slot.get('slot')} attempt {k}")
    avoid_rec = []
    for ap_ in avoid_paths:
        got = worlds.read_avoid(ap_)
        for x in got:
            reserved.setdefault(int(x), f"a seed reserved in {ap_}")
        avoid_rec.append({"path": os.path.abspath(ap_), "sha256": rqlib.sha256_file(ap_), "seeds": len(got)})
    sp = rqlib.read_json(splits_path)
    split, fork = sp.get("split") or {}, list(sp.get("fork") or [])
    by = {w["id"]: w for w in hreg["worlds"]}
    ce = hreg["schedule"]["checkpoint_every"]
    pilot = dict(PILOT, **(pilot or {}))
    for x in list(origins) + [horizon, pilot["origin"], pilot["first"], pilot["horizon"]]:
        if x <= 0 or x % ce:
            raise ForkError(f"{x}: origins and horizons are positive multiples of the checkpoint interval {ce}")
    if not 0 < pilot["first"] <= pilot["horizon"]:
        raise ForkError("the pilot's first horizon is within its horizon")
    for wid in fork:
        if wid not in by or by[wid]["treatment"] != "C":
            raise ForkError(f"fork world {wid} is not a C world of {wpath}")
        if split.get(wid) not in ROLE:
            raise ForkError(f"fork world {wid} has no split")
    if len(set(fork)) != len(fork):
        raise ForkError("a fork world is listed twice")
    pool = sorted((w for w in by if by[w]["treatment"] == "C" and split.get(w) in ("val", "validation")
                   and w not in fork), key=lambda w: rqlib.sha256_bytes(f"{ns}|pilot|{w}".encode()))
    out, seen = [], {}

    def branch(kind, wid, origin, k, total, hold=None):
        root = by[wid]
        bid = f"{wid}.o{m_label(origin)}.s{k}" if kind == "main" else f"{wid}.p{m_label(origin)}.s{k}"
        seed = rqlib.derive_seed(ns, "fork", root["uuid"], origin, k)
        if seed in seen:
            raise ForkError(f"fork seeds of {seen[seed]} and {bid} collide: change the namespace")
        if seed in reserved:
            raise ForkError(f"the fork seed of {bid} ({seed}) is {reserved[seed]}: change the namespace")
        seen[seed] = bid
        b = {"id": bid, "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:fork:{ns}:{bid}")), "kind": kind,
             "root": wid, "root_uuid": root["uuid"], "split": ROLE[split[wid]] if kind == "main" else "diagnostic",
             "treatment": root["treatment"], "block": root.get("block"), "flags": root["flags"],
             "predator_log": root["predator_log"], "config_args": None,
             "origin": {"frame": origin, "label": worlds.label_of(origin), "seed": seed, "k": k},
             "total_steps": origin + total}
        if hold is not None:
            b["hold_at"] = origin + hold
        out.append(b)
    for wid in sorted(fork):
        for origin in origins:
            for k in range(seeds):
                branch("main", wid, origin, k, horizon)
    if pool:
        for k in range(pilot["seeds"]):
            branch("pilot", pool[0], pilot["origin"], k, pilot["horizon"], pilot["first"])
    return {"schema": SCHEMA, "namespace": ns,
            "worlds_registry": {"path": "config/worlds.json", "sha256": rqlib.sha256_file(wpath)},
            "splits": {"path": os.path.abspath(splits_path), "sha256": rqlib.sha256_file(splits_path)},
            "schedule": {"total_steps": max([b["total_steps"] for b in out] or [0]), "checkpoint_every": ce,
                         "log_every": hreg["schedule"]["log_every"]},
            "origins": list(origins), "horizon": horizon, "seeds": seeds,
            "pilot": dict(pilot, world=pool[0] if pool else None), "fork_worlds": sorted(fork),
            "native_panel": sorted(w for w in by if by[w]["treatment"] == "C"),
            "split": {w: ROLE[s] for w, s in sorted(split.items()) if s in ROLE},
            "holdout": {k: ROLE[v] for k, v in sorted((sp.get("holdout") or {}).items()) if v in ROLE},
            "avoid": avoid_rec, "worlds": out}


def load_forks(study):
    p = os.path.join(study, "config", "forks.json")
    raw = rqlib.read_bytes(p)
    reg = json.loads(raw)
    if reg.get("schema") != SCHEMA:
        raise ForkError(f"{p}: schema {reg.get('schema')!r}")
    have = rqlib.sha256_file(os.path.join(study, reg["worlds_registry"]["path"]))
    if have != reg["worlds_registry"]["sha256"]:
        raise ForkError(f"{p} was registered against another config/worlds.json ({have[:12]} now)")
    return reg, rqlib.sha256_bytes(raw)


# ================================================================== origins
def zero_before(study, b):
    """Why the branch's root is extinct at or before its origin (None if not): the histories' supported
    first zeros, the ledger read NOW."""
    root, f = b["root"], b["origin"]["frame"]
    led = worlds.read_jsonl(os.path.join(study, "availability.jsonl"))
    early = sorted((fz, g) for g, fz in worlds.first_zeros(led, root, study).items() if fz <= f)
    if early:
        return f"its root {root}'s {early[0][1]} reached 0 at frame {early[0][0]}, at or before the origin"
    return None


def record_invalid(b, rec):
    """Why this EXACT archive record (or frozen record) is not a valid fork origin (None if it is): no
    prey, or (C and B) no predators."""
    if rec is not None and (rec.get("prey") == 0 or (b["treatment"] != "A" and rec.get("predators") == 0)):
        return (f"the archived origin {b['origin']['label']} of {b['root']} holds {rec.get('prey')} prey and "
                f"{rec.get('predators')} predators")
    return None


def origin_invalid(study, b, frozen_rec=None):
    """Why an ADMITTED branch's origin is no longer valid on the current evidence (None if it is): the
    guild counts of the record it froze (origin.rec.json), then the ledger read now."""
    return record_invalid(b, frozen_rec) or zero_before(study, b)


def branch_invalid(study, b):
    """origin_invalid for an admitted branch, with the record it froze (an origin.rec.json written before
    the guild counts were recorded falls back to the archive's record); an origin frozen from a root
    attempt that was since restarted (a discarded attempt) is invalid."""
    rp = os.path.join(worlds.wdir(froot(study), b["id"]), "origin.rec.json")
    frec = rqlib.read_json(rp) if os.path.isfile(rp) else None
    if frec is not None:
        cur = worlds.attempt_of(study, b["root"])
        if int(frec.get("root_attempt", 0)) != cur:
            return (f"its origin was frozen from attempt {frec.get('root_attempt', 0)} of {b['root']}, a discarded "
                    f"attempt (the root restarted: attempt {cur})")
    if frec is not None and "prey" not in frec:
        frec = worlds.archive_records(study, b["root"]).get(b["origin"]["label"])
    return origin_invalid(study, b, frec)


def root_registry(study):
    return rqlib.read_json(os.path.join(study, "config", "worlds.json"))


def origin_status(study, b):
    """-> ("available", archive record) | ("waiting", why) | ("unavailable", why). A root whose current
    attempt may still be REPLACED by the burn-in rule is waiting (its early zeros decide nothing:
    worlds.burn_in_decided). The archive record is fetched ONCE, and that exact record is the one checked
    (its guild counts, its bytes) and frozen; the availability ledger is read AFTER it was obtained."""
    root = b["root"]
    att = worlds.attempt_of(study, root)            # (read BEFORE anything else: the attempt admitted)
    decided, why = worlds.burn_in_decided(study, root_registry(study), root)
    if not decided:
        return "waiting", f"its root {root}: {why} (it may still be restarted)"
    rec = worlds.archive_records(study, root).get(b["origin"]["label"])
    if rec is not None:
        why = record_invalid(b, rec)
        if why:
            return "unavailable", why
        if not os.path.isfile(rec["path"]) or rqlib.sha256_file(rec["path"]) != rec["sha256"]:
            return "waiting", f"the archived {b['origin']['label']} of {root} does not verify (repaired by its supervisor first)"
        rec = dict(rec, root_attempt=att)
    why = zero_before(study, b)                 # (read now, after the record was obtained)
    if why:
        return "unavailable", why
    if rec is None:
        st = worlds.read_state(study, root)
        if st["status"] in ("done", "extinct"):
            return "unavailable", f"its root {root} ended ({st['status']}) without archiving {b['origin']['label']}"
        return "waiting", f"its root {root} has not archived {b['origin']['label']} yet ({st['status']})"
    return "available", rec


def freeze_origin(fr, b, rec):
    """The branch's frozen, verified copy of its origin (once; never replaced) -> (path, sha256)."""
    d = worlds.wdir(fr, b["id"])
    worlds.mkdirs_durable(d)
    p, rp = os.path.join(d, "origin.json"), os.path.join(d, "origin.rec.json")
    if os.path.isfile(rp):
        r = rqlib.read_json(rp)
        if not (os.path.isfile(p) and rqlib.sha256_file(p) == r["sha256"]):
            raise ForkError(f"{b['id']}: its frozen origin {p} is missing or changed")
        if r["sha256"] != rec["sha256"]:
            raise ForkError(f"{b['id']}: the histories' archived origin changed since it was frozen")
        return p, r["sha256"]
    att = rec.get("root_attempt")
    if att is None:                                 # (bound to the attempt admitted: origin_status)
        att = worlds.attempt_of(os.path.dirname(fr), b["root"])
    raw = rqlib.read_bytes(rec["path"])
    if rqlib.sha256_bytes(raw) != rec["sha256"]:
        raise ForkError(f"{b['id']}: the archived origin does not hash to its record")
    tmp = p + ".tmp"
    if os.path.exists(tmp):
        os.chmod(tmp, 0o644)
        os.remove(tmp)
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)
    if worlds.attempt_of(os.path.dirname(fr), b["root"]) != att:    # (a restart during the copy)
        os.chmod(tmp, 0o644)
        os.remove(tmp)
        raise OriginRaced(f"{b['id']}: its root {b['root']} restarted while the origin was copied (attempt {att} "
                          "was admitted): not frozen")
    os.replace(tmp, p)
    rqlib.fsync_dir(d)
    r = {"schema": ORIGIN_SCHEMA, "branch": b["id"], "root": b["root"], "label": b["origin"]["label"],
         "frame": b["origin"]["frame"], "sha256": rec["sha256"], "source": rec["path"], "prey": rec.get("prey"),
         "predators": rec.get("predators"), "root_attempt": att, "utc": rqlib.now_utc()}
    rqlib.write_json_durable(rp, r)
    return p, rec["sha256"]


def verify_frozen(fr, bid):
    """The branch's frozen origin against its durable digest (origin.rec.json) -> (path, sha256), or
    None if it was never frozen; ForkError if the file is missing or its bytes changed."""
    d = worlds.wdir(fr, bid)
    p, rp = os.path.join(d, "origin.json"), os.path.join(d, "origin.rec.json")
    if not os.path.isfile(rp):
        return None
    sha = rqlib.read_json(rp)["sha256"]
    if not os.path.isfile(p) or rqlib.sha256_file(p) != sha:
        raise ForkError(f"{bid}: its frozen origin {p} does not match its recorded digest {sha[:12]}")
    return p, sha


def refresh_origins(study, reg, log):
    """Under the fork lock, before anything runs: the origins ledger's torn tail repaired; every
    branch's frozen origin verified against its digest (a mismatch fails the branch, whatever its
    state); every pending / waiting branch's origin admitted (frozen), left waiting or recorded
    unavailable from the CURRENT evidence; an admitted branch whose origin newly turns out to lie at or
    after its root's extinction (or to hold an empty guild) is INVALIDATED (its artifacts kept, the
    invalidation recorded); the ledger reconciled with the branch states idempotently (an event
    missing after a crash between the two writes is appended) -> the runtime registry."""
    fr = froot(study)
    lp = os.path.join(fr, "origins.jsonl")
    events = worlds.read_jsonl(lp, repair=True)
    have = {(e.get("branch"), e.get("status")) for e in events}

    def record(bid, status, **kw):
        if (bid, status) not in have:
            worlds._append_durable(lp, dict({"branch": bid, "status": status, "utc": rqlib.now_utc()}, **kw))
            have.add((bid, status))
    out = []
    for b in reg["worlds"]:
        bid = b["id"]
        st = worlds.read_state(fr, bid)
        fresh = not os.path.isfile(os.path.join(worlds.wdir(fr, bid), "state.json"))
        changed = False
        try:
            frozen = verify_frozen(fr, bid)
        except ForkError as e:
            frozen, changed = None, True
            if st["status"] not in ("failed", "unavailable", "invalidated"):
                st = dict(st, status="failed", end_reason=str(e))
                worlds.write_state(fr, bid, st)
                log(f"{bid}: FAILED: {e}")
            record(bid, "origin_changed", reason=str(e))
        if st["status"] in ("pending", "waiting"):
            kind, info = origin_status(study, b)
            if kind == "available":
                try:
                    path, sha = freeze_origin(fr, b, info)
                except OriginRaced as e:
                    log(f"{bid}: {e}; it waits")
                    kind, info = "waiting", str(e)
                else:
                    frozen = (path, sha)
                    if st["status"] == "waiting" or fresh:
                        st = dict(st, status="pending")
                        worlds.write_state(fr, bid, st)
            if kind == "available":
                pass
            elif kind == "unavailable":
                st = dict(st, status="unavailable", end_reason=info)
                worlds.write_state(fr, bid, st)
                log(f"{bid}: UNAVAILABLE ({info}); recorded, not replaced")
            elif st["status"] != "waiting":
                st = dict(st, status="waiting", end_reason=info)
                worlds.write_state(fr, bid, st)
        elif st["status"] not in ("unavailable", "invalidated") and not changed:
            # every admitted branch that may still run, a FAILED one included (--retry-failed resumes it)
            info = branch_invalid(study, b)
            if info:
                st = dict(st, status="invalidated", end_reason=info, invalidated_from=st["status"])
                worlds.write_state(fr, bid, st)
                log(f"{bid}: INVALIDATED ({info}); its artifacts are kept")
        # the ledger follows the durable states (idempotent)
        if frozen:
            record(bid, "available", sha256=frozen[1])
        if st["status"] in ("unavailable", "invalidated"):
            record(bid, st["status"], reason=st.get("end_reason"))
        rw = json.loads(json.dumps(b))
        if frozen:
            rw["origin"].update(local=frozen[0], sha256=frozen[1])
        out.append(rw)
    return dict(reg, worlds=out)


# ================================================================== commands
def launch(a, log):
    study = os.path.abspath(a.study)
    fr = froot(study)
    reg, sha = load_forks(study)
    ar = worlds.bind_root(fr, sha, a.archive_root, create=True)
    exe, exe_sha = worlds.pin_binary(fr, a.binary)
    hs = os.path.join(study, "bin", "evo_boids.sha256")
    if not os.path.isfile(hs) or rqlib.read_text(hs).split()[0] != exe_sha:
        raise ForkError("the branches run the histories' pinned engine (the same sha256); this one differs")
    runtime = refresh_origins(study, reg, log)
    sup = worlds.Supervisor(fr, runtime, ar, exe, exe_sha, a, log)
    if not a.extend_pilot:
        sup.hold = {b["id"]: b["hold_at"] for b in reg["worlds"] if b.get("hold_at")}
    byid = {b["id"]: b for b in reg["worlds"]}
    sup.ineligible = lambda wid: branch_invalid(study, byid[wid])     # before every segment, every retry
    sup.guards = runlib.disk_guards(a.disk_min, fr)
    rc = sup.run()
    refresh_origins(study, reg, log)            # (the ledger records what the run invalidated)
    n = {}
    for b in reg["worlds"]:
        s = worlds.read_state(fr, b["id"])["status"]
        n[s] = n.get(s, 0) + 1
    log(f"branches: {n}")
    return rc


def runtime_registry(study):
    reg, _ = load_forks(study)
    fr = froot(study)
    out = []
    for b in reg["worlds"]:
        rw = json.loads(json.dumps(b))
        rp = os.path.join(worlds.wdir(fr, b["id"]), "origin.rec.json")
        if os.path.isfile(rp):
            rw["origin"].update(local=os.path.join(worlds.wdir(fr, b["id"]), "origin.json"),
                                sha256=rqlib.read_json(rp)["sha256"])
        out.append(rw)
    return dict(reg, worlds=out)


def status(study):
    reg = runtime_registry(study)
    fr = froot(study)
    out = {"branches": {}, "counts": {}}
    for b in reg["worlds"]:
        st = worlds.read_state(fr, b["id"])
        acc = [r["frame"] for r in worlds.accept_records(fr, b["id"])]
        out["branches"][b["id"]] = {"status": st["status"], "reason": st.get("end_reason"), "origin": b["origin"]["frame"],
                                    "accepted_through": max(acc) if acc else None, "segments": len(st["segments"])}
        out["counts"][st["status"]] = out["counts"].get(st["status"], 0) + 1
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


RANK = {"diagnostic": -1, "training": 0, "validation": 1, "test": 2}
PILOT_FAMILIES = ("pilot_branch", "pilot_original")


def merge_role(a, b):
    """The role a pair measured once must carry when two profiles need it: the most held-out (test >
    validation > training > diagnostic)."""
    return a if RANK[a] >= RANK[b] else b


OUTCOMES_SCHEMA = "finfolk.redqueen.forkoutcomes/2"
BRANCH_AT = worlds.AT_HORIZON + ("invalidated", "pending_origin", "unavailable_origin")


def _ledgers(study):
    """The histories' and the branches' availability ledgers, read once."""
    return (worlds.read_jsonl(os.path.join(study, "availability.jsonl")),
            worlds.read_jsonl(os.path.join(froot(study), "availability.jsonl")))


def evidence_ctx(study):
    """What every evidence-bound decision below reads ONCE (the registries, both availability ledgers, the restart
    records) and the caches of each world's evidence sequence."""
    fr = froot(study)
    hreg = root_registry(study)
    led_h, led_f = _ledgers(study)
    return {"study": study, "fr": fr, "hreg": hreg, "reg": runtime_registry(study),
            "hworlds": {w["id"]: w for w in hreg["worlds"]}, "led_h": led_h, "led_f": led_f,
            "restarts": worlds.restart_records(study), "hist": {}, "branch": {}}


def history_evidence(ctx, wid):
    """A history's RETAINED attempt under the rule-24 evidence sequence (worlds.attempt_sequence / attempt_outcome
    over evidence.py: the newest line of descent, validated rows, the first absorbing terminal boundary; Codex
    #78 r1 P1) and its burn-in disposition (worlds.disposition) -> {"attempt", "outcome" (None: recorded, not
    installed), "decided", "why", "disposition", "first_terminal" (its frame or None)}."""
    if wid in ctx["hist"]:
        return ctx["hist"][wid]
    study, hreg = ctx["study"], ctx["hreg"]
    w, sched = ctx["hworlds"][wid], hreg["schedule"]
    idx, _, _ = worlds.attempt_index(study, wid, ctx["restarts"])
    k = max(idx)
    d, _ = idx[k]
    bi, maxr = worlds.burn_in_of(hreg), int(hreg.get("max_restarts") or 0)
    o = None
    if d:
        seq = worlds.attempt_sequence(study, wid, d, w, k, ctx["led_h"], sched["log_every"])
        o = worlds.attempt_outcome(seq, w, worlds.total_steps(w, sched), bi)
    decided, why, disp = worlds.disposition(o, k, maxr, bi)
    ft = o["first_terminal"]["frame"] if o and o["first_terminal"] else None
    ctx["hist"][wid] = rec = {"attempt": k, "outcome": o, "decided": decided, "why": why, "disposition": disp,
                              "first_terminal": ft}
    return rec


def branch_evidence(ctx, b):
    """A branch's evidence-bound outcome (worlds.attempt_outcome over its own segments from its origin, its own
    ledger; a branch never restarts; its refill baseline, the origin's counter, is unchecked)."""
    if b["id"] not in ctx["branch"]:
        fr = ctx["fr"]
        d = worlds.wdir(fr, b["id"])
        seq = worlds.attempt_sequence(fr, b["id"], d if os.path.isdir(d) else None, b, 0, ctx["led_f"],
                                      ctx["reg"]["schedule"]["log_every"])
        ctx["branch"][b["id"]] = worlds.attempt_outcome(seq, b, int(b["total_steps"]), 0)
    return ctx["branch"][b["id"]]


def origin_disposition(ctx, b):
    """(state, why) of a branch's origin on its ROOT's rule-24 evidence, in this order (Codex #78 r1 P2-2, P2-3):
    invalidated (the branch's state says so, or its origin was frozen from a discarded root attempt: rejected
    before any outcome is classified); pending (the root's retained attempt is not settled: it may still be
    restarted, so nothing is decided and every scheduled target is kept); unavailable (the root's evidenced
    first terminal boundary at or before the origin, the frozen record holds no prey / predators, or the root
    reached its registered end before the origin: recorded, never replaced); technical (the branch's state says
    unavailable, but the root's evidence does not support it: repair it); available."""
    fr = ctx["fr"]
    st = worlds.read_state(fr, b["id"])
    if st["status"] == "invalidated":
        return "invalidated", f"the branch is invalidated ({st.get('end_reason')})"
    h = history_evidence(ctx, b["root"])
    rp = os.path.join(worlds.wdir(fr, b["id"]), "origin.rec.json")
    frec = rqlib.read_json(rp) if os.path.isfile(rp) else None
    if frec is not None and int(frec.get("root_attempt", 0)) != h["attempt"]:
        return "invalidated", (f"its origin was frozen from attempt {frec.get('root_attempt', 0)} of {b['root']}, a "
                               f"discarded attempt (attempt {h['attempt']} is retained)")
    if not h["decided"]:
        return "pending", f"its root {b['root']}: {h['why']} (it may still be restarted: nothing is decided)"
    o, f = h["outcome"], b["origin"]["frame"]
    if h["first_terminal"] is not None and h["first_terminal"] <= f:
        return "unavailable", (f"its root {b['root']}'s evidenced first terminal boundary (frame {h['first_terminal']}) "
                               "is at or before the origin")
    why = record_invalid(b, frec)
    if why:
        return "unavailable", why
    if o and o["observation"] == "administrative" and o["frontier"] < f:
        return "unavailable", f"its root {b['root']} reached its registered end (frame {o['frontier']}) before the origin"
    if st["status"] == "unavailable":
        return "technical", (f"its state says unavailable ({st.get('end_reason')}), but its root's evidence does not "
                             "support it: repair it")
    return "available", None


def absent(ctx, branches, wid, frame):
    """(cause, why) when the joint state (wid, frame) will never exist (Annex H D6 rule 27, §§10.1-10.4: profiles
    stop at the biological boundary; an unavailable origin is recorded without replacement), else None, on the
    rule-24 evidence: a branch that is invalidated or whose origin is unavailable (origin_disposition); a branch or
    history whose evidenced first terminal boundary is at or before the frame. A root or history whose retained
    attempt is NOT settled decides nothing (Codex #78 r1 P2-2): its states stay scheduled, as does a state merely
    not reached yet."""
    if wid in branches:
        s, why = origin_disposition(ctx, branches[wid])
        if s == "pending":
            return None
        if s == "invalidated":
            return "technical", f"the branch is invalidated: {why}"
        if s == "technical":
            return "technical", f"the branch is technically unavailable: {why}"
        if s == "unavailable":
            return "unavailable_origin", f"an unavailable origin: {why}"
        o = branch_evidence(ctx, branches[wid])
    else:
        h = history_evidence(ctx, wid)
        if not h["decided"]:
            return None
        o = h["outcome"]
    ft = (o or {}).get("first_terminal")
    if ft and ft["frame"] <= frame:
        return "biological", (f"biological: {wid}'s first terminal boundary ({ft['kind']}) at frame {ft['frame']}, at "
                              f"or before the target {frame}")
    return None


def profile_design(study, refs, with_pilot_10m=False):
    """The common-profile measurements as a design/2 fragment (worlds, times, edges): see the module doc.
    refs: {"prey": [8 entries], "predators": [8 entries]}, an entry {"world", "frame"} for a main
    history, or {"world", "frame", "uuid", "archive"} for an external (sentinel) reference: its own UUID
    and the directory holding its checkpoints (end.<frame>.json, F1.json). Each guild needs 8 DISTINCT
    snapshots. An edge's role is its most held-out endpoint (test before validation before training;
    a training world's snapshot holdout counts; an external reference is training); the pilot's
    families are diagnostic unless an endpoint outside the pilot is validation or test. A repeated pair
    is measured once with the most held-out role it is required in (diagnostic below training)."""
    reg = runtime_registry(study)
    hist_ar = rqlib.read_json(os.path.join(study, "study.json"))["archive_root"]
    fr = froot(study)
    fork_ar = rqlib.read_json(os.path.join(fr, "study.json"))["archive_root"] if os.path.isfile(
        os.path.join(fr, "study.json")) else os.path.join(fr, "archive")
    hreg = rqlib.read_json(os.path.join(study, "config", "worlds.json"))
    huuid = {w["id"]: w["uuid"] for w in hreg["worlds"]}
    branch_role = {b["id"]: b["split"] for b in reg["worlds"]}
    pilot_ids = {b["id"] for b in reg["worlds"] if b["kind"] == "pilot"} | (
        {reg["pilot"]["world"]} if reg["pilot"].get("world") else set())    # (diagnostic in pilot families only)
    wmap, times, pairs, dup, external = {}, {}, {}, [0], set()
    ctx = evidence_ctx(study)
    led_h, led_f = ctx["led_h"], ctx["led_f"]
    omitted = []

    def world(wid, uid, ad):
        w = {"uuid": uid, "pattern": os.path.join(ad, "end.{frame}.json"), "paths": {"F1": os.path.join(ad, "F1.json")}}
        if wid in wmap and wmap[wid] != w:
            raise ForkError(f"world {wid} is defined twice with another identity ({wmap[wid]['uuid']} / {uid})")
        for other, x in wmap.items():
            if other != wid and x["uuid"] == uid:
                raise ForkError(f"the UUID {uid} names two worlds ({other}, {wid})")
        wmap[wid] = w
        return wid

    def t(frame):
        frame = int(frame)
        lab = "F1" if frame == 1 else f"f{frame}"
        times[lab] = frame
        return lab

    def ref(r):
        wid, frame = r["world"], int(r["frame"])
        if wid in huuid:
            if r.get("uuid") not in (None, huuid[wid]) or r.get("archive") not in (
                    None, os.path.join(hist_ar, "worlds", wid)):
                raise ForkError(f"reference {wid}: its UUID / archive conflict with the history of that id")
            return world(wid, huuid[wid], os.path.join(hist_ar, "worlds", wid)), t(frame)
        if not (r.get("uuid") and r.get("archive")):
            raise ForkError(f"reference {wid} is not a main history: give its uuid and archive directory")
        external.add(wid)
        return world(wid, r["uuid"], r["archive"]), t(frame)
    for guild in ("prey", "predators"):
        lst = refs.get(guild) or []
        ids = {(huuid.get(r.get("world"), r.get("uuid")), int(r.get("frame", -1))) for r in lst}
        if len(lst) != 8 or len(ids) != 8:
            raise ForkError(f"the reference panel is 8 DISTINCT {guild} snapshots ({len(ids)} distinct of {len(lst)})")
    rp = [ref(r) for r in refs["prey"]]
    rq = [ref(r) for r in refs["predators"]]

    def endpoint_role(wid, lab):
        if wid in branch_role:
            return branch_role[wid]
        if wid in external:
            return "training"
        role = reg["split"].get(wid, "training")
        frame = times[lab]
        tix = 0 if frame == 1 else frame // 1_000_000
        if role == "training" and frame % 1_000_000 in (0, 1):
            role = reg.get("holdout", {}).get(f"{wid}:{tix}", "training")
        return role

    def add(family, prey, pred):
        ends = [prey] + ([pred] if pred else [])
        if family in PILOT_FAMILIES:           # declared diagnostic, unless an endpoint outside the pilot is held out
            outside = [endpoint_role(*e) for e in ends if e[0] not in pilot_ids]
            outside = [r for r in outside if r in ("validation", "test")]
            role = max(outside, key=RANK.__getitem__) if outside else "diagnostic"
        else:
            role = max((endpoint_role(*e) for e in ends), key=RANK.__getitem__)
        key = (prey, pred)
        if key in pairs:                       # measured once, with the most held-out role it is needed in
            dup[0] += 1
            pairs[key]["role"] = merge_role(pairs[key]["role"], role)
            return
        pairs[key] = {"family": family, "role": role, "prey": {"world": prey[0], "time": prey[1]},
                      "predators": None if pred is None else {"world": pred[0], "time": pred[1]}}

    bdict = {b["id"]: b for b in reg["worlds"]}

    def state(family, wid, frame):
        ab = absent(ctx, bdict, wid, frame)
        if ab:                                 # (an explicit omission: never a path to an absent state)
            omitted.append({"family": family, "state": {"world": wid, "frame": int(frame)}, "pairs": 17,
                            "cause": ab[0], "why": ab[1]})
            return
        lab = t(frame)
        for pw, pt in rq:                      # its prey against the 8 predator references
            add(family, (wid, lab), (pw, pt))
        for qw, qt in rp:                      # the 8 prey references against its predators
            add(family, (qw, qt), (wid, lab))
        add(family, (wid, lab), None)          # its prey's predator-free continuation
    H = reg["horizon"]
    for b in reg["worlds"]:
        world(b["id"], b["uuid"], os.path.join(fork_ar, "worlds", b["id"]))
        o = b["origin"]["frame"]
        if b["kind"] == "main":
            for h in SHORT + (H,):
                state("fork_branch", b["id"], o + h)
        else:
            for h in SHORT + ((reg["pilot"]["horizon"],) if with_pilot_10m else ()):
                state("pilot_branch", b["id"], o + h)
    for wid in reg["fork_worlds"]:                  # original continuations, the short horizons
        world(wid, huuid[wid], os.path.join(hist_ar, "worlds", wid))
        for o in reg["origins"]:
            for h in SHORT:
                state("fork_original", wid, o + h)
    pw_ = reg["pilot"].get("world")
    if pw_:
        world(pw_, huuid[pw_], os.path.join(hist_ar, "worlds", pw_))
        for h in SHORT + ((reg["pilot"]["horizon"],) if with_pilot_10m else ()):
            state("pilot_original", pw_, reg["pilot"]["origin"] + h)
    for wid in reg["native_panel"]:                 # the primary target times (fork roots included, once)
        world(wid, huuid[wid], os.path.join(hist_ar, "worlds", wid))
        for o in reg["origins"]:
            state("native_panel", wid, o + H)
    edges = list(pairs.values())
    return {"schema": PROFILE_SCHEMA, "forks_sha256": rqlib.sha256_file(os.path.join(study, "config", "forks.json")),
            "worlds": wmap, "times": dict(sorted(times.items(), key=lambda kv: kv[1])), "edges": edges,
            "counts": {f: sum(1 for e in edges if e["family"] == f) for f in sorted({e["family"] for e in edges})},
            "roles": {r: sum(1 for e in edges if e["role"] == r) for r in sorted({e["role"] for e in edges})},
            "deduplicated": dup[0],
            # (D6 rule 27: the scheduled states that will never exist, each with its cause; not replaced)
            "omitted": omitted,
            "omitted_counts": {f: sum(1 for o in omitted if o["family"] == f) for f in sorted({o["family"] for o in omitted})},
            "ledgers": {"histories_records": len(led_h), "branches_records": len(led_f)}}


def outcomes(study, horizons=None):
    """THE BRANCHES' ECOLOGICAL OUTCOMES (Annex H D6 rule 27, §§10.1-10.4), independent of any profile's
    availability: every registered branch, its origin's disposition, its evidenced first zero of each guild and
    first terminal boundary, its frontier and accepted-through, the evidence's hashes and unsupported ledger
    entries, and at each horizon (origin + 1M, 4M, 10M) one of BRANCH_AT: alive / predator_extinct /
    prey_terminal (the prey first: later predator status unobserved) / not_yet_observed / technical /
    invalidated / pending_origin / unavailable_origin; with counts per kind x split x horizon. Read-only.
    (Codex #78 r1 P1, P2-3) Every outcome comes from the RULE-24 EVIDENCE SEQUENCE (branch_evidence: the newest
    line of descent, validated rows, the first absorbing terminal; a ledger zero outside it is listed as
    unsupported, never an extinction), after the origin's disposition (origin_disposition): an invalidated
    branch is "invalidated" and a technically unavailable one "technical" before anything else, an unsettled root
    "pending_origin", an unavailable origin "unavailable_origin"; a done / extinct state its evidence does not
    support is technical (worlds.at_horizon)."""
    ctx = evidence_ctx(study)
    reg = ctx["reg"]
    hz = list(horizons or (SHORT + (reg["horizon"],)))
    rows, counts = {}, {}
    pre = {"invalidated": "invalidated", "pending": "pending_origin", "unavailable": "unavailable_origin",
           "technical": "technical"}
    for b in reg["worlds"]:
        bid, o = b["id"], b["origin"]["frame"]
        s, why = origin_disposition(ctx, b)
        ob = branch_evidence(ctx, b)
        h_ = history_evidence(ctx, b["root"])
        at = {}
        for h in hz:
            s_ = pre.get(s) or worlds.at_horizon(ob, o + h)
            at[str(h)] = s_
            c = counts.setdefault(b["kind"], {}).setdefault(b["split"], {}).setdefault(str(h), {})
            c[s_] = c.get(s_, 0) + 1
        rows[bid] = {"root": b["root"], "kind": b["kind"], "split": b["split"], "origin": o,
                     "origin_state": s, "origin_why": why, "root_attempt": h_["attempt"],
                     "root_disposition": h_["disposition"], "status": ob["status"], "reason": ob["end_reason"],
                     "first_zeros": {g: z["frame"] for g, z in sorted(ob["events"].items()) if isinstance(z, dict)},
                     "first_terminal": ob["first_terminal"], "frontier": ob["frontier"],
                     "accepted_through": ob["accepted_through"], "observation": ob["observation"],
                     "integrity": ob["integrity"], "unsupported_ledger": ob["unsupported_ledger"],
                     "evidence": ob["evidence"], "at": at}
    return {"schema": OUTCOMES_SCHEMA, "forks_sha256": rqlib.sha256_file(os.path.join(study, "config", "forks.json")),
            "horizons": hz, "kinds": list(BRANCH_AT), "branches": rows, "counts": counts,
            "evidence_sha256": rqlib.sha256_file(os.path.abspath(worlds.evidence.__file__)),
            "note": "each branch has its own absorbing ecological outcome from its origin (D6 rule 27, §§10.1-10.4), from "
                    "the rule-24 evidence sequence; an unavailable origin is recorded, never replaced; an unsettled "
                    "root decides nothing; profile availability does not enter"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--study", required=True)
    r.add_argument("--splits", required=True)
    r.add_argument("--namespace", required=True)
    r.add_argument("--out")
    r.add_argument("--origins", default=",".join(str(x) for x in ORIGINS))
    r.add_argument("--horizon", type=int, default=HORIZON)
    r.add_argument("--seeds", type=int, default=SEEDS)
    r.add_argument("--pilot-origin", type=int, default=PILOT["origin"])
    r.add_argument("--pilot-seeds", type=int, default=PILOT["seeds"])
    r.add_argument("--pilot-first", type=int, default=PILOT["first"])
    r.add_argument("--pilot-horizon", type=int, default=PILOT["horizon"])
    r.add_argument("--avoid", action="append", default=[], metavar="FILE",
                   help="reserved seeds (integers, or JSON / JSONL with seed keys); the founder seeds always")
    for name in ("launch", "status", "stitch", "profile-design", "outcomes"):
        s = sub.add_parser(name)
        s.add_argument("--study", required=True)
        if name == "launch":
            s.add_argument("--binary", required=True)
            s.add_argument("--archive-root")
            s.add_argument("--extend-pilot", action="store_true", help="lift the pilot's +4M hold: continue to +10M")
            s.add_argument("--workers", type=int, default=4)
            s.add_argument("--mem-min-mb", type=int, default=8192)
            s.add_argument("--disk-min", action="append", metavar="PATH:MB")
            s.add_argument("--retries", type=int, default=3)
            s.add_argument("--on-extinction", choices=("stop", "continue"), default="stop")
            s.add_argument("--prune-local", action="store_true")
            s.add_argument("--retry-failed", action="store_true")
            s.add_argument("--poll", type=float, default=30.0)
        if name == "stitch":
            s.add_argument("--branch", required=True)
            s.add_argument("--partial", action="store_true")
        if name == "profile-design":
            s.add_argument("--references", required=True)
            s.add_argument("--out", required=True)
            s.add_argument("--with-pilot-10m", action="store_true")
        if name == "outcomes":
            s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        study = os.path.abspath(a.study)
        if a.cmd == "register":
            reg = register(study, a.splits, a.namespace, [int(x) for x in a.origins.split(",")], a.horizon, a.seeds,
                           {"origin": a.pilot_origin, "seeds": a.pilot_seeds, "first": a.pilot_first,
                            "horizon": a.pilot_horizon}, a.avoid)
            out = a.out or os.path.join(study, "config", "forks.json")
            new = worlds.write_registry(out, rqlib.canonical(reg))
            print(f"registered {len(reg['worlds'])} branches -> {out} ({'written' if new else 'unchanged'}; "
                  f"sha256 {rqlib.sha256_file(out)})", file=sys.stderr)
            return 0
        if a.cmd == "status":
            return status(study)
        if a.cmd == "stitch":
            man = worlds.stitch(froot(study), a.branch, runtime_registry(study), a.partial)
            print(json.dumps(man["files"], indent=1, sort_keys=True))
            return 0
        if a.cmd == "profile-design":
            out = profile_design(study, rqlib.read_json(a.references), a.with_pilot_10m)
            rqlib.write_durable(a.out, rqlib.canonical(out))
            print(json.dumps(out["counts"]) + (f"; omitted {out['omitted_counts']}" if out["omitted"] else ""),
                  file=sys.stderr)
            return 0
        if a.cmd == "outcomes":
            out = outcomes(study)
            rqlib.write_durable(a.out, rqlib.canonical(out))
            print(json.dumps(out["counts"], sort_keys=True), file=sys.stderr)
            return 0
        fr = froot(study)
        worlds.mkdirs_durable(fr)
        lock = worlds._flock(os.path.join(fr, ".worlds.lock"))
        os.nice(19 - os.nice(0))
        with lock, open(os.path.join(fr, "supervisor.log"), "a") as logf:
            def log(msg):
                line = f"{rqlib.now_utc()} {msg}"
                for o in (sys.stdout, logf):
                    try:
                        o.write(line + "\n")
                        o.flush()
                    except (OSError, ValueError):
                        pass
            return launch(a, log)
    except (ForkError, worlds.WorldsError, OSError, KeyError, ValueError) as e:
        print(f"forks.py {a.cmd}: {e}", file=sys.stderr)
        return 73 if isinstance(e, worlds.WorldsError) and "another worlds.py holds" in str(e) else 2


if __name__ == "__main__":
    sys.exit(main())
