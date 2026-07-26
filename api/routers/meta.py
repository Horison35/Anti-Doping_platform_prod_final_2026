# -*- coding: utf-8 -*-
"""api/routers/meta.py — свежесть данных для шапки платформы: дата последнего
опубликованного прогона SIAR и дата последнего выпуска АД-Монитора. Только
чтение уже существующих меток времени — никаких новых расчётов."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import get_cursor
from ..security import require_session

router = APIRouter(prefix="/api/v1/meta", tags=["meta"], dependencies=[Depends(require_session)])


@router.get("")
def get_meta():
    with get_cursor() as cur:
        cur.execute("SELECT max(published_at) AS d FROM antidoping.runs WHERE published_at IS NOT NULL")
        siar = (cur.fetchone() or {}).get("d")
        cur.execute("SELECT max(monitor_date) AS d FROM antidoping.flags")
        monitor = (cur.fetchone() or {}).get("d")
    return {
        "siar_published_at": siar.isoformat() if siar else None,
        "monitor_date": str(monitor) if monitor else None,
    }
