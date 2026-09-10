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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        name="get_historical_data_range",
        description=(
            "Queries available market symbols with loaded historical data in DepthSight, "
            "including exact start/end date intervals, available candle timeframes, and microstructural data "
            "(bookDepth aggregated percentage depth buckets, open interest, 1s tick trades). "
            "NOTE: DepthSight orderbook data is 'bookDepth' (Binance Futures aggregated percentage buckets: "
            "±0.2%, ±1.0%, ±2.0%, ±3.0%, ±4.0%, ±5.0% bids/asks depth and notional volume), NOT tick-level L2 ladder. "
            "ALWAYS call this before running backtests to ensure your target symbol and dates exist in storage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair symbol (e.g. 'BTCUSDT'). If provided, returns exact date range and timeframe coverage for this pair. If omitted, lists all available pairs.",
                }
            },
            "required": [],
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
                "strategy_type": {
                    "type": "string",
                    "enum": [
                        "breakout",
                        "mean_reversion",
                        "trend_following",
                        "scalping",
                        "momentum",
                    ],
                    "description": (
                        "Strategy archetype: 'breakout', 'mean_reversion', 'trend_following', 'scalping', or 'momentum'. "
                        "Directly categorizes the insight in the Memory Bank without requiring an external LLM classification call."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "1 to 4 concise snake_case tags characterizing indicators and setup (e.g. ['breakout', 'volatility_squeeze', 'adx']). "
                        "Prefer selecting existing database tags returned by search_agent_memory to keep vocabulary unified across sessions. "
                        "Do NOT include the asset symbol in tags (symbol has its own dedicated column)."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "MANDATORY: Structured rationale for this backtest variant. "
                        "Format with concise bullets: Context (asset, TF), Setup (thesis and why these blocks/parameters were chosen), "
                        "Success Factors (expected edge/triggers), and Rule for Future. "
                        "DepthSight uses this reasoning to automatically synthesize learned rules in the user's memory bank."
                    ),
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
                    "description": "1 to 4 concise snake_case tags. Prefer choosing from the existing database tags returned by search_agent_memory to keep vocabulary unified across agent sessions. Only create a new tag if none fit.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Optional trading pair in UPPERCASE (e.g. 'BTCUSDT'). Do NOT include pair names inside the tags list.",
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
_MCP_SESSION_STATE: Dict[str, dict] = {}

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


ALLOWED_TYPES_DOC = """# DepthSight Visual Builder Strict Type Checklist & Parameter Schemas

**ABSOLUTELY CRITICAL**: You MUST use ONLY these exact type values in your JSON configurations.
Do NOT invent new types. Do NOT use similar-sounding names.

## Filters (use in `filters` section):
- `rel_vol_filter`: relative volume threshold
  `{"rel_vol_threshold": 1.5, "lookback_period": 20}`
- `trend_filter`: ADX threshold + direction
  `{"indicator": "ADX", "threshold": 25.0}`
- `volatility_filter`: ATR threshold
  `{"natr_threshold": 1.0}`
- `trading_session`: session hours (UTC)
  `{"sessions": ["london", "new_york"], "timezone": "UTC"}`
- `btc_state_filter` (PRO only): BTC market regime ("Consolidation", "Trending Up", "Trending Down", "Any")
- `correlation` (PRO only): correlation against BTC/ETH
- `senior_tf_confluence` (PRO only): higher timeframe indicator alignment

## Foundations & Decision Blocks (use in `entryConditions` section):
### Data Providers:
- `local_level`: high/low swing levels
  `{"timeframe": "15m", "lookback_period": 20, "level_type": "high", "is_data_provider": true, "proximity_type": "atr_multiplier", "proximity_value": 1.5}`
- `significant_level`: key daily/weekly support/resistance zones
  `{}` (no params needed; outputs detected_level)
- `tape_analysis` (PRO only / Precision): aggressive buyer/seller delta flow
- `order_book_zone` (PRO only / Precision): orderbook depth ratio and wall detection using bookDepth percentage buckets

### Decision Blocks:
- `value_comparison`: compare indicators (RSI, EMA, MACD, Stochastic, Bollinger Bands, ATR)
  Example: `{"leftOperand": {"source": "indicator", "key": "RSI_14"}, "operator": "lt", "rightOperand": {"source": "value", "value": 30.0}}`
- `trend_direction`: EMA fast vs slow slope
  `{"timeframe": "15m", "required_trend": "LONG", "fast_period": 10, "slow_period": 50, "rsi_period": 14, "rsi_lower_bound": 40, "rsi_upper_bound": 60}`
- `volume_confirmation`: volume spikes vs average
  `{"multiplier": 1.5, "lookback_period": 20}`
- `classic_pattern`: candlestick patterns (engulfing, pinbar, breakout)
  `{"pattern_type": "engulfing", "lookback": 3}`
- `price_consolidation`: channel/range breakout
  `{"lookback_period": 20, "max_range_atr": 0.5}`
- `volatility_squeeze`: Bollinger Bands squeeze inside Keltner Channels
  `{"lookback_candles": 20, "squeeze_ratio": 0.6}`
- `price_action_analyzer`: multi-candle geometric structure (e.g. higher lows)
  `{"structure_type": "higher_lows", "lookback_candles": 30, "min_points": 2, "order": 3}`
- `return_to_level`: retest of broken level
  `{"level_block_id": "resistance_level_1", "retest_type": "breakout_retest", "approach_direction": "from_below", "proximity_type": "atr_multiplier", "proximity_value": 1.5, "departure_type": "atr_multiplier", "departure_value": 3.0, "confirmation_time_sec": 60, "cooldown_sec": 300}`
- `level_touch_analyzer`: number of level touches without piercing
  `{"level_source": {"source": "block_result", "block_id": "resistance_level_1", "key": "detected_level"}, "lookback_candles": 50, "touch_tolerance_pct": 0.1, "invalidate_on_pierce": true, "min_touches": 3}`
- `round_level`: psychological round price levels
  `{"proximity_pct": 0.1}`
- `open_interest` (PRO only): OI surge / liquidation traps
- `order_book_zone_condition` (PRO only): order book liquidity wall detection using bookDepth percentage buckets
- `tape_condition` (PRO only): aggressive tape delta
- `l2_microstructure` / `orderbook_imbalance` (PRO only): depth imbalance calculated from bookDepth buckets

### DepthSight Orderbook Format Note (bookDepth):
Orderbook data in DepthSight is **bookDepth**, NOT raw tick-level L2 orderbook ladder.
Binance Futures `bookDepth` provides periodic snapshots of cumulative volume and notional USD at fixed percentage offsets:
- Bids: `depth_m0.2` (-0.2%), `depth_m1.0` (-1%), `depth_m2.0` (-2%), `depth_m3.0` (-3%), `depth_m4.0` (-4%), `depth_m5.0` (-5%) and `notional_m0.2`..`notional_m5.0`.
- Asks: `depth_p0.2` (+0.2%), `depth_p1.0` (+1%), `depth_p2.0` (+2%), `depth_p3.0` (+3%), `depth_p4.0` (+4%), `depth_p5.0` (+5%) and `notional_p0.2`..`notional_p5.0`.
Blocks like `order_book_zone` and `orderbook_imbalance` operate on these percentage buckets. Do NOT attempt to query tick-level order queues.

## Actions & Triggers:
- `open_position` (use in `initialization` only):
  `{"direction": "LONG", "risk_type": "percent_balance", "risk_value": 1.0, "sl_type": "atr_multiplier", "sl_value": 2.0, "tp_type": "rr_multiplier", "tp_value": 4.0, "partial_exits": [{"tp_type": "rr_multiplier", "tp_value": 1.5, "size_pct": 30.0}, {"tp_type": "rr_multiplier", "tp_value": 3.0, "size_pct": 70.0}]}`
- `on_candle_close` (use in `entryTrigger` only)
- `on_tick` (use in `entryTrigger` only)
- `on_condition_met` (use in `entryTrigger` only)

## Position Management (use in `positionManagement` section):
- `move_to_breakeven`: `{"target_type": "rr_multiplier", "target_value": 1.0, "offset_pips": 2}`
- `scale_in`: `{"add_size_pct_of_initial_risk": 100.0, "max_entries": 3}`
- `dca_management`: `{"max_safety_orders": 5, "volume_multiplier": 2.0, "step_type": "percentage", "step_value": 1.0, "step_multiplier": 1.0}`
- `grid_management`: `{"grid_levels": 10, "range_type": "percentage", "upper_bound": 1.0, "lower_bound": 1.0}`
- `modify_stop_loss`: `{"new_sl_price": {"source": "value", "value": 1850.5}}`
- `modify_take_profit`: `{"new_tp_price": {"source": "value", "value": 1950.0}}`
- `close_position`: `{}`
- `conditional_management`: `{"if_conditions": {"type": "AND", "children": []}, "then_actions": []}`
- `trailing_stop` (PRO only / Precision): `{"activation_pct": 1.5, "callback_pct": 0.5}`
- `conditional_exit` (PRO only): dynamic condition-based exit

## Logic Containers:
- `AND`: all child conditions must be true
- `OR`: at least one child condition must be true
"""

MEMORY_GUIDE_DOC = """# DepthSight Agent Memory & Quant Protocol Guide

## 1. The Core Quant Development Loop
Every autonomous trading agent operating on DepthSight must follow this 6-step loop:
1. **Search Experience**: Call `search_agent_memory(symbol=..., strategy_type=...)` before formulating any strategy. Check what setups have previously failed or succeeded on this asset and inspect existing database tags.
2. **Inspect Market Regime**: Call `get_market_metrics(symbol=...)` to check current NATR volatility, 1H vs 6H macro trend, and ML Oracle regime (Flat vs Impulse).
3. **Verify Schemas**: Call `get_strategy_schema_and_examples(block_name=...)` to inspect exact Python parameters and allowed block types.
4. **Validate Performance**: Run simulations via `run_backtest(symbol=..., strategy_config=...)`. Evaluate PnL%, Win Rate%, Profit Factor, and Max Drawdown%.
5. **Formulate & Persist Rules**: Extract actionable findings and store them in persistent memory via `store_agent_memory(...)`.
6. **Deploy Strategy**: If backtest KPIs meet criteria (Win Rate > 55%, Profit Factor > 1.4, Drawdown < 15%), persist the strategy using `save_strategy(...)`.

## 2. Strategy Architecture & Reasoning Standard
- **Multi-block synergy**: Avoid testing random single-indicator strategies. A production strategy combines market context/filters, entry conditions/patterns, and clear position management.
- **Mandatory `reasoning` field**: Every strategy JSON must include a structured `reasoning` string inside `config_data` (or at root):
  - **Context:** [target asset, timeframe, and market condition]
  - **Setup:** [core thesis, pattern or trigger rationale]
  - **Success Factors:** [what confirms the edge: volume, volatility, level touch]
  - **Rule for Future:** [actionable rule synthesized for future iterations]

## 3. Evolutionary Optimization & Backtracking
- **Baseline + Mutation**: Do NOT start from scratch every iteration. Establish a baseline configuration.
- **Single-knob Mutation**: When optimizing, mutate ONLY ONE parameter at a time (e.g. lookback period from 14 to 21, volume threshold from 1.5 to 2.0, or adding a specific filter).
- **Backtrack on Degradation**: If mutation degrades performance (PnL decreases or Drawdown spikes), immediately discard the mutated variant, revert to the previous best baseline, and try an alternative mutation.

## 4. Rule Synthesis & Deduplication (CRITICAL)
When calling `store_agent_memory`, synthesize **high-confidence, actionable rules** for future strategy generations:
- Focus on specific indicators, filters, or parameters.
- **Actionable Rule Format**:
  `[Market Condition / Context] -> [Actionable Parameter / Filter Rule] to prevent [Failure Mode] / capture [Opportunity]`
  - *Example 1 (Failure Prevention)*: "For breakout setups on 15m BTCUSDT, always require `trend_filter` (ADX > 25) and volume confirmation multiplier > 1.8x to eliminate fakeouts in consolidation."
  - *Example 2 (Edge Capture)*: "In high volatility (NATR > 0.015), RSI oversold dips (RSI <= 28) paired with `trailing_stop` (activation 1.5%, callback 0.4%) achieve 68% win rate on ETHUSDT."
- **Deduplication Rule**: Compare your proposed insight with existing rules returned by `search_agent_memory`. If a rule with a similar concept, indicator parameter, or trade filter already exists, **DO NOT** create a duplicate.

## 5. Classification & Tagging Conventions (From tag_insight.md)
- **Select from Existing Tag Pool First**: Inspect the active database tags returned by `search_agent_memory` or displayed in the session. Pick 1 to 4 appropriate tags from the pool to keep vocabulary unified across agent sessions.
- **Create New Tags Sparingly**: Only if no existing tag accurately describes the concept, create a concise new `snake_case` tag (e.g. `volatility_squeeze`, `retest_level`, `pinbar`).
- **Never Put Tickers in Tags**: Always pass the trading pair in the dedicated `symbol` field in UPPERCASE (e.g. `symbol='BTCUSDT'`).
- **strategy_type**: Must be one of:
  - `"breakout"` (channel/level breaks)
  - `"mean_reversion"` (RSI/Bollinger/Stochastic counter-trend pullbacks)
  - `"trend_following"` (EMA/MACD/ADX trend continuation)
  - `"scalping"` (quick momentum/orderbook/tape scalps)
  - `"momentum"` (impulse/volume spikes)
- **outcome**:
  - `"success"`: strategy demonstrated robust profitability.
  - `"failure"`: strategy suffered negative return or toxic trade clusters.
  - `"neutral"`: mixed results or inconclusive tests.
"""


def get_formatted_codebase_reference() -> str:
    """Formats cached codebase blocks with python syntax highlighting."""
    codebase = get_cached_codebase_context()
    if not codebase:
        return "# No codebase context available."
    sections = []
    for k, code in sorted(codebase.items()):
        sections.append(f"### From: `{k}`\n```python\n{code}\n```")
    return "\n\n".join(sections)


def get_autopilot_generator_prompt() -> str:
    """Loads the authentic platform autopilot system prompt and generator prompt (Vector engine)
    and populates them with complete codebase reference blocks, working JSON examples, and engine architectural rules.
    """
    prompts_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "prompts")
    )
    system_prompt_path = os.path.join(prompts_dir, "autopilot_system.md")
    generator_prompt_path = os.path.join(prompts_dir, "autopilot_generator_system.md")

    codebase_ref = get_formatted_codebase_reference()

    autopilot_system_content = ""
    if os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                autopilot_system_content = f.read().replace(
                    "{resolved_symbol}", "ADAUSDT"
                )
        except Exception as e:
            logger.error(f"Failed to read autopilot_system.md: {e}")

    generator_content = ""
    if os.path.exists(generator_prompt_path):
        try:
            with open(generator_prompt_path, "r", encoding="utf-8") as f:
                generator_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read autopilot_generator_system.md: {e}")

    if "{codebase_reference}" in generator_content:
        generator_content = generator_content.replace(
            "{codebase_reference}", codebase_ref
        )
    else:
        generator_content += (
            f"\n\n<codebase_reference>\n{codebase_ref}\n</codebase_reference>"
        )

    mcp_operational_rules = """
# ==================================================
# CRITICAL ARCHITECTURAL RULES FOR DEPTHSIGHT ENGINE
# ==================================================

1. **STRICT SINGLE DIRECTION PER RUN (LONG OR SHORT)**:
   - In DepthSight, every Visual Builder strategy execution is UNIDIRECTIONAL.
   - `initialization.params.direction` MUST be strictly set to `"LONG"` or `"SHORT"`.
   - The vector backtester runs ONLY the direction specified in `initialization.params.direction`.
   - **NEVER create conflicting branches**: do NOT combine both LONG and SHORT logic into a single strategy configuration. If `direction="LONG"`, all SHORT entry conditions are completely ignored by the engine. To test both, run a LONG strategy backtest, then a separate SHORT strategy backtest.

2. **THE 4-STAGE PIPELINE ARCHITECTURE**:
   - **Stage 1 (`filters`)**: Global market state gates (`volatility_filter`, `trend_filter`, `rel_vol_filter`, `trading_session`). If conditions are not met, the candle is skipped before evaluating entries.
   - **Stage 2 (`entryConditions` & `entryTrigger`)**: Setup triggers (`on_candle_close`). Keep entry conditions concise (1 clean foundation block or synergy of 2-3 blocks).
   - **Stage 3 (`initialization`)**: `open_position` with `direction` ("LONG" or "SHORT"), `risk_type`, `risk_value`, `sl_type`, `tp_type`, and `partial_exits`.
   - **Stage 4 (`positionManagement`)**: Active in-trade blocks (`move_to_breakeven`, `scale_in`). Do NOT leave empty if you want breakeven or trailing protection!

3. **NEVER DUPLICATE LOOKBACK PERIODS (ANTI-SPAGHETTI RULE)**:
   - **DO NOT** create 10-14 duplicate `AND` blocks testing 5d, 10d, 14d, 20d, 30d lookback levels. This is a severe anti-pattern (overfitting/conflicting signals).
   - Use ONE clean level provider (e.g. `significant_level` or `local_level` with `is_data_provider: true`) paired with volume/consolidation confirmation.

4. **TRADE FREQUENCY & SAMPLE SIZE (HOW TO GET >= 50 TRADES)**:
   - Proving edge on 1m requires statistical validity (>= 50 trades).
   - Multi-week extremes (e.g. 20-day High on 1d timeframe) happen only ~10-15 times in 2 years! Do NOT use them when high trade frequency is needed.
   - To achieve >= 50 trades on 1m:
     - Use `significant_level` (intraday swing highs/lows)
     - Use `local_level` on 4h / 1d with shorter lookback (e.g. 24h to 3 days)
     - Use `return_to_level` (pullback and retest entries)
     - Use `volatility_squeeze` + `volume_confirmation`

5. **COMPLETE BREAKOUT STRATEGY EXAMPLE (COPY-PASTE READY)**:
```json
{
  "name": "ADAUSDT_1m_Clean_Breakout",
  "symbol": "ADAUSDT",
  "timeframe": "1m",
  "start_date": "2025-01-01",
  "end_date": "2026-08-31",
  "marketType": "FUTURES",
  "signal_source": "internal",
  "reasoning": "Context: ADAUSDT 1m breakout of swing resistance. Setup: 1m candle close above significant intraday level with volume confirmation and pre-breakout consolidation. Success factors: Relative volume > 1.5x, consolidation range <= 0.8 ATR. Rule for Future: Move to BE at 1.5 R:R, take partial profits at 1.5, 3.0, and 5.0 R:R.",
  "min_foundation_weight_threshold": 50.0,
  "foundation_weights": {
    "foundation_breakout": 50.0
  },
  "filters": {
    "type": "AND",
    "children": [
      {
        "type": "volatility_filter",
        "params": {
          "natr_threshold": 0.8
        }
      },
      {
        "type": "rel_vol_filter",
        "params": {
          "rel_vol_threshold": 1.5,
          "lookback_period": 20
        }
      }
    ]
  },
  "entryTrigger": {
    "type": "on_candle_close",
    "params": {}
  },
  "entryConditions": {
    "type": "OR",
    "children": [
      {
        "id": "foundation_breakout",
        "type": "AND",
        "children": [
          {
            "id": "level_provider",
            "type": "significant_level",
            "params": {}
          },
          {
            "type": "value_comparison",
            "params": {
              "leftOperand": { "source": "candle", "key": "close" },
              "operator": "gt",
              "rightOperand": { "source": "block_result", "block_id": "level_provider", "key": "detected_level" }
            }
          },
          {
            "type": "price_consolidation",
            "params": {
              "lookback_period": 15,
              "max_range_atr": 0.8
            }
          }
        ]
      }
    ]
  },
  "initialization": {
    "type": "open_position",
    "params": {
      "direction": "LONG",
      "risk_type": "percent_balance",
      "risk_value": 1.0,
      "sl_type": "atr_multiplier",
      "sl_value": 2.0,
      "tp_type": "rr_multiplier",
      "tp_value": 5.0,
      "partial_exits": [
        { "tp_type": "rr_multiplier", "tp_value": 1.5, "size_pct": 40.0 },
        { "tp_type": "rr_multiplier", "tp_value": 3.0, "size_pct": 30.0 },
        { "tp_type": "rr_multiplier", "tp_value": 5.0, "size_pct": 30.0 }
      ]
    }
  },
  "positionManagement": [
    {
      "type": "move_to_breakeven",
      "params": {
        "target_type": "rr_multiplier",
        "target_value": 1.5,
        "offset_pips": 2
      }
    }
  ]
}
```
"""

    parts = []
    if autopilot_system_content:
        parts.append(
            "## PART 1: DEPTHSIGHT AUTOPILOT JSON SPECIFICATION & EXAMPLES\n"
            + autopilot_system_content
        )
    parts.append(mcp_operational_rules)
    if generator_content:
        parts.append(
            "## PART 2: ALLOWED BLOCK TYPES, SCHEMAS & LIVE CODEBASE BLOCKS\n"
            + generator_content
        )

    return "\n\n".join(parts)


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

    # Category handlers
    if category == "codebase":
        return get_formatted_codebase_reference()

    elif category == "memory_guide":
        return MEMORY_GUIDE_DOC

    elif category == "allowed_types":
        return ALLOWED_TYPES_DOC

    # Default ("summary", "all", "schemas", "blocks", "examples"):
    # Returns the full platform autopilot generator system prompt with all blocks and code
    return get_autopilot_generator_prompt()


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


async def get_storage_symbols_info(
    redis_client: Optional[Any] = None, force_refresh: bool = False
) -> list[dict]:
    """Retrieves cached storage symbols metadata from Redis or scans parquet files."""
    cache_key = "depthsight:admin:storage_info"
    if redis_client and not force_refresh:
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(f"Failed to read storage info from Redis cache: {e}")

    project_root = Path(__file__).parent.parent.parent.resolve()
    base_path = project_root / "data_storage" / "binance" / "futures"
    if not base_path.exists():
        return []

    from api.routes.admin import _scan_storage_sync

    symbols_data = await asyncio.to_thread(_scan_storage_sync, base_path)
    if redis_client and symbols_data:
        try:
            await redis_client.set(cache_key, json.dumps(symbols_data), ex=600)
        except Exception:
            pass

    return symbols_data


async def tool_get_historical_data_range(
    symbol: Optional[str] = None,
    redis_client: Optional[Any] = None,
) -> str:
    """Queries loaded historical market data coverage, date ranges, and available features."""
    storage_data = await get_storage_symbols_info(redis_client)
    if not storage_data:
        return (
            "⚠️ No historical data storage directory found or no symbols loaded yet. "
            "Contact your platform administrator or configure the Data Pipeline."
        )

    if symbol:
        clean_target = symbol.strip().upper()
        match = next((s for s in storage_data if s["symbol"] == clean_target), None)
        if not match:
            available_list = ", ".join(sorted([s["symbol"] for s in storage_data])[:20])
            return (
                f"❌ Symbol **{clean_target}** has no historical data loaded in DepthSight.\n\n"
                f"**Available Loaded Symbols ({len(storage_data)} total)**:\n"
                f"{available_list}...\n\n"
                f"Call `get_historical_data_range` without arguments to see the full table."
            )

        kline = match.get("klines_1m") or {}
        s_date = kline.get("start_date", "N/A")
        e_date = kline.get("end_date", "N/A")
        size_mb = kline.get("size_mb", 0)
        tfs = ", ".join(match.get("timeframes", [])) or "1m"

        depth_status = "✅ Available" if match.get("has_depth") else "❌ Not loaded"
        depth_note = (
            "*(Binance Futures aggregated percentage buckets: depth_m0.2..m5.0 bids, depth_p0.2..p5.0 asks, notional_m/p. Used by 'order_book_zone' & 'orderbook_imbalance', NOT tick-level L2 ladder)*"
            if match.get("has_depth")
            else "*(Not loaded)*"
        )

        return (
            f"### Historical Data Coverage: **{clean_target}**\n"
            f"- **Valid Date Interval**: `{s_date}` to `{e_date}`\n"
            f"- **Available Timeframes**: {tfs}\n"
            f"- **1m Parquet Size**: {size_mb} MB\n"
            f"- **Enriched with High-Res Data**: {'Yes' if kline.get('is_enriched') else 'No'}\n\n"
            f"#### Microstructural / PRO Features for {clean_target}:\n"
            f"- **Orderbook Depth (bookDepth)**: {depth_status} {depth_note}\n"
            f"- **Open Interest (OI)**: {'✅ Available' if match.get('has_oi') else '❌ Not loaded'}\n"
            f"- **1s Tick Klines**: {'✅ Available' if match.get('has_klines_1s') else '❌ Not loaded'}\n"
            f"- **AggTrades / Tape Delta**: {'✅ Available' if match.get('has_aggtrades') else '❌ Not loaded'}\n\n"
            f"💡 **Orderbook Structure Note**: DepthSight orderbook data is **bookDepth** (aggregated snapshots of cumulative depth and notional volume at percentage thresholds ±0.2%, ±1.0%, ±2.0%, ±3.0%, ±4.0%, ±5.0%), NOT a tick-by-tick L2 price ladder.\n"
            f"💡 *When running backtests on {clean_target}, choose start_date and end_date between `{s_date}` and `{e_date}`.*"
        )

    # General summary table of all loaded symbols
    lines = [
        f"### DepthSight Historical Market Storage ({len(storage_data)} symbols available):",
        "",
        "| Symbol | Available History Range | Timeframes | bookDepth (±% Buckets) | Open Interest |",
        "| :--- | :--- | :--- | :---: | :---: |",
    ]
    for s in sorted(storage_data, key=lambda x: x["symbol"]):
        k = s.get("klines_1m") or {}
        s_date = k.get("start_date", "N/A")
        e_date = k.get("end_date", "N/A")
        date_range = (
            f"`{s_date}` to `{e_date}`" if s_date != "N/A" else "Not downloaded"
        )
        tfs = ", ".join(s.get("timeframes", [])[:4])
        if len(s.get("timeframes", [])) > 4:
            tfs += f" (+{len(s['timeframes']) - 4})"
        depth = "✅" if s.get("has_depth") else "❌"
        oi = "✅" if s.get("has_oi") else "❌"
        lines.append(
            f"| **{s['symbol']}** | {date_range} | {tfs or '1m'} | {depth} | {oi} |"
        )

    lines.append("")
    lines.append(
        "💡 **Orderbook Format (bookDepth)**: DepthSight orderbook data is **bookDepth** (Binance Futures percentage depth buckets: ±0.2%, ±1%, ±2%, ±3%, ±4%, ±5% bids/asks depth and notional volume), NOT raw tick-level L2 ladder. Used by PRO blocks like `order_book_zone` and `orderbook_imbalance`."
    )
    lines.append(
        "💡 **Rule for Backtests**: You must ONLY run backtests on symbols listed above, and your `start_date` and `end_date` must strictly fall within each symbol's available history range."
    )

    return "\n".join(lines)


def resolve_strategy_tags_and_type(
    strategy_config: dict,
    clean_symbol: str,
    explicit_tags: Optional[List[str]] = None,
    explicit_strategy_type: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Resolves and normalizes strategy_type and tags for agent memory insights.

    Prefers explicit tags and strategy_type provided directly by the calling agent.
    If omitted or empty, falls back to zero-token programmatic extraction from
    strategy blocks and indicators, ensuring consistent vocabulary without burning server LLM tokens.
    """

    # 1. Helper to extract all block types recursively
    def _extract_blocks(node: Any) -> List[str]:
        types = []
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, str) and t.strip():
                types.append(t.strip())
            for v in node.values():
                types.extend(_extract_blocks(v))
        elif isinstance(node, list):
            for item in node:
                types.extend(_extract_blocks(item))
        return types

    extracted_blocks = _extract_blocks(strategy_config)
    blocks_lower = [b.lower() for b in extracted_blocks]
    blocks_text = " ".join(blocks_lower)

    # 2. Resolve strategy_type
    raw_type = explicit_strategy_type or strategy_config.get("strategy_type")
    valid_types = {
        "breakout",
        "mean_reversion",
        "trend_following",
        "scalping",
        "momentum",
    }
    type_synonyms = {
        "trend": "trend_following",
        "trending": "trend_following",
        "trend_follower": "trend_following",
        "reversion": "mean_reversion",
        "mean_revert": "mean_reversion",
        "range": "mean_reversion",
        "scalp": "scalping",
        "squeeze": "breakout",
        "volatility": "breakout",
    }

    strat_type = None
    if raw_type and isinstance(raw_type, str):
        cleaned_raw = raw_type.strip().lower()
        cleaned_raw = type_synonyms.get(cleaned_raw, cleaned_raw)
        if cleaned_raw in valid_types:
            strat_type = cleaned_raw

    if not strat_type:
        if any(k in blocks_text for k in ("squeeze", "breakout", "donchian")):
            strat_type = "breakout"
        elif any(
            k in blocks_text for k in ("rsi", "reversion", "bollinger", "stoch", "mean")
        ):
            strat_type = "mean_reversion"
        elif any(
            k in blocks_text
            for k in ("trend", "adx", "supertrend", "ema", "sma", "macd")
        ):
            strat_type = "trend_following"
        else:
            strat_type = "breakout"

    # 3. Resolve and normalize tags
    clean_sym_lower = clean_symbol.strip().lower() if clean_symbol else ""
    sym_base = (
        clean_sym_lower.replace("usdt", "").replace("busd", "").replace("usdc", "")
    )

    def _normalize_tag(tag: Any) -> Optional[str]:
        if not isinstance(tag, str):
            return None
        t = tag.strip().lower()
        t = re.sub(r"[\s\-/]+", "_", t)
        t = re.sub(r"[^\w]", "", t).strip("_")
        if not t:
            return None
        # Disallow symbol in tags list (symbol has its own dedicated column)
        if t == clean_sym_lower or (sym_base and t == sym_base):
            return None
        return t

    tags_source = (
        explicit_tags
        if (explicit_tags and isinstance(explicit_tags, list))
        else strategy_config.get("tags")
    )

    normalized_tags: List[str] = []
    if tags_source and isinstance(tags_source, list):
        for raw_tag in tags_source:
            norm = _normalize_tag(raw_tag)
            if norm and norm not in normalized_tags:
                normalized_tags.append(norm)

    # 4. If tags still empty, extract programmatic fallback from strategy blocks at 0 cost
    if not normalized_tags:
        skip_container_blocks = {
            "and",
            "or",
            "not",
            "open_position",
            "close_position",
            "on_candle_close",
            "on_candle_open",
            "none",
        }
        for b in extracted_blocks:
            norm_b = _normalize_tag(b)
            if (
                norm_b
                and norm_b not in skip_container_blocks
                and norm_b not in normalized_tags
            ):
                normalized_tags.append(norm_b)

        # Ensure strategy type tag is included if space allows
        if strat_type not in normalized_tags:
            normalized_tags.insert(0, strat_type)

    # Limit to 5 tags max
    clean_tags = normalized_tags[:5]
    return strat_type, clean_tags


async def tool_run_backtest(
    symbol: str,
    strategy_config: dict,
    start_date: str,
    end_date: str,
    timeframe: str = "15m",
    engine: str = "vector",
    strategy_name: Optional[str] = None,
    strategy_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    reasoning: Optional[str] = None,
    user: Optional[models.User] = None,
    redis_client: Optional[Any] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """Executes a backtest through Celery with user plan limits, quota checks, and automatic memory bank recording."""
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

    # Support both direct strategy_config and config_data-wrapped schemas
    if isinstance(strategy_config.get("config_data"), dict):
        strategy_config = strategy_config["config_data"]

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
        norm_engine = schemas.normalize_backtest_engine(engine, default="vector")
    except ValueError as exc:
        return f"Error: Invalid backtest engine '{engine}': {exc}"

    try:
        _enforce_strategy_plan_restrictions(strategy_config, user)
        _enforce_backtest_engine_access(user, norm_engine)
    except Exception as e:
        return f"Plan Restriction Error: {e}"

    # Check if strategy requires precision engine
    if is_strategy_kline_only(strategy_config) and norm_engine == "vector":
        return (
            "Error: This strategy contains advanced blocks that require the 'precision' engine. "
            "Please specify engine='precision' (available on Pro plans)."
        )

    # 3. Historical data availability and boundary verification
    storage_symbols = await get_storage_symbols_info(redis_client)
    if storage_symbols:
        symbol_map = {s["symbol"]: s for s in storage_symbols if s.get("symbol")}
        if clean_symbol not in symbol_map:
            available_list = ", ".join(sorted(symbol_map.keys())[:15])
            return (
                f"Historical Data Error: Symbol '{clean_symbol}' has no historical data loaded in DepthSight. "
                f"Available symbols ({len(symbol_map)} total): {available_list}... "
                f"Call 'get_historical_data_range' to view all supported pairs and their valid date intervals."
            )

        sym_info = symbol_map[clean_symbol]
        kline_info = sym_info.get("klines_1m") or {}
        avail_start_str = kline_info.get("start_date")
        avail_end_str = kline_info.get("end_date")
        if (
            avail_start_str
            and avail_end_str
            and avail_start_str != "N/A"
            and avail_end_str != "N/A"
        ):
            try:
                avail_start_dt = datetime.fromisoformat(avail_start_str)
                avail_end_dt = datetime.fromisoformat(avail_end_str)
                if start_dt.date() < avail_start_dt.date() or end_dt.date() > (
                    avail_end_dt.date() + timedelta(days=1)
                ):
                    return (
                        f"Historical Date Range Error: Requested backtest dates ({start_date} to {end_date}) "
                        f"are outside the loaded historical data for {clean_symbol} ({avail_start_str} to {avail_end_str}). "
                        f"Please adjust start_date and end_date to be strictly within {avail_start_str} and {avail_end_str}."
                    )
            except Exception as dt_err:
                logger.warning(f"Storage boundary date parse error: {dt_err}")

    # 3. Quota and concurrency enforcement
    quota_feature = f"run_{norm_engine}_backtest"
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
            "backtest_engine": norm_engine,
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

        # Extract reasoning: parameter first, then inside strategy_config
        actual_reasoning = (
            reasoning
            or strategy_config.get("reasoning")
            or (
                strategy_config.get("config_data", {}).get("reasoning")
                if isinstance(strategy_config.get("config_data"), dict)
                else ""
            )
            or ""
        ).strip()

        # Ensure we have strat_type for session tracking
        try:
            strat_type, clean_tags = resolve_strategy_tags_and_type(
                strategy_config=strategy_config,
                clean_symbol=clean_symbol,
                explicit_tags=tags,
                explicit_strategy_type=strategy_type,
            )
        except Exception:
            strat_type = strategy_type or "unknown"
            clean_tags = []

        # Automatic Agent Memory Bank Recording & Rule Synthesis Loop (matching platform autopilot)
        memory_status_note = ""
        try:
            import hashlib
            from api.agent_autopilot import (
                run_rule_synthesis,
                evaluate_rule_lifecycle,
            )
            from api.database import async_session_factory

            is_success = pnl > 0.0 and trades >= 5
            outcome = "success" if is_success else "failure"
            reason = (
                "positive return"
                if is_success
                else ("negative return" if pnl <= 0.0 else "too few trades (< 5)")
            )
            filters_list = (
                [
                    f.get("type")
                    for f in strategy_config.get("filters", {}).get("children", [])
                ]
                if isinstance(strategy_config.get("filters"), dict)
                else []
            )

            content = (
                f"{'Profitable' if is_success else 'Failed'} strategy '{run_name}' on {clean_symbol} ({timeframe}): "
                f"PnL={pnl:.2f}%, WR={win_rate:.1f}%, trades={trades}, DD={max_dd:.1f}%. Reason: {reason}. "
                f"Weights: {strategy_config.get('foundation_weights')}, Filters: {filters_list}."
            )
            if actual_reasoning:
                content += f" Reasoning: {actual_reasoning}."
            content += f" Config: {strategy_config}"

            config_str = json.dumps(strategy_config)
            config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()

            mem_data = schemas.AgentMemoryCreate(
                memory_type="strategy_insight",
                content=content,
                relevance_score=1.0 if is_success else 0.8,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=90 if is_success else 30),
                tags=clean_tags,
                symbol=clean_symbol,
                strategy_type=strat_type,
                outcome=outcome,
                confidence=0.85 if is_success else 0.70,
                validated_count=1,
                config_hash=config_hash,
            )

            if db:
                await crud.create_agent_memory(
                    db, user_id=user.id, memory_data=mem_data
                )
                await db.commit()
            else:
                async with async_session_factory() as db_session:
                    await crud.create_agent_memory(
                        db_session, user_id=user.id, memory_data=mem_data
                    )
                    await db_session.commit()

            # Trigger background rule synthesis and lifecycle evaluation
            asyncio.create_task(run_rule_synthesis(user.id, strat_type))
            asyncio.create_task(
                evaluate_rule_lifecycle(user.id, strategy_config, pnl, strat_type)
            )

            memory_status_note = (
                f"\n\n🧠 **Memory Bank Auto-Recorded**:\n"
                f"- Run saved as `{outcome.upper()}` for `{clean_symbol}` (`{strat_type}`).\n"
                f"- Assigned tags: {', '.join(f'`{t}`' for t in clean_tags)}.\n"
                f"- Background rule synthesis & lifecycle active (synthesizes new rules every 3+ insights)."
            )
            if not actual_reasoning:
                memory_status_note += "\n- ⚠️ *Notice: No `reasoning` parameter provided. Always provide `reasoning` in run_backtest to help the Memory Engine extract higher quality rules.*"
        except Exception as mem_err:
            logger.warning(
                f"Auto-recording memory insight in MCP run_backtest failed: {mem_err}"
            )

        # Check for direction mismatch and trade density diagnostics
        direction_val = str(
            strategy_config.get("initialization", {})
            .get("params", {})
            .get("direction", "LONG")
        ).upper()

        config_text = json.dumps(strategy_config).lower()
        has_opposing = False
        if direction_val == "LONG" and (
            "foundation_short" in config_text
            or '"required_trend": "short"' in config_text
        ):
            has_opposing = True
        elif direction_val == "SHORT" and (
            "foundation_long" in config_text
            or '"required_trend": "long"' in config_text
        ):
            has_opposing = True

        diagnostics_notes = []
        if has_opposing:
            diagnostics_notes.append(
                f"- ⚠️ **Direction Mismatch Warning**: Strategy has `direction='{direction_val}'`, but contains opposing direction conditions. "
                f"DepthSight Vector Engine runs strictly single-directional (`{direction_val}`); all opposing branches are ignored by the engine. Do not mix LONG and SHORT branches in a single configuration."
            )
        if trades < 30:
            diagnostics_notes.append(
                f"- ⚠️ **Low Trade Sample Notice ({trades} trades in {duration_days} days)**: "
                "For statistical validity (and user prompts requiring >= 50 trades), avoid multi-week extremes (such as 20d High) which occur too rarely. "
                "Use `significant_level` (intraday swing levels), 4h local levels, or retests (`return_to_level`) to generate adequate trade sample size."
            )
        diagnostics_text = (
            ("\n\n🛠️ **Engine Diagnostics**:\n" + "\n".join(diagnostics_notes))
            if diagnostics_notes
            else ""
        )

        status_emoji = "✅" if pnl > 0 else "⚠️"
        
        # Stateful MCP guidance for LLM
        global _MCP_SESSION_STATE
        session_key = f"{user.id}:{clean_symbol}:{strat_type}"
        state = _MCP_SESSION_STATE.get(session_key)
        
        if state is None:
            state = {"best_pnl": -999999.0, "best_config": None, "failures": 0, "iterations": 0}
            _MCP_SESSION_STATE[session_key] = state
            
        state["iterations"] += 1
        
        if pnl > state["best_pnl"]:
            state["best_pnl"] = pnl
            state["best_config"] = strategy_config
            state["failures"] = 0
            
            autopilot_guidance = (
                f"💡 **Quant Autopilot Guidance (NEW BEST BASELINE)**:\n"
                f"- **Result**: This is your best variant so far in this session (PnL: {pnl:+.2f}%).\n"
                f"- **Next Step**: Adopt this configuration as your new Baseline.\n"
                f"- **Rule**: Make ONLY ONE mathematical mutation at a time to optimize it further."
            )
        else:
            state["failures"] += 1
            if state["failures"] >= 3:
                autopilot_guidance = (
                    f"💡 **Quant Autopilot Guidance (EXHAUSTED - PARADIGM PIVOT)**:\n"
                    f"- **Result**: You failed to improve the baseline 3 times in a row. You are stuck in a local minimum.\n"
                    f"- **Action**: DISCARD this strategy architecture entirely. Pivot to a new archetype (e.g. mean_reversion, trend_following, etc).\n"
                )
                # Reset state so new paradigm starts fresh
                state["best_pnl"] = -999999.0
                state["failures"] = 0
            else:
                best_config_str = json.dumps(state["best_config"], indent=2)
                autopilot_guidance = (
                    f"💡 **Quant Autopilot Guidance (DEGRADATION - BACKTRACK REQUIRED)**:\n"
                    f"- **Result**: This mutation degraded performance (PnL: {pnl:+.2f}% vs Best: {state['best_pnl']:+.2f}%).\n"
                    f"- **Action**: You MUST revert to your best baseline. Do NOT use the variant you just generated.\n"
                    f"- **Best Config**: Here is the exact JSON of your best variant. Use this as your baseline for the next mutation:\n"
                    f"```json\n{best_config_str}\n```"
                )

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
            f"- **Task ID**: `{celery_task.id}`"
            f"{memory_status_note}\n\n"
            f"{autopilot_guidance}"
            f"{diagnostics_text}\n\n"
            f"**Recommendation**: If this strategy demonstrates strong risk-adjusted returns, "
            f"consider saving it using `save_strategy` or inspecting learned rules via `search_agent_memory`."
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

    unique_tags = await crud.get_unique_agent_tags(db=db, user_id=user.id)
    tags_pool_text = ""
    if unique_tags:
        tags_str = ", ".join(f"`{t}`" for t in unique_tags)
        tags_pool_text = (
            f"\n\n---\n**Available Database Tags ({len(unique_tags)} in user memory bank):**\n"
            f"{tags_str}\n\n"
            f"*Tagging Rule: When running backtests via `run_backtest` or storing insights via `store_agent_memory`, pick 1 to 4 tags from this pool to maintain consistency. Create a new snake_case tag only if no existing tag fits.*"
        )

    if not memories:
        return f"No agent memories or rules matched your criteria.{tags_pool_text}"

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

    if tags_pool_text:
        lines.append(tags_pool_text)

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

    # Clean, normalize and deduplicate tags (lowercase, stripped, non-empty)
    cleaned_tags = list(
        dict.fromkeys(
            t.strip().lower() for t in tags if t and isinstance(t, str) and t.strip()
        )
    )
    clean_symbol = (
        symbol.strip().upper()
        if symbol and isinstance(symbol, str) and symbol.strip()
        else None
    )
    clean_strat_type = strategy_type.strip().lower()
    clean_outcome = outcome.strip().lower()

    memory_data = schemas.AgentMemoryCreate(
        content=content.strip(),
        strategy_type=clean_strat_type,
        tags=cleaned_tags,
        outcome=clean_outcome,
        confidence=max(0.1, min(1.0, confidence)),
        symbol=clean_symbol,
        memory_type="strategy_insight",
        relevance_score=1.0,
    )

    saved = await crud.create_agent_memory(
        db=db, user_id=user.id, memory_data=memory_data
    )
    await db.commit()

    # Trigger background rule synthesis (exactly like platform autopilot)
    try:
        from api.agent_autopilot import run_rule_synthesis

        asyncio.create_task(run_rule_synthesis(user.id, clean_strat_type))
    except Exception as e:
        logger.debug(f"Rule synthesis trigger skipped: {e}")

    # Fetch updated unique tags to return in response
    updated_tags = await crud.get_unique_agent_tags(db=db, user_id=user.id)
    tags_pool_str = ", ".join(f"`{t}`" for t in updated_tags)

    return (
        f"✅ Insight saved to persistent memory bank!\n"
        f"- **ID**: `{saved.id}`\n"
        f"- **Category**: `{saved.strategy_type}`\n"
        f"- **Symbol**: `{saved.symbol or 'General'}`\n"
        f"- **Outcome**: `{saved.outcome}`\n"
        f"- **Tags**: {', '.join(f'`{t}`' for t in saved.tags or [])}\n\n"
        f"**Active Tag Pool ({len(updated_tags)} tags):** {tags_pool_str}\n"
        f"*(Background rule synthesis automatically checks for new rules when 3+ insights exist for {clean_strat_type})*"
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

    elif name == "get_historical_data_range":
        return await tool_get_historical_data_range(
            symbol=arguments.get("symbol"),
            redis_client=redis_client,
        )

    elif name == "run_backtest":
        return await tool_run_backtest(
            symbol=arguments.get("symbol", ""),
            strategy_config=arguments.get("strategy_config", {}),
            start_date=arguments.get("start_date", ""),
            end_date=arguments.get("end_date", ""),
            timeframe=arguments.get("timeframe", "15m"),
            engine=arguments.get("engine", "vector"),
            strategy_name=arguments.get("strategy_name"),
            strategy_type=arguments.get("strategy_type"),
            tags=arguments.get("tags"),
            reasoning=arguments.get("reasoning"),
            user=user,
            redis_client=redis_client,
            db=db,
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
