import os
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_svg_chart_path(
    equity_points: list, width: int = 400, height: int = 260
) -> str:
    """Generates an SVG path string for a given list of equity/price points."""
    if not equity_points or len(equity_points) < 2:
        return ""

    try:
        # Normalize points
        y_values = [float(p) for p in equity_points]
        min_y, max_y = min(y_values), max(y_values)
        y_range = max_y - min_y if max_y > min_y else 1

        points = [
            (
                (i / (len(y_values) - 1)) * width,
                height - ((y - min_y) / y_range * (height - 20)) - 10,
            )
            for i, y in enumerate(y_values)
        ]

        path_d = f"M {points[0][0]:.2f} {points[0][1]:.2f}"
        for i in range(1, len(points)):
            path_d += f" L {points[i][0]:.2f} {points[i][1]:.2f}"

        area_d = (
            path_d + f" L {points[-1][0]:.2f} {height} L {points[0][0]:.2f} {height} Z"
        )
        return area_d
    except Exception as e:
        logger.error(f"Error generating SVG path: {e}")
        return ""


async def render_card(
    template_name: str, placeholders: dict, width: int = 800, height: int = 420
) -> bytes:
    """Reads a template, replaces placeholders, and renders it to a PNG using Playwright."""
    template_path = os.path.join(TEMPLATE_DIR, "templates", template_name)
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Substitute placeholders
    for key, val in placeholders.items():
        html = html.replace(f"{{{{ {key} }}}}", str(val))

    logger.info(f"Rendering {template_name} via Playwright ({width}x{height})...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()
        await page.set_viewport_size({"width": width, "height": height})
        await page.set_content(html)
        await page.evaluate("document.fonts.ready")
        # Give Google Fonts and animations/SVG a tiny moment to settle
        await asyncio.sleep(0.3)
        screenshot_bytes = await page.screenshot(type="png")
        await browser.close()
        return screenshot_bytes


async def render_backtest_card(
    strategy_name: str,
    symbol: str,
    period_str: str,
    equity_points: list[float],
    kpis: dict,
) -> bytes:
    """Renders the backtesting report card."""
    chart_width, chart_height = 400, 260
    svg_path = generate_svg_chart_path(equity_points, chart_width, chart_height)

    if svg_path:
        chart_svg = f"""
        <svg width="100%" height="100%" viewBox="0 0 {chart_width} {chart_height}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stop-color="#3b82f6" stop-opacity="0.4"/>
                    <stop offset="95%" stop-color="#3b82f6" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <path d="{svg_path}" fill="url(#chartGrad)" stroke="#3b82f6" stroke-width="2"/>
        </svg>
        """
    else:
        chart_svg = '<div class="chart-placeholder">No chart data available</div>'

    pnl = kpis.get("net_profit", 0)
    pnl_sign = "+" if pnl >= 0 else ""
    pnl_class = "profit" if pnl >= 0 else "loss"

    placeholders = {
        "STRATEGY_NAME": strategy_name,
        "SUBTITLE": f"{symbol} | {period_str}",
        "CHART_SVG": chart_svg,
        "NET_PROFIT": f"{pnl_sign}${pnl:,.2f}",
        "NET_PROFIT_CLASS": pnl_class,
        "WIN_RATE": f"{kpis.get('win_rate', 0):.1f}%",
        "MAX_DRAWDOWN": f"{kpis.get('max_drawdown', 0):.2f}%",
        "TOTAL_TRADES": str(kpis.get("total_trades", 0)),
        "PROFIT_FACTOR": f"{kpis.get('profit_factor', 0.0):.2f}",
        "SHARPE_RATIO": f"{kpis.get('sharpe_ratio', 0.0):.2f}",
    }

    return await render_card("backtest_card.html", placeholders, width=800, height=480)


async def render_trade_alert_card(
    direction: str,  # "long" or "short"
    symbol: str,
    strategy_name: str,
    entry_price: float,
    position_size: str,
    stop_loss: float,
    take_profit: float,
    confidence_score: int,
    unrealized_pnl: float,
    roe_percent: float,
) -> bytes:
    """Renders the real-time trade alert card."""
    pnl_sign = "+" if unrealized_pnl >= 0 else ""
    pnl_class = "" if unrealized_pnl >= 0 else "negative"

    placeholders = {
        "SIGNAL_TYPE_CLASS": direction.lower(),
        "SIGNAL_TITLE": f"{direction.capitalize()} Opened",
        "SYMBOL": symbol,
        "STRATEGY_NAME": strategy_name,
        "ENTRY_PRICE": f"${entry_price:,.2f}",
        "POSITION_SIZE": position_size,
        "STOP_LOSS": f"${stop_loss:,.2f}",
        "TAKE_PROFIT": f"${take_profit:,.2f}",
        "CONFIDENCE_SCORE": f"{confidence_score}%",
        "CONFIDENCE_BAR_WIDTH": f"{confidence_score}%",
        "PNL_CLASS": pnl_class,
        "PNL_VALUE": f"{pnl_sign}${unrealized_pnl:,.2f}",
        "ROE_VALUE": f"{pnl_sign}{roe_percent:+.2f}%",
        "TIMESTAMP": datetime.utcnow().strftime("%b %d, %Y · %H:%M UTC"),
    }

    return await render_card(
        "trade_alert_card.html", placeholders, width=800, height=420
    )


async def render_market_analysis_card(
    symbol: str,
    current_price: float,
    price_change_pct: float,
    price_history: list[float],
    indicators: dict,
    ai_insight: str,
) -> bytes:
    """Renders the real-time market analysis card."""
    change_sign = "▲" if price_change_pct >= 0 else "▼"
    change_class = "up" if price_change_pct >= 0 else "down"

    # Render sparkline chart
    chart_width, chart_height = 420, 170
    spark_path = generate_svg_chart_path(price_history, chart_width, chart_height)

    spark_color = "#22c55e" if price_change_pct >= 0 else "#ef4444"

    if spark_path:
        sparkline_svg = f"""
        <svg width="100%" height="100%" viewBox="0 0 {chart_width} {chart_height}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="{spark_color}" stop-opacity="0.3"/>
                    <stop offset="100%" stop-color="{spark_color}" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <path d="{spark_path}" fill="url(#sparkGrad)" stroke="{spark_color}" stroke-width="2"/>
        </svg>
        """
    else:
        sparkline_svg = '<div class="chart-placeholder" style="line-height: 170px; text-align: center;">No history</div>'

    trend = indicators.get("trend", "Neutral")
    trend_class = (
        "bullish"
        if trend.lower() == "bullish"
        else ("bearish" if trend.lower() == "bearish" else "neutral")
    )

    placeholders = {
        "SYMBOL": symbol,
        "CURRENT_PRICE": f"${current_price:,.2f}",
        "PRICE_CHANGE_CLASS": change_class,
        "PRICE_CHANGE": f"{change_sign} {price_change_pct:+.2f}%",
        "SPARKLINE_SVG": sparkline_svg,
        "RSI_VALUE": f"{indicators.get('rsi', 50.0):.1f}",
        "RSI_CLASS": "neutral",
        "VOLUME_VALUE": indicators.get("volume", "Average"),
        "VOLUME_CLASS": "bullish"
        if "high" in indicators.get("volume", "").lower()
        or "above" in indicators.get("volume", "").lower()
        else "neutral",
        "TREND_VALUE": trend.capitalize(),
        "TREND_CLASS": trend_class,
        "VOLATILITY_VALUE": indicators.get("volatility", "Moderate"),
        "VOLATILITY_CLASS": "neutral",
        "AI_INSIGHT": ai_insight,
        "TIMESTAMP": datetime.utcnow().strftime("%b %d, %Y · %H:%M UTC"),
    }

    return await render_card(
        "market_analysis_card.html", placeholders, width=800, height=420
    )


async def render_portfolio_card(
    all_time_pnl: float,
    active_bots: list[dict],
    stats: dict,
    weekly_pnl_data: list[dict],  # list of {"day": "Mon", "pnl": 120.0}
) -> bytes:
    """Renders the Portfolio/Trading Dashboard card."""
    pnl_class = "profit" if all_time_pnl >= 0 else "loss"
    pnl_sign = "+" if all_time_pnl >= 0 else ""

    # Generate bot pills
    bot_pills = ""
    for bot in active_bots[:3]:  # limit to 3 for UI spacing
        bot_pills += f'<div class="bot-pill"><span class="bot-dot"></span> {bot.get("name")}</div>\n'

    # Generate bar chart
    bar_chart_html = ""
    max_abs_pnl = (
        max([abs(day["pnl"]) for day in weekly_pnl_data]) if weekly_pnl_data else 1
    )
    if max_abs_pnl == 0:
        max_abs_pnl = 1

    for day_data in weekly_pnl_data[:7]:
        day_pnl = day_data["pnl"]
        day_sign = "+" if day_pnl >= 0 else ""
        day_class = "profit" if day_pnl >= 0 else "loss"

        # Height ratio
        height_pct = int(min(95, max(10, (abs(day_pnl) / max_abs_pnl) * 90)))

        bar_chart_html += f"""
        <div class="bar-group">
            <div class="bar-value">{day_sign}${day_pnl:,.0f}</div>
            <div class="bar-wrapper"><div class="bar {day_class}" style="height: {height_pct}%;"></div></div>
            <div class="bar-day">{day_data["day"]}</div>
        </div>
        """

    placeholders = {
        "PNL_HERO_AMOUNT": f"{pnl_sign}${all_time_pnl:,.2f}",
        "PNL_HERO_CLASS": pnl_class,
        "ACTIVE_BOTS_COUNT": str(stats.get("active_bots_count", 0)),
        "TODAY_TRADES_COUNT": str(stats.get("today_trades", 0)),
        "TODAY_TRADES_SUB": f"{stats.get('trades_won', 0)} won · {stats.get('trades_lost', 0)} lost",
        "WIN_RATE": f"{stats.get('win_rate', 0.0):.1f}%",
        "TODAY_PNL": f"{'+' if stats.get('today_pnl', 0) >= 0 else ''}${stats.get('today_pnl', 0):,.0f}",
        "TODAY_PNL_CLASS": "profit" if stats.get("today_pnl", 0) >= 0 else "loss",
        "TODAY_PNL_ROE": f"{stats.get('today_roe', 0.0):+.1f}%",
        "BAR_CHART_HTML": bar_chart_html,
        "BOT_PILLS_HTML": bot_pills,
    }

    return await render_card("portfolio_card.html", placeholders, width=800, height=420)
