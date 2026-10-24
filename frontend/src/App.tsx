import { lazy, Suspense, useEffect } from "react";
import { App as AntApp, ConfigProvider, Spin, theme as antTheme } from "antd";
import ruRU from "antd/locale/ru_RU";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useUi } from "@/store/ui";
import { useAuth } from "@/store/auth";
import { homeFor, ROUTE_ROLES } from "@/shared/roles";
import AppLayout from "@/components/AppLayout";
import RequireRole from "@/components/RequireRole";
import Login from "@/pages/Login";

const Feed = lazy(() => import("@/pages/Feed"));
const Journal = lazy(() => import("@/pages/Journal"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Cameras = lazy(() => import("@/pages/Cameras"));
const CameraSetup = lazy(() => import("@/pages/CameraSetup"));
const Performance = lazy(() => import("@/pages/Performance"));
const Profile = lazy(() => import("@/pages/Profile"));
const Users = lazy(() => import("@/pages/Users"));
const NotFound = lazy(() => import("@/pages/NotFound"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
    },
  },
});

function Home() {
  const role = useAuth((s) => s.user?.role);
  return <Navigate to={homeFor(role)} replace />;
}

const page = (el: JSX.Element) => (
  <Suspense fallback={<div className="page-loading"><Spin size="large" /></div>}>{el}</Suspense>
);

export default function App() {
  const mode = useUi((s) => s.theme);
  const dark = mode === "dark";
  // токены CSS — на <html>, чтобы их видели и порталы antd (Drawer, Modal)
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
  }, [mode]);
  return (
    <ConfigProvider
      locale={ruRU}
      theme={{
        algorithm: dark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: {
          colorPrimary: "#2563eb",
          colorInfo: "#2563eb",
          colorError: "#d03b3b",
          colorSuccess: "#0ca30c",
          colorWarning: "#e0a10f",
          borderRadius: 10,
          fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
          colorBgLayout: dark ? "#0b0f17" : "#f4f6fa",
          colorBgContainer: dark ? "#131924" : "#ffffff",
          colorBorderSecondary: dark ? "#1f2733" : "#e9edf3",
        },
        components: {
          Layout: { siderBg: "#0b1220", headerBg: dark ? "#0f141d" : "#ffffff", headerPadding: "0 24px", headerHeight: 64 },
          Menu: { darkItemBg: "#0b1220", darkSubMenuItemBg: "#0b1220", darkItemSelectedBg: "#1d4ed8", itemBorderRadius: 8, itemHeight: 42 },
          Card: { paddingLG: 20 },
          Table: { headerBg: dark ? "#161d29" : "#f8fafc" },
        },
      }}
    >
      <AntApp notification={{ maxCount: 3, stack: { threshold: 2 }, placement: "bottomRight" }}>
        <QueryClientProvider client={queryClient}>
          <div className="app-root">
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={<AppLayout />}>
                  <Route index element={<Home />} />
                  <Route path="feed" element={page(<RequireRole roles={ROUTE_ROLES.feed}><Feed /></RequireRole>)} />
                  <Route path="journal" element={page(<RequireRole roles={ROUTE_ROLES.journal}><Journal /></RequireRole>)} />
                  <Route path="dashboard" element={page(<RequireRole roles={ROUTE_ROLES.dashboard}><Dashboard /></RequireRole>)} />
                  <Route path="cameras" element={page(<RequireRole roles={ROUTE_ROLES.cameras}><Cameras /></RequireRole>)} />
                  <Route path="cameras/:id" element={page(<RequireRole roles={ROUTE_ROLES.setup}><CameraSetup /></RequireRole>)} />
                  <Route path="performance" element={page(<RequireRole roles={ROUTE_ROLES.performance}><Performance /></RequireRole>)} />
                  <Route path="profile" element={page(<Profile />)} />
                  <Route path="users" element={page(<RequireRole roles={ROUTE_ROLES.users}><Users /></RequireRole>)} />
                  <Route path="*" element={page(<NotFound />)} />
                </Route>
              </Routes>
            </BrowserRouter>
          </div>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
