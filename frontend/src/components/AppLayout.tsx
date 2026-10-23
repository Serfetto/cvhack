import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { App, Avatar, Badge, Button, Drawer, Dropdown, Grid, Layout, Menu, Space, Tag, Tooltip, Typography } from "antd";
import {
  AlertOutlined, BarChartOutlined, BellOutlined, BulbOutlined, DashboardOutlined, LogoutOutlined, MenuFoldOutlined,
  MenuUnfoldOutlined, MoonOutlined, SoundOutlined, TableOutlined, TeamOutlined, ThunderboltOutlined, UserOutlined,
  VideoCameraOutlined, MutedOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import type { EventOut } from "@/api/types";
import { api } from "@/api/client";
import { useAuth } from "@/store/auth";
import { useLive } from "@/store/live";
import { useUi } from "@/store/ui";
import { can, ROLE_TITLE, ROUTE_ROLES } from "@/shared/roles";
import { playAlarm } from "@/shared/sound";
import { USE_MOCKS } from "@/env";
import ConnectionBadge from "./ConnectionBadge";
import EventDrawer, { useOpenEvent } from "./EventDrawer";
import { ScenarioIcon } from "./Tags";

const { Sider, Header, Content } = Layout;

const NAV = [
  { key: "/feed", icon: <BellOutlined />, label: "Лента событий", roles: ROUTE_ROLES.feed },
  { key: "/journal", icon: <TableOutlined />, label: "Журнал", roles: ROUTE_ROLES.journal },
  { key: "/dashboard", icon: <DashboardOutlined />, label: "Дашборд", roles: ROUTE_ROLES.dashboard },
  { key: "/cameras", icon: <VideoCameraOutlined />, label: "Камеры", roles: ROUTE_ROLES.cameras },
  { key: "/performance", icon: <ThunderboltOutlined />, label: "Производительность", roles: ROUTE_ROLES.performance },
  { key: "/users", icon: <TeamOutlined />, label: "Пользователи", roles: ROUTE_ROLES.users },
];

function Brand({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link to="/" className="brand">
      <img src="/favicon.svg" alt="" width={32} height={32} />
      {!collapsed && (
        <div className="brand-text">
          <div className="brand-name">LinQ Safety</div>
          <div className="brand-sub">видеоконтроль ТБ</div>
        </div>
      )}
    </Link>
  );
}

/** Системное уведомление ОС — только если вкладка в фоне и пользователь разрешил. */
function desktopNotify(title: string, body: string, id: string) {
  if (!document.hidden || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const n = new Notification(title, { body, tag: id, icon: "/favicon.svg", requireInteraction: true });
  n.onclick = () => {
    window.focus();
    const url = new URL(location.href);
    url.searchParams.set("event", id);
    history.pushState(null, "", url);
    dispatchEvent(new PopStateEvent("popstate"));
    n.close();
  };
}

/** Начальная загрузка ленты (последние события + все непринятые) и живые обновления по WebSocket. */
function useLiveFeed() {
  const qc = useQueryClient();
  const { notification } = App.useApp();
  const open = useOpenEvent();
  const openRef = useRef(open);
  openRef.current = open;
  const sound = useUi((s) => s.sound);
  const prefsSound = useAuth((s) => s.user?.notify_prefs?.sound ?? true);
  const soundRef = useRef(sound && prefsSound);
  soundRef.current = sound && prefsSound;

  useEffect(() => {
    const live = useLive.getState();
    live.connect();
    Promise.all([
      api.get<{ items: EventOut[] }>("/events/events", { page_size: 100, sort: "-started_at" }),
      api.get<{ items: EventOut[] }>("/events/events", { page_size: 300, status: "new", sort: "-started_at" }),
    ]).then(([a, b]) => live.seed([...a.items, ...b.items])).catch(() => undefined);

    // журнал и дашборд обновляются сами, но не чаще раза в 3 с
    let pending: number | undefined;
    const invalidate = () => {
      if (pending) return;
      pending = window.setTimeout(() => {
        pending = undefined;
        qc.invalidateQueries({ queryKey: ["events", "list"] });
        qc.invalidateQueries({ queryKey: ["stats"] });
      }, 3000);
    };

    const unsub = live.subscribe((m) => {
      invalidate();
      if (m.type === "event.updated") {
        qc.setQueryData(["events", "detail", m.event.id], (old: object | undefined) => (old ? { ...old, ...m.event } : old));
        if (m.event.status !== "new") return;
        qc.invalidateQueries({ queryKey: ["events", "detail", m.event.id] });
        return;
      }
      if (m.notify === false) return;
      const e = m.event;
      const title = e.scenario_title || e.scenario;
      const where = `${e.camera_name || e.camera_id}${e.zone_name ? ` · ${e.zone_name}` : ""}`;
      const btn = (
        <Button type="primary" size="small" onClick={() => { openRef.current(e.id); notification.destroy(e.id); }}>
          Открыть
        </Button>
      );
      if (m.type === "event.escalated") {
        notification.warning({ key: e.id, message: `Не принято вовремя: ${title}`, description: where, actions: btn, duration: 15 });
        desktopNotify(`Не принято вовремя: ${title}`, where, e.id);
        if (soundRef.current) playAlarm("normal");
      } else if (e.severity === "critical") {
        notification.error({ key: e.id, message: title, description: where, actions: btn, icon: <AlertOutlined style={{ color: "#d03b3b" }} />, duration: 12 });
        desktopNotify(`Критично: ${title}`, where, e.id);
        if (soundRef.current) playAlarm("critical");
      } else if (e.severity === "high") {
        notification.warning({ key: e.id, message: title, description: where, actions: btn, icon: <ScenarioIcon code={e.scenario} />, duration: 6 });
        if (soundRef.current) playAlarm("normal");
      }
    });
    return () => {
      unsub();
      window.clearTimeout(pending);
    };
  }, [qc, notification]);
}

export default function AppLayout() {
  const access = useAuth((s) => s.access);
  const user = useAuth((s) => s.user);
  const loc = useLocation();
  if (!access || !user) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />;
  return <Shell />;
}

function Shell() {
  const user = useAuth((s) => s.user)!;
  const clear = useAuth((s) => s.clear);
  const { theme, toggleTheme, sound, setSound, collapsed, setCollapsed } = useUi();
  const screens = Grid.useBreakpoint();
  const mobile = !screens.lg;
  const [mobileNav, setMobileNav] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();
  const qc = useQueryClient();

  const events = useLive((s) => s.events);
  const unaccepted = useMemo(() => Object.values(events).filter((e) => e.status === "new"), [events]);
  const criticalNew = unaccepted.filter((e) => e.severity === "critical").length;
  useLiveFeed();

  // непринятые видны даже на соседней вкладке браузера
  useEffect(() => {
    document.title = `${unaccepted.length ? `(${unaccepted.length}) ` : ""}LinQ Safety — видеоконтроль ТБ`;
  }, [unaccepted.length]);
  const items = NAV.filter((n) => can(user.role, n.roles)).map((n) => ({
    key: n.key,
    icon: n.icon,
    label: n.key === "/feed" && unaccepted.length ? (
      <span className="menu-badge">{n.label}<Badge count={unaccepted.length} size="small" /></span>
    ) : n.label,
  }));
  const selected = "/" + loc.pathname.split("/")[1];

  const logout = async () => {
    const refresh = useAuth.getState().refresh;
    if (refresh) api.post("/auth/logout", { refresh_token: refresh }).catch(() => undefined);
    useLive.getState().disconnect();
    clear();
    qc.clear();
    nav("/login");
  };

  const menu = (
    <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={items}
      onClick={({ key }) => { nav(key); setMobileNav(false); }} style={{ borderInlineEnd: 0, padding: "0 8px" }} />
  );

  return (
    <Layout style={{ minHeight: "100vh" }}>
      {!mobile && (
        <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} trigger={null} width={248} collapsedWidth={72}
          style={{ position: "sticky", top: 0, height: "100vh", overflow: "auto" }}>
          <Brand collapsed={collapsed} />
          {menu}
          <div className="sider-footer">
            {!collapsed && <div className="sider-role">{ROLE_TITLE[user.role]}</div>}
          </div>
        </Sider>
      )}
      {mobile && (
        <Drawer open={mobileNav} onClose={() => setMobileNav(false)} placement="left" width={264} closable={false}
          styles={{ body: { padding: 0, background: "#0b1220" } }}>
          <Brand />
          {menu}
        </Drawer>
      )}
      <Layout>
        <Header className="app-header">
          <Space size={12}>
            <Button type="text" icon={mobile || collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => (mobile ? setMobileNav(true) : setCollapsed(!collapsed))} />
            {USE_MOCKS && (
              <Tooltip title="Данные из MSW-моков: бэкенд не нужен. Для реального API — VITE_USE_MOCKS=false">
                <Tag color="purple" bordered={false}>демо-режим</Tag>
              </Tooltip>
            )}
          </Space>
          <Space size={mobile ? 4 : 12}>
            {criticalNew > 0 && (
              <Button danger type="primary" size="small" className="pulse" icon={<AlertOutlined />} onClick={() => nav("/feed")}>
                {!mobile && "Критичных: "}{criticalNew}
              </Button>
            )}
            <ConnectionBadge compact={mobile} />
            <Tooltip title="Непринятые события">
              <Badge count={unaccepted.length} size="small" offset={[-4, 4]}>
                <Button type="text" icon={<BellOutlined />} onClick={() => nav("/feed")} />
              </Badge>
            </Tooltip>
            <Tooltip title={sound ? "Звук тревог включён" : "Звук выключен"}>
              <Button type="text" icon={sound ? <SoundOutlined /> : <MutedOutlined />} onClick={() => setSound(!sound)} />
            </Tooltip>
            <Tooltip title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}>
              <Button type="text" icon={theme === "dark" ? <BulbOutlined /> : <MoonOutlined />} onClick={toggleTheme} />
            </Tooltip>
            <Dropdown
              trigger={["click"]}
              menu={{
                items: [
                  { key: "who", label: <div className="dropdown-user"><b>{user.full_name || user.username}</b><div className="muted small">{user.role_title || ROLE_TITLE[user.role]}</div></div>, disabled: true },
                  { type: "divider" },
                  { key: "profile", icon: <UserOutlined />, label: "Личный кабинет", onClick: () => nav("/profile") },
                  ...(can(user.role, ROUTE_ROLES.dashboard) ? [{ key: "dash", icon: <BarChartOutlined />, label: "Дашборд", onClick: () => nav("/dashboard") }] : []),
                  { key: "logout", icon: <LogoutOutlined />, label: "Выйти", danger: true, onClick: logout },
                ],
              }}
            >
              <Space className="header-user" size={8}>
                <Avatar style={{ background: "linear-gradient(135deg,#3b82f6,#6366f1)" }}>
                  {(user.full_name || user.username).slice(0, 1).toUpperCase()}
                </Avatar>
                {screens.md && (
                  <div className="header-user-text">
                    <Typography.Text strong ellipsis style={{ maxWidth: 180 }}>{user.full_name || user.username}</Typography.Text>
                    <div className="muted small">{ROLE_TITLE[user.role]}</div>
                  </div>
                )}
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
      <EventDrawer />
    </Layout>
  );
}
