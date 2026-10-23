# Фронтенд (SPA)

План работ — [docs/plans/frontend.md](../docs/plans/frontend.md). Стек: React 18 + TypeScript + Vite, Ant Design 5.

## Подключение к бэкенду

Бэкенд поднимается из корня репозитория: `docker compose up -d --build`. Всё API идёт через шлюз
`http://localhost:8080`, в dev-режиме Vite проксирует туда:

```ts
// vite.config.ts
server: {
  proxy: {
    "/api": "http://localhost:8080",
    "/media": "http://localhost:8080",
    "/live": "http://localhost:8080",
    "/ws": { target: "ws://localhost:8080", ws: true },
  },
},
```

| Что | Адрес |
|---|---|
| Swagger (типы — `openapi-typescript`) | `/api/{auth,config,events,inference,ingest,analytics,notifications}/openapi.json` |
| Вход | `POST /api/auth/login` → `access_token`, `refresh_token`; пользователи `admin`, `hse`, `master`, `operator`, `manager`, `auditor`, пароль `demo` |
| Лента событий | `WS /ws?access_token=…` — формат сообщений в корневом README |
| Снапшот камеры для редактора зон | `GET /api/config/cameras/{id}/snapshot?access_token=…` |
| Живое видео | `/live/cam01/index.m3u8` (hls.js) |

## В docker compose

Шлюз уже отправляет `/` на сервис `frontend:80`. Когда появится `Dockerfile` (сборка Vite → nginx),
раскомментировать сервис `frontend` в корневом `docker-compose.yml`.
