"""Check that checked-in measurements and witnesses remain inspectable evidence."""
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

from querywitness.artifacts import load_json, replay, sql_fixture

ROOT=Path(__file__).resolve().parents[1]
class ReleaseEvidenceTests(unittest.TestCase):
    def test_committed_raw_records_match_manifests(self):
        for directory in ('v1','ablation-forced-fk'):
            root=ROOT/'benchmarks'/directory
            manifest=load_json(root/'manifest.json')
            for name,expected in manifest['file_sha256'].items():
                with self.subTest(run=directory,file=name):
                    self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected)
    def test_release_witnesses_replay_and_sql_fixtures_load(self):
        files=sorted((ROOT/'benchmarks'/'v1'/'witnesses').glob('*/witness.json'))
        self.assertEqual(len(files),12)
        for path in files:
            with self.subTest(family=path.parent.name):
                witness=load_json(path)
                self.assertEqual(replay(witness)['status'],'reproduced')
                db=sqlite3.connect(':memory:')
                try:
                    db.executescript(sql_fixture(witness))
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                finally:db.close()
    def test_archived_source_snapshot_hashes(self):
        root=ROOT/'benchmarks'/'ablation-forced-fk'/'source_snapshot'
        for name,expected in load_json(root/'SHA256.json').items():
            with self.subTest(file=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected)
