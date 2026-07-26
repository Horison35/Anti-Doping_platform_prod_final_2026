# -*- coding: utf-8 -*-
"""tests/test_backtest.py — Lift@K (метрика качества модели, LOGIC.md §2)."""
from __future__ import annotations

import pandas as pd

from ml.backtest import compute_lift_at_k


def test_lift_at_k_perfect_ranking():
    # 10 связок, топ-2 по proba — ровно те, что реально нарушили: lift@20 максимален.
    full_grid = pd.DataFrame({
        "Вид спорта": [f"sport{i}" for i in range(10)],
        "Субъект РФ": ["Москва"] * 10,
        "proba": [0.9, 0.8, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
    })
    registry_agg = pd.DataFrame({
        "Вид спорта": ["sport0", "sport1"],
        "Субъект РФ": ["Москва", "Москва"],
        "Год нарушения": [2026, 2026],
        "Квартал": [3, 3],
        "Нарушений": [2, 1],
    })
    result = compute_lift_at_k(full_grid, registry_agg, 2026, 3, k_values=(20,))
    assert result["n_actual_positive"] == 2
    assert result["base_rate"] == 0.2
    # топ-20% = 2 строки = ровно обе положительные → rate_top=1.0 → lift = 1.0/0.2 = 5.0
    assert result["lift_at_20"] == 5.0
    assert result["hits_at_20"] == 2


def test_lift_at_k_top_pick_matches_actual():
    # Однозначный лидер по proba (sport0) совпадает с единственной нарушившей связкой.
    full_grid = pd.DataFrame({
        "Вид спорта": [f"sport{i}" for i in range(10)],
        "Субъект РФ": ["Москва"] * 10,
        "proba": [0.9] + [0.1] * 9,
    })
    registry_agg = pd.DataFrame({
        "Вид спорта": ["sport0"],
        "Субъект РФ": ["Москва"],
        "Год нарушения": [2026],
        "Квартал": [3],
        "Нарушений": [1],
    })
    result = compute_lift_at_k(full_grid, registry_agg, 2026, 3, k_values=(10,))
    assert result["base_rate"] == 0.1
    # топ-10% = 1 строка — однозначно sport0 (proba=0.9) → hit
    assert result["hits_at_10"] == 1
    assert result["lift_at_10"] == 10.0


def test_lift_at_k_wrong_quarter_gives_zero_positives():
    full_grid = pd.DataFrame({
        "Вид спорта": ["sport0"], "Субъект РФ": ["Москва"], "proba": [0.9],
    })
    registry_agg = pd.DataFrame({
        "Вид спорта": ["sport0"], "Субъект РФ": ["Москва"],
        "Год нарушения": [2025], "Квартал": [1], "Нарушений": [3],
    })
    result = compute_lift_at_k(full_grid, registry_agg, 2026, 3, k_values=(10,))
    assert result["n_actual_positive"] == 0
    assert result["base_rate"] == 0.0
    assert result["lift_at_10"] is None
