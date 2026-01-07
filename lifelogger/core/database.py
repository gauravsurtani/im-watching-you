"""Database connection and operations for lifelogger."""

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
        event_type: str,
        app_name: str | None = None,
        window_title: str | None = None,
        duration_seconds: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> int:
        """Insert a single activity event."""
        import orjson

        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO activity_events
                    (timestamp, device_id, event_type, app_name, window_title, duration_seconds, data)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                timestamp,
                device_id,
                event_type,
                app_name,
                window_title,
                duration_seconds,
                orjson.dumps(data).decode() if data else None,
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
                    e["event_type"],
                    e.get("app_name"),
                    e.get("window_title"),
                    e.get("duration_seconds"),
                    orjson.dumps(e.get("data")).decode() if e.get("data") else None,
                )
                for e in events
            ]
            await conn.executemany(
                """
                INSERT INTO activity_events
                    (timestamp, device_id, event_type, app_name, window_title, duration_seconds, data)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
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
                    AND event_type = 'app_usage'
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
                WHERE timestamp::date = $1 AND event_type = 'transcript'
                ORDER BY timestamp
                """,
                target_date,
            )
            return [dict(row) for row in rows]


async def get_database() -> Database:
    """Get a connected database instance."""
    db = Database()
    await db.connect()
    return db
