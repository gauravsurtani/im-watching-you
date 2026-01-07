"""Daily digest generation with LLM summarization.

Uses Ollama for local LLM inference to generate daily summaries.
"""

import json
from datetime import date, datetime
from typing import Any

import aiohttp
from jinja2 import Template

from lifelogger.core.config import Settings, get_settings
from lifelogger.core.database import Database
from lifelogger.core.models import DailyDigest

# System prompt for digest generation
DIGEST_SYSTEM_PROMPT = """You are a personal assistant analyzing daily activity and conversation data.
Your task is to create a concise, useful daily digest. Be specific and actionable.
Focus on patterns, insights, and things the user should follow up on."""

DIGEST_USER_PROMPT = """Analyze the following activity log and audio transcripts from today.
Generate a structured daily digest with these sections:

1. **Time Summary**: Total active time, top 5 apps by duration
2. **Topics Discussed**: Main themes from conversations (from transcripts)
3. **Ideas Captured**: Any insights, plans, or creative thoughts mentioned
4. **Action Items**: Tasks or commitments mentioned ("I should...", "need to...", "todo")
5. **Content Referenced**: Any media, articles, books, or videos mentioned
6. **Follow-ups**: Things to revisit or research further

## Activity Data (Top apps by usage time):
{activity_summary}

## Today's Transcripts:
{transcripts}

Generate a concise, scannable digest. Use bullet points. Be specific - include names, URLs, and details when available.
If transcripts are empty, focus on activity patterns and skip transcript-related sections."""


class DigestGenerator:
    """Generate daily digests using Ollama LLM."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db: Database | None = None

    async def _ensure_db(self) -> Database:
        """Ensure database connection exists."""
        if self.db is None:
            self.db = Database(self.settings)
            await self.db.connect()
        return self.db

    async def generate_digest(self, target_date: date) -> DailyDigest:
        """Generate a daily digest for the specified date."""
        db = await self._ensure_db()

        # Fetch activity summary
        app_usage = await db.get_app_usage_summary(target_date, limit=10)
        activity_summary = self._format_app_usage(app_usage)

        # Fetch transcripts
        transcripts = await db.get_transcripts_for_date(target_date)
        transcript_text = self._format_transcripts(transcripts)

        # Generate with LLM
        prompt = DIGEST_USER_PROMPT.format(
            activity_summary=activity_summary,
            transcripts=transcript_text if transcript_text else "(No transcripts for today)",
        )

        llm_response = await self._call_ollama(prompt)

        # Parse and structure the response
        return DailyDigest(
            date=datetime.combine(target_date, datetime.min.time()),
            time_summary=self._extract_section(llm_response, "Time Summary"),
            top_apps=[
                {"app": row["app_name"], "seconds": row["total_seconds"]}
                for row in app_usage[:5]
            ],
            topics_discussed=self._extract_list(llm_response, "Topics Discussed"),
            ideas_captured=self._extract_list(llm_response, "Ideas Captured"),
            action_items=self._extract_list(llm_response, "Action Items"),
            content_referenced=self._extract_list(llm_response, "Content Referenced"),
            follow_ups=self._extract_list(llm_response, "Follow-ups"),
            raw_llm_response=llm_response,
        )

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API for text generation."""
        url = f"{self.settings.ollama_url}/api/generate"

        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "system": DIGEST_SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Ollama API error: {resp.status} - {error_text}")
                result = await resp.json()
                return result.get("response", "")

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

    def _extract_section(self, text: str, section_name: str) -> str:
        """Extract a section from the LLM response."""
        import re

        pattern = rf"\*?\*?{re.escape(section_name)}\*?\*?:?\s*\n?(.*?)(?=\n\*?\*?\d+\.|$|\n\*?\*?[A-Z])"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_list(self, text: str, section_name: str) -> list[str]:
        """Extract a bulleted list from a section."""
        section = self._extract_section(text, section_name)
        if not section:
            return []

        items = []
        for line in section.split("\n"):
            line = line.strip()
            if line.startswith(("-", "*", "•")):
                items.append(line.lstrip("-*• ").strip())
            elif line and not line.startswith("#"):
                items.append(line)

        return [item for item in items if item]


# Email/notification template
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
        follow_ups=digest.follow_ups,
    )
