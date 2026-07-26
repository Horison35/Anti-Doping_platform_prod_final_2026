# -*- coding: utf-8 -*-
"""api/facts.py — фактические цифры под {причина} зоны для карточки «почему именно так».

ВАЖНО: это НЕ формулировки SIAR (те дословно живут в siar/rules.py и не
дублируются здесь) — только человекочитаемое числовое пояснение к уже
готовой {причине} (rules.ZONE_REASONS), собранное детерминированным кодом
из сырых признаков модели (predictions.lag_1q/lag_2q/rolling_*). Ни одно
число здесь не порождает LLM (LOGIC.md §1).
"""
from __future__ import annotations

from typing import Optional


def _decline(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    d10, d100 = n % 10, n % 100
    if d100 in (11, 12, 13, 14):
        return many
    if d10 == 1:
        return one
    if d10 in (2, 3, 4):
        return few
    return many


def _violations_phrase(n: float) -> str:
    n = int(round(n))
    word = _decline(n, "нарушение", "нарушения", "нарушений")
    return f"{n} {word}"


def build_facts(pred_row: Optional[dict], zone: str) -> dict:
    """Фактические числа под зону RED/ORANGE. GREEN/NO_DATA — причины нет, facts пуст."""
    if not pred_row or zone not in ("RED", "ORANGE"):
        return {}

    lag_1q = float(pred_row.get("lag_1q") or 0)
    lag_2q = float(pred_row.get("lag_2q") or 0)
    rolling_mean_8q = float(pred_row.get("rolling_mean_8q") or 0)
    rolling_sum_4q = float(pred_row.get("rolling_sum_4q") or 0)

    if zone == "RED":
        recent = lag_1q + lag_2q
        return {
            "lag_1q": lag_1q,
            "lag_2q": lag_2q,
            "human": f"Фактически: {_violations_phrase(recent)} за последние два квартала "
                     f"(прошлый квартал — {_violations_phrase(lag_1q)}, "
                     f"позапрошлый — {_violations_phrase(lag_2q)}).",
        }

    return {
        "rolling_mean_8q": round(rolling_mean_8q, 2),
        "rolling_sum_4q": rolling_sum_4q,
        "human": f"Фактически: в среднем {rolling_mean_8q:.2f} нарушения за квартал "
                 f"на восьмиквартальной истории, {_violations_phrase(rolling_sum_4q)} "
                 f"за последний год.",
    }
