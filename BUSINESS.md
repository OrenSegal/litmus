# Business

Positioning and monetization for Litmus. Discipline mirrors signal-scout:
**the open-source CLI is distribution, not revenue; service-first; freeze new
mechanisms until a real run logs a real outcome.**

## Wedge → general

- **Layer 1 (wedge):** pytest for skills — regression CI. Every skill / plugin /
  prompt author. Sells on *"stop shipping untested prose."*
- **Layer 2 (general):** a verification harness for any agent claim.
  `verify_sources.py` was the first hand-built instance; Litmus generalizes it.

## Moat ranking (highest → lowest)

1. **Regression-corpus flywheel** — every user's suite run is labeled behavioral
   data. Compounds; uncopyable late.
2. **Hallucination Index** — a recurring public leaderboard of shipped skills ×
   models (which regress, on which model, this week). Marketing engine + layer-2
   credibility. `litmus index` is the prototype.
3. **Trust architecture** — the anchored-judge guardrails (§6). Hard-to-copy
   engineering; the reason a Litmus green means something a thin runner's doesn't.
4. **The CLI** — a lead, not a moat. Free and open.

## Monetization ladder (do NOT build yet — freeze until data)

1. Free OSS: `litmus run | gate | matrix`.
2. Hosted CI: runs the matrix on every PR, dashboards drift, gates merges.
3. Private index: a team's own skills benchmarked continuously against releases.
4. Claim-verification API (layer 2): `verify_sources.py` as a service — biggest
   market, last to build.

## First act

One real suite, gated in CI, with logged outcomes — before any new mechanism.
`examples/signal-scout/` is case study #1: it ports `verify_sources.py`'s
guarantees into Litmus assertions.
