# Search and witness method

QueryWitness tests a finite sequence of small databases. The observable result is a successful mismatch, agreement on tested instances, or an inconclusive/incomplete outcome. The reference query is supplied by the caller, not an independently proven specification.

## Generation

`generate_instance` uses a local `random.Random(seed)` and a topological ordering of foreign-key dependencies. Parent tables are generated before children. A sampled foreign key containing any NULL is preserved, following SQLite's composite-key NULL rule. Otherwise values are selected from parent rows, or become NULL when the whole local key can be nullable and there are no parent rows. Proposed rows are retained only after full schema validation.

Both strategies use the same finite value pools unless a column supplies a domain:

- INTEGER: `-2, -1, 0, 1, 2, 10, 100`
- REAL: `-1.5, -0.5, 0.0, 0.5, 1.0, 2.0, 10.0`
- TEXT: `"", "A", "B", "0", "01", "x", "é"`

Undomained INTEGER primary keys instead use sequential positive identifiers. Nullable non-key cells normally receive NULL with probability 0.15 before foreign-key assignment.

`random` samples a target cardinality uniformly from zero through `max_rows` for each table. `boundary` changes the schedule using `seed % 8`: 0 gives an entirely empty instance, 1 raises the initial NULL probability to 0.55, and 2 or 3 requests the maximum cardinality; other residues use the ordinary cardinality rule. Repeated values arise from the small domains, not a query-aware duplicate synthesis algorithm. Non-NULL foreign-key values can be replaced by parent-key values; every completed proposal is still validated.

Each table gets at most `40 * max(1, target_rows)` row-construction attempts. Failure to fill the target is permitted; the result must still validate. `max_rows` is an upper bound, from 1 to 32 per table. This sampler does not enumerate the domain product, derive constants from SQL, solve constraints, guarantee coverage of a boundary, or characterize production data distributions.

## Search

For trial index `i`, search generates one instance with seed `seed + i`, executes reference and candidate in separate fresh in-memory databases containing that instance, and compares the returned relations under the chosen policy. It stops at the first successful mismatch, the trial limit, or the search-time check. Errors and resource limits are counted as inconclusive observations, never converted to a witness.

Search records the base/witness seed, generator version, SQLite version, schema/query hashes, policy, generation settings, execution limits, and completed/inconclusive trial counts. Search-time checks occur between trials; a trial already running can finish after the nominal deadline. Search does not cache results.

The statuses mean:

| Status | Interpretation |
| --- | --- |
| `counterexample` | A schema-valid generated instance produced two successful, different results |
| `no_counterexample_within_budget` | Every completed trial agreed and the trial budget finished; no general equivalence claim |
| `inconclusive` | Trial budget finished without a witness, but at least one comparison could not be evaluated |
| `search_budget_exhausted` | Search-time budget interrupted the trial schedule |
| `unsupported_generation` | Generator cannot handle the requested schema/configuration |

Even full agreement can miss an error because a necessary value, cardinality, data relationship, or query feature was absent. Increasing the budget may help; it does not turn this method into a proof.

## Row reduction

Reduction begins by validating and rechecking the witness. It tries complement chunk deletions within tables, increasing or decreasing granularity as appropriate. It then repeatedly scans all tables for a single-row deletion that preserves a successful mismatch. Every proposed instance must satisfy the entire schema before query evaluation.

Reduction defaults to 500 query-pair checks and 30 seconds. Invalid-schema proposals are rejected without consuming a query-pair check. It never modifies SQL, changes values, weakens keys, or performs cascading/multi-table deletion as one operation.

`row_1_minimal: true` means that the completed final scan found no schema-valid deletion of one remaining row that preserves a successful result mismatch, and no check was inconclusive. This is local minimality under this deletion operation, schema, policy, and execution limits. It is **not** a globally smallest witness. In particular, a parent and child may be removable together even though deleting the parent alone violates a foreign key.

`budget_exhausted` and `inconclusive_reduction` preserve the best retained witness but do not establish minimality. `not_a_witness` means the initial recheck failed to reproduce a successful mismatch. Chunk reduction follows the established delta-debugging family of ideas; see [related work](RELATED_WORK.md).

## Artifacts and replay

`build_witness` revalidates the retained instance and reexecutes both queries. Only a successful mismatch can become a witness. The bundle contains:

- `witness.json`: full schema, instance, original SQL, policy, execution limits, exact typed observations, comparison, search/reduction metadata, runtime versions, and checksums
- `fixture.sql`: schema and data dump followed by the supplied queries, for manual inspection; execution outside QueryWitness does not inherit its guardrails
- `report.html`: escaped, self-contained presentation of the same witness; no active query service

The JSON's SHA-256 self-check detects accidental modifications; it is not a signature or authenticity guarantee. Replay verifies that checksum and the schema, reruns both queries, and compares exact observations as well as the mismatch. `reproduced` requires both exact observations and a current mismatch. `observation_changed` can occur even if a mismatch remains, for example after a runtime or result-order change. `inconclusive` means execution was not successfully comparable.

Replay is stricter than bag equality: it checks recorded column labels, row order, and type-tagged values. An unordered SQL result can therefore trigger observation drift while preserving the original bag mismatch. Keep the recorded Python/SQLite/tool versions when exact replay matters.
