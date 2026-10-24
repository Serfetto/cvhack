"""Fine-tune YOLOv8s (COCO weights) on data/datasets/objects: forklift, pallet_truck, phone.

    python backend/ml/training/train_objects.py --data data/datasets/objects/data.yaml

Result: data/runs/objects/weights/best.pt. Then the same path as pose (backend/ml/README.md):
export_onnx.py → cut_head.py --name objects → verify_split.py → compile_tpu.py.
YOLOv8, not YOLO11: the head cut and the TPU compilation are proven on v8.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/datasets/objects/data.yaml"))
    parser.add_argument("--weights", default="yolov8s.pt")
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--batch", type=int, default=12)
    # на Windows каждый воркер загрузки — отдельный процесс с CUDA-библиотеками torch (~1 ГБ выделенной
    # памяти): 8 воркеров рядом с Docker исчерпали файл подкачки (WinError 1455)
    parser.add_argument("--workers", type=int, default=3)
    # disk — картинки один раз декодируются в .npy рядом с JPEG (~7 ГБ): без воркеров обучение упирается в декодирование
    parser.add_argument("--cache", default="disk", choices=["disk", "ram", "none"])
    parser.add_argument("--project", type=Path, default=Path("data/runs"))
    parser.add_argument("--name", default="objects")
    args = parser.parse_args()
    YOLO(args.weights).train(
        data=str(args.data), imgsz=640, epochs=args.epochs, batch=args.batch, workers=args.workers,
        cache=False if args.cache == "none" else args.cache,
        project=str(args.project.resolve()), name=args.name, exist_ok=True,
        # Без AMP: на RTX 5060 Ti (torch 2.11, ultralytics 8.4) fp16 разгонял cls_loss до сотен, и после эпохи
        # mAP был 0. Muon (оптимизатор по умолчанию в 8.4) падал с bad allocation, SGD с lr 0,01 расходился.
        # AdamW с lr 0,001 — прежний выбор ultralytics для дообучения; смещения на прогреве не разгоняем до 0,1.
        optimizer="AdamW", lr0=0.001, amp=False, warmup_epochs=1, warmup_bias_lr=0.001,
        patience=15, cos_lr=True, close_mosaic=10, seed=0, plots=True,
    )


if __name__ == "__main__":  # Windows dataloader workers re-import this module
    main()
