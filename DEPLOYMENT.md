# Think4U HRMS 部署指南

## 開發環境

```bash
docker compose up -d --build
# 瀏覽 http://localhost:8001
# 預設 admin / admin
```

## 生產環境

### 1. 準備

```bash
git clone <fork-url> think4u-hrms
cd think4u-hrms

# 複製環境變數樣板並填入實際值
cp .env.prod.example .env.prod
nano .env.prod
```

**.env.prod 重點欄位：**
- `SECRET_KEY` — `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DAILY_VERIFICATION_CODE_SECRET` — `python -c "import base64,secrets; print(base64.b32encode(secrets.token_bytes(20)).decode())"`
- `DB_PASSWORD` — 強密碼
- `ALLOWED_HOSTS` — 你的網域

### 2. SSL 憑證

放兩個檔案：
- `nginx/ssl/think4u.crt`
- `nginx/ssl/think4u.key`

或用 Let's Encrypt：
```bash
# 先用 HTTP 啟動 nginx，跑 certbot
certbot --nginx -d hrms.your-domain.com
# 完成後將憑證複製到 nginx/ssl/
```

### 3. 啟動

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.prod up -d --build

# 初次部署：建立 admin / 設定角色 / 灌種子（如需要）
docker compose -f docker-compose.prod.yaml exec server python manage.py createsuperuser
docker compose -f docker-compose.prod.yaml exec server python manage.py configure_roles
docker compose -f docker-compose.prod.yaml exec server python manage.py seed_think4u_data  # 可選
```

### 4. Cron 排程（在 host 上設定）

```bash
crontab -e
```

加入：
```
# 每年 1/1 重置特休
0 0 1 1 *   cd /path/to/think4u-hrms && docker compose -f docker-compose.prod.yaml exec -T server python manage.py sync_annual_leave

# 每日 1:00 偵測滿 6 個月補給特休
0 1 * * *   cd /path/to/think4u-hrms && docker compose -f docker-compose.prod.yaml exec -T server python manage.py grant_six_month_leave

# 每年 12/31 23:59 結算年度
59 23 31 12 * cd /path/to/think4u-hrms && docker compose -f docker-compose.prod.yaml exec -T server python manage.py year_end_leave_settlement --output-dir /var/think4u-reports
```

### 5. 備份

`docker-compose.prod.yaml` 內建一個 `backup` 服務，每 24 小時自動 `pg_dump` 到 `./backups/` 並保留 30 天。

手動備份：
```bash
docker compose -f docker-compose.prod.yaml exec -T db pg_dump -U $DB_USER $DB_NAME > backup-$(date +%Y%m%d).sql
```

還原：
```bash
docker compose -f docker-compose.prod.yaml exec -T db psql -U $DB_USER -d $DB_NAME < backup-20260101.sql
```

### 6. 升級 / 維護

```bash
# 拉新版
git pull
docker compose -f docker-compose.prod.yaml up -d --build

# 跑 migrations
docker compose -f docker-compose.prod.yaml exec server python manage.py migrate

# 重編譯翻譯（若 .po 有更新）
docker compose -f docker-compose.prod.yaml exec server python manage.py compilemessages -l zh_Hant

# 收 static
docker compose -f docker-compose.prod.yaml exec server python manage.py collectstatic --noinput
```

### 7. 監控

健康檢查端點：`https://hrms.your-domain.com/health/`

回應 `{"status":"ok"}` 表示存活。

### 8. 與官方 Horilla 同步 bug fix

```bash
git remote -v   # 確認有 upstream
git fetch upstream
git merge upstream/1.0  # 或 upstream/master
# 解衝突後
docker compose -f docker-compose.prod.yaml up -d --build
```
