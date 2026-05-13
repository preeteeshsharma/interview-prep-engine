from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RoundType = Literal["DSA", "LLD", "machine_coding", "sysdesign", "behavioral", "hiring_manager", "unknown"]
Rating = Literal["easy", "medium", "hard"]


class InterviewDTO(BaseModel):
    id: int
    company: str
    role: str
    round_type: str | None
    scheduled_for: datetime | None


class PrepPlanDTO(BaseModel):
    id: int
    interview_id: int
    generated_at: datetime
    completed_at: datetime | None
    self_rating: Rating | None
    skipped: bool


class MockSessionDTO(BaseModel):
    id: int
    interview_id: int
    round_type: str
    started_at: datetime
    ended_at: datetime | None
