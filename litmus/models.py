"""Core data model. Everything the engine reads or produces lives here.

The one contract that matters is `AgentRun`: the captured artifact of a single
agent execution. Adapters (transcript, claude-code, agent-sdk) produce it; the
engine only ever consumes it. Keeping this the sole input is what makes the
engine pure and testable without a model or an API key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Status(str, Enum):
    """Verdict severity. Ordered worst-first via `rank` for aggregation.

    INCONCLUSIVE exists so a judge that can't prove its grade never reports a
    green — the load-bearing rule of the whole product (see LITMUS_SPEC §6).
    """

    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIP = "SKIP"
    PASS = "PASS"

    @property
    def rank(self) -> int:
        # lower = worse; used to pick the worst status in a group
        return {"FAIL": 0, "INCONCLUSIVE": 1, "SKIP": 2, "PASS": 3}[self.value]

    @property
    def is_green(self) -> bool:
        return self is Status.PASS


def worst(statuses: List["Status"]) -> "Status":
    if not statuses:
        return Status.SKIP
    return min(statuses, key=lambda s: s.rank)


@dataclass
class ToolCall:
    name: str
    input: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_obj(cls, obj: Dict[str, Any]) -> "ToolCall":
        return cls(name=str(obj.get("name", "")), input=dict(obj.get("input", {})))


@dataclass
class AgentRun:
    """One captured execution. `output` is the agent's structured result
    (the JSON it produced); `tool_calls` is the ordered list of tools it
    invoked; the rest are optional telemetry for budget assertions."""

    output: Any = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    final_text: str = ""
    transcript: str = ""
    cost_usd: Optional[float] = None
    tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_obj(cls, obj: Dict[str, Any]) -> "AgentRun":
        return cls(
            output=obj.get("output"),
            tool_calls=[ToolCall.from_obj(t) for t in obj.get("tool_calls", [])],
            final_text=str(obj.get("final_text", "")),
            transcript=str(obj.get("transcript", "")),
            cost_usd=obj.get("cost_usd"),
            tokens=obj.get("tokens"),
            latency_ms=obj.get("latency_ms"),
            meta=dict(obj.get("meta", {})),
        )

    @classmethod
    def load(cls, path: Path) -> "AgentRun":
        return cls.from_obj(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class Verdict:
    """Result of one assertion against one AgentRun."""

    name: str
    status: Status
    detail: str = ""
    evidence: Any = None

    @classmethod
    def passed(cls, name: str, detail: str = "", evidence: Any = None) -> "Verdict":
        return cls(name, Status.PASS, detail, evidence)

    @classmethod
    def failed(cls, name: str, detail: str = "", evidence: Any = None) -> "Verdict":
        return cls(name, Status.FAIL, detail, evidence)

    @classmethod
    def inconclusive(cls, name: str, detail: str = "", evidence: Any = None) -> "Verdict":
        return cls(name, Status.INCONCLUSIVE, detail, evidence)

    @classmethod
    def skipped(cls, name: str, detail: str = "") -> "Verdict":
        return cls(name, Status.SKIP, detail)


@dataclass
class AssertionResult:
    """One assertion aggregated across a case's N samples."""

    name: str
    status: Status
    pass_rate: float
    threshold: float
    samples: int
    verdicts: List[Verdict] = field(default_factory=list)

    @property
    def flaky(self) -> bool:
        # neither reliably green nor reliably red
        return 0.0 < self.pass_rate < 1.0

    def to_baseline(self) -> Dict[str, Any]:
        return {"status": self.status.value, "pass_rate": round(self.pass_rate, 4)}


@dataclass
class Case:
    """A golden task. `runs` are the AgentRun sources (paths) for its samples;
    the runner may also fill them by convention (see suite loader)."""

    id: str
    asserts: List[Dict[str, Any]] = field(default_factory=list)
    target: Dict[str, Any] = field(default_factory=dict)
    input: Any = None
    samples: int = 1
    runs: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class CaseResult:
    id: str
    status: Status
    assertions: List[AssertionResult] = field(default_factory=list)
    target: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def flaky(self) -> bool:
        return any(a.flaky for a in self.assertions)

    def to_baseline(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "assertions": {a.name: a.to_baseline() for a in self.assertions},
        }


@dataclass
class SuiteResult:
    name: str
    cases: List[CaseResult] = field(default_factory=list)
    target: Dict[str, Any] = field(default_factory=dict)

    @property
    def green(self) -> bool:
        return all(c.status is Status.PASS for c in self.cases)

    def to_baseline(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "target": self.target,
            "cases": {c.id: c.to_baseline() for c in self.cases},
        }
