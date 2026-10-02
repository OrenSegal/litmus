---
name: litmus
description: >-
  Author and run red/green regression tests for a skill, system prompt, or tool
  definition. Use when someone wants to test prompt-ware behavior, catch a skill
  regression, check whether a skill still works on a new model, or pin golden
  tasks with assertions. Turns "did my edit make the agent better or worse?"
  from vibes into a red/green diff.
---

# litmus: red/green regression tests for skills, prompts and tool definitions

litmus tests the *behavior* of a skill, not its scripts. You pin golden tasks
(cases), each with assertions over what the agent actually did, and get a
red/green diff. Underneath it is a verification harness: **a green only ever
comes from a check that could have failed.** A judge (LLM-graded) verdict that
can't be falsified against an anchor or a deterministic guardrail is reported
`INCONCLUSIVE`, never `PASS`.

Read [references/case-format.md](references/case-format.md) before authoring a
suite, [references/assertions.md](references/assertions.md) for the full
assertion set, and [references/trust-architecture.md](references/trust-architecture.md)
before adding any `judge` assertion.

## Engine

litmus is a stdlib-only Python CLI (Python 3.10+). Installed as a Claude Code
plugin, `litmus` is already on the Bash tool's PATH (the plugin's `bin/litmus`),
and `/litmus:run`, `/litmus:gate` and `/litmus:new-case` call it. Elsewhere:

```bash
pip install git+https://github.com/OrenSegal/litmus   # provides the `litmus` command (not on PyPI yet)
# or, from a checkout:  python3 -m litmus.cli ...
```

Exit codes: 0 green / no regression, 1 red / regression, 2 the suite could not
be evaluated (bad file, path outside the suite, judge or capture error).
`litmus status <suite>` says how many runs were captured live versus written by
hand, which is what a green on that suite actually proves.

## The workflow

1. **Capture** what the target agent did into an `AgentRun` — the sole input the
   engine grades. Either let a real run write it:

   ```bash
   litmus capture "your task prompt" --model sonnet-5 --cwd path/to/skill \
       --out suite/runs/<case-id>/sonnet-5.json
   ```

   …or hand-author the JSON for offline tests (see case-format.md).

2. **Author cases** under `suite/cases/*.json` — one golden task each, with
   assertions. Push everything you can down to deterministic assertions; reach
   for `judge` only for genuinely subjective quality.

3. **Run**:

   ```bash
   litmus run suite/                 # red/green table, exit 1 on any FAIL
   litmus run suite/ --html out.html # + self-contained HTML report
   litmus run suite/ --judge claude  # also grade `judge` assertions via the Claude CLI
   ```

   `--judge claude` works on `run`, `gate`, `bless`, `matrix` and `index`.
   `--judge-model <id>` picks the judge model (default
   `claude-haiku-4-5-20251001`). The Claude CLI must be installed and either
   logged in or given `ANTHROPIC_API_KEY`; if it can't answer, the command
   exits 2 with the reason instead of reporting INCONCLUSIVE. Pass the same
   `--judge` setting to `bless` and `gate`, or judge assertions blessed as
   PASS will show up as regressions. The judge never grades runs produced by
   its own model: if a run's `meta.model` (or the suite `target.model`) is the
   judge model, that judge assertion is INCONCLUSIVE and no call is made, so
   pick a `--judge-model` that differs from the model under test. Runs with no
   known model are graded, with one warning on stderr.

4. **Baseline + gate** for CI — the ratchet only breaks the build on a
   *regression*, never on a fix or a new green case:

   ```bash
   litmus bless suite/                       # snapshot current result as baseline
   litmus gate  suite/ --baseline suite/baseline.json   # exit 1 on regressions
   ```

5. **Matrix** — answer "does this skill still work on the new model?" by tagging
   each run's `meta.model` and running:

   ```bash
   litmus matrix suite/ --reference opus-4.8   # case x model grid; exit 1 on cross-model regressions
   ```

## Rules when authoring

- **Assert invariants, not exact strings.** Model output is stochastic. Use
  `must_run`, `must_not`, `schema`, `equals` on a typed field, `resolves`,
  `grounded` — not brittle full-text matches. Set `samples: N` for anything
  flaky-prone; litmus reports pass-rates and flags flaky assertions.
- **A `judge` assertion is INCONCLUSIVE unless you pass `--judge claude`, by
  design.** It also needs at least one pass and one fail anchor. Don't "fix" an
  INCONCLUSIVE by loosening: add anchors and run with `--judge claude`
  (trust-architecture.md), or express the check deterministically.
- **Never let `bless` paper over a real failure.** It refuses to snapshot a
  live deterministic FAIL; fix the case instead.

## CI snippet

```yaml
- run: pip install git+https://github.com/OrenSegal/litmus
- run: litmus gate suite/ --baseline suite/baseline.json
```
