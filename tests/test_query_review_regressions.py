"""Original adversarial regressions discovered in pre-evaluation independent review."""
import json
import unittest
from dataclasses import replace
from querywitness.schema import Schema
from querywitness.generate import GenerationError
from querywitness.query_plan import compile_plan
from querywitness.query_generate import generate_query_aware

class QueryReviewTests(unittest.TestCase):
    def setUp(self):
        self.schema=Schema.from_dict({'tables':[{'name':'items','columns':[{'name':'n','type':'INTEGER'}]}]})
    def test_ascii_case_cte_shadowing_never_hints_physical_table(self):
        for query in ['WITH ITEMS AS (SELECT 1 AS n) SELECT n FROM items WHERE n=731',
                      'WITH ITEMS AS (SELECT 1 AS n) SELECT x.n FROM items x WHERE x.n=731',
                      'WITH ITEMS AS (SELECT 1 AS n) SELECT n FROM items WHERE EXISTS (SELECT 1 FROM items x WHERE x.n=731)']:
            p=compile_plan(self.schema,query,'SELECT n FROM items')
            self.assertNotIn(731,dict(((t,c),v) for t,c,v in p.pools)['items','n'])
            self.assertTrue(p.to_dict()['skips'])
    def test_forged_plan_cannot_override_bounds_pools_or_provenance(self):
        p=compile_plan(self.schema,'SELECT n FROM items','SELECT n FROM items')
        mutations=[replace(p,counts=(33,)),replace(p,counts=(-1,)),
                   replace(p,preferred=(('items','n',(999,)),)),
                   replace(p,pools=(('items','n',(999,)),)),
                   replace(p,groups=(('items','missing'),)),
                   replace(p,joins=((('items','n'),('missing','x')),)),
                   replace(p,_manifest_json='{}')]
        for changed in mutations:
            for seed in (0,2,4):
                with self.subTest(changed=changed,seed=seed),self.assertRaises(GenerationError):
                    generate_query_aware(self.schema,changed,seed)

    def test_forward_and_implicit_recursive_cte_sources_are_not_physical(self):
        s=Schema.from_dict({'tables':[{'name':'b','columns':[{'name':'n','type':'INTEGER'}]}]})
        p=compile_plan(s,'WITH a AS (SELECT n FROM b WHERE n=731), b AS (SELECT 731 AS n) SELECT n FROM a','SELECT n FROM b')
        self.assertNotIn(731,p.pools[0][2])
        p=compile_plan(self.schema,'WITH items(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM items WHERE n<9) SELECT n FROM items','SELECT n FROM items')
        self.assertNotIn(9,p.pools[0][2])

    def test_real_foreign_key_and_join_preserve_exact_pool_representations(self):
        s=Schema.from_dict({'tables':[
            {'name':'p','columns':[{'name':'x','type':'REAL','domain':[1]}],'primary_key':['x']},
            {'name':'c','columns':[{'name':'x','type':'REAL','domain':[1.0]}], 'foreign_keys':[{'columns':['x'],'references':{'table':'p','columns':['x']}}]}]})
        p=compile_plan(s,'SELECT p.x FROM p JOIN c ON p.x=c.x','SELECT x FROM c')
        for seed in range(64):
            data,_=generate_query_aware(s,p,seed)
            for row in data['c']:
                if row[0] is not None:self.assertIs(type(row[0]),float)

    def test_planning_deadline_returns_budget_status_without_query_execution(self):
        from querywitness.search import search
        result=search(self.schema,'SELECT n FROM items','SELECT n FROM items',strategy='query_aware',seconds=1e-9,trials=8)
        self.assertEqual(result['status'],'search_budget_exhausted')
        self.assertEqual(result['query_executions'],0)
        self.assertEqual(result['evaluated'],0)
        self.assertEqual(result['budget_stage'],'planning')

    def test_sampler_rejects_nonplan_objects_with_generation_error(self):
        for value in (None,{},object()):
            with self.assertRaises(GenerationError):generate_query_aware(self.schema,value,0)
