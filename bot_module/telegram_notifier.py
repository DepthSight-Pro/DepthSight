# bot_module/telegram_notifier.py
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal
import traceback
import json

from telebot.async_telebot import AsyncTeleBot  # type: ignore
from telebot.apihelper import ApiTelegramException  # type: ignore
import backoff  # type: ignore

from bot_module import config
from bot_module.strategy import SignalDirection  # Assume SignalDirection is here
from api import crud

logger = logging.getLogger("bot_module.telegram_notifier")


# Formatting utilities
def _escape_markdown_v2(text: Any) -> str:
    """Escapes special characters for MarkdownV2."""
    if text is None:
        return ""
    text = str(text)
    escape_chars = r"_*[]()~`>#+-.=|{}!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)


def _format_price(price: Optional[float], tick_size: Optional[float]) -> str:
    if price is None:
        return "N/A"
    if tick_size is None or tick_size <= 0:
        return f"{price:.8f}"  # Fallback to 8 digits
    try:
        price_d = Decimal(str(price))
        tick_d = Decimal(str(tick_size))
        # Determine the number of decimal places from tick_size
        decimals = abs(tick_d.as_tuple().exponent)
        formatted_price = f"{price_d:.{decimals}f}"
        return formatted_price
    except Exception:
        return f"{price:.8f}"


def _format_quantity(quantity: Optional[float], base_asset: Optional[str]) -> str:
    if quantity is None:
        return "N/A"
    # Approximate logic for different precision. Can be improved based on stepSize from exchangeInfo.
    precision = 8
    if base_asset:
        if base_asset in ["BTC", "ETH", "BNB"]:
            precision = 5
        elif quantity < 1:
            precision = 4
        elif quantity < 100:
            precision = 2
        else:
            precision = 0
    return f"{quantity:.{precision}f}"


def _normalize_market_type_for_label(raw_market_type: Optional[Any]) -> str:
    raw = (
        raw_market_type
        if raw_market_type is not None
        else getattr(config, "TRADING_MARKET_TYPE", "")
    )
    market_type = str(raw or "").strip().lower().replace("-", "_")
    if "spot" in market_type:
        return "spot"
    if any(
        token in market_type
        for token in ("future", "futures", "usdtm", "perp", "swap", "linear")
    ):
        return "futures_usdtm"
    return market_type or "futures_usdtm"


def _extract_leverage_for_label(data: Dict[str, Any]) -> Optional[str]:
    leverage = data.get("leverage")
    signal_details = data.get("signal_details")
    if leverage is None and isinstance(signal_details, dict):
        for key in ("leverage", "leverage_x", "leverageX", "leverage_multiplier"):
            if signal_details.get(key) is not None:
                leverage = signal_details.get(key)
                break
    if leverage is None:
        return None
    try:
        leverage_float = float(leverage)
        if leverage_float <= 0:
            return None
        if leverage_float.is_integer():
            return str(int(leverage_float))
        return f"{leverage_float:g}"
    except (TypeError, ValueError):
        leverage_str = str(leverage).strip().lower().removesuffix("x")
        return leverage_str or None


def _format_market_label(data: Dict[str, Any]) -> Tuple[str, str]:
    market_type = _normalize_market_type_for_label(data.get("market_type"))
    if market_type == "spot":
        label = "[SPOT]"
    else:
        leverage = _extract_leverage_for_label(data)
        label = f"[FUTURES {leverage}x]" if leverage else "[FUTURES]"
    return label, _escape_markdown_v2(label)


def _format_market_action(
    data: Dict[str, Any], direction_key: str = "direction"
) -> Tuple[str, str]:
    direction = str(data.get(direction_key, "") or "").upper()
    market_type = _normalize_market_type_for_label(data.get("market_type"))
    if market_type == "spot":
        if direction == "LONG":
            direction = "BUY"
        elif direction == "SHORT":
            direction = "SELL"
    return direction, _escape_markdown_v2(direction)


def _format_pnl_percent(
    pnl: Optional[float],
    entry_price: Optional[float],
    quantity: Optional[float],
    direction: Optional[SignalDirection],
) -> str:
    if (
        pnl is None
        or entry_price is None
        or quantity is None
        or direction is None
        or entry_price == 0
        or quantity == 0
    ):
        return "N/A"
    try:
        # PnL is calculated from the entry cost
        entry_value = entry_price * quantity
        if entry_value == 0:
            return "N/A"
        pnl_percent = (pnl / entry_value) * 100
        sign = "+" if pnl > 0 else ""
        return f"{sign}{pnl_percent:.2f}%"
    except Exception:
        return "N/A"


def _format_price_move_percent(
    entry_price: Optional[float],
    exit_price: Optional[float],
    direction: Optional[SignalDirection],
) -> str:
    if (
        entry_price is None
        or exit_price is None
        or direction is None
        or entry_price == 0
    ):
        return "N/A"
    try:
        move = exit_price - entry_price
        if direction == SignalDirection.SHORT:
            move = -move  # Invert for short so that positive is profit

        move_percent = (move / entry_price) * 100
        sign = "+" if move_percent > 0 else ""
        return f"{sign}{move_percent:.2f}%"
    except Exception:
        return "N/A"


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "N/A"
    try:
        td = timedelta(seconds=int(seconds))
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if not parts and secs >= 0:
            parts.append(f"{secs}s")  # Show seconds if the duration is very short
        return " ".join(parts) if parts else "0s"
    except Exception:
        return "N/A"


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str = "",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        if not bot_token or "YOUR_TELEGRAM_BOT_TOKEN" in bot_token:
            raise ValueError("Telegram Bot Token is not configured.")

        # Note: chat_id can be empty. Users configure their own Chat IDs via the frontend,
        # and the per-user chat_id is passed via the target_chat_id parameter in notification methods.
        # The global chat_id is only a fallback.
        self.bot_token = bot_token
        self.chat_id = chat_id  # May be empty - that's okay for per-user notifications
        self.loop = loop or asyncio.get_event_loop()
        self.bot = AsyncTeleBot(
            self.bot_token, parse_mode="MarkdownV2"
        )  # Using MarkdownV2
        self.queue: asyncio.Queue[Optional[Tuple[str, Dict[str, Any]]]] = asyncio.Queue(
            maxsize=100
        )
        self._processor_task: Optional[asyncio.Task] = None
        self._running = False

        # Message deduplication: do not send identical messages more often than once every N seconds
        self._recent_messages: Dict[str, float] = {}  # hash -> timestamp
        self._dedup_window_sec = 10.0

    async def start(self):
        if self._running:
            logger.warning("TelegramNotifier processor already running.")
            return
        if not config.TELEGRAM_NOTIFICATIONS_ENABLED:
            logger.info(
                "Telegram notifications are globally disabled in config. Notifier will not start."
            )
            return

        logger.info("Starting TelegramNotifier...")
        self._running = True
        self._processor_task = self.loop.create_task(
            self._queue_processor(), name="TelegramQueueProcessor"
        )
        await self._send_startup_message()  # Sending startup message

    async def stop(self):
        if not self._running:
            return
        logger.info("Stopping TelegramNotifier...")
        self._running = False
        await self.queue.put(None)  # Signal to terminate the handler
        if self._processor_task:
            try:
                await asyncio.wait_for(self._processor_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout waiting for TelegramNotifier processor to stop."
                )
                self._processor_task.cancel()
            except Exception as e:
                logger.error(f"Error stopping TelegramNotifier processor: {e}")
        logger.info("TelegramNotifier stopped.")

    async def _send_startup_message(self):
        """Sends a message about the bot startup."""
        timestamp = _escape_markdown_v2(
            datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
        )
        message_parts = [
            "🚀 *Bot started*",
            f"⏰ *Time:* `{timestamp}`",
            f"⚙️ *Market:* `{_escape_markdown_v2(config.TRADING_MARKET_TYPE)}`",
            f"🌍 *Environment:* `{_escape_markdown_v2(config.ACTIVE_TRADING_ENVIRONMENT)}`",
        ]
        message = "\n".join(message_parts)
        await self._add_to_queue("BOT_STARTUP", {"message_text": message})

    @backoff.on_exception(
        backoff.expo,
        ApiTelegramException,
        max_tries=5,
        on_giveup=lambda details: logger.error(
            f"Telegram API send failed after {details['tries']} tries. Error: {details.get('exception')}"
        ),
    )
    async def _send_message_async_with_retries(
        self, text: str, chat_id: Optional[str] = None
    ):
        """Sends a message to Telegram with retries.

        Args:
            text: Message text.
            chat_id: Optional Chat ID for sending. If not specified, self.chat_id is used.
        """
        if not text:
            logger.warning("Attempted to send an empty message to Telegram.")
            return
        target_chat_id = chat_id or self.chat_id
        if not target_chat_id:
            logger.warning("No target chat_id available for Telegram message.")
            return
        try:
            # logger.debug(f"Sending to Telegram chat_id {target_chat_id}: {text[:100]}...")
            await self.bot.send_message(
                target_chat_id,
                text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            # logger.debug(f"Message sent successfully to chat_id {target_chat_id}.")
        except ApiTelegramException as e:
            logger.error(
                f"Telegram API Error for chat_id {target_chat_id}: {e.error_code} - {e.description}"
            )
            if e.error_code == 400 and "can't parse entities" in e.description.lower():
                logger.error(
                    "MarkdownV2 parsing error. Message content (first 500 chars):\n"
                    + text[:500]
                )
                # Attempting to send without Markdown
                await self.bot.send_message(
                    target_chat_id, text, disable_web_page_preview=True
                )
            elif e.error_code == 429:  # Too Many Requests
                retry_after = e.result_json.get("parameters", {}).get("retry_after", 30)
                logger.warning(
                    f"Telegram rate limit hit. Retrying after {retry_after}s."
                )
                await asyncio.sleep(retry_after + 1)  # +1 for buffer
                raise  # Retry after backoff
            else:
                raise  # Other ApiTelegramException errors will be handled by backoff
        except Exception as e:
            logger.error(
                f"Unexpected error sending Telegram message: {e}", exc_info=True
            )
            # Do not raise an error here so that backoff does not trigger on non-API errors

    async def _queue_processor(self):
        logger.info("TelegramNotifier queue processor started.")
        while self._running:
            try:
                item = await self.queue.get()
                if item is None:  # Exit signal
                    self.queue.task_done()
                    break

                event_type, data = item
                logger.debug(
                    f"[RAW_EVENT] Type: {event_type}, Data: {json.dumps(data, default=str)}"
                )
                message_text = data.get("message_text", "")  # If text is already formed

                if not message_text:  # If the text was not formed, format it here
                    formatter_method_name = f"_format_{event_type.lower()}_message"
                    formatter_method = getattr(self, formatter_method_name, None)
                    if formatter_method and callable(formatter_method):
                        message_text = formatter_method(data)
                    else:
                        logger.warning(
                            f"No formatter found for event type: {event_type}. Data: {data}"
                        )
                        # Create a simple default message
                        pretty_data = "\n".join(
                            [
                                f"`{_escape_markdown_v2(k)}`: `{_escape_markdown_v2(v)}`"
                                for k, v in data.items()
                            ]
                        )
                        message_text = f"🔔 *Event: {_escape_markdown_v2(event_type)}*\n{pretty_data}"

                if message_text:
                    target_chat_id = data.get(
                        "_target_chat_id"
                    )  # Get target chat_id from data
                    await self._send_message_async_with_retries(
                        message_text, chat_id=target_chat_id
                    )

                self.queue.task_done()
            except asyncio.CancelledError:
                logger.info("TelegramNotifier queue processor cancelled.")
                break
            except Exception as e:
                logger.error(
                    f"Error in TelegramNotifier queue processor: {e}", exc_info=True
                )
                # Mark the task as completed to avoid blocking the queue on error
                if "item" in locals() and item is not None:
                    self.queue.task_done()
                await asyncio.sleep(1)  # A short pause before the next attempt

        logger.info("TelegramNotifier queue processor stopped.")

    async def _add_to_queue(
        self,
        event_type: str,
        data: Dict[str, Any],
        target_chat_id: Optional[str] = None,
        user_notification_settings: Optional[Dict[str, Any]] = None,
    ):
        """Adds a message to the queue for sending.

        Args:
            event_type: Event type for notification.
            data: Event data.
            target_chat_id: Optional Chat ID for sending. If not specified, self.chat_id will be used.
            user_notification_settings: Optional user notification settings from the DB.
        """
        if not config.TELEGRAM_NOTIFICATIONS_ENABLED:
            return

        # === MESSAGE DEDUPLICATION ===
        # Prevents sending identical messages from multiple controller instances
        import hashlib

        # Create a hash based on the event type and key data (without timestamp)
        dedup_data = {
            k: v for k, v in data.items() if k not in ("timestamp", "_target_chat_id")
        }
        msg_hash = hashlib.md5(
            f"{event_type}:{json.dumps(dedup_data, sort_keys=True, default=str)}".encode()
        ).hexdigest()
        now = time.time()

        if msg_hash in self._recent_messages:
            if now - self._recent_messages[msg_hash] < self._dedup_window_sec:
                logger.debug(
                    f"Skipping duplicate {event_type} message (sent {now - self._recent_messages[msg_hash]:.1f}s ago)"
                )
                return

        self._recent_messages[msg_hash] = now

        # Cleaning up old records (once per minute)
        self._recent_messages = {
            h: t for h, t in self._recent_messages.items() if now - t < 60.0
        }
        # === END OF DEDUPLICATION ===

        if not config.TELEGRAM_NOTIFICATIONS_ENABLED:
            return

        # Mapping of event types to user setting keys
        event_to_setting_key = {
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
        }

        # Check user settings (if provided)
        if user_notification_settings is not None:
            setting_key = event_to_setting_key.get(event_type.upper())
            if setting_key:
                # If the setting is explicitly False - do not send
                user_setting = user_notification_settings.get(setting_key)
                if user_setting is False:
                    logger.debug(
                        f"Telegram notification for {event_type} disabled by user settings (key: {setting_key})."
                    )
                    return
        else:
            # Fallback to global settings from config if user settings are not passed
            notify_toggle_attr = f"TELEGRAM_NOTIFY_{event_type.upper()}"
            if hasattr(config, notify_toggle_attr) and not getattr(
                config, notify_toggle_attr
            ):
                logger.debug(
                    f"Telegram notification for {event_type} is disabled by global config toggle."
                )
                return

        # Add target chat_id to data for queue processor
        if target_chat_id:
            data["_target_chat_id"] = target_chat_id
        else:
            if event_type == "SL_MOVED_TO_BE":
                logger.warning(
                    f"[SL_TO_BE_NOTIFY] _add_to_queue: No target_chat_id provided for {event_type}. "
                    f"Will use global self.chat_id='{self.chat_id[:8] if self.chat_id else 'EMPTY'}...'"
                )

        try:
            await self.queue.put((event_type, data))
            if event_type == "SL_MOVED_TO_BE":
                logger.info(
                    f"[SL_TO_BE_NOTIFY] Message added to queue successfully for {event_type}"
                )
        except asyncio.QueueFull:
            logger.warning(
                f"Telegram notification queue is full. Message for {event_type} discarded."
            )
        except Exception as e:
            logger.error(
                f"Error adding message to Telegram queue for {event_type}: {e}"
            )

    # Formatting methods
    def _format_new_position_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol"))
        market_label, market_label_escaped = _format_market_label(data)
        action_plain, action = _format_market_action(data)
        emoji = (
            "🚀" if action_plain in {"LONG", "BUY"} else "🪂"
        )  # Example, can be improved

        entry_price_raw = data.get("entry_price")
        tick_size = data.get(
            "tick_size", config.DEFAULT_TICK_SIZE
        )  # Need tick_size from pair_info or Position
        entry_price_fmt = _format_price(entry_price_raw, tick_size)

        quantity_raw = data.get("quantity")
        base_asset = _escape_markdown_v2(
            data.get("base_asset", symbol.replace("USDT", "").replace("BUSD", ""))
        )  # Rough definition
        quantity_fmt = _format_quantity(quantity_raw, base_asset)

        sl_price_fmt = _format_price(data.get("stop_loss"), tick_size)
        tp_price_fmt = _format_price(data.get("take_profit"), tick_size)

        strategy = _escape_markdown_v2(data.get("strategy"))
        client_order_id = _escape_markdown_v2(data.get("client_order_id"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        signal_details_short = ""
        raw_signal_details = data.get("signal_details", {})
        if isinstance(raw_signal_details, dict):
            # Example: extract foundation_total_weight if present
            weight = raw_signal_details.get("foundation_total_weight")
            pattern = raw_signal_details.get(
                "pattern_detected"
            ) or raw_signal_details.get("pattern")
            if weight is not None:
                signal_details_short += f"Main weight\\.: `{weight:.1f}%` "
            if pattern and pattern != "None":
                signal_details_short += f"Pattern: `{_escape_markdown_v2(pattern)}`"

        parts = [
            f"{emoji} *New position: {market_label_escaped} {action} {symbol}*",
            f"🏷️ *Market:* `{_escape_markdown_v2(market_label)}`",
            f"📈 *Asset:* `{symbol}`",
            f"🧭 *Action:* `{action}`",
            f"🎯 *Entry price:* `{entry_price_fmt}`",
            f"⚖️ *Volume:* `{quantity_fmt} {base_asset}`",
            f"🛡️ *Stop\\-loss:* `{sl_price_fmt}`",
            f"💰 *Take\\-profit \\(final\\.:\\)* `{tp_price_fmt if tp_price_fmt else 'Not set'}`",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
        ]

        partial_targets_data = data.get(
            "partial_targets"
        )  # Expected List[Dict{'price': float, 'fraction': float, 'quantity': float}]
        if partial_targets_data and isinstance(partial_targets_data, list):
            parts.append("📋 *Partial TP:*")
            for i, pt in enumerate(partial_targets_data):
                pt_price_fmt = _format_price(pt.get("price"), tick_size)
                pt_fraction_pct = pt.get("orig_fraction", pt.get("fraction", 0.0)) * 100
                pt_qty_fmt = _format_quantity(pt.get("quantity"), base_asset)
                parts.append(
                    f"  TP{i + 1}: `{pt_price_fmt}` \\(`{pt_fraction_pct:.0f}%` of `{pt_qty_fmt}`\\)"
                )

        parts.extend(
            [
                f"🧠 *Strategy:* `{strategy}`",
                f"🆔 *Client Order ID:* `{client_order_id}`",
                f"⏰ *Time:* `{timestamp}`",
            ]
        )
        if signal_details_short:
            parts.append(f"📝 *Signal details:* {signal_details_short.strip()}")

        return "\n".join(parts)

    def _format_position_closed_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol"))
        market_label, market_label_escaped = _format_market_label(data)
        _, action = _format_market_action(data)

        pnl_raw = data.get("pnl")
        emoji = "🏁"
        if pnl_raw is not None:
            emoji = "💰" if pnl_raw > 0 else ("📉" if pnl_raw < 0 else "⚖️")

        entry_price_raw = data.get("entry_price")
        exit_price_raw = data.get("exit_price")
        tick_size = data.get("tick_size", config.DEFAULT_TICK_SIZE)
        entry_price_fmt = _format_price(entry_price_raw, tick_size)
        exit_price_fmt = _format_price(exit_price_raw, tick_size)

        quote_asset = _escape_markdown_v2(data.get("quote_asset", "USDT"))
        pnl_fmt = f"{pnl_raw:+.2f}" if pnl_raw is not None else "N/A"

        initial_quantity = data.get("initial_quantity")  # Needed for PnL %
        pnl_percent_fmt = _format_pnl_percent(
            pnl_raw, entry_price_raw, initial_quantity, data.get("direction_enum")
        )

        price_move_percent_fmt = _format_price_move_percent(
            entry_price_raw, exit_price_raw, data.get("direction_enum")
        )

        exit_reason = _escape_markdown_v2(data.get("exit_reason", "N/A"))

        closed_quantity_raw = data.get("closed_quantity", initial_quantity)
        base_asset = _escape_markdown_v2(
            data.get("base_asset", symbol.replace("USDT", "").replace("BUSD", ""))
        )
        closed_qty_fmt = _format_quantity(closed_quantity_raw, base_asset)
        initial_qty_fmt = _format_quantity(initial_quantity, base_asset)

        duration_sec = data.get("duration_seconds")
        duration_fmt = _format_duration(duration_sec)

        entry_client_order_id = _escape_markdown_v2(data.get("entry_client_order_id"))
        exit_order_id = _escape_markdown_v2(data.get("exit_order_id", "N/A"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            f"{emoji} *Position closed: {market_label_escaped} {action} {symbol}*",
            f"🏷️ *Market:* `{_escape_markdown_v2(market_label)}`",
            f"📈 *Asset:* `{symbol}`",
            f"🧭 *Action:* `{action}`",
            f"🔑 *Entry price:* `{entry_price_fmt}`",
            f"🚪 *Exit price:* `{exit_price_fmt}`",
            f"💸 *PnL:* `{pnl_fmt} {quote_asset}` \\(`{pnl_percent_fmt}`\\)",
            f"📊 *Price movement:* `{price_move_percent_fmt}`",
            f"⚙️ *Exit reason:* `{exit_reason}`",
            f"⚖️ *Volume:* `{closed_qty_fmt}` / `{initial_qty_fmt} {base_asset}`",
            f"⏳ *Duration:* `{duration_fmt}`",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
            f"🆔 *Entry Client Order ID:* `{entry_client_order_id}`",
            f"🆔 *Exit Order ID:* `{exit_order_id}`",
            f"⏰ *Closing time:* `{timestamp}`",
        ]
        return "\n".join(parts)

    def _format_partial_tp_filled_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol"))
        tp_index = data.get("tp_index", 0) + 1  # 0-based to 1-based
        market_label, market_label_escaped = _format_market_label(data)

        fill_price_raw = data.get("fill_price")
        tick_size = data.get("tick_size", config.DEFAULT_TICK_SIZE)
        fill_price_fmt = _format_price(fill_price_raw, tick_size)

        closed_quantity_raw = data.get("closed_quantity")
        fraction_raw = data.get("fraction_of_initial", 0.0)
        base_asset = _escape_markdown_v2(
            data.get("base_asset", symbol.replace("USDT", "").replace("BUSD", ""))
        )
        closed_qty_fmt = _format_quantity(closed_quantity_raw, base_asset)

        remaining_quantity_raw = data.get("remaining_quantity")
        remaining_qty_fmt = _format_quantity(remaining_quantity_raw, base_asset)

        entry_client_order_id = _escape_markdown_v2(data.get("entry_client_order_id"))
        tp_order_id = _escape_markdown_v2(data.get("tp_order_id"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            f"🎯 *Partial TP executed: {market_label_escaped} {symbol} \\({tp_index}\\-th TP\\)*",
            f"🏷️ *Market:* `{_escape_markdown_v2(market_label)}`",
            f"📈 *Asset:* `{symbol}`",
            f"🚪 *TP execution price:* `{fill_price_fmt}`",
            f"⚖️ *Closed volume:* `{closed_qty_fmt} {base_asset}` \\(`{fraction_raw * 100:.0f}%` of initial\\)",
            f"📦 *Remaining in position:* `{remaining_qty_fmt} {base_asset}`",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
            f"🆔 *Entry Client Order ID:* `{entry_client_order_id}`",
            f"🆔 *TP Order ID:* `{tp_order_id}`",
            f"⏰ *Time:* `{timestamp}`",
        ]
        return "\n".join(parts)

    def _format_sl_moved_to_be_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol"))
        market_label, market_label_escaped = _format_market_label(data)

        new_sl_price_raw = data.get("new_sl_price")
        entry_price_raw = data.get("entry_price")
        tick_size = data.get("tick_size", config.DEFAULT_TICK_SIZE)
        new_sl_fmt = _format_price(new_sl_price_raw, tick_size)
        entry_fmt = _format_price(entry_price_raw, tick_size)

        entry_client_order_id = _escape_markdown_v2(data.get("entry_client_order_id"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        # Get the reason and diagnostic data
        reason = data.get("reason")
        diagnostic_data = data.get("diagnostic_data", {})

        parts = [
            f"🛡️ *Stop\\-loss moved to BE: {market_label_escaped} {symbol}*",
            f"🏷️ *Market:* `{_escape_markdown_v2(market_label)}`",
            f"📈 *Asset:* `{symbol}`",
            f"🎯 *New SL \\(BE\\):* `{new_sl_fmt}`",
            f"🔑 *Entry price:* `{entry_fmt}`",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
            f"🆔 *Entry Client Order ID:* `{entry_client_order_id}`",
            f"⏰ *Time:* `{timestamp}`",
        ]

        # Add the reason to the message if it exists
        if reason:
            parts.insert(1, f"📝 *Reason:* `{_escape_markdown_v2(reason)}`")

        # Add diagnostics for debugging rare problems
        if diagnostic_data:
            diag_parts = []
            if "initial_sl" in diagnostic_data:
                initial_sl_fmt = _format_price(
                    diagnostic_data.get("initial_sl"), tick_size
                )
                diag_parts.append(f"InitSL: `{initial_sl_fmt}`")
            if "current_rr" in diagnostic_data:
                current_rr = diagnostic_data.get("current_rr")
                diag_parts.append(
                    f"R:R: `{current_rr:.2f}`"
                    if current_rr is not None
                    else "R:R: `N/A`"
                )
            if "pnl_per_unit" in diagnostic_data:
                pnl_pu = diagnostic_data.get("pnl_per_unit")
                diag_parts.append(
                    f"PnL/unit: `{pnl_pu:.6f}`"
                    if pnl_pu is not None
                    else "PnL/unit: `N/A`"
                )
            if "price_for_check" in diagnostic_data:
                pfc_fmt = _format_price(
                    diagnostic_data.get("price_for_check"), tick_size
                )
                diag_parts.append(f"High/Low: `{pfc_fmt}`")
            if "candle_time" in diagnostic_data:
                ct = diagnostic_data.get("candle_time")
                if ct:
                    candle_time_str = (
                        ct.strftime("%H:%M:%S") if hasattr(ct, "strftime") else str(ct)
                    )
                    diag_parts.append(
                        f"Candle \\(open\\): `{_escape_markdown_v2(candle_time_str)}`"
                    )

            if diag_parts:
                parts.append(f"🔬 *Diagnostics: {', '.join(diag_parts)}")

        return "\n".join(parts)

    def _format_risk_manager_alert_message(self, data: Dict[str, Any]) -> str:
        alert_type = _escape_markdown_v2(
            data.get("alert_type", "ALERT")
        )  # ALERT or TRADE_DISABLED
        emoji = "⚠️" if alert_type != "TRADE_DISABLED" else "🛑"
        title_prefix = (
            "Risk\\-manager warning"
            if alert_type != "TRADE_DISABLED"
            else "TRADING HALTED"
        )

        reason = _escape_markdown_v2(data.get("reason", "Not specified"))

        current_balance_raw = data.get("current_balance")
        quote_asset = _escape_markdown_v2(data.get("quote_asset", "USDT"))
        balance_fmt = (
            f"{current_balance_raw:.2f}" if current_balance_raw is not None else "N/A"
        )

        daily_pnl_raw = data.get("daily_pnl")
        pnl_fmt = f"{daily_pnl_raw:+.2f}" if daily_pnl_raw is not None else "N/A"

        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            f"{emoji} *{title_prefix}*",
            f"📝 *Reason:* {reason}",
        ]
        if current_balance_raw is not None:
            parts.append(f"📊 *Current balance:* `{balance_fmt} {quote_asset}`")
        if daily_pnl_raw is not None:
            parts.append(f"📉 *Daily PnL:* `{pnl_fmt} {quote_asset}`")

        api_key_name = data.get("api_key_name")
        if api_key_name:
            parts.append(f"🔑 *API key:* `{_escape_markdown_v2(api_key_name)}`")

        parts.append(f"⏰ *Time:* `{timestamp}`")

        return "\n".join(parts)

    def _format_order_execution_error_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol"))
        order_type = _escape_markdown_v2(
            data.get("order_type", "UNKNOWN")
        )  # ENTRY, SL, TP
        market_label, market_label_escaped = _format_market_label(data)

        client_order_id = _escape_markdown_v2(data.get("client_order_id", "N/A"))
        error_message = _escape_markdown_v2(data.get("error_message", "No details"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            f"❌ *Order error: {market_label_escaped} {symbol} {order_type}*",
            f"🏷️ *Market:* `{_escape_markdown_v2(market_label)}`",
            f"📈 *Asset:* `{symbol}`",
            f"📝 *Order type:* `{order_type}`",
            f"🆔 *Client Order ID:* `{client_order_id}`",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
            f"💬 *Error message:* {error_message}",
            f"⏰ *Time:* `{timestamp}`",
        ]
        return "\n".join(parts)

    def _format_blacklist_alert_message(self, data: Dict[str, Any]) -> str:
        symbol = _escape_markdown_v2(data.get("symbol", "UNKNOWN"))
        reason = _escape_markdown_v2(data.get("reason", "Not specified"))
        until = data.get("until")

        emoji = "🚫"
        title = f"Coin locked: {symbol}"

        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            f"{emoji} *{title}*",
            f"📝 *Reason:* {reason}",
        ]

        if until:
            if isinstance(until, str):
                until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            else:
                until_dt = until
            until_fmt = _escape_markdown_v2(until_dt.strftime("%d.%m.%Y %H:%M:%S UTC"))
            parts.append(f"⏳ *Locked until:* `{until_fmt}`")
        else:
            parts.append("♾️ *Blocked:* `Permanently`")

        parts.append(f"⏰ *Signal time:* `{timestamp}`")

        api_key_name = data.get("api_key_name")
        if api_key_name:
            parts.append(f"🔑 *API key:* `{_escape_markdown_v2(api_key_name)}`")

        return "\n".join(parts)

    def _format_bot_error_message(self, data: Dict[str, Any]) -> str:
        error_description = _escape_markdown_v2(
            data.get("error_description", "Unknown error")
        )
        module_function = _escape_markdown_v2(data.get("module_function", "N/A"))
        action_taken = _escape_markdown_v2(data.get("action_taken", "No information"))
        timestamp = _escape_markdown_v2(
            datetime.fromtimestamp(
                data.get("timestamp", time.time()), timezone.utc
            ).strftime("%d.%m.%Y %H:%M:%S UTC")
        )

        parts = [
            "🆘 *Critical bot error\\!*",
            f"🔑 *API key:* `{_escape_markdown_v2(data.get('api_key_name', 'N/A'))}`",
            f"📝 *Message: {error_description}",
            f"📄 *Module/Function:* `{module_function}`",
            f"⏰ *Time:* `{timestamp}`",
        ]
        if action_taken and action_taken != "N/A":
            parts.append(f"❗ *Action: {action_taken}")

        return "\n".join(parts)

    def _format_hft_event_message(self, data: Dict[str, Any]) -> str:
        subtype = data.get("subtype")
        bot_id = _escape_markdown_v2(data.get("bot_id", "Unknown"))

        parts = []

        if subtype == "bot_started":
            parts.append("🚀 *HFT Engine Started*")
            parts.append(f"🆔 *Bot ID:* `{bot_id}`")

        elif subtype == "bot_stopped":
            parts.append("🛑 *HFT Engine Stopped*")
            parts.append(f"🆔 *Bot ID:* `{bot_id}`")

        elif subtype == "signal":
            symbol = _escape_markdown_v2(data.get("symbol"))
            side = _escape_markdown_v2(data.get("side"))
            price = _escape_markdown_v2(data.get("price"))
            prob = float(data.get("prob", 0))

            spread = data.get("spread_bps", "N/A")
            liquidity = _escape_markdown_v2(data.get("liquidity_status", "N/A"))

            emoji = "⚡"
            parts.append(f"{emoji} *HFT Signal*")
            parts.append(f"📈 *Asset:* `{symbol}`")
            parts.append(f"🧭 *Side:* `{side}`")
            parts.append(f"🎯 *Price:* `{price}`")
            parts.append(f"📊 *Prob:* `{prob:.2f}`")
            parts.append(f"📏 *Spread:* `{spread} bps`")
            parts.append(f"💧 *Liq:* `{liquidity}`")

        elif subtype == "trade":
            symbol = _escape_markdown_v2(data.get("symbol"))
            side = _escape_markdown_v2(data.get("side"))
            price = _escape_markdown_v2(data.get("price"))
            qty = _escape_markdown_v2(data.get("qty"))
            realized_pnl = data.get("realized_pnl")

            if realized_pnl is not None:
                pnl_val = float(realized_pnl)
                emoji = "💰" if pnl_val > 0 else "📉"
                title = "HFT Trade Closed"
            else:
                emoji = "💸"
                title = "HFT Trade Executed"

            parts.append(f"{emoji} *{title}*")
            parts.append(f"📈 *Asset:* `{symbol}`")
            parts.append(f"🧭 *Side:* `{side}`")
            parts.append(f"⚖️ *Qty:* `{qty}` @ `{price}`")

            if realized_pnl is not None:
                parts.append(f"💵 *Realized PnL:* `{realized_pnl}`")

        elif subtype == "position_closed":
            symbol = _escape_markdown_v2(data.get("symbol"))
            side = _escape_markdown_v2(data.get("side"))
            price = _escape_markdown_v2(data.get("price"))
            pnl_val = float(data.get("pnl", 0))
            reason = _escape_markdown_v2(data.get("reason", "N/A"))

            emoji = "💰" if pnl_val > 0 else "📉"

            parts.append(f"{emoji} *HFT Trade Closed*")
            parts.append(f"📈 *Asset:* `{symbol}`")
            parts.append(f"🧭 *Side:* `{side}`")
            parts.append(f"🚪 *Exit Price:* `{price}`")
            parts.append(f"💵 *Realized PnL:* `{pnl_val}`")
            parts.append(f"📝 *Reason:* `{reason}`")
            parts.append(f"🆔 *Bot ID:* `{bot_id}`")

        elif subtype == "error":
            message = _escape_markdown_v2(data.get("message", "Unknown error"))
            parts.append("⚠️ *HFT Engine Error*")
            parts.append(f"📝 *Message:* `{message}`")
            parts.append(f"🆔 *Bot ID:* `{bot_id}`")

        else:
            # Unknown subtype - do not send message, only log
            logger.debug(
                f"HFT event with unknown subtype '{subtype}', skipping Telegram notification."
            )
            return ""  # Empty string = do not send

        # Common timestamp (only if there is content)
        if parts:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            parts.append(f"⏰ *Time:* `{_escape_markdown_v2(timestamp)}`")

        return "\n".join(parts)

    # Public methods for sending notifications
    async def new_position(
        self,
        symbol: str,
        direction: SignalDirection,
        entry_price: float,
        quantity: float,
        base_asset: str,
        stop_loss: float,
        take_profit: Optional[float],
        strategy: str,
        client_order_id: str,
        signal_details: Optional[Dict[str, Any]] = None,
        partial_targets_info: Optional[List[Dict[str, Any]]] = None,
        tick_size: Optional[float] = None,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        leverage: Optional[Any] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about opening a position.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "symbol": symbol,
            "direction": direction.name,
            "entry_price": entry_price,
            "quantity": quantity,
            "base_asset": base_asset,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "strategy": strategy,
            "client_order_id": client_order_id,
            "timestamp": time.time(),
            "signal_details": signal_details or {},
            "partial_targets": partial_targets_info or [],
            "tick_size": tick_size,
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        }
        await self._add_to_queue(
            "NEW_POSITION",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def position_closed(
        self,
        symbol: str,
        direction: SignalDirection,
        entry_price: float,
        exit_price: float,
        pnl: float,
        quote_asset: str,
        exit_reason: str,
        closed_quantity: float,
        initial_quantity: float,
        base_asset: str,
        duration_seconds: float,
        entry_client_order_id: str,
        exit_order_id: Optional[str] = None,
        tick_size: Optional[float] = None,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        leverage: Optional[Any] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about closing a position.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "symbol": symbol,
            "direction": direction.name,
            "direction_enum": direction,  # For _format_pnl_percent
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "quote_asset": quote_asset,
            "exit_reason": exit_reason,
            "closed_quantity": closed_quantity,
            "initial_quantity": initial_quantity,
            "base_asset": base_asset,
            "duration_seconds": duration_seconds,
            "entry_client_order_id": entry_client_order_id,
            "exit_order_id": exit_order_id,
            "timestamp": time.time(),
            "tick_size": tick_size,
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        }
        await self._add_to_queue(
            "POSITION_CLOSED",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def partial_tp_filled(
        self,
        symbol: str,
        tp_index: int,
        fill_price: float,
        closed_quantity: float,
        fraction_of_initial: float,
        base_asset: str,
        remaining_quantity: float,
        entry_client_order_id: str,
        tp_order_id: Optional[str] = None,
        tick_size: Optional[float] = None,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        leverage: Optional[Any] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about a partial take-profit.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "symbol": symbol,
            "tp_index": tp_index,
            "fill_price": fill_price,
            "closed_quantity": closed_quantity,
            "fraction_of_initial": fraction_of_initial,
            "base_asset": base_asset,
            "remaining_quantity": remaining_quantity,
            "entry_client_order_id": entry_client_order_id,
            "tp_order_id": tp_order_id,
            "timestamp": time.time(),
            "tick_size": tick_size,
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        }
        await self._add_to_queue(
            "PARTIAL_TP_FILLED",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def sl_moved_to_be(
        self,
        symbol: str,
        new_sl_price: float,
        entry_price: float,
        entry_client_order_id: str,
        tick_size: Optional[float] = None,
        chat_id: Optional[str] = None,
        reason: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        diagnostic_data: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        leverage: Optional[Any] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about moving stop-loss to break-even.

        Args:
            notification_settings: User notification settings from the DB (optional).
            diagnostic_data: Diagnostic data for debugging (initial_sl, current_rr, pnl_per_unit, candle_time).
        """
        # Logging function call
        logger.info(
            f"[SL_TO_BE_NOTIFY] sl_moved_to_be CALLED | symbol={symbol}, "
            f"new_sl={new_sl_price}, entry={entry_price}, reason={reason}, "
            f"chat_id={'SET' if chat_id else 'EMPTY'}, cid={entry_client_order_id[:8] if entry_client_order_id else 'N/A'}"
        )

        data = {
            "symbol": symbol,
            "new_sl_price": new_sl_price,
            "entry_price": entry_price,
            "entry_client_order_id": entry_client_order_id,
            "timestamp": time.time(),
            "tick_size": tick_size,
            "reason": reason,
            "diagnostic_data": diagnostic_data or {},
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        }
        await self._add_to_queue(
            "SL_MOVED_TO_BE",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def risk_manager_alert(
        self,
        reason: str,
        alert_type: str = "ALERT",
        current_balance: Optional[float] = None,
        daily_pnl: Optional[float] = None,
        quote_asset: Optional[str] = "USDT",
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification from the risk manager.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "reason": reason,
            "alert_type": alert_type,
            "current_balance": current_balance,
            "daily_pnl": daily_pnl,
            "quote_asset": quote_asset,
            "api_key_name": api_key_name,
            "timestamp": time.time(),
        }
        await self._add_to_queue(
            "RISK_MANAGER_ALERT",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def order_execution_error(
        self,
        symbol: str,
        order_type: str,
        client_order_id: Optional[str],
        error_message: str,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        leverage: Optional[Any] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about an order execution error.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "symbol": symbol,
            "order_type": order_type,
            "client_order_id": client_order_id,
            "error_message": error_message,
            "timestamp": time.time(),
            "market_type": market_type,
            "leverage": leverage,
            "api_key_name": api_key_name,
        }
        await self._add_to_queue(
            "ORDER_EXECUTION_ERROR",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def blacklist_alert(
        self,
        symbol: str,
        reason: str,
        until: Optional[Any] = None,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about a coin block.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        data = {
            "symbol": symbol,
            "reason": reason,
            "until": until,
            "api_key_name": api_key_name,
            "timestamp": time.time(),
        }
        await self._add_to_queue(
            "BLACKLIST_ALERT",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def bot_error(
        self,
        error_description: str,
        module_function: Optional[str] = None,
        action_taken: Optional[str] = None,
        exc_info: Optional[Any] = None,
        chat_id: Optional[str] = None,
        notification_settings: Optional[Dict[str, Any]] = None,
        api_key_name: Optional[str] = None,
    ):
        """Sends a notification about a critical bot error.

        Args:
            notification_settings: User notification settings from the DB (optional).
        """
        full_error_desc = error_description
        if exc_info:
            # Get the first few lines of the traceback
            tb_lines = traceback.format_exception(
                type(exc_info), exc_info, exc_info.__traceback__, limit=5
            )
            tb_summary = "\n".join(
                tb_lines[-3:]
            )  # The last 3 lines are usually the most informative
            full_error_desc += (
                f"\n\nTraceback (summary):\n`{_escape_markdown_v2(tb_summary)}`"
            )

        data = {
            "error_description": full_error_desc,  # Use the already formatted one with a traceback
            "module_function": module_function,
            "action_taken": action_taken,
            "api_key_name": api_key_name,
            "timestamp": time.time(),
        }
        await self._add_to_queue(
            "BOT_ERROR",
            data,
            target_chat_id=chat_id,
            user_notification_settings=notification_settings,
        )

    async def hft_event(
        self, subtype: str, event_data: Dict[str, Any], chat_id: Optional[str] = None
    ):
        """Sends a notification about an HFT engine event.

        Args:
            subtype: Event subtype (bot_started, bot_stopped, signal, trade, error).
            event_data: Raw event data from Redis.
            chat_id: Chat ID (if there is a user-specific one).
        """
        # Combine subtype with data for the formatter
        data = event_data.copy()
        data["subtype"] = subtype

        # For HFT events, we currently use a global switch or always send,
        # since HFT notification settings may be separate.
        # For now, consider them critical and send.

        if (
            subtype == "signal" and not config.TELEGRAM_NOTIFY_NEW_POSITION
        ):  # Use the position setting for signals as a proxy
            return

        await self._add_to_queue("HFT_EVENT", data, target_chat_id=chat_id)

    async def send_test_message(self, chat_id: str):
        """Sends a test message to the specified chat ID.

        This method bypasses the global TELEGRAM_NOTIFICATIONS_ENABLED check
        and the message queue, sending the message directly. This allows users
        to test their Chat ID even if global notifications are disabled.
        """
        if not chat_id:
            logger.warning("send_test_message called with empty chat_id.")
            return

        message = "🔔 *Test notification*\n\nThis message confirms that your Chat ID is configured correctly and the bot can send you notifications\\."

        try:
            # Send directly, bypassing the queue and global notification checks
            await self.bot.send_message(
                chat_id, message, parse_mode="MarkdownV2", disable_web_page_preview=True
            )
            logger.info(f"Test notification sent successfully to chat_id: {chat_id}")
        except ApiTelegramException as e:
            logger.error(
                f"Telegram API Error sending test message to chat_id {chat_id}: {e.error_code} - {e.description}"
            )
            if e.error_code == 400 and "can't parse entities" in e.description.lower():
                # Fallback: try sending without markdown
                try:
                    plain_message = "🔔 Test notification\n\nThis message confirms that your Chat ID is configured correctly and the bot can send you notifications."
                    await self.bot.send_message(
                        chat_id, plain_message, disable_web_page_preview=True
                    )
                    logger.info(
                        f"Test notification (plain text fallback) sent successfully to chat_id: {chat_id}"
                    )
                except Exception as e2:
                    logger.error(
                        f"Failed to send plain text fallback test message: {e2}"
                    )
                    raise
            else:
                raise
        except Exception as e:
            logger.error(
                f"Unexpected error sending test message to chat_id {chat_id}: {e}",
                exc_info=True,
            )
            raise

    def setup_handlers(self, get_db_gen, redis_client):
        """
        Registers bot command handlers.
        get_db_gen: function that returns a database session generator.
        redis_client: initialized Redis client.
        """

        @self.bot.message_handler(commands=["start"])
        async def handle_start(message):
            # Command format: /start <token>
            parts = message.text.split()
            if len(parts) < 2:
                # Regular start without token - just welcome
                await self.bot.reply_to(
                    message,
                    "👋 Hello! Use the 'Connect Telegram' button in DepthSight settings for automatic linking.",
                )
                return

            token = parts[1]
            redis_key = f"tg_bind:{token}"

            try:
                user_id_bytes = await redis_client.get(redis_key)
                if not user_id_bytes:
                    await self.bot.reply_to(
                        message,
                        "❌ The link has expired or is invalid. Please get a new link in the settings.",
                    )
                    return

                user_id = int(user_id_bytes)
                chat_id = str(message.chat.id)
                username = message.from_user.username

                # Update DB
                db_gen = get_db_gen()
                async with await anext(db_gen) as db:
                    await crud.update_user_telegram_chat_id(
                        db, user_id=user_id, chat_id=chat_id, username=username
                    )
                    await db.commit()

                # Success
                await self.bot.reply_to(
                    message,
                    "✅ *Done!* DepthSight notifications have been successfully connected to this chat.",
                )
                await redis_client.delete(redis_key)

                logger.info(
                    f"Telegram bound successfully for user {user_id} to chat {chat_id}"
                )

            except Exception as e:
                logger.error(f"Error in Telegram binding handler: {e}", exc_info=True)
                await self.bot.reply_to(
                    message,
                    "⚠️ An error occurred during binding. Please try again later.",
                )

    async def start_polling(self):
        """Starts the bot's infinity polling as a background task."""
        logger.info("Starting Telegram Bot polling...")
        # Since infinity_polling is blocking (even async), we run it in a task
        asyncio.create_task(self.bot.infinity_polling())
