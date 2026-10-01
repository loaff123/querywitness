import unittest
from querywitness.schema import Schema
from querywitness.search import search

class QueryAwareSearchTests(unittest.TestCase):
    def setUp(self):
        self.schema=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
    def test_new_strategy_records_plan_accounting_and_detects_literal(self):
        result=search(self.schema,'SELECT x FROM t WHERE x=727','SELECT x FROM t WHERE x=728',strategy='query_aware',trials=64)
        self.assertEqual(result['status'],'counterexample')
        self.assertIn('generation_plan',result)
        self.assertEqual(result['query_executions'],2*result['evaluated'])
        self.assertEqual(result['generated_trials'],result['evaluated'])
        self.assertLessEqual(result['both_empty_trials'],result['evaluated'])
        self.assertEqual(result,search(self.schema,'SELECT x FROM t WHERE x=727','SELECT x FROM t WHERE x=728',strategy='query_aware',trials=64))
    def test_equivalent_control_remains_finite_claim_and_counts_vacuity(self):
        result=search(self.schema,'SELECT x FROM t WHERE x>7','SELECT x FROM t WHERE 7<x',strategy='query_aware',trials=32)
        self.assertEqual(result['status'],'no_counterexample_within_budget')
        self.assertEqual(result['evaluated'],32)
        self.assertEqual(result['query_executions'],64)
        self.assertNotIn('equivalent',result)
    def test_unsupported_planning_input_fails_explicitly_without_executions(self):
        result=search(self.schema,'SELECT x FROM t LIMIT 1','SELECT x FROM t',strategy='query_aware',trials=8)
        self.assertEqual(result['status'],'unsupported_generation')
        self.assertEqual(result['evaluated'],0)

    def test_cli_exposes_opt_in_strategy(self):
        from querywitness.cli import _parser
        args=_parser().parse_args(['search','schema.json','a.sql','b.sql','--strategy','query_aware'])
        self.assertEqual(args.strategy,'query_aware')
