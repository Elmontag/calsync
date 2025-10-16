"""Utilities for protecting sensitive account settings."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from copy import deepcopy
from functools import lru_cache
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

from .models import AccountType

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"password", "client_secret", "token", "refresh_token"}
_ENCRYPTED_PREFIX = "enc:"


class SecretEncryptionError(RuntimeError):
    """Raised when a secret cannot be encrypted or decrypted safely."""


def _derive_fernet_key() -> bytes:
    """Build a Fernet compatible key from the configured application secret."""

    secret = os.getenv("CALSYNC_SECRET_KEY")
    if not secret:
        raise SecretEncryptionError(
            "CALSYNC_SECRET_KEY ist nicht gesetzt. Verschlüsselung kann nicht durchgeführt werden."
        )

    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_cipher() -> Fernet:
    """Return a cached Fernet instance for consistent encryption."""

    key = _derive_fernet_key()
    return Fernet(key)


def _encrypt_value(value: str) -> str:
    if value.startswith(_ENCRYPTED_PREFIX):
        return value
    cipher = _get_cipher()
    token = cipher.encrypt(value.encode("utf-8"))
    return f"{_ENCRYPTED_PREFIX}{token.decode('utf-8')}"


def _decrypt_value(value: str) -> str:
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value
    token = value[len(_ENCRYPTED_PREFIX) :].encode("utf-8")
    cipher = _get_cipher()
    try:
        decrypted = cipher.decrypt(token)
        return decrypted.decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - depends on stored data integrity
        logger.error("Entschlüsselung des Geheimnisses fehlgeschlagen: %s", exc)
        raise SecretEncryptionError("Gespeichertes Geheimnis konnte nicht entschlüsselt werden.") from exc


def _transform_sensitive_values(
    payload: dict[str, Any], transformer: Callable[[str], str]
) -> dict[str, Any]:
    transformed = deepcopy(payload)
    for key, value in list(transformed.items()):
        if isinstance(value, dict):
            transformed[key] = _transform_sensitive_values(value, transformer)
        elif isinstance(value, list):
            transformed[key] = [
                _transform_sensitive_values(item, transformer)
                if isinstance(item, dict)
                else _process_scalar(key, item, transformer)
                for item in value
            ]
        else:
            transformed[key] = _process_scalar(key, value, transformer)
    return transformed


def _process_scalar(key: str, value: Any, transformer: Callable[[str], str]) -> Any:
    if key in _SENSITIVE_KEYS and isinstance(value, str) and value:
        return transformer(value)
    return value


def encrypt_account_settings(
    account_type: AccountType, settings: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of ``settings`` with sensitive values encrypted."""

    if not isinstance(settings, dict):
        return settings
    return _transform_sensitive_values(settings, _encrypt_value)


def decrypt_account_settings(
    account_type: AccountType, settings: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of ``settings`` with encrypted values restored."""

    if not isinstance(settings, dict):
        return settings
    return _transform_sensitive_values(settings, _decrypt_value)

