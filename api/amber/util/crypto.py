"""Envelope encryption for OAuth refresh tokens.

Each token gets a fresh 256-bit data key (DEK). The token is sealed with AES-256-GCM under
the DEK, and the DEK is wrapped by a key-encryption key: Cloud KMS in prod, or a local AES
key in dev/test. Both layers bind `aad` (the owning user id), so a ciphertext copied onto
another user's row fails to decrypt.

Blob layout: version(1) | len(wrapped_dek)(2, big-endian) | wrapped_dek | nonce(12) | ciphertext
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from amber.util.config import Settings

_VERSION = 1
_NONCE = 12


def _local_key(settings: Settings) -> bytes:
    if settings.local_token_key is None or settings.env == "prod":
        raise RuntimeError("No token encryption key (AMBER_TOKEN_KMS_KEY, or outside prod AMBER_LOCAL_TOKEN_KEY)")
    key = base64.urlsafe_b64decode(settings.local_token_key.get_secret_value())
    if len(key) != 32:
        raise ValueError("AMBER_LOCAL_TOKEN_KEY must be 32 bytes")
    return key


def _wrap_key(settings: Settings, dek: bytes, aad: bytes) -> tuple[bytes, str]:
    """Wraps the data key; returns (wrapped, key_version)."""
    if settings.token_kms_key:
        from google.cloud import kms

        resp = kms.KeyManagementServiceClient().encrypt(
            request={"name": settings.token_kms_key, "plaintext": dek, "additional_authenticated_data": aad}
        )
        return resp.ciphertext, resp.name  # resp.name is the KMS key version that was used
    nonce = os.urandom(_NONCE)
    return nonce + AESGCM(_local_key(settings)).encrypt(nonce, dek, aad), "local"


def _unwrap_key(settings: Settings, wrapped: bytes, aad: bytes) -> bytes:
    if settings.token_kms_key:
        from google.cloud import kms

        resp = kms.KeyManagementServiceClient().decrypt(
            request={"name": settings.token_kms_key, "ciphertext": wrapped, "additional_authenticated_data": aad}
        )
        return resp.plaintext
    return AESGCM(_local_key(settings)).decrypt(wrapped[:_NONCE], wrapped[_NONCE:], aad)


def encrypt_token(settings: Settings, plaintext: str, aad: str) -> tuple[bytes, str]:
    """Returns (blob, key_version)."""
    aad_b = aad.encode()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), aad_b)
    wrapped, key_version = _wrap_key(settings, dek, aad_b)
    blob = bytes([_VERSION]) + len(wrapped).to_bytes(2, "big") + wrapped + nonce + ciphertext
    return blob, key_version


def decrypt_token(settings: Settings, blob: bytes, aad: str) -> str:
    if not blob or blob[0] != _VERSION:
        raise ValueError("unsupported token blob version")
    n = int.from_bytes(blob[1:3], "big")
    wrapped = blob[3 : 3 + n]
    nonce = blob[3 + n : 3 + n + _NONCE]
    ciphertext = blob[3 + n + _NONCE :]
    dek = _unwrap_key(settings, wrapped, aad.encode())
    return AESGCM(dek).decrypt(nonce, ciphertext, aad.encode()).decode()
