# -*- coding: utf-8 -*-
"""api/config.py — конфигурация FastAPI-сервиса из окружения/.env.

Секреты только из .env (STRUCTURE.md, правило 6) — здесь нет ни одного
хардкода пароля/строки подключения. Отсутствие обязательного значения —
громкая ошибка при старте процесса, а не тихий дефолт на проде.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(root: Path) -> None:
    """Мини-.env без внешних зависимостей (тот же приём, что в db/loaders/*)."""
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} не задан: заполните .env по образцу .env.example (переменная обязательна)"
        )
    return value


DATABASE_URL = _require("DATABASE_URL")
APP_PASSWORD = _require("APP_PASSWORD")
SESSION_SECRET = _require("SESSION_SECRET")

SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "30"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").strip().lower() == "true"
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# Порог блокировки входа по паролю (защита общего пароля от подбора; см. api/security.py)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "300"))

REPORTS_DIR = ROOT / "reports"
PREDICTIONS_DIR = ROOT / "predictions"
