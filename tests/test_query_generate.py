"""Original contract tests authored before query-aware sampler implementation."""
import unittest
from querywitness.schema import Schema
from querywitness.generate import GenerationError, generate_instance
from querywitness.query_plan import compile_plan
from querywitness.query_generate import generate_query_aware


def schema(columns=None):
    return Schema.from_dict({'tables':[{'name':'t','columns':columns or [{'name':'x','type':'INTEGER'}]}]})


class QueryGenerationTests(unittest.TestCase):
    def test_deterministic_valid_bounded_and_accounted(self):
        s=schema(); p=compile_plan(s,'SELECT x FROM t WHERE x=-37','SELECT x FROM t WHERE x=-38')
        pools={(t,c):v for t,c,v in p.pools}
        for seed in range(64):
            data, stats=generate_query_aware(s,p,seed)
            self.assertEqual((data,stats),generate_query_aware(s,p,seed)); s.validate_instance(data)
            self.assertLessEqual(len(data['t']),8)
            self.assertEqual(stats['accepted_rows'],len(data['t']))
            self.assertEqual(stats['attempted_rows'],stats['accepted_rows']+stats['rejected_rows'])
            self.assertLessEqual(stats['attempted_rows'],8*40)
            self.assertTrue(all(r[0] is None or r[0] in pools['t','x'] for r in data['t']))

    def test_explicit_domain_never_gains_predicate_literal(self):
        s=schema([{'name':'x','type':'INTEGER','domain':[4,9]}]);p=compile_plan(s,'SELECT x FROM t WHERE x=731','SELECT x FROM t')
        for seed in range(40):
            d,_=generate_query_aware(s,p,seed)
            self.assertTrue(all(r[0] in [None,4,9] for r in d['t']))

    def test_duplicate_and_distinct_templates_reach_values(self):
        s=schema();p=compile_plan(s,'SELECT x FROM t WHERE x=-37','SELECT DISTINCT x FROM t WHERE x=-37')
        instances=[generate_query_aware(s,p,n)[0]['t'] for n in range(64)]
        self.assertTrue(any(len([r for r in rows if r==[-37]])>=2 for rows in instances))
        self.assertTrue(any(len(set(r[0] for r in rows if r[0] is not None))>=5 for rows in instances))
        self.assertTrue(any(not rows for rows in instances));self.assertTrue(any([None] in rows for rows in instances))

    def test_join_multicolumn_templates_respect_keys_and_effective_domains(self):
        s=Schema.from_dict({'tables':[
            {'name':'p','columns':[{'name':'a','type':'INTEGER'},{'name':'b','type':'TEXT'}],'primary_key':['a','b']},
            {'name':'c','columns':[{'name':'a','type':'INTEGER'},{'name':'b','type':'TEXT'},{'name':'v','type':'INTEGER'}], 'foreign_keys':[{'columns':['a','b'],'references':{'table':'p','columns':['a','b']}}]}]})
        p=compile_plan(s,"SELECT p.a FROM p JOIN c ON p.a=c.a AND p.b=c.b WHERE c.v=427",'SELECT a FROM p')
        pools={(t,c):v for t,c,v in p.pools}
        for seed in range(64):
            data,stats=generate_query_aware(s,p,seed);s.validate_instance(data)
            for t in s.tables:
                for row in data[t.name]:
                    for c,v in zip(t.columns,row):self.assertTrue(v is None or v in pools[t.name,c.name])

    def test_plan_schema_mismatch_and_invalid_seed_rejected(self):
        s=schema();p=compile_plan(s,'SELECT x FROM t','SELECT x FROM t')
        for seed in (-1,True,2**63):
            with self.assertRaises(GenerationError):generate_query_aware(s,p,seed)
        different=schema([{'name':'x','type':'INTEGER','domain':[1]}])
        with self.assertRaises(GenerationError):generate_query_aware(different,p,0)

    def test_cycles_remain_unsupported(self):
        s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'INTEGER'}],'primary_key':['x'],'foreign_keys':[{'columns':['x'],'references':{'table':'t','columns':['x']}}]}]})
        p=compile_plan(s,'SELECT x FROM t','SELECT x FROM t')
        with self.assertRaises(GenerationError):generate_query_aware(s,p,1)

    def test_original_generators_have_unchanged_golden_digest(self):
        import hashlib,json
        s=schema()
        values=[generate_instance(s,n,m) for m in ('random','boundary') for n in range(64)]
        got=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
        self.assertEqual(got,'f8a486c6c8b002f9bd137c69de6d4021d8608235566c28d42ea2de44fc50e9eb')

class QueryTargetTests(unittest.TestCase):
    def test_count_schedule_uses_exact_compiled_row_targets(self):
        s=schema();p=compile_plan(s,'SELECT COUNT(*) FROM t HAVING COUNT(*)=4','SELECT COUNT(*) FROM t')
        self.assertEqual(p.counts,(3,4,5))
        for seed in range(4,100,8):
            _,stats=generate_query_aware(s,p,seed)
            self.assertIn(stats['requested_rows']['t'],p.counts)

    def test_join_duplicate_schedule_targets_one_side_of_count(self):
        s=Schema.from_dict({'tables':[{'name':name,'columns':[{'name':'x','type':'INTEGER'}]} for name in ('a','b')]})
        p=compile_plan(s,'SELECT COUNT(*) FROM a JOIN b ON a.x=b.x HAVING COUNT(*)=4','SELECT COUNT(*) FROM a JOIN b ON a.x=b.x')
        for seed in range(2,82,8):
            _,stats=generate_query_aware(s,p,seed)
            requests=list(stats['requested_rows'].values())
            self.assertEqual(sum(v==1 for v in requests),1)
            self.assertIn(max(requests),p.counts)
