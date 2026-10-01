"""Checks for the public external-regression evidence contract."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'benchmarks/sqlglot-regression-v1'

class ExternalRegressionPublicationTest(unittest.TestCase):
    def test_frozen_case_pack_and_all_budgets(self):
        cases = json.loads((PACK/'cohort/evaluation-cases.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(cases), 55)
        self.assertEqual(sum(c['oracle_status']=='witnessed_different' for c in cases),27)
        self.assertEqual(sum(c['role']=='intended_control' for c in cases),28)
        self.assertEqual(len({c['cluster'] for c in cases}),3)
        p=json.loads((PACK/'evaluation-protocol.json').read_text(encoding='utf-8'))
        self.assertEqual(p['methods'],['random','boundary','query_aware'])
        self.assertEqual(p['repeat_seeds'],[20260930,20261930,20262930,20263930])
        self.assertEqual(55*len(p['methods'])*len(p['repeat_seeds'])*p['trials'],42240)
    def test_reported_results_match_compact_records(self):
        s=json.loads((PACK/'results/summary.json').read_text(encoding='utf-8'))
        for m,hits,mismatches in [('random',24,3990),('boundary',24,3870),('query_aware',27,3330)]:
            r=s['methods'][m]
            self.assertEqual(r['tasks_found_any_seed'],hits)
            self.assertEqual(r['trial_counts']['mismatch'],mismatches)
            self.assertEqual(r['intended_control_tasks_with_mismatch'],[])
            self.assertEqual(sum(c['tasks_found_any_seed']>0 for c in r['cluster_coverage']),3)
    def test_public_pack_hashes_and_privacy(self):
        manifest=json.loads((PACK/'PUBLIC_MANIFEST.json').read_text(encoding='utf-8'))
        for name,expected in manifest['files'].items():
            data=(PACK/name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),expected,name)
            text=data.decode('utf-8')
            for marker in ('/workspace/','libfile_','libdir_','file_000000','@qq.com','siwc_bypass','source_repository_credential'):
                self.assertNotIn(marker,text,name)
        self.assertIn('Copyright (c) 2026 Toby Mao',(PACK/'LICENSE.SQLGLOT').read_text(encoding='utf-8'))
    def test_distribution_preserves_sqlglot_license(self):
        self.assertIn('include benchmarks/sqlglot-regression-v1/LICENSE.SQLGLOT', (ROOT/'MANIFEST.in').read_text(encoding='utf-8'))

    def test_public_documentation_links(self):
        self.assertIn('SQLGLOT_REGRESSION_VALIDATION.md',(ROOT/'README.md').read_text(encoding='utf-8'))
        page=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertIn('SQLGLOT_REGRESSION_VALIDATION.md',page)
        self.assertIn('24/27',page)
        self.assertIn('28 intended controls',page)
