// Синтетические кадры камер для моков: цех в перспективе, оборудование, «человек» в заданной рамке.
// Это SVG 1280×720 — <img> и Konva показывают его так же, как JPEG с камеры.
import type { BBox } from "@/api/types";

const W = 1280;
const H = 720;

interface Layout {
  wall: [string, string];
  floor: [string, string];
  machines: { x: number; y: number; w: number; h: number; color: string; label?: string }[];
  stripes?: { x: number; y: number; w: number; h: number }[];
}

const LAYOUTS: Record<string, Layout> = {
  "cam-01": {
    wall: ["#2b3442", "#1d2430"],
    floor: ["#4a4f57", "#2f3339"],
    machines: [
      { x: 40, y: 170, w: 380, h: 330, color: "#3d5a80", label: "ПРЕСС КД-2130" },
      { x: 860, y: 230, w: 160, h: 230, color: "#5c677d" },
      { x: 1050, y: 260, w: 200, h: 200, color: "#4a5568" },
    ],
    stripes: [{ x: 0, y: 500, w: 480, h: 14 }],
  },
  "cam-02": {
    wall: ["#30343c", "#22262d"],
    floor: ["#55585e", "#35383d"],
    machines: [
      { x: 60, y: 220, w: 220, h: 260, color: "#556270", label: "СТЕЛЛАЖ А" },
      { x: 300, y: 250, w: 180, h: 230, color: "#4f5b66" },
      { x: 880, y: 300, w: 230, h: 150, color: "#c08a1e", label: "ПОГРУЗЧИК" },
    ],
    stripes: [{ x: 760, y: 288, w: 14, h: 432 }],
  },
  "cam-03": {
    wall: ["#28303a", "#1b2129"],
    floor: ["#4b5058", "#2d3036"],
    machines: [
      { x: 420, y: 120, w: 440, h: 360, color: "#384656", label: "ВОРОТА №2" },
      { x: 60, y: 300, w: 180, h: 180, color: "#7a6a4f" },
      { x: 1020, y: 300, w: 200, h: 180, color: "#7a6a4f" },
    ],
  },
  "cam-04": {
    wall: ["#2d333b", "#20252b"],
    floor: ["#50545b", "#33363b"],
    machines: [
      { x: 40, y: 140, w: 260, h: 360, color: "#4a5a6a", label: "СТЕЛЛАЖ B" },
      { x: 330, y: 140, w: 260, h: 360, color: "#4a5a6a" },
      { x: 980, y: 140, w: 260, h: 360, color: "#4a5a6a", label: "СТЕЛЛАЖ C" },
    ],
  },
};

const DEFAULT_LAYOUT = LAYOUTS["cam-03"];

function person(b: BBox, vest = "#f97316", lying = false): string {
  const [x1, y1, x2, y2] = [b[0] * W, b[1] * H, b[2] * W, b[3] * H];
  const w = x2 - x1;
  const h = y2 - y1;
  if (lying) {
    const cy = y1 + h * 0.55;
    const r = Math.min(h, w * 0.2) * 0.32;
    return `<g>
      <ellipse cx="${x1 + w / 2}" cy="${y2 - 4}" rx="${w * 0.5}" ry="${h * 0.12}" fill="rgba(0,0,0,0.35)"/>
      <circle cx="${x1 + r * 1.2}" cy="${cy}" r="${r}" fill="#e8c4a0"/>
      <rect x="${x1 + r * 2.3}" y="${cy - h * 0.22}" width="${w * 0.42}" height="${h * 0.44}" rx="${h * 0.15}" fill="${vest}"/>
      <rect x="${x1 + r * 2.3 + w * 0.4}" y="${cy - h * 0.16}" width="${w * 0.4}" height="${h * 0.32}" rx="${h * 0.12}" fill="#1f2a44"/>
    </g>`;
  }
  const r = w * 0.24;
  return `<g>
    <ellipse cx="${x1 + w / 2}" cy="${y2}" rx="${w * 0.55}" ry="${h * 0.04}" fill="rgba(0,0,0,0.35)"/>
    <rect x="${x1 + w * 0.22}" y="${y1 + h * 0.55}" width="${w * 0.22}" height="${h * 0.45}" rx="${w * 0.08}" fill="#1f2a44"/>
    <rect x="${x1 + w * 0.56}" y="${y1 + h * 0.55}" width="${w * 0.22}" height="${h * 0.45}" rx="${w * 0.08}" fill="#1f2a44"/>
    <rect x="${x1 + w * 0.1}" y="${y1 + h * 0.2}" width="${w * 0.8}" height="${h * 0.42}" rx="${w * 0.2}" fill="${vest}"/>
    <rect x="${x1 + w * 0.1}" y="${y1 + h * 0.36}" width="${w * 0.8}" height="${h * 0.04}" fill="#e5e7eb" opacity="0.9"/>
    <circle cx="${x1 + w / 2}" cy="${y1 + r}" r="${r}" fill="#e8c4a0"/>
    <path d="M${x1 + w / 2 - r} ${y1 + r * 0.9} a${r} ${r} 0 0 1 ${2 * r} 0 z" fill="#facc15"/>
  </g>`;
}

export interface SceneOpts {
  cameraId: string;
  cameraName?: string;
  persons?: { bbox: BBox; lying?: boolean; vest?: string }[];
  boxes?: { bbox: BBox; label: string; color: string }[];
  time?: Date;
}

export function sceneSvg(o: SceneOpts): string {
  const L = LAYOUTS[o.cameraId] || DEFAULT_LAYOUT;
  const t = o.time || new Date();
  const ts = `${t.toLocaleDateString("ru-RU")} ${t.toLocaleTimeString("ru-RU")}`;
  const horizon = 300;
  const floorLines = Array.from({ length: 9 }, (_, i) => {
    const x = (i / 8) * W;
    return `<line x1="${W / 2 + (x - W / 2) * 0.25}" y1="${horizon}" x2="${x}" y2="${H}" stroke="rgba(255,255,255,0.06)" stroke-width="2"/>`;
  }).join("");
  const rows = Array.from({ length: 6 }, (_, i) => {
    const y = horizon + (H - horizon) * ((i + 1) / 6) ** 1.6;
    return `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="2"/>`;
  }).join("");
  const machines = L.machines
    .map(
      (m) => `<g>
      <rect x="${m.x}" y="${m.y}" width="${m.w}" height="${m.h}" rx="6" fill="${m.color}"/>
      <rect x="${m.x}" y="${m.y}" width="${m.w}" height="${m.h * 0.12}" rx="6" fill="rgba(255,255,255,0.08)"/>
      <rect x="${m.x + m.w * 0.1}" y="${m.y + m.h * 0.25}" width="${m.w * 0.35}" height="${m.h * 0.2}" rx="3" fill="rgba(0,0,0,0.25)"/>
      <rect x="${m.x}" y="${m.y + m.h - 10}" width="${m.w}" height="10" fill="rgba(0,0,0,0.35)"/>
      ${m.label ? `<text x="${m.x + 14}" y="${m.y + m.h * 0.08 + 6}" font-family="monospace" font-size="16" fill="rgba(255,255,255,0.55)">${m.label}</text>` : ""}
    </g>`,
    )
    .join("");
  const stripes = (L.stripes || [])
    .map(
      (s) =>
        `<rect x="${s.x}" y="${s.y}" width="${s.w}" height="${s.h}" fill="url(#hazard)"/>`,
    )
    .join("");
  const people = (o.persons || []).map((p) => person(p.bbox, p.vest, p.lying)).join("");
  const boxes = (o.boxes || [])
    .map((b) => {
      const [x1, y1, x2, y2] = [b.bbox[0] * W, b.bbox[1] * H, b.bbox[2] * W, b.bbox[3] * H];
      return `<g><rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" fill="none" stroke="${b.color}" stroke-width="4"/>
        <rect x="${x1}" y="${y1 - 30}" width="${b.label.length * 10 + 20}" height="30" fill="${b.color}"/>
        <text x="${x1 + 10}" y="${y1 - 9}" font-family="sans-serif" font-size="17" font-weight="600" fill="#fff">${b.label}</text></g>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${L.wall[0]}"/><stop offset="1" stop-color="${L.wall[1]}"/></linearGradient>
    <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${L.floor[1]}"/><stop offset="1" stop-color="${L.floor[0]}"/></linearGradient>
    <radialGradient id="light" cx="0.5" cy="0" r="0.9"><stop offset="0" stop-color="rgba(255,240,200,0.18)"/><stop offset="1" stop-color="rgba(0,0,0,0)"/></radialGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75"><stop offset="0.6" stop-color="rgba(0,0,0,0)"/><stop offset="1" stop-color="rgba(0,0,0,0.55)"/></radialGradient>
    <pattern id="hazard" width="28" height="28" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="14" height="28" fill="#facc15"/><rect x="14" width="14" height="28" fill="#111"/></pattern>
  </defs>
  <rect width="${W}" height="${horizon}" fill="url(#wall)"/>
  <rect y="${horizon}" width="${W}" height="${H - horizon}" fill="url(#floor)"/>
  ${[160, 480, 800, 1120].map((x) => `<rect x="${x - 60}" y="20" width="120" height="10" rx="5" fill="rgba(255,250,230,0.7)"/>`).join("")}
  ${floorLines}${rows}${stripes}${machines}${people}
  <rect width="${W}" height="${H}" fill="url(#light)"/>
  <rect width="${W}" height="${H}" fill="url(#vignette)"/>
  ${boxes}
  <rect x="16" y="${H - 48}" width="${ts.length * 11 + 150}" height="32" rx="4" fill="rgba(0,0,0,0.55)"/>
  <text x="28" y="${H - 26}" font-family="monospace" font-size="18" fill="#e5e7eb">${o.cameraId.toUpperCase()}  ${ts}</text>
  <circle cx="${W - 36}" cy="34" r="8" fill="#ef4444"/><text x="${W - 92}" y="40" font-family="monospace" font-size="18" fill="#fca5a5">REC</text>
</svg>`;
}

/** Человек, бродящий по кадру: позиция зависит от времени — при «Обновить кадр» он сдвигается. */
export function walkerBBox(cameraId: string, tMs = Date.now()): BBox {
  const seed = cameraId.charCodeAt(cameraId.length - 1);
  const p = ((tMs / 1000 + seed * 7) % 40) / 40;
  const x = 0.08 + 0.78 * (p < 0.5 ? p * 2 : 2 - p * 2);
  const y = 0.5 + 0.12 * Math.sin(p * Math.PI * 2);
  const h = 0.32 + (y - 0.5) * 0.6;
  return [x, y, x + h * 0.32, y + h].map((v) => Math.min(Math.max(v, 0), 1)) as BBox;
}
