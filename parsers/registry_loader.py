# -*- coding: utf-8 -*-
"""registry_loader — загрузка агрегата базы дисквалификаций в PostgreSQL.

Источник: predictions/registry_agg.csv, который выгружает ml/predict.py из
ОЧИЩЕННОЙ базы. Очистка «как в ноутбуке модели» живёт в одном месте —
в ml/predict.py; этот модуль её не дублирует, а грузит готовый агрегат.

Правило 8 (STRUCTURE.md): ФИО в БД не попадают. По построению в CSV только
агрегаты вид спорта × субъект РФ × квартал; защита ниже дополнительно
отказывается грузить файл, где встретились персональные колонки.

Использование — из оркестратора прогона (db/loaders/load_ml_run.py):
    from parsers.registry_loader import load_registry
    n = load_registry(cur, run_id, "predictions/registry_agg.csv")
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

EXPECTED_COLS = ["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал", "Нарушений"]
FORBIDDEN_MARKERS = ("фио", "дата рождения", "тренер")  # правило 8

INSERT_SQL = (
    "INSERT INTO antidoping.registry_agg "
    "(run_id, sport, region, year, quarter, violations) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)


def _last_closed_quarter(today: date) -> tuple[int, int]:
    q_closed = (today.month - 1) // 3
    return (today.year, q_closed) if q_closed else (today.year - 1, 4)


def load_registry(cur, run_id: int, csv_path: str | Path,
                  today: date | None = None) -> int:
    """Грузит registry_agg.csv в antidoping.registry_agg (в открытой транзакции).

    Возвращает число вставленных строк. Любая проблема с файлом — SystemExit:
    частично загруженный агрегат хуже отсутствующего.
    """
    p = Path(csv_path)
    df = pd.read_csv(p)

    low = [str(c).strip().lower() for c in df.columns]
    bad = [c for c, l in zip(df.columns, low) if any(m in l for m in FORBIDDEN_MARKERS)]
    if bad:
        raise SystemExit(f"❌ registry_loader: в {p.name} персональные колонки {bad} — "
                         f"в БД грузим только агрегаты (STRUCTURE.md, п. 8)")

    missing = [c for c in EXPECTED_COLS if c not in df.columns]
    if missing:
        raise SystemExit(f"❌ registry_loader: в {p.name} нет колонок {missing}; "
                         f"ожидается registry_agg.csv из ml/predict.py")

    df = df[EXPECTED_COLS].copy()
    for c in ("Год нарушения", "Квартал", "Нарушений"):
        df[c] = pd.to_numeric(df[c], errors="raise").astype(int)
    if (df["Нарушений"] <= 0).any():
        raise SystemExit("❌ registry_loader: найдены нулевые/отрицательные счётчики — "
                         "в агрегате ожидаются только ненулевые ячейки")
    if not df["Квартал"].between(1, 4).all():
        raise SystemExit("❌ registry_loader: значение «Квартал» вне 1..4")
    if df.duplicated(["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"]).any():
        raise SystemExit("❌ registry_loader: дубли ячеек вид×регион×квартал — "
                         "PK таблицы registry_agg их не пропустит")

    # Ячейки в ещё не закрытых кварталах: обычно даты ОКОНЧАНИЯ санкций,
    # просочившиеся при извлечении дат. «База — истина» (LOGIC.md §1) —
    # грузим как есть, но громко предупреждаем.
    ly, lq = _last_closed_quarter(today or date.today())
    fut = df[(df["Год нарушения"] > ly) |
             ((df["Год нарушения"] == ly) & (df["Квартал"] > lq))]
    if len(fut):
        print(f"⚠️  registry_loader: {int(fut['Нарушений'].sum())} нарушений в "
              f"{len(fut)} ячейках датированы кварталами после {ly} Q{lq} "
              f"(последний закрытый) — проверьте извлечение дат в базе.")

    rows = [(run_id, str(r["Вид спорта"]), str(r["Субъект РФ"]),
             int(r["Год нарушения"]), int(r["Квартал"]), int(r["Нарушений"]))
            for _, r in df.iterrows()]
    cur.executemany(INSERT_SQL, rows)
    return len(rows)


if __name__ == "__main__":
    sys.exit("registry_loader — модуль для оркестратора прогона; "
             "запускайте db/loaders/load_ml_run.py")
