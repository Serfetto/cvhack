import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Col, DatePicker, Empty, Progress, Row, Segmented, Select, Skeleton, Space, Tooltip, Typography } from "antd";
import {
  AlertOutlined, CheckCircleOutlined, ClockCircleOutlined, FieldTimeOutlined, InfoCircleOutlined, RiseOutlined,
} from "@ant-design/icons";
import type { EventFilter } from "@/api/types";
import { useByArea, useByCamera, useByType, useDirectory, useHeatmap, usePrecision, useSummary, useTrend } from "@/api/hooks";
import { dayjs, DOW, fmtDuration, pct } from "@/shared/format";
import { SEVERITY } from "@/shared/severity";
import PageHeader from "@/components/PageHeader";
import StatTile from "@/components/StatTile";
import EChart, { useChartInk } from "@/components/EChart";
import { ScenarioIcon } from "@/components/Tags";
import { RANGE_PRESETS } from "./Journal";

const BLUE = "#2a78d6";
const BLUE_DARK = "#3987e5";
const HEAT = ["#eef4fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const HEAT_DARK = ["#16202e", "#173052", "#184f95", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"];

function ChartCard({ title, hint, children, extra, loading, empty }: {
  title: string; hint?: string; children: React.ReactNode; extra?: React.ReactNode; loading?: boolean; empty?: boolean;
}) {
  return (
    <Card variant="borderless" className="chart-card"
      title={<span>{title}{hint && <Tooltip title={hint}><InfoCircleOutlined className="muted" style={{ marginLeft: 8, fontSize: 13 }} /></Tooltip>}</span>}
      extra={extra}>
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : empty ? <Empty style={{ padding: "48px 0" }} description="Нет данных за период" /> : children}
    </Card>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const ink = useChartInk();
  const { tree, areas } = useDirectory();
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>(RANGE_PRESETS[3].value);
  const [area, setArea] = useState<number | undefined>();
  const [demo, setDemo] = useState<"all" | "real">("all");

  const filter: EventFilter = useMemo(() => ({
    from: range[0].toISOString(), to: range[1].toISOString(), area_id: area ? [area] : undefined, demo: demo === "real" ? false : undefined,
  }), [range, area, demo]);

  const summary = useSummary(filter);
  const todayFilter = useMemo(() => ({ ...filter, from: dayjs().startOf("day").toISOString(), to: undefined }), [filter]);
  const today = useSummary(todayFilter);
  const byType = useByType(filter);
  const byCamera = useByCamera(filter);
  const byArea = useByArea(filter);
  const heat = useHeatmap(filter);
  const trend = useTrend(filter);
  const precision = usePrecision(filter);

  /** Клик по графику → журнал с тем же периодом и уточняющим фильтром. */
  const toJournal = (extra: Record<string, string | undefined>) => {
    const p = new URLSearchParams();
    p.set("from", filter.from!);
    p.set("to", filter.to!);
    if (area) p.append("area_id", String(area));
    if (demo === "real") p.set("demo", "false");
    for (const [k, v] of Object.entries(extra)) if (v) { p.delete(k); p.append(k, v); }
    nav(`/journal?${p}`);
  };

  const s = summary.data;
  const color = ink.dark ? BLUE_DARK : BLUE;

  const axisCommon = {
    axisLine: { lineStyle: { color: ink.axis } },
    axisTick: { show: false },
    axisLabel: { color: ink.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: ink.grid } },
  };

  const typeOption = useMemo(() => ({
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...ink.tooltip },
    xAxis: { type: "category", data: (byType.data || []).map((r) => r.title || r.scenario), ...axisCommon, splitLine: { show: false },
      axisLabel: { ...axisCommon.axisLabel, interval: 0, width: 90, overflow: "break" } },
    yAxis: { type: "value", minInterval: 1, ...axisCommon, axisLine: { show: false } },
    series: [{
      name: "Событий", type: "bar", barMaxWidth: 44, data: (byType.data || []).map((r) => ({ value: r.count, code: r.scenario })),
      itemStyle: { color, borderRadius: [4, 4, 0, 0] }, emphasis: { itemStyle: { color: ink.dark ? "#5598e7" : "#256abf" } },
      label: { show: true, position: "top", color: ink.text, fontSize: 11 },
    }],
  }), [byType.data, ink, color]); // eslint-disable-line react-hooks/exhaustive-deps

  const hbar = (rows: { name: string; value: number; key: string }[]) => ({
    grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...ink.tooltip },
    xAxis: { type: "value", minInterval: 1, ...axisCommon, axisLine: { show: false } },
    yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name), ...axisCommon, splitLine: { show: false },
      axisLabel: { ...axisCommon.axisLabel, color: ink.text, width: 140, overflow: "truncate" } },
    series: [{
      name: "Событий", type: "bar", barMaxWidth: 22, data: rows.map((r) => ({ value: r.value, key: r.key })),
      itemStyle: { color, borderRadius: [0, 4, 4, 0] }, label: { show: true, position: "right", color: ink.text, fontSize: 11 },
    }],
  });

  const cameraRows = (byCamera.data || []).map((r) => ({ name: r.camera_name || r.camera_id, value: r.count, key: r.camera_id }));
  const areaRows = (byArea.data || []).map((r) => ({ name: r.area_id ? areas.get(r.area_id)?.name || `Участок ${r.area_id}` : "Без участка", value: r.count, key: String(r.area_id ?? "") }));

  const heatOption = useMemo(() => {
    const cells = heat.data || [];
    // шкала по 95-му перцентилю: один всплеск (например, текущий час с живыми камерами) не гасит остальные клетки
    const counts = cells.map((c) => c.count).filter((v) => v > 0).sort((a, b) => a - b);
    const max = Math.max(1, counts[Math.floor((counts.length - 1) * 0.95)] ?? 1);
    return {
      grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
      tooltip: { ...ink.tooltip, formatter: (p: { data: [number, number, number, number] }) => `${DOW[p.data[1]]}, ${String(p.data[0]).padStart(2, "0")}:00–${String(p.data[0] + 1).padStart(2, "0")}:00<br/><b>${p.data[3]}</b> событий` },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")), ...axisCommon, splitLine: { show: false }, axisLine: { show: false } },
      yAxis: { type: "category", data: DOW, inverse: true, ...axisCommon, splitLine: { show: false }, axisLine: { show: false } },
      visualMap: { min: 0, max, dimension: 2, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 12, itemHeight: 160,
        inRange: { color: ink.dark ? HEAT_DARK : HEAT }, textStyle: { color: ink.muted, fontSize: 11 }, text: ["чаще", "реже"] },
      series: [{
        type: "heatmap", data: cells.map((c) => [c.hour, c.dow, Math.min(c.count, max), c.count]),
        itemStyle: { borderColor: ink.surface, borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: ink.text, borderWidth: 1 } },
      }],
    };
  }, [heat.data, ink]); // eslint-disable-line react-hooks/exhaustive-deps

  const trendOption = useMemo(() => {
    const rows = trend.data || [];
    return {
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, textStyle: { color: ink.text }, itemWidth: 14, itemHeight: 8, icon: "roundRect" },
      tooltip: { trigger: "axis", ...ink.tooltip },
      xAxis: { type: "category", data: rows.map((r) => dayjs(r.date).format("DD.MM")), boundaryGap: false, ...axisCommon, splitLine: { show: false } },
      yAxis: { type: "value", minInterval: 1, ...axisCommon, axisLine: { show: false } },
      series: [
        { name: "Все события", type: "line", smooth: 0.3, symbol: "circle", symbolSize: 8, showSymbol: false, data: rows.map((r) => r.count),
          lineStyle: { width: 2, color }, itemStyle: { color, borderColor: ink.surface, borderWidth: 2 },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}40` }, { offset: 1, color: `${color}00` }] } } },
        { name: "Критичные", type: "line", smooth: 0.3, symbol: "circle", symbolSize: 8, showSymbol: false, data: rows.map((r) => r.critical),
          lineStyle: { width: 2, color: SEVERITY.critical.color }, itemStyle: { color: SEVERITY.critical.color, borderColor: ink.surface, borderWidth: 2 } },
      ],
    };
  }, [trend.data, ink, color]); // eslint-disable-line react-hooks/exhaustive-deps

  const areaOptions = tree.flatMap((x) => x.areas).map((a) => ({ value: a.id, label: a.name }));

  return (
    <div className="page">
      <PageHeader
        title="Дашборд"
        subtitle="Где и когда нарушают чаще — клик по столбцу открывает журнал с этим фильтром"
        extra={
          <Space wrap>
            <DatePicker.RangePicker presets={RANGE_PRESETS} value={range} allowClear={false} format="DD.MM.YYYY"
              onChange={(v) => v?.[0] && v[1] && setRange([v[0].startOf("day"), v[1].endOf("day")])} />
            <Select allowClear placeholder="Все участки" style={{ minWidth: 200 }} value={area} onChange={setArea} options={areaOptions} />
            <Segmented value={demo} onChange={(v) => setDemo(v as "all" | "real")}
              options={[{ label: "Все", value: "all" }, { label: "Без демо", value: "real" }]} />
          </Space>
        }
      />

      <Row gutter={[16, 16]}>
        <Col xs={12} md={8} xl={4}>
          <StatTile label="Сегодня" icon={<RiseOutlined />} value={today.data?.total ?? "—"} loading={today.isLoading}
            sub={`${s?.total ?? "—"} за период`} onClick={() => toJournal({ from: dayjs().startOf("day").toISOString(), to: dayjs().endOf("day").toISOString() })} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <StatTile label="Критичных" icon={<AlertOutlined />} accent={SEVERITY.critical.color} value={s?.critical ?? "—"} loading={summary.isLoading}
            sub={s?.total ? `${pct(s.critical / s.total)} от всех` : undefined} onClick={() => toJournal({ severity: "critical" })} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <StatTile label="Непринятых" icon={<ClockCircleOutlined />} accent={s?.unaccepted ? "#e0a10f" : "#0ca30c"} value={s?.unaccepted ?? "—"}
            loading={summary.isLoading} sub={s?.escalated ? `${s.escalated} эскалировано` : "без эскалаций"} onClick={() => toJournal({ status: "new" })} />
        </Col>
        <Col xs={12} md={8} xl={4}>
          <StatTile label="Время реакции" icon={<FieldTimeOutlined />} accent="#7c3aed" value={fmtDuration(s?.avg_reaction_s)} loading={summary.isLoading}
            hint="Среднее время от появления события до первого действия оператора" sub="среднее до первого действия" />
        </Col>
        <Col xs={24} md={16} xl={8}>
          <StatTile label="Точность по отметкам операторов" icon={<CheckCircleOutlined />} accent="#0ca30c" loading={summary.isLoading}
            hint="Доля подтверждённых и устранённых среди всех, что операторы отметили (подтверждено + устранено + ложное)"
            value={
              <Space align="center" size={16}>
                <span>{pct(s?.precision, 1)}</span>
                {s && <Progress percent={Math.round((s.precision || 0) * 100)} showInfo={false} strokeColor="#0ca30c" style={{ width: 160, margin: 0 }} />}
              </Space>
            }
            sub={s ? `${s.confirmed + s.resolved} подтверждено · ${s.false} ложных` : undefined} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={14}>
          <ChartCard title="Динамика по дням" loading={trend.isLoading} empty={!trend.data?.length}>
            <EChart option={trendOption} height={300}
              onClick={(p) => { const r = trend.data?.[p.dataIndex]; if (r) toJournal({ from: dayjs(r.date).startOf("day").toISOString(), to: dayjs(r.date).endOf("day").toISOString() }); }} />
          </ChartCard>
        </Col>
        <Col xs={24} xl={10}>
          <ChartCard title="Нарушения по типам" loading={byType.isLoading} empty={!byType.data?.length}>
            <EChart option={typeOption} height={300} onClick={(p) => toJournal({ scenario: (p.data as { code: string }).code })} />
          </ChartCard>
        </Col>
        <Col xs={24}>
          <ChartCard title="Когда чаще нарушают" hint="Количество событий по дням недели и часам (местное время)"
            loading={heat.isLoading} empty={!heat.data?.length}>
            <EChart option={heatOption} height={320} />
          </ChartCard>
        </Col>
        <Col xs={24} lg={12}>
          <ChartCard title="По камерам" loading={byCamera.isLoading} empty={!cameraRows.length}>
            <EChart option={hbar(cameraRows)} height={Math.max(200, cameraRows.length * 44)} onClick={(p) => toJournal({ camera_id: (p.data as { key: string }).key })} />
          </ChartCard>
        </Col>
        <Col xs={24} lg={12}>
          <ChartCard title="По участкам" loading={byArea.isLoading} empty={!areaRows.length}>
            <EChart option={hbar(areaRows)} height={Math.max(200, areaRows.length * 44)} onClick={(p) => toJournal({ area_id: (p.data as { key: string }).key })} />
          </ChartCard>
        </Col>
        <Col xs={24}>
          <ChartCard title="Точность сценариев по отметкам операторов" loading={precision.isLoading} empty={!precision.data?.length}
            hint="Онлайн-оценка precision: сколько из отмеченных операторами событий оказались настоящими нарушениями">
            <div className="precision-grid">
              {(precision.data || []).map((r) => {
                const marked = r.confirmed + r.false;
                return (
                  <div key={r.scenario} className="precision-row" onClick={() => toJournal({ scenario: r.scenario })}>
                    <Space size={10}><ScenarioIcon code={r.scenario} /><b>{r.title || r.scenario}</b></Space>
                    <Progress percent={r.precision != null ? Math.round(r.precision * 100) : 0} size="small"
                      strokeColor={r.precision == null ? undefined : r.precision >= 0.8 ? "#0ca30c" : r.precision >= 0.6 ? "#e0a10f" : "#d03b3b"}
                      format={() => pct(r.precision)} />
                    <Typography.Text type="secondary" className="small">{r.confirmed} подтв. · {r.false} ложн. · {marked} отмечено</Typography.Text>
                  </div>
                );
              })}
            </div>
          </ChartCard>
        </Col>
      </Row>
    </div>
  );
}
