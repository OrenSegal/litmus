"""Adapter for Shelfie's substitution prompt eval (a prompt the app sends to a
model, graded by Shelfie's own runner; no Claude Code plugin involved).

Suite layout, owned by the Shelfie repo:

- subject: `config/ai/prompts/substitution.json`, the prompt SSOT the app and
  the eval both render. Its `template` is a JSON string array, so line
  operators on the raw file mostly hit `_doc` and `golden`. Pass a recorded
  manifest (`--mutants`) that mutates the template instead.
- cases: one per fixture in `tests/eval/golden_sets/substitution.json`, train
  split only. The test split is held out from tuning loops in Shelfie's eval
  rules, and a mutation run reads every score it produces.
- runner: `scripts/ci/run-deterministic-ai-evals.py --live`, which calls the
  deployed ai-gateway (so it needs SUPABASE_URL and SUPABASE_ANON_KEY) and
  grades each answer with a deterministic fuzzy match against the fixture's
  `acceptable_subs` and `unacceptable` lists. Per-case score is the fixture's
  mean `fixture_score`; Shelfie's per-fixture bar is 0.8, so pass
  `--threshold 0.8`.

The runner's cost is a config-pricing estimate (`cost.estimated_cost_usd`),
not billing. litmus's `--runs` maps to the runner's `--samples`.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import Case, CaseRun, Grader, Suite, SuiteRun
from .base import CommandRunner, subprocess_runner

__all__ = ["ShelfieSubstitutionAdapter", "parse_shelfie_result"]

GOLDEN = Path("tests/eval/golden_sets/substitution.json")
PROMPT = Path("config/ai/prompts/substitution.json")
RUNNER = Path("scripts/ci/run-deterministic-ai-evals.py")
RESULTS = "tests/eval/results"
SPLIT = "train"


class ShelfieSubstitutionAdapter:
    name = "shelfie-substitution"
    # One case run is one gateway call. Shelfie's own config-pricing estimate
    # for its reasoning-role model was $0.0009 per call on 2026-10-09
    # (`run-deterministic-ai-evals.py --estimate-cost`). Used only before a
    # baseline exists; after it, litmus uses the baseline's reported cost.
    case_run_cost_usd = 0.001

    def __init__(self, runner: Optional[CommandRunner] = None, *, runs: int = 1, model: Optional[str] = None,
                 case_glob: Optional[str] = None, timeout: Optional[float] = None,
                 python_bin: str = sys.executable, files_glob: Optional[str] = None, **_unused: Any) -> None:
        # **_unused: the CLI passes every adapter the claude-plugin-eval options
        # (judge model, tools, scaffold...). None of them apply to this runner.
        self.runner = runner or subprocess_runner
        self.runs = runs
        self.model = model
        self.case_glob = case_glob
        self.timeout = timeout
        self.python_bin = python_bin
        self.files_glob = files_glob

    def load_suite(self, target: Path) -> Suite:
        root = target.resolve()
        golden = root / GOLDEN
        if not golden.is_file():
            raise ValueError(f"{golden}: not found (expected a Shelfie checkout)")
        if not (root / RUNNER).is_file():
            raise ValueError(f"{root / RUNNER}: not found")
        try:
            doc = json.loads(golden.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{golden}: {exc}") from exc
        cases = []
        for f in doc.get("fixtures") or []:
            if not isinstance(f, dict) or not f.get("id") or f.get("split", "train") != SPLIT:
                continue
            g = Grader(name="acceptable-substitute", type="shelfie-fuzzy-match", source=golden,
                       config={"acceptable": f.get("acceptable_subs") or [], "unacceptable": f.get("unacceptable") or []})
            cases.append(Case(name=str(f["id"]), directory=golden.parent, prompt=str(f.get("original") or ""),
                              graders=[g], meta={"split": SPLIT}))
        if self.case_glob:
            cases = [c for c in cases if fnmatch.fnmatch(c.name, self.case_glob)]
        if not cases:
            raise ValueError(f"{golden}: no {SPLIT}-split fixtures")
        return Suite(root=root, eval_dir=golden.parent, cases=cases, adapter=self.name)

    def subject_files(self, suite: Suite) -> List[Path]:
        p = suite.root / PROMPT
        if not p.is_file():
            return []
        if self.files_glob and not fnmatch.fnmatch(PROMPT.as_posix(), self.files_glob):
            return []
        return [p]

    def results_rel(self, suite: Suite) -> Optional[str]:
        return RESULTS

    def command(self, workdir: Path, out_json: Path) -> List[str]:
        argv = [self.python_bin, str(workdir / RUNNER), "--repo", str(workdir), "--output", str(out_json),
                "--live", "--samples", str(self.runs), "--split", SPLIT]
        if self.model:
            argv += ["--model", self.model]
        return argv

    def describe_command(self, target: Path) -> str:
        return " ".join(self.command(target, Path("<out>/result.json")))

    def run(self, workdir: Path, suite: Suite, out_dir: Path, label: str) -> SuiteRun:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir.resolve() / "result.json"
        res = self.runner(self.command(workdir, out_json), out_dir, self.timeout, label, None)
        (out_dir / "stderr.txt").write_text(res.stderr or "", encoding="utf-8")
        # Exit 1 is normal: `--live` also runs the scan-recognition gate, which
        # fails while its fixture images are absent. The JSON is written first.
        if not out_json.is_file():
            why = (res.stderr or "").strip().splitlines()[-1:] or [f"exit {res.returncode}"]
            return SuiteRun(ok=False, error=f"no result written (exit {res.returncode}): {why[0]}")
        try:
            doc = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return SuiteRun(ok=False, error=f"result is not JSON: {exc}")
        return parse_shelfie_result(doc, res.returncode)


def parse_shelfie_result(doc: Dict[str, Any], returncode: int = 0) -> SuiteRun:
    """Turn the runner's result JSON into a SuiteRun, from `metrics.substitution_live`."""
    live = (doc.get("metrics") or {}).get("substitution_live")
    if not isinstance(live, dict):
        return SuiteRun(ok=False, error="no substitution_live metrics (did the run use --live?)", raw=doc)
    cost = (live.get("cost") or {}).get("estimated_cost_usd")
    if returncode not in (0, 1):
        return SuiteRun(ok=False, error=f"runner exited {returncode}", cost_usd=cost, raw=doc)
    details = live.get("details") or []
    if details and all(d.get("error") and not d.get("samples_scored") for d in details):
        return SuiteRun(ok=False, error=f"every fixture errored: {details[0].get('error')}", cost_usd=cost, raw=doc)
    cases: Dict[str, CaseRun] = {}
    for d in details:
        scored = d.get("samples_scored") or 0
        err = None
        if d.get("error"):
            # A gateway error in any sample: the mean covers fewer samples than asked.
            err = f"gateway error in {d.get('errors', 1)} sample(s): {d['error']}"
        elif not scored:
            err = "no graded samples"
        score = float(d["fixture_score"]) if scored and d.get("fixture_score") is not None else None
        cases[str(d.get("id"))] = CaseRun(score=score, error=err)
    return SuiteRun(ok=True, cases=cases, cost_usd=cost, raw=doc)
