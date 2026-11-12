"""D8 (2026-11-12): prospective survival materiality, independent pooled bank magnitude.

No time stratification or directional fits are permitted in deriving this constant.
The observations hash fixes the complete registered allocation, including positive q.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path

OBSERVATIONS_SHA256 = '64b113ce30bf76c52cda19efcde227becc2b9c00de0e2a5bbbe2892630f5cf84'
AGES_SHA256 = '6ffb99ec4062801b68c462ab08208e8367d128ca820e0a9e84752f4403a717d5'
B = 0.0469305419921875
DELTA_Q = DELTA_HC = 0.10 * B
D_Q = 0.20 * B


def specification():
    return {'schema': 'finfolk.redqueen.material/D8', 'amendment': 'D8', 'date': '2026-11-12',
            'b': B, 'definition': 'mean over all 256 exposed pairs of abs(mean over all 64 matched replicates '
            'of (L-L0)/600), at 5000 steps; controls matched by prey identity and replicate; positive q kept; '
            'no time stratification or outcome exclusions',
            'observations_sha256': OBSERVATIONS_SHA256, 'ages_sha256': AGES_SHA256,
            'delta_Q_per_50M': DELTA_Q, 'delta_HC_per_50M': DELTA_HC, 'd_Q_RMS': D_Q,
            'directional_fraction': 0.10, 'recurrent_fraction': 0.20,
            'capture': 'unchanged: delta_P=log(1.10), d_C=0.10'}


def derive_b(path):
    """Exact rational sums, one final binary64 rounding; refuse every other file, before parsing."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != OBSERVATIONS_SHA256:
        raise ValueError('D8: observations sha256 is not the frozen registered bank')
    doc = json.loads(raw)
    if doc.get('missing'):
        raise ValueError('D8 requires the complete bank')
    free, pairs = {}, {}
    for o in doc['observations']:
        prey, pred, r = tuple(o['prey']), o['pred'], o['replicate']
        L = o['horizons']['5000']['survivors']
        if type(L) is not int or not 0 <= L <= 600 or type(r) is not int or not 0 <= r < 64:
            raise ValueError('D8: invalid cohort count / replicate')
        group = free if pred is None else pairs.setdefault((prey, tuple(pred)), {})
        key = (prey, r) if pred is None else r
        if key in group:
            raise ValueError('D8: duplicate observation')
        group[key] = L
    if len(pairs) != 256 or len(free) != 32 * 64:
        raise ValueError('D8: incomplete registered allocation')
    total = Fraction(0)
    for (prey, _), reps in sorted(pairs.items()):
        if set(reps) != set(range(64)):
            raise ValueError('D8: incomplete exposed pair')
        total += abs(Fraction(sum(reps[r] - free[prey, r] for r in range(64)), 64 * 600))
    return float(total / 256)


def cohort_ceiling(ages, horizon=5000, dt=0.016, max_age=None):
    """Initial prey capable of surviving age mortality; boundary equality is retained."""
    import math
    values = ages['ages']
    maximum = ages['max_age'] if max_age is None else max_age
    if (not values or len(values) != ages['n'] or horizon < 0 or dt <= 0 or
            not math.isfinite(maximum) or maximum <= 0 or
            any(not math.isfinite(a) or a < 0 or a > maximum for a in values)):
        raise ValueError('invalid registered cohort / horizon / age law')
    cutoff = maximum - horizon * dt
    return sum(a <= cutoff for a in values)


def registered_ages():
    raw = (Path(__file__).parent / 'fixtures' / 'registered_ages.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != AGES_SHA256:
        raise ValueError('registered ages sha256 differs from D8 provenance')
    return json.loads(raw)
