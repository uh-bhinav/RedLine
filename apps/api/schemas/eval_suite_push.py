import uuid

from pydantic import BaseModel


class EvalSuitePushResponse(BaseModel):
    suite_id: uuid.UUID
    created_suite: bool
    cases_added: int
    cases_updated: int