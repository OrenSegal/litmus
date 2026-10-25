"""The adapter contract and the command runners adapters shell out through."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from ..models import Suite, SuiteRun

__all__ = ["Adapter", "CommandResult", "CommandRunner", "subprocess_runner", "ReplayRunner"]


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """(argv, cwd, timeout_seconds, label, env) -> CommandResult. `label` is
    "baseline" or a mutant id; real runners ignore it, replay and fake runners
    key on it. `env` replaces the child's environment; None inherits ours."""

    def __call__(self, argv: List[str], cwd: Path, timeout: Optional[float], label: str,
                 env: Optional[Dict[str, str]] = None) -> CommandResult: ...


def subprocess_runner(argv: List[str], cwd: Path, timeout: Optional[float], label: str,
                      env: Optional[Dict[str, str]] = None) -> CommandResult:
    if shutil.which(argv[0], path=(env or {}).get("PATH")) is None:
        return CommandResult(127, "", f"{argv[0]}: not found on PATH")
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"timed out after {timeout}s")
    return CommandResult(p.returncode, p.stdout, p.stderr)


class ReplayRunner:
    """Replays recorded result files instead of running anything.

    `results_dir/<label>.json` is copied to the path the adapter asked the
    runner to write (the argument after `--json`). A label with no recording
    behaves like a failed run (exit 2), which litmus reports INCONCLUSIVE.
    Used by tests and by the offline demo in examples/.
    """

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir
        self.calls: List[List[str]] = []

    @staticmethod
    def safe(label: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)

    def __call__(self, argv: List[str], cwd: Path, timeout: Optional[float], label: str,
                 env: Optional[Dict[str, str]] = None) -> CommandResult:
        self.calls.append(list(argv))
        src = self.results_dir / f"{self.safe(label)}.json"
        if not src.is_file():
            return CommandResult(2, "", f"no recording for {label} at {src}")
        out = Path(argv[argv.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return CommandResult(0, "", "")


class Adapter(Protocol):
    name: str

    def load_suite(self, target: Path) -> Suite:
        """Read the suite. Raises ValueError with a readable message on a bad suite."""
        ...

    def subject_files(self, suite: Suite) -> List[Path]:
        """Files under suite.root that mutants may change. Never files of the suite itself."""
        ...

    def results_rel(self, suite: Suite) -> Optional[str]:
        """Path (relative to root) the runner writes results into; not copied into mutants."""
        ...

    def run(self, workdir: Path, suite: Suite, out_dir: Path, label: str) -> SuiteRun:
        """Run the whole suite once against `workdir` (a copy of suite.root)."""
        ...

    def describe_command(self, target: Path) -> str:
        """The real command one run executes, for docs and --dry-run output."""
        ...
