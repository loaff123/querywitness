# Semantic and schema contract

This document defines what a QueryWitness comparison means. The implementation uses Python's SQLite runtime to execute SQL and SQLGlot 27.29.0 to inspect syntax. It does not transpile SQL, establish cross-engine equivalence, or prove determinism.

## Result equality

Both executions must return `ok` before a mismatch can be reported. If either is unsupported, fails, or exceeds a resource limit, comparison is `inconclusive`, even when the other succeeds. Two identical errors are also inconclusive.

Columns are compared by position. Names and aliases are ignored; differing column counts are a mismatch even when both outputs have no rows.

| Policy | Equality rule | Intended use |
| --- | --- | --- |
| `bag` (default) | Same rows with the same multiplicities, ignoring output order | Ordinary SQL result comparison |
| `set` | Same distinct rows, ignoring duplicates and order | Explicitly duplicate-insensitive requirements |
| `ordered` | Same row sequence, including duplicates | Explicitly ordered results within the restricted ordering contract |

Cell comparison uses these rules:

- NULL equals NULL for comparison of observations. This is an output-comparison rule, not the SQL predicate `NULL = NULL`.
- INTEGER and finite REAL are compared as exact rational numeric values. Thus `1` equals `1.0`; no rounding tolerance is used. An integer larger than binary64's exact range does not silently become a float.
- Positive and negative floating-point zero compare equal. Ordinary floating-point arithmetic remains SQLite's arithmetic; mathematically equivalent formulas may have different rounded results.
- TEXT is compared exactly, with no case folding or Unicode normalization. A numeric string never equals a numeric value.
- BLOB results are compared byte-for-byte. BLOB input columns are not in the schema contract.
- NaN and infinite numeric outputs are unsupported.

Witness observations preserve types independently of comparison: integers are decimal strings, reals use Python hexadecimal float strings, blobs use hexadecimal bytes, and NULL/text have explicit tags. Consequently, numerically equal INTEGER/REAL observations can compare equal while remaining different exact replay observations.

An ordered-only mismatch can have zero `reference_only_count` and `candidate_only_count`: those counts describe row multiplicities, not sequence edits.

## Ordered results

Each query must be a simple outer `SELECT` with explicit projections. `SELECT *`, compound outer queries, duplicate output aliases, and implicit ordering are excluded. An outer `ORDER BY` must cover **every projected value**, using recognized exact expressions, projection aliases, or ordinal positions. Ordering only by a key is rejected even when a person knows it uniquely determines the remaining columns. Explicit `COLLATE` clauses are excluded in every policy, avoiding case-insensitive or other collation ties between distinct compared text values.

For example, `SELECT g, x FROM t ORDER BY g, x` meets the coverage rule; `SELECT g, x FROM t ORDER BY g` does not. This conservative rule avoids ordinary unequal-row ties; it is not a general theorem about all SQLite ordering behavior. See the implementation's fail-closed checks and limitations before extending the allowed subset.

## SQL acceptance and exclusions

The parser accepts one query statement only. SQLite executes the original text. Candidate/reference SQL is never used as database setup SQL.

Within the guardrails, ordinary projections, predicates, joins, derived tables, `EXISTS`/`IN`, CTEs, grouping, aggregates, and compound queries may be used. Acceptance is the intersection of parser checks, the authorizer, the installed SQLite version, and resource limits; this list is not a promise to accept every composition of these features.

The following are rejected or reported as unsupported:

- Multiple statements, DDL/DML, `ATTACH`, `DETACH`, query-supplied `PRAGMA`, extension loading, and access to undeclared tables
- `LIMIT` and `OFFSET`, even when an ordering is present
- Window queries and scalar or unclassified subqueries
- Bare non-grouped columns in aggregate projections, `HAVING`, or aggregate `ORDER BY`
- Non-column grouping expressions and ordinals; the checker requires explicit simple grouped column references rather than inferred functional dependencies
- Subqueries in aggregate projections, `HAVING`, or aggregate `ORDER BY`
- Explicit `COLLATE` clauses; aggregate `HAVING` aliases are not resolved, so repeat the aggregate expression explicitly. Aggregate `ORDER BY` aliases resolve only when used as a direct ordering term
- Functions outside the explicit allowlist, including random/time functions, custom functions, and file/extension functions
- Bound query parameters, nonfinite outputs, NUL or surrogate code points in SQL, oversized SQL, and syntax beyond parser limits

The function allowlist is `abs`, `avg`, `char`, `coalesce`, `count`, `hex`, `ifnull`, `instr`, `length`, `like`, `likelihood`, `likely`, `lower`, `ltrim`, `max`, `min`, `nullif`, `quote`, `replace`, `round`, `rtrim`, `sign`, `substr`, `substring`, `sum`, `total`, `trim`, `typeof`, `unicode`, `unlikely`, and `upper`. Operators, including `CAST` and `CASE`, are inspected as syntax rather than ordinary function calls. Runtime availability still depends on SQLite.

Guardrails can reject harmless SQL and can have implementation bugs. A successful parse is not a proof of safety or determinism. SQLite's documented semantics are the execution reference, including [NULLs, grouping, and result ordering](https://www.sqlite.org/lang_select.html).

## Schema format

```json
{
  "tables": [
    {
      "name": "t",
      "columns": [
        {"name": "id", "type": "INTEGER", "nullable": false},
        {"name": "x", "type": "INTEGER", "domain": [-1, 0, 1, 10]}
      ],
      "primary_key": ["id"],
      "unique": [],
      "foreign_keys": []
    }
  ]
}
```

An instance is an object such as `{"t": [[1, null], [2, 10]]}`. Row cells follow the declared column order. Exactly the declared tables must appear, including empty tables. Unknown schema fields are errors.

| Item | Contract |
| --- | --- |
| Tables and columns | 1–12 tables; 1–32 columns per table |
| Identifiers | ASCII letter/underscore followed by letters/digits/underscores; 1–63 characters; no `sqlite_` prefix; case-insensitive collisions rejected |
| Input rows | At most 2,000 total across all tables |
| INTEGER | Signed 64-bit integer; booleans are rejected |
| REAL | Finite float of absolute value at most `1e100`, or integer of absolute value at most `2**53`; booleans rejected |
| TEXT | At most 4,096 UTF-8 bytes; no NUL or surrogate code points |
| Nullability | Defaults to true; every primary-key column is non-NULL regardless of its flag |
| Domains | Optional list of 1–64 non-NULL values matching the type; nullable columns may additionally contain NULL |
| Unique/FK declarations | At most 32 unique groups and 32 foreign keys per table |

No arbitrary DDL, CHECK expressions, defaults, generated columns, indexes, collations, triggers, or views are accepted in a schema definition. Domains are validated by QueryWitness rather than represented as SQL CHECK constraints in a fixture.

## Keys and relational constraints

Primary and unique keys may be composite. A unique-key row containing any NULL is exempt from uniqueness comparison. A composite foreign key containing any NULL does not require a matching parent. Non-NULL foreign keys must reference an explicitly declared primary or unique key with the same ordered column group and matching declared types. These choices follow the relevant [SQLite foreign-key rules](https://www.sqlite.org/foreignkeys.html).

For example, a child table can declare the following key, provided `tenant` and `parent_id` are its columns and `parents` declares `primary_key: ["tenant", "id"]` (or that exact unique group):

```json
{
  "columns": ["tenant", "parent_id"],
  "references": {"table": "parents", "columns": ["tenant", "id"]}
}
```

Place this object in the child table's `foreign_keys` list. Column/table references use their declared names; columns are positional within each key. The contract has no cascade actions or deferred-constraint configuration supplied by the user.

Validation and database construction support explicit instances with self-references or cycles by checking the whole instance and using deferred foreign keys. Generation requires an acyclic dependency order and returns `unsupported_generation` for cycles. It does not solve general relational constraints. Tight domains, overlapping foreign keys, or uniqueness requirements can result in fewer generated rows than the requested upper bound.

## Execution bounds

Default `ExecutionLimits`: 10,000 output rows, a 2,000,000-byte output/SQLite value bound, 1,000,000 approximate SQLite VM steps, 2 seconds per query execution, and 32,768 SQL UTF-8 bytes. Additional SQLite limits include 64 result columns, expression depth 100, 25 compound SELECT terms, zero attached databases, and zero query parameters. Parsed trees are capped at 4,096 nodes and depth 80.

The output-byte counter uses encoded string representations of returned cells; it is not an exact process-memory meter. Progress checks are cooperative, every 100 VM operations. Parsing and database setup are not controlled by that SQLite callback. These limits reduce accidental runaway work; they are not OS-level memory, CPU, or wall-clock isolation.
