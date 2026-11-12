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
identity still governs the matched-control join and sharing checks.

## Estimation and reporting

The H-P and H-Q fits use the fixed 41-opponent coarse panels and their measured observations, with a
single occurrence of each free-control observation in the joint likelihood. H-C jointly fits its four
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
`detection` is the authoritative family decision. `material_point`, `operational_success` and
`material_exceedance` are distinct. H-T's material-exceedance field is null because its fourteen-margin
transition claim has no additional nested material test. Raw estimator results, support coverage,
eligibility, ecology, adjusted p-values and material-spec provenance accompany the rows. Defined
infinities serialize as explicit strings in strict JSON.

Production fixes the registered six assay replicates, 9,999 bootstrap draws and Q200 minimum 24. The
Python integration fixture explicitly uses `production=False`, one replicate and 19 draws to exercise
real estimators in minutes. Its non-production marker is retained in the report. This verifies the data
contract; it is neither numerical calibration nor a power claim.
