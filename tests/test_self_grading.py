"""No self-grading (LITMUS_SPEC §6 guardrail 4): a judge must not grade a run
produced by its own model.

Every judge here is a stub (`ScriptedJudge`, or a patched `ClaudeJudge.__call__`
that never reaches `subprocess`). No test calls a model.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from litmus import assertions as A
from litmus.adapters.claude_code import parse_stream
from litmus.assertions import EvalContext, run_assertion
from litmus.judge import ClaudeJudge, DEFAULT_JUDGE_MODEL, ScriptedJudge
from litmus.models import AgentRun, Status
from litmus.runner import evaluate_suite

from tests.test_cli import FAKE_CLAUDE, _main

RUBRIC = "the opener is specific"


def _judge(model, calls):
    """An honest stub judge standing in for `model`. It records every call."""
    j = ScriptedJudge(lambda art, r: calls.append(art) or art.get("opener") == "specific")
    j.model = model  # set as an attribute so the file also runs against older code
    return j


def _write_anchors(base: Path) -> dict:
    (base / "good.json").write_text(json.dumps({"opener": "specific"}))
    (base / "bad.json").write_text(json.dumps({"opener": "mailmerge"}))
    return {"judge": {
        "rubric": RUBRIC,
        "anchors": [
            {"output": "good.json", "expect": "pass"},
            {"output": "bad.json", "expect": "fail"},
        ],
    }}


def _run(meta=None) -> AgentRun:
    return AgentRun(output={"opener": "specific"}, meta=dict(meta or {}))


def _warnings(ctx) -> list:
    return list(getattr(ctx, "warnings", []))


class TestSelfGradingEngine(unittest.TestCase):
    def _grade(self, judge_model, run_meta):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            entry = _write_anchors(Path(d))
            ctx = EvalContext(base_dir=Path(d), judge=_judge(judge_model, calls))
            v = run_assertion(entry, _run(run_meta), ctx)
        return v, calls, ctx

    def test_same_model_is_not_graded(self):
        v, calls, _ = self._grade("claude-haiku-4-5-20251001", {"model": "claude-haiku-4-5-20251001"})
        self.assertIs(v.status, Status.INCONCLUSIVE)
        self.assertIn("self-grading", v.detail)
        self.assertEqual(calls, [], "the judge must not be called at all, not even on anchors")

    def test_same_model_after_normalization_is_not_graded(self):
        # the model-regression example tags runs "haiku-4.5"; the default judge is
        # claude-haiku-4-5-20251001. Same model, different spelling.
        v, calls, _ = self._grade(DEFAULT_JUDGE_MODEL, {"model": "haiku-4.5"})
        self.assertIs(v.status, Status.INCONCLUSIVE)
        self.assertEqual(calls, [])

    def test_different_model_is_graded(self):
        v, calls, ctx = self._grade(DEFAULT_JUDGE_MODEL, {"model": "sonnet-5"})
        self.assertIs(v.status, Status.PASS)
        self.assertEqual(len(calls), 3)  # two anchors + one panel vote
        self.assertEqual(_warnings(ctx), [])

    def test_unknown_model_is_graded_and_warns_once(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            entry = _write_anchors(Path(d))
            ctx = EvalContext(base_dir=Path(d), judge=_judge(DEFAULT_JUDGE_MODEL, calls))
            # no meta at all, and capture's "default" placeholder: both unknown
            verdicts = [run_assertion(entry, _run(meta), ctx)
                        for meta in (None, {"model": "default"}, None)]
        self.assertTrue(all(v.status is Status.PASS for v in verdicts))
        self.assertEqual(len(calls), 9)
        warnings = _warnings(ctx)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("meta.model", warnings[0])

    def test_suite_target_model_is_the_fallback(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            entry = _write_anchors(base)
            (base / "suite.json").write_text(json.dumps({"target": {"model": "sonnet-5"}}))
            (base / "cases").mkdir()
            for cid in ("a", "b"):
                (base / "cases" / f"{cid}.json").write_text(json.dumps({"id": cid, "assert": [entry]}))
            (base / "runs").mkdir()
            # a: no meta, so target.model (sonnet-5) is the producer -> self-grading
            (base / "runs" / "a.json").write_text(json.dumps({"output": {"opener": "specific"}}))
            # b: its own meta.model wins over the target -> graded
            (base / "runs" / "b.json").write_text(json.dumps(
                {"output": {"opener": "specific"}, "meta": {"model": "opus-4.8"}}))
            ctx = EvalContext(base_dir=base, judge=_judge("claude-sonnet-5", calls))
            result = evaluate_suite(base, ctx)
        by_id = {c.id: c.status for c in result.cases}
        self.assertEqual(by_id, {"a": Status.INCONCLUSIVE, "b": Status.PASS})
        self.assertEqual(len(calls), 3)
        self.assertEqual(_warnings(ctx), [])


class TestModelIdNormalization(unittest.TestCase):
    def test_spellings_of_one_model_match(self):
        for other in ("claude-haiku-4-5", "haiku-4.5", "anthropic/claude-haiku-4-5",
                      "us.anthropic.claude-haiku-4-5-20251001-v1:0", "global.anthropic.claude-haiku-4-5-20251001-v1:0",
                      "claude-haiku-4-5@20251001",
                      "Claude-Haiku-4-5-latest", "haiku"):
            self.assertTrue(A.same_model("claude-haiku-4-5-20251001", other), other)
        self.assertTrue(A.same_model("claude-3-5-sonnet-20241022", "sonnet-3.5"))

    def test_different_models_do_not_match(self):
        for other in ("sonnet-5", "claude-haiku-4-6", "claude-opus-4-5", "sonnet", "haiku-3"):
            self.assertFalse(A.same_model("claude-haiku-4-5-20251001", other), other)

    def test_unknown_never_matches(self):
        for unknown in (None, "", "default", "  "):
            self.assertIsNone(A.normalize_model_id(unknown))
            self.assertFalse(A.same_model(unknown, unknown))


class TestCaptureRecordsModel(unittest.TestCase):
    def test_parse_stream_takes_model_from_init_event(self):
        run = parse_stream([
            {"type": "system", "subtype": "init", "model": "claude-sonnet-4-5-20250929"},
            {"type": "result", "subtype": "success", "result": "{}"},
        ])
        self.assertEqual(run.meta.get("model"), "claude-sonnet-4-5-20250929")

    def test_capture_keeps_an_explicit_model_tag(self):
        # `matrix --reference opus-4.8` matches on the --model tag, so it must win
        from litmus.adapters import claude_code
        stream = json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-4-8-20260101"})
        done = mock.Mock(stdout=stream + "\n", returncode=0)
        with mock.patch.object(claude_code.subprocess, "run", return_value=done):
            tagged = claude_code.capture("p", model="opus-4.8")
            untagged = claude_code.capture("p")
        self.assertEqual(tagged.meta["model"], "opus-4.8")
        self.assertEqual(tagged.meta["model_id"], "claude-opus-4-8-20260101")
        self.assertEqual(untagged.meta["model"], "claude-opus-4-8-20260101")


class TestSelfGradingCli(unittest.TestCase):
    def _suite(self, base: Path, meta) -> None:
        entry = _write_anchors(base)
        (base / "cases").mkdir()
        (base / "cases" / "c.json").write_text(json.dumps({"id": "c", "assert": [entry]}))
        (base / "runs" / "c").mkdir(parents=True)
        for i in (1, 2):  # two samples, so "once" is actually tested
            run = {"output": {"opener": "specific"}}
            if meta is not None:
                run["meta"] = meta
            (base / "runs" / "c" / f"s{i}.json").write_text(json.dumps(run))

    def _cli(self, meta, *extra):
        calls = []

        def honest(self_, artifact, rubric):
            calls.append(artifact)
            return artifact.get("opener") == "specific"

        with tempfile.TemporaryDirectory() as d, \
                mock.patch("shutil.which", return_value=FAKE_CLAUDE), \
                mock.patch.object(ClaudeJudge, "__call__", honest):
            self._suite(Path(d), meta)
            code, out, err = _main(["run", d, "--judge", "claude", *extra])
        return code, out, err, calls

    def test_default_judge_on_its_own_runs_is_not_graded(self):
        code, out, err, calls = self._cli({"model": "haiku-4.5"})
        self.assertEqual(calls, [])
        self.assertIn("INCONC", out)
        self.assertNotIn("1/1 green", out)

    def test_different_judge_model_is_graded(self):
        code, out, err, calls = self._cli({"model": "haiku-4.5"}, "--judge-model", "claude-sonnet-4-5")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(calls), 6)
        self.assertIn("1/1 green", out)
        self.assertNotIn("warning", err)

    def test_unknown_producer_is_graded_with_one_warning(self):
        code, out, err, calls = self._cli(None)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(calls), 6)
        self.assertIn("1/1 green", out)
        self.assertEqual(err.count("litmus: warning:"), 1, err)
        self.assertIn("no-self-grading", err)


if __name__ == "__main__":
    unittest.main()
