# Command line reference

The installed `querywitness` command and `python -m querywitness` have the same interface. Run `querywitness --help` or a subcommand with `--help` for the installed version. Commands print machine-readable JSON to stdout; errors go to stderr. Help and version output are text.

## Search

```text
querywitness search SCHEMA REFERENCE CANDIDATE
  [--out DIR] [--trials 100] [--seed 0]
  [--strategy boundary|random] [--policy bag|set|ordered]
  [--max-rows 8] [--seconds 60] [--no-minimize]
```

`SCHEMA` is a JSON schema contract; `REFERENCE` and `CANDIDATE` are UTF-8 SQL file paths, not inline SQL. Search uses `boundary` and `bag` by default. `--trials` accepts 1–10,000; `--max-rows` accepts 1–32; `--seconds` accepts a finite positive value up to 3,600. The seed is a nonnegative integer small enough for the entire trial sequence to remain in the supported 63-bit range.

With `--out`, search creates a new directory and writes `result.json`. A counterexample also yields `witness.json`, `fixture.sql`, and `report.html`. The mismatch is reduced by default; `--no-minimize` retains the initial generated witness. `result.json` retains the original generated instance and its observations, while `witness.json` contains the retained reduced instance; reduction metadata connects the two. Per-query limits and reduction budgets use library defaults; this CLI does not expose a flag for every library limit. Reduction has a separate 500-check/30-second budget in addition to the search budget.

The output location must not exist. Choose a new destination for a rerun rather than deleting evidence from the previous run. Without `--out`, inspect stdout for the search result; no portable bundle is written.

## Demo

```sh
querywitness demo count_nullable --out demo-count
```

The family argument defaults to `count_nullable`. Demo uses the selected catalog family's known revealing fixture, reduces it, and writes a witness bundle. It does not measure whether generation would discover that fixture.

## Replay

```sh
querywitness replay demo-count/witness.json
```

Replay validates integrity/schema, then reruns the two queries using the recorded policy and execution limits. See [the replay contract](ALGORITHM.md#artifacts-and-replay) for exact observations versus result equality. This is the supported guarded replay route; directly running `fixture.sql` in another program has different safety and comparison behavior.

## Catalog

```sh
querywitness catalog
querywitness catalog --validate
```

The first command lists available families. Validation executes each family's reference, mutant, and control on its benign and revealing fixtures, checks the asserted relations, and checks literal expected outputs for the revealing fixtures. It does not establish universal equivalence of the controls.

## Benchmark

```sh
querywitness benchmark --out evaluation \
  --trials 16 --repeats 8 --seed 20260930 --max-rows 8

querywitness benchmark --out selected-evaluation \
  --family count_nullable --family join_multiplicity
```

`--family ID` is repeatable. Without it, all 12 families run. The benchmark allows 1–1,000 trials per run and 1–100 repeats. The output directory must be new. It contains `manifest.json`, `summary.json`, `REPORT.md`, per-family `raw/*.jsonl` records, and bundles for discovered mutant witnesses.

Unlike search, each random/boundary benchmark run consumes its entire trial budget even after finding a mismatch. A single masking fixture is a separately labeled baseline, not an equal-budget competitor. See [the protocol](REPRODUCIBILITY.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Successful command; successful demo; reproduced replay; or completed search with no counterexample |
| 1 | Search found a counterexample; replay observations changed; catalog oracle validation failed; or benchmark found a control mismatch |
| 2 | Invalid input, usage, schema, integrity, or filesystem/output error |
| 3 | Inconclusive outcome, unsupported generation, or exhausted search-time budget |
| 130 | User interruption |

Do not interpret exit 0 as query equivalence. Use the JSON `status` and the command's meaning. In CI, a search exit 1 may be the intended regression signal. Benchmark returns 3 if any comparisons are inconclusive; otherwise it returns 1 for control mismatches and 0 for a completed run. Catalog validation and benchmark failures should be inspected rather than counted as semantic detections.

JSON files are limited to 16 MB and duplicate keys/nonfinite JSON numbers are rejected. SQL input is limited to 32,768 UTF-8 bytes. Standard output and generated files may contain supplied SQL or data; treat captured logs accordingly.
