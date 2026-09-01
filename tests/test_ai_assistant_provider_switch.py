import pytest

from api import ai_assistant


@pytest.fixture(autouse=True)
def reset_ai_settings():
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    yield
    ai_assistant._DYNAMIC_AI_SETTINGS = None


def test_get_openrouter_model_name_defaults_to_opus_and_supports_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    assert ai_assistant._get_openrouter_model_name() == "anthropic/claude-opus-5"

    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    assert ai_assistant._get_openrouter_model_name() == "openai/gpt-4o-mini"

    # Fallback to Google model if openrouter model setting is explicitly empty
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_GEMINI_MODEL", "gemini-3-flash-preview")
    ai_assistant._DYNAMIC_AI_SETTINGS = None
    dyn = ai_assistant._get_dynamic_settings()
    dyn["providers"]["openrouter"]["model"] = ""
    assert ai_assistant._get_openrouter_model_name() == "google/gemini-3-flash-preview"


def test_extract_openrouter_response_text_supports_content_parts():
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": [
                        {"type": "text", "text": "First line"},
                        {"type": "text", "text": "Second line"},
                    ]
                },
            }
        ]
    }

    assert (
        ai_assistant._extract_openrouter_response_text(payload, require_complete=True)
        == "First line\nSecond line"
    )


def test_ensure_ai_provider_configured_requires_openrouter_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    ai_assistant._DYNAMIC_AI_SETTINGS = None

    with pytest.raises(ConnectionError, match="OPENROUTER_API_KEY"):
        ai_assistant._ensure_ai_provider_configured()


def test_get_active_ai_provider_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "invalid-provider")
    ai_assistant._DYNAMIC_AI_SETTINGS = None

    with pytest.raises(ConnectionError, match="Unsupported AI_PROVIDER"):
        ai_assistant._get_active_ai_provider()
