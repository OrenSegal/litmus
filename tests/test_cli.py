"""Tests for how the `litmus` command wires a judge into the engine.

No test here calls a model. `ClaudeJudge.__call__` or `subprocess.run` inside
`litmus.judge` is patched in every test that could reach it, and the tests that
expect no judge make those patches raise if they are touched.
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from litmus import cli
from litmus.judge import ClaudeJudge

FAKE_CLAUDE = "/usr/local/bin/claude"


def _build_suite(base: Path, output: dict) -> None:
    """One case with a single judge assertion, both anchors, and one run."""
    (base / "cases").mkdir()
    (base / "cases" / "c.json").write_text(json.dumps({
        "id": "c",
        "assert": [{"judge": {
            "rubric": "the opener is specific",
            "anchors": [
                {"output": "good.json", "expect": "pass"},
                {"output": "bad.json", "expect": "fail"},
            ],
        }}],
    }))
    (base / "good.json").write_text(json.dumps({"opener": "specific"}))
    (base / "bad.json").write_text(json.dumps({"opener": "mailmerge"}))
    (base / "runs").mkdir()
    (base / "runs" / "c.json").write_text(json.dumps({"output": output}))


def _honest(calls):
    """Stand-in for ClaudeJudge.__call__: grades like a well-calibrated judge."""
    def call(self, artifact, rubric):
        calls.append(artifact)
        return artifact.get("opener") == "specific"
    return call


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse errors exit instead of returning
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TestCliJudge(unittest.TestCase):
    def test_judge_flag_reaches_the_judge(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch.object(ClaudeJudge, "__call__", _honest(calls)):
            _build_suite(Path(d), {"opener": "specific"})
            code, out, err = _main(["run", d, "--judge", "claude"])
        self.assertEqual(code, 0, err)
        # two anchors re-graded, then one call on the real output
        self.assertEqual(calls, [{"opener": "specific"}, {"opener": "mailmerge"}, {"opener": "specific"}])
        self.assertIn("1/1 green", out)
        self.assertNotIn("INCONC", out)

    def test_judge_verdict_drives_the_exit_code(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch.object(ClaudeJudge, "__call__", _honest(calls)):
            _build_suite(Path(d), {"opener": "mailmerge"})
            code, out, _ = _main(["run", d, "--judge", "claude"])
        self.assertEqual(code, 1)
        self.assertIn("1 failing", out)

    def test_judge_model_is_passed_through(self):
        seen = []

        def call(self, artifact, rubric):
            seen.append(self.model)
            return artifact.get("opener") == "specific"

        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch.object(ClaudeJudge, "__call__", call):
            _build_suite(Path(d), {"opener": "specific"})
            _main(["run", d, "--judge", "claude", "--judge-model", "some-model"])
        self.assertEqual(set(seen), {"some-model"})

    def test_every_grading_command_accepts_the_judge(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE):
            _build_suite(Path(d), {"opener": "specific"})
            baseline = str(Path(d) / "baseline.json")
            commands = [
                ["bless", d, "--out", baseline],
                ["gate", d, "--baseline", baseline],
                ["matrix", d],
                ["index", d],
            ]
            for argv in commands:
                calls = []
                with self.subTest(cmd=argv[0]), mock.patch.object(ClaudeJudge, "__call__", _honest(calls)):
                    code, _, err = _main(argv + ["--judge", "claude"])
                    self.assertEqual(code, 0, err)
                    self.assertEqual(len(calls), 3)

    def test_no_judge_flag_stays_inconclusive_and_never_calls_out(self):
        boom = AssertionError("judge must not be called without --judge")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ClaudeJudge, "__call__", side_effect=boom), \
                mock.patch("litmus.judge.subprocess.run", side_effect=boom), \
                mock.patch("shutil.which", side_effect=boom):
            _build_suite(Path(d), {"opener": "specific"})
            code, out, err = _main(["run", d])
        self.assertEqual(code, 0, err)
        self.assertIn("INCONC", out)
        self.assertIn("no judge configured", out)
        self.assertIn("0/1 green", out)

    def test_missing_claude_cli_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("litmus.judge.subprocess.run", side_effect=AssertionError("must not run")):
            _build_suite(Path(d), {"opener": "specific"})
            code, out, err = _main(["run", d, "--judge", "claude"])
        self.assertEqual(code, 2)
        self.assertIn("claude", err)
        self.assertIn("ANTHROPIC_API_KEY", err)
        self.assertEqual(out, "")

    def test_failing_claude_cli_is_a_clear_error_not_inconclusive(self):
        # e.g. not logged in and no ANTHROPIC_API_KEY: the CLI exits non-zero with empty stdout
        failed = subprocess.CompletedProcess(["claude"], 1, stdout="", stderr="Invalid API key")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch("litmus.judge.subprocess.run", return_value=failed):
            _build_suite(Path(d), {"opener": "specific"})
            code, out, err = _main(["run", d, "--judge", "claude"])
        self.assertEqual(code, 2)
        self.assertIn("Invalid API key", err)
        self.assertNotIn("INCONC", out)

    def test_real_claude_judge_reads_the_cli_reply(self):
        # runs the real ClaudeJudge.__call__; only the subprocess is faked
        argvs = []

        def fake_run(argv, **kwargs):
            argvs.append(argv)
            verdict = "PASS" if '"opener": "specific"' in argv[2] else "FAIL"
            return subprocess.CompletedProcess(argv, 0, stdout=f"{verdict}\nreason", stderr="")

        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch("litmus.judge.subprocess.run", side_effect=fake_run):
            _build_suite(Path(d), {"opener": "specific"})
            code, out, err = _main(["run", d, "--judge", "claude", "--judge-model", "m1"])
        self.assertEqual(code, 0, err)
        self.assertIn("1/1 green", out)
        self.assertEqual(len(argvs), 3)
        self.assertTrue(all(a[:2] == ["claude", "-p"] and a[3:] == ["--model", "m1"] for a in argvs))

    def test_judge_model_without_judge_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            _build_suite(Path(d), {"opener": "specific"})
            code, _, err = _main(["run", d, "--judge-model", "m1"])
        self.assertEqual(code, 2)
        self.assertIn("--judge-model only applies together with --judge", err)

    def test_empty_judge_reply_is_a_clear_error(self):
        empty = subprocess.CompletedProcess(["claude"], 0, stdout="  \n", stderr="")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch("litmus.judge.subprocess.run", return_value=empty):
            _build_suite(Path(d), {"opener": "specific"})
            code, _, err = _main(["run", d, "--judge", "claude"])
        self.assertEqual(code, 2)
        self.assertIn("empty", err)


if __name__ == "__main__":
    unittest.main()
