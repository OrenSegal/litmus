"""Time-boxed regex search for the `matches` assertion.

The pattern comes from the case author and the text from the model under test.
A pattern with nested quantifiers (`^(a+)+$`) can backtrack exponentially on
the wrong text, and Python's `re` has no timeout of its own. Two ways to bound it:

- On the main thread of a platform with SIGALRM, an interval timer interrupts
  the search (CPython checks for signals inside the regex engine).
- Anywhere else (worker threads, Windows), the search runs in a child Python
  process that is killed when the timeout passes.

Either way a search that runs too long raises RegexTimeout, which the caller
turns into a FAIL instead of a hang.
"""

from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import threading
from typing import Any, List

__all__ = ["RegexTimeout", "search_any"]


class RegexTimeout(Exception):
    """The search did not finish within its time budget."""


_CHILD = (
    "import json, re, sys\n"
    "d = json.load(sys.stdin)\n"
    "rx = re.compile(d['p'])\n"
    "sys.exit(0 if any(rx.search(t) for t in d['t']) else 1)\n"
)


def _can_alarm() -> bool:
    return hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()


def _search_alarm(pattern: str, texts: List[str], timeout: float) -> bool:
    rx = re.compile(pattern)

    def _on_alarm(signum: int, frame: Any) -> None:
        raise RegexTimeout(pattern)

    old_handler = signal.signal(signal.SIGALRM, _on_alarm)
    old_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return any(rx.search(t) for t in texts)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:  # restore a timer someone else had running
            signal.setitimer(signal.ITIMER_REAL, *old_timer)


def _search_child(pattern: str, texts: List[str], timeout: float) -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _CHILD],
            input=json.dumps({"p": pattern, "t": texts}),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RegexTimeout(pattern) from exc
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"regex worker failed: {proc.stderr.strip() or proc.returncode}")
    return proc.returncode == 0


def search_any(pattern: str, texts: List[str], timeout: float) -> bool:
    """True if `pattern` matches anywhere in any of `texts`.

    Raises RegexTimeout if the search takes longer than `timeout` seconds and
    re.error if the pattern does not compile.
    """
    if timeout <= 0:
        raise ValueError("regex timeout must be positive")
    re.compile(pattern)
    if not texts:
        return False
    if _can_alarm():
        return _search_alarm(pattern, texts, timeout)
    return _search_child(pattern, texts, timeout)
