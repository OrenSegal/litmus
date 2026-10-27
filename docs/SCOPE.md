# Scope

litmus is the check on top of an eval runner. It asks whether a suite can
fail, and measures how much of the prompt the suite actually covers. It does
not run or grade evals: [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals)
does that, and litmus drives it through an adapter (see [SPEC.md](../SPEC.md)).

A suite's greens are only as good as its ability to go red, and runners do not
measure that. The cheapest case to catch is a grader that cannot fail at all:
an absence assertion such as `must_not: {field: "$.segments[*].opener"}`
passes on any output without that field, including an empty one. litmus finds
graders like that offline, before any paid run.
