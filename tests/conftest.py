# tests/conftest.py
# ruff: noqa: E402

import os
from dotenv import load_dotenv

load_dotenv(override=True)
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from typing import Any, Dict, Optional

# Set fake environment variables, the NAMES of which
# EXACTLY MATCH those expected in api/database.py.
print("MONKEYPATCHING ENV VARS FOR PYTEST COLLECTION (v2)")
os.environ["POSTGRES_USER"] = "testuser"
os.environ["POSTGRES_PASSWORD"] = "testpassword"
os.environ["POSTGRES_DB"] = "testdb"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["TESTING"] = "true"
os.environ["RATELIMIT_ENABLED"] = "false"
os.environ["JWT_SECRET_KEY"] = "test_secret_key_1234567890_test_secret_key"
os.environ["API_ENCRYPTION_KEY"] = "fFEvqTGV-LGkN0ASdZrlOUhEpllCyi1Dj-PmKY3eh6Y="


# Now the import will pass without errors
import logging
import pytest

# from dotenv import load_dotenv # Removed
import os
import pandas as pd
import json

# Logger configuration for conftest itself, if needed
conftest_logger = logging.getLogger("conftest")
if not conftest_logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    conftest_logger.addHandler(handler)
    conftest_logger.setLevel(logging.INFO)

# Create a basic configuration so that logs are output somewhere at all
# This is important because pytest can capture output if there is no basic configuration
logging.basicConfig(
    level=logging.INFO,  # Set the default level to INFO
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,  # Output to standard output stream
)

# Set a higher level for "noisy" libraries.
# This will force them to output only WARNING messages and above (errors).
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

# Other libraries can be added if they are "noisy"
# logging.getLogger('httpx').setLevel(logging.WARNING)

# Set the level for our own module to see its INFO messages
logging.getLogger("bot_module").setLevel(logging.INFO)

# conftest_logger.info(f"[Conftest] Attempting to load .env file from: {os.getcwd()}") # Removed
# if os.path.exists(".env"): # Removed
#     conftest_logger.info("[Conftest] .env file FOUND.") # Removed
#     load_dotenv_success = load_dotenv(override=True) # Removed
#     conftest_logger.info(f"[Conftest] load_dotenv() returned: {load_dotenv_success}") # Removed
# else: # Removed
#     conftest_logger.warning("[Conftest] .env file NOT FOUND in current directory. Ensure it exists if you rely on it for API keys.") # Removed

# conftest_logger.debug(f"[Conftest] BOT_BINANCE_SPOT_API_KEY from env after load: ...{os.getenv('BOT_BINANCE_SPOT_API_KEY')[-4:] if os.getenv('BOT_BINANCE_SPOT_API_KEY') else 'Not Set'}") # Removed
# conftest_logger.debug(f"[Conftest] BOT_BINANCE_FUTURES_API_KEY from env after load: ...{os.getenv('BOT_BINANCE_FUTURES_API_KEY')[-4:] if os.getenv('BOT_BINANCE_FUTURES_API_KEY') else 'Not Set'}") # Removed


# --- NEW IMPORTS FOR THE TEST DB ---
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from api.security import create_access_token
from api.database import Base, get_db


def pytest_addoption(parser):
    parser.addoption(
        "--exchange",
        action="store",
        default=os.getenv("E2E_EXCHANGE", "binance"),
        choices=("binance", "bybit"),
        help="Exchange profile for live e2e tests. Defaults to binance.",
    )


@pytest.fixture
def e2e_exchange_profile(pytestconfig, monkeypatch):
    exchange = str(pytestconfig.getoption("--exchange") or "binance").lower()
    profiles = {
        "binance": {
            "exchange": "binance_futures",
            "exchange_by_market": {
                "spot": "binance_spot",
                "futures_usdtm": "binance_futures",
            },
            "display_name": "Binance",
            "api_key_env": "TESTNET_BINANCE_FUTURES_API_KEY",
            "api_secret_env": "TESTNET_BINANCE_FUTURES_API_SECRET",
            "market_type": "futures_usdtm",
            "supports_algo_orders": True,
            "supports_exchange_trailing_stop": True,
        },
        "bybit": {
            "exchange": "bybit_linear",
            "exchange_by_market": {
                "spot": "bybit_spot",
                "futures_usdtm": "bybit_linear",
            },
            "display_name": "Bybit",
            "api_key_env": "TESTNET_BYBIT_API_KEY",
            "api_secret_env": "TESTNET_BYBIT_API_SECRET",
            "market_type": "futures_usdtm",
            "supports_algo_orders": False,
            "supports_exchange_trailing_stop": False,
        },
    }
    profile = profiles[exchange].copy()
    api_key = os.getenv(profile["api_key_env"])
    api_secret = os.getenv(profile["api_secret_env"])
    if not api_key or not api_secret:
        pytest.skip(
            f"{profile['display_name']} e2e keys are not set. "
            f"Expected {profile['api_key_env']} and {profile['api_secret_env']}."
        )

    profile["api_key"] = api_key
    profile["api_secret"] = api_secret

    from bot_module import config as global_bot_config

    monkeypatch.setattr(global_bot_config, "ACTIVE_TRADING_ENVIRONMENT", "testnet")
    monkeypatch.setattr(
        global_bot_config, "TRADING_MARKET_TYPE", profile["market_type"]
    )
    monkeypatch.setattr(global_bot_config, "BINANCE_ACTIVE_API_KEY", api_key)
    monkeypatch.setattr(global_bot_config, "BINANCE_ACTIVE_API_SECRET", api_secret)
    monkeypatch.setattr(global_bot_config, "SYMBOL_COOLDOWN_SECONDS", 1)
    return profile


from api import models
from api.depthsight_api import app as fastapi_app
from pathlib import Path

# Define the project root folder (it is one level higher than the tests folder)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from datetime import datetime, timezone, timedelta  # Ensured timedelta is here
import random
from bot_module.logger_setup import setup_bot_logging
from bot_module import config as bot_config
from unittest.mock import (
    MagicMock,
    PropertyMock,
    AsyncMock,
)  # Added AsyncMock here
from celery.result import AsyncResult
from api.dependencies import require_permission
import subprocess
import time
import requests
import pytest_asyncio
import uuid

try:
    import _pytest.tmpdir as pytest_tmpdir_module
    import _pytest.pathlib as pytest_pathlib_module

    pytest_tmpdir_module.cleanup_dead_symlinks = lambda *args, **kwargs: None
    pytest_pathlib_module.cleanup_dead_symlinks = lambda *args, **kwargs: None
except Exception:
    pass

from api import crud, schemas
from api.push_sender import send_push_notification
from bot_module.runtime_dependencies import configure_runtime_dependencies

configure_runtime_dependencies(
    crud_module=crud,
    get_db_factory=get_db,
    push_sender=send_push_notification,
)

try:
    from bot_module.controller import TradingController
    from bot_module.ml_strategy import OnlineAgentStrategy
    from bot_module.utils import round_dynamic
except ImportError:
    OnlineAgentStrategy = MagicMock()  # type: ignore

    def round_dynamic(x, y, z=None):
        return x


logger_configured = False


# MockStream class for Redis parser
class MockStream:
    def at_eof(self):
        # print("DEBUG: MockStream.at_eof() called, returning False (stream active but may be empty)")
        return False  # Simulate stream active but possibly empty


# @pytest.fixture(scope="session", autouse=True)
# def mock_redis_connection_globally():
#    async def mock_connect_global(self, *args, **kwargs):
#        # This mock simulates a successful connection without network call
#        # It also handles internal state expected by redis-py's parser
#        if hasattr(self, '_parser') and self._parser is not None:
#            self._parser._connected = True # type: ignore
#            if not hasattr(self._parser, '_stream') or self._parser._stream is None: # type: ignore
#                 self._parser._stream = MockStream() # type: ignore
#        # print(f"DEBUG: Global mock_connect_global called by {self}, returning True")
#        return True
#
#    with patch('redis.asyncio.connection.Connection.connect', mock_connect_global) as p:
#        # print("DEBUG: redis.asyncio.connection.Connection.connect PATCHED globally for session")
#        yield p
#        # print("DEBUG: redis.asyncio.connection.Connection.connect UNPATCHED globally for session")


@pytest_asyncio.fixture(scope="function")
async def mock_redis_client():
    """
    Creates a Redis mock with automatic state cleanup after each test.
    This is the canonical way to ensure test isolation in pytest.
    """
    mock = MagicMock(spec=redis.Redis)
    mock._data = {}
    mock.publish_calls = []

    async def _publish_mock(channel, message):
        mock.publish_calls.append((channel, message))
        return 1

    async def _get_mock(key):
        return mock._data.get(key)

    async def _set_mock(key, value, **kwargs):
        if kwargs.get("nx") and key in mock._data:
            return False
        mock._data[key] = value
        return True

    async def _delete_mock(*keys):
        deleted_count = 0
        for key in keys:
            if key in mock._data:
                del mock._data[key]
                deleted_count += 1
        return deleted_count

    async def _incr_mock(key):
        current_value_str = mock._data.get(key, "0")
        new_value = int(current_value_str) + 1
        mock._data[key] = str(new_value)
        return new_value

    async def _decr_mock(key):
        current_value_str = mock._data.get(key, "0")
        new_value = int(current_value_str) - 1
        mock._data[key] = str(new_value)
        return new_value

    async def _expire_mock(key, seconds):
        return 1 if key in mock._data else 0

    async def _keys_mock(pattern):
        import fnmatch

        return [k for k in mock._data.keys() if fnmatch.fnmatch(k, pattern)]

    async def _mget_mock(keys):
        return [mock._data.get(k) for k in keys]

    async def _set_initial_data(key, data):
        mock._data[key] = json.dumps(data)

    mock.publish = AsyncMock(side_effect=_publish_mock)
    mock.get = AsyncMock(side_effect=_get_mock)
    mock.set = AsyncMock(side_effect=_set_mock)
    mock.delete = AsyncMock(side_effect=_delete_mock)
    mock.incr = AsyncMock(side_effect=_incr_mock)
    mock.decr = AsyncMock(side_effect=_decr_mock)
    mock.expire = AsyncMock(side_effect=_expire_mock)
    mock.keys = AsyncMock(side_effect=_keys_mock)
    mock.mget = AsyncMock(side_effect=_mget_mock)
    mock.ping = AsyncMock(return_value=True)
    mock.set_initial_data = _set_initial_data
    yield mock
    # Cleanup is not required as the mock is local to the test


@pytest_asyncio.fixture(scope="function")
async def override_redis_client(app: FastAPI, mock_redis_client):
    """
    Injects mock_redis_client into FastAPI dependencies.
    This ensures that API endpoints use the same mock
    that we configure in tests.
    """
    from api.redis_client import get_redis_client

    async def _override():
        return mock_redis_client

    # Save the original dependency (if it needs to be restored)
    app.dependency_overrides[get_redis_client] = _override
    yield mock_redis_client
    # Clear override after the test
    app.dependency_overrides.pop(get_redis_client, None)


# Define mock_make_api_request at module level

# Removing the global mock_redis_connection_globally fixture as fakeredis should handle this.
# If other tests need to mock actual redis connections, they should do so more specifically.
# For now, this broad patch seems to cause issues with fakeredis's own connection handling.
# The mock_connect_global function itself is also removed.

# @pytest.fixture(scope="session", autouse=True)
# def mock_redis_connection_globally():
#     async def mock_connect_global(self, *args, **kwargs):
#         # This mock simulates a successful connection without network call
#         # It also handles internal state expected by redis-py's parser
#         if hasattr(self, '_parser') and self._parser is not None:
#             self._parser._connected = True # type: ignore
#             if not hasattr(self._parser, '_stream') or self._parser._stream is None: # type: ignore
#                  self._parser._stream = MockStream() # type: ignore
#         # print(f"DEBUG: Global mock_connect_global called by {self}, returning True")
#         return True
#
#     with patch('redis.asyncio.connection.Connection.connect', mock_connect_global) as p:
#         # print("DEBUG: redis.asyncio.connection.Connection.connect PATCHED globally for session")
#         yield p
#         # print("DEBUG: redis.asyncio.connection.Connection.connect UNPATCHED globally for session")


@pytest.fixture
def mock_require_permission(app: FastAPI):
    """
    A fixture that uses the canonical FastAPI way to override
    a dependency. It completely disables permission and quota checks.
    """

    # This "fake" dependency does nothing and just returns None
    async def fake_dependency():
        return None

    # Replace the real dependency with our fake one
    app.dependency_overrides[require_permission] = fake_dependency
    yield
    # After the test is finished, clear the mock so as not to affect other tests
    app.dependency_overrides = {}


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session):
    """
    Fixture for creating a test user in the DB for a single test.
    """
    # 1. Create data for a new user
    unique_id = uuid.uuid4().hex[:6]
    user_create_schema = schemas.UserCreate(
        username=f"testuser_{unique_id}",
        email=f"testuser_{unique_id}@example.com",
        password="testpassword123",
        ref_code="test",
    )

    # 2. Use the CRUD function to create a user
    db_user = await crud.create_user(db_session, user_create_schema)

    # Ensure user is active for tests
    db_user.is_active = True

    # ADDED: At least one active API key is now required to start strategies
    api_key = models.ApiKey(
        user_id=db_user.id,
        name="Default Test Key",
        exchange="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="test...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key)

    await db_session.commit()
    await db_session.refresh(db_user)

    # 3. Pass the created user to the test
    yield db_user


@pytest.fixture(scope="function")
def mock_celery_tasks(mocker):
    """
    Mocks celery_app.send_task so tasks don't run,
    and returns an object mimicking AsyncResult with an .id attribute.
    """
    mock_result_obj = MagicMock(spec=AsyncResult)
    mock_result_obj.id = f"mock-celery-task-{uuid.uuid4().hex[:6]}"
    mock_result_obj.state = "SUCCESS"

    mocker.patch("api.celery_app.celery_app.send_task", return_value=mock_result_obj)

    yield mock_result_obj


@pytest.fixture(scope="session", autouse=True)
def configure_celery_for_tests():
    """
    Configures Celery for tests ONCE per session.
    Uses eager mode, which is useful for E2E tests,
    but will be overridden by mocks in API unit tests.
    """
    try:
        from tasks import celery_app as app_celery

        # If Celery is already configured, do nothing
        if app_celery.conf.task_always_eager:
            return

        app_celery.conf.broker_url = "memory://"
        app_celery.conf.result_backend = "rpc://"
        app_celery.conf.task_always_eager = True
        conftest_logger.info("[Conftest] Celery configured for eager execution.")
    except ImportError:
        conftest_logger.error("[Conftest] Celery app could not be imported.")
    except Exception as e:
        conftest_logger.error(
            f"[Conftest] Error configuring Celery: {e}", exc_info=True
        )


@pytest_asyncio.fixture(scope="function")
async def ensure_testnet_ready():
    """
    E2E precheck for Testnet:
    1) checks server time endpoint availability
    2) validates local/server clock skew
    3) performs a lightweight signed probe to detect -1021 and account-side unavailability
    """

    async def _check(executor, market_type: Optional[str] = None) -> Dict[str, Any]:
        effective_market = market_type or getattr(executor, "market_type", "unknown")
        max_skew_ms = int(os.getenv("E2E_MAX_SERVER_TIME_SKEW_MS", "3000"))
        log_prefix = f"[E2EPrecheck:{effective_market}]"

        try:
            server_resp = await asyncio.wait_for(
                executor.get_server_time(), timeout=10.0
            )
        except asyncio.TimeoutError:
            pytest.skip(f"{log_prefix} Server time request timed out. Skipping E2E.")

        if not isinstance(server_resp, dict):
            pytest.skip(
                f"{log_prefix} Invalid server time response: {type(server_resp).__name__}"
            )
        if server_resp.get("error"):
            pytest.skip(f"{log_prefix} Server time endpoint unavailable: {server_resp}")

        try:
            server_time_ms = int(server_resp.get("serverTime"))
        except (TypeError, ValueError):
            pytest.skip(
                f"{log_prefix} Missing/invalid serverTime in response: {server_resp}"
            )

        local_time_ms = int(time.time() * 1000)
        skew_ms = local_time_ms - server_time_ms
        if abs(skew_ms) > max_skew_ms:
            pytest.skip(
                f"{log_prefix} Local clock skew too high ({skew_ms}ms, limit={max_skew_ms}ms). "
                "Likely to trigger Binance -1021."
            )

        probe_endpoint = (
            "/fapi/v2/balance"
            if effective_market == "futures_usdtm"
            else "/api/v3/account"
        )
        try:
            signed_probe = await asyncio.wait_for(
                executor._request("GET", probe_endpoint, signed=True), timeout=20.0
            )
        except asyncio.TimeoutError:
            pytest.skip(
                f"{log_prefix} Signed probe timed out on {probe_endpoint}. Skipping E2E."
            )

        if signed_probe is None:
            pytest.skip(f"{log_prefix} Signed probe returned None on {probe_endpoint}.")

        if isinstance(signed_probe, dict) and signed_probe.get("error"):
            code = signed_probe.get("code")
            msg = str(signed_probe.get("msg", ""))
            if code == -1021 or "Timestamp" in msg:
                pytest.skip(
                    f"{log_prefix} Testnet clock/timestamp mismatch (-1021): {msg}"
                )
            pytest.skip(f"{log_prefix} Signed probe failed on Testnet: {signed_probe}")

        conftest_logger.info(
            f"{log_prefix} Precheck OK. serverTime={server_time_ms}, localTime={local_time_ms}, skew={skew_ms}ms"
        )
        return {
            "server_time_ms": server_time_ms,
            "local_time_ms": local_time_ms,
            "skew_ms": skew_ms,
            "probe_endpoint": probe_endpoint,
        }

    return _check


@pytest.fixture(scope="session", autouse=True)
def configure_logging_and_celery_for_tests(tmp_path_factory):
    global logger_configured
    if not logger_configured:
        conftest_logger.info(
            "[Conftest Fixture] Configuring bot_module logging for test session..."
        )
        try:
            log_dir = tmp_path_factory.mktemp("test_logs")
        except OSError:
            log_dir = PROJECT_ROOT / ".pytest_tmp" / "test_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            conftest_logger.warning(
                f"[Conftest Fixture] Falling back to workspace temp dir for logs: {log_dir}"
            )
        bot_config.LOG_FILE_BOT = str(log_dir / "test_bot_module.log")
        bot_config.LOG_FILE_TRADES = str(log_dir / "test_trades_and_events.csv")
        conftest_logger.info(
            f"[Conftest Fixture] Overriding bot log path for tests to: {bot_config.LOG_FILE_BOT}"
        )
        conftest_logger.info(
            f"[Conftest Fixture] Overriding trade log path for tests to: {bot_config.LOG_FILE_TRADES}"
        )
        try:
            setup_bot_logging()
            logger_configured = True
            conftest_logger.info(
                "[Conftest Fixture] Bot module logging configured successfully."
            )

            # --- START: DEBUG LOGGING FOR CONTROLLER AND RISK MANAGER ---
            logging.getLogger("bot_module.controller").setLevel(logging.DEBUG)
            logging.getLogger("bot_module.risk_manager").setLevel(logging.DEBUG)
            conftest_logger.info(
                "[Conftest Fixture] Set bot_module.controller and bot_module.risk_manager log levels to DEBUG."
            )
            # --- END: DEBUG LOGGING ---
        except Exception as e:
            conftest_logger.error(
                f"[Conftest Fixture] Error configuring bot_module logging: {e}",
                exc_info=True,
            )
    else:
        conftest_logger.info(
            "[Conftest Fixture] Bot module logging already configured for this session."
        )

    conftest_logger.info("[Conftest Fixture] Configuring Celery for test session...")
    try:
        from tasks import celery_app as app_celery

        app_celery.conf.broker_url = "memory://"
        app_celery.conf.result_backend = "rpc://"
        app_celery.conf.task_always_eager = True
        conftest_logger.info(
            f"[Conftest Fixture] Celery broker_url set to: {app_celery.conf.broker_url}"
        )
        conftest_logger.info(
            f"[Conftest Fixture] Celery result_backend set to: {app_celery.conf.result_backend}"
        )
        conftest_logger.info(
            f"[Conftest Fixture] Celery task_always_eager set to: {app_celery.conf.task_always_eager}"
        )
        conftest_logger.info(
            "[Conftest Fixture] Celery configured for in-memory broker, rpc backend, and eager execution."
        )
    except ImportError:
        conftest_logger.error(
            "[Conftest Fixture] Celery app ('tasks.celery_app') could not be imported. Celery not configured for tests."
        )
    except Exception as e:
        conftest_logger.error(
            f"[Conftest Fixture] Error configuring Celery: {e}", exc_info=True
        )


import asyncio
from fastapi import FastAPI
import redis.asyncio as redis


try:
    from tasks import celery_app
except ImportError:
    celery_app = MagicMock()

VALID_API_KEY = "your-super-secret-api-key"


@pytest.fixture(scope="session")
def app() -> FastAPI:
    # Disable rate limiting in tests
    if hasattr(fastapi_app.state, "limiter"):
        fastapi_app.state.limiter._enabled = False
    return fastapi_app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def app_lifespan(app: FastAPI):
    """
    Runs the application lifespan once for the entire test session.
    This initializes global resources (e.g., an aiohttp session).
    """
    async with app.router.lifespan_context(app):
        yield


@pytest.fixture(scope="function", autouse=True)
def block_real_api_calls(monkeypatch):
    """
    This fixture is automatically applied to all tests (autouse=True).
    It globally patches the low-level API request function,
    ensuring that no test can make a real network call.
    """
    # Patch both functions in different modules where they might be used
    monkeypatch.setattr(
        "bot_module.data_loader._make_api_request", mock_make_api_request_global
    )
    monkeypatch.setattr(
        "bot_module.trainer._make_api_request", mock_make_api_request_global
    )
    yield  # Test is executed here


async def override_get_db():
    async with TestAsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def current_user(db_session: AsyncSession) -> models.User:
    """
    Returns the user object with ID=1, which is created in setup_database.
    """
    user = await db_session.get(models.User, 1)
    assert user is not None, "User with ID=1 was not found in the test DB."
    return user


@pytest_asyncio.fixture(scope="function")
async def created_strategy_config(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    current_user: models.User,
):
    """
    Fixture for creating and subsequently cleaning up the test strategy configuration.
    """
    payload = {
        "name": f"Testable Config {uuid.uuid4()}",
        "config_data": {
            "strategy_name": "VolumeBreakout",
            "symbol": "BTC/USDT",
            "market_type": "futures",
            "params": {"candle_timeframe": "5m"},
        },
    }
    response = await authenticated_client.post(
        "/api/v1/strategies/config", json=payload
    )
    assert response.status_code == 201, (
        f"Failed to create strategy config: {response.text}"
    )
    created_config_data = response.json()["data"]

    yield created_config_data

    # Cleanup
    config_id = created_config_data["id"]
    await crud.delete_strategy_config(
        db_session, user_id=current_user.id, config_id=config_id
    )
    await db_session.commit()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """
    Provides a real, transactional session to the in-memory test DB.
    """
    async with TestAsyncSessionLocal() as session:
        yield session
        # After the test, the transaction is automatically rolled back thanks to autouse=True in setup_database


# Create a factory for clients to avoid code duplication
@pytest_asyncio.fixture(scope="function")
async def authenticated_client_factory(app: FastAPI, mock_redis_client, mocker):
    """
    FACTORY for creating authenticated clients.
    """
    app.dependency_overrides[get_db] = override_get_db
    mocker.patch("api.database.engine", new=test_engine)
    mocker.patch("api.database.AsyncSessionLocal", new=TestAsyncSessionLocal)
    from api.redis_client import get_redis_client as original_get_redis_for_override
    from api.dependencies import (
        get_redis_client_for_quota as original_get_redis_quota_for_override,
    )

    app.dependency_overrides[original_get_redis_for_override] = lambda: (
        mock_redis_client
    )
    app.dependency_overrides[original_get_redis_quota_for_override] = lambda: (
        mock_redis_client
    )

    async def _create_client(user: models.User) -> AsyncClient:
        token = create_access_token(data={"sub": user.username})
        # ASGITransport(app=app) automatically handles lifespan
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://testserver")
        client.headers.update({"Authorization": f"Bearer {token}"})
        return client

    yield _create_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def test_client(
    app: FastAPI, mock_redis_client: MagicMock, mocker
) -> AsyncClient:
    """Unauthenticated client."""
    app.dependency_overrides[get_db] = override_get_db
    mocker.patch("api.database.engine", new=test_engine)
    mocker.patch("api.database.AsyncSessionLocal", new=TestAsyncSessionLocal)
    from api.redis_client import get_redis_client as original_get_redis_for_override
    from api.dependencies import (
        get_redis_client_for_quota as original_get_redis_quota_for_override,
    )

    app.dependency_overrides[original_get_redis_for_override] = lambda: (
        mock_redis_client
    )
    app.dependency_overrides[original_get_redis_quota_for_override] = lambda: (
        mock_redis_client
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def free_user(db_session: AsyncSession):
    """Creates a user with the 'free' plan."""
    unique_id = uuid.uuid4().hex[:6]
    user_schema = schemas.UserCreate(
        username=f"free_user_{unique_id}",
        email=f"free_user_{unique_id}@example.com",
        password="password",
    )
    user = await crud.create_user(db_session, user_schema)
    user.plan = "free"
    user.is_active = True

    # At least one active API key is now required to start strategies
    api_key = models.ApiKey(
        user_id=user.id,
        name="Free Key",
        exchange="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="free...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key)

    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def standard_user(db_session: AsyncSession):
    """Creates a user with the 'standard' plan."""
    unique_id = uuid.uuid4().hex[:6]
    user_schema = schemas.UserCreate(
        username=f"standard_user_{unique_id}",
        email=f"standard_user_{unique_id}@example.com",
        password="password",
    )
    user = await crud.create_user(db_session, user_schema)
    user.plan = "standard"
    user.is_active = True

    #  At least one active API key is now required to start strategies
    api_key = models.ApiKey(
        user_id=user.id,
        name="Standard Key",
        exchange="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="stan...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key)

    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def pro_user(db_session: AsyncSession):
    """Creates a user with the 'pro' plan."""
    unique_id = uuid.uuid4().hex[:6]
    user_schema = schemas.UserCreate(
        username=f"pro_user_{unique_id}",
        email=f"pro_user_{unique_id}@example.com",
        password="password",
    )
    user = await crud.create_user(db_session, user_schema)
    user.plan = "pro"
    user.is_active = True

    # At least one active API key is now required to start strategies
    api_key = models.ApiKey(
        user_id=user.id,
        name="Pro Key",
        exchange="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="pro...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key)

    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def free_user_client(free_user: models.User, authenticated_client_factory):
    """Authenticated client for a user with the 'free' plan."""
    client = await authenticated_client_factory(free_user)
    async with client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def standard_user_client(
    standard_user: models.User, authenticated_client_factory
):
    """Authenticated client for a user with the 'standard' plan."""
    client = await authenticated_client_factory(standard_user)
    async with client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def pro_user_client(pro_user: models.User, authenticated_client_factory):
    """Authenticated client for a user with the 'pro' plan."""
    client = await authenticated_client_factory(pro_user)
    async with client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(pro_user_client: AsyncClient):
    """Alias for pro_user_client for backward compatibility."""
    yield pro_user_client


# --- New fixture for the test DB ---

from sqlalchemy.pool import StaticPool

# URL for SQLite in memory
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Create engine specifically for tests
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)  # echo=True for SQL debugging
TestAsyncSessionLocal = async_sessionmaker(
    test_engine, expire_on_commit=False, autoflush=False
)


# This fixture will be automatically applied to each test
@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Fixture for creating and cleaning up tables for each test.
    Also creates a user with User ID=1 and their AppConfig.
    """
    async with test_engine.begin() as conn:
        # Create all tables before the test
        await conn.run_sync(Base.metadata.create_all)

    # Create a user and their configuration
    async with TestAsyncSessionLocal() as session:
        async with session.begin():
            from api import schemas as api_schemas  # Renamed to avoid conflict
            from api.security import get_password_hash

            # Create User 1
            # Check if user already exists to make fixture idempotent for this part if needed,
            # but with drop_all, it should be fine.
            user_check = await session.get(models.User, 1)
            if not user_check:
                user_create = api_schemas.UserCreate(
                    username="testuser1",
                    email="testuser1@example.com",
                    password="testpassword1",
                )
                hashed_password = get_password_hash(user_create.password)
                db_user = models.User(
                    id=1,
                    username=user_create.username,
                    email=user_create.email,
                    hashed_password=hashed_password,
                    is_active=True,
                )
                session.add(db_user)
                # logger.info("Test User 1 created in setup_database.") # Use conftest_logger

                # Create AppConfig for User 1
                default_risk_management = {
                    "daily_max_loss_percent": 5.0,
                    "risk_per_trade_percent": 1.0,
                    "min_rr_ratio": 2.0,
                    "maxDrawdown": 10.0,
                    "maxConcurrentTrades": 5,
                    "stopLossEnabled": True,
                    "defaultStopLossPercent": 2.0,
                }
                default_data_sources = {
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                    "statuses": [],
                }  # Added ETHUSDT for broader testing
                default_notifications = {
                    "emailEnabled": False,
                    "telegramEnabled": False,
                    "telegramChatId": "",
                }

                db_app_config = models.AppConfig(
                    user_id=1,
                    risk_management=default_risk_management,
                    data_sources=default_data_sources,
                    notifications=default_notifications,
                )
                session.add(db_app_config)

                # ADDED: At least one active API key is now required to start strategies
                db_api_key = models.ApiKey(
                    user_id=1,
                    name="Initial Test Key",
                    exchange="binance",
                    encrypted_api_key="enc-key",
                    encrypted_api_secret="enc-secret",
                    key_prefix="init...1234",
                    status="valid",
                    is_active=True,
                )
                session.add(db_api_key)
                # logger.info("Default AppConfig for User 1 created in setup_database.")
            else:
                # logger.info("Test User 1 already exists or setup_database called multiple times within one test scope (unexpected).")
                pass
        await session.commit()

    yield  # The test itself is executed here

    async with test_engine.begin() as conn:
        # Drop all tables after the test
        await conn.run_sync(Base.metadata.drop_all)


# Global stub for API requests used by old tests


def mock_make_api_request_global(
    path, params=None, method="GET", data=None, headers=None, **kwargs
):
    # print(f"DEBUG: mock_make_api_request_global received call for path: {path} with params: {params} and kwargs: {kwargs}")

    # Helper for timestamp conversion
    def convert_iso_to_ms(iso_str):
        return int(
            datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp() * 1000
        )

    # Target time range for dynamic data
    target_start_dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    target_end_dt = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    target_start_ms = int(target_start_dt.timestamp() * 1000)
    target_end_ms = int(target_end_dt.timestamp() * 1000)

    if path == "exchangeInfo":
        return {
            "timezone": "UTC",
            "serverTime": int(datetime.now(timezone.utc).timestamp() * 1000),
            "rateLimits": [],
            "exchangeFilters": [],
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "pair": "ETHUSDT",
                    "status": "TRADING",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                    "contractType": "PERPETUAL",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "10000",
                            "stepSize": "0.001",
                        },
                        {"filterType": "NOTIONAL", "minNotional": "10.0"},
                    ],
                    "orderTypes": ["LIMIT", "MARKET"],
                    "icebergAllowed": False,
                },
                {
                    "symbol": "ETH/USDT",
                    "pair": "ETH/USDT",
                    "status": "TRADING",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                    "contractType": "PERPETUAL",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "10000",
                            "stepSize": "0.001",
                        },
                        {"filterType": "NOTIONAL", "minNotional": "10.0"},
                    ],
                    "orderTypes": ["LIMIT", "MARKET"],
                    "icebergAllowed": False,
                },
                {
                    "symbol": "BTCUSDT",
                    "pair": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                    "contractType": "PERPETUAL",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.0001",
                            "maxQty": "1000",
                            "stepSize": "0.0001",
                        },
                        {"filterType": "NOTIONAL", "minNotional": "10.0"},
                    ],
                    "orderTypes": ["LIMIT", "MARKET"],
                    "icebergAllowed": False,
                },
            ],
        }
    elif path == "account":
        return {
            "makerCommission": 10,
            "takerCommission": 10,
            "buyerCommission": 0,
            "sellerCommission": 0,
            "canTrade": True,
            "canWithdraw": True,
            "canDeposit": True,
            "updateTime": 123456789,
            "accountType": "SPOT" if "spot" in kwargs.get("url", "") else "FUTURES",
            "balances": [
                {"asset": "BTC", "free": "1.0", "locked": "0.0"},
                {"asset": "USDT", "free": "100000.0", "locked": "0.0"},
            ],
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "0",
                    "initialMargin": "0",
                    "maintMargin": "0",
                }
            ],
        }
    elif path == "openOrders":
        return []
    elif isinstance(path, str) and (path == "klines" or path == "continuousKlines"):
        symbol = params.get("symbol", "")
        interval = params.get("interval", "1m")
        start_time_ms = params.get("startTime")
        end_time_ms = params.get("endTime")

        if (
            (symbol.upper() == "ETHUSDT" or symbol.upper() == "ETH/USDT")
            and start_time_ms is not None
            and end_time_ms is not None
            and max(start_time_ms, target_start_ms) < min(end_time_ms, target_end_ms)
        ):  # Check for overlap
            mock_klines = []
            current_ts_ms = start_time_ms

            interval_td = timedelta(minutes=1)  # default
            if interval == "1h":
                interval_td = timedelta(hours=1)
            elif interval == "1d":
                interval_td = timedelta(days=1)
            elif interval == "5m":
                interval_td = timedelta(minutes=5)
            # Add other intervals if needed for tests

            kline_count = 0
            max_klines = 100  # Generate up to 100 klines for the test

            while current_ts_ms < end_time_ms and kline_count < max_klines:
                open_price = round(random.uniform(2000, 2500), 2)
                high_price = round(open_price + random.uniform(0, 50), 2)
                low_price = round(open_price - random.uniform(0, 50), 2)
                close_price = round(random.uniform(low_price, high_price), 2)
                volume = round(random.uniform(100, 1000), 3)
                quote_asset_volume = round(volume * close_price, 2)
                number_of_trades = random.randint(50, 200)
                taker_buy_base_asset_volume = round(
                    volume * random.uniform(0.3, 0.7), 3
                )
                taker_buy_quote_asset_volume = round(
                    taker_buy_base_asset_volume * close_price, 2
                )
                close_time_ms = (
                    current_ts_ms + int(interval_td.total_seconds() * 1000) - 1
                )

                kline = [
                    current_ts_ms,
                    str(open_price),
                    str(high_price),
                    str(low_price),
                    str(close_price),
                    str(volume),
                    close_time_ms,
                    str(quote_asset_volume),
                    number_of_trades,
                    str(taker_buy_base_asset_volume),
                    str(taker_buy_quote_asset_volume),
                    "0",
                ]
                mock_klines.append(kline)
                current_ts_ms += int(interval_td.total_seconds() * 1000)
                kline_count += 1
            # print(f"DEBUG: Dynamically generated {len(mock_klines)} klines for {symbol} from {start_time_ms} to {end_time_ms}")
            return mock_klines
        else:
            # Fallback to existing static mock kline data
            ts1 = int(
                (datetime.now(timezone.utc) - timedelta(minutes=2)).timestamp() * 1000
            )
            ts2 = int(
                (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp() * 1000
            )
            return [
                [
                    ts1,
                    "100.0",
                    "105.0",
                    "99.0",
                    "102.0",
                    "1000.0",
                    ts1 + 59999,
                    "102000.0",
                    100,
                    "500.0",
                    "51000.0",
                    "0",
                ],
                [
                    ts2,
                    "102.0",
                    "108.0",
                    "101.0",
                    "107.0",
                    "1200.0",
                    ts2 + 59999,
                    "128400.0",
                    120,
                    "600.0",
                    "64200.0",
                    "0",
                ],
            ]

    elif isinstance(path, str) and path == "aggTrades":
        symbol = params.get("symbol", "")
        start_time_ms = params.get("startTime")
        end_time_ms = params.get("endTime")
        # from_id = params.get('fromId') # Not used for now, but available

        if (
            (symbol.upper() == "ETHUSDT" or symbol.upper() == "ETH/USDT")
            and start_time_ms is not None
            and end_time_ms is not None
            and max(start_time_ms, target_start_ms) < min(end_time_ms, target_end_ms)
        ):  # Check for overlap
            mock_trades = []
            current_agg_id = random.randint(100000, 200000)
            num_trades = 20  # Generate 20 agg trades

            # Ensure timestamps are within the requested range, even if narrow
            # Use a smaller time step if the requested range is very short
            time_increment_ms = max(
                1, (end_time_ms - start_time_ms) // (num_trades + 1)
            )
            if time_increment_ms == 0:
                time_increment_ms = 100  # default if range is too small

            for i in range(num_trades):
                price = round(random.uniform(2000, 2500), 2)
                quantity = round(random.uniform(0.01, 1.0), 3)
                # Ensure timestamp is within requested range and increasing
                trade_ts_ms = min(
                    start_time_ms + i * time_increment_ms, end_time_ms - 1
                )

                trade = {
                    "a": current_agg_id,
                    "p": str(price),
                    "q": str(quantity),
                    "f": current_agg_id * 10,  # Dummy first trade id
                    "l": current_agg_id * 10
                    + random.randint(0, 5),  # Dummy last trade id
                    "T": trade_ts_ms,
                    "m": random.choice([True, False]),
                }
                mock_trades.append(trade)
                current_agg_id += 1
            # print(f"DEBUG: Dynamically generated {len(mock_trades)} aggTrades for {symbol} from {start_time_ms} to {end_time_ms}")
            return mock_trades
        else:
            # Fallback to existing static mock aggTrade data
            trade_time1 = int(
                (datetime.now(timezone.utc) - timedelta(seconds=10)).timestamp() * 1000
            )
            trade_time2 = int(
                (datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp() * 1000
            )
            return [
                {
                    "a": 12345,
                    "p": "101.50",
                    "q": "0.5",
                    "f": 100,
                    "l": 102,
                    "T": trade_time1,
                    "m": True,
                },
                {
                    "a": 12346,
                    "p": "101.55",
                    "q": "0.2",
                    "f": 103,
                    "l": 103,
                    "T": trade_time2,
                    "m": False,
                },
            ]

    # Fallback for unhandled paths
    conftest_logger.error(
        f"Mock _make_api_request_global called with UNHANDLED path: {path} and params {params}. This will likely cause a test error."
    )
    raise NotImplementedError(
        f"Mock _make_api_request_global called with unhandled path: {path} and params {params}"
    )


@pytest.fixture(scope="function")
def mock_ml_agent_instance():
    """Fixture that creates a stub for the ML agent."""
    agent = MagicMock(spec=OnlineAgentStrategy)
    agent.NAME = "OnlineAgentStrategy"
    agent.candle_timeframe = "1m"
    agent.atr_period = 14
    agent.stop_loss_atr_multiplier = 1.0
    agent.take_profit_atr_multiplier = 2.0
    agent.min_probability_threshold = 0.6
    agent._round_price = MagicMock(
        side_effect=lambda price, tick, mode: round_dynamic(price, tick)
    )
    agent.feature_extractor = MagicMock()
    agent.feature_extractor.extract_features = MagicMock(
        return_value={"feat1": 0.5, "feat2": -0.2}
    )
    agent.feature_extractor.normalize_features = MagicMock(
        return_value={"feat1": 0.6, "feat2": -0.1}
    )
    agent.model_pipeline = MagicMock()
    agent.model_pipeline.learn_one = MagicMock()
    agent.model_pipeline.predict_proba_one = MagicMock(return_value={1: 0.7, 0: 0.3})
    type(agent.model_pipeline).steps_processed = PropertyMock(return_value=10)
    type(agent).required_data_types = PropertyMock(
        return_value={"kline_1m", "aggTrade"}
    )
    return agent


@pytest.fixture(scope="session")
def sample_klines_df_for_fvb():
    """Provides a sample Kline DataFrame for FastVectorBacktester tests."""
    data = {
        "open_time": pd.to_datetime(
            [
                "2023-01-01 00:00:00",
                "2023-01-01 00:01:00",
                "2023-01-01 00:02:00",
                "2023-01-01 00:03:00",
                "2023-01-01 00:04:00",
            ]
        ),
        "open": [100, 101, 102, 103, 104],
        "high": [105, 106, 107, 108, 109],
        "low": [99, 100, 101, 102, 103],
        "close": [101, 102, 103, 104, 105],
        "volume": [10, 12, 11, 13, 14],
    }
    df = pd.DataFrame(data)
    df.set_index("open_time", inplace=True)
    df.index = df.index.tz_localize("UTC")  # Ensure timezone awareness
    return df


@pytest.fixture(scope="function")
def mock_binance_server():
    """
    Starts and stops the Binance mock server for each test.
    Uses subprocess to run uvicorn in the background.
    """
    server_process = subprocess.Popen(
        [
            "uvicorn",
            "tests.e2e.mock_binance_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            "9999",
        ]
    )

    time.sleep(2)

    try:
        response = requests.get("http://127.0.0.1:9999/docs")
        response.raise_for_status()
        print("\nMock Binance server is up and running.")
    except (requests.ConnectionError, requests.HTTPError) as e:
        server_process.terminate()
        pytest.fail(f"Mock Binance server did not start correctly: {e}")

    yield "http://127.0.0.1:9999"

    print("\nShutting down mock Binance server...")
    server_process.terminate()
    server_process.wait()
    print("Mock Binance server shut down.")


@pytest.fixture
async def running_bot_with_mock_binance(
    monkeypatch, mock_redis_client, mock_binance_server
):
    """
    Fixture for a full E2E test: starts TradingController,
    configured to work with the Binance mock server.
    """
    from bot_module import config as global_bot_config
    from bot_module.executor import BinanceExecutor
    from bot_module.data_consumer import DataConsumer
    from bot_module.risk_manager import RiskManager

    # 1. Patch the config so the bot connects to our mock server
    monkeypatch.setattr(global_bot_config, "ACTIVE_TRADING_ENVIRONMENT", "testnet")
    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", "futures_usdtm")

    # Most important: substitute URLs
    monkeypatch.setattr(
        global_bot_config, "BINANCE_FUTURES_TESTNET_API_URL", mock_binance_server
    )
    monkeypatch.setattr(
        global_bot_config,
        "BINANCE_FUTURES_TESTNET_USER_DATA_WS_URL",
        f"{mock_binance_server.replace('http', 'ws')}/ws",
    )
    monkeypatch.setattr(
        global_bot_config,
        "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
        f"{mock_binance_server.replace('http', 'ws')}/stream",
    )
    # Add similar ones for SPOT, if needed
    monkeypatch.setattr(
        global_bot_config, "BINANCE_SPOT_TESTNET_API_URL", mock_binance_server
    )
    monkeypatch.setattr(
        global_bot_config,
        "BINANCE_SPOT_TESTNET_USER_DATA_WS_URL",
        f"{mock_binance_server.replace('http', 'ws')}/ws",
    )

    # 2. Simplify configuration for the test
    monkeypatch.setattr(global_bot_config, "SYMBOL_SOURCE_MODE", "STATIC_LIST")
    monkeypatch.setattr(global_bot_config, "SYMBOL_SOURCE_STATIC_LIST", ["BTCUSDT"])
    monkeypatch.setattr(global_bot_config, "DEFAULT_RISK_PER_TRADE_PERCENT", 1.0)
    monkeypatch.setattr(
        global_bot_config,
        "STRATEGY_DEFAULTS",
        {
            "VolumeBreakout": {"enabled": True, "candle_timeframe": "1m"},
        },
    )

    # 3. Create and start the entire system
    # Use REAL components, not mocks
    import aiohttp

    session = aiohttp.ClientSession()
    executor = BinanceExecutor(api_key="test", api_secret="test", session=session)

    # Paper executor mock
    paper_executor = MagicMock()
    paper_executor.controller = None

    data_consumer = DataConsumer(loop=asyncio.get_running_loop(), executor=executor)
    risk_manager = RiskManager(
        executor=executor,
        paper_executor=paper_executor,
        user_id=1,
        db_session=None,
        user_settings={},
    )
    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=data_consumer,
        live_executor=executor,
        paper_executor=paper_executor,
        risk_manager=risk_manager,
        user_id=1,
    )

    await controller.start()
    await asyncio.sleep(2)  # Give time for startup and subscriptions

    yield controller  # Pass the controller to the test

    # 4. Stop after test
    await controller.stop()
    await executor.close()
    await session.close()
