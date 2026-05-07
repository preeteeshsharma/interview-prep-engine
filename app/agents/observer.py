from app.schemas.agent_io import RubricScore


class Observer:
    async def score(self, transcript: list[dict]) -> RubricScore:
        pass
