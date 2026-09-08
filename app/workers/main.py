import asyncio
import signal
import time

import structlog
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.modules.inventory.service import sweep_expired
from app.workers.outbox import process_one
from app.core.telemetry import configure_telemetry


async def run() -> None:
    settings = get_settings()
    configure_telemetry(settings)
    configure_logging(settings.log_level)
    logger = structlog.get_logger()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (
            NotImplementedError
        ):  # Windows event loops do not implement add_signal_handler.
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    next_sweep = 0.0
    next_retention = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_sweep:
                async with get_session_factory()() as session:
                    count = await sweep_expired(session)
                    await session.commit()
                logger.info("reservation_sweep", expired_orders=count)
                next_sweep = time.monotonic() + 60
            if time.monotonic() >= next_retention:
                from app.workers.retention import prune_payloads

                async with get_session_factory()() as session:
                    counts = await prune_payloads(session)
                    await session.commit()
                logger.info("retention_sweep", **counts)
                next_retention = time.monotonic() + 86400
            for _ in range(50):
                if stop.is_set() or not await process_one(
                    get_session_factory(), settings
                ):
                    break
        except Exception:
            logger.exception("worker_heartbeat_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
        except TimeoutError:
            pass
    logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(run())
