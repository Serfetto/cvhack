// Контракты бэкенда: backend/server/libs/common/common/messages.py и схемы сервисов.
// После `npm run gen:api` сверять с src/api/schema/*.d.ts. Координаты (bbox, полигоны) нормированы к 0..1.

export type Severity = "critical" | "high" | "medium" | "low";
export type EventStatus = "new" | "confirmed" | "false" | "forwarded" | "resolved";
export type Role = "admin" | "hse" | "master" | "operator" | "manager" | "auditor";
export type ZoneKind = "danger" | "no_smoking" | "height" | "fence" | "forbidden";
export type SourceType = "rtsp" | "file" | "images";
export type ClipStatus = "none" | "pending" | "ready" | "failed";
export type BBox = [number, number, number, number];
export type Point = [number, number];

// --- auth -----------------------------------------------------------------------

export interface NotifyPrefs {
  scenarios: string[];
  area_ids: number[];
  min_severity: Severity;
  telegram: boolean;
  sound: boolean;
}

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  role_title: string;
  area_ids: number[];
  is_active: boolean;
  telegram_chat_id: number | null;
  notify_prefs: NotifyPrefs;
  created_at: string;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface MePatch {
  full_name?: string;
  telegram_chat_id?: number | null;
  notify_prefs?: NotifyPrefs;
}

export interface UserCreate {
  username: string;
  password: string;
  full_name: string;
  role: Role;
  area_ids: number[];
}

export interface UserPatch {
  full_name?: string;
  role?: Role;
  area_ids?: number[];
  is_active?: boolean;
  password?: string;
  telegram_chat_id?: number | null;
}

export interface RoleInfo {
  code: Role;
  title: string;
}

// --- events ---------------------------------------------------------------------

export interface EventOut {
  id: string;
  camera_id: string;
  camera_name: string | null;
  area_id: number | null;
  zone_id: number | null;
  zone_name: string | null;
  rule_id: number | null;
  scenario: string;
  scenario_title: string | null;
  severity: Severity;
  status: EventStatus;
  started_at: string;
  confirmed_at: string | null;
  ended_at: string | null;
  created_at: string;
  escalated_at: string | null;
  confidence: number | null;
  track_id: number | null;
  bbox: BBox | null;
  snapshot_url: string | null;
  annotated_url: string | null;
  snapshot_sha256: string | null;
  clip_url: string | null;
  clip_status: ClipStatus;
  assignee_id: number | null;
  demo: boolean;
  frame_ts: number | null;
}

export interface EventAction {
  id: number;
  user_id: number | null;
  username: string | null;
  action: string; // created | status | comment | ended | escalated
  from_status: string | null;
  to_status: string | null;
  comment: string | null;
  at: string;
}

export interface EventDetail extends EventOut {
  actions: EventAction[];
  allowed_statuses: EventStatus[];
}

export interface EventPage {
  items: EventOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface EventFilter {
  camera_id?: string[];
  area_id?: number[];
  zone_id?: number[];
  scenario?: string[];
  severity?: Severity[];
  status?: EventStatus[];
  from?: string;
  to?: string;
  demo?: boolean;
}

export type EventSort = "-started_at" | "started_at" | "-severity" | "-created_at";

export interface StatusIn {
  status: EventStatus;
  comment?: string | null;
  assignee_id?: number | null;
}

export type WsMessage =
  | { type: "hello"; user: { id: number; username: string; role: Role; full_name: string; area_ids: number[] } }
  | { type: "event.created" | "event.updated" | "event.escalated"; event: EventOut; notify?: boolean }
  | { type: "ping" | "pong"; ts: number };

// --- stats ----------------------------------------------------------------------

export interface Summary {
  total: number;
  today: number;
  critical: number;
  unaccepted: number;
  forwarded: number;
  confirmed: number;
  false: number;
  resolved: number;
  escalated: number;
  precision: number | null;
  avg_reaction_s: number | null;
  by_severity: Partial<Record<Severity, number>>;
}

export interface TypeRow {
  scenario: string;
  title: string | null;
  count: number;
  critical: number;
}

export interface CameraRow {
  camera_id: string;
  camera_name: string | null;
  area_id: number | null;
  count: number;
}

export interface AreaRow {
  area_id: number | null;
  count: number;
}

export interface HeatCell {
  dow: number;
  hour: number;
  count: number;
}

export interface TrendRow {
  date: string;
  count: number;
  critical: number;
}

export interface PrecisionRow {
  scenario: string;
  title: string | null;
  camera_id: string | null;
  confirmed: number;
  false: number;
  precision: number | null;
}

// --- config (camera-service) -------------------------------------------------------

export interface StreamStatus {
  state: "online" | "connecting" | "offline" | "disabled" | "unknown" | string;
  fps: number;
  last_frame_ts: number | null;
  error: string | null;
  w: number | null;
  h: number | null;
}

export interface Camera {
  id: string;
  area_id: number | null;
  area_name: string | null;
  site_id: number | null;
  name: string;
  description: string;
  source_type: SourceType;
  source_url: string;
  analysis_fps: number;
  enabled: boolean;
  version: number;
  zones_count: number;
  rules_count: number;
  stream: StreamStatus;
  live_hls: string | null;
}

export interface CameraIn {
  id?: string | null;
  area_id: number | null;
  name: string;
  description?: string;
  source_type: SourceType;
  source_url: string;
  analysis_fps: number;
  enabled: boolean;
}

export interface Zone {
  id: number;
  camera_id: string;
  name: string;
  kind: ZoneKind;
  polygon: Point[];
  color: string | null;
  enabled: boolean;
}

export type ZoneIn = Omit<Zone, "id" | "camera_id">;

export interface Schedule {
  days: number[]; // 0 — понедельник
  from?: string | null; // "ЧЧ:ММ"
  to?: string | null;
}

export interface Rule {
  id: number;
  camera_id: string;
  scenario: string;
  zone_id: number | null;
  params: Record<string, unknown>;
  severity: Severity | null;
  schedule: Schedule | null;
  valid_until: string | null;
  enabled: boolean;
}

export type RuleIn = Omit<Rule, "id" | "camera_id">;

export interface CameraDetail extends Camera {
  zones: Zone[];
  rules: Rule[];
}

export interface TreeArea {
  id: number;
  site_id: number;
  name: string;
  cameras: Camera[];
}

export interface TreeSite {
  id: number;
  name: string;
  address: string;
  areas: TreeArea[];
}

export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema & { default?: unknown; minimum?: number; maximum?: number; enum?: unknown[] }>;
  [k: string]: unknown;
}

export interface ScenarioInfo {
  code: string;
  title: string;
  description: string;
  requires: string[];
  severity: Severity;
  per_track: boolean;
  zone_required: boolean;
  params_schema: JsonSchema;
}

// --- inference / ingest ---------------------------------------------------------------

export interface ModelInfo {
  name?: string;
  version?: string;
  input?: number[] | string | null;
  program?: string | null;
  preset?: string | null;
  [k: string]: unknown;
}

export interface ModelsOut {
  backend?: string;
  active_backend: string;
  url?: string;
  error?: string;
  // есть только у FallbackDetector (INFERENCE_FALLBACK задан)
  fallback?: { active: boolean; backend: string; last_error: string | null };
  models?: ModelInfo[];
  consume: boolean;
  shards: number[];
  fps: number;
  [k: string]: unknown;
}

export interface LatencyStat {
  p50: number;
  p95: number;
  mean?: number;
}

export interface BenchmarkReport {
  model: string;
  program?: string | null;
  backend: string;
  batch: number;
  input?: unknown;
  runs?: number;
  measured_at: string;
  latency_ms: Record<string, LatencyStat>;
  fps: number;
  source?: string;
}

export interface BenchmarkIn {
  runs: number;
  warmup: number;
  camera_id?: string | null;
}

export interface IngestStream {
  camera_id: string;
  state: string;
  fps: number;
  target_fps?: number;
  frames?: number;
  error?: string | null;
  [k: string]: unknown;
}
