import unittest
from querywitness.schema import Schema, SchemaError
from querywitness.generate import generate_instance, GenerationError
from test_schema import DEFINITION
class GenerationTests(unittest.TestCase):
 def test_repeatable_and_valid(self):
  s=Schema.from_dict(DEFINITION)
  for seed in range(40):
   a=generate_instance(s,seed);self.assertEqual(a,generate_instance(s,seed));s.validate_instance(a)
 def test_empty_boundary(self):
  s=Schema.from_dict(DEFINITION);self.assertEqual(generate_instance(s,0,'boundary'),{'people':[],'orders':[]})
 def test_unique_domain_small_is_not_infinite_loop(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'id','type':'INTEGER','domain':[1]}],'primary_key':['id']}]})
  for seed in range(20):self.assertLessEqual(len(generate_instance(s,seed)['t']),1)
 def test_foreign_key_parent_order(self):
  d={'tables':list(reversed(DEFINITION['tables']))};s=Schema.from_dict(d)
  for seed in range(20):s.validate_instance(generate_instance(s,seed))
 def test_cycle_explicitly_unsupported(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'id','type':'INTEGER'}],'primary_key':['id'],'foreign_keys':[{'columns':['id'],'references':{'table':'t','columns':['id']}}]}]})
  with self.assertRaises(GenerationError):generate_instance(s,0)

class NullableForeignKeyCoverageTests(unittest.TestCase):
    def test_parent_rows_do_not_erase_nullable_foreign_keys(self):
        s=Schema.from_dict({'tables':[
            {'name':'p','columns':[{'name':'id','type':'INTEGER','nullable':False}],'primary_key':['id']},
            {'name':'c','columns':[{'name':'pid','type':'INTEGER','nullable':True}],
             'foreign_keys':[{'columns':['pid'],'references':{'table':'p','columns':['id']}}]}]})
        for strategy in ('random','boundary'):
            with self.subTest(strategy=strategy):
                self.assertTrue(any((d:=generate_instance(s,seed,strategy))['p'] and any(row[0] is None for row in d['c']) for seed in range(80)))
