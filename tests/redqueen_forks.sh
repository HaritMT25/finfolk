#!/usr/bin/env bash
# redqueen_forks.sh — tools/redqueen/forks.py end to end against the real engine (serial build), on
# tiny worlds (200 prey, 24,000 steps, a checkpoint every 4,000), plus its unit tests.
#
#   tests/redqueen_forks.sh PATH/TO/evo_boids WORKDIR        (env: PYTHON, default python3)
#
#   1. two C histories run to the end (one a fork world, one the pilot's validation world);
#   2. register: 2 main origins (8,000 archived; 28,000 past the histories' end: unavailable,
#      recorded, never replaced) x 2 seeds, and a 2-seed pilot at 12,000 held at +4,000;
#   3. launch with every branch engine SIGKILLed after its first checkpoint: each branch resumes
#      (a technical resume: no reseed) and its archived checkpoints are byte-identical to an
#      uninterrupted run of `--load-checkpoint origin --reseed-after-load SEED`; its stitched lineage,
#      predator and wiring logs equal that run's; the two seeds and the original continuation differ;
#      the frozen origin is the histories' archived checkpoint; the pilot is held (not finalized);
#   4. --extend-pilot: the pilot continues to +8,000 from its hold, byte-identical to an
#      uninterrupted run; the profile design lists every measured state once.
set -uo pipefail
BIN=$(readlink -f "${1:?usage: redqueen_forks.sh EVO_BOIDS WORKDIR}")
W=$(readlink -m "${2:?usage: redqueen_forks.sh EVO_BOIDS WORKDIR}")
T=$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/redqueen" && pwd)
PY="${PYTHON:-python3} -I"
WS="$PY $T/worlds.py"
FK="$PY $T/forks.py"
[ -d "$W" ] && chmod -R u+w "$W" 2> /dev/null
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
GUARD="--mem-min-mb 50 --disk-min $W:200 --poll 0.2"
$PY -W error::ResourceWarning "$T/test_forks.py" > unit.log 2>&1 || { tail -30 unit.log; fail "unit tests"; }
grep -q ResourceWarning unit.log && fail "the unit tests leak file handles"

cat > arena.json <<'JSON'
{"schema": "finfolk.redqueen.arena/1", "status": "selected",
 "common": {"population": 200, "min-pop": 0, "predator-min-pop": 0, "max-pop": 250, "target-food": 800,
            "food-spawn": 3, "food-amp": 2, "food-patches": 0, "current": 0, "move-cost": 0, "gene-cost": 0},
 "treatments": {
  "C": {"predators": 6, "predator-economy": true, "predator-brain": true, "predator-max-pop": 12,
        "predator-max-age": 40, "predator-meal": 20, "predator-cooldown": 1.5},
  "A": {"predators": 3, "predator-cooldown": 1.5},
  "B": {"predators": 6, "predator-economy": true, "predator-max-pop": 12, "predator-max-age": 40,
        "predator-meal": 20, "predator-cooldown": 1.5}}}
JSON

# 1. two C histories
$WS register --arena arena.json --namespace rq-test-forks --blocks 1 --per-block C=2 --total-steps 24000 --burn-in 0 \
    --checkpoint-every 4000 --log-every 100 --out R/config/worlds.json 2> /dev/null || fail "register"
$WS f1 --root R --binary "$BIN" > rf1.log 2>&1 || fail "f1: $(tail -3 rf1.log)"
$WS launch --root R --binary "$BIN" --workers 2 --on-extinction continue $GUARD > r.log 2>&1 || fail "launch: $(tail -3 r.log)"
read CW1 CW2 < <($PY -c 'import json; print(*sorted(w["id"] for w in json.load(open("R/config/worlds.json"))["worlds"]))')
echo "{\"split\": {\"$CW1\": \"test\", \"$CW2\": \"val\"}, \"fork\": [\"$CW1\"]}" > splits.json

# 2. the fork registry
$FK register --study R --splits splits.json --namespace rq-test-forks --origins 8000,28000 --horizon 24000 --seeds 2 \
    --pilot-origin 12000 --pilot-seeds 2 --pilot-first 4000 --pilot-horizon 8000 2> fr.log || fail "forks register: $(cat fr.log)"
cp R/config/forks.json forks1.json
$FK register --study R --splits splits.json --namespace rq-test-forks --origins 8000,28000 --horizon 24000 --seeds 2 \
    --pilot-origin 12000 --pilot-seeds 2 --pilot-first 4000 --pilot-horizon 8000 2> /dev/null || fail "register again"
cmp -s forks1.json R/config/forks.json || fail "forks register is not deterministic"
$FK register --study R --splits splits.json --namespace other --origins 8000 2> ow.log && fail "the fork registry was replaced"
grep -q "never replaced" ow.log || fail "the overwrite refusal does not say why: $(cat ow.log)"

# 3. launch: one main branch's engine killed before its first acceptance (a ROOT REPLAY, the same seed),
#    the other's after its first verified acceptance (a TECHNICAL RESUME, no reseed)
read B0 S0 B1 S1 < <($PY -c 'import json
bs = [b for b in json.load(open("R/config/forks.json"))["worlds"] if b["kind"] == "main" and b["origin"]["frame"] == 8000]
print(bs[0]["id"], bs[0]["origin"]["seed"], bs[1]["id"], bs[1]["origin"]["seed"])')
$FK launch --study R --binary "$BIN" --workers 4 $GUARD > fl.log 2>&1 &
sp=$!
for _ in $(seq 1 3000); do pgrep -f "reseed-after-load $S1 " > /dev/null && break; sleep 0.01; done
pkill -KILL -f "reseed-after-load $S1 " || { kill $sp; fail "no engine of $B1 to kill before its first acceptance"; }
for _ in $(seq 1 6000); do [ -s "R/forks/worlds/$B0/accept.jsonl" ] && break; sleep 0.01; done
[ -s "R/forks/worlds/$B0/accept.jsonl" ] || { kill $sp; fail "$B0 accepted nothing"; }
pkill -KILL -f "reseed-after-load $S0 " || { kill $sp; fail "$B0's engine ended before it could be killed after an acceptance"; }
wait $sp; rc=$?
[ "$rc" = 0 ] || fail "forks launch (exit $rc): $(tail -5 fl.log)"
cat > ref.sh <<'SH'
#!/bin/bash
# ref.sh BIN ORIGIN SEED STEPS DIR: the uninterrupted branch (one engine run)
mkdir -p "$5/ckpt" && cd "$5" && "$1" --load-checkpoint "$2" --reseed-after-load "$3" --no-render --headless "$4" \
    --log-every 100 --flush-every 1 --checkpoint-every 4000 --save-checkpoint ckpt/end.json --csv run.csv --wiring-log \
    --predator-log > out.log 2>&1
SH
$PY - "$T" "$BIN" "$W" <<'PY' || fail "the branches"
import csv, json, os, subprocess, sys; sys.path.insert(0, sys.argv[1]); import worlds, forks, rqlib, ckpt
BIN, W = sys.argv[2], sys.argv[3]
reg = forks.runtime_registry("R")
fr = "R/forks"
st = {b["id"]: worlds.read_state(fr, b["id"]) for b in reg["worlds"]}
main = [b for b in reg["worlds"] if b["kind"] == "main"]
pilot = [b for b in reg["worlds"] if b["kind"] == "pilot"]
for b in main:
    if b["origin"]["frame"] == 28000:
        assert st[b["id"]]["status"] == "unavailable" and "without archiving end.28000" in st[b["id"]]["end_reason"], st[b["id"]]
    else:
        assert st[b["id"]]["status"] == "done", (b["id"], st[b["id"]])
for b in pilot:
    s = st[b["id"]]
    assert s["status"] == "held", (b["id"], s)
    assert not os.path.exists(os.path.join(fr, "archive", "worlds", b["id"], "FINALIZED"))
led = [json.loads(l) for l in open(os.path.join(fr, "origins.jsonl"))]
assert sum(1 for e in led if e["status"] == "unavailable") == 2, led
hist = worlds.archive_records("R", main[0]["root"])
resumed, replayed = 0, 0
for b in [x for x in main if x["origin"]["frame"] == 8000]:
    o = b["origin"]
    assert rqlib.sha256_file(o["local"]) == hist["end.8000"]["sha256"] == o["sha256"]       # the frozen origin
    segs = st[b["id"]]["segments"]
    assert "--reseed-after-load" in segs[0]["args"] and segs[0]["start_frame"] == 8000, segs[0]
    for s in segs:      # the root (again, after a loss before the first acceptance) reseeds; a resume never
        assert ("--reseed-after-load" in s["args"]) == (s["start_frame"] == 8000), s
        if "--reseed-after-load" in s["args"]:
            assert s["args"][s["args"].index("--reseed-after-load") + 1] == str(o["seed"]), s
    resumed += any(s["start_frame"] > 8000 for s in segs)                 # a technical resume (no reseed)
    replayed += sum(s["start_frame"] == 8000 for s in segs) >= 2           # a root replay (the same seed)
    ref = os.path.join(W, "ref_" + b["id"])
    subprocess.check_call(["bash", "ref.sh", BIN, os.path.abspath(o["local"]), str(o["seed"]), "24000", ref])
    arec = worlds.archive_records(fr, b["id"])
    assert sorted(r["frame"] for r in arec.values()) == list(range(12000, 32001, 4000)), sorted(arec)
    for f in range(12000, 32001, 4000):
        assert rqlib.sha256_file(os.path.join(ref, "ckpt", f"end.{f}.json")) == arec[f"end.{f}"]["sha256"], (b["id"], f)
    worlds.stitch(fr, b["id"], reg)
    sd = os.path.join(fr, "worlds", b["id"], "stitched")
    for f in ("run.predlog.csv", "run.predators.csv", "run.pwiring.csv"):
        assert open(os.path.join(ref, f)).read() == open(os.path.join(sd, f)).read(), (b["id"], f)
    rw = list(csv.reader(open(os.path.join(ref, "run.wiring.csv"))))
    sw = list(csv.reader(open(os.path.join(sd, "run.wiring.csv"))))
    assert sw == [rw[0]] + [[str(int(r[0]) + 8000)] + r[1:] for r in rw[1:]], b["id"]           # step -> frame
    rr = list(csv.DictReader(open(os.path.join(ref, "run.csv"))))
    srows = list(csv.DictReader(open(os.path.join(sd, "run.csv"))))
    keep = lambda r: {k: v for k, v in r.items() if k not in worlds.NON_CONTINUABLE}      # noqa: E731
    assert [keep(r) for r in rr[1:]] == [keep(r) for r in srows[1:]], b["id"]
    ctr = ckpt.load(o["local"])["counters"]
    for col, key in worlds.INTERVAL_FIX:                                                  # the origin's counters
        assert int(srows[0][col]) == int(rr[0][col]) - int(ctr.get(key, 0)), col
b0, b1 = [x for x in main if x["origin"]["frame"] == 8000]
a0, a1 = worlds.archive_records(fr, b0["id"]), worlds.archive_records(fr, b1["id"])
assert a0["end.12000"]["sha256"] != a1["end.12000"]["sha256"], "two seeds gave the same future"
assert a0["end.12000"]["sha256"] != hist["end.12000"]["sha256"], "a reseeded branch equals the original continuation"
assert worlds.audit_archive(fr, b0["id"], json.load(open(os.path.join(fr, "study.json")))["archive_root"], "done")
assert resumed >= 1 and replayed >= 1, (resumed, replayed)
print("branches ok; technical resumes:", resumed, "root replays:", replayed)
PY
grep -q "UNAVAILABLE" fl.log || fail "the unavailable origins were not logged"

# 4. the pilot's hold lifted: the same branches continue (no reseed), byte-identical to one run
$FK launch --study R --binary "$BIN" --workers 2 --extend-pilot $GUARD > fl2.log 2>&1 || fail "--extend-pilot: $(tail -3 fl2.log)"
grep -q "hold is lifted" fl2.log || fail "the hold was not lifted: $(tail -3 fl2.log)"
$PY - "$T" "$BIN" "$W" <<'PY' || fail "the extended pilot"
import os, subprocess, sys; sys.path.insert(0, sys.argv[1]); import worlds, forks, rqlib
BIN, W = sys.argv[2], sys.argv[3]
reg = forks.runtime_registry("R")
for b in [x for x in reg["worlds"] if x["kind"] == "pilot"]:
    st = worlds.read_state("R/forks", b["id"])
    assert st["status"] == "done", (b["id"], st["status"])
    assert st["segments"][-1]["start_frame"] == 16000 and "--reseed-after-load" not in st["segments"][-1]["args"]
    ref = os.path.join(W, "ref_" + b["id"])
    subprocess.check_call(["bash", "ref.sh", BIN, os.path.abspath(b["origin"]["local"]), str(b["origin"]["seed"]), "8000", ref])
    arec = worlds.archive_records("R/forks", b["id"])
    for f in (16000, 20000):
        assert rqlib.sha256_file(os.path.join(ref, "ckpt", f"end.{f}.json")) == arec[f"end.{f}"]["sha256"], (b["id"], f)
refs = {"prey": [{"world": b, "frame": f} for b in sorted({x["root"] for x in reg["worlds"]}) for f in (4000, 8000, 12000, 16000)],
        "predators": [{"world": b, "frame": f} for b in sorted({x["root"] for x in reg["worlds"]}) for f in (20000, 24000, 4000, 12000)]}
out = forks.profile_design("R", refs)
assert out["counts"]["fork_branch"] == 4 * 3 * 17 and out["counts"]["pilot_branch"] == 2 * 2 * 17, out["counts"]
print("pilot ok; profile design", out["counts"], "deduplicated", out["deduplicated"])
PY
$FK status --study R > st.json || fail "status"
echo "redqueen_forks: ok"
