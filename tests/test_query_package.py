"""Publication packaging must retain compressed original evidence and freeze manifests."""
from pathlib import Path
import unittest

class QueryAwarePackageTests(unittest.TestCase):
    def test_sdist_includes_original_gzip_records_and_hash_manifests(self):
        manifest=(Path(__file__).resolve().parents[1]/'MANIFEST.in').read_text()
        line=next(line for line in manifest.splitlines() if line.startswith('recursive-include benchmarks '))
        self.assertIn('*.gz',line)
        self.assertIn('SHA256SUMS',line)
