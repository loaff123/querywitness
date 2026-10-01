import importlib.util
import io
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class EvaluationTest(unittest.TestCase):
    def module(self):
        path=ROOT/'scripts/evaluate.py'
        self.assertTrue(path.exists(),'evaluation harness is missing')
        spec=importlib.util.spec_from_file_location('evaluate',path)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def test_raw_schema_validator_preserves_null_type_and_row_bounds(self):
        m=self.module();s={'tables':[{'name':'regression_input','columns':[{'name':'x','type':'INTEGER','nullable':True}],'primary_key':[],'unique':[],'foreign_keys':[]}]}
        m.validate_instance(s,{'regression_input':[[None],[-2],[3]]},8)
        for bad in ({'regression_input':[[True]]},{'regression_input':[[1.2]]},{'regression_input':[[1]]*9},{'other':[]}):
            with self.assertRaises(ValueError):m.validate_instance(s,bad,8)
    def test_every_trial_retained_after_first_mismatch_and_generation_error(self):
        m=self.module()
        class Runtime:
            def generate(self,schema,plan,seed,method,config):
                if seed==102:raise ValueError('test generation error')
                return {'regression_input':[[seed]]},None
            def execute(self,schema,instance,sql,config):return {'status':'ok','columns':['result'],'rows':[[1 if sql=='left' else 2]],'detail':None}
            def observe(self,result):return result
            def compare(self,a,b,policy):return {'status':'mismatch'}
        case={'id':'toy','role':'detection','cluster':'toy','schema':{'tables':[{'name':'regression_input','columns':[{'name':'x','type':'INTEGER','nullable':True}],'primary_key':[],'unique':[],'foreign_keys':[]}]},'reference_sql':'left','candidate_sql':'right'}
        log=io.StringIO();summary=m.run_repeat(case,{},None,'random',0,100,{'trials':4,'max_rows':8,'policy':'bag'},Runtime(),log)
        rows=[json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual([r['seed'] for r in rows],[100,101,102,103])
        self.assertEqual([r['status'] for r in rows],['mismatch','mismatch','inconclusive','mismatch'])
        self.assertEqual(rows[-1]['instance'],{'regression_input':[[103]]})
        self.assertEqual(summary['first_hit_trial'],0)
        self.assertEqual(summary['attempted_trials'],4)
    def test_shared_frozen_counts_and_budget(self):
        m=self.module();cases=json.loads((ROOT/'inputs/evaluation-cases.json').read_text())['cases'];p=json.loads((ROOT/'evaluation-protocol.json').read_text())
        self.assertEqual(len(cases),55);self.assertEqual(len(cases)*len(p['methods'])*len(p['repeat_seeds'])*p['trials'],42240)
        self.assertEqual(sum(c['oracle_status']=='witnessed_different' for c in cases),27)
        self.assertEqual(sum(c['role']=='intended_control' for c in cases),28)

if __name__=='__main__':unittest.main()
