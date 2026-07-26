// api/hooks.ts — React Query хуки поверх api/client.ts. Один хук = один эндпоинт.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./client"
import type {
  CountResponse,
  CriterionHistoryRow,
  DigestResponse,
  EntityDetail,
  FlagRow,
  FoSummary,
  GridCell,
  HistoryRow,
  ListResponse,
  QuadrantRow,
  Snapshot,
  SummaryResponse,
} from "./types"

export function useMeta(enabled: boolean) {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => api.get<{ siar_published_at: string | null; monitor_date: string | null }>("/api/v1/meta"),
    enabled,
    staleTime: 60_000,
  })
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth", "status"],
    queryFn: () => api.get<{ authenticated: boolean }>("/api/v1/auth/status"),
    staleTime: 0,
    retry: false,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (password: string) =>
      api.post<{ ok: boolean }>("/api/v1/auth/login", { password }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth", "status"] }),
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/v1/auth/logout"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth", "status"] }),
  })
}

export function useSnapshots(enabled: boolean) {
  return useQuery({
    queryKey: ["snapshots"],
    queryFn: () => api.get<ListResponse<Snapshot>>("/api/v1/snapshots"),
    enabled,
  })
}

export interface EntityFilters {
  zone?: string
  priority?: number
  fo?: string
  limit?: number
}

function toQuery(filters: EntityFilters): string {
  const p = new URLSearchParams()
  if (filters.zone) p.set("zone", filters.zone)
  if (filters.priority) p.set("priority", String(filters.priority))
  if (filters.fo) p.set("fo", filters.fo)
  if (filters.limit) p.set("limit", String(filters.limit))
  const s = p.toString()
  return s ? `?${s}` : ""
}

export function useOsfList(filters: EntityFilters, enabled: boolean) {
  return useQuery({
    queryKey: ["osf", filters],
    queryFn: () => api.get<ListResponse<QuadrantRow>>(`/api/v1/osf${toQuery(filters)}`),
    enabled,
  })
}

export function useRegionsList(filters: EntityFilters, enabled: boolean) {
  return useQuery({
    queryKey: ["regions", filters],
    queryFn: () => api.get<ListResponse<QuadrantRow>>(`/api/v1/regions${toQuery(filters)}`),
    enabled,
  })
}

export function useOsfSummary(enabled: boolean) {
  return useQuery({
    queryKey: ["osf", "summary"],
    queryFn: () => api.get<SummaryResponse>("/api/v1/osf/summary"),
    enabled,
  })
}

export function useRegionsSummary(enabled: boolean) {
  return useQuery({
    queryKey: ["regions", "summary"],
    queryFn: () => api.get<SummaryResponse>("/api/v1/regions/summary"),
    enabled,
  })
}

export function useFoSummary(enabled: boolean) {
  return useQuery({
    queryKey: ["regions", "fo-summary"],
    queryFn: () => api.get<ListResponse<FoSummary>>("/api/v1/regions/fo-summary"),
    enabled,
  })
}

export function useOsfDetail(entityName: string | null) {
  return useQuery({
    queryKey: ["osf", "detail", entityName],
    queryFn: () => api.get<EntityDetail>(`/api/v1/osf/${encodeURIComponent(entityName!)}`),
    enabled: !!entityName,
  })
}

export function useRegionDetail(entityName: string | null) {
  return useQuery({
    queryKey: ["regions", "detail", entityName],
    queryFn: () => api.get<EntityDetail>(`/api/v1/regions/${encodeURIComponent(entityName!)}`),
    enabled: !!entityName,
  })
}

export function useGrid(enabled: boolean) {
  return useQuery({
    queryKey: ["grid"],
    queryFn: () => api.get<CountResponse<GridCell>>("/api/v1/grid"),
    enabled,
  })
}

export function useHistoryEntities(kind: "osf" | "region", enabled: boolean) {
  return useQuery({
    queryKey: ["history", "entities", kind],
    queryFn: () =>
      api.get<CountResponse<{ entity_name: string; fo: string | null }>>(
        `/api/v1/history/entities?kind=${kind}`,
      ),
    enabled,
  })
}

export function useHistory(
  kind: "osf" | "region",
  entityName: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["history", kind, entityName],
    queryFn: () =>
      api.get<CountResponse<HistoryRow>>(
        `/api/v1/history?kind=${kind}${entityName ? `&entity_name=${encodeURIComponent(entityName)}` : ""}`,
      ),
    enabled,
  })
}

export function useCriterionHistory(
  kind: "osf" | "region",
  entityName: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["history", "criteria", kind, entityName],
    queryFn: () =>
      api.get<CountResponse<CriterionHistoryRow>>(
        `/api/v1/history/criteria?kind=${kind}&entity_name=${encodeURIComponent(entityName!)}`,
      ),
    enabled: enabled && !!entityName,
  })
}

export function useCompareEntities(
  kind: "osf" | "region",
  entities: string[],
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["history", "compare", kind, entities],
    queryFn: () =>
      api.get<CountResponse<HistoryRow>>(
        `/api/v1/history/compare?kind=${kind}&entities=${entities.map(encodeURIComponent).join(",")}`,
      ),
    enabled: enabled && entities.length > 0,
  })
}

export function useDigest(scope: "rf" | "intl" | "both", enabled: boolean) {
  return useQuery({
    queryKey: ["monitor", "digest", scope],
    queryFn: () => api.get<DigestResponse>(`/api/v1/monitor/digest?scope=${scope}`),
    enabled,
  })
}

export function useMonitorFeed(scope: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["monitor", "feed", scope],
    queryFn: () =>
      api.get<ListResponse<FlagRow>>(`/api/v1/monitor/feed${scope ? `?scope=${scope}` : ""}`),
    enabled,
  })
}

export function useMonitorUnverified(enabled: boolean) {
  return useQuery({
    queryKey: ["monitor", "unverified"],
    queryFn: () => api.get<ListResponse<FlagRow>>("/api/v1/monitor/unverified"),
    enabled,
  })
}

export interface UnmatchedRow {
  unmatched_id: number
  kind: "osf" | "region"
  side: "model" | "rating"
  name: string
  reason: string
}

export function useUnmatched(kind: "osf" | "region", enabled: boolean) {
  return useQuery({
    queryKey: ["unmatched", kind],
    queryFn: () => api.get<CountResponse<UnmatchedRow>>(`/api/v1/unmatched?kind=${kind}`),
    enabled,
  })
}

export function useSubmitFeedback() {
  return useMutation({
    mutationFn: (body: { section: string; message: string }) =>
      api.post<{ ok: boolean; message: string }>("/api/v1/feedback", body),
  })
}
