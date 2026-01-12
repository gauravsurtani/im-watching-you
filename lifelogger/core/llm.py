"""Hybrid LLM service supporting both local (Ollama) and cloud (OpenRouter) providers.

All categorization, classification, and content extraction is done via LLM.
No regex or rule-based heuristics for content understanding.

Privacy-aware routing:
- Sensitive data (transcripts, full URLs) → Local Ollama only
- Non-sensitive classification → Can use cloud (OpenRouter free tier)
- Configurable per data type
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import aiohttp
from pydantic import BaseModel, ValidationError

from lifelogger.core.config import Settings, get_settings
from lifelogger.core.models_config import TaskType, get_model_for_task


T = TypeVar("T", bound=BaseModel)


class DataSensitivity(Enum):
    """Data sensitivity levels for privacy-aware routing."""

    LOW = "low"  # Category names, app names, generic classification
    MEDIUM = "medium"  # Window titles, domain names
    HIGH = "high"  # Full URLs, personal notes, file paths
    CRITICAL = "critical"  # Transcripts, conversations, passwords


@dataclass
class RateLimiter:
    """Adaptive rate limiter for API calls with burst handling."""

    max_requests: int = 20
    window_seconds: int = 60
    _timestamps: deque = field(default_factory=deque)
    _consecutive_waits: int = 0

    async def acquire(self) -> None:
        """Wait until we can make a request within rate limits."""
        now = time.time()

        # Remove old timestamps
        while self._timestamps and self._timestamps[0] < now - self.window_seconds:
            self._timestamps.popleft()

        # Wait if at limit
        if len(self._timestamps) >= self.max_requests:
            sleep_time = self._timestamps[0] + self.window_seconds - now
            if sleep_time > 0:
                self._consecutive_waits += 1
                await asyncio.sleep(sleep_time)
                return await self.acquire()
        else:
            self._consecutive_waits = 0

        self._timestamps.append(now)

    def requests_remaining(self) -> int:
        """Get number of requests remaining in current window."""
        now = time.time()
        while self._timestamps and self._timestamps[0] < now - self.window_seconds:
            self._timestamps.popleft()
        return max(0, self.max_requests - len(self._timestamps))

    def seconds_until_reset(self) -> float:
        """Seconds until oldest request expires from window."""
        if not self._timestamps:
            return 0
        return max(0, self._timestamps[0] + self.window_seconds - time.time())


class ClassificationCache:
    """LRU cache for event classifications to avoid redundant LLM calls.

    Caches based on (app_name, simplified_title) keys.
    Same app with similar activity patterns get cached classification.
    """

    def __init__(self, max_size: int = 1000):
        self._cache: dict[str, EventClassification] = {}
        self._access_order: deque = deque()
        self._max_size = max_size

    def _make_key(self, app_name: str | None, window_title: str | None) -> str:
        """Create cache key from event data."""
        app = (app_name or "").lower().strip()
        # Simplify title - keep first 3 words
        title_words = (window_title or "").split()[:3]
        title = " ".join(title_words).lower()
        return f"{app}::{title}"

    def get(self, app_name: str | None, window_title: str | None) -> EventClassification | None:
        """Get cached classification if available."""
        key = self._make_key(app_name, window_title)
        if key in self._cache:
            # Move to end (most recently used)
            try:
                self._access_order.remove(key)
            except ValueError:
                pass
            self._access_order.append(key)
            return self._cache[key]
        return None

    def put(
        self,
        app_name: str | None,
        window_title: str | None,
        classification: EventClassification,
    ) -> None:
        """Cache a classification."""
        key = self._make_key(app_name, window_title)

        # Evict oldest if at capacity
        while len(self._cache) >= self._max_size and self._access_order:
            oldest = self._access_order.popleft()
            self._cache.pop(oldest, None)

        self._cache[key] = classification
        self._access_order.append(key)

    def stats(self) -> dict[str, int]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
        }


# Global classification cache
_classification_cache = ClassificationCache()


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        """Generate text completion."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        pass


class OllamaProvider(LLMProvider):
    """Local LLM provider using Ollama."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def is_available(self) -> bool:
        return bool(self.settings.ollama_host)

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        session = await self._get_session()
        url = f"{self.settings.ollama_url}/api/generate"

        payload: dict[str, Any] = {
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

        if json_mode:
            payload["format"] = "json"

        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Ollama API error: {resp.status} - {error_text}")
            result = await resp.json()
            return result.get("response", "")


class OpenRouterProvider(LLMProvider):
    """Cloud LLM provider using OpenRouter (supports free models).

    Supports task-specific model selection via models_config.
    """

    # Free models available on OpenRouter (updated Jan 2025)
    FREE_MODELS = [
        "meta-llama/llama-3.2-3b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-2-9b-it:free",
        "google/gemma-3-12b-it:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-7b-instruct:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
        "qwen/qwen-2.5-7b-instruct:free",
        "qwen/qwen2.5-vl-32b-instruct:free",
        "qwen/qwen2.5-vl-72b-instruct:free",
        "microsoft/phi-4:free",
        "deepseek/deepseek-r1:free",
    ]

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(
            max_requests=settings.openrouter_rate_limit,
            window_seconds=60,
        )
        self._default_model = settings.openrouter_model

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def is_available(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    def get_rate_limiter(self) -> RateLimiter:
        """Get the rate limiter for status checks."""
        return self._rate_limiter

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        model_id: str | None = None,  # Override model for this request
    ) -> str:
        if not self.is_available():
            raise RuntimeError("OpenRouter API key not configured")

        # Rate limiting
        await self._rate_limiter.acquire()

        session = await self._get_session()
        url = f"{self.settings.openrouter_base_url}/chat/completions"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Use specified model or default
        model = model_id or self._default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/lifelogger",
            "X-Title": "Lifelogger",
        }

        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status == 429:
                # Rate limited - wait and retry
                await asyncio.sleep(5)
                return await self.generate(prompt, system, temperature, max_tokens, json_mode)

            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"OpenRouter API error: {resp.status} - {error_text}")

            result = await resp.json()
            return result["choices"][0]["message"]["content"]


class HybridLLMService:
    """Hybrid LLM service with privacy-aware routing between local and cloud providers.

    Provider selection strategy:
    - "local": Always use Ollama (maximum privacy)
    - "cloud": Always use OpenRouter (no local GPU needed)
    - "hybrid": Route based on data sensitivity
    - "cloud_fallback": Try local first, fall back to cloud on failure
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._ollama = OllamaProvider(self.settings)
        self._openrouter = OpenRouterProvider(self.settings)

    async def close(self) -> None:
        """Close all provider sessions."""
        await self._ollama.close()
        await self._openrouter.close()

    def _select_provider(
        self, sensitivity: DataSensitivity = DataSensitivity.LOW
    ) -> LLMProvider:
        """Select the appropriate provider based on strategy and sensitivity."""
        strategy = self.settings.llm_provider

        if strategy == "local":
            return self._ollama

        if strategy == "cloud":
            if not self._openrouter.is_available():
                return self._ollama
            return self._openrouter

        if strategy == "hybrid":
            # Route based on sensitivity
            if sensitivity in (DataSensitivity.HIGH, DataSensitivity.CRITICAL):
                return self._ollama
            if self._openrouter.is_available():
                return self._openrouter
            return self._ollama

        if strategy == "cloud_fallback":
            return self._ollama  # Primary is local, fallback handled separately

        return self._ollama

    def _get_model_for_task(self, task_type: TaskType | None) -> str | None:
        """Get the model ID for a specific task type based on settings."""
        if task_type is None:
            return None

        # Check for explicit model overrides in settings
        overrides = {
            TaskType.EVENT_CLASSIFICATION: self.settings.model_classification,
            TaskType.BATCH_CLASSIFICATION: self.settings.model_classification,
            TaskType.TRANSCRIPT_ANALYSIS: self.settings.model_analysis,
            TaskType.DIGEST_GENERATION: self.settings.model_digest,
            TaskType.URL_ANALYSIS: self.settings.model_classification,
            TaskType.GENERAL: self.settings.model_general,
        }

        override = overrides.get(task_type)
        if override:
            return override

        # Use preset-based model selection
        model_spec = get_model_for_task(task_type, preset=self.settings.model_preset)
        return model_spec.id

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        sensitivity: DataSensitivity = DataSensitivity.LOW,
        task_type: TaskType | None = None,
    ) -> str:
        """Generate text completion with automatic provider selection.

        Args:
            prompt: The prompt to send to the LLM
            system: Optional system message
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            sensitivity: Data sensitivity level for routing
            task_type: Optional task type for model selection (OpenRouter only)
        """
        provider = self._select_provider(sensitivity)

        # Get task-specific model for OpenRouter
        model_id = None
        if isinstance(provider, OpenRouterProvider) and task_type:
            model_id = self._get_model_for_task(task_type)

        try:
            if isinstance(provider, OpenRouterProvider):
                return await provider.generate(
                    prompt, system, temperature, max_tokens, model_id=model_id
                )
            return await provider.generate(prompt, system, temperature, max_tokens)
        except Exception as e:
            # Fallback logic for cloud_fallback strategy
            if (
                self.settings.llm_provider == "cloud_fallback"
                and provider == self._ollama
                and self._openrouter.is_available()
                and sensitivity not in (DataSensitivity.HIGH, DataSensitivity.CRITICAL)
            ):
                return await self._openrouter.generate(
                    prompt, system, temperature, max_tokens, model_id=model_id
                )
            raise e

    async def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        sensitivity: DataSensitivity = DataSensitivity.LOW,
        task_type: TaskType | None = None,
    ) -> dict[str, Any]:
        """Generate structured JSON output."""
        provider = self._select_provider(sensitivity)

        # Get task-specific model for OpenRouter
        model_id = None
        if isinstance(provider, OpenRouterProvider) and task_type:
            model_id = self._get_model_for_task(task_type)

        # Append JSON instruction
        json_prompt = f"""{prompt}

IMPORTANT: Respond with valid JSON only. No markdown, no code blocks, no explanation.
Just the raw JSON object."""

        if system:
            system = system + "\nAlways respond with valid JSON only."

        try:
            if isinstance(provider, OpenRouterProvider):
                response = await provider.generate(
                    json_prompt, system, temperature, max_tokens, json_mode=True, model_id=model_id
                )
            else:
                response = await provider.generate(
                    json_prompt, system, temperature, max_tokens, json_mode=True
                )
        except Exception as e:
            # Fallback
            if (
                self.settings.llm_provider == "cloud_fallback"
                and provider == self._ollama
                and self._openrouter.is_available()
                and sensitivity not in (DataSensitivity.HIGH, DataSensitivity.CRITICAL)
            ):
                response = await self._openrouter.generate(
                    json_prompt, system, temperature, max_tokens, json_mode=True, model_id=model_id
                )
            else:
                raise e

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {response[:500]}") from e

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system: str | None = None,
        temperature: float = 0.3,
        sensitivity: DataSensitivity = DataSensitivity.LOW,
        task_type: TaskType | None = None,
    ) -> T:
        """Generate output validated against a Pydantic model."""
        schema = response_model.model_json_schema()
        schema_prompt = f"""{prompt}

Respond with a JSON object matching this schema:
{json.dumps(schema, indent=2)}"""

        result = await self.generate_json(
            schema_prompt, system, temperature, sensitivity=sensitivity, task_type=task_type
        )

        try:
            return response_model.model_validate(result)
        except ValidationError as e:
            raise ValueError(f"LLM response does not match expected schema: {e}") from e


# Backward compatibility alias
LLMService = HybridLLMService


# ============================================================================
# Event Classification
# ============================================================================


class EventClassification(BaseModel):
    """LLM-determined event classification."""

    event_type: str
    category: str
    subcategory: str | None = None
    is_productive: bool | None = None
    description: str
    confidence: float


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


def _redact_sensitive_for_cloud(
    app_name: str | None,
    window_title: str | None,
    url: str | None,
    settings: Settings,
) -> tuple[str | None, str | None, str | None, DataSensitivity]:
    """Redact sensitive information for cloud processing.

    Returns redacted values and the sensitivity level.
    """
    sensitivity = DataSensitivity.LOW

    # URL handling
    redacted_url = url
    if url and settings.privacy_local_urls:
        # Extract just the domain for cloud, keep full URL local
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            redacted_url = parsed.netloc  # Just the domain
        except Exception:
            redacted_url = "[redacted]"
        sensitivity = DataSensitivity.HIGH

    # Window title handling
    redacted_title = window_title
    if window_title and settings.privacy_local_window_titles:
        # Keep first few words, redact the rest
        words = window_title.split()[:3]
        redacted_title = " ".join(words) + "..." if len(window_title.split()) > 3 else window_title
        sensitivity = max(sensitivity, DataSensitivity.MEDIUM, key=lambda x: x.value)

    return app_name, redacted_title, redacted_url, sensitivity


async def classify_event(
    llm: HybridLLMService,
    app_name: str | None,
    window_title: str | None,
    url: str | None = None,
    duration: float | None = None,
    extra_data: dict[str, Any] | None = None,
) -> EventClassification:
    """Classify an activity event using LLM with privacy-aware routing."""
    settings = llm.settings

    # Determine if we need to redact for cloud
    if settings.llm_provider in ("cloud", "hybrid"):
        r_app, r_title, r_url, sensitivity = _redact_sensitive_for_cloud(
            app_name, window_title, url, settings
        )
    else:
        r_app, r_title, r_url = app_name, window_title, url
        sensitivity = DataSensitivity.LOW

    prompt = EVENT_CLASSIFICATION_PROMPT.format(
        app_name=r_app or "Unknown",
        window_title=r_title or "Unknown",
        url=r_url or "None",
        duration=duration or 0,
        extra_data=json.dumps(extra_data) if extra_data else "None",
    )

    return await llm.generate_structured(
        prompt=prompt,
        response_model=EventClassification,
        system=EVENT_CLASSIFICATION_SYSTEM,
        temperature=0.2,
        sensitivity=sensitivity,
        task_type=TaskType.EVENT_CLASSIFICATION,
    )


# ============================================================================
# Batch Classification
# ============================================================================


class BatchEventClassification(BaseModel):
    """Batch of classified events."""

    classifications: list[EventClassification]


async def classify_events_batch(
    llm: HybridLLMService,
    events: list[dict[str, Any]],
    batch_size: int = 30,  # LLMs handle large batches well
    use_cache: bool = True,
) -> list[EventClassification]:
    """Classify multiple events in batches for efficiency.

    Uses caching to skip events similar to previously classified ones.
    With 30 events/batch and 20 req/min limit = 600 events/min = 36k/hour.
    """
    all_classifications: list[EventClassification | None] = [None] * len(events)
    events_to_classify: list[tuple[int, dict[str, Any]]] = []  # (original_index, event)
    settings = llm.settings

    # First pass: check cache for each event
    cache_hits = 0
    for idx, event in enumerate(events):
        if use_cache:
            cached = _classification_cache.get(
                event.get("app_name"),
                event.get("window_title"),
            )
            if cached:
                all_classifications[idx] = cached
                cache_hits += 1
                continue
        events_to_classify.append((idx, event))

    # Process uncached events in batches
    for i in range(0, len(events_to_classify), batch_size):
        batch_items = events_to_classify[i : i + batch_size]
        batch = [item[1] for item in batch_items]
        batch_indices = [item[0] for item in batch_items]

        # Determine sensitivity and redact if needed
        max_sensitivity = DataSensitivity.LOW
        processed_events = []

        for e in batch:
            if settings.llm_provider in ("cloud", "hybrid"):
                r_app, r_title, r_url, sens = _redact_sensitive_for_cloud(
                    e.get("app_name"),
                    e.get("window_title"),
                    e.get("url"),
                    settings,
                )
                max_sensitivity = max(max_sensitivity, sens, key=lambda x: x.value)
            else:
                r_app = e.get("app_name", "Unknown")
                r_title = e.get("window_title", "Unknown")
                r_url = e.get("url", "None")

            processed_events.append({
                "app_name": r_app or "Unknown",
                "window_title": r_title or "Unknown",
                "url": r_url or "None",
                "duration": e.get("duration", 0),
            })

        events_text = "\n\n".join(
            f"Event {j + 1}:\n"
            f"  App: {pe['app_name']}\n"
            f"  Title: {pe['window_title']}\n"
            f"  URL: {pe['url']}\n"
            f"  Duration: {pe['duration']}s"
            for j, pe in enumerate(processed_events)
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
                sensitivity=max_sensitivity,
                task_type=TaskType.BATCH_CLASSIFICATION,
            )

            # Store results and update cache
            for j, classification in enumerate(result.classifications):
                orig_idx = batch_indices[j]
                all_classifications[orig_idx] = classification
                # Cache the result
                if use_cache:
                    _classification_cache.put(
                        batch[j].get("app_name"),
                        batch[j].get("window_title"),
                        classification,
                    )
        except (ValueError, ValidationError):
            # Fall back to individual classification
            for j, event in enumerate(batch):
                orig_idx = batch_indices[j]
                try:
                    classification = await classify_event(
                        llm,
                        app_name=event.get("app_name"),
                        window_title=event.get("window_title"),
                        url=event.get("url"),
                        duration=event.get("duration"),
                        extra_data=event.get("data"),
                    )
                    all_classifications[orig_idx] = classification
                    if use_cache:
                        _classification_cache.put(
                            event.get("app_name"),
                            event.get("window_title"),
                            classification,
                        )
                except Exception:
                    all_classifications[orig_idx] = EventClassification(
                        event_type="other",
                        category="Unknown",
                        subcategory=None,
                        is_productive=None,
                        description="Classification failed",
                        confidence=0.0,
                    )

    # Convert None values to default classification (shouldn't happen but safety)
    return [
        c if c is not None else EventClassification(
            event_type="other",
            category="Unknown",
            description="Not classified",
            confidence=0.0,
        )
        for c in all_classifications
    ]


def estimate_classification_time(
    num_events: int,
    batch_size: int = 30,
    rate_limit: int = 20,
    cache_hit_rate: float = 0.3,
) -> dict[str, Any]:
    """Estimate time to classify events with rate limiting.

    Args:
        num_events: Number of events to classify
        batch_size: Events per LLM call
        rate_limit: Requests per minute allowed
        cache_hit_rate: Expected cache hit ratio (0.0 to 1.0)

    Returns:
        Dict with timing estimates
    """
    events_after_cache = int(num_events * (1 - cache_hit_rate))
    num_batches = (events_after_cache + batch_size - 1) // batch_size
    minutes_needed = num_batches / rate_limit

    return {
        "total_events": num_events,
        "events_from_cache": num_events - events_after_cache,
        "events_to_classify": events_after_cache,
        "num_batches": num_batches,
        "rate_limit_rpm": rate_limit,
        "estimated_minutes": round(minutes_needed, 1),
        "estimated_seconds": round(minutes_needed * 60, 0),
    }


# ============================================================================
# Transcript Analysis (Always Local - High Privacy)
# ============================================================================


class TranscriptAnalysis(BaseModel):
    """LLM analysis of a transcript."""

    summary: str
    topics: list[str]
    action_items: list[str]
    ideas: list[str]
    people_mentioned: list[str]
    content_referenced: list[str]
    sentiment: str
    key_quotes: list[str]
    follow_ups: list[str]


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


async def analyze_transcript(llm: HybridLLMService, transcript_text: str) -> TranscriptAnalysis:
    """Analyze a transcript using LLM.

    Always uses local processing due to high sensitivity of conversation data.
    """
    prompt = TRANSCRIPT_ANALYSIS_PROMPT.format(transcript=transcript_text)

    return await llm.generate_structured(
        prompt=prompt,
        response_model=TranscriptAnalysis,
        system=TRANSCRIPT_ANALYSIS_SYSTEM,
        temperature=0.3,
        sensitivity=DataSensitivity.CRITICAL,  # Always local
        task_type=TaskType.TRANSCRIPT_ANALYSIS,
    )


# ============================================================================
# URL/Content Enrichment
# ============================================================================


class URLAnalysis(BaseModel):
    """LLM analysis of a URL."""

    domain: str
    site_name: str
    content_type: str
    topic: str | None
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
    llm: HybridLLMService, url: str, title: str | None = None
) -> URLAnalysis:
    """Analyze a URL to extract structured metadata."""
    settings = llm.settings

    # Determine sensitivity based on settings
    sensitivity = DataSensitivity.HIGH if settings.privacy_local_urls else DataSensitivity.LOW

    prompt = URL_ANALYSIS_PROMPT.format(url=url, title=title or "Unknown")

    return await llm.generate_structured(
        prompt=prompt,
        response_model=URLAnalysis,
        system="You analyze URLs and web page titles to extract metadata.",
        temperature=0.2,
        sensitivity=sensitivity,
        task_type=TaskType.URL_ANALYSIS,
    )


# ============================================================================
# Provider Status
# ============================================================================


async def check_provider_status(settings: Settings | None = None) -> dict[str, Any]:
    """Check the status of available LLM providers."""
    settings = settings or get_settings()
    status = {
        "strategy": settings.llm_provider,
        "providers": {},
    }

    # Check Ollama
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.ollama_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    status["providers"]["ollama"] = {
                        "available": True,
                        "url": settings.ollama_url,
                        "model": settings.ollama_model,
                        "installed_models": models,
                    }
                else:
                    status["providers"]["ollama"] = {"available": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        status["providers"]["ollama"] = {"available": False, "error": str(e)}

    # Check OpenRouter
    if settings.openrouter_api_key:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{settings.openrouter_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        status["providers"]["openrouter"] = {
                            "available": True,
                            "model": settings.openrouter_model,
                            "fallback_model": settings.openrouter_fallback_model,
                            "rate_limit": settings.openrouter_rate_limit,
                        }
                    else:
                        status["providers"]["openrouter"] = {
                            "available": False,
                            "error": f"HTTP {resp.status}",
                        }
        except Exception as e:
            status["providers"]["openrouter"] = {"available": False, "error": str(e)}
    else:
        status["providers"]["openrouter"] = {
            "available": False,
            "error": "API key not configured",
        }

    return status


# ============================================================================
# Singleton accessor
# ============================================================================

_llm_instance: HybridLLMService | None = None


def get_llm_service(settings: Settings | None = None) -> HybridLLMService:
    """Get or create the global LLM service instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = HybridLLMService(settings)
    return _llm_instance
