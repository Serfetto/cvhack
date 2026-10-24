import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Alert, Button, Form, Input, Typography } from "antd";
import { LockOutlined, UserOutlined, AlertOutlined, VideoCameraOutlined, DashboardOutlined, ThunderboltOutlined } from "@ant-design/icons";
import type { Role, TokenOut } from "@/api/types";
import { useAuth } from "@/store/auth";
import { homeFor, ROLE_TITLE } from "@/shared/roles";
import { USE_MOCKS } from "@/env";

const DEMO: { username: Role; hint: string }[] = [
  { username: "operator", hint: "лента и тревоги" },
  { username: "master", hint: "свой цех, телефон" },
  { username: "hse", hint: "зоны и правила" },
  { username: "manager", hint: "дашборд" },
  { username: "auditor", hint: "журнал, экспорт" },
  { username: "admin", hint: "всё + ИТ" },
];

const FEATURES = [
  { icon: <AlertOutlined />, title: "Тревога за секунды", text: "Кадр с рамкой, клип, камера и зона — одно нарушение, одно оповещение" },
  { icon: <VideoCameraOutlined />, title: "Зоны и правила без кода", text: "Нарисуйте полигон на кадре камеры и включите сценарий" },
  { icon: <DashboardOutlined />, title: "Где и когда нарушают", text: "Тепловая карта, динамика, точность по отметкам операторов" },
  { icon: <ThunderboltOutlined />, title: "LinQ TPU", text: "FPS и задержки по стадиям, расчёт камер на устройство" },
];

export default function Login() {
  const access = useAuth((s) => s.access);
  const user = useAuth((s) => s.user);
  const setTokens = useAuth((s) => s.setTokens);
  const nav = useNavigate();
  const loc = useLocation();
  const [form] = Form.useForm();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (access && user) return <Navigate to={homeFor(user.role)} replace />;

  const submit = async (v: { username: string; password: string }) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(v),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => null);
        throw new Error(r.status === 401 ? b?.detail || "Неверный логин или пароль" : `Сервис входа недоступен (${r.status})`);
      }
      const t = (await r.json()) as TokenOut;
      setTokens(t);
      const from = (loc.state as { from?: string } | null)?.from;
      nav(from && from !== "/login" ? from : homeFor(t.user.role), { replace: true });
    } catch (e) {
      setError(e instanceof TypeError ? "Нет связи с сервером" : (e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login">
      <div className="login-hero">
        <div className="login-hero-inner">
          <div className="brand brand-lg">
            <img src="/favicon.svg" alt="" width={44} height={44} />
            <div className="brand-text">
              <div className="brand-name">LinQ Safety</div>
              <div className="brand-sub">видеоконтроль нарушений ТБ на LinQ TPU</div>
            </div>
          </div>
          <h1 className="login-title">Каждое нарушение — <span>замечено вовремя</span></h1>
          <div className="login-features">
            {FEATURES.map((f) => (
              <div className="login-feature" key={f.title}>
                <span className="login-feature-icon">{f.icon}</span>
                <div>
                  <div className="login-feature-title">{f.title}</div>
                  <div className="login-feature-text">{f.text}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="login-grid" />
      </div>

      <div className="login-panel">
        <div className="login-card">
          <Typography.Title level={3} style={{ marginBottom: 4 }}>Вход в систему</Typography.Title>
          <Typography.Paragraph type="secondary">Используйте учётную запись предприятия</Typography.Paragraph>
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
          <Form form={form} layout="vertical" size="large" onFinish={submit} requiredMark={false} initialValues={{ username: "", password: "" }}>
            <Form.Item name="username" label="Логин" rules={[{ required: true, message: "Введите логин" }]}>
              <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label="Пароль" rules={[{ required: true, message: "Введите пароль" }]}>
              <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>Войти</Button>
          </Form>

          <div className="login-demo">
            <div className="muted small" style={{ marginBottom: 8 }}>
              Демо-пользователи · пароль <code>demo</code>{USE_MOCKS && " · данные из моков"}
            </div>
            <div className="login-demo-grid">
              {DEMO.map((d) => (
                <button type="button" key={d.username} className="demo-chip"
                  onClick={() => { form.setFieldsValue({ username: d.username, password: "demo" }); form.submit(); }}>
                  <b>{ROLE_TITLE[d.username]}</b>
                  <span>{d.hint}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
