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

## Когда VPN снова заработает

Загрузить `data/bundles/cvhack_worker.zip` в `~/work` через JupyterLab, затем в
терминале Jupyter:

```bash
cd ~/work
unzip -o cvhack_worker.zip -d cvhack_worker
cd cvhack_worker
cp data/models/pose/yolov8n_pose_b1_o1_h1m.tpu /auto/cache/"$USER"/
python3 -m pip install --user 'onnxruntime==1.29.0' 'opencv-python-headless==4.11.0.86'
python3 backend/ml/worker/linq_worker.py \
  --model-dir data/models/pose \
  --program /auto/cache/"$USER"/yolov8n_pose_b1_o1_h1m.tpu
```

`pika` и `tpu_pycloud_format` уже есть в окружении Jupyter. После появления
`Listening on RabbitMQ queue cvhack12731.jpeg` можно запустить бэкенд с
`INFERENCE_BACKEND=broker`, `BROKER_URL` и `BROKER_REQUEST_QUEUE` из `.env.example`.
Хост с бэкендом должен иметь собственный маршрут через VPN к `10.0.114.30:5672`.
Для аварийного режима поставить `INFERENCE_FALLBACK=onnx` и держать полную ONNX-модель
в `data/models/pose` на хосте бэкенда.

После сквозной проверки процесс можно запустить в фоне через `nohup`. Прежде чем
считать интеграцию готовой, проверить ответ на реальном JPEG, таймаут при остановке
воркера, переключение на ONNX и задержку через VPN. Этот сетевой тест пока не
выполнен из-за отсутствия VPN.
