#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rusada_rating_watcher.py — наблюдатель за рейтингами РУСАДА.

Что делает при каждом запуске (запускается по расписанию: cron / Планировщик Windows):
  1. Открывает страницу рейтингов РУСАДА.
  2. Находит ссылки на целевые файлы по шаблону названия («Рейтинг ОСФ …», «Рейтинг регионов …»).
  3. Скачивает файл, считает SHA-256 и сравнивает с последней известной версией.
  4. Файл изменился (или его ещё не было) → сохраняет версионированную копию
     data/ratings/<id>/<дата>__<имя файла> и обновляет state.json.
  5. Для каждого обновившегося рейтинга запускает hook-команду (пересборка отчёта).
  6. Пишет журнал в watcher.log. Любая нештатная ситуация — строка ALERT и ненулевой
     код выхода, чтобы планировщик/оркестратор её заметил.

Принципы:
  · Ничего не додумывает: не нашёл ссылку по шаблону — ALERT, а не «наверное не обновилось».
  · Версии не перезаписываются: каждая редакция рейтинга хранится отдельным файлом
    (это снапшоты для воспроизводимости — какой файл лежал в основе какого прогона).
  · Вежливость к источнику: один запуск = один заход на страницу + скачивание только
    изменившихся файлов. Рекомендуемая частота — 1 раз в сутки, не чаще.

Зависимости: pip install requests
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

# ══════════════════════════ НАСТРОЙКИ ══════════════════════════

BASE_DIR   = Path(__file__).resolve().parent
DATA_DIR   = BASE_DIR / "data" / "ratings"     # версионированные копии
STATE_FILE = BASE_DIR / "state.json"           # что и какой версии уже скачано
LOG_FILE   = BASE_DIR / "watcher.log"

# Страницы, на которых РУСАДА публикует рейтинги.
# Если структура сайта поменяется — поправить здесь (watcher сам скажет ALERT).
RATING_PAGES = [
    "https://rusada.ru/education/ratings.php",
    "https://rusada.ru/federations_leagues/raiting/",
]

# Целевые файлы: id → шаблон текста ссылки/имени файла + допустимые расширения.
TARGETS = [
    {
        "id": "osf",
        "title": "Рейтинг ОСФ",
        "pattern": re.compile(r"рейтинг[\s\-–—]*осф", re.IGNORECASE),
        "extensions": (".pdf",),
        # Команда после обновления (пути поправить под свою машину); None — ничего не запускать.
        "on_update": [sys.executable, str(BASE_DIR / "build_report.py")],
    },
    {
        "id": "regions",
        "title": "Рейтинг регионов",
        "pattern": re.compile(r"рейтинг[\s\-–—]*регион", re.IGNORECASE),
        "extensions": (".xlsx", ".xls"),
        "on_update": None,  # сюда — скрипт регионального отчёта, когда будет готов
    },
]

HEADERS = {
    # Представляемся обычным браузером — сайт отдаёт файлы любому клиенту,
    # но дефолтный UA питона местами режется.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TIMEOUT = 60          # сек на запрос
RETRIES = 3           # попыток на каждый запрос
RETRY_PAUSE = 10      # сек между попытками

# ══════════════════════════ СЛУЖЕБНОЕ ══════════════════════════

def log(msg, alert=False):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {'ALERT ' if alert else ''}{msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get(url, stream=False):
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=stream)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 — фиксируем любую сетевую беду
            last_err = e
            log(f"попытка {attempt}/{RETRIES} не удалась: {url} → {e}")
            time.sleep(RETRY_PAUSE)
    raise RuntimeError(f"не удалось получить {url}: {last_err}")


LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def find_links(page_html, page_url):
    """Все ссылки страницы: (абсолютный URL, видимый текст ссылки)."""
    links = []
    for href, inner in LINK_RE.findall(page_html):
        text = TAG_RE.sub(" ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        links.append((urljoin(page_url, href), text))
    return links


def _year_of(url, text):
    """Максимальный четырёхзначный год, найденный в тексте ссылки или имени файла (0 — не найден)."""
    years = [int(y) for y in re.findall(r"(20\d{2})", f"{text} {url.split('/')[-1]}")]
    return max(years) if years else 0


def match_target(target, links):
    """Ищем ссылку целевого файла: сначала по тексту ссылки, затем по имени файла в href.
    На странице могут висеть архивные редакции прошлых лет — возвращаем ТОЛЬКО самую
    свежую (максимальный год в названии); иначе архив затирал бы состояние и давал
    ложные «обновления» на каждом прогоне."""
    found = []
    for url, text in links:
        if not url.lower().split("?")[0].endswith(target["extensions"]):
            continue
        fname = url.split("/")[-1]
        if target["pattern"].search(text) or target["pattern"].search(fname):
            found.append((url, text or fname))
    if not found:
        return []
    found.sort(key=lambda ut: _year_of(*ut), reverse=True)
    best_year = _year_of(*found[0])
    skipped = [t for u, t in found[1:] if _year_of(u, t) < best_year]
    if skipped:
        log(f"[{target['id']}] архивные редакции пропущены: {'; '.join(skipped)}")
    return [found[0]]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ══════════════════════════ ОСНОВНОЙ ЦИКЛ ══════════════════════════

def run():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    exit_code = 0
    updated_targets = []

    # 1. Собираем ссылки со всех страниц рейтингов
    all_links = []
    pages_ok = 0
    for page in RATING_PAGES:
        try:
            html = http_get(page).text
            page_links = find_links(html, page)
            all_links.extend(page_links)
            pages_ok += 1
            log(f"страница получена: {page} · ссылок: {len(page_links)}")
        except Exception as e:  # noqa: BLE001
            log(f"страница недоступна: {page} → {e}", alert=True)
            exit_code = 1

    if pages_ok == 0:
        log("ни одна страница рейтингов не открылась — прогон прерван", alert=True)
        return 2

    # 2. По каждой цели: найти → скачать → сравнить → сохранить
    for target in TARGETS:
        tid = target["id"]
        candidates = match_target(target, all_links)

        if not candidates:
            log(f"[{tid}] ссылка по шаблону «{target['title']}» НЕ найдена — "
                f"проверить структуру страницы вручную", alert=True)
            exit_code = 1
            continue

        # Если редакций несколько — обрабатываем каждую (они различаются URL/хэшем)
        for url, text in candidates:
            try:
                resp = http_get(url)
                blob = resp.content
            except Exception as e:  # noqa: BLE001
                log(f"[{tid}] файл не скачался: {url} → {e}", alert=True)
                exit_code = 1
                continue

            digest = sha256_bytes(blob)
            known = state.get(tid, {})
            if known.get("sha256") == digest:
                log(f"[{tid}] без изменений (sha256 совпадает): «{text}»")
                continue

            # Новая редакция → версионированная копия
            orig_name = url.split("/")[-1].split("?")[0] or f"{tid}{target['extensions'][0]}"
            stamp = datetime.now().strftime("%Y-%m-%d")
            tdir = DATA_DIR / tid
            tdir.mkdir(parents=True, exist_ok=True)
            dest = tdir / f"{stamp}__{orig_name}"
            dest.write_bytes(blob)

            # Стабильная ссылка «текущая версия» для скриптов-потребителей
            latest = tdir / f"latest{Path(orig_name).suffix}"
            shutil.copyfile(dest, latest)

            prev = known.get("sha256", "—")
            state[tid] = {
                "sha256": digest,
                "url": url,
                "link_text": text,
                "file": str(dest),
                "downloaded_at": datetime.now().isoformat(timespec="seconds"),
                "previous_sha256": prev,
            }
            save_state(state)
            log(f"[{tid}] ОБНОВЛЕНИЕ: «{text}» → {dest.name} (sha256 {digest[:12]}…, прежний {str(prev)[:12]}…)")
            updated_targets.append(target)

    # 3. Хуки пересборки — только для реально обновившихся целей
    for target in updated_targets:
        cmd = target.get("on_update")
        if not cmd:
            continue
        log(f"[{target['id']}] запускаю пересборку: {' '.join(map(str, cmd))}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            tail = (res.stdout or res.stderr or "").strip().splitlines()[-3:]
            log(f"[{target['id']}] пересборка завершена, код {res.returncode}; хвост вывода: {' | '.join(tail)}")
            if res.returncode != 0:
                exit_code = 1
        except Exception as e:  # noqa: BLE001
            log(f"[{target['id']}] пересборка упала: {e}", alert=True)
            exit_code = 1

    if not updated_targets:
        log("итог прогона: обновлений нет")
    else:
        log(f"итог прогона: обновлено целей — {len(updated_targets)}: "
            + ", ".join(t["id"] for t in updated_targets))
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
