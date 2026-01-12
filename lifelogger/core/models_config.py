"""Model configuration for task-specific LLM routing.

Based on research (Jan 2025), these are the best models for each task type.
All models listed here are FREE on OpenRouter.

Sources:
- https://openrouter.ai/collections/free-models
- https://openrouter.ai/docs/guides/features/structured-outputs
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(Enum):
    """Types of LLM tasks in the system."""

    # Fast, simple classification
    EVENT_CLASSIFICATION = "event_classification"

    # Batch classification (multiple events)
    BATCH_CLASSIFICATION = "batch_classification"

    # Complex analysis
    TRANSCRIPT_ANALYSIS = "transcript_analysis"

    # Daily/weekly digest generation
    DIGEST_GENERATION = "digest_generation"

    # URL/content analysis
    URL_ANALYSIS = "url_analysis"

    # General purpose
    GENERAL = "general"


@dataclass
class ModelSpec:
    """Specification for an LLM model."""

    id: str  # OpenRouter model ID
    name: str  # Human-readable name
    context_window: int  # Max tokens
    supports_json: bool  # Native JSON mode support
    supports_tools: bool  # Function calling support
    speed: str  # "fast", "medium", "slow"
    quality: str  # "basic", "good", "excellent"
    best_for: list[str] = field(default_factory=list)
    notes: str = ""


# ============================================================================
# Available Free Models on OpenRouter (as of Jan 2025)
# ============================================================================

AVAILABLE_MODELS: dict[str, ModelSpec] = {
    # === LLAMA MODELS ===
    "llama-3.2-3b": ModelSpec(
        id="meta-llama/llama-3.2-3b-instruct:free",
        name="Llama 3.2 3B",
        context_window=131072,
        supports_json=True,
        supports_tools=True,
        speed="fast",
        quality="basic",
        best_for=["simple classification", "quick tasks"],
        notes="Smallest, fastest. Good for high-volume simple tasks.",
    ),
    "llama-3.1-8b": ModelSpec(
        id="meta-llama/llama-3.1-8b-instruct:free",
        name="Llama 3.1 8B",
        context_window=131072,
        supports_json=True,
        supports_tools=True,
        speed="fast",
        quality="good",
        best_for=["classification", "summarization"],
        notes="Good balance. 100% JSON success rate with Response Healing.",
    ),
    "llama-3.3-70b": ModelSpec(
        id="meta-llama/llama-3.3-70b-instruct:free",
        name="Llama 3.3 70B",
        context_window=131072,
        supports_json=True,
        supports_tools=True,
        speed="slow",
        quality="excellent",
        best_for=["complex analysis", "long documents"],
        notes="Largest Llama. Best quality but slower.",
    ),

    # === GEMMA MODELS (Google) ===
    "gemma-2-9b": ModelSpec(
        id="google/gemma-2-9b-it:free",
        name="Gemma 2 9B",
        context_window=8192,
        supports_json=True,
        supports_tools=False,
        speed="fast",
        quality="good",
        best_for=["classification", "short text analysis"],
        notes="Fast and reliable. Good for classification tasks.",
    ),
    "gemma-3-12b": ModelSpec(
        id="google/gemma-3-12b-it:free",
        name="Gemma 3 12B",
        context_window=131072,
        supports_json=True,
        supports_tools=True,
        speed="medium",
        quality="good",
        best_for=["structured output", "function calling"],
        notes="Latest Gemma. 128k context, multimodal capable.",
    ),
    "gemma-3-27b": ModelSpec(
        id="google/gemma-3-27b-it:free",
        name="Gemma 3 27B",
        context_window=131072,
        supports_json=True,
        supports_tools=True,
        speed="medium",
        quality="excellent",
        best_for=["complex reasoning", "long context"],
        notes="Largest Gemma. Excellent for complex tasks.",
    ),

    # === MISTRAL MODELS ===
    "mistral-7b": ModelSpec(
        id="mistralai/mistral-7b-instruct:free",
        name="Mistral 7B",
        context_window=32768,
        supports_json=True,
        supports_tools=False,
        speed="fast",
        quality="good",
        best_for=["general tasks", "classification"],
        notes="Reliable workhorse model.",
    ),
    "mistral-small-24b": ModelSpec(
        id="mistralai/mistral-small-3.1-24b-instruct:free",
        name="Mistral Small 24B",
        context_window=96000,
        supports_json=True,
        supports_tools=True,
        speed="medium",
        quality="excellent",
        best_for=["function calling", "structured output", "complex analysis"],
        notes="Best for JSON structured output. Function calling optimized.",
    ),

    # === QWEN MODELS (Alibaba) ===
    "qwen-2.5-7b": ModelSpec(
        id="qwen/qwen-2.5-7b-instruct:free",
        name="Qwen 2.5 7B",
        context_window=32768,
        supports_json=True,
        supports_tools=True,
        speed="fast",
        quality="good",
        best_for=["multilingual", "coding"],
        notes="Good multilingual support.",
    ),
    "qwen-2.5-32b": ModelSpec(
        id="qwen/qwen2.5-vl-32b-instruct:free",
        name="Qwen 2.5 VL 32B",
        context_window=32768,
        supports_json=True,
        supports_tools=True,
        speed="medium",
        quality="excellent",
        best_for=["multimodal", "complex analysis"],
        notes="Vision-language model. Very capable.",
    ),
    "qwen-2.5-72b": ModelSpec(
        id="qwen/qwen2.5-vl-72b-instruct:free",
        name="Qwen 2.5 VL 72B",
        context_window=32768,
        supports_json=True,
        supports_tools=True,
        speed="slow",
        quality="excellent",
        best_for=["highest quality", "complex reasoning"],
        notes="Largest free Qwen. Top-tier quality.",
    ),

    # === OTHER MODELS ===
    "phi-4-14b": ModelSpec(
        id="microsoft/phi-4:free",
        name="Phi-4 14B",
        context_window=16384,
        supports_json=True,
        supports_tools=True,
        speed="fast",
        quality="good",
        best_for=["reasoning", "math", "coding"],
        notes="Microsoft's efficient reasoning model.",
    ),
    "deepseek-r1": ModelSpec(
        id="deepseek/deepseek-r1:free",
        name="DeepSeek R1",
        context_window=65536,
        supports_json=True,
        supports_tools=True,
        speed="medium",
        quality="excellent",
        best_for=["reasoning", "complex tasks"],
        notes="Strong reasoning capabilities.",
    ),
}


# ============================================================================
# Task-to-Model Mapping (Recommended Defaults)
# ============================================================================

DEFAULT_TASK_MODELS: dict[TaskType, list[str]] = {
    # Fast classification - prioritize speed
    TaskType.EVENT_CLASSIFICATION: [
        "llama-3.2-3b",      # Fastest
        "gemma-2-9b",        # Fallback
        "mistral-7b",        # Second fallback
    ],

    # Batch classification - balance speed and quality
    TaskType.BATCH_CLASSIFICATION: [
        "gemma-2-9b",        # Good JSON, fast
        "llama-3.1-8b",      # 100% JSON success
        "mistral-small-24b", # Best JSON if needed
    ],

    # Transcript analysis - prioritize quality (always local anyway)
    TaskType.TRANSCRIPT_ANALYSIS: [
        "mistral-small-24b", # Best for structured extraction
        "gemma-3-27b",       # High quality
        "llama-3.3-70b",     # Fallback
    ],

    # Digest generation - need good summarization
    TaskType.DIGEST_GENERATION: [
        "gemma-3-12b",       # Good summarization
        "mistral-small-24b", # Structured output
        "llama-3.1-8b",      # Fast fallback
    ],

    # URL analysis - simple task
    TaskType.URL_ANALYSIS: [
        "llama-3.2-3b",      # Fast enough
        "gemma-2-9b",        # Fallback
    ],

    # General purpose
    TaskType.GENERAL: [
        "gemma-3-12b",       # Good all-rounder
        "llama-3.1-8b",      # Fallback
        "mistral-7b",        # Second fallback
    ],
}


# ============================================================================
# Preset Configurations
# ============================================================================

@dataclass
class ModelPreset:
    """Preset configuration for different use cases."""

    name: str
    description: str
    classification_model: str
    analysis_model: str
    digest_model: str
    general_model: str


PRESETS: dict[str, ModelPreset] = {
    "speed": ModelPreset(
        name="Speed Optimized",
        description="Fastest response times, good for high-volume processing",
        classification_model="llama-3.2-3b",
        analysis_model="gemma-2-9b",
        digest_model="llama-3.1-8b",
        general_model="llama-3.2-3b",
    ),
    "balanced": ModelPreset(
        name="Balanced",
        description="Good balance of speed and quality (recommended)",
        classification_model="gemma-2-9b",
        analysis_model="mistral-small-24b",
        digest_model="gemma-3-12b",
        general_model="gemma-3-12b",
    ),
    "quality": ModelPreset(
        name="Quality Optimized",
        description="Best quality, slower processing",
        classification_model="gemma-3-12b",
        analysis_model="qwen-2.5-72b",
        digest_model="gemma-3-27b",
        general_model="gemma-3-27b",
    ),
    "minimal": ModelPreset(
        name="Minimal Resources",
        description="Smallest models, fastest, lowest resource usage",
        classification_model="llama-3.2-3b",
        analysis_model="llama-3.2-3b",
        digest_model="llama-3.2-3b",
        general_model="llama-3.2-3b",
    ),
}


def get_model_for_task(
    task: TaskType,
    preset: str = "balanced",
    custom_models: dict[TaskType, str] | None = None,
) -> ModelSpec:
    """Get the best model for a specific task.

    Args:
        task: The type of task
        preset: Preset name ("speed", "balanced", "quality", "minimal")
        custom_models: Optional custom task-to-model mapping

    Returns:
        ModelSpec for the recommended model
    """
    # Check custom mapping first
    if custom_models and task in custom_models:
        model_key = custom_models[task]
        if model_key in AVAILABLE_MODELS:
            return AVAILABLE_MODELS[model_key]

    # Check preset
    if preset in PRESETS:
        p = PRESETS[preset]
        model_key = {
            TaskType.EVENT_CLASSIFICATION: p.classification_model,
            TaskType.BATCH_CLASSIFICATION: p.classification_model,
            TaskType.TRANSCRIPT_ANALYSIS: p.analysis_model,
            TaskType.DIGEST_GENERATION: p.digest_model,
            TaskType.URL_ANALYSIS: p.classification_model,
            TaskType.GENERAL: p.general_model,
        }.get(task, p.general_model)

        if model_key in AVAILABLE_MODELS:
            return AVAILABLE_MODELS[model_key]

    # Fall back to defaults
    model_keys = DEFAULT_TASK_MODELS.get(task, ["gemma-2-9b"])
    for key in model_keys:
        if key in AVAILABLE_MODELS:
            return AVAILABLE_MODELS[key]

    # Ultimate fallback
    return AVAILABLE_MODELS["gemma-2-9b"]


def list_models_for_task(task: TaskType) -> list[ModelSpec]:
    """List all recommended models for a task, in priority order."""
    model_keys = DEFAULT_TASK_MODELS.get(task, ["gemma-2-9b"])
    return [AVAILABLE_MODELS[k] for k in model_keys if k in AVAILABLE_MODELS]


def get_model_by_id(model_id: str) -> ModelSpec | None:
    """Get model spec by OpenRouter model ID."""
    for spec in AVAILABLE_MODELS.values():
        if spec.id == model_id:
            return spec
    return None


def list_all_models() -> list[ModelSpec]:
    """List all available models."""
    return list(AVAILABLE_MODELS.values())


def get_preset(name: str) -> ModelPreset | None:
    """Get a preset by name."""
    return PRESETS.get(name)


def list_presets() -> list[ModelPreset]:
    """List all available presets."""
    return list(PRESETS.values())
