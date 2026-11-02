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
#   5. hodge.py's self-test; plan.py + run.py on a two-cell plan (resume skips);
#   6. the runner's memory gate: cgroup v2 limits up the tree, fail closed on
#      malformed / unreadable readings (the runner exits 2, admits nothing);
#   7. a registered 3x3 matrix: analyze.py --plan gives formal rows bound to
#      the plan hash; with one registered cell missing, descriptive only.
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

# 6. the memory gate fails closed and honours cgroup v2 limits up the tree
mkdir -p cg/a/b
printf 'MemTotal: 9000000 kB\nMemAvailable: 8000000 kB\n' > meminfo.ok
printf 'MemAvailable: lots kB\n' > meminfo.bad
echo "0::/a/b" > proc_cgroup
echo 1073741824 > cg/a/b/memory.max; echo 536870912 > cg/a/b/memory.current
echo max > cg/a/memory.max; echo 1 > cg/a/memory.current
$PY - "$T" "$W" <<'PY' || fail "memory headroom readings"
import os, sys
sys.path.insert(0, sys.argv[1]); import run
w = sys.argv[2]
os.environ.update(INVASION_MEMINFO=f"{w}/meminfo.ok", INVASION_PROC_CGROUP=f"{w}/proc_cgroup",
                  INVASION_CGROUP_ROOT=f"{w}/cg")
assert run.mem_headroom_mb() == 512, run.mem_headroom_mb()          # the cgroup is the binding limit
open(f"{w}/cg/a/b/memory.max", "w").write("max\n")
assert run.mem_headroom_mb() == 7812, run.mem_headroom_mb()         # no limit: MemAvailable
open(f"{w}/cg/a/b/memory.current", "w").write("oops\n")
open(f"{w}/cg/a/b/memory.max", "w").write("1073741824\n")
assert run.mem_headroom_mb() is None                                 # malformed cgroup reading
open(f"{w}/cg/a/b/memory.current", "w").write("536870912\n")
os.environ["INVASION_MEMINFO"] = f"{w}/meminfo.bad"
assert run.mem_headroom_mb() is None                                 # malformed MemAvailable
os.environ["INVASION_MEMINFO"] = f"{w}/does_not_exist"
assert run.mem_headroom_mb() is None                                 # unreadable
PY
INVASION_MEMINFO=$W/meminfo.bad $PY "$T/run.py" --plan plan.jsonl --root root_mem --binary "$BIN" --workers 1 > mem.log 2>&1
rc=$?
[ "$rc" = 2 ] || fail "run.py with an unreadable memory reading exited $rc, expected 2"
ls root_mem/cells/*/done.json > /dev/null 2>&1 && fail "run.py admitted a cell without a memory reading"

# 7. a registered 3x3 matrix: formal only when every registered cell is finished
eng --headless 1500 --seed 3 --population 200 --save-checkpoint C.json
cat > design3.json <<EOF
{"name": "t3", "snapshots": {"A": "$W/A.json", "B": "$W/B.json", "C": "$W/C.json"}, "conditions": {"off": 0},
 "fractions": [0.1], "replicates": 3, "steps": 600, "checkpoint_every": 300, "log_every": 300,
 "matrix": ["A", "B", "C"]}
EOF
$PY "$T/plan.py" design3.json > plan3.jsonl || fail "plan.py (matrix)"
[ "$(wc -l < plan3.jsonl)" = 27 ] || fail "plan.py: a 3x3 matrix x 3 replicates is 27 cells"
$PY "$T/run.py" --plan plan3.jsonl --root root3 --binary "$BIN" --workers 2 > run3.log 2>&1 || fail "run.py (matrix): $(tail -3 run3.log)"
$PY "$T/analyze.py" --root root3 --out an3 --plan plan3.jsonl --windows 0.25 --no-power --sims 50 > an3.log 2>&1 \
    || fail "analyze.py: $(tail -5 an3.log)"
$PY - <<'PY' || fail "analysis of the complete registered matrix"
import csv, json
inp = json.load(open("an3/inputs.json"))
assert inp["complete"] and not inp["registered_missing"] and not inp["identity_problems"], inp
rows = list(csv.DictReader(open("an3/matrix.csv")))
assert rows and all(r["status"] == "formal" and r["n"] == "3" and r["k"] == "3" for r in rows), rows
assert all(r["plan_sha256"] == inp["plan"]["sha256"] for r in rows)
assert all(abs(float(r["gamma_check"])) < 1e-9 for r in rows)
PY
rm root3/cells/off_f100_A_B_r01/done.json
$PY "$T/analyze.py" --root root3 --out an3b --plan plan3.jsonl --windows 0.25 --no-power --sims 50 > an3b.log 2>&1 \
    || fail "analyze.py (incomplete): $(tail -5 an3b.log)"
$PY - <<'PY' || fail "an incomplete registered matrix must be descriptive"
import csv, json
inp = json.load(open("an3b/inputs.json"))
assert not inp["complete"] and inp["registered_missing"] == ["off_f100_A_B_r01"], inp["registered_missing"]
rows = list(csv.DictReader(open("an3b/matrix.csv")))
assert rows, "the available 2-replicate block should still be reported (descriptively)"
for r in rows:
    assert r["status"].startswith("descriptive") and r["p_lof"] == "" and r["floor95"] == "" and r["k"] == "2", r
PY
echo "invasion_tooling: ok"
