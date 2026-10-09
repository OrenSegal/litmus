"""Shared test helpers: a fake `claude plugin eval` runner and suite builders."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from litmus.adapters.base import CommandResult

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo-plugin"


def result_doc(scores: Dict[str, Optional[float]], *, partial: bool = False, errors: Optional[Dict[str, str]] = None,
               cost: float = 0.05) -> dict:
    errors = errors or {}
    return {
        "schemaVersion": 1, "claudeVersion": "test", "costUsd": cost, "partial": partial,
        "partialReason": "interrupted" if partial else None,
        "suite": {"ablation": "none", "threshold": 1},
        "cases": [{"name": n, "aggregates": {"score": s},
                   "arms": {"with": [{"score": s, "error": errors.get(n), "graders": []}]}}
                  for n, s in scores.items()],
    }


class FakeRunner:
    """Stands in for `claude plugin eval`: reads the mutated plugin copy it is
    pointed at and writes a result JSON, using `score_fn(workdir) -> doc`."""

    def __init__(self, score_fn: Callable[[Path], dict], returncode: int = 0) -> None:
        self.score_fn = score_fn
        self.returncode = returncode
        self.calls: List[List[str]] = []
        self.labels: List[str] = []

    def __call__(self, argv, cwd, timeout, label):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        self.labels.append(label)
        workdir = Path(argv[3])
        out = Path(cwd) / argv[argv.index("--json") + 1]  # relative paths resolve against cwd, as in a subprocess
        out.write_text(json.dumps(self.score_fn(workdir)), encoding="utf-8")
        return CommandResult(self.returncode, "", "")


def demo_scores(workdir: Path) -> dict:
    text = (workdir / "skills" / "changelog" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1] if text.startswith("---") else ""
    ok = "release notes" in head and 'Never write a "Features" heading' in text and '"No user-facing changes."' in text
    return result_doc({"tests-only-diff": 1.0 if ok else 0.0, "ends-with-version": 1.0, "no-todo-left": 1.0})


class TempDir:
    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix="litmus-test-"))
        return self.path

    def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
        shutil.rmtree(self.path, ignore_errors=True)


def write_case(root: Path, name: str, prompt: str, graders: Dict[str, str], eval_dir: str = "evals") -> Path:
    d = root / eval_dir / name
    (d / "graders").mkdir(parents=True, exist_ok=True)
    (d / "prompt.md").write_text(f"---\nmax_turns: 3\n---\n\n{prompt}\n", encoding="utf-8")
    for g, body in graders.items():
        (d / "graders" / f"{g}.md").write_text(body, encoding="utf-8")
    return d


def make_plugin(root: Path, skill_body: str = "Do the thing.\n- Never skip step 2.\n") -> Path:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name": "p", "version": "0.0.1"}', encoding="utf-8")
    (root / "skills" / "s").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "s" / "SKILL.md").write_text(
        f"---\nname: s\ndescription: Does the thing.\n---\n\n{skill_body}", encoding="utf-8")
    return root
