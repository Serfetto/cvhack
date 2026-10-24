"""Проверка JWT (RS256) во всех сервисах. Публичный ключ берётся из JWKS auth-service.

Токен ищется в заголовке `Authorization: Bearer …`, а если его нет — в параметре `?access_token=`
(нужно для <img src>, <video src> и WebSocket, где заголовок не передать).
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from common.messages import Role

ALL_ROLES = tuple(Role)


class CurrentUser(BaseModel):
    id: int
    username: str
    role: Role
    full_name: str = ""
    area_ids: list[int] = []

    def has_area(self, area_id: int | None) -> bool:
        """Мастер видит только свои участки; у остальных ролей ограничения по участкам нет."""
        if self.role != Role.MASTER or not self.area_ids:
            return True
        return area_id in self.area_ids


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_url: str | None = None, public_key=None):
        self.issuer = issuer
        self.audience = audience
        self.public_key = public_key
        self.jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5) if jwks_url and public_key is None else None

    def verify(self, token: str) -> CurrentUser:
        try:
            key = self.public_key if self.public_key is not None else self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience)
        except jwt.PyJWKClientConnectionError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"auth-service недоступен: {e}") from e
        except jwt.PyJWKClientError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неизвестный ключ подписи токена") from e
        except jwt.ExpiredSignatureError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен истёк") from e
        except jwt.InvalidTokenError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный токен") from e
        if claims.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен access-токен")
        return CurrentUser(
            id=int(claims["sub"]),
            username=claims.get("username", ""),
            role=Role(claims["role"]),
            full_name=claims.get("name", ""),
            area_ids=claims.get("areas", []),
        )


_verifier: TokenVerifier | None = None


def configure_verifier(verifier: TokenVerifier) -> None:
    global _verifier
    _verifier = verifier


@lru_cache
def _default_verifier() -> TokenVerifier:
    from common.settings import BaseServiceSettings

    s = BaseServiceSettings()
    return TokenVerifier(issuer=s.jwt_issuer, audience=s.jwt_audience, jwks_url=s.auth_jwks_url)


def get_verifier() -> TokenVerifier:
    return _verifier or _default_verifier()


_bearer = HTTPBearer(auto_error=False, description="access_token из POST /api/auth/login")


def token_from_request(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    if creds and creds.credentials:
        return creds.credentials
    return request.query_params.get("access_token")


def require(*roles: Role):
    """Зависимость FastAPI: пускает пользователя с одной из ролей (admin пускается всегда).
    Без аргументов — любой вошедший пользователь."""
    allowed = set(roles)

    def dep(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
        token = token_from_request(request, creds)
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужна авторизация", headers={"WWW-Authenticate": "Bearer"})
        user = get_verifier().verify(token)
        if allowed and user.role not in allowed and user.role != Role.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dep
