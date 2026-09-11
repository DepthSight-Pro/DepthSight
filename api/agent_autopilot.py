# api/agent_autopilot.py

import asyncio
import logging
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import WebSocket

from api.database import async_session_factory
from api import crud, models, schemas, ai_assistant
from api.ai_assistant import _generate_json_response

logger = logging.getLogger(__name__)


def clean_double_newlines(text: str) -> str:
    """Helper to clean up excessive spacing (3+ newlines) from LLM output,
    ensuring neat markdown presentation on the frontend."""
    if not text:
        return ""
    # Standardize all double newlines to single \n\n, removing 3+ sequences
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Also standardize CRLF if any
    text = re.sub(r"(\r\n){3,}", "\r\n\r\n", text)
    return text


def guess_symbol_from_prompt(prompt: str, default: str = "BTCUSDT") -> str:
    """Fast regex check to extract symbols if they are explicitly mentioned (e.g. 'BTC', 'ETHUSDT').
    Returns empty string if not explicitly matched, signaling that LLM resolution is needed."""
    prompt_upper = prompt.upper()

    # Match exact patterns like BTCUSDT, ETH-USDT, etc.
    pair_match = re.search(r"\b([A-Z]{2,10})(?:/|-)?USDT\b", prompt_upper)
    if pair_match:
        return f"{pair_match.group(1)}USDT"

    # Match common base tickers directly as a fallback (if they stand as separate words)
    common_tickers = [
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "DOGE",
        "LTC",
        "LINK",
        "DOT",
        "AVAX",
        "SUI",
        "APT",
        "PEPE",
        "TON",
    ]
    for ticker in common_tickers:
        if re.search(r"\b" + ticker + r"\b", prompt_upper):
            return f"{ticker}USDT"

    return ""


async def resolve_symbol_with_llm(
    user_prompt: str,
    available_symbols: Optional[list[str]] = None,
    default: str = "BTCUSDT",
) -> str:
    """Resolves target trading asset from prompt. Fast-tracks explicit tickers,
    and delegates any ambiguous, slang, or translated names (like 'биток', 'эфир') to the LLM."""
    # 1. Fast regex lookup for explicit tickers
    fast_match = guess_symbol_from_prompt(user_prompt, default="")
    if fast_match:
        if available_symbols and fast_match not in available_symbols:
            # Check if stripped match or prefix exists in storage
            matched = next(
                (
                    s
                    for s in available_symbols
                    if s == fast_match or s.startswith(fast_match.replace("USDT", ""))
                ),
                None,
            )
            if matched:
                return matched
        return fast_match

    # 2. LLM resolution for translation / slang / context matching
    avail_str = (
        f" Currently loaded symbols in DepthSight storage: {', '.join(available_symbols[:35])}."
        if available_symbols
        else ""
    )
    try:
        raw = await _generate_json_response(
            system_prompt=(
                "You are an expert crypto trading assistant. "
                f"{avail_str} "
                "Identify the target cryptocurrency from the user prompt and return ONLY a JSON object: "
                '{"symbol": "<BASE>USDT"} where <BASE> is the standard Binance ticker symbol. '
                "Examples: 'биток' -> BTCUSDT, 'эфир' -> ETHUSDT, 'солана' -> SOLUSDT, 'dogecoin' -> DOGEUSDT. "
                "Whenever possible, choose an asset from the available loaded symbols list above. "
                f"If the asset is completely ambiguous or not specified, default to {default}."
            ),
            user_prompt=f"Identify the symbol from this prompt: '{user_prompt}'",
            max_output_tokens=60,
        )
        data = json.loads(raw)
        symbol = data.get("symbol", default).upper().strip()

        # Basic validation of the resolved symbol format
        if symbol and len(symbol) >= 4 and symbol.endswith("USDT"):
            return symbol
    except Exception as e:
        logger.warning(
            f"LLM symbol resolution failed: {e}. Falling back to default '{default}'."
        )

    return default


def _extract_pnl(content: str) -> float:
    """Extracts PnL percentage from memory content string (e.g. 'PnL=12.34%' or 'PnL: 12.34%')."""
    match = re.search(r"PnL[=:]\s*([-\d.]+)", content)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _extract_config(content: str) -> Optional[Dict[str, Any]]:
    """Extracts strategy configuration dictionary from memory content string.
    Supports both standard JSON formatting and Python dictionary string representations.
    """
    match = re.search(r"Config:\s*(\{.*\})", content, re.DOTALL)
    if not match:
        return None
    raw_str = match.group(1).strip()
    try:
        data = json.loads(raw_str)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        import ast

        data = ast.literal_eval(raw_str)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


async def tag_strategy_insight(
    strategy_json: dict, pnl: float, win_rate: float, trades: int, user_id: int
) -> dict:
    # Extract structural blocks for LLM prompt context
    filters = [
        f.get("type") for f in strategy_json.get("filters", {}).get("children", [])
    ]

    def find_types(node):
        res = []
        if isinstance(node, dict):
            t = node.get("type")
            if t:
                res.append(t)
            for v in node.values():
                res.extend(find_types(v))
        elif isinstance(node, list):
            for item in node:
                res.extend(find_types(item))
        return res

    all_blocks = list(set(find_types(strategy_json)))

    from api.crud import search_agent_memories
    from api.database import async_session_factory

    unique_tags = set()
    try:
        async with async_session_factory() as db_session:
            all_memories = await search_agent_memories(
                db_session, user_id=user_id, limit=500
            )
            for m in all_memories:
                if m.tags:
                    for t in m.tags:
                        if isinstance(t, str):
                            unique_tags.add(t.strip().lower())
    except Exception:
        pass

    tags_str = ", ".join(f"'{t}'" for t in sorted(list(unique_tags)))
    if not tags_str:
        tags_str = "'breakout', 'reversion', 'trend', 'scalping'"

    prompt = _load_prompt("tag_insight.md").format(
        symbol=strategy_json.get("symbol"),
        timeframe=strategy_json.get("timeframe"),
        pnl=pnl,
        win_rate=win_rate,
        trades=trades,
        all_blocks=all_blocks,
        tags_str=tags_str,
    )
    try:
        system_prompt = (
            "You are a trading strategy classification AI. Always return strict JSON."
        )
        raw_json = await _generate_json_response(
            system_prompt=system_prompt, user_prompt=prompt, max_output_tokens=1000
        )
        data = json.loads(raw_json)
        return {
            "strategy_type": data.get("strategy_type", "breakout"),
            "tags": data.get("tags", []),
            "outcome": data.get("outcome", "success" if pnl > 0 else "failure"),
            "confidence": data.get("confidence", 0.8),
        }
    except Exception as e:
        logger.error(f"Failed to tag strategy insight using LLM: {e}")
        strategy_type = (
            "breakout" if "breakout" in str(all_blocks).lower() else "mean_reversion"
        )
        fallback_tags = list(
            set([strategy_json.get("symbol", "BTCUSDT"), strategy_type] + filters)
        )
        return {
            "strategy_type": strategy_type,
            "tags": fallback_tags,
            "outcome": "success" if pnl > 0 else "failure",
            "confidence": 0.7,
        }


async def run_rule_synthesis(user_id: int, strategy_type: str):
    async with async_session_factory() as db:
        memories = await crud.search_agent_memories(
            db,
            user_id=user_id,
            strategy_type=strategy_type,
            memory_type="strategy_insight",
            limit=10,
        )
        if len(memories) < 3:
            return

        existing_rules = await crud.search_agent_memories(
            db,
            user_id=user_id,
            strategy_type=strategy_type,
            memory_type="rule",
            limit=10,
        )

        memory_contents = []
        for i, m in enumerate(memories):
            memory_contents.append(f"Insight {i + 1}: {m.content}")

        from api import models
        from sqlalchemy import select

        # Query all unique tags from DB for this user
        unique_tags = set()
        try:
            result = await db.execute(
                select(models.AgentMemory.tags).where(
                    models.AgentMemory.user_id == user_id
                )
            )
            all_tags_list = result.scalars().all()
            for tags_row in all_tags_list:
                if tags_row:
                    for t in tags_row:
                        unique_tags.add(t.strip().lower())
        except Exception:
            pass

        tags_str = ", ".join(f"'{t}'" for t in sorted(list(unique_tags)))
        if not tags_str:
            tags_str = "'breakout', 'reversion', 'trend', 'scalping'"

        rules_str = ""
        if existing_rules:
            rules_str = "\nExisting Rules in Memory Bank:\n" + "\n".join(
                f"- {r.content}" for r in existing_rules
            )

        prompt = _load_prompt("rule_synthesis.md").format(
            memories_count=len(memories),
            strategy_type=strategy_type,
            memories_content=chr(10).join(memory_contents),
            rules_str=rules_str,
            tags_str=tags_str,
        )
        try:
            system_prompt = (
                "You are the DepthSight Memory Manager. Always return strict JSON."
            )
            raw_json = await _generate_json_response(
                system_prompt=system_prompt, user_prompt=prompt, max_output_tokens=1000
            )
            data = json.loads(raw_json)

            rule_content = data.get("rule_content")
            if rule_content and rule_content.strip():
                rule_tags = list(
                    set(data.get("tags", []) + [strategy_type, "rule", "all_symbols"])
                )
                await crud.create_agent_memory(
                    db,
                    user_id=user_id,
                    memory_data=schemas.AgentMemoryCreate(
                        memory_type="rule",
                        content=rule_content,
                        relevance_score=0.95,
                        expires_at=None,
                        tags=rule_tags,
                        strategy_type=strategy_type,
                        confidence=data.get("confidence", 0.8),
                        validated_count=1,
                    ),
                )
                await db.commit()
                logger.info(
                    f"Synthesized new agent rule for {strategy_type}: '{rule_content}'"
                )
        except Exception as e:
            logger.error(f"Rule synthesis failed: {e}")


async def evaluate_rule_lifecycle(
    user_id: int, strategy_json: dict, pnl: float, strategy_type: str
):
    """Reinforces successful rules and deprecates rules that lead to failures."""
    from api.ai_assistant import _generate_json_response

    outcome = "success" if pnl > 0.0 else "failure"

    async with async_session_factory() as db:
        rules = await crud.search_agent_memories(
            db,
            user_id=user_id,
            memory_type="rule",
            strategy_type=strategy_type,
            limit=10,
        )
        if not rules:
            return

        rules_context = "\n".join([f"ID: {r.id} | Content: {r.content}" for r in rules])

        lite_strategy = strategy_json.copy()
        strategy_str = json.dumps(lite_strategy, indent=2)

        prompt = _load_prompt("rule_evaluation.md").format(
            outcome=outcome,
            pnl=pnl,
            strategy_str=strategy_str,
            rules_context=rules_context,
        )

        try:
            system_prompt = "You evaluate rule application. Output strictly JSON."
            raw_json = await _generate_json_response(
                system_prompt=system_prompt, user_prompt=prompt, max_output_tokens=500
            )
            data = json.loads(raw_json)
            applied_ids = data.get("applied_rule_ids", [])

            if not applied_ids:
                return

            for rule in rules:
                if rule.id in applied_ids:
                    if outcome == "success":
                        rule.confidence = min(1.0, rule.confidence + 0.1)
                        rule.validated_count = (rule.validated_count or 0) + 1
                        logger.info(
                            f"Rule {rule.id} reinforced. New conf: {rule.confidence}"
                        )
                    else:
                        is_comm = getattr(rule, "visibility", "private") == "community"
                        penalty = 0.05 if is_comm else 0.2
                        rule.confidence = max(0.0, rule.confidence - penalty)
                        rule.validated_count = (rule.validated_count or 0) - 1
                        logger.info(
                            f"{'Community ' if is_comm else ''}Rule {rule.id} penalized (-{penalty}). New conf: {rule.confidence}"
                        )

                        deprecate_conf = 0.2 if is_comm else 0.3
                        deprecate_count = -5 if is_comm else -2
                        if (
                            rule.confidence <= deprecate_conf
                            or rule.validated_count <= deprecate_count
                        ):
                            logger.warning(
                                f"{'Community ' if is_comm else ''}Rule {rule.id} DEPRECATED due to repeated failures."
                            )
                            rule.expires_at = datetime.now(timezone.utc)

            await db.commit()
        except Exception as e:
            logger.error(f"Failed to evaluate rule lifecycle: {e}")


def _load_prompt(filename: str) -> str:
    filepath = os.path.join(os.path.dirname(__file__), "prompts", filename)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


CRITIC_SYSTEM_PROMPT = _load_prompt("critic_system.md")
MEMORY_RESEARCHER_SYSTEM_PROMPT = _load_prompt("memory_researcher_system.md")
ADVISOR_SYSTEM_PROMPT = _load_prompt("strategy_advisor_system.md")


async def run_memory_researcher_agent(
    user_id: int,
    symbol: str,
    user_prompt: str,
    websocket: WebSocket,
    storage_range_info: str = "",
) -> str:
    """Queries the database for user memories and synthesizes a concise trading summary."""
    from api import crud, models
    from api.database import async_session_factory
    from api.ai_assistant import _generate_text_response
    from sqlalchemy import or_, select

    try:
        # Fetch all unique tags from DB to match against the user prompt
        prompt_tags = []
        async with async_session_factory() as db:
            user_obj = await db.get(models.User, user_id)
            has_community = (
                bool(getattr(user_obj, "share_community_memories", False))
                if user_obj
                else False
            )
            db_tags = set()
            try:
                tag_query = select(models.AgentMemory.tags)
                if has_community:
                    tag_query = tag_query.where(
                        or_(
                            models.AgentMemory.user_id == user_id,
                            models.AgentMemory.visibility == "community",
                        )
                    )
                else:
                    tag_query = tag_query.where(models.AgentMemory.user_id == user_id)
                result = await db.execute(tag_query)
                all_tags_rows = result.scalars().all()
                for tags_row in all_tags_rows:
                    if tags_row:
                        for t in tags_row:
                            db_tags.add(t.strip().lower())
            except Exception as e:
                logger.error(f"Failed to query unique tags in Memory Researcher: {e}")

            # Extract tags present in user prompt
            prompt_lower = user_prompt.lower()
            for t in db_tags:
                if t in prompt_lower:
                    prompt_tags.append(t)

        # Notify UI about tag querying decisions
        if prompt_tags:
            status_message = f"🤖 Memory Researcher Agent: Querying past trading sessions with tags: {prompt_tags}..."
        else:
            status_message = (
                "🤖 Memory Researcher Agent: Querying past trading sessions..."
            )

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": status_message,
            }
        )

        search_tags = prompt_tags if prompt_tags else None

        async with async_session_factory() as db:
            user_obj = await db.get(models.User, user_id)
            has_community = (
                bool(getattr(user_obj, "share_community_memories", False))
                if user_obj
                else False
            )

            # 1. Fetch rules
            rules = await crud.search_agent_memories(
                db,
                user_id=user_id,
                memory_type="rule",
                tags=search_tags,
                limit=10,
                include_community=has_community,
            )
            # 2. Fetch symbol insights
            exact_insights = await crud.search_agent_memories(
                db,
                user_id=user_id,
                memory_type="strategy_insight",
                symbol=symbol,
                tags=search_tags,
                limit=15,
                include_community=has_community,
            )
            # 3. Fetch transfer insights if exact_insights is small
            transfer_insights = []
            if len(exact_insights) < 10:
                all_insights = await crud.search_agent_memories(
                    db,
                    user_id=user_id,
                    memory_type="strategy_insight",
                    tags=search_tags,
                    limit=15,
                    include_community=has_community,
                )
                transfer_insights = [m for m in all_insights if m.symbol != symbol]

        total_memories_count = len(rules) + len(exact_insights) + len(transfer_insights)

        if total_memories_count == 0:
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "thinking",
                    "message": "🧠 Memory Researcher Agent: No prior memories found in database. Starting with clean slate.",
                }
            )
            return ""

        comm_count = sum(
            1
            for m in (rules + exact_insights + transfer_insights)
            if getattr(m, "visibility", "private") == "community"
        )
        if comm_count > 0:
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "thinking",
                    "message": f"🌐 Community Memory: Found {comm_count} shared insights from other traders across the network.",
                }
            )

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"🕵️ Memory Researcher Agent: Found {total_memories_count} relevant memories. Synthesizing insight summary...",
            }
        )

        # Construct the memory content text
        raw_memories = []
        if rules:
            raw_memories.append("Universal Trading Rules:")
            for r in rules:
                tag = (
                    " [COMMUNITY 🌐]"
                    if getattr(r, "visibility", "private") == "community"
                    else ""
                )
                raw_memories.append(f"-{tag} {r.content}")
        if exact_insights:
            raw_memories.append(f"\nPast Backtest Insights for {symbol}:")
            for m in exact_insights:
                tag = (
                    " [COMMUNITY 🌐]"
                    if getattr(m, "visibility", "private") == "community"
                    else ""
                )
                raw_memories.append(
                    f"-{tag} Outcome: {m.outcome.upper()} | Content: {m.content}"
                )
        if transfer_insights:
            raw_memories.append(
                "\nCross-Asset Backtest Insights (transferable lessons):"
            )
            for m in transfer_insights:
                tag = (
                    " [COMMUNITY 🌐]"
                    if getattr(m, "visibility", "private") == "community"
                    else ""
                )
                raw_memories.append(
                    f"-{tag} Asset: {m.symbol} | Outcome: {m.outcome.upper()} | Content: {m.content}"
                )

        memories_text = "\n".join(raw_memories)

        system_instruction = MEMORY_RESEARCHER_SYSTEM_PROMPT

        storage_note = (
            f"\nHistorical Data in DepthSight Storage: {storage_range_info}"
            if storage_range_info
            else ""
        )
        user_content = (
            f"User Request: {user_prompt}\n"
            f"Target Symbol: {symbol}{storage_note}\n\n"
            f"Raw Memories:\n"
            f"{memories_text}\n\n"
            f"Based on the above, synthesize the trading rules and insights for {symbol}."
        )

        summary_text = await _generate_text_response(
            system_instruction=system_instruction,
            messages=[{"role": "user", "content": user_content}],
        )

        summary_text = clean_double_newlines(summary_text)

        # Extract top-performing configurations from historical insights (Variant C)
        top_configs = []
        seen_config_hashes = set()
        candidate_insights = [
            m for m in (exact_insights + transfer_insights) if m.outcome == "success"
        ]
        for m in candidate_insights:
            cfg = _extract_config(m.content)
            pnl_val = _extract_pnl(m.content)
            if cfg and pnl_val > 0:
                clean_cfg = cfg.copy()
                for k in ("id", "user_id", "created_at", "updated_at"):
                    clean_cfg.pop(k, None)
                c_hash = hashlib.sha256(
                    json.dumps(clean_cfg, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if c_hash in seen_config_hashes:
                    continue
                seen_config_hashes.add(c_hash)
                top_configs.append((pnl_val, m.symbol or symbol, clean_cfg))

        if top_configs:
            top_configs.sort(key=lambda x: x[0], reverse=True)
            best_configs = top_configs[:3]
            config_blocks = []
            for rank, (pnl_val, sym_val, c_dict) in enumerate(best_configs, 1):
                config_blocks.append(
                    f"### Top Config #{rank} ({sym_val}, Historical PnL: +{pnl_val:.2f}%):\n"
                    f"```json\n{json.dumps(c_dict, indent=2)}\n```"
                )
            summary_text += (
                "\n\n## PROVEN HIGH-PERFORMING STRATEGY CONFIGURATIONS (INSPIRATION):\n"
                "You may draw architectural inspiration from these proven configurations (e.g. entry block logic, filter choices, risk/reward settings). "
                "DO NOT copy them blindly; adapt and mutate their parameters and filters for the current asset and market conditions:\n\n"
                + "\n\n".join(config_blocks)
            )

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"🧠 **Memory Research Summary:**\n\n{summary_text}",
            }
        )
        return summary_text
    except Exception as e:
        logger.error(f"Memory Researcher Agent failed: {e}")
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"⚠️ Memory Researcher Agent failed: {str(e)}. Proceeding without summary.",
            }
        )
        return ""


async def run_strategy_advisor_agent(
    user_id: int,
    symbol: str,
    initial_memory_rules: str,
    current_config: dict,
    current_pnl: float,
    current_trades: int,
    best_config: dict,
    best_pnl: float,
    best_trades: int,
    websocket: WebSocket,
    storage_range_info: str = "",
) -> str:
    """Compares the last run's configuration and results with the best configuration and historical rules, then writes concrete recommendations."""
    from api.ai_assistant import (
        _get_active_ai_provider,
        _generate_json_response,
        _generate_text_response,
    )
    from api import crud, models
    from api.database import async_session_factory
    from sqlalchemy import or_, select

    # Fetch all unique tags from DB for this user (including community if opted in) to pass to Advisor
    db_tags = set()
    try:
        async with async_session_factory() as db:
            user_obj = await db.get(models.User, user_id)
            has_community = (
                bool(getattr(user_obj, "share_community_memories", False))
                if user_obj
                else False
            )
            tag_query = select(models.AgentMemory.tags)
            if has_community:
                tag_query = tag_query.where(
                    or_(
                        models.AgentMemory.user_id == user_id,
                        models.AgentMemory.visibility == "community",
                    )
                )
            else:
                tag_query = tag_query.where(models.AgentMemory.user_id == user_id)
            result = await db.execute(tag_query)
            all_tags_rows = result.scalars().all()
            for tags_row in all_tags_rows:
                if tags_row:
                    for t in tags_row:
                        db_tags.add(t.strip().lower())
    except Exception as e:
        logger.error(f"Failed to query unique tags from database: {e}")

    # Standard default tags in case database is empty or error occurs
    if not db_tags:
        db_tags = {
            "breakout",
            "reversion",
            "trend",
            "scalping",
            "volatility_squeeze",
            "rel_vol_filter",
            "classic_pattern",
            "price_action_analyzer",
            "price_consolidation",
            "EMA",
            "ADX",
            "RSI",
        }

    # Render prompt with dynamic tag list
    system_prompt_with_tags = ADVISOR_SYSTEM_PROMPT.replace(
        "{db_tags}", ", ".join(f"'{t}'" for t in sorted(list(db_tags)))
    )

    await websocket.send_json(
        {
            "event": "autopilot_status",
            "status": "thinking",
            "message": "🤖 Strategy Advisor Agent: Analyzing recent variant performance...",
        }
    )

    # Clean configs for prompt (remove database/metadata keys)
    def clean_config(c):
        if not c:
            return {}
        clean = c.copy()
        clean.pop("id", None)
        clean.pop("user_id", None)
        clean.pop("created_at", None)
        clean.pop("updated_at", None)
        return clean

    clean_curr = clean_config(current_config)
    clean_best = clean_config(best_config)

    # Resolve active model for JSON/Text generation
    provider = _get_active_ai_provider()
    advisor_model = os.environ.get("AI_ADVISOR_MODEL")
    if not advisor_model:
        if provider == "google":
            advisor_model = "gemini-3-flash-preview"
        elif provider == "qwen":
            advisor_model = os.environ.get("QWEN_MODEL", "qwen-max")
        else:
            advisor_model = os.environ.get(
                "OPENROUTER_MODEL", "google/gemini-3-flash-preview"
            )

    # Programmatic fallback tag extractor
    def extract_fallback_tags(curr, best) -> list[str]:
        tags = set()
        blocks_to_detect = {
            "volatility_squeeze",
            "rel_vol_filter",
            "trend_filter",
            "price_action_analyzer",
            "price_consolidation",
            "classic_pattern",
            "return_to_level",
            "level_touch_analyzer",
            "move_to_breakeven",
            "conditional_management",
        }

        def walk(node):
            if isinstance(node, dict):
                node_type = node.get("type")
                if node_type in blocks_to_detect:
                    tags.add(node_type)
                for k, v in node.items():
                    if isinstance(v, str) and v in {"ADX", "RSI", "EMA", "SMA", "MACD"}:
                        tags.add(v)
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(curr)
        walk(best)
        # Only keep fallback tags that actually exist in DB (if database has tags)
        active_fallbacks = [t for t in tags if t in db_tags]
        if not active_fallbacks:
            # Fall back to first available tag in db
            active_fallbacks = [sorted(list(db_tags))[0]] if db_tags else ["breakout"]
        return active_fallbacks

    # Turn 0: Ask Advisor what tags it wants to query
    range_header = (
        f" (Historical Storage: {storage_range_info})" if storage_range_info else ""
    )
    advisor_user_prompt = (
        f"Target Asset: {symbol}{range_header}\n\n"
        f"Best Variant Configuration (PnL: {best_pnl:.2f}%, Trades: {best_trades}):\n"
        f"```json\n{json.dumps(clean_best, indent=2)}\n```\n\n"
        f"Latest Variant Configuration (PnL: {current_pnl:.2f}%, Trades: {current_trades}):\n"
        f"```json\n{json.dumps(clean_curr, indent=2)}\n```\n\n"
        f"Select the tags you want to search in the memory bank to compare this setup with historical successes or failures."
    )

    tags = []
    fallback_used = False
    try:
        raw_tool_json = await _generate_json_response(
            system_prompt=system_prompt_with_tags,
            user_prompt=advisor_user_prompt,
            max_output_tokens=500,
            model_name=advisor_model,
        )

        import re

        match = re.search(r"\{.*\}", raw_tool_json, re.DOTALL)
        if match:
            call_data = json.loads(match.group())
            tags = call_data.get("arguments", {}).get("tags", [])
            # Normalize casing and spacing of selected tags
            tags = [str(t).strip().lower() for t in tags]
            tags = [t for t in tags if t in db_tags]
            if not tags:
                raise ValueError("No valid tags parsed after database filtering")
        else:
            raise ValueError("No valid JSON found in response")
    except Exception as e:
        logger.warning(
            f"Strategy Advisor tool call failed ({e}). Running fallback tag extraction."
        )
        tags = extract_fallback_tags(clean_curr, clean_best)
        fallback_used = True

    # Log tag retrieval status
    if fallback_used:
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"⚠️ Strategy Advisor Agent: Tool call failed. Programmatic fallback tags selected: {tags}",
            }
        )
    else:
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"🔍 Strategy Advisor Agent: Decided to query memory with tags: {tags}",
            }
        )

    # Query DB with the selected tags
    retrieved_lines = []
    try:
        async with async_session_factory() as db:
            user_obj = await db.get(models.User, user_id)
            has_community = (
                bool(getattr(user_obj, "share_community_memories", False))
                if user_obj
                else False
            )
            memories = await crud.search_agent_memories(
                db,
                user_id=user_id,
                tags=tags,
                symbol=symbol,
                limit=8,
                include_community=has_community,
            )
            for m in memories:
                icon = "success" if m.outcome == "success" else "failure"
                comm_tag = (
                    " [COMMUNITY 🌐]"
                    if getattr(m, "visibility", "private") == "community"
                    else ""
                )
                retrieved_lines.append(f"- [{icon.upper()}]{comm_tag} {m.content}")

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"🧠 Recall Synapses: Retrieved {len(memories)} relevant memories matching {tags}.",
            }
        )
    except Exception as e:
        logger.error(f"Failed to query advisor database: {e}")
        retrieved_lines = ["No matching memories retrieved due to internal error."]

    # Turn 1: Advisor generates the final text advice using multi-turn conversation context
    retrieved_context = (
        "\n".join(retrieved_lines)
        if retrieved_lines
        else "No matching historical memories found."
    )

    # Construct assistant response representation of Turn 0
    if not fallback_used and raw_tool_json:
        assistant_turn_0 = raw_tool_json
    else:
        assistant_turn_0 = json.dumps(
            {
                "function": "search_advisor_memory",
                "arguments": {"tags": tags, "symbol": symbol},
            },
            indent=2,
        )

    advisor_turn_1_prompt = (
        f"Historical Memory Rules:\n"
        f"{initial_memory_rules}\n\n"
        f"Here are the historical examples retrieved from the database:\n"
        f"{retrieved_context}\n\n"
        f"Compare the configurations and results, and write specific recommendations for the next variant."
    )

    messages = [
        {"role": "user", "content": advisor_user_prompt},
        {"role": "assistant", "content": assistant_turn_0},
        {"role": "user", "content": advisor_turn_1_prompt},
    ]

    try:
        advice_text = await _generate_text_response(
            system_instruction=system_prompt_with_tags,
            messages=messages,
        )

        advice_text = clean_double_newlines(advice_text)

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"💡 **Strategic Advisor Advice:**\n\n{advice_text}",
            }
        )
        return advice_text
    except Exception as e:
        logger.error(f"Strategy Advisor Agent failed at Turn 1: {e}")
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"⚠️ Strategy Advisor Agent failed: {str(e)}. Falling back to general rules.",
            }
        )
        return initial_memory_rules


async def run_critic_agent(strategy_json: dict) -> dict:
    """Review a strategy JSON for logical flaws using a fast flash model."""
    try:
        from api.ai_assistant import _get_active_ai_provider

        provider = _get_active_ai_provider()

        critic_model = os.environ.get("AI_CRITIC_MODEL")
        if not critic_model:
            if provider == "google":
                critic_model = "gemini-3-flash-preview"
            elif provider == "qwen":
                critic_model = os.environ.get("QWEN_MODEL", "qwen-max")
            else:
                critic_model = os.environ.get(
                    "OPENROUTER_MODEL", "google/gemini-3-flash-preview"
                )

        lite_strategy = strategy_json.copy()

        system_prompt = (
            "You are a strict Quantitative Risk Manager. "
            "Review the strategy JSON for fatal logical flaws (e.g., impossible math, missing required fields). "
            "You MUST be EXTREMELY concise. "
            "Return ONLY valid JSON matching this exact schema: "
            '{"approved": true, "reason": "Short explanation under 20 words", "critical_flaw": null}'
        )

        user_prompt = f"Review this config for critical flaws:\n\n{json.dumps(lite_strategy, indent=2)[:3000]}"

        raw = await _generate_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=2000,
            model_name=critic_model,
        )

        import re

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return {
                "approved": result.get("approved", True),
                "reason": result.get("reason", "Approved without comments."),
                "critical_flaw": result.get("critical_flaw"),
            }

        logger.warning(
            f"Critic Agent returned invalid JSON. Auto-approving. Output: {raw[:100]}"
        )
        return {
            "approved": True,
            "reason": "Critic hallucinated, auto-approved.",
            "critical_flaw": None,
        }

    except Exception as e:
        logger.error(f"Critic agent failed: {e}")
        return {
            "approved": True,
            "reason": f"Critic offline or errored, bypassing. ({str(e)})",
            "critical_flaw": None,
        }


async def run_autopilot_loop(
    websocket: WebSocket,
    user_id: int,
    symbol: str | None,
    user_prompt: str,
    max_iterations: int | str = 5,
    image_base64: str | None = None,
    image_mime_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Runs the self-correcting Autopilot loop: Generate -> Backtest -> Learn -> Repeat."""
    until_profitable = False
    if isinstance(max_iterations, str) and max_iterations == "until_profitable":
        until_profitable = True
        iterations_limit = 30
    else:
        try:
            iterations_limit = int(max_iterations)
        except ValueError:
            iterations_limit = 5

    logger.info(
        f"Starting Autopilot Loop for user {user_id}. Prompt: '{user_prompt}', limit: {iterations_limit}, until_profitable: {until_profitable}"
    )

    # 1. Fetch available historical data in storage
    storage_data = []
    try:
        from api.mcp.tools import get_storage_symbols_info
        from api.redis_client import get_redis_client

        try:
            redis_client = await get_redis_client()
        except Exception:
            redis_client = None
        storage_data = await get_storage_symbols_info(redis_client)
    except Exception as e:
        logger.warning(f"Failed to query storage info for autopilot: {e}")

    storage_map = {s["symbol"]: s for s in storage_data if s.get("symbol")}
    available_symbols = sorted(list(storage_map.keys()))

    # 2. Initial guess for the symbol — uses alias map first, LLM fallback with storage awareness
    if symbol:
        resolved_symbol = symbol.upper().strip()
    else:
        resolved_symbol = (
            (
                await resolve_symbol_with_llm(
                    user_prompt, available_symbols=available_symbols
                )
            )
            .upper()
            .strip()
        )

    # If resolved_symbol is not in storage, alert and fallback
    if storage_map and resolved_symbol not in storage_map:
        logger.warning(f"Resolved symbol {resolved_symbol} not found in local storage.")
        fallback = "BTCUSDT" if "BTCUSDT" in storage_map else available_symbols[0]
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": f"⚠️ **{resolved_symbol}** is not loaded in local storage. Switching to loaded asset **{fallback}**.",
            }
        )
        resolved_symbol = fallback

    # 3. Extract loaded date interval and features for resolved_symbol
    sym_info = storage_map.get(resolved_symbol, {})
    kline_info = sym_info.get("klines_1m") or {}
    storage_start_date = kline_info.get("start_date") or "2025-01-01"
    storage_end_date = kline_info.get("end_date") or "2026-07-12"

    # Determine default backtest dates
    user_specified_start = start_date
    user_specified_end = end_date
    has_user_date_intent = bool(user_specified_start or user_specified_end)

    if not has_user_date_intent:
        date_matches = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", user_prompt)
        if len(date_matches) >= 2:
            user_specified_start = date_matches[0]
            user_specified_end = date_matches[1]
            has_user_date_intent = True
        elif "2025" in user_prompt and "2026" not in user_prompt:
            user_specified_start = "2025-01-01"
            user_specified_end = "2025-12-31"
            has_user_date_intent = True

    default_start_date = user_specified_start or storage_start_date
    default_end_date = user_specified_end or storage_end_date

    # Notify UI of asset data coverage
    timeframes_str = ", ".join(sym_info.get("timeframes", ["15m"])) or "15m"
    features_list = []
    if sym_info.get("has_depth"):
        features_list.append("Orderbook Depth")
    if sym_info.get("has_oi"):
        features_list.append("Open Interest")
    features_str = f" | Features: {', '.join(features_list)}" if features_list else ""

    storage_range_info = f"{storage_start_date} to {storage_end_date} (TFs: {timeframes_str}{features_str})"

    await websocket.send_json(
        {
            "event": "autopilot_status",
            "status": "thinking",
            "message": f"📊 Target: **{resolved_symbol}** | Available History: **{storage_start_date}** to **{storage_end_date}** (Timeframes: {timeframes_str}{features_str})",
        }
    )

    # Screenshot analysis step
    if image_base64:
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": "🕵️ Analyzing chart screenshot...",
            }
        )
        try:
            from api.ai_assistant import _generate_text_response

            vision_system_prompt = (
                "You are an expert technical analyst and quantitative trader. "
                "Analyze the provided chart screenshot. "
                "Provide a brief description of what you see (patterns, trend, key levels) "
                "and suggest a trading strategy to build. "
                "Be extremely concise, structured, and use Markdown (bullet points, bold text). "
                "Limit your response to 2-3 short paragraphs or bullet points."
            )
            vision_user_prompt = (
                f"Analyze this chart screenshot for {resolved_symbol}. "
                f"Based on this and the user request: '{user_prompt}', "
                f"what strategy should we build?"
            )
            analysis_text = await _generate_text_response(
                system_instruction=vision_system_prompt,
                messages=[{"role": "user", "content": vision_user_prompt}],
                image_base64=image_base64,
                image_mime_type=image_mime_type,
            )
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "thinking",
                    "message": f"📊 **Vision Analysis:**\n\n{analysis_text}",
                }
            )
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "thinking",
                    "message": f"⚠️ Vision analysis failed: {str(e)}",
                }
            )

    # Memory research step (runs once at start to fetch historical base rules)
    initial_memory_rules = await run_memory_researcher_agent(
        user_id=user_id,
        symbol=resolved_symbol,
        user_prompt=user_prompt,
        websocket=websocket,
        storage_range_info=storage_range_info,
    )
    if not initial_memory_rules:
        initial_memory_rules = "No prior memories found in database."

    current_feedback = ""
    current_feedback_history = {}
    best_strategy = None
    best_pnl = -999999.0
    best_iteration = 1
    best_kpis = None
    last_strategy_json = None

    last_iteration_json = None
    last_iteration_pnl = 0.0
    last_iteration_trades = 0

    for i in range(1, iterations_limit + 1):
        # Get user configuration
        async with async_session_factory() as db:
            user = await crud.get_user_by_id(db, user_id=user_id)

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "generating",
                "iteration": i,
                "message": f"Generating Strategy Variant {chr(64 + i)} for {resolved_symbol}...",
            }
        )

        # Dynamic memory research/advisor step
        if i == 1:
            memory_summary = initial_memory_rules
        else:
            advisor_advice = await run_strategy_advisor_agent(
                user_id=user_id,
                symbol=resolved_symbol,
                initial_memory_rules=initial_memory_rules,
                current_config=last_iteration_json,
                current_pnl=last_iteration_pnl,
                current_trades=last_iteration_trades,
                best_config=best_strategy,
                best_pnl=best_pnl,
                best_trades=best_kpis.get("trades", 0) if best_kpis else 0,
                websocket=websocket,
                storage_range_info=storage_range_info,
            )
            # Combine the historical rules and the dynamic advice so the generator retains both
            memory_summary = f"{initial_memory_rules}\n\n# CURRENT SESSION STRATEGIC ADVICE:\n{advisor_advice}"

        # Build prompt including iteration context, diversity directive, and feedback
        autopilot_instruction = _load_prompt("autopilot_system.md").format(
            resolved_symbol=resolved_symbol,
            start_date=default_start_date,
            end_date=default_end_date,
        )
        variant_letter = chr(64 + i)
        iteration_header = f"\n\n--- ITERATION {i}/{iterations_limit} (Generating Variant {variant_letter}) ---"
        if i == 1:
            iteration_guidance = (
                "Goal: Generate a robust initial baseline strategy. Aim for at least 20 trades "
                "over the backtest period with a solid Risk-to-Reward ratio (1:2 to 1:4) and clear, high-conviction entry logic."
            )
        else:
            iteration_guidance = (
                f"Goal: Generate Variant {variant_letter}.\n"
                "DIVERSITY & EXPLORATION DIRECTIVE:\n"
                "- Do NOT generate an identical or minor cosmetic clone of the previous config.\n"
                "- If previous trades were too low (< 20 trades), loosen entry filters, widen indicator thresholds, or lower min_foundation_weight_threshold.\n"
                "- If previous PnL was negative or drawdown high, explore alternative entry blocks, "
                "adjust stop loss type/distance, or test a different indicator timeframe/lookback."
            )
        active_prompt = (
            f"{autopilot_instruction}\n\nUser Request: Find a profitable strategy for {resolved_symbol} based on: '{user_prompt}'\n"
            f"{iteration_header}\n{iteration_guidance}"
        )
        if current_feedback:
            active_prompt += f"\n\nPrevious Iteration Feedback:\n{current_feedback}\nPlease improve the configuration based on this."

        try:
            # Request strategy config from active AI provider
            # Image (chart screenshot) is sent only on the first iteration
            # to recognise the visual pattern. Subsequent iterations mutate
            # the JSON based solely on backtest KPIs.
            request_kwargs: dict = {
                "text_prompt": active_prompt,
                "current_config_json": last_strategy_json,
                "memory_summary": memory_summary or None,
            }
            if i == 1:
                request_kwargs["image_base64"] = image_base64
                request_kwargs["image_mime_type"] = image_mime_type
            request = schemas.GenerateStrategyRequest(**request_kwargs)
            strategy_json = await ai_assistant.generate_strategy_json_from_prompt(
                request, user, websocket=websocket
            )

            # Validate that the AI did not generate restricted (pro-only / kline-only) blocks
            # as Autopilot runs on the Vector engine
            from api.dependencies import plans_config

            def find_restricted_blocks(node, restricted_set):
                found = []
                if isinstance(node, dict):
                    node_type = node.get("type")
                    if node_type in restricted_set:
                        found.append(node_type)
                    for v in node.values():
                        found.extend(find_restricted_blocks(v, restricted_set))
                elif isinstance(node, list):
                    for item in node:
                        found.extend(find_restricted_blocks(item, restricted_set))
                return found

            restrictions = plans_config.get_block_restrictions()
            restricted_set = set(
                restrictions.get("pro_only", []) + restrictions.get("kline_only", [])
            )
            bad_blocks = find_restricted_blocks(strategy_json, restricted_set)

            if bad_blocks:
                logger.warning(
                    f"AI generated strategy with restricted blocks: {bad_blocks}. Forcing retry."
                )
                current_feedback += f"\n- Iteration {i} failed validation: You generated strategy '{strategy_json.get('strategy_name')}' using unsupported blocks: {bad_blocks}. The Autopilot Vector engine only supports standard blocks. You MUST rewrite the strategy without using {bad_blocks}."
                await websocket.send_json(
                    {
                        "event": "autopilot_status",
                        "status": "failed_iteration",
                        "iteration": i,
                        "message": f"Variant {chr(64 + i)} used unsupported blocks: {bad_blocks}. Requesting correction...",
                    }
                )
                continue

            # Extract symbols generated dynamically by the model
            cfg_data = (
                strategy_json.get("config_data")
                if isinstance(strategy_json.get("config_data"), dict)
                else {}
            )
            ai_symbols = strategy_json.get("symbols") or cfg_data.get("symbols")
            if (
                ai_symbols
                and isinstance(ai_symbols, list)
                and len(ai_symbols) > 0
                and ai_symbols[0]
            ):
                cand_sym = str(ai_symbols[0]).upper().strip()
                if not storage_map or cand_sym in storage_map:
                    resolved_symbol = cand_sym
            elif strategy_json.get("symbol") or cfg_data.get("symbol"):
                cand_sym = (
                    str(strategy_json.get("symbol") or cfg_data.get("symbol"))
                    .upper()
                    .strip()
                )
                if not storage_map or cand_sym in storage_map:
                    resolved_symbol = cand_sym

            # Extract parameters generated dynamically by the model
            raw_start = strategy_json.get("start_date") or cfg_data.get("start_date")
            raw_end = strategy_json.get("end_date") or cfg_data.get("end_date")

            start_date = (
                str(raw_start)[:10]
                if raw_start and str(raw_start) != "null"
                else default_start_date
            )
            if raw_end and str(raw_end) != "null":
                # If model returned legacy 2025-12-31 but user didn't ask for 2025 and 2026 data exists
                if (
                    str(raw_end)[:10] == "2025-12-31"
                    and not has_user_date_intent
                    and default_end_date > "2025-12-31"
                ):
                    end_date = default_end_date
                else:
                    end_date = str(raw_end)[:10]
            else:
                end_date = default_end_date

            timeframe = (
                strategy_json.get("timeframe") or cfg_data.get("timeframe") or "15m"
            )

            strategy_display_name = (
                strategy_json.get("name")
                or strategy_json.get("strategy_name")
                or f"Variant {chr(64 + i)}"
            )

            # Synchronize timeframe across all fields to ensure the engine and trainer load it correctly
            strategy_json["candle_timeframe"] = timeframe
            strategy_json["entry_timeframe"] = timeframe
            strategy_json["start_date"] = start_date
            strategy_json["end_date"] = end_date
            if "config_data" in strategy_json and isinstance(
                strategy_json["config_data"], dict
            ):
                strategy_json["config_data"]["start_date"] = start_date
                strategy_json["config_data"]["end_date"] = end_date
            if "entryTrigger" in strategy_json and isinstance(
                strategy_json["entryTrigger"], dict
            ):
                strategy_json["entryTrigger"]["timeframe"] = timeframe

            # Will be set at the end of the iteration based on backtracking performance

            # --- Critic Agent bypassed in favor of Memory Researcher & Programmatic Validation ---
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "validating",
                    "iteration": i,
                    "message": "✅ Critic Agent bypassed. Programmatic logic validation active.",
                }
            )

        except Exception as e:
            logger.error(f"AI generation or validation failed: {e}")
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "failed_iteration",
                    "iteration": i,
                    "message": f"Variant {chr(64 + i)} generation failed: {str(e)}. Retrying...",
                }
            )
            current_feedback += (
                f"\n- Iteration {i} generation failed with error: {str(e)}."
            )
            continue

        # Run backtest via Celery (matches how user runs backtests manually)
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "backtesting",
                "iteration": i,
                "message": f"Queueing Celery Backtest for Variant {chr(64 + i)} on {resolved_symbol} ({start_date} to {end_date}, {timeframe})...",
            }
        )

        from api.celery_app import celery_app

        backtest_payload = {
            "strategy_name": "VisualBuilderStrategy",
            "symbol": resolved_symbol,
            "start_date": start_date,
            "end_date": end_date,
            "timeframe": timeframe,
            "params": {"config": strategy_json},
        }

        try:
            # Dispatch the task to Celery
            celery_task = celery_app.send_task(
                "run_backtest_task",
                args=[backtest_payload, user_id],
                priority=9,
            )

            # Wait for task completion
            while not celery_task.ready():
                await asyncio.sleep(0.5)

            task_result = celery_task.result
            if isinstance(task_result, Exception):
                raise task_result
            if not task_result or resolved_symbol not in task_result:
                raise ValueError(f"No backtest results returned for {resolved_symbol}")

            kpis = task_result[resolved_symbol]
        except Exception as e:
            logger.error(f"Celery backtest execution failed: {e}")
            current_feedback += (
                f"\n- Iteration {i} failed during backtest execution: {str(e)}."
            )
            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "failed_iteration",
                    "iteration": i,
                    "message": f"Variant {chr(64 + i)} failed: Celery execution error.",
                }
            )
            continue

        total_pnl = kpis.get("total_pnl_pct", 0.0)
        win_rate = kpis.get("win_rate", 0.0)
        trades_count = kpis.get("trades", 0)
        max_dd = kpis.get("max_drawdown", 0.0)

        # Stream result to client
        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "iteration_result",
                "iteration": i,
                "pnl": total_pnl,
                "win_rate": win_rate,
                "trades": trades_count,
                "max_dd": max_dd,
                "strategy_name": strategy_display_name,
                "reasoning": strategy_json.get("reasoning", ""),
            }
        )

        # Update last iteration tracking
        last_iteration_json = strategy_json
        last_iteration_pnl = total_pnl
        last_iteration_trades = trades_count

        # Track the best variant
        if total_pnl > best_pnl:
            best_pnl = total_pnl
            best_strategy = strategy_json
            best_iteration = i
            best_kpis = {
                "pnl": total_pnl,
                "win_rate": win_rate,
                "trades": trades_count,
                "max_dd": max_dd,
            }

        # Check if it meets success criteria
        if total_pnl > 5.0 and trades_count >= 20:
            # We found a winning strategy! Save memory of success
            reasoning = strategy_json.get("reasoning", "")
            filters_list = [
                f.get("type")
                for f in strategy_json.get("filters", {}).get("children", [])
            ]
            try:
                d1 = datetime.strptime(start_date[:10], "%Y-%m-%d")
                d2 = datetime.strptime(end_date[:10], "%Y-%m-%d")
                backtest_days = abs((d2 - d1).days)
            except Exception:
                backtest_days = 30

            content = f"Profitable strategy '{strategy_display_name}' on {resolved_symbol} ({timeframe}): PnL={total_pnl:.2f}%, WR={win_rate:.1f}%, DD={max_dd:.1f}%, trades={trades_count}, days={backtest_days}. Weights: {strategy_json.get('foundation_weights')}, Filters: {filters_list}. Reasoning: {reasoning}. Config: {json.dumps(strategy_json)}"

            # Generate classification tags and config hash
            tag_data = await tag_strategy_insight(
                strategy_json, total_pnl, win_rate, trades_count, user_id
            )
            config_str = json.dumps(strategy_json)
            config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()

            saved_memory_id = None
            async with async_session_factory() as db:
                saved_memory = await crud.create_agent_memory(
                    db,
                    user_id=user_id,
                    memory_data=schemas.AgentMemoryCreate(
                        memory_type="strategy_insight",
                        content=content,
                        relevance_score=1.0,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
                        tags=tag_data.get("tags", []),
                        symbol=resolved_symbol,
                        strategy_type=tag_data.get("strategy_type", "breakout"),
                        outcome="success",
                        confidence=tag_data.get("confidence", 1.0),
                        validated_count=1,
                        config_hash=config_hash,
                    ),
                )
                await db.commit()
                saved_memory_id = saved_memory.id

                # Trigger community promotion if user opted in
                user_obj = await db.get(models.User, user_id)
                if user_obj and getattr(user_obj, "share_community_memories", False):
                    try:
                        from tasks import maybe_promote_to_community

                        maybe_promote_to_community.delay(
                            memory_id=saved_memory_id, user_id=user_id
                        )
                    except Exception as prom_err:
                        logger.debug(
                            f"Failed to queue Celery community promotion, running async direct: {prom_err}"
                        )
                        try:
                            from tasks import async_maybe_promote_to_community

                            asyncio.create_task(
                                async_maybe_promote_to_community(
                                    memory_id=saved_memory_id, user_id=user_id
                                )
                            )
                        except Exception as direct_err:
                            logger.debug(
                                f"Direct community promotion failed: {direct_err}"
                            )

            # Trigger rule synthesis check in background
            asyncio.create_task(
                run_rule_synthesis(user_id, tag_data.get("strategy_type", "breakout"))
            )
            asyncio.create_task(
                evaluate_rule_lifecycle(
                    user_id,
                    strategy_json,
                    total_pnl,
                    tag_data.get("strategy_type", "breakout"),
                )
            )

            if until_profitable:
                # Stop immediately and report success
                await websocket.send_json(
                    {
                        "event": "autopilot_status",
                        "status": "success",
                        "message": f"Profitable strategy found in Variant {chr(64 + i)} (PnL: {total_pnl:.2f}%). Stopping as requested.",
                        "strategy_json": strategy_json,
                        "kpis": {
                            "pnl": total_pnl,
                            "win_rate": win_rate,
                            "trades": trades_count,
                            "max_dd": max_dd,
                        },
                    }
                )
                return

            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "candidate_success",
                    "message": f"Profitable candidate found in Variant {chr(64 + i)} (PnL: {total_pnl:.2f}%). Continuing to search for better variants...",
                }
            )
            feedback_msg = f"Variant {chr(64 + i)} succeeded backtest with PnL: {total_pnl:.2f}%, winrate: {win_rate:.1f}%, trades: {trades_count}. Let's try to optimize it further to get even higher PnL."
            current_feedback_history[i] = feedback_msg
        else:
            # Create failure reason and save to database
            reason = "negative return" if total_pnl <= 0.0 else "too few trades (< 5)"
            reasoning = strategy_json.get("reasoning", "")
            filters_list = [
                f.get("type")
                for f in strategy_json.get("filters", {}).get("children", [])
            ]
            insight = f"Failed strategy '{strategy_display_name}' on {resolved_symbol} ({timeframe}): PnL={total_pnl:.2f}%, WR={win_rate:.1f}%, trades={trades_count}. Reason: {reason}. Weights: {strategy_json.get('foundation_weights')}, Filters: {filters_list}. Reasoning: {reasoning}. Config: {json.dumps(strategy_json)}"

            # Generate classification tags and config hash
            tag_data = await tag_strategy_insight(
                strategy_json, total_pnl, win_rate, trades_count, user_id
            )
            config_str = json.dumps(strategy_json)
            config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()

            async with async_session_factory() as db:
                await crud.create_agent_memory(
                    db,
                    user_id=user_id,
                    memory_data=schemas.AgentMemoryCreate(
                        memory_type="strategy_insight",
                        content=insight,
                        relevance_score=0.8,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                        tags=tag_data.get("tags", []),
                        symbol=resolved_symbol,
                        strategy_type=tag_data.get("strategy_type", "breakout"),
                        outcome="failure",
                        confidence=tag_data.get("confidence", 0.8),
                        validated_count=1,
                        config_hash=config_hash,
                    ),
                )
                await db.commit()

            # Trigger rule synthesis check in background
            asyncio.create_task(
                run_rule_synthesis(user_id, tag_data.get("strategy_type", "breakout"))
            )
            asyncio.create_task(
                evaluate_rule_lifecycle(
                    user_id,
                    strategy_json,
                    total_pnl,
                    tag_data.get("strategy_type", "breakout"),
                )
            )

            feedback_msg = f"Variant {chr(64 + i)} failed backtest with PnL: {total_pnl:.2f}%, winrate: {win_rate:.1f}%, trades: {trades_count}, max drawdown: {max_dd:.1f}%. Reason: {reason}."
            current_feedback_history[i] = feedback_msg

        recent_feedbacks = "\n".join(
            [f"- {msg}" for msg in list(current_feedback_history.values())[-3:]]
        )

        # Backtracking decision:
        # If this candidate performed worse than the best PnL achieved so far, reset base config.
        if total_pnl < best_pnl and best_strategy is not None:
            last_strategy_json = best_strategy

            # Extract clean config for failed variant to show model what NOT to do
            failed_config_clean = strategy_json.copy()
            failed_config_clean.pop("id", None)
            failed_config_clean.pop("user_id", None)
            failed_config_clean.pop("created_at", None)
            failed_config_clean.pop("updated_at", None)

            # Reset feedback to focus on the best baseline AND explain the failed modification
            current_feedback = (
                f"Recent History (Last 3 runs):\n{recent_feedbacks}\n\n"
                f"⚠️ Notice: We have backtracked to the best configuration so far (Variant {chr(64 + best_iteration)}).\n"
                f"The subsequent modification (Variant {chr(64 + i)}) deteriorated the performance (PnL: {total_pnl:.2f}% vs Best: {best_pnl:.2f}%).\n"
                f"Failed Variant {chr(64 + i)} Config snippet:\n{json.dumps(failed_config_clean, indent=2)[:800]}...\n\n"
                f"CRITICAL INSTRUCTION FOR NEXT VARIANT:\n"
                f"You MUST make meaningful mathematical changes to the baseline strategy. DO NOT output the exact same config.\n"
                f"Try exploring ONE of these mutations:\n"
                f"- Change indicator lookback periods (e.g., from 14 to 21 or 7)\n"
                f"- Adjust multiplier thresholds (e.g., volume multiplier from 2.0 to 3.0)\n"
                f"- Add a completely new filter from the STANDARD blocks list\n"
            )

            await websocket.send_json(
                {
                    "event": "autopilot_status",
                    "status": "loading_data",
                    "message": f"⚠️ Backtracking: Variant {chr(64 + i)} performance deteriorated (PnL: {total_pnl:.2f}% vs Best: {best_pnl:.2f}%). Restoring best variant config as base...",
                }
            )
        else:
            last_strategy_json = strategy_json
            current_feedback = (
                f"Recent History (Last 3 runs):\n{recent_feedbacks}\n\n"
                f"Please analyze the recent history and optimize the configuration further to get higher PnL (target > 5.0% and >= 20 trades). "
                f"DIVERSITY DIRECTIVE: Make meaningful structural improvements rather than repeating the exact same parameters."
            )

    # If we exited the loop, return the best found overall
    if best_strategy is not None:
        best_name = (
            best_strategy.get("name")
            or best_strategy.get("strategy_name")
            or "VisualBuilderStrategy"
        )

        # Generate classification tags and config hash for the best strategy
        tag_data = await tag_strategy_insight(
            best_strategy,
            best_pnl,
            best_kpis.get("win_rate", 0.0),
            best_kpis.get("trades", 0),
            user_id,
        )
        config_str = json.dumps(best_strategy)
        config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()

        async with async_session_factory() as db:
            await crud.create_agent_memory(
                db,
                user_id=user_id,
                memory_data=schemas.AgentMemoryCreate(
                    memory_type="optimization",
                    content=f"Best optimized strategy '{best_name}' on {resolved_symbol} ({best_strategy.get('timeframe', '15m')}): PnL={best_pnl:.2f}%, WR={best_kpis.get('win_rate', 0.0):.1f}%, DD={best_kpis.get('max_drawdown', 0.0):.1f}%. Config: {best_strategy}",
                    relevance_score=0.95,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                    tags=tag_data.get("tags", []),
                    symbol=resolved_symbol,
                    strategy_type=tag_data.get("strategy_type", "breakout"),
                    outcome="success" if best_pnl > 0.0 else "failure",
                    confidence=tag_data.get("confidence", 0.95),
                    validated_count=1,
                    config_hash=config_hash,
                ),
            )
            await db.commit()

        status_event = "success" if best_pnl > 0.0 else "partial_success"
        message_event = (
            f"Successfully optimized! Best variant found has positive PnL ({best_pnl:.2f}%)."
            if best_pnl > 0.0
            else f"Autopilot finished. Returned best candidate found (PnL: {best_pnl:.2f}%)."
        )

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": status_event,
                "message": message_event,
                "strategy_json": best_strategy,
                "kpis": best_kpis,
                "iteration": best_iteration,
            }
        )
