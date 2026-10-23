"""Шина на Redis: Streams для горячего пути (consumer groups, ack) и Pub/Sub для оповещений.

В потоке каждое сообщение — одно поле `data` с JSON. Консьюмер подтверждает (XACK) сообщение
только после успешной обработки: рестарт сервиса не теряет данные. Сообщения, упавшие
`max_retries` раз, уходят в `dlq:{stream}`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import redis.asyncio as aioredis
from pydantic import BaseModel, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError, TimeoutError as RedisTimeoutError

from common.logging import get_logger

log = get_logger(__name__)

M = TypeVar("M", bound=BaseModel)


@dataclass(slots=True)
class MsgCtx:
    stream: str
    id: str


Handler = Callable[[M, MsgCtx], Awaitable[None]]


def _s(v: bytes | str) -> str:
    return v.decode() if isinstance(v, bytes) else v


def default_consumer_name(service: str) -> str:
    return f"{service}-{socket.gethostname()}"


class Bus:
    def __init__(self, url: str):
        self.url = url
        # бинарный клиент: кадры JPEG и JSON
        self.redis: aioredis.Redis = aioredis.from_url(url, decode_responses=False, health_check_interval=30)

    async def close(self) -> None:
        await self.redis.aclose()

    async def wait_ready(self, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                await self.redis.ping()
                return
            except (RedisConnectionError, RedisTimeoutError, OSError):
                if time.monotonic() > deadline:
                    raise
                log.warning("redis_not_ready", url=self.url.split("@")[-1])
                await asyncio.sleep(1)

    # --- Streams -----------------------------------------------------------

    async def xadd(self, stream: str, msg: BaseModel | dict, maxlen: int = 10_000) -> str:
        data = msg.model_dump_json() if isinstance(msg, BaseModel) else json.dumps(msg, ensure_ascii=False, default=str)
        msg_id = await self.redis.xadd(stream, {"data": data}, maxlen=maxlen, approximate=True)
        return _s(msg_id)

    async def ensure_group(self, stream: str, group: str, start_id: str = "0") -> None:
        try:
            await self.redis.xgroup_create(stream, group, id=start_id, mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        streams: list[str],
        group: str,
        consumer: str,
        model: type[M],
        handler: Handler,
        *,
        count: int = 10,
        block_ms: int = 1000,
        start_id: str = "0",
        max_retries: int = 3,
        claim_idle_ms: int = 30_000,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Бесконечный цикл чтения группы. Сначала дочитывает свои неподтверждённые сообщения,
        затем новые. Периодически забирает зависшие сообщения упавших консьюмеров (XAUTOCLAIM)."""
        for s in streams:
            await self.ensure_group(s, group, start_id)
        failures: dict[str, int] = {}
        read_pending = True
        last_claim = 0.0
        stop = stop or asyncio.Event()

        async def handle(stream: str, msg_id: str, fields: dict) -> None:
            nonlocal read_pending
            raw = fields.get(b"data") or fields.get("data")
            try:
                obj = model.model_validate_json(raw)
            except (ValidationError, TypeError, ValueError) as e:
                log.error("bad_message", stream=stream, id=msg_id, error=str(e)[:300])
                await self._dead_letter(stream, group, msg_id, raw, "bad_message")
                return
            try:
                await handler(obj, MsgCtx(stream, msg_id))
            except asyncio.CancelledError:
                raise
            except Exception:
                n = failures.get(msg_id, 0) + 1
                failures[msg_id] = n
                log.exception("handler_failed", stream=stream, id=msg_id, attempt=n)
                if n >= max_retries:
                    await self._dead_letter(stream, group, msg_id, raw, "handler_failed")
                    failures.pop(msg_id, None)
                else:
                    read_pending = True
                    await asyncio.sleep(min(0.5 * n, 3))
                return
            failures.pop(msg_id, None)
            await self.redis.xack(stream, group, msg_id)

        while not stop.is_set():
            try:
                now = time.monotonic()
                if now - last_claim > claim_idle_ms / 1000:
                    last_claim = now
                    for s in streams:
                        claimed = await self.redis.xautoclaim(s, group, consumer, min_idle_time=claim_idle_ms, start_id="0-0", count=100)
                        if claimed and claimed[1]:
                            log.warning("claimed_stale_messages", stream=s, n=len(claimed[1]))
                            read_pending = True

                ids = "0" if read_pending else ">"
                resp = await self.redis.xreadgroup(group, consumer, {s: ids for s in streams}, count=count, block=None if read_pending else block_ms)
                got = 0
                for stream_name, messages in resp or []:
                    for msg_id, fields in messages:
                        if not fields:  # удалено из потока (MAXLEN), но висит в pending
                            await self.redis.xack(_s(stream_name), group, msg_id)
                            continue
                        got += 1
                        await handle(_s(stream_name), _s(msg_id), fields)
                if read_pending and got == 0:
                    read_pending = False
                if got == 0:
                    await asyncio.sleep(0)  # отдать управление, даже если клиент вернулся без ожидания
            except asyncio.CancelledError:
                raise
            except (RedisConnectionError, RedisTimeoutError, OSError) as e:
                log.warning("redis_connection_lost", error=str(e))
                await asyncio.sleep(1)
            except ResponseError as e:
                if "NOGROUP" in str(e):
                    for s in streams:
                        await self.ensure_group(s, group, start_id)
                else:
                    log.exception("consume_error")
                    await asyncio.sleep(1)

    async def _dead_letter(self, stream: str, group: str, msg_id: str, raw: Any, reason: str) -> None:
        await self.redis.xadd(f"dlq:{stream}", {"data": raw or b"", "reason": reason, "group": group, "id": msg_id}, maxlen=1000, approximate=True)
        await self.redis.xack(stream, group, msg_id)

    # --- Pub/Sub -------------------------------------------------------------

    async def publish(self, channel: str, msg: BaseModel | dict) -> None:
        data = msg.model_dump_json() if isinstance(msg, BaseModel) else json.dumps(msg, ensure_ascii=False, default=str)
        await self.redis.publish(channel, data)

    async def listen(self, channels: list[str] = (), patterns: list[str] = ()) -> AsyncIterator[tuple[str, dict]]:
        """Подписка с автоматическим переподключением. Отдаёт (канал, данные JSON)."""
        while True:
            pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
            try:
                if channels:
                    await pubsub.subscribe(*channels)
                if patterns:
                    await pubsub.psubscribe(*patterns)
                async for m in pubsub.listen():
                    if m.get("type") not in ("message", "pmessage"):
                        continue
                    try:
                        data = json.loads(m["data"])
                    except (TypeError, ValueError):
                        continue
                    yield _s(m["channel"]), data
                await asyncio.sleep(0.5)  # подписка завершилась без ошибки — переподключаемся с паузой
            except asyncio.CancelledError:
                raise
            except (RedisConnectionError, RedisTimeoutError, OSError) as e:
                log.warning("pubsub_reconnect", error=str(e))
                await asyncio.sleep(1)
            finally:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    # --- Кадры и JSON-ключи ---------------------------------------------------

    async def get_json(self, key: str) -> Any:
        raw = await self.redis.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ex: int | None = None) -> None:
        await self.redis.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ex)
