#!/usr/bin/env python3
"""noisescale.py: the noise bank's serialized s(mu) curve and its ONE evaluator, shared by noisebank.py (the
bank's fit and the production V builder) and calib.py (the generator noise and the analysis weights).
Amendment D4 rule 13; design v4 section 7.4; Annex H.9.2.

A CURVE (one channel) is {"x": [...], "s": [...]} with optional "direction":
  x          the knots on the latent location logit(mu): finite and strictly increasing;
  s          the values: finite and > 0, MONOTONE (all non-increasing or all non-decreasing);
  direction  "increasing" / "decreasing", when present, must agree with s.
s(mu) is linear in logit(mu) between the knots. Beyond the outermost knots it is held CONSTANT: an
extrapolation assumption outside the bank's measured support, not an estimate. A single knot is a
constant curve.
A curve SET maps the channels C (capture), S (exposed survival) and F (predator-free survival) to curves.

This file is byte-identical on every branch that carries it, so there is one implementation.
"""
from __future__ import annotations

import math

CHANNELS = ("C", "S", "F")


class ScaleError(ValueError):
    pass


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_curve(c, ch="?"):
    """A valid curve (see the module docstring), else ScaleError."""
    if not isinstance(c, dict) or not isinstance(c.get("x"), list) or not isinstance(c.get("s"), list):
        raise ScaleError(f"s_logit[{ch}]: a curve is {{'x': [knots], 's': [values]}}")
    x, s = c["x"], c["s"]
    if not x or len(x) != len(s):
        raise ScaleError(f"s_logit[{ch}]: {len(x)} knots and {len(s)} values (at least one, equally many)")
    if not all(_num(v) for v in x + s):
        raise ScaleError(f"s_logit[{ch}]: knots and values must be finite numbers")
    if any(b <= a for a, b in zip(x, x[1:])):
        raise ScaleError(f"s_logit[{ch}]: the knots must be strictly increasing")
    if any(v <= 0 for v in s):
        raise ScaleError(f"s_logit[{ch}]: the values must be positive")
    d = [b - a for a, b in zip(s, s[1:])]
    up, down = any(v > 0 for v in d), any(v < 0 for v in d)
    if up and down:
        raise ScaleError(f"s_logit[{ch}]: the values are not monotone")
    want = c.get("direction")
    if want is not None and (want not in ("increasing", "decreasing") or (want == "increasing" and down)
                             or (want == "decreasing" and up)):
        raise ScaleError(f"s_logit[{ch}]: direction {want!r} disagrees with the values")
    return c


def check_set(curves, channels=CHANNELS):
    """A curve for every channel, each valid."""
    if not isinstance(curves, dict):
        raise ScaleError("s_logit: a curve set {channel: curve} is required")
    missing = [ch for ch in channels if ch not in curves]
    if missing:
        raise ScaleError(f"s_logit: no curve for {missing}")
    for ch in channels:
        check_curve(curves[ch], ch)
    return curves


def evaluate(c, mu):
    """s(mu) of one curve, vectorized over mu (linear in logit(mu) between knots, constant beyond)."""
    import numpy as np
    mu = np.asarray(mu, float)
    x = np.log(np.clip(mu, 1e-300, None) / np.clip(1 - mu, 1e-300, None))
    return np.interp(x, np.asarray(c["x"], float), np.asarray(c["s"], float))
