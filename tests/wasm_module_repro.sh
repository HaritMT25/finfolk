#!/bin/bash
# After building the six production artifacts with emsdk 6.0.4:
#   nice -n 19 bash tests/wasm_module_repro.sh
# WASM_REPRO_BASE_REF defaults to main; set it to the approved main commit
# when the checkout has no local main ref. Git access is read-only.
# Rebuild from source at another absolute path; never change the originals.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
copy=$(mktemp -d /tmp/finfolk-module-repro.XXXXXX)
trap 'rm -rf "$copy"' EXIT
cp "$root/CMakeLists.txt" "$root/CMakePresets.json" "$copy/"
cp -R "$root/src" "$root/wasm" "$copy/"
mkdir "$copy/web"
(
    cd "$copy"
    bash wasm/build_wasm.sh
    bash wasm/build_ocean.sh
)
for module in evo_boids.js evo_boids.wasm evo_boids_mt.js evo_boids_mt.wasm evo_ocean.js evo_ocean.wasm; do
    cmp "$root/web/$module" "$copy/web/$module"
done
python3 - "$root" "$copy" "${WASM_REPRO_BASE_REF:-main}" <<'PY'
import hashlib
from pathlib import Path
import subprocess
import sys

root, copy = map(Path, sys.argv[1:3])
base = subprocess.check_output(
    ['git', '-C', str(root), 'rev-parse', '--verify', sys.argv[3] + '^{commit}'],
    text=True).strip()
# Count occurrences in the actual bytes, including strings shorter than 8 bytes.
roots = [str(root), str(copy), '/home/harit']
print('Approved main commit:', base)
print('Forbidden build roots:', roots)
print('artifact\tbuild\tsha256\tworktree\tsecond-root\thost-home\tvirtual-home')
for name in ('evo_boids.js', 'evo_boids.wasm', 'evo_boids_mt.js',
             'evo_boids_mt.wasm', 'evo_ocean.js', 'evo_ocean.wasm'):
    original = subprocess.check_output(['git', '-C', str(root), 'show', base + ':web/' + name])
    for build, data in [('main', original), ('head', (root / 'web' / name).read_bytes()),
                        ('second', (copy / 'web' / name).read_bytes())]:
        counts = [data.count(path.encode()) for path in roots]
        virtual = data.count(b'/home/web_user')
        print('\t'.join(map(str, [name, build, hashlib.sha256(data).hexdigest(), *counts, virtual])),
              flush=True)
        assert not any(counts), (name, build, 'embedded build root', counts)
        if virtual:
            assert name.endswith('.js'), (name, build, 'virtual HOME in Wasm')
            assert b'/home/web_user' in original, (name, 'virtual HOME absent from main')
PY
echo 'PASS: six artifacts byte-identical across different source paths; no absolute build paths'
