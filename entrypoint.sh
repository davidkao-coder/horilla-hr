#!/bin/bash

echo "Waiting for database to be ready..."

# Think4U: 還原 Horilla 掛在 auth.User 的 is_new_employee migration。
# 此欄位以 User.add_to_class 加在內建 auth app，migration 檔（auth/migrations/0013_user_is_new_employee.py）
# 原存在 venv site-packages，重建 image 會清掉 → migration graph 缺節點、makemigrations/migrate 全失敗。
# 從版控 patch 複製回 auth migrations 目錄，確保重建後仍可解析。
AUTH_MIG_DIR="$(python3 -c 'import os, django.contrib.auth.migrations as m; print(os.path.dirname(m.__file__))' 2>/dev/null)"
if [ -n "$AUTH_MIG_DIR" ] && [ ! -f "$AUTH_MIG_DIR/0013_user_is_new_employee.py" ]; then
    cp horilla/auth_migrations_patch/0013_user_is_new_employee.py "$AUTH_MIG_DIR/" 2>/dev/null \
        && echo "restored auth.0013_user_is_new_employee migration"
fi

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
