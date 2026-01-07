"""Centralized LLM service for all AI-powered operations.

All categorization, classification, and content extraction is done via LLM.
No regex or rule-based heuristics for content understanding.
"""

import json
from datetime import datetime
from typing import Any, TypeVar

import aiohttp
from pydantic import BaseModel, ValidationError

from lifelogger.core.config import Settings, get_settings


T = TypeVar("T", bound=BaseModel)


class LLMService:
    """Centralized LLM service using Ollama for all AI operations."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Generate text completion from the LLM."""
        session = await self._get_session()
        url = f"{self.settings.ollama_url}/api/generate"

        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if system:
            payload["system"] = system

        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Ollama API error: {resp.status} - {error_text}")
            result = await resp.json()
            return result.get("response", "")

    async def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate structured JSON output from the LLM.

        Uses Ollama's JSON mode for reliable structured output.
        """
        session = await self._get_session()
        url = f"{self.settings.ollama_url}/api/generate"

        # Append JSON instruction to prompt
        json_prompt = f"""{prompt}

IMPORTANT: Respond with valid JSON only. No markdown, no code blocks, no explanation.
Just the raw JSON object."""

        payload = {
            "model": self.settings.ollama_model,
            "prompt": json_prompt,
            "stream": False,
            "format": "json",  # Ollama's JSON mode
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if system:
            payload["system"] = system + "\nAlways respond with valid JSON only."

        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Ollama API error: {resp.status} - {error_text}")
            result = await resp.json()
            response_text = result.get("response", "{}")

        # Parse the JSON response
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            # If parsing fails, try to extract JSON from the response
            raise ValueError(f"LLM did not return valid JSON: {response_text[:500]}") from e

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system: str | None = None,
        temperature: float = 0.3,
    ) -> T:
        """Generate output validated against a Pydantic model.

        Args:
            prompt: The prompt to send
            response_model: Pydantic model class for validation
            system: Optional system prompt
            temperature: LLM temperature

        Returns:
            Validated Pydantic model instance
        """
        # Generate schema description from Pydantic model
        schema = response_model.model_json_schema()
        schema_prompt = f"""{prompt}

Respond with a JSON object matching this schema:
{json.dumps(schema, indent=2)}"""

        result = await self.generate_json(schema_prompt, system, temperature)

        try:
            return response_model.model_validate(result)
        except ValidationError as e:
            raise ValueError(f"LLM response does not match expected schema: {e}") from e


# ============================================================================
# Event Classification
# ============================================================================

class EventClassification(BaseModel):
    """LLM-determined event classification."""

    event_type: str  # "app_usage", "browser", "communication", "media", "productivity", "gaming", "development", "other"
    category: str  # High-level category
    subcategory: str | None = None  # More specific category
    is_productive: bool | None = None  # Whether this is productive work
    description: str  # Brief description of the activity
    confidence: float  # 0.0 to 1.0


EVENT_CLASSIFICATION_SYSTEM = """You are an activity classification assistant.
Given app usage data, classify the activity accurately.
Consider the app name, window title, and any URL information.
Be precise and consistent in your classifications."""

EVENT_CLASSIFICATION_PROMPT = """Classify this activity event:

App: {app_name}
Window Title: {window_title}
URL: {url}
Duration: {duration} seconds
Additional Data: {extra_data}

Classify into one of these event types:
- "app_usage": General application usage
- "browser": Web browsing activity
- "communication": Email, chat, video calls
- "media": Music, video, entertainment
- "productivity": Documents, spreadsheets, notes
- "gaming": Games and gaming platforms
- "development": Code editors, terminals, dev tools
- "other": Anything else

Also provide:
- category: High-level category (e.g., "Work", "Entertainment", "Social", "Learning")
- subcategory: More specific (e.g., "Video Streaming", "Code Review", "Email")
- is_productive: true/false/null if unclear
- description: Brief description of what the user was doing
- confidence: Your confidence in this classification (0.0 to 1.0)

Respond with JSON only."""


async def classify_event(
    llm: LLMService,
    app_name: str | None,
    window_title: str | None,
    url: str | None = None,
    duration: float | None = None,
    extra_data: dict[str, Any] | None = None,
) -> EventClassification:
    """Classify an activity event using LLM."""
    prompt = EVENT_CLASSIFICATION_PROMPT.format(
        app_name=app_name or "Unknown",
        window_title=window_title or "Unknown",
        url=url or "None",
        duration=duration or 0,
        extra_data=json.dumps(extra_data) if extra_data else "None",
    )

    return await llm.generate_structured(
        prompt=prompt,
        response_model=EventClassification,
        system=EVENT_CLASSIFICATION_SYSTEM,
        temperature=0.2,
    )


# ============================================================================
# Batch Classification (for efficiency)
# ============================================================================

class BatchEventClassification(BaseModel):
    """Batch of classified events."""

    classifications: list[EventClassification]


async def classify_events_batch(
    llm: LLMService,
    events: list[dict[str, Any]],
    batch_size: int = 10,
) -> list[EventClassification]:
    """Classify multiple events in batches for efficiency.

    Args:
        llm: LLM service instance
        events: List of event dicts with app_name, window_title, url, duration, data
        batch_size: Number of events to classify per LLM call

    Returns:
        List of classifications in same order as input events
    """
    all_classifications = []

    for i in range(0, len(events), batch_size):
        batch = events[i : i + batch_size]

        # Format batch for prompt
        events_text = "\n\n".join(
            f"Event {j + 1}:\n"
            f"  App: {e.get('app_name', 'Unknown')}\n"
            f"  Title: {e.get('window_title', 'Unknown')}\n"
            f"  URL: {e.get('url', 'None')}\n"
            f"  Duration: {e.get('duration', 0)}s"
            for j, e in enumerate(batch)
        )

        prompt = f"""Classify these {len(batch)} activity events:

{events_text}

For each event, provide classification with:
- event_type: one of "app_usage", "browser", "communication", "media", "productivity", "gaming", "development", "other"
- category: High-level category
- subcategory: Specific category (or null)
- is_productive: true/false/null
- description: Brief description
- confidence: 0.0 to 1.0

Return a JSON object with a "classifications" array containing {len(batch)} classification objects in order."""

        try:
            result = await llm.generate_structured(
                prompt=prompt,
                response_model=BatchEventClassification,
                system=EVENT_CLASSIFICATION_SYSTEM,
                temperature=0.2,
            )
            all_classifications.extend(result.classifications)
        except (ValueError, ValidationError):
            # Fall back to individual classification on batch failure
            for event in batch:
                try:
                    classification = await classify_event(
                        llm,
                        app_name=event.get("app_name"),
                        window_title=event.get("window_title"),
                        url=event.get("url"),
                        duration=event.get("duration"),
                        extra_data=event.get("data"),
                    )
                    all_classifications.append(classification)
                except Exception:
                    # Default classification on failure
                    all_classifications.append(
                        EventClassification(
                            event_type="other",
                            category="Unknown",
                            subcategory=None,
                            is_productive=None,
                            description="Classification failed",
                            confidence=0.0,
                        )
                    )

    return all_classifications


# ============================================================================
# Transcript Analysis
# ============================================================================

class TranscriptAnalysis(BaseModel):
    """LLM analysis of a transcript."""

    summary: str  # Brief summary of the conversation
    topics: list[str]  # Main topics discussed
    action_items: list[str]  # Tasks or commitments mentioned
    ideas: list[str]  # Ideas or insights mentioned
    people_mentioned: list[str]  # Names of people referenced
    content_referenced: list[str]  # Books, articles, media mentioned
    sentiment: str  # "positive", "negative", "neutral", "mixed"
    key_quotes: list[str]  # Important or notable quotes
    follow_ups: list[str]  # Things to follow up on


TRANSCRIPT_ANALYSIS_SYSTEM = """You are a personal assistant analyzing conversation transcripts.
Extract useful information that helps the user remember and act on what was discussed.
Be specific and actionable. Include names, details, and context when available."""

TRANSCRIPT_ANALYSIS_PROMPT = """Analyze this transcript and extract useful information:

Transcript:
{transcript}

Extract:
- summary: Brief summary (1-2 sentences)
- topics: Main topics discussed (list of strings)
- action_items: Tasks or commitments ("I should...", "need to...", "will do...")
- ideas: Insights, plans, or creative thoughts mentioned
- people_mentioned: Names of people referenced
- content_referenced: Books, articles, videos, podcasts mentioned
- sentiment: Overall tone ("positive", "negative", "neutral", "mixed")
- key_quotes: Notable or important quotes worth remembering
- follow_ups: Things to research, revisit, or follow up on

Return JSON only."""


async def analyze_transcript(llm: LLMService, transcript_text: str) -> TranscriptAnalysis:
    """Analyze a transcript using LLM to extract structured information."""
    prompt = TRANSCRIPT_ANALYSIS_PROMPT.format(transcript=transcript_text)

    return await llm.generate_structured(
        prompt=prompt,
        response_model=TranscriptAnalysis,
        system=TRANSCRIPT_ANALYSIS_SYSTEM,
        temperature=0.3,
    )


# ============================================================================
# URL/Content Enrichment
# ============================================================================

class URLAnalysis(BaseModel):
    """LLM analysis of a URL."""

    domain: str
    site_name: str  # Human-friendly site name
    content_type: str  # "article", "video", "social", "tool", "documentation", "other"
    topic: str | None  # What the content is about (from URL/title)
    is_work_related: bool | None


URL_ANALYSIS_PROMPT = """Analyze this URL and window title:

URL: {url}
Title: {title}

Determine:
- domain: The domain name
- site_name: Human-friendly name (e.g., "YouTube", "GitHub", "Google Docs")
- content_type: One of "article", "video", "social", "tool", "documentation", "shopping", "entertainment", "other"
- topic: What the content is about (infer from URL path and title), or null if unclear
- is_work_related: true/false/null if unclear

Return JSON only."""


async def analyze_url(
    llm: LLMService, url: str, title: str | None = None
) -> URLAnalysis:
    """Analyze a URL to extract structured metadata."""
    prompt = URL_ANALYSIS_PROMPT.format(url=url, title=title or "Unknown")

    return await llm.generate_structured(
        prompt=prompt,
        response_model=URLAnalysis,
        system="You analyze URLs and web page titles to extract metadata.",
        temperature=0.2,
    )


# ============================================================================
# Singleton accessor
# ============================================================================

_llm_instance: LLMService | None = None


def get_llm_service(settings: Settings | None = None) -> LLMService:
    """Get or create the global LLM service instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMService(settings)
    return _llm_instance
