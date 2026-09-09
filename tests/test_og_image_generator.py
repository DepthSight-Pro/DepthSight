from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request

from api.og_image_generator import _generate_equity_svg_path, generate_og_image
from api.routes.public import (
    _get_base_url,
    _is_social_bot,
    _render_shared_html,
    get_og_image,
    get_shared_backtest_page_or_og,
)
from api.schemas import SharedBacktestData, SharedBacktestPeriod


def _shared_data(equity_curve, kpis=None):
    if kpis is None:
        kpis = {"total_return_pct": 12.5, "max_drawdown_pct": 3.0}
    return SharedBacktestData(
        strategyName="Shared Strategy",
        symbol="BTCUSDT",
        period=SharedBacktestPeriod(
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        kpis=kpis,
        equityCurve=equity_curve,
        parameters={},
    )


def test_generate_equity_svg_path_handles_empty_and_flat_curves():
    assert _generate_equity_svg_path([], width=400, height=160) == ""

    path = _generate_equity_svg_path([[0, 1000], [1, 1000]], width=400, height=160)

    assert path.startswith("M ")
    assert "L" in path


async def test_generate_og_image_returns_png_bytes_for_shared_backtest():
    class FakeBrowser:
        async def new_page(self):
            page = AsyncMock()
            page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfake-image")
            return page

        async def close(self):
            return None

    class FakePlaywright:
        chromium = AsyncMock()

        async def __aenter__(self):
            self.chromium.launch = AsyncMock(return_value=FakeBrowser())
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch(
        "api.og_image_generator.async_playwright", return_value=FakePlaywright()
    ):
        image = await generate_og_image(_shared_data([[0, 1000], [1, 1125]]))

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert image == b"\x89PNG\r\n\x1a\nfake-image"


async def test_generate_og_image_handles_none_and_missing_kpis():
    class FakeBrowser:
        async def new_page(self):
            page = AsyncMock()
            page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nrobust")
            return page

        async def close(self):
            return None

    class FakePlaywright:
        chromium = AsyncMock()

        async def __aenter__(self):
            self.chromium.launch = AsyncMock(return_value=FakeBrowser())
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch(
        "api.og_image_generator.async_playwright", return_value=FakePlaywright()
    ):
        # KPI with None values and alternative trade / dd keys
        data = _shared_data(
            [],
            kpis={
                "total_pnl": None,
                "win_rate": None,
                "max_drawdown": None,
                "max_drawdown_pct": 5.5,
                "trades": None,
                "total_trades": 42,
            },
        )
        image = await generate_og_image(data)
        assert image == b"\x89PNG\r\n\x1a\nrobust"


def test_is_social_bot_detection():
    # Social bots
    assert _is_social_bot("TelegramBot (like TwitterBot)") is True
    assert _is_social_bot("Twitterbot/1.0") is True
    assert (
        _is_social_bot(
            "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
        )
        is True
    )
    assert _is_social_bot("WhatsApp/2.21.12.21 A") is True
    assert (
        _is_social_bot("Mozilla/5.0 (compatible; Discordbot/2.0; +https://discord.app)")
        is True
    )
    assert _is_social_bot("Slackbot-LinkExpanding 1.0") is True

    # Regular browsers
    assert (
        _is_social_bot(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        is False
    )
    assert (
        _is_social_bot(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
        )
        is False
    )
    assert _is_social_bot("") is False
    assert _is_social_bot(None) is False


def test_get_base_url_extracts_forwarded_headers():
    req = Request(
        scope={
            "type": "http",
            "headers": [
                (b"x-forwarded-host", b"app.depthsight.pro"),
                (b"x-forwarded-proto", b"https, https"),
            ],
        }
    )
    assert _get_base_url(req) == "https://app.depthsight.pro"


@pytest.mark.asyncio
async def test_render_shared_html_contains_complete_og_tags():
    req = Request(
        scope={
            "type": "http",
            "headers": [
                (b"host", b"app.depthsight.pro"),
                (b"x-forwarded-proto", b"https"),
            ],
        }
    )

    fake_shared_data = {
        "data": {
            "strategyName": "EMA SuperTrend",
            "symbol": "ETHUSDT",
            "period": {"start": "2024-01-01T00:00:00Z", "end": "2024-06-01T00:00:00Z"},
            "kpis": {"total_pnl": 2450.50, "win_rate": 72.4},
            "equityCurve": [],
        }
    }

    with patch(
        "api.routes.public.get_shared_backtest_data",
        new_callable=AsyncMock,
        return_value=fake_shared_data,
    ):
        response = await _render_shared_html("sample-slug", req, db=AsyncMock())

    assert response.status_code == 200
    html_text = response.body.decode("utf-8")

    assert (
        '<meta property="og:title" content="DepthSight Report: EMA SuperTrend on ETHUSDT">'
        in html_text
    )
    assert "Performance: +2450.50 USD PNL | Win Rate: 72.4%" in html_text
    assert (
        '<meta property="og:image" content="https://app.depthsight.pro/og-image/sample-slug.png">'
        in html_text
    )
    assert (
        '<meta property="og:image:secure_url" content="https://app.depthsight.pro/og-image/sample-slug.png">'
        in html_text
    )
    assert '<meta name="twitter:card" content="summary_large_image">' in html_text
    assert (
        '<meta name="twitter:image" content="https://app.depthsight.pro/og-image/sample-slug.png">'
        in html_text
    )


@pytest.mark.asyncio
async def test_og_image_endpoint_uses_redis_cache():
    fake_redis = AsyncMock()
    # 1. First call: cache miss
    fake_redis.get.return_value = None

    fake_shared_data = {
        "data": {
            "strategyName": "Strategy",
            "symbol": "BTCUSDT",
            "period": {"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"},
            "kpis": {"total_pnl": 100.0, "win_rate": 60.0},
            "equityCurve": [],
        }
    }

    with (
        patch(
            "api.routes.public.get_shared_backtest_data",
            new_callable=AsyncMock,
            return_value=fake_shared_data,
        ),
        patch(
            "api.routes.public.generate_og_image",
            new_callable=AsyncMock,
            return_value=b"\x89PNG\r\n\x1a\nfresh-og-image",
        ),
    ):
        resp1 = await get_og_image("test-slug", db=AsyncMock(), redis_client=fake_redis)

    assert resp1.body == b"\x89PNG\r\n\x1a\nfresh-og-image"
    assert resp1.headers.get("X-Cache") == "MISS"
    fake_redis.set.assert_awaited_once_with(
        "og_image:test-slug", b"\x89PNG\r\n\x1a\nfresh-og-image", ex=86400
    )

    # 2. Second call: cache hit
    fake_redis.get.return_value = b"\x89PNG\r\n\x1a\ncached-og-image"
    resp2 = await get_og_image("test-slug", db=AsyncMock(), redis_client=fake_redis)
    assert resp2.body == b"\x89PNG\r\n\x1a\ncached-og-image"
    assert resp2.headers.get("X-Cache") == "HIT"


@pytest.mark.asyncio
async def test_s_route_handles_bot_and_regular_browser():
    bot_req = Request(
        scope={
            "type": "http",
            "headers": [
                (b"user-agent", b"TelegramBot (like TwitterBot)"),
                (b"host", b"app.depthsight.pro"),
                (b"x-forwarded-proto", b"https"),
            ],
        }
    )

    fake_shared_data = {
        "data": {
            "strategyName": "Strategy",
            "symbol": "BTCUSDT",
            "period": {"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"},
            "kpis": {"total_pnl": 50.0, "win_rate": 50.0},
            "equityCurve": [],
        }
    }

    with patch(
        "api.routes.public.get_shared_backtest_data",
        new_callable=AsyncMock,
        return_value=fake_shared_data,
    ):
        # Bot request should return HTML with OG tags
        bot_resp = await get_shared_backtest_page_or_og(
            "my-slug", bot_req, db=AsyncMock()
        )
        assert bot_resp.status_code == 200
        assert b"og:title" in bot_resp.body

    # Regular user request should redirect to frontend URL
    user_req = Request(
        scope={
            "type": "http",
            "headers": [
                (b"user-agent", b"Mozilla/5.0 Chrome/120.0.0.0"),
                (b"host", b"app.depthsight.pro"),
                (b"x-forwarded-proto", b"https"),
            ],
        }
    )
    user_resp = await get_shared_backtest_page_or_og(
        "my-slug", user_req, db=AsyncMock()
    )
    assert user_resp.status_code == 302
    assert user_resp.headers["location"] == "https://app.depthsight.pro/s/my-slug"
