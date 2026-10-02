import base64
import os

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from amber.util import config
from amber.util.config import Settings
from amber.util.crypto import LocalKeyWrapper, TokenCipher
from amber.util.security import cookie_names


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher(LocalKeyWrapper(os.urandom(32)))


def test_roundtrip(cipher):
    blob, version = cipher.encrypt("refresh-token", aad="user-1")
    assert version == "local" and b"refresh-token" not in blob
    assert cipher.decrypt(blob, aad="user-1") == "refresh-token"


def test_each_encryption_uses_a_fresh_data_key(cipher):
    a, _ = cipher.encrypt("same", aad="u")
    b, _ = cipher.encrypt("same", aad="u")
    assert a != b


def test_ciphertext_is_bound_to_its_user(cipher):
    blob, _ = cipher.encrypt("refresh-token", aad="user-1")
    with pytest.raises(Exception):  # noqa: B017 (cryptography raises InvalidTag)
        cipher.decrypt(blob, aad="user-2")


def test_tampering_is_detected(cipher):
    blob, _ = cipher.encrypt("refresh-token", aad="user-1")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(Exception):  # noqa: B017
        cipher.decrypt(tampered, aad="user-1")


def test_unknown_blob_version_is_rejected(cipher):
    with pytest.raises(ValueError):
        cipher.decrypt(b"\x09rest", aad="u")


REQUIRED = {
    "google_oauth_client_id": "cid",
    "google_oauth_client_secret": "secret",
    "firebase_project_id": "p",
    "firebase_web_api_key": "k",
    "state_cookie_key": Fernet.generate_key().decode(),
    "database_dsn": "postgresql://amber_app@127.0.0.1:5432/amber",
}


def _prod(**kw) -> Settings:
    base = REQUIRED | {
        "env": "prod",
        "public_base_url": "https://amber.example.com",
        "token_kms_key": "projects/p/locations/l/keyRings/r/cryptoKeys/k",
    }
    return Settings(**(base | kw))


def test_prod_settings_are_valid():
    assert _prod().env == "prod"


@pytest.mark.parametrize(
    "override",
    [
        {"token_kms_key": None},
        {"local_token_key": base64.urlsafe_b64encode(os.urandom(32)).decode()},
        {"cookie_secure": False},
        {"public_base_url": "http://amber.example.com"},
        {"google_oauth_client_secret": ""},
        {"firebase_web_api_key": ""},
        {"state_cookie_key": "not-a-fernet-key"},
        {"database_dsn": ""},
        {"trusted_proxies": "not-a-cidr"},
    ],
)
def test_prod_rejects_unsafe_settings(override):
    with pytest.raises(ValidationError):
        _prod(**override)


def test_https_uses_host_prefix():
    s = Settings(env="test", public_base_url="https://amber.example.com")
    assert cookie_names(s) == ("__Host-amber_session", "__Host-amber_csrf", "__Host-amber_oauth")


@pytest.mark.parametrize("kw", [{"public_base_url": "http://localhost:3000"}, {"cookie_secure": False}])
def test_plain_http_dev_drops_host_prefix(kw):
    # Browsers reject __Host- cookies over http, even on localhost.
    s = Settings(env="test", **({"public_base_url": "https://amber.example.com"} | kw))
    assert cookie_names(s) == ("amber_session", "amber_csrf", "amber_oauth")


def test_dev_also_requires_secrets_at_startup():
    with pytest.raises(ValidationError, match="AMBER_GOOGLE_OAUTH_CLIENT_ID"):
        Settings(env="dev", local_token_key=base64.urlsafe_b64encode(os.urandom(32)).decode())


def test_prod_ignores_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AMBER_COOKIE_SECURE=false\n")
    monkeypatch.chdir(tmp_path)
    for key, value in (
        REQUIRED
        | {
            "env": "prod",
            "public_base_url": "https://a.example",
            "token_kms_key": "projects/p/locations/l/keyRings/r/cryptoKeys/k",
        }
    ).items():
        monkeypatch.setenv(f"AMBER_{key.upper()}", value)
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().cookie_secure is True  # the stray .env was not read
    finally:
        config.get_settings.cache_clear()
