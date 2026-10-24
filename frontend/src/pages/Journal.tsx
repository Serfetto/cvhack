import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { App, Button, Card, DatePicker, Segmented, Select, Space, Table, Tooltip, Typography } from "antd";
import type { TableProps } from "antd";
import { ClearOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import type { EventFilter, EventOut, EventSort, EventStatus, Severity } from "@/api/types";
import { download } from "@/api/client";
import { useDirectory, useEvents, useScenarios } from "@/api/hooks";
import { useAuth } from "@/store/auth";
import { CAN, can } from "@/shared/roles";
import { SEVERITY, SEVERITY_ORDER, STATUS, STATUS_ORDER } from "@/shared/severity";
import { dayjs, eventDuration, fmtDateTime, plural } from "@/shared/format";
import PageHeader from "@/components/PageHeader";
import { useOpenEvent } from "@/components/EventDrawer";
import { DemoTag, ScenarioIcon, SeverityTag, StatusTag } from "@/components/Tags";

/** Фильтры журнала живут в URL: ссылкой можно поделиться, «назад» в браузере их возвращает. */
export function filterFromParams(p: URLSearchParams): EventFilter {
  const list = (k: string) => (p.getAll(k).length ? p.getAll(k) : undefined);
  const demo = p.get("demo");
  return {
    camera_id: list("camera_id"),
    area_id: list("area_id")?.map(Number),
    zone_id: list("zone_id")?.map(Number),
    scenario: list("scenario"),
    severity: list("severity") as Severity[] | undefined,
    status: list("status") as EventStatus[] | undefined,
    from: p.get("from") || undefined,
    to: p.get("to") || undefined,
    demo: demo === null ? undefined : demo === "true",
  };
}

export const RANGE_PRESETS = [
  { label: "Сегодня", value: [dayjs().startOf("day"), dayjs().endOf("day")] as [dayjs.Dayjs, dayjs.Dayjs] },
  { label: "Вчера", value: [dayjs().subtract(1, "day").startOf("day"), dayjs().subtract(1, "day").endOf("day")] as [dayjs.Dayjs, dayjs.Dayjs] },
  { label: "7 дней", value: [dayjs().subtract(6, "day").startOf("day"), dayjs().endOf("day")] as [dayjs.Dayjs, dayjs.Dayjs] },
  { label: "30 дней", value: [dayjs().subtract(29, "day").startOf("day"), dayjs().endOf("day")] as [dayjs.Dayjs, dayjs.Dayjs] },
  { label: "Этот месяц", value: [dayjs().startOf("month"), dayjs().endOf("day")] as [dayjs.Dayjs, dayjs.Dayjs] },
];

const SORT_COLUMNS: Record<string, [EventSort, EventSort]> = {
  started_at: ["-started_at", "started_at"],
  severity: ["-severity", "-severity"],
};

export default function Journal() {
  const [params, setParams] = useSearchParams();
  const { message } = App.useApp();
  const role = useAuth((s) => s.user?.role);
  const open = useOpenEvent();
  const { tree, areas, cameras } = useDirectory();
  const { data: scenarios } = useScenarios();
  const [exporting, setExporting] = useState(false);

  const filter = useMemo(() => filterFromParams(params), [params]);
  const page = Number(params.get("page") || 1);
  const pageSize = Number(params.get("size") || 20);
  const sort = (params.get("sort") || "-started_at") as EventSort;
  const { data, isFetching, refetch } = useEvents(filter, page, pageSize, sort);

  const update = (patch: Record<string, string | string[] | undefined | null>, resetPage = true) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      p.delete(k);
      if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
      else if (v !== undefined && v !== null && v !== "") p.set(k, v);
    }
    if (resetPage) p.delete("page");
    setParams(p);
  };

  const hasFilters = ["camera_id", "area_id", "scenario", "severity", "status", "from", "to", "demo", "zone_id"].some((k) => params.has(k));

  const exportCsv = async () => {
    setExporting(true);
    try {
      await download("/events/events/export.csv", { ...filter } as Record<string, string | string[]>, "violations.csv");
      message.success("CSV выгружен — открывается в Excel");
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setExporting(false);
    }
  };

  const columns: TableProps<EventOut>["columns"] = [
    {
      title: "Кадр", key: "thumb", width: 92, render: (_, e) => (
        <div className="table-thumb">{e.snapshot_url && <img src={e.snapshot_url} alt="" loading="lazy" />}</div>
      ),
    },
    {
      title: "Время", dataIndex: "started_at", key: "started_at", width: 170, sorter: true,
      sortOrder: sort === "-started_at" ? "descend" : sort === "started_at" ? "ascend" : null,
      render: (v: string, e) => (
        <div>
          <div style={{ fontVariantNumeric: "tabular-nums" }}>{fmtDateTime(v)}</div>
          <div className="muted small">{eventDuration(v, e.ended_at)}</div>
        </div>
      ),
    },
    {
      title: "Нарушение", key: "scenario", render: (_, e) => (
        <Space size={8}>
          <span className="event-icon" style={{ color: SEVERITY[e.severity].color, background: SEVERITY[e.severity].bg }}><ScenarioIcon code={e.scenario} /></span>
          <div>
            <div><b>{e.scenario_title || e.scenario}</b> {e.demo && <DemoTag />}</div>
            <div className="muted small">{e.zone_name || "весь кадр"}</div>
          </div>
        </Space>
      ),
    },
    {
      title: "Важность", dataIndex: "severity", key: "severity", width: 140, sorter: true, sortOrder: sort === "-severity" ? "descend" : null,
      render: (v: Severity) => <SeverityTag value={v} compact />,
    },
    {
      title: "Камера / участок", key: "camera", render: (_, e) => (
        <div>
          <div>{e.camera_name || e.camera_id}</div>
          <div className="muted small">{e.area_id ? areas.get(e.area_id)?.name : "—"}</div>
        </div>
      ),
    },
    { title: "Статус", dataIndex: "status", key: "status", width: 170, render: (v: EventStatus) => <StatusTag value={v} /> },
    {
      title: "Увер.", dataIndex: "confidence", key: "confidence", width: 70, align: "right",
      render: (v: number | null) => (v != null ? `${Math.round(v * 100)}%` : "—"),
    },
  ];

  const onTableChange: TableProps<EventOut>["onChange"] = (pg, _f, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    let nextSort: EventSort = "-started_at";
    if (s?.order && s.columnKey && SORT_COLUMNS[s.columnKey as string]) {
      nextSort = SORT_COLUMNS[s.columnKey as string][s.order === "ascend" ? 1 : 0];
    }
    update({ page: String(pg.current || 1), size: String(pg.pageSize || 20), sort: nextSort === "-started_at" ? null : nextSort }, false);
  };

  const cameraOptions = [...cameras.values()].map((c) => ({ value: c.id, label: c.name }));
  const areaOptions = tree.flatMap((s) => s.areas).map((a) => ({ value: String(a.id), label: a.name }));

  return (
    <div className="page">
      <PageHeader
        title="Журнал нарушений"
        subtitle={data ? `${data.total.toLocaleString("ru-RU")} ${plural(data.total, "запись", "записи", "записей")} по фильтру` : "История нарушений и действий операторов"}
        extra={
          <Space>
            <Tooltip title="Обновить"><Button icon={<ReloadOutlined spin={isFetching} />} onClick={() => refetch()} /></Tooltip>
            {can(role, CAN.export) && (
              <Button type="primary" icon={<DownloadOutlined />} loading={exporting} onClick={exportCsv}>Экспорт CSV</Button>
            )}
          </Space>
        }
      />

      <Card variant="borderless" className="filters-card">
        <div className="filters">
          <DatePicker.RangePicker
            showTime={{ format: "HH:mm" }}
            format="DD.MM.YY HH:mm"
            presets={RANGE_PRESETS}
            value={filter.from ? [dayjs(filter.from), filter.to ? dayjs(filter.to) : null] : null}
            onChange={(v) => update({ from: v?.[0]?.toISOString(), to: v?.[1]?.toISOString() })}
            allowEmpty={[true, true]}
            placeholder={["Период с", "по"]}
          />
          <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Тип нарушения" style={{ minWidth: 200 }}
            value={filter.scenario || []} onChange={(v) => update({ scenario: v })}
            options={(scenarios || []).map((s) => ({ value: s.code, label: s.title }))} />
          <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Участок" style={{ minWidth: 180 }}
            value={(filter.area_id || []).map(String)} onChange={(v) => update({ area_id: v })} options={areaOptions} />
          <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Камера" style={{ minWidth: 180 }}
            value={filter.camera_id || []} onChange={(v) => update({ camera_id: v })} options={cameraOptions} />
          <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Важность" style={{ minWidth: 160 }}
            value={filter.severity || []} onChange={(v) => update({ severity: v })}
            options={SEVERITY_ORDER.map((s) => ({ value: s, label: SEVERITY[s].title }))} />
          <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Статус" style={{ minWidth: 160 }}
            value={filter.status || []} onChange={(v) => update({ status: v })}
            options={STATUS_ORDER.map((s) => ({ value: s, label: STATUS[s].title }))} />
          <Segmented
            value={filter.demo === undefined ? "all" : filter.demo ? "demo" : "real"}
            onChange={(v) => update({ demo: v === "all" ? null : String(v === "demo") })}
            options={[{ label: "Все", value: "all" }, { label: "Реальные", value: "real" }, { label: "Демо", value: "demo" }]}
          />
          {hasFilters && (
            <Button type="link" icon={<ClearOutlined />} onClick={() => setParams(new URLSearchParams())}>Сбросить</Button>
          )}
        </div>
        {filter.zone_id && (
          <Typography.Text type="secondary" className="small">Фильтр по зоне: {filter.zone_id.join(", ")}</Typography.Text>
        )}
      </Card>

      <Card variant="borderless" styles={{ body: { padding: 0 } }}>
        <Table<EventOut>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={data?.items}
          loading={isFetching && !data}
          onChange={onTableChange}
          onRow={(e) => ({ onClick: () => open(e.id), style: { cursor: "pointer" } })}
          rowClassName={(e) => (e.status === "new" ? "row-new" : "")}
          scroll={{ x: 900 }}
          pagination={{
            current: page, pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100],
            showTotal: (t, r) => `${r[0]}–${r[1]} из ${t.toLocaleString("ru-RU")}`,
          }}
          locale={{ emptyText: hasFilters ? "Ничего не найдено — попробуйте ослабить фильтры" : "Журнал пуст" }}
        />
      </Card>
    </div>
  );
}
