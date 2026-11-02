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
#      the plan hash, CSVs at round-trip precision; cells duplicated across
#      roots, a registered cell missing, or an UNREGISTERED cell with the
#      missing cell's labels: descriptive only; inputs.json binds cells.csv;
#   8. snapshot identity: plan.py registers file contents; a changed snapshot
#      is refused before the batch and before each build; a name read as two
#      files across batch attempts is excluded from the analysis;
#   9. SIGTERM to the runner alone leaves no engine running.
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
$PY "$T/analyze.py" --root root3 --out an3 --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 > an3.log 2>&1 \
    || fail "analyze.py: $(tail -5 an3.log)"
$PY - <<'PY' || fail "analysis of the complete registered matrix"
import csv, json
inp = json.load(open("an3/inputs.json"))
assert inp["complete"] and not inp["registered_missing"] and not inp["identity_problems"], inp
rows = list(csv.DictReader(open("an3/matrix.csv")))
assert rows and all(r["status"] == "formal" and r["n"] == "3" and r["k"] == "3" for r in rows), rows
assert all(r["plan_sha256"] == inp["plan"]["sha256"] for r in rows)
assert all(abs(float(r["gamma_check"])) < 1e-9 for r in rows)
# the CSVs are machine-readable: floats at round-trip precision, not the Markdown's 4 decimals
def sig(v):
    return len(v.lstrip("+-").split("e")[0].replace(".", "").lstrip("0"))
for r in rows:
    for c in ("cyclic_share", "rms_A", "noise_A"):
        assert sig(r[c]) > 6, (c, r[c])
    assert all(sig(x) > 6 for x in r["ratings"].split()), r["ratings"]
runs = list(csv.DictReader(open("an3/runs.csv")))
assert sum(1 for x in runs if x["s"] and sig(x["s"]) > 6) > 0.9 * len(runs), "runs.csv scores rounded"
PY
# a window the runs never reached is not read at their final checkpoint: no score, no formal row
$PY "$T/analyze.py" --root root3 --out an3w --plan plan3.jsonl --windows 50 --no-power --sims 50 > an3w.log 2>&1 \
    || fail "analyze.py (window beyond the horizon): $(tail -5 an3w.log)"
$PY - "$T" <<'PY' || fail "a requested window must not silently become an earlier or final checkpoint"
import csv, os, sys
runs = list(csv.DictReader(open("an3w/runs.csv")))
assert runs and all(r["missed"] == "True" and r["s"] == "" and r["steps_at"] == "" for r in runs), runs[:2]
rows = list(csv.DictReader(open("an3w/matrix.csv"))) if os.path.exists("an3w/matrix.csv") else []
assert not any(r["status"] == "formal" for r in rows), rows
sys.path.insert(0, sys.argv[1]); import run
# the runner's schedule check: every periodic checkpoint must be there (the engine only warns)
files = ["end.json", "end.1300.json", "end.1600.json", "end.1900.json", "arena.json"]
assert run.check_schedule(files, 1000, 900, 300) == [], run.check_schedule(files, 1000, 900, 300)
assert run.check_schedule([f for f in files if f != "end.1600.json"], 1000, 900, 300) == [1600]
assert run.check_schedule(["end.json"], 1000, 900, 0) == []
PY
# the same finished cells in two roots: nothing says which copy is right, so neither is used
cp -r root3 root3dup
$PY "$T/analyze.py" --root root3 --root root3dup --out an3d --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 \
    > an3d.log 2>&1 || fail "analyze.py (duplicate roots): $(tail -5 an3d.log)"
$PY - <<'PY' || fail "cells duplicated across roots must not give formal decisions"
import csv, json, os
inp = json.load(open("an3d/inputs.json"))
assert not inp["complete"] and len(inp["identity_problems"]) >= 27, len(inp["identity_problems"])
rows = list(csv.DictReader(open("an3d/matrix.csv"))) if os.path.exists("an3d/matrix.csv") else []
assert not any(r["status"] == "formal" for r in rows), rows
PY
rm root3/cells/off_f100_A_B_r01/done.json
$PY "$T/analyze.py" --root root3 --out an3b --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 > an3b.log 2>&1 \
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
# an UNREGISTERED finished cell carrying the missing cell's labels (same condition, fraction, pair
# and replicate; other seeds) must not stand in for it
$PY - <<'PY' || fail "building the substitute cell"
import json, os, shutil
src, dst = "root3/cells/off_f100_A_B_r00", "root3/cells/off_f100_A_B_r01x"
shutil.copytree(src, dst)
for f in ("cell.json", "done.json"):
    p = os.path.join(dst, f)
    d = json.load(open(p))
    c = d["cell"] if f == "done.json" else d
    c.update(id="off_f100_A_B_r01x", replicate=1, slot_seed=c["slot_seed"] + 1)
    json.dump(d, open(p, "w"))
PY
$PY "$T/analyze.py" --root root3 --out an3c --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 > an3c.log 2>&1 \
    || fail "analyze.py (substitute): $(tail -5 an3c.log)"
$PY - <<'PY' || fail "an unregistered cell filled a registered position"
import csv, json
inp = json.load(open("an3c/inputs.json"))
assert any(u.split("/")[-1] == "off_f100_A_B_r01x" for u in inp["unregistered_finished"]), inp["unregistered_finished"]
assert not inp["complete"] and inp["registered_missing"] == ["off_f100_A_B_r01"], inp["registered_missing"]
rows = list(csv.DictReader(open("an3c/matrix.csv")))
assert rows and all(r["status"].startswith("descriptive") and r["k"] == "2" for r in rows), rows
assert not any(x["id"] == "off_f100_A_B_r01x" for x in csv.DictReader(open("an3c/runs.csv"))), "unregistered cell in runs.csv"
PY
rm -rf root3/cells/off_f100_A_B_r01x
$PY - <<'PY' || fail "inputs.json must bind the report to the cell results it used"
import csv, hashlib, json
inp = json.load(open("an3/inputs.json"))
h = hashlib.sha256(open("an3/cells.csv", "rb").read()).hexdigest()
assert inp["cells_csv"]["sha256"] == h and inp["cells_csv"]["cells"] == 27, inp["cells_csv"]
cells = list(csv.DictReader(open("an3/cells.csv")))
assert len(cells) == 27 and all(len(c["done_sha256"]) == 64 for c in cells)
assert sorted(inp["snapshots"]) == ["A", "B", "C"], inp["snapshots"]
PY

# 8. snapshot identity: registered by content. A snapshot overwritten after planning is refused
#    by the runner (before the batch and before each build); with a plan that registered paths
#    only, the analysis sees one name read as two files and excludes it.
cp A.json As.json; cp B.json Bs.json; cp C.json Cs.json
cat > design8.json <<EOF
{"name": "t8", "snapshots": {"A": "$W/As.json", "B": "$W/Bs.json", "C": "$W/Cs.json"}, "conditions": {"off": 0},
 "fractions": [0.1], "replicates": 2, "steps": 600, "checkpoint_every": 300, "log_every": 300,
 "matrix": ["A", "B", "C"]}
EOF
$PY "$T/plan.py" design8.json > plan8.jsonl || fail "plan.py (design8)"
$PY - <<'PY' || fail "plan.py must register the snapshot contents"
import hashlib, json
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
for c in (json.loads(l) for l in open("plan8.jsonl")):
    assert c["resident_sha256"] == h(c["resident"]), c["id"]
    assert (c["invader_sha256"] == h(c["invader"])) if c["mode"] == "invade" else c["invader_sha256"] is None, c["id"]
PY
cp A.json Cs.json   # C overwritten after planning
$PY "$T/run.py" --plan plan8.jsonl --root root8 --binary "$BIN" --workers 2 > run8.log 2>&1
rc=$?
[ "$rc" = 2 ] && grep -q "snapshots changed since planning" run8.log || fail "run.py ran a plan whose snapshot changed (exit $rc)"
ls root8/cells/*/done.json > /dev/null 2>&1 && fail "run.py admitted a cell from a changed snapshot"
mkdir -p root/cells/snapcheck   # the per-build check (a snapshot overwritten mid-batch)
$PY - <<'PY' || fail "writing the snapcheck cell"
import json
c = [json.loads(l) for l in open("plan8.jsonl") if json.loads(l)["resident_name"] == "C"][0]
c["id"] = "snapcheck"
json.dump(c, open("root/cells/snapcheck/cell.json", "w"))
PY
$PY "$T/run.py" --root "$W/root" --_cell snapcheck > snapcheck.log 2>&1
rc=$?
[ "$rc" = 5 ] || fail "run_cell built an arena from a changed snapshot (exit $rc)"
rm -rf root/cells/snapcheck
cp C.json Cs.json
$PY - <<'PY' || fail "writing the path-only plan"
import json
with open("plan8p.jsonl", "w") as f:
    for ln in open("plan8.jsonl"):
        c = json.loads(ln)
        del c["resident_sha256"], c["invader_sha256"]
        f.write(json.dumps(c, sort_keys=True) + "\n")
PY
head -9 plan8p.jsonl > plan8p_a.jsonl   # batch 1: replicate 0
$PY "$T/run.py" --plan plan8p_a.jsonl --root root8p --binary "$BIN" --workers 2 > run8a.log 2>&1 || fail "run.py batch 1"
cp A.json Cs.json   # C overwritten between the batch attempts
$PY "$T/run.py" --plan plan8p.jsonl --root root8p --binary "$BIN" --workers 2 > run8b.log 2>&1 || fail "run.py batch 2"
$PY "$T/analyze.py" --root root8p --out an8 --plan plan8p.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 > an8.log 2>&1 \
    || fail "analyze.py (two-batch): $(tail -5 an8.log)"
$PY - <<'PY' || fail "a snapshot name read as two files must be excluded"
import csv, json, os
inp = json.load(open("an8/inputs.json"))
assert any(p.startswith("snapshot C was read as 2 different files") for p in inp["identity_problems"]), inp["identity_problems"]
assert "C" not in inp["snapshots"] and not inp["complete"]
rows = list(csv.DictReader(open("an8/matrix.csv"))) if os.path.exists("an8/matrix.csv") else []
assert not any(r["status"] == "formal" for r in rows), rows
PY

# 9. SIGTERM to the runner process alone (not its group) stops every engine it started
cat > design9.json <<EOF
{"name": "t9", "snapshots": {"A": "$W/A.json", "B": "$W/B.json"}, "conditions": {"off": 0}, "fractions": [0.1],
 "replicates": 1, "steps": 400000, "checkpoint_every": 0, "log_every": 1000, "pairs": [["B", "A"]]}
EOF
$PY "$T/plan.py" design9.json > plan9.jsonl || fail "plan.py (design9)"
engines() { pgrep -f "$W/root9/bin/evo_boids" | wc -l; }
$PY "$T/run.py" --plan plan9.jsonl --root root9 --binary "$BIN" --workers 2 > run9.log 2>&1 &
rp=$!
for _ in $(seq 1 150); do [ "$(engines)" -ge 2 ] && break; sleep 0.1; done
[ "$(engines)" -ge 2 ] || { kill -TERM $rp; fail "the runner did not start 2 engines: $(tail -3 run9.log)"; }
kill -TERM $rp
wait $rp
rc=$?
left=$(engines)
pkill -KILL -f "$W/root9/bin/evo_boids" 2> /dev/null   # (this test's own engines, if the check fails)
[ "$left" = 0 ] || fail "SIGTERM to the runner left $left engine(s) running"
[ "$rc" = 130 ] || fail "the signalled runner exited $rc, expected 130"
echo "invasion_tooling: ok"
