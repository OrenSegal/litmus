# AGENTS.md

litmus: red/green regression tests for skills, prompts and tool definitions.
Part of [sous](https://github.com/OrenSegal/sous).

- **Engine**: `litmus/` — pure Python, stdlib-only, no model calls. Grades an
  `AgentRun` (captured agent execution) against deterministic assertions.
- **Skill**: `skills/litmus/SKILL.md` teaches an agent to author + run suites.
- **CLI**: `litmus run | gate | bless | matrix | index | capture | calibrate | status`
  (`pip install git+https://github.com/OrenSegal/litmus`, the plugin's `bin/litmus`, or `python3 -m litmus.cli`).
- **Tests**: `python3 -m unittest discover -s tests -t .` (offline, no API key).

The invariant that defines the product: **a green only ever comes from a check
that could have failed.** Judge verdicts without a falsifiable anchor are
`INCONCLUSIVE`, never `PASS`. See `LITMUS_SPEC.md` §6 and
`skills/litmus/references/trust-architecture.md`.

When extending: keep the engine pure (grade JSON, never call a model — adapters
do that), add a test for every new assertion, and never let a green come from an
unfalsifiable check.
