# -*- coding: utf-8 -*-
"""load_siar_run — снапшот результата SIAR v2 (ОСФ или регионы) в PostgreSQL.

Второй загрузчик СЛОЯ 3 (STRUCTURE.md этап 4): load_ml_run.py грузит только
прогон модели (predictions/registry_agg) — этот файл закрывает вторую
половину конвейера, которой раньше не было: результаты siar/osf_report.py и
siar/region_report.py (сейчас лежат в reports/osf_risk_final.xlsx и
reports/region_risk_final.xlsx) → rating_criteria, quadrant_results,
matching_audit, unmatched, thresholds(scope=osf|region).

Важно: обоснование/рекомендация НЕ копируются из Excel как текст. Excel
сейчас формирует их инлайн-логикой (STRUCTURE.md отмечает osf_report.py и
region_report.py статусом «🔧 доработка: формулировки SIAR v2 из rules.py» —
они ещё не используют rules.evaluate()). Чтобы в БД не задублировался второй,
слегка отличающийся набор формулировок, этот загрузчик берёт из Excel только
сырые факты (зона, балл, невыполненные критерии) и пересчитывает
state/priority/status/justification/recommendation через siar.rules.evaluate()
— «правила приоритизации живут только в siar/rules.py» (STRUCTURE.md, п. 3).
Побочный эффект: сохраняются только УТВЕРЖДЁННЫЕ формулировки LOGIC.md §3.

Ограничение источника: osf_report.py/region_report.py экспортируют в Excel
только «выполнен/не выполнен» по критерию, не исходное числовое значение.
Поэтому rating_criteria.value для criterion_kind='base' — прокси 1.0/0.0
(выполнен/не выполнен), а не сырой балл из PDF/xlsx рейтинга; сам числовой
балл появится, когда osf_report.py/region_report.py будут переведены на
отдачу сырых значений отдельными полями (не только «выполнен/не выполнен»).

Bonus/penalty критерии регионов (1.9/1.10/3.4) — начиная с версии
region_report.py на siar.rules.evaluate() — экспортируются отдельной
колонкой «Бонусы/штрафы» и грузятся точным числом. Если на входе старый
report-файл без этой колонки (сформирован до перевода на rules.py) —
загрузчик не падает и не выдумывает нули, а печатает предупреждение и
грузит только base-критерии.

Запуск (после siar/osf_report.py или siar/region_report.py):
    python db/loaders/load_siar_run.py --kind osf \\
        --source "Rei_ting-OSF-2025-_itog_-_1_.pdf" \\
        --report reports/osf_risk_final.xlsx \\
        --meta   ml/artifacts/meta_20260702_2203.json

    python db/loaders/load_siar_run.py --kind region \\
        --source "Rei_ting-regionov-Itogi-2025.xlsx" \\
        --report reports/region_risk_final.xlsx \\
        --meta   ml/artifacts/meta_20260702_2203.json

--source — исходный файл рейтинга (для sha256 и N источника, §5.1); --meta —
тот же ml/artifacts/meta_*.json, что и у load_ml_run.py (в quadrant_results
и predictions должна стоять одна версия модели, откуда взяты зоны риска).
DATABASE_URL берётся из окружения или .env в корне (правило 6).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# _key — единственная нормализация имён регионов в проекте (алиасы, падежи);
# переиспользуем её же для matching_audit, а не заводим второй список алиасов.
from siar.region_report import _key as region_key  # noqa: E402
from siar.rules import (  # noqa: E402
    EntityKind,
    OSF_CRITERIA,
    RATING_SCALES,
    SIAR_VERSION,
    Zone,
    ZONE_REASONS,
    evaluate,
    is_high_rating,
)

FILE_ROLE_SOURCE = {"osf": "osf_rating_pdf", "region": "region_rating_xlsx"}
FILE_ROLE_REPORT = {"osf": "osf_risk_report_xlsx", "region": "region_risk_report_xlsx"}
MAIN_SHEET = {"osf": "Итог", "region": "Матрица регионов"}
BONUS_MARK, PENALTY_MARK = "(бонус)", "(штраф)"

OSF_REQUIRED_COLS = [
    "№", "Вид спорта (ОСФ)", "Приоритет", "Зона риска", "Оценка риска (proba)",
    "Баллы рейтинга РУСАДА", "Место в рейтинге",
    "Выполненные критерии РУСАДА", "Невыполненные критерии РУСАДА",
]
REGION_REQUIRED_COLS = [
    "№", "ФО", "Регион", "Приоритет", "Зона риска", "Оценка риска (proba)",
    "Итого баллов", "Место", "Выполненные критерии", "Невыполненные критерии",
]

INSERT_RUN = ("INSERT INTO antidoping.runs (run_kind, model_version, rules_version, notes) "
              "VALUES (%s, %s, %s, %s) RETURNING run_id")
INSERT_INPUT = ("INSERT INTO antidoping.run_inputs "
                "(run_id, file_role, file_name, sha256, row_count) "
                "VALUES (%s, %s, %s, %s, %s)")
INSERT_THRESHOLD = ("INSERT INTO antidoping.thresholds "
                    "(run_id, scope, code, value, rules_version) "
                    "VALUES (%s, %s, %s, %s, %s)")
INSERT_CRITERION = ("INSERT INTO antidoping.rating_criteria "
                    "(run_id, kind, entity_name, fo, criterion_code, block, "
                    "criterion_kind, value, is_met, sort_order) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
INSERT_QUADRANT = ("INSERT INTO antidoping.quadrant_results "
                   "(run_id, kind, entity_name, fo, matched_model_name, zone, proba, "
                   "reason, state, priority, status, rating_score, rating_high, "
                   "rating_place, unmet_criteria, has_attention_zone, justification, "
                   "recommendation, monitor_signals_30d, monitor_signals_90d, "
                   "risk_rank, siar_version) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
INSERT_AUDIT = ("INSERT INTO antidoping.matching_audit "
                "(run_id, kind, model_name, rating_name, match_type, confidence, "
                "zone, proba, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")
INSERT_UNMATCHED = ("INSERT INTO antidoping.unmatched (run_id, kind, side, name, reason) "
                    "VALUES (%s, %s, %s, %s, %s)")


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


# ══════════════════════════ ЧТЕНИЕ EXCEL ══════════════════════════

def _read_sheet_or_empty(path: Path, name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=name)
    except ValueError:
        return pd.DataFrame()


def _opt_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    return float(v)


def _opt_int(v) -> int | None:
    if v is None or pd.isna(v) or str(v).strip() == "":
        return None
    return int(float(v))


def _parse_criteria_list(text) -> list[str]:
    s = "" if pd.isna(text) else str(text).strip()
    if not s or s == "нет":
        return []
    return [c.strip() for c in s.split(";") if c.strip()]


def _parse_zone(text: str) -> str:
    """«🔴 RED» / «⚪ NO_DATA» → код зоны (последний токен)."""
    return str(text).strip().split()[-1]


def read_report(kind: str, report_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    main = pd.read_excel(report_path, sheet_name=MAIN_SHEET[kind])
    required = OSF_REQUIRED_COLS if kind == "osf" else REGION_REQUIRED_COLS
    missing = [c for c in required if c not in main.columns]
    if missing:
        raise SystemExit(f"❌ {report_path.name}: лист «{MAIN_SHEET[kind]}» без колонок {missing} — "
                         f"ожидается вывод siar/{'osf' if kind == 'osf' else 'region'}_report.py")
    audit = _read_sheet_or_empty(report_path, "Аудит матчинга")
    unmatched = _read_sheet_or_empty(report_path, "Не сопоставлено")
    return main, audit, unmatched


# ══════════════════════════ rating_criteria ══════════════════════════

def osf_criteria_rows(row) -> list[dict]:
    entity = row["Вид спорта (ОСФ)"]
    met = set(_parse_criteria_list(row["Выполненные критерии РУСАДА"]))
    unmet = set(_parse_criteria_list(row["Невыполненные критерии РУСАДА"]))
    out = []
    for order, code in enumerate(OSF_CRITERIA):
        if code in met:
            is_met = True
        elif code in unmet:
            is_met = False
        else:
            raise SystemExit(f"❌ load_siar_run: критерий «{code}» не найден ни в "
                             f"«Выполненные», ни в «Невыполненные» для «{entity}» — "
                             f"неполный список критериев в отчёте")
        out.append(dict(entity_name=entity, fo=None, criterion_code=code, block=None,
                        criterion_kind="base", value=1.0 if is_met else 0.0,
                        is_met=is_met, sort_order=order))
    return out


def region_criteria_rows(row, has_extras_col: bool) -> list[dict]:
    entity, fo = row["Регион"], row["ФО"]
    met = _parse_criteria_list(row["Выполненные критерии"])
    unmet = _parse_criteria_list(row["Невыполненные критерии"])
    out = []
    for order, code in enumerate(met + unmet):
        block = code.split(".", 1)[0].strip() if "." in code else None
        is_met = code in met
        out.append(dict(entity_name=entity, fo=fo, criterion_code=code, block=block,
                        criterion_kind="base", value=1.0 if is_met else 0.0,
                        is_met=is_met, sort_order=order))

    if not has_extras_col:
        return out  # текущий region_report.py не экспортирует «Бонусы/штрафы» отдельной
                    # колонкой (см. предупреждение в main()) — bonus/penalty не грузим,
                    # а не молча додумываем нули

    extras = row["Бонусы/штрафы"]
    extras = "" if pd.isna(extras) else str(extras).strip()
    for order2, part in enumerate(p.strip() for p in extras.split(";") if p.strip()):
        m = re.match(r"^(.*):\s*([+-]?[\d.]+)$", part)
        if not m:
            raise SystemExit(f"❌ load_siar_run: не разобрать «{part}» в «Бонусы/штрафы» ({entity})")
        label, val = m.group(1).strip(), float(m.group(2))
        if BONUS_MARK in label:
            crit_kind = "bonus"
        elif PENALTY_MARK in label:
            crit_kind = "penalty"
        else:
            raise SystemExit(f"❌ load_siar_run: неизвестный тип «{label}» — "
                             f"ожидается «{BONUS_MARK}» или «{PENALTY_MARK}» ({entity})")
        block = label.split(".", 1)[0].strip() if "." in label else None
        out.append(dict(entity_name=entity, fo=fo, criterion_code=label, block=block,
                        criterion_kind=crit_kind, value=val, is_met=None,
                        sort_order=100 + order2))
    return out


# ══════════════════════════ quadrant_results ══════════════════════════

def build_osf_quadrant_row(row, audit_df: pd.DataFrame) -> dict:
    entity = row["Вид спорта (ОСФ)"]
    zone_code = _parse_zone(row["Зона риска"])
    zone = Zone.coerce(zone_code)
    proba = _opt_float(row["Оценка риска (proba)"])
    score = float(row["Баллы рейтинга РУСАДА"])
    unmet = _parse_criteria_list(row["Невыполненные критерии РУСАДА"])
    reason = ZONE_REASONS.get(zone)

    try:
        a = evaluate(EntityKind.OSF, zone, score, reason=reason,
                    unmet_criteria=unmet, object_name=entity)
    except ValueError as e:
        raise SystemExit(f"❌ load_siar_run: SIAR v2 отклонил строку «{entity}»: {e}")

    matched_model_name = None
    if not audit_df.empty:
        cand = audit_df[(audit_df["ОСФ (рейтинг)"] == entity) & (audit_df["Зона"] == zone_code)]
        if proba is not None and not cand.empty:
            close = cand[np.isclose(cand["proba"].astype(float), proba, atol=1e-3)]
            if not close.empty:
                cand = close
        if not cand.empty:
            matched_model_name = str(cand.iloc[0]["Вид спорта (модель)"])

    return dict(
        kind="osf", entity_name=entity, fo=None, matched_model_name=matched_model_name,
        zone=zone_code, proba=proba, reason=a.reason,
        state=a.state.value, priority=a.priority, status=a.status,
        rating_score=score, rating_high=is_high_rating(score, EntityKind.OSF),
        rating_place=_opt_int(row["Место в рейтинге"]),
        unmet_criteria=list(a.unmet_criteria), has_attention_zone=a.has_attention_zone,
        justification=a.justification, recommendation=a.recommendation,
        monitor_signals_30d=None, monitor_signals_90d=None,
        risk_rank=_opt_int(row["№"]), siar_version=SIAR_VERSION,
    )


def build_region_quadrant_row(row, audit_df: pd.DataFrame, ekey: str) -> dict:
    entity, fo = row["Регион"], row["ФО"]
    zone_code = _parse_zone(row["Зона риска"])
    zone = Zone.coerce(zone_code)
    proba = _opt_float(row["Оценка риска (proba)"])
    score = float(row["Итого баллов"])
    unmet = _parse_criteria_list(row["Невыполненные критерии"])
    reason = ZONE_REASONS.get(zone)

    try:
        a = evaluate(EntityKind.REGION, zone, score, reason=reason,
                    unmet_criteria=unmet, object_name=entity)
    except ValueError as e:
        raise SystemExit(f"❌ load_siar_run: SIAR v2 отклонил строку «{entity}»: {e}")

    matched_model_name = None
    if not audit_df.empty:
        cand = audit_df[audit_df["Ключ"] == ekey]
        if not cand.empty:
            matched_model_name = str(cand.iloc[0]["Регион (модель)"])

    return dict(
        kind="region", entity_name=entity, fo=fo, matched_model_name=matched_model_name,
        zone=zone_code, proba=proba, reason=a.reason,
        state=a.state.value, priority=a.priority, status=a.status,
        rating_score=score, rating_high=is_high_rating(score, EntityKind.REGION),
        rating_place=_opt_int(row["Место"]),
        unmet_criteria=list(a.unmet_criteria), has_attention_zone=a.has_attention_zone,
        justification=a.justification, recommendation=a.recommendation,
        monitor_signals_30d=None, monitor_signals_90d=None,
        risk_rank=_opt_int(row["№"]), siar_version=SIAR_VERSION,
    )


# ══════════════════════════ matching_audit / unmatched ══════════════════════════

def osf_audit_rows(audit_df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in audit_df.iterrows():
        rating_name = None if r["ОСФ (рейтинг)"] == "—" else str(r["ОСФ (рейтинг)"])
        rows.append(("osf", str(r["Вид спорта (модель)"]), rating_name,
                     str(r["Тип матчинга"]), float(r["Уверенность"]),
                     str(r["Зона"]), float(r["proba"]), None))
    return rows


def region_audit_rows(audit_df: pd.DataFrame, key_to_region: dict[str, str]) -> list[tuple]:
    """Лист «Аудит матчинга» region_report.py хранит только нормализованный
    «Ключ» и да/нет, без самого сопоставленного имени — восстанавливаем его
    через ту же key_to_region, что и matched_model_name в quadrant_results
    (обе стороны region_key() совпадают ровно при найденном матче)."""
    rows = []
    for _, r in audit_df.iterrows():
        found = str(r["Найден в рейтинге"]).strip() == "да"
        rating_name = key_to_region.get(r["Ключ"]) if found else None
        match_type = "точный" if found else "нет"
        rows.append(("region", str(r["Регион (модель)"]), rating_name,
                     match_type, 1.0 if found else 0.0,
                     str(r["Зона"]), float(r["proba"]), None))
    return rows


SIDE_MAP = {"модель": "model", "рейтинг": "rating"}


def unmatched_rows(kind: str, unmatched_df: pd.DataFrame) -> list[tuple]:
    rows = []
    for _, r in unmatched_df.iterrows():
        side = SIDE_MAP.get(str(r["Источник"]).strip())
        if side is None:
            raise SystemExit(f"❌ load_siar_run: неизвестный «Источник» «{r['Источник']}» "
                             f"в «Не сопоставлено» ({kind})")
        rows.append((kind, side, str(r["Название"]), str(r["Причина"])))
    return rows


def _pg_connect(dsn: str):
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        raise SystemExit("❌ Нет драйвера PostgreSQL: pip install 'psycopg[binary]'")
    return psycopg.connect(dsn)


def main(argv=None, connect=_pg_connect) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", required=True, choices=["osf", "region"])
    ap.add_argument("--source", required=True, help="исходный рейтинг: PDF (osf) или xlsx (region)")
    ap.add_argument("--report", required=True, help="reports/osf_risk_final.xlsx или region_risk_final.xlsx")
    ap.add_argument("--meta", required=True, help="ml/artifacts/meta_*.json — версия модели, чьи зоны в отчёте")
    ap.add_argument("--notes", default=None)
    args = ap.parse_args(argv)

    kind = args.kind
    source_p, report_p, meta_p = Path(args.source), Path(args.report), Path(args.meta)
    for p in (source_p, report_p, meta_p):
        if not p.exists():
            raise SystemExit(f"❌ Файл не найден: {p}")

    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    model_version = str(meta.get("model_version") or meta_p.stem.removeprefix("meta_"))

    main_df, audit_df, unmatched_df = read_report(kind, report_p)

    if kind == "osf":
        criteria_rows = [c for _, row in main_df.iterrows() for c in osf_criteria_rows(row)]
        quadrant_rows = [build_osf_quadrant_row(row, audit_df) for _, row in main_df.iterrows()]
        audit_rows = osf_audit_rows(audit_df) if not audit_df.empty else []
    else:
        has_extras_col = "Бонусы/штрафы" in main_df.columns
        if not has_extras_col:
            print("⚠️  load_siar_run: в «Матрица регионов» нет колонки «Бонусы/штрафы» — "
                 "bonus/penalty критерии НЕ загружены (region_report.py сейчас не "
                 "экспортирует их отдельной колонкой, только внутри текста «Обоснование»); "
                 "rating_criteria получит только base-критерии.")
        criteria_rows = [c for _, row in main_df.iterrows()
                         for c in region_criteria_rows(row, has_extras_col)]
        # region_key — единая нормализация для обеих сторон (кв.результаты и аудит),
        # строится один раз, а не пересчитывается на каждую строку.
        key_to_region = {region_key(name): name for name in main_df["Регион"]}
        quadrant_rows = [build_region_quadrant_row(row, audit_df, region_key(row["Регион"]))
                         for _, row in main_df.iterrows()]
        audit_rows = region_audit_rows(audit_df, key_to_region) if not audit_df.empty else []
    unmatched_out = unmatched_rows(kind, unmatched_df) if not unmatched_df.empty else []

    load_env(ROOT)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("❌ DATABASE_URL не задан: заполните .env по образцу .env.example")

    conn = connect(dsn)
    try:
        cur = conn.cursor()

        cur.execute(INSERT_RUN, (f"siar_{kind}", model_version, SIAR_VERSION, args.notes))
        run_id = int(cur.fetchone()[0])

        cur.executemany(INSERT_INPUT, [
            (run_id, FILE_ROLE_SOURCE[kind], source_p.name, sha256_file(source_p), len(main_df)),
            (run_id, FILE_ROLE_REPORT[kind], report_p.name, sha256_file(report_p), len(main_df)),
            (run_id, "model_meta_json", meta_p.name, sha256_file(meta_p), None),
        ])

        scale = RATING_SCALES[EntityKind.coerce(kind)]
        cur.executemany(INSERT_THRESHOLD, [
            (run_id, kind, "high_threshold", float(scale.high_threshold), SIAR_VERSION),
            (run_id, kind, "max_score", float(scale.max_score), SIAR_VERSION),
        ])

        cur.executemany(INSERT_CRITERION, [
            (run_id, kind, c["entity_name"], c["fo"], c["criterion_code"], c["block"],
             c["criterion_kind"], c["value"], c["is_met"], c["sort_order"])
            for c in criteria_rows
        ])

        cur.executemany(INSERT_QUADRANT, [
            (run_id, q["kind"], q["entity_name"], q["fo"], q["matched_model_name"],
             q["zone"], q["proba"], q["reason"], q["state"], q["priority"], q["status"],
             q["rating_score"], q["rating_high"], q["rating_place"], q["unmet_criteria"],
             q["has_attention_zone"], q["justification"], q["recommendation"],
             q["monitor_signals_30d"], q["monitor_signals_90d"], q["risk_rank"], q["siar_version"])
            for q in quadrant_rows
        ])

        if audit_rows:
            cur.executemany(INSERT_AUDIT, [(run_id, *row) for row in audit_rows])
        if unmatched_out:
            cur.executemany(INSERT_UNMATCHED, [(run_id, *row) for row in unmatched_out])

        cur.execute("SELECT antidoping.publish_run(%s)", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"✅ SIAR-прогон опубликован: run_id={run_id} · kind={kind} · модель {model_version} · "
          f"rules {SIAR_VERSION}\n"
          f"   quadrant_results: {len(quadrant_rows)} · rating_criteria: {len(criteria_rows)} · "
          f"audit: {len(audit_rows)} · не сопоставлено: {len(unmatched_out)}\n"
          f"   Проверка: docker compose exec db psql -U antidoping -d antidoping "
          f"-c 'SELECT * FROM antidoping.v_snapshots;'")
    return run_id


if __name__ == "__main__":
    main()
