import { useEffect, type ReactNode } from "react"
import { createPortal } from "react-dom"

// Портал прямо в document.body — иначе модалка рендерится внутри <main
// className="relative z-[1]">, которое само создаёт новый stacking context:
// z-50 на модалке тогда сравнивается только с соседями ВНУТРИ <main>, а не
// со шторкой <header> (z-30) — и шапка перекрывает крестик закрытия,
// независимо от того, насколько большой z-index стоит у самой модалки.
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center sm:p-6"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full overflow-y-auto rounded-t-3xl border border-[var(--color-line)] bg-[#0b1220]/95 backdrop-blur-2xl sm:max-w-2xl sm:rounded-3xl"
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-[var(--color-line)] bg-[#0b1220]/95 px-5 py-4 backdrop-blur">
          <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-sub)]">{title}</div>
          <button
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>
        <div className="px-5 py-5 sm:px-8 sm:py-7">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
