"""`litmus index`: rank suites worst-first by their share of green cases.

One row per suite, labelled by its target skill and model, with counts of
failing and INCONCLUSIVE cases. Pure and offline.
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
        counts = result.counts()
        return cls(skill, model, counts[Status.PASS], counts[Status.FAIL], counts[Status.INCONCLUSIVE],
                   len(result.cases))


def build_index(entries: List[IndexEntry]) -> List[IndexEntry]:
    """Rank worst-first: a low green-rate is the headline."""
    return sorted(entries, key=lambda e: (e.green_rate, -e.failing))


def render_index(entries: List[IndexEntry]) -> str:
    ranked = build_index(entries)
    lines = [
        "litmus index",
        "",
        f"{'skill':<20} {'model':<14} {'green':>7} {'fail':>5} {'inconc':>7}",
        "-" * 56,
    ]
    for e in ranked:
        lines.append(
            f"{e.skill[:20]:<20} {e.model[:14]:<14} {e.green_rate:>6.0%} {e.failing:>5} {e.inconclusive:>7}"
        )
    return "\n".join(lines)
