# api/audit_logger.py
"""
Audit Logger for security events.
Logs critical security events: logins, authentication errors,
password changes, API key creation, etc.
"""

import os
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum
from pathlib import Path


class AuditEventType(str, Enum):
    """Audit event types."""

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    REGISTER = "REGISTER"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET_REQUEST = "PASSWORD_RESET_REQUEST"
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_DELETED = "API_KEY_DELETED"
    API_KEY_TESTED = "API_KEY_TESTED"
    API_KEY_STATUS_CHANGED = "API_KEY_STATUS_CHANGED"
    API_KEY_DECRYPT_FAILED = "API_KEY_DECRYPT_FAILED"
    ADMIN_IMPERSONATION = "ADMIN_IMPERSONATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"


class AuditLogger:
    """
    Centralized logger for security events.
    Writes to a separate file and can send to Redis for real-time monitoring.
    """

    def __init__(self, log_file: Optional[str] = None):
        # Path from env or default
        if log_file is None:
            log_file = os.getenv("AUDIT_LOG_PATH", "logs/security_audit.log")

        self.logger = logging.getLogger("security_audit")
        self.logger.setLevel(logging.INFO)

        # Avoid duplicate handlers
        if not self.logger.handlers:
            try:
                # Create directory if it does not exist
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)

                # File handler with JSON format for parsing
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(logging.INFO)

                # Simple formatter - JSON will be formatted manually
                formatter = logging.Formatter("%(message)s")
                file_handler.setFormatter(formatter)

                self.logger.addHandler(file_handler)
                print(f"[AuditLogger] Initialized. Logging to: {log_file}")
            except Exception as e:
                # Fallback to stderr if failed to open file
                print(f"[AuditLogger] WARNING: Could not create file handler: {e}")
                print("[AuditLogger] Falling back to stderr")
                stderr_handler = logging.StreamHandler()
                stderr_handler.setLevel(logging.INFO)
                stderr_handler.setFormatter(logging.Formatter("[AUDIT] %(message)s"))
                self.logger.addHandler(stderr_handler)

    def log_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "INFO",
    ):
        """
        Writes a security event to the log.

        Args:
            event_type: Type of event
            user_id: User ID (if known)
            username: Username (if known)
            ip_address: Client IP address
            user_agent: Browser User-Agent
            success: Whether the action succeeded
            details: Additional details
            severity: INFO, WARNING, CRITICAL
        """
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type.value,
            "success": success,
            "severity": severity,
            "user_id": user_id,
            "username": username,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details": details or {},
        }

        # Remove None values for compactness
        event = {k: v for k, v in event.items() if v is not None}

        # Log as JSON
        log_line = json.dumps(event, ensure_ascii=False)

        if severity == "CRITICAL":
            self.logger.critical(log_line)
        elif severity == "WARNING":
            self.logger.warning(log_line)
        else:
            self.logger.info(log_line)

    def login_success(
        self,
        user_id: int,
        username: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """Logs a successful login."""
        self.log_event(
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            success=True,
        )

    def login_failed(
        self,
        username: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        reason: str = "Invalid credentials",
    ):
        """Logs a failed login attempt."""
        self.log_event(
            event_type=AuditEventType.LOGIN_FAILED,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            details={"reason": reason},
            severity="WARNING",
        )

    def admin_impersonation(
        self,
        admin_user_id: int,
        admin_username: str,
        target_user_id: int,
        target_username: str,
        ip_address: Optional[str] = None,
    ):
        """Logs when an admin impersonates another user."""
        self.log_event(
            event_type=AuditEventType.ADMIN_IMPERSONATION,
            user_id=admin_user_id,
            username=admin_username,
            ip_address=ip_address,
            success=True,
            details={
                "target_user_id": target_user_id,
                "target_username": target_username,
            },
            severity="WARNING",  # Always WARNING - this is an important action
        )

    def api_key_created(
        self,
        user_id: int,
        username: str,
        key_id: int,
        exchange: str,
        ip_address: Optional[str] = None,
    ):
        """Logs API key creation."""
        self.log_event(
            event_type=AuditEventType.API_KEY_CREATED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=True,
            details={"key_id": key_id, "exchange": exchange},
        )

    def api_key_deleted(
        self, user_id: int, username: str, key_id: int, ip_address: Optional[str] = None
    ):
        """Logs API key deletion."""
        self.log_event(
            event_type=AuditEventType.API_KEY_DELETED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=True,
            details={"key_id": key_id},
        )

    def permission_denied(
        self,
        user_id: Optional[int],
        username: Optional[str],
        resource: str,
        action: str,
        ip_address: Optional[str] = None,
    ):
        """Logs access denied."""
        self.log_event(
            event_type=AuditEventType.PERMISSION_DENIED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=False,
            details={"resource": resource, "action": action},
            severity="WARNING",
        )

    def rate_limit_exceeded(
        self, ip_address: str, endpoint: str, user_id: Optional[int] = None
    ):
        """Logs rate limit exceeded."""
        self.log_event(
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            user_id=user_id,
            ip_address=ip_address,
            success=False,
            details={"endpoint": endpoint},
            severity="WARNING",
        )

    def api_key_tested(
        self,
        user_id: int,
        username: str,
        key_id: int,
        test_result: str,
        ip_address: Optional[str] = None,
    ):
        """Logs API key testing."""
        self.log_event(
            event_type=AuditEventType.API_KEY_TESTED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=(test_result == "valid"),
            details={"key_id": key_id, "result": test_result},
        )

    def api_key_status_changed(
        self,
        user_id: int,
        username: str,
        key_id: int,
        is_active: bool,
        ip_address: Optional[str] = None,
    ):
        """Logs API key activation/deactivation."""
        self.log_event(
            event_type=AuditEventType.API_KEY_STATUS_CHANGED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=True,
            details={"key_id": key_id, "is_active": is_active},
        )

    def api_key_decrypt_failed(
        self, user_id: int, username: str, key_id: int, ip_address: Optional[str] = None
    ):
        """Logs failed API key decryption — a possible sign of data tampering."""
        self.log_event(
            event_type=AuditEventType.API_KEY_DECRYPT_FAILED,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=False,
            details={"key_id": key_id},
            severity="CRITICAL",
        )


# Global instance for application use
audit_logger = AuditLogger()


def get_client_ip(request) -> str:
    """Extracts the real client IP from the request (accounts for proxies)."""
    # X-Forwarded-For can contain multiple IPs separated by a comma
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # X-Real-IP from Nginx
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback to direct IP
    if hasattr(request, "client") and request.client:
        return request.client.host

    return "unknown"


def get_user_agent(request) -> str:
    """Extracts User-Agent from the request."""
    return request.headers.get("User-Agent", "unknown")[:200]  # Limit the length
