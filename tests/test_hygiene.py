# -*- coding: utf-8 -*-
"""tests/test_hygiene.py — гигиена репозитория (Definition of Done):

  * агрегатные таблицы ML/SIAR-конвейера не содержат колонок с ФИО
    (STRUCTURE.md, п. 8) — flags.subject НЕ проверяется здесь: это
    документированное исключение (README «Несущие принципы» — лента
    АД-Монитора republishing уже официально опубликованных санкций);
  * в отслеживаемых .py/.sh файлах нет хардкода домашних путей разработчика
    (/Users/..., /home/<user>/...) и debug-заглушек (pdb.set_trace, breakpoint()).

Общий грep по "секретам" намеренно НЕ ищет конкретные значения — тест не
должен сам держать в себе секретные строки; здесь проверяется форма
(паттерн локального пути), а не конкретное значение.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DDL_TEXT = (ROOT / "db" / "ddl.sql").read_text(encoding="utf-8")

PIPELINE_TABLES = [
    "registry_agg", "predictions", "quadrant_results",
    "rating_criteria", "thresholds", "matching_audit", "unmatched",
]
FORBIDDEN_COLUMN_TOKENS = ("фио", "full_name", "фамилия", "athlete_name", "имя_спортсмена")


def _table_block(name: str) -> str:
    # db/ddl.sql задаёт `SET LOCAL search_path = antidoping, public;` — сами
    # CREATE TABLE внутри файла не квалифицированы схемой.
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {name} \((.*?)\n\);", DDL_TEXT, re.S)
    assert m, f"не нашли CREATE TABLE IF NOT EXISTS {name} в db/ddl.sql"
    return m.group(1)


def _column_names(block: str) -> list[str]:
    names = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        if line.upper().startswith(("CONSTRAINT", "PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY")):
            continue
        m = re.match(r"^(\w+)\s+", line)
        if m:
            names.append(m.group(1).lower())
    return names


@pytest.mark.parametrize("table", PIPELINE_TABLES)
def test_pipeline_table_has_no_name_columns(table):
    cols = _column_names(_table_block(table))
    assert cols, f"не нашли ни одной колонки для {table} — проверьте регэксп парсинга"
    for col in cols:
        for bad in FORBIDDEN_COLUMN_TOKENS:
            assert bad not in col, (
                f"antidoping.{table}.{col} похоже на поле с ФИО — эта таблица "
                f"агрегатная (вид спорта × регион), персональные данные сюда "
                f"не попадают (STRUCTURE.md, п. 8)"
            )


def _tracked_files(*suffixes: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [ROOT / p for p in out if p.endswith(suffixes)]


_HOME_PATH_RE = re.compile(r"/Users/[A-Za-z0-9_.\-]+|/home/[A-Za-z0-9_.\-]+/")
_SELF_TEST_FILE = Path(__file__).resolve()


def test_no_hardcoded_developer_home_paths():
    offenders = []
    for path in _tracked_files(".py", ".sh"):
        if path.resolve() == _SELF_TEST_FILE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _HOME_PATH_RE.finditer(text):
            offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, (
        "хардкод домашних путей разработчика найден (используйте Path(__file__)."
        "resolve().parents[N] от корня репозитория, как везде в проекте):\n"
        + "\n".join(offenders)
    )


_DEBUG_MARKERS = ("pdb.set_trace(", "breakpoint()", "debugger;", "console.log(")


def test_no_debug_breakpoints_left_in_code():
    offenders = []
    for path in _tracked_files(".py", ".js", ".ts", ".tsx", ".jsx"):
        if path.resolve() == _SELF_TEST_FILE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in _DEBUG_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker!r}")
    assert not offenders, "debug-заглушки найдены в коде:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# ФИО не попадают во внешние LLM-запросы АД-Монитора (архитектурное
# требование — не только промтом, а по построению: build_prompt() физически
# не получает flags.subject/title/summary). Статическая проверка исходника
# monitor/summarize_digest.py.build_prompt — если кто-то однажды добавит туда
# параметр вроде `subject`/`title`, тест упадёт раньше продакшена.
# ---------------------------------------------------------------------------

_PII_FIELD_NAMES = ("subject", "title", "summary", "фио")


def test_summarize_digest_prompt_builder_never_touches_pii_fields():
    import ast
    import inspect
    import re

    from monitor import summarize_digest as sd

    source = inspect.getsource(sd.build_prompt) + "\n" + inspect.getsource(sd.anonymized_facts)
    # Убираем строковые литералы (докстринги/комментарии внутри исходника
    # неизбежно ОБСУЖДАЮТ subject/title как то, чего здесь нет) — интересует
    # только код: обращение к ключу/атрибуту с таким именем.
    tree = ast.parse(source)
    code_only_lines = set(range(1, source.count("\n") + 2))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            code_only_lines.discard(node.lineno)  # докстринг-выражение целиком

    lines = source.splitlines()
    code_text = "\n".join(l for i, l in enumerate(lines, start=1) if i in code_only_lines)

    key_access = re.compile(r"""['"](subject|title|summary)['"]|\.(subject|title|summary)\b""")
    m = key_access.search(code_text)
    assert m is None, (
        f"monitor/summarize_digest.py: build_prompt/anonymized_facts обращается к "
        f"полю «{m.group(0)}» — в LLM-запрос АД-Монитора должны попадать только "
        f"обезличенные агрегаты (категория/вид спорта/регион/дата): {code_text!r}"
    )
