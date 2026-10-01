# Query-aware generation implementation plan

> Execution: tests-first implementation, independent original fixtures, followed by correctness and security review.

**Goal:** Improve bounded SQLite witness generation with explicit, reproducible query-derived sampling pools and valid relational templates.
**Architecture:** `query_plan.py` compiles immutable hints/provenance; `query_generate.py` samples validated instances and accounting; `search.py` and CLI opt into the strategy without changing the original generators.
**Tech stack:** Python >=3.11, SQLite, pinned SQLGlot 27.29.0, stdlib unittest.
**Spec:** `QUERY_AWARE_DESIGN.md`

## Global constraints
No equivalence claims; no literal outside an explicit domain; original generators/baseline artifacts immutable; maximum 64 finite values per column; maximum 32 requested rows/table; original query/engine safety limits unchanged; external licensed data never enters the MIT tree.

## Review focus
- Correlation, alias shadowing and derived outputs must never be mistaken for unrelated base columns
- signed64 endpoints and exact Unicode must preserve type and range
- FK overwrites and uniqueness must not escape effective pools or declared constraints
- Skipped/invalid hints, failed attempts and empty output cannot be presented as coverage/proof
- Query planning and hints must be bounded and incapable of executing external SQL or changing the SQLite safety boundary

## Tasks
- [ ] Write `tests/test_query_aware.py`: finite domains, integer/text literal symmetry, signed64 clipping, exact aliases/correlation/ambiguity, natural join multi-column mapping, unsupported/coercion skips, budget diagnostics and deterministic generation/search metadata. Observe failure with absent new API.
- [ ] Implement `compile_plan(schema, reference, candidate, max_rows=8, sql_bytes=32768) -> QueryPlan` in `query_plan.py`; immutable tuple-based hints and manifest serialization; exact pools and provenance hash.
- [ ] Implement `generate_query_aware(schema, plan, seed) -> (instance, stats)` in `query_generate.py`; bounded schedules, FK order, instance validation and finite attempt statistics. Verify targeted tests and all original115 tests.
- [ ] Integrate opt-in strategy in `search.py`/`cli.py`; retain old defaults and existing result semantics, report query-aware provenance/vacuity/accounting; test CLI bundle replay and unsupported inputs.
- [ ] Freeze implementation plus original suite before matched-budget outcomes; run original suite and equal external trial/row/execution budgets in a separate licensed development directory. Preserve all trials, warnings, independent replay and baseline integrity checks. Report misses and negative results.
- [ ] Obtain independent correctness/security review; add test-first fixes for findings, rerun affected/full tests. Keep pre-fix outcomes distinct if implementation changes.
- [ ] Build wheel/sdist, installed-package tests, static explorer tests, source/docs/license audit, update generic docs/demo and same Library artifact identity if appropriate. Publish authorized source to existing private repository, verify exact remote commit and final four-job CI; do not alter visibility/auth or pending unrelated browser tabs.
