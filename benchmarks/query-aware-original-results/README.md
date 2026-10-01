# Original query-aware development evaluation: complete evidence

This directory contains only the newly authored original validation suite's outcomes. The 16 case objects are byte-semantic-identical to the independently frozen original suite in `../query-aware-original-suite/`; only top-level internal provenance/path labels were sanitized in that public suite. See `PROVENANCE.json` and the suite's semantic-equality record.

## Result

Each method received four repeats × 64 trials × 16 cases = 4,096 trials, with starting seeds 20260930, 20261930, 20262930, 20263930 and at most eight accepted rows per table. All 12,288 trial records are retained, including after first hits. Effective value domains, accepted row counts, generation attempts, and wall-clock work are deliberately not equal across strategies.

| Method | Detected tasks / 16 | Known row8-distinguishable cases / 11 | Detected repeats / 64 | Mismatch trials | Both-empty trials | Inconclusive |
|---|---:|---:|---:|---:|---:|---:|
| random | 6 | 6 | 24 | 647 | 2,460 | 0 |
| boundary | 6 | 6 | 24 | 668 | 2,528 | 0 |
| query_aware | 11 | 11 | 44 | 998 | 2,122 | 0 |

All 92 saved first witnesses passed independent raw-schema, exact typed-bag, saved-observation, explicit-domain and row-bound checks, including reverse insertion order. No method reported a mismatch on the four globally equivalent controls or the additional case that becomes distinguishable only beyond row8. All generation/instance-validity/resource-limit errors were zero in the recorded run.

These are original DEVELOPMENT results, not a representative workload, held-out generalization, an equivalence proof, or a speed benchmark. Case 13's nine-row hand-authored witness intentionally exceeds this search bound. The first three rare-integer cases are also detectable through the zero-valued candidate side; task detection alone does not establish coverage of every rare input value. The independent checker shares SQLite with the product.

## Reproduce

Install the project and its pinned dependencies, then from the repository root:

    python scripts/evaluate_query_aware_original.py verify
    python scripts/evaluate_query_aware_original.py run --output /tmp/querywitness-original-reproduction --compare-recorded benchmarks/query-aware-original-results

The output directory must be new. Python optimized mode (`-O`) is rejected because the frozen independent oracle uses assertions. The runner uses the exact public frozen suite, compiles and saves a plan per case, records every trial, validates all saved witnesses, and optionally compares every recorded trial field except timing against these records. A failure preserves partial output. Machine-dependent timings are retained but not required to match. Reproduction uses source files from this repository and the dependencies in the active Python environment.

## Inspect and verify

- `config.json`: exact three-method/four-repeat/64-trial/row8/SQLite-limit configuration
- `runtime.json`: package and engine versions, with machine-specific import paths omitted
- `original/*/plan.json`: exact per-case plans and compilation timing
- `original/*/trials.jsonl.gz`: all trials, losslessly compressed with gzip mtime zero and blank filename
- `original/*/*-witness.json`: exact recorded first-witness bytes
- `original/*/summary.json`: exact per-case summaries
- `summary.json`: only this cohort's summary
- `witness-checks.json`: all 92 independent witness reports
- `witness-check-summary.json`: exact verification denominator
- `PROVENANCE.json`: frozen source identity, original case semantic digest, and copy/sanitization rules
- `MANIFEST.json`: every included file's SHA-256/byte count; compressed logs additionally include decompressed SHA-256, byte count, and record count

The reproducibility reader accepts raw `.jsonl` and compressed `.jsonl.gz` transparently. Every compressed log decompresses to the exact bytes of the original recorded log; no trial, time field, status, instance hash, statistic or error record was dropped to reduce size. Plans, per-case summaries, and first-witness JSON were copied byte for byte. Aggregate summaries/checks were filtered to this cohort; runtime paths were omitted.
