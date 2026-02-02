"""Background worker for continuous data processing.

Handles:
- Continuous classification of new events
- Transcription queue processing
- Periodic digest generation
- Health monitoring

This worker helps you track productivity across all areas of life
by automatically processing and categorizing your digital activities.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path

from lifelogger.core.config import get_settings
from lifelogger.core.database import Database
from lifelogger.core.llm import (
    HybridLLMService,
    classify_events_batch,
    estimate_classification_time,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("lifelogger.worker")


class LifeloggerWorker:
    """Background worker for continuous data processing."""

    def __init__(self):
        self.settings = get_settings()
        self.db: Database | None = None
        self.llm: HybridLLMService | None = None
        self._shutdown = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """Start the worker and all background tasks."""
        logger.info("Starting Lifelogger Worker...")
        logger.info("Goal: Track and optimize productivity across all fields of life")

        # Initialize services
        self.db = Database(self.settings)
        await self.db.connect()
        self.llm = HybridLLMService(self.settings)

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._classification_loop()),
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._stats_reporter_loop()),
        ]

        logger.info("Worker started successfully")

        # Wait for shutdown
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stopping worker...")
        self._shutdown = True

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Close connections
        if self.llm:
            await self.llm.close()
        if self.db:
            await self.db.disconnect()

        logger.info("Worker stopped")

    def _handle_shutdown(self):
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        self._shutdown = True
        for task in self._tasks:
            task.cancel()

    async def _classification_loop(self):
        """Continuously classify unclassified events."""
        logger.info("Classification loop started")

        while not self._shutdown:
            try:
                # Get unclassified events
                unclassified = await self._get_unclassified_events(limit=100)

                if unclassified:
                    logger.info(f"Found {len(unclassified)} unclassified events")

                    # Estimate time
                    estimate = estimate_classification_time(len(unclassified))
                    logger.info(
                        f"Estimated time: {estimate['estimated_seconds']}s "
                        f"({estimate['num_batches']} batches)"
                    )

                    # Classify in batches
                    events_data = [
                        {
                            "app_name": e.get("app_name"),
                            "window_title": e.get("window_title"),
                            "url": e.get("url"),
                            "duration": e.get("duration"),
                        }
                        for e in unclassified
                    ]

                    classifications = await classify_events_batch(
                        self.llm, events_data, batch_size=30, use_cache=True
                    )

                    # Update database
                    updated = 0
                    for event, classification in zip(unclassified, classifications):
                        await self._update_event_classification(
                            event["id"],
                            event["timestamp"],
                            classification.model_dump(),
                        )
                        updated += 1

                    logger.info(f"Classified {updated} events")

                    # Log productivity insights
                    productive = sum(
                        1 for c in classifications if c.is_productive is True
                    )
                    unproductive = sum(
                        1 for c in classifications if c.is_productive is False
                    )
                    logger.info(
                        f"Productivity: {productive} productive, "
                        f"{unproductive} unproductive, "
                        f"{len(classifications) - productive - unproductive} neutral"
                    )
                else:
                    logger.debug("No unclassified events, sleeping...")

                # Sleep before next check
                await asyncio.sleep(60)  # Check every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Classification loop error: {e}")
                await asyncio.sleep(30)  # Back off on error

    async def _get_unclassified_events(self, limit: int = 100) -> list[dict]:
        """Get events that haven't been classified yet."""
        query = """
            SELECT id, timestamp, device_id, source, app_name, window_title,
                   url, duration, data
            FROM activity_events
            WHERE classification IS NULL
            ORDER BY timestamp DESC
            LIMIT $1
        """
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, limit)
            return [dict(row) for row in rows]

    async def _update_event_classification(
        self, event_id: str, timestamp: datetime, classification: dict
    ):
        """Update an event with its classification."""
        import json

        query = """
            UPDATE activity_events
            SET classification = $1
            WHERE id = $2 AND timestamp = $3
        """
        async with self.db.acquire() as conn:
            await conn.execute(query, json.dumps(classification), event_id, timestamp)

    async def _health_check_loop(self):
        """Periodic health checks."""
        logger.info("Health check loop started")

        while not self._shutdown:
            try:
                # Check database
                async with self.db.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                    db_ok = True
            except Exception:
                db_ok = False
                logger.warning("Database health check failed")

            # Check LLM
            try:
                from lifelogger.core.llm import check_provider_status

                status = await check_provider_status(self.settings)
                llm_ok = any(
                    p.get("available")
                    for p in status.get("providers", {}).values()
                )
            except Exception:
                llm_ok = False
                logger.warning("LLM health check failed")

            if db_ok and llm_ok:
                logger.debug("Health check passed")
            else:
                logger.warning(f"Health check: DB={db_ok}, LLM={llm_ok}")

            await asyncio.sleep(300)  # Every 5 minutes

    async def _stats_reporter_loop(self):
        """Periodic productivity stats reporting."""
        logger.info("Stats reporter started")

        while not self._shutdown:
            try:
                # Wait until next hour
                now = datetime.now()
                next_hour = (now + timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0
                )
                sleep_seconds = (next_hour - now).total_seconds()
                await asyncio.sleep(sleep_seconds)

                if self._shutdown:
                    break

                # Get last hour's stats
                stats = await self._get_hourly_stats()
                if stats:
                    logger.info(
                        f"Last hour: {stats['total_events']} events, "
                        f"{stats['productive_minutes']:.0f}m productive, "
                        f"Top app: {stats['top_app']}"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stats reporter error: {e}")
                await asyncio.sleep(60)

    async def _get_hourly_stats(self) -> dict | None:
        """Get statistics for the last hour."""
        query = """
            SELECT
                COUNT(*) as total_events,
                SUM(CASE WHEN classification->>'is_productive' = 'true'
                    THEN duration ELSE 0 END) / 60.0 as productive_minutes,
                MODE() WITHIN GROUP (ORDER BY app_name) as top_app
            FROM activity_events
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(query)
                if row and row["total_events"] > 0:
                    return {
                        "total_events": row["total_events"],
                        "productive_minutes": row["productive_minutes"] or 0,
                        "top_app": row["top_app"] or "Unknown",
                    }
        except Exception as e:
            logger.error(f"Error getting hourly stats: {e}")
        return None


async def main():
    """Run the worker."""
    worker = LifeloggerWorker()
    try:
        await worker.start()
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
