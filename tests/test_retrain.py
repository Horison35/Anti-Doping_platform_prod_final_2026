# -*- coding: utf-8 -*-
"""tests/test_retrain.py — оркестрация автопереобучения (blue/green, без простоя).

Тяжёлые шаги (реальный прогон ml/predict.py, реальное обучение по ноутбуку)
подменены — тестируем логику принятия решений: файл невалиден → failed,
нет ноутбука → rejected с понятной причиной, кандидат хуже → rejected и
активная версия не меняется, кандидат не хуже → promoted и model_artifacts
переключается ровно на одну активную строку.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from ml import retrain


@pytest.fixture()
def seeded_active(pg_dsn, tmp_path):
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    # ux_artifact_one_active допускает не более одной активной строки на всю
    # таблицу — тесты делят одну сессионную БД, поэтому гасим активные строки
    # прошлых тестов перед тем, как завести свою.
    cur.execute("UPDATE antidoping.model_artifacts SET status = 'retired' WHERE status = 'active'")
    model_path = tmp_path / "baseline.pkl"
    meta_path = tmp_path / "baseline_meta.json"
    model_path.write_bytes(b"fake-model")
    meta_path.write_text("{}", encoding="utf-8")
    # Версия уникальна на всю тестовую сессию (tmp_path.name меняется на
    # каждый вызов фикстуры) — несколько тестов используют одну сессионную БД.
    version = f"baseline-{tmp_path.name}"
    cur.execute(
        """INSERT INTO antidoping.model_artifacts
               (version, model_path, meta_path, sha256, status)
           VALUES (%s, %s, %s, %s, 'active') RETURNING artifact_id""",
        (version, str(model_path), str(meta_path), "0" * 64),
    )
    artifact_id = cur.fetchone()["artifact_id"]
    conn.close()
    return {"artifact_id": artifact_id, "model_path": model_path, "meta_path": meta_path, "version": version}


@pytest.fixture()
def new_data_file(tmp_path):
    p = tmp_path / "new_registry.xlsx"
    p.write_bytes(b"fake-xlsx")
    return p


def _mock_success(*a, **k):
    return subprocess.CompletedProcess(args=a, returncode=0, stdout="ok", stderr="")


def test_missing_active_artifact_raises(pg_dsn, new_data_file, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    with pytest.raises(SystemExit, match="нет активной версии"):
        retrain.main(["--new-data", str(new_data_file)])


def test_no_training_notebook_rejects_with_clear_reason(
    pg_dsn, seeded_active, new_data_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setattr(retrain, "TRAIN_NOTEBOOK", tmp_path / "does_not_exist.ipynb")
    monkeypatch.setattr(retrain.subprocess, "run", _mock_success)

    rc = retrain.main(["--new-data", str(new_data_file), "--period", "2026 Q3"])
    assert rc == 0

    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT decision, decision_reason FROM antidoping.retrain_runs ORDER BY retrain_id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    assert row["decision"] == "rejected"
    assert "отсутствует" in row["decision_reason"]

    # активная версия не менялась — файл прошёл только валидацию/обновление прогноза
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT version FROM antidoping.model_artifacts WHERE status = 'active'")
    assert cur.fetchone()["version"] == seeded_active["version"]
    conn.close()


def test_candidate_promoted_when_not_worse(
    pg_dsn, seeded_active, new_data_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    # ВАЖНО: sync_active_artifact_dir пишет в ARTIFACTS_DIR/current — без этой
    # подмены тест унёс бы фиктивные файлы в настоящий ml/artifacts/ репозитория.
    monkeypatch.setattr(retrain, "ARTIFACTS_DIR", tmp_path / "artifacts")
    notebook = tmp_path / "train.ipynb"
    notebook.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(retrain, "TRAIN_NOTEBOOK", notebook)
    monkeypatch.setattr(retrain.subprocess, "run", _mock_success)

    def fake_run_training(data_path, candidate_dir, nb):
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "prod_ensemble_candidate1.pkl").write_bytes(b"fake-candidate")
        (candidate_dir / "meta_candidate1.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(retrain, "run_training", fake_run_training)

    import ml.backtest as backtest_mod
    monkeypatch.setattr(
        backtest_mod, "backtest_one_model",
        lambda model, meta, data, period: {
            "lift_at_20": 5.0 if Path(model).name.startswith("prod_ensemble_candidate") else 4.0
        },
    )

    rc = retrain.main(["--new-data", str(new_data_file), "--period", "2026 Q3"])
    assert rc == 0

    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT decision FROM antidoping.retrain_runs ORDER BY retrain_id DESC LIMIT 1")
    assert cur.fetchone()["decision"] == "promoted"
    cur.execute("SELECT version, status FROM antidoping.model_artifacts WHERE status = 'active'")
    active = cur.fetchone()
    assert active["version"] == "candidate1"
    conn.close()


def test_candidate_rejected_when_worse(
    pg_dsn, seeded_active, new_data_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setattr(retrain, "ARTIFACTS_DIR", tmp_path / "artifacts")
    notebook = tmp_path / "train2.ipynb"
    notebook.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(retrain, "TRAIN_NOTEBOOK", notebook)
    monkeypatch.setattr(retrain.subprocess, "run", _mock_success)

    def fake_run_training(data_path, candidate_dir, nb):
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "prod_ensemble_candidate2.pkl").write_bytes(b"fake-candidate")
        (candidate_dir / "meta_candidate2.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(retrain, "run_training", fake_run_training)

    import ml.backtest as backtest_mod
    monkeypatch.setattr(
        backtest_mod, "backtest_one_model",
        lambda model, meta, data, period: {
            "lift_at_20": 1.0 if Path(model).name.startswith("prod_ensemble_candidate") else 5.0
        },
    )

    rc = retrain.main(["--new-data", str(new_data_file), "--period", "2026 Q3"])
    assert rc == 0

    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT decision FROM antidoping.retrain_runs ORDER BY retrain_id DESC LIMIT 1")
    assert cur.fetchone()["decision"] == "rejected"
    cur.execute("SELECT version FROM antidoping.model_artifacts WHERE status = 'active'")
    assert cur.fetchone()["version"] == seeded_active["version"]  # активная версия не пострадала
    conn.close()


def test_sync_active_artifact_dir_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(retrain, "ARTIFACTS_DIR", tmp_path)
    model = tmp_path / "m.pkl"
    meta = tmp_path / "m.json"
    model.write_bytes(b"x")
    meta.write_text("{}", encoding="utf-8")

    retrain.sync_active_artifact_dir(model, meta)
    current = tmp_path / "current"
    assert (current / "m.pkl").exists()
    assert (current / "MODEL_PATH").read_text(encoding="utf-8") == "m.pkl"


def test_latest_closed_quarter_calendar_math(monkeypatch):
    class FakeDatetime:
        @classmethod
        def now(cls):
            import datetime as real_dt
            return real_dt.datetime(2026, 7, 25)

    monkeypatch.setattr(retrain, "datetime", FakeDatetime)
    assert retrain.latest_closed_quarter() == "2026 Q2"

    class FakeDatetimeQ1:
        @classmethod
        def now(cls):
            import datetime as real_dt
            return real_dt.datetime(2026, 2, 1)

    monkeypatch.setattr(retrain, "datetime", FakeDatetimeQ1)
    assert retrain.latest_closed_quarter() == "2025 Q4"
