export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";

/** Адрес WebSocket ленты: тот же хост, что у страницы (в dev Vite проксирует /ws на шлюз). */
export function wsUrl(token: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws?access_token=${encodeURIComponent(token)}`;
}

export const GRAFANA_URL = import.meta.env.VITE_GRAFANA_URL || `${location.protocol}//${location.hostname}:3000`;
