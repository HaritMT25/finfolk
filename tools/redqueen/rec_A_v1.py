#!/usr/bin/env python3
"""rec_A_v1: the Red Queen gate-2 exact-graph recovery under option A, the bank/D8 observation model
(A_design_v5.md 4.4; the successor of rec_C_v2, whose bodies are c4ac6090... / 5a0d15f2...). Local orchestration
only: it never edits a tool or any production or bank path, and every output goes under P_REC (--root).

  measure  the measurement-only benchmark (v5 7 step 8, PC-20; CRITERION C6's one exception): one complete dataset,
           r2_034 with options a,fwd, in bank mode and namespace rq2026-d8-recovery-A1-measure, from the snapshot tools
           and the bank inputs. Only completion, timing, RSS and unresolved-integration counts are read (no score,
           selected rank, bound or success); prepare binds its inputs and outputs in FROZEN.sha256 as measurement-only.
           Refused once FROZEN.sha256 exists, and after one benchmark.
  prepare  the freeze: copy and bind the bank/D8 inputs into P_REC/inputs/bank (bank_d8.json, its receipt, the
           provenance receipt, the validation spec, its report and their witness receipt, obs_tables.npz, the #68
           conformance receipt of v5 7 step 6 / T5-4, and the four bank inputs: read-only copies, re-hashed); snapshot
           the tools (obslaw, material, common, noisescale and the
           ages fixture included); the study inputs as rec_C_v2 did; every legacy configuration (recovery.prepare_run)
           and every extra plan (recovery_extra.py prepare) in bank mode and namespace rq2026-d8-recovery-A1; the
           frozen SCHEDULE.json (A_design_v5 3.8 in clarification 4 F1's representation); the top-level
           FROZEN.sha256. No observation is generated.
  run      after the external witness (P_REC/PRIOR.receipt containing FROZEN.sha256's digest): every scheduled run in
           bank mode (--obs-model bank --bank ... --obs-tables ... to every recovery.py run / one and recovery_extra.py
           prepare / run / one), at most 2 concurrent workers in total, then the acceptance packet through `recovery.py
           packet --mode acceptance` only (never diagnostic mode). Exit 0 iff the packet's exit is 0.

Protections kept from rec_C_v2: nice 19 and one BLAS thread (rec_A_v1.sh), an exclusive P_REC lock, process-group
cleanup of every child on TERM / INT, protected roots, no output symlinks, immutable bytes, RETAINED_RESULTS.sha256,
ARTIFACTS.sha256, status.json. A planning-mode configuration or plan anywhere under P_REC is refused. Every child
stays tracked until its whole process group is gone (Codex WP5 P2-W5-2): TERM / INT are blocked from before each
spawn until the child is tracked, and a child that exits abnormally (a recovery supervisor killed alone, say) has
the rest of its group stopped (TERM, then KILL after 8 s) before the wrapper goes on, so no worker outlives the lock.

EXTRA_AVOID (production; rec_C_v2's): a file listing additional reservation paths, one per line. The list and every
listed file are copied into P_REC (inputs/extra_avoid.list, inputs/reservations/), bound in FROZEN.sha256, included in
the collision checks and passed to the fork registration; a listed file that is missing is refused (Codex WP5
P2-W5-1). measure and prepare must see the same inventory (its copies are immutable).

--test-fixture DIR (rec_A_v1.sh: RQ_REC_A_TEST_FIXTURE; TESTS ONLY): the study inventory (registry, reservations,
forks, references, the production graph) is replaced by DIR's toy graph (recovery_toy is required), the schedule by
DIR/schedule.json, the bank/D8 inputs come from DIR/d8 and the authorities from DIR/authority; the frozen pins of the
four registered bank inputs and of the authorities, the resource preflight and prepare's acceptance-completeness
precheck are not applied (recorded in inputs/policy.json), and EXTRA_AVOID is refused. Every other rule is the
production one. The mode, fixture or production, is recorded once in inputs/mode.json (bound in FROZEN.sha256; Codex
WP5 P3-W5-2): a prepare, run or resume of the other mode is refused, and run skips the resource preflight only in a
fixture-frozen root, whose frozen graph must be a recovery toy.
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FINFOLK = Path('/home/harit/finfolk')
PROD = FINFOLK / 'redqueen_2026'
BANK = FINFOLK / 'redqueen_noisebank_2026'
REGSHA = '1193b562fd7c6a202b1b4bd12edbc8ce3855ea60f39458e38845e8d359c61dde'
NS = 'rq2026-d8-recovery-A1'                       # (A_design_v5 3.8, 4.4; CRITERION C5 as v5 6.1 drafts it)
NS_MEASURE = 'rq2026-d8-recovery-A1-measure'       # (v5 7 step 8: the measurement-only benchmark's own namespace)
MAX_WORKERS = 2                                    # (v5 4.4: at most 2 concurrent workers in total)
PACKET_MODE = 'acceptance'                         # (v5 3.8, 4.4: the wrapper never uses diagnostic mode)
MAIN = ['r0', 'r1_017', 'r1_034', 'r2_017', 'r2_034']
STRESS = ['r0_asym', 'r2_034_asym', 'r0_twoway', 'r2_034_clustered', 'r0_ownworld', 'r2_034_noisy', 'r1_017_noisy',
          'r2_017_noisy']
NUMERICAL = ['num_r1', 'num_r2', 'num_r3', 'num_r4']
CASES = ['biological_at', 'biological_after', 'technical', 'pending_prefix', 'pending_attempt', 'mixed', 'roots0',
         'roots1', 'roots2']
FIT = {'ranks': 4, 'lambdas': '0.01,0.02,0.05,0.2', 'iters': 30, 'start': 'both'}   # (CRITERION C2; clarif. 4 F3)
SURFACE = {'basis': 6, 'embedding': 'shared', 'center': 'references'}
# The bank/D8 inputs of A_design_v5 4.4, under these names in the D8 directory (the runbook's steps 1-7) and copied to
# P_REC/inputs/bank/; the four bank inputs with the artifact's inputs key that binds each (v5 0.3, obslaw.INPUT_KEYS).
BANK_ARTIFACT, BANK_RECEIPT, PROVENANCE = 'bank_d8.json', 'bank_d8.receipt.json', 'provenance.json'
VALIDATION_SPEC, VALIDATION_REPORT = 'd8validation.spec.json', 'd8validation.report.json'
VALIDATION_WITNESS, OBS_TABLES = 'd8validation.witness.receipt', 'obs_tables.npz'
CONFORMANCE = 'pr68_conformance.receipt'           # (v5 7 step 6, T5-4: the #68 adoption gate's receipt, bound too)
BANK_INPUTS = {'observations.json': 'observations_sha256', 'ages.json': 'ages_sha256',
               'bank.plan.jsonl': 'plan_sha256', 'bank.design.json': 'design_file_sha256'}
D8_FILES = (BANK_ARTIFACT, BANK_RECEIPT, PROVENANCE, VALIDATION_SPEC, VALIDATION_REPORT, VALIDATION_WITNESS,
            OBS_TABLES, CONFORMANCE, *BANK_INPUTS)
NOISE_SCALES = (1.0, 2.0)                          # (v5 7 step 7: obs-tables --noise-scales 1,2)
# The authorities bound in FROZEN.sha256: the frozen design, its frozen clarifications and amendments by sha256; the
# prelaunch tracker and rec_C_v2's two historical plans by name (their current bytes are bound, not pinned).
AUTHORITIES = {
    'A_design_v5.md': '5d4c00bee7297b102d415571a21dfc8eb43f1debf7308ebaf8e5e2ed7793a266',
    'A_design_v5_clarification_1.md': 'f9b467ac8b8ee4e2957b9010922a68367dba88d475d8988e2e33ad06ce2626bd',
    'A_design_v5_clarification_2.md': 'f6ccc85ea401c83f698e373e9839de9be2dc2d89a10c7ef08c9d65610e393ea2',
    'A_design_v5_clarification_3.md': 'dd50354ab90a7d4ce779f2485a3b6118e3089bb86601cee03e812b25f288cd0f',
    'A_design_v5_clarification_4.md': '87053a80920b83cc16f914396fc2061a34d20e3b54446474d5986458a675eb70',
    'A_design_v5_clarification_4.freeze_addendum.md':
        'a493f35bcc26b091c3b7df48bd0fff780f004030e9cb55c0f3716072b8c73bf8',
    'amendment_D8_v2.md': '566966e9c42952ab1699c47c520b2f61f91afd0228d9f0185be7cd7d027f92c9',
    'amendment_D9_launch_before_registration.md': '6bff81343ae0b58175c6cf36b5ad0ee0a9d92157d62cd570318796ee3a0c0636',
    'redqueen_study_design_v4_codex.md': '15252e6cc8a6e10858738088fc3bba271b38b274124763f402e5da77aede1251',
    'redqueen_annexH_codex.md': 'bfed06bac787b6026eff4956175cf76aae0dcbca8fec29964a43f065dab8dbb3',
    'PRELAUNCH_GATES.md': None, 'recovery_runbook_codex.md': None, 'recovery_tooling_plan_codex.md': None,
}
CHILDREN = set()
SPAWN_SIGNALS = {signal.SIGTERM, signal.SIGINT}    # (blocked from before a spawn until its child is tracked)
TERM_GRACE, KILL_WAIT = 8, 30                      # (seconds: a group's wait after TERM, then after KILL)
STAMP = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
# (set by configure: the root, the snapshot tools, the graph, the bank copies, the worker count, the inputs, test mode)
C = T = G = B = TB = None
JOBS = MAX_WORKERS
D8 = AUTH = CRIT = FIXTURE = None
TEST = False


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def canonical(value):
    """rqlib.canonical's encoding (sorted keys, no spaces, ASCII, no NaN, a trailing newline)."""
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
            + '\n').encode('ascii')


def dump(p, value):
    same(p, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def same(p, data):
    """Immutable bytes: an existing file must already hold exactly data (a new P_REC otherwise)."""
    p = Path(p)
    if p.exists():
        if p.read_bytes() != data:
            raise RuntimeError(f'conflicting immutable bytes: {p}')
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def copy(src, dst, read_only=False):
    src = Path(src)
    if not src.is_file():
        raise RuntimeError(f'missing input: {src}')
    data = src.read_bytes()
    same(dst, data)
    if read_only:
        os.chmod(dst, 0o444)
    return {'source': str(src.resolve()), 'copy': str(Path(dst).relative_to(C)), 'sha256': hashlib.sha256(
        data).hexdigest()}


def group_alive(pgid):
    """Whether process group pgid still has a member (killpg(pgid, 0); an unreaped zombie is still a member)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_children():
    """Process-group cleanup (rec_C_v2; Codex WP5 P2-W5-2): every child is a group leader (start_new_session) and stays
    in CHILDREN until its WHOLE group is gone, its exited leader included (a supervisor can exit before its workers).
    TERM every group, wait until each has no member (reaping our own exited leaders: a zombie leader keeps its group)
    or 8 s, KILL every group left and wait again (at most 30 s) -> the groups that still have members ([]: every
    child and every worker of every child is gone)."""
    for p in list(CHILDREN):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGTERM)
    for sig, wait in ((None, TERM_GRACE), (signal.SIGKILL, KILL_WAIT)):
        for p in list(CHILDREN) if sig else ():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, sig)
        deadline = time.monotonic() + wait
        while True:
            for p in list(CHILDREN):
                p.poll()                                  # (reaps an exited leader of ours; a known exit is kept)
                if p.returncode is not None and not group_alive(p.pid):
                    CHILDREN.discard(p)
            if not CHILDREN or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        if not CHILDREN:
            break
    return sorted(p.pid for p in CHILDREN)


def interrupted(sig, frame):
    raise KeyboardInterrupt(f'signal {sig}')


def spawn(cmd, out):
    """subprocess.Popen in its own process group, tracked in CHILDREN before TERM / INT can act (Codex WP5 P2-W5-2;
    recovery_extra.run's pattern): both are blocked from before the fork until the child is in CHILDREN, so a signal in
    between is delivered once the child can be stopped; the child starts with the wrapper's own mask (preexec_fn
    restores it before exec)."""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, SPAWN_SIGNALS)
    try:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, old))
        CHILDREN.add(p)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)
    return p


def call(args, label, check=True):
    """One child (sys.executable -I -B args) in its own process group, logged and timed (wall, user / system CPU and
    the maximum RSS from wait4) -> its exit code; a nonzero exit raises unless check is False. The child leaves
    CHILDREN only once its whole group is gone (Codex WP5 P2-W5-2): after a nonzero exit, or with members of its group
    still running, the group is stopped (stop_children) while it is still tracked, so a recovery supervisor killed
    alone never leaves its workers running past the wrapper's lock; members left by an exit 0 fail the stage."""
    log, timing = C / 'logs' / f'{STAMP}.{label}.log', C / 'timing' / f'{STAMP}.{label}.json'
    cmd = [sys.executable, '-I', '-B', *map(str, args)]
    print(shlex.join(cmd), flush=True)
    t0 = time.time()
    with log.open('ab') as f:
        p = spawn(cmd, f)
        _, status, ru = os.wait4(p.pid, 0)
        p.returncode = os.waitstatus_to_exitcode(status)
    rc = p.returncode
    members = group_alive(p.pid)
    if rc or members:           # (an abnormal exit or a group still running: stopped before the child is released)
        left = stop_children()
    else:
        left = []
        CHILDREN.discard(p)
    dump(timing, {'label': label, 'command': cmd, 'exit': rc, 'wall_s': round(time.time() - t0, 3),
                  'user_s': ru.ru_utime, 'system_s': ru.ru_stime, 'max_rss_kib': ru.ru_maxrss})
    if left:
        raise RuntimeError(f'{label}: exit {rc}; INTEGRITY: process group(s) {left} still have members after SIGKILL')
    if members and not rc:
        raise RuntimeError(f'{label}: exit 0 with processes of its group still running (stopped): not a completed '
                           f'stage; see {log}')
    if rc and check:
        raise RuntimeError(f'{label}: exit {rc}{"; the rest of its process group stopped" if members else ""}; '
                           f'see {log}')
    return rc


def modules(*names):
    sys.path.insert(0, str(T))
    import importlib
    return [importlib.import_module(n) for n in names]


def bank_flags():
    """The bank flags every recovery.py run / one and recovery_extra.py prepare / run / one receives (v5 4.4); never
    --allow-synthetic-bank."""
    return ['--obs-model', 'bank', '--bank', B, '--obs-tables', TB]


# ------------------------------------------------------------------ the schedule (CRITERION C2-C4; v5 3.8 roles)
def schedule_spec():
    """The frozen C2 matrix as directories: legacy (name, role, scenarios, reps, options, surface) and extra (name,
    role, options, cases, scenarios, reps); the fit is CRITERION C2's for every noisy fit and clarification 4 F3's for
    the numerical role. Test mode: the fixture's schedule.json (the same structure)."""
    if TEST:
        return json.loads((FIXTURE / 'schedule.json').read_text())
    legacy = [dict(name='main', role='C1-primary', scenarios=MAIN, reps=20, options=['a', 'fwd'], **SURFACE)]
    legacy += [dict(name=f'stress_{s}', role='stress', scenarios=[s], reps=10, options=['a', 'fwd'], **SURFACE)
               for s in STRESS]
    legacy += [dict(name=f'numerical_{s}', role='numerical', scenarios=[s], reps=1, options=['a'], **SURFACE)
               for s in NUMERICAL]
    for name, change in (('basis4', {'basis': 4}), ('basis8', {'basis': 8}), ('separate', {'embedding': 'separate'}),
                         ('train_c', {'center': 'train_c'})):
        legacy.append(dict(name=name, role='sensitivity', scenarios=MAIN, reps=20, options=['a', 'fwd'],
                           **dict(SURFACE, **change)))
    extra = [dict(name=op, role=f'extra-{op}', options=[op], cases=['intact'], scenarios=MAIN, reps=20)
             for op in ('interp', 'fwd_all', 'fwd_early')]
    extra.append(dict(name='attrition', role='extra-attrition', options=['a', 'interp', 'fwd_all', 'fwd_early'],
                      cases=CASES, scenarios=['r0'], reps=1))
    return {'namespace': NS, 'legacy': legacy, 'extra': extra}


def fit_of(spec):
    return dict(FIT, **spec.get('fit', {})) if TEST else dict(FIT)


def fit_args(fit, x):
    return ['--ranks', str(fit['ranks']), '--lambdas', fit['lambdas'], '--iters', str(fit['iters']), '--start',
            fit['start'], '--basis', str(x.get('basis', 6)), '--embedding', x.get('embedding', 'shared'), '--center',
            x.get('center', 'references')]


def schedule_document(spec):
    """SCHEDULE.json (A_design_v5 3.8; clarification 4 F1): exactly schema, observation_model_sha256 (the one model
    every configuration, plan and result carries), inputs {graph, references, bank, obs_tables} and directories (each
    with exactly v5 3.8's fields and its expected configuration / plan sha256), every path relative to P_REC (the
    schedule file's directory) -> the document, from the prepared directories."""
    dirs, models = [], set()
    for x in spec['legacy']:
        cfg = json.loads((C / 'runs' / x['name'] / 'config.json').read_text())
        models.add(hashlib.sha256(canonical(cfg['observation_model'])).hexdigest())
        dirs.append({'dir': f"runs/{x['name']}", 'kind': 'legacy', 'role': x['role'], 'scenarios': list(x['scenarios']),
                     'reps': x['reps'], 'options': list(x['options']),
                     'expected_config_sha256': hashlib.sha256(canonical(cfg)).hexdigest()})
    for x in spec['extra']:
        plan = json.loads((C / 'extra' / x['name'] / 'plan.json').read_text())
        models.add(plan['inputs']['observation_model_sha256'])
        dirs.append({'dir': f"extra/{x['name']}", 'kind': 'extra', 'role': x['role'], 'scenarios': list(x['scenarios']),
                     'reps': x['reps'], 'options': list(x['options']), 'cases': list(x['cases']),
                     'expected_plan_sha256': hashlib.sha256(canonical(plan)).hexdigest()})
    if len(models) != 1:
        raise RuntimeError(f'the scheduled directories carry {len(models)} observation models (exactly one)')
    return {'schema': 'finfolk.redqueen.recoveryschedule/1', 'observation_model_sha256': models.pop(),
            'inputs': {'graph': 'inputs/graph/graph.jsonl.gz', 'references': None,
                       'bank': f'inputs/bank/{BANK_ARTIFACT}', 'obs_tables': f'inputs/bank/{OBS_TABLES}'},
            'directories': dirs}


def refuse_planning():
    """Every configuration (runs/*/config.json) and plan (extra/*/plan.json) under P_REC must be bank mode, accepting
    and of namespace rq2026-d8-recovery-A1, and measure/'s configuration bank mode in the measurement namespace: a
    planning-mode or other configuration is refused (v5 3.7, 4.4)."""
    for p in sorted((C / 'runs').glob('*/config.json')) + sorted((C / 'measure').glob('*/config.json')):
        cfg = json.loads(p.read_text())
        om = cfg.get('observation_model') or {}
        ns = NS_MEASURE if p.parent.parent.name == 'measure' else NS
        if om.get('mode') != 'bank' or om.get('noise_source') != 'bank_d8' or om.get('accepting') is not True \
                or cfg.get('namespace') != ns:
            raise RuntimeError(f'{p.relative_to(C)}: a planning-mode or non-accepting configuration, or another '
                               f'namespace (mode {om.get("mode")!r}, namespace {cfg.get("namespace")!r}): refused')
    for p in sorted((C / 'extra').glob('*/plan.json')):
        plan = json.loads(p.read_text())
        if plan.get('noise_source') != 'bank_d8' or plan.get('accepting') is not True or plan.get('namespace') != NS:
            raise RuntimeError(f'{p.relative_to(C)}: a planning-mode or non-accepting plan, or another namespace '
                               f'(noise_source {plan.get("noise_source")!r}): refused')


# ------------------------------------------------------------------ inputs
def snapshot_tools(criterion=True):
    """The tool snapshot: every non-test tools/redqueen/*.py (obslaw, material, common and noisescale included), the
    ages fixture, and this wrapper pair in control/ with the criterion (immutable copies; the measurement-only
    benchmark, which precedes the criterion's adoption, v5 7 steps 8-9, binds no criterion)."""
    import numpy as np
    if np.__version__ != '2.3.4' and not TEST:
        raise RuntimeError('NumPy 2.3.4 required')
    prov = [copy(HERE / n, C / 'control' / n) for n in ('rec_A_v1.sh', 'rec_A_v1.py')]
    if criterion:
        text = Path(CRIT).read_text()
        if 'rec_A_v1' not in text or NS not in text:
            raise RuntimeError(f'{CRIT}: not a rec_A_v1 criterion (it must name rec_A_v1 and {NS})')
        prov.append(copy(CRIT, C / 'control' / 'CRITERION.txt'))
    for p in sorted(HERE.glob('*.py')):
        if not p.name.startswith('test_'):
            prov.append(copy(p, T / p.name))
    for n in ('obslaw.py', 'material.py', 'common.py', 'noisescale.py', 'recovery.py', 'recovery_extra.py', 'map.py'):
        if not (T / n).is_file():
            raise RuntimeError(f'tool snapshot lacks {n}')
    prov.append(copy(HERE / 'fixtures' / 'registered_ages.json', T / 'fixtures' / 'registered_ages.json'))
    return prov


def authorities():
    prov = []
    for n, pin in AUTHORITIES.items():
        p = Path(AUTH) / n
        if not p.is_file():
            raise RuntimeError(f'authority {n} missing from {AUTH}')
        if pin and not TEST and sha(p) != pin:
            raise RuntimeError(f'authority {n} is not the frozen {pin[:8]}...')
        prov.append(copy(p, C / 'authority' / n))
    return prov


def bank_inputs():
    """The bank/D8 inputs (v5 4.4): each D8 file copied read-only into P_REC/inputs/bank (an existing identical copy
    stays) and re-hashed; the artifact and its tables load and validate through the snapshot obslaw (every noise
    multiplier v5 7 step 7 tabulates, no synthetic bank); the artifact binds the copies it names (its inputs'
    provenance and validation report, its refit receipt), the witness receipt names the validation spec's digest
    and, in production, the four bank inputs are the registered bytes the artifact binds (v5 0.3)."""
    prov = [copy(Path(D8) / n, C / 'inputs' / 'bank' / n, read_only=True) for n in D8_FILES]
    obslaw, rec = modules('obslaw', 'recovery')
    art = obslaw.BankArtifact(str(B))
    spec = schedule_spec()
    gammas = {1.0} | {rec.scenario_gamma(s) for x in spec['legacy'] + spec['extra'] for s in x['scenarios']}
    obslaw.BankObservationModel(str(B), str(TB), gammas=tuple(sorted(gammas)))
    inputs, noise = art.doc['inputs'], art.doc['fit']['noise']
    bound = {PROVENANCE: inputs['provenance_sha256'], VALIDATION_REPORT: inputs['validation_report_sha256'],
             BANK_RECEIPT: noise['receipt_sha256']}
    if not TEST:
        bound.update({n: inputs[k] for n, k in BANK_INPUTS.items()})
        for n, k in BANK_INPUTS.items():
            if inputs[k] != obslaw.REGISTERED_INPUTS[k]:
                raise RuntimeError(f'the bank artifact binds {k} {inputs[k][:8]}..., not the registered input')
    for n, want in bound.items():
        if sha(C / 'inputs' / 'bank' / n) != want:
            raise RuntimeError(f'inputs/bank/{n} is not the file the bank artifact binds ({want[:8]}...)')
    if sha(C / 'inputs' / 'bank' / VALIDATION_SPEC) not in (C / 'inputs' / 'bank' / VALIDATION_WITNESS).read_text():
        raise RuntimeError('the validation witness receipt does not contain the validation spec digest')
    if art.sha256 not in (C / 'inputs' / 'bank' / CONFORMANCE).read_text():
        raise RuntimeError('the #68 conformance receipt (T5-4) does not name this bank artifact\'s sha256')
    return prov


def study_inputs():
    """The study inventory: production (rec_C_v2's, unchanged but for the bank paths: the registry and its
    verification, every reservation, the bank's frozen avoidance provenance and plan, the runtime, the graph, the forks,
    the reference slots) or, in test mode, the fixture's toy graph alone."""
    import numpy as np
    runtime = {'python': sys.version, 'executable': str(Path(sys.executable).resolve()), 'numpy': np.__version__,
               'numpy_file': str(Path(np.__file__).resolve()), 'noise_source': 'bank_d8'}
    dump(C / 'inputs/runtime.json', runtime)
    files = {str(Path(sys.executable).resolve())}
    site = Path(np.__file__).resolve().parent.parent
    for n in ('numpy', 'numpy.libs', f'numpy-{np.__version__}.dist-info'):
        files.update(str(p.resolve()) for p in (site / n).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    dump(C / 'inputs/runtime_files.json', {p: sha(p) for p in sorted(files)})
    if TEST:
        prov = [copy(FIXTURE / 'graph' / n, C / 'inputs/graph' / n) for n in ('graph.jsonl.gz', 'graph.meta.json')]
        graph, rec = modules('graph', 'recovery')
        g = graph.load(str(G))
        if not g.get('recovery_toy'):
            raise RuntimeError('--test-fixture needs a recovery toy graph (never a registered graph)')
        dump(C / 'inputs/policy.json', {'mode': 'TEST FIXTURE (not a recovery input)', 'graph': 'toy',
                                        'graph_identity': rec.graph_identity(g), 'noise': 'bank_d8',
                                        'not_applied': ['study inventory', 'registered bank-input pins',
                                                        'authority pins', 'resource preflight',
                                                        'acceptance-completeness precheck']})
        return prov
    return production_inputs()


def reservations(reg):
    """The reservation inventory (rec_C_v2.py:106-137): the registry's avoidance records and the bank's frozen
    avoidance provenance (each verified by sha256), every production reservation file and, with EXTRA_AVOID
    (rec_C_v2.py:120-125, 129-130; Codex WP5 P2-W5-1), every file its list names (one path per line; a missing one is
    refused), all copied into inputs/reservations/; the list itself is copied to inputs/extra_avoid.list and read
    from that copy. The registry's originals, the seed-named production reservations and every listed file are the
    collision paths (the avoidance checks and the fork registration read them) -> (provenance, collision paths)."""
    prov = []
    records = list(reg['avoid'])
    bank_sources = BANK / 'config/production_avoid_sources.json'
    prov.append(copy(bank_sources, C / 'inputs/bank/production_avoid_sources.json'))
    records += json.loads(bank_sources.read_text())
    external = {}
    for r in records:
        p = Path(r['path'])
        if not p.is_file() or sha(p) != r['sha256']:
            raise RuntimeError(f'reservation provenance missing/changed: {p}')
        external[str(p)] = p
    for p in sorted((PROD / 'reservations').iterdir()):
        if p.is_file():
            external[str(p)] = p
    listed = []
    if os.environ.get('EXTRA_AVOID'):
        prov.append(copy(Path(os.environ['EXTRA_AVOID']).resolve(), C / 'inputs/extra_avoid.list'))
        for line in (C / 'inputs/extra_avoid.list').read_text().splitlines():
            if line.strip():
                p = Path(line.strip()).resolve()
                if not p.is_file():
                    raise RuntimeError(f'EXTRA_AVOID lists a missing reservation file: {p}')
                listed.append(p)
                external[str(p)] = p
    paths, originals = [], {str(Path(x['path'])) for x in reg['avoid']}
    originals.update(str(p) for p in (PROD / 'reservations').iterdir() if p.is_file() and 'seed' in p.name)
    originals.update(str(p) for p in listed)
    for i, (original, p) in enumerate(sorted(external.items())):
        dst = C / 'inputs/reservations' / f'{i:03d}.{p.name}'
        prov.append(copy(p, dst))
        if original in originals:
            paths.append(str(dst))
    return prov, paths


def production_inputs():
    """rec_C_v2's snapshot_inputs + build_inputs (server-verified there), with NS and the bank paths of A: production
    only (it needs the production registry). The tests run it only on a toy registry with toy reservation and fork
    metadata (TestRecAV1Wrapper's inventory test; never a real input). Rechecked line by line against rec_C_v2.py
    (Codex WP5 P2-W5-1): EXTRA_AVOID restored (reservations()), the nine seeds per reserved slot checked again
    (rec_C_v2.py:157), and the planning graph and fork registry re-derived on every call as rec_C_v2 did (graph.py's
    write and same() accept only the same bytes: measure's and prepare's inventories must agree)."""
    graph, worlds, sealing, forks, rec, extra = modules('graph', 'worlds', 'sealing', 'forks', 'recovery',
                                                        'recovery_extra')
    prov = []
    for n in ('worlds.json', 'registry.verify.json', 'reservation_sources.json', 'arena.selected.json'):
        prov.append(copy(PROD / 'config' / n, C / 'inputs/study/config' / n))
    reg = json.loads((C / 'inputs/study/config/worlds.json').read_text())
    if sha(C / 'inputs/study/config/worlds.json') != REGSHA:
        raise RuntimeError('registry changed')
    rprov, paths = reservations(reg)
    prov += rprov
    for n in ('bank.plan.jsonl', 'bank.design.json', 'readiness.json'):
        prov.append(copy(BANK / 'config' / n, C / 'inputs/bank' / n))
    dump(C / 'inputs/avoid_paths.json', paths)
    verify = json.loads((C / 'inputs/study/config/registry.verify.json').read_text())
    assert verify['ok'] and verify['registry_sha256'] == REGSHA
    assert reg['namespace'] == 'finfolk-rq-production-2026-11-d6d7-v1'
    assert sealing.layout_of(reg['worlds'])['registered_64']
    assert reg['max_restarts'] == 8 and len(reg['reserved']) == 64
    assert all(len(x['seeds']) == 9 for x in reg['reserved']), 'a reserved slot without exactly nine seeds'
    hist = {s for x in reg['reserved'] for s in x['seeds']}
    assert len(hist) == 576 and all(0 < s < 2 ** 32 for s in hist)
    plan_rows = [json.loads(s) for s in (C / 'inputs/bank/bank.plan.jsonl').read_text().splitlines() if s.strip()]
    assert len(plan_rows) == 18432 and all(x['schema'] == 'finfolk.redqueen.plan/2' for x in plan_rows)
    bs = worlds.read_avoid(str(C / 'inputs/bank/bank.plan.jsonl'))
    assert bs and not bs & hist
    counts = []
    for p in paths:
        seeds = worlds.read_avoid(p)
        assert seeds, f'zero seeds extracted: {p}'
        overlap = bs & seeds
        if overlap and not (p.endswith('.noisebank.seeds.json') and seeds == bs):
            raise RuntimeError(f'bank shares unrelated avoidance seeds: {p}')
        assert not seeds & hist, f'history shares avoidance seeds: {p}'
        counts.append({'path': p, 'seeds': len(seeds), 'overlap_bank': len(overlap)})
    dump(C / 'inputs/avoid_checks.json', {'history_unique': len(hist), 'bank_rows': len(plan_rows),
                                          'bank_unique_seeds': len(bs), 'files': counts})
    pg = PROD / 'graph'
    if (pg / 'graph.jsonl.gz').exists() or (pg / 'graph.meta.json').exists():
        for n in ('graph.jsonl.gz', 'graph.meta.json'):
            prov.append(copy(pg / n, C / 'inputs/graph' / n))
        graph_policy = 'copied existing production graph'
    else:                       # (re-derived on every call, as rec_C_v2: graph.py write accepts only the same bytes)
        call([T / 'graph.py', 'build', '--registry', C / 'inputs/study/config/worlds.json', '--namespace',
              'rq2026-d6d7-graph', '--snapshot-topup', '6', '--ab-topup', '8', '--ab-topup-mode', 'fitting',
              '--lag-probe', '7', '--out', G.parent], 'graph-build')
        graph_policy = 'INTENDED production graph; not yet published in production root'
    g = graph.load(str(G))
    assert not graph.check_quotas(g)
    assert g.get('registry') == graph.registry_binding(str(C / 'inputs/study/config/worlds.json'))
    assert g['train_matchings'] and not g.get('recovery_toy')
    dump(C / 'inputs/graph/report.json', graph.report(g))
    fp = PROD / 'config/forks.json'
    if fp.exists():
        prov.append(copy(fp, C / 'inputs/study/config/forks.json'))
        fork_policy = 'actual production registry'
    else:                       # (re-registered on every call, as rec_C_v2: same() accepts only the same bytes)
        f = forks.register(str(C / 'inputs/study'), str(G.parent / 'graph.meta.json'), 'rq2026-d6d7-replay',
                           avoid_paths=[str(C / 'inputs/bank/bank.plan.jsonl'),
                                        str(C / 'inputs/study/config/worlds.json'), *paths])
        same(C / 'inputs/study/config/forks.json', canonical(f))
        fork_policy = 'PLANNING registry only; not published production forks'
    f = json.loads((C / 'inputs/study/config/forks.json').read_text())
    assert f['worlds_registry']['sha256'] == REGSHA
    assert set(f['fork_worlds']) == set(g['fork'])
    fs = {x['origin']['seed'] for x in f['worlds']}
    assert len(fs) == len(f['worlds']) and not fs & hist and not fs & bs
    for p in paths:
        assert not fs & worlds.read_avoid(p), p
    if (PROD / 'config/references.json').exists():
        raise RuntimeError('actual references appeared: inventory/copy all studies_checked receipt dependencies in a '
                           'new reviewed freeze (rec_C_v2: this version uses the planning slots)')
    dump(C / 'inputs/reference_slots.json', {'assumed': list(rec.REF_TIMES), 'sentinels': ['w01', 'w02', 'w03', 'w06'],
                                             'qualification': 'design:404 deterministic later relabelling; topology/'
                                                              'support changes require rerun'})
    dump(C / 'inputs/policy.json', {'graph': graph_policy, 'forks': fork_policy,
                                    'references': 'PLANNING reference slots; no actual reference validation',
                                    'graph_identity': rec.graph_identity(g), 'noise': 'bank_d8 (A_design_v5)'})
    return prov


def mode_name():
    return 'fixture' if TEST else 'production'


def frozen_mode():
    """The mode this root was frozen in (inputs/mode.json, bound in FROZEN.sha256; Codex WP5 P3-W5-2), which must be
    this invocation's (--test-fixture or not) -> it; another or no recorded mode is refused."""
    p = C / 'inputs/mode.json'
    mode = json.loads(p.read_text()).get('mode') if p.is_file() else None
    if mode != mode_name():
        raise RuntimeError(f'P_REC was frozen in {mode or "an unrecorded"} mode and this invocation is {mode_name()} '
                           f'mode (--test-fixture / RQ_REC_A_TEST_FIXTURE): refused')
    return mode


def all_inputs(freeze=True):
    """The tools, the authorities, the bank/D8 inputs and the study inputs, bound in inputs/provenance.json (prepare);
    the measurement-only benchmark takes the tools, the bank/D8 inputs and the study inputs only. First the mode is
    recorded (once: measure and prepare must agree) and, in fixture mode, EXTRA_AVOID is refused (a production study
    input the fixture has no inventory for)."""
    if TEST and os.environ.get('EXTRA_AVOID'):
        raise RuntimeError('EXTRA_AVOID is a production study input; --test-fixture has no study inventory: refused')
    if (C / 'inputs/mode.json').exists():
        frozen_mode()
    dump(C / 'inputs/mode.json', {'mode': mode_name()})
    if not freeze:
        snapshot_tools(criterion=False)
        bank_inputs()
        study_inputs()
        return
    prov = snapshot_tools() + authorities() + bank_inputs() + study_inputs()
    dump(C / 'inputs/provenance.json', prov)


# ------------------------------------------------------------------ phases
PREPARE_LEGACY = ('import argparse, json, sys\nsys.path.insert(0, sys.argv[1])\nimport recovery\n'
                  'print(recovery.prepare_run(argparse.Namespace(**json.loads(sys.argv[2]))))\n')


def prepare_legacy(x, fit, out, ns):
    """recovery.prepare_run in a child from the snapshot tools (the configuration only: no observation)."""
    a = dict(graph=str(G), references=None, out=str(out), namespace=ns, fitter='registered',
             options=','.join(x['options']), ranks=fit['ranks'], lambdas=fit['lambdas'], iters=fit['iters'],
             start=fit['start'], basis=x.get('basis', 6), embedding=x.get('embedding', 'shared'),
             center=x.get('center', 'references'), ab_cap=-1, scenarios=','.join(x['scenarios']), set=None,
             reps=x['reps'], obs_model='bank', bank=str(B), obs_tables=str(TB), allow_synthetic_bank=False)
    call(['-c', PREPARE_LEGACY, T, json.dumps(a)], f'prepare-{out.name}')


def unresolved_integrations(rec, branches):
    """MEASUREMENT.json's unresolved-integration counts: pairs whose count score is finite but UNRESOLVED
    (map.pred_count_lpd's grid_unresolved), per option and stored integration record, reported separately and never
    summed (Codex WP5 P3-W5-1). candidates: every candidate's validation and test integration records. branch_tests:
    each forward branch's test-comparison records, the selected and the rank-0 model's, stored under the branch
    (recovery.py forward_procedure: a branch's comparison is not among the candidates'). Reads no score, selected rank,
    bound or success (CRITERION C6)."""
    def n(info):
        return int((info or {}).get('grid_unresolved', 0))
    return {
        'label': 'pairs with grid_unresolved per stored integration record, not summed: candidates = every '
                 'candidate\'s validation and test records; branch_tests = each forward branch\'s test comparison, its '
                 'selected and rank-0 records (stored under the branch)',
        'candidates': {opt: sum(n((c.get('integration') or {}).get(s)) for c in o.get('candidates', ())
                                for s in ('validation', 'test')) for opt, o in rec['options'].items()},
        'branch_tests': {opt: {b: {k: n((o[b].get('integration') or {}).get(k)) for k in ('selected', 'rank0')}
                               for b in branches if isinstance(o.get(b), dict)}
                         for opt, o in rec['options'].items()}}


def measure():
    """The measurement-only benchmark (v5 7 step 8, PC-20; CRITERION C6): before the freeze, once."""
    if (C / 'FROZEN.sha256').exists():
        raise RuntimeError('the measurement-only benchmark precedes the freeze (CRITERION C6): FROZEN.sha256 exists')
    if (C / 'measure/MEASUREMENT.json').exists() or any((C / 'measure').glob('*/*.*.json')):
        raise RuntimeError('a measurement-only benchmark exists: it is a single dataset (CRITERION C6)')
    all_inputs(freeze=False)
    out = C / 'measure/r2_034'
    x = dict(scenarios=['r2_034'], reps=1, options=['a', 'fwd'], **SURFACE)
    prepare_legacy(x, FIT, out, NS_MEASURE)
    refuse_planning()
    args = [T / 'recovery.py', 'run', '--graph', G, '--namespace', NS_MEASURE, '--fitter', 'registered', '--options',
            'a,fwd', *fit_args(FIT, x), '--scenarios', 'r2_034', '--reps', '1', '--jobs', '1', *bank_flags(),
            '--out', out]
    call(args, 'measure-r2_034')
    rec = json.loads((out / 'r2_034.000.json').read_text())
    timing = json.loads((C / 'timing' / f'{STAMP}.measure-r2_034.json').read_text())
    (recovery,) = modules('recovery')
    unresolved = unresolved_integrations(rec, recovery.BRANCHES)
    dump(C / 'measure/MEASUREMENT.json', {
        'label': 'MEASUREMENT-ONLY (CRITERION C6): never an acceptance realization; only completion, timing, RSS and '
                 'unresolved-integration counts are read', 'namespace': NS_MEASURE, 'scenario': 'r2_034',
        'options': ['a', 'fwd'], 'completed': True, 'wall_s': timing['wall_s'],
        'cpu_s': round(timing['user_s'] + timing['system_s'], 3), 'max_rss_kib': timing['max_rss_kib'],
        'unresolved_integration_pairs': unresolved})
    print('MEASURED (measurement-only); prepare binds it', flush=True)


def prepare():
    if (C / 'FROZEN.sha256').exists():
        check_freeze()
        print('already prepared; immutable freeze verified', flush=True)
        return
    if any((C / 'runs').glob('**/*.*.json')) or any((C / 'extra').glob('**/results/*.json')):
        raise RuntimeError('recovery results exist before freeze')
    all_inputs()
    spec = schedule_spec()
    if spec.get('namespace', NS) != NS:
        raise RuntimeError(f'the schedule namespace must be {NS}')
    fit = fit_of(spec)
    for x in spec['legacy']:
        prepare_legacy(x, fit, C / 'runs' / x['name'], NS)
    for x in spec['extra']:
        call([T / 'recovery_extra.py', 'prepare', '--graph', G, '--namespace', NS, '--options', ','.join(x['options']),
              '--cases', ','.join(x['cases']), '--scenarios', ','.join(x['scenarios']), '--reps', str(x['reps']),
              *fit_args(fit, {k: fit[k] for k in SURFACE if k in fit}), *bank_flags(),
              *(['--allow-toy'] if TEST else []), '--out', C / 'extra' / x['name']],
             f"prepare-extra-{x['name']}")
    refuse_planning()
    doc = schedule_document(spec)
    same(C / 'SCHEDULE.json', canonical(doc))
    (rec,) = modules('recovery')
    entries = rec._schedule_entries(json.loads((C / 'SCHEDULE.json').read_text()), str(C))   # (F1's parser)
    if not TEST:
        gaps = rec.schedule_gaps(entries) + rec.bound_settings_gaps(entries)
        if gaps:
            raise RuntimeError('the schedule does not satisfy the frozen C2 matrix: ' + '; '.join(gaps))
    if (C / 'measure').exists():
        same(C / 'MEASUREMENT_ONLY.sha256', ''.join(
            f'{sha(p)}  {p.relative_to(C)}\n' for p in sorted((C / 'measure').rglob('*')) if p.is_file()).encode())
    same(C / 'FROZEN.sha256', frozen_manifest())
    check_freeze()
    print('PREPARED, no recovery observations generated. Witness:', sha(C / 'FROZEN.sha256'), flush=True)


def frozen_manifest():
    """FROZEN.sha256's bytes: every file under control/, authority/, inputs/ (the bank/D8 copies, the mode, the study
    inventory with EXTRA_AVOID's list and reservations), tools/, runs/, extra/ and measure/, then SCHEDULE.json and
    MEASUREMENT_ONLY.sha256, sorted."""
    frozen = []
    for sub in ('control', 'authority', 'inputs', 'tools', 'runs', 'extra', 'measure'):
        for p in sorted((C / sub).rglob('*')):
            if p.is_file() and not p.name.startswith('.'):
                frozen.append(f'{sha(p)}  {p.relative_to(C)}\n')
    for n in ('SCHEDULE.json', 'MEASUREMENT_ONLY.sha256'):
        if (C / n).exists():
            frozen.append(f'{sha(C / n)}  {n}\n')
    return ''.join(sorted(frozen)).encode()


def check_freeze():
    """Every FROZEN.sha256 entry, the frozen mode (= this invocation's), the active wrapper (= its control copy), the
    runtime, the schedule (re-derived from the frozen configurations and plans, byte for byte) and the bank mode of
    everything under P_REC."""
    names = set()
    for line in (C / 'FROZEN.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        p = (C / name).resolve()
        if not p.is_relative_to(C) or not p.is_file() or sha(p) != digest:
            raise RuntimeError(f'frozen input changed: {name}')
        names.add(name)
    if 'inputs/mode.json' not in names:
        raise RuntimeError('the freeze does not bind the mode (inputs/mode.json): refused')
    frozen_mode()
    for n in ('rec_A_v1.sh', 'rec_A_v1.py'):
        if sha(HERE / n) != sha(C / 'control' / n):
            raise RuntimeError(f'active orchestrator changed: {n}')
    for name, digest in json.loads((C / 'inputs/runtime_files.json').read_text()).items():
        if sha(name) != digest:
            raise RuntimeError(f'runtime changed: {name}')
    if sys.version != json.loads((C / 'inputs/runtime.json').read_text())['python']:
        raise RuntimeError('Python changed')
    if canonical(schedule_document(schedule_spec())) != (C / 'SCHEDULE.json').read_bytes():
        raise RuntimeError('schedule changed')
    refuse_planning()


def run():
    check_freeze()
    prior = C / 'RETAINED_RESULTS.sha256'
    if prior.exists():
        for line in prior.read_text().splitlines():
            digest, name = line.split('  ', 1)
            if sha(C / name) != digest:
                raise RuntimeError(f'retained result changed: {name}')
    receipt = C / 'PRIOR.receipt'
    if not receipt.is_file() or sha(C / 'FROZEN.sha256') not in receipt.read_text():
        raise RuntimeError('authentic pre-result external witness receipt containing the freeze digest required '
                           '(P_REC/PRIOR.receipt)')
    if frozen_mode() == 'production':      # (rec_C_v2's conservative preflight, at 2 workers)
        available = int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines()
                             if s.startswith('MemAvailable:'))) * 1024
        if available < (8 + 4 * JOBS) * 1024 ** 3:
            raise RuntimeError('need 8 GiB headroom + 4 GiB/worker')
        if shutil.disk_usage(C).free < 60 * 1024 ** 3:
            raise RuntimeError('need 50 GiB free reserve + 10 GiB recovery allowance')
    else:                                  # (no preflight only in a fixture-frozen root, on its frozen toy graph)
        (graph,) = modules('graph')
        if not graph.load(str(G)).get('recovery_toy'):
            raise RuntimeError('a fixture-frozen root must hold a recovery toy graph (never a registered graph): '
                               'refused')
    spec = schedule_spec()
    fit = fit_of(spec)
    call([T / 'recovery.py', 'conditioning', '--graph', G, '--out', C / 'conditioning.json'], 'conditioning')
    for x in spec['legacy']:
        check_freeze()
        call([T / 'recovery.py', 'run', '--graph', G, '--namespace', NS, '--fitter', 'registered', '--options',
              ','.join(x['options']), *fit_args(fit, x), '--scenarios', ','.join(x['scenarios']), '--reps',
              str(x['reps']), '--jobs', str(JOBS), *bank_flags(), '--out', C / 'runs' / x['name']],
             f"legacy-{x['name']}")
        call([T / 'recovery.py', 'summarize', '--dir', C / 'runs' / x['name'], '--out',
              C / 'summaries' / f"{x['name']}.json"], f"summarize-{x['name']}")
    for x in sorted(spec['extra'], key=lambda x: x['role'] == 'extra-attrition'):     # (one at a time, attrition last)
        check_freeze()
        call([T / 'recovery_extra.py', 'run', '--dir', C / 'extra' / x['name'], '--graph', G, '--jobs',
              str(min(2, JOBS)), *bank_flags()], f"extra-{x['name']}")
        call([T / 'recovery_extra.py', 'summarize', '--dir', C / 'extra' / x['name'], '--out',
              C / 'summaries' / f"extra-{x['name']}.json"], f"summarize-extra-{x['name']}")
    check_freeze()
    out = C / f'acceptance.{STAMP}.json'
    rc = call([T / 'recovery.py', 'packet', '--mode', PACKET_MODE, '--schedule', C / 'SCHEDULE.json', '--out', out],
              'packet', check=False)
    print(f'acceptance packet ({PACKET_MODE}): exit {rc}, {out.name if out.exists() else "no packet file"}', flush=True)
    if rc:
        raise RuntimeError(f'the acceptance packet exits {rc} (incomplete, a failed check or a refused schedule): '
                           f'see {out.name if out.exists() else "the packet log"}')


def checkpoint_results():
    p = C / 'RETAINED_RESULTS.sha256'
    bound = {}
    if p.exists():
        for line in p.read_text().splitlines():
            digest, name = line.split('  ', 1)
            bound[name] = digest
            if sha(C / name) != digest:
                raise RuntimeError(f'retained result changed: {name}')
    for f in (list((C / 'runs').glob('*/*.json')) + list((C / 'extra').glob('*/results/*.json'))
              + list((C / 'measure').glob('*/*.json'))):
        if f.name != 'config.json':
            bound.setdefault(str(f.relative_to(C)), sha(f))
    tmp = C / 'RETAINED_RESULTS.sha256.tmp'
    tmp.write_text(''.join(f'{bound[n]}  {n}\n' for n in sorted(bound)))
    os.replace(tmp, p)


def artifacts():
    lines = [f'{sha(p)}  {p.relative_to(C)}\n' for p in sorted(C.rglob('*'))
             if p.is_file() and not p.is_symlink() and p.name not in ('ARTIFACTS.sha256', '.lock')]
    tmp = C / 'ARTIFACTS.sha256.tmp'
    tmp.write_text(''.join(lines))
    os.replace(tmp, C / 'ARTIFACTS.sha256')


def configure(a):
    """The globals of one invocation from its arguments (also used by the tests, in process)."""
    global C, T, G, B, TB, JOBS, D8, AUTH, CRIT, FIXTURE, TEST
    C = Path(a.root).expanduser().resolve()
    JOBS = a.jobs
    FIXTURE = Path(a.test_fixture).resolve() if a.test_fixture else None
    TEST = FIXTURE is not None
    D8 = a.d8 or (str(FIXTURE / 'd8') if TEST else str(C / 'inputs' / 'bank'))
    AUTH = a.authority or (str(FIXTURE / 'authority') if TEST else None)
    CRIT = a.criterion or (str(FIXTURE / 'CRITERION.txt') if TEST else None)
    T, G = C / 'tools/redqueen', C / 'inputs/graph/graph.jsonl.gz'
    B, TB = C / 'inputs' / 'bank' / BANK_ARTIFACT, C / 'inputs' / 'bank' / OBS_TABLES


def protected(root):
    roots = [PROD, BANK, FINFOLK / 'repo', FINFOLK / 'src', FINFOLK / 'bin', FINFOLK / 'fable', FINFOLK / 'rq_launch']
    roots += list(FINFOLK.glob('validation*')) if FINFOLK.is_dir() else []
    return (root in (FINFOLK, Path.home(), Path('/'), REPO) or any(root == p or root.is_relative_to(p) for p in roots)
            or REPO.is_relative_to(root))


def main(argv=None):
    """-> the exit code: 0 done; 2 refused or failed (the reason on stderr)."""
    try:
        return guarded(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        print(f'rec_A_v1: {e.code if isinstance(e.code, str) else "refused"}', file=sys.stderr, flush=True)
        return 2


def guarded(argv):
    if any('diagnostic' in x for x in argv):
        raise SystemExit('rec_A_v1 never uses diagnostic mode: the acceptance packet is recovery.py packet --mode '
                         'acceptance only (A_design_v5 3.8, 4.4)')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('phase', choices=('measure', 'prepare', 'run'))
    ap.add_argument('--root', required=True)
    ap.add_argument('--jobs', type=int, default=MAX_WORKERS)
    ap.add_argument('--d8', help='the bank/D8 inputs (default P_REC/inputs/bank: the runbook\'s steps 1-7)')
    ap.add_argument('--authority', help='the authorities directory (AUTHORITIES)')
    ap.add_argument('--criterion', help='the adopted rec_A_v1 CRITERION text')
    ap.add_argument('--test-fixture', help='TESTS ONLY: a toy-graph fixture directory (see the module docstring)')
    a = ap.parse_args(argv)
    if a.jobs not in range(1, MAX_WORKERS + 1):
        raise SystemExit(f'--jobs {a.jobs}: at most {MAX_WORKERS} concurrent workers in total (A_design_v5 4.4)')
    configure(a)
    if protected(C):
        raise SystemExit('P_REC is a protected/non-dedicated directory')
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise SystemExit('nice 19 required')
    if a.phase == 'prepare' and (not AUTH or not CRIT):
        raise SystemExit('prepare needs --authority and --criterion (AUTHORITY_DIR, CRITERION: the adopted text)')
    C.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in C.rglob('*')):
        raise SystemExit('output symlinks refused')
    os.umask(0o077)
    with (C / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('another rec_A_v1 invocation holds the P_REC lock (exclusive): refused') from None
        if any(p.is_symlink() for p in C.rglob('*')):
            raise SystemExit('output symlinks refused')
        for n in ('logs', 'timing', 'tmp', 'summaries'):
            (C / n).mkdir(exist_ok=True)
        os.environ['TMPDIR'] = str(C / 'tmp')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        rc = 2
        try:
            {'measure': measure, 'prepare': prepare, 'run': run}[a.phase]()
            rc = 0
        except (Exception, KeyboardInterrupt, SystemExit) as e:
            print(f'FAILED: {e}', file=sys.stderr, flush=True)
        finally:
            for s in SPAWN_SIGNALS:        # (a second TERM / INT never cuts the cleanup short)
                signal.signal(s, signal.SIG_IGN)
            left = stop_children()
            if left:
                print(f'INTEGRITY ERROR: process group(s) {left} still have members after SIGKILL', file=sys.stderr,
                      flush=True)
                rc = 2
            (C / 'status.json').write_text(json.dumps({'phase': a.phase, 'exit': rc, 'attempt': STAMP}) + '\n')
            try:
                checkpoint_results()
            except Exception as e:
                print(f'INTEGRITY ERROR, retained manifest preserved: {e}', file=sys.stderr)
                rc = 2
            artifacts()
        return rc


if __name__ == '__main__':
    sys.exit(main())
