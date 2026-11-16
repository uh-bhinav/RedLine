"""
Packaging invariants (Phase 3 Section 4).

Two things are guarded here, both of which fail silently and late if they break:

  1. `pip install agentbench` must not require the server's dependency tree. The CLI
     talks to a hosted RedLine over HTTP; a user has no Postgres, no Redpanda, and
     often no libpq to compile psycopg2 against. This is architectural rule #6 ("the
     CLI never imports from apps.api") enforced by packaging -- a CLI command that
     starts importing apps.api would break a clean install rather than quietly
     working on the maintainer's machine.

  2. pyproject.toml's [api] extra and apps/api/requirements.txt must agree.
     The Dockerfiles install from requirements.txt for layer caching; pip users get
     the extra. Two dependency lists that drift produce "works in Docker, broken on
     pip" bugs that are miserable to diagnose.

Run from the repo root:
    pytest apps/api/tests/unit/test_packaging.py -v -m unit
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "apps" / "api" / "requirements.txt"

# Packages that must never appear in the CLI's base dependencies.
SERVER_ONLY = {
    "psycopg2-binary", "psycopg2", "sqlalchemy", "alembic", "confluent-kafka",
    "clickhouse-driver", "redis", "fastapi", "uvicorn", "google-genai",
    "apscheduler", "prometheus-client", "opentelemetry-sdk", "numpy",
}


def _load_pyproject() -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        import tomli as tomllib  # Python 3.10
    return tomllib.loads(PYPROJECT.read_text())


def _normalize(spec: str) -> str:
    """'uvicorn[standard]==0.32.1' -> 'uvicorn'. Comparison is by package identity;
    version pinning is checked separately."""
    name = re.split(r"[<>=!\[;]", spec.strip(), maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def _requirements_packages() -> set[str]:
    lines = REQUIREMENTS.read_text().splitlines()
    return {
        _normalize(line)
        for line in lines
        if line.strip() and not line.strip().startswith(("#", "-"))
    }


@pytest.fixture(scope="module")
def pyproject() -> dict:
    if not PYPROJECT.exists():
        pytest.fail(f"pyproject.toml not found at {PYPROJECT}")
    return _load_pyproject()


# ---------- the CLI is installable on its own ----------

def test_cli_base_dependencies_exclude_server_packages(pyproject):
    base = {_normalize(d) for d in pyproject["project"]["dependencies"]}
    leaked = base & SERVER_ONLY

    assert not leaked, (
        f"server-only packages leaked into the CLI's base dependencies: "
        f"{sorted(leaked)}. `pip install agentbench` would now require a database "
        f"driver the user has no use for."
    )


def test_console_script_is_declared(pyproject):
    scripts = pyproject["project"].get("scripts", {})
    assert scripts.get("agentbench") == "apps.cli.main:app", (
        "the `agentbench` console script is missing or points somewhere unexpected"
    )


def test_packages_are_explicit_and_exclude_the_api(pyproject):
    packages = pyproject["tool"]["setuptools"]["packages"]

    assert "apps.cli" in packages
    assert "apps.cli.commands" in packages
    assert not any(p.startswith("apps.api") for p in packages), (
        "apps.api must not ship in the CLI distribution"
    )
    assert not any(p.startswith("agents") for p in packages), (
        "the benchmark agents are fixtures under test, not library code"
    )


def test_cli_source_does_not_import_the_api():
    """The packaging split only holds if the code respects it (rule #6)."""
    offenders = []
    for path in (REPO_ROOT / "apps" / "cli").rglob("*.py"):
        text = path.read_text()
        if re.search(r"^\s*(from|import)\s+apps\.api", text, re.MULTILINE):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"CLI modules import from apps.api, which breaks a CLI-only install: {offenders}. "
        f"Add an API endpoint instead."
    )


# ---------- the two dependency lists agree ----------

def test_api_extra_matches_requirements_txt(pyproject):
    extra = {_normalize(d) for d in pyproject["project"]["optional-dependencies"]["api"]}
    base = {_normalize(d) for d in pyproject["project"]["dependencies"]}
    dev = {_normalize(d) for d in pyproject["project"]["optional-dependencies"]["dev"]}

    declared = extra | base | dev
    required = _requirements_packages()

    missing_from_pyproject = required - declared
    assert not missing_from_pyproject, (
        f"in requirements.txt but not pyproject.toml: {sorted(missing_from_pyproject)}. "
        f"A pip install would be missing them."
    )

    missing_from_requirements = declared - required
    assert not missing_from_requirements, (
        f"in pyproject.toml but not requirements.txt: {sorted(missing_from_requirements)}. "
        f"The Docker images would be missing them."
    )


def test_every_dependency_is_version_pinned(pyproject):
    """Unpinned dependencies make builds unreproducible, which for a platform whose
    pitch is reproducible evaluation is an awkward thing to ship."""
    all_deps = (
        pyproject["project"]["dependencies"]
        + pyproject["project"]["optional-dependencies"]["api"]
        + pyproject["project"]["optional-dependencies"]["dev"]
    )
    unpinned = [d for d in all_deps if not re.search(r"[=<>]", d)]
    assert not unpinned, f"unpinned dependencies: {unpinned}"


def test_starlette_conflict_package_is_absent(pyproject):
    """Architectural rule #10: prometheus-fastapi-instrumentator requires
    starlette>=1.0.0 and fastapi==0.115.6 ships starlette 0.41.x."""
    all_deps = " ".join(
        pyproject["project"]["dependencies"]
        + pyproject["project"]["optional-dependencies"]["api"]
    ).lower()
    assert "prometheus-fastapi-instrumentator" not in all_deps


# ---------- metadata a published package needs ----------

def test_project_metadata_is_complete(pyproject):
    project = pyproject["project"]
    assert project["name"] == "agentbench"
    assert project["requires-python"].startswith(">=3.10")
    assert project.get("license"), "a published package needs a license"
    assert project.get("description")
