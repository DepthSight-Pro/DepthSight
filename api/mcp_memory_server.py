"""
MCP (Model Context Protocol) Memory Server for DepthSight.
Provides memory search tools to AI agents via JSON-RPC 2.0 over TCP.
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("mcp_memory_server")

MCP_MEMORY_PORT = int(os.environ.get("MCP_MEMORY_PORT", "8100"))
MCP_MEMORY_HOST = os.environ.get("MCP_MEMORY_HOST", "127.0.0.1")


class MCPMemoryServer:
    """TCP-based MCP server exposing agent memory tools."""

    def __init__(self, host: str = MCP_MEMORY_HOST, port: int = MCP_MEMORY_PORT):
        self.host = host
        self.port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._tools = [
            {
                "name": "search_agent_memory",
                "description": "Searches the agent's persistent memory bank for historical strategy insights, rules, and outcomes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "User ID to search memories for (required)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of tags to filter (e.g. ['breakout', 'volume'])",
                        },
                        "symbol": {
                            "type": "string",
                            "description": "Optional trading symbol (e.g. 'ETHUSDT')",
                        },
                        "strategy_type": {
                            "type": "string",
                            "description": "Optional strategy type (e.g. 'breakout', 'mean_reversion')",
                        },
                    },
                    "required": ["user_id"],
                },
            }
        ]

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info(f"MCP Memory Server listening on {self.host}:{self.port}")
        await self._server.serve_forever()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("MCP Memory Server stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        logger.debug(f"MCP client connected: {addr}")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = json.loads(line.decode().strip())
                response = await self._dispatch(msg)
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
        except (
            asyncio.IncompleteReadError,
            ConnectionResetError,
            json.JSONDecodeError,
        ) as e:
            logger.debug(f"MCP client disconnected ({addr}): {e}")
        finally:
            writer.close()

    async def _dispatch(self, msg: dict) -> dict:
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "depthsight-memory",
                            "version": "1.0.0",
                        },
                    },
                }
            elif method == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": self._tools},
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                if tool_name == "search_agent_memory":
                    result = await self._search_agent_memory(**arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": result}]},
                    }
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}",
                    },
                }
            elif method == "notifications/initialized":
                return None
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        except Exception as e:
            logger.error(f"MCP error handling {method}: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)},
            }

    async def _search_agent_memory(
        self,
        user_id: int,
        tags: Optional[list] = None,
        symbol: Optional[str] = None,
        strategy_type: Optional[str] = None,
    ) -> str:
        """Cascade search: Rules -> Exact insights -> Cross-asset transfer."""
        from .database import async_session_factory
        from . import crud

        async with async_session_factory() as db:
            rules = await crud.search_agent_memories(
                db,
                user_id=user_id,
                memory_type="rule",
                tags=tags,
                strategy_type=strategy_type,
                limit=2,
            )
            exact = await crud.search_agent_memories(
                db,
                user_id=user_id,
                memory_type="strategy_insight",
                symbol=symbol,
                tags=tags,
                strategy_type=strategy_type,
                limit=3,
            )
            budget = 8 - (len(rules) + len(exact))
            transfer = []
            if budget > 0 and strategy_type:
                candidates = await crud.search_agent_memories(
                    db,
                    user_id=user_id,
                    memory_type="strategy_insight",
                    strategy_type=strategy_type,
                    limit=budget + 5,
                )
                seen_ids = {m.id for m in exact}
                for c in candidates:
                    if (
                        c.symbol
                        and symbol
                        and c.symbol.upper() != symbol.upper()
                        and c.id not in seen_ids
                    ):
                        transfer.append(c)
                        seen_ids.add(c.id)
                        if len(transfer) >= budget:
                            break

            lines = []
            if rules:
                lines.append("**Universal Rules:**")
                for r in rules:
                    lines.append(f"- [conf: {r.confidence * 100:.0f}%] {r.content}")
            if exact:
                lines.append(f"\n**{symbol or 'Target'} Insights:**")
                for m in exact:
                    icon = "success" if m.outcome == "success" else "failure"
                    lines.append(f"- [{icon.upper()}] {m.content}")
            if transfer:
                lines.append("\n**Cross-Asset Transfer:**")
                for m in transfer:
                    lines.append(
                        f"- ⚡ [Transfer from {m.symbol}] [{m.outcome.upper()}] {m.content}"
                    )
            if not lines:
                return "No matching memories found."
            return "\n".join(lines)


class MCPClient:
    """Client that connects to the local MCP Memory Server."""

    def __init__(self, host: str = MCP_MEMORY_HOST, port: int = MCP_MEMORY_PORT):
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._initialized = False
        self._tools: list[dict] = []

    async def connect(self, retries: int = 5, delay: float = 0.3):
        if self._initialized:
            return
        last_error = None
        for attempt in range(retries):
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
                break
            except (ConnectionRefusedError, OSError) as e:
                last_error = e
                await asyncio.sleep(delay * (attempt + 1))
        else:
            raise ConnectionError(
                f"Cannot connect to MCP Memory Server at {self.host}:{self.port} after {retries} attempts: {last_error}"
            )

        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "depthsight-ai", "version": "1.0.0"},
            },
        )
        self._initialized = True
        await self._send_request("notifications/initialized", {})
        tools_result = await self._send_request("tools/list", {})
        self._tools = tools_result.get("tools", [])

    async def close(self):
        if self._writer:
            self._writer.close()
            self._initialized = False

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> Any:
        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        content = result.get("content", [])
        if content:
            return content[0].get("text", "")
        return ""

    async def _send_request(self, method: str, params: dict) -> dict:
        req = (
            json.dumps(
                {"jsonrpc": "2.0", "id": id(self), "method": method, "params": params}
            )
            + "\n"
        )
        self._writer.write(req.encode())
        await self._writer.drain()
        line = await self._reader.readline()

        resp = json.loads(line.decode().strip()) or {}

        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error']}")
        return resp.get("result", {})


_mcp_server_instance: Optional[MCPMemoryServer] = None
_mcp_client_instance: Optional[MCPClient] = None


def _is_local_mcp() -> bool:
    """Check if the MCP server should run locally (in-process) vs. connecting to a remote one."""
    host = (os.environ.get("MCP_MEMORY_HOST") or "").strip().lower()
    return not host or host in ("127.0.0.1", "localhost", "0.0.0.0")


async def ensure_mcp_server():
    """Start the MCP server locally only when MCP_MEMORY_HOST is localhost/127.0.0.1."""
    global _mcp_server_instance
    if not _is_local_mcp():
        return None
    if _mcp_server_instance is None:
        _mcp_server_instance = MCPMemoryServer()
        await _mcp_server_instance.start()
    return _mcp_server_instance


async def get_mcp_client() -> MCPClient:
    global _mcp_client_instance
    if _mcp_client_instance is None:
        if _is_local_mcp():
            await ensure_mcp_server()
        _mcp_client_instance = MCPClient()
        await _mcp_client_instance.connect()
    return _mcp_client_instance
