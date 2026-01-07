#!/usr/bin/env python3
"""
Daily digest generation script.

Run this via cron to generate and send daily digests:
    0 7 * * * /usr/bin/python3 /opt/lifelogger/scripts/server/daily_digest.py

Can also be run manually for testing or catch-up.
"""

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lifelogger.core.config import get_settings
from lifelogger.exporters.digest import DigestGenerator, render_digest_markdown
from lifelogger.exporters.notifications import NotificationService


async def generate_and_send_digest(
    target_date: date,
    send_notification: bool = True,
    save_to_db: bool = True,
) -> None:
    """Generate a daily digest and optionally send it."""
    settings = get_settings()

    print(f"Generating digest for {target_date}...")

    generator = DigestGenerator(settings)
    digest = await generator.generate_digest(target_date)

    # Print the digest
    markdown = render_digest_markdown(digest)
    print(markdown)

    # Save to database
    if save_to_db:
        from lifelogger.core.database import Database
        import orjson

        db = Database(settings)
        await db.connect()

        async with db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_digests (digest_date, summary, top_apps, topics, action_items, raw_response)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (digest_date) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    top_apps = EXCLUDED.top_apps,
                    topics = EXCLUDED.topics,
                    action_items = EXCLUDED.action_items,
                    raw_response = EXCLUDED.raw_response,
                    generated_at = NOW()
                """,
                target_date,
                digest.time_summary,
                orjson.dumps(digest.top_apps).decode(),
                orjson.dumps(digest.topics_discussed).decode(),
                orjson.dumps(digest.action_items).decode(),
                digest.raw_llm_response,
            )

        await db.disconnect()
        print(f"Digest saved to database.")

    # Send notification
    if send_notification:
        print("Sending notification...")
        notifier = NotificationService(settings)
        success = await notifier.send_digest(digest)
        if success:
            print("Notification sent successfully!")
        else:
            print("Failed to send notification.", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Generate daily digest")
    parser.add_argument(
        "--date",
        type=lambda s: date.fromisoformat(s),
        default=date.today() - timedelta(days=1),  # Default to yesterday
        help="Date to generate digest for (YYYY-MM-DD, default: yesterday)",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Don't send notification",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save to database",
    )

    args = parser.parse_args()

    asyncio.run(
        generate_and_send_digest(
            args.date,
            send_notification=not args.no_send,
            save_to_db=not args.no_save,
        )
    )


if __name__ == "__main__":
    main()
