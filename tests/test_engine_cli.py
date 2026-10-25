from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path
from typing import List

from litmus.adapters.claude_plugin_eval import ClaudePluginEvalAdapter
from litmus.audit import audit_result
from litmus.cli import main
from litmus.engine import MutateOptions, mutate
from litmus.mutants import Mutant, sha256, write_manifest

from .helpers import DEMO, ROOT, FakeRunner, TempDir, demo_scores, result_doc


def cli(*argv: str):  # type: ignore[no-untyped-def]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestEngine(unittest.TestCase):
    def test_fake_runner_end_to_end_on_demo(self):
        with TempDir() as d:
            plugin = d / "demo"
            shutil.copytree(DEMO, plugin)
            runner = FakeRunner(demo_scores)
            rep = mutate(ClaudePluginEvalAdapter(runner), plugin, d / "out", MutateOptions())
            self.assertEqual(runner.labels[0], "baseline")
            self.assertTrue(all("--ablation" in c and "none" in c for c in runner.calls))
            verdicts = {m["id"].split(":")[0] + ":" + m["description"][:30]: m["verdict"] for m in rep["mutants"]}
            self.assertIn("KILLED", verdicts.values())
            self.assertIn("SURVIVED", verdicts.values())
            killed = [m for m in rep["mutants"] if m["verdict"] == "KILLED"]
            self.assertTrue(all(m["killed_by"] == ["tests-only-diff"] for m in killed))
            self.assertTrue(any(m["operator"] == "delete-body" for m in killed))
            self.assertTrue((d / "out" / "mutants.json").is_file())
            # the original plugin is never modified
            self.assertEqual((plugin / "skills/changelog/SKILL.md").read_text(),
                             (DEMO / "skills/changelog/SKILL.md").read_text())

    def test_edits_during_the_run_do_not_reach_later_mutants(self):
        with TempDir() as d:
            plugin = d / "demo"
            shutil.copytree(DEMO, plugin)
            readme = plugin / "notes.md"
            readme.write_text("v1\n")
            seen: List[bool] = []

            def score(workdir: Path) -> dict:
                seen.append((workdir / "notes.md").read_text().endswith("EDITED\n"))
                readme.write_text(readme.read_text() + "EDITED\n")  # the owner edits mid-run
                return demo_scores(workdir)

            rep = mutate(ClaudePluginEvalAdapter(FakeRunner(score)), plugin, d / "out", MutateOptions(max_mutants=3))
            self.assertEqual(len(seen), 4)
            self.assertEqual(seen, [False] * 4)
            self.assertNotIn("INCONCLUSIVE", {m["verdict"] for m in rep["mutants"]})

    def test_reported_diffs_come_from_the_snapshot(self):
        with TempDir() as d:
            plugin = d / "demo"
            shutil.copytree(DEMO, plugin)

            def score(workdir: Path) -> dict:
                for f in plugin.rglob("*.md"):  # the owner rewrites the live files mid-run
                    f.write_text("LIVE\n")
                return demo_scores(workdir)

            rep = mutate(ClaudePluginEvalAdapter(FakeRunner(score)), plugin, d / "out", MutateOptions(max_mutants=3))
            diffs = [m["diff"] for m in rep["mutants"]]
            self.assertTrue(diffs and all(diffs))
            self.assertFalse(any("LIVE" in x for x in diffs))

    def test_untrusted_baseline_makes_every_mutant_inconclusive(self):
        with TempDir() as d:
            runner = FakeRunner(lambda w: result_doc({"tests-only-diff": 1.0}, partial=True))
            rep = mutate(ClaudePluginEvalAdapter(runner), DEMO, d, MutateOptions(max_mutants=3))
            self.assertEqual({m["verdict"] for m in rep["mutants"]}, {"INCONCLUSIVE"})
            self.assertEqual(len(runner.calls), 1)  # mutants are not run on a bad baseline

    def test_relative_out_dir_still_finds_the_result(self):
        # The default --out is relative (.litmus/<stamp>) and the runner's cwd is the run dir.
        with TempDir() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                rep = mutate(ClaudePluginEvalAdapter(FakeRunner(demo_scores)), DEMO, Path("rel"),
                             MutateOptions(max_mutants=1))
            finally:
                os.chdir(cwd)
            self.assertTrue(rep["baseline"]["ok"], rep["baseline"]["error"])

    def test_budget_stops_launching_mutants(self):
        with TempDir() as d:
            runner = FakeRunner(lambda w: result_doc({"tests-only-diff": 1.0}, cost=1.0))
            rep = mutate(ClaudePluginEvalAdapter(runner), DEMO, d, MutateOptions(max_mutants=5, budget_usd=2.5))
            self.assertEqual(rep["score"]["not_run"], 4)
            self.assertEqual(rep["score"]["total_run"], 1)

    def test_stale_manifest_mutant_is_inconclusive(self):
        with TempDir() as d:
            plugin = d / "demo"
            shutil.copytree(DEMO, plugin)
            code, _, _ = cli("mutate", str(plugin), "--dry-run", "--out", str(d / "dry"), "--max-mutants", "2",
                             "--allow-vacuous")
            self.assertEqual(code, 0)
            skill = plugin / "skills/changelog/SKILL.md"
            skill.write_text(skill.read_text() + "\n- New rule.\n")
            runner = FakeRunner(demo_scores)
            rep = mutate(ClaudePluginEvalAdapter(runner), plugin, d / "o",
                         MutateOptions(manifest=d / "dry" / "mutants.json"))
            self.assertEqual({m["verdict"] for m in rep["mutants"]}, {"INCONCLUSIVE"})
            self.assertTrue(all("stale" in m["reason"] for m in rep["mutants"]))

    def test_mutant_under_a_symlinked_directory_is_inconclusive_and_the_run_continues(self):
        with TempDir() as d:
            plugin = d / "demo"
            shutil.copytree(DEMO, plugin)
            outside = d / "outside"
            outside.mkdir()
            (outside / "x.md").write_text("original\n")
            os.symlink(outside, plugin / "shared")
            skill = "skills/changelog/SKILL.md"
            orig = (plugin / skill).read_text()
            bad = Mutant("bad", "op", "shared/x.md", 0, "", sha256("original\n"), "mutated\n")
            good = Mutant("good", "op", skill, 0, "", sha256(orig), orig.replace("release notes", "notes"))
            write_manifest(d / "m.json", plugin, [bad, good])
            runner = FakeRunner(demo_scores)
            rep = mutate(ClaudePluginEvalAdapter(runner), plugin, d / "o", MutateOptions(manifest=d / "m.json"))
            verdicts = {m["id"]: (m["verdict"], m["reason"]) for m in rep["mutants"]}
            self.assertEqual(verdicts["bad"][0], "INCONCLUSIVE")
            self.assertIn("unsafe mutant", verdicts["bad"][1])
            self.assertEqual(verdicts["good"][0], "KILLED")
            self.assertEqual((outside / "x.md").read_text(), "original\n")


class TestCli(unittest.TestCase):
    def test_demo_replay_matches_recordings(self):
        with TempDir() as d:
            code, out, _ = cli("mutate", str(DEMO), "--replay-results", str(ROOT / "examples/demo-recordings"),
                               "--out", str(d), "--quiet")
            self.assertEqual(code, 1)  # vacuous grader + null-green case in the demo suite
            rep = json.loads((d / "report.json").read_text())
            self.assertEqual(rep["exit_code"], 1)
            self.assertEqual(rep["score"]["inconclusive"], 0, "recordings are out of date: run examples/record_demo.py")
            self.assertIn("mutation score: 50%", out)
            html = (d / "report.html").read_text()
            self.assertIn("<title>litmus mutation report</title>", html)
            self.assertIn("SURVIVED", html)

    def test_real_run_requires_yes(self):
        code, _, err = cli("mutate", str(DEMO))
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)

    def test_dry_run_exit_codes(self):
        with TempDir() as d:
            code, out, _ = cli("mutate", str(DEMO), "--dry-run", "--out", str(d))
            self.assertEqual(code, 1)
            self.assertIn("dry run:", out)
            code, _, _ = cli("mutate", str(DEMO), "--dry-run", "--out", str(d), "--allow-vacuous")
            self.assertEqual(code, 0)

    def test_unknown_operator_and_bad_suite(self):
        self.assertEqual(cli("mutate", str(DEMO), "--dry-run", "--operators", "nope")[0], 2)
        with TempDir() as d:
            self.assertEqual(cli("vacuity", str(d))[0], 2)

    def test_vacuity_command(self):
        code, out, _ = cli("vacuity", str(DEMO))
        self.assertEqual(code, 1)
        self.assertIn("VACUOUS", out)
        code, out, _ = cli("vacuity", str(DEMO), "--json")
        self.assertEqual(json.loads(out)["counts"]["vacuous"], 1)

    def test_operators_command(self):
        code, out, _ = cli("operators")
        self.assertEqual(code, 0)
        self.assertIn("invert-rule", out)

    def test_baseline_with_no_green_case_exits_2(self):
        with TempDir() as d:
            rec = d / "rec"
            rec.mkdir()
            (rec / "baseline.json").write_text(json.dumps(result_doc({"tests-only-diff": 0.0})))
            code, _, err = cli("mutate", str(DEMO), "--replay-results", str(rec), "--out", str(d / "o"),
                               "--quiet", "--max-mutants", "2")
            self.assertEqual(code, 2)
            self.assertIn("baseline", err)


def two_arm(case: str, graders: list, with_runs: list, without_runs: list, score_without: float) -> dict:
    return {"schemaVersion": 1, "suite": {"threshold": 1, "ablation": "with-without"}, "cases": [{
        "name": case, "graders": graders,
        "aggregates": {"score": 1, "scoreWithout": score_without, "delta": 1 - score_without},
        "arms": {"with": with_runs, "without": without_runs}}]}


class TestAudit(unittest.TestCase):
    def run_of(self, **passed):  # type: ignore[no-untyped-def]
        return {"graders": [{"name": k, "passed": v, "scored": k != "fired"} for k, v in passed.items()]}

    def test_plugin_removal_survivor_and_never_failed(self):
        graders = [{"name": "judge", "type": "llm", "config": {}}, {"name": "fired", "type": "tool_used",
                                                                    "config": {"tool": "Skill"}}]
        doc = two_arm("c", graders, [self.run_of(judge=True, fired=True)] * 3,
                      [self.run_of(judge=True, fired=False)] * 3, 1.0)
        a = audit_result(doc)
        kinds = [f["kind"] for f in a["cases"][0]["findings"]]
        self.assertEqual(kinds, ["PLUGIN_REMOVAL_SURVIVED", "NEVER_FAILED"])
        self.assertEqual(a["cases"][0]["indicators"], ["fired"])
        self.assertEqual(a["counts"]["unexpected_findings"], 2)

    def test_negative_case_is_expected(self):
        graders = [{"name": "nofire", "type": "tool_used", "config": {"tool": "Skill", "min": 0, "max": 0}},
                   {"name": "answer", "type": "regex", "config": {"pattern": "def"}}]
        doc = two_arm("c", graders, [self.run_of(nofire=True, answer=True)],
                      [self.run_of(nofire=True, answer=False)], 1.0)
        a = audit_result(doc)
        self.assertTrue(a["cases"][0]["negative"])
        self.assertEqual(a["counts"]["plugin_removal_survived"], 0)

    def test_discriminating_case_has_no_findings(self):
        doc = two_arm("c", [{"name": "j", "type": "llm"}], [self.run_of(j=True)], [self.run_of(j=False)], 0.0)
        self.assertEqual(audit_result(doc)["counts"]["unexpected_findings"], 0)

    def test_cli_audit(self):
        with TempDir() as d:
            p = d / "r.json"
            p.write_text(json.dumps(two_arm("c", [], [self.run_of(j=True)], [self.run_of(j=True)], 1.0)))
            code, out, _ = cli("audit", str(p))
            self.assertEqual(code, 1)
            self.assertIn("PLUGIN_REMOVAL_SURVIVED", out)
            (d / "bad.json").write_text("{}")
            self.assertEqual(cli("audit", str(d / "bad.json"))[0], 2)


if __name__ == "__main__":
    unittest.main()
