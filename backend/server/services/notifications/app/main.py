"""notification-service: WebSocket-рассылка событий с учётом роли и участков, Telegram (опционально).

Протокол /ws?access_token=… (или ?token=…):
    → {"type": "hello", "user": {...}}
    → {"type": "event.created" | "event.updated" | "event.escalated", "event": EventOut, "notify": bool}
    → {"type": "ping", "ts": …} каждые 25 с;  клиент может слать "ping" — ответ {"type": "pong"}
`notify` — совпадает ли событие с подписками пользователя из ЛК (звук и всплывающее окно — по нему).
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from prometheus_client import Counter, Gauge, Histogram

from common.auth import CurrentUser, get_verifier
from common.bus import Bus
from common.logging import get_logger
from common.messages import CHANNEL_TO_WS_TYPE, SEVERITY_RANK, Channels, Keys, Role, Severity
from common.service import Supervisor, create_app
from common.settings import BaseServiceSettings
from common.storage import Storage

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "notifications"
    telegram_bot_token: str = ""
    ping_s: float = 25.0


settings = Settings()
bus = Bus(settings.redis_url)
storage = Storage.from_settings(settings)
sup = Supervisor()

WS_CONNECTIONS = Gauge("ws_connections", "Открытые WebSocket-соединения")
SENT = Counter("notifications_sent_total", "Отправленные уведомления", ["channel", "type"])
E2E_SECONDS = Histogram("event_e2e_seconds", "От кадра, подтвердившего нарушение, до отправки в браузер",
                        buckets=(0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10))
ALERT_DELAY = Histogram("alert_delay_seconds", "От начала нарушения до оповещения (с окном подтверждения)",
                        buckets=(0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 30))


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    user: CurrentUser
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))


class Hub:
    def __init__(self) -> None:
        self.conns: set[Conn] = set()
        self.prefs: dict[int, dict] = {}
        self.prefs_loaded = 0.0

    async def refresh_prefs(self, force: bool = False) -> None:
        if not force and time.monotonic() - self.prefs_loaded < 30:
            return
        raw = await bus.redis.hgetall(Keys.NOTIFY_USERS)
        self.prefs = {int(k): json.loads(v) for k, v in raw.items()}
        self.prefs_loaded = time.monotonic()

    def wants(self, user_id: int, event: dict) -> bool:
        p = (self.prefs.get(user_id) or {}).get("prefs") or {}
        if p.get("scenarios") and event.get("scenario") not in p["scenarios"]:
            return False
        if p.get("area_ids") and event.get("area_id") not in p["area_ids"]:
            return False
        min_sev = Severity(p.get("min_severity", "low"))
        return SEVERITY_RANK[Severity(event.get("severity", "low"))] >= SEVERITY_RANK[min_sev]

    async def broadcast(self, ws_type: str, event: dict) -> None:
        await self.refresh_prefs()
        for c in list(self.conns):
            if not c.user.has_area(event.get("area_id")):
                continue
            msg = {"type": ws_type, "event": event, "notify": self.wants(c.user.id, event)}
            try:
                c.queue.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning("ws_slow_client_dropped", user=c.user.username)
                await c.ws.close(code=1013)
                self.conns.discard(c)
        SENT.labels("ws", ws_type).inc(len(self.conns))


hub = Hub()


async def listen_events() -> None:
    async for channel, data in bus.listen(patterns=[Channels.EVENTS_PATTERN]):
        ws_type = CHANNEL_TO_WS_TYPE.get(channel)
        event = data.get("event") if isinstance(data, dict) else None
        if not ws_type or not event:
            continue
        if ws_type == "event.created":
            now = time.time()
            if event.get("frame_ts"):
                E2E_SECONDS.observe(max(now - event["frame_ts"], 0))
            try:
                ALERT_DELAY.observe(max(now - datetime.fromisoformat(event["started_at"]).timestamp(), 0))
            except (KeyError, ValueError):
                pass
        await hub.broadcast(ws_type, event)
        if settings.telegram_bot_token and ws_type in ("event.created", "event.escalated"):
            asyncio.create_task(telegram(ws_type, event))


# --- Telegram -------------------------------------------------------------------------------------

SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
ESCALATE_ROLES = {Role.ADMIN.value, Role.HSE.value, Role.MANAGER.value, Role.MASTER.value}


async def telegram(ws_type: str, event: dict) -> None:
    await hub.refresh_prefs()
    targets = []
    for uid, u in hub.prefs.items():
        chat = u.get("telegram_chat_id")
        if not chat:
            continue
        areas = u.get("area_ids") or []
        if u.get("role") == Role.MASTER.value and areas and event.get("area_id") not in areas:
            continue
        if ws_type == "event.escalated":
            if u.get("role") in ESCALATE_ROLES:
                targets.append(chat)
        elif (u.get("prefs") or {}).get("telegram") and hub.wants(uid, event):
            targets.append(chat)
    if not targets:
        return
    head = "⏰ Не принято вовремя! " if ws_type == "event.escalated" else ""
    text = (f"{head}{SEV_ICON.get(event['severity'], '')} {event.get('scenario_title') or event['scenario']}\n"
            f"Камера: {event.get('camera_name') or event['camera_id']}"
            + (f", зона: {event['zone_name']}" if event.get("zone_name") else "")
            + f"\nВремя: {datetime.fromisoformat(event['started_at']).astimezone(ZoneInfo(settings.app_tz)):%d.%m.%Y %H:%M:%S}")
    photo = None
    if event.get("annotated_url") or event.get("snapshot_url"):
        url = event.get("annotated_url") or event.get("snapshot_url")
        key = url.split(f"/{storage.bucket}/", 1)[-1]
        try:
            photo = await storage.get(key)
        except Exception:
            photo = None
    api = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=10) as client:
        for chat in targets:
            try:
                if photo:
                    await client.post(f"{api}/sendPhoto", data={"chat_id": chat, "caption": text}, files={"photo": ("event.jpg", photo, "image/jpeg")})
                else:
                    await client.post(f"{api}/sendMessage", data={"chat_id": chat, "text": text})
                SENT.labels("telegram", ws_type).inc()
            except httpx.HTTPError as e:
                log.warning("telegram_failed", chat=chat, error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.wait_ready()
    await hub.refresh_prefs(force=True)
    sup.spawn("listen-events", listen_events)
    yield
    await sup.stop()
    await bus.close()


app = create_app(settings, "notification-service", "WebSocket-оповещения и Telegram", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    token = ws.query_params.get("access_token") or ws.query_params.get("token")
    try:
        user = await asyncio.to_thread(get_verifier().verify, token or "")
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = Conn(ws, user)
    hub.conns.add(conn)
    WS_CONNECTIONS.set(len(hub.conns))
    await ws.send_json({"type": "hello", "user": user.model_dump(mode="json")})

    async def writer():
        while True:
            try:
                msg = await asyncio.wait_for(conn.queue.get(), timeout=settings.ping_s)
            except TimeoutError:
                msg = {"type": "ping", "ts": time.time()}
            await ws.send_json(msg)

    wtask = asyncio.create_task(writer())
    try:
        while True:
            text = await ws.receive_text()
            if text.strip('"') == "ping" or '"ping"' in text:
                conn.queue.put_nowait({"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.info("ws_closed", user=user.username, error=str(e))
    finally:
        wtask.cancel()
        hub.conns.discard(conn)
        WS_CONNECTIONS.set(len(hub.conns))


@app.get("/connections", tags=["service"], summary="Кто сейчас на связи")
async def connections():
    return [{"user": c.user.username, "role": c.user.role, "areas": c.user.area_ids} for c in hub.conns]
