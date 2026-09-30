import unittest
from querywitness.schema import Schema
from querywitness.search import search
class SearchTests(unittest.TestCase):
 def setUp(self):self.s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
 def test_detects_distinct(self):
  r=search(self.s,'SELECT x FROM t','SELECT DISTINCT x FROM t',trials=30);self.assertEqual(r['status'],'counterexample');self.assertGreater(r['evaluated'],0)
 def test_no_counterexample_not_equivalence(self):
  r=search(self.s,'SELECT x FROM t','SELECT x FROM t',trials=8);self.assertEqual(r['status'],'no_counterexample_within_budget');self.assertNotIn('equivalent',r)
 def test_candidate_error_inconclusive(self):
  r=search(self.s,'SELECT x FROM t','SELECT missing FROM t',trials=3);self.assertEqual(r['status'],'inconclusive');self.assertEqual(r['inconclusive'],3)
 def test_repeatable_provenance(self):
  a=search(self.s,'SELECT x FROM t','SELECT DISTINCT x FROM t',trials=10,seed=99);b=search(self.s,'SELECT x FROM t','SELECT DISTINCT x FROM t',trials=10,seed=99);self.assertEqual(a,b)
 def test_strategy_cycle_error_explicit(self):
  with self.assertRaises(ValueError):search(self.s,'SELECT x FROM t','SELECT x FROM t',trials=0)
