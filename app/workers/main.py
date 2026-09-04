import asyncio
import signal

import structlog
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops do not implement add_signal_handler.
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    while not stop.is_set():
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
            logger.info("worker_heartbeat")
            # TODO: Consume the outbox here, claiming rows with FOR UPDATE SKIP LOCKED.
        except Exception:
            logger.exception("worker_heartbeat_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass
    logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(run())


