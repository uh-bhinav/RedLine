"""
Unit tests for the Phase 5.1 dead-letter-queue mechanism
(RedpandaEvalWorker.retry_or_dead_letter()).

Pure-logic tests: _make_producer()/_make_consumer() are monkeypatched to return
Mocks so nothing here touches a real broker -- no docker-compose needed, runs
anywhere, matching the discipline every other engine's unit test suite follows.

Run from the repo root:
    pytest apps/api/tests/unit/test_redpanda_dlq.py -v
"""
import json
import uuid
from unittest.mock import MagicMock

import pytest

import apps.api.core.redpanda_queue as redpanda_queue
from apps.api.core.jobqueue import ClaimedJob
from apps.api.core.redpanda_queue import RedpandaEvalWorker

pytestmark = pytest.mark.unit


@pytest.fixture
def worker(monkeypatch):
    mock_producer = MagicMock()
    mock_producer.flush.return_value = 0  # 0 == everything flushed successfully
    mock_consumer = MagicMock()

    monkeypatch.setattr(redpanda_queue, "_make_producer", lambda: mock_producer)
    monkeypatch.setattr(redpanda_queue, "_make_consumer", lambda group_id: mock_consumer)
    monkeypatch.setattr(redpanda_queue._settings, "max_job_retries", 3)

    w = RedpandaEvalWorker(group_id="test-worker")
    w._producer_mock = mock_producer  # stash for assertions
    return w


def _claimed(retry_count: int) -> ClaimedJob:
    return ClaimedJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="eval.requested",
        payload={"eval_run_id": str(uuid.uuid4())},
        retry_count=retry_count,
    )


def test_retries_when_under_limit(worker):
    claimed = _claimed(retry_count=0)

    dead_lettered = worker.retry_or_dead_letter(claimed, "boom")

    assert dead_lettered is False
    call = worker._producer_mock.produce.call_args
    assert call.kwargs["topic"] == "eval.requested"
    envelope = json.loads(call.kwargs["value"].decode("utf-8"))
    assert envelope["retry_count"] == 1
    assert envelope["job_id"] == str(claimed.id)
    assert "final_error" not in envelope


def test_retry_count_increments_across_repeated_failures(worker):
    claimed = _claimed(retry_count=2)

    dead_lettered = worker.retry_or_dead_letter(claimed, "boom again")

    assert dead_lettered is False
    envelope = json.loads(worker._producer_mock.produce.call_args.kwargs["value"].decode("utf-8"))
    assert envelope["retry_count"] == 3


def test_dead_letters_once_limit_exceeded(worker):
    claimed = _claimed(retry_count=3)  # next_retry = 4 > max_job_retries = 3

    dead_lettered = worker.retry_or_dead_letter(claimed, "final failure")

    assert dead_lettered is True
    call = worker._producer_mock.produce.call_args
    assert call.kwargs["topic"] == "eval.requested.dead-letter"
    envelope = json.loads(call.kwargs["value"].decode("utf-8"))
    assert envelope["retry_count"] == 3  # preserved, not incremented past the limit
    assert envelope["final_error"] == "final failure"
    assert envelope["job_id"] == str(claimed.id)


def test_dead_letter_topic_naming():
    assert redpanda_queue._dead_letter_topic("eval.requested") == "eval.requested.dead-letter"
    assert redpanda_queue._dead_letter_topic("load.requested") == "load.requested.dead-letter"


def test_raises_on_unflushed_messages(worker):
    worker._producer_mock.flush.return_value = 1  # 1 message left undelivered
    claimed = _claimed(retry_count=0)

    with pytest.raises(RuntimeError, match="flush timed out"):
        worker.retry_or_dead_letter(claimed, "boom")
