"""Tests for M2-M6: stream parser, judge guardrails, matrix, index, HTML.

All offline. The judge tests use ScriptedJudge (a deterministic fake) to prove
the §6 guardrails without any model call.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from litmus.adapters.claude_code import parse_stream
from litmus.assertions import EvalContext, run_assertion
from litmus.index import IndexEntry, build_index, render_index
from litmus.judge import ScriptedJudge
from litmus.matrix import evaluate_matrix
from litmus.models import AgentRun, CaseResult, Status, SuiteResult
from litmus.report_html import render_html


class TestStreamParser(unittest.TestCase):
    EVENTS = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "websearch", "input": {"q": "x"}},
            {"type": "tool_use", "name": "finalize.py", "input": {}},
        ]}},
        {"type": "result", "subtype": "success",
         "result": "Done.\n```json\n{\"individuals\": [{\"type\": \"Individual\"}]}\n```",
         "total_cost_usd": 0.03, "duration_ms": 5100,
         "usage": {"input_tokens": 1000, "output_tokens": 200}},
    ]

    def test_tool_calls_and_telemetry(self):
        run = parse_stream(self.EVENTS)
        self.assertEqual([c.name for c in run.tool_calls], ["websearch", "finalize.py"])
        self.assertEqual(run.cost_usd, 0.03)
        self.assertEqual(run.tokens, 1200)
        self.assertEqual(run.latency_ms, 5100)

    def test_output_extracted_from_fence(self):
        run = parse_stream(self.EVENTS)
        self.assertEqual(run.output, {"individuals": [{"type": "Individual"}]})

    def test_graceful_on_junk(self):
        run = parse_stream([{"type": "system", "foo": 1}, {"type": "result", "result": "no json here"}])
        self.assertIsNone(run.output)
        self.assertEqual(run.tool_calls, [])


class TestJudgeGuardrails(unittest.TestCase):
    def _ctx_with_anchors(self, judge, base: Path) -> EvalContext:
        (base / "good.json").write_text(json.dumps({"opener": "specific"}))
        (base / "bad.json").write_text(json.dumps({"opener": "mailmerge"}))
        return EvalContext(base_dir=base, judge=judge)

    def _entry(self):
        return {"judge": {
            "rubric": "opener is specific",
            "anchors": [{"output": "good.json", "expect": "pass"},
                        {"output": "bad.json", "expect": "fail"}],
            "panel": 3,
        }}

    def test_calibrated_judge_passes(self):
        # honest judge: 'specific' -> pass, else fail; grades anchors correctly
        judge = ScriptedJudge(lambda art, r: art.get("opener") == "specific")
        with tempfile.TemporaryDirectory() as d:
            ctx = self._ctx_with_anchors(judge, Path(d))
            v = run_assertion(self._entry(), AgentRun(output={"opener": "specific"}), ctx)
        self.assertIs(v.status, Status.PASS)

    def test_miscalibrated_judge_is_void(self):
        # rubber-stamp judge: always PASS -> misgrades the fail anchor -> INCONCLUSIVE
        judge = ScriptedJudge(lambda art, r: True)
        with tempfile.TemporaryDirectory() as d:
            ctx = self._ctx_with_anchors(judge, Path(d))
            v = run_assertion(self._entry(), AgentRun(output={"opener": "mailmerge"}), ctx)
        self.assertIs(v.status, Status.INCONCLUSIVE)

    def test_panel_tie_defaults_fail(self):
        # calibrated on anchors, but the real artifact splits the panel evenly-ish
        flip = {"n": 0}

        def rule(art, r):
            if art.get("opener") == "specific":
                return True
            if art.get("opener") == "mailmerge":
                return False
            flip["n"] += 1
            return flip["n"] % 2 == 0  # 1 of 3 votes -> minority

        with tempfile.TemporaryDirectory() as d:
            ctx = self._ctx_with_anchors(ScriptedJudge(rule), Path(d))
            v = run_assertion(self._entry(), AgentRun(output={"opener": "borderline"}), ctx)
        self.assertIs(v.status, Status.FAIL)


class TestMatrix(unittest.TestCase):
    def _build_suite(self, base: Path):
        (base / "cases").mkdir()
        (base / "cases" / "c1.json").write_text(json.dumps(
            {"id": "c1", "assert": [{"must_run": "finalize.py"}]}))
        for model, tools in [("opus-4.8", ["finalize.py"]), ("haiku-4.5", [])]:
            d = base / "runs" / "c1"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{model}.json").write_text(json.dumps(
                {"meta": {"model": model}, "tool_calls": [{"name": t} for t in tools]}))

    def test_matrix_and_cross_model_regression(self):
        with tempfile.TemporaryDirectory() as dd:
            base = Path(dd)
            self._build_suite(base)
            result = evaluate_matrix(base)
            self.assertIs(result.grid["c1"]["opus-4.8"].status, Status.PASS)
            self.assertIs(result.grid["c1"]["haiku-4.5"].status, Status.FAIL)
            regs = result.regressions_vs("opus-4.8")
            self.assertEqual(len(regs), 1)
            self.assertIn("haiku-4.5", regs[0])


class TestIndex(unittest.TestCase):
    def test_ranked_worst_first(self):
        good = SuiteResult("a", [CaseResult("x", Status.PASS), CaseResult("y", Status.PASS)], {"skill": "a"})
        bad = SuiteResult("b", [CaseResult("x", Status.FAIL), CaseResult("y", Status.PASS)], {"skill": "b"})
        entries = [IndexEntry.from_suite("a", "opus-4.8", good), IndexEntry.from_suite("b", "haiku-4.5", bad)]
        ranked = build_index(entries)
        self.assertEqual(ranked[0].skill, "b")  # worst green-rate first
        self.assertIn("Hallucination Index", render_index(entries))


class TestHtml(unittest.TestCase):
    def test_render_contains_status_and_case(self):
        result = SuiteResult("s", [CaseResult("mycase", Status.FAIL)], {"model": "sonnet-5"})
        doc = render_html(result)
        self.assertIn("<!doctype html>", doc)
        self.assertIn("mycase", doc)
        self.assertIn("FAIL", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
