"""Regression tests for the public explorer, using genuine local benchmark output."""
import importlib.util
import json
from pathlib import Path
from html.parser import HTMLParser
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_demo', ROOT / 'scripts/build_demo.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from querywitness.benchmark import run_benchmark
        cls.temp = tempfile.TemporaryDirectory(prefix='querywitness-site-tests-')
        cls.root = Path(cls.temp.name)
        cls.benchmark = cls.root / 'benchmark'
        cls.summary = run_benchmark(cls.benchmark, trials=8, repeats=1,
                                    family_ids=['count_nullable'])
        cls.catalog = ROOT / 'src/querywitness/data/catalog.json'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_benchmark_generates_exact_explorer_and_downloads(self):
        out = self.root / 'real'
        result = builder.build_site(self.benchmark, self.catalog, out)
        self.assertEqual(result['families'], 1)
        self.assertEqual(result['witnesses'], 1)
        html = (out / 'index.html').read_text()
        witness = json.loads((self.benchmark / 'witnesses/count_nullable/witness.json').read_text())
        self.assertIn('SELECT COUNT(x) FROM t', html)
        self.assertIn('SELECT COUNT(*) FROM t', html)
        self.assertIn('row-1-minimal', html)
        self.assertIn('NULL', html)
        self.assertIn('INTEGER', html)
        self.assertIn('No finite search proves equivalence', html)
        self.assertIn('github.com/loaff123/querywitness', html)
        self.assertNotIn('{{', html)
        self.assertEqual((out / 'downloads/witnesses/count_nullable/witness.json').read_bytes(),
                         (self.benchmark / 'witnesses/count_nullable/witness.json').read_bytes())
        self.assertEqual((out / 'downloads/summary.json').read_bytes(),
                         (self.benchmark / 'summary.json').read_bytes())
        self.assertEqual(witness['comparison']['status'], 'mismatch')
        self.assertTrue((out / 'favicon.svg').is_file())
        self.assertTrue((out / 'app.js').is_file())
        # A deliberate rebuild only replaces previously generated output.
        builder.build_site(self.benchmark, self.catalog, out)

    def test_missing_input_never_creates_results(self):
        out = self.root / 'missing-result'
        with self.assertRaises((ValueError, FileNotFoundError)):
            builder.build_site(self.root / 'absent', self.catalog, out)
        self.assertFalse(out.exists())

    def test_preserves_unowned_output(self):
        out = self.root / 'unowned'
        out.mkdir()
        (out / 'keep.txt').write_text('user content')
        with self.assertRaises(ValueError):
            builder.build_site(self.benchmark, self.catalog, out)
        self.assertEqual((out / 'keep.txt').read_text(), 'user content')

    def test_refuses_tampered_witness(self):
        source = self.root / 'tampered'
        shutil.copytree(self.benchmark, source)
        path = source / 'witnesses/count_nullable/witness.json'
        witness = json.loads(path.read_text())
        witness['candidate'] = 'SELECT 1'
        path.write_text(json.dumps(witness))
        with self.assertRaisesRegex(ValueError, 'integrity|checksum'):
            builder.build_site(source, self.catalog, self.root / 'tampered-output')

    def test_refuses_catalog_drift(self):
        catalog = self.root / 'changed-catalog.json'
        value = json.loads(self.catalog.read_text())
        value['cases'][0]['mechanism'] += ' changed'
        catalog.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'catalog'):
            builder.build_site(self.benchmark, catalog, self.root / 'drift-output')

    def test_escapes_text_and_handles_missing_witness_honestly(self):
        source = self.root / 'no-witness'
        shutil.copytree(self.benchmark, source)
        shutil.rmtree(source / 'witnesses')
        summary = json.loads((source / 'summary.json').read_text())
        for method in ('random', 'boundary'):
            summary['method_detection'][method]['detected_family_runs'] = 0
            summary['method_detection'][method]['detected_distinct_families'] = 0
            summary['by_family'][0]['methods'][method]['mutant']['detected_runs'] = 0
        (source / 'summary.json').write_text(json.dumps(summary))
        out = self.root / 'no-witness-output'
        builder.build_site(source, self.catalog, out)
        html = (out / 'index.html').read_text()
        self.assertIn('No witness saved', html)
        self.assertNotIn('downloads/witnesses/count_nullable/witness.json', html)
        self.assertEqual(builder.esc('<script>"&'), '&lt;script&gt;&quot;&amp;')

    def test_all_generated_internal_links_resolve(self):
        out = self.root / 'linked'
        builder.build_site(self.benchmark, self.catalog, out)
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids, self.links = set(), []
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if 'id' in values:
                    self.ids.add(values['id'])
                if tag in ('a', 'link', 'script'):
                    link = values.get('href', values.get('src'))
                    if link:
                        self.links.append(link)
        parser = Links()
        parser.feed((out / 'index.html').read_text())
        for link in parser.links:
            if link.startswith('#'):
                self.assertIn(link[1:], parser.ids)
            elif not link.startswith('https://'):
                self.assertTrue((out / link).is_file(), link)

    def test_query_aware_update_preserves_recorded_baseline_scope(self):
        out = self.root / 'query-aware-info'
        builder.build_site(self.benchmark, self.catalog, out)
        html = (out / 'index.html').read_text()
        self.assertIn('Opt-in query-aware generation', html)
        self.assertIn('explicit domains are never widened', html)
        self.assertIn('recorded v1 baseline', html)
        self.assertIn('/blob/main/docs/QUERY_AWARE.md', html)

    def test_supplementary_query_aware_witness_is_exact_and_available(self):
        out=self.root/'query-aware-example'
        builder.build_site(self.benchmark,self.catalog,out)
        original=ROOT/'benchmarks/query-aware-demo/witness.json'
        self.assertTrue((out/'query-aware-example/witness.json').is_file())
        self.assertEqual((out/'query-aware-example/witness.json').read_bytes(),original.read_bytes())
        self.assertIn('query-aware-example/report.html',(out/'index.html').read_text())

    def test_escapes_catalog_and_typed_text(self):
        case = json.loads(self.catalog.read_text())['cases'][1]
        case['title'] = '<img src=x onerror=alert(1)>'
        case['mechanism'] = '</p><script>alert(1)</script>'
        family = self.summary['by_family'][0]
        rendered = builder.render_family(case, family, None, 1)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', builder.typed_cell({'type': 'text', 'value': '<script>'}))

    def test_rejects_missing_detected_witness(self):
        source = self.root / 'missing-witness'
        shutil.copytree(self.benchmark, source)
        shutil.rmtree(source / 'witnesses')
        with self.assertRaisesRegex(ValueError, 'Missing witness'):
            builder.build_site(source, self.catalog, self.root / 'missing-witness-output')

    def test_refuses_inconsistent_aggregate_counts(self):
        source = self.root / 'wrong-counts'
        shutil.copytree(self.benchmark, source)
        path = source / 'summary.json'
        value = json.loads(path.read_text())
        value['control_mismatches'] += 1
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'control'):
            builder.build_site(source, self.catalog, self.root / 'wrong-counts-output')

    def test_rejects_output_containing_sources(self):
        with self.assertRaises(ValueError):
            builder.build_site(self.benchmark, self.catalog, self.root)


if __name__ == '__main__':
    unittest.main()
