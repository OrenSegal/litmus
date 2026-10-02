"""Load suites and cases from disk, and resolve each case's AgentRun samples.

Suite layout (dir-based):

    suite/
      suite.json            # optional: { "name", "target", "defaults": {...} }
      cases/*.json|*.yaml    # one Case each
      runs/<case-id>/*.json  # AgentRun samples for that case
      runs/<case-id>.json    # ...or a single sample
      *.schema.json          # referenced by `schema: { ref: ... }`

Cases are authored in JSON (always) or YAML (if pyyaml is installed). The
engine never needs YAML — it's author-side sugar only.

Every path a suite names (`runs:`, `schema.ref`, judge `anchors[].output`, and
the `runs/<case-id>` convention) must stay inside the suite directory after
symlinks are resolved; see `suite_path`. A crafted case can't make litmus read,
or send to a judge, a file outside its suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import AgentRun, Case


class SuiteError(ValueError):
    """A suite, case or run file is malformed, or names a path outside the
    suite. The CLI reports it and exits 2, never as a red or green result."""


def suite_path(base_dir: Path, relative: Any) -> Path:
    """Resolve `relative` against `base_dir` and refuse anything outside it.

    Absolute paths, `..` segments and symlinks are all followed first, so the
    check is on where the file really is.
    """
    if not isinstance(relative, str) or not relative:
        raise SuiteError(f"expected a non-empty relative path, got {relative!r}")
    root = Path(base_dir).resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise SuiteError(f"path {relative!r} resolves outside the suite directory ({root})")
    return target


def _load_doc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # optional dependency
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SuiteError(
                f"{path.name} is YAML but pyyaml isn't installed. "
                "Install `litmus-ci[yaml]`, or author the case in JSON."
            ) from exc
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SuiteError(f"{path}: not valid YAML ({exc})") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SuiteError(f"{path}: not valid JSON ({exc.msg}, line {exc.lineno})") from exc


def _int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SuiteError(f"{where}: expected an integer, got {value!r}")
    try:
        return int(value)
    except ValueError as exc:
        raise SuiteError(f"{where}: expected an integer, got {value!r}") from exc


def load_case(path: Path, defaults: Dict[str, Any]) -> Case:
    doc = _load_doc(path)
    if not isinstance(doc, dict):
        raise SuiteError(f"{path}: a case must be a JSON object, got {type(doc).__name__}")
    asserts = doc.get("assert", doc.get("asserts", []))
    if not isinstance(asserts, list):
        raise SuiteError(f"{path}: `assert` must be a list")
    target = doc.get("target", {})
    if not isinstance(target, dict):
        raise SuiteError(f"{path}: `target` must be an object")
    runs = doc.get("runs", [])
    if not isinstance(runs, list):
        raise SuiteError(f"{path}: `runs` must be a list of paths")
    samples = _int(doc.get("samples", defaults.get("samples", 1)), f"{path}: samples")
    if samples < 1:
        raise SuiteError(f"{path}: samples must be at least 1")
    return Case(
        id=str(doc.get("id") or doc.get("case") or path.stem),
        asserts=asserts,
        target={**defaults.get("target", {}), **target},
        input=doc.get("input"),
        samples=samples,
        runs=list(runs),
        tags=list(doc.get("tags", [])),
    )


def load_suite(suite_dir: Path) -> Tuple[str, Dict[str, Any], List[Case]]:
    suite_dir = Path(suite_dir)
    if not suite_dir.is_dir():
        raise SuiteError(f"suite path is not a directory: {suite_dir}")
    meta: Dict[str, Any] = {}
    meta_path = suite_dir / "suite.json"
    if meta_path.exists():
        meta = _load_doc(meta_path)
        if not isinstance(meta, dict):
            raise SuiteError(f"{meta_path}: must be a JSON object")
    defaults = meta.get("defaults", {})
    if not isinstance(defaults, dict):
        raise SuiteError(f"{meta_path}: `defaults` must be an object")
    if "target" in meta:
        if not isinstance(meta["target"], dict):
            raise SuiteError(f"{meta_path}: `target` must be an object")
        defaults.setdefault("target", meta["target"])
    case_files = sorted(
        p for p in (suite_dir / "cases").glob("*") if p.suffix in (".json", ".yaml", ".yml")
    ) if (suite_dir / "cases").is_dir() else []
    cases = [load_case(p, defaults) for p in case_files]
    seen: Dict[str, Path] = {}
    for case, path in zip(cases, case_files):
        if case.id in seen:
            raise SuiteError(f"duplicate case id {case.id!r} in {seen[case.id].name} and {path.name}")
        seen[case.id] = path
    name = str(meta.get("name", suite_dir.name))
    return name, meta.get("target", {}), cases


def load_runs(case: Case, suite_dir: Path) -> List[AgentRun]:
    """Resolve a case's AgentRun samples from the suite directory.

    Precedence: explicit `runs:` paths -> runs/<id>/*.json -> runs/<id>.json.
    Raises FileNotFoundError when there are none and SuiteError when a path
    leaves the suite or a run file is not a valid AgentRun.
    """
    paths: List[Path] = []
    if case.runs:
        paths = [suite_path(suite_dir, r) for r in case.runs]
    else:
        dir_ = suite_path(suite_dir, f"runs/{case.id}")
        single = suite_path(suite_dir, f"runs/{case.id}.json")
        if dir_.is_dir():
            paths = sorted(p for p in dir_.glob("*.json"))
            for p in paths:  # a symlinked sample must not escape either
                suite_path(suite_dir, str(p.relative_to(Path(suite_dir).resolve())))
        elif single.exists():
            paths = [single]
    if not paths:
        raise FileNotFoundError(
            f"case {case.id!r}: no AgentRun samples found "
            f"(set `runs:` or add runs/{case.id}/*.json)"
        )
    runs: List[AgentRun] = []
    for p in paths:
        doc = _load_doc(p)
        if not isinstance(doc, dict):
            raise SuiteError(f"{p}: an AgentRun must be a JSON object")
        try:
            runs.append(AgentRun.from_obj(doc))
        except (TypeError, ValueError, AttributeError) as exc:
            raise SuiteError(f"{p}: not a valid AgentRun ({exc})") from exc
    return runs


def runs_or_error(case: Case, suite_dir: Path) -> Tuple[List[AgentRun], str]:
    """`load_runs`, but a case whose runs cannot be used comes back as
    ([], reason) instead of raising, so one bad case never stops a suite."""
    try:
        return load_runs(case, suite_dir), ""
    except (FileNotFoundError, SuiteError) as exc:
        return [], str(exc)
