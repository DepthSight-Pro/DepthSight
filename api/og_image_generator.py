from datetime import datetime
import logging
import asyncio
from playwright.async_api import async_playwright
from .schemas import SharedBacktestData

logger = logging.getLogger(__name__)


def _generate_equity_svg_path(
    equity_data: list[list[any]], width: int, height: int
) -> str:
    """Converts equity curve data into an SVG path string."""
    if not equity_data or len(equity_data) < 2:
        return ""

    try:
        numeric_data = []
        for p in equity_data:
            try:
                # p[0] can be ISO string or timestamp
                if isinstance(p[0], (int, float)):
                    ts = float(p[0])
                else:
                    date_str = str(p[0]).replace("Z", "+00:00")
                    ts = datetime.fromisoformat(date_str).timestamp()
                numeric_data.append([ts, float(p[1])])
            except Exception as e:
                logger.warning(f"Skipping invalid equity point {p}: {e}")
                continue

        if len(numeric_data) < 2:
            logger.warning("Not enough valid points for equity curve")
            return ""

        timestamps = [p[0] for p in numeric_data]
        values = [p[1] for p in numeric_data]

        min_val, max_val = min(values), max(values)
        min_ts, max_ts = min(timestamps), max(timestamps)

        val_range = max_val - min_val if max_val > min_val else 1
        ts_range = max_ts - min_ts if max_ts > min_ts else 1
    except Exception as e:
        logger.error(f"Error preparing equity path: {e}")
        return ""

    points = [
        (
            (p[0] - min_ts) / ts_range * width,
            height - ((p[1] - min_val) / val_range * (height - 10)) - 5,
        )
        for p in numeric_data
    ]

    if not points:
        return ""

    path_d = f"M {points[0][0]:.2f} {points[0][1]:.2f}"
    for i in range(1, len(points)):
        path_d += f" L {points[i][0]:.2f} {points[i][1]:.2f}"

    area_d = path_d + f" L {points[-1][0]:.2f} {height} L {points[0][0]:.2f} {height} Z"

    return area_d


async def generate_og_image(data: SharedBacktestData) -> bytes:
    """
    Generates an Open Graph image from backtest data using Playwright.
    """
    pnl_value = data.kpis.get("total_pnl", 0)
    pnl_sign = "+" if pnl_value >= 0 else ""
    pnl_color = "#22c55e" if pnl_value >= 0 else "#ef4444"

    kpis = {
        "Net Profit": f"{pnl_sign}{pnl_value:,.2f} USD",
        "Win Rate": f"{data.kpis.get('win_rate', 0):.1f}%",
        "Max Drawdown": f"{data.kpis.get('max_drawdown', 0):.2f}%",
        "Total Trades": str(data.kpis.get("trades", 0)),
    }

    kpi_html = ""
    for name, value in kpis.items():
        value_color = (
            pnl_color
            if name == "Net Profit"
            else ("#ef4444" if name == "Max Drawdown" else "white")
        )
        kpi_html += f"""
            <div class="kpi-item">
                <div class="kpi-name">{name}</div>
                <div class="kpi-value" style="color: {value_color};">{value}</div>
            </div>
        """

    # Old SVG is commented out and replaced with a new, more detailed one.
    logo_svg = """
    <svg viewBox="0 0 340 100" xmlns="http://www.w.org/2000/svg" shape-rendering="geometricPrecision" text-rendering="optimizeLegibility" image-rendering="optimizeQuality" height="100">
        <style>
            .logo-text-depth { 
                fill: #FFFFFF !important;
            }
        </style>
        <defs>
            <linearGradient id="dashLogoTechGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#00D4FF"></stop>
                <stop offset="100%" stop-color="#0066FF"></stop>
            </linearGradient>
            <linearGradient id="dashLogoPulseGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#00D4FF" stop-opacity="0"></stop>
                <stop offset="50%" stop-color="#00D4FF" stop-opacity="0.8"></stop>
                <stop offset="100%" stop-color="#00D4FF" stop-opacity="0"></stop>
            </linearGradient>
            <filter id="dashLogoGlow">
                <feGaussianBlur stdDeviation="2.5" result="coloredBlur"></feGaussianBlur>
                <feMerge>
                    <feMergeNode in="coloredBlur"></feMergeNode>
                    <feMergeNode in="SourceGraphic"></feMergeNode>
                </feMerge>
            </filter>
        </defs>
        <!-- Icon moved from 25 to 5 -->
        <g transform="translate(5, 25)">
            <circle cx="25" cy="25" r="24" fill="none" stroke="url(#dashLogoTechGradient)" stroke-width="2" opacity="0.8"></circle>
            <circle cx="25" cy="25" r="18" fill="none" stroke="#00D4FF" stroke-width="1" opacity="0.5"></circle>
            <circle cx="25" cy="25" r="12" fill="none" stroke="#00D4FF" stroke-width="1" opacity="0.4"></circle>
            <path d="M 25 25 L 40 15 M 25 25 L 40 35 M 25 25 L 10 15 M 25 25 L 10 35" stroke="#0066FF" stroke-width="1" opacity="0.4"></path>
            <circle cx="25" cy="25" r="8" fill="url(#dashLogoTechGradient)" filter="url(#dashLogoGlow)"></circle>
            <circle cx="25" cy="25" r="4" fill="#FFFFFF" opacity="0.9"></circle>
            <path d="M 25 5 L 25 10 M 25 40 L 25 45 M 5 25 L 10 25 M 40 25 L 45 25" stroke="url(#dashLogoTechGradient)" stroke-width="2" stroke-linecap="round"></path>
            <path d="M 25 25 L 45 5" stroke="url(#dashLogoPulseGradient)" stroke-width="2" opacity="0.7">
                <animateTransform attributeName="transform" type="rotate" from="0 25 25" to="360 25 25" dur="4s" repeatCount="indefinite"></animateTransform>
            </path>
        </g>
        <!-- Text moved from 110 to 90 -->
        <text x="90" y="54" dominant-baseline="middle" font-family="Montserrat, Helvetica, Arial, sans-serif" font-size="38">
            <tspan font-weight="700" class="logo-text-depth">Depth</tspan>
            <tspan fill="url(#dashLogoTechGradient)" font-weight="300" class="logo-text-sight">Sight</tspan>
        </text>
    </svg>
    """

    chart_width = 650
    chart_height = 300
    equity_curve_path = _generate_equity_svg_path(
        data.equity_curve, chart_width, chart_height
    )
    chart_svg = (
        f"""
    <svg width="{chart_width}" height="{chart_height}" viewBox="0 0 {chart_width} {chart_height}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stop-color="#3b82f6" stop-opacity="0.4"/>
                <stop offset="95%" stop-color="#3b82f6" stop-opacity="0"/>
            </linearGradient>
        </defs>
        <path d="{equity_curve_path}" fill="url(#chartGradient)" stroke="#3b82f6" stroke-width="2" />
    </svg>
    """
        if equity_curve_path
        else '<div class="chart-placeholder">No chart data available</div>'
    )

    strategy_display_name = data.strategy_name
    if strategy_display_name == "VisualBuilderStrategy" and data.parameters:
        strategy_display_name = (
            data.parameters.get("name")
            or data.parameters.get("strategy_display_name")
            or data.parameters.get("config", {}).get("name")
            or strategy_display_name
        )

    if len(strategy_display_name) > 18:
        strategy_display_name = strategy_display_name[:18] + "..."

    # Format period string
    try:
        start_dt = datetime.fromisoformat(str(data.period.start))
        end_dt = datetime.fromisoformat(str(data.period.end))
        months_en = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        period_str = f"Period: {months_en[start_dt.month - 1]} {start_dt.day} - {months_en[end_dt.month - 1]} {end_dt.day}"
    except Exception:
        period_str = ""

    subtitle_str = f"{data.symbol} | {period_str}"

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Montserrat:wght@300;700&display=swap" rel="stylesheet">
        <style>
            body {{ margin: 0; font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #1c1917, #111827); color: #e5e7eb; display: flex; justify-content: center; align-items: center; width: 1200px; height: 630px; }}
            .container {{ width: 1100px; height: 550px; display: flex; flex-direction: column; justify-content: space-between; }}
            .header {{ display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 20px; }}
            .title-block {{ display: flex; flex-direction: column; }}
            .strategy-name {{ font-size: 64px; font-weight: 700; color: white; margin: 0; line-height: 1.2; }}
            .subtitle {{ font-size: 36px; font-weight: 500; color: #9ca3af; margin-top: 12px; }}
            .content {{ display: flex; justify-content: space-between; align-items: flex-end; }}
            .chart-placeholder {{ width: 650px; height: 300px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #4b5563; border: 2px dashed #374151; }}
            .kpi-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; width: 400px; }}
            .kpi-item {{ background-color: rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 20px; }}
            .kpi-name {{ font-size: 20px; color: #9ca3af; margin-bottom: 8px; }}
            .kpi-value {{ font-size: 32px; font-weight: 600; }}
            .footer {{ font-size: 24px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="title-block">
                    <h1 class="strategy-name">{strategy_display_name}</h1>
                    <div class="subtitle">{subtitle_str}</div>
                </div>
                {logo_svg}
            </div>
            <div class="content">
                {chart_svg}
                <div class="kpi-grid">{kpi_html}</div>
            </div>
            <div class="footer">depthsight.pro</div>
        </div>
    </body>
    </html>
    """

    logger.info("Launching Playwright for OG image generation...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1200, "height": 630})
            await page.set_content(html_template)
            await page.evaluate("document.fonts.ready")
            await asyncio.sleep(0.5)
            screenshot_bytes = await page.screenshot(type="png")
            await browser.close()
            logger.info(
                f"OG image generated successfully, size: {len(screenshot_bytes)} bytes"
            )
            return screenshot_bytes
    except Exception as e:
        logger.error(f"Playwright rendering failed: {e}", exc_info=True)
        raise
