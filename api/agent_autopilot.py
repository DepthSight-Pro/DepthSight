# api/agent_autopilot.py

import asyncio
import logging
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from fastapi import WebSocket

from api.database import async_session_factory
from api import crud, schemas, ai_assistant
from api.ai_assistant import _generate_json_response

logger = logging.getLogger(__name__)


def guess_symbol_from_prompt(prompt: str, default: str = "BTCUSDT") -> str:
    """Guesses the asset symbol from the prompt text."""
    prompt_upper = prompt.upper()
    for s in ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LTC"]:
        if s in prompt_upper:
            return f"{s}USDT"
    return default


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
                select(models.AgentMemory.tags)
                .where(models.AgentMemory.user_id == user_id)
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
                        rule.confidence = max(0.0, rule.confidence - 0.2)
                        rule.validated_count = (rule.validated_count or 0) - 1
                        logger.info(
                            f"Rule {rule.id} penalized. New conf: {rule.confidence}"
                        )

                        if rule.confidence <= 0.3 or rule.validated_count <= -2:
                            logger.warning(
                                f"Rule {rule.id} DEPRECATED due to repeated failures."
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
) -> str:
    """Queries the database for user memories and synthesizes a concise trading summary."""
    from api import crud, models
    from api.database import async_session_factory
    from api.ai_assistant import _generate_text_response
    from sqlalchemy import select

    try:
        # Fetch all unique tags from DB to match against the user prompt
        prompt_tags = []
        async with async_session_factory() as db:
            db_tags = set()
            try:
                result = await db.execute(
                    select(models.AgentMemory.tags)
                    .where(models.AgentMemory.user_id == user_id)
                )
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
            status_message = "🤖 Memory Researcher Agent: Querying past trading sessions..."

        await websocket.send_json(
            {
                "event": "autopilot_status",
                "status": "thinking",
                "message": status_message,
            }
        )

        search_tags = prompt_tags if prompt_tags else None

        async with async_session_factory() as db:
            # 1. Fetch rules
            rules = await crud.search_agent_memories(
                db, user_id=user_id, memory_type="rule", tags=search_tags, limit=10
            )
            # 2. Fetch symbol insights
            exact_insights = await crud.search_agent_memories(
                db,
                user_id=user_id,
                memory_type="strategy_insight",
                symbol=symbol,
                tags=search_tags,
                limit=15,
            )
            # 3. Fetch transfer insights if exact_insights is small
            transfer_insights = []
            if len(exact_insights) < 10:
                all_insights = await crud.search_agent_memories(
                    db, user_id=user_id, memory_type="strategy_insight", tags=search_tags, limit=15
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
                raw_memories.append(f"- {r.content}")
        if exact_insights:
            raw_memories.append(f"\nPast Backtest Insights for {symbol}:")
            for m in exact_insights:
                raw_memories.append(
                    f"- Outcome: {m.outcome.upper()} | Content: {m.content}"
                )
        if transfer_insights:
            raw_memories.append(
                "\nCross-Asset Backtest Insights (transferable lessons):"
            )
            for m in transfer_insights:
                raw_memories.append(
                    f"- Asset: {m.symbol} | Outcome: {m.outcome.upper()} | Content: {m.content}"
                )

        memories_text = "\n".join(raw_memories)

        system_instruction = MEMORY_RESEARCHER_SYSTEM_PROMPT

        user_content = (
            f"User Request: {user_prompt}\n"
            f"Target Symbol: {symbol}\n\n"
            f"Raw Memories:\n"
            f"{memories_text}\n\n"
            f"Based on the above, synthesize the trading rules and insights for {symbol}."
        )

        summary_text = await _generate_text_response(
            system_instruction=system_instruction,
            messages=[{"role": "user", "content": user_content}],
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
) -> str:
    """Compares the last run's configuration and results with the best configuration and historical rules, then writes concrete recommendations."""
    from api.ai_assistant import _get_active_ai_provider, _generate_json_response, _generate_text_response
    from api import crud, models
    from api.database import async_session_factory
    from sqlalchemy import select

    # Fetch all unique tags from DB for this user to pass to Advisor
    db_tags = set()
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(models.AgentMemory.tags)
                .where(models.AgentMemory.user_id == user_id)
            )
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
            'breakout', 'reversion', 'trend', 'scalping', 'volatility_squeeze', 
            'rel_vol_filter', 'classic_pattern', 'price_action_analyzer', 
            'price_consolidation', 'EMA', 'ADX', 'RSI'
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
            "volatility_squeeze", "rel_vol_filter", "trend_filter", 
            "price_action_analyzer", "price_consolidation", "classic_pattern",
            "return_to_level", "level_touch_analyzer", "move_to_breakeven", "conditional_management"
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
    advisor_user_prompt = (
        f"Target Asset: {symbol}\n\n"
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
        logger.warning(f"Strategy Advisor tool call failed ({e}). Running fallback tag extraction.")
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
            memories = await crud.search_agent_memories(
                db, user_id=user_id, tags=tags, symbol=symbol, limit=8
            )
            for m in memories:
                icon = "success" if m.outcome == "success" else "failure"
                retrieved_lines.append(f"- [{icon.upper()}] {m.content}")

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
    retrieved_context = "\n".join(retrieved_lines) if retrieved_lines else "No matching historical memories found."
    
    # Construct assistant response representation of Turn 0
    if not fallback_used and raw_tool_json:
        assistant_turn_0 = raw_tool_json
    else:
        assistant_turn_0 = json.dumps({
            "function": "search_advisor_memory",
            "arguments": {
                "tags": tags,
                "symbol": symbol
            }
        }, indent=2)

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
        {"role": "user", "content": advisor_turn_1_prompt}
    ]

    try:
        advice_text = await _generate_text_response(
            system_instruction=system_prompt_with_tags,
            messages=messages,
        )
        
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

    # Initial guess for the symbol to build system instructions
    resolved_symbol = (symbol or guess_symbol_from_prompt(user_prompt)).upper()

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
            )
            # Combine the historical rules and the dynamic advice so the generator retains both
            memory_summary = f"{initial_memory_rules}\n\n# CURRENT SESSION STRATEGIC ADVICE:\n{advisor_advice}"

        # Build prompt including current feedback if previous iteration failed
        autopilot_instruction = _load_prompt("autopilot_system.md").format(
            resolved_symbol=resolved_symbol
        )
        active_prompt = f"{autopilot_instruction}\n\nUser Request: Find a profitable strategy for {resolved_symbol} based on: '{user_prompt}'"
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
            ai_symbols = strategy_json.get("symbols") or strategy_json.get(
                "config_data", {}
            ).get("symbols")
            if (
                ai_symbols
                and isinstance(ai_symbols, list)
                and len(ai_symbols) > 0
                and ai_symbols[0]
            ):
                resolved_symbol = str(ai_symbols[0]).upper()
            elif strategy_json.get("symbol"):
                resolved_symbol = str(strategy_json.get("symbol")).upper()

            # Extract parameters generated dynamically by the model
            start_date = strategy_json.get("start_date") or "2025-01-01"
            end_date = strategy_json.get("end_date") or "2025-12-31"
            timeframe = strategy_json.get("timeframe") or "15m"

            strategy_display_name = (
                strategy_json.get("name")
                or strategy_json.get("strategy_name")
                or f"Variant {chr(64 + i)}"
            )

            # Synchronize timeframe across all fields to ensure the engine and trainer load it correctly
            strategy_json["candle_timeframe"] = timeframe
            strategy_json["entry_timeframe"] = timeframe
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
        if total_pnl > 0.0 and trades_count >= 5:
            # We found a winning strategy! Save memory of success
            reasoning = strategy_json.get("reasoning", "")
            filters_list = [
                f.get("type")
                for f in strategy_json.get("filters", {}).get("children", [])
            ]
            content = f"Profitable strategy '{strategy_display_name}' on {resolved_symbol} ({timeframe}): PnL={total_pnl:.2f}%, WR={win_rate:.1f}%, DD={max_dd:.1f}%. Weights: {strategy_json.get('foundation_weights')}, Filters: {filters_list}. Reasoning: {reasoning}. Config: {strategy_json}"

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
            insight = f"Failed strategy '{strategy_display_name}' on {resolved_symbol} ({timeframe}): PnL={total_pnl:.2f}%, WR={win_rate:.1f}%, trades={trades_count}. Reason: {reason}. Weights: {strategy_json.get('foundation_weights')}, Filters: {filters_list}. Reasoning: {reasoning}. Config: {strategy_json}"

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
                f"Please analyze the recent history and optimize the configuration further to get higher PnL."
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
