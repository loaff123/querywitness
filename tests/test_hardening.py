import unittest
from querywitness.schema import Schema, SchemaError
from querywitness.engine import execute, ExecutionLimits
from querywitness.search import search

S = Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'},{'name':'g','type':'TEXT'}]}]})
D = {'t':[[1,'a'],[2,'a'],[None,'b']]}

class HardeningTests(unittest.TestCase):
    def test_bare_aggregate_projection_excluded(self):
        for q in ['SELECT x, COUNT(*) FROM t', 'SELECT g, x, SUM(x) FROM t GROUP BY g', 'SELECT COALESCE(x, 0), SUM(x) FROM t', 'SELECT "x", COUNT(*) FROM t']:
            with self.subTest(sql=q): self.assertEqual(execute(S,D,q).status,'unsupported')
    def test_valid_grouped_and_nested_aggregates(self):
        for q in ['SELECT g, SUM(x) FROM t GROUP BY g', 'SELECT AVG(s) FROM (SELECT g, SUM(x) AS s FROM t GROUP BY g)', 'SELECT g, SUM(x)+1 FROM t GROUP BY g']:
            with self.subTest(sql=q): self.assertEqual(execute(S,D,q).status,'ok')
    def test_scalar_subquery_arbitrary_first_row_excluded(self):
        self.assertEqual(execute(S,D,'SELECT (SELECT x FROM t)').status,'unsupported')
    def test_window_excluded(self):
        self.assertEqual(execute(S,D,'SELECT SUM(x) OVER () FROM t').status,'unsupported')
    def test_real_lossy_integer_rejected_before_sqlite(self):
        s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'REAL'}]}]})
        for v in [2**63,2**53+1]:
            with self.subTest(v=v),self.assertRaises(SchemaError): s.validate_instance({'t':[[v]]})
    def test_bool_time_limit_rejected(self):
        with self.assertRaises(ValueError): ExecutionLimits(seconds=True)
    def test_search_provenance_complete(self):
        r=search(S,'SELECT x FROM t','SELECT x FROM t',trials=2,limits=ExecutionLimits(rows=42))
        self.assertEqual(r['execution_limits']['rows'],42)
        self.assertEqual(len(r['schema_sha256']),64)
    def test_search_deadline_and_rows_config(self):
        r=search(S,'SELECT x FROM t','SELECT x FROM t',trials=1,max_rows=2,seconds=5)
        self.assertEqual(r['max_rows'],2)

class ReviewRegressionTests(unittest.TestCase):
    def test_cast_alias_does_not_hide_bare_column(self):
        self.assertEqual(execute(S,D,'SELECT CAST(SUM(x) AS REAL)+g FROM t').status,'unsupported')
    def test_quoted_aggregate_name_detected(self):
        self.assertEqual(execute(S,D,'SELECT "sum"(x), g FROM t').status,'unsupported')
    def test_qualified_groups_not_pooled(self):
        self.assertEqual(execute(S,D,'SELECT a.g,SUM(b.x) FROM t a JOIN t b ON 1=1 GROUP BY a.x,b.g').status,'unsupported')
    def test_scalar_min_cannot_hide_bare_column(self):
        self.assertEqual(execute(S,D,'SELECT MIN(x,2),COUNT(*) FROM t').status,'unsupported')
    def test_aggregate_having_bare_column_rejected(self):
        self.assertEqual(execute(S,D,'SELECT SUM(x) FROM t HAVING g="a"').status,'unsupported')
    def test_arithmetic_aggregate_is_supported(self):
        self.assertEqual(execute(S,D,'SELECT SUM(x)*2 FROM t').status,'ok')
    def test_total_aggregate_does_not_hide_bare_column(self):
        self.assertEqual(execute(S,D,'SELECT TOTAL(x),g FROM t').status,'unsupported')
    def test_having_alias_collision_does_not_hide_source(self):
        self.assertEqual(execute(S,D,"SELECT SUM(x) AS g FROM t HAVING g='a'").status,'unsupported')
    def test_total_valid_aggregate_supported(self):
        self.assertEqual(execute(S,D,'SELECT TOTAL(x) FROM t').status,'ok')
    def test_deep_ast_rejected_cleanly(self):
        self.assertEqual(execute(S,D,'SELECT '+ '+'.join(['1']*1000)).status,'unsupported')
    def test_sql_surrogate_rejected_cleanly(self):
        self.assertEqual(execute(S,D,"SELECT '\ud800'").status,'unsupported')
    def test_search_invalid_unicode_is_clean_input_error(self):
        with self.assertRaises(ValueError):search(S,"SELECT '\ud800'",'SELECT x FROM t',trials=1)
