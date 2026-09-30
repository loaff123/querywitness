import unittest
from querywitness.schema import Schema
from querywitness.engine import execute, ExecutionLimits
SCHEMA=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}]}]})
DATA={'t':[[1],[1],[None]]}
class EngineTests(unittest.TestCase):
 def test_select_retains_duplicates_null(self):
  r=execute(SCHEMA,DATA,'SELECT x FROM t');self.assertEqual(r.status,'ok');self.assertEqual(r.rows,((1,),(1,),(None,)))
 def test_reject_write_and_attachment(self):
  for q in ['DELETE FROM t','ATTACH DATABASE \'/tmp/forbidden.db\' AS a','PRAGMA user_version=9','SELECT load_extension(\'x\')','SELECT * FROM sqlite_master']:
   with self.subTest(q=q): self.assertEqual(execute(SCHEMA,DATA,q).status,'unsupported')
 def test_error_not_mismatch(self):self.assertEqual(execute(SCHEMA,DATA,'SELECT missing FROM t').status,'query_error')
 def test_row_limit_is_inconclusive(self):self.assertEqual(execute(SCHEMA,DATA,'SELECT x FROM t',ExecutionLimits(rows=2)).status,'resource_limit')
 def test_multistatement_denied(self):self.assertEqual(execute(SCHEMA,DATA,'SELECT 1; SELECT 2').status,'unsupported')
 def test_aggregate_valid(self):self.assertEqual(execute(SCHEMA,DATA,'SELECT COUNT(*), COUNT(x), SUM(x) FROM t').rows,((3,2,2),))
 def test_quoted_forbidden_word_is_data(self):self.assertEqual(execute(SCHEMA,DATA,"SELECT 'DELETE LIMIT' FROM t").status,'ok')
 def test_recursive_budget(self):
  r=execute(SCHEMA,DATA,'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT SUM(x) FROM c',ExecutionLimits(vm_steps=1000));self.assertEqual(r.status,'resource_limit')
 def test_nondeterminism_rejected(self):
  for q in ['SELECT random()','SELECT CURRENT_TIMESTAMP','SELECT x FROM t LIMIT 1']:
   self.assertEqual(execute(SCHEMA,DATA,q).status,'unsupported')
 def test_inputs_unchanged(self):
  execute(SCHEMA,DATA,'SELECT x FROM t');self.assertEqual(DATA,{'t':[[1],[1],[None]]})
