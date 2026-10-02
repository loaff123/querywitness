"""New closure flags remain opt-in and incomplete evidence never emits a bundle."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from querywitness.cli import main


class FKCLITests(unittest.TestCase):
    def runcli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "querywitness", *map(str, args)],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_demo_opt_in_and_explicit_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "closure"
            r = self.runcli("demo", "--out", out, "--reduction-mode", "fk-closure")
            self.assertEqual(r.returncode, 0, r.stderr)
            value = json.loads((out / "witness.json").read_text())
            self.assertEqual(value["reduction"]["deletion_mode"], "fk-closure")
            ordinary = self.runcli("replay", out / "witness.json")
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertEqual(
                json.loads(ordinary.stdout)["minimality_verification"]["status"],
                "not_requested",
            )
            verified = self.runcli(
                "replay", out / "witness.json", "--verify-minimality"
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(
                json.loads(verified.stdout)["minimality_verification"]["status"],
                "verified",
            )
            bounded = self.runcli(
                "replay",
                out / "witness.json",
                "--verify-minimality",
                "--minimality-checks",
                "1",
            )
            self.assertEqual(bounded.returncode, 3, bounded.stderr)

    def test_old_artifact_explicit_audit_is_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "default"
            self.assertEqual(self.runcli("demo", "--out", out).returncode, 0)
            r = self.runcli("replay", out / "witness.json", "--verify-minimality")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertEqual(
                json.loads(r.stdout)["minimality_verification"]["status"], "unsupported"
            )

    def test_contradictory_no_minimize_rejected_before_reading_inputs(self):
        r = self.runcli(
            "search",
            "no-schema",
            "no-reference",
            "no-candidate",
            "--no-minimize",
            "--reduction-mode",
            "fk-closure",
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("--no-minimize", r.stderr)
        self.assertIn("--reduction-mode", r.stderr)

    def test_search_closure_emits_bound_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema.json").write_text(
                '{"tables":[{"name":"t","columns":[{"name":"x","type":"INTEGER"}]}]}'
            )
            (root / "a.sql").write_text("SELECT x FROM t")
            (root / "b.sql").write_text("SELECT DISTINCT x FROM t")
            r = self.runcli(
                "search",
                root / "schema.json",
                root / "a.sql",
                root / "b.sql",
                "--out",
                root / "out",
                "--trials",
                "32",
                "--reduction-mode",
                "fk-closure",
            )
            self.assertEqual(r.returncode, 1, r.stderr)
            value = json.loads((root / "out" / "witness.json").read_text())
            self.assertTrue(value["reduction"]["fk_closure_1_minimal"])

    def test_failed_reproduction_prevents_demo_bundle(self):
        reduction = {
            "status": "initial_check_inconclusive",
            "instance": {"t": []},
            "witness_reproduced": False,
            "deletion_mode": "fk-closure",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("querywitness.cli.minimize", return_value=reduction),
            patch("querywitness.cli.build_witness") as build,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            out = Path(directory) / "out"
            code = main(["demo", "--out", str(out), "--reduction-mode", "fk-closure"])
            self.assertEqual(code, 3)
            build.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(
                json.loads(output.getvalue())["status"], "initial_check_inconclusive"
            )

    def test_explicit_replay_exit_code_matrix(self):
        for observed, minimality, expected in [
            ("reproduced", "verified", 0),
            ("reproduced", "refuted", 1),
            ("reproduced", "inconclusive", 3),
            ("reproduced", "budget_exhausted", 3),
            ("reproduced", "unsupported", 3),
            ("observation_changed", "verified", 1),
            ("observation_changed", "inconclusive", 1),
            ("inconclusive", "verified", 3),
            ("inconclusive", "refuted", 1),
        ]:
            with (
                self.subTest(observed=observed, minimality=minimality),
                patch("querywitness.cli._load_json", return_value={}),
                patch(
                    "querywitness.cli.replay",
                    return_value={
                        "status": observed,
                        "minimality_verification": {"status": minimality},
                    },
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    main(["replay", "unused.json", "--verify-minimality"]), expected
                )

    def test_invalid_audit_budgets(self):
        for flag, value in [
            ("--minimality-checks", "0"),
            ("--minimality-checks", "10001"),
            ("--minimality-seconds", "nan"),
            ("--minimality-seconds", "0"),
            ("--minimality-seconds", "301"),
        ]:
            r = self.runcli(
                "replay", "missing.json", "--verify-minimality", flag, value
            )
            self.assertEqual(r.returncode, 2)
            self.assertNotIn("No such file", r.stderr)


if __name__ == "__main__":
    unittest.main()
