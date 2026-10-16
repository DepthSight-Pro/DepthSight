# bot_module/db_retry.py
"""Transient database-connection failure detection and retry budget.

Context: behind PgBouncer (transaction pooling) the pooler may close or
recycle a server connection while a query is in flight, especially when
hundreds of client connections multiplex over tens of server connections.
asyncpg then raises "connection was closed in the middle of operation".
pool_pre_ping (api/database.py) only covers connections that are already
dead at checkout time - it cannot help a kill mid-operation. The only
correct recovery is rollback + retry, which is safe exactly when nothing
was committed yet (callers must enforce the pre-commit condition).

Kept dependency-free on purpose: the matcher works on exception class
names and message substrings, so it classifies asyncpg/SQLAlchemy errors
without importing either driver (tests run on SQLite/mocks).
"""

import logging
import os

logger = logging.getLogger(__name__)

# Substrings (lowercased) identifying a dropped/broken DB connection as
# opposed to a logic error (constraint violation, bad SQL, ...). Matched
# against str(exc); empty messages never match, so genuinely unknown
# failures keep the old single-attempt behaviour.
_TRANSIENT_MARKERS = (
    "connection was closed",
    "connection is closed",
    "connection lost",
    "connection reset",
    "server closed the connection",
    "connectiondoesnotexist",
    "connectionfailure",
    "cannot operate on a closed",
    "ssl syscall",
    "eof detected",
    "broken pipe",
    "too many clients",
    "remaining connection slots",
)

# Exception class names (without module path) treated as transient even
# when the message is empty - asyncpg connectivity errors notoriously
# stringify to "". Deliberately narrow: generic OperationalError /
# InterfaceError are NOT matched by class alone (they also cover logic
# errors); their transient instances are still caught via the message
# markers above.
_TRANSIENT_CLASS_NAMES = frozenset(
    {
        "ConnectionDoesNotExistError",
        "ConnectionFailureError",
        "ConnectionResetError",
        "DisconnectionError",
    }
)


def is_transient_connection_error(exc: BaseException) -> bool:
    """True if `exc` looks like a dropped DB connection worth one retry."""
    if exc is None:
        return False
    if type(exc).__name__ in _TRANSIENT_CLASS_NAMES:
        return True
    try:
        message = str(exc).lower()
    except Exception:
        return False
    if not message:
        return False
    # SQLAlchemy wraps driver errors in DBAPIError/OperationalError whose
    # str() contains the driver message; the markers above catch both.
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def get_retry_attempts() -> int:
    """Max attempts (first try + retries) for transient DB failures."""
    try:
        attempts = int(os.environ.get("DB_TRANSIENT_RETRY_ATTEMPTS", "2") or 2)
    except (TypeError, ValueError):
        attempts = 2
    return max(1, attempts)
