## What and why

## How it was checked

- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] Bug fix: a test that failed before this change is included
- [ ] New assertion or check: a test shows it can FAIL, not only PASS
- [ ] `ruff check litmus tests` and `mypy` are clean
- [ ] Plugin files changed: `claude plugin validate . --strict` passes
- [ ] `CHANGELOG.md` updated

## Anything not verified

<!-- e.g. "not run against a real model", "only tested on macOS" -->
