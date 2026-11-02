#!/usr/bin/env bash
# Tests for tools/alife2027/run.sh with fake children (no simulation):
#   bash tests/alife2027/test_runner.sh        (about 40 s; uses one or two cores lightly)
set -u -o pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUN=$HERE/../../tools/alife2027/run.sh
W=$(mktemp -d /tmp/alife_runner_test.XXXXXX)
trap 'rm -rf "$W"' EXIT
PASS=0 FAIL=0
ok() { if eval "$2"; then PASS=$((PASS + 1)); echo "ok   $1"; else FAIL=$((FAIL + 1)); echo "FAIL $1   [$2]"; fi; }

# the fake "simulation": records its niceness and its start / end, sleeps, writes PREFIX.out, exits CODE
mkdir -p "$W/build"
cat > "$W/build/ocean_eye_exp" <<'EOF'
#!/usr/bin/env bash
out=x sleep=1 code=0 log=/dev/null
while [ $# -gt 0 ]; do case "$1" in --out) out=$2;; --sleep) sleep=$2;; --code) code=$2;; --log) log=$2;; esac; shift 2; done
echo "start $out $(date +%s.%N) $(ps -o ni= -p $$ | tr -d ' ')" >> "$log"
sleep "$sleep"
echo "end $out $(date +%s.%N)" >> "$log"
echo done > "$out.out"
exit "$code"
EOF
chmod +x "$W/build/ocean_eye_exp"
python3 - "$W/build" <<'PY'
import hashlib, json, sys
d = sys.argv[1]
h = hashlib.sha256(open(d + "/ocean_eye_exp", "rb").read()).hexdigest()
json.dump({"executable": {"sha256": h}, "git": {"commit": "test"}, "source_inventory": {"hash": "test"}},
          open(d + "/build_manifest.json", "w"))
PY
mkplan() {   # mkplan FILE LOG "sleep:code sleep:code ..."
    python3 - "$1" "$2" "$3" <<'PY'
import json, sys
path, log, specs = sys.argv[1], sys.argv[2], sys.argv[3].split()
with open(path, "w") as f:
    for i, s in enumerate(specs):
        sl, code = s.split(":")
        p = f"J{i}_s{i}"
        f.write(json.dumps({"id": f"test/s{i}/J{i}", "phase": "test", "dir": f"s{i}/J{i}", "prefix": p, "seed": i,
                            "arm": f"J{i}", "kind": "fake", "expect": {"files": [p + ".out"]},
                            "argv": ["--out", p, "--sleep", sl, "--code", code, "--log", log]}) + "\n")
PY
}
maxconc() {   # the largest number of simultaneously running fake jobs in LOG
    python3 - "$1" <<'PY'
import sys
ev = []
for ln in open(sys.argv[1]):
    k, name, t = ln.split()[:3]
    ev.append((float(t), 1 if k == "start" else -1))
cur = best = 0
for t, d in sorted(ev, key=lambda e: (e[0], e[1])):
    cur += d; best = max(best, cur)
print(best)
PY
}

# 1. bounded concurrency, nice 19, manifests
mkplan "$W/p1.jsonl" "$W/l1.txt" "1:0 1:0 1:0 1:0 1:0 1:0"
bash "$RUN" --plan "$W/p1.jsonl" --root "$W/r1" --build "$W/build" --workers 2 --poll 0.1 > /dev/null; rc=$?
ok "six jobs complete (exit 0)" '[ $rc = 0 ]'
ok "at most 2 at a time" '[ "$(maxconc "$W/l1.txt")" -le 2 ]'
ok "every child at nice 19" '[ "$(awk "/^start/ {print \$4}" "$W/l1.txt" | sort -u)" = 19 ]'
ok "a manifest per job" '[ "$(find "$W/r1/test" -name "*.manifest.json" | wc -l)" = 6 ]'
# 2. resume: nothing reruns
n0=$(grep -c ^start "$W/l1.txt")
bash "$RUN" --plan "$W/p1.jsonl" --root "$W/r1" --build "$W/build" --workers 2 --poll 0.1 > /dev/null; rc=$?
ok "resume skips completed jobs" '[ $rc = 0 ] && [ "$(grep -c ^start "$W/l1.txt")" = "$n0" ]'
# 3. a corrupt "complete" job is an error
echo tampered >> "$W/r1/test/s3/J3/J3_s3.out"
bash "$RUN" --plan "$W/p1.jsonl" --root "$W/r1" --build "$W/build" --workers 2 --poll 0.1 > /dev/null; rc=$?
ok "a changed completed output fails the resume" '[ $rc = 1 ]'
# 4. a failing child stops admission and the runner exits 1
mkplan "$W/p4.jsonl" "$W/l4.txt" "0.3:0 2.5:0 0.5:3 1:0 1:0 1:0"   # J2 fails while J1 still runs
bash "$RUN" --plan "$W/p4.jsonl" --root "$W/r4" --build "$W/build" --workers 2 --poll 0.1 > /dev/null; rc=$?
ok "child failure -> exit 1" '[ $rc = 1 ]'
ok "no admission after the failure" '[ "$(grep -c ^start "$W/l4.txt")" = 3 ]'
ok "the failure is recorded" 'grep -q "	3	invalid" "$W/r4/attempts.tsv"'
ok "the running job was drained, not killed" '[ "$(grep -c "^end J1" "$W/l4.txt")" = 1 ] && [ -f "$W/r4/test/s1/J1/J1_s1.manifest.json" ]'
# 5. STOP drains and exits 75; removing it resumes
mkplan "$W/p5.jsonl" "$W/l5.txt" "1.5:0 1.5:0 1.5:0"
( sleep 0.7; touch "$W/r5/STOP" ) &
bash "$RUN" --plan "$W/p5.jsonl" --root "$W/r5" --build "$W/build" --workers 1 --poll 0.1 > /dev/null; rc=$?
ok "STOP -> exit 75 after the running job" '[ $rc = 75 ] && [ "$(grep -c ^end "$W/l5.txt")" = 1 ]'
rm -f "$W/r5/STOP"
bash "$RUN" --plan "$W/p5.jsonl" --root "$W/r5" --build "$W/build" --workers 1 --poll 0.1 > /dev/null; rc=$?
ok "restart completes the rest without rerunning" '[ $rc = 0 ] && [ "$(grep -c ^start "$W/l5.txt")" = 3 ]'
# 6. low memory pauses the running jobs and resumes them
printf 'MemTotal: 8000000 kB\nMemAvailable: 6000000 kB\n' > "$W/mem"
mkplan "$W/p6.jsonl" "$W/l6.txt" "2:0 2:0"
( until [ "$(grep -c ^start "$W/l6.txt" 2> /dev/null)" = 2 ]; do sleep 0.05; done   # both running: memory drops
  printf 'MemAvailable: 1000000 kB\n' > "$W/mem"; sleep 0.8
  ps -o stat= -p "$(pgrep -d, -f l6.txt)" > "$W/states6"   # while paused (sleep keeps its deadline, so time can't show it)
  sleep 0.7; printf 'MemAvailable: 4000000 kB\n' > "$W/mem" ) &
t0=$(date +%s.%N)
ALIFE_MEMINFO=$W/mem bash "$RUN" --plan "$W/p6.jsonl" --root "$W/r6" --build "$W/build" --workers 2 --poll 0.1 > /dev/null; rc=$?
t1=$(date +%s.%N)
ok "low memory: pause then resume, all complete" '[ $rc = 0 ] && grep -q "pause: MemAvailable" "$W/r6/runner.log" && grep -q "resume: MemAvailable" "$W/r6/runner.log"'
ok "every job process was stopped (T) during the pause" '[ -s "$W/states6" ] && ! grep -qv "^T" "$W/states6"'
# 7. SIGTERM: children terminated and reaped, exit 130
mkplan "$W/p7.jsonl" "$W/l7.txt" "30:0 30:0"
bash "$RUN" --plan "$W/p7.jsonl" --root "$W/r7" --build "$W/build" --workers 2 --poll 0.1 > /dev/null &
rp=$!
sleep 1; kill -TERM $rp; wait $rp; rc=$?
sleep 0.3
ok "SIGTERM -> exit 130" '[ $rc = 130 ]'
ok "no child left running" '! pgrep -f "l7.txt" > /dev/null'
# 8. limits and identity
bash "$RUN" --plan "$W/p1.jsonl" --root "$W/r8" --build "$W/build" --workers 5 > /dev/null 2>&1; rc=$?
ok "--workers 5 refused" '[ $rc = 2 ]'
cp -r "$W/build" "$W/build2"; echo "# changed" >> "$W/build2/ocean_eye_exp"
python3 - "$W/build2" <<'PY'
import hashlib, json, sys
d = sys.argv[1]; m = json.load(open(d + "/build_manifest.json"))
m["executable"]["sha256"] = hashlib.sha256(open(d + "/ocean_eye_exp", "rb").read()).hexdigest()
json.dump(m, open(d + "/build_manifest.json", "w"))
PY
bash "$RUN" --plan "$W/p1.jsonl" --root "$W/r1" --build "$W/build2" --workers 2 > /dev/null 2>&1; rc=$?
ok "another build for the same root refused" '[ $rc = 2 ]'
echo "runner tests: $PASS passed, $FAIL failed"
[ $FAIL = 0 ]
