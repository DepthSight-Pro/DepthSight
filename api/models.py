# ruff: noqa: E402
# api/models.py
import enum
import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Text,
    UniqueConstraint,
    Enum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
from datetime import datetime, timezone


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    plan = Column(String, default="free", nullable=False)
    plan_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Gamification fields
    xp = Column(Integer, default=0, nullable=False, server_default="0")
    level = Column(Integer, default=1, nullable=False, server_default="1")

    # AFFILIATE PROGRAM FIELDS
    role = Column(String, nullable=False, server_default="user")  # Reverted from Enum
    affiliate_commission_rate = Column(Float, nullable=True)

    # ADMIN FIELDS
    admin_notes = Column(Text, nullable=True)

    # PUSH NOTIFICATIONS
    push_subscription = Column(JSON, nullable=True)

    # SYMBOL SELECTION CONFIG
    symbol_selection_config = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    referral_code = Column(String, unique=True, index=True, nullable=True)
    tradingview_webhook_token = Column(String, unique=True, index=True, nullable=True)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    config = relationship(
        "AppConfig", back_populates="user", uselist=False, lazy="selectin"
    )
    api_keys = relationship("ApiKey", back_populates="user", lazy="selectin")
    backtest_runs = relationship(
        "BacktestRun",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    strategy_configs = relationship(
        "StrategyConfig", back_populates="owner", lazy="selectin"
    )
    genetic_runs = relationship(
        "GeneticRun",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    bonuses = relationship(
        "Bonus",
        back_populates="user",
        foreign_keys="[Bonus.user_id]",
        cascade="all, delete-orphan",
    )
    achievements = relationship("UserAchievement", back_populates="user")
    ai_chat_messages = relationship(
        "AIChatMessage", back_populates="user", cascade="all, delete-orphan"
    )
    support_tickets = relationship(
        "SupportTicket", back_populates="user", cascade="all, delete-orphan"
    )

    # Relationship to track who invited whom
    referrer = relationship(
        "User", remote_side=[id], foreign_keys=[referred_by_user_id]
    )

    # AFFILIATE PROGRAM RELATIONSHIPS
    referrals = relationship(
        "User", back_populates="referrer", foreign_keys=[referred_by_user_id]
    )
    commissions = relationship(
        "Commission",
        back_populates="affiliate",
        foreign_keys="[Commission.affiliate_user_id]",
    )


class AIChatMessage(Base):
    __tablename__ = "ai_chat_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), nullable=False, index=True)
    role = Column(String(10), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Vision fields
    image_base64 = Column(Text, nullable=True)
    image_mime_type = Column(String(50), nullable=True)

    user = relationship("User", back_populates="ai_chat_messages")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    bitcart_id = Column(
        "nowpayments_payment_id", String, nullable=True, index=True
    )  # Bitcart invoice ID (mapped to the old column)
    plan_name = Column(String, nullable=False)  # 'standard' or 'pro'
    amount_usd = Column(Float, nullable=False)

    # Statuses: PENDING, FINISHED, FAILED, EXPIRED
    status = Column(String, default="PENDING", nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    commission = relationship(
        "Commission", back_populates="source_payment", uselist=False
    )


# -- AFFILIATE PROGRAM MODEL --
class Commission(Base):
    __tablename__ = "commissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    affiliate_user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    referred_user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    source_payment_id = Column(
        String, ForeignKey("payments.id"), nullable=False, index=True
    )
    commission_amount_usd = Column(Float, nullable=False)
    status = Column(
        String, nullable=False, index=True, default="pending"
    )  # Reverted from Enum
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    becomes_available_at = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    affiliate = relationship(
        "User", foreign_keys=[affiliate_user_id], back_populates="commissions"
    )
    referred_user = relationship("User", foreign_keys=[referred_user_id])
    source_payment = relationship("Payment", back_populates="commission")


class AffiliatePayout(Base):
    __tablename__ = "affiliate_payouts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    status = Column(
        String, default="pending", nullable=False
    )  # pending, paid, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    transaction_id = Column(String, nullable=True)
    payout_address = Column(String, nullable=True)

    user = relationship("User")


class AppConfig(Base):
    __tablename__ = "app_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    risk_management = Column(JSON, nullable=False)
    backtest_risk_management = Column(JSON, nullable=True)
    notifications = Column(JSON, nullable=False)
    data_sources = Column(JSON, nullable=False)
    exchange_settings = Column(JSON, nullable=True)

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="config", lazy="selectin")


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    config_data = Column(JSON, nullable=False)
    symbol_selection_mode = Column(String, default="DYNAMIC", nullable=False)
    symbols = Column(JSON, nullable=True)
    use_ml_confirmation = Column(Boolean, default=False, nullable=False)
    foundation_weights = Column(JSON, nullable=True, server_default="{}")

    # Oracle Filter fields
    oracle_regime = Column(Integer, nullable=True)
    oracle_confidence = Column(Float, nullable=True)

    # Genome Project fields
    parent_strategy_id = Column(
        String,
        ForeignKey("strategy_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation = Column(Integer, default=1, nullable=False, server_default="1")
    source_mutation = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner = relationship("User", back_populates="strategy_configs")
    parent = relationship(
        "StrategyConfig",
        remote_side=[id],
        foreign_keys=[parent_strategy_id],
        lazy="selectin",
    )
    children = relationship(
        "StrategyConfig",
        back_populates="parent",
        foreign_keys=[parent_strategy_id],
        lazy="selectin",
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    name = Column(String, nullable=False)
    # IMPORTANT: Store keys encrypted (Fernet AES-128-CBC + HMAC)
    encrypted_api_key = Column(String, nullable=False)
    encrypted_api_secret = Column(String, nullable=False)
    # SHA-256 hash for deterministic search of duplicates
    # (Fernet encryption is non-deterministic — each encrypt() yields a different result)
    api_key_hash = Column(String(64), nullable=True, unique=True, index=True)
    key_prefix = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    status = Column(String, default="untested")
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys", lazy="selectin")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    trade_uuid = Column(String, unique=True, index=True, nullable=False)
    timestamp_close = Column(DateTime(timezone=True), nullable=False, index=True)
    symbol = Column(String, index=True)
    strategy_config_id = Column(
        String,
        ForeignKey("strategy_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    direction = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    commission = Column(Float)
    exit_reason = Column(String)
    quantity = Column(Float)
    trade_mode = Column(String(10), nullable=False, server_default="LIVE", index=True)
    api_key_id = Column(
        Integer,
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # New fields for grouping partial exits
    position_entry_id = Column(
        String, index=True, nullable=True
    )  # entry_client_order_id from position
    exit_type = Column(
        String, nullable=True
    )  # PARTIAL_TP, FINAL_TP, STOP_LOSS, MANUAL, etc.
    is_final_exit = Column(
        Boolean, nullable=True, server_default="false"
    )  # Final exit from position

    # Signal details with decision trace for analytics
    signal_details_json = Column(
        JSON, nullable=True
    )  # Contains decision_trace for foundation analytics

    # Timestamp of entry for accurate trade timing
    timestamp_signal = Column(
        DateTime(timezone=True), nullable=True
    )  # When signal was generated
    timestamp_entry = Column(
        DateTime(timezone=True), nullable=True
    )  # When position was actually opened

    # Maximum floating profit and loss during the trade (for analytics)
    max_floating_profit = Column(
        Float, nullable=True
    )  # MFP - Maximum floating profit in USD
    max_floating_loss = Column(
        Float, nullable=True
    )  # MFL - Maximum floating loss in USD

    strategy_config = relationship("StrategyConfig")
    api_key = relationship("ApiKey", lazy="selectin")

    @property
    def exchange(self) -> str:
        return self.api_key.exchange if self.api_key else "binance"


from sqlalchemy.types import JSON


class TradeAnalytics(Base):
    __tablename__ = "trade_analytics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    source_type = Column(String)  # 'backtest' or 'live'
    source_trade_id = Column(String)
    strategy_config_id = Column(
        String, ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True
    )
    symbol = Column(String, index=True)
    direction = Column(String)
    timestamp_close = Column(DateTime(timezone=True), index=True)
    pnl_usd = Column(Float)
    win_rate_contribution = Column(Integer)
    profit_factor_gross_profit = Column(Float)
    profit_factor_gross_loss = Column(Float)
    used_foundations = Column(JSON)
    used_filters = Column(JSON)
    used_indicators = Column(JSON)  # New field for indicators
    used_management_blocks = Column(JSON)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    task_id = Column(String, unique=True, index=True, nullable=False)
    task_type = Column(String)  # 'backtest' or 'optimization'
    status = Column(String, default="PENDING")
    parameters = Column(JSON)
    results = Column(JSON, nullable=True)
    error_message = Column(String, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class BacktestRun(Base):
    """Stores metadata of each backtest run."""

    __tablename__ = "backtest_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String, ForeignKey("tasks.task_id"), nullable=False, index=True)

    strategy_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    market_type = Column(String, nullable=False, default="futures_usdtm")
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    initial_balance = Column(Float, nullable=False)
    parameters_json = Column(JSON, nullable=False)

    status = Column(String, default="PENDING", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    kpi_results_json = Column(JSON, nullable=True)
    error_message = Column(String, nullable=True)
    equity_curve_json = Column(JSON, nullable=True)
    analytics_report_json = Column(JSON, nullable=True)

    user = relationship("User", back_populates="backtest_runs")
    task = relationship("Task")
    trades = relationship(
        "BacktestTrade", back_populates="backtest_run", cascade="all, delete-orphan"
    )


class BacktestTradeExecution(Base):
    """Stores a single partial execution (fill) within a trade."""

    __tablename__ = "backtest_trade_executions"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(
        Integer, ForeignKey("backtest_trades.id"), nullable=False, index=True
    )

    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    # Ensure the field name is 'price', not something else.
    price = Column(Float, nullable=False)

    quantity = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # 'ENTRY' or 'EXIT'

    # Relationship with BacktestTrade
    trade = relationship("BacktestTrade", back_populates="executions")


class BacktestTrade(Base):
    """Stores each individual trade from a backtest."""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True)
    backtest_run_id = Column(
        String, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    client_order_id = Column(String, unique=True, nullable=False, index=True)

    direction = Column(String, nullable=False)
    timestamp_entry = Column(DateTime(timezone=True), nullable=False, index=True)
    timestamp_exit = Column(DateTime(timezone=True), nullable=False)

    entry_price = Column(Float)
    exit_price = Column(Float)
    quantity = Column(Float)
    pnl = Column(Float)
    commission = Column(Float)
    exit_reason = Column(String)

    # Key field for storing the decision tree
    decision_trace_json = Column(JSON)

    # New L2 detail fields
    l2_ideal_entry_price = Column(Float, nullable=True)
    l2_entry_slippage_usd = Column(Float, nullable=True)
    l2_entry_filled_quantity = Column(Float, nullable=True)
    l2_ideal_exit_price = Column(Float, nullable=True)
    l2_exit_slippage_usd = Column(Float, nullable=True)
    l2_filled_qty_at_exit = Column(Float, nullable=True)

    backtest_run = relationship("BacktestRun", back_populates="trades")
    executions = relationship(
        "BacktestTradeExecution",
        back_populates="trade",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GeneticRun(Base):
    __tablename__ = "genetic_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    celery_task_id = Column(String, nullable=True, index=True)  # Task ID from Celery
    status = Column(
        String, index=True, nullable=False, default="PENDING"
    )  # PENDING, RUNNING, COMPLETED, FAILED, STOPPED
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    config_json = Column(JSON, nullable=False)  # Parameters of the run
    progress = Column(
        JSON, nullable=True
    )  # Live progress data: {current_generation, total_generations, best_fitness_so_far, average_fitness}
    error_message = Column(
        Text, nullable=True
    )  # For storing error messages if status is FAILED

    user = relationship("User", back_populates="genetic_runs")
    found_strategies = relationship(
        "FoundStrategy",
        back_populates="genetic_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class FoundStrategy(Base):
    __tablename__ = "found_strategies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey("genetic_runs.id"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)  # Rank in the hall of fame
    strategy_json = Column(JSON, nullable=False)  # Full configuration of the strategy
    fitness_score = Column(Float, nullable=False)
    kpis_json = Column(JSON, nullable=False)  # Full KPIs from DepthSightBacktester
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    genetic_run = relationship("GeneticRun", back_populates="found_strategies")


class DatasetRun(Base):
    """Stores metadata of the dataset generation task."""

    __tablename__ = "dataset_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)  # Name specified by the user
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    celery_task_id = Column(String, nullable=True, index=True)

    status = Column(
        String, default="PENDING", index=True
    )  # PENDING, RUNNING, COMPLETED, FAILED
    parameters_json = Column(
        JSON, nullable=False
    )  # Parameters: symbols, period, data types, target

    file_path = Column(
        String, nullable=True
    )  # Path to the dataset file (.csv or .parquet)
    feature_list = Column(JSON, nullable=True)  # List of generated features
    dataset_shape = Column(JSON, nullable=True)  # {'rows': 10000, 'cols': 25}
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    training_runs = relationship(
        "TrainingRun", back_populates="dataset", cascade="all, delete-orphan"
    )


class TrainingRun(Base):
    """Stores metadata and results of the model training task."""

    __tablename__ = "training_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(
        String, ForeignKey("dataset_runs.id"), nullable=False, index=True
    )
    celery_task_id = Column(String, nullable=True, index=True)

    status = Column(
        String, default="PENDING", index=True
    )  # PENDING, RUNNING, COMPLETED, FAILED
    parameters_json = Column(
        JSON, nullable=False
    )  # Parameters: model type, selected features, hyperparameters

    model_path = Column(
        String, nullable=True
    )  # Path to the model artifact (.joblib, .pkl)
    report_path = Column(String, nullable=True)  # Path to the JSON report with metrics
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    dataset = relationship("DatasetRun", back_populates="training_runs")


class SymbolStrategyPerformance(Base):
    __tablename__ = "symbol_strategy_performance"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    strategy_name = Column(String, nullable=False, index=True)
    total_pnl_usd = Column(Float, nullable=False, default=0.0, server_default="0.0")

    # Data from the SymbolStrategyPerformanceStats class
    trade_results_buffer_json = Column(
        JSON, nullable=False
    )  # Store deque as JSON array
    current_risk_multiplier_index = Column(Integer, nullable=False)
    last_penalty_timestamp = Column(Float, nullable=False)
    total_trades_for_assessment = Column(Integer, nullable=False)

    # Add unique composite key
    __table_args__ = (
        UniqueConstraint(
            "user_id", "symbol", "strategy_name", name="_user_symbol_strategy_uc"
        ),
    )


class Bonus(Base):
    __tablename__ = "bonuses"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    feature_name = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    status = Column(String, nullable=False, index=True)  # pending, active
    source_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="bonuses", foreign_keys=[user_id])
    source_user = relationship("User", foreign_keys=[source_user_id])


class PaperWallet(Base):
    __tablename__ = "paper_wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    asset = Column(String(20), nullable=False)
    balance = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "asset", name="_user_asset_uc"),)


class SharedBacktest(Base):
    __tablename__ = "shared_backtests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    backtest_run_id = Column(
        String, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Unique, unpredictable identifier for public link
    public_slug = Column(
        String,
        unique=True,
        index=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex[:12],
    )

    # Privacy settings
    is_strategy_name_public = Column(Boolean, default=True, nullable=False)
    are_parameters_public = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(
        Boolean, default=True, nullable=False
    )  # For ability to deactivate the link

    backtest_run = relationship("BacktestRun")
    user = relationship("User")


# New Gamification Models


class Rarity(enum.Enum):
    COMMON = "COMMON"
    RARE = "RARE"
    EPIC = "EPIC"
    LEGENDARY = "LEGENDARY"


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    icon = Column(String, nullable=False)
    xp_reward = Column(Integer, nullable=False)
    rarity = Column(Enum(Rarity), nullable=False)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    achievement_id = Column(String, ForeignKey("achievements.id"), nullable=False)
    unlocked_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="achievements")
    achievement = relationship("Achievement")

    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="_user_achievement_uc"),
    )


class LeaderboardPeriod(enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ALL_TIME = "all_time"


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    backtest_run_id = Column(String, ForeignKey("backtest_runs.id"), nullable=False)
    shared_backtest_slug = Column(
        String, ForeignKey("shared_backtests.public_slug"), nullable=False
    )
    period = Column(Enum(LeaderboardPeriod), nullable=False)
    category = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    meta_data = Column(JSON, nullable=True)

    user = relationship("User")
    backtest_run = relationship("BacktestRun")
    shared_backtest = relationship("SharedBacktest")

    @property
    def is_config_public(self) -> bool:
        return (
            self.shared_backtest.are_parameters_public
            if self.shared_backtest
            else False
        )


# Genome Project Models


class Gene(Base):
    """Reference book of discovered genes (successful component combinations)."""

    __tablename__ = "genes"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    components = Column(JSON, nullable=False)
    rarity = Column(Float, nullable=False, default=100.0)

    metadata_json = Column(
        "metadata", JSON, nullable=True
    )  # Rename attribute, but keep column name in DB
    # Or, if migration has not been created yet:
    # metadata_json = Column(JSON, nullable=True) # Just rename

    first_discovered_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())

    first_discoverer = relationship("User")
    user_genes = relationship(
        "UserGene", back_populates="gene", cascade="all, delete-orphan"
    )


class UserGene(Base):
    """User's personal gene library."""

    __tablename__ = "user_genes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    gene_id = Column(String, ForeignKey("genes.id"), nullable=False, index=True)
    unlocked_at = Column(DateTime(timezone=True), server_default=func.now())
    source_strategy_id = Column(
        String, ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True
    )
    source_type = Column(
        String, nullable=True
    )  # 'manual', 'discovery_lab', 'optimizer', 'hybrid'

    user = relationship("User")
    gene = relationship("Gene", back_populates="user_genes")
    source_strategy = relationship("StrategyConfig")

    __table_args__ = (UniqueConstraint("user_id", "gene_id", name="_user_gene_uc"),)


# ==============================================================================
# Phantom Trade Tracker Models
# ==============================================================================


class PhantomTrade(Base):
    """
    Stores data about 'phantom' trades — virtual positions that continue
    to be tracked after the real trade has been closed at breakeven (BE/SL_AT_BE).

    This allows analyzing:
    - How many times BE 'saved' from loss (the price would have hit initial SL later)
    - How many times BE 'stole' profit (the price would have hit initial TP later)
    """

    __tablename__ = "phantom_trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Relationship with real trade
    real_trade_id = Column(
        String, nullable=False, index=True
    )  # client_order_id or trade_uuid
    symbol = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)  # LONG or SHORT
    strategy_config_id = Column(
        String, ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True
    )

    # Entry parameters
    entry_price = Column(Float, nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=False)

    # Initial levels (before moving to BE)
    initial_stop_loss = Column(Float, nullable=False)
    initial_take_profit = Column(Float, nullable=False)

    # BE trigger time
    be_trigger_time = Column(DateTime(timezone=True), nullable=False)
    be_exit_price = Column(Float, nullable=False)
    real_pnl_pct = Column(Float, nullable=False)  # Real PnL (usually ~0)
    real_pnl_usd = Column(Float, nullable=True)

    # Results of phantom tracking
    phantom_status = Column(
        String, nullable=False, index=True, default="TRACKING"
    )  # TRACKING, TP_HIT, SL_HIT, TIMEOUT
    phantom_exit_time = Column(DateTime(timezone=True), nullable=True)
    phantom_exit_price = Column(Float, nullable=True)
    phantom_pnl_pct = Column(
        Float, nullable=True
    )  # Potential PnL if BE was not activated
    phantom_pnl_usd = Column(Float, nullable=True)

    # MAE/MFE metrics (Maximum Adverse/Favorable Excursion)
    mfe_after_be = Column(
        Float, nullable=True
    )  # Max favorable movement after BE (in %)
    mae_after_be = Column(Float, nullable=True)  # Max adverse movement after BE (in %)
    mfe_price = Column(Float, nullable=True)  # Price at MFE time
    mae_price = Column(Float, nullable=True)  # Price at MAE time

    # Additional metrics
    candles_to_resolution = Column(
        Integer, nullable=True
    )  # Number of candles to resolution
    timeout_candles = Column(
        Integer, nullable=True
    )  # Timeout configuration for this phantom

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User")
    strategy_config = relationship("StrategyConfig")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    subject = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)

    # Context field for app state (strategy config, etc.)
    context = Column(JSON, nullable=True)

    # Statuses: OPEN, IN_PROGRESS, RESOLVED, CLOSED
    status = Column(String(20), default="OPEN", nullable=False, index=True)

    # Base64 or URL to screenshot
    screenshot = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="support_tickets")
    messages = relationship(
        "SupportTicketMessage", back_populates="ticket", cascade="all, delete-orphan"
    )


class SupportTicketMessage(Base):
    __tablename__ = "support_ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(
        String,
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_name = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    image = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("SupportTicket", back_populates="messages")


class HubFeedback(Base):
    __tablename__ = "hub_feedback"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    contact_email = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubTopic(Base):
    __tablename__ = "hub_topics"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_type = Column(String(20), nullable=False)  # 'strategy' or 'discussion'
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    author_name = Column(String(50), nullable=False)

    # Strategy-specific fields (nullable for 'discussion')
    symbol = Column(String(50), nullable=True)
    period_start = Column(String(50), nullable=True)
    period_end = Column(String(50), nullable=True)
    kpis = Column(JSON, nullable=True)
    equity_curve = Column(JSON, nullable=True)
    strategy_json = Column(JSON, nullable=True)

    likes_count = Column(Integer, default=0, server_default="0")
    is_verified = Column(Boolean, default=False, nullable=False, server_default="false")
    tags = Column(JSON, nullable=True)
    delete_token = Column(String(36), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubComment(Base):
    __tablename__ = "hub_comments"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(
        String(36), ForeignKey("hub_topics.id", ondelete="CASCADE"), nullable=False
    )
    author_name = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubVerifiedStrategy(Base):
    __tablename__ = "hub_verified_strategies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    author = Column(String(100), nullable=False)
    tags = Column(JSON, nullable=False)
    description = Column(Text, nullable=False)
    strategy_json = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubNewsItem(Base):
    __tablename__ = "hub_news"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    date = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    likes_count = Column(Integer, default=0, server_default="0")
    is_pinned = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubNewsComment(Base):
    __tablename__ = "hub_news_comments"
    id = Column(Integer, primary_key=True, index=True)
    news_id = Column(
        Integer, ForeignKey("hub_news.id", ondelete="CASCADE"), nullable=False
    )
    author_name = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class HubNode(Base):
    __tablename__ = "hub_nodes"
    id = Column(Integer, primary_key=True, index=True)
    node_uuid = Column(String(36), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    secret_hash = Column(String(255), nullable=False)
    ip_address = Column(String(50), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    version = Column(String(50), default="1.0.0", server_default="1.0.0")
    last_ping = Column(DateTime(timezone=True), nullable=True)
    latency_ms = Column(Float, nullable=True)
    is_banned = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
