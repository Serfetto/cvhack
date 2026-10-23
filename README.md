# Видеоконтроль нарушений ТБ на LinQ TPU

Кейс LinQ, хакатон «Открой Моспром». Сервис принимает видео с камер, находит нарушения техники безопасности
нейросетями на российском ускорителе **LinQ TPU** и за секунды оповещает диспетчера и мастера: кадр с рамкой,
клип, камера, время, тип нарушения. Каждое нарушение даёт ровно одно оповещение. Журнал хранит историю
и действия людей, дашборд показывает, где и когда нарушают чаще.

Архитектура и план работ: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/plans/](docs/plans/README.md).

## Запуск

```bash
cp .env.example .env            # необязательно: без .env работают значения по умолчанию
docker compose up -d --build
python backend/server/tools/smoke.py           # сквозная проверка: вход → событие по WebSocket → статус → статистика
```

Без роликов и без моделей всё уже работает: контейнер `cams` крутит тестовую таблицу в RTSP, а детектор
`synthetic` водит по кадру «человека», который заходит в опасную зону. Свои ролики кладутся в
`data/demo_videos/cam01.mp4` … `cam04.mp4` (имя файла = путь RTSP), модели ML — в `data/models/<имя>/`.

| Что | Адрес |
|---|---|
| Шлюз (UI и API) | http://localhost:8080 |
| Swagger сервисов | http://localhost:8080/api/{auth,config,events,inference,ingest,analytics,notifications}/docs |
| WebSocket событий | ws://localhost:8080/ws?access_token=… |
| Живое видео (HLS) | http://localhost:8080/live/cam01/index.m3u8 |
| Снапшоты и клипы | http://localhost:8080/media/linq/… |
| Grafana (FPS, задержки) | http://localhost:3000 (дашборд «LinQ: конвейер видеоаналитики») |
| Prometheus | http://localhost:9090 |
| MinIO | http://localhost:9001 (minioadmin / minioadmin) |
| Traefik | http://localhost:8081 |

**Демо-пользователи** (пароль `demo`, задаётся `DEMO_PASSWORD`): `admin`, `hse` (охрана труда),
`master` (мастер цеха №1, видит только свой участок), `operator` (диспетчер), `manager` (руководитель),
`auditor` (юрист).

## Сервисы

```
камера → ingest → frames:{shard} → inference (TPU) → detections → analytics → violations → events → events.* → notifications → браузер
                                                                                     ↘ MinIO (снапшот)  ↘ clips:requests → ingest → MinIO (клип)
```

| Сервис | Что делает | Ключевые эндпоинты |
|---|---|---|
| `auth` | Пользователи, роли, JWT RS256 (access 15 мин + одноразовый refresh), профиль, подписки | `POST /login`, `POST /refresh`, `GET/PATCH /me`, `GET/POST/PATCH /users`, `GET /.well-known/jwks.json` |
| `camera` | Площадки → участки → камеры, зоны-полигоны, правила с параметрами и расписанием. Публикует конфигурацию в Redis | `GET /tree`, CRUD `/sites` `/areas` `/cameras` `/cameras/{id}/zones` `/cameras/{id}/rules`, `GET /cameras/{id}/snapshot`, `GET /scenarios` |
| `ingest` | Воркер на камеру: RTSP / файл по кругу / папка кадров, прореживание до FPS анализа, JPEG, кольцевой буфер 20 с, клипы MP4 (H.264) | `GET /streams`, `POST /streams/{cam}/restart` |
| `inference` | Шлюз к TPU: кадры → детекции. Бэкенды `pytpu`, `onnx`, `remote`, `synthetic`, аварийное переключение | `GET /models`, `POST /benchmark`, `GET /benchmarks`, `POST /detect` |
| `analytics` | Трекинг (ByteTrack), сценарии-плагины, конечный автомат подтверждения, склейка треков, доказательства в MinIO | `GET /scenarios`, `GET /state` |
| `events` | Журнал, статусы и история действий, статистика, CSV, эскалация, приём нарушений по HTTP | `GET /events`, `GET /events/{id}`, `PATCH /events/{id}/status`, `GET /events/export.csv`, `GET /stats/*` |
| `notifications` | WebSocket с фильтром по роли и участкам, Telegram (если задан токен бота) | `WS /ws` |

Горячий путь (`ingest → inference → analytics → events → notifications`) идёт через Redis Streams с
consumer groups: сообщение подтверждается только после обработки, рестарт любого сервиса событий не теряет.
Конфигурацию камер горячий путь берёт из Redis, а не из REST: если `camera`, `auth` или БД лягут, детекция
продолжит работать.

### WebSocket `/ws`

```jsonc
{"type": "hello", "user": {"id": 4, "username": "operator", "role": "operator", ...}}
{"type": "event.created",   "event": EventOut, "notify": true}   // notify — совпало с подписками пользователя
{"type": "event.updated",   "event": EventOut, "notify": true}   // статус, окончание, готов клип
{"type": "event.escalated", "event": EventOut, "notify": true}   // не принято за N минут
{"type": "ping", "ts": 1761217513.4}                            // раз в 25 с; клиент может слать "ping"
```

С неверным или истёкшим токеном рукопожатие отклоняется (HTTP 403) — клиенту нужно обновить токен и переподключиться.
`EventOut` — `backend/server/libs/common/common/messages.py`. Координаты (`bbox`, полигоны зон) нормированы к 0..1.
Статусы: `new → confirmed | false | forwarded → resolved` (допустимые переходы — поле `allowed_statuses`
в карточке события).

### Фильтры журнала и статистики

`GET /api/events/events?camera_id=cam-01&camera_id=cam-02&area_id=1&scenario=fall&severity=critical&status=new&from=2026-10-24T00:00:00%2B03:00&to=…&page=1&page_size=50&sort=-started_at`

Те же параметры принимают `/events/export.csv` и `/stats/summary`, `/stats/by-type`, `/stats/by-camera`,
`/stats/by-area`, `/stats/heatmap` (день недели × час), `/stats/trend` (по дням), `/stats/precision`
(доля подтверждённых операторами — онлайн-оценка точности по сценариям).

## Инференс: CPU, TPU и стенд LinQ

Код сервиса один, меняется только `INFERENCE_BACKEND`:

| Значение | Где считается | Когда |
|---|---|---|
| `synthetic` | без нейросети, фейковый человек | разработка конвейера и UI |
| `onnx` | CPU, модели из `data/models/<имя>/` | разработка, аварийный режим |
| `pytpu` | LinQ TPU (`/dev/tpu*`) | только на стенде |
| `remote` | `tpu-worker` на стенде по HTTP | основной режим A1 |

`INFERENCE_FALLBACK=onnx` — если основной бэкенд трижды подряд падает, кадры идут в аварийный, через 30 с
повторная попытка. Активный бэкенд виден в `GET /api/inference/models` и в метрике `inference_fallback_active`.

**tpu-worker на стенде** — это тот же `inference`, только без очередей:

```bash
pip install ./backend/server/libs/common -r backend/server/services/inference/requirements.txt
cd backend/server/services/inference
INFERENCE_BACKEND=pytpu CONSUME=false MODELS_DIR=/path/to/models uvicorn app.main:app --host 0.0.0.0 --port 8000
# у нас: INFERENCE_BACKEND=remote REMOTE_URL=http://<адрес стенда>:8000 INFERENCE_FALLBACK=onnx
```

Режим A2 (стенд сам читает наш Redis): на стенде `CONSUME=true REDIS_URL=redis://:<пароль>@<наш VPN IP>:6379/0`.
Режим B (всё на стенде): `python backend/server/tools/replay.py <видео|rtsp> --detector pytpu --camera cam-01 --post http://<vps>:8080/api/events --token <INGEST_TOKEN>`.

**Контракт для ML** — `backend/server/services/inference/detectors/local.py` (функции `ml_runtime`) и
`backend/server/services/inference/backends/base.py` (`Backend`, `ModelSpec`, `meta.json`).

## Как добавить

**Камеру** — в UI или `POST /api/config/cameras` (`source_type`: `rtsp` | `file` | `images`). `ingest` подхватит
её без перезапуска. Стартовый набор камер — `backend/server/infra/cameras.yml`.

**Новый тип нарушения** — файл в `backend/server/services/analytics/scenarios/`:

```python
from scenarios.base import ScenarioBase, Scene, Severity, Track, register

@register
class PhoneScenario(ScenarioBase):
    code = "phone"
    title = "Телефон в рабочей зоне"
    requires = {"pose", "objects"}
    severity = Severity.MEDIUM
    params_schema = {"type": "object", "properties": {
        "max_dist": {"type": "number", "default": 0.5, "title": "Телефон у руки, в ростах"},
        "confirm_s": {"default": 3.0},
    }}

    def check(self, track: Track, scene: Scene, params: dict) -> float:
        ...  # 0..1 — «нарушение на этом кадре»
```

Сценарий сразу появляется в `GET /api/config/scenarios`, форма параметров в UI строится по `params_schema`.
Подтверждение во времени (`confirm_s`, `confirm_ratio`), окончание (`release_s`), подавление повторов
(`cooldown_s`) и склейку треков после перекрытия делает каркас — в сценарии об этом думать не нужно.

Проверить сценарий на ролике без Docker:

```bash
python backend/server/tools/replay.py fall01.mp4 --detector onnx --scenario fall --save-detections fall01.jsonl
python backend/server/tools/replay.py fall01.mp4 --detections fall01.jsonl --scenario fall --params '{"confirm_s": 1.0}'
```

## Демо-история для дашборда

`POST /api/events/demo/seed {"days": 14, "per_day": 20}` (роль `admin`) создаёт события с пометкой
`demo=true`; `DELETE /api/events/demo` удаляет их. Фильтр `?demo=false` показывает только реальные события.

## Разработка

```bash
uv venv --python 3.12 .venv
cd backend/server
uv pip install --python ../../.venv -e libs/common -r services/analytics/requirements.txt -r services/inference/requirements.txt \
    -r services/auth/requirements.txt -r services/camera/requirements.txt pytest fakeredis
../../.venv/Scripts/python -m pytest tests     # Linux/macOS: ../../.venv/bin/python
```

Сервис можно запустить локально против инфраструктуры из compose:
`cd backend/server/services/events && DATABASE_URL=postgresql+asyncpg://linq:linq@localhost:5432/linq REDIS_URL=redis://:linq-redis@localhost:6379/0 MINIO_ENDPOINT=localhost:9000 AUTH_JWKS_URL=http://localhost:8080/api/auth/.well-known/jwks.json uvicorn app.main:app --port 8003`.

```
backend/
  server/                          бэкенд
    libs/common/                   контракты (messages.py), шина Redis, JWT, метрики, логи, конфигурация камер
    services/<сервис>/app/         FastAPI-приложение сервиса
    services/analytics/engine/     трекинг, конечный автомат, движок (без ввода-вывода)
    services/analytics/scenarios/  сценарии нарушений (плагины, пишет ML)
    services/inference/detectors/  synthetic / local (onnx, pytpu) / remote / fallback
    infra/                         Traefik, MediaMTX, Prometheus, Grafana, cameras.yml
    tools/                         replay.py (видео → события офлайн), smoke.py (сквозная проверка)
    tests/
  ml/                              датасеты, обучение, экспорт, компиляция под TPU, бенчмарк, метрики
frontend/                          SPA (React + Vite)
docs/                              архитектура и планы
data/                              (не в git) demo_videos/, models/, calib/, eval/
docker-compose.yml                 вся система одной командой
```

## Лицензии

Ultralytics YOLO — AGPL-3.0 (для продукта нужна коммерческая лицензия или Apache-2.0 модели).
Датасеты и их лицензии перечислены в ARCHITECTURE §8.
