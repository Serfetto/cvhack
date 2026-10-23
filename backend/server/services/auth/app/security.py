"""Ключи RS256, выпуск токенов, хэши паролей (argon2)."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


class KeyPair:
    """Приватный ключ хранится в файле (volume), чтобы токены переживали рестарт сервиса."""

    def __init__(self, path: str):
        p = Path(path)
        if p.exists():
            self.private = serialization.load_pem_private_key(p.read_bytes(), password=None)
        else:
            self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(
                self.private.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                )
            )
        self.public = self.private.public_key()
        pem = self.public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.kid = hashlib.sha256(pem).hexdigest()[:16]

    def jwks(self) -> dict:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.public))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}


def issue_access_token(keys: KeyPair, user, issuer: str, audience: str, ttl_s: int) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "username": user.username,
        "name": user.full_name,
        "role": user.role,
        "areas": list(user.area_ids or []),
        "type": "access",
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(claims, keys.private, algorithm="RS256", headers={"kid": keys.kid})


def new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
