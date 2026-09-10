"""
Tests for DepthSight Model Context Protocol (MCP 2025-03-26) Server.
Verifies Streamable HTTP and SSE transports, authentication, tool calls, resources, and prompts.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import models


@pytest.mark.asyncio
async def test_mcp_unauthenticated_rejected(test_client: AsyncClient):
    """Verifies that MCP endpoints require authentication."""
    resp = await test_client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_initialize(authenticated_client: AsyncClient):
    """Verifies standard MCP protocol handshake and version negotiation."""
    # 1. Modern 2026-07-28 handshake
    req = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "test-agent", "version": "1.0"},
        },
    }
    resp = await authenticated_client.post("/api/v1/mcp", json=req)
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "req-1"
    result = data["result"]
    assert result["protocolVersion"] == "2026-07-28"
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]
    assert "prompts" in result["capabilities"]
    assert result["serverInfo"]["name"] == "depthsight-mcp"
    assert "Agent Trading & Memory Protocol" in result["instructions"]
    assert "search_agent_memory" in result["instructions"]
    assert "Stagnation Prevention (Patience = 3)" in result["instructions"]

    # 2. Backward-compatible negotiation with legacy 2025-03-26 client
    req_legacy = {
        "jsonrpc": "2.0",
        "id": "req-legacy",
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26"},
    }
    resp_legacy = await authenticated_client.post("/api/v1/mcp", json=req_legacy)
    assert resp_legacy.status_code == 200
    assert resp_legacy.json()["result"]["protocolVersion"] == "2025-03-26"


@pytest.mark.asyncio
async def test_mcp_ping(authenticated_client: AsyncClient):
    """Verifies ping/liveness check."""
    req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    resp = await authenticated_client.post("/api/v1/mcp", json=req)
    assert resp.status_code == 200
    assert resp.json()["result"] == {}


@pytest.mark.asyncio
async def test_mcp_tools_list(authenticated_client: AsyncClient):
    """Verifies tools/list returns complete catalog with valid schemas."""
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    resp = await authenticated_client.post("/api/v1/mcp", json=req)
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    expected_tools = [
        "get_strategy_schema_and_examples",
        "get_market_metrics",
        "get_historical_data_range",
        "run_backtest",
        "list_strategies",
        "get_strategy",
        "save_strategy",
        "search_agent_memory",
        "store_agent_memory",
        "get_bot_status",
        "get_open_positions",
        "get_trading_analytics",
    ]
    for expected in expected_tools:
        assert expected in tool_names, f"Expected tool '{expected}' not in MCP catalog."


@pytest.mark.asyncio
async def test_mcp_tool_get_strategy_schema(authenticated_client: AsyncClient):
    """Verifies agent can fetch strategy schemas and examples for context."""
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "get_strategy_schema_and_examples",
            "arguments": {"category": "all"},
        },
    }
    resp = await authenticated_client.post("/api/v1/mcp", json=req)
    assert resp.status_code == 200
    content = resp.json()["result"]["content"][0]["text"]
    assert "STRICT TYPE VALIDATION" in content
    assert "trend_filter" in content
    assert "open_position" in content
    assert "DATA FLOW" in content
    assert "codebase_reference" in content

    # 2. Test memory_guide category
    req_mem = {
        "jsonrpc": "2.0",
        "id": "4b",
        "method": "tools/call",
        "params": {
            "name": "get_strategy_schema_and_examples",
            "arguments": {"category": "memory_guide"},
        },
    }
    resp_mem = await authenticated_client.post("/api/v1/mcp", json=req_mem)
    assert resp_mem.status_code == 200
    mem_content = resp_mem.json()["result"]["content"][0]["text"]
    assert "Rule Synthesis & Deduplication" in mem_content
    assert "Classification & Tagging Conventions" in mem_content

    # 3. Test block_name query
    req_block = {
        "jsonrpc": "2.0",
        "id": "4c",
        "method": "tools/call",
        "params": {
            "name": "get_strategy_schema_and_examples",
            "arguments": {"block_name": "trend_filter"},
        },
    }
    resp_block = await authenticated_client.post("/api/v1/mcp", json=req_block)
    assert resp_block.status_code == 200
    block_content = resp_block.json()["result"]["content"][0]["text"]
    assert "Codebase Reference for 'trend_filter'" in block_content
    assert "```python" in block_content


@pytest.mark.asyncio
async def test_mcp_tool_get_market_metrics(authenticated_client: AsyncClient):
    """Verifies agent can retrieve market intelligence for a pair."""
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "get_market_metrics",
            "arguments": {"symbol": "BTCUSDT"},
        },
    }
    resp = await authenticated_client.post("/api/v1/mcp", json=req)
    assert resp.status_code == 200
    content = resp.json()["result"]["content"][0]["text"]
    assert "BTCUSDT" in content


@pytest.mark.asyncio
async def test_mcp_strategy_and_memory_tools(
    authenticated_client: AsyncClient,
    pro_user: models.User,
    db_session: AsyncSession,
):
    """Verifies strategy CRUD and explicit agent memory storage via MCP tools."""
    # 1. Save Strategy
    sample_strategy = {
        "name": "MCP_Test_Strategy",
        "symbol": "ETHUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "filters": {"type": "AND", "children": []},
        "entryConditions": {"type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "params": {}},
        "initialization": {
            "type": "open_position",
            "params": {
                "side": "LONG",
                "position_size_type": "PERCENT_EQUITY",
                "position_size_value": 10.0,
                "stop_loss_pct": 1.0,
                "take_profit_pct": 2.0,
            },
        },
        "positionManagement": [],
    }

    save_req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "save_strategy",
            "arguments": {
                "name": "MCP_Test_Strategy",
                "strategy_config": sample_strategy,
                "symbol": "ETHUSDT",
                "timeframe": "15m",
            },
        },
    }
    save_resp = await authenticated_client.post("/api/v1/mcp", json=save_req)
    assert save_resp.status_code == 200
    save_text = save_resp.json()["result"]["content"][0]["text"]
    assert "successfully saved" in save_text

    # 2. List Strategies
    list_req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "list_strategies", "arguments": {}},
    }
    list_resp = await authenticated_client.post("/api/v1/mcp", json=list_req)
    assert list_resp.status_code == 200
    list_text = list_resp.json()["result"]["content"][0]["text"]
    assert "MCP_Test_Strategy" in list_text

    # 3. Store Agent Memory
    mem_store_req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "store_agent_memory",
            "arguments": {
                "content": "RSI oversold bounces on 15m ETHUSDT show 68% win rate when ADX > 22.",
                "strategy_type": "mean_reversion",
                "tags": ["eth", "rsi", "adx", "pullback"],
                "outcome": "success",
                "confidence": 0.9,
                "symbol": "ETHUSDT",
            },
        },
    }
    mem_resp = await authenticated_client.post("/api/v1/mcp", json=mem_store_req)
    assert mem_resp.status_code == 200
    assert (
        "Insight saved to persistent memory bank"
        in mem_resp.json()["result"]["content"][0]["text"]
    )

    # 4. Search Agent Memory
    search_req = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "search_agent_memory",
            "arguments": {"symbol": "ETHUSDT", "tags": ["rsi"]},
        },
    }
    search_resp = await authenticated_client.post("/api/v1/mcp", json=search_req)
    assert search_resp.status_code == 200
    search_text = search_resp.json()["result"]["content"][0]["text"]
    assert "RSI oversold bounces" in search_text


@pytest.mark.asyncio
async def test_mcp_bot_status_positions_and_analytics(
    authenticated_client: AsyncClient,
    pro_user: models.User,
    db_session: AsyncSession,
    mock_redis_client,
):
    """Verifies get_bot_status, get_open_positions, and get_trading_analytics."""
    import json
    from datetime import datetime, timezone
    from uuid import uuid4

    # 1. Test get_bot_status (mock bot in Redis)
    mock_bot = [
        {
            "strategy_name": "Scalping_ETH",
            "symbol": "ETHUSDT",
            "mode": "paper",
            "state": "RUNNING",
            "candle_timeframe": "5m",
            "user_id": pro_user.id,
        }
    ]
    await mock_redis_client.set(
        f"depthsight:state:strategies:{pro_user.id}:1", json.dumps(mock_bot)
    )

    bot_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "get_bot_status", "arguments": {"mode": "all"}},
        },
    )
    assert bot_resp.status_code == 200
    bot_text = bot_resp.json()["result"]["content"][0]["text"]
    assert "Scalping_ETH" in bot_text
    assert "ETHUSDT" in bot_text

    # 2. Test get_open_positions (mock position in Redis)
    mock_pos = [
        {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "amount": 0.05,
            "entry_price": 60000.0,
            "mark_price": 61200.0,
            "unrealized_pnl": 60.0,
            "unrealized_pnl_pct": 2.0,
            "stop_loss": 59000.0,
            "take_profit": 63000.0,
            "mode": "live",
            "user_id": pro_user.id,
            "strategy_name": "Breakout_BTC",
        }
    ]
    await mock_redis_client.set(
        f"depthsight:state:positions:{pro_user.id}:1", json.dumps(mock_pos)
    )

    pos_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "get_open_positions", "arguments": {}},
        },
    )
    assert pos_resp.status_code == 200
    pos_text = pos_resp.json()["result"]["content"][0]["text"]
    assert "BTCUSDT" in pos_text
    assert "LONG" in pos_text
    assert "60.00" in pos_text

    # 3. Test get_trading_analytics (seed Trade model in DB)
    trade = models.Trade(
        user_id=pro_user.id,
        trade_uuid=str(uuid4()),
        timestamp_close=datetime.now(timezone.utc),
        symbol="SOLUSDT",
        direction="LONG",
        entry_price=140.0,
        exit_price=150.0,
        pnl=50.0,
        commission=1.5,
        exit_reason="TP",
        quantity=5.0,
        trade_mode="LIVE",
    )
    db_session.add(trade)
    await db_session.commit()

    analytics_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "get_trading_analytics",
                "arguments": {"mode": "live"},
            },
        },
    )
    assert analytics_resp.status_code == 200
    analytics_text = analytics_resp.json()["result"]["content"][0]["text"]
    assert "Trading Performance Analytics" in analytics_text
    assert "SOLUSDT" in analytics_text
    assert "Net PnL" in analytics_text


@pytest.mark.asyncio
async def test_mcp_resources_and_prompts(authenticated_client: AsyncClient):
    """Verifies MCP resource reading and prompt generation for context."""
    # 1. Resources list
    r_list = await authenticated_client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 10, "method": "resources/list"},
    )
    assert r_list.status_code == 200
    resources = r_list.json()["result"]["resources"]
    assert any(r["uri"] == "depthsight://docs/strategy_schema.json" for r in resources)
    assert any(r["uri"] == "depthsight://docs/codebase_reference.md" for r in resources)
    assert any(r["uri"] == "depthsight://docs/memory_protocol.md" for r in resources)
    assert any(r["uri"] == "depthsight://docs/allowed_blocks.md" for r in resources)
    assert any(r["uri"] == "depthsight://docs/available_history.md" for r in resources)

    # 2. Resource read - schema
    r_read = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "resources/read",
            "params": {"uri": "depthsight://docs/strategy_schema.json"},
        },
    )
    assert r_read.status_code == 200
    contents = r_read.json()["result"]["contents"]
    assert len(contents) > 0
    assert "Visual Builder" in contents[0]["text"]

    # 2b. Resource read - memory protocol
    r_read_mem = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "11b",
            "method": "resources/read",
            "params": {"uri": "depthsight://docs/memory_protocol.md"},
        },
    )
    assert r_read_mem.status_code == 200
    contents_mem = r_read_mem.json()["result"]["contents"]
    assert len(contents_mem) > 0
    assert "Rule Synthesis & Deduplication" in contents_mem[0]["text"]

    # 3. Prompts get
    p_get = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "prompts/get",
            "params": {
                "name": "depthsight_quant_developer",
                "arguments": {"trading_style": "scalping", "target_symbol": "SOLUSDT"},
            },
        },
    )
    assert p_get.status_code == 200
    messages = p_get.json()["result"]["messages"]
    assert len(messages) > 0
    assert "SOLUSDT" in messages[0]["content"]["text"]


@pytest.mark.asyncio
async def test_mcp_sse_session_and_messages(
    authenticated_client: AsyncClient,
    pro_user: models.User,
):
    """Verifies SSE session handshake and message dispatch."""
    from api.mcp.sse import sse_session_manager

    # 1. Create a session directly to simulate SSE connection
    session = await sse_session_manager.create_session(user_id=pro_user.id)
    assert session.session_id in sse_session_manager.sessions

    # 2. Post a message to /messages?session_id=...
    post_resp = await authenticated_client.post(
        f"/api/v1/mcp/messages?session_id={session.session_id}",
        json={"jsonrpc": "2.0", "id": "sse-msg-1", "method": "ping"},
    )
    assert post_resp.status_code == 202

    # 3. Verify response was queued into session's queue
    event_payload = await session.queue.get()
    assert "event: message" in event_payload
    assert '"id": "sse-msg-1"' in event_payload

    # Cleanup
    await sse_session_manager.remove_session(session.session_id)


@pytest.mark.asyncio
async def test_mcp_pat_token_lifecycle(
    authenticated_client: AsyncClient,
    test_client: AsyncClient,
    pro_user: models.User,
):
    """Verifies complete lifecycle of Personal Access Tokens (PAT): creation, auth, query, revocation."""
    # 1. Create a new PAT
    create_resp = await authenticated_client.post(
        "/api/v1/mcp/tokens",
        json={"name": "Claude Desktop Home", "expires_days": 90},
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()["data"]
    token_id = created_data["id"]
    raw_pat = created_data["token"]
    assert raw_pat.startswith("ds_pat_")
    assert created_data["name"] == "Claude Desktop Home"

    # 2. List PATs
    list_resp = await authenticated_client.get("/api/v1/mcp/tokens")
    assert list_resp.status_code == 200
    tokens_list = list_resp.json()["data"]
    assert any(t["id"] == token_id for t in tokens_list)

    # 3. Authenticate with unauthenticated test_client using PAT in Authorization header
    mcp_resp_header = await test_client.post(
        "/api/v1/mcp",
        headers={"Authorization": f"Bearer {raw_pat}"},
        json={"jsonrpc": "2.0", "id": 100, "method": "ping"},
    )
    assert mcp_resp_header.status_code == 200
    assert mcp_resp_header.json()["result"] == {}

    # 4. Authenticate with PAT in query parameter (?token=ds_pat_...)
    mcp_resp_query = await test_client.post(
        f"/api/v1/mcp?token={raw_pat}",
        json={"jsonrpc": "2.0", "id": 101, "method": "ping"},
    )
    assert mcp_resp_query.status_code == 200
    assert mcp_resp_query.json()["result"] == {}

    # 5. Revoke / Delete PAT
    del_resp = await authenticated_client.delete(f"/api/v1/mcp/tokens/{token_id}")
    assert del_resp.status_code == 204

    # 6. Try to authenticate again with revoked PAT -> Rejected!
    rejected_resp = await test_client.post(
        "/api/v1/mcp",
        headers={"Authorization": f"Bearer {raw_pat}"},
        json={"jsonrpc": "2.0", "id": 102, "method": "ping"},
    )
    assert rejected_resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_plan_restrictions_and_pro_blocks(
    free_user_client: AsyncClient,
    pro_user_client: AsyncClient,
):
    """Verifies that non-Pro users cannot use Pro blocks or Precision backtest engine via MCP."""
    # 1. Non-Pro user tries to run Precision engine
    standard_strategy = {
        "name": "Basic_Strategy",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "filters": {"type": "AND", "children": []},
        "entryConditions": {"type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "params": {}},
        "initialization": {
            "type": "open_position",
            "params": {
                "side": "LONG",
                "position_size_type": "PERCENT_EQUITY",
                "position_size_value": 10.0,
            },
        },
    }

    req_precision = {
        "jsonrpc": "2.0",
        "id": 103,
        "method": "tools/call",
        "params": {
            "name": "run_backtest",
            "arguments": {
                "symbol": "BTCUSDT",
                "strategy_config": standard_strategy,
                "start_date": "2025-06-01",
                "end_date": "2025-06-10",
                "engine": "precision",
            },
        },
    }
    resp_precision = await free_user_client.post("/api/v1/mcp", json=req_precision)
    assert resp_precision.status_code == 200
    text_precision = resp_precision.json()["result"]["content"][0]["text"]
    assert "Plan Restriction Error" in text_precision
    assert "Precision Engine is available on the Pro plan only" in text_precision

    # 2. Non-Pro user tries to use a PRO-only block (e.g. btc_state_filter)
    pro_strategy = {
        "name": "Pro_Blocked_Strategy",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "filters": {
            "type": "AND",
            "children": [
                {"type": "btc_state_filter", "params": {"state": "Trending Up"}}
            ],
        },
        "entryConditions": {"type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "params": {}},
        "initialization": {
            "type": "open_position",
            "params": {
                "side": "LONG",
                "position_size_type": "PERCENT_EQUITY",
                "position_size_value": 10.0,
            },
        },
    }
    req_pro_block = {
        "jsonrpc": "2.0",
        "id": 104,
        "method": "tools/call",
        "params": {
            "name": "save_strategy",
            "arguments": {
                "name": "Pro_Blocked_Strategy",
                "strategy_config": pro_strategy,
            },
        },
    }
    resp_pro = await free_user_client.post("/api/v1/mcp", json=req_pro_block)
    assert resp_pro.status_code == 200
    text_pro = resp_pro.json()["result"]["content"][0]["text"]
    assert "contains Pro-only blocks" in text_pro or "Upgrade to Pro" in text_pro


@pytest.mark.asyncio
async def test_mcp_historical_data_range_and_backtest_bounds(
    authenticated_client: AsyncClient,
    mock_redis_client,
):
    """Verifies get_historical_data_range tool and run_backtest boundary validation."""
    import json

    # 1. Seed mock storage data in Redis
    mock_storage = [
        {
            "symbol": "BTCUSDT",
            "timeframes": ["1m", "5m", "15m", "1h"],
            "klines_1m": {
                "start_date": "2025-01-01",
                "end_date": "2026-07-12",
                "size_mb": 45.2,
                "is_enriched": True,
            },
            "has_aggtrades": True,
            "has_klines_1s": True,
            "has_oi": True,
            "has_depth": True,
        },
        {
            "symbol": "ETHUSDT",
            "timeframes": ["1m", "15m"],
            "klines_1m": {
                "start_date": "2025-06-01",
                "end_date": "2026-06-30",
                "size_mb": 25.0,
                "is_enriched": False,
            },
            "has_aggtrades": False,
            "has_klines_1s": False,
            "has_oi": False,
            "has_depth": False,
        },
    ]
    await mock_redis_client.set(
        "depthsight:admin:storage_info", json.dumps(mock_storage)
    )

    # 2. Call get_historical_data_range without arguments (full table)
    resp_all = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 200,
            "method": "tools/call",
            "params": {"name": "get_historical_data_range", "arguments": {}},
        },
    )
    assert resp_all.status_code == 200
    text_all = resp_all.json()["result"]["content"][0]["text"]
    assert "DepthSight Historical Market Storage" in text_all
    assert "BTCUSDT" in text_all
    assert "ETHUSDT" in text_all
    assert "`2025-01-01` to `2026-07-12`" in text_all

    # 3. Call get_historical_data_range for a specific symbol (BTCUSDT)
    resp_btc = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 201,
            "method": "tools/call",
            "params": {
                "name": "get_historical_data_range",
                "arguments": {"symbol": "BTCUSDT"},
            },
        },
    )
    assert resp_btc.status_code == 200
    text_btc = resp_btc.json()["result"]["content"][0]["text"]
    assert "Historical Data Coverage: **BTCUSDT**" in text_btc
    assert "`2025-01-01` to `2026-07-12`" in text_btc
    assert "Orderbook Depth (bookDepth)" in text_btc
    assert "✅ Available" in text_btc
    assert "Open Interest (OI)" in text_btc

    # 4. Call get_historical_data_range for unknown symbol
    resp_unknown = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 202,
            "method": "tools/call",
            "params": {
                "name": "get_historical_data_range",
                "arguments": {"symbol": "NONEXISTENTUSDT"},
            },
        },
    )
    assert resp_unknown.status_code == 200
    text_unknown = resp_unknown.json()["result"]["content"][0]["text"]
    assert "Symbol **NONEXISTENTUSDT** has no historical data loaded" in text_unknown

    # 5. run_backtest on unsupported symbol -> rejected with diagnostic
    sample_strategy = {
        "name": "Test_Strat",
        "symbol": "NONEXISTENTUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "filters": {"type": "AND", "children": []},
        "entryConditions": {"type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "params": {}},
        "initialization": {
            "type": "open_position",
            "params": {
                "side": "LONG",
                "position_size_type": "PERCENT_EQUITY",
                "position_size_value": 10.0,
            },
        },
    }
    resp_bt_unsupported = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 203,
            "method": "tools/call",
            "params": {
                "name": "run_backtest",
                "arguments": {
                    "symbol": "NONEXISTENTUSDT",
                    "strategy_config": sample_strategy,
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-10",
                },
            },
        },
    )
    assert resp_bt_unsupported.status_code == 200
    text_bt_unsupported = resp_bt_unsupported.json()["result"]["content"][0]["text"]
    assert "Historical Data Error" in text_bt_unsupported
    assert (
        "Symbol 'NONEXISTENTUSDT' has no historical data loaded" in text_bt_unsupported
    )

    # 6. run_backtest with dates out of bounds (e.g. 2024 before 2025) -> rejected with valid boundaries
    resp_bt_out_of_bounds = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 204,
            "method": "tools/call",
            "params": {
                "name": "run_backtest",
                "arguments": {
                    "symbol": "BTCUSDT",
                    "strategy_config": sample_strategy,
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-01",
                },
            },
        },
    )
    assert resp_bt_out_of_bounds.status_code == 200
    text_bt_out_of_bounds = resp_bt_out_of_bounds.json()["result"]["content"][0]["text"]
    assert "Historical Date Range Error" in text_bt_out_of_bounds
    assert (
        "outside the loaded historical data for BTCUSDT (2025-01-01 to 2026-07-12)"
        in text_bt_out_of_bounds
    )

    # 7. Read available_history.md resource
    res_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 205,
            "method": "resources/read",
            "params": {"uri": "depthsight://docs/available_history.md"},
        },
    )
    assert res_resp.status_code == 200
    res_text = res_resp.json()["result"]["contents"][0]["text"]
    assert "DepthSight Historical Market Storage" in res_text


@pytest.mark.asyncio
async def test_mcp_memory_tag_pooling_and_autopilot_guidance(
    authenticated_client: AsyncClient,
    pro_user: models.User,
    db_session: AsyncSession,
    mocker,
):
    """Verifies database tag pooling, tag normalization, and autopilot instructions in MCP."""
    from api import crud, schemas

    # 1. Direct DB check for get_unique_agent_tags
    await crud.create_agent_memory(
        db=db_session,
        user_id=pro_user.id,
        memory_data=schemas.AgentMemoryCreate(
            content="Breakout test memory 1",
            strategy_type="breakout",
            tags=["Breakout", "VOLATILITY_SQUEEZE", "Breakout"],
            outcome="success",
            symbol="BTCUSDT",
            memory_type="strategy_insight",
        ),
    )
    await db_session.commit()

    unique_tags = await crud.get_unique_agent_tags(db=db_session, user_id=pro_user.id)
    assert unique_tags == ["breakout", "volatility_squeeze"]

    # 2. Call search_agent_memory over MCP -> verify tag pool is present
    search_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 301,
            "method": "tools/call",
            "params": {
                "name": "search_agent_memory",
                "arguments": {"symbol": "BTCUSDT"},
            },
        },
    )
    assert search_resp.status_code == 200
    search_text = search_resp.json()["result"]["content"][0]["text"]
    assert "Available Database Tags (2 in user memory bank)" in search_text
    assert "`breakout`" in search_text
    assert "`volatility_squeeze`" in search_text

    # 3. Call store_agent_memory over MCP with uppercase/messy tags & lowercase symbol
    store_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 302,
            "method": "tools/call",
            "params": {
                "name": "store_agent_memory",
                "arguments": {
                    "content": "For mean reversion on 15m ETH, require RSI oversold < 25.",
                    "strategy_type": "MEAN_REVERSION",
                    "tags": ["  RSI_OVERSOLD  ", "Breakout", "RSI_OVERSOLD"],
                    "symbol": "ethusdt",
                    "outcome": "SUCCESS",
                },
            },
        },
    )
    assert store_resp.status_code == 200
    store_text = store_resp.json()["result"]["content"][0]["text"]
    assert "**Category**: `mean_reversion`" in store_text
    assert "**Symbol**: `ETHUSDT`" in store_text
    assert "**Tags**: `rsi_oversold`, `breakout`" in store_text
    assert "**Active Tag Pool (3 tags):**" in store_text

    # 4. Verify system prompt incorporates active tag pool and autopilot protocol
    prompt_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 303,
            "method": "prompts/get",
            "params": {
                "name": "depthsight_quant_developer",
                "arguments": {
                    "trading_style": "momentum",
                    "target_symbol": "ETHUSDT",
                },
            },
        },
    )
    assert prompt_resp.status_code == 200
    prompt_msg = prompt_resp.json()["result"]["messages"][0]["content"]["text"]
    assert "Active Database Tags (3 in memory pool)" in prompt_msg
    assert "'breakout'" in prompt_msg
    assert "'rsi_oversold'" in prompt_msg
    assert "'volatility_squeeze'" in prompt_msg
    assert "No Isolated Guessing - Rich Block Synergies" in prompt_msg
    assert "Mandatory Reasoning" in prompt_msg
    assert "Evolutionary Optimization & Backtracking" in prompt_msg
    assert "Stagnation Prevention (Patience Limit = 3) & Paradigm Pivot" in prompt_msg

    # 5. Verify run_backtest automatically persists insight into AgentMemory and records reasoning
    mock_task = mocker.MagicMock()
    mock_task.id = "mock-bt-celery-123"
    mock_task.ready.return_value = True
    mock_task.result = {
        "BTCUSDT": {
            "total_pnl_pct": 7.5,
            "win_rate": 64.0,
            "trades": 25,
            "max_drawdown": 3.5,
            "sharpe_ratio": 1.8,
            "profit_factor": 2.1,
        }
    }
    mocker.patch("api.celery_app.celery_app.send_task", return_value=mock_task)

    sample_bt_strategy = {
        "name": "Auto_Memory_Test_Strategy",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "filters": {
            "type": "AND",
            "children": [
                {"type": "volatility_filter", "params": {"natr_threshold": 1.0}}
            ],
        },
        "entryConditions": {"type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "params": {}},
        "initialization": {"type": "open_position", "params": {"side": "LONG"}},
        "positionManagement": [],
    }

    bt_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 304,
            "method": "tools/call",
            "params": {
                "name": "run_backtest",
                "arguments": {
                    "symbol": "BTCUSDT",
                    "strategy_config": sample_bt_strategy,
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-10",
                    "strategy_type": "breakout",
                    "tags": ["volatility_expansion", "atr_breakout", "BTCUSDT"],
                    "reasoning": "Testing volatility filter with ATR > 1.0 to catch expansion breakouts.",
                },
            },
        },
    )
    assert bt_resp.status_code == 200
    bt_text = bt_resp.json()["result"]["content"][0]["text"]
    assert "Memory Bank Auto-Recorded" in bt_text
    assert "Run saved as `SUCCESS` for `BTCUSDT` (`breakout`)" in bt_text
    assert "Assigned tags: `volatility_expansion`, `atr_breakout`" in bt_text
    assert "Quant Autopilot Guidance (Best Baseline Candidate)" in bt_text

    # Verify directly in DB that AgentMemory has been auto-created with the reasoning, tags, and strategy_type
    auto_memories = await crud.search_agent_memories(
        db=db_session, user_id=pro_user.id, symbol="BTCUSDT"
    )
    assert any(
        "Testing volatility filter with ATR > 1.0" in (m.content or "")
        and m.outcome == "success"
        and m.strategy_type == "breakout"
        and "volatility_expansion" in (m.tags or [])
        and "atr_breakout" in (m.tags or [])
        and "BTCUSDT" not in (m.tags or [])
        for m in auto_memories
    )

    # 6. Verify negative backtest with zero-token programmatic fallback tags and patience limit = 3
    mock_task_neg = mocker.MagicMock()
    mock_task_neg.id = "mock-bt-celery-neg"
    mock_task_neg.ready.return_value = True
    mock_task_neg.result = {
        "BTCUSDT": {
            "total_pnl_pct": -4.2,
            "win_rate": 30.0,
            "trades": 10,
            "max_drawdown": 8.1,
            "sharpe_ratio": -0.5,
            "profit_factor": 0.6,
        }
    }
    mocker.patch("api.celery_app.celery_app.send_task", return_value=mock_task_neg)

    neg_bt_resp = await authenticated_client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 305,
            "method": "tools/call",
            "params": {
                "name": "run_backtest",
                "arguments": {
                    "symbol": "BTCUSDT",
                    "strategy_config": sample_bt_strategy,
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-10",
                    "reasoning": "Testing tight stop with fast reversion.",
                },
            },
        },
    )
    assert neg_bt_resp.status_code == 200
    neg_bt_text = neg_bt_resp.json()["result"]["content"][0]["text"]
    assert "Memory Bank Auto-Recorded" in neg_bt_text
    assert "Run saved as `FAILURE` for `BTCUSDT`" in neg_bt_text
    assert "Assigned tags: " in neg_bt_text
    assert (
        "Quant Autopilot Guidance (Patience Limit = 3 & Paradigm Pivot)" in neg_bt_text
    )
    assert "Patience Limit = 3" in neg_bt_text
    assert "DISCARD this strategy architecture entirely" in neg_bt_text

    # Verify fallback tags in DB
    neg_memories = await crud.search_agent_memories(
        db=db_session, user_id=pro_user.id, symbol="BTCUSDT"
    )
    assert any(
        "Testing tight stop with fast reversion." in (m.content or "")
        and m.outcome == "failure"
        and m.strategy_type == "breakout"
        and "volatility_filter" in (m.tags or [])
        for m in neg_memories
    )
