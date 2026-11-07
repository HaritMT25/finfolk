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
twice (a repeat is measured once, its first family kept; "deduplicated" counts them).
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


def froot(study):
    return os.path.join(study, "forks")


def m_label(frame):
    return f"{frame // 1_000_000}M" if frame % 1_000_000 == 0 else str(frame)


# ================================================================== registry
def register(study, splits_path, ns, origins=ORIGINS, horizon=HORIZON, seeds=SEEDS, pilot=None):
    wpath = os.path.join(study, "config", "worlds.json")
    hreg = rqlib.read_json(wpath)
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
            "worlds": out}


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
def origin_status(study, b, ledger=None):
    """-> ("available", archive record) | ("waiting", why) | ("unavailable", why) for a branch's origin
    in the histories' archive (its bytes verified against the record)."""
    root, f = b["root"], b["origin"]["frame"]
    led = worlds.read_jsonl(os.path.join(study, "availability.jsonl")) if ledger is None else ledger
    zeros = worlds.first_zeros(led, root, study)
    early = sorted((fz, g) for g, fz in zeros.items() if fz <= f)
    if early:
        return "unavailable", f"its root {root}'s {early[0][1]} reached 0 at frame {early[0][0]}, at or before the origin"
    rec = worlds.archive_records(study, root).get(b["origin"]["label"])
    st = worlds.read_state(study, root)
    if rec is None:
        if st["status"] in ("done", "extinct"):
            return "unavailable", f"its root {root} ended ({st['status']}) without archiving {b['origin']['label']}"
        return "waiting", f"its root {root} has not archived {b['origin']['label']} yet ({st['status']})"
    if not os.path.isfile(rec["path"]) or rqlib.sha256_file(rec["path"]) != rec["sha256"]:
        return "waiting", f"the archived {b['origin']['label']} of {root} does not verify (repaired by its supervisor first)"
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
    os.replace(tmp, p)
    rqlib.fsync_dir(d)
    r = {"schema": ORIGIN_SCHEMA, "branch": b["id"], "root": b["root"], "label": b["origin"]["label"],
         "frame": b["origin"]["frame"], "sha256": rec["sha256"], "source": rec["path"], "utc": rqlib.now_utc()}
    rqlib.write_json_durable(rp, r)
    return p, rec["sha256"]


def refresh_origins(study, reg, log):
    """Every pending / waiting branch's origin: frozen (pending), still waiting, or unavailable
    (recorded in forks/origins.jsonl) -> the runtime registry (the branches with their frozen origins)."""
    fr = froot(study)
    led = worlds.read_jsonl(os.path.join(study, "availability.jsonl"))
    out = []
    for b in reg["worlds"]:
        st = worlds.read_state(fr, b["id"])
        if st["status"] in ("pending", "waiting"):
            kind, info = origin_status(study, b, led)
            if kind == "available":
                path, sha = freeze_origin(fr, b, info)
                if st["status"] == "waiting" or not os.path.isfile(os.path.join(worlds.wdir(fr, b["id"]), "state.json")):
                    worlds._append_durable(os.path.join(fr, "origins.jsonl"), {
                        "branch": b["id"], "status": "available", "sha256": sha, "utc": rqlib.now_utc()})
                    worlds.write_state(fr, b["id"], dict(st, status="pending"))
            elif kind == "unavailable":
                worlds.write_state(fr, b["id"], dict(st, status="unavailable", end_reason=info))
                worlds._append_durable(os.path.join(fr, "origins.jsonl"), {
                    "branch": b["id"], "status": "unavailable", "reason": info, "utc": rqlib.now_utc()})
                log(f"{b['id']}: UNAVAILABLE ({info}); recorded, not replaced")
            elif st["status"] != "waiting":
                worlds.write_state(fr, b["id"], dict(st, status="waiting", end_reason=info))
        rw = json.loads(json.dumps(b))
        rp = os.path.join(worlds.wdir(fr, b["id"]), "origin.rec.json")
        if os.path.isfile(rp):
            rw["origin"].update(local=os.path.join(worlds.wdir(fr, b["id"]), "origin.json"),
                                sha256=rqlib.read_json(rp)["sha256"])
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
    sup.guards = runlib.disk_guards(a.disk_min, fr)
    rc = sup.run()
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


def profile_design(study, refs, with_pilot_10m=False):
    """The common-profile measurements as a design/2 fragment (worlds, times, edges): see the module doc."""
    reg = runtime_registry(study)
    hist_ar = rqlib.read_json(os.path.join(study, "study.json"))["archive_root"]
    fr = froot(study)
    fork_ar = rqlib.read_json(os.path.join(fr, "study.json"))["archive_root"] if os.path.isfile(
        os.path.join(fr, "study.json")) else os.path.join(fr, "archive")
    hreg = rqlib.read_json(os.path.join(study, "config", "worlds.json"))
    huuid = {w["id"]: w["uuid"] for w in hreg["worlds"]}
    wmap, times, edges, seen, dup = {}, {}, [], set(), [0]

    def world(wid, uid, ar):
        if wid not in wmap:
            ad = os.path.join(ar, "worlds", wid)
            wmap[wid] = {"uuid": uid, "pattern": os.path.join(ad, "end.{frame}.json"),
                         "paths": {"F1": os.path.join(ad, "F1.json")}}
        return wid

    def t(frame):
        lab = f"f{frame}"
        times[lab] = frame
        return lab

    if len(refs.get("prey") or []) != 8 or len(refs.get("predators") or []) != 8:
        raise ForkError("the reference panel is 8 prey and 8 predator snapshots")
    rp = [(world(r["world"], huuid[r["world"]], hist_ar), t(int(r["frame"]))) for r in refs["prey"]]
    rq = [(world(r["world"], huuid[r["world"]], hist_ar), t(int(r["frame"]))) for r in refs["predators"]]

    def state(family, role, wid, frame):
        lab = t(frame)
        for pw, pt in rq:                      # its prey against the 8 predator references
            add(family, role, (wid, lab), (pw, pt))
        for qw, qt in rp:                      # the 8 prey references against its predators
            add(family, role, (qw, qt), (wid, lab))
        add(family, role, (wid, lab), None)    # its prey's predator-free continuation

    def add(family, role, prey, pred):
        key = (prey, pred)
        if key in seen:                        # (measured once: e.g. a reference snapshot inside a panel state)
            dup[0] += 1
            return
        seen.add(key)
        edges.append({"family": family, "role": role, "prey": {"world": prey[0], "time": prey[1]},
                      "predators": None if pred is None else {"world": pred[0], "time": pred[1]}})
    H = reg["horizon"]
    for b in reg["worlds"]:
        world(b["id"], b["uuid"], fork_ar)
        o = b["origin"]["frame"]
        if b["kind"] == "main":
            for h in SHORT + (H,):
                state("fork_branch", b["split"], b["id"], o + h)
        else:
            for h in SHORT + ((reg["pilot"]["horizon"],) if with_pilot_10m else ()):
                state("pilot_branch", "diagnostic", b["id"], o + h)
    for wid in reg["fork_worlds"]:                  # original continuations, the short horizons
        world(wid, huuid[wid], hist_ar)
        for o in reg["origins"]:
            for h in SHORT:
                state("fork_original", reg["split"][wid], wid, o + h)
    pw_ = reg["pilot"].get("world")
    if pw_:
        world(pw_, huuid[pw_], hist_ar)
        for h in SHORT + ((reg["pilot"]["horizon"],) if with_pilot_10m else ()):
            state("pilot_original", "diagnostic", pw_, reg["pilot"]["origin"] + h)
    for wid in reg["native_panel"]:                 # the primary target times (fork roots included, once)
        world(wid, huuid[wid], hist_ar)
        for o in reg["origins"]:
            state("native_panel", reg["split"].get(wid, "training"), wid, o + H)
    return {"schema": PROFILE_SCHEMA, "forks_sha256": rqlib.sha256_file(os.path.join(study, "config", "forks.json")),
            "worlds": wmap, "times": dict(sorted(times.items(), key=lambda kv: kv[1])), "edges": edges,
            "counts": {f: sum(1 for e in edges if e["family"] == f) for f in sorted({e["family"] for e in edges})},
            "deduplicated": dup[0]}


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
    for name in ("launch", "status", "stitch", "profile-design"):
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
    a = ap.parse_args(argv)
    try:
        study = os.path.abspath(a.study)
        if a.cmd == "register":
            reg = register(study, a.splits, a.namespace, [int(x) for x in a.origins.split(",")], a.horizon, a.seeds,
                           {"origin": a.pilot_origin, "seeds": a.pilot_seeds, "first": a.pilot_first,
                            "horizon": a.pilot_horizon})
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
            print(json.dumps(out["counts"]), file=sys.stderr)
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
