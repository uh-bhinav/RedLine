# RedLine

RedLine is a CI gate for AI agents. It runs an agent against an evaluation suite and decides whether a change is safe to ship. It computes an Agent Reliability Score (ARS), detects drift in behaviour over time, diffs two agent versions case by case, runs load tests, and mines failure clusters from failing transcripts.

## Screenshots

| Dashboard home | Gate failed | Agent health |
|---|---|---|
| ![Dashboard home](docs/demo/01_dashboard_home.png) | ![Gate failed](docs/demo/02_gate_failed_hero.png) | ![Agent health](docs/demo/03_agent_health.png) |

![Silent drift](docs/demo/04_silent_drift.png)

## Quick start

```powershell
copy .env.example .env          # then set JWT_SECRET_KEY
powershell -File scripts/redline.ps1 up
python -m scripts.seed_demo --reset
powershell -File scripts/redline.ps1 verify
```

Demo login: `demo@redline.dev` / `DemoPass123!`

New here? Read [docs/ONBOARDING.md](docs/ONBOARDING.md) for what changed and how to start. Full instructions, local mode without Docker, environment variables, the worker reliability model, tests and troubleshooting are in [docs/RUNNING.md](docs/RUNNING.md).
