"""Jupyter-side JPEG -> LinQ cloud TPU -> compact JSON worker.

Run as a regular Python process on the LinQ Jupyter host. This process has no
direct TPU device: it sends PyTask to the shared tpu.direct/input queue.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import pika

INFERENCE_DIR = Path(__file__).resolve().parents[2] / "server/services/inference"
sys.path.insert(0, str(INFERENCE_DIR))
from backends.base import ModelSpec  # noqa: E402
from ml_runtime import postprocess_pose, preprocess  # noqa: E402


def broker_parameters(url: str, timeout_s: float) -> pika.URLParameters:
    parameters = pika.URLParameters(url)
    parameters.socket_timeout = timeout_s
    parameters.blocked_connection_timeout = timeout_s
    return parameters


class LinqPoseWorker:
    def __init__(self, spec: ModelSpec, program: Path, broker_url: str,
                 request_queue: str, timeout_s: float = 10.0,
                 conf: float = 0.35, iou: float = 0.5):
        if not program.is_file():
            raise FileNotFoundError(program)
        if not spec.path("onnx_tail").is_file():
            raise FileNotFoundError(spec.path("onnx_tail"))
        self.spec, self.program, self.broker_url = spec, program, broker_url
        self.request_queue, self.timeout_s = request_queue, timeout_s
        self.conf, self.iou = conf, iou

    def infer_tpu(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        from tpu_pycloud_format import (
            MESSAGE_ID_ATTR_NAME, RESPONSE_ROUTING_KEYS_ATTR_NAME,
            TARGET_URI_ATTR_NAME, PyTask, deserialize, serialize,
        )

        connection = pika.BlockingConnection(broker_parameters(self.broker_url, self.timeout_s))
        try:
            channel = connection.channel()
            task_id = uuid.uuid4().hex
            reply_queue = channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
            channel.queue_bind(exchange="tpu.direct", queue=reply_queue, routing_key=reply_queue)
            channel.basic_publish(
                exchange="tpu.direct", routing_key="input",
                body=serialize(PyTask(data={self.spec.input_name: tensor})),
                properties=pika.BasicProperties(headers={
                    TARGET_URI_ATTR_NAME: f"file://{self.program}?raw=False",
                    RESPONSE_ROUTING_KEYS_ATTR_NAME: json.dumps([reply_queue]),
                    MESSAGE_ID_ATTR_NAME: task_id,
                }),
            )
            deadline = time.monotonic() + self.timeout_s
            for method, properties, body in channel.consume(
                reply_queue, auto_ack=True, inactivity_timeout=0.2,
            ):
                if method is not None:
                    if properties.headers and properties.headers.get(MESSAGE_ID_ATTR_NAME, task_id) != task_id:
                        raise RuntimeError("TPU reply has a different task ID")
                    outputs, _, _ = deserialize(body)
                    missing = set(self.spec.output_names) - outputs.keys()
                    if missing:
                        raise ValueError(f"TPU reply lacks outputs: {sorted(missing)}")
                    return outputs
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"LinQ TPU did not answer within {self.timeout_s:g}s")
            raise RuntimeError("TPU reply consumer stopped")
        finally:
            if connection.is_open:
                connection.close()

    def detect(self, jpeg: bytes) -> dict:
        started = time.monotonic()
        if len(jpeg) > 8_000_000:
            raise ValueError("JPEG exceeds 8 MB worker limit")
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Cannot decode JPEG")
        tensor, meta = preprocess(image, self.spec)
        prepared = time.monotonic()
        outputs = self.infer_tpu(tensor)
        inferred = time.monotonic()
        persons = postprocess_pose(outputs, meta, self.spec, self.conf, self.iou)
        done = time.monotonic()
        return {
            "persons": persons, "objects": [], "backend": "linq-tpu",
            "models": {self.spec.name: f"{self.spec.name}@{self.spec.version}-linq-tpu"},
            "latency_ms": {
                "pre": round((prepared - started) * 1000, 3),
                "infer": round((inferred - prepared) * 1000, 3),
                "post": round((done - inferred) * 1000, 3),
                "total": round((done - started) * 1000, 3),
            },
        }

    def serve_once(self) -> None:
        connection = pika.BlockingConnection(broker_parameters(self.broker_url, self.timeout_s))
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.request_queue, durable=True)
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=1)
            print(f"Listening on RabbitMQ queue {self.request_queue}", flush=True)
            for method, properties, body in channel.consume(self.request_queue, auto_ack=False, inactivity_timeout=1.0):
                if method is None:
                    continue
                try:
                    result = self.detect(body)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                if properties.reply_to:
                    try:
                        channel.basic_publish(
                            exchange="", routing_key=properties.reply_to,
                            body=json.dumps(result, separators=(",", ":")).encode(),
                            properties=pika.BasicProperties(
                                content_type="application/json", correlation_id=properties.correlation_id,
                            ), mandatory=True,
                        )
                    except pika.exceptions.UnroutableError:
                        pass  # The client timed out and its temporary reply queue disappeared.
                channel.basic_ack(method.delivery_tag)
        finally:
            if connection.is_open:
                connection.close()

    def serve_forever(self) -> None:
        while True:
            try:
                self.serve_once()
            except KeyboardInterrupt:
                return
            except pika.exceptions.AMQPError as exc:
                print(f"RabbitMQ disconnected: {exc}; retrying in 2s", file=sys.stderr, flush=True)
                time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--broker-url", default=os.getenv("BROKER_URL", "amqp://guest:guest@10.0.114.30:5672/%2F"))
    parser.add_argument("--request-queue", default=os.getenv("BROKER_REQUEST_QUEUE", "cvhack12731.jpeg"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args()
    worker = LinqPoseWorker(
        ModelSpec.load(args.model_dir), args.program.resolve(), args.broker_url,
        args.request_queue, args.timeout, args.conf, args.iou,
    )
    worker.serve_forever()


if __name__ == "__main__":
    main()
