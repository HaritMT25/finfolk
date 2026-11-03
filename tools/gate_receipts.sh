# Gate receipts: source this file, then
#   FAST=1 JOBS=2 BUILD_JOBS=2 gate_run ocean-fast -- bash wasm/ocean_parity.sh
#   FAST=1 JOBS=2 BUILD_JOBS=2 gate_check ocean-fast      # lookup only, one JSON line
# gate_run = reuse a fresh receipt, or execute and record; it returns the gate's exit code
# (2 = invalid invocation, 125 = identity, storage or receipt publication failed). Run from the repository root.
# GATE_FORCE=1 re-executes despite a receipt; CI / GITHUB_ACTIONS disable all reuse. See docs/gate_receipts.md.
# Sourcing defines functions only; nothing runs.

_gate_call() {
  local mode=$1 gate=${2:-} top
  if [ -z "$gate" ]; then echo "gate_$mode: gate name required" >&2; return 2; fi
  shift 2
  if [ "${1:-}" = "--" ]; then shift; fi
  # The helper is resolved on every call from the candidate being gated (not from wherever this file was sourced);
  # -I ignores PYTHON* variables. The helper's bytes are part of every key.
  top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f "$top/tools/gate_receipts.py" ] || {
    echo "gate_$mode: no tools/gate_receipts.py in this checkout" >&2; return 125; }
  python3 -I "$top/tools/gate_receipts.py" "$mode" "$gate" -- "$@"
}

gate_run() { _gate_call run "$@"; }
gate_check() { _gate_call check "$@"; }
