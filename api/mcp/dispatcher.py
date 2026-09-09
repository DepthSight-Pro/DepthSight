"""
Model Context Protocol (MCP 2025-03-26) Dispatcher.
Handles JSON-RPC 2.0 requests, protocol handshake, tools, resources, and prompts.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.ext.asyncio import AsyncSession

from api import models
from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    PromptArgument,
    PromptDefinition,
    ResourceDefinition,
    make_error_response,
    make_success_response,
    make_tool_result,
)
from .tools import TOOL_DEFINITIONS, execute_tool, tool_get_strategy_schema_and_examples

logger = logging.getLogger("depthsight.mcp.dispatcher")

# ---------------------------------------------------------------------------
# Resources and Prompts Catalogs
# ---------------------------------------------------------------------------

RESOURCE_DEFINITIONS: List[ResourceDefinition] = [
    ResourceDefinition(
        uri="depthsight://docs/strategy_schema.json",
        name="DepthSight Strategy Schema",
        description="JSON schema defining the valid structure, blocks, and parameters for Visual Builder strategies.",
        mimeType="application/json",
    ),
    ResourceDefinition(
        uri="depthsight://docs/strategy_examples.md",
        name="DepthSight Working Strategy Examples",
        description="Proven, working strategy configurations (Breakout, RSI Reversal, Trend Following) in JSON.",
        mimeType="text/markdown",
    ),
    ResourceDefinition(
        uri="depthsight://docs/block_reference.md",
        name="DepthSight Indicator and Block Catalog",
        description="Reference of all available filters, indicators, triggers, and position management blocks.",
        mimeType="text/markdown",
    ),
    ResourceDefinition(
        uri="depthsight://docs/codebase_reference.md",
        name="DepthSight Live Codebase Reference",
        description="Full extracted Python execution blocks and Pydantic schemas from api/schemas.py and bot_module/strategy.py.",
        mimeType="text/markdown",
    ),
    ResourceDefinition(
        uri="depthsight://docs/memory_protocol.md",
        name="DepthSight Agent Memory Protocol",
        description="Guidelines for searching memory, rule synthesis, deduplication, and structured classification tagging.",
        mimeType="text/markdown",
    ),
    ResourceDefinition(
        uri="depthsight://docs/allowed_blocks.md",
        name="DepthSight Strict Allowed Types & Block Catalog",
        description="Authoritative copy-paste list of allowed types for filters, foundation blocks, conditions, and position management.",
        mimeType="text/markdown",
    ),
]

PROMPT_DEFINITIONS: List[PromptDefinition] = [
    PromptDefinition(
        name="depthsight_quant_developer",
        description="Configures the AI as an elite algorithmic trading quant specializing in DepthSight visual strategies.",
        arguments=[
            PromptArgument(
                name="trading_style",
                description="Target trading style (e.g. 'scalping', 'trend_following', 'reversal').",
                required=False,
            ),
            PromptArgument(
                name="target_symbol",
                description="Target pair symbol (e.g. 'BTCUSDT').",
                required=False,
            ),
        ],
    )
]


class MCPDispatcher:
    """Core dispatcher for JSON-RPC 2.0 messages over Streamable HTTP and SSE."""

    def __init__(self):
        self.server_name = "depthsight-mcp"
        self.server_version = "1.0.0"

    async def dispatch(
        self,
        request_data: Union[Dict[str, Any], List[Dict[str, Any]]],
        user: models.User,
        db: AsyncSession,
        redis_client: Optional[Any] = None,
    ) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """Handles single or batch JSON-RPC 2.0 requests."""
        if isinstance(request_data, list):
            responses = []
            for item in request_data:
                res = await self._dispatch_single(item, user, db, redis_client)
                if res is not None:
                    responses.append(res)
            return responses

        return await self._dispatch_single(request_data, user, db, redis_client)

    async def _dispatch_single(
        self,
        msg: Dict[str, Any],
        user: models.User,
        db: AsyncSession,
        redis_client: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(msg, dict):
            return make_error_response(
                None, INVALID_REQUEST, "Invalid JSON-RPC 2.0 request payload."
            )

        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if not method or not isinstance(method, str):
            return make_error_response(
                req_id, INVALID_REQUEST, "Missing or invalid 'method' field."
            )

        try:
            # 1. Handshake & Initialization (negotiates client requested version or latest 2026-07-28)
            if method == "initialize":
                client_version = params.get("protocolVersion")
                negotiated_version = (
                    client_version
                    if client_version in SUPPORTED_PROTOCOL_VERSIONS
                    else LATEST_PROTOCOL_VERSION
                )
                return make_success_response(
                    req_id,
                    {
                        "protocolVersion": negotiated_version,
                        "capabilities": {
                            "tools": {"listChanged": False},
                            "resources": {"subscribe": False, "listChanged": False},
                            "prompts": {"listChanged": False},
                        },
                        "serverInfo": {
                            "name": self.server_name,
                            "version": self.server_version,
                        },
                        "instructions": (
                            "DepthSight Algorithmic Trading Platform MCP Server.\n\n"
                            "### Agent Trading & Memory Protocol:\n"
                            "1. Prior Experience: ALWAYS call `search_agent_memory` before designing strategies for a symbol.\n"
                            "2. Market Intelligence: Check live volatility (NATR) and regime via `get_market_metrics`.\n"
                            "3. Precision Schemas: Call `get_strategy_schema_and_examples` (with category or block_name) "
                            "to inspect exact Python parameters and avoid hallucinating block names.\n"
                            "4. Verification: Run backtests via `run_backtest` to validate performance metrics.\n"
                            "5. Persistent Learning: After backtesting, synthesize actionable non-duplicate rules "
                            "and persist them with `store_agent_memory`.\n"
                            "6. Live Operations: Check running bots with `get_bot_status`, monitor active positions with "
                            "`get_open_positions`, and review performance metrics with `get_trading_analytics`."
                        ),
                    },
                )

            # 2. Initialized Notification (no response needed for notifications)
            elif method == "notifications/initialized":
                return None

            # 3. Ping / Liveness Check
            elif method == "ping":
                return make_success_response(req_id, {})

            # 4. Tools Catalog (supports 2026 caching ttlMs)
            elif method == "tools/list":
                tools_payload = [t.model_dump() for t in TOOL_DEFINITIONS]
                return make_success_response(
                    req_id,
                    {
                        "tools": tools_payload,
                        "_meta": {
                            "ttlMs": 300000,
                            "cacheScope": "user",
                        },
                    },
                )

            # 5. Tool Call Execution
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments") or {}

                if not tool_name:
                    return make_error_response(
                        req_id, INVALID_PARAMS, "Missing tool 'name' parameter."
                    )

                try:
                    text_result = await execute_tool(
                        name=tool_name,
                        arguments=arguments,
                        user=user,
                        db=db,
                        redis_client=redis_client,
                    )
                    return make_success_response(req_id, make_tool_result(text_result))
                except ValueError as e:
                    return make_error_response(req_id, METHOD_NOT_FOUND, str(e))
                except Exception as e:
                    logger.error(
                        f"Error executing tool '{tool_name}' for user {user.id}: {e}",
                        exc_info=True,
                    )
                    return make_success_response(
                        req_id,
                        make_tool_result(f"Error executing tool: {e}", is_error=True),
                    )

            # 6. Resources Catalog
            elif method == "resources/list":
                resources_payload = [r.model_dump() for r in RESOURCE_DEFINITIONS]
                return make_success_response(req_id, {"resources": resources_payload})

            # 7. Resource Reading
            elif method == "resources/read":
                uri = params.get("uri")
                if not uri:
                    return make_error_response(
                        req_id, INVALID_PARAMS, "Missing 'uri' parameter."
                    )

                content_text = await self._read_resource(uri)
                if content_text is None:
                    return make_error_response(
                        req_id, INVALID_PARAMS, f"Resource not found: {uri}"
                    )

                return make_success_response(
                    req_id,
                    {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "text/markdown",
                                "text": content_text,
                            }
                        ]
                    },
                )

            # 8. Prompts Catalog
            elif method == "prompts/list":
                prompts_payload = [p.model_dump() for p in PROMPT_DEFINITIONS]
                return make_success_response(req_id, {"prompts": prompts_payload})

            # 9. Prompt Retrieval
            elif method == "prompts/get":
                prompt_name = params.get("name")
                if prompt_name != "depthsight_quant_developer":
                    return make_error_response(
                        req_id, METHOD_NOT_FOUND, f"Prompt '{prompt_name}' not found."
                    )

                style = params.get("arguments", {}).get(
                    "trading_style", "scalping / intraday"
                )
                symbol = params.get("arguments", {}).get("target_symbol", "BTCUSDT")

                system_prompt_content = await self._generate_system_prompt(
                    style=style, symbol=symbol
                )
                return make_success_response(
                    req_id,
                    {
                        "description": f"DepthSight Quant Developer configured for {style} on {symbol}.",
                        "messages": [
                            {
                                "role": "user",
                                "content": {
                                    "type": "text",
                                    "text": system_prompt_content,
                                },
                            }
                        ],
                    },
                )

            # Unknown Method
            else:
                logger.warning(f"MCP method not found: {method}")
                return make_error_response(
                    req_id, METHOD_NOT_FOUND, f"Method not found: {method}"
                )

        except Exception as e:
            logger.error(
                f"Internal error processing MCP method {method}: {e}", exc_info=True
            )
            return make_error_response(
                req_id, INTERNAL_ERROR, f"Internal error: {str(e)}"
            )

    async def _read_resource(self, uri: str) -> Optional[str]:
        """Loads resource content on-demand."""
        if uri == "depthsight://docs/strategy_schema.json":
            return await tool_get_strategy_schema_and_examples(category="blocks")
        elif uri == "depthsight://docs/strategy_examples.md":
            return await tool_get_strategy_schema_and_examples(category="examples")
        elif uri == "depthsight://docs/block_reference.md":
            return await tool_get_strategy_schema_and_examples(category="summary")
        elif uri == "depthsight://docs/codebase_reference.md":
            return await tool_get_strategy_schema_and_examples(category="codebase")
        elif uri == "depthsight://docs/memory_protocol.md":
            return await tool_get_strategy_schema_and_examples(category="memory_guide")
        elif uri == "depthsight://docs/allowed_blocks.md":
            return await tool_get_strategy_schema_and_examples(category="allowed_types")
        return None

    async def _generate_system_prompt(self, style: str, symbol: str) -> str:
        """Generates rich quant system instructions incorporating codebase guidelines and memory protocol."""
        allowed_types = await tool_get_strategy_schema_and_examples(
            category="allowed_types"
        )
        memory_guide = await tool_get_strategy_schema_and_examples(
            category="memory_guide"
        )
        return (
            f"You are an elite quantitative trading strategy engineer operating on the DepthSight platform.\n"
            f"Target Trading Style: {style}\n"
            f"Target Asset: {symbol}\n\n"
            f"### DepthSight Quant Agent Operating Protocol:\n"
            f"1. **Check Memory First**: Call `search_agent_memory(symbol='{symbol}')` to discover past wins and failure modes.\n"
            f"2. **Check Market Intelligence**: Call `get_market_metrics(symbol='{symbol}')` for NATR volatility and Oracle regime.\n"
            f"3. **Consult Exact Code**: Use `get_strategy_schema_and_examples` (with category or block_name) to inspect exact Python blocks and parameters.\n"
            f"4. **Iterate with Backtests**: Execute `run_backtest` to verify metrics (PnL%, Win Rate%, Drawdown%).\n"
            f"5. **Save Rules**: Store actionable non-duplicate findings via `store_agent_memory`.\n"
            f"6. **Deploy**: Persist verified configurations to user account via `save_strategy`.\n"
            f"7. **Monitor & Analyze**: Inspect active bots via `get_bot_status`, monitor positions via `get_open_positions`, "
            f"and evaluate real trade performance via `get_trading_analytics`.\n\n"
            f"{allowed_types}\n\n"
            f"{memory_guide}\n\n"
            f"CRITICAL: Always validate JSON types against the allowed list and never invent imaginary parameters!"
        )
