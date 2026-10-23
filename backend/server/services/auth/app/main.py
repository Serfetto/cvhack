"""auth-service: личный кабинет, пользователи и роли, выпуск JWT."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, TokenVerifier, configure_verifier, require
from common.bus import Bus
from common.db import Database
from common.logging import get_logger
from common.messages import Keys, Role, Severity
from common.service import create_app
from common.settings import BaseServiceSettings

from .models import Base, RefreshToken, User
from .security import KeyPair, hash_password, hash_refresh, issue_access_token, new_refresh_token, verify_password

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "auth"
    jwt_key_path: str = "/data/keys/jwt.pem"
    access_ttl_min: int = 15
    refresh_ttl_days: int = 7
    demo_password: str = "demo"
    seed_users: bool = True


settings = Settings()
db = Database(settings.database_url, "auth")
bus = Bus(settings.redis_url)
keys: KeyPair | None = None

ROLE_TITLES = {
    Role.ADMIN: "Администратор",
    Role.HSE: "Специалист по охране труда",
    Role.MASTER: "Мастер / начальник смены",
    Role.OPERATOR: "Диспетчер",
    Role.MANAGER: "Руководитель",
    Role.AUDITOR: "Юрист / аудитор",
}

SEED = [
    ("admin", Role.ADMIN, "Администратор системы", []),
    ("hse", Role.HSE, "Иванова Анна (охрана труда)", []),
    ("master", Role.MASTER, "Петров Сергей (мастер цеха №1)", [1]),
    ("operator", Role.OPERATOR, "Сидоров Олег (диспетчер)", []),
    ("manager", Role.MANAGER, "Кузнецова Мария (руководитель)", []),
    ("auditor", Role.AUDITOR, "Смирнов Павел (юрист)", []),
]


# --- схемы API ---------------------------------------------------------------


class NotifyPrefs(BaseModel):
    scenarios: list[str] = Field(default_factory=list, description="Пусто — все типы нарушений")
    area_ids: list[int] = Field(default_factory=list, description="Пусто — все доступные участки")
    min_severity: Severity = Severity.LOW
    telegram: bool = False
    sound: bool = True


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: Role
    role_title: str
    area_ids: list[int]
    is_active: bool
    telegram_chat_id: int | None
    notify_prefs: NotifyPrefs
    created_at: datetime


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MePatch(BaseModel):
    full_name: str | None = None
    telegram_chat_id: int | None = None
    notify_prefs: NotifyPrefs | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=4)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=4)
    full_name: str = ""
    role: Role
    area_ids: list[int] = Field(default_factory=list)


class UserPatch(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    area_ids: list[int] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=4)
    telegram_chat_id: int | None = None


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        full_name=u.full_name,
        role=Role(u.role),
        role_title=ROLE_TITLES[Role(u.role)],
        area_ids=list(u.area_ids or []),
        is_active=u.is_active,
        telegram_chat_id=u.telegram_chat_id,
        notify_prefs=NotifyPrefs.model_validate(u.notify_prefs or {}),
        created_at=u.created_at,
    )


# --- служебное ------------------------------------------------------------------


async def sync_notify_user(u: User) -> None:
    """Кому и куда слать уведомления — notification-service читает это из Redis, а не из нашей БД."""
    if not u.is_active:
        await bus.redis.hdel(Keys.NOTIFY_USERS, str(u.id))
        return
    data = {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "area_ids": list(u.area_ids or []),
        "telegram_chat_id": u.telegram_chat_id,
        "prefs": u.notify_prefs or {},
    }
    await bus.redis.hset(Keys.NOTIFY_USERS, str(u.id), json.dumps(data, ensure_ascii=False))


async def seed(session: AsyncSession) -> None:
    exists = (await session.execute(select(User.id).limit(1))).first()
    if exists or not settings.seed_users:
        return
    for username, role, name, areas in SEED:
        session.add(User(username=username, password_hash=hash_password(settings.demo_password), full_name=name,
                         role=role.value, area_ids=areas, notify_prefs=NotifyPrefs().model_dump(mode="json")))
    await session.commit()
    log.info("seeded_users", n=len(SEED))


async def issue_tokens(session: AsyncSession, u: User) -> TokenOut:
    access = issue_access_token(keys, u, settings.jwt_issuer, settings.jwt_audience, settings.access_ttl_min * 60)
    refresh, refresh_hash = new_refresh_token()
    session.add(RefreshToken(token_hash=refresh_hash, user_id=u.id,
                             expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_ttl_days)))
    await session.commit()
    return TokenOut(access_token=access, refresh_token=refresh, expires_in=settings.access_ttl_min * 60, user=user_out(u))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global keys
    keys = KeyPair(settings.jwt_key_path)
    configure_verifier(TokenVerifier(settings.jwt_issuer, settings.jwt_audience, public_key=keys.public))
    await db.init(Base.metadata)
    await bus.wait_ready()
    async with db.sessionmaker() as s:
        await seed(s)
        for u in (await s.execute(select(User))).scalars():
            await sync_notify_user(u)
    yield
    await bus.close()
    await db.close()


app = create_app(settings, "auth-service", "Личный кабинет, пользователи, роли и JWT", lifespan=lifespan)


async def get_user(session: AsyncSession, user_id: int) -> User:
    u = await session.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return u


# --- вход ---------------------------------------------------------------------------


@app.post("/login", response_model=TokenOut, tags=["auth"], summary="Вход по логину и паролю")
async def login(body: LoginIn, session: AsyncSession = Depends(db.session)):
    u = (await session.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return await issue_tokens(session, u)


@app.post("/refresh", response_model=TokenOut, tags=["auth"], summary="Обновить пару токенов (refresh одноразовый)")
async def refresh(body: RefreshIn, session: AsyncSession = Depends(db.session)):
    rt = await session.get(RefreshToken, hash_refresh(body.refresh_token))
    if not rt or rt.revoked_at or rt.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-токен недействителен")
    rt.revoked_at = datetime.now(UTC)
    u = await get_user(session, rt.user_id)
    if not u.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь отключён")
    return await issue_tokens(session, u)


@app.post("/logout", status_code=204, tags=["auth"], summary="Выход: отозвать refresh-токен")
async def logout(body: RefreshIn, session: AsyncSession = Depends(db.session)):
    await session.execute(update(RefreshToken).where(RefreshToken.token_hash == hash_refresh(body.refresh_token))
                          .values(revoked_at=datetime.now(UTC)))
    await session.commit()


@app.get("/.well-known/jwks.json", tags=["auth"], summary="Публичные ключи для проверки JWT")
async def jwks():
    return keys.jwks()


@app.get("/roles", tags=["auth"], summary="Справочник ролей")
async def roles():
    return [{"code": r.value, "title": t} for r, t in ROLE_TITLES.items()]


# --- личный кабинет --------------------------------------------------------------


@app.get("/me", response_model=UserOut, tags=["me"], summary="Профиль текущего пользователя")
async def me(user: CurrentUser = Depends(require()), session: AsyncSession = Depends(db.session)):
    return user_out(await get_user(session, user.id))


@app.patch("/me", response_model=UserOut, tags=["me"], summary="Изменить профиль и подписки на уведомления")
async def patch_me(body: MePatch, user: CurrentUser = Depends(require()), session: AsyncSession = Depends(db.session)):
    u = await get_user(session, user.id)
    if body.full_name is not None:
        u.full_name = body.full_name
    if "telegram_chat_id" in body.model_fields_set:
        u.telegram_chat_id = body.telegram_chat_id
    if body.notify_prefs is not None:
        u.notify_prefs = body.notify_prefs.model_dump(mode="json")
    await session.commit()
    await sync_notify_user(u)
    return user_out(u)


@app.post("/me/password", status_code=204, tags=["me"], summary="Сменить пароль")
async def change_password(body: PasswordChange, user: CurrentUser = Depends(require()), session: AsyncSession = Depends(db.session)):
    u = await get_user(session, user.id)
    if not verify_password(body.old_password, u.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Старый пароль неверен")
    u.password_hash = hash_password(body.new_password)
    await session.commit()


# --- пользователи (админ) ----------------------------------------------------------


@app.get("/users", response_model=list[UserOut], tags=["users"], summary="Список пользователей")
async def list_users(_: CurrentUser = Depends(require(Role.ADMIN)), session: AsyncSession = Depends(db.session)):
    return [user_out(u) for u in (await session.execute(select(User).order_by(User.id))).scalars()]


@app.post("/users", response_model=UserOut, status_code=201, tags=["users"], summary="Создать пользователя")
async def create_user(body: UserCreate, _: CurrentUser = Depends(require(Role.ADMIN)), session: AsyncSession = Depends(db.session)):
    if (await session.execute(select(User.id).where(User.username == body.username))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Логин уже занят")
    u = User(username=body.username, password_hash=hash_password(body.password), full_name=body.full_name,
             role=body.role.value, area_ids=body.area_ids, notify_prefs=NotifyPrefs().model_dump(mode="json"))
    session.add(u)
    await session.commit()
    await session.refresh(u)
    await sync_notify_user(u)
    return user_out(u)


@app.patch("/users/{user_id}", response_model=UserOut, tags=["users"], summary="Изменить пользователя")
async def patch_user(user_id: int, body: UserPatch, _: CurrentUser = Depends(require(Role.ADMIN)), session: AsyncSession = Depends(db.session)):
    u = await get_user(session, user_id)
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None:
        u.role = body.role.value
    if body.area_ids is not None:
        u.area_ids = body.area_ids
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    if "telegram_chat_id" in body.model_fields_set:
        u.telegram_chat_id = body.telegram_chat_id
    await session.commit()
    await sync_notify_user(u)
    return user_out(u)
