"""
Creates the three Phase 2 Redpanda topics if they don't already exist.

Idempotent -- safe to re-run. Topics are created with sensible defaults for
local development (1 partition, replication factor 1 -- a single-broker setup).
In production (Phase 4), bump partitions to tenant_count * 2 and replication
factor to 3 across separate brokers.

Topic design:
  eval.requested   -- API publishes here; eval workers consume
  eval.completed   -- workers publish results here; trace workers consume
  trace.emitted    -- eval engine emits per-turn trace events for ClickHouse
  load.requested   -- Phase 4 Section 4: API publishes here; load_worker consumes.
                      Its own topic (not eval.requested) because a load runner's
                      resource profile is completely different from an eval
                      runner's -- firing many concurrent outbound requests vs.
                      processing one case at a time (foundational doc §9.3).
  *.dead-letter     -- Phase 5.1: a job that has exceeded max_job_retries lands
                      here instead of being retried again. Inspect with
                      `rpk topic consume eval.requested.dead-letter` (via the
                      redpanda container) or the Redpanda Console UI at
                      localhost:8080. See docs/infra-hardening.md for the manual
                      requeue procedure -- there is no automated replay tool yet.

Usage (from the repo root):
    python -m apps.api.scripts.init_topics
"""
import sys

from confluent_kafka.admin import AdminClient, NewTopic

from apps.api.core.config import get_settings

TOPICS = [
    "eval.requested",
    "eval.completed",
    "trace.emitted",
    "load.requested",
    "eval.requested.dead-letter",
    "load.requested.dead-letter",
]


def main() -> None:
    settings = get_settings()
    admin = AdminClient({"bootstrap.servers": settings.redpanda_bootstrap_servers})

    existing = set(admin.list_topics(timeout=10).topics.keys())
    to_create = [
        NewTopic(topic, num_partitions=1, replication_factor=1)
        for topic in TOPICS
        if topic not in existing
    ]

    if not to_create:
        print("All topics already exist:")
        for t in TOPICS:
            print(f"  ✓ {t}")
        return

    futures = admin.create_topics(to_create)
    for topic, future in futures.items():
        try:
            future.result()
            print(f"  + created topic '{topic}'")
        except Exception as e:
            if "TOPIC_ALREADY_EXISTS" in str(e):
                print(f"  ✓ topic '{topic}' already exists")
            else:
                print(f"  ✗ failed to create '{topic}': {e}", file=sys.stderr)
                sys.exit(1)

    print("Topics ready.")


if __name__ == "__main__":
    main()