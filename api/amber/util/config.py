"""Runtime configuration, read from AMBER_* environment variables (and .env outside prod)."""

import ipaddress
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env is only a dev convenience; get_settings() never reads it in prod.
    model_config = SettingsConfigDict(env_prefix="AMBER_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    # Where `python main.py` listens. In a container use AMBER_HOST=0.0.0.0 and the
    # platform's port (Cloud Run sets $PORT).
    host: str = "127.0.0.1"
    port: int = 8000

    # Origin the browser uses for both the web app and /api (same origin via the LB, or
    # the Next.js dev server's /api rewrite locally). OAuth redirects are built from it.
    public_base_url: str = "http://localhost:3000"

    # Google OAuth web client (must be the client configured for Firebase's Google provider).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")

    # Existing Firebase project. The web API key is only used server-side for signInWithIdp.
    firebase_project_id: str = ""
    firebase_web_api_key: SecretStr = SecretStr("")

    # Gemini API Key for LLM and embeddings
    gemini_api_key: SecretStr = SecretStr("")

    # Google service-account key file used by google.auth.default() (Firebase Admin, KMS).
    # Read from GOOGLE_APPLICATION_CREDENTIALS (no AMBER_ prefix), in the environment or .env.
    # A relative path is resolved against the api folder. Unset: use the ambient credentials
    # (e.g. the Cloud Run service account).
    google_application_credentials: str | None = Field(default=None, validation_alias="GOOGLE_APPLICATION_CREDENTIALS")

    # Fernet key that encrypts the short-lived OAuth state/PKCE cookie.
    state_cookie_key: SecretStr = SecretStr("")

    # Refresh-token envelope encryption: a Cloud KMS key in prod, or a local AES key in dev/test.
    token_kms_key: str | None = None  # projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>
    local_token_key: SecretStr | None = None  # urlsafe base64, 32 bytes. Never in prod.

    # libpq DSN for psycopg2, e.g. postgresql://amber_app@127.0.0.1:5432/amber_dev
    # In GCP the API reaches Cloud SQL through the Cloud SQL Auth Proxy sidecar on 127.0.0.1
    # (private IP, --auto-iam-authn), so the DSN carries no password.
    database_dsn: SecretStr = SecretStr("")

    # Proxies allowed to report the client IP via X-Forwarded-For (the GCP load balancer's
    # ranges, the Next.js dev server). Comma-separated CIDRs. Empty: trust no header.
    trusted_proxies: str = ""

    # How long a user's "revoked before" timestamp from Firebase is cached per instance.
    # Signing out everywhere takes effect on other instances within this window.
    revocation_cache_seconds: int = 60

    cookie_secure: bool | None = None
    session_days: int = 5
    bootstrap_admin_emails: str = ""  # comma-separated

    # Agent model settings
    agent_model_name: str = "gemini-2.5-flash"
    litellm_base_url: str = ""
    litellm_api_key: SecretStr = SecretStr("")

    @property
    def public_origin(self) -> str:
        parts = urlsplit(self.public_base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_origin}/api/auth/google/callback"

    @property
    def bootstrap_admins(self) -> set[str]:
        return {e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()}

    @property
    def trusted_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(c.strip()) for c in self.trusted_proxies.split(",") if c.strip()]

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.cookie_secure is None:
            self.cookie_secure = self.public_base_url.startswith("https://")
        self.trusted_networks  # noqa: B018 (fail fast on a malformed CIDR)
        if self.env != "test":
            # Fail at startup, not at the first sign-in.
            required = {
                "AMBER_GOOGLE_OAUTH_CLIENT_ID": self.google_oauth_client_id,
                "AMBER_GOOGLE_OAUTH_CLIENT_SECRET": self.google_oauth_client_secret.get_secret_value(),
                "AMBER_FIREBASE_PROJECT_ID": self.firebase_project_id,
                "AMBER_FIREBASE_WEB_API_KEY": self.firebase_web_api_key.get_secret_value(),
                "AMBER_STATE_COOKIE_KEY": self.state_cookie_key.get_secret_value(),
                "AMBER_DATABASE_DSN": self.database_dsn.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Missing required settings: {', '.join(missing)}")
            try:
                Fernet(self.state_cookie_key.get_secret_value())
            except ValueError as exc:
                raise ValueError("AMBER_STATE_COOKIE_KEY must be a Fernet key") from exc
            if not self.token_kms_key and self.local_token_key is None:
                raise ValueError("Set AMBER_TOKEN_KMS_KEY (or, outside prod, AMBER_LOCAL_TOKEN_KEY)")
        if self.env == "prod":
            if not self.token_kms_key:
                raise ValueError("AMBER_TOKEN_KMS_KEY is required in prod")
            if self.local_token_key is not None:
                raise ValueError("AMBER_LOCAL_TOKEN_KEY must not be set in prod")
            if not self.cookie_secure:
                raise ValueError("AMBER_COOKIE_SECURE must be true in prod")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("AMBER_PUBLIC_BASE_URL must be https in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    env_file = None if os.environ.get("AMBER_ENV") == "prod" else ".env"
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
