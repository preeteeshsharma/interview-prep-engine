from app.schemas.agent_io import Critique, RubricScore


class Coach:
    async def critique(self, transcript: list[dict], rubric: RubricScore) -> Critique:
        pass
