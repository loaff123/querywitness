# Reproduction and evaluation protocol

This protocol separates a tool demonstration, regression validation, and measured generator coverage. The actual release numbers are recorded in [`benchmarks/v1/REPORT.md`](../benchmarks/v1/REPORT.md); this document does not substitute anticipated outcomes for executions.

## Reproduce a checkout

Use a clean Python 3.11+ environment with SQLite support. Record the exact Git commit rather than relying on a moving branch.

```sh
git clone https://github.com/loaff123/querywitness.git
cd querywitness
git rev-parse HEAD
python -m venv .venv
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install .
python -m unittest discover -s tests -v
python -m querywitness catalog --validate
python -c "import sys, sqlite3, sqlglot; print(sys.version); print(sqlite3.sqlite_version); print(sqlglot.__version__)"
```

Packaging pins SQLGlot 27.29.0. SQLite comes from Python's runtime and may differ by OS/distribution even for the same Python version. Retain that version along with Python, platform, package version, commit, test output, and command. A passing test suite does not certify unsupported syntax or all environments.

For a clean package check, build wheel/sdist with `python -m build`, install the wheel in a second new virtual environment outside the checkout, and run `python -m querywitness catalog --validate`, demo, and replay there. Building requires the standard Python `build` package. This catches missing package data and accidental dependence on the source tree.

## Equal trial-budget experiment

```sh
querywitness benchmark --out reproduced-v1 \
  --trials 16 --repeats 8 --seed 20260930 --max-rows 8
```

Use the published manifest's configuration if it differs. `reproduced-v1` must not already exist. To make a smaller smoke run, select a family explicitly and report it as a subset:

```sh
querywitness benchmark --out smoke \
  --family count_nullable --trials 3 --repeats 2 --seed 100
```

### Fixed factors

The runner fixes the catalog/schema domains, bag comparison, maximum rows per table, default execution limits, and two methods (`random`, `boundary`). Both methods evaluate the mutant and equivalent-control variant with the same schedule:

`trial_seed = base_seed + repeat_index * trials_per_run + trial_index`

Every run evaluates all scheduled trials. A first hit is logged but does not end the run. This distinguishes the benchmark from the search command's early stopping. Generators are query-independent; neither reads the SQL to choose values.

For `F` families, `R` repeats, and `T` trials, the matched-budget experiment performs `F * 2 methods * 2 variants * R * T` query-pair comparisons. Each comparison executes two queries on fresh databases. Both methods therefore have equal trial budgets, not necessarily equal CPU time, row counts, distinct instance counts, or useful coverage. Duplicate instances remain in the denominator.

Additional work is explicitly outside that denominator:

- Catalog validation runs three queries on two fixed fixtures per family
- The single-benign baseline compares one mutant pair per family
- The first discovered mutant witness for each family is reduced and written as a bundle
- Bundle construction reexecutes queries, and reduction has its own checks/time budget

The methods run in a fixed order, random before boundary. Only one bundle per family is saved, so the illustrated witness may come from the first method even if the second also finds witnesses. It is not an independently selected or globally best witness.

### Baseline interpretation

The benign fixture is deliberately authored to mask each bug; report it separately. Do not describe this as a fair equal-cost contest between a single arbitrary production database and generation. Random and boundary methods share finite pools and constraints, so "random" here means this particular constrained sampler, not uniform sampling over all legal databases.

## Inspect the evidence

- `manifest.json`: tool/Python/SQLite/parser/platform versions, catalog hash, complete configuration, raw column definitions, validation result, and hashes of raw files
- `summary.json`: per-family/method/variant counts, first-hit positions, detections, controls, inconclusive observations, and runtime metadata
- `raw/<family>.jsonl`: benign result plus every method/variant/repeat; each trial stores seed, comparison status, instance hash, total input rows, and both query statuses
- `witnesses/<family>/`: actual mismatch bundles, when found
- `REPORT.md`: a readable summary of that run

Raw records contain hashes rather than every generated database. Regenerate a trial with the recorded schema, seed, strategy, and `max_rows`, then verify `querywitness.artifacts.digest(instance)` against its recorded hash. The exact catalog and generator version matter. This is a reproducible seed log, not a complete corpus of materialized test databases.

Compare semantic fields, raw instance hashes, seeds, statuses, denominators, and witness observations. Wall-clock durations and platform metadata will differ; complete JSON files need not be byte-identical. Runtime drift may also change SQL behavior or resource-limit outcomes, which must be disclosed rather than normalized away.

## Metrics and reporting rules

Report mutant detected family-runs over all scheduled family-runs for each method, and distinct detected families over selected families. Also report per-family results, control mismatches, inconclusive comparisons, completed evaluations, the full budget, and the catalog/version. First-hit trial is an ordered position within a fixed budget, not a time-to-detection measurement.

Elapsed run times include generation and execution; the run that saves a witness also includes its reduction and bundle work. Total time includes the separately labeled baseline and witness work but starts after catalog validation. These measurements are not isolated generator performance, peak memory, or an equal-wall-time comparison.

Do not drop inconclusive cases from denominators to improve a success rate. Inspect any control mismatch before making accuracy claims: it can indicate a bad control, floating-point effect, semantic-guard gap, or implementation bug. Preserve negative findings and failed runs.

No confidence interval is supplied by the runner. The 12 families are purposively selected, and seed repeats reuse those same tasks. Treating every seeded trial as an independent research task would overstate evidence. A generalization study would need independently collected/held-out families, prespecified selection and evaluation, additional oracles, and a justified uncertainty method. The supplemental internal frozen-case check below does not establish that kind of generalization.

## Reproduce the pre-fix ablation

The initial generator forced nullable foreign keys to reference a parent whenever parent rows existed. This erased the legal NULL cases needed by `not_in_null`. It was repaired after inspecting these 12 development families; final catalog performance is therefore not a held-out estimate.

The original full core source and catalog snapshot, SHA-256 records, raw run, and report are retained under `benchmarks/ablation-forced-fk/`. To rerun that implementation without replacing the installed current package:

```sh
python scripts/reproduce_ablation.py --out reproduced-ablation
```

The destination must be new. The helper runs the retained snapshot with its recorded configuration. Compare raw trial seeds, statuses, instance hashes, and counts; elapsed times can differ. The pre-fix run detected 85/96 random and 88/96 boundary mutant family-runs, each covering 11/12 families. The final v1 run detected 93/96 and 96/96 respectively, each covering 12/12. This is a within-project development ablation with post-inspection repair, not an independently preregistered result or an external-method comparison.

## Reproduce the supplemental frozen cases

```sh
python scripts/run_holdout.py --out holdout-reproduction
```

The five cases in `benchmarks/holdout-cases.json` and their protocol were frozen before generated evaluation. The script pins the case-file hash and records generator/source hashes and runtime versions. An optional first invocation with `--freeze-only` creates just the freeze record; the same command without the flag then evaluates it. Otherwise the destination must be new. A generator change between those two steps is rejected.

The fixed protocol evaluates random and boundary on seeds 712000–712031, 32 instances per case/method, maximum 8 rows per table, bag semantics, and default execution limits. Each instance is tested against mutant and control, totaling 640 comparisons; no early stopping occurs. Literal expected bags check all three queries on masking and revealing fixtures, totaling 30 oracle checks. Five authored witnesses plus the first generated witness per case/method are saved and replayed; reduction is outside the comparison budget.

Read `benchmarks/holdout/REPORT.md`, `summary.json`, `manifest.json`, `freeze.json`, and `oracle-checks.json`. Its `raw/*.jsonl` files retain full instances and typed observations, and its manifest hashes outputs except itself. Compare these semantic records, case/generator/source hashes, and replay outcomes, allowing runtime/timestamp/timing metadata to differ.

The recorded result was 5/5 detected cases for each method, all 640 comparisons completed, 30/30 oracle checks passed, 15/15 exact witness replays, and no control mismatches or inconclusives. The case author had inspected the generator and development catalog: this is a small internal frozen validation set, not blind/external validation. Do not pool these five cases and the twelve development families into a single independent benchmark score.

## Replay a published witness

```sh
querywitness replay benchmarks/v1/witnesses/count_nullable/witness.json
```

Use an actual witness directory listed in the report. `reproduced` checks exact observations and a present mismatch. A different SQLite version is flagged. Checksum integrity is not authentication; inspect any third-party fixture and use a suitably isolated local environment. Do not run unknown SQL fixtures in a database containing sensitive data.
