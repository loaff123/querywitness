# Query-aware finite-domain generation

Select `--strategy query_aware` to inspect both queries and use bounded, constraint-checked generation hints. `boundary` remains the default; the original `random` and `boundary` implementations are unchanged.

```sh
querywitness search schema.json reference.sql candidate.sql \
  --strategy query_aware --trials 256 --seed 20260930 --max-rows 8 --out result
```

## Values are part of the contract

An explicit column `domain` remains a hard restriction. A predicate such as `x=731` does not authorize adding 731 to a declared domain `[4,9]`.

Without a declared domain, this opt-in strategy begins with finite default INTEGER/REAL/TEXT pools, then adds type-correct INTEGER predicate literals and their immediate neighbors or exact TEXT equality/IN literals. INTEGER primary columns also start with 1 through the per-table row bound. Each effective pool has at most 64 non-NULL values. NULL is separate and is generated only when allowed. This is finite sampling inside the schema's type contract, not exhaustive search of the type.

The emitted `generation_plan.effective_domains` records every actual non-NULL pool and whether an explicit schema domain constrained it. The plan also records input hashes, canonical AST hashes, SQLGlot version, hint skips/warnings, inferred joins/groups and row bound. Save this metadata with the result. Query source text is never rewritten or transpiled.

## Supported hints, conservative skips

Hint extraction resolves base-table columns through scoped aliases, including supported correlations. It does not infer through derived/CTE outputs, casts, arbitrary expressions, ambiguous names or implicit type coercion. REAL literal inference is deferred. Unsupported query syntax fails plan construction; accepted SQL can still have unsupported hint forms, which are reported and left to ordinary exploration.

Simple same-type equality joins share possible values. Simple NATURAL joins use all common columns, not just one convenient key. Generation alternates empty, NULL-rich, duplicate-rich matching, distinct-rich matching, bounded count-target, unmatched and random schedules. These are heuristic attempts to reach useful data, not guarantees that a WHERE/HAVING predicate is satisfied. Join keys and grouping columns can compete with declared constraints; schema constraints win.

Foreign keys are assigned in dependency order, preserving legal partial NULL keys. Every candidate row is checked against the original schema, and foreign-key values retain an exact representative from the child's effective pool. Impossible key/domain combinations consume a bounded attempt budget and may yield fewer than the requested rows. Cyclic generation remains unsupported.

## Budgets and interpretation

`max_rows` is an upper bound for each table, never silently increased. COUNT targets within that bound may influence requested rows; simple static count bounds can produce informational warnings. Exact SUM/AVG synthesis and general cardinality solving are not implemented. A count warning does not establish query equivalence, nor does failure to find a witness.

Search reports generated trials, query executions, both-empty trials, attempted/rejected/accepted rows and the original search status. It stops at the first successful mismatch, while evaluation harnesses can deliberately retain every planned trial. A trial consists of one generated database and two executions. Planning checks the search deadline between scopes and propagation steps, and search checks again after generation. Compile time is inside the search wall-clock accounting; SQLite's cooperative limits remain per execution, not an operating-system sandbox.

Comparisons against the old strategies must distinguish equal trial/row/execution budgets from equal value domains. Inferred values change the searched population. Already inspected external examples are post-evaluation development evidence, even if their original baseline is frozen. New synthetic fixtures are useful regression checks, not a claim of external generalization, complete recall or state-of-the-art performance.

Direct API callers must use an unchanged plan returned by `compile_plan`. The sampler checks row targets, preferred values, exact pools and serialized manifest consistency before sampling, including the empty schedule. These consistency checks detect stale or edited plans; they are not cryptographic authentication.
