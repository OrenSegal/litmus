"""Load suites and cases from disk, and resolve each case's AgentRun samples.

Suite layout (dir-based):

    suite/
      suite.json            # optional: { "name", "target", "defaults": {...} }
      cases/*.json|*.yaml    # one Case each
      runs/<case-id>/*.json  # AgentRun samples for that case (transcript adapter)
      runs/<case-id>.json    # ...or a single sample
      *.schema.json          # referenced by `schema: { ref: ... }`

Cases are authored in JSON (always) or YAML (if pyyaml is installed). The
engine never needs YAML — it's author-side sugar only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import AgentRun, Case


def _load_doc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # optional dependency
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                f"{path.name} is YAML but pyyaml isn't installed. "
                "Install `litmus-ci[yaml]`, or author the case in JSON."
            ) from exc
        return yaml.safe_load(text)
    return json.loads(text)


def load_case(path: Path, defaults: Dict[str, Any]) -> Case:
    doc = _load_doc(path)
    target = {**defaults.get("target", {}), **doc.get("target", {})}
    return Case(
        id=str(doc.get("id") or doc.get("case") or path.stem),
        asserts=doc.get("assert", doc.get("asserts", [])),
        target=target,
        input=doc.get("input"),
        samples=int(doc.get("samples", defaults.get("samples", 1))),
        runs=list(doc.get("runs", [])),
        tags=list(doc.get("tags", [])),
    )


def load_suite(suite_dir: Path) -> Tuple[str, Dict[str, Any], List[Case]]:
    suite_dir = Path(suite_dir)
    if not suite_dir.is_dir():
        raise NotADirectoryError(f"suite path is not a directory: {suite_dir}")
    meta: Dict[str, Any] = {}
    meta_path = suite_dir / "suite.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    defaults = meta.get("defaults", {})
    if "target" in meta:
        defaults.setdefault("target", meta["target"])
    case_files = sorted(
        p for p in (suite_dir / "cases").glob("*") if p.suffix in (".json", ".yaml", ".yml")
    ) if (suite_dir / "cases").is_dir() else []
    cases = [load_case(p, defaults) for p in case_files]
    name = meta.get("name", suite_dir.name)
    return name, meta.get("target", {}), cases


def load_runs(case: Case, suite_dir: Path) -> List[AgentRun]:
    """Resolve a case's AgentRun samples (transcript adapter).

    Precedence: explicit `runs:` paths -> runs/<id>/*.json -> runs/<id>.json.
    """
    paths: List[Path] = []
    if case.runs:
        paths = [suite_dir / r for r in case.runs]
    else:
        dir_ = suite_dir / "runs" / case.id
        single = suite_dir / "runs" / f"{case.id}.json"
        if dir_.is_dir():
            paths = sorted(dir_.glob("*.json"))
        elif single.exists():
            paths = [single]
    if not paths:
        raise FileNotFoundError(
            f"case {case.id!r}: no AgentRun samples found "
            f"(set `runs:` or add runs/{case.id}/*.json)"
        )
    return [AgentRun.load(p) for p in paths]
