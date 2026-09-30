# Synthetic catalog and evaluation card

## Purpose and composition

The version 0.1.0 catalog is an original, purpose-built set of **12 synthetic SQL error families** for exercising QueryWitness's comparison, generation, reduction, and replay workflow. Its source is [`src/querywitness/data/catalog.json`](../src/querywitness/data/catalog.json), distributed under the repository's MIT license.

Each family has one schema contract, reference query, deliberately wrong mutant, algebraically motivated equivalent control, benign masking fixture, revealing fixture, and literal expected reference/mutant outputs on the revealing fixture. Each uses bag semantics. The schema and finite domains are part of the case: a control's intended equivalence can depend on them.

The examples were authored for this project with AI assistance. They are not scraped production workloads, externally annotated model outputs, or a human/expert-reviewed benchmark. The phrase "hand-authored" in catalog metadata means explicitly constructed fixtures rather than samples from a workload corpus; it is not a human-validation claim. No personal data, paid model calls, or LLM performance evaluation are involved.

| Family ID | Semantic distinction |
| --- | --- |
| `join_multiplicity` | Existence versus one output row per matching child |
| `count_nullable` | Counting non-NULL values versus counting rows |
| `not_in_null` | Anti-existence versus `NOT IN` with a NULL-bearing subquery |
| `left_join_filter` | Filtering the optional relation in `ON` versus `WHERE` |
| `sum_distinct` | Summing rows versus summing distinct values |
| `average_grain` | Row-weighted mean versus unweighted mean of group means |
| `null_negation` | Explicit missing-value acceptance versus SQL unknown |
| `empty_aggregate` | Defined zero versus NULL for an empty sum |
| `union_multiplicity` | `UNION ALL` versus duplicate removal |
| `correlated_filter` | Per-parent predicate versus uncorrelated global existence |
| `inclusive_boundary` | Inclusive versus strict endpoint |
| `having_grain` | Filtering aggregate groups versus filtering input rows |

## Validation and its limits

`catalog --validate` checks schema validity and executes three queries on each of two fixtures: 72 fixture-query executions for all 12 families. A benign fixture must mask the mutant. A revealing fixture must distinguish it, and its literal expected outputs must match. The control must agree with the reference on both fixtures.

The literal expected outputs are specified independently of the production comparator; validation uses Python `Counter` on returned tuples. This is an additional oracle check, not a second independent SQL engine or a machine-checked proof. The expected values and control labels can themselves contain errors. These checks do not certify all possible inputs or excluded SQL features.

## Evaluation tasks and units

The evaluated method is database generation, not a language model. The two matched-budget methods are random and boundary-biased generation from the same contracts and value pools. A separately reported single-benign-fixture baseline illustrates a deliberately constructed blind spot; its masking behavior is by design.

- A family is one distinct synthetic query-error construction
- A family-run is one method's fixed trial sequence for a family and seed repeat
- A trial is one generated instance and query-pair comparison
- A repeat changes seeds, not the underlying task
- Mutants and equivalent controls are separate variants; both are evaluated

Twelve families remain twelve families regardless of the number of seeds, rows, executions, or files. Reusing seeds across methods provides a paired schedule, not identical instances: different generation branches can consume the random stream differently.

## Recorded v1 results

The [recorded report](../benchmarks/v1/REPORT.md) and [manifest](../benchmarks/v1/manifest.json) use 16 trials, 8 repeats, seed 20260930, and at most 8 rows per table. The 6,144 matched-budget comparisons produced zero control mismatches and zero inconclusive comparisons. Random detected 93/96 mutant family-runs; boundary detected 96/96. Each detected 12/12 distinct families. The three additional boundary detections were in `empty_aggregate` (8/8 versus 5/8). These are development-set observations on this catalog and schedule, not evidence of a general performance advantage: the generator was debugged on these same families.

The retained [pre-fix run](../benchmarks/ablation-forced-fk/REPORT.md) found 85/96 random and 88/96 boundary family-runs, with both methods missing `not_in_null` in all eight repeats. The original generator overwrote a child's initially sampled NULL with a parent-key value whenever parent rows existed. Here that parent primary key is non-NULL. If no parent rows existed, neither query could return a parent. This made a revealing mixture of a NULL child key and an unmatched parent unreachable, although the explicit revealing fixture was schema-valid and detected the error.

More seeds alone could not repair that rule. The final generator preserves a sampled composite FK whenever any component is NULL, while still validating every proposal. The complete original source snapshot, hashes, and raw records are preserved rather than replacing the negative evidence. See the [reproduction instructions](REPRODUCIBILITY.md#reproduce-the-pre-fix-ablation). This post-inspection repair is why the v1 catalog must be labeled a development set. It also demonstrates why replay of an authored revealing fixture and generated coverage are different evidence. The single-benign baseline detected 0/12 by construction.

The manifest records Python 3.12.14, SQLite 3.53.1, and SQLGlot 27.29.0 on Linux. Its recorded total elapsed time is local diagnostic metadata, not a speed comparison with another tool or a controlled microbenchmark. No uncertainty interval or external-system comparison was run.

## Supplemental frozen validation

Five additional synthetic cases were separately authored after inspecting the API, development catalog, and generator: `composite_partial_null`, `dual_nullable_role_keys`, `unicode_duplicate_labels`, `real_inclusive_boundaries`, and `three_table_join_grain`. They extend schema/domain combinations while revisiting related SQL mechanisms. The [case file](../benchmarks/holdout-cases.json), literal oracle outputs, configuration, and [freeze record](../benchmarks/holdout/freeze.json) were fixed before generated evaluation. No post-result tuning was performed. The case-file SHA-256 is `db43f222ba5d2e36999abf78e269322a20cf149253a95dadadfcc5431b366ae7`.

The [recorded validation](../benchmarks/holdout/REPORT.md) evaluated 32 seeds (712000–712031) per method and case, with bag comparison and at most 8 rows per table: 320 generated instances and 640 mutant/control comparisons. Both methods detected 5/5 mutants; all 30 literal fixture/query checks passed; control mismatches and inconclusive comparisons were zero. Fifteen retained authored/generated witness bundles replayed with exact observations. Full generated instances and typed observations are retained in the raw records, unlike the compact seed/hash logs of the development benchmark.

"Holdout" in the artifact paths means cases frozen before this evaluation and separate from the original twelve. Their author saw the generator, they are AI-assisted synthetic cases, and they are neither a blind/external study nor independently expert-reviewed. One 32-seed sweep remains one run for each method/case. This modest internal validation does not supply a population error rate or remove the development-set caveat from v1.

## Appropriate interpretation

Use the catalog for regression testing, demonstrations, instrumentation checks, and tightly scoped generator comparisons. Use the actual [versioned report](../benchmarks/v1/REPORT.md), raw records, and manifest for measured numbers. Report failures, unsupported/inconclusive outcomes, and control mismatches alongside detection counts.

Do not use these results to claim:

- General accuracy on production SQL, another dialect, or all valid schemas
- LLM pass rates, human performance, or an independent expert annotation study
- State-of-the-art performance against external systems not run under a comparable protocol
- Formal equivalence from agreement or globally minimum witnesses from row reduction
- Statistical generalization from seed-level confidence intervals

## Bias, leakage, and missing coverage

The twelve-family catalog is purposively selected and visible during implementation; it has no internal held-out split. The generator and those cases were developed together, and domain values may make some distinctions easy. The supplemental frozen cases have the narrower independence described above. The benign fixtures intentionally hide the errors. All queries and expected outputs are public, so contamination-sensitive model evaluations would need a different dataset and protocol.

Missing areas include real application schemas, diverse SQL dialects, business constraints beyond the JSON contract, large databases, cyclic-FK generation, broad string/date behavior, query-plan guidance, solver synthesis, windows, limits, and general scalar subqueries. One mutant per family does not exhaust that error category. Seed sweeps characterize this implementation on these cases, not a population of unseen queries.

## Maintenance

New families should include a clear requirement, independently reasoned revealing outputs, a genuinely masking benign fixture, a justified control, provenance/license information, and a regression test. Change the catalog version and rerun the full evaluation when semantics or cases change. Preserve the old report/manifest rather than silently replacing evidence. No external dataset is incorporated merely by citing related work.
