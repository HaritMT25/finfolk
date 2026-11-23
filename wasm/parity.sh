#!/bin/bash
# parity.sh — the native-vs-wasm bit-for-bit determinism suite.
#
# Builds wasm/parity_driver.cpp with the native toolchain and with Emscripten,
# runs both across a seed/config matrix, and byte-compares the final
# checkpoints. Any mismatch = the wasm build is NOT reproducing the native
# serial build and the port must not ship.
#
# Prereq: source ~/emsdk/emsdk_env.sh (or have em++ on PATH).
set -e
cd "$(dirname "$0")/.."

# Unique output dir per run (two worktrees can run parity at once); PARITY_DIR=/x reuses one.
if [ -n "${PARITY_DIR:-}" ]; then OUT=$PARITY_DIR; mkdir -p "$OUT"
else
    OUT=$(mktemp -d /tmp/evo_parity.XXXXXX)
    # removed when the run passes unless KEEP_OUT=1; kept when it fails (an explicit PARITY_DIR is never removed)
    if [ -z "${KEEP_OUT:-}" ]; then trap 'rc=$?; if [ $rc = 0 ]; then rm -rf "$OUT"; else echo "== kept $OUT (run did not pass)" >&2; fi' EXIT; fi
fi
echo "== outputs in $OUT"

echo "== building parity drivers"
# NATIVE_CXXFLAGS: extra flags for the NATIVE side only, to hold a throughput build (CMakeLists.txt,
# EVO_NATIVE_ARCH / EVO_LTO) to the same wasm, e.g. NATIVE_CXXFLAGS="-march=x86-64-v3 -mno-fma -flto=auto".
[ -n "${NATIVE_CXXFLAGS:-}" ] && echo "   native extra flags: $NATIVE_CXXFLAGS"
# shellcheck disable=SC2086  # NATIVE_CXXFLAGS is a list of flags: split on purpose
g++ -O3 -std=c++20 -ffp-contract=off ${NATIVE_CXXFLAGS:-} -I src wasm/parity_driver.cpp -o "$OUT/parity_native"
# -msimd128: the browser modules are built with it (wasm/wasm.cmake), so the
# parity check runs the same vectorised code.
em++ -O3 -std=c++20 -ffp-contract=off -msimd128 -I src wasm/parity_driver.cpp -o "$OUT/parity_wasm.js"

run_case () {  # run_case NAME SEED STEPS [extra args...]
    local name=$1 seed=$2 steps=$3; shift 3
    "$OUT/parity_native" "$seed" "$steps" "$@" > "$OUT/$name.native.json" 2> "$OUT/$name.native.log"
    node "$OUT/parity_wasm.js" "$seed" "$steps" "$@" > "$OUT/$name.wasm.json" 2> "$OUT/$name.wasm.log"
    if cmp -s "$OUT/$name.native.json" "$OUT/$name.wasm.json"; then
        echo "PASS  $name (seed $seed, $steps steps $*) $(grep -o '[0-9]* steps/s' "$OUT/$name.native.log" | head -1)"
    else
        echo "FAIL  $name (seed $seed, $steps steps $*)"
        echo "      first differing byte: $(cmp "$OUT/$name.native.json" "$OUT/$name.wasm.json" | head -1)"
        FAILED=1
    fi
}

FAILED=0
for s in 1 42 999 2718 31415; do
    run_case "default_s$s" "$s" 2000
done
run_case "rich_s42"    42    2000 --rich
run_case "rich_s31415" 31415 2000 --rich
run_case "tri_s42"     42    2000 --tri
run_case "toro_s42"    42    2000 --toroidal
run_case "toro_rich_s7" 7    2000 --rich --toroidal
# Genetic reproduction gate (isolation.hpp). Both thresholds are chosen to
# actually BITE — in-run neighbour pairs sit ~18-20 apart, so 18 blocks roughly
# half of attempted births and 14 blocks nearly all of them. A threshold above
# ~23 would leave the gate inert and prove nothing about the new code path.
run_case "iso_s42"     42    2000 --repro-max-distance 18
run_case "iso_rich_s999" 999 2000 --rich --repro-max-distance 14
# Gate mitigations (v0.24.0). Both are set INSIDE the measured collapse zone,
# where the hard gate at the same threshold is what they have to be compared
# against, and both are verified to fire rather than assumed to:
#   soft_s42   T=16 W=5  -> 55 insertions, 53 of them ABOVE the hard threshold
#              (measured at step 2000; the same seed and T with W=0 makes 1
#              insertion). The soft ramp is the only path in the tree that draws
#              on the gate — exactly one rng.unit per gate evaluation — so a
#              draw-count or draw-order difference between native and wasm shows
#              up here and nowhere else.
#   grace_s999 T=13 grace=60 -> 197 insertions, ALL 197 via the founder bypass
#              (the same seed and T without grace makes 0: 13 is below the
#              breeding floor, which is the point). It draws nothing; what it
#              proves is that both builds pick the same pairs to exempt.
run_case "soft_s42"    42    2000 --repro-max-distance 16 --repro-soft-width 5
run_case "grace_s999"  999   2000 --repro-max-distance 13 --repro-grace 60
# Tier-1 body model (body_model.hpp). This is a DYNAMICS knob that also ADDS TO
# THE RANDOM STREAM (two rng.range draws per insertion), so the on-path needs
# native==wasm proven independently of the off-path: a draw-count or draw-order
# difference between the two builds would show up here and nowhere else.
# body_s42 is the case with live morphology at the end (192 insertions, bodySize
# spread 0.86-1.14 at step 2000). body_rich_s7 is the harsher one: --rich at 2000
# steps collapses to the --min-pop floor under predation in EVERY seed (that is
# pre-existing, not a body-model effect — plain --rich s7/s42 do it too), so its
# survivors are reseeded founders back at 1.0. It still earns its place: 23
# insertions happen along the way (peak bodySize spread 0.92-1.09 around step
# 1000), and it exercises the body factors against predators/currents/patches
# and through the reseed path, where founders must draw NOTHING.
run_case "body_s42"      42   2000 --body-model
run_case "body_rich_s7"  7    2000 --rich --body-model
# body_tri_s42 exists because the other two body cases cannot see turnFactor at
# all. turnFactor is the ONLY dynamical consumer of bodyElong, it multiplies
# cfg.maxTurnRate, and cfg.maxTurnRate is read on the triangular-motion branch
# only — so with --tri off, bodyElong is decorative and a turn factor wired to
# the wrong parameter (or deleted outright) ships green through every other
# case here. Measured at step 2000: 193 insertions, 471 alive, 186 of them off
# the default body, bodyElong spread 0.856-1.138 — so the elongation term is
# live and varying across the population when the compare happens.
run_case "body_tri_s42"  42   2000 --tri --body-model
# The ONE configuration where both stream-adding mechanisms interleave inside a
# single insertion: the soft gate's one rng.unit() per evaluation, then the body
# model's two rng.range draws on success. Every other case exercises them in
# isolation, so a draw-ORDER regression between the two — which is exactly the
# kind of bug that is hardest to bisect after the fact — would surface here and
# nowhere else. Measured at step 2000: 55 insertions, 54 of them soft-admitted,
# bodySize spread 0.902-1.117 (53 creatures off the default body).
run_case "soft_body_s42" 42   2000 --repro-max-distance 16 --repro-soft-width 5 --body-model
# Predator floor, ceiling and heritable traits (v0.26.0). The floor and
# inheritance ADD TO THE RANDOM STREAM (three draws per refill, two per bud),
# the ceiling decides which buds happen. Each case is measured to bite at its
# compare step rather than assumed to:
#   pinherit_s42  562 buds = 1124 trait draws; speedFactor 0.62-1.48 and
#                 buddingFactor 0.50-1.32 across 441 predators at step 2000.
#   pfloor_s42    meal 0: every predator starves, and the floor refills 9 times
#                 (27 draws) to hold 3.
#   pcap_s42      the absorb meal that grows --rich to 295 predators by step
#                 2000 is held at 8 (4 buds, then refused).
#   pall_s42      all three in one run, so their draws interleave inside single
#                 steps: 11 buds, 2 refills and 13 starvations by step 6000,
#                 between a floor of 20 and a ceiling of 24.
run_case "pinherit_s42" 42   2000 --rich --pred-inherit
run_case "pfloor_s42"   42   2000 --rich --pred-meal 0 --pred-floor 3
run_case "pcap_s42"     42   2000 --rich --pred-cap 8
run_case "pall_s42"     42   6000 --rich --pred-count 20 --pred-meal 12 --pred-floor 20 --pred-inherit --pred-cap 24
# Stage C neural predators (v0.27.0). Their draws come from a second stream
# (WorldCommon::predRng_: founders' genomes, bud mutations, the RANDOM input),
# seeded by one global draw at the end of init, and the checkpoint is format 2.
# Measured at the compare step:
#   pbrain_s42        absorb meal: 385 buds (385 genome mutations), 377 predators,
#                     generation 11, 197 captures.
#   pbrain_all_s7     inheritance + floor 3 + cap 16 + max age 20 + toroidal: 3 buds,
#                     9 aged out, 1 starved, 6 random-genome refills.
#   pbrain_frozen_s3  no economy (the frozen-newborn assay): 4 immortal predators,
#                     no buds, 29 captures by their networks.
#   pbrain_frozenacct_s3  the frozen assay (economy accounting, no deaths or buds;
#                     energy held in [0, T], age capped at the max age of 10 s).
#   pbrain_primer_s5  the pursuit primer on 8 founders: 406 buds, 434 captures.
run_case "pbrain_s42"       42 2000 --rich --pred-brain
run_case "pbrain_all_s7"    7  4000 --rich --toroidal --pred-brain --pred-inherit --pred-floor 3 --pred-cap 16 --pred-max-age 20 --pred-meal 14
run_case "pbrain_frozen_s3" 3  2000 --rich --pred-brain --pred-noecon
run_case "pbrain_frozenacct_s3" 3 2000 --rich --pred-brain --pred-frozen --pred-max-age 10
run_case "pbrain_primer_s5" 5  2000 --rich --pred-brain --pred-primer --pred-count 8
run_case "long_s42"    42    10000

run_case "sat_s42"       42 2000 --weight-mutation-mode saturating
run_case "sat_rich_s7"    7 2000 --rich --weight-mutation-mode saturating
run_case "sat_pbrain_s42" 42 2000 --rich --pred-brain --weight-mutation-mode saturating

if [ "$FAILED" = "1" ]; then
    echo "== PARITY FAILED — bisect with --trace 10 on the failing case"
    exit 1
fi
echo "== ALL PARITY CASES PASS: native serial == wasm, bit for bit"
