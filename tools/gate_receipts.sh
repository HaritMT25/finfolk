# Gate receipts: source this file, then
#   FAST=1 JOBS=2 BUILD_JOBS=2 gate_run ocean-fast -- bash wasm/ocean_parity.sh
#   FAST=1 JOBS=2 BUILD_JOBS=2 gate_check ocean-fast      # lookup only, one JSON line
# gate_run = reuse a fresh receipt, or execute and record; it returns the gate's exit code
# (2 = invalid invocation, 125 = identity or receipt publication failed). Run from the repository root.
# GATE_FORCE=1 re-executes despite a receipt; CI / GITHUB_ACTIONS disable all reuse. See docs/gate_receipts.md.
# Sourcing defines functions only; nothing runs.
_GATE_RECEIPTS_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gate_receipts.py"

_gate_call() {
  local mode=$1 gate=${2:-}
  if [ -z "$gate" ]; then echo "gate_$mode: gate name required" >&2; return 2; fi
  shift 2
  if [ "${1:-}" = "--" ]; then shift; fi
  # The candidate's own helper runs (it is part of the tree being keyed); -I ignores PYTHON* variables.
  python3 -I "$_GATE_RECEIPTS_PY" "$mode" "$gate" -- "$@"
}

gate_run() { _gate_call run "$@"; }
gate_check() { _gate_call check "$@"; }
