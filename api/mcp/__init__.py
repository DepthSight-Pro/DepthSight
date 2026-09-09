"""
Model Context Protocol (MCP) package for DepthSight.
Exposes DepthSight algorithmic trading, backtesting, and market tools to external AI agents.
"""

from .dispatcher import MCPDispatcher
from .sse import sse_session_manager

__all__ = ["MCPDispatcher", "sse_session_manager"]
