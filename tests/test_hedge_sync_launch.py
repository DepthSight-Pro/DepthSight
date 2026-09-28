# tests/test_hedge_sync_launch.py
"""SYNC_STEP hedge launch: shared lot step, notional validation, fan-out."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, models, schemas


async def _second_key(db_session, user_id, exchange="bitget"):
    key = models.ApiKey(
        user_id=user_id,
        name=f"{exchange} Key",
        exchange=exchange,
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="xx...0000",
        status="valid",
        is_active=True,
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


async def _futures_config(db_session, user_id):
    created = await crud.create_strategy_config(
        db_session,
        user_id=user_id,
        config_create=schemas.StrategyConfigCreate(
            name="Sync Hedge Strat",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "marketType": "FUTURES",
                "params": {},
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(created)
    return created


def _mock_specs(monkeypatch, price=1.5):
    async def _fake_fetch(exchange, symbols):
        step = 10.0 if exchange == "bitget" else 1.0
        min_qty = 10.0 if exchange == "bitget" else 1.0
        return {s: {"step": step, "min_qty": min_qty, "price": price} for s in symbols}

    monkeypatch.setattr("api.routes.strategies._fetch_hedge_lot_specs", _fake_fetch)


def _start_payloads(mock_redis_client):
    return [
        json.loads(message_json)
        for _channel, message_json in mock_redis_client.publish_calls
        if json.loads(message_json).get("command") == "START_STRATEGY"
    ]


@pytest.mark.asyncio
async def test_sync_launch_fans_out_with_shared_step(
    pro_user_client: AsyncClient,
    mock_redis_client,
    db_session: AsyncSession,
    pro_user: models.User,
    monkeypatch,
):
    config = await _futures_config(db_session, pro_user.id)
    keys = await crud.get_active_api_keys_for_user(db_session, user_id=pro_user.id)
    leg_a = keys[0]
    leg_b = await _second_key(db_session, pro_user.id, exchange="bitget")
    _mock_specs(monkeypatch)

    response = await pro_user_client.post(
        "/api/v1/strategies",
        json={
            "config_id": config.id,
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": ["XRPUSDT"],
            "api_key_id": leg_a.id,
            "hedge": {
                "enabled": True,
                "leg_b_api_key_id": leg_b.id,
                "side_mode": "OPPOSITE",
                "exit_policy": "INDEPENDENT",
                "size_mode": "SYNC_STEP",
                "notional_usd": 20.0,
                "entry_sync_timeout_sec": 120.0,
            },
        },
    )
    assert response.status_code == 202, response.text

    messages = _start_payloads(mock_redis_client)
    assert len(messages) == 2
    by_leg = {}
    for message in messages:
        payload = message["payload"]
        leg = payload["config_data"]["hedge"]["leg"]
        by_leg[leg] = payload
    assert set(by_leg) == {"A", "B"}
    assert by_leg["A"]["api_key_id"] == leg_a.id
    assert by_leg["B"]["api_key_id"] == leg_b.id
    assert by_leg["A"]["config_data"]["hedge"]["qty_steps"] == {"XRPUSDT": 10.0}
    assert by_leg["B"]["config_data"]["hedge"]["qty_steps"] == {"XRPUSDT": 10.0}
    assert by_leg["B"]["config_data"]["hedge"]["invert"] is True
    assert by_leg["A"]["config_data"]["hedge"]["entry_sync_timeout_sec"] == 120.0
    assert response.json()["data"]["hedge_group_id"]


@pytest.mark.asyncio
async def test_sync_launch_rejects_small_notional(
    pro_user_client: AsyncClient,
    mock_redis_client,
    db_session: AsyncSession,
    pro_user: models.User,
    monkeypatch,
):
    config = await _futures_config(db_session, pro_user.id)
    keys = await crud.get_active_api_keys_for_user(db_session, user_id=pro_user.id)
    leg_b = await _second_key(db_session, pro_user.id, exchange="bitget")
    _mock_specs(monkeypatch)

    response = await pro_user_client.post(
        "/api/v1/strategies",
        json={
            "config_id": config.id,
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": ["XRPUSDT"],
            "api_key_id": keys[0].id,
            "hedge": {
                "enabled": True,
                "leg_b_api_key_id": leg_b.id,
                "size_mode": "SYNC_STEP",
                "notional_usd": 5.0,
            },
        },
    )
    assert response.status_code == 400, response.text
    assert "too small" in response.text
    assert _start_payloads(mock_redis_client) == []


@pytest.mark.asyncio
async def test_sync_launch_rejects_dynamic_symbols(
    pro_user_client: AsyncClient,
    mock_redis_client,
    db_session: AsyncSession,
    pro_user: models.User,
    monkeypatch,
):
    config = await _futures_config(db_session, pro_user.id)
    keys = await crud.get_active_api_keys_for_user(db_session, user_id=pro_user.id)
    leg_b = await _second_key(db_session, pro_user.id, exchange="bitget")
    _mock_specs(monkeypatch)

    response = await pro_user_client.post(
        "/api/v1/strategies",
        json={
            "config_id": config.id,
            "mode": "live",
            "symbol_selection_mode": "DYNAMIC",
            "symbols": [],
            "api_key_id": keys[0].id,
            "hedge": {
                "enabled": True,
                "leg_b_api_key_id": leg_b.id,
                "size_mode": "SYNC_STEP",
                "notional_usd": 20.0,
            },
        },
    )
    assert response.status_code == 400, response.text
    assert _start_payloads(mock_redis_client) == []
