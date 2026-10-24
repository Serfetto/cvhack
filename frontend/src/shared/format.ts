import dayjs from "dayjs";
import "dayjs/locale/ru";
import relativeTime from "dayjs/plugin/relativeTime";
import duration from "dayjs/plugin/duration";

dayjs.extend(relativeTime);
dayjs.extend(duration);
dayjs.locale("ru");

export const fmtTime = (s?: string | null) => (s ? dayjs(s).format("HH:mm:ss") : "—");
export const fmtDateTime = (s?: string | null) => (s ? dayjs(s).format("DD.MM.YYYY HH:mm:ss") : "—");
export const fmtShort = (s?: string | null) => {
  if (!s) return "—";
  const d = dayjs(s);
  return d.isSame(dayjs(), "day") ? d.format("HH:mm:ss") : d.format("DD.MM HH:mm");
};
export const fromNow = (s?: string | null) => (s ? dayjs(s).fromNow() : "—");

export function fmtDuration(sec?: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  if (sec < 60) return `${Math.round(sec)} с`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m < 60) return s ? `${m} мин ${s} с` : `${m} мин`;
  return `${Math.floor(m / 60)} ч ${m % 60} мин`;
}

export function eventDuration(start: string, end?: string | null): string {
  if (!end) return "продолжается";
  return fmtDuration((dayjs(end).valueOf() - dayjs(start).valueOf()) / 1000);
}

export const pct = (v?: number | null, digits = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`);

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

export const DOW = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export { dayjs };
