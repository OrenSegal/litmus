# Security

litmus grades captured agent runs and can invoke a judge model when you pass `--judge`.

- Report a vulnerability through GitHub's private advisory form on this repo, not a public issue.
- In scope: a crafted suite, case or run file that makes litmus execute code, read files outside the suite directory, or send data to a model you did not select.
- What leaves your machine, and only when you ask: `--judge claude` sends the rubric and the graded artifact (and each anchor file) to `claude -p` over stdin, with tools disabled, no MCP servers, no saved session and an empty temporary working directory. `litmus capture` sends your prompt the same way and runs the agent with whatever tools your CLI settings allow, in the `--cwd` you give it. `resolves` and `grounded` fetch the http(s) URLs found in the run's output; those URLs come from the model, so run untrusted suites where outbound requests to internal hosts don't matter.
- Hardened in 0.2.0: every path a suite names must resolve inside the suite directory (symlinks included); `matches` regexes are time-boxed; YAML loads with `safe_load`; the fetcher refuses non-http(s) schemes.
- Out of scope: a green result that comes from assertions you wrote too loosely. Calibration exists to catch that; see `LITMUS_SPEC.md`.
