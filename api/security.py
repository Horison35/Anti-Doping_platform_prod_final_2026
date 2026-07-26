# -*- coding: utf-8 -*-
"""api/security.py — единый пароль на вход (без логинов, без пользователей).

Одна дверь на всю платформу: пароль сверяется с APP_PASSWORD из .env, при
успехе выдаётся подписанная (itsdangerous) сессионная кука httpOnly. Никаких
учётных записей, имён пользователей или ролей на этом уровне — по ТЗ
«доступ по паролю, без логинов». Роли доступа (LOGIC.md §7) — отдельная,
явно не решённая на этом этапе задача, см. README/DEPLOY.

Защита общего пароля от подбора — простой лимитер попыток по IP в памяти
процесса (порог/окно — api/config.py). Это не замена HTTPS/файрвола, а
разумный минимум для «одного пароля на всех».
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Cookie, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

SESSION_COOKIE = "adp_session"

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="adp-session-v1")

# IP -> список меток времени неудачных попыток (память процесса; для одного
# инстанса API этого достаточно — при желании вынести в Redis при масштабировании).
_failed_attempts: dict[str, list[float]] = defaultdict(list)


def issue_session_token() -> str:
    return _serializer.dumps({"ok": True})


def verify_session_token(token: str) -> bool:
    try:
        _serializer.loads(token, max_age=config.SESSION_MAX_AGE_DAYS * 86400)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_not_locked_out(request: Request) -> None:
    ip = _client_ip(request)
    now = time.time()
    window_start = now - config.LOGIN_LOCKOUT_SECONDS
    attempts = [t for t in _failed_attempts[ip] if t >= window_start]
    _failed_attempts[ip] = attempts
    if len(attempts) >= config.LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток входа. Повторите через "
                   f"{config.LOGIN_LOCKOUT_SECONDS // 60} мин.",
        )


def register_failed_attempt(request: Request) -> None:
    ip = _client_ip(request)
    _failed_attempts[ip].append(time.time())


def clear_attempts(request: Request) -> None:
    ip = _client_ip(request)
    _failed_attempts.pop(ip, None)


def require_session(adp_session: str | None = Cookie(default=None)) -> None:
    """FastAPI-зависимость: подключается ко всем роутерам, кроме auth/health."""
    if not adp_session or not verify_session_token(adp_session):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Требуется вход по паролю платформы",
        )
