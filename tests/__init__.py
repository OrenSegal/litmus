"""litmus tests. No test may start a real eval run.

`litmus mutate` without an injected runner shells out to `claude plugin eval`
on the caller's credential. The only thing that stopped a test from doing that
was the code under test (the `--yes` check): a regression there turned
`python -m unittest` into a paid run for anyone with `claude` on PATH. So the
adapters' default runner is replaced here, for every test, with one that fails.
Tests that need a runner inject `FakeRunner` or `ReplayRunner`; the one test of
`subprocess_runner` itself imports it from `litmus.adapters.base`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from litmus.adapters import claude_plugin_eval, shelfie_substitution
from litmus.adapters.base import CommandResult


def _refuse(argv: List[str], cwd: Path, timeout: Optional[float], label: str,
            env: Optional[Dict[str, str]] = None) -> CommandResult:
    raise AssertionError(f"a test tried to run a real command: {' '.join(argv[:3])} ... (inject a fake runner)")


claude_plugin_eval.subprocess_runner = _refuse  # type: ignore[assignment]
shelfie_substitution.subprocess_runner = _refuse  # type: ignore[assignment]
