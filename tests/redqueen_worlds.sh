#!/usr/bin/env bash
# redqueen_worlds.sh — tools/redqueen/worlds.py end to end against the real engine (serial build),
# on tiny worlds (200 prey, 24,000 steps, a checkpoint every 4,000), plus its unit tests.
#
#   tests/redqueen_worlds.sh PATH/TO/evo_boids WORKDIR        (env: PYTHON, default python3)
#
#   1. register: deterministic bytes; one block of C, A and B; placeholder and floor refusals;
#   2. f1 + launch: every history completes; F1 and six checkpoints per world are archived
#      read-only, the archive directories finalized (FINALIZED, 0555); verify-f1: F1 resumed to
#      the first checkpoint is byte-identical to the history's (F1 lies on its trajectory);
#   3. a SIGKILLed C engine: the supervisor resumes the last good checkpoint; every archived
#      checkpoint equals the uninterrupted root's, and the stitched logs equal the uninterrupted
#      run's (lineage log, predators.csv, pwiring, prey wiring; the main CSV but its timing and
#      repro_components columns);
#   4. a SIGKILLed supervisor: its engines die with it (PR_SET_PDEATHSIG); the restart resumes and
#      finishes with the same archive;
#   5. extinction: a prey collapse is recorded in availability.jsonl and the world ends "extinct"
#      (archive finalized); STOP stops admission (exit 75); design-block lists the archive.
set -u
BIN=${1:?usage: redqueen_worlds.sh EVO_BOIDS WORKDIR}
W=${2:?usage: redqueen_worlds.sh EVO_BOIDS WORKDIR}
case "$BIN" in /*) ;; *) BIN="$PWD/$BIN" ;; esac
T=$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/redqueen" && pwd)
PY="${PYTHON:-python3} -I"
WS="$PY $T/worlds.py"
[ -d "$W" ] && chmod -R u+w "$W" 2> /dev/null
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
GUARD="--mem-min-mb 50 --disk-min $W:200 --poll 0.2"
$PY -c 'import sys; print("redqueen_worlds: Python", sys.version.split()[0])'
$PY -W error::ResourceWarning "$T/test_worlds.py" > unit.log 2>&1 || { tail -30 unit.log; fail "unit tests"; }
grep -q ResourceWarning unit.log && fail "the unit tests leak file handles"

cat > arena.json <<'JSON'
{"schema": "finfolk.redqueen.arena/1", "status": "selected",
 "common": {"population": 200, "min-pop": 0, "max-pop": 250, "target-food": 800},
 "treatments": {
  "C": {"predators": 6, "predator-economy": true, "predator-brain": true, "predator-min-pop": 0,
        "predator-max-pop": 12, "predator-max-age": 15, "predator-meal": 14},
  "A": {"predators": 3},
  "B": {"predators": 6, "predator-economy": true, "predator-min-pop": 0, "predator-max-pop": 12,
        "predator-max-age": 15, "predator-meal": 14}}}
JSON
REG="register --arena arena.json --namespace rq-test-worlds --blocks 1 --per-block C=1,A=1,B=1
     --total-steps 24000 --checkpoint-every 4000 --log-every 100"

# 1. the registry
$WS $REG --out reg1.json 2> /dev/null || fail "register"
$WS $REG --out reg2.json 2> /dev/null || fail "register (again)"
cmp -s reg1.json reg2.json || fail "register is not deterministic"
sed 's/"predator-max-age": 15, "predator-meal": 14}, *$/"predator-max-age": "SELECTED_AGE", "predator-meal": 14},/' arena.json \
    | sed 's/"status": "selected"/"status": "placeholder"/' > arena_ph.json
$WS register --arena arena_ph.json --namespace x --out x.json 2> ph.log && fail "a placeholder arena was registered"
grep -q "placeholder" ph.log || fail "the placeholder refusal does not say why: $(cat ph.log)"
sed 's/"min-pop": 0,/"min-pop": 20,/' arena.json > arena_floor.json
$WS register --arena arena_floor.json --namespace x --out x.json 2> fl.log && fail "a prey floor was registered"
grep -q "prey floor" fl.log || fail "the floor refusal does not say why: $(cat fl.log)"
mkroot() { mkdir -p "$1/config"; cp reg1.json "$1/config/worlds.json"; }
CW=$($PY -c 'import json; print([w["id"] for w in json.load(open("reg1.json"))["worlds"] if w["treatment"] == "C"][0])')

# 2. f1 + launch, uninterrupted
mkroot R1
$WS f1 --root R1 --binary "$BIN" --archive-root "$W/arch1" > r1f1.log 2>&1 || fail "f1: $(tail -3 r1f1.log)"
$WS launch --root R1 --binary "$BIN" --archive-root "$W/arch1" --workers 3 --on-extinction continue $GUARD > r1.log 2>&1 \
    || fail "launch: $(tail -5 r1.log)"
$WS verify-f1 --root R1 > r1v.log 2>&1 || fail "verify-f1: $(tail -3 r1v.log)"
$PY - "$T" <<'PY' || fail "the uninterrupted root"
import json, os, stat, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib
reg = json.load(open("R1/config/worlds.json"))
for w in reg["worlds"]:
    st = worlds.read_state("R1", w["id"])
    assert st["status"] == "done" and len(st["segments"]) == 1, (w["id"], st["status"])
    recs = worlds.archive_records("R1", w["id"])
    assert sorted(r["frame"] for r in recs.values()) == [1, 4000, 8000, 12000, 16000, 20000, 24000], recs.keys()
    for r in recs.values():
        assert rqlib.sha256_file(r["path"]) == r["sha256"] and os.stat(r["path"]).st_mode & 0o777 == 0o444
    ad = os.path.dirname(recs["F1"]["path"])
    assert os.path.isfile(os.path.join(ad, "FINALIZED")) and os.stat(ad).st_mode & 0o777 == 0o555
    assert json.load(open(f"R1/worlds/{w['id']}/f1_verify.json"))["identical"] is True
PY

# 3. a SIGKILLed C engine: resume, identical archive, stitched logs = the uninterrupted logs
mkroot R2
$WS launch --root R2 --binary "$BIN" --archive-root "$W/arch2" --workers 3 --on-extinction continue $GUARD > r2.log 2>&1 &
sp=$!
# (late enough that the unflushed predator wiring log has reached disk past a checkpoint, so the
#  resume starts from a checkpoint, not from the founder seed)
for _ in $(seq 1 2000); do [ -f "R2/worlds/$CW/ckpt/end.16000.json" ] && break; sleep 0.01; done
pkill -KILL -f "$W/R2/bin/evo_boids.*--predator-log" || { kill $sp; fail "no C engine to kill (it finished first?)"; }
wait $sp; rc=$?
[ "$rc" = 0 ] || fail "the supervisor did not finish after the kill (exit $rc): $(tail -5 r2.log)"
$WS stitch --root R2 --world "$CW" > /dev/null || fail "stitch"
$PY - "$T" "$CW" <<'PY' || fail "the interrupted history differs from the uninterrupted one"
import csv, json, sys; sys.path.insert(0, sys.argv[1]); import worlds
cw = sys.argv[2]
reg = json.load(open("R1/config/worlds.json"))
for w in reg["worlds"]:
    a = {k: r["sha256"] for k, r in worlds.archive_records("R1", w["id"]).items() if k != "F1"}
    b = {k: r["sha256"] for k, r in worlds.archive_records("R2", w["id"]).items()}
    assert a == b, (w["id"], sorted(set(a) ^ set(b)))
st = worlds.read_state("R2", cw)
assert len(st["segments"]) >= 2 and st["status"] == "done", st
assert any(s["start_frame"] > 0 for s in st["segments"][1:]), "the resume did not start from a checkpoint"
for f in ("run.predlog.csv", "run.predators.csv", "run.pwiring.csv", "run.wiring.csv"):
    x, y = open(f"R1/worlds/{cw}/seg000/{f}").read(), open(f"R2/worlds/{cw}/stitched/{f}").read()
    assert x == y, f
def rows(p):
    with open(p) as fh:
        return [{k: v for k, v in r.items() if k not in worlds.NON_CONTINUABLE} for r in csv.DictReader(fh)]
assert rows(f"R1/worlds/{cw}/seg000/run.csv") == rows(f"R2/worlds/{cw}/stitched/run.csv")
print("segments", [(s["name"], s["start_frame"]) for s in st["segments"]])
PY

# 4. a SIGKILLed supervisor: no engine outlives it; the restart finishes with the same archive
mkroot R3
$WS launch --root R3 --binary "$BIN" --archive-root "$W/arch3" --workers 3 --on-extinction continue $GUARD > r3a.log 2>&1 &
sp=$!
for _ in $(seq 1 1500); do ls R3/worlds/*/ckpt/end.8000.json > /dev/null 2>&1 && break; sleep 0.01; done
kill -KILL $sp; wait $sp 2> /dev/null
for _ in $(seq 1 100); do [ -z "$(pgrep -f "$W/R3/bin/evo_boids")" ] && break; sleep 0.1; done
[ -z "$(pgrep -f "$W/R3/bin/evo_boids")" ] || { pkill -KILL -f "$W/R3/bin/evo_boids"; fail "an engine outlived the supervisor"; }
$WS launch --root R3 --binary "$BIN" --archive-root "$W/arch3" --workers 3 --on-extinction continue $GUARD > r3b.log 2>&1 \
    || fail "the restart: $(tail -5 r3b.log)"
$PY - "$T" <<'PY' || fail "the restarted root's archive differs"
import json, sys; sys.path.insert(0, sys.argv[1]); import worlds
for w in json.load(open("R1/config/worlds.json"))["worlds"]:
    a = {k: r["sha256"] for k, r in worlds.archive_records("R1", w["id"]).items() if k != "F1"}
    b = {k: r["sha256"] for k, r in worlds.archive_records("R3", w["id"]).items()}
    assert a == b and worlds.read_state("R3", w["id"])["status"] == "done", w["id"]
PY

# 5. extinction, STOP, design-block
cat > arena_x.json <<'JSON'
{"schema": "finfolk.redqueen.arena/1", "status": "selected",
 "common": {"population": 8, "min-pop": 0, "max-pop": 8, "target-food": 20},
 "treatments": {"A": {"predators": 40, "predator-capture-radius": 60}}}
JSON
mkdir -p RX/config
$WS register --arena arena_x.json --namespace rq-test-x --blocks 1 --per-block A=1 --total-steps 24000 \
    --checkpoint-every 4000 --log-every 100 --out RX/config/worlds.json 2> /dev/null || fail "register (extinction)"
$WS launch --root RX --binary "$BIN" --archive-root "$W/archx" --workers 1 $GUARD > rx.log 2>&1 || fail "launch (extinction): $(tail -3 rx.log)"
$PY - "$T" <<'PY' || fail "the extinction was not recorded"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
led = [json.loads(l) for l in open("RX/availability.jsonl")]
assert len(led) == 1 and led[0]["guild"] == "prey" and led[0]["first_zero_frame"] > 0, led
st = worlds.read_state("RX", led[0]["world"])
assert st["status"] == "extinct", st["status"]
assert os.path.isfile(os.path.join("archx", "worlds", led[0]["world"], "FINALIZED"))
import subprocess

PY
mkroot R4; touch R4/STOP
$WS launch --root R4 --binary "$BIN" --archive-root "$W/arch4" $GUARD > r4.log 2>&1; rc=$?
[ "$rc" = 75 ] || fail "STOP: exit $rc, expected 75"
ls R4/worlds/*/seg000 > /dev/null 2>&1 && fail "STOP admitted a segment"
$WS design-block --root R1 --archive-root "$W/arch1" --out block.json || fail "design-block"
$PY - <<'PY' || fail "design-block contents"
import json
b = json.load(open("block.json"))
assert b["times"] == {"F1": 1, "f4000": 4000, "f8000": 8000, "f12000": 12000, "f16000": 16000, "f20000": 20000, "f24000": 24000}
w = next(iter(b["worlds"].values()))
assert w["pattern"].endswith("end.{frame}.json") and w["paths"]["F1"].endswith("F1.json")
PY
echo "redqueen_worlds: ok"
