"""Tests for `litmus.calibrate` and `litmus calibrate`. No model is called:
judges are `ScriptedJudge`, and the CLI test patches `ClaudeJudge.__call__`."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from litmus import cli
from litmus.calibrate import CalibrationError, Sample, calibrate, fill_judge, load_samples
from litmus.judge import ClaudeJudge, ScriptedJudge

FAKE_CLAUDE = "/usr/local/bin/claude"


def _samples(pairs):
    """pairs of (human, judge) -> Samples with ids s0, s1, ..."""
    return [Sample(id=f"s{i}", artifact=f"a{i}", rubric="r", human=h, judge=j)
            for i, (h, j) in enumerate(pairs)]


def _write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class MetricsTest(unittest.TestCase):
    def test_textbook_kappa(self):
        # 20 both fail, 5 judge-only fail, 10 human-only fail, 15 both pass:
        # observed 0.70, chance 0.50, kappa 0.40.
        pairs = ([("fail", "fail")] * 20 + [("pass", "fail")] * 5
                 + [("fail", "pass")] * 10 + [("pass", "pass")] * 15)
        c = calibrate(_samples(pairs))
        self.assertEqual((c.tp, c.fp, c.fn, c.tn), (20, 5, 10, 15))
        self.assertAlmostEqual(c.kappa, 0.4)
        self.assertAlmostEqual(c.recall, 20 / 30)
        self.assertAlmostEqual(c.precision, 20 / 25)
        self.assertAlmostEqual(c.accuracy, 0.7)
        self.assertEqual(len(c.disagreements), 15)

    def test_always_pass_judge_has_high_accuracy_and_zero_kappa(self):
        pairs = [("pass", "pass")] * 90 + [("fail", "pass")] * 10
        c = calibrate(_samples(pairs))
        self.assertAlmostEqual(c.accuracy, 0.9)
        self.assertEqual(c.recall, 0.0)
        self.assertIsNone(c.precision)  # the judge never said FAIL
        self.assertAlmostEqual(c.kappa, 0.0)

    def test_perfect_agreement(self):
        c = calibrate(_samples([("fail", "fail")] * 3 + [("pass", "pass")] * 7))
        self.assertAlmostEqual(c.kappa, 1.0)
        self.assertEqual(c.disagreements, [])

    def test_kappa_undefined_when_everything_is_one_label(self):
        c = calibrate(_samples([("pass", "pass")] * 5))
        self.assertIsNone(c.kappa)
        self.assertIsNone(c.recall)

    def test_unjudged_rows_are_excluded_and_counted(self):
        c = calibrate(_samples([("fail", "fail"), ("pass", None), ("fail", None)]))
        self.assertEqual(c.n, 1)
        self.assertEqual(c.unjudged, 2)


class FillJudgeTest(unittest.TestCase):
    def test_fills_missing_verdicts_only(self):
        samples = _samples([("pass", None), ("fail", "pass")])
        judge = ScriptedJudge(lambda artifact, rubric: False, model="claude-sonnet-5")
        fill_judge(samples, judge)
        self.assertEqual([s.judge for s in samples], ["fail", "pass"])
        fill_judge(samples, judge, rejudge=True)
        self.assertEqual([s.judge for s in samples], ["fail", "fail"])

    def test_skips_samples_the_judge_model_produced(self):
        samples = _samples([("pass", None), ("pass", None)])
        samples[0].model = "claude-haiku-4-5-20251001"
        samples[1].model = "claude-sonnet-5"
        calls = []
        judge = ScriptedJudge(lambda a, r: calls.append(a) or True, model="haiku-4.5")
        warnings = fill_judge(samples, judge)
        self.assertEqual(calls, ["a1"])
        self.assertIsNone(samples[0].judge)
        self.assertEqual(len(warnings), 1)
        self.assertIn("s0", warnings[0])


class LoadTest(unittest.TestCase):
    def _load(self, rows):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "labels.jsonl"
            if isinstance(rows, str):
                path.write_text(rows)
            else:
                _write_jsonl(path, rows)
            return load_samples(path)

    def test_normalizes_case(self):
        [s] = self._load([{"id": 1, "artifact": {"x": 1}, "rubric": "r", "human": "FAIL", "judge": " Pass "}])
        self.assertEqual((s.id, s.human, s.judge, s.artifact), ("1", "fail", "pass", {"x": 1}))

    def test_rejects_bad_label(self):
        with self.assertRaisesRegex(CalibrationError, "human"):
            self._load([{"id": "a", "artifact": "x", "rubric": "r", "human": "maybe"}])

    def test_rejects_missing_field_and_duplicate_id(self):
        with self.assertRaisesRegex(CalibrationError, "rubric"):
            self._load([{"id": "a", "artifact": "x", "human": "pass"}])
        row = {"id": "a", "artifact": "x", "rubric": "r", "human": "pass"}
        with self.assertRaisesRegex(CalibrationError, "duplicate"):
            self._load([row, row])

    def test_rejects_bad_json(self):
        with self.assertRaisesRegex(CalibrationError, ":1: not valid JSON"):
            self._load("{not json\n")


class CliTest(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_prelabeled_file_needs_no_judge(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "labels.jsonl"
            _write_jsonl(path, [
                {"id": "a", "artifact": "x", "rubric": "r", "human": "fail", "judge": "fail"},
                {"id": "b", "artifact": "y", "rubric": "r", "human": "pass", "judge": "fail"},
                {"id": "c", "artifact": "z", "rubric": "r", "human": "pass", "judge": "pass"},
            ])
            with mock.patch.object(ClaudeJudge, "__call__", side_effect=AssertionError("judge called")):
                code, out, _ = self._run(["calibrate", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("3 judged samples, 1 human-labeled failures", out)
            self.assertIn("b: human PASS, judge FAIL", out)

            code, out, _ = self._run(["calibrate", str(path), "--json", "--min-kappa", "0.9"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["confusion"], {"tp": 1, "fp": 1, "fn": 0, "tn": 1})

    def test_judge_fills_and_writes_out(self):
        with tempfile.TemporaryDirectory() as d:
            path, out_path = Path(d) / "labels.jsonl", Path(d) / "judged.jsonl"
            _write_jsonl(path, [
                {"id": "a", "artifact": "bad", "rubric": "r", "human": "fail"},
                {"id": "b", "artifact": "good", "rubric": "r", "human": "pass"},
            ])
            with mock.patch("litmus.judge.shutil.which", return_value=FAKE_CLAUDE), \
                 mock.patch.object(ClaudeJudge, "__call__", autospec=True,
                                   side_effect=lambda self, artifact, rubric: artifact == "good"):
                code, out, _ = self._run(["calibrate", str(path), "--judge", "claude",
                                          "--judge-model", "claude-sonnet-5", "--out", str(out_path)])
            self.assertEqual(code, 0)
            self.assertIn("kappa      1.000", out)
            judged = [json.loads(line)["judge"] for line in out_path.read_text().splitlines()]
            self.assertEqual(judged, ["fail", "pass"])

    def test_bad_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "labels.jsonl"
            path.write_text('{"id": "a"}\n')
            code, _, err = self._run(["calibrate", str(path)])
            self.assertEqual(code, 2)
            self.assertIn("missing 'artifact'", err)


if __name__ == "__main__":
    unittest.main()
