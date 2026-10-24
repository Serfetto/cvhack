import type { EventStatus, Severity, ZoneKind } from "@/api/types";

// Единые цвета важности (status palette: critical / serious / warning / нейтральный) — всегда вместе с иконкой и подписью
export const SEVERITY: Record<Severity, { title: string; short: string; color: string; bg: string; rank: number }> = {
  critical: { title: "Критическое", short: "Критично", color: "#d03b3b", bg: "rgba(208,59,59,0.12)", rank: 3 },
  high: { title: "Высокая", short: "Высокая", color: "#ec835a", bg: "rgba(236,131,90,0.14)", rank: 2 },
  medium: { title: "Средняя", short: "Средняя", color: "#e0a10f", bg: "rgba(250,178,25,0.16)", rank: 1 },
  low: { title: "Низкая", short: "Низкая", color: "#8a8f98", bg: "rgba(138,143,152,0.14)", rank: 0 },
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export const STATUS: Record<EventStatus, { title: string; action: string; color: string }> = {
  new: { title: "Новое", action: "Вернуть в новые", color: "#2563eb" },
  confirmed: { title: "Подтверждено", action: "Подтвердить", color: "#d03b3b" },
  false: { title: "Ложное", action: "Ложное", color: "#8a8f98" },
  forwarded: { title: "Передано мастеру", action: "Передать мастеру", color: "#7c3aed" },
  resolved: { title: "Устранено", action: "Устранено", color: "#0ca30c" },
};

export const STATUS_ORDER: EventStatus[] = ["new", "forwarded", "confirmed", "resolved", "false"];

export const ZONE_KIND: Record<ZoneKind, { title: string; color: string }> = {
  danger: { title: "Опасная зона", color: "#ef4444" },
  forbidden: { title: "Запретная зона", color: "#a855f7" },
  height: { title: "Работа на высоте", color: "#f59e0b" },
  fence: { title: "Ограждение", color: "#0ea5e9" },
  no_smoking: { title: "Не курить", color: "#10b981" },
};

// Категориальная палитра (фиксированный порядок, проверена на дальтонизм) — для типов нарушений на графиках
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
