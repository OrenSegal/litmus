# Changelog

## 0.3.0

litmus is now a mutation tester for eval suites ("Can your eval fail?"). The
0.2 regression engine is removed. See the README section "Why litmus was
retired, and what it became".

### Added

- `litmus mutate`: seven deterministic operators (`delete-body`,
  `delete-instruction`, `invert-rule`, `swap-tool-names`, `truncate`,
  `wrong-fact`, `drop-description`), a baseline run and one
  `claude plugin eval --ablation none` run per mutant, a mutation score where
  INCONCLUSIVE never counts as killed, JSON and HTML reports, and a replayable
  `mutants.json` manifest (also the format for recorded LLM-written mutants).
- `litmus vacuity`: offline proofs that a grader cannot fail, and null probes
  (empty reply, "Done.", refusal, echoed prompt) that find cases a do-nothing
  run passes, in both scoring modes.
- `litmus audit`: reads existing `aggregate-result.json` files and reports
  cases that stayed green with the plugin removed, and graders that never failed.
- Adapter interface (`litmus/adapters/base.py`) with a `claude-plugin-eval`
  adapter; runners are injected, so tests and the demo never call a model.
- `examples/demo-plugin` with simulated recordings; `SPEC.md`.

### Removed

- The 0.2 engine and its commands: `run`, `gate`, `bless`, `matrix`, `index`,
  `capture`, `calibrate`, `status`, the assertion library, the judge, the
  example suites, `LITMUS_SPEC.md` and `calibration/`. They remain in git
  history at v0.2.0.

## 0.2.x (never released)

### Changed

- One description for the package, npm installer and plugin, checked by a test.
- `LITMUS_SPEC.md` is now the engine's design document only, and matches the
  code (`samples` defaults to 1; `ordering`, `capture`, `calibrate` and
  `status` are documented).
- `litmus capture` now writes the run's `transcript` too; it was parsed and
  then dropped from the file.
- `litmus index` output is headed `litmus index`.
- `pyproject.toml` reads the version from `litmus.__version__`.

### Removed

- The blank `calibration/WRITEUP.md` template.
- `litmus.adapters.transcript` and `AgentRun.load`, which nothing used.
  Run files are read by `litmus.case.load_runs`.

## 0.2.0

Security and correctness hardening. Every fix below has a test in
`tests/test_hardening.py` that failed before the fix.

### Fixed

- A crafted case could read any file on disk through `runs:`, `schema.ref`
  or a judge anchor (and send the anchor to the judge model). Every path a
  suite names must now resolve inside the suite directory, symlinks included.
- `matches` with a catastrophic regex (e.g. `^(a+)+$`) hung the grader. The
  search is now time-boxed (`timeout`, default 2 s) and a timeout is a FAIL.
- Vacuous greens: `grounded` passed when no source was an http(s) URL and
  silently dropped claims when claim and source counts differed; `budget: {}`
  passed. These now FAIL or are INCONCLUSIVE.
- A case with a SKIP assertion could never be green, which hid its later
  regressions from the gate. SKIP no longer affects the roll-up; a case with
  fewer runs than its `samples` is INCONCLUSIVE.
- `gate` passed when baseline cases disappeared, when an assertion went from
  PASS to FAIL on an already-red case, and against a file that was not a
  baseline at all. All three are now caught.
- `matrix --reference` with an unknown model exited 0.
- Malformed suite, case and run files, and duplicate case ids, raised a
  traceback with exit 1, indistinguishable from a red result. They now exit 2
  with a one-line message (or fail only the affected case, for a bad run file).
- The judge read any first line containing "PASS" as a pass, so
  "FAIL - would not PASS review" was a PASS. The first word now decides, and an
  unparseable reply is a judge error.
- The judge and `capture` passed the prompt in argv, which failed with E2BIG on
  large artifacts. Both now use stdin.
- `capture` wrote a run file even when the Claude CLI failed (e.g. a bad API
  key). It now exits 2 and writes nothing.
- The fetcher built a User-Agent header but never sent it.
- `litmus --version` reported 0.1.0 while the manifests said 0.1.1.

### Added

- `evals/`: two offline `claude plugin eval` cases for the litmus skill (fires
  and writes a case; does not fire on an unrelated request). Not run in CI.
- `litmus status <suite>`: captured versus fixture runs, missing samples, judge
  coverage and baseline provenance. Captured runs are stamped
  `meta.captured_by` and `meta.captured_at`.
- `scripts/capture-real-run.sh` to capture a real run for a case (costs money;
  never run in CI).
- Plugin slash commands `/litmus:run`, `/litmus:gate`, `/litmus:new-case`, and
  `bin/litmus`, which runs the bundled engine without a pip install.
- The judge runs with tools disabled, no MCP servers, no saved session and an
  empty temporary working directory.
- Baselines record the Litmus version and judge model; `gate` warns on a judge
  or suite-name mismatch.
- Type hints throughout (`py.typed`, strict mypy), ruff, CI on Python
  3.10-3.13, an 85% branch-coverage floor, strict plugin validation, a release
  workflow that attaches the sdist and wheel to a GitHub Release, dependabot,
  CONTRIBUTING and CODE_OF_CONDUCT.

### Changed

- Requires Python 3.10 or newer.
- `--drift-tol` must be between 0 and 1.

## 0.1.1

- CI runs `claude plugin validate` against the plugin manifest.
- Added SECURITY.md.

## 0.1.0

- Engine, `claude-code` capture adapter, judge calibration, matrix and index.
