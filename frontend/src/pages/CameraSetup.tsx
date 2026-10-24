import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert, App, Badge, Button, Card, Col, Empty, Form, Input, InputNumber, Popconfirm, Result, Row, Select, Skeleton, Space, Switch, Tag,
  Tooltip, Typography,
} from "antd";
import {
  ArrowLeftOutlined, BorderOutlined, CheckOutlined, DeleteOutlined, EditOutlined, EyeInvisibleOutlined, EyeOutlined, PlusOutlined,
  ReloadOutlined, SaveOutlined, TableOutlined, UndoOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import type { Point, Rule, ZoneKind } from "@/api/types";
import { withToken } from "@/api/client";
import { useCamera, useDeleteRule, useDeleteZone, usePatchCamera, useSaveRule, useSaveZone, useScenarios } from "@/api/hooks";
import { DOW, dayjs, fmtShort } from "@/shared/format";
import { SEVERITY, ZONE_KIND } from "@/shared/severity";
import PageHeader from "@/components/PageHeader";
import ZoneEditor, { type ZoneDraft } from "@/components/ZoneEditor";
import RuleModal from "@/components/RuleModal";
import { ScenarioIcon, SeverityTag } from "@/components/Tags";

function useSnapshot(cameraId: string | undefined) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [takenAt, setTakenAt] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!cameraId) return;
    setLoading(true);
    const img = new window.Image();
    img.onload = () => {
      setImage(img);
      setError(null);
      setLoading(false);
      setTakenAt(new Date().toISOString());
    };
    img.onerror = () => {
      setError("Кадров с камеры пока нет: проверьте поток. Зоны можно рисовать и без кадра.");
      setLoading(false);
    };
    img.src = withToken(`/api/config/cameras/${cameraId}/snapshot?t=${Date.now()}`);
  }, [cameraId]);
  useEffect(load, [load]);
  return { image, error, loading, takenAt, reload: load };
}

function scheduleText(r: Rule): string {
  const parts: string[] = [];
  const s = r.schedule;
  if (s?.days?.length && s.days.length < 7) {
    parts.push(s.days.length === 5 && [0, 1, 2, 3, 4].every((d) => s.days.includes(d)) ? "будни" : s.days.map((d) => DOW[d]).join(", "));
  }
  if (s?.from && s?.to) parts.push(`${s.from}–${s.to}`);
  if (r.valid_until) parts.push(`до ${dayjs(r.valid_until).format("DD.MM HH:mm")}`);
  return parts.length ? parts.join(" · ") : "всегда";
}

let keySeq = 0;

export default function CameraSetup() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { data: cam, isLoading, error, refetch } = useCamera(id);
  const { data: scenarios = [], byCode } = useScenarios();
  const snap = useSnapshot(id);
  const saveZone = useSaveZone(id!);
  const deleteZone = useDeleteZone(id!);
  const saveRule = useSaveRule(id!);
  const deleteRule = useDeleteRule(id!);
  const patchCamera = usePatchCamera(id!);

  const [drafts, setDrafts] = useState<ZoneDraft[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [mask, setMask] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ruleModal, setRuleModal] = useState<{ open: boolean; rule: Rule | null }>({ open: false, rule: null });

  // зоны с сервера → черновики; локальные несохранённые правки не затираем
  useEffect(() => {
    if (!cam) return;
    setDrafts((prev) => {
      const dirty = prev.filter((d) => d.dirty);
      const server = cam.zones.map((z) => ({ key: `z${z.id}`, id: z.id, name: z.name, kind: z.kind, polygon: z.polygon, enabled: z.enabled, color: z.color }));
      return [...server.map((s) => dirty.find((d) => d.id === s.id) || s), ...dirty.filter((d) => !d.id)];
    });
  }, [cam]);

  const dirtyCount = drafts.filter((d) => d.dirty).length;
  useEffect(() => {
    if (!dirtyCount) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirtyCount]);

  const sel = drafts.find((d) => d.key === selected);
  const update = (key: string, patch: Partial<ZoneDraft>) =>
    setDrafts((ds) => ds.map((d) => (d.key === key ? { ...d, ...patch, dirty: true } : d)));

  const onDrawn = (polygon: Point[]) => {
    const key = `new${++keySeq}`;
    setDrafts((ds) => [...ds, { key, name: `Зона ${ds.length + 1}`, kind: "danger", polygon, enabled: true, color: null, dirty: true }]);
    setSelected(key);
    setDrawing(false);
    message.info("Зона нарисована — задайте имя и тип, затем «Сохранить»");
  };

  const applied = async () => {
    const r = await refetch();
    qc.invalidateQueries({ queryKey: ["cameras"] });
    message.success({ content: `Применено — камера перечитала настройки (версия ${r.data?.version ?? "?"})`, icon: <CheckOutlined style={{ color: "#0ca30c" }} /> });
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      for (const d of drafts.filter((x) => x.dirty)) {
        if (!d.name.trim()) throw new Error("У зоны должно быть имя");
        const z = await saveZone.mutateAsync({ id: d.id, name: d.name.trim(), kind: d.kind, polygon: d.polygon, enabled: d.enabled, color: d.color });
        setDrafts((ds) => ds.map((x) => (x.key === d.key ? { ...x, id: z.id, key: `z${z.id}`, dirty: false } : x)));
        if (selected === d.key) setSelected(`z${z.id}`);
      }
      await applied();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    setDrafts(cam!.zones.map((z) => ({ key: `z${z.id}`, id: z.id, name: z.name, kind: z.kind, polygon: z.polygon, enabled: z.enabled, color: z.color })));
    setSelected(null);
  };

  const removeZone = (d: ZoneDraft) => {
    const rulesCount = cam?.rules.filter((r) => r.zone_id === d.id).length || 0;
    const run = () => {
      if (!d.id) {
        setDrafts((ds) => ds.filter((x) => x.key !== d.key));
        setSelected(null);
        return;
      }
      deleteZone.mutate(d.id, {
        onSuccess: () => { setDrafts((ds) => ds.filter((x) => x.key !== d.key)); setSelected(null); applied(); },
        onError: (e) => message.error(e.message),
      });
    };
    if (rulesCount) {
      modal.confirm({ title: `Удалить зону «${d.name}»?`, content: `Вместе с ней удалятся правила (${rulesCount}).`, okText: "Удалить", okButtonProps: { danger: true }, onOk: run });
    } else run();
  };

  const toggleRule = (r: Rule, enabled: boolean) =>
    saveRule.mutate({ id: r.id, enabled }, { onSuccess: applied, onError: (e) => message.error(e.message) });

  const zoneName = useMemo(() => new Map(cam?.zones.map((z) => [z.id, z.name]) || []), [cam]);

  if (isLoading) return <div className="page"><Skeleton active paragraph={{ rows: 12 }} /></div>;
  if (error || !cam) return <Result status="404" title="Камера не найдена" extra={<Button onClick={() => nav("/cameras")}>К списку камер</Button>} />;

  const online = cam.stream.state === "online";

  return (
    <div className="page">
      <PageHeader
        title={<Space><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => nav("/cameras")} />{cam.name}</Space>}
        subtitle={
          <Space size={8} wrap>
            <Badge status={online ? "success" : "error"} text={online ? `в сети · ${cam.stream.fps.toFixed(1)} к/с` : "нет сигнала"} />
            <span>·</span><span>{cam.area_name || "без участка"}</span>
            <span>·</span><Tooltip title="Версия конфигурации растёт при каждом изменении — по ней видно, что камера перечитала настройки"><Tag bordered={false}>версия {cam.version}</Tag></Tooltip>
          </Space>
        }
        extra={<Link to={`/journal?camera_id=${cam.id}`}><Button icon={<TableOutlined />}>События камеры</Button></Link>}
      />

      <Row gutter={[20, 20]}>
        <Col xs={24} xl={16}>
          <Card variant="borderless" className="editor-card" styles={{ body: { padding: 12 } }}>
            <div className="editor-toolbar">
              <Space wrap>
                {drawing ? (
                  <Button danger icon={<UndoOutlined />} onClick={() => setDrawing(false)}>Отменить рисование</Button>
                ) : (
                  <Button type="primary" icon={<BorderOutlined />} onClick={() => { setDrawing(true); setSelected(null); }}>Нарисовать зону</Button>
                )}
                <Button icon={mask ? <EyeInvisibleOutlined /> : <EyeOutlined />} onClick={() => setMask(!mask)}>{mask ? "Скрыть маску" : "Маска"}</Button>
                <Tooltip title={snap.takenAt ? `Кадр от ${fmtShort(snap.takenAt)}` : undefined}>
                  <Button icon={<ReloadOutlined spin={snap.loading} />} onClick={snap.reload}>Обновить кадр</Button>
                </Tooltip>
              </Space>
              <Space>
                {dirtyCount > 0 && <Button onClick={discard}>Отменить правки</Button>}
                <Button type="primary" icon={<SaveOutlined />} disabled={!dirtyCount} loading={saving} onClick={saveAll}>
                  Сохранить{dirtyCount ? ` (${dirtyCount})` : ""}
                </Button>
              </Space>
            </div>
            {snap.error && !snap.image && <Alert type="warning" showIcon message={snap.error} style={{ marginBottom: 12 }} />}
            <ZoneEditor image={snap.image} zones={drafts} selected={selected} onSelect={setSelected} drawing={drawing}
              onChange={(k, polygon) => update(k, { polygon })} onDrawn={onDrawn} onCancelDraw={() => setDrawing(false)} showMask={mask} />
            <div className="editor-hint">
              {drawing ? (
                <>Кликайте по кадру, чтобы ставить вершины. <b>Замкнуть</b> — клик по первой точке, двойной клик или Enter. Backspace — убрать последнюю точку, Esc — отмена.</>
              ) : sel ? (
                <>Тяните вершины и всю зону. Клик по <b>полупрозрачной точке</b> на ребре — новая вершина. Двойной клик / правая кнопка / Delete — удалить вершину.</>
              ) : (
                <>Выберите зону на кадре или в списке, чтобы изменить её. Координаты сохраняются в долях кадра (0..1) — от разрешения камеры не зависят.</>
              )}
            </div>
          </Card>
        </Col>

        <Col xs={24} xl={8}>
          <Card variant="borderless" title={`Зоны · ${drafts.length}`} className="side-card">
            {drafts.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Зон нет — нарисуйте первую на кадре" />}
            <div className="zone-list">
              {drafts.map((d) => (
                <div key={d.key} className={`zone-item ${d.key === selected ? "active" : ""}`} onClick={() => setSelected(d.key)}>
                  <span className="zone-swatch" style={{ background: d.color || ZONE_KIND[d.kind].color }} />
                  <div className="zone-item-text">
                    <b>{d.name}</b>
                    <span className="muted small">{ZONE_KIND[d.kind].title}{!d.enabled && " · выключена"}{d.dirty && " · не сохранено"}</span>
                  </div>
                  <span className="muted small">{d.polygon.length} т.</span>
                </div>
              ))}
            </div>
            {sel && (
              <div className="zone-form">
                <Form layout="vertical" size="middle">
                  <Form.Item label="Название">
                    <Input value={sel.name} onChange={(e) => update(sel.key, { name: e.target.value })} maxLength={255} />
                  </Form.Item>
                  <Form.Item label="Тип зоны">
                    <Select value={sel.kind} onChange={(v: ZoneKind) => update(sel.key, { kind: v })}
                      options={(Object.keys(ZONE_KIND) as ZoneKind[]).map((k) => ({
                        value: k, label: <Space><span className="zone-swatch" style={{ background: ZONE_KIND[k].color }} />{ZONE_KIND[k].title}</Space>,
                      }))} />
                  </Form.Item>
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <Space><Switch checked={sel.enabled} onChange={(v) => update(sel.key, { enabled: v })} /> Зона активна</Space>
                    <Button danger icon={<DeleteOutlined />} onClick={() => removeZone(sel)}>Удалить</Button>
                  </Space>
                </Form>
              </div>
            )}
          </Card>

          <Card variant="borderless" className="side-card" style={{ marginTop: 20 }} title={`Правила · ${cam.rules.length}`}
            extra={<Button type="link" icon={<PlusOutlined />} onClick={() => setRuleModal({ open: true, rule: null })}>Добавить</Button>}>
            {cam.rules.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Нет правил — камера ничего не ищет" />}
            <div className="rule-list">
              {cam.rules.map((r) => {
                const sc = byCode.get(r.scenario);
                const sev = r.severity || sc?.severity || "medium";
                return (
                  <div key={r.id} className={`rule-item ${r.enabled ? "" : "disabled"}`}>
                    <span className="event-icon" style={{ color: SEVERITY[sev].color, background: SEVERITY[sev].bg }}><ScenarioIcon code={r.scenario} /></span>
                    <div className="rule-text">
                      <b>{sc?.title || r.scenario}</b>
                      <span className="muted small">{r.zone_id ? zoneName.get(r.zone_id) || `зона ${r.zone_id}` : "весь кадр"} · {scheduleText(r)}</span>
                      <span><SeverityTag value={sev} compact />{!r.severity && <span className="muted small"> по умолч.</span>}</span>
                    </div>
                    <div className="rule-actions">
                      <Switch size="small" checked={r.enabled} loading={saveRule.isPending && saveRule.variables?.id === r.id} onChange={(v) => toggleRule(r, v)} />
                      <Space size={0}>
                        <Button type="text" size="small" icon={<EditOutlined />} onClick={() => setRuleModal({ open: true, rule: r })} />
                        <Popconfirm title="Удалить правило?" okText="Удалить" okButtonProps={{ danger: true }}
                          onConfirm={() => deleteRule.mutate(r.id, { onSuccess: applied, onError: (e) => message.error(e.message) })}>
                          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </Space>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card variant="borderless" className="side-card" style={{ marginTop: 20 }} title="Камера">
            <Form layout="vertical">
              <Space size={24} wrap>
                <Form.Item label="FPS анализа" tooltip="Сколько кадров в секунду уходит в нейросеть — влияет на загрузку TPU">
                  <InputNumber min={0.2} max={30} step={0.5} defaultValue={cam.analysis_fps}
                    onBlur={(e) => {
                      const v = Number(e.target.value);
                      if (v && v !== cam.analysis_fps) patchCamera.mutate({ analysis_fps: v }, { onSuccess: applied, onError: (er) => message.error(er.message) });
                    }} />
                </Form.Item>
                <Form.Item label="Анализ включён">
                  <Switch checked={cam.enabled} loading={patchCamera.isPending}
                    onChange={(v) => patchCamera.mutate({ enabled: v }, { onSuccess: applied, onError: (er) => message.error(er.message) })} />
                </Form.Item>
              </Space>
              <div className="camera-source">
                <span className="muted small">Источник · {cam.source_type.toUpperCase()}</span>
                <Typography.Text copyable={{ text: cam.source_url }} ellipsis style={{ fontSize: 13 }}>{cam.source_url}</Typography.Text>
              </div>
            </Form>
          </Card>
        </Col>
      </Row>

      <RuleModal open={ruleModal.open} rule={ruleModal.rule} onClose={() => setRuleModal({ open: false, rule: null })}
        cameraId={cam.id} zones={cam.zones} scenarios={scenarios} onSaved={applied} />
    </div>
  );
}
