#!/usr/bin/env bash
# reseed_after_load.sh — end-to-end test of the CLI flag --reseed-after-load S
# (src/app/main.cpp), run by ctest in the serial build only (a resume is
# bit-exact only there; see checkpoint_io.hpp).
#
#   tests/reseed_after_load.sh PATH/TO/evo_boids WORKDIR
#
# Asserts:
#   1. no flag = the old behaviour: 300 steps + resume + 300 steps writes the
#      same bytes as 600 steps in one go (the exact-resume contract);
#   2. the same S twice reproduces bit for bit;
#   3. two different S diverge, and not only in the saved rng state (the
#      creatures themselves differ), and S differs from the exact resume;
#   4. the flag is refused without --load-checkpoint.
set -u
BIN=${1:?usage: reseed_after_load.sh EVO_BOIDS WORKDIR}
W=${2:?usage: reseed_after_load.sh EVO_BOIDS WORKDIR}
rm -rf "$W"; mkdir -p "$W"; cd "$W" || exit 2
fail() { echo "FAIL: $*" >&2; exit 1; }
run() { "$BIN" --no-render --population 120 --log-every 100 "$@" > /dev/null 2>&1 || fail "evo_boids $* exited $?"; }
# A checkpoint minus its rng-state line: what is left is the world itself.
world_only() { grep -v '"rngState"' "$1"; }

run --headless 300 --seed 11 --save-checkpoint base.json
run --headless 600 --seed 11 --save-checkpoint full.json
run --headless 300 --load-checkpoint base.json --save-checkpoint plain.json
cmp -s full.json plain.json || fail "no flag: 300 + resume + 300 differs from 600 in one go"

run --headless 300 --load-checkpoint base.json --reseed-after-load 1 --save-checkpoint r1a.json
run --headless 300 --load-checkpoint base.json --reseed-after-load 1 --save-checkpoint r1b.json
run --headless 300 --load-checkpoint base.json --reseed-after-load 2 --save-checkpoint r2.json
cmp -s r1a.json r1b.json || fail "same S twice is not bit-identical"
cmp -s r1a.json r2.json && fail "S=1 and S=2 produced the same bytes"
[ "$(world_only r1a.json)" != "$(world_only r2.json)" ] || fail "S=1 and S=2 differ only in the rng state"
[ "$(world_only r1a.json)" != "$(world_only plain.json)" ] || fail "S=1 is the exact resume"

# The reseeded end state is an ordinary checkpoint: it resumes exactly.
run --headless 100 --load-checkpoint r1a.json --save-checkpoint r1a_more.json
run --headless 100 --load-checkpoint r1a.json --save-checkpoint r1a_more2.json
cmp -s r1a_more.json r1a_more2.json || fail "a reseeded end checkpoint does not resume exactly"

if "$BIN" --no-render --headless 10 --reseed-after-load 3 > /dev/null 2>&1; then
    fail "--reseed-after-load without --load-checkpoint was accepted"
fi

# --checkpoint-every next to a bare --save-checkpoint file name (no directory)
# used to throw from create_directories(""); the periodic files land beside it.
run --headless 200 --load-checkpoint base.json --save-checkpoint bare.json --checkpoint-every 100
[ -f bare.400.json ] && [ -f bare.500.json ] && [ -f bare.json ] || fail "--checkpoint-every with a bare file name"
cmp -s bare.500.json bare.json || fail "the last periodic checkpoint differs from the end checkpoint"
echo "reseed_after_load: ok"
