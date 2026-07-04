import ast
from pathlib import Path

from api.schemas import SymbolSelectionConfig as ApiSymbolSelectionConfig
from bot_module.symbol_selection import SymbolSelectionConfig


def test_api_reexports_runtime_symbol_selection_config():
    assert ApiSymbolSelectionConfig is SymbolSelectionConfig
    assert SymbolSelectionConfig(mode="STATIC").model_dump() == {
        "mode": "STATIC",
        "min_natr": 0.0,
        "oracle_regime": None,
        "oracle_confidence": 0.0,
        "max_concurrent_symbols": 1,
    }


def test_controller_does_not_import_api_schemas_for_symbol_selection():
    controller_path = Path("bot_module/controller.py")
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "api.schemas":
            imports.extend(alias.name for alias in node.names)

    assert "SymbolSelectionConfig" not in imports


def test_trading_runtime_modules_do_not_import_api_layer():
    runtime_modules = [
        Path("bot_module/controller.py"),
        Path("bot_module/paper_executor.py"),
        Path("bot_module/telegram_notifier.py"),
        Path("bot_module/risk_manager.py"),
    ]

    offenders = []
    for path in runtime_modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "api" or alias.name.startswith("api."):
                        offenders.append(f"{path}:{node.lineno}:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "api" or module.startswith("api."):
                    offenders.append(f"{path}:{node.lineno}:{module}")

    assert offenders == []
