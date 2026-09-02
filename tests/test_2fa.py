# tests/test_2fa.py
import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import models, totp_service
from api.rate_limiter import limiter


@pytest.fixture(autouse=True)
def disable_rate_limiter():
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


class TestTotpServiceUnit:
    """Unit tests for the totp_service functions."""

    def test_secret_generation(self):
        secret = totp_service.generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) == 32

    def test_provisioning_uri(self):
        secret = totp_service.generate_totp_secret()
        uri = totp_service.get_totp_uri("trader_bob", secret, issuer="DepthSight")
        assert uri.startswith("otpauth://totp/DepthSight:trader_bob?")
        assert f"secret={secret}" in uri
        assert "issuer=DepthSight" in uri

    def test_qr_code_generation(self):
        secret = totp_service.generate_totp_secret()
        uri = totp_service.get_totp_uri("alice", secret)
        qr_b64 = totp_service.generate_qr_code_base64(uri)
        assert qr_b64.startswith("data:image/png;base64,")
        assert len(qr_b64) > 100

    def test_secret_encryption_roundtrip(self):
        secret = totp_service.generate_totp_secret()
        encrypted = totp_service.encrypt_totp_secret(secret)
        assert encrypted != secret
        decrypted = totp_service.decrypt_totp_secret(encrypted)
        assert decrypted == secret

    def test_verify_totp_code_success_and_replay(self):
        secret = totp_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # Valid initial code
        is_valid, step = totp_service.verify_totp_code(secret, code)
        assert is_valid is True
        assert isinstance(step, int)

        # Replay attempt with same or older step must be rejected
        replay_valid, _ = totp_service.verify_totp_code(secret, code, last_step=step)
        assert replay_valid is False

        # Future step allowed
        future_valid, new_step = totp_service.verify_totp_code(
            secret, code, last_step=step - 1
        )
        assert future_valid is True
        assert new_step == step

    def test_verify_totp_code_invalid(self):
        secret = totp_service.generate_totp_secret()
        is_valid, _ = totp_service.verify_totp_code(secret, "000000")
        assert is_valid is False

        # Invalid formats
        assert totp_service.verify_totp_code(secret, "")[0] is False
        assert totp_service.verify_totp_code(secret, "abc")[0] is False
        assert totp_service.verify_totp_code(secret, "12345")[0] is False

    def test_backup_codes_generation_and_consumption(self):
        plain_codes, hashed_codes = totp_service.generate_backup_codes(count=8)
        assert len(plain_codes) == 8
        assert len(hashed_codes) == 8

        # Verify and consume the first code
        first_code = plain_codes[0]
        valid, remaining = totp_service.verify_and_consume_backup_code(
            first_code, hashed_codes
        )
        assert valid is True
        assert len(remaining) == 7

        # Consuming the same code again should fail
        second_attempt, remaining2 = totp_service.verify_and_consume_backup_code(
            first_code, remaining
        )
        assert second_attempt is False
        assert len(remaining2) == 7

        # Invalid code
        invalid_valid, _ = totp_service.verify_and_consume_backup_code(
            "INVALID1", remaining
        )
        assert invalid_valid is False


@pytest.mark.asyncio
class TestTwoFactorAuthAPI:
    """API integration tests for 2FA setup, login verification, backup codes, and disable."""

    async def test_get_totp_status_initial(
        self, authenticated_client: AsyncClient, pro_user: models.User
    ):
        response = await authenticated_client.get("/api/v1/auth/2fa/status")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["isTotpEnabled"] is False
        assert data["remainingBackupCodesCount"] == 0

    async def test_totp_setup_flow(
        self, authenticated_client: AsyncClient, pro_user: models.User
    ):
        response = await authenticated_client.post("/api/v1/auth/2fa/setup")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "secret" in data
        assert "qrCode" in data
        assert data["qrCode"].startswith("data:image/png;base64,")
        assert "manualEntryKey" in data

    async def test_totp_confirm_invalid_code(
        self, authenticated_client: AsyncClient, pro_user: models.User
    ):
        setup_resp = await authenticated_client.post("/api/v1/auth/2fa/setup")
        secret = setup_resp.json()["data"]["secret"]

        confirm_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/confirm",
            json={"secret": secret, "code": "000000"},
        )
        assert confirm_resp.status_code == 400
        assert "Invalid verification code" in confirm_resp.json()["detail"]

    async def test_totp_confirm_success_and_full_login_flow(
        self,
        authenticated_client: AsyncClient,
        test_client: AsyncClient,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        # 1. Setup 2FA
        setup_resp = await authenticated_client.post("/api/v1/auth/2fa/setup")
        secret = setup_resp.json()["data"]["secret"]

        # 2. Confirm with valid code
        totp = pyotp.TOTP(secret)
        current_code = totp.now()

        confirm_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/confirm",
            json={"secret": secret, "code": current_code},
        )
        assert confirm_resp.status_code == 200
        confirm_data = confirm_resp.json()["data"]
        assert confirm_data["success"] is True
        backup_codes = confirm_data["backupCodes"]
        assert len(backup_codes) == 8

        # Verify DB state
        await db_session.refresh(pro_user)
        assert pro_user.is_totp_enabled is True
        assert pro_user.totp_secret is not None
        assert len(pro_user.totp_backup_codes) == 8

        # 3. Status endpoint reflects enablement
        status_resp = await authenticated_client.get("/api/v1/auth/2fa/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["data"]["isTotpEnabled"] is True
        assert status_resp.json()["data"]["remainingBackupCodesCount"] == 8

        # 4. Attempting duplicate setup returns 400
        dup_setup = await authenticated_client.post("/api/v1/auth/2fa/setup")
        assert dup_setup.status_code == 400

        # 5. Login attempt with password now returns requires_2fa: True and temp_token
        login_resp = await test_client.post(
            "/api/v1/token",
            data={"username": pro_user.username, "password": "password"},
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        assert login_data["requires_2fa"] is True
        assert "temp_token" in login_data
        temp_token = login_data["temp_token"]
        assert login_data["token"] is None

        # 6. Verify temp token cannot be used as Bearer token on general endpoints
        unauth_resp = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {temp_token}"},
        )
        assert unauth_resp.status_code == 401

        # 7. Complete 2FA login with wrong code
        bad_verify = await test_client.post(
            "/api/v1/auth/2fa/verify-login",
            json={"tempToken": temp_token, "code": "999999"},
        )
        assert bad_verify.status_code == 400

        # 8. Complete 2FA login with valid code or backup code
        backup_code = backup_codes[0]
        backup_verify = await test_client.post(
            "/api/v1/auth/2fa/verify-login",
            json={"tempToken": temp_token, "code": backup_code},
        )
        assert backup_verify.status_code == 200
        auth_result = backup_verify.json()
        assert auth_result["token"]["access_token"] is not None
        assert auth_result["user"]["username"] == pro_user.username

    async def test_login_with_backup_code_consumes_code(
        self,
        authenticated_client: AsyncClient,
        test_client: AsyncClient,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        # Setup and confirm
        setup_resp = await authenticated_client.post("/api/v1/auth/2fa/setup")
        secret = setup_resp.json()["data"]["secret"]
        totp = pyotp.TOTP(secret)
        confirm_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/confirm",
            json={"secret": secret, "code": totp.now()},
        )
        backup_codes = confirm_resp.json()["data"]["backupCodes"]
        used_backup_code = backup_codes[0]

        # Login to get temp token
        login_resp = await test_client.post(
            "/api/v1/token",
            data={"username": pro_user.username, "password": "password"},
        )
        temp_token = login_resp.json()["temp_token"]

        # Use backup code
        verify_resp = await test_client.post(
            "/api/v1/auth/2fa/verify-login",
            json={"tempToken": temp_token, "code": used_backup_code},
        )
        assert verify_resp.status_code == 200

        # Verify backup code count decreased
        await db_session.refresh(pro_user)
        assert len(pro_user.totp_backup_codes) == 7

        # Re-login to get another temp token
        login_resp2 = await test_client.post(
            "/api/v1/token",
            data={"username": pro_user.username, "password": "password"},
        )
        temp_token2 = login_resp2.json()["temp_token"]

        # Trying the same backup code again must fail
        reuse_resp = await test_client.post(
            "/api/v1/auth/2fa/verify-login",
            json={"tempToken": temp_token2, "code": used_backup_code},
        )
        assert reuse_resp.status_code == 400

    async def test_regenerate_backup_codes(
        self,
        authenticated_client: AsyncClient,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        # Setup and confirm
        setup_resp = await authenticated_client.post("/api/v1/auth/2fa/setup")
        secret = setup_resp.json()["data"]["secret"]
        totp = pyotp.TOTP(secret)
        confirm_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/confirm",
            json={"secret": secret, "code": totp.now()},
        )
        initial_codes = confirm_resp.json()["data"]["backupCodes"]

        # Advance to next time step to avoid replay detection
        import time

        future_code = totp.at(time.time() + 35)
        regen_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/regenerate-backup-codes",
            json={"code": future_code},
        )
        assert regen_resp.status_code == 200
        new_codes = regen_resp.json()["data"]["backupCodes"]
        assert len(new_codes) == 8
        assert new_codes != initial_codes

    async def test_disable_2fa(
        self,
        authenticated_client: AsyncClient,
        test_client: AsyncClient,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        # Setup and confirm
        setup_resp = await authenticated_client.post("/api/v1/auth/2fa/setup")
        secret = setup_resp.json()["data"]["secret"]
        totp = pyotp.TOTP(secret)
        await authenticated_client.post(
            "/api/v1/auth/2fa/confirm",
            json={"secret": secret, "code": totp.now()},
        )

        # Disable with password
        disable_resp = await authenticated_client.post(
            "/api/v1/auth/2fa/disable",
            json={"code": "", "password": "password"},
        )
        assert disable_resp.status_code == 200

        await db_session.refresh(pro_user)
        assert pro_user.is_totp_enabled is False
        assert pro_user.totp_secret is None
        assert pro_user.totp_backup_codes is None

        # Subsequent login should NOT require 2FA
        login_resp = await test_client.post(
            "/api/v1/token",
            data={"username": pro_user.username, "password": "password"},
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["requires_2fa"] is False
        assert login_resp.json()["token"]["access_token"] is not None
