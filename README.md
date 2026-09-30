# QueryWitness

Find a small SQLite database on which two queries return different answers, then save, inspect, and replay that counterexample.

QueryWitness is a local Python CLI and library for bounded differential testing of SQL. It generates schema-valid databases, compares successful query results, and reduces a mismatch by deleting rows while preserving declared constraints. It is useful when a rewrite passes an ordinary example but may mishandle duplicates, NULLs, joins, or aggregation.

**No counterexample within a budget is not a proof of equivalence.** A witness establishes an observed difference under the recorded schema, SQLite runtime, and comparison policy. It does not establish which query matches your intended requirement.

[Open the public counterexample explorer](https://querywitness.lyczz.chatgpt.site) to inspect the recorded examples and download exact replay bundles. The static demo executes no uploaded SQL.

## Quick start

Requires Python 3.11 or newer, its SQLite module, and `sqlglot==27.29.0`. Install from a checkout; no PyPI release is assumed.

```sh
git clone https://github.com/loaff123/querywitness.git
cd querywitness
python -m venv .venv
# POSIX shell:
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install .

querywitness demo count_nullable --out demo-count
querywitness replay demo-count/witness.json
querywitness catalog --validate
```

Open `demo-count/report.html` locally to inspect the queries, tables, typed observations, and reduction record. The directory also contains a portable `witness.json` and a `fixture.sql`. Output directories must not already exist.

The built-in COUNT example distinguishes `SELECT COUNT(x) FROM t` from `SELECT COUNT(*) FROM t`: a row with `x = NULL` is enough. The demo starts from the catalog's revealing fixture; it is not a search-coverage measurement.

For your own queries, put the schema contract in JSON and each query in a UTF-8 file:

```sh
querywitness search schema.json reference.sql candidate.sql \
  --trials 100 --seed 0 --strategy boundary --policy bag --out my-witness
```

Exit code **1 means a counterexample was found** for `search`; it is an expected test failure, not a crash. Exit 0 with `no_counterexample_within_budget` means only that the completed tests agreed. Check the JSON status, especially exit 3 for inconclusive or incomplete searches. See the [CLI reference](docs/CLI.md).

## What it does

- Enforces an explicit JSON contract for INTEGER, REAL, and TEXT columns, nullability, finite domains, primary keys, unique keys, and foreign keys, including composite keys
- Generates small instances with paired, deterministic random and boundary-biased strategies
- Defaults to bag comparison, preserving duplicates; also offers explicit set and ordered policies
- Keeps SQL errors, unsupported syntax, and resource exhaustion separate from output mismatches
- Reduces successful mismatches with schema-valid row deletion and reports whether row-1-minimality was established
- Saves exact typed observations, query/data checksums, configuration, runtime information, a SQL fixture, and an escaped standalone HTML report

Numeric comparison is exact and tolerance-free: INTEGER `1` and REAL `1.0` agree, but TEXT `'1'` does not. Artifact observations retain their distinct type tags. Ordered comparison requires explicit projections and an `ORDER BY` covering every projected value. Read the [semantic contract](docs/CONTRACT.md) before interpreting results.

## Scope and safety

SQLite is the only execution engine. The accepted SQL subset is intentionally narrower than SQLite: no modification statements, arbitrary schema SQL, `LIMIT`/`OFFSET`, windows, scalar subqueries, unapproved functions, or ambiguous bare aggregate columns. Some otherwise valid SQL is rejected. Cyclic foreign keys can be validated and replayed as explicit instances, but the generator does not support them.

Query execution uses fresh in-memory databases, a SQLite authorizer, read-only query mode, and bounded outputs and work. **This is a local testing tool, not an internet-facing or multi-tenant hostile-SQL sandbox.** Reports and bundles contain supplied SQL and data. Review them before sharing. See [SECURITY.md](SECURITY.md).

## Evaluation and research use

The release includes **12 original synthetic semantic families**, each with one deliberately incorrect mutant, an equivalent control, a masking fixture, and a revealing fixture with independently specified expected outputs. They are a small regression catalog, not a representative workload sample, expert-reviewed dataset, or LLM benchmark. Seed repetitions do not create new independent tasks.

The experiment runner compares random and boundary generation with identical trial budgets and seed schedules, retaining every trial rather than stopping at the first hit. Actual results, including negatives, belong in the [versioned evaluation report](benchmarks/v1/REPORT.md), with raw records and a manifest beside it. No results are inferred from the design of the tool.

The recorded v1 run used 16 trials and 8 seed repeats per family/method/variant, for 6,144 matched-budget comparisons. Random detected 93/96 mutant family-runs; boundary detected 96/96. Both detected 12/12 distinct families, with zero control mismatches and zero inconclusive comparisons in this run. These are **development-set results**: the generator was debugged using these 12 families. The separate, intentionally masking benign fixtures detected 0/12.

**The earlier failure is retained:** an initial run missed `not_in_null` because foreign-key assignment erased legal NULL keys. The generator was corrected, and the complete [pre-fix run and source snapshot](benchmarks/ablation-forced-fk/REPORT.md) remain available. The final random strategy still missed `empty_aggregate` in 3/8 repeats. See the [negative-result and development-set analysis](docs/DATASET_CARD.md#recorded-v1-results).

A separate [five-case frozen validation](benchmarks/holdout/REPORT.md) completed 640 comparisons and detected all five mutants with each method, with zero control mismatches or inconclusive comparisons. Its cases and budgets were frozen before execution, but its author had read the generator and catalog. It is a small internal validation split, not blind or external validation.

```sh
querywitness benchmark --out my-evaluation --trials 16 --repeats 8 --seed 20260930
```

See the [dataset and evaluation card](docs/DATASET_CARD.md), [reproduction protocol](docs/REPRODUCIBILITY.md), and [related-work matrix](docs/RELATED_WORK.md). Test database generation, query mutation testing, and delta debugging have substantial prior art. QueryWitness makes no first-of-kind, state-of-the-art, formal verification, or novelty guarantee.

## Documentation

- [Command line](docs/CLI.md) and [Python API](docs/API.md)
- [SQL, schema, and comparison contract](docs/CONTRACT.md)
- [Generation, search, reduction, and replay](docs/ALGORITHM.md)
- [Dataset and evaluation card](docs/DATASET_CARD.md)
- [Reproducibility and measurement protocol](docs/REPRODUCIBILITY.md)
- [Related work and contribution boundaries](docs/RELATED_WORK.md)
- [Contributing](CONTRIBUTING.md), [security](SECURITY.md), and [citation metadata](CITATION.cff)

The source and original synthetic catalog are MIT-licensed; see [LICENSE](LICENSE). Citation metadata identifies this software release, not a peer-reviewed paper or a registered DOI.
