"""Command-line interface for lifelogger."""

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
    """Lifelogger - Privacy-first personal second brain."""
    pass


@main.command()
@click.option("--activity-dir", type=click.Path(exists=True, path_type=Path), help="Activity data directory")
@click.option("--transcripts-dir", type=click.Path(exists=True, path_type=Path), help="Transcripts directory")
def ingest(activity_dir: Path | None, transcripts_dir: Path | None):
    """Ingest synced data files into the database."""
    from lifelogger.core.ingest import IngestService

    async def run():
        service = IngestService()

        with console.status("Ingesting data..."):
            if activity_dir:
                results = await service.ingest_activity_files(activity_dir)
            elif transcripts_dir:
                results = await service.ingest_transcript_files(transcripts_dir)
            else:
                results = await service.run_full_ingest()

        summary = results.get("summary", {})
        console.print(f"[green]Ingestion complete![/green]")
        console.print(f"  Activity events: {summary.get('activity_events', 0)}")
        console.print(f"  Transcripts: {summary.get('transcripts', 0)}")
        console.print(f"  Files processed: {summary.get('files_processed', 0)}")

    asyncio.run(run())


@main.command()
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]),
              default=str(date.today()), help="Date to generate digest for (YYYY-MM-DD)")
@click.option("--send/--no-send", default=False, help="Send notification after generation")
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Save digest to file")
def digest(target_date: datetime, send: bool, output: Path | None):
    """Generate a daily digest."""
    from lifelogger.exporters.digest import DigestGenerator, render_digest_markdown
    from lifelogger.exporters.notifications import NotificationService

    async def run():
        generator = DigestGenerator()

        with console.status(f"Generating digest for {target_date.date()}..."):
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


@main.command()
def setup():
    """Interactive setup wizard."""
    console.print("[bold]Lifelogger Setup[/bold]\n")

    console.print("1. Start the Docker services:")
    console.print("   [dim]cd docker && docker compose up -d[/dim]\n")

    console.print("2. Wait for services to be healthy:")
    console.print("   [dim]docker compose ps[/dim]\n")

    console.print("3. Pull an Ollama model:")
    console.print("   [dim]docker exec lifelogger-ollama ollama pull qwen2.5:7b[/dim]\n")

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
    console.print("   [dim]# Hourly data ingestion[/dim]")
    console.print("   [dim]0 * * * * cd /path/to/im-watching-you && python -m lifelogger ingest[/dim]")
    console.print("   [dim]# Daily digest at 7 AM[/dim]")
    console.print("   [dim]0 7 * * * cd /path/to/im-watching-you && python -m lifelogger digest --send[/dim]")


if __name__ == "__main__":
    main()
