# Trust architecture — why a judge is INCONCLUSIVE by default

Every eval tool has the same silent failure mode: the judge is a model, and a
model scoring its own kind of work rubber-stamps it. Litmus's rule:

> A green only ever comes from a check that could have failed. A judge verdict
> that can't be falsified against an anchor or a deterministic guardrail is
> `INCONCLUSIVE`, never `PASS`.

A `judge` assertion earns a `PASS` only if **all four** guardrails hold:

1. **Anchored calibration.** The rubric ships with pinned pass/fail exemplars.
   Before grading the real output, the judge re-grades the anchors. If it
   misgrades a known anchor, its verdict is void → `INCONCLUSIVE`. A judge that
   can't tell fixed-good from fixed-bad doesn't get to bless anything.
   Anchors are required: with no anchors, or without at least one `pass` and one
   `fail` anchor, the assertion is `INCONCLUSIVE` and the real output is never
   graded. A pass-only set can't catch a judge that always says PASS.

   ```json
   { "judge": {
       "rubric": "The opener references a specific thing the person actually posted.",
       "anchors": [
         { "output": "fixtures/good_opener.json", "expect": "pass" },
         { "output": "fixtures/mailmerge.json",   "expect": "fail" }
       ],
       "panel": 3
   } }
   ```

2. **Adversarial panel.** `panel: N` (default 1) calls of the configured judge
   vote; **ties and disagreement default to FAIL.** `ClaudeJudge` is prompted to
   refute: find a concrete violation and answer FAIL, or PASS only if it can't.
   The N calls use the same judge and prompt, so they are repeated samples, not
   independent judges.

3. **Deterministic floor.** A judge PASS can never override a deterministic FAIL
   on the same case. Checkable truth outranks opinion.

4. **No self-grading.** The judge model is decoupled from the target model and
   sees only `{artifact, rubric}`, never "you produced this." Litmus enforces
   the model side too: before any judge call, it compares the judge model
   (`--judge-model`) with the model that produced the run (the run's
   `meta.model`, else the suite or case `target.model`). If they are the same
   model, the judge is not called and the assertion is `INCONCLUSIVE`. Ids are
   compared after normalizing: lowercase, drop provider prefixes (`anthropic/`,
   Bedrock `us.anthropic.`), date suffixes (`-20251001`, `@20251001`), Bedrock
   `-v1:0` and `-latest`, turn `.` into `-`, drop `claude-`. So
   `claude-haiku-4-5-20251001` and `haiku-4.5` are the same model, and a bare
   alias like `haiku` matches every haiku. If the producing model is unknown
   (no `meta.model`, or `default`, and no `target.model`), the run is graded as
   before and Litmus prints one warning to stderr per command. Tag your runs
   with `meta.model` so the check can run. The exact normalization rule is in
   `LITMUS_SPEC.md` §6. From Python, a judge callable without a `model`
   attribute skips the check (graded, with a warning), and warnings are
   collected on `EvalContext.warnings`; the CLI is what prints them.

## Wiring a judge

From the command line, add `--judge claude` to `run`, `gate`, `bless`,
`matrix` or `index`:

```bash
litmus run suite/ --judge claude
litmus gate suite/ --baseline suite/baseline.json --judge claude --judge-model <id>
```

This uses `litmus.judge.ClaudeJudge`, which calls `claude -p` once per anchor
and once per panel vote. The Claude CLI handles auth: your `claude` login, or
`ANTHROPIC_API_KEY` if set. The default judge model is
`claude-haiku-4-5-20251001`.

Without `--judge`, no judge is built and no model is called, so every `judge`
assertion is INCONCLUSIVE. If you ask for a judge and it can't answer (`claude`
not on PATH, a non-zero exit such as an auth error, or an empty reply), the
command prints the reason and exits 2. It does not report INCONCLUSIVE, because
that would hide a setup problem behind a verdict.

From Python, the engine takes a `JudgeFn(artifact, rubric) -> bool` on its
`EvalContext(judge=...)`. In tests, `litmus.judge.ScriptedJudge(rule)` is a
deterministic fake so the guardrails are provable offline.

## The tell

If you find yourself loosening a rubric to turn `INCONCLUSIVE` into `PASS`,
stop — you're removing the falsifiability that makes the green mean anything.
Either add anchors that pin the judgment, or express the check deterministically
(`schema`, `must_not`, `equals`, `grounded`).
