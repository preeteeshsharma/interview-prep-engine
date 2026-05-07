class MockOrchestrator:
    async def run_turn(self, session_id: int, user_message: str) -> str:
        """Route a WhatsApp message through the mock interview flow."""
        pass

    async def end_session(self, session_id: int) -> str:
        """Run Observer + Coach, return summary."""
        pass
