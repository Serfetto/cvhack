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

## Первый запуск pose на LinQ

В этой поставке стенда Jupyter не видит `/dev/tpu*`; инференс выполняет облачный воркер через RabbitMQ. SDK `2026.9.45` работает под Linux x86_64 и Python 3.12.11. Его публичный архив указан в `artifacts/Процедура_подготовки_и_инференса_сетей_на_LinQ_TPU.pdf`. Распаковать архив вне git и собрать контейнер с корня распакованной папки `tpu_framework`:

```bash
docker build --platform linux/amd64 -f backend/ml/compile/Dockerfile -t cvhack-linq:2026.9.45 /path/to/tpu_framework
```

Скачать официальные веса `yolov8n-pose.pt` из [Ultralytics assets](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n-pose.pt) в `data/models/pose/`. Модель Ultralytics распространяется по AGPL-3.0; проверить условия использования перед коммерческим развёртыванием.

```bash
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/export/export_onnx.py data/models/pose/yolov8n-pose.pt data/models/pose/yolov8n-pose.onnx
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/export/cut_head.py data/models/pose/yolov8n-pose.onnx --out-dir data/models/pose
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/export/verify_split.py data/models/pose data/calib --limit 20
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/compile/compile_tpu.py data/models/pose data/calib --limit 128
```

Для калибровки нужны настоящие JPEG/PNG с людьми в `data/calib/`. COCO128 годится для первой технической проверки; для итоговой оценки взять отдельные кадры с камер, похожих на целевую сцену, и не использовать оценочные ролики при калибровке. Результат в `data/models/pose/` включает полную ONNX-модель, TPU-часть, ONNX-хвост и `meta.json`. Файл `.tpu` загружается в персональный `/auto/cache/<логин>/` на стенде; Jupyter-клиент отправляет путь к нему через брокер `tpu.direct` с ключом `input`.

Упрощение ONNX-графа выключено: в `ultralytics==8.4.0` оно удаляет некоторые имена узлов, перечисленные в PDF SDK. Текущий скрипт режет граф на трёх выходах ветвей bbox, score и keypoints перед DFL/декодированием; корректность среза проверяется `verify_split.py` на реальных кадрах.

Числа из `docs/stand.md` относятся к примеру ResNet50 и не являются скоростью pose. Очередь и 16 TPU общие для всех команд, поэтому задержку нужно мерить от отправки до ответа, явно включая ожидание в очереди.
