#!/bin/bash
# ocean_parity.sh — the Ocean world's determinism suite (PLAN_ecosystem.md §12,
# E0 exit test: "Ocean: native == wasm fingerprints"), with a historical oracle.
#
# Builds tools/ocean_parity_driver.cpp natively (g++, the flags of wasm/parity.sh)
# and with Emscripten (the flags of wasm/build_ocean.sh: -msimd128, single-
# threaded; run under node), runs both over the case matrix below and holds
# every case to three oracles:
#   1. native == wasm, byte for byte. The driver fingerprints the WHOLE state
#      (tools/ocean_fingerprint.hpp) after EVERY step, folds it into a rolling
#      `chain` hash, and prints the sections and the chain every 100 steps
#      (250 in the long cases): a divergence at any step fails, even one that
#      heals before the next print.
#   2. native == the committed baseline, tests/ocean_baseline/<case>.txt.
#      Native and wasm are built from the SAME source, so a change to shared
#      behaviour (a cost, the rng stream, a feature-OFF path Classic shares)
#      passes oracle 1; the baseline, recorded from a known engine commit
#      (tests/ocean_baseline/MANIFEST), is what catches it.
#   3. the case's --expect conditions on the driver's coverage counters: it
#      really reached the branch it is in the matrix for (a predator died of
#      old age, the population sat at maxPopulation, the logs decimated, ...).
# A case also FAILS if its state ever holds a non-finite float (scanned every
# step), even when both builds agree on it: wasm leaves a NaN's bits to the host.
# That includes an object removed within a step while it held one (a fish whose
# reserves went -inf starves and is erased before any scan: the engine counts
# what removed objects held, OceanWorld::totalNonFiniteRemoved, and the driver
# adds it to the step's count); the nf_* list checks that this is caught.
# Then builds tests/ocean_tests.cpp both ways and runs it (unit checks; their
# output must also match between the builds).
#
# E1 physics: the cases before the e1_* block run with every E1 knob at its
# default (OFF); the e1_* cases turn the features on (so do steer_life_e1_s5
# and eye_e1_*). The ocean-vision keys (steerFrame, foodLife, eye, eyeOnly,
# eyeCode) are at their defaults (0) in every case before the steer_* block. The r_* list holds
# configs outside the Ocean knobs' ranges (oceanConfigError) and the Ocean's
# ranges for SimConfig keys (oceanSimConfigError): each must be REFUSED by
# oc_init / oc_set_param. The harness's copy of the E1 preset is checked against
# kE1PresetJson (src/ocean/ocean_config.hpp).
#
# Glass walls (OceanConfig::walls): every case before the walls_* block runs
# them OFF (their baselines are the ones recorded before the key existed); the
# walls_* / eye_walls_* cases turn them on and assert containment from outside
# the engine (--expect outside=0) plus the branch they are for (wallTouch,
# predWallTouch, foodNearGlass: the driver's cover counters, printed only when
# non-zero). walls_bigtank_s9 is the page's Big tank preset (BIGTANK, checked
# against web/ocean_config.js). The r_walls_* / r_wall_* / r_live_wall* configs
# must be refused (walls + toroidal, the side knobs' ranges, live changes);
# every r_live_* case is refused by both drivers' --set as well, the state
# bit for bit what a run without it has.
#
# Direct compiler calls only: CMakeLists.txt / CMakePresets.json (Classic's
# build) are untouched. Prereq: em++ on PATH, or ~/emsdk/emsdk_env.sh.
#
#   wasm/ocean_parity.sh              # everything (~8 min on 8 cores, both builds)
#   JOBS=8 OCEAN_PARITY_DIR=/tmp/x wasm/ocean_parity.sh
#   ONLY=def_s1 wasm/ocean_parity.sh  # one case (a grep -E pattern on the name)
#   NO_TESTS=1 wasm/ocean_parity.sh   # parity cases only
#   NO_EYE=1 wasm/ocean_parity.sh     # the plain Ocean build only
#   FAST=1 wasm/ocean_parity.sh       # CI's subset (FAST_CASES below: 43 cases, about a
#                                     # quarter of the cases' cost) with EVERY guard and both
#                                     # builds' unit checks; not with --rebaseline
#
# Two builds: the plain Ocean build (-DEVO_WORLD_OCEAN; every case not named
# eye_*) and the compound-eye build (+ -DEVO_OCEAN_EYE: 64 sensors, its own
# planes and genetics; the eye_* cases, eye on unless the case says otherwise;
# eye_only_* / eye_blind_* = OceanConfig::eyeOnly with the eye on / off;
# eye_code* = OceanConfig::eyeCode, the eye's encodings; eye_cloak_* = its
# cloaks, eyeCode 8 / 16: the eye ignores fish / food; eye_e1_* = with E1
# physics on). Each build's native and wasm binaries are compared with each
# other and with the baselines, each build's unit checks run natively and
# under node, and the r_eye_* refusals are asked of the eye build's shim.
#
# The appearance genome (OceanConfig::appearance, src/ocean/appearance_model.hpp)
# is ON by default, so every case above also builds and inherits it: its own
# fingerprint section (`app=` on every fp line, `appchain=` after `chain=`,
# the cover line's app* counters), kept out of `all` and `chain`. It is
# cosmetic, and this script proves that on every run: each case in APP_TWINS
# runs again with {"appearance":0}, and its output must be the case's output
# with every app* field removed, byte for byte (every simulation section, the
# combined hash, the chain over every step, the counters, the final line).
# APP_TWINS=all twins every selected case. The app_* cases cover what the
# defaults do not: patterns only / shapes only, every inheritance knob at 0
# and at its maximum, live knob changes, a long run.
#
# Bisecting a FAIL: the table names the first differing line (step and
# sections; `chain` alone = the states differed at some step since the last
# print and agree again). Re-run the case with --trace (every step) to find the
# first bad step S, then --dump-step S --dump FILE on both builds (for a
# baseline FAIL: on the old and the new engine) and diff the dumps.
#
# ---- Rebaselining -------------------------------------------------------------
#   wasm/ocean_parity.sh --rebaseline
#       runs everything and REPORTS which baselines differ and where; writes nothing
#   wasm/ocean_parity.sh --rebaseline --overwrite --reason "what changed, and why"
#       writes them, only if every selected case passes oracles 1 and 3, the
#       unit checks pass and no config guard failed (so not with NO_TESTS;
#       with ONLY the refused-config guard still runs); records the commit,
#       date, compilers, reason and cases in tests/ocean_baseline/MANIFEST.
#       Every write is checked (staged in tests/ocean_baseline/.rebaseline.*,
#       then moved into place): any failure exits 1 and says what was written
# Rebaselining is legitimate ONLY when behaviour is MEANT to change: a
# deliberate engine change (a new default path, a fix that moves a trajectory,
# a draw added by design), a new or edited case, or a change to what the
# harness hashes (bump ofp::kFormatVersion). It is NEVER legitimate to make a
# failure go away: a baseline FAIL nobody intended is a regression to find
# (--trace, --dump), not to re-record. If you cannot say which change moved
# which case and why, do not rebaseline. Commit the new baselines WITH the
# change that moved them, after reading `git diff tests/ocean_baseline`.
set -u
REBASE=0; OVERWRITE=0; REASON=""
while [ $# -gt 0 ]; do
    case "$1" in
        --rebaseline) REBASE=1 ;;
        --overwrite)  OVERWRITE=1 ;;
        --reason)     shift; REASON=${1:-} ;;
        -h|--help)    sed -n '2,/^set -u$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done
if [ "$OVERWRITE" = 1 ] && [ "$REBASE" = 0 ]; then echo "--overwrite goes only with --rebaseline" >&2; exit 2; fi
if [ "$OVERWRITE" = 1 ] && [ -z "$REASON" ]; then
    echo "--overwrite needs --reason \"which behaviour changed, on purpose, and why\"" >&2; exit 2
fi
# A baseline is written only after every check: NO_TESTS skips the unit checks
# and the shim validation (and, with them, the refused-config guard), so it
# cannot go with --overwrite. (ONLY may: the guards below still run then.)
if [ "$OVERWRITE" = 1 ] && [ -n "${NO_TESTS:-}" ]; then
    echo "--overwrite cannot go with NO_TESTS: the unit checks and the shim / config guards must run before a baseline is written" >&2
    exit 2
fi
if [ "$REBASE" = 1 ] && [ -n "${FAST:-}" ]; then
    echo "--rebaseline cannot go with FAST (CI's subset): run the whole matrix, or name the cases with ONLY" >&2
    exit 2
fi
cd "$(dirname "$0")/.."
T0=$(date +%s)
BASE=tests/ocean_baseline

OUT=${OCEAN_PARITY_DIR:-/tmp/ocean_parity}
JOBS=${JOBS:-4}
mkdir -p "$OUT"
rm -f "$OUT"/*.txt "$OUT"/*.log "$OUT"/*.rc
if ! command -v em++ > /dev/null; then
    # shellcheck disable=SC1090
    source ~/emsdk/emsdk_env.sh > /dev/null 2>&1
fi
command -v em++ > /dev/null || { echo "em++ not found: source ~/emsdk/emsdk_env.sh" >&2; exit 2; }
NODE="node --max-old-space-size=6144"

CXXFLAGS="-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src"
# build_ocean.sh's codegen flags; node instead of web, real files (NODERAWFS)
# for --dump, EXIT_RUNTIME so stdout is flushed and main's status is the exit code.
EMFLAGS="-msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1"

GPP_VER=$(g++ -dumpversion); EM_VER=$(em++ --version | head -1 | sed 's/.*) //')
echo "== tree: $(git rev-parse --abbrev-ref HEAD 2>/dev/null) $(git rev-parse --short HEAD 2>/dev/null)," \
     "$(git status --porcelain 2>/dev/null | wc -l) changed/untracked path(s)"
echo "== building (g++ $GPP_VER, $EM_VER)"
build () {  # build LABEL CMD...
    local label=$1; shift
    if "$@" > "$OUT/build_$label.log" 2>&1; then echo "   built $label"; else echo "   BUILD FAILED: $label"; cat "$OUT/build_$label.log"; return 1; fi
}
VARIANTS="plain"; [ -z "${NO_EYE:-}" ] && VARIANTS="plain eye"
PIDS=()
for v in $VARIANTS; do
    # binaries: plain = opd_native / opd_wasm.js / ocean_tests_*; eye = *_eye
    if [ $v = eye ]; then F="$CXXFLAGS -DEVO_OCEAN_EYE"; S=_eye; else F="$CXXFLAGS"; S=; fi
    build driver_native$S g++ $F tools/ocean_parity_driver.cpp -o "$OUT/opd_native$S" & PIDS+=($!)
    build driver_wasm$S   em++ $F $EMFLAGS tools/ocean_parity_driver.cpp -o "$OUT/opd_wasm$S.js" & PIDS+=($!)
    if [ -z "${NO_TESTS:-}" ]; then
        build tests_native$S g++ $F tests/ocean_tests.cpp -o "$OUT/ocean_tests_native$S" & PIDS+=($!)
        build tests_wasm$S   em++ $F $EMFLAGS tests/ocean_tests.cpp -o "$OUT/ocean_tests_wasm$S.js" & PIDS+=($!)
    fi
done
BUILD_OK=1
for p in "${PIDS[@]}"; do wait "$p" || BUILD_OK=0; done
[ "$BUILD_OK" = 1 ] || { echo "== BUILD FAILED"; exit 1; }
sfx () { [[ $1 == eye_* ]] && echo _eye; }   # sfx CASE_NAME -> the build's binary suffix

# ---- the case matrix ---------------------------------------------------------
# NAME | ARGS (driver arguments; cfg JSON written without spaces; --expect
# NAMEopV conditions on the driver's `cover` counters) | what it covers
NAMES=(); ARGS=(); WHY=()
add () { NAMES+=("$1"); ARGS+=("$2"); WHY+=("$3"); }
BANDS='--expect bandTop>0 --expect bandFloor>0'
RICH='"currentStrength":80,"currentMode":0,"currentDrift":1,"foodPatches":5,"foodDrift":true,"predatorCount":4,"predatorEconomy":true,"moveCost":7e-5,"maxNeighbors":7,"geneCost":0.005'
add def_s1        "1 3000 $BANDS"             "preview defaults (applyOceanDefaults + OceanConfig{}); both wall bands hit"
add def_s42       '42 3000'                   "defaults, another seed"
add def_s999      '999 3000'                  "defaults, another seed"
add def_s31415    '31415 3000'                "defaults, another seed"
add pred_s7       '7 3000 --cfg {"predatorCount":5} --expect dPred>0'  "Stage A predators: 3-D hunt, wander pitch draws"
add econ_s42      '42 3000 --cfg {"predatorCount":6,"predatorEconomy":true,"predatorMinPopulation":3,"predatorMaxPopulation":24,"predatorInheritance":true} --expect pBirths>0 --expect predTraitVaried>0' \
                  "Stage B economy + floor + cap + inheritance (bud depth draws)"
add rich_s5       "5 3000 --cfg {$RICH}"      "Classic's --rich set: eddies, patches+drift, economy, move/gene cost, topological 7"
add eddies_s11    '11 3000 --cfg {"currentStrength":120,"currentEddies":8,"foodDrift":true,"foodPatches":6,"foodDepthMode":1,"foodDepthSpread":20}' \
                  "strong eddies, food at per-patch depths"
add gyre_toro_s13 '13 3000 --cfg {"currentStrength":60,"currentMode":1,"currentGyreEps":0.4,"toroidal":true,"foodDrift":true}' \
                  "double gyre, toroidal senses"
add rich_toro_s7  "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1}" "rich + toroidal + patch depths"
add x_steep_s3    "3 3000 --cfg {\"pitchMax\":4,\"kBuoy\":25,\"wallBand\":100,\"vDrag\":0,\"foodDepthMode\":1,\"foodPatches\":4,\"foodDepthSpread\":500} $BANDS" \
                  "extreme: pitchMax 4, kBuoy 25, wallBand 100, no drag, spread 500"
add x_deep_s8     '8 3000 --depth 2000 --cfg {"pitchMax":0.01,"kBuoy":-5,"vDrag":200,"wallBand":0,"buoyMutation":0.5,"toroidal":true,"cHold":0.5,"cPress":0.3}' \
                  "extreme: D 2000, pitchMax 0.01, kBuoy -5, vDrag 200, no walls, depth costs"
add x_shallow_s4  "4 3000 --depth 10 --cfg {\"pitchMax\":1.5,\"wallBand\":5,\"kBuoy\":0,\"foodDepthMode\":1,\"foodPatches\":3,\"foodDepthSpread\":0} $BANDS" \
                  "extreme: D 10 (the minimum), bands cover it all, spread 0"
add x_osc_s6      '6 3000 --cfg {"vDrag":300,"pitchMax":2,"kBuoy":-20,"wallBand":119,"buoyMutation":1}' \
                  "extreme: vDrag 300 (vz flips sign each step), wallBand ~D/2, buoyMutation 1"
add x_tri_body_s9 '9 3000 --cfg {"triangularMotion":true,"bodyModel":true,"reproMaxDistance":16,"reproSoftWidth":5,"pitchMax":1.2}' \
                  "triangular motion + body model + soft repro gate (kernel draws interleaved with bodyBuoy)"
add live_s21      '21 3000 --cfg {"predatorCount":3} --set pitchMax=0.2@800 --set kBuoy=3@1200 --set vDrag=0.5@1200 --set wallBand=40@2000 --set buoyMutation=0.3@2000' \
                  "live oc_set_param-style changes mid-run"
add capture_s17   '17 3000 --capture --cfg {"predatorCount":2,"currentStrength":50}' \
                  "every fish's 46 sensor + 13 action bits hashed every step"
add big_s42       '42 2000 --pop 1500'        "1500 founders, defaults"
add big_toro_s9   '9 2000 --pop 1500 --w 2560 --h 1440 --cfg {"toroidal":true,"predatorCount":8,"predatorEconomy":true,"maxNeighbors":7,"currentStrength":60,"foodPatches":6,"foodDrift":true,"foodDepthMode":1}' \
                  "1500 founders, 2560x1440, toroidal, economy, topological, currents"
add long_s42      '42 10000 --every 250'      "10k steps, defaults"
# ---- branches the cases above never reach, each asserted with --expect ----
add pred_age_s23  '23 6000 --cfg {"predatorCount":6,"predatorEconomy":true,"predatorMaxAge":25,"predatorMeal":15,"predatorMoveCost":0.00003,"predatorMinPopulation":3,"predatorReproEnergy":50} --expect pAge>0 --expect dPred>0 --expect pBirths>0' \
                  "predators die of old age; a fixed predatorMeal; an explicit predatorMoveCost (96 s)"
add gate_s29      '29 6000 --cfg {"reproMaxDistance":16,"reproSoftWidth":0,"reproGracePeriod":30} --expect grace>0 --expect gateBirths>0 --expect soft=0' \
                  "the HARD pairing gate (soft width 0) and the grace bypass for young founders (96 s)"
add cap_s31       '31 4000 --cfg {"maxPopulation":330} --expect capSteps>0 --expect popMax=330' \
                  "a positive maxPopulation cap, binding for most of the run"
add fast_logs_s41 '41 8000 --capture --logs 16,16 --cfg {"fastTanh":true,"predatorCount":2} --expect fastTanhSteps>0 --expect clusterStride>1 --expect reproStride>1 --expect deathLog>0 --expect birthLog>0' \
                  "fastTanh nets (actions hashed); death-cluster map + birth log populated AND decimated (128 s)"
add toro_bud_s43  '43 8000 --cfg {"toroidal":true,"predatorCount":6,"predatorEconomy":true,"predatorInheritance":true,"predatorTraitMutation":0.2,"predatorMinPopulation":2,"predatorMaxPopulation":30} --expect pBirths>0 --expect predGenMax>1 --expect predTraitVaried>0' \
                  "toroidal predator budding + trait inheritance (128 s)"
# ---- E1 physics, features ON (the cases above run every E1 knob at its default) ----
# E1_PRESET must equal kE1PresetJson in src/ocean/ocean_config.hpp (checked below).
E1_PRESET='{"waveSpeed":6,"deepCurrent":true,"currentStrength":5,"foodDrift":true,"lightEnabled":true,"depthCostScaled":true,"cHold":0.05,"cPress":0.03}'
add e1_waves_s3   '3 3000 --cfg {"waveSpeed":8,"foodDrift":true,"predatorCount":3}' \
                  "E1 waves alone: three trains move food, fish, predators in 3-D"
add e1_deep_s5    '5 3000 --cfg {"deepCurrent":true,"currentStrength":60,"foodDrift":true,"foodPatches":4,"foodDepthMode":1,"predatorCount":4,"predatorEconomy":true,"predatorMinPopulation":2}' \
                  "E1 deep current (eddies x f(d)), patch depths, economy"
add e1_gyre_s13   '13 3000 --cfg {"deepCurrent":true,"waveSpeed":5,"currentStrength":40,"currentMode":1,"toroidal":true,"foodDrift":true,"maxNeighbors":7}' \
                  "E1 deep double gyre + waves, toroidal, topological"
add e1_costs_s8   '8 3000 --cfg {"depthCostScaled":true,"cHold":0.3,"cPress":0.2,"bodyModel":true,"waveSpeed":4}' \
                  "E1 depth costs x metabolicRate·massFactor, body model"
add e1_size_s9    '9 3000 --cfg {"bodyModel":true,"sizeDrift":true,"sizeFight":true,"mouthGate":true,"kMouth":1.2,"waveSpeed":6,"deepCurrent":true,"currentStrength":30,"foodDrift":true}' \
                  "E1 size laws: drift min(1,1/L), fights x L², mouth gate (L < .83 starve-gated)"
add e1_preset_s42 "42 3000 --cfg $E1_PRESET"  "E1 preset (kE1PresetJson, the page's ?e1=1)"
add e1_preset_long "7 10000 --every 250 --cfg $E1_PRESET" "E1 preset, 10k steps"
add e1_live_s21   '21 3000 --cfg {"currentStrength":40,"foodDrift":true,"predatorCount":2} --set waveSpeed=6@500 --set deepCurrent=1@800 --set sizeDrift=1@1200 --set depthCostScaled=1@1500 --set cHold=0.05@1500 --set waveGravity=40@2000 --set waveSpeed=0@2500 --set mouthGate=1@2600 --set kMouth=0.6@2600' \
                  "E1 knobs switched live (oc_set_param), waves stopped again (clock kept)"
add e1_capture_s17 '17 3000 --capture --cfg {"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"foodDrift":true}' \
                  "E1: sensors (CURRENT_FWD/LR read the 3-D flow) hashed every step"
add e1_x_shallow_s4 '4 3000 --depth 10 --cfg {"waveSpeed":100,"waveBand":1,"waveGravity":10000,"deepCurrent":true,"currentStrength":80,"foodDrift":true,"predatorCount":3}' \
                  "E1 extreme: D 10, waves at every range end (speed 100, band 1, g 10^4)"
add e1_x_big_s9   '9 2000 --pop 1500 --w 2560 --h 1440 --cfg {"waveSpeed":12,"waveBand":8,"deepCurrent":true,"currentStrength":60,"toroidal":true,"foodDrift":true,"bodyModel":true,"sizeDrift":true,"sizeFight":true,"mouthGate":true,"predatorCount":6,"predatorEconomy":true,"depthCostScaled":true,"cHold":0.1,"cPress":0.1}' \
                  "E1 everything on, 1500 founders, 2560x1440, toroidal"

# ---- own-frame steering and the food lifetime (plain build; ocean-vision) ----
# Each asserts with --expect that the branch ran (cover counters printed only
# when non-zero: steerOwnSteps, foodExpired, agesKept, eye*; see the driver).
add steer_own_s1  '1 3000 --cfg {"steerFrame":1} --expect steerOwnSteps>0' "own-frame steering (STEER_X right, STEER_Y ahead), defaults"
add steer_own_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"steerFrame\":1} --expect steerOwnSteps>0" \
                  "own-frame steering + rich + toroidal + patch depths"
add steer_own_capture_s17 '17 3000 --capture --cfg {"steerFrame":1,"predatorCount":2,"currentStrength":50} --expect steerOwnSteps>0' \
                  "own-frame steering, every fish's sensor + action bits hashed"
add steer_own_live_s21 '21 3000 --cfg {"predatorCount":3} --set steerFrame=1@700 --set steerFrame=0@1500 --set steerFrame=1@2200 --expect steerOwnSteps>0' \
                  "steerFrame switched on / off / on mid-run (oc_set_param)"
add steer_own_tri_s9 '9 3000 --cfg {"triangularMotion":true,"bodyModel":true,"reproMaxDistance":16,"reproSoftWidth":5,"pitchMax":1.2,"steerFrame":1} --expect steerOwnSteps=0' \
                  "triangular motion ignores steerFrame (fish as x_tri_body_s9's)"
# own-frame labels (OceanConfig::labelFrame, the ALIFE 2027 A1 arm; labelOwnSteps printed only when non-zero)
add label_own_capture_s17 '17 3000 --capture --cfg {"labelFrame":1,"steerFrame":1,"predatorCount":2,"currentStrength":50} --expect labelOwnSteps>0 --expect steerOwnSteps>0' \
                  "own-frame labels + own-frame steering, every fish's sensor + action bits hashed"
add label_own_live_s21 '21 3000 --cfg {"predatorCount":3,"steerFrame":1} --set labelFrame=1@600 --set labelFrame=0@1500 --set labelFrame=1@2200 --expect labelOwnSteps>0' \
                  "labelFrame switched on / off / on mid-run (oc_set_param)"
SV='"foodSpawnBase":1,"foodSpawnAmp":0,"foodEnergy":15,"targetFood":800'
add life_s1       "1 3000 --cfg {\"foodLife\":8,$SV} --expect foodExpired>0" "foodLife 8, sparse valuable food (1 item/step x 15)"
add life_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"foodLife\":5} --expect foodExpired>0" \
                  "foodLife 5 + rich (patches + drift) + toroidal"
add life_live_s21 '21 3000 --cfg {"predatorCount":3} --set foodLife=6@600 --set foodLife=0@1800 --set foodLife=2.5@2400 --expect foodExpired>0 --expect agesKept>0' \
                  "foodLife switched on / off (ages kept and hashed) / on mid-run (oc_set_param)"
add steer_life_e1_s5 "5 3000 --cfg {\"waveSpeed\":6,\"deepCurrent\":true,\"currentStrength\":20,\"foodDrift\":true,\"depthCostScaled\":true,\"cHold\":0.05,\"cPress\":0.03,\"steerFrame\":1,\"foodLife\":8,$SV} --expect steerOwnSteps>0 --expect foodExpired>0" \
                  "E1 waves + deep current + scaled costs with own-frame steering and foodLife 8"
# The spawn cap (targetFood·2) counts live items: food expiring in a step frees
# its place in that step's spawn (foodCapFreed: steps that refilled such places).
add life_cap_fixture_s1 '1 3000 --pop 0 --cfg {"minPopulation":0,"targetFood":1,"foodSpawnBase":2,"foodSpawnAmp":0,"foodLife":0.016} --expect foodExpired=5999 --expect foodCapFreed=3000' \
                  "no fish, cap 2, 2 items/step that last one step: 2 live items every step"
add life_cap_s3   '3 3000 --cfg {"targetFood":300,"foodSpawnBase":6,"foodSpawnAmp":0,"foodLife":10} --expect foodExpired>0 --expect foodCapFreed>0' \
                  "foodLife 10 with the stock at its cap (targetFood 300, 6 items/step)"
# ---- the compound-eye build (-DEVO_OCEAN_EYE: 64 sensors, its own planes) ----
# Every case named eye_* runs in the eye build (the eye on unless it says
# otherwise; eye_only_* / eye_blind_* = eyeOnly with the eye on / off; eye_code*
# = eyeCode, the eye's encodings; eye_e1_* = with E1 physics on).
add eye_off_s1    '1 3000 --expect eyeSteps=0' "eye build, eye off: 64 sensors, the 18 eye inputs read 0"
add eye_def_s1    '1 3000 --cfg {"eye":1} --expect eyeSteps>0' "eye on, defaults: fish, food in all three loops"
add eye_def_s999  '999 3000 --cfg {"eye":1} --expect eyeSteps>0' "eye on, another seed"
add eye_capture_s17 '17 3000 --capture --cfg {"eye":1,"predatorCount":2,"currentStrength":50} --expect eyeLit>0' \
                  "eye on, every fish's 64 sensor (18 eye) + 13 action bits hashed"
add eye_rich_s5   "5 3000 --cfg {$RICH,\"eye\":1} --expect eyeSteps>0" "eye on + rich: predators (economy) in the predator scan, topological 7"
add eye_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"eye\":1} --expect eyeSteps>0" \
                  "eye on + rich + toroidal (wrapped offsets) + patch depths"
add eye_x_deep_s8 '8 3000 --depth 2000 --cfg {"pitchMax":0.01,"kBuoy":-5,"vDrag":200,"wallBand":0,"buoyMutation":0.5,"toroidal":true,"cHold":0.5,"cPress":0.3,"eye":1} --expect eyeSteps>0' \
                  "eye on, D 2000: ambient light underflows toward 0 at depth"
add eye_x_shallow_s4 '4 3000 --depth 10 --cfg {"pitchMax":1.5,"wallBand":5,"kBuoy":0,"foodDepthMode":1,"foodPatches":3,"foodDepthSpread":0,"eye":1} --expect eyeSteps>0' \
                  "eye on, D 10: nearly flat, so up/down sectors are rare"
add eye_tri_body_s9 '9 3000 --cfg {"triangularMotion":true,"bodyModel":true,"reproMaxDistance":16,"reproSoftWidth":5,"pitchMax":1.2,"eye":1} --expect eyeSteps>0' \
                  "eye on + body model: fish apparent size from heritable bodySize"
add eye_live_s21  '21 3000 --cfg {"predatorCount":3} --set eye=1@500 --set eye=0@1500 --set eye=1@2200 --expect eyeSteps>0' \
                  "eye switched on / off / on mid-run (oc_set_param)"
add eye_big_toro_s9 '9 2000 --pop 1500 --w 2560 --h 1440 --cfg {"toroidal":true,"predatorCount":8,"predatorEconomy":true,"maxNeighbors":7,"currentStrength":60,"foodPatches":6,"foodDrift":true,"foodDepthMode":1,"eye":1} --expect eyeSteps>0' \
                  "eye on, 1500 founders, 2560x1440, toroidal, economy, topological, currents"
add eye_long_s42  '42 10000 --every 250 --cfg {"eye":1} --expect eyeSteps>0' "eye on, 10k steps"
# ---- eye-only mode (OceanConfig::eyeOnly: the 23 labeled senses 0 and skipped) ----
EXP='"predatorCount":4,"predatorEconomy":true,"predatorCooldown":3,"predatorMetabolism":2,"predatorMeal":10,"predatorReproEnergy":60,"predatorMaxPopulation":6,"predatorMinPopulation":2,"predatorInheritance":true'
add eye_only_s1   '1 3000 --cfg {"eye":1,"eyeOnly":1} --expect eyeOnlySteps>0 --expect eyeSteps>0' "eye-only: the eye alone, defaults"
add eye_blind_s1  '1 3000 --cfg {"eyeOnly":1} --expect eyeOnlySteps>0 --expect eyeSteps=0' "blind: eyeOnly with the eye off (own state, pheromones, current)"
add eye_only_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeOnly":1,"predatorCount":2,"currentStrength":50} --expect eyeLit>0 --expect labeledLit=0' \
                  "eye-only, every fish's 64 sensor bits hashed (23 labeled = 0)"
add eye_only_rich_s5 "5 3000 --cfg {$RICH,\"eye\":1,\"eyeOnly\":1} --expect eyeOnlySteps>0" \
                  "eye-only + rich: economy predators, topological 7 (no cut in eye-only)"
add eye_only_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"eye\":1,\"eyeOnly\":1} --expect eyeOnlySteps>0" \
                  "eye-only + rich + toroidal (wrapped offsets) + patch depths"
add eye_only_exp_s3 "3 5000 --cfg {$EXP,\"eye\":1,\"eyeOnly\":1} --expect eyeOnlySteps>0" \
                  "eye-only, the eye experiment's predator economy (meal 10, cap 6, floor 2, inheritance)"
add eye_blind_exp_toro_s4 "4 3000 --cfg {$EXP,\"toroidal\":true,\"eyeOnly\":1} --expect eyeOnlySteps>0 --expect eyeSteps=0" "blind + the experiment's economy, toroidal"
add eye_only_live_s21 '21 3000 --cfg {"predatorCount":3,"eye":1} --set eyeOnly=1@500 --set eye=0@1200 --set eyeOnly=0@1800 --set eyeOnly=1@2400 --set eye=1@2600 --expect eyeOnlySteps>0 --expect eyeSteps>0' \
                  "eyeOnly / eye switched mid-run: labeled+eye -> eye-only -> blind -> labeled -> blind -> eye-only"
add eye_steer_rich_s5 "5 3000 --cfg {$RICH,\"eye\":1,\"steerFrame\":1} --expect steerOwnSteps>0 --expect eyeSteps>0" "eye + labels + own-frame steering + rich"
add eye_steer_only_exp_s3 "3 5000 --cfg {$EXP,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1} --expect steerOwnSteps>0 --expect eyeOnlySteps>0" \
                  "eye-only + own-frame steering, the eye experiment's economy"
add eye_steer_blind_exp_toro_s4 "4 3000 --cfg {$EXP,\"toroidal\":true,\"eyeOnly\":1,\"steerFrame\":1} --expect steerOwnSteps>0 --expect eyeSteps=0" \
                  "blind + own-frame steering + the experiment's economy, toroidal"
add eye_life_steer_only_s3 "3 5000 --cfg {$EXP,$SV,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"foodLife\":8} --expect foodExpired>0 --expect steerOwnSteps>0 --expect eyeOnlySteps>0" \
                  "eye-only + own frame + foodLife 8 + sparse valuable food + the experiment's economy"
add eye_life_steer_blind_s4 "4 3000 --cfg {$EXP,$SV,\"eyeOnly\":1,\"steerFrame\":1,\"foodLife\":8} --expect foodExpired>0 --expect eyeSteps=0" \
                  "blind + own frame + foodLife 8 + sparse valuable food"
# ---- eye encodings (OceanConfig::eyeCode: 1 faded contrast, 2 opponent pairs, 4 summed sectors) ----
add eye_code1_s1  '1 3000 --cfg {"eye":1,"eyeCode":1} --expect eyeCodeMask=1' "eyeCode 1 (faded contrast), defaults"
add eye_code2_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeCode":2,"predatorCount":2,"currentStrength":50} --expect eyeCodeMask=2 --expect eyeLit>0' \
                  "eyeCode 2 (opponent pairs), every fish's sensor + action bits hashed"
add eye_code4_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeCode":4,"predatorCount":2,"currentStrength":50} --expect eyeCodeMask=4 --expect eyeLit>0' \
                  "eyeCode 4 (summed sectors), every fish's sensor + action bits hashed"
add eye_code4_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"eye\":1,\"eyeCode\":4} --expect eyeCodeMask=4" \
                  "summed sectors + rich (economy predators; topological 7: sums before the cut) + toroidal"
add eye_code7_only_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeOnly":1,"eyeCode":7,"predatorCount":2,"currentStrength":50} --expect eyeCodeMask=7 --expect eyeLit>0 --expect labeledLit=0' \
                  "eyeCode 7 (all three) + eye-only, every fish's sensor + action bits hashed"
add eye_code7_steer_only_exp_s3 "3 5000 --cfg {$EXP,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"eyeCode\":7} --expect eyeCodeMask=7 --expect steerOwnSteps>0" \
                  "eyeCode 7 + eye-only + own-frame steering, the eye experiment's economy"
add eye_code7_life_steer_only_s3 "3 5000 --cfg {$EXP,$SV,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"foodLife\":8,\"eyeCode\":7} --expect eyeCodeMask=7 --expect foodExpired>0" \
                  "eyeCode 7 + eye-only + own frame + foodLife 8 + sparse valuable food + the experiment's economy"
add eye_code7_big_s42 '42 2000 --pop 1500 --cfg {"eye":1,"eyeCode":7} --expect eyeCodeMask=7' \
                  "eyeCode 7, 1500 founders: long per-sector float sums in visit order"
add eye_code_live_s21 '21 3000 --cfg {"predatorCount":3,"eye":1} --set eyeCode=4@500 --set eyeCode=7@1000 --set eyeOnly=1@1500 --set eyeCode=2@2000 --set eyeCode=1@2400 --set eyeCode=0@2700 --expect eyeCodeMask=7 --expect eyeOnlySteps>0' \
                  "eyeCode switched mid-run (oc_set_param): 0 -> 4 -> 7 -> 7 eye-only -> 2 -> 1 -> 0"
# ---- E1 physics with the eye (each feature as defined alone; ocean_world.hpp
# "E1 with the eye build's features": food eyeCon follows its depth under E1
# drift, the eye sees mouth-gated food) ----
add eye_e1_preset_s42 "42 3000 --cfg ${E1_PRESET%\}},\"eye\":1} --expect eyeE1Steps>0" "the E1 preset (kE1PresetJson) + the eye"
add eye_e1_capture_s17 '17 3000 --capture --cfg {"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"foodDrift":true,"eye":1,"eyeCode":7} --expect eyeE1Steps>0 --expect eyeLit>0 --expect eyeCodeMask=7' \
                  "E1 waves + deep current + food drift in depth, eyeCode 7: every sensor bit hashed"
add eye_e1_size_s9 '9 3000 --cfg {"bodyModel":true,"sizeDrift":true,"sizeFight":true,"mouthGate":true,"kMouth":1.2,"waveSpeed":6,"deepCurrent":true,"currentStrength":30,"foodDrift":true,"eye":1} --expect eyeE1Steps>0' \
                  "E1 size laws (mouth gate: smell gated, sight not) + the eye"
add eye_e1_only_steer_life_s3 "3 5000 --cfg {$EXP,$SV,\"waveSpeed\":6,\"deepCurrent\":true,\"currentStrength\":20,\"foodDrift\":true,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"foodLife\":8} --expect eyeE1Steps>0 --expect eyeOnlySteps>0 --expect steerOwnSteps>0 --expect foodExpired>0" \
                  "eye-only + own frame + foodLife 8 + E1 waves / deep current + the experiment's economy"
add eye_e1_live_s21 '21 3000 --cfg {"currentStrength":40,"foodDrift":true,"predatorCount":2,"eye":1} --set waveSpeed=6@500 --set eyeOnly=1@900 --set deepCurrent=1@1200 --set steerFrame=1@1500 --set foodLife=6@1800 --set waveSpeed=0@2400 --set eyeCode=4@2600 --expect eyeE1Steps>0 --expect foodExpired>0 --expect steerOwnSteps>0' \
                  "E1 and the eye's keys switched live, interleaved (oc_set_param)"
# ---- the cloaked eye (eyeCode 8: the eye ignores fish, 16: it ignores food;
# predators always seen; the labeled senses unchanged; in eye-only mode the
# cloaked kind is not queried) ----
# L12 = the cloaked-eye ablation's world verbatim (experiment 2's cfg_L12.json:
# the stable predator economy, 1 food item/step x 15 energy, foodLife 12 s).
L12='"predatorCount":4,"predatorSpeed":110,"predatorPerception":150,"predatorCaptureRadius":14,"predatorEconomy":true,"predatorCooldown":3,"predatorMetabolism":2,"predatorMeal":10,"predatorReproEnergy":60,"predatorMaxPopulation":6,"predatorMinPopulation":2,"predatorInheritance":true,"foodSpawnBase":1,"foodSpawnAmp":0,"foodEnergy":15,"targetFood":800,"foodLife":12'
add eye_cloak_fish_s1 '1 3000 --cfg {"eye":1,"eyeCode":8} --expect eyeCodeMask=8 --expect eyeSteps>0' \
                  "the eye ignores fish, labels on (the neighbour loop runs, only the eye's bin skips fish)"
add eye_cloak_food_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeCode":16,"predatorCount":2,"currentStrength":50} --expect eyeCodeMask=16 --expect eyeLit>0' \
                  "the eye ignores food, every sensor bit hashed (the labeled food senses still read it)"
add eye_cloak_sum_rich_toro_s7 "7 3000 --cfg {$RICH,\"toroidal\":true,\"foodDepthMode\":1,\"eye\":1,\"eyeCode\":12} --expect eyeCodeMask=12" \
                  "summed sectors over food + predators (fish cloaked) + rich + toroidal + topological 7"
add eye_cloak_fish_only_steer_l12_s3 "3 5000 --cfg {$L12,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"eyeCode\":8} --expect eyeCodeMask=8 --expect eyeOnlySteps>0 --expect steerOwnSteps>0 --expect foodExpired>0" \
                  "eye-only (no neighbour query) + own frame, the ablation's world (L12)"
add eye_cloak_food_only_steer_l12_s3 "3 5000 --cfg {$L12,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"eyeCode\":16} --expect eyeCodeMask=16 --expect eyeOnlySteps>0 --expect steerOwnSteps>0 --expect foodExpired>0" \
                  "eye-only (no food query) + own frame, the ablation's world (L12)"
add eye_a1_l12_s3 "3 5000 --capture --cfg {$L12,\"steerFrame\":1,\"labelFrame\":1} --expect labelOwnSteps>0 --expect steerOwnSteps>0 --expect eyeSteps=0 --expect foodExpired>0" \
                  "ALIFE 2027 arm A1 in the eye build: labels in the steering frame, eye off, the paper's world (L12)"
add eye_a1_eye_rich_s5 "5 3000 --cfg {$RICH,\"eye\":1,\"steerFrame\":1,\"labelFrame\":1} --expect labelOwnSteps>0 --expect eyeSteps>0" \
                  "own-frame labels beside the eye + rich (predators, topological 7)"
add eye_cloak_both_only_capture_s17 '17 3000 --capture --cfg {"eye":1,"eyeOnly":1,"eyeCode":24,"predatorCount":4,"currentStrength":50} --expect eyeCodeMask=24 --expect eyeLit>0 --expect labeledLit=0' \
                  "only predators seen (eyeCode 24), eye-only, every sensor bit hashed"
add eye_cloak_live_s21 '21 3000 --cfg {"predatorCount":3,"eye":1} --set eyeCode=8@500 --set eyeCode=16@1000 --set eyeOnly=1@1500 --set eyeCode=28@2000 --set eyeCode=0@2500 --expect eyeCodeMask=28 --expect eyeOnlySteps>0' \
                  "cloaks switched mid-run (oc_set_param): 0 -> 8 -> 16 -> 16 eye-only -> 28 -> 0"

# ---- the appearance genome (on by default above; these cover its other settings) ----
APPMAX='"patternMutation":0.25,"patternPhaseMutation":0.25,"patternNovelProbability":0.25,"morphologyMutation":0.25,"morphologyNovelProbability":0.25'
APPZERO='"patternMutation":0,"patternPhaseMutation":0,"patternNovelProbability":0,"morphologyMutation":0,"morphologyNovelProbability":0'
add app_patterns_s1 '1 3000 --cfg {"appearance":1} --expect appOffspring>0 --expect appMean>0 --expect appShapeMean=0' \
                  "appearance 1: skin patterns only (shapes stay neutral)"
add app_shapes_s42 '42 3000 --cfg {"appearance":2} --expect appOffspring>0 --expect appShapeMean>0 --expect appMean=0' \
                  "appearance 2: body shapes only (patterns stay neutral)"
add app_zero_mut_s7 "7 3000 --cfg {$APPZERO} --expect appOffspring>0 --expect appNovel=0 --expect appShapeNovel=0" \
                  "every inheritance knob 0: copies and means only (still 160 draws a child)"
add app_max_mut_s8 "8 3000 --cfg {$APPMAX,\"predatorCount\":3} --expect appNovel>0 --expect appShapeNovel>0" \
                  "every inheritance knob at 0.25: clamps, crossAngle wraps, disk projections"
add app_live_s21 '21 3000 --cfg {"predatorCount":3} --set patternMutation=0.2@500 --set patternNovelProbability=0.25@1000 --set morphologyMutation=0@1500 --set patternPhaseMutation=0.25@2000 --set appearance=3@2200 --set morphologyNovelProbability=0@2500 --expect appOffspring>0' \
                  "the inheritance knobs changed live; appearance set to the value it has (a no-op)"
add app_rich_toro_e1_s9 "9 3000 --cfg {$RICH,\"toroidal\":true,\"waveSpeed\":6,\"deepCurrent\":true,\"bodyModel\":true,\"sizeDrift\":true,$APPMAX} --expect appFounders>300 --expect appOffspring>0" \
                  "max knobs + rich (reseeds, predation) + toroidal + E1 + body model"
add app_long_s42  '42 20000 --every 500 --expect appOffspring>0' "20k steps, defaults: the genealogy over a long run"

# ---- glass walls (OceanConfig::walls; every case above runs them OFF, and so
# wraps exactly as before the key existed). Each asserts containment from
# outside the engine (--expect outside=0: no fish, trail point, food item or
# predator outside the closed tank after any step) and the branch it is for.
# BIGTANK = the page's "Big tank" preset (web/ocean_config.js BIG_TANK) verbatim
# (checked below). ----
BIGTANK='"walls":true,"maxPopulation":2000,"minPopulation":200,"targetFood":9600,"foodSpawnBase":12,"foodSpawnAmp":8,"foodEnergy":5,"interactRadius":48,"waveSpeed":6,"deepCurrent":true,"currentStrength":5,"foodDrift":true,"lightEnabled":true,"depthCostScaled":true,"cHold":0.05,"cPress":0.03,"steerFrame":1'
WALLX='--expect wallSteps>0 --expect outside=0'
add walls_def_s1  "1 3000 --cfg {\"walls\":true} $WALLX --expect wallTouch>0" "glass walls, defaults: soft turns, contact, trails held inside"
add walls_def_s999 "999 3000 --cfg {\"walls\":true} $WALLX" "glass walls, another seed"
add walls_e1_s42  "42 3000 --cfg ${E1_PRESET%\}},\"walls\":true} $WALLX --expect wallTouch>0" \
                  "the E1 preset in a glass tank: standing-mode pairs, tapered current, food's mirror-folded transport"
add walls_e1_long "7 10000 --every 250 --cfg ${E1_PRESET%\}},\"walls\":true} $WALLX" "the E1 preset with walls, 10k steps"
add walls_rich_s5 "5 3000 --cfg {$RICH,\"walls\":true} $WALLX" "rich (eddies, patches + drift, economy, topological) in a glass tank"
add walls_econ_s42 "42 3000 --cfg {\"walls\":true,\"predatorCount\":6,\"predatorEconomy\":true,\"predatorMinPopulation\":3,\"predatorMaxPopulation\":24,\"predatorInheritance\":true} $WALLX --expect pBirths>0" \
                  "predator economy with walls: buds mirror-folded inside (the same draws)"
add walls_gyre_s13 "13 3000 --cfg {\"walls\":true,\"deepCurrent\":true,\"waveSpeed\":5,\"currentStrength\":40,\"currentMode\":1,\"currentGyreEps\":0.4,\"foodDrift\":true,\"maxNeighbors\":7} $WALLX" \
                  "deep double gyre (tapered streamfunction) + waves, topological"
add walls_patch_s11 "11 3000 --cfg {\"walls\":true,\"currentStrength\":120,\"currentEddies\":8,\"foodDrift\":true,\"foodPatches\":6,\"foodPatchRadius\":400,\"foodDepthMode\":1,\"foodDepthSpread\":200} $WALLX --expect foodNearGlass>0" \
                  "wide food patches at patch depths (drawn over patch ∩ tank), strong eddies"
add walls_tri_body_s9 "9 3000 --cfg {\"walls\":true,\"triangularMotion\":true,\"bodyModel\":true,\"reproMaxDistance\":16,\"reproSoftWidth\":5,\"pitchMax\":1.2} $WALLX" \
                  "triangular motion + body model with walls"
add walls_size_s9 "9 3000 --cfg {\"walls\":true,\"bodyModel\":true,\"sizeDrift\":true,\"sizeFight\":true,\"mouthGate\":true,\"kMouth\":1.2,\"waveSpeed\":6,\"deepCurrent\":true,\"currentStrength\":30,\"foodDrift\":true} $WALLX" \
                  "E1 size laws (sizeDrift through the wall flow) with walls"
add walls_capture_s17 "17 3000 --capture --cfg {\"walls\":true,\"predatorCount\":2,\"currentStrength\":50,\"foodDrift\":true} $WALLX" \
                  "walls: every fish's sensor + action bits hashed (BOUNDARY_DIST, CURRENT_FWD / LR of the wall flow)"
add walls_live_s21 "21 3000 --cfg {\"walls\":true,\"predatorCount\":3,\"currentStrength\":40,\"foodDrift\":true} --set waveSpeed=6@500 --set deepCurrent=1@900 --set sizeDrift=1@1200 --set waveSpeed=0@2400 $WALLX" \
                  "walls with the E1 knobs switched live (wall waves prepared live, stopped again)"
add walls_steer_life_s1 "1 3000 --cfg {\"walls\":true,\"steerFrame\":1,\"foodLife\":8,$SV} $WALLX --expect steerOwnSteps>0 --expect foodExpired>0" \
                  "walls + own-frame steering + foodLife 8, sparse valuable food"
add walls_x_band0_s3 "3 3000 --cfg {\"walls\":true,\"sideWallBand\":0,\"minSpeed\":100,\"maxSpeed\":2000,\"currentStrength\":200,\"foodDrift\":true,\"predatorCount\":3,\"predatorSpeed\":600} $WALLX --expect wallTouch>0 --expect predWallTouch>0" \
                  "extreme: no soft band (contact only), speeds to 2000, a 200-strength current"
add walls_x_shallow_s4 "4 3000 --depth 10 --cfg {\"walls\":true,\"waveSpeed\":100,\"waveBand\":1,\"waveGravity\":10000,\"deepCurrent\":true,\"currentStrength\":80,\"foodDrift\":true,\"predatorCount\":3,\"sideWallBand\":400,\"sideWallTurnRate\":1000} $WALLX" \
                  "extreme: D 10, waves at their range ends (16 transport substeps), band 400, turn rate 1000"
add walls_x_small_s6 "6 3000 --w 100 --h 100 --pop 60 --cfg {\"walls\":true,\"currentStrength\":300,\"currentMode\":1,\"currentGyreEps\":1,\"waveSpeed\":30,\"foodDrift\":true,\"targetFood\":200,\"perceptionRadius\":40,\"predatorCount\":2} $WALLX --expect wallTouch>0" \
                  "extreme: a 100 x 100 tank, gyre 300 eps 1, waves 30"
add walls_bigtank_s9 "9 1000 --pop 2000 --w 3840 --h 2160 --cfg {$BIGTANK} $WALLX" "the Big tank preset: 3840 x 2160 x 240, 2000 founders"
add eye_walls_s1  "1 3000 --cfg {\"eye\":1,\"walls\":true} $WALLX --expect eyeSteps>0" "the eye with walls (non-wrapped offsets)"
add eye_walls_e1_capture_s17 "17 3000 --capture --cfg {\"eye\":1,\"eyeCode\":7,\"walls\":true,\"waveSpeed\":6,\"deepCurrent\":true,\"currentStrength\":40,\"foodDrift\":true} $WALLX --expect eyeLit>0" \
                  "the eye (code 7) with walls + E1 flow: food eyeCon follows its folded depth; every sensor bit hashed"
add eye_walls_only_steer_s3 "3 5000 --cfg {$EXP,\"eye\":1,\"eyeOnly\":1,\"steerFrame\":1,\"walls\":true} $WALLX --expect eyeOnlySteps>0" \
                  "eye-only + own frame + the experiment's economy, in a glass tank"

# CI's subset (FAST=1; .github/workflows/ci.yml on every push / pull request;
# the whole matrix runs there weekly and on demand): one or more cases of every
# family above, the cheap ones — defaults, predators + economy, rich, the
# extremes, live changes, capture, the population cap, triangular + body, E1
# (alone, preset, live, extreme, costs), own-frame steering, the food lifetime
# (with the spawn-cap cases), in the eye build the eye off / on / captured,
# eye-only, blind, the encodings, the cloaks, E1 + eye-only + foodLife, and
# the appearance genome's settings (patterns only, shapes only, every knob at
# its maximum, live knobs). The appearance twins of DEFAULT_TWINS run for the
# selected cases only (13 of them).
FAST_CASES="def_s1 pred_s7 econ_s42 rich_s5 rich_toro_s7 x_steep_s3 x_deep_s8 x_shallow_s4 live_s21 capture_s17
 cap_s31 x_tri_body_s9 e1_deep_s5 e1_waves_s3 e1_preset_s42 e1_live_s21 e1_x_shallow_s4 e1_costs_s8 steer_own_s1
 steer_own_live_s21 life_s1 life_rich_toro_s7 life_live_s21 steer_life_e1_s5 life_cap_fixture_s1 life_cap_s3
 eye_off_s1 eye_def_s1 eye_capture_s17 eye_blind_s1 eye_only_capture_s17 eye_code7_only_capture_s17 eye_code_live_s21
 eye_e1_only_steer_life_s3 eye_cloak_both_only_capture_s17 eye_cloak_live_s21 eye_cloak_food_only_steer_l12_s3
 eye_life_steer_blind_s4 eye_x_shallow_s4 app_patterns_s1 app_shapes_s42 app_max_mut_s8 app_live_s21
 walls_def_s1 walls_e1_s42 walls_econ_s42 walls_x_band0_s3 walls_x_shallow_s4 eye_walls_s1"

# Configs the page must REFUSE (oc_init / oc_set_param; ocean_tests --accepts
# must exit 1): every Ocean knob has a finite range, so none of these can run.
RNAMES=(); RARGS=()
radd () { RNAMES+=("$1"); RARGS+=("$2"); }
radd r_kbuoy_hole   '1 10 --cfg {"kBuoy":-1e37}'
radd r_kbuoy_big    '1 10 --cfg {"kBuoy":1001}'
radd r_vdrag        '1 10 --cfg {"vDrag":1e30}'
radd r_pitch_tiny   '1 10 --cfg {"pitchMax":1e-9}'
radd r_wallband     '1 10 --cfg {"wallBand":1e9}'
radd r_buoymut      '1 10 --cfg {"buoyMutation":1.5}'
radd r_chold_neg    '1 10 --cfg {"cHold":-0.5}'
radd r_spread       '1 10 --cfg {"foodDepthSpread":1e30}'
radd r_mode         '1 10 --cfg {"foodDepthMode":2}'
radd r_wave_speed   '1 10 --cfg {"waveSpeed":1e6}'
radd r_wave_band    '1 10 --cfg {"waveSpeed":6,"waveBand":0}'
radd r_wave_g       '1 10 --cfg {"waveGravity":0}'
radd r_kwater       '1 10 --cfg {"kWater":-0.1}'
radd r_l0           '1 10 --cfg {"L0":1e39}'
radd r_kmouth       '1 10 --cfg {"kMouth":0}'
radd r_bool         '1 10 --cfg {"deepCurrent":2}'
# A SimConfig switch is true / false, an Ocean one true / false / 0 / 1, at every
# occurrence (SimConfig's reader kept the old value for anything else:
# {"toroidal":1} ran with walls).
radd r_bool_sim_one '1 10 --cfg {"toroidal":1}'
radd r_bool_sim_two '1 10 --cfg {"toroidal":2}'
radd r_bool_sim_frac '1 10 --cfg {"bodyModel":0.5}'
radd r_bool_sim_str '1 10 --cfg {"foodDrift":"yes"}'
radd r_bool_sim_null '1 10 --cfg {"predatorEconomy":null}'
radd r_bool_sim_dup '1 10 --cfg {"triangularMotion":true,"triangularMotion":2}'
radd r_bool_ocean_str '1 10 --cfg {"lightEnabled":"on"}'
radd r_bool_ocean_dup '1 10 --cfg {"deepCurrent":true,"deepCurrent":"x"}'
radd r_depth        '1 10 --depth 1e6'
radd r_live_kbuoy   '1 10 --set kBuoy=1e37@5'
radd r_live_wave    '1 10 --set waveSpeed=500@5'
radd r_live_bool    '1 10 --set mouthGate=0.5@5'
radd r_live_band    '1 10 --set waveBand=0.5@5'
# The Ocean's ranges for SimConfig keys (ocean_config.hpp oceanSimConfigError).
radd r_cur_hang     '1 10 --pop 0 --cfg {"currentMode":1,"currentStrength":1e20,"deepCurrent":true,"foodDrift":true,"targetFood":1}'
radd r_cur_strength '1 10 --cfg {"currentStrength":1001}'
radd r_cur_neg      '1 10 --cfg {"currentStrength":-1}'
radd r_cur_eddies   '1 10 --cfg {"currentStrength":50,"currentEddies":101}'
radd r_cur_core     '1 10 --cfg {"currentStrength":50,"currentCore":1e9}'
radd r_cur_drift    '1 10 --cfg {"currentStrength":50,"currentDrift":1e30}'
radd r_cur_eps      '1 10 --cfg {"currentStrength":50,"currentMode":1,"currentGyreEps":2}'
radd r_cur_mode     '1 10 --cfg {"currentStrength":50,"currentMode":2}'
radd r_patch_radius '1 10 --cfg {"toroidal":true,"foodPatches":3,"foodPatchRadius":1e30}'
# Int keys must be whole numbers in int's range (checked before the shared
# reader's (int) cast), and the values that reach an int conversion while stepping.
radd r_int_big      '1 10 --cfg {"maxPopulation":2147483648}'
radd r_int_neg_big  '1 10 --cfg {"foodPatches":-1e10}'
radd r_int_frac     '1 10 --cfg {"currentMode":0.5}'
radd r_int_dup      '1 10 --cfg {"predatorCount":2,"predatorCount":1e300}'
radd r_live_int     '1 10 --set maxPopulation=2147483648@5'
radd r_live_frac    '1 10 --set minPopulation=7.5@5'
radd r_food_base    '1 10 --cfg {"foodSpawnBase":1e20}'
radd r_food_amp     '1 10 --cfg {"foodSpawnAmp":-1e20}'
radd r_live_food    '1 10 --set foodSpawnBase=1e20@5'
radd r_target_food  '1 10 --cfg {"targetFood":2000000000}'
radd r_live_target  '1 10 --set targetFood=2147483647@5'
radd r_speed        '1 10 --cfg {"maxSpeed":1e30}'
radd r_live_speed   '1 10 --set maxSpeed=1e30@5'
radd r_pred_speed   '1 10 --cfg {"predatorCount":2,"predatorSpeed":1e30}'
radd r_radius_big   '1 10 --cfg {"predatorCount":2,"predatorPerception":1e30}'
# Every other float the step reads must be finite (1e39 is an infinite float),
# and the counts / world sizes that size allocations have generous ceilings.
radd r_turn_inf     '1 10 --cfg {"triangularMotion":true,"maxTurnRate":1e39}'
# Arithmetic-safe motion bounds (the live-code audit of PRs #22-#25, finding 4):
# maxTurnRate 3e38 x turnFactor 4/3 overflowed (then 0 x inf = NaN); maxSpeed
# 1e-38 made the first captured OWN_SPEED = 80 / 1e-38 = inf.
radd r_turn_big     '1 10 --cfg {"triangularMotion":true,"bodyModel":true,"maxTurnRate":3e38}'
radd r_turn_neg_big '1 10 --cfg {"triangularMotion":true,"maxTurnRate":-10001}'
radd r_speed_tiny   '1 10 --pop 1 --capture --cfg {"minPopulation":0,"minSpeed":0,"maxSpeed":1e-38}'
radd r_live_speed_tiny '1 10 --cfg {"minSpeed":0} --set maxSpeed=0.001@5'
radd r_cooldown_inf '1 10 --cfg {"interactCooldown":1e39}'
radd r_repro_cd_inf '1 10 --cfg {"reproCooldown":-1e39}'
radd r_pred_metab   '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorMetabolism":1e39}'
radd r_pred_cd_inf  '1 10 --cfg {"predatorCount":2,"predatorCooldown":1e39}'
radd r_pred_meal    '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorMeal":1e39}'
radd r_pred_repro   '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorReproEnergy":-1e39}'
radd r_pred_age_inf '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorMaxAge":1e39}'
# The energies in [-1e6, 1e6] (kOceanMaxEnergy): finite values past it overflowed
# (one fish eating four items of 1e38: reserves +inf; moveCost 1e38: a step's cost inf).
radd r_food_energy  '1 1 --pop 1 --cfg {"minPopulation":0,"pickupRadius":1000000,"foodEnergy":1e38}'
radd r_move_cost    '1 10 --cfg {"moveCost":1e38}'
radd r_gene_cost    '1 10 --cfg {"geneCost":-1000001}'
radd r_metab_big    '1 10 --cfg {"metabolicRate":2e6}'
radd r_newborn_big  '1 10 --cfg {"newbornEnergy":1e7}'
radd r_repro_big    '1 10 --cfg {"reproEnergy":-2e6}'
radd r_pred_meal_big '1 10 --cfg {"predatorCount":4,"predatorEconomy":true,"predatorMeal":3e38}'
radd r_pred_mcost_big '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorMoveCost":1e38}'
radd r_pred_newborn_big '1 10 --cfg {"predatorCount":2,"predatorEconomy":true,"predatorNewbornEnergy":-3e38}'
radd r_live_energy  '1 10 --set foodEnergy=1000001@5'
radd r_live_pred_metab '1 10 --cfg {"predatorCount":2,"predatorEconomy":true} --set predatorMetabolism=1e30@5'
# (Each just past its ceiling, and still small enough to allocate: were the
# check missing, oc_init would accept it, not crash into a false "refused".)
radd r_pop_big      '1 10 --pop 100001'
radd r_width_big    '1 10 --w 100001'
radd r_height_big   '1 10 --h 100001'
radd r_grid_cells   '1 10 --w 6000 --h 3000 --cfg {"perceptionRadius":1,"interactRadius":1,"pickupRadius":1}'
radd r_minpop_big   '1 10 --cfg {"minPopulation":100001}'
radd r_live_minpop  '1 10 --set minPopulation=100001@5'
radd r_predcount_big '1 10 --cfg {"predatorCount":100001}'
radd r_patches_big  '1 10 --cfg {"foodPatches":100001}'
# The ocean-vision keys: the int keys (eye, eyeOnly, eyeCode, steerFrame) are
# whole numbers in int's range, then in range; foodLife in [0, 3600] (beyond,
# float ages lose accuracy, and from 2^19 s they stop: kOceanMaxFoodLife). r_eye_*
# are asked of the eye build's shim, the rest of the plain build's (where eye,
# eyeOnly and eyeCode must stay 0).
radd r_steer_frac   '1 10 --cfg {"steerFrame":0.5}'
radd r_steer_two    '1 10 --cfg {"steerFrame":2}'
radd r_steer_huge   '1 10 --cfg {"steerFrame":1e300}'
radd r_steer_dup    '1 10 --cfg {"steerFrame":1,"steerFrame":0.5}'
radd r_life_neg     '1 10 --cfg {"foodLife":-1}'
radd r_life_big     '1 10 --cfg {"foodLife":1000001}'
radd r_life_inf     '1 10 --cfg {"foodLife":1e39}'
radd r_life_hour    '1 10 --cfg {"foodLife":3600.5}'
radd r_life_stall   '1 10 --cfg {"foodLife":1000000}'
radd r_live_steer   '1 10 --set steerFrame=0.5@5'
radd r_live_steer2  '1 10 --set steerFrame=2@5'
radd r_live_life    '1 10 --set foodLife=1e7@5'
radd r_live_life_hour '1 10 --set foodLife=3601@5'
radd r_plain_eye    '1 10 --cfg {"eye":1}'
radd r_plain_eyeonly '1 10 --cfg {"eyeOnly":1}'
radd r_plain_eyecode '1 10 --cfg {"eyeCode":1}'
radd r_plain_live_eye '1 10 --set eye=1@5'
radd r_eye_frac     '1 10 --cfg {"eye":0.5}'
radd r_eye_two      '1 10 --cfg {"eye":2}'
radd r_eye_huge     '1 10 --cfg {"eye":1e300}'
radd r_eye_dup      '1 10 --cfg {"eye":1,"eye":0.5}'
radd r_eye_only_frac '1 10 --cfg {"eye":1,"eyeOnly":0.5}'
radd r_eye_only_two '1 10 --cfg {"eyeOnly":2}'
radd r_eye_code_frac '1 10 --cfg {"eye":1,"eyeCode":0.5}'
radd r_eye_code_big '1 10 --cfg {"eye":1,"eyeCode":32}'
radd r_plain_cloak  '1 10 --cfg {"eyeCode":16}'
radd r_eye_code_huge '1 10 --cfg {"eye":1,"eyeCode":1e300}'
radd r_eye_code_neg '1 10 --cfg {"eye":1,"eyeCode":-1}'
radd r_eye_code_int '1 10 --cfg {"eye":1,"eyeCode":2147483648}'
radd r_eye_live_frac '1 10 --set eye=0.5@5'
radd r_eye_live_code '1 10 --set eyeCode=32@5'
radd r_eye_live_code_frac '1 10 --set eyeCode=2.5@5'
radd r_eye_radius_sq '1 10 --cfg {"eye":1,"perceptionRadius":1e20}'
# The appearance keys: appearance a bit set 0..3, set at init only; each knob in [0, 0.25].
radd r_app_four     '1 10 --cfg {"appearance":4}'
radd r_app_neg      '1 10 --cfg {"appearance":-1}'
radd r_app_frac     '1 10 --cfg {"appearance":1.5}'
radd r_app_huge     '1 10 --cfg {"appearance":1e300}'
radd r_app_mut      '1 10 --cfg {"patternMutation":0.26}'
radd r_app_phase    '1 10 --cfg {"patternPhaseMutation":-0.01}'
radd r_app_novel    '1 10 --cfg {"patternNovelProbability":1e39}'
radd r_app_mmut     '1 10 --cfg {"morphologyMutation":0.5}'
radd r_app_mnovel   '1 10 --cfg {"morphologyNovelProbability":2}'
radd r_app_live_off '1 10 --set appearance=0@5'
radd r_app_live_two '1 10 --set appearance=2@5'
radd r_app_live_mut '1 10 --set patternMutation=0.3@5'
radd r_app_live_nov '1 10 --set morphologyNovelProbability=0.26@5'
# Glass walls: never with toroidal (either order), the bool strict, the side
# knobs in [0, 1e5] / [0, 1000], every walls key restart-only (oc_set_param
# refuses it, on or off, the same value too), the world-size / grid checks too.
radd r_walls_toro   '1 10 --cfg {"walls":true,"toroidal":true}'
radd r_walls_toro_rev '1 10 --cfg {"toroidal":true,"walls":1}'
radd r_walls_str    '1 10 --cfg {"walls":"yes"}'
radd r_walls_two    '1 10 --cfg {"walls":2}'
radd r_walls_dup    '1 10 --cfg {"walls":true,"walls":"x"}'
radd r_wall_band_neg '1 10 --cfg {"walls":true,"sideWallBand":-1}'
radd r_wall_band_big '1 10 --cfg {"walls":true,"sideWallBand":100001}'
radd r_wall_turn_neg '1 10 --cfg {"walls":true,"sideWallTurnRate":-1}'
radd r_wall_turn_big '1 10 --cfg {"walls":true,"sideWallTurnRate":1001}'
radd r_wall_turn_inf '1 10 --cfg {"sideWallTurnRate":1e39}'
radd r_live_walls   '1 10 --set walls=1@5'
radd r_live_walls_off '1 10 --cfg {"walls":true} --set walls=0@5'
radd r_live_walls_same '1 10 --cfg {"walls":true} --set walls=1@5'
radd r_live_wall_band '1 10 --cfg {"walls":true} --set sideWallBand=40@5'
radd r_live_wall_turn '1 10 --cfg {"walls":true} --set sideWallTurnRate=3@5'
radd r_walls_grid   '1 10 --w 6000 --h 3000 --cfg {"walls":true,"perceptionRadius":1,"interactRadius":1,"pickupRadius":1}'
radd r_walls_narrow '1 10 --w 99 --cfg {"walls":true}'

# Non-finite state that is gone before any scan can see it (the Codex audit of
# PR #18, finding 6): a fish whose reserves overflow to -inf starves and is
# erased within the step, a predator likewise. Each nf_* run must still report
# it, in both builds: nonfinite_max > 0 and cover nonFiniteRemoved > 0, with the
# objects gone from the final world (the third field). The energy ranges refuse
# these configs now, so they run with the driver's TEST-ONLY --unchecked (the
# Ocean's ranges not applied); they are not parity cases.
NFNAMES=(); NFARGS=(); NFGONE=()
nfadd () { NFNAMES+=("$1"); NFARGS+=("$2"); NFGONE+=("$3"); }
nfadd nf_move_cost      '1 3 --pop 1 --unchecked --cfg {"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"minSpeed":30,"maxSpeed":30,"moveCost":1e38}' 'pop=0'
nfadd nf_pred_move_cost '1 3 --pop 0 --unchecked --cfg {"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":2,"predatorEconomy":true,"predatorMoveCost":1e38}' 'pred=0'

run_one () {  # run_one INDEX: native and wasm side by side
    local i=$1 name=${NAMES[$1]} s
    s=$(sfx "$name")
    local -a A
    read -r -a A <<< "${ARGS[$i]}"
    ( "$OUT/opd_native$s" "${A[@]}" > "$OUT/$name.native.txt" 2> "$OUT/$name.native.log"; echo $? > "$OUT/$name.native.rc" ) &
    ( $NODE "$OUT/opd_wasm$s.js" "${A[@]}" > "$OUT/$name.wasm.txt" 2> "$OUT/$name.wasm.log"; echo $? > "$OUT/$name.wasm.rc" ) &
    wait
}

SEL=()
for i in "${!NAMES[@]}"; do
    if [ -n "${ONLY:-}" ] && ! [[ ${NAMES[$i]} =~ ${ONLY} ]]; then continue; fi
    if [ -n "${NO_EYE:-}" ] && [[ ${NAMES[$i]} == eye_* ]]; then continue; fi
    if [ -n "${FAST:-}" ] && [[ " $(echo $FAST_CASES) " != *" ${NAMES[$i]} "* ]]; then continue; fi
    SEL+=("$i")
done
FAST_BAD=""
if [ -n "${FAST:-}" ]; then   # every FAST_CASES name must be a case (a typo would silently shrink the subset)
    for c in $FAST_CASES; do
        found=0
        for nm in "${NAMES[@]}"; do [ "$nm" = "$c" ] && found=1 && break; done
        [ "$found" = 1 ] || FAST_BAD="$FAST_BAD $c"
    done
    echo "== FAST: CI's subset, ${#SEL[@]} of ${#NAMES[@]} cases${FAST_BAD:+; NOT CASES:$FAST_BAD}"
fi
# Every case must be a world the page accepts: the real oc_init / oc_set_param
# validation (wasm/ocean_wasm.cpp, through ocean_tests --accepts) is asked first.
declare -A REFUSED=()
if [ -z "${NO_TESTS:-}" ]; then
    for i in "${SEL[@]}"; do
        read -r -a A <<< "${ARGS[$i]}"
        msg=$("$OUT/ocean_tests_native$(sfx "${NAMES[$i]}")" --accepts "${A[@]}" 2>&1) || REFUSED[$i]=${msg:-refused}
    done
    echo "== shim validation (oc_init + oc_set_param): $(( ${#SEL[@]} - ${#REFUSED[@]} )) of ${#SEL[@]} case configs accepted"
fi
# The configs that must be refused, and the preset's copy above vs the source.
# (ONLY skips the refused-config list to save time, except under --overwrite.)
GUARD_FAILED=0
if [ -z "${NO_TESTS:-}" ] && { [ -z "${ONLY:-}" ] || [ "$OVERWRITE" = 1 ]; }; then
    nref=0; bad=""
    for i in "${!RNAMES[@]}"; do
        read -r -a A <<< "${RARGS[$i]}"
        rs=; [[ ${RNAMES[$i]} == r_eye_* ]] && rs=_eye
        if [ -n "$rs" ] && [ -n "${NO_EYE:-}" ]; then continue; fi
        if "$OUT/ocean_tests_native$rs" --accepts "${A[@]}" > "$OUT/${RNAMES[$i]}.refusal.txt" 2>&1; then
            bad="$bad ${RNAMES[$i]}"
        else
            nref=$((nref + 1))
        fi
    done
    if [ -z "$bad" ]; then
        echo "== out-of-range configs: $nref of ${#RNAMES[@]} refused by oc_init / oc_set_param (as they must be)${NO_EYE:+; r_eye_* skipped (NO_EYE)}"
    else
        echo "== out-of-range configs ACCEPTED (must be refused):$bad"; GUARD_FAILED=1
    fi
fi
SRC_PRESET=$(sed -n 's/^ *R"(\(.*\))";$/\1/p' src/ocean/ocean_config.hpp | head -1)
if [ "$SRC_PRESET" = "$E1_PRESET" ]; then
    echo "== E1 preset: the harness's copy == kE1PresetJson"
else
    echo "== E1 preset DRIFT: harness '$E1_PRESET' vs ocean_config.hpp '$SRC_PRESET'"; GUARD_FAILED=1
fi
# The Big tank case runs the page's preset (web/ocean_config.js BIG_TANK) verbatim.
JS_BIG=$($NODE -e 'require("./web/ocean_config.js"); const b = globalThis.EvoOceanConfig.BIG_TANK; console.log(JSON.stringify(b.cfg) + " " + b.width + "x" + b.height + "x" + b.depth + " pop=" + b.population)' 2>&1)
if [ "$JS_BIG" = "{$BIGTANK} 3840x2160x240 pop=2000" ]; then
    echo "== Big tank preset: the harness's copy == web/ocean_config.js BIG_TANK"
else
    echo "== Big tank preset DRIFT: harness '{$BIGTANK} 3840x2160x240 pop=2000' vs web/ocean_config.js '$JS_BIG'"; GUARD_FAILED=1
fi
# The Ocean's pre-cast check of int keys (ocean_config.hpp kSimConfigIntKeys)
# must cover exactly the keys checkpoint::readConfig reads with intOr.
RC_INT=$(sed -n '/^inline void readConfig/,/^}/p' src/core/checkpoint_io.hpp | grep -o 'intOr("[A-Za-z]*"' | sed 's/intOr("//;s/"//' | sort | tr '\n' ' ')
OC_INT=$(sed -n '/kSimConfigIntKeys\[\] = {/,/};/p' src/ocean/ocean_config.hpp | grep -o '"[A-Za-z]*"' | tr -d '"' | sort | tr '\n' ' ')
if [ -n "$RC_INT" ] && [ "$RC_INT" = "$OC_INT" ]; then
    echo "== int keys: kSimConfigIntKeys == checkpoint::readConfig's intOr keys ($(echo "$OC_INT" | wc -w))"
else
    echo "== int keys DRIFT: readConfig reads '$RC_INT', kSimConfigIntKeys lists '$OC_INT'"; GUARD_FAILED=1
fi
# And the bool-key check (kSimConfigBoolKeys, kOceanBoolKeys) exactly the keys
# readConfig reads with boolOr and readOceanConfig with readBool.
RC_BOOL=$(sed -n '/^inline void readConfig/,/^}/p' src/core/checkpoint_io.hpp | grep -o 'boolOr("[A-Za-z]*"' | sed 's/boolOr("//;s/"//' | sort | tr '\n' ' ')
OC_BOOL=$(sed -n '/kSimConfigBoolKeys\[\] = {/,/};/p' src/ocean/ocean_config.hpp | grep -o '"[A-Za-z]*"' | tr -d '"' | sort | tr '\n' ' ')
RO_BOOL=$(sed -n '/^inline bool readOceanConfig/,/^}/p' src/ocean/ocean_config.hpp | grep -o 'readBool(o, "[A-Za-z]*"' | sed 's/.*"\([A-Za-z]*\)"/\1/' | sort | tr '\n' ' ')
OO_BOOL=$(sed -n '/kOceanBoolKeys\[\] = {/,/};/p' src/ocean/ocean_config.hpp | grep -o '"[A-Za-z]*"' | tr -d '"' | sort | tr '\n' ' ')
if [ -n "$RC_BOOL" ] && [ "$RC_BOOL" = "$OC_BOOL" ] && [ -n "$RO_BOOL" ] && [ "$RO_BOOL" = "$OO_BOOL" ]; then
    echo "== bool keys: kSimConfigBoolKeys == readConfig's boolOr keys ($(echo "$OC_BOOL" | wc -w)), kOceanBoolKeys == readOceanConfig's readBool keys ($(echo "$OO_BOOL" | wc -w))"
else
    echo "== bool keys DRIFT: readConfig '$RC_BOOL' vs kSimConfigBoolKeys '$OC_BOOL'; readOceanConfig '$RO_BOOL' vs kOceanBoolKeys '$OO_BOOL'"; GUARD_FAILED=1
fi
# Non-finite state removed within a step must still fail a run (the nf_* list).
nfbad=""
for i in "${!NFNAMES[@]}"; do
    read -r -a A <<< "${NFARGS[$i]}"
    for b in native wasm; do
        f="$OUT/${NFNAMES[$i]}.nf_$b.txt"
        if [ $b = native ]; then "$OUT/opd_native" "${A[@]}" > "$f" 2> /dev/null; else $NODE "$OUT/opd_wasm.js" "${A[@]}" > "$f" 2> /dev/null; fi
        rc=$?
        fin=$(grep '^final ' "$f")
        nfm=$(echo "$fin" | tr ' ' '\n' | sed -n 's/^nonfinite_max=//p')
        rem=$(grep '^cover ' "$f" | tr ' ' '\n' | sed -n 's/^nonFiniteRemoved=//p')
        if [ "$rc" != 0 ] || [ -z "$nfm" ] || [ "$nfm" = 0 ] || [ -z "$rem" ] || [ "$rem" = 0 ] || [[ $fin != *" ${NFGONE[$i]} "* ]]; then
            nfbad="$nfbad ${NFNAMES[$i]}($b: rc=$rc nonfinite_max=${nfm:-?} nonFiniteRemoved=${rem:-0})"
        fi
    done
done
if [ -z "$nfbad" ]; then
    echo "== non-finite state removed within a step: ${#NFNAMES[@]} of ${#NFNAMES[@]} nf_* runs caught, native and wasm (--unchecked)"
else
    echo "== non-finite state removed within a step NOT caught:$nfbad"; GUARD_FAILED=1
fi
# Every live refusal (r_live_*) through the harness's own --set as well, native
# and wasm (tools/ocean_parity_driver.cpp applySet; the restart-only keys share
# ocean_config.hpp oceanRestartOnlyError with oc_set_param): each run must stop
# at its --set (exit 4) and print the state the refusal left, which must be,
# bit for bit (rng included), the state a run without the --set has at that
# step: nothing changed, nothing drawn.
lvbad=""; nlv=0
for i in "${!RNAMES[@]}"; do
    [[ ${RNAMES[$i]} == r_live_* ]] || continue
    read -r -a A <<< "${RARGS[$i]}"
    P=(); S=""
    for ((k = 0; k < ${#A[@]}; ++k)); do
        if [ "${A[$k]}" = --set ]; then S=${A[$((k + 1))]##*@}; k=$((k + 1)); else P+=("${A[$k]}"); fi
    done
    P[1]=$S   # SEED STEPS ...: the plain run stops where the --set would apply
    for b in native wasm; do
        f="$OUT/${RNAMES[$i]}.live_$b.txt"; g="$OUT/${RNAMES[$i]}.plain_$b.txt"
        if [ $b = native ]; then
            "$OUT/opd_native" "${A[@]}" --sparse > "$f" 2> /dev/null; rc=$?
            "$OUT/opd_native" "${P[@]}" --sparse --every "$S" > "$g" 2> /dev/null
        else
            $NODE "$OUT/opd_wasm.js" "${A[@]}" --sparse > "$f" 2> /dev/null; rc=$?
            $NODE "$OUT/opd_wasm.js" "${P[@]}" --sparse --every "$S" > "$g" 2> /dev/null
        fi
        ref=$(sed -n 's/^refused /fp /p' "$f"); plain=$(grep "^fp $S " "$g")
        if [ "$rc" != 4 ] || [ -z "$ref" ] || [ "$ref" != "$plain" ]; then
            lvbad="$lvbad ${RNAMES[$i]}($b: rc=$rc$([ -n "$ref" ] && [ "$ref" != "$plain" ] && echo ', state moved'))"
        fi
    done
    nlv=$((nlv + 1))
done
if [ -z "$lvbad" ]; then
    echo "== live refusals through the harness's --set: $nlv of $nlv r_live_* refused by both drivers, the state untouched"
else
    echo "== live refusals NOT refused (or the state moved) by the harness's --set:$lvbad"; GUARD_FAILED=1
fi
[ -n "$FAST_BAD" ] && GUARD_FAILED=1
# Baseline files without a case (a renamed or dropped case): stale history.
ORPHANS=""
if [ -z "${ONLY:-}" ] && [ -d "$BASE" ]; then
    for f in "$BASE"/*.txt; do
        [ -e "$f" ] || continue
        b=$(basename "$f" .txt); found=0
        for nm in "${NAMES[@]}"; do [ "$nm" = "$b" ] && found=1 && break; done
        [ "$found" = 1 ] || ORPHANS="$ORPHANS $b"
    done
    if [ -n "$ORPHANS" ]; then
        if [ "$REBASE" = 1 ]; then echo "== baselines with no case (removed by --overwrite):$ORPHANS"
        else echo "== baselines with no case (git rm them, or --rebaseline):$ORPHANS"; GUARD_FAILED=1; fi
    fi
fi
echo "== running ${#SEL[@]} case(s), $JOBS at a time (native and wasm side by side) in $OUT"
for i in "${SEL[@]}"; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    run_one "$i" &
done
wait

# The first differing line of EXPECTED and GOT, and what differs on it: for a
# fingerprint line the step and the sections, else the line's k=v keys.
first_diff () {  # first_diff EXPECTED GOT LABEL_OF_GOT
    local c ln la lb
    c=$(cmp "$1" "$2" 2>&1)
    ln=$(echo "$c" | sed -n 's/.*line \([0-9]*\).*/\1/p')
    if echo "$c" | grep -q EOF; then echo "$3 output $(echo "$c" | grep -q "EOF on $2" && echo ends || echo runs on) after line $ln"; return; fi
    [ -n "$ln" ] || { echo "(no line info)"; return; }
    la=$(sed -n "${ln}p" "$1"); lb=$(sed -n "${ln}p" "$2")
    echo "line $ln ($(echo "$la" | awk '{print ($1 == "fp") ? "step " $2 : "the " $1 " line"}')): $(paste -d'\t' <(echo "$la" | tr ' ' '\n') <(echo "$lb" | tr ' ' '\n') |
        awk -F'\t' '$1 != $2 { if ($1 ~ /=/) { split($1, k, "="); printf "%s ", k[1] } else if (!shown) { printf "value "; shown = 1 } }')differ"
}
secs_of () { sed -n 's/^# [0-9]* steps, \([0-9.]*\) s.*/\1/p' "$1" 2>/dev/null; }

FAILED=0; NPASS=0
CHANGED=(); declare -A CHANGE_WHY=()
printf '\n%-30s %6s %6s %5s %6s %5s %4s %7s %7s  %s\n' CASE SEED STEPS POP BIRTHS FOOD PRED NATIVE WASM RESULT
for i in "${SEL[@]}"; do
    name=${NAMES[$i]}
    read -r -a A <<< "${ARGS[$i]}"
    n="$OUT/$name.native.txt"; w="$OUT/$name.wasm.txt"; b="$BASE/$name.txt"
    fin=$(grep '^final ' "$n" 2>/dev/null)
    get () { echo "$fin" | tr ' ' '\n' | sed -n "s/^$1=//p"; }
    nfp=$(grep -c '^fp ' "$n" 2>/dev/null)
    rcn=$(cat "$OUT/$name.native.rc" 2>/dev/null); rcw=$(cat "$OUT/$name.wasm.rc" 2>/dev/null)
    ok=0
    if [ -n "${REFUSED[$i]:-}" ]; then
        res="FAIL  the page refuses this config: ${REFUSED[$i]}"
    elif [ "$rcn" = 5 ] && [ "$rcw" = 5 ]; then
        res="FAIL  expectation not met (the case did not reach its branch):$(sed -n 's/^expect \(.*\) FAILED \(.*\)/ \1 \2/p' "$n" | tr '\n' ' ')"
    elif [ "$rcn" != 0 ] || [ "$rcw" != 0 ]; then
        res="FAIL  exit native=$rcn wasm=$rcw: $(tail -1 "$OUT/$name.wasm.log" 2>/dev/null) $(tail -1 "$OUT/$name.native.log" 2>/dev/null)"
    elif [ -z "$fin" ]; then
        res="FAIL  no final line"
    elif [ "$(get nonfinite_max)" != 0 ]; then
        # Both builds may agree here and still not be portable: wasm leaves a
        # NaN's sign/payload to the host (x86 0xffc00000, ARM 0x7fc00000).
        rmv=$(grep '^cover ' "$n" | tr ' ' '\n' | sed -n 's/^nonFiniteRemoved=//p')
        res="FAIL  non-finite state from step $(get nonfinite_from) (up to $(get nonfinite_max) values${rmv:+; $rmv held by objects removed within a step})"
        cmp -s "$n" "$w" && res="$res; native == wasm on this host only"
    elif ! cmp -s "$n" "$w"; then
        res="FAIL  native != wasm: $(first_diff "$n" "$w" wasm)"
    else
        ok=1
    fi
    if [ "$ok" = 1 ]; then
        if [ ! -f "$b" ]; then
            why="no baseline yet ($b)"
        elif cmp -s "$n" "$b"; then
            why=""
        else
            why="differs from the baseline at $(first_diff "$b" "$n" native); $(diff "$b" "$n" | grep -c '^>') line(s) differ"
        fi
        if [ -z "$why" ]; then
            res="PASS  native == wasm == baseline ($nfp prints, every step chained)"; NPASS=$((NPASS + 1))
        elif [ "$REBASE" = 1 ]; then
            res="CHANGED  native == wasm, but $why"; CHANGED+=("$i"); CHANGE_WHY[$i]=$why
        else
            res="FAIL  native == wasm, but $why (an intended change? see --rebaseline; else a regression)"; FAILED=1
        fi
    else
        FAILED=1
    fi
    printf '%-30s %6s %6s %5s %6s %5s %4s %6ss %6ss  %s\n' "$name" "${A[0]}" "${A[1]}" "$(get pop)" "$(get births)" \
        "$(get food)" "$(get pred)" "$(secs_of "$OUT/$name.native.log")" "$(secs_of "$OUT/$name.wasm.log")" "$res"
done

# Same build, same arguments, twice: the native driver itself is reproducible
# (the first selected case of each build).
for v in $VARIANTS; do
    for i in "${SEL[@]}"; do
        name=${NAMES[$i]}
        [ "$(sfx "$name")" = "$([ $v = eye ] && echo _eye)" ] || continue
        read -r -a A <<< "${ARGS[$i]}"
        "$OUT/opd_native$(sfx "$name")" "${A[@]}" > "$OUT/$name.native2.txt" 2> /dev/null
        if cmp -s "$OUT/$name.native.txt" "$OUT/$name.native2.txt"; then
            echo "repeat: $name native run twice -> identical"
        else
            echo "repeat: $name native run twice -> DIFFERENT"; FAILED=1
        fi
        break
    done
done

# ---- appearance is cosmetic: each twin with {"appearance":0} must be the
# case's own output with every app* field removed, byte for byte (line 1, the
# header, names the cfg and so differs) ----
DEFAULT_TWINS="def_s1 gate_s29 cap_s31 x_tri_body_s9 fast_logs_s41 rich_s5 pred_s7 econ_s42 toro_bud_s43 pred_age_s23 live_s21 capture_s17 big_toro_s9 long_s42 e1_preset_s42 e1_size_s9 e1_live_s21 e1_x_big_s9 life_live_s21 eye_def_s1 eye_e1_capture_s17 eye_code7_big_s42 eye_only_exp_s3 eye_cloak_live_s21 eye_life_steer_only_s3 walls_e1_s42 walls_econ_s42"
TWINS=${APP_TWINS:-$DEFAULT_TWINS}
[ "$TWINS" = all ] && TWINS="${NAMES[*]}"
# The case's output minus its app* fields and its app* expectations.
app_strip () { sed -E '/^expect app/d; s/ app[A-Za-z]*=[^ ]*//g' "$1" | tail -n +2; }
twin_args () {  # twin_args ARGS -> the same with appearance 0 in its cfg and no app* expectations
    # A live `--set appearance=N@S` is a no-op only at the value the world was
    # built with (the driver refuses a change, exit 4): in the twin, built with
    # appearance 0, it becomes `appearance=0` (app_live_s21's appearance=3@2200;
    # the live-code audit of PRs #22-#25, finding 1).
    local a
    a=$(printf '%s\n' "$1" | sed -E 's/ --expect app[A-Za-z]*[<>=]+[0-9]+//g; s/--set appearance=[0-9.]+@/--set appearance=0@/g')
    if [[ $a == *'"appearance":'* ]]; then printf '%s\n' "$a" | sed -E 's/"appearance":[0-9]+/"appearance":0/'
    elif [[ $a == *"--cfg {"* ]]; then printf '%s\n' "$a" | sed 's/--cfg {/--cfg {"appearance":0,/'
    else printf '%s --cfg {"appearance":0}\n' "$a"; fi
}
NTWIN=0; TWIN_BAD=""
declare -A ISSEL=(); for i in "${SEL[@]}"; do ISSEL[$i]=1; done
twin_one () {  # twin_one INDEX
    local i=$1 name=${NAMES[$1]} s
    s=$(sfx "$name")
    local -a A
    read -r -a A <<< "$(twin_args "${ARGS[$i]}")"
    "$OUT/opd_native$s" "${A[@]}" > "$OUT/$name.off.txt" 2> "$OUT/$name.off.log"; echo $? > "$OUT/$name.off.rc"
}
TWIN_IDX=()
for i in "${!NAMES[@]}"; do
    [ -n "${ISSEL[$i]:-}" ] || continue
    for t in $TWINS; do [ "$t" = "${NAMES[$i]}" ] && TWIN_IDX+=("$i") && break; done
done
for i in "${TWIN_IDX[@]}"; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    twin_one "$i" &
done
wait
for i in "${TWIN_IDX[@]}"; do
    name=${NAMES[$i]}
    if [ "$(cat "$OUT/$name.off.rc" 2>/dev/null)" != "$(cat "$OUT/$name.native.rc" 2>/dev/null)" ]; then
        TWIN_BAD="$TWIN_BAD $name(exit)"
    elif ! cmp -s <(app_strip "$OUT/$name.native.txt") <(app_strip "$OUT/$name.off.txt"); then
        TWIN_BAD="$TWIN_BAD $name"
    else
        NTWIN=$((NTWIN + 1))
    fi
done
if [ ${#TWIN_IDX[@]} -gt 0 ]; then
    if [ -z "$TWIN_BAD" ]; then
        echo "== appearance is cosmetic: $NTWIN of ${#TWIN_IDX[@]} case(s) with appearance off == with it on minus its app* fields (every section, all, chain, counters, final line)"
    else
        echo "== appearance CHANGED THE SIMULATION in:$TWIN_BAD (diff <(sed -E 's/ app[A-Za-z]*=[^ ]*//g' X.native.txt) X.off.txt in $OUT)"; FAILED=1
    fi
fi

TESTS_OK=1
if [ -z "${NO_TESTS:-}" ]; then
    for v in $VARIANTS; do
        S=; [ $v = eye ] && S=_eye
        echo
        echo "== unit checks (tests/ocean_tests.cpp), $v build, native"
        "$OUT/ocean_tests_native$S" > "$OUT/tests$S.native.txt" 2>&1; rct=$?
        cat "$OUT/tests$S.native.txt"
        echo "== unit checks, $v build, wasm (node)"
        $NODE "$OUT/ocean_tests_wasm$S.js" > "$OUT/tests$S.wasm.txt" 2>&1; rcw=$?
        tail -1 "$OUT/tests$S.wasm.txt"
        if [ $rct != 0 ] || [ $rcw != 0 ]; then TESTS_OK=0; echo "   unit checks FAILED (native rc $rct, wasm rc $rcw)"; fi
        if cmp -s "$OUT/tests$S.native.txt" "$OUT/tests$S.wasm.txt"; then
            echo "   unit-check output native == wasm (every printed value identical)"
        else
            echo "   unit-check output differs native vs wasm:"; diff "$OUT/tests$S.native.txt" "$OUT/tests$S.wasm.txt" | head -20; TESTS_OK=0
        fi
    done
fi

echo
echo "== $(( $(date +%s) - T0 )) s total"
if [ "$REBASE" = 1 ]; then
    echo "== rebaseline: ${#CHANGED[@]} case(s) differ from their baseline or have none${ORPHANS:+; orphans:$ORPHANS}"
    for i in "${CHANGED[@]}"; do echo "   ${NAMES[$i]}: ${CHANGE_WHY[$i]}"; done
    if [ ${#CHANGED[@]} -eq 0 ] && [ -z "$ORPHANS" ]; then
        echo "   nothing to write"
    elif [ "$OVERWRITE" = 0 ]; then
        echo "   DRY RUN: nothing written. If (and only if) these changes are the behaviour you meant, record them:"
        echo "     $0 --rebaseline --overwrite --reason \"what changed and why\""
    elif [ "$FAILED" = 1 ] || [ "$TESTS_OK" = 0 ] || [ "$GUARD_FAILED" = 1 ]; then
        echo "   REFUSED: every case must pass native == wasm and its expectations, the unit checks must pass and"
        echo "   no guard may fail before a baseline is written (fix the failures above first)"
        exit 1
    else
        # Every write is checked. All new files (the baselines and the
        # MANIFEST with its new entry) are first staged in $BASE/.rebaseline.*
        # (same filesystem), so a full disk or a read-only directory fails
        # there with nothing replaced; then each is moved into place, checked.
        mkdir -p "$BASE" || { echo "   FAILED: cannot create $BASE; nothing written"; exit 1; }
        STAGE=$(mktemp -d "$BASE/.rebaseline.XXXXXX") || { echo "   FAILED: cannot create a staging directory in $BASE; nothing written"; exit 1; }
        stage_fail () { echo "   FAILED: $1; nothing written to $BASE"; rm -rf "$STAGE"; exit 1; }
        names=""
        for i in "${CHANGED[@]}"; do
            cp "$OUT/${NAMES[$i]}.native.txt" "$STAGE/${NAMES[$i]}.txt" || stage_fail "cannot stage ${NAMES[$i]}.txt"
            names="$names ${NAMES[$i]}"
        done
        fmt=$(sed -n '1s/.*format=\([0-9]*\).*/\1/p' "$OUT/${NAMES[${SEL[0]}]}.native.txt")
        dirty=$(git status --porcelain -- src wasm/ocean_wasm.cpp 2>/dev/null | wc -l)
        if [ -f "$BASE/MANIFEST" ]; then
            cp "$BASE/MANIFEST" "$STAGE/MANIFEST" || stage_fail "cannot stage MANIFEST"
        else
            cat > "$STAGE/MANIFEST" << 'EOF' || stage_fail "cannot write a new MANIFEST"
tests/ocean_baseline — the Ocean determinism harness's historical oracle.

<case>.txt is ocean_parity_driver's native output for that case of
wasm/ocean_parity.sh (whose wasm output must equal it too): the fingerprint of
the whole world every 100 / 250 steps, the rolling chain over every step, the
coverage counters, the expectations, the final line. wasm/ocean_parity.sh fails
any case whose output differs from its file here, so a change to shared
behaviour that native and wasm make identically (they are built from the same
source) still fails.

Rewrite these files ONLY with `wasm/ocean_parity.sh --rebaseline --overwrite
--reason "..."`, ONLY when behaviour is MEANT to change (a deliberate engine
change, a new or edited case, a change to what the harness hashes — then bump
ofp::kFormatVersion), and NEVER to make a failure go away. Commit them with
the change that moved them. Each rewrite is logged below (newest last).

EOF
        fi
        {
            echo "$(date -u +%Y-%m-%dT%H:%MZ)  engine $(git rev-parse --short HEAD 2>/dev/null)$( [ "$dirty" -gt 0 ] && echo " + $dirty uncommitted engine path(s)" )  format=$fmt  g++ $GPP_VER / $EM_VER"
            echo "  reason: $REASON"
            echo "  wrote:$names${ORPHANS:+; removed:$ORPHANS}"
        } >> "$STAGE/MANIFEST" || stage_fail "cannot append the entry to the staged MANIFEST"
        # Staged: now replace. A failure from here on can leave the set partly
        # rewritten; say so, and how to undo it.
        moved=0
        place_fail () {
            echo "   FAILED: $1, after $moved of the baseline file(s) were replaced: $BASE may be PARTLY rewritten" \
                 "and the MANIFEST may not record it. Restore it: git checkout -- $BASE (staging kept in $STAGE)"
            exit 1
        }
        for i in "${CHANGED[@]}"; do
            mv -f "$STAGE/${NAMES[$i]}.txt" "$BASE/${NAMES[$i]}.txt" || place_fail "cannot replace $BASE/${NAMES[$i]}.txt"
            moved=$((moved + 1))
        done
        for o in $ORPHANS; do
            rm -f "$BASE/$o.txt" && [ ! -e "$BASE/$o.txt" ] || place_fail "cannot remove the orphan $BASE/$o.txt"
        done
        mv -f "$STAGE/MANIFEST" "$BASE/MANIFEST" || place_fail "cannot replace $BASE/MANIFEST"
        rmdir "$STAGE" || echo "   (could not remove the empty staging directory $STAGE)"
        echo "   WROTE ${#CHANGED[@]} baseline(s) to $BASE and logged them in $BASE/MANIFEST."
        echo "   Read the diff before committing: git diff --stat $BASE; git diff $BASE/MANIFEST"
    fi
    [ "$FAILED" = 1 ] || [ "$TESTS_OK" = 0 ] || [ "$GUARD_FAILED" = 1 ] && { echo "== (parity / unit / guard failures above)"; exit 1; }
    exit 0
fi
if [ "$FAILED" = 1 ] || [ "$TESTS_OK" = 0 ] || [ "$GUARD_FAILED" = 1 ]; then
    [ "$FAILED" = 1 ] && echo "== OCEAN PARITY FAILED: bisect with --trace, then --dump-step/--dump (native vs wasm, or old vs new engine)"
    [ "$TESTS_OK" = 0 ] && echo "== OCEAN UNIT CHECKS FAILED"
    [ "$GUARD_FAILED" = 1 ] && echo "== OCEAN CONFIG GUARDS FAILED (a bad config accepted, the E1 preset copy or the int- / bool-key lists drifted, an orphan baseline, or removed non-finite state not caught)"
    exit 1
fi
if [ -n "${NO_TESTS:-}" ]; then
    echo "== ALL $NPASS OCEAN PARITY CASES PASS: native == wasm == baseline, bit for bit, every step; expectations met;" \
         "unit checks, shim validation and config guards NOT run (NO_TESTS)"
    exit 0
fi
echo "== ALL $NPASS OCEAN PARITY CASES PASS${FAST:+ (the FAST subset, of ${#NAMES[@]})}: native == wasm == baseline, bit for bit," \
     "every step; expectations met; unit checks pass in both builds"
