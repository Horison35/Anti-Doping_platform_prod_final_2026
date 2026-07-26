import { Card } from "../components/ui/Primitives"
import { PriorityBadge, ZoneBadge } from "../components/ui/Badge"

export default function Help() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-sub)]">Справка</p>
        <h1 className="text-2xl font-extrabold text-[var(--color-text)]">Как читать платформу</h1>
      </div>

      <Card className="p-5">
        <h2 className="mb-3 text-sm font-bold text-[var(--color-text)]">Зона риска</h2>
        <p className="mb-3 text-sm text-[var(--color-sub)]">
          Зону задаёт прогнозная модель по истории нарушений — рейтинг РУСАДА на неё не влияет.
        </p>
        <div className="flex flex-wrap gap-2">
          <ZoneBadge zone="RED" />
          <ZoneBadge zone="ORANGE" />
          <ZoneBadge zone="GREEN" />
          <ZoneBadge zone="NO_DATA" />
        </div>
        <ul className="mt-3 space-y-1 text-sm text-[var(--color-text)]/90">
          <li><b>Высокий риск</b> — есть нарушения за последние два квартала подряд.</li>
          <li><b>Повышенный риск</b> — нарушения повторяются на длинной истории (два года).</li>
          <li><b>Низкий риск</b> — по истории нарушений всё спокойно.</li>
          <li><b>Нет данных</b> — прогнозная модель не располагает данными по этой связке.</li>
        </ul>
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 text-sm font-bold text-[var(--color-text)]">Приоритет</h2>
        <p className="mb-3 text-sm text-[var(--color-sub)]">
          Приоритет — это зона риска, сопоставленная с качеством антидопинговой работы (баллом
          рейтинга РУСАДА). Одна и та же таблица соответствия — для всех связок, без исключений.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PriorityCell p={1} desc="Высокий риск + рейтинг ниже порога — требует немедленного внимания." />
          <PriorityCell p={2} desc="Высокий риск, но антидопинговая работа уже на хорошем уровне." />
          <PriorityCell p={3} desc="«Потенциальный риск»: явных нарушений нет, но рейтинг говорит, что работа не проводится." />
          <PriorityCell p={4} desc="Риска нет, работа ведётся хорошо — плановый мониторинг." />
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Матрица (квадранты) и тепловая карта</h2>
        <p className="text-sm text-[var(--color-text)]/90">
          На матрице каждая точка — федерация или регион: по горизонтали — балл рейтинга РУСАДА,
          по вертикали — оценка риска модели. Цвет — приоритет. Тепловая карта показывает то же
          самое в разрезе «вид спорта × регион» — чем краснее клетка, тем выше риск именно в этой
          комбинации.
        </p>
      </Card>

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Селектор Топ-N</h2>
        <p className="text-sm text-[var(--color-text)]/90">
          На каждой таблице есть переключатель «Топ-10 / Топ-20 / Топ-50 / Все записи» — данные
          никогда не скрываются, любую запись любого среза можно посмотреть полностью, а через
          раздел «Выгрузка» — скачать целиком в Excel или CSV.
        </p>
      </Card>

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">«Почему именно так»</h2>
        <p className="text-sm text-[var(--color-text)]/90">
          Клик по любой строке или точке открывает карточку с обоснованием: какое правило
          сработало и какие фактические цифры за этим стоят. Текст обоснования всегда пишет код
          по утверждённой методике — искусственный интеллект его не формулирует.
        </p>
      </Card>

      <Card className="p-5">
        <h2 className="mb-2 text-sm font-bold text-[var(--color-text)]">Как связали название с рейтингом РУСАДА</h2>
        <p className="mb-3 text-sm text-[var(--color-text)]/90">
          Название федерации или региона в прогнозной модели и в официальном рейтинге РУСАДА не
          всегда записано одинаково («ФТАР» / «Федерация тхэквондо России»). Чтобы сопоставить
          связку с её баллом рейтинга, код проверяет варианты по порядку — какой сработал, тот и
          использован:
        </p>
        <ul className="space-y-1.5 text-sm text-[var(--color-text)]/90">
          <li><b>Полное совпадение названий</b> — самый надёжный вариант.</li>
          <li><b>Совпадение по алиасу</b> — известное другое название той же связки.</li>
          <li><b>Отдельная маршрутизация для паралимпийских дисциплин</b> — свой список сопоставлений.</li>
          <li><b>Совпадение по отдельным словам в названии</b> (токены) — когда общее название состоит из тех же ключевых слов.</li>
          <li><b>Совпадение по части слов</b> — частичное токенное совпадение.</li>
          <li><b>Морфологическое совпадение</b> — совпадение с учётом падежей и окончаний.</li>
        </ul>
        <p className="mt-3 text-sm text-[var(--color-sub)]">
          Если ни один вариант не сработал — соответствие не найдено, и балл рейтинга РУСАДА в
          обосновании приоритета не учитывается.
        </p>
      </Card>
    </div>
  )
}

function PriorityCell({ p, desc }: { p: 1 | 2 | 3 | 4; desc: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-surface-soft)] p-3">
      <PriorityBadge priority={p} />
      <p className="mt-2 text-xs text-[var(--color-text)]/80">{desc}</p>
    </div>
  )
}
