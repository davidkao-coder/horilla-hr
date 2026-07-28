# 04 維運 Runbook（Think4U HRMS）

> 出事時照這份做。環境有兩套：本機開發（Windows）與正式（Ubuntu）。

## 1. 環境總覽
| | 開發 | 正式 |
|---|---|---|
| 主機 | Windows 11（開發者電腦）| Ubuntu `192.168.2.135`（SSH port **2425**、帳號 `think4u`）|
| 專案路徑 | `D:\3.develop\98.hrms_Horilla\honsi-hrms` | `/home/think4u/hrms` |
| Compose 檔 | `docker-compose.yaml` + `override` | `docker-compose.deploy.yaml` + `--env-file .env.prod` |
| 入口 | http://localhost:8001 | 系統 nginx → `127.0.0.1:8091` → 容器 8000 |
| 網域 | —（測試用 ngrok）| https://hrms.think4u-tech.com（DNS → 106.104.136.29，路由器需轉 80/443 → .135）|

正式機常用前綴（以下簡稱 `dc`）：
```bash
cd /home/think4u/hrms
alias dc='docker compose -f docker-compose.deploy.yaml --env-file .env.prod'
```

## 2. 部署
### 日常更新（程式改版）
本機 git-bash：
```bash
bash scripts/deploy_to_server.sh          # 密碼認證約輸入 4 次
```
### 首次/重建含資料
```bash
bash scripts/deploy_to_server.sh --with-data   # ⚠️ 會覆蓋伺服器 DB
```
### 手動流程（腳本不可用時）
打 tar（排除 .git/media/backups…）→ scp → 伺服器解壓到 `/home/think4u/hrms` → `dc up -d --build`。
資料還原：`dc stop server` → db 內 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` → `psql -f /backups/xxx.sql` → `dc start server`。

### nginx / HTTPS（一次性）
```bash
sudo cp /home/think4u/hrms/deploy/nginx-hrms.conf /etc/nginx/sites-available/hrms
sudo ln -sf /etc/nginx/sites-available/hrms /etc/nginx/sites-enabled/hrms
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d hrms.think4u-tech.com     # 憑證自動續期由 certbot.timer 處理
```

## 3. 備份與還原
| 項目 | 位置/方式 |
|---|---|
| 正式自動備份 | compose 內 `backup` service 每日 `pg_dump` → `/home/think4u/hrms/backups/`，保留 30 天 |
| 開發手動備份 | `bash scripts/backup.sh`（或 `backup.bat`）→ 預設輸出 `../backup/` |
| 還原 | `bash scripts/restore.sh <備份目錄>`；正式機用上面手動流程 |
| **異地備份 ⚠️** | 尚未設定——backups 只在同一台機器，建議 rsync 到 NAS 或雲端 |

## 4. 排程（建議設定，尚未全部建立）
| 排程 | 指令 | 頻率 |
|---|---|---|
| 未打卡提醒 | `dc exec -T server python manage.py notify_unpunched` | 週一–五 10:30 |
| 稽核清理 | `dc exec -T server python manage.py purge_audit_log` | 每月 1 日 03:00 |
| 備份 | （backup service 已內建）| 每日 |

crontab 範例（正式機 `crontab -e`）：
```cron
30 10 * * 1-5 cd /home/think4u/hrms && docker compose -f docker-compose.deploy.yaml --env-file .env.prod exec -T server python manage.py notify_unpunched
0 3 1 * *    cd /home/think4u/hrms && docker compose -f docker-compose.deploy.yaml --env-file .env.prod exec -T server python manage.py purge_audit_log
```

## 5. 健康檢查與監控
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -H "X-Forwarded-Proto: https" http://127.0.0.1:8091/health/
dc ps          # 容器狀態
dc logs -f --tail=30 server
```

## 6. 故障排除（實際案例）
| 症狀 | 原因 | 處置 |
|---|---|---|
| health 回 **301** | 正常！DEBUG=False 強制 HTTPS 轉向 | 檢查時帶 `-H "X-Forwarded-Proto: https"` |
| health 回 **000** | 容器還在開機（每次啟動跑 migrate/翻譯/collectstatic 約 1–3 分鐘）或已掛 | `dc logs -f server` 等 `Listening at:`；掛了看錯誤 |
| **500** + log 出現 `relation ... does not exist` | DB 是空的（還原沒跑完 / migrate 失敗）| 重跑資料還原流程（§2）；驗證：`dc exec -T db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT count(*) FROM employee_employee;"'` |
| `NodeNotFoundError: auth.0013...` | image 重建後 auth migration patch 沒還原 | 見 docs/02 M3；entrypoint 會自動處理，確認 `horilla/auth_migrations_patch/` 存在 |
| 登入 **403 CSRF** | 網域不在 `CSRF_TRUSTED_ORIGINS` | 加進 `.env.prod`（正式）或 override（開發）後重啟 |
| Google 登入 `redirect_uri_mismatch` | Console 登記的 URI 與實際不符 | 登記值須為 `https://<網域>/google/callback`（根路徑、無斜線）|
| 換頁第一下卡、第二下秒回 | gunicorn worker 不足 | 確認 GUNICORN_WORKERS/THREADS env（deploy 預設 3×4）|
| 郵件都沒寄 | SMTP 未設定（`_safe_send` 靜默略過）| `.env.prod` 填 EMAIL_* 後 `dc restart server` |
| ngrok 3004 | tunnel 指錯 port/協定 | `ngrok http 8001`（本機開發埠）|

## 7. 版本升級注意
- 改了 `.py` → 正式機要 `dc up -d --build`（image 內含程式，非掛載）。
- 改了 po → build 內含 compilemessages，不用另外處理。
- **每年勞健保級距調整** → 改 `think4u/payroll_rules.py` 的 `LABOR_GRADES`/`HEALTH_GRADES`（連動投保薪資下拉與計算）。
- 上游 Horilla 升級：原則上**不做**（見 docs/02 §1）。
