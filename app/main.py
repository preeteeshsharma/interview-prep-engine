import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.db.models import Base
from app.db.session import engine
from app.jobs.morning_drill import run_morning_drill
from app.lib.logging import configure_logging, get_logger
from app.routes.health import router as health_router
from app.routes.webhooks.inbox import router as inbox_router
from app.routes.webhooks.twilio import router as twilio_router

configure_logging()
logger = get_logger(__name__)

_scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory exists before SQLite touches it.
    Path("data").mkdir(exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db.tables.created")

    _scheduler.start()
    ist = ZoneInfo("Asia/Kolkata")
    _scheduler.add_job(
        run_morning_drill,
        trigger=CronTrigger(hour=7, minute=0, timezone=ist),
        id="morning_drill",
        replace_existing=True,
    )
    logger.info("scheduler.started")

    yield

    _scheduler.shutdown(wait=False)
    logger.info("scheduler.stopped")


app = FastAPI(title="Interview Prep Engine", lifespan=lifespan)


@app.middleware("http")
async def attach_request_id(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(health_router)
app.include_router(twilio_router)
app.include_router(inbox_router)
