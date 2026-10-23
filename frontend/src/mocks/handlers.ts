import { http, HttpResponse, delay, ws } from "msw";
import type { EventOut, EventStatus, Severity, User, ZoneKind } from "@/api/types";
import * as db from "./db";
import { sceneSvg, walkerBBox } from "./scene";

// --- токены: псевдо-JWT, чтобы клиент проверял exp и обновлял пару так же, как с бэкендом ----------

const ACCESS_TTL = 15 * 60;
const refreshTokens = new Map<string, number>();

function b64(o: unknown) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(o)))).replace(/=+$/, "");
}

function issue(u: User) {
  const exp = Math.floor(Date.now() / 1000) + ACCESS_TTL;
  const access = `${b64({ alg: "none" })}.${b64({ sub: String(u.id), role: u.role, exp })}.mock`;
  const refresh = db.uuid();
  refreshTokens.set(refresh, u.id);
  return { access_token: access, refresh_token: refresh, token_type: "bearer", expires_in: ACCESS_TTL, user: publicUser(u) };
}

function publicUser(u: User & { password?: string }): User {
  const { password: _p, ...rest } = u;
  return rest;
}

function userFromToken(token: string | null): (User & { password: string }) | null {
  if (!token) return null;
  try {
    const p = JSON.parse(decodeURIComponent(escape(atob(token.split(".")[1]))));
    if (p.exp * 1000 < Date.now()) return null;
    return db.users.find((u) => u.id === Number(p.sub) && u.is_active) || null;
  } catch {
    return null;
  }
}

function authed(req: Request) {
  const h = req.headers.get("Authorization");
  const token = h?.startsWith("Bearer ") ? h.slice(7) : new URL(req.url).searchParams.get("access_token");
  return userFromToken(token);
}

const unauthorized = () => HttpResponse.json({ detail: "Нужна авторизация" }, { status: 401 });
const forbidden = () => HttpResponse.json({ detail: "Недостаточно прав" }, { status: 403 });
const notFound = (what = "Не найдено") => HttpResponse.json({ detail: what }, { status: 404 });

type Resolver = (args: { request: Request; params: Record<string, string>; user: User & { password: string } }) => Response | Promise<Response>;

/** Обёртка: проверка токена и роли (admin пускается всегда), небольшая сетевая задержка для реализма. */
function guard(roles: string[] | null, fn: Resolver) {
  return async ({ request, params }: { request: Request; params: Record<string, string | readonly string[] | undefined> }) => {
    await delay(120 + Math.random() * 180);
    const user = authed(request);
    if (!user) return unauthorized();
    if (roles && user.role !== "admin" && !roles.includes(user.role)) return forbidden();
    return fn({ request, params: params as Record<string, string>, user });
  };
}

const ACT = ["operator", "master", "hse"];
const WRITE = ["hse"];
const EXPORT = ["hse", "auditor", "manager"];

// --- WebSocket -------------------------------------------------------------------------------

const live = ws.link(/\/ws(\?.*)?$/);
const clients = new Map<{ send: (d: string) => void; id: string }, User>();

function emit(type: "event.created" | "event.updated" | "event.escalated", e: EventOut) {
  for (const [client, user] of clients) {
    if (user.role === "master" && user.area_ids.length && !user.area_ids.includes(e.area_id as number)) continue;
    const p = user.notify_prefs;
    const sevOk: Record<Severity, number> = { low: 0, medium: 1, high: 2, critical: 3 };
    const notify =
      (!p.scenarios.length || p.scenarios.includes(e.scenario)) &&
      (!p.area_ids.length || p.area_ids.includes(e.area_id as number)) &&
      sevOk[e.severity] >= sevOk[p.min_severity];
    client.send(JSON.stringify({ type, event: e, notify }));
  }
}

let generator: number | undefined;

function spawnViolation() {
  const active = db.rules.filter((r) => r.enabled && db.cameras.find((c) => c.id === r.camera_id && c.enabled && c.id !== "cam-05"));
  // иногда — «падение», чтобы показать критичную тревогу
  const rule = Math.random() < 0.18 ? db.rules.find((r) => r.scenario === "fall") : active[Math.floor(Math.random() * active.length)];
  if (!rule) return;
  const camera = db.cameras.find((c) => c.id === rule.camera_id)!;
  const scenario = db.scenarios.find((s) => s.code === rule.scenario) || db.scenarios[0];
  const zone = db.zones.find((z) => z.id === rule.zone_id) || null;
  const e = db.makeEvent({ camera, scenario, started: new Date(Date.now() - 2500), severity: rule.severity || undefined, zone, ruleId: rule.id });
  e.clip_status = "pending";
  db.events.set(e.id, e);
  emit("event.created", db.toOut(e));
  setTimeout(() => {
    e.ended_at = new Date().toISOString();
    db.action(e, { action: "ended" });
    emit("event.updated", db.toOut(e));
  }, 5000 + Math.random() * 10_000);
  setTimeout(() => {
    e.clip_status = "ready";
    e.clip_url = `/media/mock/clips/${e.id}.mp4`;
    emit("event.updated", db.toOut(e));
  }, 9000);
}

function escalate() {
  const limits: Record<Severity, number> = { critical: 2, high: 5, medium: 15, low: 60 };
  const now = Date.now();
  for (const e of db.events.values()) {
    if (e.status !== "new" || e.escalated_at || e.demo) continue;
    if (now - new Date(e.created_at).getTime() > limits[e.severity] * 60_000) {
      e.escalated_at = new Date().toISOString();
      db.action(e, { action: "escalated", comment: `Не принято за ${limits[e.severity]} мин` });
      emit("event.escalated", db.toOut(e));
    }
  }
}

function startGenerator() {
  if (generator) return;
  const tick = () => {
    if (clients.size) spawnViolation();
    generator = window.setTimeout(tick, 9000 + Math.random() * 9000);
  };
  generator = window.setTimeout(tick, 6000);
  window.setInterval(escalate, 10_000);
}

const wsHandler = live.addEventListener("connection", ({ client }) => {
  const token = new URL(client.url).searchParams.get("access_token");
  const user = userFromToken(token);
  if (!user) {
    client.close(4401, "unauthorized");
    return;
  }
  clients.set(client, user);
  client.send(JSON.stringify({ type: "hello", user: { id: user.id, username: user.username, role: user.role, full_name: user.full_name, area_ids: user.area_ids } }));
  client.addEventListener("message", (ev) => {
    if (String(ev.data).includes("ping")) client.send(JSON.stringify({ type: "pong", ts: Date.now() / 1000 }));
  });
  client.addEventListener("close", () => clients.delete(client));
  startGenerator();
});

// --- HTTP ------------------------------------------------------------------------------------

const svg = (body: string) => new HttpResponse(body, { headers: { "Content-Type": "image/svg+xml", "Cache-Control": "no-store" } });

function camOr404(id: string) {
  return db.cameras.find((c) => c.id === id);
}

export const handlers = [
  wsHandler,

  // auth
  http.post("/api/auth/login", async ({ request }) => {
    await delay(350);
    const b = (await request.json()) as { username: string; password: string };
    const u = db.users.find((x) => x.username === b.username);
    if (!u || !u.is_active || u.password !== b.password) return HttpResponse.json({ detail: "Неверный логин или пароль" }, { status: 401 });
    return HttpResponse.json(issue(u));
  }),
  http.post("/api/auth/refresh", async ({ request }) => {
    const b = (await request.json()) as { refresh_token: string };
    const uid = refreshTokens.get(b.refresh_token);
    refreshTokens.delete(b.refresh_token);
    const u = db.users.find((x) => x.id === uid);
    if (!u) return HttpResponse.json({ detail: "Refresh-токен недействителен" }, { status: 401 });
    return HttpResponse.json(issue(u));
  }),
  http.post("/api/auth/logout", async ({ request }) => {
    const b = (await request.json()) as { refresh_token: string };
    refreshTokens.delete(b.refresh_token);
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/auth/roles", () => HttpResponse.json(db.roleList)),
  http.get("/api/auth/me", guard(null, ({ user }) => HttpResponse.json(publicUser(user)))),
  http.patch("/api/auth/me", guard(null, async ({ request, user }) => {
    const b = (await request.json()) as Partial<User>;
    if (b.full_name !== undefined) user.full_name = b.full_name;
    if ("telegram_chat_id" in b) user.telegram_chat_id = b.telegram_chat_id ?? null;
    if (b.notify_prefs) user.notify_prefs = b.notify_prefs;
    for (const [c, u] of clients) if (u.id === user.id) clients.set(c, user);
    return HttpResponse.json(publicUser(user));
  })),
  http.post("/api/auth/me/password", guard(null, async ({ request, user }) => {
    const b = (await request.json()) as { old_password: string; new_password: string };
    if (b.old_password !== user.password) return HttpResponse.json({ detail: "Старый пароль неверен" }, { status: 400 });
    user.password = b.new_password;
    return new HttpResponse(null, { status: 204 });
  })),
  http.get("/api/auth/users", guard([], () => HttpResponse.json(db.users.map(publicUser)))),
  http.post("/api/auth/users", guard([], async ({ request }) => {
    const b = (await request.json()) as User & { password: string };
    if (db.users.some((u) => u.username === b.username)) return HttpResponse.json({ detail: "Логин уже занят" }, { status: 409 });
    const u = { ...b, id: Math.max(...db.users.map((x) => x.id)) + 1, is_active: true, telegram_chat_id: null, role_title: "",
      notify_prefs: { scenarios: [], area_ids: [], min_severity: "low" as Severity, telegram: false, sound: true }, created_at: new Date().toISOString() };
    db.setRoleTitle(u);
    db.users.push(u);
    return HttpResponse.json(publicUser(u), { status: 201 });
  })),
  http.patch("/api/auth/users/:id", guard([], async ({ request, params }) => {
    const u = db.users.find((x) => x.id === Number(params.id));
    if (!u) return notFound("Пользователь не найден");
    const b = (await request.json()) as Partial<User & { password: string }>;
    Object.assign(u, Object.fromEntries(Object.entries(b).filter(([, v]) => v !== undefined && v !== "")));
    db.setRoleTitle(u);
    return HttpResponse.json(publicUser(u));
  })),

  // config
  http.get("/api/config/tree", guard(null, () => HttpResponse.json(db.tree()))),
  http.get("/api/config/scenarios", guard(null, () => HttpResponse.json(db.scenarios))),
  http.get("/api/config/cameras", guard(null, () => HttpResponse.json(db.cameras.map(db.cameraOut)))),
  http.post("/api/config/cameras", guard(WRITE, async ({ request }) => {
    const b = (await request.json()) as (typeof db.cameras)[number];
    let id = b.id;
    if (!id) {
      let n = db.cameras.length;
      do id = `cam-${String(++n).padStart(2, "0")}`;
      while (db.cameras.some((c) => c.id === id));
    } else if (db.cameras.some((c) => c.id === id)) return HttpResponse.json({ detail: "Камера с таким id уже есть" }, { status: 409 });
    const cam = { ...b, id, description: b.description || "", version: 1 };
    db.cameras.push(cam);
    return HttpResponse.json(db.cameraOut(cam), { status: 201 });
  })),
  http.get("/api/config/cameras/:id", guard(null, ({ params }) => {
    const c = camOr404(params.id);
    if (!c) return notFound("Камера не найдена");
    return HttpResponse.json({ ...db.cameraOut(c), zones: db.zones.filter((z) => z.camera_id === c.id), rules: db.rules.filter((r) => r.camera_id === c.id) });
  })),
  http.patch("/api/config/cameras/:id", guard(WRITE, async ({ request, params }) => {
    const c = camOr404(params.id);
    if (!c) return notFound("Камера не найдена");
    Object.assign(c, await request.json());
    db.bumpVersion(c.id);
    return HttpResponse.json(db.cameraOut(c));
  })),
  http.delete("/api/config/cameras/:id", guard(WRITE, ({ params }) => {
    const i = db.cameras.findIndex((c) => c.id === params.id);
    if (i < 0) return notFound("Камера не найдена");
    db.cameras.splice(i, 1);
    return new HttpResponse(null, { status: 204 });
  })),
  http.get("/api/config/cameras/:id/snapshot", guard(null, ({ params }) => {
    const c = camOr404(params.id);
    if (!c || c.id === "cam-05") return notFound("Кадров с камеры пока нет: проверьте поток");
    return svg(sceneSvg({ cameraId: c.id, persons: [{ bbox: walkerBBox(c.id) }] }));
  })),
  http.post("/api/config/cameras/:id/zones", guard(WRITE, async ({ request, params }) => {
    const b = (await request.json()) as { name: string; kind: ZoneKind; polygon: [number, number][]; enabled: boolean; color: string | null };
    const z = { id: Math.max(0, ...db.zones.map((x) => x.id)) + 1, camera_id: params.id, ...b, color: b.color ?? null, enabled: b.enabled ?? true };
    db.zones.push(z);
    db.bumpVersion(params.id);
    return HttpResponse.json(z, { status: 201 });
  })),
  http.patch("/api/config/cameras/:id/zones/:zid", guard(WRITE, async ({ request, params }) => {
    const z = db.zones.find((x) => x.id === Number(params.zid) && x.camera_id === params.id);
    if (!z) return notFound("Зона не найдена");
    Object.assign(z, await request.json());
    db.bumpVersion(params.id);
    return HttpResponse.json(z);
  })),
  http.delete("/api/config/cameras/:id/zones/:zid", guard(WRITE, ({ params }) => {
    const zid = Number(params.zid);
    db.zones.splice(db.zones.findIndex((x) => x.id === zid), 1);
    for (let i = db.rules.length - 1; i >= 0; i--) if (db.rules[i].zone_id === zid) db.rules.splice(i, 1);
    db.bumpVersion(params.id);
    return new HttpResponse(null, { status: 204 });
  })),
  http.post("/api/config/cameras/:id/rules", guard(WRITE, async ({ request, params }) => {
    const b = (await request.json()) as Omit<(typeof db.rules)[number], "id" | "camera_id">;
    const sc = db.scenarios.find((s) => s.code === b.scenario);
    if (!sc) return HttpResponse.json({ detail: `Неизвестный сценарий «${b.scenario}»` }, { status: 422 });
    if (sc.zone_required && !b.zone_id) return HttpResponse.json({ detail: `Сценарию «${sc.title}» нужна зона` }, { status: 422 });
    const r = { id: Math.max(0, ...db.rules.map((x) => x.id)) + 1, camera_id: params.id, ...b, params: b.params || {} };
    db.rules.push(r);
    db.bumpVersion(params.id);
    return HttpResponse.json(r, { status: 201 });
  })),
  http.patch("/api/config/cameras/:id/rules/:rid", guard(WRITE, async ({ request, params }) => {
    const r = db.rules.find((x) => x.id === Number(params.rid) && x.camera_id === params.id);
    if (!r) return notFound("Правило не найдено");
    Object.assign(r, await request.json());
    db.bumpVersion(params.id);
    return HttpResponse.json(r);
  })),
  http.delete("/api/config/cameras/:id/rules/:rid", guard(WRITE, ({ params }) => {
    db.rules.splice(db.rules.findIndex((x) => x.id === Number(params.rid)), 1);
    db.bumpVersion(params.id);
    return new HttpResponse(null, { status: 204 });
  })),

  // events
  http.get("/api/events/events", guard(null, ({ request, user }) => {
    const p = new URL(request.url).searchParams;
    const page = Number(p.get("page") || 1);
    const size = Number(p.get("page_size") || 50);
    const xs = db.sortEvents(db.filterEvents(p, user), p.get("sort") || "-started_at");
    return HttpResponse.json({ items: xs.slice((page - 1) * size, page * size).map(db.toOut), total: xs.length, page, page_size: size });
  })),
  http.get("/api/events/events/export.csv", guard(EXPORT, ({ request, user }) => {
    const p = new URL(request.url).searchParams;
    const xs = db.sortEvents(db.filterEvents(p, user), "-started_at");
    const st: Record<string, string> = { new: "Новое", confirmed: "Подтверждено", false: "Ложное", forwarded: "Передано мастеру", resolved: "Устранено" };
    const rows = [["ID", "Начало", "Окончание", "Камера", "Участок", "Зона", "Нарушение", "Важность", "Статус", "Уверенность", "SHA-256 снапшота", "Демо"]];
    const dt = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU") : "");
    for (const e of xs) rows.push([e.id, dt(e.started_at), dt(e.ended_at), e.camera_name || e.camera_id, String(e.area_id ?? ""), e.zone_name || "",
      e.scenario_title || e.scenario, e.severity, st[e.status], e.confidence?.toFixed(2) || "", e.snapshot_sha256 || "", e.demo ? "да" : ""]);
    const csv = "﻿" + rows.map((r) => r.map((c) => (c.includes(";") ? `"${c}"` : c)).join(";")).join("\r\n");
    return new HttpResponse(csv, { headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": `attachment; filename="violations_${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")}.csv"` } });
  })),
  http.get("/api/events/events/:id", guard(null, ({ params, user }) => {
    const e = db.events.get(params.id);
    if (!e || (user.role === "master" && user.area_ids.length && !user.area_ids.includes(e.area_id as number))) return notFound("Событие не найдено");
    return HttpResponse.json(db.toDetail(e));
  })),
  http.patch("/api/events/events/:id/status", guard(ACT, async ({ request, params, user }) => {
    const e = db.events.get(params.id);
    if (!e) return notFound("Событие не найдено");
    const b = (await request.json()) as { status: EventStatus; comment?: string; assignee_id?: number };
    if (b.status !== e.status && !db.TRANSITIONS[e.status].includes(b.status)) return HttpResponse.json({ detail: "Переход недопустим" }, { status: 409 });
    db.action(e, { action: "status", from_status: e.status, to_status: b.status, comment: b.comment || null, user_id: user.id, username: user.username });
    e.status = b.status;
    if (b.assignee_id) e.assignee_id = b.assignee_id;
    e.first_action_at ??= new Date().toISOString();
    emit("event.updated", db.toOut(e));
    return HttpResponse.json(db.toDetail(e));
  })),
  http.post("/api/events/events/:id/comments", guard(ACT, async ({ request, params, user }) => {
    const e = db.events.get(params.id);
    if (!e) return notFound("Событие не найдено");
    const b = (await request.json()) as { comment: string };
    db.action(e, { action: "comment", comment: b.comment, user_id: user.id, username: user.username });
    return HttpResponse.json(db.toDetail(e));
  })),

  // stats
  http.get("/api/events/stats/:name", guard(null, ({ request, params, user }) => {
    const p = new URL(request.url).searchParams;
    if (params.name === "trend" && !p.get("from")) p.set("from", new Date(Date.now() - 30 * 86400_000).toISOString());
    const xs = db.filterEvents(p, user);
    const crit = (g: { severity: string }[]) => g.filter((e) => e.severity === "critical").length;
    switch (params.name) {
      case "summary":
        return HttpResponse.json(db.summary(xs));
      case "by-type":
        return HttpResponse.json(db.groupCount(xs, (e) => e.scenario).map(([k, g]) => ({ scenario: k, title: g[0].scenario_title, count: g.length, critical: crit(g) })));
      case "by-camera":
        return HttpResponse.json(db.groupCount(xs, (e) => e.camera_id).map(([k, g]) => ({ camera_id: k, camera_name: g[0].camera_name, area_id: g[0].area_id, count: g.length })));
      case "by-area":
        return HttpResponse.json(db.groupCount(xs, (e) => e.area_id).map(([k, g]) => ({ area_id: k, count: g.length })));
      case "heatmap":
        return HttpResponse.json(db.groupCount(xs, (e) => { const d = new Date(e.started_at); return `${(d.getDay() + 6) % 7}:${d.getHours()}`; })
          .map(([k, g]) => ({ dow: Number(k.split(":")[0]), hour: Number(k.split(":")[1]), count: g.length })));
      case "trend": {
        const day = (s: string) => { const d = new Date(s); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
        return HttpResponse.json(db.groupCount(xs, (e) => day(e.started_at)).map(([k, g]) => ({ date: k, count: g.length, critical: crit(g) })).sort((a, b) => a.date.localeCompare(b.date)));
      }
      case "precision":
        return HttpResponse.json(db.groupCount(xs, (e) => e.scenario).map(([k, g]) => {
          const c = g.filter((e) => e.status === "confirmed" || e.status === "resolved").length;
          const f = g.filter((e) => e.status === "false").length;
          return { scenario: k, title: g[0].scenario_title, camera_id: null, confirmed: c, false: f, precision: c + f ? Math.round((c / (c + f)) * 1000) / 1000 : null };
        }));
    }
    return notFound();
  })),
  http.post("/api/events/demo/seed", guard([], () => HttpResponse.json({ created: 0 }))),

  // inference / ingest
  http.get("/api/inference/models", async () => {
    await delay(100);
    return HttpResponse.json({
      backend: "remote", active_backend: "remote", url: "http://10.8.0.2:8000", fallback: { active: false, backend: "onnx", last_error: null },
      models: [
        { name: "pose", version: "yolo11s-pose-v3", input: [640, 640], program: "pose_640_int8.tpu", preset: "int8-calib-512" },
        { name: "objects", version: "yolo11s-ppe-v2", input: [640, 640], program: "det_640_int8.tpu", preset: "int8-calib-512" },
      ],
      consume: true, shards: [0], fps: +(19.2 + Math.random() * 1.4).toFixed(2),
    });
  }),
  http.get("/api/inference/benchmarks", async () => {
    await delay(150);
    return HttpResponse.json([...db.benchmarks].sort((a, b) => b.measured_at.localeCompare(a.measured_at)));
  }),
  http.post("/api/inference/benchmark", async ({ request }) => {
    const b = (await request.json()) as { runs: number };
    await delay(Math.min(4000, 800 + b.runs * 6));
    const j = () => 1 + (Math.random() - 0.5) * 0.08;
    const rep = {
      model: "pose+objects", program: "pose_640_int8.tpu,det_640_int8.tpu", backend: "remote", batch: 1, input: [640, 640], runs: b.runs,
      measured_at: new Date().toISOString(), source: "inference-service", fps: +(38.5 * j()).toFixed(2),
      latency_ms: { pre: { p50: +(1.8 * j()).toFixed(2), p95: +(2.5 * j()).toFixed(2) }, rpc: { p50: +(12.6 * j()).toFixed(2), p95: +(19.8 * j()).toFixed(2) },
        infer: { p50: +(11.9 * j()).toFixed(2), p95: +(13.6 * j()).toFixed(2) }, post: { p50: +(1.4 * j()).toFixed(2), p95: +(2.0 * j()).toFixed(2) },
        total: { p50: +(25.9 * j()).toFixed(2), p95: +(35.1 * j()).toFixed(2) } },
    };
    db.benchmarks.push(rep);
    return HttpResponse.json(rep);
  }),
  http.get("/api/ingest/streams", async () =>
    HttpResponse.json({
      config_source: "redis",
      streams: db.cameras.map((c) => {
        const o = db.cameraOut(c);
        return { camera_id: c.id, state: o.stream.state, fps: o.stream.fps, target_fps: c.analysis_fps, error: o.stream.error, source: c.source_url };
      }),
    }),
  ),

  // медиа: снапшоты событий
  http.get("/media/mock/:kind/:file", ({ params }) => {
    const id = String(params.file).replace(/\.\w+$/, "");
    const e = db.events.get(id);
    if (!e || params.kind === "clips") return notFound();
    const lying = e.scenario === "fall";
    return svg(sceneSvg({
      cameraId: e.camera_id, time: new Date(e.started_at), persons: e.bbox ? [{ bbox: e.bbox, lying }] : [],
      boxes: params.kind === "annotated" && e.bbox ? [{ bbox: e.bbox, label: `${e.scenario_title} ${Math.round((e.confidence || 0) * 100)}%`, color: "#ef4444" }] : [],
    }));
  }),
];
