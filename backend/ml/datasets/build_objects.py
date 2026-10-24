r"""Build the YOLO dataset for the `objects` model: forklift and pallet truck from LOCO, phone from COCO.

    curl -L -o data/datasets/_dl/loco/loco-all-v1.json \
        https://raw.githubusercontent.com/tum-fml/loco/main/rgb/loco-all-v1.json
    python backend/ml/datasets/build_objects.py \
        --loco data/datasets/_dl/loco/dataset.zip --loco-ann data/datasets/_dl/loco/loco-all-v1.json \
        --coco data/datasets/_dl/coco/annotations_trainval2017.zip \
        --out data/datasets/objects

LOCO (public domain): ~5 100 annotated warehouse frames; images come from go.mytum.de/239870, annotations
from the GitHub repo. Forklifts are scarce there (598 boxes), pallet trucks are not (2 827). The validation
part is a whole subset, so near-identical neighbouring frames never land on both sides of the split.
COCO 2017: every image with a `cell phone` box; images are fetched one by one from images.cocodataset.org.
Neither source labels the other's classes, but forklifts are absent from COCO phone photos and phones
are rare in LOCO, so the missing labels cost little here.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLASSES = ["forklift", "pallet_truck", "phone"]
LOCO_CLASSES = {"forklift": 0, "pallet_truck": 1}
COCO_CLASSES = {"cell phone": 2}
NEGATIVE_SHARE = 0.1  # frames without target objects, as a share of the positive train frames
MAX_SIDE = 640  # = imgsz of training


def yolo_line(cls: int, box: list[float], w: int, h: int) -> str | None:
    x, y, bw, bh = box
    x1, y1, x2, y2 = max(x, 0), max(y, 0), min(x + bw, w), min(y + bh, h)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return f"{cls} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"


def place(src: Path, dst: Path, max_side: int = MAX_SIDE) -> None:
    """YOLO shrinks every image to imgsz anyway, so larger ones are stored already shrunk:
    the dataset fits the OS file cache and training stops waiting for the disk."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    import cv2

    image = cv2.imread(str(src))
    h, w = image.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        image = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dst), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return
    try:
        os.link(src, dst)  # same drive: no second copy of the images
    except OSError:
        shutil.copy2(src, dst)


def coco_samples(data: dict, classes: dict[str, int]) -> dict[int, tuple[dict, list[str]]]:
    """image id → (image record, YOLO label lines) for images with at least one wanted box."""
    wanted = {c["id"]: classes[c["name"]] for c in data["categories"] if c["name"] in classes}
    images = {i["id"]: i for i in data["images"]}
    out: dict[int, tuple[dict, list[str]]] = {}
    for a in data["annotations"]:
        if a["category_id"] not in wanted or a.get("iscrowd"):
            continue
        img = images[a["image_id"]]
        line = yolo_line(wanted[a["category_id"]], a["bbox"], img["width"], img["height"])
        if line:
            out.setdefault(img["id"], (img, []))[1].append(line)
    return out


def write(out: Path, split: str, name: str, src: Path, lines: list[str], counts: Counter) -> None:
    place(src, out / "images" / split / name)
    (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    (out / "labels" / split / Path(name).with_suffix(".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
    counts[split, "images"] += 1
    for line in lines:
        counts[split, CLASSES[int(line.split()[0])]] += 1


def build_loco(archive: Path, annotations: Path, out: Path, val_subset: str, forklift_repeat: int,
               counts: Counter) -> None:
    root = archive.parent / "extracted"
    if not root.exists():
        print(f"unpacking {archive} …", flush=True)
        with zipfile.ZipFile(archive) as z:
            z.extractall(root)
    data = json.loads(annotations.read_text(encoding="utf-8"))
    files = {p.name: p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}}

    def split_of(img: dict) -> str:
        return "val" if f"/{val_subset}/" in img["path"] else "train"

    positives = coco_samples(data, LOCO_CLASSES)
    negatives = [i for i in data["images"] if i["id"] not in positives]
    random.Random(0).shuffle(negatives)
    budget = Counter(split_of(img) for img, _ in positives.values())
    for split in budget:
        budget[split] = int(budget[split] * NEGATIVE_SHARE)
    samples = list(positives.values())
    for img in negatives:
        if budget[split_of(img)] > 0:
            budget[split_of(img)] -= 1
            samples.append((img, []))
    for img, lines in samples:
        src = files.get(Path(img["file_name"]).name)
        if src is None:
            counts["loco", "missing"] += 1
            continue
        write(out, split_of(img), f"loco_{src.name}", src, lines, counts)
        # погрузчиков в 13 раз меньше телефонов: их кадры в обучении повторяются
        if split_of(img) == "train" and any(line.startswith("0 ") for line in lines):
            for k in range(1, forklift_repeat):
                write(out, "train", f"loco_r{k}_{src.name}", src, lines, counts)


def fetch(url: str, dst: Path) -> Path:
    if not dst.exists():
        tmp = dst.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dst)
    return dst


def build_coco(archive: Path, out: Path, counts: Counter, threads: int) -> None:
    cache = archive.parent
    with zipfile.ZipFile(archive) as z:
        for coco_split, split in (("val2017", "val"), ("train2017", "train")):
            print(f"COCO {coco_split}: reading annotations …", flush=True)
            data = json.loads(z.read(f"annotations/instances_{coco_split}.json"))
            samples = list(coco_samples(data, COCO_CLASSES).values())
            del data
            print(f"COCO {coco_split}: {len(samples)} images with phones, downloading …", flush=True)
            (cache / coco_split).mkdir(exist_ok=True)
            with ThreadPoolExecutor(threads) as ex:
                paths = list(ex.map(lambda s, cs=coco_split: fetch(
                    f"http://images.cocodataset.org/{cs}/{s[0]['file_name']}", cache / cs / s[0]["file_name"]), samples))
            for (img, lines), src in zip(samples, paths, strict=True):
                write(out, split, f"coco_{src.name}", src, lines, counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loco", type=Path, required=True, help="LOCO dataset.zip")
    parser.add_argument("--loco-ann", type=Path, required=True, help="LOCO rgb/loco-all-v1.json")
    parser.add_argument("--coco", type=Path, required=True, help="COCO annotations_trainval2017.zip")
    parser.add_argument("--out", type=Path, default=Path("data/datasets/objects"))
    parser.add_argument("--loco-val-subset", default="subset-4")
    parser.add_argument("--forklift-repeat", type=int, default=4)
    parser.add_argument("--threads", type=int, default=32)
    args = parser.parse_args()
    counts: Counter = Counter()
    build_loco(args.loco, args.loco_ann, args.out, args.loco_val_subset, args.forklift_repeat, counts)
    build_coco(args.coco, args.out, counts, args.threads)
    out = args.out.resolve()
    (args.out / "data.yaml").write_text(
        f"path: {out.as_posix()}\ntrain: images/train\nval: images/val\n"
        f"names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES)), encoding="utf-8")
    for split in ("train", "val"):
        print(split, {k: counts[split, k] for k in ["images", *CLASSES]})
    if counts["loco", "missing"]:
        print("LOCO images not found in the archive:", counts["loco", "missing"])
    print(args.out / "data.yaml")


if __name__ == "__main__":
    main()
