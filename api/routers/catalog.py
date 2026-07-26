# -*- coding: utf-8 -*-
"""api/routers/catalog.py — переключатель снапшотов (LOGIC.md §4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import get_cursor
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/snapshots", tags=["snapshots"], dependencies=[Depends(require_session)]
)


@router.get("")
def list_snapshots():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM antidoping.v_snapshots ORDER BY run_id DESC LIMIT 50")
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}
