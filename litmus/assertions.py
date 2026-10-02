"""The assertion library — the heart of litmus.

Each assertion is a pure function `(config, AgentRun, EvalContext) -> Verdict`.
Deterministic assertions are trusted unconditionally. The one judge assertion
is trusted only through the §6 guardrails, and with no judge configured it
returns INCONCLUSIVE — never PASS — because a green must come from a check
that could have failed.

A case's `assert:` entry is a dict with exactly one key (the assertion name);
its value is that assertion's config (a string shorthand or a dict).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import schema as schema_mod
from .case import suite_path
from .fetch import Fetcher, UrllibFetcher, grounding_ratio, is_http_url
from .regex import RegexTimeout, search_any
from .jsonpath import exists, resolve
from .model_ids import normalize_model_id, same_model
from .models import AgentRun, Status, Verdict

# A judge callable: (artifact, rubric) -> bool  (True == meets the criterion).
# Absent by default, so judge assertions are INCONCLUSIVE unless a caller wires
# one in (the CLI does this only with `--judge`).
JudgeFn = Callable[[Any, str], bool]


class JudgeError(RuntimeError):
    """The configured judge could not give a verdict (CLI missing, auth failed,
    empty reply). It aborts the run instead of becoming a verdict, so a broken
    judge is never reported as INCONCLUSIVE or FAIL."""


@dataclass
class EvalContext:
    fetcher: Fetcher = field(default_factory=UrllibFetcher)
    base_dir: Path = field(default_factory=lambda: Path("."))
    judge: Optional[JudgeFn] = None
    timeout: int = 10
    # The suite/case `target.model`. Fallback for the model that produced a run
    # when the run itself has no `meta.model` (see `producing_model`).
    target_model: Optional[str] = None
    # Messages for the caller to show once (the CLI prints them to stderr).
    # Shared by reference across per-case copies of the context, deduplicated.
    warnings: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


AssertionFn = Callable[[Any, AgentRun, EvalContext], Verdict]
_REGISTRY: Dict[str, AssertionFn] = {}


def assertion(name: str) -> Callable[[AssertionFn], AssertionFn]:
    def deco(fn: AssertionFn) -> AssertionFn:
        _REGISTRY[name] = fn
        return fn

    return deco


def run_assertion(entry: Dict[str, Any], run: AgentRun, ctx: EvalContext) -> Verdict:
    """Dispatch one `assert:` entry (a single-key dict) to its handler."""
    if not isinstance(entry, dict) or len(entry) != 1:
        return Verdict("<malformed>", Status.FAIL, f"assert entry must be a single-key dict, got {entry!r}")
    name, config = next(iter(entry.items()))
    handler = _REGISTRY.get(name)
    if handler is None:
        return Verdict(name, Status.FAIL, f"unknown assertion '{name}'")
    try:
        return handler(config, run, ctx)
    except JudgeError:
        raise
    except Exception as exc:  # a broken assertion config is a failure, never a crash
        return Verdict(name, Status.FAIL, f"assertion errored: {exc}")


# --------------------------------------------------------------------------- #
# tool-call assertions
# --------------------------------------------------------------------------- #
def _called(run: AgentRun, tool: str) -> List[int]:
    return [i for i, c in enumerate(run.tool_calls) if c.name == tool]


def _subset(sub: Dict[str, Any], sup: Dict[str, Any]) -> bool:
    return all(k in sup and sup[k] == v for k, v in sub.items())


@assertion("must_run")
def must_run(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    cfg: Dict[str, Any] = {"tool": config} if isinstance(config, str) else dict(config)
    tool = cfg["tool"]
    hits = _called(run, tool)
    if not hits:
        return Verdict.failed("must_run", f"tool {tool!r} was never called", [c.name for c in run.tool_calls])
    if "args" in cfg:
        if not any(_subset(cfg["args"], run.tool_calls[i].input) for i in hits):
            return Verdict.failed("must_run", f"{tool!r} called, but never with args {cfg['args']}")
    if "before" in cfg:
        other = _called(run, cfg["before"])
        if not other or min(hits) >= min(other):
            return Verdict.failed("must_run", f"{tool!r} not called before {cfg['before']!r}")
    if "after" in cfg:
        other = _called(run, cfg["after"])
        if not other or max(hits) <= max(other):
            return Verdict.failed("must_run", f"{tool!r} not called after {cfg['after']!r}")
    return Verdict.passed("must_run", f"{tool!r} called")


@assertion("ordering")
def ordering(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    first, then = config["first"], config["then"]
    a, b = _called(run, first), _called(run, then)
    if not a or not b:
        return Verdict.failed("ordering", f"need both {first!r} and {then!r} called; got {bool(a)}/{bool(b)}")
    if min(a) < min(b):
        return Verdict.passed("ordering", f"{first!r} before {then!r}")
    return Verdict.failed("ordering", f"{first!r} not before {then!r}")


@assertion("must_not")
def must_not(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    cfg = dict(config)
    if "tool" in cfg:
        if _called(run, cfg["tool"]):
            return Verdict.failed("must_not", f"forbidden tool {cfg['tool']!r} was called")
        return Verdict.passed("must_not", f"{cfg['tool']!r} not called")
    if "field" in cfg:
        if exists(cfg["field"], run.output):
            return Verdict.failed("must_not", f"forbidden field present: {cfg['field']}", resolve(cfg["field"], run.output))
        return Verdict.passed("must_not", f"{cfg['field']} absent")
    if "phrase" in cfg:
        where = cfg.get("in", "final_text")
        hay = {"final_text": run.final_text, "transcript": run.transcript, "output": str(run.output)}[where]
        if cfg["phrase"].lower() in hay.lower():
            return Verdict.failed("must_not", f"forbidden phrase {cfg['phrase']!r} present in {where}")
        return Verdict.passed("must_not", f"{cfg['phrase']!r} absent from {where}")
    return Verdict.failed("must_not", f"must_not needs one of tool/field/phrase, got {list(cfg)}")


# --------------------------------------------------------------------------- #
# output-shape assertions
# --------------------------------------------------------------------------- #
@assertion("schema")
def schema(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    cfg = dict(config)
    path = cfg.get("path", "$")
    if "ref" in cfg:
        sch = json.loads(suite_path(ctx.base_dir, cfg["ref"]).read_text(encoding="utf-8"))
    else:
        sch = cfg["schema"]
    targets = resolve(path, run.output)
    if not targets:
        return Verdict.failed("schema", f"path {path} matched nothing in output")
    errs: List[str] = []
    for t in targets:
        errs.extend(schema_mod.validate(t, sch))
    if errs:
        return Verdict.failed("schema", f"{len(errs)} schema error(s)", errs[:10])
    return Verdict.passed("schema", f"{path} valid")


@assertion("equals")
def equals(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    path, value = config["path"], config["value"]
    got = resolve(path, run.output)
    if not got:
        return Verdict.failed("equals", f"{path} matched nothing")
    if all(g == value for g in got):
        return Verdict.passed("equals", f"{path} == {value!r}")
    return Verdict.failed("equals", f"{path} != {value!r}", got)


@assertion("contains")
def contains(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    path, value = config["path"], config["value"]
    got = [g for g in resolve(path, run.output) if isinstance(g, str)]
    if any(value in g for g in got):
        return Verdict.passed("contains", f"{path} contains {value!r}")
    return Verdict.failed("contains", f"no value at {path} contains {value!r}", got)


@assertion("matches")
def matches(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    path, pattern = config["path"], config["pattern"]
    timeout = float(config.get("timeout", 2.0))
    re.compile(pattern)  # a bad pattern is a config error, raised before any matching
    got = [g for g in resolve(path, run.output) if isinstance(g, str)]
    # The pattern is the case author's; the text is the model's. A pattern with
    # nested quantifiers can backtrack for minutes on the wrong text, so the
    # search is time-boxed and a timeout is a FAIL, never a hang.
    try:
        hit = search_any(pattern, got, timeout)
    except RegexTimeout:
        return Verdict.failed(
            "matches", f"regex /{pattern}/ timed out after {timeout}s at {path} "
            "(catastrophic backtracking?); simplify the pattern")
    if hit:
        return Verdict.passed("matches", f"{path} matches /{pattern}/")
    return Verdict.failed("matches", f"no value at {path} matches /{pattern}/", got)


_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


@assertion("count")
def count(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    path, op, value = config["path"], config["op"], config["value"]
    n = len(resolve(path, run.output))
    if _OPS[op](n, value):
        return Verdict.passed("count", f"count({path})={n} {op} {value}")
    return Verdict.failed("count", f"count({path})={n} not {op} {value}")


_BUDGET_METRICS = {"cost_usd", "tokens", "latency_ms"}


@assertion("budget")
def budget(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    limits = dict(config)
    if not limits:
        return Verdict.failed("budget", f"budget needs at least one of {sorted(_BUDGET_METRICS)}")
    unknown = sorted(set(limits) - _BUDGET_METRICS)
    if unknown:
        return Verdict.failed("budget", f"unknown budget metric(s) {unknown}; use {sorted(_BUDGET_METRICS)}")
    for metric, cap in limits.items():
        got = getattr(run, metric, None)
        if got is None:
            return Verdict.inconclusive("budget", f"run has no {metric} telemetry to check")
        if got > cap:
            return Verdict.failed("budget", f"{metric}={got} exceeds {cap}")
    return Verdict.passed("budget", f"within {limits}")


# --------------------------------------------------------------------------- #
# grounding assertions: network I/O only through ctx.fetcher
# --------------------------------------------------------------------------- #
@assertion("resolves")
def resolves(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    cfg = {"path": config} if isinstance(config, str) else dict(config)
    urls = [u for u in resolve(cfg["path"], run.output) if is_http_url(u)]
    if not urls:
        return Verdict.skipped("resolves", f"no fetchable URLs at {cfg['path']}")
    dead, walled = [], []
    for url in urls:
        res = ctx.fetcher.fetch(url, ctx.timeout)
        if res.bot_walled:
            walled.append(url)
        elif res.status is None or res.status >= 400:
            dead.append((url, res.status))
    if dead:
        return Verdict.failed("resolves", f"{len(dead)} unreachable URL(s)", dead)
    if walled:
        return Verdict.inconclusive("resolves", f"{len(walled)} bot-walled URL(s) — unverifiable, not dead", walled)
    return Verdict.passed("resolves", f"{len(urls)} URL(s) live")


@assertion("grounded")
def grounded(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    claims = resolve(config["claim"], run.output)
    sources = resolve(config["source"], run.output)
    threshold = float(config.get("threshold", 0.15))
    if len(claims) != len(sources):
        # Claims and sources pair up by position; with unequal counts the
        # pairing is a guess and the extra claims would go unchecked.
        return Verdict.failed(
            "grounded", f"{len(claims)} claim(s) but {len(sources)} source(s) matched; "
            "each claim needs exactly one source")
    pairs = list(zip(claims, sources))
    if not pairs:
        return Verdict.skipped("grounded", "no claim/source pairs to check")
    low: List[Tuple[str, float]] = []
    walled: List[str] = []
    unfetchable: List[Any] = []
    for claim, source in pairs:
        if not is_http_url(source):
            unfetchable.append(source)
            continue
        res = ctx.fetcher.fetch(source, ctx.timeout)
        if res.bot_walled:
            walled.append(source)
            continue
        ratio = grounding_ratio(str(claim), res.text)
        if ratio < threshold:
            low.append((source, round(ratio, 2)))
    if low:
        return Verdict.failed("grounded", f"{len(low)} claim(s) not grounded in their source", low)
    if len(unfetchable) == len(pairs):
        return Verdict.skipped("grounded", "no claim had a fetchable http(s) source")
    if walled or unfetchable:
        return Verdict.inconclusive(
            "grounded", f"{len(walled)} source(s) bot-walled and {len(unfetchable)} not an http(s) URL "
            "— unverifiable", walled + unfetchable)
    return Verdict.passed("grounded", f"{len(pairs)} claim(s) grounded")


# --------------------------------------------------------------------------- #
# judge assertion — untrusted until anchored (§6). No judge => INCONCLUSIVE.
# --------------------------------------------------------------------------- #
@assertion("judge")
def judge(config: Any, run: AgentRun, ctx: EvalContext) -> Verdict:
    rubric = config["rubric"]
    if ctx.judge is None:
        return Verdict.inconclusive(
            "judge",
            "no judge configured — a green must come from a falsifiable check, so this is INCONCLUSIVE, not PASS",
        )
    # §6 guardrail 1: anchored calibration. Anchors are required, with at least one
    # "pass" and at least one "fail" example. Without both, calibration cannot catch a
    # constant judge: an always-PASS judge agrees with any pass-only set, and an
    # always-FAIL judge agrees with any fail-only set. An uncalibrated judge call is
    # not a check that could have failed, so it is INCONCLUSIVE, never PASS.
    anchors = config.get("anchors") or []
    expects = [a.get("expect") for a in anchors]
    bad = [e for e in expects if e not in ("pass", "fail")]
    if bad:
        return Verdict.failed("judge", f"anchor expect must be 'pass' or 'fail', got {bad!r}")
    if "pass" not in expects or "fail" not in expects:
        return Verdict.inconclusive(
            "judge",
            "judge needs at least one 'pass' and one 'fail' anchor to be calibrated; "
            "an uncalibrated judge verdict is INCONCLUSIVE, not PASS",
        )
    # §6 guardrail 4: no self-grading. Checked before any judge call, so a judge
    # that is the model under test never sees the anchors or the real output.
    same, reason = _self_grading(run, ctx)
    if same:
        return Verdict.inconclusive("judge", reason)
    # Load every anchor before the first judge call, so an anchor path that
    # leaves the suite fails the assertion without anything reaching the judge.
    loaded = [(anchor, json.loads(suite_path(ctx.base_dir, anchor["output"]).read_text(encoding="utf-8")))
              for anchor in anchors]
    if reason:
        ctx.warn(reason)
    # If the judge misgrades a known anchor, its verdict on the real artifact is void.
    for anchor, art in loaded:
        expect = anchor["expect"] == "pass"
        if ctx.judge(art, rubric) != expect:
            return Verdict.inconclusive("judge", f"judge failed anchor calibration on {anchor['output']}")
    # §6 guardrail 2: judge panel, ties default to FAIL.
    panel = int(config.get("panel", 1))
    votes = [ctx.judge(run.output, rubric) for _ in range(panel)]
    if sum(votes) * 2 > panel:
        return Verdict.passed("judge", f"panel {sum(votes)}/{panel} after anchor calibration")
    return Verdict.failed("judge", f"panel {sum(votes)}/{panel} (ties default to fail)")


# --------------------------------------------------------------------------- #
# no self-grading (§6 guardrail 4): the judge model must not be the model that
# produced the run.
# --------------------------------------------------------------------------- #
def producing_model(run: AgentRun, ctx: EvalContext) -> Optional[str]:
    """The model that produced `run`: its `meta.model`, else the suite or case
    `target.model`. None if neither names a model."""
    for candidate in (run.meta.get("model"), ctx.target_model):
        if normalize_model_id(candidate) is not None:
            return str(candidate)
    return None


def _self_grading(run: AgentRun, ctx: EvalContext) -> Tuple[bool, str]:
    """Return (is_self_grading, message).

    (True, reason) when the judge model is the producing model. (False, warning)
    when either side is unknown, so the check could not run. (False, "") when
    the two are known and differ.
    """
    judge_model = getattr(ctx.judge, "model", None)
    produced_by = producing_model(run, ctx)
    if normalize_model_id(judge_model) is None:
        return False, (
            "no-self-grading check skipped: the judge does not report a model, so "
            "litmus cannot tell whether it produced the runs it grades"
        )
    if produced_by is None:
        return False, (
            "no-self-grading check skipped: some graded runs have no meta.model and "
            "the suite has no target.model, so litmus cannot tell whether the judge "
            f"model ({judge_model}) produced them"
        )
    if same_model(judge_model, produced_by):
        return True, (
            f"self-grading: judge model {judge_model!r} is the model that produced this "
            f"run ({produced_by!r}), so it may not grade it. Use a different --judge-model. "
            "Not graded, so INCONCLUSIVE, not PASS"
        )
    return False, ""
