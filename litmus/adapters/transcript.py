"""Transcript adapter — load pre-captured AgentRun artifacts from disk.

This is the whole M1 capture story: a run already happened (in CI, or from a
live adapter that wrote its result), and its AgentRun JSON sits on disk. The
engine grades it. No model, no network, no API key.

AgentRun JSON shape (all fields optional except what your assertions read):

    {
      "output": { ... },          # the structured result the agent produced
      "tool_calls": [ {"name": "finalize.py", "input": {...}}, ... ],
      "final_text": "…",
      "transcript": "…",
      "cost_usd": 0.03, "tokens": 4200, "latency_ms": 5100,
      "meta": { "model": "sonnet-5", "skill_version": "1.6.0" }
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ..models import AgentRun


def load(path: Path) -> AgentRun:
    return AgentRun.load(Path(path))


def load_many(paths: List[Path]) -> List[AgentRun]:
    return [AgentRun.load(Path(p)) for p in paths]
