#!/usr/bin/env python3
"""Evaluate the frozen, small independently-authored validation suite.

Run from the checkout after installing QueryWitness and its pinned dependency:
    python scripts/run_holdout.py --out holdout-reproduction

The case file fixes every experimental parameter. Output is exclusive; a prior
freeze-only directory is accepted, but existing results are never overwritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from querywitness import __version__
from querywitness.artifacts import (
    build_witness, digest, load_json, observation, replay, write_bundle,
)
from querywitness.compare import compare_results
from querywitness.engine import ExecutionLimits, execute
from querywitness.generate import GenerationError, generate_instance
from querywitness.reduce import minimize
from querywitness.schema import Schema
from querywitness.semantics import PARSER_VERSION

CASES = ROOT / "benchmarks" / "holdout-cases.json"
FROZEN_CASE_SHA256 = "db43f222ba5d2e36999abf78e269322a20cf149253a95dadadfcc5431b366ae7"
GENERATOR = ROOT / "src" / "querywitness" / "generate.py"
INTERPRETATION = (
    "Small independently-authored holdout validation set, separate from the "
    "12 development fixtures. Not an external benchmark, expert-reviewed set, "
    "blind evaluation, or statistically representative sample. The author read "
    "the API, development catalog, and generator. Cases and parameters were "
    "frozen before generated evaluation; no post-result tuning was performed. "
    "Agreement within a finite budget does not establish equivalence."
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def freeze(destination):
    if sha256(CASES) != FROZEN_CASE_SHA256:
        raise ValueError("Frozen case file changed; this is not the recorded suite")
    if destination.exists():
        if {p.name for p in destination.iterdir()} != {"freeze.json"}:
            raise ValueError("Output must be new or contain only freeze.json")
        record = load_json(destination / "freeze.json")
        if record["case_file_sha256"] != FROZEN_CASE_SHA256:
            raise ValueError("Existing freeze refers to a different case file")
        if record["generator_sha256"] != sha256(GENERATOR):
            raise ValueError("Generator changed after this directory's freeze")
        return record
    destination.mkdir(parents=True)
    record = {
        "format": "querywitness/holdout-freeze",
        "format_version": 1,
        "frozen_at_runtime_utc": datetime.now(timezone.utc).isoformat(),
        "case_file": "benchmarks/holdout-cases.json",
        "case_file_sha256": FROZEN_CASE_SHA256,
        "generator_file": "src/querywitness/generate.py",
        "generator_sha256": sha256(GENERATOR),
        "first_generated_evaluation_started": False,
        "protocol": "Cases and all parameters fixed before generated evaluation; no tuning after freeze.",
    }
    write_json(destination / "freeze.json", record)
    return record


def oracle_checks(case, schema, limits):
    """Compare literal, authored expected bags without the production comparator."""
    records = []
    for fixture_name in ("masking", "revealing"):
        fixture = case[fixture_name]
        schema.validate_instance(fixture["instance"])
        for variant in ("reference", "mutant", "equivalent_control"):
            expected = fixture["expected_" + variant]
            result = execute(schema, fixture["instance"], case[variant], limits)
            records.append({
                "case": case["id"], "fixture": fixture_name, "query": variant,
                "expected_rows": expected, "observation": observation(result),
                "passed": result.status == "ok" and Counter(result.rows) == Counter(map(tuple, expected)),
            })
        ref = Counter(map(tuple, fixture["expected_reference"]))
        mutant = Counter(map(tuple, fixture["expected_mutant"]))
        control = Counter(map(tuple, fixture["expected_equivalent_control"]))
        if ref != control or (ref == mutant) != (fixture_name == "masking"):
            raise ValueError("Authored masking/revealing/control oracle relationship is invalid")
    return records


def save_replayed_witness(destination, schema, data, case, limits, search, reduction=None):
    witness = build_witness(
        schema, data, case["reference"], case["mutant"],
        limits=limits, search=search, reduction=reduction,
    )
    write_bundle(witness, destination)
    # Replay the actual persisted artifact, not only the in-memory object.
    checked = replay(load_json(destination / "witness.json"))
    write_json(destination / "replay.json", checked)
    return {"status": checked["status"], "exact_observations": checked["exact_observations"]}


def evaluate(destination):
    freeze_record = freeze(destination)
    suite = load_json(CASES)
    config = suite["evaluation"]
    limits = ExecutionLimits(**config["execution_limits"])
    if asdict(limits) != config["execution_limits"]:
        raise ValueError("Execution limit normalization changed frozen values")
    source_hashes = {
        str(p.relative_to(ROOT)): sha256(p)
        for p in sorted((ROOT / "src" / "querywitness").glob("*.py"))
    }
    source_hashes["scripts/run_holdout.py"] = sha256(Path(__file__))
    (destination / "raw").mkdir()
    start = time.perf_counter()
    all_records = []
    all_oracles = []
    case_summaries = []
    errors = []
    witness_checks = []
    for case in suite["cases"]:
        case_id = case["id"]
        case_summary = {"id": case_id, "methods": {}}
        case_summaries.append(case_summary)
        try:
            schema = Schema.from_dict(case["schema"])
            checks = oracle_checks(case, schema, limits)
            all_oracles.extend(checks)
            if not all(check["passed"] for check in checks):
                case_summary["status"] = "oracle_invalid"
                errors.append({"case": case_id, "phase": "oracle", "detail": "Literal expected output was not reproduced"})
                continue
            check = save_replayed_witness(
                destination / "oracle-witnesses" / case_id,
                schema, case["revealing"]["instance"], case, limits,
                {"source": "frozen hand-authored revealing fixture", "generated_search": False},
            )
            witness_checks.append({"case": case_id, "source": "oracle", **check})
        except Exception as error:
            case_summary["status"] = "oracle_error"
            errors.append({"case": case_id, "phase": "oracle", "type": type(error).__name__, "detail": str(error)})
            continue

        records = []
        for method in config["methods"]:
            method_records = []
            first_saved = False
            for offset in range(config["trials_per_method"]):
                seed = config["seed_start"] + offset
                record = {"case": case_id, "method": method, "seed": seed, "trial": offset + 1}
                try:
                    data = generate_instance(schema, seed, method, config["max_rows"])
                    schema.validate_instance(data)
                    record.update({"generation_status": "ok", "instance": data, "instance_sha256": digest(data)})
                    reference = execute(schema, data, case["reference"], limits)
                    record["reference_observation"] = observation(reference)
                    record["comparisons"] = {}
                    for variant in config["variants"]:
                        candidate = execute(schema, data, case[variant], limits)
                        result = compare_results(reference, candidate, config["policy"])
                        record["comparisons"][variant] = {**result, "candidate_observation": observation(candidate)}
                    if record["comparisons"]["mutant"]["status"] == "mismatch" and not first_saved:
                        first_saved = True
                        try:
                            reduced = minimize(
                                schema, data, case["reference"], case["mutant"],
                                limits=limits, **config["reduction"],
                            )
                            check = save_replayed_witness(
                                destination / "generated-witnesses" / case_id / method,
                                schema, reduced["instance"], case, limits,
                                {"seed": seed, "strategy": method, "trial_budget": config["trials_per_method"], "max_rows": config["max_rows"]},
                                {k: v for k, v in reduced.items() if k != "instance"},
                            )
                            witness_checks.append({"case": case_id, "source": method, **check})
                        except Exception as error:
                            errors.append({"case": case_id, "phase": "witness", "method": method, "seed": seed, "type": type(error).__name__, "detail": str(error)})
                except GenerationError as error:
                    record.update({"generation_status": "unsupported_generation", "detail": str(error)})
                except Exception as error:
                    record.update({"generation_status": "error", "error_type": type(error).__name__, "detail": str(error)})
                    errors.append({"case": case_id, "phase": "trial", "method": method, "seed": seed, "type": type(error).__name__, "detail": str(error)})
                records.append(record)
                method_records.append(record)
            stats = {"planned_instances": config["trials_per_method"]}
            stats["generation_status_counts"] = dict(Counter(r["generation_status"] for r in method_records))
            for variant in config["variants"]:
                comparisons = [(r["trial"], r["comparisons"][variant]) for r in method_records if variant in r.get("comparisons", {})]
                counts = Counter(c["status"] for _, c in comparisons)
                first = next((trial for trial, c in comparisons if c["status"] == "mismatch"), None)
                stats[variant] = {
                    "comparisons": len(comparisons),
                    "agreement": counts["agreement"], "mismatch": counts["mismatch"], "inconclusive": counts["inconclusive"],
                    "first_mismatch_trial": first,
                    "outcome": "detected" if first is not None else (
                        "miss" if variant == "mutant" and counts["agreement"] == config["trials_per_method"] else (
                            "no_mismatch_within_budget" if counts["agreement"] == config["trials_per_method"] else "incomplete_or_inconclusive"
                        )
                    ),
                    "reference_status_counts": dict(Counter(c["reference_status"] for _, c in comparisons)),
                    "candidate_status_counts": dict(Counter(c["candidate_status"] for _, c in comparisons)),
                }
            case_summary["methods"][method] = stats
        case_summary["status"] = "evaluated"
        all_records.extend(records)
        (destination / "raw" / (case_id + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n" for r in records),
            encoding="utf-8",
        )

    all_comparisons = [(variant, result) for r in all_records for variant, result in r.get("comparisons", {}).items()]
    summary = {
        "format": "querywitness/holdout-summary", "format_version": 1,
        "interpretation": INTERPRETATION, "case_file_sha256": FROZEN_CASE_SHA256,
        "cases": len(suite["cases"]), "configuration": config,
        "planned_generated_instances": len(suite["cases"]) * len(config["methods"]) * config["trials_per_method"],
        "planned_comparisons": len(suite["cases"]) * len(config["methods"]) * config["trials_per_method"] * len(config["variants"]),
        "generated_instance_attempts": len(all_records),
        "generation_status_counts": dict(Counter(r["generation_status"] for r in all_records)),
        "completed_comparisons": len(all_comparisons),
        "inconclusive_comparisons": sum(r["status"] == "inconclusive" for _, r in all_comparisons),
        "unsupported_query_comparisons": sum("unsupported" in (r["reference_status"], r["candidate_status"]) for _, r in all_comparisons),
        "query_error_comparisons": sum("query_error" in (r["reference_status"], r["candidate_status"]) for _, r in all_comparisons),
        "unsupported_generation_attempts": sum(r["generation_status"] == "unsupported_generation" for r in all_records),
        "generation_error_attempts": sum(r["generation_status"] == "error" for r in all_records),
        "control_mismatch_comparisons": sum(v == "equivalent_control" and r["status"] == "mismatch" for v, r in all_comparisons),
        "oracle_query_checks": len(all_oracles), "oracle_query_passes": sum(r["passed"] for r in all_oracles),
        "witness_replays": witness_checks,
        "method_outcomes": {}, "by_case": case_summaries, "errors": errors,
        "elapsed_seconds": round(time.perf_counter() - start, 6),
    }
    for method in config["methods"]:
        outcomes = Counter(c["methods"].get(method, {}).get("mutant", {}).get("outcome", c["status"]) for c in case_summaries)
        summary["method_outcomes"][method] = {"detected_cases": outcomes["detected"], "missed_cases": outcomes["miss"], "other_cases": len(suite["cases"]) - outcomes["detected"] - outcomes["miss"], "total_cases": len(suite["cases"])}
    write_json(destination / "oracle-checks.json", all_oracles)
    write_json(destination / "summary.json", summary)
    lines = ["# Frozen validation results", "", INTERPRETATION, "",
             "## Fixed protocol", "",
             f"Five cases; seeds {config['seed_start']}–{config['seed_end_inclusive']}; {config['trials_per_method']} generated instances per case and method; max_rows={config['max_rows']}. Random and boundary use paired seeds. Each generated instance is compared with the mutant and equivalent control. No early stopping or parameter tuning.", "",
             "Literal hand-computed expected bags validate all three queries on both revealing and masking fixtures. These checks use Python Counter rather than the production result comparator. They still share the SQLite execution engine; they are not a second-engine differential oracle.", "",
             "## Observed outcomes", "",
             f"Completed comparisons: {summary['completed_comparisons']}/{summary['planned_comparisons']}. Literal oracle checks: {summary['oracle_query_passes']}/{summary['oracle_query_checks']}. Control mismatches: {summary['control_mismatch_comparisons']}. Inconclusive comparisons: {summary['inconclusive_comparisons']}.", "",
             "| Case | Random | Boundary |", "|---|---|---|"]
    for case in case_summaries:
        cells = []
        for method in config["methods"]:
            result = case["methods"].get(method, {}).get("mutant", {})
            cells.append(f"{result.get('outcome', case['status'])}; {result.get('mismatch', 0)}/{config['trials_per_method']} mismatches; first={result.get('first_mismatch_trial')}")
        lines.append(f"| {case['id']} | {cells[0]} | {cells[1]} |")
    lines += ["", f"Unsupported query comparisons: {summary['unsupported_query_comparisons']}; query errors: {summary['query_error_comparisons']}; unsupported generation attempts: {summary['unsupported_generation_attempts']}; generation errors: {summary['generation_error_attempts']}; other recorded errors: {len(errors)}.", "",
              f"Exact replay checks: {sum(r['status'] == 'reproduced' and r['exact_observations'] for r in witness_checks)}/{len(witness_checks)}. Five authored witnesses are retained regardless of generated detection. The first generated mismatch per case and method is reduced and saved separately; reduction does not consume the comparison budget.", "",
              "## Reproduce", "", "From a checkout with the pinned dependency installed:", "", "```sh", "python scripts/run_holdout.py --out holdout-reproduction", "```", "",
              "The output directory must be new. To inspect the freeze before execution, first run with --freeze-only, then run the same command without that flag. The case-file SHA is pinned by the script. Compare case/generator/source hashes, generated data and status records, expected outputs and replay checks; runtime provenance and elapsed times can vary. Every generated instance and typed observation is in raw/*.jsonl; manifest.json hashes every output other than itself.", "",
              "## Limits", "", "These five purposively selected tasks extend schema/domain/constraint coverage beyond the development catalog, but revisit related SQL semantic mechanisms. Reading the catalog and generator makes this a modest internal validation split, not independent external validation. One seed sweep is one run per method/case, not 32 independent tasks. No population-level confidence intervals, superiority claim, or false-positive-rate estimate is justified. A missed mutant is retained as a miss, never relabeled equivalent. Equivalent controls follow the declared constraints and SQLite contract.", ""]
    (destination / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    current_sources = {name: sha256(ROOT / name) for name in source_hashes}
    if current_sources != source_hashes or sha256(CASES) != FROZEN_CASE_SHA256:
        raise RuntimeError("Cases or evaluated sources changed during evaluation; outputs are invalid")
    manifest = {
        "format": "querywitness/holdout-manifest", "format_version": 1,
        "tool_version": __version__, "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version, "sqlglot_version": PARSER_VERSION,
        "platform": platform.platform(), "case_file_sha256": FROZEN_CASE_SHA256,
        "freeze_record": freeze_record, "configuration": config,
        "source_sha256": source_hashes,
        "command": "python scripts/run_holdout.py --out holdout-reproduction",
        "output_sha256": {str(p.relative_to(destination)): sha256(p) for p in sorted(destination.rglob("*")) if p.is_file()},
    }
    write_json(destination / "manifest.json", manifest)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    if args.freeze_only:
        print(json.dumps(freeze(args.out), indent=2))
        return 0
    summary = evaluate(args.out)
    print(json.dumps({k: summary[k] for k in (
        "cases", "completed_comparisons", "oracle_query_checks", "oracle_query_passes",
        "control_mismatch_comparisons", "inconclusive_comparisons", "method_outcomes", "errors",
    )}, indent=2))
    bad_replays = any(r["status"] != "reproduced" or not r["exact_observations"] for r in summary["witness_replays"])
    return int(bool(summary["errors"] or bad_replays or summary["control_mismatch_comparisons"] or summary["oracle_query_passes"] != summary["cases"] * 6))


if __name__ == "__main__":
    raise SystemExit(main())
