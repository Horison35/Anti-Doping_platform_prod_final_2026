# -*- coding: utf-8 -*-
"""Корень репозитория -> sys.path, чтобы `import siar.rules` работал из pytest.

Плюс фикстуры для интеграционных тестов API (tests/test_api.py): поднимают
одноразовый Postgres в Docker для сессии тестов и не трогают dev/prod базу
из .env. Тесты, требующие БД, пропускаются (skip, не fail), если Docker
недоступен в окружении — чтобы юнит-тесты siar/rules.py (test_rules.py)
работали где угодно без Docker, как и раньше.
"""
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_dsn():
    """DSN одноразового Postgres 16 с применённой db/ddl.sql. Живёт всю сессию тестов."""
    if not _docker_available():
        pytest.skip("Docker недоступен — интеграционные тесты API/БД пропущены")

    name = f"adp_test_{uuid.uuid4().hex[:8]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--name", name,
            "-e", "POSTGRES_USER=antidoping",
            "-e", "POSTGRES_PASSWORD=test",
            "-e", "POSTGRES_DB=antidoping",
            "-p", f"{port}:5432",
            "postgres:16-alpine",
        ],
        check=True, capture_output=True,
    )
    dsn = f"postgresql://antidoping:test@localhost:{port}/antidoping"
    try:
        for _ in range(60):
            r = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "antidoping", "-d", "antidoping"],
                capture_output=True,
            )
            if r.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Postgres в контейнере не поднялся за 60с")

        subprocess.run(
            ["docker", "cp", str(ROOT / "db" / "ddl.sql"), f"{name}:/ddl.sql"], check=True
        )
        subprocess.run(
            ["docker", "exec", name, "psql", "-U", "antidoping", "-d", "antidoping",
             "-f", "/ddl.sql", "-v", "ON_ERROR_STOP=1"],
            check=True, capture_output=True,
        )
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="session")
def api_app(pg_dsn):
    """FastAPI app с окружением, указывающим на одноразовую тестовую БД."""
    os.environ["DATABASE_URL"] = pg_dsn
    os.environ["APP_PASSWORD"] = "test-only-password"
    os.environ["SESSION_SECRET"] = "test-only-session-secret"
    os.environ["COOKIE_SECURE"] = "false"

    from api import config as api_config
    api_config.DATABASE_URL = pg_dsn
    api_config.APP_PASSWORD = "test-only-password"
    api_config.COOKIE_SECURE = False

    from api.main import app
    return app
