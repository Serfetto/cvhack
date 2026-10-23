import { useState } from "react";
import { Segmented, Skeleton, Switch } from "antd";
import { PictureOutlined } from "@ant-design/icons";
import type { EventOut } from "@/api/types";
import { SEVERITY } from "@/shared/severity";

interface Props {
  event: EventOut;
  controls?: boolean;
  height?: number | string;
  rounded?: boolean;
}

/** Кадр события с рамкой поверх. Рамка в долях 0..1 → проценты: пиксели не нужны, масштаб любой. */
export default function EventSnapshot({ event, controls, height, rounded = true }: Props) {
  const [showBox, setShowBox] = useState(true);
  const [variant, setVariant] = useState<"raw" | "annotated">("raw");
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const src = variant === "annotated" && event.annotated_url ? event.annotated_url : event.snapshot_url;
  const b = event.bbox;
  const color = SEVERITY[event.severity].color;

  return (
    <div>
      <div className={`snapshot ${rounded ? "snapshot-rounded" : ""}`} style={height ? { height } : undefined}>
        {!src || failed ? (
          <div className="snapshot-empty"><PictureOutlined /> Кадр недоступен</div>
        ) : (
          <div className="snapshot-frame">
            {!loaded && <Skeleton.Image active className="snapshot-skeleton" />}
            <img src={src} alt="Кадр нарушения" onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
              style={{ opacity: loaded ? 1 : 0 }} />
            {loaded && b && showBox && variant === "raw" && (
              <div className="bbox" style={{
                left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`,
                borderColor: color, boxShadow: `0 0 0 2px rgba(0,0,0,.35), 0 0 24px ${color}66`,
              }}>
                <span className="bbox-label" style={{ background: color }}>
                  {event.scenario_title || event.scenario}
                  {event.confidence != null && ` · ${Math.round(event.confidence * 100)}%`}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
      {controls && src && !failed && (
        <div className="snapshot-controls">
          {event.annotated_url && (
            <Segmented size="small" value={variant} onChange={(v) => setVariant(v as "raw" | "annotated")}
              options={[{ label: "Кадр + рамка", value: "raw" }, { label: "Разметка сервера", value: "annotated" }]} />
          )}
          {variant === "raw" && b && (
            <label className="muted small">
              <Switch size="small" checked={showBox} onChange={setShowBox} /> &nbsp;Рамка
            </label>
          )}
        </div>
      )}
    </div>
  );
}
