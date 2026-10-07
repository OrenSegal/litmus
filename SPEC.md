# litmus spec

Version 0.3.0. litmus measures whether an eval suite can fail. It does this
two ways: it proves some graders can never fail (offline, free), and it breaks
the thing under test on purpose and checks whether the suite goes red
(mutation testing, one eval run per mutant).

The rule carried over from litmus 0.2: **a green only counts if it came from a
check that could have failed.** In mutation terms: a mutant only counts as
killed when a trusted run shows it, and INCONCLUSIVE never counts as killed.

## 1. Terms

- **Subject**: the prose that steers the model. For a Claude Code plugin:
  `skills/**/SKILL.md`, then `agents/**/*.md`, then `commands/**/*.md`, in that
  priority order. Never anything inside the eval directory.
- **Suite**: the eval cases and graders that test the subject.
- **Mutant**: a copy of the subject with one deliberate defect.
- **Baseline**: one run of the suite against an unmutated copy, with the same
  flags every mutant run uses.
- **Killed**: a case that was green on the baseline is red on the mutant.
- **Survived**: every baseline-green case stayed green. The suite did not
  notice the defect.
- **INCONCLUSIVE**: litmus could not trust the comparison. Never killed.

## 2. Mutation operators

All operators are deterministic: the same file gives the same sites in the
same order, and each mutant id is `operator:file:site:sha8`, where `sha8` is
the first 8 hex digits of the SHA-256 of the patched file. Body operators skip
fenced code blocks and never touch the frontmatter.

| Operator | Site | What it does |
|---|---|---|
| `delete-body` | 1 per file | Empty the body, keep the frontmatter. Evals that survive it do not depend on the prose at all. |
| `delete-instruction` | each directive line | Delete one list item or one line containing must, never, always, do not, should, only, required, before, after, refuse, ask. |
| `invert-rule` | each line with a rule word | Flip the leftmost rule word: never and always swap, must not becomes must, must becomes must not, do not becomes do, should and should not swap, cannot becomes can. |
| `swap-tool-names` | each adjacent pair | Swap two tool names (`Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`, `WebFetch`, `WebSearch`, `Skill`, `Task`, `Agent`) or two inline-code spans (commands, flags, paths) everywhere in the body. `$ARGUMENTS`-style placeholders are skipped. |
| `truncate` | 1 per file, 4+ body lines | Keep the first half of the body lines. |
| `wrong-fact` | each number or flip word | A plausible wrong fact: a number doubles (20 becomes 40), a year-sized number moves by 2 (1999 becomes 2001), or a directional word flips (before/after, first/last, true/false, allow/deny, include/exclude, increase/decrease, more/fewer, above/below). List numbering is skipped. |
| `drop-description` | 1 per file with a description | Replace the frontmatter `description` with `General helper.` so a skill should stop triggering. |

Limits: `--max-sites` (default 5) caps sites per operator per file;
`--max-mutants` (default 20) caps the total, chosen round-robin across
operators so every operator stays represented. `--files GLOB` restricts the
subject files.

### LLM-written mutants

LLM-written mutants are allowed but must be recorded before they are run.
litmus 0.3 ships the recording format and the replay path, not a generator.
A generator writes a manifest (section 5) with `operator: "llm:<name>"`, the
full patched file, the original file's SHA-256, and a `generator` object that
records how it was made (for example `{"kind": "llm", "model": "...",
"prompt": "...", "temperature": 0}`). `litmus mutate --mutants manifest.json`
replays it byte for byte. A mutant whose original file changed since it was
recorded is **stale** and reported INCONCLUSIVE without running.

## 3. Vacuity detection (offline)

Runs before any mutant, costs nothing, and needs no credentials.

### 3.1 Static proofs

| Finding | Rule |
|---|---|
| `VACUOUS` | `regex` with `match: contains` (default) whose pattern matches the empty string, on a non-file target. It passes on any output. |
| `VACUOUS` | `tool_used` with `min: 0` and no `max`. It accepts any number of calls, including none. |
| `ALWAYS_FAILS` | `regex` with `not_contains` or `count:0` whose pattern matches the empty string; `tool_used` with `min` above `max`. |
| `WEAK_RUBRIC` | `llm` or `baseline` grader whose rubric never mentions FAIL. Heuristic, reported, never fails CI. |

### 3.2 Null probes

Every case is graded against four synthetic runs that did no work. None has
tool calls or created files.

| Probe | Final message |
|---|---|
| `silent` | empty |
| `done` | `Done.` |
| `refusal` | `I can't help with that.` |
| `echo` | the case prompt, verbatim |

litmus re-implements the four deterministic grader types (`regex`,
`tool_used`, `tool_order`, `file_exists`) from the published docs to grade
probes. Patterns are JavaScript regexes; litmus translates named groups,
backreferences, `[^]` and flags, and treats `\d`, `\w`, `\b` as ASCII unless
the `u` flag is set. A pattern it cannot translate makes the grader UNKNOWN.
`llm` and `baseline` graders are always UNKNOWN on probes: litmus never calls
a judge for them.

Per grader: `NULL_PASS` if it passes on any probe, `DISCRIMINATES` if it fails
on all of them. Absence checks (`not_contains`, `count:0`, `max: 0`,
`exists: false`) are labelled `guard`: they are meant to pass when nothing
happens and are only useful next to a grader that requires the work.

Per case, in both scoring modes:

- `ablation-none`: every grader counts.
- `with-without` (the runner's default): `tool_used` on `Skill` and
  `arm: with-only` graders are excluded unless `arm: both`; if that would
  exclude everything, everything counts. This mirrors the docs' exclusion
  rule.

For each probe litmus computes the lowest and highest possible weighted score
(UNKNOWN graders counted as fail, then as pass) and compares both with the
threshold:

- `NULL_GREEN`: the lowest possible score on some probe meets the threshold.
  A run that did nothing would turn the case green. Proven, not estimated.
- `JUDGE_ONLY`: no probe is provably red; only a judge stands between a
  do-nothing run and green.
- `OK`: every probe is provably red.

Assumption flagged in the code: the `trace` target is modelled as compact
JSON messages with the user prompt first. The real trace also has an init
line listing tools and plugins, which probes do not model.

## 4. Adapter interface

An adapter connects litmus to one eval runner. It is a Python object with:

```python
class Adapter(Protocol):
    name: str
    def load_suite(self, target: Path) -> Suite
    def subject_files(self, suite: Suite) -> list[Path]   # priority order
    def results_rel(self, suite: Suite) -> str | None      # not copied into mutants
    def run(self, workdir: Path, suite: Suite, out_dir: Path, label: str) -> SuiteRun
    def describe_command(self, target: Path) -> str
```

`Suite`, `Case`, `Grader`, `SuiteRun` and `CaseRun` live in `litmus/models.py`
and carry no runner-specific fields. Adapters shell out through an injected
`CommandRunner(argv, cwd, timeout, label) -> CommandResult`; the real one is
`subprocess_runner`. Tests and the offline demo inject a fake or
`ReplayRunner`, so no test calls a model.

Vacuity probes only apply where the adapter's graders map to the four
deterministic types; another adapter maps its own assertion types onto
`Grader.type` or leaves them UNKNOWN.

### 4.1 `claude-plugin-eval` (shipped)

- Reads `evals/` (or `--eval-dir`, or the manifest's `experimental.evals`):
  `prompt.md` frontmatter and body, `case.yaml` (PyYAML needed for graders
  listed in it), `graders/*.md`. Skips `results/` and `mocks/`.
- Each run copies the plugin to a temp directory (skipping `.git`, caches and
  `evals/results`, symlinking `node_modules` and virtualenvs), applies at most
  one mutant, and runs:

  ```
  claude plugin eval <copy> --ablation none --runs N --threshold T \
    --trust-plugin --no-publish --json <out>/result.json --output-dir <out>/eval-output \
    [--eval-dir D] [--case GLOB] [--model M] [--judge-model J] [--scaffold] [--allow-tools ...]
  ```

  `--ablation none` on every run, baseline included, because the docs say it
  changes absolute scores; mixing modes would compare unlike numbers.
  `--trust-plugin` is needed because each copy is a new directory; only run
  litmus on plugins you would run yourself.
- Reads the `--json` result (`schemaVersion: 1`). Exit 0 and 1 are normal runs
  (1 means a case fell below threshold, which is what a killed mutant looks
  like). A missing result, `partial: true`, or any other exit code makes the
  run untrusted. A case whose runs hit an infrastructure error (rate limit,
  usage limit, auth, overloaded, 429, 5xx) or skipped paid graders under a
  cost ceiling is untrusted. A timeout or turn cap is behavior, not
  infrastructure: it is graded on what it produced, as the runner does.

### 4.2 Next adapters (not built)

- **promptfoo**: suite = `promptfooconfig.yaml`; subject = the prompt files it
  references; run = `promptfoo eval -c <copy> -o result.json`; per-case score =
  the share of assertions passed per test. `contains`, `icontains`, `regex`,
  `equals` and `not-*` map onto the regex grader for vacuity probes;
  `llm-rubric` maps to UNKNOWN.
- **Inspect / OpenAI evals**: same contract; subject is the system prompt or
  solver prompt file.

## 5. File formats

### 5.1 Mutants manifest (`mutants.json`)

```json
{
  "schema": "litmus.mutants/1",
  "litmus_version": "0.3.0",
  "root": "/path/to/plugin",
  "mutants": [{
    "id": "invert-rule:skills/x/SKILL.md:0:1a2b3c4d",
    "operator": "invert-rule",
    "file": "skills/x/SKILL.md",
    "site": 0,
    "description": "line 9: 'Never' -> 'Always' in: ...",
    "original_sha256": "...",
    "patched": "<full patched file>",
    "patched_sha256": "...",
    "generator": {"kind": "deterministic"}
  }]
}
```

`file` must be relative with no `..`. A `patched_sha256` that does not match
`patched` is rejected.

### 5.2 Report (`report.json`)

```json
{
  "schema": "litmus.report/1",
  "litmus_version": "0.3.0",
  "generated_at": "2026-10-06T23:00:00+00:00",
  "adapter": "claude-plugin-eval",
  "suite": {"root": "...", "eval_dir": "...", "cases": ["..."]},
  "threshold": 1.0,
  "runs_per_case": 1,
  "command": "claude plugin eval ...",
  "mutant_source": "deterministic operators: ...",
  "estimate_usd": 2.2,
  "vacuity": {"probes": {}, "graders": [], "cases": [], "counts": {}},
  "baseline": {"ok": true, "error": null, "cost_usd": 0.4, "cases": {}, "green_cases": []},
  "mutants": [{"id": "...", "operator": "...", "file": "...", "description": "...",
               "verdict": "KILLED|SURVIVED|INCONCLUSIVE|NOT_RUN", "reason": "...",
               "killed_by": [], "case_scores": {}, "cost_usd": 0.1, "diff": "...", "generator": {}}],
  "score": {"mutation_score": 0.5, "decided_score": 0.5, "killed": 5, "survived": 5,
            "inconclusive": 0, "not_run": 0, "total_run": 10, "by_operator": {}},
  "dry_run": false,
  "spent_usd": 1.2,
  "exit_code": 1
}
```

`report.html` renders the same data as one self-contained page (no external
requests, light and dark): score tiles, the vacuity table, every mutant with
its verdict, reason and diff, and the exact command.

### 5.3 Audit (`litmus audit --json`)

Per `aggregate-result.json`: per case `score`, `score_without`, `delta`,
`negative`, `indicators` (graders with `scored: false`) and `findings`:

- `PLUGIN_REMOVAL_SURVIVED`: `scoreWithout` at or above the threshold. The
  no-plugin arm is a free delete-everything mutant, and it survived. Marked
  expected for a negative case (a scored "Skill not invoked" check, or only
  absence checks).
- `NEVER_FAILED`: a scored grader that passed in every run of both arms.
  Observed, not proven.

## 6. Scoring

```
mutation_score = killed / (killed + survived + inconclusive)
decided_score  = killed / (killed + survived)          # shown, never gated on
```

A mutant is KILLED when, in a trusted mutant run, at least one case that was
green on a trusted baseline scores below the threshold. A real kill on one
case is not undone by an untrusted result on another. It is INCONCLUSIVE
when the baseline is untrusted, no case is green on the baseline, the mutant
run is untrusted, a baseline-green case is missing or untrusted in the mutant
run (and nothing was killed), or the mutant is stale. NOT_RUN (budget) is
listed and left out of both scores.

With `--runs 1` a flaky case can fake a kill. Use `--runs 3` for a number you
will publish, and read `decided_score` next to `mutation_score`.

## 7. CLI and exit codes

```
litmus mutate   <plugin> [--dry-run] [--yes] [--operators a,b] [--files GLOB]
                [--max-mutants 20] [--max-sites 5] [--mutants manifest.json]
                [--runs 1] [--threshold 1.0] [--min-score 0.5] [--max-cost-usd X]
                [--model M] [--judge-model J] [--allow-tools ...] [--scaffold]
                [--case GLOB] [--eval-dir D] [--out DIR] [--keep] [--allow-vacuous]
                [--replay-results DIR]
litmus vacuity  <plugin> [--json] [--threshold T] [--case GLOB] [--eval-dir D]
litmus audit    <aggregate-result.json>... [--json]
litmus operators
```

A real `mutate` run needs `--yes`, because it calls `claude plugin eval`
once for the baseline and once per mutant on your credential.
`--max-cost-usd` stops launching mutants once the next one would pass the
budget, estimated from the baseline's real cost per run.

| Exit | `mutate` | `vacuity` | `audit` |
|---|---|---|---|
| 0 | score at or above `--min-score` and no vacuity failure | no vacuity failure | no unexpected finding |
| 1 | score below `--min-score`, or a vacuity failure (VACUOUS, ALWAYS_FAILS, NULL_GREEN) unless `--allow-vacuous` | a vacuity failure | an unexpected finding |
| 2 | could not evaluate: bad suite or manifest, missing `--yes`, untrusted baseline, or no green baseline case | bad suite | unreadable or wrong-schema file |

A `--dry-run` exits 0 or 1 on vacuity alone and runs nothing.

## 8. What litmus does not do

- It does not mutate code (hooks, scripts, MCP servers). Use a code mutation
  tool for those. A plugin whose behavior lives in a hook (sous's guard) gets
  little from prose mutants.
- It does not prove a surviving mutant is a real gap. Some mutants are
  equivalent (deleting a redundant line changes nothing the model does). Read
  the survivor list; do not chase 100%.
- Probes do not model the real trace's init line or MCP mock calls.
- It never calls a judge itself.
