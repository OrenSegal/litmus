---
name: changelog
description: Write release notes from a git diff. Use when the user asks for release notes or a changelog entry.
---

# changelog

Write release notes for the diff the user gives you.

- Group changes under Added, Changed and Fixed.
- Never write a "Features" heading when the diff only touches tests or CI config; say "No user-facing changes." instead.
- Always end with the version number from `package.json`.
- Keep each bullet under 20 words.
