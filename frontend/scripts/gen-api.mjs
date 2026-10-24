// Типы из Swagger сервисов: npm run gen:api (бэкенд должен быть поднят, шлюз — VITE_API_TARGET или :8080)
import { execSync } from "node:child_process";

const base = process.env.VITE_API_TARGET || "http://localhost:8080";
for (const svc of ["auth", "config", "events", "inference", "ingest", "analytics", "notifications"]) {
  execSync(`npx openapi-typescript ${base}/api/${svc}/openapi.json -o src/api/schema/${svc}.d.ts`, { stdio: "inherit" });
}
