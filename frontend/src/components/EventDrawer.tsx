import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert, App, Button, Descriptions, Divider, Drawer, Empty, Grid, Input, Skeleton, Space, Timeline, Tooltip, Typography,
} from "antd";
import { CopyOutlined, LinkOutlined, LoadingOutlined, VideoCameraOutlined } from "@ant-design/icons";
import type { EventAction, EventDetail, EventStatus } from "@/api/types";
import { useAddComment, useDirectory, useEvent, useSetStatus } from "@/api/hooks";
import { useLive } from "@/store/live";
import { useAuth } from "@/store/auth";
import { CAN, can } from "@/shared/roles";
import { SEVERITY, STATUS } from "@/shared/severity";
import { eventDuration, fmtDateTime, fromNow } from "@/shared/format";
import EventSnapshot from "./EventSnapshot";
import { DemoTag, ScenarioIcon, SeverityTag, StatusIcon, StatusTag } from "./Tags";

/** Открыть карточку события из любого экрана: ?event=<id> в URL — ссылкой можно поделиться. */
export function useOpenEvent() {
  const [params, setParams] = useSearchParams();
  return (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("event", id);
    else p.delete("event");
    setParams(p, { replace: !id });
  };
}

function actionText(a: EventAction): string {
  switch (a.action) {
    case "created":
      return "Событие создано системой";
    case "ended":
      return "Нарушение закончилось";
    case "escalated":
      return a.comment || "Эскалация: не принято вовремя";
    case "comment":
      return "Комментарий";
    case "status":
      return `${a.from_status ? STATUS[a.from_status as EventStatus]?.title : "—"} → ${STATUS[a.to_status as EventStatus]?.title || a.to_status}`;
    default:
      return a.action;
  }
}

function timelineColor(a: EventAction): string {
  if (a.action === "escalated") return "red";
  if (a.action === "status" && a.to_status) return STATUS[a.to_status as EventStatus]?.color || "blue";
  if (a.action === "comment") return "gray";
  return "blue";
}

function Clip({ e }: { e: EventDetail }) {
  const [failed, setFailed] = useState(false);
  if (e.clip_status === "pending")
    return <div className="clip-placeholder"><LoadingOutlined /> Клип готовится — появится через несколько секунд</div>;
  if (e.clip_status === "failed") return <div className="clip-placeholder muted">Клип не удалось собрать</div>;
  if (e.clip_status !== "ready" || !e.clip_url) return <div className="clip-placeholder muted">Клип не записывался</div>;
  if (failed)
    return (
      <div className="clip-placeholder muted">
        Клип недоступен для воспроизведения. <a href={e.clip_url} target="_blank" rel="noreferrer">Скачать</a>
      </div>
    );
  return <video className="clip" src={e.clip_url} controls preload="metadata" poster={e.snapshot_url || undefined} onError={() => setFailed(true)} />;
}

function StatusPanel({ e }: { e: EventDetail }) {
  const { message } = App.useApp();
  const [next, setNext] = useState<EventStatus | undefined>();
  const [comment, setComment] = useState("");
  const setStatus = useSetStatus();
  const addComment = useAddComment();

  const submit = () => {
    if (next) {
      setStatus.mutate({ id: e.id, status: next, comment: comment || null }, {
        onSuccess: () => {
          message.success(`Статус: ${STATUS[next].title}`);
          setNext(undefined);
          setComment("");
        },
        onError: (err) => message.error(err.message),
      });
    } else if (comment.trim()) {
      addComment.mutate({ id: e.id, comment }, { onSuccess: () => setComment(""), onError: (err) => message.error(err.message) });
    }
  };

  return (
    <div className="status-panel">
      <Space wrap style={{ marginBottom: 8 }}>
        {e.allowed_statuses.map((s) => (
          <Button key={s} size="middle" icon={<StatusIcon value={s} />} type={next === s ? "primary" : "default"}
            onClick={() => setNext(next === s ? undefined : s)}>
            {STATUS[s].action}
          </Button>
        ))}
      </Space>
      <Input.TextArea rows={2} value={comment} onChange={(ev) => setComment(ev.target.value)}
        placeholder={next ? `Комментарий к «${STATUS[next].title}» (необязательно)` : "Комментарий в историю события"} />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
        <Button type="primary" onClick={submit} disabled={!next && !comment.trim()} loading={setStatus.isPending || addComment.isPending}>
          {next ? `Сохранить: ${STATUS[next].title}` : "Добавить комментарий"}
        </Button>
      </div>
    </div>
  );
}

export default function EventDrawer() {
  const [params] = useSearchParams();
  const id = params.get("event");
  const open = useOpenEvent();
  const screens = Grid.useBreakpoint();
  const { message } = App.useApp();
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading, error } = useEvent(id);
  // свежие поля (окончание, клип, статус) приходят по WebSocket раньше, чем перезапрос карточки
  const live = useLive((s) => (id ? s.events[id] : undefined));
  const { areas } = useDirectory();
  const e: EventDetail | undefined = data ? { ...data, ...(live && live.status === data.status ? live : {}) } : undefined;

  const copyLink = () => {
    navigator.clipboard?.writeText(location.href);
    message.success("Ссылка на событие скопирована");
  };

  return (
    <Drawer
      open={!!id}
      onClose={() => open(null)}
      width={screens.md ? 720 : "100%"}
      destroyOnHidden
      title={
        e ? (
          <Space size={10} wrap>
            <span className="drawer-scenario-icon" style={{ color: SEVERITY[e.severity].color, background: SEVERITY[e.severity].bg }}>
              <ScenarioIcon code={e.scenario} />
            </span>
            <span>{e.scenario_title || e.scenario}</span>
          </Space>
        ) : "Событие"
      }
      extra={<Tooltip title="Скопировать ссылку"><Button type="text" icon={<LinkOutlined />} onClick={copyLink} /></Tooltip>}
    >
      {isLoading && <Skeleton active paragraph={{ rows: 10 }} />}
      {error && <Alert type="error" showIcon message="Не удалось загрузить событие" description={(error as Error).message} />}
      {e && (
        <>
          <Space wrap size={6} style={{ marginBottom: 12 }}>
            <SeverityTag value={e.severity} />
            <StatusTag value={e.status} />
            {e.escalated_at && <Typography.Text type="danger" strong>Эскалировано {fromNow(e.escalated_at)}</Typography.Text>}
            {e.demo && <DemoTag />}
          </Space>

          <EventSnapshot event={e} controls />

          <Divider orientation="left" plain><VideoCameraOutlined /> Клип</Divider>
          <Clip e={e} />

          {can(role, CAN.act) && (
            <>
              <Divider orientation="left" plain>Действие</Divider>
              <StatusPanel e={e} />
            </>
          )}

          <Divider orientation="left" plain>Детали</Divider>
          <Descriptions size="small" column={screens.sm ? 2 : 1} colon={false} styles={{ label: { color: "var(--muted)" } }}>
            <Descriptions.Item label="Камера">{e.camera_name || e.camera_id}</Descriptions.Item>
            <Descriptions.Item label="Участок">{e.area_id ? areas.get(e.area_id)?.name || `№${e.area_id}` : "—"}</Descriptions.Item>
            <Descriptions.Item label="Зона">{e.zone_name || "весь кадр"}</Descriptions.Item>
            <Descriptions.Item label="Уверенность">{e.confidence != null ? `${Math.round(e.confidence * 100)}%` : "—"}</Descriptions.Item>
            <Descriptions.Item label="Начало">{fmtDateTime(e.started_at)}</Descriptions.Item>
            <Descriptions.Item label="Окончание">{e.ended_at ? fmtDateTime(e.ended_at) : <Typography.Text type="warning">продолжается</Typography.Text>}</Descriptions.Item>
            <Descriptions.Item label="Длительность">{eventDuration(e.started_at, e.ended_at)}</Descriptions.Item>
            <Descriptions.Item label="Трек">#{e.track_id ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="SHA-256 кадра" span={2}>
              {e.snapshot_sha256 ? (
                <Typography.Text code copyable={{ text: e.snapshot_sha256, icon: <CopyOutlined /> }} style={{ fontSize: 12 }}>
                  {e.snapshot_sha256.slice(0, 24)}…
                </Typography.Text>
              ) : "—"}
            </Descriptions.Item>
          </Descriptions>

          <Divider orientation="left" plain>История</Divider>
          {e.actions.length ? (
            <Timeline
              items={e.actions.map((a) => ({
                color: timelineColor(a),
                children: (
                  <div>
                    <div><b>{actionText(a)}</b></div>
                    {a.comment && a.action !== "escalated" && <div className="timeline-comment">{a.comment}</div>}
                    <div className="muted small">{fmtDateTime(a.at)}{a.username ? ` · ${a.username}` : ""}</div>
                  </div>
                ),
              }))}
            />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Действий пока нет" />}
        </>
      )}
    </Drawer>
  );
}
