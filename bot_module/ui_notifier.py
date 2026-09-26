# bot_module/ui_notifier.py
"""In-app / Web Push mirror of Telegram trading notifications.

Single funnel: every trading event that currently produces a Telegram message
(``bot_module.telegram_notifier.TelegramNotifier``) is mirrored as a structured
payload published to Redis channel ``user:{user_id}:notifications``, which the
WebSocket server already forwards to subscribed frontends (see
``api/websocket_server.py`` protected pattern ``r"^user:(\\d+):notifications$"``).

Design goals (the controller is already huge, so this module owns everything):
- ``TradingController`` / ``RiskManager`` call sites stay untouched. Instead the
  controller wraps its ``TelegramNotifier`` instance once via
  :func:`wrap_telegram_notifier`; the proxy forwards every call to the real
  notifier and schedules a fire-and-forget UI mirror with the same kwargs.
- No Markdown: frontends render title/body themselves, so payloads carry plain
  text plus scalar ``data`` (prices, quantities, PnL, reasons).
- Same user toggles as Telegram (``notifyNewPosition`` etc. from
  ``app_config.notifications``). HFT subtypes without a dedicated toggle reuse
  the closest trading toggle.
- History is intentionally NOT persisted server-side (realtime + localStorage on
  clients, per product decision). Redis pub/sub is fire-and-forget.
- Web Push (background delivery when the tab is closed) reuses the existing
  ``send_push_notification`` plumbing; it is scheduled only when a push
  subscription could be resolved, otherwise WS-only delivery applies.
- Nothing here ever raises into trading code paths: all entry points are
  wrapped in try/except and degrade to logs.

Payload contract (consumed by web frontend + PWA)::
    {
        "id": "<uuid4 hex>",
        "type": "position_opened | position_closed | partial_tp | sl_moved | "
                "risk_alert | order_error | blacklist | bot_error | "
                "hft_signal | hft_trade | hft_closed | hft_info | info",
        "severity": "info | success | warning | error",
        "title": "plain-text headline (may contain one emoji prefix)",
        "body": "plain-text details",
        "symbol": "BTCUSDT" | None,
        "side": "LONG | SHORT | BUY | SELL" | None,
        "ts_ms": 1234567890000,
        "user_id": 1,
        "api_key_id": 5 | None,
        "tag": "stable dedup tag for push collapsing",
        "data": {"scalars only"},
    }
"""

import asyncio
import inspect
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("bot_module.ui_notifier")

# Redis channel template; must stay in sync with the WS server allow-list.
NOTIFICATIONS_CHANNEL_TEMPLATE = "user:{user_id}:notifications"

# --- UI notification types -------------------------------------------------
POSITION_OPENED = "position_opened"
POSITION_CLOSED = "position_closed"
PARTIAL_TP = "partial_tp"
SCALE_IN = "scale_in"
SL_MOVED = "sl_moved"
RISK_ALERT = "risk_alert"
ORDER_ERROR = "order_error"
BLACKLIST = "blacklist"
BOT_ERROR = "bot_error"
HFT_SIGNAL = "hft_signal"
HFT_TRADE = "hft_trade"
HFT_CLOSED = "hft_closed"
HFT_INFO = "hft_info"
INFO = "info"

ALL_TYPES = (
    POSITION_OPENED,
    POSITION_CLOSED,
    PARTIAL_TP,
    SCALE_IN,
    SL_MOVED,
    RISK_ALERT,
    ORDER_ERROR,
    BLACKLIST,
    BOT_ERROR,
    HFT_SIGNAL,
    HFT_TRADE,
    HFT_CLOSED,
    HFT_INFO,
    INFO,
)

# Telegram event name -> UI type.
TELEGRAM_EVENT_TO_UI_TYPE = {
    "NEW_POSITION": POSITION_OPENED,
    "POSITION_CLOSED": POSITION_CLOSED,
    "PARTIAL_TP_FILLED": PARTIAL_TP,
    "PARTIAL_TP": PARTIAL_TP,
    "SCALE_IN_FILLED": SCALE_IN,
    "SL_MOVED_TO_BE": SL_MOVED,
    "RISK_MANAGER_ALERT": RISK_ALERT,
    "RISK_ALERTS": RISK_ALERT,
    "ORDER_EXECUTION_ERROR": ORDER_ERROR,
    "ORDER_ERRORS": ORDER_ERROR,
    "BOT_ERROR": BOT_ERROR,
    "BOT_ERRORS": BOT_ERROR,
    "BLACKLIST_ALERT": BLACKLIST,
    "BLACKLIST_ALERTS": BLACKLIST,
}

# Telegram event name (and UI type) -> user setting key in
# app_config.notifications. Same toggles govern Telegram and in-app delivery.
# HFT engine events have no dedicated toggles and reuse the closest trading one;
# lifecycle events (engine started/stopped) are always delivered.
EVENT_TO_SETTING_KEY = {
    "NEW_POSITION": "notifyNewPosition",
    "POSITION_CLOSED": "notifyPositionClosed",
    "PARTIAL_TP_FILLED": "notifyPartialTp",
    "PARTIAL_TP": "notifyPartialTp",
    "SL_MOVED_TO_BE": "notifySlMovedToBe",
    "RISK_MANAGER_ALERT": "notifyRiskAlerts",
    "RISK_ALERTS": "notifyRiskAlerts",
    "ORDER_EXECUTION_ERROR": "notifyOrderErrors",
    "ORDER_ERRORS": "notifyOrderErrors",
    "BOT_ERROR": "notifyBotErrors",
    "BOT_ERRORS": "notifyBotErrors",
    "BLACKLIST_ALERT": "notifyBlacklistAlerts",
    "BLACKLIST_ALERTS": "notifyBlacklistAlerts",
    POSITION_OPENED: "notifyNewPosition",
    POSITION_CLOSED: "notifyPositionClosed",
    PARTIAL_TP: "notifyPartialTp",
    SL_MOVED: "notifySlMovedToBe",
    "SCALE_IN_FILLED": "notifyNewPosition",
    SCALE_IN: "notifyNewPosition",
    RISK_ALERT: "notifyRiskAlerts",
    ORDER_ERROR: "notifyOrderErrors",
    BOT_ERROR: "notifyBotErrors",
    BLACKLIST: "notifyBlacklistAlerts",
    HFT_SIGNAL: "notifyNewPosition",
    HFT_TRADE: "notifyPositionClosed",
    HFT_CLOSED: "notifyPositionClosed",
    # HFT_INFO and INFO intentionally have no toggle (always delivered).
}

_MAX_BODY_LEN = 300
_MAX_DATA_STR_LEN = 500


# --- Settings helpers ------------------------------------------------------
def normalize_settings(settings: Any) -> Dict[str, Any]:
    """Coerces a notifications settings section (dict / Pydantic / JSON) to dict."""
    if settings is None:
        return {}
    if isinstance(settings, dict):
        return settings
    if hasattr(settings, "model_dump"):
        try:
            return settings.model_dump(mode="json", by_alias=True)  # type: ignore[no-any-return]
        except TypeError:
            return settings.model_dump(by_alias=True)  # type: ignore[no-any-return]
    if hasattr(settings, "dict"):
        try:
            return settings.dict()  # type: ignore[no-any-return]
        except Exception:
            return {}
    if isinstance(settings, str):
        try:
            parsed = json.loads(settings)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def is_allowed(event_or_type: str, settings: Any) -> bool:
    """True unless the matching user toggle is explicitly False.

    Unknown events (no toggle mapping) and missing settings default to allowed,
    mirroring the Telegram notifier's backward-compatible behaviour.
    """
    key = EVENT_TO_SETTING_KEY.get(str(event_or_type or "").upper(), "")
    if not key:
        key = EVENT_TO_SETTING_KEY.get(str(event_or_type or ""), "")
    if not key:
        return True
    values = normalize_settings(settings)
    return values.get(key) is not False


# --- Plain-text formatting helpers (no Markdown) ---------------------------
def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _fmt_price(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    text = f"{number:.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _fmt_qty(value: Any) -> str:
    return _fmt_price(value)


def _fmt_money(value: Any, quote: str = "USDT") -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.2f} {quote}"


def _fmt_pct(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.2f}%"


def _fmt_duration(seconds: Any) -> str:
    try:
        total = int(float(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "n/a"
    if total < 0:
        return "n/a"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _clip(text: Any, limit: int = _MAX_BODY_LEN) -> str:
    text = "" if text is None else str(text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _direction_name(direction: Any) -> str:
    if direction is None:
        return ""
    name = getattr(direction, "name", direction)
    return str(name or "").upper()


def _display_side(direction: Any, market_type: Any = None) -> str:
    side = _direction_name(direction)
    if str(market_type or "").strip().lower() == "spot":
        if side == "LONG":
            return "BUY"
        if side == "SHORT":
            return "SELL"
    return side


def _scalar_data(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keeps only JSON-scalar values so payloads stay small and serializable."""
    clean: Dict[str, Any] = {}
    for key, value in (data or {}).items():
        if value is None or isinstance(value, (bool, int, float, str)):
            text = str(value)
            clean[str(key)] = (
                text
                if len(text) <= _MAX_DATA_STR_LEN
                else text[:_MAX_DATA_STR_LEN] + "…"
            )
    return clean


def channel_for(user_id: Any) -> str:
    return NOTIFICATIONS_CHANNEL_TEMPLATE.format(user_id=user_id)


def build_payload(
    *,
    ui_type: str,
    severity: str,
    title: str,
    body: str,
    user_id: Any,
    api_key_id: Any = None,
    symbol: Any = None,
    side: Any = None,
    tag: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assembles the canonical UI notification payload (pure, testable)."""
    return {
        "id": uuid.uuid4().hex,
        "type": ui_type,
        "severity": severity,
        "title": _clip(title, 140),
        "body": _clip(body, _MAX_BODY_LEN),
        "symbol": str(symbol).upper() if symbol else None,
        "side": str(side or "") or None,
        "ts_ms": int(time.time() * 1000),
        "user_id": user_id,
        "api_key_id": api_key_id,
        "tag": tag or f"depthsight-{ui_type}-{uuid.uuid4().hex[:8]}",
        "data": _scalar_data(data),
    }


# --- Transport -------------------------------------------------------------
async def publish(redis_client: Any, user_id: Any, payload: Dict[str, Any]) -> bool:
    """Publishes a payload to ``user:{user_id}:notifications``. Never raises."""
    if user_id is None or redis_client is None:
        return False
    try:
        await redis_client.publish(
            channel_for(user_id), json.dumps(payload, default=str)
        )
        return True
    except Exception as exc:
        logger.debug("UI notification publish failed for user %s: %s", user_id, exc)
        return False


async def _clear_expired_push_subscription(user_id: Any) -> bool:
    """Drops a dead (404/410) push subscription so later events stop failing.

    Uses the runtime crud/get_db dependencies (configured by the process
    entrypoint); never raises.
    """
    if user_id is None:
        return False
    try:
        from bot_module.runtime_dependencies import crud, get_db

        async for db in get_db():
            await crud.delete_user_push_subscription(db, user_id=user_id)
            await db.commit()
        logger.info(
            "Removed expired push subscription for user %s; "
            "the client will resubscribe on next launch.",
            user_id,
        )
        return True
    except Exception as exc:
        logger.debug(
            "Failed to clear expired push subscription for user %s: %s",
            user_id,
            exc,
        )
        return False


async def _send_push(
    push_subscription: Any,
    title: str,
    body: str,
    tag: str,
    *,
    user_id: Any = None,
    url: Optional[str] = None,
) -> str:
    """Delivers a Web Push via the configured sender (off the event loop).

    Returns the sender status (sent/expired/failed/...); expired subscriptions
    are removed from the DB so the client resubscribes on next launch.
    Never raises.
    """
    if not push_subscription or not isinstance(push_subscription, dict):
        return "failed"
    try:
        from api.push_sender import DEFAULT_PUSH_URL
        from bot_module.runtime_dependencies import send_push_notification

        status = await asyncio.to_thread(
            send_push_notification,
            subscription_info=push_subscription,
            title=title,
            body=body,
            tag=tag,
            url=url if url is not None else DEFAULT_PUSH_URL,
        )
        if status == "expired":
            await _clear_expired_push_subscription(user_id)
        return status
    except Exception as exc:
        logger.debug("UI notification push failed: %s", exc)
        return "failed"


async def emit_notification(
    redis_client: Any,
    *,
    user_id: Any,
    ui_type: str,
    telegram_event: Optional[str],
    severity: str,
    title: str,
    body: str,
    symbol: Any = None,
    side: Any = None,
    api_key_id: Any = None,
    tag: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    notification_settings: Any = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    """Filters by user toggles, publishes to Redis, optionally Web Push.

    Returns the payload on delivery attempt, None when suppressed. Never raises.
    """
    try:
        gate = telegram_event or ui_type
        if not is_allowed(gate, notification_settings):
            logger.debug("UI notification %s suppressed by user settings.", ui_type)
            return None
        payload = build_payload(
            ui_type=ui_type,
            severity=severity,
            title=title,
            body=body,
            user_id=user_id,
            api_key_id=api_key_id,
            symbol=symbol,
            side=side,
            tag=tag,
            data=data,
        )
        await publish(redis_client, user_id, payload)
        if push_subscription:
            if loop is not None:
                try:
                    loop.create_task(
                        _send_push(
                            push_subscription,
                            payload["title"],
                            payload["body"],
                            payload["tag"],
                            user_id=user_id,
                        ),
                        name=f"UiPush_{ui_type}",
                    )
                except Exception as exc:
                    logger.debug("Failed to schedule UI push: %s", exc)
            else:
                await _send_push(
                    push_subscription,
                    payload["title"],
                    payload["body"],
                    payload["tag"],
                    user_id=user_id,
                )
        return payload
    except Exception as exc:
        logger.debug("UI notification emit failed (%s): %s", ui_type, exc)
        return None


# --- Per-event emit helpers (formatting lives here, not in the controller) --
async def emit_position_opened(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    direction: Any = None,
    entry_price: Any = None,
    quantity: Any = None,
    base_asset: Any = None,
    stop_loss: Any = None,
    take_profit: Any = None,
    strategy: Any = None,
    client_order_id: Any = None,
    market_type: Any = None,
    leverage: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    side = _display_side(direction, market_type)
    emoji = "🚀" if side in {"LONG", "BUY"} else "🪂"
    lev = f" {leverage}x" if leverage not in (None, "") else ""
    market = (
        f" · {market_type}{lev}"
        if market_type
        else (f" · {leverage}x" if leverage not in (None, "") else "")
    )
    title = f"{emoji} {side} {symbol} @ {_fmt_price(entry_price)}"
    body = (
        f"Qty {_fmt_qty(quantity)} {base_asset or ''}".strip()
        + f" · SL {_fmt_price(stop_loss)}"
        + f" · TP {_fmt_price(take_profit) if take_profit not in (None, '') else '—'}"
        + (f" · {strategy}" if strategy else "")
        + market
    )
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=POSITION_OPENED,
        telegram_event="NEW_POSITION",
        severity="info",
        title=title,
        body=body,
        symbol=symbol,
        side=side,
        api_key_id=api_key_id,
        tag=f"position-opened-{client_order_id or uuid.uuid4().hex[:8]}",
        data={
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "strategy": strategy,
            "client_order_id": client_order_id,
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_position_closed(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    direction: Any = None,
    entry_price: Any = None,
    exit_price: Any = None,
    pnl: Any = None,
    quote_asset: Any = "USDT",
    exit_reason: Any = None,
    closed_quantity: Any = None,
    initial_quantity: Any = None,
    base_asset: Any = None,
    duration_seconds: Any = None,
    entry_client_order_id: Any = None,
    exit_order_id: Any = None,
    market_type: Any = None,
    leverage: Any = None,
    strategy: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    side = _display_side(direction, market_type)
    pnl_num = _num(pnl)
    severity = (
        "success"
        if pnl_num is not None and pnl_num > 0
        else ("error" if pnl_num is not None and pnl_num < 0 else "info")
    )
    emoji = "💰" if severity == "success" else ("📉" if severity == "error" else "⚖️")
    quote = str(quote_asset or "USDT")
    pnl_pct: Optional[float] = None
    try:
        entry_n, qty_n = _num(entry_price), _num(initial_quantity)
        if pnl_num is not None and entry_n and qty_n:
            pnl_pct = (pnl_num / (entry_n * qty_n)) * 100
    except Exception:
        pnl_pct = None
    title = (
        f"{emoji} Closed {side} {symbol} {_fmt_money(pnl, quote)} ({_fmt_pct(pnl_pct)})"
    )
    body = (
        f"{_fmt_price(entry_price)} → {_fmt_price(exit_price)}"
        + (f" · {exit_reason}" if exit_reason else "")
        + f" · {_fmt_duration(duration_seconds)}"
        + (f" · {strategy}" if strategy else "")
    )
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=POSITION_CLOSED,
        telegram_event="POSITION_CLOSED",
        severity=severity,
        title=title,
        body=body,
        symbol=symbol,
        side=side,
        api_key_id=api_key_id,
        tag=f"position-closed-{entry_client_order_id or uuid.uuid4().hex[:8]}",
        data={
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "quote_asset": quote,
            "exit_reason": exit_reason,
            "closed_quantity": closed_quantity,
            "initial_quantity": initial_quantity,
            "strategy": strategy,
            "market_type": market_type,
            "leverage": leverage,
            "entry_client_order_id": entry_client_order_id,
            "exit_order_id": exit_order_id,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_partial_tp(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    tp_index: Any = 0,
    fill_price: Any = None,
    closed_quantity: Any = None,
    fraction_of_initial: Any = 0.0,
    base_asset: Any = None,
    remaining_quantity: Any = None,
    entry_client_order_id: Any = None,
    tp_order_id: Any = None,
    market_type: Any = None,
    api_key_id: Any = None,
    strategy: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    try:
        tp_no = int(tp_index) + 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        tp_no = tp_index
    try:
        frac_pct = float(fraction_of_initial) * 100  # type: ignore[arg-type]
    except (TypeError, ValueError):
        frac_pct = fraction_of_initial
    title = f"🎯 TP{tp_no} {symbol} @ {_fmt_price(fill_price)}"
    body = (
        f"Closed {_fmt_qty(closed_quantity)} {base_asset or ''}".strip()
        + f" ({frac_pct:.0f}%)"
        if isinstance(frac_pct, float)
        else f" ({frac_pct})" + f" · left {_fmt_qty(remaining_quantity)}"
    )
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=PARTIAL_TP,
        telegram_event="PARTIAL_TP_FILLED",
        severity="success",
        title=title,
        body=body,
        symbol=symbol,
        api_key_id=api_key_id,
        tag=f"partial-tp-{entry_client_order_id or ''}-{tp_no}",
        data={
            "tp_index": tp_index,
            "fill_price": fill_price,
            "closed_quantity": closed_quantity,
            "fraction_of_initial": fraction_of_initial,
            "remaining_quantity": remaining_quantity,
            "strategy": strategy,
            "entry_client_order_id": entry_client_order_id,
            "tp_order_id": tp_order_id,
            "market_type": market_type,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_scale_in(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    fill_price: Any = None,
    filled_quantity: Any = None,
    new_average_entry: Any = None,
    new_total_quantity: Any = None,
    entry_client_order_id: Any = None,
    direction: Any = None,
    base_asset: Any = None,
    market_type: Any = None,
    leverage: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    side = _display_side(direction, market_type)
    title = f"➕ Scale-in {symbol} @ {_fmt_price(fill_price)}"
    body = (
        f"Added {_fmt_qty(filled_quantity)} {base_asset or ''}".strip()
        + f" · avg {_fmt_price(new_average_entry)}"
        + f" · total {_fmt_qty(new_total_quantity)}"
    )
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=SCALE_IN,
        telegram_event="SCALE_IN_FILLED",
        severity="info",
        title=title,
        body=body,
        symbol=symbol,
        side=side or None,
        api_key_id=api_key_id,
        tag=f"scale-in-{entry_client_order_id or ''}-{int(time.time() * 1000)}",
        data={
            "fill_price": fill_price,
            "filled_quantity": filled_quantity,
            "new_average_entry": new_average_entry,
            "new_total_quantity": new_total_quantity,
            "entry_client_order_id": entry_client_order_id,
            "direction": _direction_name(direction),
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_sl_moved(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    new_sl_price: Any = None,
    entry_price: Any = None,
    entry_client_order_id: Any = None,
    reason: Any = None,
    market_type: Any = None,
    api_key_id: Any = None,
    strategy: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    title = f"🛡️ SL → breakeven {symbol} @ {_fmt_price(new_sl_price)}"
    body = str(reason) if reason else f"Entry {_fmt_price(entry_price)}"
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=SL_MOVED,
        telegram_event="SL_MOVED_TO_BE",
        severity="info",
        title=title,
        body=body,
        symbol=symbol,
        api_key_id=api_key_id,
        tag=f"sl-moved-{entry_client_order_id or uuid.uuid4().hex[:8]}",
        data={
            "new_sl_price": new_sl_price,
            "entry_price": entry_price,
            "reason": reason,
            "strategy": strategy,
            "entry_client_order_id": entry_client_order_id,
            "market_type": market_type,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_risk_alert(
    redis_client: Any,
    *,
    user_id: Any,
    reason: str,
    alert_type: Any = "ALERT",
    current_balance: Any = None,
    daily_pnl: Any = None,
    quote_asset: Any = "USDT",
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    halted = str(alert_type or "").upper() == "TRADE_DISABLED"
    severity = "error" if halted else "warning"
    title = "🛑 Trading halted" if halted else "⚠️ Risk alert"
    quote = str(quote_asset or "USDT")
    body = str(reason or "Not specified")
    extras = []
    if current_balance is not None:
        extras.append(f"Balance {_fmt_money(current_balance, quote)}".replace("+", ""))
    if daily_pnl is not None:
        extras.append(f"Daily PnL {_fmt_money(daily_pnl, quote)}")
    if extras:
        body += " · " + " · ".join(extras)
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=RISK_ALERT,
        telegram_event="RISK_MANAGER_ALERT",
        severity=severity,
        title=title,
        body=body,
        api_key_id=api_key_id,
        tag=f"risk-{int(time.time())}",
        data={
            "reason": reason,
            "alert_type": alert_type,
            "current_balance": current_balance,
            "daily_pnl": daily_pnl,
            "quote_asset": quote,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_order_error(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    order_type: Any = "UNKNOWN",
    client_order_id: Any = None,
    error_message: Any = None,
    market_type: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    title = f"❌ Order error {symbol} {order_type}"
    body = _clip(error_message or "No details", _MAX_BODY_LEN)
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=ORDER_ERROR,
        telegram_event="ORDER_EXECUTION_ERROR",
        severity="error",
        title=title,
        body=body,
        symbol=symbol,
        api_key_id=api_key_id,
        tag=f"order-error-{client_order_id or uuid.uuid4().hex[:8]}",
        data={
            "order_type": order_type,
            "client_order_id": client_order_id,
            "error_message": error_message,
            "market_type": market_type,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_blacklist(
    redis_client: Any,
    *,
    user_id: Any,
    symbol: str,
    reason: Any = None,
    until: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    title = f"🚫 {symbol} blocked"
    body = str(reason or "Not specified")
    if until:
        body += f" · until {until}"
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=BLACKLIST,
        telegram_event="BLACKLIST_ALERT",
        severity="warning",
        title=title,
        body=body,
        symbol=symbol,
        api_key_id=api_key_id,
        tag=f"blacklist-{symbol}-{int(time.time())}",
        data={"reason": reason, "until": until, "api_key_name": api_key_name},
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_bot_error(
    redis_client: Any,
    *,
    user_id: Any,
    error_description: str,
    module_function: Any = None,
    action_taken: Any = None,
    api_key_id: Any = None,
    api_key_name: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    title = "🆘 Bot error"
    prefix = f"{module_function}: " if module_function else ""
    body = prefix + _clip(error_description, _MAX_BODY_LEN - len(prefix))
    if action_taken:
        body = _clip(body + f" · Action: {action_taken}", _MAX_BODY_LEN)
    return await emit_notification(
        redis_client,
        user_id=user_id,
        ui_type=BOT_ERROR,
        telegram_event="BOT_ERROR",
        severity="error",
        title=title,
        body=body,
        api_key_id=api_key_id,
        tag=f"bot-error-{int(time.time())}",
        data={
            "error_description": error_description,
            "module_function": module_function,
            "action_taken": action_taken,
            "api_key_name": api_key_name,
        },
        notification_settings=notification_settings,
        loop=loop,
        push_subscription=push_subscription,
    )


async def emit_hft(
    redis_client: Any,
    *,
    user_id: Any,
    subtype: str,
    event_data: Optional[Dict[str, Any]] = None,
    api_key_id: Any = None,
    notification_settings: Any = None,
    loop: Any = None,
    push_subscription: Any = None,
) -> Optional[Dict[str, Any]]:
    """Mirrors HFT engine events (bot_started/stopped/signal/trade/error)."""
    data = dict(event_data or {})
    bot_id = data.get("bot_id", "")
    if subtype == "bot_started":
        return await emit_notification(
            redis_client,
            user_id=user_id,
            ui_type=HFT_INFO,
            telegram_event=None,
            severity="info",
            title="🚀 HFT engine started",
            body=f"Bot {bot_id or 'n/a'}",
            api_key_id=api_key_id,
            tag=f"hft-started-{bot_id}-{int(time.time())}",
            data={"bot_id": bot_id},
            notification_settings=notification_settings,
            loop=loop,
            push_subscription=push_subscription,
        )
    if subtype == "bot_stopped":
        return await emit_notification(
            redis_client,
            user_id=user_id,
            ui_type=HFT_INFO,
            telegram_event=None,
            severity="warning",
            title="🛑 HFT engine stopped",
            body=f"Bot {bot_id or 'n/a'}",
            api_key_id=api_key_id,
            tag=f"hft-stopped-{bot_id}-{int(time.time())}",
            data={"bot_id": bot_id},
            notification_settings=notification_settings,
            loop=loop,
            push_subscription=push_subscription,
        )
    if subtype == "signal":
        symbol, side = data.get("symbol"), data.get("side")
        prob = _num(data.get("prob"))
        title = f"⚡ HFT signal {symbol or ''} {side or ''}".strip()
        body = (
            f"Price {_fmt_price(data.get('price'))}"
            + (f" · prob {prob:.2f}" if prob is not None else "")
            + (
                f" · spread {data.get('spread_bps')} bps"
                if data.get("spread_bps") not in (None, "")
                else ""
            )
        )
        return await emit_notification(
            redis_client,
            user_id=user_id,
            ui_type=HFT_SIGNAL,
            telegram_event=HFT_SIGNAL,
            severity="info",
            title=title,
            body=body,
            symbol=symbol,
            side=side,
            api_key_id=api_key_id,
            tag=f"hft-signal-{symbol}-{int(time.time() * 1000)}",
            data=data,
            notification_settings=notification_settings,
            loop=loop,
            push_subscription=push_subscription,
        )
    if subtype in {"trade", "position_closed"}:
        symbol, side = data.get("symbol"), data.get("side")
        pnl_raw = data.get("realized_pnl", data.get("pnl"))
        pnl_num = _num(pnl_raw)
        if pnl_raw is None:
            severity, emoji, headline = "info", "💸", "HFT trade executed"
        else:
            severity = "success" if pnl_num is not None and pnl_num > 0 else "error"
            emoji = "💰" if severity == "success" else "📉"
            headline = "HFT trade closed"
        quote = str(data.get("quote_asset") or "USDT")
        title = f"{emoji} {headline} {symbol or ''}".strip()
        body = (
            f"{side or ''} {data.get('qty', '')} @ {_fmt_price(data.get('price'))}".strip()
            + (f" · PnL {_fmt_money(pnl_raw, quote)}" if pnl_raw is not None else "")
            + (f" · {data.get('reason')}" if data.get("reason") else "")
        )
        return await emit_notification(
            redis_client,
            user_id=user_id,
            ui_type=HFT_CLOSED if pnl_raw is not None else HFT_TRADE,
            telegram_event=HFT_CLOSED if pnl_raw is not None else HFT_TRADE,
            severity=severity,
            title=title,
            body=body,
            symbol=symbol,
            side=side,
            api_key_id=api_key_id,
            tag=f"hft-trade-{symbol}-{int(time.time() * 1000)}",
            data=data,
            notification_settings=notification_settings,
            loop=loop,
            push_subscription=push_subscription,
        )
    if subtype == "error":
        return await emit_notification(
            redis_client,
            user_id=user_id,
            ui_type=BOT_ERROR,
            telegram_event=BOT_ERROR,
            severity="error",
            title="⚠️ HFT engine error",
            body=_clip(data.get("message") or "Unknown error"),
            api_key_id=api_key_id,
            tag=f"hft-error-{int(time.time())}",
            data=data,
            notification_settings=notification_settings,
            loop=loop,
            push_subscription=push_subscription,
        )
    logger.debug("Unknown HFT subtype '%s', UI mirror skipped.", subtype)
    return None


# --- Transparent proxy over TelegramNotifier --------------------------------
class UiMirroringNotifier:
    """Forwards every call to the wrapped TelegramNotifier + mirrors to UI.

    Only this proxy is constructed (via :func:`wrap_telegram_notifier`), so all
    existing controller / risk-manager call sites are mirrored without edits.
    The mirror is always scheduled as a separate task and never delays or
    breaks the Telegram delivery.
    """

    def __init__(
        self,
        inner: Any,
        *,
        get_user_id: Callable[[], Any],
        get_api_key_id: Optional[Callable[[], Any]] = None,
        get_api_key_name: Optional[Callable[[], Any]] = None,
        get_redis: Optional[Callable[[], Any]] = None,
        get_loop: Optional[Callable[[], Any]] = None,
        get_settings: Optional[Callable[[], Any]] = None,
        resolve_push_subscription: Optional[Callable[[], Awaitable[Any]]] = None,
    ):
        self._inner = inner
        self._get_user_id = get_user_id
        self._get_api_key_id = get_api_key_id or (lambda: None)
        self._get_api_key_name = get_api_key_name or (lambda: None)
        self._get_redis = get_redis or (lambda: None)
        self._get_loop = get_loop or (lambda: None)
        self._get_settings = get_settings or (lambda: {})
        self._resolve_push = resolve_push_subscription

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"UiMirroringNotifier({self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        # start/stop/send_test_message and any future methods: plain forwarding.
        return getattr(self._inner, name)

    # -- internals ---------------------------------------------------------
    def _mirror(self, coro_factory: Callable[[], Awaitable[Any]], event: str) -> None:
        try:
            loop = self._get_loop()
            if loop is None:
                return
            loop.create_task(self._run_mirror(coro_factory), name=f"UiMirror_{event}")
        except Exception as exc:
            logger.debug("Failed to schedule UI mirror for %s: %s", event, exc)

    async def _run_mirror(self, coro_factory: Callable[[], Awaitable[Any]]) -> None:
        try:
            await coro_factory()
        except Exception as exc:
            logger.debug("UI mirror failed: %s", exc)

    def _ctx(self) -> Dict[str, Any]:
        try:
            user_id = self._get_user_id()
        except Exception:
            user_id = None
        try:
            api_key_id = self._get_api_key_id()
        except Exception:
            api_key_id = None
        try:
            api_key_name = self._get_api_key_name()
        except Exception:
            api_key_name = None
        try:
            redis_client = self._get_redis()
        except Exception:
            redis_client = None
        try:
            loop = self._get_loop()
        except Exception:
            loop = None
        try:
            settings = self._get_settings()
        except Exception:
            settings = {}
        return {
            "user_id": user_id,
            "api_key_id": api_key_id,
            "api_key_name": api_key_name,
            "redis_client": redis_client,
            "loop": loop,
            "settings": settings,
        }

    async def _push_subscription(self) -> Any:
        if self._resolve_push is None:
            return None
        try:
            sub = await self._resolve_push()
            return sub if isinstance(sub, dict) else None
        except Exception as exc:
            logger.debug("Push subscription resolve failed: %s", exc)
            return None

    def _with_settings(
        self, method: str, args: tuple, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Injects the fresh user toggles into the forwarded Telegram call.

        Call sites never pass ``notification_settings`` (verified: zero usages),
        so without this the frontend toggles would only gate the UI mirror while
        Telegram obeyed global switches. Injection happens only when user
        settings are actually loaded (non-empty dict); otherwise the call is
        forwarded untouched and Telegram keeps its legacy global behavior.
        """
        try:
            if "notification_settings" in _bind(method, args, kwargs):
                return kwargs
            settings = self._get_settings()
            if isinstance(settings, dict) and settings:
                return {**kwargs, "notification_settings": settings}
        except Exception as exc:
            logger.debug("Settings injection failed for %s: %s", method, exc)
        return kwargs

    # -- mirrored API (signatures match TelegramNotifier; **extra forwards) --
    async def new_position(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("new_position", args, kwargs)
        result = await _maybe_await(self._inner.new_position(*args, **kwargs))
        bound = _bind("new_position", args, kwargs)
        self._mirror(lambda: self._mirror_new_position(bound), "NEW_POSITION")
        return result

    async def _mirror_new_position(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_position_opened(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "direction",
                    "entry_price",
                    "quantity",
                    "base_asset",
                    "stop_loss",
                    "take_profit",
                    "strategy",
                    "client_order_id",
                    "market_type",
                    "leverage",
                ),
            ),
        )

    async def position_closed(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("position_closed", args, kwargs)
        result = await _maybe_await(self._inner.position_closed(*args, **kwargs))
        bound = _bind("position_closed", args, kwargs)
        self._mirror(lambda: self._mirror_position_closed(bound), "POSITION_CLOSED")
        return result

    async def _mirror_position_closed(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_position_closed(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "direction",
                    "entry_price",
                    "exit_price",
                    "pnl",
                    "quote_asset",
                    "exit_reason",
                    "closed_quantity",
                    "initial_quantity",
                    "base_asset",
                    "duration_seconds",
                    "entry_client_order_id",
                    "exit_order_id",
                    "market_type",
                    "leverage",
                ),
            ),
        )

    async def partial_tp_filled(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("partial_tp_filled", args, kwargs)
        result = await _maybe_await(self._inner.partial_tp_filled(*args, **kwargs))
        bound = _bind("partial_tp_filled", args, kwargs)
        self._mirror(lambda: self._mirror_partial_tp(bound), "PARTIAL_TP")
        return result

    async def _mirror_partial_tp(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_partial_tp(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "tp_index",
                    "fill_price",
                    "closed_quantity",
                    "fraction_of_initial",
                    "base_asset",
                    "remaining_quantity",
                    "entry_client_order_id",
                    "tp_order_id",
                    "market_type",
                ),
            ),
        )

    async def scale_in_filled(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("scale_in_filled", args, kwargs)
        result = await _maybe_await(self._inner.scale_in_filled(*args, **kwargs))
        bound = _bind("scale_in_filled", args, kwargs)
        self._mirror(lambda: self._mirror_scale_in(bound), "SCALE_IN_FILLED")
        return result

    async def _mirror_scale_in(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_scale_in(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "fill_price",
                    "filled_quantity",
                    "new_average_entry",
                    "new_total_quantity",
                    "entry_client_order_id",
                    "direction",
                    "base_asset",
                    "market_type",
                    "leverage",
                ),
            ),
        )

    async def sl_moved_to_be(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("sl_moved_to_be", args, kwargs)
        result = await _maybe_await(self._inner.sl_moved_to_be(*args, **kwargs))
        bound = _bind("sl_moved_to_be", args, kwargs)
        self._mirror(lambda: self._mirror_sl_moved(bound), "SL_MOVED_TO_BE")
        return result

    async def _mirror_sl_moved(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_sl_moved(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "new_sl_price",
                    "entry_price",
                    "entry_client_order_id",
                    "reason",
                    "market_type",
                ),
            ),
        )

    async def risk_manager_alert(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("risk_manager_alert", args, kwargs)
        result = await _maybe_await(self._inner.risk_manager_alert(*args, **kwargs))
        bound = _bind("risk_manager_alert", args, kwargs)
        self._mirror(lambda: self._mirror_risk(bound), "RISK_ALERT")
        return result

    async def _mirror_risk(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_risk_alert(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                ("reason", "alert_type", "current_balance", "daily_pnl", "quote_asset"),
            ),
        )

    async def order_execution_error(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("order_execution_error", args, kwargs)
        result = await _maybe_await(self._inner.order_execution_error(*args, **kwargs))
        bound = _bind("order_execution_error", args, kwargs)
        self._mirror(lambda: self._mirror_order_error(bound), "ORDER_ERROR")
        return result

    async def _mirror_order_error(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_order_error(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(
                kwargs,
                (
                    "symbol",
                    "order_type",
                    "client_order_id",
                    "error_message",
                    "market_type",
                ),
            ),
        )

    async def blacklist_alert(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("blacklist_alert", args, kwargs)
        result = await _maybe_await(self._inner.blacklist_alert(*args, **kwargs))
        bound = _bind("blacklist_alert", args, kwargs)
        self._mirror(lambda: self._mirror_blacklist(bound), "BLACKLIST")
        return result

    async def _mirror_blacklist(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_blacklist(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(kwargs, ("symbol", "reason", "until")),
        )

    async def bot_error(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = self._with_settings("bot_error", args, kwargs)
        result = await _maybe_await(self._inner.bot_error(*args, **kwargs))
        bound = _bind("bot_error", args, kwargs)
        self._mirror(lambda: self._mirror_bot_error(bound), "BOT_ERROR")
        return result

    async def _mirror_bot_error(self, kwargs: Dict[str, Any]) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_bot_error(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            api_key_id=ctx["api_key_id"],
            api_key_name=kwargs.get("api_key_name", ctx["api_key_name"]),
            notification_settings=kwargs.get("notification_settings", ctx["settings"]),
            loop=ctx["loop"],
            push_subscription=push,
            **_pick(kwargs, ("error_description", "module_function", "action_taken")),
        )

    async def hft_event(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._inner.hft_event(*args, **kwargs)
        subtype = kwargs.get("subtype", args[0] if args else None)
        event_data = kwargs.get("event_data", args[1] if len(args) > 1 else {})
        self._mirror(lambda: self._mirror_hft(subtype, event_data), "HFT")
        return result

    async def _mirror_hft(self, subtype: Any, event_data: Any) -> None:
        ctx = self._ctx()
        if ctx["user_id"] is None:
            return
        push = await self._push_subscription()
        await emit_hft(
            ctx["redis_client"],
            user_id=ctx["user_id"],
            subtype=str(subtype or ""),
            event_data=event_data if isinstance(event_data, dict) else {},
            api_key_id=ctx["api_key_id"],
            notification_settings=ctx["settings"],
            loop=ctx["loop"],
            push_subscription=push,
        )


def _pick(source: Dict[str, Any], keys: tuple) -> Dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


async def _maybe_await(value: Any) -> Any:
    """Await awaitables, pass through sync results (e.g. MagicMock inners in tests)."""
    if inspect.isawaitable(value):
        return await value
    return value


# TelegramNotifier parameter order per method (mirrors telegram_notifier.py).
# Used to bind positional call-site args for the UI mirror.
_TELEGRAM_PARAM_NAMES: Dict[str, tuple] = {
    "new_position": (
        "symbol",
        "direction",
        "entry_price",
        "quantity",
        "base_asset",
        "stop_loss",
        "take_profit",
        "strategy",
        "client_order_id",
        "signal_details",
        "partial_targets_info",
        "tick_size",
        "chat_id",
        "notification_settings",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "position_closed": (
        "symbol",
        "direction",
        "entry_price",
        "exit_price",
        "pnl",
        "quote_asset",
        "exit_reason",
        "closed_quantity",
        "initial_quantity",
        "base_asset",
        "duration_seconds",
        "entry_client_order_id",
        "exit_order_id",
        "tick_size",
        "chat_id",
        "notification_settings",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "partial_tp_filled": (
        "symbol",
        "tp_index",
        "fill_price",
        "closed_quantity",
        "fraction_of_initial",
        "base_asset",
        "remaining_quantity",
        "entry_client_order_id",
        "tp_order_id",
        "tick_size",
        "chat_id",
        "notification_settings",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "sl_moved_to_be": (
        "symbol",
        "new_sl_price",
        "entry_price",
        "entry_client_order_id",
        "tick_size",
        "chat_id",
        "reason",
        "notification_settings",
        "diagnostic_data",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "scale_in_filled": (
        "symbol",
        "fill_price",
        "filled_quantity",
        "new_average_entry",
        "new_total_quantity",
        "entry_client_order_id",
        "direction",
        "base_asset",
        "chat_id",
        "notification_settings",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "risk_manager_alert": (
        "reason",
        "alert_type",
        "current_balance",
        "daily_pnl",
        "quote_asset",
        "chat_id",
        "notification_settings",
        "api_key_name",
    ),
    "order_execution_error": (
        "symbol",
        "order_type",
        "client_order_id",
        "error_message",
        "chat_id",
        "notification_settings",
        "market_type",
        "leverage",
        "api_key_name",
    ),
    "blacklist_alert": (
        "symbol",
        "reason",
        "until",
        "chat_id",
        "notification_settings",
        "api_key_name",
    ),
    "bot_error": (
        "error_description",
        "module_function",
        "action_taken",
        "exc_info",
        "chat_id",
        "notification_settings",
        "api_key_name",
    ),
}


def _bind(method: str, args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Merges positional + keyword call-site args into one kwargs dict."""
    bound = dict(zip(_TELEGRAM_PARAM_NAMES.get(method, ()), args))
    bound.update(kwargs)
    return bound


def wrap_telegram_notifier(
    inner: Any,
    *,
    get_user_id: Callable[[], Any],
    get_api_key_id: Optional[Callable[[], Any]] = None,
    get_api_key_name: Optional[Callable[[], Any]] = None,
    get_redis: Optional[Callable[[], Any]] = None,
    get_loop: Optional[Callable[[], Any]] = None,
    get_settings: Optional[Callable[[], Any]] = None,
    resolve_push_subscription: Optional[Callable[[], Awaitable[Any]]] = None,
) -> Any:
    """Wraps a TelegramNotifier with the UI mirror. Idempotent, None-safe."""
    if inner is None or isinstance(inner, UiMirroringNotifier):
        return inner
    return UiMirroringNotifier(
        inner,
        get_user_id=get_user_id,
        get_api_key_id=get_api_key_id,
        get_api_key_name=get_api_key_name,
        get_redis=get_redis,
        get_loop=get_loop,
        get_settings=get_settings,
        resolve_push_subscription=resolve_push_subscription,
    )
