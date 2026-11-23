import asyncio
from datetime import datetime
import html
import logging
from playwright.async_api import async_playwright
from .schemas import SharedBacktestData, SharedTradeData

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
    kpis_raw = data.kpis or {}
    try:
        pnl_raw = kpis_raw.get("total_pnl")
        pnl_value = float(pnl_raw) if pnl_raw is not None else 0.0
    except (ValueError, TypeError):
        pnl_value = 0.0

    pnl_sign = "+" if pnl_value >= 0 else ""
    pnl_color = "#22c55e" if pnl_value >= 0 else "#ef4444"

    try:
        win_rate_raw = kpis_raw.get("win_rate")
        win_rate_value = float(win_rate_raw) if win_rate_raw is not None else 0.0
    except (ValueError, TypeError):
        win_rate_value = 0.0

    try:
        max_dd_raw = kpis_raw.get("max_drawdown")
        if max_dd_raw is None:
            max_dd_raw = kpis_raw.get("max_drawdown_pct")
        max_dd_value = float(max_dd_raw) if max_dd_raw is not None else 0.0
    except (ValueError, TypeError):
        max_dd_value = 0.0

    trades_value = (
        kpis_raw.get("trades")
        if kpis_raw.get("trades") is not None
        else kpis_raw.get("total_trades", 0)
    )

    kpis = {
        "Net Profit": f"{pnl_sign}{pnl_value:,.2f} USD",
        "Win Rate": f"{win_rate_value:.1f}%",
        "Max Drawdown": f"{max_dd_value:.2f}%",
        "Total Trades": str(trades_value),
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
            .strategy-name {{ font-size: 44px; font-weight: 700; color: white; margin: 0; line-height: 1.2; }}
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


def _get_exchange_svg_icon(exchange: str | None) -> str:
    """Returns an inline SVG icon for the specified crypto exchange."""
    if not exchange:
        ex = "binance"
    else:
        ex = exchange.lower().strip()
        for suffix in ["_testnet", "_futures", "_usdtm", "_usdm", "_linear", "_swap", "_spot"]:
            if ex.endswith(suffix):
                ex = ex[: -len(suffix)]
                break

    if ex in ("binance", "binance_futures", "binance_spot"):
        return """<svg viewBox="0 0 1024 1024" width="15" height="15" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><circle cx="512" cy="512" r="512" fill="#f3ba2f"/><path fill="#fff" d="M404.9 468 512 360.9l107.1 107.2 62.3-62.3L512 236.3 342.6 405.7z"/><path transform="rotate(-45.001 298.629 511.998)" fill="#fff" d="M254.6 467.9h88.1V556h-88.1z"/><path fill="#fff" d="M404.9 556 512 663.1l107.1-107.2 62.4 62.3h-.1L512 787.7 342.6 618.3l-.1-.1z"/><path transform="rotate(-45.001 725.364 512.032)" fill="#fff" d="M681.3 468h88.1v88.1h-88.1z"/><path fill="#fff" d="M575.2 512 512 448.7l-46.7 46.8-5.4 5.3-11.1 11.1-.1.1.1.1 63.2 63.2 63.2-63.3z"/></svg>"""
    elif ex in ("bybit", "bybit_testnet"):
        return """<svg viewBox="0 0 968 646.9" width="16" height="11" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><path fill="#F7A600" d="M640.4,389.9V201h38v188.9H640.4z"/><path fill="#1a1a1a" d="M197.8,446h-81.4V257.1h78.1c38,0,60.1,20.7,60.1,53.1c0,21-14.2,34.5-24,39c11.7,5.3,26.8,17.2,26.8,42.5 C257.4,426.9,232.5,446,197.8,446z M191.6,290h-37.1v43.5h37.1c16.1,0,25.1-8.8,25.1-21.8S207.7,290,191.6,290z M194,366.6h-39.6 v46.4H194c17.2,0,25.4-10.6,25.4-23.4S211.2,366.6,194,366.6z"/><path fill="#1a1a1a" d="M373.2,368.5V446h-37.7v-77.5L277,257.1h41.2l36.3,76.1l35.8-76.1h41.2L373.2,368.5z"/><path fill="#1a1a1a" d="M539.3,446h-81.4V257.1H536c38,0,60.1,20.7,60.1,53.1c0,21-14.2,34.5-24,39c11.7,5.3,26.8,17.2,26.8,42.5 C598.8,426.9,574,446,539.3,446z M533,290h-37.1v43.5H533c16.1,0,25.1-8.8,25.1-21.8S549.1,290,533,290z M535.4,366.6h-39.6v46.4 h39.6c17.2,0,25.4-10.6,25.4-23.4S552.7,366.6,535.4,366.6L535.4,366.6z"/><path fill="#1a1a1a" d="M800.7,290v156h-38V290H712v-32.9h139.5V290H800.7z"/></svg>"""
    elif ex in ("bitget", "bitget_futures"):
        return """<svg viewBox="0 0 200 200" width="14" height="14" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><circle cx="100" cy="100" r="100" fill="#00F0FF"/><path d="M93.1911 80.4883H128.212L164.039 116.086C166.37 118.402 166.382 122.168 164.063 124.496L118.117 170.674H82.0405L92.9473 160.07L132.992 120.278L93.4556 80.4854" fill="black"/><path d="M107.585 120.188H72.5635L36.7367 84.5904C34.4061 82.2747 34.3942 78.5083 36.7129 76.1807L82.6588 30H118.735L107.829 40.6036L67.7835 80.396L107.32 120.188" fill="black"/></svg>"""
    elif ex in ("okx", "okex"):
        return """<svg viewBox="0 0 2500 2500" width="14" height="14" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><rect width="2500" height="2500" rx="400" fill="#000000"/><path fill="#FFFFFF" d="M1464.3,1015.3h-405.2c-17.2,0-31.3,14.1-31.3,31.3v405.2c0,17.2,14.1,31.3,31.3,31.3h405.2c17.2,0,31.3-14.1,31.3-31.3 v-405.2C1495.6,1029.4,1481.5,1015.3,1464.3,1015.3z"/><path fill="#FFFFFF" d="M996.6,549.1H591.4c-17.2,0-31.3,14.1-31.3,31.3v405.2c0,17.2,14.1,31.3,31.3,31.3h405.2c17.2,0,31.3-14.1,31.3-31.3 V580.4C1027.8,563.2,1013.8,549.1,996.6,549.1z"/><path fill="#FFFFFF" d="M1930.5,549.1h-405.2c-17.2,0-31.3,14.1-31.3,31.3v405.2c0,17.2,14.1,31.3,31.3,31.3h405.2c17.2,0,31.3-14.1,31.3-31.3 V580.4C1961.8,563.2,1947.7,549.1,1930.5,549.1z"/><path fill="#FFFFFF" d="M996.6,1481.5H591.4c-17.2,0-31.3,14.1-31.3,31.3V1918c0,17.2,14.1,31.3,31.3,31.3h405.2c17.2,0,31.3-14.1,31.3-31.3 v-405.2C1027.8,1495.6,1013.8,1481.5,996.6,1481.5z"/><path fill="#FFFFFF" d="M1930.5,1481.5h-405.2c-17.2,0-31.3,14.1-31.3,31.3V1918c0,17.2,14.1,31.3,31.3,31.3h405.2c17.2,0,31.3-14.1,31.3-31.3 v-405.2C1961.8,1495.6,1947.7,1481.5,1930.5,1481.5z"/></svg>"""
    elif ex == "weex":
        return """<svg viewBox="0 0 161 100" width="16" height="10" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><path fill-rule="evenodd" clip-rule="evenodd" d="M85.5881 56.6164L98.0561 43.9989L80.6568 26L63.2575 43.9989L75.7255 56.5795L67.9279 64.5036L47.1185 43.9989L56.6566 34.2891H65.1681L71.6144 27.3064H53.5647L37.3335 43.9989L67.9279 73.9631L80.6568 61.6005L93.3857 74L123.98 43.9989L107.749 27.3433H89.6992L96.1455 34.3259H104.657L114.195 43.9989L93.3857 64.5405L85.5881 56.6164ZM80.6573 51.1132L73.4081 43.9964L80.6573 36.3354L87.9065 43.9964L80.6573 51.1132Z" fill="#D8AE15"/></svg>"""
    elif ex in ("gate", "gateio"):
        return """<svg viewBox="0 0 2500 2500" width="14" height="14" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><rect width="2500" height="2500" rx="400" fill="#0c111c"/><path fill="#2354E6" d="M1250,1937.5c-379.7,0-687.5-307.8-687.5-687.5c0-379.7,307.8-687.5,687.5-687.5V0 C559.6,0,0,559.6,0,1250c0,690.3,559.6,1250,1250,1250c690.3,0,1250-559.6,1250-1250h-562.5 C1937.5,1629.7,1629.7,1937.5,1250,1937.5z"/><polygon fill="#17E6A1" points="1250,1250 1937.5,1250 1937.5,562.5 1250,562.5"/></svg>"""
    elif ex in ("hyperliquid", "hl"):
        return """<svg viewBox="0 0 200 200" width="14" height="14" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; display: block;"><circle cx="100" cy="100" r="100" fill="#011916"/><path fill="#00D28E" d="M175.1 99.3c0 49.5-30.4 65.3-46.5 51.3-13.1-11.5-17-35.9-36.8-38.4-25.1-3-27.4 30.4-43.9 30.4-19.3 0-23-27.8-23-42.3 0-14.7 4.1-34.7 20.5-34.7 19.1 0 20.2 28.8 44.2 27.1 23.7-1.6 24.2-31.5 39.8-44.2 13.6-11.3 45.8.7 45.8 50.8Z"/></svg>"""
    else:
        return """<svg viewBox="0 0 24 24" width="14" height="14" fill="#1a1a1a" style="vertical-align: middle; display: block;"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>"""


async def generate_trade_og_image(data: SharedTradeData) -> bytes:
    """
    Generates a 1200x630 Open Graph PnL Card image for a real trade.
    Transfers 100% of the design, typography, layout, official exchange SVG logos,
    and visual effects from trade_pnl_card_preview.html.
    """
    direction = (data.direction or "LONG").upper()
    is_long = direction in ("LONG", "BUY")

    pnl_value = data.pnl if data.pnl is not None else 0.0
    roi_value = data.roi_pct if data.roi_pct is not None else 0.0
    is_profit = (roi_value >= 0) if data.roi_pct is not None else (pnl_value >= 0)

    pnl_sign = "+" if pnl_value >= 0 else ""
    roi_sign = "+" if roi_value >= 0 else ""

    accent_color = "#34d399" if is_profit else "#f87171"
    glow_class = "glow-profit" if is_profit else "glow-loss"

    mode = (data.pnl_display_mode or "PERCENT").upper()
    if mode == "USD":
        metric_label = "Net Realized Profit (USD)"
        main_pnl_str = f"{pnl_sign}${pnl_value:,.2f}"
        secondary_pnl_html = ""
    elif mode == "BOTH":
        metric_label = "Net Profit & ROI"
        main_pnl_str = f"{roi_sign}{roi_value:.2f}%"
        secondary_pnl_html = f"""<span class="secondary-pnl font-mono">({pnl_sign}${pnl_value:,.2f} USD)</span>"""
    else:  # PERCENT (Private default)
        metric_label = "Return on Investment (ROI)"
        main_pnl_str = f"{roi_sign}{roi_value:.2f}%"
        secondary_pnl_html = ""

    # Direction badge styling
    if is_long:
        dir_class = "dir-long"
        dir_text = "LONG 10x" if "10X" in direction else f"{direction} 10x" if "X" not in direction else direction
    else:
        dir_class = "dir-short"
        dir_text = "SHORT 10x" if "10X" in direction else f"{direction} 10x" if "X" not in direction else direction

    # Symbol formatting
    raw_symbol = data.symbol or "Asset"
    if "USDT" in raw_symbol:
        base_asset = raw_symbol.replace("USDT", "").strip()
        display_symbol = f"{base_asset} / USDT"
    else:
        base_asset = raw_symbol
        display_symbol = raw_symbol

    # Strategy badge
    strat_badge_html = ""
    if data.strategy_name:
        esc_strat = html.escape(data.strategy_name[:26])
        strat_badge_html = f"""<span class="strat-badge font-mono">⚡ {esc_strat}</span>"""

    # Trajectory SVG Curve
    traj_status = (data.exit_reason or ("TAKE PROFIT" if is_profit else "STOP LOSS")).upper()
    if is_profit:
        traj_area_d = "M 0 65 Q 40 60 70 45 T 140 25 T 200 10 L 200 80 L 0 80 Z"
        traj_line_d = "M 0 65 Q 40 60 70 45 T 140 25 T 200 10"
        traj_line_stroke = "#10b981"
        traj_last_y = 10
        traj_ping_fill = "#34d399"
        traj_stop_color = "#10b981"
        traj_status_color = "#34d399"
        corner_glow = "rgba(16, 185, 129, 0.15)"
    else:
        traj_area_d = "M 0 15 Q 40 25 70 45 T 140 60 T 200 70 L 200 80 L 0 80 Z"
        traj_line_d = "M 0 15 Q 40 25 70 45 T 140 60 T 200 70"
        traj_line_stroke = "#ef4444"
        traj_last_y = 70
        traj_ping_fill = "#f87171"
        traj_stop_color = "#ef4444"
        traj_status_color = "#f87171"
        corner_glow = "rgba(239, 68, 68, 0.15)"

    entry_str = f"${data.entry_price:,.2f}" if data.entry_price is not None else "—"
    exit_str = f"${data.exit_price:,.2f}" if data.exit_price is not None else "—"

    # Duration
    duration_str = "—"
    if data.duration_seconds is not None and data.duration_seconds > 0:
        h, rem = divmod(int(data.duration_seconds), 3600)
        m, _ = divmod(rem, 60)
        duration_str = f"{h}ч {m}м" if h > 0 else f"{m}м"

    # Card 3 in bottom row: Position Size (if public) or Exit Reason
    if data.quantity is not None and data.quantity > 0:
        card3_title = "ОБЪЕМ ПОЗИЦИИ"
        card3_val = f"{data.quantity:g} {base_asset}"
        card3_color = "#22d3ee"
    else:
        card3_title = "ЗАКРЫТА ПО"
        card3_val = data.exit_reason or ("Take Profit" if is_profit else "Stop Loss")
        card3_color = accent_color

    # Exchange badge
    raw_exchange = data.exchange or "binance"
    exchange_logo_svg = _get_exchange_svg_icon(raw_exchange)
    exchange_display = raw_exchange.upper().replace("_TESTNET", "") + " USDT-M"

    # Referral & QR code
    ref_code = data.referral_code or (data.author_username or "DEPTHSIGHT")
    bonus_tokens = data.bonus_tokens or 1000

    # Date
    close_time_str = (
        data.timestamp_close.strftime("%d.%m.%Y %H:%M")
        if hasattr(data.timestamp_close, "strftime")
        else str(data.timestamp_close)[:16]
    )

    slug_short = (data.trade_uuid or "trade")[:12]

    # Official DepthSight Logo SVG (identical to trade_pnl_card_preview.html)
    depthsight_logo_svg = """
    <svg viewBox="0 0 340 100" xmlns="http://www.w3.org/2000/svg" class="glow-cyan" height="52" shape-rendering="geometricPrecision">
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
        <g transform="translate(5, 25)">
            <circle cx="25" cy="25" r="24" fill="none" stroke="url(#dashLogoTechGradient)" stroke-width="2" opacity="0.8"></circle>
            <circle cx="25" cy="25" r="18" fill="none" stroke="#00D4FF" stroke-width="1" opacity="0.5"></circle>
            <circle cx="25" cy="25" r="12" fill="none" stroke="#00D4FF" stroke-width="1" opacity="0.4"></circle>
            <path d="M 25 25 L 40 15 M 25 25 L 40 35 M 25 25 L 10 15 M 25 25 L 10 35" stroke="#0066FF" stroke-width="1" opacity="0.4"></path>
            <circle cx="25" cy="25" r="8" fill="url(#dashLogoTechGradient)" filter="url(#dashLogoGlow)"></circle>
            <circle cx="25" cy="25" r="4" fill="#FFFFFF" opacity="0.9"></circle>
            <path d="M 25 5 L 25 10 M 25 40 L 25 45 M 5 25 L 10 25 M 40 25 L 45 25" stroke="url(#dashLogoTechGradient)" stroke-width="2" stroke-linecap="round"></path>
        </g>
        <text x="90" y="54" dominant-baseline="middle" font-family="Montserrat, Helvetica, Arial, sans-serif" font-size="38">
            <tspan font-weight="700" fill="#FFFFFF">Depth</tspan>
            <tspan fill="url(#dashLogoTechGradient)" font-weight="300">Sight</tspan>
        </text>
    </svg>
    """

    html_template = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800;900&family=Montserrat:wght@400;600;700;800;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            width: 1200px;
            height: 630px;
            background: #090d16;
            color: #f3f4f6;
            font-family: 'Inter', sans-serif;
            overflow: hidden;
            position: relative;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        .font-mono {{
            font-family: 'JetBrains Mono', monospace;
        }}
        .font-display {{
            font-family: 'Montserrat', sans-serif;
        }}
        .glow-profit {{
            text-shadow: 0 0 30px rgba(34, 197, 94, 0.4), 0 0 60px rgba(34, 197, 94, 0.15);
        }}
        .glow-loss {{
            text-shadow: 0 0 30px rgba(239, 68, 68, 0.4), 0 0 60px rgba(239, 68, 68, 0.15);
        }}
        .glow-cyan {{
            filter: drop-shadow(0 0 10px rgba(0, 212, 255, 0.4));
        }}
        .grid-pattern {{
            position: absolute;
            inset: 0;
            background-image: 
                radial-gradient(rgba(0, 212, 255, 0.07) 1px, transparent 1px),
                linear-gradient(to right, rgba(255, 255, 255, 0.02) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
            background-size: 20px 20px, 40px 40px, 40px 40px;
            background-color: #090d16;
        }}
        .corner-glow-left {{
            position: absolute;
            top: -80px;
            left: -80px;
            width: 320px;
            height: 320px;
            border-radius: 50%;
            background: {corner_glow};
            filter: blur(90px);
            pointer-events: none;
        }}
        .corner-glow-right {{
            position: absolute;
            bottom: -80px;
            right: -80px;
            width: 320px;
            height: 320px;
            border-radius: 50%;
            background: rgba(0, 212, 255, 0.10);
            filter: blur(90px);
            pointer-events: none;
        }}
        .card-container {{
            position: relative;
            z-index: 10;
            width: 1200px;
            height: 630px;
            padding: 38px 46px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        /* Header */
        .header-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 70px;
        }}
        .badges-group {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
        }}
        .badge-live {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 9999px;
            background: rgba(16, 185, 129, 0.12);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.35);
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .live-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #34d399;
            box-shadow: 0 0 8px #34d399;
        }}
        .badge-exchange {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 4px 14px 4px 5px;
            border-radius: 9999px;
            background: rgba(255, 255, 255, 0.04);
            color: #e5e7eb;
            border: 1px solid rgba(255, 255, 255, 0.12);
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .exchange-logo-circle {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
            overflow: hidden;
        }}
        /* Hero Section */
        .hero-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            height: 270px;
        }}
        .hero-left {{
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 12px;
        }}
        .hero-title-row {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .symbol-text {{
            font-size: 46px;
            font-weight: 900;
            color: #ffffff;
            letter-spacing: -0.02em;
            line-height: 1;
        }}
        .dir-long {{
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 900;
            letter-spacing: 0.08em;
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.4);
            text-transform: uppercase;
        }}
        .dir-short {{
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 900;
            letter-spacing: 0.08em;
            background: rgba(168, 85, 247, 0.2);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.4);
            text-transform: uppercase;
        }}
        .strat-badge {{
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 12px;
            color: #22d3ee;
            background: rgba(6, 182, 212, 0.12);
            border: 1px solid rgba(6, 182, 212, 0.25);
            max-width: 260px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .metric-label {{
            font-size: 13px;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: #9ca3af;
            margin-bottom: 4px;
        }}
        .pnl-block {{
            display: flex;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
        }}
        .main-pnl {{
            font-size: 60px;
            font-weight: 900;
            color: {accent_color};
            letter-spacing: -0.02em;
            line-height: 1;
        }}
        .secondary-pnl {{
            font-size: 30px;
            font-weight: 700;
            color: {accent_color}cc;
            line-height: 1;
        }}
        /* Trajectory Curve Box */
        .hero-right {{
            width: 380px;
            display: flex;
            justify-content: flex-end;
        }}
        .traj-card {{
            width: 360px;
            height: 200px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.07);
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
        }}
        .traj-top {{
            font-size: 11px;
            color: #9ca3af;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .traj-status {{
            font-weight: 700;
            color: {traj_status_color};
        }}
        .traj-bottom {{
            font-size: 11px;
            color: #9ca3af;
            display: flex;
            justify-content: space-between;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
            padding-top: 6px;
        }}
        /* Bottom Row */
        .bottom-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            height: 110px;
            padding-top: 10px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .metrics-grid {{
            flex: 1;
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 12px;
        }}
        .metric-card {{
            background: rgba(255, 255, 255, 0.03);
            border-radius: 10px;
            padding: 12px 14px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        .metric-card-title {{
            font-size: 10px;
            text-transform: uppercase;
            color: #9ca3af;
            letter-spacing: 0.05em;
        }}
        .metric-card-val {{
            font-size: 14px;
            font-weight: 700;
            color: white;
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        /* Referral & QR Block */
        .ref-card {{
            width: 320px;
            background: linear-gradient(to right, rgba(0, 212, 255, 0.10), rgba(0, 102, 255, 0.10));
            border-radius: 10px;
            padding: 10px 14px;
            border: 1px solid rgba(0, 212, 255, 0.35);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }}
        .ref-info {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
        }}
        .ref-header {{
            font-size: 10px;
            font-weight: 700;
            color: #67e8f9;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .ref-header-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #22d3ee;
        }}
        .ref-code-line {{
            font-size: 13px;
            font-weight: 800;
            color: white;
            margin-top: 3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .ref-code-highlight {{
            color: #22d3ee;
        }}
        .ref-bonus-line {{
            font-size: 10px;
            color: #9ca3af;
            margin-top: 3px;
        }}
        .qr-box {{
            flex-shrink: 0;
            width: 48px;
            height: 48px;
            background: white;
            border-radius: 6px;
            padding: 3px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        /* Footer */
        .footer-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 11px;
            color: #6b7280;
            padding-top: 6px;
        }}
        .footer-url {{
            color: rgba(6, 182, 212, 0.9);
            font-weight: 600;
            letter-spacing: 0.05em;
        }}
    </style>
</head>
<body>
    <!-- Background Ambient Gradients -->
    <div class="grid-pattern"></div>
    <div class="corner-glow-left"></div>
    <div class="corner-glow-right"></div>

    <div class="card-container">
        
        <!-- 1. HEADER ROW -->
        <div class="header-row">
            <!-- DepthSight Logo -->
            <div style="display: flex; align-items: center;">
                {depthsight_logo_svg}
            </div>

            <!-- Badges: Live Trade + Exchange with Logo -->
            <div class="badges-group">
                <span class="badge-live">
                    <span class="live-dot"></span>
                    Live Trade
                </span>
                <span class="badge-exchange">
                    <span class="exchange-logo-circle">{exchange_logo_svg}</span>
                    {exchange_display}
                </span>
            </div>
        </div>

        <!-- 2. HERO MIDDLE SECTION -->
        <div class="hero-row">
            <div class="hero-left">
                <!-- Pair + Direction + Strategy -->
                <div class="hero-title-row">
                    <span class="symbol-text font-display">{display_symbol}</span>
                    <span class="{dir_class} font-display">{dir_text}</span>
                    {strat_badge_html}
                </div>

                <!-- Big Metric Block -->
                <div>
                    <div class="metric-label font-mono">{metric_label}</div>
                    <div class="pnl-block">
                        <span class="main-pnl font-mono {glow_class}">{main_pnl_str}</span>
                        {secondary_pnl_html}
                    </div>
                </div>
            </div>

            <!-- Trajectory Sparkline Curve -->
            <div class="hero-right">
                <div class="traj-card">
                    <div class="traj-top font-mono">
                        <span>EXECUTION</span>
                        <span class="traj-status">{traj_status}</span>
                    </div>

                    <svg viewBox="0 0 200 80" preserveAspectRatio="none" style="width: 100%; height: 118px; overflow: visible;">
                        <defs>
                            <linearGradient id="ogTrajGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stop-color="{traj_stop_color}" stop-opacity="0.35"/>
                                <stop offset="100%" stop-color="{traj_stop_color}" stop-opacity="0"/>
                            </linearGradient>
                        </defs>
                        <path d="{traj_area_d}" fill="url(#ogTrajGrad)"/>
                        <path d="{traj_line_d}" fill="none" stroke="{traj_line_stroke}" stroke-width="3" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
                        <circle cx="200" cy="{traj_last_y}" r="3.5" fill="{traj_ping_fill}"/>
                    </svg>

                    <div class="traj-bottom font-mono">
                        <span>In: {entry_str}</span>
                        <span>Out: {exit_str}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 3. BOTTOM ROW: METRICS + REFERRAL QR BLOCK -->
        <div class="bottom-row">
            <div class="metrics-grid font-mono">
                <div class="metric-card">
                    <div class="metric-card-title">Вход / Выход</div>
                    <div class="metric-card-val">{entry_str} → {exit_str}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-card-title">Длительность</div>
                    <div class="metric-card-val">{duration_str}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-card-title">{card3_title}</div>
                    <div class="metric-card-val" style="color: {card3_color};">{card3_val}</div>
                </div>
            </div>

            <div class="ref-card font-mono">
                <div class="ref-info">
                    <div class="ref-header">
                        <span class="ref-header-dot"></span>
                        Торгуй на DepthSight
                    </div>
                    <div class="ref-code-line">
                        Реф-код: <span class="ref-code-highlight">{ref_code}</span>
                    </div>
                    <div class="ref-bonus-line">
                        +{bonus_tokens:,} бонусных токенов
                    </div>
                </div>

                <div class="qr-box">
                    <svg viewBox="0 0 29 29" width="42" height="42" fill="black">
                        <rect x="2" y="2" width="7" height="7"/>
                        <rect x="3" y="3" width="5" height="5" fill="white"/>
                        <rect x="4" y="4" width="3" height="3" fill="black"/>
                        <rect x="20" y="2" width="7" height="7"/>
                        <rect x="21" y="3" width="5" height="5" fill="white"/>
                        <rect x="22" y="4" width="3" height="3" fill="black"/>
                        <rect x="2" y="20" width="7" height="7"/>
                        <rect x="3" y="21" width="5" height="5" fill="white"/>
                        <rect x="4" y="22" width="3" height="3" fill="black"/>
                        <rect x="11" y="4" width="2" height="2"/>
                        <rect x="15" y="4" width="2" height="2"/>
                        <rect x="11" y="8" width="4" height="2"/>
                        <rect x="12" y="12" width="5" height="5"/>
                        <rect x="4" y="12" width="3" height="3"/>
                        <rect x="20" y="11" width="2" height="4"/>
                        <rect x="23" y="13" width="3" height="3"/>
                        <rect x="11" y="20" width="3" height="4"/>
                        <rect x="16" y="22" width="4" height="3"/>
                        <rect x="22" y="22" width="4" height="4"/>
                    </svg>
                </div>
            </div>
        </div>

        <!-- 4. FOOTER URL & DATE -->
        <div class="footer-row font-mono">
            <span class="footer-url">app.depthsight.pro/t/{slug_short}</span>
            <span>Закрыта: {close_time_str}</span>
        </div>

    </div>
</body>
</html>
"""

    logger.info("Launching Playwright for Trade OG image generation...")
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
                f"Trade OG image generated successfully, size: {len(screenshot_bytes)} bytes"
            )
            return screenshot_bytes
    except Exception as e:
        logger.error(f"Playwright trade rendering failed: {e}", exc_info=True)
        raise

