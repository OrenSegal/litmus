"""Adapters connect litmus to an eval runner.

An adapter knows three things about its runner: how to read a suite into
`litmus.models.Suite`, which files are the subject under test (what mutants
are made from), and how to run the suite once against a directory and report
per-case scores. Everything else (operators, vacuity probes, scoring, reports)
is shared. See SPEC.md, "Adapter interface".
"""

from __future__ import annotations

from typing import Callable, Dict

from .base import Adapter, CommandRunner, ReplayRunner, subprocess_runner
from .claude_plugin_eval import ClaudePluginEvalAdapter
from .shelfie_substitution import ShelfieSubstitutionAdapter

__all__ = ["Adapter", "CommandRunner", "ReplayRunner", "subprocess_runner", "ADAPTERS", "ClaudePluginEvalAdapter",
           "ShelfieSubstitutionAdapter"]

ADAPTERS: Dict[str, Callable[..., Adapter]] = {
    "claude-plugin-eval": ClaudePluginEvalAdapter,
    "shelfie-substitution": ShelfieSubstitutionAdapter,
}
