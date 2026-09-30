# Security and privacy

## Intended use

QueryWitness is a bounded local SQL-testing tool for a developer-controlled environment. It is **not an internet-facing, multi-user, or hostile-code sandbox**. Do not expose its Python API or CLI directly as an uploaded-SQL execution service. It runs SQLite and the parser in the same process, without an OS/container isolation boundary.

Use a disposable environment with no sensitive files, credentials, production database access, or unnecessary network permissions when examining untrusted inputs. Review queries and artifacts before running them. `fixture.sql` is a convenience export: opening it in an ordinary SQL client does not preserve QueryWitness's guards.

## Implemented defenses

- Schema creation comes from validated JSON definitions; identifiers are quoted and data inserts use parameters
- Each query runs against a fresh in-memory database containing the supplied validated instance
- SQLite query-only mode and an allowlist authorizer restrict queries to reads of declared tables and approved functions
- Attachment, mutation, query-supplied pragmas, extension/file functions, and unapproved functions are denied
- Parser checks exclude selected nondeterministic/ambiguous constructs; SQL, syntax-tree, SQLite VM work, elapsed execution, value, output, and schema bounds limit accidental abuse
- Bundle directories are created exclusively, and existing output paths are refused
- Reports HTML-escape supplied values/SQL and use a restrictive content security policy without scripts or external resources
- JSON loading rejects oversized input, duplicate keys, and nonfinite numeric literals

See the precise [contract](docs/CONTRACT.md). The [SQLite authorizer](https://www.sqlite.org/c3ref/set_authorizer.html) is an operation-control mechanism, not process isolation. SQLite's own [security guidance](https://www.sqlite.org/security.html) discusses additional precautions for untrusted SQL.

## Residual risks

Native-library or parser vulnerabilities, expensive parsing/setup, cooperative-timeout gaps, allocator behavior, and unexpected SQLite semantics remain possible. Resource counters are not hard OS CPU/memory quotas. No security audit or penetration-test certification is claimed. Dependency upgrades require regression review because parsing and SQL behavior are part of the contract.

Checksums are unkeyed integrity checks. Anyone who edits a witness can recompute one; a valid checksum is neither a trusted signature nor permission to execute its SQL. A partially failed output operation may leave a directory behind; inspect and choose a fresh destination rather than trusting its completeness.

## Data handling

The CLI performs local computation and does not require an API key or send query/data telemetry. Package installation may contact the configured package index. Deliberately publishing or uploading an output file shares its contents with that destination.

Witness JSON, HTML reports, SQL fixtures, stdout, captured logs, and custom benchmark outputs can contain schema names, full SQL text, literal values, input rows, and results. Hashes do not anonymize those files. Review all outputs before adding them to an issue, repository, website, or message. Prefer synthetic reproductions. Do not put secrets or production personal data into public artifacts.

## Reporting an issue

Use the repository's private vulnerability-reporting option under Security if it is available. If no private route is offered, open a minimal issue asking for a private contact route without exploit details or sensitive data. Do not assume a private channel exists or post credentials, private rows, or a weaponized exploit publicly.

For a non-sensitive semantic bug, include package/Python/SQLite/parser versions, policy and limits, a minimal synthetic schema/fixture, expected versus actual behavior, and reproduction steps. A passing test, a current patch, or lack of a reported vulnerability is not a security guarantee. The project makes no guaranteed response-time or long-term-support commitment.
