#!/bin/bash
# monitor/run_daily.sh — прогон АД-Монитора (планировщик: раз в 4 дня, см. DEPLOY.md).
#
# Имя файла осталось историческим (run_daily.sh) — переименование задело бы
# README/DEPLOY/systemd-юнит без содержательной пользы; фактическая частота
# задаётся исключительно расписанием планировщика (systemd timer,
# OnCalendar=*-*-* 00:00:00/4 дня — не в этом скрипте) + WINDOW_DAYS ниже.
# Промышленный контур (2026-07): по антидопинговой теме публикации выходят
# нечасто — ежедневный прогон прототипа давал много пустых итераций и
# расход токенов впустую; WINDOW_DAYS=4 держит окно синхронным с расписанием,
# чтобы новости за все 4 дня между прогонами не терялись.
#
# claude -p — headless-режим Claude Code по подписке (claude.ai OAuth,
# НЕ ANTHROPIC_API_KEY — переменная сознательно не читается и не нужна).
#
# Промт для claude -p = ad_monitor_prompt_v15.md ЦЕЛИКОМ (задаёт формат JSON)
# + 4 раздела из ad-monitor.skill (задают процесс сбора, не формат):
#   «Матрица обязательных запросов», «Календарные триггеры»,
#   «Верификация записей», «Финальный чек-лист». Раздел «Структура выпуска»
#   (HTML/present_files/digest_template.html) НЕ включается — он для другого
#   сценария (интерактивный дайджест в чате), не для headless JSON.
#
# Порядок: собрать промт → claude -p → снять JSON из envelope (снять
# markdown-обёртку ```json, если появится) → monitor/load_digest.py → лог.
#
# ВАЖНО: НЕ добавлен в cron автоматически. Сначала прогнать руками и
# проверить сырой вывод + содержимое antidoping.flags.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# cron запускается с минимальным PATH (обычно /usr/bin:/bin) — там нет ни
# venv, ни Postgres.app. Не полагаемся на то, что PATH уже настроен.
export PATH="$ROOT/.venv/bin:/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
PYTHON_BIN="$ROOT/.venv/bin/python3"

# claude auth (OAuth-сессия claude.ai) теряется без USER/LOGNAME в окружении —
# найдено эмпирически (env -i HOME+PATH → "Not logged in"; + USER/LOGNAME →
# залогинено). cron гарантирует LOGNAME, но не USER — не полагаемся на удачу.
export USER="${USER:-$(whoami)}"
export LOGNAME="${LOGNAME:-$(whoami)}"

DATE="$(date +%F)"
RUN_UUID="$(uuidgen)"
WINDOW_DAYS="${AD_MONITOR_WINDOW_DAYS:-4}"
INBOX="$ROOT/monitor/inbox"
LOGS="$ROOT/monitor/logs"
mkdir -p "$INBOX" "$LOGS"

LOG_FILE="$LOGS/run_${DATE}.log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

log "=== АД-Монитор: прогон $DATE (run_uuid=$RUN_UUID) ==="

# ── Стабильный путь к claude: симлинк ~/.claude/bin/claude, не версионный
#    путь внутри VSCode-расширения. Если симлинк протух (расширение
#    обновилось, старая версия удалена) — чиним сами, а не падаем молча. ──
CLAUDE_LINK="$HOME/.claude/bin/claude"
if [ ! -e "$CLAUDE_LINK" ]; then
    log "⚠️  $CLAUDE_LINK не резолвится — ищу актуальный бинарник claude-code в VSCode extensions"
    NEW_BIN="$(find "$HOME/.vscode/extensions" -maxdepth 4 \
        -path '*anthropic.claude-code-*/resources/native-binary/claude' -type f 2>/dev/null \
        | sort -V | tail -1)"
    if [ -z "$NEW_BIN" ]; then
        log "❌ Не нашёл claude-code ни по симлинку, ни в ~/.vscode/extensions — прогон остановлен"
        exit 1
    fi
    mkdir -p "$(dirname "$CLAUDE_LINK")"
    ln -sf "$NEW_BIN" "$CLAUDE_LINK"
    log "🔧 Симлинк переприкреплён: $CLAUDE_LINK -> $NEW_BIN"
fi
CLAUDE_BIN="$CLAUDE_LINK"

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    log "❌ ANTHROPIC_API_KEY задан в окружении — прогон остановлен, чтобы не уйти на платный API-путь по ошибке"
    exit 1
fi

# ── 1. Собрать промт: контракт (формат) + 4 раздела скилла (процесс) ──
PROMPT_FILE="$(mktemp)"
trap 'rm -f "$PROMPT_FILE"' EXIT

cat "$ROOT/monitor/ad_monitor_prompt_v15.md" > "$PROMPT_FILE"
printf '\n---\n\n' >> "$PROMPT_FILE"

"$PYTHON_BIN" - "$ROOT/monitor/ad-monitor.skill" >> "$PROMPT_FILE" <<'PYEOF'
import re
import sys
import zipfile

skill_path = sys.argv[1]
with zipfile.ZipFile(skill_path) as z:
    text = z.read("ad-monitor/SKILL.md").decode("utf-8")

wanted = ["Матрица обязательных запросов", "Календарные триггеры",
         "Верификация записей", "Финальный чек-лист"]
parts = re.split(r"(?m)^## ", text)
found = {}
for part in parts[1:]:
    header_line = part.split("\n", 1)[0].strip()
    for prefix in wanted:
        if header_line.startswith(prefix):
            found[prefix] = "## " + part.rstrip()
missing = [p for p in wanted if p not in found]
if missing:
    sys.exit(f"не найдены разделы в SKILL.md: {missing}")

# Чек-лист в SKILL.md писан под HTML-выпуск (пункты 4/6/7 ссылаются на номера
# разделов из «Структура выпуска», которую мы не включаем в headless-JSON
# промт) — адаптируем эти три пункта под поля JSON-контракта. 1/2/3/5/8 не
# трогаем — универсальны. Файл-источник (ad-monitor.skill) не меняем, правка
# только здесь, при сборке. Если исходный текст когда-нибудь изменится —
# явная ошибка, а не тихая неприменённая замена.
CHECKLIST_FIXES = {
    "4. Каждая подтверждённая запись имеет первичный источник в разделе 09.":
        "4. Каждая запись в data_feed.records с verification=\"verified\" имеет\n"
        "   непустой source_url.",
    "6. Все даты в разделах 04–06 сверены с первоисточниками этого прогона.":
        "6. Все даты в data_feed.records и dashboard.timeline сверены с\n"
        "   первоисточниками этого прогона.",
    "7. KPI арифметически сходятся с содержимым разделов.":
        "7. KPI в dashboard.kpi арифметически сходятся с суммой count по\n"
        "   соответствующим спискам, которые их формируют:\n"
        "   - \"Новые дисквалификации\" / \"Рос. санкции (окно)\" — считаются\n"
        "     по data_feed.records (только то, что реально в window_days);\n"
        "   - \"Междунар. санкции\" — если dashboard.tables содержит контекстные\n"
        "     записи вне окна (с note \"вне окна\"), KPI может отражать этот\n"
        "     более широкий контекст, но тогда рядом с меткой должно быть явно\n"
        "     видно, что это контекст, а не новое (например через сам title\n"
        "     таблицы \"вне окна, если новых нет\" — уже есть в контракте).\n"
        "\n"
        "   Иными словами: KPI никогда не расходится с тем списком, который\n"
        "   его непосредственно порождает — но data_feed (→ flags/БД) и\n"
        "   dashboard-контекст (→ только показ человеку) остаются двумя\n"
        "   разными списками по замыслу, не должны искусственно совпадать.",
}
checklist_text = found["Финальный чек-лист"]
for old, new in CHECKLIST_FIXES.items():
    if old not in checklist_text:
        sys.exit(f"ожидаемая строка чек-листа для замены не найдена: {old!r}")
    checklist_text = checklist_text.replace(old, new)
found["Финальный чек-лист"] = checklist_text

for p in wanted:
    print(found[p])
    print()
PYEOF

cat >> "$PROMPT_FILE" <<EOF

---

Параметры прогона: window_days=$WINDOW_DAYS, focus=all, run_id=$RUN_UUID.

Это headless-автоматизация с реально предоставленными правами WebSearch и WebFetch (--allowedTools). Эти инструменты могут быть в списке отложенных (deferred) — если не видишь их сразу среди доступных, найди их через поиск инструментов и используй по-настоящему для каждого источника матрицы. Это не ролевая игра и не тест: результат проверяется кодом (HTTP-проверка ссылок, дедуп) до попадания в базу — не отказывайся от задания без хотя бы одной реальной попытки поиска.

Верни ТОЛЬКО валидный JSON по контракту из системного промта выше. Никакого HTML, markdown-обёртки, дайджеста или текста вне JSON.
EOF

log "Промт собран: $(wc -l < "$PROMPT_FILE" | tr -d ' ') строк ($ROOT/monitor/ad_monitor_prompt_v15.md + 4 раздела ad-monitor.skill)"

# ── 2. Вызов claude -p (headless, подписка claude.ai, --output-format json),
#    с ОДНОЙ автоматической повторной попыткой, если ответ не оказался
#    валидным JSON. --allowedTools обязателен: без него в non-interactive
#    режиме (нет TTY для интерактивного разрешения) любой вызов инструмента
#    отклоняется автоматически (прогон 2026-07-13). Отдельно от прав — сами
#    WebSearch/WebFetch бывают в списке ОТЛОЖЕННЫХ инструментов (нужно сначала
#    «найти» через поиск инструментов, как и любой другой deferred-tool);
#    2026-07-14 модель ни разу не попыталась их найти и ответила текстом без
#    JSON вообще — 2026-07-15 повтор с тем же промтом отработал корректно без
#    единой правки, отсюда и retry ниже как вторая, независимая линия защиты
#    (первая — явное упоминание deferred-инструментов в самом промте выше). ──
DIGEST_VALID=0
for ATTEMPT in 1 2; do
    RAW_ENVELOPE="$INBOX/raw_${DATE}_${RUN_UUID}_attempt${ATTEMPT}.json"
    DIGEST_JSON="$INBOX/digest_${DATE}_${RUN_UUID}_attempt${ATTEMPT}.json"

    log "Вызываю claude -p (попытка $ATTEMPT/2)..."
    if ! "$CLAUDE_BIN" -p "$(cat "$PROMPT_FILE")" --output-format json \
            --allowedTools "WebSearch WebFetch" \
            > "$RAW_ENVELOPE" 2>>"$LOG_FILE"; then
        log "⚠️  Попытка $ATTEMPT: claude -p завершился с ошибкой, см. $RAW_ENVELOPE / $LOG_FILE"
        continue
    fi
    log "Сырой ответ claude (попытка $ATTEMPT): $RAW_ENVELOPE"

    # Снять .result из envelope + markdown-обёртку ```json, если появится
    # (ответ не всегда чистый JSON — реальный случай 2026-07-13: «вот
    # результат: ```json...``` заметки»); ищем фенс в ЛЮБОМ месте текста,
    # не только в начале, с fallback на голый текст. Успех попытки — только
    # если получившийся текст реально парсится как JSON (json.loads).
    if ! "$PYTHON_BIN" - "$RAW_ENVELOPE" "$DIGEST_JSON" <<'PYEOF'
import json
import re
import sys

raw_path, out_path = sys.argv[1], sys.argv[2]
with open(raw_path, encoding="utf-8") as f:
    envelope = json.load(f)

if envelope.get("is_error"):
    sys.exit(f"claude -p вернул ошибку: {envelope.get('result')!r}")

def extract_json_text(text: str) -> str:
    text = text.strip()
    m = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text  # фенса нет вообще — текст уже голый JSON (проверено тестами)

text = extract_json_text(envelope.get("result") or "")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(text)

json.loads(text)  # не парсится → ненулевой код выхода → попытка провалена
PYEOF
    then
        log "⚠️  Попытка $ATTEMPT: ответ не оказался валидным JSON ($DIGEST_JSON)"
        continue
    fi

    log "✅ Попытка $ATTEMPT дала валидный JSON: $DIGEST_JSON"
    DIGEST_VALID=1
    break
done

if [ "$DIGEST_VALID" != "1" ]; then
    log "❌ Обе попытки (1 и 2) не дали валидного JSON — прогон $DATE провален"
    exit 1
fi

# ── Ручная проверка перед первым включением в cron: AD_MONITOR_SKIP_LOAD=1
#    останавливает прогон здесь — файл с JSON остаётся на диске, в БД ничего
#    не пишется. Штатный cron-режим (без переменной) идёт в БД как обычно. ──
if [ "${AD_MONITOR_SKIP_LOAD:-0}" = "1" ]; then
    log "⏸️  AD_MONITOR_SKIP_LOAD=1 — загрузка в БД пропущена, файл для ручной проверки: $DIGEST_JSON"
    exit 0
fi

# ── 3. Загрузка в БД ──
log "Загружаю в БД: $PYTHON_BIN monitor/load_digest.py $DIGEST_JSON"
if ! "$PYTHON_BIN" "$ROOT/monitor/load_digest.py" "$DIGEST_JSON" 2>&1 | tee -a "$LOG_FILE"; then
    log "❌ load_digest.py завершился с ошибкой — прогон $DATE провален"
    exit 1
fi

# ── 4. Письменная аналитика (отдельный шаг, не часть контракта v15) ──
log "Формирую письменную аналитику: $PYTHON_BIN monitor/summarize_digest.py --monitor-date $DATE"
if "$PYTHON_BIN" "$ROOT/monitor/summarize_digest.py" --monitor-date "$DATE" --skip-empty 2>&1 | tee -a "$LOG_FILE"; then
    log "✅ Прогон $DATE завершён успешно (данные + письменная аналитика)"
else
    log "⚠️  summarize_digest.py завершился с ошибкой — данные выпуска уже в БД, "
    log "    только письменного обзора не будет; прогон $DATE НЕ считается провальным"
fi
