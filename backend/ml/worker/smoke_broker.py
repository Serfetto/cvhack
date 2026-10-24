"""Local RabbitMQ integration smoke using ONNX in place of the cloud TPU."""

from __future__ import annotations

import argparse
import sys
import threading
import uuid
from pathlib import Path

import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/server/libs/common"))
from smoke_local import CpuHeadWorker, ModelSpec  # noqa: E402
from detectors import create_detector, create_with_fallback  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--broker-url", required=True)
    args = parser.parse_args()
    ort.set_default_logger_severity(3)
    spec = ModelSpec.load(args.model_dir)
    queue = "cvhack_smoke_" + uuid.uuid4().hex[:10]
    worker = CpuHeadWorker(spec, spec.path("tpu"))
    worker.broker_url = args.broker_url
    worker.request_queue = queue
    threading.Thread(target=worker.serve_once, daemon=True).start()
    client = create_detector("broker", broker_url=args.broker_url,
                             broker_request_queue=queue, broker_timeout_s=5.0)
    result = client.detect(args.image.read_bytes(), camera_id="smoke", ts=1.0)
    if len(result.persons) != 1 or result.persons[0].score < 0.8:
        raise AssertionError(f"Unexpected detection: {result.persons}")
    print(f"request/reply OK: {len(result.persons)} person, score={result.persons[0].score:.3f}, "
          f"total={result.latency_ms['total']:.1f} ms")
    try:
        client.detect(b"not a JPEG")
    except RuntimeError as exc:
        if "Cannot decode JPEG" not in str(exc):
            raise
        print("error response OK")
    else:
        raise AssertionError("Invalid JPEG did not return an error")
    missing_queue = queue + "_no_worker"
    try:
        create_detector("broker", broker_url=args.broker_url,
                        broker_request_queue=missing_queue, broker_timeout_s=0.6).detect(b"abc")
    except TimeoutError:
        print("timeout OK")
    else:
        raise AssertionError("Missing worker did not time out")
    fallback = create_with_fallback(
        "broker", "onnx", broker_url=args.broker_url,
        broker_request_queue=missing_queue, broker_timeout_s=0.6,
        models_dir=str(args.model_dir.parent), models=["pose"],
    )
    for _ in range(2):
        try:
            fallback.detect(args.image.read_bytes())
        except TimeoutError:
            continue
        raise AssertionError("Fallback activated before the configured failure count")
    result = fallback.detect(args.image.read_bytes())
    if "аварийный" not in result.backend or len(result.persons) != 1:
        raise AssertionError(f"ONNX fallback failed: {result.backend}, {len(result.persons)} persons")
    print("ONNX fallback OK")


if __name__ == "__main__":
    main()
