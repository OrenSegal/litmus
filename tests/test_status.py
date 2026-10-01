"""`litmus status`: tells captured runs from fixtures and says what a green proves."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from litmus.status import render_status, suite_status
from tests.test_hardening import ROOT, _main, _write


class TestStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.suite = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_shipped_examples_are_reported_as_fixtures(self):
        st = suite_status(ROOT / "examples" / "signal-scout")
        self.assertEqual(st.captured, 0)
        self.assertEqual(st.fixtures, 2)
        self.assertIn("are fixtures", render_status(st))

    def test_captured_and_fixture_runs_are_counted_apart(self):
        _write(self.suite / "cases" / "a.json", {
            "id": "a", "samples": 3,
            "assert": [{"must_run": "x"}, {"judge": {"rubric": "r", "anchors": []}}]})
        _write(self.suite / "runs" / "a" / "live.json",
               {"meta": {"model": "m", "captured_by": "litmus capture"}})
        _write(self.suite / "runs" / "a" / "hand.json", {"meta": {"model": "m"}})
        st = suite_status(self.suite)
        self.assertEqual((st.captured, st.fixtures, st.judge_assertions), (1, 1, 1))
        text = render_status(st)
        self.assertIn("declares samples: 3, has 2", text)
        self.assertIn("1 judge assertion(s)", text)
        self.assertIn("no baseline.json", text)

    def test_case_without_runs_is_listed_not_fatal(self):
        _write(self.suite / "cases" / "a.json", {"id": "a", "assert": [{"must_run": "x"}]})
        code, out, _ = _main(["status", str(self.suite)])
        self.assertEqual(code, 0)
        self.assertIn("no usable runs", out)

    def test_stamped_baseline_is_reported(self):
        _write(self.suite / "cases" / "a.json", {"id": "a", "assert": [{"must_run": "x"}]})
        _write(self.suite / "runs" / "a.json", {"tool_calls": [{"name": "x"}]})
        self.assertEqual(_main(["bless", str(self.suite)])[0], 0)
        self.assertIsNone(json.loads((self.suite / "baseline.json").read_text())["litmus"]["judge"])
        code, out, _ = _main(["status", str(self.suite)])
        self.assertEqual(code, 0)
        self.assertIn("with no judge", out)

    def test_missing_suite_exits_2(self):
        code, _, err = _main(["status", str(self.suite / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("litmus: error:", err)


if __name__ == "__main__":
    unittest.main()
