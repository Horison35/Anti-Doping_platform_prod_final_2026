import { useState } from "react"
import { useDigest, useSnapshots, useUnmatched } from "../api/hooks"
import { Card, EmptyState, Skeleton } from "../components/ui/Primitives"

function fmt(iso: string | null): string {
  if (!iso) return "н/д"
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })
}

export default function Transparency() {
  const snapshots = useSnapshots(true)
  const digest = useDigest("both", true)
  const [unmatchedKind, setUnmatchedKind] = useState<"osf" | "region">("osf")
  const unmatched = useUnmatched(unmatchedKind, true)

  const latest = snapshots.data?.items[0]

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">
          Для внешней проверки
        </p>
        <h1 className="text-2xl font-extrabold text-[var(--color-text)]">О данных и воспроизводимости</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--color-sub)]">
          Эта страница закрывает вопрос «а откуда эта цифра?» — без похода в код и без обращения
          к разработчику. Ничего не скрыто: пробелы и несопоставленные записи показаны явно.
        </p>
      </div>

      {snapshots.isLoading && <Skeleton className="h-40" />}

      {latest && (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-bold text-[var(--color-text)]">Последний опубликованный прогон</h2>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-[var(--color-sub)]">Версия модели</dt>
              <dd className="font-semibold text-[var(--color-text)]">{latest.model_version || "н/д"}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-sub)]">Версия методики приоритизации</dt>
              <dd className="font-semibold text-[var(--color-text)]">{latest.rules_version || "н/д"}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-sub)]">Дата расчёта</dt>
              <dd className="font-semibold text-[var(--color-text)]">{fmt(latest.published_at)}</dd>
            </div>
          </dl>
          <p className="mt-4 rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] p-3 text-xs text-[var(--color-sub)]">
            Повторный расчёт на тех же входных файлах даёт побайтово идентичный результат — это
            проверяется автоматическими тестами на каждое изменение системы.
          </p>
        </Card>
      )}

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">История прогонов (снапшоты)</h2>
        {snapshots.data?.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase text-[var(--color-sub)]">
                  <th className="py-2 pr-4">Дата</th>
                  <th className="py-2 pr-4">Версия модели</th>
                  <th className="py-2 pr-4">ОСФ</th>
                  <th className="py-2 pr-4">Регионов</th>
                  <th className="py-2 pr-4">Входных файлов</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.data.items.slice(0, 10).map((s) => (
                  <tr key={s.run_id} className="border-b border-[var(--color-line)] last:border-0">
                    <td className="py-2 pr-4">{fmt(s.published_at)}</td>
                    <td className="py-2 pr-4 text-[var(--color-sub)]">{s.model_version || "—"}</td>
                    <td className="py-2 pr-4">{s.n_osf}</td>
                    <td className="py-2 pr-4">{s.n_regions}</td>
                    <td className="py-2 pr-4">{s.n_inputs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Прогонов пока нет" />
        )}
      </Card>

      <Card className="p-5">
        <h2 className="mb-1 text-sm font-bold text-[var(--color-text)]">Честная подача пробелов АД-Монитора</h2>
        <p className="mb-3 text-xs text-[var(--color-sub)]">Статус мониторинга за последний выпуск.</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Не подтверждено" value={digest.data?.unverified_count ?? "…"} />
          <Stat label="Источник недоступен" value={digest.data?.source_unavailable_count ?? "…"} />
          <Stat label="Выпусков в архиве" value={digest.data?.timeline?.length ?? "…"} />
        </div>
      </Card>

      <Card className="p-5">
        <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-bold text-[var(--color-text)]">Не сопоставлено</h2>
            <p className="text-xs text-[var(--color-sub)]">
              Связки модели и рейтинга РУСАДА, которые не удалось сопоставить друг с другом.
              Ни одна из них не отбрасывается при расчёте — весь список ниже, с причиной по каждой.
            </p>
          </div>
          <div className="flex rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1 sm:w-fit">
            {(["osf", "region"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setUnmatchedKind(k)}
                className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                  unmatchedKind === k ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)]"
                }`}
              >
                {k === "osf" ? "ОСФ" : "Регионы"}
              </button>
            ))}
          </div>
        </div>
        {unmatched.isLoading ? (
          <Skeleton className="h-24" />
        ) : unmatched.data?.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase text-[var(--color-sub)]">
                  <th className="py-2 pr-4">Сторона</th>
                  <th className="py-2 pr-4">Название</th>
                  <th className="py-2 pr-4">Причина</th>
                </tr>
              </thead>
              <tbody>
                {unmatched.data.items.map((r) => (
                  <tr key={r.unmatched_id} className="border-b border-[var(--color-line)] last:border-0">
                    <td className="py-2 pr-4 text-[var(--color-sub)]">
                      {r.side === "model" ? "модель" : "рейтинг"}
                    </td>
                    <td className="py-2 pr-4 font-medium text-[var(--color-text)]">{r.name}</td>
                    <td className="py-2 pr-4 text-[var(--color-sub)]">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Всё сопоставлено" hint="Несопоставленных записей в текущем прогоне нет" />
        )}
      </Card>

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Архитектурный принцип</h2>
        <p className="text-sm leading-relaxed text-[var(--color-text)]/90">
          Модель ранжирует вероятность нарушения. Код детерминированно решает зону риска,
          приоритет и формулирует обоснование по утверждённым правилам. Искусственный интеллект
          используется только в АД-Мониторе — для сбора и краткого пересказа новостей. Ни одно
          число и ни одно обоснование приоритета или зоны риска не порождается ИИ — этот принцип
          не имеет исключений ни в одном модуле системы.
        </p>
      </Card>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] p-3 text-center">
      <div className="text-xl font-extrabold text-[var(--color-text)]">{value}</div>
      <div className="text-xs text-[var(--color-sub)]">{label}</div>
    </div>
  )
}
