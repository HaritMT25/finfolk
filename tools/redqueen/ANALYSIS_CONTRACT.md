# Annex H production analysis adapter (D8)

`analysis.py` is an outcome-reading command. Its integration suite uses synthetic outcomes only.
Do not run it on production or validation outcomes before the authorized analysis freeze.

```sh
PYTHON=/absolute/offline/venv/bin/python3
nice -n 19 "$PYTHON" -I tools/redqueen/analysis.py \
  --root ASSAYS --root SCRIPTED_ASSAYS --plan EXECUTABLE.jsonl --plan-sha256 FROZEN_DIGEST \
  --registry worlds.json --ecology ecology.json --mask mask.json --references references.json \
  --params fitted-generator.json --critical critical.json --acceptance acceptance.json \
  --gates epoch-gates.json --out final-analysis.json
```

Supply one combined, frozen executable plan containing the required cells from every root, including
predator-free and scripted assays. A control shared across panels is measured and supplied once.
The roots must contain committed chunks; unpacked work directories are not an analysis input. Missing,
duplicate, extra, substituted or incomplete bundles are errors, including a missing cell in an otherwise
valid archive. The CLI checks the frozen plan digest. The API accepts decoded rows so callers must bind
their plan bytes themselves. Neither path repairs stores, writes inputs, launches engines or reads archives.

The registry, ecological export, graphmask/2 and references/1 assignment are the existing production
formats. The executable plan must carry their registered availability binding. The adapter uses
`plan.references_index`, `plan.mask_index`, `stats.eligibility` and the shared mask validator. Each
source snapshot must have the verified archive digest registered by the mask or reference assignment.
Biologically unavailable worlds remain in the ecological report; technical measurement gaps are pending
repair. A complete world's omitted required panel is an error, never a smaller analysis population.
The common Q200 population and the separate H-C block population come from the existing dispatcher.

## Bundle fields

| Input | Fields read and purpose |
|---|---|
| Chunk index | `chunk`, `bytes`, `sha256`, `cells`; per-member hashes and completion summaries. Every archive and selected member is hashed. |
| `done.json` | `bundle_sha256`, row/kind/common/pair/prey-config summaries, `role`, `families`, transplant group and realized digest; checked against the bundle and index. |
| `bundle.json` | `schema` must be bundle/2; `cell` must equal the plan row exactly; `score`, `sharing`, `files.common.json`, `arena_prey_config_sha256`. |
| Plan cell | `schema`, `id`, `availability`, `namespace`, `role`, `kind`, `assay`, `prey_policy`, `k`, `steps`, `horizons`, `replicate`, `prey`, `predators`, `groups`, `seeds`. Remaining fields are checked by exact plan-row equality. |
| Endpoints | `snapshot` joins controls and reference sources; `sha256` binds bytes; `uuid` resolves registered worlds/attempts (including display aliases); **`frame / 1e6` is the actual time**, including F1 = 1e-6 M. Display time labels are not the analysis clock. |
| Scorer | `schema`, `n_start=600`, `dt=0.016`, `k`, `assay`, `steps`, `scripted`; exactly one `horizons[].steps=5000`, integer `captures` and `survivors`; required no-replenishment, frozen-K and fork checks. Capture denominator is the registered `noisebank.capture_bound(5000)=324`; survival denominator remains 600. |
| Sharing | Keys and seeds must equal the cell's; realized common digest must match `files`; all common, pair and transplant groups must agree across chunks/roots. Exposed/free sample, age and reseed keys/seeds must agree. |

The bundle's engine arguments, embedded CSV text, timing/CPU/host fields, other horizons, cosmetic
metadata and readouts such as energetic buds/pursuit are not estimators' inputs. The chunk digest still
covers these bytes. Optional `age_strata` in each horizon is tolerated and ignored by the five primary
tests; its presence or absence does not alter their estimands. This adapter does not implement the
separate descriptive age-stratum analysis. History energy expenditure is not inferred from assay data.

All main roles (training, validation, test, support) enter the frozen confirmatory backbone. Independent
namespaces, audits, diagnostics and other assay/construction conditions are explicitly counted as ignored.
Cross-world and reference-grid pairs are verified but not part of these within-world hypotheses. Unknown
external sources are refused unless the reference assignment authenticates them. Reference identity is
translated to its registered `RQ:k` / `RP:k` slot for the calibration graph fingerprint, while snapshot
identity still governs the matched-control join and sharing checks. Slots are indexed by guild and
snapshot: a snapshot selected once in each guild retains both slots.

## Estimation and reporting

The H-P and H-Q fits use the fixed 41-opponent coarse panels and their measured observations, with a
single occurrence of each free-control observation in the joint likelihood. Both coordinates must be
coarse, including in H-T's epoch directional fits. Fine observations remain recurrence inputs.
H-C jointly fits its four
neural references and scripted benchmark, then passes per-world slopes to the existing count-weighted
block dispatcher. H-F and H-T use measured replicate means with matched controls, the same null-fitted
bank covariance builder as calibration, and shared-reference source loadings. H-T recomputes the epoch
recurrence gates from the observed epoch statistics and frozen epoch critical values; it uses all
fourteen margins and all six candidates. A completed `T_T=-Infinity` is available with family p=1.
NaN, numerical failures, missing calibration or absent qualifying populations cannot reject.

Critical values and acceptance are the real `calib.py crit/accept` artifacts, not supplied p-values.
The adapter checks the acceptance's critical-artifact digest, development/validation identities, D8
specification, fitted parameters, tools, draws and realized graph. Model p-values come from the
acceptance artifact's stratified `ptables`. Frozen epoch gates must pass the existing count-based checks and match the exact gate-artifact digest used in H-T calibration.
There is no synthetic calibration fallback in production. A stale artifact is refused.

The five rows always remain in Holm; an unavailable row has `available=false`, a reason, and p=1.
Below the Q200 minimum, no confirmatory calibration artifact is consumed; missing or stale calibration
cannot suppress descriptive estimation. Measured world slopes, epoch slopes and recurrence estimates appear
under `descriptive`; they cannot enable a confirmatory decision. With one qualifying world, retain its
slope but do not attempt world resampling. With no qualifying worlds there are no such estimates.
`detection` is the authoritative family decision. `material_point`, `operational_success` and
`material_exceedance` are distinct. H-T's material-exceedance field is null because its fourteen-margin
transition claim has no additional nested material test. Raw estimator results, support coverage,
eligibility, ecology, adjusted p-values and material-spec provenance accompany the rows. Defined
infinities serialize as explicit strings in strict JSON.
`descriptive.H_F` retains the raw H-F functional, positive-contribution count and selected-world
summaries. `H_F_worlds` and `epoch_worlds` retain every candidate's measured support failures, phases,
readouts and reversal/return chains; `epoch_H_F` retains epoch functionals. `epoch_betas`, `gate_flags`
and (when calculable) `H_T` retain the transition inputs and descriptive components.

## D8 v2 generator and fit provenance

Survival means are `c_H * sigmoid(eta)` in every generator path, including native means and boundary
searches. Draw `min(M_H, floor(600 * sigmoid(a + epsilon) + 0.5))`; solve its location with the cap
inside the expectation. The upper category includes the entire upper latent tail. Means zero and
`c_H` give deterministic counts zero and `M_H`; `M_H=0` gives only zeros. Capture retains its own bound.
The internal table key records both count scale and ceiling; cache identities bind the support law,
engine age-clock sources and material specification. Capped tables refine their location grid until
they meet the existing interpolation tolerance. The calibration generator and its H-T resampling use
`AnnexH/D8/1`, bound into manifests. Other stream namespaces and reservations are unchanged.

`material.age_feasible` is the common age-only support predicate. It rounds the starting age, timestep
and maximum age to binary32, adds the binary32 timestep with binary32 rounding at each frame, and
tests strict `age > max_age`. A cached binary search finds the largest feasible binary32 starting age;
monotonicity makes its predicate equivalent to executing the clock for every individual. It supports
actual registered physiology, including construction-specific maximum ages. For the frozen 600 ages,
ceilings are 247, 0 and 0 at 5k, 10k and 20k; survival denominators remain 600.

Production parameter artifacts must explicitly contain `cohort`, `cohort_sha256`, `horizon`, `dt`,
`support_law`, `age_clock`, `engine_sha256`, `survivor_ceiling`, and `fit`, as well as the existing fitted flag and curves.
Use the exact authenticated registered cohort, its D8 source hash, horizon 5000, timestep 0.016,
`material.SUPPORT_LAW`, `material.age_clock_identity()`, the actual fitting-source engine executable
SHA-256, and ceiling 247. `fit.mean_head` must be
`c_H*sigmoid(eta)` and `fit.noise_likelihood` must be `600-rounded-capped-upper-infinity`.
Both `fit.mean` and `fit.noise` must identify `implementation_sha256`, `inputs_sha256` and
`receipt_sha256`. These fields attest the fitting procedure and bind its independent receipts; they
do not implement or replace the scientific fit review. Missing provenance is refused, with no
production defaults. In particular the fitted interval likelihood's upper capped category must have
latent upper endpoint +infinity. Parameter fitting is still outside this generator module.

Every pre-D8 mean/noise fit or fit without this provenance is stale. Regenerate/refit those fits,
survivor location tables, covariance/loadings, development and validation panels, boundaries and B/I
audits, H-F critical values and material tables, epoch gates, complete H-T calibration, acceptance and
power reports. No regeneration or power claim is supplied by these synthetic tests. All production
calibration remains subject to D5's cumulative CPU budget; D8 provides no reset.

Production fixes the registered six assay replicates, 9,999 bootstrap draws and Q200 minimum 24. The
Python integration fixture explicitly uses `production=False`, one replicate and 19 draws to exercise
real estimators in minutes. Its non-production marker is retained in the report. This verifies the data
contract; it is neither numerical calibration nor a power claim.
