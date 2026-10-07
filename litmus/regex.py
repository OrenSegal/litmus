"""Time-boxed regex search, used to re-run eval graders against probe runs.

The pattern comes from the suite author and the text from a probe or a model.
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

__all__ = ["RegexTimeout", "search_any", "count_matches"]


class RegexTimeout(Exception):
    """The search did not finish within its time budget."""


_CHILD = (
    "import json, re, sys\n"
    "d = json.load(sys.stdin)\n"
    "rx = re.compile(d['p'], d['f'])\n"
    "print(sum(len(rx.findall(t)) if d['c'] else (1 if rx.search(t) else 0) for t in d['t']))\n"
)


def _can_alarm() -> bool:
    return hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()


def _count_alarm(pattern: str, flags: int, texts: List[str], timeout: float, count: bool) -> int:
    rx = re.compile(pattern, flags)

    def _on_alarm(signum: int, frame: Any) -> None:
        raise RegexTimeout(pattern)

    old_handler = signal.signal(signal.SIGALRM, _on_alarm)
    old_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        if count:
            return sum(len(rx.findall(t)) for t in texts)
        return 1 if any(rx.search(t) for t in texts) else 0
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:  # restore a timer someone else had running
            signal.setitimer(signal.ITIMER_REAL, *old_timer)


def _count_child(pattern: str, flags: int, texts: List[str], timeout: float, count: bool) -> int:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _CHILD],
            input=json.dumps({"p": pattern, "f": flags, "t": texts, "c": count}),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RegexTimeout(pattern) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"regex worker failed: {proc.stderr.strip() or proc.returncode}")
    return int(proc.stdout.strip() or 0)


def _run(pattern: str, flags: int, texts: List[str], timeout: float, count: bool) -> int:
    if timeout <= 0:
        raise ValueError("regex timeout must be positive")
    re.compile(pattern, flags)
    if not texts:
        return 0
    if _can_alarm():
        return _count_alarm(pattern, flags, texts, timeout, count)
    return _count_child(pattern, flags, texts, timeout, count)


def search_any(pattern: str, texts: List[str], timeout: float, flags: int = 0) -> bool:
    """True if `pattern` matches anywhere in any of `texts`.

    Raises RegexTimeout if the search takes longer than `timeout` seconds and
    re.error if the pattern does not compile.
    """
    return _run(pattern, flags, texts, timeout, count=False) > 0


def count_matches(pattern: str, text: str, timeout: float, flags: int = 0) -> int:
    """Number of non-overlapping matches of `pattern` in `text` (time-boxed)."""
    return _run(pattern, flags, [text], timeout, count=True)
