"""Litmus — red/green CI for prompt-ware.

The engine grades an AgentRun (a captured artifact of one agent execution)
against a set of deterministic assertions. It never calls a model — grading
is pure and fully testable offline. See LITMUS_SPEC.md.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .models import AgentRun, Verdict, Status, Case, CaseResult, SuiteResult
from .runner import evaluate_case, evaluate_suite

__all__ = [
    "AgentRun",
    "Verdict",
    "Status",
    "Case",
    "CaseResult",
    "SuiteResult",
    "evaluate_case",
    "evaluate_suite",
    "__version__",
]
