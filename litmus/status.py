"""`litmus status` — what a green on this suite does and does not prove.

A green means the assertions held over the AgentRun files on disk. Whether
those files are what a real agent did is a separate question, and this command
answers it from the files themselves:

- a run stamped `meta.captured_by == "litmus capture"` was written by
  `litmus capture` from a real Claude CLI session (the stamp is self-declared:
  anyone can type it into a JSON file, so treat it as provenance, not proof);
- any other run is a fixture: hand-written or produced by some other tool.

It also counts `judge` assertions (never graded without `--judge`), declared
`samples` that have no run, and whether the baseline was blessed with a judge.
Pure and offline: it reads files and never calls a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters.claude_code import CAPTURED_BY
from .case import SuiteError, load_runs, load_suite


@dataclass
class CaseStatus:
    id: str
    captured: int = 0
    fixtures: int = 0
    declared_samples: int = 1
    judge_assertions: int = 0
    models: List[str] = field(default_factory=list)
    error: str = ""


@dataclass
class SuiteStatus:
    name: str
    cases: List[CaseStatus] = field(default_factory=list)
    baseline: Optional[Dict[str, Any]] = None  # {"version", "judge"} if stamped, {} if not
    baseline_path: Optional[str] = None

    @property
    def captured(self) -> int:
        return sum(c.captured for c in self.cases)

    @property
    def fixtures(self) -> int:
        return sum(c.fixtures for c in self.cases)

    @property
    def judge_assertions(self) -> int:
        return sum(c.judge_assertions for c in self.cases)


def suite_status(suite_dir: Path) -> SuiteStatus:
    suite_dir = Path(suite_dir)
    name, _, cases = load_suite(suite_dir)
    result = SuiteStatus(name=name)
    for case in cases:
        cs = CaseStatus(
            id=case.id,
            declared_samples=case.samples,
            judge_assertions=sum(1 for a in case.asserts if isinstance(a, dict) and "judge" in a),
        )
        try:
            runs = load_runs(case, suite_dir)
        except (FileNotFoundError, SuiteError) as exc:
            cs.error = str(exc)
            result.cases.append(cs)
            continue
        for run in runs:
            if run.meta.get("captured_by") == CAPTURED_BY:
                cs.captured += 1
            else:
                cs.fixtures += 1
            model = str(run.meta.get("model", "")) or "?"
            if model not in cs.models:
                cs.models.append(model)
        result.cases.append(cs)
    baseline_path = suite_dir / "baseline.json"
    if baseline_path.is_file():
        result.baseline_path = str(baseline_path)
        try:
            doc = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
        meta = doc.get("litmus") if isinstance(doc, dict) else None
        result.baseline = dict(meta) if isinstance(meta, dict) else {}
    return result


def render_status(st: SuiteStatus) -> str:
    total = st.captured + st.fixtures
    lines = [f"litmus status · {st.name}", ""]
    width = max([len(c.id) for c in st.cases] + [4])
    for c in st.cases:
        if c.error:
            lines.append(f"  {c.id:<{width}}  no usable runs: {c.error}")
            continue
        notes = []
        n = c.captured + c.fixtures
        if n < c.declared_samples:
            notes.append(f"declares samples: {c.declared_samples}, has {n}")
        if c.judge_assertions:
            notes.append(f"{c.judge_assertions} judge assertion(s)")
        lines.append(
            f"  {c.id:<{width}}  captured {c.captured}  fixture {c.fixtures}  "
            f"models {','.join(c.models)}" + (f"  ({'; '.join(notes)})" if notes else ""))
    lines += ["", "What a green on this suite proves:"]
    lines.append(f"  - the assertions held over these {total} run file(s); grading is deterministic.")
    if st.fixtures and not st.captured:
        lines.append(f"  - all {st.fixtures} run(s) are fixtures (no `litmus capture` stamp). A green shows the")
        lines.append("    checks work on these files, not that a live agent behaves this way.")
    elif st.fixtures:
        lines.append(f"  - {st.captured} run(s) carry the `litmus capture` stamp; {st.fixtures} are fixtures.")
        lines.append("    Only the stamped runs speak for a live agent (the stamp is self-declared).")
    elif st.captured:
        lines.append(f"  - all {st.captured} run(s) carry the `litmus capture` stamp (self-declared provenance).")
    if st.judge_assertions:
        lines.append(f"  - {st.judge_assertions} judge assertion(s) are INCONCLUSIVE unless run with --judge;")
        lines.append("    with --judge, a PASS also depends on the anchors, not a measured human agreement.")
    if st.baseline is None:
        lines.append("  - no baseline.json: `litmus gate` has nothing to ratchet against yet.")
    elif not st.baseline:
        lines.append("  - baseline.json predates 0.2.0 (no litmus stamp); re-bless to record the judge used.")
    else:
        judge = st.baseline.get("judge")
        with_judge = f"with judge {judge}" if judge else "with no judge (judge assertions were INCONCLUSIVE)"
        lines.append(f"  - baseline blessed by litmus {st.baseline.get('version')} {with_judge}.")
    return "\n".join(lines)
