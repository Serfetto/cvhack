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

Готовые модели лежат в git: `data/models/pose/` и `data/models/objects/` — `meta.json`, полная ONNX,
ONNX-хвост, программа `.tpu` (у objects ещё веса `.pt`). Остальное в `data/` в git не кладём: датасеты,
промежуточные файлы компиляции, `data/calib/`, `data/eval/`, `data/demo_videos/`.

## Код ML, который работает внутри сервисов

Эти модули импортируют сервисы бэкенда, поэтому они лежат рядом с ними:

| Что | Где | Контракт |
|---|---|---|
| Пре- и постпроцессинг позы | `backend/server/services/inference/ml_runtime/` | `preprocess`, `postprocess_pose` — см. docstring `detectors/local.py` |
| ONNX-бэкенд | `backend/server/services/inference/backends/onnx.py` | `Backend`, `ModelSpec`, формат `meta.json` — `backends/base.py` |
| Брокер LinQ | `backend/server/services/inference/detectors/broker.py`, `backend/ml/worker/` | JPEG → Jupyter → TPU → JSON; [инструкция](worker/README.md) |
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

Первый запуск pose на TPU выполнен. На проверочном кадре CPU и TPU нашли одного человека; уверенность — 0,862 и 0,861. Из 12 последовательных запросов медианная задержка от отправки до ответа — 355 мс. TPU общие для команд, поэтому это не чистое время вычисления. Калибровка была на 32 кадрах, компиляция — O1; программа отдаёт три тензора.

Конвейер работает на TPU сквозным образом: кадры камер идут через детектор `broker` и RabbitMQ стенда на воркеры в Jupyter (`worker/`), события создаются по детекциям TPU. Запуск и замеры — в [worker/README.md](worker/README.md).

`yolov8n-pose` пропускает мелких и далёких людей: на пешеходном ролике из сэмплов OpenCV модель находит 2–3 человека из 7. На CPU результат тот же, так что дело в модели, а не в TPU. Нужна модель крупнее или дообучение.

## Модель objects: погрузчик, рохля, телефон

Вторая модель нужна сценариям `proximity` (сближение с техникой) и `phone` (телефон в руке). Она
работает на каждом кадре вместе с pose: воркер отправляет обе программы на TPU одновременно.

| Класс | Данные | В обучении | В проверке |
|---|---|---|---|
| `forklift` | [LOCO](https://github.com/tum-fml/loco), public domain | 479 рамок, кадры повторены ×4 | 119 |
| `pallet_truck` | LOCO | 2 268 | 559 |
| `phone` | COCO 2017, класс `cell phone` | 6 373 | 261 |

Для проверки из LOCO отложен целый `subset-4`, поэтому соседние почти одинаковые кадры не попадают
одновременно в обучение и проверку.

```bash
# данные (~1,8 ГБ): картинки LOCO, разметка LOCO из GitHub, разметка COCO; фото COCO качает скрипт
curl -L -o data/datasets/_dl/loco/dataset.zip https://go.mytum.de/239870
curl -L -o data/datasets/_dl/loco/loco-all-v1.json https://raw.githubusercontent.com/tum-fml/loco/main/rgb/loco-all-v1.json
curl -L -o data/datasets/_dl/coco/annotations_trainval2017.zip http://images.cocodataset.org/annotations/annotations_trainval2017.zip
python backend/ml/datasets/build_objects.py --loco data/datasets/_dl/loco/dataset.zip \
  --loco-ann data/datasets/_dl/loco/loco-all-v1.json --coco data/datasets/_dl/coco/annotations_trainval2017.zip

# обучение на GPU: torch под CUDA 12.8 (RTX 50xx), ultralytics==8.4.0
python backend/ml/training/train_objects.py --weights data/weights/yolov8s.pt

# дальше тот же путь, что у pose; калибровка — смесь кадров LOCO и COCO из обучения (data/calib/objects)
mkdir -p data/models/objects
python backend/ml/export/export_onnx.py data/runs/objects/weights/best.pt data/models/objects/yolov8s-objects.onnx
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/export/cut_head.py data/models/objects/yolov8s-objects.onnx --out-dir data/models/objects --name objects
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/export/verify_split.py data/models/objects data/calib/objects --limit 20
docker run --rm --platform linux/amd64 -v "$PWD:/work" cvhack-linq:2026.9.45 \
  python backend/ml/compile/compile_tpu.py data/models/objects data/calib/objects --limit 160
```

У detect-головы граф режется на двух ветвях — распределение рамок `Concat` и логиты классов `Concat_1`;
DFL, декодирование и сигмоида остаются в ONNX-хвосте. `postprocess_detect` совпадает с `ultralytics`
до рамки (35 кадров, 204 детекции).

Результат (лучшая эпоха 19 из 34, ранняя остановка; проверка — другой склад LOCO и фото COCO):

| Класс | Precision | Recall | mAP50 |
|---|---|---|---|
| `forklift` | 0,24 | 0,51 | 0,36 |
| `pallet_truck` | 0,61 | 0,20 | 0,28 |
| `phone` | 0,56 | 0,52 | 0,53 |

Модель путает погрузчик и рохлю, но для сценария `proximity` это одна «техника». На камерах сверху
техника находится не на каждом кадре, поэтому сценарий помнит её `memory_s` секунд.

Квантование. С калибровкой по умолчанию логиты классов на TPU коррелировали с float-моделью на 0,65,
и TPU не находил технику там, где её видел CPU. `--activation-percentile 99.9` отсекает редкие
экстремальные активации; корреляция стала 0,98, уверенности на TPU лишь немного ниже CPU. Перебирать
настройки удобно без стенда: `QuantizedModel.load(qm).as_torch_graph().gm(round(x·127))` воспроизводит
выходы TPU.

Сервис TPU кэширует программы по пути: файл, перезаписанный под тем же именем, не подхватывается.
Поэтому `compile_tpu.py` добавляет в имя программы хэш её содержимого.

## Экспериментальные сценарии падения и неподвижности

`fall` использует сырые детекции позы до ByteTrack: при падении трекер может на несколько кадров
потерять человека, а горизонтальную позу увидеть всего один раз. Сценарий требует, чтобы рядом
в последние 2 с была вертикальная поза, а новая поза стала горизонтальной и опустилась вниз.
Он создаёт обычное событие аналитики с рамкой человека. `immobile` срабатывает, если один
отслеживаемый человек лежит почти без движения не менее 4 с и модель видит его без длинных
пропусков. Оба правила доступны в каталоге; для новой БД они включены на `cam-03` в
`backend/server/infra/cameras.yml`. В уже созданной БД правила нужно добавить через UI/API,
поскольку YAML применяется только при первой инициализации.

Локальная проверка без контейнеров, с полной ONNX-моделью:

```bash
python backend/server/tools/replay.py data/models/test.mov \
  --camera cam-03 --detector onnx --models pose --tracker bytetrack --fps 5
```

На `test.mov` (локальный файл, не в git) правило `fall` создаёт одно событие на 10,01-й секунде.
`immobile` на этом ролике не срабатывает: после падения модель недостаточно долго видит лежащего
человека. Это эвристики по позе, а не отдельная обученная модель падений или медицинский диагноз;
качество на других роликах пока не измерено.
