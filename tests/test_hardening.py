"""Regression tests for bugs found in the 0.2.0 hardening audit.

Each test pins one reproduced bug: a crafted suite reading files outside the
suite directory, a vacuous green, a gate that a regression slips past, an exit
code that mixes "red" with "broken", a judge reply misread as PASS, a failed
capture written as a run. All offline: no model, no network beyond loopback.
"""

from __future__ import annotations

import http.server
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from litmus import cli
from litmus.assertions import EvalContext, JudgeError, run_assertion
from litmus.gate import diff
from litmus.models import AgentRun, AssertionResult, Case, CaseResult, Status, SuiteResult, ToolCall
from litmus.runner import evaluate_case, evaluate_suite

ROOT = Path(__file__).resolve().parent.parent


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.suite = self.root / "suite"
        self.suite.mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()


# --------------------------------------------------------------------------- #
# path traversal: a case may only read files inside its suite directory
# --------------------------------------------------------------------------- #
class TestContainment(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        _write(self.root / "outside" / "secret.json", {"output": {"secret": "TOPSECRET"}})

    def test_runs_path_outside_suite_is_refused(self):
        _write(self.suite / "cases" / "c.json",
               {"id": "c", "runs": ["../outside/secret.json"], "assert": [{"must_not": {"tool": "x"}}]})
        result = evaluate_suite(self.suite)
        self.assertIs(result.cases[0].status, Status.FAIL)
        self.assertIn("outside the suite", result.cases[0].error)

    def test_absolute_runs_path_is_refused(self):
        _write(self.suite / "cases" / "c.json",
               {"id": "c", "runs": [str(self.root / "outside" / "secret.json")],
                "assert": [{"must_not": {"tool": "x"}}]})
        result = evaluate_suite(self.suite)
        self.assertIs(result.cases[0].status, Status.FAIL)
        self.assertIn("outside the suite", result.cases[0].error)

    def test_case_id_cannot_walk_out_of_runs(self):
        _write(self.root / "outside" / "x.json", {"output": {}})
        _write(self.suite / "cases" / "c.json",
               {"id": "../../outside/x", "assert": [{"must_not": {"tool": "x"}}]})
        result = evaluate_suite(self.suite)
        self.assertIs(result.cases[0].status, Status.FAIL)
        self.assertIn("outside the suite", result.cases[0].error)

    def test_schema_ref_outside_suite_is_refused(self):
        ctx = EvalContext(base_dir=self.suite)
        v = run_assertion({"schema": {"path": "$", "ref": "../outside/secret.json"}},
                          AgentRun(output={}), ctx)
        self.assertIs(v.status, Status.FAIL)
        self.assertIn("outside the suite", v.detail)

    def test_symlink_escaping_suite_is_refused(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlinks")
        try:
            (self.suite / "link.json").symlink_to(self.root / "outside" / "secret.json")
        except OSError:
            self.skipTest("cannot create symlinks here")
        ctx = EvalContext(base_dir=self.suite)
        v = run_assertion({"schema": {"path": "$", "ref": "link.json"}}, AgentRun(output={}), ctx)
        self.assertIs(v.status, Status.FAIL)
        self.assertIn("outside the suite", v.detail)

    def test_judge_anchor_outside_suite_is_never_sent_to_the_judge(self):
        seen = []

        def judge(artifact, rubric):
            seen.append(artifact)
            return True

        judge.model = "judge-model-x"  # type: ignore[attr-defined]
        _write(self.suite / "good.json", {"ok": True})
        ctx = EvalContext(base_dir=self.suite, judge=judge)
        entry = {"judge": {"rubric": "r", "anchors": [
            {"output": "good.json", "expect": "pass"},
            {"output": "../outside/secret.json", "expect": "fail"},
        ]}}
        v = run_assertion(entry, AgentRun(output={}, meta={"model": "producer"}), ctx)
        self.assertIs(v.status, Status.FAIL)
        self.assertIn("outside the suite", v.detail)
        self.assertNotIn({"output": {"secret": "TOPSECRET"}}, seen)

    def test_schema_ref_inside_suite_still_works(self):
        _write(self.suite / "s.schema.json", {"type": "object", "required": ["a"]})
        ctx = EvalContext(base_dir=self.suite)
        v = run_assertion({"schema": {"path": "$", "ref": "s.schema.json"}}, AgentRun(output={"a": 1}), ctx)
        self.assertIs(v.status, Status.PASS)


# --------------------------------------------------------------------------- #
# vacuous greens: a PASS must come from a check that could have failed
# --------------------------------------------------------------------------- #
class TestNoVacuousGreen(unittest.TestCase):
    def test_grounded_with_no_fetchable_source_is_not_pass(self):
        run = AgentRun(output={"claim": "anything at all", "src": "not-a-url"})
        v = run_assertion({"grounded": {"claim": "$.claim", "source": "$.src"}}, run, EvalContext())
        self.assertIsNot(v.status, Status.PASS)

    def test_grounded_with_mismatched_claim_and_source_counts_fails(self):
        from litmus.fetch import DictFetcher

        run = AgentRun(output={"claims": ["alpha beta gamma", "delta epsilon zeta"],
                               "srcs": ["https://a.example"]})
        ctx = EvalContext(fetcher=DictFetcher({"https://a.example": "alpha beta gamma"}))
        v = run_assertion({"grounded": {"claim": "$.claims[*]", "source": "$.srcs[*]"}}, run, ctx)
        self.assertIs(v.status, Status.FAIL)
        self.assertIn("2 claim(s) but 1 source(s)", v.detail)

    def test_empty_budget_is_not_pass(self):
        v = run_assertion({"budget": {}}, AgentRun(cost_usd=1.0), EvalContext())
        self.assertIs(v.status, Status.FAIL)

    def test_unknown_budget_metric_fails(self):
        v = run_assertion({"budget": {"meta": 1}}, AgentRun(), EvalContext())
        self.assertIs(v.status, Status.FAIL)


# --------------------------------------------------------------------------- #
# case roll-up and declared samples
# --------------------------------------------------------------------------- #
class TestCaseRollup(unittest.TestCase):
    def test_pass_plus_skip_is_green(self):
        # docs: "A case is green only if every assertion is PASS or SKIP"
        case = Case(id="c", asserts=[{"must_run": "a"}, {"resolves": "$.urls[*]"}])
        res = evaluate_case(case, [AgentRun(output={}, tool_calls=[ToolCall("a")])], EvalContext())
        self.assertIs(res.status, Status.PASS)

    def test_only_skips_is_skip(self):
        case = Case(id="c", asserts=[{"resolves": "$.urls[*]"}])
        res = evaluate_case(case, [AgentRun(output={})], EvalContext())
        self.assertIs(res.status, Status.SKIP)

    def test_fewer_runs_than_declared_samples_is_not_green(self):
        case = Case(id="c", asserts=[{"must_run": "a"}], samples=3)
        res = evaluate_case(case, [AgentRun(tool_calls=[ToolCall("a")])], EvalContext())
        self.assertIs(res.status, Status.INCONCLUSIVE)
        self.assertIn("samples: 3", res.error)

    def test_sample_shortfall_does_not_hide_a_failure(self):
        case = Case(id="c", asserts=[{"must_run": "a"}], samples=3)
        res = evaluate_case(case, [AgentRun()], EvalContext())
        self.assertIs(res.status, Status.FAIL)


# --------------------------------------------------------------------------- #
# the gate ratchet
# --------------------------------------------------------------------------- #
def _ar(name: str, status: Status) -> AssertionResult:
    return AssertionResult(name, status, 1.0 if status is Status.PASS else 0.0, 1.0, 1)


class TestGateRatchet(unittest.TestCase):
    def test_removed_case_is_a_regression(self):
        cur = SuiteResult("s", [CaseResult("a", Status.PASS)])
        base = {"name": "s", "cases": {"a": {"status": "PASS"}, "b": {"status": "PASS"}}}
        report = diff(cur, base)
        self.assertFalse(report.ok)
        self.assertEqual(report.removed, ["b"])

    def test_inconclusive_case_turning_fail_is_a_regression(self):
        # a judge case gated without --judge is INCONCLUSIVE; its deterministic
        # assertions must still be gated
        base = {"cases": {"a": {"status": "INCONCLUSIVE", "assertions": {
            "00:must_run": {"status": "PASS", "pass_rate": 1.0},
            "01:judge": {"status": "INCONCLUSIVE", "pass_rate": 0.0}}}}}
        cur = SuiteResult("s", [CaseResult("a", Status.FAIL, [
            _ar("00:must_run", Status.FAIL), _ar("01:judge", Status.INCONCLUSIVE)])])
        report = diff(cur, base)
        self.assertFalse(report.ok)
        self.assertTrue(any("00:must_run" in r for r in report.regressions), report.regressions)

    def test_still_red_case_with_a_newly_failing_assertion_is_a_regression(self):
        base = {"cases": {"a": {"status": "FAIL", "assertions": {
            "00:must_run": {"status": "PASS", "pass_rate": 1.0},
            "01:equals": {"status": "FAIL", "pass_rate": 0.0}}}}}
        cur = SuiteResult("s", [CaseResult("a", Status.FAIL, [
            _ar("00:must_run", Status.FAIL), _ar("01:equals", Status.FAIL)])])
        report = diff(cur, base)
        self.assertFalse(report.ok)

    def test_still_red_with_no_new_failure_is_ok(self):
        base = {"cases": {"a": {"status": "FAIL", "assertions": {
            "00:equals": {"status": "FAIL", "pass_rate": 0.0}}}}}
        cur = SuiteResult("s", [CaseResult("a", Status.FAIL, [_ar("00:equals", Status.FAIL)])])
        report = diff(cur, base)
        self.assertTrue(report.ok)
        self.assertEqual(report.still_red, ["a"])


class TestCliExitCodes(_Tmp):
    def _green_suite(self) -> None:
        _write(self.suite / "cases" / "a.json", {"id": "a", "assert": [{"must_run": "x"}]})
        _write(self.suite / "runs" / "a.json", {"tool_calls": [{"name": "x"}]})

    def test_missing_suite_dir_exits_2(self):
        code, _, err = _main(["run", str(self.root / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("litmus: error:", err)

    def test_malformed_case_file_exits_2(self):
        _write(self.suite / "cases" / "a.json", "{not json")
        code, _, err = _main(["run", str(self.suite)])
        self.assertEqual(code, 2)
        self.assertIn("a.json", err)

    def test_case_file_that_is_not_an_object_exits_2(self):
        _write(self.suite / "cases" / "a.json", [1, 2])
        code, _, err = _main(["run", str(self.suite)])
        self.assertEqual(code, 2)

    def test_malformed_run_file_fails_that_case_only(self):
        self._green_suite()
        _write(self.suite / "cases" / "b.json", {"id": "b", "assert": [{"must_run": "x"}]})
        _write(self.suite / "runs" / "b.json", "{not json")
        code, out, _ = _main(["run", str(self.suite)])
        self.assertEqual(code, 1)
        self.assertIn("1/2 green", out)

    def test_duplicate_case_ids_exit_2(self):
        self._green_suite()
        _write(self.suite / "cases" / "a2.json", {"id": "a", "assert": [{"must_run": "y"}]})
        code, _, err = _main(["run", str(self.suite)])
        self.assertEqual(code, 2)
        self.assertIn("duplicate case id", err)

    def test_gate_against_a_file_that_is_not_a_baseline_exits_2(self):
        self._green_suite()
        _write(self.root / "suite.json", {"name": "other"})
        code, _, err = _main(["gate", str(self.suite), "--baseline", str(self.root / "suite.json")])
        self.assertEqual(code, 2)
        self.assertIn("not a litmus baseline", err)

    def test_gate_against_another_suites_baseline_fails(self):
        self._green_suite()
        _write(self.root / "b.json", {"name": "other", "cases": {"zzz": {"status": "PASS"}}})
        code, out, err = _main(["gate", str(self.suite), "--baseline", str(self.root / "b.json")])
        self.assertEqual(code, 1)
        self.assertIn("removed", out)
        self.assertIn("baseline is for suite 'other'", err)

    def test_matrix_unknown_reference_exits_2(self):
        code, _, err = _main(["matrix", str(ROOT / "examples" / "model-regression"),
                              "--reference", "opus-4.9"])
        self.assertEqual(code, 2)
        self.assertIn("opus-4.9", err)

    def test_matrix_known_reference_still_detects_regression(self):
        code, _, _ = _main(["matrix", str(ROOT / "examples" / "model-regression"),
                            "--reference", "opus-4.8"])
        self.assertEqual(code, 1)

    def test_negative_drift_tolerance_is_rejected(self):
        self._green_suite()
        code, _, _ = _main(["gate", str(self.suite), "--drift-tol", "-0.5"])
        self.assertEqual(code, 2)

    def test_bless_records_the_judge_setting_and_gate_warns_on_mismatch(self):
        self._green_suite()
        code, _, _ = _main(["bless", str(self.suite)])
        self.assertEqual(code, 0)
        baseline = json.loads((self.suite / "baseline.json").read_text())
        self.assertIn("litmus", baseline)
        self.assertIsNone(baseline["litmus"]["judge"])
        baseline["litmus"]["judge"] = "claude-sonnet-5"
        (self.suite / "baseline.json").write_text(json.dumps(baseline))
        code, _, err = _main(["gate", str(self.suite)])
        self.assertEqual(code, 0)
        self.assertIn("blessed with judge", err)


# --------------------------------------------------------------------------- #
# regex DoS in `matches`
# --------------------------------------------------------------------------- #
class TestRegexTimeout(unittest.TestCase):
    EVIL = {"matches": {"path": "$.t", "pattern": "^(a+)+$", "timeout": 0.2}}
    RUN = AgentRun(output={"t": "a" * 40 + "!"})

    def test_catastrophic_pattern_times_out_as_fail(self):
        t = time.monotonic()
        v = run_assertion(self.EVIL, self.RUN, EvalContext())
        self.assertLess(time.monotonic() - t, 5)
        self.assertIs(v.status, Status.FAIL)
        self.assertIn("timed out", v.detail)

    def test_catastrophic_pattern_times_out_off_the_main_thread(self):
        box = {}
        th = threading.Thread(target=lambda: box.update(v=run_assertion(self.EVIL, self.RUN, EvalContext())))
        t = time.monotonic()
        th.start()
        th.join(30)
        self.assertLess(time.monotonic() - t, 15)
        self.assertIs(box["v"].status, Status.FAIL)
        self.assertIn("timed out", box["v"].detail)

    def test_normal_patterns_still_work(self):
        run = AgentRun(output={"t": ["nope", "order #123"]})
        self.assertIs(run_assertion({"matches": {"path": "$.t[*]", "pattern": r"#\d+"}}, run,
                                    EvalContext()).status, Status.PASS)
        self.assertIs(run_assertion({"matches": {"path": "$.t[*]", "pattern": r"^x"}}, run,
                                    EvalContext()).status, Status.FAIL)


# --------------------------------------------------------------------------- #
# judge adapter
# --------------------------------------------------------------------------- #
class TestClaudeJudgeAdapter(unittest.TestCase):
    def _reply(self, stdout: str) -> bool:
        from litmus.judge import ClaudeJudge

        done = subprocess.CompletedProcess(["claude"], 0, stdout=stdout, stderr="")
        with mock.patch("litmus.judge.subprocess.run", return_value=done):
            return ClaudeJudge(model="m")({"a": 1}, "rubric")

    def test_hedged_fail_reply_is_not_read_as_pass(self):
        self.assertFalse(self._reply("FAIL - the opener would not PASS review\n"))

    def test_markdown_wrapped_verdicts_parse(self):
        self.assertTrue(self._reply("**PASS**\nreason"))
        self.assertFalse(self._reply("\nFAIL.\n"))

    def test_unparseable_reply_is_a_judge_error(self):
        with self.assertRaises(JudgeError):
            self._reply("I think this should PASS\n")

    def test_prompt_goes_over_stdin_with_tools_disabled(self):
        from litmus.judge import ClaudeJudge

        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="PASS\n", stderr="")

        with mock.patch("litmus.judge.subprocess.run", side_effect=fake_run):
            ClaudeJudge(model="m")({"opener": "specific"}, "the opener is specific")
        argv, kwargs = calls[0]
        self.assertIn('"opener": "specific"', kwargs["input"])
        self.assertNotIn("the opener is specific", " ".join(argv))
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotEqual(Path(kwargs["cwd"]).resolve(), Path.cwd().resolve())

    @unittest.skipIf(sys.platform == "win32", "uses a POSIX shell script as a fake CLI")
    def test_large_artifact_reaches_a_real_subprocess(self):
        # before: OSError [Errno 7] Argument list too long, from argv
        from litmus.judge import ClaudeJudge

        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "claude"
            fake.write_text("#!/bin/sh\ncat > /dev/null\necho PASS\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ.get("PATH", "")}):
                self.assertTrue(ClaudeJudge(model="m")({"a": "x" * 3_000_000}, "r"))


# --------------------------------------------------------------------------- #
# capture adapter
# --------------------------------------------------------------------------- #
class TestCaptureFailures(_Tmp):
    def _capture(self, **patch):
        out = self.root / "run.json"
        with mock.patch("litmus.adapters.claude_code.subprocess.run", **patch):
            code, stdout, err = _main(["capture", "do the task", "--out", str(out)])
        return code, err, out

    def test_nonzero_exit_is_an_error_and_writes_nothing(self):
        failed = subprocess.CompletedProcess(["claude"], 1, stdout="", stderr="Invalid API key")
        code, err, out = self._capture(return_value=failed)
        self.assertEqual(code, 2)
        self.assertIn("Invalid API key", err)
        self.assertFalse(out.exists())

    def test_missing_cli_is_an_error(self):
        code, err, out = self._capture(side_effect=FileNotFoundError("claude"))
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())

    def test_timeout_is_an_error(self):
        code, err, out = self._capture(side_effect=subprocess.TimeoutExpired(["claude"], 300))
        self.assertEqual(code, 2)
        self.assertIn("timed out", err)

    def test_no_events_is_an_error(self):
        done = subprocess.CompletedProcess(["claude"], 0, stdout="not json\n", stderr="")
        code, err, out = self._capture(return_value=done)
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())

    def test_prompt_goes_over_stdin_and_run_is_stamped(self):
        stream = "\n".join(json.dumps(e) for e in [
            {"type": "system", "subtype": "init", "model": "claude-sonnet-5"},
            {"type": "result", "subtype": "success", "result": "{\"ok\": true}"},
        ])
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=stream, stderr="")

        code, err, out = self._capture(side_effect=fake_run)
        self.assertEqual(code, 0, err)
        argv, kwargs = calls[0]
        self.assertEqual(kwargs["input"], "do the task")
        self.assertNotIn("do the task", argv)
        meta = json.loads(out.read_text())["meta"]
        self.assertEqual(meta["captured_by"], "litmus capture")
        self.assertIn("captured_at", meta)

    def test_malformed_stream_events_do_not_crash_the_parser(self):
        from litmus.adapters.claude_code import parse_stream

        run = parse_stream([{"type": "assistant", "message": None},
                            {"type": "assistant", "message": {"content": [
                                {"type": "tool_use", "name": "t", "input": "not-a-dict"}]}},
                            {"type": "result", "usage": None}])
        self.assertEqual([c.name for c in run.tool_calls], ["t"])


# --------------------------------------------------------------------------- #
# fetcher
# --------------------------------------------------------------------------- #
class TestFetcherHeaders(unittest.TestCase):
    def test_user_agent_is_sent(self):
        from litmus.fetch import UrllibFetcher

        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib name
                seen.append(self.headers.get("User-Agent"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<p>hello world</p>")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            res = UrllibFetcher().fetch(f"http://127.0.0.1:{server.server_port}/", 5)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(res.status, 200)
        self.assertIn("litmus", seen[0])


# --------------------------------------------------------------------------- #
# release hygiene: every manifest names the same version
# --------------------------------------------------------------------------- #
class TestVersionsAgree(unittest.TestCase):
    def test_all_manifests_match_the_package_version(self):
        import re

        from litmus import __version__

        pyproject = (ROOT / "pyproject.toml").read_text()
        py_version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        package = json.loads((ROOT / "package.json").read_text())["version"]
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["version"]
        self.assertEqual({__version__, py_version, package, plugin, market}, {__version__})

    def test_version_flag_matches_package_version(self):
        from litmus import __version__

        code, out, _ = _main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)


if __name__ == "__main__":
    unittest.main()
