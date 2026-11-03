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
#   9. SIGTERM to the runner alone leaves no engine running;
#  10. parent -> child correspondence: with distinct mother lines and mutation
#      off, every child's lineage and genome match its derived birth record,
#      and a log with two same-frame births swapped is refused;
#  11. block comparisons: inclusive within-regime summary, regime / time
#      sub-blocks decomposed on their own, the bipartite cross-regime graph's
#      cyclic part harmonic (a planted 4-cycle found there, not in the blocks);
#  12. null calibration under heteroscedastic noise: the bootstrap and
#      sign-flip lack-of-fit tests keep their level (the old chi-square did not);
#  13. interpretation: the score is a founder pedigree index; S > 0 with one
#      direction losing is 'opposite directions', never a reciprocal claim.
#  Review round 2:
#  14. directional labels use Student-t bounds (k - 1 df), not 1.96;
#  15. an incomplete block publishes no sub-block p-values, and an omnibus
#      needs every REGISTERED condition formal (no silent shrinking);
#  16. calibration assesses the analysis's own primary configuration and binds
#      its inputs, code and outputs in manifest.json; the stress worlds exist
#      and the rare-event world breaks the tests (the qualification);
#  17. bounded-scale sensitivity: a transitive bounded (logistic) ladder makes
#      raw-scale curl that the bounded model removes; a planted cycle survives;
#  18. the common fixed-step clock reads every run at the same step; horizon.py
#      calibrates T on a cell selection; an extinct read scores s = -f0;
#  19. infer.py and bounded.py self-tests (grouped omnibus, Gray-code flips; the co-primary;
#      the Aranda-Ordaz link at small lambda);
#  Review round 3:
#  20. the error-bank planner: cores, indexed seeds, seed-overlap refusal; the progress file;
#  21. bank resampling WITH replacement (full noise energy); the bank omnibus mode;
#  22. explicit home-regime primary blocks (two disjoint cores; a missing primary cell);
#  23. exact fixed-step reads; formal only at registered windows;
#  24. the co-primary decision: family threshold 0.05/12, H1 / H1b / claim calibration.
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
# the score says what it is: a founder pedigree index ("mixed pedigree", not "hybrid")
assert s["measure"] == "founder_pedigree_contribution" and "n_mixed_pedigree" in s["points"][-1], s["points"][-1]
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

# 10. parent -> child correspondence, directly: an arena where every fish has its own mother line
#     and mutation is off, so each child's lineage and genome identify the birth it came from
$PY - "$T" <<'PY' || fail "building the correspondence arena"
import json, sys
sys.path.insert(0, sys.argv[1]); import invlib
cp = invlib.load_checkpoint("inv.json")
cs = cp["creatures"]
cs["lineageId"] = [10 ** 9 + k for k in range(int(cs["count"]))]   # distinct; never == an id
cp["config"]["mutationMultiplier"] = 0.0
invlib.write_atomic("cor.json", invlib.dumps_checkpoint(cp))
m = json.load(open("inv.manifest.json")); m["output"]["sha256"] = invlib.sha256_file("cor.json")
json.dump(m, open("cor.manifest.json", "w"))
PY
eng --load-checkpoint cor.json --reseed-after-load 4 --headless 1500 --csv cor.csv --repro-log \
    --repro-log-max 100000000 --save-checkpoint cor.end.json --checkpoint-every 100
cps=""; for f in cor.end.*.json; do cps="$cps --checkpoint $f"; done
$PY "$T/score.py" --arena cor.json --manifest cor.manifest.json --births cor.births.csv $cps \
    --checkpoint cor.end.json --out cor.score.json > /dev/null || fail "score.py (correspondence arena)"
$PY - <<'PY' || fail "the correspondence checks did not run"
import json
d = json.load(open("cor.score.json"))["derivation"]
assert d["crossover_checked_children"] >= 20 and d["lineage_checked_children"] >= 20, d
PY
# swap the parents of two births in one frame (as if the newborns were permuted before their ids
# were assigned): counts, frames, ids and parent availability all still agree
$PY - <<'PY' || fail "building the permuted log"
lines = open("cor.births.csv").read().split("\n")
rows = [(k, ln.split(",")) for k, ln in enumerate(lines) if ln and not ln.startswith("#") and not ln.startswith("index")]
for (a, x), (b, y) in zip(rows, rows[1:]):
    if x[1] == y[1] and x[4] != y[4]:
        x[2:6], y[2:6] = y[2:6], x[2:6]
        lines[a], lines[b] = ",".join(x), ",".join(y)
        break
else:
    raise SystemExit("no frame with two births of different mother lines")
open("cor.perm.births.csv", "w").write("\n".join(lines))
PY
if $PY "$T/score.py" --arena cor.json --manifest cor.manifest.json --births cor.perm.births.csv $cps \
       --checkpoint cor.end.json > cor.perm.log 2>&1; then
    fail "a log whose births were permuted within a frame was accepted"
fi

# 11. block comparisons: relation summaries say what they are (inclusive within-regime group), and
#     balanced sub-blocks are decomposed on their own; the cross-regime pairs form a bipartite graph
#     whose cyclic part is all harmonic (a planted 4-cycle through both regimes is found there, and
#     the within-regime sub-blocks, pure ladders, show none)
$PY - "$T" <<'PY' || fail "sub-block / incomplete-graph decompositions"
import random, sys
sys.path.insert(0, sys.argv[1]); import analyze, infer
rnd = random.Random(4)
names = ["a1", "a2", "a3", "b1", "b2", "b3"]
meta = {nm: {"run": "r" + nm[0] + ("12" if nm[1] in "12" else "3"), "regime": nm[0], "family": "f" + nm,
             "time": 1 if nm[1] in "12" else 2} for nm in names}
r = {nm: rnd.gauss(0, 0.05) for nm in names}
cyc = {("a1", "b1"): 1, ("b1", "a2"): 1, ("a2", "b2"): 1, ("b2", "a1"): 1}   # a1 -> b1 -> a2 -> b2 -> a1
amp = 0.02
def Aij(i, j):
    c = amp * cyc.get((i, j), 0) - amp * cyc.get((j, i), 0)
    return r[i] - r[j] + c
rows = []
for j in names:
    for i in names:
        for rep in range(4):
            mu = 0.0 if i == j else 0.5 * Aij(i, j)
            rows.append({"cond": "off", "frac": 0.1, "G": 1.0, "mode": "sham" if i == j else "invade", "i": i, "j": j,
                         "rep": rep, "s": mu + rnd.gauss(0, 1e-6), "missed": False})
out, detail, blocks, joint, subs = analyze.matrices(rows, meta, sims=99, registry=None, kind="wild")
assert "within-regime (all): n=6" in out[0]["by_category"], out[0]["by_category"]
g = {s["group"]: s for s in subs}
assert {"regime=a", "regime=b", "time=1", "cross-regime pairs (bipartite, incomplete)"} <= set(g), sorted(g)
assert g["time=1"]["cyclic_share"] > 0.01   # the 4 time-1 items carry the planted cycle
z = blocks[("off", 0.1, 1.0)]["z"]
assert abs(g["regime=a"]["cyclic_share"] - infer.infer([analyze.subblock(z, [0, 1, 2])], B=19)["share_raw"]) < 1e-12
assert g["regime=a"]["cyclic_share"] < 1e-6 and g["regime=b"]["cyclic_share"] < 1e-6, (g["regime=a"], g["regime=b"])
sg = analyze.subgraph_summary(z, lambda p, q: names[p][0] != names[q][0])
assert sg["triangles"] == 0 and abs(sg["local_nc"]) < 1e-12 and abs(sg["harmonic_nc"] / (4 * amp ** 2) - 1) < 1e-3, sg
assert out[0]["cyclic_share"] > 0.01   # the full matrix sees the cycle too
PY

# 12. calibration: with heteroscedastic null noise (per-cell SDs 0.002-0.08, as in the pilot) the
#     lack-of-fit tests keep their level; the superseded isotropic chi-square does not
$PY - "$T" <<'PY' || fail "null calibration of the lack-of-fit test"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate, infer
rnd = random.Random(12)
N, k, S = 6, 6, 300
sds = [[0.0 if i == p else math.exp(rnd.uniform(math.log(0.002), math.log(0.08))) for i in range(N)] for p in range(N)]
rej = {"boot": 0, "flip": 0, "chi2": 0, "sym": 0}
for s in range(S):
    z = [[[0.0 if i == p else sds[p][i] * rnd.gauss(0, 1) for i in range(N)] for _ in range(k)] for p in range(N)]
    r = infer.infer([z], B=99, seed=s)
    rej["boot"] += r["p_lof"] <= 0.05
    rej["sym"] += r["p_sym"] <= 0.05
    rej["flip"] += r["p_lof_flip"] <= 0.05
    rej["chi2"] += calibrate.old_tests(z)[0] <= 0.05
rate = {t: v / S for t, v in rej.items()}
print("null rejection at alpha 0.05:", rate)
assert rate["boot"] <= 0.09 and rate["sym"] <= 0.09 and rate["flip"] <= 0.06, rate
assert rate["chi2"] >= 0.09, rate   # the old test's anti-conservatism (0.12 here), for the record
PY

# 13. interpretation: a positive symmetric part is not a reciprocal claim. The pilot's n102e / n102l
#     pair (-0.035 one way, +0.133 the other, S = +0.049) is 'opposite directions'
$PY - "$T" <<'PY' || fail "reciprocal classification"
import sys
sys.path.insert(0, sys.argv[1]); import analyze
prs = [{"cond": "off", "frac": 0.05, "G": 5.0, "j": "n102l", "i": "n102e", "st": -0.0352, "se_paired": 0.009, "z": -3.9},
       {"cond": "off", "frac": 0.05, "G": 5.0, "j": "n102e", "i": "n102l", "st": 0.1325, "se_paired": 0.010, "z": 13.2}]
pt = analyze.pair_table(prs)
assert len(pt) == 1 and pt[0]["S"] > 0 and pt[0]["reciprocal"] == "opposite directions", pt
assert analyze.reciprocal(2.5, 3.0) == "reciprocal gain" and analyze.reciprocal(-2.5, -3.0) == "reciprocal suppression"
assert analyze.reciprocal(2.5, 1.0) == "unresolved" and analyze.reciprocal(None, 3.0) == "unresolved"
PY

# 14. directional bounds from k replicates are Student-t, not normal: the pilot's Stage-A
#     n101e / p103e pair at 10 replicates (-2.175, +1.979) is not 'opposite directions'
$PY - "$T" <<'PY' || fail "directional labels need t bounds"
import sys
sys.path.insert(0, sys.argv[1]); import analyze
assert abs(analyze.direction_cutoff(6) - 2.5706) < 1e-3 and abs(analyze.direction_cutoff(10) - 2.2622) < 1e-3
assert analyze.reciprocal(-2.175, 1.979, 10, 10) == "unresolved"
assert analyze.reciprocal(-2.175, 1.979) == "opposite directions"   # (the large-k limit only)
assert analyze.reciprocal(-2.6, 2.6, 6, 6) == "opposite directions" and analyze.reciprocal(-2.5, 2.6, 6, 6) == "unresolved"
prs = [{"cond": "predA4", "frac": 0.05, "G": 10.0, "j": "p103e", "i": "n101e", "st": -0.02, "se_paired": 0.0092, "z": -2.175, "k": 10},
       {"cond": "predA4", "frac": 0.05, "G": 10.0, "j": "n101e", "i": "p103e", "st": 0.02, "se_paired": 0.0101, "z": 1.979, "k": 10}]
pt = analyze.pair_table(prs)
assert pt[0]["reciprocal"] == "unresolved" and abs(pt[0]["cut_a_into_b"] - 2.2622) < 1e-3, pt
PY

# 15. a block with a registered cell missing publishes no sub-block p-value, and an omnibus
#     over the registered conditions with one of them incomplete is descriptive (it used to
#     shrink to the formal ones)
$PY - "$T" <<'PY' || fail "sub-block / omnibus decision gates"
import random, sys
sys.path.insert(0, sys.argv[1]); import analyze
rnd = random.Random(15)
names = ["a1", "a2", "a3", "b1", "b2", "b3"]
meta = {nm: {"run": "r" + nm, "regime": nm[0], "family": "f" + nm, "time": 1} for nm in names}
conds, reps = ("off", "predA", "predB"), (0, 1, 2)
rows, reg = [], {}
for c in conds:
    for j in names:
        for i in names:
            mode = "sham" if i == j else "invade"
            reg.setdefault((c, 0.05), {})[(i, j, mode)] = set(reps)
            for r in reps:
                if c == "predB" and (i, j, r) == ("a1", "b2", 1):
                    continue   # one registered cell never finished
                rows.append({"cond": c, "frac": 0.05, "G": 5.0, "mode": mode, "i": i, "j": j, "rep": r,
                             "s": (0.0 if i == j else 0.02 * (names.index(i) - names.index(j))) + rnd.gauss(0, 0.004),
                             "missed": False})
out, detail, blocks, joint, subs = analyze.matrices(rows, meta, sims=49, registry=reg, kind="residual")
st = {m["cond"]: m["status"] for m in out}
assert st["off"] == st["predA"] == "formal" and st["predB"].startswith("descriptive"), st
for s in subs:
    if s["cond"] == "predB":
        assert s["p_lof"] is None and s["p_lof_flip"] is None and s["status"].startswith("descriptive"), s
    elif s["group"].startswith("regime="):   # complete sub-blocks of a formal block are tested
        assert s["p_lof"] is not None, s
assert joint and all(j["status"].startswith("descriptive") and j.get("p_lof") is None and j.get("p_primary") is None
                     for j in joint), joint
assert all(j["required"] == "off predA predB" for j in joint), joint
# with predB not registered, the two formal conditions are the registered set: formal, both structures
reg2 = {k: v for k, v in reg.items()}
rows2 = [x for x in rows if x["cond"] != "predB"]
out, detail, blocks, joint, subs = analyze.matrices(rows2, meta, sims=49, registry={("off", 0.05): reg[("off", 0.05)],
                                                    ("predA", 0.05): reg[("predA", 0.05)]}, kind="residual")
kinds = {j["structure"]: j for j in joint}
assert set(kinds) == {"pooled block x assays"}, kinds
assert all(j["status"] == "formal" and j["p_lof"] is not None for j in joint), joint
# the home-regime x assay omnibus is now the explicit primary one (test 22)
for r in rows2:
    r["f0"] = 0.05
pr, pb, pj = analyze.primary_blocks(rows2, meta, {("off", 0.05): reg[("off", 0.05)], ("predA", 0.05): reg[("predA", 0.05)]},
                                    None, 49)
assert len(pj) == 1 and pj[0]["status"] == "formal" and pj[0]["flip_min_p"] == 1 / 16, pj
# without a plan nothing is formal
out, detail, blocks, joint, subs = analyze.matrices(rows2, meta, sims=49, registry=None, kind="residual")
assert all(j.get("p_lof") is None for j in joint) and all(s["p_lof"] is None for s in subs)
PY

# 16. calibration runs the analysis's own primary configuration, refuses another primary kind,
#     binds blocks / code / outputs in manifest.json, and has the stress worlds; the rare-event
#     world (review round 2's counterexample) breaks the sign-flip at k = 6 (the qualification)
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal_bad --kinds wild > cal_bad.log 2>&1
[ $? = 2 ] && grep -q "primary bootstrap kind" cal_bad.log || fail "calibrate.py accepted a primary kind other than the analysis's"
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal3 --sims 10 --B 19 --chunk 5 --no-plants \
    --worlds hetero,skewfactor,mixture,rare1 --workers 2 > cal3.log 2>&1 || fail "calibrate.py: $(tail -5 cal3.log)"
$PY - "$T" <<'PY' || fail "calibration provenance / configuration"
import csv, hashlib, json, math, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate, infer
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
m = json.load(open("cal3/manifest.json"))
assert m["blocks"]["sha256"] == h("an3/blocks.json") and m["outputs"]["calib.csv"] == h("cal3/calib.csv")
assert m["outputs"]["calib.md"] == h("cal3/calib.md") and m["primary"] == infer.PRIMARY
for f in ("calibrate.py", "infer.py", "hodge.py", "bounded.py"):
    assert m["code"][f] == h(f"{sys.argv[1]}/{f}"), f
assert m["args"]["kinds"] == infer.PRIMARY["kind"] and m["task_seeds"], m["args"]
rows = list(csv.DictReader(open("cal3/calib.csv")))
assert {r["world"] for r in rows} == {"hetero", "skewfactor", "mixture", "rare1"}
assert any(r["test"].startswith("ball coverage") for r in rows)
# the rare-event counterexample: mean zero, bounded, yet the exact-looking test rejects most nulls
w = calibrate.World([[[0.0 if i == p else rnd_ for i, rnd_ in enumerate((0.01,) * 6)] for _ in range(6)] for p in range(6)], "rare1")
rnd = random.Random(16)
rej = sum(infer.signflip([w.draw(rnd)]) <= 0.05 for _ in range(200)) / 200
assert rej > 0.5, rej
PY
# the stats spec's omnibus design (2 independent groups x 2 assays), both tests and sign-flip only
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal3o --sims 0 --omnibus 4:3:2:2 \
    --omnibus-sims 4 --omnibus-B 19 --chunk 2 --workers 1 > cal3o.log 2>&1 || fail "calibrate.py --omnibus: $(tail -5 cal3o.log)"
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal3f --sims 0 --omnibus 4:3:2:2 \
    --omnibus-sims 4 --chunk 2 --omnibus-plants none --omnibus-tests flip --workers 1 > cal3f.log 2>&1 \
    || fail "calibrate.py --omnibus-tests flip: $(tail -5 cal3f.log)"
$PY - <<'PY' || fail "omnibus design rows"
import csv
o = list(csv.DictReader(open("cal3o/calib.csv")))
f = list(csv.DictReader(open("cal3f/calib.csv")))
assert {r["test"] for r in o} == {"omnibus boot residual", "omnibus sign-flip"} and any(r["effect"] != "null" for r in o)
assert {r["test"] for r in f} == {"omnibus sign-flip"} and {r["effect"] for r in f} == {"null"}
assert all((r["G"], r["C"]) == ("2", "2") for r in o + f)
PY

# 17. bounded-scale sensitivity: a transitive logistic ladder (no ordinal cycle) has raw-scale curl;
#     the logistic node-additive model removes it, while a sign-reversing cycle on top survives
$PY - "$T" <<'PY' || fail "bounded-scale sensitivity"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import analyze, bounded
rnd = random.Random(17)
names = [f"x{t}" for t in range(6)]
u = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
def rows_for(cycle):
    rows = []
    for jj, j in enumerate(names):
        for ii, i in enumerate(names):
            for r in range(4):
                if i == j:
                    q = 0.05 + rnd.gauss(0, 1e-5)
                else:
                    q = bounded.sigmoid(math.log(0.05 / 0.95) + u[ii] - u[jj])
                    q += cycle.get((ii, jj), 0.0) - cycle.get((jj, ii), 0.0) + rnd.gauss(0, 1e-5)
                rows.append({"cond": "off", "frac": 0.05, "G": 5.0, "mode": "sham" if i == j else "invade", "i": i,
                             "j": j, "rep": r, "s": q - 0.05, "f0": 0.05, "missed": False})
    return rows
reg = None
rows = rows_for({})
out, detail, blocks, joint, subs = analyze.matrices(rows, None, sims=49, registry=reg, kind="residual")
assert out[0]["triads_cyclic"] == 0 and out[0]["noise_corrected"] > 0.005, out[0]["noise_corrected"]
srows, mrows = analyze.scale_sensitivity(rows, blocks, ["logit:0.001", "asin"], ["logistic", "strength"], 49, 49)
ms = {m["model"]: m for m in mrows}
for nm in ("logistic", "strength"):
    assert ms[nm]["C_fit"] > 0.95 * ms[nm]["T_C"] and ms[nm]["share_res_nc"] < 0.02 * ms[nm]["share_nc_raw"], ms[nm]
sc = {s["scale"]: s for s in srows}
assert sc["logit:0.001"]["noise_corrected"] < 1e-3 and abs(sc["raw"]["cyclic_share"] - out[0]["cyclic_share"]) < 1e-12, sc
rows = rows_for({(0, 1): 0.06, (1, 2): 0.06, (2, 0): 0.06})
out, detail, blocks, joint, subs = analyze.matrices(rows, None, sims=49, registry=reg, kind="residual")
srows, mrows = analyze.scale_sensitivity(rows, blocks, [], ["logistic"], 49, 49)
assert mrows[0]["survival"] > 0.3 and mrows[0]["share_res_nc"] > 0.01, mrows[0]
PY
$PY "$T/analyze.py" --root root3 --out an3s --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --sims 50 \
    --bounded-sims 20 > an3s.log 2>&1 || fail "analyze.py (bounded outputs): $(tail -5 an3s.log)"
[ -s an3s/scale.csv ] && [ -s an3s/bounded.csv ] && grep -q "Bounded-scale sensitivity" an3s/summary.md \
    || fail "analyze.py wrote no bounded-scale tables"

# 18. common fixed-step clock: every run read at the same step (exactly, at a checkpoint); T from
#     horizon.py on a selection of cells; an extinct read is the unconditional endpoint s = -f0
$PY "$T/horizon.py" --root root3 --plan plan3.jsonl --select mode=sham --generations 0.25 --grid 300 --out hz3.json \
    > hz3.log 2>&1 || fail "horizon.py: $(tail -3 hz3.log)"
$PY "$T/analyze.py" --root root3 --out an3t --plan plan3.jsonl --clock steps --horizon hz3.json --sims 50 --scales "" \
    --bounded "" > an3t.log 2>&1 || fail "analyze.py --clock steps: $(tail -5 an3t.log)"
$PY - "$T" <<'PY' || fail "fixed-step clock / extinction"
import csv, json, sys
sys.path.insert(0, sys.argv[1]); import analyze
hz = json.load(open("hz3.json"))
assert hz["T"] % 300 == 0 and hz["T2"] == 2 * hz["T"] and hz["cells"] and all(c["id"].split("_")[3] == "sham" for c in hz["cells"]), hz
runs = list(csv.DictReader(open("an3t/runs.csv")))
Ws = {float(x["W"]) for x in runs}
assert Ws == {float(hz["T"]), float(hz["T2"])} or Ws == {float(hz["T"])}, Ws
for x in runs:
    if x["missed"] == "False":
        assert float(x["steps_at"]) == float(x["W"]) and float(x["rel_err"]) == 0.0, x
inp = json.load(open("an3t/inputs.json"))
assert inp["clock"] == "steps" and inp["horizon"]["T"] == hz["T"]
rec = {"id": "x", "j": "A", "i": "B", "mode": "invade", "frac": 0.1, "cond": "off", "rep": 0, "n0": 100, "m": 10,
       "f0": 0.1, "points": [{"steps": 300, "score": None, "extinct": True, "n": 0, "births": 40, "generations": 0.4,
                              "invader_lost": False}]}
r = analyze.run_rows([rec], {}, [300.0], 0.1, clock="steps")
assert r[0]["s"] == -0.1 and r[0]["extinct"] and r[0]["gens"] == 0.4, r
PY

# 20. the error-bank planner (review round 3): separate home-regime cores, the registered indexed
#     seed allocation (slot / donor / predator / engine-reseed formulas), the seed-overlap refusal,
#     and the runner's progress file
cat > design20.json <<EOF
{"name": "t20", "snapshots": {"A": "$W/A.json", "B": "$W/B.json", "C": "$W/C.json", "D": "$W/As.json"},
 "conditions": {"off": 0, "predA2": 2}, "fractions": [0.05], "replicates": 3, "steps": 600, "checkpoint_every": 300,
 "log_every": 300, "cores": [["x", ["A", "B"]], ["y", ["C", "D"]]],
 "seed_scheme": {"type": "indexed", "namespace": "t20", "slot_base": 1000000000, "donor_base": 1100000000,
                 "pred_base": 1200000000, "reseed_base": 2000000000, "assays": ["off", "predA2"]}}
EOF
$PY "$T/plan.py" design20.json > plan20.jsonl || fail "plan.py (indexed cores)"
$PY - <<'PY' || fail "indexed seed allocation"
import json
cells = [json.loads(l) for l in open("plan20.jsonl")]
assert len(cells) == 2 * 4 * 2 * 3, len(cells)          # 2 cores x (2 pairs + 2 shams) x 2 assays x 3 reps
assert not any({c["resident_name"], c["invader_name"]} in ({"A", "C"}, {"A", "D"}, {"B", "C"}, {"B", "D"}) for c in cells)
idx = {"A": (0, 0), "B": (0, 1), "C": (1, 0), "D": (1, 1)}
for c in cells:
    h, j = idx[c["resident_name"]]
    i = idx[c["invader_name"]][1]
    u = 3 * (2 * h + j) + c["replicate"]
    a = ["off", "predA2"].index(c["condition"])
    assert c["slot_seed"] == 1000000000 + u and c["donor_seed"] == 1100000000 + 2 * u + i, c
    assert c["reseed"] == 2000000000 + 2 * u + a and c["pred_seed"] == (1200000000 + u if a else None), c
    assert c["seed_namespace"] == "t20" and c["core"] == ("x" if h == 0 else "y")
PY
$PY "$T/plan.py" design20.json --avoid plan20.jsonl > /dev/null 2> avoid20.log
[ $? = 2 ] && grep -q "seed(s) also used" avoid20.log || fail "plan.py did not refuse seeds used by an archived plan"
$PY "$T/plan.py" design20.json --avoid plan3.jsonl > /dev/null 2>&1 || fail "plan.py refused a disjoint archive"
$PY - <<'PY' || fail "the runner's progress file"
import json
p = json.load(open("root3/progress.json"))
assert p["total"] == 27 and p["state"] == "all done" and p["failed"] == [] and p["workers"] == 2, p
PY

# 21. review round 3, P1-1: generating k-unit datasets from a K-unit bank must give the means the
#     bank's noise (iid draws, WITH replacement, variance restored); k of K without replacement
#     keeps only (1 - k/K) of it (here 0.75) and is only a labelled diagnostic
$PY - "$T" <<'PY' || fail "empirical bank resampling"
import random, sys
sys.path.insert(0, sys.argv[1]); import calibrate, infer
rnd = random.Random(21)
N, K, k = 4, 40, 10
bank = [[[0.0 if i == p else rnd.gauss(0, 1) for i in range(N)] for _ in range(K)] for p in range(N)]
res = infer.residual_units(bank)
target = sum(sum(x * x for x in u) for col in res for u in col) / K / k   # sum over columns of tr(S_K) / k (S_K: n-1)
def energy(world, n=4000):
    w = calibrate.World(bank, world, k=k)
    tot = 0.0
    for _ in range(n):
        z = w.draw(rnd)
        tot += sum(sum(v * v for v in mp) for mp in infer.column_means(z))
    return tot / n / target
e_iid, e_wor = energy("empirical"), energy("empirical-wor")
print("mean-noise energy / target: with replacement", round(e_iid, 3), "without", round(e_wor, 3))
assert abs(e_iid - 1.0) < 0.05 and abs(e_wor - (1 - k / K)) < 0.05, (e_iid, e_wor)
PY
# the bank mode: omnibus draws from an error bank's primary blocks (assays joint, regimes independent)
$PY - "$T" <<'PY' || fail "building the toy bank"
import json, random, sys
sys.path.insert(0, sys.argv[1])
rnd = random.Random(211)
pbs = []
for g in ("np", "p4"):
    for c in ("off", "predA4"):
        z = [[[0.0 if i == p else rnd.gauss(0, 0.02) for i in range(4)] for _ in range(12)] for p in range(4)]
        pbs.append({"cond": c, "frac": 0.05, "G": 13500.0, "group": g, "names": [f"{g}{t}" for t in range(4)],
                    "reps": list(range(12)), "z": z, "zq": z, "status": "formal"})
json.dump({"schema": "finfolk.invasion.blocks/2", "blocks": [], "primary_blocks": pbs}, open("bank21.json", "w"))
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal21 --sims 0 --bank bank21.json --bank-k 6 \
    --bank-sims 4 --bank-outer 2 --bank-inner 2 --chunk 2 --omnibus-B 19 --workers 1 > cal21.log 2>&1 \
    || fail "calibrate.py --bank: $(tail -5 cal21.log)"
$PY - <<'PY' || fail "bank calibration rows"
import csv, json
rows = list(csv.DictReader(open("cal21/calib.csv")))
assert {r["world"] for r in rows} == {"bank", "bank-gauss", "bank outer0", "bank outer1"}, {r["world"] for r in rows}
assert all((r["G"], r["C"], r["k"]) == ("2", "2", "6") for r in rows)
m = json.load(open("cal21/manifest.json"))
assert m["bank"]["K"] == 12 and m["bank"]["groups"] == ["np", "p4"], m["bank"]
PY

# 22. review round 3, P1-2: the primary matrices are built per home regime, explicitly. Two disjoint
#     complete registered cores (no cross-home cell) give two formal primary blocks per assay and a
#     formal four-block omnibus (the pooled clique kept one regime); one missing primary observation
#     makes its block and the omnibus descriptive
$PY - "$T" <<'PY' || fail "explicit home-regime primary blocks"
import random, sys
sys.path.insert(0, sys.argv[1]); import analyze
rnd = random.Random(22)
cores = {"x": ["x1", "x2", "x3"], "y": ["y1", "y2", "y3"]}
reg, rows = {}, []
for c in ("off", "predA"):
    for core in cores.values():
        for j in core:
            for i in core:
                mode = "sham" if i == j else "invade"
                reg.setdefault((c, 0.05), {})[(i, j, mode)] = {0, 1, 2}
                for r in range(3):
                    rows.append({"cond": c, "frac": 0.05, "G": 13500.0, "mode": mode, "i": i, "j": j, "rep": r,
                                 "s": (0.0 if i == j else 0.03 * (int(i[1]) - int(j[1]))) + rnd.gauss(0, 0.003),
                                 "f0": 0.05, "missed": False})
out, detail, blocks, joint, subs = analyze.matrices(rows, None, sims=49, registry=reg, cores=cores)
assert all(m["status"].startswith("descriptive: the plan registers separate cores") for m in out), [m["status"] for m in out]
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 49)
assert sorted(k[3] for k in pb) == ["x", "x", "y", "y"] and all(b["status"] == "formal" for b in pb.values()), pb.keys()
assert len(pj) == 1 and pj[0]["status"] == "formal" and pj[0]["required"] == "off/x off/y predA/x predA/y", pj
assert pj[0]["p_lof_flip"] is not None and pj[0]["p_res_flip"] is not None and "claim_beyond_bounded" in pj[0]
rows_m = [x for x in rows if not (x["cond"] == "predA" and (x["i"], x["j"], x["rep"]) == ("y1", "y2", 2))]
pr, pb, pj = analyze.primary_blocks(rows_m, None, reg, cores, 49)
assert pb[("predA", 0.05, 13500.0, "y")]["status"].startswith("descriptive") and pb[("off", 0.05, 13500.0, "y")]["status"] == "formal"
assert pj[0]["status"].startswith("descriptive: primary block(s) predA/y") and pj[0].get("p_lof_flip") is None, pj
# cross-home cells registered (and incomplete) do not block complete cores
reg_x = {k: dict(v) for k, v in reg.items()}
reg_x[("off", 0.05)][("x1", "y1", "invade")] = {0, 1, 2}
pr, pb, pj = analyze.primary_blocks(rows, None, reg_x, cores, 49)
assert pb[("off", 0.05, 13500.0, "x")]["status"] == "formal" and pj[0]["status"] == "formal"
assert analyze.cores_from_plan({"c1": {"core": "x", "resident_name": "x1", "invader_name": "x2", "mode": "invade"}}) == {"x": ["x1", "x2"]}
PY

# 23. review round 3, P2-4: a fixed-step window is read at exactly that step (a 14,000-step checkpoint
#     is not the 13,500-step window), and formal decisions need the window in the horizon registration
$PY - "$T" <<'PY' || fail "exact fixed-step reads"
import random, sys
sys.path.insert(0, sys.argv[1]); import analyze
rec = {"id": "x", "j": "A", "i": "B", "mode": "invade", "frac": 0.05, "cond": "off", "rep": 0, "n0": 100, "m": 5,
       "f0": 0.05, "points": [{"steps": s, "score": 0.01, "extinct": False, "n": 90, "births": 100, "generations": 1.0,
                              "invader_lost": False} for s in (12000, 14000)]}
r = analyze.run_rows([rec], {}, [13500.0, 14000.0], 0.10, clock="steps")
assert r[0]["missed"] and r[0]["s"] is None and not r[1]["missed"] and r[1]["steps_at"] == 14000, r
rnd = random.Random(23)
names = ["a", "b", "c"]
rows = [{"cond": "off", "frac": 0.05, "G": 14000.0, "mode": "sham" if i == j else "invade", "i": i, "j": j, "rep": rep,
         "s": rnd.gauss(0, 0.01), "f0": 0.05, "missed": False} for i in names for j in names for rep in range(3)]
reg = {("off", 0.05): {(i, j, "sham" if i == j else "invade"): {0, 1, 2} for i in names for j in names}}
out, *_ = analyze.matrices(rows, None, sims=19, registry=reg, windows_registered={13500.0, 27000.0})
assert out[0]["status"] == "descriptive: window not in the horizon registration", out[0]["status"]
out, *_ = analyze.matrices(rows, None, sims=19, registry=reg, windows_registered={14000.0, 28000.0})
assert out[0]["status"] == "formal"
PY

# 24. review round 3, P2-3: the frozen co-primary and its decision. The family threshold is 0.05/12,
#     the primary omnibus carries H1, H1b and the claim, and calibrate.py --compound evaluates H1, H1b
#     and their conjunction in a transitive bounded world (support-preserving endpoints)
$PY - "$T" <<'PY' || fail "co-primary constants"
import sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
assert abs(bounded.ALPHA_FAMILY - 0.05 / 12) < 1e-15 and bounded.ALPHA_FAMILY in calibrate.ALPHAS
assert bounded.CO_PRIMARY_MODEL == "logistic"
PY
$PY "$T/calibrate.py" --blocks an3s/blocks.json --key off/0.1/0.25 --out cal24 --sims 0 --compound 4:4:2 \
    --compound-sims 4 --workers 1 > cal24.log 2>&1 || fail "calibrate.py --compound: $(tail -5 cal24.log)"
$PY - <<'PY' || fail "compound decision rows"
import csv
rows = list(csv.DictReader(open("cal24/calib.csv")))
tests = {r["test"] for r in rows}
assert {"H1 raw sign-flip omnibus", "H1b logistic residual sign-flip omnibus", "claim: H1 and H1b"} <= tests, tests
assert any(abs(float(r["alpha"]) - 0.05 / 12) < 1e-12 for r in rows)
assert {r["effect"] for r in rows if r["test"] == "claim: H1 and H1b"} >= {"bounded ladder",
        "bounded ladder + d_C=0.02 in all conditions", "bounded ladder + d_C=0.03 in one condition"}
assert any(r["test"].startswith("feasible (no clipped mean)") for r in rows)
PY

# 19. self-tests of the inference and bounded-scale modules
$PY "$T/infer.py" > /dev/null || fail "infer.py self-test"
$PY "$T/bounded.py" > /dev/null || fail "bounded.py self-test"
echo "invasion_tooling: ok"
