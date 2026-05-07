from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RoundType = Literal["DSA", "LLD", "sysdesign", "behavioral", "hiring_manager", "unknown"]


class InterviewDTO(BaseModel):
    id: int
    company: str
    role: str
    round_types: list[RoundType]
    scheduled_for: datetime | None
    status: str
    created_at: datetime


class PrepPlanDTO(BaseModel):
    id: int
    interview_id: int
    plan_md: str
    time_budget_min: int
    generated_at: datetime
    completed_at: datetime | None
    self_rating: str | None
    skipped: bool


class MockSessionDTO(BaseModel):
    id: int
    interview_id: int
    round_type: str
    started_at: datetime
    ended_at: datetime | None
