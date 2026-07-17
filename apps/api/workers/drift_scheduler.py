"""
Drift scheduler (Phase 2 Section 9).

Long-running process that fires run_drift_check() on a configurable cron schedule.
Default: every 6 hours. For testing: set DRIFT_INTERVAL_HOURS=0.0167 (1 minute).

Run from the repo root:
    python -m apps.api.workers.drift_scheduler

In k3d: deployed as a separate Deployment with 1 replica (no autoscaling --
drift checks are intentionally serialized to avoid concurrent LLM cost spikes).
"""
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from apps.api.services.drift.runner import run_drift_check

logger = logging.getLogger("redline.drift_scheduler")

DRIFT_INTERVAL_HOURS = float(os.environ.get("DRIFT_INTERVAL_HOURS", "6"))


def main() -> None:
    scheduler = BlockingScheduler()

    scheduler.add_job(
        run_drift_check,
        trigger=IntervalTrigger(hours=DRIFT_INTERVAL_HOURS),
        id="drift_check",
        name="Model drift detection",
        # run immediately on startup so we don't wait 6 hours for the first check
        next_run_time=__import__("datetime").datetime.now(),
        misfire_grace_time=300,  # if a run is missed by <5 min, run it anyway
        coalesce=True,           # if multiple runs were missed, run once not many
    )

    logger.info(
        f"Drift scheduler started. "
        f"Interval: every {DRIFT_INTERVAL_HOURS}h. "
        f"First run: immediate."
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Drift scheduler stopped.")


if __name__ == "__main__":
    main()