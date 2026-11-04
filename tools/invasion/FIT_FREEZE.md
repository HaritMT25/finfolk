# Fitting freeze: attachment to the preregistration (2026-11-04)

The preregistration (approved 2026-11-04T06:44Z; §3, "Fit failures") freezes deterministic initialization, the 200-iteration optimizer, the relative tolerance 1e-11 and the final pinned implementation. It leaves the convergence repairs to be finished before bank1 is inspected. This file is the dated record of those repairs and of every numerical convention that decides whether a fit, a law or a quantile is accepted.

- **Source of truth:** `bounded.FIT_FREEZE` and the constants named below. The gate manifest records `FIT_FREEZE` and the SHA-256 of every tool source.
- **Written:** 2026-11-04, in PR #49, review rounds 2–4, before bank1's results were inspected.
- **Changing anything here** after the freeze needs a dated re-registration (preregistration §4, "On failure").

## 1. The optimizer (unchanged by these repairs)

The optimizer is Levenberg–Marquardt, `bounded.lm`. Each iteration solves **(J'J + λ · diag(J'J) + 1e-18 · I) step = J'r**:
- **`LM_DIAG` = 1e-18** is an absolute diagonal stabilizer.
- λ starts at 1e-3, is divided by 3 on an accepted step (floor 1e-9), and is multiplied by 10 on a rejected one. An accepted step is one with SSE_new ≤ SSE, ties included.

The exits are:
- **exact:** SSE ≤ 1e-26 · max(‖y‖², **1e-30**);
- **tol:** an accepted step improved the SSE by S − S_new ≤ 1e-11 · max(S, **1e-30**);
- **step:** the step is at most 1e-12 · (1 + max |θ|);
- **damping:** λ exceeded 1e6 without an accepted step;
- **cap:** **200** iterations.

The logistic start is the two-way additive fit of the logit:0.001-clipped means (`bounded.initial`). There are no restarts and no penalties.

**No outcome-dependent rescue.** The classifier below only ever *marks* a fit unconverged. It never changes a fitted value: its Gauss–Newton probe evaluates trial points and adopts none.

## 2. The linear predictor and its derivative

- η = μ + a_i + b_j is clamped to **±40** (`ETA_CLAMP`). Beyond the clamp the link is constant.
- σ'(x) is evaluated as **e^(−|x|) / (1 + e^(−|x|))²** at the clamped η (`bounded.dsigmoid`), the stable form.

## 3. When a fit counts as converged (`bounded.lm`'s exit classifier)

Let n be the number of cells, and **allow = 1e-4 · SSE + 1e-12 · max(‖y‖², n)** (`STAT_TOL`, `STAT_ABS`). An exit counts as converged only if all of the following hold:

1. **Every number is finite:** SSE, all parameters, all fitted values and every Jacobian entry.
2. **The exit is exact, or both of these hold:**
   - **(a) No realizable linearized gain.** The **exact** linearized gain ‖Q₁'r‖² must be ≤ allow, **or** the Gauss–Newton probe must fail to realize it.
     - **The gain** is computed by Householder QR of J with column pivoting (`bounded.qr_gain`). The reflections are applied to r as they are formed, and the numerical rank is taken at the first pivot |R_kk| ≤ 1e-13 · |R₁₁| (`RANK_TOL`).
     - Every direction and every **combination** of the tangent space that is numerically resolvable counts, however weak. In review round 3, column scaling plus a ridge still hid a0 − a1; that is not possible here.
     - **The probe** (`bounded.gn_probe`) evaluates θ + t · d along the exact Gauss–Newton step d, the least-squares solution on the resolved columns, at t = 1, 0.8, 0.8², …, for 220 points. It never adopts one.
     - The fit is **unconverged** if any probe lowers the SSE by more than allow.
   - **(b) No unresolved residual.** The residual energy on numerically **flat** cells must be ≤ allow. A cell is flat when |η| ≥ the clamp (the link is constant there, and the reported derivative is the clamp point's), or when its Jacobian row is ≤ 1e-13 · max |J|. Such cells carry no first-order information.
3. **At the iteration cap,** also max |J'r| ≤ 1e-9 · max(1, ‖y‖) (`GTOL`).

**Why the probe is there.** A first-order gain cannot by itself tell two cases apart.
- **A stalled saturation** is a weak direction along which a *finite move* removes the residual. Fixture A is one: a0 = +25, a1 = −25, targets 0.5, SSE 5.5, where θ = 0 gives SSE 0.
- **An unrealizable weak direction** is one whose linear prediction no finite move achieves. Two examples: a boundary infimum whose pseudo-targets lie outside [0, 1], and a well-converged fit with an ill-conditioned weak combination.

The exact gain alone flagged 292 of the pilot's 1,999 bootstrap refits at T. For those flagged fits, the exact Gauss–Newton step with a line search lowered nothing (≤ 1e-14), and neither did 20,000 more LM iterations. Under the full rule, 0 of those refits are unconverged.

Conversely, in the bounded.py self-test's planted-cycle bootstrap (N = 5, pseudo-means outside [0, 1]), some refits **really** stall along a weak combination. LM exits on its tolerance, and 20,000 more iterations change nothing, but the probe realizes up to 18% lower SSE: LM's λ · diag(J'J) damping cannot move there. Those refits are now correctly unconverged, so that bootstrap p-value is withheld. Every earlier classifier wrongly certified them.

**The absolute allowance.** 1e-12 per cell is a residual RMS of 1e-6 on a probability scale.
- It lets a boundary infimum with negligible SSE count as converged, such as an item whose targets are all exactly 0.
- It cannot certify relative fitting accuracy for arbitrarily low-noise cells.

Every fit reports `reason`, `grad`, `stationarity` (the exact gain / SSE), `rank`, `flat_sse`, `saturated_sse`, and `probe_decrease` when probed.

A required fit that does not converge, a non-finite result, or a failed tangent-space projection (`bounded.Unavailable`) makes H1b **unavailable**. In the gate:
- an unavailable null decision counts as a rejection and an unavailable alternative as a failure;
- any unavailable dataset, gate or diagnostic, fails validity.

### Fixtures (`tests/invasion_tooling.sh`, step 42)

N = 12; logistic ladder σ(−2.3 + a_i + b_j) with a ~ N(0, 0.8²), b ~ N(0, 0.6²), seed 42.

| fixture | expected | result |
|---|---|---|
| interior (ladder + N(0, 0.01²), clipped to [0, 1]) | converged; SSE equal to the **independent reference** | converged; relative SSE difference 1.8e-14 |
| low variance (ladder ± 1e-9) | converged | converged |
| zero row / zero column / an invader that always wins | converged (boundary infima) | converged |
| all-zero target matrix (Codex round 1) | converged | converged; SSE 2.7e-21 |
| all logits 30 / 40 / 45, targets 0.5 | not converged | not converged |
| one item's effect at +47, classified where it stands | not converged | not converged (flat cells) |
| **A** in 12 arrangements: a_i = +25, a_j = −25, on invader and on resident effects, incl. Codex's a0 / a1 (rounds 3–4) | not converged | not converged; gain ≈ SSE at full rank 23 |
| **B:** the rectangle local minimum (round 3) | converged | converged; gain 2e-23 |

**The independent reference shares no code with `bounded.py`.** It has:
- its own model: overparametrized (μ, a_0..11, b_0..11), σ via tanh, σ' via 1/(4 cosh²);
- its own Cholesky solver and Gauss–Newton;
- its own modified Gram–Schmidt least squares and line search.

It confirms the following:
- **Interior:** the SSE agrees to 1.8e-14.
- **A, every arrangement:** its own gain exceeds 0.99 · SSE, and its own line search realizes 25% of the SSE (the allowance is 1e-4 of it).
- **B:** its gain is below 1e-12 · SSE, its probe realizes nothing, and all 400 random perturbations raise the SSE.

scipy and numpy are not installed in this WSL.

**On older code:**
- 6a1971f (round 1): logits 40 / 45 and the partly saturated fit were "converged"; the all-zero fit was not.
- 13a8a63 (round 2): A was "converged", B was not.
- d7542a5 (round 3): A permuted to a0 / a1 was "converged".

### Sweep: what it shows and what it does not

The sweep uses the toy registered bank built from the pilot's fitted ladders: four processes at nice 19, every detector fit recorded. It covered 8,000 fits under the final classifier: 400 datasets × 4 fits in each of the L, J8, R05-D and R01-C null worlds and the J0 four-condition alternative.
- **Unconverged:** 0.
- **Probed:** 0, meaning the exact gain exceeded the allowance.
- **Largest exact gain / allow:** 1.3e-9 (J8). The largest flat-cell energy is 0, and every exit was `tol`.

The pilot's own primary H1b fits and all 2 × 1,999 bootstrap refits are converged (0 probed). The H1b decisions are unchanged: p = 3/1024 at T and 2/1024 at 2T, with p_boot 0.0005.

**What this does not establish.** The gate needs ~336,000 detector fits in its gate datasets and ~64,000 in its diagnostics.
- Zero failures in 8,000 fits gives a per-fit false-unavailability bound of about 3 / 8,000 ≈ 3.7e-4 (95%, one-sided). That is **an iid-binomial illustration only**: the fits are not independent, since the four fits of a dataset share it and the assays' noise is deliberately dependent in several worlds.
- A ≤ 5% chance of any flag across ~400,000 fits would need a rate near 1.3e-7. That is **not** established.
- The margin, many orders of magnitude between ordinary fits and the threshold, suggests the threshold sits far from them. It cannot exclude rare pathological datasets.
- If one occurs, the gate fails closed: validity fails and the gate does not pass. A failed gate is then handled under the registration's "On failure" rule.

## 4. The bounded marginal law (`calibrate.marginal`)

The law follows preregistration §4:
- zero mass p0 = min(0.05, v / (2 (v + μ²))) for 0 < μ < 0.03, else p0 = 0;
- a Beta part with both moments exact;
- a point mass at v = 0 and a Bernoulli(μ) at v = μ(1 − μ).

Numerical conventions:
- **The Beta part's variance:** v_B = (v (1 − p0) − p0 μ²) / (1 − p0)², and v_B = v when p0 = 0.
- **Achieved moments** use the law of total variance.
- **Endpoint band:** a requested v within the relative band **1e-12** of μ(1 − μ) is the Bernoulli endpoint and is flagged `edge`. Beyond the band, an infeasible request fails.
- **Capping:** only the pilot-sourced pre-check world may cap an infeasible v, and the cap is flagged.

## 5. The quantile function (joint worlds: q = F⁻¹(Φ(W)))

**What "exact" means here.** The quantile is a numerically computed inverse, not an exact one.
- **Interpolation:** the error is ≤ ~1e-10 in logit x within the table's domain, checked at every interval's midpoint. That is a refinement test, not a proved uniform bound.
- **Near 1:** x is limited by the double's own resolution (absolute ~1e-16).
- **The CDF evaluator's accuracy** depends on the regime below.

**The table** is built in (s, t) = (logit u, logit x) **on exactly s ∈ [−36, 36]**:
- **Endpoints:** t(±36) are solved by bracketing from t₀ = log a − log b, in steps growing from the law's logit SD s/√(ab(s + 1)), then bisection to 1e-9 in s.
- **Nodes:** exact nodes and slopes, joined by cubic Hermite interpolation.
- **Refinement:** an interval is split until it is at most 0.5 wide in s and its midpoint is within 1e-10 in logit x.
- **Stop rule:** an interval narrower than 1e-9 logit SDs is kept even if its test fails. Such cases are counted in `floor_hits`, which is 0 in every tested law.
- **Outside the domain** (|s| > 36), the quantile is solved by bisection on the same CDF evaluator.

**The CDF evaluator, by regime:**
- **Normalizer:** −log B(a, b) by `calibrate.betaln`. Both shapes < 10: direct lgamma. Otherwise, Stirling with log1p forms and series corrections, error ≤ ~1e-12. This replaced the lgamma subtraction, which gave 0 instead of 36.84 at (1, 1e16).
- **Extreme asymmetry:** when b ≥ 10³ (a + 1) and |a − 1| (a + 10√a + 40) / b ≤ 0.5, or mirrored for a ≫ b, the tails come from a series of regularized incomplete gamma functions in τ = −log(1 − x) (BGRAT type), with 30 terms of the expansion of ((1 − e^−s)/s)^(a−1). There the continued fraction would need 1 − x to more precision than a double holds.
- **Otherwise:** Numerical Recipes' continued fraction, with an iteration budget that grows as √max(a, b).
- **Both shapes > 1e7:** fourth-order Cornish–Fisher. Against the exact table at (2e5, 5e5) it agrees within 5e-10.

**Regressions (step 43):**
- Closed forms Beta(1, b) (F⁻¹ = −expm1(log(1 − u)/b)) and Beta(a, 1) (F⁻¹ = u^(1/a)), for a, b ∈ {3, 1e4, 1e9, 1e16} and u ∈ {e^−40, 1e-10, 0.3, 0.9, 1 − 1e-12}: relative error ≤ 1e-9 in x, or in 1 − x near 1 up to the double's resolution. The tables have < 3,000 nodes.
- The concentrated law (shapes 9e6): a 223-node table.

**Not established:** a uniform accuracy proof for every (a, b). Large shapes that are both below 1e7 but highly asymmetric outside the series regime rely on the continued fraction. Its accuracy there degrades as ~ε · (a + b) in the CDF's relative value: about 2e-9 at a + b = 1e7, a negligible fraction of the law's SD.

## 6. Plants (`calibrate.feasible_plant`)

- **Construction:** the probability-scale cycle, clipped to [0.002, 0.998]. The amplitude c is the first crossing of d_res ≥ target on the grid 0, 0.001, …, 1, then bisection to **1e-4 relative**.
- **Noiseless refits:** each uses `bounded.fit`, warm-started from the previous converged evaluation, and must converge under §3.
- **The clipped null's refit (c = 0):** if it does not converge, the plant is not constructed and validity fails. Its effect is exported as `d_res_clip0`.

## 7. The rare-event reflection

The rare-event reflection is `calibrate.RARE_REFLECTION`, "conjugate" (U' = 1 − T(1 − U)); the alternative reading is "literal" (1 − T(U)). The gate manifest records the choice. It is conjugate, per Amendment 1 (2026-11-04T16:23Z) of the approval record; per Codex's ruling, keeping conjugation needed that dated amendment.
