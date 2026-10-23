import type { ReactNode } from "react";
import { Card, Skeleton, Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";

interface Props {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  accent?: string;
  sub?: ReactNode;
  loading?: boolean;
  onClick?: () => void;
}

export default function StatTile({ label, value, hint, icon, accent = "#2563eb", sub, loading, onClick }: Props) {
  return (
    <Card className={`stat-tile ${onClick ? "clickable" : ""}`} onClick={onClick} variant="borderless">
      <div className="stat-top">
        <span className="stat-icon" style={{ color: accent, background: `${accent}1a` }}>{icon}</span>
        <span className="stat-label">
          {label}
          {hint && <Tooltip title={hint}><InfoCircleOutlined className="muted" style={{ marginLeft: 6 }} /></Tooltip>}
        </span>
      </div>
      {loading ? <Skeleton.Input active size="small" style={{ marginTop: 10 }} /> : <div className="stat-value">{value}</div>}
      {sub && <div className="stat-sub">{sub}</div>}
    </Card>
  );
}
