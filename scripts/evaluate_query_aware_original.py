#!/usr/bin/env python3
"""Reproduce the original-only QueryWitness query-aware DEVELOPMENT evaluation.

Requires QueryWitness's installed dependencies. Uses the public, frozen original
fixture suite and its independent stdlib oracle. Never consumes another corpus.
Example: python scripts/evaluate_query_aware_original.py run --output /tmp/qw-original
Audit bundled evidence: python scripts/evaluate_query_aware_original.py verify
Python optimized mode (-O) is forbidden because the frozen oracle uses assertions.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import platform
import sqlite3
import sys
import time
import traceback

SOURCE = Path(__file__).resolve().parents[1]
FIXTURES = SOURCE/'benchmarks/query-aware-original-suite'
PUBLIC_RESULTS = SOURCE/'benchmarks/query-aware-original-results'

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def relative_posix(path, root):
    """Serialize relative artifact paths identically on Windows and POSIX."""
    return path.relative_to(root).as_posix()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def default_config():
    return {'methods': ['random', 'boundary', 'query_aware'],
            'repeat_seeds': [20260930, 20261930, 20262930, 20263930],
            'trials': 64, 'max_rows': 8, 'policy': 'bag',
            'limits': {'rows': 10000, 'bytes': 2000000, 'vm_steps': 1000000,
                       'seconds': 2.0, 'sql_bytes': 32768}}

def planned_trials(n, config):
    return n * len(config['methods']) * len(config['repeat_seeds']) * config['trials']

class InstanceViolation(ValueError):
    """Independent evaluator contract check failed."""

def validate_instance(schema, instance, max_rows):
    """Independent raw-schema check on EVERY trial, without product validators."""
    def require(condition, message):
        if not condition:
            raise InstanceViolation(message)
    require(isinstance(instance, dict), 'instance must be a mapping')
    tables = schema['tables']
    require(set(instance) == {t['name'] for t in tables}, 'instance tables differ')
    require(sum(len(rows) for rows in instance.values() if isinstance(rows, list)) <= 2000, 'total row cap exceeded')
    by_name = {t['name']: t for t in tables}
    for table in tables:
        rows = instance[table['name']]
        require(isinstance(rows, list), 'table rows must be a list')
        require(len(rows) <= max_rows, 'row-per-table budget exceeded')
        columns = table['columns']
        positions = {c['name']: i for i, c in enumerate(columns)}
        for row in rows:
            require(isinstance(row, (list, tuple)) and len(row) == len(columns), 'row width mismatch')
            for column, value in zip(columns, row):
                if value is None:
                    require(column.get('nullable', True) and column['name'] not in table.get('primary_key', []), 'illegal NULL')
                    continue
                kind = column['type']
                if kind == 'INTEGER':
                    legal = type(value) is int and -(2**63) <= value < 2**63
                elif kind == 'REAL':
                    legal = ((type(value) is int and abs(value) <= 2**53) or
                             (type(value) is float and math.isfinite(value) and abs(value) <= 1e100))
                elif kind == 'TEXT':
                    legal = (type(value) is str and '\0' not in value and
                             not any(0xD800 <= ord(c) <= 0xDFFF for c in value) and
                             len(value.encode('utf-8', errors='surrogatepass')) <= 4096)
                else:
                    legal = False
                require(legal, 'illegal type or value bound')
                if 'domain' in column:
                    require(value in column['domain'], 'outside explicit domain')
        groups = ([table['primary_key']] if table.get('primary_key') else []) + table.get('unique', [])
        for group in groups:
            seen = set()
            for row in rows:
                key = tuple(row[positions[c]] for c in group)
                if None in key:
                    continue
                require(key not in seen, 'primary/unique key violation')
                seen.add(key)
    for table in tables:
        pos = {c['name']: i for i, c in enumerate(table['columns'])}
        for fk in table.get('foreign_keys', []):
            ref = fk['references']
            parent = by_name[ref['table']]
            parent_pos = {c['name']: i for i, c in enumerate(parent['columns'])}
            parent_keys = {tuple(row[parent_pos[c]] for c in ref['columns']) for row in instance[parent['name']]}
            for row in instance[table['name']]:
                key = tuple(row[pos[c]] for c in fk['columns'])
                require(None in key or key in parent_keys, 'foreign key violation')

class ProductRuntime:
    def __init__(self):
        # Dependencies come from the installed package environment.
        sys.path[:0] = [str(SOURCE/'src')]
        import querywitness
        import sqlglot
        from querywitness.schema import Schema
        from querywitness.engine import execute, ExecutionLimits
        from querywitness.generate import generate_instance
        from querywitness.query_plan import compile_plan
        from querywitness.query_generate import generate_query_aware
        from querywitness.compare import compare_results
        from querywitness.artifacts import observation
        if not Path(querywitness.__file__).resolve().is_relative_to((SOURCE/'src').resolve()):
            raise RuntimeError('unexpected product import location')
        self.Schema = Schema
        self.ExecutionLimits = ExecutionLimits
        self._execute = execute
        self._generate = generate_instance
        self._compile = compile_plan
        self._query_generate = generate_query_aware
        self._compare = compare_results
        self._observation = observation
        self.versions = {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                         'sqlglot': sqlglot.__version__, 'querywitness': querywitness.__version__,
                         'querywitness_import_path': querywitness.__file__}

    def schema(self, raw):
        return self.Schema.from_dict(raw)

    def compile(self, schema, reference, candidate, config):
        return self._compile(schema, reference, candidate, max_rows=config['max_rows'], sql_bytes=config['limits']['sql_bytes'])

    def generate(self, schema, plan, seed, method, config):
        if method == 'query_aware':
            return self._query_generate(schema, plan, seed)
        return self._generate(schema, seed, method, config['max_rows']), None

    def execute(self, schema, instance, sql, config):
        return self._execute(schema, instance, sql, self.ExecutionLimits(**config['limits']), policy=config['policy'])

    def compare(self, a, b, policy):
        return self._compare(a, b, policy)

    def observation(self, result):
        return self._observation(result)

def evaluate_case(case, config, dest, runtime):
    dest.mkdir(parents=True, exist_ok=True)
    schema = runtime.schema(case['schema'])
    tick = time.monotonic()
    plan = runtime.compile(schema, *case['pair'], config)
    plan_seconds = time.monotonic() - tick
    plan_data = plan.to_dict()
    write_json(dest/'plan.json', {'case_id': case['case_id'], 'plan': plan_data,
                                'plan_sha256': digest(plan_data), 'compile_seconds': plan_seconds})
    runs = []
    with (dest/'trials.jsonl').open('x', encoding='utf-8') as log:
        for method in config['methods']:
            for repeat, start_seed in enumerate(config['repeat_seeds']):
                counts = Counter()
                errors = Counter()
                nonempty = [0, 0]
                both_empty = 0
                first = None
                generation_errors = 0
                invalid_instances = 0
                begin = time.monotonic()
                for trial in range(config['trials']):
                    seed = start_seed + trial
                    tick = time.monotonic()
                    instance = None
                    a = b = None
                    record = {'case_id': case['case_id'], 'source_index': case.get('source_index'),
                              'cohort': case['cohort'], 'method': method, 'repeat': repeat, 'trial': trial,
                              'seed': seed, 'instance_sha256': None, 'table_rows': None,
                              'reference_status': 'not_run', 'candidate_status': 'not_run',
                              'reference_rows': None, 'candidate_rows': None, 'status': 'inconclusive',
                              'both_empty': False, 'generation_status': 'not_run',
                              'instance_validation_status': 'not_run', 'generator_stats': None,
                              'generation_seconds': 0.0, 'instance_validation_seconds': 0.0,
                              'reference_seconds': 0.0, 'candidate_seconds': 0.0, 'comparison_seconds': 0.0}
                    stage = 'generation'
                    stage_tick = time.monotonic()
                    try:
                        instance, stats = runtime.generate(schema, plan, seed, method, config)
                        record['generation_seconds'] = time.monotonic() - stage_tick
                        record['generation_status'] = 'ok'
                        record['generator_stats'] = stats
                        stage = 'instance_validation'
                        stage_tick = time.monotonic()
                        record['instance_sha256'] = digest(instance)
                        record['table_rows'] = {k: len(v) for k, v in instance.items()}
                        validate_instance(case['schema'], instance, config['max_rows'])
                        record['instance_validation_seconds'] = time.monotonic() - stage_tick
                        record['instance_validation_status'] = 'valid'
                        stage = 'reference'
                        stage_tick = time.monotonic()
                        a = runtime.execute(schema, instance, case['pair'][0], config)
                        record['reference_seconds'] = time.monotonic() - stage_tick
                        record.update(reference_status=a.status, reference_rows=len(a.rows))
                        stage = 'candidate'
                        stage_tick = time.monotonic()
                        b = runtime.execute(schema, instance, case['pair'][1], config)
                        record['candidate_seconds'] = time.monotonic() - stage_tick
                        record.update(candidate_status=b.status, candidate_rows=len(b.rows))
                        stage = 'comparison'
                        stage_tick = time.monotonic()
                        comp = runtime.compare(a, b, config['policy'])
                        record['comparison_seconds'] = time.monotonic() - stage_tick
                        record['status'] = comp['status']
                        record['both_empty'] = a.status == b.status == 'ok' and not a.rows and not b.rows
                        if comp['status'] == 'inconclusive':
                            record['details'] = [a.detail, b.detail]
                    except Exception as error:
                        record[stage + '_seconds'] = time.monotonic() - stage_tick
                        record['error_stage'] = stage
                        record['details'] = [type(error).__name__ + ': ' + str(error)]
                        if stage == 'generation':
                            record['generation_status'] = 'error'
                            generation_errors += 1
                        elif stage == 'instance_validation':
                            record['instance_validation_status'] = 'invalid'
                            invalid_instances += 1
                        elif stage in ('reference', 'candidate'):
                            record[stage + '_status'] = 'exception'
                    record['seconds'] = time.monotonic() - tick
                    counts[record['status']] += 1
                    both_empty += bool(record['both_empty'])
                    nonempty[0] += record['reference_status'] == 'ok' and bool(record['reference_rows'])
                    nonempty[1] += record['candidate_status'] == 'ok' and bool(record['candidate_rows'])
                    if record['status'] == 'inconclusive':
                        errors[json.dumps(record.get('details', []), sort_keys=True)] += 1
                    log.write(json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')
                    log.flush()
                    if record['status'] == 'mismatch' and first is None:
                        first = trial
                        write_json(dest/f'{method}-{repeat}-witness.json', {
                            'case_id': case['case_id'], 'cohort': case['cohort'],
                            'source_index': case.get('source_index'),
                            'source_row_sha256': case.get('source_row_sha256'),
                            'fixture_case_sha256': case.get('fixture_case_sha256'),
                            'pair_sha256': case.get('pair_sha256'), 'plan_sha256': digest(plan_data),
                            'policy': config['policy'], 'method': method, 'repeat': repeat,
                            'trial': trial, 'seed': seed, 'instance': instance,
                            'instance_sha256': record['instance_sha256'], 'table_rows': record['table_rows'],
                            'generator_stats': record['generator_stats'],
                            'reference_observation': runtime.observation(a),
                            'candidate_observation': runtime.observation(b),
                            'plain_observations': [{'rows': [list(row) for row in r.rows], 'width': len(r.columns)} for r in (a, b)],
                            'comparison': comp})
                runs.append({'method': method, 'repeat': repeat, 'counts': dict(counts),
                             'attempted_trials': config['trials'], 'first_hit_trial': first,
                             'nonempty_trials': nonempty, 'both_empty_trials': both_empty,
                             'generation_errors': generation_errors, 'invalid_instances': invalid_instances,
                             'errors': dict(errors), 'seconds': time.monotonic() - begin})
    summary = {'case_id': case['case_id'], 'source_index': case.get('source_index'),
               'cohort': case['cohort'], 'pair_sha256': case.get('pair_sha256'),
               'compile_seconds': plan_seconds, 'runs': runs}
    write_json(dest/'summary.json', summary)
    return summary

def verify_original_witness(oracle, case, instance, expected, limits):
    """Original author's schema/Counter oracle, bounded stdlib execution wrapper."""
    def observe(reverse):
        data = {name: list(reversed(rows)) if reverse else rows for name, rows in instance.items()}
        db = oracle.build_database(case['schema'], data)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA query_only=ON')
            observations = []
            for query in case['pair']:
                if len(query.encode('utf-8')) > limits['sql_bytes']:
                    raise RuntimeError('independent SQL byte limit')
                start = time.monotonic()
                steps = [0]
                def progress():
                    steps[0] += 100
                    return steps[0] >= limits['vm_steps'] or time.monotonic() - start > limits['seconds']
                db.set_progress_handler(progress, 100)
                cursor = db.execute(query)
                rows = []
                size = 0
                for row in cursor:
                    if len(rows) >= limits['rows']:
                        raise RuntimeError('independent row limit')
                    size += len(canonical(list(row)))
                    if size > limits['bytes']:
                        raise RuntimeError('independent byte limit')
                    rows.append(list(row))
                observations.append({'rows': rows, 'width': len(cursor.description)})
            return observations
        finally:
            db.close()
    forward, reverse = observe(False), observe(True)
    def equal(a, b):
        return a['width'] == b['width'] and oracle.bag(a['rows']) == oracle.bag(b['rows'])
    if equal(*forward):
        raise AssertionError('witness does not disagree')
    if not all(equal(a, b) for a, b in zip(forward, reverse)):
        raise AssertionError('insertion order changes output bags')
    if not all(equal(a, b) for a, b in zip(forward, expected)):
        raise AssertionError('saved observations differ from independent execution')
    return {'verified': True, 'source_constraints_enforced': True, 'strict_types_checked': True,
            'bag_mismatch': True, 'reverse_insertion_same_bags': True, 'observations': forward}

def summarize(out, cases, config, reports):
    result = {'classification': 'DEVELOPMENT, not held-out generalization', 'cohorts': {}}
    verified = {(r['cohort'], r['case_id'], r['method'], r['repeat']) for r in reports if r['status'] == 'verified'}
    for cohort in sorted({c['cohort'] for c in cases}):
        members = [c for c in cases if c['cohort'] == cohort]
        methods = {}
        summaries = {c['case_id']: read_json(out/cohort/c['case_id']/'summary.json') for c in members}
        case_outcomes = []
        for method in config['methods']:
            raw_cases = confirmed_cases = hit_runs = 0
            counts = Counter()
            empty = generation_errors = invalid = 0
            seconds = 0.0
            always_empty_cases = 0
            for case in members:
                runs = [r for r in summaries[case['case_id']]['runs'] if r['method'] == method]
                detected = any(r['first_hit_trial'] is not None for r in runs)
                confirmed = any((cohort, case['case_id'], method, r['repeat']) in verified for r in runs)
                raw_cases += detected
                confirmed_cases += confirmed
                hit_runs += sum(r['first_hit_trial'] is not None for r in runs)
                all_empty = sum(r['both_empty_trials'] for r in runs) == config['trials'] * len(config['repeat_seeds'])
                always_empty_cases += all_empty
                for r in runs:
                    counts.update(r['counts'])
                    empty += r['both_empty_trials']
                    generation_errors += r['generation_errors']
                    invalid += r['invalid_instances']
                    seconds += r['seconds']
                case_outcomes.append({'case_id': case['case_id'], 'source_index': case.get('source_index'),
                                      'method': method, 'raw_detected': detected, 'confirmed_detected': confirmed,
                                      'always_both_empty': all_empty,
                                      'bounded_relation': case.get('relation_with_at_most_8_rows_per_table'),
                                      'first_hit_trials': [r['first_hit_trial'] for r in runs]})
            methods[method] = {'tasks': len(members), 'raw_detected_tasks': raw_cases,
                               'confirmed_detected_tasks': confirmed_cases, 'detected_runs': hit_runs,
                               'planned_runs': len(members)*len(config['repeat_seeds']),
                               'counts': dict(counts), 'both_empty_trials': empty,
                               'always_both_empty_tasks': always_empty_cases,
                               'generation_errors': generation_errors, 'invalid_instances': invalid,
                               'method_seconds': seconds}
        result['cohorts'][cohort] = {'tasks': len(members), 'planned_trials': planned_trials(len(members), config),
                                    'methods': methods, 'case_outcomes': case_outcomes}
    write_json(out/'summary.json', result)
    return result


def reject_optimized_mode():
    if not __debug__:
        raise RuntimeError('Python -O is unsupported: the frozen independent oracle requires assertions')


def bytes_digest(data):
    return hashlib.sha256(data).hexdigest()


def original_cases():
    suite = read_json(FIXTURES/'fixtures.json')
    if len(suite['cases']) != 16:
        raise RuntimeError('frozen original suite must have exactly 16 cases')
    return [{**case, 'case_id': case['id'], 'cohort': 'original',
             'pair': [case['reference_sql'], case['candidate_sql']],
             'pair_sha256': digest([case['reference_sql'], case['candidate_sql']]),
             'fixture_case_sha256': digest(case)} for case in suite['cases']]


def load_oracle():
    reject_optimized_mode()
    path = FIXTURES/'validate_sqlite.py'
    spec = importlib.util.spec_from_file_location('querywitness_original_oracle', path)
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    oracle.check_manifest()
    return oracle


def compress_trial_bytes(data):
    """Deterministic gzip: blank filename, mtime zero, preserved exact input bytes."""
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', mtime=0, compresslevel=9) as stream:
        stream.write(data)
    return buffer.getvalue()


def read_trial_bytes(path):
    path = Path(path)
    if not path.exists() and path.suffix != '.gz':
        path = path.with_suffix(path.suffix + '.gz')
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == '.gz' else data


def read_trial_records(path):
    return [json.loads(line) for line in read_trial_bytes(path).decode('utf-8').splitlines()]


def compress_logs(out):
    for path in sorted(out.glob('original/*/trials.jsonl')):
        compressed = path.with_suffix('.jsonl.gz')
        raw = path.read_bytes()
        with compressed.open('xb') as stream:
            stream.write(compress_trial_bytes(raw))
        if read_trial_bytes(compressed) != raw:
            raise RuntimeError('trial compression failed exact-byte verification')
        path.unlink()


def stable_record(record):
    return {key: value for key, value in record.items() if key != 'seconds' and not key.endswith('_seconds')}


def compare_recorded(out, recorded):
    differences = []
    count = 0
    for case in original_cases():
        relative = Path('original')/case['case_id']/'trials.jsonl'
        old = read_trial_records(recorded/relative)
        fresh = read_trial_records(out/relative)
        if len(old) != 768 or len(fresh) != 768:
            raise RuntimeError('recorded or reproduced original trial count differs')
        for a, b in zip(old, fresh):
            count += 1
            if stable_record(a) != stable_record(b):
                differences.append({'case_id': case['case_id'], 'method': a['method'],
                                    'repeat': a['repeat'], 'trial': a['trial']})
    result = {'compared_trials': count, 'different_trials': len(differences),
              'status': 'identical_ignoring_timing' if not differences else 'different',
              'ignored_fields': 'seconds and all *_seconds instrumentation fields',
              'differences': differences}
    write_json(out/'recorded-comparison.json', result)
    return result


def verify_output(out, save=False):
    reject_optimized_mode()
    oracle = load_oracle()
    config = default_config()
    cases = original_cases()
    expected = [(method, repeat, trial) for method in config['methods'] for repeat in range(4) for trial in range(64)]
    trials = 0
    reports = []
    for case in cases:
        folder = out/'original'/case['case_id']
        plan = read_json(folder/'plan.json')
        if plan['plan_sha256'] != digest(plan['plan']):
            raise RuntimeError('recorded plan digest differs')
        records = read_trial_records(folder/'trials.jsonl')
        if [(r['method'], r['repeat'], r['trial']) for r in records] != expected:
            raise RuntimeError('missing, duplicate, or out-of-order original trial key')
        trials += len(records)
        for record in records:
            if record['case_id'] != case['case_id'] or record['cohort'] != 'original':
                raise RuntimeError('trial belongs to wrong case/cohort')
            if record['seed'] != config['repeat_seeds'][record['repeat']] + record['trial']:
                raise RuntimeError('trial seed differs from fixed schedule')
            if record['table_rows'] is not None and any(n > 8 for n in record['table_rows'].values()):
                raise RuntimeError('accepted row bound exceeded')
        for method in config['methods']:
            for repeat in range(4):
                rs = [r for r in records if r['method'] == method and r['repeat'] == repeat]
                first = next((r for r in rs if r['status'] == 'mismatch'), None)
                path = folder/f'{method}-{repeat}-witness.json'
                if path.exists() != bool(first):
                    raise RuntimeError('first witness presence differs from trial log')
                if first is None:
                    continue
                witness = read_json(path)
                report = {'path': relative_posix(path, out), 'cohort': 'original',
                          'case_id': case['case_id'], 'method': method, 'repeat': repeat}
                try:
                    if witness['trial'] != first['trial'] or witness['seed'] != first['seed']:
                        raise RuntimeError('saved first witness trial/seed differs')
                    if digest(witness['instance']) != witness['instance_sha256'] or witness['instance_sha256'] != first['instance_sha256']:
                        raise RuntimeError('witness instance digest differs')
                    if witness['pair_sha256'] != case['pair_sha256'] or witness['fixture_case_sha256'] != case['fixture_case_sha256']:
                        raise RuntimeError('witness query or frozen fixture identity differs')
                    if witness['plan_sha256'] != plan['plan_sha256']:
                        raise RuntimeError('witness plan identity differs')
                    validate_instance(case['schema'], witness['instance'], 8)
                    checked = verify_original_witness(oracle, case, witness['instance'], witness['plain_observations'], config['limits'])
                    report.update(status='verified', row_bound_verified=True, explicit_domains_verified=True, independent=checked)
                    if case['relation_with_at_most_8_rows_per_table'] == 'equivalent':
                        report['status'] = 'oracle_control_violation'
                except Exception as error:
                    report.update(status='quarantined', error=type(error).__name__ + ': ' + str(error))
                reports.append(report)
    result = {'trial_records': trials, 'saved_witnesses': len(reports),
              'verified': sum(r['status'] == 'verified' for r in reports),
              'quarantined': sum(r['status'] == 'quarantined' for r in reports),
              'oracle_control_violations': sum(r['status'] == 'oracle_control_violation' for r in reports)}
    if save:
        write_json(out/'witness-checks.json', reports)
        write_json(out/'witness-check-summary.json', result)
    if result['quarantined'] or result['oracle_control_violations']:
        raise RuntimeError('independent witness validation failed: ' + json.dumps(result))
    return reports, result


def make_manifest(out):
    files = {}
    for path in sorted(out.rglob('*')):
        if not path.is_file() or path.name == 'MANIFEST.json':
            continue
        entry = {'bytes': path.stat().st_size, 'sha256': file_digest(path)}
        if path.name == 'trials.jsonl.gz':
            raw = read_trial_bytes(path)
            entry.update(decompressed_bytes=len(raw), decompressed_sha256=bytes_digest(raw), records=len(raw.splitlines()))
        files[relative_posix(path, out)] = entry
    return {'format_version': 1, 'cohort': 'original', 'case_count': 16, 'trial_records': 12288,
            'compression': 'gzip, blank filename, mtime=0, exact decompressed bytes preserved', 'files': files}


def verify_manifest(out):
    manifest = read_json(out/'MANIFEST.json')
    actual = make_manifest(out)
    if manifest != actual:
        raise RuntimeError('original-result artifact inventory or digest changed')
    return manifest


def run_original(out, compare_to=None):
    reject_optimized_mode()
    load_oracle()
    cases = original_cases()
    config = default_config()
    out.mkdir(parents=True, exist_ok=False)
    before = {relative_posix(path, SOURCE): file_digest(path)
              for directory in (SOURCE/'src', FIXTURES) for path in sorted(directory.rglob('*'))
              if path.is_file() and '__pycache__' not in path.parts and not path.name.endswith('.pyc')}
    write_json(out/'input-freeze.json', {'classification': 'original DEVELOPMENT validation; not external generalization',
                                       'frozen_at_utc': utc(), 'files_sha256': before})
    write_json(out/'config.json', config)
    start = time.monotonic()
    try:
        runtime = ProductRuntime()
        write_json(out/'runtime.json', {k: v for k, v in runtime.versions.items() if k != 'querywitness_import_path'})
        for case in cases:
            evaluate_case(case, config, out/'original'/case['case_id'], runtime)
            print(case['case_id'], '768 trial records retained', flush=True)
        compress_logs(out)
        reports, checked = verify_output(out, save=True)
        result = summarize(out, cases, config, reports)
        comparison = compare_recorded(out, compare_to) if compare_to else None
        after = {relative: file_digest(SOURCE/relative) for relative in before}
        if before != after:
            raise RuntimeError('source or fixture bytes changed during reproduction')
        write_json(out/'completion.json', {'status': 'completed', 'completed_trials': 12288,
                                          'seconds': time.monotonic()-start, 'finished_utc': utc(),
                                          'witness_checks': checked, 'recorded_comparison': comparison})
        write_json(out/'MANIFEST.json', make_manifest(out))
        verify_manifest(out)
        print(json.dumps({'status': 'completed', **checked, 'recorded_comparison': comparison}, indent=2))
    except BaseException as error:
        write_json(out/'failure.json', {'status': 'failed_partial_preserved', 'error': type(error).__name__ + ': ' + str(error),
                                       'seconds': time.monotonic()-start, 'traceback': traceback.format_exc()})
        raise


def main():
    reject_optimized_mode()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'verify'])
    parser.add_argument('--output', type=Path, help='New directory for a reproduction; existing directory to verify')
    parser.add_argument('--compare-recorded', type=Path, help='Compare all trial fields other than timing with recorded evidence')
    args = parser.parse_args()
    if args.action == 'run':
        if args.output is None:
            parser.error('--output is required for run and must not already exist')
        run_original(args.output, args.compare_recorded)
    else:
        output = args.output or PUBLIC_RESULTS
        verify_manifest(output)
        _, checked = verify_output(output)
        print(json.dumps({'status': 'verified', **checked}, indent=2))


if __name__ == '__main__':
    main()
