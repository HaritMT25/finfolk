# Fitting freeze: attachment to the preregistration (2026-11-04)

The preregistration (approved 2026-11-04T06:44Z; §3, "Fit failures") freezes deterministic initialization, the 200-iteration optimizer, the relative tolerance 1e-11 and the final pinned implementation, and it leaves the convergence repairs to be finished before bank1 is inspected. This file is the dated record of those repairs and of every numerical convention that decides whether a fit, a law or a quantile is accepted.

- **Source of truth:** `bounded.FIT_FREEZE` and the constants named below. The gate manifest records `FIT_FREEZE` and the SHA-256 of every tool source.
- **Written:** 2026-11-04, in PR #49, review rounds 2–3, before bank1's results were inspected.
- **Changing anything here** after the freeze needs a dated re-registration (preregistration §4, "On failure").

## 1. The optimizer (unchanged by these repairs)

The optimizer is Levenberg–Marquardt, `bounded.lm`. Each iteration solves **(J'J + λ · diag(J'J) + 1e-18 · I) step = J'r**:
- **`LM_DIAG` = 1e-18** is an absolute diagonal stabilizer. It matters precisely along nearly saturated directions, where diag(J'J) ≪ 1e-18.
- λ starts at 1e-3, is divided by 3 on an accepted step (floor 1e-9), and is multiplied by 10 on a rejected one.

The exits are:
- **exact:** SSE ≤ 1e-26 ‖y‖²;
- **tol:** an accepted step improved the SSE by less than **1e-11** (relative);
- **step:** the step is at most 1e-12 · (1 + max |θ|);
- **damping:** λ exceeded 1e6 without an accepted step;
- **cap:** **200** iterations.

The logistic start is the two-way additive fit of the logit:0.001-clipped means (`bounded.initial`). There are no restarts and no penalties.

**No outcome-dependent rescue:** the classifier below only ever *marks* a fit unconverged. It never changes a fitted value.

## 2. The linear predictor and its derivative

- η = μ + a_i + b_j is clamped to **±40** (`ETA_CLAMP`); beyond it the link is constant.
- σ'(x) is evaluated as **e^(−|x|) / (1 + e^(−|x|))²** at the clamped η (`bounded.dsigmoid`). This is the stable form: the old σ(1 − σ) cancelled to exactly 0 at logit 40.

## 3. When a fit counts as converged (`bounded.lm`'s exit classifier)

Let n be the number of cells, and **allow = 1e-4 · SSE + 1e-12 · max(‖y‖², n)** (`STAT_TOL`, `STAT_ABS`). An exit counts as converged only if all of the following hold:

1. **Every number is finite:** SSE, all parameters and all fitted values.
2. **The exit is exact, or the fit is first-order stationary *in column-scaled form*.** Let D = diag(J'J), J̃ = J D^(−1/2) and g̃ = D^(−1/2) J'r. The Gauss–Newton predicted decrease **g̃' (J̃'J̃ + 1e-12 · I)⁻¹ g̃** (`STAT_RIDGE`) must be ≤ allow.
   - Every parameter direction is assessed on its own scale, so a weak direction cannot be hidden by a ridge sized to the strong ones. That was review round 3's fixture A: derivatives 1.4e-11, which the old global ridge, 1e-12 · max diag, hid completely.
   - If the Jacobian has vanished entirely, the predicted decrease is the whole SSE.
3. **At the iteration cap,** also max |J'r| ≤ 1e-9 · max(1, ‖y‖) (`GTOL`).

**What kind of test this is.** It is first-order: a regularized, linearized gain, not a certificate of global or local optimality.
- **A stalled saturation is rejected.** A large scaled score means the residual still has a direction to go; for example, an item pushed far beyond its targets.
- **A legitimate minimum keeps residual it cannot remove locally.** Its score is zero even if some of that residual sits on a numerically saturated cell. That is fixture B, Codex's rectangle.
- **The saturated-cell veto is gone.** The round-2 rule rejected any residual on saturated cells (Jacobian row ≤ 1e-12) and so wrongly rejected B. That residual energy is still reported, as `saturated_sse`.

**The absolute allowance.** 1e-12 per cell is a residual RMS of 1e-6 on a probability scale.
- It lets a boundary infimum with negligible SSE count as converged, such as an item whose targets are all exactly 0.
- By the same token, it cannot certify relative fitting accuracy for arbitrarily low-noise cells.

Every fit reports `reason`, `grad`, `stationarity` and `saturated_sse`.

A required fit that does not converge, a non-finite result, or a failed tangent-space projection (`bounded.Unavailable`) makes H1b **unavailable**. In the gate:
- an unavailable null decision counts as a rejection and an unavailable alternative as a failure;
- any unavailable dataset, gate or diagnostic, fails validity.

### Fixtures (`tests/invasion_tooling.sh`, step 42)

N = 12; logistic ladder σ(−2.3 + a_i + b_j) with a ~ N(0, 0.8²), b ~ N(0, 0.6²), seed 42.

| fixture | expected | result |
|---|---|---|
| interior (ladder + N(0, 0.01²), clipped to [0, 1]) | converged; SSE equal to the **independent reference** (below) | converged; relative SSE difference 1.8e-14 |
| low variance (ladder ± 1e-9) | converged | converged |
| zero row (invader 3: every target exactly 0) | converged (boundary infimum) | converged |
| zero column (resident 5 admits nobody) | converged | converged |
| an invader that always wins (targets exactly 1) | converged | converged |
| all-zero target matrix (Codex round 1's boundary example) | converged | converged; SSE 2.7e-21 |
| all logits 30 / 40 / 45, targets 0.5 | not converged | not converged; SSE 33 |
| one item's effect at +47, classified where it stands | not converged | not converged |
| **A:** a0 = +25, a11 = −25, targets 0.5 (Codex round 3) | not converged: SSE 5.5, while θ = 0 gives 0 | not converged; scaled predicted decrease ≈ the whole SSE |
| **B:** the rectangle local minimum (Codex round 3) | converged: score 0, a local minimum | converged; scaled predicted decrease 5e-31 |

**The independent reference shares no code with `bounded.py`.** It has:
- its own model: overparametrized (μ, a_0..11, b_0..11), σ via tanh, σ' via 1/(4 cosh²);
- its own Cholesky solver;
- Gauss–Newton with a line search.

It confirms the following:
- **Interior:** the SSE agrees to 1.8e-14 relative.
- **A:** θ = 0 has SSE exactly 0, and the reference's own column-scaled score at A is ≥ 0.4 of the SSE.
- **B:** all 400 random perturbations of size 1e-3 or 1e-2 have a larger SSE, and the reference's Gauss–Newton cannot descend from B.

scipy and numpy are not installed in this WSL, so no third-party solver was used.

**On older code:**
- On 6a1971f (round 1), logits 40 / 45 and the partly saturated fit were "converged", and the all-zero boundary fit was not.
- On 13a8a63 (round 2), A was "converged" and B was not.

### Sweep: what it shows and what it does not

The sweep uses the toy registered bank built from the pilot's fitted ladders, at 1 worker. It covered 8,000 detector fits under the final classifier: 400 datasets × 4 fits in each of the L, J8, R05-D and R01-C null worlds and the J0 four-condition alternative.
- **0 unconverged.** Every fit exited on the SSE tolerance.
- **Largest predicted decrease / allow:** 1.7e-9.
- **Saturated residual energy:** 0 in every fit.

An earlier 8,000-fit sweep under the round-2 classifier also gave 0 unconverged, with a largest predicted decrease / allow of 2.2e-9.

**What this does not establish.** The gate needs ~336,000 detector fits in its gate datasets and ~64,000 in its diagnostics.
- 0 failures in 8,000 fits bounds the per-fit false-unavailability rate only at **≤ 3.7e-4** (95%, one-sided).
- A ≤ 5% chance of any flag across ~400,000 fits would need a rate near **1.3e-7**. That is **not** established.
- The margin, about nine orders of magnitude between the bulk of legitimate fits and the threshold, suggests the threshold sits far from ordinary fits. It cannot exclude rare pathological datasets.
- If one occurs, the gate fails closed: validity fails and the gate does not pass. A failed gate is then handled under the registration's "On failure" rule.

## 4. The bounded marginal law (`calibrate.marginal`)

The law follows preregistration §4:
- zero mass p0 = min(0.05, v / (2 (v + μ²))) for 0 < μ < 0.03, else p0 = 0;
- a Beta part with both moments exact;
- a point mass at v = 0 and a Bernoulli(μ) at v = μ(1 − μ).

Numerical conventions:
- **The Beta part's variance:** v_B = (v (1 − p0) − p0 μ²) / (1 − p0)², and v_B = v when p0 = 0. This has no cancellation.
- **Achieved moments** use the law of total variance: Var = (1 − p0) v_B + p0 (1 − p0) m_B².
- **Endpoint band:** a requested v within the relative band **1e-12** of μ(1 − μ), on either side, is the Bernoulli endpoint and is flagged `edge` (`MARGINAL_EDGE`). Beyond the band, v > μ(1 − μ) is invalid: the world is not built and the gate fails.
- **Capping:** only the pilot-sourced pre-check world (pooled pilot SDs) may cap an infeasible v, and the cap is flagged.

## 5. The quantile function (joint worlds: q = F⁻¹(Φ(W)))

The Beta quantile is tabulated in (s, t) = (logit u, logit x) **on exactly s ∈ [−36, 36]** (`QTABLE_S`):
- **Endpoints:** t(−36) and t(+36) are solved by bracketing from the mean, in steps growing from the law's logit SD, then bisection to 1e-9 in s.
- **Nodes:** exact nodes with exact slopes dt/ds, joined by cubic Hermite interpolation.
- **Refinement:** an interval is split until it is at most **0.5** wide in s (`QTABLE_DS`) and its interpolant matches the exact curve at the midpoint to **1e-10** in logit x (`QTABLE_TOL`).
- **Stop rule:** an interval narrower than **1e-9 logit SDs** of the law (`QTABLE_MIN_DT`) is kept even if its midpoint test fails. Such cases are counted in `floor_hits`, which is 0 in every tested law.
- **Outside the domain** (|s| > 36, and within 1e-9 of the solved endpoints), the quantile is solved exactly by bisection on s(t) (`exact_t`).

Concentrated-law regression (step 43). μ = 0.5, v = 0.25 / 18,000,001 gives shapes 9e6. The table has **223 nodes**, builds in 0.1 s and has an error ≤ 1.1e-11. The old table kept its bracketing overshoot to |s| ≈ 557,000, about 2.2 million nodes.

Other notes:
- The continued fraction's iteration budget grows as √max(a, b).
- When **both shapes exceed 1e7** (`QCF_MIN`), a fourth-order Cornish–Fisher expansion is used instead. Against the exact table at (2e5, 5e5) it agrees within 5e-10.
- Uniforms are carried as the pair (u, 1 − u), each accurate in its own tail.

## 6. Plants (`calibrate.feasible_plant`)

- **Construction:** the probability-scale cycle, clipped to [0.002, 0.998]. The amplitude c is the first crossing of d_res ≥ target on the grid 0, 0.001, …, 1, then bisection to **1e-4 relative**.
- **Noiseless refits:** each uses `bounded.fit`, warm-started from the previous converged evaluation, and must converge under §3.
- **The clipped null's refit (c = 0):**
  - if it does not converge, the plant is not constructed (`solved` False, `clip0_converged` False), and the gate's validity fails (review round 3);
  - its effect is exported as `d_res_clip0`.

## 7. The rare-event reflection

The rare-event reflection is `calibrate.RARE_REFLECTION`, "conjugate" (U' = 1 − T(1 − U)); the alternative reading is "literal" (1 − T(U)). The gate manifest records the choice. It is conjugate, per Amendment 1 (2026-11-04T16:23Z) of the approval record; per Codex's ruling, keeping conjugation needed that dated amendment.
