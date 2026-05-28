#!/usr/bin/env bash
# Think4U HRMS — 一鍵備份（dev / prod 通用）
# 用法：
#   bash scripts/backup.sh             # 備份到 ./backups/<時間戳>/
#   bash scripts/backup.sh /d/some/dir # 備份到指定資料夾
#
# 內容：
#   1. db.sql.gz  : PostgreSQL pg_dump（壓縮）
#   2. media.tar.gz : ./media 上傳檔
#
# 自動清理：保留最近 30 份
set -euo pipefail

# 切到專案根（script 位於 ./scripts/）
cd "$(dirname "$0")/.."

TS=$(date +%Y-%m-%d_%H%M%S)
ROOT="${1:-./backups}"
OUT="$ROOT/$TS"
mkdir -p "$OUT"

echo "==> Think4U 備份 $TS"
echo "    目標：$OUT"

# 1) PostgreSQL dump (在 db container 內跑 pg_dump，pipe 到 host 後壓縮)
echo "==> pg_dump …"
docker compose exec -T db pg_dump -U postgres -d horilla --clean --if-exists \
  | gzip > "$OUT/db.sql.gz"
DB_SIZE=$(du -h "$OUT/db.sql.gz" | cut -f1)
echo "    db.sql.gz ($DB_SIZE)"

# 2) media 檔案
if [ -d "./media" ] && [ -n "$(ls -A ./media 2>/dev/null)" ]; then
  echo "==> 打包 media …"
  tar -czf "$OUT/media.tar.gz" media
  MEDIA_SIZE=$(du -h "$OUT/media.tar.gz" | cut -f1)
  echo "    media.tar.gz ($MEDIA_SIZE)"
else
  echo "==> media 為空，跳過"
fi

# 3) 自動清理：保留最近 30 份
echo "==> 清理過舊備份（保留最近 30 份）…"
( cd "$ROOT" && ls -1dt */ 2>/dev/null | tail -n +31 | xargs -r rm -rf )

echo ""
echo "✅ 備份完成：$OUT"
ls -lh "$OUT"
