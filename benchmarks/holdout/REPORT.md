# Frozen validation results

Small independently-authored holdout validation set, separate from the 12 development fixtures. Not an external benchmark, expert-reviewed set, blind evaluation, or statistically representative sample. The author read the API, development catalog, and generator. Cases and parameters were frozen before generated evaluation; no post-result tuning was performed. Agreement within a finite budget does not establish equivalence.

## Fixed protocol

Five cases; seeds 712000–712031; 32 generated instances per case and method; max_rows=8. Random and boundary use paired seeds. Each generated instance is compared with the mutant and equivalent control. No early stopping or parameter tuning.

Literal hand-computed expected bags validate all three queries on both revealing and masking fixtures. These checks use Python Counter rather than the production result comparator. They still share the SQLite execution engine; they are not a second-engine differential oracle.

## Observed outcomes

Completed comparisons: 640/640. Literal oracle checks: 30/30. Control mismatches: 0. Inconclusive comparisons: 0.

| Case | Random | Boundary |
|---|---|---|
| composite_partial_null | detected; 19/32 mismatches; first=1 | detected; 18/32 mismatches; first=2 |
| dual_nullable_role_keys | detected; 23/32 mismatches; first=2 | detected; 24/32 mismatches; first=2 |
| unicode_duplicate_labels | detected; 11/32 mismatches; first=5 | detected; 15/32 mismatches; first=3 |
| real_inclusive_boundaries | detected; 23/32 mismatches; first=3 | detected; 22/32 mismatches; first=4 |
| three_table_join_grain | detected; 21/32 mismatches; first=2 | detected; 21/32 mismatches; first=2 |

Unsupported query comparisons: 0; query errors: 0; unsupported generation attempts: 0; generation errors: 0; other recorded errors: 0.

Exact replay checks: 15/15. Five authored witnesses are retained regardless of generated detection. The first generated mismatch per case and method is reduced and saved separately; reduction does not consume the comparison budget.

## Reproduce

From a checkout with the pinned dependency installed:

```sh
python scripts/run_holdout.py --out holdout-reproduction
```

The output directory must be new. To inspect the freeze before execution, first run with --freeze-only, then run the same command without that flag. The case-file SHA is pinned by the script. Compare case/generator/source hashes, generated data and status records, expected outputs and replay checks; runtime provenance and elapsed times can vary. Every generated instance and typed observation is in raw/*.jsonl; manifest.json hashes every output other than itself.

## Limits

These five purposively selected tasks extend schema/domain/constraint coverage beyond the development catalog, but revisit related SQL semantic mechanisms. Reading the catalog and generator makes this a modest internal validation split, not independent external validation. One seed sweep is one run per method/case, not 32 independent tasks. No population-level confidence intervals, superiority claim, or false-positive-rate estimate is justified. A missed mutant is retained as a miss, never relabeled equivalent. Equivalent controls follow the declared constraints and SQLite contract.
