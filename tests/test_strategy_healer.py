# tests/test_strategy_healer.py
import pytest
from bot_module.strategy_healer import heal_strategy_config
from bot_module.fast_vector_backtester import FastVectorBacktester


def test_healer_rewires_broken_block_id_and_key_aliases():
    broken_config = {
        "symbol": "LINKUSDT",
        "entryConditions": {
            "id": "root",
            "type": "OR",
            "children": [
                {
                    "id": "w_breakout_long",
                    "type": "AND",
                    "children": [
                        {
                            "id": "413172e8-9b35-4dfc-8dba-5ad25a5cccf8",
                            "type": "local_level",
                            "params": {
                                "timeframe": "1h",
                                "is_data_provider": True,
                                "level_type": "high",
                            },
                        },
                        {
                            "id": "cmp_block",
                            "type": "value_comparison",
                            "params": {
                                "operator": "gt",
                                "leftOperand": {"source": "candle", "key": "close"},
                                "rightOperand": {
                                    "source": "block_result",
                                    "block_id": "provider_1h_high",  # Broken hallucinated ID!
                                    "field": "level_price",  # 'field' instead of 'key'
                                },
                            },
                        },
                    ],
                }
            ],
        },
        "foundation_weights": {"breakout_long": 100},  # Mismatched with w_breakout_long
    }

    healed = heal_strategy_config(broken_config, symbol="LINKUSDT")

    # 1. block_id must be rewired to the provider's actual UUID
    right_op = healed["entryConditions"]["children"][0]["children"][1]["params"][
        "rightOperand"
    ]
    assert right_op["block_id"] == "413172e8-9b35-4dfc-8dba-5ad25a5cccf8"
    assert right_op["key"] == "detected_level"
    assert "field" not in right_op

    # 2. foundation_weights must be synchronized
    weights = healed["foundation_weights"]
    assert "w_breakout_long" in weights
    assert weights["w_breakout_long"] == 100


def test_healer_adapts_unscaled_atr_to_natr_on_altcoins():
    altcoin_config = {
        "symbol": "LINKUSDT",
        "filters": {
            "type": "AND",
            "children": [
                {
                    "id": "v_filter",
                    "type": "volatility_filter",
                    "params": {
                        "indicator": "ATR",
                        "operator": "gt",
                        "value": 1.5,  # 1.5 is absurd on LINK ($15) where 1m ATR is $0.02
                    },
                }
            ],
        },
    }

    healed = heal_strategy_config(altcoin_config, symbol="LINKUSDT")
    filter_node = healed["filters"]["children"][0]

    # Must be converted to natr_filter
    assert filter_node["type"] == "natr_filter"
    assert "natr_threshold" in filter_node["params"]
    assert filter_node["params"]["natr_threshold"] == pytest.approx(0.3)


def test_healer_preserves_atr_on_high_priced_assets():
    btc_config = {
        "symbol": "BTCUSDT",
        "filters": {
            "type": "AND",
            "children": [
                {
                    "id": "v_filter",
                    "type": "volatility_filter",
                    "params": {
                        "indicator": "ATR",
                        "operator": "gt",
                        "value": 15.0,  # 15.0 is valid on BTC ($60,000)
                    },
                }
            ],
        },
    }

    healed = heal_strategy_config(btc_config, symbol="BTCUSDT")
    filter_node = healed["filters"]["children"][0]

    # Must remain volatility_filter
    assert filter_node["type"] == "volatility_filter"
    assert filter_node["params"]["value"] == 15.0


def test_fast_vector_backtester_normalize_heals_broken_strategy():
    broken = {
        "symbol": "LINKUSDT",
        "min_foundation_weight_threshold": 35,
        "foundation_weights": {"breakout_long": 100},
        "filters": {
            "type": "AND",
            "children": [
                {
                    "id": "atr_filt",
                    "type": "volatility_filter",
                    "params": {"indicator": "ATR", "operator": "gt", "value": 1.5},
                }
            ],
        },
        "entryConditions": {
            "type": "OR",
            "children": [
                {
                    "id": "w_breakout_long",
                    "type": "AND",
                    "children": [
                        {
                            "id": "provider_uuid_12345",
                            "type": "local_level",
                            "params": {"is_data_provider": True, "level_type": "high"},
                        },
                        {
                            "id": "cmp_block",
                            "type": "value_comparison",
                            "params": {
                                "operator": "gt",
                                "rightOperand": {
                                    "source": "block_result",
                                    "block_id": "nonexistent_id",
                                    "field": "level_price",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }

    normalized = FastVectorBacktester.normalize_strategy(broken)

    # Check ATR converted to natr_filter
    assert normalized["filters"]["children"][0]["type"] == "natr_filter"

    # Check weights synchronized
    assert "w_breakout_long" in normalized["foundation_weights"]

    # Check block_id rewired to provider_uuid_12345
    cmp_op = normalized["entryConditions"]["children"][0]["children"][1]["params"][
        "rightOperand"
    ]
    assert cmp_op["block_id"] == "provider_uuid_12345"
    assert cmp_op["key"] == "detected_level"
