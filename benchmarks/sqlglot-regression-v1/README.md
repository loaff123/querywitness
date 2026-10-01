# SQLGlot regression-derived validation v1

This is a **source-informed, bounded external regression cohort**, evaluated with
unchanged QueryWitness 0.2.0. It is not blinded, organizationally independent,
a representative workload sample or a population-recall estimate. SQLGlot is
both the fixture source and QueryWitness's parser, which introduces coupling.

## Recorded result

| Method | Known-different pairs found | Task–seed budgets with a witness | Intended controls with a mismatch | Bug clusters detected |
|---|---:|---:|---:|---:|
| random | 24/27 | 96/108 | 0/28 | 3/3 |
| boundary | 24/27 | 96/108 | 0/28 | 3/3 |
| query_aware | 27/27 | 108/108 | 0/28 | 3/3 |

Each of four repeats had the same pair-coverage result. The additional detections
are `subtraction_02:parent`, `subtraction_07:parent`, and `subtraction_13:parent`.
The paired comparison therefore has **12 task–seed gains and zero losses**:
three closely related pairs × four repeats, **not 12 independent bugs**. Each
baseline found 10/13 subtraction pairs and all six COALESCE and eight conditional
pairs; query-aware found all 27. All methods already covered every bug cluster.

The baseline INTEGER pool is `[-2,-1,0,1,2,10,100]`, with NULL sampled separately.
The three misses differ only at x = 3 or 7, neither of which is in that pool.
Actual query-aware plans add 6, 7 and 8 around the candidate literal 7; 7 exposes
the difference. They do not add 3. This illustrates literal-neighbor sampling,
not arithmetic solving. No generator was changed or tuned after this finding.

| Method | Mismatch trials | Agreement trials | Errors/inconclusive | Both empty | Generation seconds | Product-trial seconds |
|---|---:|---:|---:|---:|---:|---:|
| random | 3,990 | 10,090 | 0 | 1,155 | 0.520 | 13.117 |
| boundary | 3,870 | 10,210 | 0 | 2,310 | 0.535 | 12.967 |
| query_aware | 3,330 | 10,750 | 0 | 2,377 | 1.709 | 14.486 |

Query-aware covered more pairs but produced fewer mismatch trials and took
longer in generation. Timing is a single-runtime, fixed-order observation,
not a counterbalanced performance study. Product-trial time includes generation,
input checking, guarded SQL execution, comparison and bookkeeping, excluding log
writes. Planning added 0.069 s; total run wall time including logging was 45.858 s.
Replay/export work is outside those benchmark times. No general superiority,
speed or cost claim follows.

All 21,504 trials on **28 intended controls** agreed, with zero observed
contradictions. This does not prove equivalence or estimate a population
false-positive rate. A witness shows a difference, not which query is correct.

## Sources and admission, fixed before generation

QueryWitness product pin:
[`4a9bfc55e9e6d2b0e02257a0c01fe0131317d8d9`](https://github.com/loaff123/querywitness/tree/4a9bfc55e9e6d2b0e02257a0c01fe0131317d8d9).
All newly added fixture pairs in `tests/fixtures/optimizer/simplify.sql` were
included from these exact SQLGlot parent/fix comparisons:

| Cluster | Parent | Fix | New fixtures |
|---|---|---|---:|
| Subtraction | `eba0b304f179484ad7b5e0ae3467128abadae2f9` | [e16a179](https://github.com/tobymao/sqlglot/commit/e16a179a4226e7049e050f5cc86d63ace9c60b40) | 13 |
| COALESCE operand order | `1d753d72c6e81e39cfc7160af33673314d4d600e` | [c9ad903](https://github.com/tobymao/sqlglot/commit/c9ad903e7553543686472e5babf3c18e4e7dbc7b) | 6 |
| Conditional precedence | `a070393d34aae2fda84f70896a3c3d90820720b5` | [06c7b3d](https://github.com/tobymao/sqlglot/commit/06c7b3dd7b656ff5ed80337ee668cf58318e002b) | 13 |

The pinned upstream fixture loader, `simplify` and `parse_and_optimize` helpers
produced the **real pre-fix outputs**. The helpers' function bodies and schema
expression were extracted unchanged from their AST, avoiding unrelated test
dependencies. All 32 fixed outputs matched their upstream expected expression.
[The complete source pool](cohort/source-pool.json) preserves expressions, outputs,
fixture indices, line anchors, helper hashes and source links.

A mechanical wrapper, `SELECT (<unchanged expression>) AS result FROM regression_input`,
preserves the expression's operators, literals and parentheses. All identifiers
become alphabetically ordered nullable INTEGER columns, without finite schema
domains or key constraints. This restricted INTEGER/SQLite interpretation is an
adaptation, not a claim about every upstream SQL dialect or type.

The full 32-fixture pool gives 64 detection/control role pairs. Four IF fixtures
(`conditional_precedence_07`, `_08`, `_09`, `_11`) are unsupported by the unchanged
QueryWitness allowlist: all eight role pairs remain in the pool/ledger but are
excluded. SQLite itself supported IF in the recorded runtime; no convenient
function rewrite was used. `conditional_precedence_06:parent` is the same pair
as its intended control and is retained as an alias, yielding **55 unique compatible
tasks: 27 witnessed different and 28 intended controls**. The complete
[admission ledger](cohort/admission-ledger.json) retains exclusions and aliases.
No task was added, removed or tuned after generation outcomes.

Before generation, an independent standard-library SQLite checker used a fixed
diagnostic domain `[NULL,-8,-3,-2,-1,0,1,2,3,4,5,8]`. It tested an empty table and
all singleton Cartesian combinations, retaining all 113,012 diagnostic records.
31 raw parent pairs had singleton witnesses; one was unresolved and duplicate
with its intended control. After compatibility exclusions, 27 remained.
All intended controls had finite-domain agreement, not proof. Duplicate-row
multiplicity checks at 2 and 8 rows are not informative order-invariance tests.
[Oracle results and all raw diagnostics](https://querywitness.lyczz.chatgpt.site/downloads/sqlglot-regression-v1-evidence.zip) are retained in the public data archive.
The diagnostic domain was never supplied to QueryWitness's generators.

### Duplicate screening and limits

Before outcomes, unordered pairs were compared against the exact product pin's
12 catalog cases (24 role pairs), five validation cases (10 role pairs), 16
query-aware original pairs, and all 64 rows of the prior VeriEQL Literature
source at commit `493cbb81000205e33b0623cfd1c39106fa035fae`.
The 64 Literature rows have 61 distinct exact pairs; this broader check does not
reconstruct the historical 45-case admission decisions.

Exact text, SQLGlot-27.29.0 formatting ASTs, shared global textual identifier
renaming and typed-literal abstraction found no prior overlap. Renaming is not
scope resolution or semantic equivalence. Of 114 prior records, 111 parsed;
three retained VeriEQL parse failures were structurally inspected as union or
multi-relation grouped/join queries, unlike these scalar-expression pairs.
Ranked structural neighbors were also reviewed, without claiming formal
near-duplicate completeness. These are source-level screening observations,
not proof of research novelty. Restricted VeriEQL SQL/schema is not distributed.

## Frozen protocol and complete evidence

- Python 3.12.14; SQLite 3.53.1; SQLGlot parser **27.29.0**; QueryWitness **0.2.0**
- Methods, in fixed order: random, boundary, query_aware
- Start seeds: **20260930, 20261930, 20262930, 20263930**
- Trial seed = start seed + zero-based trial index
- **64 trials × 4 seeds × 3 methods × 55 tasks = 42,240**, all retained after first hit
- Maximum 8 input rows; bag comparison
- Limits: 10,000 output rows, 2,000,000 bytes, 1,000,000 VM steps,
  2.0 s per SQL execution, 32,768 SQL bytes, and all unchanged product guards
- Capture: complete rows, typed observations, errors, both-empty flags, stage
  timing, actual query-aware plans and baseline/effective value pools

The cohort was frozen locally at 2026-10-01T17:02:07Z. Execution source and inputs
were hashed before the first generator call at 17:11:17Z. This was a local
commitment, **not public preregistration**. [Provenance](provenance.json) identifies
the original archive/manifest hashes and exactly copied public files.

[Download the complete public data-only evidence archive](https://querywitness.lyczz.chatgpt.site/downloads/sqlglot-regression-v1-evidence.zip)
and verify the SHA-256 and size in [evidence.json](evidence.json). It contains all
42,240 trial records, all 42,240 independent replay records, 55 plans, 300 native
first-hit witnesses, compact results, the entire source/oracle pool and all
113,012 diagnostic records. Its internal `SHA256SUMS` hashes every other member.
The original full archives remain separately retained; their hashes are not
presented as publicly accessible download links.

Every generated instance was checked against the raw schema and independently
replayed in original/reversed insertion order without importing QueryWitness or
SQLGlot. All forward typed observations matched; all reverse bags and comparison
outcomes matched. All **11,190** mismatch trials reproduced; **9,597** witness
reversals changed the row sequence, and **9,665** witness instances had distinct
rows. No contradictory control, invalid instance, replay error or omitted/duplicate
trial key occurred. The checker shares SQLite as its semantic reference: this is
separate code, not a second database engine or organization.

[Summary](results/summary.json), [every task/seed result in the data archive](https://querywitness.lyczz.chatgpt.site/downloads/sqlglot-regression-v1-evidence.zip),
[observed values](results/observed-values.json) and
[replay summary](results/independent-replay-summary.json) are directly inspectable.
The 300 native first-hit artifacts are unminimized recorded instances, not new
searches. Their product export/replay validation performed 602 additional SQL
executions and zero generator calls, outside all reported benchmark counts/times.

## Reproduce the same frozen experiment

Use a fresh clone with full Git history, Python 3.11+ and `sqlglot==27.29.0`.
For exact recorded runtime reproduction, use Python 3.12.14 and SQLite 3.53.1;
other SQLite versions must be reported separately. Install dependencies using
your normal trusted package workflow before running these commands.

```sh
python -m pip install 'sqlglot==27.29.0'
python benchmarks/sqlglot-regression-v1/reproduce.py --out ../sqlglot-reproduction --run
```

The wrapper verifies this public package, extracts and hashes all 416 product
files from the **recorded pin**, copies the unchanged case pack, writes a **new**
execution commitment before generation, runs every trial, independently replays
all instances, and recomputes results. It refuses an existing output directory.
A shallow checkout may need `git fetch --unshallow` first. No dependency is
silently installed and no network request is made by the wrapper.

The public evaluator changes only original commit-time input locations and
attribution metadata; `ProductRuntime`, `run_repeat`, `baseline_pool` and `run`
retain the frozen function bodies. Replay/checker and post-run metric computation
are copied unchanged. New manifests/timings will differ; compare trial keys,
instances, typed outcomes, statuses and coverage, not compressed bytes or clocks.
Do not discard errors or change cases to force recorded counts on a new runtime.

To reproduce the source extraction, first clone the official SQLGlot repository
with its history, then run:

```sh
git clone https://github.com/tobymao/sqlglot.git ../sqlglot-source
python benchmarks/sqlglot-regression-v1/reproduce_sources.py \
  --sqlglot-repo ../sqlglot-source --out ../sqlglot-source-check
```

This reruns exact parent/fix helpers and requires byte-identical `source-pool.json`.
It does not run a QueryWitness generator. For an individual saved example:

```sh
querywitness replay benchmarks/sqlglot-regression-v1/results/example-witness.json
```

The license notices and source pins are in [NOTICE.md](NOTICE.md) and
[LICENSE.SQLGLOT](LICENSE.SQLGLOT). This package introduces no product behavior
change and no package version bump.
