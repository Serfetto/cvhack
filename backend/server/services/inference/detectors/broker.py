"""JPEG request/reply client for the LinQ worker running in Jupyter.

Connections are kept open and pooled: an AMQP handshake over the VPN costs several round trips,
and the shared TPU serves parallel requests, so callers may run up to INFERENCE_CONCURRENCY at once.
"""

from __future__ import annotations

import json
import logging
import queue
import time
import uuid

import cv2
import numpy as np
import pika

from .base import DetectResult

MAX_SIDE = 640  # the worker letterboxes to the model input anyway; larger frames only load the VPN
logging.getLogger("pika").setLevel(logging.WARNING)  # INFO on every connection and channel


def shrink(jpeg: bytes, max_side: int = MAX_SIDE) -> bytes:
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None or max(image.shape[:2]) <= max_side:
        return jpeg  # an undecodable frame goes as is: the worker replies with the error
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    image = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


class _Client:
    """One connection with its own reply queue. A late reply to a timed-out request is skipped."""

    def __init__(self, url: str, request_queue: str, timeout_s: float):
        params = pika.URLParameters(url)
        params.socket_timeout = timeout_s
        params.blocked_connection_timeout = timeout_s
        self.request_queue = request_queue
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=request_queue, durable=True)
        self.reply_queue = self.channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
        self.channel.basic_consume(self.reply_queue, self._on_reply, auto_ack=True)
        self.waiting: str | None = None
        self.reply: bytes | None = None

    def _on_reply(self, channel, method, properties, body: bytes) -> None:
        if properties.correlation_id == self.waiting:
            self.reply = body

    def call(self, jpeg: bytes, headers: dict, timeout_s: float) -> bytes:
        self.waiting, self.reply = uuid.uuid4().hex, None
        self.channel.basic_publish(
            exchange="", routing_key=self.request_queue, body=jpeg,
            properties=pika.BasicProperties(
                content_type="image/jpeg", correlation_id=self.waiting, reply_to=self.reply_queue,
                expiration=str(int(timeout_s * 1000)), headers=headers,
            ),
        )
        deadline = time.monotonic() + timeout_s
        while self.reply is None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"LinQ worker did not answer within {timeout_s:g}s")
            self.connection.process_data_events(time_limit=min(left, 0.2))
        return self.reply

    def close(self) -> None:
        try:
            if self.connection.is_open:
                self.connection.close()
        except pika.exceptions.AMQPError:
            pass


class BrokerDetector:
    name = "broker"

    def __init__(self, url: str, request_queue: str, timeout_s: float = 3.0):
        if not url or not request_queue:
            raise ValueError("BROKER_URL and BROKER_REQUEST_QUEUE are required")
        self.url = url
        self.request_queue = request_queue
        self.timeout_s = timeout_s
        self.idle: queue.Queue[_Client] = queue.Queue()  # FIFO: every pooled connection stays in use and alive

    def _client(self) -> _Client:
        while True:
            try:
                client = self.idle.get_nowait()
            except queue.Empty:
                return _Client(self.url, self.request_queue, self.timeout_s)
            if client.connection.is_open:
                return client
            client.close()

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        if not jpeg:
            raise ValueError("Empty JPEG")
        started = time.monotonic()
        jpeg = shrink(jpeg)
        client = self._client()
        try:
            body = client.call(jpeg, {"camera_id": camera_id or "", "ts": str(ts) if ts is not None else ""}, self.timeout_s)
        except TimeoutError:
            self.idle.put(client)  # the connection is fine, the worker is just late or absent
            raise
        except BaseException:
            client.close()
            raise
        self.idle.put(client)
        payload = json.loads(body)
        if "error" in payload:
            raise RuntimeError(f"LinQ worker: {payload['error']}")
        result = DetectResult.model_validate(payload)
        total_ms = (time.monotonic() - started) * 1000
        worker_ms = result.latency_ms.get("total", 0.0)
        result.latency_ms["rpc"] = round(max(total_ms - worker_ms, 0.0), 3)
        result.latency_ms["total"] = round(total_ms, 3)
        return result

    def info(self) -> dict:
        return {"backend": self.name, "request_queue": self.request_queue, "models": []}
