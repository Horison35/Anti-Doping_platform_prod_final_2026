# -*- coding: utf-8 -*-
"""api/routers/health.py — проверка живости для docker-compose healthcheck/Nginx."""
from __future__ import annotations

from fastapi import APIRouter

from ..db import get_cursor

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health():
    with get_cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"status": "ok"}
