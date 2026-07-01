"""
GitHub Checks API REST calls (corrected Section 12 design).

This is the ONLY place in the codebase that knows GitHub exists.
Called by ci_check.py using the ambient GITHUB_TOKEN from the Actions environment.
The API server has zero knowledge of this module.
"""
from __future__ import annotations

import httpx

GITHUB_API = "https://api.github.com"
CHECK_NAME = "AgentBench Reliability Check"


def create_check_run(repo: str, commit_sha: str, token: str) -> int:
    """Creates an in_progress Check Run. Returns the check_run_id."""
    r = httpx.post(
        f"{GITHUB_API}/repos/{repo}/check-runs",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "name": CHECK_NAME,
            "head_sha": commit_sha,
            "status": "in_progress",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["id"]


def update_check_run(repo: str, check_run_id: int, passed: bool, reasons: list[str], token: str) -> None:
    """Marks the Check Run completed with success or failure + the gate's reasons."""
    summary = (
        "All gate thresholds passed."
        if passed
        else "Gate failed:\n" + "\n".join(f"- {r}" for r in reasons)
    )
    r = httpx.patch(
        f"{GITHUB_API}/repos/{repo}/check-runs/{check_run_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "status": "completed",
            "conclusion": "success" if passed else "failure",
            "output": {
                "title": "AgentBench Reliability Check",
                "summary": summary,
            },
        },
        timeout=15,
    )
    r.raise_for_status()