#!/bin/bash
# identity_base_head.sh BASE_BIN HEAD_BIN WORKDIR: the engine-identity evidence for an engine change that
# must leave every existing path bit-identical (Codex #74 r1). Both binaries (serial builds, the same flags)
# run the same scenarios: Classic, Stage A / B / C histories with a mid-run resume, and transplants from a
# Stage C and a Stage B prey world, checkpoint and random sources, in all three assay modes, each arena then
# run with periodic checkpoints. Every output file (checkpoints with their RNG states, arenas, manifests, the
# main CSV without its two timing columns, the run sidecar <stem>.config.txt without its build timestamp
# "(built __DATE__ __TIME__)", the predator and lineage logs) is hashed; the two manifests must
# be equal, and within each binary a resumed history must equal the uninterrupted one. Exit 0 = identical.
set -u
BASE=$(readlink -f "${1:?usage: identity_base_head.sh BASE_BIN HEAD_BIN WORKDIR}")
HEAD=$(readlink -f "${2:?}")
W=${3:?}
[ -x "$BASE" ] && [ -x "$HEAD" ] || { echo "FAIL: $BASE or $HEAD is not an executable" >&2; exit 2; }
rm -rf "$W"; mkdir -p "$W"
W=$(readlink -f "$W")
# (the economy of tests/redqueen_tooling.sh's tiny Stage C worlds; the floor keeps the donor's predators)
ECON="--predator-economy --predator-meal 14 --predator-max-pop 12 --predator-min-pop 2 --predator-max-age 15"
run_all() {   # $1 binary, $2 directory
    local B=$1 D=$2
    mkdir -p "$D"; cd "$D" || exit 2
    e() { "$B" --no-render --log-every 250 "$@" > /dev/null 2>&1 || { echo "FAIL: $B $*" >&2; exit 1; }; }
    for spec in "classic:" "stageA:--predators 4" "stageB:--predators 6 $ECON" \
                "stageC:--predators 6 $ECON --predator-brain --predator-log"; do
        n=${spec%%:*}; f=${spec#*:}
        mkdir -p "$n"; cd "$n"
        # shellcheck disable=SC2086
        e --headless 4000 --seed 21 --population 200 $f --wiring-log --checkpoint-every 2000 --save-checkpoint h.json --csv h.csv
        e --load-checkpoint h.2000.json --headless 2000 --checkpoint-every 2000 --save-checkpoint r.json --csv r.csv \
          $( [ "$n" = stageC ] && echo --predator-log ) --wiring-log
        cmp -s h.json r.json || { echo "FAIL: $n: the resumed history differs from the uninterrupted one ($B)" >&2; exit 1; }
        cd ..
    done
    # a second Stage C world: the checkpoint donor
    mkdir -p donor; cd donor
    e --headless 2000 --seed 22 --population 200 --predators 6 $ECON --predator-brain --save-checkpoint y.json --csv y.csv
    cd ..
    for x in stageC stageB; do
        for src in ckpt random; do
            for assay in frozen frozen-newborn live; do
                t="t_${x}_${src}_${assay}"
                mkdir -p "$t"; cd "$t"
                cp "../$x/h.json" x.json
                [ "$src" = ckpt ] && cp ../donor/y.json y.json
                e --load-checkpoint x.json --predators-from "$( [ "$src" = ckpt ] && echo y.json || echo random )" \
                  --transplant-count 4 --transplant-seed 9 --assay "$assay" --transplant-out arena.json
                e --load-checkpoint arena.json --reseed-after-load 77 --headless 1000 --checkpoint-every 500 \
                  --save-checkpoint end.json --csv run.csv
                cd ..
            done
        done
    done
    cd "$W"
}
( run_all "$BASE" "$W/base" ) || exit 1
( run_all "$HEAD" "$W/head" ) || exit 1
python3 -I - "$W" <<'PY'
import csv, hashlib, io, json, os, re, sys
W = sys.argv[1]
TIMING = ("elapsed_s", "steps_per_sec")
def manifest(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in sorted(files):
            p = os.path.join(d, f)
            raw = open(p, "rb").read()
            if f.endswith(".config.txt"):          # (its first line carries the build's __DATE__ __TIME__ only)
                raw = re.sub(rb"\(built [^)\n]*\)", b"(built <masked>)", raw, count=1)
            if f.endswith(".csv"):
                rows = list(csv.reader(io.StringIO(raw.decode())))
                if rows and any(c in rows[0] for c in TIMING):
                    keep = [i for i, c in enumerate(rows[0]) if c not in TIMING]
                    raw = "\n".join(",".join(r[i] for i in keep if i < len(r)) for r in rows).encode()
            out[os.path.relpath(p, root)] = hashlib.sha256(raw).hexdigest()
    return out
b, h = manifest(os.path.join(W, "base")), manifest(os.path.join(W, "head"))
diff = sorted(k for k in set(b) | set(h) if b.get(k) != h.get(k))
rep = {"files": len(b), "identical": not diff, "differences": diff, "base": b, "head": h}
json.dump(rep, open(os.path.join(W, "identity.json"), "w"), indent=1, sort_keys=True)
kinds = {}
for k in b:
    kinds[k.split("/")[0]] = kinds.get(k.split("/")[0], 0) + 1
print(f"{len(b)} files in {len(kinds)} scenarios {sorted(kinds.items())}: "
      + ("IDENTICAL" if not diff else f"{len(diff)} DIFFER: {diff[:8]}"))
sys.exit(0 if not diff else 1)
PY
