#!/bin/bash
set -euo pipefail
BIN=${1:?binary}
WORK=${2:?scratch}
mkdir -p "$WORK"
cd "$WORK"
run() { "$BIN" --no-render --headless 1 --population 3 --min-pop 0 --seed 42 --name g2 "$@" >run.log 2>&1; }
policy=(--genome-version 2 --brain-eval-version 2 --weight-mutation-mode saturating)
for length in --genome-min --genome-max --genome-init-min --genome-init-max; do
    for token in 80junk 80.5 9999999999999999999999999999 '' 0x50; do
        for order in first last; do
            args=("${policy[@]}" "$length" "$token")
            if [ "$order" = first ]; then args=("$length" "$token" "${policy[@]}"); fi
            if run "${args[@]}" --save-checkpoint forbidden.json; then echo "FAIL accepted $length $token $order"; exit 1; fi
            test ! -e forbidden.json
        done
    done
done
# A later valid duplicate must not erase an earlier malformed token.
if run --genome-max 80junk "${policy[@]}" --genome-max 80; then exit 1; fi
run "${policy[@]}" --bias-genes --save-checkpoint v2.json
run --load-checkpoint v2.json --save-checkpoint resumed.json
python3 - <<'PY'
import json
for name in ['v2.json','resumed.json']:
    j=json.load(open(name));assert j['formatVersion']==3
    assert j['brainPolicy']['metadataVersion']==2
    assert j['config']['genomeVersion']==2
PY
# Policy flags on resume must never be silently discarded, even at defaults.
for args in '--genome-version 2' '--brain-eval-version 2' '--bias-genes' '--hidden-neurons 12' '--weight-mutation-mode saturating'; do
    if run --load-checkpoint v2.json $args --save-checkpoint forbidden.json; then exit 1; fi
    grep -q 'use genome_v2_convert' run.log
    test ! -e forbidden.json
done
# Existing complete-token truncation for v1 and PR1 saturation remains.
run --genome-max 80junk
run --weight-mutation-mode saturating --genome-max 80junk
echo 'genome v2 CLI: PASS'
