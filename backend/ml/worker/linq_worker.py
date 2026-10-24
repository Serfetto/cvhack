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
from ml_runtime import postprocess_detect, postprocess_pose, preprocess  # noqa: E402


def broker_parameters(url: str, timeout_s: float) -> pika.URLParameters:
    parameters = pika.URLParameters(url)
    parameters.socket_timeout = timeout_s
    parameters.blocked_connection_timeout = timeout_s
    return parameters


class LinqWorker:
    """Runs every model (pose, objects) on each JPEG; persons come from pose, objects from detect models."""

    def __init__(self, models: list[tuple[ModelSpec, Path]], broker_url: str,
                 request_queue: str, timeout_s: float = 10.0,
                 conf: float = 0.35, iou: float = 0.5, objects_conf: float = 0.25):
        for spec, program in models:
            if not program.is_file():
                raise FileNotFoundError(program)
            if not spec.path("onnx_tail").is_file():
                raise FileNotFoundError(spec.path("onnx_tail"))
        self.models, self.broker_url = models, broker_url
        self.request_queue, self.timeout_s = request_queue, timeout_s
        self.conf, self.iou, self.objects_conf = conf, iou, objects_conf

    def infer_tpu(self, tensors: dict[str, np.ndarray]) -> dict[str, dict[str, np.ndarray]]:
        """Sends all programs to the shared TPU at once, each with its own reply queue."""
        from tpu_pycloud_format import (
            MESSAGE_ID_ATTR_NAME, RESPONSE_ROUTING_KEYS_ATTR_NAME,
            TARGET_URI_ATTR_NAME, PyTask, deserialize, serialize,
        )

        connection = pika.BlockingConnection(broker_parameters(self.broker_url, self.timeout_s))
        try:
            channel = connection.channel()
            replies: dict[str, bytes] = {}
            for spec, program in self.models:
                reply_queue = channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
                channel.queue_bind(exchange="tpu.direct", queue=reply_queue, routing_key=reply_queue)
                channel.basic_consume(reply_queue, lambda _ch, _m, _p, body, name=spec.name: replies.setdefault(name, body),
                                      auto_ack=True)
                channel.basic_publish(
                    exchange="tpu.direct", routing_key="input",
                    body=serialize(PyTask(data={spec.input_name: tensors[spec.name]})),
                    properties=pika.BasicProperties(headers={
                        TARGET_URI_ATTR_NAME: f"file://{program}?raw=False",
                        RESPONSE_ROUTING_KEYS_ATTR_NAME: json.dumps([reply_queue]),
                        MESSAGE_ID_ATTR_NAME: uuid.uuid4().hex,
                    }),
                )
            deadline = time.monotonic() + self.timeout_s
            while len(replies) < len(self.models):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"LinQ TPU did not answer within {self.timeout_s:g}s")
                connection.process_data_events(time_limit=min(left, 0.2))
            result = {}
            for spec, _ in self.models:
                outputs, _, _ = deserialize(replies[spec.name])
                missing = set(spec.output_names) - outputs.keys()
                if missing:
                    raise ValueError(f"TPU reply for {spec.name} lacks outputs: {sorted(missing)}")
                result[spec.name] = outputs
            return result
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
        tensors, metas = {}, {}
        for spec, _ in self.models:
            tensors[spec.name], metas[spec.name] = preprocess(image, spec)
        prepared = time.monotonic()
        outputs = self.infer_tpu(tensors)
        inferred = time.monotonic()
        persons, objects = [], []
        for spec, _ in self.models:
            if spec.task == "pose":
                persons += postprocess_pose(outputs[spec.name], metas[spec.name], spec, self.conf, self.iou)
            else:
                objects += postprocess_detect(outputs[spec.name], metas[spec.name], spec, self.objects_conf, self.iou)
        done = time.monotonic()
        return {
            "persons": persons, "objects": objects, "backend": "linq-tpu",
            "models": {spec.name: f"{spec.name}@{spec.version}-linq-tpu" for spec, _ in self.models},
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
    parser.add_argument("--model-dir", type=Path, action="append", required=True,
                        help="data/models/<name> with meta.json; repeat for pose and objects")
    parser.add_argument("--program-dir", type=Path, default=Path("/auto/cache") / os.getenv("USER", ""),
                        help="where the TPU service reads .tpu programs (meta.json files.tpu)")
    parser.add_argument("--broker-url", default=os.getenv("BROKER_URL", "amqp://guest:guest@10.0.114.30:5672/%2F"))
    parser.add_argument("--request-queue", default=os.getenv("BROKER_REQUEST_QUEUE", "cvhack12731.jpeg"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--objects-conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args()
    specs = [ModelSpec.load(d) for d in args.model_dir]
    worker = LinqWorker(
        [(spec, (args.program_dir / spec.files["tpu"]).resolve()) for spec in specs], args.broker_url,
        args.request_queue, args.timeout, args.conf, args.iou, args.objects_conf,
    )
    print("Models: " + ", ".join(f"{s.name} ({s.task}, {s.files['tpu']})" for s in specs), flush=True)
    worker.serve_forever()


if __name__ == "__main__":
    main()
