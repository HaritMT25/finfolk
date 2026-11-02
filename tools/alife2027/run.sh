#!/usr/bin/env bash
# run.sh — the ALIFE 2027 runner: resumable, failure-propagating, bounded.
#
#   tools/alife2027/run.sh --plan PLAN.jsonl --root DIR --build BUILDDIR
#                          [--workers N] [--cpus LIST] [--poll S]
#
# PLAN.jsonl comes from tools/alife2027/plan.py; BUILDDIR from build.py (its
# ocean_eye_exp + build_manifest.json). Everything lands under DIR, outside
# the repository:
#   DIR/build/            the pinned executable and build manifest (copied on
#                         the first run; its SHA-256 is checked before EVERY
#                         launch; a different build for the same DIR is refused)
#   DIR/plan.jsonl        the pinned plan (a different plan is refused)
#   DIR/<phase>/s<seed>/<arm>/   one job: its outputs, logs, time.txt and, once
#                         the process succeeded AND its outputs validated
#                         (runlib.py), <prefix>.manifest.json, written atomically
#   DIR/runner.log, DIR/attempts.tsv
#
# Rules:
#   * at most --workers simultaneous simulations (1..4; default 2), each
#     single-threaded under `nice -n 19` (and `taskset -c LIST` with --cpus)
#   * one runner per DIR (flock on DIR/.runner.lock)
#   * resume: a job with a manifest is re-verified (its outputs must still hash
#     as recorded: a corrupt "complete" job is an error) and skipped; a job
#     without one is rerun from initialization, the earlier attempt's files
#     moved to attempt_N/
#   * a failed process or a failed validation stops admission; running jobs
#     finish (or are drained); the runner exits 1
#   * DIR/STOP: stop admitting, let running jobs finish, exit 75; remove it and
#     start again to resume
#   * memory: below ALIFE_MEM_PAUSE bytes of MemAvailable (default 2 GiB) no
#     job is admitted and running jobs' process groups are SIGSTOPped; they
#     continue at ALIFE_MEM_RESUME (default 3 GiB). These are WSL / Linux
#     readings: they say nothing about the Windows host's headroom.
#   * SIGINT / SIGTERM: paused jobs are continued, every job is terminated and
#     reaped, exit 130
# Test hooks: ALIFE_MEMINFO (a file in /proc/meminfo's format).
set -u -o pipefail
TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PLAN="" ROOT="" BUILD="" WORKERS=2 CPUS="" POLL=2
while [ $# -gt 0 ]; do
    case "$1" in
        --plan) PLAN=$2; shift 2 ;;
        --root) ROOT=$2; shift 2 ;;
        --build) BUILD=$2; shift 2 ;;
        --workers) WORKERS=$2; shift 2 ;;
        --cpus) CPUS=$2; shift 2 ;;
        --poll) POLL=$2; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
[ -n "$PLAN" ] && [ -n "$ROOT" ] && [ -n "$BUILD" ] || { echo "usage: run.sh --plan P --root DIR --build BUILDDIR [--workers N] [--cpus LIST]" >&2; exit 2; }
case "$WORKERS" in 1|2|3|4) ;; *) echo "--workers must be 1..4" >&2; exit 2 ;; esac
[ "${BASH_VERSINFO[0]}" -ge 5 ] || { echo "bash 5 needed" >&2; exit 2; }
MEMINFO=${ALIFE_MEMINFO:-/proc/meminfo}
PAUSE=${ALIFE_MEM_PAUSE:-2147483648}
RESUME=${ALIFE_MEM_RESUME:-3221225472}
mkdir -p "$ROOT"
ROOT=$(cd "$ROOT" && pwd)
exec 9> "$ROOT/.runner.lock"
flock -n 9 || { echo "another runner holds $ROOT" >&2; exit 73; }
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$ROOT/runner.log"; }

# ---- pin the build and the plan ------------------------------------------------
mkdir -p "$ROOT/build"
if [ ! -f "$ROOT/build/build_manifest.json" ]; then
    cp "$BUILD/ocean_eye_exp" "$BUILD/build_manifest.json" "$ROOT/build/" || exit 2
elif ! cmp -s "$BUILD/build_manifest.json" "$ROOT/build/build_manifest.json"; then
    echo "$ROOT already holds runs of another build ($ROOT/build/build_manifest.json)" >&2; exit 2
fi
EXE=$ROOT/build/ocean_eye_exp
BM=$ROOT/build/build_manifest.json
WANT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['executable']['sha256'])" "$BM") || exit 2
exe_ok() { [ "$(sha256sum < "$EXE" | cut -d' ' -f1)" = "$WANT" ]; }
exe_ok || { echo "pinned executable does not match its build manifest" >&2; exit 2; }
if [ ! -f "$ROOT/plan.jsonl" ]; then cp "$PLAN" "$ROOT/plan.jsonl"
elif ! cmp -s "$PLAN" "$ROOT/plan.jsonl"; then echo "$ROOT already runs another plan" >&2; exit 2; fi
mkdir -p "$ROOT/.jobs"
NJOBS=$(python3 - "$ROOT/plan.jsonl" "$ROOT/.jobs" <<'PY'
import json, os, sys
n = 0
for i, line in enumerate(open(sys.argv[1])):
    line = line.strip()
    if not line:
        continue
    j = json.loads(line)
    base = os.path.join(sys.argv[2], "%06d" % n)
    with open(base + ".json", "w") as f:
        json.dump(j, f)
    with open(base + ".argv", "wb") as f:
        f.write(b"".join(a.encode() + b"\0" for a in j["argv"]))
    with open(base + ".meta", "w") as f:
        f.write("%s\t%s\t%s\n" % (j["id"], os.path.join(j["phase"], j["dir"]), j["prefix"]))
    n += 1
print(n)
PY
) || exit 2
[ -f "$ROOT/attempts.tsv" ] || printf 'job\tattempt\tstart_utc\tend_utc\tstatus\tvalidation\n' > "$ROOT/attempts.tsv"
log "runner start: $NJOBS jobs, workers $WORKERS, cpus ${CPUS:-any}, nice 19, plan $(sha256sum < "$ROOT/plan.jsonl" | cut -c1-12), exe ${WANT:0:12}"

TASKSET=()
[ -n "$CPUS" ] && TASKSET=(taskset -c "$CPUS")
TIMER=()
[ -x /usr/bin/time ] && TIMER=(/usr/bin/time -v -o)
mem_avail() { awk '/^MemAvailable:/ {print $2 * 1024; exit}' "$MEMINFO"; }

declare -A RUN_N=() RUN_START=() RUN_ATTEMPT=()
FAILED=0 STOPPED=0 PAUSED=0 next=0 done_count=0

running() {   # alive and not a zombie
    local pid=$1 st
    kill -0 "$pid" 2> /dev/null || return 1
    st=$(awk '{print $3}' "/proc/$pid/stat" 2> /dev/null) || return 1
    [ "$st" != Z ]
}

meta() { IFS=$'\t' read -r JID JDIR JPREFIX < "$ROOT/.jobs/$(printf %06d "$1").meta"; }

launch() {
    local n=$1 a=1 dir
    meta "$n"
    dir=$ROOT/$JDIR
    mkdir -p "$dir"
    if compgen -G "$dir/*.*" > /dev/null; then   # an interrupted earlier attempt: keep its files
        while [ -d "$dir/attempt_$a" ]; do a=$((a + 1)); done
        mkdir "$dir/attempt_$a"
        find "$dir" -maxdepth 1 -type f -exec mv {} "$dir/attempt_$a/" \;
        log "job $JID: earlier attempt kept in attempt_$a"
    fi
    a=1; while [ -d "$dir/attempt_$a" ]; do a=$((a + 1)); done
    exe_ok || { log "FAILED: pinned executable changed on disk"; FAILED=1; return 1; }
    local args=()
    mapfile -d '' args < "$ROOT/.jobs/$(printf %06d "$n").argv"
    local timer=()
    [ ${#TIMER[@]} -gt 0 ] && timer=("${TIMER[@]}" "$JPREFIX.time.txt")
    ( cd "$dir" && exec setsid nice -n 19 "${TASKSET[@]}" "${timer[@]}" "$EXE" "${args[@]}" \
        > "$JPREFIX.stdout.log" 2> "$JPREFIX.stderr.log" ) &
    local pid=$!
    RUN_N[$pid]=$n; RUN_START[$pid]=$(date -u +%FT%TZ); RUN_ATTEMPT[$pid]=$a
    log "start $JID (pid $pid, attempt $a)"
}

finish() {
    local pid=$1 st=$2 n=${RUN_N[$1]} v=ok
    meta "$n"
    if ! python3 "$TOOLS/runlib.py" finalize "$ROOT/.jobs/$(printf %06d "$n").json" "$ROOT/$JDIR" "$BM" "$st" \
            "${RUN_ATTEMPT[$pid]}" >> "$ROOT/runner.log" 2>&1; then
        v=invalid
        FAILED=1
        log "FAILED: $JID exit $st (validation $v; see $ROOT/$JDIR)"
    else
        done_count=$((done_count + 1))
        log "done $JID"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$JID" "${RUN_ATTEMPT[$pid]}" "${RUN_START[$pid]}" "$(date -u +%FT%TZ)" "$st" "$v" \
        >> "$ROOT/attempts.tsv"
    unset "RUN_N[$pid]" "RUN_START[$pid]" "RUN_ATTEMPT[$pid]"
}

reap() {
    local pid st
    for pid in "${!RUN_N[@]}"; do
        if ! running "$pid"; then
            wait "$pid"; st=$?
            finish "$pid" "$st"
        fi
    done
}

signal_all() { local pid; for pid in "${!RUN_N[@]}"; do kill "-$1" -- "-$pid" 2> /dev/null; done; }

on_signal() {
    log "signal: terminating ${#RUN_N[@]} job(s)"
    signal_all CONT
    signal_all TERM
    local pid
    for pid in "${!RUN_N[@]}"; do wait "$pid" 2> /dev/null; done
    log "interrupted"
    exit 130
}
trap on_signal INT TERM

while :; do
    reap
    if [ -e "$ROOT/STOP" ] && [ $STOPPED = 0 ]; then STOPPED=1; log "STOP file: no more admissions"; fi
    # memory: pause / resume whatever is running (also while draining)
    avail=$(mem_avail)
    if [ "$avail" -lt "$PAUSE" ]; then
        if [ $PAUSED = 0 ] && [ ${#RUN_N[@]} -gt 0 ]; then signal_all STOP; PAUSED=1; log "pause: MemAvailable $avail < $PAUSE"; fi
    elif [ $PAUSED = 1 ] && [ "$avail" -ge "$RESUME" ]; then
        signal_all CONT; PAUSED=0; log "resume: MemAvailable $avail"
    fi
    [ $PAUSED = 1 ] && [ ${#RUN_N[@]} -eq 0 ] && PAUSED=0
    if [ $FAILED = 1 ] || [ $STOPPED = 1 ] || [ $next -ge "$NJOBS" ]; then
        [ ${#RUN_N[@]} -eq 0 ] && break
        sleep "$POLL"; continue
    fi
    if [ $PAUSED = 1 ] || [ "$avail" -lt "$PAUSE" ]; then sleep "$POLL"; continue; fi
    if [ ${#RUN_N[@]} -lt "$WORKERS" ]; then
        meta "$next"
        if [ -f "$ROOT/$JDIR/$JPREFIX.manifest.json" ]; then
            if python3 "$TOOLS/runlib.py" verify "$ROOT/$JDIR" "$JPREFIX" > /dev/null 2>> "$ROOT/runner.log"; then
                done_count=$((done_count + 1))
            else
                log "FAILED: $JID is marked complete but its outputs changed (investigate $ROOT/$JDIR)"
                FAILED=1
            fi
        else
            launch "$next" || true
        fi
        next=$((next + 1))
        continue
    fi
    sleep "$POLL"
done
if [ $FAILED = 1 ]; then log "runner end: FAILED ($done_count of $NJOBS complete)"; exit 1; fi
if [ $STOPPED = 1 ] && [ $done_count -lt "$NJOBS" ]; then log "runner end: stopped ($done_count of $NJOBS complete)"; exit 75; fi
log "runner end: all $NJOBS jobs complete"
exit 0
