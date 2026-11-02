#!/usr/bin/env bash
# invasion_tooling.sh — end-to-end test of tools/invasion against the real
# engine (serial build): it pins the child-id derivation score.py relies on, so
# an engine change to how ids are handed out fails here instead of silently
# corrupting invasion scores.
#
#   tests/invasion_tooling.sh PATH/TO/evo_boids WORKDIR
#
#   1. two small evolved snapshots (fresh runs, two seeds);
#   2. invade (with 2 Stage A predators), sham and self arenas; each runs with
#      --reseed-after-load and --repro-log and scores with the derivation
#      checked at three checkpoints;
#   3. a tampered birth log and a reseeding arena are refused;
#   4. the arena builder's load + dump resumes byte-identically;
#   5. hodge.py's self-test; plan.py + run.py on a two-cell plan (resume skips).
set -u
BIN=${1:?usage: invasion_tooling.sh EVO_BOIDS WORKDIR}
W=${2:?usage: invasion_tooling.sh EVO_BOIDS WORKDIR}
T=$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/invasion" && pwd)
PY="python3 -I"
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
eng() { "$BIN" --no-render --log-every 250 "$@" > /dev/null 2>&1 || fail "evo_boids $* exited $?"; }

eng --headless 1500 --seed 1 --population 200 --save-checkpoint A.json
eng --headless 1500 --seed 2 --population 200 --save-checkpoint B.json

arena() {   # name mode extra...
    local name=$1 mode=$2; shift 2
    $PY "$T/arena.py" --resident A.json --mode "$mode" --fraction 0.1 --slot-seed 5 --out "$name.json" \
        --manifest "$name.manifest.json" "$@" > /dev/null || fail "arena.py $name"
    eng --load-checkpoint "$name.json" --reseed-after-load 3 --headless 1200 --csv "$name.csv" --repro-log \
        --repro-log-max 100000000 --save-checkpoint "$name.end.json" --checkpoint-every 400
    local f0; f0=$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['world']['frame'])" "$name.json")
    $PY "$T/score.py" --arena "$name.json" --manifest "$name.manifest.json" --births "$name.births.csv" \
        --checkpoint "$name.end.$((f0 + 400)).json" --checkpoint "$name.end.$((f0 + 800)).json" \
        --checkpoint "$name.end.json" --out "$name.score.json" > /dev/null || fail "score.py $name"
}
arena inv invade --invader B.json --donor-seed 6 --predators 2 --pred-seed 7
arena sham sham --donor-seed 6
arena self self
$PY - <<'PY' || fail "arena / score contents"
import json
m = json.load(open("inv.manifest.json"))
assert m["m"] == round(0.1 * m["n"]) and len(m["marked_ids"]) == m["m"], m["m"]
assert m["config_changes"]["minPopulation"] == [50, 0]
cp = json.load(open("inv.json"))
assert cp["predators"]["count"] == 2 and cp["config"]["predatorCount"] == 2
assert cp["world"]["nextId"] == m["resident"]["nextId"] + m["m"]
s = json.load(open("inv.score.json"))
assert s["derivation"]["ok"] and s["derivation"]["checked_checkpoints"] == 3 and s["births"] > 0
assert s["derivation"]["max_derived_id"] == s["derivation"]["end_nextId"] - 1
sh = json.load(open("sham.manifest.json"))
assert [x["slot"] for x in sh["swapped"]] == [x["slot"] for x in m["swapped"]], "sham must reuse the slots"
se = json.load(open("self.manifest.json"))
assert se["start"]["nextId"] == se["resident"]["nextId"], "self mode mints no ids"
PY

# 3. refusals
grep -v '^3,' inv.births.csv > bad.births.csv
if $PY "$T/score.py" --arena inv.json --manifest inv.manifest.json --births bad.births.csv \
       --checkpoint inv.end.json > /dev/null 2>&1; then fail "a birth log with a missing row was accepted"; fi
$PY - "$T" <<'PY' || fail "building the reseeding arena"
import json, sys
sys.path.insert(0, sys.argv[1]); import invlib
cp = invlib.load_checkpoint("inv.json"); cp["config"]["minPopulation"] = 5000
invlib.write_atomic("rs.json", invlib.dumps_checkpoint(cp))
m = json.load(open("inv.manifest.json")); m["output"]["sha256"] = invlib.sha256_file("rs.json")
json.dump(m, open("rs.manifest.json", "w"))
PY
eng --load-checkpoint rs.json --headless 300 --csv rs.csv --repro-log --save-checkpoint rs.end.json
if $PY "$T/score.py" --arena rs.json --manifest rs.manifest.json --births rs.births.csv \
       --checkpoint rs.end.json > /dev/null 2>&1; then fail "a reseeding arena was accepted"; fi

# 4. load + dump is exact
$PY - "$T" <<'PY' || fail "round trip"
import sys
sys.path.insert(0, sys.argv[1]); import invlib
invlib.write_atomic("A_rt.json", invlib.dumps_checkpoint(invlib.load_checkpoint("A.json")))
PY
eng --load-checkpoint A.json --headless 300 --save-checkpoint A_o.json
eng --load-checkpoint A_rt.json --headless 300 --save-checkpoint A_rt_o.json
cmp -s A_o.json A_rt_o.json || fail "a round-tripped checkpoint does not resume identically"

# 5. hodge self-test, planner + runner
$PY "$T/hodge.py" > /dev/null || fail "hodge.py self-test"
cat > design.json <<EOF
{"name": "t", "snapshots": {"A": "$W/A.json", "B": "$W/B.json"}, "conditions": {"off": 0},
 "fractions": [0.1], "replicates": 1, "steps": 600, "checkpoint_every": 300, "log_every": 300,
 "pairs": [["B", "A"]]}
EOF
$PY "$T/plan.py" design.json > plan.jsonl || fail "plan.py"
[ "$(wc -l < plan.jsonl)" = 2 ] || fail "plan.py: expected 2 cells"
$PY "$T/run.py" --plan plan.jsonl --root root --binary "$BIN" --workers 2 > run.log 2>&1 || fail "run.py: $(tail -3 run.log)"
[ -f root/cells/off_f100_A_B_r00/done.json ] && [ -f root/cells/off_f100_A_sham_r00/done.json ] || fail "run.py: no done.json"
$PY "$T/run.py" --plan plan.jsonl --root root --binary "$BIN" --workers 2 | grep -q "2 already done" || fail "run.py resume"
echo "invasion_tooling: ok"
