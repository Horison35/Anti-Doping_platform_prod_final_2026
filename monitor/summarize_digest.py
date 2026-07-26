#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor/summarize_digest.py — письменная аналитика АД-Монитора (шаг ПОСЛЕ load_digest.py).

Контракт ad_monitor_prompt_v15.md — только JSON, без прозы (правило самого
контракта) — этим файлом НЕ меняется: он не трогает monitor/run_daily.sh
и не переписывает промт узла. Это отдельный, дополнительный шаг конвейера:
читает уже загруженные и верифицированные flags за выпуск и просит модель
только пересказать (никаких оценок риска, LOGIC.md §1 «LLM только собирает
и резюмирует»).

Защита ФИО (жёсткое архитектурное требование, не только промтом): в LLM
уходят ТОЛЬКО обезличенные агрегаты — категория, вид спорта, страна/РФ,
дата, количество. Поля flags.subject/title/summary (могут содержать имя
уже опубликованной санкции — README, «Несущие принципы», исключение для
ленты АД-Монитора) в промт НЕ попадают вообще: не «просим не упоминать
имена», а физически не даём модели данных, из которых имя можно взять.

Запуск (после monitor/load_digest.py):
    python monitor/summarize_digest.py --monitor-date 2026-07-25

Идемпотентно: ON CONFLICT (monitor_date, scope) DO UPDATE — повторный запуск
на тот же день перезаписывает narrative, а не плодит дубли.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WINDOW_DAYS_BACK = int(os.environ.get("AD_MONITOR_WINDOW_DAYS", "4"))

# Служебный жаргон/оценочные слова, которым не место в пересказе новостей
# (LOGIC.md §1: LLM не оценивает риск и не порождает формулировки SIAR).
FORBIDDEN_NARRATIVE_TOKENS = (
    "приоритет", "siar", "зона риска", "красная зона", "оранжевая зона",
    "рекомендуется присвоить", "risk_index",
)

INSERT_NARRATIVE = """
INSERT INTO antidoping.digest_narrative
    (run_id, monitor_date, window_from, window_to, scope, narrative, source_flag_ids)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (monitor_date, scope) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    window_from = EXCLUDED.window_from,
    window_to = EXCLUDED.window_to,
    narrative = EXCLUDED.narrative,
    source_flag_ids = EXCLUDED.source_flag_ids,
    generated_at = now()
"""


def load_env(root: Path) -> None:
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def resolve_claude_bin() -> str:
    """Тот же приём, что monitor/run_daily.sh: стабильный симлинк, иначе
    поиск актуального бинарника claude-code в VSCode extensions."""
    link = Path.home() / ".claude" / "bin" / "claude"
    if link.exists():
        return str(link)
    candidates = sorted(
        (Path.home() / ".vscode" / "extensions").glob(
            "*anthropic.claude-code-*/resources/native-binary/claude"
        )
    )
    if candidates:
        return str(candidates[-1])
    raise SystemExit(
        "❌ Не нашёл claude-code ни по симлинку ~/.claude/bin/claude, ни в "
        "~/.vscode/extensions — установите Claude Code или создайте симлинк"
    )


def anonymized_facts(cur, monitor_date_: date, window_from: date, scope: str) -> tuple[list[dict], list[int]]:
    """Только обезличенные агрегаты — flags.subject/title/summary НЕ читаются."""
    cur.execute(
        """
        SELECT flag_id, category, sport, is_ru, event_date
        FROM antidoping.flags
        WHERE confirmed AND scope = %s
          AND monitor_date BETWEEN %s AND %s
        ORDER BY event_date NULLS LAST
        """,
        (scope, window_from, monitor_date_),
    )
    rows = cur.fetchall()
    facts = [
        {
            "категория": r["category"],
            "вид_спорта": r["sport"] or "не указан",
            "российский": r["is_ru"],
            "дата": str(r["event_date"]) if r["event_date"] else "н/д",
        }
        for r in rows
    ]
    return facts, [r["flag_id"] for r in rows]


def build_prompt(scope: str, facts: list[dict]) -> str:
    scope_label = "российского" if scope == "rf" else "международного"
    lines = "\n".join(
        f"- {f['категория']}, вид спорта: {f['вид_спорта']}, дата: {f['дата']}" for f in facts
    )
    return f"""Ты помогаешь антидопинговой платформе с чисто техническим пересказом.

Ниже — обезличенный список подтверждённых событий {scope_label} потока за период
({len(facts)} шт.). В списке НЕТ имён людей и организаций — не придумывай их и не
подставляй. Никаких оценок риска, приоритетов или рекомендаций — только сухой
связный пересказ на русском языке (3–5 предложений): что произошло по категориям
и видам спорта, какие сюжеты продолжаются. Не используй слова «приоритет»,
«зона риска», «SIAR». Если список пуст — напиши одну фразу, что значимых
подтверждённых событий за период не зафиксировано.

Список событий:
{lines if lines else "(пусто)"}

Верни только текст пересказа, без заголовков и разметки."""


def assert_narrative_clean(text: str) -> None:
    lowered = text.lower()
    for token in FORBIDDEN_NARRATIVE_TOKENS:
        if token in lowered:
            raise SystemExit(
                f"❌ Пересказ содержит запрещённый токен «{token}» — модель вышла "
                f"за рамки пересказа (LOGIC.md §1): {text!r}"
            )


def call_claude(prompt: str, claude_bin: str) -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "❌ ANTHROPIC_API_KEY задан в окружении — прогон остановлен, чтобы не "
            "уйти на платный API-путь по ошибке (см. monitor/run_daily.sh)"
        )
    env = dict(os.environ)
    env.setdefault("USER", os.environ.get("USER", "unknown"))
    env.setdefault("LOGNAME", os.environ.get("LOGNAME", "unknown"))
    result = subprocess.run(
        [claude_bin, "-p", prompt, "--output-format", "json"],
        capture_output=True, text=True, timeout=120, env=env,
    )
    if result.returncode != 0:
        raise SystemExit(f"❌ claude -p завершился с ошибкой: {result.stderr[:2000]}")
    import json as _json
    envelope = _json.loads(result.stdout)
    if envelope.get("is_error"):
        raise SystemExit(f"❌ claude -p вернул ошибку: {envelope.get('result')!r}")
    text = (envelope.get("result") or "").strip()
    m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    return text


def _pg_connect(dsn: str):
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        raise SystemExit("❌ Нет драйвера PostgreSQL: pip install 'psycopg[binary]'")
    from psycopg.rows import dict_row  # noqa: PLC0415
    return psycopg.connect(dsn, row_factory=dict_row)


def main(argv=None, connect=_pg_connect, claude_caller=call_claude) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monitor-date", default=str(date.today()))
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--skip-empty", action="store_true",
                     help="не звать модель для потока без подтверждённых событий")
    args = ap.parse_args(argv)

    monitor_date_ = date.fromisoformat(args.monitor_date)
    window_from = monitor_date_ - timedelta(days=WINDOW_DAYS_BACK - 1)

    load_env(ROOT)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("❌ DATABASE_URL не задан: заполните .env по образцу .env.example")

    claude_bin = resolve_claude_bin()

    conn = connect(dsn)
    try:
        cur = conn.cursor()
        written = 0
        for scope in ("rf", "intl"):
            facts, flag_ids = anonymized_facts(cur, monitor_date_, window_from, scope)
            if not facts and args.skip_empty:
                continue
            prompt = build_prompt(scope, facts)
            narrative = claude_caller(prompt, claude_bin)
            assert_narrative_clean(narrative)
            cur.execute(
                INSERT_NARRATIVE,
                (args.run_id, monitor_date_, window_from, monitor_date_, scope, narrative, flag_ids),
            )
            written += 1
            print(f"✅ {scope}: {len(facts)} событий → пересказ {len(narrative)} симв.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"✅ Письменная аналитика обновлена: {written} поток(ов) за {monitor_date_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
