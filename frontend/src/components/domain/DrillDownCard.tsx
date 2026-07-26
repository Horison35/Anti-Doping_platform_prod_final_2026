import { useMemo } from "react"
import { Link } from "react-router-dom"
import { useCriterionHistory } from "../../api/hooks"
import type { EntityDetail } from "../../api/types"
import { PriorityBadge, ZoneBadge } from "../ui/Badge"
import { Skeleton } from "../ui/Primitives"
import { Modal } from "../ui/Modal"
import { cleanSummary } from "../../lib/monitorText"

// Карточка «почему именно так» — эталон формы подачи из ТЗ. Показывает ТОЛЬКО
// готовый текст из БД (justification/recommendation, посчитан siar.rules.evaluate);
// компонент ничего не переформулирует и не досочиняет — только раскладывает
// уже существующие поля по понятным разделам с простыми подписями.
// Методика сопоставления связки с рейтингом РУСАДА (match_type) описана в
// разделе «Справка» — в самой карточке аналитику эта техническая деталь не нужна.

function fmtDate(iso: string | null): string {
  if (!iso) return "н/д"
  const d = new Date(iso)
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
}

export function DrillDownCard({
  detail,
  kind,
  loading,
  onClose,
}: {
  detail: EntityDetail | undefined
  kind: "osf" | "region"
  loading: boolean
  onClose: () => void
}) {
  // Разрез по критериям рейтинга для ТЕКУЩЕГО прогона — та же витрина, что и
  // в Динамике (rating_criteria), просто берём срез только за последнюю дату
  // вместо полного пивота по кварталам: здесь нужен один взгляд «что не так
  // сейчас», а не история изменений.
  const criteria = useCriterionHistory(kind, detail?.entity_name ?? null, !!detail)
  const latestCriteria = useMemo(() => {
    const base = (criteria.data?.items ?? []).filter((c) => c.criterion_kind === "base")
    if (!base.length) return []
    const latest = base.reduce((max, c) => (c.run_published_at > max ? c.run_published_at : max), base[0].run_published_at)
    return base.filter((c) => c.run_published_at === latest)
  }, [criteria.data])

  return (
    <Modal title="Почему именно так" onClose={onClose}>
      {loading || !detail ? (
            <div className="space-y-3">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <>
              <h2 className="text-xl font-extrabold text-[var(--color-text)] sm:text-2xl">
                {detail.entity_name}
                {detail.fo && <span className="ml-2 text-sm font-medium text-[var(--color-sub)]">{detail.fo}</span>}
              </h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <PriorityBadge priority={detail.priority} />
                <ZoneBadge zone={detail.zone} />
                {detail.risk_index !== null && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--color-line)] bg-[var(--color-surface-hover)] px-2.5 py-1 text-xs font-semibold text-[var(--color-text)]"
                    title="Процентиль по выборке текущего прогона: 100 — самый высокий риск, 0 — самый низкий"
                  >
                    Индекс риска: {detail.risk_index} из 100 (процентиль по выборке)
                  </span>
                )}
              </div>

              <Section title="Обоснование зоны риска">
                {detail.reason ? (
                  <p>
                    Сработало правило: <b>{detail.reason}</b>.
                  </p>
                ) : (
                  <p>Систематичности по истории нарушений не выявлено.</p>
                )}
                {detail.facts?.human && <p className="mt-1 text-[var(--color-sub)]">{detail.facts.human}</p>}
                {detail.proba != null && (
                  <p className="mt-1 text-xs text-[var(--color-sub)]">
                    Необработанная оценка модели (для аналитика): {detail.proba.toFixed(3)}
                  </p>
                )}
              </Section>

              <Section title="Обоснование приоритета">
                <p>{detail.justification}</p>
                <p className="mt-2 text-[var(--color-sub)]">
                  Балл рейтинга РУСАДА — {detail.rating_score} (
                  {detail.rating_high ? "оценивается как высокий" : "ниже порога высокого уровня"}
                  ). Правило соответствия одно и то же для всех связок, исключений нет.
                </p>
              </Section>

              {!!latestCriteria.length && (
                <Section title="Критерии рейтинга РУСАДА">
                  <div className="flex flex-wrap gap-2">
                    {latestCriteria.map((c) => (
                      <span
                        key={c.criterion_code}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] px-2.5 py-1.5 text-xs text-[var(--color-text)]"
                      >
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${
                            c.is_met === true
                              ? "bg-[var(--color-zone-green)]"
                              : c.is_met === false
                                ? "bg-[var(--color-zone-red)]"
                                : "bg-[var(--color-zone-nodata)]"
                          }`}
                        />
                        {c.criterion_code}
                      </span>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Рекомендация">
                <p>{detail.recommendation}</p>
              </Section>

              {(detail.top_regions?.length || detail.top_sports?.length) ? (
                <Section title={kind === "osf" ? "Самые рисковые регионы по этому виду спорта" : "Самые рисковые виды спорта в этом регионе"}>
                  <ul className="space-y-1">
                    {(detail.top_regions || detail.top_sports || []).slice(0, 5).map((peer, i) => {
                      const name = peer.region || peer.sport
                      return (
                        <li key={i} className="flex items-center justify-between gap-2 text-sm">
                          <span>{name && name.trim() !== "-" ? name : "н/д"}</span>
                          <ZoneBadge zone={peer.zone} />
                        </li>
                      )
                    })}
                  </ul>
                </Section>
              ) : null}

              <Section title="На каких данных посчитано">
                <p>
                  Сохранённый срез данных на {fmtDate(detail.snapshot.computed_at)}, версия модели{" "}
                  {detail.snapshot.model_version || "н/д"}. Повторный расчёт на этих же данных даст
                  точно такой же результат.
                </p>
              </Section>

              {detail.monitor_signals_30d !== undefined && (
                <Section title="Новости по теме (АД-Монитор)">
                  <p>
                    Сигналов мониторинга: {detail.monitor_signals_30d} за 30 дней,{" "}
                    {detail.monitor_signals_90d} за 90 дней. Это дополнительный контекст — он не
                    меняет зону риска и приоритет.
                  </p>
                  {detail.monitor_feed_note && (
                    <p className="mt-1 text-[var(--color-sub)]">{detail.monitor_feed_note}</p>
                  )}
                  {!!detail.monitor_feed?.length && (
                    <ul className="mt-3 space-y-2">
                      {detail.monitor_feed.map((item, i) => (
                        <li key={i} className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] p-3">
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-[var(--color-accent)] underline underline-offset-2 hover:text-[#5b93f5]"
                          >
                            {item.title}
                          </a>
                          {cleanSummary(item.summary) && (
                            <p className="mt-1 text-xs leading-relaxed text-[var(--color-text)]/80">{cleanSummary(item.summary)}</p>
                          )}
                          <div className="mt-1 text-xs text-[var(--color-sub)]">
                            {item.source_name || "источник н/д"} · {fmtDate(item.event_date)}
                            {item.scope && ` · ${item.scope === "rf" ? "Россия" : "международное"}`}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link
                    to="/monitor"
                    className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-accent)] hover:underline"
                  >
                    Смотреть в АД-Монитор →
                  </Link>
                </Section>
              )}
            </>
          )}
    </Modal>
  )
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 border-t border-[var(--color-line)] pt-4 first:mt-6 first:border-0 first:pt-0">
      <h3 className="mb-1.5 text-sm font-bold text-[var(--color-text)]">{title}</h3>
      <div className="text-sm leading-relaxed text-[var(--color-text)]/90">{children}</div>
    </div>
  )
}
