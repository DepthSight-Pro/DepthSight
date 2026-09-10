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
from .tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    tool_get_strategy_schema_and_examples,
    tool_get_historical_data_range,
)

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
    ResourceDefinition(
        uri="depthsight://docs/available_history.md",
        name="DepthSight Available Historical Data",
        description="List of all coins with loaded historical data, timeframes, and date boundaries in storage.",
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
                            "4. Verification & Auto-Memory: Run backtests via `run_backtest`. Provide `strategy_type` ('breakout', 'mean_reversion', 'trend_following', 'scalping', 'momentum') and `tags` (1 to 4 snake_case tags, selecting from the pool in `search_agent_memory`). MANDATORY: Always pass the `reasoning` parameter "
                            "explaining your strategy setup, triggers, and expected edge. DepthSight automatically records every backtest run "
                            "into your persistent memory bank and synthesizes learned rules in the background.\n"
                            "5. Evolutionary Iteration & Backtracking: Treat your best run as Baseline. Mutate only ONE parameter at a time. "
                            "Backtrack to the best baseline immediately if a mutation degrades metrics.\n"
                            "6. Stagnation Prevention (Patience = 3): Allow up to 3 mutation attempts to improve the best baseline. "
                            "If after 3 attempts there is no improvement or the baseline PnL remains non-profitable (<= 0%), the hypothesis is EXHAUSTED (Dead-End). "
                            "DISCARD this strategy architecture entirely and PIVOT to an alternative paradigm (Trend Breakout <-> Mean Reversion <-> Volatility Squeeze <-> Orderbook/Imbalance).\n"
                            "7. Persistent Learning: Inspect learned rules via `search_agent_memory`. You can also manually store high-level rules via `store_agent_memory`.\n"
                            "8. Live Operations: Check running bots with `get_bot_status`, monitor active positions with "
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

                content_text = await self._read_resource(uri, redis_client=redis_client)
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
                    style=style, symbol=symbol, user=user, db=db
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

    async def _read_resource(
        self, uri: str, redis_client: Optional[Any] = None
    ) -> Optional[str]:
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
        elif uri == "depthsight://docs/available_history.md":
            return await tool_get_historical_data_range(redis_client=redis_client)
        return None

    async def _generate_system_prompt(
        self,
        style: str,
        symbol: str,
        user: Optional[models.User] = None,
        db: Optional[AsyncSession] = None,
    ) -> str:
        """Generates rich quant system instructions incorporating codebase guidelines, plan limits, memory protocol, and active tag pool."""
        from api import crud

        user_tags: List[str] = []
        if db and user:
            try:
                user_tags = await crud.get_unique_agent_tags(db=db, user_id=user.id)
            except Exception as e:
                logger.debug(f"Failed to query unique tags for prompt: {e}")

        if user_tags:
            tags_pool_str = ", ".join(f"'{t}'" for t in user_tags)
            tags_section = (
                f"### Active Database Tags ({len(user_tags)} in memory pool):\n"
                f"[{tags_pool_str}]\n"
                f"*Protocol Rule: When formulating insights via `store_agent_memory`, pick 1 to 4 tags from this pool to maintain consistency across agent sessions. Only create a new snake_case tag if none fit.*\n\n"
            )
        else:
            tags_section = (
                "### Active Database Tags:\n"
                "[No tags stored in database yet. Create concise snake_case tags when saving insights.]\n\n"
            )

        allowed_types = await tool_get_strategy_schema_and_examples(
            category="allowed_types"
        )
        memory_guide = await tool_get_strategy_schema_and_examples(
            category="memory_guide"
        )

        plan_str = user.plan.lower() if user and user.plan else "free"
        is_pro = plan_str in ["pro", "institutional"]

        if not is_pro:
            tier_notes = (
                f"### CRITICAL SUBSCRIPTION PLAN RESTRICTION ({plan_str.upper()} Plan):\n"
                f"- User is on the **{plan_str.upper()}** plan (not PRO).\n"
                f"- **DO NOT use any PRO-only blocks** (`btc_state_filter`, `correlation`, `open_interest`, "
                f"`tape_condition`, `order_book_zone_condition`, `l2_microstructure`, `senior_tf_confluence`, `conditional_exit`, `trailing_stop`).\n"
                f"- **DO NOT request precision engine**. Always use standard indicators and specify `engine='vector'` for all backtests.\n\n"
            )
        else:
            tier_notes = (
                "### SUBSCRIPTION TIER: PRO\n"
                "- Full access to all advanced blocks (bookDepth percentage walls, Tape delta, Higher timeframe confluence, Trailing stop) "
                "and both 'vector' and 'precision' backtest engines.\n\n"
            )

        return (
            f"You are an elite quantitative trading strategy engineer operating on the DepthSight platform.\n"
            f"Target Trading Style: {style}\n"
            f"Target Asset: {symbol}\n\n"
            f"{tier_notes}"
            f"{tags_section}"
            f"### DepthSight Quant Agent Operating Protocol:\n"
            f"1. **Check Available History First**: Call `get_historical_data_range` to verify supported pairs and their loaded date intervals (start_date to end_date). "
            f"Note that DepthSight orderbook data is **bookDepth** (Binance Futures percentage buckets: ±0.2%, ±1.0%, ±2.0%, ±3.0%, ±4.0%, ±5.0%), NOT raw tick-level L2 ladder. "
            f"Never guess arbitrary dates or unsupported coins!\n"
            f"2. **Check Memory & Active Tags**: Call `search_agent_memory(symbol='{symbol}')` and review universal rules to discover past wins, failure modes, and active tags.\n"
            f"3. **Check Market Intelligence**: Call `get_market_metrics(symbol='{symbol}')` for NATR volatility, macro trend, and ML Oracle regime.\n"
            f"4. **No Isolated Guessing - Rich Block Synergies**: Single indicators (like RSI alone) mathematically fail. "
            f"Combine standard blocks across the entire spectrum: price consolidation, volatility squeeze, candlestick patterns, swing levels, volume confirmation, breakeven, and DCA/Grid.\n"
            f"5. **Mandatory Reasoning**: In every strategy JSON, include a structured `reasoning` field: Context, Setup, Success Factors, and Rule for Future.\n"
            f"6. **Iterate with Backtests**: Execute `run_backtest` (strictly within the symbol's available historical date range) to verify metrics (PnL%, Win Rate%, Drawdown%).\n"
            f"7. **Save Insights with Tag Consistency**: Call `store_agent_memory` after every backtest. "
            f"Prefer picking 1-4 tags from the active pool above. Always pass the pair in UPPERCASE in `symbol='{symbol}'` (not in tags).\n"
            f"8. **Evolutionary Optimization & Backtracking**: Treat your best backtest as the Baseline. "
            f"Mutate only ONE parameter at a time (e.g. adjust ATR multiplier, change indicator period, or add one filter). "
            f"If a mutation degrades performance, immediately revert to the best baseline!\n"
            f"9. **Stagnation Prevention (Patience Limit = 3) & Paradigm Pivot**: "
            f"Allow up to 3 mutation attempts to improve your best baseline. "
            f"If after 3 attempts there is no improvement, or if the baseline PnL remains negative (<= 0%), the hypothesis is EXHAUSTED (Local Minimum Trap). "
            f"You MUST DISCARD this strategy architecture entirely and PIVOT to a completely different market paradigm "
            f"(e.g. switch between: 1) Trend Breakout & Moving Averages, 2) Mean Reversion & Oscillators/Bollinger, 3) Volatility Squeeze & Volume Imbalance, 4) bookDepth Wall Bounce).\n"
            f"10. **Deploy & Save**: Persist verified positive configurations to user account via `save_strategy`.\n"
            f"11. **Monitor & Analyze**: Inspect active bots via `get_bot_status`, monitor positions via `get_open_positions`, "
            f"and evaluate real trade performance via `get_trading_analytics`.\n\n"
            f"{allowed_types}\n\n"
            f"{memory_guide}\n\n"
            f"CRITICAL: Always validate JSON types against the allowed list and never invent imaginary parameters!"
        )
