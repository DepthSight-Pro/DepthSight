# tests/test_push_sender.py
"""Unit tests for api.push_sender delivery statuses."""

import json

import pytest
from pywebpush import WebPushException

import api.push_sender as push_sender


@pytest.fixture
def vapid_keys(monkeypatch):
    monkeypatch.setattr(push_sender, "VAPID_PRIVATE_KEY", "test-private")
    monkeypatch.setattr(push_sender, "VAPID_PUBLIC_KEY", "test-public")


SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}


def test_sent(monkeypatch, vapid_keys):
    calls = {}

    def fake_webpush(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(push_sender, "webpush", fake_webpush)
    status = push_sender.send_push_notification(
        dict(SUB), "Title", "Body", tag="t1", url="/pwa/?screen=notifications"
    )
    assert status == push_sender.PUSH_SENT
    payload = json.loads(calls["data"])
    assert payload == {
        "title": "Title",
        "body": "Body",
        "tag": "t1",
        "url": "/pwa/?screen=notifications",
    }


def test_url_omitted_when_none(monkeypatch, vapid_keys):
    calls = {}

    def fake_webpush(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(push_sender, "webpush", fake_webpush)
    assert (
        push_sender.send_push_notification(dict(SUB), "T", "B") == push_sender.PUSH_SENT
    )
    assert "url" not in json.loads(calls["data"])


@pytest.mark.parametrize("code", [404, 410])
def test_expired(monkeypatch, vapid_keys, code):
    class FakeResponse:
        status_code = code
        text = "gone"

    def fake_webpush(**kwargs):
        raise WebPushException("gone", response=FakeResponse())

    monkeypatch.setattr(push_sender, "webpush", fake_webpush)
    assert (
        push_sender.send_push_notification(dict(SUB), "T", "B")
        == push_sender.PUSH_EXPIRED
    )


def test_failed_on_server_error(monkeypatch, vapid_keys):
    class FakeResponse:
        status_code = 500
        text = "boom"

    def fake_webpush(**kwargs):
        raise WebPushException("boom", response=FakeResponse())

    monkeypatch.setattr(push_sender, "webpush", fake_webpush)
    assert (
        push_sender.send_push_notification(dict(SUB), "T", "B")
        == push_sender.PUSH_FAILED
    )


def test_failed_on_unexpected_error(monkeypatch, vapid_keys):
    def fake_webpush(**kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(push_sender, "webpush", fake_webpush)
    assert (
        push_sender.send_push_notification(dict(SUB), "T", "B")
        == push_sender.PUSH_FAILED
    )


def test_not_configured(monkeypatch):
    monkeypatch.setattr(push_sender, "VAPID_PRIVATE_KEY", None)
    monkeypatch.setattr(push_sender, "VAPID_PUBLIC_KEY", None)
    assert (
        push_sender.send_push_notification(dict(SUB), "T", "B")
        == push_sender.PUSH_NOT_CONFIGURED
    )
