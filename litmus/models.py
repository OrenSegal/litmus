"""Data shapes shared by every adapter: a suite, its cases and graders, and
the result of running a suite once.

Adapters translate their own formats into these. Nothing here knows about
`claude plugin eval`, promptfoo or any other runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Verdict(str, Enum):
    """Outcome of one mutant or one probe. INCONCLUSIVE never counts as KILLED."""

    KILLED = "KILLED"
    SURVIVED = "SURVIVED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class Grader:
    name: str
    type: str
    weight: float = 1.0
    arm: Optional[str] = None  # None | "with-only" | "both"
    config: Dict[str, Any] = field(default_factory=dict)
    body: str = ""  # rubric text for llm/baseline graders
    source: Optional[Path] = None

    @property
    def deterministic(self) -> bool:
        return self.type in ("regex", "tool_used", "tool_order", "file_exists")


@dataclass
class Case:
    name: str
    directory: Path
    prompt: str
    graders: List[Grader]
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Suite:
    """An eval suite plus the subject it tests (a plugin directory, a prompt file...)."""

    root: Path  # the directory the adapter copies to build a mutant
    eval_dir: Path
    cases: List[Case]
    adapter: str


@dataclass
class CaseRun:
    """One case's outcome in one suite run."""

    score: Optional[float]  # None when nothing could be graded
    error: Optional[str] = None


@dataclass
class SuiteRun:
    """One execution of the whole suite, against the original or a mutant."""

    ok: bool  # False: the run itself could not be trusted (crash, partial, auth)
    cases: Dict[str, CaseRun] = field(default_factory=dict)
    error: Optional[str] = None
    cost_usd: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None
