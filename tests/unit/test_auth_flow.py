from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth.sms import get_sms_provider
from backend.database import Base, get_db
from backend.main import app


class CapturingSmsProvider:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def send_otp(self, phone_number: str, otp: str) -> None:
        self.codes.append(otp)


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, CapturingSmsProvider]]:
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
    monkeypatch.setattr("backend.api.routes.config.DEBUG", True)
    try:
        yield TestClient(app), provider
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_sms_provider, None)
        engine.dispose()


def test_register_login_profile_and_logout_flow(auth_client):
    client, _ = auth_client
    register = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Aisha Sharma",
            "username": "aisha",
            "email": "aisha@example.com",
            "mobile_number": "9876543210",
            "password": "StrongPass!123",
        },
    )
    assert register.status_code == 201, register.text

    login = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "aisha", "password": "StrongPass!123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    profile = client.get("/api/v1/users/me", headers=auth_header)
    assert profile.status_code == 200, profile.text
    assert profile.json()["email"] == "aisha@example.com"
    assert profile.json()["mobile_number"] == "***3210"

    updated = client.put(
        "/api/v1/users/me",
        json={"full_name": "Aisha S.", "mobile_number": "9876543211"},
        headers=auth_header,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Aisha S."
    assert updated.json()["mobile_number"] == "***3211"

    history = client.get("/api/v1/users/login-history", headers=auth_header)
    assert history.status_code == 200, history.text
    assert len(history.json()["items"]) >= 1

    logout = client.post("/api/v1/auth/logout", headers=auth_header)
    assert logout.status_code == 200, logout.text
    protected = client.get("/api/v1/users/me", headers=auth_header)
    assert protected.status_code == 401, protected.text


def test_forgot_reset_and_change_password_flow(auth_client):
    client, provider = auth_client
    register = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Rohit Kumar",
            "username": "rohit",
            "email": "rohit@example.com",
            "mobile_number": "9988776655",
            "password": "StrongPass!123",
        },
    )
    assert register.status_code == 201, register.text

    forgot = client.post("/api/v1/auth/forgot-password", json={"email": "rohit@example.com"})
    assert forgot.status_code == 200, forgot.text
    otp = provider.codes[0]
    assert otp not in forgot.text

    verification = client.post(
        "/api/v1/auth/verify-reset-otp",
        json={"email": "rohit@example.com", "otp": otp},
    )
    assert verification.status_code == 200, verification.text
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": verification.json()["reset_token"],
            "new_password": "NewStrongPass!456",
            "confirm_password": "NewStrongPass!456",
        },
    )
    assert reset.status_code == 200, reset.text

    login = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "rohit@example.com", "password": "NewStrongPass!456"},
    )
    assert login.status_code == 200, login.text
    auth_header = {"Authorization": f"Bearer {login.json()['token']}"}
    change = client.post(
        "/api/v1/users/change-password",
        json={
            "current_password": "NewStrongPass!456",
            "new_password": "ChangePass!789",
            "confirm_password": "ChangePass!789",
        },
        headers=auth_header,
    )
    assert change.status_code == 200, change.text


def test_unauthorized_user_routes_are_rejected(auth_client):
    client, _ = auth_client
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401, response.text
