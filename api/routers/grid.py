# -*- coding: utf-8 -*-
"""api/routers/grid.py — сырая сетка «вид спорта × регион» для heatmap (СЛОЙ 4/5).

Источник — predictions последнего опубликованного ml-прогона. Зона/proba —
как есть из ml/predict.py (siar/rules.assign_zone), без пересчёта.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import get_cursor
from ..security import require_session

router = APIRouter(prefix="/api/v1/grid", tags=["grid"], dependencies=[Depends(require_session)])


@router.get("")
def get_grid():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT sport, region, zone, proba, reason
            FROM antidoping.predictions
            WHERE run_id = (
                SELECT max(run_id) FROM antidoping.runs
                WHERE published_at IS NOT NULL AND run_kind = 'ml'
            )
            """
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}
