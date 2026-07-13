# ruff: noqa: E402
# api/ai_assistant.py
import os
import asyncio
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from fastapi import HTTPException, status, WebSocket
import uuid
import base64

import httpx

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - depends on optional package availability
    genai = None
    types = None

from . import schemas, crud, models
from .analytics_parsers import DecisionTraceParser
from .gamification import grant_achievement
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .dependencies import (
    get_redis_client_for_quota,
    is_strategy_pro_only,
    is_strategy_kline_only,
)
from .quota_manager import QuotaManager
from fastapi import Depends
import redis.asyncio as redis
from functools import lru_cache

# Logger configuration
logger = logging.getLogger(__name__)

# Global variable for cached prompt
CACHED_GENERATOR_PROMPT: Optional[str] = None
CACHED_ADVISOR_TEMPLATE: Optional[str] = None

SUPPORTED_AI_PROVIDERS = {"google", "openrouter", "qwen"}
DEFAULT_AI_PROVIDER = "qwen"
DEFAULT_GOOGLE_MODEL = "gemini-3-flash-preview"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_TIMEOUT_SECONDS = 120.0
DEFAULT_QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_QWEN_TIMEOUT_SECONDS = 300.0
_CONFIGURED_GEMINI_CLIENT = None


@lru_cache(maxsize=None)
def load_prompt(filename: str) -> str:
    filepath = os.path.join(os.path.dirname(__file__), "prompts", filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# NEW PROMPT FOR "ADVISOR"
ASSISTANT_ADVISOR_PROMPT_TEMPLATE = load_prompt("advisor_system.md")

GENERATOR_PROMPT_TEMPLATE = load_prompt("generator_system.md")


def _get_default_block_params(block_type: str) -> Dict[str, Any]:
    """
    Returns a dictionary with default parameters for the specified block type.
    Synchronized with frontend/src/components/strategy-editor/migration.ts
    """
    # Mapping to correct incorrect block names from AI
    type_mapping = {
        "trend_strength_filter": "trend_filter",
        "adx_filter": "trend_filter",
        "btc_state": "btc_state_filter",
        "position_state": "price_vs_level",  # Non-existent block -> replacement
    }
    block_type = type_mapping.get(block_type, block_type)

    if block_type == "trading_session":
        return {"session": "london"}
    if block_type == "volatility_filter":
        return {"indicator": "ATR", "operator": "gt", "value": 1.5}
    if block_type == "trend_filter":
        return {"indicator": "ADX", "threshold": 25.0}
    if block_type == "senior_tf_confluence":
        return {"timeframe": "1h"}
    if block_type == "natr_filter":
        return {"natr_threshold": 1.0}
    if block_type == "rel_vol_filter":
        return {"mode": "relative", "rel_vol_threshold": 1.5, "lookback_period": 20}
    if block_type == "significant_level":
        return {
            "level_type": "daily_high",
            "proximity_type": "percentage",
            "proximity_value": 0.2,
        }
    if block_type == "round_level":
        return {"proximity_type": "percentage", "proximity_value": 0.2}
    if block_type == "trend_direction":
        return {
            "timeframe": "15m",
            "required_trend": "LONG",
            "fast_period": 10,
            "slow_period": 50,
            "rsi_period": 14,
            "rsi_lower_bound": 40,
            "rsi_upper_bound": 60,
        }
    if block_type == "volume_confirmation":
        return {"multiplier": 1.5, "lookback_period": 20}
    if block_type == "local_level":
        return {
            "timeframe": "1h",
            "lookback_period": 24,
            "level_type": "high",
            "proximity_type": "percentage",
            "proximity_value": 0.2,
            "is_data_provider": False,
        }
    if block_type == "tape_analysis":
        return {"time_window_sec": 5}
    if block_type == "order_book_zone":
        return {"side": "bids", "range_type": "Percentage", "range_value": 1.0}
    if block_type == "classic_pattern":
        return {"pattern_name": "bullish_engulfing"}
    if block_type == "price_consolidation":
        return {"lookback_period": 20, "max_range_atr": 0.5}
    if block_type == "return_to_level":
        return {
            "level_block_id": None,
            "retest_type": "touch",
            "approach_direction": "any",
            "confirmation_time_sec": 0,
            "cooldown_sec": 300,
            "proximity_multiplier": 0.1,
            "departure_multiplier": 1.5,
        }
    if block_type == "value_comparison":
        return {"operator": "gt", "rightOperand": {"source": "value", "value": 0}}
    if block_type == "rsi_condition":
        return {"period": 14, "operator": "gt", "value": 70, "shift": 0}
    if block_type == "ma_cross_condition":
        return {
            "fast_period": 9,
            "slow_period": 21,
            "ma_type": "ema",
            "shift": 0,
            "operator": "crosses_above",
        }
    if block_type == "macd_condition":
        return {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "condition": "macd_cross_above_signal",
            "shift": 0,
        }
    if block_type == "bollinger_bands_condition":
        return {
            "period": 20,
            "std_dev": 2,
            "source": "close",
            "location": "above_upper",
            "shift": 0,
        }
    if block_type == "stochastic_condition":
        return {
            "k_period": 14,
            "d_period": 3,
            "smoothing": 3,
            "condition": "k_cross_above_d",
            "shift": 0,
        }
    if block_type == "price_vs_level":
        return {
            "price_source": {"source": "candle", "key": "close", "shift": 0},
            "operator": "gt",
            "level_source": None,
        }
    if block_type == "btc_state_filter":
        return {"required_state": "Consolidation"}
    if block_type == "open_interest":
        return {"analyze": "change_pct", "lookback": 5, "operator": "gt", "value": 1.0}
    if block_type == "correlation":
        return {"lookback": 50, "operator": "lt", "value": 0.7}
    if block_type == "scale_in":
        return {"add_size_pct_of_initial_risk": 100, "max_entries": 3}
    if block_type == "dca_management":
        return {
            "max_safety_orders": 3,
            "volume_multiplier": 2.0,
            "step_type": "percentage",
            "step_value": 1.0,
        }
    if block_type == "grid_management":
        return {
            "grid_levels": 10,
            "range_type": "percentage",
            "upper_bound": 1.0,
            "lower_bound": 1.0,
        }
    if block_type == "modify_stop_loss":
        return {"new_sl_price": {"source": "value", "value": 0}}
    if block_type == "modify_take_profit":
        return {"new_tp_price": {"source": "value", "value": 0}}
    if block_type == "close_position":
        return {}
    if block_type == "trailing_stop":
        return {"type": "Percentage", "value": 2.0}
    if block_type == "move_to_breakeven":
        return {"target_type": "rr_multiplier", "target_value": 1.0, "offset_pips": 2}
    if block_type == "level_touch_analyzer":
        return {
            "level_source": None,
            "lookback_candles": 50,
            "touch_tolerance_pct": 0.1,
            "invalidate_on_pierce": True,
            "min_touches": 3,
        }
    if block_type == "volatility_squeeze":
        return {"lookback_candles": 20, "squeeze_ratio": 0.6}
    if block_type == "price_action_analyzer":
        return {
            "structure_type": "higher_lows",
            "lookback_candles": 30,
            "min_points": 2,
            "order": 3,
        }
    # Return empty dictionary for all other types
    return {}


def _ensure_default_params(node: Any):
    """
    Recursively traverses the strategy JSON structure and injects/complements default 'params'.
    """
    if not isinstance(node, dict):
        return

    # If this is a block with a type, process its parameters
    if "type" in node:
        # Ensure a unique ID is present for every block
        if "id" not in node or not node["id"]:
            import uuid

            node["id"] = str(uuid.uuid4())
        # Correct the type name if necessary
        type_mapping = {
            "trend_strength_filter": "trend_filter",
            "adx_filter": "trend_filter",
            "btc_state": "btc_state_filter",
            "position_state": "price_vs_level",
        }
        if node["type"] in type_mapping:
            logger.info(
                f"Migrating block type from '{node['type']}' to '{type_mapping[node['type']]}'"
            )
            node["type"] = type_mapping[node["type"]]

        # Get default parameters
        defaults = _get_default_block_params(node["type"])

        # If there are no parameters at all, add defaults
        if "params" not in node:
            node["params"] = defaults
            logger.info(f"Injected default params for block type: {node['type']}")
        # If parameters are present but incomplete, complement them with defaults
        elif defaults:
            # Merge: defaults first, then existing (which overwrite defaults)
            node["params"] = {**defaults, **node["params"]}
            logger.debug(f"Merged default params for block type: {node['type']}")

    # Recursively traverse all possible nested structures
    for key, value in node.items():
        if isinstance(value, list):
            for item in value:
                _ensure_default_params(item)
        elif isinstance(value, dict):
            _ensure_default_params(value)


def _sanitize_strategy_nulls(node: Any) -> Any:
    """
    Recursively sanitize a strategy JSON dict to fix common LLM issues
    (especially from Qwen models) where required fields are set to null
    instead of empty containers.

    Fixes:
      - children: null  ->  children: []
      - params: null    ->  params: {}
      - positionManagement: null  ->  positionManagement: []
      - Ensures filters/entryConditions have type + children structure
      - Ensures initialization has type + params structure
      - Ensures entryTrigger has type
    """
    if not isinstance(node, dict):
        return node

    # Fix null children -> empty list (ConditionNode requires List, not None)
    if "children" in node and node["children"] is None:
        node["children"] = []

    # Fix null params -> empty dict (InitializationBlock, EntryTrigger require Dict)
    if "params" in node and node["params"] is None:
        node["params"] = {}

    # Fix null positionManagement -> empty list
    if "positionManagement" in node and node["positionManagement"] is None:
        node["positionManagement"] = []

    # Fix null foundation_weights -> empty dict
    if "foundation_weights" in node and node["foundation_weights"] is None:
        node["foundation_weights"] = {}

    # Ensure filters is a proper ConditionNode dict, not a scalar or None
    if "filters" in node:
        f = node["filters"]
        if f is None:
            node["filters"] = {"type": "AND", "children": []}
        elif isinstance(f, dict) and "children" not in f:
            f["children"] = []
        elif isinstance(f, dict) and f.get("children") is None:
            f["children"] = []

    # Ensure entryConditions is a proper ConditionNode dict
    if "entryConditions" in node:
        ec = node["entryConditions"]
        if ec is None:
            node["entryConditions"] = {"type": "OR", "children": []}
        elif isinstance(ec, dict) and "children" not in ec:
            ec["children"] = []
        elif isinstance(ec, dict) and ec.get("children") is None:
            ec["children"] = []

    # Ensure initialization has required structure
    if "initialization" in node:
        init = node["initialization"]
        if init is None:
            node["initialization"] = {"type": "open_position", "params": {}}
        elif isinstance(init, dict):
            if "type" not in init:
                init["type"] = "open_position"
            if "params" not in init or init["params"] is None:
                init["params"] = {}

    # Ensure entryTrigger has required structure
    if "entryTrigger" in node:
        et = node["entryTrigger"]
        if et is None:
            node["entryTrigger"] = {"type": "on_candle_close", "timeframe": "1m"}
        elif isinstance(et, dict) and "type" not in et:
            et["type"] = "on_candle_close"

    # Recurse into all nested dicts and lists
    for key, value in node.items():
        if isinstance(value, list):
            for item in value:
                _sanitize_strategy_nulls(item)
        elif isinstance(value, dict):
            _sanitize_strategy_nulls(value)

    return node


from .plans import plans_config


def _build_tier_context_message(user: models.User, is_advisor: bool) -> str:
    pro_blocks = plans_config.get_block_restrictions().get("pro_only", [])
    kline_blocks = plans_config.get_block_restrictions().get("kline_only", [])

    context = "\n\n# User Subscription & System Limits Context:\n"
    context += f"The user is currently on the '{user.plan}' subscription tier.\n"

    if user.plan not in ["pro", "institutional"]:
        context += f"IMPORTANT: They DO NOT have access to Pro blocks. The restricted Pro blocks are: {', '.join(pro_blocks)}.\n"
        if not is_advisor:
            context += "CRITICAL RULE: Since you are generating a JSON strategy payload, you MUST NOT include any of the restricted Pro blocks. Doing so will cause the system to reject the strategy with a 403 error.\n"
        else:
            context += "Since you are acting as an Advisor, you may carefully and unobtrusively mention how a specific Pro block (e.g. 'correlation' to filter dumps, or 'tape_condition' for microstructure) could legitimately improve their strategy. DO NOT be pushy. Mention it purely as a technical option.\n"
    else:
        context += f"The user holds a Pro tier. They can use any blocks, including the advanced Pro blocks: {', '.join(pro_blocks)}.\n"

    context += "\n# Engine Constraints:\n"
    context += f"The 'Turbo' (Vector) engine is extremely fast but DOES NOT support the following heavy blocks: {', '.join(kline_blocks)}.\n"
    context += "If the user mentions wanting speed or using Turbo, and the strategy relies on these blocks, inform them they will need to use the 'Precision' (Kline) engine or remove the heavy blocks.\n"
    return context


def _user_has_precision_access(user: models.User) -> bool:
    quota_limit = (
        plans_config.get_plan(user.plan)
        .get("quotas", {})
        .get("run_kline_backtest_per_day", 0)
    )
    return quota_limit != 0


def _validate_generated_strategy_for_user(
    strategy_json: Dict[str, Any], user: models.User
) -> None:
    if not _user_has_precision_access(user):
        if is_strategy_pro_only(strategy_json):
            raise ValueError(
                "AI generated a strategy with Pro-only blocks for a non-Pro user."
            )
        if is_strategy_kline_only(strategy_json):
            raise ValueError(
                "AI generated a strategy that requires the Precision engine but the user doesn't have access to it."
            )


def get_code_context_for_prompt(file_paths: List[str]) -> Dict[str, str]:
    """
    Reads files, finds blocks marked with AI_CONTEXT_START/END, and returns them.
    """
    context_blocks: Dict[str, str] = {}
    for file_path in file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                found_blocks = re.findall(
                    r"^\s*# AI_CONTEXT_START: (.+?)\s*?\n(.*?)\n^\s*# AI_CONTEXT_END\s*?$",
                    content,
                    re.DOTALL | re.MULTILINE,
                )
                for block_name, code in found_blocks:
                    unique_key = f"{os.path.basename(file_path)}_{block_name.strip()}"
                    context_blocks[unique_key] = code.strip()
            logger.info(
                f"Successfully extracted {len(found_blocks)} context blocks from {file_path}"
            )
        except FileNotFoundError:
            logger.error(f"Context file not found: {file_path}")
        except Exception as e:
            logger.error(f"Error reading or parsing context from {file_path}: {e}")
    return context_blocks


def build_and_cache_prompts():
    """
    Collects context from the codebase and caches BOTH prompts (generator and advisor).
    Called once at application startup.
    """
    global CACHED_GENERATOR_PROMPT, CACHED_ADVISOR_TEMPLATE

    paths_to_scan = [
        os.path.join("api", "schemas.py"),
        os.path.join("bot_module", "strategy.py"),
    ]

    logger.info(f"Building AI assistant prompts from files: {paths_to_scan}")

    code_context = get_code_context_for_prompt(paths_to_scan)

    if not code_context:
        logger.error(
            "No code context was extracted. AI assistant may not function correctly."
        )
        codebase_reference_str = "# No context available."
    else:
        formatted_context = []
        for key, code in code_context.items():
            formatted_context.append(f"### From: {key}\n\n```python\n{code}\n```")
        codebase_reference_str = "\n\n".join(formatted_context)

    # Cache prompt for the GENERATOR
    CACHED_GENERATOR_PROMPT = GENERATOR_PROMPT_TEMPLATE.format(
        codebase_reference=codebase_reference_str
    )
    logger.info("AI JSON Generator (Pro) prompt has been built and cached.")

    # Cache prompt for the ADVISOR
    CACHED_ADVISOR_TEMPLATE = ASSISTANT_ADVISOR_PROMPT_TEMPLATE.format(
        codebase_reference=codebase_reference_str
    )
    logger.info(
        "AI Co-Pilot Advisor (Flash) prompt template has been built and cached."
    )


def contains_python_code(text: str) -> bool:
    """
    Checks text for presence of Python code blocks, ignoring JSON.
    """
    # 1. Keywords that with high probability indicate Python code,
    # rather than JSON or another language. Spaces are important to avoid matching inside words.
    python_keywords = {
        "def ",
        "class ",
        "import ",
        "async def",
        "return ",
        "pair_info:",
        "market_data:",  # Characteristic of your code
        "elif ",
        "try:",
        "except:",
    }

    # 2. Find all blocks enclosed in triple quotes
    code_blocks = re.findall(r"```([\s\S]*?)```", text)
    if not code_blocks:
        return False  # If there are no blocks, there is no code

    for block in code_blocks:
        content = block.strip()

        # 3. Ignore blocks that look like JSON
        if content.startswith("{") and content.endswith("}"):
            continue
        if content.startswith("[") and content.endswith("]"):
            continue

        # 4. Check for Python keywords in the remaining blocks
        for keyword in python_keywords:
            if keyword in content:
                # Keyword found - this is definitely code!
                return True

    return False


# --- RAG: Screener Context Gathering ---
async def enrich_market_context_for_ai(text_prompt: str) -> str:
    """
    Analyzes user text, searches for cryptocurrency mentions, and makes
    a request to the Screener API to get market context (NATR, trend, regime).
    """
    if not text_prompt:
        return ""
    import re

    # 1. Search for full tickers ending with USDT (e.g., SOLUSDT, ARIAUSDT, 1000PEPEUSDT)
    words = re.findall(r"\b[A-Z0-9]{2,10}USDT\b", text_prompt)

    # 2. Exclude stop-words, although matching USDT at the end is already quite precise
    stop_words = {"LONG", "SHORT", "GRID", "DCA", "AND", "OR"}

    possible_symbols = [w for w in words if w not in stop_words]

    context_blocks = []
    screener_url = os.getenv("SCREENER_API_URL", "http://localhost:8050").rstrip("/")

    # To avoid spamming the API, take at most the first 2 found symbols
    for symbol in possible_symbols[:2]:
        target_pair = symbol

        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                api_url = f"{screener_url}/api/v1/metrics/{target_pair}"
                response = await client.get(api_url)
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    natr = data.get("natr", "N/A")
                    trend = data.get("macro_trend", "N/A")
                    oracle = data.get("oracle_regime", "N/A")
                    vol = data.get("volume_24h", "N/A")

                    oracle_text = "Unknown"
                    if oracle == 1:
                        oracle_text = "1 (Impulse / Pump / Dump)"
                    elif oracle == 0:
                        oracle_text = "0 (Flat / Consolidation)"

                    context_blocks.append(
                        f"### LIVE SCREENER DATA for {target_pair} ###\n"
                        f"- Current volatility (NATR): {natr}\n"
                        f"- Current macro-trend (1H vs 6H): {trend}\n"
                        f"- ML Oracle Regime: {oracle_text}\n"
                        f"- Daily volume ($): {vol}\n"
                        f"Consider these metrics when advising the user or building a strategy."
                    )
                else:
                    logger.debug(f"RAG: Coin {target_pair} not found in the screener.")
        except Exception as e:
            logger.warning(
                f"RAG: Error requesting context from screener ({api_url}): {e}"
            )
            break  # If the screener is down, don't waste time on the next symbol

    if context_blocks:
        return "\n\n".join(context_blocks) + "\n\n"
    return ""


# --- Core Logic ---


def _get_active_ai_provider() -> str:
    provider = os.getenv("AI_PROVIDER", DEFAULT_AI_PROVIDER).strip().lower()
    if provider not in SUPPORTED_AI_PROVIDERS:
        raise ConnectionError(
            f"Unsupported AI_PROVIDER '{provider}'. Supported values: {', '.join(sorted(SUPPORTED_AI_PROVIDERS))}."
        )
    return provider


def _get_google_model_name() -> str:
    return os.getenv("GOOGLE_GEMINI_MODEL", DEFAULT_GOOGLE_MODEL).strip()


def _get_openrouter_model_name() -> str:
    configured_model = os.getenv("OPENROUTER_MODEL", "").strip()
    if configured_model:
        return configured_model

    google_model = _get_google_model_name()
    if not google_model:
        return ""
    if "/" in google_model:
        return google_model
    return f"google/{google_model}"


def _get_qwen_model_name() -> str:
    return os.getenv("QWEN_MODEL", "qwen-max").strip()


def _get_active_model_name(provider: Optional[str] = None) -> str:
    active_provider = provider or _get_active_ai_provider()
    if active_provider == "google":
        return _get_google_model_name()
    if active_provider == "openrouter":
        return _get_openrouter_model_name()
    if active_provider == "qwen":
        return _get_qwen_model_name()
    raise ConnectionError(f"Unsupported AI provider: {active_provider}")


def _get_gemini_client():
    global _CONFIGURED_GEMINI_CLIENT
    if _CONFIGURED_GEMINI_CLIENT is not None:
        return _CONFIGURED_GEMINI_CLIENT

    if genai is None:
        raise ConnectionError("google-genai package is not installed.")

    # Check if Vertex AI is enabled
    use_vertex = os.getenv("USE_VERTEX_AI", "False").lower() == "true"
    if use_vertex:
        # Check for GCP key file path
        gcp_key_path = os.getenv("GCP_KEY_PATH", "")
        if not gcp_key_path:
            possible_paths = [
                os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "tg_bot", "gcp_key.json"
                ),
                "tg_bot/gcp_key.json",
                "../tg_bot/gcp_key.json",
                "gcp_key.json",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    gcp_key_path = path
                    break

        if gcp_key_path and os.path.exists(gcp_key_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(gcp_key_path)
            logger.info(f"Loaded GCP credentials from {gcp_key_path}")

        project_id = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "global")

        _CONFIGURED_GEMINI_CLIENT = genai.Client(
            vertexai=True, project=project_id, location=location
        )
        logger.info(
            f"Initialized Gemini Client via Vertex AI (Project: {project_id}, Location: {location})"
        )
    else:
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_api_key:
            raise ConnectionError("GEMINI_API_KEY is not configured.")
        _CONFIGURED_GEMINI_CLIENT = genai.Client(api_key=gemini_api_key)
        logger.info("Initialized Gemini Client via standard Google AI Studio")

    return _CONFIGURED_GEMINI_CLIENT


def _ensure_google_client_configured() -> None:
    try:
        _get_gemini_client()
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini: {e}")
        raise ConnectionError(f"Could not configure Google Gemini: {e}") from e


def _ensure_ai_provider_configured() -> str:
    provider = _get_active_ai_provider()
    if provider == "google":
        _ensure_google_client_configured()
    elif provider == "qwen":
        qwen_api_key = os.getenv("QWEN_API_KEY", "").strip()
        if not qwen_api_key:
            raise ConnectionError("QWEN_API_KEY is not configured.")
        if not _get_qwen_model_name():
            raise ConnectionError("QWEN_MODEL is not configured.")
    else:
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not openrouter_api_key:
            raise ConnectionError("OPENROUTER_API_KEY is not configured.")
        if not _get_openrouter_model_name():
            raise ConnectionError("OPENROUTER_MODEL is not configured.")
    return provider


def _build_openrouter_headers() -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '').strip()}",
        "Content-Type": "application/json",
    }

    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        headers["HTTP-Referer"] = referer

    title = os.getenv("OPENROUTER_APP_TITLE", "DepthSight AI Assistant").strip()
    if title:
        headers["X-Title"] = title

    return headers


def _normalize_openrouter_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text_part = item.get("text")
            if text_part is None and item.get("type") == "text":
                text_part = item.get("content")
            if text_part:
                parts.append(str(text_part).strip())
        return "\n".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content).strip()


def _extract_openrouter_response_text(
    payload: Dict[str, Any], *, require_complete: bool
) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter response has no choices.")

    first_choice = choices[0] or {}
    finish_reason = first_choice.get("finish_reason")
    if require_complete and finish_reason and finish_reason != "stop":
        raise ValueError(
            f"OpenRouter generation did not finish normally. Reason: {finish_reason}."
        )

    message = first_choice.get("message") or {}
    response_text = _normalize_openrouter_message_content(message.get("content"))
    if not response_text:
        raise ValueError("OpenRouter response has no text content.")
    return response_text


def _extract_google_response_text(response: Any, *, require_complete: bool) -> str:
    if require_complete:
        if not response.candidates:
            # Safely get finish or block reason
            prompt_feedback = getattr(response, "prompt_feedback", None)
            block_reason = "UNKNOWN"
            if prompt_feedback and getattr(prompt_feedback, "block_reason", None):
                block_reason = getattr(
                    prompt_feedback.block_reason,
                    "name",
                    str(prompt_feedback.block_reason),
                )
            safety_ratings_info = (
                getattr(prompt_feedback, "safety_ratings", [])
                if prompt_feedback
                else []
            )
            logger.error(
                "Gemini response has no candidates. Prompt blocked. "
                f"Reason: {block_reason}. Safety ratings: {safety_ratings_info}"
            )
            raise ValueError(
                "Your request was blocked by AI safety filters "
                f"(at the prompt level). Please try to rephrase "
                f"it. Reason: {block_reason}."
            )

        first_candidate = response.candidates[0]
        finish_reason = getattr(first_candidate, "finish_reason", "STOP")
        finish_reason_str = str(finish_reason).upper()
        if "STOP" not in finish_reason_str:
            safety_ratings_info = getattr(first_candidate, "safety_ratings", [])
            logger.error(
                "Gemini generation did not finish normally. "
                f"Reason: {finish_reason_str}. Safety ratings: {safety_ratings_info}"
            )
            raise ValueError(
                "AI could not generate a complete response. "
                f"Generation was interrupted due to: '{finish_reason_str}'. "
                "Try simplifying the request."
            )

        if first_candidate.content and first_candidate.content.parts:
            for part in first_candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    return part.text

        finish_reason_str = "UNKNOWN"
        if getattr(first_candidate, "finish_reason", None):
            finish_reason_str = str(first_candidate.finish_reason).upper()
        safety_ratings_info = getattr(first_candidate, "safety_ratings", [])
        logger.error(
            "Gemini candidate content has no text part. "
            f"Generation blocked. Reason: {finish_reason_str}. Safety ratings: {safety_ratings_info}"
        )
        raise ValueError(
            "AI could not generate a text response "
            f"(the content may have been blocked). Reason: {finish_reason_str}."
        )

    # For non-require_complete (e.g. standard chat where we just want the response text)
    if hasattr(response, "text") and response.text:
        return response.text
    if (
        response.candidates
        and response.candidates[0].content
        and response.candidates[0].content.parts
    ):
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                return part.text
    return ""


def _normalize_image_payload(
    image_base64: Optional[str], image_mime_type: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    if not image_base64:
        return None, None

    mime_type = (image_mime_type or "image/jpeg").strip() or "image/jpeg"
    data = image_base64.strip()
    match = re.match(
        r"^data:(?P<mime>image/[-+.\w]+);base64,(?P<data>.*)$",
        data,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        mime_type = match.group("mime") or mime_type
        data = match.group("data").strip()

    return data, mime_type


async def _generate_google_json_response(
    system_prompt: str,
    user_prompt: str,
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    max_output_tokens: int = 8192,
    model_name: Optional[str] = None,
) -> str:
    _ensure_google_client_configured()
    client = _get_gemini_client()
    model_name = model_name or _get_google_model_name()

    prompt_parts = [system_prompt, user_prompt]
    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )
    if normalized_image and normalized_mime:
        prompt_parts.append(
            types.Part.from_bytes(
                data=base64.b64decode(normalized_image), mime_type=normalized_mime
            )
        )

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt_parts,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=max_output_tokens,
        ),
    )
    return _extract_google_response_text(response, require_complete=True)


async def _generate_google_text_response(
    system_instruction: str,
    messages: List[Dict[str, str]],
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> str:
    _ensure_google_client_configured()
    client = _get_gemini_client()
    model_name = _get_google_model_name()

    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )

    gemini_contents = []
    for i, msg in enumerate(messages):
        role = "model" if msg["role"] == "assistant" else msg["role"]
        parts = [types.Part.from_text(text=msg["content"])]

        if (
            i == len(messages) - 1
            and msg["role"] == "user"
            and normalized_image
            and normalized_mime
        ):
            parts.append(
                types.Part.from_bytes(
                    data=base64.b64decode(normalized_image), mime_type=normalized_mime
                )
            )

        gemini_contents.append(types.Content(role=role, parts=parts))

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=gemini_contents,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
    )
    return _extract_google_response_text(response, require_complete=False)


async def _call_openrouter_api(
    messages: List[Dict[str, str]],
    *,
    response_format: Optional[Dict[str, str]] = None,
    max_tokens: Optional[int] = None,
    require_complete: bool,
    model_name: Optional[str] = None,
) -> str:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not openrouter_api_key:
        raise ConnectionError("OPENROUTER_API_KEY is not configured.")

    model_name = model_name or _get_openrouter_model_name()
    if not model_name:
        raise ConnectionError("OPENROUTER_MODEL is not configured.")

    timeout_seconds = float(
        os.getenv("OPENROUTER_TIMEOUT_SECONDS", str(DEFAULT_OPENROUTER_TIMEOUT_SECONDS))
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    openrouter_url = (
        os.getenv("OPENROUTER_API_URL", DEFAULT_OPENROUTER_URL).strip()
        or DEFAULT_OPENROUTER_URL
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                openrouter_url,
                headers=_build_openrouter_headers(),
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        response_body = e.response.text
        logger.error(
            f"OpenRouter request failed with status {e.response.status_code}: {response_body}"
        )
        raise ConnectionError(
            f"OpenRouter request failed with status {e.response.status_code}: {response_body}"
        ) from e
    except httpx.RequestError as e:
        logger.error(f"OpenRouter request error: {e}")
        raise ConnectionError(f"OpenRouter request failed: {e}") from e

    return _extract_openrouter_response_text(
        response.json(), require_complete=require_complete
    )


async def _generate_openrouter_json_response(
    system_prompt: str,
    user_prompt: str,
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    max_output_tokens: int = 8192,
    model_name: Optional[str] = None,
) -> str:
    user_content = user_prompt
    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )
    if normalized_image and normalized_mime:
        user_content = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{normalized_mime};base64,{normalized_image}"
                },
            },
        ]

    return await _call_openrouter_api(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_output_tokens,
        require_complete=True,
        model_name=model_name,
    )


async def _generate_openrouter_text_response(
    system_instruction: str,
    messages: List[Dict[str, str]],
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> str:
    openrouter_messages = [{"role": "system", "content": system_instruction}]
    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )

    for i, msg in enumerate(messages):
        content = msg["content"]
        if (
            i == len(messages) - 1
            and msg["role"] == "user"
            and normalized_image
            and normalized_mime
        ):
            content = [
                {"type": "text", "text": msg["content"]},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{normalized_mime};base64,{normalized_image}"
                    },
                },
            ]
        openrouter_messages.append({"role": msg["role"], "content": content})

    return await _call_openrouter_api(
        openrouter_messages,
        require_complete=False,
    )


def _extract_qwen_response_text(
    payload: Dict[str, Any], *, require_complete: bool
) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Qwen response has no choices.")

    first_choice = choices[0] or {}
    finish_reason = first_choice.get("finish_reason")
    if require_complete and finish_reason and finish_reason != "stop":
        raise ValueError(
            f"Qwen generation did not finish normally. Reason: {finish_reason}."
        )

    message = first_choice.get("message") or {}
    response_text = message.get("content", "").strip()
    if not response_text:
        raise ValueError("Qwen response has no text content.")
    return response_text


async def _call_qwen_api(
    messages: List[Dict[str, str]],
    *,
    response_format: Optional[Dict[str, str]] = None,
    max_tokens: Optional[int] = None,
    require_complete: bool,
    model_name: Optional[str] = None,
) -> str:
    qwen_api_key = os.getenv("QWEN_API_KEY", "").strip()
    if not qwen_api_key:
        raise ConnectionError("QWEN_API_KEY is not configured.")

    model_name = model_name or _get_qwen_model_name()
    if not model_name:
        raise ConnectionError("QWEN_MODEL is not configured.")

    timeout_seconds = float(
        os.getenv("QWEN_TIMEOUT_SECONDS", str(DEFAULT_QWEN_TIMEOUT_SECONDS))
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    qwen_url = os.getenv("QWEN_API_URL", DEFAULT_QWEN_URL).strip() or DEFAULT_QWEN_URL
    headers = {
        "Authorization": f"Bearer {qwen_api_key}",
        "Content-Type": "application/json",
    }

    # Retry with exponential backoff for transient errors (429, 5xx, timeouts)
    max_retries = 3
    last_exception: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    qwen_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

            return _extract_qwen_response_text(
                response.json(), require_complete=require_complete
            )
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            response_body = e.response.text
            is_retryable = status_code == 429 or status_code >= 500
            if is_retryable and attempt < max_retries - 1:
                backoff = 2**attempt  # 1s, 2s, 4s
                logger.warning(
                    f"Qwen request failed with status {status_code} (attempt {attempt + 1}/{max_retries}). "
                    f"Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                last_exception = e
                continue
            logger.error(
                f"Qwen request failed with status {status_code}: {response_body}"
            )
            raise ConnectionError(
                f"Qwen request failed with status {status_code}: {response_body}"
            ) from e
        except (httpx.RequestError, httpx.TimeoutException) as e:
            if attempt < max_retries - 1:
                backoff = 2**attempt
                logger.warning(
                    f"Qwen request error (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                last_exception = e
                continue
            logger.error(f"Qwen request error after {max_retries} attempts: {e}")
            raise ConnectionError(
                f"Qwen request failed after {max_retries} attempts: {e}"
            ) from e

    # Should not reach here, but safety fallback
    raise ConnectionError(
        f"Qwen request failed after {max_retries} attempts: {last_exception}"
    )


async def _generate_qwen_json_response(
    system_prompt: str,
    user_prompt: str,
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    max_output_tokens: int = 8192,
    model_name: Optional[str] = None,
) -> str:
    user_content = user_prompt
    logger.warning(
        f"[Qwen Debug] System prompt length: {len(system_prompt)} chars, User prompt length: {len(user_prompt)} chars. "
        f"System prompt preview: {system_prompt[:200]}..."
    )
    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )
    if normalized_image and normalized_mime:
        user_content = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{normalized_mime};base64,{normalized_image}"
                },
            },
        ]

    return await _call_qwen_api(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_output_tokens,
        require_complete=True,
        model_name=model_name,
    )


async def _generate_qwen_text_response(
    system_instruction: str,
    messages: List[Dict[str, str]],
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> str:
    qwen_messages = [{"role": "system", "content": system_instruction}]
    normalized_image, normalized_mime = _normalize_image_payload(
        image_base64, image_mime_type
    )

    for i, msg in enumerate(messages):
        content = msg["content"]
        if (
            i == len(messages) - 1
            and msg["role"] == "user"
            and normalized_image
            and normalized_mime
        ):
            content = [
                {"type": "text", "text": msg["content"]},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{normalized_mime};base64,{normalized_image}"
                    },
                },
            ]
        qwen_messages.append({"role": msg["role"], "content": content})

    return await _call_qwen_api(
        qwen_messages,
        require_complete=False,
    )


async def _generate_json_response(
    system_prompt: str,
    user_prompt: str,
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    max_output_tokens: int = 8192,
    model_name: Optional[str] = None,
) -> str:
    provider = _ensure_ai_provider_configured()
    actual_model = model_name or _get_active_model_name(provider)
    logger.info(
        f"Generating AI JSON via provider '{provider}' using model '{actual_model}'"
    )
    if provider == "google":
        raw = await _generate_google_json_response(
            system_prompt,
            user_prompt,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            max_output_tokens=max_output_tokens,
            model_name=model_name,
        )
    elif provider == "qwen":
        raw = await _generate_qwen_json_response(
            system_prompt,
            user_prompt,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            max_output_tokens=max_output_tokens,
            model_name=model_name,
        )
    else:
        raw = await _generate_openrouter_json_response(
            system_prompt,
            user_prompt,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            max_output_tokens=max_output_tokens,
            model_name=model_name,
        )
        
    return _extract_json_block(raw)

def _extract_json_block(text: str) -> str:
    """Safely extracts a JSON object from text, stripping markdown blocks if present."""
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]
    return text


async def _generate_text_response(
    system_instruction: str,
    messages: List[Dict[str, str]],
    *,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> str:
    provider = _ensure_ai_provider_configured()
    logger.info(
        f"Generating AI text via provider '{provider}' using model '{_get_active_model_name(provider)}'"
    )
    if provider == "google":
        return await _generate_google_text_response(
            system_instruction,
            messages,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
        )
    elif provider == "qwen":
        return await _generate_qwen_text_response(
            system_instruction,
            messages,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
        )
    return await _generate_openrouter_text_response(
        system_instruction,
        messages,
        image_base64=image_base64,
        image_mime_type=image_mime_type,
    )


async def get_chat_response(
    request: schemas.AIChatRequest,
    user: models.User,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client_for_quota),
) -> schemas.AIChatResponse:
    """
    Processes requests to the AI Co-Pilot.
    Uses 'mode' to choose between 'advisor' (cheap Flash model for analysis)
    and 'generator' (powerful Pro model to generate JSON).
    """
    # Grant achievement for using AI assistant
    await grant_achievement(db, user.id, "used_ai_assistant")

    mode = request.mode or "advisor"
    logger.info(f"AI Chat request from user '{user.username}'. Mode: {mode}")

    session_id = request.session_id
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated new session_id: {session_id} for user {user.id}")
    else:
        logger.info(f"Using existing session_id: {session_id} for user {user.id}")

    active_provider = _ensure_ai_provider_configured()

    # Quota check before API call
    quota_manager = QuotaManager(user, redis_client, db)
    if not await quota_manager.check_and_consume("use_ai_assistant"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have exceeded the usage limit for the AI Assistant on your current plan.",
        )

    # ==========================================================================
    # GENERATOR MODE (PRO MODEL)
    # ==========================================================================
    if mode == "generator":
        if not CACHED_GENERATOR_PROMPT:
            logger.error("AI Generator (Pro) prompt is not cached. Cannot proceed.")
            raise ConnectionError("AI Generator prompt is not ready.")

        db_history = await crud.get_chat_history(db, user.id, session_id)
        logger.info(
            f"Generator mode: Retrieved {len(db_history)} messages from DB for session {session_id}"
        )

        # 1: Smart context and prompt construction ---
        # Search for the latest assistant message containing recommendations
        last_assistant_recommendations = ""
        for msg in reversed(db_history):
            if msg.role == "assistant":
                # Ensure this is a message offering generation
                if "prepare an updated strategy configuration" in msg.content:
                    last_assistant_recommendations = msg.content
                    break

        final_instruction = ""
        if last_assistant_recommendations:
            # If recommendations are found, create a clear MODIFICATION prompt
            logger.info(
                "Generator mode: Found prior recommendations, creating a modification prompt."
            )
            final_instruction = (
                f"CRITICAL TASK: Your goal is to **modify** an existing strategy based on the detailed recommendations provided by your 'Advisor' persona in the previous step. You must not create a new strategy from scratch. Strictly follow all instructions given in the recommendations.\n\n"
                f"## Full Text of Advisor's Recommendations (MUST BE IMPLEMENTED):\n"
                f"'''\n{last_assistant_recommendations}\n'''\n\n"
                f"## User's Confirmation:\n"
                f"The user has agreed to these changes with the message: '{request.text_prompt}'\n\n"
                f"## Action Required:\n"
                f"Carefully read the recommendations above. Apply **all** proposed changes (like adding filters, changing weights, adjusting thresholds) to the 'CURRENT STRATEGY CONFIGURATION' provided below and output the complete, updated JSON."
            )
        else:
            # If no recommendations are found, operate in scratch generation mode
            logger.info(
                "Generator mode: No prior recommendations found, creating a standard generation prompt."
            )
            # 2: Remove slicing [:200] for complete context ---
            conversation_summary = []
            for msg in db_history:
                if msg.role == "user":
                    conversation_summary.append(
                        f"USER: {msg.content}"
                    )  # Slicing removed
                elif msg.role == "assistant":
                    conversation_summary.append(
                        f"ASSISTANT: {msg.content}"
                    )  # Slicing removed

            conversation_context = (
                "\n".join(conversation_summary[-6:])
                if conversation_summary
                else "No previous conversation."
            )

            final_instruction = (
                f"Based on our previous conversation:\n{conversation_context}\n\n"
                f"Please generate a strategy configuration from scratch. User's final instruction: '{request.text_prompt}'"
            )

        user_prompt_parts = [f"USER PROMPT: '{final_instruction}'"]

        market_context_str = await enrich_market_context_for_ai(request.text_prompt)
        if market_context_str:
            user_prompt_parts.insert(0, market_context_str)
            logger.info("Generator mode: Injected market RAG context.")

        user_prompt_parts.append(_build_tier_context_message(user, is_advisor=False))

        # Add backtest context if present
        if request.backtest_id:
            db_run = await crud.get_backtest_run_by_any_id(
                db, user_id=user.id, identity=request.backtest_id
            )
            if db_run:
                user_prompt_parts.append("\n\n# BACKTEST ANALYSIS CONTEXT:")
                user_prompt_parts.append(
                    f"Strategy that was tested:\n```json\n{json.dumps(db_run.parameters_json, indent=2)}\n```"
                )
                user_prompt_parts.append(
                    f"\nKPI Results:\n```json\n{json.dumps(db_run.kpi_results_json, indent=2)}\n```"
                )
                logger.info(
                    f"Generator mode: Added backtest context for run {request.backtest_id}"
                )

        # Add current strategy (important for modifications)
        if request.strategy_json:
            user_prompt_parts.append(
                "\n\n# CURRENT STRATEGY CONFIGURATION (modify this):"
            )
            user_prompt_parts.append(json.dumps(request.strategy_json, indent=2))
        else:
            logger.info(
                "Generator mode: No base strategy JSON in context, will generate from scratch."
            )

        full_user_prompt = "\n".join(user_prompt_parts)

        try:
            raw_json_text = await _generate_json_response(
                CACHED_GENERATOR_PROMPT,
                full_user_prompt,
                image_base64=request.image_base64,
                image_mime_type=request.image_mime_type,
            )
            strategy_dict = json.loads(raw_json_text)

            # Apply sanitization for common LLM structure issues (especially Qwen)
            _sanitize_strategy_nulls(strategy_dict)
            # Apply migrations and default parameters
            _ensure_default_params(strategy_dict)

            # Flexible parsing: support with or without config_data wrapper
            if "config_data" in strategy_dict and isinstance(
                strategy_dict["config_data"], dict
            ):
                config_data_to_validate = strategy_dict["config_data"]
                logger.debug(
                    "Generator mode: AI response contains 'config_data' wrapper"
                )
            elif "filters" in strategy_dict or "entryConditions" in strategy_dict:
                config_data_to_validate = strategy_dict
                logger.debug("AI response is direct strategy config (no wrapper)")
            else:
                config_data_to_validate = (
                    strategy_dict  # Fallback for backward compatibility
                )

            # Add required fields
            if "enabled" not in config_data_to_validate:
                config_data_to_validate["enabled"] = True
            if "strategy_name" not in config_data_to_validate:
                config_data_to_validate["strategy_name"] = "VisualBuilderStrategy"
            if "signal_source" not in config_data_to_validate:
                config_data_to_validate["signal_source"] = "internal"

            validated_config = schemas.StrategyV2ConfigData.model_validate(
                config_data_to_validate
            )
            strategy_json = validated_config.model_dump(exclude_unset=True)

            logger.info(
                f"Generator mode: Strategy generated/modified for session {session_id}"
            )

            return schemas.AIChatResponse(
                text_response="Configuration generated successfully.",
                strategy_json=strategy_json,
                session_id=session_id,
            )

        except Exception as e:
            logger.error(
                f"Error during Strategy PRO generation for user {user.id}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail=f"An error occurred while generating the strategy: {e}",
            )

    # ==========================================================================
    # ADVISOR MODE (FLASH MODEL)
    # ==========================================================================
    else:  # mode == 'advisor'
        if not CACHED_ADVISOR_TEMPLATE:
            logger.error(
                "AI Advisor (Flash) prompt template is not cached. Cannot proceed."
            )
            raise ConnectionError("AI Advisor prompt is not ready.")

        context_block = (
            "# The user is asking a general question without specific context."
        )

        db_history = await crud.get_chat_history(db, user.id, session_id)
        logger.info(
            f"Retrieved {len(db_history)} messages from DB for session {session_id}"
        )

        messages_for_gemini = []
        messages_for_provider = []

        for msg in db_history:
            gemini_role = "model" if msg.role == "assistant" else msg.role
            messages_for_gemini.append({"role": gemini_role, "parts": [msg.content]})
            messages_for_provider.append({"role": msg.role, "content": msg.content})

        market_context_str = await enrich_market_context_for_ai(request.text_prompt)
        if market_context_str:
            messages_for_gemini.append({"role": "user", "parts": [market_context_str]})
            messages_for_provider.append(
                {"role": "user", "content": market_context_str}
            )
            logger.info("Advisor mode: Injected market RAG context.")

        tier_context = _build_tier_context_message(user, is_advisor=True)
        messages_for_gemini.append({"role": "system", "parts": [tier_context]})
        messages_for_provider.append({"role": "system", "content": tier_context})

        messages_for_gemini.append({"role": "user", "parts": [request.text_prompt]})
        messages_for_provider.append({"role": "user", "content": request.text_prompt})

        logger.info(f"Advisor mode: Processing message for session {session_id}")

        if request.backtest_id:
            db_run = await crud.get_backtest_run_by_any_id(
                db, user_id=user.id, identity=request.backtest_id
            )
            if db_run:
                combinations_map = defaultdict(
                    lambda: {"pnl": 0.0, "winCount": 0, "totalCount": 0}
                )
                foundations_map = defaultdict(
                    lambda: {"pnl": 0.0, "winCount": 0, "totalCount": 0}
                )

                for trade in db_run.trades:
                    if not trade.decision_trace_json:
                        continue
                    parser = DecisionTraceParser(trade.decision_trace_json)
                    foundations_ids = parser.get_used_foundations()
                    if not foundations_ids:
                        continue

                    combo_key = ",".join(sorted(foundations_ids))
                    combinations_map[combo_key]["pnl"] += trade.pnl
                    combinations_map[combo_key]["totalCount"] += 1
                    if trade.pnl > 0:
                        combinations_map[combo_key]["winCount"] += 1

                    for found_id in foundations_ids:
                        foundations_map[found_id]["pnl"] += trade.pnl
                        foundations_map[found_id]["totalCount"] += 1
                        if trade.pnl > 0:
                            foundations_map[found_id]["winCount"] += 1

                individual_stats_list = []
                for key, data in foundations_map.items():
                    win_rate = (
                        (data["winCount"] / data["totalCount"]) * 100
                        if data["totalCount"] > 0
                        else 0
                    )
                    individual_stats_list.append(
                        {
                            "foundation": key.replace("w_", ""),
                            "pnl": data["pnl"],
                            "win_rate": win_rate,
                            "trades": data["totalCount"],
                        }
                    )
                individual_stats_list.sort(key=lambda x: x["pnl"], reverse=True)

                ind_headers = ["Foundation ID", "Total PnL", "Win Rate", "Trades"]
                ind_table_lines = [
                    f"| {' | '.join(ind_headers)} |",
                    f"| {' | '.join(['---'] * len(ind_headers))} |",
                ]
                for item in individual_stats_list:
                    ind_table_lines.append(
                        f"| {item['foundation']} | {item['pnl']:.2f} | {item['win_rate']:.1f}% | {item['trades']} |"
                    )
                individual_stats_table_str = (
                    "\n".join(ind_table_lines)
                    if individual_stats_list
                    else "No individual foundation data available."
                )

                combo_stats_list = []
                for key, data in combinations_map.items():
                    win_rate = (
                        (data["winCount"] / data["totalCount"]) * 100
                        if data["totalCount"] > 0
                        else 0
                    )
                    combo_stats_list.append(
                        {
                            "combination": key.replace("w_", ""),
                            "pnl": data["pnl"],
                            "win_rate": win_rate,
                            "trades": data["totalCount"],
                        }
                    )
                combo_stats_list.sort(key=lambda x: x["pnl"], reverse=True)

                combo_headers = ["Combination IDs", "Total PnL", "Win Rate", "Trades"]
                combo_table_lines = [
                    f"| {' | '.join(combo_headers)} |",
                    f"| {' | '.join(['---'] * len(combo_headers))} |",
                ]
                for item in combo_stats_list:
                    combo_table_lines.append(
                        f"| {item['combination']} | {item['pnl']:.2f} | {item['win_rate']:.1f}% | {item['trades']} |"
                    )
                combo_table_str = (
                    "\n".join(combo_table_lines)
                    if combo_stats_list
                    else "No foundation combinations data available."
                )

                best_trades = sorted(
                    [t for t in db_run.trades if t.pnl > 0],
                    key=lambda x: x.pnl,
                    reverse=True,
                )[:5]
                best_trades_str = (
                    "\n".join(
                        [
                            f"- Trade at {bt.timestamp_exit.strftime('%Y-%m-%d %H:%M')}: PnL = +{bt.pnl:.2f}, Reason: {bt.exit_reason}"
                            for bt in best_trades
                        ]
                    )
                    or "No profitable trades found."
                )

                worst_trades = sorted(
                    [t for t in db_run.trades if t.pnl < 0], key=lambda x: x.pnl
                )[:5]
                worst_trades_str = (
                    "\n".join(
                        [
                            f"- Trade at {wt.timestamp_exit.strftime('%Y-%m-%d %H:%M')}: PnL = {wt.pnl:.2f}, Reason: {wt.exit_reason}"
                            for wt in worst_trades
                        ]
                    )
                    or "No losing trades found."
                )

                analytics_report_str = ""
                if db_run.analytics_report_json:
                    analytics_report_str = f"## Structured Analytics Report\nThis report provides counters for events that happened during the backtest, which is crucial for debugging strategies with zero or few trades.\n```json\n{json.dumps(db_run.analytics_report_json, indent=2)}\n```"

                context_block = f"""# Backtest Analysis Context
## Strategy JSON```json
{json.dumps(db_run.parameters_json, indent=2)}
```
## Overall KPIs
```json
{json.dumps(db_run.kpi_results_json, indent=2)}
```
{analytics_report_str}
## Individual Foundation Stats
This table shows the performance of each foundation block across all trades it participated in. Use this to identify strong and weak individual components.
{individual_stats_table_str}
## Foundation Combination Stats
This table shows the performance of specific groups of foundations that triggered trades. Use this to find powerful synergies or conflicting combinations.
{combo_table_str}
## 5 Best Performing Trades
{best_trades_str}
## 5 Worst Performing Trades
{worst_trades_str}
"""

        if request.analytics_context:
            logger.info("Advisor mode: Processing real trade analytics context.")
            analytics_md = "# Live Trading Analytics Context\n"

            if "kpis" in request.analytics_context:
                analytics_md += (
                    "## Overall KPIs\n```json\n"
                    + json.dumps(request.analytics_context["kpis"], indent=2)
                    + "\n```\n"
                )

            if "strategy_json" in request.analytics_context:
                analytics_md += (
                    "## Strategy Configuration\n```json\n"
                    + json.dumps(request.analytics_context["strategy_json"], indent=2)
                    + "\n```\n"
                )

            if (
                "top_trades" in request.analytics_context
                and request.analytics_context["top_trades"]
            ):
                analytics_md += "## Top 5 Best Trades\n"
                for t in request.analytics_context["top_trades"]:
                    analytics_md += f"- Trade: PnL = +{t.get('pnl', 0):.2f}, Reason: {t.get('exit_reason')}, Symbol: {t.get('symbol')}\n"

            if (
                "bottom_trades" in request.analytics_context
                and request.analytics_context["bottom_trades"]
            ):
                analytics_md += "## Top 5 Worst Trades\n"
                for t in request.analytics_context["bottom_trades"]:
                    analytics_md += f"- Trade: PnL = {t.get('pnl', 0):.2f}, Reason: {t.get('exit_reason')}, Symbol: {t.get('symbol')}\n"

            context_block = analytics_md

        if (
            context_block
            != "# The user is asking a general question without specific context."
        ):
            messages_for_gemini.insert(-1, {"role": "user", "parts": [context_block]})
            messages_for_provider.insert(-1, {"role": "user", "content": context_block})

        try:
            import sys

            messages_size = sys.getsizeof(str(messages_for_provider))
            logger.info(
                f"Sending {len(messages_for_provider)} messages to {active_provider}. Total size: {messages_size} bytes."
            )

            text_response = await _generate_text_response(
                CACHED_ADVISOR_TEMPLATE,
                messages_for_provider,
                image_base64=request.image_base64,
                image_mime_type=request.image_mime_type,
            )

            if contains_python_code(text_response):
                logger.warning(
                    f"Potential Python code leak detected in AI response for user {user.id}. "
                    f"Blocking response."
                )
                safe_response_text = "I apologize, but I was unable to generate a valid response that adheres to security policies. Could you please rephrase your request to focus on concepts or usage, rather than implementation details?"
                return schemas.AIChatResponse(
                    text_response=safe_response_text,
                    strategy_json=None,
                    session_id=session_id,
                )

            logger.info(f"Advisor mode: Response generated for session {session_id}")
            return schemas.AIChatResponse(
                text_response=text_response, strategy_json=None, session_id=session_id
            )

        except Exception as e:
            logger.error(
                f"Error during advisor call for user {user.id}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=503, detail=f"An error occurred with the AI assistant: {e}"
            )


from .mcp_memory_server import get_mcp_client

# Mapping from JSON Schema types to Gemini types for MCP tool conversion
_JSON_TYPE_TO_GEMINI = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _mcp_schema_to_gemini(schema: dict) -> Any:
    """Recursively convert MCP JSON Schema to Gemini Schema using strict Enum types."""
    schema = schema or {}
    raw_type = schema.get("type", "").upper()

    if raw_type == "OBJECT":
        gemini_type = types.Type.OBJECT if types else "OBJECT"
    elif raw_type == "ARRAY":
        gemini_type = types.Type.ARRAY if types else "ARRAY"
    elif raw_type == "INTEGER":
        gemini_type = types.Type.INTEGER if types else "INTEGER"
    elif raw_type == "NUMBER":
        gemini_type = types.Type.NUMBER if types else "NUMBER"
    elif raw_type == "BOOLEAN":
        gemini_type = types.Type.BOOLEAN if types else "BOOLEAN"
    else:
        gemini_type = types.Type.STRING if types else "STRING"

    kwargs = {"type": gemini_type}

    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "enum" in schema:
        kwargs["enum"] = schema["enum"]
    if "required" in schema:
        kwargs["required"] = schema["required"]

    if raw_type == "ARRAY" and "items" in schema:
        kwargs["items"] = _mcp_schema_to_gemini(schema["items"])

    if raw_type == "OBJECT" and "properties" in schema:
        kwargs["properties"] = {
            k: _mcp_schema_to_gemini(v) for k, v in schema["properties"].items()
        }

    if types is not None:
        return types.Schema(**kwargs)
    return kwargs


def _mcp_tool_to_openrouter(mcp_tool: dict) -> dict:
    """Convert MCP tool definition to OpenRouter/Qwen function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {}),
        },
    }


def _mcp_tools_to_gemini_tool(mcp_tools: list) -> dict:
    """Convert MCP tool definitions to a Gemini-compatible dict."""
    declarations = []
    for tool in mcp_tools:
        schema = tool.get("inputSchema", {})
        declarations.append(
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": _mcp_schema_to_gemini(schema),
            }
        )
    return {"function_declarations": declarations}


async def generate_strategy_json_from_prompt(
    request: schemas.GenerateStrategyRequest,
    current_user: models.User,
    websocket: Optional[WebSocket] = None,
) -> Dict[str, Any]:
    """
    Processes user request, interacts with Gemini, and returns strategy JSON.
    """
    global CACHED_GENERATOR_PROMPT
    active_provider = _ensure_ai_provider_configured()

    market_context_str = await enrich_market_context_for_ai(request.text_prompt)

    if CACHED_GENERATOR_PROMPT is None:
        logger.warning("AI system prompt was not cached. Building it on-demand.")
        build_and_cache_prompts()

    if websocket:
        # Autopilot mode: use dedicated prompt with STANDARD blocks only (no PRO/kline)
        session_generator_prompt = load_prompt("autopilot_generator_system.md")
    else:
        session_generator_prompt = CACHED_GENERATOR_PROMPT

    if websocket:
        # Inject the Agent Memory & Tools block dynamically.
        # Query active tags dynamically from the database
        from sqlalchemy import select
        from .database import async_session_factory

        try:
            async with async_session_factory() as db_session:
                result = await db_session.execute(
                    select(models.AgentMemory.tags).where(
                        models.AgentMemory.user_id == current_user.id
                    )
                )
                tag_rows = result.scalars().all()
                unique_tags = set()
                for t_list in tag_rows:
                    if t_list:
                        for t in t_list:
                            if isinstance(t, str):
                                unique_tags.add(t.strip().lower())

                tags_str = ", ".join(f"'{t}'" for t in sorted(list(unique_tags)))
                if not tags_str:
                    tags_str = "'breakout', 'reversion', 'trend', 'scalping'"
        except Exception as e:
            logger.error(f"Error querying tags dynamically: {e}", exc_info=True)
            tags_str = "'breakout', 'reversion', 'trend', 'scalping'"

        if getattr(request, "memory_summary", None):
            agent_block = f"""
# MEMORIES & RULES
Below is a synthesized summary of past trading results, successful rules, and common failure patterns for this asset.
You MUST strictly adhere to these guidelines and avoid the specified negative patterns:
{request.memory_summary}
"""
        else:
            agent_block = f"""
# AGENT MEMORY & TOOLS
- You have access to the `search_agent_memory` tool provided by the MCP Memory Server.
- You MUST call `search_agent_memory` EXACTLY ONCE on your first turn.
- CRITICAL: DO NOT call the search tool multiple times. After receiving the search results, you MUST immediately output the final Strategy JSON configuration.
- To immediately find the best performing past strategies, always include `outcome='success'` in your search query!
- Current VALID tags in your database: [{tags_str}].
- STRICT RULE: When calling `search_agent_memory`, you MUST ONLY use tags from the valid list above. DO NOT invent new tags.
"""
        if "# SUBSCRIPTION & ENGINE CONSTRAINTS" in session_generator_prompt:
            session_generator_prompt = session_generator_prompt.replace(
                "# SUBSCRIPTION & ENGINE CONSTRAINTS",
                agent_block + "\n# SUBSCRIPTION & ENGINE CONSTRAINTS",
            )
        elif "# ENGINE CONSTRAINT" in session_generator_prompt:
            session_generator_prompt = session_generator_prompt.replace(
                "# ENGINE CONSTRAINT",
                agent_block + "\n# ENGINE CONSTRAINT",
            )
        else:
            session_generator_prompt = agent_block + "\n" + session_generator_prompt

    if active_provider in ("openrouter", "qwen"):
        user_prompt_parts = [f"USER PROMPT: '{request.text_prompt}'"]
        if market_context_str:
            user_prompt_parts.insert(0, market_context_str)
        user_prompt_parts.append(
            _build_tier_context_message(current_user, is_advisor=False)
        )
        if request.current_config_json:
            user_prompt_parts.append(
                "\n\n# CURRENT STRATEGY CONFIGURATION (modify this based on the new prompt):"
            )
            config_to_send = request.current_config_json.copy()
            config_to_send.pop("id", None)
            config_to_send.pop("user_id", None)
            config_to_send.pop("created_at", None)
            config_to_send.pop("updated_at", None)
            user_prompt_parts.append(json.dumps(config_to_send, indent=2))

        # Initialize MCP client for dynamic tool discovery
        mcp_client = await get_mcp_client()
        mcp_tools = mcp_client.tools
        tools_schema = [_mcp_tool_to_openrouter(t) for t in mcp_tools]
        first_tool_name = mcp_tools[0]["name"] if mcp_tools else "search_agent_memory"

        full_user_prompt = "\n".join(user_prompt_parts)

        user_content: Any = full_user_prompt
        normalized_image, normalized_mime = _normalize_image_payload(
            request.image_base64, request.image_mime_type
        )
        if normalized_image and normalized_mime:
            user_content = [
                {"type": "text", "text": full_user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{normalized_mime};base64,{normalized_image}"
                    },
                },
            ]

        messages = [
            {"role": "system", "content": session_generator_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            raw_response_text = ""
            model_thinking = ""
            for turn in range(5):
                payload = {
                    "model": _get_qwen_model_name()
                    if active_provider == "qwen"
                    else _get_openrouter_model_name(),
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0.7,
                }

                if turn == 0 and not getattr(request, "memory_summary", None):
                    payload["tools"] = tools_schema
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": first_tool_name},
                    }
                else:
                    payload["response_format"] = {"type": "json_object"}

                api_url = (
                    os.getenv("QWEN_API_URL", DEFAULT_QWEN_URL).strip()
                    or DEFAULT_QWEN_URL
                )
                api_key = os.getenv("QWEN_API_KEY", "").strip()
                if active_provider == "openrouter":
                    api_url = (
                        os.getenv("OPENROUTER_API_URL", DEFAULT_OPENROUTER_URL).strip()
                        or DEFAULT_OPENROUTER_URL
                    )
                    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

                if not api_key:
                    raise ConnectionError(
                        f"{active_provider.upper()}_API_KEY is not configured."
                    )

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                if active_provider == "openrouter":
                    headers.update(_build_openrouter_headers())

                logger.info(f"Sending {active_provider} request, turn {turn}...")
                timeout_seconds = float(
                    os.getenv("QWEN_TIMEOUT_SECONDS", str(DEFAULT_QWEN_TIMEOUT_SECONDS))
                )
                if active_provider == "openrouter":
                    timeout_seconds = float(
                        os.getenv(
                            "OPENROUTER_TIMEOUT_SECONDS",
                            str(DEFAULT_OPENROUTER_TIMEOUT_SECONDS),
                        )
                    )

                async with httpx.AsyncClient(timeout=timeout_seconds) as http_client:
                    response = await http_client.post(
                        api_url, headers=headers, json=payload
                    )
                    response.raise_for_status()
                    res_data = response.json()

                choices = res_data.get("choices") or []
                if not choices:
                    raise ValueError(
                        f"{active_provider.upper()} API returned no choices."
                    )

                choice_msg = choices[0].get("message") or {}
                tool_calls = choice_msg.get("tool_calls")
                text_content = choice_msg.get("content") or ""

                turn_reasoning = (
                    choice_msg.get("reasoning")
                    or choice_msg.get("reasoning_content")
                    or ""
                )
                if turn_reasoning:
                    model_thinking = turn_reasoning

                text_tool_call = None
                if turn == 0 and not tool_calls and text_content:
                    match = re.search(
                        r"call:(?:default_api:)?search_agent_memory\s*(\{.*?\})",
                        text_content,
                        re.DOTALL,
                    )
                    if match:
                        args_str = match.group(1)
                        try:
                            args = json.loads(args_str)
                        except Exception:
                            cleaned_args_str = re.sub(r"(\w+)\s*:", r'"\1":', args_str)
                            try:
                                args = json.loads(cleaned_args_str)
                            except Exception:
                                args = {}
                        text_tool_call = {
                            "name": "search_agent_memory",
                            "arguments": args,
                        }

                if not tool_calls and not text_tool_call:
                    raw_response_text = text_content
                    break

                if tool_calls:
                    tool_calls = tool_calls[:1]
                    logger.info(
                        f"{active_provider.upper()} requested native tool calls: {[t.get('function', {}).get('name') for t in tool_calls]}"
                    )
                    if websocket:
                        try:
                            tool_names = [
                                t.get("function", {}).get("name") for t in tool_calls
                            ]
                            await websocket.send_json(
                                {
                                    "event": "autopilot_status",
                                    "status": "loading_data",
                                    "message": f"🤖 AI Agent ({active_provider}): Querying memory bank via MCP tool '{tool_names[0]}'",
                                }
                            )
                        except Exception:
                            pass

                    messages.append(choice_msg)
                    for tc in tool_calls:
                        tc_id = tc.get("id")
                        tc_func = tc.get("function") or {}
                        tc_name = tc_func.get("name")
                        tc_args_str = tc_func.get("arguments") or "{}"
                        try:
                            tc_args = json.loads(tc_args_str)
                        except Exception:
                            tc_args = {}
                        tc_args["user_id"] = current_user.id
                        result_text = await mcp_client.call_tool(tc_name, tc_args)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": tc_name,
                                "content": result_text,
                            }
                        )
                else:
                    logger.info(
                        f"{active_provider.upper()} requested text-based tool call fallback: {text_tool_call['name']}"
                    )
                    if websocket:
                        try:
                            await websocket.send_json(
                                {
                                    "event": "autopilot_status",
                                    "status": "loading_data",
                                    "message": f"🤖 AI Agent ({active_provider}): Querying memory bank via MCP tool '{text_tool_call['name']}' (text fallback)",
                                }
                            )
                        except Exception:
                            pass
                    messages.append(choice_msg)
                    tc_args = text_tool_call["arguments"]
                    tc_args["user_id"] = current_user.id
                    result_text = await mcp_client.call_tool(
                        text_tool_call["name"], tc_args
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[System: search_agent_memory results]\n{result_text}\n\nBased on these memories, please proceed with generating the strategy configuration JSON.",
                        }
                    )

            if model_thinking and websocket:
                try:
                    await websocket.send_json(
                        {
                            "event": "autopilot_status",
                            "status": "thinking",
                            "message": f"🧠 {model_thinking}",
                        }
                    )
                except Exception:
                    pass

            # JSON parsing and validation
            json_start_index = raw_response_text.find("{")
            json_end_index = raw_response_text.rfind("}")
            if (
                json_start_index == -1
                or json_end_index == -1
                or json_end_index < json_start_index
            ):
                raise ValueError(
                    f"Could not find a valid JSON structure in the AI's response. Raw text: {raw_response_text}"
                )

            clean_json_text = raw_response_text[json_start_index : json_end_index + 1]
            logger.debug(f"Extracted clean JSON part for parsing: {clean_json_text}")

            try:
                strategy_dict = json.loads(clean_json_text)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode the extracted JSON part. Error: {e}")
                raise ValueError(
                    f"The AI returned a malformed JSON object. Details: {e}. Content: {clean_json_text}"
                )

            _sanitize_strategy_nulls(strategy_dict)
            _ensure_default_params(strategy_dict)

            if "config_data" in strategy_dict and isinstance(
                strategy_dict["config_data"], dict
            ):
                config_data_to_validate = strategy_dict["config_data"]
            elif "filters" in strategy_dict or "entryConditions" in strategy_dict:
                config_data_to_validate = strategy_dict
            else:
                raise ValueError(
                    "AI response does not contain valid strategy structure (missing 'config_data' or 'filters'/'entryConditions')."
                )

            for field in ("enabled", "strategy_name", "signal_source"):
                if field not in config_data_to_validate:
                    defaults = {
                        "enabled": True,
                        "strategy_name": "VisualBuilderStrategy",
                        "signal_source": "internal",
                    }
                    logger.warning(
                        f"AI response was missing '{field}' field. Injecting default: {defaults[field]}."
                    )
                    config_data_to_validate[field] = defaults[field]

            if "filters" in config_data_to_validate and isinstance(
                config_data_to_validate["filters"], list
            ):
                logger.info("Migrating filters from list to AND-ConditionNode")
                config_data_to_validate["filters"] = {
                    "type": "AND",
                    "children": config_data_to_validate["filters"],
                }

            logger.warning(
                f"[{active_provider} JSON Output] Config to validate: {json.dumps(config_data_to_validate, indent=2, ensure_ascii=False)}"
            )
            validated_config_data = schemas.StrategyV2ConfigData.model_validate(
                config_data_to_validate
            )

            if validated_config_data.unsupported_features:
                logger.info(
                    f"[AI_FEEDBACK] User: '{request.text_prompt[:100]}...' | AI Comments: {validated_config_data.unsupported_features}"
                )

            response_dict = validated_config_data.model_dump(exclude_unset=True)
            response_dict.pop("unsupported_features", None)
            _validate_generated_strategy_for_user(response_dict, current_user)

            return response_dict
        except Exception as e:
            logger.error(
                f"Error during {active_provider} generation, parsing, or validation: {e}",
                exc_info=True,
            )
            if "AI could not generate" in str(e) or "Your request was blocked" in str(
                e
            ):
                raise e
            raise ValueError(
                f"Failed to generate a valid strategy from the prompt. Please try to rephrase your request. Error: {e}"
            )
    try:
        _ensure_google_client_configured()
        client = _get_gemini_client()
        model_name = _get_google_model_name() or "gemini-3-flash-preview"
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        raise ConnectionError(f"Could not initialize Gemini client: {e}")

    user_prompt_parts = [f"USER PROMPT: '{request.text_prompt}'"]
    if market_context_str:
        user_prompt_parts.insert(0, market_context_str)

    user_prompt_parts.append(
        _build_tier_context_message(current_user, is_advisor=False)
    )

    if request.current_config_json:
        user_prompt_parts.append(
            "\n\n# CURRENT STRATEGY CONFIGURATION (modify this based on the new prompt):"
        )
        config_to_send = request.current_config_json.copy()
        config_to_send.pop("id", None)
        config_to_send.pop("user_id", None)
        config_to_send.pop("created_at", None)
        config_to_send.pop("updated_at", None)
        user_prompt_parts.append(json.dumps(config_to_send, indent=2))

    full_user_prompt = "\n".join(user_prompt_parts)

    try:
        logger.info(
            f"Sending request to Gemini with prompt: {full_user_prompt[:500]}..."
        )

        # Initialize MCP client for dynamic tool discovery
        gemini_mcp_client = await get_mcp_client()
        gemini_tools = gemini_mcp_client.tools
        gemini_tool_obj = _mcp_tools_to_gemini_tool(gemini_tools)
        first_tool_name = (
            gemini_tools[0]["name"] if gemini_tools else "search_agent_memory"
        )

        contents: list[Any] = [full_user_prompt]
        normalized_image, normalized_mime = _normalize_image_payload(
            request.image_base64, request.image_mime_type
        )
        if normalized_image and normalized_mime:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(normalized_image), mime_type=normalized_mime
                )
            )

        model_thinking = ""
        has_tools = (
            gemini_tool_obj
            and "function_declarations" in gemini_tool_obj
            and bool(gemini_tool_obj["function_declarations"])
            and not getattr(request, "memory_summary", None)
        )

        for turn in range(5):
            config_args: dict = {
                "max_output_tokens": 8192,
                "system_instruction": session_generator_prompt,
                "temperature": 0.7,
            }
            if turn == 0:
                if has_tools:
                    config_args["tools"] = [gemini_tool_obj]
                    config_args["tool_config"] = {
                        "function_calling_config": {
                            "mode": "ANY",
                            "allowed_function_names": [first_tool_name],
                        }
                    }
                else:
                    config_args["response_mime_type"] = "application/json"
            else:
                config_args["response_mime_type"] = "application/json"

            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config_args,
            )

            function_calls = getattr(response, "function_calls", None)

            text_tool_call = None
            first_candidate = response.candidates[0] if response.candidates else None
            text_content = ""
            if (
                first_candidate
                and first_candidate.content
                and first_candidate.content.parts
            ):
                text_content = "".join(
                    p.text
                    for p in first_candidate.content.parts
                    if hasattr(p, "text") and p.text
                )
                turn_thinking = " ".join(
                    p.text
                    for p in first_candidate.content.parts
                    if getattr(p, "thought", None) is True and p.text
                )
                if turn_thinking:
                    model_thinking = turn_thinking

            if turn == 0 and not function_calls and text_content:
                match = re.search(
                    r"call:(?:default_api:)?search_agent_memory\s*(\{.*?\})",
                    text_content,
                    re.DOTALL,
                )
                if match:
                    args_str = match.group(1)
                    try:
                        args = json.loads(args_str)
                    except Exception:
                        cleaned_args_str = re.sub(r"(\w+)\s*:", r'"\1":', args_str)
                        try:
                            args = json.loads(cleaned_args_str)
                        except Exception:
                            args = {}
                    text_tool_call = {"name": "search_agent_memory", "arguments": args}

            if not function_calls and not text_tool_call:
                break

            if function_calls:
                function_calls = function_calls[:1]
                logger.info(
                    f"Gemini requested tool calls: {[f.name for f in function_calls]}"
                )
                if websocket:
                    try:
                        tool_names = [f.name for f in function_calls]
                        await websocket.send_json(
                            {
                                "event": "autopilot_status",
                                "status": "loading_data",
                                "message": f"🤖 AI Agent: Querying memory bank via MCP tool '{tool_names[0]}'",
                            }
                        )
                    except Exception:
                        pass

                tool_response_parts = []
                for function_call in function_calls:
                    name = function_call.name
                    args = dict(function_call.args or {})
                    args["user_id"] = current_user.id
                    result_text = await gemini_mcp_client.call_tool(name, args)

                    if websocket:
                        try:
                            if "No matching" in result_text:
                                ws_msg = "ℹ️ Recall Synapses: No matching memories found (Bank is empty for these tags)."
                            else:
                                count = result_text.count("\n- ")
                                ws_msg = f"🧠 Recall Synapses: Retrieved {count} relevant memories from the agent memory bank."
                            await websocket.send_json(
                                {
                                    "event": "autopilot_status",
                                    "status": "loading_data",
                                    "message": ws_msg,
                                }
                            )
                        except Exception:
                            pass
                    tool_response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=name, response={"result": result_text}
                            )
                        )
                    )
                if response.candidates and response.candidates[0].content:
                    contents.append(response.candidates[0].content)
                contents.append(types.Content(role="user", parts=tool_response_parts))
            else:
                logger.info(
                    f"Gemini requested text-based tool call fallback: {text_tool_call['name']}"
                )
                if websocket:
                    try:
                        await websocket.send_json(
                            {
                                "event": "autopilot_status",
                                "status": "loading_data",
                                "message": f"🤖 AI Agent: Querying memory bank via MCP tool '{text_tool_call['name']}' (text fallback)",
                            }
                        )
                    except Exception:
                        pass
                if response.candidates and response.candidates[0].content:
                    contents.append(response.candidates[0].content)
                tc_args = text_tool_call["arguments"]
                tc_args["user_id"] = current_user.id
                result_text = await gemini_mcp_client.call_tool(
                    text_tool_call["name"], tc_args
                )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text=f"[System: search_agent_memory results]\n{result_text}\n\nBased on these memories, please proceed with generating the strategy configuration JSON."
                            )
                        ],
                    )
                )

        if model_thinking and websocket:
            try:
                await websocket.send_json(
                    {
                        "event": "autopilot_status",
                        "status": "thinking",
                        "message": f"🧠 {model_thinking}",
                    }
                )
            except Exception:
                pass

        # 1. Check if there are any candidates in the response. If not, the prompt is blocked.
        if not response.candidates:
            prompt_feedback = getattr(response, "prompt_feedback", None)
            finish_reason = "UNKNOWN"
            if prompt_feedback and getattr(prompt_feedback, "block_reason", None):
                finish_reason = getattr(
                    prompt_feedback.block_reason,
                    "name",
                    str(prompt_feedback.block_reason),
                )
            safety_ratings_info = (
                getattr(prompt_feedback, "safety_ratings", [])
                if prompt_feedback
                else []
            )
            logger.error(
                f"Gemini response has no candidates. Prompt blocked. Reason: {finish_reason}. Safety ratings: {safety_ratings_info}"
            )
            raise ValueError(
                f"Your request was blocked by AI safety filters (at the prompt level). Please try to rephrase it. Reason: {finish_reason}."
            )

        first_candidate = response.candidates[0]

        # 2. Check why generation stopped.
        finish_reason = getattr(first_candidate, "finish_reason", "STOP")
        finish_reason_str = str(finish_reason).upper()

        if "STOP" not in finish_reason_str:
            if "MALFORMED_FUNCTION_CALL" in finish_reason_str:
                logger.warning(
                    "Gemini hallucinated a malformed function call. Skipping memory search."
                )
                return await _generate_json_response(
                    session_generator_prompt,
                    full_user_prompt,
                    image_base64=request.image_base64,
                    image_mime_type=request.image_mime_type,
                )

            safety_ratings_info = getattr(first_candidate, "safety_ratings", [])
            logger.error(
                f"Gemini generation did not finish normally. Reason: {finish_reason_str}. Safety ratings: {safety_ratings_info}"
            )
            raise ValueError(
                f"AI could not generate a complete response. Generation was interrupted due to: '{finish_reason_str}'. Try simplifying the request."
            )

        # 3. Safely extract the text part of the response.
        raw_response_text = None
        if first_candidate.content and first_candidate.content.parts:
            for part in first_candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    raw_response_text = part.text
                    break

        if raw_response_text is None:
            finish_reason = "UNKNOWN"
            if getattr(first_candidate, "finish_reason", None):
                finish_reason = str(first_candidate.finish_reason).upper()
            safety_ratings_info = getattr(first_candidate, "safety_ratings", [])
            logger.error(
                f"Gemini candidate content has no text part. Generation blocked. Reason: {finish_reason}. Safety ratings: {safety_ratings_info}"
            )
            raise ValueError(
                f"AI could not generate a text response (the content may have been blocked). Reason: {finish_reason}."
            )

        logger.debug(f"Received raw response from Gemini: {raw_response_text}")

        # The code below remains unchanged, but now it will operate on a guaranteed complete JSON
        json_start_index = raw_response_text.find("{")
        json_end_index = raw_response_text.rfind("}")

        if (
            json_start_index == -1
            or json_end_index == -1
            or json_end_index < json_start_index
        ):
            raise ValueError(
                f"Could not find a valid JSON structure in the AI's response. Raw text: {raw_response_text}"
            )

        clean_json_text = raw_response_text[json_start_index : json_end_index + 1]
        logger.debug(f"Extracted clean JSON part for parsing: {clean_json_text}")

        try:
            strategy_dict = json.loads(clean_json_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode the extracted JSON part. Error: {e}")
            raise ValueError(
                f"The AI returned a malformed JSON object. Details: {e}. Content: {clean_json_text}"
            )

        _sanitize_strategy_nulls(strategy_dict)
        _ensure_default_params(strategy_dict)

        # Flexible parsing: support with or without config_data wrapper
        if "config_data" in strategy_dict and isinstance(
            strategy_dict["config_data"], dict
        ):
            config_data_to_validate = strategy_dict["config_data"]
            logger.debug("AI response contains 'config_data' wrapper")
        elif "filters" in strategy_dict or "entryConditions" in strategy_dict:
            config_data_to_validate = strategy_dict
            logger.debug("AI response is direct strategy config (no wrapper)")
        else:
            raise ValueError(
                "AI response does not contain valid strategy structure (missing 'config_data' or 'filters'/'entryConditions')."
            )

        if "enabled" not in config_data_to_validate:
            logger.warning(
                "AI response was missing 'enabled' field. Injecting default: True."
            )
            config_data_to_validate["enabled"] = True
        if "strategy_name" not in config_data_to_validate:
            logger.warning(
                "AI response was missing 'strategy_name' field. Injecting default: 'VisualBuilderStrategy'."
            )
            config_data_to_validate["strategy_name"] = "VisualBuilderStrategy"
        if "signal_source" not in config_data_to_validate:
            logger.warning(
                "AI response was missing 'signal_source' field. Injecting default: 'internal'."
            )
            config_data_to_validate["signal_source"] = "internal"

        validated_config_data = schemas.StrategyV2ConfigData.model_validate(
            config_data_to_validate
        )

        if validated_config_data.unsupported_features:
            logger.info(
                f"[AI_FEEDBACK] User: '{request.text_prompt[:100]}...' | AI Comments: {validated_config_data.unsupported_features}"
            )

        response_dict = validated_config_data.model_dump(exclude_unset=True)
        response_dict.pop("unsupported_features", None)
        _validate_generated_strategy_for_user(response_dict, current_user)

        return response_dict

    except Exception as e:
        logger.error(
            f"Error during Gemini generation, parsing, or validation: {e}",
            exc_info=True,
        )
        # Improve error handling for the user
        if "AI could not generate" in str(e) or "Your request was blocked" in str(e):
            raise e  # Pass through our custom, understandable errors
        else:
            # General error for all other cases
            raise ValueError(
                f"Failed to generate a valid strategy from the prompt. Please try to rephrase your request. Error: {e}"
            )
