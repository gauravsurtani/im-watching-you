"""Data source adapters for lifelogger.

Each source module provides functions to import data from various platforms
and convert them to the common ActivityEvent format.
"""

from lifelogger.sources.activitywatch import ActivityWatchSource
from lifelogger.sources.transcripts import TranscriptSource

__all__ = ["ActivityWatchSource", "TranscriptSource"]
