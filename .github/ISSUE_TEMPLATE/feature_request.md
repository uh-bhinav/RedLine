---
name: Feature request
about: Propose something RedLine doesn't do yet
title: ''
labels: enhancement
assignees: ''
---

**What's missing, and why it matters**
Describe the gap. If it's one of the five Phase 4 novelty features (ARS,
behavioural diff, chaos engineering, load testing, failure mining), check
`docs/architecture-roadmap.md` first — there may already be a design for it.

**Which phase does this belong to?**
See `docs/architecture-roadmap.md`. An item belongs in the current phase only if a
later phase's feature has a hard dependency on it — see §0 for why that rule exists.

**Would this change a STABLE CONTRACT?**
`JobQueue`, `AgentAdapter`, `LLMRateLimiter.acquire()`, or the pure gate/ARS
functions. If yes, say how — a new signature is a much bigger conversation than a
new implementation.

**Proposed approach** (optional)
If you have one. Not required — "here's a gap" is a useful issue on its own.
