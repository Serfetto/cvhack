"""JPEG request/reply client for the LinQ worker running in Jupyter."""

from __future__ import annotations

import json
import time
import uuid

import pika

from .base import DetectResult


class BrokerDetector:
    name = "broker"

    def __init__(self, url: str, request_queue: str, timeout_s: float = 3.0):
        if not url or not request_queue:
            raise ValueError("BROKER_URL and BROKER_REQUEST_QUEUE are required")
        self.url = url
        self.request_queue = request_queue
        self.timeout_s = timeout_s

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        if not jpeg:
            raise ValueError("Empty JPEG")
        started = time.monotonic()
        params = pika.URLParameters(self.url)
        params.socket_timeout = self.timeout_s
        params.blocked_connection_timeout = self.timeout_s
        connection = pika.BlockingConnection(params)
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.request_queue, durable=True)
            reply_queue = channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
            request_id = uuid.uuid4().hex
            channel.basic_publish(
                exchange="", routing_key=self.request_queue, body=jpeg,
                properties=pika.BasicProperties(
                    content_type="image/jpeg", correlation_id=request_id, reply_to=reply_queue,
                    expiration=str(int(self.timeout_s * 1000)),
                    headers={"camera_id": camera_id or "", "ts": str(ts) if ts is not None else ""},
                ),
            )
            deadline = started + self.timeout_s
            for method, properties, body in channel.consume(
                reply_queue, auto_ack=True, inactivity_timeout=0.2,
            ):
                if method is not None:
                    if properties.correlation_id != request_id:
                        raise RuntimeError("RabbitMQ reply has a different correlation ID")
                    payload = json.loads(body)
                    if "error" in payload:
                        raise RuntimeError(f"LinQ worker: {payload['error']}")
                    result = DetectResult.model_validate(payload)
                    total_ms = (time.monotonic() - started) * 1000
                    worker_ms = result.latency_ms.get("total", 0.0)
                    result.latency_ms["rpc"] = round(max(total_ms - worker_ms, 0.0), 3)
                    result.latency_ms["total"] = round(total_ms, 3)
                    return result
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"LinQ worker did not answer within {self.timeout_s:g}s")
            raise RuntimeError("RabbitMQ reply consumer stopped")
        finally:
            if connection.is_open:
                connection.close()

    def info(self) -> dict:
        return {"backend": self.name, "request_queue": self.request_queue, "models": []}
