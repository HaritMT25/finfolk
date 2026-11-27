#!/usr/bin/env bash
# End-to-end assay-4 faults. Alter the kernel's priced fuel before the actual
# reserve debit in a scratch copy; checked-in mechanics are never modified.
set -euo pipefail
cd "$(dirname "$0")/.."
out=${HYDRO_ACCOUNTING_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/ocean_hydro_accounting.XXXXXX")}
mkdir -p "$out/ocean"
export HYDRO_ACCOUNTING_OUT="$out"
python3 - <<'PY'
import os,pathlib
out=pathlib.Path(os.environ['HYDRO_ACCOUNTING_OUT'])
s=pathlib.Path('src/ocean/hydro_step.hpp').read_text()
needle='if(!limitMotor(c,energy-reserved,s.fatigue,r.plan.requestPower,references().workConversion,r.motor)) return refuse(kStepMotor);'
assert s.count(needle)==1
s=s.replace(needle,needle+'''
#ifdef HYDRO_CAL4_E2E_FAULT
        if(hydrofault::active) {
#if HYDRO_CAL4_E2E_FAULT == 1
            r.motor.fuel=.591f*kSubDt;
#elif HYDRO_CAL4_E2E_FAULT == 2
            r.motor.fuel=.609f*kSubDt;
#else
            r.motor.fuel-=.0005f*kSubDt;
#endif
        }
#endif
''')
(out/'ocean/hydro_step.hpp').write_text(s)
(out/'fault_state.hpp').write_text('namespace hydrofault { inline bool active=false; }\n')
PY
flags=(-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I "$out" -I src -I src/ocean -include "$out/fault_state.hpp")
for fault in conversion_minus conversion_plus free_low free_high in_band_undercharge; do
    case "$fault" in
      conversion_minus) define=-DPLANT_CAL4_CONVERSION_FAULT=.99f ;;
      conversion_plus) define=-DPLANT_CAL4_CONVERSION_FAULT=1.01f ;;
      free_low) define=-DHYDRO_CAL4_E2E_FAULT=1 ;;
      free_high) define=-DHYDRO_CAL4_E2E_FAULT=2 ;;
      in_band_undercharge) define=-DHYDRO_CAL4_E2E_FAULT=3 ;;
    esac
    nice -n 19 "${CXX:-g++}" "${flags[@]}" "$define" tools/ocean_hydro_assay.cpp -o "$out/$fault"
    test ! -e "$out/$fault.stage4.hpp"
    set +e
    nice -n 19 "$out/$fault" --assay 4 --emit-calibration "$out/$fault.stage4.hpp" --manifest "$out/$fault.json" > "$out/$fault.log" 2>&1
    status=$?
    set -e
    test "$status" = 1
    test ! -e "$out/$fault.stage4.hpp"
    python3 - "$out/$fault.json" "$fault" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]));fault=sys.argv[2];p={r['name']:r['pass'] for r in x['results']}
assert not x['passed']
if fault.startswith('conversion'):
 assert not p['cal4/restrained_reference_.60_roundoff']
else:
 assert not p['cal4/independent_motor_fatigue_accounting']
 assert not p['cal4/every_debit_matches_rounded_ledger']
 assert p['cal4/free_motor_.60_plus_minus_.008']==(fault=='in_band_undercharge')
print('PASS,end_to_end_'+fault+',exit=1,no_stage4=true,failures='+str([k for k,v in p.items() if not v]))
PY
    # Also exercise the genuine final-stage --check-all entry point.
    if rg -q 'kFrozenThrough = 4' src/ocean/hydro_calibration.hpp; then
      set +e
      nice -n 19 "$out/$fault" --check-all --manifest "$out/$fault.check_all.json" > "$out/$fault.check_all.log" 2>&1
      status=$?
      set -e
      test "$status" = 1
    fi
done
printf 'PASS,all_actual_assay4_faults_rejected,evidence=%s\n' "$out"
