import base64
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

settings = get_settings()
_hasher = PasswordHasher(time_cost=1, memory_cost=1024) if settings.env == "test" else PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(48)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_access_token(user_id: UUID, role: str, sid: UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": str(sid),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def _key() -> bytes:
    raw = settings.provider_key_encryption_key.encode()
    if len(raw) == 32:
        return raw
    return base64.b64decode(raw)


def encrypt_secret(plaintext: str) -> str:
    """AES-GCM encryption for provider API keys. Returns base64(nonce || ciphertext)."""
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)).decode()


def decrypt_secret(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
