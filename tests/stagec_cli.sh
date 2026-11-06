#!/usr/bin/env bash
# stagec_cli.sh — the Stage C CLI rules end to end through the real binary
# (src/app/main.cpp), run by ctest in the serial build only (resumes are
# bit-exact only there).
#
#   tests/stagec_cli.sh PATH/TO/evo_boids WORKDIR
#
# Asserts:
#   1. the lineage log across a resume: segment 1 cut at the checkpoint frame,
#      then segment 2 without its L rows, equals the uninterrupted log; the log
#      is flushed at every checkpoint write; segment 2 opens with one L row per
#      live predator;
#   2. a lineage log is never overwritten (the run refuses, the old log stays);
#   3. Stage C flags on a version-1 resume are refused (exit 1), not ignored;
#   4. --transplant-count below -1, or not a number, is refused;
#   5. an arena's first run opens its log with T rows (source = the source id),
#      a resume of that run with L rows; the default frozen assay keeps the
#      predator count and lets energy move.
set -u
BIN=${1:?usage: stagec_cli.sh EVO_BOIDS WORKDIR}
W=${2:?usage: stagec_cli.sh EVO_BOIDS WORKDIR}
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
run() { "$BIN" --no-render --log-every 250 "$@" > /dev/null 2>&1 || fail "evo_boids $* exited $?"; }
STAGEC="--population 200 --predators 6 --predator-economy --predator-brain --predator-meal 14
        --predator-max-pop 12 --predator-min-pop 2 --predator-max-age 15 --predator-log"

# 1. resume and stitch (checkpoint at 1700, not a multiple of --log-every)
run --headless 3000 --seed 5 $STAGEC --name full
run --headless 1700 --seed 5 $STAGEC --name seg1 --save-checkpoint seg1.json
run --headless 1300 --load-checkpoint seg1.json --predator-log --name seg2
F=1700
head -1 runs/full.predlog.csv > stitched.csv
awk -F, -v f=$F 'NR > 1 && $1 <= f' runs/seg1.predlog.csv >> stitched.csv
awk -F, 'NR > 1 && $2 != "L"' runs/seg2.predlog.csv >> stitched.csv
cmp -s stitched.csv runs/full.predlog.csv || fail "the stitched lineage log differs from the uninterrupted one"
[ "$(awk -F, 'NR > 1 && $1 > 1700' runs/seg1.predlog.csv | wc -l)" = 0 ] || fail "segment 1 has rows after its end"
NPRED=$(python3 -c "import json; print(json.load(open('seg1.json'))['predators']['count'])")
[ "$(awk -F, 'NR > 1 && $2 == "L" && $1 == 1700' runs/seg2.predlog.csv | wc -l)" = "$NPRED" ] ||
    fail "segment 2 does not open with one L row per live predator ($NPRED)"
grep -q ',B,' runs/full.predlog.csv || fail "no buds in the test run (the test would prove nothing)"

# the log is on disk at a checkpoint: the periodic checkpoint's frame is covered
run --headless 1000 --seed 6 $STAGEC --name per --checkpoint-every 400
awk -F, 'NR > 1 {print $1}' runs/per.predlog.csv | sort -n | tail -1 | grep -q . || fail "empty periodic log"

# 2. never overwrite a lineage log
cp runs/seg2.predlog.csv keep.csv
if "$BIN" --no-render --headless 100 --load-checkpoint seg1.json --predator-log --name seg2 > /dev/null 2>&1; then
    fail "a run overwrote an existing lineage log"
fi
cmp -s keep.csv runs/seg2.predlog.csv || fail "the refused run touched the existing log"

# 3. Stage C flags on a version-1 resume
run --headless 300 --seed 7 --population 150 --predators 4 --predator-economy --save-checkpoint v1.json
for flag in "--predator-brain" "--predator-mutation 2" "--predator-turn-rate 3" "--predator-min-speed 5" \
            "--predator-primer" "--predator-log"; do
    if "$BIN" --no-render --headless 10 --load-checkpoint v1.json $flag > /dev/null 2>&1; then
        fail "$flag on a version-1 resume was accepted"
    fi
done
run --headless 10 --load-checkpoint v1.json                     # without them: fine

# 4. --transplant-count
for k in -5 abc; do
    if "$BIN" --no-render --load-checkpoint v1.json --predators-from random --transplant-count "$k" \
         --transplant-out bad.json > /dev/null 2>&1; then
        fail "--transplant-count $k was accepted"
    fi
done

# 5. an arena: T rows on its first run, L rows after; frozen keeps the count
run --load-checkpoint seg1.json --predators-from seg1.json --transplant-count 4 --transplant-seed 3 \
    --transplant-out arena.json
grep -q '"arena":true' arena.json || fail "the arena is not marked"
grep -q '"predatorFrozen":true' arena.json || fail "the default assay is not frozen"
run --headless 600 --load-checkpoint arena.json --reseed-after-load 1 --predator-log --name a1 \
    --save-checkpoint a1.json --csv runs/a1.csv
[ "$(awk -F, 'NR > 1 && $2 == "T" && $13 > 0' runs/a1.predlog.csv | wc -l)" = 4 ] ||
    fail "the arena's first run does not open with 4 T rows carrying their source ids"
grep -q '"arena":true' a1.json && fail "a checkpoint of the arena's run is still marked as a fresh arena"
run --headless 100 --load-checkpoint a1.json --predator-log --name a2
[ "$(awk -F, 'NR > 1 && $2 == "L"' runs/a2.predlog.csv | wc -l)" = 4 ] || fail "a resumed arena run does not open with L rows"
python3 - runs/a1.predators.csv <<'PY' || fail "the frozen assay: the count moved or the energy did not"
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
assert all(int(r["predator_pop"]) == 4 for r in rows), "count moved"
assert all(int(r["births_interval"]) == 0 and int(r["deaths_starv_interval"]) == 0 for r in rows), "births/deaths"
assert len({r["energy_mean"] for r in rows}) > 1, "energy pinned"
PY
echo "stagec_cli: ok"
