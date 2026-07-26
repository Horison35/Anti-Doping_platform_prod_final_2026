import { useState } from "react"
import { useLocation } from "react-router-dom"
import { useSubmitFeedback } from "../../api/hooks"
import { Button } from "../ui/Primitives"

export function FeedbackWidget() {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState("")
  const [sent, setSent] = useState(false)
  const submit = useSubmitFeedback()

  function close() {
    setOpen(false)
    setSent(false)
    setMessage("")
  }

  async function onSubmit() {
    if (!message.trim()) return
    await submit.mutateAsync({ section: location.pathname, message: message.trim() })
    setSent(true)
    setMessage("")
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-[var(--color-ink)] px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-black/20 transition hover:bg-[var(--color-ink-2)]"
      >
        💬 <span className="hidden sm:inline">Оставить отзыв</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 backdrop-blur-sm sm:items-center">
          <div className="w-full max-w-md rounded-2xl border border-[var(--color-line)] bg-[#0b1220]/95 p-6 shadow-xl backdrop-blur-2xl">
            {sent ? (
              <>
                <p className="text-base font-semibold text-[var(--color-text)]">
                  Спасибо, Ваш отзыв записан и передан разработчику!
                </p>
                <Button onClick={close} className="mt-4 w-full">
                  Закрыть
                </Button>
              </>
            ) : (
              <>
                <h3 className="text-base font-bold text-[var(--color-text)]">Пожелание или комментарий</h3>
                <p className="mt-1 text-xs text-[var(--color-sub)]">
                  Комментарии не отображаются в интерфейсе никому — только сохраняются с датой и разделом.
                </p>
                <textarea
                  autoFocus
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={4}
                  className="mt-3 w-full rounded-xl border border-[var(--color-line)] bg-[var(--color-surface)] p-3 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-sub)] focus:border-[var(--color-accent)]/50"
                  placeholder="Что можно улучшить?"
                />
                <div className="mt-3 flex gap-2">
                  <Button variant="ghost" onClick={close} className="flex-1">
                    Отмена
                  </Button>
                  <Button onClick={onSubmit} disabled={submit.isPending || !message.trim()} className="flex-1">
                    Отправить
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
