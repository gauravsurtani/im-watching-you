#!/usr/bin/env python3
"""
Syncthing conflict detector.

Monitors for .sync-conflict-* files and sends alerts.
Run hourly via cron:
    0 * * * * /usr/bin/python3 /opt/lifelogger/scripts/server/check_sync_conflicts.py
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lifelogger.core.config import get_settings
from lifelogger.exporters.notifications import NotificationService


async def check_for_conflicts(send_alert: bool = True) -> list[Path]:
    """Check for Syncthing conflict files."""
    settings = get_settings()
    sync_path = settings.sync_base_path

    if not sync_path.exists():
        print(f"Sync path does not exist: {sync_path}")
        return []

    conflicts = list(sync_path.rglob("*.sync-conflict-*"))

    if conflicts:
        print(f"Found {len(conflicts)} sync conflicts:")
        for conflict in conflicts:
            print(f"  - {conflict}")

        if send_alert:
            notifier = NotificationService(settings)
            await notifier.send_alert(
                title="Sync Conflicts Detected",
                message=f"Found {len(conflicts)} sync conflict files in {sync_path}.\n\nFiles:\n"
                + "\n".join(f"- {c.name}" for c in conflicts[:10])
                + (f"\n... and {len(conflicts) - 10} more" if len(conflicts) > 10 else ""),
                priority="high",
            )
    else:
        print("No sync conflicts found.")

    return conflicts


def main():
    parser = argparse.ArgumentParser(description="Check for Syncthing conflicts")
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Don't send notification alerts",
    )

    args = parser.parse_args()

    conflicts = asyncio.run(check_for_conflicts(send_alert=not args.no_alert))
    sys.exit(1 if conflicts else 0)


if __name__ == "__main__":
    main()
