---
name: litmus
description: >-
  Author and run red/green regression tests for a skill, system prompt, or tool
  definition. Use when someone wants to test prompt-ware behavior, catch a skill
  regression, check whether a skill still works on a new model, or pin golden
  tasks with assertions. Turns "did my edit make the agent better or worse?"
  from vibes into a red/green diff.
---

# Litmus — red/green CI for prompt-ware

Litmus tests the *behavior* of a skill, not its scripts. You pin golden tasks
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

Litmus is a stdlib-only Python CLI. Install once:

```bash
pip install litmus-ci        # provides the `litmus` command
# or, from a checkout:  python3 -m litmus.cli ...
```

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
   ```

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
  flaky-prone; Litmus reports pass-rates and flags flaky assertions.
- **A `judge` with no judge configured is INCONCLUSIVE, by design.** Don't
  "fix" it by loosening — either wire an anchored judge (trust-architecture.md)
  or express the check deterministically.
- **Never let `bless` paper over a real failure.** It refuses to snapshot a
  live deterministic FAIL; fix the case instead.

## CI snippet

```yaml
- run: pip install litmus-ci
- run: litmus gate suite/ --baseline suite/baseline.json
```
