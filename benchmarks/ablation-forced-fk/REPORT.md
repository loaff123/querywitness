# QueryWitness synthetic evaluation

Synthetic regression coverage only. Seed repetitions are not independent tasks. No LLM, SOTA, population-generalization, or equivalence-proof claim.

12 families; 16 instances per method/run; 8 seed repeats. Random and boundary each have 96 mutant runs. Every generated instance is also tested against its equivalent control.

Actual instance comparisons: 6144; control mismatches: 0; inconclusive comparisons: 0.

| Method | Detected family-runs | Distinct families detected |
|---|---:|---:|
| random | 85 / 96 | 11 / 12 |
| boundary | 88 / 96 | 11 / 12 |

The separate single-benign-fixture baseline detected 0/12 mutants. Masking fixtures were authored to illustrate one-database blindness; this is not evidence about arbitrary production datasets.

## Per-family detection runs

| Family | Random | Boundary |
|---|---:|---:|
| join_multiplicity | 8/8 | 8/8 |
| count_nullable | 8/8 | 8/8 |
| not_in_null | 0/8 | 0/8 |
| left_join_filter | 8/8 | 8/8 |
| sum_distinct | 8/8 | 8/8 |
| average_grain | 8/8 | 8/8 |
| null_negation | 8/8 | 8/8 |
| empty_aggregate | 5/8 | 8/8 |
| union_multiplicity | 8/8 | 8/8 |
| correlated_filter | 8/8 | 8/8 |
| inclusive_boundary | 8/8 | 8/8 |
| having_grain | 8/8 | 8/8 |

## Reproduction and limitations

Run the command in docs/REPRODUCIBILITY.md with the configuration in manifest.json. Compare raw seeds, status, data hashes and observations; elapsed times and environment metadata vary. No confidence interval is supplied: repeats reuse the same tasks, and the 12 tasks are purposively selected, not sampled. There is no held-out real-workload set. Generator domains are supplied by each catalog schema. Neither strategy is query-aware or complete. Equivalent controls are mathematical constructions, not a statistical estimate of the false-positive rate on all SQL.
