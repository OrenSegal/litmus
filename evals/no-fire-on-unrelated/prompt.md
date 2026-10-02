---
name: no-fire-on-unrelated
description: An ordinary coding request must not load the litmus skill.
tags: [trigger, negative]
max_turns: 4
timeout_seconds: 120
allowed_tools: [Read, Glob, Grep, Skill]
---

Write a Python function `slugify(title: str) -> str` that lowercases a title,
replaces runs of non-alphanumeric characters with a single hyphen, and strips
leading and trailing hyphens. Just the function, no tests.
