import { Button, Result } from "antd";
import { Link } from "react-router-dom";
import type { Role } from "@/api/types";
import { useAuth } from "@/store/auth";
import { can, homeFor } from "@/shared/roles";

export default function RequireRole({ roles, children }: { roles: Role[]; children: JSX.Element }) {
  const role = useAuth((s) => s.user?.role);
  if (!can(role, roles)) {
    return (
      <Result
        status="403"
        title="Нет доступа"
        subTitle="Этот раздел недоступен для вашей роли."
        extra={<Link to={homeFor(role)}><Button type="primary">На главную</Button></Link>}
      />
    );
  }
  return children;
}
