# JPEG → LinQ TPU через RabbitMQ

`linq_worker.py` запускается в Jupyter LinQ. Это обычный процесс на CPU: он получает
JPEG из нашей очереди, готовит тензор, отправляет `PyTask` в общую `tpu.direct/input`,
декодирует ответ и возвращает JSON с рамками и 17 ключевыми точками. Прямой доступ
к `/dev/tpu*` в нашем Jupyter не требуется.

Сообщения в нашей очереди: тело запроса — JPEG; `reply_to` — временная очередь
клиента; `correlation_id` — идентификатор кадра. Тело ответа — JSON в формате
`DetectResult` либо `{"error":"..."}`. Один воркер обрабатывает кадры последовательно;
истёкшие запросы клиента автоматически удаляются из очереди по TTL.

## Подготовка без VPN

Из корня рабочей копии `cvhack-ml`:

```bash
python3 backend/ml/worker/package.py data/models/pose data/bundles/cvhack_worker.zip
```

Архив содержит код воркера, `meta.json`, ONNX-хвост и скомпилированную `.tpu`.
Он лежит в игнорируемой Git папке `data/`.

Проверка обработки JPEG без TPU (в окружении с `pika`, OpenCV и ONNX Runtime):

```bash
python backend/ml/worker/smoke_local.py data/models/pose \
  data/calib/coco128/images/train2017/000000000294.jpg
```

При наличии локального RabbitMQ можно также запустить `smoke_broker.py` с URL
брокера: он проверяет реальный обмен JPEG/JSON, ответ на битый кадр, таймаут
и переход на ONNX. 24.10.2026 такой тест прошёл на кадре COCO: один человек,
уверенность 0,862. Это проверка нашего протокола с CPU-эквивалентом TPU-части;
сетевая проверка с LinQ остаётся после восстановления VPN.

## Запуск на стенде

Бандл уже развёрнут в `~/work/cvhack_worker` (код, `meta.json`, ONNX-хвост, ссылка на
`/auto/cache/$USER/yolov8n_pose_b1_o1_h1m.tpu`). Чтобы развернуть заново, загрузить
`data/bundles/cvhack_worker.zip` в `~/work` и распаковать его в `cvhack_worker`. Затем установить
`onnxruntime==1.29.0` и `opencv-python-headless==4.11.0.86` через `pip install --user` и скопировать
`.tpu` в `/auto/cache/$USER/`. `pika` и `tpu_pycloud_format` уже есть в окружении Jupyter.

Воркеры запускаются в фоне, по умолчанию четыре на одну очередь, и гоняют на каждом кадре все модели
из `data/models` (переменная `MODELS` сужает набор). Общий TPU стенда обслуживает
запросы параллельно: один воркер даёт около 3 кадр/с, четыре — около 10.

```bash
docker compose exec -T linq-vpn ljup sh 'sh ~/work/cvhack_worker/backend/ml/worker/start_workers.sh'
```

Скрипт перезапускает воркеры и печатает `Listening on RabbitMQ queue cvhack12731.jpeg` для
каждого. Логи пишутся в `~/work/cvhack_worker/logs/`. Процессы живут, пока работает сервер
Jupyter; после его перезапуска скрипт нужно выполнить снова.

## Бэкенд

VPN поднят только в контейнере `linq-vpn`. Он пробрасывает RabbitMQ стенда остальным
контейнерам как `linq-vpn:5672`; этот адрес — `BROKER_URL` по умолчанию в `docker-compose.yml`.
В `.env`:

```bash
INFERENCE_BACKEND=broker
INFERENCE_FALLBACK=onnx      # полная ONNX-модель и meta.json в data/models/pose
INFERENCE_CONCURRENCY=4      # до 4 кадров в полёте, по одному на камеру
```

```bash
docker compose --profile linq up -d linq-vpn
docker compose up -d
```

При `INFERENCE_CONCURRENCY` больше 1 кадр камеры, у которой предыдущий кадр ещё в работе,
пропускается (метрика `inference_dropped_total{reason="busy"}`). Так в модель всегда идёт
свежий кадр, а очередь не копится. Кадры крупнее 640 px клиент уменьшает до отправки.
Если стенд не ответил три раза подряд, кадры 30 секунд идут в ONNX на CPU, затем снова в брокер.

С двумя моделями (pose и objects) обе программы уходят на TPU одновременно. Замер 24.10.2026, 4 камеры:
4,3 кадр/с, средняя задержка 835 мс (TPU 532, сеть и брокер 266). Событие «опасное сближение» на
`cam-03` подтверждено через 1,6 с после начала эпизода.

Замер только с pose, 24.10.2026: 4 камеры по 5 кадр/с, 4 воркера. Через TPU обработано 6,6 кадр/с, без ошибок.
Средняя задержка 495 мс: TPU вместе с общей очередью стенда — 358, сеть VPN и брокер — 118,
пред- и постобработка — около 20. Событие `in_zone` дошло до браузера через 0,58 с после кадра.
TPU и ONNX на CPU дают совпадающие рамки и уверенности (±0,05).
