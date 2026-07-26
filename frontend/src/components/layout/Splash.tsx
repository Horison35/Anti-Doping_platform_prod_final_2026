import { Button, CountUp } from "../ui/Primitives"
import { Logo } from "../ui/Logo"

export function Splash({ onContinue }: { onContinue: () => void }) {
  return (
    <div className="relative flex min-h-screen flex-col justify-between overflow-hidden bg-[#060911] px-6 py-10 sm:px-12 sm:py-14">
      <div className="app-grain" />
      <div className="app-aurora">
        <i /><i /><i />
      </div>

      <div className="relative z-10 mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center">
        <div className="mb-6 inline-flex w-fit items-center gap-2.5 rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-white/70">
          <Logo size={16} />
          Система поддержки принятия решений
        </div>
        <h1 className="text-3xl font-extrabold leading-tight text-white sm:text-5xl">
          Нарушение видно раньше,
          <br className="hidden sm:block" /> чем оно официально зарегистрировано
        </h1>
        <p className="mt-6 max-w-2xl text-base leading-relaxed text-white/70 sm:text-lg">
          Система приоритизации антидопинговой работы: сразу видно, в каких спортивных
          федерациях и субъектах РФ необходимо усилить антидопинговую деятельность, а где
          ситуация остаётся под контролем.
        </p>
        <p className="mt-4 max-w-2xl text-xs text-white/40">
          История нарушений, официальные рейтинги РУСАДА и ежедневный новостной мониторинг —
          в одной картине, без ручной сверки таблиц.
        </p>
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[
            { n: 142, label: "общероссийских федераций под наблюдением" },
            { n: 89, label: "субъектов РФ в матрице риска" },
            { n: 4, label: "уровня приоритета — понятных с первого взгляда" },
          ].map((s) => (
            <div
              key={s.label}
              onMouseMove={(e) => {
                const r = e.currentTarget.getBoundingClientRect()
                e.currentTarget.style.setProperty("--hx", `${((e.clientX - r.left) / r.width) * 100}%`)
                e.currentTarget.style.setProperty("--hy", `${((e.clientY - r.top) / r.height) * 100}%`)
              }}
              className="glass !rounded-2xl p-4"
            >
              <div className="text-2xl font-extrabold tabular-nums text-white">
                <CountUp target={s.n} />
              </div>
              <div className="mt-1 text-xs text-white/60">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="relative z-10 flex items-center justify-between gap-4">
        <p className="hidden max-w-sm text-xs text-white/40 sm:block">
          Ни одна цифра и ни один факт не выдуманы нейросетью — каждый вывод можно перепроверить.
        </p>
        <Button
          onClick={onContinue}
          className="ml-auto !bg-none !bg-white !text-[var(--color-ink)] !shadow-none !px-6 !py-3 hover:!bg-white/90"
        >
          Продолжить →
        </Button>
      </div>
    </div>
  )
}
