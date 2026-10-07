# bot_module/node_identity.py
"""Exchange-agnostic readers for mining identity in AppConfig.exchange_settings.

The settings blob looks like::

    {
        "weex": {"mining_node_uuid": ..., "wallet_address": ...,
                 "bitget_uid": ..., ...},
        "bitget": {"mining_node_uuid": ..., "wallet_address": ...},
        ...
        "mining_node_uuid": ...,   # top-level fallback
        "wallet_address": ...,     # top-level fallback
    }

Historically every reader hardcoded its own exchange list (hub used weex
only, the epoch used bybit/okx/weex/binance without bitget), so each new
exchange silently broke owner/referrer resolution for its users. These
helpers deliberately know NO exchange names: they scan every mapping
section plus the top level for the well-known identity keys. A future
exchange works with zero code changes.

Only the two key names ``mining_node_uuid`` / ``wallet_address`` are read,
one level deep — never a deep recursive walk, so unrelated nested
structures (if any appear) cannot leak into identity resolution.

Priority (deterministic, backward compatible): the legacy ``weex`` section
first (it was historically the only source), then remaining sections in
sorted key order, then top-level keys.
"""

from typing import Any, Dict, Iterator, List, Optional, Tuple

MINING_NODE_UUID_KEY = "mining_node_uuid"
WALLET_ADDRESS_KEY = "wallet_address"

_LEGACY_FIRST_SECTION = "weex"


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def iter_identity_sections(
    settings: Optional[Dict[str, Any]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield ``(section_name, section_dict)`` in deterministic priority order.

    ``""`` denotes the synthetic top-level section (scalar keys of the
    settings blob itself). Non-mapping values are skipped.
    """
    if not isinstance(settings, dict):
        return
    sections: List[Tuple[str, Dict[str, Any]]] = []
    for key in sorted(settings.keys(), key=lambda k: str(k)):
        if str(key) == _LEGACY_FIRST_SECTION:
            continue
        value = settings.get(key)
        if isinstance(value, dict):
            sections.append((str(key), value))
    legacy = settings.get(_LEGACY_FIRST_SECTION)
    ordered: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(legacy, dict):
        ordered.append((_LEGACY_FIRST_SECTION, legacy))
    ordered.extend(sections)
    # Top-level scalar keys act as the final fallback section.
    top_level = {k: v for k, v in settings.items() if not isinstance(v, dict)}
    if top_level:
        ordered.append(("", top_level))
    yield from ordered


def collect_mining_node_uuids(settings: Optional[Dict[str, Any]]) -> List[str]:
    """All distinct mining node UUIDs across every exchange section."""
    found: List[str] = []
    for _, section in iter_identity_sections(settings):
        uuid = _as_text(section.get(MINING_NODE_UUID_KEY))
        if uuid and uuid not in found:
            found.append(uuid)
    return found


def collect_wallet_addresses(settings: Optional[Dict[str, Any]]) -> List[str]:
    """All distinct bound wallet addresses across every exchange section."""
    found: List[str] = []
    lowered: List[str] = []
    for _, section in iter_identity_sections(settings):
        wallet = _as_text(section.get(WALLET_ADDRESS_KEY))
        if wallet and wallet.lower() not in lowered:
            lowered.append(wallet.lower())
            found.append(wallet)
    return found


def primary_mining_node_uuid(settings: Optional[Dict[str, Any]]) -> Optional[str]:
    """First mining node UUID in priority order (None when absent)."""
    uuids = collect_mining_node_uuids(settings)
    return uuids[0] if uuids else None


def primary_wallet_address(settings: Optional[Dict[str, Any]]) -> Optional[str]:
    """First bound wallet address in priority order (None when absent)."""
    wallets = collect_wallet_addresses(settings)
    return wallets[0] if wallets else None


def find_identity_pair(
    settings: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """First ``(mining_node_uuid, mining_node_secret)`` pair in priority order.

    UUID and secret always come from the SAME section (falling back to the
    top-level secret) so credentials can never be mixed across sections —
    mixed pairs failed hub auth. Returns ``(None, None)`` when no section
    carries a node UUID.
    """
    if not isinstance(settings, dict):
        return None, None
    top_secret = _as_text(settings.get("mining_node_secret"))
    for _, section in iter_identity_sections(settings):
        uuid = _as_text(section.get(MINING_NODE_UUID_KEY))
        if not uuid:
            continue
        secret = _as_text(section.get("mining_node_secret")) or top_secret
        return uuid, secret
    return None, None
