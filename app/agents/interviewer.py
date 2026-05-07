from app.schemas.agent_io import TurnOutput


class Interviewer:
    async def start_session(self, round_type: str, context: str) -> str:
        """Return opening question."""
        pass

    async def next_turn(self, transcript: list[dict], user_reply: str) -> TurnOutput:
        """Return next interviewer turn."""
        pass
