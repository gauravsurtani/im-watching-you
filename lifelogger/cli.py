"""Command-line interface for lifelogger.

All classification and analysis is LLM-powered - no regex or rule-based heuristics.
"""

import asyncio
from datetime import date, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
@click.version_option()
def main():
    """Lifelogger - Privacy-first personal second brain.

    All categorization and classification is powered by local LLM.
    """
    pass


@main.command()
@click.option("--activity-dir", type=click.Path(exists=True, path_type=Path), help="Activity data directory")
@click.option("--transcripts-dir", type=click.Path(exists=True, path_type=Path), help="Transcripts directory")
@click.option("--classify/--no-classify", default=False, help="Run LLM classification during ingestion")
@click.option("--analyze/--no-analyze", default=False, help="Run LLM analysis on transcripts")
def ingest(activity_dir: Path | None, transcripts_dir: Path | None, classify: bool, analyze: bool):
    """Ingest synced data files into the database.

    By default, data is ingested raw without classification. Use --classify
    to run LLM classification during ingestion (slower but more convenient).
    """
    from lifelogger.core.ingest import IngestService

    async def run():
        service = IngestService()

        status_msg = "Ingesting data"
        if classify:
            status_msg += " with LLM classification"
        if analyze:
            status_msg += " with transcript analysis"
        status_msg += "..."

        with console.status(status_msg):
            if activity_dir:
                results = {"activity": await service.ingest_activity_files(activity_dir, classify=classify)}
                results["summary"] = {"activity_events": sum(v for v in results["activity"].values() if v > 0)}
            elif transcripts_dir:
                results = {"transcripts": await service.ingest_transcript_files(transcripts_dir, analyze=analyze)}
                results["summary"] = {"transcripts": sum(v for v in results["transcripts"].values() if v > 0)}
            else:
                results = await service.run_full_ingest(classify=classify, analyze_transcripts=analyze)

        summary = results.get("summary", {})
        console.print(f"[green]Ingestion complete![/green]")
        console.print(f"  Activity events: {summary.get('activity_events', 0)}")
        console.print(f"  Transcripts: {summary.get('transcripts', 0)}")
        console.print(f"  Files processed: {summary.get('files_processed', 0)}")
        if classify or analyze:
            console.print(f"  LLM classification: {'enabled' if classify else 'disabled'}")
            console.print(f"  LLM analysis: {'enabled' if analyze else 'disabled'}")

    asyncio.run(run())


@main.command()
@click.option("--batch-size", default=50, help="Events to classify per LLM batch")
@click.option("--max-events", default=500, help="Maximum events to classify")
def classify(batch_size: int, max_events: int):
    """Classify unclassified events using LLM.

    This can be run as a catch-up job to classify events that were
    ingested without the --classify flag.
    """
    from lifelogger.core.ingest import IngestService

    async def run():
        service = IngestService()

        with console.status(f"Classifying up to {max_events} events..."):
            count = await service.classify_unclassified_events(
                batch_size=batch_size,
                max_events=max_events,
            )

        console.print(f"[green]Classification complete![/green]")
        console.print(f"  Events classified: {count}")

    asyncio.run(run())


@main.command()
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]),
              default=str(date.today()), help="Date to generate digest for (YYYY-MM-DD)")
@click.option("--send/--no-send", default=False, help="Send notification after generation")
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Save digest to file")
def digest(target_date: datetime, send: bool, output: Path | None):
    """Generate a daily digest using LLM."""
    from lifelogger.exporters.digest import DigestGenerator, render_digest_markdown
    from lifelogger.exporters.notifications import NotificationService

    async def run():
        generator = DigestGenerator()

        with console.status(f"Generating digest for {target_date.date()} (LLM-powered)..."):
            digest_result = await generator.generate_digest(target_date.date())

        markdown = render_digest_markdown(digest_result)
        console.print(markdown)

        if output:
            output.write_text(markdown)
            console.print(f"\n[dim]Saved to {output}[/dim]")

        if send:
            with console.status("Sending notification..."):
                notifier = NotificationService()
                success = await notifier.send_digest(digest_result)
                if success:
                    console.print("[green]Notification sent![/green]")
                else:
                    console.print("[red]Failed to send notification[/red]")

    asyncio.run(run())


@main.command()
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]),
              default=str(date.today()), help="Date to show stats for (YYYY-MM-DD)")
@click.option("--device", help="Filter by device ID")
@click.option("--limit", default=10, help="Number of apps to show")
def stats(target_date: datetime, device: str | None, limit: int):
    """Show activity statistics."""
    from lifelogger.core.database import Database

    async def run():
        db = Database()
        await db.connect()

        app_usage = await db.get_app_usage_summary(target_date.date(), device_id=device, limit=limit)

        if not app_usage:
            console.print("[yellow]No activity data found for this date.[/yellow]")
            return

        table = Table(title=f"App Usage - {target_date.date()}")
        table.add_column("App", style="cyan")
        table.add_column("Time", style="green", justify="right")
        table.add_column("Events", justify="right")

        for row in app_usage:
            hours = row["total_seconds"] / 3600
            if hours >= 1:
                time_str = f"{hours:.1f}h"
            else:
                time_str = f"{row['total_seconds'] / 60:.0f}m"
            table.add_row(row["app_name"] or "Unknown", time_str, str(row["event_count"]))

        console.print(table)

        await db.disconnect()

    asyncio.run(run())


@main.command()
def devices():
    """List registered devices."""
    from lifelogger.core.database import Database

    async def run():
        db = Database()
        await db.connect()

        async with db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM devices ORDER BY last_sync DESC NULLS LAST"
            )

        if not rows:
            console.print("[yellow]No devices registered yet.[/yellow]")
            return

        table = Table(title="Registered Devices")
        table.add_column("Device ID", style="cyan")
        table.add_column("Platform")
        table.add_column("Last Sync")
        table.add_column("Active")

        for row in rows:
            last_sync = row["last_sync"].strftime("%Y-%m-%d %H:%M") if row["last_sync"] else "Never"
            active = "[green]Yes[/green]" if row["is_active"] else "[red]No[/red]"
            table.add_row(row["device_id"], row["platform"], last_sync, active)

        console.print(table)

        await db.disconnect()

    asyncio.run(run())


@main.command()
@click.argument("message")
@click.option("--title", "-t", default="Lifelogger Alert", help="Notification title")
def notify(message: str, title: str):
    """Send a test notification."""
    from lifelogger.exporters.notifications import NotificationService

    async def run():
        notifier = NotificationService()
        success = await notifier.send_alert(title, message)
        if success:
            console.print("[green]Notification sent![/green]")
        else:
            console.print("[red]Failed to send notification[/red]")

    asyncio.run(run())


@main.command("weekly-digest")
@click.option("--weeks-back", default=0, help="Weeks back from current week (0 = this week)")
@click.option("--send/--no-send", default=False, help="Send notification after generation")
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Save digest to file")
def weekly_digest(weeks_back: int, send: bool, output: Path | None):
    """Generate a weekly digest using LLM."""
    from datetime import timedelta
    from lifelogger.exporters.digest import DigestGenerator, render_digest_markdown

    async def run():
        generator = DigestGenerator()

        # Calculate week start (Monday)
        today = date.today()
        week_start = today - timedelta(days=today.weekday() + (weeks_back * 7))
        week_end = week_start + timedelta(days=6)

        with console.status(f"Generating weekly digest for {week_start} to {week_end} (LLM-powered)..."):
            # Generate digests for each day of the week
            all_digests = []
            for day_offset in range(7):
                day = week_start + timedelta(days=day_offset)
                if day <= today:
                    try:
                        day_digest = await generator.generate_digest(day)
                        all_digests.append((day, day_digest))
                    except Exception as e:
                        console.print(f"[yellow]Skipping {day}: {e}[/yellow]")

        # Combine into weekly summary
        console.print(f"\n[bold]Weekly Digest: {week_start} - {week_end}[/bold]\n")

        for day, digest_result in all_digests:
            console.print(f"[cyan]== {day.strftime('%A, %B %d')} ==[/cyan]")
            markdown = render_digest_markdown(digest_result)
            console.print(markdown)
            console.print()

        if output:
            full_content = f"# Weekly Digest: {week_start} - {week_end}\n\n"
            for day, digest_result in all_digests:
                full_content += f"## {day.strftime('%A, %B %d')}\n\n"
                full_content += render_digest_markdown(digest_result) + "\n\n"
            output.write_text(full_content)
            console.print(f"[dim]Saved to {output}[/dim]")

        if send:
            from lifelogger.exporters.notifications import NotificationService
            with console.status("Sending notification..."):
                notifier = NotificationService()
                # Send summary of the week
                if all_digests:
                    success = await notifier.send_alert(
                        f"Weekly Digest: {week_start} - {week_end}",
                        f"Generated digests for {len(all_digests)} days. Check your dashboard for details."
                    )
                    if success:
                        console.print("[green]Notification sent![/green]")
                    else:
                        console.print("[red]Failed to send notification[/red]")

    asyncio.run(run())


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def web(host: str, port: int, reload: bool):
    """Start the web dashboard server."""
    import uvicorn
    from lifelogger.web.app import create_app

    console.print(f"[bold]Starting Lifelogger Dashboard[/bold]")
    console.print(f"  URL: http://{host}:{port}")
    console.print(f"  API Docs: http://{host}:{port}/docs")
    console.print()

    if reload:
        uvicorn.run("lifelogger.web.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        app = create_app()
        uvicorn.run(app, host=host, port=port)


@main.command("import-browser")
@click.option("--browser", type=click.Choice(["chrome", "firefox", "auto"]), default="auto",
              help="Browser to import from")
@click.option("--profile", help="Browser profile name (uses default if not specified)")
@click.option("--days", default=30, help="Days of history to import")
@click.option("--classify/--no-classify", default=False, help="Run LLM classification")
def import_browser(browser: str, profile: str | None, days: int, classify: bool):
    """Import browser history from Chrome or Firefox."""
    from datetime import timedelta
    from lifelogger.sources.browser import BrowserHistorySource
    from lifelogger.core.database import Database

    async def run():
        source = BrowserHistorySource()
        db = Database()
        await db.connect()

        since = datetime.now() - timedelta(days=days)

        with console.status(f"Importing browser history from last {days} days..."):
            if browser == "auto":
                events = await source.import_all_browsers(since=since)
            elif browser == "chrome":
                events = await source.import_chrome(profile_name=profile, since=since)
            else:
                events = await source.import_firefox(profile_name=profile, since=since)

        if not events:
            console.print("[yellow]No browser history found.[/yellow]")
            return

        with console.status(f"Saving {len(events)} events to database..."):
            await db.insert_activity_events_batch(events)

        console.print(f"[green]Imported {len(events)} browser history events![/green]")

        if classify:
            from lifelogger.core.ingest import IngestService
            service = IngestService()
            with console.status("Running LLM classification..."):
                count = await service.classify_unclassified_events(max_events=len(events))
            console.print(f"  Classified: {count} events")

        await db.disconnect()

    asyncio.run(run())


@main.command("import-calendar")
@click.argument("ics_path", type=click.Path(exists=True, path_type=Path))
@click.option("--days-back", default=30, help="Days back to import")
@click.option("--days-forward", default=7, help="Days forward to import")
def import_calendar(ics_path: Path, days_back: int, days_forward: int):
    """Import calendar events from an ICS file."""
    from datetime import timedelta
    from lifelogger.sources.calendar import CalendarSource
    from lifelogger.core.database import Database

    async def run():
        source = CalendarSource()
        db = Database()
        await db.connect()

        since = datetime.now() - timedelta(days=days_back)
        until = datetime.now() + timedelta(days=days_forward)

        with console.status(f"Importing calendar events from {ics_path}..."):
            events = await source.import_ics(ics_path, since=since, until=until)

        if not events:
            console.print("[yellow]No calendar events found in the specified range.[/yellow]")
            return

        with console.status(f"Saving {len(events)} events to database..."):
            await db.insert_activity_events_batch(events)

        console.print(f"[green]Imported {len(events)} calendar events![/green]")

        await db.disconnect()

    asyncio.run(run())


@main.command()
@click.argument("query")
@click.option("--days", default=7, help="Days to search back")
@click.option("--limit", default=20, help="Maximum results")
@click.option("--fuzzy/--no-fuzzy", default=False, help="Use fuzzy matching")
def search(query: str, days: int, limit: int, fuzzy: bool):
    """Search activity events using full-text search."""
    from lifelogger.core.database import Database

    async def run():
        db = Database()
        await db.connect()

        with console.status(f"Searching for '{query}'..."):
            async with db.acquire() as conn:
                if fuzzy:
                    # Fuzzy search using trigrams
                    rows = await conn.fetch(
                        """
                        SELECT
                            id, timestamp, source, app_name, window_title, url,
                            GREATEST(
                                similarity(window_title, $1),
                                similarity(app_name, $1)
                            ) as relevance
                        FROM activity_events
                        WHERE timestamp > NOW() - INTERVAL '%s days'
                        AND (
                            similarity(window_title, $1) > 0.3
                            OR similarity(app_name, $1) > 0.3
                        )
                        ORDER BY relevance DESC, timestamp DESC
                        LIMIT $2
                        """ % days,
                        query, limit
                    )
                else:
                    # Full-text search with ILIKE fallback
                    rows = await conn.fetch(
                        """
                        SELECT
                            id, timestamp, source, app_name, window_title, url,
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
                        )
                        ORDER BY relevance DESC, timestamp DESC
                        LIMIT $3
                        """ % days,
                        query, f"%{query}%", limit
                    )

        if not rows:
            console.print(f"[yellow]No results found for '{query}'[/yellow]")
            return

        table = Table(title=f"Search Results: '{query}'")
        table.add_column("Time", style="dim")
        table.add_column("Source", style="cyan")
        table.add_column("App")
        table.add_column("Title/URL")
        table.add_column("Score", justify="right")

        for row in rows:
            timestamp = row["timestamp"].strftime("%m/%d %H:%M")
            title = row["window_title"] or row["url"] or "-"
            if len(title) > 50:
                title = title[:47] + "..."
            table.add_row(
                timestamp,
                row["source"],
                row["app_name"] or "-",
                title,
                f"{row['relevance']:.2f}"
            )

        console.print(table)
        console.print(f"\n[dim]Found {len(rows)} results[/dim]")

        await db.disconnect()

    asyncio.run(run())


@main.command()
@click.option("--days", default=90, help="Days of data to retain")
@click.option("--archive/--no-archive", default=True, help="Archive before deleting")
@click.option("--dry-run/--execute", default=True, help="Show what would be deleted without actually deleting")
def cleanup(days: int, archive: bool, dry_run: bool):
    """Clean up old data from the database."""
    from datetime import timedelta
    from lifelogger.core.database import Database

    async def run():
        db = Database()
        await db.connect()

        cutoff = datetime.now() - timedelta(days=days)

        async with db.acquire() as conn:
            # Count events to delete
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM activity_events WHERE timestamp < $1",
                cutoff
            )

        if count == 0:
            console.print(f"[green]No events older than {days} days found.[/green]")
            return

        console.print(f"Found [bold]{count}[/bold] events older than {cutoff.date()}")

        if dry_run:
            console.print("[yellow]Dry run - no changes made. Use --execute to actually delete.[/yellow]")
            return

        if archive:
            console.print("[dim]Archiving is handled by data_retention.py script[/dim]")

        with console.status("Deleting old events..."):
            async with db.acquire() as conn:
                await conn.execute(
                    "DELETE FROM activity_events WHERE timestamp < $1",
                    cutoff
                )

        console.print(f"[green]Deleted {count} events![/green]")

        await db.disconnect()

    asyncio.run(run())


@main.command("llm-status")
def llm_status():
    """Check LLM provider status and configuration."""
    from lifelogger.core.llm import check_provider_status, OpenRouterProvider
    from lifelogger.core.config import get_settings
    from lifelogger.core.models_config import (
        TaskType,
        get_model_for_task,
        get_preset,
        PRESETS,
    )

    async def run():
        settings = get_settings()
        console.print("[bold]LLM Provider Status[/bold]\n")

        with console.status("Checking providers..."):
            status = await check_provider_status(settings)

        # Strategy
        strategy_colors = {
            "local": "green",
            "cloud": "cyan",
            "hybrid": "yellow",
            "cloud_fallback": "magenta",
        }
        strategy = status["strategy"]
        color = strategy_colors.get(strategy, "white")
        console.print(f"Strategy: [{color}]{strategy}[/{color}]")

        strategy_descriptions = {
            "local": "All processing done locally via Ollama (maximum privacy)",
            "cloud": "All processing via OpenRouter cloud (no GPU needed)",
            "hybrid": "Cloud for classification, local for sensitive data",
            "cloud_fallback": "Try local first, fall back to cloud on failure",
        }
        console.print(f"  [dim]{strategy_descriptions.get(strategy, '')}[/dim]\n")

        # Providers
        providers = status["providers"]

        # Ollama
        ollama = providers.get("ollama", {})
        if ollama.get("available"):
            console.print("[green]Ollama:[/green] Available")
            console.print(f"  URL: {ollama.get('url')}")
            console.print(f"  Model: {ollama.get('model')}")
            models = ollama.get("installed_models", [])
            if models:
                console.print(f"  Installed: {', '.join(models[:5])}" + ("..." if len(models) > 5 else ""))
        else:
            console.print(f"[red]Ollama:[/red] Not available - {ollama.get('error', 'Unknown error')}")

        console.print()

        # OpenRouter
        openrouter = providers.get("openrouter", {})
        if openrouter.get("available"):
            console.print("[green]OpenRouter:[/green] Available")
            console.print(f"  Model: {openrouter.get('model')}")
            console.print(f"  Fallback: {openrouter.get('fallback_model')}")
            console.print(f"  Rate limit: {openrouter.get('rate_limit')} req/min")
        else:
            console.print(f"[yellow]OpenRouter:[/yellow] Not available - {openrouter.get('error', 'Unknown error')}")

        console.print()

        # Model Configuration
        console.print("[bold]Model Configuration:[/bold]")
        preset = get_preset(settings.model_preset)
        if preset:
            console.print(f"  Preset: [cyan]{preset.name}[/cyan]")
            console.print(f"    [dim]{preset.description}[/dim]")
        else:
            console.print(f"  Preset: {settings.model_preset}")

        console.print("\n  [bold]Task-Specific Models:[/bold]")
        task_display = {
            TaskType.EVENT_CLASSIFICATION: "Classification",
            TaskType.BATCH_CLASSIFICATION: "Batch Classification",
            TaskType.TRANSCRIPT_ANALYSIS: "Transcript Analysis",
            TaskType.DIGEST_GENERATION: "Digest Generation",
            TaskType.URL_ANALYSIS: "URL Analysis",
            TaskType.GENERAL: "General",
        }

        for task_type, display_name in task_display.items():
            model_spec = get_model_for_task(task_type, preset=settings.model_preset)
            # Check for overrides
            override_map = {
                TaskType.EVENT_CLASSIFICATION: settings.model_classification,
                TaskType.BATCH_CLASSIFICATION: settings.model_classification,
                TaskType.TRANSCRIPT_ANALYSIS: settings.model_analysis,
                TaskType.DIGEST_GENERATION: settings.model_digest,
                TaskType.URL_ANALYSIS: settings.model_classification,
                TaskType.GENERAL: settings.model_general,
            }
            override = override_map.get(task_type)
            if override:
                console.print(f"    {display_name}: [yellow]{override}[/yellow] (override)")
            else:
                console.print(f"    {display_name}: {model_spec.name} [{model_spec.speed}]")

        console.print()

        # Available presets
        console.print("[bold]Available Presets:[/bold]")
        for name, p in PRESETS.items():
            marker = " <--" if name == settings.model_preset else ""
            console.print(f"  {name}: {p.description}{marker}")

        console.print()

        # Free models info
        console.print("[bold]Free OpenRouter Models:[/bold]")
        for model in OpenRouterProvider.FREE_MODELS[:6]:
            console.print(f"  - {model}")
        console.print(f"  ... and {len(OpenRouterProvider.FREE_MODELS) - 6} more")

        console.print("\n[dim]Get a free API key at: https://openrouter.ai/keys[/dim]")

        # Privacy settings
        console.print("\n[bold]Privacy Settings:[/bold]")
        console.print(f"  Transcripts local only: {'Yes' if settings.privacy_local_transcripts else 'No'}")
        console.print(f"  URLs local only: {'Yes' if settings.privacy_local_urls else 'No'}")
        console.print(f"  Window titles local only: {'Yes' if settings.privacy_local_window_titles else 'No'}")
        console.print(f"  Digests local only: {'Yes' if settings.privacy_local_digests else 'No'}")

    asyncio.run(run())


@main.command()
def setup():
    """Interactive setup wizard."""
    console.print("[bold]Lifelogger Setup[/bold]\n")

    console.print("1. Start the Docker services:")
    console.print("   [dim]cd docker && docker compose up -d[/dim]\n")

    console.print("2. Wait for services to be healthy:")
    console.print("   [dim]docker compose ps[/dim]\n")

    console.print("3. Configure LLM (choose one):")
    console.print("   [cyan]Option A: OpenRouter (Free, no GPU needed)[/cyan]")
    console.print("   - Get free API key: https://openrouter.ai/keys")
    console.print("   - Add to .env: LIFELOGGER_OPENROUTER_API_KEY=your_key")
    console.print("   - Set: LIFELOGGER_LLM_PROVIDER=cloud")
    console.print()
    console.print("   [green]Option B: Ollama (Local, requires GPU)[/green]")
    console.print("   [dim]docker exec lifelogger-ollama ollama pull qwen2.5:7b[/dim]")
    console.print("   - Set: LIFELOGGER_LLM_PROVIDER=local")
    console.print()
    console.print("   [yellow]Option C: Hybrid (Best of both)[/yellow]")
    console.print("   - Set up both Ollama and OpenRouter")
    console.print("   - Set: LIFELOGGER_LLM_PROVIDER=hybrid")
    console.print("   - Cloud handles classification, local handles sensitive data\n")

    console.print("4. Set up Syncthing:")
    console.print("   - Open http://localhost:8384")
    console.print("   - Add your client devices")
    console.print("   - Configure folders to sync to ~/Syncthing/lifelogger\n")

    console.print("5. Install on client devices:")
    console.print("   - Install ActivityWatch: https://activitywatch.net")
    console.print("   - Install Syncthing: https://syncthing.net")
    console.print("   - Copy scripts/clients/export_activitywatch.py")
    console.print("   - Set up scheduled task to run the export script\n")

    console.print("6. Set up cron jobs on server (example):")
    console.print("   [dim]# Hourly data ingestion (fast, no classification)[/dim]")
    console.print("   [dim]0 * * * * cd /path/to/im-watching-you && python -m lifelogger ingest[/dim]")
    console.print("   [dim]# Daily classification catch-up[/dim]")
    console.print("   [dim]0 6 * * * cd /path/to/im-watching-you && python -m lifelogger classify[/dim]")
    console.print("   [dim]# Daily digest at 7 AM[/dim]")
    console.print("   [dim]0 7 * * * cd /path/to/im-watching-you && python -m lifelogger digest --send[/dim]")
    console.print("   [dim]# Weekly digest on Sundays[/dim]")
    console.print("   [dim]0 10 * * 0 cd /path/to/im-watching-you && python -m lifelogger weekly-digest --send[/dim]")

    console.print("\n7. [Optional] Connect to Claude Desktop:")
    console.print("   - Run: lifelogger mcp-server (to test)")
    console.print("   - Add to Claude Desktop config (see README)")
    console.print("   - Ask Claude: 'What was I working on yesterday?'")


@main.command("mcp-server")
def mcp_server():
    """Start the MCP server for Claude Desktop integration.

    This allows Claude to query your activity data directly.
    Add this server to your Claude Desktop configuration to enable
    questions like 'What was I working on last week?'
    """
    from lifelogger.mcp.server import main as run_mcp
    console.print("[bold]Starting Lifelogger MCP Server...[/bold]")
    console.print("Claude Desktop can now access your activity data.")
    console.print("Press Ctrl+C to stop.\n")
    run_mcp()


@main.command()
def health():
    """Run comprehensive system health check.

    Checks all components: database, LLM providers, Syncthing,
    ActivityWatch data. Shows what's working and what needs fixing.
    """
    from lifelogger.core.diagnostics import (
        run_full_health_check,
        get_troubleshooting_steps,
        HealthStatus,
    )

    async def run():
        console.print("[bold]Lifelogger System Health Check[/bold]\n")

        with console.status("Checking all components..."):
            health_report = await run_full_health_check()

        # Overall status
        status_colors = {
            HealthStatus.HEALTHY: "green",
            HealthStatus.DEGRADED: "yellow",
            HealthStatus.UNHEALTHY: "red",
            HealthStatus.UNKNOWN: "dim",
        }
        status_icons = {
            HealthStatus.HEALTHY: "✓",
            HealthStatus.DEGRADED: "⚠",
            HealthStatus.UNHEALTHY: "✗",
            HealthStatus.UNKNOWN: "?",
        }

        color = status_colors[health_report.status]
        icon = status_icons[health_report.status]
        console.print(f"Overall Status: [{color}]{icon} {health_report.status.value.upper()}[/{color}]\n")

        # Component details
        console.print("[bold]Components:[/bold]")
        for component in health_report.components:
            c_color = status_colors[component.status]
            c_icon = status_icons[component.status]
            console.print(f"  [{c_color}]{c_icon}[/{c_color}] {component.name}: {component.message}")

            if component.details:
                for key, value in component.details.items():
                    if value is not None:
                        console.print(f"      [dim]{key}: {value}[/dim]")

        # Troubleshooting steps
        steps = get_troubleshooting_steps(health_report)
        if steps:
            console.print("\n[bold yellow]Suggested Fixes:[/bold yellow]")
            for i, step in enumerate(steps, 1):
                console.print(f"  {i}. {step}")

        # Quick tips
        if health_report.status == HealthStatus.HEALTHY:
            console.print("\n[green]All systems operational![/green]")
        else:
            console.print("\n[dim]Run 'lifelogger health' again after making fixes.[/dim]")

    asyncio.run(run())


@main.command()
@click.option("--app", "-a", required=True, help="App name (e.g., 'VS Code', 'Chrome')")
@click.option("--title", "-t", default="", help="Window title or description")
@click.option("--duration", "-d", type=int, default=30, help="Duration in minutes (default: 30)")
@click.option("--category", "-c", default=None, help="Category (Work, Entertainment, etc.)")
@click.option("--productive/--not-productive", default=None, help="Mark as productive or not")
@click.option("--note", "-n", default=None, help="Additional note")
def log(app: str, title: str, duration: int, category: str | None, productive: bool | None, note: str | None):
    """Manually log an activity when automatic tracking fails.

    Use this when ActivityWatch isn't running, you're on a device
    without tracking, or you want to log something that wasn't captured.

    Examples:
        lifelogger log -a "Meeting" -t "Project standup" -d 30 -c Work --productive
        lifelogger log -a "Reading" -t "Design Patterns book" -d 60 -c Learning
        lifelogger log -a "Break" -t "Lunch" -d 45 --not-productive
    """
    from datetime import datetime, timedelta
    from lifelogger.core.database import Database
    from lifelogger.core.config import get_settings
    import uuid

    async def run():
        settings = get_settings()
        db = Database(settings)
        await db.connect()

        # Create event
        now = datetime.now()
        event = {
            "timestamp": now - timedelta(minutes=duration),  # Started 'duration' ago
            "device_id": "manual",
            "source": "manual_log",
            "app_name": app,
            "window_title": title or None,
            "url": None,
            "duration_seconds": duration * 60,
            "data": {"note": note} if note else None,
            "classification": {
                "event_type": "manual",
                "category": category or "Uncategorized",
                "subcategory": None,
                "is_productive": productive,
                "description": title or app,
                "confidence": 1.0,
            } if category or productive is not None else None,
        }

        try:
            await db.insert_activity_event(**event)
            console.print(f"[green]✓ Logged:[/green] {app}")
            console.print(f"  Duration: {duration} minutes")
            if title:
                console.print(f"  Title: {title}")
            if category:
                console.print(f"  Category: {category}")
            if productive is not None:
                console.print(f"  Productive: {'Yes' if productive else 'No'}")
            if note:
                console.print(f"  Note: {note}")
        except Exception as e:
            console.print(f"[red]Error logging activity:[/red] {e}")
        finally:
            await db.disconnect()

    asyncio.run(run())


@main.command("quick-log")
@click.argument("description")
@click.option("--duration", "-d", type=int, default=30, help="Duration in minutes")
def quick_log(description: str, duration: int):
    """Quick one-liner activity log.

    Examples:
        lifelogger quick-log "Worked on API refactor" -d 60
        lifelogger quick-log "Team meeting"
        lifelogger quick-log "Coffee break" -d 15
    """
    from datetime import datetime, timedelta
    from lifelogger.core.database import Database
    from lifelogger.core.config import get_settings

    async def run():
        settings = get_settings()
        db = Database(settings)
        await db.connect()

        now = datetime.now()
        event = {
            "timestamp": now - timedelta(minutes=duration),
            "device_id": "manual",
            "source": "quick_log",
            "app_name": "Manual Entry",
            "window_title": description,
            "url": None,
            "duration_seconds": duration * 60,
            "data": None,
            "classification": None,  # Will be classified by background worker
        }

        try:
            await db.insert_activity_event(**event)
            console.print(f"[green]✓ Logged ({duration}m):[/green] {description}")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
        finally:
            await db.disconnect()

    asyncio.run(run())


if __name__ == "__main__":
    main()
