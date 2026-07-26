import { useMemo, useState } from "react"
import type { QuadrantRow } from "../../api/types"
import { PriorityBadge, ZoneBadge } from "../ui/Badge"
import { TopNSelector } from "../ui/Primitives"

export function EntityTable({
  rows,
  total,
  onSelect,
  kind,
}: {
  rows: QuadrantRow[]
  total: number
  onSelect: (entityName: string) => void
  kind: "osf" | "region"
}) {
  const [topN, setTopN] = useState<number | "all">(20)

  const visible = useMemo(() => (topN === "all" ? rows : rows.slice(0, topN)), [rows, topN])

  return (
    <div>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <p className="text-sm text-[var(--color-sub)]">
          Показано {visible.length} из {total}
        </p>
        <TopNSelector value={topN} onChange={setTopN} total={total} />
      </div>

      {/* Мобайл: карточки. Десктоп: таблица. Одни и те же данные. */}
      <div className="space-y-2 sm:hidden">
        {visible.map((r) => (
          <button
            key={r.result_id}
            onClick={() => onSelect(r.entity_name)}
            className="block w-full rounded-2xl border border-[var(--color-line)] bg-[var(--color-surface)] p-4 text-left active:bg-[var(--color-surface-hover)]"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-semibold text-[var(--color-text)]">{r.entity_name}</span>
              <PriorityBadge priority={r.priority} compact />
            </div>
            <div className="mt-2 flex items-center gap-2">
              <ZoneBadge zone={r.zone} />
              <span className="text-xs text-[var(--color-sub)]">Рейтинг: {r.rating_score}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="hidden overflow-x-auto rounded-2xl border border-[var(--color-line)] sm:block">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-[var(--color-line)] bg-[var(--color-surface-soft)] text-left text-xs uppercase tracking-wide text-[var(--color-sub)]">
              <th className="px-4 py-3 font-semibold">№</th>
              <th className="px-4 py-3 font-semibold">{kind === "osf" ? "Вид спорта" : "Регион"}</th>
              <th className="px-4 py-3 font-semibold">Зона</th>
              <th className="px-4 py-3 font-semibold">Приоритет</th>
              <th className="px-4 py-3 font-semibold">Рейтинг РУСАДА</th>
              <th className="px-4 py-3 font-semibold" />
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr
                key={r.result_id}
                onClick={() => onSelect(r.entity_name)}
                className="group cursor-pointer border-b border-[var(--color-line)] last:border-0 hover:bg-[var(--color-surface-hover)]"
              >
                <td className="px-4 py-3 text-[var(--color-sub)]">{r.risk_rank ?? i + 1}</td>
                <td className="px-4 py-3 font-medium text-[var(--color-text)]">
                  {r.entity_name}
                  {r.fo && <span className="ml-2 text-xs text-[var(--color-sub)]">{r.fo}</span>}
                </td>
                <td className="px-4 py-3">
                  <ZoneBadge zone={r.zone} />
                </td>
                <td className="px-4 py-3">
                  <PriorityBadge priority={r.priority} compact />
                </td>
                <td className="px-4 py-3 tabular-nums text-[var(--color-text)]">{r.rating_score}</td>
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
    </div>
  )
}
