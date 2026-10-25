from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Callable, Dict, List

from litmus.adapters.base import CommandResult
from litmus.adapters.shelfie_substitution import ShelfieSubstitutionAdapter, parse_shelfie_result
from litmus.engine import MutateOptions, mutate
from litmus.mutants import Mutant, sha256, write_manifest

from .helpers import TempDir

PROMPT = {"template": ['Suggest one cooking substitute for "{{itemName}}".', "Respond with JSON only:"]}


def make_shelfie(root: Path) -> Path:
    (root / "tests/eval/golden_sets").mkdir(parents=True)
    (root / "config/ai/prompts").mkdir(parents=True)
    (root / "scripts/ci").mkdir(parents=True)
    fixtures = [
        {"id": "sub_a", "original": "buttermilk", "acceptable_subs": ["milk + lemon"], "unacceptable": ["milk"]},
        {"id": "sub_b", "original": "egg", "acceptable_subs": ["flax egg"], "unacceptable": ["water"],
         "split": "train"},
        {"id": "sub_held", "original": "sesame", "acceptable_subs": ["sunflower"], "unacceptable": ["tahini"],
         "split": "test"},
    ]
    (root / "tests/eval/golden_sets/substitution.json").write_text(json.dumps({"fixtures": fixtures}))
    (root / "config/ai/prompts/substitution.json").write_text(json.dumps(PROMPT, indent=2) + "\n")
    (root / "scripts/ci/run-deterministic-ai-evals.py").write_text("# stand-in; tests never run it\n")
    return root


def live_doc(details: List[dict], cost: float = 0.01) -> dict:
    return {"metrics": {"substitution": {"acceptable_rate": 1.0},
                        "substitution_live": {"details": details, "cost": {"estimated_cost_usd": cost}}}}


def detail(fid: str, score: float, **extra: object) -> dict:
    return {"id": fid, "fixture_score": score, "samples_scored": 1, **extra}


class FakeShelfieRunner:
    """Stands in for the Shelfie runner: reads the prompt in the copy it is
    pointed at (`--repo`) and writes the result JSON to `--output`."""

    def __init__(self, doc_fn: Callable[[Path], dict], returncode: int = 1) -> None:
        self.doc_fn = doc_fn
        self.returncode = returncode
        self.calls: List[List[str]] = []

    def __call__(self, argv, cwd, timeout, label, env=None):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        workdir = Path(argv[argv.index("--repo") + 1])
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps(self.doc_fn(workdir)))
        return CommandResult(self.returncode, "", "")


def prompt_scores(workdir: Path) -> dict:
    """Green on both train fixtures while the prompt names the item."""
    text = (workdir / "config/ai/prompts/substitution.json").read_text()
    ok = 1.0 if "{{itemName}}" in text else 0.0
    return live_doc([detail("sub_a", ok), detail("sub_b", 1.0 if ok else 0.0)])


class TestShelfieSuite(unittest.TestCase):
    def test_train_split_cases_and_prompt_subject(self):
        with TempDir() as d:
            root = make_shelfie(d / "shelfie")
            a = ShelfieSubstitutionAdapter()
            s = a.load_suite(root)
            self.assertEqual([c.name for c in s.cases], ["sub_a", "sub_b"])
            self.assertEqual(s.cases[0].graders[0].type, "shelfie-fuzzy-match")
            self.assertEqual([p.relative_to(s.root).as_posix() for p in a.subject_files(s)],
                             ["config/ai/prompts/substitution.json"])
            self.assertEqual(a.results_rel(s), "tests/eval/results")

    def test_not_a_shelfie_checkout_is_a_readable_error(self):
        with TempDir() as d:
            with self.assertRaisesRegex(ValueError, "Shelfie checkout"):
                ShelfieSubstitutionAdapter().load_suite(d)

    def test_command_runs_live_train_split_with_samples_and_model(self):
        a = ShelfieSubstitutionAdapter(runs=3, model="gemini-x", python_bin="python3")
        argv = a.command(Path("/w"), Path("/o/result.json"))
        self.assertEqual(argv[:2], ["python3", "/w/scripts/ci/run-deterministic-ai-evals.py"])
        for flag, value in (("--repo", "/w"), ("--samples", "3"), ("--split", "train"), ("--model", "gemini-x")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--live", argv)

    def test_cli_options_for_other_runners_are_accepted(self):
        ShelfieSubstitutionAdapter(None, eval_dir=None, threshold=0.8, judge_model=None, allow_tools=None,
                                   scaffold=False, max_cost_usd=None)


class TestShelfieResult(unittest.TestCase):
    def test_scores_and_cost(self):
        run = parse_shelfie_result(live_doc([detail("sub_a", 1.0), detail("sub_b", 0.0)], cost=0.02), 1)
        self.assertTrue(run.ok)
        self.assertEqual({k: v.score for k, v in run.cases.items()}, {"sub_a": 1.0, "sub_b": 0.0})
        self.assertEqual(run.cost_usd, 0.02)

    def test_offline_result_is_untrusted(self):
        run = parse_shelfie_result({"metrics": {"substitution": {"acceptable_rate": 1.0}}})
        self.assertFalse(run.ok)
        self.assertIn("--live", run.error or "")

    def test_every_fixture_errored_is_untrusted(self):
        doc = live_doc([{"id": "sub_a", "fixture_score": 0.0, "samples_scored": 0, "error": "HTTP 429"}])
        self.assertFalse(parse_shelfie_result(doc).ok)

    def test_a_gateway_error_marks_only_that_case(self):
        doc = live_doc([detail("sub_a", 1.0), detail("sub_b", 1.0, error="timed out", errors=1)])
        run = parse_shelfie_result(doc)
        self.assertTrue(run.ok)
        self.assertIsNone(run.cases["sub_a"].error)
        self.assertIn("timed out", run.cases["sub_b"].error or "")

    def test_crash_exit_is_untrusted(self):
        self.assertFalse(parse_shelfie_result(live_doc([detail("sub_a", 1.0)]), 2).ok)

    def test_missing_result_file_is_untrusted(self):
        with TempDir() as d:
            root = make_shelfie(d / "shelfie")
            a = ShelfieSubstitutionAdapter(lambda argv, cwd, timeout, label, env=None: CommandResult(1, "", "no creds"))
            run = a.run(root, a.load_suite(root), d / "out", "baseline")
            self.assertFalse(run.ok)
            self.assertIn("no creds", run.error or "")


class TestShelfieMutate(unittest.TestCase):
    def test_manifest_mutant_of_the_template_is_killed_and_one_that_misses_survives(self):
        with TempDir() as d:
            root = make_shelfie(d / "shelfie")
            rel = "config/ai/prompts/substitution.json"
            original = (root / rel).read_text()

            def patched(template: List[str]) -> str:
                return json.dumps({"template": template}, indent=2) + "\n"

            mutants = [
                Mutant("manual:drop-item:0", "manual:drop-item", rel, 0, "drop the item name", sha256(original),
                       patched(["Suggest one cooking substitute.", PROMPT["template"][1]]), {"kind": "hand-written"}),
                Mutant("manual:drop-json:0", "manual:drop-json", rel, 0, "drop the JSON line", sha256(original),
                       patched(PROMPT["template"][:1]), {"kind": "hand-written"}),
            ]
            write_manifest(d / "m.json", root, mutants)
            runner = FakeShelfieRunner(prompt_scores)
            rep = mutate(ShelfieSubstitutionAdapter(runner), root, d / "out", MutateOptions(manifest=d / "m.json"))
            verdicts: Dict[str, str] = {m["id"]: m["verdict"] for m in rep["mutants"]}
            self.assertEqual(verdicts, {"manual:drop-item:0": "KILLED", "manual:drop-json:0": "SURVIVED"})
            self.assertEqual(rep["baseline"]["green_cases"], ["sub_a", "sub_b"])
            self.assertEqual(len(runner.calls), 3)
            # Every run pointed the runner at a copy, never at the original checkout.
            self.assertTrue(all(c[c.index("--repo") + 1] != str(root) for c in runner.calls))

    def test_dry_run_estimate_uses_the_adapter_cost_per_case_run(self):
        with TempDir() as d:
            root = make_shelfie(d / "shelfie")
            rep = mutate(ShelfieSubstitutionAdapter(), root, d / "out", MutateOptions(dry_run=True))
            # 2 train cases x (baseline + each mutant) x $0.001, not the $0.10 agent default.
            self.assertEqual(rep["estimate_usd"], round(2 * (1 + len(rep["mutants"])) * 0.001, 2))
            self.assertLess(rep["estimate_usd"], 0.2)


if __name__ == "__main__":
    unittest.main()
