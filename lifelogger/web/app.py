"""FastAPI web application for lifelogger dashboard."""

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from lifelogger.core.config import get_settings
from lifelogger.core.database import Database


# Response models
class AppUsageResponse(BaseModel):
    """App usage statistics response."""
    app_name: str
    total_seconds: float
    total_hours: float
    event_count: int


class EventResponse(BaseModel):
    """Activity event response."""
    id: int
    timestamp: datetime
    device_id: str
    source: str
    app_name: str | None
    window_title: str | None
    url: str | None
    duration_seconds: float | None
    classification: dict[str, Any] | None


class StatsResponse(BaseModel):
    """Daily statistics response."""
    date: date
    total_events: int
    total_hours: float
    top_apps: list[AppUsageResponse]
    devices: list[str]


class SearchResult(BaseModel):
    """Search result item."""
    id: int
    timestamp: datetime
    source: str
    app_name: str | None
    window_title: str | None
    url: str | None
    snippet: str | None
    relevance: float


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Lifelogger Dashboard",
        description="Privacy-first personal activity tracking dashboard",
        version="0.1.0",
    )

    # CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Database connection
    db: Database | None = None

    @app.on_event("startup")
    async def startup():
        nonlocal db
        db = Database(get_settings())
        await db.connect()

    @app.on_event("shutdown")
    async def shutdown():
        if db:
            await db.disconnect()

    # Routes
    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Serve the dashboard home page."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Lifelogger Dashboard</title>
            <style>
                body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
                h1 { color: #333; }
                .card { background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 10px 0; }
                .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
                .stat-value { font-size: 2em; font-weight: bold; color: #2563eb; }
                table { width: 100%; border-collapse: collapse; }
                th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
                a { color: #2563eb; }
            </style>
        </head>
        <body>
            <h1>Lifelogger Dashboard</h1>
            <div class="stats">
                <div class="card">
                    <h3>Today's Activity</h3>
                    <div id="today-stats">Loading...</div>
                </div>
                <div class="card">
                    <h3>Top Apps</h3>
                    <div id="top-apps">Loading...</div>
                </div>
            </div>
            <div class="card">
                <h3>API Endpoints</h3>
                <ul>
                    <li><a href="/docs">/docs</a> - Interactive API documentation</li>
                    <li><a href="/api/stats/today">/api/stats/today</a> - Today's statistics</li>
                    <li><a href="/api/events?limit=10">/api/events</a> - Recent events</li>
                    <li><a href="/api/search?q=code">/api/search?q=code</a> - Search events</li>
                </ul>
            </div>
            <script>
                fetch('/api/stats/today')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('today-stats').innerHTML = `
                            <div class="stat-value">${data.total_hours.toFixed(1)}h</div>
                            <div>${data.total_events} events across ${data.devices.length} devices</div>
                        `;
                        document.getElementById('top-apps').innerHTML = data.top_apps
                            .slice(0, 5)
                            .map(a => `<div>${a.app_name}: ${a.total_hours.toFixed(1)}h</div>`)
                            .join('');
                    })
                    .catch(e => {
                        document.getElementById('today-stats').textContent = 'Error loading stats';
                    });
            </script>
        </body>
        </html>
        """

    @app.get("/api/stats/today", response_model=StatsResponse)
    async def get_today_stats():
        """Get statistics for today."""
        return await get_stats_for_date(date.today())

    @app.get("/api/stats/{target_date}", response_model=StatsResponse)
    async def get_stats_for_date(target_date: date):
        """Get statistics for a specific date."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not connected")

        # Get app usage
        app_usage = await db.get_app_usage_summary(target_date, limit=20)

        # Get all events for the day to calculate totals
        events = await db.get_activity_for_date(target_date)

        total_seconds = sum(e.get("duration_seconds", 0) or 0 for e in events)
        devices = list(set(e["device_id"] for e in events))

        return StatsResponse(
            date=target_date,
            total_events=len(events),
            total_hours=total_seconds / 3600,
            top_apps=[
                AppUsageResponse(
                    app_name=a["app_name"] or "Unknown",
                    total_seconds=a["total_seconds"] or 0,
                    total_hours=(a["total_seconds"] or 0) / 3600,
                    event_count=a["event_count"],
                )
                for a in app_usage
            ],
            devices=devices,
        )

    @app.get("/api/events", response_model=list[EventResponse])
    async def get_events(
        target_date: date | None = Query(None, description="Filter by date"),
        device_id: str | None = Query(None, description="Filter by device"),
        source: str | None = Query(None, description="Filter by source"),
        limit: int = Query(100, le=1000, description="Maximum results"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
    ):
        """Get activity events with optional filters."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not connected")

        query_date = target_date or date.today()
        events = await db.get_activity_for_date(query_date, device_id=device_id)

        # Apply additional filters
        if source:
            events = [e for e in events if e.get("source") == source]

        # Apply pagination
        events = events[offset : offset + limit]

        return [
            EventResponse(
                id=e["id"],
                timestamp=e["timestamp"],
                device_id=e["device_id"],
                source=e["source"],
                app_name=e.get("app_name"),
                window_title=e.get("window_title"),
                url=e.get("url"),
                duration_seconds=e.get("duration_seconds"),
                classification=e.get("classification"),
            )
            for e in events
        ]

    @app.get("/api/search", response_model=list[SearchResult])
    async def search_events(
        q: str = Query(..., min_length=2, description="Search query"),
        days: int = Query(7, le=365, description="Days to search back"),
        limit: int = Query(50, le=200, description="Maximum results"),
    ):
        """Full-text search across events."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not connected")

        # Search using PostgreSQL full-text search
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    timestamp,
                    source,
                    app_name,
                    window_title,
                    url,
                    ts_rank(
                        to_tsvector('english', coalesce(window_title, '') || ' ' || coalesce(app_name, '')),
                        plainto_tsquery('english', $1)
                    ) as relevance
                FROM activity_events
                WHERE timestamp > NOW() - INTERVAL '%s days'
                AND (
                    window_title ILIKE $2
                    OR app_name ILIKE $2
                    OR url ILIKE $2
                    OR data::text ILIKE $2
                )
                ORDER BY relevance DESC, timestamp DESC
                LIMIT $3
                """ % days,
                q,
                f"%{q}%",
                limit,
            )

        return [
            SearchResult(
                id=r["id"],
                timestamp=r["timestamp"],
                source=r["source"],
                app_name=r["app_name"],
                window_title=r["window_title"],
                url=r["url"],
                snippet=_create_snippet(r["window_title"], q),
                relevance=r["relevance"],
            )
            for r in rows
        ]

    @app.get("/api/devices")
    async def get_devices():
        """Get list of registered devices."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not connected")

        async with db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM devices ORDER BY last_sync DESC NULLS LAST"
            )

        return [dict(r) for r in rows]

    @app.get("/api/sources")
    async def get_sources():
        """Get list of data sources with counts."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not connected")

        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT source, COUNT(*) as count
                FROM activity_events
                GROUP BY source
                ORDER BY count DESC
                """
            )

        return [{"source": r["source"], "count": r["count"]} for r in rows]

    return app


def _create_snippet(text: str | None, query: str, max_length: int = 100) -> str | None:
    """Create a snippet highlighting the search query."""
    if not text:
        return None

    # Find query position
    lower_text = text.lower()
    lower_query = query.lower()
    pos = lower_text.find(lower_query)

    if pos == -1:
        return text[:max_length] + "..." if len(text) > max_length else text

    # Extract snippet around the match
    start = max(0, pos - 30)
    end = min(len(text), pos + len(query) + 30)

    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet


# CLI entry point
def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server."""
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host, port=port)
