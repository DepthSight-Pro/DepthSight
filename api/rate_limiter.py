"""Shared slowapi rate limiter.

Kept in its own module so the main app and every router module (auth, backtests,
discovery, hub, ...) reference the *same* ``Limiter`` instance without circular
imports. In tests the limiter is built disabled (``RATELIMIT_ENABLED=false``);
``tests/conftest.py`` additionally forces ``app.state.limiter._enabled = False``.
"""

import os
import re

from slowapi import Limiter

# Literal limits (e.g. "5/hour") are used verbatim; named limits ("login",
# "backtest", ...) are resolved from LIMITS_CONFIG below.
_LITERAL_LIMIT_RE = re.compile(r"^\d+/(?:second|minute|hour|day)(?:/[a-zA-Z0-9_.-]+)?$")

TESTING = os.getenv("TESTING", "false").lower() == "true"
RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() != "false"

# Limits for different endpoints. Overridden in tests.
LIMITS_CONFIG = {
    "backtest": "100/hour",
    "genetic": "10/hour",
    "login": os.getenv("RATE_LIMIT_LOGIN", "20/minute"),
    "default": "600/minute",
    "hub_feedback": "5/hour",
    "hub_topics": "10/hour",
    "hub_like": "60/minute",
    "hub_comments": "30/minute",
    "hub_messages": "30/minute",
}


def get_limit_value(limit_name: str) -> str:
    """Return the rate limit string for ``limit_name``.

    Literal limits (``"5/hour"``) are returned unchanged; otherwise the value is
    looked up in ``LIMITS_CONFIG``. Under tests, low limits can be selectively
    enabled via ``TEST_LIMIT_<NAME>`` and everything else defaults to a high stub.
    """
    if _LITERAL_LIMIT_RE.match(limit_name):
        return limit_name
    if TESTING:
        test_limit = os.getenv(f"TEST_LIMIT_{limit_name.upper()}")
        return test_limit if test_limit else "10000/hour"
    return LIMITS_CONFIG.get(limit_name, LIMITS_CONFIG["default"])


def _build_rate_limit_redis_url() -> str:
    configured = os.getenv("RATE_LIMIT_REDIS_URL")
    if configured:
        return configured
    username = os.getenv("REDIS_USERNAME") or ""
    password = os.getenv("REDIS_PASSWORD") or ""
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    auth = ""
    if password:
        auth = f"{username}:{password}@" if username else f":{password}@"
    return f"redis://{auth}{host}:{port}/1"


def get_real_client_ip(request) -> str:
    """Extract real client IP considering reverse proxies (X-Forwarded-For, X-Real-IP).

    Uses the LAST entry of ``X-Forwarded-For``: our reverse proxy (Caddy)
    appends the actual peer address, while any client-supplied prefix can be
    freely spoofed. Taking the first entry would let attackers rotate fake
    IPs and bypass rate limiting.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if hasattr(request, "client") and request.client:
        return request.client.host
    return "127.0.0.1"


# Use memory storage in tests, Redis in production for synchronization between workers.
if TESTING:
    limiter = Limiter(
        key_func=get_real_client_ip,
        storage_uri="memory://",
        default_limits=["10000/hour"],
        enabled=RATELIMIT_ENABLED,
    )
else:
    limiter = Limiter(
        key_func=get_real_client_ip,
        storage_uri=_build_rate_limit_redis_url(),
        default_limits=[get_limit_value("default")],
        enabled=RATELIMIT_ENABLED,
    )
