from pydantic import BaseModel, Field


class TurnOutput(BaseModel):
    question: str
    follow_up_hints: list[str]
    missing_justifications: list[str]


class RubricScore(BaseModel):
    depth: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    edge_cases: int = Field(ge=1, le=5)
    time_management: int = Field(ge=1, le=5)
    requirements: int = Field(ge=1, le=5)

    def total(self) -> int:
        return self.depth + self.clarity + self.edge_cases + self.time_management + self.requirements


class CritiqueEntry(BaseModel):
    quote_offset: int = Field(ge=0)
    issue: str
    suggestion: str


class Critique(BaseModel):
    entries: list[CritiqueEntry]
    overall_summary: str
