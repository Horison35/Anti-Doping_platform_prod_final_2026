import { useRef, useState, type FormEvent, type MouseEvent } from "react"
import { useLogin } from "../../api/hooks"
import { ApiError } from "../../api/client"
import { Button } from "../ui/Primitives"
import { Logo } from "../ui/Logo"

// Ближе к силуэту (левый край подписи хуже 66-78% — вдоль плеча/руки на фото),
// но по вертикали — только выше заголовка (≤24%) или ниже подвала (≥78%): на
// узких экранах (640-750px) карточка формы почти во всю ширину, горизонтальный
// отступ там не спасает — спасает только вертикальный зазор до/после неё.
const TELEMETRY = [
  { label: "УЗЕЛ 0x4F2A · СИНХРОНИЗИРОВАНО", top: "12%", left: "68%", delay: "0s" },
  { label: "ПОТОК ДАННЫХ: АКТИВЕН", top: "22%", left: "78%", delay: "2.6s" },
  { label: "ЦЕЛОСТНОСТЬ ДАННЫХ: ПОДТВЕРЖДЕНА", top: "80%", left: "64%", delay: "5.2s" },
  { label: "КАНАЛ СВЯЗИ: ЗАЩИЩЁН", top: "90%", left: "74%", delay: "7.8s" },
]

export function PasswordGate() {
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const login = useLogin()
  const stageRef = useRef<HTMLDivElement>(null)

  function onStageMouseMove(e: MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = (e.clientX - r.left) / r.width - 0.5
    const py = (e.clientY - r.top) / r.height - 0.5
    stageRef.current?.style.setProperty("--px", `${px * -16}px`)
    stageRef.current?.style.setProperty("--py", `${py * -12}px`)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await login.mutateAsync(password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError(err.message)
      } else {
        setError("Неверный пароль")
      }
    }
  }

  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#060911] px-4 py-10"
      onMouseMove={onStageMouseMove}
    >
      <div ref={stageRef} className="gate-hero-parallax">
        <div className="gate-hero-bg" style={{ backgroundImage: "url(/gate-hero.jpg)" }} />
      </div>
      <div className="gate-hero-scan" />
      <div className="gate-hero-veil" />
      <div className="app-grain" />
      {TELEMETRY.map((t) => (
        <span
          key={t.label}
          className="gate-telemetry"
          style={{ top: t.top, left: t.left, animationDelay: t.delay }}
        >
          {t.label}
        </span>
      ))}

      <div className="relative z-[2] w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mb-4 flex justify-center">
            <Logo size={30} />
          </div>
          <h1 className="text-2xl font-extrabold leading-tight text-white drop-shadow-[0_2px_12px_rgba(0,0,0,0.6)] sm:text-3xl">
            Антидопинговая система приоритизации принятия решений
          </h1>
          <p className="mt-3 text-sm text-white/60 sm:text-base">
            Сигнал виден раньше, чем результат теста
          </p>
        </div>
        <form
          onSubmit={onSubmit}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            e.currentTarget.style.setProperty("--hx", `${((e.clientX - r.left) / r.width) * 100}%`)
            e.currentTarget.style.setProperty("--hy", `${((e.clientY - r.top) / r.height) * 100}%`)
          }}
          className="glass !rounded-2xl p-6"
        >
          <label className="mb-2 block text-sm font-medium text-white/80">
            Пароль доступа
          </label>
          <input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder-white/30 outline-none focus:border-white/40"
            placeholder="••••••••"
          />
          {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
          <Button
            type="submit"
            disabled={login.isPending || !password}
            className="mt-4 w-full !bg-none !bg-white !text-[var(--color-ink)] !shadow-none hover:!bg-white/90"
          >
            {login.isPending ? "Проверяем…" : "Войти"}
          </Button>
        </form>
        <p className="mt-6 text-center text-xs text-white/40 drop-shadow-[0_1px_6px_rgba(0,0,0,0.8)]">
          Доступ только для сотрудников антидопинговой сферы
        </p>
      </div>
    </div>
  )
}
