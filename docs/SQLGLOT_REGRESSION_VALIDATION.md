# External regression-derived validation

The unchanged QueryWitness 0.2.0 strategies were evaluated on a frozen, source-informed
cohort adapted from three SQLGlot simplifier bug fixes. On **27 compatible pairs
already witnessed to differ**, random found **24/27**, boundary **24/27**, and
query-aware **27/27**. All methods detected differences in **all three bug clusters**.
The same pair-coverage counts occurred in every one of four seed repeats.

All **28 intended controls** had zero observed mismatches across 21,504 trials;
this is finite test agreement, **not equivalence proof**. No error or inconclusive
comparison occurred in the complete 42,240-trial run.

Query-aware's 12 paired task–seed gains represent **three related subtraction
pairs × four seeds**, not 12 independent bugs. It produced fewer mismatch trials
(3,330 versus random 3,990 and boundary 3,870) and took longer in generation
(1.709 s versus 0.520 s and 0.535 s). This evidence supports neither general
superiority nor a population-recall or speed claim.

The source cohort is external; the adaptation and evaluation are not blind or
organizationally independent. SQLGlot also supplies QueryWitness's parser.

- [Complete methods, limitations, results and reproduction instructions](../benchmarks/sqlglot-regression-v1/README.md)
- [Frozen 55-case pack](../benchmarks/sqlglot-regression-v1/cohort/evaluation-cases.json)
- [All source fixtures and actual parent/fixed outputs](../benchmarks/sqlglot-regression-v1/cohort/source-pool.json)
- [Complete admission/exclusion ledger](../benchmarks/sqlglot-regression-v1/cohort/admission-ledger.json)
- [Per-task, per-seed results in the public evidence archive](https://querywitness.lyczz.chatgpt.site/downloads/sqlglot-regression-v1-evidence.zip)
- [Public raw evidence and checksums](../benchmarks/sqlglot-regression-v1/evidence.json)

All 42,240 recorded instances were independently replayed with a standard-library
SQLite checker in original and reverse insertion order. All 11,190 mismatch
trials reproduced; 9,597 reversals changed the actual row sequence. The checker
has separate observation/comparison code but shares SQLite as the reference engine.
