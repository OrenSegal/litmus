"""`litmus matrix` — the answer to "every model upgrade re-rolls the dice".

Group a suite's captured AgentRun samples by their `meta.model`, evaluate each
case independently per model, and render a case × model status grid. Pure and
offline: it grades whatever runs are on disk (each tagged with its model),
never calling a model itself.

Run layout for a matrix: tag each AgentRun with meta.model, e.g.
    runs/<case-id>/sonnet-5.json      -> {"meta":{"model":"sonnet-5"}, ...}
    runs/<case-id>/opus-4.8.json      -> {"meta":{"model":"opus-4.8"}, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .assertions import EvalContext
from .case import load_runs, load_suite
from .models import AgentRun, CaseResult, Status
from .report import _tag  # reuse the coloured status glyph


@dataclass
class MatrixResult:
    models: List[str] = field(default_factory=list)
    # case_id -> model -> CaseResult
    grid: Dict[str, Dict[str, CaseResult]] = field(default_factory=dict)

    def regressions_vs(self, reference: str) -> List[str]:
        """Cases green on `reference` model but not on some other model."""
        out = []
        for cid, bym in self.grid.items():
            ref = bym.get(reference)
            if ref and ref.status is Status.PASS:
                for m, r in bym.items():
                    if m != reference and r.status is not Status.PASS:
                        out.append(f"{cid}: green on {reference}, {r.status.value} on {m}")
        return out


def _group_by_model(runs: List[AgentRun]) -> Dict[str, List[AgentRun]]:
    groups: Dict[str, List[AgentRun]] = {}
    for r in runs:
        groups.setdefault(str(r.meta.get("model", "default")), []).append(r)
    return groups


def evaluate_matrix(
    suite_dir: Path,
    ctx: Optional[EvalContext] = None,
    models: Optional[List[str]] = None,
) -> MatrixResult:
    suite_dir = Path(suite_dir)
    ctx = ctx or EvalContext(base_dir=suite_dir)
    if ctx.base_dir == Path("."):
        ctx.base_dir = suite_dir
    from .runner import evaluate_case

    _, _, cases = load_suite(suite_dir)
    result = MatrixResult()
    seen: List[str] = []
    for case in cases:
        try:
            runs = load_runs(case, suite_dir)
        except FileNotFoundError:
            continue
        groups = _group_by_model(runs)
        result.grid[case.id] = {}
        for model, group in groups.items():
            if models and model not in models:
                continue
            if model not in seen:
                seen.append(model)
            result.grid[case.id][model] = evaluate_case(case, group, ctx)
    result.models = models or seen
    return result


def render_matrix(result: MatrixResult) -> str:
    if not result.models:
        return "litmus matrix · no model-tagged runs found"
    width = max([len(c) for c in result.grid] + [4])
    header = " " * (width + 2) + "  ".join(f"{m[:10]:<10}" for m in result.models)
    lines = ["litmus matrix", "", header]
    for cid, bym in result.grid.items():
        cells = []
        for m in result.models:
            r = bym.get(m)
            cells.append(f"{_tag(r.status):<10}" if r else f"{'—':<10}")
        lines.append(f"{cid:<{width}}  " + "  ".join(cells))
    return "\n".join(lines)
