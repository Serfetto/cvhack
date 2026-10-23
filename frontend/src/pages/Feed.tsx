import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, Col, Empty, Grid, Row, Segmented, Select, Space, Tooltip, Typography } from "antd";
import { AlertOutlined, BellOutlined, ClockCircleOutlined, EnvironmentOutlined, VideoCameraOutlined } from "@ant-design/icons";
import type { EventOut, EventStatus } from "@/api/types";
import { useDirectory, useScenarios } from "@/api/hooks";
import { useLive } from "@/store/live";
import { useAuth } from "@/store/auth";
import { SEVERITY, SEVERITY_ORDER, STATUS } from "@/shared/severity";
import { fmtShort, fromNow, plural } from "@/shared/format";
import PageHeader from "@/components/PageHeader";
import EventActions from "@/components/EventActions";
import { useOpenEvent } from "@/components/EventDrawer";
import { DemoTag, ScenarioIcon, SeverityTag, StatusTag } from "@/components/Tags";

type StatusFilter = "all" | "new" | EventStatus;

/** Кнопка «уведомления на рабочем столе»: критичные тревоги видны, даже когда вкладка свёрнута. */
function DesktopNotifyButton() {
  const [perm, setPerm] = useState(typeof Notification === "undefined" ? "denied" : Notification.permission);
  if (perm !== "default") return null;
  return (
    <Tooltip title="Критичные события и эскалации придут системным уведомлением, даже если вкладка свёрнута">
      <Button icon={<BellOutlined />} onClick={() => Notification.requestPermission().then(setPerm)}>Уведомления на рабочем столе</Button>
    </Tooltip>
  );
}

/** Перерисовка раз в 15 с — чтобы «2 минуты назад» не застывало. */
function useTick(ms = 15_000) {
  const [, set] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => set((x) => x + 1), ms);
    return () => window.clearInterval(t);
  }, [ms]);
}

function Thumb({ e, w = 168 }: { e: EventOut; w?: number }) {
  const b = e.bbox;
  return (
    <div className="thumb" style={{ width: w }}>
      {e.snapshot_url ? <img src={e.snapshot_url} alt="" loading="lazy" /> : <div className="thumb-empty"><VideoCameraOutlined /></div>}
      {b && e.snapshot_url && (
        <div className="bbox bbox-thin" style={{
          left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`,
          borderColor: SEVERITY[e.severity].color,
        }} />
      )}
      {!e.ended_at && <span className="thumb-live">идёт</span>}
    </div>
  );
}

function CriticalBanner({ e, mobile }: { e: EventOut; mobile: boolean }) {
  const open = useOpenEvent();
  return (
    <div className="critical-banner" onClick={() => open(e.id)}>
      <Thumb e={e} w={mobile ? 120 : 200} />
      <div className="critical-body">
        <div className="critical-head">
          <AlertOutlined className="critical-icon" />
          <span className="critical-title">{e.scenario_title || e.scenario}</span>
          {e.escalated_at && <span className="critical-esc">не принято вовремя</span>}
        </div>
        <div className="critical-meta">
          <span><VideoCameraOutlined /> {e.camera_name || e.camera_id}</span>
          {e.zone_name && <span><EnvironmentOutlined /> {e.zone_name}</span>}
          <span><ClockCircleOutlined /> {fmtShort(e.started_at)} · {fromNow(e.started_at)}</span>
        </div>
        <div className="critical-actions">
          <EventActions event={e} size={mobile ? "large" : "middle"} block={mobile} />
        </div>
      </div>
    </div>
  );
}

function EventRow({ e, fresh, areaName, mobile }: { e: EventOut; fresh: boolean; areaName?: string; mobile: boolean }) {
  const open = useOpenEvent();
  const sev = SEVERITY[e.severity];
  return (
    <div className={`event-row ${fresh ? "event-fresh" : ""} ${e.status === "new" ? "event-new" : ""}`}
      style={{ "--sev": sev.color } as React.CSSProperties} onClick={() => open(e.id)}>
      <Thumb e={e} w={mobile ? 112 : 168} />
      <div className="event-main">
        <div className="event-title">
          <span className="event-icon" style={{ color: sev.color, background: sev.bg }}><ScenarioIcon code={e.scenario} /></span>
          <Typography.Text strong ellipsis>{e.scenario_title || e.scenario}</Typography.Text>
        </div>
        <div className="event-meta">
          <span><VideoCameraOutlined /> {e.camera_name || e.camera_id}</span>
          {e.zone_name && <span><EnvironmentOutlined /> {e.zone_name}</span>}
          {areaName && !mobile && <span className="muted">{areaName}</span>}
        </div>
        <Space size={6} wrap>
          <SeverityTag value={e.severity} compact />
          <StatusTag value={e.status} />
          {e.demo && <DemoTag />}
        </Space>
      </div>
      <div className="event-side">
        <Tooltip title={new Date(e.started_at).toLocaleString("ru-RU")}>
          <div className="event-time">{fmtShort(e.started_at)}</div>
        </Tooltip>
        <div className="muted small">{fromNow(e.started_at)}</div>
        {!mobile && <div className="event-actions"><EventActions event={e} /></div>}
      </div>
      {mobile && e.status === "new" && (
        <div className="event-footer" onClick={(ev) => ev.stopPropagation()}>
          <EventActions event={e} size="large" block />
        </div>
      )}
    </div>
  );
}

export default function Feed() {
  useTick();
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  const role = useAuth((s) => s.user?.role);
  const userAreas = useAuth((s) => s.user?.area_ids || []);
  const events = useLive((s) => s.events);
  const fresh = useLive((s) => s.fresh);
  const link = useLive((s) => s.link);
  const { tree, areas } = useDirectory();
  const { data: scenarios } = useScenarios();

  const [area, setArea] = useState<number | undefined>();
  const [scenario, setScenario] = useState<string | undefined>();
  const [status, setStatus] = useState<StatusFilter>("all");

  const all = useMemo(() => Object.values(events).sort((a, b) => b.started_at.localeCompare(a.started_at)), [events]);
  const filtered = useMemo(
    () => all.filter((e) =>
      (area === undefined || e.area_id === area) &&
      (!scenario || e.scenario === scenario) &&
      (status === "all" || e.status === status)),
    [all, area, scenario, status],
  );
  const critical = filtered.filter((e) => e.severity === "critical" && e.status === "new");
  const rest = filtered.filter((e) => !(e.severity === "critical" && e.status === "new"));
  const unaccepted = all.filter((e) => e.status === "new").length;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todays = all.filter((e) => new Date(e.started_at) >= today);
  const bySev = SEVERITY_ORDER.map((s) => ({ s, n: todays.filter((e) => e.severity === s).length }));
  const byCam = Object.entries(todays.reduce<Record<string, number>>((m, e) => ((m[e.camera_name || e.camera_id] = (m[e.camera_name || e.camera_id] || 0) + 1), m), {}))
    .sort((a, b) => b[1] - a[1]).slice(0, 5);

  const areaOptions = tree.flatMap((s) => s.areas)
    .filter((a) => role !== "master" || !userAreas.length || userAreas.includes(a.id))
    .map((a) => ({ value: a.id, label: a.name }));

  return (
    <div className="page">
      <PageHeader
        title="Лента событий"
        extra={!mobile && <DesktopNotifyButton />}
        subtitle={
          <Space size={8}>
            <Badge status={link === "online" ? "processing" : "error"} />
            {link === "online" ? "в реальном времени" : "нет связи — данные могут устареть"}
            <span>·</span>
            <b style={{ color: unaccepted ? SEVERITY.critical.color : undefined }}>{unaccepted}</b>{" "}
            {plural(unaccepted, "непринятое", "непринятых", "непринятых")}
          </Space>
        }
      />

      <div className="filters">
        <Segmented
          value={status}
          onChange={(v) => setStatus(v as StatusFilter)}
          options={[
            { label: "Все", value: "all" },
            { label: <span>Непринятые {unaccepted > 0 && <Badge count={unaccepted} size="small" style={{ marginLeft: 4 }} />}</span>, value: "new" },
            { label: STATUS.forwarded.title, value: "forwarded" },
            { label: STATUS.confirmed.title, value: "confirmed" },
          ]}
        />
        <Select allowClear placeholder="Участок" style={{ minWidth: 200 }} value={area} onChange={setArea} options={areaOptions} />
        <Select allowClear placeholder="Тип нарушения" style={{ minWidth: 220 }} value={scenario} onChange={setScenario}
          options={(scenarios || []).map((s) => ({ value: s.code, label: <Space><ScenarioIcon code={s.code} />{s.title}</Space> }))} />
      </div>

      <Row gutter={[20, 20]}>
        <Col xs={24} xl={17}>
          {critical.length > 0 && (
            <div className="critical-stack">
              {critical.map((e) => <CriticalBanner key={e.id} e={e} mobile={mobile} />)}
            </div>
          )}
          <Card variant="borderless" className="feed-card" styles={{ body: { padding: 0 } }}>
            {rest.length === 0 && critical.length === 0 ? (
              <Empty style={{ padding: 48 }} description={status === "new" ? "Все события приняты — отличная работа" : "Событий нет. Новые появятся здесь автоматически"} />
            ) : (
              rest.slice(0, 150).map((e) => (
                <EventRow key={e.id} e={e} fresh={!!fresh[e.id] && Date.now() - fresh[e.id] < 20_000} mobile={mobile}
                  areaName={e.area_id ? areas.get(e.area_id)?.name : undefined} />
              ))
            )}
          </Card>
        </Col>
        {screens.xl && (
          <Col xl={7}>
            <Card variant="borderless" title="Сегодня" className="side-card">
              <div className="today-total">{todays.length}<span>{plural(todays.length, "событие", "события", "событий")}</span></div>
              <div className="sev-bars">
                {bySev.map(({ s, n }) => (
                  <div key={s} className="sev-bar">
                    <span className="sev-dot" style={{ background: SEVERITY[s].color }} />
                    <span className="sev-name">{SEVERITY[s].title}</span>
                    <span className="sev-track"><span style={{ width: `${todays.length ? (n / todays.length) * 100 : 0}%`, background: SEVERITY[s].color }} /></span>
                    <b>{n}</b>
                  </div>
                ))}
              </div>
            </Card>
            <Card variant="borderless" title="Чаще всего сегодня" className="side-card" style={{ marginTop: 20 }}>
              {byCam.length ? byCam.map(([name, n]) => (
                <div key={name} className="top-row"><span><VideoCameraOutlined /> {name}</span><b>{n}</b></div>
              )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Пока тихо" />}
            </Card>
          </Col>
        )}
      </Row>
    </div>
  );
}
