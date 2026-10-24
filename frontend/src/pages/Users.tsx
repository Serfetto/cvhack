import { useState } from "react";
import { App, Avatar, Badge, Button, Card, Form, Input, Modal, Select, Space, Switch, Table, Tag } from "antd";
import type { TableProps } from "antd";
import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { Role, User } from "@/api/types";
import { useDirectory, useSaveUser, useUsers } from "@/api/hooks";
import { ROLE_TITLE } from "@/shared/roles";
import { fmtDateTime } from "@/shared/format";
import PageHeader from "@/components/PageHeader";

const ROLE_COLOR: Record<Role, string> = { admin: "magenta", hse: "green", master: "orange", operator: "blue", manager: "purple", auditor: "cyan" };

function UserModal({ user, open, onClose }: { user: User | null; open: boolean; onClose: () => void }) {
  const [form] = Form.useForm();
  const save = useSaveUser();
  const { tree } = useDirectory();
  const { message } = App.useApp();
  const role = Form.useWatch("role", form);
  return (
    <Modal open={open} onCancel={onClose} title={user ? `Пользователь ${user.username}` : "Новый пользователь"} okText={user ? "Сохранить" : "Создать"}
      confirmLoading={save.isPending} destroyOnHidden
      onOk={() => form.validateFields().then((v) => save.mutate({ ...v, id: user?.id, password: v.password || undefined }, {
        onSuccess: () => { message.success(user ? "Сохранено" : "Пользователь создан"); onClose(); },
        onError: (e) => message.error(e.message),
      }))}>
      <Form form={form} layout="vertical" preserve={false}
        initialValues={user ? { full_name: user.full_name, role: user.role, area_ids: user.area_ids, is_active: user.is_active } : { role: "operator", area_ids: [] }}>
        {!user && (
          <Form.Item name="username" label="Логин" rules={[{ required: true }, { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: "Латиница, цифры, _ . -" }]}>
            <Input autoComplete="off" />
          </Form.Item>
        )}
        <Form.Item name="full_name" label="ФИО и должность"><Input /></Form.Item>
        <Form.Item name="role" label="Роль" rules={[{ required: true }]}>
          <Select options={(Object.keys(ROLE_TITLE) as Role[]).map((r) => ({ value: r, label: ROLE_TITLE[r] }))} />
        </Form.Item>
        <Form.Item name="area_ids" label="Участки" extra={role === "master" ? "Мастер видит события только своих участков" : "Для этой роли ограничение по участкам не действует"}>
          <Select mode="multiple" allowClear options={tree.flatMap((s) => s.areas).map((a) => ({ value: a.id, label: a.name }))} />
        </Form.Item>
        <Form.Item name="password" label={user ? "Новый пароль" : "Пароль"} rules={user ? [{ min: 4 }] : [{ required: true }, { min: 4 }]}
          extra={user ? "Оставьте пустым, чтобы не менять" : undefined}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        {user && <Form.Item name="is_active" label="Активен" valuePropName="checked"><Switch /></Form.Item>}
      </Form>
    </Modal>
  );
}

export default function Users() {
  const { data, isLoading } = useUsers();
  const { areas } = useDirectory();
  const [edit, setEdit] = useState<{ open: boolean; user: User | null }>({ open: false, user: null });

  const columns: TableProps<User>["columns"] = [
    {
      title: "Пользователь", key: "u", render: (_, u) => (
        <Space>
          <Avatar style={{ background: u.is_active ? "#2563eb" : "#9ca3af" }}>{(u.full_name || u.username).slice(0, 1).toUpperCase()}</Avatar>
          <div><b>{u.full_name || u.username}</b><div className="muted small">@{u.username}</div></div>
        </Space>
      ),
    },
    { title: "Роль", dataIndex: "role", render: (r: Role) => <Tag color={ROLE_COLOR[r]} bordered={false}>{ROLE_TITLE[r]}</Tag> },
    { title: "Участки", dataIndex: "area_ids", render: (a: number[]) => (a.length ? a.map((x) => areas.get(x)?.name || x).join(", ") : <span className="muted">все</span>) },
    { title: "Telegram", dataIndex: "telegram_chat_id", render: (v: number | null) => (v ? <Badge status="success" text="подключён" /> : <span className="muted">—</span>) },
    { title: "Статус", dataIndex: "is_active", render: (v: boolean) => <Badge status={v ? "success" : "default"} text={v ? "активен" : "отключён"} /> },
    { title: "Создан", dataIndex: "created_at", render: fmtDateTime },
    { key: "a", width: 60, render: (_, u) => <Button type="text" icon={<EditOutlined />} onClick={() => setEdit({ open: true, user: u })} /> },
  ];

  return (
    <div className="page">
      <PageHeader title="Пользователи" subtitle="Роли и доступ к участкам"
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setEdit({ open: true, user: null })}>Добавить</Button>} />
      <Card variant="borderless" styles={{ body: { padding: 0 } }}>
        <Table<User> rowKey="id" columns={columns} dataSource={data} loading={isLoading} pagination={false} scroll={{ x: 800 }} />
      </Card>
      <UserModal open={edit.open} user={edit.user} onClose={() => setEdit({ open: false, user: null })} />
    </div>
  );
}
