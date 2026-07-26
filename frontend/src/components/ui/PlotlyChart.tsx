import { useEffect, useRef } from "react"
import type { Config, Data, Layout, PlotMouseEvent } from "plotly.js"

// Plotly загружается с CDN через <script> в index.html (правило проекта:
// не вшивать 4 МБ библиотеки в бандл — STRUCTURE.md, п. 5). Здесь только
// тонкая обёртка над глобальным window.Plotly.

type PlotlyLike = {
  react: (el: HTMLElement, data: Data[], layout?: Partial<Layout>, config?: Partial<Config>) => Promise<unknown>
  purge: (el: HTMLElement) => void
}

declare global {
  interface Window {
    Plotly?: PlotlyLike & {
      newPlot: PlotlyLike["react"]
    }
  }
}

interface PlotlyDiv extends HTMLDivElement {
  on: (event: "plotly_click", handler: (e: PlotMouseEvent) => void) => void
  removeAllListeners?: (event: string) => void
}

// Тёмная стеклянная тема графиков: холст прозрачный (карточка-стекло видна
// сквозь него), сетка и подписи — приглушённый светлый тон, читаемый на тёмном
// фоне. Цвета самих данных (зоны/приоритеты) остаются из siar/rules.py —
// здесь меняется только окружение графика, не значения.
const BASE_FONT = { family: "Inter, Segoe UI, Roboto, Arial, sans-serif", color: "#c7d0e0", size: 12 }
const AXIS_DEFAULTS = {
  automargin: true,
  gridcolor: "rgba(255,255,255,0.08)",
  zerolinecolor: "rgba(255,255,255,0.16)",
  linecolor: "rgba(255,255,255,0.14)",
  tickfont: { color: "#8b96ab" },
}

export function PlotlyChart({
  data,
  layout,
  height = 360,
  config,
  onPointClick,
}: {
  data: Data[]
  layout?: Partial<Layout>
  height?: number
  config?: Partial<Config>
  onPointClick?: (customdata: unknown) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current || !window.Plotly) return
    const merged: Partial<Layout> = {
      autosize: true,
      height,
      margin: { l: 8, r: 8, t: layout?.title ? 40 : 8, b: 8 },
      font: BASE_FONT,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      showlegend: true,
      legend: { orientation: "h", y: -0.15, font: { color: "#8b96ab" } },
      colorway: ["#3b82f6", "#f59e0b", "#dc2626", "#10b981", "#94a3b8", "#6a34e0"],
      // Тёмная подсказка при наведении — иначе Plotly рисует свою белую по
      // умолчанию, и она одна на всей платформе выбивается из стеклянной темы.
      hoverlabel: { bgcolor: "#0b1220", bordercolor: "rgba(255,255,255,0.18)", font: { color: "#e7edf7", size: 12 } },
      ...layout,
      // Фиксированный margin выше — только запасной минимум. Без automargin Plotly
      // рисует подписи тиков/заголовок без учёта реальной ширины текста, и длинные
      // подписи (числа, повёрнутый заголовок оси, категории) обрезаются до
      // последнего символа вместо того, чтобы раздвинуть поле графика.
      xaxis: { ...AXIS_DEFAULTS, ...layout?.xaxis },
      yaxis: { ...AXIS_DEFAULTS, ...layout?.yaxis },
    }
    window.Plotly.react(ref.current, data, merged, {
      displayModeBar: false,
      responsive: true,
      ...config,
    })

    const el = ref.current as PlotlyDiv
    if (onPointClick && el.on) {
      el.on("plotly_click", (e: PlotMouseEvent) => {
        const point = e.points?.[0]
        if (point) onPointClick(point.customdata)
      })
    }
  }, [data, layout, height, config, onPointClick])

  useEffect(() => {
    const el = ref.current
    return () => {
      if (el && window.Plotly) window.Plotly.purge(el)
    }
  }, [])

  return <div ref={ref} className="w-full" style={{ height }} />
}
