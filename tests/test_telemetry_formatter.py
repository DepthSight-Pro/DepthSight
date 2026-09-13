# tests/test_telemetry_formatter.py
from bot_module.telemetry_formatter import (
    extract_rejection_telemetry,
    format_event_log_markdown,
    _format_filter_node_label,
)


def test_telemetry_handles_none_and_empty():
    telemetry = extract_rejection_telemetry(None, None)
    assert telemetry["signals_generated_total"] == 0
    assert telemetry["trades_opened"] == 0
    assert telemetry["total_rejections"] == 0
    assert telemetry["primary_bottleneck"] is not None

    md = format_event_log_markdown(telemetry, language="ru")
    assert "**Сгенерировано сигналов**: 0" in md
    assert "**Всего отклонений**: **0**" in md
    assert "Аномалий не обнаружено" in md


def test_telemetry_extracts_full_screenshot_data_and_resolves_filter():
    # Matches the user's screenshot:
    # 105 signals, 59 trades, 346 rejections:
    # - Cooldown: 46
    # - Filter 841a5627-ed03-4b87-aad2-7bd32592698f: 300
    # Foundation breakout_long: 105
    strategy_config = {
        "symbol": "LINKUSDT",
        "filters": {
            "id": "root_filt",
            "type": "AND",
            "children": [
                {
                    "id": "841a5627-ed03-4b87-aad2-7bd32592698f",
                    "type": "volatility_filter",
                    "params": {
                        "indicator": "ATR",
                        "operator": "gt",
                        "value": 1.5,
                    },
                }
            ],
        },
        "entryConditions": {
            "id": "root_entry",
            "type": "OR",
            "children": [
                {"id": "w_breakout_long", "type": "AND", "children": []}
            ],
        },
    }

    analytics_report = {
        "event_counters": {
            "signals_generated_total": 105,
            "trades_opened": 59,
            "foundation_trigger_counts": {
                "breakout_long": 105,
            },
            "rejections": {
                "by_global_risk_limit": 0,
                "by_cooldown": 46,
                "by_filter": {
                    "841a5627-ed03-4b87-aad2-7bd32592698f": 300,
                },
                "by_weight_threshold": 0,
                "by_position_calculation": 0,
                "by_slippage_beyond_sl": 0,
                "by_risk_manager": 0,
                "by_risk_manager_reasons": {},
            },
        },
        "anomalies": [],
    }

    telemetry = extract_rejection_telemetry(analytics_report, strategy_config)

    assert telemetry["signals_generated_total"] == 105
    assert telemetry["trades_opened"] == 59
    assert telemetry["total_rejections"] == 346

    # Verify filter resolution
    filters = telemetry["rejections"]["by_filter"]
    assert len(filters) == 1
    assert filters[0]["id"] == "841a5627-ed03-4b87-aad2-7bd32592698f"
    assert filters[0]["count"] == 300
    assert "volatility_filter" in filters[0]["label"]
    assert "ATR gt 1.5" in filters[0]["label"]

    # Verify primary bottleneck detects the ATR filter
    assert "volatility_filter" in telemetry["primary_bottleneck"]
    assert "300 signals" in telemetry["primary_bottleneck"]

    md_ru = format_event_log_markdown(telemetry, language="ru")
    assert "**Сгенерировано сигналов**: 105" in md_ru
    assert "**Открыто сделок**: 59" in md_ru
    assert "**Всего отклонений**: **346**" in md_ru
    assert "Отклонено: Из-за перезарядки: 46" in md_ru
    assert "volatility_filter" in md_ru
    assert "`breakout_long`: 105" in md_ru
    assert "Аномалий не обнаружено" in md_ru

    # Check compact markdown
    md_compact = format_event_log_markdown(telemetry, compact=True)
    assert "Signals=105" in md_compact
    assert "Trades=59" in md_compact
    assert "Rejections=346" in md_compact
    assert "Primary Bottleneck" in md_compact


def test_telemetry_detects_cooldown_and_risk_manager_bottlenecks():
    # Case 1: Cooldown is largest
    report_cooldown = {
        "event_counters": {
            "signals_generated_total": 50,
            "trades_opened": 10,
            "rejections": {
                "by_cooldown": 40,
                "by_filter": {},
            },
        }
    }
    telemetry = extract_rejection_telemetry(report_cooldown)
    assert "Cooldown rejected 40 signals" in telemetry["primary_bottleneck"]

    # Case 2: Risk manager is largest
    report_rm = {
        "event_counters": {
            "signals_generated_total": 50,
            "trades_opened": 5,
            "rejections": {
                "by_risk_manager": 25,
                "by_risk_manager_reasons": {"DAILY_LOSS_LIMIT": 25},
            },
        }
    }
    telemetry_rm = extract_rejection_telemetry(report_rm)
    assert "DAILY_LOSS_LIMIT: 25" in telemetry_rm["primary_bottleneck"]


def test_format_filter_node_label():
    node = {
        "type": "natr_filter",
        "params": {"natr_threshold": 1.2},
    }
    label = _format_filter_node_label(node, "node123")
    assert label == "`natr_filter` [NATR > 1.2%]"

    node_trend = {
        "type": "trend_filter",
        "params": {"indicator": "ADX", "threshold": 25},
    }
    label_trend = _format_filter_node_label(node_trend, "node_adx")
    assert label_trend == "`trend_filter` [ADX, threshold=25]"
