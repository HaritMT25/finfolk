#!/usr/bin/env bash
# Standalone geometry/signed-trim tests and a rejected measurement-only fault.
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/ocean_hydro_measurements.XXXXXX")
trap 'rm -rf "$out"' EXIT
flags=(-O3 -std=c++20 -ffp-contract=off -I src)
nice -n 19 "${CXX:-g++}" "${flags[@]}" tests/ocean_hydro_measurements.cpp -o "$out/good"
nice -n 19 "$out/good"
nice -n 19 "${CXX:-g++}" "${flags[@]}" -DPLANT_RADIUS_FAULT tests/ocean_hydro_measurements.cpp -o "$out/fault"
set +e
nice -n 19 "$out/fault" > "$out/fault.log"
status=$?
set -e
cat "$out/fault.log"
test "$status" = 1
# The fault must fail both identities on the resolved synthetic arc, while
# transient/unresolved exclusions and angle checks retain their semantics.
for name in resolved_course_identity resolved_heading_identity; do
    rg -q "^FAIL,$name$" "$out/fault.log"
done
for name in transient_not_exercised unresolved_not_exercised D2_heading_alignment D2_signed_angles; do
    rg -q "^PASS,$name$" "$out/fault.log"
done
printf '%s\n' 'PASS,planted_radius_fault_rejected'

for fault in CONVERSION FREE_LOW FREE_HIGH; do
    nice -n 19 "${CXX:-g++}" "${flags[@]}" "-DPLANT_CAL4_${fault}_FAULT" tests/ocean_hydro_measurements.cpp -o "$out/motor_$fault"
    set +e
    nice -n 19 "$out/motor_$fault" > "$out/motor_$fault.log"
    status=$?
    set -e
    cat "$out/motor_$fault.log"
    test "$status" = 1
    case "$fault" in
        CONVERSION) predicate=restrained_motor_roundoff ;;
        FREE_LOW) predicate=free_motor_planted_lower ;;
        FREE_HIGH) predicate=free_motor_planted_upper ;;
    esac
    rg -q "^FAIL,$predicate$" "$out/motor_$fault.log"
    printf 'PASS,planted_motor_%s_fault_rejected\n' "$fault"
done
