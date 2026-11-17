#!/usr/bin/env bash
# rec_A_v1 (A_design_v5.md 4.4; the successor of rec_C_v2): Red Queen gate-2 recovery under the bank/D8 observation
# model. Read-only on the production and bank roots; every output goes under P_REC. See rec_A_v1.py and the adopted
# CRITERION. Phases: measure (the measurement-only benchmark, before prepare), prepare (the freeze), run (after the
# external witness of FROZEN.sha256: P_REC/PRIOR.receipt). The acceptance packet is produced by run, through
# `recovery.py packet --mode acceptance` only; the wrapper never uses diagnostic mode.
#   env: P_REC, JOBS (1 or 2: at most 2 concurrent workers in total), PY, D8_DIR, AUTHORITY_DIR, CRITERION;
#        RQ_REC_A_TEST_FIXTURE (tests only: a toy-graph fixture directory, never a real input).
set -euo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PY=${PY:-python3}
P_REC=${P_REC:-/home/harit/finfolk/work/recovery_A_v1}
JOBS=${JOBS:-2}
[[ $# -ge 1 && ( $1 == measure || $1 == prepare || $1 == run ) ]] || {
  echo 'usage: rec_A_v1.sh measure|prepare|run' >&2; exit 2; }
[[ $# == 1 ]] || {
  echo 'rec_A_v1.sh takes the phase only: the acceptance packet is recovery.py packet --mode acceptance,' \
       'never diagnostic (A_design_v5 3.8, 4.4)' >&2
  exit 2; }
[[ $JOBS =~ ^[12]$ ]] || {
  echo 'JOBS must be 1 or 2 (at most 2 concurrent workers in total, A_design_v5 4.4)' >&2; exit 2; }
[[ $(ps -o ni= -p $$) -eq 19 ]] || { echo 'Launch with nice -n 19' >&2; exit 2; }
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
unset PYTHONPATH RQ_PYLIB
ARGS=("$1" --root "$P_REC" --jobs "$JOBS")
if [[ -n ${D8_DIR:-} ]]; then ARGS+=(--d8 "$D8_DIR"); fi
if [[ -n ${AUTHORITY_DIR:-} ]]; then ARGS+=(--authority "$AUTHORITY_DIR"); fi
if [[ -n ${CRITERION:-} ]]; then ARGS+=(--criterion "$CRITERION"); fi
if [[ -n ${RQ_REC_A_TEST_FIXTURE:-} ]]; then ARGS+=(--test-fixture "$RQ_REC_A_TEST_FIXTURE"); fi
exec "$PY" -I -B "$HERE/rec_A_v1.py" "${ARGS[@]}"
