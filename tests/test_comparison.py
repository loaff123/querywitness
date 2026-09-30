import unittest
from querywitness.compare import compare_results
from querywitness.engine import QueryResult
class ComparisonTests(unittest.TestCase):
 def test_bag_preserves_duplicates(self):self.assertEqual(compare_results(QueryResult('ok',('x',),((1,),(1,))),QueryResult('ok',('x',),((1,),)))['status'],'mismatch')
 def test_bag_ignores_order_and_labels(self):self.assertEqual(compare_results(QueryResult('ok',('x',),((1,),(2,))),QueryResult('ok',('y',),((2,),(1,))))['status'],'agreement')
 def test_set_policy_explicit(self):self.assertEqual(compare_results(QueryResult('ok',('x',),((1,),(1,))),QueryResult('ok',('x',),((1,),)),'set')['status'],'agreement')
 def test_ordered_policy(self):self.assertEqual(compare_results(QueryResult('ok',('x',),((1,),(2,))),QueryResult('ok',('x',),((2,),(1,))),'ordered')['status'],'mismatch')
 def test_errors_inconclusive_not_mismatch(self):
  for status in ['query_error','resource_limit','unsupported']:
   self.assertEqual(compare_results(QueryResult('ok',('x',),((1,),)),QueryResult(status))['status'],'inconclusive')
 def test_numeric_values_equal_but_text_not(self):
  a=QueryResult('ok',('x',),((1,),));self.assertEqual(compare_results(a,QueryResult('ok',('x',),((1.0,),)))['status'],'agreement');self.assertEqual(compare_results(a,QueryResult('ok',('x',),(('1',),)))['status'],'mismatch')
 def test_empty_width_matters(self):self.assertEqual(compare_results(QueryResult('ok',('x',),()),QueryResult('ok',('x','y'),()))['status'],'mismatch')
 def test_null_blob_and_bigint(self):
  a=QueryResult('ok',('x',),((None,),(b'\xff',),(9007199254740993,)));b=QueryResult('ok',('x',),((None,),(b'\xff',),(9007199254740992.0,)));self.assertEqual(compare_results(a,b)['status'],'mismatch')
