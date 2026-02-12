"""MCP (Model Context Protocol) server for Lifelogger.

Exposes your personal activity data to Claude Desktop, enabling
conversations like:
- "What was I working on last week?"
- "When did I last discuss the budget?"
- "Am I more productive in mornings or afternoons?"

All data stays local - Claude queries your MCP server, which queries
your local TimescaleDB.
"""

from lifelogger.mcp.server import main, serve

__all__ = ["main", "serve"]
