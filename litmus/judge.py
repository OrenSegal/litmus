"""Judge adapters — turn an artifact + rubric into a boolean verdict.

The trust guardrails (anchored calibration, judge panel, deterministic
floor) live in `assertions.judge` and are pure. This module only supplies the
`JudgeFn` those guardrails wrap. `ClaudeJudge` shells to the Claude CLI, which
handles auth itself (a `claude` login, or ANTHROPIC_API_KEY if that is set).
The `litmus` command uses it only when run with `--judge claude`. Tests never
let it reach a real model; `ScriptedJudge` is the deterministic fake they use
to prove the guardrails.

What `ClaudeJudge` sends: one prompt (the rubric and the artifact) over stdin,
to `claude -p` with every tool disabled (`--tools ""`), no MCP servers
(`--strict-mcp-config`), no saved session, and an empty temporary working
directory, so the judge can read nothing but the prompt and cannot act. The
environment is inherited unchanged because the CLI needs it for auth.

A JudgeFn returns True iff the artifact meets the rubric. It is deliberately
blind to authorship: it sees only {artifact, rubric}, never "you wrote this"
(§6 guardrail 4, no self-grading).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
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

# The verdict is the first word of the first non-empty line, allowing markdown
# decoration ("**PASS**", "FAIL."). Anything else is unparseable, not a PASS.
_VERDICT = re.compile(r"^\W*(PASS|FAIL)\b", re.IGNORECASE)


def parse_verdict(reply: str) -> bool:
    """True for PASS, False for FAIL; JudgeError for anything else."""
    for line in reply.splitlines():
        if line.strip():
            m = _VERDICT.match(line.strip())
            if m:
                return m.group(1).upper() == "PASS"
            raise JudgeError(f"judge reply does not start with PASS or FAIL: {line.strip()[:120]!r}")
    raise JudgeError("the Claude CLI judge returned an empty reply")


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
        argv = ["claude", "-p", "--model", self.model, "--tools", "",
                "--strict-mcp-config", "--no-session-persistence"]
        try:
            with tempfile.TemporaryDirectory(prefix="litmus-judge-") as scratch:
                proc = subprocess.run(
                    argv,
                    input=prompt,
                    cwd=scratch,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
        except FileNotFoundError as exc:
            raise JudgeError("the Claude CLI (`claude`) is not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise JudgeError(f"the Claude CLI judge timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise JudgeError(f"could not run the Claude CLI judge: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip() or "no output"
            raise JudgeError(
                f"the Claude CLI judge exited with code {proc.returncode}: {detail}. "
                "If this is an auth error, run `claude` to log in or set ANTHROPIC_API_KEY."
            )
        return parse_verdict(proc.stdout or "")
