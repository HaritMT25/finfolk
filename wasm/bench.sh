#!/bin/bash
# bench.sh — step time at a fixed creature count: native serial, native OpenMP,
# wasm single-threaded and wasm threaded, all from wasm/bench_fixed.cpp.
#
# Prereq: source ~/emsdk/emsdk_env.sh. Wasm runs use the emsdk Node ($EMSDK_NODE),
# the same V8 as Chrome. Each cell is the median of REPS runs, each of which is
# the median of 5 timed blocks. Plug the machine in; battery power throttles.
#
# usage: wasm/bench.sh [N list] [thread list]   (defaults below)
set -euo pipefail
cd "$(dirname "$0")/.."

NS=${1:-"500 1000 2000 4000"}
TS=${2:-"2 4 8"}
REPS=${REPS:-3}
WARM=${WARM:-300}
MEASURE=${MEASURE:-1000}
NODE=${EMSDK_NODE:-node}
# a unique dir per run (two worktrees can bench at once, though timings need a quiet machine); BENCH_DIR reuses one.
# Removed on success unless KEEP_OUT=1 (raw.txt is in it); kept on failure; an explicit BENCH_DIR is never removed.
if [ -n "${BENCH_DIR:-}" ]; then OUT=$BENCH_DIR; mkdir -p "$OUT"
else
    OUT=$(mktemp -d /tmp/evo_bench.XXXXXX)
    if [ -z "${KEEP_OUT:-}" ]; then trap 'rc=$?; if [ $rc = 0 ]; then rm -rf "$OUT"; else echo "== kept $OUT (run did not pass)" >&2; fi' EXIT; fi
fi
echo "== outputs in $OUT"

CXX="-O3 -std=c++20 -ffp-contract=off -I src wasm/bench_fixed.cpp"
echo "== building"
g++ $CXX -o "$OUT/native_serial"
g++ $CXX -fopenmp -DUSE_OPENMP -o "$OUT/native_omp"
em++ $CXX -msimd128 -sENVIRONMENT=node -sALLOW_MEMORY_GROWTH=1 -sEXIT_RUNTIME=1 -o "$OUT/wasm_st.js"
em++ $CXX -msimd128 -pthread -DEVO_POOL_THREADS -sENVIRONMENT=node -sEXIT_RUNTIME=1 \
     -sPTHREAD_POOL_SIZE=7 -sINITIAL_MEMORY=134217728 -sALLOW_MEMORY_GROWTH=1 \
     -o "$OUT/wasm_mt.js" 2>/dev/null

median() { sort -n | awk '{a[NR]=$1} END {print a[int((NR+1)/2)]}'; }
run() {  # label, command... -> median ms/step over REPS
    local label=$1; shift
    local v
    v=$(for r in $(seq "$REPS"); do "$@" | sed -n 's/.*ms_per_step=\([0-9.]*\).*/\1/p'; done | median)
    echo "$label $v" >> "$OUT/raw.txt"
    echo "$v"
}

: > "$OUT/raw.txt"
echo "== machine"
lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core' | sed 's/^/   /'
echo "   node $($NODE --version), $(g++ --version | head -1), $(em++ --version | head -1 | cut -c1-60)"
echo
header="| creatures | native 1 thread |"
sep="|---:|---:|"
for t in $TS; do header="$header native OpenMP $t |"; sep="$sep---:|"; done
header="$header wasm 1 thread |"; sep="$sep---:|"
for t in $TS; do header="$header wasm threaded $t |"; sep="$sep---:|"; done
echo "ms per step (lower is better)"
echo "$header"
echo "$sep"
for n in $NS; do
    row="| $n | $(run "native1 $n" "$OUT/native_serial" "$n" 1 "$WARM" "$MEASURE") |"
    for t in $TS; do row="$row $(run "omp$t $n" "$OUT/native_omp" "$n" "$t" "$WARM" "$MEASURE") |"; done
    row="$row $(run "wasm1 $n" "$NODE" "$OUT/wasm_st.js" "$n" 1 "$WARM" "$MEASURE") |"
    for t in $TS; do row="$row $(run "wasmmt$t $n" "$NODE" "$OUT/wasm_mt.js" "$n" "$t" "$WARM" "$MEASURE") |"; done
    echo "$row"
done
