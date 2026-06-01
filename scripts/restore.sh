#!/usr/bin/env bash
# Think4U HRMS — 從備份還原（會覆蓋現有資料！）
# 用法：
#   bash scripts/restore.sh ../backup/2026-05-28_143025
#
# 會做的事：
#   1. 確認你真的要還原（要打 yes）
#   2. drop 並重建 horilla DB
#   3. 灌入 db.sql.gz
#   4. 解開 media.tar.gz 覆蓋 ./media
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "用法：bash scripts/restore.sh <備份資料夾>"
  echo ""
  echo "可用的備份："
  ls -1dt ../backup/*/ ./backups/*/ 2>/dev/null | head -10 || echo "  （無）"
  exit 1
fi

SRC="$1"
if [ ! -f "$SRC/db.sql.gz" ]; then
  echo "❌ 找不到 $SRC/db.sql.gz"
  exit 1
fi

echo "⚠️  即將從 $SRC 還原："
echo "    - 會 DROP + 重建 horilla 資料庫"
[ -f "$SRC/media.tar.gz" ] && echo "    - 會覆蓋 ./media"
echo ""
read -r -p "確認還原？輸入 yes 繼續：" CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "取消"
  exit 0
fi

# 1) 停 server（避免連線中斷），保留 db
echo "==> 停止 server…"
docker compose stop server || true

# 2) DB restore（dump 內含 --clean --if-exists，會自動 drop 物件再建）
echo "==> 還原 PostgreSQL …"
gunzip -c "$SRC/db.sql.gz" | docker compose exec -T db psql -U postgres -d horilla

# 3) media restore
if [ -f "$SRC/media.tar.gz" ]; then
  echo "==> 還原 media …"
  rm -rf ./media
  tar -xzf "$SRC/media.tar.gz"
fi

# 4) 重啟 server
echo "==> 重啟 server…"
docker compose start server

echo ""
echo "✅ 還原完成：$SRC"
