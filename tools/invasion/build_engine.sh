#!/bin/bash
# build_engine.sh OUT [--arch x86-64-v3] [--lto] [--pgo ARENA.json ...] [--train-steps N] [--epoch S]
#                     [--rev REV] [--cxx PATH] [--jobs N]
#
# Build the serial Classic engine (the evo_boids app, EVO_NO_OPENMP=ON, Release) for a study, from a clean
# commit of this repository, reproducibly, and write OUT (the binary) and OUT.build.json (how it was made).
#
#   (no options)        the default serial build: what every study so far has pinned
#   --arch LEVEL        x86-64, x86-64-v2 or x86-64-v3 (CMakeLists.txt EVO_NATIVE_ARCH, always with -mno-fma).
#                       Only these named levels: "native" (the build host's CPU) and v4 (AVX-512) are refused
#   --lto               link-time optimisation (EVO_LTO)
#   --pgo ARENA...      profile-guided optimisation: build with -fprofile-generate, run each ARENA checkpoint
#                       headless (--train-steps, default 4000, with every output the cells write: CSV,
#                       birth log, periodic and final checkpoints), then rebuild with -fprofile-use. Train on
#                       arenas that are NOT the ones the binary will be judged on. NOT for a study binary:
#                       two PGO builds of the same inputs came out different (g++ 13.3), and it ran 6.5%
#                       SLOWER than --arch x86-64-v3 --lto (docs/throughput.md); kept for experiments
#   --epoch S           SOURCE_DATE_EPOCH (the "built ..." stamp the binary prints); default: the commit's time.
#                       Same commit + toolchain + options + epoch = the same bytes (without --pgo). A different
#                       epoch is a different binary: register the bytes identity.py tested, not a rebuild
#   --rev REV           the commit to build (default HEAD); the build uses `git archive REV`, never the
#                       working tree, so uncommitted edits cannot reach a study binary
#   --cxx PATH          the C++ compiler (default /usr/bin/c++, what the pinned studies used), passed to CMake
#                       explicitly; CXXFLAGS, CFLAGS, CPPFLAGS, LDFLAGS, CXX, CC and CMAKE_GENERATOR are unset
#
# Refused (exit 1): a requested option the commit's CMakeLists.txt does not apply (its "throughput build:"
# line must name exactly the expected flags; with no option there must be none), and a binary containing a
# fused multiply-add or an approximate reciprocal (rcp / rsqrt) instruction, or one objdump cannot read.
# OUT.build.json records the commit, the options, the compile and link lines CMake generated, the toolchain
# (compiler path and version, cmake, binutils, glibc, libstdc++, SFML), the epoch and the sha256.
# The binary is NOT a study binary until tools/invasion/identity.py has shown it byte-identical to the
# study's pinned binary on real cells (docs/throughput.md, "Registering a new engine binary"). Everything
# runs at nice 19; --jobs (default 2) bounds the compiler.
set -euo pipefail
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage
OUT=$(realpath -m "$1"); shift
ARCH=""; LTO=OFF; PGO=(); STEPS=4000; EPOCH=""; JOBS=2; REV=HEAD; CXX_PATH=/usr/bin/c++
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
    --cxx) CXX_PATH=$2; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown argument $1" >&2; usage ;;
  esac
done
case "$ARCH" in
  ""|x86-64|x86-64-v2|x86-64-v3) ;;
  *) echo "--arch $ARCH refused: only x86-64, x86-64-v2 or x86-64-v3 (a named, portable level; never 'native')" >&2
     exit 2 ;;
esac
# the build sees only what this script passes: no flags or compiler from the caller's environment
unset CXXFLAGS CFLAGS CPPFLAGS LDFLAGS CXX CC CMAKE_GENERATOR
[ -x "$CXX_PATH" ] || { echo "--cxx $CXX_PATH is not an executable" >&2; exit 2; }
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
OPTS=(-DCMAKE_BUILD_TYPE=Release -DEVO_NO_OPENMP=ON -DEVO_LTO=$LTO -DCMAKE_CXX_COMPILER="$CXX_PATH")
[ -n "$ARCH" ] && OPTS+=(-DEVO_NATIVE_ARCH="$ARCH")
expected() {  # expected PGO_MODE -> the "throughput build:" flag list CMakeLists.txt must report ("" = none)
  local f=()
  [ -n "$ARCH" ] && f+=("-march=$ARCH" -mno-fma)
  [ "$LTO" = ON ] && f+=(-flto=auto)
  [ "$1" = generate ] && f+=(-fprofile-generate "-fprofile-dir=$W/pgo" -fprofile-update=single)
  [ "$1" = use ] && f+=(-fprofile-use "-fprofile-dir=$W/pgo" -fprofile-partial-training -Wno-missing-profile)
  local IFS=';'; echo "${f[*]}"
}
build() {  # build PGO_MODE
  nice -n 19 cmake -S "$W/src" -B "$B" "${OPTS[@]}" -DEVO_PGO="$1" -DEVO_PGO_DIR="$W/pgo" > "$W/cmake_$1.log" 2>&1 \
    || { cat "$W/cmake_$1.log"; exit 1; }
  # the commit must really apply what was asked: a CMakeLists.txt without these options ignores them and
  # would build the baseline under a record that claims the flags (review of #51, P2-1)
  local want got
  want=$(expected "$1")
  got=$(grep -h '^-- throughput build: ' "$W/cmake_$1.log" | sed 's/^-- throughput build: //' || true)
  if [ "$got" != "$want" ]; then
    echo "REFUSED: commit ${COMMIT:0:12} applies '${got:-no throughput flags}', expected '${want:-no throughput flags}'" >&2
    exit 1
  fi
  nice -n 19 cmake --build "$B" --target evo_boids --clean-first -j "$JOBS" > "$W/build_$1.log" 2>&1 \
    || { tail -40 "$W/build_$1.log"; exit 1; }
}
TRAIN=()
if [ ${#PGO[@]} -gt 0 ]; then
  build generate
  i=0
  for a in "${PGO[@]}"; do
    d=$W/train/$i; mkdir -p "$d"; cp "$a" "$d/arena.json"
    (cd "$d" && nice -n 19 "$B/evo_boids" --load-checkpoint arena.json --reseed-after-load $((i + 1)) \
        --headless "$STEPS" --no-render --log-every 1000 --csv run.csv --repro-log --repro-log-max 100000000 \
        --save-checkpoint end.json --checkpoint-every $((STEPS / 2)) > stdout.log 2>&1) \
      || { echo "training run on $a failed"; tail "$d/stdout.log"; exit 1; }
    TRAIN+=("$a" "$(sha256sum "$a" | cut -d' ' -f1)" "$((i + 1))")
    i=$((i + 1))
  done
  NGCDA=$(find "$W/pgo" -name '*.gcda' 2>/dev/null | wc -l)
  [ "$NGCDA" -gt 0 ] || { echo "the training runs wrote no profile (*.gcda) under $W/pgo" >&2; exit 1; }
  echo "profile: $NGCDA .gcda file(s)"
  build use
else
  build ""
fi
objdump -d "$B/evo_boids" > "$W/disasm.txt" || { echo "REFUSED: objdump could not disassemble the binary" >&2; exit 1; }
[ -s "$W/disasm.txt" ] || { echo "REFUSED: objdump produced nothing" >&2; exit 1; }
# fused multiply-add (vfmadd*, vfmsub*, vfnmadd*, vfnmsub*, vfmaddsub*) and approximate reciprocals
# (rcpps/rcpss/rsqrtps/rsqrtss and their v / AVX-512 forms): none may appear
BAD=$(grep -cE '\s(vf(n)?m(add|sub)|v?rcp[0-9]*[ps]s|v?rsqrt[0-9]*[ps]s)\b' "$W/disasm.txt" || true)
if [ "$BAD" != 0 ]; then
  echo "REFUSED: $BAD fused multiply-add / approximate reciprocal instruction(s) in the binary:" >&2
  grep -E '\s(vf(n)?m(add|sub)|v?rcp[0-9]*[ps]s|v?rsqrt[0-9]*[ps]s)\b' "$W/disasm.txt" | head -5 >&2
  exit 1
fi
cp "$B/evo_boids" "$OUT"
pkgver() { dpkg-query -W -f='${Version}' "$1" 2>/dev/null || echo unknown; }
CXX_ID=$(grep -h 'set(CMAKE_CXX_COMPILER_VERSION ' "$B"/CMakeFiles/*/CMakeCXXCompiler.cmake | sed -E 's/.*"(.*)".*/\1/')
OUT="$OUT" COMMIT="$COMMIT" EPOCH="$EPOCH" ARCH="$ARCH" LTO="$LTO" \
CMAKE_OPTS="${OPTS[*]}" FLAGS_MAKE="$(cat "$B/CMakeFiles/evo_boids.dir/flags.make")" \
LINK_TXT="$(cat "$B/CMakeFiles/evo_boids.dir/link.txt")" \
CACHE_CXX="$(grep -h '^CMAKE_CXX_COMPILER:' "$B/CMakeCache.txt" | cut -d= -f2-)" CXX_REAL="$(readlink -f "$CXX_PATH")" \
CXX_VERSION="$CXX_ID" CXX_BANNER="$("$CXX_PATH" --version | head -1)" CMAKE_VERSION="$(cmake --version | head -1)" \
LD_VERSION="$(ld --version | head -1)" GLIBC="$(getconf GNU_LIBC_VERSION) ($(pkgver libc6))" \
LIBSTDCXX="$(pkgver libstdc++6)" SFML="$(grep -h '^SFML_DIR:' "$B/CMakeCache.txt" | cut -d= -f2-) ($(pkgver libsfml-dev))" \
THROUGHPUT="$(grep -h '^-- throughput build: ' "$W"/cmake_*.log | tail -1 | sed 's/^-- throughput build: //' || true)" \
python3 -I - "${TRAIN[@]}" <<'PY'
import hashlib, json, os, subprocess, sys, datetime
e = os.environ
out = e["OUT"]
t = sys.argv[1:]
rec = {
    "schema": "finfolk.engine.build/2",
    "binary": out,
    "sha256": hashlib.sha256(open(out, "rb").read()).hexdigest(),
    "commit": e["COMMIT"],
    "options": {"arch": e["ARCH"] or None, "lto": e["LTO"] == "ON", "pgo": bool(t)},
    "cmake_options": e["CMAKE_OPTS"],
    "throughput_flags_applied": e["THROUGHPUT"] or None,
    "compile": e["FLAGS_MAKE"].strip().splitlines(),
    "link": e["LINK_TXT"].strip(),
    "toolchain": {"cxx": e["CACHE_CXX"], "cxx_resolved": e["CXX_REAL"], "cxx_version": e["CXX_VERSION"],
                  "cxx_banner": e["CXX_BANNER"], "cmake": e["CMAKE_VERSION"], "ld": e["LD_VERSION"],
                  "glibc": e["GLIBC"], "libstdc++": e["LIBSTDCXX"], "sfml": e["SFML"]},
    "source_date_epoch": int(e["EPOCH"]),
    "pgo_training": [{"arena": t[i], "sha256": t[i + 1], "reseed": int(t[i + 2])} for i in range(0, len(t), 3)],
    "fma_or_approx_reciprocal_instructions": 0,
    "version": subprocess.run([out, "--version"], capture_output=True, text=True).stdout.strip().splitlines()[0],
    "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
with open(out + ".build.json", "w") as f:
    f.write(json.dumps(rec, indent=1, sort_keys=True) + "\n")
print(f"{rec['sha256']}  {out}")
PY
