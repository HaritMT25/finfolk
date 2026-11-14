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
import backbone
import numpy as np
import recurrence
import transition
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
from test_calib import d8_bank_and_params


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


def fixture(d, shared_reference=False):
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
    if shared_reference:
        # sealing.py permits uniqueness within each guild, and this cross-guild alias.
        refs['references']['RP:3'].update({k: refs['references']['RQ:0'][k] for k in ('uuid', 'frame', 'sha256')})
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


def calibrated(args, graphs, c_E=1e9):
    q = set(args['ecology']['Q200']['worlds'])
    graph = [g for g in graphs if g.id in q]
    man = calib.manifest(graph, args['params'], args['draws'], production=False, graph_source='synthetic-fixture')
    crit = {'manifest': {'H-F': man, 'H-T': man}, 'c_F': 0., 'c_M': 1.1,
            'c_E': {e: c_E for e in ('E1', 'E2', 'E3')}, 'c_T': stats.HT_GUARD}
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
        slots = {(k.split(':')[0], plan.snapshot_uuid(v['uuid'], v['frame'])): k for k, v in refs.items()}
        ids = {v['uuid']: w for w, v in self.args['mask']['worlds'].items()}
        assays = analysis.Assays(bundles, {w['id']: w for w in self.args['registry']['worlds']}, 1, 600, slots, ids)
        self.assertTrue(math.isfinite(assays.hc('C10')['neural']))
        self.assertTrue(assays.within['C10'])

    def test_raw_hf_diagnostics_survive_strict_json(self):
        d = json.loads(json.dumps(analysis.json_safe(self.report['descriptive']), allow_nan=False))
        hf = d['H_F']
        self.assertEqual(hf['n'], 8)
        self.assertEqual(hf['positive'], sum(w['P'] is not None for w in hf['worlds'].values()))
        self.assertEqual(hf['S_F'], sum(w['contribution'] for w in hf['worlds'].values())/8)
        for w in d['H_F_worlds']:
            selected = hf['worlds'][w['id']]
            self.assertIn('P', selected)
            self.assertEqual(selected['support_failures'], {str(r['P']): r['fails'] for r in w['periods'] if not r['supported']})
            self.assertEqual(selected['phase_support'], w['phase_support'])
            for r in w['periods']:
                if 'readout' in r:
                    for ch in ('C', 'Q'):
                        self.assertIn('phase', r['readout'][ch])
                        self.assertIn('chain', r['readout'][ch])
                        self.assertIn('G', r['readout'][ch])
            if selected['P'] is not None:
                r = next(r for r in w['periods'] if r['P'] == selected['P'])
                self.assertEqual(selected['phase_C'], r['phase_C'])
                self.assertEqual(selected['phase_Q'], r['phase_Q'])
        self.assertEqual(set(d['epoch_worlds']), {'E1', 'E2', 'E3'})

    def test_epoch_directional_components_equal_calibration_coarse_betas(self):
        """P1 (Codex review of 03d8813): H-T's epoch directional components (and the per-world epoch slopes) use
        ONLY the coarse 41 x 41 panel: they are calibration's Panel.betas on the same counts. The fixture also
        measures the registered fine pairs, whose cos(t / 7) term the backbone does not model, so admitting them
        moves the estimates. The counts are read from the packed bundles, independently of the adapter."""
        bundles = analysis.load_packed(self.args['roots'], self.args['rows'])
        q = set(self.args['ecology']['Q200']['worlds'])
        within, free = {}, {}
        for b in bundles.values():
            c, h = b['cell'], b['score']['horizons'][0]
            qw, pw = c['prey'].get('world'), (c.get('predators') or {}).get('world')
            ti = stats.t_of_frame(c['prey']['frame'])
            if c['kind'] == 'nopred' and qw in q:
                free[qw, ti] = free.get((qw, ti), 0) + h['survivors']
            elif qw in q and pw == qw:
                key = (qw, ti, stats.t_of_frame(c['predators']['frame']))
                C, S = within.get(key, (0, 0))
                within[key] = (C + h['captures'], S + h['survivors'])
        scale = calib.R_REP / self.args['reps']          # (Panel.betas takes R_REP-replicate sums)
        panel = calib.Panel(self.graphs, self.args['params'], 'H-T', 'dev', 'actual', 'T1', 0)
        expected = {e: {'P': {}, 'Q': {}} for e in transition.EPOCHS}
        for wg in self.graphs:
            if wg.id not in q:
                continue
            cells = list(zip(wg.ti.tolist(), wg.tj.tolist()))
            self.assertTrue(set(cells) - {(a, b) for a in calib.COARSE for b in calib.COARSE})  # (fine pairs measured)
            K = {'C': np.array([within[wg.id, a, b][0] for a, b in cells], float) * scale,
                 'S': np.array([within[wg.id, a, b][1] for a, b in cells], float) * scale,
                 'F': np.array([free[wg.id, t] for t in wg.prey.tolist()], float) * scale}
            for e, (bP, bQ) in panel.betas(wg, K).items():
                expected[e]['P'][wg.id], expected[e]['Q'][wg.id] = bP, bQ
        comps = self.report['results']['H-T']['components']
        for e in transition.EPOCHS:
            self.assertEqual(set(expected[e]['P']), q)
            self.assertAlmostEqual(comps[e]['beta_P'], float(np.mean(list(expected[e]['P'].values()))), delta=1e-8)
            self.assertAlmostEqual(comps[e]['beta_Q'], float(np.mean(list(expected[e]['Q'].values()))), delta=1e-8)
            for h in 'PQ':
                for w, v in expected[e][h].items():
                    self.assertAlmostEqual(self.report['descriptive']['epoch_betas'][e][h][w], v, delta=1e-8)

    def test_ht_with_passing_epoch_gates(self):
        """The default fixture's epoch critical values (1e9) switch every gate off, so H-T only ever meets -inf
        (Codex r11 claims check). With c_E = -1 every AVAILABLE epoch's gate passes (S_F >= 0): all six
        candidates' fourteen margins are evaluated on the measured components, with D8's constants (pinned
        here independently of the implementation's)."""
        report = analysis.analyze(**calibrated(self.args, self.graphs, c_E=-1.))
        d, ht = report['descriptive'], report['results']['H-T']
        flags = {e: bool(d['epoch_H_F'][e]['available']) for e in transition.EPOCHS}
        self.assertEqual(d['gate_flags'], flags)
        self.assertTrue(any(flags.values()))
        self.assertTrue(ht['available'], ht.get('reasons'))
        b, comps = 0.0469305419921875, ht['components']
        dQ, deltaQ, dC, deltaP = 0.20 * b, 0.10 * b, 0.10, math.log(1.10)
        self.assertEqual(len(ht['candidates']), 6)
        for c in ht['candidates']:
            A, F, m = comps[c['ARD']], comps[c['FSD']], c['margins']
            self.assertEqual(len(m), 14)
            self.assertEqual(c['gate'], flags[c['FSD']])
            # D8 rule 47's fourteen margins, each computed here from the components and the pinned constants
            # (r12 review P3: the list had ten; the four contrasts below were only sign/length-checked).
            want = (('beta_P[a]', A['beta_P']), ('beta_Q[a]', A['beta_Q']),
                    ('dC2-EU_C[a]', dC ** 2 - A['EU_C']), ('dQ2-EU_Q[a]', dQ ** 2 - A['EU_Q']),
                    ('EF_C[f]-dC2', F['EF_C'] - dC ** 2), ('EF_Q[f]-dQ2', F['EF_Q'] - dQ ** 2),
                    ('dP-beta_P[f]', deltaP - F['beta_P']), ('dP+beta_P[f]', deltaP + F['beta_P']),
                    ('dQ-beta_Q[f]', deltaQ - F['beta_Q']), ('dQ+beta_Q[f]', deltaQ + F['beta_Q']),
                    ('beta_P[a]-beta_P[f]', A['beta_P'] - F['beta_P']), ('beta_Q[a]-beta_Q[f]', A['beta_Q'] - F['beta_Q']),
                    ('EF_C[f]-EU_C[a]', F['EF_C'] - A['EU_C']), ('EF_Q[f]-EU_Q[a]', F['EF_Q'] - A['EU_Q']))
            self.assertEqual(len(want), 14)
            self.assertEqual(set(m), {name for name, _ in want})
            for name, value in want:
                self.assertAlmostEqual(m[name], value, delta=1e-12, msg=name)
            self.assertEqual(math.isfinite(c['T']), c['gate'] and all(v > 0 for v in m.values()))
        self.assertEqual(ht['T_T'], max(c['T'] for c in ht['candidates']))
        row = next(x for x in report['rows'] if x['hypothesis'] == 'H-T')
        self.assertTrue(row['available'])

    def test_reference_snapshot_in_both_guilds(self):
        with tempfile.TemporaryDirectory() as d:
            args, graphs = fixture(d, shared_reference=True)
            report = analysis.analyze(**calibrated(args, graphs))
            self.assertTrue(all(r['available'] for r in report['rows']))
            refs = json.loads(args['references_raw'])['references']
            self.assertEqual(refs['RQ:0']['uuid'], refs['RP:3']['uuid'])
            slots = {(k.split(':')[0], plan.snapshot_uuid(v['uuid'], v['frame'])): k for k, v in refs.items()}
            ids = {v['uuid']: w for w, v in args['mask']['worlds'].items()}
            assays = analysis.Assays(analysis.load_packed(args['roots'], args['rows']),
                                    {w['id']: w for w in args['registry']['worlds']}, 1, 600, slots, ids)
            self.assertEqual({r for _, r in assays.refc['C10']}, {f'RQ:{k}' for k in range(4)})
            self.assertEqual({r for _, r in assays.refq['C10']}, {f'RP:{k}' for k in range(4)})
            # A free-control identity remains the snapshot, never a guild slot.
            shared = plan.snapshot_uuid(refs['RQ:0']['uuid'], refs['RQ:0']['frame'])
            self.assertEqual(sum(qid == shared for qid, _ in assays.free), 1)

    def test_epoch_gate_unavailable_never_passes(self):
        epoch = {e: {'available': e != 'E2', 'S_F': 100.} for e in transition.EPOCHS}
        self.assertEqual(analysis.epoch_gate_flags(epoch, {e: 1. for e in epoch}),
                         {'E1': True, 'E2': False, 'E3': True})

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
            # A population below 24 cannot require a passing, matching confirmatory calibration
            # merely to retain its descriptive estimates. Deliberately supply unusable artifacts.
            report = analysis.analyze(**dict(args, crit={}, acceptance={}, gates=None))
            hc = next(x for x in report['rows'] if x['hypothesis'] == 'H-C')
            self.assertTrue(hc['available'])
            self.assertEqual(hc['detection'], expected)
            self.assertEqual(report['decision']['H-C']['n_blocks'], blocks)
            self.assertEqual(report['decision']['H-C']['p_floor'], 2. ** -blocks)
            for row in report['rows']:
                if row['hypothesis'] != 'H-C':
                    self.assertFalse(row['available']); self.assertEqual(row['p'], 1.)
            self.assertEqual(set(report['descriptive']['world_slopes']['H-P']), set(eco['Q200']['worlds']))
            self.assertEqual(report['descriptive']['H_F']['n'], blocks)
            self.assertEqual(set(report['descriptive']['epoch_betas']), {'E1', 'E2', 'E3'})
            self.assertTrue(report['descriptive']['H_T']['components'])
            self.assertTrue(all(math.isfinite(v) for v in report['descriptive']['world_slopes']['H-Q'].values()))

    def test_single_qualifying_world_retains_descriptive_slope(self):
        args = dict(self.args)
        eco = copy.deepcopy(args['ecology'])
        for wid, slot in eco['slots'].items():
            if slot['treatment'] == 'C' and wid != 'C10':
                slot['attempts'][-1]['observation'] = 'event'
        eco['Q200'].update(worlds=['C10'], count=1)
        args.update(ecology=eco, ecology_sha256=sha(eco), min_q200=24)
        report = analysis.analyze(**calibrated(args, self.graphs))
        self.assertEqual(report['descriptive']['H_F']['n'], 1)
        self.assertEqual(set(report['descriptive']['world_slopes']['H-P']), {'C10'})
        self.assertTrue(math.isfinite(report['results']['H-Q']['estimate']))
        self.assertTrue(all(row['p'] == 1. for row in report['rows'] if row['hypothesis'] != 'H-C'))

    def assert_descriptive(self, report, q):
        d = report['descriptive']
        self.assertEqual(set(d['world_slopes']['H-P']), set(q))
        self.assertTrue(all(math.isfinite(v) for v in d['world_slopes']['H-Q'].values()))
        self.assertEqual((d['H_F']['n'], len(d['H_F_worlds'])), (len(q), len(q)))
        self.assertTrue(math.isfinite(d['H_F']['S_F']))
        self.assertEqual(set(d['epoch_betas']), set(transition.EPOCHS))
        self.assertEqual(set(d['epoch_H_F']), set(transition.EPOCHS))
        self.assertTrue(d['H_T']['components'])
        json.dumps(analysis.json_safe(report), allow_nan=False)

    def test_below_minimum_never_reads_a_p_table(self):
        """r12 review P2: one qualifying world below the population minimum (the analogue of 23 < 24), valid
        parameters, crit = {}, gates = None and an unusable acceptance p-table. The descriptive estimates are
        reported, every confirmatory row but H-C is unavailable with p = 1, and stats.model_p is never called.
        Also with unusable material / H-T tables, and with a valid calibration (which is not consumed)."""
        q = self.args['ecology']['Q200']['worlds']
        below = dict(self.args, min_q200=len(q) + 1)
        nan = {'old': [float('nan')]}
        for label, artifacts in (
                ('review scenario', dict(crit={}, acceptance={'ptables': {'H-F detection': nan}}, gates=None)),
                ('material and H-T tables', dict(crit={}, acceptance={'ptables': {'H-F material': nan, 'H-T': nan}},
                                                 gates=None)),
                ('valid calibration', {k: self.run_args[k] for k in ('crit', 'acceptance', 'gates')})):
            with self.subTest(label), patch.object(stats, 'model_p', wraps=stats.model_p) as model_p:
                report = analysis.analyze(**dict(below, **artifacts))
                self.assertEqual(model_p.call_count, 0, [call.args[0] for call in model_p.call_args_list])
                self.assertFalse(any(report['eligibility']['hypotheses'][h]['available'] for h in stats.Q200_FAMILY))
                for row in report['rows']:
                    if row['hypothesis'] != 'H-C':
                        self.assertEqual((row['available'], row['p'], row['detection']), (False, 1., False), row)
                self.assertEqual(report['results']['H-F']['reason'], 'Q200 below confirmatory minimum')
                self.assert_descriptive(report, q)

    def test_unavailable_claim_or_statistic_never_reads_its_p_table(self):
        """The same audit inside the confirmatory population: a p-table is read only for an AVAILABLE claim of an
        AVAILABLE statistic. (a) H-F detection fails its acceptance (so the nested material claim is unavailable
        too); (b) only the material claim fails; (c) the raw H-F statistic is unavailable (forced, as hf() reports
        a world without a supported candidate). The unusable H-F tables are never read; H-T's still is."""
        q = self.args['ecology']['Q200']['worlds']
        real_hf = recurrence.hf
        def unavailable_hf(worlds, eligibility=None, provenance=None):
            res = real_hf(worlds, eligibility=eligibility, provenance=provenance)
            # Only the population statistic carries the eligibility record (the epoch functionals do not).
            return res if eligibility is None else dict(res, available=False, reasons=['synthetic: no support'])
        for label, failed, unusable, hf in (('detection fails', 'H-F detection', ('H-F detection', 'H-F material'), None),
                                            ('material fails', 'H-F material', ('H-F material',), None),
                                            ('statistic unavailable', None, ('H-F detection', 'H-F material'), unavailable_hf)):
            acc = copy.deepcopy(self.run_args['acceptance'])
            if failed:
                acc['pass'][failed] = False
            nan = {'old': [float('nan')]}
            acc['ptables'].update({claim: nan for claim in unusable})
            with self.subTest(label), patch.object(stats, 'model_p', wraps=stats.model_p) as model_p, \
                    patch.object(recurrence, 'hf', side_effect=hf or real_hf):
                report = analysis.analyze(**dict(self.run_args, acceptance=acc))
                read = [call.args[1] for call in model_p.call_args_list]
                self.assertFalse(any(t is nan for t in read), label)
                self.assertTrue(any(t is acc['ptables']['H-T'] for t in read), label)
                self.assertTrue(all(report['eligibility']['hypotheses'][h]['available'] for h in stats.Q200_FAMILY))
                rows = {row['hypothesis']: row for row in report['rows']}
                self.assertTrue(rows['H-T']['available'])
                hfres = report['results']['H-F']
                if label == 'material fails':
                    self.assertTrue(rows['H-F']['available'])
                    # The valid detection table was read: 1000 null scores of 1e9 >= S_F, p = 1001 / 1001.
                    self.assertEqual(hfres['p_F'], 1.)
                    self.assertTrue(any(t is acc['ptables']['H-F detection'] for t in read))
                    self.assertEqual((hfres['c_M'], hfres['p_M'], hfres['exceeds_material']), (None, None, False))
                else:
                    self.assertFalse(hfres['available'])
                    self.assertEqual((rows['H-F']['available'], rows['H-F']['p'], rows['H-F']['detection']),
                                     (False, 1., False))
                self.assert_descriptive(report, q)

    def test_stale_d8_calibration_refused(self):
        crit = copy.deepcopy(self.run_args['crit'])
        crit['manifest']['H-F']['material_spec_sha256'] = 'old'
        acc = copy.deepcopy(self.run_args['acceptance'])
        acc['crit_sha256'] = calib.doc_sha(crit)  # get past the digest check, exercise the SPEC comparison
        with self.assertRaisesRegex(analysis.AnalysisError, 'stale / mismatched calibration:.*material_spec_sha256'):
            analysis._check_calibration(crit, acc, self.graphs, self.args['params'], 19, False)

    def test_production_cannot_use_synthetic_shortcuts(self):
        with self.assertRaisesRegex(analysis.AnalysisError, 'production requires registered'):
            analysis.analyze(**dict(self.run_args, production=True))

    def test_noise_source_is_checked_before_any_bundle(self):
        """#68 round 14 (pr68_engine_field_spec_v2, callers): a production analysis without the adopted bank
        artifact's bytes is refused; with them, calib.check_noise_source runs right after check_params and before
        any bundle is read (load_packed stubbed); a non-production run checks the bytes whenever given. Synthetic
        bank and parameters only (test_calib.d8_bank_and_params)."""
        bank, raw, fitted = d8_bank_and_params(calib)
        prod = dict(self.run_args, params=fitted, production=True, draws=stats.B_BOOT,
                    min_q200=stats.MIN_Q200, reps=calib.R_REP)

        class Reached(Exception):
            pass
        sigma_d = copy.deepcopy(fitted)
        sigma_d['noise']['SigmaD'][0][1] = sigma_d['noise']['SigmaD'][1][0] = 0.06
        with patch.object(analysis, 'load_packed', side_effect=Reached) as lp:
            with self.assertRaisesRegex(analysis.AnalysisError, 'noise-bank artifact named by fit.noise'):
                analysis.analyze(**prod)
            for name, args, why in (
                    ('appended byte', dict(prod, noise_source_raw=raw + b' '), 'noise source: the bank artifact bytes'),
                    ('synthetic bank', dict(prod, noise_source_raw=rqlib.canonical(dict(bank, synthetic=True))),
                     'noise source: the bank artifact bytes'),
                    ('changed SigmaD', dict(prod, params=sigma_d, noise_source_raw=raw),
                     "noise source: the noise block is not the bank artifact's"),
                    ('non-production, given', dict(self.run_args, params=fitted, noise_source_raw=raw + b' '),
                     'noise source: the bank artifact bytes')):
                with self.subTest(case=name):
                    with self.assertRaisesRegex(calib.CalibError, why):
                        analysis.analyze(**args)
            self.assertEqual(lp.call_count, 0)
            with self.assertRaises(Reached):
                analysis.analyze(**dict(prod, noise_source_raw=raw))
            self.assertEqual(lp.call_count, 1)
        self.assertIsNone(self.report['input_provenance']['noise_source_sha256'])


class DirectionalPanelsTests(unittest.TestCase):
    def assays(self):
        a = analysis.Assays.__new__(analysis.Assays)
        a.reps = calib.R_REP
        a.world_ids_by_uuid = {}
        coarse = list(calib.COARSE)
        coords = [(i, j) for i in coarse for j in coarse] + [(10., 11.), (11., 10.)]
        a.within, a.pairs, a.free = {'C1': {}}, {}, {}
        for i, j in coords:
            qid, pid = str(i), str(j)
            C = 324 * float(calib.sig(np.array([-.7 + .12*j/50]))[0])
            S = 600 * (.3 + .005*i/50)
            a.within['C1'][i, j] = {'C': C*a.reps, 'S': S*a.reps, 'F': 210*a.reps, 'qid': qid, 'pid': pid}
            a.pairs[qid, pid] = {r: ({}, {}, C, S) for r in range(a.reps)}
            for r in range(a.reps):
                a.free[qid, r] = ({'prey': {'world': 'C1', 'frame': round(i*1e6)}}, {}, 210.)
        return a

    def slopes(self, a, interval=backbone.FULL):
        cap, exp = a.panels('C1')
        free = a.free_series('C1', {t for ts, _ in exp.values() for t in ts})
        focal = [t for t in calib.COARSE if interval[0] <= t <= interval[1]]
        return (backbone.hp_world(cap, focal, interval)[0], backbone.hq_world(free, exp, focal, interval)[0])

    def test_fine_outcomes_cannot_change_directional_inputs_or_epoch_slopes(self):
        a = self.assays()
        inputs = copy.deepcopy(a.panels('C1'))
        slopes = {e: self.slopes(a, interval) for e, interval in recurrence.SCOPES.items()}
        self.perturb_fine(a)
        self.assertEqual(a.panels('C1'), inputs)
        self.assertIn((10., 11.), a.within['C1'])  # recurrence keeps the fine measurement
        self.assertEqual({e: self.slopes(a, interval) for e, interval in recurrence.SCOPES.items()}, slopes)

    @staticmethod
    def perturb_fine(a):
        """Off-law outcomes at the two fine pairs (and the fine prey time's free control): an estimator that
        admitted them could not recover the generating slopes."""
        for i, j in ((10., 11.), (11., 10.)):
            o = a.within['C1'][i, j]
            o['C'] = 0.; o['S'] = 247.*a.reps
            a.pairs[o['qid'], o['pid']] = {r: ({}, {}, 0., 247.) for r in range(a.reps)}
        for r in range(a.reps):
            a.free[str(11.), r] = (a.free[str(11.), r][0], {}, 0.)

    def test_known_directional_slopes_and_calibration_epoch_identity(self):
        a = self.assays()
        self.perturb_fine(a)
        bp, bq = self.slopes(a)
        self.assertAlmostEqual(bp, .12, delta=1e-6)
        self.assertAlmostEqual(bq, .005, delta=1e-6)
        coords = list(a.within['C1'])
        refs = [(t, f'RQ:{r}') for t in calib.COARSE for r in range(4)]
        wg = calib.WorldGraph('C1', 0, coords, refs, [(t, f'RP:{r}') for t, r in refs])
        panel = calib.Panel([wg], calib.placeholder_params(), 'H-T', 'dev', 'actual', 'T1', 0)
        K = {'C': np.array([a.within['C1'][i,j]['C'] for i,j in zip(wg.ti, wg.tj)]),
             'S': np.array([a.within['C1'][i,j]['S'] for i,j in zip(wg.ti, wg.tj)]),
             'F': np.full(len(wg.prey), 210.*a.reps)}
        expected = panel.betas(wg, K)
        for e in transition.EPOCHS:
            np.testing.assert_allclose(self.slopes(a, recurrence.SCOPES[e]), expected[e], rtol=0, atol=1e-10)


if __name__ == '__main__':
    unittest.main()
