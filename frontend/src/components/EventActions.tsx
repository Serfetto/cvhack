import { useState } from "react";
import { App, Button, Input, Modal, Space, Tooltip } from "antd";
import { CheckOutlined, CloseOutlined, SendOutlined } from "@ant-design/icons";
import type { EventOut, EventStatus } from "@/api/types";
import { useSetStatus } from "@/api/hooks";
import { useAuth } from "@/store/auth";
import { CAN, can } from "@/shared/roles";
import { STATUS } from "@/shared/severity";

const QUICK: { status: EventStatus; icon: JSX.Element; short: string; primary?: boolean }[] = [
  { status: "confirmed", icon: <CheckOutlined />, short: "Принял", primary: true },
  { status: "false", icon: <CloseOutlined />, short: "Ложное" },
  { status: "forwarded", icon: <SendOutlined />, short: "Мастеру" },
];

/** Быстрые действия «Подтвердить / Ложное / Передать мастеру» — в ленте и на телефоне мастера. */
export default function EventActions({ event, size = "small", block, onDone }: {
  event: EventOut; size?: "small" | "middle" | "large"; block?: boolean; onDone?: () => void;
}) {
  const role = useAuth((s) => s.user?.role);
  const { message } = App.useApp();
  const setStatus = useSetStatus();
  const [ask, setAsk] = useState<EventStatus | null>(null);
  const [comment, setComment] = useState("");
  if (!can(role, CAN.act) || event.status !== "new") return null;

  // мастеру «передать мастеру» не нужно
  const actions = QUICK.filter((a) => !(role === "master" && a.status === "forwarded"));

  const run = (status: EventStatus, text?: string) =>
    setStatus.mutate(
      { id: event.id, status, comment: text || null },
      {
        onSuccess: () => {
          message.success(`${STATUS[status].title}: ${event.scenario_title || event.scenario}`);
          setAsk(null);
          setComment("");
          onDone?.();
        },
        onError: (e) => message.error(e.message),
      },
    );

  const buttons = actions.map((a) => (
    <Tooltip key={a.status} title={size === "small" && !block ? STATUS[a.status].action : undefined}>
      <Button
        size={size}
        type={a.primary ? "primary" : "default"}
        // три кнопки на узком экране — без иконок, иначе подписи обрезаются
        icon={block && actions.length > 2 ? undefined : a.icon}
        block={block}
        loading={setStatus.isPending && setStatus.variables?.status === a.status}
        onClick={() => (a.status === "confirmed" ? run(a.status) : setAsk(a.status))}
      >
        {block ? a.short : size !== "small" ? STATUS[a.status].action : null}
      </Button>
    </Tooltip>
  ));

  return (
    <>
      {block ? (
        // телефон мастера: крупные кнопки сеткой, ничего не вылезает за экран
        <div className="actions-grid" style={{ gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))` }} onClick={(e) => e.stopPropagation()}>
          {buttons}
        </div>
      ) : (
        <Space.Compact onClick={(e) => e.stopPropagation()}>{buttons}</Space.Compact>
      )}
      <Modal
        open={!!ask}
        title={ask ? STATUS[ask].action : ""}
        okText={ask ? STATUS[ask].action : "OK"}
        onOk={() => ask && run(ask, comment)}
        confirmLoading={setStatus.isPending}
        onCancel={() => setAsk(null)}
        destroyOnHidden
      >
        <Input.TextArea autoFocus rows={3} value={comment} onChange={(e) => setComment(e.target.value)}
          placeholder={ask === "false" ? "Почему ложное: тень, манекен, сотрудник в разрешённой зоне…" : "Комментарий для мастера (необязательно)"} />
      </Modal>
    </>
  );
}
