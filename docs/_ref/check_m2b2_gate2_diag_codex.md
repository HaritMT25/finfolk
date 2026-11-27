<!-- Codex gpt-6.1-sol high, read-only, codex_council/codex_queue.mjs lap1122b 2026-11-22T21:18:40.333Z: chkm2b2diag -->

**1. Summary**

The root cause is correct, and the compatibility envelope is a sound reconciliation of the two rounded capacity representations. The recovery-window correction is also correct.

I found no confirmed P1/P2 defect in the proposed production repair. I recommend two test improvements during round 2. Patched compilation, full kernel parity, performance, and the remaining gates are **unverified**.

I read files and independently evaluated the binary32 arithmetic; I did not edit, build, or execute project files.

**2. Change map**

- Move the existing division-based `fuelMass` into the coefficient header.
- Extend `evalLoad`’s mass domain to include both rounded endpoints, while retaining strict energy validation and the existing transaction publication order.
- Extend recovery observation to 2,000 substeps, retaining zero final fatigue and the 0.016 s timing tolerance.

**3. Findings by severity**

**P1/P2: none confirmed in the diagnosis or production repair.**

**P3 — Test the fuel conversion directly; total mass can hide the exact discrepancy being repaired.**  
Location: [fix_capacity.patch:102](C:/Users/harit/codex_council/snaps/m2b2diag/build_m2b1_pr2/diag/fix_capacity.patch:102).

**Fact:** The new assertion checks `L.mass == bc.leanMass + fuelMass(energy)`. Total-body rounding can swallow a wrong fuel mass. For the neutral body at the selected interior energy, 22.5 E:

| Quantity | Correct conversion | One fuel ULP too high |
|---|---:|---:|
| Fuel mass bits | `3d3851ec` | `3d3851ed` |
| Loaded total-mass bits | `3f8c1b38` | `3f8c1b38` |
| Fuel-volume bits | `41ee3a05` | `41ee3a06` |

Thus this assertion can pass an incorrect conversion.

There is also an unverified false-failure risk: the loader computes `(innerMass + fuelMass) + finMass`, whereas the assertion computes `(innerMass + finMass) + fuelMass`. Those are not generally binary32-identical. The production order is visible at [hydro_coefficients.hpp:642](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/hydro_coefficients.hpp:642) and :649. **VERIFY:** I have not established that this mismatch occurs in the proposed 137-body sample.

**Minimal change:** Compare `loadAt` against a direct `evalLoad` using the required fuel conversion, including `fuelVolume` and the complete loaded result. Add an independent bit assertion such as `fuelMass(5)` being `0x3c23d70a`, which distinguishes division from reciprocal multiplication. Preserve the loader’s existing addition order.

**P3 — The added atomicity case exercises early refusal only.**  
Location: [fix_capacity.patch:116](C:/Users/harit/codex_council/snaps/m2b2diag/build_m2b1_pr2/diag/fix_capacity.patch:116).

**Fact:** `invalid.energy=NAN` fails parcel validation before candidate-state construction. It therefore cannot detect premature publication during the subsequent momentum/load calculation. The actual publication fence remains correct at [ocean_energy.hpp:134](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/ocean_energy.hpp:134).

**Concrete additional case:** Start below capacity and supply a finite parcel with very large, perpendicular position and velocity components. Its orbital cross product overflows during candidate construction, causing final state validation to refuse.

**Minimal change:** Add that late-refusal case with nontrivial ledger, state, and receipt sentinels; require all three to remain unchanged. Keep the existing NaN case as an early-refusal check.

The remaining items are minor.

**4. Claims checked**

| Claim | Assessment |
|---|---|
| Capacity mismatch causes the full-credit refusal | **Confirmed**, independently recomputed from the source expressions. |
| Neutral `fuelMass(Ecap)` is `3db851ec`, while the old bound is `3db851eb` | **Confirmed.** |
| Reciprocal multiplication is not an equivalent replacement | **Confirmed:** at 5 E it gives `3c23d70b`, versus division’s `3c23d70a`. |
| Envelope includes every legal energy’s fuel mass | **Confirmed mathematically**, subject to the stated finite, nonnegative capacity preconditions. |
| Envelope preserves previously accepted compiled-load outputs | **Confirmed by source inspection:** the loaded-property arithmetic is unchanged. This is not a claim that newly accepted trajectories are byte-identical. |
| Discrepancy is at most one ULP for every legal body | **Not established.** The diagnosis correctly limits that observation to its sampled bodies. |
| Native and wasm arithmetic reproducer outputs match | **Confirmed for the supplied logs:** both have the reported SHA256 and matching 23 words. Execution provenance was not independently reproduced; the wasm executable is absent from this snapshot. |
| Both patches apply cleanly together | **Confirmed structurally:** all seven hunks have matching counts and exact source context, including their combined changes. Compilation remains unverified. |
| Recovery completes on substep 1,819 / 501 | **Confirmed by independent binary32 recurrence evaluation** for white / mixed fibre. |
| Increasing the horizon weakens the timing acceptance | **False:** the patch retains 0.016 s and adds completed recovery. The diagnosis correctly says otherwise. |
| These diagnostics advance a project gate | **No such claim is made.** The supplied gate-2 log still records two failed groups. |
| Gates 3–12, timing, memory, module freshness, and release identity are established | **Unverifiable here and explicitly unclaimed** by the diagnosis. |

The supporting reasoning is as follows.

**Root cause and numerical laws**

The brief defines the real-valued relations at [m2b1_brief_codex.md:149](C:/Users/harit/codex_council/snaps/m2b2diag/docs/_ref/m2b1_brief_codex.md:149). Production stores capacity using [hydro_coefficients.hpp:528](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/hydro_coefficients.hpp:528), then independently evaluates the mass bound at :624.

Applying binary32 rounding after each source operation gives:

```text
rhoWater             = 3adc145c
density              = 3ac61252
round(500*density)   = 3f416de4
Ecap                 = 42340000  = 45
round(Vreserve*density)
                     = 3db851eb
round(Ecap/500)       = 3db851ec
fuelVolume(Ecap)      = 426e3a05
reserveCapacity      = 426e3a04
```

The exact product of the stored density and reserve volume is approximately `0.08999999970152217`, below the midpoint `0.089999999850988388…`. The exact quotient `45/500 = 0.09` is above that midpoint. This verifies the diagnosis independently of its decimal displays.

The resulting transaction refusal is correct under the old incompatible domains: the candidate target fails refreshed-load validation, so nothing is published. The repair must reconcile the domains rather than change that failure behavior.

**Ranking and inclusion proof**

For finite nonnegative `C=Ecap`, correctly rounded division by positive 500 is monotone:

```text
0 ≤ E ≤ C
⇒ fuelMass(E) ≤ fuelMass(C)
⇒ fuelMass(E) ≤ max(oldMassBound, fuelMass(C)).
```

This proves inclusion for **every qualifying capacity**, including subnormal energy values; it does not depend on the 137 bodies or on a one-ULP discrepancy limit. It proves the mass-bound check cannot cause this particular refusal, not that every other load/state validation must succeed.

The envelope preserves the real-valued equations because its two endpoints coincide when rounding is removed. It deliberately changes the binary32 refusal domain. It neither clamps a supplied mass nor repairs a failed load. `target=clamp(E+delta,0,Ecap)` remains unchanged at [ocean_energy.hpp:108](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/ocean_energy.hpp:108), and publication remains after candidate validation.

The ranking is sound **if preserving the current Ecap representation and existing direct-mass callers is the chosen compatibility policy**. If reserve capacity must remain an absolute rounded mass ceiling, option (b) is preferable.

The suggested “define capacity once in mass space at birth” alternative is already option (b). It needs an explicit safe energy-endpoint conversion; `round(500*Mcap)` alone is insufficient. The supplied counterexample independently evaluates as:

```text
Mcap                         = 3db80015
round(500*Mcap)              = 4233b015
round(round(500*Mcap)/500)    = 3db80016
```

There is no exact choice preserving all three incompatible requirements: the existing Ecap bits, the existing strict mass ceiling, and the existing division.

**Downstream consequences**

The slight volume overrun has no identified structural failure in the current kernel. Fuel volume feeds inflation, displaced volume, geometry, and the neutral-gas calculation; those paths do not subtract it from remaining reserve capacity or reject `fuelVolume > reserveCapacity`. See [hydro_coefficients.hpp:628](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/hydro_coefficients.hpp:628), :661, and [hydro_step.hpp:139](C:/Users/harit/codex_council/snaps/m2b2diag/src/ocean/hydro_step.hpp:139).

That supports accepting the envelope; it does **not** establish universal “harmlessness”:

- Newly accepted loads can produce different buoyancy, geometry, and loaded-result digests. That is the intended consequence of accepting their exact ledger-derived mass.
- Coefficient fields, Ecap, layouts, and hashing traversal are unchanged by this patch.
- Production offspring allocation and enabled checkpoint integration are deferred work. Their universal compatibility cannot be certified from these internal kernels.
- The new arithmetic/comparison is deterministic in construction, but full native/wasm evidence remains required.

**Recovery bound**

From the brief’s fibre law:

```text
T(f) = 8(1−f)/(.55+.90f)
```

This decreases over `[0,1]`, so white fibre supplies the maximum continuous recovery time:

```text
T(0) = 160/11 s
T(0)/.008 = 20000/11 ≈ 1818.1818 substeps.
```

My binary32 recurrence evaluation reproduced 35.178985595703125 fatigue after 1,818 steps and zero after 1,819; mixed fibre completed after 501.

The 2,000-step horizon is a sensible margin, not a uniquely derived minimum. The strict timing assertion still rejects a 1% white-fibre slowdown, approximately 0.147 s. Stalled recovery also fails the new `fatigue==0` requirement. Shared errors in coefficients and expected time still require the independent law/assay checks, as the diagnosis acknowledges.

**Remaining round-2 risks**

The remaining gate list accurately describes substantial unfinished implementation, especially the independent reference, assay driver, frozen calibration stages, mechanics fixture, and timing/memory tooling—not merely commands waiting to run ([diagnosis:220](C:/Users/harit/codex_council/snaps/m2b2diag/docs/m2b2_gate2_diag.md:220)).

At scale, do not infer the +448 ns/fish-step allowance from this small patch: the bound adds work to repeated load evaluation. Likewise, 1,260 B of element payload does not prove the 1,404 B resident ceiling. Preserve the paired/A/A timing requirements and capacity/peak-memory measurements.

The boundary/full-credit checks meaningfully fail the current mismatch. Original physical endpoints, zero/interior loads, and existing conservation cases are primarily compatibility checks. The two proposed test improvements address the main remaining assumptions: exact conversion hidden by total-mass rounding, and atomicity beyond preflight refusal.

**5. VERDICT: AUTHORIZE WITH CHANGES**

Authorize the compatibility envelope and the recovery correction, with these additions during round 2:

1. Replace the regrouped total-mass conversion oracle with direct loaded-result comparison and an independent division bit check.
2. Add a late-failure atomicity test.

Retain the diagnosis’s gate order and evidence requirements. This authorizes implementation and validation; it does not establish merge readiness.
