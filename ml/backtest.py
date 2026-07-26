#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ml/backtest.py — квартальное сравнение прогноз/факт (LOGIC.md §7, STRUCTURE.md).

Метрика качества — Lift@K, не precision (LOGIC.md §2): среди топ-K% связок
по proba смотрим, во сколько раз доля реально нарушивших выше базовой ставки
по всей сетке. Используется и как самостоятельный квартальный отчёт, и как
гейт промоушена в ml/retrain.py (кандидат обязан не уступать действующей
версии на одном и том же закрытом квартале).

Никакой очистки данных здесь заново не пишем (риск разъехаться с
ml/predict.py, см. предупреждение в шапке predict.py про off-by-one баг из
прошлого рефакторинга) — прогноз на закрытый квартал получаем, запуская
ml/predict.py subprocess'ом с --period, и читаем его же full_grid.csv /
registry_agg.csv.

Запуск как отдельный квартальный отчёт:
    python ml/backtest.py --model ml/artifacts/prod_ensemble_X.pkl \\
        --meta ml/artifacts/meta_X.json --data "Список дисквал.xlsx" \\
        --period "2026 Q2" --out backtest/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

K_VALUES = (10, 20, 50)


def compute_lift_at_k(
    full_grid: pd.DataFrame,
    registry_agg: pd.DataFrame,
    target_year: int,
    target_quarter: int,
    k_values=K_VALUES,
) -> dict:
    """Lift@K для одного закрытого квартала.

    full_grid    — вывод ml/predict.py (Вид спорта, Субъект РФ, proba, …) на
                   ЭТОТ ЖЕ target_year/target_quarter (predict.py считает ровно
                   один целевой период за прогон — год/квартал не хранит в CSV).
    registry_agg — фактические нарушения (после очистки, тот же прогон
                   predict.py), с колонками Год нарушения/Квартал/Нарушений.
    """
    actual = registry_agg[
        (registry_agg["Год нарушения"] == target_year)
        & (registry_agg["Квартал"] == target_quarter)
        & (registry_agg["Нарушений"] > 0)
    ]
    actual_keys = set(zip(actual["Вид спорта"], actual["Субъект РФ"]))

    pred = full_grid.sort_values("proba", ascending=False).reset_index(drop=True)
    n_total = len(pred)
    if n_total == 0:
        raise ValueError("full_grid пуст — нечего сравнивать")

    base_rate = len(actual_keys) / n_total
    result: dict = {"base_rate": base_rate, "n_total": n_total, "n_actual_positive": len(actual_keys)}

    for k in k_values:
        n_top = max(1, round(n_total * k / 100))
        top = pred.head(n_top)
        hits = sum(
            1 for _, r in top.iterrows() if (r["Вид спорта"], r["Субъект РФ"]) in actual_keys
        )
        rate_top = hits / n_top
        result[f"lift_at_{k}"] = (rate_top / base_rate) if base_rate > 0 else None
        result[f"hits_at_{k}"] = hits
    return result


def run_predict(
    model_path: Path, meta_path: Path, data_path: Path, period: str, out_dir: Path,
    python_bin: Optional[str] = None,
) -> None:
    python_bin = python_bin or sys.executable
    cmd = [
        python_bin, str(ROOT / "ml" / "predict.py"),
        "--model", str(model_path), "--meta", str(meta_path),
        "--data", str(data_path), "--out", str(out_dir), "--period", period,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"ml/predict.py упал при бэктесте (период {period}): "
            f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )


def backtest_one_model(
    model_path: Path, meta_path: Path, data_path: Path, period: str,
    python_bin: Optional[str] = None,
) -> dict:
    """Прогон + Lift@K для одной версии модели на одном закрытом квартале."""
    ty, tq = _parse_period(period)
    with tempfile.TemporaryDirectory(prefix="adp_backtest_") as tmp:
        tmp_dir = Path(tmp)
        run_predict(model_path, meta_path, data_path, period, tmp_dir, python_bin)
        full_grid = pd.read_csv(tmp_dir / "full_grid.csv")
        registry_agg = pd.read_csv(tmp_dir / "registry_agg.csv")
    return compute_lift_at_k(full_grid, registry_agg, ty, tq)


def _parse_period(text: str) -> tuple[int, int]:
    import re
    m = re.fullmatch(r"\s*(\d{4})\s*[Qq]\s*([1-4])\s*", str(text))
    if not m:
        raise SystemExit(f"❌ --period: ожидается 'YYYY QN' (N=1..4), получено: {text!r}")
    return int(m.group(1)), int(m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--period", required=True, help="закрытый квартал 'YYYY QN' с известным фактом")
    ap.add_argument("--out", default="backtest")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = backtest_one_model(Path(args.model), Path(args.meta), Path(args.data), args.period)
    print(f"📊 Backtest {args.period}: {json.dumps(metrics, ensure_ascii=False, indent=2)}")

    out_path = out_dir / f"backtest_{args.period.replace(' ', '_')}.json"
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 Сохранено: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
