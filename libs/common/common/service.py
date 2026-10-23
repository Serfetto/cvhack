"""Шаблон сервиса: FastAPI + /health + /metrics + CORS + фоновые задачи с автоперезапуском."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from common.logging import get_logger, setup_logging
from common.metrics import MetricsMiddleware
from common.settings import BaseServiceSettings

log = get_logger(__name__)


def create_app(
    settings: BaseServiceSettings,
    title: str,
    description: str = "",
    lifespan: Callable[[FastAPI], AsyncIterator[None]] | None = None,
    health: Callable[[], Awaitable[dict]] | None = None,
) -> FastAPI:
    setup_logging(settings.service_name, settings.log_level, settings.log_json)
    app = FastAPI(
        title=title,
        description=description,
        version="0.1.0",
        root_path=settings.root_path,
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logging.getLogger("uvicorn.access").addFilter(_QuietProbes())

    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health", tags=["service"], summary="Проверка живости")
    async def _health() -> dict:
        extra = await health() if health else {}
        return {"status": "ok", "service": settings.service_name, **extra}

    return app


class _QuietProbes(logging.Filter):
    """Не засорять лог запросами Prometheus и healthcheck."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "GET /metrics" not in msg and "GET /health" not in msg


class Supervisor:
    """Держит фоновые задачи сервиса (консьюмеры, подписки) и перезапускает их при падении."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def spawn(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        async def runner():
            delay = 1.0
            while True:
                try:
                    await factory()
                    log.warning("task_exited", task=name)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("task_crashed", task=name)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

        self.tasks.append(asyncio.create_task(runner(), name=name))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
