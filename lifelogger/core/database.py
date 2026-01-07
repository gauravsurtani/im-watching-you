"""Database connection and operations for lifelogger.

All data is stored with raw values. Classification is done by LLM
and stored in the classification JSONB field.
"""

from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, AsyncIterator

import asyncpg
from asyncpg import Pool

from lifelogger.core.config import Settings, get_settings


class Database:
    """Async PostgreSQL database wrapper using asyncpg."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._pool: Pool | None = None

    async def connect(self) -> None:
        """Create connection pool."""
        self._pool = await asyncpg.create_pool(
            host=self.settings.db_host,
            port=self.settings.db_port,
            database=self.settings.db_name,
            user=self.settings.db_user,
            password=self.settings.db_password,
            min_size=2,
            max_size=10,
        )

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquire a connection from the pool."""
        if not self._pool:
            raise RuntimeError("Database not connected. Call connect() first.")
        async with self._pool.acquire() as conn:
            yield conn

    async def insert_activity_event(
        self,
        timestamp: datetime,
        device_id: str,
        source: str,
        app_name: str | None = None,
        window_title: str | None = None,
        url: str | None = None,
        duration_seconds: float | None = None,
        data: dict[str, Any] | None = None,
        classification: dict[str, Any] | None = None,
    ) -> int:
        """Insert a single activity event."""
        import orjson

        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO activity_events
                    (timestamp, device_id, source, app_name, window_title, url, duration_seconds, data, classification)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                timestamp,
                device_id,
                source,
                app_name,
                window_title,
                url,
                duration_seconds,
                orjson.dumps(data).decode() if data else None,
                orjson.dumps(classification).decode() if classification else None,
            )
            return row["id"]  # type: ignore

    async def insert_activity_events_batch(
        self, events: list[dict[str, Any]]
    ) -> int:
        """Batch insert activity events. Returns count of inserted rows."""
        import orjson

        if not events:
            return 0

        async with self.acquire() as conn:
            records = [
                (
                    e["timestamp"],
                    e["device_id"],
                    e["source"],
                    e.get("app_name"),
                    e.get("window_title"),
                    e.get("url"),
                    e.get("duration_seconds"),
                    orjson.dumps(e.get("data")).decode() if e.get("data") else None,
                    orjson.dumps(e.get("classification")).decode() if e.get("classification") else None,
                )
                for e in events
            ]
            await conn.executemany(
                """
                INSERT INTO activity_events
                    (timestamp, device_id, source, app_name, window_title, url, duration_seconds, data, classification)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
                """,
                records,
            )
            return len(records)

    async def get_activity_for_date(
        self, target_date: date, device_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all activity events for a specific date."""
        async with self.acquire() as conn:
            if device_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM activity_events
                    WHERE timestamp::date = $1 AND device_id = $2
                    ORDER BY timestamp
                    """,
                    target_date,
                    device_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM activity_events
                    WHERE timestamp::date = $1
                    ORDER BY timestamp
                    """,
                    target_date,
                )
            return [dict(row) for row in rows]

    async def get_app_usage_summary(
        self, target_date: date, device_id: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get top apps by usage duration for a date."""
        async with self.acquire() as conn:
            query = """
                SELECT
                    app_name,
                    SUM(duration_seconds) as total_seconds,
                    COUNT(*) as event_count
                FROM activity_events
                WHERE timestamp::date = $1
                    AND app_name IS NOT NULL
            """
            params: list[Any] = [target_date]

            if device_id:
                query += " AND device_id = $2"
                params.append(device_id)

            query += """
                GROUP BY app_name
                ORDER BY total_seconds DESC
                LIMIT ${}
            """.format(len(params) + 1)
            params.append(limit)

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_transcripts_for_date(self, target_date: date) -> list[dict[str, Any]]:
        """Get all transcripts for a specific date."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM activity_events
                WHERE timestamp::date = $1 AND source = 'transcript'
                ORDER BY timestamp
                """,
                target_date,
            )
            return [dict(row) for row in rows]

    async def get_unclassified_events(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get events that haven't been classified by LLM yet."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, device_id, source, app_name, window_title, url, duration_seconds, data
                FROM activity_events
                WHERE classification IS NULL
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]

    async def update_event_classification(
        self, event_id: int, event_timestamp: datetime, classification: dict[str, Any]
    ) -> None:
        """Update an event with LLM classification."""
        import orjson

        async with self.acquire() as conn:
            await conn.execute(
                """
                UPDATE activity_events
                SET classification = $1
                WHERE id = $2 AND timestamp = $3
                """,
                orjson.dumps(classification).decode(),
                event_id,
                event_timestamp,
            )

    async def batch_update_classifications(
        self, updates: list[tuple[int, datetime, dict[str, Any]]]
    ) -> int:
        """Batch update classifications for multiple events."""
        import orjson

        if not updates:
            return 0

        async with self.acquire() as conn:
            records = [
                (orjson.dumps(classification).decode(), event_id, timestamp)
                for event_id, timestamp, classification in updates
            ]
            await conn.executemany(
                """
                UPDATE activity_events
                SET classification = $1
                WHERE id = $2 AND timestamp = $3
                """,
                records,
            )
            return len(records)

    async def get_events_by_classification(
        self,
        target_date: date,
        event_type: str | None = None,
        category: str | None = None,
        is_productive: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Get events filtered by LLM classification."""
        async with self.acquire() as conn:
            query = """
                SELECT * FROM activity_events
                WHERE timestamp::date = $1
                AND classification IS NOT NULL
            """
            params: list[Any] = [target_date]

            if event_type:
                params.append(event_type)
                query += f" AND classification->>'event_type' = ${len(params)}"

            if category:
                params.append(category)
                query += f" AND classification->>'category' = ${len(params)}"

            if is_productive is not None:
                params.append(str(is_productive).lower())
                query += f" AND classification->>'is_productive' = ${len(params)}"

            query += " ORDER BY timestamp"

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]


async def get_database() -> Database:
    """Get a connected database instance."""
    db = Database()
    await db.connect()
    return db
