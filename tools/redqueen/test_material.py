#!/usr/bin/env python3
"""D8 provenance, complete non-rejections and age-supported synthetic calibration draws."""
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common
import material
import stats
import recurrence
import calib
import numpy as np
import graph


class MaterialTests(unittest.TestCase):
    def test_bank_bit_identity(self):
        # The bank is never opened by CI; copy the authorized read-only file into scratch first.
        path = HERE.parents[1] / 'build_stats11/bank/observations.json'
        if not path.is_file():
            self.skipTest('D8 bank absent: copy registered observations into build_stats11/bank/observations.json')
        b = material.derive_b(path)
        self.assertEqual(struct.pack('!d', b), struct.pack('!d', 0.0469305419921875))
        self.assertEqual(b, material.B)

    def test_reject_another_bank_before_reading_observations(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'observations.json'
            p.write_text('{"observations": []}')
            with self.assertRaisesRegex(ValueError, 'sha256'):
                material.derive_b(p)

    def test_scales_and_manifest(self):
        self.assertEqual(stats.DELTA_Q, 0.10 * material.B)
        self.assertEqual(stats.DELTA_C, stats.DELTA_Q)
        self.assertEqual(recurrence.D_Q, 2 * stats.DELTA_Q)
        self.assertEqual(stats.DELTA_P, math.log(1.10))
        self.assertEqual(recurrence.D_C, 0.10)
        man = calib.manifest(calib.synthetic_graph(2), calib.placeholder_params(), 99)
        self.assertEqual(man['material_spec'], material.specification())
        self.assertIn('material_spec_sha256', calib.IDENT)
        self.assertEqual(man['material_spec_sha256'], calib.doc_sha(material.specification()))

    def test_all_generator_survival_targets(self):
        rng = calib.VecSplitMix64(1)
        for mode, multiplier in (('F2', 1), ('FA1', 1), ('FA2', 2), ('F4', 1)):
            self.assertEqual(calib.plan_world('H-F', mode, 0, 0, rng)['rec']['full'][1], multiplier * material.D_Q)
        for slot, component in ((6, 'ARD'), (10, 'FSD'), (26, 'both')):
            p = calib.plan_world('H-T', 'T4', slot, 0, rng)
            self.assertIn(material.D_Q, [q for _, q in p['rec'].values()])

    def test_completed_non_rejection_and_failures(self):
        good = dict(available=True, T_T=-math.inf, c_T=stats.HT_GUARD, p_model=1.0)
        self.assertEqual(stats.family_p('H-T', good), (1.0, None))
        for changes in ({'T_T': math.nan}, {'T_T': math.inf}, {'failure': 'numerical'},
                        {'available': False}, {'p_model': math.nan}, {'p_model': -1}, {'c_T': 0}):
            self.assertIsNone(stats.family_p('H-T', dict(good, **changes))[0])
        obs = {e: dict(beta_P=0., beta_Q=0., EU_C=1., EU_Q=1., EF_C=0., EF_Q=0.)
               for e in ('E1', 'E2', 'E3')}
        draws = {e: {k: np.full(19, v) for k, v in row.items()} for e, row in obs.items()}
        tt = __import__('transition').ht_statistic(obs, draws, {e: False for e in obs})
        self.assertEqual(tt['T_T'], -math.inf)
        self.assertEqual(stats.family_p('H-T', dict(good, T_T=tt['T_T'])), (1., None))

    def test_age_support_and_expected_mean(self):
        ages = material.registered_ages()
        limit = material.cohort_ceiling(ages)
        self.assertEqual(limit, 247)
        self.assertEqual(material.cohort_ceiling({'ages': [39., 40., 41.], 'n': 3, 'max_age': 120.}), 2)
        self.assertEqual(material.cohort_ceiling(ages, 0), 600)
        p = calib.placeholder_params()
        p.pop('cohort')
        panel = calib.Panel(calib.synthetic_graph(2), p, 'H-F', 'dev', 'actual', 'F0', 0)
        self.assertEqual(panel.survivor_ceiling, limit)
        # Both extremes, plus a grid of standard normal quantiles; all outcomes are synthetic.
        mu, s = np.array([0.25]), np.array([0.20])
        K = calib.counts(mu, s, np.array([-1000., 1000.]), 600, limit)
        self.assertEqual(K.tolist(), [0., float(limit)])
        for mean, want in ((0., 0.), (limit / 600, float(limit))):
            self.assertEqual(calib.counts(np.array([mean]), s, np.array([100.]), 600, limit).tolist(), [want])
        self.assertEqual(calib.counts(np.zeros(2), s, np.array([-100., 100.]), 600, 0).tolist(), [0., 0.])
        for bad in (0.8, -0.1, math.nan):
            with self.assertRaisesRegex(calib.CalibError, 'age-bounded support'):
                calib.counts(np.array([bad]), s, np.array([0.]), 600, limit)
        # Capture remains supported on its full bound.
        self.assertEqual(float(calib.counts(np.array([0.8]), s, np.array([1000.]), 324)[0]), 324.)

    def test_float32_age_clock_boundary_and_registered_horizons(self):
        # Independent literal engine loop; the exact-arithmetic cutoff gives the WRONG answer here.
        start = 40.00001907348633
        end = np.float32(start)
        for _ in range(5000):
            end = np.float32(end + np.float32(0.016))
        self.assertEqual(float(end), 119.99422454833984)
        self.assertGreater(start + 5000 * 0.016, 120.)
        cohort = {'ages': [start], 'n': 1, 'max_age': 120.}
        self.assertEqual(material.cohort_ceiling(cohort), 1)
        for H, expected in ((5000, 247), (10000, 0), (20000, 0)):
            ages = material.registered_ages()
            clocks = np.array(ages['ages'], dtype=np.float32)
            for _ in range(H):
                clocks += np.float32(0.016)
            self.assertEqual(int(np.count_nonzero(clocks <= np.float32(120.))), expected)
            self.assertEqual(material.cohort_ceiling(ages, H), expected)
        # The one helper (#90's common.age_feasible) against direct NumPy binary32 clocks, for a supporting
        # physiology too, and for nearby floats.
        for H, dt, maximum in ((5000, .016, 120.), (800, .031, 30.)):
            starts = np.linspace(0, maximum, 101, dtype=np.float32)
            starts = np.r_[starts, np.float32(start)] if maximum == 120 else starts
            clocks = starts.copy()
            for _ in range(H):
                clocks += np.float32(dt)
            got = [common.age_feasible(float(a), H, maximum, dt) for a in starts]
            self.assertEqual(got, (clocks <= np.float32(maximum)).tolist())
            self.assertEqual(material.cohort_ceiling({'ages': starts.tolist(), 'n': len(starts), 'max_age': maximum}, H, dt),
                             sum(got))

    def test_ceiling_is_the_common_age_clock_for_every_registered_age(self):
        """Every feasibility decision of the statistics is #90's helper: the ceiling equals the per-individual
        age_death_frame count for all 600 frozen start ages (config, not outcomes) at 5k / 10k / 20k."""
        ages = material.registered_ages()
        for H, expected in ((5000, 247), (10000, 0), (20000, 0)):
            per = [common.age_death_frame(a, ages['max_age'], H) is None for a in ages['ages']]
            self.assertEqual(sum(per), expected)
            self.assertEqual(material.cohort_ceiling(ages, H), expected)
        self.assertEqual(material.age_clock_identity()['age_clock'], common.AGE_CLOCK)
        self.assertEqual(material.specification()['age_clock'], material.age_clock_identity())
        with self.assertRaises(ValueError):
            material.cohort_ceiling(ages, 5000.0)        # (a frame count, never a float horizon)

    def test_capped_law_independent_categories_and_draws(self):
        from statistics import NormalDist
        normal = NormalDist()
        N, M = 600, 247
        # Independent category probabilities: category M includes the entire upper tail.
        def categories(a, sd):
            cuts = [-math.inf] + [math.log((k-.5)/(N-k+.5)) for k in range(1, M+1)] + [math.inf]
            return np.array([normal.cdf((hi-a)/sd) - normal.cdf((lo-a)/sd)
                             for lo, hi in zip(cuts, cuts[1:])])
        for mu, sd in ((.25, .2), (.40, .37), (M/N-1e-5, .4)):
            lo, hi = -20., 20.
            for _ in range(70):
                mid = (lo+hi)/2
                if float(np.dot(np.arange(M+1), categories(mid, sd)))/N < mu:
                    lo = mid
                else:
                    hi = mid
            independent_location = (lo+hi)/2
            actual = float(calib.location(np.array([mu]), np.array([sd]), N, ceiling=M)[0])
            probs = categories(actual, sd)
            self.assertAlmostEqual(float(np.dot(np.arange(M+1), probs))/N, mu, delta=calib.LOC_S_TOL)
            self.assertAlmostEqual(actual, independent_location, delta=.002)
            z = np.array([normal.inv_cdf((i+.5)/20000) for i in range(20000)])
            raw = np.floor(N/(1+np.exp(-(actual + sd*z)))+.5)
            self.assertTrue(np.any(raw > M))
            got = calib.counts(np.full(len(z), mu), np.full(len(z), sd), sd*z, N, M)
            np.testing.assert_array_equal(got, np.minimum(M, raw))
            hist = np.bincount(got.astype(int), minlength=M+1)/len(z)
            self.assertLessEqual(float(np.max(np.abs(hist-probs))), 1/len(z)+1e-12)

    def test_capped_location_cache_identity_and_reload(self):
        saved = (calib.TABLE_CACHE, dict(calib._GRID), dict(calib._SCELL))
        try:
            with tempfile.TemporaryDirectory() as d:
                calib.TABLE_CACHE = d
                calib._GRID.clear(); calib._SCELL.clear()
                mu, sd = np.array([.25, .40]), np.array([.2025, .2025])
                first = calib.location(mu, sd, 600, ceiling=247)
                self.assertTrue(any('(600,_247)' in p.name for p in Path(d).glob('loc-*')))
                calib._GRID.clear(); calib._SCELL.clear()
                from unittest.mock import patch
                with patch.object(calib, '_build_table', side_effect=AssertionError('cache miss')):
                    second = calib.location(mu, sd, 600, ceiling=247)
                np.testing.assert_array_equal(first, second)
                raw = json.dumps(material.specification())
                self.assertIn(common.AGE_CLOCK, raw)
                self.assertIn(material.age_clock_identity()['helper_sha256'], raw)
                self.assertIn('600-rounded-logistic-normal-capped/1', raw)
        finally:
            calib.TABLE_CACHE = saved[0]
            calib._GRID.clear(); calib._GRID.update(saved[1])
            calib._SCELL.clear(); calib._SCELL.update(saved[2])

    def test_complete_registered_age_generator_pass(self):
        p = calib.placeholder_params()
        p['cohort'] = material.registered_ages()
        panel = calib.Panel(calib.synthetic_graph(2), p, 'H-F', 'dev', 'actual', 'F1', 12).simulate()
        self.assertEqual(len(panel.worlds), 2)
        result = panel.analyze_hf()
        self.assertTrue(result['full']['available'], result)
        self.assertTrue(math.isfinite(result['full']['S']))
        for w in panel.worlds:
            for ch in ('S', 'F', 'RS'):
                self.assertTrue(np.all((w['mu'][ch] >= 0) & (w['mu'][ch] <= 247/600)), ch)
            for ch in ('S', 'F'):
                self.assertTrue(np.all((w['K'][ch] >= 0) & (w['K'][ch] <= 247 * calib.R_REP)), ch)
        lat = {ch: np.array([0.]) for ch in ('C', 'RC', 'S', 'RS', 'F')}
        m = panel.means(lat)
        for ch in ('S', 'RS', 'F'):
            self.assertEqual(m[ch].tolist(), [247/1200])
        # Search/native means must use the same head, at extreme predictors as well.
        for eta in (-1000., 0., 1000.):
            wg = panel.g[0]
            lat = {ch: np.full(n, eta) for ch, n in
                   (('C', len(wg.ti)), ('S', len(wg.ti)), ('RC', len(wg.cT)), ('RS', len(wg.qT)), ('F', len(wg.prey)))}
            native = panel.native(wg, lat)
            self.assertTrue(np.all(np.abs(native['Q']) <= 247/600))
            self.assertTrue(np.all(np.abs(native['RQ']) <= 247/600))
            self.assertEqual(panel.means(lat)['F'][0], 247/600 * float(calib.sig(np.array([eta]))[0]))

    def test_calibration_streams_are_versioned_and_separated(self):
        import hashlib
        import transition
        tag = ('H-F', 'dev:actual', 'F1', 3, 'worlds')
        old = stats.stream_seed(*tag)
        new = stats.stream_seed(*tag, namespace='AnnexH/D8/1')
        independent = int.from_bytes(hashlib.sha256(('AnnexH/D8/1/'+'/'.join(map(str, tag))).encode()).digest()[:8], 'little')
        self.assertEqual(new, independent)
        self.assertNotEqual(old, new)
        p = calib.placeholder_params(); graph = calib.synthetic_graph(2)
        dev = calib.Panel(graph, p, 'H-F', 'dev', 'actual', 'F1', 3)
        val = calib.Panel(graph, p, 'H-F', 'val', 'actual', 'F1', 3)
        self.assertEqual(dev.rng('worlds').s, new)
        self.assertNotEqual(dev.rng('worlds').s, val.rng('worlds').s)
        self.assertEqual(calib.manifest(graph, p, 19)['calibration_stream_namespace'], 'AnnexH/D8/1')
        a = transition.draw_streams('calib/dev', 4, 2, 19)
        b = transition.draw_streams('calib/dev', 4, 2, 19, namespace='AnnexH/D8/1')
        c = transition.draw_streams('calib/val', 4, 2, 19, namespace='AnnexH/D8/1')
        self.assertFalse(np.array_equal(a[1], b[1]))
        self.assertFalse(np.array_equal(b[1], c[1]))

    def test_ht_calibration_stream_is_the_registered_key_under_the_d8_prefix(self):
        """D8 rule 51: the calibration H-T resampling replaces ONLY the prefix AnnexH/1/ by AnnexH/D8/1/; the
        remaining keys (H-T, calib/<tag>, bootstrap / reference-source) are the registered ones."""
        import hashlib
        import transition
        from unittest.mock import patch
        panel = calib.Panel(calib.synthetic_graph(2), calib.placeholder_params(), 'H-T', 'dev', 'actual', 'T1', 3)
        panel.worlds = []
        seen = {}

        def fake_ht(*a, **kw):
            seen.update(kw)
            return {'T_T': -math.inf, 'available': True, 'winner': None, 'phase_support': {}, 'EU_unsupported': {}}
        with patch.object(calib.recurrence, 'hf', return_value={'available': True, 'S_F': 0.}), \
                patch.object(calib.transition, 'ht', side_effect=fake_ht):
            panel.analyze_ht({e: 1. for e in transition.EPOCHS}, draws=3)
        self.assertEqual((seen['analysis'], seen['stream_namespace']), ('calib/H-T/dev:actual/T1/3', 'AnnexH/D8/1'))
        for purpose in ('bootstrap', 'reference-source'):
            text = f'AnnexH/D8/1/H-T/calib/H-T/dev:actual/T1/3/{purpose}'.encode()
            self.assertEqual(stats.stream_seed('H-T', seen['analysis'], purpose, namespace=seen['stream_namespace']),
                             int.from_bytes(hashlib.sha256(text).digest()[:8], 'little'))
            self.assertNotEqual(stats.stream_seed('H-T', seen['analysis'], purpose), stats.stream_seed(
                'H-T', seen['analysis'], purpose, namespace=seen['stream_namespace']))

    def test_rule_two_on_registered_reference_schedule(self):
        # graph.build measures EACH reference at graph.TIMES, independent of intensive status / fine offsets.
        times = np.array([1e-6 if t == 0 else float(t) for t in graph.TIMES])
        for scope in ('E1', 'E2', 'E3'):
            L, U = recurrence.SCOPES[scope]
            ts = times[(times >= L) & (times <= U)]
            for P in recurrence.EPOCH_PERIODS:
                self.assertTrue(recurrence.series_ok(ts, P), (scope, P))
        self.assertFalse(recurrence.series_ok([1e-6] + list(range(5, 51, 5)), 4.))


if __name__ == '__main__':
    unittest.main()
