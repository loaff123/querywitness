import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class CLITests(unittest.TestCase):
    def runcli(self,*args):
        return subprocess.run([sys.executable,'-m','querywitness',*map(str,args)],capture_output=True,text=True)
    def test_demo_search_replay_and_overwrite(self):
        with tempfile.TemporaryDirectory() as p:
            target=Path(p)/'demo'
            result=self.runcli('demo','count_nullable','--out',target)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(self.runcli('replay',target/'witness.json').returncode,0)
            self.assertEqual(self.runcli('demo','count_nullable','--out',target).returncode,2)
    def test_catalog_validates(self):
        result=self.runcli('catalog','--validate');self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['families'],12)
    def test_search_exit_codes(self):
        with tempfile.TemporaryDirectory() as p:
            p=Path(p); (p/'schema.json').write_text('{"tables":[{"name":"t","columns":[{"name":"x","type":"INTEGER"}]}]}')
            (p/'a.sql').write_text('SELECT x FROM t');(p/'b.sql').write_text('SELECT DISTINCT x FROM t')
            result=self.runcli('search',p/'schema.json',p/'a.sql',p/'b.sql','--out',p/'result','--trials','32')
            self.assertEqual(result.returncode,1,result.stderr)
            result=self.runcli('search',p/'schema.json',p/'a.sql',p/'a.sql','--trials','2')
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'no_counterexample_within_budget')

class CLIBoundaryTests(unittest.TestCase):
    def runcli(self, *args):
        return subprocess.run([sys.executable, '-m', 'querywitness', *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    def inputs(self, root):
        root = Path(root)
        schema = root / 'schema.json'
        reference = root / 'reference.sql'
        candidate = root / 'candidate.sql'
        schema.write_text('{"tables":[{"name":"t","columns":[{"name":"x","type":"INTEGER"}]}]}', encoding='utf-8')
        reference.write_text('SELECT x FROM t', encoding='utf-8')
        candidate.write_text('SELECT DISTINCT x FROM t', encoding='utf-8')
        return schema, reference, candidate

    def test_help_and_version(self):
        result = self.runcli('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('search', 'demo', 'replay', 'catalog', 'benchmark'):
            self.assertIn(command, result.stdout)
        self.assertEqual(self.runcli('--version').stdout.strip(), 'querywitness 0.1.0')

    def test_missing_command_is_usage_error(self):
        result = self.runcli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage:', result.stderr)

    def test_catalog_lists_known_families(self):
        result = self.runcli('catalog')
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = json.loads(result.stdout)
        self.assertEqual(catalog['families'], 12)
        self.assertIn('count_nullable', {case['id'] for case in catalog['cases']})

    def test_default_demo_writes_replayable_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'demo'
            result = self.runcli('demo', '--out', out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['family'], 'count_nullable')
            self.assertEqual({p.name for p in out.iterdir()}, {'witness.json', 'fixture.sql', 'report.html'})
            self.assertEqual(json.loads(self.runcli('replay', out / 'witness.json').stdout)['status'], 'reproduced')

    def test_unknown_demo_and_family_filter_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as root:
            for args in [('demo', 'missing'), ('benchmark', '--family', 'count_nullable', '--family', 'missing')]:
                out = Path(root) / 'out'
                result = self.runcli(*args, '--out', out)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(out.exists())
                self.assertNotIn('Traceback', result.stderr)

    def test_search_persists_summary_and_reduced_witness(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            out = Path(root) / 'out'
            result = self.runcli('search', schema, reference, candidate, '--out', out, '--trials', 32)
            self.assertEqual(result.returncode, 1, result.stderr)
            summary = json.loads((out / 'result.json').read_text())
            self.assertEqual(summary['status'], 'counterexample')
            self.assertTrue(summary['reduction']['row_1_minimal'])
            witness = json.loads((out / 'witness.json').read_text())
            self.assertEqual(witness['reduction'], summary['reduction'])
            self.assertEqual(self.runcli('replay', out / 'witness.json').returncode, 0)

    def test_search_no_witness_still_saves_summary(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, _ = self.inputs(root)
            out = Path(root) / 'out'
            result = self.runcli('search', schema, reference, reference, '--out', out, '--trials', 2)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'no_counterexample_within_budget')
            self.assertFalse((out / 'witness.json').exists())

    def test_search_existing_output_preserves_sentinel(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            out = Path(root) / 'out'
            out.mkdir()
            (out / 'sentinel').write_text('keep')
            result = self.runcli('search', schema, reference, candidate, '--out', out)
            self.assertEqual(result.returncode, 2)
            self.assertEqual([p.name for p in out.iterdir()], ['sentinel'])
            result = self.runcli('search', schema, reference, candidate, '--out', reference)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(reference.read_text(), 'SELECT x FROM t')

    def test_inconclusive_query_does_not_become_witness(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            candidate.write_text('SELECT nonexistent FROM t')
            out = Path(root) / 'out'
            result = self.runcli('search', schema, reference, candidate, '--out', out, '--trials', 1)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'inconclusive')
            self.assertFalse((out / 'witness.json').exists())

    def test_invalid_json_and_utf8_are_input_errors(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            for payload in (b'{', b'{"tables":[],"tables":[]}', b'{"tables":NaN}', b'\xff'):
                schema.write_bytes(payload)
                result = self.runcli('search', schema, reference, candidate)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)

    def test_oversized_sql_and_json_are_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            out = Path(root) / 'out'
            reference.write_text(' ' * 32769)
            result = self.runcli('search', schema, reference, candidate, '--out', out)
            self.assertEqual(result.returncode, 2)
            self.assertIn('32768', result.stderr)
            self.assertFalse(out.exists())
            reference.write_text('SELECT x FROM t')
            schema.write_text(' ' * 16000001)
            result = self.runcli('search', schema, reference, candidate)
            self.assertEqual(result.returncode, 2)
            self.assertIn('16000000', result.stderr)

    def test_invalid_search_budgets_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            for flag, value in [('--trials', '0'), ('--trials', '10001'), ('--max-rows', '33'),
                                ('--seconds', 'nan'), ('--seed', '-1'), ('--policy', 'invalid')]:
                out = Path(root) / 'out'
                result = self.runcli('search', schema, reference, candidate, '--out', out, flag, value)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(out.exists())

    def test_no_minimize_records_unestablished_minimality(self):
        with tempfile.TemporaryDirectory() as root:
            schema, reference, candidate = self.inputs(root)
            out = Path(root) / 'out'
            result = self.runcli('search', schema, reference, candidate, '--out', out, '--trials', 32, '--no-minimize')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIsNone(json.loads((out / 'witness.json').read_text())['reduction'])

    def test_tampered_witness_is_input_error(self):
        with tempfile.TemporaryDirectory() as root:
            witness = Path(root) / 'witness.json'
            witness.write_text('{"format":"querywitness/witness","format_version":1,"integrity_sha256":"bad"}')
            result = self.runcli('replay', witness)
            self.assertEqual(result.returncode, 2)
            self.assertIn('integrity', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_benchmark_small_run_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'benchmark'
            result = self.runcli('benchmark', '--out', out, '--family', 'count_nullable', '--trials', 1, '--repeats', 1)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['families'], 1)
            self.assertEqual(summary['matched_budget_instance_evaluations'], 4)
            self.assertTrue((out / 'manifest.json').is_file())
            self.assertTrue((out / 'raw' / 'count_nullable.jsonl').is_file())
            self.assertEqual(self.runcli('benchmark', '--out', out, '--trials', 1, '--repeats', 1).returncode, 2)
