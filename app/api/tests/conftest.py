"""Test harness. These tests never connect to a database or call Google or Firebase, so
they're safe to run anywhere, at any time."""

import base64
import os
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from amber.main import create_app
from amber.util.config import Settings
from amber.util.google_oauth import GoogleOAuthClient

BASE_URL = "https://amber.test"


class NoFirebase:
    """Stands in for Firebase so building the app doesn't need cloud credentials."""


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        public_base_url=BASE_URL,
        google_oauth_client_id="test-client.apps.googleusercontent.com",
        google_oauth_client_secret="test-secret",
        state_cookie_key=Fernet.generate_key().decode(),
        local_token_key=base64.urlsafe_b64encode(os.urandom(32)).decode(),
    )


@pytest.fixture
def client(settings) -> Iterator[TestClient]:
    # No database: only endpoints that don't touch Postgres are exercised here.
    app = create_app(
        settings,
        database=None,
        google=GoogleOAuthClient(settings, httpx.Client()),
        firebase=NoFirebase(),
    )
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


def start(client: TestClient, query: str = "") -> tuple[str, dict]:
    resp = client.get(f"/api/auth/google/start{query}", follow_redirects=False)
    assert resp.status_code == 303
    params = {k: v[0] for k, v in parse_qs(urlsplit(resp.headers["location"]).query).items()}
    return resp.headers["location"], params
