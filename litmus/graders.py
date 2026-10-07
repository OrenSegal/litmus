"""Re-run the deterministic `claude plugin eval` grader types in Python.

`regex`, `tool_used`, `tool_order` and `file_exists` depend only on the run's
final message, tool calls and created files, so litmus can evaluate them
against synthetic probe runs without calling a model. `llm` and `baseline`
graders need a judge and are always UNKNOWN here.

Grader patterns are JavaScript regexes. `js_regex` translates the common
differences (named groups, `[^]`, flags); a pattern it cannot translate makes
the grader UNKNOWN rather than guessing. Semantics follow the published docs
(code.claude.com/docs/en/plugin-evals, "Grader types"); where the docs are
silent, litmus says so in the outcome's reason.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .models import Grader
from .regex import RegexTimeout, count_matches, search_any

__all__ = ["ProbeRun", "Outcome", "GraderResult", "evaluate", "js_regex", "UntranslatableRegex", "trace_text"]

REGEX_TIMEOUT = 2.0


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class GraderResult:
    outcome: Outcome
    reason: str = ""


@dataclass
class ProbeRun:
    """A synthetic run: what a grader sees, with no model involved."""

    prompt: str
    last_message: str = ""
    tool_calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    files_created: Dict[str, str] = field(default_factory=dict)  # path -> contents


class UntranslatableRegex(ValueError):
    pass


_JS_FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "g": 0, "u": 0, "y": 0, "d": 0}


def js_regex(pattern: str, flags: str = "") -> Tuple[str, int]:
    """Translate a JavaScript regex to (python_pattern, re_flags) or raise UntranslatableRegex."""
    py_flags = 0 if "u" in (flags or "") else re.ASCII  # JS \d \w \b are ASCII unless /u
    for f in flags or "":
        if f not in _JS_FLAGS:
            raise UntranslatableRegex(f"unknown JS regex flag {f!r}")
        py_flags |= _JS_FLAGS[f]
    p = re.sub(r"\(\?<(?![=!])", "(?P<", pattern)
    p = re.sub(r"\\k<(\w+)>", r"(?P=\1)", p)
    p = p.replace("[^]", r"[\s\S]")
    if re.search(r"\\[pP]\{", p) or re.search(r"\\u\{", p):
        raise UntranslatableRegex("unicode property or code point escape")
    try:
        re.compile(p, py_flags)
    except re.error as exc:
        raise UntranslatableRegex(f"does not compile as a Python regex: {exc}") from exc
    return p, py_flags


def _json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def trace_text(run: ProbeRun) -> str:
    """Approximate the `trace` target: one JSON message per line, prompt first.

    Assumption (not stated in the docs): the trace includes the user's prompt.
    The real trace also has a system/init line; probes leave it out, so a regex
    that only matches plugin or tool names listed there is not caught.
    """
    lines = [_json({"type": "user", "message": {"role": "user", "content": run.prompt}})]
    for name, inp in run.tool_calls:
        lines.append(_json({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": name, "input": inp}]}}))
    if run.last_message:
        lines.append(_json({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": run.last_message}]}}))
    return "\n".join(lines)


def _target_text(target: Any, run: ProbeRun) -> Tuple[Optional[str], str]:
    if target in (None, "last_message"):
        return run.last_message, ""
    if target == "trace":
        return trace_text(run), ""
    if target == "files":
        return "\n".join(run.files_created), ""
    if target == "mock_calls":
        return None, "mock_calls target is not modelled"
    if isinstance(target, dict) and target.get("source") == "file":
        path = str(target.get("path", ""))
        if path in run.files_created:
            return run.files_created[path], ""
        return None, f"file {path!r} does not exist in the probe (docs do not say how a missing file grades)"
    return None, f"unknown target {target!r}"


def _regex(g: Grader, run: ProbeRun) -> GraderResult:
    cfg = g.config
    pattern = str(cfg.get("pattern", ""))
    try:
        py, flags = js_regex(pattern, str(cfg.get("flags") or ""))
    except UntranslatableRegex as exc:
        return GraderResult(Outcome.UNKNOWN, str(exc))
    text, why = _target_text(cfg.get("target"), run)
    if text is None:
        return GraderResult(Outcome.UNKNOWN, why)
    match = str(cfg.get("match") or "contains")
    try:
        if match == "contains":
            ok = search_any(py, [text], REGEX_TIMEOUT, flags)
        elif match == "not_contains":
            ok = not search_any(py, [text], REGEX_TIMEOUT, flags)
        elif match.startswith("count:"):
            ok = count_matches(py, text, REGEX_TIMEOUT, flags) == int(match.split(":", 1)[1])
        else:
            return GraderResult(Outcome.UNKNOWN, f"unknown match mode {match!r}")
    except RegexTimeout:
        return GraderResult(Outcome.UNKNOWN, "regex timed out")
    return GraderResult(Outcome.PASS if ok else Outcome.FAIL, f"{match} /{pattern}/")


def _calls_matching(tool: str, input_match: Optional[str], run: ProbeRun) -> Optional[List[int]]:
    """Indexes of calls to `tool` whose JSON input matches; None if the regex is untranslatable."""
    rx: Optional[Tuple[str, int]] = None
    if input_match:
        try:
            rx = js_regex(str(input_match))
        except UntranslatableRegex:
            return None
    hits = []
    for i, (name, inp) in enumerate(run.tool_calls):
        if name != tool:
            continue
        if rx and not search_any(rx[0], [_json(inp)], REGEX_TIMEOUT, rx[1]):
            continue
        hits.append(i)
    return hits


def _tool_used(g: Grader, run: ProbeRun) -> GraderResult:
    cfg = g.config
    hits = _calls_matching(str(cfg.get("tool", "")), cfg.get("input_match"), run)
    if hits is None:
        return GraderResult(Outcome.UNKNOWN, "input_match does not translate to a Python regex")
    lo = int(cfg.get("min", 1) if cfg.get("min") is not None else 1)
    hi = cfg.get("max")
    ok = len(hits) >= lo and (hi is None or len(hits) <= int(hi))
    return GraderResult(Outcome.PASS if ok else Outcome.FAIL, f"{len(hits)} matching call(s), need {lo}..{hi}")


def _side(spec: Any) -> Tuple[str, Optional[str]]:
    if isinstance(spec, dict):
        return str(spec.get("tool", "")), spec.get("input_match")
    return str(spec), None


def _tool_order(g: Grader, run: ProbeRun) -> GraderResult:
    b = _calls_matching(*_side(g.config.get("before")), run)
    a = _calls_matching(*_side(g.config.get("after")), run)
    if a is None or b is None:
        return GraderResult(Outcome.UNKNOWN, "input_match does not translate to a Python regex")
    ok = bool(a) and bool(b) and b[0] < a[0]
    return GraderResult(Outcome.PASS if ok else Outcome.FAIL, "before precedes after" if ok else "order not met")


def _file_exists(g: Grader, run: ProbeRun) -> GraderResult:
    pattern = str(g.config.get("path", ""))
    exists = g.config.get("exists", True) is not False
    found = any(fnmatch.fnmatch(p, pattern) for p in run.files_created)
    ok = found if exists else not found
    return GraderResult(Outcome.PASS if ok else Outcome.FAIL, f"glob {pattern!r} {'found' if found else 'absent'}")


_EVAL = {"regex": _regex, "tool_used": _tool_used, "tool_order": _tool_order, "file_exists": _file_exists}


def evaluate(g: Grader, run: ProbeRun) -> GraderResult:
    fn = _EVAL.get(g.type)
    if fn is None:
        return GraderResult(Outcome.UNKNOWN, f"{g.type} grader needs a judge model")
    return fn(g, run)
