import { Tag, Tooltip } from "antd";
import {
  AlertOutlined, CarOutlined, ExclamationCircleOutlined, FireOutlined, FallOutlined, MobileOutlined, StopOutlined,
  ThunderboltOutlined, WarningOutlined, ColumnHeightOutlined, CheckCircleOutlined, CloseCircleOutlined, SendOutlined,
  ClockCircleOutlined, SafetyOutlined,
} from "@ant-design/icons";
import type { EventStatus, Severity } from "@/api/types";
import { SEVERITY, STATUS } from "@/shared/severity";

const SCENARIO_ICON: Record<string, JSX.Element> = {
  fall: <FallOutlined />,
  immobile: <FallOutlined />,
  proximity: <CarOutlined />,
  running: <ThunderboltOutlined />,
  phone: <MobileOutlined />,
  smoking: <FireOutlined />,
  fire: <FireOutlined />,
  in_zone: <StopOutlined />,
  climb: <ColumnHeightOutlined />,
  height: <ColumnHeightOutlined />,
};

export function ScenarioIcon({ code }: { code: string }) {
  return SCENARIO_ICON[code] || <WarningOutlined />;
}

const SEV_ICON: Record<Severity, JSX.Element> = {
  critical: <AlertOutlined />,
  high: <ExclamationCircleOutlined />,
  medium: <WarningOutlined />,
  low: <SafetyOutlined />,
};

export function SeverityTag({ value, compact }: { value: Severity; compact?: boolean }) {
  const s = SEVERITY[value];
  return (
    <Tag
      bordered={false}
      icon={SEV_ICON[value]}
      style={{ color: s.color, background: s.bg, fontWeight: 600, marginInlineEnd: 0 }}
    >
      {compact ? s.short : s.title}
    </Tag>
  );
}

const STATUS_ICON: Record<EventStatus, JSX.Element> = {
  new: <ClockCircleOutlined />,
  confirmed: <CheckCircleOutlined />,
  false: <CloseCircleOutlined />,
  forwarded: <SendOutlined />,
  resolved: <SafetyOutlined />,
};

export function StatusTag({ value }: { value: EventStatus }) {
  const s = STATUS[value];
  return (
    <Tag bordered={false} icon={STATUS_ICON[value]} color={value === "new" ? "processing" : undefined}
      style={value === "new" ? { marginInlineEnd: 0 } : { color: s.color, background: `${s.color}18`, marginInlineEnd: 0 }}>
      {s.title}
    </Tag>
  );
}

export function StatusIcon({ value }: { value: EventStatus }) {
  return STATUS_ICON[value];
}

export function DemoTag() {
  return (
    <Tooltip title="Событие из демо-истории (POST /demo/seed), не с камеры">
      <Tag bordered={false} style={{ marginInlineEnd: 0 }}>демо</Tag>
    </Tooltip>
  );
}
