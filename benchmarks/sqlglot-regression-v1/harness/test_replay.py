import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import replay_all as m

class ReplayTest(unittest.TestCase):
    def test_normalizes_only_null_tag_representation(self):
        original={'status':'ok','columns':['result'],'rows':[[{'type':'null','value':None}],[{'type':'integer','value':'9007199254740993'}]]}
        result=m.product_as_checker(original)
        self.assertEqual(result,{'status':'ok','columns':1,'rows':[[{'type':'null'}],[{'type':'integer','value':'9007199254740993'}]]})
        self.assertTrue(m.exact_observation(result,result))
    def test_schema_validation_does_not_coerce_types(self):
        schema={'tables':[{'name':'regression_input','columns':[{'name':'x','type':'INTEGER','nullable':True}],'primary_key':[],'unique':[],'foreign_keys':[]}]}
        self.assertEqual(m.validate_schema_and_instance(schema,{'regression_input':[[None],[1]]}),(['x'],[[None],[1]]))
        with self.assertRaises(ValueError):m.validate_schema_and_instance(schema,{'regression_input':[[1.0]]})
    def test_mixed_row_reversal_compares_bags(self):
        columns=['x'];rows=[[1],[2],[2],[None]]
        a=m.observe(columns,rows,'SELECT x FROM regression_input')
        b=m.observe(columns,list(reversed(rows)),'SELECT x FROM regression_input')
        self.assertEqual(m.compare(a,b),'same')
        self.assertFalse(m.exact_observation(a,b))

if __name__=='__main__':unittest.main()
