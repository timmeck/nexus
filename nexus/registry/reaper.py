"""Liveness Reaper — marks agents with stale heartbeats as offline."""

import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("nexus.reaper")

REAPER_INTERVAL_SECONDS = 30  # Check every 30 seconds


async def reap_stale_agents() -> int:
    """Single reaper pass: mark stale agents offline. Returns count reaped."""
    from nexus.config import HEARTBEAT_TIMEOUT
    from nexus.database import get_db

    db = await get_db()
    threshold = (datetime.utcnow() - timedelta(seconds=HEARTBEAT_TIMEOUT)).isoformat()

    cursor = await db.execute(
        """UPDATE agents SET status = 'offline'
           WHERE status = 'online'
           AND last_heartbeat IS NOT NULL
           AND last_heartbeat < ?""",
        (threshold,),
    )
    await db.commit()

    if cursor.rowcount > 0:
        log.info("Reaper marked %d stale agents as offline", cursor.rowcount)
    return cursor.rowcount


async def reaper_loop() -> None:
    """Background task: scan agents, mark stale ones offline."""
    while True:
        try:
            await reap_stale_agents()
        except Exception as e:
            log.debug("Reaper cycle error: %s", e)

        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
