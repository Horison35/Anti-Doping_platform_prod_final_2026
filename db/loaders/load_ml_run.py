# -*- coding: utf-8 -*-
"""load_ml_run — снапшот ML-прогона в PostgreSQL (СЛОЙ 3, STRUCTURE.md этап 4).

Порядок записи (см. хвост db/ddl.sql):
    runs → run_inputs (sha256 входов) → thresholds (копия констант siar/rules.py)
    → registry_agg → predictions → publish_run(run_id)

Всё в ОДНОЙ транзакции: publish_run() внутри БД вызывает validate_run(), и любое
нарушение инварианта LOGIC.md §5 откатывает прогон целиком — в базе не остаётся
даже строки в runs («выдача с нарушенным инвариантом запрещена кодом»).

Запуск (после ml/predict.py, который создаёт CSV в predictions/):
    python db/loaders/load_ml_run.py \\
        --data     "24.06.2026 Список дисквал.xlsx" \\
        --grid     predictions/full_grid.csv \\
        --registry predictions/registry_agg.csv \\
        --meta     ml/artifacts/meta_20260702_2203.json \\
        --period   "2026 Q3"

--period — тот же целевой период, что печатал predict.py (снапшот должен быть
явным). DATABASE_URL берётся из окружения или из .env в корне (правило 6).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.registry_loader import load_registry  # noqa: E402
from siar.rules import (  # noqa: E402
    ORANGE_ROLLING_MEAN_8Q_MIN,
    ORANGE_ROLLING_SUM_4Q_MIN,
    SIAR_VERSION,
)

ALLOWED_ZONES = {"RED", "ORANGE", "GREEN"}  # NO_DATA в predictions не хранится (ddl)
GRID_REQUIRED = ["Вид спорта", "Субъект РФ", "зона_риска", "proba", "причина",
                 "lag_1q", "lag_2q", "rolling_mean_8q", "rolling_sum_4q"]

INSERT_RUN = ("INSERT INTO antidoping.runs (run_kind, model_version, rules_version, notes) "
              "VALUES (%s, %s, %s, %s) RETURNING run_id")
INSERT_INPUT = ("INSERT INTO antidoping.run_inputs "
                "(run_id, file_role, file_name, sha256, row_count) "
                "VALUES (%s, %s, %s, %s, %s)")
INSERT_THRESHOLD = ("INSERT INTO antidoping.thresholds "
                    "(run_id, scope, code, value, rules_version) "
                    "VALUES (%s, %s, %s, %s, %s)")
INSERT_PREDICTION = ("INSERT INTO antidoping.predictions "
                     "(run_id, sport, region, target_year, target_quarter, proba, zone, "
                     "reason, lag_1q, lag_2q, rolling_mean_8q, rolling_sum_4q) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_env(root: Path) -> None:
    """Мини-.env без внешних зависимостей: не перекрывает уже заданное окружение."""
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def parse_period(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})\s*[Qq]\s*([1-4])\s*", str(text))
    if not m:
        raise SystemExit(f"❌ --period: ожидается 'YYYY QN' (N=1..4), получено: {text!r}")
    return int(m.group(1)), int(m.group(2))


def read_grid(path: Path) -> pd.DataFrame:
    """full_grid.csv → проверенный DataFrame под констрейнты ddl (ck_pred_*)."""
    df = pd.read_csv(path)
    missing = [c for c in GRID_REQUIRED if c not in df.columns]
    if missing:
        raise SystemExit(f"❌ {path.name}: нет колонок {missing} — "
                         f"ожидается full_grid.csv из ml/predict.py")

    zones = set(df["зона_риска"].dropna().unique())
    if not zones <= ALLOWED_ZONES:
        raise SystemExit(f"❌ {path.name}: неизвестные зоны {sorted(zones - ALLOWED_ZONES)} — "
                         f"ожидаются {sorted(ALLOWED_ZONES)} (siar/rules.py)")

    df["proba"] = pd.to_numeric(df["proba"], errors="raise")
    if not df["proba"].between(0, 1).all():
        raise SystemExit(f"❌ {path.name}: proba вне [0, 1]")

    sys_mask = df["зона_риска"].isin(("RED", "ORANGE"))
    if df.loc[sys_mask, "причина"].isna().any():
        n = int(df.loc[sys_mask, "причина"].isna().sum())
        raise SystemExit(f"❌ {path.name}: {n} строк RED/ORANGE без {{причина}} — "
                         f"CSV сгенерирован не текущим predict.py?")
    stray = int(df.loc[~sys_mask, "причина"].notna().sum())
    if stray:
        print(f"⚠️  {path.name}: у {stray} GREEN-строк заполнена «причина» — "
              f"нормализую в NULL (ck_pred_reason в БД)")
    df.loc[~sys_mask, "причина"] = None
    return df


def _pg_connect(dsn: str):
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        raise SystemExit("❌ Нет драйвера PostgreSQL: pip install 'psycopg[binary]' "
                         "(и добавьте строку в requirements.txt)")
    return psycopg.connect(dsn)


def main(argv=None, connect=_pg_connect) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="исходный xlsx базы (для sha256)")
    ap.add_argument("--grid", required=True, help="predictions/full_grid.csv")
    ap.add_argument("--registry", required=True, help="predictions/registry_agg.csv")
    ap.add_argument("--meta", required=True, help="ml/artifacts/meta_*.json")
    ap.add_argument("--period", required=True,
                    help="целевой период 'YYYY QN' — тот же, что печатал predict.py")
    ap.add_argument("--notes", default=None, help="произвольная заметка к прогону")
    args = ap.parse_args(argv)

    data_p, grid_p = Path(args.data), Path(args.grid)
    reg_p, meta_p = Path(args.registry), Path(args.meta)
    for p in (data_p, grid_p, reg_p, meta_p):
        if not p.exists():
            raise SystemExit(f"❌ Файл не найден: {p}")

    ty, tq = parse_period(args.period)
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    model_version = str(meta.get("model_version")
                        or meta_p.stem.removeprefix("meta_"))  # напр. '20260702_2203'

    grid = read_grid(grid_p)
    n_registry_rows = int(len(pd.read_csv(reg_p, usecols=[0])))

    load_env(ROOT)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("❌ DATABASE_URL не задан: заполните .env по образцу .env.example")

    conn = connect(dsn)
    try:
        cur = conn.cursor()

        # 1. runs — прогон
        cur.execute(INSERT_RUN, ("ml", model_version, SIAR_VERSION, args.notes))
        run_id = int(cur.fetchone()[0])

        # 2. run_inputs — снапшот входов (LOGIC.md §5.8)
        cur.executemany(INSERT_INPUT, [
            (run_id, "registry_xlsx", data_p.name, sha256_file(data_p), None),
            (run_id, "full_grid_csv", grid_p.name, sha256_file(grid_p), int(len(grid))),
            (run_id, "registry_agg_csv", reg_p.name, sha256_file(reg_p), n_registry_rows),
            (run_id, "model_meta_json", meta_p.name, sha256_file(meta_p), None),
        ])

        # 3. thresholds — копия констант зон модели из siar/rules.py (правило 3:
        #    значения живут в rules.py, в БД — их аудиторский след по прогону)
        cur.executemany(INSERT_THRESHOLD, [
            (run_id, "model", "orange_rolling_mean_8q_min",
             float(ORANGE_ROLLING_MEAN_8Q_MIN), SIAR_VERSION),
            (run_id, "model", "orange_rolling_sum_4q_min",
             float(ORANGE_ROLLING_SUM_4Q_MIN), SIAR_VERSION),
        ])

        # 4. registry_agg — агрегат базы (очистка — в ml/predict.py)
        n_reg = load_registry(cur, run_id, reg_p)

        # 5. predictions — вся сетка целевого квартала
        rows = [(run_id, str(r["Вид спорта"]), str(r["Субъект РФ"]), ty, tq,
                 float(r["proba"]), str(r["зона_риска"]),
                 None if pd.isna(r["причина"]) else str(r["причина"]),
                 float(r["lag_1q"]), float(r["lag_2q"]),
                 float(r["rolling_mean_8q"]), float(r["rolling_sum_4q"]))
                for _, r in grid.iterrows()]
        cur.executemany(INSERT_PREDICTION, rows)

        # 6. Публикация: validate_run() внутри БД; ошибка инварианта → откат всего
        cur.execute("SELECT antidoping.publish_run(%s)", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"✅ Прогон опубликован: run_id={run_id} · период {ty} Q{tq} · "
          f"модель {model_version} · rules {SIAR_VERSION}\n"
          f"   predictions: {len(rows)} · registry_agg: {n_reg} · входов: 4 (sha256)\n"
          f"   Проверка: docker compose exec db psql -U antidoping -d antidoping "
          f"-c 'SELECT * FROM antidoping.v_snapshots;'")
    return run_id


if __name__ == "__main__":
    main()
