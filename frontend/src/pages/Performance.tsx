import { useEffect, useMemo, useState } from "react";
import { App, Badge, Button, Card, Col, Empty, Form, InputNumber, Row, Select, Space, Switch, Table, Tag, Tooltip, Typography } from "antd";
import type { TableProps } from "antd";
import {
  ApiOutlined, CalculatorOutlined, DashboardOutlined, ExperimentOutlined, LineChartOutlined, PlayCircleOutlined, ThunderboltOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import type { BenchmarkReport, IngestStream, ModelInfo } from "@/api/types";
import { useBenchmarks, useCameras, useModels, useRunBenchmark, useStreams } from "@/api/hooks";
import { fmtDateTime, plural } from "@/shared/format";
import { SERIES, SERIES_DARK } from "@/shared/severity";
import { GRAFANA_URL } from "@/env";
import PageHeader from "@/components/PageHeader";
import StatTile from "@/components/StatTile";
import EChart, { useChartInk } from "@/components/EChart";

const STAGES = ["queue", "pre", "rpc", "infer", "post"];
const STAGE_TITLE: Record<string, string> = { queue: "очередь", pre: "препроцессинг", rpc: "сеть (RPC)", infer: "инференс", post: "постобработка", total: "итого" };
const BACKEND_COLOR: Record<string, string> = { pytpu: "blue", remote: "geekblue", onnx: "orange", synthetic: "default" };

interface CalcModel {
  name: string;
  fps: number;
  every: number;
  on: boolean;
}

function Calculator({ benchmarks, loaded }: { benchmarks: BenchmarkReport[]; loaded: boolean }) {
  const [fa, setFa] = useState(5);
  const [models, setModels] = useState<CalcModel[]>([]);

  // по умолчанию — самый свежий замер на TPU для каждой модели
  useEffect(() => {
    if (models.length || !loaded) return;
    const best = new Map<string, number>();
    for (const b of benchmarks) {
      if (b.backend !== "pytpu" || b.model.includes("+")) continue;
      if (!best.has(b.model)) best.set(b.model, b.fps);
    }
    const list = [...best.entries()].map(([name, fps]) => ({ name, fps, every: 1, on: true }));
    // замеров на TPU нет — примерные числа из ARCHITECTURE §6.5, их можно поправить руками
    setModels(list.length ? list : [{ name: "pose (пример)", fps: 120, every: 1, on: true }, { name: "objects (пример)", fps: 90, every: 1, on: true }]);
  }, [benchmarks, loaded, models.length]);

  const active = models.filter((m) => m.on && m.fps > 0);
  const load = active.reduce((s, m) => s + fa / m.every / m.fps, 0); // доля TPU на одну камеру
  const cams = load > 0 ? 1 / load : 0;
  const set = (i: number, p: Partial<CalcModel>) => setModels((ms) => ms.map((m, j) => (j === i ? { ...m, ...p } : m)));

  return (
    <Card variant="borderless" className="chart-card" title={<span><CalculatorOutlined /> Сколько камер потянет одно устройство</span>}>
      <Row gutter={[24, 16]} align="middle">
        <Col xs={24} lg={14}>
          <Form layout="vertical">
            <Form.Item label="FPS анализа на камеру" tooltip="Сколько кадров в секунду с каждой камеры уходит в нейросети">
              <InputNumber min={0.2} max={30} step={0.5} value={fa} onChange={(v) => setFa(v || 1)} suffix="к/с" style={{ width: 140 }} />
            </Form.Item>
            <div className="calc-models">
              <div className="calc-head muted small"><span>Модель</span><span>FPS на TPU</span><span>Каждый N-й кадр</span><span /></div>
              {models.map((m, i) => (
                <div className="calc-row" key={m.name + i}>
                  <Typography.Text strong ellipsis>{m.name}</Typography.Text>
                  <InputNumber min={1} max={5000} value={m.fps} onChange={(v) => set(i, { fps: v || 1 })} />
                  <Select value={m.every} onChange={(v) => set(i, { every: v })} options={[1, 2, 3, 5].map((n) => ({ value: n, label: n === 1 ? "каждый" : `раз в ${n}` }))} />
                  <Switch checked={m.on} onChange={(v) => set(i, { on: v })} />
                </div>
              ))}
            </div>
          </Form>
        </Col>
        <Col xs={24} lg={10}>
          <div className="calc-result">
            <div className="calc-number">{cams ? Math.floor(cams) : "—"}</div>
            <div className="calc-label">{cams ? plural(Math.floor(cams), "камера", "камеры", "камер") : ""} на устройство</div>
            <div className="calc-formula">
              камер ≈ 1 / Σ (FPS<sub>анализа</sub> / N / FPS<sub>модели</sub>)
              <br />= 1 / ({active.map((m) => `${fa}${m.every > 1 ? `/${m.every}` : ""}/${m.fps}`).join(" + ") || "—"})
              {cams > 0 && <> ≈ <b>{cams.toFixed(1)}</b></>}
            </div>
            <Typography.Text type="secondary" className="small">Без запаса на пики. Для продакшена закладывайте 20–30% резерва (ARCHITECTURE §6.5).</Typography.Text>
          </div>
        </Col>
      </Row>
    </Card>
  );
}

export default function Performance() {
  const { message } = App.useApp();
  const ink = useChartInk();
  const models = useModels();
  const benchmarks = useBenchmarks();
  const streams = useStreams();
  const { data: cameras } = useCameras();
  const run = useRunBenchmark();
  const [runs, setRuns] = useState(200);
  const [camera, setCamera] = useState<string | undefined>();
  const [lastRun, setLastRun] = useState<string | null>(null);

  const m = models.data;
  const list = benchmarks.data || [];
  const online = (streams.data?.streams || []).filter((s) => s.state === "online").length;

  const start = () =>
    run.mutate({ runs, warmup: 20, camera_id: camera || null }, {
      onSuccess: (r) => { setLastRun(r.measured_at); message.success(`Замер готов: ${r.fps} к/с, p95 ${r.latency_ms.total?.p95 ?? "—"} мс`); },
      onError: (e) => message.error(e.message),
    });

  const chartRows = list.slice(0, 8);
  const colors = ink.dark ? SERIES_DARK : SERIES;
  const presentStages = STAGES.filter((s) => chartRows.some((r) => r.latency_ms[s]));
  const latencyOption = useMemo(() => ({
    grid: { left: 8, right: 24, top: 36, bottom: 24, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: ink.text }, itemWidth: 14, itemHeight: 8, icon: "roundRect" },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...ink.tooltip, valueFormatter: (v: number) => `${v} мс` },
    xAxis: { type: "value", name: "мс, p50", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: ink.muted }, axisLabel: { color: ink.muted }, splitLine: { lineStyle: { color: ink.grid } } },
    yAxis: {
      type: "category", inverse: true, axisTick: { show: false }, axisLine: { lineStyle: { color: ink.axis } },
      axisLabel: { color: ink.text, fontSize: 11, width: 170, overflow: "truncate" },
      data: chartRows.map((r) => `${r.model} · ${r.backend}`),
    },
    series: presentStages.map((s, i) => ({
      name: STAGE_TITLE[s], type: "bar", stack: "t", barMaxWidth: 22,
      data: chartRows.map((r) => r.latency_ms[s]?.p50 ?? 0),
      itemStyle: { color: colors[i], borderColor: ink.surface, borderWidth: 1, borderRadius: i === presentStages.length - 1 ? [0, 4, 4, 0] : 0 },
    })),
  }), [chartRows, presentStages, ink, colors]);

  const columns: TableProps<BenchmarkReport>["columns"] = [
    {
      title: "Модель", key: "model", render: (_, r) => (
        <div><b>{r.model}</b>{r.program && <div className="muted small">{r.program}</div>}</div>
      ),
    },
    { title: "Бэкенд", dataIndex: "backend", width: 110, render: (v: string) => <Tag color={BACKEND_COLOR[v] || "default"} bordered={false}>{v}</Tag> },
    { title: "Batch", dataIndex: "batch", width: 70, align: "right" },
    {
      title: "FPS", dataIndex: "fps", width: 90, align: "right", sorter: (a, b) => a.fps - b.fps,
      render: (v: number) => <b style={{ fontVariantNumeric: "tabular-nums" }}>{v.toFixed(1)}</b>,
    },
    {
      title: "Задержка p50 / p95, мс", key: "lat", render: (_, r) => (
        <div className="lat-cells">
          {[...STAGES, "total"].filter((s) => r.latency_ms[s]).map((s) => (
            <Tooltip key={s} title={STAGE_TITLE[s]}>
              <span className={`lat-cell ${s === "total" ? "lat-total" : ""}`}>
                <span className="muted">{s}</span> {r.latency_ms[s].p50} / {r.latency_ms[s].p95}
              </span>
            </Tooltip>
          ))}
        </div>
      ),
    },
    {
      title: "Замер", key: "at", width: 190, render: (_, r) => (
        <div>
          <div style={{ fontVariantNumeric: "tabular-nums" }}>{fmtDateTime(r.measured_at)}</div>
          <div className="muted small">{r.source}{r.runs ? ` · ${r.runs} прогонов` : ""}</div>
        </div>
      ),
    },
  ];

  const streamCols: TableProps<IngestStream>["columns"] = [
    { title: "Камера", dataIndex: "camera_id", render: (v: string) => cameras?.find((c) => c.id === v)?.name || v },
    {
      title: "Состояние", dataIndex: "state", render: (v: string, s) => (
        <Tooltip title={s.error}><Badge status={v === "online" ? "success" : v === "connecting" ? "processing" : v === "disabled" ? "default" : "error"} text={v} /></Tooltip>
      ),
    },
    {
      title: "FPS факт / цель", key: "fps", align: "right",
      render: (_, s) => <span style={{ fontVariantNumeric: "tabular-nums" }}>{(s.fps || 0).toFixed(1)} / {s.target_fps ?? "—"}</span>,
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Производительность"
        subtitle="Замеры на LinQ TPU и CPU: FPS, задержки по стадиям, ёмкость устройства"
        extra={<a href={GRAFANA_URL} target="_blank" rel="noreferrer"><Button icon={<LineChartOutlined />}>Grafana</Button></a>}
      />

      <Row gutter={[16, 16]}>
        <Col xs={12} xl={6}>
          <StatTile label="Активный бэкенд" icon={<ApiOutlined />} loading={models.isLoading}
            value={<Space>{m?.active_backend || "—"}{m?.fallback?.active && <Tag color="red">аварийный</Tag>}</Space>}
            sub={m?.error ? `ошибка: ${m.error}` : m?.fallback ? `резерв: ${m.fallback.backend}${m.fallback.last_error ? ` · ${m.fallback.last_error}` : ""}` : "без резерва"}
            accent={m?.fallback?.active || m?.error ? "#d03b3b" : "#2563eb"} />
        </Col>
        <Col xs={12} xl={6}>
          <StatTile label="Поток инференса" icon={<ThunderboltOutlined />} accent="#7c3aed" loading={models.isLoading}
            value={m ? `${m.fps.toFixed(1)} к/с` : "—"} sub="кадров обрабатывается сейчас" />
        </Col>
        <Col xs={12} xl={6}>
          <StatTile label="Моделей" icon={<ExperimentOutlined />} accent="#0ca30c" loading={models.isLoading}
            value={m?.models?.length ?? "—"} sub={(m?.models || []).map((x: ModelInfo) => x.name).join(" + ") || "—"} />
        </Col>
        <Col xs={12} xl={6}>
          <StatTile label="Камер в сети" icon={<VideoCameraOutlined />} accent="#e0a10f" loading={streams.isLoading}
            value={`${online} / ${streams.data?.streams.length ?? "—"}`} sub={`конфигурация: ${streams.data?.config_source || "—"}`} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={14}>
          <Card variant="borderless" className="chart-card" title={<span><DashboardOutlined /> Задержка по стадиям (p50)</span>}>
            {chartRows.length ? <EChart option={latencyOption} height={Math.max(240, chartRows.length * 46 + 60)} /> : <Empty description="Замеров ещё нет" />}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card variant="borderless" className="chart-card" title={<span><PlayCircleOutlined /> Запустить бенчмарк</span>}>
            <Form layout="vertical">
              <Space wrap size={16}>
                <Form.Item label="Прогонов"><InputNumber min={10} max={5000} step={50} value={runs} onChange={(v) => setRuns(v || 200)} /></Form.Item>
                <Form.Item label="Кадр" tooltip="Последний кадр камеры или синтетический 1280×720">
                  <Select allowClear placeholder="синтетический 1280×720" style={{ minWidth: 220 }} value={camera} onChange={setCamera}
                    options={(cameras || []).map((c) => ({ value: c.id, label: c.name }))} />
                </Form.Item>
              </Space>
              <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending} onClick={start} block>
                {run.isPending ? "Идёт замер…" : `Запустить на ${m?.active_backend || "текущем бэкенде"}`}
              </Button>
              {m?.models && (
                <div className="model-list">
                  {m.models.map((x: ModelInfo, i: number) => (
                    <div key={i} className="model-row">
                      <b>{x.name}</b>
                      <span className="muted small">{[x.version, Array.isArray(x.input) ? x.input.join("×") : x.input, x.program, x.preset].filter(Boolean).join(" · ")}</span>
                    </div>
                  ))}
                </div>
              )}
            </Form>
          </Card>
        </Col>
        <Col xs={24}>
          <Calculator benchmarks={list} loaded={!benchmarks.isLoading} />
        </Col>
        <Col xs={24}>
          <Card variant="borderless" title="История замеров" styles={{ body: { padding: 0 } }}>
            <Table<BenchmarkReport> rowKey={(r) => `${r.measured_at}-${r.model}-${r.backend}-${r.source}`} columns={columns} dataSource={list}
              loading={benchmarks.isLoading} pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 900 }}
              rowClassName={(r) => (r.measured_at === lastRun ? "row-highlight" : "")} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card variant="borderless" title="Потоки камер (ingest)" styles={{ body: { padding: 0 } }}>
            <Table<IngestStream> rowKey="camera_id" size="small" columns={streamCols} dataSource={streams.data?.streams} pagination={false} loading={streams.isLoading} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
