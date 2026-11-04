#!/bin/bash
# build_engine.sh OUT [--arch x86-64-v3] [--lto] [--pgo ARENA.json ...] [--train-steps N] [--epoch S] [--jobs N]
#
# Build the serial Classic engine (the evo_boids app, EVO_NO_OPENMP=ON, Release) for a study, from a clean
# commit of this repository, reproducibly, and write OUT (the binary) and OUT.build.json (how it was made).
#
#   (no options)        the default serial build: what every study so far has pinned
#   --arch x86-64-v3    AVX2 code with -mno-fma (CMakeLists.txt, EVO_NATIVE_ARCH)
#   --lto               link-time optimisation (EVO_LTO)
#   --pgo ARENA...      profile-guided optimisation: build with -fprofile-generate, run each ARENA checkpoint
#                       headless (--train-steps, default 4000, with every output the cells write: CSV,
#                       birth log, periodic and final checkpoints), then rebuild with -fprofile-use. Train on
#                       arenas that are NOT the ones the binary will be judged on. NOT for a study binary:
#                       two PGO builds of the same inputs came out different (g++ 13.3), and it ran 6.5%
#                       SLOWER than --arch x86-64-v3 --lto (docs/throughput.md); kept for experiments
#   --epoch S           SOURCE_DATE_EPOCH (the "built ..." stamp the binary prints); default: the commit's time.
#                       Same commit + compiler + options + epoch = the same bytes (without --pgo)
#   --rev REV           the commit to build (default HEAD); the build uses `git archive REV`, never the
#                       working tree, so uncommitted edits cannot reach a study binary
#
# The binary is refused (exit 1) if it contains a fused multiply-add instruction. It is NOT a study binary
# until tools/invasion/identity.py has shown it byte-identical to the study's pinned binary on real cells
# (docs/throughput.md, "Registering a new engine binary"). Everything runs at nice 19; --jobs (default 2)
# bounds the compiler.
set -euo pipefail
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage
OUT=$(realpath -m "$1"); shift
ARCH=""; LTO=OFF; PGO=(); STEPS=4000; EPOCH=""; JOBS=2; REV=HEAD
while [ $# -gt 0 ]; do
  case "$1" in
    --arch) ARCH=$2; shift 2 ;;
    --lto) LTO=ON; shift ;;
    --pgo) shift; while [ $# -gt 0 ] && [[ $1 != --* ]]; do PGO+=("$(realpath "$1")"); shift; done
           [ ${#PGO[@]} -gt 0 ] || { echo "--pgo needs at least one arena checkpoint" >&2; exit 2; } ;;
    --train-steps) STEPS=$2; shift 2 ;;
    --epoch) EPOCH=$2; shift 2 ;;
    --jobs) JOBS=$2; shift 2 ;;
    --rev) REV=$2; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown argument $1" >&2; usage ;;
  esac
done
REPO=$(cd "$(dirname "$0")/../.." && pwd)
COMMIT=$(git -C "$REPO" rev-parse --verify "$REV^{commit}")
[ -n "$EPOCH" ] || EPOCH=$(git -C "$REPO" log -1 --format=%ct "$COMMIT")
export SOURCE_DATE_EPOCH=$EPOCH
[ -e "$OUT" ] && { echo "$OUT exists: refusing to overwrite a binary" >&2; exit 2; }
# A FIXED work path, not mktemp, so nothing path-dependent can vary between two builds (the non-PGO
# builds came out the same from different paths anyway; PGO builds differ even with the path fixed).
# One build at a time (the lock); the directory is removed afterwards.
W=/tmp/finfolk_build_engine
exec 9> "$W.lock"
flock -n 9 || { echo "another build_engine.sh holds $W.lock" >&2; exit 2; }
rm -rf "$W"; mkdir -p "$W"
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/src" "$W/train"
git -C "$REPO" archive "$COMMIT" | tar -x -C "$W/src"
B=$W/build   # one build directory for both PGO passes: the profile is keyed by the object paths
OPTS=(-DCMAKE_BUILD_TYPE=Release -DEVO_NO_OPENMP=ON -DEVO_LTO=$LTO)
[ -n "$ARCH" ] && OPTS+=(-DEVO_NATIVE_ARCH="$ARCH")
build() {  # build PGO_MODE
  nice -n 19 cmake -S "$W/src" -B "$B" "${OPTS[@]}" -DEVO_PGO="$1" -DEVO_PGO_DIR="$W/pgo" > "$W/cmake_$1.log" 2>&1 \
    || { cat "$W/cmake_$1.log"; exit 1; }
  nice -n 19 cmake --build "$B" --target evo_boids --clean-first -j "$JOBS" > "$W/build_$1.log" 2>&1 \
    || { tail -40 "$W/build_$1.log"; exit 1; }
}
TRAIN_JSON="[]"
if [ ${#PGO[@]} -gt 0 ]; then
  build generate
  TRAIN_JSON="["
  i=0
  for a in "${PGO[@]}"; do
    d=$W/train/$i; mkdir -p "$d"; cp "$a" "$d/arena.json"
    (cd "$d" && nice -n 19 "$B/evo_boids" --load-checkpoint arena.json --reseed-after-load $((i + 1)) \
        --headless "$STEPS" --no-render --log-every 1000 --csv run.csv --repro-log --repro-log-max 100000000 \
        --save-checkpoint end.json --checkpoint-every $((STEPS / 2)) > stdout.log 2>&1) \
      || { echo "training run on $a failed"; tail "$d/stdout.log"; exit 1; }
    [ $i -gt 0 ] && TRAIN_JSON+=","
    TRAIN_JSON+="{\"arena\":\"$a\",\"sha256\":\"$(sha256sum "$a" | cut -d' ' -f1)\",\"reseed\":$((i + 1)),\"steps\":$STEPS}"
    i=$((i + 1))
  done
  TRAIN_JSON+="]"
  NGCDA=$(find "$W/pgo" -name '*.gcda' 2>/dev/null | wc -l)
  [ "$NGCDA" -gt 0 ] || { echo "the training runs wrote no profile (*.gcda) under $W/pgo" >&2; exit 1; }
  echo "profile: $NGCDA .gcda file(s)"
  build use
else
  build ""
fi
FMA=$(objdump -d "$B/evo_boids" | grep -cE '\svf(n)?m(add|sub)' || true)   # vfmadd*, vfmsub*, vfnmadd*, vfnmsub*, vfmaddsub*
if [ "$FMA" != 0 ]; then echo "REFUSED: $FMA fused multiply-add instructions in the binary" >&2; exit 1; fi
cp "$B/evo_boids" "$OUT"
SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
FLAGS=$(grep -h "throughput build" "$W"/cmake_*.log | tail -1 | sed 's/^-- throughput build: //' || true)
cat > "$OUT.build.json" <<EOF
{
 "schema": "finfolk.engine.build/1",
 "binary": "$OUT",
 "sha256": "$SHA",
 "commit": "$COMMIT",
 "cmake": "$(echo "${OPTS[@]}")",
 "extra_flags": "$FLAGS",
 "compiler": "$(g++ --version | head -1)",
 "source_date_epoch": $EPOCH,
 "pgo_training": $TRAIN_JSON,
 "fma_instructions": 0,
 "version": "$("$OUT" --version 2>&1 | head -1)",
 "built_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo "$SHA  $OUT"
