"""
Drift detection. After every completed eval run we compare its ARS snapshot with the
rolling baseline of the agent's previous snapshots. A drop of more than DROP_THRESHOLD
raises a DriftAlert, typed by what changed underneath:
  * model  -> the model name differs from the previous version, or the code hash is
              identical yet behaviour moved (the provider changed the model silently)
  * prompt -> the code/prompt hash changed
  * metric -> same version, score just regressed
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.models import AgentVersion, ARSSnapshot, DriftAlert, EvalRun
from apps.api.services import ars_engine

DROP_THRESHOLD = 0.10
BASELINE_RUNS = 3


def detect(db: Session, eval_run: EvalRun, snapshot: ARSSnapshot) -> DriftAlert | None:
    version = db.get(AgentVersion, eval_run.agent_version_id)
    history = [s for s in ars_engine.agent_snapshots(db, version.agent_id) if s.id != snapshot.id]
    history = [s for s in history if s.created_at < snapshot.created_at][:BASELINE_RUNS]
    if not history:
        return None

    baseline = sum(s.ars for s in history) / len(history)
    if snapshot.ars >= baseline - DROP_THRESHOLD:
        return None

    prev_version = db.get(AgentVersion, history[0].agent_version_id)
    if prev_version.id == version.id:
        drift_type, why = "metric", "Reliability dropped on an unchanged version"
    elif prev_version.model_name != version.model_name:
        drift_type, why = "model", f"Model changed {prev_version.model_name} -> {version.model_name}"
    elif prev_version.content_hash == version.content_hash:
        drift_type, why = "model", "Code is identical but behaviour changed after a model update"
    else:
        drift_type, why = "prompt", "Behaviour regressed after a prompt/code change"

    alert = DriftAlert(
        agent_id=version.agent_id,
        drift_type=drift_type,
        metric="ars",
        baseline_value=round(baseline, 4),
        current_value=snapshot.ars,
        message=f"{why}: ARS fell below its rolling baseline.",
        eval_run_id=eval_run.id,
    )
    db.add(alert)
    db.commit()
    return alert
