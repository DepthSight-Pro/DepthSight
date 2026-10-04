# bot_module/private_stream_registry.py
"""Process-global registry of private user-data streams, one per (exchange, api_key).

Why this exists:

- Exchanges cap simultaneous private WebSocket connections per IP (Bitget 100
  with IP-ban risk on repeated disconnects, WEEX spot 20). One stream per
  controller means hundreds of connections from one box.
- Single-session exchanges (bitget, weex) KICK the previous login when a second
  one arrives (Bitget 30017 "Account logoff"): with N controllers sharing one
  key, every controller's private stream fights the others and they flap
  forever. One stream per key removes the fight entirely.

Design:

- Lazy: a stream opens on first live demand and closes after the idle timeout.
  1m-strategy bots are flat most of the time, so steady-state stream count is
  ~open positions, not ~controllers (10-50x less).
- Shared: all controllers of one key attach to the same loop; the loop runs on
  the first subscriber's executor and migrates on owner departure.
- Routed: raw order events go ONLY to the controller owning the clientOrderId
  (kills the MANUAL_CLOSE_DETECTED / external-SL-adoption cross-talk between
  sibling controllers sharing a key); account/balance events go to everyone.
  Controllers additionally ignore sibling-format cids they don't own, so even
  a stale extra delivery is harmless.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

from bot_module import config

logger = logging.getLogger(__name__)

# (exchange_id, api_key_id) -> entry. api_key_id None means "unknown key" and
# is never shared: without a key we cannot prove two controllers are siblings.
_entries: Dict[Tuple[str, Any], "_StreamEntry"] = {}
_registry_lock = asyncio.Lock()

# Process-global open-attempt timestamps per exchange (monotonic seconds,
# sliding 60 s window). Bounds the aggregate connect-request rate: per-key
# throttles alone cannot, 1000 controllers retrying would breach 300/5min solo.
_open_attempts: Dict[str, Deque[float]] = {}

# Last REST poll timestamp per (exchange, api_key) for per-key poll sharing:
# with several strategies on one key a single poll covers all siblings.
_last_poll: Dict[Tuple[str, Any], float] = {}

# Balance/account events carry no order identity: broadcast to every subscriber.
_BROADCAST_EVENT_TYPES = {
    "outboundAccountPosition",
    "ACCOUNT_UPDATE",
    "balanceUpdate",
}


@dataclass
class _Subscriber:
    sub_id: Any
    on_event: Callable[[Dict[str, Any]], Awaitable[None]]
    owns_cid: Callable[[Optional[str]], bool]
    open_fn: Callable[[Callable[[Dict[str, Any]], Awaitable[None]]], Awaitable[bool]]
    stop_fn: Callable[[], Awaitable[None]]
    label: str = ""


@dataclass
class _StreamEntry:
    exchange_id: str
    api_key_id: Any
    subscribers: Dict[Any, _Subscriber] = field(default_factory=dict)
    owner_sub_id: Any = None
    running: bool = False
    # True while an open is in flight: concurrent ensurers wait for it instead
    # of logging in twice (a second login kicks the first on single-session
    # exchanges - the exact storm this module removes).
    opening: bool = False
    opened_event: asyncio.Event = field(default_factory=asyncio.Event)
    # Physical connections this loop holds (Bitget opens a second orders-algo
    # channel for plan SL/TP). Counted against the per-exchange budget.
    conns: int = 1
    # Hottest reported relative distance to TP/SL (fraction, smaller = hotter;
    # None = unknown). Drives promotion/eviction under a full budget.
    heat: Optional[float] = None
    opened_at: float = 0.0  # monotonic timestamp of the last successful open


def _budget_for(exchange: str) -> int:
    table = getattr(config, "PRIVATE_WS_CONN_BUDGET", None) or {}
    if exchange in table:
        return int(table[exchange])
    return int(getattr(config, "PRIVATE_WS_CONN_BUDGET_DEFAULT", 80))


def _rate_per_min_for(exchange: str) -> int:
    table = getattr(config, "PRIVATE_WS_CONN_RATE_PER_MIN", None) or {}
    return int(table.get(exchange, 30))


def _conns_per_key_for(exchange: str) -> int:
    table = getattr(config, "PRIVATE_WS_CONNS_PER_KEY", None) or {}
    return int(table.get(exchange, 1))


def _running_conns(exchange: str) -> int:
    return sum(
        e.conns for (ex, _key), e in _entries.items() if ex == exchange and e.running
    )


def _rate_ok_locked(exchange: str, now: float) -> bool:
    """Sliding 60 s window on open attempts. Caller holds _registry_lock."""
    dq = _open_attempts.get(exchange)
    if dq is None:
        dq = _open_attempts[exchange] = deque()
    while dq and dq[0] <= now - 60.0:
        dq.popleft()
    return len(dq) < _rate_per_min_for(exchange)


def _record_open_locked(exchange: str, now: float) -> None:
    dq = _open_attempts.get(exchange)
    if dq is None:
        dq = _open_attempts[exchange] = deque()
    dq.append(now)


def _eviction_candidate_locked(
    exchange: str, newcomer_heat: float, now: float
) -> Optional[Tuple[str, Any]]:
    """Coldest running loop this newcomer may take over, or None.

    Victim must be older than min-hold and clearly colder (heat larger than
    newcomer_heat * margin). Unknown heat (+inf) is evictable: a key that
    never reports cannot defend its slot against a known-hot key.
    """
    margin = float(getattr(config, "PRIVATE_WS_PROMOTE_MARGIN", 1.5) or 1.5)
    min_hold = float(getattr(config, "PRIVATE_WS_MIN_HOLD_SECONDS", 60) or 0)
    best: Optional[Tuple[str, Any]] = None
    best_heat = newcomer_heat * margin
    for key, entry in _entries.items():
        if key[0] != exchange or not entry.running:
            continue
        if now - entry.opened_at < min_hold:
            continue
        entry_heat = entry.heat if entry.heat is not None else float("inf")
        if entry_heat > best_heat:
            best_heat = entry_heat
            best = key
    return best


def _norm_exchange(exchange_id: Any) -> str:
    return (
        str(exchange_id or "")
        .lower()
        .replace("_testnet", "")
        .replace("_spot", "")
        .replace("_linear", "")
    )


def _event_cid(event: Dict[str, Any]) -> Optional[str]:
    """Extract the clientOrderId from a normalized execution-report event."""
    if not isinstance(event, dict):
        return None
    etype = event.get("e")
    if etype == "ORDER_TRADE_UPDATE":
        inner = event.get("o") or {}
        return inner.get("c") or None
    if etype == "executionReport":
        return event.get("c") or event.get("C") or event.get("newClientOrderId") or None
    return None


def _is_broadcast(event: Dict[str, Any]) -> bool:
    return isinstance(event, dict) and event.get("e") in _BROADCAST_EVENT_TYPES


async def _route_event(key: Tuple[str, Any], event: Dict[str, Any]) -> None:
    """Deliver one raw event to the owning subscriber(s). Never raises."""
    try:
        entry = _entries.get(key)
        if not entry:
            return
        subs = list(entry.subscribers.values())
        if not subs:
            return
        if _is_broadcast(event):
            targets = subs
        else:
            cid = _event_cid(event)
            targets = [s for s in subs if s.owns_cid(cid)] if cid else list(subs)
            if not targets:
                # No owner (stale subscriber set or foreign manual order):
                # deliver nowhere for order events. The controller-level
                # sibling guard is the second layer; true manual orders are
                # still detected by controllers that keep a stream for other
                # reasons... more precisely: manual detection needs SOMEONE to
                # see it, so fall back to broadcast when NOBODY owns it.
                targets = subs
        for sub in targets:
            try:
                await sub.on_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    f"[PrivateStream:{key}] subscriber {sub.label} failed: {e}"
                )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[PrivateStream:{key}] routing failed: {e}")


def _make_router(key: Tuple[str, Any]):
    async def router(event: Dict[str, Any]) -> None:
        await _route_event(key, event)

    return router


async def ensure_stream(
    exchange_id: str,
    api_key_id: Any,
    sub_id: Any,
    on_event: Callable[[Dict[str, Any]], Awaitable[None]],
    owns_cid: Callable[[Optional[str]], bool],
    open_fn: Callable[[Callable[[Dict[str, Any]], Awaitable[None]]], Awaitable[bool]],
    stop_fn: Callable[[], Awaitable[None]],
    label: str = "",
    heat: Optional[float] = None,
) -> bool:
    """Attach a subscriber; open the shared loop on first demand.

    Admission is process-global per exchange: simultaneous loops are capped
    by the connection budget (one env knob per exchange, raisable without a
    release) and opens are rate-limited in a sliding 60 s window (per-key
    throttles cannot bound 1000 controllers retrying at once). When the
    budget is full, a known-hot newcomer evicts the coldest running loop
    past min-hold; everyone else (and every rejection) falls back to REST
    polling. Returns True when a live loop exists afterwards. Never raises.
    """
    key = (_norm_exchange(exchange_id), api_key_id)
    if api_key_id is None:
        return False
    now = time.monotonic()
    evict_stop: Optional[Callable[[], Awaitable[None]]] = None
    try:
        async with _registry_lock:
            entry = _entries.get(key)
            if entry is None:
                entry = _entries[key] = _StreamEntry(
                    exchange_id=key[0], api_key_id=api_key_id
                )
            entry.subscribers[sub_id] = _Subscriber(
                sub_id=sub_id,
                on_event=on_event,
                owns_cid=owns_cid,
                open_fn=open_fn,
                stop_fn=stop_fn,
                label=label or str(sub_id),
            )
            if heat is not None:
                entry.heat = heat
            if entry.running:
                return True
            if entry.opening:
                join_open = True
                open_fn_to_use = None
            else:
                need = _conns_per_key_for(key[0])
                admitted = _running_conns(key[0]) + need <= _budget_for(
                    key[0]
                ) and _rate_ok_locked(key[0], now)
                if not admitted and heat is not None:
                    victim_key = _eviction_candidate_locked(key[0], heat, now)
                    if victim_key is not None:
                        victim = _entries.get(victim_key)
                        if victim is not None and victim.running:
                            victim.running = False
                            owner = victim.subscribers.get(victim.owner_sub_id)
                            if owner is not None:
                                evict_stop = owner.stop_fn
                            else:
                                for sub in victim.subscribers.values():
                                    evict_stop = sub.stop_fn
                                    break
                            logger.info(
                                f"[PrivateStream:{victim_key}] evicted for hotter "
                                f"{key} (budget)."
                            )
                            admitted = _rate_ok_locked(key[0], now)
                if not admitted:
                    # Budget or rate full without eviction: drop our
                    # subscription (poll fallback covers) instead of queuing
                    # a connect attempt that risks an exchange IP ban.
                    entry.subscribers.pop(sub_id, None)
                    if not entry.subscribers and entry is _entries.get(key):
                        _entries.pop(key, None)
                    return False
                # We are the opener.
                _record_open_locked(key[0], now)
                entry.opening = True
                entry.conns = need
                entry.opened_event.clear()
                entry.owner_sub_id = sub_id
                join_open = False
                open_fn_to_use = entry.subscribers[sub_id].open_fn
        if evict_stop is not None:
            try:
                await evict_stop()
            except Exception as e:
                logger.warning(f"[PrivateStream:{key}] victim stop failed: {e}")
        if join_open:
            try:
                await asyncio.wait_for(entry.opened_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            async with _registry_lock:
                fresh = _entries.get(key)
                return bool(
                    fresh is not None and fresh.running and sub_id in fresh.subscribers
                )
        # Open outside the registry lock (login takes ~1s, may retry).
        try:
            ok = await open_fn_to_use(_make_router(key))
        except Exception as e:
            logger.warning(f"[PrivateStream:{key}] open failed: {e}")
            ok = False
        stop_orphan = False
        async with _registry_lock:
            entry = _entries.get(key)
            if entry is None:
                return False
            entry.opening = False
            try:
                if not entry.subscribers:
                    # Everyone left while we were opening: stop the orphan
                    # with our own stop_fn (it opened this loop) and drop it.
                    stop_orphan = bool(ok)
                    _entries.pop(key, None)
                    return False
                if ok:
                    entry.running = True
                    entry.opened_at = time.monotonic()
                    logger.info(
                        f"[PrivateStream:{key}] shared loop live "
                        f"({len(entry.subscribers)} subscriber(s))."
                    )
                    return True
                # Open failed: drop our subscription, keep others intact.
                entry.subscribers.pop(sub_id, None)
                if not entry.subscribers:
                    _entries.pop(key, None)
                return False
            finally:
                entry.opened_event.set()
        if stop_orphan:
            try:
                await stop_fn()
            except Exception as e:
                logger.warning(f"[PrivateStream:{key}] orphan stop failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"[PrivateStream:{key}] ensure failed: {e}")
        return False


def report_heat(exchange_id: str, api_key_id: Any, heat: Optional[float]) -> None:
    """Refresh the promotion heat of a tracked key (relative TP/SL distance).

    Smaller = hotter. None clears to unknown. Best effort, never raises.
    """
    try:
        key = (_norm_exchange(exchange_id), api_key_id)
        if api_key_id is None:
            return
        entry = _entries.get(key)
        if entry is not None:
            entry.heat = heat
    except Exception:
        pass


def should_poll(exchange_id: str, api_key_id: Any, interval_seconds: float) -> bool:
    """True when this caller should run the REST poll for the key now.

    Per-key (not per-controller) sharing: with several strategies on one key
    a single poll covers all siblings, so the rest skip their tick. Hot keys
    (positions near TP/SL without a WS slot) pass a shorter interval.
    Occasional double-poll on a race is harmless (fill handling dedups).
    """
    try:
        key = (_norm_exchange(exchange_id), api_key_id)
        if api_key_id is None:
            return True
        now = time.monotonic()
        if now - _last_poll.get(key, 0.0) < interval_seconds:
            return False
        _last_poll[key] = now
        return True
    except Exception:
        return True


async def release_stream(exchange_id: str, api_key_id: Any, sub_id: Any) -> None:
    """Detach; stop the loop when nobody needs it, migrate owner otherwise."""
    key = (_norm_exchange(exchange_id), api_key_id)
    if api_key_id is None:
        return
    migrate_to = None
    stop_fn = None
    try:
        async with _registry_lock:
            entry = _entries.get(key)
            if entry is None:
                return
            left = entry.subscribers.pop(sub_id, None)
            if left is None:
                return
            logger.info(
                f"[PrivateStream:{key}] subscriber {left.label} detached "
                f"({len(entry.subscribers)} left)."
            )
            if not entry.subscribers:
                if entry.running:
                    stop_fn = left.stop_fn
                _entries.pop(key, None)
            elif entry.owner_sub_id == sub_id and entry.running:
                # Owner left with subscribers remaining: migrate the loop.
                nxt = next(iter(entry.subscribers.values()))
                entry.owner_sub_id = nxt.sub_id
                entry.running = False
                migrate_to = nxt
        if stop_fn is not None:
            try:
                await stop_fn()
            except Exception as e:
                logger.warning(f"[PrivateStream:{key}] stop failed: {e}")
            logger.info(f"[PrivateStream:{key}] shared loop stopped (no demand).")
        elif migrate_to is not None:
            try:
                ok = await migrate_to.open_fn(_make_router(key))
            except Exception as e:
                logger.warning(f"[PrivateStream:{key}] migrate failed: {e}")
                ok = False
            async with _registry_lock:
                entry = _entries.get(key)
                if entry is not None and entry.owner_sub_id == migrate_to.sub_id:
                    entry.running = bool(ok)
    except Exception as e:
        logger.warning(f"[PrivateStream:{key}] release failed: {e}")


def subscriber_count(exchange_id: str, api_key_id: Any) -> int:
    entry = _entries.get((_norm_exchange(exchange_id), api_key_id))
    return len(entry.subscribers) if entry else 0


def is_stream_running(exchange_id: str, api_key_id: Any) -> bool:
    entry = _entries.get((_norm_exchange(exchange_id), api_key_id))
    return bool(entry and entry.running)


def stream_owner(exchange_id: str, api_key_id: Any) -> Any:
    entry = _entries.get((_norm_exchange(exchange_id), api_key_id))
    return entry.owner_sub_id if entry else None


def reset_registry() -> None:
    """Test hook: drop all entries (callers must stop their own loops)."""
    _entries.clear()
    _open_attempts.clear()
    _last_poll.clear()


async def wait_until_idle_shutdown() -> None:
    """Test/finalization hook: best-effort stop of every tracked loop."""
    async with _registry_lock:
        items = list(_entries.items())
        _entries.clear()
    for key, entry in items:
        try:
            if entry.running and entry.owner_sub_id is not None:
                owner = entry.subscribers.get(entry.owner_sub_id)
                if owner is not None:
                    await owner.stop_fn()
        except Exception:
            pass
        logger.info(f"[PrivateStream:{key}] force-stopped.")
