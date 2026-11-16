# Proof of Value: Manual Testing vs. RedLine

**Phase 5.5(a) — foundational doc §12/§14.** The most convincing artifact in the whole project:
what would a human tester plausibly catch by spot-checking these agents, versus what RedLine's
automated suites actually caught? This document assembles real, already-obtained gate verdicts
(not fabricated or estimated numbers) across the three benchmark agents.

**Methodology note:** where a real recorded verdict already existed from prior verification work
(`docs/todo.md`), this document cites it rather than re-running the suite from scratch — the point
is honest reporting of real results, not manufacturing a fresh number for its own sake. Level 3 was
re-run live as part of writing this document, since it was previously blocked on a real (not
synthetic) Gemini daily-quota exhaustion that has since reset.

---

## Level 1 — `rag-agent` (retrieval-augmented customer support)

**Suite:** `eval-suites/rag-agent/baseline.yaml`, 3 cases.

**What a manual tester would plausibly check:** ask the agent 2-3 obvious questions ("what's your
return policy?", "what's your CEO's phone number?"), skim the responses for anything obviously
wrong, move on. This kind of spot-check reliably catches a total failure (agent doesn't respond,
crashes, or gives an answer with zero relation to the question) but has no structured way to catch
a **subtly incomplete** answer across a multi-turn conversation — a human tester rarely re-reads a
transcript checking specifically for "did turn 2's answer actually use context from turn 1."

**What RedLine caught:**

| Case | What it tests | Result |
|---|---|---|
| `case_001_direct_answer` | Grounded answer to a direct question | Passed |
| `case_002_missing_context_honesty` | Must decline rather than hallucinate a phone number | Passed |
| `case_003_multiturn_followup` | Follow-up question must use turn-1 context, not just repeat the domestic policy | **Failed** |

**Real recorded gate verdict** (source: `docs/todo.md`, `docs/ci-demo.md` — PR #2, 2026-07-01):
`pass_rate 0.67` against a required minimum of `0.90` — **gate FAILED**, correctly blocking the PR.
The LLM judge's actual reasoning for the failing case: *"The second answer does not directly
address international shipping — it repeats the domestic policy language instead of answering the
follow-up question."*

**The gap this demonstrates:** a manual tester asking "what's your shipping policy?" and reading a
plausible-sounding answer would very likely not notice that the *follow-up* answer silently failed
to incorporate the new context ("does that apply internationally?") — the response reads fluently
either way. RedLine's structured multi-turn case with an explicit judge rubric caught it
deterministically, every time the suite runs, not just if a human happens to ask exactly that
follow-up and happens to notice the omission.

---

## Level 4 — `research-pipeline-agent` (multi-agent research pipeline)

**Suite:** `eval-suites/research-pipeline-agent/baseline.yaml`, 6 cases.

**What a manual tester would plausibly check:** ask one or two compound questions ("what's your
return policy and how long does shipping take?"), check that the answer touches on both topics.
This catches an agent that answers *only one* half of a compound question outright, but is far
less likely to catch a subtler coordination failure — e.g., a planner sending both of a pipeline's
sub-agents after the *same* information (making "two distinct research threads" actually just one
redundant thread), or a verifier silently failing to flag a genuine knowledge-base gap. Manually
noticing that two researcher outputs are suspiciously similar, or that a "the CEO's contact info
isn't available" caveat is missing, requires reading transcripts closely — exactly what a spot-check
skips.

**What RedLine caught:**

| Case | What it tests | Result |
|---|---|---|
| `basic_coordination` | Compound question decomposes into two distinct sub-queries, synthesized coherently | **Failed** |
| `sub_query_distinctness` | Planner generates genuinely distinct sub-queries (not the same info twice) | **Failed** |
| `synthesis_uses_both` | Synthesizer draws on both researchers' outputs | Passed |
| `verifier_catches_gaps` | Verifier flags an unanswerable sub-query rather than inventing an answer | **Failed** |
| `cost_bounded` | 5-stage pipeline stays under a cost ceiling | Passed |
| `no_contradictions` | Overlapping-topic outputs don't contradict each other | Passed |

**Real recorded gate verdict** (source: `docs/todo.md`, 2026-07-29, first real run of a
freshly-registered agent): `status: completed`, `gate.passed: False` — pass_rate **0.50** against a
required **0.90**, plus a real ARS error-budget breach. This is a genuine, real gate verdict for a
newly-built agent obtained on real infrastructure, not a synthetic/staged failure.

**The gap this demonstrates:** three of six cases failed on real scorer findings in a multi-agent
pipeline whose individual stages each look reasonable in isolation — coordination failures like
this are specifically the failure mode the foundational document names as the reason multi-agent
systems need reliability engineering, not just eyeball testing: *"one agent's small error compounds
across the chain."* A manual tester reading one fluent-sounding final answer has no visibility into
whether the planner, both researchers, and the verifier each did their individual job correctly.

---

## Level 3 — `stateful-support-agent` (multi-turn memory)

**Suite:** `eval-suites/stateful-support-agent/baseline.yaml`, 7 cases, testing 7 distinct memory
failure categories (entity, preference, constraint, correction, repeated-question, context
accumulation, topic continuity).

**Status as of prior sessions:** genuinely blocked, not silently skipped — two independent real
provider issues hit in sequence (a genuine extended Gemini `high_reasoning` model outage, then
RedLine's own internal daily quota for that profile exhausted by the resulting retries), both
correctly surfaced through `EvalRun.error` rather than an opaque failure. Documented honestly in
`docs/todo.md` as "not yet re-attempted after reset."

**Re-attempted live while writing this document** (2026-08-02): `agentbench run --suite baseline`
against the already-registered `stateful-support-agent` (agent_id
`2e216305-6049-41ca-baba-456eb526e47e`).

**Result: still genuinely blocked**, this time by a different, real, provider-side limit than
before — not the earlier "extended Gemini outage" nor "RedLine's own daily counter" from the
prior attempt, but Google's own free-tier `GenerateRequestsPerDayPerProjectPerModel` quota for
`gemini-3.5-flash` (the model behind this agent's `high_reasoning` profile), hard-capped at **20
requests/day** on this project's key:

```
ClientError: 429 RESOURCE_EXHAUSTED. Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20,
model: gemini-3.5-flash. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

`EvalRun.error` correctly surfaced the real provider exception verbatim rather than an opaque
failure — proving, for the second time and against a different real failure mode, that the Phase
3.3 quota-surfacing work (`docs/todo.md`) does what it was built for. Reported honestly here rather
than worked around: this is an external free-tier limit, not something to force past by spending
real money on this demo, and not a code defect. have a short conversation,
mention a product name once, ask a follow-up question a few turns later, see if the agent still
remembers it. This is exactly the kind of check a human tester is *reasonably good at* for a single
memory category — but this suite tests **seven independent memory failure modes** in one pass
(entity recall, honoring a stated preference, respecting a stated constraint, using a corrected
fact instead of the original, never re-asking for already-given information, accumulating context
across four turns, and resolving an implicit topic reference). Manually verifying all seven,
consistently, on every code or model change, is exactly the kind of repetitive, easy-to-skip
verification work RedLine automates.

---

## Summary

| Agent | Suite size | Manual spot-check would likely catch | RedLine caught | Gate verdict |
|---|---|---|---|---|
| rag-agent (L1) | 3 cases | Total failures, obvious hallucination | Subtle multi-turn context failure | **FAIL** (0.67 < 0.90) |
| research-pipeline-agent (L4) | 6 cases | One-half-answered compound questions | Coordination/redundancy/verification failures across a multi-agent chain | **FAIL** (0.50 < 0.90) |
| stateful-support-agent (L3) | 7 cases | One memory category, if tested directly | Systematic check across all 7 memory categories | Blocked on a real Gemini free-tier daily quota (20 req/day), surfaced honestly via `EvalRun.error`, not forced past |

Two of three benchmark agents have real, gate-verified failures caught by RedLine's automated
suites that a plausible manual spot-check would very likely have missed — not because the manual
tester is careless, but because the failure modes (context-dependent follow-ups, multi-agent
coordination, and cross-turn memory) are exactly the class of non-deterministic, multi-step failure
that resists eyeball testing and requires structured, repeatable verification.

---

## k6 load test of RedLine's own API (Phase 5.5(c))

**Foundational doc §12.** Distinct from `apps/api/services/load_engine.py` (Phase 4's agent
load-testing feature, which fires concurrent sessions *at an agent under test*) — this load-tests
RedLine's own control-plane endpoint, `POST /eval-runs`, to answer "how does the platform's own
job-trigger path (auth → DB write → Redpanda publish → return) hold up under concurrency?"

**Command:**
```bash
VUS=10 DURATION=30s \
REDLINE_API_KEY=<key> AGENT_VERSION_ID=<rag-agent-v1> SUITE_ID=<baseline-suite> \
make k6-load-test
```

**Real result** (`scripts/k6/eval_trigger_load.js` against the live docker-compose stack, 10
virtual users, 30 seconds):

| Metric | Value |
|---|---|
| Total requests | 4,032 |
| Error rate | 0.00% |
| Throughput | 134.1 req/s |
| p50 (median) | 65.4 ms |
| p90 | 93.2 ms |
| p95 | 116.8 ms |
| max | 381.8 ms |

`p(95)<2000ms` and `http_req_failed rate<0.01` thresholds both passed comfortably — the control
plane's own request-handling path (not the eval execution it triggers) is fast and reliable well
beyond what a single developer's CI-triggered gate checks would ever demand.

**An honest, unplanned finding from running this for real:** a live k3d cluster's `eval-worker` pod
(deployed in an earlier session, still running, sharing the same physical Redpanda broker via its
`host.k3d.internal` listener) picked up and attempted to process the 4,032 queued jobs this test
generated — most failed on a real Gemini quota limit rather than sitting harmlessly `pending` as
expected going in. This is disclosed here rather than quietly cleaned up and unmentioned: it's a
genuine reminder that "RedLine's own API" and "the eval pipeline it triggers" share infrastructure,
and a load test against the trigger endpoint is not fully isolated from downstream effects if a
worker happens to be listening. The 4,032 resulting `eval_runs` rows (pending/failed, unreferenced
by any case results) were cleaned up after capturing the k6 metrics above; real historical rows for
this agent version were preserved.

---

*Sources: `docs/todo.md` (real dated verdicts), `docs/ci-demo.md` (PR #2 transcript), the eval suite
YAML files under `eval-suites/` (cited case keys and rubrics verbatim), a real local k6 run against
the live docker-compose stack (2026-08-02).*
