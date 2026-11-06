#!/usr/bin/env bash
# redqueen_tooling.sh — end-to-end tests of tools/redqueen against the real engine (serial build),
# on tiny Stage C worlds (200 prey, a few thousand steps), plus its unit tests.
#
#   tests/redqueen_tooling.sh PATH/TO/evo_boids WORKDIR
#   env: PYTHON (default python3), RQ_TEST_WORKERS (default 10: the runner's >= 10-worker path)
#
#   1. ckpt.py: version-2 and version-1 files validate; tampered files are refused by the adapter
#      AND by the engine (the two agree); a Python load + dump resumes byte-identically;
#   2. common.py: the common-environment checkpoint is deterministic (same seed, same bytes), its
#      manifest records sampling and duplication, the pinned engine loads it, runs 100 steps and
#      round-trips it through save / load (common.py validate), and the transplant accepts it;
#   3. plan.py: a pending plan, the final plan bound to it (refused when anything but the hashes
#      differs, or a frame is not the registered one), deterministic bytes;
#   4. run.py with RQ_TEST_WORKERS workers and small chunks: every cell done and packed, the
#      score checks (fixed K, predation deaths == captures, the fork's zero captures, shared
#      common checkpoints), resume skips everything;
#   5. determinism: a second root with other workers / chunk sizes gives byte-identical bundles;
#   6. replay of a packed cell into an empty directory is identical, also with its predator
#      source moved away (read from the store); a non-empty --out is refused;
#   7. resume after a SIGKILLed worker (the cell fails, the rerun is identical), --retries
#      requeues a killed cell in the same session, and a SIGKILLed runner leaves no engine and
#      resumes to identical bundles;
#   8. STOP file, disk guard, memory guard (fail closed), a changed source, a changed plan row
#      and a pending plan are all refused.
set -u
BIN=${1:?usage: redqueen_tooling.sh EVO_BOIDS WORKDIR}
W=${2:?usage: redqueen_tooling.sh EVO_BOIDS WORKDIR}
case "$BIN" in /*) ;; *) BIN="$PWD/$BIN" ;; esac
T=$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/redqueen" && pwd)
PY="${PYTHON:-python3} -I"
NW=${RQ_TEST_WORKERS:-10}
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
eng() { "$BIN" --no-render --log-every 250 "$@" > /dev/null 2>&1 || fail "evo_boids $* exited $?"; }
RUN="$PY $T/run.py"
GUARD="--disk-min $W:200 --mem-min-mb 50"
$PY -c 'import sys; print("redqueen_tooling: Python", sys.version.split()[0])'

$PY "$T/test_redqueen.py" > unit.log 2>&1 || { tail -30 unit.log; fail "unit tests"; }

# --- tiny Stage C worlds: A and B (periodic checkpoints at 1500 and 3000, a one-step F1 replay), a template
STAGEC="--population 200 --predators 6 --predator-economy --predator-brain --predator-meal 14
        --predator-max-pop 12 --predator-min-pop 2 --predator-max-age 15"
for w in A:21 B:22; do
    n=${w%%:*}; s=${w##*:}
    eng --headless 3000 --seed $s $STAGEC --checkpoint-every 1500 --save-checkpoint $n.json
    eng --headless 1 --seed $s $STAGEC --save-checkpoint $n.F1.json
done
eng --headless 1 --seed 99 $STAGEC --save-checkpoint T.json
eng --headless 1 --seed 31 $STAGEC --population 60 --save-checkpoint S60.json
eng --headless 300 --seed 7 --population 150 --predators 4 --predator-economy --save-checkpoint V1.json
[ -f A.1500.json ] && [ -f B.3000.json ] || fail "the periodic checkpoints are missing"

# 1. the adapter
$PY "$T/ckpt.py" validate A.1500.json B.3000.json T.json V1.json > /dev/null || fail "ckpt.py validate"
$PY - "$T" <<'PY' || fail "ckpt.py: versions, extraction"
import sys; sys.path.insert(0, sys.argv[1]); import ckpt
a = ckpt.load("A.3000.json"); v1 = ckpt.load("V1.json")
assert a["formatVersion"] == 2 and v1["formatVersion"] == 1
m = ckpt.meta(a)
assert m["predator_brain"] and m["frame"] == 3000 and m["prey_alive"] > 0 and m["predators"] >= 2, m
p = ckpt.predators(a)
assert all(len(x["genes"]) == 2 * len(x["genes"]) // 2 and x["id"] < m["next_predator_id"] for x in p)
assert len(ckpt.prey(a, alive_only=True)) == m["prey_alive"]
assert all(x.get("genes") is None for x in ckpt.predators(v1))
PY
# tampered copies: the adapter and the engine must both refuse each
$PY - "$T" <<'PY' || fail "building the tampered files"
import json, sys; sys.path.insert(0, sys.argv[1]); import ckpt
base = ckpt.load("A.1500.json")
def put(name, f):
    c = json.loads(json.dumps(base)); f(c); open(name, "w").write(ckpt.dumps(c))
put("bad_id.json", lambda c: c["predators"]["id"].__setitem__(0, c["world"]["nextPredatorId"]))
put("bad_genes.json", lambda c: c["predators"]["genes"].pop())
put("bad_sensor.json", lambda c: c["predators"].update(sensorSet=2))
put("bad_brain.json", lambda c: c["config"].update(predatorBrain=False))
put("bad_nextid.json", lambda c: c["world"].update(nextId=1))
PY
for f in bad_id bad_genes bad_sensor bad_brain bad_nextid; do
    $PY "$T/ckpt.py" validate $f.json > /dev/null 2>&1 && fail "ckpt.py accepted $f"
    "$BIN" --no-render --load-checkpoint $f.json --headless 1 > /dev/null 2>&1 && fail "the engine accepted $f (the adapter is stricter than the engine?)"
done
$PY - "$T" <<'PY' || fail "round trip"
import sys; sys.path.insert(0, sys.argv[1]); import ckpt
open("A_rt.json", "w").write(ckpt.dumps(ckpt.load("A.1500.json")))
PY
eng --load-checkpoint A.1500.json --headless 300 --save-checkpoint A_o.json
eng --load-checkpoint A_rt.json --headless 300 --save-checkpoint A_rt_o.json
cmp -s A_o.json A_rt_o.json || fail "a Python load + dump of a version-2 checkpoint does not resume identically"

# 2. the common-environment checkpoint
cb() { $PY "$T/common.py" build --template T.json --source "$1" --n "$2" --seed "$3" --out "$4.json" --manifest "$4.manifest.json" > /dev/null || fail "common.py build $4"; }
cb A.3000.json 100 5 c1; cb A.3000.json 100 5 c2; cb A.3000.json 100 6 c3; cb S60.json 150 5 c4
cmp -s c1.json c2.json && cmp -s c1.manifest.json c2.manifest.json || fail "common.py: the same seed gave different bytes"
cmp -s c1.json c3.json && fail "common.py: another seed gave the same checkpoint"
$PY - "$T" <<'PY' || fail "common checkpoint contents"
import json, sys; sys.path.insert(0, sys.argv[1]); import ckpt, common
c, m, t, s = ckpt.load("c1.json"), json.load(open("c1.manifest.json")), ckpt.load("T.json"), ckpt.load("A.3000.json")
cs = c["creatures"]
assert cs["count"] == 100 and cs["id"] == list(range(1, 101)) and c["world"]["nextId"] == 101
assert c["predators"]["count"] == 0 and c["world"]["nextPredatorId"] == 1 and c["formatVersion"] == 2
assert c["world"]["frame"] == t["world"]["frame"] and c["food"] == t["food"] and c["config"] == t["config"]
assert set(cs["age"]) == {0.0} and set(cs["foodReserves"]) == {30.0} and set(cs["neuronOutputs"]) == {0.5}
assert cs["oscPhase"] == t["creatures"]["oscPhase"][:100], "template oscillator phases"
assert all(v == 0 for k, v in c["counters"].items() if "Stride" not in k)
pool = ckpt.prey(s, alive_only=True)
assert m["sampling"]["pool"] == len(pool) and m["sampling"]["with_replacement"] == (len(pool) < 100), m["sampling"]
assert m["source"]["sha256"] and m["output"]["sha256"]
for i, r in enumerate(ckpt.prey(c)):
    assert r["genes"] == pool[m["slots"]["source_index"][i]]["genes"]
m4 = json.load(open("c4.manifest.json"))
s4 = m4["sampling"]
assert s4["pool"] < 150 and s4["with_replacement"] and s4["max_copies"] >= 2 and s4["distinct"] == s4["pool"], s4
PY
$PY "$T/common.py" validate --binary "$BIN" --work val1 c1.json > val1.log 2>&1 || fail "common.py validate: $(tail -3 val1.log)"
$PY "$T/common.py" validate --binary "$BIN" --work val4 c4.json > val4.log 2>&1 || fail "common.py validate (duplicated): $(tail -3 val4.log)"
grep -q '"python_round_trip_exact":true' val1/validate.json && grep -q '"engine_resume_exact":true' val1/validate.json \
    || fail "validate.json does not record both round trips"
eng --load-checkpoint c1.json --predators-from B.3000.json --transplant-count 3 --transplant-seed 4 --assay frozen \
    --transplant-out c1_arena.json
grep -q '"count":3' c1_arena.json || fail "the transplant onto a common checkpoint"

# 3. plan.py
cat > design.json <<EOF
{"schema": "finfolk.redqueen.design/1", "name": "smoke", "seed_namespace": "rq-smoke-test",
 "times": {"F1": 1, "T1500": 1500, "T3000": 3000},
 "worlds": {"A": {"uuid": "11111111-aaaa", "pattern": "$W/A.{frame}.json", "paths": {"F1": "$W/A.F1.json"}},
            "B": {"uuid": "22222222-bbbb", "pattern": "$W/B.{frame}.json", "paths": {"F1": "$W/B.F1.json"}}},
 "templates": ["$W/T.json"],
 "defaults": {"assay": "frozen", "k": 3, "prey_policy": "common", "n_prey": 100, "sampling": "wor-balanced",
              "steps": 600, "horizons": [200, 600], "log_every": 100, "checkpoint_every": 200},
 "blocks": [
  {"name": "coarse", "prey_worlds": ["A"], "prey_times": ["F1", "T3000"], "predators": "same",
   "predator_times": ["F1", "T3000"], "replicates": 2, "with_nopred": true},
  {"name": "cross", "prey_worlds": ["A"], "prey_times": ["T3000"], "predators": {"partner": {"A": "B"}},
   "predator_times": ["T1500"], "replicates": 1, "prey_policy": "native"},
  {"name": "rand", "prey_worlds": ["A"], "prey_times": ["T1500"], "predators": "random", "replicates": 1}]}
EOF
$PY "$T/plan.py" design.json --pending --out plan.pending.jsonl 2> plan_p.log || fail "plan.py --pending: $(cat plan_p.log)"
$PY "$T/plan.py" design.json --against plan.pending.jsonl --out plan.jsonl 2> plan_f.log || fail "plan.py --against: $(cat plan_f.log)"
$PY "$T/plan.py" design.json --against plan.pending.jsonl --out plan2.jsonl 2> /dev/null || fail "plan.py (again)"
cmp -s plan.jsonl plan2.jsonl || fail "plan.py is not deterministic"
[ "$(wc -l < plan.jsonl)" = 14 ] || fail "plan.py: expected 14 cells, got $(wc -l < plan.jsonl)"
sed 's/"steps": 600/"steps": 800/' design.json > design_x.json
$PY "$T/plan.py" design_x.json --against plan.pending.jsonl --out x.jsonl 2> /dev/null && fail "a final plan that is not the registered pending plan"
sed 's/"T1500": 1500/"T1500": 1600/; s/A.{frame}/A.{label}/' design.json > design_f.json
cp A.1500.json A.T1500.json; cp A.3000.json A.T3000.json
$PY "$T/plan.py" design_f.json --out x.jsonl 2> planf.log && fail "a snapshot at the wrong frame was registered"
grep -q "frame 1500, registered 1600" planf.log || fail "the frame refusal does not say why: $(cat planf.log)"
$RUN --plan plan.pending.jsonl --root rpend --binary "$BIN" $GUARD > pend.log 2>&1 && fail "run.py ran a pending plan"

# 4. the runner
$RUN --plan plan.jsonl --root r1 --binary "$BIN" --workers $NW --chunk-size 5 $GUARD > r1.log 2>&1 || fail "run.py: $(tail -5 r1.log)"
$RUN --root r1 --status > st1.json || fail "status"
$PY - "$T" <<'PY' || fail "the finished root"
import json, os, sys, zipfile; sys.path.insert(0, sys.argv[1]); import store, rqlib
st = json.load(open("st1.json"))
assert st["done"] == st["plan_cells"] == st["packed"] == 14 and st["finished_unpacked"] == 0 and st["chunks"] == 3, st
assert os.listdir("r1/work") == [], os.listdir("r1/work")
recs, cells = store.load_index("r1")
assert [len(r["cells"]) for r in recs] == [5, 5, 4]
B = {c: json.loads(store.read_member("r1", c, cells=cells)) for c in cells}
groups = {}
for cid, b in B.items():
    sc, cl = b["score"], b["cell"]
    assert sc["schema"] == "finfolk.redqueen.score/1" and [h["steps"] for h in sc["horizons"]] == [200, 600]
    h5 = sc["horizons"][-1]
    assert 0 <= h5["survival"] <= 1 and h5["deaths_predation"] == h5["captures"], (cid, h5)
    if cl["kind"] == "nopred":
        assert h5["captures"] == 0 and h5["capture_rate"] is None and h5["predators"] == 0, cid
    else:
        assert h5["predators"] == 3 and abs(h5["predator_seconds"] - 3 * 600 * 0.016) < 1e-9, (cid, h5)
        assert b["arena_manifest"]["predators"]["count"] == 3
    assert b["engine_args"]["assay"][:4] == ["--load-checkpoint", "arena.json", "--reseed-after-load", str(cl["seeds"]["reseed"])]
    assert "end.json" in b["files"] and len([f for f in b["files"] if f.startswith("end.")]) == 4, sorted(b["files"])
    if cl["prey_policy"] == "common":
        groups.setdefault(cl["groups"]["common"], set()).add(b["files"]["common.json"])
        assert store.has("r1", b["common_manifest_sha256"]), "common manifest not in the store"
    for role in ("prey", "predators", "template"):
        x = cl.get(role)
        if isinstance(x, dict) and x.get("sha256"):
            assert store.has("r1", x["sha256"]), (cid, role)
assert groups and all(len(v) == 1 for v in groups.values()), groups
assert sum(1 for b in B.values() if b["cell"]["kind"] == "nopred") == 4
assert any(b["score"]["horizons"][-1]["captures"] > 0 for b in B.values()), "no captures at all (the test proves nothing)"
assert any(b["cell"]["prey_policy"] == "native" for b in B.values())
PY
$RUN --plan plan.jsonl --root r1 --binary "$BIN" --workers $NW $GUARD > r1b.log 2>&1 || fail "run.py resume"
grep -q "14 already done, 0 to run" r1b.log || fail "run.py resume did not skip the finished cells: $(tail -3 r1b.log)"

# bundles of a root by cell id, as JSON lines (for the comparisons below)
bundles() { $PY - "$T" "$1" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import store, rqlib
_, cells = store.load_index(sys.argv[2])
for c in sorted(cells):
    print(c, rqlib.sha256_bytes(store.read_member(sys.argv[2], c, cells=cells)))
PY
}
bundles r1 > b1.txt

# 5. determinism across roots, worker counts and chunk sizes
$RUN --plan plan.jsonl --root r2 --binary "$BIN" --workers 2 --chunk-size 100 $GUARD > r2.log 2>&1 || fail "run.py (r2): $(tail -5 r2.log)"
bundles r2 > b2.txt
cmp -s b1.txt b2.txt || fail "the same plan rows gave different bundles: $(diff b1.txt b2.txt | head -5)"

# 6. replay
CROSS=$(grep -o '"id":"A.T3000~B.T1500[^"]*"' plan.jsonl | cut -d'"' -f4)
FORK=$(grep -o '"id":"A.T3000~none[^"]*r01"' plan.jsonl | cut -d'"' -f4)
$RUN --root r1 --replay "$FORK" --out rp1 > rp1.log 2>&1 || fail "replay of $FORK: $(tail -5 rp1.log)"
grep -q '"identical":true' rp1/cell/replay.json || fail "replay.json does not say identical"
ls rp1/cell/end.*.json > /dev/null 2>&1 || fail "the replay did not bring the checkpoints back"
mv B.1500.json B.1500.moved
$RUN --root r1 --replay "$CROSS" --out rp2 > rp2.log 2>&1 || fail "replay with the source moved (store): $(tail -5 rp2.log)"
mv B.1500.moved B.1500.json
$RUN --root r1 --replay "$CROSS" --out rp2 > rp3.log 2>&1 && fail "a replay into a non-empty --out"

# 7. kills. (a) a worker SIGKILLed while its cell is paused after the transplant: the cell fails,
#    the runner stops; the restart moves the attempt aside and reruns it identically
workers_of() { pgrep -f -- "--root $W/$1 --_cell" ; }
paused() {   # wait for the paused cell (the hook writes its id into the flag file) -> its id
    for _ in $(seq 1 600); do [ -s pause_once ] && break; sleep 0.1; done
    [ -s pause_once ] && head -1 pause_once
}
RQ_TEST_PAUSE="after-transplant:60:$W/pause_once" $RUN --plan plan.jsonl --root r3 --binary "$BIN" --workers 2 $GUARD > r3a.log 2>&1 &
rp=$!
victim=$(paused) || { kill $rp; fail "no cell reached the pause"; }
pkill -KILL -f -- "--root $W/r3 --_cell $victim" || { kill $rp; fail "no worker to kill"; }
wait $rp; rc=$?
[ "$rc" = 1 ] || fail "a runner whose worker was killed exited $rc, expected 1"
grep -q "FAILED .* (exit -9)" r3/runner.log || fail "the killed cell is not reported: $(tail -3 r3/runner.log)"
$RUN --plan plan.jsonl --root r3 --binary "$BIN" --workers $NW --chunk-size 5 $GUARD > r3b.log 2>&1 || fail "resume after the kill: $(tail -5 r3b.log)"
ls r3/attempts/*.attempt1/cell.stderr.log > /dev/null 2>&1 || fail "the killed attempt was not kept"
ls r3/attempts/*.attempt1/end.*.json > /dev/null 2>&1 && fail "the killed attempt kept its checkpoints"
bundles r3 > b3.txt
cmp -s b1.txt b3.txt || fail "the resumed root's bundles differ"
# (b) --retries: the killed cell is requeued in the same session
rm -f pause_once
RQ_TEST_PAUSE="after-transplant:60:$W/pause_once" $RUN --plan plan.jsonl --root r4 --binary "$BIN" --workers 2 --retries 1 $GUARD > r4.log 2>&1 &
rp=$!
victim=$(paused) || { kill $rp; fail "no cell reached the pause (r4)"; }
pkill -KILL -f -- "--root $W/r4 --_cell $victim" || { kill $rp; fail "no worker to kill (r4)"; }
wait $rp; rc=$?
[ "$rc" = 0 ] || fail "--retries 1 did not finish the plan (exit $rc): $(tail -3 r4.log)"
grep -q "KILLED .*requeued" r4/runner.log || fail "--retries did not requeue the killed cell"
bundles r4 > b4.txt
cmp -s b1.txt b4.txt || fail "the retried root's bundles differ"
# (c) the runner itself SIGKILLed: its workers die with it (PR_SET_PDEATHSIG), no engine is left,
#     and the restart finishes identically
rm -f pause_once
RQ_TEST_PAUSE="after-transplant:60:$W/pause_once" $RUN --plan plan.jsonl --root r5 --binary "$BIN" --workers 2 $GUARD > r5a.log 2>&1 &
rp=$!
paused > /dev/null || { kill $rp; fail "no cell reached the pause (r5)"; }
kill -KILL $rp; wait $rp 2> /dev/null
for _ in $(seq 1 100); do [ -z "$(workers_of r5)" ] && [ -z "$(pgrep -f "$W/r5/bin/evo_boids")" ] && break; sleep 0.2; done
[ -z "$(workers_of r5)" ] || fail "workers outlived the SIGKILLed runner"
[ -z "$(pgrep -f "$W/r5/bin/evo_boids")" ] || fail "an engine outlived the SIGKILLed runner"
$RUN --plan plan.jsonl --root r5 --binary "$BIN" --workers $NW $GUARD > r5b.log 2>&1 || fail "resume after the runner was killed: $(tail -5 r5b.log)"
bundles r5 > b5.txt
cmp -s b1.txt b5.txt || fail "the bundles after a runner kill differ"

# 8. refusals and guards
touch r6_stop; mkdir -p r6; mv r6_stop r6/STOP
$RUN --plan plan.jsonl --root r6 --binary "$BIN" $GUARD > r6.log 2>&1; rc=$?
[ "$rc" = 75 ] || fail "a STOP file: exit $rc, expected 75"
ls r6/work/* > /dev/null 2>&1 && fail "a STOP file admitted a cell"
$RUN --plan plan.jsonl --root r7 --binary "$BIN" --disk-min "$W:999999999" --mem-min-mb 50 > r7.log 2>&1; rc=$?
[ "$rc" = 75 ] && grep -q "disk guard" r7/STOP || fail "the disk guard (exit $rc)"
printf 'MemAvailable: lots kB\n' > meminfo.bad
RQ_MEMINFO=$W/meminfo.bad $RUN --plan plan.jsonl --root r8 --binary "$BIN" --workers 1 $GUARD > r8.log 2>&1; rc=$?
[ "$rc" = 2 ] || fail "an unreadable memory reading: exit $rc, expected 2"
ls r8/work/* > /dev/null 2>&1 && fail "the runner admitted a cell without a memory reading"
cp T.json T2.json
sed "s#$W/T.json#$W/T2.json#" design.json > design_t2.json
$PY "$T/plan.py" design_t2.json --out plan_t2.jsonl 2> /dev/null || fail "plan.py (T2)"
echo " " >> T2.json
$RUN --plan plan_t2.jsonl --root r9 --binary "$BIN" $GUARD > r9.log 2>&1; rc=$?
[ "$rc" = 2 ] && grep -q "sources changed" r9.log || fail "a changed template was not refused (exit $rc)"
$PY - <<'PY' || fail "editing a plan row"
import json
rows = [json.loads(l) for l in open("plan.jsonl")]
rows[0]["horizons"] = [600]
open("plan_edit.jsonl", "w").write("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))
PY
$RUN --plan plan_edit.jsonl --root r1 --binary "$BIN" $GUARD > r1e.log 2>&1; rc=$?
[ "$rc" = 2 ] && grep -q "differs from the one it was packed with" r1e.log || fail "a changed row of a finished cell (exit $rc)"
# a donor whose predators are extinct: planned with a warning, and the cell fails as biological
# (exit 9: never a fabricated predator), which stops the runner
$PY - "$T" "$W" <<'PY' || fail "building the extinct donor"
import json, sys; sys.path.insert(0, sys.argv[1]); import ckpt
c = ckpt.load("B.1500.json")
for k, v in list(c["predators"].items()):
    if isinstance(v, list):
        c["predators"][k] = []
c["predators"]["count"] = 0
open("Z.1500.json", "w").write(ckpt.dumps(c))
d = json.load(open("design.json"))
d["worlds"]["Z"] = {"uuid": "33333333-zzzz", "pattern": sys.argv[2] + "/Z.{frame}.json"}
d["blocks"] = [{"name": "z", "prey_worlds": ["A"], "prey_times": ["T1500"], "predators": {"world": "Z"},
                "predator_times": ["T1500"], "replicates": 1}]
json.dump(d, open("design_z.json", "w"))
PY
$PY "$T/plan.py" design_z.json --out plan_z.jsonl 2> plan_z.log || fail "plan.py (extinct donor): $(cat plan_z.log)"
grep -q "no predators" plan_z.log || fail "plan.py did not warn about the extinct donor"
$RUN --plan plan_z.jsonl --root r10 --binary "$BIN" $GUARD > r10.log 2>&1; rc=$?
[ "$rc" = 1 ] && grep -q "FAILED .*(exit 9).*biological" r10/runner.log || fail "an extinct donor did not fail as biological (exit $rc)"
echo "redqueen_tooling: ok ($NW workers)"
