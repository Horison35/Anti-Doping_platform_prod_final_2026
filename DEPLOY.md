# DEPLOY.md — команды запуска, остановки, логов, обновления модели

Платформа сейчас развёрнута на `<IP_СЕРВЕРА>` (Debian 12) и доступна по
`https://antidoping-platform.duckdns.org`. Этот файл — исчерпывающий список
команд для повседневной эксплуатации и для повторного развёртывания с нуля.

## Архитектура развёртывания

```
docker compose (детерминированная часть, без внешних учётных сессий):
  db        — PostgreSQL 16, том pgdata, порт 127.0.0.1:5432
  api       — FastAPI, порт 127.0.0.1:8000
  frontend  — Nginx: отдаёт собранный React + проксирует /api → api:8000, порт 127.0.0.1:8080

хостовые сервисы (systemd, вне docker-compose — см. «Почему» ниже):
  nginx (хост)                       — TLS-терминация, порт 80/443 → 127.0.0.1:8080
  certbot.timer                      — автопродление сертификата Let's Encrypt (встроен пакетом)
  antidoping-backup.timer            — ежедневный pg_dump в ~/backups/antidoping
  antidoping-rating-watcher.timer    — еженедельный прогон parsers/rusada_rating_watcher.py
  antidoping-registry-watcher.service — постоянно слушает data/inbox/registry/ (автопереобучение)
  antidoping-monitor.timer           — АД-Монитор раз в 4 дня (по умолчанию НЕ включён — см. ниже)
```

**Почему АД-Монитор/наблюдатели — на хосте, а не в docker-compose:** `monitor/run_daily.sh`
вызывает `claude -p` в headless-режиме ПОДПИСКИ Claude Code (OAuth-сессия хоста через
`~/.claude`), а не `ANTHROPIC_API_KEY`. Такую сессию нельзя честно упаковать в контейнер без
монтирования домашней папки хоста — решение то же самое, что уже используется на этом сервере
для сопоставимых процессов. `docker compose up` поднимает всё, что не зависит от внешней
пользовательской сессии — это db+api+frontend, ядро Definition of Done.

## Быстрый старт с нуля (новый сервер)

```bash
# 1. Системные пакеты
curl -fsSL https://get.docker.com | sh   # или см. deploy/install_docker.sh
sudo apt-get install -y nginx certbot python3-certbot-nginx rsync

# 2. Код на сервер (с рабочей машины)
rsync -avz --exclude-from=.dockerignore ./ user@server:~/antidoping_platform/
rsync -avz ml/artifacts/*.pkl ml/artifacts/*.json user@server:~/antidoping_platform/ml/artifacts/

# 3. Секреты
cp .env.example .env
# заполнить: POSTGRES_PASSWORD, APP_PASSWORD, SESSION_SECRET (openssl rand -hex 32),
# DUCKDNS_SUBDOMAIN, DUCKDNS_TOKEN

# 4. Поднять контур
docker compose up -d --build
curl -s http://localhost:8000/api/v1/health   # {"status":"ok"}

# 5. Python-окружение для хостовых скриптов (наблюдатели, переобучение)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 6. Загрузить первый прогон (см. «Обновление данных» ниже)
# 7. HTTPS — см. «HTTPS и домен» ниже
# 8. Systemd-таймеры — см. «Хостовые сервисы» ниже
```

## Повседневные команды

```bash
# Запуск / остановка всего контура
docker compose up -d
docker compose down                 # контейнеры удаляются, том pgdata (данные) — нет
docker compose down -v              # ⚠️ ТАКЖЕ удаляет данные БД — только для полного сброса

# Перезапуск одного сервиса
docker compose restart api

# Логи
docker compose logs -f api
docker compose logs -f --tail=200 db
journalctl -u antidoping-monitor.service -f
journalctl -u antidoping-registry-watcher.service -f

# Статус
docker compose ps
systemctl list-timers --all | grep antidoping
```

## Обновление модели (продакшн-артефакт)

Разовая регистрация уже обученной версии как активной (только если `model_artifacts` пуста —
на этом сервере уже сделано при первом деплое):

```bash
source .venv/bin/activate
python3 - <<'PY'
import hashlib, psycopg
from pathlib import Path
dsn = [l.split('=',1)[1] for l in open('.env') if l.startswith('DATABASE_URL=')][0].strip()
pkl = Path('ml/artifacts/prod_ensemble_ВЕРСИЯ.pkl').resolve()
meta = Path('ml/artifacts/meta_ВЕРСИЯ.json').resolve()
h = hashlib.sha256(pkl.read_bytes()).hexdigest()
conn = psycopg.connect(dsn); cur = conn.cursor()
cur.execute("UPDATE antidoping.model_artifacts SET status='retired' WHERE status='active'")
cur.execute("INSERT INTO antidoping.model_artifacts (version, model_path, meta_path, sha256, status) VALUES (%s,%s,%s,%s,'active')",
            (pkl.stem.removeprefix('prod_ensemble_'), str(pkl), str(meta), h))
conn.commit(); conn.close()
PY
```

### Автоматическое переобучение (blue/green, без простоя)

```bash
# Вручную (или положите файл в data/inbox/registry/ — подхватит antidoping-registry-watcher.service)
.venv/bin/python ml/retrain.py --new-data "новый_список_дисквал.xlsx" --trigger manual
```

Что происходит:
1. Прогон **действующей** моделью на новых данных — это одновременно валидация файла
   (не хватает колонок → падает здесь же) и немедленное обновление прогноза без риска.
   Файл повреждён/неполон → `retrain_runs.decision='failed'`, файл уходит в
   `data/inbox/registry/_failed/`, активная модель не тронута, сервис не падает.
2. Если рядом лежит `ml/antidoping_model_production.ipynb` — обучается кандидат.
   **Нет ноутбука** → `decision='rejected'` с причиной «обучение недоступно», прогноз всё
   равно обновлён. Это ожидаемое поведение, пока методика обучения не перенесена в репозиторий.
3. Backtest кандидата против действующей версии (Lift@20, последний закрытый квартал).
   Кандидат не хуже (порог `RETRAIN_MIN_LIFT_RATIO` в `.env`, по умолчанию 95%) →
   `promote_model_artifact()` + атомарная подмена `ml/artifacts/current/` → промоушен.
   Хуже → `rejected`, активная версия продолжает работать.

Журнал решений: `SELECT * FROM antidoping.retrain_runs ORDER BY retrain_id DESC;`

**Чтобы включить настоящее обучение:** положите `antidoping_model_production.ipynb` в `ml/`.
Контракт: ноутбук должен прочитать переменные окружения `ANTIDOPING_TRAIN_DATA` (путь к новому
xlsx) и `ANTIDOPING_TRAIN_OUT` (папка) и сохранить туда `prod_ensemble_<версия>.pkl` +
`meta_<версия>.json` той же структуры полей, что уже есть в `ml/artifacts/meta_*.json`.

## АД-Монитор — включение (один ручной шаг)

Claude Code CLI и Node.js уже установлены на сервере (`claude --version`). Осталось:

```bash
ssh user@server
claude login   # интерактивный OAuth — откройте показанную ссылку в браузере, войдите под своей подпиской
claude -p "1+1" --output-format json   # проверка headless-режима
```

После успешного входа — ручная проверка перед автоматикой (как советует сам скрипт):

```bash
cd ~/antidoping_platform
AD_MONITOR_SKIP_LOAD=1 ./monitor/run_daily.sh   # прогон без записи в БД, посмотреть сырой JSON
./monitor/run_daily.sh                          # штатный прогон с записью в БД
sudo systemctl enable --now antidoping-monitor.timer   # включить расписание (раз в 4 дня)
```

## HTTPS и домен

Уже настроено: DuckDNS-поддомен `antidoping-platform.duckdns.org` → `<IP_СЕРВЕРА>`,
сертификат Let's Encrypt через `certbot --nginx`, автопродление — встроенный `certbot.timer`.

Если IP сервера сменится:
```bash
curl "https://www.duckdns.org/update?domains=antidoping-platform&token=$DUCKDNS_TOKEN&ip="
```
Рекомендуется поставить это в cron раз в 5–10 минут на случай смены IP (сейчас — статический,
одноразового вызова достаточно; если провайдер меняет адрес динамически, добавьте:
`*/10 * * * * curl -s "https://www.duckdns.org/update?domains=antidoping-platform&token=...&ip=" >/dev/null`).

Обновить сертификат вручную (обычно не требуется — таймер делает это сам):
```bash
sudo certbot renew --dry-run   # проверка
sudo certbot renew             # реальное продление
```

## Бэкапы и восстановление

```bash
./db/backup.sh                          # разовый бэкап (systemd-таймер делает это ежедневно в 03:30)
ls ~/backups/antidoping/                # хранятся BACKUP_KEEP_DAYS дней (по умолчанию 30)

# Восстановление из бэкапа
gunzip -c ~/backups/antidoping/antidoping_ДАТА.sql.gz | docker compose exec -T db psql -U antidoping -d antidoping
```

## Диагностика

```bash
# Сервис не отвечает
docker compose ps                       # все ли healthy
docker compose logs --tail=100 api

# HTTPS не открывается
sudo nginx -t                           # синтаксис конфига
sudo systemctl status nginx
curl -v https://antidoping-platform.duckdns.org/api/v1/health

# Нет данных на дашборде (пустые экраны)
docker compose exec db psql -U antidoping -d antidoping -c "SELECT * FROM antidoping.v_snapshots;"
# пусто → прогон не загружен, см. README «Прогон модели/SIAR вручную»

# АД-Монитор молчит
journalctl -u antidoping-monitor.service --no-pager -n 50
cat monitor/logs/run_*.log | tail -50
```

## Локальная разработка (Мак/Linux, без сервера)

```bash
cp .env.example .env    # COOKIE_SECURE=false для http://localhost без TLS
docker compose up -d --build
cd frontend && npm install && npm run dev   # dev-сервер на :5173 с прокси на api:8000
```
