"""`litmus index` — the Hallucination Index.

Aggregate many suite results (skill × model) into a leaderboard: for each
entry, the share of cases that are verifiably green, and the share that are
INCONCLUSIVE (a self-grading model could have waved these through — Litmus
won't). Pure and offline; the growth-loop artifact of LITMUS_SPEC §12.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import Status, SuiteResult


@dataclass
class IndexEntry:
    skill: str
    model: str
    green: int
    failing: int
    inconclusive: int
    total: int

    @property
    def green_rate(self) -> float:
        return self.green / self.total if self.total else 0.0

    @classmethod
    def from_suite(cls, skill: str, model: str, result: SuiteResult) -> "IndexEntry":
        g = sum(1 for c in result.cases if c.status is Status.PASS)
        f = sum(1 for c in result.cases if c.status is Status.FAIL)
        i = sum(1 for c in result.cases if c.status is Status.INCONCLUSIVE)
        return cls(skill, model, g, f, i, len(result.cases))


def build_index(entries: List[IndexEntry]) -> List[IndexEntry]:
    """Rank worst-first: a low green-rate is the headline."""
    return sorted(entries, key=lambda e: (e.green_rate, -e.failing))


def render_index(entries: List[IndexEntry]) -> str:
    ranked = build_index(entries)
    lines = [
        "Litmus Hallucination Index",
        "",
        f"{'skill':<20} {'model':<14} {'green':>7} {'fail':>5} {'inconc':>7}",
        "-" * 56,
    ]
    for e in ranked:
        lines.append(
            f"{e.skill[:20]:<20} {e.model[:14]:<14} {e.green_rate:>6.0%} {e.failing:>5} {e.inconclusive:>7}"
        )
    return "\n".join(lines)
