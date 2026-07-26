# -*- coding: utf-8 -*-
"""api/routers/auth.py — единый вход по паролю (без логинов)."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel

from .. import config
from ..security import (
    SESSION_COOKIE,
    check_not_locked_out,
    clear_attempts,
    issue_session_token,
    register_failed_attempt,
    verify_session_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    check_not_locked_out(request)
    if body.password != config.APP_PASSWORD:
        register_failed_attempt(request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный пароль")

    clear_attempts(request)
    token = issue_session_token()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=config.SESSION_MAX_AGE_DAYS * 86400,
        path="/",
    )
    return {"ok": True}


@router.get("/status")
def status_check(adp_session: str | None = Cookie(default=None)):
    return {"authenticated": bool(adp_session and verify_session_token(adp_session))}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
