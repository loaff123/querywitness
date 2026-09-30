import tempfile
import unittest
from pathlib import Path
from querywitness.benchmark import run_benchmark

class BenchmarkTests(unittest.TestCase):
    def test_fixed_budget_no_early_stop_and_controls(self):
        with tempfile.TemporaryDirectory() as p:
            summary=run_benchmark(Path(p)/'results',trials=3,repeats=2,seed=100,family_ids=['count_nullable'])
            self.assertEqual(summary['matched_budget_runs'],8)
            self.assertEqual(summary['matched_budget_instance_evaluations'],24)
            self.assertEqual(summary['control_mismatches'],0)
            self.assertEqual(summary['benign_detected_families'],0)
            self.assertTrue((Path(p)/'results'/'raw'/'count_nullable.jsonl').exists())
