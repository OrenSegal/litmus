# History: why litmus 0.2 was retired, and what it became

litmus 0.2 (October 2026) was a red/green regression harness for skills and
prompts. It graded captured agent runs against deterministic assertions and an
anchored LLM judge, under one rule: a green only ever comes from a check that
could have failed.

It broke its own rule. On 2026-10-02 I retired it from the sous marketplace
with this note: "its deterministic assertions can pass when they could never
fail (four assertions that cannot fail gave 1/1 green), and `claude plugin
eval` covers the rest." The judge path was guarded: an unanchored judge was
INCONCLUSIVE, never PASS. The deterministic path was not. An absence
assertion such as `must_not: {field: "$.segments[*].opener"}` passes on any
output that has no such field, including an empty one. Re-running the old
example suites today against an empty run, 3 of their 10 assertions still
pass, all `must_not`. I can't reconstruct which four assertions the original
note counted, so treat that number as the note's, not as re-verified.

Two lessons came out of it:

1. A suite's greens are only as good as its ability to go red, and nobody
   measures that. Not my old tool, not the runners.
2. Running and grading is a solved problem now that `claude plugin eval`
   exists. Competing with the platform's own runner is a losing position.

So litmus is now the missing check on top of the runner: it asks whether the
suite can fail, and measures how much of the prompt it actually covers. The
old engine (assertions, judge, calibrate, matrix, index, capture) is removed;
`git log` has it.
