import html
import logging
import os

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas
from ..database import get_db
from ..og_image_generator import generate_og_image
from ..redis_client import get_redis_client


logger = logging.getLogger(__name__)

public_router = APIRouter(tags=["Public"])

SOCIAL_BOT_USER_AGENTS = (
    "bot",
    "crawler",
    "spider",
    "scraper",
    "preview",
    "opengraph",
    "metatags",
    "facebookexternalhit",
    "whatsapp",
    "skypeuripreview",
    "vkshare",
)


def _is_social_bot(user_agent: str | None) -> bool:
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(bot in ua for bot in SOCIAL_BOT_USER_AGENTS)


def _get_base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "https").split(",")[0].strip()
    if host and not ("localhost" in host or "127.0.0.1" in host or "api:8000" in host):
        return f"{proto}://{host}"

    public_base = os.getenv("PUBLIC_BASE_URL") or os.getenv("FRONTEND_BASE_URL")
    if public_base and not ("localhost" in public_base or "127.0.0.1" in public_base):
        return public_base.rstrip("/")

    if host:
        return f"{proto}://{host}"
    return "https://app.depthsight.pro"


@public_router.get(
    "/api/v1/shared/{public_slug}",
    response_model=schemas.ApiResponseData[schemas.SharedBacktestData],
)
async def get_shared_backtest_data(
    public_slug: str, db: AsyncSession = Depends(get_db)
):
    shared_backtest = await crud.get_shared_backtest_by_slug(
        db, public_slug=public_slug
    )
    if not shared_backtest or not shared_backtest.backtest_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or access is closed.",
        )

    run = shared_backtest.backtest_run
    run_params = run.parameters_json or {}
    strategy_config = run_params.get("config") if isinstance(run_params, dict) else None
    if not isinstance(strategy_config, dict):
        strategy_config = None
    strategy_display_name = (
        (run_params.get("name") if isinstance(run_params, dict) else None)
        or (
            run_params.get("strategy_display_name")
            if isinstance(run_params, dict)
            else None
        )
        or (strategy_config or {}).get("name")
        or run.strategy_name
    )

    response_data = {
        "strategyName": run.strategy_name
        if shared_backtest.is_strategy_name_public
        else "Private Strategy",
        "symbol": run.symbol,
        "period": {"start": run.start_date, "end": run.end_date},
        "kpis": run.kpi_results_json or {},
        "equityCurve": run.equity_curve_json or [],
        "parameters": run.parameters_json
        if shared_backtest.are_parameters_public
        else None,
        "strategyConfig": strategy_config
        if shared_backtest.are_parameters_public
        else None,
    }

    if shared_backtest.is_strategy_name_public:
        response_data["strategyName"] = strategy_display_name
    if shared_backtest.are_parameters_public:
        response_data["parameters"] = run_params
        response_data["strategyConfig"] = strategy_config

    return {"data": response_data}


@public_router.get("/r/{ref_code}")
async def affiliate_redirector(
    ref_code: str,
    request: Request,
    redis_client: redis.Redis = Depends(get_redis_client),
):
    effective_ref = ref_code
    if ref_code == "register":
        effective_ref = request.query_params.get("ref", "register")

    logger.info(
        "AFFILIATE REDIRECT: Received request for ref_code='%s', effective_ref='%s'",
        ref_code,
        effective_ref,
    )
    await crud.increment_referral_clicks(
        redis_client=redis_client, referral_code=effective_ref
    )

    return RedirectResponse(f"/register?ref={effective_ref}", status_code=302)


@public_router.get("/og-image/{public_slug}.png")
async def get_og_image(
    public_slug: str,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    cache_key = f"og_image:{public_slug}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return Response(
                content=cached,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Cache": "HIT",
                },
            )
    except Exception as cache_err:
        logger.warning(
            "Redis cache check failed for og_image:%s: %s",
            public_slug,
            cache_err,
        )

    data_response = await get_shared_backtest_data(public_slug, db)
    shared_data = data_response["data"]

    try:
        image_bytes = await generate_og_image(
            schemas.SharedBacktestData.model_validate(shared_data)
        )
        try:
            await redis_client.set(cache_key, image_bytes, ex=86400)
        except Exception as cache_save_err:
            logger.warning(
                "Redis cache save failed for og_image:%s: %s",
                public_slug,
                cache_save_err,
            )

        return Response(
            content=image_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Cache": "MISS",
            },
        )
    except Exception as e:
        logger.error(
            "Failed to generate OG image for slug %s: %s",
            public_slug,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not generate report image.")


async def _render_shared_html(
    public_slug: str, request: Request, db: AsyncSession
) -> HTMLResponse:
    try:
        data_response = await get_shared_backtest_data(public_slug, db)
        data = data_response["data"]

        strategy_name = data.get("strategyName") or "Trading Strategy"
        symbol = data.get("symbol") or "Asset"
        kpis = data.get("kpis") or {}

        try:
            pnl = float(kpis.get("total_pnl") or 0.0)
        except (ValueError, TypeError):
            pnl = 0.0

        try:
            win_rate = float(kpis.get("win_rate") or 0.0)
        except (ValueError, TypeError):
            win_rate = 0.0

        pnl_str = f"{'+' if pnl >= 0 else ''}{pnl:.2f} USD"

        title = f"DepthSight Report: {strategy_name} on {symbol}"
        description = (
            f"Performance: {pnl_str} PNL | Win Rate: {win_rate:.1f}%. "
            "View detailed backtest analytics on DepthSight AI Platform."
        )

        abs_base_url = _get_base_url(request)
        image_url = f"{abs_base_url}/og-image/{public_slug}.png"
        page_url = f"{abs_base_url}/s/{public_slug}"

        e_title = html.escape(title, quote=True)
        e_description = html.escape(description, quote=True)
        e_page_url = html.escape(page_url, quote=True)
        e_image_url = html.escape(image_url, quote=True)
        e_strategy_name = html.escape(strategy_name, quote=True)
        e_symbol = html.escape(symbol, quote=True)
        e_pnl_str = html.escape(pnl_str, quote=True)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{e_title}</title>
    <meta name="description" content="{e_description}" />

    <!-- Open Graph / Telegram / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="DepthSight">
    <meta property="og:url" content="{e_page_url}">
    <meta property="og:title" content="{e_title}">
    <meta property="og:description" content="{e_description}">
    <meta property="og:image" content="{e_image_url}">
    <meta property="og:image:secure_url" content="{e_image_url}">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:site" content="@depthsight">
    <meta name="twitter:url" content="{e_page_url}">
    <meta name="twitter:title" content="{e_title}">
    <meta name="twitter:description" content="{e_description}">
    <meta name="twitter:image" content="{e_image_url}">
</head>
<body style="background-color: #0d1117; color: white; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
    <div style="text-align: center; padding: 20px;">
        <h1 style="color: #58a6ff;">{e_strategy_name}</h1>
        <p style="font-size: 1.2em;">{e_symbol} | {e_pnl_str}</p>
        <p style="color: #8b949e;">Loading report...</p>
        <img src="{e_image_url}" alt="Equity Curve" style="max-width: 100%; border-radius: 8px; margin-top: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
    </div>
</body>
</html>"""
        return HTMLResponse(
            content=html_content,
            headers={"Cache-Control": "public, max-age=300"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error rendering shared page for slug %s: %s",
            public_slug,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=404, detail="Report not found")


@public_router.get("/render-shared/{public_slug:path}", response_class=HTMLResponse)
async def render_shared_backtest(
    public_slug: str, request: Request, db: AsyncSession = Depends(get_db)
):
    clean_slug = public_slug.strip("/")
    return await _render_shared_html(clean_slug, request, db)


@public_router.get("/s/{public_slug:path}", response_class=HTMLResponse)
async def get_shared_backtest_page_or_og(
    public_slug: str, request: Request, db: AsyncSession = Depends(get_db)
):
    clean_slug = public_slug.strip("/")
    user_agent = request.headers.get("user-agent", "")
    if _is_social_bot(user_agent):
        return await _render_shared_html(clean_slug, request, db)

    # For standard browser requests hitting the API route directly,
    # redirect to the frontend route /s/{public_slug}
    configured_frontend = os.getenv("FRONTEND_BASE_URL", "").strip()
    if configured_frontend and not (
        "localhost" in configured_frontend or "127.0.0.1" in configured_frontend
    ):
        frontend_url = configured_frontend.rstrip("/")
    else:
        frontend_url = _get_base_url(request)

    return RedirectResponse(
        url=f"{frontend_url.rstrip('/')}/s/{clean_slug}",
        status_code=302,
    )
