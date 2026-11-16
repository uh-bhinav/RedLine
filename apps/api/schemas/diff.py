import uuid

from pydantic import BaseModel


class DiffRunCreate(BaseModel):
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    suite_id: uuid.UUID


class DiffRunResponse(BaseModel):
    # Phase 5.3 (dashboard v2) -- the created row's id, needed so a caller
    # (the frontend's trigger-diff dialog) can navigate to /diffs/{id}
    # immediately after POSTing. Not returned before this addition.
    id: uuid.UUID
    classification: str
    code_changed: bool
    behavior_changed: bool
    mean_similarity: float
    threshold: float
    per_case_similarity: dict[str, float]
    detail: str
    # Needed for the side-by-side diff viewer to fetch both runs'
    # transcripts (GET /dashboard/runs/{id}). Already stored on BehaviorDiff,
    # just not returned before this.
    eval_run_a_id: uuid.UUID
    eval_run_b_id: uuid.UUID
