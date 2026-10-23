// In-memory «бэкенд» для MSW: та же форма данных, что у сервисов (messages.py, схемы FastAPI).
import type {
  BenchmarkReport, Camera, EventAction, EventDetail, EventOut, EventStatus, JsonSchema, Role, Rule, ScenarioInfo, Severity,
  TreeSite, User, Zone,
} from "@/api/types";

// --- справочники ----------------------------------------------------------------------

export const sites = [{ id: 1, name: "Завод «Моспром-Демо»", address: "Москва" }];
export const areas = [
  { id: 1, site_id: 1, name: "Цех №1 — штамповка" },
  { id: 2, site_id: 1, name: "Склад готовой продукции" },
  { id: 3, site_id: 1, name: "Цех №2 — сборка" },
];

type CamRow = Omit<Camera, "area_name" | "site_id" | "zones_count" | "rules_count" | "stream" | "live_hls">;

export const cameras: CamRow[] = [
  { id: "cam-01", area_id: 1, name: "Цех 1, пресс", description: "Пресс КД-2130, вид сбоку", source_type: "rtsp", source_url: "rtsp://mediamtx:8554/cam01", analysis_fps: 5, enabled: true, version: 3 },
  { id: "cam-02", area_id: 1, name: "Цех 1, проход", description: "Проезд погрузчиков", source_type: "rtsp", source_url: "rtsp://mediamtx:8554/cam02", analysis_fps: 5, enabled: true, version: 2 },
  { id: "cam-03", area_id: 2, name: "Склад, ворота", description: "", source_type: "rtsp", source_url: "rtsp://mediamtx:8554/cam03", analysis_fps: 5, enabled: true, version: 1 },
  { id: "cam-04", area_id: 2, name: "Склад, стеллажи", description: "", source_type: "rtsp", source_url: "rtsp://mediamtx:8554/cam04", analysis_fps: 5, enabled: true, version: 1 },
  { id: "cam-05", area_id: 3, name: "Цех 2, конвейер", description: "Камера на обслуживании", source_type: "rtsp", source_url: "rtsp://10.0.4.15:554/stream1", analysis_fps: 5, enabled: true, version: 1 },
];

export const zones: Zone[] = [
  { id: 1, camera_id: "cam-01", name: "Опасная зона пресса", kind: "danger", polygon: [[0.0, 0.3], [0.37, 0.3], [0.37, 1.0], [0.0, 1.0]], color: null, enabled: true },
  { id: 2, camera_id: "cam-02", name: "Проезд погрузчиков", kind: "forbidden", polygon: [[0.6, 0.4], [1.0, 0.4], [1.0, 1.0], [0.6, 1.0]], color: null, enabled: true },
];

export const rules: Rule[] = [
  { id: 1, camera_id: "cam-01", scenario: "in_zone", zone_id: 1, severity: "high", params: { confirm_s: 2.0, cooldown_s: 10 }, schedule: null, valid_until: null, enabled: true },
  { id: 2, camera_id: "cam-02", scenario: "in_zone", zone_id: 2, severity: "critical", params: { confirm_s: 1.5, cooldown_s: 10 }, schedule: null, valid_until: null, enabled: true },
  { id: 3, camera_id: "cam-01", scenario: "fall", zone_id: null, severity: null, params: {}, schedule: { days: [0, 1, 2, 3, 4], from: "07:55", to: "20:00" }, valid_until: null, enabled: true },
  { id: 4, camera_id: "cam-03", scenario: "running", zone_id: null, severity: null, params: { speed: 1.2 }, schedule: null, valid_until: null, enabled: true },
  { id: 5, camera_id: "cam-04", scenario: "phone", zone_id: null, severity: null, params: {}, schedule: null, valid_until: null, enabled: false },
];

const COMMON: Record<string, JsonSchema> = {
  threshold: { type: "number", minimum: 0, maximum: 1, default: 0.5, title: "Порог срабатывания на кадре" },
  confirm_s: { type: "number", minimum: 0, maximum: 60, default: 2.0, title: "Окно подтверждения, с" },
  confirm_ratio: { type: "number", minimum: 0.1, maximum: 1, default: 0.7, title: "Доля кадров «да» в окне" },
  release_s: { type: "number", minimum: 0, maximum: 120, default: 3.0, title: "Нарушение закончилось, если его нет, с" },
  cooldown_s: { type: "number", minimum: 0, maximum: 3600, default: 30.0, title: "Пауза перед повторным событием, с" },
};

function schema(own: Record<string, JsonSchema>): JsonSchema {
  const props: Record<string, JsonSchema> = { ...COMMON };
  for (const [k, v] of Object.entries(own)) props[k] = { ...(props[k] || {}), ...v };
  return { type: "object", properties: props };
}

export const scenarios: ScenarioInfo[] = [
  {
    code: "fall", title: "Падение человека", severity: "critical", requires: ["pose"], per_track: true, zone_required: false,
    description: "Резкий переход торса из вертикали в горизонталь; затем неподвижность — эскалация.",
    params_schema: schema({
      angle_deg: { type: "number", minimum: 20, maximum: 90, default: 55, title: "Наклон торса, °" },
      immobile_s: { type: "number", minimum: 3, maximum: 120, default: 10, title: "Неподвижность для эскалации, с" },
      confirm_s: { default: 1.0 },
    }),
  },
  {
    code: "in_zone", title: "Человек в опасной зоне", severity: "high", requires: ["pose"], per_track: true, zone_required: false,
    description: "Человек находится внутри полигона зоны дольше окна подтверждения. Без зоны — человек в любом месте кадра.",
    params_schema: schema({
      point: { type: "string", enum: ["foot", "center"], default: "foot", title: "Какая точка человека должна быть в зоне", description: "foot — точка опоры, center — центр рамки" },
      min_score: { type: "number", minimum: 0, maximum: 1, default: 0.4, title: "Мин. уверенность детекции" },
      confirm_s: { default: 2.0 },
    }),
  },
  {
    code: "phone", title: "Телефон в рабочей зоне", severity: "medium", requires: ["objects", "pose"], per_track: true, zone_required: false,
    description: "Телефон у кисти или головы ≥ 3 с в зоне оборудования.",
    params_schema: schema({
      max_dist: { type: "number", minimum: 0.1, maximum: 2, default: 0.5, title: "Телефон у руки, в ростах" },
      confirm_s: { default: 3.0 },
    }),
  },
  {
    code: "proximity", title: "Опасное сближение с техникой", severity: "critical", requires: ["objects", "pose"], per_track: true, zone_required: false,
    description: "Расстояние между человеком и движущимся погрузчиком меньше k × рост человека.",
    params_schema: schema({
      k_height: { type: "number", minimum: 0.2, maximum: 5, default: 1.5, title: "Дистанция, в ростах человека" },
      moving_only: { type: "boolean", default: true, title: "Только движущаяся техника" },
      confirm_s: { default: 1.0 },
    }),
  },
  {
    code: "running", title: "Бег в цехе", severity: "high", requires: ["pose"], per_track: true, zone_required: false,
    description: "Скорость центра таза больше X ростов в секунду дольше 1,5 с.",
    params_schema: schema({
      speed: { type: "number", minimum: 0.3, maximum: 5, default: 1.0, title: "Скорость, ростов/с" },
      confirm_s: { default: 1.5 },
    }),
  },
];

// --- пользователи ---------------------------------------------------------------------

const ROLE_TITLES: Record<Role, string> = {
  admin: "Администратор", hse: "Специалист по охране труда", master: "Мастер / начальник смены", operator: "Диспетчер",
  manager: "Руководитель", auditor: "Юрист / аудитор",
};

export const roleList = (Object.keys(ROLE_TITLES) as Role[]).map((code) => ({ code, title: ROLE_TITLES[code] }));

const defaultPrefs = () => ({ scenarios: [], area_ids: [], min_severity: "low" as Severity, telegram: false, sound: true });

export const users: (User & { password: string })[] = (
  [
    ["admin", "admin", "Администратор системы", []],
    ["hse", "hse", "Иванова Анна (охрана труда)", []],
    ["master", "master", "Петров Сергей (мастер цеха №1)", [1]],
    ["operator", "operator", "Сидоров Олег (диспетчер)", []],
    ["manager", "manager", "Кузнецова Мария (руководитель)", []],
    ["auditor", "auditor", "Смирнов Павел (юрист)", []],
  ] as [string, Role, string, number[]][]
).map(([username, role, full_name, area_ids], i) => ({
  id: i + 1, username, role, role_title: ROLE_TITLES[role], full_name, area_ids, is_active: true, telegram_chat_id: null,
  notify_prefs: defaultPrefs(), created_at: new Date(Date.now() - 20 * 86400_000).toISOString(), password: "demo",
}));

export function setRoleTitle(u: User) {
  u.role_title = ROLE_TITLES[u.role];
}

// --- события --------------------------------------------------------------------------

type Stored = EventOut & { actions: EventAction[]; first_action_at: string | null };
export const events = new Map<string, Stored>();
let actionId = 1;

let rndState = 42;
function rnd() {
  rndState = (rndState * 1664525 + 1013904223) % 4294967296;
  return rndState / 4294967296;
}
const pick = <T,>(xs: T[], w?: number[]): T => {
  if (!w) return xs[Math.floor(rnd() * xs.length)];
  const total = w.reduce((a, b) => a + b, 0);
  let r = rnd() * total;
  for (let i = 0; i < xs.length; i++) if ((r -= w[i]) < 0) return xs[i];
  return xs[xs.length - 1];
};
const gauss = (m: number, s: number) => m + s * Math.sqrt(-2 * Math.log(rnd() || 1e-9)) * Math.cos(2 * Math.PI * rnd());

export function uuid(): string {
  return crypto.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, () => ((Math.random() * 16) | 0).toString(16));
}

export function action(e: Stored, a: Partial<EventAction> & { action: string }, at = new Date()) {
  e.actions.push({ id: actionId++, user_id: null, username: null, from_status: null, to_status: null, comment: null, at: at.toISOString(), ...a });
}

export function mediaFor(id: string) {
  return { snapshot_url: `/media/mock/events/${id}.svg`, annotated_url: `/media/mock/annotated/${id}.svg` };
}

const CAM_BBOX: Record<string, () => [number, number, number, number]> = {
  "cam-01": () => { const x = 0.08 + rnd() * 0.2; return [x, 0.42, x + 0.11, 0.82]; },
  "cam-02": () => { const x = 0.62 + rnd() * 0.22; return [x, 0.46, x + 0.1, 0.86]; },
};

function randomBBox(cam: string): [number, number, number, number] {
  if (CAM_BBOX[cam]) return CAM_BBOX[cam]();
  const x = 0.1 + rnd() * 0.7;
  const y = 0.38 + rnd() * 0.18;
  return [x, y, x + 0.1, Math.min(y + 0.36, 0.98)];
}

export function makeEvent(opts: {
  camera: CamRow; scenario: ScenarioInfo; started: Date; status?: EventStatus; demo?: boolean; reactionS?: number; severity?: Severity;
  zone?: Zone | null; ruleId?: number | null;
}): Stored {
  const id = uuid();
  const created = new Date(opts.started.getTime() + (1500 + rnd() * 2000));
  const sev = opts.severity || opts.scenario.severity;
  const lying = opts.scenario.code === "fall";
  let bbox = randomBBox(opts.camera.id);
  if (lying) bbox = [bbox[0] - 0.05, bbox[3] - 0.14, bbox[0] + 0.18, bbox[3]];
  const e: Stored = {
    id, camera_id: opts.camera.id, camera_name: opts.camera.name, area_id: opts.camera.area_id, zone_id: opts.zone?.id ?? null,
    zone_name: opts.zone?.name ?? null, rule_id: opts.ruleId ?? null, scenario: opts.scenario.code, scenario_title: opts.scenario.title,
    severity: sev, status: "new", started_at: opts.started.toISOString(), confirmed_at: created.toISOString(), ended_at: null,
    created_at: created.toISOString(), escalated_at: null, confidence: Math.round((0.55 + rnd() * 0.4) * 100) / 100,
    track_id: Math.floor(rnd() * 900) + 1, bbox, ...mediaFor(id),
    snapshot_sha256: Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(rnd() * 16)]).join(""),
    clip_url: null, clip_status: "none", assignee_id: null, demo: !!opts.demo, frame_ts: opts.started.getTime() / 1000,
    actions: [], first_action_at: null,
  };
  action(e, { action: "created", to_status: "new" }, created);
  if (opts.status && opts.status !== "new") {
    const at = new Date(created.getTime() + (opts.reactionS ?? 60) * 1000);
    e.status = opts.status;
    e.first_action_at = at.toISOString();
    action(e, { action: "status", from_status: "new", to_status: opts.status, username: pick(["operator", "master", "hse"]), user_id: 4 }, at);
  }
  return e;
}

const SCEN_WEIGHTS: Record<string, number> = { fall: 1, proximity: 3, running: 4, phone: 5, in_zone: 4 };

function seedHistory() {
  const now = new Date();
  for (let d = 14; d >= 1; d--) {
    const day = new Date(now);
    day.setDate(day.getDate() - d);
    day.setHours(0, 0, 0, 0);
    const weekend = day.getDay() === 0 || day.getDay() === 6;
    const n = Math.max(3, Math.round(gauss(weekend ? 8 : 22, 5)));
    for (let i = 0; i < n; i++) {
      const hour = Math.min(Math.max(Math.round(pick([gauss(10, 1.5), gauss(14.5, 1.5), gauss(18, 1)])), 0), 23);
      const started = new Date(day);
      started.setHours(hour, Math.floor(rnd() * 60), Math.floor(rnd() * 60));
      const sc = pick(scenarios, scenarios.map((s) => SCEN_WEIGHTS[s.code] || 1));
      const cam = pick(cameras.slice(0, 4), [5, 4, 2, 2]);
      const status = pick<EventStatus>(["confirmed", "false", "resolved", "forwarded"], [50, 15, 30, 5]);
      const e = makeEvent({ camera: cam, scenario: sc, started, status, demo: true, reactionS: Math.max(5, gauss(70, 40)) });
      e.ended_at = new Date(started.getTime() + (3 + rnd() * 37) * 1000).toISOString();
      e.clip_status = "none";
      events.set(e.id, e);
    }
  }
  // сегодня: реальные события, два из них ещё не приняты — сразу видно в ленте
  const today: [string, string, number, EventStatus][] = [
    ["cam-02", "in_zone", 190, "confirmed"], ["cam-01", "in_zone", 150, "resolved"], ["cam-03", "running", 95, "false"],
    ["cam-04", "phone", 61, "forwarded"], ["cam-01", "in_zone", 34, "confirmed"], ["cam-03", "running", 12, "new"],
    ["cam-02", "proximity", 3, "new"],
  ];
  for (const [camId, code, minAgo, status] of today) {
    const cam = cameras.find((c) => c.id === camId)!;
    const sc = scenarios.find((s) => s.code === code)!;
    const zone = zones.find((z) => z.camera_id === camId && code === "in_zone") || null;
    const rule = rules.find((r) => r.camera_id === camId && r.scenario === code);
    const e = makeEvent({ camera: cam, scenario: sc, started: new Date(Date.now() - minAgo * 60_000), status, reactionS: 40 + rnd() * 60,
      severity: rule?.severity || undefined, zone, ruleId: rule?.id ?? null });
    e.ended_at = new Date(new Date(e.started_at).getTime() + 8_000 + rnd() * 20_000).toISOString();
    e.clip_status = "ready";
    e.clip_url = `/media/mock/clips/${e.id}.mp4`;
    events.set(e.id, e);
  }
}
seedHistory();

export const TRANSITIONS: Record<EventStatus, EventStatus[]> = {
  new: ["confirmed", "false", "forwarded", "resolved"],
  forwarded: ["confirmed", "false", "resolved"],
  confirmed: ["resolved", "forwarded"],
  false: ["new"],
  resolved: ["new"],
};

export function toOut(e: Stored): EventOut {
  const { actions: _a, first_action_at: _f, ...out } = e;
  return out;
}

export function toDetail(e: Stored): EventDetail {
  return { ...toOut(e), actions: e.actions, allowed_statuses: [...TRANSITIONS[e.status]].sort() };
}

// --- фильтры и агрегаты (как EventFilter.apply и stats.py) ------------------------------

export function filterEvents(p: URLSearchParams, user?: User | null): Stored[] {
  const all = (k: string) => p.getAll(k).filter(Boolean);
  const cams = all("camera_id");
  const ar = all("area_id").map(Number);
  const zs = all("zone_id").map(Number);
  const sc = all("scenario");
  const sev = all("severity");
  const st = all("status");
  const from = p.get("from") ? new Date(p.get("from")!).getTime() : null;
  const to = p.get("to") ? new Date(p.get("to")!).getTime() : null;
  const demo = p.get("demo");
  return [...events.values()].filter((e) => {
    const t = new Date(e.started_at).getTime();
    if (cams.length && !cams.includes(e.camera_id)) return false;
    if (ar.length && !ar.includes(e.area_id as number)) return false;
    if (zs.length && !zs.includes(e.zone_id as number)) return false;
    if (sc.length && !sc.includes(e.scenario)) return false;
    if (sev.length && !sev.includes(e.severity)) return false;
    if (st.length && !st.includes(e.status)) return false;
    if (from !== null && t < from) return false;
    if (to !== null && t >= to) return false;
    if (demo !== null && String(e.demo) !== demo) return false;
    if (user?.role === "master" && user.area_ids.length && !user.area_ids.includes(e.area_id as number)) return false;
    return true;
  });
}

const RANK: Record<Severity, number> = { critical: 3, high: 2, medium: 1, low: 0 };

export function sortEvents(xs: Stored[], sort: string): Stored[] {
  const by = (a: Stored, b: Stored) => b.started_at.localeCompare(a.started_at);
  switch (sort) {
    case "started_at":
      return xs.sort((a, b) => a.started_at.localeCompare(b.started_at));
    case "-severity":
      return xs.sort((a, b) => RANK[b.severity] - RANK[a.severity] || by(a, b));
    case "-created_at":
      return xs.sort((a, b) => b.created_at.localeCompare(a.created_at));
    default:
      return xs.sort(by);
  }
}

export function summary(xs: Stored[]) {
  const today0 = new Date();
  today0.setHours(0, 0, 0, 0);
  const c = (f: (e: Stored) => boolean) => xs.filter(f).length;
  const confirmed = c((e) => e.status === "confirmed");
  const fl = c((e) => e.status === "false");
  const resolved = c((e) => e.status === "resolved");
  const real = confirmed + resolved;
  const reactions = xs.filter((e) => e.first_action_at).map((e) => (new Date(e.first_action_at!).getTime() - new Date(e.created_at).getTime()) / 1000);
  const by_severity: Record<string, number> = {};
  xs.forEach((e) => (by_severity[e.severity] = (by_severity[e.severity] || 0) + 1));
  return {
    total: xs.length, today: c((e) => new Date(e.started_at) >= today0), critical: c((e) => e.severity === "critical"),
    unaccepted: c((e) => e.status === "new"), forwarded: c((e) => e.status === "forwarded"), confirmed, false: fl, resolved,
    escalated: c((e) => !!e.escalated_at), precision: real + fl ? Math.round((real / (real + fl)) * 1000) / 1000 : null,
    avg_reaction_s: reactions.length ? Math.round((reactions.reduce((a, b) => a + b, 0) / reactions.length) * 10) / 10 : null,
    by_severity,
  };
}

export function groupCount<K extends string | number | null>(xs: Stored[], key: (e: Stored) => K) {
  const m = new Map<K, Stored[]>();
  xs.forEach((e) => {
    const k = key(e);
    m.set(k, [...(m.get(k) || []), e]);
  });
  return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
}

// --- камеры -----------------------------------------------------------------------------

const STREAM_STATE: Record<string, { state: string; fps: number; error: string | null }> = {
  "cam-05": { state: "offline", fps: 0, error: "RTSP: Connection timed out (10.0.4.15:554)" },
};

export function cameraOut(c: CamRow): Camera {
  const area = areas.find((a) => a.id === c.area_id);
  const st = !c.enabled ? { state: "disabled", fps: 0, error: null } : STREAM_STATE[c.id] || { state: "online", fps: +(c.analysis_fps - Math.random() * 0.3).toFixed(2), error: null };
  return {
    ...c, area_name: area?.name ?? null, site_id: area?.site_id ?? null,
    zones_count: zones.filter((z) => z.camera_id === c.id).length, rules_count: rules.filter((r) => r.camera_id === c.id).length,
    stream: { ...st, last_frame_ts: st.state === "online" ? Date.now() / 1000 : null, w: 1280, h: 720 }, live_hls: null,
  };
}

export function tree(): TreeSite[] {
  return sites.map((s) => ({
    ...s,
    areas: areas.filter((a) => a.site_id === s.id).map((a) => ({ ...a, cameras: cameras.filter((c) => c.area_id === a.id).map(cameraOut) })),
  }));
}

export function bumpVersion(camId: string) {
  const c = cameras.find((x) => x.id === camId);
  if (c) c.version += 1;
}

// --- бенчмарки -------------------------------------------------------------------------

export const benchmarks: BenchmarkReport[] = [
  {
    model: "yolo11s-pose", program: "pose_640_int8.tpu", backend: "pytpu", batch: 1, input: [640, 640], runs: 500,
    measured_at: new Date(Date.now() - 5 * 3600_000).toISOString(), fps: 118.4, source: "ml/linq_pose.json",
    latency_ms: { pre: { p50: 1.9, p95: 2.6 }, infer: { p50: 5.6, p95: 6.4 }, post: { p50: 0.9, p95: 1.3 }, total: { p50: 8.4, p95: 10.1 } },
  },
  {
    model: "yolo11s", program: "det_640_int8.tpu", backend: "pytpu", batch: 1, input: [640, 640], runs: 500,
    measured_at: new Date(Date.now() - 5 * 3600_000).toISOString(), fps: 92.7, source: "ml/linq_objects.json",
    latency_ms: { pre: { p50: 1.9, p95: 2.5 }, infer: { p50: 7.4, p95: 8.6 }, post: { p50: 1.4, p95: 2.2 }, total: { p50: 10.8, p95: 12.9 } },
  },
  {
    model: "yolo11s-pose", program: null, backend: "onnx", batch: 1, input: [640, 640], runs: 200,
    measured_at: new Date(Date.now() - 26 * 3600_000).toISOString(), fps: 14.2, source: "ml/cpu_pose.json",
    latency_ms: { pre: { p50: 2.4, p95: 3.3 }, infer: { p50: 63.1, p95: 71.8 }, post: { p50: 1.1, p95: 1.6 }, total: { p50: 70.4, p95: 79.0 } },
  },
  {
    model: "yolo11s-pose", program: "pose_640_int8.tpu", backend: "remote", batch: 1, input: [640, 640], runs: 200,
    measured_at: new Date(Date.now() - 2 * 3600_000).toISOString(), fps: 41.3, source: "inference-service",
    latency_ms: { pre: { p50: 1.8, p95: 2.4 }, rpc: { p50: 14.2, p95: 22.9 }, infer: { p50: 5.7, p95: 6.6 }, post: { p50: 0.9, p95: 1.2 }, total: { p50: 24.2, p95: 33.4 } },
  },
];
