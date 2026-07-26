# -*- coding: utf-8 -*-
"""api/routers/gaps.py — «честная подача пробелов»: несопоставленные записи
SIAR как интерактивный JSON (не только выгрузка в Excel/CSV, ТЗ п. 3).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..db import get_cursor
from ..security import require_session

router = APIRouter(prefix="/api/v1/unmatched", tags=["gaps"], dependencies=[Depends(require_session)])


@router.get("")
def get_unmatched(kind: str = Query(..., pattern="^(osf|region)$")):
    with get_cursor() as cur:
        cur.execute(
            """SELECT unmatched_id, kind, side, name, reason FROM antidoping.unmatched
               WHERE kind = %s AND run_id = (
                   SELECT max(run_id) FROM antidoping.runs
                   WHERE published_at IS NOT NULL AND run_kind = %s
               )
               ORDER BY side, name""",
            (kind, f"siar_{kind}"),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}
