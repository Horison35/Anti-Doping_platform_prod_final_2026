# -*- coding: utf-8 -*-
"""api/routers/monitor.py — витрина АД-Монитора: общий дайджест + точечный контекст.

Графическая аналитика считается кодом по проверенным записям flags (НЕ по
самоотчёту LLM о собственных KPI) — тот же принцип «код считает, LLM собирает»
(LOGIC.md §1), применённый и к статистике дайджеста, а не только к SIAR.
Письменная аналитика — отдельно посчитанный текст из digest_narrative
(monitor/summarize_digest.py), подставляется как есть, без домысливания.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..db import get_cursor
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/monitor", tags=["monitor"], dependencies=[Depends(require_session)]
)

_SCOPE_FILTER_SQL = "AND scope = %(scope)s"


@router.get("/digest")
def get_digest(scope: str = Query("both", pattern="^(rf|intl|both)$")):
    """Последний выпуск АД-Монитора: KPI, распределения, таймлайн, письменная аналитика."""
    with get_cursor() as cur:
        cur.execute("SELECT max(monitor_date) AS d FROM antidoping.flags")
        latest = (cur.fetchone() or {}).get("d")
        if latest is None:
            return {"available": False, "message": "Дайджест ещё не поступал"}

        scope_sql = "" if scope == "both" else _SCOPE_FILTER_SQL
        params = {"monitor_date": latest, "scope": scope}

        cur.execute(
            f"""SELECT category, count(*) AS n FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s AND confirmed {scope_sql}
                GROUP BY category ORDER BY n DESC""",
            params,
        )
        by_category = cur.fetchall()

        cur.execute(
            f"""SELECT coalesce(source_name, 'н/д') AS source_name, count(*) AS n
                FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s AND confirmed {scope_sql}
                GROUP BY source_name ORDER BY n DESC LIMIT 10""",
            params,
        )
        by_source = cur.fetchall()

        cur.execute(
            f"""SELECT coalesce(country, 'н/д') AS country, count(*) AS n
                FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s AND confirmed {scope_sql}
                GROUP BY country ORDER BY n DESC LIMIT 12""",
            params,
        )
        by_country = cur.fetchall()

        cur.execute(
            f"""SELECT coalesce(sport, 'н/д') AS sport, count(*) AS n
                FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s AND confirmed {scope_sql}
                  AND sport IS NOT NULL
                GROUP BY sport ORDER BY n DESC LIMIT 12""",
            params,
        )
        by_sport = cur.fetchall()

        cur.execute(
            """SELECT monitor_date,
                      count(*) FILTER (WHERE confirmed)     AS confirmed_n,
                      count(*) FILTER (WHERE NOT confirmed) AS unverified_n
               FROM antidoping.flags
               GROUP BY monitor_date ORDER BY monitor_date DESC LIMIT 12"""
        )
        timeline = list(reversed(cur.fetchall()))

        cur.execute(
            f"""SELECT count(*) AS n FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s {scope_sql} AND NOT confirmed""",
            params,
        )
        unverified_count = cur.fetchone()["n"]

        cur.execute(
            f"""SELECT count(*) AS n FROM antidoping.flags
                WHERE monitor_date = %(monitor_date)s {scope_sql}
                  AND NOT confirmed AND NOT url_verified""",
            params,
        )
        source_unavailable_count = cur.fetchone()["n"]

        narratives: dict[str, Optional[str]] = {}
        narrative_dates: dict[str, Optional[str]] = {}
        for sc in ("rf", "intl"):
            cur.execute(
                """SELECT narrative, generated_at FROM antidoping.digest_narrative
                   WHERE monitor_date = %s AND scope = %s""",
                (latest, sc),
            )
            row = cur.fetchone()
            narratives[sc] = row["narrative"] if row else None
            narrative_dates[sc] = str(row["generated_at"]) if row else None

    return {
        "available": True,
        "monitor_date": str(latest),
        "scope": scope,
        "by_category": by_category,
        "by_source": by_source,
        "by_country": by_country,
        "by_sport": by_sport,
        "timeline": timeline,
        "unverified_count": unverified_count,
        "source_unavailable_count": source_unavailable_count,
        "narrative_rf": narratives["rf"],
        "narrative_intl": narratives["intl"],
        "narrative_generated_at": narrative_dates,
    }


@router.get("/feed")
def get_feed(
    scope: Optional[str] = Query(None, pattern="^(rf|intl)$"),
    category: Optional[str] = None,
    limit: Optional[int] = Query(None, description="Топ-N; без параметра — все записи"),
):
    """Верифицированная лента (v_flags_public) — для «Ленты мониторинга»."""
    clauses = ["1=1"]
    params: dict = {}
    if scope:
        clauses.append("scope = %(scope)s")
        params["scope"] = scope
    if category:
        clauses.append("category = %(category)s")
        params["category"] = category
    where = " AND ".join(clauses)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM antidoping.v_flags_public WHERE {where} "
            f"ORDER BY monitor_date DESC, event_date DESC NULLS LAST",
            params,
        )
        rows = cur.fetchall()
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return {"total": total, "returned": len(rows), "items": rows}


@router.get("/unverified")
def get_unverified(limit: Optional[int] = Query(None)):
    """Честная подача пробелов: неподтверждённые записи и недоступные источники."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT flag_id, monitor_date, event_date, category, scope,
                      source_name, title, summary, source_url,
                      url_verified, expires_at, created_at
               FROM antidoping.flags
               WHERE NOT confirmed
               ORDER BY monitor_date DESC"""
        )
        rows = cur.fetchall()
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return {"total": total, "returned": len(rows), "items": rows}


@router.get("/signals/{sport}")
def get_signals(sport: str):
    """Доп-критерий §3: «Сигналы мониторинга: N за 30/90 дней» по виду спорта."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT signals_30d, signals_90d FROM antidoping.v_monitor_signals WHERE lower(sport) = lower(%s)",
            (sport,),
        )
        row = cur.fetchone()
    return row or {"signals_30d": 0, "signals_90d": 0}
