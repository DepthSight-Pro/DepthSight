# api/federation.py
"""Re-export shim.

The implementation lives in ``bot_module/federation.py`` (dependency-safe:
``api -> bot_module`` is the allowed direction, and the bot runtime needs the
same helper). Import from here keeps existing API-layer call sites working.
"""

from bot_module.federation import (  # noqa: F401
    InsecureHubUrlError,
    get_federation_hub_url,
)

__all__ = ["InsecureHubUrlError", "get_federation_hub_url"]
