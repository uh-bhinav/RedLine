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