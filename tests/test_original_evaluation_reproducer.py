"""Original-only public reproducer tests; no external corpus dependencies."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(test):
    path = ROOT/'scripts/evaluate_query_aware_original.py'
    test.assertTrue(path.exists(), 'public original-only reproducer is not implemented')
    spec = importlib.util.spec_from_file_location('original_reproducer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OriginalReproducerTests(unittest.TestCase):
    def test_exact_original_budget(self):
        m = load(self)
        self.assertEqual(len(m.original_cases()), 16)
        self.assertEqual(m.planned_trials(16, m.default_config()), 12288)
        self.assertEqual(m.default_config()['methods'], ['random','boundary','query_aware'])
        self.assertEqual(m.default_config()['repeat_seeds'], [20260930,20261930,20262930,20263930])
        self.assertEqual(m.default_config()['trials'],64)
        self.assertEqual(m.default_config()['max_rows'],8)

    def test_deterministic_gzip_preserves_exact_raw_bytes(self):
        m = load(self)
        raw = b'{"a": 1}\n{"unicode":"\\u00e9"}\n'
        compressed = m.compress_trial_bytes(raw)
        self.assertEqual(compressed, m.compress_trial_bytes(raw))
        self.assertEqual(gzip.decompress(compressed), raw)
        self.assertEqual(compressed[4:8], b'\0'*4)

    def test_reader_handles_raw_and_gzipped_logs(self):
        m = load(self)
        raw = b'{"trial":0}\n{"trial":1}\n'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trials.jsonl'
            path.write_bytes(raw)
            self.assertEqual(m.read_trial_records(path), [{'trial':0},{'trial':1}])
            zipped=path.with_suffix('.jsonl.gz')
            zipped.write_bytes(m.compress_trial_bytes(raw))
            self.assertEqual(m.read_trial_records(zipped), m.read_trial_records(path))
            path.unlink()
            self.assertEqual(m.read_trial_records(path), [{'trial':0},{'trial':1}])

    def test_original_fixture_case_identity(self):
        m = load(self)
        source = json.loads((m.FIXTURES/'fixtures.json').read_text(encoding='utf-8'))['cases']
        cases = m.original_cases()
        for original,case in zip(source,cases):
            self.assertEqual(case['fixture_case_sha256'],m.digest(original))
            self.assertEqual(case['pair'],[original['reference_sql'],original['candidate_sql']])
        self.assertEqual(sum(c['relation_with_at_most_8_rows_per_table']=='different' for c in cases),11)

    def test_public_files_and_all_trial_keys(self):
        m = load(self)
        results=ROOT/'benchmarks/query-aware-original-results'
        self.assertTrue(results.exists())
        manifest=json.loads((results/'MANIFEST.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['trial_records'],12288)
        seen=set()
        for path in sorted((results/'original').glob('*/trials.jsonl.gz')):
            raw=gzip.decompress(path.read_bytes())
            relative=path.relative_to(results).as_posix()
            entry=manifest['files'][relative]
            self.assertEqual(m.bytes_digest(path.read_bytes()),entry['sha256'])
            self.assertEqual(m.bytes_digest(raw),entry['decompressed_sha256'])
            records=m.read_trial_records(path)
            self.assertEqual(len(records),768)
            for record in records:
                self.assertEqual(record['cohort'],'original')
                self.assertIsNone(record['source_index'])
                key=(record['case_id'],record['method'],record['repeat'],record['trial'])
                self.assertNotIn(key,seen)
                seen.add(key)
                self.assertEqual(record['seed'],m.default_config()['repeat_seeds'][record['repeat']]+record['trial'])
        self.assertEqual(len(seen),12288)

    def test_no_private_paths_or_external_data_in_export(self):
        m=load(self)
        results=ROOT/'benchmarks/query-aware-original-results'
        forbidden=('/workspace/', '/root/', 'querywitness-external-validation', 'VeriEQL', 'case-58', 'source_line')
        for path in results.rglob('*'):
            if not path.is_file(): continue
            content=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
            text=content.decode('utf-8')
            for token in forbidden:
                self.assertNotIn(token,text,str(path))

    def test_comparison_ignores_timing_but_detects_outcome_changes(self):
        m=load(self)
        a={'trial':0,'seconds':1.0,'generation_seconds':.1,'status':'agreement','instance_sha256':'abc'}
        b={**a,'seconds':7,'generation_seconds':3}
        self.assertEqual(m.stable_record(a),m.stable_record(b))
        b['instance_sha256']='changed'
        self.assertNotEqual(m.stable_record(a),m.stable_record(b))

    def test_optimized_python_is_rejected(self):
        import subprocess,sys
        path=ROOT/'scripts/evaluate_query_aware_original.py'
        result=subprocess.run([sys.executable,'-O',str(path),'verify'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Python -O is unsupported',result.stderr)

    def test_windows_relative_paths_serialize_as_posix(self):
        from pathlib import PureWindowsPath
        m=load(self)
        self.assertTrue(hasattr(m, 'relative_posix'), 'portable manifest path serializer is missing')
        root=PureWindowsPath('C:/evidence')
        path=root/'original'/'original_04_exact_unicode'/'trials.jsonl.gz'
        self.assertEqual(m.relative_posix(path,root),
                         'original/original_04_exact_unicode/trials.jsonl.gz')


if __name__=='__main__':unittest.main()
