import { useEffect, useMemo, useRef, useState } from "react"
import { NavLink, Outlet, useNavigate } from "react-router-dom"
import { useHistoryEntities, useLogout, useMeta } from "../../api/hooks"
import { FeedbackWidget } from "../domain/FeedbackWidget"
import { Logo } from "../ui/Logo"

// Быстрый переход к любой связке из любой точки платформы — без похода
// в Приоритеты и ручного поиска глазами по таблице на 142/89 строк.
function GlobalSearch() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const navigate = useNavigate()
  const boxRef = useRef<HTMLDivElement>(null)
  const osf = useHistoryEntities("osf", open)
  const region = useHistoryEntities("region", open)

  useEffect(() => {
    function onOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onOutside)
    return () => document.removeEventListener("mousedown", onOutside)
  }, [])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const all = [
      ...(osf.data?.items ?? []).map((e) => ({ ...e, kind: "osf" as const })),
      ...(region.data?.items ?? []).map((e) => ({ ...e, kind: "region" as const })),
    ]
    return all.filter((e) => e.entity_name.toLowerCase().includes(q)).slice(0, 8)
  }, [osf.data, region.data, query])

  function select(name: string, kind: "osf" | "region") {
    setOpen(false)
    setQuery("")
    navigate(`/analytics?kind=${kind}&entity=${encodeURIComponent(name)}`)
  }

  return (
    <div ref={boxRef} className="relative">
      {open ? (
        // На узких экранах — почти во всю ширину шапки (иначе фиксированные
        // 288px перекрывают лого платформы, а не аккуратно ложатся поверх);
        // от sm и шире — компактный выпадающий блок у правого края.
        <div className="fixed inset-x-3 top-2.5 z-40 sm:absolute sm:inset-x-auto sm:right-0 sm:top-0 sm:w-80">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
            placeholder="Поиск связки — федерация или регион…"
            className="w-full rounded-lg border border-[var(--color-accent)] bg-[#0b1220] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-sub)] outline-none"
          />
          {!!results.length && (
            <div className="absolute z-20 mt-1.5 max-h-72 w-full overflow-y-auto rounded-xl border border-[var(--color-line)] bg-[#0b1220] shadow-2xl">
              {results.map((r) => (
                <button
                  key={`${r.kind}-${r.entity_name}`}
                  onClick={() => select(r.entity_name, r.kind)}
                  className="block w-full px-4 py-2.5 text-left text-sm text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]"
                >
                  {r.entity_name}
                  <span className="ml-2 text-xs text-[var(--color-sub)]">
                    {r.kind === "osf" ? "ОСФ" : "Регион"}
                    {r.fo ? ` · ${r.fo}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--color-sub)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
          aria-label="Поиск связки"
        >
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden>
            <circle cx="9" cy="9" r="6.5" stroke="currentColor" strokeWidth="1.6" />
            <path d="M14 14 L18.5 18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </div>
  )
}

function fmtShort(iso: string | null): string {
  if (!iso) return "н/д"
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
}

// Свежесть данных — сразу видно в шапке на любой странице, не нужно идти
// в Динамику/АД-Монитор, чтобы понять, насколько давно был прогон/выпуск.
function FreshnessBadge() {
  const meta = useMeta(true)
  if (!meta.data) return null
  return (
    <div
      className="hidden items-center gap-2 rounded-lg border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] px-3 py-1.5 text-xs text-[var(--color-sub)] xl:flex"
      title="Дата последнего опубликованного прогона SIAR и последнего выпуска АД-Монитора"
    >
      <span>Прогон: <b className="font-semibold text-[var(--color-text)]">{fmtShort(meta.data.siar_published_at)}</b></span>
      <span className="text-[var(--color-line)]">·</span>
      <span>АД-Монитор: <b className="font-semibold text-[var(--color-text)]">{fmtShort(meta.data.monitor_date)}</b></span>
    </div>
  )
}

const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/analytics", label: "Приоритеты" },
  { to: "/history", label: "Динамика" },
  { to: "/monitor", label: "АД-Монитор" },
  { to: "/export", label: "Выгрузка" },
  { to: "/о-системе", label: "О данных" },
  { to: "/справка", label: "Справка" },
]

export function AppShell() {
  const [open, setOpen] = useState(false)
  const logout = useLogout()

  return (
    <div className="flex min-h-screen flex-col">
      <div className="app-grain" />
      <div className="app-aurora">
        <i /><i /><i />
      </div>

      <header className="sticky top-0 z-30 border-b border-[var(--color-line)] bg-[#060911]/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2">
            <Logo size={26} />
            <span className="text-sm font-bold text-[var(--color-text)] sm:text-base">
              Антидопинговая платформа
            </span>
          </div>

          <nav className="hidden items-center gap-1 lg:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition ${
                    isActive
                      ? "bg-[var(--color-accent)] text-white shadow-[0_4px_16px_-4px_rgba(59,130,246,0.6)]"
                      : "text-[var(--color-sub)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            <GlobalSearch />
            <FreshnessBadge />
            <button
              onClick={() => logout.mutate()}
              className="hidden text-xs font-medium text-[var(--color-sub)] hover:text-[var(--color-text)] lg:block"
            >
              Выйти
            </button>
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-[var(--color-text)] hover:bg-[var(--color-surface-hover)] lg:hidden"
              aria-label="Меню"
            >
              <span className="text-xl">{open ? "✕" : "☰"}</span>
            </button>
          </div>
        </div>

        {open && (
          <nav className="flex flex-col gap-1 border-t border-[var(--color-line)] p-3 lg:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `rounded-lg px-4 py-3 text-sm font-medium ${
                    isActive ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              onClick={() => logout.mutate()}
              className="mt-2 rounded-lg px-4 py-3 text-left text-sm font-medium text-[var(--color-sub)]"
            >
              Выйти
            </button>
          </nav>
        )}
      </header>

      <main className="relative z-[1] mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="relative z-[1] border-t border-[var(--color-line)] px-4 py-6 text-center text-xs text-[var(--color-sub)] sm:px-6">
        Антидопинговая платформа поддержки принятия решений · внутренняя система
      </footer>

      <FeedbackWidget />
    </div>
  )
}
