"""MCP Server for Lifelogger - Exposes your life data to Claude.

This server provides Claude Desktop with tools to query your personal
activity data, transcripts, and productivity metrics. All processing
happens locally on your machine.

Usage:
    # Run directly
    python -m lifelogger.mcp.server

    # Or via CLI
    lifelogger mcp-server
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

from lifelogger.core.config import get_settings
from lifelogger.core.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lifelogger.mcp")

# Create MCP server
server = Server("lifelogger")

# Global database connection
_db: Database | None = None


async def get_db() -> Database:
    """Get or create database connection."""
    global _db
    if _db is None:
        settings = get_settings()
        _db = Database(settings)
        await _db.connect()
    return _db


# =============================================================================
# Tool Definitions - What Claude Can Do
# =============================================================================

TOOLS = [
    Tool(
        name="search_activities",
        description="""Search through the user's activity history.
        Use this to find specific activities, apps used, websites visited, or work patterns.
        Examples: "meetings last week", "time on YouTube", "coding sessions".""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (searches app names, window titles, URLs)",
                },
                "days": {
                    "type": "integer",
                    "description": "How many days back to search (default: 7)",
                    "default": 7,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 20)",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_daily_stats",
        description="""Get activity statistics for a specific date.
        Returns total hours tracked, top apps used, productivity breakdown, and device info.
        Use this to understand what the user did on a particular day.""",
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, or 'today', 'yesterday'",
                    "default": "today",
                },
            },
        },
    ),
    Tool(
        name="get_productivity_summary",
        description="""Get productivity metrics over a time period.
        Shows productive vs unproductive time by category, productivity score,
        and trends. Use this to help the user understand their work patterns.""",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)",
                    "default": 7,
                },
            },
        },
    ),
    Tool(
        name="get_recent_activities",
        description="""Get the most recent activities.
        Use this to see what the user has been doing recently or to get context
        about their current work session.""",
        inputSchema={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to look (default: 4)",
                    "default": 4,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum activities to return (default: 30)",
                    "default": 30,
                },
            },
        },
    ),
    Tool(
        name="search_transcripts",
        description="""Search through conversation transcripts.
        Use this to find discussions about specific topics, people mentioned,
        or action items from meetings. Returns relevant excerpts.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for transcript content",
                },
                "days": {
                    "type": "integer",
                    "description": "How many days back to search (default: 30)",
                    "default": 30,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_app_usage",
        description="""Get detailed usage statistics for specific apps.
        Use this to see how much time the user spends on particular applications
        and when they use them most.""",
        inputSchema={
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App name to analyze (partial match supported)",
                },
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 7)",
                    "default": 7,
                },
            },
            "required": ["app_name"],
        },
    ),
    Tool(
        name="compare_periods",
        description="""Compare activity between two time periods.
        Use this to help the user understand changes in their work patterns,
        like 'this week vs last week' or 'this month vs last month'.""",
        inputSchema={
            "type": "object",
            "properties": {
                "period1_start": {
                    "type": "string",
                    "description": "Start date of first period (YYYY-MM-DD)",
                },
                "period1_end": {
                    "type": "string",
                    "description": "End date of first period (YYYY-MM-DD)",
                },
                "period2_start": {
                    "type": "string",
                    "description": "Start date of second period (YYYY-MM-DD)",
                },
                "period2_end": {
                    "type": "string",
                    "description": "End date of second period (YYYY-MM-DD)",
                },
            },
            "required": ["period1_start", "period1_end", "period2_start", "period2_end"],
        },
    ),
    Tool(
        name="get_context_around_time",
        description="""Get activities around a specific timestamp.
        Use this to understand what the user was doing before and after a
        particular moment, like understanding context around a meeting or event.""",
        inputSchema={
            "type": "object",
            "properties": {
                "timestamp": {
                    "type": "string",
                    "description": "Timestamp in ISO format or natural language like '2024-01-15 14:30'",
                },
                "window_minutes": {
                    "type": "integer",
                    "description": "Minutes before and after to include (default: 30)",
                    "default": 30,
                },
            },
            "required": ["timestamp"],
        },
    ),
    Tool(
        name="get_category_breakdown",
        description="""Get time breakdown by category (Work, Entertainment, Social, etc.).
        Use this to help the user understand how they allocate their time across
        different types of activities.""",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 7)",
                    "default": 7,
                },
            },
        },
    ),
]


# =============================================================================
# Tool Implementations
# =============================================================================


async def search_activities(query: str, days: int = 7, limit: int = 20) -> dict[str, Any]:
    """Search activity events."""
    db = await get_db()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                timestamp, device_id, source, app_name, window_title, url,
                duration_seconds, classification
            FROM activity_events
            WHERE timestamp > NOW() - make_interval(days => $1)
              AND (
                  app_name ILIKE $2 OR
                  window_title ILIKE $2 OR
                  url ILIKE $2 OR
                  classification::text ILIKE $2
              )
            ORDER BY timestamp DESC
            LIMIT $3
            """,
            days,
            f"%{query}%",
            limit,
        )

        results = []
        for row in rows:
            results.append({
                "timestamp": row["timestamp"].isoformat(),
                "app": row["app_name"],
                "title": row["window_title"][:100] if row["window_title"] else None,
                "url": row["url"],
                "duration_minutes": round(row["duration_seconds"] / 60, 1) if row["duration_seconds"] else None,
                "category": row["classification"].get("category") if row["classification"] else None,
                "productive": row["classification"].get("is_productive") if row["classification"] else None,
            })

        return {
            "query": query,
            "days_searched": days,
            "results_count": len(results),
            "activities": results,
        }


async def get_daily_stats(date_str: str = "today") -> dict[str, Any]:
    """Get statistics for a specific date."""
    db = await get_db()

    # Parse date
    if date_str == "today":
        target_date = date.today()
    elif date_str == "yesterday":
        target_date = date.today() - timedelta(days=1)
    else:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    async with db.acquire() as conn:
        # Get totals
        totals = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as event_count,
                SUM(duration_seconds) / 3600.0 as total_hours,
                COUNT(DISTINCT device_id) as device_count
            FROM activity_events
            WHERE timestamp::date = $1
            """,
            target_date,
        )

        # Get top apps
        top_apps = await conn.fetch(
            """
            SELECT
                app_name,
                SUM(duration_seconds) / 3600.0 as hours,
                COUNT(*) as sessions
            FROM activity_events
            WHERE timestamp::date = $1 AND app_name IS NOT NULL
            GROUP BY app_name
            ORDER BY hours DESC
            LIMIT 10
            """,
            target_date,
        )

        # Get productivity breakdown
        productivity = await conn.fetch(
            """
            SELECT
                classification->>'category' as category,
                classification->>'is_productive' as productive,
                SUM(duration_seconds) / 3600.0 as hours
            FROM activity_events
            WHERE timestamp::date = $1 AND classification IS NOT NULL
            GROUP BY category, productive
            ORDER BY hours DESC
            """,
            target_date,
        )

        return {
            "date": str(target_date),
            "total_hours": round(totals["total_hours"] or 0, 1),
            "event_count": totals["event_count"],
            "devices_used": totals["device_count"],
            "top_apps": [
                {"app": r["app_name"], "hours": round(r["hours"] or 0, 1), "sessions": r["sessions"]}
                for r in top_apps
            ],
            "by_category": [
                {"category": r["category"], "productive": r["productive"], "hours": round(r["hours"] or 0, 1)}
                for r in productivity
            ],
        }


async def get_productivity_summary(days: int = 7) -> dict[str, Any]:
    """Get productivity metrics."""
    db = await get_db()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                classification->>'category' as category,
                classification->>'is_productive' as is_productive,
                SUM(duration_seconds) / 3600.0 as hours
            FROM activity_events
            WHERE timestamp > NOW() - make_interval(days => $1)
              AND classification IS NOT NULL
            GROUP BY category, is_productive
            """,
            days,
        )

        productive_hours = 0
        unproductive_hours = 0
        neutral_hours = 0
        by_category = {}

        for row in rows:
            cat = row["category"] or "Unknown"
            hours = row["hours"] or 0

            if cat not in by_category:
                by_category[cat] = {"productive": 0, "unproductive": 0, "neutral": 0}

            if row["is_productive"] == "true":
                productive_hours += hours
                by_category[cat]["productive"] += hours
            elif row["is_productive"] == "false":
                unproductive_hours += hours
                by_category[cat]["unproductive"] += hours
            else:
                neutral_hours += hours
                by_category[cat]["neutral"] += hours

        total = productive_hours + unproductive_hours + neutral_hours
        score = round((productive_hours / total * 100) if total > 0 else 0, 1)

        return {
            "period_days": days,
            "productivity_score": score,
            "total_tracked_hours": round(total, 1),
            "productive_hours": round(productive_hours, 1),
            "unproductive_hours": round(unproductive_hours, 1),
            "neutral_hours": round(neutral_hours, 1),
            "by_category": {
                cat: {k: round(v, 1) for k, v in vals.items()}
                for cat, vals in by_category.items()
            },
        }


async def get_recent_activities(hours: int = 4, limit: int = 30) -> dict[str, Any]:
    """Get recent activities."""
    db = await get_db()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                timestamp, app_name, window_title, url, duration_seconds,
                classification->>'category' as category,
                classification->>'description' as description
            FROM activity_events
            WHERE timestamp > NOW() - make_interval(hours => $1)
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            hours,
            limit,
        )

        activities = []
        for row in rows:
            activities.append({
                "time": row["timestamp"].strftime("%H:%M"),
                "app": row["app_name"],
                "title": row["window_title"][:80] if row["window_title"] else None,
                "duration_min": round(row["duration_seconds"] / 60, 1) if row["duration_seconds"] else None,
                "category": row["category"],
                "what": row["description"],
            })

        return {
            "hours_back": hours,
            "count": len(activities),
            "activities": activities,
        }


async def search_transcripts(query: str, days: int = 30, limit: int = 10) -> dict[str, Any]:
    """Search transcript content."""
    db = await get_db()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                timestamp,
                data->>'text' as text,
                classification->>'summary' as summary,
                classification->>'topics' as topics,
                classification->>'action_items' as action_items
            FROM activity_events
            WHERE source = 'transcript'
              AND timestamp > NOW() - make_interval(days => $1)
              AND (
                  data->>'text' ILIKE $2 OR
                  classification->>'summary' ILIKE $2 OR
                  classification::text ILIKE $2
              )
            ORDER BY timestamp DESC
            LIMIT $3
            """,
            days,
            f"%{query}%",
            limit,
        )

        results = []
        for row in rows:
            text = row["text"] or ""
            # Find relevant excerpt
            query_lower = query.lower()
            text_lower = text.lower()
            pos = text_lower.find(query_lower)

            if pos >= 0:
                start = max(0, pos - 100)
                end = min(len(text), pos + len(query) + 100)
                excerpt = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
            else:
                excerpt = text[:200] + "..." if len(text) > 200 else text

            results.append({
                "timestamp": row["timestamp"].isoformat(),
                "excerpt": excerpt,
                "summary": row["summary"],
                "topics": json.loads(row["topics"]) if row["topics"] else [],
                "action_items": json.loads(row["action_items"]) if row["action_items"] else [],
            })

        return {
            "query": query,
            "days_searched": days,
            "results_count": len(results),
            "transcripts": results,
        }


async def get_app_usage(app_name: str, days: int = 7) -> dict[str, Any]:
    """Get usage stats for a specific app."""
    db = await get_db()

    async with db.acquire() as conn:
        # Total usage
        totals = await conn.fetchrow(
            """
            SELECT
                SUM(duration_seconds) / 3600.0 as total_hours,
                COUNT(*) as session_count,
                AVG(duration_seconds) / 60.0 as avg_session_minutes
            FROM activity_events
            WHERE app_name ILIKE $1
              AND timestamp > NOW() - make_interval(days => $2)
            """,
            f"%{app_name}%",
            days,
        )

        # Usage by day
        by_day = await conn.fetch(
            """
            SELECT
                timestamp::date as day,
                SUM(duration_seconds) / 3600.0 as hours
            FROM activity_events
            WHERE app_name ILIKE $1
              AND timestamp > NOW() - make_interval(days => $2)
            GROUP BY day
            ORDER BY day
            """,
            f"%{app_name}%",
            days,
        )

        # Usage by hour of day
        by_hour = await conn.fetch(
            """
            SELECT
                EXTRACT(HOUR FROM timestamp) as hour,
                SUM(duration_seconds) / 3600.0 as hours
            FROM activity_events
            WHERE app_name ILIKE $1
              AND timestamp > NOW() - make_interval(days => $2)
            GROUP BY hour
            ORDER BY hour
            """,
            f"%{app_name}%",
            days,
        )

        return {
            "app_name": app_name,
            "period_days": days,
            "total_hours": round(totals["total_hours"] or 0, 1),
            "session_count": totals["session_count"],
            "avg_session_minutes": round(totals["avg_session_minutes"] or 0, 1),
            "by_day": [
                {"date": str(r["day"]), "hours": round(r["hours"] or 0, 1)}
                for r in by_day
            ],
            "by_hour": [
                {"hour": int(r["hour"]), "hours": round(r["hours"] or 0, 2)}
                for r in by_hour
            ],
        }


async def compare_periods(
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
) -> dict[str, Any]:
    """Compare two time periods."""
    db = await get_db()

    async def get_period_stats(start: str, end: str) -> dict:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    SUM(duration_seconds) / 3600.0 as total_hours,
                    SUM(CASE WHEN classification->>'is_productive' = 'true'
                        THEN duration_seconds ELSE 0 END) / 3600.0 as productive_hours,
                    COUNT(DISTINCT app_name) as unique_apps,
                    COUNT(*) as event_count
                FROM activity_events
                WHERE timestamp >= $1 AND timestamp < $2
                """,
                start_dt,
                end_dt + timedelta(days=1),
            )

            top_apps = await conn.fetch(
                """
                SELECT app_name, SUM(duration_seconds) / 3600.0 as hours
                FROM activity_events
                WHERE timestamp >= $1 AND timestamp < $2 AND app_name IS NOT NULL
                GROUP BY app_name
                ORDER BY hours DESC
                LIMIT 5
                """,
                start_dt,
                end_dt + timedelta(days=1),
            )

            return {
                "total_hours": round(row["total_hours"] or 0, 1),
                "productive_hours": round(row["productive_hours"] or 0, 1),
                "unique_apps": row["unique_apps"],
                "event_count": row["event_count"],
                "top_apps": [{"app": r["app_name"], "hours": round(r["hours"] or 0, 1)} for r in top_apps],
            }

    period1 = await get_period_stats(period1_start, period1_end)
    period2 = await get_period_stats(period2_start, period2_end)

    # Calculate changes
    def pct_change(new, old):
        if old == 0:
            return None
        return round((new - old) / old * 100, 1)

    return {
        "period1": {"start": period1_start, "end": period1_end, **period1},
        "period2": {"start": period2_start, "end": period2_end, **period2},
        "changes": {
            "total_hours_pct": pct_change(period2["total_hours"], period1["total_hours"]),
            "productive_hours_pct": pct_change(period2["productive_hours"], period1["productive_hours"]),
            "total_hours_diff": round(period2["total_hours"] - period1["total_hours"], 1),
            "productive_hours_diff": round(period2["productive_hours"] - period1["productive_hours"], 1),
        },
    }


async def get_context_around_time(timestamp: str, window_minutes: int = 30) -> dict[str, Any]:
    """Get activities around a specific time."""
    db = await get_db()

    # Parse timestamp
    try:
        target_time = datetime.fromisoformat(timestamp)
    except ValueError:
        target_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                timestamp, app_name, window_title, url, duration_seconds,
                classification->>'category' as category,
                classification->>'description' as description
            FROM activity_events
            WHERE timestamp BETWEEN $1 AND $2
            ORDER BY timestamp
            """,
            target_time - timedelta(minutes=window_minutes),
            target_time + timedelta(minutes=window_minutes),
        )

        before = []
        after = []

        for row in rows:
            item = {
                "time": row["timestamp"].strftime("%H:%M:%S"),
                "app": row["app_name"],
                "title": row["window_title"][:60] if row["window_title"] else None,
                "category": row["category"],
                "what": row["description"],
            }

            if row["timestamp"] < target_time:
                before.append(item)
            else:
                after.append(item)

        return {
            "target_time": target_time.isoformat(),
            "window_minutes": window_minutes,
            "before": before[-10:],  # Last 10 before
            "after": after[:10],     # First 10 after
        }


async def get_category_breakdown(days: int = 7) -> dict[str, Any]:
    """Get time breakdown by category."""
    db = await get_db()

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE(classification->>'category', 'Uncategorized') as category,
                SUM(duration_seconds) / 3600.0 as hours,
                COUNT(*) as event_count,
                COUNT(DISTINCT app_name) as unique_apps
            FROM activity_events
            WHERE timestamp > NOW() - make_interval(days => $1)
            GROUP BY category
            ORDER BY hours DESC
            """,
            days,
        )

        total_hours = sum(r["hours"] or 0 for r in rows)

        categories = []
        for row in rows:
            hours = row["hours"] or 0
            categories.append({
                "category": row["category"],
                "hours": round(hours, 1),
                "percentage": round(hours / total_hours * 100, 1) if total_hours > 0 else 0,
                "event_count": row["event_count"],
                "unique_apps": row["unique_apps"],
            })

        return {
            "period_days": days,
            "total_hours": round(total_hours, 1),
            "categories": categories,
        }


# =============================================================================
# MCP Server Handlers
# =============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Execute a tool call."""
    try:
        if name == "search_activities":
            result = await search_activities(**arguments)
        elif name == "get_daily_stats":
            result = await get_daily_stats(**arguments)
        elif name == "get_productivity_summary":
            result = await get_productivity_summary(**arguments)
        elif name == "get_recent_activities":
            result = await get_recent_activities(**arguments)
        elif name == "search_transcripts":
            result = await search_transcripts(**arguments)
        elif name == "get_app_usage":
            result = await get_app_usage(**arguments)
        elif name == "compare_periods":
            result = await compare_periods(**arguments)
        elif name == "get_context_around_time":
            result = await get_context_around_time(**arguments)
        elif name == "get_category_breakdown":
            result = await get_category_breakdown(**arguments)
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")]
            )

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))]
        )

    except Exception as e:
        logger.exception(f"Error executing tool {name}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")]
        )


# =============================================================================
# Server Entry Points
# =============================================================================

async def serve():
    """Run the MCP server."""
    logger.info("Starting Lifelogger MCP Server...")
    logger.info("This server provides Claude with access to your activity data.")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Main entry point."""
    asyncio.run(serve())


if __name__ == "__main__":
    main()
