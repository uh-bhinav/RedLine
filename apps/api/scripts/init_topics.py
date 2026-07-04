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