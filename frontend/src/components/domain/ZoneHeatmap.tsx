import { useMemo } from "react"
import type { Data } from "plotly.js"
import type { GridCell } from "../../api/types"
import { PlotlyChart } from "../ui/PlotlyChart"

const ZONE_VALUE: Record<string, number> = { GREEN: 0, ORANGE: 1, RED: 2 }

// Heatmap «вид спорта × регион» (STRUCTURE.md, frontend): топ-N по обеим осям
// с наихудшей зоной, чтобы полотно оставалось читаемым, а не 226×85 клеток.
export function ZoneHeatmap({ cells, topN = 18 }: { cells: GridCell[]; topN?: number }) {
  const { sports, regions, z, text } = useMemo(() => {
    const worstBySport = new Map<string, number>()
    const worstByRegion = new Map<string, number>()
    for (const c of cells) {
      const v = ZONE_VALUE[c.zone] ?? -1
      worstBySport.set(c.sport, Math.max(worstBySport.get(c.sport) ?? -1, v))
      worstByRegion.set(c.region, Math.max(worstByRegion.get(c.region) ?? -1, v))
    }
    const topSports = [...worstBySport.entries()].sort((a, b) => b[1] - a[1]).slice(0, topN).map(([s]) => s)
    const topRegions = [...worstByRegion.entries()].sort((a, b) => b[1] - a[1]).slice(0, topN).map(([r]) => r)

    const cellMap = new Map<string, GridCell>()
    for (const c of cells) cellMap.set(`${c.sport}|||${c.region}`, c)

    const z: number[][] = topSports.map((s) =>
      topRegions.map((r) => ZONE_VALUE[cellMap.get(`${s}|||${r}`)?.zone ?? ""] ?? null),
    )
    // Сырую proba сюда не выводим (LOGIC.md §4: только по клику, в карточке
    // «почему именно так») — только зона и причина, тем же языком, что и везде.
    const text: string[][] = topSports.map((s) =>
      topRegions.map((r) => {
        const cell = cellMap.get(`${s}|||${r}`)
        if (!cell) return ""
        return `${s} × ${r}\n${cell.zone}${cell.reason ? ` · ${cell.reason}` : ""}`
      }),
    )
    return { sports: topSports, regions: topRegions, z, text }
  }, [cells, topN])

  const data: Data[] = [
    {
      type: "heatmap",
      x: regions,
      y: sports,
      z,
      text,
      hovertemplate: "%{text}<extra></extra>",
      // «Низкий риск» намеренно почти сливается с фоном карточки — внимание не должно
      // тратиться на большинство спокойных клеток. Яркость приберегли только для
      // повышенного/высокого риска, как и всюду в интерфейсе (те же оттенки, что в бейджах).
      colorscale: [
        [0, "#131b28"],
        [0.5, "#c17a1a"],
        [1, "#dc2626"],
      ],
      zmin: 0,
      zmax: 2,
      showscale: false,
      xgap: 3,
      ygap: 3,
    } as unknown as Data,
  ]

  return (
    <div>
      <PlotlyChart
        data={data}
        height={Math.max(360, sports.length * 28)}
        layout={{ xaxis: { tickangle: -40 }, margin: { l: 170, r: 8, t: 8, b: 100 } }}
      />
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-[var(--color-sub)]">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#131b28", border: "1px solid var(--color-line)" }} /> низкий риск</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#c17a1a" }} /> повышенный риск</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#dc2626" }} /> высокий риск</span>
      </div>
    </div>
  )
}
