#!/bin/bash

echo "Waiting for database to be ready..."
python3 manage.py makemigrations
python3 manage.py migrate
python3 manage.py compilemessages -l zh_Hant
python3 manage.py collectstatic --noinput
python3 manage.py createhorillauser --first_name admin --last_name admin --username admin --password admin --email admin@example.com --phone 1234567890
# Think4U: 預設只有 1 個 sync worker → 所有請求序列化，背景輪詢（通知/訊息）
# 佔住唯一 worker 時，使用者點換頁會卡在佇列等待（第一下 loading、再點才秒回）。
# 改用 gthread：2 workers × 4 threads = 8 併發，避免互相阻塞；記憶體只 ~2 份。
# 可用環境變數覆寫：GUNICORN_WORKERS / GUNICORN_THREADS / GUNICORN_TIMEOUT
gunicorn --bind 0.0.0.0:8000 \
  --worker-class gthread \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  horilla.wsgi:application
