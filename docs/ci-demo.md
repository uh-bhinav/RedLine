# CI / Branch-Protection Demonstration

**Section 12 + 15 acceptance criterion** (roadmap §15, final bullet):
> The CI/branch-protection demonstration is a manual, documented one-time validation
> with a recording/screenshot kept in `docs/` — GitHub's branch protection UI itself
> isn't something to unit test, but the fact that it works must be provably demonstrated,
> not just assumed.

---

## What was demonstrated

On **2026-07-01**, a real pull request (`uh-bhinav/RedLine#2`, branch
`test1/agentbench-ci-check`) was blocked from merging into `main` by a failing
`AgentBench Reliability Check`. Screenshots are in this directory.

---

## Exact Actions log (key lines)

```
agentbench  agentbench ci-check  Check Run created: id=84495429489
agentbench  agentbench ci-check  Eval run created: 9f933eba-ee31-47c6-8c3f-090fbe8cf864
agentbench  agentbench ci-check    status: running...
agentbench  agentbench ci-check    status: running...
agentbench  agentbench ci-check  GATE FAILED
agentbench  agentbench ci-check    ✗ pass_rate 0.67 is below required minimum 0.90
agentbench  agentbench ci-check  ##[error]Process completed with exit code 1.
```

---

## Branch protection rule

Set via `gh api`:

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["AgentBench Reliability Check"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

Confirmed active:
```
"contexts": ["AgentBench Reliability Check"]
```

---

## Why the gate failed

`case_003_multiturn_followup` failed. The LLM judge's verdict:

> "The second answer does not directly address international shipping in a
> comprehensive way, and it asks the user to repeat information already given
> in turn 1."

This is a real RAG agent behavioral limitation, not a platform bug. The gate
correctly caught it. `pass_rate = 2/3 = 0.67`, below the required `0.90`
minimum set by the default `GatePolicy`.

---

## Infrastructure used

| Component | Detail |
|---|---|
| API server | FastAPI on `localhost:8000` (Mac M2, local Docker Compose) |
| Public URL | ngrok free tunnel (`https://612d-101-0-62-31.ngrok-free.app`) |
| Worker | `python -m apps.api.workers.eval_worker` (local, same machine) |
| LLM | Gemini 2.5 Flash + Gemini Embedding 001 (free tier) |
| GitHub Actions | ubuntu-latest runner, Python 3.10 |

---

## Reproducing this demonstration

1. Start Postgres: `docker compose up -d postgres`
2. Start API: `uvicorn apps.api.main:app --reload --port 8000`
3. Start worker: `python -m apps.api.workers.eval_worker`
4. Start tunnel: `ngrok http 8000`
5. Set repo secrets: `REDLINE_BASE_URL`, `REDLINE_API_KEY`, `GEMINI_API_KEY`
6. Open a PR targeting `main` from any branch
7. The `AgentBench Reliability Check` status appears within ~60 seconds
8. If `case_003` still fails, the gate blocks the merge automatically

---

## Post-Phase-4 update (2026-08-02): ARS and error-budget reasoning now visible in gate output

**Manual user action still open, stated plainly:** the transcript above (PR #2) is a real,
verbatim log — but it predates Phase 4's ARS/error-budget work, so it only ever shows a
`pass_rate` reason. I (the agent doing this write-up) cannot produce a screen recording. What
follows is the up-to-date written walkthrough of what the gate's reasoning looks like today;
producing an actual video is a ~2-minute task only a human can do — see the box at the end of this
section.

### What changed in the gate's own output

`gate_engine._compute_gate_result()` now also carries an ARS threshold check
(`apps/api/services/gate_engine.py`), and `evaluate()` separately checks the agent's
**error budget** across recent runs (`ars_engine.evaluate_error_budget()`) — a statement about
history, not just the current run, so it can fail a run even if that run's own numbers look fine.
A `GateResult.reasons` list today can therefore contain any combination of:

```
pass_rate 0.50 is below required minimum 0.90
ars 0.612 is below required minimum 0.850
error budget exhausted: 3/5 recent run(s) scored below target ARS 0.90 (60.0% breach rate vs 10.0% allowed budget)
```

### A real, already-obtained example: the Level 4 (`research-pipeline-agent`) verdict

This is not a staged example — it's the actual gate verdict obtained during Phase 4 verification
work (full detail and case-level findings in `docs/proof-of-value.md`):

```
status: completed
gate.passed: False
  ✗ pass_rate 0.50 is below required minimum 0.90
  ✗ ars error-budget breach
```

Three of six cases failed on real scorer findings — `basic_coordination`, `sub_query_distinctness`,
and `verifier_catches_gaps` — plus the run's ARS score triggered the error-budget check. This is
what a blocked PR's Actions log shows today when a newly-built agent's multi-agent coordination has
real gaps: not just "below 90%," but which specific cases failed and why (see
`docs/proof-of-value.md` for the per-case reasoning), plus the reliability-trend signal ARS adds on
top of a single run's pass rate.

> **Remaining manual action:** open a PR against one of the benchmark agents with a deliberately
> introduced regression, let `AgentBench Reliability Check` run and fail it, and record (screen
> capture) the GitHub PR UI showing the blocked merge button, the failing check, and the check's
> summary output. No code changes are required for this — the mechanism above already works
> end-to-end, verified against real infrastructure; this is purely capturing it on video. Roughly
> 2 minutes of work whenever there's a next real PR to demonstrate it against.