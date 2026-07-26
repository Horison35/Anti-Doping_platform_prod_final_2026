import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  useFoSummary,
  useGrid,
  useOsfDetail,
  useOsfList,
  useRegionDetail,
  useRegionsList,
} from "../api/hooks"
import { Card, EmptyState, ErrorState, Skeleton } from "../components/ui/Primitives"
import { EntityTable } from "../components/domain/EntityTable"
import { QuadrantScatter } from "../components/domain/QuadrantScatter"
import { ZoneHeatmap } from "../components/domain/ZoneHeatmap"
import { DrillDownCard } from "../components/domain/DrillDownCard"
import { ApiError } from "../api/client"

type Tab = "osf" | "region"
const ZONES = ["RED", "ORANGE", "GREEN", "NO_DATA"] as const
const PRIORITIES = [1, 2, 3, 4] as const

export default function Analytics() {
  // Прямая ссылка на конкретную связку (ТЗ, сценарий внешнего эксперта):
  // ?kind=osf&entity=... — можно скопировать и отправить, откроет ту же карточку.
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTabState] = useState<Tab>(
    searchParams.get("kind") === "region" ? "region" : "osf",
  )
  const [zone, setZone] = useState<string | undefined>()
  const [priority, setPriority] = useState<number | undefined>()
  const [fo, setFo] = useState<string | undefined>()
  const [openEntity, setOpenEntityState] = useState<string | null>(searchParams.get("entity"))
  const [showHeatmap, setShowHeatmap] = useState(false)

  function setOpenEntity(name: string | null) {
    setOpenEntityState(name)
    const next = new URLSearchParams(searchParams)
    next.set("kind", tab)
    if (name) next.set("entity", name)
    else next.delete("entity")
    setSearchParams(next, { replace: true })
  }

  function setTab(next: Tab) {
    setTabState(next)
    setOpenEntityState(null)
    const params = new URLSearchParams(searchParams)
    params.set("kind", next)
    params.delete("entity")
    setSearchParams(params, { replace: true })
  }

  const osfList = useOsfList({ zone, priority }, tab === "osf")
  const regionsList = useRegionsList({ zone, priority, fo }, tab === "region")
  const foSummary = useFoSummary(tab === "region")
  const grid = useGrid(showHeatmap)

  const osfDetail = useOsfDetail(tab === "osf" ? openEntity : null)
  const regionDetail = useRegionDetail(tab === "region" ? openEntity : null)

  const list = tab === "osf" ? osfList : regionsList
  const rows = useMemo(() => list.data?.items ?? [], [list.data])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
            Приоритеты SIAR
          </p>
          <h1 className="text-2xl font-extrabold text-[var(--color-text)]">Аналитика по связкам</h1>
        </div>
        <div className="flex rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1">
          {(["osf", "region"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t)
                setZone(undefined)
                setPriority(undefined)
                setFo(undefined)
              }}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                tab === t ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)]"
              }`}
            >
              {t === "osf" ? "ОСФ" : "Регионы"}
            </button>
          ))}
        </div>
      </div>

      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChip label="Все зоны" active={!zone} onClick={() => setZone(undefined)} />
        {ZONES.map((z) => (
          <FilterChip key={z} label={z} active={zone === z} onClick={() => setZone(z)} />
        ))}
        <span className="mx-1 h-5 w-px bg-[var(--color-line)]" />
        <FilterChip label="Все приоритеты" active={!priority} onClick={() => setPriority(undefined)} />
        {PRIORITIES.map((p) => (
          <FilterChip key={p} label={`П${p}`} active={priority === p} onClick={() => setPriority(p)} />
        ))}
        {tab === "region" && foSummary.data && (
          <>
            <span className="mx-1 h-5 w-px bg-[var(--color-line)]" />
            <FilterChip label="Все округа" active={!fo} onClick={() => setFo(undefined)} />
            {foSummary.data.items.map((f) => (
              <FilterChip key={f.fo} label={f.fo} active={fo === f.fo} onClick={() => setFo(f.fo)} />
            ))}
          </>
        )}
      </div>

      {list.isLoading && <Skeleton className="h-96 w-full" />}
      {list.isError && <ErrorState message={(list.error as ApiError)?.message || "ошибка"} />}

      {list.data && rows.length === 0 && (
        <EmptyState title="Нет записей по выбранным фильтрам" hint="Попробуйте снять часть фильтров" />
      )}

      {list.data && rows.length > 0 && (
        <>
          <Card className="p-4 sm:p-6">
            <h2 className="mb-3 text-sm font-bold text-[var(--color-text)]">Таблица связок</h2>
            <EntityTable rows={rows} total={list.data.total} kind={tab} onSelect={setOpenEntity} />
          </Card>

          <Card className="p-4 sm:p-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold text-[var(--color-text)]">Матрица риск × рейтинг</h2>
              <p className="text-xs text-[var(--color-sub)]">клик по точке — карточка обоснования</p>
            </div>
            <QuadrantScatter
              rows={rows}
              threshold={tab === "osf" ? 80 : 130}
              onSelect={(name) => setOpenEntity(name)}
            />
          </Card>

          <Card className="p-4 sm:p-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold text-[var(--color-text)]">
                Тепловая карта: вид спорта × регион
              </h2>
              <button
                onClick={() => setShowHeatmap((v) => !v)}
                className="text-xs font-semibold text-[var(--color-text)] underline underline-offset-2"
              >
                {showHeatmap ? "скрыть" : "показать"}
              </button>
            </div>
            {showHeatmap && (grid.data ? <ZoneHeatmap cells={grid.data.items} /> : <Skeleton className="h-96" />)}
          </Card>
        </>
      )}

      {openEntity && (
        <DrillDownCard
          kind={tab}
          detail={tab === "osf" ? osfDetail.data : regionDetail.data}
          loading={tab === "osf" ? osfDetail.isLoading : regionDetail.isLoading}
          onClose={() => setOpenEntity(null)}
        />
      )}
    </div>
  )
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white shadow-[0_0_16px_-4px_rgba(59,130,246,0.6)]"
          : "border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-sub)] hover:border-[var(--color-accent)]/40 hover:text-[var(--color-text)]"
      }`}
    >
      {label}
    </button>
  )
}
