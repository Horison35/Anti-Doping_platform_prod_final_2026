import { Card } from "../components/ui/Primitives"

interface ExportItem {
  title: string
  hint: string
  base: string
  params?: string
}

const SECTIONS: { title: string; items: ExportItem[] }[] = [
  {
    title: "Приоритеты",
    items: [
      { title: "Приоритеты ОСФ", hint: "142 федерации, текущий прогон", base: "/api/v1/export/osf" },
      { title: "Приоритеты регионов", hint: "89 субъектов РФ, текущий прогон", base: "/api/v1/export/regions" },
    ],
  },
  {
    title: "Не сопоставлено",
    items: [
      { title: "Не сопоставлено — ОСФ", hint: "модель ↔ рейтинг РУСАДА", base: "/api/v1/export/unmatched", params: "kind=osf" },
      { title: "Не сопоставлено — регионы", hint: "модель ↔ рейтинг регионов", base: "/api/v1/export/unmatched", params: "kind=region" },
    ],
  },
  {
    title: "Сопоставление названий",
    items: [
      { title: "Сопоставление названий — ОСФ", hint: "как связали название с рейтингом, насколько точно", base: "/api/v1/export/audit", params: "kind=osf" },
      { title: "Сопоставление названий — регионы", hint: "как связали название с рейтингом, насколько точно", base: "/api/v1/export/audit", params: "kind=region" },
    ],
  },
  {
    title: "История",
    items: [
      { title: "История — ОСФ", hint: "все опубликованные прогоны", base: "/api/v1/export/history", params: "kind=osf" },
      { title: "История — регионы", hint: "все опубликованные прогоны", base: "/api/v1/export/history", params: "kind=region" },
    ],
  },
]

export default function Exports() {
  return (
    <div className="space-y-8">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
          Без интерактивных экранов
        </p>
        <h1 className="text-2xl font-extrabold text-[var(--color-text)]">Выгрузка данных</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--color-sub)]">
          Полные таблицы — без предварительной фильтрации. Данные полностью совпадают с тем,
          что показано в интерактивных разделах платформы.
        </p>
      </div>

      {SECTIONS.map((section) => (
        <div key={section.title}>
          <h2 className="mb-3 text-sm font-bold text-[var(--color-text)]">{section.title}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {section.items.map((item) => (
              <Card key={item.title} className="flex items-center justify-between p-4">
                <div>
                  <div className="font-semibold text-[var(--color-text)]">{item.title}</div>
                  <div className="text-xs text-[var(--color-sub)]">{item.hint}</div>
                </div>
                <div className="flex gap-2">
                  <a
                    href={`${item.base}.xlsx${item.params ? `?${item.params}` : ""}`}
                    className="rounded-lg border border-[var(--color-line)] px-3 py-2 text-xs font-semibold text-[var(--color-text)] hover:bg-[var(--color-surface-hover)] hover:border-[var(--color-accent)]/40"
                  >
                    Excel
                  </a>
                  <a
                    href={`${item.base}.csv${item.params ? `?${item.params}` : ""}`}
                    className="rounded-lg border border-[var(--color-line)] px-3 py-2 text-xs font-semibold text-[var(--color-text)] hover:bg-[var(--color-surface-hover)] hover:border-[var(--color-accent)]/40"
                  >
                    CSV
                  </a>
                </div>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
