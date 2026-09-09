"""
MCP Tool definitions and handlers for DepthSight.
Exposes algorithmic trading, backtesting, strategy management, and market intelligence tools.
"""

import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, models, schemas
from api.celery_app import celery_app
from api.plans import plans_config
from .protocol import ToolDefinition

logger = logging.getLogger("depthsight.mcp.tools")

# ---------------------------------------------------------------------------
# Tool Catalog (JSON Schema specifications for MCP clients)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: List[ToolDefinition] = [
    ToolDefinition(
        name="get_strategy_schema_and_examples",
        description=(
            "Returns schemas, Python codebase blocks, allowed type definitions, "
            "memory protocols, and working JSON examples for DepthSight Visual Builder strategies. "
            "ALWAYS call this tool if you need to know exact block parameters, indicators, "
            "and syntax before running backtests or saving strategies."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "all",
                        "summary",
                        "blocks",
                        "schemas",
                        "examples",
                        "codebase",
                        "indicators",
                        "filters",
                        "memory_guide",
                        "allowed_types",
                    ],
                    "description": (
                        "Information category: 'summary' (compact overview), 'codebase' (live Python/Pydantic code), "
                        "'indicators' (indicator condition blocks), 'filters' (regime/volatility filters), "
                        "'allowed_types' (strict copy-paste allowed block types), 'memory_guide' (rules for synthesizing "
                        "and storing agent memory), or 'examples' (working JSON strategies). Default: 'summary'."
                    ),
                },
                "block_name": {
                    "type": "string",
                    "description": (
                        "Optional specific block name to inspect (e.g. 'trend_filter', 'value_comparison', "
                        "'trailing_stop', 'move_to_breakeven'). If provided, returns exact Python code for this block."
                    ),
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_market_metrics",
        description=(
            "Fetches live market intelligence metrics for a trading pair from the DepthSight Screener. "
            "Returns Normalized ATR (NATR volatility), 1H vs 6H macro trend, ML Oracle regime (Flat vs Impulse), "
            "and 24-hour volume in USD."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol in USDT (e.g. 'BTCUSDT', 'ETHUSDT', 'SOLUSDT').",
                }
            },
            "required": ["symbol"],
        },
    ),
    ToolDefinition(
        name="run_backtest",
        description=(
            "Queues and executes an algorithmic backtest simulation on historical market data. "
            "Validates user plan limits and quotas (Free: up to 20/day, max 90 days history; "
            "Standard: 50/day, 365 days; Pro: unlimited). "
            "Returns key performance indicators (PnL%, Win Rate%, Total Trades, Max Drawdown%, Profit Factor)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol (e.g. 'BTCUSDT').",
                },
                "strategy_config": {
                    "type": "object",
                    "description": (
                        "Complete Visual Builder strategy JSON object. "
                        "If you don't know the structure, call 'get_strategy_schema_and_examples' first."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format YYYY-MM-DD (e.g. '2026-06-01').",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in ISO format YYYY-MM-DD (e.g. '2026-08-31').",
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"],
                    "description": "Candle timeframe (default: '15m').",
                },
                "engine": {
                    "type": "string",
                    "enum": ["vector", "precision"],
                    "description": "Backtest engine: 'vector' (Turbo, fast) or 'precision' (Kline tick-level, Pro). Default: 'vector'.",
                },
                "strategy_name": {
                    "type": "string",
                    "description": "Optional human-readable name for the strategy run.",
                },
            },
            "required": ["symbol", "strategy_config", "start_date", "end_date"],
        },
    ),
    ToolDefinition(
        name="list_strategies",
        description="Lists all saved strategy configurations belonging to the authenticated user.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="get_strategy",
        description="Retrieves full configuration details and blocks of a specific saved strategy by its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "config_id": {
                    "type": "string",
                    "description": "Unique UUID of the saved strategy configuration.",
                }
            },
            "required": ["config_id"],
        },
    ),
    ToolDefinition(
        name="save_strategy",
        description=(
            "Saves a new strategy configuration or updates an existing one in the user's DepthSight account. "
            "Enforces block plan restrictions (Pro blocks require Pro plan)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Display name of the strategy.",
                },
                "strategy_config": {
                    "type": "object",
                    "description": "Valid Visual Builder strategy JSON object.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional target trading pair (e.g. 'BTCUSDT').",
                },
                "timeframe": {
                    "type": "string",
                    "description": "Optional default timeframe (e.g. '15m').",
                },
                "description": {
                    "type": "string",
                    "description": "Optional notes or explanation of strategy logic.",
                },
            },
            "required": ["name", "strategy_config"],
        },
    ),
    ToolDefinition(
        name="search_agent_memory",
        description=(
            "Cascading search through the user's persistent agent memory bank and learned trading rules. "
            "Returns past insights, winning patterns, and failure modes filtered by tags, symbol, or strategy type. "
            "PROTOCOL: Call this tool FIRST before generating or modifying any strategy to avoid repeating known mistakes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filter tags (e.g. ['breakout', 'rsi', 'scalping']).",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair to filter (e.g. 'BTCUSDT').",
                },
                "strategy_type": {
                    "type": "string",
                    "description": "Optional strategy category (e.g. 'breakout', 'mean_reversion', 'trend', 'scalping', 'momentum').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of memories to return (default: 10).",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="store_agent_memory",
        description=(
            "Persists an actionable trading insight, synthesized rule, or backtest lesson into the user's "
            "agent memory bank. Follow the Memory Protocol: formulate clear actionable rules, avoid duplicates, "
            "and assign structured classification tags."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "Actionable rule or insight. Format: '[Market condition/Context] -> [Parameter/Indicator rule] "
                        "to prevent [failure mode] / capture [edge]'. Example: 'For breakout setups on 15m BTCUSDT, "
                        "require trend_filter ADX > 25 to avoid false breaks.'"
                    ),
                },
                "strategy_type": {
                    "type": "string",
                    "description": "Strategy type: 'breakout', 'mean_reversion', 'trend_following', 'scalping', or 'momentum'.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1 to 4 descriptive snake_case tags (e.g. ['volatility', 'adx', 'take_profit_3pct']).",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair symbol (e.g. 'BTCUSDT').",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "neutral"],
                    "description": "Outcome classification of the setup/rule.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score between 0.1 and 1.0 (default: 0.85).",
                },
            },
            "required": ["content", "strategy_type", "tags", "outcome"],
        },
    ),
    ToolDefinition(
        name="get_bot_status",
        description="Returns currently active live and paper trading bots for the authenticated user, including running symbols, timeframes, and execution states.",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["live", "paper", "all"],
                    "description": "Filter by trading mode (default: 'all').",
                }
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_open_positions",
        description=(
            "Retrieves active trading positions for the authenticated user from live or paper trading bots. "
            "Returns position direction (LONG/SHORT), entry price, current mark price, quantity/size, "
            "unrealized PnL ($ and %), and active Stop Loss / Take Profit prices."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["all", "live", "paper"],
                    "description": "Filter by trading mode ('live', 'paper', or 'all'). Default: 'all'.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair to filter (e.g. 'BTCUSDT').",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="get_trading_analytics",
        description=(
            "Retrieves trading performance analytics and KPI breakdown for the user's closed trades. "
            "Returns Net PnL, Win Rate %, Profit Factor, total commission fees, average trade metrics, "
            "and lists top winning and losing trades with exit reasons."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["live", "paper"],
                    "description": "Trading mode ('live' or 'paper'). Default: 'live'.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair symbol filter (e.g. 'BTCUSDT').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent trades to analyze (default: 50, max: 200).",
                },
            },
            "required": [],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Codebase Context & Reference Protocol
# ---------------------------------------------------------------------------

_CODEBASE_CONTEXT_CACHE: Optional[Dict[str, str]] = None


def get_cached_codebase_context() -> Dict[str, str]:
    """Extracts and caches code blocks marked with # AI_CONTEXT_START / END
    from api/schemas.py and bot_module/strategy.py.
    """
    global _CODEBASE_CONTEXT_CACHE
    if _CODEBASE_CONTEXT_CACHE is not None:
        return _CODEBASE_CONTEXT_CACHE

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    paths = [
        os.path.join(repo_root, "api", "schemas.py"),
        os.path.join(repo_root, "bot_module", "strategy.py"),
    ]
    context_blocks: Dict[str, str] = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
                found = re.findall(
                    r"^\s*# AI_CONTEXT_START: (.+?)\s*?\n(.*?)\n^\s*# AI_CONTEXT_END\s*?$",
                    content,
                    re.DOTALL | re.MULTILINE,
                )
                for block_name, code in found:
                    key = f"{os.path.basename(p)}_{block_name.strip()}"
                    context_blocks[key] = code.strip()
        except Exception as e:
            logger.error(f"Error reading codebase context from {p}: {e}")

    _CODEBASE_CONTEXT_CACHE = context_blocks
    return _CODEBASE_CONTEXT_CACHE


ALLOWED_TYPES_DOC = """# DepthSight Visual Builder Strict Type Checklist

**ABSOLUTELY CRITICAL**: You MUST use ONLY these exact type values in your JSON configurations.
Do NOT invent new types. Do NOT use similar-sounding names.

## Filters (use in `filters` section):
- `rel_vol_filter`: relative volume threshold
- `trend_filter`: ADX threshold + direction
- `btc_state_filter` (PRO only): BTC market regime ("Consolidation", "Trending Up", "Trending Down", "Any")
- `correlation` (PRO only): correlation against BTC/ETH
- `trading_session`: session hours (UTC)
- `volatility_filter`: ATR threshold
- `senior_tf_confluence` (PRO only): higher timeframe indicator alignment

## Foundations & Decision Blocks (use in `entryConditions` section):
### Data Providers:
- `tape_analysis`: aggressive buyer/seller delta flow
- `order_book_zone`: depth ratio and wall detection
- `local_level`: high/low swings
- `significant_level`: key support/resistance zones

### Decision Blocks:
- `value_comparison`: compare indicators (RSI, EMA, MACD, Stochastic, Bollinger Bands, ATR)
- `trend_direction`: EMA fast vs slow slope
- `volume_confirmation`: volume spikes vs average
- `classic_pattern`: engulfing, pinbar, breakout
- `price_consolidation`: channel breakout
- `open_interest`: OI surge / liquidation traps
- `round_level`: psychological round price levels
- `return_to_level`: retest of broken level
- `level_touch_analyzer`: number of level touches
- `volatility_squeeze`: Bollinger inside Keltner squeeze
- `price_action_analyzer`: multi-candle structure

## Position Management (use in `positionManagement` section):
- `move_to_breakeven`: trigger_pct, offset_pct
- `trailing_stop`: activation_pct, callback_pct
- `scale_in`: gradual entry execution
- `conditional_management`: indicator-driven exit
- `modify_stop_loss`: dynamic SL adjustment
- `modify_take_profit`: dynamic TP adjustment
- `close_position`: immediate market exit
- `dca_management`: dollar-cost averaging steps
- `grid_management`: geometric/arithmetic grid orders

## Logic Containers:
- `AND`: all child conditions must be true
- `OR`: at least one child condition must be true

## Actions & Triggers:
- `open_position` (use in `initialization` only)
- `on_candle_close` (use in `entryTrigger` only)
- `on_tick` (use in `entryTrigger` only)
- `on_condition_met` (use in `entryTrigger` only)
"""

MEMORY_GUIDE_DOC = """# DepthSight Agent Memory & Quant Protocol Guide

## 1. The Core Quant Development Loop
Every autonomous trading agent operating on DepthSight must follow this 6-step loop:
1. **Search Experience**: Call `search_agent_memory(symbol=..., strategy_type=...)` before formulating any strategy. Check what setups have previously failed or succeeded on this asset.
2. **Inspect Market Regime**: Call `get_market_metrics(symbol=...)` to check current NATR volatility, 1H vs 6H macro trend, and ML Oracle regime (Flat vs Impulse).
3. **Verify Schemas**: Call `get_strategy_schema_and_examples(block_name=...)` to inspect exact Python parameters and allowed block types.
4. **Validate Performance**: Run simulations via `run_backtest(symbol=..., strategy_config=...)`. Evaluate PnL%, Win Rate%, Profit Factor, and Max Drawdown%.
5. **Formulate & Persist Rules**: Extract actionable findings and store them in persistent memory via `store_agent_memory(...)`.
6. **Deploy Strategy**: If backtest KPIs meet criteria (Win Rate > 55%, Profit Factor > 1.4, Drawdown < 15%), persist the strategy using `save_strategy(...)`.

## 2. Rule Synthesis & Deduplication (CRITICAL)
When calling `store_agent_memory`, synthesize **high-confidence, actionable rules** for future strategy generations:
- Focus on specific indicators, filters, or parameters.
- **Actionable Rule Format**:
  `[Market Condition / Context] -> [Actionable Parameter / Filter Rule] to prevent [Failure Mode] / capture [Opportunity]`
  - *Example 1 (Failure Prevention)*: "For breakout setups on 15m BTCUSDT, always require `trend_filter` (ADX > 25) and volume confirmation multiplier > 1.8x to eliminate fakeouts in consolidation."
  - *Example 2 (Edge Capture)*: "In high volatility (NATR > 0.015), RSI oversold dips (RSI <= 28) paired with `trailing_stop` (activation 1.5%, callback 0.4%) achieve 68% win rate on ETHUSDT."
- **Deduplication Rule**: Compare your proposed insight with existing rules returned by `search_agent_memory`. If a rule with a similar concept, indicator parameter, or trade filter already exists, **DO NOT** create a duplicate.

## 3. Classification & Tagging Conventions
- **strategy_type**: Must be one of:
  - `"breakout"` (channel/level breaks)
  - `"mean_reversion"` (RSI/Bollinger/Stochastic counter-trend pullbacks)
  - `"trend_following"` (EMA/MACD/ADX trend continuation)
  - `"scalping"` (quick momentum/orderbook/tape scalps)
  - `"momentum"` (impulse/volume spikes)
- **outcome**:
  - `"success"`: strategy demonstrated robust profitability.
  - `"failure"`: strategy suffered severe drawdowns or toxic trade clusters.
  - `"neutral"`: mixed results or inconclusive tests.
- **tags**: Choose 1 to 4 concise `snake_case` tags (e.g. `["adx", "rsi_pullback", "volatility", "trailing_stop", "orderbook"]`).
"""


async def tool_get_strategy_schema_and_examples(
    category: str = "summary",
    block_name: Optional[str] = None,
) -> str:
    """Returns documentation, schemas, codebase references, and examples for Visual Builder strategies."""
    # 1. Inspect specific block by name if requested
    if block_name:
        block_name_clean = block_name.strip().lower()
        codebase = get_cached_codebase_context()

        # 1a. Direct substring match
        matches = {k: v for k, v in codebase.items() if block_name_clean in k.lower()}

        # 1b. Token / word overlap match if no direct substring match
        if not matches:
            words = [w for w in re.split(r"[_\s\-]+", block_name_clean) if len(w) > 2]
            if words:
                matches = {
                    k: v
                    for k, v in codebase.items()
                    if all(w in k.lower() for w in words)
                }

        # 1c. Visual Builder block aliases
        if not matches:
            aliases = {
                "trend_filter": ["trend_strength", "adx"],
                "volatility_filter": ["volatility", "natr"],
                "rel_vol_filter": ["rel_vol"],
                "trailing_stop": ["ManagementBlocks"],
                "move_to_breakeven": ["ManagementBlocks"],
                "value_comparison": ["ConditionBlocks"],
            }
            if block_name_clean in aliases:
                target_terms = aliases[block_name_clean]
                matches = {
                    k: v
                    for k, v in codebase.items()
                    if any(term in k.lower() for term in target_terms)
                }

        if matches:
            sections = [
                f"### DepthSight Codebase Reference for '{block_name}' ({len(matches)} match{'es' if len(matches) > 1 else ''}):"
            ]
            for k, code in sorted(matches.items()):
                sections.append(f"#### From: `{k}`\n```python\n{code}\n```")
            return "\n\n".join(sections)
        else:
            available = sorted(list(codebase.keys()))
            return (
                f"No exact codebase block matched '{block_name}'.\n"
                f"Available blocks in codebase ({len(available)} total):\n"
                + "\n".join(f"- `{name}`" for name in available[:30])
                + (
                    f"\n... and {len(available) - 30} more."
                    if len(available) > 30
                    else ""
                )
            )

    blocks_doc = """## DepthSight Visual Builder Strategy Schema

A DepthSight strategy is represented as a structured JSON object containing:
- `symbol`: string (e.g. "BTCUSDT")
- `timeframe`: string (e.g. "15m", "1h")
- `direction`: "LONG" | "SHORT" | "BOTH"
- `filters`: Root condition group containing market regime/trend/volatility filters.
- `entryConditions`: Root condition group defining entry criteria.
- `entryTrigger`: Execution trigger:
  - `{"type": "on_candle_close"}`
  - `{"type": "on_condition_met"}`
- `initialization`: Position setup:
  - `open_position` with `position_size_type`, `position_size_value`, `stop_loss_pct`, `take_profit_pct`
- `positionManagement`: List of active management rules:
  - `trailing_stop` (activation_pct, callback_pct)
  - `move_to_breakeven` (trigger_pct, offset_pct)
  - `modify_take_profit` / `modify_stop_loss`
"""

    examples_doc = """## Example: EMA Trend + RSI Pullback Strategy (Valid JSON)
```json
{
  "name": "EMA_Trend_RSI_Reversal",
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "direction": "LONG",
  "filters": {
    "type": "AND",
    "children": [
      {
        "type": "trend_filter",
        "params": {
          "indicator": "ADX",
          "threshold": 20.0
        }
      }
    ]
  },
  "entryConditions": {
    "type": "AND",
    "children": [
      {
        "type": "value_comparison",
        "params": {
          "left_indicator": "RSI",
          "left_period": 14,
          "operator": "<=",
          "right_value": 35.0
        }
      },
      {
        "type": "value_comparison",
        "params": {
          "left_indicator": "EMA",
          "left_period": 20,
          "operator": ">",
          "right_indicator": "EMA",
          "right_period": 50
        }
      }
    ]
  },
  "entryTrigger": {
    "type": "on_candle_close",
    "params": {}
  },
  "initialization": {
    "type": "open_position",
    "params": {
      "side": "LONG",
      "position_size_type": "PERCENT_EQUITY",
      "position_size_value": 10.0,
      "stop_loss_pct": 1.5,
      "take_profit_pct": 3.0
    }
  },
  "positionManagement": [
    {
      "type": "trailing_stop",
      "params": {
        "activation_pct": 1.5,
        "callback_pct": 0.5
      }
    },
    {
      "type": "move_to_breakeven",
      "params": {
        "trigger_pct": 1.0,
        "offset_pct": 0.1
      }
    }
  ]
}
```
"""

    # Category handlers
    if category == "codebase":
        codebase = get_cached_codebase_context()
        sections = [
            f"## DepthSight Full Codebase Reference ({len(codebase)} blocks extracted from schemas & execution engine)"
        ]
        for k, code in sorted(codebase.items()):
            sections.append(f"### `{k}`\n```python\n{code}\n```")
        return "\n\n".join(sections)

    elif category == "indicators":
        codebase = get_cached_codebase_context()
        indicator_keys = [
            k
            for k in codebase.keys()
            if any(
                term in k.lower()
                for term in [
                    "condition",
                    "indicator",
                    "rsi",
                    "macd",
                    "stoch",
                    "bollinger",
                    "level",
                    "trend_direction",
                    "pattern",
                ]
            )
        ]
        sections = [
            f"## DepthSight Indicator & Condition Blocks ({len(indicator_keys)} blocks):"
        ]
        for k in sorted(indicator_keys):
            sections.append(f"### `{k}`\n```python\n{codebase[k]}\n```")
        return "\n\n".join(sections)

    elif category == "filters":
        codebase = get_cached_codebase_context()
        filter_keys = [
            k
            for k in codebase.keys()
            if any(
                term in k.lower()
                for term in [
                    "filter",
                    "session",
                    "btc_state",
                    "volatility",
                    "rel_vol",
                    "adx",
                    "natr",
                ]
            )
        ]
        sections = [f"## DepthSight Filter Blocks ({len(filter_keys)} blocks):"]
        for k in sorted(filter_keys):
            sections.append(f"### `{k}`\n```python\n{codebase[k]}\n```")
        return "\n\n".join(sections)

    elif category == "memory_guide":
        return MEMORY_GUIDE_DOC

    elif category in ("allowed_types", "schemas"):
        return ALLOWED_TYPES_DOC

    elif category == "examples":
        return examples_doc

    elif category == "blocks":
        return f"{blocks_doc}\n\n{ALLOWED_TYPES_DOC}"

    elif category == "all":
        codebase = get_cached_codebase_context()
        blocks_list = "\n".join(f"- `{k}`" for k in sorted(codebase.keys())[:15])
        return (
            f"{blocks_doc}\n\n"
            f"{ALLOWED_TYPES_DOC}\n\n"
            f"{examples_doc}\n\n"
            f"{MEMORY_GUIDE_DOC}\n\n"
            f"### Available Codebase Implementation Blocks ({len(codebase)} total):\n"
            f"{blocks_list}\n"
            f"... and {len(codebase) - 15} more. To view any block's code, call `get_strategy_schema_and_examples(block_name='<name>')`."
        )

    # Default: "summary"
    return f"{blocks_doc}\n\n{ALLOWED_TYPES_DOC}\n\n{examples_doc}"


async def tool_get_market_metrics(symbol: str) -> str:
    """Queries Screener API for live metrics for a symbol."""
    target_pair = symbol.strip().upper()
    if not target_pair.endswith("USDT"):
        target_pair += "USDT"

    screener_url = os.getenv("SCREENER_API_URL", "http://localhost:8050").rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{screener_url}/api/v1/metrics/{target_pair}")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                natr = data.get("natr", "N/A")
                trend = data.get("macro_trend", "N/A")
                oracle = data.get("oracle_regime", "N/A")
                vol = data.get("volume_24h", "N/A")
                oracle_text = (
                    "Flat / Consolidation"
                    if oracle == 0
                    else ("Impulse / Volatile" if oracle == 1 else str(oracle))
                )

                return (
                    f"### Live Market Metrics for {target_pair}\n"
                    f"- **Current Volatility (NATR)**: {natr}\n"
                    f"- **Macro Trend (1H vs 6H)**: {trend}\n"
                    f"- **ML Oracle Regime**: {oracle_text}\n"
                    f"- **24h Volume (USD)**: {vol}\n"
                    f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}"
                )
    except Exception as e:
        logger.warning(f"Screener request failed for {target_pair}: {e}")

    return (
        f"### Market Metrics for {target_pair} (Fallback)\n"
        f"- **Symbol**: {target_pair}\n"
        f"- **Status**: Screener offline or symbol not indexed\n"
        f"- **Recommendation**: Use standard volatility and trend filters in backtest."
    )


async def tool_run_backtest(
    symbol: str,
    strategy_config: dict,
    start_date: str,
    end_date: str,
    timeframe: str = "15m",
    engine: str = "vector",
    strategy_name: Optional[str] = None,
    user: Optional[models.User] = None,
    redis_client: Optional[Any] = None,
) -> str:
    """Executes a backtest through Celery with user plan limits and quota checks."""
    if user is None:
        raise ValueError("Authenticated user is required to run backtests.")

    from api.depthsight_api import (
        _check_symbol_permissions,
        _enforce_strategy_plan_restrictions,
        _enforce_backtest_engine_access,
        is_strategy_kline_only,
    )
    from api.dependencies import (
        check_concurrent_task_limit,
        check_usage_quota,
        increment_concurrent_task_counter,
        increment_usage_quota,
    )

    clean_symbol = symbol.strip().upper()
    await _check_symbol_permissions(user, [clean_symbol])

    # 1. Date duration limit check against user plan
    user_plan = plans_config.get_plan(user.plan)
    limits = user_plan.get("limits", {})
    max_days = limits.get("max_backtest_duration_days")

    try:
        start_dt = datetime.fromisoformat(start_date.replace("Z", ""))
        end_dt = datetime.fromisoformat(end_date.replace("Z", ""))
    except Exception as e:
        return f"Error: Invalid date format. Use YYYY-MM-DD. Details: {e}"

    duration_days = (end_dt - start_dt).days
    if duration_days <= 0:
        return "Error: end_date must be after start_date."

    if max_days is not None and max_days != -1 and duration_days > max_days:
        return (
            f"Error: Backtest duration ({duration_days} days) exceeds your plan limit of {max_days} days. "
            f"Please reduce the date range or upgrade your plan."
        )

    # 2. Block and engine restrictions
    try:
        _enforce_strategy_plan_restrictions(strategy_config, user)
        _enforce_backtest_engine_access(user, engine)
    except Exception as e:
        return f"Plan Restriction Error: {e}"

    # Check if strategy requires precision engine
    if is_strategy_kline_only(strategy_config) and engine == "vector":
        return (
            "Error: This strategy contains advanced blocks that require the 'precision' engine. "
            "Please specify engine='precision' (available on Pro plans)."
        )

    # 3. Quota and concurrency enforcement
    quota_feature = f"run_{engine}_backtest"
    if redis_client:
        try:
            concurrent_check = check_concurrent_task_limit("run_backtest")
            await concurrent_check(user, redis_client)
            usage_check = check_usage_quota(quota_feature)
            await usage_check(user, redis_client)
        except Exception as e:
            return f"Quota / Concurrency Limit Exceeded: {e}"

    # 4. Celery dispatch
    priority = limits.get("celery_task_priority", 9)
    run_name = strategy_name or strategy_config.get("name") or "VisualBuilderStrategy"

    backtest_payload = {
        "strategy_name": run_name,
        "symbol": clean_symbol,
        "start_date": start_date,
        "end_date": end_date,
        "timeframe": timeframe,
        "params": {
            "config": strategy_config,
            "backtest_engine": engine,
        },
    }

    try:
        celery_task = celery_app.send_task(
            "run_backtest_task",
            args=[backtest_payload, user.id],
            priority=priority,
        )

        if redis_client:
            await increment_concurrent_task_counter(user.id, redis_client)
            await increment_usage_quota(user.id, quota_feature, redis_client)

        logger.info(f"MCP User {user.username} queued backtest task {celery_task.id}")

        # 5. Wait for result asynchronously (up to 60 seconds)
        max_wait_seconds = 60
        waited = 0.0
        while not celery_task.ready() and waited < max_wait_seconds:
            await asyncio.sleep(0.5)
            waited += 0.5

        if not celery_task.ready():
            return (
                f"### Backtest Queued (Processing Asynchronously)\n"
                f"- **Task ID**: `{celery_task.id}`\n"
                f"- **Symbol**: {clean_symbol}\n"
                f"- **Engine**: {engine}\n"
                f"- **Status**: The simulation is running in the background. "
                f"Execution took longer than 60s. Results will be saved to your account."
            )

        task_result = celery_task.result
        if isinstance(task_result, Exception):
            raise task_result

        # Format KPI results
        result_data = (
            task_result.get(clean_symbol, {}) if isinstance(task_result, dict) else {}
        )
        pnl = result_data.get("total_pnl_pct", 0.0)
        win_rate = result_data.get("win_rate", 0.0)
        trades = result_data.get("trades", 0)
        max_dd = result_data.get("max_drawdown", 0.0)
        sharpe = result_data.get("sharpe_ratio", 0.0)
        profit_factor = result_data.get("profit_factor", 0.0)

        status_emoji = "✅" if pnl > 0 else "⚠️"
        return (
            f"### {status_emoji} Backtest Results: {clean_symbol} ({timeframe})\n"
            f"- **Strategy**: {run_name}\n"
            f"- **Period**: {start_date} to {end_date} ({duration_days} days)\n"
            f"- **Engine**: {engine.upper()}\n"
            f"- **Total Return (PnL)**: **{pnl:+.2f}%**\n"
            f"- **Win Rate**: **{win_rate:.1f}%**\n"
            f"- **Total Trades**: {trades}\n"
            f"- **Max Drawdown**: {max_dd:.2f}%\n"
            f"- **Profit Factor**: {profit_factor:.2f}\n"
            f"- **Sharpe Ratio**: {sharpe:.2f}\n"
            f"- **Task ID**: `{celery_task.id}`\n\n"
            f"**Recommendation**: If this strategy demonstrates strong risk-adjusted returns, "
            f"consider saving it using `save_strategy` or recording insights with `store_agent_memory`."
        )

    except Exception as e:
        logger.error(f"MCP Backtest error for user {user.id}: {e}", exc_info=True)
        return f"Backtest execution failed: {str(e)}"


async def tool_list_strategies(user: models.User, db: AsyncSession) -> str:
    """Lists saved strategies for the authenticated user."""
    configs = await crud.get_strategy_configs_by_user(db, user_id=user.id)
    if not configs:
        return "No saved strategies found in your DepthSight account."

    lines = [f"### Saved Strategies ({len(configs)} total):"]
    for c in configs:
        cfg = c.config_data if isinstance(c.config_data, dict) else {}
        sym = (c.symbols[0] if c.symbols else None) or cfg.get("symbol") or "N/A"
        timeframe = cfg.get("timeframe") or "N/A"
        created = c.created_at.strftime("%Y-%m-%d") if c.created_at else "Unknown"
        lines.append(
            f"- **{c.name}** (ID: `{c.id}`) | Symbol: `{sym}` | TF: `{timeframe}` | Created: {created}"
        )

    return "\n".join(lines)


async def tool_get_strategy(config_id: str, user: models.User, db: AsyncSession) -> str:
    """Fetches details for a single saved strategy."""
    config = await crud.get_strategy_config(db, user_id=user.id, config_id=config_id)
    if not config:
        return f"Error: Strategy with ID '{config_id}' not found in your account."

    cfg = config.config_data if isinstance(config.config_data, dict) else {}
    sym = (config.symbols[0] if config.symbols else None) or cfg.get("symbol") or "N/A"
    timeframe = cfg.get("timeframe") or "N/A"

    return (
        f"### Strategy: {config.name}\n"
        f"- **ID**: `{config.id}`\n"
        f"- **Symbol**: `{sym}`\n"
        f"- **Timeframe**: `{timeframe}`\n"
        f"- **Description**: {config.description or 'None'}\n\n"
        f"```json\n{json.dumps(config.config_data, indent=2)}\n```"
    )


async def tool_save_strategy(
    name: str,
    strategy_config: dict,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    description: Optional[str] = None,
    user: Optional[models.User] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Validates and saves a new strategy to the user's account."""
    if user is None or db is None:
        return "Error: Database session and authenticated user required."

    from api.depthsight_api import (
        _coerce_strategy_config_dict,
        _enforce_strategy_plan_restrictions,
    )

    try:
        clean_config = _coerce_strategy_config_dict(strategy_config, "new")
        _enforce_strategy_plan_restrictions(clean_config, user)

        detected_symbol = symbol or strategy_config.get("symbol") or "BTCUSDT"
        detected_tf = timeframe or strategy_config.get("timeframe") or "15m"
        clean_config["symbol"] = detected_symbol
        clean_config["timeframe"] = detected_tf

        create_schema = schemas.StrategyConfigCreate(
            name=name.strip(),
            config_data=clean_config,
            symbols=[detected_symbol] if detected_symbol else None,
            description=description,
        )

        saved = await crud.create_strategy_config(
            db=db, user_id=user.id, config_create=create_schema
        )
        await db.commit()
        await db.refresh(saved)

        return (
            f"✅ Strategy **{saved.name}** successfully saved!\n"
            f"- **Config ID**: `{saved.id}`\n"
            f"- **Symbol**: `{detected_symbol}`\n"
            f"- **Timeframe**: `{detected_tf}`\n"
            f"You can now run backtests with this configuration or deploy it in live/paper trading."
        )
    except Exception as e:
        logger.error(f"MCP save_strategy error for user {user.id}: {e}", exc_info=True)
        return f"Error saving strategy: {str(e)}"


async def tool_search_agent_memory(
    user: models.User,
    db: AsyncSession,
    tags: Optional[List[str]] = None,
    symbol: Optional[str] = None,
    strategy_type: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Cascading search through user's persistent agent memory."""
    memories = await crud.search_agent_memories(
        db=db,
        user_id=user.id,
        tags=tags,
        symbol=symbol,
        strategy_type=strategy_type,
        limit=min(limit, 25),
    )

    if not memories:
        return "No agent memories or rules matched your criteria."

    lines = [f"### Agent Knowledge & Historical Insights ({len(memories)} found):"]
    for m in memories:
        outcome_tag = f"[{m.outcome.upper()}]" if m.outcome else ""
        tags_str = f"Tags: {', '.join(m.tags)}" if m.tags else ""
        lines.append(
            f"\n#### {outcome_tag} {m.strategy_type or 'Insight'} ({m.symbol or 'General'})"
        )
        if tags_str:
            lines.append(f"*{tags_str}*")
        lines.append(f"{m.content}")

    return "\n".join(lines)


async def tool_store_agent_memory(
    content: str,
    strategy_type: str,
    tags: List[str],
    outcome: str,
    confidence: float = 0.85,
    symbol: Optional[str] = None,
    user: Optional[models.User] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Stores an explicit insight or rule into the user's agent memory."""
    if user is None or db is None:
        return "Error: Database session and authenticated user required."

    memory_data = schemas.AgentMemoryCreate(
        content=content.strip(),
        strategy_type=strategy_type.strip().lower(),
        tags=[t.strip().lower() for t in tags],
        outcome=outcome.strip().lower(),
        confidence=max(0.1, min(1.0, confidence)),
        symbol=symbol.strip().upper() if symbol else None,
        memory_type="strategy_insight",
        relevance_score=1.0,
    )

    saved = await crud.create_agent_memory(
        db=db, user_id=user.id, memory_data=memory_data
    )
    await db.commit()

    return (
        f"✅ Insight saved to persistent memory bank!\n"
        f"- **ID**: `{saved.id}`\n"
        f"- **Category**: {saved.strategy_type}\n"
        f"- **Outcome**: {saved.outcome}\n"
        f"- **Tags**: {', '.join(saved.tags or [])}\n"
        f"This knowledge will be used by DepthSight agents during subsequent strategy generations."
    )


async def tool_get_bot_status(
    mode: str = "all",
    user: Optional[models.User] = None,
    redis_client: Optional[Any] = None,
) -> str:
    """Fetches currently active live and paper trading bots from Redis."""
    if user is None or redis_client is None:
        return "Error: Redis client and user required."

    redis_key_strategies = os.environ.get(
        "REDIS_STATE_KEY_STRATEGIES", "depthsight:state:strategies"
    )
    base_key = f"{redis_key_strategies}:{user.id}"
    bots = []

    try:
        keys = await redis_client.keys(f"{base_key}:*")
        if keys:
            values = await redis_client.mget(keys)
            for v in values:
                if v:
                    bots.extend(json.loads(v))

        if mode != "all":
            bots = [b for b in bots if b.get("mode") == mode]

        if not bots:
            return f"No active trading bots currently running in mode: '{mode}'."

        lines = [f"### Active Trading Bots ({len(bots)} total):"]
        for b in bots:
            s_name = b.get("strategy_name", "Unknown")
            sym = b.get("symbol", "N/A")
            b_mode = b.get("mode", "paper").upper()
            state = b.get("state", "RUNNING")
            tf = b.get("candle_timeframe", b.get("timeframe", "N/A"))
            lines.append(
                f"- **{s_name}** | Symbol: `{sym}` | TF: `{tf}` | Mode: `{b_mode}` | State: `{state}`"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error reading bot status from Redis: {e}")
        return f"Error querying bot status: {str(e)}"


async def tool_get_open_positions(
    mode: str = "all",
    symbol: Optional[str] = None,
    user: Optional[models.User] = None,
    redis_client: Optional[Any] = None,
) -> str:
    """Fetches active trading positions for the authenticated user from Redis."""
    if user is None or redis_client is None:
        return "Error: Redis client and user required."

    redis_key_positions = os.environ.get(
        "REDIS_STATE_KEY_POSITIONS", "depthsight:state:positions"
    )
    base_key = f"{redis_key_positions}:{user.id}"
    positions = []

    try:
        keys = await redis_client.keys(f"{base_key}:*")
        if keys:
            values = await redis_client.mget(keys)
            for v in values:
                if v:
                    positions.extend(json.loads(v))

        # Filter by user_id
        positions = [p for p in positions if str(p.get("user_id")) == str(user.id)]

        if mode != "all":
            positions = [
                p for p in positions if p.get("mode", "").lower() == mode.lower()
            ]

        if symbol:
            clean_sym = symbol.strip().upper()
            positions = [p for p in positions if p.get("symbol") == clean_sym]

        if not positions:
            filter_desc = (
                f" for symbol '{symbol}'"
                if symbol
                else (f" in mode '{mode}'" if mode != "all" else "")
            )
            return f"No open positions currently active{filter_desc}."

        lines = [f"### Open Positions ({len(positions)} active):"]
        for p in positions:
            sym = p.get("symbol", "N/A")
            side = p.get("side", p.get("direction", "LONG")).upper()
            qty = p.get("amount", p.get("size", p.get("quantity", 0.0)))
            entry = p.get("entry_price", 0.0)
            mark = p.get("current_price", p.get("mark_price", entry))
            unrealized_pnl = p.get("unrealized_pnl", 0.0)
            pnl_pct = p.get("unrealized_pnl_pct", p.get("pnl_percent", 0.0))
            sl = p.get("stop_loss", p.get("sl_price", "N/A"))
            tp = p.get("take_profit", p.get("tp_price", "N/A"))
            p_mode = p.get("mode", "paper").upper()
            strat = p.get("strategy_name", "VisualBuilder")

            pnl_icon = "🟢" if unrealized_pnl >= 0 else "🔴"
            lines.append(
                f"\n#### {pnl_icon} {sym} ({side}) — {p_mode}\n"
                f"- **Strategy**: {strat}\n"
                f"- **Size**: {qty} | **Entry**: ${entry:,.4f} | **Mark**: ${mark:,.4f}\n"
                f"- **Unrealized PnL**: ${unrealized_pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
                f"- **Risk Management**: SL: `{sl}` | TP: `{tp}`"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error reading open positions from Redis: {e}")
        return f"Error querying open positions: {str(e)}"


async def tool_get_trading_analytics(
    mode: str = "live",
    symbol: Optional[str] = None,
    limit: int = 50,
    user: Optional[models.User] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Analyzes real/paper closed trade history and generates quantitative performance metrics."""
    if user is None or db is None:
        return "Error: Database session and user required."

    limit = max(5, min(200, limit))
    clean_symbol = symbol.strip().upper() if symbol else None
    trade_mode = mode.strip().upper()

    trades, total_count = await crud.get_trades_with_count(
        db=db,
        user_id=user.id,
        limit=limit,
        symbol=clean_symbol,
        trade_mode=trade_mode,
    )

    if not trades or total_count == 0:
        sym_desc = f" for symbol {clean_symbol}" if clean_symbol else ""
        return (
            f"No trade history found in '{mode}' mode{sym_desc}. "
            f"Start bots or run backtests to generate trade performance data."
        )

    # Calculate KPIs
    winning_trades = [t for t in trades if (t.pnl or 0.0) > 0]
    losing_trades = [t for t in trades if (t.pnl or 0.0) < 0]
    total_pnl = sum(t.pnl or 0.0 for t in trades)
    total_fees = sum(t.commission or 0.0 for t in trades)
    net_pnl = total_pnl - total_fees
    gross_profit = sum(t.pnl for t in winning_trades)
    gross_loss = abs(sum(t.pnl for t in losing_trades))

    win_rate = (len(winning_trades) / len(trades) * 100) if trades else 0.0
    profit_factor = (
        (gross_profit / gross_loss)
        if gross_loss > 0
        else (gross_profit if gross_profit > 0 else 1.0)
    )
    avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0.0
    avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0.0

    # Sort best and worst trades
    sorted_by_pnl = sorted(trades, key=lambda t: t.pnl or 0.0, reverse=True)
    best_trades = sorted_by_pnl[:3]
    worst_trades = sorted_by_pnl[-3:] if len(sorted_by_pnl) >= 3 else []
    worst_trades = [t for t in worst_trades if (t.pnl or 0.0) < 0]

    # Time-based toxicity check: group by hour
    hour_pnl = defaultdict(float)
    for t in trades:
        if t.timestamp_close:
            hour = t.timestamp_close.hour
            hour_pnl[hour] += t.pnl or 0.0

    unprofitable_hours = [
        f"{h:02d}:00 UTC (${pnl:,.2f})"
        for h, pnl in sorted(hour_pnl.items())
        if pnl < 0
    ]

    lines = [
        f"### Trading Performance Analytics ({trade_mode} Mode)\n",
        f"- **Total Closed Trades**: {len(trades)} (out of {total_count} total in history)",
        f"- **Net PnL**: ${net_pnl:+,.2f} (Gross PnL: ${total_pnl:+,.2f} | Fees: ${total_fees:,.2f})",
        f"- **Win Rate**: {win_rate:.1f}% ({len(winning_trades)}W / {len(losing_trades)}L)",
        f"- **Profit Factor**: {profit_factor:.2f}",
        f"- **Avg Win**: +${avg_win:,.2f} | **Avg Loss**: -${avg_loss:,.2f}",
    ]

    if best_trades:
        lines.append("\n#### Top Winning Trades:")
        for t in best_trades:
            close_str = (
                t.timestamp_close.strftime("%Y-%m-%d %H:%M")
                if t.timestamp_close
                else "N/A"
            )
            lines.append(
                f"- **{t.symbol}** ({t.direction or 'LONG'}): +${(t.pnl or 0.0):,.2f} | Exit: `{t.exit_reason or 'TP'}` | Closed: {close_str}"
            )

    if worst_trades:
        lines.append("\n#### Top Losing Trades:")
        for t in reversed(worst_trades):
            close_str = (
                t.timestamp_close.strftime("%Y-%m-%d %H:%M")
                if t.timestamp_close
                else "N/A"
            )
            lines.append(
                f"- **{t.symbol}** ({t.direction or 'LONG'}): -${abs(t.pnl or 0.0):,.2f} | Exit: `{t.exit_reason or 'SL'}` | Closed: {close_str}"
            )

    if unprofitable_hours:
        lines.append(
            "\n#### ⚠️ Toxic / Unprofitable Trading Hours (UTC):\n"
            + ", ".join(unprofitable_hours[:5])
            + "\n*Tip: Consider using the `trading_session` filter to restrict bot execution during these hours.*"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Master Tool Dispatcher
# ---------------------------------------------------------------------------


async def execute_tool(
    name: str,
    arguments: Dict[str, Any],
    user: models.User,
    db: AsyncSession,
    redis_client: Optional[Any] = None,
) -> str:
    """Routes an MCP tool call to its corresponding implementation."""
    arguments = arguments or {}

    if name == "get_strategy_schema_and_examples":
        return await tool_get_strategy_schema_and_examples(
            category=arguments.get("category", "summary"),
            block_name=arguments.get("block_name"),
        )

    elif name == "get_market_metrics":
        if "symbol" not in arguments:
            return "Error: 'symbol' argument is required."
        return await tool_get_market_metrics(symbol=arguments["symbol"])

    elif name == "run_backtest":
        return await tool_run_backtest(
            symbol=arguments.get("symbol", ""),
            strategy_config=arguments.get("strategy_config", {}),
            start_date=arguments.get("start_date", ""),
            end_date=arguments.get("end_date", ""),
            timeframe=arguments.get("timeframe", "15m"),
            engine=arguments.get("engine", "vector"),
            strategy_name=arguments.get("strategy_name"),
            user=user,
            redis_client=redis_client,
        )

    elif name == "list_strategies":
        return await tool_list_strategies(user=user, db=db)

    elif name == "get_strategy":
        if "config_id" not in arguments:
            return "Error: 'config_id' argument is required."
        return await tool_get_strategy(
            config_id=arguments["config_id"], user=user, db=db
        )

    elif name == "save_strategy":
        if "name" not in arguments or "strategy_config" not in arguments:
            return "Error: Both 'name' and 'strategy_config' arguments are required."
        return await tool_save_strategy(
            name=arguments["name"],
            strategy_config=arguments["strategy_config"],
            symbol=arguments.get("symbol"),
            timeframe=arguments.get("timeframe"),
            description=arguments.get("description"),
            user=user,
            db=db,
        )

    elif name == "search_agent_memory":
        return await tool_search_agent_memory(
            user=user,
            db=db,
            tags=arguments.get("tags"),
            symbol=arguments.get("symbol"),
            strategy_type=arguments.get("strategy_type"),
            limit=arguments.get("limit", 10),
        )

    elif name == "store_agent_memory":
        for req in ["content", "strategy_type", "tags", "outcome"]:
            if req not in arguments:
                return f"Error: Missing required argument '{req}'."
        return await tool_store_agent_memory(
            content=arguments["content"],
            strategy_type=arguments["strategy_type"],
            tags=arguments["tags"],
            outcome=arguments["outcome"],
            confidence=arguments.get("confidence", 0.85),
            symbol=arguments.get("symbol"),
            user=user,
            db=db,
        )

    elif name == "get_bot_status":
        return await tool_get_bot_status(
            mode=arguments.get("mode", "all"),
            user=user,
            redis_client=redis_client,
        )

    elif name == "get_open_positions":
        return await tool_get_open_positions(
            mode=arguments.get("mode", "all"),
            symbol=arguments.get("symbol"),
            user=user,
            redis_client=redis_client,
        )

    elif name == "get_trading_analytics":
        return await tool_get_trading_analytics(
            mode=arguments.get("mode", "live"),
            symbol=arguments.get("symbol"),
            limit=arguments.get("limit", 50),
            user=user,
            db=db,
        )

    else:
        raise ValueError(f"Unknown tool: {name}")
