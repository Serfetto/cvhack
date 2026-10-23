import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App, Button, Checkbox, Collapse, DatePicker, Form, Modal, Segmented, Select, Space, Switch, TimePicker, Typography } from "antd";
import RjsfForm from "@rjsf/antd";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import type Core from "@rjsf/core";
import type { Rule, ScenarioInfo, Severity, Zone } from "@/api/types";
import { useSaveRule } from "@/api/hooks";
import { dayjs, DOW } from "@/shared/format";
import { SEVERITY, SEVERITY_ORDER } from "@/shared/severity";
import { ScenarioIcon } from "./Tags";

interface Props {
  open: boolean;
  onClose: () => void;
  cameraId: string;
  rule: Rule | null; // null — новое правило
  zones: Zone[];
  scenarios: ScenarioInfo[];
  onSaved: () => void;
}

type ScheduleMode = "always" | "schedule";

/** Значения по умолчанию из схемы — в правило пишем только то, что отличается (иначе новые дефолты не применятся). */
function defaults(s?: ScenarioInfo): Record<string, unknown> {
  return Object.fromEntries(Object.entries(s?.params_schema.properties || {}).filter(([, v]) => v.default !== undefined).map(([k, v]) => [k, v.default]));
}

// часто используемые параметры автомата — наверх, остальные по порядку схемы
const ORDER = ["confirm_s", "*", "threshold", "confirm_ratio", "release_s", "cooldown_s"];

export default function RuleModal({ open, onClose, cameraId, rule, zones, scenarios, onSaved }: Props) {
  const { message } = App.useApp();
  const save = useSaveRule(cameraId);
  const formRef = useRef<Core>(null);
  const [scenario, setScenario] = useState<string | undefined>();
  const [zoneId, setZoneId] = useState<number | null>(null);
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [mode, setMode] = useState<ScheduleMode>("always");
  const [days, setDays] = useState<number[]>([]);
  const [time, setTime] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [validUntil, setValidUntil] = useState<dayjs.Dayjs | null>(null);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!open) return;
    setScenario(rule?.scenario);
    setZoneId(rule?.zone_id ?? (zones[0]?.id ?? null));
    setSeverity(rule?.severity ?? null);
    setParams(rule?.params || {});
    const sch = rule?.schedule;
    setMode(sch && (sch.days?.length || sch.from || sch.to) ? "schedule" : "always");
    setDays(sch?.days || []);
    setTime(sch?.from && sch?.to ? [dayjs(sch.from, "HH:mm"), dayjs(sch.to, "HH:mm")] : null);
    setValidUntil(rule?.valid_until ? dayjs(rule.valid_until) : null);
    setEnabled(rule?.enabled ?? true);
  }, [open, rule, zones]);

  const info = scenarios.find((s) => s.code === scenario);
  const schema = useMemo(() => {
    if (!info) return null;
    const s = JSON.parse(JSON.stringify(info.params_schema)) as RJSFSchema;
    delete s.title;
    return s;
  }, [info]);
  const uiSchema: UiSchema = useMemo(() => {
    const keys = Object.keys(schema?.properties || {});
    return {
      // rjsf ругается на ключи порядка, которых нет в схеме
      "ui:order": ORDER.filter((k) => k === "*" || keys.includes(k)),
      "ui:submitButtonOptions": { norender: true },
    };
  }, [schema]);

  const submit = () => {
    if (!scenario || !info) return message.warning("Выберите сценарий");
    if (info.zone_required && zoneId === null) return message.warning(`Сценарию «${info.title}» нужна зона`);
    if (formRef.current && !formRef.current.validateForm()) return message.warning("Проверьте параметры сценария");
    const d = defaults(info);
    const changed = Object.fromEntries(Object.entries(params).filter(([k, v]) => v !== undefined && JSON.stringify(v) !== JSON.stringify(d[k])));
    const schedule = mode === "schedule" ? { days, from: time?.[0].format("HH:mm") ?? null, to: time?.[1].format("HH:mm") ?? null } : null;
    save.mutate(
      { id: rule?.id, scenario, zone_id: zoneId, severity, params: changed, schedule, valid_until: validUntil?.toISOString() ?? null, enabled },
      {
        onSuccess: () => { onSaved(); onClose(); },
        onError: (e) => message.error(e.message),
      },
    );
  };

  const untilPresets = [
    { label: "До 12:00 сегодня", value: dayjs().hour(12).minute(0).second(0) },
    { label: "До конца смены (20:00)", value: dayjs().hour(20).minute(0).second(0) },
    { label: "До конца недели", value: dayjs().endOf("week") },
  ];

  return (
    <Modal open={open} onCancel={onClose} width={680} title={rule ? "Правило" : "Новое правило"} destroyOnHidden
      okText={rule ? "Сохранить" : "Добавить правило"} onOk={submit} confirmLoading={save.isPending}>
      <Form layout="vertical" component={false}>
        <Form.Item label="Сценарий" required>
          <Select value={scenario} onChange={(v) => { setScenario(v); setParams({}); setSeverity(null); }} disabled={!!rule}
            placeholder="Что искать на кадре" size="large"
            options={scenarios.map((s) => ({
              value: s.code,
              label: <Space><ScenarioIcon code={s.code} />{s.title}<Typography.Text type="secondary" className="small">{s.requires.join(" + ")}</Typography.Text></Space>,
            }))} />
          {info?.description && <Typography.Paragraph type="secondary" className="small" style={{ margin: "6px 0 0" }}>{info.description}</Typography.Paragraph>}
        </Form.Item>

        <Space size={16} wrap style={{ width: "100%" }} className="rule-row">
          <Form.Item label="Зона" required={info?.zone_required} style={{ minWidth: 240 }}>
            <Select value={zoneId ?? "none"} onChange={(v) => setZoneId(v === "none" ? null : Number(v))}
              options={[
                ...(info?.zone_required ? [] : [{ value: "none", label: "Весь кадр" }]),
                ...zones.map((z) => ({ value: z.id, label: z.name })),
              ]} />
          </Form.Item>
          <Form.Item label="Важность" style={{ minWidth: 220 }}>
            <Select value={severity ?? "default"} onChange={(v) => setSeverity(v === "default" ? null : (v as Severity))}
              options={[
                { value: "default", label: `По умолчанию — ${info ? SEVERITY[info.severity].title.toLowerCase() : "из сценария"}` },
                ...SEVERITY_ORDER.map((s) => ({ value: s, label: <Space><span className="sev-dot" style={{ background: SEVERITY[s].color }} />{SEVERITY[s].title}</Space> })),
              ]} />
          </Form.Item>
          <Form.Item label="Включено">
            <Switch checked={enabled} onChange={setEnabled} />
          </Form.Item>
        </Space>

        <Form.Item label="Когда действует">
          <Segmented value={mode} onChange={(v) => setMode(v as ScheduleMode)}
            options={[{ label: "Всегда", value: "always" }, { label: "По расписанию", value: "schedule" }]} />
        </Form.Item>
        {mode === "schedule" && (
          <div className="schedule-box">
            <Form.Item label="Дни недели" extra="Ничего не выбрано — каждый день">
              <Checkbox.Group value={days} onChange={(v) => setDays(v as number[])} options={DOW.map((d, i) => ({ label: d, value: i }))} />
              <Space size={4} style={{ marginLeft: 8 }}>
                <Button size="small" type="link" onClick={() => setDays([0, 1, 2, 3, 4])}>Будни</Button>
                <Button size="small" type="link" onClick={() => setDays([])}>Все</Button>
              </Space>
            </Form.Item>
            <Form.Item label="Время" extra="Если «с» позже «по» — интервал через полночь (ночная смена)">
              <TimePicker.RangePicker format="HH:mm" minuteStep={5} value={time} order={false}
                onChange={(v) => setTime(v && v[0] && v[1] ? [v[0], v[1]] : null)} placeholder={["с", "по"]} />
              <Space size={4} style={{ marginLeft: 8 }} wrap>
                <Button size="small" type="link" onClick={() => setTime([dayjs("07:55", "HH:mm"), dayjs("12:00", "HH:mm")])}>07:55–12:00</Button>
                <Button size="small" type="link" onClick={() => setTime([dayjs("08:00", "HH:mm"), dayjs("20:00", "HH:mm")])}>Дневная смена</Button>
                <Button size="small" type="link" onClick={() => setTime([dayjs("20:00", "HH:mm"), dayjs("08:00", "HH:mm")])}>Ночная</Button>
              </Space>
            </Form.Item>
          </div>
        )}
        <Form.Item label="Действует до" extra="Временное правило — например, на время ремонта. Пусто — бессрочно">
          <Space wrap>
            <DatePicker showTime={{ format: "HH:mm" }} format="DD.MM.YYYY HH:mm" value={validUntil} onChange={setValidUntil} presets={untilPresets} />
            <Button size="small" type="link" onClick={() => setValidUntil(dayjs().hour(12).minute(0).second(0))}>до 12:00 сегодня</Button>
          </Space>
          {validUntil && validUntil.isBefore(dayjs()) && <Alert type="warning" showIcon message="Срок уже прошёл — правило не будет срабатывать" style={{ marginTop: 8 }} />}
        </Form.Item>

        {schema && (
          <Collapse
            defaultActiveKey={rule && Object.keys(rule.params || {}).length ? ["p"] : []}
            items={[{
              key: "p",
              label: <span>Параметры сценария <Typography.Text type="secondary" className="small">· форма из params_schema, значения по умолчанию подставлены</Typography.Text></span>,
              children: (
                <div className="rjsf-wrap">
                  <RjsfForm
                    ref={formRef}
                    schema={schema}
                    uiSchema={uiSchema}
                    formData={{ ...defaults(info), ...params }}
                    validator={validator}
                    onChange={(e) => setParams(e.formData || {})}
                    showErrorList={false}
                    liveValidate
                  />
                </div>
              ),
            }]}
          />
        )}
      </Form>
    </Modal>
  );
}
