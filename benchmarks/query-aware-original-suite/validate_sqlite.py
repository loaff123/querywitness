#!/usr/bin/env python3
"""Standalone oracle: Python stdlib only, no QueryWitness imports or generator calls."""
import argparse
import collections
import hashlib
import itertools
import json
import math
import sqlite3
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def quote(name):
    return '"' + name.replace('"', '""') + '"'

def cell_key(value):
    if value is None:
        return ('null',)
    if type(value) is int:
        return ('number', Fraction(value))
    if type(value) is float and math.isfinite(value):
        return ('number', Fraction.from_float(value))
    if type(value) is str:
        return ('text', value)
    if type(value) is bytes:
        return ('blob', value)
    raise AssertionError(f'Unsupported result cell: {value!r}')

def bag(rows):
    return collections.Counter(tuple(cell_key(v) for v in row) for row in rows)

def validate_input(schema, instance):
    tables = schema['tables']
    assert set(instance) == {t['name'] for t in tables}, 'instance table mismatch'
    assert sum(len(rows) for rows in instance.values()) <= 2000
    for t in tables:
        for row in instance[t['name']]:
            assert len(row) == len(t['columns']), 'row width mismatch'
            for c, value in zip(t['columns'], row):
                if value is None:
                    assert c.get('nullable', True) and c['name'] not in t.get('primary_key', []), 'illegal NULL'
                    continue
                kind = c['type']
                if kind == 'INTEGER':
                    assert type(value) is int and -(2**63) <= value < 2**63, 'illegal INTEGER'
                elif kind == 'REAL':
                    assert type(value) in (int, float) and math.isfinite(value), 'illegal REAL'
                    assert abs(value) <= (2**53 if type(value) is int else 1e100), 'REAL range'
                elif kind == 'TEXT':
                    assert type(value) is str and '\0' not in value, 'illegal TEXT'
                    assert len(value.encode('utf-8')) <= 4096, 'TEXT length'
                else:
                    raise AssertionError('unknown input type')
                if 'domain' in c:
                    assert any(cell_key(value) == cell_key(v) for v in c['domain']), 'outside explicit domain'

def build_database(schema, instance):
    validate_input(schema, instance)
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys = ON')
    assert db.execute('PRAGMA foreign_keys').fetchone() == (1,)
    for t in schema['tables']:
        clauses = []
        for c in t['columns']:
            nonnull = not c.get('nullable', True) or c['name'] in t.get('primary_key', [])
            clauses.append(quote(c['name']) + ' ' + c['type'] + (' NOT NULL' if nonnull else ''))
        if t.get('primary_key'):
            clauses.append('PRIMARY KEY (' + ', '.join(map(quote, t['primary_key'])) + ')')
        for group in t.get('unique', []):
            clauses.append('UNIQUE (' + ', '.join(map(quote, group)) + ')')
        for key in t.get('foreign_keys', []):
            ref = key['references']
            clauses.append('FOREIGN KEY (' + ', '.join(map(quote, key['columns'])) + ') REFERENCES ' +
                           quote(ref['table']) + ' (' + ', '.join(map(quote, ref['columns'])) +
                           ') DEFERRABLE INITIALLY DEFERRED')
        db.execute('CREATE TABLE ' + quote(t['name']) + ' (' + ', '.join(clauses) + ')')
    try:
        db.execute('BEGIN')
        for t in schema['tables']:
            db.executemany('INSERT INTO ' + quote(t['name']) + ' VALUES (' +
                           ', '.join('?' for _ in t['columns']) + ')', instance[t['name']])
        db.commit()
        assert not db.execute('PRAGMA foreign_key_check').fetchall(), 'foreign key violation'
        return db
    except BaseException:
        db.close()
        raise

def execute_pair(case, instance):
    db = build_database(case['schema'], instance)
    try:
        observations = []
        for side in ('reference', 'candidate'):
            cursor = db.execute(case[side + '_sql'])
            columns = len(cursor.description)
            rows = [list(row) for row in cursor.fetchall()]
            assert columns == case['expected_column_count'], f'{side} column count'
            observations.append((columns, rows))
        return observations
    finally:
        db.close()

def check_manifest():
    manifest = ROOT / 'SHA256SUMS'
    assert manifest.exists(), 'Missing freeze manifest'
    for line in manifest.read_text().splitlines():
        expected, filename = line.split('  ', 1)
        assert '/' not in filename and filename not in ('.', '..'), 'unexpected manifest path'
        actual = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        assert actual == expected, f'Frozen artifact changed: {filename}'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bootstrap', action='store_true', help='Author-only initial verification before manifest creation')
    args = parser.parse_args()
    if not args.bootstrap:
        check_manifest()
    suite = json.loads((ROOT / 'fixtures.json').read_text(encoding='utf-8'))
    results = []
    for case in suite['cases']:
        observed_difference = False
        for f in case['fixtures']:
            ref, cand = execute_pair(case, f['instance'])
            assert bag(ref[1]) == bag(f['expected_reference_rows']), (case['id'], f['name'], 'reference mismatch', ref[1])
            assert bag(cand[1]) == bag(f['expected_candidate_rows']), (case['id'], f['name'], 'candidate mismatch', cand[1])
            equal = ref[0] == cand[0] and bag(ref[1]) == bag(cand[1])
            observed_difference |= not equal
            within_bound = all(len(rows) <= 8 for rows in f['instance'].values())
            if case['global_relation'] == 'equivalent':
                assert equal, 'equivalent control false positive'
            if within_bound and case['relation_with_at_most_8_rows_per_table'] == 'equivalent':
                assert equal, 'bounded-equivalent false positive'
            results.append({'case_id': case['id'], 'fixture': f['name'], 'equal': equal,
                            'within_row8': within_bound, 'reference_rows': ref[1], 'candidate_rows': cand[1]})
        assert observed_difference == (case['global_relation'] == 'different'), case['id']

    # Independent exhaustive finite checks, not generated QueryWitness data.
    by_id = {c['id']: c for c in suite['cases']}
    exhaustive = 0
    restricted = by_id['original_05_domain_forbids_literal']
    for n in range(9):
        for values in itertools.combinations_with_replacement([None, 3, 19], n):
            ref, cand = execute_pair(restricted, {'restricted': [[v] for v in values]})
            assert bag(ref[1]) == bag(cand[1]) == bag([])
            exhaustive += 1
    beyond = by_id['original_13_count_beyond_row8']
    for n in range(9):
        for values in itertools.combinations_with_replacement(['a', 'b'], n):
            ref, cand = execute_pair(beyond, {'ballot': [[v] for v in values]})
            assert bag(ref[1]) == bag(cand[1]) == bag([])
            exhaustive += 1

    # Ensure the independent input checker rejects an excluded literal and FK violations.
    for case, instance in [
        (restricted, {'restricted': [[-460213]]}),
        (by_id['original_10_composite_key_fk'], {'parent': [[1, 7, 'north']], 'child': [[2, 7, 'orphan']]}),
    ]:
        try:
            db = build_database(case['schema'], instance)
        except (AssertionError, sqlite3.IntegrityError):
            pass
        else:
            db.close()
            raise AssertionError('Negative legality self-test did not reject fixture')

    output = {'status': 'PASS', 'sqlite_version': sqlite3.sqlite_version,
              'suite_classification': suite['classification'], 'case_count': len(suite['cases']),
              'hand_authored_fixture_count': len(results),
              'globally_different_pairs': sum(c['global_relation'] == 'different' for c in suite['cases']),
              'globally_equivalent_controls': sum(c['global_relation'] == 'equivalent' for c in suite['cases']),
              'row8_different_pairs': sum(c['relation_with_at_most_8_rows_per_table'] == 'different' for c in suite['cases']),
              'additional_exhaustive_bounded_instances': exhaustive,
              'negative_legality_checks': 2, 'results': results}
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
