#!/usr/bin/env python3
"""runlib.py: validate one job's outputs against its plan entry, and write
its completed manifest (only after the process succeeded and its outputs
validated), atomically.

    python3 tools/alife2027/runlib.py finalize JOBJSON JOBDIR BUILD_MANIFEST STATUS ATTEMPT
    python3 tools/alife2027/runlib.py verify JOBDIR          (a completed job's outputs still hash as recorded)

Validation is against what the plan says the job must produce (`expect`),
never against whichever files exist: row schedules, fingerprint counts,
monotone counters, population and food accounting, CSV / diagnostics
agreement, branch checks, the run's own status, and its arm settings.
Ecological failures (rescue, low population, no sweep) are valid outcomes.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys

FAKE_KIND = "fake"   # runner tests: jobs whose `expect` lists files only


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_rows(path):
    with open(path, newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(io.StringIO("".join(lines))))


def schedule(steps, every, with_zero):
    s = list(range(every, steps + 1, every))
    if not s or s[-1] != steps:
        s.append(steps)
    return ([0] if with_zero else []) + s


class Invalid(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise Invalid(msg)


def validate_job(job, jdir):
    """Raises Invalid on the first problem; returns the list of output files."""
    e = job["expect"]
    P = os.path.join(jdir, job["prefix"])
    if job.get("kind") == FAKE_KIND:
        files = [os.path.join(jdir, f) for f in e["files"]]
        for f in files:
            need(os.path.exists(f), f"missing {f}")
        return files
    files = []

    def exists(suffix):
        p = P + suffix
        need(os.path.exists(p), f"missing {p}")
        files.append(p)
        return p

    steps, every = e["steps"], e["every"]
    # run info (the driver's own manifest)
    info = json.load(open(exists(".run.json")))
    need(info["result"]["status"] == 0, f"run status {info['result']['status']}")
    need(info["seed"] == job["seed"] and info["arm"] == job["arm"], "run.json seed / arm differ from the plan")
    for k, v in e["arm"].items():
        need(info["arm_settings"][k] == v, f"arm setting {k} = {info['arm_settings'][k]}, plan {v}")
    need(info["build"]["NUM_SENSES"] == 64 and info["build"]["eye_build"], "not the 64-sense eye build")
    need(info["steps"] == steps and info["result"]["final_step"] == steps, "steps differ")
    res = json.load(open(exists(".resolved.json")))
    need(res["effective"]["ocean"]["eye"] == e["arm"]["eye"] and res["effective"]["ocean"]["eyeCode"] == e["arm"]["eyeCode"],
         "resolved effective config disagrees with the arm")
    for k, v in job["cfg"].items():   # every frozen key took the frozen value
        sec = "sim" if k in res["init"]["sim"] else "ocean" if k in res["init"]["ocean"] else None
        need(sec is not None, f"config key {k} not in the resolved config")
        got = res["init"][sec][k]
        need(got == v or (isinstance(v, (int, float)) and not isinstance(v, bool) and got is not None
                          and abs(float(got) - float(v)) <= 1e-6 * max(1.0, abs(float(v)))),
             f"config {k}: resolved {got}, frozen {v}")
    # the interval CSV
    rows = read_csv_rows(exists(".csv"))
    need([int(r["step"]) for r in rows] == schedule(steps, every, False), "CSV rows off schedule")
    need(all(int(r["seed"]) == job["seed"] and r["arm"] == job["arm"] for r in rows), "CSV seed / arm column")
    # diagnostics
    drows = read_csv_rows(exists(".diag.csv"))
    need([int(r["step"]) for r in drows] == schedule(steps, every, True), "diag rows off schedule")
    founders = int(drows[0]["pop"])
    prev = None
    for r in drows:
        g = {k: int(v) for k, v in r.items()}
        need(g["diag_steps"] == g["step"], f"diag observed {g['diag_steps']} steps at {g['step']}")
        need(g["pop"] == founders + g["births"] + g["reseeds"] - g["deaths"], f"population accounting at {g['step']}")
        need(g["deaths"] == g["deaths_pred"] + g["deaths_starve"] + g["deaths_age"], f"death causes at {g['step']}")
        need(g["food_identity_bad"] == 0 and g["food_expiry_bad"] == 0, f"food identity at {g['step']}")
        need(g["nonfinite_removed"] == 0, f"non-finite removed at {g['step']}")
        need(g["min_pop"] <= g["pop"] and g["min_pop_pre_floor"] <= g["min_pop"], f"minimum population at {g['step']}")
        need((g["first_reseed_step"] < 0) == (g["reseeds"] == 0), f"first reseed vs reseeds at {g['step']}")
        if prev:
            for k in ("births", "deaths", "reseeds", "reseed_steps", "auc_pop", "food_eaten", "food_expired",
                      "food_arrivals", "pred_births", "pred_reseeds"):
                need(g[k] >= prev[k], f"{k} decreased at {g['step']}")
            need(g["min_pop"] <= prev["min_pop"], f"min_pop rose at {g['step']}")
        prev = g
    dby = {int(r["step"]): r for r in drows}
    eaten = 0
    for r in rows:
        s = int(r["step"])
        eaten += int(r["food_eaten_int"])
        need(int(r["births"]) == int(dby[s]["births"]) and int(r["reseeds"]) == int(dby[s]["reseeds"]) and
             int(r["pop"]) == int(dby[s]["pop"]), f"CSV and diag disagree at {s}")
        need(eaten == int(dby[s]["food_eaten"]), f"summed interval intake != diag food_eaten at {s}")
    # fingerprints
    fp = open(exists(".fp.txt")).read().splitlines()
    fsteps = [int(ln.split()[1]) for ln in fp if ln.startswith("fp ")]
    need(fsteps == schedule(steps, e["fp_every"], True), "fingerprint lines off schedule")
    summ = [ln for ln in fp if ln.startswith("fp_summary")]
    need(len(summ) == 1, "no fingerprint summary")
    kv = dict(x.split("=", 1) for x in summ[0].split()[1:])
    want_obs = steps + 1 if e["fp"] == "dense" else len(fsteps)
    need(kv["mode"] == e["fp"] and int(kv["observed"]) == want_obs, f"fingerprint mode / observed {kv}")
    need(int(kv["nonfinite_max"]) == 0, "non-finite state")
    if e["fp"] == "dense":
        need(all(" chain=" in ln for ln in fp if ln.startswith("fp ")), "dense lines without chain")
    # behavioural tests
    for suffix in [ "_behav.csv"] + [f"_behav_{s}.csv" for s in e["behav_at"]]:
        b = read_csv_rows(exists(suffix))
        need([r["genomes"] for r in b] == ["evolved", "random"], f"behav rows in {suffix}")
    # wiring
    if e["wiring"]:
        wl = open(exists(".wiring.csv")).read().splitlines()
        snaps = sorted({int(ln.split(",")[1]) for ln in wl if ln.startswith("S,")})
        want = schedule(steps, e["wiring"]["every"], True) if e["wiring"]["every"] else [steps]
        need(snaps == want, f"wiring snapshots {snaps[:3]}..., want {want[:3]}...")
        for s in want:
            whos = [ln.split(",")[2] for ln in wl if ln.startswith(f"S,{s},")]
            need(whos == ["evolved", "random"], f"wiring summary rows at {s}")
        if not e["wiring"]["paths"]:   # (with paths, a population may still have no eye path at all)
            need(not any(ln.startswith("P,") for ln in wl), "path rows in a no-paths wiring dump")
    # encounters
    if e["encounters"]:
        er = read_csv_rows(exists(".enc.csv"))
        need([int(r["step"]) for r in er] == schedule(e["encounters"]["until"], e["encounters"]["every"], False),
             "encounter rows off schedule")
        need(sum(int(r["steps"]) for r in er) == e["encounters"]["until"], "encounter steps")
        u = e["encounters"]["until"]
        if u in dby:
            need(sum(int(r["births"]) for r in er) == int(dby[u]["births"]), "encounter births != diag births")
    # branches
    if e["branches"]:
        bp = exists(".branches.csv")
        files.append(bp + ".fp.txt")
        need(os.path.exists(bp + ".fp.txt"), "missing branch fingerprints")
        txt = open(bp).read().splitlines()
        brows = read_csv_rows(bp)
        names = [s.split(":")[0] for s in e["branch_spec"].split(";") if s]
        need([(int(r["checkpoint"]), r["branch"]) for r in brows] == [(c, n) for c in e["branches"] for n in names],
             "branch rows")
        for r in brows:
            need(int(r["food_identity_bad"]) == 0 and int(r["food_expiry_bad"]) == 0 and int(r["nonfinite"]) == 0,
                 f"branch {r['branch']}@{r['checkpoint']}: identity / finite")
            need(int(r["food_end"]) == int(r["food0"]) + int(r["food_arrivals"]) - int(r["eaten"]) - int(r["food_expired"]),
                 f"branch {r['branch']}@{r['checkpoint']}: food identity over the continuation")
            need(int(r["steps"]) == e["branch_steps"], "branch steps")
        checks = [ln for ln in txt if ln.startswith("# check ")]
        for c in e["branches"]:
            need(f"# check parent_restored checkpoint={c} ok" in checks, f"parent not restored at {c}")
            sham = [ln for ln in checks if ln.startswith(f"# check sham_identity checkpoint={c} ")]
            for ln in sham:
                ok = ln.endswith(" ok") or (ln.endswith("does)") and c + e["branch_steps"] > steps)
                need(ok, f"sham identity: {ln}")
        need("# check food_identity bad=0 ok" in checks, "branch food identity")
    return files


def parse_time(path):
    """/usr/bin/time -v output -> a few numbers (None when absent)."""
    out = {}
    if not os.path.exists(path):
        return out
    t = open(path).read()
    m = re.search(r"Elapsed \(wall clock\) time.*: (?:(\d+):)?(\d+):([\d.]+)", t)
    if m:
        h = int(m.group(1) or 0)
        out["elapsed_s"] = h * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for key, pat in (("user_s", r"User time \(seconds\): ([\d.]+)"), ("system_s", r"System time \(seconds\): ([\d.]+)"),
                     ("max_rss_kb", r"Maximum resident set size \(kbytes\): (\d+)")):
        m = re.search(pat, t)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return out


def finalize(job, jdir, build_manifest, status, attempt):
    if status != 0:
        raise Invalid(f"process exit status {status}")
    files = validate_job(job, jdir)
    for extra in (".stdout.log", ".stderr.log", ".time.txt"):
        p = os.path.join(jdir, job["prefix"] + extra)
        if os.path.exists(p):
            files.append(p)
    bm = json.load(open(build_manifest))
    run_info = None
    rj = os.path.join(jdir, job["prefix"] + ".run.json")
    if os.path.exists(rj):
        run_info = json.load(open(rj))
    man = {
        "schema": "finfolk.alife2027.manifest/1",
        "job": job,
        "attempt": attempt,
        "finished_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build": {"manifest_sha256": sha256(build_manifest), "executable_sha256": bm["executable"]["sha256"],
                  "git_commit": bm["git"]["commit"], "source_inventory": bm["source_inventory"]["hash"]},
        "process": {"exit_status": status, **parse_time(os.path.join(jdir, job["prefix"] + ".time.txt"))},
        "run_info": run_info,
        "outputs": {os.path.relpath(f, jdir): sha256(f) for f in sorted(set(files))},
        "validation": "ok",
    }
    path = os.path.join(jdir, job["prefix"] + ".manifest.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return man


def verify(jdir, prefix):
    man = json.load(open(os.path.join(jdir, prefix + ".manifest.json")))
    bad = [p for p, h in man["outputs"].items() if not os.path.exists(os.path.join(jdir, p)) or sha256(os.path.join(jdir, p)) != h]
    if bad:
        raise Invalid("outputs changed since completion: " + ", ".join(bad))
    return man


def main():
    a = sys.argv
    try:
        if len(a) == 7 and a[1] == "finalize":
            job = json.loads(open(a[2]).read())
            man = finalize(job, a[3], a[4], int(a[5]), int(a[6]))
            print(f"validated {job['id']}: {len(man['outputs'])} outputs, "
                  f"{man['process'].get('elapsed_s', float('nan')):.1f} s")
            return 0
        if len(a) == 4 and a[1] == "verify":
            verify(a[2], a[3])
            print("ok")
            return 0
    except Invalid as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
