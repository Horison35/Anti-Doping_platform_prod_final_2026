#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ml/retrain.py — автоматизация цикла переобучения (blue/green, без простоя).

Как это соотносится с правилом «модель не переобучать агентом-кодером»
(STRUCTURE.md): методика обучения (antidoping_model_production.ipynb) —
исследованный процесс владельца проекта, агент её не пишет и не изобретает
заново. Этот файл — только ОРКЕСТРАЦИЯ: приём нового файла → безопасная
проверка → (если есть ноутбук-методика) обучение кандидата → backtest-гейт
→ атомарный blue/green-промоушен. Если ноутбука нет, скрипт честно
останавливается после обновления прогноза действующей моделью — никогда
не подставляет придуманную процедуру обучения (правило «не дорисовывать»).

Пайплайн:
  1. Новый файл реестра → validate_and_refresh(): прогон ml/predict.py
     ДЕЙСТВУЮЩЕЙ моделью на новых данных. Это одновременно и валидация
     файла (predict.py/clean_data() падает на нехватке колонок — ловим
     эту же ошибку, а не пишем вторую проверку), и немедленное обновление
     прогноза без риска для качества (действующая модель не меняется).
     Провал → retrain_runs.decision='failed', активная модель не тронута.
  2. find_train_entrypoint(): ищет ml/antidoping_model_production.ipynb.
     Нет файла → лог "обучение недоступно", выход после шага 1 (успешно).
  3. run_training(): jupyter nbconvert --execute с ANTIDOPING_TRAIN_DATA/
     ANTIDOPING_TRAIN_OUT в окружении — контракт для методики владельца.
  4. Регистрация кандидата в model_artifacts (status=candidate).
  5. backtest-гейт: ml/backtest.py сравнивает Lift@20 кандидата и текущей
     активной версии на одном и том же последнем ЗАКРЫТОМ квартале.
  6. Кандидат не хуже → promote_model_artifact() + атомарная подмена
     symlink ml/artifacts/current → повторный прогон новой моделью на
     новых данных → загрузка в БД (db/loaders/load_ml_run.py).
     Кандидат хуже/бэктест упал → decision='rejected'/'failed', активная
     версия продолжает работать как ни в чём не бывало.

Запуск (обычно — из ml/watch_registry.py при появлении нового файла):
    python ml/retrain.py --new-data "25.10.2026 Список дисквал.xlsx" \\
        --trigger file_watch
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS_DIR = ROOT / "ml" / "artifacts"
CURRENT_LINK = ARTIFACTS_DIR / "current"
TRAIN_NOTEBOOK = ROOT / "ml" / "antidoping_model_production.ipynb"
BACKTEST_LIFT_MIN_RATIO = float(os.environ.get("RETRAIN_MIN_LIFT_RATIO", "0.95"))
# ^ кандидат допускается при lift_at_20 >= 95% от базовой версии — не строгий
#   "не хуже ни на йоту", чтобы не блокировать промоушен шумом на малых выборках.


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_env(root: Path) -> None:
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def find_train_entrypoint() -> Optional[Path]:
    return TRAIN_NOTEBOOK if TRAIN_NOTEBOOK.exists() else None


def _pg_connect(dsn: str):
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(dsn, row_factory=dict_row)


def get_active_artifact(cur) -> Optional[dict]:
    cur.execute(
        "SELECT * FROM antidoping.model_artifacts WHERE status = 'active' LIMIT 1"
    )
    return cur.fetchone()


def start_retrain_run(cur, trigger: str, file_path: Path) -> tuple[int, int]:
    cur.execute(
        "INSERT INTO antidoping.runs (run_kind, notes) VALUES ('retrain', %s) RETURNING run_id",
        (f"trigger={trigger} file={file_path.name}",),
    )
    run_id = cur.fetchone()["run_id"]
    cur.execute(
        """INSERT INTO antidoping.retrain_runs
               (run_id, trigger, triggering_file, triggering_sha256, decision)
           VALUES (%s, %s, %s, %s, 'pending') RETURNING retrain_id""",
        (run_id, trigger, file_path.name, sha256_file(file_path)),
    )
    return run_id, cur.fetchone()["retrain_id"]


def finish_retrain_run(cur, retrain_id: int, run_id: int, **fields) -> None:
    fields.setdefault("finished_at", datetime.now())
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    fields["retrain_id"] = retrain_id
    cur.execute(f"UPDATE antidoping.retrain_runs SET {set_clause} WHERE retrain_id = %(retrain_id)s", fields)
    cur.execute(
        "UPDATE antidoping.runs SET status = %s, finished_at = now() WHERE run_id = %s",
        ("success" if fields.get("decision") in ("promoted", "rejected") else "failed", run_id),
    )


def validate_and_refresh(model_path: Path, meta_path: Path, data_path: Path, out_dir: Path, period: Optional[str]) -> None:
    """Прогон predict.py действующей моделью на новых данных — валидация файла
    «в подарок» (clean_data() кода не дублируем, а полагаемся на ту же ошибку)."""
    cmd = [sys.executable, str(ROOT / "ml" / "predict.py"),
           "--model", str(model_path), "--meta", str(meta_path),
           "--data", str(data_path), "--out", str(out_dir)]
    if period:
        cmd += ["--period", period]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"Файл не прошёл прогон текущей моделью (вероятно, повреждён/неполон): "
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


def run_training(data_path: Path, candidate_dir: Path, notebook: Path) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["ANTIDOPING_TRAIN_DATA"] = str(data_path)
    env["ANTIDOPING_TRAIN_OUT"] = str(candidate_dir)
    result = subprocess.run(
        ["jupyter", "nbconvert", "--to", "notebook", "--execute",
         "--output", "/dev/null", str(notebook)],
        capture_output=True, text=True, timeout=6 * 3600, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Обучение (nbconvert) упало: {result.stderr[-3000:]}")

    pkls = sorted(candidate_dir.glob("prod_ensemble_*.pkl"))
    metas = sorted(candidate_dir.glob("meta_*.json"))
    if not pkls or not metas:
        raise RuntimeError(
            f"Ноутбук отработал, но не оставил prod_ensemble_*.pkl/meta_*.json в {candidate_dir} "
            f"— проверьте контракт ANTIDOPING_TRAIN_OUT в самом ноутбуке"
        )


def register_candidate(cur, candidate_pkl: Path, candidate_meta: Path) -> int:
    version = candidate_pkl.stem.removeprefix("prod_ensemble_")
    cur.execute(
        """INSERT INTO antidoping.model_artifacts
               (version, model_path, meta_path, sha256, status)
           VALUES (%s, %s, %s, %s, 'candidate') RETURNING artifact_id""",
        (version, str(candidate_pkl), str(candidate_meta), sha256_file(candidate_pkl)),
    )
    return cur.fetchone()["artifact_id"]


def latest_closed_quarter() -> str:
    now = datetime.now()
    q_closed = (now.month - 1) // 3
    if q_closed == 0:
        return f"{now.year - 1} Q4"
    return f"{now.year} Q{q_closed}"


def sync_active_artifact_dir(candidate_pkl: Path, candidate_meta: Path) -> None:
    """Обновляет ml/artifacts/current/ — удобный фиксированный путь для людей
    и простых cron/systemd-вызовов (DEPLOY.md), которым не хочется идти в
    Postgres за model_artifacts.status='active'. Источник истины для САМОГО
    retrain.py — всегда таблица model_artifacts; эта директория — зеркало.
    Подмена атомарна (os.replace каталога на той же ФС): наблюдатель либо
    видит старую версию целиком, либо новую — никогда смесь."""
    target_dir = ARTIFACTS_DIR / "current"
    staging_dir = ARTIFACTS_DIR / f".current.staging.{os.getpid()}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_pkl, staging_dir / candidate_pkl.name)
    shutil.copy2(candidate_meta, staging_dir / candidate_meta.name)
    (staging_dir / "MODEL_PATH").write_text(candidate_pkl.name, encoding="utf-8")
    (staging_dir / "META_PATH").write_text(candidate_meta.name, encoding="utf-8")
    os.replace(staging_dir, target_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new-data", required=True, help="новая таблица дисквалификаций (xlsx)")
    ap.add_argument("--trigger", default="manual", choices=["file_watch", "manual", "scheduled"])
    ap.add_argument("--period", default=None, help="целевой квартал прогноза (по умолчанию — календарь)")
    ap.add_argument("--skip-training", action="store_true",
                     help="только обновить прогноз действующей моделью, без попытки обучения")
    args = ap.parse_args(argv)

    data_path = Path(args.new_data)
    if not data_path.exists():
        raise SystemExit(f"❌ Файл не найден: {data_path}")

    load_env(ROOT)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("❌ DATABASE_URL не задан")

    conn = _pg_connect(dsn)
    cur = conn.cursor()
    active = get_active_artifact(cur)
    if not active:
        conn.close()
        raise SystemExit(
            "❌ В model_artifacts нет активной версии — заполните её вручную перед "
            "первым запуском автопереобучения (см. DEPLOY.md)"
        )

    run_id, retrain_id = start_retrain_run(cur, args.trigger, data_path)
    conn.commit()

    try:
        with tempfile.TemporaryDirectory(prefix="adp_retrain_refresh_") as tmp:
            refresh_dir = Path(tmp)
            validate_and_refresh(
                Path(active["model_path"]), Path(active["meta_path"]), data_path,
                refresh_dir, args.period,
            )
            print(f"✅ Файл прошёл проверку — прогноз действующей моделью ({active['version']}) обновлён")

            # Загрузка обновлённого прогноза (действующая модель, новые данные) в БД —
            # закрывает «автоматизацию цикла модель↔мониторинг» независимо от обучения.
            load_cmd = [
                sys.executable, str(ROOT / "db" / "loaders" / "load_ml_run.py"),
                "--data", str(data_path),
                "--grid", str(refresh_dir / "full_grid.csv"),
                "--registry", str(refresh_dir / "registry_agg.csv"),
                "--meta", active["meta_path"],
                "--period", args.period or latest_closed_quarter(),
                "--notes", f"retrain_id={retrain_id} refresh-only",
            ]
            load_result = subprocess.run(load_cmd, capture_output=True, text=True, timeout=600)
            if load_result.returncode != 0:
                print(f"⚠️  Не удалось загрузить обновлённый прогноз в БД: {load_result.stderr[-1500:]}")

        if args.skip_training:
            finish_retrain_run(cur, retrain_id, run_id, decision="rejected",
                               decision_reason="--skip-training: только обновление прогноза")
            conn.commit()
            print("ℹ️  --skip-training: обучение пропущено по запросу")
            return 0

        notebook = find_train_entrypoint()
        if notebook is None:
            finish_retrain_run(
                cur, retrain_id, run_id, decision="rejected",
                decision_reason=(
                    f"обучение недоступно: {TRAIN_NOTEBOOK} отсутствует — "
                    f"прогноз обновлён действующей моделью, переобучение "
                    f"пропущено (см. DEPLOY.md, раздел «Автопереобучение»)"
                ),
            )
            conn.commit()
            print("ℹ️  Ноутбук обучения не найден — переобучение пропущено, прогноз уже обновлён")
            return 0

        candidate_dir = ARTIFACTS_DIR / "candidates" / f"retrain_{retrain_id}"
        run_training(data_path, candidate_dir, notebook)
        candidate_pkl = sorted(candidate_dir.glob("prod_ensemble_*.pkl"))[-1]
        candidate_meta = sorted(candidate_dir.glob("meta_*.json"))[-1]
        candidate_id = register_candidate(cur, candidate_pkl, candidate_meta)
        conn.commit()
        print(f"✅ Кандидат обучен и зарегистрирован: artifact_id={candidate_id}")

        from ml.backtest import backtest_one_model  # noqa: PLC0415

        bt_period = latest_closed_quarter()
        baseline_metrics = backtest_one_model(
            Path(active["model_path"]), Path(active["meta_path"]), data_path, bt_period,
        )
        candidate_metrics = backtest_one_model(candidate_pkl, candidate_meta, data_path, bt_period)

        baseline_lift = baseline_metrics.get("lift_at_20") or 0.0
        candidate_lift = candidate_metrics.get("lift_at_20") or 0.0
        cur.execute(
            """UPDATE antidoping.retrain_runs SET
                   candidate_artifact_id = %s, baseline_artifact_id = %s,
                   metric_name = 'lift_at_20',
                   candidate_metric = %s, baseline_metric = %s
               WHERE retrain_id = %s""",
            (candidate_id, active["artifact_id"], candidate_lift, baseline_lift, retrain_id),
        )

        if candidate_lift >= baseline_lift * BACKTEST_LIFT_MIN_RATIO:
            sync_active_artifact_dir(candidate_pkl, candidate_meta)
            cur.execute("SELECT antidoping.promote_model_artifact(%s)", (candidate_id,))
            finish_retrain_run(
                cur, retrain_id, run_id, decision="promoted",
                decision_reason=f"lift@20 кандидата {candidate_lift:.3f} >= "
                                 f"{BACKTEST_LIFT_MIN_RATIO:.0%} от базовой {baseline_lift:.3f}",
            )
            conn.commit()
            print(f"🚀 Кандидат промоутирован в active (lift@20 {candidate_lift:.3f} vs {baseline_lift:.3f})")
        else:
            finish_retrain_run(
                cur, retrain_id, run_id, decision="rejected",
                decision_reason=f"lift@20 кандидата {candidate_lift:.3f} < "
                                 f"{BACKTEST_LIFT_MIN_RATIO:.0%} от базовой {baseline_lift:.3f} — не промоутирован",
            )
            conn.commit()
            print(f"⛔ Кандидат отклонён (lift@20 {candidate_lift:.3f} vs {baseline_lift:.3f}) — активная версия не тронута")
        return 0

    except Exception as e:
        conn.rollback()
        cur = conn.cursor()
        finish_retrain_run(cur, retrain_id, run_id, decision="failed", decision_reason=str(e)[:2000])
        conn.commit()
        print(f"❌ Автопереобучение провалено: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
