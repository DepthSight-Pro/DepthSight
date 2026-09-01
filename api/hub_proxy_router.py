# api/hub_proxy_router.py
import logging
import httpx
from fastapi import APIRouter, Request, Response, HTTPException, status
from bot_module.federation import get_federation_hub_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hub", tags=["Federation Hub Proxy"])

_HOP_BY_HOP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_EXCLUDED_RESPONSE_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
}


@router.api_route(
    "",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_hub_request(request: Request, path: str = ""):
    """
    Transparently forwards client requests from a local node to the Central Federation Hub.
    Eliminates browser CORS and Mixed Content issues for local node users.
    """
    try:
        hub_base_url = get_federation_hub_url().rstrip("/")
    except Exception as e:
        logger.error(f"[HubProxy] Could not resolve central hub URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Federation hub URL error: {e}",
        )

    clean_path = path.lstrip("/")
    target_url = f"{hub_base_url}/{clean_path}" if clean_path else hub_base_url
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Forward headers excluding hop-by-hop
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS
    }

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
            )

            # Filter response headers (exclude transfer/encoding headers since content is already decoded)
            resp_headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in _HOP_BY_HOP_HEADERS
                and k.lower() not in _EXCLUDED_RESPONSE_HEADERS
            }

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )
    except httpx.RequestError as exc:
        logger.warning(f"[HubProxy] Network error forwarding to {target_url}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Central Federation Hub is currently unreachable.",
        )
    except Exception as exc:
        logger.error(f"[HubProxy] Unexpected error proxying to {target_url}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to proxy request to Central Federation Hub.",
        )
