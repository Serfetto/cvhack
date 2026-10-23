import { useEffect, useMemo, useRef, useState } from "react";
import { Circle, Group, Image as KImage, Label, Layer, Line, Rect, Stage, Tag as KTag, Text } from "react-konva";
import type Konva from "konva";
import type { Point, ZoneKind } from "@/api/types";
import { ZONE_KIND } from "@/shared/severity";

export interface ZoneDraft {
  key: string;
  id?: number;
  name: string;
  kind: ZoneKind;
  polygon: Point[];
  enabled: boolean;
  color: string | null;
  dirty?: boolean;
}

interface Props {
  image: HTMLImageElement | null;
  zones: ZoneDraft[];
  selected: string | null;
  onSelect: (key: string | null) => void;
  onChange: (key: string, polygon: Point[]) => void;
  drawing: boolean;
  onDrawn: (polygon: Point[]) => void;
  onCancelDraw: () => void;
  showMask: boolean;
}

const round = (v: number) => Math.round(Math.min(Math.max(v, 0), 1) * 10000) / 10000;
const zoneColor = (z: ZoneDraft) => z.color || ZONE_KIND[z.kind]?.color || "#ef4444";

/**
 * Редактор полигонов поверх кадра камеры. Координаты хранятся в долях 0..1,
 * в пиксели переводятся только при отрисовке по фактическому размеру сцены.
 */
export default function ZoneEditor({ image, zones, selected, onSelect, onChange, drawing, onDrawn, onCancelDraw, showMask }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [draft, setDraft] = useState<Point[]>([]);
  const [cursor, setCursor] = useState<Point | null>(null);
  const [vertex, setVertex] = useState<number | null>(null);
  const lastClick = useRef<{ t: number; x: number; y: number } | null>(null);
  const aspect = image ? image.naturalWidth / image.naturalHeight || 16 / 9 : 16 / 9;
  const height = Math.round(width / aspect);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, Math.floor(e.contentRect.width))));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!drawing) {
      setDraft([]);
      setCursor(null);
    }
  }, [drawing]);

  useEffect(() => setVertex(null), [selected]);

  const toPx = (p: Point) => [p[0] * width, p[1] * height];
  const flat = (pts: Point[]) => pts.flatMap(toPx);
  const norm = (x: number, y: number): Point => [round(x / width), round(y / height)];

  const sel = zones.find((z) => z.key === selected);

  const finish = () => {
    if (draft.length < 3) return;
    onDrawn(draft);
    setDraft([]);
  };

  // клавиатура: Enter — замкнуть, Esc — отменить, Backspace — убрать последнюю точку, Delete — удалить выбранную вершину
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, [contenteditable]")) return;
      if (drawing) {
        if (e.key === "Enter") finish();
        if (e.key === "Escape") onCancelDraw();
        if (e.key === "Backspace") setDraft((d) => d.slice(0, -1));
      } else if (sel && vertex !== null && (e.key === "Delete" || e.key === "Backspace") && sel.polygon.length > 3) {
        onChange(sel.key, sel.polygon.filter((_, i) => i !== vertex));
        setVertex(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const stageClick = (e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
    const pos = e.target.getStage()?.getPointerPosition();
    if (!pos) return;
    if (drawing) {
      // двойной клик в одной точке — замкнуть; Konva-шный dblclick не годится: срабатывает и на два быстрых клика в разных местах
      const now = Date.now();
      const prev = lastClick.current;
      lastClick.current = { t: now, x: pos.x, y: pos.y };
      if (prev && now - prev.t < 350 && Math.hypot(pos.x - prev.x, pos.y - prev.y) < 8) {
        finish();
        return;
      }
      setDraft((d) => [...d, norm(pos.x, pos.y)]);
      return;
    }
    if (e.target === e.target.getStage() || e.target.name() === "bg") onSelect(null);
  };

  const removeVertex = (i: number) => {
    if (!sel || sel.polygon.length <= 3) return;
    onChange(sel.key, sel.polygon.filter((_, j) => j !== i));
    setVertex(null);
  };

  const midpoints = useMemo(() => {
    if (!sel || drawing) return [];
    return sel.polygon.map((p, i) => {
      const q = sel.polygon[(i + 1) % sel.polygon.length];
      return { i, p: [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] as Point };
    });
  }, [sel, drawing]);

  const fontSize = width < 600 ? 11 : 13;

  return (
    <div ref={wrap} className={`zone-editor ${drawing ? "is-drawing" : ""}`}>
      <Stage
        width={width}
        height={height}
        onMouseDown={stageClick}
        onTouchStart={stageClick}
        onMouseMove={(e) => {
          if (!drawing) return;
          const pos = e.target.getStage()?.getPointerPosition();
          if (pos) setCursor(norm(pos.x, pos.y));
        }}
        onContextMenu={(e) => e.evt.preventDefault()}
      >
        <Layer listening>
          {image ? (
            <KImage name="bg" image={image} width={width} height={height} />
          ) : (
            <Rect name="bg" width={width} height={height} fill="#1f2937" />
          )}
        </Layer>

        {showMask && (
          <Layer listening={false}>
            <Rect width={width} height={height} fill="rgba(2,6,23,0.62)" />
            {zones.filter((z) => z.enabled).map((z) => (
              <Line key={z.key} points={flat(z.polygon)} closed fill="#000" globalCompositeOperation="destination-out" />
            ))}
          </Layer>
        )}

        <Layer>
          {zones.map((z) => {
            const c = zoneColor(z);
            const isSel = z.key === selected;
            const [lx, ly] = toPx(z.polygon.reduce((a, p) => (p[1] < a[1] ? p : a), z.polygon[0]));
            return (
              <Group key={z.key}>
                <Line
                  points={flat(z.polygon)}
                  closed
                  fill={`${c}${isSel ? "40" : showMask ? "10" : "2a"}`}
                  stroke={c}
                  strokeWidth={isSel ? 3 : 2}
                  dash={z.enabled ? undefined : [8, 6]}
                  shadowColor={c}
                  shadowBlur={isSel ? 12 : 0}
                  shadowOpacity={0.6}
                  draggable={isSel && !drawing}
                  onMouseDown={(e) => {
                    if (drawing) return;
                    e.cancelBubble = true;
                    onSelect(z.key);
                  }}
                  onTap={(e) => { if (!drawing) { e.cancelBubble = true; onSelect(z.key); } }}
                  onDragEnd={(e) => {
                    const dx = e.target.x() / width;
                    const dy = e.target.y() / height;
                    e.target.position({ x: 0, y: 0 });
                    onChange(z.key, z.polygon.map(([x, y]) => [round(x + dx), round(y + dy)]));
                  }}
                  onMouseEnter={(e) => { if (!drawing) e.target.getStage()!.container().style.cursor = isSel ? "move" : "pointer"; }}
                  onMouseLeave={(e) => { e.target.getStage()!.container().style.cursor = ""; }}
                />
                <Label x={lx} y={Math.max(0, ly - fontSize - 12)} listening={false}>
                  <KTag fill={c} cornerRadius={4} opacity={0.92} />
                  <Text text={`${z.name}${z.dirty ? " •" : ""}`} fontSize={fontSize} fontStyle="600" padding={5} fill="#fff" />
                </Label>
              </Group>
            );
          })}

          {sel && !drawing && (
            <Group>
              {midpoints.map(({ i, p }) => {
                const [x, y] = toPx(p);
                return (
                  <Circle key={`m${i}`} x={x} y={y} radius={5} fill="#fff" opacity={0.55} stroke={zoneColor(sel)} strokeWidth={1}
                    onMouseDown={(e) => {
                      e.cancelBubble = true;
                      const pts = [...sel.polygon];
                      pts.splice(i + 1, 0, p);
                      onChange(sel.key, pts);
                      setVertex(i + 1);
                    }}
                    onMouseEnter={(e) => { e.target.getStage()!.container().style.cursor = "copy"; }}
                    onMouseLeave={(e) => { e.target.getStage()!.container().style.cursor = ""; }}
                  />
                );
              })}
              {sel.polygon.map((p, i) => {
                const [x, y] = toPx(p);
                return (
                  <Circle key={`v${i}`} x={x} y={y} radius={vertex === i ? 8 : 7} fill={vertex === i ? zoneColor(sel) : "#fff"}
                    stroke={zoneColor(sel)} strokeWidth={2.5} draggable hitStrokeWidth={14}
                    dragBoundFunc={(pos) => ({ x: Math.min(Math.max(pos.x, 0), width), y: Math.min(Math.max(pos.y, 0), height) })}
                    onMouseDown={(e) => { e.cancelBubble = true; setVertex(i); }}
                    onDragMove={(e) => {
                      const pts = [...sel.polygon];
                      pts[i] = norm(e.target.x(), e.target.y());
                      onChange(sel.key, pts);
                    }}
                    onDblClick={(e) => { e.cancelBubble = true; removeVertex(i); }}
                    onContextMenu={(e) => { e.evt.preventDefault(); e.cancelBubble = true; removeVertex(i); }}
                    onMouseEnter={(e) => { e.target.getStage()!.container().style.cursor = "grab"; }}
                    onMouseLeave={(e) => { e.target.getStage()!.container().style.cursor = ""; }}
                  />
                );
              })}
            </Group>
          )}

          {drawing && draft.length > 0 && (
            <Group listening={draft.length >= 3}>
              <Line points={flat(cursor ? [...draft, cursor] : draft)} stroke="#38bdf8" strokeWidth={2} dash={[6, 4]} listening={false} />
              {draft.length >= 3 && <Line points={flat(draft)} closed fill="rgba(56,189,248,0.18)" listening={false} />}
              {draft.map((p, i) => {
                const [x, y] = toPx(p);
                const first = i === 0 && draft.length >= 3;
                return (
                  <Circle key={i} x={x} y={y} radius={first ? 9 : 5} fill={first ? "#38bdf8" : "#fff"} stroke="#0284c7" strokeWidth={2}
                    onMouseDown={(e) => { if (first) { e.cancelBubble = true; finish(); } }}
                    onMouseEnter={(e) => { if (first) e.target.getStage()!.container().style.cursor = "pointer"; }}
                    onMouseLeave={(e) => { e.target.getStage()!.container().style.cursor = ""; }}
                  />
                );
              })}
            </Group>
          )}
        </Layer>
      </Stage>
    </div>
  );
}
