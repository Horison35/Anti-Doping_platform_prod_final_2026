import { useMemo } from "react"
import type { Data } from "plotly.js"
import type { QuadrantRow } from "../../api/types"
import { PlotlyChart } from "../ui/PlotlyChart"

const PRIORITY_COLOR: Record<number, string> = { 1: "#DC2626", 2: "#F59E0B", 3: "#3B82F6", 4: "#10B981" }
const PRIORITY_NAME: Record<number, string> = {
  1: "Приоритет 1",
  2: "Приоритет 2",
  3: "Приоритет 3",
  4: "Приоритет 4",
}

export function QuadrantScatter({
  rows,
  threshold,
  onSelect,
}: {
  rows: QuadrantRow[]
  threshold: number
  onSelect: (entityName: string) => void
}) {
  // Границы заливки квадрантов считаем по реальным данным (не произвольной
  // «большой цифрой» вроде ±1000) — иначе Plotly включает координаты фигур
  // в автомасштаб оси X, и вместо 0–100 (ОСФ) или 0–190 (регионы) ось
  // растягивается на весь диапазон значений shapes.
  const xMin = useMemo(() => Math.min(0, ...rows.map((r) => r.rating_score)) - 5, [rows])
  const xMax = useMemo(() => Math.max(100, threshold, ...rows.map((r) => r.rating_score)) + 5, [rows, threshold])

  const data = useMemo<Data[]>(() => {
    const byPriority: Record<number, QuadrantRow[]> = { 1: [], 2: [], 3: [], 4: [] }
    for (const r of rows) byPriority[r.priority]?.push(r)

    // Ось Y — risk_index (перцентиль, 0–100), не сырая proba (LOGIC.md §4:
    // «сырую proba показывать только аналитику по клику» — раскрыта в
    // карточке «почему именно так», не на общем графике для всех).
    return Object.entries(byPriority).map(([p, group]) => ({
      x: group.map((r) => r.rating_score),
      y: group.map((r) => r.risk_index ?? -2),
      text: group.map((r) => r.entity_name),
      customdata: group.map((r) => r.entity_name),
      name: PRIORITY_NAME[Number(p)],
      mode: "markers",
      type: "scatter",
      marker: { color: PRIORITY_COLOR[Number(p)], size: 11, opacity: 0.85, line: { width: 1, color: "white" } },
      hovertemplate: "<b>%{text}</b><br>Рейтинг: %{x}<br>Индекс риска: %{y}/100<extra></extra>",
    }))
  }, [rows])

  return (
    <PlotlyChart
      data={data}
      height={420}
      layout={{
        // Фиксированный margin.l у PlotlyChart (8px) слишком мал для повёрнутого
        // заголовка оси Y — без явного зазора Plotly рисует подписи тиков поверх
        // заголовка (виден только последний символ числа). Явный margin + standoff
        // разводят заголовок и подписи тиков по разным колонкам.
        margin: { l: 64, r: 8, t: 8, b: 44 },
        shapes: [
          // Лёгкая заливка 4 квадрантов — не новое правило, а продолжение уже
          // показанных цветов маркеров (P1-P4) на фон: слева/справа граница —
          // реальный порог rating_high (threshold, тот же, что красит вертикальную
          // линию); сверху/снизу — медиана risk_index (по определению самого
          // индекса 50-й перцентиль, а не изобретённая граница зоны).
          { type: "rect", x0: xMin, x1: threshold, y0: 50, y1: 105, fillcolor: "rgba(220,38,38,0.05)", line: { width: 0 } },
          { type: "rect", x0: threshold, x1: xMax, y0: 50, y1: 105, fillcolor: "rgba(245,158,11,0.05)", line: { width: 0 } },
          { type: "rect", x0: xMin, x1: threshold, y0: -5, y1: 50, fillcolor: "rgba(59,130,246,0.05)", line: { width: 0 } },
          { type: "rect", x0: threshold, x1: xMax, y0: -5, y1: 50, fillcolor: "rgba(16,185,129,0.05)", line: { width: 0 } },
          {
            type: "line",
            x0: threshold,
            x1: threshold,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: "rgba(255,255,255,0.28)", dash: "dot", width: 1.5 },
          },
          {
            type: "line",
            x0: 0,
            x1: 1,
            xref: "paper",
            y0: 50,
            y1: 50,
            line: { color: "rgba(255,255,255,0.28)", dash: "dot", width: 1.5 },
          },
        ],
        xaxis: { title: { text: "Балл рейтинга РУСАДА", standoff: 8 }, range: [xMin, xMax] },
        yaxis: { title: { text: "Индекс риска (0–100)", standoff: 16 }, range: [-5, 105] },
      }}
      onPointClick={(customdata) => {
        if (typeof customdata === "string") onSelect(customdata)
      }}
    />
  )
}
