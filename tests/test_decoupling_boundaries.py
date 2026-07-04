import sys


def test_exchanges_common_does_not_import_ccxt():
    # Remove exchanges-related modules from sys.modules to force clean imports
    to_remove = [
        "ccxt",
        "bot_module.exchanges",
        "bot_module.exchanges.factory",
        "bot_module.exchanges.ccxt_executor",
        "bot_module.exchanges.common",
    ]
    saved_modules = {}
    for mod in to_remove:
        if mod in sys.modules:
            saved_modules[mod] = sys.modules.pop(mod)

    try:
        # Import the common exchanges utilities
        from bot_module.exchanges.common import (
            normalize_exchange_id,
            exchange_settings_key,
            is_binance_exchange,
        )

        # Assert functional correctness of the isolated helpers
        assert normalize_exchange_id("binance") == "binance"
        assert normalize_exchange_id("bybit") == "bybit_linear"
        assert exchange_settings_key("bybit_futures") == "bybit_linear"
        assert is_binance_exchange("binance_futures") is True
        assert is_binance_exchange("bybit_linear") is False

        # Assert that ccxt and execution modules were NOT imported
        assert "ccxt" not in sys.modules
        assert "bot_module.exchanges.factory" not in sys.modules
        assert "bot_module.exchanges.ccxt_executor" not in sys.modules

    finally:
        # Restore sys.modules
        for mod, val in saved_modules.items():
            sys.modules[mod] = val


def test_celery_app_does_not_import_tasks():
    # Remove tasks-related modules from sys.modules
    to_remove = [
        "tasks",
        "api.celery_app",
    ]
    saved_modules = {}
    for mod in to_remove:
        if mod in sys.modules:
            saved_modules[mod] = sys.modules.pop(mod)

    try:
        # Import the Celery app
        from api.celery_app import (
            celery_app,
            _simulation_inspector_state_key,
        )

        assert celery_app is not None
        assert (
            _simulation_inspector_state_key("test_task")
            == "simulation-inspector:test_task"
        )

        # Assert that the full tasks definitions file was NOT imported
        assert "tasks" not in sys.modules

    finally:
        # Restore sys.modules
        for mod, val in saved_modules.items():
            sys.modules[mod] = val
