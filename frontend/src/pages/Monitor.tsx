import { useMemo, useState } from "react"
import type { Data } from "plotly.js"
import { useDigest, useMonitorFeed, useMonitorUnverified } from "../api/hooks"
import { Card, CountUp, EmptyState, Skeleton } from "../components/ui/Primitives"
import { PlotlyChart } from "../components/ui/PlotlyChart"
import type { FlagRow } from "../api/types"
import { cleanSummary } from "../lib/monitorText"

type ScopeTab = "both" | "rf" | "intl"

function fmtDate(iso?: string | null): string {
  if (!iso) return "н/д"
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" })
}

const CATEGORY_LABEL: Record<string, string> = {
  disqualification: "Дисквалификация",
  provisional: "Временное отстранение",
  event: "Мероприятие",
  policy: "Политика/регламент",
}

export default function Monitor() {
  const [scope, setScope] = useState<ScopeTab>("both")
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const digest = useDigest(scope, true)
  const feedRf = useMonitorFeed("rf", true)
  const feedIntl = useMonitorFeed("intl", true)
  const unverified = useMonitorUnverified(true)

  // Единая честная лента: подтверждённые публикации и неподтверждённые сигналы
  // вместе, в одном месте (разделе «Новости»), а не спрятаны отдельным блоком
  // внизу страницы. Разнести неподтверждённые по колонкам Россия/Международные
  // нельзя честно — контракт АД-Монитора не пишет им scope вообще (не поле
  // «потерялось», а его в принципе нет у неподтверждённых записей) — поэтому
  // они идут отдельным честно подписанным блоком «без привязки к потоку»,
  // а не куда-то в один из двух списков наугад.
  const mergedRfAll = useMergedFeed(feedRf.data?.items, undefined, "rf")
  const mergedIntlAll = useMergedFeed(feedIntl.data?.items, undefined, "intl")
  const unattributedAll = useMergedFeed(undefined, unverified.data?.items, null)

  const byCategory = (items: FeedListItem[]) =>
    categoryFilter ? items.filter((it) => it.category === categoryFilter) : items
  const mergedRf = byCategory(mergedRfAll)
  const mergedIntl = byCategory(mergedIntlAll)
  const unattributed = byCategory(unattributedAll)

  if (digest.isLoading) return <Skeleton className="h-96 w-full" />
  if (!digest.data?.available) {
    return (
      <EmptyState
        title="Дайджест ещё не поступал"
        hint="АД-Монитор публикует выпуск раз в 4 дня — первый появится после ближайшего прогона"
      />
    )
  }
  const d = digest.data

  const categoryChart: Data[] = d.by_category?.length
    ? [{ labels: d.by_category.map((c) => c.category as string), values: d.by_category.map((c) => c.n), type: "pie", hole: 0.45 }]
    : []
  const sourceChart: Data[] = d.by_source?.length
    ? [{ x: d.by_source.map((c) => c.n), y: d.by_source.map((c) => c.source_name as string), type: "bar", orientation: "h", marker: { color: "#3B82F6" } }]
    : []
  const countryChart: Data[] = d.by_country?.length
    ? [{ x: d.by_country.map((c) => c.country as string), y: d.by_country.map((c) => c.n), type: "bar", marker: { color: "#6a34e0" } }]
    : []
  const timelineChart: Data[] = d.timeline?.length
    ? [
        { x: d.timeline.map((t) => t.monitor_date), y: d.timeline.map((t) => t.confirmed_n), type: "scatter", mode: "lines+markers", name: "Подтверждено", line: { color: "#10B981" } },
        { x: d.timeline.map((t) => t.monitor_date), y: d.timeline.map((t) => t.unverified_n), type: "scatter", mode: "lines+markers", name: "Не подтверждено", line: { color: "#94A3B8" } },
      ]
    : []

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
            Выпуск от {fmtDate(d.monitor_date)}
          </p>
          <h1 className="text-2xl font-extrabold text-[var(--color-text)]">АД-Монитор</h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--color-sub)]">
            Мировая и российская антидопинговая повестка — прогон раз в 4 дня. Формулировки в
            обзоре готовит ИИ, но только пересказ уже подтверждённых новостей — без оценок риска.
          </p>
        </div>
        <div className="flex rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1">
          {(["both", "rf", "intl"] as ScopeTab[]).map((s) => (
            <button
              key={s}
              onClick={() => setScope(s)}
              className={`rounded-lg px-3 py-2 text-xs font-semibold ${
                scope === s ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)]"
              }`}
            >
              {s === "both" ? "Оба потока" : s === "rf" ? "Россия" : "Международный"}
            </button>
          ))}
        </div>
      </div>

      {/* ── 1. НОВОСТИ ── */}
      <section>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-extrabold text-[var(--color-text)]">Новости</h2>
          {categoryFilter && (
            <button
              onClick={() => setCategoryFilter(null)}
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-accent)]/20 px-2.5 py-1 text-xs font-semibold text-[var(--color-accent)] hover:bg-[var(--color-accent)]/30"
            >
              Фильтр: {CATEGORY_LABEL[categoryFilter] || categoryFilter} <span aria-hidden>✕</span>
            </button>
          )}
        </div>
        <Card className="p-4 sm:p-5">
          <p className="mb-4 text-xs text-[var(--color-sub)]">
            Каждая запись — с указанием первичного источника; клик по заголовку открывает
            оригинал. Записи без пометки — подтверждены проверкой кода; с пометкой в скобках —
            честно показанный пробел (сигнал ещё не подтверждён или ссылка недоступна). Клик по
            категории — фильтр по ней.
          </p>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {(scope === "both" || scope === "rf") && (
              <FeedList title="Россия" items={mergedRf} loading={feedRf.isLoading} onCategoryClick={setCategoryFilter} />
            )}
            {(scope === "both" || scope === "intl") && (
              <FeedList title="Международные" items={mergedIntl} loading={feedIntl.isLoading} onCategoryClick={setCategoryFilter} />
            )}
          </div>

          {!!unattributed.length && (
            <div className="mt-6 border-t border-[var(--color-line-soft)] pt-5">
              <FeedList
                title="Сигналы без привязки к потоку (не подтверждены)"
                items={unattributed}
                loading={unverified.isLoading}
              />
            </div>
          )}
        </Card>
      </section>

      {/* ── 2. ГРАФИКА И АНАЛИТИКА ── */}
      <section>
        <h2 className="mb-3 text-lg font-extrabold text-[var(--color-text)]">Графика и аналитика</h2>
        <div className="space-y-4">
          {(scope === "both" || scope === "rf") && d.narrative_rf && (
            <Card index={0} className="p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">Обзор — российский поток</h3>
              <p className="text-sm leading-relaxed text-[var(--color-text)]/90">{d.narrative_rf}</p>
            </Card>
          )}
          {(scope === "both" || scope === "intl") && d.narrative_intl && (
            <Card index={1} className="p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">Обзор — международный поток</h3>
              <p className="text-sm leading-relaxed text-[var(--color-text)]/90">{d.narrative_intl}</p>
            </Card>
          )}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card index={0} className="p-4">
              <div className="text-2xl font-extrabold text-[var(--color-text)]">
                <CountUp target={(d.by_category ?? []).reduce((a, c) => a + c.n, 0)} delayMs={150} />
              </div>
              <div className="text-xs text-[var(--color-sub)]">подтверждённых публикаций</div>
            </Card>
            <Card index={1} className="p-4">
              <div className="text-2xl font-extrabold text-[var(--color-zone-orange)]">
                <CountUp target={d.unverified_count ?? 0} delayMs={220} />
              </div>
              <div className="text-xs text-[var(--color-sub)]">не подтверждено</div>
            </Card>
            <Card index={2} className="p-4">
              <div className="text-2xl font-extrabold text-[var(--color-zone-red)]">
                <CountUp target={d.source_unavailable_count ?? 0} delayMs={290} />
              </div>
              <div className="text-xs text-[var(--color-sub)]">источник оказался недоступен</div>
            </Card>
            <Card index={3} className="p-4">
              <div className="text-2xl font-extrabold text-[var(--color-text)]">
                <CountUp target={d.timeline?.length ?? 0} delayMs={360} />
              </div>
              <div className="text-xs text-[var(--color-sub)]">выпусков в архиве</div>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card index={4} className="p-4 sm:p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">Типы событий</h3>
              {categoryChart.length ? <PlotlyChart data={categoryChart} height={280} layout={{ showlegend: true }} /> : <EmptyState title="Нет данных за выпуск" />}
            </Card>
            <Card index={5} className="p-4 sm:p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">По источникам</h3>
              {sourceChart.length ? <PlotlyChart data={sourceChart} height={280} layout={{ margin: { l: 220, r: 16 }, showlegend: false }} /> : <EmptyState title="Нет данных за выпуск" />}
            </Card>
            <Card index={6} className="p-4 sm:p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">По странам</h3>
              {countryChart.length ? <PlotlyChart data={countryChart} height={280} layout={{ margin: { b: 60 }, showlegend: false, xaxis: { type: "category" } }} /> : <EmptyState title="Нет данных за выпуск" />}
            </Card>
            <Card index={7} className="p-4 sm:p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--color-text)]">Динамика от выпуска к выпуску</h3>
              {timelineChart.length ? <PlotlyChart data={timelineChart} height={280} layout={{ xaxis: { type: "category" } }} /> : <EmptyState title="Пока один выпуск" />}
            </Card>
          </div>
        </div>
      </section>
    </div>
  )
}

interface FeedListItem {
  flag_id: number
  title: string
  summary: string | null
  source_name: string | null
  source_url: string
  event_date: string | null
  category?: string | null
  note: "не подтверждено" | "источник недоступен" | null
}

function useMergedFeed(
  confirmed: FlagRow[] | undefined,
  unverifiedAll: FlagRow[] | undefined,
  scope: "rf" | "intl" | null,
): FeedListItem[] {
  return useMemo(() => {
    const conf: FeedListItem[] = (confirmed ?? []).map((it) => ({
      flag_id: it.flag_id,
      title: it.title,
      summary: cleanSummary(it.summary),
      source_name: it.source_name,
      source_url: it.source_url,
      event_date: it.event_date,
      category: it.category,
      note: null,
    }))
    // scope у неподтверждённых записей контракт не пишет вообще — фильтр по
    // потоку тут неприменим, берём все как есть (вызывающая сторона решает,
    // передавать ли unverifiedAll в эту колонку).
    const unconf: FeedListItem[] = (unverifiedAll ?? [])
      .map((it) => ({
        flag_id: it.flag_id,
        title: it.title,
        summary: cleanSummary(it.summary),
        source_name: it.source_name,
        source_url: it.source_url,
        event_date: it.event_date,
        category: it.category,
        note: it.url_verified ? "не подтверждено" : "источник недоступен",
      }))
    return [...conf, ...unconf].sort((a, b) => (b.event_date || "").localeCompare(a.event_date || ""))
  }, [confirmed, unverifiedAll, scope])
}

function FeedList({
  title,
  items,
  loading,
  onCategoryClick,
}: {
  title: string
  items: FeedListItem[]
  loading: boolean
  onCategoryClick?: (category: string) => void
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-[var(--color-sub)]">{title}</h3>
      {loading ? (
        <Skeleton className="h-32" />
      ) : items.length ? (
        <ul className="space-y-3">
          {items.slice(0, 10).map((it) => (
            <li
              key={it.flag_id}
              className={`rounded-2xl border p-4 ${
                it.note
                  ? "border-[var(--color-zone-orange)]/25 bg-[var(--color-zone-orange)]/[0.06]"
                  : "border-[var(--color-line)] bg-[var(--color-surface)]"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                {!it.note && it.category && CATEGORY_LABEL[it.category] && (
                  <button
                    onClick={() => onCategoryClick?.(it.category!)}
                    className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white/70 transition hover:bg-white/20 hover:text-white"
                  >
                    {CATEGORY_LABEL[it.category]}
                  </button>
                )}
                <span className="text-xs font-medium text-[var(--color-sub)]">{fmtDate(it.event_date)}</span>
              </div>
              {it.source_url ? (
                <a
                  href={it.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1.5 block text-base font-bold leading-snug text-white hover:text-[var(--color-accent)] hover:underline"
                >
                  {it.title}
                  {it.note && <span className="ml-1.5 font-semibold text-[var(--color-zone-orange)]">({it.note})</span>}
                </a>
              ) : (
                <div className="mt-1.5 text-base font-bold leading-snug text-white">
                  {it.title}
                  {it.note && <span className="ml-1.5 font-semibold text-[var(--color-zone-orange)]">({it.note})</span>}
                </div>
              )}
              {it.summary && (
                <p className="mt-1.5 text-sm leading-relaxed text-white/70">{it.summary}</p>
              )}
              <div className="mt-2 text-xs font-medium text-[var(--color-sub)]">
                {it.source_name || "источник н/д"}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="Нет публикаций" />
      )}
    </div>
  )
}
