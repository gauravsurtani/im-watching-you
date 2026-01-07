"""Web dashboard for lifelogger.

Provides a FastAPI-based web interface for querying and visualizing data.
"""

from lifelogger.web.app import create_app

__all__ = ["create_app"]
