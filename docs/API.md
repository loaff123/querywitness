# Python API

The public package is version 0.1.0. The module-level functions below are the current small API; internal names and result dictionaries may evolve. Pin the package, parser, and runtime for reproducible research. There is no network service API.

## Minimal search

```python
from querywitness.schema import Schema
from querywitness.search import search

schema = Schema.from_dict({
    "tables": [{
        "name": "t",
        "columns": [{"name": "x", "type": "INTEGER"}],
    }]
})

result = search(
    schema,
    "SELECT COUNT(x) FROM t",
    "SELECT COUNT(*) FROM t",
    trials=32,
    seed=0,
    strategy="boundary",
    policy="bag",
)
print(result["status"])
```

The return value is a dictionary, with an `instance` only when a counterexample is found. Read [status meanings](ALGORITHM.md#search) rather than treating every non-counterexample return as equivalence.

## Schema and execution

```python
from querywitness.engine import ExecutionLimits, execute
from querywitness.compare import compare_results

limits = ExecutionLimits(rows=1000, bytes=200000, vm_steps=100000, seconds=1.0)
data = {"t": [[None], [1], [1]]}
schema.validate_instance(data)
reference = execute(schema, data, "SELECT x FROM t", limits)
candidate = execute(schema, data, "SELECT DISTINCT x FROM t", limits)
comparison = compare_results(reference, candidate, policy="bag")
```

- `Schema.from_dict(definition)` validates a definition; `schema.to_dict()` emits the normalized contract
- `schema.validate_instance(data)` returns normally for a valid instance and raises `SchemaError` otherwise
- `execute(schema, data, sql, limits=None, *, policy='bag')` returns an immutable `QueryResult` with `status`, `columns`, `rows`, and `detail`
- `compare_results(reference, candidate, policy='bag')` returns `agreement`, `mismatch`, or `inconclusive` plus counts/status details

The comparator compares already-produced results; it cannot inspect SQL or certify its ordering. For ordered use, pass `policy='ordered'` to execution as well as comparison, or use `search`, which forwards the policy. Directly constructing a `QueryResult` bypasses execution guardrails.

Schema/configuration errors can raise exceptions before query execution. SQL rejection/errors/resource exhaustion are represented in `QueryResult`; do not turn them into result rows or mismatches.

## Generation and reduction

```python
from querywitness.generate import generate_instance
from querywitness.reduce import minimize

instance = generate_instance(schema, seed=1, strategy="boundary", max_rows=8)

if result["status"] == "counterexample":
    reduction = minimize(
        schema, result["instance"],
        "SELECT COUNT(x) FROM t", "SELECT COUNT(*) FROM t",
        policy="bag", max_checks=500, seconds=30.0,
    )
```

`search(schema, reference, candidate, *, trials=100, seed=0, strategy='boundary', policy='bag', limits=None, max_rows=8, seconds=60.0)` performs bounded search. The standalone generator defaults to `strategy='random'`; search defaults to `boundary`.

`minimize(schema, instance, reference, candidate, policy='bag', max_checks=500, seconds=30.0, limits=None, *, deletion_mode='row')` returns the retained `instance`, reduction status/check count, and `row_1_minimal`. A reduction budget allows 1–10,000 checks and positive finite time up to 300 seconds. Read the guarantee before calling the result a minimal witness.

## Witnesses

```python
from querywitness.artifacts import build_witness, load_json, replay, write_bundle

if result["status"] == "counterexample":
    witness = build_witness(
        schema, reduction["instance"],
        "SELECT COUNT(x) FROM t", "SELECT COUNT(*) FROM t",
        policy="bag",
        search={k: v for k, v in result.items() if k != "instance"},
        reduction={k: v for k, v in reduction.items() if k != "instance"},
    )
    write_bundle(witness, "new-witness-directory")
    replay_result = replay(load_json("new-witness-directory/witness.json"))
```

`build_witness(..., *, limits=None, search=None, reduction=None)` always validates and reexecutes; it raises if the instance does not produce a successful mismatch. `write_bundle(value, destination)` requires a new directory. `verify_witness(value)` validates the checksum and contract but does not execute queries; `replay(value)` does execute them. A self-checksum does not authenticate an untrusted sender.

## Catalog and evaluation

`querywitness.catalog.load_catalog()` reads the bundled JSON catalog. `validate_catalog()` returns a dictionary with family count, fixture execution count, and failures.

`querywitness.benchmark.run_benchmark(destination, *, trials=16, repeats=8, seed=20260930, max_rows=8, family_ids=None)` writes evaluation artifacts and returns the summary. `family_ids` is an optional collection of catalog IDs. The benchmark uses bag comparison and default execution limits. See [reproduction and equal-budget accounting](REPRODUCIBILITY.md).

## Query-aware generation

```python
from querywitness.query_plan import compile_plan
from querywitness.query_generate import generate_query_aware

plan = compile_plan(schema, reference_sql, candidate_sql, max_rows=8)
instance, statistics = generate_query_aware(schema, plan, seed=19)
manifest = plan.to_dict()
```

Use `search(..., strategy="query_aware")` for ordinary searches. Keep the original schema and plan together; mismatched schemas are rejected. Plans disclose exact finite pools and unsupported hints. See [the contract and limitations](QUERY_AWARE.md).


## Opt-in foreign-key closure reduction

`minimize(..., deletion_mode='fk-closure')` proposes the least set of row
occurrences that must be removed with the seed rows to preserve declared FKs.
The default remains `deletion_mode='row'`; other values raise `ValueError`.
Neither mode changes SQL or cell values. See [the precise operation](ALGORITHM.md#foreign-key-closure-reduction-opt-in).

```python
reduction = minimize(schema, data, reference_sql, candidate_sql,
                     deletion_mode="fk-closure", max_checks=500, seconds=30.0)
if reduction["witness_reproduced"]:
    witness = build_witness(
        schema, reduction["instance"], reference_sql, candidate_sql,
        reduction={k: v for k, v in reduction.items() if k != "instance"},
    )
```

Pass the same policy and resolved `ExecutionLimits` to reduction and construction.
`build_witness` rejects a closure scope/context that belongs to different final
inputs or runtime. It separately executes two queries to construct the artifact.

`fk_closure_1_minimal` implies schema-relative `row_1_minimal`, never global minimum
cardinality. `witness_reproduced` distinguishes an established retained witness
from an initial inconclusive check or a timeout before reproduction. Inspect
`status`, `checks`, `query_executions`, `inconclusive_checks`, `budget_stage`, and
`final_scan_*` for incomplete work. The reducer counts initial reproduction and
every started candidate pair, with no unbudgeted final recheck. Bounds are
cooperative, including setup/traversal; an in-flight operation can overrun them.

```python
result = replay(witness, verify_minimality=True,
                minimality_checks=500, minimality_seconds=30.0)
print(result["status"])  # ordinary exact-observation replay
print(result["minimality_verification"]["status"])
```

The separate audit returns `verified`, `refuted`, `inconclusive`,
`budget_exhausted`, or `unsupported`; a refuting singleton closure includes
`seed: {table, index}` and `removed_rows`. It never modifies the witness. A
reproduced mismatch alone does not verify minimality. Ordinary replay of a closure
artifact records `minimality_verification: {status: 'not_requested'}`; old artifacts
keep their original ordinary replay result shape.

The direct `querywitness.fk_closure.check_fk_closure_minimality(schema, instance,
reference, candidate, policy='bag', *, limits, max_checks=500, seconds=30.0)` API
performs this fixed-instance audit without the artifact replay calls. Successful
initial agreement returns `refuted` with `reason='not_a_witness'`. Both budget
APIs require 1–10,000 checks and finite positive seconds at most 300; booleans
are not budgets. Audit query limits remain those recorded in the artifact.

The audit reports recorded/current operation and runtime contexts, whether they
changed, and a SHA-256 binding of its current scope. A current-runtime audit does
not prove what another runtime would do on every deletion candidate.
