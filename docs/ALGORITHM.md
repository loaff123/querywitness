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

This section describes the unchanged default `deletion_mode='row'`.

Reduction begins by validating and rechecking the witness. It tries complement chunk deletions within tables, increasing or decreasing granularity as appropriate. It then repeatedly scans all tables for a single-row deletion that preserves a successful mismatch. Every proposed instance must satisfy the entire schema before query evaluation.

Reduction defaults to 500 query-pair checks and 30 seconds. Invalid-schema proposals are rejected without consuming a query-pair check. It never modifies SQL, changes values, weakens keys, or performs cascading/multi-table deletion as one operation.

`row_1_minimal: true` means that the completed final scan found no schema-valid deletion of one remaining row that preserves a successful result mismatch, and no check was inconclusive. This is local minimality under this deletion operation, schema, policy, and execution limits. It is **not** a globally smallest witness. In particular, a parent and child may be removable together even though deleting the parent alone violates a foreign key.

`budget_exhausted` and `inconclusive_reduction` preserve the best retained witness but do not establish minimality. `not_a_witness` means the initial recheck failed to reproduce a successful mismatch. Chunk reduction follows the established delta-debugging family of ideas; see [related work](RELATED_WORK.md).

## Foreign-key closure reduction (opt-in)

`deletion_mode='fk-closure'` changes the proposal operation. Rows retain occurrence
identities, including duplicate child rows. For every fully non-NULL FK, the
unique supporting parent has an edge to the child. An actual NULL in any component
exempts that entire FK; a nullable declaration with a non-NULL value does not.

Deleting seed rows means deleting every row reachable through these parent-to-child
edges, including the seeds. This is the unique least deletion set that contains
the seeds and leaves a schema-valid instance under the existing restricted
contract. Deletion can only break FKs by retaining a child of a deleted supporting
parent; reachability includes precisely those dependents. Iterative traversal
handles self-references, cycles, composite keys and multiple parents without
recursion. There are no SQLite cascade actions or cell rewrites.

The graph is built once and reused on surviving IDs. Unique non-NULL supporting
parents cannot switch after deletion. Every candidate still passes full schema
validation and both guarded SQL executions. An unexpected invalid closure or
load failure propagates as a consistency error, never evidence for minimality.
The opt-in controller uses the same table/chunk schedule, followed by a complete
singleton-closure scan. Any accepted final-pass deletion restarts the entire scan.
The mismatch predicate is nonmonotone: a formerly unsuccessful deletion can later
preserve a mismatch.

For parent `p(id PRIMARY KEY)` and child `c(pid REFERENCES p(id))`, one matched row
in each can be a row-minimal witness for `COUNT(*) FROM p` versus `COUNT(*)+1 FROM c`:
parent-only deletion is invalid and child-only deletion gives agreement. Deleting
the parent's closure removes both and preserves the 0-versus-1 mismatch.

`fk_closure_1_minimal: true` means every singleton closure of the final instance
was checked decisively and none preserves a mismatch, with no inconclusive check
anywhere in the reducer run. It implies the existing `row_1_minimal` property.
It does not imply subset-minimality or minimum cardinality. For two unconstrained
rows, `COUNT(*)` versus `CASE WHEN COUNT(*)=1 THEN 1 ELSE COUNT(*)+1 END` differs
at two and zero rows but agrees at one: the two-row instance is closure-1-minimal.

Defaults and caps are unchanged: 500 pair checks / 30 seconds, at most 10,000 /
300. Initial reproduction and every started candidate pair share the budget.
`query_executions` also counts completed individual calls, including a lone
reference call if time expires before its candidate. There is no hidden final
recheck. An empty successful witness can be vacuously minimal with one pair check;
a nonempty one cannot. Every accepted deletion removes at least one row. Candidate
checks are not cached or deduplicated, even for equivalent roots in a cycle.

One monotonic deadline covers validation/copying, graph/traversal, proposal
creation and query execution. Graph loops check at each row and every 256 edges;
existing schema validation, allocations and in-flight native operations are
cooperative phases that may overrun. A late pair is not accepted; the previous
witness is retained. `budget_stage` identifies the interrupted phase. Exact
candidate order is deterministic with identical decisive results and nonbinding
time bounds, not solely because a seed repeats.

New-mode statuses distinguish `not_a_witness` (successful initial agreement),
`initial_check_inconclusive`, `budget_exhausted`, `inconclusive_reduction`, and
`minimized`. `witness_reproduced` must be true before treating retained data as
an established witness. Either unfinished or inconclusive work withholds both
minimality flags. The CLI emits no bundle if initial reproduction was not established.

The graph kernel uses standard-library code only. The independent SQLite subset
oracle imports no production graph or validation implementation: it enumerates
all valid deletion supersets and intersects them. Production tests cover 96
fixtures, 1,421 seed sets, 7,730 containment checks and 1,806 surviving-state roots,
plus an iterative 2,000-row chain. These are bounded tests, not a universal proof.

## Artifacts and replay

`build_witness` revalidates the retained instance and reexecutes both queries. Only a successful mismatch can become a witness. The bundle contains:

- `witness.json`: full schema, instance, original SQL, policy, execution limits, exact typed observations, comparison, search/reduction metadata, runtime versions, and checksums
- `fixture.sql`: schema and data dump followed by the supplied queries, for manual inspection; query text is preserved verbatim with a separate-line semicolon appended after each query so trailing line comments cannot consume the delimiter. Execution outside QueryWitness does not inherit its guardrails
- `report.html`: escaped, self-contained presentation of the same witness; no active query service

The JSON's SHA-256 self-check detects accidental modifications; it is not a signature or authenticity guarantee. Replay verifies that checksum and the schema, reruns both queries, and compares exact observations as well as the mismatch. `reproduced` requires both exact observations and a current mismatch. `observation_changed` can occur even if a mismatch remains, for example after a runtime or result-order change. `inconclusive` means execution was not successfully comparable.

Replay is stricter than bag equality: it checks recorded column labels, row order, and type-tagged values. An unordered SQL result can therefore trigger observation drift while preserving the original bag mismatch. Keep the recorded Python/SQLite/tool versions when exact replay matters.


### Closure claim scope and explicit audit

Closure metadata binds `operator_version='fk-closure-v1'`,
`schema_contract='querywitness-schema-1.0'`,
`comparison_contract='querywitness-exact-v1'`, tool/SQLite/SQLGlot/Python versions,
schema, final instance, exact original SQL, policy and resolved execution limits
using canonical JSON SHA-256. Construction checks current inputs/context;
verification checks recorded context against recorded provenance so historical
artifacts remain replayable. Format version remains 1.

A valid checksum and consistent metadata do not prove a scan happened. A person
can forge a plausible minimality flag and recompute both hashes. Ordinary replay
still verifies only the exact observations and successful mismatch; for closure
artifacts it explicitly marks minimality `not_requested`. Opt-in
`replay(..., verify_minimality=True)` independently reproduces the final witness
and tests every singleton closure on that fixed instance with its own bounds.
It returns `verified`, `refuted`, `inconclusive`, `budget_exhausted`, or `unsupported`
separately from observation replay. A refutation identifies a final-instance seed
and deletion size. Earlier conservative reducer nonclaims can verify in a new run.

The audit reports recorded/current contexts and a current scope hash. Matching
final observations across runtimes does not establish matching deletion outcomes;
a successful audit establishes the property only in its current context.

Workflow accounting is explicit: reduction consumes its reported pair checks;
artifact construction runs two additional SQL executions; ordinary replay runs
two more; explicit minimality auditing adds its own counted pairs (including
initial reproduction). No stage silently increases per-query execution limits.
