---
type: regex
target: last_message
pattern: '^#+\s*Features'
flags: m
match: not_contains
---

A tests-and-CI diff must not get a Features heading.
