# Contributing

Thanks for helping. litmus has one rule that every change must keep:
**a green only ever comes from a check that could have failed.**

## Setup

```bash
git clone https://github.com/OrenSegal/litmus && cd litmus
python3 -m unittest discover -s tests -t .   # offline, no dependencies
pip install -e ".[dev]"                     # optional: coverage, ruff, mypy, build
```

Python 3.10 or newer. The engine is stdlib-only; keep it that way.

## Before you open a pull request

```bash
python3 -m unittest discover -s tests -t .
python3 -m litmus.cli gate examples/signal-scout --baseline examples/signal-scout/baseline.json
ruff check litmus tests
mypy
coverage run -m unittest discover -s tests -t . && coverage report   # floor: 85%
claude plugin validate . --strict                                    # if you touched the plugin
```

CI runs all of these on Python 3.10 to 3.13.

## Rules for changes

- **Keep the engine pure.** `litmus/` grades JSON and never calls a model.
  Only adapters (`litmus/adapters/`, `litmus/judge.py`) shell out, and tests
  mock them. No test may call a real model or the network beyond loopback.
- **Test first for bugs.** Add a test that fails on `main`, then fix it.
- **Every new assertion gets a test that shows it can FAIL**, not only PASS.
- **No vacuous greens.** If an assertion has nothing to check, it is SKIP or
  INCONCLUSIVE, never PASS.
- **Paths from suites go through `litmus.case.suite_path`.** Nothing a case
  names may be read from outside its suite.
- **Exit codes are API:** 0 green, 1 red or regression, 2 could not evaluate.
- The version lives in `litmus/__init__.py`; `pyproject.toml` reads it from
  there. Change it there and in `package.json`, `.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`; a test fails until all agree.
- Add a line under the next version in `CHANGELOG.md`.

## Skill trigger evals

`evals/` holds `claude plugin eval` cases for the litmus skill itself: one that
should fire it and produce a litmus case, and one unrelated request that must not
fire it. They call a real model on your own credential, so they are not run in CI.
Run them by hand when you change `skills/litmus/SKILL.md`'s description:

```bash
claude plugin eval . --runs 3 --max-cost-usd 2
```

`claude plugin validate --strict` does not check `evals/`.

## Releases

Tag `vX.Y.Z` on `main`. The release workflow checks the tag against
`litmus.__version__`, runs the tests, builds the sdist and wheel, and attaches them to a
GitHub Release. Nothing is published to PyPI or npm automatically.

## Security

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
