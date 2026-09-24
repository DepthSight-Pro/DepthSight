# tests/test_xlsx_import_fallback.py
"""
Broker XLSX importers live in gitignored hub_private and may be absent in
open-source builds. The admin endpoints must degrade with HTTP 501 (clear
message for the frontend) instead of crashing with ImportError -> 500.
"""

import importlib

import pytest
from fastapi import HTTPException

from api.routes.config import _load_broker_xlsx_importer


def test_loader_returns_module_when_present():
    module = _load_broker_xlsx_importer("hub_private.import_weex_xlsx", "Weex")
    assert hasattr(module, "parse_weex_xlsx")
    assert hasattr(module, "apply_weex_groups_session")


def test_loader_raises_501_when_module_missing(monkeypatch):
    real_import_module = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "hub_private.import_weex_xlsx":
            raise ImportError("No module named 'hub_private'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(HTTPException) as exc_info:
        _load_broker_xlsx_importer("hub_private.import_weex_xlsx", "Weex")
    assert exc_info.value.status_code == 501
    assert "not included in this build" in exc_info.value.detail
