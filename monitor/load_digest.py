# -*- coding: utf-8 -*-
"""monitor/load_digest.py — валидация и загрузка JSON-дайджеста АД-Монитора в flags.

Схема полей — по реальному monitor/ad_monitor_prompt_v15.md:
  records:    id, scope (rf|intl — поток выпуска, обязателен, идёт в
              flags.scope для дашборда «АД-Монитор»), category, subject,
              subject_nationality, sport (может быть null), violation,
              sanction_body, term, date, source_url, verification,
              is_doping_event.
  unverified: subject, reason, hint_url — НАМНОГО более скудная форма, без
              category/source_url/date/is_doping_event. Не путать с records
              «минус строгость» — это структурно другой объект, поэтому ниже
              две отдельные функции валидации/сборки, а не одна с флагом strict.

Использование:
    python monitor/load_digest.py <путь_к_json>

Ничего не грузит частично: любая проблема со схемой/полями — явная ошибка
и ненулевой код выхода (SystemExit), до открытия соединения с БД.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOP_LEVEL_REQUIRED = ["status", "window", "data_feed", "ml_feed", "dashboard"]

# Обязательные поля — буквально по контракту (см. докстринг файла). sport в
# records разрешён null самим контрактом ("вид спорта | null") — не требуем.
CONFIRMED_REQUIRED = ["category", "subject", "source_url", "date", "is_doping_event", "scope"]
UNVERIFIED_REQUIRED = ["subject", "reason", "hint_url"]
VALID_SCOPES = {"rf", "intl"}

# category у unverified в контракте нет вообще (только subject/reason/hint_url) —
# ставим понятную заглушку, чтобы удовлетворить NOT NULL flags.category, не
# выдумывая содержательную категорию.
UNVERIFIED_CATEGORY_PLACEHOLDER = "неподтверждённый сигнал"

DEDUP_WINDOW_DAYS = 7
UNVERIFIED_EXPIRES_DAYS = 2  # «снимается за два выпуска» при ежедневном окне (§6)

INSERT_RUN = "INSERT INTO antidoping.runs (run_kind, notes) VALUES (%s, %s) RETURNING run_id"
FINISH_RUN = ("UPDATE antidoping.runs SET status='success', finished_at=now() "
             "WHERE run_id=%s")
DUP_CHECK = ("SELECT 1 FROM antidoping.flags WHERE dedup_hash=%s AND monitor_date >= %s")
INSERT_FLAG = (
    "INSERT INTO antidoping.flags "
    "(run_id, monitor_date, event_date, category, is_doping_event, scope, sport, region, "
    "country, is_ru, title, summary, source_name, source_url, url_verified, "
    "url_checked_at, confirmed, expires_at, dedup_hash, payload) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


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


def validate_contract(doc: dict, path: Path) -> None:
    if not isinstance(doc, dict):
        raise SystemExit(f"❌ {path.name}: верхний уровень JSON должен быть объектом, "
                         f"получено {type(doc).__name__}")
    missing = [k for k in TOP_LEVEL_REQUIRED if k not in doc]
    if missing:
        raise SystemExit(f"❌ {path.name}: нет обязательных полей верхнего уровня {missing} "
                         f"(контракт monitor/ad_monitor_prompt_v15.md) — есть: {sorted(doc.keys())}")
    df = doc["data_feed"]
    if not isinstance(df, dict) or "records" not in df or "unverified" not in df:
        got = sorted(df.keys()) if isinstance(df, dict) else type(df).__name__
        raise SystemExit(f"❌ {path.name}: data_feed без records/unverified — есть: {got}")
    if not isinstance(df["records"], list) or not isinstance(df["unverified"], list):
        raise SystemExit(f"❌ {path.name}: data_feed.records/.unverified должны быть списками")


def _check_fields(rec: dict, idx: int, side: str, required: list[str]) -> None:
    if not isinstance(rec, dict):
        raise SystemExit(f"❌ data_feed.{side}[{idx}]: запись должна быть объектом, "
                         f"получено {type(rec).__name__}")
    missing = [f for f in required if rec.get(f) in (None, "")]
    if missing:
        raise SystemExit(f"❌ data_feed.{side}[{idx}]: нет обязательных полей {missing} "
                         f"(контракт v15) — есть в записи: {sorted(rec.keys())}")


def check_confirmed_record(rec: dict, idx: int) -> None:
    _check_fields(rec, idx, "records", CONFIRMED_REQUIRED)
    if rec.get("scope") not in VALID_SCOPES:
        raise SystemExit(
            f"❌ data_feed.records[{idx}]: scope={rec.get('scope')!r} — "
            f"ожидается один из {sorted(VALID_SCOPES)} (контракт v15)"
        )


def check_unverified_record(rec: dict, idx: int) -> None:
    _check_fields(rec, idx, "unverified", UNVERIFIED_REQUIRED)


def dedup_hash_for_confirmed(rec: dict) -> str:
    """По ТЗ: sha256(subject+violation+date) — все три поля есть в контракте буквально."""
    subject = str(rec.get("subject") or "")
    violation = str(rec.get("violation") or "")
    d = str(rec.get("date") or "")
    return sha256_hex(f"{subject}|{violation}|{d}")


def dedup_hash_for_unverified(rec: dict) -> str:
    """unverified не имеет violation/date — ближайший аналог: subject+reason."""
    subject = str(rec.get("subject") or "")
    reason = str(rec.get("reason") or "")
    return sha256_hex(f"{subject}|{reason}")


def verify_url(url: str, timeout: float = 10.0) -> tuple[bool, datetime]:
    checked_at = datetime.now(timezone.utc)
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; ADMonitorBot/1.0)"})
        return (r.status_code < 400), checked_at
    except requests.RequestException:
        return False, checked_at


def build_confirmed_flag_row(run_id: int, monitor_date, rec: dict, dedup: str,
                             verified: bool, checked_at: datetime) -> tuple:
    subject = rec.get("subject")
    nationality = rec.get("subject_nationality")
    sanction_body = rec.get("sanction_body")
    summary = "; ".join(p for p in (
        rec.get("violation"),
        f"орган: {sanction_body}" if sanction_body else None,
        f"срок: {rec.get('term')}" if rec.get("term") else None,
    ) if p) or None

    return (run_id, monitor_date, rec.get("date"), rec.get("category"),
            bool(rec.get("is_doping_event", False)), rec.get("scope"), rec.get("sport"), None,
            nationality, nationality == "RU", subject, summary, sanction_body,
            rec.get("source_url"), verified, checked_at, True, None, dedup,
            json.dumps(rec, ensure_ascii=False))


def build_unverified_flag_row(run_id: int, monitor_date, rec: dict, dedup: str,
                              verified: bool, checked_at: datetime) -> tuple:
    expires_at = date.today() + timedelta(days=UNVERIFIED_EXPIRES_DAYS)
    return (run_id, monitor_date, None, UNVERIFIED_CATEGORY_PLACEHOLDER, False,
            None, None, None, None, False, rec.get("subject"), rec.get("reason"), None,
            rec.get("hint_url"), verified, checked_at, False, expires_at, dedup,
            json.dumps(rec, ensure_ascii=False))


def _pg_connect(dsn: str):
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        raise SystemExit("❌ Нет драйвера PostgreSQL: pip install 'psycopg[binary]'")
    return psycopg.connect(dsn)


def main(argv=None, connect=_pg_connect) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_path")
    ap.add_argument("--skip-url-check", action="store_true",
                    help="не ходить в сеть (только для отладки схемы, не для прод-загрузки)")
    args = ap.parse_args(argv)

    p = Path(args.json_path)
    if not p.exists():
        raise SystemExit(f"❌ Файл не найден: {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ {p.name}: невалидный JSON — {e}")

    validate_contract(doc, p)
    records = doc["data_feed"]["records"]
    unverified = doc["data_feed"]["unverified"]
    for i, r in enumerate(records):
        check_confirmed_record(r, i)
    for i, r in enumerate(unverified):
        check_unverified_record(r, i)

    window = doc.get("window") or {}
    monitor_date = window.get("date") or window.get("to") or str(date.today())
    json_run_id = doc.get("run_id") or window.get("run_id")
    notes = f"monitor_run_uuid={json_run_id}" if json_run_id else None

    load_env(ROOT)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("❌ DATABASE_URL не задан: заполните .env по образцу .env.example")

    conn = connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(INSERT_RUN, ("monitor", notes))
        run_id = int(cur.fetchone()[0])

        cutoff = date.today() - timedelta(days=DEDUP_WINDOW_DAYS)
        loaded, skipped_dup = 0, 0

        for idx, rec in enumerate(records):
            dh = dedup_hash_for_confirmed(rec)
            cur.execute(DUP_CHECK, (dh, cutoff))
            if cur.fetchone():
                skipped_dup += 1
                continue

            source_url = rec.get("source_url")
            if args.skip_url_check:
                verified, checked_at = False, datetime.now(timezone.utc)
            else:
                verified, checked_at = verify_url(source_url)

            # §5.7 / ck_flags_confirmed_verified: confirmed требует проверенного
            # первичного источника. Если JSON утверждает verification="verified"
            # (records), а наша HTTP-проверка не подтвердила URL — это расхождение
            # данных, не тихая подстановка: останавливаемся с точным указанием записи.
            if not verified and not args.skip_url_check:
                raise SystemExit(
                    f"❌ data_feed.records[{idx}] помечена как подтверждённая, но "
                    f"HTTP HEAD source_url не прошёл проверку: {source_url!r} — "
                    f"загрузка остановлена (не молчим о расхождении, LOGIC.md §5.7)")

            cur.execute(INSERT_FLAG, build_confirmed_flag_row(
                run_id, monitor_date, rec, dh, verified, checked_at))
            loaded += 1

        for idx, rec in enumerate(unverified):
            dh = dedup_hash_for_unverified(rec)
            cur.execute(DUP_CHECK, (dh, cutoff))
            if cur.fetchone():
                skipped_dup += 1
                continue

            hint_url = rec.get("hint_url")
            if args.skip_url_check:
                verified, checked_at = False, datetime.now(timezone.utc)
            else:
                verified, checked_at = verify_url(hint_url)

            cur.execute(INSERT_FLAG, build_unverified_flag_row(
                run_id, monitor_date, rec, dh, verified, checked_at))
            loaded += 1

        cur.execute(FINISH_RUN, (run_id,))
        conn.commit()
    except BaseException:
        # BaseException, не Exception: наш собственный SystemExit (расхождение
        # confirmed/url_verified внутри уже открытой транзакции) обязан тоже
        # откатывать явно, а не полагаться на неявный откат при закрытии соединения.
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"✅ Дайджест загружен: run_id={run_id} · monitor_date={monitor_date}\n"
          f"   загружено записей: {loaded} · пропущено дублей (7 дней): {skipped_dup}")
    return run_id


if __name__ == "__main__":
    main()
