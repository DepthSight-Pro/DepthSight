import json
import logging
from types import SimpleNamespace

from api.audit_logger import AuditEventType, AuditLogger, get_client_ip, get_user_agent


def test_audit_logger_writes_structured_security_event(tmp_path):
    log_file = tmp_path / "audit.log"
    audit_python_logger = logging.getLogger("security_audit")
    for handler in list(audit_python_logger.handlers):
        audit_python_logger.removeHandler(handler)
        handler.close()
    logger = AuditLogger(log_file=str(log_file))

    logger.log_event(
        AuditEventType.LOGIN_FAILED,
        user_id=42,
        username="alice",
        ip_address="203.0.113.10",
        user_agent="pytest",
        details={"reason": "bad_password"},
    )

    event = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert event["event_type"] == AuditEventType.LOGIN_FAILED.value
    assert event["user_id"] == 42
    assert event["details"] == {"reason": "bad_password"}
    assert event["severity"] == "INFO"


def test_audit_request_helpers_prefer_proxy_headers():
    request = SimpleNamespace(
        headers={
            "X-Forwarded-For": "198.51.100.20, 10.0.0.1",
            "User-Agent": "DepthSightTest/1.0",
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert get_client_ip(request) == "10.0.0.1"
    assert get_user_agent(request) == "DepthSightTest/1.0"
