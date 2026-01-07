#!/usr/bin/env python3
"""
ActivityWatch export script for client devices.

Run this script on Mac/Windows/Linux to export ActivityWatch data
to a Syncthing-synced folder for server ingestion.

Usage:
    python export_activitywatch.py --output ~/Syncthing/lifelogger/activity/

Can be scheduled via cron (Linux/Mac) or Task Scheduler (Windows).
Cron example (hourly):
    0 * * * * /usr/bin/python3 /path/to/export_activitywatch.py --output ~/Syncthing/lifelogger/activity/
"""

import argparse
import json
import socket
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


def get_aw_client(host: str = "localhost", port: int = 5600) -> str:
    """Get ActivityWatch API base URL."""
    return f"http://{host}:{port}/api/0"


def fetch_buckets(api_url: str) -> dict[str, Any]:
    """Fetch all buckets from ActivityWatch."""
    response = requests.get(f"{api_url}/buckets", timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_events(
    api_url: str,
    bucket_id: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Fetch events from a bucket within a time range."""
    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": -1,  # No limit
    }
    response = requests.get(
        f"{api_url}/buckets/{bucket_id}/events",
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def export_day(
    api_url: str,
    target_date: date,
    output_dir: Path,
    device_id: str,
) -> Path:
    """Export a full day's data to a JSON file."""
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

    buckets = fetch_buckets(api_url)

    all_events = []
    bucket_info = {}

    for bucket_id, bucket_data in buckets.items():
        # Only export window, browser, and afk watchers
        watcher_type = bucket_data.get("type", "")
        if not any(t in watcher_type for t in ["window", "web", "afk"]):
            continue

        try:
            events = fetch_events(api_url, bucket_id, start, end)
            if events:
                all_events.extend(events)
                bucket_info[bucket_id] = {
                    "type": watcher_type,
                    "event_count": len(events),
                }
        except requests.RequestException as e:
            print(f"Warning: Failed to fetch {bucket_id}: {e}")

    # Create output structure
    output = {
        "device_id": device_id,
        "hostname": socket.gethostname(),
        "export_date": target_date.isoformat(),
        "exported_at": datetime.now().isoformat(),
        "buckets": bucket_info,
        "events": all_events,
    }

    # Ensure output directory exists
    device_dir = output_dir / device_id
    device_dir.mkdir(parents=True, exist_ok=True)

    output_file = device_dir / f"{target_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Export ActivityWatch data for Syncthing sync"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path.home() / "Syncthing" / "lifelogger" / "activity",
        help="Output directory for exported JSON files",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="ActivityWatch server host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5600,
        help="ActivityWatch server port",
    )
    parser.add_argument(
        "--device-id",
        default=socket.gethostname().lower().replace(" ", "-"),
        help="Device identifier (defaults to hostname)",
    )
    parser.add_argument(
        "--date",
        type=lambda s: date.fromisoformat(s),
        default=date.today(),
        help="Date to export (YYYY-MM-DD, defaults to today)",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=0,
        help="Export this many days back (in addition to --date)",
    )

    args = parser.parse_args()

    api_url = get_aw_client(args.host, args.port)

    # Test connection
    try:
        fetch_buckets(api_url)
    except requests.RequestException as e:
        print(f"Error: Cannot connect to ActivityWatch at {api_url}: {e}")
        sys.exit(1)

    # Export requested days
    dates_to_export = [args.date - timedelta(days=i) for i in range(args.days_back + 1)]

    for target_date in dates_to_export:
        try:
            output_file = export_day(api_url, target_date, args.output, args.device_id)
            print(f"Exported {target_date} -> {output_file}")
        except Exception as e:
            print(f"Error exporting {target_date}: {e}")


if __name__ == "__main__":
    main()
