#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ml/watch_registry.py — файл-триггер автопереобучения (СЛОЙ 2).

Наблюдает за папкой data/inbox/registry/ (создаётся при первом запуске).
Загрузка нового файла базы дисквалификаций СЮДА (вручную или другим
процессом — например, будущим приёмом файла через веб-интерфейс) сама
инициирует цикл переобучения и пересчёта прогноза — без ручного запуска
команды (ТЗ п. 4).

Устойчивость к «ещё пишется»: ждём, пока размер файла не перестанет расти
между двумя проверками (STABLE_CHECKS подряд) — иначе можно схватить
наполовину загруженный xlsx и получить ложный «файл повреждён».

Запуск (обычно — systemd-сервис, см. DEPLOY.md):
    python ml/watch_registry.py --inbox data/inbox/registry
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("watch_registry")

STABLE_CHECKS = 3
STABLE_INTERVAL_SECONDS = 2.0
VALID_SUFFIXES = (".xlsx", ".xls")


def wait_until_stable(path: Path) -> bool:
    """True, если размер файла не менялся STABLE_CHECKS проверок подряд."""
    last_size = -1
    stable_count = 0
    for _ in range(60):  # максимум ~2 минуты ожидания
        if not path.exists():
            return False
        size = path.stat().st_size
        if size == last_size and size > 0:
            stable_count += 1
            if stable_count >= STABLE_CHECKS:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(STABLE_INTERVAL_SECONDS)
    return False


def process_new_file(path: Path, processed_dir: Path, failed_dir: Path) -> None:
    logger.info("Новый файл в очереди: %s — жду стабилизации размера…", path.name)
    if not wait_until_stable(path):
        logger.error("Файл %s не стабилизировался — пропускаю (возможно, ещё копируется)", path.name)
        return

    logger.info("Запускаю ml/retrain.py для %s", path.name)
    result = subprocess.run(
        [sys.executable, str(ROOT / "ml" / "retrain.py"),
         "--new-data", str(path), "--trigger", "file_watch"],
        capture_output=True, text=True, timeout=8 * 3600,
    )
    logger.info("retrain.py stdout:\n%s", result.stdout[-4000:])
    if result.returncode != 0:
        logger.error("retrain.py завершился с ошибкой (код %s):\n%s", result.returncode, result.stderr[-4000:])
        failed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(failed_dir / path.name))
        logger.error(
            "Файл перемещён в %s — активная модель НЕ пострадала, сервис продолжает "
            "работать на прежней версии (ALERT: требуется ручная проверка файла)",
            failed_dir,
        )
        return

    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(processed_dir / path.name))
    logger.info("✅ %s обработан, перемещён в %s", path.name, processed_dir)


def watch_forever(inbox: Path, poll_seconds: float) -> None:
    processed_dir = inbox / "_processed"
    failed_dir = inbox / "_failed"
    seen: set[str] = set()
    logger.info("Наблюдаю за %s (опрос каждые %.0fс)…", inbox, poll_seconds)
    while True:
        for path in sorted(inbox.iterdir()) if inbox.exists() else []:
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                process_new_file(path, processed_dir, failed_dir)
            except Exception:
                logger.exception("Необработанная ошибка при обработке %s", path.name)
        time.sleep(poll_seconds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=str(ROOT / "data" / "inbox" / "registry"))
    ap.add_argument("--poll-seconds", type=float, default=30.0)
    ap.add_argument("--once", action="store_true", help="обработать текущие файлы и выйти (для тестов/cron)")
    args = ap.parse_args()

    inbox = Path(args.inbox)
    inbox.mkdir(parents=True, exist_ok=True)

    if args.once:
        processed_dir = inbox / "_processed"
        failed_dir = inbox / "_failed"
        for path in sorted(inbox.iterdir()):
            if path.is_file() and path.suffix.lower() in VALID_SUFFIXES:
                process_new_file(path, processed_dir, failed_dir)
        return 0

    watch_forever(inbox, args.poll_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
