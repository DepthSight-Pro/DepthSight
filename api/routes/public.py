import logging

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
        run_params.get("name")
        or run_params.get("strategy_display_name")
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
        "strategyConfig": run.parameters_json.get("config")
        if shared_backtest.are_parameters_public and run.parameters_json
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
    ref_code: str, request: Request, redis: redis.Redis = Depends(get_redis_client)
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
        redis_client=redis, referral_code=effective_ref
    )

    return RedirectResponse(f"/register?ref={effective_ref}", status_code=302)


@public_router.get("/og-image/{public_slug}.png")
async def get_og_image(public_slug: str, db: AsyncSession = Depends(get_db)):
    data_response = await get_shared_backtest_data(public_slug, db)
    shared_data = data_response["data"]

    try:
        image_bytes = await generate_og_image(
            schemas.SharedBacktestData.model_validate(shared_data)
        )
        return Response(content=image_bytes, media_type="image/png")
    except Exception as e:
        logger.error(
            "Failed to generate OG image for slug %s: %s", public_slug, e, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Could not generate report image.")


@public_router.get("/render-shared/{public_slug}", response_class=HTMLResponse)
async def render_shared_backtest(
    public_slug: str, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        data_response = await get_shared_backtest_data(public_slug, db)
        data = data_response["data"]

        strategy_name = data.get("strategyName", "Trading Strategy")
        symbol = data.get("symbol", "Asset")
        kpis = data.get("kpis", {})
        pnl = kpis.get("total_pnl", 0)
        pnl_str = f"{'+' if pnl >= 0 else ''}{pnl:.2f} USD"
        win_rate = kpis.get("win_rate", 0)

        title = f"DepthSight Report: {strategy_name} on {symbol}"
        description = f"Performance: {pnl_str} PNL | Win Rate: {win_rate:.1f}%. View detailed backtest analytics on DepthSight AI Platform."

        host = request.headers.get("host", "app.depthsight.pro")
        scheme = request.headers.get("x-forwarded-proto", "https")
        abs_base_url = f"{scheme}://{host}"

        image_url = f"{abs_base_url}/og-image/{public_slug}.png"
        page_url = f"{abs_base_url}/s/{public_slug}"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <meta name="description" content="{description}" />
    
    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="{page_url}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="{image_url}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">

    <!-- Twitter -->
    <meta property="twitter:card" content="summary_large_image">
    <meta property="twitter:url" content="{page_url}">
    <meta property="twitter:title" content="{title}">
    <meta property="twitter:description" content="{description}">
    <meta property="twitter:image" content="{image_url}">

    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Redirect for regular users if they get here directly -->
    <script>
        window.location.href = "/s/{public_slug}";
    </script>
</head>
<body style="background-color: #0d1117; color: white; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
    <div style="text-align: center; padding: 20px;">
        <h1 style="color: #58a6ff;">{strategy_name}</h1>
        <p style="font-size: 1.2em;">{symbol} | {pnl_str}</p>
        <p style="color: #8b949e;">Loading report...</p>
        <img src="{image_url}" alt="Equity Curve" style="max-width: 100%; border-radius: 8px; margin-top: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error("Error rendering shared page for bot: %s", e, exc_info=True)
        raise HTTPException(status_code=404, detail="Report not found")
