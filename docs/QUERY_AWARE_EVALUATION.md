# Query-aware generation: measured development evaluation

QueryWitness 0.2.0, 2026-09-30. **Development evidence, not held-out external generalization.** This change was motivated by already inspected external failures. It is not a new solver, formal equivalence method, completeness result, or state-of-the-art claim.

## Methods and budgets

`random` and `boundary` source bytes are unchanged from 0.1.0. The optional `query_aware` strategy uses both SQL texts symmetrically to form explicit finite value pools and constraint-checked schedules. Declared column domains and row bounds remain hard limits. See [the strategy contract](QUERY_AWARE.md).

For each method and task: four starting seeds (20260930, 20261930, 20262930, 20263930), 64 trials per seed, at most eight accepted rows per table, positional bag comparison, and unchanged per-query limits (10,000 output rows, 2,000,000 bytes, 1,000,000 approximate VM steps, two seconds, 32,768 SQL bytes). Every trial was retained after the first hit.

These are equal trial, row-ceiling and execution-budget comparisons. **They are not equal-value-domain, equal-generated-row-count, equal-generation-attempt or equal-time comparisons.** Query-aware sampling deliberately adds type-valid inferred values only where no explicit finite schema domain forbids them. Method order was fixed; timings are not a speed benchmark.

Runtime: Python 3.12.14, SQLite 3.53.1, SQLGlot 27.29.0. The complete study executed 46,848 paired-query trials across two separate cohorts in 150.36 seconds on this environment. No population-level speed or uncertainty claim follows from that one runtime.

## Original frozen suite: public, reproducible evidence

A separate author created 16 original pairs and 22 hand-reasoned fixtures from the semantic contract, without inspecting the generator implementation or external corpus/results. The suite was frozen before generator evaluation. Its independent stdlib SQLite validator also checks 210 small bounded instances and two deliberately invalid inputs. This is still newly authored, AI-assisted development validation, not a representative or external workload. No human/expert adjudication is claimed; independence refers to separate fixture/checker construction, not an independent organization or SQL engine.

The 16 pairs comprise eleven known distinguishable pairs within row8, four globally equivalent controls, and one globally different pair whose witness requires nine rows and which is equivalent within row8.

| Method | Detected tasks | Detected runs | Mismatch trials | Both-empty trials | Inconclusive |
|---|---:|---:|---:|---:|---:|
| random | 6/16 | 24/64 | 647/4,096 | 2,460/4,096 | 0 |
| boundary | 6/16 | 24/64 | 668/4,096 | 2,528/4,096 | 0 |
| query_aware | 11/16 | 44/64 | 998/4,096 | 2,122/4,096 | 0 |

Query-aware found all eleven cases with a known witness inside the stated bound. None of the three methods reported a mismatch on the four equivalent controls or the beyond-bound case: 3,840 negative-control/bounded-control comparisons in total. This does not estimate a false-positive rate over arbitrary SQL.

All 92 saved original-suite first-hit witnesses passed independent schema, typed-bag, observation and reverse-insertion replay checks. The checker does not import the product database builder or comparator; it does share the same SQLite library, so shared DBMS bugs remain possible. These are valid witnesses, not claims of global or row-1 minimality.

- [Frozen original suite and oracle](../benchmarks/query-aware-original-suite/)
- [Original-only raw records and witness checks](../benchmarks/query-aware-original-results/)
- [Original-only reproduction script](../scripts/evaluate_query_aware_original.py)

Raw trial logs are losslessly gzip-compressed with both compressed and uncompressed hashes. Their timing fields are machine-dependent; reproduction compares deterministic outcomes and instance hashes rather than requiring equal elapsed seconds.

## External development cohort: aggregate findings only

The pinned upstream source is [VeriEQL/VeriEQL at 493cbb8](https://github.com/VeriEQL/VeriEQL/blob/493cbb81000205e33b0623cfd1c39106fa035fae/benchmarks/literature/literature.jsonlines). The original compatibility screen admitted 45 of its 64 Literature source rows. Those are 45 schema-plus-query tasks containing 42 distinct SQL-text pairs. The same cohort, unchanged SQL/schema interpretation, seeds and bounds were reused; excluded cases were not repaired or reintroduced to inflate coverage.

| Method | Confirmed detected tasks | Detected runs | Mismatch trials | Always-both-empty tasks | Inconclusive |
|---|---:|---:|---:|---:|---:|
| random | 14/45 | 47/180 | 1,646/11,520 | 19/45 | 0 |
| boundary | 14/45 | 52/180 | 1,624/11,520 | 19/45 | 0 |
| query_aware | 18/45 | 63/180 | 1,379/11,520 | 9/45 | 0 |

The new strategy gained five tasks but missed one task detected by both old methods: a net gain of four, **not a strict superset or uniform improvement**. It also produced fewer mismatch trials than either old method. Broader task coverage and raw mismatch frequency measure different things. Reduced emptiness is useful coverage evidence, not proof that remaining pairs are correct or equivalent.

All 23,040 fresh random/boundary records reproduced the frozen baseline exactly on original recorded fields other than elapsed time. All 162 saved external first-hit witnesses independently replayed under the original recorded source constraints and eight-row bound. Together with the original cohort, all 254 saved witnesses verified, with zero quarantines, generation/legality errors or inconclusive comparisons in this run.

This is detection yield, never recall: the external cohort does not provide a complete independently established inequivalence oracle. Seed repeats are not independent research tasks. The intervention was designed after reading this corpus, so these outcomes cannot support held-out generalization.

### External licensing and reproducibility limit

The upstream repository's [license](https://github.com/VeriEQL/VeriEQL/blob/493cbb81000205e33b0623cfd1c39106fa035fae/license.md) is CC BY-NC-SA 4.0, distinct from this project's MIT source and original synthetic fixtures. External SQL/schema records, derived witness bundles, trial records and the full external evaluation evidence are deliberately kept outside this repository pending a redistribution/license plan. This public report provides aggregate findings only; the external experiment is **not fully reproducible from this repository alone**. No license claim is made about earlier papers' material beyond the audited upstream notice. The original-only study above is the public reproducible evaluation.

## Review and remaining limits

Before this measurement, independent correctness/security review exposed and fixed CTE shadowing, exact REAL pool representation, caller-modified plan provenance, and propagation-loop deadline gaps. Regression tests cover the fixes. The original execution/comparison guardrails were not changed.

Direct/derived CTE output inference, complex NATURAL join chains, REAL literal inference, arbitrary coercions, exact SUM/AVG construction, cycles and cardinalities outside the row cap remain unsupported or conservatively skipped. A heuristic can still miss a known discrepancy, as the external regression demonstrates. Finite sampling never establishes semantic equivalence or identifies intended query correctness. Broader external validation needs a separately selected, licensed and frozen corpus with unseen outcomes.
