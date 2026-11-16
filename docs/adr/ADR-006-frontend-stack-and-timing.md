# ADR-006: Frontend stack (Vite + React + TypeScript) and deferred rewrite

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** Abhinav Mahesh Gurkar

---

## Context

`apps/dashboard/` is 546 lines of plain JavaScript: Vite + React 18 + React Router, three read-only
pages (`AgentsList`, `AgentDetail`, `RunDetail`), hand-rolled `fetch()` with no auth header, no
state library, no charting library, and a single 165-line `index.css`.

It is a competent Phase 1 placeholder and it is not the product's dashboard. Foundational document
§7 specifies the dashboard as *"see eval results, behavioural diffs, ARS trend over time, production
failure clusters."* The current app can display exactly one of those four. Phase 4 adds ARS trends,
behavioural diffs, chaos results, load-test reports and failure clusters — five new data surfaces,
none of which exist as APIs yet.

Two questions had to be answered: **what stack**, and **when**.

## Decision

### Stack: Vite + React + TypeScript + TanStack Query + Tailwind + shadcn/ui + Recharts

**TypeScript is the load-bearing choice.** FastAPI already emits an OpenAPI schema derived from the
Pydantic response models in `apps/api/schemas/`. Generating the client types from that schema in CI
(`openapi-typescript`) means a backend response-model change **breaks the frontend build** rather
than failing silently at runtime in a user's browser. For a platform whose entire pitch is
"we catch the regressions you would have shipped," a frontend that can silently desync from its own
backend is an embarrassing contradiction. This is a correctness property, not a preference.

The rest follows from it: TanStack Query for server-state (polling a running eval is the dominant
interaction, and it handles cache invalidation and refetch intervals natively); Tailwind + shadcn/ui
because the dashboard needs a real component vocabulary — tables, dialogs, tabs, diff views — and
hand-writing that CSS is not the interesting engineering here; Recharts for ARS trends and load-test
percentile curves.

**Not Next.js.** The backend is FastAPI. There is no SSR requirement and no public SEO surface —
every page sits behind auth. A static SPA bundle is served by the nginx gateway that already exists
in the Helm chart, deploying as part of the existing chart with no new workload. Next.js would mean
running a Node server in the cluster to render pages that do not need rendering.

### Timing: one high-quality rewrite in Phase 5, after the Phase 4 APIs stabilise

The rewrite does **not** happen incrementally alongside Phase 4. Five new backend features means
five new response schemas that will churn while being designed. Building UI against churning data
shapes means rewriting the same screens repeatedly and arriving at an incoherent design assembled in
five uncoordinated passes.

Phase 4 features therefore ship with **API + CLI surfaces only** (`agentbench diff`,
`agentbench chaos`, `agentbench load`). The CLI is the primary interface during Phase 4 — which is
also correct product-wise, since the CI/CD use case is the platform's main entry point and it is
headless.

The existing v1 dashboard stays running and untouched until it is replaced wholesale.

## Consequences

**Positive**
- Frontend and backend types cannot silently diverge; the build enforces it.
- One coherent design pass instead of five uncoordinated ones.
- No wasted UI work against schemas that changed the following week.
- Static bundle deploys inside the existing Helm chart — no new production workload, consistent with
  ADR-005.
- Phase 4 velocity is not gated on UI work.

**Negative**
- Phase 4 features are CLI/API-only when first shipped and are not demoable in a browser until
  Phase 5. Accepted: the CLI *is* the primary interface for CI/CD, and screenshots are not the
  deliverable.
- The current v1 dashboard remains unauthenticated for longer. Mitigated in Phase 3.1 by putting
  auth on the `/dashboard` **API routes** — the v1 frontend will need an auth header added at that
  point even though it is destined for replacement. That small cost is worth not shipping a
  cross-tenant read hole.
- 546 lines are discarded rather than migrated. At that size, rewriting is cheaper than retrofitting
  TypeScript, auth, query caching and a design system onto it.

**Follow-up work created**
- Phase 3.1 must add an auth header to the v1 dashboard's `fetch()` calls when `/dashboard` routes
  become authenticated, or the v1 app breaks.
- Phase 4 features must ship with complete OpenAPI response models, since those become the
  generated frontend types in Phase 5.

## Alternatives considered

**Incremental — convert v1 to TypeScript, add auth and TanStack Query, grow pages alongside
Phase 4.** Less upfront work, but carries forward the current unstyled layout and hand-rolled fetch
patterns, and still means rebuilding screens as Phase 4 schemas churn. Rejected.

**Full rewrite now, before Phase 4.** Produces a polished dashboard for features that do not exist,
then rebuilds it as each one lands. Rejected.

**Drop the dashboard, ship CLI-only.** Defensible for a CI/CD tool, and rejected because behavioural
diffs and failure clusters are inherently visual — a cosine-distance table in a terminal does not
communicate what a side-by-side diff view does. §7 lists the dashboard as a deliverable.
