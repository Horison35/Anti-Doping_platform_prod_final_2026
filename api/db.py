# -*- coding: utf-8 -*-
"""api/db.py — пул подключений к PostgreSQL (psycopg 3 + psycopg_pool).

Один пул на процесс uvicorn; курсоры отдают dict (row_factory=dict_row),
чтобы роутеры сразу отдавали JSON без ручного маппинга колонок.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


@contextmanager
def get_cursor() -> Iterator["psycopg.Cursor"]:  # noqa: F821
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
