import { useState } from "react"
import { useNavigate } from "react-router-dom"
import type { Data } from "plotly.js"
import { useOsfDetail, useOsfSummary, useRegionDetail, useRegionsSummary } from "../api/hooks"
import { Button, Card, CountUp, EmptyState, Skeleton } from "../components/ui/Primitives"
import { ZoneBadge } from "../components/ui/Badge"
import { PlotlyChart } from "../components/ui/PlotlyChart"
import { DrillDownCard } from "../components/domain/DrillDownCard"
import type { PriorityTop5Row, SummaryResponse } from "../api/types"

const PRIORITY_META = [
  { key: "1", label: "Приоритет 1", hint: "требует немедленного внимания", color: "var(--color-p1)", trend: "up" as const },
  { key: "2", label: "Приоритет 2", hint: "риск есть, работа ведётся", color: "var(--color-p2)", trend: "up" as const },
  { key: "3", label: "Приоритет 3", hint: "потенциальный риск", color: "var(--color-p3)", trend: "up" as const },
  { key: "4", label: "Приоритет 4", hint: "всё в порядке", color: "var(--color-p4)", trend: "down" as const },
]

// Крупный значок «уровня внимания» в углу карточки — визуально показывает,
// куда смотреть: вверх — категория требует внимания, вниз — категория
// спокойная. Направление зафиксировано смыслом самой категории приоритета
// (см. PRIORITY_META), а не сравнением с прошлым прогоном — на карточке
// сознательно нет текста про «первый прогон»/сравнения: только число,
// стрелка, приоритет и подпись под ним (ТЗ).
function TrendBadge({ trend, color, delay }: { trend: "up" | "down"; color: string; delay: string }) {
  const up = trend === "up"
  return (
    <div
      className="trend-pop absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full"
      style={{
        background: `color-mix(in srgb, ${color} 22%, transparent)`,
        boxShadow: `0 0 16px color-mix(in srgb, ${color} 55%, transparent)`,
        color,
        animationDelay: delay,
      }}
      title={up ? "Категория требует внимания" : "Категория спокойная"}
    >
      <svg width="16" height="16" viewBox="0 0 12 12" className={up ? "" : "rotate-180"} aria-hidden>
        <path d="M6 1 L11 10 L1 10 Z" fill="currentColor" />
      </svg>
    </div>
  )
}

// Тот же расклад по приоритетам, что и в 4 карточках выше, просто ещё и
// формой — доля с одного взгляда, без пересчёта чисел в уме. Данные и цвета
// строго те же (PRIORITY_META), донат ничего не считает заново.
function PriorityDonut({ summary }: { summary: SummaryResponse }) {
  const total = PRIORITY_META.reduce((sum, p) => sum + (summary.current?.[p.key] ?? 0), 0)
  const data: Data[] = [
    {
      type: "pie",
      hole: 0.64,
      labels: PRIORITY_META.map((p) => p.label),
      values: PRIORITY_META.map((p) => summary.current?.[p.key] ?? 0),
      marker: { colors: PRIORITY_META.map((p) => p.color), line: { color: "#0b1220", width: 2 } },
      textinfo: "none",
      hovertemplate: "%{label}: %{value}<extra></extra>",
    },
  ]
  return (
    <PlotlyChart
      data={data}
      height={168}
      layout={{
        showlegend: false,
        margin: { l: 4, r: 4, t: 4, b: 4 },
        annotations: [
          {
            text: `${total}`,
            showarrow: false,
            font: { size: 26, color: "#e7edf7" },
            x: 0.5,
            y: 0.54,
          },
          {
            text: "связок",
            showarrow: false,
            font: { size: 11, color: "#8b96ab" },
            x: 0.5,
            y: 0.38,
          },
        ],
      }}
    />
  )
}

function SummaryBlock({
  title,
  summary,
  isLoading,
  onOpen,
}: {
  title: string
  summary: SummaryResponse | undefined
  isLoading: boolean
  onOpen: (name: string) => void
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    )
  }
  if (!summary?.available) {
    return <EmptyState title="Прогонов пока нет" hint="Данные появятся после первого опубликованного прогона" />
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-bold text-[var(--color-text)]">{title}</h2>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_180px]">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {PRIORITY_META.map((p, i) => (
            <Card key={p.key} index={i} className="relative p-4">
              <TrendBadge trend={p.trend} color={p.color} delay={`${i * 70 + 260}ms`} />
              <div
                className="text-3xl font-extrabold tabular-nums"
                style={{ color: p.color, textShadow: `0 0 22px color-mix(in srgb, ${p.color} 40%, transparent)` }}
              >
                <CountUp target={summary.current?.[p.key] ?? 0} delayMs={i * 70 + 150} />
              </div>
              <div className="mt-1 text-xs font-semibold text-[var(--color-text)]">{p.label}</div>
              <div className="text-[11px] text-[var(--color-sub)]">{p.hint}</div>
            </Card>
          ))}
        </div>
        <Card index={4} className="flex items-center justify-center p-2">
          <PriorityDonut summary={summary} />
        </Card>
      </div>

      {!!summary.top5_priority1?.length && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-bold text-[var(--color-sub)]">Топ-5 приоритета 1</h3>
          <div className="space-y-2">
            {summary.top5_priority1.map((row: PriorityTop5Row, i) => (
              <button
                key={row.entity_name}
                onClick={() => onOpen(row.entity_name)}
                style={{ animationDelay: `${320 + i * 60}ms` }}
                className="glass rise-in flex w-full items-center justify-between gap-3 !rounded-xl px-4 py-3 text-left hover:bg-[var(--color-surface-hover)]"
              >
                <span className="font-medium text-[var(--color-text)]">
                  {row.entity_name}
                  {row.fo && <span className="ml-2 text-xs text-[var(--color-sub)]">{row.fo}</span>}
                </span>
                <ZoneBadge zone={row.zone} />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Overview() {
  const navigate = useNavigate()
  const osfSummary = useOsfSummary(true)
  const regionsSummary = useRegionsSummary(true)
  const [openEntity, setOpenEntity] = useState<{ kind: "osf" | "region"; name: string } | null>(null)

  const osfDetail = useOsfDetail(openEntity?.kind === "osf" ? openEntity.name : null)
  const regionDetail = useRegionDetail(openEntity?.kind === "region" ? openEntity.name : null)

  return (
    <div className="space-y-10">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
          Обзор · за 30 секунд
        </p>
        <h1 className="mt-1 text-2xl font-extrabold text-[var(--color-text)] sm:text-3xl">
          Состояние антидопинговой повестки
        </h1>
      </div>

      <SummaryBlock
        title="Общероссийские спортивные федерации"
        summary={osfSummary.data}
        isLoading={osfSummary.isLoading}
        onOpen={(name) => setOpenEntity({ kind: "osf", name })}
      />

      <SummaryBlock
        title="Субъекты РФ"
        summary={regionsSummary.data}
        isLoading={regionsSummary.isLoading}
        onOpen={(name) => setOpenEntity({ kind: "region", name })}
      />

      <div className="flex justify-center pt-2">
        <Button variant="outline" onClick={() => navigate("/analytics")}>
          Перейти к полному анализу →
        </Button>
      </div>

      {openEntity && (
        <DrillDownCard
          kind={openEntity.kind}
          detail={openEntity.kind === "osf" ? osfDetail.data : regionDetail.data}
          loading={openEntity.kind === "osf" ? osfDetail.isLoading : regionDetail.isLoading}
          onClose={() => setOpenEntity(null)}
        />
      )}
    </div>
  )
}
