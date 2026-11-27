<!-- Codex gpt-6.1-sol high, read-only, codex_council/codex_queue.mjs lap1123b 2026-11-23T09:18:24.770Z: chkm2d2 -->

1. **Summary**

The six classifications are supported: the three righting failures and two depth failures are **(a), authorized calibration**; the friction failure is **(c), a specification/model problem**, including a real limitation of the prescribed contact solver.

The friction limitation is not an implementation departure: `hydro_contact.hpp` implements the plan’s local static/dynamic iteration. Moving the load changes the tested wrench and avoids the demonstrated failing case; it does **not** repair or validate aggregate static-friction behavior generally.

The recorded evidence supports the conditional **33/33**, calibration-only **32/33**, and focused gates 2–3 results. Raw trace equality cannot be independently rechecked from this snapshot because the traces are omitted.

I found no P1/P2 against the diagnosis. Two minor corrections follow.

2. **Change map**

- Patches 1–2 change three calibration constants: metacentric fraction, vertical feedback gain, and regulator time constant.
- Patch 3 adds an external torque to the friction assay, moving its sampled force application point from COM to COM’s projection onto the floor.
- Production mechanics, contact, tests, and independent reference sources remain unchanged in the candidate.
- Scratch results remain at `kFrozenThrough=0`; they are neither frozen calibration nor completed gate-4 evidence.

3. **Findings by severity**

**P1/P2: none established against this diagnosis.**

**P3 — An inside-hull cap would exclude this candidate; it does not prove that changing the law or acceptance is necessary.**

At [docs/m2b2_gate4_diag.md:25](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/m2b2_gate4_diag.md:25), the report says an owner-imposed geometric cap would require “a different law/acceptance solution.” The experiments establish that fraction 1 rebounds above the righting limit, not that every permitted calibration respecting such a cap is impossible.

Concrete consequence: an owner requesting that cap could be presented with an unnecessarily narrow choice between changing mechanics and weakening acceptance.

Minimal correction: say the cap would exclude the tested candidate and require **further authorized calibration, or a separately approved law/acceptance change**. Do not claim impossibility from the fraction-1 experiment.

**P3 — Patch 3 implements a sampled floor-plane wrench, rather than continuously maintaining floor-plane application.**

The candidate computes force and lever at [candidate/tools/ocean_hydro_assay.cpp:120](C:/Users/harit/codex_council/snaps/m2b2diag2/build_m2b1_pr2/diag2/audit_20261123/candidate/tools/ocean_hydro_assay.cpp:120). The callback is evaluated once per outer step at [tools/ocean_hydro_assay.cpp:44](C:/Users/harit/codex_council/snaps/m2b2diag2/tools/ocean_hydro_assay.cpp:44), and that body-frame wrench is reused across the mechanical substeps.

For a rotating body, its second-substep world force/application point therefore need not remain exactly tangential/in the floor plane. This does not invalidate the recorded result, but “floor-plane load” should specify that sampling convention.

Minimal correction: document the outer-step sampling and holding explicitly. If continuous world-frame application is intended, implement and validate a substep callback before claiming that stimulus.

The remaining items are minor.

**VERIFY — Evidence limits**

- Raw native/Wasm trace bytes and their reported SHA256 cannot be independently compared here.
- The command journal records individual elapsed times, but no start/end timestamps or process timeline. It cannot independently prove the maximum number of simultaneous compiler processes.
- Original-server Git history and every server operation are unavailable; “nothing committed,” “no network,” and comprehensive absence of other activity remain recorded claims rather than independently reconstructed facts.

These limitations are not evidence that the claims are false.

4. **Independent classification and arithmetic checks**

| Failure | Classification | Independent assessment |
|---|---|---|
| Roll, 1.021° | **(a)** | Restoring sign, loaded-half-depth lever, and implicit stiffness match the prescribed law. Insufficient settling at the starting constant is supported. |
| Pitch, 5.002° | **(a)** | Uses the pitch rotation and larger effective inertia. The weaker normalized damping and endpoint phase explain the larger residual. |
| Combined, 4.409° | **(a)** | Applies the combined release to the same law; no separate missing restoring term was found. |
| Target 96, error 25.77 u | **(a)** | Target scaling and feedback signs match the plan. Starting gains produce local instability. |
| Target 144, error 22.33 u | **(a)** | Same unstable regulator; capacity/rate saturation is not the demonstrated cause. |
| Subthreshold floor load, 9.03 u/s | **(c)** | COM-load moment feasibility and the prescribed solver’s local kinetic fallback are separate specification-level problems. |

The implementation locations are [hydro_step.hpp:136](C:/Users/harit/codex_council/snaps/m2b2diag2/src/ocean/hydro_step.hpp:136), [hydro_step.hpp:189](C:/Users/harit/codex_council/snaps/m2b2diag2/src/ocean/hydro_step.hpp:189), and [hydro_contact.hpp:139](C:/Users/harit/codex_council/snaps/m2b2diag2/src/ocean/hydro_contact.hpp:139).

**Why friction remains category (c)**

FACT: the plan expressly requires four sweeps, zero initial accumulated impulses, acceptance within the local static disk, and otherwise projection onto the smaller dynamic disk. See [plan:890](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_pr2_plan_codex.md:890) and [plan:906](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_pr2_plan_codex.md:906). The implementation follows those instructions, including accumulated tangent increments, vector friction bounds, and effective-mass torque response.

The supplied contact values independently give:

- \(N=14.266634\), \(F=0.72N=10.271976\).
- COM-load required normal COP: **4.441811 u**, outside the current support interval **[−1.658823, 2.777574]**.
- Floor-plane-load required COP: **1.816713 u**, inside that interval.
- A proportional tangential distribution needs \(|T_i|/N_i=0.72<0.8\).

Thus the COM case lacks an initial static moment balance at that pose. Separately, the floor-plane case has the demonstrated aggregate static balance, yet the local solver selects dynamic friction. The probe records all three points at approximately \(0.6J_n\), delivering about **0.0673274** tangential impulse against **0.0821758** required. See [contact_both_loads.log:14](C:/Users/harit/codex_council/snaps/m2b2diag2/build_m2b1_pr2/diag2/audit_20261123/contact_both_loads.log:14).

That is a real solver limitation, not merely a tipping explanation. However, correcting it would change an explicitly prescribed algorithm. Under the requested distinction, that makes it **(c), not a demonstrated (b) implementation bug**.

The counterfactual controls strengthen that conclusion: floor-plane loading still slides at **9.743128 u/s**, and 64 sweeps still slide at **9.746955 u/s** at bootstrap calibration. See `audit_20261123/plane_only_assay.log:32` and `plane64_assay.log:32`.

The passing calibrated floor-plane case uses the same contact implementation. It therefore exercises the same local law on a different wrench and settled support configuration. It does **not** show that the previously failing feasible-static case has been repaired. The diagnosis correctly acknowledges this at [docs/m2b2_gate4_diag.md:173](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/m2b2_gate4_diag.md:173).

**Calibration authority**

The supplied documents authorize these numeric changes:

- The brief calls numerical values starting constants, except its named anchors: [brief:3](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_brief_codex.md:3).
- Assay 1 explicitly freezes “metacentric offset and regulator gains”: [brief:660](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_brief_codex.md:660).
- The plan assigns righting and regulator calibration to assay 1 and permits changes before freeze: [plan:1066](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_pr2_plan_codex.md:1066).

Neither document supplies an upper bound of 1 for the metacentric fraction. The declared model remains:

\[
\delta=f\,\text{loadedHalfDepth},\qquad
K=g\rho V\delta.
\]

Changing \(f\) from .12 to 2 preserves that model. It does not relocate a geometrically calculated COB. The change is substantial—**16⅔ times the starting stiffness**, with an **8.072791 u** neutral lever—but the supplied text does not make it an additional owner-approval item.

Likewise, changing vertical gain to .2 and tau to 2 s preserves the declared regulator equation. Tau is a regulator constant covered by the plan’s broader assignment, even though the brief’s table abbreviates the category as “gains.”

**Arithmetic**

I independently recalculated the reported scalar approximations:

| Quantity | Roll | Pitch |
|---|---:|---:|
| Effective inertia | 15.613873 | 60.042976 |
| Natural frequency, rad/s | 3.693820 | 1.883649 |
| Period, s | 1.700999 | 3.335646 |
| Quadratic damping coefficient β | 19.888827 | 33.705456 |
| Peak-speed equivalent damping ratio | .111159 | .048988 |
| Small-step numerical attenuation, 1/s | .054577 | .014193 |

The inertia ratio is **3.845489**. These are consistent with [hydro_coefficients.hpp:765](C:/Users/harit/codex_council/snaps/m2b2diag2/src/ocean/hydro_coefficients.hpp:765). The damping ratios are amplitude-dependent approximations, not fixed linear damping ratios; the report correctly labels them.

The regulator polynomial also checks:

\[
s^3+\frac{s^2}{\tau}
+\left(\frac{B k_v}{82\tau}-C\right)s
+\frac{B k_d}{240\tau}=0,
\]

with \(B=165.430476\), \(C=.0245848333\).

- Starting constants: coefficients **[1, .2, −.016515054, .0110286984]**, poles approximately **−.3423435, +.0711717 ± .1647722i**.
- Candidate: **[1, .5, .177159650, .0275717460]**, poles approximately **−.2402675, −.12986625 ± .31287238i**.

The stated Routh boundary is correct. At tau 2 s, the required vertical gain is approximately **.081747, .079039, .076823** at pressures **1.8, 2, 2.2**; .2 exceeds all three.

The fresh extended logs independently reproduce the reported late depth ranges and candidate final depths. The report’s `analysis.json` is not itself a fresh-run provenance proof: its analysis script reads older `diag2` extended logs at `analyze_audit.py:38`. Here, the fresh audit logs agree with those values.

5. **Claims checked**

In this table, `A/` means `build_m2b1_pr2/diag2/audit_20261123/`.

| Claim | Status | Evidence and limits |
|---|---|---|
| Three patches make only the reported changes | **Confirmed** | Compared 303 candidate source/test/tool/wasm files: only `hydro_calibration.hpp` and `ocean_hydro_assay.cpp` differ. Patch contents match those changes. |
| Exact constants and stage 0 | **Confirmed** | `A/candidate.manifest.json:2` records the proposed float bits, `frozen_through:0`, and zero measured-power bits. |
| Zero-fuzz patch application produced candidate bytes | **Supported** | `A/commands.jsonl:32` records the application/comparison command and exit 0; `A/patch_apply_check.log:4` records byte equality. I did not apply patches. |
| Candidate native and Wasm each pass 33/33 | **Confirmed from retained evidence** | Both result sets contain 33 passes; logs are byte-identical. Commands exit 0 at `A/commands.jsonl:3` and `:25`. |
| Calibration alone passes 32/33 | **Confirmed** | `A/calibration_only_assay.log:32` retains the sole failing speed, 9.2599535; raw exit 1 is recorded at `commands.jsonl:31`. |
| Gates 2–3 pass | **Confirmed from retained evidence** | Optimized and UBSan logs match byte-for-byte; 11 and 12 groups pass. Reference log ends PASS, with the reported 11,508 increments, 5,754 actuator checks, residuals and nine completed trajectories at `A/candidate_reference.log:61`. |
| Initial test-build failure was a missing copied wasm source | **Confirmed** | `A/build_candidate_tests.log:1` names the missing include; retry succeeds at `commands.jsonl:7`. |
| All 27 previously passing named checks still pass | **Confirmed** | Compared original and candidate manifests. This is predicate compatibility, not unchanged trajectories or unchanged friction stimulus. |
| Native/Wasm manifests differ only in target; 12 chains match | **Confirmed** | Independently compared both retained manifests. |
| Raw CSV traces are byte-identical with the reported SHA256 | **Unverifiable directly here** | Recorded in `A/native_wasm_verified.json:8`; raw traces are omitted. Matching logs/manifests support, but do not independently reproduce, that comparison. |
| Pre-existing files preserved | **Confirmed for available inventory entries** | Rehashed **2,248** available files: zero mismatches. **242** inventory entries are absent from the snapshot. `A/preservation_verified.json:2` records the original 2,490-file check. |
| Earlier base copies match current sources | **Confirmed** | Compared 292 files under `diag2/base/{src,tests,tools}`: no differences. |
| nice/thread/compiler flags followed | **Confirmed for recorded invocations** | `A/run.py:4` sets nice 19; `:5` sets OMP=2, OpenBLAS=1 and EMCC=1. Recorded C++ builds use `-ffp-contract=off`, with no fast-math or OpenMP flags. |
| No commit/network/browser or excessive concurrent builds | **Partly unverifiable** | No such operation appears in the journal, but it is not a complete process/session audit. |
| Full gate 4, frozen fixtures, full parity, performance or memory acceptance established | **Not claimed; not established** | The report correctly leaves these outstanding. |

No material result claim was contradicted by the retained logs.

The tests have appropriate but limited reach. The six assay predicates expose the original failures. The extended righting probes counter lucky endpoint selection. Gates 2–3 provide compatibility and independent mechanics checks; the contact unit tests at [tests/ocean_hydro_step_tests.hpp:340](C:/Users/harit/codex_council/snaps/m2b2diag2/tests/ocean_hydro_step_tests.hpp:340) check sweep count, impulse closure, disk bounds and dynamic friction, but **cannot establish that aggregate feasible static solutions are found**. The diagnostic probes print evidence rather than asserting that stronger property.

6. **Exact OWNER DECISION questions**

The coordinator should ask:

> **For assay 1’s floor hold/slip checks, should the horizontal force act at COM height or at COM’s projection onto the floor?** The calibrated floor-plane candidate passes all 33 checks; the calibrated COM-height candidate still slides at about 9.26 u/s. Choosing the floor plane removes the overturning couple from this acceptance test. It does not make the COM-height case pass.

And explicitly include:

> **May we retain the prescribed four-sweep local contact solver with its demonstrated limitation that it can slide even when an aggregate static balance is feasible, or must we redesign it before freezing assay 1?** Retaining it allows the tested candidate to proceed under the narrower acceptance definition. Requiring aggregate static sticking needs an approved contact-algorithm change, independent contact tests, and renewed validation; the three proposed patches do not provide that repair.

No separate permission question for the three numeric calibrations is required by the supplied plan/brief. Disclose their magnitude and behavioral effect; do not invent a geometric cap.

7. **Ordered round-3 builder plan**

1. **Record the owner’s answers and preserve round-2 evidence.** Recheck gate 1, base identity and frozen scope. If the solver must change, stop this three-patch route and obtain the contact design first.

2. **Implement candidate-header emission before the calibrated build.** Use exact hexadecimal floats or integer bit literals as required by [plan:236](C:/Users/harit/codex_council/snaps/m2b2diag2/docs/_ref/m2b1_pr2_plan_codex.md:236). Emit the patch-1/2 values with `kFrozenThrough=0`; verify generated bytes/bits. Patch 2 depends on patch 1’s context. Apply patch 3 only if its stimulus is approved, documenting the sampling convention.

3. **Rerun gates 2 and 3 against the actual worktree:** optimized focused suites, separate UBSan suites, and the independent reference at the unchanged tolerances. Preserve commands, raw exits and outputs. Scratch candidate results do not replace these runs.

4. **Run and freeze assay 1 properly.** Require every approved subcase to pass. Retain the COM-load and feasible-static counterexamples as diagnostics. Only after success emit stage 1, rebuild and rerun assay 1. Do not relabel the existing stage-0 manifest as frozen evidence.

5. **Complete assays 2→3→4 in order.** Emit each candidate, rebuild, and rerun all preceding assays after tuning. Freeze only that stage’s assigned constants. At stage 2, install measured 82/108 power bits and validate the reference-law transition without lowering force capacity. Finish with generated `kFrozenThrough=4` and genuine `--check-all`; the current driver explicitly lacks that implementation at `tools/ocean_hydro_assay.cpp:196`.

6. **Run gates 5–6:** complete deterministic fixture modes and native/Wasm comparisons before installing new fixtures, then compare installed fixtures; run full Ocean parity, guards, suites and expanded twins. Use only the plan’s explicitly permitted, fully evidenced exception, if applicable.

7. **Run gates 7–11:** sequential native/Wasm component timing and actual allocated-memory measurements with A/A control; Ocean and Classic rebuild/freshness; native-serial repository checks; module consumers and available local TypeScript. Keep offline operation, nice 19 and bounded concurrency. A payload-size printout does not prove the 1,404 B/fish resident ceiling.

8. **Run gate 12 and report remaining obligations.** Audit against the fixed PR-1 base, record module hashes and generated calibration/fixture identities, and preserve all raw failures. Do not alter historical baselines, Classic pins, RNG order, `src/core`, public world/configuration/checkpoint/fingerprint/rendering paths, geometry normalization, or acceptance thresholds. Do not commit, merge, deploy or rebaseline without authorization.

The most likely continuing failure is morphology/support-dependent sliding caused by local kinetic-branch selection. The three patches add no resident state or production loop work, but one-fish assay success supplies no 2,000-fish performance or broad contact-correctness proof.

**VERDICT: SOUND WITH CORRECTIONS.** The classifications, arithmetic and conditional candidate results are supported. Correct the two minor statements above and make acceptance of the known solver limitation explicit before round 3.
