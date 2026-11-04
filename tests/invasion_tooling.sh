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
#  24. the co-primary decision: family threshold 0.05/12, H1 / H1b / claim calibration (from the
#      pilot blocks, and from an error bank's own primary blocks: their fits, items and cell SDs).
#  25. --prune: scored cells lose their checkpoints (hashes kept, births gzipped), analyses unchanged,
#      byte-identical replay, a failed score check prunes nothing, the disk guard stops (fail closed).
#  Review round 4:
#  22. (+) the primary groups frozen from the registration: a legacy regime with no result, cores plus
#      secondary cross-home pairs end to end;
#  26. a bank is calibrated only if it is the registered one (spec + plan; --bank-exploratory otherwise);
#  27. exact null means in the compound world, the endpoint law's moments, plant diagnostics, feasible plants;
#  28. an unconverged fit decides nothing (analysis: invalid; calibration: a non-rejection, counted);
#  29. replay prerequisites before pruning, the store, --update-tools keeping versions, revalidated
#      interrupted prunes, the durable write order (traced);
#  30. the disk guard's stop path with an unwritable disk; guaranteed cleanup of running cells.
#  Review round 5:
#  29. (+) the replay dependencies durable before any deletion (store blobs, store/, the binary, bin/, the
#      root; a first pin of the binary), and --replay routed to a store-capable driver when a path-only
#      legacy cell's snapshot has moved;
#  31. the registered bank is the approved plan with its policies (state, predators); a failed plant
#      construction or source fit is a counted power failure, never power at the target.
#  Preregistered calibration gate (the round-5 "not in this PR" list):
#  33. the registered bounded marginal law (exact moments or failure; Bernoulli / point mass; alternatives
#      keep v / (mu (1 - mu)); the exact quantile);
#  34. the joint bounded worlds J0, J8, R05-D, R05-C, R01-D, R01-C;
#  35. the registered plant (probability scale, grid first crossing + bisection, 1e-4 relative);
#  36. one invalid-dataset path (saturated fits, failed projections, non-finite results: unavailable; the
#      gate screen counts an unavailable null decision as a rejection);
#  37. gate.py: the frozen manifest before any computation, the schedule and seeds, refusals, the decision;
#  38. the bank's original identity (item IDs, snapshot hashes, all 28,800 cells);
#  39. the headline claim: strict registration, a passed gate, T only; the prose; the confirmation seeds.
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
# (a toy bank: not the registered specification, so --bank-exploratory; step 26 checks the registered path)
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal21 --sims 0 --bank bank21.json --bank-k 6 \
    --bank-sims 4 --bank-outer 2 --bank-inner 2 --chunk 2 --omnibus-B 19 --workers 1 --bank-exploratory > cal21.log 2>&1 \
    || fail "calibrate.py --bank: $(tail -5 cal21.log)"
$PY - <<'PY' || fail "bank calibration rows"
import csv, json
rows = list(csv.DictReader(open("cal21/calib.csv")))
assert {r["world"] for r in rows} == {"bank", "bank-gauss", "bank outer0", "bank outer1"}, {r["world"] for r in rows}
assert all((r["G"], r["C"], r["k"]) == ("2", "2", "6") and r["key"] == "bank (exploratory)" for r in rows)
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
assert analyze.cores_from_plan({"c1": {"core": "x", "resident_name": "x1", "invader_name": "x2", "mode": "invade"},
                                "c2": {"core": "x", "resident_name": "x2", "invader_name": "x2", "mode": "sham"}}) == {"x": ["x1", "x2"]}
# review round 4, P1-1: the required groups are frozen from the registration. A legacy plan (one pooled
# 6-item matrix, home regimes from --meta) whose regime y has no finished cell at all: the omnibus
# must stay the registered four-block one (descriptive), not become a formal two-block test
meta = {nm: {"regime": nm[0]} for nm in ("x1", "x2", "x3", "y1", "y2", "y3")}
reg_l = {(c, 0.05): {(i, j, "sham" if i == j else "invade"): {0, 1, 2} for i in meta for j in meta} for c in ("off", "predA")}
rows_x = [x for x in rows if x["i"][0] == "x" and x["j"][0] == "x"]
pr, pb, pj = analyze.primary_blocks(rows_x, meta, reg_l, None, 49)
assert len(pj) == 1 and pj[0]["required"] == "off/x off/y predA/x predA/y", pj
assert pj[0]["status"].startswith("descriptive: primary block(s)") and "off/y" in pj[0]["status"] \
    and "predA/y" in pj[0]["status"] and pj[0].get("p_lof_flip") is None and pj[0].get("claim_beyond_bounded") is None, pj
assert {r["group"] for r in pr if r["cond"] == "off"} == {"x", "y"}, pr   # the empty regime is reported, not dropped
pr, pb, pj = analyze.primary_blocks(rows, meta, reg_l, None, 49)        # both regimes finished: formal
assert pj[0]["status"] == "formal", pj[0]["status"]
PY
# ... and end to end: a derived-seed plan with two cores plus secondary cross-home pairs (both directions)
# keeps the cores' registered membership, so the primary analysis stays the four formal core blocks
cat > design22.json <<EOF
{"name": "t22", "snapshots": {"x1": "$W/A.json", "x2": "$W/B.json", "x3": "$W/C.json", "y1": "$W/As.json",
 "y2": "$W/Bs.json", "y3": "$W/Cs.json"}, "conditions": {"off": 0, "predA": 2}, "fractions": [0.05], "replicates": 3,
 "steps": 13500, "checkpoint_every": 4500, "log_every": 1000, "cores": [["x", ["x1", "x2", "x3"]], ["y", ["y1", "y2", "y3"]]],
 "pairs": [["x1", "y1"], ["x2", "y2"]], "both": true}
EOF
$PY "$T/plan.py" design22.json > plan22.jsonl || fail "plan.py (cores + secondary cross-home pairs)"
$PY - "$T" <<'PY' || fail "a plan's secondary cross-home pairs changed its registered cores"
import json, random, sys
sys.path.insert(0, sys.argv[1]); import analyze
plan = {c["id"]: c for c in (json.loads(l) for l in open("plan22.jsonl"))}
cross = [c for c in plan.values() if c["mode"] == "invade" and c["resident_name"][0] != c["invader_name"][0]]
assert len(cross) == 4 * 2 * 3 and {c["core"] for c in cross} == {"x", "y"}, len(cross)   # tagged by the resident's core
cores = analyze.cores_from_plan(plan)
assert cores == {"x": ["x1", "x2", "x3"], "y": ["y1", "y2", "y3"]}, cores
reg = analyze.registry_from_plan(plan)
rnd = random.Random(222)
rows = [{"cond": c["condition"], "frac": c["fraction"], "G": 13500.0, "mode": c["mode"],
         "i": c["invader_name"] if c["mode"] == "invade" else c["resident_name"], "j": c["resident_name"], "rep": c["replicate"],
         "s": (0.0 if c["mode"] == "sham" else 0.02 * (int(c["invader_name"][1]) - int(c["resident_name"][1]))) + rnd.gauss(0, 0.003),
         "f0": 0.05, "missed": False} for c in plan.values()]
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 49, windows_registered={13500.0, 27000.0})
assert sorted(pb) == sorted((c, 0.05, 13500.0, g) for c in ("off", "predA") for g in ("x", "y")), sorted(pb)
assert all(b["status"] == "formal" and b["names"] == cores[k[3]] for k, b in pb.items()), [(k, b["status"]) for k, b in pb.items()]
assert len(pj) == 1 and pj[0]["status"] == "formal" and pj[0]["required"] == "off/x off/y predA/x predA/y", pj
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
# ... and from an error bank's own four primary blocks: each group / condition is the bank's own
#     fitted ladder over its own items (not resampled) with its own cells' SDs
$PY - <<'PY' || fail "a positive toy bank"
import json
b = json.load(open("bank21.json"))
for pb in b["primary_blocks"]:
    pb["zq"] = [[[0.0 if i == p else 0.05 + abs(x) for i, x in enumerate(u)] for u in col] for p, col in enumerate(pb["z"])]
json.dump(b, open("bank24.json", "w"))
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal24b --sims 0 --bank bank24.json --bank-sims 0 \
    --compound 4:4:2 --compound-sims 2 --workers 1 --bank-exploratory > cal24b.log 2>&1 \
    || fail "calibrate.py --compound --bank: $(tail -5 cal24b.log)"
$PY - <<'PY' || fail "compound rows from the bank"
import csv
rows = [r for r in csv.DictReader(open("cal24b/calib.csv")) if r["scale"] == "compound"]
assert {"H1 raw sign-flip omnibus", "claim: H1 and H1b"} <= {r["test"] for r in rows}, rows[:2]
assert all(r["key"] == "bank (exploratory)" and r["world"].startswith("the bank's own") and (r["N"], r["G"], r["C"]) == ("4", "2", "2")
           for r in rows), rows[:2]
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal24c --sims 0 --bank bank24.json --bank-sims 0 \
    --compound 5:4:2 --compound-sims 2 --workers 1 --bank-exploratory > cal24c.log 2>&1 && fail "--compound --bank accepted N != the bank's"
grep -q "use 4:k:2" cal24c.log || fail "--compound --bank: no N:G hint ($(tail -2 cal24c.log))"
$PY - "$T" <<'PY' || fail "the bank's compound world must use the bank's own fits, items and cell SDs"
import json, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
pbs = {(p["group"], p["cond"]): p for p in json.load(open("bank24.json"))["primary_blocks"]}
zq = [[pbs[(g, c)]["zq"] for c in ("off", "predA4")] for g in ("np", "p4")]
calibrate.G.update({"bank_zq": zq})
seen = []
import math
calibrate.draw_marginal = lambda rnd, m: seen.append((m["mu"], math.sqrt(m["v_req"]))) or min(max(m["mu"] + 0.01 * rnd.random(), 0.0), 1.0)
calibrate.task_compound((None, 4, 3, 2, 1, "null", 9))
exp = []
for g in range(2):
    for c in range(2):
        par, sds = bounded.fit_matrix(zq[g][c])["params"], calibrate.cell_sds(zq[g][c])
        exp += [(bounded.sigmoid(par["mu"] + par["a"][i] + par["b"][p]), sds[p][i])   # (review round 4: never clipped)
                for p in range(4) for _r in range(3) for i in range(4) if i != p]
assert len(seen) == len(exp) == 2 * 2 * 4 * 3 * 3, (len(seen), len(exp))
assert all(abs(a - x) < 1e-12 and abs(b - y) < 1e-12 for (a, b), (x, y) in zip(seen, exp)), (seen[:3], exp[:3])
PY

# 25. pruning (the error bank's disk budget). A finished root is swept: every cell's arena, end and
#     periodic checkpoints go after its score check, the birth log stays gzipped (lossless) and every
#     deleted file's hash is recorded; the analysis of the pruned root equals the unpruned one's; a
#     replay rebuilds a pruned cell byte for byte (and a wrong record is a mismatch); a cell whose
#     score fails the check is left untouched; --prune runs prune new cells and leave no scratch
#     files; the disk guard stops through the STOP path, failing closed
cp -r root3dup root25 && cp -r root3dup root25c   # root3dup: step 7's complete 27-cell matrix, unpruned
$PY "$T/run.py" --root root25 --prune-finished > p25.log 2>&1 || fail "run.py --prune-finished: $(tail -3 p25.log)"
$PY - <<'PY' || fail "pruned cells: checkpoints gone, birth log gzipped losslessly, hashes recorded"
import glob, gzip, hashlib, json, os
cells = sorted(glob.glob("root25/cells/*/done.json"))
assert len(cells) == 27, len(cells)
for p in cells:
    d, done = os.path.dirname(p), json.load(open(p))
    pr, left = done["pruned"], set(os.listdir(d))
    assert not any(f == "arena.json" or f.startswith("end.") or f == "run.births.csv" for f in left), left
    assert {"score.json", "arena.manifest.json", "run.csv", "run.births.csv.gz", "cell.json"} <= left, left
    assert pr["removed"]["arena.json"] == done["outputs"]["arena.json"] and pr["removed"]["end.json"] == done["outputs"]["end.json"]
    assert len(pr["removed"]) == 3, pr["removed"]          # arena, end and the last step's duplicate of end.json
    assert hashlib.sha256(gzip.open(os.path.join(d, "run.births.csv.gz")).read()).hexdigest() == done["outputs"]["run.births.csv"]
    assert "--replay" in pr["replay"]
PY
$PY "$T/run.py" --root root25 --prune-finished > p25b.log 2>&1 && grep -q "0 finished cells pruned now, 27 already pruned" p25b.log \
    || fail "a second sweep is not a no-op: $(tail -2 p25b.log)"
$PY "$T/analyze.py" --root root25 --out an25 --plan plan3.jsonl --windows 0.25 --max-window-error 0.6 --no-power --sims 50 > an25.log 2>&1 \
    || fail "analyze.py (pruned root): $(tail -5 an25.log)"
cmp -s an3/matrix.csv an25/matrix.csv && cmp -s an3/runs.csv an25/runs.csv || fail "the pruned root analyses differently"
$PY "$T/run.py" --root root25 --replay off_f100_B_A_r02 --out rp25 > rp25.log 2>&1 || fail "replay: $(tail -8 rp25.log)"
grep -q "replay off_f100_B_A_r02: identical" rp25.log && cmp -s rp25/end.json root3dup/cells/off_f100_B_A_r02/end.json \
    && cmp -s rp25/arena.json root3dup/cells/off_f100_B_A_r02/arena.json || fail "the replay is not byte-identical"
$PY - <<'PY' || fail "tampering with a recorded hash"
import json
p = "root25/cells/off_f100_C_sham_r01/done.json"
d = json.load(open(p)); d["outputs"]["end.json"] = "0" * 64; json.dump(d, open(p, "w"))
PY
$PY "$T/run.py" --root root25 --replay off_f100_C_sham_r01 --out rp25t > rp25t.log 2>&1
[ $? = 8 ] && grep -q "DIFFERENT end.json" rp25t.log || fail "a replay against a wrong record did not report a mismatch"
$PY "$T/run.py" --root root25 --replay off_f100_B_A_r02 --out rp25 > /dev/null 2>&1 && fail "replay into a non-empty --out"
$PY - <<'PY' || fail "corrupting a score"
import hashlib, json
d = "root25c/cells/off_f100_A_B_r00"
s = json.load(open(f"{d}/score.json")); s["derivation"]["ok"] = False
open(f"{d}/score.json", "w").write(json.dumps(s, indent=1, sort_keys=True) + "\n")
done = json.load(open(f"{d}/done.json"))
done["outputs"]["score.json"] = hashlib.sha256(open(f"{d}/score.json", "rb").read()).hexdigest()
json.dump(done, open(f"{d}/done.json", "w"))
PY
$PY "$T/run.py" --root root25c --prune-finished > p25c.log 2>&1
[ $? = 1 ] && grep -q "NOT PRUNED off_f100_A_B_r00: score derivation not ok" p25c.log \
    && [ -f root25c/cells/off_f100_A_B_r00/arena.json ] && [ -f root25c/cells/off_f100_A_B_r00/end.json ] \
    && [ ! -f root25c/cells/off_f100_A_C_r00/arena.json ] || fail "a cell with a failed score check was pruned: $(tail -3 p25c.log)"
$PY "$T/run.py" --plan plan.jsonl --root root25r --binary "$BIN" --workers 2 --prune > r25.log 2>&1 || fail "run.py --prune: $(tail -3 r25.log)"
$PY "$T/run.py" --plan plan.jsonl --root root25r --binary "$BIN" --workers 2 --prune > r25b.log 2>&1
grep -q "2 already done" r25b.log && grep -q "0 finished cells pruned now, 2 already pruned" r25b.log \
    || fail "resume of pruned cells: $(tail -3 r25b.log)"
$PY - <<'PY' || fail "cells pruned by the runner"
import glob, json, os
for p in glob.glob("root25r/cells/*/done.json"):
    d, done = os.path.dirname(p), json.load(open(p))
    assert "pruned" in done and done.get("tmp_files_left") == 0, done.keys()
    assert not os.path.exists(f"{d}/tmp") and not os.path.exists(f"{d}/arena.json") and not os.path.exists(f"{d}/end.json"), os.listdir(d)
assert len(glob.glob("root25r/cells/*/done.json")) == 2
assert json.load(open("root25r/progress.json"))["prune"] is True
PY
$PY "$T/run.py" --plan plan.jsonl --root root25g --binary "$BIN" --workers 1 --disk-min "$W:999999999" > g25.log 2>&1
[ $? = 75 ] && grep -q "disk guard" root25g/STOP && ! ls root25g/cells/*/done.json > /dev/null 2>&1 \
    || fail "the disk guard did not stop the runner: $(tail -3 g25.log)"
grep -q "stopped by the disk guard" root25g/progress.json || fail "progress.json lacks the disk guard's reason"
rm -f root25g/STOP
$PY "$T/run.py" --plan plan.jsonl --root root25g --binary "$BIN" --workers 1 --disk-min "$W/no_such_dir:1" > g25b.log 2>&1
[ $? = 75 ] && grep -q "unreadable" root25g/STOP || fail "an unreadable disk reading did not fail closed"
$PY - "$T" <<'PY' || fail "disk guard defaults"
import os, sys
sys.path.insert(0, sys.argv[1]); import run
assert run.disk_guards(["none"], "/x") == [] and run.disk_guards(["/a:5", "/b/c:7"], "/x") == [("/a", 5), ("/b/c", 7)]
assert run.disk_guards(None, "/x") == ([("/", 10240), ("/mnt/c", 6000)] if os.path.ismount("/mnt/c") else [("/x", 1024)])
assert run.disk_problem([("/", 0)]) is None and "below" in run.disk_problem([("/", 1 << 40)])
PY

# 26. review round 4, P2-4: an error bank is calibrated only if it is the registered bank: the frozen
#     specification (assays, groups, items, K, formal blocks, the fixed-step horizon, aligned replicates,
#     unique keys, shapes) and the plan it was analysed from; --bank-exploratory runs anything else,
#     labelled exploratory
cat > design26.json <<EOF
{"name": "t26", "snapshots": {"np0": "$W/A.json", "np1": "$W/B.json", "np2": "$W/C.json", "np3": "$W/As.json",
 "p40": "$W/Bs.json", "p41": "$W/Cs.json", "p42": "$W/A.json", "p43": "$W/B.json"},
 "conditions": {"off": 0, "predA4": 4}, "fractions": [0.05], "replicates": 12, "steps": 13500, "checkpoint_every": 4500,
 "log_every": 1000, "cores": [["np", ["np0", "np1", "np2", "np3"]], ["p4", ["p40", "p41", "p42", "p43"]]],
 "pairs": [["np0", "p40"]], "both": true}
EOF
$PY "$T/plan.py" design26.json > plan26.jsonl || fail "plan.py (design26)"
$PY - "$T" <<'PY' || fail "building the registered toy bank"
import hashlib, json, math, random, sys
sys.path.insert(0, sys.argv[1]); import bounded
rnd = random.Random(26)
sha = hashlib.sha256(open("plan26.jsonl", "rb").read()).hexdigest()
pbs = []
for g in ("np", "p4"):
    names = [f"{g}{t}" for t in range(4)]
    a = [rnd.gauss(0, 0.8) for _ in range(4)]
    b = [rnd.gauss(0, 0.5) for _ in range(4)]
    for c in ("off", "predA4"):
        zq = [[[0.0 if i == p else min(1.0, max(0.0, bounded.sigmoid(-2.5 + a[i] + b[p]) + rnd.gauss(0, 0.01)))
                for i in range(4)] for _ in range(12)] for p in range(4)]
        z = [[[0.0 if i == p else u[i] - col[r][p] for i in range(4)] for r, u in enumerate(col)] for p, col in enumerate(zq)]
        pbs.append({"cond": c, "frac": 0.05, "G": 13500.0, "group": g, "names": names, "reps": list(range(12)),
                    "z": z, "zq": zq, "status": "formal"})
good = {"schema": "finfolk.invasion.blocks/2", "plan_sha256": sha, "analysis_sha256": "x", "clock": "steps",
        "blocks": [], "primary_blocks": pbs}
json.dump(good, open("bank26.json", "w"))
cells = [json.loads(l) for l in open("plan26.jsonl")]
registry = {}
for c in cells:
    registry.setdefault(c["core"], {})[c["resident_name"]] = c["resident_sha256"]
json.dump({"items": 4, "K": 12, "plan_sha256": sha, "state": "slot", "predators": {"off": 0, "predA4": 4},
           "steps": 13500, "registry": registry, "cells": len(cells)}, open("spec26.json", "w"))
# (prereg gate) the bank analysis' inputs.json, beside the export: every registered cell finished, the files read
json.dump({"plan": {"sha256": sha, "cells": len(cells)}, "clock": "steps", "complete": True, "registered_missing": [],
           "unregistered_finished": [], "identity_problems": [], "finished": len(cells), "cells_csv": {"cells": len(cells)},
           "snapshots": {nm: h for v in registry.values() for nm, h in v.items()}, "analysis_code": {"analyze.py": "x"}},
          open("inputs.json", "w"))
def variant(name, f):
    b = json.loads(json.dumps(good)); f(b); json.dump(b, open(name, "w"))
variant("bank26_offonly.json", lambda b: b.update(primary_blocks=[p for p in b["primary_blocks"] if p["cond"] == "off"]))
variant("bank26_desc.json", lambda b: b["primary_blocks"][3].update(status="descriptive: 1 of 192 registered cells missing"))
variant("bank26_misal.json", lambda b: b["primary_blocks"][1].update(reps=list(range(1, 13))))
variant("bank26_dup.json", lambda b: b["primary_blocks"].append(dict(b["primary_blocks"][0])))
variant("bank26_gens.json", lambda b: b.update(clock="gens"))
variant("bank26_shape.json", lambda b: b["primary_blocks"][2]["zq"][1].pop())
PY
# the review's failure scenario: twelve-item blocks of both regimes but only the off assay, with the old
# command line: accepted before, refused now (with the reason)
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal26o --sims 0 --bank bank26_offonly.json \
    --bank-sims 0 --compound 4:4:2 --compound-sims 2 --workers 1 > cal26o.log 2>&1
[ $? = 2 ] && grep -q "assays \['off'\], the spec registers \['off', 'predA4'\]" cal26o.log \
    || fail "an off-only bank was calibrated as the registered bank: $(tail -2 cal26o.log)"
cal26() {   # out bank extra...: exit status of a registered-bank compound run
    local out=$1 bank=$2; shift 2
    $PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out "$out" --sims 0 --bank "$bank" \
        --bank-plan plan26.jsonl --bank-spec spec26.json --bank-sims 0 --compound 4:4:2 --compound-sims 2 \
        --compound-variants null --workers 1 "$@" > "$out.log" 2>&1
}
cal26 cal26g bank26.json || fail "the registered toy bank was refused: $(tail -4 cal26g.log)"
for v in desc:status misal:"differ in items or replicates" dup:"duplicate (group, assay)" gens:"clock" \
         shape:"replicates, expected 12" offonly:"no predA4 block"; do
    nm=${v%%:*} why=${v#*:}
    cal26 "cal26_$nm" "bank26_$nm.json"; rc=$?
    [ $rc = 2 ] && grep -qF "$why" "cal26_$nm.log" || fail "bank variant $nm: exit $rc, expected a refusal naming '$why': $(tail -3 cal26_$nm.log)"
done
cp plan26.jsonl plan26_other.jsonl && echo "" >> plan26_other.jsonl   # another file: another hash
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal26p --sims 0 --bank bank26.json \
    --bank-plan plan26_other.jsonl --bank-spec spec26.json --bank-sims 0 --compound 4:4:2 --compound-sims 2 \
    --compound-variants null --workers 1 > cal26p.log 2>&1
[ $? = 2 ] && grep -q "the analysis bound plan" cal26p.log || fail "a bank checked against another plan was accepted"
cal26 cal26x bank26_offonly.json --bank-exploratory || fail "--bank-exploratory refused: $(tail -3 cal26x.log)"
$PY - "$T" <<'PY' || fail "registered vs exploratory bank rows / provenance"
import csv, json, sys
sys.path.insert(0, sys.argv[1]); import calibrate
g = list(csv.DictReader(open("cal26g/calib.csv")))
x = list(csv.DictReader(open("cal26x/calib.csv")))
assert g and all(r["key"] == "bank" for r in g) and all(r["key"] == "bank (exploratory)" for r in x), (g[:1], x[:1])
mg, mx = json.load(open("cal26g/manifest.json"))["bank"], json.load(open("cal26x/manifest.json"))["bank"]
assert mg["problems"] == [] and mg["plan"]["sha256"] and mx["problems"] and "EXPLORATORY" in open("cal26x/calib.md").read()
# the registered core membership: residents only (the secondary np0 <-> p40 pair adds nobody)
cells = [json.loads(l) for l in open("plan26.jsonl")]
assert any(c["mode"] == "invade" and {c["resident_name"], c["invader_name"]} == {"np0", "p40"} for c in cells)
assert calibrate.plan_cores(cells) == {"np": ["np0", "np1", "np2", "np3"], "p4": ["p40", "p41", "p42", "p43"]}
PY

# 27. review round 4, P2-5: the compound world's null means are the declared logistic ladder EXACTLY (no
#     clipping: a ladder with cells below 0.002 used to become another mean family), its endpoint law
#     has exactly those means (and the requested SDs where feasible, capped ones flagged), and every
#     alternative exports what it planted: clipping, d_add, the noiseless logistic-residual RMS d_res,
#     with the feasible family solved to its d_res target
$PY - "$T" <<'PY' || fail "exact null means / endpoint moments in the compound world"
import json, math, random, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
# the review's example: logits (-9, -7; -7, -5) clipped at 0.002 have a logit rectangle contrast of 1.2126
lg = lambda p: math.log(p / (1 - p))
cl = [min(max(bounded.sigmoid(x), 0.002), 0.998) for x in (-9.0, -7.0, -7.0, -5.0)]
assert abs((lg(cl[0]) - lg(cl[1]) - lg(cl[2]) + lg(cl[3])) - 1.2126) < 1e-3
# a ladder far below the old clip: every endpoint draw's mean is the ladder's own mean
rnd = random.Random(27)
a, b = [-3.0, -1.0, 0.5, 1.5], [0.0, 1.0, -1.0, 2.0]
pbs = {}
for g in range(2):
    for c in range(2):
        pbs[(g, c)] = [[[0.0 if i == p else bounded.sigmoid(-6.0 + a[i] - b[p]) * (1 + 0.05 * rnd.gauss(0, 1))
                         for i in range(4)] for _ in range(8)] for p in range(4)]
zq = [[pbs[(g, c)] for c in range(2)] for g in range(2)]
calibrate.G.update({"bank_zq": zq})
seen = []
calibrate.draw_marginal = lambda rnd_, m: seen.append(m["mu"]) or m["mu"]
calibrate.task_compound((None, 4, 3, 2, 1, "null", 9))
exp = []
for g in range(2):
    for c in range(2):
        par = bounded.fit_matrix(zq[g][c])["params"]
        exp += [bounded.sigmoid(par["mu"] + par["a"][i] + par["b"][p]) for p in range(4) for _r in range(3) for i in range(4) if i != p]
assert min(exp) < 0.002, min(exp)                     # cells the old clip moved
assert len(seen) == len(exp) and all(abs(x - y) <= 1e-15 * max(y, 1e-300) for x, y in zip(seen, exp)), \
    [(x, y) for x, y in zip(seen, exp) if x != y][:3]
PY
$PY - "$T" <<'PY' || fail "the zero-inflated Beta's moments"
import importlib, math, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate
rnd = random.Random(271)
n = 200000
xs = [calibrate._zib(rnd, 2e-5, 2e-5) for _ in range(n)]   # a near-certain loser: the old law clipped mu to 1e-4
m = sum(xs) / n
assert abs(m - 2e-5) < 5 * 2e-5 / math.sqrt(n), m
for mu, sd in ((2e-5, 2e-5), (0.01, 0.001), (0.02, 0.03), (0.3, 0.2), (0.7, 0.01), (0.5, 0.0)):
    z = calibrate.zib_moments(mu, sd)
    assert abs((1 - z["pz"]) * z["mb"] - mu) <= 1e-15 * mu and abs(z["sd"] - sd) <= 1e-9 * max(sd, 1e-12) and not z["capped"], (mu, sd, z)
z = calibrate.zib_moments(0.3, 0.47)       # beyond the Bernoulli bound: the pilot-sourced world caps it, flagged, mean kept
assert z["capped"] and z["sd"] < 0.47 and abs((1 - z["pz"]) * z["mb"] - 0.3) < 1e-15, z
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal27 --sims 0 --bank bank26.json \
    --bank-plan plan26.jsonl --bank-spec spec26.json --bank-sims 0 --compound 4:4:2 --compound-sims 2 --workers 1 \
    > cal27.log 2>&1 || fail "calibrate.py --compound (all variants): $(tail -4 cal27.log)"
$PY - "$T" <<'PY' || fail "the compound world's plant diagnostics"
import csv, sys
sys.path.insert(0, sys.argv[1]); import calibrate
d = {(r["quantity"], r["effect"]): r for r in csv.DictReader(open("cal27/diag.csv"))}
rows = {(r["test"], r["effect"], r["alpha"]): r for r in csv.DictReader(open("cal27/calib.csv"))}
for t in (0.01, 0.02, 0.03):
    lab = f"bounded ladder + feasible plant d_res={t} in all conditions"
    r = d[("d_res: noiseless logistic-residual RMS per planted condition", lab)]
    assert abs(float(r["min"]) - t) <= calibrate.PLANT_TOL * t and abs(float(r["max"]) - t) <= calibrate.PLANT_TOL * t, r
    assert ("clipped cells per planted condition", lab) in d
    assert rows[(f"plant at its target (feasible family: solved; refits converged): {lab}", "null", "0.95")]["x"] == "2"
    # (prereg gate: the registered plant is the probability-scale one, so it may clip; what it clipped is exported)
    assert ("d_res of the clipped null alone (c -> 0+)", lab) in d and ("plant amplitude c (probability scale)", lab) in d
for t in (0.01, 0.02, 0.03):
    lab = f"bounded ladder + d_C={t} in all conditions"
    assert ("d_add: RMS added circulation per planted condition", lab) in d and ("d_res: noiseless logistic-residual RMS per planted condition", lab) in d
assert float(d[("cells with a capped SD (share)", "bounded ladder")]["n"]) == 2
assert ("H1b invalid (a logistic fit did not converge): bounded ladder", "null", "0.95") in rows
PY

# 28. review round 4, P2-6: an unconverged fit decides nothing. With the optimizer cut to one iteration
#     (an unfinished fit), the primary omnibus' H1b and claim are invalid - not a rejection - in the
#     analysis, and calibration counts such datasets as non-rejections in the denominator
$PY - "$T" <<'PY' || fail "an unconverged logistic fit produced a formal decision"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import analyze, bounded
rnd = random.Random(28)
cores = {"x": ["x1", "x2", "x3", "x4"], "y": ["y1", "y2", "y3", "y4"]}
cyc = {(0, 1): 0.05, (1, 2): 0.05, (2, 0): 0.05}
reg, rows = {}, []
for c in ("off", "predA"):
    for core in cores.values():
        for jj, j in enumerate(core):
            for ii, i in enumerate(core):
                mode = "sham" if i == j else "invade"
                reg.setdefault((c, 0.05), {})[(i, j, mode)] = set(range(6))
                for r in range(6):
                    q = 0.05 if i == j else bounded.sigmoid(-2.0 + 0.6 * ii - 0.4 * jj) + cyc.get((ii, jj), 0.0) - cyc.get((jj, ii), 0.0)
                    rows.append({"cond": c, "frac": 0.05, "G": 13500.0, "mode": mode, "i": i, "j": j, "rep": r,
                                 "s": q - 0.05 + rnd.gauss(0, 0.003), "f0": 0.05, "missed": False})
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 49, bsims=9)
assert pj[0]["status"] == "formal" and pj[0]["both_rejected"] is True and pj[0]["h1b_valid"], pj   # the data reject
assert pj[0]["claim_beyond_bounded"] is None and "no calibration gate record" in pj[0]["claim_status"], pj   # (prereg gate)
# (review of #49, round 4, P2-3: probed / probe-certified fits and refits are reported with the H1b decision)
assert "; fits: 4, probed " in pj[0]["h1b_diagnostics"] and "; bootstrap refits: 36, probed " in pj[0]["h1b_diagnostics"] \
    and "probe-certified" in pj[0]["h1b_diagnostics"], pj[0]["h1b_diagnostics"]
lm0 = bounded.lm
bounded.lm = lambda model, cells, y, th0, iters=200, tol=1e-11: lm0(model, cells, y, th0, 1, tol)   # unfinished fits
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 49, bsims=9)
bounded.lm = lm0
j = pj[0]
assert j["status"] == "formal" and j["p_lof_flip"] is not None, j            # H1 needs no fit
assert j["claim_beyond_bounded"] is None and j["p_res_flip"] is None and j["p_res_boot"] is None, j
assert j["claim_status"].startswith("invalid: logistic mean fit(s) not converged") and "INVALID" in j["h1b_diagnostics"], j
assert all(r.get("p_res_flip") is None and r.get("fit_converged") is False for r in pr if "F_res" in r), pr
PY
$PY - "$T" <<'PY' || fail "calibration must count an unconverged H1b as a non-rejection"
import json, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
pbs = {(p["group"], p["cond"]): p for p in json.load(open("bank26.json"))["primary_blocks"]}
calibrate.G.update({"bank_zq": [[pbs[(g, c)]["zq"] for c in ("off", "predA4")] for g in ("np", "p4")]})
lm0 = bounded.lm
lm1 = lambda model, cells, y, th0, iters=200, tol=1e-11: lm0(model, cells, y, th0, 1, tol)
sf0 = getattr(calibrate, "_source_fit", bounded.fit_matrix)
def sf(zq):
    bounded.lm = lm0
    try:
        return sf0(zq)
    finally:
        bounded.lm = lm1
calibrate._source_fit = sf
bounded.lm = lm1
gk, cnt, n, *_ = calibrate.task_compound((None, 4, 6, 2, 3, "nominal", 28))
labels = {e for (t, e, a) in cnt if t == "claim: H1 and H1b"}
assert len(labels) == 6 and n == 3, (labels, n)
for e in labels:
    assert cnt[(f"H1b invalid (a logistic fit did not converge): {e}", "null", 0.95)] == n, e
    assert all(cnt[("claim: H1 and H1b", e, a)] == 0 and cnt[("H1b logistic residual sign-flip omnibus", e, a)] == 0
               for a in calibrate.ALPHAS), e
PY

# 29. review round 4, P1-2 / P2-3: pruning deletes nothing whose replay cannot be verified, and the
#     prune sweep finalizes like a new cell. A cell whose registered snapshot is gone, or from before
#     tool pinning, keeps its checkpoints; --update-tools keeps the replaced versions (a replay then
#     rebuilds them from DIR/store), and refuses if a finished cell needs a version the store lacks;
#     an interrupted prune is revalidated before it is finished; a cell pruned earlier whose replay
#     can no longer be verified stops the sweep; and the order of the writes is the durable one
for r in root29s root29l root29u root29r root29i root29f; do rm -rf $r; cp -r root3dup $r; done
$PY - <<'PY' || fail "preparing the replay-provenance roots"
import json
def edit(root, cid, f):
    for name in ("cell.json", "done.json"):
        p = f"{root}/cells/{cid}/{name}"
        d = json.load(open(p))
        f(d["cell"] if name == "done.json" else d, d, name)
        json.dump(d, open(p, "w"))
# root29s: one cell's registered resident path is gone (same registered content hash)
edit("root29s", "off_f100_A_B_r00", lambda c, d, n: c.update(resident=c["resident"].replace("/A.json", "/A_gone.json")))
# root29l: one cell from before tool pinning (no tool hashes)
p = "root29l/cells/off_f100_B_C_r01/done.json"
d = json.load(open(p)); del d["tools_sha256"]; json.dump(d, open(p, "w"))
PY
$PY "$T/run.py" --root root29s --prune-finished > p29s.log 2>&1 || fail "--prune-finished (gone snapshot): $(tail -3 p29s.log)"
grep -q "KEPT (checkpoints stay) off_f100_A_B_r00: replay provenance not established" p29s.log \
    && [ -f root29s/cells/off_f100_A_B_r00/end.json ] && [ -f root29s/cells/off_f100_A_B_r00/arena.json ] \
    && [ ! -f root29s/cells/off_f100_A_C_r00/end.json ] || fail "a cell whose snapshot is gone was pruned: $(tail -3 p29s.log)"
$PY "$T/run.py" --root root29l --prune-finished > p29l.log 2>&1 || fail "--prune-finished (legacy cell): $(tail -3 p29l.log)"
grep -q "KEPT (checkpoints stay) off_f100_B_C_r01: .*before tool pinning" p29l.log \
    && [ -f root29l/cells/off_f100_B_C_r01/end.json ] || fail "a cell without tool hashes was pruned: $(tail -3 p29l.log)"
$PY - <<'PY' || fail "the store keeps every version a pruned cell needs"
import glob, hashlib, json, os
st = {os.path.basename(p) for p in glob.glob("root29s/store/*")}
done = json.load(open("root29s/cells/off_f100_A_C_r00/done.json"))
man = json.load(open("root29s/cells/off_f100_A_C_r00/arena.manifest.json"))
need = {done["tools_sha256"][f] for f in ("invlib.py", "arena.py", "score.py")} | {man["resident"]["sha256"], man["invader"]["sha256"]}
assert need <= st, need - st
for p in glob.glob("root29s/store/*"):
    assert hashlib.sha256(open(p, "rb").read()).hexdigest() == os.path.basename(p) and not os.access(p, os.W_OK), p
PY
# --update-tools keeps the versions it replaces; the replay of a cell that ran them rebuilds them from the store
rm -rf T29 && cp -r "$T" T29 && echo "# (a later score.py)" >> T29/score.py
$PY "$T/run.py" --root root29u --prune-finished > p29u.log 2>&1 || fail "--prune-finished (root29u): $(tail -3 p29u.log)"
$PY T29/run.py --plan plan3.jsonl --root root29u --binary "$BIN" --workers 1 --update-tools > u29.log 2>&1 \
    || fail "--update-tools: $(tail -3 u29.log)"
cmp -s T29/score.py root29u/tools/score.py || fail "--update-tools did not replace score.py"
rm -rf rp29 && $PY "$T/run.py" --root root29u --replay off_f100_B_A_r02 --out rp29 > rp29.log 2>&1 \
    || fail "replay of a cell whose score.py was updated since: $(tail -4 rp29.log)"
grep -q "replay off_f100_B_A_r02: identical" rp29.log && grep -q '"tools_from": "the store' rp29/replay.json \
    && cmp -s rp29/end.json root3dup/cells/off_f100_B_A_r02/end.json || fail "the replay from stored versions is not identical"
$PY - <<'PY' || fail "preparing a cell that needs an unstored version"
import json
p = "root29r/cells/off_f100_C_A_r00/done.json"
d = json.load(open(p)); d["tools_sha256"]["score.py"] = "e" * 64; json.dump(d, open(p, "w"))
PY
$PY T29/run.py --plan plan3.jsonl --root root29r --binary "$BIN" --workers 1 --update-tools > u29r.log 2>&1
[ $? = 2 ] && grep -q "refused: finished cells need tool versions the store lacks" u29r.log && ! cmp -s T29/score.py root29r/tools/score.py \
    || fail "--update-tools discarded a version a finished cell needs: $(tail -2 u29r.log)"
# an interrupted prune (its record durable, a checkpoint still there) is revalidated: a score that no
# longer passes its check keeps the checkpoint
$PY "$T/run.py" --root root29i --prune-finished > p29i.log 2>&1 || fail "--prune-finished (root29i): $(tail -3 p29i.log)"
cp root3dup/cells/off_f100_A_B_r00/arena.json root29i/cells/off_f100_A_B_r00/
$PY - <<'PY' || fail "corrupting the interrupted cell's score"
import hashlib, json
d = "root29i/cells/off_f100_A_B_r00"
s = json.load(open(f"{d}/score.json")); s["derivation"]["ok"] = False
open(f"{d}/score.json", "w").write(json.dumps(s, indent=1, sort_keys=True) + "\n")
done = json.load(open(f"{d}/done.json"))
done["outputs"]["score.json"] = hashlib.sha256(open(f"{d}/score.json", "rb").read()).hexdigest()
json.dump(done, open(f"{d}/done.json", "w"))
PY
$PY "$T/run.py" --root root29i --prune-finished > p29i2.log 2>&1
[ $? = 1 ] && grep -q "NOT PRUNED off_f100_A_B_r00: score derivation not ok" p29i2.log && [ -f root29i/cells/off_f100_A_B_r00/arena.json ] \
    || fail "an interrupted prune was finished without revalidating the cell: $(tail -2 p29i2.log)"
# a cell pruned earlier whose replay can no longer be verified (it ran an arena.py version that is
# neither stored nor pinned)
$PY - <<'PY' || fail "breaking a pruned cell's provenance"
import json
p = "root29u/cells/off_f100_C_B_r01/done.json"
d = json.load(open(p)); d["tools_sha256"]["arena.py"] = "a" * 64; json.dump(d, open(p, "w"))
PY
$PY "$T/run.py" --root root29u --prune-finished > p29u2.log 2>&1
[ $? = 1 ] && grep -q "NOT PRUNED off_f100_C_B_r01: pruned earlier, and its replay can no longer be verified" p29u2.log \
    || fail "a pruned cell that can no longer be replayed went unnoticed: $(tail -2 p29u2.log)"
# the protocol, traced: the sweep and a new cell write and delete in the durable order (every kept file
# and the gzip flushed, the directory synced, done.json's rename then the directory synced, the deletions,
# the directory synced again); invlib.write_atomic syncs the directory after its rename. Review round 5:
# beyond the cell directory, the whole replay-dependency set is durable before the first deletion (every
# needed store blob, store/, the pinned binary, bin/ and the root), and a first pin of the binary is durable
rm -rf root29f/cells/off_f100_C_B_r02 && mkdir root29f/cells/off_f100_C_B_r02
grep '"id": "off_f100_C_B_r02"' plan3.jsonl > root29f/cells/off_f100_C_B_r02/cell.json
: > empty29.jsonl
$PY - "$T" "$BIN" <<'PY' > t29f.log 2>&1 || fail "the finalization protocol (traced): $(tail -3 t29f.log)"
import json, os, sys
sys.path.insert(0, sys.argv[1]); import invlib, run
ev = []
of, orp, orm = os.fsync, os.replace, os.remove
def fs(fd):
    ev.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
    return of(fd)
def rp(a, b):
    ev.append(("replace", os.path.abspath(b)))
    return orp(a, b)
def rm(p):
    ev.append(("remove", os.path.abspath(p)))
    return orm(p)
os.fsync, os.replace, os.remove = fs, rp, rm
root = os.path.abspath("root29f")
def check(d, what):
    e = [x for x in ev if x[1] == d or os.path.dirname(x[1]) == d]
    pr = json.load(open(f"{d}/done.json"))["pruned"]
    gone = {f"{d}/{f}" for f in list(pr["removed"]) + list(pr["compressed"])}
    i_done = e.index(("replace", f"{d}/done.json"))
    rms = [i for i, x in enumerate(e) if x[0] == "remove" and x[1] in gone]
    assert len(rms) == len(gone) == 4 and min(rms) > i_done, (what, e)
    for f in ("score.json", "run.csv", "arena.manifest.json", "run.births.csv.gz", "stdout.log"):
        assert any(x == ("fsync", f"{d}/{f}") for x in e[:i_done]), (what, f, e)
    assert ("fsync", d) in e[:i_done], (what, "the directory before done.json")
    assert ("fsync", d) in e[i_done + 1:min(rms)], (what, "the directory after done.json's rename, before deleting")
    assert e[-1] == ("fsync", d) and max(rms) < len(e) - 1, (what, "the directory after the deletions", e[-3:])
def deps(d, what):
    pr = json.load(open(f"{d}/done.json"))
    gone = {f"{d}/{f}" for f in list(pr["pruned"]["removed"]) + list(pr["pruned"]["compressed"])}
    first = min(i for i, x in enumerate(ev) if x[0] == "remove" and x[1] in gone)
    man = json.load(open(f"{d}/arena.manifest.json"))
    blobs = [pr["tools_sha256"][f] for f in ("invlib.py", "arena.py", "score.py")] + \
            [man[r]["sha256"] for r in ("resident", "invader") if man.get(r)]
    need = [f"{root}/store/{h}" for h in blobs] + [f"{root}/store", f"{root}/bin/evo_boids", f"{root}/bin", root]
    before = set(ev[:first])
    miss = [p for p in need if ("fsync", p) not in before]
    assert not miss, (what, "not durable before the first deletion:", miss)
run.prune_finished(root, lambda m: None)
check(f"{root}/cells/off_f100_A_C_r00", "sweep")
deps(f"{root}/cells/off_f100_A_C_r00", "sweep")
ev.clear()
getattr(run, "_SYNCED", set()).clear()      # (a cell worker is a new process)
getattr(run, "_STORE_OK", set()).clear()
assert run.run_cell(root, "off_f100_C_B_r02", prune=True) == 0
check(f"{root}/cells/off_f100_C_B_r02", "new cell")
deps(f"{root}/cells/off_f100_C_B_r02", "new cell")
ev.clear()
invlib.write_atomic(f"{root}/wa.txt", "x\n")
i = ev.index(("replace", f"{root}/wa.txt"))
assert ("fsync", root) in ev[i + 1:], ev
ev.clear()
rp = os.path.abspath("root29p")
assert run.main(["--plan", "empty29.jsonl", "--root", rp, "--binary", sys.argv[2], "--workers", "1", "--disk-min", "none"]) == 0
fs_tmp = [i for i, x in enumerate(ev) if x == ("fsync", f"{rp}/bin/evo_boids.tmp")]
i_rep = ev.index(("replace", f"{rp}/bin/evo_boids")) if ("replace", f"{rp}/bin/evo_boids") in ev else -1
assert fs_tmp and i_rep > fs_tmp[0] and ("fsync", f"{rp}/bin") in ev[i_rep:] and ("fsync", rp) in ev[i_rep:], \
    ("the first pin of the binary is not durable", [x for x in ev if "/bin" in x[1] or x[1] == rp][:12])
PY
# review round 5, P2-2: a public --replay must not choose an old pinned driver that cannot read the store.
# A path-only legacy cell (no registered snapshot hashes) is pruned (its snapshot archived), its snapshot is
# then moved away, and the pinned run.py is a pre-store driver (here a stub that would exit 99)
rm -rf root29v && cp -r root3dup root29v && cp A.json A_moved29.json
$PY - <<'PY' || fail "preparing the path-only legacy cell"
import json
for name in ("cell.json", "done.json"):
    p = f"root29v/cells/off_f100_A_B_r01/{name}"
    x = json.load(open(p))
    c = x["cell"] if name == "done.json" else x
    del c["resident_sha256"], c["invader_sha256"]
    c["resident"] = c["resident"].replace("/A.json", "/A_moved29.json")
    json.dump(x, open(p, "w"))
PY
$PY "$T/run.py" --root root29v --prune-finished > p29v.log 2>&1 || fail "--prune-finished (path-only cell): $(tail -3 p29v.log)"
[ ! -f root29v/cells/off_f100_A_B_r01/end.json ] || fail "the path-only legacy cell was not pruned: $(tail -3 p29v.log)"
rm -f A_moved29.json
printf 'import sys\n\ndef replay_cell():\n    pass\n\nsys.exit(99)\n' > root29v/tools/run.py
rm -rf rp29v && $PY "$T/run.py" --root root29v --replay off_f100_A_B_r01 --out rp29v > rp29v.log 2>&1
rc=$?
[ $rc = 0 ] && grep -q "replay off_f100_A_B_r01: identical" rp29v.log && grep -q '"resident": "store"' rp29v/replay.json \
    || fail "a replay needing the store was routed to the old pinned driver (exit $rc): $(tail -2 rp29v.log)"

# 30. review round 4, P3-7: the disk guard's clean stop works when the disk cannot be written: the
#     guard fires while a cell is running and STOP / progress.json fail with ENOSPC - admission stops in
#     memory, the running cell finishes, exit 75, no engine left; and whatever else breaks the runner's
#     loop, its running workers and engines are terminated
$PY - "$T" "$BIN" "$W" > t30a.log 2>&1 <<'PY' || fail "the disk guard's stop path with an unwritable disk: $(tail -3 t30a.log)"
import errno, json, os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import invlib, run
BIN, W = sys.argv[2], sys.argv[3]
engines = lambda r: len(subprocess.run(["pgrep", "-f", f"{W}/{r}/bin/evo_boids"], capture_output=True, text=True).stdout.split())
calls = [0]
def dp(guards):
    calls[0] += 1
    return None if calls[0] == 1 else "test: / has 0 MB free, below the disk guard's 1 MB"
wa0 = invlib.write_atomic
def wa(path, text):
    if calls[0] >= 2 and os.path.basename(path) in ("STOP", "progress.json"):
        raise OSError(errno.ENOSPC, "No space left on device (test)")
    return wa0(path, text)
run.disk_problem, invlib.write_atomic = dp, wa
try:
    rc = run.main(["--plan", "plan.jsonl", "--root", "root30", "--binary", BIN, "--workers", "2", "--disk-min", "/:1"])
except Exception as e:
    rc = f"raised {e!r}"
finally:
    invlib.write_atomic = wa0
left = engines("root30")
subprocess.run(["pkill", "-KILL", "-f", f"{W}/root30/bin/evo_boids"])   # (this test's own engines, if it fails)
done = [c for c in os.listdir("root30/cells") if os.path.exists(f"root30/cells/{c}/done.json")]
log = open("root30/runner.log").read()
assert rc == 75 and left == 0, (rc, left)
assert len(done) == 1 and not os.path.exists("root30/STOP") and "could NOT write" in log, (done, log[-600:])
assert "stopped by the disk guard" in log and calls[0] == 2, log[-400:]
PY
$PY - "$T" "$BIN" "$W" > t30b.log 2>&1 <<'PY' || fail "an unexpected error in the runner left its cells running: $(tail -3 t30b.log)"
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[1]); import run
BIN, W = sys.argv[2], sys.argv[3]
engines = lambda r: len(subprocess.run(["pgrep", "-f", f"{W}/{r}/bin/evo_boids"], capture_output=True, text=True).stdout.split())
calls = [0]
def dp(guards):
    calls[0] += 1
    if calls[0] >= 2:
        for _ in range(100):   # (wait until the admitted cell's engine runs)
            if engines("root30b"):
                break
            time.sleep(0.05)
        raise RuntimeError("test: the runner breaks")
run.disk_problem = dp
try:
    rc = run.main(["--plan", "plan.jsonl", "--root", "root30b", "--binary", BIN, "--workers", "2", "--disk-min", "/:1"])
except RuntimeError as e:
    rc = f"raised {e}"
left = engines("root30b")
subprocess.run(["pkill", "-KILL", "-f", f"{W}/root30b/bin/evo_boids"])
assert rc == "raised test: the runner breaks" and left == 0, (rc, left)
assert "runner error" in open("root30b/runner.log").read()
PY

# 31. review round 5, P2-3 / P2-4: a registered bank must be the APPROVED registration with its policies
#     (an otherwise valid bank with state 'carry', with zero predators under the label predA4, or from an
#     alternate plan consistent with its own export is refused); and a simulated alternative counts toward
#     power at its target only if its world was built as registered (every source fit converged, every
#     feasible plant solved with a converged noiseless refit) - a failed construction is a power failure,
#     kept in the denominator and counted
$PY - "$T" <<'PY' || fail "the frozen bank specification binds the approved plan and its policies"
import sys
sys.path.insert(0, sys.argv[1]); import calibrate
s = calibrate.BANK_SPEC
assert len(s["plan_sha256"]) == 64 and s["state"] == "slot" and s["predators"] == {"off": 0, "predA4": 4} and s["steps"] == 13500, s
PY
for nm in carry zero alt; do
    $PY - "$nm" <<'PY' || fail "building the $nm registration"
import sys
nm = sys.argv[1]
d = open("design26.json").read()
old, new = {"carry": ('"fractions": [0.05],', '"fractions": [0.05], "state": "carry",'),
            "zero": ('"predA4": 4}', '"predA4": 0}'),
            "alt": ('"log_every": 1000', '"log_every": 500')}[nm]
assert d.count(old) == 1, (nm, old)
open(f"design26_{nm}.json", "w").write(d.replace(old, new))
PY
    $PY "$T/plan.py" design26_$nm.json > plan26_$nm.jsonl || fail "plan.py (design26_$nm)"
    $PY - "$nm" <<'PY' || fail "binding the $nm bank to its own plan"
import hashlib, json, sys
nm = sys.argv[1]
sha = hashlib.sha256(open(f"plan26_{nm}.jsonl", "rb").read()).hexdigest()
b = json.load(open("bank26.json")); b["plan_sha256"] = sha; json.dump(b, open(f"bank26_{nm}.json", "w"))
s = json.load(open("spec26.json"))
if nm != "alt":
    s["plan_sha256"] = sha   # approved = this plan: only the policy check can refuse it
json.dump(s, open(f"spec26_{nm}.json", "w"))
PY
done
for v in carry:"arena state policy" zero:"predator counts" alt:"is not the approved registration"; do
    nm=${v%%:*} why=${v#*:}
    $PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal31_$nm --sims 0 --bank bank26_$nm.json \
        --bank-plan plan26_$nm.jsonl --bank-spec spec26_$nm.json --bank-sims 0 --compound 4:4:2 --compound-sims 2 \
        --compound-variants null --workers 1 > cal31_$nm.log 2>&1
    rc=$?
    [ $rc = 2 ] && grep -qF "$why" cal31_$nm.log || fail "the $nm bank was accepted as the registered one (exit $rc): $(tail -2 cal31_$nm.log)"
done
$PY - "$T" <<'PY' || fail "a failed plant construction or source fit counted toward power"
import json, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
pbs = {(p["group"], p["cond"]): p for p in json.load(open("bank26.json"))["primary_blocks"]}
calibrate.G.update({"bank_zq": [[pbs[(g, c)]["zq"] for c in ("off", "predA4")] for g in ("np", "p4")]})
lab = "bounded ladder + feasible plant d_res=0.05 in all conditions"
calibrate.compound_variants = lambda which: [("bounded ladder", None, 0.0, "all"), (lab, "target", 0.05, "all")]
A = calibrate.ALPHAS
fp0, pd0, sf0 = calibrate.feasible_plant, calibrate.plant_diagnostics, getattr(calibrate, "_source_fit", None)
def run(tag):
    calibrate.G["_plants"] = {}
    gk, cnt, n, *_ = calibrate.task_compound((None, 4, 6, 2, 4, "target", 31))
    return cnt, n
cnt, n = run("ok")                                   # the plant is detectable when it is built
assert cnt[("claim: H1 and H1b", lab, 0.05)] >= 3, cnt[("claim: H1 and H1b", lab, 0.05)]
fail_key = f"world not built as registered (source fit, law or plant failed; counted as a failure): {lab}"
cases = {
    "an unsolved plant (iteration limit)": lambda: setattr(calibrate, "feasible_plant", lambda *a, **k: fp0(*a, **dict(k, iters=1))),
    "an unconverged noiseless refit": lambda: setattr(calibrate, "plant_diagnostics", lambda *a: pd0(*a)[:2] + (False,) + pd0(*a)[3:]),
    "an unconverged source fit": lambda: setattr(calibrate, "_source_fit", lambda zq: dict(bounded.fit_matrix(zq), converged=False)),
}
for what, patch in cases.items():
    calibrate.feasible_plant, calibrate.plant_diagnostics = fp0, pd0
    if sf0 is not None:
        calibrate._source_fit = sf0
    patch()
    cnt, n = run(what)
    assert all(cnt[(t, lab, a)] == 0 for t in ("claim: H1 and H1b", "H1 raw sign-flip omnibus",
                                               "H1b logistic residual sign-flip omnibus") for a in A), (what, cnt[("claim: H1 and H1b", lab, 0.05)])
    assert cnt.get((fail_key, "null", 0.95)) == n == 4, (what, cnt.get((fail_key, "null", 0.95)))
    if what == "an unconverged source fit":   # the whole world is invalid, null included
        assert cnt[("world not built as registered (source fit, law or plant failed; counted as a failure): bounded ladder", "null", 0.95)] == n
PY

# 32. quick check of round 5 (P2): a failed directory fsync must not leave replay dependencies cached as
# durable. Two cells with the same dependencies: the first barrier's fsync of store/ fails (EIO), so that
# cell deletes nothing; the second cell's barrier must sync the blob, store/ and the root again before its
# deletions. Once durable, a third cell syncs nothing more
rm -rf root32 && mkdir -p root32/store root32/bin
$PY - "$T" <<'PY' > t32.log 2>&1 || fail "a failed directory fsync left the replay dependencies cached as durable: $(tail -3 t32.log)"
import errno, os, sys
sys.path.insert(0, sys.argv[1]); import run
root = os.path.abspath("root32"); h = "b" * 64; sd = f"{root}/store"
open(f"{sd}/{h}", "w").write("blob\n")
ev, boom, of = [], [True], os.fsync
def fs(fd):
    p = os.readlink(f"/proc/self/fd/{fd}")
    ev.append(p)
    if p == sd and boom[0]:
        boom[0] = False
        raise OSError(errno.EIO, "injected")
    return of(fd)
os.fsync = fs
run._SYNCED.clear()
try:
    run.durability_barrier(root, [h])
    raise SystemExit("the first barrier did not raise")
except OSError as e:
    assert e.errno == errno.EIO, e
assert (root, h) not in run._SYNCED, "a blob was cached as durable although store/ did not sync"
ev.clear()
run.durability_barrier(root, [h])
assert f"{sd}/{h}" in ev and sd in ev and root in ev, ev
assert (root, h) in run._SYNCED
ev.clear()
run.durability_barrier(root, [h])
assert ev == [], ev
PY

# 33. prereg gate, review round 5 items 5 / 6: the registered bounded marginal law. Exact feasible moments
#     (the old law capped mu 0.5 / SD 0.49 at SD 0.47434), the zero mass as registered, a point mass at
#     v = 0, Bernoulli at v = mu (1 - mu), FAILURE on an invalid specification (no cap), alternatives that keep
#     v / (mu (1 - mu)), and a quantile function that is the exact inverse (the joint worlds need it)
$PY - "$T" <<'PY' || fail "the registered bounded marginal law"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate, hodge
for mu, v in ((0.5, 0.49 ** 2), (0.3, 0.04), (0.01, 1e-6), (2e-5, 4e-10), (0.02, 9e-4), (0.7, 1e-4), (0.002, 0.0019)):
    m = calibrate.marginal(mu, v)
    mm, vv = calibrate.marginal_moments(m)
    assert m["valid"] and not m["capped"] and abs(mm - mu) <= 1e-13 * mu and abs(vv - v) <= 1e-9 * v, (mu, v, m)
m = calibrate.marginal(0.01, 1e-4)
assert abs(m["p0"] - min(0.05, 1e-4 / (2 * (1e-4 + 1e-4)))) < 1e-15 and calibrate.marginal(0.04, 1e-4)["p0"] == 0.0
assert calibrate.marginal(0.4, 0.0)["kind"] == "point"
b = calibrate.marginal(0.3, 0.21)
assert b["kind"] == "bernoulli" and calibrate.marginal_moments(b) == (0.3, 0.21), b
bad = calibrate.marginal(0.3, 0.2209)
assert not bad["valid"] and "infeasible" in bad["reason"] and calibrate.marginal(0.3, 0.2209, cap=True)["capped"]
assert not calibrate.marginal(0.0, 0.0)["valid"] and not calibrate.marginal(0.5, -1e-9)["valid"]
assert not hasattr(calibrate, "ZIB_VMAX")
alt = calibrate.marginal_alt(0.1, 0.0045, 0.2)
assert alt["valid"] and abs(alt["v"] - 0.0045 / 0.09 * 0.16) < 1e-15, alt
rnd = random.Random(33)
n = 100000
for law in (b, calibrate.marginal(0.5, 0.49 ** 2), calibrate.marginal(0.01, 1e-4)):
    xs = [calibrate.draw_marginal(rnd, law) for _ in range(n)]
    mu, v = calibrate.marginal_moments(law)
    m_ = sum(xs) / n
    v_ = sum((x - m_) ** 2 for x in xs) / (n - 1)
    assert abs(m_ - mu) < 5 * math.sqrt(v / n) and abs(v_ / v - 1) < 0.05, (law["kind"], m_, mu, v_, v)
for a, bb in ((0.05, 3.0), (2.0, 2.0), (900.0, 1100.0), (0.8, 0.02)):
    q = calibrate.BetaQuantile(a, bb)
    for u in (1e-14, 1e-6, 0.01, 0.37, 0.5, 0.93, 1 - 1e-9):
        x = q(u, 1 - u)
        xe = bounded.sigmoid(q.exact_t(math.log(u) - math.log1p(-u)))
        assert abs(x - xe) < 1e-9, (a, bb, u, x, xe)
        if 0.01 <= u <= 0.93 and bb > 0.1:   # (an independent CDF; Beta(0.8, 0.02) puts u = 0.37 at 1 - 1.4e-10,
            assert abs(hodge.betainc(a, bb, x) - u) < 1e-9, (a, bb, u, hodge.betainc(a, bb, x))   # finer than a double)
PY

# 34. review round 5 item 8: the six joint bounded worlds. Through the copula the uniforms stay exactly uniform
#     (so every marginal is the registered law), J0's assays are latently independent and J8's correlated
#     (Spearman 6/pi asin(0.4) = 0.786), within an assay the column factor loads (-1)^i, and the rare event is
#     shared across assays: in R05-D even invaders sit in their top 5% and odd ones in their bottom 5% together
#     in ~pi of the columns; R05-C touches only resident 0's invaders 1 (low) and 2 (high)
$PY - "$T" <<'PY' || fail "the joint stress worlds"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate
assert sorted(calibrate.JOINT_WORLDS) == ["J0", "J8", "R01-C", "R01-D", "R05-C", "R05-D"]
calibrate.quantile_marginal = lambda m, lo, hi: lo          # observe the uniforms themselves
laws = [[None] * 5 for _ in range(2)]
rnd = random.Random(34)
def rank_corr(x, y):
    n = len(x)
    rx = {v: i for i, v in enumerate(sorted(x))}
    ry = {v: i for i, v in enumerate(sorted(y))}
    a, b = [rx[v] for v in x], [ry[v] for v in y]
    ma, mb = sum(a) / n, sum(b) / n
    return sum((p - ma) * (q - mb) for p, q in zip(a, b)) / math.sqrt(sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b))
n = 20000
for name, w in calibrate.JOINT_WORLDS.items():
    for p in (0, 3):
        qs = [calibrate.joint_column(rnd, laws, p, w["kappa"], w["rare"]) for _ in range(n)]
        for c in range(2):
            for i in range(5):
                if i == p:
                    continue
                u = [q[c][i] for q in qs]
                m, v = sum(u) / n, sum((x - 0.5) ** 2 for x in u) / n
                assert abs(m - 0.5) < 5 * math.sqrt(1 / 12 / n) and abs(v * 12 - 1) < 0.04, (name, p, c, i, m, v)
        i1 = 1 if p != 1 else 2
        cross = rank_corr([q[0][i1] for q in qs], [q[1][i1] for q in qs])
        within = rank_corr([q[0][i1] for q in qs], [q[0][i1 + 1 if i1 + 1 != p else i1 + 2] for q in qs])
        want = 6 / math.pi * math.asin(w["kappa"] / 2)
        if w["rare"] is None:
            assert abs(cross - want) < 0.03 and within < -0.7, (name, cross, want, within)
        if w["rare"] is not None:
            pi_ = w["rare"]["pi"]
            if w["rare"]["where"] == "distributed" or p == 0:
                sel = [i for i in range(5) if calibrate.rare_selected(w["rare"]["where"], p, i)]
                both = sum(all((q[c][i] >= 1 - pi_) if i % 2 == 0 else (q[c][i] <= pi_) for c in range(2) for i in sel)
                           for q in qs) / n
                assert abs(both - pi_) < 4 * math.sqrt(pi_ / n) + 0.004, (name, p, both, pi_)
            else:   # concentrated: other columns are plain J8 (no event at all)
                assert not any(calibrate.rare_selected("concentrated", p, i) for i in range(5))
assert calibrate.rare_selected("concentrated", 0, 1) and calibrate.rare_selected("concentrated", 0, 2) \
    and not calibrate.rare_selected("concentrated", 0, 3) and not calibrate.rare_selected("concentrated", 1, 2)
PY

# 35. review round 5 item 7: the registered plant. Probability scale, clipped to [0.002, 0.998], amplitude c at
#     the FIRST grid crossing of d_res >= target on 0, 0.001, ..., 1 then bisection to 1e-4 relative; the null
#     untouched; an unreachable target is not solved (never silently weakened)
$PY - "$T" <<'PY' || fail "the registered plant construction"
import random, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate, infer
rnd = random.Random(35)
N = 12
par = {"mu": -2.3, "a": [rnd.gauss(0, 0.8) for _ in range(N)], "b": [rnd.gauss(0, 0.6) for _ in range(N)]}
eta, mean0, th0 = calibrate._ladder(par, list(range(N)), N)
keep = [row[:] for row in mean0]
v = infer.cycle_template(N, "diffuse", seed=5)
for target in (0.01, 0.02):
    x = calibrate.feasible_plant(eta, mean0, th0, v, target)
    assert x["solved"] and x["converged"] and abs(x["d_res"] - target) <= calibrate.PLANT_TOL * target, x["d_res"]
    m = x["grid_m"]
    assert m and (m - 1) / calibrate.PLANT_GRID < x["c"] <= m / calibrate.PLANT_GRID, (m, x["c"])
    if m > 1:   # the crossing is the first one on the grid
        lo = calibrate.nominal_plant(mean0, v, (m - 1) / calibrate.PLANT_GRID)[0]
        assert calibrate.plant_diagnostics(lo, mean0, th0)[1] < target
    want, ncl, _, _ = calibrate.nominal_plant(mean0, v, x["c"])
    assert x["mean"] == want and x["clipped"] == ncl, "the alternative is the clipped probability-scale plant at c"
assert mean0 == keep
calibrate.PLANT_GRID = 20   # (a coarse grid only to keep this check short: no crossing anywhere on [0, 1])
far = calibrate.feasible_plant(eta, mean0, th0, v, 5.0)
assert not far["solved"] and far["grid_m"] is None and far["evals"] == 21, (far["d_res"], far["evals"])
PY

# 36. review round 5 items 4 / 10: one invalid-dataset path. A saturated plateau (every logit 30, targets 0.5:
#     tiny gradient, SSE 33) is no longer 'converged'; every fit reports its termination reason, gradient and
#     stationarity; a failed projection or a non-finite result makes H1b UNAVAILABLE instead of aborting (the
#     analysis and a calibration dataset alike); the gate screen counts an unavailable null decision as a
#     REJECTION and an unavailable alternative as a FAILURE, beside the raw procedure rate
$PY - "$T" <<'PY' || fail "one invalid-dataset path"
import json, math, random, sys
sys.path.insert(0, sys.argv[1]); import analyze, bounded, calibrate
model, cells = bounded.Model("logistic", 12), bounded._cells(12)
r = bounded.lm(model, cells, [0.5] * len(cells), [30.0] + [0.0] * 22)
assert r[2] is False and r[1] > 30 and r.grad < 1e-9 and r.stationarity > 0.5, (r[2], r[1], r.grad, r.stationarity)
assert "stat_tol" in bounded.FIT_FREEZE and bounded.FIT_FREEZE["iters"] == 200 and bounded.FIT_FREEZE["tol"] == 1e-11
pbs = {(p["group"], p["cond"]): p for p in json.load(open("bank26.json"))["primary_blocks"]}
groups = [[pbs[(g, c)]["zq"] for c in ("off", "predA4")] for g in ("np", "p4")]
f = bounded.fit_matrix(groups[0][0])
assert f["converged"] and f["reason"] in ("tol", "exact", "step", "damping", "cap") and f["grad"] is not None and f["stationarity"] is not None
ok = calibrate.decide(groups)
assert ok["valid"] and ok["conj"] is not None, ok
inv0 = bounded._inverse
bounded._inverse = lambda M: (_ for _ in ()).throw(ValueError("singular"))
ro = bounded.residual_omnibus(groups)
dec = calibrate.decide(groups)
bounded._inverse = inv0
assert not ro["valid"] and ro["p_flip"] is None and "projection failed" in ro["invalid"], ro["invalid"]
assert dec["conj"] is None and dec["p1b"] is None and not dec["valid"] and dec["p1"] is not None, dec
nan = json.loads(json.dumps(groups))
nan[1][1][2][3][0] = float("nan")
dn = calibrate.decide(nan)
assert dn["conj"] is None and not dn["valid"], dn
assert calibrate.screen_p(None, null=True) == 0.0 and calibrate.screen_p(None, null=False) is None and calibrate.screen_p(0.3, True) == 0.3
# the analysis: a failed projection is descriptive, not an abort
rnd = random.Random(36)
cores = {"x": ["x1", "x2", "x3", "x4"], "y": ["y1", "y2", "y3", "y4"]}
reg, rows = {}, []
for c in ("off", "predA"):
    for core in cores.values():
        for jj, j in enumerate(core):
            for ii, i in enumerate(core):
                mode = "sham" if i == j else "invade"
                reg.setdefault((c, 0.05), {})[(i, j, mode)] = set(range(6))
                for rr in range(6):
                    q = 0.05 if i == j else bounded.sigmoid(-2.0 + 0.6 * ii - 0.4 * jj)
                    rows.append({"cond": c, "frac": 0.05, "G": 13500.0, "mode": mode, "i": i, "j": j, "rep": rr,
                                 "s": q - 0.05 + rnd.gauss(0, 0.003), "f0": 0.05, "missed": False})
bounded._inverse = lambda M: (_ for _ in ()).throw(ValueError("singular"))
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 19)
bounded._inverse = inv0
assert pj[0]["status"] == "formal" and pj[0]["p_res_flip"] is None and pj[0]["claim_beyond_bounded"] is None, pj
assert "projection failed" in pj[0]["claim_status"] and all(r_.get("p_res_flip") is None for r_ in pr if "F_res" in r_), pj
# calibration: unconverged fits in every dataset -> raw rates count non-rejections, the gate screen rejections
calibrate.G.update({"bank_zq": groups})
lm0 = bounded.lm
sf0 = calibrate._source_fit
def sf(zq):
    bounded.lm = lm0
    try:
        return sf0(zq)
    finally:
        bounded.lm = lm1
lm1 = lambda model, cells, y, th0, iters=200, tol=1e-11: lm0(model, cells, y, th0, 1, tol)
calibrate._source_fit = sf
bounded.lm = lm1
gk, cnt, n, *_ = calibrate.task_compound((None, 4, 6, 2, 3, "null", 36))
bounded.lm, calibrate._source_fit = lm0, sf0
a = calibrate.ALPHAS[-1]
assert cnt[("claim: H1 and H1b", "bounded ladder", a)] == 0 and cnt[("claim: H1 and H1b [gate screen]", "bounded ladder", a)] == n == 3, cnt
assert cnt[("H1b logistic residual sign-flip omnibus [gate screen]", "bounded ladder", a)] == n
PY

# 37. review round 5 item 11: the gate driver. 'freeze' writes the frozen manifest (master seed 20271103, the
#     ordered schedule and its seeds, every count: 104,000 + 116,000 datasets, the registered bank identity,
#     the tool hashes, the fitting freeze, the acceptance rule) and nothing else; 'run' writes it BEFORE any
#     computation, refuses a changed manifest and a bank that is not the registered one (formal), and writes a
#     machine-readable decision (exit 1 on fail, with reasons); results do not depend on the worker count or on
#     an interruption; an invalid law (v > mu (1 - mu)) fails validity
$PY "$T/gate.py" freeze --out gf37 > gf37.log 2>&1 || fail "gate.py freeze: $(tail -3 gf37.log)"
$PY - "$T" <<'PY' || fail "the frozen gate manifest"
import hashlib, json, os, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate, gate
assert sorted(os.listdir("gf37")) == ["manifest.json"]
m = json.load(open("gf37/manifest.json"))
p = m["protocol"]
assert m["formal"] is True and p["master_seed"] == 20271103 and p["counts"] == {"null": 10000, "alt": 2000, "diag": 2000,
       "outer": 100, "outer_inner": 1000, "chunk": 50}, p["counts"]
assert p["gate_datasets"] == 104000 and p["diagnostic_datasets"] == 116000 and p["geometry"] == {"N": 12, "k": 10, "G": 2, "C": 2}
assert abs(p["alpha"] - 0.05 / 12) < 1e-15 and abs(p["level_ceiling"] - 0.1 / 12) < 1e-15 and p["power_bound"] == 0.8
assert [c["criterion"] for c in p["acceptance"]] == ["level", "power", "validity"] and p["fitting"] == json.loads(json.dumps(bounded.FIT_FREEZE))
assert p["bank"]["plan_sha256"].startswith("1040e673") and p["bank"]["cells"] == 28800
assert sum(len(v) for v in p["bank"]["registry"].values()) == 24 and all(len(h) == 64 for v in p["bank"]["registry"].values() for h in v.values())
assert p["preregistration"]["sha256"].startswith("cf1518bc") and p["preregistration"]["approved_utc"] == "2026-11-04T06:44Z"
s = m["schedule"]
assert m["tasks"] == len(s) == 9 * 200 + 7 * 40 + 8 * 40 + 100 * 20 and [t[0] for t in s] == list(range(len(s)))
assert s[0][1:3] == ["L", "null"] and s[-1][1:3] == ["E", "outer99"] and sum(t[3] for t in s) == 104000 + 116000
assert all(t[4] == gate.task_seed(t[0], t[1], t[2]) for t in s) and len({t[4] for t in s}) == len(s)
assert m["schedule_sha256"] == hashlib.sha256(gate.canon(s).encode()).hexdigest()
for f in gate.TOOLS:
    assert m["tools"][f] == hashlib.sha256(open(os.path.join(sys.argv[1], f), "rb").read()).hexdigest(), f
PY
$PY - "$T" "$W" <<'PY' || fail "building the registered 12-item toy bank"
import hashlib, json, os, random, sys
sys.path.insert(0, sys.argv[1]); import bounded, calibrate, plan
W = sys.argv[2]
files = [f"{W}/{x}.json" for x in ("A", "B", "C", "As", "Bs", "Cs")]
cores = {"np": [f"n{t:02d}" for t in range(12)], "p4": [f"p{t:02d}" for t in range(12)]}
K = 12
design = {"name": "t37", "snapshots": {nm: files[t % 6] for names in cores.values() for t, nm in enumerate(names)},
          "conditions": {"off": 0, "predA4": 4}, "fractions": [0.05], "replicates": K, "steps": 13500,
          "checkpoint_every": 4500, "log_every": 1000, "cores": [[g, v] for g, v in cores.items()]}
cells = plan.expand(design)
text = "".join(json.dumps(c, sort_keys=True) + "\n" for c in cells)
open("plan37.jsonl", "w").write(text)
sha = hashlib.sha256(text.encode()).hexdigest()
reg = {}
for c in cells:
    reg.setdefault(c["core"], {})[c["resident_name"]] = c["resident_sha256"]
rnd = random.Random(37)
pbs = []
for g, names in cores.items():
    a = [rnd.gauss(0, 0.8) for _ in range(12)]
    b = [rnd.gauss(0, 0.6) for _ in range(12)]
    mus = {c: [[bounded.sigmoid(-2.3 + a[i] + b[p] + (0.2 if c == "predA4" else 0.0)) for i in range(12)] for p in range(12)]
           for c in ("off", "predA4")}
    laws = {c: [[(calibrate.marginal(mus[c][p][i], rnd.uniform(0.005, 0.04) * mus[c][p][i] * (1 - mus[c][p][i]))
                  if i != p else None) for i in range(12)] for p in range(12)] for c in ("off", "predA4")}
    zq = {c: [[None] * K for _ in range(12)] for c in laws}
    for p in range(12):
        for r in range(K):
            q = calibrate.joint_column(rnd, [laws["off"][p], laws["predA4"][p]], p, 0.4)
            zq["off"][p][r], zq["predA4"][p][r] = q
    for c in ("off", "predA4"):
        sham = [[0.05 + 0.005 * rnd.gauss(0, 1) for _ in range(K)] for _ in range(12)]
        z = [[[zq[c][p][r][i] - sham[p][r] if i != p else 0.0 for i in range(12)] for r in range(K)] for p in range(12)]
        pbs.append({"cond": c, "frac": 0.05, "G": 13500.0, "group": g, "names": sorted(names), "reps": list(range(K)),
                    "z": z, "zq": zq[c], "status": "formal"})
os.makedirs("bank37", exist_ok=True)
os.makedirs("bank37bad", exist_ok=True)
bb = {"schema": "finfolk.invasion.blocks/2", "plan_sha256": sha, "analysis_sha256": "a37", "clock": "steps",
      "blocks": [], "primary_blocks": pbs}
json.dump(bb, open("bank37/blocks.json", "w"))
inputs = {"plan": {"sha256": sha, "cells": len(cells)}, "clock": "steps", "complete": True, "registered_missing": [],
          "unregistered_finished": [], "identity_problems": [], "finished": len(cells), "cells_csv": {"cells": len(cells)},
          "snapshots": {nm: h for v in reg.values() for nm, h in v.items()}, "analysis_code": {"analyze.py": "a37"}}
json.dump(inputs, open("bank37/inputs.json", "w"))
json.dump(inputs, open("bank37bad/inputs.json", "w"))
json.dump({"plan_sha256": sha, "registry": reg, "K": K, "cells": len(cells)}, open("spec37.json", "w"))
json.dump({"null": 4, "alt": 4, "diag": 2, "outer": 2, "outer_inner": 2, "chunk": 2}, open("counts37.json", "w"))
json.dump({"null": 2, "alt": 2, "diag": 2, "outer": 1, "outer_inner": 2, "chunk": 2}, open("counts37b.json", "w"))
for r in range(K):   # one cell whose variance exceeds mu (1 - mu): the registered law cannot exist
    pbs[0]["zq"][1][r][0] = float(r % 2)
json.dump(bb, open("bank37bad/blocks.json", "w"))
PY
g37() {   # out bank counts extra...: a gate run on the toy bank (exploratory: its own spec and counts)
    local out=$1 bank=$2 counts=$3; shift 3
    $PY "$T/gate.py" run --out "$out" --bank "$bank" --bank-plan plan37.jsonl --bank-spec spec37.json --counts "$counts" "$@" \
        > "$out.log" 2>&1
}
g37 g37 bank37/blocks.json counts37.json --workers 1; rc=$?
[ $rc = 1 ] || fail "gate.py run on tiny counts must FAIL (exit 1), got $rc: $(tail -4 g37.log)"
$PY - "$T" <<'PY' || fail "the gate decision record"
import json, os, sys
sys.path.insert(0, sys.argv[1]); import gate
d = json.load(open("g37/decision.json"))
assert d["schema"] == "finfolk.invasion.gate-decision/1" and d["decision"] == "fail" and d["formal"] is False and d["reasons"], d["decision"]
lv = [c for c in d["criteria"] if c["criterion"] == "level"]
pw = [c for c in d["criteria"] if c["criterion"] == "power"]
va = [c for c in d["criteria"] if c["criterion"] == "validity"]
assert sorted((c["world"], c["test"]) for c in lv) == sorted((w, t) for w in gate.NULL_WORLDS for t in gate.LEVEL_TESTS[w])
assert sorted(c["world"] for c in pw) == sorted(gate.BOUNDED_WORLDS) and all(c["n"] == 4 for c in pw + lv)
assert len(va) == 1 and va[0]["ok"] is True, va      # the toy world is built as registered: tiny counts fail on level / power
assert all(x["solved"] and abs(x["d_res"] - 0.01) <= 1e-6 for x in d["target_plants"].values()), d["target_plants"]
assert all(f["converged"] for f in d["source_fits"].values())
man = os.path.getmtime("g37/manifest.json")
tasks = [os.path.getmtime(os.path.join("g37/tasks", f)) for f in os.listdir("g37/tasks")]
assert len(tasks) == json.load(open("g37/manifest.json"))["tasks"] and man <= min(tasks), "manifest after a task"
json.dump(d["criteria"], open("g37_criteria.json", "w"), sort_keys=True)
for f in sorted(os.listdir("g37/tasks"))[::2]:
    os.remove(os.path.join("g37/tasks", f))
PY
g37 g37 bank37/blocks.json counts37.json --workers 2; rc=$?
[ $rc = 1 ] || fail "gate.py run (resumed, 2 workers): exit $rc: $(tail -3 g37.log)"
grep -q "already done" g37.log || fail "the interrupted gate run did not resume"
$PY - <<'PY' || fail "the gate's result depends on the worker count / an interruption"
import json
assert json.load(open("g37/decision.json"))["criteria"] == json.load(open("g37_criteria.json"))
PY
g37 g37 bank37/blocks.json counts37b.json --workers 1; rc=$?
[ $rc = 2 ] && grep -q "differs from the regenerated manifest" g37.log || fail "a changed gate manifest was not refused (exit $rc)"
$PY "$T/gate.py" run --out g37f --bank bank37/blocks.json --bank-plan plan37.jsonl --workers 1 > g37f.log 2>&1; rc=$?
[ $rc = 2 ] && grep -q "not the registered bank" g37f.log && [ -z "$(ls g37f/tasks)" ] \
    && $PY -c "import json; d = json.load(open('g37f/decision.json')); assert d['decision'] == 'refused' and d['reasons']" \
    || fail "the formal gate ran on a bank that is not the registered one (exit $rc): $(tail -3 g37f.log)"
g37 g37b bank37bad/blocks.json counts37b.json --workers 1; rc=$?
[ $rc = 1 ] && $PY -c "
import json; d = json.load(open('g37b/decision.json')); v = [c for c in d['criteria'] if c['criterion'] == 'validity'][0]
assert not v['ok'] and any('infeasible' in p for p in v['problems']), v" || fail "an invalid law did not fail the gate's validity (exit $rc)"

# 38. review round 5 items 3 / 6: the bank's ORIGINAL identity. The frozen spec carries bank1's 24 item IDs with
#     their snapshot hashes and its 28,800 cells; a bank is refused if an item is renamed, a cell's snapshot hash
#     differs, a registered cell is missing from the analysis, a snapshot read is another file, or the analysis
#     inputs are absent
$PY - "$T" <<'PY' || fail "the bank's original identity"
import json, sys
sys.path.insert(0, sys.argv[1]); import calibrate
s = calibrate.BANK_SPEC
assert s["cells"] == 28800 and sorted(s["registry"]) == ["np", "p4"] and all(len(v) == 12 for v in s["registry"].values())
assert s["registry"]["np"]["n201l"].startswith("6ceb84c7") and s["registry"]["p4"]["p212m"].startswith("138b8948")
spec = dict(s, **json.load(open("spec37.json")))
bb = json.load(open("bank37/blocks.json"))
cells = [json.loads(l) for l in open("plan37.jsonl")]
inputs = json.load(open("bank37/inputs.json"))
sha = spec["plan_sha256"]
def probs(bb_=bb, cells_=cells, inputs_=inputs):
    return calibrate.validate_bank(bb_, spec, cells_, sha, inputs_)[3]
assert probs() == [], probs()
def jd(x):
    return json.loads(json.dumps(x))
b2 = jd(bb); b2["primary_blocks"][0]["names"][3] = "zz"; b2["primary_blocks"][1]["names"][3] = "zz"
assert any("registered item IDs" in p for p in probs(bb_=b2)), probs(bb_=b2)
c2 = jd(cells); c2[7]["resident_sha256"] = "0" * 64
assert any("snapshot hash is not the registered one" in p for p in probs(cells_=c2)), probs(cells_=c2)
i2 = jd(inputs); i2["registered_missing"] = ["off_f050_n00_n01_r00"]; i2["complete"] = False; i2["finished"] -= 1
assert any("registered_missing" in p for p in probs(inputs_=i2)) and any("not complete" in p for p in probs(inputs_=i2))
i3 = jd(inputs); i3["snapshots"]["p05"] = "f" * 64
assert any("snapshots read differ" in p for p in probs(inputs_=i3)), probs(inputs_=i3)
assert any("no analysis inputs.json" in p for p in probs(inputs_=None))
c4 = cells[:-1]
assert any("the registered bank" in p for p in probs(cells_=c4)), probs(cells_=c4)
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal38 --sims 0 --bank bank37/blocks.json \
    --bank-plan plan37.jsonl --bank-spec spec37.json --bank-inputs bank37bad/inputs.json --bank-sims 0 --compound 12:4:2 \
    --compound-sims 2 --compound-variants null --workers 1 > cal38.log 2>&1 || fail "calibrate.py refused the registered toy bank: $(tail -3 cal38.log)"
$PY - <<'PY' || fail "a missing registered cell in the bank analysis"
import json
i = json.load(open("bank37bad/inputs.json")); i["registered_missing"] = ["x"]; json.dump(i, open("inputs38.json", "w"))
PY
$PY "$T/calibrate.py" --blocks an3/blocks.json --key off/0.1/0.25 --out cal38m --sims 0 --bank bank37/blocks.json \
    --bank-plan plan37.jsonl --bank-spec spec37.json --bank-inputs inputs38.json --bank-sims 0 --compound 12:4:2 \
    --compound-sims 2 --compound-variants null --workers 1 > cal38m.log 2>&1
[ $? = 2 ] && grep -q "registered_missing" cal38m.log || fail "a bank with a missing registered cell was calibrated"

# 39. review round 5 items 1 / 2 / 12: the headline claim needs the strict confirmation registration, a
#     verified PASSED formal gate record and reads T only (2T is descriptive); a 0-8 / 0-9 registration is no
#     nine-replicate formal block under the protocol; no 'Holm family' / 'bounded logistic transitivity'
#     prose; the confirmation seed manifest (indexed confirm-v1 allocation, 5,760 trajectories) and its
#     disjointness check
! grep -n "Holm family\|bounded logistic transitivity\|Holm's first step" "$T"/*.py || fail "superseded claim prose in the tools"
$PY - "$T" <<'PY' || fail "the headline claim is tied to the gate, T and the strict registration"
import hashlib, json, os, random, sys
sys.path.insert(0, sys.argv[1]); import analyze, bounded, gate
rnd = random.Random(39)
cores = {"x": [f"x{t:02d}" for t in range(12)], "y": [f"y{t:02d}" for t in range(12)]}
cyc = {(0, 1): 0.06, (1, 2): 0.06, (2, 0): 0.06}
reg, rows = {}, []
for G in (13500.0, 27000.0):
    for c in ("off", "predA4"):
        for core in cores.values():
            for jj, j in enumerate(core):
                for ii, i in enumerate(core):
                    mode = "sham" if i == j else "invade"
                    reg.setdefault((c, 0.05), {})[(i, j, mode)] = set(range(10))
                    for r in range(10):
                        q = 0.05 if i == j else bounded.sigmoid(-2.0 + 0.15 * ii - 0.1 * jj) + cyc.get((ii, jj), 0.0) - cyc.get((jj, ii), 0.0)
                        rows.append({"cond": c, "frac": 0.05, "G": G, "mode": mode, "i": i, "j": j, "rep": r,
                                     "s": q - 0.05 + rnd.gauss(0, 0.003), "f0": 0.05, "missed": False})
strict = {"groups": 2, "N": 12, "k": 10, "assays": ["off", "predA4"], "fraction": 0.05}
def pj_(reg_, confirm):
    return analyze.primary_blocks(rows, None, reg_, cores, 19, windows_registered={13500.0, 27000.0}, confirm=confirm)
_, _, pj = pj_(reg, None)
assert all(j["status"] == "formal" and j["both_rejected"] is True and j["claim_beyond_bounded"] is None for j in pj), pj
ok = {"T": 13500.0, "strict": strict, "gate": {}, "gate_problems": []}
_, _, pj = pj_(reg, ok)
by = {j["G"]: j for j in pj}
assert by[13500.0]["claim_beyond_bounded"] is True and by[13500.0]["claim_status"].startswith("formal"), by[13500.0]
assert by[27000.0]["claim_beyond_bounded"] is None and "not the confirmatory horizon" in by[27000.0]["claim_status"], by[27000.0]
_, _, pj = pj_(reg, dict(ok, gate_problems=["the gate decision is 'fail', not 'pass'"]))
assert all(j["claim_beyond_bounded"] is None and j["both_rejected"] is True for j in pj), pj
assert "no passed gate" in {j["G"]: j for j in pj}[13500.0]["claim_status"], pj
reg9 = {k: dict(v) for k, v in reg.items()}
reg9[("off", 0.05)][("x03", "x05", "invade")] = set(range(9))     # one cell registers 0..8
_, pb, pj = pj_(reg9, None)
assert pb[("off", 0.05, 13500.0, "x")]["status"] == "formal" and pb[("off", 0.05, 13500.0, "x")]["reps"] == list(range(9))
_, pb, pj = pj_(reg9, ok)
assert pb[("off", 0.05, 13500.0, "x")]["status"].startswith("descriptive: confirmation protocol") and "no intersection" in \
    pb[("off", 0.05, 13500.0, "x")]["status"], pb[("off", 0.05, 13500.0, "x")]["status"]
assert all(j["status"].startswith("descriptive") and j.get("claim_beyond_bounded") is None for j in pj), pj
small = {k: {kk: vv for kk, vv in v.items() if kk[0] not in ("x11", "y11") and kk[1] not in ("x11", "y11")} for k, v in reg.items()}
c11 = {g: v[:11] for g, v in cores.items()}
_, pb, pj = analyze.primary_blocks(rows, None, small, c11, 19, windows_registered={13500.0}, confirm=ok)
assert all(b["status"].startswith("descriptive: confirmation protocol") for b in pb.values()), [b["status"] for b in pb.values()]
# the gate record (review of #49, finding 2): a fresh manifest plus a four-field 'pass' with no calibration run
# behind it is NOT a passed gate (step 41 checks the complete chain)
os.makedirs("gate39", exist_ok=True)
text = gate.canon(gate.manifest())
open("gate39/manifest.json", "w").write(text)
dec = {"schema": "finfolk.invasion.gate-decision/1", "decision": "pass", "formal": True,
       "manifest_sha256": hashlib.sha256(text.encode()).hexdigest()}
json.dump(dec, open("gate39/decision.json", "w"))
s, p = analyze.verify_gate("gate39")
assert p and any("run.json" in x for x in p), p
PY
$PY "$T/analyze.py" --root root3 --out an39 --plan plan3.jsonl --clock steps --horizon hz3.json --sims 50 --scales "" \
    --bounded "" --gate gate39 > an39.log 2>&1 || fail "analyze.py --gate: $(tail -4 an39.log)"
$PY -c "import json; g = json.load(open('an39/inputs.json'))['gate']; assert g['problems'] and g['plan_problems'] and g['T'] == 13500.0, g" \
    || fail "analyze.py --gate did not record why the claim is withheld"
$PY "$T/gate.py" seeds --out seeds39.json --avoid plan3.jsonl --avoid plan20.jsonl --home-seeds-used 101,102,201,212 > seeds39.log 2>&1 \
    || fail "gate.py seeds: $(tail -2 seeds39.log)"
$PY - <<'PY' || fail "the confirmation seed manifest"
import json
s = json.load(open("seeds39.json"))
assert s["trajectories"] == 5760 and s["invasions"] == 5280 and s["shams"] == 480 and s["collisions"] == [] == s["home_collisions"]
assert s["protocol"]["home_seeds"] == {"off": list(range(430001, 430007)), "predA4": list(range(430007, 430013))}
c = {(x["h"], x["assay"], x["j"], x["i"], x["r"]): x for x in s["cells"]}
x = c[(1, "predA4", 11, 4, 9)]
u = 10 * (12 * 1 + 11) + 9
assert (x["slot_seed"], x["donor_seed"], x["pred_seed"], x["reseed"]) == (3000000000 + u, 3100000000 + 12 * u + 4, 3200000000 + u, 3300000000 + 2 * u + 1)
x = c[(0, "off", 3, 3, 0)]
assert x["mode"] == "sham" and x["donor_seed"] == 3100000000 + 12 * 30 + 3 and x["pred_seed"] is None and x["reseed"] == 3300000000 + 60
open("plan39x.jsonl", "w").write(json.dumps({"slot_seed": 3000000007, "donor_seed": None, "pred_seed": None, "reseed": 5}) + "\n")
PY
$PY "$T/gate.py" seeds --out seeds39x.json --avoid plan39x.jsonl > seeds39x.log 2>&1
[ $? = 2 ] && $PY -c "import json; assert json.load(open('seeds39x.json'))['collisions'] == [3000000007]" || fail "a seed collision was not refused"
$PY "$T/gate.py" seeds --out seeds39h.json --home-seeds-used 430003 > /dev/null 2>&1
[ $? = 2 ] || fail "a home-seed collision was not refused"

# 40. review of #49, finding 1: the confirmation protocol requires the specification's full group x assay product
#     (an off-only plan with two complete 12-item cores and replicates 0-9 used to give a formal headline at T),
#     and the plan itself must be the approved design as far as the repository can tell: the confirm-v1 indexed
#     seeds, both assays, 0.05 / slot, a 27,000-step trajectory saving T exactly, and registered snapshots at
#     500,000 / 3,000,000 steps with predator-off homes first
$PY - "$T" <<'PY' || fail "the confirmation protocol's required design"
import random, sys
sys.path.insert(0, sys.argv[1]); import analyze, bounded
rnd = random.Random(40)
cores = {"x": [f"x{t:02d}" for t in range(12)], "y": [f"y{t:02d}" for t in range(12)]}
cyc = {(0, 1): 0.06, (1, 2): 0.06, (2, 0): 0.06}
reg, rows = {}, []
for core in cores.values():
    for jj, j in enumerate(core):
        for ii, i in enumerate(core):
            mode = "sham" if i == j else "invade"
            reg.setdefault(("off", 0.05), {})[(i, j, mode)] = set(range(10))
            for r in range(10):
                q = 0.05 if i == j else bounded.sigmoid(-2.0 + 0.15 * ii - 0.1 * jj) + cyc.get((ii, jj), 0.0) - cyc.get((jj, ii), 0.0)
                rows.append({"cond": "off", "frac": 0.05, "G": 13500.0, "mode": mode, "i": i, "j": j, "rep": r,
                             "s": q - 0.05 + rnd.gauss(0, 0.003), "f0": 0.05, "missed": False})
ok = {"T": 13500.0, "gate": {}, "gate_problems": [], "plan_problems": [],
      "strict": {"groups": 2, "N": 12, "k": 10, "assays": ["off", "predA4"], "fraction": 0.05}}
pr, pb, pj = analyze.primary_blocks(rows, None, reg, cores, 19, windows_registered={13500.0, 27000.0}, confirm=ok)
assert len(pj) == 1 and pj[0]["status"].startswith("descriptive: primary block(s)") and "predA4/x" in pj[0]["status"], pj
assert pj[0].get("claim_beyond_bounded") is None and pj[0]["required"] == "off/x off/y predA4/x predA4/y", pj
assert any(r_["cond"] == "predA4" and "not registered" in r_["status"] for r_ in pr), pr
_, _, pj = analyze.primary_blocks(rows, None, reg, cores, 19, windows_registered={13500.0, 27000.0})
assert pj[0]["status"] == "formal" and pj[0]["claim_beyond_bounded"] is None   # (generic mode: a formal off-only omnibus)
PY
$PY - "$T" "$W" <<'PY' || fail "the confirmation plan's binding to the approved design"
import json, os, sys
sys.path.insert(0, sys.argv[1]); import gate, plan
W = sys.argv[2]
os.makedirs("snap40", exist_ok=True)
def snaps(pred_np=0, pred_p4=4, odd_frame=None):
    out = {}
    for core, pred in (("np", pred_np), ("p4", pred_p4)):
        for t in range(12):
            nm = f"{core[0]}{t:02d}"
            fr = 500000 if t % 2 == 0 else 3000000
            if odd_frame and nm == odd_frame:
                fr = 1000000
            p_ = f"{W}/snap40/{nm}.json"
            json.dump({"world": {"frame": fr}, "config": {"predatorCount": pred}, "tag": [core, t]}, open(p_, "w"))
            out[nm] = p_
    return out
SCH = {"type": "indexed", "namespace": "confirm-v1", "slot_base": 3000000000, "donor_base": 3100000000,
       "pred_base": 3200000000, "reseed_base": 3300000000, "assays": ["off", "predA4"]}
def design(**kw):
    d = {"name": "c40", "snapshots": snaps(), "conditions": {"off": 0, "predA4": 4}, "fractions": [0.05], "replicates": 10,
         "steps": 27000, "checkpoint_every": 4500, "log_every": 1000, "seed_scheme": dict(SCH),
         "cores": [["np", [f"n{t:02d}" for t in range(12)]], ["p4", [f"p{t:02d}" for t in range(12)]]]}
    d.update(kw)
    return d
def probs(d, tamper=None):
    cells = plan.expand(d)
    if tamper:
        tamper(cells)
    return gate.confirmation_plan_problems(cells)
good = probs(design())
assert good == [], good
assert len(plan.expand(design())) == 5760
cases = {
    "steps": (design(steps=13500), "not 2T"),
    "checkpoints": (design(checkpoint_every=2000), "not 2T with T saved exactly"),
    "core order": (design(cores=[["p4", [f"p{t:02d}" for t in range(12)]], ["np", [f"n{t:02d}" for t in range(12)]]]),
                   "home predator counts"),
    "derived seeds": ({k: v for k, v in design().items() if k != "seed_scheme"}, "seed namespace"),
    "off only": (design(conditions={"off": 0}, seed_scheme=dict(SCH, assays=["off"])), "primary trajectories are registered"),
}
for nm, (d, why) in cases.items():
    p = probs(d)
    assert any(why in x for x in p), (nm, p)
d = design(); d["snapshots"] = snaps(odd_frame="n03")
assert any("snapshot steps" in x for x in probs(d)), probs(d)
d = design(); d["snapshots"] = snaps(pred_np=4)
assert any("home predator counts" in x for x in probs(d)), probs(d)
def bump(cells):
    cells[17]["donor_seed"] += 1
assert any("donor_seed not the confirm-v1 manifest's" in x for x in probs(design(), bump)), probs(design(), bump)
# review of #49, round 2 (Codex's alias case): every resident j = 0 and both cores h = 0 - u = r, slot 3e9 + r,
# donor 3.1e9 + 12 r, predator 3.2e9 + r, reseed 3.3e9 + 2 r + a - keeps every inferred index consistent; it must
# fail the bijections cores <-> h and members <-> j
def alias(cells):
    for c in cells:
        r = c["replicate"]
        a = 0 if c["condition"] == "off" else 1
        c.update(slot_seed=3000000000 + r, donor_seed=3100000000 + 12 * r, reseed=3300000000 + 2 * r + a,
                 pred_seed=3200000000 + r if a else None)
p = probs(design(), alias)
assert any("cores and h are not a bijection" in x for x in p) and any("not a bijection onto 0..11" in x for x in p), p
PY

# 41. review of #49, finding 2: a passed gate is a complete, consistent chain. gate.verify_record re-reads the
#     exploratory toy run of step 37 and finds nothing wrong but its 'fail' (tiny counts); then every broken link
#     is found: a forged 'pass' label (re-aggregation fails), a missing or altered task record, another run.json,
#     another calibrate.py in the manifest, an unbound cell-law artifact, and a lone decision with no run behind it
$PY - "$T" <<'PY' || fail "the gate record's chain verification"
import hashlib, json, os, shutil, sys
sys.path.insert(0, sys.argv[1]); import gate
RC = json.load(open("g37/receipt.json"))["receipt"]      # (the coordinator records it outside the directory)
s, p = gate.verify_record("g37", require_formal=False, receipt_sha=RC)
assert len(p) == 2 and "not 'pass'" in p[0] and "acceptance rule FAILS" in p[1] and s["receipt"] == RC, p
q = gate.verify_record("g37", require_formal=False)[1]
assert any("no external receipt" in x for x in q), q
assert any("not the one recorded outside" in x for x in gate.verify_record("g37", False, "0" * 64)[1])
def fresh():
    shutil.rmtree("g41", ignore_errors=True)
    shutil.copytree("g37", "g41")
def rewrite(name, f):
    d = json.load(open(f"g41/{name}")); f(d); open(f"g41/{name}", "w").write(gate.canon(d))
def task(i, f):
    t = json.load(open(f"g41/tasks/{i:05d}.json")); f(t); open(f"g41/tasks/{i:05d}.json", "w").write(json.dumps(t))
def check(why, rc=RC):
    q = gate.verify_record("g41", require_formal=False, receipt_sha=rc)[1]
    assert any(why in x for x in q), (why, q)
fresh(); rewrite("decision.json", lambda d: d.update(decision="pass", reasons=[]))
check("acceptance rule FAILS"); check("differs from the one the evidence regenerates"); check("not the one recorded outside")
fresh(); os.remove("g41/tasks/00003.json")
check("task record(s) missing or invalid")
fresh()
def flip(t):   # (a valid record with another count)
    new = 0 if t["rej"]["claim"] else 1
    t["rej"]["claim"] = new; t["rej"]["H1"] = max(t["rej"]["H1"], new); t["rej"]["H1b"] = max(t["rej"]["H1b"], new)
    for k_ in ("H1", "H1b", "claim"):
        t["rej05"][k_] = max(t["rej05"][k_], t["rej"][k_])
task(0, flip)
check("differs from the one the evidence regenerates")
fresh(); task(5, lambda t: t.update(run_sha256="0" * 64)); check("another run")
def impossible(t):   # 1 conjunction rejection with no H1 / H1b rejection
    t["rej"].update(claim=1, H1=0, H1b=0); t["rej05"].update(claim=max(t["rej05"]["claim"], 1))
fresh(); task(0, impossible); check("more conjunction rejections")
fresh(); task(0, lambda t: t.update(built=False)); check("not built as registered")
fresh(); task(19, lambda t: t["plants"]["0/0"].update(d_res=0.5)); check("plants are not the reference")
fresh(); task(0, lambda t: t["fit_info"]["0/0"].update(sse=1.0)); check("source-fit reports are not the reference")
outer = [t for t in json.load(open("g37/manifest.json"))["schedule"] if t[2] == "outer0"][0][0]
def at05(t):   # another rej05 count for H1, still a valid record: no criterion changes, the diagnostics do
    r5, r = t["rej05"]["H1"], t["rej"]["H1"]
    t["rej05"]["H1"] = r5 + 1 if r5 + 1 <= t["n"] else max(r, r5 - 1)
fresh(); task(outer, at05)
q = gate.verify_record("g41", require_formal=False, receipt_sha=RC)[1]
assert any("differs from the one the evidence regenerates" in x and "diagnostics" in x for x in q), q
fresh(); rewrite("run.json", lambda d: d.update(platform="elsewhere"))
check("run.json is not the one the decision bound")
fresh(); rewrite("run.json", lambda d: d["bank"]["blocks"].update(sha256="0" * 64))
check("the blocks file it binds is missing or changed")
fresh(); rewrite("run.json", lambda d: d["bank"].update(inputs=None))
check("no inputs binding")
fresh()
m = json.load(open("g41/manifest.json")); m["tools"]["calibrate.py"] = "0" * 64; txt = gate.canon(m)
open("g41/manifest.json", "w").write(txt)
rewrite("decision.json", lambda d: d.update(manifest_sha256=hashlib.sha256(txt.encode()).hexdigest()))
check("other tool sources: ['calibrate.py']")
fresh(); rewrite("cell_laws.json", lambda d: d.update(run_sha256="0" * 64))
check("cell_laws.json is not bound")
fresh()
def law(d):
    d["rows"][5]["mean_achieved"] *= 1.01
rewrite("cell_laws.json", law)
cl_sha = hashlib.sha256(open("g41/cell_laws.json").read().encode()).hexdigest()
rewrite("decision.json", lambda d: d.update(cell_laws_sha256=cl_sha))
check("not the construction the bank export replays to"); check("incomplete or inexact laws")
fresh(); open("g41/gate.md", "a").write("edited\n"); check("gate.md is not the report")
shutil.rmtree("g41b", ignore_errors=True); os.makedirs("g41b")
shutil.copy("g37/decision.json", "g41b/decision.json"); shutil.copy("g37/manifest.json", "g41b/manifest.json")
q = gate.verify_record("g41b", require_formal=False, receipt_sha=RC)[1]
assert any("run.json: missing" in x for x in q), q
assert any("exploratory" in x for x in gate.verify_record("g37", receipt_sha=RC)[1])
PY

# 44. review of #49, finding 5: the prescribed diagnostics are part of validity - completed, constructed, every
#     dataset available - while their rejection rates carry no threshold
$PY - "$T" <<'PY' || fail "diagnostic construction and completion in the gate's validity"
import copy, json, os, sys
sys.path.insert(0, sys.argv[1]); import gate
man = json.load(open("g37/manifest.json"))
sched = man["schedule"]
res = {t[0]: json.load(open(f"g37/tasks/{t[0]:05d}.json")) for t in sched}
agg = gate.aggregate(res, sched)
crit, _ = gate.decide_gate(copy.deepcopy(agg), None, False, [])
assert [c for c in crit if c["criterion"] == "validity"][0]["ok"], crit[-1]
def validity(a):
    return [c for c in gate.decide_gate(a, None, False, [])[0] if c["criterion"] == "validity"][0]
a = copy.deepcopy(agg); a[("L", "place-g1c0")]["plants"]["1/0"]["solved"] = False
v = validity(a); assert not v["ok"] and any("placement plant 1/0" in x for x in v["problems"]), v
a = copy.deepcopy(agg); a[("L", "tri-g0c1")]["plants"]["0/1"]["converged"] = False
v = validity(a); assert not v["ok"] and any("triangle 0/1" in x for x in v["problems"]), v
outer = [t for t in sched if t[2] == "outer1"][0][0]
r2 = {k: v for k, v in res.items() if k != outer}
v = validity(gate.aggregate(r2, sched)); assert not v["ok"] and any("E outer1" in x for x in v["problems"]), v
a = copy.deepcopy(agg); a[("L", "place-g0c0")]["unavailable"]["H1b"] = 1
v = validity(a); assert not v["ok"] and any("unavailable" in x for x in v["problems"]), v
a = copy.deepcopy(agg); a[("L", "place-g0c0")]["rej"]["claim"] = 0     # a diagnostic RATE never fails the gate
assert validity(a)["ok"]
PY

# 45. review of #49, finding 6: every task record is bound to its run's inputs and validated before aggregation:
#     records copied into a run over other inputs are recomputed, never reused; malformed counters are refused
$PY - "$T" <<'PY' || fail "task records bound to their run"
import json, sys
sys.path.insert(0, sys.argv[1]); import gate
man = json.load(open("g37/manifest.json"))
run_sha = json.load(open("g37/decision.json"))["run_sha256"]
t = man["schedule"][0]
r = json.load(open("g37/tasks/00000.json"))
ms = json.load(open("g37/decision.json"))["manifest_sha256"]
assert gate.task_problems(r, t, ms, run_sha) == [] and r["run_sha256"] == run_sha
assert "another run (bank inputs)" in gate.task_problems(r, t, ms, "0" * 64)
for bad in ({"rej": {"H1": -1, "H1b": 0, "claim": 0}}, {"unavailable": {"H1": 99, "H1b": 0, "claim": 0}}, {"why": []}):
    assert gate.task_problems(dict(r, **bad), t, ms, run_sha), bad
te = [x for x in man["schedule"] if x[1] == "E"][0]
re_ = json.load(open(f"g37/tasks/{te[0]:05d}.json"))
assert gate.task_problems(dict(re_, rej=dict(re_["rej"], H1b=1), rej05=dict(re_["rej05"], H1b=1)), te, ms, run_sha)
i = json.load(open("bank37/inputs.json")); i["note"] = "another export of the same bank"
json.dump(i, open("bank37/inputs_alt.json", "w"))
PY
rm -rf g45 && mkdir -p g45 && cp -r g37/tasks g37/manifest.json g45/
timeout 120 $PY "$T/gate.py" run --out g45 --bank bank37/blocks.json --bank-plan plan37.jsonl --bank-spec spec37.json \
    --counts counts37.json --bank-inputs bank37/inputs_alt.json --workers 1 > g45.log 2>&1
grep -q "0 already done, 42 stale record(s) recomputed" g45.log || fail "task records of another run were reused: $(head -3 g45.log)"

# 46. review of #49, finding 7: the new home + assay seeds against the archived home + assay seeds (an archived
#     home seed equal to a new slot seed is a collision)
$PY "$T/gate.py" seeds --out seeds46.json --home-seeds-used 3000000007 > seeds46.log 2>&1
[ $? = 2 ] && $PY -c "import json; assert 3000000007 in json.load(open('seeds46.json'))['collisions']" \
    || fail "an archived home seed equal to a new assay seed was not a collision"

# 47. review of #49, finding 8: the bank-bound cell-law artifact (requested vs achieved moments of every null and
#     planted cell) and no stale 'logit-scale' plant text
$PY - "$T" <<'PY' || fail "the cell-law artifact"
import hashlib, json, math, sys
sys.path.insert(0, sys.argv[1]); import calibrate
text = open("g37/cell_laws.json").read()
cl = json.loads(text)
d = json.load(open("g37/decision.json"))
assert d["cell_laws_sha256"] == hashlib.sha256(text.encode()).hexdigest() and cl["run_sha256"] == d["run_sha256"]
rows = cl["rows"]
by = {}
for r in rows:
    by.setdefault(r["variant"], []).append(r)
assert len(by["null"]) == 4 * 132 and len(by["target"]) == 4 * 132 and all(len(by[f"place-g{g}c{c}"]) == 132 for g in (0, 1) for c in (0, 1))
bb = json.load(open("bank37/blocks.json"))
zq = {(b["group"], b["cond"]): b["zq"] for b in bb["primary_blocks"]}[("np", "off")]
x = [zq[4][r][7] for r in range(12)]
m = sum(x) / 12
v = sum((y - m) ** 2 for y in x) / 11
r0 = [r for r in by["null"] if (r["group"], r["cond"], r["resident"], r["invader"]) == (0, 0, 4, 7)][0]
assert abs(r0["v_requested"] - v) <= 1e-12 * v and abs(r0["var_achieved"] - v) <= 1e-12 * v and abs(r0["mean_achieved"] - r0["mu"]) <= 1e-15
for r in by["target"]:
    want = r["v_bank"] / (r["mu_null"] * (1 - r["mu_null"])) * r["mu"] * (1 - r["mu"])
    assert r["valid"] and abs(r["v_requested"] - want) <= 1e-12 * want and abs(r["sd_achieved"] - math.sqrt(want)) <= 1e-9 * math.sqrt(want)
src = open(sys.argv[1] + "/calibrate.py").read()
assert "logit-scale cycle" not in src
PY

# 48. review of #49, ruling 3: the rare-event reflection behind ONE switch (the user chooses the reading), both
#     readings tested: U = 0.25, pi = 0.05 on a reflected coordinate gives 0.2875 (conjugation 1 - T(1 - U)) or
#     0.7625 (literal 1 - T(U)) without the event; each keeps the uniform marginal; the literal reading flips the
#     column factor's sign on the reflected (odd) invaders; the manifest records the choice
$PY - "$T" <<'PY' || fail "the rare-event reflection switch"
import json, math, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate, gate
rt = calibrate.rare_transform
assert calibrate.RARE_REFLECTION == "conjugate"
for rule, want0, want1 in (("conjugate", 0.2875, 0.0125), ("literal", 0.7625, 0.0375)):
    lo, hi = rt(0.25, 0.75, False, 0.05, True, rule)
    assert abs(lo - want0) < 1e-15 and abs(lo + hi - 1) < 1e-15, (rule, lo)
    lo, hi = rt(0.25, 0.75, True, 0.05, True, rule)
    assert abs(lo - want1) < 1e-15, (rule, lo)
    lo, hi = rt(0.25, 0.75, False, 0.05, False, rule)
    assert abs(lo - 0.2375) < 1e-15 and abs(hi - 0.7625) < 1e-15, (lo, hi)
p = gate.protocol()["worlds"]
assert p["R05-D"]["reflection"] == "conjugate" and p["J8"]["reflection"] is None
calibrate.quantile_marginal = lambda m, lo, hi: lo
laws = [[None] * 4 for _ in range(2)]
w = calibrate.JOINT_WORLDS["R05-D"]
def corr(x, y):
    n = len(x); mx, my = sum(x) / n, sum(y) / n
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
signs = {}
for rule in ("conjugate", "literal"):
    calibrate.RARE_REFLECTION = rule
    rnd = random.Random(48)
    qs = [calibrate.joint_column(rnd, laws, 0, w["kappa"], w["rare"]) for _ in range(20000)]
    for i in (1, 2, 3):
        u = [q[0][i] for q in qs]
        assert abs(sum(u) / len(u) - 0.5) < 0.01 and abs(sum((x - 0.5) ** 2 for x in u) / len(u) * 12 - 1) < 0.04, (rule, i)
    signs[rule] = corr([q[0][1] for q in qs], [q[0][2] for q in qs])
assert signs["conjugate"] < -0.5 and signs["literal"] > 0.5, signs
PY

# 42. review of #49, finding 3: the fitting classifier on prespecified fixtures. A numerically vanished Jacobian
#     never certifies an appreciable residual (all logits 30 / 40 / 45 with targets 0.5: SSE 33; one item's effect
#     pushed to +47), derivatives are stable (sigma' without the 1 - sigma cancellation), and boundary infima
#     with negligible SSE are NOT spuriously unavailable (an all-zero target matrix, an all-zero invader row, an
#     all-zero resident column, an invader that always wins); an interior fit matches an independent reference
#     (2,000 iterations from the true parameters) and a low-variance ladder converges
$PY - "$T" <<'PY' || fail "the fitting classifier fixtures"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import bounded
assert bounded.dsigmoid(40.0) > 4e-18 and abs(bounded.dsigmoid(30.0) - math.exp(-30.0)) < 1e-25
N = 12
cells = bounded._cells(N)
model = bounded.Model("logistic", N)
rnd = random.Random(42)
a = [rnd.gauss(0, 0.8) for _ in range(N)]
b = [rnd.gauss(0, 0.6) for _ in range(N)]
def ladder():
    return [[bounded.sigmoid(-2.3 + a[i] + b[j]) if i != j else None for j in range(N)] for i in range(N)]
def lmfit(M, th0=None):
    y = [M[i][j] for i, j in cells]
    return bounded.lm(model, cells, y, bounded.initial("logistic", M) if th0 is None else th0), y
out = {}
M = [[(min(1, max(0, v + rnd.gauss(0, 0.01))) if v is not None else None) for v in row] for row in ladder()]
r, y = lmfit(M)
th_true = [-2.3 + sum(a) / N + sum(b) / N] + [x - sum(a) / N for x in a[:N - 1]] + [x - sum(b) / N for x in b[:N - 1]]
ref = bounded.lm(model, cells, y, th_true, iters=2000)
out["interior"] = (r[2], abs(r[1] - ref[1]) / ref[1])
M = [[(v + 1e-9 * rnd.gauss(0, 1) if v is not None else None) for v in row] for row in ladder()]
out["low variance"] = (lmfit(M)[0][2], 0)
M = ladder()
for j in range(N):
    if j != 3:
        M[3][j] = 0.0
M = [[(min(1, max(0, v + rnd.gauss(0, 0.005))) if (v is not None and i != 3) else v) for v in row] for i, row in enumerate(M)]
out["zero row"] = (lmfit(M)[0][2], 0)
M = ladder()
for i in range(N):
    if i != 5:
        M[i][5] = 0.0
out["zero column"] = (lmfit(M)[0][2], 0)
M = ladder()
for j in range(N):
    if j != 7:
        M[7][j] = 1.0
out["one row"] = (lmfit(M)[0][2], 0)
out["all zero"] = (lmfit([[0.0 if i != j else None for j in range(N)] for i in range(N)])[0][2], 0)
H = [[0.5 if i != j else None for j in range(N)] for i in range(N)]
for L in (30.0, 40.0, 45.0):
    r, _ = lmfit(H, [L] + [0.0] * (2 * N - 2))
    out[f"saturated {L:g}"] = (r[2], r.saturated_sse)
th = list(th_true)
th[3] += 47.0   # (classified where it stands: iters = 0)
r = bounded.lm(model, cells, [ladder()[i][j] for i, j in cells], th, iters=0)
out["partly saturated"] = (r[2], r.saturated_sse)
print(out)
good = ("interior", "low variance", "zero row", "zero column", "one row", "all zero")
bad = ("saturated 30", "saturated 40", "saturated 45", "partly saturated")
assert all(out[k][0] for k in good), [k for k in good if not out[k][0]]
assert not any(out[k][0] for k in bad), [k for k in bad if out[k][0]]
assert out["interior"][1] < 1e-9 and all(out[k][1] > 1 for k in bad)
f = bounded.fit(H, "logistic", [40.0] + [0.0] * (2 * N - 2))
assert not f["converged"] and f["saturated_sse"] > 30 and f["flat_sse"] is not None, f["reason"]
PY
# ... and review of #49, round 2: (A) a0 = +25, a11 = -25 with targets 0.5 (SSE 5.5, derivatives 1.4e-11: the
#     global ridge used to hide those directions) is NOT converged; (B) Codex's rectangle - a finite local minimum
#     whose residual sits partly on a saturated cell (score exactly 0) - IS converged. Checked against an
#     INDEPENDENT reference that shares no code with bounded.py: its own model and derivative (tanh / cosh), an
#     overparametrized (mu, a_0..11, b_0..11) form, its own Cholesky and Gauss-Newton with line search
$PY - "$T" <<'PY' || fail "the fitting classifier against Codex's round-2 fixtures and an independent reference"
import math, random, sys
sys.path.insert(0, sys.argv[1]); import bounded
N = 12
cells = bounded._cells(N)
model = bounded.Model("logistic", N)
def rsig(x):
    return 0.5 * (1.0 + math.tanh(0.5 * x))
def rdsig(x):
    c = math.cosh(0.5 * x) if abs(x) < 1400 else float("inf")
    return 1.0 / (4.0 * c * c)
def reval(th, Y):
    mu, a, b = th[0], th[1:1 + N], th[1 + N:]
    r, Jr = [], []
    for (i, j) in cells:
        e = mu + a[i] + b[j]
        r.append(Y[(i, j)] - rsig(e))
        d = rdsig(e)
        row = [0.0] * (1 + 2 * N)
        row[0], row[1 + i], row[1 + N + j] = d, d, d
        Jr.append(row)
    return r, Jr
def rsse(th, Y):
    return sum(x * x for x in reval(th, Y)[0])
def rchol_solve(A, bv):
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            L[i][j] = math.sqrt(s) if i == j else s / L[j][j]
    z = [0.0] * n
    for i in range(n):
        z[i] = (bv[i] - sum(L[i][k] * z[k] for k in range(i))) / L[i][i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (z[i] - sum(L[k][i] * x[k] for k in range(i + 1, n))) / L[i][i]
    return x
def rgn(th, Y, iters=400, lam=1e-8):
    S = rsse(th, Y)
    for _ in range(iters):
        r, Jr = reval(th, Y)
        P = len(th)
        A = [[sum(row[p] * row[q] for row in Jr) + (lam if p == q else 0.0) for q in range(P)] for p in range(P)]
        step = rchol_solve(A, [sum(row[p] * ri for row, ri in zip(Jr, r)) for p in range(P)])
        t = 1.0
        while t > 1e-12:
            thn = [x + t * s for x, s in zip(th, step)]
            Sn = rsse(thn, Y)
            if Sn < S:
                break
            t *= 0.5
        if t <= 1e-12 or S - Sn <= 1e-15 * max(S, 1e-300):
            return th, S
        th, S = thn, Sn
    return th, S
def rscore(th, Y):
    r, Jr = reval(th, Y)
    S = sum(x * x for x in r)
    return max(sum(row[p] * ri for row, ri in zip(Jr, r)) ** 2 / sum(row[p] ** 2 for row in Jr) / S for p in range(len(th)))
def bth(mu, a, b):
    ma, mb = sum(a) / N, sum(b) / N
    return [mu + ma + mb] + [x - ma for x in a[:N - 1]] + [x - mb for x in b[:N - 1]]
YA = {c: 0.5 for c in cells}
aA = [25.0] + [0.0] * 10 + [-25.0]
rA = bounded.lm(model, cells, [YA[c] for c in cells], bth(0.0, aA, [0.0] * N), iters=0)
assert not rA[2] and abs(rA[1] - 5.5) < 1e-6, (rA[2], rA[1])
assert rsse([0.0] * (1 + 2 * N), YA) == 0.0 and rscore([0.0] + aA + [0.0] * N, YA) > 0.4   # (independently: not a minimum)
aB = [15.0] + [0.0] * (N - 1)
bB = [0.0, 15.0] + [0.0] * (N - 2)
d01 = rdsig(30.0)
rr = {(0, 1): -0.5, (0, 3): d01 / (2 * rdsig(15.0)), (2, 1): d01 / (2 * rdsig(15.0)), (2, 3): -2 * d01}
YB = {(i, j): rsig(aB[i] + bB[j]) + rr.get((i, j), 0.0) for (i, j) in cells}
assert all(0.0 <= v <= 1.0 for v in YB.values())
rB = bounded.lm(model, cells, [YB[c] for c in cells], bth(0.0, aB, bB), iters=0)
assert rB[2] and abs(rB[1] - 0.25) < 1e-9, (rB[2], rB[1], rB.stationarity)
thB = [0.0] + aB + bB
SB = rsse(thB, YB)
rnd = random.Random(7)
for _ in range(200):          # (independently: every nearby point is worse - a local minimum)
    for h in (1e-3, 1e-2):
        d = [rnd.gauss(0, 1) for _ in thB]
        nd = math.sqrt(sum(x * x for x in d))
        assert rsse([x + h * y / nd for x, y in zip(thB, d)], YB) >= SB - 1e-15
assert rgn(list(thB), YB)[1] >= SB - 1e-12
rnd = random.Random(42)
a = [rnd.gauss(0, 0.8) for _ in range(N)]
b = [rnd.gauss(0, 0.6) for _ in range(N)]
YI = {(i, j): min(1, max(0, bounded.sigmoid(-2.3 + a[i] + b[j]) + rnd.gauss(0, 0.01))) for (i, j) in cells}
fI = bounded.fit([[YI[(i, j)] if i != j else None for j in range(N)] for i in range(N)], "logistic")
_, SR = rgn([-2.3] + [0.0] * (2 * N), YI)
assert fI["converged"] and abs(fI["sse"] - SR) / SR < 1e-9, (fI["sse"], SR)
# review of #49, round 3: A in item permutations - a WEAK COMBINATION of strong columns (a0 = +25 / a1 = -25:
# Codex's case, where column scaling plus a ridge hid a0 - a1) - is NOT converged in every arrangement, on the
# invader and on the resident effects; the reference confirms independently: its own (modified Gram-Schmidt)
# least-squares gain is ~the whole SSE and a line search along its own Gauss-Newton direction realizes a
# large part of it (25% of the SSE in every arrangement; the allowance is 1e-4 of it)
def rmgs(Jr, r):
    m, P = len(Jr), len(Jr[0])
    Q, R, keep = [[Jr[i][p] for i in range(m)] for p in range(P)], [[0.0] * P for _ in range(P)], []
    big = max(math.sqrt(sum(x * x for x in q)) for q in Q)
    for p in range(P):
        v = Q[p]
        for _ in range(2):
            for k in keep:
                dd = sum(x * y for x, y in zip(Q[k], v)); R[k][p] += dd
                v = [x - dd * y for x, y in zip(v, Q[k])]
        nv = math.sqrt(sum(x * x for x in v))
        if nv > 1e-13 * big:
            R[p][p] = nv; Q[p] = [x / nv for x in v]; keep.append(p)
    qr = {p: sum(x * y for x, y in zip(Q[p], r)) for p in keep}
    dlt = [0.0] * P
    for p in reversed(keep):
        dlt[p] = (qr[p] - sum(R[p][c] * dlt[c] for c in keep if c > p)) / R[p][p]
    return sum(v * v for v in qr.values()), dlt
def rprobe(th, Y):
    r, Jr = reval(th, Y)
    S = sum(x * x for x in r)
    gain, dlt = rmgs(Jr, r)
    best, t = 0.0, 1.0
    for _ in range(260):
        best = max(best, S - rsse([x + t * y for x, y in zip(th, dlt)], Y))
        t *= 0.8
    return S, gain, best
for side in ("a", "b"):
    for i, j in ((0, 1), (0, 11), (1, 0), (5, 6), (11, 3), (4, 9)):
        e = [0.0] * N; e[i] = 25.0; e[j] = -25.0
        aa, bb = (e, [0.0] * N) if side == "a" else ([0.0] * N, e)
        r = bounded.lm(model, cells, [YA[c] for c in cells], bth(0.0, aa, bb), iters=0)
        assert not r[2] and r.rank == 2 * N - 1, (side, i, j, r[2], r.stationarity)
        S, gain, best = rprobe([0.0] + aa + bb, YA)
        assert gain > 0.99 * S and best > 0.1 * S, (side, i, j, S, gain, best)
S, gain, best = rprobe(thB, YB)
assert gain < 1e-12 * S and best <= 1e-12, (gain, best)   # B: nothing to gain, nothing realizable
assert "rank_tol" in bounded.FIT_FREEZE and "stat_ridge" not in bounded.FIT_FREEZE
# review of #49, round 4 (Claude), P1-1: the gain's rank cut NESTS inside the flat-cell rule (RANK_TOL / sqrt(n) |R_11|,
# and |R_11| <= sqrt(n) max|J|). At RANK_TOL |R_11| a weak combination on cells with derivatives between 2.5e-14 and
# ~7e-14 was neither in the gain nor flat: A was certified at eta0 = +-30.3 .. 31.3 in the 8 arrangements without item
# 11. Now A over eta0 in [20, 45] (0.05 steps) is never certified, in any of the 12 arrangements. (Every check below
# records its failure, so each one shows on older code.)
def allow_of(y_, S_):
    return 1e-4 * S_ + 1e-12 * max(sum(v * v for v in y_), float(len(y_)))
bad = []
yA = [YA[c] for c in cells]
cert = []
for side in ("a", "b"):
    for i, j in ((0, 1), (0, 11), (1, 0), (5, 6), (11, 3), (4, 9)):
        for k in range(501):
            e0 = 20.0 + 0.05 * k
            e = [0.0] * N; e[i] = e0; e[j] = -e0
            aa, bb = (e, [0.0] * N) if side == "a" else ([0.0] * N, e)
            if bounded.lm(model, cells, yA, bth(0.0, aa, bb), iters=0)[2]:
                cert.append((side, i, j, round(e0, 2)))
if cert:
    bad.append(f"A certified at {len(cert)} of 6012 points, e.g. {cert[:4]}")
e = [0.0] * N; e[0] = 30.8; e[1] = -30.8   # (inside the old gap: resolved at full rank, the probe realizes it)
r = bounded.lm(model, cells, yA, bth(0.0, e, [0.0] * N), iters=0)
if r[2] or r.rank != 2 * N - 1 or not r.stationarity > 0.99 or not (r.probe_decrease or 0.0) >= allow_of(yA, r[1]):
    bad.append(f"A at +-30.8: converged {r[2]}, rank {r.rank}, gain/S {r.stationarity}, probe {r.probe_decrease}")
# ... while B-type legitimate minima stay converged (gain ~0) up to where the flat-cell rule fails closed (a false
# unavailability, never a false certification: from 15.7 + 15.7 the cells at |eta| ~ 31.4 are flat)
def yB(sB):
    aB_, bB_ = [sB] + [0.0] * (N - 1), [0.0, sB] + [0.0] * (N - 2)
    d01_ = rdsig(2 * sB)
    rr_ = {(0, 1): -0.5, (0, 3): d01_ / (2 * rdsig(sB)), (2, 1): d01_ / (2 * rdsig(sB)), (2, 3): -2 * d01_}
    return [rsig(aB_[i] + bB_[j]) + rr_.get((i, j), 0.0) for (i, j) in cells], bth(0.0, aB_, bB_)
for sB in (10.0, 12.0, 14.0, 15.0, 15.5, 15.65, 15.7, 16.0, 17.0):
    yb_, th_ = yB(sB)
    r = bounded.lm(model, cells, yb_, th_, iters=0)
    flat_ok = sB < 15.7
    if r[2] != flat_ok or not r.stationarity < 1e-12 or (flat_ok and r.probe_decrease is not None) or             (not flat_ok and not r.flat_sse > allow_of(yb_, r[1])):
        bad.append(f"B at {sB}: converged {r[2]}, gain/S {r.stationarity}, flat {r.flat_sse}, probe {r.probe_decrease}")
# review of #49, round 4 (Claude), P2-2: the probe refines its coarse 0.8 grid around the scanned SSE's local minima
# (golden section in log t). The reviewer's planted cycles - row 0 at eta0 with targets 1 - 1e-3, items 1-11 at
# 0.5 + kappa sin(2 pi (i - j) / 11), orthogonal to the tangent space - leave a decrease window narrower than the
# grid's 1.25 ratio; they were certified, they are NOT converged, and independently (the reference's own SSE)
# moving row 0 to logit(0.999) lowers the SSE by 10x / 20x the allowance
for kap, e0, mult in ((0.0135, 29.96, 9.0), (0.0095, 29.48, 18.0)):
    YC = {(i, j): (1 - 1e-3 if i == 0 else (0.5 if j == 0 else 0.5 + kap * math.sin(2 * math.pi * (i - j) / 11)))
          for (i, j) in cells}
    yC = [YC[c] for c in cells]
    aC = [e0] + [0.0] * (N - 1)
    r = bounded.lm(model, cells, yC, bth(0.0, aC, [0.0] * N), iters=0)
    al = allow_of(yC, r[1])
    if r[2] or not (r.probe_decrease or 0.0) >= al:
        bad.append(f"planted cycle kappa {kap}: converged {r[2]}, probe / allow {(r.probe_decrease or 0.0) / al:.3g}")
    drop = rsse([0.0] + aC + [0.0] * N, YC) - rsse([0.0, math.log(0.999 / 0.001)] + [0.0] * (N - 1) + [0.0] * N, YC)
    assert drop >= mult * al, (kap, drop, al)   # (the reference: a decrease IS available)
if not all(k_ in bounded.FIT_FREEZE for k_ in ("probe_shrink", "probe_steps", "probe_refine", "probe_golden")):
    bad.append("the probe's constants are not frozen dict keys")
if not abs(getattr(bounded, "gain_cut", lambda n: 0.0)(len(cells)) - bounded.RANK_TOL / math.sqrt(len(cells))) < 1e-30:
    bad.append("no gain_cut = RANK_TOL / sqrt(n)")
assert not bad, bad
PY

# 43. review of #49, finding 4: the Beta part's variance without cancellation (mu 0.5, v 1e-18 used to become
#     0 and an invalid law), exact moments of very concentrated laws, the 1e-12 endpoint band as an explicit,
#     flagged convention, and the Cornish-Fisher quantile of very concentrated Betas against the exact table
$PY - "$T" <<'PY' || fail "a feasible concentrated law rejected through cancellation"
import sys
sys.path.insert(0, sys.argv[1]); import calibrate
for mu, v in ((0.5, 1e-18), (0.01, 1e-12), (2e-5, 4e-10), (0.7, 1e-16)):
    m = calibrate.marginal(mu, v)
    mm, vv = calibrate.marginal_moments(m)
    assert m["valid"] and m["kind"] == "beta" and abs(mm - mu) <= 1e-15 * mu and abs(vv - v) <= 1e-12 * v, (mu, v, m["kind"], vv)
assert calibrate.marginal(0.5, 1e-18)["vb"] == 1e-18
e = calibrate.marginal(0.3, 0.21 * (1 + 5e-13))
assert e["valid"] and e["kind"] == "bernoulli" and e["edge"] and not e["capped"], e
assert not calibrate.marginal(0.3, 0.21 * (1 + 1e-11))["valid"] and not calibrate.marginal(0.3, 0.2)["edge"]
x = calibrate.quantile_marginal(calibrate.marginal(0.5, 1e-18), 0.975, 0.025)
assert abs((x - 0.5) / 1e-9 - 1.959964) < 1e-4, x
q = calibrate.BetaQuantile(2e5, 5e5)
for u in (1e-6, 0.01, 0.3, 0.5, 0.99, 1 - 1e-6):
    assert abs(q(u, 1 - u) - calibrate._beta_quantile_cf(2e5, 5e5, u, 1 - u)) < 5e-10, u
PY
# ... and review of #49, round 2: the table spans EXACTLY s = logit u in [-36, 36] (its endpoints solved), so a
#     valid concentrated law (mu 0.5, v 0.25 / 18,000,001: shapes 9e6, below the Cornish-Fisher cutoff) is a
#     small table - it used to keep its bracketing overshoot to |s| ~ 557,000, ~2.2 million nodes - and the
#     quantile beyond |s| = 36 is solved exactly
$PY - "$T" <<'PY' || fail "the quantile table's registered domain"
import math, sys, time
sys.path.insert(0, sys.argv[1]); import bounded, calibrate
m = calibrate.marginal(0.5, 0.25 / 18000001)
assert m["kind"] == "beta" and abs(m["alpha"] - 9e6) < 1 and abs(m["beta"] - 9e6) < 1, m
t0 = time.time()
q = calibrate.BetaQuantile(m["alpha"], m["beta"])
assert len(q.s) <= 2000 and time.time() - t0 < 60 and q.floor_hits == 0, (len(q.s), q.floor_hits)
assert abs(q.s[0] + 36.0) <= 1e-9 and abs(q.s[-1] - 36.0) <= 1e-9, (q.s[0], q.s[-1])
for u in (1e-30, 1e-20, 1e-14, 1e-6, 0.3, 0.5, 0.9, 1 - 1e-9):
    s = math.log(u) - math.log1p(-u)
    assert abs(q(u, 1 - u) - bounded.sigmoid(q.exact_t(s))) < 1e-9, u
for a, b in ((0.05, 3.0), (2.0, 2.0), (0.8, 0.02)):
    q = calibrate.BetaQuantile(a, b)
    assert abs(q.s[0] + 36.0) <= 1e-9 and abs(q.s[-1] - 36.0) <= 1e-9 and len(q.s) < 5000, (a, b, len(q.s))
PY
# ... and review of #49, round 3: the log-Beta normalizer for large asymmetric shapes (lgamma(a + b) - lgamma(b)
#     was 0 at a = 1, b = 1e16, the true -log B = 36.84) and the extreme-asymmetry regime, against CLOSED FORMS that
#     share nothing with the CDF evaluator: Beta(1, b): F^-1(u) = -expm1(log(1 - u) / b); Beta(a, 1): F^-1(u) =
#     u^(1/a); b and a up to 1e16, u down to e^-40 (beyond the tabulated range: the exact fallback)
$PY - "$T" <<'PY' || fail "the Beta quantile against closed forms"
import math, sys
sys.path.insert(0, sys.argv[1]); import calibrate
US = (math.exp(-40), 1e-10, 0.3, 0.9, 1 - 1e-12)
def close(x, xe, one_minus_xe):
    if xe < 0.5:
        return abs(x - xe) <= 1e-9 * xe
    return abs(x - xe) <= max(1e-9 * one_minus_xe, 4.5e-16)   # (near 1: the double's own resolution)
for b in (3.0, 1e4, 1e9, 1e16):
    q = calibrate.BetaQuantile(1.0, b)
    assert len(q.s) < 3000 and q.floor_hits == 0, (b, len(q.s))
    for u in US:
        lxe = math.log1p(-u) / b
        assert close(q(u, 1 - u), -math.expm1(lxe), math.exp(lxe)), (b, u, q(u, 1 - u), -math.expm1(lxe))
for a in (3.0, 1e4, 1e9, 1e16):
    q = calibrate.BetaQuantile(a, 1.0)
    assert len(q.s) < 3000 and q.floor_hits == 0, (a, len(q.s))
    for u in US:
        lxe = math.log(u) / a
        assert close(q(u, 1 - u), math.exp(lxe), -math.expm1(lxe)), (a, u, q(u, 1 - u), math.exp(lxe))
assert abs(calibrate.betaln(1.0, 1e16) + math.log(1e16)) < 1e-12 and abs(calibrate.betaln(1e16, 1.0) + math.log(1e16)) < 1e-12
for a, b in ((12.0, 30.0), (3.0, 47.0), (0.5, 11.0), (100.0, 250.0), (2.0, 3.0)):
    assert abs(calibrate.betaln(a, b) - (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))) < 1e-11, (a, b)
PY

# ... and review of #49, round 4 (Claude), P3: Beta(a, 1) / Beta(1, b) make the BGRAT series' coefficients c_k (k >= 1)
#     vanish, so the expansion proper was untested. Beta(2, b) (I_x = 1 - (1 - x)^b (1 + b x)) for b up to 1e16 and
#     Beta(1/2, n) (a < 1: the finite-sum identity for an integer second shape), both tails and mirrored: the
#     quantile lies within 1e-9 relative (or the double's resolution) of the reference
$PY - "$T" <<'PY' || fail "the Beta quantile against Beta(2, b) and Beta(1/2, n) references"
import math, sys
sys.path.insert(0, sys.argv[1]); import calibrate
# Beta(2, b): I_x = 1 - (1 - x)^b (1 + b x), as positive terms. With z = -b log(1 - x) and
# delta = b (-log(1 - x) - x) >= 0: P = [1 - e^-z (1 + z)] + e^-z delta; Q = exp(b log(1 - x) + log1p(b x))
def p2(z):   # 1 - e^-z (1 + z) = e^-z sum_{k>=2} z^k / k!
    if z >= 0.5:
        return -math.expm1(-z) - z * math.exp(-z)
    t, s, k = z * z / 2.0, 0.0, 2
    while t > 1e-300 and t > 1e-18 * s:
        s += t
        k += 1
        t *= z / k
    return math.exp(-z) * s
def nl1(x, x1):   # -log(1 - x) - x >= 0
    if x < 0.1:
        t, s, k = x * x, 0.0, 2
        while t / k > 1e-18 * max(s, 1e-300):
            s += t / k
            k += 1
            t *= x
        return s
    return -math.log(x1) - x
def beta2(b, x, x1, upper):   # -> P (or Q = 1 - P) of Beta(2, b) at x (x1 = 1 - x)
    if upper:
        return math.exp(b * (math.log1p(-x) if x < 0.5 else math.log(x1)) + math.log1p(b * x))
    z = -b * math.log(x1) if x >= 0.1 else b * (x + nl1(x, x1))
    return p2(z) + math.exp(-z) * b * nl1(x, x1)
# Beta(1/2, n), n integer: I_x = sqrt(x) sum_{k<n} (1/2)_k / k! (1 - x)^k (the finite-sum identity for an integer second
# shape), and 1 - I_x = sqrt(x) sum_{k>=n} (1/2)_k / k! (1 - x)^k (the binomial series of (1 - y)^(-1/2) = x^(-1/2))
def betahalf(n, x, x1, upper):
    n = int(n)
    if not upper:
        c, w, lo = 1.0, 1.0, 0.0
        for k in range(n):
            lo += c * w
            c *= (k + 0.5) / (k + 1.0)
            w *= x1
        return math.sqrt(x) * lo
    lc = math.lgamma(n + 0.5) - math.lgamma(0.5) - math.lgamma(n + 1.0) + n * math.log(x1) if x1 > 0 else -math.inf
    t, hi, k = math.exp(lc), 0.0, n
    while t > 1e-19 * hi and t > 0:
        hi += t
        t *= (k + 0.5) / (k + 1.0) * x1
        k += 1
    return math.sqrt(x) * hi
def check(cdf, x, x1, u, u1, floor=0.0, eps=1e-9):
    """u lies between the reference CDF at the quantile moved by +-eps relative (or the double's resolution)."""
    if x < 0.5:
        d = max(eps * x, floor)
        xl, xh = x - d, x + d
        xl1, xh1 = 1.0 - xl, 1.0 - xh
    else:
        d = max(eps * x1, 4.5e-16, floor)
        xl1, xh1 = x1 + d, max(x1 - d, 1e-300)
        xl, xh = 1.0 - xl1, 1.0 - xh1
    up = u > 0.5
    Fl, Fh = cdf(max(xl, 1e-300), xl1, up), cdf(xh, xh1, up)
    if not up:
        return Fl <= u <= Fh, (Fl, u, Fh)
    return Fl >= u1 >= Fh, (Fl, u1, Fh)
US = (math.exp(-40), 1e-10, 0.3, 0.9, 1 - 1e-12)
# the references agree with each other's closed forms where they overlap: Beta(2, 1) = x^2, Beta(1/2, 1) = sqrt(x)
for x in (1e-9, 0.01, 0.4, 0.93):
    P, Q = beta2(1.0, x, 1 - x, False), beta2(1.0, x, 1 - x, True)
    assert abs(P - x * x) <= 1e-15 * x * x and abs(P + Q - 1) < 1e-15, (x, P)
    P = betahalf(1, x, 1 - x, False)
    assert abs(P - math.sqrt(x)) <= 1e-15 * math.sqrt(x), (x, P)
    if x >= 0.01:   # (the upper-tail series needs ~40 / x terms)
        Q = betahalf(1, x, 1 - x, True)
        assert abs(P + Q - 1) < 1e-13, (x, P, Q)
        P, Q = betahalf(40, x, 1 - x, False), betahalf(40, x, 1 - x, True)
        assert abs(P + Q - 1) < 1e-13, (x, P, Q)
res = []
for a, b, cdf in [(2.0, bb, (lambda x, x1, up, bb=bb: beta2(bb, x, x1, up))) for bb in (3.0, 50.0, 1e4, 1e9, 1e16)] + \
                 [(0.5, bb, (lambda x, x1, up, bb=bb: betahalf(bb, x, x1, up))) for bb in (3.0, 50.0, 1e4)]:
    q = calibrate.BetaQuantile(a, b)
    qm = calibrate.BetaQuantile(b, a) if b <= 1e9 else None   # (mirrored: x -> 1 - x)
    assert len(q.s) < 3000 and q.floor_hits == 0, (a, b, len(q.s))
    for u in US:
        ok, info = check(cdf, q(u, 1 - u), 1 - q(u, 1 - u), u, 1 - u)
        res.append((a, b, u, ok))
        assert ok, (a, b, u, info)
        if qm is not None:
            xm = qm(1 - u, u)   # = 1 - (the (a, b) quantile at u)
            ok, info = check(cdf, 1.0 - xm, xm, u, 1 - u, floor=2.3e-16)
            assert ok, ("mirrored", a, b, u, info)
assert calibrate._asym_ok(2.0, 1e4) and calibrate._asym_ok(2.0, 1e16) and calibrate._asym_ok(0.5, 1e4)
PY

# 49. review of #49, round 2, finding 5: a required noiseless refit of the CLIPPED NULL that does not converge
#     leaves the plant unconstructed (it used to be ignored: only its d_res was kept), and the gate's validity fails
$PY - "$T" <<'PY' || fail "an unconverged clipped-null refit"
import copy, json, random, sys
sys.path.insert(0, sys.argv[1]); import calibrate, gate, infer
rnd = random.Random(49)
N = 12
par = {"mu": -2.3, "a": [rnd.gauss(0, 0.8) for _ in range(N)], "b": [rnd.gauss(0, 0.6) for _ in range(N)]}
eta, mean0, th0 = calibrate._ladder(par, list(range(N)), N)
v = infer.cycle_template(N, "diffuse", seed=5)
ok = calibrate.feasible_plant(eta, mean0, th0, v, 0.01)
assert ok["solved"] and ok["clip0_converged"] is True
pd0 = calibrate.plant_diagnostics
calls = []
def pd(m, m0, th):
    out = pd0(m, m0, th)
    calls.append(1)
    return out[:2] + ((False,) if len(calls) == 1 else (out[2],)) + out[3:]   # only the first (c = 0) refit fails
calibrate.plant_diagnostics = pd
x = calibrate.feasible_plant(eta, mean0, th0, v, 0.01)
calibrate.plant_diagnostics = pd0
assert not x["solved"] and x["clip0_converged"] is False and "clipped null" in x["failure"], x.get("failure")
man = json.load(open("g37/manifest.json"))
res = {t[0]: json.load(open(f"g37/tasks/{t[0]:05d}.json")) for t in man["schedule"]}
agg = gate.aggregate(res, man["schedule"])
agg[("L", "target")]["plants"]["0/1"]["clip0_converged"] = False
v_ = [c for c in gate.decide_gate(agg, None, False, [])[0] if c["criterion"] == "validity"][0]
assert not v_["ok"] and any("target plant 0/1" in p for p in v_["problems"]), v_
PY

# 50. review of #49, round 3, finding 1: a FORMAL receipt covers only tasks computed by the run that issues it.
#     Coherent fabrication planted in the cache BEFORE the receipt is issued - every record correctly bound
#     (manifest, run, construction) but with invented counters - is ignored by a formal run, which recomputes
#     every task; an exploratory resume may reuse its cache, and its receipt is not formal
$PY - "$T" <<'PY' > t50.log 2>&1 || fail "a formal receipt over fabricated cached counters: $(tail -3 t50.log)"
import argparse, contextlib, io, json, os, shutil, sys
sys.path.insert(0, sys.argv[1]); import gate
m0 = gate.manifest
gate.manifest = lambda counts=None, spec=None: dict(m0(counts, spec), formal=True)   # the formal path on the toy registration
shutil.rmtree("g50", ignore_errors=True)
args = argparse.Namespace(out="g50", bank="bank37/blocks.json", bank_plan="plan37.jsonl", bank_inputs=None, workers=1,
                          counts="counts37b.json", bank_spec="spec37.json")
with contextlib.redirect_stdout(io.StringIO()):
    gate.cmd_run(args)
genuine = {f: open(f"g50/tasks/{f}").read() for f in os.listdir("g50/tasks")}
for f, text in genuine.items():   # fabricate: every null clean, every alternative rejects - coherent and bound
    t = json.loads(text)
    n = t["n"]
    alt = t["variant"] != "null" and not t["variant"].startswith("outer")
    for k_ in ("H1", "H1b", "claim"):
        if t["world"] in ("E", "G") and k_ != "H1":
            continue
        t["rej"][k_] = t["rej05"][k_] = n if alt else 0
        t["unavailable"][k_] = 0
    open(f"g50/tasks/{f}", "w").write(json.dumps(t, sort_keys=True) + "\n")
out = io.StringIO()
with contextlib.redirect_stdout(out):
    gate.cmd_run(args)
log = out.getvalue()
assert "formal run: %d cached task record(s) ignored" % len(genuine) in log and "0 already done" in log, log[:400]
def body(text):   # a recomputed record equals the genuine one, up to its wall time
    t = json.loads(text); t.pop("seconds"); return t
assert all(body(open(f"g50/tasks/{f}").read()) == body(text) for f, text in genuine.items()), "a fabricated record survived"
rc = json.load(open("g50/receipt.json"))["components"]
assert rc["formal"] is True and rc["tasks_computed_by_this_run"] == len(genuine) and "RECEIPT" in log, rc
gate.manifest = m0
q = gate.verify_record("g37", receipt_sha=json.load(open("g37/receipt.json"))["receipt"])[1]
assert any("not a formal receipt" in x for x in q), q   # (g37 was resumed: 21 of 42 tasks came from its cache)
PY

# 51. review of #49, round 4 (Claude), P2-3: the fit classifier's reports are recorded - the source fits carry every
#     report, every bounded task record summarizes its H1b decisions' fits (fits, unconverged, probed,
#     probe-certified, the largest probe decrease, unresolved-block energy and flat-cell SSE, the smallest resolved
#     Hessian eigenvalue), the decision's diagnostics and gate.md report them, and a malformed summary is a problem
$PY - "$T" <<'PY' > t51.log 2>&1 || fail "the gate's fit-classifier reports: $(tail -3 t51.log)"
import copy, json, os, sys
sys.path.insert(0, sys.argv[1]); import bounded, gate
man_sha, run_sha = gate.sha256_file("g37/manifest.json"), gate.sha256_file("g37/run.json")
sched = {t[0]: t for t in json.load(open("g37/manifest.json"))["schedule"]}
cl = json.load(open("g37/cell_laws.json"))
assert all(set(gate.FIT_REPORTS) <= set(fi) for fi in cl["fit_info"].values()), cl["fit_info"]
tot, recs = None, {}
for f in sorted(os.listdir("g37/tasks")):
    r = json.load(open(f"g37/tasks/{f}"))
    t = sched[r["index"]]
    recs[r["index"]] = (r, t)
    if t[1] in ("E", "G"):
        assert r["fit_diag"] is None, r["fit_diag"]
        continue
    fd = r["fit_diag"]
    assert sorted(fd) == sorted(bounded.FIT_DIAG_KEYS) and fd["fits"] == (4 * t[3] if r["built"] else 0), (t, fd)
    assert fd["probe_certified"] <= fd["probed"] <= fd["fits"] and fd["unconverged"] <= fd["fits"], fd
    tot = bounded.merge_fit_diag(tot, fd)
dec = json.load(open("g37/decision.json"))
rows = dec["diagnostics"]["fit_classifier"]
assert rows and sum(x["fits"] for x in rows) == tot["fits"] and sum(x["probed"] for x in rows) == tot["probed"], (rows, tot)
assert "Detector fits (H1b's four logistic mean fits per dataset" in open("g37/gate.md").read()
r, t = next(v for v in recs.values() if v[1][1] == "L")
assert not gate.task_problems(r, t, man_sha, run_sha), gate.task_problems(r, t, man_sha, run_sha)
for mut in ({"fits": 4 * t[3] + 1}, {"probe_certified": r["fit_diag"]["probed"] + 1}, {"max_probe_decrease": "x"}):
    r2 = copy.deepcopy(r)
    r2["fit_diag"].update(mut)
    assert "fit_diag malformed" in gate.task_problems(r2, t, man_sha, run_sha), mut
r2 = copy.deepcopy(r)
del r2["fit_diag"]
assert "fit_diag malformed" in gate.task_problems(r2, t, man_sha, run_sha)
r, t = next(v for v in recs.values() if v[1][1] == "E")
r2 = dict(r, fit_diag=bounded.fit_diag())
assert "an H1-only world with fit diagnostics" in gate.task_problems(r2, t, man_sha, run_sha)
PY

# 19. self-tests of the inference and bounded-scale modules
$PY "$T/infer.py" > /dev/null || fail "infer.py self-test"
$PY "$T/bounded.py" > /dev/null || fail "bounded.py self-test"
echo "invasion_tooling: ok"
