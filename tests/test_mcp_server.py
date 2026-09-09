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
    assert "Visual Builder Strategy Schema" in content
    assert "trend_filter" in content
    assert "open_position" in content
    assert "EMA_Trend_RSI_Reversal" in content
    assert "Agent Memory & Quant Protocol Guide" in content

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
