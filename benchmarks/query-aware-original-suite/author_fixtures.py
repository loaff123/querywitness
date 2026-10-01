#!/usr/bin/env python3
"""Original fixture authoring source. Expected rows below are hand-authored."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent

def col(name, kind='INTEGER', nullable=True, domain=None):
    out = {'name': name, 'type': kind, 'nullable': nullable}
    if domain is not None:
        out['domain'] = domain
    return out

def table(name, columns, primary_key=(), foreign_keys=(), unique=()):
    return {'name': name, 'columns': columns, 'primary_key': list(primary_key),
            'unique': list(unique), 'foreign_keys': list(foreign_keys)}

def fk(columns, parent, parent_columns):
    return {'columns': columns, 'references': {'table': parent, 'columns': parent_columns}}

def fixture(name, instance, ref, cand):
    return {'name': name, 'instance': instance, 'expected_reference_rows': ref,
            'expected_candidate_rows': cand}

cases = []
def case(identifier, tags, tables, reference, candidate, relation, row8, rationale, fixtures):
    cases.append({'id': identifier, 'tags': tags, 'schema': {'tables': tables},
                  'reference_sql': reference, 'candidate_sql': candidate,
                  'policy': 'bag', 'global_relation': relation,
                  'relation_with_at_most_8_rows_per_table': row8,
                  'oracle_rationale': rationale, 'fixtures': fixtures})

for identifier, value, tag in [
    ('original_01_negative_literal', -734921, 'uncommon_negative_integer'),
    ('original_02_near_int64_max', 9223372036854775799, 'near_signed64_max'),
    ('original_03_near_int64_min', -9223372036854775799, 'near_signed64_min'),
]:
    case(identifier, [tag, 'literal'], [table('reading', [col('value')])],
         f'SELECT value FROM reading WHERE value = {value}',
         'SELECT value FROM reading WHERE value = 0', 'different', 'different',
         'The literal row and zero row are distinct exact signed-64 INTEGER values.',
         [fixture('literal_zero_neighbor_and_null', {'reading': [[value], [0], [value + 1], [None]]},
                  [[value]], [[0]])])

unicode_decomposed = 'ma\u00f1ana/\u96ea/\U0001f642/e\u0301'
unicode_composed = 'ma\u00f1ana/\u96ea/\U0001f642/\u00e9'
case('original_04_exact_unicode', ['exact_unicode', 'text_literal', 'no_normalization'],
     [table('label', [col('text', 'TEXT')])],
     f"SELECT text FROM label WHERE text = '{unicode_decomposed}'",
     f"SELECT text FROM label WHERE text = '{unicode_composed}'", 'different', 'different',
     'SQLite BINARY text equality distinguishes the final decomposed e+U+0301 from U+00E9.',
     [fixture('both_normalization_forms', {'label': [[unicode_decomposed], [unicode_composed], [None]]},
              [[unicode_decomposed]], [[unicode_composed]])])

case('original_05_domain_forbids_literal', ['explicit_domain', 'equivalent_control'],
     [table('restricted', [col('value', domain=[3, 19])])],
     'SELECT value FROM restricted WHERE value = -460213',
     'SELECT value FROM restricted WHERE 0 = 1', 'equivalent', 'equivalent',
     'Legal values are only 3, 19, or NULL. Equality to -460213 is never TRUE; both bags are always empty.',
     [fixture('all_legal_values_and_duplicate', {'restricted': [[3], [19], [None], [3]]}, [], [])])

case('original_06_qualified_alias', ['aliases', 'literal'],
     [table('measurement', [col('id', nullable=False), col('signal')], primary_key=['id'])],
     'SELECT m.id AS result_id FROM measurement AS m WHERE m.signal = 48263',
     'SELECT q.id AS ignored_output_name FROM measurement AS q WHERE q.signal = 48264',
     'different', 'different', 'Qualified references resolve to the same table; the two signal literals select different primary keys.',
     [fixture('two_signals', {'measurement': [[5, 48263], [6, 48264]]}, [[5]], [[6]])])

case('original_07_duplicate_sensitive_join', ['join', 'bag_multiplicity', 'distinct'],
     [table('source', [col('key', nullable=False), col('label', 'TEXT', False)], primary_key=['key']),
      table('copy', [col('key', nullable=False)])],
     'SELECT s.label FROM source AS s JOIN copy AS c ON c.key = s.key',
     'SELECT DISTINCT s.label FROM source AS s JOIN copy AS c ON c.key = s.key',
     'different', 'different', 'Two matching copy rows repeat the same projected label; DISTINCT removes one occurrence.',
     [fixture('one_source_two_copies', {'source': [[23, 'repeated']], 'copy': [[23], [23]]},
              [['repeated'], ['repeated']], [['repeated']])])

case('original_08_correlated_exists', ['correlated_exists', 'aliases', 'foreign_key'],
     [table('account', [col('id', nullable=False)], primary_key=['id']),
      table('event', [col('account_id', nullable=False), col('code', nullable=False)],
            foreign_keys=[fk(['account_id'], 'account', ['id'])])],
     'SELECT a.id FROM account AS a WHERE EXISTS (SELECT 1 FROM event AS e WHERE e.account_id = a.id AND e.code = 61279)',
     'SELECT a.id FROM account AS a WHERE EXISTS (SELECT 1 FROM event AS e WHERE e.code = 61279)',
     'different', 'different', 'Only account 11 owns the qualifying event, while the uncorrelated predicate also selects account 12.',
     [fixture('one_owner_one_nonowner', {'account': [[11], [12]], 'event': [[11, 61279]]}, [[11]], [[11], [12]])])

case('original_09_multicolumn_natural_join', ['natural_join', 'multicolumn_join', 'text'],
     [table('left_side', [col('key', nullable=False), col('region', 'TEXT', False), col('payload', 'TEXT', False)]),
      table('right_side', [col('key', nullable=False), col('region', 'TEXT', False), col('score', nullable=False)])],
     'SELECT l.payload, r.score FROM left_side AS l NATURAL JOIN right_side AS r',
     'SELECT l.payload, r.score FROM left_side AS l JOIN right_side AS r ON l.key = r.key',
     'different', 'different', 'NATURAL JOIN equates both shared columns key and region; the candidate omits region.',
     [fixture('same_key_two_regions', {'left_side': [[7, 'outer', 'chosen']], 'right_side': [[7, 'inner', 10], [7, 'outer', 20]]},
              [['chosen', 20]], [['chosen', 10], ['chosen', 20]])])

case('original_10_composite_key_fk', ['composite_primary_key', 'composite_foreign_key', 'join'],
     [table('parent', [col('tenant', nullable=False), col('code', nullable=False), col('label', 'TEXT', False)],
            primary_key=['tenant', 'code']),
      table('child', [col('tenant', nullable=False), col('code', nullable=False), col('note', 'TEXT', False)],
            primary_key=['tenant', 'code'], foreign_keys=[fk(['tenant', 'code'], 'parent', ['tenant', 'code'])])],
     'SELECT c.note, p.label FROM child AS c JOIN parent AS p ON c.tenant = p.tenant AND c.code = p.code',
     'SELECT c.note, p.label FROM child AS c JOIN parent AS p ON c.code = p.code',
     'different', 'different', 'The child references exactly (1,7). Dropping the tenant join predicate incorrectly matches parent (2,7).',
     [fixture('two_tenants_reuse_code', {'parent': [[1, 7, 'north'], [2, 7, 'south']], 'child': [[1, 7, 'chosen']]},
              [['chosen', 'north']], [['chosen', 'north'], ['chosen', 'south']])])

case('original_11_null_predicate', ['null_semantics'],
     [table('maybe', [col('value')])],
     'SELECT value FROM maybe WHERE value IS NULL',
     'SELECT value FROM maybe WHERE value = NULL', 'different', 'different',
     'IS NULL selects the NULL row; equality to NULL evaluates UNKNOWN even for NULL.',
     [fixture('null_and_integer', {'maybe': [[None], [4]]}, [[None]], [])])

count_table = table('ballot', [col('category', 'TEXT', False)])
case('original_12_count_within_row8', ['count_threshold', 'within_row8'], [count_table],
     'SELECT category, COUNT(*) FROM ballot GROUP BY category HAVING COUNT(*) >= 7',
     'SELECT category, COUNT(*) FROM ballot GROUP BY category HAVING COUNT(*) >= 8',
     'different', 'different', 'Exactly seven rows in one group satisfy only the reference HAVING predicate.',
     [fixture('seven_votes', {'ballot': [['a']] * 7}, [['a', 7]], []),
      fixture('eight_votes_control', {'ballot': [['a']] * 8}, [['a', 8]], [['a', 8]]),
      fixture('empty_control', {'ballot': []}, [], [])])

case('original_13_count_beyond_row8', ['count_threshold', 'beyond_row8', 'bounded_equivalent'], [count_table],
     'SELECT category, COUNT(*) FROM ballot GROUP BY category HAVING COUNT(*) >= 9',
     'SELECT category, COUNT(*) FROM ballot GROUP BY category HAVING COUNT(*) >= 10',
     'different', 'equivalent', 'No group in a table of at most eight rows can reach either threshold. Exactly nine rows are a global witness.',
     [fixture('nine_votes_outside_row8', {'ballot': [['a']] * 9}, [['a', 9]], []),
      fixture('eight_votes_bounded_control', {'ballot': [['a']] * 8}, [], []),
      fixture('ten_votes_control', {'ballot': [['a']] * 10}, [['a', 10]], [['a', 10]])])

case('original_14_ordinary_equivalent', ['equivalent_control', 'ordinary_predicate', 'null_semantics'],
     [table('number', [col('value')])],
     'SELECT value FROM number WHERE value <= 37',
     'SELECT value FROM number WHERE NOT (value > 37)', 'equivalent', 'equivalent',
     'For legal INTEGER values the predicates have identical truth values; both are UNKNOWN on NULL and preserve duplicates.',
     [fixture('around_boundary_and_null', {'number': [[36], [37], [37], [38], [None], [-4]]},
              [[36], [37], [37], [-4]], [[36], [37], [37], [-4]])])

case('original_15_redundant_join_equivalent', ['equivalent_control', 'redundant_join', 'foreign_key', 'primary_key'],
     [table('lookup', [col('id', nullable=False)], primary_key=['id']),
      table('record', [col('id', nullable=False), col('lookup_id', nullable=False)], primary_key=['id'],
            foreign_keys=[fk(['lookup_id'], 'lookup', ['id'])])],
     'SELECT r.id FROM record AS r',
     'SELECT r.id FROM record AS r JOIN lookup AS l ON r.lookup_id = l.id', 'equivalent', 'equivalent',
     'The non-NULL foreign key guarantees a parent exists and its primary key guarantees exactly one match per record.',
     [fixture('shared_parent_and_unused_parent', {'lookup': [[2], [8], [9]], 'record': [[31, 2], [32, 2], [33, 8]]},
              [[31], [32], [33]], [[31], [32], [33]]),
      fixture('empty_both_tables', {'lookup': [], 'record': []}, [], [])])

case('original_16_redundant_count_equivalent', ['equivalent_control', 'redundant_count_predicate', 'null_group'],
     [table('tag', [col('category', 'TEXT')])],
     'SELECT category, COUNT(*) FROM tag GROUP BY category',
     'SELECT category, COUNT(*) FROM tag GROUP BY category HAVING COUNT(*) >= 1',
     'equivalent', 'equivalent', 'Every emitted GROUP BY group contains at least one input row; empty input emits no group.',
     [fixture('duplicate_and_null_groups', {'tag': [[None], ['k'], ['k']]}, [[None, 1], ['k', 2]], [[None, 1], ['k', 2]]),
      fixture('empty_control', {'tag': []}, [], [])])

for c in cases:
    c['expected_column_count'] = 2 if c['id'].split('_')[1] in {'09', '10', '12', '13', '16'} else 1

payload = {
    'suite_name': 'QueryWitness original query-aware development validation',
    'format_version': 1,
    'classification': 'newly authored development validation; NOT external generalization',
    'provenance': {
        'author': 'Independently authored original fixtures, without inspecting generator implementation or external corpus',
        'authored_utc_date': '2026-09-30',
        'source_used': 'querywitness/docs/CONTRACT.md only',
        'product_generator_inspected': False,
        'external_corpus_or_results_inspected': False,
        'expected_rows': 'Hand-authored in author_fixtures.py before any generator execution; independently checked using Python standard-library sqlite3.',
        'freeze_rule': 'Freeze fixtures.json, validator, authoring source, and this provenance with SHA256SUMS before generator runs; preserve these bytes during evaluation.'
    },
    'evaluation_bound': {'max_rows_per_table': 8, 'policy': 'bag'},
    'interpretation': 'Different means a demonstrated witness exists, not that an incomplete generator must find it. Equivalent controls must never produce a false-positive witness. original_13 is globally different but provably equivalent within row8.',
    'cases': cases,
}
(ROOT / 'fixtures.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Authored {len(cases)} pairs, {sum(len(c["fixtures"]) for c in cases)} fixtures')
