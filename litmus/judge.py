"""Judge adapters — turn an artifact + rubric into a boolean verdict.

The trust guardrails (anchored calibration, judge panel, deterministic
floor) live in `assertions.judge` and are pure. This module only supplies the
`JudgeFn` those guardrails wrap. `ClaudeJudge` shells to the Claude CLI, which
handles auth itself (a `claude` login, or ANTHROPIC_API_KEY if that is set).
The `litmus` command uses it only when run with `--judge claude`. Tests never
let its subprocess call run; `ScriptedJudge` is the deterministic fake they use
to prove the guardrails.

A JudgeFn returns True iff the artifact meets the rubric. It is deliberately
blind to authorship: it sees only {artifact, rubric}, never "you wrote this"
(§6 guardrail 4, no self-grading).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, Optional, Tuple

from .assertions import JudgeError

_JUDGE_PROMPT = """You are a reviewer trying to refute the claim that the \
artifact satisfies the criterion. Look for a concrete way the artifact violates \
the criterion. If you find one, answer FAIL. Answer PASS only if you looked and \
could not find any violation. Judge ONLY the artifact against the criterion; do \
not consider who produced it. Answer with a single word on the first line: \
PASS or FAIL.

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

    def __init__(self, rule: Callable[[Any, str], bool], model: Optional[str] = None):
        self._rule = rule
        # The model this fake stands in for, read by the no-self-grading check.
        self.model = model

    def __call__(self, artifact: Any, rubric: str) -> bool:
        return bool(self._rule(artifact, rubric))


DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"


class ClaudeJudge:
    """Judge backed by the Claude CLI (`claude -p`).

    Raises JudgeError when the CLI is missing, exits non-zero, or replies with
    nothing, so a broken judge stops the run with a message instead of quietly
    misgrading an anchor and showing up as INCONCLUSIVE.
    """

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, timeout: int = 120):
        self.model = model
        self.timeout = timeout

    @staticmethod
    def check_available() -> None:
        """Fail fast, before any grading, if the `claude` command isn't on PATH."""
        if shutil.which("claude") is None:
            raise JudgeError(
                "--judge claude needs the Claude CLI, and `claude` is not on PATH. "
                "Install it, then either run `claude` once to log in or set "
                "ANTHROPIC_API_KEY. Leave out --judge to skip judging (judge "
                "assertions will be INCONCLUSIVE)."
            )

    def __call__(self, artifact: Any, rubric: str) -> bool:
        prompt = _JUDGE_PROMPT.format(
            rubric=rubric,
            artifact=json.dumps(artifact, ensure_ascii=False) if not isinstance(artifact, str) else artifact,
        )
        try:
            proc = subprocess.run(
                ["claude", "-p", prompt, "--model", self.model],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise JudgeError("the Claude CLI (`claude`) is not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise JudgeError(f"the Claude CLI judge timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip() or "no output"
            raise JudgeError(
                f"the Claude CLI judge exited with code {proc.returncode}: {detail}. "
                "If this is an auth error, run `claude` to log in or set ANTHROPIC_API_KEY."
            )
        if not proc.stdout.strip():
            raise JudgeError("the Claude CLI judge returned an empty reply")
        first = proc.stdout.strip().splitlines()[0].upper()
        return bool(re.search(r"\bPASS\b", first))
