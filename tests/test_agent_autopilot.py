import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from api import ai_assistant, crud, schemas


def test_get_qwen_model_name_defaults_to_qwen_max(monkeypatch):
    monkeypatch.delenv("QWEN_MODEL", raising=False)
    assert ai_assistant._get_qwen_model_name() == "qwen-max"

    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")
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
    monkeypatch.setenv("QWEN_MODEL", "qwen-max")

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
