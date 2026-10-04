"""Registry: one shared private stream per (exchange, api_key).

Exchanges cap simultaneous private WS per IP (Bitget 100, WEEX 20) and
single-session exchanges kick the previous login (Bitget 30017). One shared
loop per key fixes both; routing by clientOrderId ownership fixes the
MANUAL_CLOSE_DETECTED / external-SL-adoption cross-talk between siblings.
"""

import asyncio

import pytest

from bot_module import private_stream_registry as reg


@pytest.fixture(autouse=True)
def _clean():
    reg.reset_registry()
    yield
    reg.reset_registry()


def _sub(sub_id, owned=(), inbox=None, opens=None):
    inbox = inbox if inbox is not None else []
    opens = opens if opens is not None else []

    async def on_event(event):
        inbox.append(event)

    def owns_cid(cid):
        return cid in set(owned)

    async def open_fn(router):
        opens.append(router)
        return True

    async def stop_fn():
        opens.clear()

    return {
        "sub_id": sub_id,
        "on_event": on_event,
        "owns_cid": owns_cid,
        "open_fn": open_fn,
        "stop_fn": stop_fn,
    }


def _ensure(exchange="bitget", key=7, **kw):
    return reg.ensure_stream(exchange, key, **kw)


@pytest.mark.asyncio
async def test_single_loop_for_many_subscribers():
    recs = {i: _sub(i) for i in ("a", "b", "c")}
    for i in ("a", "b", "c"):
        r = recs[i]
        assert (
            await _ensure(
                sub_id=i,
                on_event=r["on_event"],
                owns_cid=r["owns_cid"],
                open_fn=r["open_fn"],
                stop_fn=r["stop_fn"],
            )
            is True
        )
    assert reg.subscriber_count("bitget", 7) == 3
    assert reg.is_stream_running("bitget", 7) is True
    assert reg.stream_owner("bitget", 7) == "a"


@pytest.mark.asyncio
async def test_routing_delivers_only_to_owner():
    inbox_a, inbox_b = [], []
    rec_a = _sub("a", owned={"x-entry-aaa"}, inbox=inbox_a)
    rec_b = _sub("b", owned={"x-entry-bbb"}, inbox=inbox_b)
    for r in (rec_a, rec_b):
        assert (
            await _ensure(
                sub_id=r["sub_id"],
                on_event=r["on_event"],
                owns_cid=r["owns_cid"],
                open_fn=r["open_fn"],
                stop_fn=r["stop_fn"],
            )
            is True
        )

    await reg._route_event(
        ("bitget", 7),
        {"e": "ORDER_TRADE_UPDATE", "o": {"c": "x-entry-aaa", "X": "FILLED"}},
    )
    assert len(inbox_a) == 1
    assert len(inbox_b) == 0, "sibling must not receive another controller fill"

    await reg._route_event(("bitget", 7), {"e": "ACCOUNT_UPDATE", "a": {}})
    assert len(inbox_a) == 2
    assert len(inbox_b) == 1, "balance events go to everyone"


@pytest.mark.asyncio
async def test_release_stops_at_zero_and_migrates_owner():
    stopped = []
    rec_a = _sub("a")
    rec_b = _sub("b")

    async def stop_a():
        stopped.append("a")

    async def stop_b():
        stopped.append("b")

    rec_a["stop_fn"] = stop_a
    rec_b["stop_fn"] = stop_b
    for r in (rec_a, rec_b):
        assert (
            await _ensure(
                sub_id=r["sub_id"],
                on_event=r["on_event"],
                owns_cid=r["owns_cid"],
                open_fn=r["open_fn"],
                stop_fn=r["stop_fn"],
            )
            is True
        )
    assert reg.stream_owner("bitget", 7) == "a"

    await reg.release_stream("bitget", 7, "a")  # owner leaves, b remains
    assert stopped == [], "loop must migrate, not stop"
    assert reg.is_stream_running("bitget", 7) is True
    assert reg.stream_owner("bitget", 7) == "b"

    await reg.release_stream("bitget", 7, "b")
    assert stopped == ["b"], "last release stops the loop"
    assert reg.is_stream_running("bitget", 7) is False


@pytest.mark.asyncio
async def test_concurrent_ensure_opens_once():
    opens = []

    async def slow_open(router):
        await asyncio.sleep(0.05)
        opens.append(1)
        return True

    async def noop_stop():
        pass

    async def noop_event(event):
        pass

    results = await asyncio.gather(
        *[
            reg.ensure_stream(
                "bitget",
                7,
                f"s{i}",
                noop_event,
                lambda cid: False,
                slow_open,
                noop_stop,
            )
            for i in range(5)
        ]
    )
    assert all(results)
    assert len(opens) == 1, "concurrent ensurers must join, not double-login"


@pytest.mark.asyncio
async def test_failed_open_drops_only_requester():
    async def fail_open(router):
        return False

    async def noop_stop():
        pass

    async def noop_event(event):
        pass

    assert (
        await reg.ensure_stream(
            "bitget", 7, "a", noop_event, lambda cid: False, fail_open, noop_stop
        )
        is False
    )
    assert reg.subscriber_count("bitget", 7) == 0


@pytest.mark.asyncio
async def test_none_key_never_shared():
    async def noop_stop():
        pass

    async def noop_event(event):
        pass

    async def ok_open(router):
        return True

    assert (
        await reg.ensure_stream(
            "bitget", None, "a", noop_event, lambda cid: False, ok_open, noop_stop
        )
        is False
    )


@pytest.mark.asyncio
async def test_budget_rejects_over_cap(monkeypatch):
    """Simultaneous loops per exchange are capped; losers go to REST poll."""
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONN_BUDGET, "bitget", 2)
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONNS_PER_KEY, "bitget", 1)
    rec_a, rec_b, rec_c = _sub("a"), _sub("b"), _sub("c")
    assert await _ensure(key=1, **rec_a) is True
    assert await _ensure(key=2, **rec_b) is True
    assert await _ensure(key=3, **rec_c) is False
    assert reg.is_stream_running("bitget", 3) is False
    assert reg.subscriber_count("bitget", 3) == 0, "rejected sub must not linger"


@pytest.mark.asyncio
async def test_rate_bucket_throttles_open_storm(monkeypatch):
    """Aggregate open rate is bounded even when every key retries at once."""
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONN_RATE_PER_MIN, "bitget", 2)
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONNS_PER_KEY, "bitget", 1)
    assert await _ensure(key=11, **_sub("a")) is True
    assert await _ensure(key=12, **_sub("b")) is True
    assert await _ensure(key=13, **_sub("c")) is False


@pytest.mark.asyncio
async def test_hot_newcomer_evicts_coldest(monkeypatch):
    """A clearly hotter key takes over the coldest running loop past min-hold."""
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONN_BUDGET, "bitget", 1)
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONNS_PER_KEY, "bitget", 1)
    monkeypatch.setattr(reg.config, "PRIVATE_WS_MIN_HOLD_SECONDS", 0.0)
    monkeypatch.setattr(reg.config, "PRIVATE_WS_PROMOTE_MARGIN", 1.5)
    stopped = []

    async def victim_stop():
        stopped.append(1)

    rec_cold = _sub("cold")
    rec_cold["stop_fn"] = victim_stop
    assert await _ensure(key=21, heat=0.5, **rec_cold) is True
    assert reg.is_stream_running("bitget", 21) is True

    rec_hot = _sub("hot")
    assert await _ensure(key=22, heat=0.001, **rec_hot) is True
    assert stopped == [1], "victim loop must be stopped on eviction"
    assert reg.is_stream_running("bitget", 21) is False
    assert reg.is_stream_running("bitget", 22) is True
    # Evicted subscribers stay attached and fall back to polling.
    assert reg.subscriber_count("bitget", 21) == 1


@pytest.mark.asyncio
async def test_cold_newcomer_rejected_when_full(monkeypatch):
    """Without a clear heat advantage the newcomer stays on REST poll."""
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONN_BUDGET, "bitget", 1)
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONNS_PER_KEY, "bitget", 1)
    monkeypatch.setattr(reg.config, "PRIVATE_WS_MIN_HOLD_SECONDS", 0.0)
    assert await _ensure(key=31, heat=0.001, **_sub("hot")) is True
    assert await _ensure(key=32, heat=0.5, **_sub("cold")) is False
    assert await _ensure(key=33, **_sub("unknown")) is False


@pytest.mark.asyncio
async def test_min_hold_protects_fresh_loops(monkeypatch):
    """A loop younger than min-hold cannot be evicted, however hot the rival."""
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONN_BUDGET, "bitget", 1)
    monkeypatch.setitem(reg.config.PRIVATE_WS_CONNS_PER_KEY, "bitget", 1)
    monkeypatch.setattr(reg.config, "PRIVATE_WS_MIN_HOLD_SECONDS", 3600.0)
    assert await _ensure(key=41, heat=0.5, **_sub("fresh")) is True
    assert await _ensure(key=42, heat=0.0001, **_sub("hot")) is False


def test_should_poll_shares_per_key():
    assert reg.should_poll("bitget", 51, 60.0) is True
    assert reg.should_poll("bitget", 51, 60.0) is False
    assert reg.should_poll("bitget", 52, 60.0) is True, "other keys unaffected"
    assert reg.should_poll("bitget", None, 60.0) is True


@pytest.mark.asyncio
async def test_report_heat_updates_entry():
    await _ensure(key=61, heat=0.25, **_sub("a"))
    reg.report_heat("bitget", 61, 0.01)
    assert reg._entries[("bitget", 61)].heat == 0.01
    reg.report_heat("bitget", 61, None)
    assert reg._entries[("bitget", 61)].heat is None
