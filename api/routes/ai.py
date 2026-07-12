import json
import logging
from typing import Callable, List, Optional

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai_assistant, crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..dependencies import require_permission, get_redis_client_for_quota


logger = logging.getLogger(__name__)


def create_ai_routers(
    enforce_strategy_plan_restrictions: Callable[[dict, models.User], None],
    user_has_pro_tier_access: Callable[[models.User], bool],
    is_strategy_kline_only: Callable[[dict], bool],
) -> tuple[APIRouter, APIRouter]:
    ai_meta_router = APIRouter(
        prefix="/api/v1/ai",
        tags=["AI Assistant (Meta)"],
        dependencies=[Depends(get_current_user)],
    )

    ai_core_router = APIRouter(
        prefix="/api/v1/ai",
        tags=["AI Assistant (Core)"],
        dependencies=[
            Depends(get_current_user),
            Depends(require_permission("use_ai_assistant")),
        ],
    )

    @ai_meta_router.get(
        "/chat/latest-session", response_model=schemas.ApiResponseData[Optional[str]]
    )
    async def get_latest_chat_session(
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        session_id = await crud.get_latest_chat_session_id(db, user_id=current_user.id)
        return {"data": session_id}

    @ai_meta_router.post("/chat/history/init", status_code=status.HTTP_201_CREATED)
    async def init_chat_session(
        request: schemas.AIChatInitSessionRequest,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        logger.info(
            "Initializing chat session %s for user %s",
            request.session_id,
            current_user.id,
        )

        message_data = schemas.AIChatMessageCreate(
            session_id=request.session_id,
            role="assistant",
            content=request.initial_message,
        )
        await crud.create_chat_message(
            db, user_id=current_user.id, message_data=message_data
        )
        await db.commit()

        logger.info("Chat session %s initialized successfully", request.session_id)
        return {"message": "Session initialized"}

    @ai_meta_router.get(
        "/chat/history/{session_id}",
        response_model=schemas.ApiResponseData[List[schemas.AIChatMessage]],
    )
    async def get_chat_history(
        session_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        history = await crud.get_chat_history(
            db, user_id=current_user.id, session_id=session_id, limit=50
        )
        return {"data": history}

    @ai_meta_router.get(
        "/memories",
        response_model=schemas.ApiResponseData[List[schemas.AgentMemory]],
    )
    async def get_agent_memories(
        tag: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy_type: Optional[str] = None,
        memory_type: Optional[str] = None,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        if tag or symbol or strategy_type or memory_type:
            memories = await crud.search_agent_memories(
                db,
                user_id=current_user.id,
                tags=[tag] if tag else None,
                symbol=symbol,
                strategy_type=strategy_type,
                memory_type=memory_type,
            )
        else:
            memories = await crud.get_agent_memories(db, user_id=current_user.id)
        return {"data": memories}

    @ai_meta_router.delete("/memories", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_agent_memories(
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        await crud.delete_agent_memories(db, user_id=current_user.id)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @ai_meta_router.delete(
        "/chat/history/{session_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    async def delete_chat_history(
        session_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        deleted_count = await crud.delete_chat_session(
            db, user_id=current_user.id, session_id=session_id
        )
        logger.info(
            "User %s deleted %s messages from session %s",
            current_user.id,
            deleted_count,
            session_id,
        )
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @ai_core_router.post(
        "/generate-strategy",
        response_model=schemas.ApiResponseData[schemas.StrategyV2ConfigData],
    )
    async def generate_strategy_from_text_ai_core_endpoint(
        request: schemas.GenerateStrategyRequest,
        current_user: models.User = Depends(get_current_user),
    ):
        logger.info(
            "User '%s' generating strategy from text prompt.", current_user.username
        )
        try:
            generated_json = await ai_assistant.generate_strategy_json_from_prompt(
                request, current_user
            )
            enforce_strategy_plan_restrictions(generated_json, current_user)
            if is_strategy_kline_only(generated_json) and not user_has_pro_tier_access(
                current_user
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Generated strategy requires Precision-compatible blocks that are unavailable on your current plan.",
                )
            return {"data": generated_json}
        except ConnectionError as e:
            logger.error(
                "AI Assistant connection error for user '%s': %s",
                current_user.username,
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
            )
        except ValueError as e:
            logger.warning(
                "AI Assistant validation/parsing error for user '%s': %s",
                current_user.username,
                e,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except Exception as e:
            logger.error(
                "Unexpected error in AI Assistant endpoint for user '%s': %s",
                current_user.username,
                e,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while generating the strategy.",
            )

    @ai_core_router.post("/chat", response_model=schemas.AIChatResponse)
    async def chat_with_ai_copilot(
        request: schemas.AIChatRequest,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        redis_client: redis.Redis = Depends(get_redis_client_for_quota),
    ):
        user_message_data = schemas.AIChatMessageCreate(
            session_id=request.session_id,
            role="user",
            content=request.text_prompt,
            image_base64=request.image_base64,
            image_mime_type=request.image_mime_type,
        )
        await crud.create_chat_message(
            db, user_id=current_user.id, message_data=user_message_data
        )

        if request.history:
            request.history = request.history[-20:]

        try:
            ai_response = await ai_assistant.get_chat_response(
                request=request, user=current_user, db=db, redis_client=redis_client
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Error getting AI response for user %s: %s",
                current_user.id,
                e,
                exc_info=True,
            )
            error_message_data = schemas.AIChatMessageCreate(
                session_id=request.session_id,
                role="assistant",
                content=f"Sorry, an error occurred: {e}",
            )
            await crud.create_chat_message(
                db, user_id=current_user.id, message_data=error_message_data
            )
            await db.commit()
            raise HTTPException(status_code=500, detail="Error processing AI request.")

        assistant_content = ai_response.text_response
        if request.mode == "generator" and ai_response.strategy_json:
            assistant_content = json.dumps(ai_response.strategy_json, indent=2)

        assistant_message_data = schemas.AIChatMessageCreate(
            session_id=request.session_id,
            role="assistant",
            content=assistant_content,
        )
        await crud.create_chat_message(
            db, user_id=current_user.id, message_data=assistant_message_data
        )

        await db.commit()
        return ai_response

    return ai_meta_router, ai_core_router
