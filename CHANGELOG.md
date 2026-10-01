# Changelog

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
