import json
from copy import deepcopy
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from querywitness.schema import Schema
from querywitness.artifacts import build_witness, replay, verify_witness, write_bundle, load_json, sql_fixture, digest

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


class SQLFixtureBoundaryTests(unittest.TestCase):
    def test_query_endings_preserve_text_and_execute_both_queries(self):
        schema = Schema.from_dict({'tables': [
            {'name': 't', 'columns': [{'name': 'x', 'type': 'INTEGER'}]}
        ]})
        endings = {
            'ordinary': '',
            'semicolon': ';',
            'line_comment': ' -- trailing comment',
            'semicolon_in_comment': ' -- trailing comment;',
            'crlf_before_comment': '\r\n-- trailing comment',
            'crlf_after_comment': ' -- trailing comment\r\n',
            'whitespace': ' \t\r\n ',
            'semicolon_whitespace': '; \t\r\n ',
            'block_comment': ' /* closed -- ; comment */',
            'quoted_markers': ", '-- /* ; */ ''quoted''' AS \"-- /* ; */\"",
        }
        for reference_name, reference_ending in endings.items():
            for candidate_name, candidate_ending in endings.items():
                with self.subTest(reference=reference_name, candidate=candidate_name):
                    reference = 'SELECT 1' + reference_ending
                    candidate = 'SELECT 2' + candidate_ending
                    witness = build_witness(schema, {'t': []}, reference, candidate)
                    original = deepcopy(witness)
                    fixture = sql_fixture(witness)
                    db = sqlite3.connect(':memory:')
                    statements = []
                    try:
                        db.set_trace_callback(statements.append)
                        # A following query also checks the final candidate boundary.
                        db.executescript(fixture + '\nSELECT 3;')
                    finally:
                        db.close()
                    queries = [statement for statement in statements if 'SELECT ' in statement]
                    self.assertEqual(len(queries), 3, statements)
                    for number, statement in enumerate(queries, 1):
                        self.assertIn(f'SELECT {number}', statement)
                    self.assertTrue(fixture.endswith(
                        '-- Reference query\n' + reference + '\n;\n\n'
                        '-- Candidate query\n' + candidate + '\n;\n'))
                    self.assertEqual(witness, original)
                    for name, query in [('reference', reference), ('candidate', candidate)]:
                        self.assertEqual(witness[name], query)
                        self.assertEqual(witness['provenance'][name + '_sha256'],
                                         hashlib.sha256(query.encode('utf-8')).hexdigest())
                    self.assertEqual(replay(witness)['status'], 'reproduced')

    def test_loaded_query_with_comment_after_semicolon_exports_verbatim(self):
        schema = Schema.from_dict({'tables': [
            {'name': 't', 'columns': [{'name': 'x', 'type': 'INTEGER'}]}
        ]})
        # The parser excludes these endings, but the exporter also accepts loaded
        # artifacts with valid checksums. Keep their SQL intact without relaxing
        # the execution guardrails or silently normalizing their query text.
        for name in ('reference', 'candidate'):
            for ending in ('; -- trailing comment;', '; /* closed -- ; comment */'):
                with self.subTest(query=name, ending=ending):
                    witness = build_witness(schema, {'t': []}, 'SELECT 1', 'SELECT 2')
                    witness[name] += ending
                    witness['provenance'][name + '_sha256'] = hashlib.sha256(
                        witness[name].encode('utf-8')).hexdigest()
                    del witness['integrity_sha256']
                    witness['integrity_sha256'] = digest(witness)
                    original = deepcopy(witness)
                    self.assertEqual(replay(witness)['status'], 'inconclusive')
                    fixture = sql_fixture(witness)
                    db = sqlite3.connect(':memory:')
                    statements = []
                    try:
                        db.set_trace_callback(statements.append)
                        db.executescript(fixture + '\nSELECT 3;')
                    finally:
                        db.close()
                    queries = [statement for statement in statements if 'SELECT ' in statement]
                    self.assertEqual(len(queries), 3, statements)
                    for number, statement in enumerate(queries, 1):
                        self.assertIn(f'SELECT {number}', statement)
                    self.assertIn(witness[name] + '\n;\n', fixture)
                    self.assertEqual(witness, original)
                    self.assertEqual(replay(witness)['status'], 'inconclusive')
