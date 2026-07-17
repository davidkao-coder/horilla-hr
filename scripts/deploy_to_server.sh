#!/bin/bash
# Think4U HRMS — 部署到 Ubuntu 伺服器（192.168.2.135，系統 nginx 同機反代 127.0.0.1:8091）
#
# 用法（在 Windows git-bash、專案根目錄執行）：
#   bash scripts/deploy_to_server.sh              # 只同步程式 + 重建重啟（日常更新用）
#   bash scripts/deploy_to_server.sh --with-data  # 另外把「本機開發 DB」搬到伺服器（覆蓋伺服器 DB！首次部署用）
#
# 密碼認證下全程約輸入密碼 3 次（--with-data 為 5 次）；
# 想免密碼：ssh-copy-id -p 2425 think4u@192.168.2.135
set -euo pipefail

HOST=192.168.2.135
PORT=2425
USER=think4u
DIR=/home/think4u/hrms
SSH="ssh -p $PORT $USER@$HOST"
COMPOSE="docker compose -f docker-compose.deploy.yaml --env-file .env.prod"

cd "$(dirname "$0")/.."
[ -f .env.prod ] || { echo "!! 找不到 .env.prod（應在專案根目錄）"; exit 1; }

echo "==> 1/3 檢查 docker + 同步程式碼到 $USER@$HOST:$DIR（密碼 1/3）"
tar czf - \
  --exclude=.git --exclude=node_modules --exclude=__pycache__ \
  --exclude=media --exclude=backups --exclude=import_data --exclude=staticfiles \
  --exclude='*.xlsx' --exclude=.env --exclude=.env.prod \
  . | $SSH "command -v docker >/dev/null 2>&1 || { echo '!! 伺服器未安裝 docker：請先跑  curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER  後重新登入'; exit 42; }
            mkdir -p $DIR/backups $DIR/media && tar xzf - -C $DIR && echo '   程式碼同步完成'"

echo "==> 2/3 上傳 .env.prod（密碼 2/3）"
scp -P $PORT .env.prod $USER@$HOST:$DIR/.env.prod

echo "==> 3/3 伺服器 build + 啟動 + 健康檢查（密碼 3/3；首次 build 需數分鐘）"
$SSH "cd $DIR && $COMPOSE up -d --build && \
      echo '   等待服務啟動…' && \
      for i in \$(seq 1 36); do
        CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/health/ || true)
        [ \"\$CODE\" = '200' ] && break; sleep 5;
      done; echo \"   健康檢查: HTTP \$CODE\""

if [[ "${1:-}" == "--with-data" ]]; then
  echo "==> [with-data] 匯出本機 DB（不需密碼）"
  export MSYS_NO_PATHCONV=1
  docker compose exec -T db pg_dump -U postgres -d horilla -O --no-acl > /tmp/t4u_deploy_dump.sql
  echo "    dump 大小: $(du -h /tmp/t4u_deploy_dump.sql | cut -f1)"

  echo "==> [with-data] 上傳 dump（密碼 4/5）"
  scp -P $PORT /tmp/t4u_deploy_dump.sql $USER@$HOST:$DIR/backups/deploy_dump.sql

  echo "==> [with-data] 還原到伺服器 DB — 覆蓋（密碼 5/5）"
  $SSH "cd $DIR && \
    $COMPOSE stop server >/dev/null && \
    $COMPOSE exec -T db sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -q -c \"DROP SCHEMA public CASCADE; CREATE SCHEMA public;\"' && \
    $COMPOSE exec -T db sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -q -f /backups/deploy_dump.sql' >/dev/null && \
    $COMPOSE start server >/dev/null && \
    echo '   資料還原完成，服務重啟中…' && sleep 8 && \
    for i in \$(seq 1 24); do
      CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/health/ || true)
      [ \"\$CODE\" = '200' ] && break; sleep 5;
    done; echo \"   健康檢查: HTTP \$CODE\""
  rm -f /tmp/t4u_deploy_dump.sql
fi

cat <<'NEXT'

✅ 部署完成。第一次部署還需在「伺服器上」設定系統 nginx（一次性，需 sudo）：
  sudo cp /home/think4u/hrms/deploy/nginx-hrms.conf /etc/nginx/sites-available/hrms
  sudo ln -sf /etc/nginx/sites-available/hrms /etc/nginx/sites-enabled/hrms
  sudo nginx -t && sudo systemctl reload nginx
  sudo certbot --nginx -d hrms.think4u-tech.com   # HTTPS（需路由器 80/443 → 192.168.2.135）

設定完成後開 https://hrms.think4u-tech.com 驗證（帳密與開發機相同）。
NEXT
