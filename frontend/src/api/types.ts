// api/types.ts — формы ответов API (зеркало api/routers/*.py). Не формулировки —
// только структура; человеческий текст (justification/recommendation) приходит
// готовым из БД (siar.rules.evaluate), фронтенд его не порождает и не меняет.

export type Zone = "RED" | "ORANGE" | "GREEN" | "NO_DATA"
export type Priority = 1 | 2 | 3 | 4

export interface QuadrantRow {
  result_id: number
  run_id: number
  kind: "osf" | "region"
  entity_name: string
  fo: string | null
  matched_model_name: string | null
  zone: Zone
  proba: number | null
  reason: string | null
  state: "A" | "B" | "C" | "D"
  priority: Priority
  status: string | null
  rating_score: number
  rating_high: boolean
  rating_place: number | null
  unmet_criteria: string[]
  has_attention_zone: boolean
  justification: string
  recommendation: string
  monitor_signals_30d: number | null
  monitor_signals_90d: number | null
  risk_rank: number | null
  siar_version: string
  risk_index: number | null
}

export interface Facts {
  lag_1q?: number
  lag_2q?: number
  rolling_mean_8q?: number
  rolling_sum_4q?: number
  human?: string
}

export interface DrilldownPeer {
  region?: string
  sport?: string
  zone: Zone
  proba: number | null
  reason: string | null
}

export interface SnapshotMeta {
  model_version: string | null
  rules_version: string | null
  computed_at: string | null
}

export interface MonitorFeedItem {
  title: string
  summary: string | null
  source_name: string | null
  source_url: string
  event_date: string | null
  scope: "rf" | "intl" | null
}

export interface EntityDetail extends QuadrantRow {
  facts: Facts
  monitor_signals_30d: number
  monitor_feed?: MonitorFeedItem[]
  monitor_feed_note?: string
  top_regions?: DrilldownPeer[]
  top_sports?: DrilldownPeer[]
  match_type: string | null
  match_confidence: number | null
  snapshot: SnapshotMeta
}

export interface ListResponse<T> {
  total: number
  returned: number
  items: T[]
}

export interface CountResponse<T> {
  count: number
  items: T[]
}

export interface Snapshot {
  run_id: number
  run_kind: string
  started_at: string
  finished_at: string | null
  published_at: string | null
  model_version: string | null
  rules_version: string | null
  n_osf: number
  n_regions: number
  n_inputs: number
}

export interface FoSummary {
  run_id: number
  fo: string
  regions: number
  avg_score: number
  p1: number
  p2: number
  p3: number
  p4: number
  zone_red: number
  zone_orange: number
  zone_green: number
  zone_no_data: number
}

export interface HistoryRow extends QuadrantRow {
  run_started_at: string
  run_published_at: string
  model_version: string | null
  rules_version: string | null
}

export interface CriterionHistoryRow {
  criterion_code: string
  block: string | null
  criterion_kind: "base" | "bonus" | "penalty"
  value: number
  is_met: boolean | null
  run_published_at: string
  model_version: string | null
}

export interface FeatureHistoryRow {
  target_year: number
  target_quarter: number
  proba: number
  zone: Zone
  reason: string | null
  lag_1q: number
  lag_2q: number
  rolling_mean_8q: number
  rolling_sum_4q: number
  run_published_at: string
}

export interface DigestCount {
  n: number
  [key: string]: string | number
}

export interface DigestTimelinePoint {
  monitor_date: string
  confirmed_n: number
  unverified_n: number
}

export interface DigestResponse {
  available: boolean
  message?: string
  monitor_date?: string
  scope?: string
  by_category?: DigestCount[]
  by_source?: DigestCount[]
  by_country?: DigestCount[]
  by_sport?: DigestCount[]
  timeline?: DigestTimelinePoint[]
  unverified_count?: number
  source_unavailable_count?: number
  narrative_rf?: string | null
  narrative_intl?: string | null
}

export interface FlagRow {
  flag_id: number
  monitor_date: string
  event_date: string | null
  category: string
  scope: "rf" | "intl" | null
  sport: string | null
  region: string | null
  country: string | null
  is_ru: boolean
  title: string
  summary: string | null
  source_name: string | null
  source_url: string
  url_verified: boolean
  confirmed: boolean
  expires_at: string | null
}

export interface PriorityTop5Row {
  entity_name: string
  fo?: string | null
  zone: Zone
  rating_score: number
  justification: string
}

export interface SummaryResponse {
  available: boolean
  current?: Record<string, number>
  previous?: Record<string, number> | null
  top5_priority1?: PriorityTop5Row[]
}

export interface GridCell {
  sport: string
  region: string
  zone: Zone
  proba: number | null
  reason: string | null
}
