# bot_module/federation.py
"""Central accessor for the Federation Hub base URL.

Lives in ``bot_module`` because the dependency direction is one-way
(``api -> bot_module`` allowed; the reverse is forbidden by contract test),
and BOTH the API layer and the bot runtime need the same validated URL.

Every outbound call to the central hub MUST go through
``get_federation_hub_url()`` so that an insecure (non-HTTPS) configuration
fails loudly instead of silently shipping the node secret in cleartext.

Escape hatch for local development: set ``ALLOW_INSECURE_HUB_URL=true``.
Plain HTTP is always allowed for localhost/127.0.0.1 targets.
"""

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_HUB_URL = "https://app.depthsight.pro/api/v1/hub"


class InsecureHubUrlError(RuntimeError):
    """Raised when FEDERATION_HUB_URL points to a non-HTTPS endpoint."""


def get_federation_hub_url() -> str:
    """Returns the validated Federation Hub base URL (no trailing slash)."""
    url = (
        os.getenv("FEDERATION_HUB_URL")
        or os.getenv("VITE_HUB_API_URL")
        or os.getenv("API_URL")
        or _DEFAULT_HUB_URL
    ).rstrip("/")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()

    if scheme == "https":
        return url

    is_local = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    allow_insecure = os.getenv("ALLOW_INSECURE_HUB_URL", "false").lower() == "true"

    if is_local or allow_insecure:
        logger.warning(
            "[FEDERATION] Using INSECURE hub URL '%s'. The node secret travels "
            "unencrypted; allowed because target is local or "
            "ALLOW_INSECURE_HUB_URL=true.",
            url,
        )
        return url

    raise InsecureHubUrlError(
        f"FEDERATION_HUB_URL must use HTTPS (got '{url}'). The node secret and "
        "telemetry are transmitted to this endpoint. For local development set "
        "ALLOW_INSECURE_HUB_URL=true."
    )
