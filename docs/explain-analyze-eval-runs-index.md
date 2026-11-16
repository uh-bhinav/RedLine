# `EXPLAIN ANALYZE` Before/After: `eval_runs` Tenant + Time Index

**Phase 5.5(b) — foundational doc §10.6/§12.** Real, captured `psql` output — not estimated or
fabricated numbers.

## The gap

`eval_runs` is the highest-traffic table in the schema — every eval trigger writes to it, and both
the CLI's `ci-check` and the dashboard query it filtered by tenant, ordered by recency. Despite
that, no migration ever created an index backing `WHERE tenant_id = ? ORDER BY created_at` — the
table had only its primary key (`id`) as an index. `load_runs` already had this exact composite
index pattern (`ix_load_runs_tenant_created`, migration `0007`); `eval_runs` did not.

**Fixed by:** migration `0010_add_eval_runs_tenant_created_index.py` +
`EvalRun.__table_args__` gaining `Index("ix_eval_runs_tenant_created", "tenant_id", "created_at")`
in `apps/api/models/eval.py`.

## Methodology

The table's real row count in local dev was only 58 — too small for Postgres's planner to ever
prefer an index scan (at that size, a sequential scan is genuinely cheaper, and the planner
correctly says so regardless of whether an index exists). To get a realistic before/after at a
scale where the index actually matters, 150,000 synthetic rows were inserted (same real
tenant/agent-version/suite IDs from the seeded reference data, `created_at` randomly distributed
over the past 730 days), the query run before and after the migration, and the synthetic rows then
deleted — real rows referenced by `eval_case_results`, `ars_snapshots`, `behavior_diffs`, or
`drift_snapshots` were explicitly protected from the cleanup.

Query used for both runs:

```sql
EXPLAIN ANALYZE
SELECT * FROM eval_runs
WHERE tenant_id = 'c1caeaf6-d6ab-4f93-99d8-25907cfebd6d'
  AND created_at > now() - interval '7 days'
ORDER BY created_at DESC
LIMIT 20;
```

## Before (no index) — real Seq Scan

```
 Limit  (cost=4878.04..4878.09 rows=20 width=145) (actual time=62.339..62.345 rows=20 loops=1)
   ->  Sort  (cost=4878.04..4887.78 rows=3897 width=145) (actual time=62.337..62.341 rows=20 loops=1)
         Sort Key: created_at DESC
         Sort Method: top-N heapsort  Memory: 35kB
         ->  Seq Scan on eval_runs  (cost=0.00..4774.34 rows=3897 width=145) (actual time=0.029..61.681 rows=1444 loops=1)
               Filter: ((tenant_id = 'c1caeaf6-d6ab-4f93-99d8-25907cfebd6d'::uuid) AND (created_at > (now() - '7 days'::interval)))
               Rows Removed by Filter: 148614
 Planning Time: 0.928 ms
 Execution Time: 62.444 ms
```

Every one of the ~150,000 rows had to be read and filtered — `Rows Removed by Filter: 148614`.

## After (`ix_eval_runs_tenant_created` applied) — real Index Scan

```
 Limit  (cost=0.42..22.96 rows=20 width=145) (actual time=0.148..0.551 rows=20 loops=1)
   ->  Index Scan Backward using ix_eval_runs_tenant_created on eval_runs  (cost=0.42..5695.82 rows=5055 width=145) (actual time=0.147..0.547 rows=20 loops=1)
         Index Cond: ((tenant_id = 'c1caeaf6-d6ab-4f93-99d8-25907cfebd6d'::uuid) AND (created_at > (now() - '7 days'::interval)))
 Planning Time: 4.571 ms
 Execution Time: 0.609 ms
```

The planner now walks the index directly (`Index Scan Backward` — it can read in `created_at DESC`
order straight off the index, which is also why the explicit `Sort` step disappears entirely) and
never touches a row outside the matching range.

## Result

| | Execution Time | Plan |
|---|---|---|
| Before | 62.444 ms | Seq Scan + explicit Sort |
| After | 0.609 ms | Index Scan Backward (no separate sort needed) |

**~102x faster** at 150,000 rows for a query shape (`tenant_id` + recency) that both the CLI gate
check and the dashboard run routinely. The gap widens, not narrows, as the table grows — a
sequential scan's cost is linear in table size; this index scan's cost is not.
