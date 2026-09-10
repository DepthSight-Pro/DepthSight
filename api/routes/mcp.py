"""
FastAPI Routes for Model Context Protocol (MCP 2025-03-26).
Supports Streamable HTTP JSON-RPC 2.0 and SSE transports.
"""

import logging
from typing import List, Optional

import redis.asyncio as redis
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, models, schemas
from api.auth import get_current_user_from_token
from api.database import get_db
from api.mcp.dispatcher import MCPDispatcher
from api.mcp.tools import TOOL_DEFINITIONS
from api.mcp.sse import sse_session_manager
from api.rate_limiter import limiter
from api.redis_client import get_redis_client

logger = logging.getLogger("depthsight.routes.mcp")

mcp_router = APIRouter(prefix="/mcp", tags=["MCP"])
dispatcher = MCPDispatcher()


# ---------------------------------------------------------------------------
# Authentication Dependency for MCP
# ---------------------------------------------------------------------------


async def get_mcp_user(
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    """
    Authenticates an MCP client using either:
    1. HTTP Bearer token in the 'Authorization' header.
    2. '?token=<token>' query parameter (standard for EventSource SSE connections).
    """
    resolved_token = None

    if auth_header and auth_header.startswith("Bearer "):
        resolved_token = auth_header.replace("Bearer ", "").strip()
    elif token:
        resolved_token = token.strip()

    if not resolved_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide 'Authorization: Bearer <token>' header or '?token=...' query parameter.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_current_user_from_token(resolved_token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


# ---------------------------------------------------------------------------
# Streamable HTTP Transport: POST /api/v1/mcp
# ---------------------------------------------------------------------------


@mcp_router.post(
    "",
    summary="Model Context Protocol (MCP) Streamable HTTP Endpoint",
    description="Accepts JSON-RPC 2.0 requests (single or batch) following the MCP specification.",
)
@mcp_router.post(
    "/sse",
    summary="Fallback Streamable HTTP on /sse",
    include_in_schema=False,
)
@limiter.limit("120/minute")
async def mcp_streamable_http(
    request: Request,
    user: models.User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
            },
        )

    response = await dispatcher.dispatch(
        request_data=body,
        user=user,
        db=db,
        redis_client=redis_client,
    )

    if response is None:
        # Notifications return 204 No Content
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return JSONResponse(content=response)


# ---------------------------------------------------------------------------
# SSE Transport: GET /api/v1/mcp/sse & POST /api/v1/mcp/messages
# ---------------------------------------------------------------------------


@mcp_router.get(
    "/sse",
    summary="Model Context Protocol (MCP) SSE Connection Endpoint",
    description="Opens an SSE stream for Claude Desktop and Cursor IDE MCP clients.",
)
@mcp_router.get(
    "",
    summary="Model Context Protocol (MCP) SSE Connection Endpoint (Root Fallback)",
    description="Allows clients connecting via SSE to use root /mcp URL.",
    include_in_schema=False,
)
async def mcp_sse_connect(
    request: Request,
    user: models.User = Depends(get_mcp_user),
):
    session = await sse_session_manager.create_session(user_id=user.id)

    # Determine message posting endpoint relative to host
    base_path = request.scope.get("root_path", "") + "/api/v1/mcp/messages"

    return StreamingResponse(
        sse_session_manager.stream_session(session, base_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@mcp_router.post(
    "/messages",
    summary="Model Context Protocol (MCP) SSE Message Handler",
    description="Receives JSON-RPC 2.0 messages from SSE-connected clients and queues responses on their stream.",
)
async def mcp_sse_message(
    request: Request,
    session_id: str = Query(..., description="Active SSE session ID"),
    user: models.User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    session = sse_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSE session '{session_id}' not found or expired.",
        )

    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: session belongs to another user.",
        )

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {str(e)}",
        )

    response = await dispatcher.dispatch(
        request_data=body,
        user=user,
        db=db,
        redis_client=redis_client,
    )

    if response is not None:
        await session.push_event("message", response)

    return Response(status_code=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------------
# Convenience REST Discovery Endpoint
# ---------------------------------------------------------------------------


@mcp_router.get(
    "/tools",
    summary="List available MCP tools",
    description="Returns the full list and schemas of DepthSight tools exposed via MCP.",
)
async def list_mcp_tools(user: models.User = Depends(get_mcp_user)):
    return {
        "status": "success",
        "protocol_version": "2026-07-28",
        "tools": [t.model_dump() for t in TOOL_DEFINITIONS],
    }


# ---------------------------------------------------------------------------
# Personal Access Tokens (PAT) Management Endpoints
# ---------------------------------------------------------------------------

@mcp_router.get(
    "/tokens",
    response_model=schemas.ApiResponseData[List[schemas.PersonalAccessTokenInfo]],
    summary="List user's Personal Access Tokens",
    description="Returns all active and revoked PAT tokens created by the user.",
)
async def list_user_pats(
    user: models.User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
):
    tokens = await crud.get_personal_access_tokens_by_user(db, user_id=user.id)
    validated = [schemas.PersonalAccessTokenInfo.model_validate(t) for t in tokens]
    return {"data": validated}


@mcp_router.post(
    "/tokens",
    response_model=schemas.ApiResponseData[schemas.PersonalAccessTokenCreated],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Personal Access Token",
    description="Generates a secure long-lived PAT. The raw token is returned only once!",
)
async def create_user_pat(
    token_create: schemas.PersonalAccessTokenCreate,
    user: models.User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
):
    if not token_create.name or not token_create.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token name is required.",
        )

    raw_token, db_pat = await crud.create_personal_access_token(
        db=db, user_id=user.id, token_create=token_create
    )
    await db.commit()
    await db.refresh(db_pat)

    response_data = schemas.PersonalAccessTokenCreated(
        id=db_pat.id,
        name=db_pat.name,
        token_prefix=db_pat.token_prefix,
        is_active=db_pat.is_active,
        created_at=db_pat.created_at,
        expires_at=db_pat.expires_at,
        last_used_at=db_pat.last_used_at,
        token=raw_token,
    )
    return {"data": response_data}


@mcp_router.delete(
    "/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a Personal Access Token",
    description="Permanently deletes or revokes a PAT token.",
)
async def delete_user_pat(
    token_id: int,
    user: models.User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
):
    success = await crud.delete_personal_access_token(db, user_id=user.id, token_id=token_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or already deleted.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
