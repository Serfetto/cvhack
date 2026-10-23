import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App, Badge, Button, Card, Col, Empty, Form, Input, InputNumber, Modal, Row, Segmented, Select, Skeleton, Space, Switch, Tag, Typography } from "antd";
import { PlusOutlined, SettingOutlined, TableOutlined, VideoCameraOutlined, WarningOutlined } from "@ant-design/icons";
import type { Camera, CameraIn } from "@/api/types";
import { withToken } from "@/api/client";
import { useCameras, useCreateCamera, useDirectory } from "@/api/hooks";
import { useAuth } from "@/store/auth";
import { CAN, can } from "@/shared/roles";
import PageHeader from "@/components/PageHeader";
import HlsPlayer from "@/components/HlsPlayer";

const STATE: Record<string, { text: string; status: "success" | "processing" | "error" | "default" | "warning" }> = {
  online: { text: "В сети", status: "success" },
  connecting: { text: "Подключение", status: "processing" },
  offline: { text: "Нет сигнала", status: "error" },
  disabled: { text: "Отключена", status: "default" },
  unknown: { text: "Неизвестно", status: "warning" },
};

/** Последний кадр камеры, обновляется каждые 3 с — когда HLS нет (файл, папка кадров) или поток не поднялся. */
export function LiveSnapshot({ cameraId, intervalMs = 3000 }: { cameraId: string; intervalMs?: number }) {
  const [t, setT] = useState(Date.now());
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const id = window.setInterval(() => setT(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  if (failed) return <div className="video-empty"><WarningOutlined /> Кадров с камеры пока нет</div>;
  return <img className="live-video" alt="" src={withToken(`/api/config/cameras/${cameraId}/snapshot?t=${t}`)} onError={() => setFailed(true)} />;
}

function CameraCard({ c }: { c: Camera }) {
  const nav = useNavigate();
  const role = useAuth((s) => s.user?.role);
  const st = STATE[c.stream.state] || STATE.unknown;
  const online = c.stream.state === "online";
  return (
    <Card variant="borderless" className="camera-card" cover={
      <div className="camera-video">
        {online ? (
          c.live_hls ? <HlsPlayer src={c.live_hls} fallback={<LiveSnapshot cameraId={c.id} />} /> : <LiveSnapshot cameraId={c.id} />
        ) : (
          <div className="video-empty"><VideoCameraOutlined /> {st.text}</div>
        )}
        <div className="camera-overlay">
          <span className={`camera-state camera-state-${c.stream.state}`}><Badge status={st.status} /> {st.text}</span>
          {online && <span className="camera-fps">{c.stream.fps.toFixed(1)} к/с</span>}
        </div>
      </div>
    }>
      <div className="camera-head">
        <div>
          <Typography.Text strong style={{ fontSize: 15 }}>{c.name}</Typography.Text>
          <div className="muted small">{c.area_name || "Без участка"} · {c.id}</div>
        </div>
        <Space size={4}>
          <Tag bordered={false}>{c.zones_count} зон</Tag>
          <Tag bordered={false}>{c.rules_count} правил</Tag>
        </Space>
      </div>
      {c.stream.error && <Typography.Paragraph type="danger" className="small" ellipsis={{ rows: 2 }} style={{ margin: "8px 0 0" }}>{c.stream.error}</Typography.Paragraph>}
      <div className="camera-actions">
        <Button icon={<TableOutlined />} onClick={() => nav(`/journal?camera_id=${c.id}`)}>События</Button>
        {can(role, CAN.configure) && (
          <Button type="primary" ghost icon={<SettingOutlined />} onClick={() => nav(`/cameras/${c.id}`)}>Зоны и правила</Button>
        )}
      </div>
    </Card>
  );
}

function AddCamera({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<CameraIn>();
  const { tree } = useDirectory();
  const create = useCreateCamera();
  const { message } = App.useApp();
  const nav = useNavigate();
  const type = Form.useWatch("source_type", form);
  return (
    <Modal open={open} onCancel={onClose} title="Новая камера" okText="Добавить" confirmLoading={create.isPending} destroyOnHidden
      onOk={() => form.validateFields().then((v) => create.mutate(v, {
        onSuccess: (c) => { message.success(`Камера ${c.id} добавлена — ingest подхватит её без перезапуска`); onClose(); nav(`/cameras/${c.id}`); },
        onError: (e) => message.error(e.message),
      }))}>
      <Form form={form} layout="vertical" preserve={false} initialValues={{ source_type: "rtsp", analysis_fps: 5, enabled: true }}>
        <Form.Item name="name" label="Название" rules={[{ required: true, message: "Как называется камера" }]}><Input placeholder="Цех 2, конвейер" /></Form.Item>
        <Form.Item name="area_id" label="Участок">
          <Select allowClear options={tree.flatMap((s) => s.areas).map((a) => ({ value: a.id, label: a.name }))} />
        </Form.Item>
        <Form.Item name="source_type" label="Источник">
          <Segmented options={[{ label: "RTSP", value: "rtsp" }, { label: "Видеофайл", value: "file" }, { label: "Папка кадров", value: "images" }]} />
        </Form.Item>
        <Form.Item name="source_url" label={type === "rtsp" ? "RTSP-адрес" : "Путь"} rules={[{ required: true, message: "Укажите источник" }]}>
          <Input placeholder={type === "rtsp" ? "rtsp://user:pass@10.0.0.5:554/stream1" : "/app/data/demo_videos/cam05.mp4"} />
        </Form.Item>
        <Space size={24}>
          <Form.Item name="analysis_fps" label="FPS анализа" tooltip="Сколько кадров в секунду уходит в нейросеть"><InputNumber min={0.2} max={30} step={0.5} /></Form.Item>
          <Form.Item name="enabled" label="Включена" valuePropName="checked"><Switch /></Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

export default function Cameras() {
  const { data, isLoading } = useCameras();
  const { tree } = useDirectory();
  const role = useAuth((s) => s.user?.role);
  const [area, setArea] = useState<number | "all">("all");
  const [adding, setAdding] = useState(false);
  const cams = (data || []).filter((c) => area === "all" || c.area_id === area);
  const online = (data || []).filter((c) => c.stream.state === "online").length;

  return (
    <div className="page">
      <PageHeader
        title="Камеры"
        subtitle={data ? `${online} из ${data.length} в сети` : "Живое видео и состояние потоков"}
        extra={can(role, CAN.configure) && <Button type="primary" icon={<PlusOutlined />} onClick={() => setAdding(true)}>Добавить камеру</Button>}
      />
      <div className="filters">
        <Segmented value={String(area)} onChange={(v) => setArea(v === "all" ? "all" : Number(v))}
          options={[{ label: "Все участки", value: "all" }, ...tree.flatMap((s) => s.areas).map((a) => ({ label: a.name, value: String(a.id) }))]} />
      </div>
      {isLoading ? (
        <Row gutter={[20, 20]}>{[1, 2, 3, 4].map((i) => <Col key={i} xs={24} md={12} xl={8}><Card variant="borderless"><Skeleton.Image active style={{ width: "100%", height: 200 }} /><Skeleton active /></Card></Col>)}</Row>
      ) : cams.length ? (
        <Row gutter={[20, 20]}>
          {cams.map((c) => <Col key={c.id} xs={24} md={12} xl={8} xxl={6}><CameraCard c={c} /></Col>)}
        </Row>
      ) : (
        <Empty description="Камер нет" />
      )}
      <AddCamera open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}
