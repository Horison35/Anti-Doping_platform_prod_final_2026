# -*- coding: utf-8 -*-
"""api/routers/feedback.py — форма пожеланий.

Только запись в БД (дата + раздел + текст). Ни один эндпоинт платформы не
читает эту таблицу обратно — комментарии не видны никому, включая автора
(ТЗ: «не отображаются в интерфейсе никому»). Читает только разработчик
напрямую из БД (psql/DBeaver), в API этого пути нет вообще.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..db import get_cursor
from ..security import require_session

router = APIRouter(
    prefix="/api/v1/feedback", tags=["feedback"], dependencies=[Depends(require_session)]
)


class FeedbackRequest(BaseModel):
    section: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_feedback(body: FeedbackRequest):
    section = body.section.strip()
    message = body.message.strip()
    if not section or not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Раздел и текст обязательны")
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO antidoping.feedback (section, message) VALUES (%s, %s)",
            (section, message),
        )
    return {"ok": True, "message": "Спасибо, Ваш отзыв записан и передан разработчику!"}
