# bot_module/config.py
try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    print(
        "DEBUG: dotenv module not found, load_dotenv will be a no-op."
    )  # Or use logger if available early

    def load_dotenv(*args, **kwargs):
        """Mock load_dotenv to do nothing and return False"""
        return False


import os
import logging
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


logger = logging.getLogger(__name__)
if not logging.getLogger("bot_module").hasHandlers():  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)

# Suppress verbose ccxt debug logs
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("ccxt.base.exchange").setLevel(logging.WARNING)

# ==============================================================================
# Bot Runner Scaling
# ==============================================================================
# Number of processes for load distribution between bots (sharding)
# If 1 - works in a single process. If > 1 - creates workers.
BOT_RUNNER_PROCESSES = int(os.environ.get("BOT_RUNNER_PROCESSES", 1))

# ==============================================================================
# Market Type and Environment Settings
# ==============================================================================
# Market type for trading: 'spot' or 'futures_usdtm'
TRADING_MARKET_TYPE = (
    os.environ.get("TRADING_MARKET_TYPE", "futures_usdtm").strip().lower()
)
# Execution environment: 'mainnet' or 'testnet'
ACTIVE_TRADING_ENVIRONMENT = (
    os.environ.get("ACTIVE_TRADING_ENVIRONMENT", "mainnet").strip().lower()
)

# ==============================================================================
# Binance API Credentials
# ==============================================================================

# --- NEW BLOCK: Loading ALL keys from .env ---
# Mainnet Keys
MAINNET_SPOT_API_KEY = os.environ.get("MAINNET_BINANCE_SPOT_API_KEY", "")
MAINNET_SPOT_API_SECRET = os.environ.get("MAINNET_BINANCE_SPOT_API_SECRET", "")
MAINNET_FUTURES_API_KEY = os.environ.get("MAINNET_BINANCE_FUTURES_API_KEY", "")
MAINNET_FUTURES_API_SECRET = os.environ.get("MAINNET_BINANCE_FUTURES_API_SECRET", "")

# Testnet Keys
TESTNET_SPOT_API_KEY = os.environ.get("TESTNET_BINANCE_SPOT_API_KEY", "")
TESTNET_SPOT_API_SECRET = os.environ.get("TESTNET_BINANCE_SPOT_API_SECRET", "")
TESTNET_FUTURES_API_KEY = os.environ.get("TESTNET_BINANCE_FUTURES_API_KEY", "")
TESTNET_FUTURES_API_SECRET = os.environ.get("TESTNET_BINANCE_FUTURES_API_SECRET", "")

# --- These variables will now be CALCULATED ---
BINANCE_SPOT_API_KEY = ""
BINANCE_SPOT_API_SECRET = ""
BINANCE_FUTURES_API_KEY = ""
BINANCE_FUTURES_API_SECRET = ""

if ACTIVE_TRADING_ENVIRONMENT == "mainnet":
    BINANCE_SPOT_API_KEY = MAINNET_SPOT_API_KEY
    BINANCE_SPOT_API_SECRET = MAINNET_SPOT_API_SECRET
    BINANCE_FUTURES_API_KEY = MAINNET_FUTURES_API_KEY
    BINANCE_FUTURES_API_SECRET = MAINNET_FUTURES_API_SECRET
    logger.info("Configuration loaded for MAINNET environment.")
elif ACTIVE_TRADING_ENVIRONMENT == "testnet":
    BINANCE_SPOT_API_KEY = TESTNET_SPOT_API_KEY
    BINANCE_SPOT_API_SECRET = TESTNET_SPOT_API_SECRET
    BINANCE_FUTURES_API_KEY = TESTNET_FUTURES_API_KEY
    BINANCE_FUTURES_API_SECRET = TESTNET_FUTURES_API_SECRET
    logger.info("Configuration loaded for TESTNET environment.")
else:
    raise ValueError(
        f"Unknown ACTIVE_TRADING_ENVIRONMENT: '{ACTIVE_TRADING_ENVIRONMENT}'"
    )

# --- This block remains unchanged; it selects active keys from the already selected set ---
BINANCE_ACTIVE_API_KEY = ""
BINANCE_ACTIVE_API_SECRET = ""

if TRADING_MARKET_TYPE == "spot":
    BINANCE_ACTIVE_API_KEY = BINANCE_SPOT_API_KEY
    BINANCE_ACTIVE_API_SECRET = BINANCE_SPOT_API_SECRET
    if not BINANCE_ACTIVE_API_KEY or not BINANCE_ACTIVE_API_SECRET:
        logger.warning(
            f"ACTIVE Binance SPOT API keys for environment '{ACTIVE_TRADING_ENVIRONMENT}' are not configured in .env."
        )
elif TRADING_MARKET_TYPE == "futures_usdtm":
    BINANCE_ACTIVE_API_KEY = BINANCE_FUTURES_API_KEY
    BINANCE_ACTIVE_API_SECRET = BINANCE_FUTURES_API_SECRET
    if not BINANCE_ACTIVE_API_KEY or not BINANCE_ACTIVE_API_SECRET:
        logger.warning(
            f"ACTIVE Binance FUTURES API keys for environment '{ACTIVE_TRADING_ENVIRONMENT}' are not configured in .env."
        )
else:
    logger.warning(
        f"Unknown TRADING_MARKET_TYPE ('{TRADING_MARKET_TYPE}') to select API keys. Keys are not set."
    )

# ==============================================================================
# Binance API URLs
# ==============================================================================
BINANCE_SPOT_MAINNET_API_URL = "https://api.binance.com"
BINANCE_SPOT_MAINNET_USER_DATA_WS_URL = "wss://stream.binance.com:9443/ws"
# --- ADDED: Explicit Mainnet Market Data WS URL for Spot ---
BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_FUTURES_USDTM_MAINNET_API_URL = "https://fapi.binance.com"
BINANCE_FUTURES_USDTM_MAINNET_USER_DATA_WS_URL = "wss://fstream.binance.com/ws"
# --- ADDED: Explicit Mainnet Market Data WS URL for USDT-M Futures ---
BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL = "wss://fstream.binance.com/ws"

BINANCE_SPOT_TESTNET_API_URL = "https://testnet.binance.vision"
BINANCE_SPOT_TESTNET_USER_DATA_WS_URL = "wss://stream.testnet.binance.vision/ws"
# --- ADDED: URL for spot testnet market data ---
BINANCE_SPOT_TESTNET_MARKET_DATA_WS_URL = "wss://stream.testnet.binance.vision/ws"  # Usually matches UserData, but better explicitly
# Adding URL for DataLoader from testnet (if needed for E2E)
BINANCE_SPOT_TESTNET_API_URL_FOR_LOADER = "https://testnet.binance.vision/api/v3"

BINANCE_FUTURES_TESTNET_MARKET_DATA_WS_URL = "wss://stream.binancefuture.com/ws"  # Usually matches UserData, but better explicitly

BINANCE_FUTURES_TESTNET_API_URL = "https://testnet.binancefuture.com"
BINANCE_FUTURES_TESTNET_USER_DATA_WS_URL = "wss://stream.binancefuture.com/ws"
# Adding URL for DataLoader from testnet (if needed for E2E)
BINANCE_FUTURES_TESTNET_API_URL_FOR_LOADER = "https://testnet.binancefuture.com/fapi/v1"

# --- URL for loading market data (Market Data Streams) ---
# Initialize the variable before use
BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER: str = ""

# Logic for BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER
if ACTIVE_TRADING_ENVIRONMENT == "testnet":
    if TRADING_MARKET_TYPE == "spot":
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = (
            BINANCE_SPOT_TESTNET_MARKET_DATA_WS_URL
        )
        logger.info(
            f"Config: DataConsumer will use SPOT TESTNET Market Data WS: {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
        )
    elif TRADING_MARKET_TYPE == "futures_usdtm":
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = BINANCE_FUTURES_TESTNET_MARKET_DATA_WS_URL  # This variable was already defined
        logger.info(
            f"Config: DataConsumer will use FUTURES USDT-M TESTNET Market Data WS: {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
        )
    else:
        # Fallback or error for unhandled market type in testnet
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = (
            ""  # Or some default / error indicator
        )
        logger.error(
            f"Config: Unsupported TRADING_MARKET_TYPE '{TRADING_MARKET_TYPE}' for 'testnet' market data WS URL."
        )
elif ACTIVE_TRADING_ENVIRONMENT == "mainnet":
    if TRADING_MARKET_TYPE == "spot":
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = (
            BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL
        )
        logger.info(
            f"Config: DataConsumer will use SPOT MAINNET Market Data WS: {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
        )
    elif TRADING_MARKET_TYPE == "futures_usdtm":
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = (
            BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL
        )
        logger.info(
            f"Config: DataConsumer will use FUTURES USDT-M MAINNET Market Data WS: {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
        )
    else:
        # Fallback or error for unhandled market type in mainnet
        BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = (
            ""  # Or some default / error indicator
        )
        logger.error(
            f"Config: Unsupported TRADING_MARKET_TYPE '{TRADING_MARKET_TYPE}' for 'mainnet' market data WS URL."
        )
else:
    BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = ""  # Fallback for unknown environment
    logger.error(
        f"Config: Unsupported ACTIVE_TRADING_ENVIRONMENT: {ACTIVE_TRADING_ENVIRONMENT} for market data WS URL."
    )

# Ensure BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER is initialized if not set by logic above or set to empty.
if not BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER:  # Checks for empty string
    # Default fallback, though the logic above should cover all known ACTIVE_TRADING_ENVIRONMENT and TRADING_MARKET_TYPE
    # or explicitly set it to "" with an error. This is a safety net.
    BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER = BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL  # Defaulting to Spot Mainnet Market Data
    logger.warning(
        f"Config: BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER was not meaningfully set by logic or was empty, defaulted to: {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
    )


# --- Block for defining BINANCE_EXECUTION_API_URL and BINANCE_EXECUTION_WS_URL has been removed, ---
# --- since BinanceExecutor now determines its URLs independently. ---
# --- Logging of these URLs is also removed. ---

BINANCE_SPOT_DATA_API_URL_FOR_LOADER = "https://api.binance.com/api/v3"
BINANCE_FUTURES_USDTM_DATA_API_URL_FOR_LOADER = "https://fapi.binance.com/fapi/v1"
BINANCE_FUTURES_COINM_DATA_API_URL_FOR_LOADER = "https://dapi.binance.com/dapi/v1"

# These are already defined above, but we ensure they exist for clarity in DataLoader context
# BINANCE_SPOT_TESTNET_API_URL_FOR_LOADER = "https://testnet.binance.vision/api/v3"
# BINANCE_FUTURES_TESTNET_API_URL_FOR_LOADER = "https://testnet.binancefuture.com/fapi/v1"


USE_TESTNET = False  # Keep if keys are different

# --- MOVED LOGGING BLOCK ---
# The actual URL used by DataLoader will be determined by ACTIVE_TRADING_ENVIRONMENT
# So, logging these "default" mainnet URLs might be confusing if testnet is active.
# We will log the effective URL within DataLoader itself or adjust this logging.
# For now, let's comment out these specific default logs here and rely on DataLoader's choice.
# logger.info(f"Binance HISTORICAL/PUBLIC DATA API Endpoint (DataLoader Default Mainnet Spot): {BINANCE_SPOT_DATA_API_URL_FOR_LOADER}")
# logger.info(f"Binance HISTORICAL/PUBLIC DATA API Endpoint (DataLoader Default Mainnet Futures): {BINANCE_FUTURES_USDTM_DATA_API_URL_FOR_LOADER}")
logger.info(
    f"Binance REALTIME MARKET DATA WebSocket Endpoint (DataConsumer Default): {BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER}"
)  # Now this variable is defined
# The following two lines have been removed because Executor now determines its own URLs and can log them during initialization.
# logger.info(f"Binance EXECUTION API Endpoint (Current Active): {BINANCE_EXECUTION_API_URL}")
# logger.info(f"Binance EXECUTION USER DATA WebSocket Endpoint (Current Active): {BINANCE_EXECUTION_WS_URL}")

# ==============================================================================
# Redis Configuration
# ==============================================================================
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))  # Main application DB
REDIS_USERNAME = os.environ.get("REDIS_USERNAME") or None
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)
REDIS_COMMAND_CHANNEL = os.environ.get("REDIS_COMMAND_CHANNEL", "depthsight:commands")
REDIS_STATE_KEY_PORTFOLIO = os.environ.get(
    "REDIS_STATE_KEY_PORTFOLIO", "depthsight:state:portfolio"
)
REDIS_STATE_KEY_STRATEGIES = os.environ.get(
    "REDIS_STATE_KEY_STRATEGIES", "depthsight:state:strategies"
)
REDIS_STATE_KEY_POSITIONS = os.environ.get(
    "REDIS_STATE_KEY_POSITIONS", "depthsight:state:positions"
)

# Market data fan-out.
# "direct" keeps the legacy in-process WebSocket behavior.
# "redis" makes bot workers request subscriptions through Redis and receive raw exchange payloads from market_data_service.py.
MARKET_DATA_FANOUT_MODE = (
    os.environ.get("MARKET_DATA_FANOUT_MODE", "direct").strip().lower()
)
MARKET_DATA_REDIS_COMMAND_CHANNEL = os.environ.get(
    "MARKET_DATA_REDIS_COMMAND_CHANNEL", "depthsight:market_data:commands"
)
MARKET_DATA_REDIS_EVENT_CHANNEL_PREFIX = os.environ.get(
    "MARKET_DATA_REDIS_EVENT_CHANNEL_PREFIX", "depthsight:market_data:events"
)
MARKET_DATA_REDIS_SNAPSHOT_KEY_PREFIX = os.environ.get(
    "MARKET_DATA_REDIS_SNAPSHOT_KEY_PREFIX", "depthsight:market_data:snapshot"
)
MARKET_DATA_REDIS_SNAPSHOT_TTL_SECONDS = int(
    os.environ.get("MARKET_DATA_REDIS_SNAPSHOT_TTL_SECONDS", 3600)
)
MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS = float(
    os.environ.get("MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 5.0)
)

logger.info(
    f"Redis configured: Host={REDIS_HOST}, Port={REDIS_PORT}, Main DB={REDIS_DB}, User={REDIS_USERNAME or 'default'}, Auth={'Yes' if REDIS_PASSWORD else 'No'}"
)

# ==============================================================================
# Celery Configuration (using Redis)
# ==============================================================================
_redis_auth_str = ""
if REDIS_PASSWORD:
    _redis_auth_str = (
        f"{REDIS_USERNAME}:{REDIS_PASSWORD}@"
        if REDIS_USERNAME
        else f":{REDIS_PASSWORD}@"
    )
CELERY_BROKER_URL = (
    f"redis://{_redis_auth_str}{REDIS_HOST}:{REDIS_PORT}/1"  # DB 1 for Celery Broker
)
CELERY_RESULT_BACKEND = (
    f"redis://{_redis_auth_str}{REDIS_HOST}:{REDIS_PORT}/2"  # DB 2 for Celery Results
)
logger.info(
    f"Celery Broker URL: {CELERY_BROKER_URL.replace(REDIS_PASSWORD or '', '***') if REDIS_PASSWORD else CELERY_BROKER_URL}"
)
logger.info(
    f"Celery Result Backend URL: {CELERY_RESULT_BACKEND.replace(REDIS_PASSWORD or '', '***') if REDIS_PASSWORD else CELERY_RESULT_BACKEND}"
)

# ==============================================================================
# Celery Worker Configuration for Multi-User Genetic Search
# ==============================================================================
# Maximum number of concurrent genetic algorithm runs
# Recommended: 1-3 for heavy tasks (full backtesting per strategy)
GENETIC_MAX_CONCURRENT_RUNS = int(os.environ.get("GENETIC_MAX_CONCURRENT_RUNS", 3))

# Number of CPU cores allocated per genetic run
# Higher = faster per-task, Lower = more parallel users
# For 24-core server: 4-8 cores per run is optimal
GENETIC_CORES_PER_RUN = int(os.environ.get("GENETIC_CORES_PER_RUN", 4))

# Celery worker concurrency (number of parallel workers)
# This should match GENETIC_MAX_CONCURRENT_RUNS for genetic-only queue
# Or be higher if worker handles other task types
CELERY_WORKER_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_CONCURRENCY", GENETIC_MAX_CONCURRENT_RUNS)
)

# Celery prefetch multiplier - how many tasks each worker prefetches
# Set to 1 for fair scheduling (first-come-first-served)
CELERY_WORKER_PREFETCH_MULTIPLIER = int(
    os.environ.get("CELERY_WORKER_PREFETCH_MULTIPLIER", 1)
)

logger.info(
    f"Genetic Worker Config: max_concurrent={GENETIC_MAX_CONCURRENT_RUNS}, cores_per_run={GENETIC_CORES_PER_RUN}, worker_concurrency={CELERY_WORKER_CONCURRENCY}"
)


# ==============================================================================
# Genetic Algorithm Settings
# ==============================================================================
GENETIC_DEFAULT_POPULATION_SIZE = 50
GENETIC_DEFAULT_GENERATIONS = 20
GENETIC_DEFAULT_CROSSOVER_PROBABILITY = 0.7
GENETIC_DEFAULT_MUTATION_PROBABILITY = 0.2
GENETIC_DEFAULT_EVALUATION_RATIO = 0.1  # Percentage of champions for full evaluation
GENETIC_DEFAULT_FITNESS_METRIC = "profit_factor"  # Default metric to optimize for
GENETIC_SCREENING_PERIOD_RATIO = 0.3  # Use first 30% of data for pre-screening
GENETIC_HALL_OF_FAME_SIZE = 10  # Number of top strategies to save

GENE_POOL: Dict[str, Any] = {
    "LOGICAL_OPERATORS": ["AND", "OR"],
    "COMPARISON_OPERATORS": [
        ">",
        "<",
        "==",
        "!=",
        ">=",
        "<=",
        "crosses_above",
        "crosses_below",
    ],
    "PRICE_SOURCES": ["open", "high", "low", "close"],
    "INDICATORS": {
        "EMA": {"period": (5, 200)},  # Adjusted lower bound for EMA/SMA
        "SMA": {"period": (5, 200)},
        "RSI": {"period": (7, 30)},
        # "ATR": {"period": (7, 30)}, # ATR is usually available via pair_info, not directly compared as operand
    },
    "VALUE_RANGES": {  # For comparing indicators/prices against static values
        "rsi_level": (10, 90),  # e.g., RSI > 70 or RSI < 30
        "price_percentage_change": (
            -5.0,
            5.0,
        ),  # e.g. for comparing price change over N bars
        "atr_multiplier_value": (
            0.5,
            5.0,
        ),  # For conditions like "low < prev_low - ATR * 0.5"
        "static_value_small": (0, 100),  # General small integer values
        "static_value_price_offset": (
            -0.01,
            0.01,
        ),  # For comparing price offsets in percentage
    },
    # Stop Loss and Take Profit types and ranges for strategy generation
    "SL_TP_TYPES": ["percentage", "atr_multiplier"],
    "STOP_LOSS_PERCENTAGE_RANGE": (0.001, 0.05),  # 0.1% to 5%
    "TAKE_PROFIT_PERCENTAGE_RANGE": (0.002, 0.1),  # 0.2% to 10%
    "STOP_LOSS_ATR_MULTIPLIER_RANGE": (0.5, 5.0),
    "TAKE_PROFIT_ATR_MULTIPLIER_RANGE": (1.0, 10.0),
    # Configuration for partial targets (if generated)
    "PARTIAL_TARGETS_MAX_COUNT": 3,
    "PARTIAL_TARGET_FRACTION_RANGE": (0.1, 0.5),  # Fraction of position to close
    # Order mode for genetic strategies (can be fixed or part of gene pool)
    "ORDER_MODES": [
        "MARKET",
        "LIMIT_RETEST",
    ],  # LIMIT_BREAK might be too complex initially
    "LIMIT_ENTRY_OFFSET_ATR_RANGE": (
        0.1,
        1.0,
    ),  # For LIMIT_RETEST mode, offset from trigger price in ATR multiples
}
logger.info("Genetic Algorithm default parameters and GENE_POOL defined.")


# ==============================================================================
# Data Source for Controller (Main App WebSocket)
# ==============================================================================

# --- NEW BLOCK OF SYMBOL SOURCE SETTINGS ---
# Active symbol list retrieval mode:
# "MAIN_APP" - via WebSocket from the main application (ws://localhost:8765)
# "STATIC_LIST" - from the static list below (SYMBOL_SOURCE_STATIC_LIST)
# "JSON_FILE" - from file (SYMBOL_SOURCE_JSON_FILE_PATH)
SYMBOL_SOURCE_MODE = "MAIN_APP"  # Default is 'MAIN_APP'

# Static list of symbols for "STATIC_LIST" mode
# Format: list of strings, e.g., ["BTCUSDT", "ETHUSDT"]
SYMBOL_SOURCE_STATIC_LIST: List[str] = [
    "APTUSDT",
    "NEWTUSDT",
    "DMCUSDT",  # Test example
]

# Path to the file with the list of symbols for "JSON_FILE" mode
# File format: JSON array of strings, for example ["BTCUSDT", "ETHUSDT"]
SYMBOL_SOURCE_JSON_FILE_PATH = "data/static_symbols.json"


# Path to the file with filtered pairs (if a static list is used) - OLD, CAN BE KEPT OR REMOVED
FILTERED_PAIRS_FILE = "data/filtered_pairs.json"
# WebSocket URL of the main application that provides market data and the list of active pairs
MAIN_APP_WS_URL = "wss://screener.depthsight.pro/ws/bot/"
# Name of the topic/message in WebSocket from the main app signaling an update to the active pairs list
MAIN_APP_SYMBOL_UPDATE_TOPIC = "filtered_pairs:update"  # Example, may differ

# ==============================================================================
# Testing & Debugging
# ==============================================================================
# Added to manage reconnection delay in tests
BINANCE_WS_RECONNECT_DELAY_BASE = 5

# ==============================================================================
# Trading Controller Settings
# ==============================================================================
# Controller main loop delay in seconds (how often signals are checked)
CONTROLLER_LOOP_DELAY = 0.1
# Maximum number of simultaneously running strategies (if such a limit exists)
MAX_CONCURRENT_STRATEGIES = 10  # Example, might not be actively used
# Time in seconds for which a symbol is "frozen" for new trades after closing the previous position on it.
SYMBOL_COOLDOWN_SECONDS = 60

LIMIT_ORDER_MAX_LIFETIME_SECONDS = (
    300  # Maximum lifetime of a limit entry order (in seconds)
)
PENDING_ENTRY_CHECK_INTERVAL_SECONDS = 60  # How often to check for "stale" limit orders

BE_SL_OFFSET_TICKS = 2  # Offset towards profit (e.g., 1-2 ticks)

BE_MOVE_RETRY_DELAY_SECONDS = 10  # Retry

# Position check interval without stop-loss (in seconds)
CONTROLLER_MISSING_SL_CHECK_INTERVAL_SECONDS = 60
# Time in seconds after opening a position during which SL placement is expected.
# If SL is not set after this time, the position will be closed.
CONTROLLER_SL_PLACEMENT_GRACE_PERIOD_SECONDS = 20  # 20 seconds should be enough

# Slippage in ticks for the limit price of SPOT STOP_LOSS_LIMIT orders relative to the stopPrice.
SPOT_SL_LIMIT_SLIPPAGE_TICKS = 3

# ==============================================================================
# Dynamic Symbol Selection / Activity Check Parameters (Used in Foundations)
# ==============================================================================
# Whether dynamic symbol selection based on their activity is enabled (used in check_foundations)
DYNAMIC_SELECTION_ENABLED = (
    True  # Not used directly by the controller, but affects foundation_market_activity
)
# Threshold for relative volume (current_volume / avg_volume_period). Signal if higher.
DYNAMIC_SELECTION_REL_VOL_THRESHOLD = 5.0
# Threshold for NATR (Normalized ATR, in %). Signal if higher.
DYNAMIC_SELECTION_NATR_THRESHOLD = 1.0
# Period for calculating the moving average volume (for DYNAMIC_SELECTION_REL_VOL_THRESHOLD)
RELATIVE_VOLUME_PERIOD = 20  # Also used in utils.add_relative_volume

# ==============================================================================
# Risk Management Settings
# ==============================================================================
# Risk per trade as a percentage of the current balance (e.g., 0.5 for 0.5%)
DEFAULT_RISK_PER_TRADE_PERCENT = 1.0
# Maximum allowed daily loss as a percentage of the balance at the start of the day
DEFAULT_DAILY_MAX_LOSS_PERCENT = 5.0
# Maximum allowable total drawdown as a percentage of balance
DEFAULT_MAX_DRAWDOWN_PERCENT = 20.0
# Maximum number of consecutive losing trades after which trading stops
DEFAULT_MAX_CONSECUTIVE_LOSSES = 10
# Minimum balance in USD, upon reaching which trading stops
MIN_BALANCE_THRESHOLD_USD = 5
# Minimum required Reward/Risk Ratio for signal approval
RISK_MANAGER_MIN_RR_RATIO = 1.0
# Maximum allowed distance to stop-loss as a percentage of the entry price
RISK_MANAGER_MAX_STOP_DISTANCE_PCT = 2.0
# Minimum allowed distance to stop-loss as a percentage of the entry price
RISK_MANAGER_MIN_STOP_DISTANCE_PCT = 0.05
# Minimum required ratio of potential profit to risk IN DOLLARS.
# For example, if the risk is $10 and this parameter is 1.5, then the potential profit must be >= $15.
RISK_MANAGER_MIN_DOLLAR_RR_RATIO = 1.0
# Minimum distance from the entry price to the partial take-profit in percent of the entry price
MIN_PARTIAL_TP_DISTANCE_PCT = 0.005  # 0.5%

RISK_MANAGER_STATE_FILE_PATH = "data/data_rm.json"

# --- Dynamic Risk Adjustment for Strategy-Symbol Performance ---
# Whether dynamic risk adjustment is enabled for the "strategy-symbol" pair
STRATEGY_SYMBOL_PERFORMANCE_ADJUSTMENT_ENABLED = True
# Number of recent trades to evaluate strategy performance on a symbol
STRATEGY_SYMBOL_ROLLING_WINDOW_SIZE = 10
# Minimum number of trades for a "strategy-symbol" pair before risk assessment and adjustment begins
STRATEGY_SYMBOL_MIN_TRADES_FOR_ASSESSMENT = 5

# Thresholds for risk REDUCTION for the "strategy-symbol" pair
# If PnL for the window < this % of the SUM OF PLANNED RISKS for trades in the window
STRATEGY_SYMBOL_PNL_THRESHOLD_PCT = -0.1
# If Win Rate for the window < this %
STRATEGY_SYMBOL_WIN_RATE_THRESHOLD_PCT = 40.0
# If N consecutive losses for this "strategy-symbol" pair
STRATEGY_SYMBOL_MAX_CONSECUTIVE_LOSSES = 3

# Risk multipliers (applied to the base DEFAULT_RISK_PER_TRADE_PERCENT)
# 1.0 = full risk, 0.0 = trading for this strategy on this symbol is temporarily disabled
STRATEGY_SYMBOL_RISK_MULTIPLIERS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
STRATEGY_SYMBOL_DEFAULT_RISK_MULTIPLIER_VALUE = 1.0  # Explicit value for start

# Conditions for risk RECOVERY (transition to a higher multiplier)
# N profitable trades in a row for this "strategy-symbol" pair
STRATEGY_SYMBOL_RECOVERY_CONSECUTIVE_WINS = 2
# If PnL for the window > this % of the SUM OF PLANNED RISKS for trades in the window
STRATEGY_SYMBOL_RECOVERY_PNL_THRESHOLD_PCT = 1.0
# "Quarantine" in seconds after a risk reduction before it can be increased, even if metrics have improved
STRATEGY_SYMBOL_COOLDOWN_AFTER_PENALTY_SECONDS = 60 * 60 * 1

# Maximum share of the balance that can be used to open a SINGLE position
# For example, 0.50 means that a position cannot be larger than 50% of the current balance.
# This limit is applied AFTER calculating the quantity based on risk per trade.
MAX_POSITION_SIZE_PCT_OF_BALANCE = 0.90  # Example: 90% of balance

# ==============================================================================
# Orderbook Foundation & Adaptation Settings
# ==============================================================================
# --- Parameters for the "Orderbook" base (analysis of nearest densities) ---
# Enable/disable "Orderbook" basis globally
ORDERBOOK_FOUNDATION_ENABLED = True
# How many order book levels (bid/ask) to check for density presence
ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK = 15
# Minimum density volume in USD to consider it significant (if ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD = False)
ORDERBOOK_FOUNDATION_MIN_DENSITY_USD = 100000
# Whether to use ATR for the dynamic density threshold
ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD = True
# If USE_ATR_THRESHOLD=True, then the density volume (in USD) must be > (ATR * Price * This_Factor)
ORDERBOOK_FOUNDATION_MIN_DENSITY_ATR_FACTOR = 7.0
# Number of RECENT candles to analyze price "approach" to density
ORDERBOOK_APPROACH_CANDLES = 10
# Minimum total price movement over APPROACH_CANDLES (in ATR fractions) to be considered an "approach"
ORDERBOOK_APPROACH_MIN_MOVE_ATR = 0.30
# How many ticks to the density to consider a "touch" (for is_price_near_support/resistance)
DENSITY_NEAR_PROXIMITY_TICKS = 3

# --- Parameters for adapting SL/TP to the order book ---
# Enable SL adaptation to order book densities
ADAPT_SL_TO_ORDERBOOK_ENABLED = True
# Enable TP adaptation to order book densities
ADAPT_TP_TO_ORDERBOOK_ENABLED = True
# Maximum SL/TP offset from the ORIGINAL in ATR fractions during adaptation
ORDERBOOK_ADAPT_MAX_OFFSET_ATR = 0.6
# Minimum distance from the entry price to the density (in ATR fractions) to consider it for adaptation
ORDERBOOK_ADAPT_MIN_DENSITY_DISTANCE_ATR = 0.25
# How many ticks to place SL BEYOND the density
ORDERBOOK_ADAPT_SL_TICKS_BEHIND_DENSITY = 1
# How many ticks to place TP BEFORE the density
ORDERBOOK_ADAPT_TP_TICKS_BEFORE_DENSITY = 5

# --- New flags for order book analysis between spot and futures ---
ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES: bool = True
ANALYZE_FUTURES_ORDERBOOK_FOR_SPOT_TRADES: bool = False
USE_COMPANION_ORDERBOOK_ANALYSIS: bool = True

# --- NEW PARAMETER ---
# How many ticks to consider a conflict zone between support on one market and resistance on another
OB_CONFLICT_PROXIMITY_TICKS: int = 2
# ==============================================================================
# Round Number Level Foundation Settings
# ==============================================================================
# Enable/disable the "Round Level" base
ROUND_LEVEL_FOUNDATION_ENABLED = True
# Maximum price deviation from a round level in % for triggering
ROUND_LEVEL_PROXIMITY_PCT = 0.002  # 0.2%
# ATR multiplier for determining the round level zone (if ROUND_LEVEL_USE_ATR_PROXIMITY = True)
ROUND_LEVEL_ATR_MULTIPLIER = 0.1
# Whether to use ATR to determine the round level zone
ROUND_LEVEL_USE_ATR_PROXIMITY = False
# Minimum price deviation from a round level in ticks (used as max(deviation_in_%, deviation_in_ticks))
ROUND_LEVEL_MIN_TICK_PROXIMITY = 5
# How many round levels of each "step type" to check up and down from the current price
ROUND_LEVEL_MAX_LEVELS_TO_CHECK_PER_STEP_TYPE = 4  # Was 2
# Multipliers for generating round levels based on price orders (e.g., 1000, 1500, 2000, 2500)
ROUND_LEVEL_ORDER_MULTIPLIERS = [
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    7.5,
    8.0,
    9.0,
    10.0,
]  # There were others
# How many price orders to scan up and down (e.g., for price 1234, scan levels for 100, 1000, 10000)
ROUND_LEVEL_MAX_ORDERS_OF_MAGNITUDE_SCAN = 2
# Step definitions for generating round levels depending on the price
ROUND_LEVEL_STEP_DEFINITIONS = [
    {"min_price": 10000, "steps": [100, 250, 500, 1000, 2500, 5000, 10000]},
    {"min_price": 1000, "steps": [10, 25, 50, 100, 250, 500, 1000]},
    {"min_price": 100, "steps": [1, 2.5, 5, 10, 25, 50, 100]},
    {"min_price": 10, "steps": [0.1, 0.25, 0.5, 1, 2.5, 5, 10]},
    {"min_price": 1, "steps": [0.01, 0.05, 0.1, 0.25, 0.5, 1]},
    {"min_price": 0.1, "steps": [0.001, 0.005, 0.01, 0.025, 0.05, 0.1]},
    {"min_price": 0.01, "steps": [0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01]},
    {
        "min_price": 0.001,
        "steps": [0.00001, 0.00005, 0.0001, 0.000025, 0.00005, 0.001],
    },  # Typo was 0.000025, should it be 0.00025? Or is it intended
    {
        "min_price": 0.0001,
        "steps": [0.000001, 0.000005, 0.00001, 0.0000025, 0.000005, 0.00001],
    },  # Similarly
    {
        "min_price": 0.0,
        "steps": [0.00000001, 0.00000005, 0.0000001, 0.00000025, 0.0000005, 0.000001],
    },
]

# ==============================================================================
# Foundation Weights & Threshold (NEW)
# ==============================================================================
# Weights for each base type (in percent).
# The sum does not necessarily have to be 100, but the threshold will be applied to the actual sum.
FOUNDATION_WEIGHTS: Dict[str, float] = {
    "market_activity": 15.0,  # Market activity
    "level": 15.0,  # Significant levels (historical High/Low)
    "pattern": 10.0,  # Pattern defined by the strategy (lower weight as it is specific)
    "volume_confirmation": 10.0,  # Volume confirmation
    "orderbook": 30.0,  # Orderbook analysis (densities, imbalance) - high weight
    "trend": 10.0,  # Trend direction
    "round_number_level": 10.0,  # Proximity to round levels
}
# Minimum total weight (in percent) to consider a signal.
MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD: float = 49.0  # For example, 50%

# Comment out or remove the old parameter, as the new system replaces it
# MIN_OFFLINE_FOUNDATIONS_REQUIRED = 3

API_RECV_WINDOW = 10000  # (was 5000 by default, can be increased to 10000-60000)

# ==============================================================================
# Executor Settings
# ==============================================================================
# Timeout for a single order (placement/cancellation) in seconds
ORDER_TIMEOUT_SECONDS = 10
# General timeout for HTTP requests to the API in seconds
API_REQUEST_TIMEOUT_SECONDS = 10
# Timeout for User Data Stream (if there are no messages, a reconnection will occur)
USER_DATA_STREAM_TIMEOUT = 60 * 50  # 50 minutes
# Interval for sending ping to maintain User Data Stream (Binance requires every 30 min, we set it with a margin)
USER_DATA_PING_INTERVAL = 60 * 20  # 20 minutes (was 30)
# Delay before WebSocket reconnection attempt in seconds
WS_RECONNECT_DELAY = 5

# ==============================================================================
# ML Agent Settings (OnlineAgentStrategy)
# ==============================================================================
# Whether to use an ML agent for signal generation instead of regular strategies
USE_ML_AGENT = False  # If True, the controller will only use OnlineAgentStrategy
# Path for saving/loading the ONLINE trained model
ONLINE_MODEL_SAVE_PATH = Path("data/online_model.joblib")
# Path to the PRETRAINED offline model (can be used for initialization or recovery)
ML_OFFLINE_TRAINED_MODEL_PATH = Path("data/offline_trained_model.joblib")  # Was .pkl
# Signal quality threshold (from 0 to 1) if the ML agent calculates it. Signals below the threshold are ignored.
min_signal_quality_score_threshold = 0.6  # Example

DATASETS_STORAGE_PATH = "data/datasets"
MODELS_STORAGE_PATH = "data/models"
REPORTS_STORAGE_PATH = "data/reports"

# Compass Strategy Paths
COMPASS_MODEL_PATH = Path("data/compass_model.json")
ORACLE_MODEL_PATH = Path("data/oracle_model.joblib")

# --- Retraining/reset parameters for OnlineAgentStrategy ---
# Whether automatic retraining/resetting of the model is enabled in case of poor performance
RETRAIN_ENABLED = False
# PnL threshold in % (relative to something, e.g., balance or sum of risks) for the window at which retraining/reset is triggered
RETRAIN_PNL_THRESHOLD_PCT = -10.0
# Window size (number of trades) for performance evaluation before retraining/reset
RETRAIN_WINDOW_SIZE = 50

# ==============================================================================
# ML Confirmation Model Settings (Used in Backtester and potentially in Controller)
# ==============================================================================
# Whether to enable the use of an ML model for CONFIRMATION of signals from REGULAR strategies
ML_CONFIRMATION_ENABLED = True
# Path to the model for confirmation (can be the same as ML_OFFLINE_TRAINED_MODEL_PATH)
ML_CONFIRMATION_MODEL_PATH = Path(
    "data/offline_trained_model.joblib"
)  # Path to the model for confirmation
# List of strategies for which ML confirmation will be applied. If empty - for all.
ML_CONFIRMATION_STRATEGIES = [
    "VolumeBreakout",
    "FakeBreakout",
    "VisualBuilderStrategy",
]  # Strategies for ML confirmation
# Minimum probability of a "good" signal (class 1) from the ML model for confirmation
ML_CONFIRMATION_PROBABILITY_THRESHOLD = 0.80
# Whether to reject a signal if the ML model predicts a "bad" signal (opposite) with high probability
ML_CONFIRMATION_REJECT_IF_OPPOSITE_HIGH_PROB = True
# Probability threshold for a "bad" (opposite) signal to reject a confirmed one
ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD = 0.75

# --- Parameters for calculating y_true when collecting data for the ML confirmation model ---
# (Used in SimpleBacktester when log_ml_confirmation_data=True)
# Minimum price movement in the signal DIRECTION (in %), to consider y_true=1
ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT = 0.6
# Maximum price drawdown AGAINST the signal (in %) to consider y_true=0
ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT = 0.2

# ==============================================================================
# Realtime ML Data Logging (if used)
# ==============================================================================
LOG_REALTIME_ML_DATA = False  # Controls whether RealtimeMLLogger will be active
LOG_FILE_REALTIME_ML = (
    "logs/realtime_ml_data.csv"  # Path to the file if logging is enabled
)
REALTIME_ML_ORDERBOOK_DEPTH_SNAPSHOT = 10  # How many order book levels to save

# ==============================================================================
# Phantom Trade Tracker Settings (Post-BE Analysis)
# ==============================================================================
# Enable/disable tracking of "phantom" trades after BE is triggered
# This allows analyzing how much potential profit is lost due to BE
PHANTOM_TRACKING_ENABLED = True

# Operating mode: 'live' — track in real-time, 'backtest_only' — backtest only
PHANTOM_TRACKING_MODE = "live"  # 'live' | 'backtest_only'

# Phantom tracking timeout in minutes (after this time, the phantom is closed by timeout)
# If 0 — a multiplier from the strategy's max_hold_candles is used
PHANTOM_TRACKING_TIMEOUT_MINUTES = 0

# Multiplier for calculating timeout from the strategy's max_hold_candles
# For example, 2.0 means: timeout = max_hold_candles * 2
# Used only if PHANTOM_TRACKING_TIMEOUT_MINUTES = 0
PHANTOM_TRACKING_TIMEOUT_MULTIPLIER = 2.0

# Default timeout in candles if max_hold_candles is not specified in the strategy
PHANTOM_TRACKING_DEFAULT_TIMEOUT_CANDLES = 100

logger.info(
    f"Phantom Tracking: enabled={PHANTOM_TRACKING_ENABLED}, mode={PHANTOM_TRACKING_MODE}"
)

# ==============================================================================
# Telegram Notifier Settings
# ==============================================================================
TELEGRAM_NOTIFICATIONS_ENABLED = True  # Global switch
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID"
)  # Can be a user or group ID

# Detailed switches (optional)
TELEGRAM_NOTIFY_NEW_POSITION = True
TELEGRAM_NOTIFY_POSITION_CLOSED = True
TELEGRAM_NOTIFY_PARTIAL_TP = True
TELEGRAM_NOTIFY_SL_MOVED_TO_BE = True
TELEGRAM_NOTIFY_RISK_ALERTS = True
TELEGRAM_NOTIFY_ORDER_ERRORS = True
TELEGRAM_NOTIFY_BOT_ERRORS = True
TELEGRAM_NOTIFY_BLACKLIST_ALERTS = True

if TELEGRAM_NOTIFICATIONS_ENABLED:
    if "YOUR_TELEGRAM_BOT_TOKEN" in TELEGRAM_BOT_TOKEN or not TELEGRAM_BOT_TOKEN:
        logger.warning(
            "Telegram notifications enabled, but TELEGRAM_BOT_TOKEN is not configured."
        )
        TELEGRAM_NOTIFICATIONS_ENABLED = False  # Disable if token is not configured
    if "YOUR_TELEGRAM_CHAT_ID" in TELEGRAM_CHAT_ID or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram notifications enabled, but TELEGRAM_CHAT_ID is not configured."
        )
        TELEGRAM_NOTIFICATIONS_ENABLED = False  # Disable if chat_id is not configured

# ==============================================================================
# Feature Extractor Settings
# ==============================================================================
# Feature definitions (dictionaries DEFAULT_KLINE_FEATURES, NEW_KLINE_FEATURES, etc., remain here)
DEFAULT_KLINE_FEATURES = {
    "ema_20_rel": {
        "period": 20,
        "indicator": "EMA_20",
    },  # Example, real indicators should be in STRATEGY_DEFAULTS or calculated
    "atr_14_rel": {"period": 14, "indicator": "ATR_14"},
    "rsi_14": {"period": 14, "indicator": "RSI_14"},
    "vol_zscore_20": {"period": 20},
    "price_change_1m": {"period": 1},  # Example, can be on another TF
    "volume_spike_ratio_20": {"period": 20},
    "delta_volume_pct_1": {"period": 1},
    "price_std_5": {"period": 5},
    "is_high_volatility": {  # Feature depending on others
        "natr_threshold": DYNAMIC_SELECTION_NATR_THRESHOLD,  # Use common NATR threshold
        "std_threshold_pct": 0.5,  # % of price
        "std_feature_name": "price_std_5",  # Standard deviation feature name
    },
}
DEFAULT_AGGTRADE_FEATURES = {
    "agg_trade_spike_10s": {"window_sec": 10},  # Number of trades per 10 sec
    "agg_trade_delta_10s": {"window_sec": 10},  # Volume delta (buy - sell) for 10 sec
}
NEW_KLINE_FEATURES = {
    "rel_volume_spike_20": {"period": 20},  # Relative volume (current / average over N)
    "volatility_spike_20": {
        "period": 20,
        "atr_period": 14,
    },  # Volatility spike (current ATR / average ATR)
    "momentum_3": {"period": 3},  # Price change for N candles in %
    "fake_breakout_score": {
        "lookback": 5,
        "atr_period": 14,
    },  # False breakout probability estimation
    "range_compression_20": {
        "period": 20
    },  # Range compression (current range / max range over N)
    "distance_to_local_max_20": {"period": 20},  # Distance to local maximum over N in %
    "distance_to_local_min_20": {"period": 20},  # Distance to local minimum over N in %
    "body_pct": {},  # Candle body size in % of the range
    "wick_pct": {},  # Total shadow size in % of the range
    "signal_quality_score": {},  # Overall signal quality score (based on other features)
    "time_since_last_signal_sec": {},  # Time in seconds since the last signal of the same strategy for this symbol
}
NEW_AGGTRADE_FEATURES = {
    "buyer_ratio_50": {"window_size": 50},  # Share of buy trades for the last N trades
    "volume_imbalance_50": {
        "window_size": 50
    },  # Volume imbalance (buy-sell)/total for N trades
    "avg_trade_size_norm_50": {
        "window_size": 50,
        "norm_window_multiplier": 2,
    },  # Normalized average trade size
    "trade_rate_30s": {"window_sec": 30},  # Trade frequency (trades/sec) over N seconds
    "liquidity_shift_score_50": {
        "window_size": 50,
        "long_window_multiplier": 3,
    },  # Liquidity shift estimation
    "agg_delta_10s": {
        "window_sec": 10
    },  # Volume delta over 10 sec (repeats the old one, but for consistency)
    "agg_delta_30s": {"window_sec": 30},  # Volume delta for 30 sec
    "agg_delta_1m": {"window_sec": 60},  # Volume delta for 1 minute
}
# All possible features (for initialization and adaptation)
ALL_POSSIBLE_FEATURES = sorted(
    list(
        DEFAULT_KLINE_FEATURES.keys()
        | DEFAULT_AGGTRADE_FEATURES.keys()
        | NEW_KLINE_FEATURES.keys()
        | NEW_AGGTRADE_FEATURES.keys()
    )
)
logger.info(f"Total possible features defined: {len(ALL_POSSIBLE_FEATURES)}")

# Parameters for calculating signal_quality_score (in FeatureExtractor)
SIGNAL_QUALITY_THRESHOLDS = {
    "rel_volume_spike_20": 2.0,  # Relative volume must be > 2
    "volatility_spike_20": 1.5,  # Volatility spike > 1.5
    "momentum_3_abs": 0.1,  # Absolute momentum > 0.1%
    "body_pct": 60.0,  # Candle body > 60% of the range
    "wick_pct": 20.0,  # Shadows < 20% of the range (less is better)
    "range_compression_20": 0.5,  # Range compression < 0.5 (less is better)
}
SIGNAL_QUALITY_WEIGHTS = {  # Weights for each condition
    "rel_volume_spike_20": 1.0,
    "volatility_spike_20": 0.5,
    "momentum_3_abs": 1.0,
    "body_pct": 0.8,
    "wick_pct": 0.8,
    "range_compression_20": 0.5,
}
SIGNAL_QUALITY_MAX_SCORE = sum(
    SIGNAL_QUALITY_WEIGHTS.values()
)  # Maximum possible score

# ==============================================================================
# Partial Exits and Stop Loss Management (Default for Strategies)
# ==============================================================================
# Configuration for partial exits: list of tuples (R:R, % of position to close)
# For example, (0.5, 0.20) - close 20% of the position at R:R 0.5:1
DEFAULT_PARTIAL_EXIT_RR_CONFIG: List[Tuple[float, float]] = [
    (0.7, 0.20),
    (1.0, 0.30),
    (1.5, 0.25),
    (2.5, 0.25),  # Closes 20+20+30+30=100%
]
# Whether to move stop-loss to break-even after the first partial take-profit is triggered
DEFAULT_MOVE_SL_TO_BE = True
# R:R for the final take-profit if partial exits do not close 100% of the position.
# If None, the final TP will be calculated using the strategy's take_profit_atr_multiplier.
DEFAULT_FINAL_TP_RR: Optional[float] = None  # Example: 3.0 for R:R 3:1

# ==============================================================================
# General Strategy Settings (NEW)
# ==============================================================================
# Globally allow/disallow opening SHORT positions.
# If False, all strategies will generate only LONG signals.
# This is relevant if the bot operates only on the spot market without margin trading.
ALLOW_SHORT_POSITIONS = True  # Set to True if shorts are allowed (e.g., for futures)

# ==============================================================================
# Strategy Default Parameters (STRATEGY_DEFAULTS)
# ==============================================================================
# Default parameters for each strategy are defined here.
# They can be overridden via `optimized_params.json`.
STRATEGY_DEFAULTS = {
    "OnlineAgentStrategy": {
        "enabled": USE_ML_AGENT,  # Enabled by the global flag USE_ML_AGENT
        "candle_timeframe": "1m",
        "atr_period": 14,
        "stop_loss_atr_multiplier": 1.2,
        "take_profit_atr_multiplier": 1.8,
        "min_probability_threshold": 0.65,  # Minimum probability from the model for entry
        "save_model_interval_seconds": 1800,  # How often to save the online model
        "model_save_path": str(
            ONLINE_MODEL_SAVE_PATH
        ),  # Where to save the online model
        "offline_model_save_path": str(
            ML_OFFLINE_TRAINED_MODEL_PATH
        ),  # Path to the pretrained model
        "use_offline_model": False,  # Whether to use a pre-trained model at startup
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT
        / 100.0,  # Risk per trade for this strategy
        # Parameters for the 'is_high_volatility' feature (if used by the agent)
        "high_volatility_natr_threshold": DYNAMIC_SELECTION_NATR_THRESHOLD,
        "high_volatility_std_threshold_pct": 0.5,
        # Retraining parameters (override global ones if specified here)
        "retrain_enabled": RETRAIN_ENABLED,
        "retrain_pnl_threshold_pct": RETRAIN_PNL_THRESHOLD_PCT,
        "retrain_window_size": RETRAIN_WINDOW_SIZE,
        # Parameters for calculating signal_quality_score (if the agent uses it)
        "signal_quality_thresholds": SIGNAL_QUALITY_THRESHOLDS,
        "signal_quality_weights": SIGNAL_QUALITY_WEIGHTS,
        "signal_quality_max_score": SIGNAL_QUALITY_MAX_SCORE,
        "min_signal_quality_score_threshold": min_signal_quality_score_threshold,
        # Partial exit parameters for ML Agent
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
    },
    "VolumeBreakout": {
        "enabled": True,
        "candle_timeframe": "1m",
        "retest_atr_percent": 0.07,  # At what % ATR from the breakout price to place a limit order for retest
        "stop_loss_atr_multiplier": 1.3,
        "take_profit_atr_multiplier": 2.0,
        "min_natr_threshold": DYNAMIC_SELECTION_NATR_THRESHOLD,  # Used for foundation_market_activity
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
        "breakout_atr_period": 15,  # ATR period for internal strategy calculations (if it doesn't take from pair_info)
    },
    "FakeBreakout": {
        "enabled": True,
        "candle_timeframe": "1m",
        "lookback_candles": 100,
        "reversal_confirmation_bars": 2,
        "stop_loss_atr_multiplier": 1.1,
        "take_profit_atr_multiplier": 1.5,
        "min_natr_threshold": DYNAMIC_SELECTION_NATR_THRESHOLD,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
        "volume_spike_multiplier": 3.0,
        "agg_trade_window_sec": 10,
    },
    "ReverseVolumeBreakout": {
        "enabled": False,
        "candle_timeframe": "3m",
        "reverse_sl_to_tp_ratio": 3.0,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": None,
        "small_risk_percent_tp_config": [
            [0.004, 0.5],  # Close 50% at +0.4%
            [0.008, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": True,
        "final_tp_rr": None,
    },
    "ReverseFakeBreakout": {
        "enabled": False,
        "candle_timeframe": "1m",
        "reverse_sl_to_tp_ratio": 3.0,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": None,
        "move_sl_to_be_on_first_tp": True,
        "final_tp_rr": None,
    },
    "CompassStrategy": {
        "enabled": False,
        "candle_timeframe": "1m",
        # Configurable entry params
        "min_entry_probability": 0.65,
        "use_oracle": True,
        # Risk Management (Stage 3 & 4)
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_atr_multiplier": 7.5,
        "trailing_stop_enabled": False,
        "trailing_stop_activation_atr": 2.0,
        "trailing_stop_distance_atr": 1.0,
        "partial_exits": [  # Default partials
            {"fraction": 0.5, "rr_multiplier": 3.0}
        ],
        "move_sl_to_be_after_first_tp": True,
        # General
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
    },
    "DensityBounce": {
        "enabled": False,
        "min_density_size_usd": ORDERBOOK_FOUNDATION_MIN_DENSITY_USD,  # Using a common parameter
        "max_touch_count": 4,
        "depth_levels_to_check": ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK,  # Use common
        "sl_ticks_multiplier": 3,
        "tp_ticks_multiplier": 30,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
    },
    "ConsolidationImpulse": {
        "enabled": True,
        "candle_timeframe": "1m",
        "range_bars": 8,
        "max_range_atr_multiplier": 1.0,
        "impulse_volume_multiplier": 2.0,
        "impulse_candle_min_body_atr": 0.3,
        "entry_delay_bars": 2,
        "atr_period": 8,
        "stop_loss_atr_multiplier": 1.1,
        "take_profit_atr_multiplier": 2.0,
        "min_natr_threshold": 0.7,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
    },
    "AggTradeReversal": {
        "enabled": False,
        "candle_timeframe": "1m",
        "spike_trades_count": 5,
        "fade_trades_count": 15,
        "spike_price_deviation_atr": 1.0,
        "volume_increase_multiplier": 2.0,
        "entry_mode": "MARKET",
        "limit_entry_offset_atr": 0.3,
        "stop_loss_atr_multiplier": 1.0,
        "take_profit_atr_multiplier": 1.5,
        "min_natr_threshold": 1.2,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
    },
    "FirstPullbacksInTrend": {
        "enabled": False,
        "sma_fast_period": 10,
        "sma_slow_period": 50,
        "rsi_period": 14,
        "rsi_lower_bound": 25,
        "rsi_upper_bound": 70,
        "pullback_check_mode": "SMA",
        "pullback_sma_touch_allowance": 0.03,
        "pullback_bars_count": 3,
        "confirmation_bar_required": False,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_atr_multiplier": 2.5,
        "trend_timeframe": "30m",
        "entry_timeframe": "5m",
        "min_natr_threshold": 0.7,
        "risk_pct_per_trade": DEFAULT_RISK_PER_TRADE_PERCENT / 100.0,
        "partial_exit_rr_config": DEFAULT_PARTIAL_EXIT_RR_CONFIG,
        "small_risk_percent_tp_config": [
            [0.005, 0.5],  # Close 50% at +0.4%
            [0.01, 0.5],  # Close the remaining 50% at +0.8%
        ],
        "move_sl_to_be_on_first_tp": DEFAULT_MOVE_SL_TO_BE,
        "final_tp_rr": DEFAULT_FINAL_TP_RR,
    },
}

# ==============================================================================
# Logging Settings
# ==============================================================================
# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL = "INFO"  # Was INFO
# Path to the main bot log file
LOG_FILE_BOT = "logs/bot_module.log"
# Path to the CSV file for logging trades and events
LOG_FILE_TRADES = "logs/trades_and_events.csv"
# Path to the "Trader's Diary" CSV file
LOG_FILE_TRADER_DIARY = "logs/trader_diary.csv"
# Log message format
LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"

# ==============================================================================
# Backtester Settings
# ==============================================================================
# Initial balance for backtest
BACKTEST_INITIAL_BALANCE = 10000.0
# Initial balance for Paper Trading
PAPER_TRADING_INITIAL_BALANCE = 10000.0
# Exchange commission in % (0.00075 for 0.075%)
BACKTEST_COMMISSION_PCT = 0.0004
# Slippage in % (0.0003 for 0.03%)
BACKTEST_SLIPPAGE_PCT = 0.0001
# Whether to save backtest trade details to a CSV file
BACKTEST_SAVE_TRADES = False  # Was False
# Path template for saving backtest trade logs (if BACKTEST_SAVE_TRADES = True)
BACKTEST_TRADES_LOG_PATH_TEMPLATE = (
    "logs/backtest_trades/{strategy}_{symbol}_{timestamp}.csv"
)
# Minimum distance to stop in % of the entry price (for the backtester, if the strategy does not specify it)
BACKTEST_MIN_STOP_DISTANCE_PCT = 0.0003  # 0.03% (was 0.0005)
# Maximum position size in % of balance (for backtester, applied in _calculate_position_details)
BACKTEST_MAX_POSITION_SIZE_PCT_BALANCE = (
    10.0  # 300% (allows leverage if balance = margin) (was 0.5 = 50%)
)

# --- Settings for collecting data for the ML confirmation model via the backtester ---
# Whether to log data for training the ML confirmation model during a REGULAR backtest (non-ML mode)
BACKTEST_LOG_FOR_ML_CONFIRMATION_MODEL = True
# Path to the file for this data
BACKTEST_ML_CONFIRMATION_DATA_PATH = "logs/ml_confirmation_training_data.csv"

# ==============================================================================
# Trainer / Optimizer Settings
# ==============================================================================
# List of symbols for priority optimization/training
TRAINER_TARGET_SYMBOLS = [
    "SOLUSDT",
    "XRPUSDT",
    "MOODENGUSDT",
    "DOGEUSDT",
    "PEPEUSDT",
    "SUIUSDT",
    "NEIROUSDT",
    "TRUMPUSDT",
    "PEOPLEUSDT",
    "WIFUSDT",
    "PNUTUSDT",
    "ENAUSDT",
    "FARTCOINUSDT",
    "ADAUSDT",
]
# Whether automatic trainer launch by schedule is enabled (the schedule implementation itself is outside this config)
TRAINER_ENABLED = True
# Trainer start time by schedule (UTC)
TRAINER_SCHEDULE_TIME = "03:00"
# Depth of historical data in days used for analysis/optimization
TRAINER_DATA_LOOKBACK_DAYS = 2  # Was 90
# Number of days of data overlap during loading for optimization (for indicator warm-up)
OPTIMIZATION_DATA_OVERLAP_DAYS = 7  # Was 0
# File for saving optimized strategy parameters
OPTIMIZED_PARAMS_FILE = Path("data/optimized_params.json")
# Optimization method: "bayesian" (Optuna) or "grid" (grid search from logs)
TRAINER_OPTIMIZATION_METHOD = "bayesian"
# Minimum number of trades in logs/backtest for a valid optimization result
TRAINER_MIN_TRADES_OPTIMIZE = 10  # Was 20

# --- Optuna settings for Bayesian optimization ---
TRAINER_OPTUNA_CONFIG = {
    "n_trials": 100,  # Number of optimization attempts (iterations)
    "timeout": 10800,  # Maximum optimization time in seconds (3 hours)
    "n_jobs": 1,  # Number of parallel processes (-1 for all cores, 1 for sequential)
    "direction": "maximize",  # Optimization direction: "maximize" or "minimize"
    "metric_name": "profit_factor",  # Metric name for optimization (from backtester KPI)
    "use_pruning": True,  # Whether to use the Pruning mechanism (cutting off unpromising trials)
    "pruner_n_startup_trials": 15,  # Number of trials before Pruner activation
    "sampler_seed": int(time.time()),  # Seed for Sampler reproducibility
    "study_name_prefix": "backtest_opt",  # Prefix for the study name in Optuna
    "storage": "sqlite:///data/optuna_backtest_studies.db",  # Optuna storage (None for in-memory)
}
# Parameter search space for Optuna (for each strategy)
TRAINER_OPTUNA_SEARCH_SPACE = {
    "OnlineAgentStrategy": {
        "stop_loss_atr_multiplier": ("float", [0.8, 3.0]),
        "take_profit_atr_multiplier": ("float", [0.5, 4.0]),
        "min_probability_threshold": ("float", [0.55, 0.85]),
    },
    "VolumeBreakout": {
        "candle_timeframe": ("categorical", [["1m", "3m", "5m"]]),
        "retest_atr_percent": ("float", [0.0, 0.5]),
        "stop_loss_atr_multiplier": ("float", [0.8, 3.0]),
        "take_profit_atr_multiplier": ("float", [1.0, 4.0]),
        "min_natr_threshold": ("float", [0.5, 3.0]),
        "risk_pct_per_trade": ("float", [0.003, 0.015]),
    },
    "FakeBreakout": {
        "candle_timeframe": ("categorical", [["1m", "3m", "5m"]]),
        "lookback_candles": ("int", [3, 15]),
        "reversal_confirmation_bars": ("int", [0, 2]),
        "stop_loss_atr_multiplier": ("float", [0.7, 2.0]),
        "take_profit_atr_multiplier": ("float", [1.0, 3.0]),
        "min_natr_threshold": ("float", [0.8, 3.5]),
        "risk_pct_per_trade": ("float", [0.003, 0.015]),
    },
    "DensityBounce": {
        "min_density_size_usd": ("int", [100000, 2000000], {"step": 50000}),
        "max_touch_count": ("int", [1, 5]),
        "depth_levels_to_check": ("int", [5, 50], {"step": 5}),
        "sl_ticks_multiplier": ("int", [3, 15]),
        "tp_ticks_multiplier": ("int", [5, 25]),
    },
    "ConsolidationImpulse": {
        "range_bars": ("int", [8, 30]),
        "max_range_atr_multiplier": ("float", [0.5, 1.2]),
        "impulse_volume_multiplier": ("float", [1.5, 3.5]),
        "impulse_candle_min_body_atr": ("float", [0.2, 0.8]),
        "entry_delay_bars": ("int", [0, 3]),
        "atr_period": ("int", [7, 20]),
        "min_natr_threshold": ("float", [0.4, 2.5]),
        "candle_timeframe": ("categorical", [["1m", "3m", "5m"]]),
        "stop_loss_atr_multiplier": ("float", [0.8, 2.5]),
        "take_profit_atr_multiplier": ("float", [1.0, 4.0]),
        "risk_pct_per_trade": ("float", [0.003, 0.015]),
    },
    "AggTradeReversal": {
        "spike_trades_count": ("int", [3, 10]),
        "fade_trades_count": ("int", [10, 30]),
        "spike_price_deviation_atr": ("float", [0.3, 1.2]),
        "volume_increase_multiplier": ("float", [1.8, 4.0]),
        "entry_mode": ("categorical", [["MARKET", "LIMIT_RETEST"]]),
        "limit_entry_offset_atr": ("float", [0.05, 0.3]),
        "min_natr_threshold": ("float", [0.8, 3.0]),
        "stop_loss_atr_multiplier": ("float", [0.7, 2.0]),
        "take_profit_atr_multiplier": ("float", [0.9, 3.0]),
        "risk_pct_per_trade": ("float", [0.003, 0.015]),
        "candle_timeframe": ("categorical", [["1m"]]),
    },
    "FirstPullbacksInTrend": {
        "sma_fast_period": ("int", [7, 30]),
        "sma_slow_period": ("int", [30, 150]),
        "rsi_period": ("int", [7, 21]),
        "rsi_lower_bound": ("int", [20, 40]),
        "rsi_upper_bound": ("int", [60, 80]),
        "pullback_check_mode": ("categorical", [["SMA", "BARS"]]),
        "pullback_sma_touch_allowance": ("float", [0.01, 0.1]),
        "pullback_bars_count": ("int", [2, 7]),
        "confirmation_bar_required": ("categorical", [[True, False]]),
        "min_natr_threshold": ("float", [0.5, 2.0]),
        "trend_timeframe": ("categorical", [["5m", "15m", "30m"]]),
        "entry_timeframe": ("categorical", [["1m", "3m"]]),
        "stop_loss_atr_multiplier": ("float", [0.8, 2.0]),
        "take_profit_atr_multiplier": ("float", [1.2, 3.0]),
        "risk_pct_per_trade": ("float", [0.003, 0.015]),
    },
}
# Parameter grid for Grid Search (if TRAINER_OPTIMIZATION_METHOD = "grid")
TRAINER_PARAM_GRID = {
    "VolumeBreakout": {
        "stop_loss_atr_multiplier": [1.0, 1.3, 1.6],
        "take_profit_atr_multiplier": [1.5, 2.0, 2.5],
    },
    "FakeBreakout": {
        "stop_loss_atr_multiplier": [0.8, 1.1, 1.4],
        "take_profit_atr_multiplier": [1.2, 1.6, 2.0],
    },
    "ReverseVolumeBreakout": {
        "reverse_sl_to_tp_ratio": [1.5, 2.0, 2.5],
        "risk_pct_per_trade": [0.005, 0.01, 0.015],
    },
    "ReverseFakeBreakout": {
        "reverse_sl_to_tp_ratio": [1.5, 2.0, 2.5],
        "risk_pct_per_trade": [0.005, 0.01, 0.015],
    },
    "ConsolidationImpulse": {
        "stop_loss_atr_multiplier": [1.0, 1.3, 1.6],
        "take_profit_atr_multiplier": [1.8, 2.2, 2.7],
    },
    "AggTradeReversal": {
        "stop_loss_atr_multiplier": [0.8, 1.0, 1.3],
        "take_profit_atr_multiplier": [1.0, 1.3, 1.6, 2.0],
    },
    "FirstPullbacksInTrend": {
        "stop_loss_atr_multiplier": [0.9, 1.1, 1.4],
        "take_profit_atr_multiplier": [1.3, 1.6, 2.0],
    },
}

# --- Settings for OFFLINE training of the ML agent (OnlineAgentStrategy) ---
# Duration of one data chunk for training (in weeks)
ML_TRAINING_CHUNK_WEEKS = 0.5  # Was 2
# Data overlap between chunks (in days)
ML_TRAINING_OVERLAP_DAYS = 1  # Was 7
# How many candles to look ahead to determine the y_true label (0 or 1)
ML_TRAINING_LABEL_LOOKAHEAD_BARS = 60  # Was 15
# Whether to simulate trades during ML data collection (for "on-the-fly" performance evaluation)
ML_TRAINING_SIMULATE_TRADES = False  # Was True
# Path to the file for simulated trade logs (if ML_TRAINING_SIMULATE_TRADES = True)
ML_SIMULATED_TRADES_LOG_FILE = Path("logs/ml_simulated_trades.csv")  # Was None
# File for saving the ML agent offline training report
ML_TRAINING_REPORT_FILE = Path("logs/ml_training_report.json")

# ==============================================================================
# Local Historical Data Settings
# ==============================================================================
# Whether to use locally saved CSV files instead of downloading via API
USE_LOCAL_HISTORICAL_DATA = False
# Path to the root folder with local historical data
# Structure: LOCAL_HISTORICAL_DATA_PATH / SYMBOL_UPPERCASE / data_type.csv (e.g., kline_1m.csv)
LOCAL_HISTORICAL_DATA_PATH = "data_storage"  # Was "data/historical_csv"

# ==============================================================================
# Local Historical Data Storage Settings (HYBRID SYSTEM)
# ==============================================================================
# Enable/disable the use of a "smart" loader with a local Parquet cache
USE_SMART_DATA_LOADER = True
# Root path to the local data storage (Data Lake)
LOCAL_DATA_STORAGE_PATH = "data_storage"

# Settings for the ETL pipeline
# Base URL for downloading ZIP archives
BULK_DATA_DOWNLOAD_URL = "https://data.binance.vision"
# Path templates for DAILY archives
BULK_KLINES_DAILY_PATH_TEMPLATE = "data/futures/um/daily/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{date_str}.zip"
BULK_AGGTRADES_DAILY_PATH_TEMPLATE = (
    "data/futures/um/daily/aggTrades/{symbol}/{symbol}-aggTrades-{date_str}.zip"
)
# Path templates for MONTHLY archives
BULK_KLINES_MONTHLY_PATH_TEMPLATE = "data/futures/um/monthly/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{date_str}.zip"
BULK_AGGTRADES_MONTHLY_PATH_TEMPLATE = (
    "data/futures/um/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{date_str}.zip"
)

# ==============================================================================
# Model Pipeline Adaptation Settings (for OnlineAgentStrategy and ML Confirmation)
# ==============================================================================
# Whether feature adaptation (removal/addition) is enabled on the fly
ADAPTATION_ENABLED = True
# After how many processed trades to check the need for adaptation
ADAPTATION_CHECK_INTERVAL = 50
# Minimum number of history records (features+PnL) for calculating correlations
MIN_HISTORY_FOR_CORR = 100
# Maximum size of feature history and PnL (in number of trades)
FEATURE_HISTORY_MAX_SIZE = 2000
# How many of the worst features to remove per adaptation iteration
NUM_FEATURES_TO_REMOVE = 1
# How many new (random from available) features to add per iteration
NUM_FEATURES_TO_ADD = 1
# Minimum correlation threshold (absolute value). Features with correlation BELOW this value (and negative) can be removed.
MIN_CORRELATION_THRESHOLD = (
    -0.01
)  # Example: features with correlation < -0.01 and low absolute correlation

# ==============================================================================
# Queue Sizes (for asynchronous queues)
# ==============================================================================
# Maximum queue size for market data from DataConsumer to Controller
MARKET_DATA_QUEUE_MAX_SIZE = 1000
# Maximum queue size for signals from Controller to TradeLogger/Executor
SIGNAL_QUEUE_MAX_SIZE = 100
# Maximum queue size for UserDataStream events from Executor to Controller
USER_DATA_QUEUE_MAX_SIZE = 500

# ==============================================================================
# Portfolio Backtester Settings
# ==============================================================================
# Default exchange rules if not specified per contract in PortfolioBacktester
DEFAULT_EXCHANGE_RULES: Dict[str, Any] = {
    "BTCUSDT": {
        "tick_size": "0.01",
        "min_qty": "0.00001",
        "step_size": "0.00001",
        "min_notional": "10.0",
    },
    "ETHUSDT": {
        "tick_size": "0.01",
        "min_qty": "0.0001",
        "step_size": "0.0001",
        "min_notional": "10.0",
    },
    # Add other commonly used symbols or a generic default
    "default": {
        "tick_size": "0.00000001",
        "min_qty": "0.001",
        "step_size": "0.001",
        "min_notional": "1.0",
    },
}

# Default path for L2 historical data storage, used by PortfolioBacktester if l2_storage_path is not given directly
L2_STORAGE_PATH_CONFIG: Optional[str] = (
    "L2_data_store"  # Or None if it must be explicitly passed
)

# Default global risk limits for PortfolioBacktester if not provided in the run request
DEFAULT_PORTFOLIO_GLOBAL_RISK_LIMITS: Dict[str, Any] = {
    "max_total_exposure_pct": 0.50,  # Max 50% of portfolio balance can be tied up in positions
    "max_concurrent_positions": 10,  # Max 10 concurrent open positions
    "commission_pct": 0.00075,  # Default commission for portfolio trades
    "risk_pct_per_trade": 0.01,  # Default risk per trade (0.01 = 1%) for position sizing
}

# ==============================================================================
# Helper Functions (for loading/getting parameters)
# ==============================================================================
DEFAULT_TICK_SIZE = 0.00000001  # General default tick_size if not found for the symbol

# --- Loading optimized parameters ---
# These variables are used for caching optimized parameters in memory
_optimized_params_data: Dict[str, Any] = {}
_optimized_params_last_mtime: float = 0.0


def load_optimized_params():
    global _optimized_params_data, _optimized_params_last_mtime
    opt_file_path = str(OPTIMIZED_PARAMS_FILE)
    try:
        if not os.path.exists(opt_file_path):
            if _optimized_params_last_mtime != 0:
                logger.info(
                    f"Optimized parameters file {opt_file_path} not found or removed. Resetting params."
                )
                _optimized_params_data = {}
                _optimized_params_last_mtime = 0
            return
        current_mtime = os.path.getmtime(opt_file_path)
        if current_mtime > _optimized_params_last_mtime:
            with open(opt_file_path, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict) and "optimized_params" in loaded_data:
                    _optimized_params_data = loaded_data["optimized_params"]
                    _optimized_params_last_mtime = current_mtime
                    logger.info(
                        f"Successfully reloaded optimized parameters from {opt_file_path}"
                    )
                else:
                    logger.warning(
                        f"Unexpected format in {opt_file_path}. Using previous or default params."
                    )
    except FileNotFoundError:
        if _optimized_params_last_mtime != 0:
            _optimized_params_data = {}
            _optimized_params_last_mtime = 0
            logger.info(
                f"Optimized parameters file {opt_file_path} not found. Resetting params."
            )
    except json.JSONDecodeError:
        logger.error(
            f"Error decoding JSON from {opt_file_path}. Using previous/default."
        )
    except Exception as e:
        logger.error(f"Error loading optimized parameters: {e}", exc_info=True)


def get_strategy_param(strategy_name: str, param_name: str, default: any = None) -> any:
    # First, check optimized parameters
    optimized_strategy_params = _optimized_params_data.get(strategy_name, {})
    value = optimized_strategy_params.get(param_name)
    if value is not None:
        # logger.debug(f"Using OPTIMIZED param for {strategy_name}: {param_name} = {value}")
        return value

    # Then check the default strategy parameters
    default_strategy_params = STRATEGY_DEFAULTS.get(strategy_name, {})
    value = default_strategy_params.get(param_name)
    if value is not None:
        # logger.debug(f"Using DEFAULT param for {strategy_name}: {param_name} = {value}")
        return value

    # Checking global parameters (e.g., score thresholds that are not specific to a single strategy)
    # These parameters should not be overridden at the strategy level in STRATEGY_DEFAULTS if they are global
    if (
        strategy_name == "OnlineAgentStrategy"
    ):  # Only for the ML agent, so it can receive these global configs
        if param_name == "signal_quality_thresholds":
            return SIGNAL_QUALITY_THRESHOLDS
        if param_name == "signal_quality_weights":
            return SIGNAL_QUALITY_WEIGHTS
        if param_name == "signal_quality_max_score":
            return SIGNAL_QUALITY_MAX_SCORE

    # If nothing is found, return the passed default value
    # logger.debug(f"Param {param_name} for {strategy_name} NOT FOUND in optimized or defaults. Using provided default: {default}")
    return default
