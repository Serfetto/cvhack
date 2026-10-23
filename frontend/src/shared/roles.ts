import type { Role } from "@/api/types";

export const ROLE_TITLE: Record<Role, string> = {
  admin: "Администратор",
  hse: "Охрана труда",
  master: "Мастер смены",
  operator: "Диспетчер",
  manager: "Руководитель",
  auditor: "Юрист / аудитор",
};

// Кто что может — повторяет проверки бэкенда (admin пускается всегда)
export const CAN = {
  act: ["operator", "master", "hse"] as Role[], // смена статуса, комментарии
  export: ["hse", "auditor", "manager"] as Role[],
  configure: ["hse"] as Role[], // камеры, зоны, правила
  users: [] as Role[],
};

export function can(role: Role | undefined, allowed: Role[]): boolean {
  if (!role) return false;
  return role === "admin" || allowed.includes(role);
}

// Доступ к экранам: меню и RequireRole
export const ROUTE_ROLES = {
  feed: ["operator", "master", "hse"] as Role[],
  journal: ["operator", "master", "hse", "manager", "auditor"] as Role[],
  dashboard: ["hse", "manager", "auditor"] as Role[],
  cameras: ["operator", "master", "hse"] as Role[],
  setup: ["hse"] as Role[],
  performance: ["hse", "manager"] as Role[],
  users: [] as Role[],
};

/** Стартовый экран роли: диспетчеру и мастеру — лента, руководителю — дашборд, юристу — журнал. */
export function homeFor(role: Role | undefined): string {
  switch (role) {
    case "manager":
      return "/dashboard";
    case "auditor":
      return "/journal";
    case "hse":
      return "/dashboard";
    default:
      return "/feed";
  }
}
