import { Badge, Button, Tooltip } from "antd";
import { useLive } from "@/store/live";
import { fromNow, dayjs } from "@/shared/format";

const LABEL = {
  online: { text: "На связи", status: "success" as const },
  connecting: { text: "Подключение…", status: "processing" as const },
  offline: { text: "Нет связи", status: "error" as const },
  idle: { text: "Не подключено", status: "default" as const },
};

export default function ConnectionBadge({ compact }: { compact?: boolean }) {
  const link = useLive((s) => s.link);
  const last = useLive((s) => s.lastMessageAt);
  const retry = useLive((s) => s.retry);
  const l = LABEL[link];
  const hint =
    link === "online"
      ? `Лента событий в реальном времени. Последнее сообщение ${last ? fromNow(dayjs(last).toISOString()) : "—"}`
      : link === "offline"
        ? "Соединение потеряно — переподключаемся автоматически. Нажмите, чтобы попробовать сейчас"
        : l.text;
  return (
    <Tooltip title={hint}>
      <Button type="text" size="small" className={`conn conn-${link}`} onClick={link === "offline" ? retry : undefined}>
        <Badge status={l.status} text={compact ? undefined : l.text} />
      </Button>
    </Tooltip>
  );
}
