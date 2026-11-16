# /test — RedLine Test Runner Guide

This command explains how to run, add, and debug tests in RedLine.

---

## Test Suite Overview

| Suite | Count | Deps | Time | Command |
|-------|-------|------|------|---------|
| Unit | 58 tests | None | <2s | `pytest -m unit` |
| Integration | 3 files | Postgres, optional Gemini | 30–120s | `pytest -m integration` |

Unit tests are the first gate — they must pass before running integration tests.

---

## Running Unit Tests

```bash
# All unit tests — no external dependencies, no Docker required
pytest -m unit

# With verbose output
pytest -m unit -v

# With coverage report
pytest -m unit --cov=apps/api --cov-report=term-missing

# Run a specific unit test file
pytest apps/api/tests/unit/test_gate_engine.py -v
pytest apps/api/tests/unit/test_scorers.py -v
pytest apps/api/tests/unit/test_auth.py -v
pytest apps/api/tests/unit/test_drift_detector.py -v
pytest apps/api/tests/unit/test_content_hash.py -v
pytest apps/api/tests/unit/test_local_python_adapter.py -v

# Run a specific test by name
pytest apps/api/tests/unit/test_gate_engine.py::test_gate_fails_below_pass_rate -v

# Run all unit tests, stop on first failure
pytest -m unit -x
```

**Expected output:**

```
58 passed in 1.4s
```

No network calls, no DB connections, no Gemini API calls.

---

## Running Integration Tests

**Prerequisites:**

```bash
# Start infrastructure
docker compose up -d

# Verify Postgres is ready (port 5433)
psql -h localhost -p 5433 -U redline -d redline -c "SELECT 1;"

# Apply migrations
alembic upgrade head

# Seed data
python -m apps.api.scripts.seed
```

```bash
# All integration tests
pytest -m integration -v

# Specific integration test files
pytest apps/api/tests/integration/test_eval_end_to_end.py -v
pytest apps/api/tests/integration/test_jobqueue.py -v
pytest apps/api/tests/integration/test_worker_restart.py -v

# The critical worker-restart test (tests SKIP LOCKED behavior)
pytest apps/api/tests/integration/test_worker_restart.py::test_worker_restart_does_not_duplicate_job -v -s
```

**Using a cheaper model for integration tests:**

The integration tests that invoke the LLM judge can be expensive on free-tier quotas. Override the model:

```bash
REDLINE_TEST_MODEL=gemini-2.0-flash pytest -m integration -v
```

This sets a cheaper model for test runs without modifying `model_profiles.yaml`.

---

## Unit Test File Breakdown

### `test_gate_engine.py` — 12 tests

Tests `_compute_gate_result()` (pure function — no DB needed):

- Pass/fail on `min_pass_rate` (0.0, 0.5, 0.9, 1.0 boundaries)
- Pass/fail on `max_avg_cost_usd` (None = skip check)
- Pass/fail on `max_avg_latency_ms` (None = skip check)
- Multi-threshold: fail on cost alone, fail on latency alone, fail on both
- Reason string format: must name the violated threshold

### `test_scorers.py` — 15 tests

Tests all 4 scorers against fake transcripts:

- `ContainsMatchScorer`: substring found/not found, must_not_contain
- `CostScorer`: under/over `max_cost_usd`, None threshold = skip
- `LatencyScorer`: under/over `max_latency_ms`, None threshold = skip
- `LLMJudgeScorer`: mocked Gemini response — tests structured output parsing, not real LLM call

### `test_auth.py` — 10 tests

Tests JWT issuance and RBAC:

- `create_access_token()` and `create_refresh_token()` produce valid JWTs
- Expired tokens raise `401`
- Wrong `"type"` claim raises `401`
- `require_role("admin")` blocks `developer` and `viewer`
- `require_role("developer")` allows `developer` and `admin`, blocks `viewer`

### `test_drift_detector.py` — 11 tests

Tests `detect_model_drift()` (pure function):

- No drift when pass_rate within threshold
- Model drift triggered when pass_rate delta exceeds threshold
- Behavior drift triggered on cost/latency regression
- RAG drift triggered on retrieval-specific metrics
- Edge cases: zero cases, all passing, all failing

### `test_content_hash.py` — 6 tests

Tests agent version content hash computation:

- Same file produces same hash (deterministic)
- Different files produce different hashes
- Hash is 64-char hex string (SHA256)
- Hash is stable across runs (no timestamp in input)

### `test_local_python_adapter.py` — 4 tests

Tests `LocalPythonAdapter` with mock agent modules:

- Valid entrypoint is imported and called correctly
- `session_state` is passed by reference (mutations persist across turns)
- `AgentTurnResult` is returned with all required fields
- Invalid entrypoint raises `ImportError`

---

## Adding New Unit Tests

**Required structure:**

```python
# apps/api/tests/unit/test_my_feature.py

import pytest

pytestmark = pytest.mark.unit  # REQUIRED — marks all tests in this file as unit tests

def test_my_feature_happy_path():
    # Arrange
    ...
    # Act
    result = my_function(input)
    # Assert
    assert result.field == expected_value

def test_my_feature_edge_case():
    ...
```

**Rules for unit tests:**
1. `pytestmark = pytest.mark.unit` at module level — mandatory
2. No database fixtures (`Session`, `get_db`, `engine`)
3. No real network calls (mock Gemini responses)
4. No file system access except reading test fixtures from `apps/api/tests/`
5. All external services mocked via `unittest.mock.patch` or `pytest-mock`

**Mocking Gemini in unit tests:**

```python
from unittest.mock import patch, MagicMock

@patch("apps.api.services.scorers.llm_judge.genai.GenerativeModel")
def test_llm_judge_passes_when_gemini_returns_true(mock_model):
    mock_response = MagicMock()
    mock_response.text = '{"passed": true, "reasoning": "Correct answer"}'
    mock_model.return_value.generate_content.return_value = mock_response
    
    scorer = LLMJudgeScorer(rubric="Must contain accurate info")
    result = scorer.score(case=fake_case, transcript=fake_transcript)
    
    assert result.passed is True
```

---

## Adding New Integration Tests

**Required structure:**

```python
# apps/api/tests/integration/test_my_integration.py

import pytest

pytestmark = pytest.mark.integration  # REQUIRED

@pytest.fixture
def db():
    """Real Postgres session on localhost:5433"""
    from apps.api.core.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_my_integration_against_real_db(db):
    ...
```

**Integration test rules:**
1. `pytestmark = pytest.mark.integration` at module level
2. Requires `docker compose up -d` before running
3. Must clean up after themselves (delete rows created during test)
4. Must not depend on seeded data IDs (query for them dynamically)
5. LLM calls are allowed but use `REDLINE_TEST_MODEL=gemini-2.0-flash` in CI

---

## Known Skip Conditions

```bash
# Tests that fail on Gemini free-tier daily quota exhaustion:
# - test_eval_end_to_end.py (calls llm_judge scorer)
# - Level 3 and Level 4 gate verdict tests (Section 10 acceptance — pending)

# Run unit tests only when quota is exhausted:
pytest -m unit
```

**If an LLM test fails with 429:**

```
google.api_core.exceptions.ResourceExhausted: 429 RESOURCE_EXHAUSTED
Quota exceeded for quota metric 'generate_requests_per_day'
```

Skip the LLM integration tests with:

```bash
pytest -m integration -k "not llm and not end_to_end"
```

Or wait until midnight PST and re-run with:

```bash
REDLINE_TEST_MODEL=gemini-2.0-flash pytest -m integration
```

---

## CI Test Command (`pytest.ini` config)

```ini
# pytest.ini
[pytest]
markers =
    unit: pure unit tests, no external dependencies
    integration: requires docker compose up, may hit real APIs
```

GitHub Actions runs:

```yaml
# .github/workflows/agentbench-check.yml
- run: pytest -m unit
  # Always runs

- run: pytest -m integration
  env:
    REDLINE_TEST_MODEL: gemini-2.0-flash
  # Runs in CI with real infra
```

---

## Test Database Connection

Integration tests connect to Postgres on port **5433** (not 5432):

```bash
# Verify connection before running integration tests
psql -h localhost -p 5433 -U redline -d redline -c "\dt"
```

The `DATABASE_URL` used by tests comes from `.env`:

```
DATABASE_URL=postgresql://redline:redline_dev@localhost:5433/redline
```
