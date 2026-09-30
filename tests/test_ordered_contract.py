import unittest
from querywitness.schema import Schema
from querywitness.engine import execute
from querywitness.search import search
from querywitness.reduce import minimize
from querywitness.artifacts import build_witness, replay, digest

S=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'},{'name':'g','type':'TEXT'}]}]})
D={'t':[[2,'a'],[1,'b']]}
class OrderedContractTests(unittest.TestCase):
    def test_search_rejects_missing_order(self):
        r=search(S,'SELECT x FROM t','SELECT x FROM t ORDER BY x',policy='ordered',trials=2)
        self.assertEqual(r['status'],'inconclusive')
    def test_reduction_rejects_missing_order(self):
        r=minimize(S,D,'SELECT x FROM t','SELECT x FROM t ORDER BY x',policy='ordered')
        self.assertEqual(r['status'],'not_a_witness')
    def test_artifact_rejects_missing_order(self):
        with self.assertRaises(ValueError):build_witness(S,D,'SELECT x FROM t','SELECT x FROM t ORDER BY x',policy='ordered')
    def test_complete_order_can_produce_witness(self):
        w=build_witness(S,D,'SELECT x FROM t ORDER BY x','SELECT x FROM t ORDER BY x DESC',policy='ordered')
        self.assertEqual(replay(w)['status'],'reproduced')
    def test_replay_rejects_order_contract_even_with_valid_checksum(self):
        w=build_witness(S,D,'SELECT x FROM t ORDER BY x DESC','SELECT x FROM t ORDER BY x',policy='ordered')
        w['reference']='SELECT x FROM t';w.pop('integrity_sha256');w['integrity_sha256']=digest(w)
        self.assertEqual(replay(w)['status'],'inconclusive')
    def test_partial_order_excluded(self):
        r=search(S,'SELECT x,g FROM t ORDER BY x','SELECT x,g FROM t ORDER BY x,g',policy='ordered',trials=2)
        self.assertEqual(r['status'],'inconclusive')
    def test_collations_excluded_including_derived_column(self):
        for q in ['SELECT g COLLATE NOCASE FROM t ORDER BY 1','SELECT c FROM (SELECT g COLLATE NOCASE AS c FROM t) ORDER BY c']:
            with self.subTest(sql=q):self.assertEqual(execute(S,D,q,policy='ordered').status,'unsupported')
    def test_duplicate_aliases_cannot_cover_two_projections(self):
        q='SELECT x AS a,g AS a FROM t ORDER BY 1,a'
        self.assertEqual(execute(S,D,q,policy='ordered').status,'unsupported')
    def test_distinct_output_names_order_supported(self):
        self.assertEqual(execute(S,D,'SELECT x AS a,g AS b FROM t ORDER BY a,b',policy='ordered').status,'ok')
    def test_order_alias_inside_expression_cannot_hide_bare_group_column(self):
        q='SELECT x,SUM(x) AS g FROM t GROUP BY x ORDER BY g+0,x,2'
        self.assertEqual(execute(S,D,q,policy='ordered').status,'unsupported')
