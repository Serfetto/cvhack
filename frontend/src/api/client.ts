import type { TokenOut } from "./types";
import { tokenExp, useAuth } from "@/store/auth";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

/** Массивы уходят повторяющимися параметрами: ?camera_id=a&camera_id=b — так их ждёт FastAPI. */
export function toQuery(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  if (status === 403) return "Недостаточно прав";
  if (status === 404) return "Не найдено";
  if (status >= 500) return "Сервис временно недоступен";
  return `Ошибка ${status}`;
}

// --- обновление токена: один запрос на всех, сколько бы 401 ни пришло одновременно ---------

let refreshing: Promise<string | null> | null = null;

export function refreshAccess(): Promise<string | null> {
  if (refreshing) return refreshing;
  const { refresh, setTokens, clear } = useAuth.getState();
  if (!refresh) return Promise.resolve(null);
  refreshing = fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  })
    .then(async (r) => {
      if (!r.ok) throw new Error("refresh failed");
      const t = (await r.json()) as TokenOut;
      setTokens(t);
      return t.access_token;
    })
    .catch(() => {
      clear();
      return null;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** Действующий access-токен: если до истечения меньше 30 с — сначала обновить. */
export async function freshAccess(): Promise<string | null> {
  const { access } = useAuth.getState();
  const exp = tokenExp(access);
  if (access && exp && exp * 1000 - Date.now() < 30_000) return refreshAccess();
  return access;
}

interface Opts {
  method?: string;
  query?: Query;
  body?: unknown;
  raw?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const token = await freshAccess();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}${toQuery(opts.query)}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  if (res.status === 401 && !retried && useAuth.getState().refresh) {
    const t = await refreshAccess();
    if (t) return request<T>(path, opts, true);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, errorMessage(res.status, body), body);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
  del: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Скачать файл с авторизацией (CSV журнала): fetch → blob → <a download>. */
export async function download(path: string, query: Query, fallbackName: string): Promise<void> {
  const res = await request<Response>(path, { query, raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const name = /filename="?([^";]+)"?/.exec(cd)?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** URL с токеном в query — для <img>/<video>, которые не умеют слать заголовки. */
export function withToken(url: string): string {
  const t = useAuth.getState().access;
  if (!t) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(t)}`;
}
