#!/usr/bin/env bash
# The actual CLI policy parser, writer selection and resume semantics.
set -euo pipefail
BIN=${1:?binary required}
WORK=${2:?scratch directory required}
mkdir -p "$WORK"
cd "$WORK"
run() { "$BIN" --no-render --headless 1 --population 3 --seed 42 --name policy "$@" >run.log 2>&1; }
run --save-checkpoint absent.json
run --weight-mutation-mode legacy --save-checkpoint legacy.json
cmp absent.json legacy.json
run --weight-mutation-mode saturating --save-checkpoint saturated.json
python3 - <<'PY'
import json
j=json.load(open('saturated.json'))
assert j['formatVersion'] == 3
assert j['config']['weightMutationMode'] == 'saturating'
assert j['brainPolicy']['metadataVersion'] == 1
PY
for value in wrap 1 LEGACY; do
    if run --weight-mutation-mode "$value"; then
        echo "accepted invalid policy $value" >&2; exit 1
    fi
done
if run --weight-mutation-mode; then
    echo 'accepted missing policy argument' >&2; exit 1
fi
# Resume follows checkpoint policy even when the CLI selects the other policy.
run --load-checkpoint absent.json --weight-mutation-mode saturating --save-checkpoint resumed.json
python3 - <<'PY'
import json
j=json.load(open('resumed.json'))
assert j['formatVersion'] == 1
assert 'weightMutationMode' not in j['config']
PY
echo 'weight policy CLI: PASS'
