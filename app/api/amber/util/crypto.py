"""Envelope encryption for OAuth refresh tokens.

Each token gets a fresh 256-bit data key (DEK). The token is sealed with AES-256-GCM under
the DEK, and the DEK is wrapped by a key-encryption key: Cloud KMS in prod, or a local AES
key in dev/test. Both layers bind `aad` (the owning user id), so a ciphertext copied onto
another user's row fails to decrypt.

Blob layout: version(1) | len(wrapped_dek)(2, big-endian) | wrapped_dek | nonce(12) | ciphertext
"""

import base64
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from amber.util.config import Settings

_VERSION = 1
_NONCE = 12


class KeyWrapper(Protocol):
    def wrap(self, dek: bytes, aad: bytes) -> tuple[bytes, str]: ...
    def unwrap(self, wrapped: bytes, aad: bytes) -> bytes: ...


class LocalKeyWrapper:
    """Dev/test only: wraps DEKs with a local AES-256-GCM key."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("local token key must be 32 bytes")
        self._aes = AESGCM(key)

    def wrap(self, dek: bytes, aad: bytes) -> tuple[bytes, str]:
        nonce = os.urandom(_NONCE)
        return nonce + self._aes.encrypt(nonce, dek, aad), "local"

    def unwrap(self, wrapped: bytes, aad: bytes) -> bytes:
        return self._aes.decrypt(wrapped[:_NONCE], wrapped[_NONCE:], aad)


class KmsKeyWrapper:
    """Wraps DEKs with a Cloud KMS symmetric key. The KEK never leaves KMS."""

    def __init__(self, key_name: str):
        from google.cloud import kms

        self._key_name = key_name
        self._client = kms.KeyManagementServiceClient()

    def wrap(self, dek: bytes, aad: bytes) -> tuple[bytes, str]:
        resp = self._client.encrypt(
            request={"name": self._key_name, "plaintext": dek, "additional_authenticated_data": aad}
        )
        return resp.ciphertext, resp.name  # resp.name is the key version that was used

    def unwrap(self, wrapped: bytes, aad: bytes) -> bytes:
        resp = self._client.decrypt(
            request={"name": self._key_name, "ciphertext": wrapped, "additional_authenticated_data": aad}
        )
        return resp.plaintext


class TokenCipher:
    def __init__(self, wrapper: KeyWrapper):
        self._wrapper = wrapper

    def encrypt(self, plaintext: str, aad: str) -> tuple[bytes, str]:
        """Returns (blob, key_version)."""
        aad_b = aad.encode()
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(_NONCE)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), aad_b)
        wrapped, key_version = self._wrapper.wrap(dek, aad_b)
        blob = bytes([_VERSION]) + len(wrapped).to_bytes(2, "big") + wrapped + nonce + ciphertext
        return blob, key_version

    def decrypt(self, blob: bytes, aad: str) -> str:
        if not blob or blob[0] != _VERSION:
            raise ValueError("unsupported token blob version")
        n = int.from_bytes(blob[1:3], "big")
        wrapped = blob[3 : 3 + n]
        nonce = blob[3 + n : 3 + n + _NONCE]
        ciphertext = blob[3 + n + _NONCE :]
        dek = self._wrapper.unwrap(wrapped, aad.encode())
        return AESGCM(dek).decrypt(nonce, ciphertext, aad.encode()).decode()


def build_token_cipher(settings: Settings) -> TokenCipher:
    if settings.token_kms_key:
        return TokenCipher(KmsKeyWrapper(settings.token_kms_key))
    if settings.local_token_key is not None and settings.env != "prod":
        key = base64.urlsafe_b64decode(settings.local_token_key.get_secret_value())
        return TokenCipher(LocalKeyWrapper(key))
    raise RuntimeError(
        "No token encryption key configured (AMBER_TOKEN_KMS_KEY or, outside prod, AMBER_LOCAL_TOKEN_KEY)"
    )
