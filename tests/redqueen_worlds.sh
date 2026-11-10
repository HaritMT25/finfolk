#!/usr/bin/env bash
# redqueen_worlds.sh — tools/redqueen/worlds.py end to end against the real engine (serial build),
# on tiny worlds (200 prey, 24,000 steps, a checkpoint every 4,000), plus its unit tests.
#
#   tests/redqueen_worlds.sh PATH/TO/evo_boids WORKDIR        (env: PYTHON, default python3)
#
#   1. register: deterministic bytes; one block of C, A and B; both floors passed as explicit
#      zeros; refusals (placeholder, a floor, an omitted floor); an existing registry is never
#      replaced by other bytes;
#   2. f1 + launch: every history completes, every checkpoint accepted with all its logs; F1 and
#      six checkpoints per world archived read-only, the archives finalized (FINALIZED, 0555);
#      the pinned engine probed serial; F1 carries the registered configuration (floors 0);
#      verify-f1 (bound to the engine's hash): F1 resumed to the first checkpoint is identical;
#   3. a SIGKILLed C engine: the supervisor verifies F1, resumes the last accepted checkpoint;
#      every archived checkpoint equals the uninterrupted root's, and the stitched logs equal the
#      uninterrupted run's (lineage log, predators.csv, pwiring, prey wiring; the main CSV but its
#      timing and repro_components columns);
#   4. lineage-log loss (a host crash's lost writes, simulated by truncating the lineage log after
#      a SIGKILLed supervisor): the resume goes back to the last checkpoint the surviving log
#      covers, and the stitched lineage log is still the uninterrupted one;
#   5. a main CSV that loses its tail although the engine exits 0 (a transient ENOSPC, simulated by
#      a wrapper): the world is not done; it resumes from the last frame every log reaches;
#   6. a SIGKILLed supervisor, a torn checkpoint and a damaged archive copy: no engine outlives it;
#      the restart quarantines the torn file, repairs the archive copy and finishes with the same
#      archive;
#   7. extinction: recorded in availability.jsonl, the world ends "extinct" (archive finalized);
#      after a restart that lost the ledger and the end, the zero is recovered and the world ends
#      again without a new segment;
#   8. a world found at its final accepted frame, and an interrupted finalization: the restart
#      finalizes both without a new segment; a changed registry is refused by the bound root;
#      STOP stops admission (exit 75); design-block lists the archive;
#   9. two fresh roots claiming one archive root at once: one wins, the other writes nothing;
#  10. an extinct world whose accepted wiring is damaged between acceptances (its zero evidence
#      intact, stop): reopened, replayed through the zero, extinct again, its archive untouched;
#  11. the burn-in rule: an A world extinct before the burn-in frame restarts from its slot's
#      reserved seeds (each attempt's F1 by the supervisor) until --max-restarts, then ends extinct.
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
noengines() {   # wait until no engine of root $1 runs
    for _ in $(seq 1 100); do [ -z "$(pgrep -f "$W/$1/bin/evo_boids")" ] && return 0; sleep 0.1; done
    pkill -KILL -f "$W/$1/bin/evo_boids"; fail "an engine of $1 outlived its supervisor"
}

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
REG="register --arena arena.json --namespace rq-test-worlds --blocks 1 --per-block C=1,A=1,B=1
     --total-steps 24000 --checkpoint-every 4000 --log-every 100 --burn-in 0"

# 1. the registry
$WS $REG --out reg1.json 2> /dev/null || fail "register"
$WS $REG --out reg2.json 2> /dev/null || fail "register (again)"
cmp -s reg1.json reg2.json || fail "register is not deterministic"
$WS $REG --out reg1.json 2> /dev/null || fail "register (the same bytes again)"
echo 4242 > avoid.txt
$WS $REG --avoid avoid.txt --out reg1.json 2> ow.log && fail "a registry was replaced by other bytes"
grep -q "never replaced" ow.log || fail "the overwrite refusal does not say why: $(cat ow.log)"
cmp -s reg1.json reg2.json || fail "the refused registration changed reg1.json"
sed 's/"predator-max-age": 40, "predator-meal": 20, "predator-cooldown": 1.5},$/"predator-max-age": "SELECTED_AGE", "predator-meal": 20, "predator-cooldown": 1.5},/' arena.json \
    | sed 's/"status": "selected"/"status": "placeholder"/' > arena_ph.json
$WS register --arena arena_ph.json --namespace x --out x.json 2> ph.log && fail "a placeholder arena was registered"
grep -q "placeholder" ph.log || fail "the placeholder refusal does not say why: $(cat ph.log)"
sed 's/"min-pop": 0,/"min-pop": 20,/' arena.json > arena_floor.json
$WS register --arena arena_floor.json --namespace x --out x.json 2> fl.log && fail "a prey floor was registered"
grep -q "prey floor" fl.log || fail "the floor refusal does not say why: $(cat fl.log)"
sed 's/"min-pop": 0, //' arena.json > arena_nofloor.json
$WS register --arena arena_nofloor.json --namespace x --out x.json 2> nf.log && fail "an omitted prey floor was registered"
grep -q "min-pop must be given explicitly" nf.log || fail "the omitted-floor refusal does not say why: $(cat nf.log)"
$PY - <<'PY' || fail "the registry's command lines"
import json
for w in json.load(open("reg1.json"))["worlds"]:
    a = w["config_args"]
    assert a[a.index("--min-pop") + 1] == "0" and a[a.index("--predator-min-pop") + 1] == "0", a
PY
mkroot() { mkdir -p "$1/config"; cp reg1.json "$1/config/worlds.json"; }
CW=$($PY -c 'import json; print([w["id"] for w in json.load(open("reg1.json"))["worlds"] if w["treatment"] == "C"][0])')

# 2. f1 + launch, uninterrupted
mkroot R1
$WS f1 --root R1 --binary "$BIN" --archive-root "$W/arch1" > r1f1.log 2>&1 || fail "f1: $(tail -3 r1f1.log)"
$WS launch --root R1 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r1.log 2>&1 \
    || fail "launch: $(tail -5 r1.log)"
$WS verify-f1 --root R1 > r1v.log 2>&1 || fail "verify-f1: $(tail -3 r1v.log)"
for w in $($PY -c 'import json; print(" ".join(w["id"] for w in json.load(open("reg1.json"))["worlds"]))'); do
    $WS stitch --root R1 --world "$w" > /dev/null || fail "stitch R1 $w"
done
$PY - "$T" <<'PY' || fail "the uninterrupted root"
import json, os, stat, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib, ckpt
reg = json.load(open("R1/config/worlds.json"))
pinned = open("R1/bin/evo_boids.sha256").read().split()[0]
assert json.load(open("R1/bin/identity.json"))["determinism"] == worlds.SERIAL
assert json.load(open("R1/study.json"))["archive_root"].endswith("/arch1")
for w in reg["worlds"]:
    st = worlds.read_state("R1", w["id"])
    assert st["status"] == "done" and len(st["segments"]) == 1, (w["id"], st["status"])
    recs = worlds.archive_records("R1", w["id"])
    assert sorted(r["frame"] for r in recs.values()) == [1, 4000, 8000, 12000, 16000, 20000, 24000], recs.keys()
    assert [r["frame"] for r in worlds.accept_records("R1", w["id"])] == [4000, 8000, 12000, 16000, 20000, 24000]
    for r in recs.values():
        assert rqlib.sha256_file(r["path"]) == r["sha256"] and os.stat(r["path"]).st_mode & 0o777 == 0o444
    assert recs["F1"]["binary_sha256"] == pinned
    cfg = ckpt.load(recs["F1"]["path"])["config"]
    assert cfg["minPopulation"] == 0 and cfg["predatorMinPopulation"] == 0, cfg
    ad = os.path.dirname(recs["F1"]["path"])
    assert os.path.isfile(os.path.join(ad, "FINALIZED")) and os.stat(ad).st_mode & 0o777 == 0o555
    v = json.load(open(f"R1/worlds/{w['id']}/f1_verify.json"))
    assert v["identical"] is True and v["binary_sha256"] == pinned
    man = json.load(open(f"R1/worlds/{w['id']}/stitched/manifest.json"))
    assert man["endpoint"] == 24000 and man["complete"] is True, man
    if w["treatment"] == "C":
        ev = [l.split(",")[1] for l in open(f"R1/worlds/{w['id']}/seg000/run.predlog.csv").read().splitlines()[1:]]
        assert ev.count("B") > 20 and ev.count("A") > 10, "the tiny C world's predators should bud and age"
assert json.load(open("arch1/OWNER.json"))["study_id"] == json.load(open("R1/study.json"))["study_id"]
PY
# (N1) a new study root naming R1's (finalized) archive root is refused; nothing in it changes
mkroot R7
snap() { find arch1 -type f -exec sha256sum {} + | sort; find arch1 -type d -exec stat -c '%a %n' {} + | sort; }
snap > arch1.before
$WS f1 --root R7 --binary "$BIN" --archive-root "$W/arch1" > r7.log 2>&1 && fail "a second study published into R1's archive"
grep -q "belongs to another study" r7.log || fail "the ownership refusal does not say why: $(cat r7.log)"
snap > arch1.after
cmp -s arch1.before arch1.after || fail "the refused study changed R1's archive"

# 3. a SIGKILLed C engine: F1 verified, resume, identical archive, stitched logs = the uninterrupted logs
mkroot R2
$WS f1 --root R2 --binary "$BIN" --archive-root "$W/arch2" > r2f1.log 2>&1 || fail "f1 R2"
$WS launch --root R2 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r2.log 2>&1 &
sp=$!
# (late enough that the unflushed predator wiring log has reached disk past a checkpoint, so the
#  resume starts from a checkpoint, not from the founder seed)
for _ in $(seq 1 3000); do [ -f "R2/worlds/$CW/ckpt/end.16000.json" ] && break; sleep 0.01; done
pkill -KILL -f "$W/R2/bin/evo_boids.*--predator-log" || { kill $sp; fail "no C engine to kill (it finished first?)"; }
wait $sp; rc=$?
[ "$rc" = 0 ] || fail "the supervisor did not finish after the kill (exit $rc): $(tail -5 r2.log)"
$WS stitch --root R2 --world "$CW" > /dev/null || fail "stitch"
cat > cmp_stitch.py <<'PY'
import csv, json, sys; sys.path.insert(0, sys.argv[1]); import worlds
root, cw = sys.argv[2], sys.argv[3]
for w in json.load(open("R1/config/worlds.json"))["worlds"]:
    a = {k: r["sha256"] for k, r in worlds.archive_records("R1", w["id"]).items() if k != "F1"}
    b = {k: r["sha256"] for k, r in worlds.archive_records(root, w["id"]).items() if k != "F1"}
    assert a == b, (w["id"], sorted(set(a) ^ set(b)))
st = worlds.read_state(root, cw)
assert st["status"] == "done", st
for f in ("run.predlog.csv", "run.predators.csv", "run.pwiring.csv", "run.wiring.csv"):
    x, y = open(f"R1/worlds/{cw}/seg000/{f}").read(), open(f"{root}/worlds/{cw}/stitched/{f}").read()
    assert x == y, f
def rows(p):
    with open(p) as fh:
        return [{k: v for k, v in r.items() if k not in worlds.NON_CONTINUABLE} for r in csv.DictReader(fh)]
assert rows(f"R1/worlds/{cw}/seg000/run.csv") == rows(f"{root}/worlds/{cw}/stitched/run.csv")
print("segments", [(s["name"], s["start_frame"]) for s in st["segments"]])
PY
$PY cmp_stitch.py "$T" R2 "$CW" || fail "the interrupted history differs from the uninterrupted one"
$PY - "$T" "$CW" <<'PY' || fail "the resume after the engine kill"
import json, sys; sys.path.insert(0, sys.argv[1]); import worlds
st = worlds.read_state("R2", sys.argv[2])
res = [s for s in st["segments"][1:] if s["start_frame"] > 0]
assert res, "the resume did not start from a checkpoint"
assert res[0]["resumed_accept"]["frame"] == res[0]["start_frame"], res[0]
v = json.load(open(f"R2/worlds/{sys.argv[2]}/f1_verify.json"))
assert v["identical"] is True and v["binary_sha256"] == open("R2/bin/evo_boids.sha256").read().split()[0]
PY
grep -q "verifying F1 with the pinned engine" r2.log || fail "the supervisor did not verify F1 before resuming"

# 4. lineage-log loss after a SIGKILLed supervisor: back to the last checkpoint the log covers
mkroot R5
$WS f1 --root R5 --binary "$BIN" --archive-root "$W/arch5" > r5f1.log 2>&1 || fail "f1 R5"
$WS launch --root R5 --binary "$BIN" --workers 3 --on-extinction continue --prune-local $GUARD > r5a.log 2>&1 &
sp=$!
for _ in $(seq 1 3000); do grep -qs '"label":"end.16000"' "R5/worlds/$CW/accept.jsonl" && break; sleep 0.01; done
kill -KILL $sp; wait $sp 2> /dev/null
noengines R5
$PY - "$T" "$CW" <<'PY' || fail "setting up the lineage-log loss"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
cw = sys.argv[2]
recs = [r for r in worlds.accept_records("R5", cw) if r["segment"] == "seg000"]
assert recs and recs[-1]["frame"] >= 16000, [r["frame"] for r in recs]
# lose the lineage log from the last accepted part that has rows: that part and every later record fail
k = max(i for i, r in enumerate(recs) if r["logs"]["run.predlog.csv"]["bytes"] > r["logs"]["run.predlog.csv"]["from"])
cut = recs[k]["logs"]["run.predlog.csv"]["from"] + 1
with open(f"R5/worlds/{cw}/seg000/run.predlog.csv", "r+b") as f:
    f.truncate(cut)
open("r5_expect", "w").write(str(recs[k - 1]["frame"] if k else 0))
PY
$WS launch --root R5 --binary "$BIN" --workers 3 --on-extinction continue --prune-local $GUARD > r5b.log 2>&1 \
    || fail "the restart after the lineage-log loss (--prune-local, N2): $(tail -5 r5b.log)"
$WS stitch --root R5 --world "$CW" > /dev/null || fail "stitch R5"
$PY cmp_stitch.py "$T" R5 "$CW" || fail "R5 differs from the uninterrupted history"
$PY - "$T" "$CW" <<'PY' || fail "the resume after the lineage-log loss"
import sys; sys.path.insert(0, sys.argv[1]); import worlds
st = worlds.read_state("R5", sys.argv[2])
assert st["segments"][1]["start_frame"] == int(open("r5_expect").read()), (st["segments"], open("r5_expect").read())
PY

# 5. the main CSV loses its tail although the engine exits 0: not done; resumed from 16000
cat > wrap.sh <<'SH'
#!/bin/bash
"@BIN@" "$@"; rc=$?
csv=""; prev=""
for a in "$@"; do [ "$prev" = "--csv" ] && csv=$a; prev=$a; done
if [ $rc = 0 ] && [ -f "@W@/trunc_once" ] && [ "${csv#seg}" != "$csv" ]; then
    case " $* " in *" --predator-log "*)
        rm -f "@W@/trunc_once"
        awk -F, 'NR == 1 || $1 <= 18000' "$csv" > "$csv.tmp" && mv "$csv.tmp" "$csv" ;;
    esac
fi
exit $rc
SH
sed -i "s|@BIN@|$BIN|; s|@W@|$W|g" wrap.sh
chmod +x wrap.sh
mkroot R6; touch trunc_once
$WS f1 --root R6 --binary "$W/wrap.sh" --archive-root "$W/arch6" > r6f1.log 2>&1 || fail "f1 R6"
$WS launch --root R6 --binary "$W/wrap.sh" --workers 3 --on-extinction continue $GUARD > r6.log 2>&1 \
    || fail "launch R6: $(tail -5 r6.log)"
[ -f trunc_once ] && fail "the wrapper never truncated the main CSV"
$WS stitch --root R6 --world "$CW" > /dev/null || fail "stitch R6"
$PY cmp_stitch.py "$T" R6 "$CW" || fail "R6 differs from the uninterrupted history"
$PY - "$T" "$CW" <<'PY' || fail "the short main CSV"
import sys; sys.path.insert(0, sys.argv[1]); import worlds
st = worlds.read_state("R6", sys.argv[2])
assert [s["start_frame"] for s in st["segments"]] == [0, 16000], st["segments"]
assert st["segments"][0]["rc"] == 0, st["segments"][0]
PY

# 6. a SIGKILLed supervisor, a torn checkpoint, a damaged archive copy
mkroot R3
$WS f1 --root R3 --binary "$BIN" --archive-root "$W/arch3" > r3f1.log 2>&1 || fail "f1 R3"
$WS launch --root R3 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r3a.log 2>&1 &
sp=$!
for _ in $(seq 1 3000); do grep -qs '"label":"end.8000"' "R3/worlds/$CW/accept.jsonl" && break; sleep 0.01; done
kill -KILL $sp; wait $sp 2> /dev/null
noengines R3
$PY - "$T" "$CW" <<'PY' || fail "setting up the torn checkpoint and the damaged archive copy"
import os, sys; sys.path.insert(0, sys.argv[1]); import worlds
cw = sys.argv[2]
loc = worlds.local_ckpts("R3", cw)
f = max(loc) + 4000
assert f <= 20000, sorted(loc)
data = open(loc[max(loc)], "rb").read()
open(f"R3/worlds/{cw}/ckpt/end.{f}.json", "wb").write(data[: len(data) // 2])   # killed mid-write
open("r3_torn", "w").write(str(f))
rec = worlds.archive_records("R3", cw)["end.4000"]
assert 4000 in loc
os.chmod(rec["path"], 0o644)
open(rec["path"], "wb").write(b"lost")                                            # a damaged archive copy
PY
$WS launch --root R3 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r3b.log 2>&1 \
    || fail "the restart: $(tail -5 r3b.log)"
$PY - "$T" "$CW" <<'PY' || fail "the restarted root"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib
cw = sys.argv[2]
for w in json.load(open("R1/config/worlds.json"))["worlds"]:
    a = {k: r["sha256"] for k, r in worlds.archive_records("R1", w["id"]).items() if k != "F1"}
    b = {k: r["sha256"] for k, r in worlds.archive_records("R3", w["id"]).items() if k != "F1"}
    assert a == b and worlds.read_state("R3", w["id"])["status"] == "done", w["id"]
    for r in worlds.archive_records("R3", w["id"]).values():
        assert rqlib.sha256_file(r["path"]) == r["sha256"] and os.stat(r["path"]).st_mode & 0o777 == 0o444, r
q = worlds.read_jsonl(f"R3/worlds/{cw}/quarantine.jsonl")
assert int(open("r3_torn").read()) in [r["frame"] for r in q], q
PY
grep -q "QUARANTINED" r3b.log || fail "the torn checkpoint was not quarantined"
grep -q "REPAIRED the archived end.4000.json" r3b.log || fail "the damaged archive copy was not repaired"

# 7. extinction; a restart that lost the ledger and the end recovers both without a new segment
cat > arena_x.json <<'JSON'
{"schema": "finfolk.redqueen.arena/1", "status": "selected",
 "common": {"population": 8, "min-pop": 0, "predator-min-pop": 0, "max-pop": 8, "target-food": 20,
            "food-spawn": 3, "food-amp": 2, "food-patches": 0, "current": 0, "move-cost": 0, "gene-cost": 0},
 "treatments": {"A": {"predators": 40, "predator-capture-radius": 60}}}
JSON
$WS register --arena arena_x.json --namespace rq-test-x --blocks 1 --per-block A=1 --total-steps 24000 \
    --checkpoint-every 4000 --log-every 100 --burn-in 0 --out RX/config/worlds.json 2> /dev/null || fail "register (extinction)"
$WS f1 --root RX --binary "$BIN" > rxf1.log 2>&1 || fail "f1 RX"
$WS launch --root RX --binary "$BIN" --workers 1 $GUARD > rx.log 2>&1 || fail "launch (extinction): $(tail -3 rx.log)"
$PY - "$T" <<'PY' || fail "the extinction was not recorded"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
led = [json.loads(l) for l in open("RX/availability.jsonl")]
assert len(led) == 1 and led[0]["guild"] == "prey" and led[0]["first_zero_frame"] > 0, led
wid = led[0]["world"]
st = worlds.read_state("RX", wid)
assert st["status"] == "extinct", st["status"]
ad = os.path.join("RX", "archive", "worlds", wid)
assert os.path.isfile(os.path.join(ad, "FINALIZED"))
assert worlds.zero_supported("RX", led[0]), led[0]          # bound to its CSV prefix (R3)
open("rx_zero", "w").write(f"{wid} {led[0]['first_zero_frame']} {len(st['segments'])}")
os.remove("RX/availability.jsonl")                           # (R3) the ledger lost, the world still extinct
PY
$WS launch --root RX --binary "$BIN" --workers 1 $GUARD > rx1.log 2>&1 || fail "relaunch (terminal, no ledger): $(tail -3 rx1.log)"
$PY - "$T" <<'PY' || fail "the terminal world's recovered zero"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
wid, z, nseg = open("rx_zero").read().split()
led = [json.loads(l) for l in open("RX/availability.jsonl")]
assert len(led) == 1 and led[0]["first_zero_frame"] == int(z) and led[0]["recovered"] is True, led
st = worlds.read_state("RX", wid)
assert st["status"] == "extinct" and len(st["segments"]) == int(nseg), st
# the previous supervisor "never saw" the zero and died before ending the world
os.remove("RX/availability.jsonl")
st["status"] = "interrupted"
worlds.write_state("RX", wid, st)
ad = os.path.join("RX", "archive", "worlds", wid)
os.chmod(ad, 0o755)
os.remove(os.path.join(ad, "FINALIZED"))
PY
$WS launch --root RX --binary "$BIN" --workers 1 $GUARD > rx2.log 2>&1 || fail "relaunch (extinction): $(tail -3 rx2.log)"
$PY - "$T" <<'PY' || fail "the recovered extinction"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
wid, z, nseg = open("rx_zero").read().split()
led = [json.loads(l) for l in open("RX/availability.jsonl")]
assert len(led) == 1 and led[0]["first_zero_frame"] == int(z) and led[0]["recovered"] is True, led
st = worlds.read_state("RX", wid)
assert st["status"] == "extinct" and len(st["segments"]) == int(nseg), st
assert os.path.isfile(os.path.join("RX", "archive", "worlds", wid, "FINALIZED"))
PY

# 8. at the final frame / an interrupted finalization; a changed registry; STOP; design-block
$PY - "$T" <<'PY' || fail "setting up the interrupted ends"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
ws = {w["treatment"]: w["id"] for w in json.load(open("R1/config/worlds.json"))["worlds"]}
for t in ("A", "B"):
    ad = os.path.join("arch1", "worlds", ws[t])
    os.chmod(ad, 0o755)
    os.remove(os.path.join(ad, "FINALIZED"))
st = worlds.read_state("R1", ws["A"])
st["status"] = "interrupted"            # died after the engine's last checkpoint, before marking it done
worlds.write_state("R1", ws["A"], st)
PY
$WS launch --root R1 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r1c.log 2>&1 || fail "the reconciling launch: $(tail -3 r1c.log)"
grep -q "already at its end (done" r1c.log || fail "the world at its final frame was not recognized"
grep -q " seg001 " r1c.log && fail "a world at its final frame got another segment"
$PY - "$T" <<'PY' || fail "the reconciled finalization"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
for w in json.load(open("R1/config/worlds.json"))["worlds"]:
    st = worlds.read_state("R1", w["id"])
    ad = os.path.join("arch1", "worlds", w["id"])
    assert st["status"] == "done" and len(st["segments"]) == 1, (w["id"], st)
    assert os.path.isfile(os.path.join(ad, "FINALIZED")) and os.stat(ad).st_mode & 0o777 == 0o555, w["id"]
PY
# (R1) a done C world whose accepted lineage log loses its tail: reopened, replayed, done again
cp "R1/worlds/$CW/seg000/run.predlog.csv" predlog.orig
cp "R1/worlds/$CW/seg000/run.pwiring.csv" pwiring.orig
$PY - "$CW" <<'PY' || fail "setting up the damaged done world"
import os, sys
p = f"R1/worlds/{sys.argv[1]}/seg000/run.predlog.csv"
with open(p, "r+b") as f:
    f.truncate(os.path.getsize(p) - 300)
PY
$WS launch --root R1 --binary "$BIN" --workers 3 --on-extinction continue $GUARD > r1e.log 2>&1 || fail "the reopening launch: $(tail -3 r1e.log)"
grep -q "$CW: REOPENED (done" r1e.log || fail "the damaged done world was not reopened: $(tail -3 r1e.log)"
$WS stitch --root R1 --world "$CW" > /dev/null || fail "stitch after the reopening"
cmp -s predlog.orig "R1/worlds/$CW/stitched/run.predlog.csv" || fail "the replayed lineage log differs"
cmp -s pwiring.orig "R1/worlds/$CW/stitched/run.pwiring.csv" || fail "the replayed pwiring differs"
$PY - "$T" "$CW" <<'PY' || fail "the reopened world"
import sys; sys.path.insert(0, sys.argv[1]); import worlds
st = worlds.read_state("R1", sys.argv[2])
assert st["status"] == "done" and len(st["segments"]) == 2 and st["segments"][1]["start_frame"] > 0, st
PY
$WS register --arena arena.json --namespace rq-test-other --blocks 1 --per-block C=1,A=1,B=1 --burn-in 0 \
    --total-steps 24000 --checkpoint-every 4000 --log-every 100 --out reg_other.json 2> /dev/null || fail "register (other)"
cp R1/config/worlds.json r1_registry.bak
chmod u+w R1/config/worlds.json; cp reg_other.json R1/config/worlds.json
$WS launch --root R1 --binary "$BIN" $GUARD > r1d.log 2>&1 && fail "a changed registry was launched in a bound root"
grep -q "is bound to the registry" r1d.log || fail "the binding refusal does not say why: $(cat r1d.log)"
cp r1_registry.bak R1/config/worlds.json
mkroot R4
$WS f1 --root R4 --binary "$BIN" > r4f1.log 2>&1 || fail "f1 R4"
touch R4/STOP
$WS launch --root R4 --binary "$BIN" $GUARD > r4.log 2>&1; rc=$?
[ "$rc" = 75 ] || fail "STOP: exit $rc, expected 75: $(tail -3 r4.log)"
ls R4/worlds/*/seg000 > /dev/null 2>&1 && fail "STOP admitted a segment"
$WS design-block --root R1 --out block.json || fail "design-block"
$PY - <<'PY' || fail "design-block contents"
import json
b = json.load(open("block.json"))
assert b["times"] == {"F1": 1, "f4000": 4000, "f8000": 8000, "f12000": 12000, "f16000": 16000, "f20000": 20000, "f24000": 24000}
w = next(iter(b["worlds"].values()))
assert w["pattern"].endswith("end.{frame}.json") and w["paths"]["F1"].endswith("F1.json")
# (Codex #77 r1 P1-1) the real engine's archive: every object on the line of descent, re-hashed; the evidence
# through the final frame; the attempt's identity and an explicit burn-in disposition
for w in b["worlds"].values():
    assert w["archived"] == sorted(b["times"].values()), w["archived"]
    assert {e["status"] for e in w["archive"].values()} == {"verified"}, w["archive"]
    assert (w["evidence"]["frontier"], w["evidence"]["stop"], w["attempt"], w["attempt_uuid"]) == \
        (24000, None, 0, w["uuid"]), w["evidence"]
    assert w["burn_in"]["disposition"] in ("no_rule", "established", "unresolved"), w["burn_in"]
assert b["evidence"]["schema"] == "finfolk.redqueen.blockevidence/1"
PY

# 9. (round 3) two fresh study roots claim one archive root at once: one wins, the other is refused
#    with nothing written (the archive lock and the hard-linked OWNER.json)
mkroot R8; mkroot R9
$WS f1 --root R8 --binary "$BIN" --archive-root "$W/arch8" > r8.log 2>&1 & p8=$!
$WS f1 --root R9 --binary "$BIN" --archive-root "$W/arch8" > r9.log 2>&1 & p9=$!
wait $p8; rc8=$?; wait $p9; rc9=$?
$PY - "$T" $rc8 $rc9 <<'PY' || fail "the concurrent archive claims: $(tail -2 r8.log r9.log)"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds
rc = {"R8": int(sys.argv[2]), "R9": int(sys.argv[3])}
won = [r for r, c in rc.items() if c == 0]
assert len(won) == 1, rc
lost = ({"R8", "R9"} - set(won)).pop()
assert not any(os.path.exists(f"{lost}/{x}") for x in ("study.json", "worlds", "bin")), os.listdir(lost)
assert json.load(open("arch8/OWNER.json"))["study_id"] == json.load(open(f"{won[0]}/study.json"))["study_id"]
assert not os.path.exists("arch8/OWNER.json.tmp")
print("claims", rc)
PY

# 10. (round 3) an extinct world whose accepted wiring bytes are damaged between two acceptances, its
#     zero evidence intact, under --on-extinction stop: reopened, the extinction shortcut refused, a
#     replay from the last verified record through the zero repairs the logs; extinct again, its
#     finalized archive untouched
cat > arena_y.json <<'JSON'
{"schema": "finfolk.redqueen.arena/1", "status": "selected",
 "common": {"population": 8, "min-pop": 0, "predator-min-pop": 0, "max-pop": 8, "target-food": 20,
            "food-spawn": 3, "food-amp": 2, "food-patches": 0, "current": 0, "move-cost": 0, "gene-cost": 0},
 "treatments": {"A": {"predators": 4, "predator-capture-radius": 60}}}
JSON
$WS register --arena arena_y.json --namespace rq-test-y --blocks 1 --per-block A=1 --total-steps 24000 \
    --checkpoint-every 400 --log-every 100 --burn-in 0 --out RY/config/worlds.json 2> /dev/null || fail "register (RY)"
$WS f1 --root RY --binary "$BIN" > ryf1.log 2>&1 || fail "f1 RY"
$WS launch --root RY --binary "$BIN" --workers 1 $GUARD > ry.log 2>&1 || fail "launch RY: $(tail -3 ry.log)"
$PY - "$T" <<'PY' || fail "setting up the damaged extinct world"
import json, os, shutil, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib
led = [json.loads(l) for l in open("RY/availability.jsonl")]
wid, fz = led[0]["world"], led[0]["first_zero_frame"]
st = worlds.read_state("RY", wid)
assert st["status"] == "extinct", st
recs = [r for r in worlds.accept_records("RY", wid) if r["frame"] <= fz]
assert len(recs) >= 2, (fz, [r["frame"] for r in recs])
p = f"RY/worlds/{wid}/seg000/run.wiring.csv"
shutil.copy(p, "ry_wiring.orig")
part = recs[1]["logs"]["run.wiring.csv"]                     # the second acceptance's part
raw = bytearray(open(p, "rb").read())
k = (part["from"] + part["bytes"]) // 2
raw[k] = ord("7") if raw[k] != ord("7") else ord("8")
open(p, "wb").write(bytes(raw))
arch = {r["label"]: rqlib.sha256_file(r["path"]) for r in worlds.archive_records("RY", wid).values()}
json.dump({"wid": wid, "fz": fz, "f0": recs[0]["frame"], "arch": arch}, open("ry_info.json", "w"))
PY
RYW=$($PY -c 'import json; print(json.load(open("ry_info.json"))["wid"])')
$WS launch --root RY --binary "$BIN" --workers 1 $GUARD > ry2.log 2>&1 || fail "the reopening launch (RY): $(tail -3 ry2.log)"
grep -q "$RYW: REOPENED (extinct" ry2.log || fail "the damaged extinct world was not reopened: $(tail -3 ry2.log)"
grep -q "replaying through the zero" ry2.log || fail "the extinction shortcut applied to unverified logs: $(tail -3 ry2.log)"
$WS stitch --root RY --world "$RYW" > /dev/null || fail "stitch RY"
$PY - "$T" <<'PY' || fail "the replayed extinct world"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib
info = json.load(open("ry_info.json"))
wid = info["wid"]
st = worlds.read_state("RY", wid)
assert st["status"] == "extinct" and len(st["segments"]) == 2 and st["segments"][1]["start_frame"] == info["f0"], st
good = worlds.verified_records("RY", wid, st, "A")
assert max(f for (s, f) in good if f <= info["fz"]) >= max(r["frame"] for r in worlds.accept_records("RY", wid)
                                                           if r["frame"] <= info["fz"] and r["segment"] == "seg000")
man = json.load(open(f"RY/worlds/{wid}/stitched/manifest.json"))
orig = open("ry_wiring.orig").read().splitlines()
got = open(f"RY/worlds/{wid}/stitched/run.wiring.csv").read().splitlines()
upto = min(man["endpoint"], int(orig[-1].split(",")[0]))
cut = lambda rows: [rows[0]] + [l for l in rows[1:] if int(l.split(",")[0]) <= upto]
assert upto >= info["fz"] - 400 and cut(got) == cut(orig), (upto, len(got), len(orig))
arch = {r["label"]: rqlib.sha256_file(r["path"]) for r in worlds.archive_records("RY", wid).values()}
assert arch == info["arch"], sorted(set(arch) ^ set(info["arch"]))
assert worlds.audit_archive("RY", wid, json.load(open("RY/study.json"))["archive_root"], "extinct")
PY
# 11. the burn-in rule (USER DECISIONS 2): an A world whose prey dies out before the burn-in frame restarts
#     from its slot's reserved seeds (the supervisor makes each attempt's F1), until --max-restarts; then
#     it ends extinct. The ledger, the moved attempts, three different F1s, the per-treatment rate.
$WS register --arena arena_x.json --namespace rq-test-z --blocks 1 --per-block A=1 --total-steps 24000 \
    --checkpoint-every 4000 --log-every 100 --burn-in 24000 --max-restarts 2 --out RZ/config/worlds.json 2> /dev/null \
    || fail "register (RZ)"
$WS f1 --root RZ --binary "$BIN" > rzf1.log 2>&1 || fail "f1 RZ"
$WS launch --root RZ --binary "$BIN" --workers 1 $GUARD > rz.log 2>&1 || fail "launch (burn-in): $(tail -3 rz.log)"
grep -q "BURN-IN" rz.log || fail "no burn-in restart was logged: $(tail -3 rz.log)"
$PY - "$T" <<'PY' || fail "the burn-in restarts"
import json, os, sys; sys.path.insert(0, sys.argv[1]); import worlds, rqlib
reg = json.load(open("RZ/config/worlds.json"))
w = reg["worlds"][0]
wid = w["id"]
seeds = next(x["seeds"] for x in reg["reserved"] if x["slot"] == w["seed_slot"])
led = worlds.restart_records("RZ")
assert [(r["attempt"], r["failed_seed"], r["seed"]) for r in led] == [(1, seeds[0], seeds[1]), (2, seeds[1], seeds[2])], led
assert all(r["zero_frame"] < 24000 for r in led), led
st = worlds.read_state("RZ", wid)
assert st["status"] == "extinct" and "restarts exhausted" in st["end_reason"], st
assert worlds.attempt_of("RZ", wid) == 2
ar = json.load(open("RZ/study.json"))["archive_root"]
f1s = [rqlib.sha256_file(os.path.join(ar, "restarts", f"{wid}.a{k}", "F1.json")) for k in (0, 1)]
f1s.append(rqlib.sha256_file(os.path.join(worlds.adir(ar, wid), "F1.json")))
assert len(set(f1s)) == 3, f1s                         # three seeds, three F1s
for k in (0, 1):
    assert os.path.isfile(os.path.join("RZ", "restarts", "worlds", f"{wid}.a{k}", "seg000", "run.csv")), k
assert os.path.isfile(os.path.join(worlds.adir(ar, wid), "FINALIZED"))
rep = worlds.burn_in_report("RZ", reg)["per_treatment"]["A"]
assert rep == {"worlds": 1, "restarts": 2, "attempts_started": 3, "early_failures": 3, "established": 0, "pending": 0,
               "unresolved": 0, "failed": 0, "failed_before_start": 0, "early_failure_rate": 1.0}, rep
for k in (0, 1):                                       # each retained attempt resolves to its own bytes
    assert worlds.audit_attempt("RZ", wid, k) == [], (k, worlds.audit_attempt("RZ", wid, k))
    assert all(r["path"].startswith(os.path.join(ar, "restarts", f"{wid}.a{k}")) for r in
               worlds.attempt_archive_records("RZ", wid, k).values())
av = worlds.read_jsonl("RZ/availability.jsonl")
assert sum(worlds.zero_supported("RZ", e) for e in av) == 1, av    # only the current attempt's zero counts
PY
$WS status --root RZ > rz_status.json 2> /dev/null || fail "status RZ"
$PY -c 'import json; s = json.load(open("rz_status.json")); assert s["burn_in"]["per_treatment"]["A"]["restarts"] == 2, s["burn_in"]' \
    || fail "status lacks the burn-in report"

echo "redqueen_worlds: ok"
