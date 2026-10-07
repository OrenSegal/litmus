# litmus

**Can your eval fail?** Mutation testing for LLM and agent eval suites.

An eval suite that never goes red tells you nothing. litmus breaks the thing
under test on purpose (deletes an instruction from a skill, inverts a rule,
swaps two tool names, truncates the prompt, plants a wrong number) and runs
your evals against each broken copy. The **mutation score** is the share of
broken copies your evals caught. Every mutant they missed is listed with its
diff, so you know which part of your prompt is untested.

It also finds graders that cannot fail at all, offline and for free, before
you spend anything on runs.

litmus runs on top of [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals),
Claude Code's plugin eval runner. It does not replace it: the runner runs and
grades, litmus asks whether those grades mean anything. The adapter interface
is open so promptfoo and other runners can follow (see [SPEC.md](./SPEC.md)).

> The rule: a mutant only counts as killed when a trusted run shows it.
> INCONCLUSIVE (a crashed, partial or rate-limited run, a baseline that was
> never green, a stale mutant) never counts as killed.

## What it finds

| Check | Cost | Finds |
|---|---|---|
| `litmus vacuity` | free, offline | Graders that provably cannot fail (`tool_used` with `min: 0` and no `max`; a regex that matches the empty string), and cases a do-nothing run would turn green (empty reply, "Done.", a refusal, the prompt echoed back). |
| `litmus audit` | free, offline | Reads results you already have. The no-plugin arm of a two-arm `claude plugin eval` run is a free "delete the whole plugin" mutant: cases that stay green without the plugin can't tell it from nothing. |
| `litmus mutate` | one eval run per mutant | Mutation score, surviving mutants with diffs, per-operator breakdown, JSON and HTML report. |

## Quickstart

```bash
pip install git+https://github.com/OrenSegal/litmus     # Python 3.10+, no dependencies
# optional, for case.yaml files that list graders: pip install "litmus-ci[yaml] @ git+https://github.com/OrenSegal/litmus"

cd my-plugin                               # has .claude-plugin/plugin.json and evals/
litmus vacuity .                           # free: graders that cannot fail
litmus audit evals/results/*/aggregate-result.json   # free: reuse past two-arm runs
litmus mutate . --dry-run                  # free: list the mutants and the cost estimate
litmus mutate . --max-mutants 10 --runs 1 --max-cost-usd 5 --yes   # real run
```

A real run calls `claude plugin eval` once for the baseline and once per
mutant, each against a temp copy of the plugin, on your Claude Code
credential. That is why it needs `--yes`. Pass the same `--allow-tools`,
`--scaffold` and `--model` flags you pass to `claude plugin eval`.

Try it without spending anything, on the bundled demo (a changelog skill with
a suite that has deliberate weak spots, and simulated recorded results; no
model is called):

```bash
git clone https://github.com/OrenSegal/litmus && cd litmus
python3 -m litmus.cli mutate examples/demo-plugin --replay-results examples/demo-recordings
```

```
vacuity: 1 vacuous, 0 always-fail, 2 null-pass grader(s); 1 null-green case(s), 1 judge-only case(s)
  WEAK_RUBRIC   ends-with-version/mentions-version: rubric never says what FAILs (heuristic)
  VACUOUS       ends-with-version/read-package-json (tool_used): min: 0 with no max accepts any number of calls, including none
  NULL_GREEN    no-todo-left [ablation-none]: green on a do-nothing run (silent, done, refusal, echo)
baseline: ok; green cases: tests-only-diff, ends-with-version, no-todo-left
mutation score: 50% (5 killed / 10 run; 5 survived, 0 inconclusive, 0 not run)
  SURVIVED     delete-instruction:skills/changelog/SKILL.md:2:380a077e: delete line 8: - Always end with the version number from `package.json`.
  SURVIVED     invert-rule:skills/changelog/SKILL.md:1:55484473: line 8: 'Always' -> 'Never' in: - Always end with the version number from `package.json`.
  SURVIVED     wrong-fact:skills/changelog/SKILL.md:0:2c9c4b4a: line 9: '20' -> '40' in: - Keep each bullet under 20 words.
  ...
```

The survivors say it plainly: nothing in the suite checks the version rule
or the bullet length. The `ends-with-version` case looks like it does, but its
deterministic grader cannot fail and its judge rubric never says what fails.

Output lands in `.litmus/<timestamp>/`: `report.json`, `report.html`, and
`mutants.json`, the exact mutants that ran. Pass that file back with
`--mutants` to replay the same mutants later (for example after a model
release); a mutant whose source file changed since is reported stale, not run.

## Mutation operators

| Operator | Breaks |
|---|---|
| `delete-body` | the whole body; frontmatter kept |
| `delete-instruction` | one directive line or list item |
| `invert-rule` | one rule word: never/always, must/must not, do not/do |
| `swap-tool-names` | two tool names or two inline-code commands, everywhere |
| `truncate` | the second half of the body |
| `wrong-fact` | one number or direction word (20 to 40, before to after) |
| `drop-description` | the frontmatter description, so the skill should stop triggering |

All are deterministic and skip code fences. LLM-written mutants are supported
as recorded manifests replayed byte for byte; litmus does not generate them
itself yet. Details, scoring and exit codes: [SPEC.md](./SPEC.md).

## CI

Exit 0 when the mutation score is at or above `--min-score` (default 0.5) and
no grader is vacuous; 1 when the suite fails that bar; 2 when litmus could not
evaluate (bad suite, untrusted or never-green baseline). `litmus vacuity` and
`litmus audit` are free, so they fit on every PR; run `mutate` on a schedule
or before a release.

## Dogfood: my own plugin suites

Run on 2026-10-06 against the eval suites of four of my Claude Code plugins
(sous, cited, scoped, deuce): 9 cases, 18 graders. Only the free checks were
run; no model was called.

- **No proven-vacuous graders, no null-green cases.** The obvious failure
  that retired litmus 0.2 is not present in these suites.
- **Under the runner's default two-arm scoring, all 9 cases can only go red
  through an LLM judge.** The deterministic graders that count are either
  excluded in two-arm mode (`tool_used: Skill`, `arm: with-only`) or absence
  guards that a do-nothing run passes. Whether these suites can fail rests
  entirely on a Haiku judge reading a rubric. (`litmus vacuity`,
  `with-without` mode.)
- **2 of the 6 non-negative cases with saved two-arm results stayed green
  with the plugin removed** in their latest full run (deuce has no saved
  results): sous `test-audit-deletion` (1.00 without the
  plugin) and scoped `deny-means-coordinate` (1.00 without the plugin, in both
  runs on record). cited `invalid-claims-file` did the same in one of its two
  runs. These evals do not measure the plugin. (`litmus audit` over the
  saved `aggregate-result.json` files.)

Not yet done: a paid `litmus mutate` run. The command for cited, about $2.70
at list price for 8 mutants:

```bash
litmus mutate ../cited --files 'skills/*' --max-mutants 8 --runs 1 --max-cost-usd 5 \
  --allow-tools Bash Write "WebFetch(domain:www.rfc-editor.org)" "WebFetch(domain:archive.org)" --yes
```

## Why litmus was retired, and what it became

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

## Limits

- **Survivors are not always gaps.** Some mutants are equivalent: deleting a
  redundant sentence changes nothing the model does. Read the list; do not
  chase 100%.
- **Noise.** With `--runs 1` a flaky case can fake a kill. Use `--runs 3` for
  numbers you publish; the report shows `decided_score` (killed over killed
  plus survived) next to the strict score.
- **Prose only.** Hooks, scripts and MCP servers are not mutated. A plugin
  whose behavior lives in a hook (the sous guard) gets little from prose
  mutants.
- **Probes approximate the runner.** litmus re-implements the four
  deterministic grader types from the published docs and translates
  JavaScript regexes to Python; anything it cannot translate is UNKNOWN, never
  a pass. The real trace's init line and MCP mock calls are not modelled.
- **Cost.** One full suite run per mutant. 20 mutants on a 3-case suite at 3
  runs per case is about 189 agent runs.
- **One adapter.** Only `claude plugin eval` today. The promptfoo adapter is
  specified, not built.

## Development

```bash
python3 -m unittest discover -s tests -t .   # offline, no model, no network
ruff check litmus tests examples && mypy
python3 examples/record_demo.py              # after editing the demo skill
```

MIT. Oren Segal.
