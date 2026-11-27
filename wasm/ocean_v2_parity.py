#!/usr/bin/env python3
"""Separate Genome v2 checks; called by ocean_parity.sh, never rebaselined.

Standalone with retained drivers: python3 wasm/ocean_v2_parity.py DRIVER_DIR
Use --no-eye only when ocean_parity.sh built with NO_EYE=1.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('drivers', type=Path)
parser.add_argument('--no-eye', action='store_true')
parser.add_argument('--no-tests', action='store_true')
settings = parser.parse_args()
out = settings.drivers.resolve()
evidence = out / 'genome_v2'
evidence.mkdir(exist_ok=True)
root = Path(__file__).resolve().parents[1]

def run(label, command, expected=0):
    start = time.monotonic()
    with (evidence / (label + '.txt')).open('wb') as stdout, (evidence / (label + '.log')).open('wb') as stderr:
        result = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr)
    (evidence / (label + '.command')).write_text(repr(command) + '\n')
    (evidence / (label + '.result')).write_text(f'exit={result.returncode}\nwall={time.monotonic()-start:.3f}\n')
    if result.returncode != expected:
        raise SystemExit(f'{label}: expected exit {expected}, got {result.returncode}; see {evidence}')
    text = (evidence / (label + '.txt')).read_text()
    if expected == 0 and not re.search(r'^final .* nonfinite_max=0(?: |$)', text, re.MULTILINE):
        raise SystemExit(f'{label}: missing finite final state; see {evidence}')
    return text

def strip(text, prefix):
    return ''.join(re.sub(r' ' + prefix + r'[A-Za-z]*=[^ \n]*', '', line)
                   for line in text.splitlines(keepends=True)[1:]
                   if not line.startswith('expect ' + prefix))

for suffix in ([''] if settings.no_eye else ['', '_eye']):
    native = [str(out / ('opd_native' + suffix))]
    wasm = ['node', '--max-old-space-size=6144', str(out / ('opd_wasm' + suffix + '.js'))]
    for bias in [False, True]:
        name = ('eye' if suffix else 'plain') + ('_bias' if bias else '_nobias')
        cfg = dict(genomeVersion=2, biasGenes=bias, hiddenNeurons=12,
                   brainEvalVersion=2, weightMutationMode='saturating')
        if suffix:
            cfg['eye'] = 1
        def args(config, body=False):
            result = ['42', '3000', '--capture', '--cfg', json.dumps(config, separators=(',', ':')),
                      '--expect', 'births>0']
            if body:
                result += ['--expect', 'bodyFounders>0', '--expect', 'bodyOffspring>0']
            return result
        a = args(cfg)
        baseline = run(name + '.native', native + a)
        assert baseline == run(name + '.wasm', wasm + a), name + ' native/wasm mismatch'
        assert baseline == run(name + '.repeat', native + a), name + ' repeat mismatch'
        off_cfg = dict(cfg, appearance=0)
        off = run(name + '.off.native', native + args(off_cfg))
        assert off == run(name + '.off.wasm', wasm + args(off_cfg)), name + ' off native/wasm mismatch'
        assert off == run(name + '.off.repeat', native + args(off_cfg)), name + ' off repeat mismatch'
        assert strip(baseline, 'app') == strip(off, 'app'), name + ' appearance twin mismatch'
        body_cfg = dict(cfg, bodyPlanPreviewEnabled=True)
        body = run(name + '.body.native', native + args(body_cfg, True))
        assert body == run(name + '.body.wasm', wasm + args(body_cfg, True)), name + ' body native/wasm mismatch'
        assert body == run(name + '.body.repeat', native + args(body_cfg, True)), name + ' body repeat mismatch'
        assert strip(baseline, 'body') == strip(body, 'body'), name + ' body twin mismatch'
        print('PASS', name, 'native == wasm == repeat; capture, births, appearance-off and body-preview twins', flush=True)

    if settings.no_tests:
        continue
    # Each malformed startup/live update must fail with the shim's refusal
    # exit (1), never a parser usage error or a runtime crash. Both targets run.
    policy = dict(genomeVersion=2, brainEvalVersion=2, hiddenNeurons=12,
                  biasGenes=True, weightMutationMode='saturating')
    refusals = {
        'r_v2_legacy': dict(policy, weightMutationMode='legacy'),
        'r_v2_eval': dict(policy, brainEvalVersion=1),
        'r_v2_hidden': dict(policy, hiddenNeurons=24),
        'r_v2_cap': dict(policy, genomeMaxLength=81),
        'r_v2_lengths': dict(policy, genomeMinLength=48, genomeInitMin=24),
        'r_v2_version_fraction': dict(policy, genomeVersion=2.5),
        'r_v2_eval_fraction': dict(policy, brainEvalVersion=2.5),
        'r_v2_hidden_fraction': dict(policy, hiddenNeurons=12.5),
        'r_bias_v1': dict(genomeVersion=1, biasGenes=True),
        'r_bias_number': dict(policy, biasGenes=1),
    }
    cases = [(name, ['--cfg', json.dumps(cfg, separators=(',', ':'))])
             for name, cfg in refusals.items()]
    for key, value in [('genomeVersion', 1), ('brainEvalVersion', 1),
                       ('hiddenNeurons', 24), ('biasGenes', 0)]:
        cases.append(('r_v2_live_' + key,
                      ['--cfg', json.dumps(policy, separators=(',', ':')),
                       '--set', key + '=' + str(value) + '@5']))
    for name, options in cases:
        for target, command in [
            ('native', [str(out / ('ocean_tests_native' + suffix))]),
            ('wasm', ['node', '--max-old-space-size=6144', str(out / ('ocean_tests_wasm' + suffix + '.js'))])
        ]:
            run(name + suffix + '.' + target,
                command + ['--accepts', '1', '10'] + options, expected=1)
    print('PASS v2/bias refusals', suffix or 'plain', len(cases), 'native and wasm', flush=True)
