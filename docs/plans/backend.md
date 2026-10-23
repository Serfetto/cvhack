# План бэкенд-программиста

**Цель роли.** Система из микросервисов поднимается одной командой. Кадр с камеры за ≤ 3 с превращается в событие в журнале и в оповещение в браузере. Конфигурация камер и зон меняется на лету, статистика доступна через API.

Основа: [ARCHITECTURE.md](../ARCHITECTURE.md) — разделы 3–5, 9–11. Общая шкала: [README.md](README.md).

## Зона ответственности

| Что | Где |
|---|---|
| Монорепо, `docker-compose.yml`, `.env.example`, инфраструктура | корень, `infra/` |
| Общая библиотека: сообщения, шина Redis, JWT, метрики, логи | `libs/common/` |
| `auth`, `camera`, `ingest`, `events`, `notifications` | `services/*` |
| `inference-service`: обвязка очередей вокруг `ml_runtime` и бэкендов от ML | `services/inference/app/` |
| `analytics-service`: трекинг, `Track` / `Scene`, реестр сценариев, конечный автомат, склейка треков, снапшоты | `services/analytics/` (кроме `scenarios/`) |
| Gateway, Prometheus и Grafana, деплой на VPS + OpenVPN | `infra/` |
| Инструменты: прогон видео через конвейер, seed-данные | `tools/` |

## Приоритеты

- **MUST:** сквозной путь `ingest → inference → analytics → events → notifications` · вход в систему · журнал с фильтрами · TPU в конвейере
- **SHOULD:** `camera-service` с зонами и горячей перезагрузкой · статистика · клипы · роли и участки · метрики и бенчмарк
- **COULD:** эскалация · Telegram · экспорт в PDF

## Стек

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + asyncpg, redis-py (asyncio), `supervision` (ByteTrack), `shapely`, PyAV / OpenCV, `prometheus-client`, `structlog`, MinIO SDK. Зависимости — `uv`.

Для хакатона допустимо создавать таблицы через `create_all` при старте. Alembic — только если останется время.

---

## Блок 0. Сейчас → 23.10 18:00 (ЧП-1)

- [ ] **Публичный репозиторий на GitHub**:
  - структура как в ARCHITECTURE §11
  - `.gitignore`: `data/`, `*.tpu`, `*.onnx`, `*.pt`, `.env`
  - README-заглушка

  Ссылку — капитану: после ЧП-1 она должна быть в ЛК.
- [ ] **`docker-compose.yml` с инфраструктурой**:
  - `postgres:16`, `redis:7`, `minio`, `bluenviron/mediamtx`, `traefik:v3`, `prometheus`, `grafana`
  - контейнер `cams`: ffmpeg крутит видео из `data/demo_videos/*.mp4` в `rtsp://mediamtx:8554/camNN`
- [ ] **`libs/common`** (к 15:30 — от него зависят все):
  - `messages.py`: `FrameMsg`, `DetectionsMsg` (`Person`, `Obj`), `ViolationMsg`, `EventOut`, `WsMessage` — поля по ARCHITECTURE §9.2, координаты нормированы 0..1
  - `bus.py`: `publish(stream, msg, maxlen)`, `consume(stream, group, handler)` с `XREADGROUP` / `XACK`, перечитывание непрочитанного при старте, `pubsub(channel)`
  - `auth.py`: проверка JWT (RS256), зависимость FastAPI `current_user(roles=...)`
  - `metrics.py` (`/metrics`), `logging.py`, `settings.py` (pydantic-settings)
- [ ] **Шаблон сервиса**: FastAPI + Dockerfile + `/health` + `/metrics`.
- [ ] **Заглушки всех сервисов** с эндпоинтами из ARCHITECTURE §5, чтобы фронтенд видел Swagger (`/docs`).
- [ ] **До 16:00 согласовать с фронтендом** список эндпоинтов, формат WS и форматы статистики.

**Готово, если** `docker compose up` поднимает инфраструктуру и заглушки, Swagger каждого сервиса открывается через gateway, MediaMTX отдаёт демо-поток.

---

## Блок 1. 23.10 18:00 → 24.10 11:00 (ЧП-2): сквозной путь на CPU

- [ ] **`ingest-service`**:
  - воркер на каждую камеру, источники `rtsp://`, файл (по кругу), папка изображений
  - прореживание до `analysis_fps`, JPEG (качество 85, длинная сторона ≤ 1280)
  - `SET frame:{cam}:{seq} EX 60` + `XADD frames:{shard} MAXLEN ~ 500`
  - переподключение с увеличивающейся паузой, метрики `ingest_fps`, `ingest_decode_seconds`
  - конфигурация камер на этом этапе — из YAML (`infra/cameras.yml`), пока нет `camera-service`
- [ ] **`inference-service`**:
  - консьюмер `frames:{shard}` → `ml_runtime` + бэкенд из `INFERENCE_BACKEND` → `XADD detections`
  - метрики по стадиям (`queue`, `pre`, `infer`, `post`)
  - если кадр старше 2 с — пропускаем: под нагрузкой важнее свежие кадры, чем полные
  - пока нет `OnnxBackend` от ML (ожидается к 23:00) — работаем на фейковом бэкенде с пустыми детекциями
- [ ] **`analytics-service`** — каркас:
  - `Track` (id, история боксов и ключевых точек за 10 с, скорость, рост в пикселях) и `Scene` (камера, зоны в `shapely`, объекты кадра, время)
  - ByteTrack по каждой камере (`supervision.ByteTrack`)
  - реестр `@register`, протокол `Scenario` (ARCHITECTURE §7.3)
  - конечный автомат `IDLE → CANDIDATE → ACTIVE → COOLDOWN` на ключ `(camera, track, scenario)`, параметры `confirm_s`, `confirm_ratio`, `release_s`, `cooldown_s`
  - склейка треков: новый трек ближе 0,1 кадра к пропавшему в течение 5 с с тем же сценарием → то же событие
  - доказательство: берём кадр из Redis → рисуем рамку → MinIO `events/YYYY/MM/DD/{event_id}.jpg` + SHA-256
  - `XADD violations` (`started` / `ended`)
  - для проверки до ML — сценарий-заглушка `in_zone` («человек в полигоне ≥ 2 с»)
- [ ] **До 02:00 отдать ML** протокол `Scenario`, `Track`, `Scene` и `tools/replay.py` (прогоняет видеофайл через конвейер и печатает события с таймкодами).
- [ ] **`event-service`**:
  - консьюмер `violations` → таблица `events`
  - `GET /events` (фильтры: камера, участок, зона, тип, статус, период; пагинация), `GET /events/{id}` (presigned URL снапшота)
  - `PATCH /events/{id}/status` + запись в `event_actions`
  - `PUBLISH events.created` / `events.updated`
- [ ] **`notification-service`**: WebSocket `/ws?token=…`, подписка на Redis Pub/Sub, рассылка `{type, event}`, keep-alive.
- [ ] **`auth-service`**:
  - `POST /login`, `POST /refresh`, `GET /me`, JWKS
  - пароли — argon2
  - seed: по пользователю на каждую роль (`admin`, `hse`, `master`, `operator`, `manager`, `auditor`)
- [ ] **24.10 09:00 — интеграция с фронтом** на общем стенде (локально или на VPS).

**Готово к ЧП-2, если** демо-видео с падением даёт событие в WS ≤ 3 с после падения, событие есть в журнале со снапшотом, повтора нет.

---

## Блок 2. 24.10 11:00 → 18:00 (ЧП-3)

- [ ] **TPU в конвейере (вместе с ML)** в выбранном режиме:
  - **A1:** `RemoteBackend` ходит на `tpu-worker` по HTTP или WebSocket (keep-alive, тайм-аут 500 мс, при ошибке — onnx)
  - **A2:** `tpu-worker` сам подключается к нашему Redis; открыть порт Redis только в VPN-интерфейс и задать пароль
  - **B:** приём `violations` со стенда через HTTP-эндпоинт `event-service`
- [ ] **VPS** (Ubuntu): docker compose, OpenVPN по инструкции из `artifacts/`:
  ```bash
  sudo nmcli connection modify Hakathon ipv4.never-default yes ipv4.routes "10.0.114.0/24" ipv4.dns-search "~lin-q.ru"
  ```
- [ ] **`camera-service`**:
  - CRUD `sites` / `areas` / `cameras` / `zones` / `rules` (полигоны — JSONB, нормированные координаты)
  - расписание и `valid_until` у правил
  - `GET /cameras/{id}/snapshot` — последний кадр из Redis
  - `GET /scenarios` — каталог, который `analytics` при старте кладёт в Redis
  - `PUBLISH config.updated`; `analytics` и `ingest` перечитывают конфигурацию без перезапуска
  - YAML из блока 1 становится seed-данными
- [ ] **`event-service`, статистика**:
  - `/stats/by-type`, `/stats/by-camera`, `/stats/heatmap` (час × день недели), `/stats/trend` (по дням), `/stats/precision` (доля `confirmed` среди отмеченных)
  - `GET /events/export.csv`
- [ ] **Клипы:** `event-service` → `clip.requested` → `ingest` вырезает из кольцевого буфера ±5 с → MP4 в MinIO → `clip.ready` → `clip_key`.
- [ ] **Роли и участки:** проверка прав в REST; в WS мастер получает только свои участки.

**Готово к ЧП-3, если** конвейер идёт через TPU; зона, нарисованная в UI, меняет поведение без перезапуска; дашборд получает реальные агрегаты.

---

## Блок 3. 24.10 18:00 → 25.10 10:00 (сдача)

- [ ] `inference` `POST /benchmark` и `GET /models`. Grafana-дашборд: FPS по камерам, задержка p50/p95 по стадиям, отставание очередей, события в минуту.
- [ ] Нагрузочный прогон: 4 и 8 камер одновременно, зафиксировать FPS и задержку → ML и в презентацию.
- [ ] **Устойчивость:**
  - рестарт любого сервиса не теряет события (`XACK` только после записи)
  - пропадание RTSP → переподключение
  - падение стенда → автоматический переход на `onnx` с пометкой в метриках и UI
- [ ] COULD: эскалация (событие не принято за N минут → `events.escalated` начальнику), Telegram-бот (aiogram).
- [ ] **Seed для показа:** площадка, участки, 4–6 камер, зоны, правила, пользователи. Если для дашборда нужна история за прошлые дни — генерируем её скриптом, **помечаем флагом `demo=true`** и честно говорим об этом на защите.
- [ ] **README:** запуск одной командой, схема, переменные окружения, как переключить бэкенд инференса, как добавить камеру и новый сценарий.
- [ ] 06:00 — code freeze. Дальше только исправления.

---

## Контракты (кратко; полный список — в Swagger сервисов)

| Сервис | Эндпоинты |
|---|---|
| auth | `POST /login` · `POST /refresh` · `GET/PATCH /me` · `GET/POST/PATCH /users` |
| camera | `/sites` · `/areas` · `/cameras` · `/cameras/{id}/zones` · `/cameras/{id}/rules` · `GET /cameras/{id}/snapshot` · `GET /scenarios` |
| events | `GET /events` · `GET /events/{id}` · `PATCH /events/{id}/status` · `GET /stats/*` · `GET /events/export.csv` |
| notifications | `WS /ws?token=` → `{"type": "event.created" \| "event.updated" \| "event.escalated", "event": EventOut}` |
| inference | `GET /models` · `POST /benchmark` · `GET /metrics` |
| ingest | `GET /streams` · `POST /streams/{cam}/restart` |

## Подсказки

- В горячем пути кадры не храним в БД: только Redis с TTL. В Postgres уходят события, в MinIO — доказательства.
- Каждый консьюмер идемпотентен: событие с тем же `event_id` не создаём дважды.
- `seq` и `ts` кадра проходят через весь путь. По ним считаем сквозную задержку `event_e2e_seconds`.
