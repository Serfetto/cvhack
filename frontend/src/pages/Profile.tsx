import { useEffect } from "react";
import { App, Avatar, Button, Card, Col, Form, Input, InputNumber, Row, Select, Skeleton, Space, Switch, Tag, Typography } from "antd";
import { BellOutlined, LockOutlined, SendOutlined, UserOutlined } from "@ant-design/icons";
import type { NotifyPrefs, Severity } from "@/api/types";
import { useChangePassword, useDirectory, useMe, usePatchMe, useScenarios } from "@/api/hooks";
import { useAuth } from "@/store/auth";
import { ROLE_TITLE } from "@/shared/roles";
import { SEVERITY, SEVERITY_ORDER } from "@/shared/severity";
import { fmtDateTime } from "@/shared/format";
import PageHeader from "@/components/PageHeader";

export default function Profile() {
  const { message } = App.useApp();
  const { data: me, isLoading } = useMe();
  const patch = usePatchMe();
  const changePassword = useChangePassword();
  const setUser = useAuth((s) => s.setUser);
  const { tree, areas } = useDirectory();
  const { data: scenarios } = useScenarios();
  const [profile] = Form.useForm();
  const [prefs] = Form.useForm<NotifyPrefs & { telegram_chat_id: number | null }>();
  const [pwd] = Form.useForm();

  useEffect(() => {
    if (!me) return;
    profile.setFieldsValue({ full_name: me.full_name });
    prefs.setFieldsValue({ ...me.notify_prefs, telegram_chat_id: me.telegram_chat_id });
  }, [me, profile, prefs]);

  if (isLoading || !me) return <div className="page"><Skeleton active paragraph={{ rows: 10 }} /></div>;

  const saved = (u: typeof me) => {
    setUser(u);
    message.success("Сохранено");
  };

  return (
    <div className="page">
      <PageHeader title="Личный кабинет" subtitle="Профиль, уведомления и безопасность" />
      <Row gutter={[20, 20]}>
        <Col xs={24} lg={9}>
          <Card variant="borderless">
            <div className="profile-head">
              <Avatar size={64} style={{ background: "linear-gradient(135deg,#3b82f6,#6366f1)", fontSize: 26 }}>
                {(me.full_name || me.username).slice(0, 1).toUpperCase()}
              </Avatar>
              <div>
                <Typography.Title level={4} style={{ margin: 0 }}>{me.full_name || me.username}</Typography.Title>
                <Space size={6} wrap style={{ marginTop: 4 }}>
                  <Tag color="blue" bordered={false}>{ROLE_TITLE[me.role]}</Tag>
                  <span className="muted small">@{me.username}</span>
                </Space>
              </div>
            </div>
            <div className="profile-meta">
              <div><span className="muted">Участки</span><span>{me.area_ids.length ? me.area_ids.map((a) => areas.get(a)?.name || a).join(", ") : "все"}</span></div>
              <div><span className="muted">В системе с</span><span>{fmtDateTime(me.created_at)}</span></div>
            </div>
            <Form form={profile} layout="vertical" onFinish={(v) => patch.mutate(v, { onSuccess: saved, onError: (e) => message.error(e.message) })}>
              <Form.Item name="full_name" label="ФИО и должность"><Input prefix={<UserOutlined />} /></Form.Item>
              <Button htmlType="submit" loading={patch.isPending}>Сохранить профиль</Button>
            </Form>
          </Card>

          <Card variant="borderless" title={<span><LockOutlined /> Смена пароля</span>} style={{ marginTop: 20 }}>
            <Form form={pwd} layout="vertical" onFinish={(v) => changePassword.mutate(v, {
              onSuccess: () => { message.success("Пароль изменён"); pwd.resetFields(); },
              onError: (e) => message.error(e.message),
            })}>
              <Form.Item name="old_password" label="Текущий пароль" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
              <Form.Item name="new_password" label="Новый пароль" rules={[{ required: true }, { min: 4, message: "Не короче 4 символов" }]}><Input.Password autoComplete="new-password" /></Form.Item>
              <Form.Item name="confirm" label="Ещё раз" dependencies={["new_password"]} rules={[{ required: true }, ({ getFieldValue }) => ({
                validator: (_, v) => (v === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("Пароли не совпадают"))),
              })]}><Input.Password autoComplete="new-password" /></Form.Item>
              <Button htmlType="submit" loading={changePassword.isPending}>Сменить пароль</Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card variant="borderless" title={<span><BellOutlined /> Подписки на уведомления</span>}>
            <Typography.Paragraph type="secondary">
              Какие события показывать всплывающим уведомлением, озвучивать и присылать в Telegram. В ленте видны все события, доступные вашей роли.
            </Typography.Paragraph>
            <Form form={prefs} layout="vertical" onFinish={({ telegram_chat_id, ...p }) => patch.mutate({ notify_prefs: p, telegram_chat_id: telegram_chat_id ?? null }, { onSuccess: saved, onError: (e) => message.error(e.message) })}>
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item name="scenarios" label="Типы нарушений" extra="Пусто — все типы">
                    <Select mode="multiple" allowClear placeholder="Все типы" options={(scenarios || []).map((s) => ({ value: s.code, label: s.title }))} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="area_ids" label="Участки" extra="Пусто — все доступные участки">
                    <Select mode="multiple" allowClear placeholder="Все участки" options={tree.flatMap((s) => s.areas).map((a) => ({ value: a.id, label: a.name }))} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="min_severity" label="Важность не ниже">
                    <Select options={[...SEVERITY_ORDER].reverse().map((s: Severity) => ({
                      value: s, label: <Space><span className="sev-dot" style={{ background: SEVERITY[s].color }} />{s === "low" ? "Все события" : s === "critical" ? "Только критичные" : `${SEVERITY[s].title} и выше`}</Space>,
                    }))} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="sound" label="Звук тревоги в браузере" valuePropName="checked"><Switch /></Form.Item>
                </Col>
              </Row>
              <div className="telegram-box">
                <Space align="start" size={16} wrap>
                  <Form.Item name="telegram" label={<span><SendOutlined /> Telegram</span>} valuePropName="checked" style={{ marginBottom: 0 }}><Switch /></Form.Item>
                  <Form.Item name="telegram_chat_id" label="Chat ID" extra="Напишите боту /start — он пришлёт ваш chat id" style={{ marginBottom: 0 }}>
                    <InputNumber style={{ width: 220 }} controls={false} placeholder="123456789" />
                  </Form.Item>
                </Space>
                <Typography.Paragraph type="secondary" className="small" style={{ margin: "8px 0 0" }}>
                  Эскалации («не принято вовремя») приходят руководителю, охране труда и мастерам независимо от подписок.
                </Typography.Paragraph>
              </div>
              <Button type="primary" htmlType="submit" loading={patch.isPending} style={{ marginTop: 16 }}>Сохранить подписки</Button>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
