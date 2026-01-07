"""Daily digest generation with LLM summarization.

Uses Ollama for local LLM inference to generate structured daily summaries.
All parsing and categorization is LLM-powered - no regex.
"""

import json
from datetime import date, datetime
from typing import Any

from jinja2 import Template
from pydantic import BaseModel

from lifelogger.core.config import Settings, get_settings
from lifelogger.core.database import Database
from lifelogger.core.llm import LLMService, get_llm_service
from lifelogger.core.models import DailyDigest


# ============================================================================
# Structured Output Models for Digest
# ============================================================================

class DigestOutput(BaseModel):
    """Structured output from the LLM for daily digest."""

    time_summary: str
    topics_discussed: list[str]
    ideas_captured: list[str]
    action_items: list[str]
    content_referenced: list[str]
    follow_ups: list[str]
    daily_highlight: str | None = None
    mood_assessment: str | None = None


# ============================================================================
# Prompts
# ============================================================================

DIGEST_SYSTEM_PROMPT = """You are a personal assistant analyzing daily activity and conversation data.
Your task is to create a concise, useful daily digest. Be specific and actionable.
Focus on patterns, insights, and things the user should follow up on.
Always respond with valid JSON matching the requested schema."""

DIGEST_USER_PROMPT = """Analyze the following activity log and audio transcripts from today.
Generate a structured daily digest.

## Activity Data (Top apps by usage time):
{activity_summary}

## Today's Transcripts:
{transcripts}

Generate a JSON response with these fields:
- time_summary: A brief summary of how time was spent (1-2 sentences)
- topics_discussed: Array of main themes from conversations (from transcripts). Empty array if no transcripts.
- ideas_captured: Array of insights, plans, or creative thoughts mentioned. Empty array if none.
- action_items: Array of tasks or commitments mentioned ("I should...", "need to...", "todo"). Empty array if none.
- content_referenced: Array of any media, articles, books, or videos mentioned. Empty array if none.
- follow_ups: Array of things to revisit or research further. Empty array if none.
- daily_highlight: The most notable thing from the day (optional, null if nothing stands out)
- mood_assessment: Overall mood/energy assessment if detectable from activity/conversations (optional)

Be specific - include names, URLs, and details when available.
If transcripts are empty, focus on activity patterns and leave transcript-related fields as empty arrays.

Respond with JSON only, no markdown formatting."""


class DigestGenerator:
    """Generate daily digests using Ollama LLM with structured output."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db: Database | None = None
        self.llm: LLMService | None = None

    async def _ensure_db(self) -> Database:
        """Ensure database connection exists."""
        if self.db is None:
            self.db = Database(self.settings)
            await self.db.connect()
        return self.db

    async def _ensure_llm(self) -> LLMService:
        """Ensure LLM service exists."""
        if self.llm is None:
            self.llm = get_llm_service(self.settings)
        return self.llm

    async def generate_digest(self, target_date: date) -> DailyDigest:
        """Generate a daily digest for the specified date using LLM."""
        db = await self._ensure_db()
        llm = await self._ensure_llm()

        # Fetch activity summary
        app_usage = await db.get_app_usage_summary(target_date, limit=10)
        activity_summary = self._format_app_usage(app_usage)

        # Fetch transcripts
        transcripts = await db.get_transcripts_for_date(target_date)
        transcript_text = self._format_transcripts(transcripts)

        # Generate with LLM using structured output
        prompt = DIGEST_USER_PROMPT.format(
            activity_summary=activity_summary,
            transcripts=transcript_text if transcript_text else "(No transcripts for today)",
        )

        # Use structured generation with Pydantic model validation
        digest_output = await llm.generate_structured(
            prompt=prompt,
            response_model=DigestOutput,
            system=DIGEST_SYSTEM_PROMPT,
            temperature=0.5,
        )

        # Build DailyDigest from structured output
        return DailyDigest(
            date=datetime.combine(target_date, datetime.min.time()),
            time_summary=digest_output.time_summary,
            top_apps=[
                {"app": row["app_name"], "seconds": row["total_seconds"]}
                for row in app_usage[:5]
            ],
            topics_discussed=digest_output.topics_discussed,
            ideas_captured=digest_output.ideas_captured,
            action_items=digest_output.action_items,
            content_referenced=digest_output.content_referenced,
            follow_ups=digest_output.follow_ups,
            raw_llm_response=json.dumps(digest_output.model_dump(), indent=2),
        )

    def _format_app_usage(self, app_usage: list[dict[str, Any]]) -> str:
        """Format app usage data for the prompt."""
        if not app_usage:
            return "(No activity data recorded)"

        lines = []
        for row in app_usage:
            hours = row["total_seconds"] / 3600
            if hours >= 1:
                time_str = f"{hours:.1f} hours"
            else:
                time_str = f"{row['total_seconds'] / 60:.0f} minutes"
            lines.append(f"- {row['app_name']}: {time_str}")

        return "\n".join(lines)

    def _format_transcripts(self, transcripts: list[dict[str, Any]]) -> str:
        """Format transcripts for the prompt."""
        if not transcripts:
            return ""

        texts = []
        for t in transcripts:
            data = t.get("data", {})
            if isinstance(data, str):
                data = json.loads(data)
            full_text = data.get("full_text", "")
            if full_text:
                timestamp = t.get("timestamp", "")
                if hasattr(timestamp, "strftime"):
                    timestamp = timestamp.strftime("%H:%M")
                texts.append(f"[{timestamp}] {full_text}")

        return "\n\n".join(texts)


# ============================================================================
# Weekly Digest (bonus feature using same LLM approach)
# ============================================================================

class WeeklyDigestOutput(BaseModel):
    """Structured output for weekly digest."""

    week_summary: str
    total_productive_hours: float | None
    top_focus_areas: list[str]
    accomplishments: list[str]
    patterns_noticed: list[str]
    recommendations: list[str]
    next_week_priorities: list[str]


WEEKLY_DIGEST_PROMPT = """Analyze this week's activity data and daily summaries.

## Daily Summaries:
{daily_summaries}

## Weekly App Usage Totals:
{weekly_app_usage}

Generate a JSON response with:
- week_summary: Overview of the week (2-3 sentences)
- total_productive_hours: Estimated productive hours (float, or null if unclear)
- top_focus_areas: Main areas of focus this week
- accomplishments: Notable things completed or progressed
- patterns_noticed: Behavioral patterns observed (good or concerning)
- recommendations: Suggestions for improvement
- next_week_priorities: Suggested priorities based on patterns

Respond with JSON only."""


async def generate_weekly_digest(
    llm: LLMService,
    daily_summaries: list[str],
    weekly_app_usage: list[dict[str, Any]],
) -> WeeklyDigestOutput:
    """Generate a weekly digest from daily summaries."""
    prompt = WEEKLY_DIGEST_PROMPT.format(
        daily_summaries="\n\n".join(daily_summaries),
        weekly_app_usage="\n".join(
            f"- {row['app_name']}: {row['total_seconds'] / 3600:.1f} hours"
            for row in weekly_app_usage[:15]
        ),
    )

    return await llm.generate_structured(
        prompt=prompt,
        response_model=WeeklyDigestOutput,
        system="You are a productivity coach analyzing weekly activity patterns.",
        temperature=0.5,
    )


# ============================================================================
# Rendering Templates
# ============================================================================

DIGEST_EMAIL_TEMPLATE = Template("""
# Daily Digest - {{ date.strftime('%B %d, %Y') }}

## Time Summary
{{ time_summary }}

## Top Apps
{% for app in top_apps %}
- **{{ app.app }}**: {{ (app.seconds / 3600)|round(1) }} hours
{% endfor %}

{% if topics_discussed %}
## Topics Discussed
{% for topic in topics_discussed %}
- {{ topic }}
{% endfor %}
{% endif %}

{% if action_items %}
## Action Items
{% for item in action_items %}
- [ ] {{ item }}
{% endfor %}
{% endif %}

{% if ideas_captured %}
## Ideas Captured
{% for idea in ideas_captured %}
- {{ idea }}
{% endfor %}
{% endif %}

{% if content_referenced %}
## Content Referenced
{% for content in content_referenced %}
- {{ content }}
{% endfor %}
{% endif %}

{% if follow_ups %}
## Follow-ups
{% for item in follow_ups %}
- {{ item }}
{% endfor %}
{% endif %}

---
*Generated by Lifelogger*
""")


def render_digest_markdown(digest: DailyDigest) -> str:
    """Render a digest as Markdown text."""
    return DIGEST_EMAIL_TEMPLATE.render(
        date=digest.date,
        time_summary=digest.time_summary,
        top_apps=digest.top_apps,
        topics_discussed=digest.topics_discussed,
        action_items=digest.action_items,
        ideas_captured=digest.ideas_captured,
        content_referenced=digest.content_referenced,
        follow_ups=digest.follow_ups,
    )
