# Fitting freeze: attachment to the preregistration (2026-11-04)

The preregistration (approved 2026-11-04T06:44Z; §3, "Fit failures") freezes deterministic initialization, the 200-iteration optimizer, the relative tolerance 1e-11 and the final pinned implementation, and it leaves the convergence repairs to be finished before bank1 is inspected. This file is the dated record of those repairs and of every numerical convention that decides whether a fit, a law or a quantile is accepted.

- **Source of truth:** `bounded.FIT_FREEZE` and the constants named below. The gate manifest records `FIT_FREEZE` and the SHA-256 of every tool source.
- **Written:** 2026-11-04, in PR #49, review round 2, before bank1's results were inspected.
- **Changing anything here** after the freeze needs a dated re-registration (preregistration §4, "On failure").

## 1. The optimizer (unchanged)

The optimizer is Levenberg–Marquardt, `bounded.lm`:
- λ starts at 1e-3, is divided by 3 on an accepted step (floor 1e-9), and is multiplied by 10 on a rejected one.
- It stops when an accepted step improves the SSE by less than **1e-11** (relative), or after **200** iterations.

The logistic start is the two-way additive fit of the logit:0.001-clipped means (`bounded.initial`). There are no restarts, no penalties and no rescue that depends on the outcome.

## 2. The linear predictor and its derivative

- η = μ + a_i + b_j is clamped to **±40** (`ETA_CLAMP`); beyond it the link is constant.
- σ'(x) is evaluated as **e^(−|x|) / (1 + e^(−|x|))²** at the clamped η (`bounded.dsigmoid`). This is the stable form: the old σ(1 − σ) cancelled to exactly 0 at logit 40, a vanished Jacobian.

## 3. When a fit counts as converged (`bounded.lm`'s exit classifier)

Let n be the number of cells, and **allow = 1e-4 · SSE + 1e-12 · max(‖y‖², n)** (`STAT_TOL`, `STAT_ABS`). An exit counts as converged only if all of the following hold:

1. **Every number is finite:** SSE, all parameters and all fitted values.
2. **The exit is exact** (SSE ≤ 1e-26 ‖y‖²), **or both of these hold:**
   - **(a) First-order stationarity.** The Gauss–Newton predicted decrease r'J (J'J + 1e-12 · max diag)⁻¹ J'r must be ≤ allow.
     - If the Jacobian has vanished entirely (max diag = 0), the predicted decrease counts as the whole SSE.
     - This is a regularized linearized gain, not a certificate of global optimality.
   - **(b) No residual on saturated cells.** Call a cell numerically saturated when every entry of its Jacobian row is ≤ 1e-12 (`SAT_D`, |η| ≳ 27.6). The residual energy on those cells must be ≤ allow. A vanished derivative never certifies an appreciable residual.
3. **At the iteration cap,** also max |J'r| ≤ 1e-9 · max(1, ‖y‖) (`GTOL`).

The absolute part of the allowance is 1e-12 per cell, i.e. a residual RMS of 1e-6 on a probability scale. It is what lets a **boundary infimum with negligible SSE** count as converged: for example, an item whose targets are all exactly 0, whose effect drifts towards −∞.

Every fit reports `reason` (one of exact, tol, step, damping, cap), `grad`, `stationarity` and `saturated_sse`.

A required fit that does not converge, a non-finite result, or a failed tangent-space projection (`bounded.Unavailable`) makes H1b **unavailable**. In the gate:
- an unavailable null decision counts as a rejection and an unavailable alternative as a failure;
- any unavailable dataset fails validity.

### Fixtures (`tests/invasion_tooling.sh`, step 42)

N = 12; logistic ladder σ(−2.3 + a_i + b_j) with a ~ N(0, 0.8²), b ~ N(0, 0.6²), seed 42.

| fixture | expected | result |
|---|---|---|
| interior (ladder + N(0, 0.01²), clipped to [0, 1]) | converged; SSE equal to an independent 2,000-iteration fit started at the true parameters | converged (tol); relative SSE difference 1.8e-14 |
| low variance (ladder ± 1e-9) | converged | converged (step) |
| zero row (invader 3: every target exactly 0) | converged (boundary infimum) | converged (tol) |
| zero column (resident 5 admits nobody) | converged | converged (cap) |
| an invader that always wins (targets exactly 1) | converged | converged (cap) |
| all-zero target matrix (Codex's boundary example) | converged | converged (cap); SSE 2.7e-21 |
| all logits 30 / 40 / 45, targets 0.5 | not converged | not converged; saturated SSE 33 |
| one item's effect at +47, classified where it stands | not converged | not converged; saturated SSE 9.6 |

On the PR #49 round-1 code (6a1971f), logits 40 and 45 and the partly saturated fit were "converged", and the all-zero boundary fit was not.

### Sweep (toy registered bank from the pilot's fitted ladders, 1 worker)

8,000 detector fits: 400 datasets × 4 fits in each of the L, J8, R05-D and R01-C null worlds and the J0 four-condition alternative.
- **0 unconverged.** Every fit exited on the SSE tolerance.
- **Largest predicted decrease / allow:** 2.2e-9, about nine orders of magnitude inside the threshold.
- **Saturated residual energy:** 0 in every fit.

The gate needs ~336,000 detector fits, plus another 64,000 in the diagnostics. This margin is the evidence that numerical false unavailability is negligible there. It is not a proof.

## 4. The bounded marginal law (`calibrate.marginal`)

The law follows preregistration §4:
- zero mass p0 = min(0.05, v / (2 (v + μ²))) for 0 < μ < 0.03, else p0 = 0;
- a Beta part with both moments exact;
- a point mass at v = 0 and a Bernoulli(μ) at v = μ(1 − μ).

Numerical conventions:
- **The Beta part's variance:** v_B = (v (1 − p0) − p0 μ²) / (1 − p0)², and v_B = v when p0 = 0. This has no cancellation: μ = 0.5, v = 1e-18 is a valid law with v_B = 1e-18, where it used to be an invalid one.
- **Achieved moments** use the law of total variance: Var = (1 − p0) v_B + p0 (1 − p0) m_B².
- **Endpoint band:** a requested v within the relative band **1e-12** of μ(1 − μ), on either side, is the Bernoulli endpoint and is flagged `edge` (`MARGINAL_EDGE`). Beyond the band, v > μ(1 − μ) is invalid: the world is not built and the gate fails.
- **Capping:** only the pilot-sourced pre-check world (pooled pilot SDs) may cap an infeasible v at the bound, and the cap is flagged.

## 5. The quantile function (joint worlds: q = F⁻¹(Φ(W)))

- The Beta quantile is tabulated in (logit u, logit x) at exact nodes with exact slopes, using cubic Hermite interpolation. The table is refined until every interval's midpoint is within **1e-10** in logit x (`QTABLE_TOL`).
- For |logit u| > 36, the quantile is solved exactly by bisection.
- The continued fraction's iteration budget grows as √max(a, b).
- When **both shapes exceed 1e7** (`QCF_MIN`), a fourth-order Cornish–Fisher expansion is used instead. Its error is O(SD |skewness|³). Against the exact table at (2e5, 5e5) it agrees within 5e-10.
- Uniforms are carried as the pair (u, 1 − u), each accurate in its own tail.

## 6. Plants (`calibrate.feasible_plant`)

- **Construction:** the probability-scale cycle, clipped to [0.002, 0.998]. The amplitude c is the first crossing of d_res ≥ target on the grid 0, 0.001, …, 1, then bisection to **1e-4 relative**.
- **Noiseless refits:** each uses `bounded.fit`, warm-started from the previous evaluation, and must converge under §3.
- **Diagnostics exported:** `d_res_clip0`, the effect of the clipped null alone.

## 7. Open choice, not frozen here

The rare-event reflection is `calibrate.RARE_REFLECTION`, currently "conjugate" (U' = 1 − T(1 − U)); the alternative is "literal" (1 − T(U)). The gate manifest records the choice. It awaits the user's decision; per Codex's ruling, keeping conjugation needs a dated amendment.
