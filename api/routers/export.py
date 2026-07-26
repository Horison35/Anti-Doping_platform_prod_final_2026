# -*- coding: utf-8 -*-
"""api/routers/export.py — раздел выгрузки: Excel/CSV напрямую из БД.

Требование ТЗ: полные таблицы без предварительной фильтрации, доступные
без прохода по интерактивным экранам, содержимое совпадает с тем, что
показано в интерфейсе (тот же источник — те же view/таблицы, что и /osf,
/regions, /history).
"""
from __future__ import annotations

import io
from typing import Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..db import get_cursor
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/export", tags=["export"], dependencies=[Depends(require_session)]
)

_MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MEDIA_CSV = "text/csv; charset=utf-8"


def _content_disposition(filename_stem: str, ext: str) -> str:
    # Content-Disposition обязан быть latin-1 — имена файлов здесь кириллические
    # (человекочитаемые для пользователя), поэтому ASCII-фолбэк + RFC 5987
    # filename* с UTF-8 percent-encoding (открывается в любом браузере).
    ascii_fallback = f"export.{ext}"
    utf8_name = quote(f"{filename_stem}.{ext}")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_name}"


def _respond(df: pd.DataFrame, fmt: str, filename_stem: str) -> Response:
    if fmt == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return Response(
            content=buf.getvalue(),
            media_type=_MEDIA_CSV,
            headers={"Content-Disposition": _content_disposition(filename_stem, "csv")},
        )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name=filename_stem[:31])
    return Response(
        content=buf.getvalue(),
        media_type=_MEDIA_XLSX,
        headers={"Content-Disposition": _content_disposition(filename_stem, "xlsx")},
    )


def _fmt_param(fmt: str) -> str:
    if fmt not in ("xlsx", "csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "fmt должен быть xlsx или csv")
    return fmt


@router.get("/osf.{fmt}")
def export_osf(fmt: str):
    fmt = _fmt_param(fmt)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM antidoping.v_osf_current ORDER BY priority, risk_rank")
        rows = cur.fetchall()
    return _respond(pd.DataFrame(rows), fmt, "приоритеты_осф")


@router.get("/regions.{fmt}")
def export_regions(fmt: str):
    fmt = _fmt_param(fmt)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM antidoping.v_regions_current ORDER BY priority, risk_rank")
        rows = cur.fetchall()
    return _respond(pd.DataFrame(rows), fmt, "приоритеты_регионов")


@router.get("/unmatched.{fmt}")
def export_unmatched(fmt: str, kind: str = Query(..., pattern="^(osf|region)$")):
    fmt = _fmt_param(fmt)
    with get_cursor() as cur:
        cur.execute(
            """SELECT * FROM antidoping.unmatched
               WHERE kind = %s AND run_id = (
                   SELECT max(run_id) FROM antidoping.runs
                   WHERE published_at IS NOT NULL AND run_kind = %s
               )""",
            (kind, f"siar_{kind}"),
        )
        rows = cur.fetchall()
    return _respond(pd.DataFrame(rows), fmt, f"не_сопоставлено_{kind}")


@router.get("/audit.{fmt}")
def export_audit(fmt: str, kind: str = Query(..., pattern="^(osf|region)$")):
    fmt = _fmt_param(fmt)
    with get_cursor() as cur:
        cur.execute(
            """SELECT * FROM antidoping.matching_audit
               WHERE kind = %s AND run_id = (
                   SELECT max(run_id) FROM antidoping.runs
                   WHERE published_at IS NOT NULL AND run_kind = %s
               )""",
            (kind, f"siar_{kind}"),
        )
        rows = cur.fetchall()
    return _respond(pd.DataFrame(rows), fmt, f"аудит_матчинга_{kind}")


@router.get("/history.{fmt}")
def export_history(
    fmt: str,
    kind: str = Query(..., pattern="^(osf|region)$"),
    entity_name: Optional[str] = None,
):
    fmt = _fmt_param(fmt)
    clauses, params = ["kind = %(kind)s"], {"kind": kind}
    if entity_name:
        clauses.append("entity_name = %(entity_name)s")
        params["entity_name"] = entity_name
    where = " AND ".join(clauses)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM antidoping.v_quadrant_history WHERE {where} "
            f"ORDER BY entity_name, run_published_at",
            params,
        )
        rows = cur.fetchall()
    return _respond(pd.DataFrame(rows), fmt, "история_рисковости")
