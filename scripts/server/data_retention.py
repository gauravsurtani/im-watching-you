#!/usr/bin/env python3
"""
Data retention and cleanup script.

Manages data lifecycle:
- Archives old data to compressed files
- Deletes data beyond retention period
- Cleans up orphaned files

Run daily via cron:
    0 3 * * * /usr/bin/python3 /opt/lifelogger/scripts/server/data_retention.py
"""

import argparse
import asyncio
import gzip
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lifelogger.core.config import get_settings
from lifelogger.core.database import Database
from lifelogger.core.logging import get_logger, LogContext

logger = get_logger("retention")


async def archive_old_events(
    db: Database,
    archive_dir: Path,
    days_to_keep: int = 90,
    batch_size: int = 10000,
) -> int:
    """Archive events older than retention period to compressed JSON files.

    Args:
        db: Database connection
        archive_dir: Directory to store archives
        days_to_keep: Keep this many days in the database
        batch_size: Number of events per archive file

    Returns:
        Number of events archived
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    cutoff_date = date.today() - timedelta(days=days_to_keep)

    logger.info(f"Archiving events before {cutoff_date}")

    total_archived = 0

    async with db.acquire() as conn:
        # Get count of events to archive
        count_row = await conn.fetchrow(
            "SELECT COUNT(*) as count FROM activity_events WHERE timestamp::date < $1",
            cutoff_date,
        )
        total_to_archive = count_row["count"]

        if total_to_archive == 0:
            logger.info("No events to archive")
            return 0

        logger.info(f"Found {total_to_archive} events to archive")

        # Archive in batches
        offset = 0
        file_num = 1

        while offset < total_to_archive:
            rows = await conn.fetch(
                """
                SELECT * FROM activity_events
                WHERE timestamp::date < $1
                ORDER BY timestamp
                LIMIT $2 OFFSET $3
                """,
                cutoff_date,
                batch_size,
                offset,
            )

            if not rows:
                break

            # Convert to JSON-serializable format
            events = []
            for row in rows:
                event = dict(row)
                # Convert datetime to ISO format
                if event.get("timestamp"):
                    event["timestamp"] = event["timestamp"].isoformat()
                if event.get("created_at"):
                    event["created_at"] = event["created_at"].isoformat()
                events.append(event)

            # Write compressed archive
            archive_file = archive_dir / f"archive_{cutoff_date}_{file_num:04d}.json.gz"

            with gzip.open(archive_file, "wt", encoding="utf-8") as f:
                json.dump(events, f)

            logger.info(f"Wrote {len(events)} events to {archive_file}")

            total_archived += len(events)
            offset += batch_size
            file_num += 1

    return total_archived


async def delete_archived_events(
    db: Database,
    days_to_keep: int = 90,
    dry_run: bool = False,
) -> int:
    """Delete events that have been archived.

    Args:
        db: Database connection
        days_to_keep: Keep this many days in the database
        dry_run: If True, only report what would be deleted

    Returns:
        Number of events deleted
    """
    cutoff_date = date.today() - timedelta(days=days_to_keep)

    async with db.acquire() as conn:
        if dry_run:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as count FROM activity_events WHERE timestamp::date < $1",
                cutoff_date,
            )
            logger.info(f"Would delete {row['count']} events (dry run)")
            return row["count"]

        result = await conn.execute(
            "DELETE FROM activity_events WHERE timestamp::date < $1",
            cutoff_date,
        )

        # Parse "DELETE X" result
        deleted = int(result.split()[-1])
        logger.info(f"Deleted {deleted} events older than {cutoff_date}")

        return deleted


async def cleanup_audio_files(
    audio_dir: Path,
    days_to_keep: int = 30,
    dry_run: bool = False,
) -> int:
    """Delete audio files older than retention period.

    Args:
        audio_dir: Directory containing audio files
        days_to_keep: Keep files newer than this
        dry_run: If True, only report what would be deleted

    Returns:
        Number of files deleted
    """
    if not audio_dir.exists():
        return 0

    cutoff_time = datetime.now() - timedelta(days=days_to_keep)
    deleted = 0

    for audio_file in audio_dir.rglob("*"):
        if not audio_file.is_file():
            continue

        # Check file extension
        if audio_file.suffix.lower() not in (".opus", ".wav", ".mp3", ".m4a", ".ogg"):
            continue

        # Check modification time
        mtime = datetime.fromtimestamp(audio_file.stat().st_mtime)
        if mtime < cutoff_time:
            if dry_run:
                logger.info(f"Would delete: {audio_file}")
            else:
                audio_file.unlink()
                logger.info(f"Deleted: {audio_file}")
            deleted += 1

    return deleted


async def cleanup_sync_conflicts(sync_dir: Path, dry_run: bool = False) -> int:
    """Delete Syncthing conflict files.

    Args:
        sync_dir: Syncthing sync directory
        dry_run: If True, only report what would be deleted

    Returns:
        Number of files deleted
    """
    if not sync_dir.exists():
        return 0

    deleted = 0

    for conflict_file in sync_dir.rglob("*.sync-conflict-*"):
        if dry_run:
            logger.info(f"Would delete conflict: {conflict_file}")
        else:
            conflict_file.unlink()
            logger.info(f"Deleted conflict: {conflict_file}")
        deleted += 1

    return deleted


async def vacuum_database(db: Database) -> None:
    """Run VACUUM ANALYZE on the database to reclaim space."""
    async with db.acquire() as conn:
        # VACUUM cannot run in a transaction
        await conn.execute("VACUUM ANALYZE activity_events")
        logger.info("Vacuumed activity_events table")


async def run_retention_tasks(
    archive: bool = True,
    delete: bool = True,
    cleanup_audio: bool = True,
    cleanup_conflicts: bool = True,
    vacuum: bool = True,
    dry_run: bool = False,
) -> dict:
    """Run all retention tasks.

    Returns:
        Summary of actions taken
    """
    settings = get_settings()
    db = Database(settings)
    await db.connect()

    results = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
    }

    try:
        archive_dir = settings.sync_base_path / "archives"

        if archive:
            with LogContext(logger, "archive_events"):
                results["events_archived"] = await archive_old_events(
                    db, archive_dir, settings.activity_retention_days
                )

        if delete and not dry_run:
            with LogContext(logger, "delete_events"):
                results["events_deleted"] = await delete_archived_events(
                    db, settings.activity_retention_days, dry_run
                )

        if cleanup_audio:
            with LogContext(logger, "cleanup_audio"):
                results["audio_files_deleted"] = await cleanup_audio_files(
                    settings.sync_audio_path, settings.audio_retention_days, dry_run
                )

        if cleanup_conflicts:
            with LogContext(logger, "cleanup_conflicts"):
                results["conflicts_deleted"] = await cleanup_sync_conflicts(
                    settings.sync_base_path, dry_run
                )

        if vacuum and not dry_run:
            with LogContext(logger, "vacuum_database"):
                await vacuum_database(db)
                results["vacuumed"] = True

    finally:
        await db.disconnect()

    return results


def main():
    parser = argparse.ArgumentParser(description="Data retention and cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be done")
    parser.add_argument("--no-archive", action="store_true", help="Skip archiving")
    parser.add_argument("--no-delete", action="store_true", help="Skip deletion")
    parser.add_argument("--no-audio", action="store_true", help="Skip audio cleanup")
    parser.add_argument("--no-vacuum", action="store_true", help="Skip database vacuum")

    args = parser.parse_args()

    results = asyncio.run(
        run_retention_tasks(
            archive=not args.no_archive,
            delete=not args.no_delete,
            cleanup_audio=not args.no_audio,
            vacuum=not args.no_vacuum,
            dry_run=args.dry_run,
        )
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
