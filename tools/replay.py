"""Прогон видеофайла через конвейер офлайн: детектор → трекинг → сценарии → конечный автомат.
Печатает события с таймкодами видео. Redis, БД и Docker не нужны.

Примеры:
    # синтетический детектор, правила камеры cam-01 из infra/cameras.yml
    python tools/replay.py data/demo_videos/cam01.mp4 --camera cam-01

    # модель ML на CPU, один сценарий без зоны, свои параметры
    python tools/replay.py fall01.mp4 --detector onnx --scenario fall --params '{"confirm_s": 1.0}'

    # сохранить детекции и потом быстро перебирать пороги без нейросети
    python tools/replay.py fall01.mp4 --detector onnx --scenario fall --save-detections fall01.jsonl
    python tools/replay.py fall01.mp4 --detections fall01.jsonl --scenario fall --params '{"torso_angle_deg": 50}'

    # режим B: горячий путь на стенде LinQ, события — в event-service по HTTP
    python tools/replay.py rtsp://... --detector pytpu --camera cam-01 --post http://<vps>:8080/api/events --token change-me
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs/common", "services/analytics", "services/inference"):
    sys.path.insert(0, str(ROOT / p))

import cv2  # noqa: E402

from common.camconfig import load_yaml  # noqa: E402
from common.messages import CameraConfig, DetectionsMsg, RuleCfg  # noqa: E402


def fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="видеофайл, папка кадров или rtsp://")
    ap.add_argument("--camera", default="cam-01", help="id камеры в YAML (зоны и правила)")
    ap.add_argument("--yaml", default=str(ROOT / "infra/cameras.yml"))
    ap.add_argument("--scenario", help="вместо правил камеры — один сценарий без зоны")
    ap.add_argument("--zone", help='полигон для --scenario: "[[0,0],[0.5,0],[0.5,1],[0,1]]"')
    ap.add_argument("--params", default="{}", help="JSON с параметрами правила")
    ap.add_argument("--fps", type=float, help="FPS анализа (по умолчанию — из конфигурации камеры)")
    ap.add_argument("--detector", default="synthetic", help="synthetic | null | onnx | pytpu | remote")
    ap.add_argument("--remote-url", default="")
    ap.add_argument("--models-dir", default=str(ROOT / "data/models"))
    ap.add_argument("--models", default="pose")
    ap.add_argument("--detections", help="JSONL с готовыми детекциями (без нейросети)")
    ap.add_argument("--save-detections", help="записать детекции в JSONL")
    ap.add_argument("--tracker", default="bytetrack", help="bytetrack | iou")
    ap.add_argument("--realtime", action="store_true", help="отдавать кадры в реальном времени")
    ap.add_argument("--post", help="URL event-service (…/api/events): слать нарушения в POST /ingest/violations")
    ap.add_argument("--token", default="change-me", help="X-Ingest-Token для --post")
    ap.add_argument("--max-seconds", type=float, help="обработать только начало видео")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):  # консоль Windows (cp1251) не печатает часть символов
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    from engine import Engine
    from scenarios import LOAD_ERRORS, REGISTRY

    for name, err in LOAD_ERRORS.items():
        print(f"[!] сценарий {name} не загрузился:\n{err}", file=sys.stderr)

    _, cams = load_yaml(args.yaml)
    params = json.loads(args.params)
    if args.scenario:
        if args.scenario not in REGISTRY:
            print(f"Нет сценария {args.scenario}. Есть: {', '.join(REGISTRY)}", file=sys.stderr)
            return 2
        zones = []
        if args.zone:
            zones = [{"id": 1, "name": "zone", "kind": "danger", "polygon": json.loads(args.zone)}]
        cfg = CameraConfig(id=args.camera, name=args.camera, source_url=args.video, zones=zones,
                           rules=[RuleCfg(id=1, scenario=args.scenario, zone_id=1 if zones else None, params=params)])
    else:
        if args.camera not in cams:
            print(f"Камеры {args.camera} нет в {args.yaml}", file=sys.stderr)
            return 2
        cfg = cams[args.camera]
        if params:
            cfg.rules = [r.model_copy(update={"params": {**r.params, **params}}) for r in cfg.rules]
    if args.fps:
        cfg.analysis_fps = args.fps
    if not cfg.rules:
        print("[!] у камеры нет правил — события не появятся", file=sys.stderr)

    engine = Engine(args.tracker)
    engine.set_config(cfg)

    detector = None
    cached: list[dict] = []
    if args.detections:
        cached = [json.loads(line) for line in Path(args.detections).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        from detectors import create_detector

        detector = create_detector(args.detector, models_dir=args.models_dir, models=args.models.split(","), remote_url=args.remote_url)
    save = open(args.save_detections, "w", encoding="utf-8") if args.save_detections else None

    http = None
    if args.post:
        import httpx

        http = httpx.Client(timeout=10)

    stats = Counter()
    lat: list[float] = []
    t_wall = time.perf_counter()
    t0 = cached[0]["ts"] if cached else time.time()  # таймкоды — от начала видео

    def frames():
        if cached:
            for d in cached:
                yield DetectionsMsg.model_validate(d), None
            return
        cap = cv2.VideoCapture(args.video)
        if not cap.isOpened():
            raise SystemExit(f"Не удалось открыть {args.video}")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = 1.0 / cfg.analysis_fps
        idx, next_t, seq = 0, 0.0, 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            media_t = idx / src_fps
            idx += 1
            if media_t + 1e-6 < next_t:
                continue
            next_t += step
            if args.max_seconds and media_t > args.max_seconds:
                break
            ok, frame = cap.retrieve()
            if not ok:
                continue
            if args.realtime:
                time.sleep(max(0.0, t0 + media_t - time.time()))
            h, w = frame.shape[:2]
            jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
            seq += 1
            ts = t0 + media_t
            a = time.perf_counter()
            res = detector.detect(jpeg, cfg.id, ts)
            lat.append((time.perf_counter() - a) * 1000)
            det = DetectionsMsg(camera_id=cfg.id, seq=seq, ts=ts, frame_key=f"replay:{seq}", w=w, h=h, backend=res.backend,
                                models=res.models, latency_ms=res.latency_ms, persons=res.persons, objects=res.objects)
            yield det, jpeg

    print(f"Камера {cfg.id}: правила {[r.scenario for r in cfg.rules]}, FPS анализа {cfg.analysis_fps}, детектор "
          f"{'из файла' if cached else args.detector}")
    print("-" * 78)
    n = 0
    for det, jpeg in frames():
        n += 1
        if save:
            save.write(det.model_dump_json() + "\n")
        for t in engine.process(det):
            vt = (t.started_at if t.kind == "started" else (t.ended_at or det.ts)) - t0
            stats[(t.scenario, t.kind)] += 1
            extra = f"conf={t.confidence:.2f} подтверждено через {t.confirmed_at - t.started_at:.1f} с" if t.kind == "started" else \
                f"длилось {((t.ended_at or det.ts) - t.started_at):.1f} с"
            print(f"{fmt(vt)}  {t.kind.upper():7}  {t.scenario:12} трек={t.track_id} зона={t.zone.name if t.zone else '-'}  {extra}")
            if http:
                body = t.to_violation().model_dump(mode="json")
                if t.kind == "started" and jpeg:
                    body["snapshot_b64"] = base64.b64encode(jpeg).decode()
                r = http.post(f"{args.post.rstrip('/')}/ingest/violations", json=body, headers={"X-Ingest-Token": args.token})
                if r.status_code >= 300:
                    print(f"[!] event-service ответил {r.status_code}: {r.text[:200]}", file=sys.stderr)
    if save:
        save.close()
    print("-" * 78)
    wall = time.perf_counter() - t_wall
    print(f"Кадров: {n}, время: {wall:.1f} с ({n / wall:.1f} кадр/с)" if wall > 0 else f"Кадров: {n}")
    if lat:
        lat.sort()
        print(f"Детектор: p50 {lat[len(lat) // 2]:.1f} мс, p95 {lat[int(len(lat) * 0.95) - 1]:.1f} мс")
    for (sc, kind), c in sorted(stats.items()):
        print(f"  {sc}: {kind} x {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
