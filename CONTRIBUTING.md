# Contributing

Thanks for helping. litmus has one rule that every change must keep:
INCONCLUSIVE never counts as killed, and nothing litmus cannot evaluate
counts as a pass.

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
python3 -m litmus.cli mutate examples/demo-plugin --replay-results examples/demo-recordings --allow-vacuous --quiet
ruff check litmus tests examples
mypy
coverage run -m unittest discover -s tests -t . && coverage report   # floor: 85%
claude plugin validate . --strict                                    # if you touched the plugin
```

CI runs all of these on Python 3.10 to 3.13.

## Rules for changes

- **No test calls a model or `claude`.** Adapters take an injected runner;
  tests use `tests/helpers.FakeRunner` or `ReplayRunner`.
- **Operators are deterministic.** Same input, same sites, same ids. Anything
  model-written goes through a recorded manifest.
- **Test first for bugs.** Add a test that fails on `main`, then fix it.
- **Exit codes are API:** 0 pass, 1 the suite failed the bar, 2 could not evaluate.
- The version lives in `litmus/__init__.py`; `pyproject.toml` reads it from
  there. Change it there and in `package.json`, `.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`; a test fails until all agree.
- If you edit `examples/demo-plugin`, run `python3 examples/record_demo.py`.
- Add a line under the next version in `CHANGELOG.md`.

## Releases

Tag `vX.Y.Z` on `main`. The release workflow checks the tag against
`litmus.__version__`, runs the tests, builds the sdist and wheel, and attaches them to a
GitHub Release. Nothing is published to PyPI or npm automatically.

## Security

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
