"""Independent, finite-pool compiler contract tests (no external corpus)."""
import dataclasses
import hashlib
import json
import unittest

from querywitness.generate import GenerationError
from querywitness.query_plan import QueryPlan, compile_plan
from querywitness.schema import Schema, _cell


def schema(*tables):
    return Schema.from_dict({'tables': list(tables)})


def table(name, columns, **kwargs):
    return dict(name=name, columns=[dict(name=n, type=k, **extra) for n, k, extra in columns], **kwargs)


def pool(plan, table_name, column):
    return {(t, c): values for t, c, values in plan.pools}[table_name, column]


class QueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.schema = schema(table('items', [('id', 'INTEGER', {}), ('n', 'INTEGER', {}), ('tag', 'TEXT', {}), ('r', 'REAL', {})], primary_key=['id']))

    def test_defaults_keys_and_immutable_manifest(self):
        p = compile_plan(self.schema, 'SELECT id FROM items', 'SELECT n FROM items', max_rows=32)
        self.assertIsInstance(p, QueryPlan)
        self.assertTrue(set(range(1, 33)) <= set(pool(p, 'items', 'id')))
        self.assertTrue({-2, -1, 0, 1, 2, 10, 100} <= set(pool(p, 'items', 'id')))
        self.assertEqual(p.max_rows, 32)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.max_rows = 1
        manifest = p.to_dict()
        self.assertEqual(manifest['generator_version'], 'query-aware-1')
        self.assertEqual(manifest['sqlglot_version'], '27.29.0')
        self.assertEqual(p.manifest, manifest)
        manifest['effective_domains'][0]['pool'].append('MUTATED')
        self.assertNotEqual(p.to_dict(), manifest)
        self.assertEqual(len(p.schema_sha256), 64)
        json.dumps(p.to_dict(), allow_nan=False)

    def test_integer_neighbors_text_predicates_and_pair_symmetry(self):
        a = "SELECT id FROM items WHERE n >= 450 AND tag IN ('lavender', 'café')"
        b = "SELECT id FROM items WHERE n BETWEEN -72 AND 93 AND tag = 'violet'"
        p, q = compile_plan(self.schema, a, b), compile_plan(self.schema, b, a)
        self.assertEqual(p.pools, q.pools)
        self.assertEqual(p.preferred, q.preferred)
        self.assertEqual(p.joins, q.joins)
        self.assertEqual(p.groups, q.groups)
        self.assertEqual(p.counts, q.counts)
        self.assertTrue({449, 450, 451, -73, -72, -71, 92, 93, 94} <= set(pool(p, 'items', 'n')))
        self.assertTrue({'lavender', 'café', 'violet'} <= set(pool(p, 'items', 'tag')))
        self.assertEqual(p.to_dict()['source_sha256']['reference'], hashlib.sha256(a.encode()).hexdigest())
        self.assertEqual(p.to_dict()['source_sha256']['candidate'], hashlib.sha256(b.encode()).hexdigest())

    def test_explicit_domains_are_never_widened_and_only_legal_preference_remains(self):
        s = schema(table('t', [('v', 'INTEGER', {'domain': [40, 41]}), ('s', 'TEXT', {'domain': ['z']})]))
        p = compile_plan(s, "SELECT v FROM t WHERE v=40 AND s='other'", 'SELECT v FROM t WHERE v=900')
        self.assertEqual(set(pool(p, 't', 'v')), {40, 41})
        self.assertEqual(pool(p, 't', 's'), ('z',))
        self.assertTrue(all(e['explicit_domain'] for e in p.to_dict()['effective_domains']))
        self.assertTrue(p.to_dict()['skips'])
        for t, c, values in p.preferred:
            self.assertTrue(set(values) <= set(pool(p, t, c)))

    def test_signed64_endpoints_do_not_overflow(self):
        p = compile_plan(self.schema, 'SELECT n FROM items WHERE n=-9223372036854775808', 'SELECT n FROM items WHERE n=9223372036854775807')
        values = pool(p, 'items', 'n')
        self.assertTrue({-(2**63), -(2**63)+1, 2**63-2, 2**63-1} <= set(values))
        self.assertTrue(all(_cell(v, 'INTEGER', False) for v in values))

    def test_huge_integer_literal_is_skipped_without_admitting_neighbor(self):
        p = compile_plan(self.schema, 'SELECT n FROM items WHERE n=9223372036854775808', 'SELECT n FROM items')
        self.assertNotIn(2**63-1, pool(p, 'items', 'n'))
        self.assertTrue(p.to_dict()['skips'])

    def test_pool_cap_retains_defaults_and_primary_keys_deterministically(self):
        sql = 'SELECT id FROM items WHERE id IN (' + ','.join(str(n) for n in range(1000, 1200)) + ')'
        p = compile_plan(self.schema, sql, 'SELECT id FROM items', max_rows=32)
        self.assertEqual(len(pool(p, 'items', 'id')), 64)
        self.assertTrue(set(range(1, 33)) <= set(pool(p, 'items', 'id')))
        self.assertTrue({-2, -1, 0, 10, 100} <= set(pool(p, 'items', 'id')))
        self.assertEqual(p.pools, compile_plan(self.schema, 'SELECT id FROM items', sql, 32).pools)
        self.assertTrue(p.to_dict()['warnings'])

    def test_real_and_coercion_hints_are_skipped(self):
        p = compile_plan(self.schema, "SELECT n FROM items WHERE r=125.5 OR n='341' OR CAST(n AS INTEGER)=77", "SELECT tag FROM items WHERE tag > 'zzzz' OR tag LIKE 'prefix%' OR n=44.5")
        self.assertNotIn(125.5, pool(p, 'items', 'r'))
        self.assertNotIn(341, pool(p, 'items', 'n'))
        self.assertNotIn(77, pool(p, 'items', 'n'))
        self.assertNotIn('zzzz', pool(p, 'items', 'tag'))
        self.assertNotIn('prefix%', pool(p, 'items', 'tag'))
        self.assertTrue(p.to_dict()['skips'])

    def test_aliases_case_insensitivity_and_correlated_exists(self):
        s = schema(table('OuterRows', [('x', 'INTEGER', {})]), table('InnerRows', [('y', 'INTEGER', {})]))
        p = compile_plan(s, 'SELECT o.x FROM OuterRows o WHERE EXISTS (SELECT 1 FROM InnerRows i WHERE i.y=o.x AND x=61)', 'SELECT O.X FROM OuterRows O WHERE O.X=73')
        self.assertTrue({60,61,62,72,73,74} <= set(pool(p, 'OuterRows', 'x')))
        self.assertIn((('InnerRows', 'y'), ('OuterRows', 'x')), p.joins)

    def test_local_alias_shadows_outer_alias(self):
        s = schema(table('a', [('x', 'INTEGER', {})]), table('b', [('x', 'INTEGER', {})]))
        p = compile_plan(s, 'SELECT z.x FROM a z WHERE EXISTS (SELECT 1 FROM b z WHERE z.x=711)', 'SELECT x FROM a')
        self.assertIn(711, pool(p, 'b', 'x'))
        self.assertNotIn(711, pool(p, 'a', 'x'))

    def test_ambiguous_unqualified_and_duplicate_alias_are_skipped(self):
        s = schema(table('a', [('x', 'INTEGER', {})]), table('b', [('x', 'INTEGER', {})]))
        p = compile_plan(s, 'SELECT a.x FROM a JOIN b ON x=801', 'SELECT p.x FROM a p JOIN b p ON p.x=811')
        self.assertFalse({800,801,802,810,811,812} & set(pool(p, 'a', 'x')))
        self.assertFalse({800,801,802,810,811,812} & set(pool(p, 'b', 'x')))
        self.assertTrue(p.to_dict()['skips'])

    def test_cte_and_derived_outputs_are_not_guessed_as_base_columns(self):
        p = compile_plan(self.schema, 'WITH items AS (SELECT 1 AS n) SELECT n FROM items WHERE n=811', 'SELECT n FROM (SELECT n FROM items) d WHERE n=821')
        self.assertNotIn(811, pool(p, 'items', 'n'))
        self.assertNotIn(821, pool(p, 'items', 'n'))
        self.assertTrue(p.to_dict()['skips'])

    def test_unknown_or_derived_source_blocks_unqualified_guess(self):
        p = compile_plan(self.schema, 'SELECT n FROM items JOIN missing m ON n=831', 'SELECT items.n FROM items JOIN (SELECT 1 AS n) d ON n=841')
        self.assertNotIn(831, pool(p, 'items', 'n'))
        self.assertNotIn(841, pool(p, 'items', 'n'))

    def test_natural_and_using_include_all_common_columns_and_groups(self):
        s = schema(table('a', [('x','INTEGER',{}), ('y','TEXT',{}), ('z','INTEGER',{})]), table('b', [('x','INTEGER',{}), ('y','TEXT',{})]))
        p = compile_plan(s, 'SELECT a.x FROM a NATURAL JOIN b GROUP BY a.x', 'SELECT a.x FROM a JOIN b USING(x,y)')
        self.assertEqual(p.joins, ((('a','x'),('b','x')), (('a','y'),('b','y'))))
        self.assertEqual(p.groups, (('a','x'),))

    def test_equijoin_union_propagates_only_compatible_legal_values(self):
        s = schema(table('a', [('x','INTEGER',{})]), table('b', [('x','INTEGER',{'domain':[77,78]})]), table('c', [('x','TEXT',{})]))
        p = compile_plan(s, 'SELECT a.x FROM a JOIN b ON a.x=b.x WHERE a.x=77', 'SELECT a.x FROM a JOIN c ON a.x=c.x')
        self.assertTrue({77,78} <= set(pool(p, 'a', 'x')))
        self.assertEqual(pool(p, 'b', 'x'), (77,78))
        self.assertEqual(p.joins, ((('a','x'),('b','x')),))
        self.assertNotIn('77', pool(p, 'c', 'x'))

    def test_foreign_key_pools_include_legal_parent_values(self):
        s = schema(table('p', [('id','INTEGER',{'domain':[77]})], primary_key=['id']), table('c', [('pid','INTEGER',{})], foreign_keys=[{'columns':['pid'],'references':{'table':'p','columns':['id']}}]))
        p = compile_plan(s, 'SELECT id FROM p', 'SELECT pid FROM c')
        self.assertIn(77, pool(p, 'c', 'pid'))

    def test_count_thresholds_and_conservative_upper_bound_warning(self):
        p = compile_plan(self.schema, 'SELECT COUNT(*) FROM items HAVING COUNT(*)>=3', 'SELECT COUNT(n) FROM items HAVING COUNT(n)>90')
        self.assertTrue({2,3,4} <= set(p.counts))
        self.assertTrue(all(type(n) is int and 0 <= n <= 8 for n in p.counts))
        self.assertTrue(any('upper bound' in str(w).lower() for w in p.to_dict()['warnings']))

    def test_count_join_bound_accounts_for_multiplicity_and_outer_joins(self):
        s = schema(table('a', [('x','INTEGER',{})]), table('b', [('x','INTEGER',{})]))
        p = compile_plan(s, 'SELECT COUNT(*) FROM a CROSS JOIN b HAVING COUNT(*)>64', 'SELECT COUNT(*) FROM a FULL JOIN b ON a.x=b.x HAVING COUNT(*)>128')
        self.assertTrue(p.to_dict()['warnings'])
        # Warnings may narrow to base cross/inner joins; no equivalence claim.
        self.assertNotIn('equivalent', json.dumps(p.to_dict()).lower())

    def test_schema_hash_matches_existing_ascii_serialization(self):
        s = schema(table('t', [('v','TEXT',{'domain':['café']})]))
        p = compile_plan(s, 'SELECT v FROM t', 'SELECT v FROM t')
        expected = hashlib.sha256(json.dumps(s.to_dict(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(p.schema_sha256, expected)

    def test_no_resolved_hints_warns_and_stays_finite(self):
        p = compile_plan(self.schema, 'SELECT n FROM items', 'SELECT n FROM items')
        self.assertTrue(any('no query hints' in str(w).lower() for w in p.to_dict()['warnings']))

    def test_sqlite_alias_case_rules_do_not_fold_unicode(self):
        s = schema(table('a', [('x','INTEGER',{})]), table('b', [('x','INTEGER',{})]))
        p = compile_plan(s, 'SELECT "Å".x FROM a "Å" JOIN b "å" ON "Å".x=731 AND "å".x=741', 'SELECT x FROM a')
        self.assertIn(731, pool(p, 'a', 'x'))
        self.assertNotIn(741, pool(p, 'a', 'x'))
        self.assertIn(741, pool(p, 'b', 'x'))
        self.assertNotIn(731, pool(p, 'b', 'x'))

    def test_manually_constructed_schema_cannot_break_pool_bound(self):
        from querywitness.schema import Column, Table
        malformed = Schema((Table('t', (Column('x', 'INTEGER', True, tuple(range(65))),), (), (), ()),))
        with self.assertRaises(GenerationError):
            compile_plan(malformed, 'SELECT x FROM t', 'SELECT x FROM t')

    def test_projection_alias_not_inferred_as_an_outer_column(self):
        s = schema(table('a', [('x','INTEGER',{})]), table('b', [('y','INTEGER',{})]))
        p = compile_plan(s, 'SELECT x FROM a WHERE EXISTS (SELECT y+1 AS x FROM b WHERE x=731)', 'SELECT x FROM a')
        self.assertNotIn(731, pool(p, 'a', 'x'))
        self.assertNotIn(731, pool(p, 'b', 'y'))
        self.assertTrue(p.to_dict()['skips'])

    def test_bad_sql_and_parameters_raise_generation_error(self):
        for query in ['', 'SELECT 1; SELECT 2', 'DELETE FROM items', 'SELECT n FROM items LIMIT 2', 'SELECT \0', "SELECT '\ud800'"]:
            with self.subTest(query=repr(query)), self.assertRaises(GenerationError):
                compile_plan(self.schema, query, 'SELECT 1')
        for value in [0,33,True,1.5]:
            with self.subTest(max_rows=value), self.assertRaises(GenerationError):
                compile_plan(self.schema, 'SELECT 1', 'SELECT 1', max_rows=value)
        with self.assertRaises(GenerationError):
            compile_plan(self.schema, 'SELECT n FROM items', 'SELECT 1', sql_bytes=8)
        for value in [0,True,-1,'x']:
            with self.subTest(sql_bytes=value), self.assertRaises(GenerationError):
                compile_plan(self.schema, 'SELECT 1', 'SELECT 1', sql_bytes=value)


if __name__ == '__main__':
    unittest.main()
