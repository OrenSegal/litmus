# Security

litmus grades captured agent runs and can invoke a judge model when you pass `--judge`.

- Report a vulnerability through GitHub's private advisory form on this repo, not a public issue.
- In scope: a crafted suite, case or run file that makes litmus execute code, read files outside the suite directory, or send data to a model you did not select.
- Out of scope: a green result that comes from assertions you wrote too loosely. Calibration exists to catch that; see `LITMUS_SPEC.md`.
