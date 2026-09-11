import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from api import ai_assistant, crud, models, schemas


@pytest.fixture(autouse=True)
def reset_ai_settings():
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    yield
    ai_assistant._DYNAMIC_AI_SETTINGS = None


def test_get_qwen_model_name_defaults_to_qwen_max(monkeypatch):
    monkeypatch.delenv("QWEN_MODEL", raising=False)
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    assert ai_assistant._get_qwen_model_name() == "qwen-3.8-max"

    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    assert ai_assistant._get_qwen_model_name() == "qwen-plus"


def test_extract_qwen_response_text_success():
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello from Qwen!"},
            }
        ]
    }
    assert (
        ai_assistant._extract_qwen_response_text(payload, require_complete=True)
        == "Hello from Qwen!"
    )


def test_extract_qwen_response_text_raises_on_incomplete():
    payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"role": "assistant", "content": "Hello from..."},
            }
        ]
    }
    with pytest.raises(ValueError, match="Qwen generation did not finish normally"):
        ai_assistant._extract_qwen_response_text(payload, require_complete=True)


def test_ensure_ai_provider_configured_requires_qwen_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "qwen")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("QWEN_MODEL", "qwen-3.8-max")
    ai_assistant._DYNAMIC_AI_SETTINGS = None

    with pytest.raises(ConnectionError, match="QWEN_API_KEY"):
        ai_assistant._ensure_ai_provider_configured()


@pytest.mark.asyncio
async def test_agent_memory_crud(db_session, test_user):
    # 1. Create a memory
    memory_data = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Failed on BTCUSDT with -10% return",
        relevance_score=0.9,
        expires_at=datetime.now(timezone.utc) + timedelta(days=5),
    )

    memory = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=memory_data
    )

    assert memory.id is not None
    assert memory.user_id == test_user.id
    assert memory.content == "Failed on BTCUSDT with -10% return"
    assert memory.relevance_score == 0.9

    # 2. Get active memories
    active_memories = await crud.get_agent_memories(db=db_session, user_id=test_user.id)
    assert len(active_memories) == 1
    assert active_memories[0].id == memory.id

    # 3. Test expired memories are filtered
    expired_memory_data = schemas.AgentMemoryCreate(
        memory_type="preference",
        content="User likes low risk",
        relevance_score=0.5,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
    )

    _expired_memory = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=expired_memory_data
    )

    # Active memories should still be 1 (expired one ignored)
    active_memories_after = await crud.get_agent_memories(
        db=db_session, user_id=test_user.id
    )
    assert len(active_memories_after) == 1
    assert active_memories_after[0].id == memory.id

    # 4. Delete expired memories
    deleted_count = await crud.delete_expired_memories(db=db_session)
    assert deleted_count == 1


@pytest.mark.asyncio
async def test_agent_memory_new_fields_crud(db_session, test_user):
    # Test creation and reading of memory with all new metadata fields
    memory_data = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Ascending triangle on ETHUSDT yielded +15% profit",
        relevance_score=0.85,
        tags=["breakout", "ascending_triangle", "trend_following"],
        symbol="ETHUSDT",
        strategy_type="VisualBuilderStrategy",
        outcome="profit",
        confidence=0.9,
        validated_count=2,
        config_hash="abcde12345",
    )

    memory = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=memory_data
    )

    assert memory.id is not None
    assert memory.tags == ["breakout", "ascending_triangle", "trend_following"]
    assert memory.symbol == "ETHUSDT"
    assert memory.strategy_type == "VisualBuilderStrategy"
    assert memory.outcome == "profit"
    assert memory.confidence == 0.9
    assert memory.validated_count == 2
    assert memory.config_hash == "abcde12345"


@pytest.mark.asyncio
async def test_search_agent_memories_advanced(db_session, test_user):
    # Setup multiple memories
    m1 = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Breakout on BTCUSDT",
        tags=["breakout", "btc"],
        symbol="BTCUSDT",
        strategy_type="BreakoutStrategy",
    )
    m2 = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Mean reversion on ETHUSDT",
        tags=["mean_reversion", "eth"],
        symbol="ETHUSDT",
        strategy_type="ReversionStrategy",
    )
    m3 = schemas.AgentMemoryCreate(
        memory_type="rule",
        content="Always use ADX filter in trending markets",
        tags=["trend", "adx"],
        symbol=None,  # Global rule
        strategy_type=None,
    )

    await crud.create_agent_memory(db=db_session, user_id=test_user.id, memory_data=m1)
    await crud.create_agent_memory(db=db_session, user_id=test_user.id, memory_data=m2)
    await crud.create_agent_memory(db=db_session, user_id=test_user.id, memory_data=m3)

    # 1. Search by tag overlap
    results = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, tags=["breakout"]
    )
    # Rules are always returned (m3) + matching tags (m1)
    assert len(results) == 2
    assert any(r.content == "Breakout on BTCUSDT" for r in results)
    assert any(
        r.content == "Always use ADX filter in trending markets" for r in results
    )

    # 2. Search by symbol
    results_sym = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, symbol="ETHUSDT"
    )
    # Returns ETHUSDT (m2) + global rules (m3)
    assert len(results_sym) == 2
    assert any(r.symbol == "ETHUSDT" for r in results_sym)
    assert any(r.memory_type == "rule" for r in results_sym)

    # 3. Search by strategy_type
    results_strat = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, strategy_type="BreakoutStrategy"
    )
    assert len(results_strat) >= 1
    assert any(r.strategy_type == "BreakoutStrategy" for r in results_strat)


@pytest.mark.asyncio
async def test_api_get_agent_memories_filtering(
    authenticated_client: AsyncClient, db_session, pro_user
):
    # authenticated_client works with pro_user
    m1 = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="API test breakout on BTCUSDT",
        tags=["api_breakout"],
        symbol="BTCUSDT",
        strategy_type="BreakoutStrategy",
    )
    await crud.create_agent_memory(db=db_session, user_id=pro_user.id, memory_data=m1)
    await db_session.commit()

    # Query with tag filter
    response = await authenticated_client.get("/api/v1/ai/memories?tag=api_breakout")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) >= 1
    assert data["data"][0]["content"] == "API test breakout on BTCUSDT"
    assert data["data"][0]["tags"] == ["api_breakout"]
    assert data["data"][0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_search_includes_community_memories(db_session, test_user, pro_user):
    # test_user has a private memory
    m1 = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="User private insight on ETHUSDT",
        tags=["eth", "breakout"],
        symbol="ETHUSDT",
        strategy_type="breakout",
        confidence=0.85,
    )
    await crud.create_agent_memory(db=db_session, user_id=test_user.id, memory_data=m1)

    # pro_user has a community memory
    m2 = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Pro user community insight on BTCUSDT",
        tags=["btc", "trend"],
        symbol="BTCUSDT",
        strategy_type="trend",
        confidence=0.90,
        visibility="community",
    )
    await crud.create_agent_memory(db=db_session, user_id=pro_user.id, memory_data=m2)
    await db_session.commit()

    # 1. Search without community -> only test_user's memory
    res_private = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, limit=10, include_community=False
    )
    assert len(res_private) == 1
    assert res_private[0].content == "User private insight on ETHUSDT"

    # 2. Search with community -> both test_user's memory and pro_user's community memory
    res_comm = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, limit=10, include_community=True
    )
    assert len(res_comm) == 2
    assert any(r.content == "User private insight on ETHUSDT" for r in res_comm)
    assert any(r.content == "Pro user community insight on BTCUSDT" for r in res_comm)


@pytest.mark.asyncio
async def test_community_dedup_by_config_hash(db_session, test_user, pro_user):
    shared_hash = "shared_hash_99999"
    m_local = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Local private version",
        symbol="SOLUSDT",
        config_hash=shared_hash,
    )
    await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=m_local
    )

    m_community = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Community version of same strategy",
        symbol="SOLUSDT",
        config_hash=shared_hash,
        visibility="community",
    )
    await crud.create_agent_memory(
        db=db_session, user_id=pro_user.id, memory_data=m_community
    )
    await db_session.commit()

    # When searching with community, the community version should be deduplicated
    results = await crud.search_agent_memories(
        db=db_session, user_id=test_user.id, limit=10, include_community=True
    )
    matching = [r for r in results if r.config_hash == shared_hash]
    assert len(matching) == 1
    assert matching[0].content == "Local private version"


@pytest.mark.asyncio
async def test_promote_memory_quality_gate(db_session, test_user):
    from tasks import async_maybe_promote_to_community

    # Enable community sharing for user
    test_user.share_community_memories = True
    await db_session.commit()

    # 1. Memory that FAILS quality gate: trades < 30
    mem_fail = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Profitable strategy on BTCUSDT: PnL=10.5%, WR=60.0%, DD=5.0%, trades=15, days=30.",
        outcome="success",
    )
    saved_fail = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=mem_fail
    )
    await db_session.commit()

    # 2. Memory that PASSES quality gate: trades >= 30, days >= 28
    mem_pass = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Profitable strategy on ETHUSDT: PnL=18.5%, WR=65.0%, DD=7.0%, trades=42, days=35. Config: {'sensitive': 'param'}",
        outcome="success",
        config_hash="strat_hash_pass_123",
    )
    saved_pass = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=mem_pass
    )
    await db_session.commit()

    # Direct call to async quality gate logic
    res_fail = await async_maybe_promote_to_community(
        saved_fail.id, test_user.id, session=db_session
    )
    assert res_fail["promoted"] is False
    assert res_fail["reason"] == "quality_gate_failed"

    res_pass = await async_maybe_promote_to_community(
        saved_pass.id, test_user.id, session=db_session
    )
    assert res_pass["promoted"] is True

    # 3. Legacy memory without trades= or days= in content, but outcome="success"
    mem_legacy = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Profitable strategy 'Legacy_EMA' on ETHUSDT (15m): PnL=18.5%, WR=65.0%, DD=7.0%. Weights: {'w': 1.0}. Reasoning: test. Config: {}",
        outcome="success",
        config_hash="legacy_hash_456",
    )
    saved_legacy = await crud.create_agent_memory(
        db=db_session, user_id=test_user.id, memory_data=mem_legacy
    )
    await db_session.commit()

    res_legacy = await async_maybe_promote_to_community(
        saved_legacy.id, test_user.id, session=db_session
    )
    assert res_legacy["promoted"] is True


@pytest.mark.asyncio
async def test_community_memory_protected_from_user_delete(
    db_session, test_user, pro_user
):
    comm_mem = schemas.AgentMemoryCreate(
        memory_type="strategy_insight",
        content="Community shared strategy",
        visibility="community",
    )
    saved = await crud.create_agent_memory(
        db=db_session, user_id=pro_user.id, memory_data=comm_mem
    )
    await db_session.commit()

    # Non-owner cannot delete
    del_other = await crud.delete_agent_memory(
        db=db_session, memory_id=saved.id, user_id=test_user.id
    )
    assert del_other is False

    # Bulk delete by any user does not delete community memories
    await crud.delete_agent_memories(db=db_session, user_id=pro_user.id)
    await db_session.commit()

    still_exists = await db_session.get(crud.models.AgentMemory, saved.id)
    assert still_exists is not None


@pytest.mark.asyncio
async def test_api_community_sharing_toggle(
    authenticated_client: AsyncClient, db_session, pro_user
):
    # Toggle community sharing ON
    res_on = await authenticated_client.put(
        "/api/v1/ai/memories/community-sharing", json={"enabled": True}
    )
    assert res_on.status_code == 200
    assert res_on.json()["share_community_memories"] is True

    await db_session.refresh(pro_user)
    assert pro_user.share_community_memories is True

    # Toggle community sharing OFF
    res_off = await authenticated_client.put(
        "/api/v1/ai/memories/community-sharing", json={"enabled": False}
    )
    assert res_off.status_code == 200
    assert res_off.json()["share_community_memories"] is False

    await db_session.refresh(pro_user)
    assert pro_user.share_community_memories is False


@pytest.mark.asyncio
async def test_api_share_agent_memory_and_retroactive_promotion(
    authenticated_client: AsyncClient, db_session, pro_user
):
    # 1. Create a private memory with >= 30 trades (legacy format without days)
    mem = models.AgentMemory(
        user_id=pro_user.id,
        memory_type="strategy_insight",
        content="Profitable strategy 'ETH_Breakout' on ETHUSDT (15m): PnL=15.2%, WR=62.0%, DD=8.1%, trades=35. Config: {'take_profit': 0.02, 'user_id': 999}",
        relevance_score=1.0,
        tags=["eth", "breakout"],
        symbol="ETHUSDT",
        strategy_type="breakout",
        outcome="success",
        confidence=0.9,
        config_hash="eth_hash_123",
        visibility="private",
    )
    db_session.add(mem)
    await db_session.commit()
    await db_session.refresh(mem)

    # 2. Test manual share endpoint
    res_share = await authenticated_client.post(f"/api/v1/ai/memories/{mem.id}/share")
    assert res_share.status_code == 200
    data = res_share.json()
    assert data["status"] == "success"
    assert data["community_memory_id"] is not None

    # Verify a community memory was created
    comm_mem = await db_session.get(models.AgentMemory, data["community_memory_id"])
    assert comm_mem.visibility == "community"
    assert "Config:" in comm_mem.content
    assert "take_profit" in comm_mem.content
    assert "user_id" not in comm_mem.content
    assert comm_mem.symbol == "ETHUSDT"

    # 3. Create another private memory with trades < 30 (should fail quality gate)
    low_trade_mem = models.AgentMemory(
        user_id=pro_user.id,
        memory_type="strategy_insight",
        content="Profitable strategy 'BTC_Scalp' on BTCUSDT (5m): PnL=2.0%, WR=50.0%, DD=5.0%, trades=10.",
        relevance_score=1.0,
        tags=["btc"],
        symbol="BTCUSDT",
        strategy_type="scalp",
        outcome="success",
        confidence=0.8,
        config_hash="btc_low_trades",
        visibility="private",
    )
    db_session.add(low_trade_mem)
    await db_session.commit()
    await db_session.refresh(low_trade_mem)

    res_fail = await authenticated_client.post(
        f"/api/v1/ai/memories/{low_trade_mem.id}/share"
    )
    assert res_fail.status_code == 400
    assert "at least 30 verified trades" in res_fail.json()["detail"]

    # 4. Test retroactive promotion: create private memory with 45 trades, then toggle enabled=True
    retro_mem = models.AgentMemory(
        user_id=pro_user.id,
        memory_type="strategy_insight",
        content="Profitable strategy 'SOL_Momentum' on SOLUSDT (1h): PnL=22.5%, WR=68.0%, DD=6.0%, trades=45.",
        relevance_score=1.0,
        tags=["sol", "momentum"],
        symbol="SOLUSDT",
        strategy_type="momentum",
        outcome="success",
        confidence=0.95,
        config_hash="sol_retro_hash",
        visibility="private",
    )
    db_session.add(retro_mem)
    await db_session.commit()

    res_toggle = await authenticated_client.put(
        "/api/v1/ai/memories/community-sharing", json={"enabled": True}
    )
    assert res_toggle.status_code == 200
    assert res_toggle.json()["promoted_count"] >= 1


def test_extract_pnl_and_config():
    from api.agent_autopilot import _extract_pnl, _extract_config

    # Test PnL extraction
    assert _extract_pnl("Strategy on BTC: PnL=15.50%, trades=25") == 15.5
    assert _extract_pnl("Strategy on ETH: PnL: -4.2%, trades=10") == -4.2
    assert _extract_pnl("No return info here") == 0.0

    # Test Config extraction (standard JSON)
    json_content = 'Profitable strategy on BTC: PnL=12.5%, trades=22. Config: {"name": "TestJson", "timeframe": "1h"}'
    cfg_json = _extract_config(json_content)
    assert cfg_json is not None
    assert cfg_json.get("name") == "TestJson"
    assert cfg_json.get("timeframe") == "1h"

    # Test Config extraction (Python dict string representation from past versions)
    python_repr_content = "Profitable strategy on ETH: PnL=18.2%, trades=30. Config: {'name': 'TestPy', 'timeframe': '15m', 'active': True}"
    cfg_py = _extract_config(python_repr_content)
    assert cfg_py is not None
    assert cfg_py.get("name") == "TestPy"
    assert cfg_py.get("timeframe") == "15m"
    assert cfg_py.get("active") is True

    # Test Config extraction with no config
    assert _extract_config("Just some notes without config") is None


def test_diversity_protocol_in_generator_prompt():
    from api.ai_assistant import load_prompt

    prompt = load_prompt("autopilot_generator_system.md")
    assert "# DIVERSITY & EXPERIMENTATION PROTOCOL (CRITICAL FOR SUCCESS)" in prompt
    assert "Trade Frequency Balance (Target >= 20 trades)" in prompt
    assert "Structural Variety Across Iterations" in prompt
    assert "Inspiration from Historical Configurations" in prompt


@pytest.mark.asyncio
async def test_run_memory_researcher_top_configs_injection(
    db_session, test_user, monkeypatch
):
    import json
    from unittest.mock import AsyncMock
    from api.agent_autopilot import run_memory_researcher_agent
    from api import agent_autopilot

    from contextlib import asynccontextmanager

    # Mock _generate_text_response so it does not call external LLMs
    async def mock_generate_text(*args, **kwargs):
        return "Synthesized: Use breakout above key levels."

    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    monkeypatch.setattr(ai_assistant, "_generate_text_response", mock_generate_text)
    monkeypatch.setattr("api.database.async_session_factory", mock_session_factory)
    monkeypatch.setattr(agent_autopilot, "async_session_factory", mock_session_factory)

    # Add 2 profitable strategy_insight memories with configs
    cfg1 = {"strategy_name": "HighPnL_BTC", "entryTrigger": {"type": "on_candle_close"}}
    cfg2 = {
        "strategy_name": "MediumPnL_BTC",
        "entryTrigger": {"type": "on_candle_close"},
    }

    mem1 = models.AgentMemory(
        user_id=test_user.id,
        memory_type="strategy_insight",
        content=f"Profitable strategy 'HighPnL_BTC' on BTCUSDT (15m): PnL=28.50%, WR=65.0%, trades=35. Config: {json.dumps(cfg1)}",
        relevance_score=1.0,
        symbol="BTCUSDT",
        strategy_type="breakout",
        outcome="success",
        confidence=1.0,
        visibility="private",
    )
    mem2 = models.AgentMemory(
        user_id=test_user.id,
        memory_type="strategy_insight",
        content=f"Profitable strategy 'MediumPnL_BTC' on BTCUSDT (15m): PnL=14.20%, WR=55.0%, trades=22. Config: {json.dumps(cfg2)}",
        relevance_score=1.0,
        symbol="BTCUSDT",
        strategy_type="breakout",
        outcome="success",
        confidence=1.0,
        visibility="private",
    )
    db_session.add_all([mem1, mem2])
    await db_session.commit()

    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()

    summary = await run_memory_researcher_agent(
        user_id=test_user.id,
        symbol="BTCUSDT",
        user_prompt="Find breakout strategy for BTC",
        websocket=mock_ws,
    )

    assert "## PROVEN HIGH-PERFORMING STRATEGY CONFIGURATIONS (INSPIRATION):" in summary
    assert "HighPnL_BTC" in summary
    assert "MediumPnL_BTC" in summary
    assert "Historical PnL: +28.50%" in summary


@pytest.mark.asyncio
async def test_community_tag_discovery_for_new_user(db_session, test_user, monkeypatch):
    from contextlib import asynccontextmanager
    from api.agent_autopilot import run_memory_researcher_agent
    from api import agent_autopilot
    from unittest.mock import AsyncMock

    test_user.share_community_memories = True
    db_session.add(test_user)

    # Community memory created by user 999
    comm_mem = models.AgentMemory(
        user_id=999,
        memory_type="strategy_insight",
        content="Profitable community strategy on ETHUSDT: PnL=15.0%, trades=25.",
        relevance_score=1.0,
        tags=["community_alpha_breakout"],
        symbol="ETHUSDT",
        strategy_type="breakout",
        outcome="success",
        confidence=1.0,
        visibility="community",
    )
    db_session.add(comm_mem)
    await db_session.commit()

    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    monkeypatch.setattr("api.database.async_session_factory", mock_session_factory)
    monkeypatch.setattr(agent_autopilot, "async_session_factory", mock_session_factory)

    async def mock_generate_text(*args, **kwargs):
        return "Synthesized summary"

    monkeypatch.setattr(ai_assistant, "_generate_text_response", mock_generate_text)

    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()

    # User prompt containing the community tag
    await run_memory_researcher_agent(
        user_id=test_user.id,
        symbol="ETHUSDT",
        user_prompt="I want a community_alpha_breakout setup",
        websocket=mock_ws,
    )

    # Verify that the websocket was called with status mentioning the matched community tag
    found_tag_query = False
    for call in mock_ws.send_json.call_args_list:
        args, kwargs = call
        if args and "community_alpha_breakout" in str(args[0]):
            found_tag_query = True
            break
    assert found_tag_query, (
        "Expected memory researcher to match community tag from prompt"
    )
