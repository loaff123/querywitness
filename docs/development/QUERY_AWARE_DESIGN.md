# Query-aware generation: bounded development design

This optional strategy improves useful generated input coverage while preserving the original SQLite execution and comparison contracts. It is heuristic testing, never an equivalence procedure. External examples already inspected during development are not held-out tests.

## Contract and approach

- `random` and `boundary` generation stay byte-for-byte unchanged. A new `query_aware` search strategy compiles both original SQL texts symmetrically; SQL is not rewritten.
- A plan records exact finite effective pools for every physical column, explicit versus inferred pool origin, schema hash, both SQL hashes, canonical AST hashes, SQLGlot version, generator version and row bound. Explicit schema domains never gain values. Without a declared domain, the user opts into the documented default pools plus type-valid INTEGER literal neighbors and exact TEXT predicates by selecting this strategy. Pools have at most 64 values; truncation/skips are disclosed.
- Hints support resolvable base-table columns in simple comparisons, literal IN and BETWEEN, same-type equijoins, all common columns of simple NATURAL/USING joins and simple GROUP BY columns. Scopes use SQLGlot's pinned scope analysis. Ambiguous aliases, derived/CTE outputs, casts/coercions, REAL literal inference and unsupported forms are skipped with reasons; the executor's acceptance policy is unchanged.
- Integer neighbors are clipped to signed64. TEXT respects the existing exact UTF-8/Unicode contract. A finite default INTEGER primary-key pool includes 1 through the row limit. NULL remains a separate legal possibility.
- Deterministic schedules alternate empty, NULL-rich, random, shared-join/group duplicate-rich and distinct-rich templates. Foreign keys are filled in dependency order and every candidate is schema-validated. Failed candidates consume the finite attempt budget. Keys, foreign keys, declared domains and row limits take precedence over hints. No solver or completeness promise.
- Simple COUNT literal targets may request k-1,k,k+1 table rows only within the row bound. A conservative base-table join upper bound can disclose an unreachable count target; it does not label a query pair equivalent. Exact SUM/AVG construction is deferred.
- Search records generated trials, two query executions per trial, both-empty trials, generation attempts/rejections and early-stop status. Compilation belongs to the same wall-clock budget. Unsupported plan input fails explicitly. Existing searches keep their previous result fields/behavior.

## Verification

Original test fixtures are authored independently without reading the external corpus and frozen before generator evaluation. Unit tests are written and observed failing before implementation. Final independent correctness and security reviewers examine the changes. Every saved detected instance is replayed with independently written sqlite3/schema logic. False positives on known controls, domain violations or unreproducibility block publication.

Matched external development comparison uses the unchanged 45 admitted tasks, all four original seeds, 64 trials each, eight rows/table and unchanged execution limits. Every trial is retained after the first hit. Original baseline files, source data and wheel remain immutable. External raw corpus/derived artifacts remain outside the MIT tree; only independently authored methods and aggregate discussion may be published.

## Scope and limits

No dialect/type/schema widening, SQL rewrite, hidden domain changes, symbolic predicates, exact aggregate synthesis, general relational solver, new equivalence claim, package publication service or repository visibility/authentication changes. New inferred values make the comparison an equal trial/row/execution-budget comparison, not an equal value-domain comparison; disclose that explicitly.
