from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import routes
from backend.auth.sms import get_sms_provider
from backend.database import (
    Base,
    PasswordResetToken,
    User,
    UserLoginActivity,
    _ensure_password_reset_columns,
    get_db,
)
from backend.main import app


class CapturingSmsProvider:
    def __init__(self) -> None:
        self.codes: list[tuple[str, str]] = []

    def send_otp(self, phone_number: str, otp: str) -> None:
        self.codes.append((phone_number, otp))


@pytest.fixture
def isolated_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, sessionmaker, CapturingSmsProvider]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    provider = CapturingSmsProvider()

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_sms_provider] = lambda: provider
    monkeypatch.setattr(routes.config, "DEBUG", True)
    try:
        yield TestClient(app), test_session, provider
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_sms_provider, None)
        engine.dispose()


def register_user(client: TestClient, email: str = "phase1@example.test") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Phase One",
            "username": "phase-one",
            "email": email,
            "mobile_number": "15551234567",
            "password": "InitialPass!123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def request_otp(client: TestClient, email: str = "phase1@example.test") -> str:
    response = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    assert "reset_token" not in response.json()
    return response.json()["message"]


def test_login_history_phone_mask_and_verified_one_time_password_reset(isolated_api):
    client, test_session, provider = isolated_api
    registered = register_user(client)

    assert registered["user"]["mobile_number"] == "***4567"
    assert "15551234567" not in str(registered)
    auth_header = {"Authorization": f"Bearer {registered['token']}"}
    profile = client.get("/api/v1/users/me", headers=auth_header)
    assert profile.json()["mobile_number"] == "***4567"
    profile_update = client.put(
        "/api/v1/users/me",
        json={"full_name": "Phase One Updated", "email": "phase1@example.test"},
        headers=auth_header,
    )
    assert profile_update.json()["mobile_number"] == "***4567"

    login = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "phase-one", "password": "InitialPass!123"},
    )
    assert login.status_code == 200, login.text
    user_id = login.json()["user"]["id"]
    session = test_session()
    history = session.query(UserLoginActivity).filter_by(user_id=user_id, success=True).all()
    assert len(history) == 2
    assert all(item.login_at is not None for item in history)
    assert all(item.user_agent is None for item in history)
    stored_user = session.query(User).filter_by(id=user_id).one()
    assert stored_user.last_login_at is not None
    assert stored_user.mobile_number == "15551234567"
    session.close()

    session = test_session()
    session.add(
        PasswordResetToken(
            user_id=user_id,
            token=routes._hash_token("legacy-unverified-token"),
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
    )
    session.commit()
    session.close()
    unverified_reset = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "legacy-unverified-token",
            "new_password": "UpdatedPass!456",
            "confirm_password": "UpdatedPass!456",
        },
    )
    assert unverified_reset.status_code == 404

    forgot = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "phase1@example.test"},
    )
    assert forgot.status_code == 200
    assert "No SMS was sent" in forgot.json()["message"]
    assert len(provider.codes) == 1
    phone_number, otp = provider.codes[0]
    assert phone_number == "15551234567"
    assert otp not in forgot.text
    assert phone_number not in forgot.text

    verified = client.post(
        "/api/v1/auth/verify-reset-otp",
        json={"email": "phase1@example.test", "otp": otp},
    )
    assert verified.status_code == 200, verified.text
    reset_token = verified.json()["reset_token"]
    assert otp not in verified.text
    assert phone_number not in verified.text

    reset_payload = {
        "token": reset_token,
        "new_password": "UpdatedPass!456",
        "confirm_password": "UpdatedPass!456",
    }
    reset = client.post("/api/v1/auth/reset-password", json=reset_payload)
    assert reset.status_code == 200, reset.text
    session = test_session()
    assert session.query(User).filter_by(id=user_id).one().password_hash.startswith("pbkdf2_sha256$")
    session.close()
    assert client.post("/api/v1/auth/reset-password", json=reset_payload).status_code == 400
    assert client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "phase-one", "password": "InitialPass!123"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "phase-one", "password": "UpdatedPass!456"},
    ).status_code == 200


def test_reset_otp_attempt_limit_and_expiry(isolated_api):
    client, test_session, provider = isolated_api
    register_user(client)
    request_otp(client)
    otp = provider.codes[-1][1]

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/verify-reset-otp",
            json={"email": "phase1@example.test", "otp": "000000" if otp != "000000" else "000001"},
        )
        assert response.status_code == 400

    locked = client.post(
        "/api/v1/auth/verify-reset-otp",
        json={"email": "phase1@example.test", "otp": otp},
    )
    assert locked.status_code == 400
    entry = test_session().query(PasswordResetToken).order_by(PasswordResetToken.id.desc()).first()
    assert entry.attempt_count == 5
    assert entry.used_at is not None

    request_otp(client)
    next_otp = provider.codes[-1][1]
    session = test_session()
    entry = session.query(PasswordResetToken).order_by(PasswordResetToken.id.desc()).first()
    entry.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()
    session.close()
    expired = client.post(
        "/api/v1/auth/verify-reset-otp",
        json={"email": "phase1@example.test", "otp": next_otp},
    )
    assert expired.status_code == 400


def test_forgot_password_response_does_not_disclose_account_existence(isolated_api):
    client, _, provider = isolated_api
    register_user(client)
    existing = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "phase1@example.test"},
    )
    missing = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "missing@example.test"},
    )
    assert existing.status_code == missing.status_code == 200
    assert existing.json() == missing.json()
    assert len(provider.codes) == 1
    assert provider.codes[0][1] not in existing.text
    assert provider.codes[0][0] not in existing.text


def test_mock_otp_is_disabled_outside_development(isolated_api, monkeypatch):
    client, test_session, provider = isolated_api
    register_user(client)
    monkeypatch.setattr(routes.config, "DEBUG", False)

    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "phase1@example.test"},
    )
    assert response.status_code == 200
    assert "provider is configured" in response.json()["message"]
    assert provider.codes == []
    session = test_session()
    assert session.query(PasswordResetToken).count() == 0
    session.close()


def test_auth_validation_errors_do_not_echo_phone_password_or_otp(isolated_api):
    client, _, _ = isolated_api
    invalid_registration = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Bad",
            "username": "bad-user",
            "email": "bad@example.test",
            "mobile_number": "5551234",
            "password": "Secret1",
        },
    )
    assert invalid_registration.status_code == 422
    assert "5551234" not in invalid_registration.text
    assert "Secret1" not in invalid_registration.text

    invalid_otp = client.post(
        "/api/v1/auth/verify-reset-otp",
        json={"email": "bad@example.test", "otp": "1234567"},
    )
    assert invalid_otp.status_code == 422
    assert "1234567" not in invalid_otp.text


def test_password_reset_schema_upgrade_is_additive_and_preserves_rows():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE password_reset_tokens ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, token VARCHAR(255) NOT NULL UNIQUE, "
                "created_at DATETIME, expires_at DATETIME NOT NULL, used_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO password_reset_tokens "
                "(id, user_id, token, expires_at) VALUES (1, 7, 'existing-hash', '2030-01-01')"
            )
        )

    _ensure_password_reset_columns(engine)
    _ensure_password_reset_columns(engine)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, user_id, token FROM password_reset_tokens WHERE id = 1")
        ).one()
    columns = {column["name"] for column in inspect(engine).get_columns("password_reset_tokens")}
    assert row == (1, 7, "existing-hash")
    assert {"otp_hash", "attempt_count", "verified_at", "reset_token_hash"} <= columns
    engine.dispose()
