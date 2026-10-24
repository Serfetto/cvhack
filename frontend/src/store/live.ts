import { create } from "zustand";
import type { EventOut, WsMessage } from "@/api/types";
import { freshAccess, refreshAccess } from "@/api/client";
import { wsUrl } from "@/env";

export type LinkState = "idle" | "connecting" | "online" | "offline";
type EventMsg = Extract<WsMessage, { event: EventOut }>;
type Listener = (m: EventMsg) => void;

const MAX_EVENTS = 400;

interface LiveState {
  link: LinkState;
  lastMessageAt: number | null;
  events: Record<string, EventOut>;
  /** id событий, пришедших за эту сессию (подсветка «новое» в ленте) */
  fresh: Record<string, number>;
  seed: (items: EventOut[]) => void;
  upsert: (e: EventOut) => void;
  connect: () => void;
  disconnect: () => void;
  /** переподключиться сейчас, не дожидаясь бэкоффа */
  retry: () => void;
  subscribe: (fn: Listener) => () => void;
}

let socket: WebSocket | null = null;
let wanted = false;
let attempt = 0;
let reconnectTimer: number | undefined;
let pingTimer: number | undefined;
let watchdog: number | undefined;
const listeners = new Set<Listener>();

function trim(events: Record<string, EventOut>): Record<string, EventOut> {
  const ids = Object.keys(events);
  if (ids.length <= MAX_EVENTS) return events;
  // выбрасываем самые старые, но непринятые держим всегда
  const sorted = ids.sort((a, b) => events[b].started_at.localeCompare(events[a].started_at));
  const out: Record<string, EventOut> = {};
  sorted.forEach((id, i) => {
    if (i < MAX_EVENTS || events[id].status === "new") out[id] = events[id];
  });
  return out;
}

export const useLive = create<LiveState>()((set, get) => {
  function clearTimers() {
    window.clearTimeout(reconnectTimer);
    window.clearInterval(pingTimer);
    window.clearTimeout(watchdog);
  }

  function armWatchdog() {
    window.clearTimeout(watchdog);
    // сервер шлёт ping раз в 25 с; тишина 60 с — соединение мёртвое, хотя close не пришёл
    watchdog = window.setTimeout(() => socket?.close(4000, "watchdog"), 60_000);
  }

  function scheduleReconnect(needRefresh: boolean) {
    if (!wanted) return;
    set({ link: "offline" });
    const delay = Math.min(15_000, 1000 * 2 ** attempt) + Math.random() * 500;
    attempt += 1;
    reconnectTimer = window.setTimeout(async () => {
      if (needRefresh) await refreshAccess();
      open();
    }, delay);
  }

  async function open() {
    if (!wanted) return;
    const token = await freshAccess();
    if (!token) {
      set({ link: "offline" });
      return;
    }
    set({ link: "connecting" });
    let opened = false;
    const ws = new WebSocket(wsUrl(token));
    socket = ws;

    ws.onopen = () => {
      opened = true;
      attempt = 0;
      set({ link: "online", lastMessageAt: Date.now() });
      armWatchdog();
      pingTimer = window.setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 20_000);
    };

    ws.onmessage = (ev) => {
      armWatchdog();
      set({ lastMessageAt: Date.now() });
      let msg: WsMessage;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "event.created" || msg.type === "event.updated" || msg.type === "event.escalated") {
        const isNew = msg.type === "event.created" && !get().events[msg.event.id];
        get().upsert(msg.event);
        if (isNew) set((s) => ({ fresh: { ...s.fresh, [msg.event.id]: Date.now() } }));
        listeners.forEach((fn) => fn(msg as EventMsg));
      }
    };

    ws.onclose = (ev) => {
      if (socket !== ws) return;
      clearTimers();
      socket = null;
      // отказ в рукопожатии (403 → 1006 до open) или 4401 — токен истёк: обновить и переподключиться
      scheduleReconnect(!opened || ev.code === 4401 || ev.code === 1008);
    };
  }

  return {
    link: "idle",
    lastMessageAt: null,
    events: {},
    fresh: {},

    seed: (items) =>
      set((s) => {
        const events = { ...s.events };
        for (const e of items) {
          const cur = events[e.id];
          // REST-ответ может быть старее, чем уже пришедшее по WS обновление
          if (!cur || cur.status === e.status || e.status !== "new") events[e.id] = e;
        }
        return { events: trim(events) };
      }),

    upsert: (e) => set((s) => ({ events: trim({ ...s.events, [e.id]: { ...s.events[e.id], ...e } }) })),

    connect: () => {
      if (wanted) return;
      wanted = true;
      attempt = 0;
      open();
    },

    retry: () => {
      if (!wanted || socket) return;
      window.clearTimeout(reconnectTimer);
      attempt = 0;
      open();
    },

    disconnect: () => {
      wanted = false;
      clearTimers();
      const ws = socket;
      socket = null;
      ws?.close(1000, "logout");
      set({ link: "idle", events: {}, fresh: {} });
    },

    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
});

// при возвращении сети — переподключиться сразу, не дожидаясь бэкоффа
window.addEventListener("online", () => useLive.getState().retry());
