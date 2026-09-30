import unittest
from querywitness.schema import Schema
from querywitness.reduce import minimize
class ReductionTests(unittest.TestCase):
 def test_duplicate_witness_reduced(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
  r=minimize(s,{'t':[[1],[1],[2],[3]]},'SELECT x FROM t','SELECT DISTINCT x FROM t')
  self.assertEqual(r['status'],'minimized');self.assertEqual(len(r['instance']['t']),2);self.assertTrue(r['row_1_minimal'])
 def test_agreement_not_witness(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
  r=minimize(s,{'t':[[1]]},'SELECT x FROM t','SELECT x FROM t');self.assertEqual(r['status'],'not_a_witness')
 def test_budget_incomplete_never_minimal(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
  r=minimize(s,{'t':[[1],[1],[2],[3]]},'SELECT x FROM t','SELECT DISTINCT x FROM t',max_checks=1)
  self.assertFalse(r['row_1_minimal']);self.assertEqual(r['status'],'budget_exhausted')
 def test_foreign_keys_preserved(self):
  from test_schema import DEFINITION
  s=Schema.from_dict(DEFINITION);d={'people':[[1,'a'],[2,'b']],'orders':[[1,1,5],[2,1,5],[3,2,8]]}
  r=minimize(s,d,'SELECT SUM(amount) FROM orders','SELECT SUM(DISTINCT amount) FROM orders');s.validate_instance(r['instance']);self.assertTrue(r['row_1_minimal'])
