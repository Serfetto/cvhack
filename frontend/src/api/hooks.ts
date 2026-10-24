import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./client";
import type {
  AreaRow, BenchmarkIn, BenchmarkReport, Camera, CameraDetail, CameraIn, CameraRow, EventDetail, EventFilter, EventPage,
  EventSort, HeatCell, IngestStream, MePatch, ModelsOut, PrecisionRow, RoleInfo, Rule, RuleIn, ScenarioInfo, StatusIn,
  Summary, TreeSite, TrendRow, TypeRow, User, UserCreate, UserPatch, Zone, ZoneIn,
} from "./types";
import { useLive } from "@/store/live";

type Q = Record<string, string | number | boolean | undefined | (string | number)[]>;
const fq = (f: EventFilter): Q => ({ ...f }) as Q;

// --- справочники -------------------------------------------------------------------

export function useTree() {
  return useQuery({ queryKey: ["tree"], queryFn: () => api.get<TreeSite[]>("/config/tree"), staleTime: 30_000 });
}

/** Плоские справочники из дерева: участки и камеры по id. */
export function useDirectory() {
  const { data, isLoading } = useTree();
  const dir = useMemo(() => {
    const areas = new Map<number, { id: number; name: string; site: string }>();
    const cameras = new Map<string, Camera>();
    for (const s of data || []) {
      for (const a of s.areas) {
        areas.set(a.id, { id: a.id, name: a.name, site: s.name });
        for (const c of a.cameras) cameras.set(c.id, c);
      }
    }
    return { tree: data || [], areas, cameras };
  }, [data]);
  return { ...dir, isLoading };
}

export function useScenarios() {
  const q = useQuery({ queryKey: ["scenarios"], queryFn: () => api.get<ScenarioInfo[]>("/config/scenarios"), staleTime: 60_000 });
  const byCode = useMemo(() => new Map((q.data || []).map((s) => [s.code, s])), [q.data]);
  return { ...q, byCode };
}

export function useRoles() {
  return useQuery({ queryKey: ["roles"], queryFn: () => api.get<RoleInfo[]>("/auth/roles"), staleTime: Infinity });
}

// --- события -----------------------------------------------------------------------

export function useEvents(filter: EventFilter, page: number, pageSize: number, sort: EventSort) {
  return useQuery({
    queryKey: ["events", "list", filter, page, pageSize, sort],
    queryFn: ({ signal }) => api.get<EventPage>("/events/events", { ...fq(filter), page, page_size: pageSize, sort }, signal),
    placeholderData: keepPreviousData,
  });
}

export function useEvent(id: string | null) {
  return useQuery({
    queryKey: ["events", "detail", id],
    queryFn: () => api.get<EventDetail>(`/events/events/${id}`),
    enabled: !!id,
  });
}

export function useSetStatus() {
  const qc = useQueryClient();
  const upsert = useLive((s) => s.upsert);
  return useMutation({
    mutationFn: ({ id, ...body }: StatusIn & { id: string }) => api.patch<EventDetail>(`/events/events/${id}/status`, body),
    onSuccess: (d) => {
      upsert(d);
      qc.setQueryData(["events", "detail", d.id], d);
      qc.invalidateQueries({ queryKey: ["events", "list"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useAddComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: string; comment: string }) => api.post<EventDetail>(`/events/events/${id}/comments`, { comment }),
    onSuccess: (d) => qc.setQueryData(["events", "detail", d.id], d),
  });
}

// --- статистика ----------------------------------------------------------------------

function stat<T>(name: string, filter: EventFilter, extra?: Q) {
  return {
    queryKey: ["stats", name, filter, extra],
    queryFn: () => api.get<T>(`/events/stats/${name}`, { ...fq(filter), ...extra }),
    placeholderData: keepPreviousData,
  };
}

export const useSummary = (f: EventFilter) => useQuery(stat<Summary>("summary", f));
export const useByType = (f: EventFilter) => useQuery(stat<TypeRow[]>("by-type", f));
export const useByCamera = (f: EventFilter) => useQuery(stat<CameraRow[]>("by-camera", f));
export const useByArea = (f: EventFilter) => useQuery(stat<AreaRow[]>("by-area", f));
export const useHeatmap = (f: EventFilter) => useQuery(stat<HeatCell[]>("heatmap", f));
export const useTrend = (f: EventFilter) => useQuery(stat<TrendRow[]>("trend", f));
export const usePrecision = (f: EventFilter) => useQuery(stat<PrecisionRow[]>("precision", f));

// --- камеры, зоны, правила ----------------------------------------------------------------

export function useCameras() {
  return useQuery({ queryKey: ["cameras"], queryFn: () => api.get<Camera[]>("/config/cameras"), refetchInterval: 10_000 });
}

export function useCamera(id: string | undefined) {
  return useQuery({ queryKey: ["camera", id], queryFn: () => api.get<CameraDetail>(`/config/cameras/${id}`), enabled: !!id });
}

function useConfigMutation<V, R>(fn: (v: V) => Promise<R>, cameraId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (cameraId) qc.invalidateQueries({ queryKey: ["camera", cameraId] });
      qc.invalidateQueries({ queryKey: ["cameras"] });
      qc.invalidateQueries({ queryKey: ["tree"] });
    },
  });
}

export const useCreateCamera = () => useConfigMutation((b: CameraIn) => api.post<Camera>("/config/cameras", b));
export const usePatchCamera = (id: string) =>
  useConfigMutation((b: Partial<CameraIn>) => api.patch<Camera>(`/config/cameras/${id}`, b), id);
export const useDeleteCamera = () => useConfigMutation((id: string) => api.del(`/config/cameras/${id}`));

export const useSaveZone = (cam: string) =>
  useConfigMutation(
    ({ id, ...b }: Partial<ZoneIn> & { id?: number }) =>
      id ? api.patch<Zone>(`/config/cameras/${cam}/zones/${id}`, b) : api.post<Zone>(`/config/cameras/${cam}/zones`, b),
    cam,
  );
export const useDeleteZone = (cam: string) => useConfigMutation((id: number) => api.del(`/config/cameras/${cam}/zones/${id}`), cam);

export const useSaveRule = (cam: string) =>
  useConfigMutation(
    ({ id, ...b }: Partial<RuleIn> & { id?: number }) => {
      if (!id) return api.post<Rule>(`/config/cameras/${cam}/rules`, b);
      const { scenario: _s, ...patch } = b; // сценарий правила не меняется — только пересоздать
      return api.patch<Rule>(`/config/cameras/${cam}/rules/${id}`, patch);
    },
    cam,
  );
export const useDeleteRule = (cam: string) => useConfigMutation((id: number) => api.del(`/config/cameras/${cam}/rules/${id}`), cam);

// --- производительность -----------------------------------------------------------------

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelsOut>("/inference/models"), refetchInterval: 5_000 });
}

export function useBenchmarks() {
  return useQuery({ queryKey: ["benchmarks"], queryFn: () => api.get<BenchmarkReport[]>("/inference/benchmarks") });
}

export function useRunBenchmark() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: BenchmarkIn) => api.post<BenchmarkReport>("/inference/benchmark", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benchmarks"] }),
  });
}

export function useStreams() {
  return useQuery({
    queryKey: ["streams"],
    queryFn: () => api.get<{ config_source: string; streams: IngestStream[] }>("/ingest/streams"),
    refetchInterval: 5_000,
  });
}

// --- профиль и пользователи ---------------------------------------------------------------

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me") });
}

export function usePatchMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: MePatch) => api.patch<User>("/auth/me", b),
    onSuccess: (u) => qc.setQueryData(["me"], u),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (b: { old_password: string; new_password: string }) => api.post<void>("/auth/me/password", b),
  });
}

export function useUsers() {
  return useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/auth/users") });
}

export function useSaveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...b }: (UserCreate | UserPatch) & { id?: number }) =>
      id ? api.patch<User>(`/auth/users/${id}`, b) : api.post<User>("/auth/users", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useSeedDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { days: number; per_day: number }) => api.post<{ created: number }>("/events/demo/seed", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stats"] }),
  });
}
