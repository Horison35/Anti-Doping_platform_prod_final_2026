import type { Priority, Zone } from "../../api/types"

// Единая визуальная иерархия: цвет зоны/приоритета считывается мгновенно
// (ТЗ: «4 уровня из документа считываются моментально по цвету»).

const ZONE_LABEL: Record<Zone, string> = {
  RED: "Высокий риск",
  ORANGE: "Повышенный риск",
  GREEN: "Низкий риск",
  NO_DATA: "Нет данных",
}

const ZONE_COLOR: Record<Zone, string> = {
  RED: "var(--color-zone-red)",
  ORANGE: "var(--color-zone-orange)",
  GREEN: "var(--color-zone-green)",
  NO_DATA: "var(--color-zone-nodata)",
}

export function ZoneBadge({ zone }: { zone: Zone }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-white"
      style={{ background: ZONE_COLOR[zone], boxShadow: `0 0 16px -2px color-mix(in srgb, ${ZONE_COLOR[zone]} 55%, transparent)` }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-white/80" />
      {ZONE_LABEL[zone]}
    </span>
  )
}

const PRIORITY_COLOR: Record<Priority, string> = {
  1: "var(--color-p1)",
  2: "var(--color-p2)",
  3: "var(--color-p3)",
  4: "var(--color-p4)",
}

const PRIORITY_LABEL: Record<Priority, string> = {
  1: "Приоритет 1",
  2: "Приоритет 2",
  3: "Приоритет 3 · потенциальный риск",
  4: "Приоритет 4",
}

export function PriorityBadge({ priority, compact }: { priority: Priority; compact?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-bold text-white"
      style={{ background: PRIORITY_COLOR[priority], boxShadow: `0 0 16px -2px color-mix(in srgb, ${PRIORITY_COLOR[priority]} 55%, transparent)` }}
    >
      {compact ? `П${priority}` : PRIORITY_LABEL[priority]}
    </span>
  )
}
