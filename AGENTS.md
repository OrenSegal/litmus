# AGENTS.md

litmus: mutation testing for LLM and agent eval suites. "Can your eval fail?"

- **Engine**: `litmus/`, pure Python, stdlib-only (PyYAML optional). Operators
  (`operators.py`), mutant manifests (`mutants.py`), offline vacuity probes
  (`vacuity.py`, `graders.py`), scoring (`scoring.py`), audit of existing
  results (`audit.py`), reports (`report.py`), orchestration (`engine.py`).
- **Adapters**: `litmus/adapters/`. `claude_plugin_eval.py` is the only one
  that runs anything, and only through an injected `CommandRunner`.
- **CLI**: `litmus mutate | vacuity | audit | operators`.
- **Spec**: `SPEC.md`. Keep it and the code in step.
- **Tests**: `python3 -m unittest discover -s tests -t .` (offline, no model).

The invariant: INCONCLUSIVE never counts as killed, and a grader litmus
cannot evaluate is UNKNOWN, never PASS. A real run spends the user's credit, so
`mutate` without `--dry-run` requires `--yes`; tests never call `claude`.

When extending: a new operator needs a test that it is deterministic, keeps
the frontmatter and skips code fences, plus a row in SPEC.md section 2. A new
adapter implements the `Adapter` protocol in `adapters/base.py` and is tested
with a fake runner.
