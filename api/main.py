# -*- coding: utf-8 -*-
"""api/main.py — FastAPI-приложение, контракт dashboard.v1 (STRUCTURE.md, СЛОЙ 4).

Запуск (см. DEPLOY.md):
    uvicorn api.main:app --host 0.0.0.0 --port 8000

Архитектурный инвариант проекта («модель ранжирует, код решает, LLM только
собирает и резюмирует») не нарушается ни одним эндпоинтом здесь: все числа
и формулировки читаются из БД такими, какими их посчитал siar/rules.evaluate()
при загрузке прогона — этот слой их не пересчитывает и не переформулирует.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .db import close_pool
from .routers import auth, catalog, export, feedback, gaps, grid, health, history, meta, monitor, osf, regions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("antidoping.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close_pool()


app = FastAPI(
    title="Антидопинговая платформа — API",
    description="Контракт dashboard.v1: приоритеты ОСФ/регионов, история, АД-Монитор, выгрузки.",
    version="1.0.0",
    lifespan=lifespan,
)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Общая обработка ошибок: клиенту — нейтральное сообщение, в лог — только
    # тип/текст исключения без тела запроса (в теле запросов платформы нет
    # ФИО спортсменов по построению — БД их не хранит, — но правило общее:
    # не логировать сырые тела запросов вообще).
    logger.exception("Необработанная ошибка на %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(osf.router)
app.include_router(regions.router)
app.include_router(history.router)
app.include_router(monitor.router)
app.include_router(grid.router)
app.include_router(gaps.router)
app.include_router(export.router)
app.include_router(feedback.router)
app.include_router(meta.router)
