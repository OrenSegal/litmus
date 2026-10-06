"""Write the simulated recordings that `litmus mutate --replay-results` replays for the demo.

NO MODEL IS CALLED. These files are hand-modelled stand-ins shaped like
`claude plugin eval --json` output (schemaVersion 1). The simulated agent obeys
the changelog skill literally:

- tests-only-diff passes only while the skill still triggers (its description
  mentions release notes) and still carries both halves of the Features rule;
- ends-with-version and no-todo-left always pass, because their graders
  cannot fail (that is the point of the demo).

Regenerate after editing the demo skill:

    python3 examples/record_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from litmus.adapters.base import ReplayRunner  # noqa: E402
from litmus.mutants import generate, select  # noqa: E402
from litmus.operators import OPERATORS  # noqa: E402

PLUGIN = HERE / "demo-plugin"
OUT = HERE / "demo-recordings"
SKILL = "skills/changelog/SKILL.md"


def scores(skill_text: str) -> dict:
    triggers = "release notes" in skill_text.split("---")[1] if skill_text.startswith("---") else False
    rule = 'Never write a "Features" heading' in skill_text and '"No user-facing changes."' in skill_text
    return {"tests-only-diff": 1.0 if (triggers and rule) else 0.0, "ends-with-version": 1.0, "no-todo-left": 1.0}


def doc(case_scores: dict) -> dict:
    return {
        "schemaVersion": 1,
        "claudeVersion": "simulated",
        "costUsd": 0.0,
        "partial": False,
        "suite": {"ablation": "none", "threshold": 1},
        "cases": [{"name": n, "aggregates": {"score": s},
                   "arms": {"with": [{"score": s, "passed": s >= 1, "error": None, "graders": []}]}}
                  for n, s in case_scores.items()],
        "aggregates": {"casesTotal": len(case_scores)},
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    original = (PLUGIN / SKILL).read_text(encoding="utf-8")
    (OUT / "baseline.json").write_text(json.dumps(doc(scores(original)), indent=1) + "\n", encoding="utf-8")
    files = [PLUGIN / SKILL]
    mutants = select(generate(PLUGIN, files, list(OPERATORS), 5), 20)
    for m in mutants:
        path = OUT / f"{ReplayRunner.safe(m.id)}.json"
        path.write_text(json.dumps(doc(scores(m.patched)), indent=1) + "\n", encoding="utf-8")
    print(f"wrote baseline + {len(mutants)} mutant recordings to {OUT}")


if __name__ == "__main__":
    main()
