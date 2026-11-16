---
name: sqlalchemy-debugging
description: Debugging SQLAlchemy issues in RedLine — session lifecycle, worker patterns, flush vs commit, migration drift detection, SKIP LOCKED job queue.
---

# SQLAlchemy Debugging — RedLine

Use this skill when:
- A worker reads stale data after committing
- A migration generates an unexpected diff
- A worker crashes and leaves a job stuck in `in_progress`
- You're unsure whether to use `flush()` or `commit()`
- The SKIP LOCKED pattern in `jobqueue.py` is not understood

---

## Pattern 1: Worker Session Lifecycle

Workers create their own sessions (they don't use FastAPI's `get_db` dependency).

**Correct pattern:**

```python
from apps.api.core.db import SessionLocal

def process_one_job():
    db = SessionLocal()
    try:
        # ... load job, process, update status ...
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Job processing failed: {e}")
        raise
    finally:
        db.close()  # ALWAYS — never let sessions leak
```

**Never:**
- Open a session at module level (the connection is held for the lifetime of the process)
- Skip `finally: db.close()` (connection pool exhaustion)
- Call `db.close()` inside the `try` block before `commit()` (closes before flush)

---

## Pattern 2: Reading Stale Data After a Worker Update

**Symptom:** The worker updates a row (`eval_run.status = "running"`, `db.commit()`), then reads it back in the same session — but gets the old value.

**Cause:** SQLAlchemy caches ORM objects in the session's identity map. After a commit, the object is still cached with its pre-commit state.

**Fix: `db.expire()` + `db.refresh()`**

```python
# Update status
eval_run.status = "running"
eval_run.started_at = datetime.utcnow()
db.commit()

# Now re-read from Postgres (not from session cache)
db.expire(eval_run)     # Mark as expired — next access will query DB
db.refresh(eval_run)    # Immediately re-fetch from DB

# eval_run.status is now "running" (from DB, not cache)
assert eval_run.status == "running"
```

**Alternatively:** Use `expire_on_commit=True` (SQLAlchemy default). After any `commit()`, all objects in the session are automatically expired. The next attribute access will trigger a new SELECT.

---

## Pattern 3: `flush()` vs `commit()`

| Operation | What it does | Transaction |
|---|---|---|
| `db.add(obj)` | Registers object for INSERT | Still in transaction |
| `db.flush()` | Sends pending SQL to DB (INSERT/UPDATE) but does NOT commit | Still in transaction, can rollback |
| `db.commit()` | Commits the transaction, makes changes permanent | New transaction starts |
| `db.rollback()` | Rolls back all changes since last commit | New transaction starts |

**Use `flush()` when:**
- You need the DB-generated PK (UUID) before committing
- You need to use the new object's ID in a subsequent ORM relationship within the same transaction

```python
eval_run = EvalRun(tenant_id=auth.tenant_id, ...)
db.add(eval_run)
db.flush()  # Sends INSERT, Postgres assigns eval_run.id
# eval_run.id is now available (UUID from gen_random_uuid())

job = Job(tenant_id=auth.tenant_id, payload={"eval_run_id": str(eval_run.id)})
db.add(job)
db.commit()  # Commits both eval_run and job atomically
```

**Use `commit()` when:**
- You want changes to be visible to other processes
- You're done with a logical unit of work

---

## Pattern 4: SKIP LOCKED — Job Queue Pattern

The `PostgresJobQueue` uses `SELECT ... FOR UPDATE SKIP LOCKED` to claim jobs without blocking other workers.

**Why this matters:**
- Without `SKIP LOCKED`: Worker A and Worker B both read the same `pending` job. Both try to claim it. One succeeds, one gets a deadlock error or processes the same job twice.
- With `SKIP LOCKED`: If Worker A holds a lock on a row, Worker B skips that row and moves to the next `pending` job. Zero blocking, zero duplicates.

**Raw SQL equivalent of what `jobqueue.py` does:**

```sql
-- Worker claims one job atomically
BEGIN;
SELECT id, payload FROM jobs
WHERE status = 'pending' AND job_type = 'eval.requested'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;

-- Worker marks it in_progress
UPDATE jobs SET status = 'in_progress' WHERE id = '<claimed_id>';
COMMIT;
```

**In SQLAlchemy 2.0:**

```python
from sqlalchemy import select, update

stmt = (
    select(Job)
    .where(Job.status == "pending", Job.job_type == "eval.requested")
    .order_by(Job.created_at)
    .with_for_update(skip_locked=True)
    .limit(1)
)
job = db.execute(stmt).scalar_one_or_none()
if job:
    job.status = "in_progress"
    db.commit()
```

---

## Pattern 5: Detecting Migration Drift

**Symptom:** You added a column to an ORM model but forgot to create a migration. The column exists in Python but not in Postgres.

**Check:**

```bash
alembic check
```

Output: `Detected the following changes: Added column 'my_table.new_col'` → a migration is needed.

Output: `No changes in schema detected` → models and DB are in sync.

**Generate a migration:**

```bash
alembic revision --autogenerate -m "add_new_col_to_my_table"
# Review the generated file
cat apps/api/migrations/versions/$(ls -t apps/api/migrations/versions/ | head -1)
alembic upgrade head
```

**Common autogenerate failures:**

1. **Model not imported** — if `MyNewModel` is not imported in `apps/api/models/__init__.py`, `Base.metadata` doesn't know about it and autogenerate won't detect the new table.

2. **`alembic.ini` points to wrong migration directory** — check:
   ```ini
   [alembic]
   script_location = apps/api/migrations
   ```

3. **ClickHouse tables detected as drift** — autogenerate only looks at Postgres (via `Base.metadata`). ClickHouse tables are created manually and are not in `Base.metadata`.

---

## Pattern 6: Debugging `DetachedInstanceError`

**Symptom:** `DetachedInstanceError: Instance <EvalRun> is not bound to a Session; attribute refresh operation cannot proceed`

**Cause:** The ORM object was loaded in one session (e.g., inside a `with_for_update()` transaction), the session was closed, and then code outside the session tried to access a lazy-loaded relationship.

**Fix Option A — Eager loading:**

```python
from sqlalchemy.orm import selectinload

stmt = select(EvalRun).options(
    selectinload(EvalRun.case_results),  # Eagerly load before session closes
).where(EvalRun.id == run_id)
eval_run = db.execute(stmt).scalar_one()
```

**Fix Option B — Keep the session open:**

```python
db = SessionLocal()
try:
    eval_run = db.execute(select(EvalRun).where(...)).scalar_one()
    # Use eval_run and ALL its relationships while db is open
    process(eval_run, db)  # Pass db into functions that need it
finally:
    db.close()
```

**Never** pass ORM objects out of a closed session if you plan to access their relationships.
