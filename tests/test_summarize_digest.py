# -*- coding: utf-8 -*-
"""tests/test_summarize_digest.py — письменная аналитика АД-Монитора.

Ключевая проверка: в промт для LLM никогда не попадают flags.subject/title/
summary (могут содержать ФИО уже опубликованной санкции) — только
обезличенные агрегаты. Это архитектурное требование («запросы к внешним
моделям формируются только по обезличенным сущностям»), проверяем его как
инвариант, а не полагаемся на промт.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from monitor import summarize_digest as sd

PII_NAME = "Иванов Иван Иванович"


@pytest.fixture()
def seeded_flags(pg_dsn):
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute("INSERT INTO antidoping.runs (run_kind) VALUES ('monitor') RETURNING run_id")
    run_id = cur.fetchone()["run_id"]
    # Дата нарочно далеко от "сегодня" — tests/test_api.py::seeded тоже сеет
    # flags на сегодняшнюю дату в той же (сессионной) тестовой БД; разные
    # даты держат окна anonymized_facts непересекающимися между файлами тестов.
    today = dt.date.today() - dt.timedelta(days=365)
    dedup = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    cur.execute(
        """
        INSERT INTO antidoping.flags
            (run_id, monitor_date, event_date, category, is_doping_event, scope,
             sport, is_ru, title, summary, source_url, url_verified, confirmed, dedup_hash)
        VALUES
            (%(run_id)s, %(d)s, %(d)s, 'санкция', true, 'rf', 'Бокс', true,
             %(name)s, %(name)s, 'https://rusada.ru/x', true, true, %(dedup)s)
        """,
        {"run_id": run_id, "d": today, "name": PII_NAME, "dedup": dedup},
    )
    conn.close()
    return today


def test_prompt_never_includes_subject_or_title(seeded_flags, pg_dsn):
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    window_from = seeded_flags - dt.timedelta(days=3)
    facts, flag_ids = sd.anonymized_facts(cur, seeded_flags, window_from, "rf")
    conn.close()

    assert len(facts) == 1
    assert len(flag_ids) == 1
    for f in facts:
        assert set(f.keys()) == {"категория", "вид_спорта", "российский", "дата"}

    prompt = sd.build_prompt("rf", facts)
    assert PII_NAME not in prompt
    assert "Бокс" in prompt


def test_assert_narrative_clean_rejects_siar_jargon():
    with pytest.raises(SystemExit):
        sd.assert_narrative_clean("Это приоритет 1 по нашей оценке.")
    sd.assert_narrative_clean("Зафиксирована санкция в боксе.")  # не должно бросить


def test_main_writes_narrative_and_is_idempotent(seeded_flags, pg_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    calls = []

    def fake_caller(prompt, claude_bin):
        calls.append(prompt)
        return "Зафиксирована одна санкция в боксе за период."

    def connect(dsn):
        return psycopg.connect(dsn, row_factory=dict_row)

    monkeypatch.setattr(sd, "resolve_claude_bin", lambda: "unused")

    rc = sd.main(
        ["--monitor-date", str(seeded_flags), "--skip-empty"],
        connect=connect,
        claude_caller=fake_caller,
    )
    assert rc == 0
    assert len(calls) == 1  # только rf — intl пуст и пропущен (--skip-empty)
    assert PII_NAME not in calls[0]

    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT narrative FROM antidoping.digest_narrative WHERE monitor_date=%s AND scope='rf'",
        (seeded_flags,),
    )
    row = cur.fetchone()
    conn.close()
    assert row["narrative"] == "Зафиксирована одна санкция в боксе за период."

    # повторный запуск — идемпотентность (ON CONFLICT DO UPDATE, не дубль)
    rc2 = sd.main(
        ["--monitor-date", str(seeded_flags), "--skip-empty"],
        connect=connect,
        claude_caller=fake_caller,
    )
    assert rc2 == 0
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) AS n FROM antidoping.digest_narrative WHERE monitor_date=%s AND scope='rf'",
        (seeded_flags,),
    )
    assert cur.fetchone()["n"] == 1
    conn.close()
