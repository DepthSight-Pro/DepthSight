# api/database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from contextlib import asynccontextmanager

# 1. Read all necessary data from environment variables
#    Variable names must match those used in the .env file
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_HOST = os.environ.get("POSTGRES_HOST")
DB_NAME = os.environ.get("POSTGRES_DB")
DB_PORT = os.environ.get("POSTGRES_PORT", 5432)

# 2. Validation (very important!). Verify all variables are found.
#    If any is missing, the application will fail with a clear error instead of breaking silently.
if not all([DB_USER, DB_PASS, DB_HOST, DB_NAME]):
    raise ValueError("One or more required database environment variables are not set!")

# 3. Assemble connection string from retrieved variables
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# 4. Connection pool sizing.
#
# This used to be create_async_engine(DATABASE_URL) with SQLAlchemy defaults, i.e.
# pool_size=5, max_overflow=10 -> a hard ceiling of 15 concurrent connections per
# process. That is fine for the API, but the bot process now runs one DB session
# per trading controller (bot_runner.py), so a shard needs roughly
# "controllers per shard" connections at the moment a candle boundary fires and
# every controller evaluates a signal. With more than 15 controllers per shard the
# surplus requests queue and then die with:
#   sqlalchemy.exc.TimeoutError: QueuePool limit of size 5/overflow 10 reached,
#   connection timed out, timeout 30
# which is indistinguishable from a broker outage in the logs.
#
# pool_pre_ping and pool_recycle matter more than usual here because a
# controller's session is created at startup and reused for the whole process
# lifetime: the underlying TCP connection can be dropped by a firewall, NAT
# gateway or a Postgres restart long before the session is used again, and
# without pre_ping the first query on the stale connection fails.
POOL_SIZE = _int_env("DB_POOL_SIZE", 5)
MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", 10)
POOL_TIMEOUT = _int_env("DB_POOL_TIMEOUT", 30)
POOL_RECYCLE = _int_env("DB_POOL_RECYCLE", 1800)
POOL_PRE_PING = _bool_env("DB_POOL_PRE_PING", True)

# asyncpg prepared-statement cache size. Leave UNSET (driver default) for
# direct Postgres connections. Set to 0 when pointing at PgBouncer in
# transaction pooling mode: prepared statements do not survive across
# transactions there, and every query would fail with
# "prepared statement already exists". See docker-compose.pgbouncer.yml.
_STATEMENT_CACHE_RAW = os.environ.get("DB_STATEMENT_CACHE_SIZE")
try:
    STATEMENT_CACHE_SIZE = (
        int(_STATEMENT_CACHE_RAW) if _STATEMENT_CACHE_RAW is not None else None
    )
except (TypeError, ValueError):
    STATEMENT_CACHE_SIZE = None

engine_options = {
    "pool_size": POOL_SIZE,
    "max_overflow": MAX_OVERFLOW,
    "pool_timeout": POOL_TIMEOUT,
    "pool_recycle": POOL_RECYCLE,
    "pool_pre_ping": POOL_PRE_PING,
}
if STATEMENT_CACHE_SIZE is not None:
    # connect_args pass straight to asyncpg.
    engine_options["connect_args"] = {"statement_cache_size": STATEMENT_CACHE_SIZE}

# Direct DSN bypassing any pooler, for code that needs session-level
# guarantees PgBouncer transaction mode cannot provide (e.g. the mining-epoch
# advisory lock in tasks.py, which must hold one server connection). Unset =
# same as DATABASE_URL. Set this to the real Postgres when POSTGRES_HOST
# points at PgBouncer.
_DIRECT_DATABASE_URL = os.environ.get("DB_DIRECT_DATABASE_URL")
DIRECT_DATABASE_URL = _DIRECT_DATABASE_URL or DATABASE_URL

engine = create_async_engine(DATABASE_URL, **engine_options)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()

# Alias for WebSocket server and other components that need a context manager for sessions
async_session_factory = AsyncSessionLocal


def get_session_for_worker() -> async_sessionmaker[AsyncSession]:
    """
    Returns session factory for use in background tasks (Celery).
    This allows session creation in the worker context.
    """
    return AsyncSessionLocal


# DEPENDENCY FOR ENDPOINTS
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope():
    """Short-lived session for ONE logical DB operation. Always closed.

    A session checks out its pool connection on first use and returns it only
    on commit/rollback/close. Read-only call sites that reuse a long-lived
    session therefore pin one connection each forever - with ~300 controllers
    that alone exhausts any pool. Every per-operation use in long-lived
    components (bot controllers, executors, risk managers) must go through
    this helper (or an equivalent factory), never through a stored session,
    unless the path commits (which also releases).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise


@asynccontextmanager
async def get_isolated_worker_session():
    """
    Creates fully isolated engine and session for a single Celery task.
    Guarantees that all resources (including connection pool) are destroyed after use.
    Used as async context manager (async with).
    Uses DIRECT_DATABASE_URL (bypasses PgBouncer when set): session-level
    guarantees such as the mining-epoch advisory lock need one real server
    connection, which transaction pooling cannot provide.
    """
    # 1. Create a new, temporary engine for this specific task.
    worker_engine = create_async_engine(DIRECT_DATABASE_URL, **engine_options)

    # 2. Create a new session factory bound to this temporary engine.
    WorkerSessionLocal = async_sessionmaker(worker_engine, expire_on_commit=False)

    # 3. Create and yield session.
    async with WorkerSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # 4. After completing 'with' block, guarantee destruction of engine and connection pool.
    await worker_engine.dispose()
