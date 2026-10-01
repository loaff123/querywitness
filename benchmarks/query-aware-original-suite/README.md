# Original query-aware development validation: publication-safe export

**Newly authored development validation. This is not external generalization evidence.**

This is a **publication-safe provenance export of the original pre-run suite**. SQL, schemas, fixture rows, exact expected bags, and oracle classifications are unchanged. Only the internal authorship identifier was replaced with accurate generic provenance. The original frozen artifacts were preserved byte-for-byte.

Original pre-run fixtures SHA-256: `ece01af307d0a3c67cdc86c7909cc2d854cac2b59be285493e325827df4755ca`

Original freeze SHA-256: `d597a35705311e0bd23c958c40d949dcd7b8b3ab0ef6bd10d127bb226354ffbb`

This export has its own `SHA256SUMS` and `FREEZE.json`, produced before generator outcomes. `semantic-equality.json` records exact semantic-content equality against the original.


These 16 original schema/query pairs and 22 hand-authored fixtures were created by the independent fixture author before running any QueryWitness generator. The only product source read was `docs/CONTRACT.md`. No generator implementation, external corpus, external evaluation results, or generated witnesses were inspected. Expected rows were authored directly in `author_fixtures.py`, then checked against Python standard-library `sqlite3` without importing QueryWitness.

## Frozen files

- `fixtures.json`: all schema/query pairs, exact hand-authored input rows and expected output bags, global and row-8 oracle classifications, per-case reasoning, provenance
- `author_fixtures.py`: the original authoring source, including literal expected bags
- `validate_sqlite.py`: independent stdlib-only schema/input/SQLite and exact bag validator
- `validation.json`: the verified initial outcomes for all 22 fixtures
- `README.md`: provenance, oracle overview, reproduction instructions, interpretation limits
- `semantic-equality.json`: exact semantic-content equality verification against the original frozen suite
- `SHA256SUMS`: SHA-256 freeze manifest for the six artifacts above
- `FREEZE.json`: export freeze time and hashes, original freeze provenance, and aggregate metadata

The validator verifies the freeze manifest by default. It creates temporary in-memory SQLite databases, checks input types/domains/nullability independently, enforces primary/unique/foreign keys with SQLite, executes both queries, and checks exact expected result bags. Numeric comparison uses exact rational values and text has no normalization. It also exhaustively checks 165 legal domain-restricted row multisets and 45 two-category row multisets through the row-8 bound, and rejects two deliberately invalid instances (excluded literal and composite-FK orphan).

## Reproduce independently

Run `python validate_sqlite.py` from this directory. Python standard library only; no product install is needed. `sha256sum -c SHA256SUMS` provides a separate integrity check. Do not rerun the authoring script or edit frozen artifacts during evaluation. Store generator results separately.

## Exact oracle overview

| ID | Subject | Global oracle | At most 8 rows/table |
|---|---|---|---|
| 01 | Uncommon literal -734921 | Different | Witness exists |
| 02 | Near INT64_MAX, 9223372036854775799 | Different | Witness exists |
| 03 | Near INT64_MIN, -9223372036854775799 | Different | Witness exists |
| 04 | Exact Unicode, decomposed/composed accent | Different | Witness exists |
| 05 | Explicit domain excludes queried literal | Equivalent | Equivalent |
| 06 | Qualified aliases and distinct integer literals | Different | Witness exists |
| 07 | Duplicate-sensitive join versus DISTINCT | Different | Witness exists |
| 08 | Correlated versus uncorrelated EXISTS | Different | Witness exists |
| 09 | Two-column NATURAL JOIN versus one-column join | Different | Witness exists |
| 10 | Composite PK/FK; missing tenant join predicate | Different | Witness exists |
| 11 | IS NULL versus equality to NULL | Different | Witness exists |
| 12 | COUNT(*) thresholds 7 versus 8 | Different | Witness exists |
| 13 | COUNT(*) thresholds 9 versus 10 | Different | Equivalent |
| 14 | Ordinary equivalent predicates, including NULL | Equivalent | Equivalent |
| 15 | Redundant join justified by non-NULL FK and PK | Equivalent | Equivalent |
| 16 | Redundant positive COUNT(*) HAVING predicate | Equivalent | Equivalent |

Exact query text, every expected bag, and every actual independently checked bag are recorded in `fixtures.json` and `validation.json`. They include duplicates and exact Unicode code points. Query output order is immaterial and column names are ignored; column counts are checked.

## Evaluation interpretation

There are 12 globally different pairs and four globally equivalent controls. Eleven different pairs have explicit witnesses at row8. Case 13 deliberately requires nine rows in one table to distinguish the queries; a row8 search must not produce a witness for it. Its nine- and ten-row fixtures are legal under the schema/engine contract, but intentionally exceed the evaluation row bound. The other two equivalent boundary fixtures for count thresholds ensure a fixture is not blindly classified by the pair's global status.

Equivalent controls must never yield a false-positive witness. A generator's failure to find a known witness is a coverage miss, not proof of equivalence. Finding any valid independently replayed mismatch suffices, even if it differs from the authored fixture. A globally equivalent label is justified by the stated semantic reasoning, not by the finite fixture check alone. The extra exhaustive checks are bounded corroboration and are not a general SQL-equivalence proof.

This suite was frozen prior to this author's generator execution (none occurred). Originality and independence refer to authorship and oracle construction, not a claim that all tested SQL patterns are novel. Do not describe these fixtures as held-out external data once product development uses them.
