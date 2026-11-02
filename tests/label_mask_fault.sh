#!/bin/bash
# label_mask_fault.sh — planted faults for ocean_tests "label_mask" (the
# dead-sensor skip, turbo-speed-1, under own-frame labels: OceanConfig::
# labelFrame 1, the ALIFE 2027 A1 arm).
#
# Under labelFrame 1 each projected input reads BOTH world components of its
# vector. Each fault below makes a COPY of the engine (the tree is not touched)
# compute one such component only when its own world-axis input is read — the
# wrongly-masked component the skip must never produce:
#   offset_y   AVG_NEIGHBOR_DX (right) drops avgDy unless AVG_NEIGHBOR_DY is read
#   heading_x  AVG_NEIGHBOR_HEADING_Y (ahead) drops avgHx unless HEADING_X is read
#   food_x     NEAREST_FOOD_DY (ahead) drops foodDx unless NEAREST_FOOD_DX is read
# label_mask must FAIL on every fault and pass on the untouched copy. A fault
# whose anchor is not found exactly once stops the script (exit 2), so a
# renamed line cannot turn into a silent pass.
#
# Usage: bash tests/label_mask_fault.sh   (from anywhere; native g++, four builds)
# Env: CXX (default g++); EYE=1 for the eye build; OPT (default -O2).
set -u
cd "$(dirname "$0")/.." || exit 2
CXX=${CXX:-g++}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tests" "$TMP/wasm"
cp -r src tools "$TMP"/
cp tests/*.cpp tests/*.hpp "$TMP/tests/"
cp wasm/*.cpp "$TMP/wasm/" 2>/dev/null
cp wasm/*.hpp "$TMP/wasm/" 2>/dev/null
FLAGS="${OPT:--O2} -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I $TMP/src"
[ -n "${EYE:-}" ] && FLAGS="$FLAGS -DEVO_OCEAN_EYE"
ENGINE="$TMP/src/ocean/ocean_world.hpp"
cp "$ENGINE" "$TMP/ocean_world.orig"

plant () {  # plant OLD NEW: the pristine engine with OLD (found exactly once) replaced by NEW
    cp "$TMP/ocean_world.orig" "$ENGINE"
    python3 - "$ENGINE" "$1" "$2" <<'PY'
import sys
path, old, new = sys.argv[1:4]
s = open(path).read()
n = s.count(old)
if n != 1:
    sys.exit("anchor found %d times (want 1): %s" % (n, old))
open(path, "w").write(s.replace(old, new))
PY
}

FAILED=0
check () {  # check NAME WANT(pass|fail)
    if ! $CXX $FLAGS "$TMP/tests/ocean_tests.cpp" -o "$TMP/t_$1" 2> "$TMP/build_$1.log"; then
        echo "BUILD FAILED: $1"; cat "$TMP/build_$1.log"; exit 2
    fi
    local out rc
    out=$("$TMP/t_$1" --only label_mask 2>&1); rc=$?
    local line; line=$(printf '%s\n' "$out" | grep -E '^(ok|FAIL) +label_mask' | head -1)
    if [ "$2" = fail ]; then
        if [ $rc -ne 0 ] && [[ $line == FAIL* ]]; then echo "fault $1: label_mask FAILS, as it must: ${line#FAIL }"
        else echo "fault $1: label_mask did NOT fail (rc $rc): $line"; FAILED=1; fi
    else
        if [ $rc -eq 0 ] && [[ $line == ok* ]]; then echo "untouched copy: label_mask passes ($line)"
        else echo "untouched copy: label_mask FAILED (rc $rc): $line"; FAILED=1; fi
    fi
}

echo "== label_mask planted faults ($CXX, ${EYE:+eye }build)"
plant 'sensors[AVG_NEIGHBOR_DX] = evomath::tanhf((avgDx * rht.x + avgDy * rht.y) / R);' \
      'sensors[AVG_NEIGHBOR_DX] = evomath::tanhf((avgDx * rht.x + ((need & senseBit(AVG_NEIGHBOR_DY)) ? avgDy : 0.0f) * rht.y) / R);' || exit 2
check offset_y fail
plant 'sensors[AVG_NEIGHBOR_HEADING_Y] = avgHx * fwd.x + avgHy * fwd.y;' \
      'sensors[AVG_NEIGHBOR_HEADING_Y] = ((need & senseBit(AVG_NEIGHBOR_HEADING_X)) ? avgHx : 0.0f) * fwd.x + avgHy * fwd.y;' || exit 2
check heading_x fail
plant 'sensors[NEAREST_FOOD_DY] = foodDx * fwd.x + foodDy * fwd.y;' \
      'sensors[NEAREST_FOOD_DY] = ((need & senseBit(NEAREST_FOOD_DX)) ? foodDx : 0.0f) * fwd.x + foodDy * fwd.y;' || exit 2
check food_x fail
cp "$TMP/ocean_world.orig" "$ENGINE"
check untouched pass
if [ $FAILED -eq 0 ]; then echo "== LABEL_MASK FAULTS: every planted fault caught; the untouched engine passes"; else echo "== LABEL_MASK FAULTS: FAILED"; fi
exit $FAILED
