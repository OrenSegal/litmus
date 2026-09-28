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
   sees only `{artifact, rubric}` — never "you produced this."

## Wiring a judge

The engine takes a `JudgeFn(artifact, rubric) -> bool` on its `EvalContext`.
`litmus.judge.ClaudeJudge` backs it with the Claude CLI (its own auth, no API
key). In tests, `litmus.judge.ScriptedJudge(rule)` is a deterministic fake so
the guardrails are provable offline.

## The tell

If you find yourself loosening a rubric to turn `INCONCLUSIVE` into `PASS`,
stop — you're removing the falsifiability that makes the green mean anything.
Either add anchors that pin the judgment, or express the check deterministically
(`schema`, `must_not`, `equals`, `grounded`).
