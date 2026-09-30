import json
import tempfile
import unittest
from pathlib import Path
from querywitness.schema import Schema
from querywitness.artifacts import build_witness, replay, verify_witness, write_bundle, load_json

S=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'x','type':'TEXT'}]}]})
D={'t':[['<script>alert(1)</script>'],['<script>alert(1)</script>']]}
class ArtifactTests(unittest.TestCase):
    def make(self): return build_witness(S,D,'SELECT x FROM t','SELECT DISTINCT x FROM t')
    def test_replay_auditable(self):
        w=self.make();self.assertEqual(replay(w)['status'],'reproduced');self.assertEqual(len(w['integrity_sha256']),64)
    def test_tampering_rejected(self):
        w=self.make();w['instance']['t'][0][0]='tampered'
        with self.assertRaises(ValueError): verify_witness(w)
    def test_agreement_not_exportable_as_witness(self):
        with self.assertRaises(ValueError):build_witness(S,D,'SELECT x FROM t','SELECT x FROM t')
    def test_bundle_safe_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as p:
            target=Path(p)/'w';write_bundle(self.make(),target)
            text=(target/'report.html').read_text();self.assertNotIn('<script>alert(1)</script>',text);self.assertIn('&lt;script&gt;',text)
            self.assertTrue((target/'fixture.sql').exists())
            with self.assertRaises(FileExistsError):write_bundle(self.make(),target)
    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as p:
            f=Path(p)/'bad.json'
            for content in ['{"x":NaN}', '{"x":1,"x":2}']:
                f.write_text(content)
                with self.assertRaises(ValueError):load_json(f)
