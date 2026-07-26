# -*- coding: utf-8 -*-
"""api/routers/regions.py — контракт dashboard.v1: субъекты РФ (СЛОЙ 4)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import get_cursor
from ..facts import build_facts
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/regions", tags=["regions"], dependencies=[Depends(require_session)]
)


@router.get("/summary")
def get_summary():
    """Для «Обзора» (персона руководителя): счётчики по приоритетам, текущий
    прогон vs предыдущий."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT run_id FROM antidoping.runs
            WHERE published_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM antidoping.quadrant_results q
                          WHERE q.run_id = runs.run_id AND q.kind = 'region')
            ORDER BY published_at DESC LIMIT 2
            """
        )
        run_ids = [r["run_id"] for r in cur.fetchall()]
        if not run_ids:
            return {"available": False}

        def counts(run_id: int) -> dict:
            cur.execute(
                "SELECT priority, count(*) AS n FROM antidoping.quadrant_results "
                "WHERE run_id = %s AND kind = 'region' GROUP BY priority",
                (run_id,),
            )
            by_p = {1: 0, 2: 0, 3: 0, 4: 0}
            for row in cur.fetchall():
                by_p[row["priority"]] = row["n"]
            return by_p

        current = counts(run_ids[0])
        previous = counts(run_ids[1]) if len(run_ids) > 1 else None

        cur.execute(
            "SELECT entity_name, fo, zone, rating_score, justification FROM antidoping.quadrant_results "
            "WHERE run_id = %s AND kind = 'region' AND priority = 1 "
            "ORDER BY risk_rank NULLS LAST LIMIT 5",
            (run_ids[0],),
        )
        top5 = cur.fetchall()

    return {
        "available": True,
        "current": current,
        "previous": previous,
        "top5_priority1": top5,
    }


@router.get("")
def list_regions(
    zone: Optional[str] = Query(None),
    priority: Optional[int] = Query(None, ge=1, le=4),
    fo: Optional[str] = Query(None, description="Федеральный округ"),
    limit: Optional[int] = Query(None, description="Топ-N; без параметра — все записи"),
):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM antidoping.v_regions_current ORDER BY priority, risk_rank NULLS LAST"
        )
        rows = cur.fetchall()

    if zone:
        rows = [r for r in rows if r["zone"] == zone.upper()]
    if priority:
        rows = [r for r in rows if r["priority"] == priority]
    if fo:
        rows = [r for r in rows if r["fo"] == fo.upper()]
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return {"total": total, "returned": len(rows), "items": rows}


@router.get("/fo-summary")
def fo_summary():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM antidoping.v_fo_summary
            WHERE run_id = (SELECT run_id FROM antidoping.v_regions_current LIMIT 1)
            ORDER BY avg_score DESC
            """
        )
        rows = cur.fetchall()
    return {"count": len(rows), "items": rows}


def _run_meta(run_id: int, cur) -> dict:
    cur.execute(
        "SELECT model_version, rules_version, started_at, published_at "
        "FROM antidoping.runs WHERE run_id = %s",
        (run_id,),
    )
    return cur.fetchone() or {}


@router.get("/{entity_name}")
def get_region_detail(entity_name: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM antidoping.v_regions_current WHERE entity_name = %s", (entity_name,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Регион не найден в текущем прогнозе")

        run_meta = _run_meta(row["run_id"], cur)
        model_version = run_meta.get("model_version")

        pred_row = None
        top_sports: list = []
        if row.get("matched_model_name") and model_version:
            cur.execute(
                """
                SELECT p.* FROM antidoping.predictions p
                JOIN antidoping.runs r ON r.run_id = p.run_id
                WHERE r.published_at IS NOT NULL AND r.model_version = %s AND p.region = %s
                ORDER BY r.published_at DESC LIMIT 1
                """,
                (model_version, row["matched_model_name"]),
            )
            pred_row = cur.fetchone()

            cur.execute(
                """
                SELECT p.sport, p.zone, p.proba, p.reason
                FROM antidoping.predictions p
                JOIN antidoping.runs r ON r.run_id = p.run_id
                WHERE r.published_at IS NOT NULL AND r.model_version = %s AND p.region = %s
                ORDER BY r.published_at DESC,
                         CASE p.zone WHEN 'RED' THEN 0 WHEN 'ORANGE' THEN 1
                                     WHEN 'GREEN' THEN 2 ELSE 3 END,
                         p.proba DESC NULLS LAST
                LIMIT 5
                """,
                (model_version, row["matched_model_name"]),
            )
            top_sports = cur.fetchall()

        cur.execute(
            """SELECT match_type, confidence FROM antidoping.matching_audit
               WHERE run_id = %s AND kind = 'region' AND rating_name = %s
               ORDER BY audit_id DESC LIMIT 1""",
            (row["run_id"], entity_name),
        )
        match = cur.fetchone()

    return {
        **row,
        "facts": build_facts(pred_row, row["zone"]),
        "top_sports": top_sports,
        # Контракт АД-Монитора (ad_monitor_prompt_v15.md) не содержит поля
        # «регион» в записях — точечный новостной контекст по региону
        # физически негде взять (в отличие от ОСФ, где flags.sport есть).
        # Пусто, а не выдумано — честно, а не подделка функциональности.
        "monitor_feed": [],
        "monitor_feed_note": "АД-Монитор не привязывает новости к региону — контекст доступен только по видам спорта",
        "match_type": match["match_type"] if match else None,
        "match_confidence": match["confidence"] if match else None,
        "snapshot": {
            "model_version": model_version,
            "rules_version": run_meta.get("rules_version"),
            "computed_at": run_meta.get("published_at") or run_meta.get("started_at"),
        },
    }
