**M2b2 gate-2 diagnosis — diagnosis only; proposed patches are unapplied**

Recommendation: adopt option (a) with a compatibility envelope: move the existing, exact `fuelMass(E)` division into the shared coefficient header and make the admissible mass endpoint `max(Vreserve*(.90f*rhoWater()), fuelMass(Ecap))`. This guarantees that every legal energy ledger maps inside the mass domain while retaining PR 1's existing physical-mass endpoint. Correct the recovery test's observation window to 2,000 substeps (16 s), retaining its 0.016 s timing tolerance and requiring zero final fatigue.

This is an explicit clarification of the **binary32 acceptance domain**, requiring coordinator authorization for round 2. It preserves the brief's real-valued formulas and the current energy capacity, but extends the strict PR 1 mass endpoint where the two rounded representations disagree. It must not be described as preserving the old refusal contract bit for bit. If the owner requires that old mass endpoint to remain an absolute ceiling, choose option (b), accepting a change to the represented energy capacity instead.

The inspected worktree is `/home/harit/finfolk/work/trees/m2b1-pr2`, HEAD `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`. Existing implementation, tests, report, logs, fixtures and modules were left unchanged. All new evidence is under `build_m2b1_pr2/diag/`; this is the only new document. No patch was applied, gate retried, baseline regenerated, module rebuilt, dependency fetched or network used. The forbidden trees, noise bank and running study were not accessed. Diagnostic builds/runs used nice 19; builds were sequential, and wasm linking was limited to one thread.

**The failure is two separately rounded representations of the same capacity.**

The authoritative text is:

- `docs/_ref/m2b1_brief_codex.md:149`: `Mfuel = max(E,0) / 500`.
- Brief line 150: `Vfuel = Mfuel / (.90 ρw)`.
- Brief line 151: `Ecap  = 500 · .90 ρw · Vreserve`.
- Brief line 156: “Keep physical capacity proportional to compartment volume; do not Kleiber-scale it.”
- `docs/_ref/m2b1_pr2_plan_codex.md:275`: `return energy > 0.0f ? energy / 500.0f : 0.0f;` at line 276.
- Plan line 295: “require `0≤E≤energyCapacity`”; line 300: “Call fixed PR 1 `evalLoad(c,Vgas,fuelMass(E),L)`.”
- Plan line 301: “Never silently repair a failed load or fall back to legacy motion.”
- Plan line 407: `target=clamp(E+requestedDelta,0,Ecap)`; line 409: `dm=fuelMass(target)-fuelMass(E)`.
- Plan line 436: “Commit atomically. On failure, leave ledger, physical state, and receipt unchanged.”

The brief gives a real-valued product, without binary32 parentheses; the plan fixes the division in the ledger conversion and calls the existing capped PR 1 loader. Neither text supplies a rule reconciling differently rounded endpoint representations. The plan's interface table, line 79, calls `evalLoad` a “Capped admissible load” with “cleared refusal.” The exact mass-space bound is in the inherited implementation/comment, not an additional independently parenthesized formula in the brief.

Exact source trace, using the **untouched working files' line numbers**:

| Quantity or operation | Working-tree source | Exact expression |
|---|---|---|
| Reference hull volume | `src/ocean/body_plan.hpp:690` | Cached `detail::hullVolumeOf(appearance::neutral(),1.0f,1.0f)` at line 691 |
| Water density | `src/ocean/hydro_coefficients.hpp:131` | Cached `1.0f / bodyplan::referenceVolume()` at line 132 |
| Lipid density ratio | `src/ocean/body_material.hpp:69` | `kRhoLipid = 0.90f` |
| Compartment volume | `src/ocean/body_plan.hpp:727` | `fatTrait = 0.20f * P.g[kFat] * V` at line 728; optional storage scaling at 730–734; `reserve = 0.02f * V + fatTrait` at 736 |
| Stored reserve volume | `src/ocean/hydro_coefficients.hpp:527` | `c.reserveCapacity = m[at(fReserveCapacity)]` |
| Stored energy capacity | `src/ocean/hydro_coefficients.hpp:528` | `(500.0f * (bodymat::kRhoLipid * rw)) * c.reserveCapacity` |
| Ledger-to-mass conversion | `src/ocean/ocean_energy.hpp:24` | `energy > 0 ? energy / 500.0f : 0.0f` |
| Existing mass acceptance bound | `src/ocean/hydro_coefficients.hpp:624` | `c.reserveCapacity * (bodymat::kRhoLipid * rw)` |
| Strict comparison | `src/ocean/hydro_coefficients.hpp:625` | Refuse unless `fuelMass <= maxFuel` at line 626 |
| Loaded fuel volume | `src/ocean/hydro_coefficients.hpp:628` | `fuelMass / (bodymat::kRhoLipid * rw)` |
| Legal ledger / actual load call | `src/ocean/ocean_energy.hpp:45` | Energy must be in `[0,c.energyCapacity]`; line 51 passes `fuelMass(energy)` to `evalLoad` |
| Credit target and final validation | `src/ocean/ocean_energy.hpp:108` | `std::clamp(sum,0.0f,c.energyCapacity)`; lines 134–136 validate the candidate load before publication |

The capacity and loader formulas are inherited from fixed PR 1; the current uncommitted coefficient diff does not change them. See `build_m2b1_pr2/diag/existing_coefficients.diff`. The new ledger path exposes their incompatibility. This is separate from the five prerequisite fixes already audited.

For positive energy, write `fl(x)` for binary32 round-to-nearest, ties-to-even:

```text
rw      = fl(1 / Vref)
density = fl(0.90f * rw)
Ecap    = fl(fl(500.0f * density) * Vreserve)
Mledger = fl(Ecap / 500.0f)
Mbound  = fl(Vreserve * density)
```

All operands and stored intermediates in these production expressions are `float`; there is no implicit double promotion. The integer literals in the conditional `energy > 0` do not promote the float division. `-ffp-contract=off` excludes contraction; there is no multiply-add in these particular expressions anyway. The discrepancy remains without FMA and without fast math: a multiply, multiply, then divide cannot undo the intermediate rounding and reproduce the directly rounded mass product.

The native probe records these exact binary32 values:

| Intermediate | Value (decimal display) | Bits |
|---|---:|---|
| `Vref` | 595.5665283203125 | `4414e442` |
| `rw` | 0.001679073553532362 | `3adc145c` |
| `.90f` | 0.89999997615814209 | `3f666666` |
| `Vreserve` | 59.5566558837890625 | `426e3a04` |
| `density` | 0.0015111661050468683 | `3ac61252` |
| `fl(500*density)` | 0.7555830478668212890625 | `3f416de4` |
| `Ecap` | 45 | `42340000` |
| `Mbound` | 0.0899999961256980896 | `3db851eb` |
| `Mledger` | 0.0900000035762786865 | `3db851ec` |
| `Vfuel` at `Ecap` | 59.556659698486328125 | `426e3a05` |

The rounding split can be located exactly, rather than inferred from decimal printouts. `build_m2b1_pr2/diag/rounding_exact.log` uses exact rational representations of the float inputs:

```text
exact density * Vreserve = 0.089999999701522170880707562901079654693603515625
midpoint of eb and ec     = 0.0899999998509883880615234375
exact 45 / 500            = 0.09
one mass ULP             = 0.000000007450580596923828125
```

The direct physical product is **below** the midpoint by `1.49466217180815874598920345306396484375e-10`, so it rounds to `eb`. The exact energy quotient is **above** the midpoint by `1.490116119384765625e-10`, so it rounds to `ec`.

Along the energy route, exact `500*density` is `0.755583052523434162139892578125`; it first rounds down to `0.7555830478668212890625`. That stored result times `Vreserve` is exactly `44.99999957342879497446119785308837890625`, which rounds to 45 (the midpoint below 45 is `44.9999980926513671875`). The final division then rounds to `ec`. The two mass values straddle the midpoint even though both express the same algebraic real-valued law.

`kFuelPerEnergy` at `hydro_coefficients.hpp:123` is a separately rounded reciprocal, `1.0f/500.0f = 0x3b03126f`. It is **not used** by the current `fuelMass`. Using `Ecap*kFuelPerEnergy` also gives `ec`, so switching division to reciprocal multiplication does not solve the failure. It can change other values: at 5 E, division gives `0x3c23d70a`, multiplication gives `0x3c23d70b`. The reference-load expression at `hydro_coefficients.hpp:784` does use reciprocal multiplication; at its actual 25 E argument both routes happen to give `0x3d4ccccd`. This diagnosis proposes no unrelated reference-load change.

Introducing double intermediates is also a numerical-law change, not a principled repair: keeping the already rounded `density` but computing its energy product in double then casting still gives 45; using double `.90` and double products with the stored `rw` gives `0x42340001` instead. Neither establishes a shared endpoint contract.

The transaction's refusal is correct under the current incompatible domains: a 25 E ledger with +100 E requests target 45 E, accepted 20 E and waste 80 E in its **local** receipt; the refreshed load fails, so none is published. The actual diagnostic result is `false`, ledger still 25 E, state and caller receipt unchanged. In the suite itself, the preceding off-centre credit has taken the ledger from 20 to 30 E, so the overflow request at `tests/ocean_hydro_step_tests.hpp:172` would instead accept 15 E and waste 85 E if successful; it fails at the same capacity boundary. The diagnostic confirms the refusal; the existing raw suite log remains `build_m2b1_pr2/logs/gate02_native_hydro_step.log`.

**Reproducer and measured scope.**

`build_m2b1_pr2/diag/capacity_repro.cpp` is a tiny, standalone C++20 arithmetic reproducer. It receives the two measured volume bit patterns as runtime arguments to its exported `sample` function. It includes no repository headers. Native GCC 15.2.0 and the installed emsdk's Clang 24.0.0git targeting wasm32 produced identical **23 result words**, compared byte for byte. The wasm executable is freestanding, run through Node v26.13.0 using `capacity_repro.mjs`; it does not require an Emscripten cache or runtime library.

Commands actually used (from the worktree root; all builds/runs exit 0):

```bash
TMPDIR="$PWD/build_m2b1_pr2/diag" nice -n 19 g++ \
  -O3 -std=c++20 -ffp-contract=off \
  build_m2b1_pr2/diag/capacity_repro.cpp \
  -o build_m2b1_pr2/diag/capacity_repro.native

TMPDIR="$PWD/build_m2b1_pr2/diag" nice -n 19 \
  /home/harit/opt/emsdk/upstream/bin/clang++ --target=wasm32 \
  -O3 -std=c++20 -ffp-contract=off -nostdlib \
  -Wl,--no-entry -Wl,--export=sample -Wl,--threads=1 \
  build_m2b1_pr2/diag/capacity_repro.cpp \
  -o build_m2b1_pr2/diag/capacity_repro.wasm

nice -n 19 build_m2b1_pr2/diag/capacity_repro.native \
  > build_m2b1_pr2/diag/capacity_repro.native.log
nice -n 19 node build_m2b1_pr2/diag/capacity_repro.mjs \
  > build_m2b1_pr2/diag/capacity_repro.wasm.log
cmp build_m2b1_pr2/diag/capacity_repro.native.log \
    build_m2b1_pr2/diag/capacity_repro.wasm.log
```

`repo_probe.cpp` separately includes and exercises the actual untouched headers, including the transaction and fatigue limiter. Its build was `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools build_m2b1_pr2/diag/repo_probe.cpp -o build_m2b1_pr2/diag/repo_probe`; its nice-19 run exits 0 and is saved as `repo_probe.native.log`.

The probe sweeps **137 bodies from `tools/ocean_hydro_bodies.hpp`**, including its 40 deterministic random founders. This is that tool's body set, not the original report's separate 117-body unit-test chain or its 85 successfully initialized step bodies:

| Relation of `fuelMass(Ecap)` to old `Mbound` | Bodies |
|---|---:|
| Lower by one ULP | 6 |
| Equal | 45 |
| Higher by one ULP (full ledger refused) | 86 |

The six lower cases are `morph8=0`, `random9`, `random17`, `random22`, `random27`, `phys_fatCapacity=0`. This is why replacing the bound by the energy image alone is not entirely compatible with PR 1's direct full-mass callers. One ULP is the measured maximum for this set, **not a proof over every legal genome/size**. These diagnostics are neither a full focused suite nor native/wasm kernel parity, and advance no gate.

**Fix options, ranked.**

Every option must be assessed against the quoted energy/mass laws, the fixed target operation, the loader's refusal rule, and the atomic publication rule. Native/wasm determinism and identity with the old numerical behavior are separate questions: a deliberate rule can be deterministic while changing accepted states.

1. **(a), recommended compatibility variant: use the same `fuelMass` function, retain the physical endpoint, accept their outward envelope.** Define `MboundNew=max(Mbound,fuelMass(Ecap))`. Move the exact existing division into `hydro_coefficients.hpp` so the loader and ledger share it without reversing the include dependency. Keep the existing capacity expression, all loaded-property expressions, and all receipt/momentum formulas.

   For finite nonnegative compiled capacities, binary32 division is monotone: `0<=E<=Ecap` implies `fuelMass(E)<=fuelMass(Ecap)<=MboundNew`. Thus the fuel-bound check cannot reject a legal ledger solely because of this mismatch. Taking the maximum also retains all previously accepted mass-space endpoints. It adds no arbitrary ULP and makes no assumption about the size of the discrepancy.

   **Law:** real-valued formulas, physical scaling and `target=clamp(...,0,Ecap)` are preserved. The old strict rounded mass boundary is intentionally extended where the ledger representation is larger. For the neutral body this permits one extra mass ULP and produces a fuel volume one volume ULP above the separately stored `reserveCapacity`. That numerical completion must be approved explicitly. The patch documents it; it does not clamp a failed load. The energy check in `loadAt` stays strict, even where the physical endpoint exceeds the energy-derived endpoint.

   **Non-capacity values:** every previously valid compiled load keeps exactly the same arithmetic and outputs. Previously refused near-capacity legal ledger values can become accepted. Values above the new mass endpoint are still refused; a ledger above `Ecap` remains illegal. The patch also explicitly refuses negative/nonfinite reserve or energy capacities before taking `max`, so NaN/negative inputs cannot be hidden by a comparison or `fuelMass`'s conditional.

   **Determinism:** the helper uses the original float division; the envelope uses deterministic finite float arithmetic/comparison. No RNG, state layout, solver, calibration constant or reciprocal is changed. Keep `-ffp-contract=off`, no fast math/reassociation, and prove native/wasm outputs in round 2. Existing accepted loaded-property outputs should remain identical; newly accepted trajectories may now initialize/run where they formerly refused.

   **Atomicity:** unchanged candidate-validation/publication order; no early write or clamp. **Tests:** both capacity representations, first mass above their maximum refused and cleared, zero/interior/adjacent/full energy, first energy above cap refused, full credit/waste and debit, illegal-credit atomicity, all tool bodies, current refusal/conservation suites, UBSan, native/wasm chains and full parity. Both existing correct overflow and out-of-domain tests remain meaningful; the latter's expected boundary must explicitly follow the approved new domain.

2. **(a), strict version: set `MboundNew=fuelMass(c.energyCapacity)` only.** This is the smallest exact shared-endpoint definition, with the same monotonic inclusion proof. **Law:** preserves all energy expressions and the real-valued equations, but both raises and lowers the old rounded mass acceptance endpoint. **Non-capacity values:** overlapping accepted loads are unchanged; six measured full physical-mass endpoints become illegal, so direct mass-space fixture/reference/test callers must be audited and deliberately adapted. Simply making this one replacement is not a complete compatible patch for the current tree. **Determinism:** the shared float conversion is native/wasm-compatible under the same flags; changed domains/fixtures need proof. **Atomicity:** preserved by retaining strict refusal and local publication. **Tests:** all of option 1, but test the new energy-derived domain and audit all old physical-fraction endpoints, isotropic checks, independent reference and fixture generation. Rank below the envelope because retaining PR 1's useful direct mass endpoint avoids unnecessary caller changes.

3. **(b): make fuel-mass capacity authoritative; derive admissible energy from it.** Keep `Mcap=fl(Vreserve*density)` and the original `evalLoad` bound. Compute the greatest finite binary32 energy whose **existing division** satisfies `fuelMass(E)<=Mcap`; the sole resident ledger remains energy. A birth-time conversion/search can establish this without adding another ledger or hot-path clamp. Merely writing `Ecap=500.0f*Mcap` is not a general round-trip guarantee.

   **Law:** algebraically equivalent to the brief's `Ecap=500·.90ρw·Vreserve`, but changes its current binary32 evaluation and the represented energy ceiling. For neutral `500.0f*Mcap` is `44.999996185302734` (`4233ffff`), whose mass is `3db851ea`, below `Mcap=3db851eb`. The next energy, 45, is illegal under the original mass ceiling. Thus the neutral legal energy capacity drops one energy ULP; storing the raw mass ceiling does not make every mass value exactly representable by an energy ledger. Across the 137 bodies the naive fuel-first roundtrip is lower in 76 and equal in 61; elsewhere it can overshoot. The standalone native/wasm reproducer includes `Mcap=3db80015`, `fl(500*Mcap)=4233b015`, whose division returns `3db80016` (one mass ULP too high).

   **Non-capacity values:** `fuelMass(E)` and load arithmetic at unchanged E stay identical, but credits/debits near the changed ceiling, offspring allocations and capacity-based inputs/digests change. **Determinism:** explicit birth-time binary32 operations and a deterministic adjacent-float/search rule can be portable; prove the conversion under native and wasm, preserving the no-fast-math flags. Do not assume a reciprocal inverse. **Atomicity:** preserved if the new ceiling is compiled consistently and all transactions use it before receipts/momentum are computed. **Tests:** full/adjacent energy roundtrip, maximality (next energy refused), original mass endpoints, capacity monotonicity/scale, conservation/overflow/funding and updated coefficient/reference/fixture evidence. Prefer this if an absolute physical-mass ceiling outranks preserving the present Ecap bits.

4. **(c): accept up to `nextafter(Mbound,+infinity)`.** **Law:** preserves current energy expressions and charge formulas, but explicitly replaces the old physical mass cap with a one-ULP tolerance. It cures the measured 86 high cases. It also expands the domain in all 45 equal and six lower cases where no expansion is needed. No proof here establishes that one ULP covers every legal body, so it is a weaker construction than option (a). **Non-capacity values:** formerly accepted values are unchanged; otherwise-invalid boundary masses become accepted whether or not a ledger requires them. **Determinism:** use the float overload/`nextafterf`, validate finiteness first, and test native/wasm identical result bits; the mathematical adjacent-float result is precise, but flags alone do not validate its library path. **Atomicity:** unchanged if only the comparison bound changes. **Tests:** old cap, one extra ULP accepted, second extra ULP refused/cleared, energy endpoints across body rails/random cases, finite/overflow cases, native/wasm outputs and all conservation/refusal gates. The tolerance must be declared, not silently installed as an epsilon.

5. **(d): clamp credits to the old admissible bound.** A coherent implementation must compute an energy target whose `fuelMass(target)<=Mbound`, **before** computing accepted energy, waste, `dm` and momentum. **Law:** changes the plan's fixed `target=clamp(E+requestedDelta,0,Ecap)` when that Ecap maps outside the old mass domain; for neutral it stops at `4233ffff`, below the declared 45 E capacity. A credit-only fix also leaves an already-full 45 E ledger un-loadable at the initial validation, so it does not reconcile the two API domains.

   Clamping only the mass passed to `evalLoad`, while retaining energy 45 and `dm=fuelMass(target)-fuelMass(E)`, breaks `Mfuel=E/500` and makes the loaded body disagree with its ledger/carried-mass update. Clamping inside a failed `loadAt` also conflicts with the plan's “Never silently repair a failed load.” **Non-capacity values:** unchanged away from the boundary only if all calculations use the corrected target; extra clipping/waste appears near capacity. **Determinism:** possible with one declared binary32 clipping rule and the same flags, but it is a behavioral change, not an atomicity fix. **Atomicity:** can be retained using local copies; an after-the-fact receipt/load clamp risks inconsistent energy/mass/P/H accounting even if stores remain atomic. **Tests:** exact accepted/spent/waste closure at clipped boundary, no hidden ledger/mass divergence, momentum conservation, invalid preexisting full ledger, repeated credits, transfers and native/wasm parity. Rank last because it either changes the required target or conceals an inconsistent body.

**Exact patch proposals, with no application or implementation validation.**

- `build_m2b1_pr2/diag/fix_capacity.patch` implements ranked option 1. It moves `fuelMass` without changing its expression; adds `fuelCapacity`; checks finite nonnegative capacity inputs; replaces the loader's bound/comment; updates the old refusal test to the approved boundary; and adds full/adjacent/interior/refusal/atomic-transaction checks across the 137 tool bodies. It does not edit the existing overflow expectation or any fixture/baseline/calibration constant.
- `build_m2b1_pr2/diag/fix_recovery_test.patch` independently changes the motor recovery observation/test only. The two patches affect separate portions of the step-test header and are intended to be applied together after authorization.

Both patches passed `nice -n 19 patch --dry-run --batch -p1` against the **current uncommitted** worktree, exit 0; logs are `fix_capacity.dry_run.log` and `fix_recovery_test.dry_run.log`. They are incremental patches against this draft, not against clean main. No patched source was materialized or compiled. Their tests are proposed evidence obligations, **not passing test claims**. Round 2 must compile and run them and must finish the larger draft implementation; these patches alone do not complete PR 2.

**The 1,800-step recovery observation was too short.**

The law is explicit in `docs/_ref/m2b1_brief_codex.md:427`–434 and 455–466:

```text
a(f) = .55+.90f
Psus = a(f) P0
Ppeak = [a(f)+2(1−f)] P0
Fmax = τburst(Ppeak−Psus), τburst=2 s, γ=.5
Fnext = clamp(F+h[Pb−min(F/h,γ max(0,Psus−P))],0,Fmax)
```

Source: `hydro_coefficients.hpp:844`–848 implements the powers/capacity; `ocean_energy.hpp:9` defines `h=kSubDt=.008f`; its lines 80–81 implement recovery and the next fatigue. The plan reproduces that recurrence at `docs/_ref/m2b1_pr2_plan_codex.md:369`–377. The current own-test limit is `tests/ocean_hydro_step_tests.hpp:134`; its analytic expected time and 0.016 s assertion are at 135–136.

At zero request with ample fuel, `P=Pb=0`, so fatigue decreases at `γ Psus` until the final partial step. From full fatigue, the real-valued recovery time is:

```text
T(f) = Fmax/(γ Psus)
     = [4(1−f)P0]/[.5(.55+.90f)P0]
     = 8(1−f)/(.55+.90f) seconds

f=0:  T = 160/11 s = 14.545454545... s
      T/h = 20000/11 = 1818.181818... substeps
      first possible completed integer observation = ceil(T/h) = 1819
f=.5: T = 4 s
f=1:  no burst/fatigue capacity; no recovery loop or division by Fmax
```

The brief's assay table at line 663 states recovery in “`4 s±2h` for γ=.5” for the neutral assay. The plan's line 1032 likewise describes the neutral case before asking for fibre 0/.5/1 tests. Four seconds is the neutral **f=.5** result; the explicit fibre-dependent law does not give four seconds for white fibre. The existing test correctly uses `Fmax/(γ Psus)` for each fibre. Its mistake is the observation horizon, not that expected formula.

The untouched kernel's actual binary32 white-fibre parameters and recurrence confirm the integer result:

| Quantity | Value | Bits |
|---|---:|---|
| `P0` | 86410.53125 | `47a8c544` |
| `Psus` | 47525.79296875 | `4739a5cb` |
| `Ppeak` | 220346.84375 | `48572eb6` |
| `Fmax` | 345642.09375 | `48a8c543` |
| `γ Psus` | 23762.896484375 | `46b9a5cb` |
| Rounded full-step decrement | 190.103179931640625 | `433e1a6a` |
| Analytic time evaluated as float | 14.545453071594238 | `4168ba2d` |

Using the exact stored values in double gives `1818.1815375503306` ideal substeps. Repeated binary32 subtraction also rounds at each step; it is not interchangeable with multiplying that ratio. The probe actually calls `limitMotor` on every step: after 1,818 recovery calls fatigue is still `35.178985595703125`; call 1,819 reaches zero, at float-observed time `14.552000999450684 s`. The mixed-fibre case actually takes 501 calls (`4.008000373840332 s`), illustrating the additional step that accumulated rounding can require even when a continuous formula gives four seconds. Peak fill takes 251 calls for white and mixed fibres, within the existing two-substep allowance.

The old 1,800 limit is only 14.40000057220459 s, about 0.14545 s shorter than the white-fibre analytic recovery. The proposal uses **2,000 substeps = 16 s**: 181 extra observations (1.448 s) beyond measured completion, or about a 10% margin over the analytic maximum white-fibre time. It retains the strict **0.016 s** timing tolerance and adds `fatigue==0`; it also checks each limiter call succeeds and that recovery remains free. This is a longer observation window, not a slower accepted law. A 1% slowdown adds roughly 0.147 s and fails the timing assertion; stalled or roughly >10%-slower recovery reaches the observation cap with positive fatigue and fails as well. The expected time derives from the declared coefficients, so this focused test checks the limiter against that law; independent coefficient/reference/assay checks must still detect an incorrect power/capacity law shared by both computation and expectation.

**Remaining gates and the round-2 authorization boundary.**

No remaining gate was run here. Gate 1 was previously inspected/passed. Gate 2 is still failed: the old native `hydro` selection passed, `hydro_step` failed two groups; the separate focused UBSan build/runs are **unrun**. Gates **3–12 are entirely unrun**. The new arithmetic/parameter probes and patch dry runs do not change that status. `kFrozenThrough` remains 0; no calibration, fixture equality, full matrix, timing or release completion is established.

For a coordinator-authorized implementation round 2, proceed in this order, using the copied plan's gate list (`docs/_ref/m2b1_pr2_plan_codex.md:1321`). Retain nice 19, network off, the plan's two-job/thread limits, local scratch/cache directories, raw commands/statuses/logs, and all frozen-scope rules. Do not use receipts to skip the first execution of changed gates.

1. **Authorize the numerical rule and edits first.** Accept the disclosed compatibility envelope (or choose fuel-space authority with its different patch), authorize applying the two incremental patches, and refresh base/tool/module identity and the fixed-PR-1 prerequisite audit. Record the acceptance-domain clarification in the round-2 report. This diagnosis authorizes no source/test edit, merge, deploy or rebaseline.
2. **Finish and rerun gate 2** (plan 1343–1354): complete the required focused coverage, build with `-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src`, run both `--only hydro` and `--only hydro_step`; separately build/run both under UBSan. Preserve the correct overflow/refusal/conservation checks and add boundary coverage. A correct-test or implementation failure blocks progression; no silent bound/test weakening.
3. **Complete and run gate 3** (1356–1364): finish the currently draft independent double actuator/trajectory/solver reference and sequential-patch comparator, then build/run `tools/ocean_hydro_reference.cpp`. Retain its independent law checks and relative LDL tolerance `2e-5`; report model differences without inventing an under-3% gate.
4. **Implement and run gate 4, calibration 1→2→3→4** (1366): the assay driver is still missing. Complete all specified subcases and metered 25 E incoming-mechanical-substep load support, rather than only outer-boundary refill. Run each assay; emit/rebuild its frozen header; rerun every preceding assay before advancing; retain candidate/final manifests and raw windows; final stage-4 `--check-all` must pass. Static/righting/depth/floor/release, tow/free-drive/fibre/shared-lambda/exhaustion, steering/body ordering/rails/finite 120 burst, and straight/turning/blocked calorimetry all remain unmeasured. Do not treat these recovery diagnostics as assay acceptance or freeze evidence.
5. **Run gate 5** (1368–1378): build native and wasm hydro and mechanics fixture drivers plus the assay driver using the offline matching emsdk. Compare native/wasm outputs **before** installing generated fixtures; then compare both against the installed fixture paths. Finish fixture/version/digest metadata. Existing hydro fixture metadata is stale for the draft; mechanics fixture generation is missing. No historical Ocean baseline or M2a fixture update is authorized.
6. **Integrate and run gate 6, full parity** (1380–1414): finish parity registration of the mechanics fixture/assay checks; unset `FAST`, `ONLY`, `NO_TESTS`, `NO_EYE`; set `APP_TWINS=all BODY_TWINS=all JOBS=2 BUILD_JOBS=2`, use a dedicated retained output directory, and preserve the raw exit status. This must cover complete native/wasm plain+eye unit outputs, historical chains, config guards, both hydro fixtures, M2a and the offline reference. If and only if the existing `life_cap_fixture_s1` body-twin exception is the sole failure, establish ordinary native/wasm/baseline equality, both body exits 5, equal body outputs, only `bodyFounders>0` failing, body section present, stripped output matching ordinary case, and every other case/check passing. Disclose the raw nonzero status; do not repair that unrelated harness or swallow arbitrary failure.
7. **Implement/run gate 7** (1416): uninstrumented native then wasm component timing and memory, sequentially with no competing builds. Reject A/A variation >3%; retain windows/raw results, timing components and remaining whole-world allowance. Measure actual vector capacities, allocator/transient/construction/copy/reset/export peaks; a 1,260 B element payload alone does not prove the 1,404 B resident ceiling. Complete-world population-2,000 M2/legacy ≤1.25 and lifecycle accounting remain PR 3.
8. **Run gate 8** (1418–1425): rebuild Ocean and check module freshness with `git diff --exit-code -- web/evo_ocean.js web/evo_ocean.wasm`. Expect identical public-module bytes in this internal-only PR; investigate any change.
9. **Run gate 9** (1427–1436): rebuild Classic ST/MT with the two-job limit and prove all four committed JS/wasm files unchanged. No `src/core` or Classic hash-pin change is authorized.
10. **Run gate 10** (1438–1446): configure/build `native-serial`, `--parallel 2`, then `ctest --test-dir build_serial --output-on-failure`. Establish and report actual SFML-dependent test availability and any genuine host/tooling limitation; unrun is not unavailable.
11. **Run gate 11** (1448–1457): `node tests/ocean_turbo_handoff.js`, `node tests/ocean_shader_slots_tests.cjs`, `node tests/ocean_materials_tests.cjs`, `node tests/ocean_mock_three_tests.mjs`; run the existing local TypeScript installation if present, without fetching dependencies. Live rendering/checkpoint/export and enabled Turbo verification remain PR 3; this plan does not require a new browser run for unchanged rendering/public paths.
12. **Run gate 12** (1459–1471): final frozen-scope diffs against the recorded base, `git diff --check`, changed-file/status inventory, and confirmation that production stepping/lifecycle, public refusal/configuration, fingerprint format, checkpoint APIs, renderer, `src/core`, Classic and historical baselines/M2a fixture remain untouched. Produce the final evidence report with real gates/versions/digests/fixtures/calibration/timing/memory and the disclosed exception if actually reached. Coordinator commits come after completion/validation; nothing here authorizes a commit, merge, deployment or rebaseline.

Preservation evidence: `build_m2b1_pr2/diag/existing_files.before.json` records hashes, sizes and modification times of all 442 preexisting worktree files (without traversing `.git` directories or symlink targets). The final comparison is `existing_files.verification.json`. Proposed patches are outside the source/test tree; the existing failed bootstrap report remains historical evidence, unchanged.
