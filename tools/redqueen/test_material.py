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
        loc = calib.location(mu * 600 / limit, s, limit)
        expected = calib.expected_fraction(loc, 0.20, limit) * limit / 600
        self.assertAlmostEqual(float(expected[0]), float(mu[0]), delta=calib.LOC_S_TOL)
        for bad in (limit / 600, 0.8, -0.1, math.nan):
            with self.assertRaisesRegex(calib.CalibError, 'age-bounded support'):
                calib.counts(np.array([bad]), s, np.array([0.]), 600, limit)
        # Capture remains supported on its full bound.
        self.assertEqual(float(calib.counts(np.array([0.8]), s, np.array([1000.]), 324)[0]), 324.)

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
