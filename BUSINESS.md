# Business

Positioning and monetization for litmus after the October 2026 pivot.
Discipline unchanged: **the open-source CLI is distribution, not revenue;
freeze new mechanisms until a real run logs a real outcome.**

## Position

"Can your eval fail?" Mutation testing for LLM and agent eval suites. It sits
on top of eval runners (`claude plugin eval` first, promptfoo next) instead of
competing with them. Runners answer "did it pass?"; litmus answers "would it
have failed if the prompt were broken?"

## Wedge to general

- **Layer 1 (wedge):** plugin and skill authors on `claude plugin eval`. Free
  `vacuity` and `audit` on every PR; `mutate` before a release or after a
  model release.
- **Layer 2 (general):** any team with an LLM eval suite (promptfoo, Inspect,
  in-house). Same operators and scoring, one adapter per runner.

## Moat ranking (highest to lowest)

1. **Survivor corpus.** Every run labels which prompt edits evals miss, by
   operator and grader type. Compounds; hard to copy late.
2. **Public "Can your eval fail?" index.** Mutation scores of public plugin
   suites, rerun on each model release. Marketing and credibility.
3. **Trust rules.** INCONCLUSIVE never kills; probes never call a judge;
   mutants are recorded and replayable.
4. **The CLI.** A lead, not a moat. Free and open.

## Monetization ladder (do NOT build yet; freeze until data)

1. Free OSS: `vacuity`, `audit`, `mutate`.
2. Hosted runs: mutation runs on a schedule and on each model release, with
   history and a PR check. Team tier priced against eval platforms
   ($100 to $250 per month; comps: Braintrust $249, Langfuse $199, LangSmith
   $39 per seat).
3. More adapters (promptfoo first) and an LLM mutant generator with recorded,
   replayable output.

## First act

One paid `litmus mutate` run on a real suite (cited is ready, command in the
README), published with its survivors, before any new mechanism.
