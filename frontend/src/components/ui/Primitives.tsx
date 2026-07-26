import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react"

// Считаем от 0 до target по месту появления в вёрстке — само число всегда
// реальное (props.target), анимация только над тем, как быстро мы его показываем.
export function CountUp({
  target,
  durationMs = 900,
  delayMs = 0,
}: {
  target: number
  durationMs?: number
  /** Пауза перед стартом накрутки — синхронизирует момент счёта с моментом
   * появления самой карточки (см. Card.index), чтобы число не начинало
   * крутиться до/пока карточка ещё невидима. */
  delayMs?: number
}) {
  const [value, setValue] = useState(0)
  // Старт всегда с нуля при первом появлении на экране (переход на страницу) —
  // именно поэтому ref инициализируется нулём, а не текущим target: если бы
  // здесь стояло useRef(target), «от» и «до» совпадали бы на первом кадре и
  // накрутки не было бы видно вообще, только мгновенное появление готового числа.
  const prevTarget = useRef(0)

  useEffect(() => {
    if (!window.matchMedia("(prefers-reduced-motion: no-preference)").matches) {
      setValue(target)
      prevTarget.current = target
      return
    }
    const from = prevTarget.current
    let raf = 0
    const timeout = window.setTimeout(() => {
      const start = performance.now()
      function step(ts: number) {
        const p = Math.min((ts - start) / durationMs, 1)
        const eased = 1 - Math.pow(1 - p, 3)
        setValue(Math.round(from + (target - from) * eased))
        if (p < 1) raf = requestAnimationFrame(step)
        else prevTarget.current = target
      }
      raf = requestAnimationFrame(step)
    }, delayMs)
    return () => {
      window.clearTimeout(timeout)
      cancelAnimationFrame(raf)
    }
  }, [target, durationMs, delayMs])

  return <span className="tabular-nums">{value}</span>
}

// Блик, едущий за курсором по стеклу (LOGIC.md §4 не регламентирует —
// чисто визуальный хром, общий для всех .glass-поверхностей).
function useGlassGlow() {
  return useCallback((e: MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty("--hx", `${((e.clientX - r.left) / r.width) * 100}%`)
    e.currentTarget.style.setProperty("--hy", `${((e.clientY - r.top) / r.height) * 100}%`)
  }, [])
}

export function Card({
  children,
  className = "",
  index,
}: {
  children: ReactNode
  className?: string
  /** Порядковый номер в сетке — задаёт задержку появления, чтобы карточки
   * влетали по очереди («накручивается»), а не все разом одним кадром. */
  index?: number
}) {
  const onMouseMove = useGlassGlow()
  const style = index !== undefined ? { animationDelay: `${index * 70}ms` } : undefined
  return (
    <div className={`glass rise-in ${className}`} onMouseMove={onMouseMove} style={style}>
      {children}
    </div>
  )
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
}: {
  children: ReactNode
  onClick?: () => void
  variant?: "primary" | "ghost" | "outline"
  type?: "button" | "submit"
  disabled?: boolean
  className?: string
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
  const variants: Record<string, string> = {
    primary:
      "bg-gradient-to-b from-[#5b93f5] to-[var(--color-accent)] text-white shadow-[0_6px_24px_-6px_rgba(59,130,246,0.5)] hover:-translate-y-0.5 hover:shadow-[0_10px_30px_-6px_rgba(59,130,246,0.65)]",
    outline: "border border-[var(--color-line)] text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]",
    ghost: "text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]",
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function StatTile({
  label,
  value,
  accent,
  hint,
}: {
  label: string
  value: ReactNode
  accent?: string
  hint?: string
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--color-sub)]">
        {label}
      </div>
      <div
        className="mt-1.5 text-3xl font-extrabold tabular-nums sm:text-4xl"
        style={{ color: accent || "var(--color-text)", textShadow: accent ? `0 0 22px color-mix(in srgb, ${accent} 40%, transparent)` : undefined }}
      >
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-[var(--color-sub)]">{hint}</div>}
    </Card>
  )
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-[var(--color-surface-hover)] ${className}`} />
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-[var(--color-line)] px-6 py-12 text-center">
      <div className="font-semibold text-[var(--color-text)]">{title}</div>
      {hint && <div className="text-sm text-[var(--color-sub)]">{hint}</div>}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-[var(--color-zone-red)]/30 bg-[var(--color-zone-red)]/10 px-6 py-8 text-center text-sm text-red-300">
      Не удалось загрузить данные: {message}
    </div>
  )
}

export function TopNSelector({
  value,
  onChange,
  total,
}: {
  value: number | "all"
  onChange: (v: number | "all") => void
  total: number
}) {
  const options: Array<number | "all"> = [10, 20, 50, "all"]
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-xl bg-[var(--color-surface-soft)] border border-[var(--color-line-soft)] p-1 text-sm">
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={`rounded-lg px-2 py-1.5 font-medium transition sm:px-3 ${
            value === opt ? "bg-white text-[#070b12] shadow-sm" : "text-[var(--color-sub)] hover:text-[var(--color-text)]"
          }`}
        >
          {opt === "all" ? `Все (${total})` : `Топ-${opt}`}
        </button>
      ))}
    </div>
  )
}
