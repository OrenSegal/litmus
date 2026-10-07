"""Adapter for `claude plugin eval` (Claude Code's plugin eval runner).

Suite layout, grader types and result fields follow
https://code.claude.com/docs/en/plugin-evals. litmus never reimplements the
runner: each run is one `claude plugin eval` invocation against a copy of the
plugin, and litmus reads the `--json` result it writes.

Every run, the baseline and every mutant, uses the same flags. `--ablation none`
is required: the docs say it changes absolute scores, so a two-arm baseline is
not comparable with one-arm mutant runs, and the no-plugin arm adds nothing a
mutant needs.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..frontmatter import FrontmatterError, parse_yaml, split
from ..models import Case, CaseRun, Grader, Suite, SuiteRun
from .base import CommandRunner, subprocess_runner

__all__ = ["ClaudePluginEvalAdapter", "SuiteError", "parse_result"]

_GRADER_KEYS = {"type", "weight", "arm", "name"}
_INFRA_ERROR = re.compile(r"rate.?limit|usage.?limit|auth|credential|overloaded|\b429\b|\b5\d\d\b|quota", re.I)


class SuiteError(ValueError):
    pass


def _plugin_manifest(root: Path) -> Dict[str, Any]:
    for rel in (".claude-plugin/plugin.json", "plugin.json"):
        p = root / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError as exc:
                raise SuiteError(f"{p}: {exc}") from exc
    return {}


def _grader_from(name: str, meta: Dict[str, Any], body: str, source: Optional[Path]) -> Grader:
    gtype = meta.get("type")
    if not gtype:
        raise SuiteError(f"{source or name}: grader has no type")
    config = {k: v for k, v in meta.items() if k not in _GRADER_KEYS}
    if gtype in ("llm", "baseline") and body.strip() and "criteria" not in config:
        config["criteria"] = body.strip()
    arm = meta.get("arm")
    return Grader(name=name, type=str(gtype), weight=float(meta.get("weight", 1) or 1),
                  arm=str(arm) if arm else None, config=config, body=body.strip(), source=source)


def _load_case(d: Path, eval_dir: Path) -> Case:
    meta: Dict[str, Any] = {}
    prompt = ""
    graders: List[Grader] = []
    cy = d / "case.yaml"
    if cy.is_file():
        try:
            data = parse_yaml(cy.read_text(encoding="utf-8")) or {}
        except FrontmatterError as exc:
            raise SuiteError(f"{cy}: {exc} (install PyYAML: pip install 'litmus-ci[yaml]')") from exc
        if not isinstance(data, dict):
            raise SuiteError(f"{cy}: not a mapping")
        meta.update({k: v for k, v in data.items() if k not in ("graders", "execution")})
        execution = data.get("execution") or {}
        if isinstance(execution, dict):
            meta.update({k: v for k, v in execution.items() if k != "prompt"})
            prompt = str(execution.get("prompt") or "")
        for g in data.get("graders") or []:
            if not isinstance(g, dict) or "name" not in g:
                raise SuiteError(f"{cy}: every grader in case.yaml needs a name")
            graders.append(_grader_from(str(g["name"]), g, str(g.get("criteria") or ""), cy))
    pm = d / "prompt.md"
    if pm.is_file():
        try:
            fm, body = split(pm.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            raise SuiteError(f"{pm}: {exc}") from exc
        meta.update(fm)
        prompt = body.strip()
    gdir = d / "graders"
    if gdir.is_dir():
        for gf in sorted(gdir.glob("*.md")):
            try:
                fm, body = split(gf.read_text(encoding="utf-8"))
            except FrontmatterError as exc:
                raise SuiteError(f"{gf}: {exc}") from exc
            graders.append(_grader_from(gf.stem, fm, body, gf))
    if not graders:
        raise SuiteError(f"{d}: case has no graders")
    name = str(meta.get("name") or d.name)
    return Case(name=name, directory=d, prompt=prompt, graders=graders, meta=meta)


def _find_cases(eval_dir: Path) -> List[Path]:
    found = []
    for p in sorted(eval_dir.rglob("*")):
        rel = p.relative_to(eval_dir).parts
        if not p.is_dir() or rel[:1] == ("results",) or "mocks" in rel:
            continue
        if (p / "prompt.md").is_file() or (p / "case.yaml").is_file():
            found.append(p)
    return found


class ClaudePluginEvalAdapter:
    name = "claude-plugin-eval"

    def __init__(self, runner: Optional[CommandRunner] = None, *, eval_dir: Optional[str] = None,
                 runs: int = 1, threshold: float = 1.0, model: Optional[str] = None,
                 judge_model: Optional[str] = None, allow_tools: Optional[List[str]] = None,
                 scaffold: bool = False, case_glob: Optional[str] = None,
                 max_cost_usd: Optional[float] = None, timeout: Optional[float] = None,
                 claude_bin: str = "claude", files_glob: Optional[str] = None) -> None:
        self.runner = runner or subprocess_runner
        self.eval_dir_name = eval_dir
        self.runs = runs
        self.threshold = threshold
        self.model = model
        self.judge_model = judge_model
        self.allow_tools = allow_tools or []
        self.scaffold = scaffold
        self.case_glob = case_glob
        self.max_cost_usd = max_cost_usd
        self.timeout = timeout
        self.claude_bin = claude_bin
        self.files_glob = files_glob

    # ---- suite -------------------------------------------------------------

    def _eval_rel(self, root: Path) -> str:
        if self.eval_dir_name:
            return self.eval_dir_name
        exp = _plugin_manifest(root).get("experimental") or {}
        rel = exp.get("evals") if isinstance(exp, dict) else None
        if isinstance(rel, str) and rel and not Path(rel).is_absolute() and ".." not in Path(rel).parts:
            return rel
        return "evals"

    def load_suite(self, target: Path) -> Suite:
        root = target.resolve()
        if not root.is_dir():
            raise SuiteError(f"{target}: not a directory")
        eval_dir = root / self._eval_rel(root)
        if not eval_dir.is_dir():
            raise SuiteError(f"{eval_dir}: no eval directory (claude plugin eval looks for evals/ by default)")
        cases = [_load_case(d, eval_dir) for d in _find_cases(eval_dir)]
        if self.case_glob:
            cases = [c for c in cases if fnmatch.fnmatch(c.name, self.case_glob)]
        if not cases:
            raise SuiteError(f"{eval_dir}: no eval cases found")
        return Suite(root=root, eval_dir=eval_dir, cases=cases, adapter=self.name)

    def subject_files(self, suite: Suite) -> List[Path]:
        """Skills first, then agents, then commands: a cap on mutants keeps the skills."""
        root = suite.root
        ev = suite.eval_dir.resolve()
        files: List[Path] = []
        for pattern in ("skills/**/SKILL.md", "agents/**/*.md", "commands/**/*.md"):
            for p in sorted(root.glob(pattern)):
                if p.is_file() and ev not in p.resolve().parents and p not in files:
                    if not self.files_glob or fnmatch.fnmatch(p.relative_to(root).as_posix(), self.files_glob):
                        files.append(p)
        return files

    def results_rel(self, suite: Suite) -> Optional[str]:
        return (suite.eval_dir.relative_to(suite.root) / "results").as_posix()

    # ---- running -----------------------------------------------------------

    def command(self, workdir: Path, out_json: Path) -> List[str]:
        argv = [self.claude_bin, "plugin", "eval", str(workdir),
                "--ablation", "none", "--runs", str(self.runs), "--threshold", str(self.threshold),
                "--trust-plugin", "--no-publish", "--json", str(out_json),
                "--output-dir", str(out_json.parent / "eval-output")]
        if self.eval_dir_name:
            argv += ["--eval-dir", self.eval_dir_name]
        if self.case_glob:
            argv += ["--case", self.case_glob]
        if self.model:
            argv += ["--model", self.model]
        if self.judge_model:
            argv += ["--judge-model", self.judge_model]
        if self.max_cost_usd is not None:
            argv += ["--max-cost-usd", f"{self.max_cost_usd:.2f}"]
        if self.scaffold:
            argv += ["--scaffold"]
        if self.allow_tools:
            argv += ["--allow-tools", *self.allow_tools]
        return argv

    def describe_command(self, target: Path) -> str:
        return " ".join(self.command(target, Path("<out>/result.json")))

    def run(self, workdir: Path, suite: Suite, out_dir: Path, label: str) -> SuiteRun:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / "result.json"
        res = self.runner(self.command(workdir, out_json), out_dir, self.timeout, label)
        (out_dir / "stderr.txt").write_text(res.stderr or "", encoding="utf-8")
        # Exit 1 means "a case scored below --threshold": the expected outcome
        # for a killed mutant. Only a missing or partial result is untrusted.
        if not out_json.is_file():
            why = (res.stderr or "").strip().splitlines()[-1:] or [f"exit {res.returncode}"]
            return SuiteRun(ok=False, error=f"no result written (exit {res.returncode}): {why[0]}")
        try:
            doc = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return SuiteRun(ok=False, error=f"result is not JSON: {exc}")
        return parse_result(doc, res.returncode)


def parse_result(doc: Dict[str, Any], returncode: int = 0) -> SuiteRun:
    """Turn an aggregate-result.json (schemaVersion 1) into a SuiteRun."""
    if doc.get("schemaVersion") != 1:
        return SuiteRun(ok=False, error=f"unsupported schemaVersion {doc.get('schemaVersion')!r}", raw=doc)
    cost = doc.get("costUsd")
    if doc.get("partial"):
        return SuiteRun(ok=False, error=f"partial run: {doc.get('partialReason') or 'unknown reason'}",
                        cost_usd=cost, raw=doc)
    if returncode not in (0, 1):
        return SuiteRun(ok=False, error=f"claude plugin eval exited {returncode}", cost_usd=cost, raw=doc)
    cases: Dict[str, CaseRun] = {}
    for c in doc.get("cases", []):
        runs = (c.get("arms") or {}).get("with") or []
        infra = [r.get("error") for r in runs if r.get("error") and _INFRA_ERROR.search(str(r.get("error")))]
        skipped = any(r.get("skippedPaidGraders") for r in runs)
        score = (c.get("aggregates") or {}).get("score")
        err = None
        if infra:
            err = f"infrastructure error in {len(infra)} run(s): {infra[0]}"
        elif skipped:
            err = "the cost ceiling skipped judge graders in a run"
        elif not runs or score is None:
            err = "no graded runs"
        cases[str(c.get("name"))] = CaseRun(score=None if score is None else float(score), error=err)
    return SuiteRun(ok=True, cases=cases, cost_usd=cost, raw=doc)
