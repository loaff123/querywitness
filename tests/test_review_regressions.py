"""Independent adversarial review regressions for the fail-closed contract."""
import unittest

from querywitness.artifacts import build_witness
from querywitness.engine import execute
from querywitness.schema import Schema
from querywitness.semantics import ordered_reason

SCHEMA = Schema.from_dict({'tables': [{'name': 't', 'columns': [
    {'name': 'x', 'type': 'INTEGER'}, {'name': 'g', 'type': 'TEXT'}]}]})
DATA = {'t': [[2, 'a'], [1, 'b']]}


class IndependentSemanticsReviewTests(unittest.TestCase):
    def test_sqlite_total_is_an_aggregate(self):
        self.assertEqual(execute(SCHEMA, DATA, 'SELECT TOTAL(x),g FROM t').status, 'unsupported')
        self.assertEqual(execute(SCHEMA, DATA, 'SELECT TOTAL(x) FROM t').status, 'ok')

    def test_having_source_column_beats_colliding_aggregate_alias(self):
        query = "SELECT SUM(x) AS g FROM t HAVING g='a'"
        self.assertEqual(execute(SCHEMA, DATA, query).status, 'unsupported')

    def test_compound_order_expression_must_not_resolve_source_as_alias(self):
        query = 'SELECT x,SUM(x) AS g FROM t GROUP BY x ORDER BY g+0,x,2'
        data = {'t': [[1, '30'], [1, '0'], [2, '20'], [2, '20']]}
        self.assertEqual(execute(SCHEMA, data, query).status, 'unsupported')

    def test_duplicate_aliases_cannot_fake_total_order(self):
        self.assertIsNotNone(ordered_reason('SELECT x AS a,g AS a FROM t ORDER BY 1,a'))

    def test_collation_cannot_hide_distinct_ordered_values(self):
        self.assertIsNotNone(ordered_reason('SELECT g COLLATE NOCASE FROM t ORDER BY 1'))
        self.assertIsNotNone(ordered_reason('SELECT c FROM (SELECT g COLLATE NOCASE AS c FROM t) ORDER BY c'))

    def test_derived_collation_cannot_choose_arbitrary_group_representative(self):
        query = 'SELECT g,COUNT(*) FROM (SELECT g COLLATE NOCASE AS g FROM t) GROUP BY g'
        self.assertEqual(execute(SCHEMA, DATA, query).status, 'unsupported')

    def test_ordered_artifacts_require_a_total_order(self):
        data = {'t': [[2, 'a'], [1, 'a']]}
        with self.assertRaises(ValueError):
            build_witness(SCHEMA, data, 'SELECT x FROM t', 'SELECT x FROM t ORDER BY x', policy='ordered')

    def test_deep_flat_expression_fails_closed(self):
        query = 'SELECT ' + '+'.join(['1'] * 1000)
        self.assertEqual(execute(SCHEMA, DATA, query).status, 'unsupported')

    def test_surrogate_sql_fails_closed(self):
        self.assertEqual(execute(SCHEMA, DATA, "SELECT '\ud800'").status, 'unsupported')


class IndependentArtifactReviewTests(unittest.TestCase):
    def test_sql_fixture_creates_parent_before_child_insert(self):
        import sqlite3
        from querywitness.artifacts import sql_fixture, replay
        schema = Schema.from_dict({'tables': [
            {'name': 'child', 'columns': [
                {'name': 'a', 'type': 'INTEGER'}, {'name': 'b', 'type': 'TEXT'},
                {'name': 'v', 'type': 'REAL'}], 'foreign_keys': [
                    {'columns': ['a', 'b'], 'references': {'table': 'parent', 'columns': ['a', 'b']}}]},
            {'name': 'parent', 'columns': [
                {'name': 'a', 'type': 'INTEGER'}, {'name': 'b', 'type': 'TEXT'}],
             'primary_key': ['a', 'b']}
        ]})
        data = {'parent': [[1, 'x']], 'child': [
            [1, 'x', 1.2345678901234567], [1, 'x', 1.2345678901234567]]}
        witness = build_witness(schema, data, 'SELECT v FROM child', 'SELECT DISTINCT v FROM child')
        self.assertEqual(replay(witness)['status'], 'reproduced')
        db = sqlite3.connect(':memory:')
        try:
            db.executescript(sql_fixture(witness))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT v FROM child').fetchall(), [(1.2345678901234567,)] * 2)
        finally:
            db.close()
