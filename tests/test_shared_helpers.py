"""Helpers that several modules share, so each rule lives in one place.

Status counts and the summary line (terminal, HTML, index, bless), the detail
a report shows for a failing assertion, which URLs are fetchable, the
placeholder for an unknown model, and the AgentRun JSON shape (read by the
engine, written by `litmus capture`).
"""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from litmus.cli import _bounded_float
from litmus.fetch import FetchResult, UrllibFetcher, is_http_url
from litmus.model_ids import UNKNOWN_MODEL, normalize_model_id
from litmus.models import AgentRun, AssertionResult, CaseResult, Status, SuiteResult, ToolCall, Verdict
from litmus.report import first_problem, rate_label, summary_line

from tests.test_hardening import _main, _Tmp


def _suite(*statuses: Status) -> SuiteResult:
    return SuiteResult("s", [CaseResult(f"c{i}", s) for i, s in enumerate(statuses)])


class TestCounts(unittest.TestCase):
    def test_counts_every_status_including_zero(self):
        counts = _suite(Status.PASS, Status.PASS, Status.FAIL).counts()
        self.assertEqual(counts, {Status.PASS: 2, Status.FAIL: 1, Status.INCONCLUSIVE: 0, Status.SKIP: 0})

    def test_summary_line(self):
        line = summary_line(_suite(Status.PASS, Status.FAIL, Status.INCONCLUSIVE, Status.SKIP))
        self.assertEqual(line, "1/4 green · 1 failing · 1 inconclusive · 1 skipped")


class TestAssertionDetail(unittest.TestCase):
    def _result(self, status, verdicts, rate=1.0):
        return AssertionResult("00:equals", status, rate, 1.0, len(verdicts), verdicts)

    def test_first_problem_is_the_first_non_passing_sample_with_a_detail(self):
        a = self._result(Status.FAIL, [Verdict.passed("equals", "ok"), Verdict.failed("equals", ""),
                                       Verdict.failed("equals", "x != y"), Verdict.failed("equals", "later")], 0.25)
        self.assertEqual(first_problem(a), "x != y")

    def test_a_passing_assertion_has_no_problem(self):
        a = self._result(Status.PASS, [Verdict.passed("equals", "ok"), Verdict.skipped("equals", "nothing")])
        self.assertIsNone(first_problem(a))

    def test_rate_label_only_for_a_split_pass_rate(self):
        self.assertEqual(rate_label(self._result(Status.PASS, [], 1.0)), "")
        self.assertEqual(rate_label(self._result(Status.FAIL, [], 0.0)), "")
        self.assertEqual(rate_label(self._result(Status.FAIL, [], 2 / 3)), "(67%)")


class TestIsHttpUrl(unittest.TestCase):
    def test_only_http_and_https_strings(self):
        for url in ("http://a.example", "https://a.example/x"):
            self.assertTrue(is_http_url(url), url)
        for value in ("ftp://a.example", "file:///etc/passwd", "a.example", "", None, 3, ["https://a"]):
            self.assertFalse(is_http_url(value), value)

    def test_the_fetcher_refuses_anything_else_without_touching_the_network(self):
        with mock.patch("litmus.fetch.urllib.request.urlopen") as urlopen:
            for url in ("HTTP://127.0.0.1/", "ftp://a.example", "file:///etc/passwd"):
                self.assertEqual(UrllibFetcher().fetch(url), FetchResult(None, ""), url)
        urlopen.assert_not_called()


class TestUnknownModel(unittest.TestCase):
    def test_the_placeholder_names_no_model(self):
        self.assertIsNone(normalize_model_id(UNKNOWN_MODEL))


class TestAgentRunShape(unittest.TestCase):
    def test_to_obj_round_trips_every_field(self):
        run = AgentRun(output={"a": [1]}, tool_calls=[ToolCall("t", {"k": "v"})], final_text="done",
                       transcript="step 1\nstep 2", cost_usd=0.5, tokens=10, latency_ms=20.0,
                       meta={"model": "m"})
        obj = run.to_obj()
        self.assertEqual(json.loads(json.dumps(obj)), obj)
        self.assertEqual(AgentRun.from_obj(obj), run)


class TestCaptureKeepsTheTranscript(_Tmp):
    def test_captured_run_file_carries_the_transcript(self):
        stream = "\n".join(json.dumps(e) for e in [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking out loud"}]}},
            {"type": "result", "subtype": "success", "result": "{\"ok\": true}"},
        ])
        out = self.root / "run.json"
        done = subprocess.CompletedProcess(["claude"], 0, stdout=stream, stderr="")
        with mock.patch("litmus.adapters.claude_code.subprocess.run", return_value=done):
            code, _, err = _main(["capture", "do the task", "--out", str(out)])
        self.assertEqual(code, 0, err)
        self.assertIn("thinking out loud", json.loads(out.read_text())["transcript"])


class TestBoundedFloat(unittest.TestCase):
    def test_accepts_the_closed_range_and_rejects_the_rest(self):
        import argparse

        parse = _bounded_float(0.0, 1.0)
        self.assertEqual(parse("0"), 0.0)
        self.assertEqual(parse("1"), 1.0)
        for bad in ("-0.1", "1.1", "nan", "inf", "x"):
            with self.subTest(value=bad), self.assertRaises(argparse.ArgumentTypeError):
                parse(bad)


if __name__ == "__main__":
    unittest.main()
