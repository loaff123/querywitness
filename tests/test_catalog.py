import unittest
from collections import Counter
from querywitness.catalog import load_catalog, validate_catalog
from querywitness.engine import execute
from querywitness.schema import Schema
from querywitness.generate import generate_instance

class CatalogTests(unittest.TestCase):
    def test_twelve_families_independent_oracles(self):
        result=validate_catalog();self.assertEqual(result['families'],12);self.assertEqual(result['failures'],[])
    def test_pure_python_reference_count_and_exists(self):
        cases={c['id']:c for c in load_catalog()['cases']}
        for seed in range(100):
            for family in ('count_nullable','join_multiplicity','correlated_filter','inclusive_boundary','sum_distinct','null_negation'):
                case=cases[family];s=Schema.from_dict(case['schema']);data=generate_instance(s,seed)
                if family=='count_nullable': expected=[(sum(r[0] is not None for r in data['t']),)]
                elif family=='join_multiplicity': expected=[(r[0],) for r in data['p'] if any(c[0]==r[0] for c in data['c'])]
                elif family=='correlated_filter': expected=[(r[0],) for r in data['p'] if any(c[0]==r[0] and c[1] is not None and c[1]>0 for c in data['c'])]
                elif family=='inclusive_boundary': expected=[(r[0],) for r in data['t'] if r[0]>=10]
                elif family=='sum_distinct':
                    values=[r[0] for r in data['t'] if r[0] is not None];expected=[(sum(values) if values else None,)]
                else: expected=[(r[0],) for r in data['t'] if r[0]!=1]
                self.assertEqual(Counter(execute(s,data,case['reference']).rows),Counter(expected),(seed,family))
