# ruff: noqa: E402
# bot_module/risk_manager.py
import logging
import time
import asyncio
import json
from datetime import timedelta, datetime, time as dt_time, timezone
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from collections import defaultdict, deque
from sqlalchemy.ext.asyncio import AsyncSession

from bot_module import config
from bot_module.strategy import StrategySignal, SignalDirection
from bot_module.exchanges import ExchangeExecutor
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.runtime_dependencies import crud
import redis.asyncio as redis_asyncio

logger = logging.getLogger("bot_module.risk_manager")


@dataclass
class TradeStats:
    start_of_day_balance: float = 0.0
    current_balance: float = 0.0
    today_pnl: float = 0.0
    consecutive_losses: int = 0
    last_trade_time: float = 0.0
    current_trading_day_start_ts: float = 0.0
    last_known_day_str: str = ""


@dataclass
class SymbolStrategyPerformanceStats:
    trade_results_buffer: deque[Tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=config.STRATEGY_SYMBOL_ROLLING_WINDOW_SIZE)
    )
    current_pnl_sum_usd: float = 0.0
    sum_initial_risk_usd_in_window: float = 0.0
    current_wins_in_window: int = 0
    current_trades_in_window: int = 0
    current_consecutive_losses: int = 0
    current_consecutive_wins_for_recovery: int = 0
    current_risk_multiplier_index: int = 0
    last_penalty_timestamp: float = 0.0
    total_trades_for_assessment: int = 0
    total_pnl_usd: float = 0.0


from bot_module.datatypes import BasePosition


def ensure_dict(obj) -> Dict[str, Any]:
    """Utility for guaranteed conversion of an object (Pydantic, JSON, etc.) into a dictionary."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        # For Pydantic v2, use mode='json' to ensure that types like datetime
        # are converted to strings (JSON-serializable).
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            # Fallback if mode='json' is not supported (unlikely in modern Pydantic v2)
            return obj.model_dump()
    if hasattr(obj, "dict"):
        # Pydantic v1 fallback
        return obj.dict()
    if isinstance(obj, str):
        try:
            import json

            return json.loads(obj)
        except Exception:
            return {}
    return {}


class RiskManager:
    def __init__(
        self,
        executor: ExchangeExecutor,
        paper_executor: "PaperTradingExecutor",
        user_id: Optional[int],
        db_session: Optional[AsyncSession],
        user_settings: Dict[str, Any],
        api_key_name: Optional[str] = None,
    ):
        self.executor = executor
        self.paper_executor = paper_executor
        self.user_id = user_id
        self.db_session = db_session
        self.api_key_name = api_key_name
        self.stats = TradeStats()
        self.trade_history: List[Dict[str, Any]] = []

        self.telegram_notifier: Optional[Any] = None
        self.loop_from_controller: Optional[asyncio.AbstractEventLoop] = None
        # Extract telegram chat ID from settings if available
        notif_settings = ensure_dict(user_settings.get("notifications"))
        self.user_telegram_chat_id: Optional[str] = notif_settings.get("telegramChatId")

        # Extract telegram chat ID from settings if available
        notif_settings = ensure_dict(user_settings.get("notifications"))
        self.user_telegram_chat_id: Optional[str] = notif_settings.get("telegramChatId")

        # SETTINGS FOR LIVE TRADING (REAL ACCOUNT)
        rm_settings = ensure_dict(user_settings.get("risk_management"))

        self.live_risk_per_trade: float = (
            float(rm_settings.get("riskPerTradePercent") or 0.0) / 100.0
        )
        self.live_max_stop_distance_pct: float = (
            float(rm_settings.get("maxStopDistancePct") or 5.0) / 100.0
        )

        # SETTINGS FOR PAPER/BACKTEST TRADING
        # Use backtest_risk_management, and if it's missing, fall back to live settings
        paper_rm_settings = ensure_dict(
            user_settings.get("backtest_risk_management") or rm_settings
        )

        self.paper_risk_per_trade: float = (
            float(paper_rm_settings.get("riskPerTradePercent") or 1.0) / 100.0
        )
        self.paper_max_stop_distance_pct: float = (
            float(paper_rm_settings.get("maxStopDistancePct") or 5.0) / 100.0
        )

        # Global limits from user settings with a check for None
        def get_fval(d, k, def_val):
            val = d.get(k)
            return float(val) if val is not None else float(def_val)

        def get_ival(d, k, def_val):
            val = d.get(k)
            return int(val) if val is not None else int(def_val)

        self.max_drawdown_threshold: float = (
            get_fval(rm_settings, "maxDrawdown", config.DEFAULT_MAX_DRAWDOWN_PERCENT)
            / 100.0
        )
        self.daily_max_loss_threshold: float = (
            get_fval(
                rm_settings,
                "dailyMaxLossPercent",
                config.DEFAULT_DAILY_MAX_LOSS_PERCENT,
            )
            / 100.0
        )
        self.risk_per_trade: float = (
            get_fval(
                rm_settings,
                "riskPerTradePercent",
                config.DEFAULT_RISK_PER_TRADE_PERCENT,
            )
            / 100.0
        )
        self.max_consecutive_losses: int = get_ival(
            rm_settings, "maxConsecutiveLosses", config.DEFAULT_MAX_CONSECUTIVE_LOSSES
        )

        # Maximum number of simultaneous trades
        self.max_concurrent_trades: int = get_ival(
            rm_settings,
            "maxConcurrentTrades",
            getattr(config, "DEFAULT_MAX_CONCURRENT_TRADES", 5),
        )

        self.min_balance_threshold: float = (
            config.MIN_BALANCE_THRESHOLD_USD
        )  # Remains global
        # Cache for blacklist notifications to avoid spamming (symbol -> timestamp)
        self.last_blacklist_notification: Dict[str, float] = {}

        self.min_rr_ratio: float = get_fval(
            rm_settings, "minRrRatio", getattr(config, "RISK_MANAGER_MIN_RR_RATIO", 3.0)
        )
        self.max_stop_distance_pct: float = (
            get_fval(
                rm_settings,
                "maxStopDistancePct",
                config.RISK_MANAGER_MAX_STOP_DISTANCE_PCT,
            )
            / 100.0
        )

        # Adaptive risk manager settings from user settings
        self._strategy_symbol_adjustment_enabled: bool = rm_settings.get(
            "strategySymbolAdjustmentEnabled", False
        )
        self._strategy_symbol_window_size: int = get_ival(
            rm_settings, "strategySymbolWindowSize", 20
        )
        self._strategy_symbol_min_trades_assess: int = get_ival(
            rm_settings, "strategySymbolMinTradesForAssessment", 10
        )
        self._strategy_symbol_pnl_thresh_pct: float = (
            get_fval(rm_settings, "strategySymbolPnlThresholdPct", -10.0) / 100.0
        )
        self._strategy_symbol_wr_thresh_pct: float = get_fval(
            rm_settings, "strategySymbolWinRateThresholdPct", 30.0
        )
        self._strategy_symbol_max_consec_loss: int = get_ival(
            rm_settings, "strategySymbolMaxConsecutiveLosses", 5
        )
        self._strategy_symbol_rec_consec_wins: int = get_ival(
            rm_settings, "strategySymbolRecoveryConsecutiveWins", 3
        )
        self._strategy_symbol_rec_pnl_thresh_pct: float = (
            get_fval(rm_settings, "strategySymbolRecoveryPnlThresholdPct", 50.0) / 100.0
        )
        self._strategy_symbol_cooldown_penalty_sec: int = get_ival(
            rm_settings, "strategySymbolCooldownAfterPenaltySeconds", 3600
        )

        # Risk multipliers remain in the global config, not configured by the user
        self._strategy_symbol_risk_multipliers: List[float] = getattr(
            config, "STRATEGY_SYMBOL_RISK_MULTIPLIERS", [0.5, 0.75, 1.0, 1.25, 1.5]
        )
        self._s_s_default_multiplier_value: float = getattr(
            config, "STRATEGY_SYMBOL_DEFAULT_RISK_MULTIPLIER_VALUE", 1.0
        )

        try:
            self._s_s_default_risk_idx = self._strategy_symbol_risk_multipliers.index(
                self._s_s_default_multiplier_value
            )
        except (ValueError, AttributeError):
            logger.error(
                f"Default risk multiplier {self._s_s_default_multiplier_value} issue. Using middle index or 0."
            )
            self._s_s_default_risk_idx = (
                len(self._strategy_symbol_risk_multipliers) // 2
                if self._strategy_symbol_risk_multipliers
                else 0
            )

        self._is_trading_allowed = True
        self._balance_lock = asyncio.Lock()
        self._reset_time_utc = dt_time(0, 1, 0, tzinfo=timezone.utc)

        # defaultdict will use the updated _strategy_symbol_window_size
        self._symbol_strategy_performance: Dict[
            Tuple[str, str], SymbolStrategyPerformanceStats
        ] = defaultdict(
            lambda: SymbolStrategyPerformanceStats(
                trade_results_buffer=deque(maxlen=self._strategy_symbol_window_size),
                current_risk_multiplier_index=self._s_s_default_risk_idx,
            )
        )

        # AUTO-BLACKLIST: Tracking consecutive stops by symbols
        # Store a list of stop timestamps (to support within_period)
        self._symbol_stop_timestamps: Dict[str, List[float]] = {}

        # Caching auto-blacklist rules from settings
        rm_settings = user_settings.get("risk_management", {}) if user_settings else {}
        blacklist_settings = rm_settings.get("blacklist", {}) if rm_settings else {}
        self._auto_blacklist_rules: List[Dict] = (
            blacklist_settings.get("autoRules", []) if blacklist_settings else []
        )
        logger.info(
            f"RiskManager initialized with {len(self._auto_blacklist_rules)} auto-blacklist rules"
        )

        # Redis (no changes)
        try:
            self.redis_client = redis_asyncio.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                username=config.REDIS_USERNAME,
                password=config.REDIS_PASSWORD,
                decode_responses=True,
            )
            self.redis_state_key = config.REDIS_STATE_KEY_PORTFOLIO
            logger.info("RiskManager initialized Redis client for state publishing.")
        except Exception as e:
            logger.error(f"Failed to initialize Redis client in RiskManager: {e}")
            self.redis_client = None

        logger.info(f"RiskManager initialized for user_id: {self.user_id}.")
        if self._strategy_symbol_adjustment_enabled:
            logger.info("Strategy-Symbol dynamic risk adjustment ENABLED.")

    def apply_user_settings(self, user_settings: Dict[str, Any]) -> None:
        """Applies fresh user settings in-place without recreating RiskManager."""
        settings = ensure_dict(user_settings)
        notif_settings = ensure_dict(settings.get("notifications"))
        rm_settings = ensure_dict(settings.get("risk_management"))
        paper_rm_settings = ensure_dict(
            settings.get("backtest_risk_management") or rm_settings
        )

        def _get_any(source: Dict[str, Any], *keys: str, default=None):
            for key in keys:
                if key in source and source.get(key) is not None:
                    return source.get(key)
            return default

        def _get_float(source: Dict[str, Any], *keys: str, default: float) -> float:
            value = _get_any(source, *keys, default=default)
            return float(value) if value is not None else float(default)

        def _get_int(source: Dict[str, Any], *keys: str, default: int) -> int:
            value = _get_any(source, *keys, default=default)
            return int(value) if value is not None else int(default)

        prev_window_size = getattr(self, "_strategy_symbol_window_size", None)

        if "telegramChatId" in notif_settings or "telegram_chat_id" in notif_settings:
            self.user_telegram_chat_id = _get_any(
                notif_settings, "telegramChatId", "telegram_chat_id"
            )

        self.live_risk_per_trade = (
            _get_float(
                rm_settings,
                "riskPerTradePercent",
                "risk_per_trade_percent",
                default=1.0,
            )
            / 100.0
        )
        self.live_max_stop_distance_pct = (
            _get_float(
                rm_settings, "maxStopDistancePct", "max_stop_distance_pct", default=5.0
            )
            / 100.0
        )

        self.paper_risk_per_trade = (
            _get_float(
                paper_rm_settings,
                "riskPerTradePercent",
                "risk_per_trade_percent",
                default=1.0,
            )
            / 100.0
        )
        self.paper_max_stop_distance_pct = (
            _get_float(
                paper_rm_settings,
                "maxStopDistancePct",
                "max_stop_distance_pct",
                default=5.0,
            )
            / 100.0
        )

        self.max_drawdown_threshold = (
            _get_float(
                rm_settings,
                "maxDrawdown",
                "max_drawdown",
                default=config.DEFAULT_MAX_DRAWDOWN_PERCENT,
            )
            / 100.0
        )
        self.daily_max_loss_threshold = (
            _get_float(
                rm_settings,
                "dailyMaxLossPercent",
                "daily_max_loss_percent",
                default=config.DEFAULT_DAILY_MAX_LOSS_PERCENT,
            )
            / 100.0
        )
        self.risk_per_trade = (
            _get_float(
                rm_settings,
                "riskPerTradePercent",
                "risk_per_trade_percent",
                default=config.DEFAULT_RISK_PER_TRADE_PERCENT,
            )
            / 100.0
        )
        self.max_consecutive_losses = _get_int(
            rm_settings,
            "maxConsecutiveLosses",
            "max_consecutive_losses",
            default=config.DEFAULT_MAX_CONSECUTIVE_LOSSES,
        )
        self.max_concurrent_trades = _get_int(
            rm_settings,
            "maxConcurrentTrades",
            "max_concurrent_trades",
            default=getattr(config, "DEFAULT_MAX_CONCURRENT_TRADES", 5),
        )
        self.min_rr_ratio = _get_float(
            rm_settings,
            "minRrRatio",
            "min_rr_ratio",
            default=getattr(config, "RISK_MANAGER_MIN_RR_RATIO", 3.0),
        )
        self.max_stop_distance_pct = (
            _get_float(
                rm_settings,
                "maxStopDistancePct",
                "max_stop_distance_pct",
                default=config.RISK_MANAGER_MAX_STOP_DISTANCE_PCT,
            )
            / 100.0
        )

        self._strategy_symbol_adjustment_enabled = bool(
            _get_any(
                rm_settings,
                "strategySymbolAdjustmentEnabled",
                "strategy_symbol_adjustment_enabled",
                default=False,
            )
        )
        self._strategy_symbol_window_size = _get_int(
            rm_settings,
            "strategySymbolWindowSize",
            "strategy_symbol_window_size",
            default=20,
        )
        self._strategy_symbol_min_trades_assess = _get_int(
            rm_settings,
            "strategySymbolMinTradesForAssessment",
            "strategy_symbol_min_trades_for_assessment",
            default=10,
        )
        self._strategy_symbol_pnl_thresh_pct = (
            _get_float(
                rm_settings,
                "strategySymbolPnlThresholdPct",
                "strategy_symbol_pnl_threshold_pct",
                default=-10.0,
            )
            / 100.0
        )
        self._strategy_symbol_wr_thresh_pct = _get_float(
            rm_settings,
            "strategySymbolWinRateThresholdPct",
            "strategy_symbol_win_rate_threshold_pct",
            default=30.0,
        )
        self._strategy_symbol_max_consec_loss = _get_int(
            rm_settings,
            "strategySymbolMaxConsecutiveLosses",
            "strategy_symbol_max_consecutive_losses",
            default=5,
        )
        self._strategy_symbol_rec_consec_wins = _get_int(
            rm_settings,
            "strategySymbolRecoveryConsecutiveWins",
            "strategy_symbol_recovery_consecutive_wins",
            default=3,
        )
        self._strategy_symbol_rec_pnl_thresh_pct = (
            _get_float(
                rm_settings,
                "strategySymbolRecoveryPnlThresholdPct",
                "strategy_symbol_recovery_pnl_threshold_pct",
                default=50.0,
            )
            / 100.0
        )
        self._strategy_symbol_cooldown_penalty_sec = _get_int(
            rm_settings,
            "strategySymbolCooldownAfterPenaltySeconds",
            "strategy_symbol_cooldown_after_penalty_seconds",
            default=3600,
        )

        blacklist_settings = ensure_dict(_get_any(rm_settings, "blacklist", default={}))
        auto_blacklist_rules = _get_any(
            blacklist_settings, "autoRules", "auto_rules", default=[]
        )
        self._auto_blacklist_rules = (
            list(auto_blacklist_rules) if isinstance(auto_blacklist_rules, list) else []
        )

        if hasattr(self, "_symbol_strategy_performance"):
            default_risk_idx = getattr(self, "_s_s_default_risk_idx", 0)
            self._symbol_strategy_performance.default_factory = lambda: (
                SymbolStrategyPerformanceStats(
                    trade_results_buffer=deque(
                        maxlen=self._strategy_symbol_window_size
                    ),
                    current_risk_multiplier_index=default_risk_idx,
                )
            )
            if (
                prev_window_size
                and prev_window_size != self._strategy_symbol_window_size
            ):
                for stats in self._symbol_strategy_performance.values():
                    resized_buffer = deque(
                        list(stats.trade_results_buffer)[
                            -self._strategy_symbol_window_size :
                        ],
                        maxlen=self._strategy_symbol_window_size,
                    )
                    stats.trade_results_buffer = resized_buffer
                    stats.current_pnl_sum_usd = sum(pnl for pnl, _ in resized_buffer)
                    stats.sum_initial_risk_usd_in_window = sum(
                        risk for _, risk in resized_buffer
                    )
                    stats.current_wins_in_window = sum(
                        1 for pnl, _ in resized_buffer if pnl > 0
                    )
                    stats.current_trades_in_window = len(resized_buffer)

        logger.info(
            "RiskManager settings refreshed for user_id=%s: max_concurrent_trades=%s, risk_per_trade=%.4f",
            self.user_id,
            self.max_concurrent_trades,
            self.risk_per_trade,
        )

    async def initialize(self):
        """Asynchronously loads state from the DB and initializes the balance."""
        logger.info(f"Async initializing RiskManager for user_id: {self.user_id}...")
        # Clear state in memory before loading to ensure a clean start
        self._symbol_strategy_performance.clear()
        await self._load_performance_from_db()
        await self.initialize_balance()
        logger.info(f"Async initialization complete for user_id: {self.user_id}.")

    async def initialize_balance(self):
        logger.info("Initializing balance for RiskManager...")
        success_fetch = await self.update_balance()

        if success_fetch and self.stats.current_balance > 0:
            # The logic for resetting daily statistics remains the same, as it does not depend on the user
            # It is important that we no longer check _state_loaded_successfully, as loading from the DB is now a standard step
            (
                current_trading_day_start_ts_float_actual,
                current_trading_day_str_utc_actual,
            ) = self._get_current_day_start_info()

            logger.info(
                f"Initializing for a new trading day scenario. ActualCurrentDay: {current_trading_day_str_utc_actual}"
            )

            self.stats.start_of_day_balance = self.stats.current_balance
            self.stats.today_pnl = 0.0
            self.stats.consecutive_losses = 0
            self.stats.current_trading_day_start_ts = (
                current_trading_day_start_ts_float_actual
            )
            self.stats.last_known_day_str = current_trading_day_str_utc_actual
            self._is_trading_allowed = True

            logger.info(
                f"Daily stats reset for new day {current_trading_day_str_utc_actual}. Start of day balance: ${self.stats.start_of_day_balance:.2f}."
            )
        else:
            logger.error(
                f"Failed to initialize balance (FetchSuccess={success_fetch}, BalanceFromExecutor={self.stats.current_balance}). Trading may be disabled."
            )
            self._is_trading_allowed = False

        if success_fetch:
            self._check_risk_limits()
        else:
            self._is_trading_allowed = False
            logger.warning(
                "[InitializeBalance] Trading disabled: failed to fetch balance."
            )

    async def update_balance(self) -> bool:
        """Updates the current USDT balance from the executor (thread-safe)."""
        log_prefix = "[RiskManager:UpdateBalance]"
        async with self._balance_lock:
            try:
                balances = (
                    await self.executor.get_account_balance()
                )  # This is GET /account
                if not balances or isinstance(balances, dict) and balances.get("error"):
                    logger.error(
                        f"{log_prefix} Failed to fetch balances from executor: {balances}"
                    )
                    return False  # Failed to get balances

                usdt_balance_data = balances.get("USDT")
                if usdt_balance_data:
                    try:
                        free_bal = float(usdt_balance_data.get("free", 0))
                        locked_bal = float(usdt_balance_data.get("locked", 0))
                        current_total_usdt = free_bal + locked_bal
                    except (ValueError, TypeError) as e:
                        logger.error(
                            f"{log_prefix} Error converting USDT balance data to float: {e}. Data: {usdt_balance_data}"
                        )
                        return False

                    # Check for abnormally low balance if the previous one was significantly higher
                    # Suppose the balance should not drop by more than 90% in one call if it was not close to zero
                    if (
                        self.stats.current_balance > 10
                        and current_total_usdt < self.stats.current_balance * 0.1
                        and current_total_usdt < self.min_balance_threshold / 2
                    ):
                        logger.warning(
                            f"{log_prefix} Detected anomalously low new balance (${current_total_usdt:.2f}) compared to previous (${self.stats.current_balance:.2f}). "
                            f"This might be a temporary API issue. NOT UPDATING BALANCE THIS TIME."
                        )
                        # Retry logic can be added here or the update can simply be skipped
                        return False  # Return False to signal a possible data issue

                    if (
                        abs(current_total_usdt - self.stats.current_balance) > 1e-9
                    ):  # 1e-9 for float comparison
                        logger.info(
                            f"{log_prefix} Balance updated: Previous=${self.stats.current_balance:.2f}, New=${current_total_usdt:.2f} (Free: {free_bal:.2f}, Locked: {locked_bal:.2f})"
                        )
                        self.stats.current_balance = current_total_usdt
                    else:
                        logger.debug(
                            f"{log_prefix} Balance unchanged: ${self.stats.current_balance:.2f}"
                        )
                    return True
                else:
                    logger.warning(
                        f"{log_prefix} USDT balance data not found in account info from executor. Current known balance: ${self.stats.current_balance:.2f}"
                    )
                    # If there is no USDT but there are other assets, this could also be a problem for a USDT bot.
                    # If self.stats.current_balance is already 0 or very small, then this might be normal.
                    return False  # If there is no USDT, consider the update failed for the USDT bot
            except Exception as e:
                logger.error(
                    f"{log_prefix} Unexpected error updating balance: {e}",
                    exc_info=True,
                )
                return False

    def _get_current_day_start_info(self) -> Tuple[float, str]:
        now_utc = datetime.now(timezone.utc)
        current_day_str = now_utc.strftime("%Y-%m-%d")
        reset_time_today_utc = datetime.combine(now_utc.date(), self._reset_time_utc)
        if now_utc < reset_time_today_utc:
            start_of_trading_day_dt = datetime.combine(
                now_utc.date() - timedelta(days=1), self._reset_time_utc
            )
        else:
            start_of_trading_day_dt = reset_time_today_utc
        return start_of_trading_day_dt.timestamp(), current_day_str

    def _check_and_reset_daily_stats(self):
        current_start_ts_float, current_day_str_utc = self._get_current_day_start_info()
        if self.stats.last_known_day_str != current_day_str_utc:
            logger.info(
                f"New trading day detected (UTC): {current_day_str_utc}. Previous day: {self.stats.last_known_day_str}"
            )
            self.stats.start_of_day_balance = self.stats.current_balance
            self.stats.today_pnl = 0.0
            self.stats.consecutive_losses = 0
            self.stats.current_trading_day_start_ts = current_start_ts_float
            self.stats.last_known_day_str = current_day_str_utc
            if not self._is_trading_allowed:
                logger.info(
                    "Global risk limits have been reset. Resuming trading capability for a new day."
                )
            self._is_trading_allowed = True
            logger.info(
                f"Balance at the start of a new day set: ${self.stats.start_of_day_balance:.2f}"
            )
            if self._strategy_symbol_adjustment_enabled:
                logger.info(
                    "Trading day change. Cooldowns for 'strategy-symbol' pairs may be revised."
                )

    async def update_trade_result(
        self, symbol: str, pnl: float, exit_reason: Optional[str] = None
    ):
        self._check_and_reset_daily_stats()
        self.stats.today_pnl += pnl
        self.stats.last_trade_time = time.time()
        if pnl <= 0:
            self.stats.consecutive_losses += 1
        else:
            self.stats.consecutive_losses = 0
        logger.info(
            f"Global PnL Updated: PnL={pnl:.2f}, GlobalTodayPnL={self.stats.today_pnl:.2f}, GlobalConsecLosses={self.stats.consecutive_losses}"
        )
        self._check_risk_limits()

        # AUTO-BLACKLIST: Tracking consecutive stops by symbols
        # Excluding BE (Break-Even) from stop count for blacklist
        is_be = exit_reason is not None and "be" in exit_reason.lower()
        is_stop_loss = (
            exit_reason is not None and "stop" in exit_reason.lower() and not is_be
        )

        if is_stop_loss:
            # Adding stop timestamp
            if symbol not in self._symbol_stop_timestamps:
                self._symbol_stop_timestamps[symbol] = []
            self._symbol_stop_timestamps[symbol].append(time.time())
            logger.debug(
                f"[AutoBlacklist:{symbol}] Stop recorded. Total stops: {len(self._symbol_stop_timestamps[symbol])}"
            )
        elif pnl > 0 or is_be:
            # On a PROFITABLE trade or BE (break-even), clear the stop history
            if symbol in self._symbol_stop_timestamps:
                self._symbol_stop_timestamps[symbol] = []

        # Checking auto-blocking rules
        await self._check_and_apply_auto_blacklist_rules(symbol)

    async def update_symbol_strategy_performance(
        self,
        symbol: str,
        strategy_name: str,
        pnl_usd: float,
        initial_risk_usd_planned: float,
    ):
        if not self._strategy_symbol_adjustment_enabled:
            return

        perf_key = (symbol, strategy_name)
        stats = self._symbol_strategy_performance[perf_key]
        log_prefix = f"[RiskManager:{symbol}:{strategy_name}:Perf]"

        # Update the cumulative PnL. This is done at the very beginning.
        stats.total_pnl_usd += pnl_usd

        # Sliding window logic (remains unchanged)
        if (
            len(stats.trade_results_buffer) == self._strategy_symbol_window_size
            and self._strategy_symbol_window_size > 0
        ):
            old_pnl, old_risk_planned = stats.trade_results_buffer[0]
            stats.current_pnl_sum_usd -= old_pnl
            stats.sum_initial_risk_usd_in_window -= old_risk_planned
        stats.trade_results_buffer.append((pnl_usd, initial_risk_usd_planned))
        stats.current_pnl_sum_usd = sum(p for p, r in stats.trade_results_buffer)
        stats.sum_initial_risk_usd_in_window = sum(
            r for p, r in stats.trade_results_buffer
        )
        stats.current_wins_in_window = sum(
            1 for p, r in stats.trade_results_buffer if p > 0
        )
        stats.current_trades_in_window = len(stats.trade_results_buffer)

        stats.current_consecutive_losses = 0
        stats.current_consecutive_wins_for_recovery = 0
        counting_losses = True
        counting_wins = True
        for pnl_hist, _ in reversed(stats.trade_results_buffer):
            if counting_losses:
                if pnl_hist <= 0:
                    stats.current_consecutive_losses += 1
                else:
                    counting_losses = False
            if counting_wins:
                if pnl_hist > 0:
                    stats.current_consecutive_wins_for_recovery += 1
                else:
                    counting_wins = False
            if not counting_losses and not counting_wins:
                break
        stats.total_trades_for_assessment += 1
        logger.debug(
            f"{log_prefix} Updated. Total PnL: {stats.total_pnl_usd:.2f}, Window PnL: {stats.current_pnl_sum_usd:.2f}, Trades: {stats.current_trades_in_window}"
        )

        # Step 1: Check and adjust risk
        await self._check_and_adjust_risk_for_symbol_strategy(symbol, strategy_name)

        # Step 2: Save the updated state to the DB
        await self._save_performance_to_db(symbol, strategy_name, stats)

    async def _check_and_adjust_risk_for_symbol_strategy(
        self, symbol: str, strategy_name: str
    ):
        perf_key = (symbol, strategy_name)
        stats = self._symbol_strategy_performance[perf_key]
        log_prefix = f"[RiskManager:{symbol}:{strategy_name}:Adjust]"

        if not self._strategy_symbol_risk_multipliers:
            logger.error(
                f"{log_prefix} Risk multipliers list is empty. Cannot adjust risk."
            )
            return

        max_multiplier_idx = len(self._strategy_symbol_risk_multipliers) - 1

        if stats.total_trades_for_assessment < self._strategy_symbol_min_trades_assess:
            logger.debug(
                f"{log_prefix} Not enough total trades ({stats.total_trades_for_assessment}/{self._strategy_symbol_min_trades_assess}) to assess."
            )
            return

        reduction_triggered = False
        # Risk Reduction Logic
        if (
            stats.current_risk_multiplier_index > 0
        ):  # Only reduce if not already at max penalty (index 0)
            reason_for_reduction = []
            if stats.current_trades_in_window >= self._strategy_symbol_window_size:
                pnl_pct_in_window = (
                    (
                        stats.current_pnl_sum_usd
                        / stats.sum_initial_risk_usd_in_window
                        * 100.0
                    )
                    if stats.sum_initial_risk_usd_in_window > 1e-9
                    else 0.0
                )
                win_rate_in_window = (
                    (
                        stats.current_wins_in_window
                        / stats.current_trades_in_window
                        * 100.0
                    )
                    if stats.current_trades_in_window > 0
                    else 0.0
                )
                if pnl_pct_in_window < self._strategy_symbol_pnl_thresh_pct:
                    reason_for_reduction.append(
                        f"PnL {pnl_pct_in_window:.2f}% < {self._strategy_symbol_pnl_thresh_pct:.2f}%"
                    )
                if win_rate_in_window < self._strategy_symbol_wr_thresh_pct:
                    reason_for_reduction.append(
                        f"WR {win_rate_in_window:.2f}% < {self._strategy_symbol_wr_thresh_pct:.2f}%"
                    )
            if (
                stats.current_consecutive_losses
                >= self._strategy_symbol_max_consec_loss
            ):
                reason_for_reduction.append(
                    f"ConsecLoss {stats.current_consecutive_losses} >= {self._strategy_symbol_max_consec_loss}"
                )

            if reason_for_reduction:
                reduction_triggered = True
                stats.current_risk_multiplier_index = max(
                    0, stats.current_risk_multiplier_index - 1
                )  # Decrease index
                stats.last_penalty_timestamp = time.time()
                stats.current_consecutive_wins_for_recovery = 0
                logger.warning(
                    f"{log_prefix} RISK REDUCED. New multiplier index: {stats.current_risk_multiplier_index} "
                    f"(Value: {self._strategy_symbol_risk_multipliers[stats.current_risk_multiplier_index]:.2f}). "
                    f"Reason(s): {'; '.join(reason_for_reduction)}"
                )

        # Risk Improvement/Enhancement Logic
        if (
            not reduction_triggered
            and stats.current_risk_multiplier_index < max_multiplier_idx
        ):  # Only improve if not at max benefit
            cooldown_passed = (
                time.time() - stats.last_penalty_timestamp
            ) >= self._strategy_symbol_cooldown_penalty_sec

            if cooldown_passed:
                reason_for_improvement = []
                if (
                    stats.current_consecutive_wins_for_recovery
                    >= self._strategy_symbol_rec_consec_wins
                ):
                    reason_for_improvement.append(
                        f"ConsecWinsRec {stats.current_consecutive_wins_for_recovery} >= {self._strategy_symbol_rec_consec_wins}"
                    )
                if stats.current_trades_in_window >= self._strategy_symbol_window_size:
                    pnl_pct_in_window_rec = (
                        (
                            stats.current_pnl_sum_usd
                            / stats.sum_initial_risk_usd_in_window
                            * 100.0
                        )
                        if stats.sum_initial_risk_usd_in_window > 1e-9
                        else 0.0
                    )
                    if pnl_pct_in_window_rec > self._strategy_symbol_rec_pnl_thresh_pct:
                        reason_for_improvement.append(
                            f"PnL {pnl_pct_in_window_rec:.2f}% > {self._strategy_symbol_rec_pnl_thresh_pct:.2f}%"
                        )

                if reason_for_improvement:
                    new_index_before_change = stats.current_risk_multiplier_index
                    stats.current_risk_multiplier_index = min(
                        max_multiplier_idx, stats.current_risk_multiplier_index + 1
                    )  # Increase index
                    stats.current_consecutive_wins_for_recovery = 0

                    log_message_action = (
                        "RISK ENHANCED"
                        if self._strategy_symbol_risk_multipliers[
                            stats.current_risk_multiplier_index
                        ]
                        > self._s_s_default_multiplier_value
                        else "RISK RECOVERED"
                    )
                    if (
                        new_index_before_change < self._s_s_default_risk_idx
                        and stats.current_risk_multiplier_index
                        == self._s_s_default_risk_idx
                    ):
                        log_message_action = "RISK RECOVERED TO NORMAL"

                    logger.info(
                        f"{log_prefix} {log_message_action}. New multiplier index: {stats.current_risk_multiplier_index} "
                        f"(Value: {self._strategy_symbol_risk_multipliers[stats.current_risk_multiplier_index]:.2f}). "
                        f"Reason(s): {'; '.join(reason_for_improvement)}"
                    )
            else:
                logger.debug(
                    f"{log_prefix} Improvement check: Cooldown period not yet passed for index {stats.current_risk_multiplier_index}."
                )

    async def is_symbol_trading_allowed(self, symbol: str) -> bool:
        """
        Checks if trading is allowed for the given symbol.
        Includes checking the global flag and the user's blacklist.
        The blacklist is checked "on the fly" from the DB - changes are applied without a restart.
        """
        # 1. Check global flag (drawdown, consecutive losses, etc.)
        if not self._is_trading_allowed:
            logger.debug(f"[Blacklist:{symbol}] Trading globally disabled")
            return False

        # 2. Checking the blacklist (on-the-fly from the DB)
        if self.db_session and crud and self.user_id:
            try:
                # CRITICAL: Reset the SQLAlchemy session cache before the query.
                # Without this, the bot will see a cached version of the config,
                # and blacklist changes via API will not be applied until the bot is restarted.
                self.db_session.expire_all()

                # Get the config from the DB (now the data is guaranteed to be fresh)
                config = await crud.get_config(self.db_session, user_id=self.user_id)
                if config and config.risk_management:
                    rm_settings = ensure_dict(config.risk_management)

                    # Extracting blacklist data
                    blacklist_data = ensure_dict(rm_settings.get("blacklist"))

                    if blacklist_data:
                        coins = blacklist_data.get("coins", [])
                        now = datetime.now(timezone.utc)

                        for coin in coins:
                            coin = ensure_dict(coin)

                            coin_symbol = coin.get("symbol", "").upper()

                            if coin_symbol == symbol.upper():
                                until_val = (
                                    coin.get("until")
                                    if isinstance(coin, dict)
                                    else getattr(coin, "until", None)
                                )

                                # If until is specified, checking if the period has expired
                                if until_val:
                                    try:
                                        if isinstance(until_val, str):
                                            until_dt = datetime.fromisoformat(
                                                until_val.replace("Z", "+00:00")
                                            )
                                        else:
                                            until_dt = until_val

                                        if until_dt > now:
                                            reason = (
                                                coin.get(
                                                    "reason", "No reason specified"
                                                )
                                                if isinstance(coin, dict)
                                                else getattr(
                                                    coin,
                                                    "reason",
                                                    "No reason specified",
                                                )
                                            )
                                            logger.warning(
                                                f"[Blacklist:{symbol}] Symbol is BLACKLISTED until {until_dt.isoformat()}. Reason: {reason}"
                                            )

                                            # Send a notification to Telegram if not sent recently
                                            await self._notify_blacklist(
                                                symbol, reason, until_dt
                                            )

                                            return False
                                        # else: period expired, symbol allowed
                                    except (ValueError, TypeError) as e:
                                        logger.warning(
                                            f"[Blacklist:{symbol}] Failed to parse until date: {until_val}. Treating as permanent. Error: {e}"
                                        )

                                        # Send notification to Telegram for an incorrect date (as a permanent block)
                                        await self._notify_blacklist(
                                            symbol,
                                            "Invalid date format - treated as permanent",
                                            None,
                                        )

                                        return False
                                else:
                                    # until is None = permanent blacklist
                                    reason = (
                                        coin.get("reason", "No reason specified")
                                        if isinstance(coin, dict)
                                        else getattr(
                                            coin, "reason", "No reason specified"
                                        )
                                    )
                                    logger.warning(
                                        f"[Blacklist:{symbol}] Symbol is PERMANENTLY BLACKLISTED. Reason: {reason}"
                                    )

                                    # Sending notification to Telegram
                                    await self._notify_blacklist(symbol, reason, None)

                                    return False
            except Exception as e:
                logger.error(
                    f"[Blacklist:{symbol}] Error checking blacklist: {e}", exc_info=True
                )
                # In case of an error, allow trading so as not to block the bot's operation

        return True

    async def _notify_blacklist(
        self, symbol: str, reason: str, until: Optional[datetime]
    ):
        """Sends a notification about a symbol block to Telegram no more than once every 10 minutes."""
        now = time.time()
        last_time = self.last_blacklist_notification.get(symbol, 0)

        if now - last_time > 600:  # 10 minutes
            if self.telegram_notifier:
                self.last_blacklist_notification[symbol] = now
                try:
                    await self.telegram_notifier.blacklist_alert(
                        symbol=symbol,
                        reason=reason,
                        until=until,
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    )
                except Exception as e:
                    logger.error(
                        f"[AutoBlacklist:{symbol}] Failed to send notification: {e}"
                    )

    async def _check_and_apply_auto_blacklist_rules(self, symbol: str):
        """Checks auto-blacklist rules and adds the symbol to the blacklist when triggered."""
        stop_timestamps = self._symbol_stop_timestamps.get(symbol, [])
        if not stop_timestamps:
            return  # No stops - nothing to check

        if not self.db_session or not crud or not self.user_id:
            return

        auto_rules = self._auto_blacklist_rules
        if not auto_rules:
            return

        now = time.time()

        try:
            for rule in auto_rules:
                rule = ensure_dict(rule)
                if not rule.get("enabled", True):
                    continue

                rule_consecutive_stops = rule.get("consecutiveStops", 999)
                within_period = rule.get(
                    "withinPeriod"
                )  # '15m', '30m', '1h', '2h', '4h', '8h', '24h' or None

                # Defining period in seconds
                period_seconds = None
                if within_period:
                    period_map = {
                        "15m": 15 * 60,
                        "30m": 30 * 60,
                        "1h": 1 * 60 * 60,
                        "2h": 2 * 60 * 60,
                        "4h": 4 * 60 * 60,
                        "8h": 8 * 60 * 60,
                        "24h": 24 * 60 * 60,
                    }
                    period_seconds = period_map.get(within_period)

                # Filtering stops by period
                if period_seconds:
                    cutoff_time = now - period_seconds
                    relevant_stops = [ts for ts in stop_timestamps if ts >= cutoff_time]
                else:
                    # No time limit - all stops in a row
                    relevant_stops = stop_timestamps

                stops_count = len(relevant_stops)
                logger.debug(
                    f"[AutoBlacklist:{symbol}] Rule check: {stops_count} stops (period={within_period}), required={rule_consecutive_stops}"
                )

                if stops_count >= rule_consecutive_stops:
                    duration = rule.get("duration", "end_of_day")
                    logger.warning(
                        f"[AutoBlacklist:{symbol}] Rule triggered! {stops_count} stops within {within_period or 'all time'} >= {rule_consecutive_stops}. Duration: {duration}"
                    )
                    await self._auto_add_to_blacklist(
                        symbol, duration, stops_count, within_period=within_period
                    )
                    # After adding, clear the stop history
                    self._symbol_stop_timestamps[symbol] = []
                    break  # Applying only the first triggered rule
        except Exception as e:
            logger.error(
                f"[AutoBlacklist:{symbol}] Error checking auto-blacklist rules: {e}",
                exc_info=True,
            )

    async def _auto_add_to_blacklist(
        self,
        symbol: str,
        duration: str,
        consecutive_stops: int,
        within_period: Optional[str] = None,
    ):
        """Adds a symbol to the blacklist automatically based on a rule."""
        if not self.db_session or not crud or not self.user_id:
            logger.error(
                f"[AutoBlacklist:{symbol}] Cannot add to blacklist: DB session or user_id missing"
            )
            return

        try:
            now = datetime.now(timezone.utc)

            # Calculating the lock expiration time
            until_dt: Optional[datetime] = None
            if duration == "1h":
                until_dt = now + timedelta(hours=1)
            elif duration == "4h":
                until_dt = now + timedelta(hours=4)
            elif duration == "8h":
                until_dt = now + timedelta(hours=8)
            elif duration == "end_of_day":
                # End of day UTC
                tomorrow = now.date() + timedelta(days=1)
                until_dt = datetime.combine(
                    tomorrow, dt_time(0, 0, 0, tzinfo=timezone.utc)
                )
            # 'permanent' - until_dt remains None

            period_label = within_period if within_period else "all time"
            reason = f"Auto-blacklist: {consecutive_stops} consecutive stops within {period_label}"

            # Getting current configuration
            self.db_session.expire_all()
            config_obj = await crud.get_config(self.db_session, user_id=self.user_id)
            if not config_obj:
                logger.error(
                    f"[AutoBlacklist:{symbol}] Config not found for user {self.user_id}"
                )
                return

            rm_settings = (
                ensure_dict(config_obj.risk_management)
                if config_obj.risk_management
                else {}
            )
            blacklist_data = ensure_dict(rm_settings.get("blacklist", {}))
            coins = blacklist_data.get("coins", [])

            # Checking if the symbol has already been added
            existing_idx = None
            for i, coin in enumerate(coins):
                coin = ensure_dict(coin)
                if coin.get("symbol", "").upper() == symbol.upper():
                    existing_idx = i
                    break

            new_coin = {
                "symbol": symbol.upper(),
                "until": until_dt.isoformat() if until_dt else None,
                "reason": reason,
                "addedAt": now.isoformat(),
            }

            if existing_idx is not None:
                coins[existing_idx] = new_coin
                logger.info(
                    f"[AutoBlacklist:{symbol}] Updated existing blacklist entry"
                )
            else:
                coins.append(new_coin)
                logger.info(f"[AutoBlacklist:{symbol}] Added new blacklist entry")

            # Save back
            blacklist_data["coins"] = coins
            rm_settings["blacklist"] = blacklist_data

            await crud.update_config_section(
                self.db_session, self.user_id, "risk_management", rm_settings
            )
            await self.db_session.commit()

            logger.warning(
                f"[AutoBlacklist:{symbol}] Symbol added to blacklist until {until_dt.isoformat() if until_dt else 'permanent'}. Reason: {reason}"
            )

            # Sending notification to Telegram
            if self.telegram_notifier:
                try:
                    await self.telegram_notifier.blacklist_alert(
                        symbol=symbol,
                        reason=reason,
                        until=until_dt.isoformat() if until_dt else None,
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    )
                except Exception as notif_e:
                    logger.error(
                        f"[AutoBlacklist:{symbol}] Failed to send Telegram notification: {notif_e}"
                    )

        except Exception as e:
            logger.error(
                f"[AutoBlacklist:{symbol}] Error adding to blacklist: {e}",
                exc_info=True,
            )

    def _check_risk_limits(self):  # Global limits
        should_be_allowed = True
        disable_reason = ""
        if self.stats.current_balance < self.min_balance_threshold:
            should_be_allowed = False
            disable_reason = f"Balance (${self.stats.current_balance:.2f}) < min (${self.min_balance_threshold:.2f})"
        else:
            if self.stats.start_of_day_balance > 1e-9:
                drawdown_pct = (
                    abs(self.stats.today_pnl / self.stats.start_of_day_balance)
                    if self.stats.today_pnl < 0
                    else 0
                )
                if drawdown_pct >= self.max_drawdown_threshold:
                    should_be_allowed = False
                    disable_reason = f"Max drawdown ({drawdown_pct * 100:.2f}%) >= limit ({self.max_drawdown_threshold * 100:.2f}%)"
                daily_loss_pct = (
                    abs(self.stats.today_pnl / self.stats.start_of_day_balance)
                    if self.stats.today_pnl < 0
                    else 0
                )
                if daily_loss_pct >= self.daily_max_loss_threshold:
                    should_be_allowed = False
                    disable_reason = f"Daily loss ({daily_loss_pct * 100:.2f}%) >= limit ({self.daily_max_loss_threshold * 100:.2f}%)"
            if self.stats.consecutive_losses >= self.max_consecutive_losses:
                should_be_allowed = False
                disable_reason = f"Max consec losses ({self.stats.consecutive_losses}) >= limit ({self.max_consecutive_losses})"
        if not should_be_allowed and self._is_trading_allowed:
            logger.critical(f"Trading disabled globally! Reason: {disable_reason}")
            self._is_trading_allowed = False
            # Added check for self.loop_from_controller
            if self.telegram_notifier and self.loop_from_controller:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.telegram_notifier.risk_manager_alert(
                            reason=disable_reason,
                            alert_type="TRADE_DISABLED",
                            current_balance=self.stats.current_balance,
                            daily_pnl=self.stats.today_pnl,
                            chat_id=self.user_telegram_chat_id,
                            api_key_name=self.api_key_name,
                        ),
                        self.loop_from_controller,
                    )
                except Exception as e:
                    logger.error(f"Failed to schedule Telegram notification: {e}")

        elif should_be_allowed and not self._is_trading_allowed:
            logger.info(
                "Global risk limits are now within acceptable range. Re-enabling trading globally."
            )
            self._is_trading_allowed = True

    async def assess_signal(
        self,
        signal: StrategySignal,
        lot_params: Optional[Dict[str, float]],
        min_notional_usd: Optional[float],
        mode: str = "live",
        executor_override: Optional[Any] = None,
    ) -> Tuple[bool, Optional[float], Optional[float], Optional[str]]:
        log_prefix = f"[RiskAssessV2:{signal.strategy_name}:{signal.symbol}:{signal.direction.name}]"
        logger.info(
            f"{log_prefix} --- STARTING SIGNAL ASSESSMENT (Mode: {mode.upper()}) ---"
        )

        # BLACKLIST CHECK (on-the-fly)
        # Check the blacklist at an early stage to avoid wasting resources on further checks
        if not await self.is_symbol_trading_allowed(signal.symbol):
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Symbol is in blacklist or trading globally disabled."
            )
            return False, None, 0.0, "SYMBOL_BLACKLISTED"

        current_balance_val = 0.0
        risk_per_trade_base = 0.0
        max_stop_distance_pct_to_use = 0.0
        balance_updated_successfully = False

        if mode == "paper":
            try:
                paper_balances = await self.paper_executor.get_account_balance()
                usdt_balance_data = (
                    paper_balances.get("USDT") if paper_balances else None
                )
                current_balance_val = (
                    float(usdt_balance_data["free"]) if usdt_balance_data else 0.0
                )
                risk_per_trade_base = self.paper_risk_per_trade
                max_stop_distance_pct_to_use = self.paper_max_stop_distance_pct
                balance_updated_successfully = True
                logger.info(
                    f"{log_prefix} Using PAPER settings. Balance: ${current_balance_val:.2f}, Risk/Trade: {risk_per_trade_base * 100:.2f}%"
                )
            except Exception as e:
                logger.error(
                    f"{log_prefix} Failed to get paper balance: {e}", exc_info=True
                )
                return False, None, 0.0, "PAPER_BALANCE_FETCH_FAILED"
        else:  # live
            self._check_and_reset_daily_stats()
            if executor_override is not None and executor_override is not self.executor:
                try:
                    balances = await executor_override.get_account_balance()
                    usdt_balance_data = balances.get("USDT") if balances else None
                    if usdt_balance_data:
                        free_bal = float(usdt_balance_data.get("free", 0.0) or 0.0)
                        locked_bal = float(usdt_balance_data.get("locked", 0.0) or 0.0)
                        current_balance_val = free_bal + locked_bal
                        balance_updated_successfully = current_balance_val > 0
                    else:
                        balance_updated_successfully = False
                except Exception as e:
                    logger.error(
                        f"{log_prefix} Failed to get live balance from market executor override: {e}",
                        exc_info=True,
                    )
                    balance_updated_successfully = False
            else:
                balance_updated_successfully = await self.update_balance()
                self._check_risk_limits()
                current_balance_val = self.stats.current_balance
            risk_per_trade_base = self.live_risk_per_trade
            max_stop_distance_pct_to_use = self.live_max_stop_distance_pct
            logger.debug(
                f"{log_prefix} Using LIVE settings. Balance: ${current_balance_val:.2f}, Risk/Trade: {risk_per_trade_base * 100:.2f}%"
            )

        if current_balance_val <= 1e-9:
            return False, None, 0.0, "ZERO_BALANCE"

        # 1. By default, the final risk is equal to the base risk for the current mode.
        if signal.risk_usd is not None:
            initial_base_risk_usd_planned = max(float(signal.risk_usd), 0.0)
            logger.debug(
                f"{log_prefix} Using fixed risk budget from strategy signal: ${initial_base_risk_usd_planned:.2f}"
            )
        else:
            risk_per_trade_final = risk_per_trade_base

            # 2. If there is an override in the signal, use it.
            if signal.risk_pct is not None:
                risk_per_trade_final = max(float(signal.risk_pct), 0.0)
                logger.debug(
                    f"{log_prefix} Using risk per trade from strategy signal: {risk_per_trade_final * 100:.2f}%"
                )

            # Now `risk_per_trade_final` always has a correct value.
            initial_base_risk_usd_planned = current_balance_val * risk_per_trade_final

        logger.debug(
            f"{log_prefix} Initial Base Risk Planned (before S/S): ${initial_base_risk_usd_planned:.2f}"
        )

        if not self._is_trading_allowed:
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Trading disabled globally by portfolio risk limits."
            )
            return False, None, initial_base_risk_usd_planned, "GLOBAL_RISK_LIMIT"

        if not balance_updated_successfully:
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Failed to update/confirm current balance."
            )
            return False, None, initial_base_risk_usd_planned, "BALANCE_UPDATE_FAILED"

        # 1. Maximum allowable risk per trade in USD (including S/S multiplier)
        target_max_risk_usd = initial_base_risk_usd_planned
        current_risk_multiplier_ss = 1.0  # By default
        if (
            self._strategy_symbol_adjustment_enabled
            and self._strategy_symbol_risk_multipliers
        ):
            perf_key = (signal.symbol, signal.strategy_name)
            # defaultdict will create SymbolStrategyPerformanceStats with a default index if the key is missing
            perf_stats = self._symbol_strategy_performance[perf_key]
            idx = perf_stats.current_risk_multiplier_index

            if 0 <= idx < len(self._strategy_symbol_risk_multipliers):
                current_risk_multiplier_ss = self._strategy_symbol_risk_multipliers[idx]
            else:  # Fallback to the default index if the saved one is incorrect
                logger.error(
                    f"{log_prefix} Invalid risk_multiplier_index {idx} for {perf_key}. Resetting to default index {self._s_s_default_risk_idx}."
                )
                current_risk_multiplier_ss = self._strategy_symbol_risk_multipliers[
                    self._s_s_default_risk_idx
                ]
                perf_stats.current_risk_multiplier_index = (
                    self._s_s_default_risk_idx
                )  # Fixing index in statistics

            target_max_risk_usd *= current_risk_multiplier_ss
            logger.info(
                f"{log_prefix} Strategy/Symbol Risk Multiplier: {current_risk_multiplier_ss:.2f} (Index: {perf_stats.current_risk_multiplier_index}). "
                f"Target Max Risk USD for sizing (after S/S): ${target_max_risk_usd:.2f}"
            )

        if target_max_risk_usd <= 1e-9:
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Target Max Risk USD for sizing is zero/negative (${target_max_risk_usd:.2f}) "
                f"after S/S multiplier {current_risk_multiplier_ss:.2f}. Base planned risk was ${initial_base_risk_usd_planned:.2f}."
            )
            return False, None, initial_base_risk_usd_planned, "ZERO_RISK"

        # 2. Maximum position nominal in USD
        # Use a parameter from config (may be specific to the backtester or live trading)
        max_pos_size_pct_cfg = getattr(
            config,
            "MAX_REAL_POSITION_SIZE_PCT_BALANCE",  # Searching first for real-specific
            getattr(config, "BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE", 0.50),
        )  # Fallback to backtester one
        max_notional_for_position_usd = current_balance_val * max_pos_size_pct_cfg
        logger.debug(
            f"{log_prefix} Max Position Notional (config {max_pos_size_pct_cfg * 100:.2f}% of balance ${current_balance_val:.2f}): ${max_notional_for_position_usd:.2f}"
        )

        # 3. Price validation and calculation of distance to stop
        entry_price_for_calc = (
            signal.trigger_price
            if signal.trigger_price is not None
            else signal.entry_price
        )
        if entry_price_for_calc is None or entry_price_for_calc <= 0:
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Invalid entry/trigger price for calculation ({entry_price_for_calc})."
            )
            return False, None, initial_base_risk_usd_planned, "INVALID_PRICE"
        entry_price_d = Decimal(str(entry_price_for_calc))

        stop_loss_price = signal.stop_loss

        # NO STOP LOSS MODE
        # If stop_loss is None, it means the strategy works without a stop (DCA/Grid).
        # Position size is defined as risk_value (% of balance) directly,
        # without calculation via distance to stop.
        if stop_loss_price is None:
            logger.info(
                f"{log_prefix} NO STOP LOSS mode. Sizing position from the planned first-entry budget."
            )

            # Position size = target_max_risk_usd / entry_price (as margin, not risk)
            notional_for_position = target_max_risk_usd
            qty_no_sl = Decimal(str(notional_for_position)) / entry_price_d

            # Limiting by max_notional
            qty_limit_by_max_notional_d = (
                Decimal(str(max_notional_for_position_usd)) / entry_price_d
            )
            working_quantity_d = min(qty_no_sl, qty_limit_by_max_notional_d)

            logger.info(
                f"{log_prefix} No-SL sizing: notional=${notional_for_position:.2f}, qty={working_quantity_d:.8f}"
            )

            # Moving to stages 6+ (exchange filters)
            # Use stop_loss_distance_d = 0 for compatibility, but set the flag
            stop_loss_distance_d = Decimal("0")
            stop_loss_price_d = Decimal("0")
        else:
            # STANDARD LOGIC WITH STOP
            if stop_loss_price <= 0:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Invalid stop_loss price ({stop_loss_price})."
                )
                return False, None, initial_base_risk_usd_planned, "INVALID_SL"
            stop_loss_price_d = Decimal(str(stop_loss_price))

            if (
                signal.direction == SignalDirection.LONG
                and stop_loss_price_d >= entry_price_d
            ) or (
                signal.direction == SignalDirection.SHORT
                and stop_loss_price_d <= entry_price_d
            ):
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: SL ({stop_loss_price_d}) incorrectly placed relative to entry ({entry_price_d}) for {signal.direction.name}."
                )
                return False, None, initial_base_risk_usd_planned, "SL_WRONG_SIDE"

            stop_loss_distance_d = abs(entry_price_d - stop_loss_price_d)
            if stop_loss_distance_d <= Decimal(str(1e-9 * entry_price_for_calc)):
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Stop loss distance is zero or negligible ({stop_loss_distance_d})."
                )
                return False, None, initial_base_risk_usd_planned, "ZERO_SL_DISTANCE"
            logger.debug(
                f"{log_prefix} EntryPriceD: {entry_price_d}, SLPriceD: {stop_loss_price_d}, SLDistD: {stop_loss_distance_d}"
            )

            max_stop_pct_d = Decimal(str(max_stop_distance_pct_to_use))
            min_stop_pct_d = Decimal(
                str(getattr(config, "RISK_MANAGER_MIN_STOP_DISTANCE_PCT", 0.05))
            ) / Decimal("100")
            if stop_loss_distance_d > entry_price_d * max_stop_pct_d:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: SL distance {stop_loss_distance_d} ({(stop_loss_distance_d / entry_price_d * 100):.2f}%) > max allowed limit ({max_stop_pct_d * 100:.2f}%)."
                )
                return False, None, initial_base_risk_usd_planned, "SL_TOO_FAR"
            if stop_loss_distance_d < entry_price_d * min_stop_pct_d:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: SL distance {stop_loss_distance_d} ({(stop_loss_distance_d / entry_price_d * 100):.2f}%) < min allowed limit ({min_stop_pct_d * 100:.2f}%)."
                )
                return False, None, initial_base_risk_usd_planned, "SL_TOO_CLOSE"

            # 5. Determining quantity based on limits (standard logic)
            qty_limit_by_max_risk_d = (
                Decimal(str(target_max_risk_usd)) / stop_loss_distance_d
            )
            qty_limit_by_max_notional_d = (
                Decimal(str(max_notional_for_position_usd)) / entry_price_d
            )

            working_quantity_d = min(
                qty_limit_by_max_risk_d, qty_limit_by_max_notional_d
            )
            logger.debug(
                f"{log_prefix} QtyLimitByRisk(S/S adj): {qty_limit_by_max_risk_d:.8f}, QtyLimitByMaxNotional: {qty_limit_by_max_notional_d:.8f} -> WorkingQtyPreAdjust: {working_quantity_d:.8f}"
            )

        # 4. R/R check (skipping if there is no stop)
        signal_details = (
            signal.details if isinstance(getattr(signal, "details", None), dict) else {}
        )
        skip_rr_for_dca_grid = bool(
            signal_details.get("skip_min_rr_for_dca_grid")
            or signal_details.get("uses_dca_or_grid_management")
        )

        if stop_loss_price is not None and not skip_rr_for_dca_grid:
            target_profit_price_for_rr_calc = signal.take_profit
            if not target_profit_price_for_rr_calc and signal.partial_targets:
                relevant_partials = [
                    pt.price for pt in signal.partial_targets if pt.price is not None
                ]
                if relevant_partials:
                    target_profit_price_for_rr_calc = (
                        max(relevant_partials)
                        if signal.direction == SignalDirection.LONG
                        else min(relevant_partials)
                    )

            if (
                not target_profit_price_for_rr_calc
                or target_profit_price_for_rr_calc <= 0
            ):
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: No valid TP (final or partial) for R/R calculation. Derived TP: {target_profit_price_for_rr_calc}"
                )
                return False, None, initial_base_risk_usd_planned, "NO_TP_FOR_RR"

            take_profit_price_d = Decimal(str(target_profit_price_for_rr_calc))
            if (
                signal.direction == SignalDirection.LONG
                and take_profit_price_d <= entry_price_d
            ) or (
                signal.direction == SignalDirection.SHORT
                and take_profit_price_d >= entry_price_d
            ):
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Derived TP ({take_profit_price_d}) not profitable relative to entry ({entry_price_d})."
                )
                return False, None, initial_base_risk_usd_planned, "TP_NOT_PROFITABLE"

            profit_distance_d = abs(take_profit_price_d - entry_price_d)
            if stop_loss_distance_d <= Decimal("1e-9"):
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: SL distance is zero, cannot calculate R/R."
                )
                return False, None, initial_base_risk_usd_planned, "ZERO_SL_FOR_RR"
            rr_ratio_prices = profit_distance_d / stop_loss_distance_d
            min_rr_decimal_prices = Decimal(str(self.min_rr_ratio))
            if rr_ratio_prices < min_rr_decimal_prices:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Price R/R {rr_ratio_prices:.2f} (using TP={target_profit_price_for_rr_calc}) < min required {self.min_rr_ratio:.2f}."
                )
                return False, None, initial_base_risk_usd_planned, "LOW_RR"
            logger.debug(
                f"{log_prefix} Price R/R check PASSED: {rr_ratio_prices:.2f} >= {self.min_rr_ratio:.2f}"
            )
        elif skip_rr_for_dca_grid:
            logger.info(
                f"{log_prefix} R/R check SKIPPED (DCA/Grid management strategy)."
            )
        else:
            logger.info(f"{log_prefix} R/R check SKIPPED (no stop loss mode).")

        # 6. Applying exchange filters to working_quantity_d
        step_size_d = (
            Decimal(str(lot_params.get("stepSize", "0")))
            if lot_params
            else Decimal("0")
        )
        min_qty_d = (
            Decimal(str(lot_params.get("minQty", "0"))) if lot_params else Decimal("0")
        )
        max_qty_float = (
            float(lot_params.get("maxQty", float("inf")))
            if lot_params
            else float("inf")
        )
        min_notional_d = (
            Decimal(str(min_notional_usd))
            if min_notional_usd is not None
            else Decimal("0")
        )

        if step_size_d > Decimal("0"):
            prev_qty_before_step = working_quantity_d
            working_quantity_d = (working_quantity_d / step_size_d).quantize(
                Decimal("0"), rounding=ROUND_DOWN
            ) * step_size_d
            logger.debug(
                f"{log_prefix} Qty after stepSize ({step_size_d}): {prev_qty_before_step:.8f} -> {working_quantity_d:.8f}"
            )

        if float(working_quantity_d) > max_qty_float:  # Comparison with maxQty
            logger.warning(
                f"{log_prefix} Working qty {working_quantity_d:.8f} > maxQty {max_qty_float}. Clamping to maxQty."
            )
            working_quantity_d = Decimal(str(max_qty_float))
            if step_size_d > Decimal("0"):  # Re-rounding
                working_quantity_d = (working_quantity_d / step_size_d).quantize(
                    Decimal("0"), rounding=ROUND_DOWN
                ) * step_size_d
            logger.debug(
                f"{log_prefix} Qty after maxQty clamp and re-step: {working_quantity_d:.8f}"
            )

        if working_quantity_d < min_qty_d:
            logger.debug(
                f"{log_prefix} Working qty {working_quantity_d:.8f} < minQty {min_qty_d:.8f}. Attempting to adjust to minQty."
            )
            # Attempt to use minQty if it fits within BOTH limits: maximum notional AND maximum risk
            if min_qty_d * entry_price_d <= Decimal(
                str(max_notional_for_position_usd)
            ) and min_qty_d * stop_loss_distance_d <= Decimal(
                str(target_max_risk_usd)
            ):  # Comparing with target_max_risk_usd (already with S/S)
                working_quantity_d = min_qty_d
                logger.info(
                    f"{log_prefix} Adjusted qty to minQty: {working_quantity_d:.8f} (within notional and target risk limits)."
                )
            else:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Cannot use minQty ({min_qty_d:.8f}) as it would violate "
                    f"max_notional_for_pos (${max_notional_for_position_usd:.2f} vs needed ${min_qty_d * entry_price_d:.2f}) "
                    f"or target_max_risk (${target_max_risk_usd:.2f} vs needed ${min_qty_d * stop_loss_distance_d:.2f})."
                )
                return False, None, initial_base_risk_usd_planned, "MIN_QTY_VIOLATION"

        if working_quantity_d <= Decimal(
            "1e-9"
        ):  # If after all rounding/checks the quantity becomes zero
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Quantity became zero or negative ({working_quantity_d:.8f}) after minQty/maxQty/stepSize adjustments."
            )
            return False, None, initial_base_risk_usd_planned, "ZERO_QTY_AFTER_ADJUST"

        # Checking minNotional
        current_notional_d = working_quantity_d * entry_price_d
        if min_notional_d > Decimal("0") and current_notional_d < min_notional_d:
            logger.debug(
                f"{log_prefix} Current notional {current_notional_d:.2f} (qty {working_quantity_d:.8f}) < minNotional {min_notional_d:.2f}. Attempting adjustment."
            )
            required_qty_for_min_notional_d = min_notional_d / entry_price_d
            if step_size_d > Decimal("0"):
                required_qty_for_min_notional_d = (
                    required_qty_for_min_notional_d / step_size_d
                ).quantize(Decimal("0"), rounding=ROUND_UP) * step_size_d

            if (
                lot_params and required_qty_for_min_notional_d < min_qty_d
            ):  # Ensure it is not less than minQty
                required_qty_for_min_notional_d = min_qty_d
                logger.debug(
                    f"{log_prefix} Qty for minNotional was < minQty, adjusted to minQty: {required_qty_for_min_notional_d:.8f}"
                )

            # Check if this new quantity fits within BOTH limits: max notional AND max risk
            if required_qty_for_min_notional_d * entry_price_d <= Decimal(
                str(max_notional_for_position_usd)
            ) and required_qty_for_min_notional_d * stop_loss_distance_d <= Decimal(
                str(target_max_risk_usd)
            ):  # Comparing with target_max_risk_usd
                working_quantity_d = required_qty_for_min_notional_d
                logger.info(
                    f"{log_prefix} Adjusted qty to {working_quantity_d:.8f} to meet minNotional (within notional and target risk limits)."
                )
            else:
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Cannot adjust qty for minNotional as it would violate "
                    f"max_notional_for_pos (${max_notional_for_position_usd:.2f} vs needed ${required_qty_for_min_notional_d * entry_price_d:.2f}) "
                    f"or target_max_risk (${target_max_risk_usd:.2f} vs needed ${required_qty_for_min_notional_d * stop_loss_distance_d:.2f})."
                )
                return (
                    False,
                    None,
                    initial_base_risk_usd_planned,
                    "MIN_NOTIONAL_VIOLATION",
                )

        final_quantity_float = float(working_quantity_d)
        if final_quantity_float <= 1e-9:  # Final quantity check
            logger.warning(
                f"{log_prefix} Signal REJECTED. Reason: Final quantity is zero or negative ({final_quantity_float:.8f}) after all adjustments."
            )
            return False, None, initial_base_risk_usd_planned, "ZERO_QTY_FINAL"

        # 7. Dollar R/R check (if the parameter is enabled and there is a stop loss)
        min_dollar_rr_ratio_config = getattr(
            config, "RISK_MANAGER_MIN_DOLLAR_RR_RATIO", None
        )
        if (
            min_dollar_rr_ratio_config is not None
            and stop_loss_price is not None
            and not skip_rr_for_dca_grid
        ):
            min_dollar_rr_decimal = Decimal(str(min_dollar_rr_ratio_config))
            potential_profit_value_d = working_quantity_d * profit_distance_d
            actual_loss_value_d_for_dollar_rr = (
                working_quantity_d * stop_loss_distance_d
            )

            if actual_loss_value_d_for_dollar_rr > Decimal("1e-9"):
                dollar_rr_ratio_actual = (
                    potential_profit_value_d / actual_loss_value_d_for_dollar_rr
                )
                if dollar_rr_ratio_actual < min_dollar_rr_decimal:
                    logger.warning(
                        f"{log_prefix} Signal REJECTED. Reason: Dollar R/R {dollar_rr_ratio_actual:.2f} "
                        f"(Profit: ${potential_profit_value_d:.2f}, Risk: ${actual_loss_value_d_for_dollar_rr:.2f}) "
                        f"< min required {min_dollar_rr_decimal:.2f}."
                    )
                    return False, None, initial_base_risk_usd_planned, "LOW_DOLLAR_RR"
            elif potential_profit_value_d <= Decimal(
                "0"
            ):  # If risk is zero and profit is not positive
                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: Dollar R/R check failed. Risk is zero, but potential profit (${potential_profit_value_d:.2f}) is not positive."
                )
                return False, None, initial_base_risk_usd_planned, "ZERO_RISK_NO_PROFIT"
            logger.debug(
                f"{log_prefix} Dollar R/R check PASSED (if enabled). Ratio: {dollar_rr_ratio_actual if actual_loss_value_d_for_dollar_rr > 1e-9 else 'N/A'}"
            )
        elif min_dollar_rr_ratio_config is not None and skip_rr_for_dca_grid:
            logger.info(
                f"{log_prefix} Dollar R/R check SKIPPED (DCA/Grid management strategy)."
            )
        elif min_dollar_rr_ratio_config is not None:
            logger.info(f"{log_prefix} Dollar R/R check SKIPPED (no stop loss mode).")

        # Final calculation of actual risk for logging
        actual_risk_usd_final_trade = float(working_quantity_d * stop_loss_distance_d)

        logger.info(
            f"{log_prefix} Signal APPROVED. Final Qty: {final_quantity_float:.8f}. "
            f"InitialBaseRiskPlannedUSD: ${initial_base_risk_usd_planned:.2f}, "
            f"TargetMaxRiskForSizingUSD: ${target_max_risk_usd:.2f} (this was used for qty calc), "
            f"ActualFinalTradeRiskUSD: ${actual_risk_usd_final_trade:.2f} (this is the real $ risk with final qty)."
        )
        logger.info(f"{log_prefix} --- ASSESSMENT FINISHED: APPROVED ---")

        return True, final_quantity_float, initial_base_risk_usd_planned, None

    async def _load_performance_from_db(self):
        if not crud or not self.db_session:
            logger.warning(
                "CRUD or DB session not available, skipping loading performance state from DB."
            )
            return

        try:
            logger.info(
                f"Loading symbol-strategy performance state from DB for user_id: {self.user_id}"
            )
            performance_records = await crud.get_all_symbol_strategy_performance(
                db=self.db_session, user_id=self.user_id
            )

            count = 0
            for record in performance_records:
                perf_key = (record.symbol, record.strategy_name)

                # JSON deserialization back to deque
                buffer_list = json.loads(record.trade_results_buffer_json)
                buffer_deque = deque(
                    buffer_list, maxlen=self._strategy_symbol_window_size
                )

                # Recreating statistics object
                stats_obj = SymbolStrategyPerformanceStats(
                    trade_results_buffer=buffer_deque,
                    current_risk_multiplier_index=record.current_risk_multiplier_index,
                    last_penalty_timestamp=record.last_penalty_timestamp,
                    total_trades_for_assessment=record.total_trades_for_assessment,
                    total_pnl_usd=getattr(record, "total_pnl_usd", 0.0),
                )

                # Recalculating derivative fields based on the buffer
                stats_obj.current_pnl_sum_usd = sum(
                    p for p, r in stats_obj.trade_results_buffer
                )
                stats_obj.sum_initial_risk_usd_in_window = sum(
                    r for p, r in stats_obj.trade_results_buffer
                )
                stats_obj.current_wins_in_window = sum(
                    1 for p, r in stats_obj.trade_results_buffer if p > 0
                )
                stats_obj.current_trades_in_window = len(stats_obj.trade_results_buffer)

                self._symbol_strategy_performance[perf_key] = stats_obj
                count += 1

            logger.info(
                f"Successfully loaded {count} performance records from DB for user_id: {self.user_id}"
            )

        except Exception as e:
            logger.error(
                f"Failed to load performance state from DB for user_id: {self.user_id}. Error: {e}",
                exc_info=True,
            )

    async def _save_performance_to_db(
        self, symbol: str, strategy_name: str, stats: SymbolStrategyPerformanceStats
    ):
        if not crud or not self.db_session:
            logger.warning(
                "CRUD or DB session not available, skipping saving performance state to DB."
            )
            return

        try:
            # Preparing data for saving to the DB
            performance_data = {
                "symbol": symbol,
                "strategy_name": strategy_name,
                "trade_results_buffer_json": json.dumps(
                    list(stats.trade_results_buffer)
                ),
                "current_risk_multiplier_index": stats.current_risk_multiplier_index,
                "last_penalty_timestamp": stats.last_penalty_timestamp,
                "total_trades_for_assessment": stats.total_trades_for_assessment,
                "total_pnl_usd": stats.total_pnl_usd,
            }

            # Call the CRUD function to create or update a record
            await crud.update_or_create_symbol_strategy_performance(
                db=self.db_session,
                user_id=self.user_id,
                performance_data=performance_data,
            )
            logger.debug(
                f"Saved performance for {symbol}-{strategy_name} to DB for user_id: {self.user_id}"
            )

        except Exception as e:
            logger.error(
                f"Failed to save performance state to DB for user_id: {self.user_id}, {symbol}-{strategy_name}. Error: {e}",
                exc_info=True,
            )

    def get_pnl_for_strategy(self, symbol: str, strategy_name: str) -> float:
        """
        Returns the cumulative PnL for a specific symbol/strategy pair
        for the entire duration of the current bot session.

        Data is loaded from the DB at startup and updated after each trade.
        """
        perf_stats = self._symbol_strategy_performance.get((symbol, strategy_name))
        if perf_stats:
            # Returning a new field with total PnL, not PnL from the window
            return perf_stats.total_pnl_usd
        return 0.0

    async def save_state(self):
        pass

    def _adjust_and_round_quantity(
        self,
        quantity: float,
        symbol: str,
        price: Optional[float],
        lot_params: Optional[Dict],
        min_notional: Optional[float],
    ) -> Optional[float]:
        """Rounds and checks the quantity according to exchange filters."""
        if quantity <= 1e-12:
            return 0.0
        log_prefix = f"[_AdjustQty:{symbol}]"
        adj_qty = quantity

        # Log input data for diagnostics
        logger.debug(
            f"{log_prefix} Input: qty={quantity:.8f}, price={price}, lot_params={lot_params}, min_notional={min_notional}"
        )

        try:
            if lot_params and lot_params.get("stepSize", 0) > 0:
                step = Decimal(str(lot_params["stepSize"]))
                qty_dec = Decimal(str(quantity))
                adj_qty = float(
                    (qty_dec / step).quantize(Decimal("0"), rounding=ROUND_DOWN) * step
                )
                if adj_qty != quantity:
                    logger.debug(
                        f"{log_prefix} Qty {quantity:.8f} rounded to step {step} -> {adj_qty:.8f}"
                    )

            if adj_qty <= 1e-12:
                return 0.0

            min_qty_filter = lot_params.get("minQty", 0) if lot_params else 0
            if adj_qty < min_qty_filter:
                # Extended logging for diagnostics
                logger.warning(
                    f"{log_prefix} REJECTED: Rounded qty {adj_qty:.8f} < minQty {min_qty_filter}. "
                    f"Original qty: {quantity:.8f}, lot_params: {lot_params}"
                )
                return None

            if (
                min_notional is not None
                and min_notional > 0
                and price is not None
                and price > 0
            ):
                notional_value = adj_qty * price
                if notional_value < min_notional:
                    # Extended logging for diagnostics
                    logger.warning(
                        f"{log_prefix} REJECTED: Notional ${notional_value:.2f} (qty={adj_qty:.8f} * price={price:.8f}) < minNotional ${min_notional:.2f}. "
                        f"Original qty: {quantity:.8f}"
                    )
                    return None

            max_qty_filter = (
                lot_params.get("maxQty", float("inf")) if lot_params else float("inf")
            )
            if adj_qty > max_qty_filter:
                logger.warning(
                    f"{log_prefix} Rounded qty {adj_qty:.8f} > maxQty {max_qty_filter}. Clamping."
                )
                adj_qty = max_qty_filter
                if adj_qty < min_qty_filter:
                    return None
                if (
                    min_notional is not None
                    and min_notional > 0
                    and price is not None
                    and price > 0
                ):
                    if (adj_qty * price) < min_notional:
                        return None

            if adj_qty <= 1e-12:
                return 0.0
            return adj_qty

        except Exception as e:
            logger.error(
                f"{log_prefix} Error adjusting quantity {quantity:.8f}: {e}",
                exc_info=True,
            )
            return None

    async def calculate_scaled_in_quantity(
        self,
        position: BasePosition,
        add_size_pct: float,
        current_price: float,
        lot_params: Optional[Dict[str, float]],
        min_notional_usd: Optional[float],
    ) -> Optional[float]:
        log_prefix = f"[RiskManager:ScaleInQty:{position.symbol}]"

        if (
            not position.initial_risk_usd_planned
            or position.initial_risk_usd_planned <= 0
        ):
            logger.error(
                f"{log_prefix} Cannot calculate scale-in quantity without initial_risk_usd_planned."
            )
            return None

        additional_risk_usd = position.initial_risk_usd_planned * (add_size_pct / 100.0)

        # If position is without stop-loss (DCA mode)
        if position.current_sl_price is None:
            # Calculating size based on margin, same as at entry
            new_quantity = additional_risk_usd / current_price
            logger.debug(
                f"{log_prefix} Scale-in NO_STOP_LOSS mode. Target additional notional: ${additional_risk_usd:.2f}. Qty: {new_quantity:.8f}"
            )
        else:
            stop_loss_distance = abs(current_price - position.current_sl_price)

            if stop_loss_distance <= 1e-9:
                logger.error(f"{log_prefix} Stop loss distance is zero or negative.")
                return None

            new_quantity = additional_risk_usd / stop_loss_distance

        return self._adjust_and_round_quantity(
            new_quantity, position.symbol, current_price, lot_params, min_notional_usd
        )
