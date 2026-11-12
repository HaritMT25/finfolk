#!/usr/bin/env python3
"""Synthetic production-shaped bundles, real scorer schema, packed-store -> all five hypotheses."""
from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analysis
import calib
import cell
import ckpt
import material
import plan
import rqlib
import score
import stats
import store
from test_redqueen import mk_cp
from test_stats import layout64, eco_doc, mask_doc


def sha(x):
    return rqlib.canonical_sha(x)


class SyntheticScorer:
    """Run the REAL scorer on synthetic checkpoints/counters and predator CSV, caching identical outcomes."""
    def __init__(self, directory):
        self.d, self.cache = directory, {}
        self.arenas = {}
        for kind in ('neural', 'free', 'scripted'):
            k = 0 if kind == 'free' else 6
            cp = mk_cp(600, k, version=1 if kind == 'scripted' else 2)
            cp['config'].update(predatorBrain=kind != 'scripted', predatorEconomy=False)
            self.arenas[kind] = cp

    def __call__(self, kind, captures, survivors):
        key = kind, captures, survivors
        if key not in self.cache:
            arena = self.arenas[kind]
            end = copy.deepcopy(arena)
            end['world']['frame'] = 5100
            end['creatures']['alive'] = [int(i < survivors) for i in range(600)]
            for k, x in {'totalDeaths': 600 - survivors, 'totalDeathsPredation': captures,
                         'totalDeathsStarvation': 600 - survivors - captures}.items():
                end['counters'][k] += x
            k = 0 if kind == 'free' else 6
            p = Path(self.d) / 'run.predators.csv'
            if kind == 'scripted':
                p.unlink(missing_ok=True)
            else:
                rows = [dict(step=100 + t, predator_pop=k, captures_interval=captures if t == 5000 else 0,
                             births_interval=0, deaths_starv_interval=0, deaths_age_interval=0, reseeds_interval=0,
                             pursuit_frac=0.2, virtual_buds_interval=0) for t in range(500, 5001, 500)]
                with p.open('w') as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
            with patch.object(ckpt, 'load', side_effect=lambda p: arena if Path(p).name == 'arena.json' else end):
                self.cache[key] = score.score(self.d, k, 5000, [5000], 500, 'frozen',
                                               fork=kind == 'free', scripted=kind == 'scripted')
        return copy.deepcopy(self.cache[key])


def fixture(d):
    """64 registry slots; one retained C/A/B per block, all other slots biologically unavailable.

    A real plan/2 expansion, 41x41 panels plus fine pairs, four shared references measured at EVERY 1M.
    Only synthetic outcomes. One replicate and 19 draws are marked non-production by analyze().
    """
    reg = layout64()
    registry = {'worlds': reg}
    alive = {w['id'] for w in reg if w['id'].endswith('0')}
    ecology = eco_doc(reg, dead=set(w['id'] for w in reg) - alive)
    mask = mask_doc(reg, {})
    refs = {'schema': plan.REFS_SCHEMA, 'references': {f'R{g}:{k}': {
        'world': f's{g}{k}', 'uuid': f'ref-{g}-{k}', 'frame': 1, 'sha256': sha(['reference', g, k])}
        for g in 'QP' for k in range(4)}}
    refs_raw = rqlib.canonical(refs)
    binding = {'graph_edges_sha256': 'g' * 64, 'registry_sha256': 'r' * 64,
               'burn_in_frame': 5_000_000, 'max_restarts': 8, 'references_sha256': rqlib.sha256_bytes(refs_raw)}
    def label(t):
        return 'F1' if t == 0 else f'{t}M'
    times = {label(t): 1 if t == 0 else t * 1_000_000 for t in range(201)}
    wmap = {w: {'uuid': f'u-{w}', 'pattern': f'/synthetic/{w}.{{frame}}.json'} for w in alive}
    wmap.update({v['world']: {'uuid': v['uuid'], 'pattern': '/synthetic/reference.json'} for v in refs['references'].values()})
    edges = []
    def edge(qw, qt, pw=None, pt=None, fam='within', scripted=False):
        edges.append({'edge': f'e{len(edges)}', 'family': fam.replace('_', '-'), 'role': ('training', 'validation', 'test', 'support')[len(edges) % 4],
                      'prey': {'world': qw, 'time': label(qt)},
                      'predators': {'source': 'scripted'} if scripted else {'world': pw, 'time': label(pt)} if pw else None})
    for w in sorted(alive):
        treatment = next(x['treatment'] for x in reg if x['id'] == w)
        if treatment == 'C':
            within = {(a, b) for a in range(0, 201, 5) for b in range(0, 201, 5)}
            within |= {(0 if a == 1e-6 else int(a), 0 if b == 1e-6 else int(b))
                       for a, b in calib.registered_fine(lag=7)}
            for a, b in sorted(within):
                edge(w, a, w, b)
        ts = range(201) if treatment == 'C' else range(0, 201, 5)
        for t in ts:
            edge(w, t, fam='nopred')
            edge(w, t, fam='scripted', scripted=True)
            for k in range(4):
                edge(w, t, f'sP{k}', 0, 'ref_prey' if treatment == 'C' else 'ref_ab')
                if treatment == 'C':
                    edge(f'sQ{k}', 0, w, t, 'ref_pred')
    for k in range(4):
        edge(f'sQ{k}', 0, fam='nopred')
    # Every pair's role must agree when a reference-free control is shared, as in the production plan.
    for e in edges:
        e['role'] = ('training', 'validation', 'test', 'support')[int(e['prey']['time'][:-1]) % 4] if e['prey']['time'] != 'F1' else 'training'
    design = {'schema': 'finfolk.redqueen.design/2', 'name': 'synthetic-annexH-e2e', 'seed_namespace': 'synthetic-r11',
              'times': times, 'worlds': wmap, 'templates': ['/synthetic/template.json'],
              'age_reference': '/synthetic/ages.json', 'replicates': 1, 'edges': edges, 'availability': binding,
              'long': {'fraction': 0}, 'defaults': {'short_steps': 5000, 'short_horizons': [5000],
                  'long_steps': 5000, 'long_horizons': [5000], 'checkpoint_every': 5000, 'log_every': 500,
                  'n_prey': 600, 'k': 6, 'prey_policy': 'common', 'assay': 'frozen'}}
    rows, _, _ = plan.expand_v2(design, pending=True)
    byworld = {w['id']: w for w in reg}
    reference_snaps = {plan.snapshot_uuid(v['uuid'], v['frame']): v['sha256'] for v in refs['references'].values()}
    for c in rows:
        for role in ('prey', 'predators', 'template', 'ages'):
            x = c.get(role)
            if not isinstance(x, dict) or not x.get('path'):
                continue
            x['sha256'] = reference_snaps.get(x.get('snapshot'), sha([role if role in ('template', 'ages') else 'snapshot', x.get('snapshot')]))
            if x.get('world') in byworld:
                mask['worlds'][x['world']]['available_sha256'][str(x['frame'])] = x['sha256']
    # The complete C graph, using the SAME reference keys / block grouping as calib.load_graph.
    graphs = []
    for w in sorted(w for w in alive if w.startswith('C')):
        def at(x):
            return stats.t_of_frame(x['frame'])
        wc = [(at(c['prey']), at(c['predators'])) for c in rows
              if c['prey']['world'] == w and (c.get('predators') or {}).get('world') == w]
        rc = [(at(c['predators']), 'RQ:' + c['prey']['world'][-1]) for c in rows
              if (c.get('predators') or {}).get('world') == w and c['prey']['world'].startswith('sQ')]
        rq = [(at(c['prey']), 'RP:' + c['predators']['world'][-1]) for c in rows
              if c['prey']['world'] == w and (c.get('predators') or {}).get('world', '').startswith('sP')]
        graphs.append(calib.WorldGraph(w, 0, wc, rc, rq))
    scorer = SyntheticScorer(d)
    root = Path(d) / 'packed'; (root / store.CHUNKS).mkdir(parents=True)
    entries = {}
    zip_path = root / store.CHUNKS / 'chunk_000000.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for i, c in enumerate(rows):
            q, p = c['prey'], c.get('predators') or {}
            ti = stats.t_of_frame(q['frame'])
            tj = stats.t_of_frame(p['frame']) if p.get('world') else 0
            kind = 'free' if c['kind'] == 'nopred' else 'scripted' if p.get('source') == 'scripted' else 'neural'
            block = byworld.get(q['world'], {}).get('block', 0)
            if kind == 'free':
                C, L = 0, 235
            else:
                C = int(150 - 0.15 * tj + 2 * math.cos(ti / 7) + block % 3)
                if q['world'] in byworld and p.get('world') == q['world']:
                    L = int(185 - (0.06 + block * 0.001) * ti + 2 * math.cos(tj / 7))
                elif kind == 'scripted':
                    L = 165
                elif q['world'].startswith('sQ'):
                    L = 180
                else:
                    # Positive H-C interaction only in C; A/B neural and scripted have equal slopes.
                    L = int(165 + (0.23 + block * 0.001) * ti) if q['world'].startswith('C') else 165
            sc = scorer(kind, C, L)
            if i % 2:
                sc['horizons'][0]['age_strata'] = [{'initial': 600, 'survivors': L}]
            files = {'common.json': sha(c['groups']['common']), 'common.manifest.json': sha(['manifest', c['groups']['common']])}
            sh = {'schema': cell.SHARING_SCHEMA, 'keys': c['groups'], 'seeds': c['seeds'],
                  'realized': {'common_sha256': files['common.json'],
                               'transplant_realized_sha256': sha(c['groups']['transplant'])}}
            b = {'schema': cell.BUNDLE_SCHEMA_V2, 'cell': c, 'binary_sha256': 'b' * 64,
                 'tools_sha256': {'score.py': sha('synthetic scorer')}, 'engine_args': {'transplant': [], 'assay': []},
                 'files': files, 'common_manifest_sha256': files['common.manifest.json'],
                 'arena_prey_config_sha256': sha('synthetic common prey config'), 'arena_manifest': {},
                 'score': sc, 'sharing': sh, 'predators_csv': '', 'run_csv': ''}
            bs = rqlib.canonical(b)
            tg = f'{c["groups"]["transplant"]}|k{c["k"]}' if kind != 'free' else None
            done = dict(store.summary_of(b), schema='finfolk.redqueen.done/1', id=c['id'],
                bundle_sha256=rqlib.sha256_bytes(bs), role=c['role'], families=c['families'],
                transplant_group=tg, transplant_realized_sha256=sh['realized']['transplant_realized_sha256'] if tg else None,
                wall_s=0., cpu_s=0.)
            probs = store.completion_problems(done, b)
            if probs:
                raise AssertionError(probs)
            ds = rqlib.canonical(done)
            entries[c['id']] = dict(store.summary_of(b), bundle_sha256=done['bundle_sha256'],
                done_sha256=rqlib.sha256_bytes(ds), role=c['role'], transplant_group=tg,
                transplant_realized_sha256=done['transplant_realized_sha256'], bundle_schema=cell.BUNDLE_SCHEMA_V2)
            z.writestr(c['id'] + '/bundle.json', bs); z.writestr(c['id'] + '/done.json', ds)
    rec = {'schema': store.CHUNK_SCHEMA, 'chunk': zip_path.name, 'sha256': rqlib.sha256_file(zip_path),
           'bytes': zip_path.stat().st_size, 'cells': entries}
    (root / store.INDEX).write_bytes(rqlib.canonical(rec))
    params = calib.placeholder_params()
    return dict(roots=[str(root)], rows=rows, registry=registry, ecology=ecology, mask=mask, params=params,
                registry_sha256='r' * 64, ecology_sha256=sha(ecology), mask_sha256=sha(mask),
                references_raw=refs_raw, production=False, draws=19, min_q200=2, reps=1), graphs


def calibrated(args, graphs):
    q = set(args['ecology']['Q200']['worlds'])
    graph = [g for g in graphs if g.id in q]
    man = calib.manifest(graph, args['params'], args['draws'], production=False, graph_source='synthetic-fixture')
    crit = {'manifest': {'H-F': man, 'H-T': man}, 'c_F': 0., 'c_M': 1.1,
            'c_E': {e: 1e9 for e in ('E1', 'E2', 'E3')}, 'c_T': stats.HT_GUARD}
    rates = {f'gate_{e}|{m}|{s}|B': {'fp': 0, 'n': 1000} for e in ('E1', 'E2', 'E3')
             for m in ('F0', 'F1', 'F2') for s in calib.STRATA}
    acc = {'manifest': crit['manifest'], 'crit_sha256': calib.doc_sha(crit), 'production': False,
           'pass': {'H-F detection': True, 'H-F material': True, 'H-T': True,
                    **{f'gate {e}': True for e in ('E1', 'E2', 'E3')}},
           'rates': {'H-F': rates}, 'ptables': {k: {'synthetic': [1e9] * 1000}
                       for k in ('H-F detection', 'H-F material', 'H-T')}}
    # Production freezes H-F gates BEFORE calibrating H-T; preserve that artifact chain, no circular digest.
    hfcrit = dict(crit, manifest={'H-F': man})
    hfacc = dict(acc, manifest=hfcrit['manifest'], crit_sha256=calib.doc_sha(hfcrit))
    gates = calib.freeze_gates(hfcrit, hfacc, production=False)
    htman = calib.manifest(graph, args['params'], args['draws'], gates=gates,
                           production=False, graph_source='synthetic-fixture')
    crit['manifest'] = {'H-F': man, 'H-T': htman}
    acc.update(manifest=crit['manifest'], crit_sha256=calib.doc_sha(crit))
    return dict(args, crit=crit, acceptance=acc, gates=gates)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.args, cls.graphs = fixture(cls.tmp.name)
        cls.run_args = calibrated(cls.args, cls.graphs)
        cls.report = analysis.analyze(**cls.run_args)

    def test_every_hypothesis_and_ht_non_rejection(self):
        r = self.report
        self.assertEqual(len(r['rows']), 5)
        self.assertFalse(r['production'])
        self.assertTrue(all(x['available'] for x in r['rows']), r['decision']['unavailable'])
        self.assertEqual(r['results']['H-T']['T_T'], -math.inf)
        ht = next(x for x in r['rows'] if x['hypothesis'] == 'H-T')
        self.assertEqual((ht['p'], ht['detection'], ht['operational_success']), (1., False, False))
        self.assertEqual(r['decision']['H-C']['n_blocks'], 8)
        self.assertTrue(r['decision']['decision']['H-C'])
        for row in r['rows']:
            self.assertIn('material_point', row)
            self.assertIn('material_exceedance', row)
        json.dumps(analysis.json_safe(r), allow_nan=False)

    def test_shared_controls_and_reference_sources(self):
        r = self.report
        self.assertGreater(r['input_summary']['measured_pairs'], r['input_summary']['free_controls'])
        self.assertEqual(r['eligibility']['Q200']['count'], 8)
        self.assertEqual(len(r['results']['H-T']['worlds']), 8)
        self.assertEqual(r['input_summary']['ignored'], {})
        # Optional parallel-PR age_strata is present in half the real-shaped scores and absent in half.
        bundles = analysis.load_packed(self.args['roots'], self.args['rows'])
        self.assertEqual({('age_strata' in b['score']['horizons'][0]) for b in bundles.values()}, {True, False})
        # Plan display aliases do not change the main-world identity or a shared reference's source.
        for b in bundles.values():
            for role in ('prey', 'predators'):
                endpoint = b['cell'].get(role) or {}
                if endpoint.get('world') == 'C10':
                    endpoint['world'] = 'display-alias-C10'
        refs = json.loads(self.args['references_raw'])['references']
        slots = {plan.snapshot_uuid(v['uuid'], v['frame']): k for k, v in refs.items()}
        ids = {v['uuid']: w for w, v in self.args['mask']['worlds'].items()}
        assays = analysis.Assays(bundles, {w['id']: w for w in self.args['registry']['worlds']}, 1, 600, slots, ids)
        self.assertTrue(math.isfinite(assays.hc('C10')['neural']))
        self.assertTrue(assays.within['C10'])

    def test_missing_bundle_refused(self):
        args = dict(self.args)
        args['rows'] = args['rows'] + [dict(args['rows'][0], id='missing-required-cell')]
        with self.assertRaisesRegex(analysis.AnalysisError, 'missing.*bundle'):
            analysis.load_packed(args['roots'], args['rows'])

    def test_hc_seven_and_six_blocks_and_unavailable_worlds(self):
        # Keep Q200 below its registered minimum: the other four rows stay at p=1; H-C still runs.
        for blocks, expected in ((7, True), (6, False)):
            args = dict(self.args)
            eco = copy.deepcopy(args['ecology'])
            for w, slot in eco['slots'].items():
                if slot['block'] > blocks:
                    slot['attempts'][-1]['observation'] = 'event'
            eco['Q200']['worlds'] = sorted(w for w, slot in eco['slots'].items()
                                         if slot['treatment'] == 'C' and stats.complete_history(slot))
            eco['Q200']['count'] = len(eco['Q200']['worlds'])
            args.update(ecology=eco, ecology_sha256=sha(eco), min_q200=24)
            report = analysis.analyze(**calibrated(args, self.graphs))
            hc = next(x for x in report['rows'] if x['hypothesis'] == 'H-C')
            self.assertTrue(hc['available'])
            self.assertEqual(hc['detection'], expected)
            self.assertEqual(report['decision']['H-C']['n_blocks'], blocks)
            self.assertEqual(report['decision']['H-C']['p_floor'], 2. ** -blocks)
            for row in report['rows']:
                if row['hypothesis'] != 'H-C':
                    self.assertFalse(row['available']); self.assertEqual(row['p'], 1.)
                    self.assertIsNone(row['material_point'])

    def test_stale_d8_calibration_refused(self):
        crit = copy.deepcopy(self.run_args['crit'])
        crit['manifest']['H-F']['material_spec_sha256'] = 'old'
        with self.assertRaisesRegex(analysis.AnalysisError, 'stale|another critical'):
            analysis._check_calibration(crit, self.run_args['acceptance'], self.graphs, self.args['params'], 19, False)

    def test_production_cannot_use_synthetic_shortcuts(self):
        with self.assertRaisesRegex(analysis.AnalysisError, 'production requires registered'):
            analysis.analyze(**dict(self.run_args, production=True))


if __name__ == '__main__':
    unittest.main()
