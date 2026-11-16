# ADR-005: Helm is the product's deployment interface; cloud provider deferred

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** Abhinav Mahesh Gurkar

---

## Context

RedLine must eventually run on a public URL so that outside users can try it and so that the
GitHub Actions gate has a real API to call (today `REDLINE_BASE_URL` is a secret pointing at a
laptop). The obvious next question is "which cloud?"

Three candidate paths were on the table:

1. **PaaS + managed data services** — Fly.io for services/workers, Neon for Postgres, Upstash for
   Redis/Kafka, ClickHouse Cloud free tier. Fastest to a live URL, genuinely free.
2. **Managed Kubernetes** — GKE/EKS. Keeps the Helm chart as the real artefact, costs real money
   past trial credits.
3. **Oracle Cloud always-free ARM VM (4 core / 24 GB) + k3s** — real Kubernetes, $0, single node.

The tension: option 1 is the fastest path to "deployed," but it is the only one that would require
the application to be reshaped. Fly.io wants `fly.toml`-shaped services; Upstash Kafka is not
Redpanda; the KEDA `ScaledObject` on consumer lag — the single most interesting piece of Phase 2
infrastructure — has nowhere to run. "Deployed" would be bought by deleting the distributed-systems
story that is the reason the project exists.

There is also a timing problem. Phase 4 introduces two new worker types (`load_runner`,
`trace_worker`) whose resource profiles are unknown until they are built. A load runner firing
thousands of concurrent outbound requests may not fit on a single free-tier node. Choosing a
provider now means choosing it against guessed requirements.

## Decision

**Helm is the product's deployment interface.** The same chart deploys unchanged to k3d locally and
to whatever cluster is chosen publicly. No application code, no manifest fork, no provider-specific
shim.

**The cloud provider is deliberately not chosen until Phase 4 is complete.**

- **Primary intent:** Oracle Cloud always-free ARM VM running k3s.
- **Fallback:** managed Kubernetes (GKE/EKS) if the Oracle free tier proves limiting or unreliable.
- **Rejected:** any target that requires application changes to deploy. If a provider needs
  compose-shaped or PaaS-shaped rework, that provider is rejected regardless of cost.

Phase 5 work that is *not* blocked by this decision proceeds immediately: the Helm chart must
already be provider-agnostic (no hardcoded hostnames, all config through ConfigMap/Secret, no
`localhost` bootstrap servers — see Bug 2), and the CI/CD pipeline builds and scans images
regardless of where they eventually land.

## Consequences

**Positive**
- The strongest available technical claim stays true: one chart, k3d on a laptop and a real cluster
  in production, zero application changes. That is a claim most side projects cannot make.
- KEDA autoscaling on consumer lag survives into production instead of being a local-only demo.
- Provider selection happens against measured resource requirements rather than guessed ones.
- Cloud-agnostic by construction, which is also the mitigation the foundational document (§15)
  gives for "free-tier cloud limits change or get revoked."

**Negative**
- No public URL until Phase 4 finishes. The CI gate keeps pointing at a local instance until then.
- A single-node k3s cluster gives no real HA. This is accepted: the goal is a working public
  deployment, not a production SLA.
- ARM (aarch64) images are required for the Oracle path. Image builds should be multi-arch from the
  start so this does not become a late surprise — the M2 Mac already builds arm64 natively, so this
  costs nothing to do now and is expensive to retrofit.

**Follow-up work created**
- Multi-arch (`linux/amd64,linux/arm64`) image builds in the Phase 5.2 CI/CD pipeline.
- Audit the Helm chart for provider-specific assumptions before provider selection.
- Bug 2 (`localhost:19092` bootstrap in the eval-service environment) must be fixed — it is exactly
  the class of hardcoded-host assumption this ADR forbids.

## Alternatives considered

**Fly.io + Neon + Upstash.** Fastest to a live URL and genuinely free. Rejected because it deletes
Kubernetes, KEDA, and the Redpanda consumer-group model from the production story, which is
precisely the engineering the project is meant to demonstrate. Reduced to a documented emergency
escape hatch, not a plan.

**Managed Kubernetes now.** Preserves everything, costs money past trial credits, and would still be
sized against guessed Phase 4 requirements. Retained as the fallback rather than the default.

**Choosing nothing and staying local forever.** Rejected — §14 of the foundational document lists a
public deployment as a success metric, and an open-source project a stranger cannot try is one
nobody adopts.
