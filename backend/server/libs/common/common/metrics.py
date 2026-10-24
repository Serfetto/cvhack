"""Prometheus: /metrics в каждом сервисе и метрика длительности HTTP-запросов."""

import time

from prometheus_client import Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HTTP_SECONDS = Histogram(
    "http_request_seconds",
    "Длительность HTTP-запросов",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

# Бакеты для задержек горячего пути (секунды)
LATENCY_BUCKETS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        if path and path not in ("/metrics", "/health"):
            HTTP_SECONDS.labels(request.method, path, str(response.status_code)).observe(time.perf_counter() - start)
        return response
