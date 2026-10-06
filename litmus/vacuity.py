"""Find graders that cannot fail, and cases that a run doing nothing would pass.

Two layers, both offline and free:

1. Static proofs. A `regex` grader whose pattern matches the empty string can
   never fail; a `tool_used` grader with `min: 0` and no `max` can never fail.
   These are VACUOUS, full stop.
2. Null probes. Each case is graded against synthetic runs that did no work:
   an empty reply, "Done.", a refusal, and the prompt echoed back, all with no
   tool calls and no files. A grader that passes on one of them is NULL_PASS.
   A case whose scored graders all pass on a probe is NULL_GREEN: an agent that
   did nothing would turn it green. Judge graders (`llm`, `baseline`) are
   UNKNOWN on probes; a case that only a judge can fail is reported as such.

Absence checks (`match: not_contains`, `max: 0`, `exists: false`) are meant to
pass when nothing happens. They are labelled `guard` so a reader can tell a
deliberate guard from an accidental pass; they are fine only when the case
also has a grader that requires the work to be done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .graders import Outcome, ProbeRun, UntranslatableRegex, evaluate, js_regex
from .models import Case, Grader, Suite

__all__ = ["PROBES", "analyze", "scored_graders", "GraderFinding", "CaseFinding"]

PROBES: Dict[str, str] = {
    "silent": "",
    "done": "Done.",
    "refusal": "I can't help with that.",
    "echo": "\x00ECHO",  # replaced by the case prompt
}


def _probe(name: str, case: Case) -> ProbeRun:
    msg = PROBES[name]
    return ProbeRun(prompt=case.prompt, last_message=case.prompt if msg == "\x00ECHO" else msg)


@dataclass
class GraderFinding:
    case: str
    grader: str
    type: str
    status: str  # VACUOUS | ALWAYS_FAILS | NULL_PASS | DISCRIMINATES | UNKNOWN
    reason: str = ""
    guard: bool = False
    weak_rubric: bool = False
    probes: Dict[str, str] = field(default_factory=dict)

    def to_obj(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class CaseFinding:
    case: str
    mode: str  # "ablation-none" | "with-without"
    status: str  # NULL_GREEN | JUDGE_ONLY | OK
    probes: Dict[str, str] = field(default_factory=dict)  # probe -> GREEN | RED | UNKNOWN
    scored: List[str] = field(default_factory=list)

    def to_obj(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _is_guard(g: Grader) -> bool:
    c = g.config
    if g.type == "regex":
        m = str(c.get("match") or "contains")
        return m == "not_contains" or m == "count:0"
    if g.type == "tool_used":
        return c.get("max") is not None and int(c["max"]) == 0
    if g.type == "file_exists":
        return c.get("exists") is False
    return False


def _matches_empty(pattern: str, flags: str) -> Optional[bool]:
    try:
        py, fl = js_regex(pattern, flags)
    except UntranslatableRegex:
        return None
    return re.search(py, "", fl) is not None


def _static(g: Grader) -> Optional[tuple]:
    c = g.config
    if g.type == "regex":
        match = str(c.get("match") or "contains")
        target = c.get("target")
        empty = _matches_empty(str(c.get("pattern", "")), str(c.get("flags") or ""))
        file_target = isinstance(target, dict)
        if empty and match == "contains" and not file_target:
            return ("VACUOUS", "pattern matches the empty string, so `contains` passes on any output")
        if empty and match in ("not_contains", "count:0"):
            return ("ALWAYS_FAILS", "pattern matches the empty string, so absence can never hold")
    if g.type == "tool_used":
        lo = c.get("min", 1)
        lo = 1 if lo is None else int(lo)
        hi = c.get("max")
        if lo <= 0 and hi is None:
            return ("VACUOUS", "min: 0 with no max accepts any number of calls, including none")
        if hi is not None and lo > int(hi):
            return ("ALWAYS_FAILS", f"min {lo} is above max {hi}")
    return None


def _weak_rubric(g: Grader) -> bool:
    if g.type not in ("llm", "baseline"):
        return False
    text = (g.body or "") + " " + str(g.config.get("criteria") or "")
    return re.search(r"\bfail", text, re.I) is None


def scored_graders(case: Case, mode: str) -> List[Grader]:
    """Graders that count toward the score, per the docs' two-arm exclusion rule."""
    if mode == "ablation-none":
        return list(case.graders)

    def excluded(g: Grader) -> bool:
        if g.arm == "both":
            return False
        if g.arm == "with-only":
            return True
        if g.type == "tool_used" and g.config.get("tool") == "Skill":
            return True
        return False

    kept = [g for g in case.graders if not excluded(g)]
    return kept or list(case.graders)


def _case_verdict(scored: List[Grader], outcomes: Dict[str, Outcome], threshold: float) -> str:
    total = sum(g.weight for g in scored) or 1.0
    passed = sum(g.weight for g in scored if outcomes[g.name] is Outcome.PASS)
    unknown = sum(g.weight for g in scored if outcomes[g.name] is Outcome.UNKNOWN)
    lo, hi = passed / total, (passed + unknown) / total
    if lo >= threshold - 1e-9:
        return "GREEN"
    if hi < threshold - 1e-9:
        return "RED"
    return "UNKNOWN"


def analyze(suite: Suite, threshold: float = 1.0) -> Dict[str, Any]:
    graders: List[GraderFinding] = []
    cases: List[CaseFinding] = []
    for case in suite.cases:
        per_probe: Dict[str, Dict[str, Outcome]] = {p: {} for p in PROBES}
        for g in case.graders:
            f = GraderFinding(case.name, g.name, g.type, "UNKNOWN", guard=_is_guard(g), weak_rubric=_weak_rubric(g))
            for p in PROBES:
                r = evaluate(g, _probe(p, case))
                per_probe[p][g.name] = r.outcome
                f.probes[p] = r.outcome.value
                if r.outcome is Outcome.UNKNOWN and not f.reason:
                    f.reason = r.reason
            st = _static(g)
            outs = set(f.probes.values())
            if st:
                f.status, f.reason = st
            elif outs == {"UNKNOWN"}:
                f.status = "UNKNOWN"
            elif "PASS" in outs:
                f.status = "NULL_PASS"
                f.reason = "passes on probe(s): " + ", ".join(p for p, o in f.probes.items() if o == "PASS")
            else:
                f.status = "DISCRIMINATES"
                f.reason = ""
            if f.weak_rubric and f.status == "UNKNOWN":
                f.reason = "rubric never says what FAILs (heuristic)"
            graders.append(f)
        for mode in ("ablation-none", "with-without"):
            scored = scored_graders(case, mode)
            cf = CaseFinding(case.name, mode, "OK", scored=[g.name for g in scored])
            for p in PROBES:
                cf.probes[p] = _case_verdict(scored, per_probe[p], threshold)
            vals = set(cf.probes.values())
            if "GREEN" in vals:
                cf.status = "NULL_GREEN"
            elif "UNKNOWN" in vals:
                cf.status = "JUDGE_ONLY"
            cases.append(cf)
    return {
        "probes": {k: ("<the case prompt>" if v == "\x00ECHO" else v) for k, v in PROBES.items()},
        "threshold": threshold,
        "graders": [g.to_obj() for g in graders],
        "cases": [c.to_obj() for c in cases],
        "counts": {
            "vacuous": sum(1 for g in graders if g.status == "VACUOUS"),
            "always_fails": sum(1 for g in graders if g.status == "ALWAYS_FAILS"),
            "null_pass": sum(1 for g in graders if g.status == "NULL_PASS"),
            "null_green_cases": len({c.case for c in cases if c.status == "NULL_GREEN"}),
            "judge_only_cases": len({c.case for c in cases if c.status == "JUDGE_ONLY"}),
        },
    }


def failing(report: Dict[str, Any]) -> bool:
    """True when the vacuity report should fail CI: a proven vacuous or always-failing
    grader, or a case that a do-nothing run turns green."""
    c = report["counts"]
    return bool(c["vacuous"] or c["always_fails"] or c["null_green_cases"])
