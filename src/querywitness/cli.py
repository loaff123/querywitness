"""Command-line entry points with bounded input and exclusive output directories.

Exit codes: 0 completed/no counterexample/reproduced; 1 counterexample or changed
replay; 2 invalid input, usage or I/O; 3 inconclusive/unsupported/budget exhausted.
A demo returning 0 means the requested demonstration was successfully produced.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import stat
import sys

from . import __version__
from .artifacts import MAX_JSON_BYTES, build_witness, replay, write_bundle
from .benchmark import run_benchmark
from .catalog import load_catalog, validate_catalog
from .engine import ExecutionLimits
from .reduce import minimize
from .schema import Schema
from .search import search

MAX_SQL_BYTES = ExecutionLimits().sql_bytes


def _read_text(path: str | Path, limit: int) -> str:
    """Read regular files only and cap the actual read, not just a prior stat."""
    path = Path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f'Input must be a regular file: {path}')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Input exceeds {limit} bytes: {path}')
    return raw.decode('utf-8')


def _load_json(path: str | Path):
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f'Nonfinite JSON number: {value}')

    return json.loads(_read_text(path, MAX_JSON_BYTES),
                      object_pairs_hook=unique_pairs, parse_constant=nonfinite)


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))


def _destination(path: str | None) -> Path | None:
    if path is None:
        return None
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Output already exists; choose a new directory: {destination}')
    return destination


def _bounded_integer(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('Expected an integer') from None
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected an integer from {low} to {high}')
        return number
    return parse


def _bounded_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Expected finite seconds from 0 to 300') from None
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise argparse.ArgumentTypeError('Expected finite seconds from 0 to 300')
    return seconds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='querywitness',
        description='Find replayable SQLite counterexamples. Bounded testing never proves equivalence.',
        epilog='Exit codes: 0 completed, 1 counterexample/changed replay, 2 input error, 3 inconclusive.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)

    search_parser = commands.add_parser('search', help='Search generated, schema-valid databases')
    search_parser.add_argument('schema', help='JSON schema file (at most 16,000,000 bytes)')
    search_parser.add_argument('reference', help='Reference SQL file (at most 32,768 bytes)')
    search_parser.add_argument('candidate', help='Candidate SQL file (at most 32,768 bytes)')
    search_parser.add_argument('--out', help='New output directory; existing paths are never overwritten')
    search_parser.add_argument('--trials', type=_bounded_integer(1, 10000), default=100)
    search_parser.add_argument('--seed', type=_bounded_integer(0, 2**63 - 1), default=0)
    search_parser.add_argument('--strategy', choices=('boundary', 'random', 'query_aware'), default='boundary')
    search_parser.add_argument('--policy', choices=('bag', 'set', 'ordered'), default='bag')
    search_parser.add_argument('--max-rows', type=_bounded_integer(1, 32), default=8)
    search_parser.add_argument('--seconds', type=float, default=60.0, help='Search wall-time budget (0–3600 seconds)')
    search_parser.add_argument('--no-minimize', action='store_true', help='Keep the generated witness without row reduction')

    search_parser.add_argument('--reduction-mode', choices=('row', 'fk-closure'), default='row')

    demo_parser = commands.add_parser('demo', help='Write a known, hand-authored catalog counterexample')
    demo_parser.add_argument('family', nargs='?', default='count_nullable')
    demo_parser.add_argument('--out', required=True, help='New output directory')

    demo_parser.add_argument('--reduction-mode', choices=('row', 'fk-closure'), default='row')

    replay_parser = commands.add_parser('replay', help='Verify a witness checksum and repeat its observations')
    replay_parser.add_argument('witness', help='Witness JSON file')

    replay_parser.add_argument('--verify-minimality', action='store_true', help='Independently audit all singleton FK closures')
    replay_parser.add_argument('--minimality-checks', type=_bounded_integer(1, 10000), default=500)
    replay_parser.add_argument('--minimality-seconds', type=_bounded_seconds, default=30.0)

    catalog_parser = commands.add_parser('catalog', help='List synthetic families or validate their oracle fixtures')
    catalog_parser.add_argument('--validate', action='store_true')

    benchmark_parser = commands.add_parser('benchmark', help='Run equal-budget random and boundary seed sweeps')
    benchmark_parser.add_argument('--out', required=True, help='New output directory')
    benchmark_parser.add_argument('--trials', type=_bounded_integer(1, 1000), default=16)
    benchmark_parser.add_argument('--repeats', type=_bounded_integer(1, 100), default=8)
    benchmark_parser.add_argument('--seed', type=_bounded_integer(0, 2**63 - 1), default=20260930)
    benchmark_parser.add_argument('--max-rows', type=_bounded_integer(1, 32), default=8)
    benchmark_parser.add_argument('--family', dest='families', action='append', help='Family ID; repeat to select several')
    return parser


def _search(args) -> int:
    if args.no_minimize and args.reduction_mode != 'row':
        raise ValueError('--no-minimize conflicts with --reduction-mode fk-closure')
    destination = _destination(args.out)
    schema = Schema.from_dict(_load_json(args.schema))
    reference = _read_text(args.reference, MAX_SQL_BYTES)
    candidate = _read_text(args.candidate, MAX_SQL_BYTES)
    result = search(schema, reference, candidate, trials=args.trials, seed=args.seed,
                    strategy=args.strategy, policy=args.policy, max_rows=args.max_rows,
                    seconds=args.seconds)
    if result['status'] == 'counterexample':
        instance = result['instance']
        reduction_meta = None
        if not args.no_minimize:
            reduction = minimize(schema, instance, reference, candidate, policy=args.policy,
                                 deletion_mode=args.reduction_mode)
            instance = reduction['instance']
            reduction_meta = {key: value for key, value in reduction.items() if key != 'instance'}
            if args.reduction_mode == 'fk-closure' and not reduction['witness_reproduced']:
                _print_json({'status': reduction['status'], 'reduction': reduction_meta})
                return 3
        result['reduction'] = reduction_meta
        if destination is not None:
            search_meta = {key: value for key, value in result.items()
                           if key not in ('instance', 'comparison', 'reference_rows', 'candidate_rows', 'reduction')}
            witness = build_witness(schema, instance, reference, candidate, policy=args.policy,
                                    search=search_meta, reduction=reduction_meta)
            write_bundle(witness, destination)
        code = 1
    else:
        code = 0 if result['status'] == 'no_counterexample_within_budget' else 3
        if destination is not None:
            destination.mkdir(parents=True, exist_ok=False)
    if destination is not None:
        result['artifact_directory'] = str(destination)
        with (destination / 'result.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    _print_json(result)
    return code


def _demo(args) -> int:
    destination = _destination(args.out)
    cases = {case['id']: case for case in load_catalog()['cases']}
    if args.family not in cases:
        raise ValueError(f'Unknown catalog family: {args.family}; use querywitness catalog')
    case = cases[args.family]
    schema = Schema.from_dict(case['schema'])
    reduction = minimize(schema, case['revealing'], case['reference'], case['mutant'],
                         deletion_mode=args.reduction_mode)
    reduction_meta = {key: value for key, value in reduction.items() if key != 'instance'}
    if args.reduction_mode == 'fk-closure' and not reduction['witness_reproduced']:
        _print_json({'status': reduction['status'], 'reduction': reduction_meta})
        return 3
    value = build_witness(schema, reduction['instance'], case['reference'], case['mutant'],
                          search={'source': 'catalog_revealing_fixture', 'family': args.family},
                          reduction=reduction_meta)
    write_bundle(value, destination)
    _print_json({'status': 'counterexample', 'family': args.family,
                 'artifact_directory': str(destination), 'reduction': reduction_meta})
    return 0


def _run(args) -> int:
    if args.command == 'search':
        return _search(args)
    if args.command == 'demo':
        return _demo(args)
    if args.command == 'replay':
        result = replay(_load_json(args.witness), verify_minimality=args.verify_minimality,
                        minimality_checks=args.minimality_checks, minimality_seconds=args.minimality_seconds)
        _print_json(result)
        if args.verify_minimality:
            audit = result['minimality_verification']['status']
            if result['status'] == 'observation_changed' or audit == 'refuted':
                return 1
            return 0 if result['status'] == 'reproduced' and audit == 'verified' else 3
        return 0 if result['status'] == 'reproduced' else (3 if result['status'] == 'inconclusive' else 1)
    if args.command == 'catalog':
        if args.validate:
            result = validate_catalog()
            _print_json(result)
            return 1 if result['failures'] else 0
        catalog = load_catalog()
        _print_json({'families': len(catalog['cases']), 'description': catalog['description'],
                     'cases': [{'id': case['id'], 'title': case['title']} for case in catalog['cases']]})
        return 0
    destination = _destination(args.out)
    known = {case['id'] for case in load_catalog()['cases']}
    unknown = set(args.families or ()) - known
    if unknown:
        raise ValueError('Unknown catalog families: ' + ', '.join(sorted(unknown)))
    result = run_benchmark(destination, trials=args.trials, repeats=args.repeats,
                           seed=args.seed, max_rows=args.max_rows, family_ids=args.families)
    _print_json(result)
    return 3 if result['inconclusive_instances'] else (1 if result['control_mismatches'] else 0)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except BrokenPipeError:
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(f'querywitness: {error}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('querywitness: interrupted', file=sys.stderr)
        return 130
