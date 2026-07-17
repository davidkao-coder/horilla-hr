#!/bin/bash
# Think4U HRMS — 部署到 Ubuntu 伺服器（192.168.2.135，系統 nginx 同機反代）
#
# 用法（在 Windows git-bash、專案根目錄執行）：
#   bash scripts/deploy_to_server.sh              # 只同步程式 + 重建重啟
#   bash scripts/deploy_to_server.sh --with-data  # 另外把「本機開發 DB」整份搬到伺服器（會覆蓋伺服器 DB！）
#
# 前置（一次性）：ssh-copy-id -p 2425 think4u@192.168.2.135
set -euo pipefail

HOST=192.168.2.135
PORT=2425
USER=think4u
DIR=/home/think4u/hrms
SSH="ssh -p $PORT $USER@$HOST"

cd "$(dirname "$0")/.."

echo "==> 1/4 同步程式碼到 $USER@$HOST:$DIR"
$SSH "mkdir -p $DIR/backups $DIR/media"
tar czf - \
  --exclude=.git --exclude=node_modules --exclude=__pycache__ \
  --exclude=media --exclude=backups --exclude=import_data --exclude=staticfiles \
  --exclude='*.xlsx' --exclude=.env --exclude=.env.prod \
  . | $SSH "tar xzf - -C $DIR"

echo "==> 2/4 上傳 .env.prod"
scp -P $PORT .env.prod $USER@$HOST:$DIR/.env.prod

echo "==> 3/4 伺服器上 build + 啟動"
$SSH "cd $DIR && docker compose -f docker-compose.deploy.yaml --env-file .env.prod up -d --build"

if [[ "${1:-}" == "--with-data" ]]; then
  echo "==> [with-data] 匯出本機開發 DB 並還原到伺服器（覆蓋伺服器 DB）"
  export MSYS_NO_PATHCONV=1
  docker compose exec -T db pg_dump -U postgres -d horilla -O --no-acl > /tmp/t4u_deploy_dump.sql
  scp -P $PORT /tmp/t4u_deploy_dump.sql $USER@$HOST:$DIR/backups/deploy_dump.sql
  $SSH "cd $DIR && \
    docker compose -f docker-compose.deploy.yaml --env-file .env.prod stop server && \
    docker compose -f docker-compose.deploy.yaml --env-file .env.prod exec -T db \
      psql -U \$(grep '^DB_USER=' .env.prod | cut -d= -f2) -d \$(grep '^DB_NAME=' .env.prod | cut -d= -f2) \
      -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' && \
    docker compose -f docker-compose.deploy.yaml --env-file .env.prod exec -T db \
      sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -q -f /backups/deploy_dump.sql' && \
    docker compose -f docker-compose.deploy.yaml --env-file .env.prod start server"
  rm -f /tmp/t4u_deploy_dump.sql
fi

echo "==> 4/4 健康檢查"
sleep 5
$SSH "for i in \$(seq 1 24); do
        CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/health/ || true)
        [ \"\$CODE\" = '200' ] && break; sleep 5;
      done; echo \"health: HTTP \$CODE\""

cat <<'NEXT'

✅ 部署完成。若是第一次部署，還需要在伺服器上設定系統 nginx（一次性）：
  sudo cp /home/think4u/hrms/deploy/nginx-hrms.conf /etc/nginx/sites-available/hrms
  sudo ln -sf /etc/nginx/sites-available/hrms /etc/nginx/sites-enabled/hrms
  sudo nginx -t && sudo systemctl reload nginx
  sudo certbot --nginx -d hrms.think4u-tech.com   # HTTPS（需路由器 80/443 → 192.168.2.135）
NEXT
