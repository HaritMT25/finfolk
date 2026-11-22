#!/usr/bin/env python3
"""Plant PR-1 flow extraction defects in disposable copies; every one must fail.

Run: python3 tests/ocean_transport_fault.py [--eye] [--only NAME ...] [--out DIR]
No production source is edited. Compile failures never count as detection.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def replace(path, old, new, count=1):
    text = path.read_text()
    if text.count(old) != count:
        raise RuntimeError(f'{path}: anchor occurs {text.count(old)} times, expected {count}: {old}')
    path.write_text(text.replace(old, new))


def plant(root, name):
    transport = root / 'src/ocean/ocean_transport.hpp'
    world = root / 'src/ocean/ocean_world.hpp'
    if name == 'live_frame':
        # Reintroduce access to the live owner specifically inside the evaluator.
        # The bridge exists only in this mutant; future state must ignore it.
        replace(transport, 'namespace oceantransport {',
                'namespace oceantransport {\ninline const unsigned long long* faultLiveFrame = nullptr;')
        replace(world, 'oceantransport::TransportParams transportParams() const {',
                'oceantransport::TransportParams transportParams() const {\n        oceantransport::faultLiveFrame = &frame;')
        replace(transport, 'const float t = (float)targetFrame;',
                'const float t = (float)*faultLiveFrame;')
    elif name == 'zero_e1':
        replace(transport, 'const Flow U = flowFast(state, params, targetFrame, f.pos, f.depth);',
                'const Flow U = flowFast(state, params, targetFrame, f.pos, f.depth);\n'
                '            if (U.x == 0 && U.y == 0 && U.d == 0) continue;')
    elif name == 'shallow_yrot':
        flow = root / 'src/ocean/ocean_flow.hpp'
        replace(flow, '#include <vector>', '#include <vector>\n#include <memory>')
        replace(flow, 'struct FlowCache {', '''// Intentionally broken: copied mutable wave storage aliases the owner.
struct SharedYRot {
    std::shared_ptr<std::vector<TrigV>> v = std::make_shared<std::vector<TrigV>>();
    void assign(std::size_t n, const TrigV& x) { v->assign(n, x); }
    bool empty() const { return v->empty(); }
    std::size_t size() const { return v->size(); }
    TrigV* data() const { return v->data(); }
    TrigV& operator[](std::size_t i) const { return (*v)[i]; }
};
struct FlowCache {''')
        replace(flow, 'std::vector<TrigV> yRot;', 'SharedYRot yRot;')
    elif name.startswith('drop_gyre'):
        dropped = name.removeprefix('drop_') + '_'
        # A plausible hand-written copy carrying all but one derived member.
        fields = ['mode_', 'vortices_', 'centers_', 'strength_', 'core_', 'w_', 'h_',
                  'gyreEps_', 'gyreOmega_', 'gyreA_', 'gyreT_']
        initializers = ', '.join(f'{f}(x.{f})' for f in fields if f != dropped)
        current = root / 'src/core/current.hpp'
        replace(current, 'bool active() const',
                f'CurrentField() = default;\n'
                f'    CurrentField(const CurrentField& x) : {initializers} {{}}\n'
                f'    CurrentField& operator=(const CurrentField&) = default;\n'
                '    bool active() const')
    elif name == 'waves_off':
        replace(transport, 'state.cache.curAdvanced = true;\n    if (wavesOn(state, params, targetFrame)) {',
                'state.cache.curAdvanced = true;\n    if (true) {')
    elif name == 'cur_advanced':
        replace(transport, 'state.cache.curAdvanced = true;', 'state.cache.curAdvanced = false;')
    elif name == 'eye_contrast':
        replace(transport, 'if (f.depth != z0) f.eyeCon = contrastAt(f.depth);',
                'if (f.depth != z0) { /* intentionally keep stale contrast */ }', count=3)
    else:
        raise ValueError(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--eye', action='store_true')
    ap.add_argument('--only', action='append', help='run just this mutant (repeatable)')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    os.nice(19)
    repo = Path(__file__).resolve().parents[1]
    out = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='ocean_transport_fault.'))
    out.mkdir(parents=True, exist_ok=True)
    print(f'outputs: {out}', flush=True)
    source = out / 'source'
    source.mkdir(exist_ok=True)
    for directory in ['src', 'tools', 'tests', 'wasm']:
        dest = source / directory
        if dest.exists():
            shutil.rmtree(dest)
        # Only source files: no study outputs, binaries or other generated data.
        shutil.copytree(repo / directory, dest,
                        ignore=lambda _, names: [n for n in names if not (n.endswith(('.hpp', '.cpp')) or (Path(_) / n).is_dir())])
    tracked = ['src/ocean/ocean_transport.hpp', 'src/ocean/ocean_world.hpp',
               'src/ocean/ocean_flow.hpp', 'src/core/current.hpp']
    original = {name: (source / name).read_bytes() for name in tracked}
    mutants = ['live_frame', 'zero_e1', 'shallow_yrot', 'drop_gyreA', 'drop_gyreOmega',
               'drop_gyreT', 'waves_off', 'cur_advanced']
    if args.eye:
        mutants += ['eye_contrast']
    if args.only:
        if set(args.only) - set(mutants):
            ap.error('unknown mutant (eye_contrast needs --eye): ' + ', '.join(args.only))
        mutants = args.only
    for name in ['clean_before', *mutants, 'clean_after']:
        for path, data in original.items():
            (source / path).write_bytes(data)
        if not name.startswith('clean_'):
            plant(source, name)
        flags = ['-O2', '-std=c++20', '-ffp-contract=off', '-DEVO_WORLD_OCEAN', '-DOCEAN_TESTS_NO_SHIM', '-I', str(source / 'src')]
        if args.eye:
            flags += ['-DEVO_OCEAN_EYE']
        command = shlex.split(os.environ.get('CXX', 'g++')) + flags + [str(source / 'tests/ocean_tests.cpp'), '-o', str(out / 'tests')]
        with (out / f'{name}.build.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(out / 'tests'), '--only', 'transport'], capture_output=True, text=True)
        (out / f'{name}.log').write_text(result.stdout + result.stderr)
        fails = [line for line in result.stdout.splitlines() if line.startswith('FAIL ')]
        want_fail = not name.startswith('clean_')
        if (want_fail and result.returncode == 1 and fails) or (not want_fail and result.returncode == 0 and not fails):
            print(f'{name}: exit {result.returncode}; ' + ('; '.join(fails) if fails else 'PASS'), flush=True)
        else:
            raise RuntimeError(f'{name}: unexpected exit {result.returncode}; see {out / (name + ".log")}')
    for path, data in original.items():
        (source / path).write_bytes(data)
    print('PASS: every planted defect failed; clean copies pass before and after; source restored', flush=True)


if __name__ == '__main__':
    main()
