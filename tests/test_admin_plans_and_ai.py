import pytest


@pytest.mark.asyncio
async def test_admin_plans_config_get_and_put(
    pro_user, free_user, db_session, authenticated_client_factory
):
    # Make pro_user an admin
    pro_user.role = "admin"
    await db_session.commit()

    admin_client = await authenticated_client_factory(pro_user)
    user_client = await authenticated_client_factory(free_user)

    # Non-admin should be forbidden (403)
    res = await user_client.get("/api/v1/admin/plans/config")
    assert res.status_code == 403

    # Admin should succeed (200)
    res = await admin_client.get("/api/v1/admin/plans/config")
    assert res.status_code == 200
    data = res.json()
    assert "plans" in data
    assert "free" in data["plans"]
    assert "standard" in data["plans"]
    assert "pro" in data["plans"]

    # Update plans config
    updated_plans = dict(data["plans"])
    updated_plans["standard"]["price_usd"] = 45
    updated_plans["standard"]["quotas"]["use_ai_assistant_per_day"] = 35

    update_payload = {
        "plans": updated_plans,
        "billing": data.get("billing"),
        "registration_trial": data.get("registration_trial"),
        "block_restrictions": data.get("block_restrictions"),
        "referral_program": data.get("referral_program"),
        "affiliate_program": data.get("affiliate_program"),
    }

    put_res = await admin_client.put(
        "/api/v1/admin/plans/config",
        json=update_payload,
    )
    assert put_res.status_code == 200
    saved_data = put_res.json()
    assert saved_data["plans"]["standard"]["price_usd"] == 45
    assert saved_data["plans"]["standard"]["quotas"]["use_ai_assistant_per_day"] == 35

    # Verify subsequent GET returns the persisted DB settings
    get_res = await admin_client.get("/api/v1/admin/plans/config")
    assert get_res.status_code == 200
    reloaded = get_res.json()
    assert reloaded["plans"]["standard"]["price_usd"] == 45

    # Verify payment plans endpoint reflects the updated price
    pay_res = await user_client.get("/api/v1/payments/plans")
    assert pay_res.status_code == 200
    pay_plans = pay_res.json()
    std_plan = next((p for p in pay_plans if p["key"] == "standard"), None)
    assert std_plan is not None
    assert std_plan["price_usd"] == 45

    # Verify discovery hub /nodes reflects the updated plans on master hub
    from unittest.mock import MagicMock
    from api.hub_router import get_active_nodes

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {}
    hub_nodes = await get_active_nodes(mock_request, db_session)
    master_node = next((n for n in hub_nodes if n.is_master), None)
    assert master_node is not None
    assert master_node.public_plans["standard"]["price_usd"] == 45


@pytest.mark.asyncio
async def test_admin_ai_settings_get_and_put(
    pro_user, free_user, db_session, authenticated_client_factory
):
    pro_user.role = "admin"
    await db_session.commit()

    admin_client = await authenticated_client_factory(pro_user)
    user_client = await authenticated_client_factory(free_user)

    # Non-admin forbidden
    res = await user_client.get("/api/v1/admin/ai/settings")
    assert res.status_code == 403

    # Admin get AI settings
    res = await admin_client.get("/api/v1/admin/ai/settings")
    assert res.status_code == 200
    data = res.json()
    assert "active_provider" in data
    assert "supported_providers" in data
    assert "qwen" in data["providers"]
    assert "google" in data["providers"]
    assert "openrouter" in data["providers"]

    # Admin update AI settings
    update_payload = {
        "active_provider": "openrouter",
        "providers": {
            "openrouter": {
                "api_key": "sk-or-v1-new-secret-test-key-12345678",
                "model": "anthropic/claude-3.5-sonnet",
                "app_title": "Custom Title",
            },
            "qwen": {
                "model": "qwen-plus",
            },
        },
    }

    put_res = await admin_client.put(
        "/api/v1/admin/ai/settings",
        json=update_payload,
    )
    assert put_res.status_code == 200
    saved_ai = put_res.json()
    assert saved_ai["active_provider"] == "openrouter"
    assert saved_ai["providers"]["openrouter"]["model"] == "anthropic/claude-3.5-sonnet"
    assert saved_ai["providers"]["openrouter"]["is_configured"] is True
    assert saved_ai["providers"]["openrouter"]["api_key_masked"].startswith("sk-o")


@pytest.mark.asyncio
async def test_admin_ai_test_connection_endpoint(
    pro_user, db_session, authenticated_client_factory
):
    pro_user.role = "admin"
    await db_session.commit()

    admin_client = await authenticated_client_factory(pro_user)
    test_payload = {
        "provider": "invalid-provider",
    }
    res = await admin_client.post(
        "/api/v1/admin/ai/test",
        json=test_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "Unsupported provider" in data["error"]
