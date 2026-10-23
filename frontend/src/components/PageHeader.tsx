import type { ReactNode } from "react";
import { Typography } from "antd";

export default function PageHeader({ title, subtitle, extra }: { title: ReactNode; subtitle?: ReactNode; extra?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>{title}</Typography.Title>
        {subtitle && <div className="muted page-subtitle">{subtitle}</div>}
      </div>
      {extra && <div className="page-header-extra">{extra}</div>}
    </div>
  );
}
