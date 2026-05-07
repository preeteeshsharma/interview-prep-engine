from app.lib.logging import get_logger

logger = get_logger(__name__)


async def run_morning_drill() -> None:
    """7am IST daily cron. Stub for Block 7."""
    logger.info("morning_drill.started")
