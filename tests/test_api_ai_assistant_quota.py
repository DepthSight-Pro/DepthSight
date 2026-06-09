# tests/test_api_ai_assistant_quota.py

import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock
from datetime import datetime, timezone
import uuid

from api import models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from api.quota_manager import QuotaManager
from fastapi import HTTPException, status


@pytest.mark.asyncio
class TestAIAssistantQuota:
    """
    Tests to verify the correctness of quota application to AI Assistant endpoints
    after router refactoring.
    """

    @pytest.fixture
    def mock_plans_config(self, mocker):
        mock_get_plan = mocker.patch("api.plans.plans_config.get_plan")

        free_plan_config_with_quota = {
            "name": "Free",
            "quotas": {"use_ai_assistant_per_day": 5},
            "permissions": ["use_ai_assistant"],
            "limits": {},
        }

        mock_get_plan.side_effect = lambda plan_name: (
            free_plan_config_with_quota if plan_name == "free" else {}
        )

        return mock_get_plan

    async def test_quota_exhausted_scenario(
        self,
        free_user_client: AsyncClient,
        free_user: models.User,
        mock_redis_client: MagicMock,
        mock_plans_config: MagicMock,
        mocker,
        db_session: AsyncSession,
    ):
        """
        Scenario 1: Quota exhausted.
        """
        # Activate the user in the DB for this test
        free_user.is_active = True
        db_session.add(free_user)
        await db_session.commit()

        async def mock_get_chat_response(*args, **kwargs):
            qm = QuotaManager(free_user, mock_redis_client, db_session)
            if not await qm.check_and_consume("use_ai_assistant"):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="You have exceeded the usage limit for the AI Assistant on your current plan.",
                )
            return schemas.AIChatResponse(
                text_response="Mock AI response", session_id=session_id
            )

        mocker.patch(
            "api.ai_assistant.get_chat_response", side_effect=mock_get_chat_response
        )

        client = free_user_client
        session_id = str(uuid.uuid4())

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_key = f"usage:{free_user.id}:use_ai_assistant_per_day:{date_str}"

        await mock_redis_client.set(quota_key, "5")
        mock_redis_client.get.return_value = "5"

        response_history = await client.get(f"/api/v1/ai/chat/history/{session_id}")
        assert response_history.status_code == 200, (
            f"GET /chat/history/{session_id} should be accessible even when the quota is exhausted. Received {response_history.status_code}: {response_history.text}"
        )

        chat_payload = {
            "session_id": session_id,
            "text_prompt": "Hello, AI",
            "mode": "advisor",
        }
        response_chat = await client.post("/api/v1/ai/chat", json=chat_payload)
        assert response_chat.status_code == 429, (
            "POST /chat should return 429 when the quota is exhausted"
        )
        assert "exceeded the usage limit" in response_chat.json()["error"]

    async def test_quota_available_scenario(
        self,
        free_user_client: AsyncClient,
        free_user: models.User,
        mock_redis_client: MagicMock,
        mock_plans_config: MagicMock,
        mocker,
        db_session: AsyncSession,
    ):
        """
        Scenario 2: Quota available.
        """
        # Activate the user in the DB for this test
        free_user.is_active = True
        db_session.add(free_user)
        await db_session.commit()

        client = free_user_client
        session_id = str(uuid.uuid4())

        async def mock_get_chat_response(*args, **kwargs):
            qm = QuotaManager(free_user, mock_redis_client, db_session)
            if not await qm.check_and_consume("use_ai_assistant"):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="You have exceeded the usage limit for the AI Assistant on your current plan.",
                )
            return schemas.AIChatResponse(
                text_response="Hello from mock AI", session_id=session_id
            )

        mock_get_chat_response_patch = mocker.patch(
            "api.ai_assistant.get_chat_response", side_effect=mock_get_chat_response
        )

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_key = f"usage:{free_user.id}:use_ai_assistant_per_day:{date_str}"

        await mock_redis_client.set(quota_key, "1")
        mock_redis_client.get.return_value = "1"
        mock_redis_client.incr.return_value = 2

        response_history = await client.get(f"/api/v1/ai/chat/history/{session_id}")
        assert response_history.status_code == 200, (
            f"GET /chat/history/{session_id} should be accessible. Received {response_history.status_code}: {response_history.text}"
        )

        mock_redis_client.incr.assert_not_called()

        chat_payload = {
            "session_id": session_id,
            "text_prompt": "Hello, AI",
            "mode": "advisor",
        }
        response_chat = await client.post("/api/v1/ai/chat", json=chat_payload)
        assert response_chat.status_code == 200, (
            f"POST /chat should work when the quota is available. Response: {response_chat.text}"
        )

        mock_get_chat_response_patch.assert_called_once()
        mock_redis_client.incr.assert_called_once_with(quota_key)
