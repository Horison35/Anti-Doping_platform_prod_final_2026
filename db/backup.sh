#!/bin/bash
# db/backup.sh — ежедневный бэкап PostgreSQL (LOGIC.md §7).
#
# Запуск (systemd timer, см. DEPLOY.md) — один раз в сутки:
#   db/backup.sh [папка_назначения]
# По умолчанию — /home/<user>/backups/antidoping (создаётся при первом запуске).
# Хранит последние KEEP_DAYS дней, старее — удаляет.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKUP_DIR="${1:-$HOME/backups/antidoping}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
mkdir -p "$BACKUP_DIR"

# .env — тот же формат, что читают db/loaders (KEY=VALUE, без внешних зависимостей)
if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source <(grep -v '^#' "$ROOT/.env" | grep '=')
    set +a
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$BACKUP_DIR/antidoping_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] Бэкап БД → $OUT_FILE"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-antidoping}" "${POSTGRES_DB:-antidoping}" \
    | gzip > "$OUT_FILE"

echo "[$(date '+%F %T')] Готово: $(du -h "$OUT_FILE" | cut -f1)"

# Ротация — старше KEEP_DAYS дней
find "$BACKUP_DIR" -name 'antidoping_*.sql.gz' -mtime "+${KEEP_DAYS}" -print -delete
