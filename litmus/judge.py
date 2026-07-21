"""Judge adapters — turn an artifact + rubric into a boolean verdict.

The trust guardrails (anchored calibration, adversarial panel, deterministic
floor) live in `assertions.judge` and are pure. This module only supplies the
`JudgeFn` those guardrails wrap. `ClaudeJudge` shells to the Claude CLI (its
own auth — no API key here) and is never exercised by the offline test suite;
`ScriptedJudge` is the deterministic fake the tests use to prove the guardrails.

A JudgeFn returns True iff the artifact meets the rubric. It is deliberately
blind to authorship: it sees only {artifact, rubric}, never "you wrote this"
(§6 guardrail 4, no self-grading).
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Dict, Tuple

_JUDGE_PROMPT = """You are a strict evaluator. Judge ONLY whether the artifact \
satisfies the criterion. Do not consider who produced it. Answer with a single \
word on the first line: PASS or FAIL.

CRITERION:
{rubric}

ARTIFACT:
{artifact}
"""


class ScriptedJudge:
    """Deterministic judge for tests: maps a (artifact-key) -> bool via a rule.

    `rule` receives the artifact and rubric and returns a bool. This lets the
    guardrail tests simulate a well-calibrated judge, a miscalibrated one, and
    a coin-flip panel without any model call.
    """

    def __init__(self, rule: Callable[[Any, str], bool]):
        self._rule = rule

    def __call__(self, artifact: Any, rubric: str) -> bool:
        return bool(self._rule(artifact, rubric))


class ClaudeJudge:
    """Judge backed by the Claude CLI. Not used in the offline test suite."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001", timeout: int = 120):
        self.model = model
        self.timeout = timeout

    def __call__(self, artifact: Any, rubric: str) -> bool:
        prompt = _JUDGE_PROMPT.format(
            rubric=rubric,
            artifact=json.dumps(artifact, ensure_ascii=False) if not isinstance(artifact, str) else artifact,
        )
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", self.model],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        first = (proc.stdout.strip().splitlines() or [""])[0].upper()
        return bool(re.search(r"\bPASS\b", first))
