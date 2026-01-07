"""Data source adapters for lifelogger.

Each source module provides functions to import data from various platforms
and convert them to the common ActivityEvent format.

NOTE: Sources do NOT perform classification. They store raw data with
source identification. Classification is done by the LLM service.
"""

from lifelogger.sources.activitywatch import ActivityWatchSource
from lifelogger.sources.browser import BrowserHistorySource
from lifelogger.sources.calendar import CalendarSource
from lifelogger.sources.transcripts import TranscriptSource
from lifelogger.sources.youtube import YouTubeSource

__all__ = [
    "ActivityWatchSource",
    "BrowserHistorySource",
    "CalendarSource",
    "TranscriptSource",
    "YouTubeSource",
]
