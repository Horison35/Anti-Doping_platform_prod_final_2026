import { useEffect, useMemo, useRef, useState } from "react"
import type { Data } from "plotly.js"
import { useCompareEntities, useCriterionHistory, useHistory, useHistoryEntities } from "../api/hooks"
import { Card, EmptyState, Skeleton } from "../components/ui/Primitives"
import { PlotlyChart } from "../components/ui/PlotlyChart"
import { ZoneBadge, PriorityBadge } from "../components/ui/Badge"
import { Section } from "../components/domain/DrillDownCard"
import { Modal } from "../components/ui/Modal"
import type { HistoryRow } from "../api/types"

function fmtDateShort(iso: string | null): string {
  if (!iso) return "н/д"
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
}

// Обоснование конкретного исторического прогона — те же данные, что и в
// карточке «Почему именно так», но взятые из уже загруженной строки истории
// (v_quadrant_history), без дополнительного запроса к API.
function HistoryRunCard({ row, onClose }: { row: HistoryRow; onClose: () => void }) {
  return (
    <Modal title={`Прогон от ${fmtDateShort(row.run_published_at)}`} onClose={onClose}>
      <h2 className="text-xl font-extrabold text-[var(--color-text)] sm:text-2xl">
        {row.entity_name}
        {row.fo && <span className="ml-2 text-sm font-medium text-[var(--color-sub)]">{row.fo}</span>}
      </h2>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <PriorityBadge priority={row.priority} />
        <ZoneBadge zone={row.zone} />
      </div>

      <Section title="Обоснование зоны риска">
        {row.reason ? (
          <p>
            Сработало правило: <b>{row.reason}</b>.
          </p>
        ) : (
          <p>Систематичности по истории нарушений не выявлено.</p>
        )}
        {row.proba != null && (
          <p className="mt-1 text-xs text-[var(--color-sub)]">
            Необработанная оценка модели (для аналитика): {row.proba.toFixed(3)}
          </p>
        )}
      </Section>

      <Section title="Обоснование приоритета">
        <p>{row.justification}</p>
        <p className="mt-2 text-[var(--color-sub)]">
          Балл рейтинга РУСАДА на момент прогона — {row.rating_score} (
          {row.rating_high ? "оценивается как высокий" : "ниже порога высокого уровня"}).
        </p>
      </Section>

      <Section title="Рекомендация">
        <p>{row.recommendation}</p>
      </Section>

      <Section title="На каких данных посчитано">
        <p>
          Версия модели {row.model_version || "н/д"}, версия правил {row.rules_version || "н/д"}.
          Этот прогон зафиксирован и не пересчитывается задним числом.
        </p>
      </Section>
    </Modal>
  )
}

type Kind = "osf" | "region"
type Mode = "single" | "compare"

const ZONE_NUM: Record<string, number> = { GREEN: 0, ORANGE: 1, RED: 2, NO_DATA: -1 }
const COMPARE_COLORS = ["#e7edf7", "#DC2626", "#F59E0B", "#10B981", "#3B82F6", "#7C8DA6"]

// Цвет закреплён за названием связки (хэш), а не за позицией в ответе API —
// иначе при добавлении/снятии связки из сравнения сервер (ORDER BY entity_name)
// переставляет строки, и уже нарисованные линии внезапно меняют цвет.
function compareColorIndex(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h % COMPARE_COLORS.length
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { year: "numeric", month: "short", day: "2-digit" })
}

// Список из 100+ связок руками не пролистать — как обычный select, но с
// поиском по вводу вместо прокрутки нативного списка браузера.
function EntityCombobox({
  entities,
  loading,
  value,
  onChange,
}: {
  entities: { entity_name: string; fo: string | null }[]
  loading: boolean
  value: string | null
  onChange: (name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery("")
      }
    }
    document.addEventListener("mousedown", onOutside)
    return () => document.removeEventListener("mousedown", onOutside)
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return entities
    return entities.filter((e) => e.entity_name.toLowerCase().includes(q))
  }, [entities, query])

  return (
    <div ref={boxRef} className="relative w-full sm:max-w-md">
      <input
        value={open ? query : value ?? ""}
        onFocus={() => {
          setOpen(true)
          setQuery("")
        }}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        placeholder={loading ? "Загрузка…" : "Поиск связки — начните вводить название…"}
        className="w-full rounded-xl border border-[var(--color-line)] bg-[var(--color-surface)] px-4 py-2.5 text-sm text-[var(--color-text)] backdrop-blur-xl outline-none focus:border-[var(--color-accent)]"
      />
      {open && (
        <div className="absolute z-20 mt-1.5 max-h-72 w-full overflow-y-auto rounded-xl border border-[var(--color-line)] bg-[#0b1220] shadow-2xl">
          {filtered.length === 0 && (
            <div className="px-4 py-3 text-sm text-[var(--color-sub)]">Ничего не найдено</div>
          )}
          {filtered.map((e) => (
            <button
              key={e.entity_name}
              type="button"
              onClick={() => {
                onChange(e.entity_name)
                setOpen(false)
                setQuery("")
              }}
              className={`block w-full px-4 py-2.5 text-left text-sm hover:bg-[var(--color-surface-hover)] ${
                value === e.entity_name ? "bg-[var(--color-surface-hover)] font-semibold text-white" : "text-[var(--color-text)]"
              }`}
            >
              {e.entity_name}
              {e.fo && <span className="ml-2 text-xs text-[var(--color-sub)]">{e.fo}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function History() {
  const [kind, setKind] = useState<Kind>("osf")
  const [mode, setMode] = useState<Mode>("single")
  const [entity, setEntity] = useState<string | null>(null)
  const [compareSet, setCompareSet] = useState<string[]>([])
  const [search, setSearch] = useState("")
  const [openRun, setOpenRun] = useState<HistoryRow | null>(null)

  const entities = useHistoryEntities(kind, true)
  const history = useHistory(kind, entity, mode === "single" && !!entity)
  const criteria = useCriterionHistory(kind, entity, mode === "single" && !!entity)
  const compare = useCompareEntities(kind, compareSet, mode === "compare" && compareSet.length > 0)

  const filteredEntities = useMemo(() => {
    const items = entities.data?.items ?? []
    if (!search.trim()) return items
    const q = search.trim().toLowerCase()
    return items.filter((e) => e.entity_name.toLowerCase().includes(q))
  }, [entities.data, search])

  const zoneSeries = useMemo<Data[]>(() => {
    if (!history.data?.items.length) return []
    const rows = history.data.items
    return [
      {
        x: rows.map((r) => fmtDate(r.run_published_at)),
        y: rows.map((r) => ZONE_NUM[r.zone] ?? -1),
        mode: "lines+markers",
        type: "scatter",
        name: "Зона риска",
        line: { color: "#e7edf7", shape: "hv" },
        marker: { color: rows.map((r) => ({ RED: "#DC2626", ORANGE: "#F59E0B", GREEN: "#10B981", NO_DATA: "#94A3B8" }[r.zone] || "#94A3B8")), size: 10 },
        hovertext: rows.map((r) => `${r.zone} · ${r.justification}`),
        hovertemplate: "%{hovertext}<extra></extra>",
      },
    ]
  }, [history.data])

  const prioritySeries = useMemo<Data[]>(() => {
    if (!history.data?.items.length) return []
    const rows = history.data.items
    return [
      {
        x: rows.map((r) => fmtDate(r.run_published_at)),
        y: rows.map((r) => r.priority),
        mode: "lines+markers",
        type: "scatter",
        name: "Приоритет",
        line: { color: "#3B82F6", shape: "hv" },
        marker: { color: rows.map((r) => ({ 1: "#DC2626", 2: "#F59E0B", 3: "#3B82F6", 4: "#10B981" }[r.priority] || "#94A3B8")), size: 10 },
        hovertext: rows.map((r) => `Приоритет ${r.priority} · ${r.zone}<br>${r.justification}`),
        hovertemplate: "%{hovertext}<extra></extra>",
      },
    ]
  }, [history.data])

  const ratingSeries = useMemo<Data[]>(() => {
    if (!history.data?.items.length) return []
    const rows = history.data.items
    return [
      {
        x: rows.map((r) => fmtDate(r.run_published_at)),
        y: rows.map((r) => r.rating_score),
        mode: "lines+markers",
        type: "scatter",
        name: "Балл рейтинга РУСАДА",
        line: { color: "#7C8DA6" },
        marker: { size: 8 },
        hovertext: rows.map(
          (r) => `Балл: ${r.rating_score} (${r.rating_high ? "оценивается как высокий" : "ниже порога высокого уровня"})`,
        ),
        hovertemplate: "%{hovertext}<extra></extra>",
      },
    ]
  }, [history.data])

  const criteriaPivot = useMemo(() => {
    const items = criteria.data?.items ?? []
    const baseItems = items.filter((c) => c.criterion_kind === "base")
    const quarters = [...new Set(baseItems.map((c) => c.run_published_at))].sort()
    const codes = [...new Set(baseItems.map((c) => c.criterion_code))]
    const grid = new Map<string, Map<string, boolean | null>>()
    for (const c of baseItems) {
      if (!grid.has(c.criterion_code)) grid.set(c.criterion_code, new Map())
      grid.get(c.criterion_code)!.set(c.run_published_at, c.is_met)
    }
    return { quarters, codes, grid }
  }, [criteria.data])

  const compareSeries = useMemo<Data[]>(() => {
    if (!compare.data?.items.length) return []
    const byEntity = new Map<string, typeof compare.data.items>()
    for (const row of compare.data.items) {
      const arr = byEntity.get(row.entity_name) ?? []
      arr.push(row)
      byEntity.set(row.entity_name, arr)
    }
    // Порядок линий — по порядку выбора пользователем (compareSet), не по
    // алфавитному порядку ответа API (см. компаратор цвета выше).
    return compareSet
      .filter((name) => byEntity.has(name))
      .map((name) => {
        const rows = byEntity.get(name)!
        return {
          x: rows.map((r) => fmtDate(r.run_published_at)),
          y: rows.map((r) => r.priority),
          mode: "lines+markers",
          type: "scatter",
          name,
          line: { color: COMPARE_COLORS[compareColorIndex(name)] },
          hovertext: rows.map((r) => `${name}<br>Приоритет ${r.priority} · ${r.zone}`),
          hovertemplate: "%{hovertext}<extra></extra>",
        } as Data
      })
  }, [compare.data, compareSet])

  // Табличное сравнение «здесь и сейчас» — при одном-двух прогонах график
  // «Приоритет во времени» показывает почти пустое поле (совпадающие по
  // приоритету связки садятся друг на друга в одну точку); таблица читается
  // одинаково хорошо при любом числе прогонов и график ничем не заменяет,
  // просто даёт то, что полезно уже сейчас.
  const compareLatest = useMemo(() => {
    if (!compare.data?.items.length) return []
    const latestByEntity = new Map<string, HistoryRow>()
    for (const row of compare.data.items) {
      const existing = latestByEntity.get(row.entity_name)
      if (!existing || row.run_published_at > existing.run_published_at) {
        latestByEntity.set(row.entity_name, row)
      }
    }
    return compareSet.filter((name) => latestByEntity.has(name)).map((name) => latestByEntity.get(name)!)
  }, [compare.data, compareSet])

  function toggleCompare(name: string) {
    setCompareSet((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]))
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
          Архив прогонов
        </p>
        <h1 className="text-2xl font-extrabold text-[var(--color-text)]">Динамика рисковости</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--color-sub)]">
          Архив таблиц дисквалификаций не очищается — здесь видно, как менялась зона риска,
          приоритет и балл рейтинга по каждой связке от прогона к прогону.
        </p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1 sm:w-fit">
          {(["osf", "region"] as Kind[]).map((k) => (
            <button
              key={k}
              onClick={() => {
                setKind(k)
                setEntity(null)
                setCompareSet([])
              }}
              className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                kind === k ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)]"
              }`}
            >
              {k === "osf" ? "ОСФ" : "Регионы"}
            </button>
          ))}
        </div>

        <div className="flex rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1 sm:w-fit">
          {([
            { k: "single", label: "Одна связка" },
            { k: "compare", label: "Сравнение" },
          ] as { k: Mode; label: string }[]).map((opt) => (
            <button
              key={opt.k}
              onClick={() => setMode(opt.k)}
              className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                mode === opt.k ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {mode === "single" && (
        <>
          <EntityCombobox
            entities={entities.data?.items ?? []}
            loading={entities.isLoading}
            value={entity}
            onChange={setEntity}
          />

          {!entity && (
            <EmptyState
              title="Выберите связку, чтобы увидеть динамику"
              hint={`Доступно ${entities.data?.count ?? "…"} связок с историей`}
            />
          )}

          {entity && history.isLoading && <Skeleton className="h-80 w-full" />}

          {entity && history.data && history.data.count === 0 && (
            <EmptyState title="Для этой связки пока только один прогон" hint="Динамика появится со следующим обновлением" />
          )}

          {entity && history.data && history.data.count > 0 && (
            <div className="space-y-4">
              <Card className="overflow-hidden">
                <h2 className="px-4 pt-4 text-sm font-bold text-[var(--color-text)] sm:px-6 sm:pt-6">
                  Прогоны по кварталам
                </h2>
                <div className="overflow-x-auto">
                  <table className="mt-2 w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--color-line)] bg-[var(--color-surface-soft)] text-left text-xs uppercase text-[var(--color-sub)]">
                        <th className="px-4 py-3">Дата прогона</th>
                        <th className="px-4 py-3">Зона</th>
                        <th className="px-4 py-3">Приоритет</th>
                        <th className="px-4 py-3">Балл</th>
                        <th className="px-4 py-3">Версия модели</th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {history.data.items.map((r, i) => (
                        <tr
                          key={i}
                          onClick={() => setOpenRun(r)}
                          className="group cursor-pointer border-b border-[var(--color-line)] last:border-0 hover:bg-[var(--color-surface-hover)]"
                        >
                          <td className="px-4 py-3">{fmtDate(r.run_published_at)}</td>
                          <td className="px-4 py-3"><ZoneBadge zone={r.zone} /></td>
                          <td className="px-4 py-3"><PriorityBadge priority={r.priority} compact /></td>
                          <td className="px-4 py-3 tabular-nums">{r.rating_score}</td>
                          <td className="px-4 py-3 text-[var(--color-sub)]">{r.model_version || "н/д"}</td>
                          <td className="px-4 py-3 text-right">
                            <span className="inline-flex items-center gap-1 rounded-lg border border-white/20 bg-white/10 px-2.5 py-1 text-xs font-bold text-white shadow-[0_2px_6px_rgba(0,0,0,0.4)] transition group-hover:bg-white/20">
                              Почему <span aria-hidden>→</span>
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {criteriaPivot.codes.length > 0 && (
                <Card className="overflow-hidden p-4 sm:p-6">
                  <h2 className="mb-1 text-sm font-bold text-[var(--color-text)]">
                    Разрез по критериям рейтинга
                  </h2>
                  <p className="mb-3 text-xs text-[var(--color-sub)]">
                    Какой именно критерий выполнялся (зелёное) или не выполнялся (красное) на
                    каждый прогон — видно, что именно изменилось.
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase text-[var(--color-sub)]">
                          <th className="py-2 pr-4">Критерий</th>
                          {criteriaPivot.quarters.map((q) => (
                            <th key={q} className="px-2 py-2 text-center">{fmtDate(q)}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {criteriaPivot.codes.map((code) => (
                          <tr key={code} className="border-b border-[var(--color-line)] last:border-0">
                            <td className="py-2 pr-4">{code}</td>
                            {criteriaPivot.quarters.map((q) => {
                              const met = criteriaPivot.grid.get(code)?.get(q)
                              return (
                                <td key={q} className="px-2 py-2 text-center">
                                  <span
                                    className={`inline-block h-3 w-3 rounded-full ${
                                      met === true ? "bg-[var(--color-zone-green)]" : met === false ? "bg-[var(--color-zone-red)]" : "bg-[var(--color-zone-nodata)]"
                                    }`}
                                    title={met === true ? "выполнен" : met === false ? "не выполнен" : "нет данных"}
                                  />
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

              <Card className="p-4 sm:p-6">
                <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Зона риска по кварталам</h2>
                <PlotlyChart data={zoneSeries} height={260} layout={{ yaxis: { tickvals: [0, 1, 2], ticktext: ["зелёная", "оранжевая", "красная"], range: [-0.5, 2.5] }, showlegend: false }} />
              </Card>
              <Card className="p-4 sm:p-6">
                <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Приоритет SIAR по кварталам</h2>
                <PlotlyChart data={prioritySeries} height={260} layout={{ yaxis: { tickvals: [1, 2, 3, 4], range: [0.5, 4.5], autorange: "reversed" }, showlegend: false }} />
              </Card>
              <Card className="p-4 sm:p-6">
                <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Балл рейтинга РУСАДА</h2>
                <PlotlyChart data={ratingSeries} height={220} layout={{ showlegend: false }} />
              </Card>
            </div>
          )}
        </>
      )}

      {mode === "compare" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
          <Card className="p-4">
            <p className="mb-2 text-xs font-bold uppercase text-[var(--color-sub)]">
              {kind === "osf" ? "Выберите виды спорта" : "Выберите регионы"}
            </p>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск…"
              className="mb-2 w-full rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-sub)]"
            />
            <div className="max-h-80 overflow-y-auto pr-1">
              {filteredEntities.map((e) => (
                <label key={e.entity_name} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--color-surface-hover)]">
                  <input
                    type="checkbox"
                    checked={compareSet.includes(e.entity_name)}
                    onChange={() => toggleCompare(e.entity_name)}
                  />
                  <span>{e.entity_name}</span>
                </label>
              ))}
            </div>
          </Card>

          <div className="space-y-4">
            {compareSet.length === 0 && (
              <EmptyState title="Отметьте 2 и более связки слева" hint="Сравнение появится в таблице и на графике" />
            )}
            {compareSet.length > 0 && compare.isLoading && <Skeleton className="h-80 w-full" />}

            {compareLatest.length > 0 && (
              <Card className="overflow-hidden">
                <h2 className="px-4 pt-4 text-sm font-bold text-[var(--color-text)] sm:px-6 sm:pt-6">
                  Сравнение — текущее состояние
                </h2>
                <div className="overflow-x-auto">
                  <table className="mt-2 w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--color-line)] bg-[var(--color-surface-soft)] text-left text-xs uppercase text-[var(--color-sub)]">
                        <th className="px-4 py-3">Связка</th>
                        <th className="px-4 py-3">Зона</th>
                        <th className="px-4 py-3">Приоритет</th>
                        <th className="px-4 py-3">Балл</th>
                        <th className="px-4 py-3">Обоснование</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compareLatest.map((row) => (
                        <tr key={row.entity_name} className="border-b border-[var(--color-line)] last:border-0">
                          <td className="px-4 py-3 font-medium text-[var(--color-text)]">
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                className="h-2 w-2 shrink-0 rounded-full"
                                style={{ background: COMPARE_COLORS[compareColorIndex(row.entity_name)] }}
                              />
                              {row.entity_name}
                            </span>
                          </td>
                          <td className="px-4 py-3"><ZoneBadge zone={row.zone} /></td>
                          <td className="px-4 py-3"><PriorityBadge priority={row.priority} compact /></td>
                          <td className="px-4 py-3 tabular-nums">{row.rating_score}</td>
                          <td className="px-4 py-3 text-[var(--color-sub)]">{row.justification}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {compareSet.length > 0 && compareSeries.length > 0 && (
              <Card className="p-4 sm:p-6">
                <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Приоритет во времени — сравнение</h2>
                <PlotlyChart
                  data={compareSeries}
                  height={360}
                  layout={{ yaxis: { tickvals: [1, 2, 3, 4], range: [0.5, 4.5], autorange: "reversed" } }}
                />
              </Card>
            )}
          </div>
        </div>
      )}

      {openRun && <HistoryRunCard row={openRun} onClose={() => setOpenRun(null)} />}
    </div>
  )
}
