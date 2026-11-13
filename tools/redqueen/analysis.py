#!/usr/bin/env python3
"""Packed production assays -> Annex H's five-row decision. See ANALYSIS_CONTRACT.md.

This command reads outcomes: run only after the analysis freeze. Integration tests use synthetic data.
No engine or source archive is opened. All executable-plan cells must exist in committed chunks.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import backbone
import calib
import graph as graphlib
import material
import noisebank
import plan
import recurrence
import rqlib
import score
import stats
import store
import transition


class AnalysisError(ValueError):
    pass


def _count(x, upper, label):
    if type(x) is not int or not 0 <= x <= upper:
        raise AnalysisError(f'{label}: expected an integer in 0..{upper}, got {x!r}')
    return x


def load_packed(roots, rows):
    """Read-only archive verification, including completion and cross-chunk/root sharing evidence."""
    if any(c.get('schema') != plan.PLAN_SCHEMA_V2 for c in rows):
        raise AnalysisError('analysis requires executable plan/2 rows')
    want = {c['id']: c for c in rows}
    if len(want) != len(rows):
        raise AnalysisError('duplicate cell in executable plan')
    got, indexed = {}, {}
    for root in roots:
        recs, cells = store.load_index(root)
        probs = store.verify_all(root, deep=True)
        if probs:
            raise AnalysisError('; '.join(probs[:5]))
        # Open each zip once: production has millions of members, not one zip open per cell.
        for rec in recs:
            with zipfile.ZipFile(Path(root) / store.CHUNKS / rec['chunk']) as z:
                members = z.namelist()
                expected = {f'{cid}/{name}' for cid in rec['cells'] for name in ('bundle.json', 'done.json')}
                if len(members) != len(expected) or set(members) != expected:
                    raise AnalysisError(f'{rec["chunk"]}: missing, duplicate or extra archive members')
                for cid, entry in rec['cells'].items():
                    if cid not in want:
                        raise AnalysisError(f'{cid}: packed cell outside the executable plan')
                    if cid in got:
                        raise AnalysisError(f'{cid}: packed in more than one root')
                    bs, ds = z.read(f'{cid}/bundle.json'), z.read(f'{cid}/done.json')
                    if (rqlib.sha256_bytes(bs) != entry['bundle_sha256'] or
                            rqlib.sha256_bytes(ds) != entry['done_sha256']):
                        raise AnalysisError(f'{cid}: member hash differs from index')
                    b, d = json.loads(bs), json.loads(ds)
                    if (b.get('schema') != store.BUNDLE_V2 or d.get('schema') != 'finfolk.redqueen.done/1'
                            or d.get('id') != cid or d.get('bundle_sha256') != entry['bundle_sha256'] or
                            b.get('cell') != want[cid]):
                        raise AnalysisError(f'{cid}: bundle / completion differs from the executable plan')
                    probs = store.completion_problems(d, b)
                    summary = dict(store.summary_of(b), role=d.get('role'),
                                   transplant_group=d.get('transplant_group'),
                                   transplant_realized_sha256=d.get('transplant_realized_sha256'))
                    probs += [f'index {k} differs from completion' for k, v in summary.items() if entry.get(k) != v]
                    if probs:
                        raise AnalysisError(f'{cid}: ' + '; '.join(probs[:4]))
                    got[cid], indexed[cid] = b, (rec, entry)
    missing = sorted(set(want) - set(got))
    if missing:
        raise AnalysisError(f'missing {len(missing)} required packed bundle(s): {missing[:5]}')
    for check in (store.common_groups, store.pair_groups, store.transplant_groups):
        check(indexed)
    return got


class Assays:
    """One row per measured pair, with all replicates and one matched free control per prey/replicate."""
    def __init__(self, bundles, worlds, reps, ceiling, reference_slots, world_ids_by_uuid):
        self.worlds, self.reps = worlds, reps
        self.world_ids_by_uuid = world_ids_by_uuid
        self.pairs, self.free = {}, {}
        self.ignored = Counter()
        for cid, b in bundles.items():
            c, sc = b['cell'], b['score']
            # The confirmatory backbone uses ALL main roles (including support and test), not map-training only.
            if c['namespace'] != 'main' or c['assay'] != 'frozen' or c['prey_policy'] != 'common':
                self.ignored['other namespace / assay / prey policy'] += 1
                continue
            if c['role'] not in ('training', 'validation', 'test', 'support'):
                self.ignored['audit / diagnostic role'] += 1
                continue
            if sc.get('schema') != score.SCHEMA or sc.get('n_start') != 600 or sc.get('dt') != score.DT:
                raise AnalysisError(f'{cid}: wrong score schema / cohort / dt')
            if sc.get('k') != c['k'] or sc.get('assay') != c['assay'] or sc.get('steps') != c['steps']:
                raise AnalysisError(f'{cid}: score differs from cell settings')
            hz = [h for h in sc['horizons'] if h['steps'] == 5000]
            if len(hz) != 1 or 5000 not in c['horizons']:
                raise AnalysisError(f'{cid}: no single registered 5k horizon')
            h = hz[0]
            L = _count(h['survivors'], ceiling, cid + ' survivors')
            checks = sc.get('checks') or {}
            if checks.get('no_prey_replenishment') is not True or checks.get('frozen_k_constant') is not True:
                raise AnalysisError(f'{cid}: required scorer checks absent')
            q, p, r = c['prey'], c.get('predators'), c['replicate']
            _count(r, reps - 1, cid + ' replicate')
            # UUID identity, not a display label or reference slot, joins every shared control.
            qid = q['snapshot']
            if c['kind'] == 'nopred':
                if c['k'] != 0 or h['captures'] != 0 or checks.get('fork_predator_free') is not True:
                    raise AnalysisError(f'{cid}: invalid predator-free control')
                dest, key, value = self.free, (qid, r), (c, b, L)
            else:
                if c['k'] != 6:
                    raise AnalysisError(f'{cid}: confirmatory capture bound requires K=6')
                scripted = (p or {}).get('source') == 'scripted'
                if bool(sc.get('scripted')) != scripted:
                    raise AnalysisError(f'{cid}: scorer scripted mode differs from source')
                if (p or {}).get('source') == 'random':
                    self.ignored['random benchmark'] += 1
                    continue
                pid = 'scripted' if scripted else p['snapshot']
                C = _count(h['captures'], noisebank.capture_bound(5000), cid + ' captures')
                dest, key, value = self.pairs.setdefault((qid, pid), {}), r, (c, b, C, L)
            if key in dest:
                raise AnalysisError(f'{cid}: duplicate measured pair / free control replicate')
            dest[key] = value
        for pair, rr in self.pairs.items():
            if set(rr) != set(range(reps)):
                raise AnalysisError(f'{pair}: incomplete replicate matrix')
            for r, (c, b, _, _) in rr.items():
                free = self.free.get((pair[0], r))
                if free is None:
                    raise AnalysisError(f'{c["id"]}: missing matched free control')
                fc, fb, _ = free
                for k in ('sample', 'ages', 'reseed'):
                    if c['seeds'].get(k) != fc['seeds'].get(k) or c['groups'].get(k) != fc['groups'].get(k):
                        raise AnalysisError(f'{c["id"]}: control has another shared {k}')
                if b['arena_prey_config_sha256'] != fb['arena_prey_config_sha256']:
                    raise AnalysisError(f'{c["id"]}: control has different prey settings')
        self.within, self.refc, self.refq, self.script = (defaultdict(dict) for _ in range(4))
        for pair, rr in self.pairs.items():
            c, _, _, _ = rr[0]
            q, p = c['prey'], c['predators']
            qw, pw = self.world_of(q), self.world_of(p)
            ti, tj = stats.t_of_frame(q['frame']), stats.t_of_frame(p['frame']) if pw else None
            obs = {'C': sum(v[2] for v in rr.values()), 'S': sum(v[3] for v in rr.values()),
                   'F': sum(self.free[pair[0], r][2] for r in range(reps)), 'qid': pair[0], 'pid': pair[1]}
            if qw in worlds and pw == qw:
                self._put(self.within[qw], (ti, tj), obs)
            elif qw in worlds and p.get('source') == 'scripted':
                self._put(self.script[qw], ti, obs)
            elif qw in worlds and pw not in worlds and 'source' not in p:
                self._put(self.refq[qw], (ti, self._slot(reference_slots, 'RP', pair[1])), obs)
            elif pw in worlds and qw not in worlds:
                self._put(self.refc[pw], (tj, self._slot(reference_slots, 'RQ', pair[0])), obs)
            else:
                self.ignored['cross-world / reference-grid pair'] += 1

    def world_of(self, endpoint):
        return self.world_ids_by_uuid.get(endpoint.get('uuid'), endpoint.get('world'))

    @staticmethod
    def _slot(reference_slots, guild, snapshot):
        """The registered slot of a reference in ITS guild (RQ: reference prey, RP: reference predators); the
        same snapshot may hold one slot in each guild (sealing's uniqueness is per guild)."""
        slot = reference_slots.get((guild, snapshot))
        if slot is None:
            raise AnalysisError(f'{snapshot}: measured as a reference {"prey" if guild == "RQ" else "predator"} '
                                f'but not registered in guild {guild}')
        return slot

    @staticmethod
    def _put(dest, key, obs):
        if key in dest:
            raise AnalysisError(f'two snapshot identities at the same analysis coordinate {key}')
        dest[key] = obs

    def free_series(self, wid, times):
        by = {}
        for (qid, r), (c, _, L) in self.free.items():
            if self.world_of(c['prey']) == wid:
                t = stats.t_of_frame(c['prey']['frame'])
                if t in times:
                    by.setdefault(t, {})[r] = L
        if set(by) != set(times) or any(set(v) != set(range(self.reps)) for v in by.values()):
            raise AnalysisError(f'{wid}: incomplete matched free-control series')
        # Each shared control is included ONCE in the likelihood, never once per opponent.
        return ([t for t in sorted(by) for r in sorted(by[t])],
                [by[t][r] for t in sorted(by) for r in sorted(by[t])])

    def panels(self, wid):
        coarse = set(calib.COARSE)
        grid = self.within[wid]
        if not all((a, b) in grid for a in coarse for b in coarse):
            raise AnalysisError(f'{wid}: incomplete 41 x 41 coarse panel')
        capture, exposed = {}, {}
        for t in sorted(coarse):
            capture[t] = ([], [], [])
            exposed[t] = ([], [])
        for (a, b), o in sorted(grid.items()):
            if a not in coarse or b not in coarse:
                continue
            capture[a][0].append(b); capture[a][1].append(o['C']); capture[a][2].append(noisebank.capture_bound(5000) * self.reps)
            # Binomial joint likelihood retains its 600 denominator per replicate.
            for r in range(self.reps):
                exposed[b][0].append(a)
                exposed[b][1].append(self.pairs[o['qid'], o['pid']][r][3])
        return capture, exposed

    def hc(self, wid):
        coarse = sorted(calib.COARSE)
        refs = sorted({r for _, r in self.refq[wid]})
        if len(refs) != 4 or not all((t, r) in self.refq[wid] for t in coarse for r in refs):
            raise AnalysisError(f'{wid}: incomplete four-reference H-C panel')
        if not set(coarse) <= set(self.script[wid]):
            raise AnalysisError(f'{wid}: incomplete scripted H-C panel')
        def series(obs):
            return ([t for t, o in obs for r in range(self.reps)],
                    [self.pairs[o['qid'], o['pid']][r][3] for t, o in obs for r in range(self.reps)])
        neural = {r: series([(t, self.refq[wid][t, r]) for t in coarse]) for r in refs}
        scripted = series([(t, self.script[wid][t]) for t in coarse])
        result = backbone.hc_world(self.free_series(wid, coarse), neural, scripted, coarse)
        return {'neural': result['beta_N'], 'scripted': result['beta_S'], 'complete': True}

    def recurrent(self, wid, block):
        wg = calib.WorldGraph(wid, block, list(self.within[wid]), list(self.refc[wid]), list(self.refq[wid]))
        def vals(panel, coords, col):
            return np.array([panel[k][col] for k in coords], float) / (self.reps * (noisebank.capture_bound(5000) if col == 'C' else 600))
        wc = list(zip(wg.ti.tolist(), wg.tj.tolist()))
        rc = list(zip(wg.cT.tolist(), wg.cR.tolist()))
        rq = list(zip(wg.qT.tolist(), wg.qR.tolist()))
        ft, fs = self.free_series(wid, set(wg.prey.tolist()))
        fm = {t: 0.0 for t in ft}
        for t, L in zip(ft, fs):
            fm[t] += L / (600 * self.reps)
        m = {'C': vals(self.within[wid], wc, 'C'), 'S': vals(self.within[wid], wc, 'S'),
             'F': np.array([fm[t] for t in wg.prey]),
             'RC': vals(self.refc[wid], rc, 'C'), 'RS': vals(self.refq[wid], rq, 'S')}
        y = {'within': {'C': m['C'], 'Q': m['S'] - np.array([fm[t] for t in wg.ti])},
             'ref': {'C': m['RC'], 'Q': m['RS'] - np.array([fm[t] for t in wg.qT])}}
        return wg, m, y


def analyze(roots, rows, registry, ecology, mask, params, crit, acceptance, gates, *,
            registry_sha256, ecology_sha256, mask_sha256, references_raw, production=True,
            draws=stats.B_BOOT, min_q200=stats.MIN_Q200, reps=calib.R_REP):
    """Dispatch every hypothesis; production safeguards cannot be relaxed without a synthetic report label."""
    if production and (draws != stats.B_BOOT or min_q200 != stats.MIN_Q200 or reps != calib.R_REP):
        raise AnalysisError('production requires registered bootstrap draws, Q200 minimum and six replicates')
    calib.check_params(params, production=production)
    bundles = load_packed(roots, rows)
    if not rows:
        raise AnalysisError('empty executable plan')
    bindings = {json.dumps(c.get('availability'), sort_keys=True) for c in rows}
    if len(bindings) != 1:
        raise AnalysisError('plans have different registered availability bindings')
    binding = rows[0].get('availability')
    if plan.binding_problems(binding):
        raise AnalysisError(plan.binding_problems(binding))
    if (binding['registry_sha256'] != registry_sha256 or
            binding['graph_edges_sha256'] != mask.get('graph', {}).get('edges_sha256')):
        raise AnalysisError('plan is bound to another registry / graph')
    ref_snaps, ref_uuids = plan.references_index(references_raw, binding)
    excluded, available = plan.mask_index(mask, ref_snaps)
    for c in rows:
        if plan.exclusion_of(c, excluded):
            raise AnalysisError(f'{c["id"]}: executable plan includes an unavailable snapshot')
        for role in ('prey', 'predators'):
            x = c.get(role) or {}
            if x.get('world') is not None and (x.get('snapshot') not in available or
                                              available[x['snapshot']] != x.get('sha256')):
                raise AnalysisError(f'{c["id"]}: {role} source not bound to the mask / references')
    worlds = {w['id']: w for w in registry['worlds']}
    ceiling = material.cohort_ceiling(params.get('cohort', material.registered_ages()),
                                      params.get('horizon', 5000), params.get('dt', score.DT))
    reference_slots = {(k.split(':')[0], plan.snapshot_uuid(v['uuid'], v['frame'])): k
                       for k, v in json.loads(references_raw)['references'].items()}
    world_ids_by_uuid = {u: w for w, info in mask['worlds'].items()
                         for u in (info.get('uuid'), info.get('attempt_uuid')) if u is not None}
    if set(world_ids_by_uuid) & ref_uuids:
        raise AnalysisError('a registered reference identity is also a main-world identity')
    if production and any(c.get('namespace') == 'main' and c.get('prey_policy') == 'common'
                          and c.get('assay') == 'frozen' and
                          ((c.get('ages') or {}).get('sha256') != material.AGES_SHA256 or c.get('n_prey') != 600)
                          for c in rows):
        raise AnalysisError('production assays must use the registered 600-prey corrected-age construction')
    assays = Assays(bundles, worlds, reps, ceiling, reference_slots, world_ids_by_uuid)
    complete = sorted(w for w, s in ecology['slots'].items() if stats.complete_history(s))
    hc_slopes = {}
    coarse_gaps = stats.mask_gaps(mask, complete, stats.COARSE_T)
    for w in complete:
        if w in coarse_gaps:
            continue
        try:
            hc_slopes[w] = assays.hc(w)
        except (backbone.BackboneError, np.linalg.LinAlgError, FloatingPointError) as e:
            hc_slopes[w] = {'neural': None, 'scripted': None, 'complete': True, 'failure': str(e)}
    provenance = lambda ws: stats.observation_provenance(mask, mask_sha256, sorted(ws))
    elig, deltas, weights = stats.eligibility(ecology, registry, hc_slopes, registry_sha256=registry_sha256,
        mask=mask, eco_sha256=ecology_sha256, mask_sha256=mask_sha256,
        min_q200=min_q200, hc_provenance=provenance(hc_slopes))
    q = elig['Q200']['worlds']
    descriptive = {}
    results, betas = {}, {e: {'P': {}, 'Q': {}} for e in transition.EPOCHS}
    can_q = any(elig['hypotheses'][h]['available'] for h in stats.Q200_FAMILY)
    if q:
        confirmatory = elig if can_q else None
        psl, qsl = {}, {}
        for w in q:
            cap, exp = assays.panels(w)
            free = assays.free_series(w, {t for times, _ in exp.values() for t in times})
            psl[w] = backbone.hp_world(cap, calib.COARSE)[0]
            qsl[w] = backbone.hq_world(free, exp, calib.COARSE)[0]
            for e in transition.EPOCHS:
                interval = recurrence.SCOPES[e]
                focal = [t for t in calib.COARSE if interval[0] <= t <= interval[1]]
                betas[e]['P'][w] = backbone.hp_world(cap, focal, interval)[0]
                betas[e]['Q'][w] = backbone.hq_world(free, exp, focal, interval)[0]
        for h, slopes, delta in (('H-P', psl, stats.DELTA_P), ('H-Q', qsl, stats.DELTA_Q)):
            results[h] = (backbone.directional_test(slopes, h, delta, draws=draws, eligibility=confirmatory, provenance=provenance(q))
                          if len(slopes) >= 2 else {'available': False, 'estimate': next(iter(slopes.values())),
                                                    'reason': 'world resampling needs at least two worlds'})
        descriptive.update(world_slopes={'H-P': psl, 'H-Q': qsl}, epoch_betas=betas)
        refs, graph, measured = {}, [], {}
        for w in q:
            refset = tuple(sorted({r for _, r in assays.refc[w]} | {r for _, r in assays.refq[w]}))
            refs.setdefault(refset, len(refs))
            wg, m, y = assays.recurrent(w, refs[refset])
            if production:
                pairs = set(zip(wg.ti.tolist(), wg.tj.tolist()))
                intensive = calib.registered_fine(intensive=True) <= pairs
                problems = calib.panel_problems(wg, intensive=intensive, lag=graphlib.LAG_PROBE)
                if problems:
                    raise AnalysisError(f'{w}: incomplete registered recurrence graph: {problems[:4]}')
            graph.append(wg); measured[w] = (m, y)
        # Reuse the very same covariance, null fitting and shared-source loading code as calibration.
        model = calib.Panel(graph, params, 'H-F', 'analysis', 'actual', 'F0', 0)
        refkeys = {k: i for i, k in enumerate(sorted({('RQ', r) for wg in graph for r in wg.cR}
                                                   | {('RP', r) for wg in graph for r in wg.qR}))}
        loads, hfworlds, epochs, epoch_results = {}, [], {e: [] for e in transition.EPOCHS}, defaultdict(list)
        for wg in graph:
            m, y = measured[wg.id]
            scopes = {}
            for scope in recurrence.SCOPES:
                cv = model.scope_covs(wg, model.eval_means(wg, m, scope))
                if reps != calib.R_REP:
                    cv = {k: recurrence.Cov(v.d * calib.R_REP / reps, v.U * math.sqrt(calib.R_REP / reps))
                          for k, v in cv.items()}
                wd = model._world_design(wg, cv, scope)
                scopes[scope] = recurrence.analyze_world(wd, y)
                if scope != 'full':
                    epochs[scope].append((wd, y)); epoch_results[scope].append(scopes[scope])
            hfworlds.append(scopes['full'])
            loads[wg.id] = model.ref_loads(wg, model.loading_means(wg, m), refkeys)
            if reps != calib.R_REP:
                loads[wg.id] = {k: v * math.sqrt(calib.R_REP / reps) for k, v in loads[wg.id].items()}
        # No confirmatory calibration is consumed below the population safeguard. In particular,
        # a missing or differently sized calibration must not suppress valid descriptive estimates.
        if can_q:
            _check_calibration(crit, acceptance, graph, params, draws, production)
        inputs = calib.decision_inputs(crit, acceptance) if can_q else {}
        rawhf = recurrence.hf(hfworlds, eligibility=confirmatory, provenance=provenance(q))
        descriptive.update(H_F=rawhf, H_F_worlds=hfworlds,
                           epoch_H_F={e: recurrence.hf(epoch_results[e]) for e in transition.EPOCHS},
                           epoch_worlds=dict(epoch_results))
        def model_p(claim, value):
            tables = acceptance.get('ptables', {}).get(claim)
            return stats.model_p(value, tables) if tables else None
        det, mat = inputs.get('H-F detection', {}), inputs.get('H-F material', {})
        # A p-table is read only for an AVAILABLE claim of an AVAILABLE statistic (#68 r12 review P2): below the
        # Q200 minimum (inputs is empty), for a claim whose calibration did not pass, or when the raw H-F
        # statistic is unavailable, hf_decision never uses the p-value, so an unusable table cannot abort the
        # descriptive report. The H-T p-value below is likewise read only for an available claim and result.
        def claim_p(claim, record, value):
            return model_p(claim, value) if record.get('available') and rawhf['available'] else None
        results['H-F'] = recurrence.hf_decision(rawhf, crit.get('c_F') if det.get('available') else None,
            claim_p('H-F detection', det, rawhf.get('S_F')), crit.get('c_M') if mat.get('available') else None,
            claim_p('H-F material', mat, rawhf.get('M_F')))
        if len(q) >= 2 and inputs.get('H-T', {}).get('available') and gates is not None:
            man = crit['manifest']['H-T']
            calib.check_gates(gates, man, production=production)
            if man.get('gates_sha256') != calib.doc_sha(gates):
                raise AnalysisError('H-T was calibrated with another frozen epoch-gate artifact')
            gate_flags = epoch_gate_flags(descriptive['epoch_H_F'], gates['c_E'])
            descriptive['gate_flags'] = gate_flags
            rawht = transition.ht(epochs, betas, gate_flags, loads=loads, k=len(refkeys), draws=draws,
                c_T=crit.get('c_T'), p_model=1.0, eligibility=confirmatory, provenance=provenance(q))
            rawht['p_model'] = model_p('H-T', rawht.get('T_T')) if rawht.get('available') else None
            rawht['reject'] = bool(rawht.get('available') and rawht['p_model'] is not None and
                                  rawht['T_T'] > rawht['c_T'] and rawht['p_model'] <= stats.DETECT_ALPHA)
            results['H-T'] = rawht
            descriptive['H_T'] = rawht
        else:
            results['H-T'] = {'available': False, 'reason': 'no passing H-T / epoch gate calibration'}
            if len(q) >= 2:
                # Uncalibrated descriptive epoch components only: no transition statistic or decision.
                desc_ht = transition.ht(epochs, betas, {e: False for e in transition.EPOCHS},
                    loads=loads, k=len(refkeys), draws=draws, c_T=None, report=False)
                descriptive['H_T'] = {k: desc_ht.get(k) for k in
                    ('components', 'phase_support', 'coverage', 'EU_unsupported', 'error', 'failure')}
        if not can_q:
            for h in stats.Q200_FAMILY:
                if h in results:
                    results[h] = dict(results[h], available=False, reason='Q200 below confirmatory minimum')
    decision = stats.decide(elig, results, deltas, weights)
    report_rows = []
    for h in stats.HYPOTHESES:
        r = decision['H-C'] if h == 'H-C' else results.get(h, {})
        available = h not in decision['unavailable']
        detection = bool(decision['decision'][h])
        point = r.get('material_point', r.get('material_points'))
        if h in ('H-P', 'H-Q'):
            operational = detection and bool(point)
            exceed = detection and r.get('material_evidence', False)
        elif h == 'H-F':
            point = (bool(r['R_C'] >= recurrence.D_C and r['R_Q'] >= recurrence.D_Q)
                     if 'R_C' in r and 'R_Q' in r else descriptive.get('H_F', {}).get('material_point'))
            operational = detection and bool(point)
            exceed = detection and bool(r.get('exceeds_material'))
        elif h == 'H-C':
            operational = detection and all((point or {}).values())
            exceed = detection and r.get('p_material', 1.0) <= stats.active_level(decision['holm'], h)
        else:
            operational, exceed, point = detection, None, None
        report_rows.append({'hypothesis': h, 'available': available, 'reason': decision['unavailable'].get(h),
            'p': decision['holm']['raw'][h], 'p_holm': decision['holm']['adjusted'][h],
            'detection': detection, 'material_point': point, 'operational_success': bool(operational),
            'material_exceedance': exceed})
    return {'schema': 'finfolk.redqueen.analysis/1', 'production': production, 'material_spec': material.specification(),
            'descriptive': descriptive, 'rows': report_rows, 'decision': decision, 'eligibility': elig, 'results': results,
            'input_provenance': {'adapter_sha256': rqlib.sha256_file(__file__),
                'registry_sha256': registry_sha256, 'ecology_sha256': ecology_sha256,
                'mask_sha256': mask_sha256, 'references_sha256': rqlib.sha256_bytes(references_raw),
                'params_sha256': calib.doc_sha(params), 'critical_sha256': calib.doc_sha(crit),
                'acceptance_sha256': calib.doc_sha(acceptance), 'gates_sha256': calib.doc_sha(gates)},
            'input_summary': {'packed_bundles': len(bundles), 'free_controls': len(assays.free),
                              'measured_pairs': len(assays.pairs), 'ignored': dict(assays.ignored)}}


def epoch_gate_flags(epoch_hf, critical):
    return {e: bool(epoch_hf[e]['available'] and critical.get(e) is not None and
                    epoch_hf[e]['S_F'] > critical[e]) for e in transition.EPOCHS}


def _check_calibration(crit, acc, graph, params, draws, production):
    if acc.get('crit_sha256') != calib.doc_sha(crit):
        raise AnalysisError('acceptance belongs to another critical-value artifact')
    if production and acc.get('production') is not True:
        raise AnalysisError('production requires production acceptance')
    for h, man in crit.get('manifest', {}).items():
        if h not in ('H-F', 'H-T'):
            continue
        expected = calib.manifest(graph, params, draws, production=production, graph_source=man.get('graph_source'))
        keys = [k for k in calib.IDENT if k != 'gates_sha256']
        diff = [k for k in keys if man.get(k) != expected.get(k)]
        diff += [k for k in calib.IDENT if man.get(k) != acc.get('manifest', {}).get(h, {}).get(k)]
        if diff:
            raise AnalysisError(f'{h}: stale / mismatched calibration: {sorted(set(diff))}')


def json_safe(value):
    """Strict JSON; preserve defined infinities as explicit strings, never emit nonstandard JSON tokens."""
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return '-Infinity' if value == -math.inf else 'Infinity' if value == math.inf else 'NaN'
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', action='append', required=True, help='committed assay store(s), including scripted cells')
    for name in ('plan', 'registry', 'ecology', 'mask', 'references', 'params', 'critical', 'acceptance', 'gates', 'out'):
        ap.add_argument('--' + name, required=True)
    ap.add_argument('--plan-sha256', required=True, help='frozen executable-plan digest')
    a = ap.parse_args(argv)
    try:
        plan_raw = Path(a.plan).read_bytes()
        if rqlib.sha256_bytes(plan_raw) != a.plan_sha256:
            raise AnalysisError('plan sha256 differs from the frozen executable plan')
        def read(path):
            raw = Path(path).read_bytes()
            return json.loads(raw), rqlib.sha256_bytes(raw)
        registry, rs = read(a.registry); ecology, es = read(a.ecology); mask, ms = read(a.mask)
        result = analyze(a.root, [json.loads(line) for line in plan_raw.splitlines() if line.strip()],
            registry, ecology, mask, read(a.params)[0], read(a.critical)[0], read(a.acceptance)[0], read(a.gates)[0],
            registry_sha256=rs, ecology_sha256=es, mask_sha256=ms, references_raw=Path(a.references).read_bytes())
        result['plan_sha256'] = a.plan_sha256
        Path(a.out).write_text(json.dumps(json_safe(result), sort_keys=True, indent=2, allow_nan=False) + '\n')
    except (AnalysisError, store.StoreError, stats.StatsError, calib.CalibError, backbone.BackboneError,
            recurrence.RecurrenceError, transition.TransitionError, OSError, ValueError, KeyError) as e:
        print(f'analysis.py: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
