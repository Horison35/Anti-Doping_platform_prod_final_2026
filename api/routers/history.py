# -*- coding: utf-8 -*-
"""api/routers/history.py — раздел «История рисковости» (архив прогонов).

Архив таблиц дисквалификаций/прогонов не очищается (LOGIC.md §1, §7) — этот
роутер читает ВСЕ опубликованные прогоны (v_quadrant_history/v_predictions_history),
а не только последний снапшот, как /osf и /regions.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..db import get_cursor
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/history", tags=["history"], dependencies=[Depends(require_session)]
)


@router.get("/entities")
def list_entities(kind: str = Query(..., pattern="^(osf|region)$")):
    """Список связок, по которым вообще есть история — для селектора на экране."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT entity_name, fo FROM antidoping.v_quadrant_history
            WHERE kind = %s ORDER BY entity_name
            """,
            (kind,),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}


@router.get("")
def get_history(
    kind: str = Query(..., pattern="^(osf|region)$"),
    entity_name: Optional[str] = Query(None),
    fo: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
):
    """Динамика зоны/приоритета/критериев по связке(ам) на всех опубликованных прогонах."""
    clauses = ["kind = %(kind)s"]
    params: dict = {"kind": kind}
    if entity_name:
        clauses.append("entity_name = %(entity_name)s")
        params["entity_name"] = entity_name
    if fo:
        clauses.append("fo = %(fo)s")
        params["fo"] = fo.upper()
    if date_from:
        clauses.append("run_published_at >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        clauses.append("run_published_at <= %(date_to)s")
        params["date_to"] = date_to

    where = " AND ".join(clauses)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM antidoping.v_quadrant_history WHERE {where} "
            f"ORDER BY run_published_at",
            params,
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}


@router.get("/features")
def get_feature_history(
    kind: str = Query(..., pattern="^(osf|region)$"),
    entity_name: str = Query(...),
):
    """Разрез «по каждому критерию» — сырые lag/rolling признаки модели по кварталам."""
    col = "sport" if kind == "osf" else "region"
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT target_year, target_quarter, proba, zone, reason,
                   lag_1q, lag_2q, rolling_mean_8q, rolling_sum_4q, run_published_at
            FROM antidoping.v_predictions_history
            WHERE {col} = %s
            ORDER BY run_published_at
            """,
            (entity_name,),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}


@router.get("/criteria")
def get_criteria_history(
    kind: str = Query(..., pattern="^(osf|region)$"),
    entity_name: str = Query(...),
):
    """Разрез «по каждому критерию рейтинга» (Стратегия/План-график/... для ОСФ,
    Блок 1/2/3 для регионов) — какой именно фактор менялся от прогона к прогону."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT rc.criterion_code, rc.block, rc.criterion_kind, rc.value, rc.is_met,
                   r.published_at AS run_published_at, r.model_version
            FROM antidoping.rating_criteria rc
            JOIN antidoping.runs r ON r.run_id = rc.run_id
            WHERE rc.kind = %s AND rc.entity_name = %s AND r.published_at IS NOT NULL
            ORDER BY r.published_at, rc.sort_order NULLS LAST, rc.criterion_code
            """,
            (kind, entity_name),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}


@router.get("/compare")
def compare_entities(
    kind: str = Query(..., pattern="^(osf|region)$"),
    entities: str = Query(..., description="список через запятую"),
):
    """Сравнение нескольких связок между собой на одном отрезке времени."""
    names = [n.strip() for n in entities.split(",") if n.strip()]
    if not names:
        return {"count": 0, "items": []}
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM antidoping.v_quadrant_history
            WHERE kind = %s AND entity_name = ANY(%s)
            ORDER BY entity_name, run_published_at
            """,
            (kind, names),
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}
