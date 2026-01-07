#!/usr/bin/env python3
"""
Data ingestion script for processing synced files.

Run this via cron to ingest new data:
    0 * * * * /usr/bin/python3 /opt/lifelogger/scripts/server/ingest_data.py

Monitors Syncthing folders and ingests new/changed files.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lifelogger.core.config import get_settings
from lifelogger.core.ingest import IngestService


async def run_ingestion(verbose: bool = False) -> dict:
    """Run the data ingestion pipeline."""
    settings = get_settings()
    service = IngestService(settings)

    print(f"Starting ingestion at {datetime.now().isoformat()}")
    print(f"Sync path: {settings.sync_base_path}")

    results = await service.run_full_ingest()

    summary = results.get("summary", {})

    print(f"\nIngestion complete:")
    print(f"  Activity events: {summary.get('activity_events', 0)}")
    print(f"  Transcripts: {summary.get('transcripts', 0)}")
    print(f"  Files processed: {summary.get('files_processed', 0)}")

    if verbose:
        print("\nDetailed results:")
        for file_path, count in results.get("activity", {}).items():
            status = f"{count} events" if count >= 0 else "ERROR"
            print(f"  {file_path}: {status}")
        for file_path, count in results.get("transcripts", {}).items():
            status = f"{count} events" if count >= 0 else "ERROR"
            print(f"  {file_path}: {status}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Ingest synced data files")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_ingestion(verbose=args.verbose))
    except Exception as e:
        print(f"Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
