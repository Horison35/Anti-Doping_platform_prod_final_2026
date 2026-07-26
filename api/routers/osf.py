# -*- coding: utf-8 -*-
"""api/routers/osf.py — контракт dashboard.v1: связки ОСФ (СЛОЙ 4).

Данные — только из БД (views v_osf_current, predictions, v_monitor_signals);
ни одно число и ни одна фраза здесь не порождаются заново — они уже посчитаны
siar/rules.evaluate() при загрузке прогона (db/loaders/load_siar_run.py).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import get_cursor
from ..facts import build_facts
from ..security import require_session

router = APIRouter(prefix="/api/v1/osf", tags=["osf"], dependencies=[Depends(require_session)])


@router.get("/summary")
def get_summary():
    """Для «Обзора» (персона руководителя): счётчики по приоритетам, текущий
    прогон vs предыдущий — «стало лучше/хуже» видно без единого клика."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT run_id FROM antidoping.runs
            WHERE published_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM antidoping.quadrant_results q
                          WHERE q.run_id = runs.run_id AND q.kind = 'osf')
            ORDER BY published_at DESC LIMIT 2
            """
        )
        run_ids = [r["run_id"] for r in cur.fetchall()]
        if not run_ids:
            return {"available": False}

        def counts(run_id: int) -> dict:
            cur.execute(
                "SELECT priority, count(*) AS n FROM antidoping.quadrant_results "
                "WHERE run_id = %s AND kind = 'osf' GROUP BY priority",
                (run_id,),
            )
            by_p = {1: 0, 2: 0, 3: 0, 4: 0}
            for row in cur.fetchall():
                by_p[row["priority"]] = row["n"]
            return by_p

        current = counts(run_ids[0])
        previous = counts(run_ids[1]) if len(run_ids) > 1 else None

        cur.execute(
            "SELECT entity_name, zone, rating_score, justification FROM antidoping.quadrant_results "
            "WHERE run_id = %s AND kind = 'osf' AND priority = 1 "
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
def list_osf(
    zone: Optional[str] = Query(None, description="RED | ORANGE | GREEN | NO_DATA"),
    priority: Optional[int] = Query(None, ge=1, le=4),
    limit: Optional[int] = Query(None, description="Топ-N; без параметра — все записи"),
):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM antidoping.v_osf_current ORDER BY priority, risk_rank NULLS LAST")
        rows = cur.fetchall()

    if zone:
        rows = [r for r in rows if r["zone"] == zone.upper()]
    if priority:
        rows = [r for r in rows if r["priority"] == priority]
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return {"total": total, "returned": len(rows), "items": rows}


def _run_meta(run_id: int, cur) -> dict:
    cur.execute(
        "SELECT model_version, rules_version, started_at, published_at "
        "FROM antidoping.runs WHERE run_id = %s",
        (run_id,),
    )
    return cur.fetchone() or {}


@router.get("/{entity_name}")
def get_osf_detail(entity_name: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM antidoping.v_osf_current WHERE entity_name = %s", (entity_name,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Связка не найдена в текущем прогнозе")

        run_meta = _run_meta(row["run_id"], cur)
        model_version = run_meta.get("model_version")

        pred_row = None
        top_regions: list = []
        if row.get("matched_model_name") and model_version:
            cur.execute(
                """
                SELECT p.* FROM antidoping.predictions p
                JOIN antidoping.runs r ON r.run_id = p.run_id
                WHERE r.published_at IS NOT NULL AND r.model_version = %s AND p.sport = %s
                ORDER BY r.published_at DESC LIMIT 1
                """,
                (model_version, row["matched_model_name"]),
            )
            pred_row = cur.fetchone()

            cur.execute(
                """
                SELECT p.region, p.zone, p.proba, p.reason
                FROM antidoping.predictions p
                JOIN antidoping.runs r ON r.run_id = p.run_id
                WHERE r.published_at IS NOT NULL AND r.model_version = %s AND p.sport = %s
                ORDER BY r.published_at DESC,
                         CASE p.zone WHEN 'RED' THEN 0 WHEN 'ORANGE' THEN 1
                                     WHEN 'GREEN' THEN 2 ELSE 3 END,
                         p.proba DESC NULLS LAST
                LIMIT 5
                """,
                (model_version, row["matched_model_name"]),
            )
            top_regions = cur.fetchall()

        # lower() с обеих сторон: АД-Монитор пишет вид спорта как обычное слово
        # («хоккей»), а модель — в своей регистровой форме («Хоккей»); без
        # регистронезависимого сравнения совпадающие по смыслу связки не находят
        # друг друга, и реальные сигналы молча теряются (не попадают в карточку).
        cur.execute(
            "SELECT signals_30d, signals_90d FROM antidoping.v_monitor_signals WHERE lower(sport) = lower(%s)",
            (row.get("matched_model_name") or entity_name,),
        )
        sig = cur.fetchone() or {"signals_30d": 0, "signals_90d": 0}

        # Точечный новостной контекст (ТЗ, п. 3б): подтверждённые публикации
        # АД-Монитора по этому же виду спорта — не только счётчик сигналов.
        cur.execute(
            """SELECT title, summary, source_name, source_url, event_date, scope
               FROM antidoping.flags
               WHERE confirmed AND lower(sport) = lower(%s)
               ORDER BY event_date DESC NULLS LAST, created_at DESC
               LIMIT 5""",
            (row.get("matched_model_name") or entity_name,),
        )
        monitor_feed = cur.fetchall()

        cur.execute(
            """SELECT match_type, confidence FROM antidoping.matching_audit
               WHERE run_id = %s AND kind = 'osf' AND rating_name = %s
               ORDER BY audit_id DESC LIMIT 1""",
            (row["run_id"], entity_name),
        )
        match = cur.fetchone()

    return {
        **row,
        "facts": build_facts(pred_row, row["zone"]),
        "monitor_signals_30d": sig["signals_30d"] or 0,
        "monitor_signals_90d": sig["signals_90d"] or 0,
        "monitor_feed": monitor_feed,
        "top_regions": top_regions,
        "match_type": match["match_type"] if match else None,
        "match_confidence": match["confidence"] if match else None,
        "snapshot": {
            "model_version": model_version,
            "rules_version": run_meta.get("rules_version"),
            "computed_at": run_meta.get("published_at") or run_meta.get("started_at"),
        },
    }
