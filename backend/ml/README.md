# ML: модели и их подготовка к LinQ TPU

План работ — [docs/plans/ml.md](../../docs/plans/ml.md), архитектура — [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) §6–8.

## Что где лежит

| Папка | Что |
|---|---|
| `datasets/` | Скрипты загрузки и объединения датасетов, разметка интервалов нарушений (`data/eval/labels.csv`) |
| `training/` | Обучение и дообучение YOLO |
| `export/` | `export_onnx.py`, обрезка головы (`cut_head.py`) |
| `compile/` | `Dockerfile` (python 3.12.11 + колёса `tpu_framework`), `compile_tpu.py` (квантование, компиляция O5 → O1) |
| `benchmark/` | `bench_tpu.py` / ноутбук для стенда; JSON-отчёты — в `benchmark/out/` (их показывает `GET /api/inference/benchmarks`) |
| `eval/` | Событийные метрики на размеченных роликах: precision, recall, ложные тревоги в час, задержка |

Большие файлы (датасеты, `.pt`, `.onnx`, `.tpu`) в git не кладём: они в `data/` в корне репозитория
(`data/models/<имя>/` — модель + `meta.json`, `data/calib/`, `data/eval/`, `data/demo_videos/`).

## Код ML, который работает внутри сервисов

Эти модули импортируют сервисы бэкенда, поэтому они лежат рядом с ними:

| Что | Где | Контракт |
|---|---|---|
| Пре- и постпроцессинг | `backend/server/services/inference/ml_runtime/` | `preprocess`, `postprocess_pose`, `postprocess_detect` — см. docstring `detectors/local.py` |
| Бэкенды `onnx`, `pytpu` | `backend/server/services/inference/backends/onnx.py`, `pytpu.py` | `Backend`, `ModelSpec`, формат `meta.json` — `backends/base.py` |
| Сценарии нарушений | `backend/server/services/analytics/scenarios/<код>.py` | `ScenarioBase`, `Track`, `Scene`, `@register` — `scenarios/base.py` |

Проверка сценария на ролике без Docker (детекции можно сохранить и потом быстро перебирать пороги):

```bash
python backend/server/tools/replay.py fall01.mp4 --detector onnx --scenario fall --save-detections fall01.jsonl
python backend/server/tools/replay.py fall01.mp4 --detections fall01.jsonl --scenario fall --params '{"confirm_s": 1.0}'
```

tpu-worker на стенде LinQ — это inference-сервис с `INFERENCE_BACKEND=pytpu CONSUME=false` (см. корневой README).
