# api/schemas.py
import re
from enum import Enum
from pydantic import (
    BaseModel,
    Field,
    EmailStr,
    ConfigDict,
    model_validator,
    field_validator,
    computed_field,
)
from pydantic.alias_generators import to_snake, to_camel
from typing import TypeVar, Generic, Optional, List, Any, Dict, Union, Tuple, Literal
from datetime import datetime
from . import schemas
import uuid

BACKTEST_ENGINE_ALIASES = {
    "vector": "vector",
    "turbo": "vector",
    "kline": "kline",
    "precision": "kline",
}


def normalize_backtest_engine(raw_engine: Any, default: str = "vector") -> str:
    normalized = str(raw_engine or "").strip().lower()
    if not normalized:
        return default

    if normalized not in BACKTEST_ENGINE_ALIASES:
        allowed_values = ", ".join(sorted(BACKTEST_ENGINE_ALIASES))
        raise ValueError(
            f"Invalid backtest_engine '{raw_engine}'. Allowed values: {allowed_values}."
        )

    return BACKTEST_ENGINE_ALIASES[normalized]


# --- User Schemas ---
class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str
    ref_code: Optional[str] = None
    source: Optional[str] = None  # 'pwa' or 'desktop'

    @field_validator("username")
    def username_must_be_safe(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_.-]*$", v):
            raise ValueError("Username contains invalid characters.")
        return v


class EmailRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    email: EmailStr
    source: Optional[str] = None


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class User(UserBase):
    id: int
    created_at: datetime
    plan: str
    is_active: bool = True
    role: str
    xp: int
    level: int
    referral_code: Optional[str] = None
    affiliate_commission_rate: Optional[float] = None  # Added field

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PaginatedUsers(BaseModel):
    total: int
    users: List[User]


class AdminUserStats(BaseModel):
    referral_count: int
    paying_referral_count: int
    total_earnings: float
    pending_earnings: float

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AdminUser(User):
    stats: Optional[AdminUserStats] = None


class PaginatedAdminUsers(BaseModel):
    total: int
    users: List[AdminUser]


# --- Token Schemas ---
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class LoginResponse(BaseModel):
    token: Token
    user: User


class TokenData(BaseModel):
    username: Optional[str] = None


# --- Push Notification Schemas ---


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribePayload(BaseModel):
    endpoint: str


class CreatePaymentRequest(BaseModel):
    plan_name: str
    currency: Optional[str] = None


class ApiKeyBase(BaseModel):
    name: str
    exchange: str

    @field_validator("name")
    def name_must_be_safe(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\s.-]*$", v):
            raise ValueError("Name contains invalid characters.")
        return v


class ApiKeyCreate(ApiKeyBase):
    api_key: str
    api_secret: str
    api_password: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_snake,
        populate_by_name=True,
    )


class ApiKey(ApiKeyBase):
    id: int
    key_prefix: str
    status: str
    is_active: bool = True
    created_at: datetime
    last_used: Optional[datetime] = None

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ApiKeyStatusUpdate(BaseModel):
    is_active: bool


class AssetBalance(BaseModel):
    asset: str
    free: float
    locked: float
    total: float

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AccountBalance(BaseModel):
    api_key_id: int
    api_key_name: str
    exchange: str = "unknown"
    market_type: str = "futures_usdtm"
    balance: float
    available_balance: float
    unrealized_pnl: float
    margin_used: float
    total_equity: float = 0.0
    assets: List[AssetBalance] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MarketBalanceSummary(BaseModel):
    market_type: str
    total_balance: float
    total_available: float
    total_unrealized_pnl: float
    total_margin_used: float
    total_equity: float
    accounts_count: int

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MultiAccountOverview(BaseModel):
    market_type: str = "all"
    total_balance: float
    total_available: float
    total_unrealized_pnl: float
    total_margin_used: float = 0.0
    total_equity: float = 0.0
    market_breakdown: List[MarketBalanceSummary] = Field(default_factory=list)
    accounts: List[AccountBalance]

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PaperWallet(BaseModel):
    asset: str
    balance: float

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --- Config Schemas ---


# --- Blacklist Schemas ---
class BlacklistedCoin(BaseModel):
    """Represents a single blacklisted coin."""

    symbol: str  # e.g., "BTCUSDT"
    until: Optional[datetime] = (
        None  # None = permanent, datetime = until specified time
    )
    reason: Optional[str] = None  # Optional reason for blacklisting
    added_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,  # Use camelCase during serialization
    )


class AutoBlacklistRule(BaseModel):
    """Rule for automatically blacklisting a coin."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    enabled: bool = True
    consecutive_stops: int = Field(
        ge=1, description="Number of consecutive stop-losses to trigger the rule"
    )
    within_period: Optional[Literal["15m", "30m", "1h", "2h", "4h", "8h", "24h"]] = (
        Field(
            default=None,
            description="Time window to track stop-losses. None = no time limit (any consecutive stop-losses)",
        )
    )
    duration: Literal["1h", "4h", "8h", "end_of_day", "permanent"] = Field(
        default="end_of_day",
        description="Lock duration: 1h, 4h, 8h, end_of_day, permanent",
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,  # Use camelCase during serialization
    )


class BlacklistSettings(BaseModel):
    """Blacklist settings for coins."""

    coins: List[BlacklistedCoin] = Field(default_factory=list)
    auto_rules: List[AutoBlacklistRule] = Field(
        default_factory=list, description="Rules for automatically blacklisting"
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,  # Use camelCase during serialization
    )


class RiskManagementSettings(BaseModel):
    # Existing fields
    maxDrawdown: float
    maxConsecutiveLosses: Optional[int] = None
    dailyMaxLossPercent: Optional[float] = None
    maxConcurrentTrades: int
    stopLossEnabled: bool
    defaultStopLossPercent: Optional[float] = None
    maxStopDistancePct: float = Field(
        default=10.0,
        description="Maximum allowed distance to stop-loss in % of entry price",
    )
    riskPerTradePercent: Optional[float] = Field(
        default=1.0, description="Risk per trade in % of balance for live trading"
    )

    # NEW FIELDS for Adaptive RM
    strategySymbolAdjustmentEnabled: bool = Field(
        default=False, description="Enable adaptive risk manager"
    )
    strategySymbolWindowSize: int = Field(
        default=20, gt=0, description="Number of trades for analysis"
    )
    strategySymbolMinTradesForAssessment: int = Field(
        default=10,
        gt=0,
        description="Minimum number of trades for the first evaluation",
    )
    strategySymbolPnlThresholdPct: float = Field(
        default=-150.0, description="PnL threshold to reduce risk (in % of risk)"
    )
    strategySymbolWinRateThresholdPct: float = Field(
        default=35.0, ge=0, le=100, description="WinRate threshold to reduce risk (%)"
    )
    strategySymbolMaxConsecutiveLosses: int = Field(
        default=5, gt=0, description="Max consecutive losses to reduce risk"
    )

    strategySymbolRecoveryConsecutiveWins: int = Field(
        default=3, gt=0, description="Number of wins to restore risk"
    )
    strategy_symbol_recovery_pnl_threshold_pct: float = 50.0
    strategy_symbol_cooldown_after_penalty_seconds: int = 86400

    blacklist: Optional[BlacklistSettings] = Field(
        default=None, description="Coin blacklist for trading"
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class BacktestRiskManagementSettings(BaseModel):
    maxDrawdown: float
    dailyMaxLossPercent: Optional[float] = None
    maxConsecutiveLosses: int
    maxConcurrentTrades: int
    stopLossEnabled: bool
    defaultStopLossPercent: Optional[float] = None
    maxStopDistancePct: float = Field(
        default=10.0,
        description="Maximum allowed distance to stop-loss in % of entry price",
    )
    riskPerTradePercent: Optional[float] = Field(
        default=1.0, description="Risk per trade in % of balance"
    )
    leverage: Optional[float] = Field(default=10.0, description="Leverage")
    strategySymbolAdjustmentEnabledForBacktest: bool = Field(
        default=False, description="Enable adaptive risk manager for backtests"
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ExchangePlatformSettings(BaseModel):
    enabled: bool
    api_key_name: str


class ExchangeSettings(BaseModel):
    binance: Optional[ExchangePlatformSettings] = None
    binance_futures: Optional[ExchangePlatformSettings] = None
    binance_spot: Optional[ExchangePlatformSettings] = None

    model_config = ConfigDict(extra="allow")


class NotificationSettings(BaseModel):
    emailEnabled: bool
    telegramEnabled: bool
    telegramChatId: Optional[str] = None
    telegramUsername: Optional[str] = None

    # Granular Telegram notification settings (all default to True for backward compatibility)
    notifyNewPosition: bool = True
    notifyPositionClosed: bool = True
    notifyPartialTp: bool = True
    notifySlMovedToBe: bool = True
    notifyRiskAlerts: bool = True
    notifyOrderErrors: bool = True
    notifyBotErrors: bool = True
    notifyBlacklistAlerts: bool = True

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TestNotificationRequest(BaseModel):
    chat_id: str


class SupportTicketCreate(BaseModel):
    subject: str
    category: str
    description: str
    context: Optional[Dict[str, Any]] = None
    screenshot: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupportTicketMessageResponse(BaseModel):
    id: int
    ticket_id: str
    sender_name: str
    text: str
    image: Optional[str] = None
    is_admin: bool
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupportTicket(BaseModel):
    id: str
    subject: str
    category: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    context: Optional[Dict[str, Any]] = None
    screenshot: Optional[str] = None
    messages: List[SupportTicketMessageResponse] = []

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupportTicketUpdate(BaseModel):
    status: Optional[str] = None
    category: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AdminSupportTicket(SupportTicket):
    user_email: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupportTicketMessageCreate(BaseModel):
    text: str
    sender_name: Optional[str] = None
    image: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupportTicketStatusResponse(BaseModel):
    id: str
    status: str
    subject: str
    category: str
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DataSourceStatus(BaseModel):
    name: str
    connected: bool
    lastSync: Optional[datetime] = None
    error: Optional[str] = None


class AppConfigBase(BaseModel):
    risk_management: Optional[RiskManagementSettings] = None
    backtest_risk_management: Optional[BacktestRiskManagementSettings] = None
    notifications: NotificationSettings
    data_sources: Dict[str, Any]
    exchange_settings: Optional[ExchangeSettings] = None


class AppConfigCreate(AppConfigBase):
    pass


class AppConfig(BaseModel):
    user_id: int  # Missing field added
    risk_management: Optional[RiskManagementSettings] = None
    backtest_risk_management: Optional[BacktestRiskManagementSettings] = None
    exchange_settings: Optional[Dict[str, Any]] = None
    notifications: Optional[Dict[str, Any]] = None
    data_sources: Optional[Dict[str, Any]] = None
    api_keys: List[ApiKey] = []

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Removed to make tests pass
        populate_by_name=True,
    )


# --- Task Schemas ---
class BacktestRunRequest(BaseModel):
    name: Optional[str] = None
    strategy_name: str
    symbol: str
    start_date: str  # Keep as string for input
    end_date: str  # Keep as string for input
    market_type: Literal["spot", "futures"] = Field(
        default="futures",
        description="The market type for the backtest ('spot' or 'futures')",
    )
    min_foundation_weight_threshold: Optional[float] = Field(
        default=None,
        description="Override the minimum foundation weight threshold for this specific run.",
    )
    foundation_weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="Override the foundation weights for this specific run.",
    )
    params: Optional[Dict[str, Any]] = None
    l2_storage_path: Optional[str] = Field(
        None, description="Path to L2 historical data storage for DepthSightBacktester."
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def check_dates(self):
        # Ensure start_date and end_date are present, otherwise validation might have already failed for missing fields
        # This validator runs *after* individual field validation.
        if self.start_date is None or self.end_date is None:
            # This case should ideally be caught by Pydantic's own required field validation
            # if start_date and end_date are not Optional. If they are optional, this check is needed.
            # Assuming they are not Optional as per the original schema.
            return self  # Let Pydantic handle missing field errors

        start_date_str, end_date_str = self.start_date, self.end_date

        # Attempt to parse with or without 'Z' and handle potential timezone awareness
        # Pydantic v2 fromisoformat is generally quite good.
        try:
            # Remove 'Z' if present, as fromisoformat in Python < 3.11 doesn't like 'Z' directly for non-aware datetime
            # For timezone-aware, it's better to ensure 'Z' is handled as UTC.
            # If dates are expected to be timezone-naive locally:
            start_dt_naive = datetime.fromisoformat(start_date_str.replace("Z", ""))
            end_dt_naive = datetime.fromisoformat(end_date_str.replace("Z", ""))

            # If they should be timezone-aware (UTC from 'Z'):
            # start_dt_aware = datetime.fromisoformat(start_date_str) if 'Z' in start_date_str else datetime.fromisoformat(start_date_str+'+00:00')
            # end_dt_aware = datetime.fromisoformat(end_date_str) if 'Z' in end_date_str else datetime.fromisoformat(end_date_str+'+00:00')
            # For this example, let's assume naive datetime comparison or that fromisoformat handles it.
            # The key is consistent handling.
            start_dt = start_dt_naive
            end_dt = end_dt_naive

        except ValueError as e:
            raise ValueError(
                f"Invalid date format for start_date or end_date. Ensure dates are ISO 8601 strings (e.g., YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SSZ). Error: {e}"
            )

        if start_dt >= end_dt:
            raise ValueError("start_date must be strictly before end_date")

        if self.params is not None:
            normalized_params = dict(self.params)
            normalized_params["backtest_engine"] = normalize_backtest_engine(
                normalized_params.get("backtest_engine"),
                default="vector",
            )
            self.params = normalized_params
        return self


class OptimizationRunRequest(BaseModel):
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    optuna_config: Optional[Dict[str, Any]] = None


class Task(BaseModel):
    task_id: str
    status: str
    task_type: str
    submitted_at: datetime
    completed_at: Optional[datetime] = None
    results: Optional[Any] = None
    error_message: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# --- Trade Schema (NEW SCHEMA) ---
class Trade(BaseModel):
    id: int
    trade_uuid: str
    timestamp_close: datetime
    timestamp_entry: Optional[datetime] = None  # When position was actually opened
    timestamp_signal: Optional[datetime] = None  # When signal was generated
    symbol: str
    strategy_config_id: Optional[str] = None
    direction: str
    entry_price: Optional[float] = None  # Can be None for incomplete entries
    exit_price: Optional[float] = None  # Can be None for incomplete entries
    pnl: Optional[float] = None
    commission: Optional[float] = None
    exit_reason: Optional[str] = None
    quantity: Optional[float] = None
    trade_mode: str
    api_key_id: Optional[int] = None
    # New fields for grouping partial exits
    position_entry_id: Optional[str] = None
    exit_type: Optional[str] = None
    is_final_exit: Optional[bool] = False
    # Maximum floating profit and loss during the trade
    max_floating_profit: Optional[float] = None  # MFE - Maximum floating profit in USD
    max_floating_loss: Optional[float] = None  # MAE - Maximum floating loss in USD
    # Decision trace for foundation analysis (works for visual and genetic strategies)
    signal_details_json: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class TradeAnalyticsCreate(BaseModel):
    user_id: int
    source_type: str
    source_trade_id: str
    strategy_config_id: Optional[str] = None
    symbol: str
    direction: str
    timestamp_close: datetime
    pnl_usd: float
    win_rate_contribution: int
    profit_factor_gross_profit: float
    profit_factor_gross_loss: float
    used_foundations: List[
        str
    ]  # Now includes ALL entry conditions (foundations + indicators)
    used_filters: List[str]
    used_management_blocks: List[str]


# 1. Create TypeVar. This is a type variable.
DataType = TypeVar("DataType")


# 2. Modify ApiResponseData to inherit from Generic[DataType]
class ApiResponseData(BaseModel, Generic[DataType]):
    """
    Standardized API response structure with a 'data' field,
    the type of which can be anything (thanks to Generic).
    """

    data: DataType
    error: Optional[str] = None
    detail: Optional[Any] = None  # For additional error information

    model_config = {
        "from_attributes": True,
    }


class ApiResponse(BaseModel):
    """
    Simple wrapper for responses where 'data' is a dictionary
    (compatible with legacy code).
    """

    data: Dict[str, Any]


# Schemas for displaying status and progress of backtest
class ProgressInfoKpis(BaseModel):
    progress: float
    current_date: str
    balance: float
    pnl: float
    trades: int
    wins: Optional[int] = None  # Add field for wins
    losses: Optional[int] = None  # Add field for losses
    win_rate: float
    max_drawdown: float
    equity_curve_live: Optional[List[List[Any]]] = None
    live_trades: List[Trade] = []


class ProgressInfoEvent(BaseModel):
    timestamp: str
    type: str
    message: str


class ProgressInfo(BaseModel):
    kpis: ProgressInfoKpis
    events: List[ProgressInfoEvent]


# --- Add field to BacktestResults ---
class BacktestResults(BaseModel):
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    trades_count: int
    equity_curve: Optional[List[List[Any]]] = None
    trades: List[Trade] = []


class TradeExecution(BaseModel):
    timestamp: datetime
    price: float
    quantity: float
    type: str  # 'ENTRY' | 'EXIT'

    model_config = ConfigDict(from_attributes=True)


class BacktestTrade(BaseModel):
    id: int
    direction: str
    timestamp_entry: datetime
    timestamp_exit: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    commission: float
    exit_reason: str
    decision_trace_json: Optional[dict] = None

    executions: List[TradeExecution] = []

    symbol: str
    strategy_name: str

    model_config = ConfigDict(from_attributes=True)


class PaginatedTradesResponse(BaseModel):
    total: int
    trades: List[BacktestTrade]


class BacktestRunListItem(BaseModel):
    """Lightweight schema for the backtests list."""

    id: str
    task_id: str
    strategy_name: str
    symbol: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    pnl: Optional[float] = None  # Will be extracted from KPI
    win_rate: Optional[float] = None  # Will be extracted from KPI

    model_config = ConfigDict(from_attributes=True)


class BacktestRunDetails(BacktestRunListItem):
    """Full schema for a single backtest with all details."""

    start_date: datetime  # These are for response, not input
    end_date: datetime
    initial_balance: float
    strategy_params: Dict[str, Any] = Field(alias="parameters_json")
    kpi_results_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    equity_curve_json: Optional[List[List[Any]]] = None
    analytics_report_json: Optional[Dict[str, Any]] = None
    trades: List[BacktestTrade] = []
    tick_size: Optional[float] = None
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# --- Schemas for Sharing Backtests ---


class ShareCreate(BaseModel):
    """Schema for creating a public backtest link request."""

    is_strategy_name_public: bool = Field(alias="isStrategyNamePublic")
    are_parameters_public: bool = Field(alias="areParametersPublic")
    publish_to_leaderboard: bool = Field(default=False, alias="publishToLeaderboard")

    model_config = ConfigDict(
        populate_by_name=True,
    )


class ShareResponseData(BaseModel):
    """Schema for the public link creation response."""

    share_url: str = Field(alias="shareUrl")
    public_slug: str = Field(alias="publicSlug")

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class SharedBacktestPeriod(BaseModel):
    start: datetime
    end: datetime


class SharedBacktestData(BaseModel):
    """Schema for the public backtest results page."""

    strategy_name: str = Field(alias="strategyName")
    symbol: str
    period: SharedBacktestPeriod
    kpis: Dict[str, Any]
    equity_curve: List[Any] = Field(alias="equityCurve")
    parameters: Optional[Dict[str, Any]] = None
    strategy_config: Optional[Dict[str, Any]] = Field(None, alias="strategyConfig")

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class PortfolioBacktestRunListItem(BaseModel):
    """Lightweight schema for the portfolio backtests list."""

    id: str  # task_id will be used
    name: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    pnl: Optional[float] = None
    sharpe_ratio: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# Modify TaskStatusResponse for backward compatibility, but new endpoints will use BacktestRun*
# --- Schemas for Optimization Progress ---
class OptimizationTrial(BaseModel):
    trial_number: int
    params: Dict[str, Any]
    value: float  # Objective function value for this trial
    datetime_start: Optional[datetime] = None
    datetime_complete: Optional[datetime] = None
    # Potentially add state like 'COMPLETE', 'FAIL', 'PRUNED' if Optuna provides it easily


class OptimizationProgressInfo(BaseModel):
    current_trial_number: (
        int  # Number of the trial currently being processed or just finished
    )
    total_trials_planned: Optional[int] = (
        None  # If known (e.g., n_trials in Optuna study)
    )
    best_trial_so_far: Optional[OptimizationTrial] = (
        None  # Details of the best trial found up to this point
    )
    recent_trials: List[
        OptimizationTrial
    ] = []  # Optional: keep a list of the last N trials
    status_message: Optional[str] = (
        None  # e.g., "Running trial 15/100", "Study optimization finished."
    )
    # Could also include study.user_attrs or other relevant Optuna study metadata if needed


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    submitted_at: datetime
    request_params: Optional[Dict[str, Any]] = None
    progress_info: Optional[
        Union[ProgressInfo, OptimizationProgressInfo, "GeneticRunProgress"]
    ] = None  # MODIFIED
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    # Updated results to accommodate different task result types
    results: Optional[Union["BacktestResults", "PortfolioBacktestResult", Any]] = (
        None  # Forward reference with quotes
    )


class PaginatedTasksResponse(BaseModel):
    total: int
    tasks: List[TaskStatusResponse]


class PortfolioStatus(BaseModel):
    balance: float
    today_pnl: float
    is_trading_allowed: bool
    consecutive_losses: int
    timestamp_utc: datetime
    market_type: str = "all"
    total_available: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_margin_used: float = 0.0
    market_breakdown: List[MarketBalanceSummary] = Field(default_factory=list)


class StrategyStartRequest(BaseModel):
    """
    Schema for launching a saved strategy configuration request.
    Accepts config ID and optional parameters for overriding.
    """

    config_id: str
    mode: str = "paper"
    symbol_selection_mode: Optional[str] = None
    symbols: Optional[List[str]] = None
    params: Optional[Dict[str, Any]] = None  # For dynamic configuration overrides
    api_key_id: Optional[int] = None  # Subaccount ID (API key) for multi-accounts


# --- Position Schemas ---
class PositionResponseItem(BaseModel):
    id: str
    symbol: str
    strategy: str
    direction: str  # 'LONG' | 'SHORT'
    size: float
    entry_price: float
    mark_price: float
    pnl: float
    pnl_percent: float
    entry_time: str  # ISO format datetime string
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    market_type: Optional[str] = None


# --- Strategy Operation Schemas (moved from depthsight_api.py) ---
class StrategyRunRequest(BaseModel):
    strategy_name: str = Field(..., json_schema_extra={"example": "VolumeBreakout"})
    symbol: str = Field(..., json_schema_extra={"example": "BTC/USDT"})
    market_type: str = Field(..., json_schema_extra={"example": "futures"})
    params: Dict[str, Any] = Field(
        ...,
        json_schema_extra={
            "example": {"candle_timeframe": "5m", "stop_loss_atr_multiplier": 1.5}
        },
    )
    # user_id will be added to payload in the endpoint, not part of request body from client directly for this schema


class StrategyInfo(StrategyRunRequest):  # For response
    id: str = Field(..., json_schema_extra={"example": "strat_8a3f-b821"})
    status: str = Field(..., json_schema_extra={"example": "running"})
    pnl: Optional[float] = Field(
        None, json_schema_extra={"example": 123.45}
    )  # Made Optional as it might not always be present
    open_positions: Optional[int] = Field(
        None, json_schema_extra={"example": 1}
    )  # Made Optional
    started_at: Optional[datetime] = None  # Made Optional
    user_id: Optional[int] = None  # To store who started it, if available from Redis
    symbol_selection_mode: Optional[str] = Field(None, description="STATIC or DYNAMIC")
    symbols: Optional[List[str]] = Field(
        None, description="List of symbols if STATIC mode"
    )
    mode: Optional[str] = Field("paper", description="Trading mode: live or paper")
    api_key_id: Optional[int] = Field(
        None, description="ID of the API key (subaccount) running this strategy"
    )
    name: Optional[str] = Field(
        None, description="User-defined name for the strategy instance"
    )

    model_config = ConfigDict(from_attributes=True)


# --- Portfolio Backtest Schemas ---


class PortfolioContractItem(BaseModel):
    id: Optional[str] = Field(
        None,
        description="Optional client-provided unique ID for this contract configuration.",
    )
    strategy_name: str
    symbol: str
    market_type: str = Field(
        default="spot", description="e.g., 'spot', 'futures_usdtm'"
    )
    params: Dict[str, Any]
    # Optional: include exchange rules if they are to be passed per contract
    # min_qty, step_size, tick_size, min_notional etc.
    # These could also be fetched by symbol later if a central exchange_info source exists
    exchange_rules: Optional[Dict[str, Any]] = Field(
        None, description="Optional: min_qty, step_size, tick_size, min_notional"
    )


class PortfolioBacktestRunRequest(BaseModel):
    name: Optional[str] = Field(
        "Portfolio Backtest", description="A descriptive name for the run"
    )
    start_date: str  # ISO format "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD"
    end_date: str  # ISO format
    initial_balance: float
    contracts: List[PortfolioContractItem]
    global_risk_limits: Dict[str, Any] = Field(
        default_factory=lambda: {
            "max_total_exposure_pct": 0.5,
            "max_concurrent_positions": 10,
            "commission_pct": 0.00075,
            "risk_pct_per_trade": 0.01,
            "simple_slippage_pct": 0.0005,  # Default 0.05% slippage for kline-based fallback
        }
    )
    # Potentially add optimization_params or other specific settings later
    l2_storage_path: Optional[str] = Field(
        None, description="Path to L2 historical data storage to enable L2 simulation."
    )

    @model_validator(mode="after")
    def check_portfolio_dates(cls, values):
        # This validator runs *after* individual field validation.
        start_date_str, end_date_str = values.start_date, values.end_date
        if (
            start_date_str is None or end_date_str is None
        ):  # Should be caught by Pydantic if not Optional
            return values
        try:
            # Strip 'Z' if present, as fromisoformat handles UTC offset like +00:00 better
            # Pydantic v2 generally handles ISO strings well.
            start_dt = datetime.fromisoformat(
                start_date_str.replace("Z", "+00:00")
                if "Z" in start_date_str
                else start_date_str
            )
            end_dt = datetime.fromisoformat(
                end_date_str.replace("Z", "+00:00")
                if "Z" in end_date_str
                else end_date_str
            )

        except ValueError as e:
            raise ValueError(
                f"Invalid date format for start_date or end_date. Use ISO 8601 format (e.g., YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SSZ). Error: {e}"
            )

        if start_dt >= end_dt:
            raise ValueError(
                "start_date must be strictly before end_date for portfolio backtest"
            )
        return values


class PortfolioBacktestKPIs(
    BaseModel
):  # Matches fields from PortfolioBacktester._calculate_kpis
    total_trades: int
    net_pnl_total: float
    gross_pnl_total: float
    total_commission_paid: float
    win_rate_pct: float
    num_wins: int
    num_losses: int
    profit_factor: float
    average_trade_pnl: float
    average_winning_trade_pnl: float
    average_losing_trade_pnl: float  # Usually positive value for avg loss
    max_drawdown_pct: float
    sharpe_ratio_simplified: float
    final_balance: float
    initial_balance: float
    profit_pct_on_initial: float
    total_entry_slippage_usd: float
    total_exit_slippage_usd: float
    total_slippage_usd: float
    avg_slippage_per_active_trade_usd: float
    avg_total_slippage_pct: float


class PortfolioBacktestSliceDetail(BaseModel):  # Renamed to avoid conflict
    pnl: float
    trades: int
    win_rate: Optional[float] = None


class PortfolioBacktestSliceAnalytics(BaseModel):  # Renamed to avoid conflict
    by_strategy: Dict[str, PortfolioBacktestSliceDetail]
    by_symbol: Dict[str, PortfolioBacktestSliceDetail]
    by_strategy_symbol: Dict[
        str, PortfolioBacktestSliceDetail
    ]  # Key: "StrategyName_Symbol"


class PortfolioBacktestResult(BaseModel):
    portfolio_kpis: PortfolioBacktestKPIs
    sliced_analytics: PortfolioBacktestSliceAnalytics  # Use the renamed version
    trade_log: List[Dict[str, Any]]  # List of trade records (as dicts for now)
    equity_curve: List[Tuple[str, float]]  # List of (timestamp_iso_string, balance)


class PositionData(BaseModel):
    id: str
    symbol: str
    strategy: str
    direction: str
    size: float
    entry_price: float
    mark_price: float
    pnl: float
    pnl_percent: float
    entry_time: str  # Consider datetime if Redis stores it structured, else str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    user_id: Optional[Any] = None  # Added to support authorization

    model_config = ConfigDict(from_attributes=True)


class UpdatePositionRequest(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


# --- Genetic Algorithm Schemas ---


# --- GeneticRun Schemas ---
class GeneticRunBase(BaseModel):
    config_json: Dict[str, Any] = Field(
        ..., description="Full configuration for the genetic run"
    )


class GeneticRunCreate(GeneticRunBase):
    """
    Extended schema for creating genetic runs from Command Center UI.
    All fields map to specific UI modules.
    """

    # === Universe & Data Module ===
    assets: Optional[List[str]] = Field(
        None, description="List of trading pairs (e.g., ['BTCUSDT', 'ETHUSDT'])"
    )
    train_split_pct: int = Field(
        70, ge=50, le=90, description="Time-machine slider: % for training"
    )
    trading_fee: float = Field(0.0004, description="Trading fee as decimal")
    slippage: float = Field(0.0001, description="Slippage model as decimal")
    initial_capital: float = Field(10000, description="Initial capital for backtest")

    # === DNA Architecture Module ===
    indicators: Optional[Dict[str, Dict[str, Any]]] = Field(
        None,
        description="Active indicators config: {id: {active, minPeriod, maxPeriod, timeframes}}",
    )
    filters: Optional[Dict[str, Dict[str, Any]]] = Field(
        None, description="Active filters config"
    )
    logic_tree_depth: int = Field(
        3, ge=1, le=7, description="Logic tree complexity depth"
    )
    correlation_limit: Optional[float] = Field(
        0.7, description="Max correlation between indicators"
    )
    signal_pruning: bool = Field(True, description="Remove redundant logic nodes")
    outlier_rejection: bool = Field(False, description="Ignore outlier strategies")
    diversity_penalty: bool = Field(True, description="Penalize similar strategies")

    # === Execution & Risk Module ===
    sl_range: Optional[List[float]] = Field(
        [1.5, 5.0], description="Stop loss ATR range [min, max]"
    )
    tp_range: Optional[List[float]] = Field(
        [2.0, 8.0], description="Take profit RR range [min, max]"
    )
    trailing_config: Optional[Dict[str, Any]] = Field(
        None, description="Trailing stop config"
    )
    breakeven_config: Optional[Dict[str, Any]] = Field(
        None, description="Breakeven config"
    )
    partial_tps: Optional[List[Dict[str, Any]]] = Field(
        [], description="Partial take profit configs"
    )
    time_stop_candles: int = Field(
        0, ge=0, description="Max hold time in candles (0=disabled)"
    )

    # === Fitness Lab Module ===
    fitness_weights: Optional[Dict[str, int]] = Field(
        {"pnl": 60, "drawdown": 30, "consistency": 10},
        description="Objective weights (should sum to 100)",
    )
    kill_switches: Optional[Dict[str, float]] = Field(
        {"max_dd": 20, "min_trades": 30},
        description="Hard gates for immediate rejection",
    )

    # === Evolution Parameters ===
    population_size: int = Field(100, ge=10, le=500, description="Population size")
    generations: int = Field(50, ge=5, le=200, description="Number of generations")
    crossover_probability: float = Field(0.7, ge=0.0, le=1.0)
    mutation_probability: float = Field(0.3, ge=0.0, le=1.0)

    # === Seed Strategy (for continuation/optimization) ===
    seed_config: Optional["SeedConfig"] = Field(
        None,
        description="Configuration for seeding with existing strategies (continue search or optimize)",
    )


# === Seed Strategy Config ===
class SeedConfig(BaseModel):
    """Configuration for seeding the genetic algorithm with existing strategies."""

    mode: Literal["random", "previous_run", "upload"] = Field(
        default="random",
        description="Seed mode: random (new search), previous_run (continue from old run), upload (user JSON)",
    )
    run_id: Optional[str] = Field(
        None,
        description="ID of the previous run to continue from (for 'previous_run' mode)",
    )
    strategies: Optional[List[Dict[str, Any]]] = Field(
        None, description="List of strategy JSONs to use as seeds (for 'upload' mode)"
    )
    top_n: int = Field(
        default=10, ge=1, le=50, description="Number of top strategies to use as seeds"
    )
    keep_structure: bool = Field(
        default=False,
        description="If True, only mutate numeric parameters, preserve block structure",
    )


class GeneticRunProgress(BaseModel):
    current_generation: Optional[int] = None
    total_generations: Optional[int] = None
    best_fitness_so_far: Optional[float] = None
    average_fitness_this_gen: Optional[float] = (
        None  # Corrected from run_genetic_search_task
    )
    status_message: Optional[str] = None  # General status message from the task


class GeneticRunResponse(GeneticRunBase):
    id: uuid.UUID  # Changed from str to uuid.UUID to match model
    user_id: int
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[GeneticRunProgress] = None  # Using the sub-schema
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None  # To store the master Celery task ID

    model_config = ConfigDict(from_attributes=True)


class GeneticRunStatusResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    celery_task_id: Optional[str] = None
    message: Optional[str] = None


# --- FoundStrategy Schemas ---
class FoundStrategyBase(BaseModel):
    rank: int
    strategy_json: Dict[str, Any]
    fitness_score: float
    kpis_json: Dict[str, Any]


class FoundStrategyCreate(FoundStrategyBase):
    run_id: uuid.UUID  # Changed from str to uuid.UUID


class FoundStrategyResponse(FoundStrategyBase):
    id: uuid.UUID  # Changed from str to uuid.UUID
    run_id: uuid.UUID  # Changed from str to uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- DatasetRun Schemas ---
class DatasetRunCreate(BaseModel):
    name: str = Field(
        ..., description="Dataset name, for example, 'My_BTC_Features_2023'"
    )
    symbols: List[str] = Field(
        ..., min_length=1, description="List of symbols to process"
    )
    start_date: str = Field(..., description="Start date in ISO 8601 format")
    end_date: str = Field(..., description="End date in ISO 8601 format")
    feature_data_types: List[str] = Field(
        ..., description="Feature data types, for example, ['kline_1m', 'aggTrade']"
    )
    target_variable: str = Field(..., description="Target variable for prediction")


class DatasetRunResponse(BaseModel):
    id: str
    name: str
    user_id: int
    celery_task_id: Optional[str] = None
    status: str
    parameters_json: Dict[str, Any]
    file_path: Optional[str] = None
    feature_list: Optional[List[str]] = None
    dataset_shape: Optional[Dict[str, int]] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# --- TrainingRun Schemas ---
class TrainingRunCreate(BaseModel):
    dataset_id: str = Field(..., description="ID of the generated dataset")
    model_type: str = Field(
        ..., description="Model type, for example, 'XGBoost', 'River HoeffdingTree'"
    )
    features_to_use: Optional[List[str]] = Field(
        None,
        description="List of features for training. If None - all from dataset are used.",
    )
    hyperparameters: Optional[Dict[str, Any]] = Field(
        None, description="JSON with model hyperparameters"
    )


class TrainingRunResponse(BaseModel):
    id: str
    user_id: int
    dataset_id: str
    celery_task_id: Optional[str] = None
    status: str
    parameters_json: Dict[str, Any]
    model_path: Optional[str] = None
    report_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ModelTrainingReport(BaseModel):
    # This schema will reflect the structure of the JSON report generated by train_offline_model.py
    # This allows easy validation and display on the frontend.
    timestamp_utc: str
    model_save_path: str
    total_steps: int
    active_features_list: List[str]
    final_metrics: Dict[str, Any]
    feature_importance: Optional[Dict[str, float]] = None  # For tree-based models


# AI_CONTEXT_START: DynamicValues
# REFERENCE: DYNAMIC VALUES
# Some parameters in the JSON configuration may not be static values,
# but dynamic references to data available at runtime.
# This allows creating flexible conditions that adapt to the market.
#
# Dynamic reference structure:
# {
#   "source": "SOURCE_TYPE",
#   "key": "DATA_NAME",
#   "shift": SHIFT (for historical data, default 0)
# }
#
# Examples:
#
# 1. Reference to current close price:
#    {"source": "candle", "key": "close", "shift": 0}
#
# 2. Reference to the previous candle's open price:
#    {"source": "candle", "key": "open", "shift": 1}
#
# 3. Reference to RSI indicator value:
#    {"source": "indicator", "key": "RSI_14"}
#
# 4. Reference to the result of another block in the condition tree (by its ID):
#    {"source": "block_result", "block_id": "some_unique_id", "key": "detected_level"}
#
# 5. Reference to the open position state (only in position management blocks):
#    {"source": "position_state", "key": "unrealized_pnl_pct"}
#
# AI should use this structure when user request mentions
# relative or calculated values (e.g. "price above RSI", "SL 2 ATR below").
# AI_CONTEXT_END


# AI_CONTEXT_START: ConditionBlocks
# Base blocks for building the condition tree
class ConditionLeaf(BaseModel):
    """Describes a 'leaf' node in the condition tree (a specific condition)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    params: Dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def assemble_params(cls, data: Any) -> Any:
        """
        This validator checks if the 'params' field is present.
        If not, it gathers all "extra" fields into 'params',
        making the schema resilient to "flat" JSON from AI.
        """
        if isinstance(data, dict) and "params" not in data:
            known_fields = {"id", "type", "params", "children"}
            params_dict = {}
            for key in list(data.keys()):
                if key not in known_fields:
                    params_dict[key] = data.pop(key)
            data["params"] = params_dict
        return data


class ConditionNode(BaseModel):
    """Describes a logical node (AND/OR) in the condition tree."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["AND", "OR"]
    children: List[Union[ConditionLeaf, "ConditionNode"]]


ConditionNode.model_rebuild()  # For handling recursive dependency
# AI_CONTEXT_END


# AI_CONTEXT_START: EntryTriggerBlock
# Block for entry trigger
class EntryTrigger(BaseModel):
    type: Literal["on_candle_close", "on_tick", "on_condition_met"]
    timeframe: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


# AI_CONTEXT_END


# AI_CONTEXT_START: InitializationBlock
# Block for trade initialization
class InitializationBlock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["open_position"]
    params: Dict[str, Any]


# AI_CONTEXT_END


# AI_CONTEXT_START: ManagementBlocks
# Blocks for position management
class DCAManagementBlock(BaseModel):
    """DCA (Dollar Cost Averaging) management block."""

    max_safety_orders: int = Field(5, ge=1)
    volume_multiplier: float = Field(2.0, ge=1.0)
    step_type: Literal["percentage", "custom_condition"] = "percentage"
    step_value: Union[float, Dict[str, Any]] = 1.0


class GridManagementBlock(BaseModel):
    """Grid trading (GRID) block."""

    range_type: Literal["percentage", "atr", "fixed_prices"] = "percentage"
    grid_levels: int = Field(10, ge=2)
    upper_bound: Union[float, Dict[str, Any]]
    lower_bound: Union[float, Dict[str, Any]]


class ManagementBlock(BaseModel):
    """Base class for all position management blocks."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    params: Optional[Dict[str, Any]] = None
    # Add children for conditional blocks
    children: Optional[List[Union["schemas.ConditionNode", "ManagementBlock"]]] = None
    if_conditions: Optional["schemas.ConditionNode"] = None
    then_actions: Optional[List["ManagementBlock"]] = None


# AI_CONTEXT_END


# AI_CONTEXT_START: StrategyV2ConfigDataBlock
# Main schema for 'config_data' field in the new version
class StrategyV2ConfigData(BaseModel):
    enabled: Optional[bool] = True
    strategy_name: str = Field(
        default="VisualBuilderStrategy", description="System name of the strategy"
    )
    symbol: str
    marketType: Literal["FUTURES", "SPOT"]
    signal_source: Literal["internal", "tradingview_webhook"] = "internal"
    min_foundation_weight_threshold: Optional[float] = 0.0
    foundation_weights: Optional[Dict[str, float]] = None
    filters: ConditionNode
    entryTrigger: EntryTrigger
    entryConditions: ConditionNode
    initialization: InitializationBlock
    positionManagement: List[ManagementBlock]
    unsupported_features: Optional[List[str]] = None
    oracle_regime: Optional[int] = None
    oracle_confidence: Optional[float] = None
    use_ml_confirmation: Optional[bool] = False
    breakeven_on_regime_change: Optional[bool] = False


# AI_CONTEXT_END


# NEW SCHEMAS FOR AI ASSISTANT
class GenerateStrategyRequest(BaseModel):
    text_prompt: str = Field(
        ..., description="Text description of the strategy from the user."
    )
    current_config_json: Optional[Dict[str, Any]] = Field(
        None, description="Complete current strategy configuration for modification."
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="Additional context for future improvements."
    )


class TradingViewWebhookPayloadBase(BaseModel):
    action: Literal["buy", "sell"]
    symbol: str
    api_key_id: Optional[int] = None
    event_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    price: Optional[float] = None
    timeframe: Optional[str] = None
    bar_time: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TradingViewWebhookPayload(TradingViewWebhookPayloadBase):
    strategy_id: str


class TradingViewStrategyScopedWebhookPayload(TradingViewWebhookPayloadBase):
    strategy_id: Optional[str] = None


class TradingViewWebhookTestRequest(BaseModel):
    config_id: str
    action: Literal["buy", "sell"]
    api_key_id: Optional[int] = None


class TradingViewWebhookStatus(BaseModel):
    config_id: str
    status: str
    updated_at: str
    message: Optional[str] = None
    source: Optional[str] = None
    action: Optional[str] = None
    symbol: Optional[str] = None
    event_id: Optional[str] = None
    api_key_id: Optional[int] = None
    trace: Optional[Dict[str, Any]] = None


class TradingViewWebhookInfo(BaseModel):
    url: str
    user_secret_token_masked: str
    sample_payload: Dict[str, Any]
    requires_strategy_id: bool = True
    strategy_id: Optional[str] = None
    symbol: Optional[str] = None


class AIChatRequest(BaseModel):
    text_prompt: str
    session_id: str
    backtest_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    strategy_json: Optional[Dict[str, Any]] = None
    mode: Optional[str] = (
        "advisor"  # 'advisor' or 'generator' # [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    )
    analytics_context: Optional[Dict[str, Any]] = None

    # NEW FIELDS FOR VISION
    image_base64: Optional[str] = Field(
        None,
        description="Chart image in raw base64 format (JPEG/PNG/WebP). Data URL is also accepted for backward compatibility.",
    )
    image_mime_type: Optional[str] = Field(
        None, description="MIME type of the image, e.g. 'image/jpeg'"
    )


class AIChatResponse(BaseModel):
    text_response: str
    session_id: str
    strategy_json: Optional[Dict[str, Any]] = None


class AIChatMessageBase(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None


class AIChatMessageCreate(AIChatMessageBase):
    session_id: str


class AIChatMessage(AIChatMessageBase):
    id: str
    user_id: int
    session_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIChatInitSessionRequest(BaseModel):
    session_id: str
    initial_message: str


# --- END: NEW SCHEMAS FOR AI ASSISTANT ---


# AI_CONTEXT_START: StrategyConfigBlock
# --- StrategyConfig Schemas ---
# 1. New schema for describing a strategy template (for "Library")
class StrategyTemplate(BaseModel):
    name: str
    description: str
    default_params: Dict[str, Any]


# 2. Update existing StrategyConfig schemas
class StrategyConfigBase(BaseModel):
    name: str
    description: Optional[str] = None
    config_data: Union[StrategyV2ConfigData, Dict[str, Any]]
    symbol_selection_mode: str = "DYNAMIC"
    symbols: Optional[List[str]] = None
    use_ml_confirmation: bool = False
    foundation_weights: Optional[Dict[str, float]] = None
    oracle_regime: Optional[int] = None
    oracle_confidence: Optional[float] = None


class StrategyConfigCreate(StrategyConfigBase):
    pass


class StrategyConfigUpdate(BaseModel):  # Make all fields optional for PUT/PATCH
    name: Optional[str] = None
    description: Optional[str] = None
    config_data: Optional[Union[StrategyV2ConfigData, Dict[str, Any]]] = None
    symbol_selection_mode: Optional[str] = None
    symbols: Optional[List[str]] = None
    use_ml_confirmation: Optional[bool] = None
    foundation_weights: Optional[Dict[str, float]] = None
    oracle_regime: Optional[int] = None
    oracle_confidence: Optional[float] = None


class StrategyConfig(StrategyConfigBase):
    id: str
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# AI_CONTEXT_END


class QuotaStatus(BaseModel):
    name: str
    used: int
    limit: int
    period: Literal["day", "month", "week"]


class BonusInfo(BaseModel):
    """User bonuses information"""

    feature_name: str
    quantity: int
    status: str

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class AccountStatusData(BaseModel):
    plan_name: str = Field(..., alias="planName")
    plan_expires_at: Optional[datetime] = Field(None, alias="planExpiresAt")
    quotas: List[QuotaStatus]
    bonuses: List[BonusInfo] = []
    referral_program: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class AppConfigUpdate(BaseModel):
    """Schema for partial application configuration update."""

    risk_management: Optional[RiskManagementSettings] = None
    backtest_risk_management: Optional[BacktestRiskManagementSettings] = None
    notifications: Optional[NotificationSettings] = None
    data_sources: Optional[Dict[str, Any]] = None
    exchange_settings: Optional[ExchangeSettings] = None
    status_message: Optional[str] = None  # For UI feedback

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SymbolSelectionConfig(BaseModel):
    mode: Literal["STATIC", "DYNAMIC_NATR", "DYNAMIC_ORACLE"] = "STATIC"
    min_natr: Optional[float] = Field(0.0, ge=0.0, le=10.0)
    oracle_regime: Optional[Literal[0, 1, 2]] = (
        None  # 0: Amnesia, 1: Paranoia, 2: Schizophrenia
    )
    oracle_confidence: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    max_concurrent_symbols: int = Field(1, ge=1)

    @model_validator(mode="after")
    def validate_dynamic_modes(self):
        if self.mode == "DYNAMIC_NATR":
            if self.min_natr is None:
                raise ValueError("min_natr must be provided for DYNAMIC_NATR mode")
        elif self.mode == "DYNAMIC_ORACLE":
            if self.oracle_regime is None:
                raise ValueError(
                    "oracle_regime must be provided for DYNAMIC_ORACLE mode"
                )
            if self.oracle_confidence is None:
                raise ValueError(
                    "oracle_confidence must be provided for DYNAMIC_ORACLE mode"
                )
        return self


# --- Affiliate Program Schemas ---


class Commission(BaseModel):
    id: str
    affiliate_user_id: int
    referred_user_id: int = Field(
        ..., validation_alias="referred_user_id", serialization_alias="referralId"
    )
    source_payment_id: str
    amount: float = Field(
        ..., validation_alias="commission_amount_usd", serialization_alias="amount"
    )
    status: str
    description: Optional[str] = "Subscription Payment"
    created_at: datetime
    becomes_available_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AffiliateStats(BaseModel):
    referral_count: int
    paying_referral_count: int
    total_earnings: float


class AffiliateWithStats(User):
    stats: AffiliateStats


class PaginatedCommissions(BaseModel):
    total: int
    commissions: List[Commission]


class AffiliateDashboardStats(BaseModel):
    pending_amount: float
    available_amount: float
    total_paid_out: float
    clicks: int  # For now it will be 0, but serves as preparation for the future
    registrations: int
    paying_customers: int

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AffiliateReferral(BaseModel):
    id: int
    username: str
    registered_at: datetime = Field(
        ..., validation_alias="created_at", serialization_alias="registeredAt"
    )
    is_paying: bool

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AdminAffiliateReferral(BaseModel):
    id: int
    username: str
    email: str
    registered_at: datetime = Field(
        ..., validation_alias="created_at", serialization_alias="registeredAt"
    )
    plan: str

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PaginatedAdminAffiliateReferrals(BaseModel):
    total: int
    referrals: List[AdminAffiliateReferral]


class PaginatedAffiliateReferrals(BaseModel):
    total: int
    referrals: List[AffiliateReferral]


class AffiliatePayout(BaseModel):
    id: str
    created_at: datetime
    amount: float
    status: str
    transaction_id: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PaginatedAffiliatePayouts(BaseModel):
    total: int
    payouts: List[AffiliatePayout]


class PayoutDetailsPayload(BaseModel):
    usdt_trc20_address: str = Field(..., alias="usdtTrc20Address")


# --- Admin Schemas ---


class AdminUserUpdate(BaseModel):
    """Schema for updating user data by administrator."""

    plan: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
    affiliate_commission_rate: Optional[float] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AdminBonusCreate(BaseModel):
    """Schema for granting a bonus to a user."""

    feature_name: str
    quantity: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DashboardStats(BaseModel):
    """Schema for the dashboard statistics response."""

    new_users_last_7_days: int
    tasks_run_last_7_days: int
    task_counts_by_type: Dict[str, int]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Bonus(BaseModel):
    id: int
    user_id: int
    feature_name: str
    quantity: int
    status: str
    source_user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class AdminUserExtendedDetails(BaseModel):
    """Schema for extended user info in admin panel."""

    user: User
    recent_tasks: List["Task"]
    paper_wallets: List[PaperWallet]

    bonuses: List[Bonus]  # Was: List[Any]

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AvailableBonus(BaseModel):
    """Schema for describing a bonus available for granting."""

    feature_name: str
    description: str
    default_quantity: int

    # ADD THIS BLOCK
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # Allows accepting both snake_case and camelCase
    )


class FoundationStat(BaseModel):
    foundation_id: str
    count: int
    avg_win_rate_contribution: float
    total_gross_profit: float
    total_gross_loss: float
    profit_factor: float

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MarketSentimentStat(BaseModel):
    direction: str
    total_pnl: float

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --- Schemas for Foundation Visualizer ---


class VisualizationLevel(BaseModel):
    time: int
    price: float
    type: str
    label: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class VisualizationMarker(BaseModel):
    time: int
    type: str  # Added field
    position: str
    color: str
    shape: str
    text: Optional[str] = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class VisualizationZone(BaseModel):
    start_time: int
    end_time: int
    type: str
    label: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class KlineForChart(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float  # Add volume


class VisualizationsData(BaseModel):
    levels: List[VisualizationLevel]
    markers: List[VisualizationMarker]
    zones: List[VisualizationZone]
    subcharts: Dict[str, Any]


class FoundationPreviewResponse(BaseModel):
    klines: List[KlineForChart]
    visualizations: VisualizationsData


class Achievement(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    xp_reward: int
    rarity: str

    model_config = ConfigDict(from_attributes=True)


class UserAchievement(BaseModel):
    id: int
    user_id: int
    achievement_id: str
    unlocked_at: datetime
    achievement: Achievement

    model_config = ConfigDict(from_attributes=True)


class LeaderboardEntry(BaseModel):
    id: str
    rank: int
    score: float
    user: User
    backtest_run_id: str
    shared_backtest_slug: str
    is_config_public: bool = False
    meta_data: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        from_attributes=True, alias_generator=to_camel, populate_by_name=True
    )


# Genome Project Schemas


class GeneBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    components: List[str]
    rarity: float
    discovered_at: datetime
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        from_attributes=True, alias_generator=to_camel, populate_by_name=True
    )


class Gene(GeneBase):
    first_discovered_by: Optional[int] = None


class UserGeneBase(BaseModel):
    gene_id: str
    unlocked_at: datetime
    source_strategy_id: Optional[str] = None
    source_type: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True, alias_generator=to_camel, populate_by_name=True
    )


class UserGene(UserGeneBase):
    id: int
    user_id: int
    gene: Gene


class UserGenesResponse(BaseModel):
    total: int
    genes: List[UserGene]


class GeneStatsResponse(BaseModel):
    total_genes_discovered: int
    total_genes_in_system: int
    rarity_breakdown: Dict[str, int]  # COMMON, RARE, EPIC, LEGENDARY
    recent_discoveries: List[UserGene]


# Evolution Tree Schemas
class StrategyNode(BaseModel):
    id: str
    name: str
    generation: int
    source_mutation: Optional[str] = None
    created_at: Optional[str] = None
    is_current: bool = False


class StrategyEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(populate_by_name=True)


class StrategyLineageResponse(BaseModel):
    nodes: List[StrategyNode]
    edges: List[StrategyEdge]
    root_id: str


class RootStrategy(BaseModel):
    id: str
    name: str
    generation: int
    created_at: datetime
    descendants_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# Strategy Breeding Schemas
class StrategyBreedRequest(BaseModel):
    parent_a_id: str
    parent_b_id: str
    mode: str  # 'entry_a_exit_b', 'entry_b_exit_a', 'filters_a_entry_b', 'filters_b_entry_a', 'balanced_merge', 'best_of_both'
    mutation_rate: Optional[float] = 0.1  # 0.0 to 1.0

    @field_validator("mutation_rate")
    @classmethod
    def validate_mutation_rate(cls, v):
        if v < 0.0 or v > 1.0:
            raise ValueError("mutation_rate must be between 0.0 and 1.0")
        return v


class StrategyBreedResponse(BaseModel):
    hybrid_config: StrategyV2ConfigData
    parent_a_name: str
    parent_b_name: str
    mode: str
    suggested_name: str


# ==============================================================================
# Phantom Trade Tracker Schemas (Post-BE Analysis)
# ==============================================================================


class PhantomTradeBase(BaseModel):
    """Base schema for a phantom trade."""

    real_trade_id: str
    symbol: str
    direction: str
    entry_price: float
    entry_time: datetime
    initial_stop_loss: float
    initial_take_profit: float
    be_trigger_time: datetime
    be_exit_price: float
    real_pnl_pct: float
    real_pnl_usd: Optional[float] = None

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PhantomTradeResponse(PhantomTradeBase):
    """Full schema of a phantom trade for API response."""

    id: int
    user_id: int
    strategy_config_id: Optional[str] = None
    phantom_status: str  # TRACKING, TP_HIT, SL_HIT, TIMEOUT
    phantom_exit_time: Optional[datetime] = None
    phantom_exit_price: Optional[float] = None
    phantom_pnl_pct: Optional[float] = None
    phantom_pnl_usd: Optional[float] = None
    mfe_after_be: Optional[float] = None  # Maximum Favorable Excursion
    mae_after_be: Optional[float] = None  # Maximum Adverse Excursion
    mfe_price: Optional[float] = None
    mae_price: Optional[float] = None
    candles_to_resolution: Optional[int] = None
    timeout_candles: Optional[int] = None
    created_at: datetime


class BEStatsByOutcome(BaseModel):
    """Statistics for a single outcome (TP_HIT, SL_HIT, TIMEOUT)."""

    count: int
    avg_phantom_pnl_pct: float
    total_phantom_pnl_pct: float
    avg_candles_to_resolution: Optional[float] = None


class BEAnalysisStats(BaseModel):
    """Aggregated statistics for BE-trades."""

    total_be_trades: int
    tp_would_hit: int  # BE "stole" profit
    sl_would_hit: int  # BE "saved" from loss
    timeout: int  # Reached neither TP nor SL

    # Key metrics
    be_saved_pct: float  # % of trades where BE saved from loss
    be_stolen_pct: float  # % of trades where BE stole profit

    # Average values
    avg_mfe_after_be: float  # Average MFE after BE
    avg_mae_after_be: float  # Average MAE after BE
    avg_phantom_pnl_if_tp: float  # Average potential PnL for TP_HIT
    avg_phantom_pnl_if_sl: float  # Average potential PnL for SL_HIT

    # Breakdown by outcomes
    by_outcome: Dict[str, BEStatsByOutcome]

    # Data-driven recommendations
    recommendation: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class BEScatterDataPoint(BaseModel):
    """A single point for a scatter plot."""

    trade_id: str
    symbol: str
    direction: str
    entry_time: datetime
    phantom_status: str
    real_pnl_pct: float
    phantom_pnl_pct: Optional[float] = None
    mfe_after_be: Optional[float] = None
    mae_after_be: Optional[float] = None
    candles_to_resolution: Optional[int] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class BEScatterDataResponse(BaseModel):
    """Data for scatter plots on the BE Analysis page."""

    points: List[BEScatterDataPoint]

    # Aggregates for visualization
    total_points: int
    avg_mfe: float
    avg_mae: float

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PaginatedPhantomTradesResponse(BaseModel):
    """Paginated response with a list of phantom trades."""

    total: int
    trades: List[PhantomTradeResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TelegramBindingLink(BaseModel):
    url: str


class BlockRestrictionsConfig(BaseModel):
    pro_only: List[str]
    kline_only: List[str]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Federation Hub Schemas ---
class HubStrategy(BaseModel):
    name: str
    author: str
    tags: List[str]
    description: str
    strategy_json: Dict[str, Any]


class HubStrategyResponse(HubStrategy):
    id: int
    model_config = ConfigDict(from_attributes=True)


class HubNews(BaseModel):
    title: str
    date: str
    text: str
    is_pinned: Optional[bool] = False


class HubNewsResponse(HubNews):
    id: int
    likes_count: int = 0
    comments_count: int = 0
    is_pinned: bool = False
    model_config = ConfigDict(from_attributes=True)


class HubNewsCommentCreate(BaseModel):
    author_name: str = Field(..., max_length=50)
    text: str = Field(..., max_length=1000)


class HubNewsCommentResponse(BaseModel):
    id: int
    news_id: int
    author_name: str
    text: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HubFeedbackCreate(BaseModel):
    category: str = Field(..., max_length=50)
    text: str
    contact_email: Optional[str] = Field(None, max_length=255)


class HubTopicCreate(BaseModel):
    topic_type: Literal["strategy", "discussion"]
    title: str = Field(..., max_length=255)
    description: str
    author_name: str = Field(..., max_length=50)
    symbol: Optional[str] = Field(None, max_length=50)
    period_start: Optional[str] = Field(None, max_length=50)
    period_end: Optional[str] = Field(None, max_length=50)
    kpis: Optional[Dict[str, Any]] = None
    equity_curve: Optional[List[Any]] = None
    strategy_json: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class HubTopicResponse(BaseModel):
    id: str
    topic_type: Literal["strategy", "discussion"]
    title: str
    description: str
    author_name: str
    symbol: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    kpis: Optional[Dict[str, Any]] = None
    equity_curve: Optional[List[Any]] = None
    strategy_json: Optional[Dict[str, Any]] = None
    likes_count: int
    comments_count: int = 0
    is_verified: bool = False
    tags: Optional[List[str]] = None
    created_at: datetime

    @computed_field
    @property
    def name(self) -> str:
        return self.title

    @computed_field
    @property
    def author(self) -> str:
        return self.author_name

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class HubTopicCreateResponse(HubTopicResponse):
    delete_token: Optional[str] = None


class HubCommentCreate(BaseModel):
    author_name: str = Field(..., max_length=50)
    text: str


class HubCommentResponse(BaseModel):
    id: int
    topic_id: str
    author_name: str
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class HubNodeRegister(BaseModel):
    node_uuid: str = Field(..., max_length=36)
    name: str = Field(..., max_length=100)
    node_secret: str = Field(..., max_length=255)
    version: Optional[str] = Field(None, max_length=50)


class HubNodePing(BaseModel):
    latency_ms: float
    version: Optional[str] = Field(None, max_length=50)


class HubNodeResponse(BaseModel):
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    country: Optional[str] = None
    latency_ms: Optional[float] = None
    version: Optional[str] = None
    is_master: bool = False


class ClientConfigurationModel(BaseModel):
    risk_management: RiskManagementSettings
    exchange_settings: ExchangeSettings
    notifications: Optional[NotificationSettings] = None
    data_sources: Optional[Dict[str, Any]] = None


class TaskStatusEnum(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskResponse(BaseModel):
    task_id: str = Field(
        ..., json_schema_extra={"example": "d290f1ee-6c54-4b01-90e6-d701748f0851"}
    )
    status: TaskStatusEnum = Field(..., json_schema_extra={"example": "pending"})
    message: str = Field(
        ..., json_schema_extra={"example": "Task has been queued for execution."}
    )


class ComponentStatus(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "database_connection"})
    status: str = Field(..., json_schema_extra={"example": "ok"})


class SystemStatus(BaseModel):
    status: str = Field(..., json_schema_extra={"example": "ok"})
    version: str = Field(..., json_schema_extra={"example": "1.0.0"})
    timestamp_utc: datetime = Field(
        ..., json_schema_extra={"example": "2024-06-14T12:00:00Z"}
    )
    components: List[ComponentStatus]


class SystemMetrics(BaseModel):
    average_response_time_ms: float
    uptime_30_days_percent: float
    total_requests_24h: int
    error_rate_24h: float


class SymbolPayload(BaseModel):
    symbol: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AddToBlacklistPayload(BaseModel):
    """Payload for adding a coin to the blacklist."""

    symbol: str
    duration: Optional[Literal["end_of_day", "permanent", "custom"]] = "permanent"
    custom_until: Optional[datetime] = None  # Used only if duration == "custom"
    reason: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class UpdateAutoBlacklistRulesPayload(BaseModel):
    """Payload for updating automatic block rules."""

    autoRules: List[AutoBlacklistRule] = Field(default_factory=list)
