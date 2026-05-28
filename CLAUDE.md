# THINK4U-HRMS 開發規範

## 專案身份
- 基底：Think4U-Tech HRMS（官方 https://github.com/horilla/horilla-hr）
- Fork：https://github.com/davidkao-coder/horilla-hr
- 客製化目的：Think4U Tech內部人事管理系統
- 語言：繁體中文介面（zh-hant）

## 技術棧
- Backend：Python 3.10 + Django 4.2 + PostgreSQL 16
- Frontend：HTMX + Bootstrap 5（Horilla 原生）
- 部署：Docker Compose

## 目錄結構規範
- 所有新增 Django app 放在 think4u/ 子目錄下
- 客製化 template 放在 templates/think4u/ 下（不直接改 Horilla 原生 template）
- 客製化 CSS/JS 放在 static/think4u/ 下
- Migration 使用 think4u_{app_name}_{number} 命名前綴

## 開發原則
- 優先使用 Horilla 原生 Signal 和 Hook，不直接 monkey-patch
- 所有新增 Model 必須有對應 Migration
- 新增功能需在本檔案 Changelog 區塊記錄
- Email 通知使用 Django send_mail，SMTP 設定由 .env 注入

## 環境變數（.env）
- DEBUG=False（生產），True（開發）
- TIME_ZONE=Asia/Taipei
- LANGUAGE_CODE=zh-hant
- DATABASE_URL=postgres://...
- EMAIL_HOST、EMAIL_PORT、EMAIL_HOST_USER、EMAIL_HOST_PASSWORD
- DAILY_VERIFICATION_CODE_SECRET=（每日驗證碼 TOTP secret）

## Docker 開發指令
- 啟動：`docker compose up -d`
- 查看 log：`docker compose logs -f server`
- 進入 shell：`docker compose exec server bash`
- 執行 manage.py：`docker compose exec server python manage.py <cmd>`
- 重啟：`docker compose restart server`

## 平台注意事項（Windows 開發者）
- 寫 shell script 時，務必保持 LF 換行（不可 CRLF），否則 Linux 容器內無法執行
- Git 用 `core.autocrlf=false` 防止自動轉換

## 禁止事項
- 禁止直接修改 Horilla 原生 migration 檔案
- 禁止在 views.py 直接 import request.user 做權限判斷（使用 Django Permission）
- 禁止 hardcode 中文字串到 Python 程式碼（使用 gettext_lazy）

## Changelog
<!-- 每完成一個 WP，在此記錄 -->
- 2026-05-12 WP-00 環境建置：clone fork、設 upstream、docker-compose.override.yaml（TZ=Asia/Taipei、LANGUAGE_CODE=zh-hant、db port 改 5433 避開本機 PG）、修正 entrypoint.sh CRLF。
- 2026-05-12 WP-01 繁體中文介面：Dockerfile 安裝 gettext；settings.py 改 `LANGUAGE_CODE = env("LANGUAGE_CODE", default="zh-hant")`；補完 horilla/locale/zh_Hant/django.po 84+4=88 條未譯（剩 0 條）；entrypoint 加 `compilemessages -l zh_Hant`（只編 zh_Hant，避開既有 fr/de .po 格式 bug）。驗證：login 頁完全中文、Content-Language=zh-hant、gettext('Employee')='員工'。
- 2026-05-12 修首頁 404：root cause = `helpdesk` / `offboarding` / `project` 三個 app 透過 `horilla/horilla_apps.py` 自動加入 INSTALLED_APPS，但其 URL 註冊只在 `apps.py:ready()` 才 append 到 `urlpatterns`，URL resolver 已快取 `reverse_dict` 導致 NoReverseMatch（`ticket-create`、`faq-category-view`、`project-dashboard-view`、`offboarding-dashboard`）。template render 拋例外被 `wrapped_view` 接住改 render `went_wrong.html`（外觀如 404）。修法：直接在 `horilla/urls.py` include 三個 app 的 urls，避開 ready 時序問題。驗證：登入後 `/` 回 200、size 從 3263→149934、122 條中文標籤可見。
- 2026-05-12 移除不需要的模組：依需求關閉 recruitment / helpdesk / project / biometric / geofencing / facedetection / horilla_ldap / horilla_backup / horilla_documents / dynamic_fields。實作分兩層：(1) UI 隱藏：從 `horilla/horilla_apps.py` 的 SIDEBARS 移除 recruitment, helpdesk, project；(2) App 卸載：在 horilla_apps.py 註解 INSTALLED_APPS.append("biometric"/"helpdesk"/"horilla_backup"/"project")；在 horilla_api/__init__.py 註解 geofencing/facedetection 註冊；在 horilla_api/urls.py 註解 helpdesk API 路由；從 horilla/urls.py 移除 helpdesk/project include（offboarding 仍 include）。recruitment 因 onboarding 強依賴只 UI 隱藏不卸載 model；horilla_documents、dynamic_fields 因 employee/base/asset 強依賴保留 model。
- 2026-05-12 dev mode 全 mount：docker-compose.override.yaml 改成 `volumes: - .:/app`（除 staticfiles、node_modules 用 anonymous volume 蓋掉），讓 horilla_api/ 等 baked-in 目錄的修改也能即時生效，無需 rebuild。
- 2026-05-25 寫 base/management/commands/seed_think4u_data.py：建 1 公司 / 4 部門 / 8 職位 / 2 工作型態 / 2 員工類型 / 1 班別 / 5 請假類型 / 8 國定假日 / 週末公司假 / 4 Auth Group / 11 帳號（admin + 10 員工，含 2 主管 + 2 HR）。Horilla 多個 base 模型的 `save()` 對 Model.clean() 傳 kwargs 不相容，命令啟動時把這些 model 的 save 還原為 `dj_models.Model.save` 繞過。
- 2026-05-25 二階段精簡：完全卸載 `recruitment / pms / onboarding / offboarding`（從 settings.INSTALLED_APPS 及 sidebar 移除）。`asset` 因 `payroll.0001_initial` migration 強依賴必須留在 INSTALLED_APPS，但已從 SIDEBARS 移除且改 `templates/dashboard_tile_container.html`、`templates/floating_button.html`、`templates/dashboard.html` 拿掉 asset 對應的 widget / FAB / modal。Settings 內各區塊本就 `{% if "app"|app_installed %}` 包好，自動隱藏。
- 2026-05-25 host port 改 8001：原 8000 被 WSL `wslrelay` 殘留佔用，於 docker-compose.override.yaml 加 `ports: !override - "8001:8000"`。本機改用 http://localhost:8001 連線。
- 2026-05-26 WP-X.1 模組精簡第二輪：employee sidebar 拿掉 Shift Requests / Work Type Requests / Rotating Shift Assign / Rotating Work Type Assign；Payroll 整個從 SIDEBARS 移除（model 仍存以滿足 migration FK）；配置 accordion 拿掉 Mail Templates 與 Restrict Leaves，只留多重核准 / 郵件自動化 / 假期 / 公司休假。
- 2026-05-26 WP-X.4 組織圖移至頂層：新建 `base/sidebar.py` 將 organisation-chart 變獨立模組；`SIDEBARS` 加入 "base"。
- 2026-05-26 WP-X.5 員工表單擴充：`EmployeeWorkInformationForm` 與 `EmployeeWorkInformationUpdateForm` 加 `groups`（ModelMultipleChoiceField），exclude `shift_id` / `work_type_id`；`sync_groups(employee)` 在儲存後同步 user.groups；employee/profile/work_info.html 隱藏 shift/work_type row，新增 Role/Groups row。
- 2026-05-26 WP-X.7 員工請假天數總覽：新 view `employee_leave_overview` + URL `/leave/employee-leave-overview/` + template；顯示員工 × 假別 × (配給/遞延/今年已休/剩餘/可用區間)；種子 seed 自動為每員工每假別建立 AvailableLeave（55 筆）。
- 2026-05-26 WP-X.3 儀表板分層：全角色看 4 個 widget（我的出勤 / 提醒 / 請假申請 / 加班申請佔位）；superuser 包 `{% if request.user.is_superuser %}` 再顯示原本的 tile container（圖表 + 報表）。
- 2026-05-26 WP-X.6 角色頁面可見性：新 model `RolePageVisibility(group, sidebar_key, visible)`；migration 0003；`horilla/config.py:_filter_sidebar_by_role` 過濾邏輯（superuser 看全部，其餘 group 未設定預設可見，有 record 則依 visible 標記）；新 view `base/think4u_views.role_visibility_view` + URL `/think4u/role-visibility/` + 4×4 矩陣 template；sidebar.html「配置」加入此入口（superuser-only）。
- 2026-05-26 WP-X.2+WP-02 雙入口 + 打卡頁：requirements.txt 加 `pyotp`；AttendanceActivity 加 `attendance_type` / `field_reason` / `client_ip` / `verification_code_used` 四欄位（migration 0003）；新 `base/think4u_clock.py`（TOTP 24h、IP capture、clock_page、clock_submit）；新 `landing.html`（雙入口）+ `clock.html`（打卡頁）；settings.py LOGIN_URL 改 `/landing/`、加 `DAILY_VERIFICATION_CODE_SECRET`；`horilla/decorators.login_required` 修：anonymous 訪問 `/` 直接導向 `/landing/`；`base/views.login_user` 修：GET 無 `next` 參數時 redirect landing。
- 2026-05-26 Rebrand：Honsi → Think4U 全域替換（29 個檔案、4 個檔案/目錄改名、URL 路徑、TOTP secret、DB 公司名）。grep 殘留 = 0。
- 2026-05-26 WP-05 台灣特休（歷年制 + 遞延）：新 `think4u` Django app；`AnnualLeaveRecord` model（migration 0001）；`services/annual_leave_calculator.py` 含 `get_service_months/calculate_prorated_days/days_by_full_years/calculate_jan1_allocation/calculate_six_month_grant`；3 個 management commands（`sync_annual_leave` / `grant_six_month_leave` / `year_end_leave_settlement`）；15 個 unit tests 全過（包含規格表 7 個 case）。
- 2026-05-26 WP-04 加班指派：`OvertimeAssignment` model（migration 0002）狀態機 7 個 status；3 對 views（manager / employee / HR）+ 7 個 URL；3 個 templates；email 通知 `_safe_send`（無 SMTP 也不崩）；think4u/sidebar.py 新加班入口；dashboard 加班 widget 解除佔位；e2e flow 驗證通過：admin→pending_employee→pending_hr→hr_approved。
- 2026-05-26 WP-06 病假附件條件式必填：`_SickLeaveAttachmentMixin` mixin 套用至 4 個 leave forms；病假必上傳 + 副檔名限制 (.pdf/.jpg/.jpeg/.png) + 10MB 上限；5 個 unit tests 全過。
- 2026-05-26 WP-03 出勤 / 計薪匯出：`think4u/attendance_exports.py` 用 openpyxl 產生 11 欄 .xlsx；HR/主管/員工三層 queryset；URL `/think4u/attendance/export/` 表單頁 + `/think4u/attendance/export/excel/` 下載；出勤 sidebar 加 Excel 匯出入口。
- 2026-05-26 WP-07 雙層審核專區：`think4u/approval_views.py` 三個 dashboard（manager / hr / employee）綜合請假 + 加班；think4u sidebar 加 4 個入口；隨角色顯示。
- 2026-05-26 WP-08 角色 / 權限 fixture：`configure_roles` management command 為 4 個 Auth Group 配 Django permissions + 預設 RolePageVisibility；`--dump` 輸出 `fixtures/initial_groups.json`。
- 2026-05-26 WP-09 正式部署：`docker-compose.prod.yaml`（server + db + nginx + 內建每日 backup）；`nginx/nginx.conf` HTTPS reverse proxy + 安全標頭；`.env.prod.example`；`DEPLOYMENT.md` 含 cron 設定、備份/還原、升級流程。
- 2026-05-28 前台「出勤」tab + 異常日快捷申請：
  - 取代原本的「我的紀錄」tab（紀錄移到出勤頁底部摺疊區）
  - 5 個 nav：打卡 / 請假 / 加班 / **出勤** / 設定
  - 出勤頁：本年度 1-12 月可切換（pill 形式），每月份顯示
    - 摘要：正常 / 遲到 / 早退 / 缺勤 / 總工時
    - 每日明細表：日期 / 上班 / 下班 / 工時 / 狀態（含遲早分鐘）/ 動作
    - 規則 banner：09:30~10:00 / 18:30~19:00 彈性、每日 ≥ 8h
  - **異常日快捷申請**：缺勤/未打卡完整/遲到/早退/工時不足 列出現 3 顆按鈕：
    - 📝 補打卡（only 缺勤/未打卡完整顯示）→ 跳 `?tab=clock&prefill_date=…`
    - 📅 請假 → 跳 `?tab=leave&prefill_date=…`
    - ⏱️ 加班 → 跳 `?tab=overtime&prefill_date=…`
    - 三個 tab 的對應日期欄位都會自動帶入點選的那天
  - 底部「最近申請彙整」摺疊區：請假 / 加班 / 補打卡 三類
- 2026-05-28 假別重構：4 種預設 + 申請給假流程：
  - **預設給假**（每位員工自動有）：特休 7 / 事假 14 / 病假 30 / 生理假 12（僅 gender=female）
  - 其他 9 種假別（婚假、產假、喪假 3 類、公傷病假、公假、產檢假、陪產假）→ 必須走「申請給假」流程
  - **新 model `LeaveGrantRequest`**：employee / leave_type / requested_days / reason / proof_document / status / granted_days / hr_note / decided_by
  - **management command `seed_default_leaves --purge-others`**：重置每員工的 default 假別配額，刪掉非預設的舊 AvailableLeave
  - **portal 變更**：
    - 「請假」下拉只列「員工有 AvailableLeave 配額 且 > 0」的假別
    - 「申請給假」摺疊區：選非預設假別 + 申請天數 + 證明文件 + 事由
    - 選到「生理假」會跳提示 banner（每月 1 天 / 半薪 / 不需證明 / 3 天內不計病假 30 天）
    - 顯示我送出的 grant requests 最近 5 筆
  - **生理假規則執行**：
    - 同月已申請過 → 擋
    - 一次請 > 1 天 → 擋
    - 全部 unit-tested ✓
  - **HR 後台 給假審核** `/think4u/leave-grant/pending/`：
    - 列出待審 grant requests（可切換看歷史）
    - 顯示員工 / 假別 / 申請天數 / 證明附件 / 事由
    - 核准：自動建立或加值 AvailableLeave（依 HR 核發天數 — 可調整）
    - 駁回：寫 hr_note
    - sidebar 加「HR — 給假審核」（accessibility = hr_accessibility）
- 2026-05-28 前台 portal 加「設定」tab（個人 + 銀行資訊修改）：
  - 第 5 個 bottom nav tab `⚙️ 設定`
  - 個人資料區：頭像上傳 + 姓名 / Email / 電話 / 地址 / 生日 / 性別 / 緊急聯絡（姓名/電話/關係）
  - 銀行資訊區：銀行名稱 + 帳號（其他欄位 Think4U 已精簡掉，不顯示）
  - URLs：`/portal/personal/submit/` + `/portal/bank/submit/`
- 2026-05-28 前台 / 後台分離：
  - **新模型** `OvertimeApplication`（員工主動加班申請，走 ApprovalWorkflow，與主管指派的 OvertimeAssignment 並存）
  - **新模型** `AdminAccessGroup(group)`：哪些角色能進後台；helper `user_can_access_admin(user)` superuser 永遠 True、其他角色看是否在 AdminAccessGroup
  - **前台 portal** `/portal/`：App 風格 + 下方 nav bar（打卡 / 請假 / 加班 / 我的），全部功能整合在單頁：
    - 打卡 tab：即時時鐘、上下班打卡、公司/外勤切換、驗證碼；底部摺疊式補打卡申請
    - 請假 tab：假別下拉、起訖日、附件（沿用 Horilla LeaveRequest）；顯示剩餘假
    - 加班 tab：日期/起訖時間/事由；分別顯示「我送出的」+「主管指派的」加班
    - 我的 tab：所有申請彙整
    - 右上：登出 + 「進後台」連結（僅 admin 角色顯示）
  - **後台守門員 middleware** `think4u/admin_gate_middleware.py`：已登入但無 admin 權限訪問非 portal/clock/login/static 路徑 → 自動導 `/portal/`
  - **登入流程改寫**：
    - 預設 `LOGIN_REDIRECT_URL = /portal/`
    - 已登入訪問 `/login/` → 依角色導 `/`（admin）或 `/portal/`（非 admin）
    - landing page 只有 admin 才看得到「後台 / 前台」選擇；非 admin 直接導 portal
  - **seed**：人資 HR + 系統管理員 預設加入 AdminAccessGroup（migration `think4u/0005`）
  - URL 路徑：`/portal/` + `/portal/clock/submit/` + `/portal/correction/submit/` + `/portal/leave/submit/` + `/portal/overtime/submit/` + `/portal/cancel/<kind>/<pk>/`
- 2026-05-28 出勤判定 + 月度統計 + 每日提醒 + 補打卡審核：
  - **規則**（`think4u/attendance_rules.py`）：上班 09:30~10:00 彈性、下班 18:30~19:00 彈性、午休 12:30~13:30、每日須 8h；> 10:00 遲到、< 18:30 早退；工時 = (out - in) - 午休重疊分鐘。
  - **月度統計頁** `/think4u/attendance/monthly/`：員工 × 日期矩陣，每格 ✓/↑/↓/✗ + hover 顯示遲到分數；總工時 / 正常 / 遲到 / 早退 / 缺勤 月度摘要；HR 看全公司、主管看部屬（含子部門）、員工看自己。
  - **每日 10:30 打卡提醒** `python manage.py notify_unpunched`：找出當日未打卡的 active employee，寄 Email + 站內通知；週末跳過；`--dry-run` 預覽；建議 cron：`30 10 * * 1-5 docker compose exec server python manage.py notify_unpunched`。
  - **補打卡申請** `PunchCorrectionRequest`（migration `think4u/0004`）：員工提交 (target_date, check_in, check_out, reason)，套用該員工職位的 ApprovalWorkflow（新增 request_type='punch_correction'），多關卡審核；核准最後一關自動寫入 `AttendanceActivity`，狀態 → 'applied'；URLs `/think4u/punch-correction/my/`（員工）+ `/punch-correction/pending/`（待我審核）+ `/punch-correction/<id>/decide/`（送出決定）。
  - sidebar：think4u 加「補打卡申請 / 補打卡審核」、attendance 加「月度出勤統計」。
- 2026-05-27 全站「頁面切換」前端效能大改善（第二輪）：
  - **Root cause**: 即使 server 回應 < 100ms，每換一頁瀏覽器仍要重抓 / 重 parse ~29 個 external JS（包括幾個超大但全站幾乎沒用到的）：
    - `pivottable_plot.min.js` 3.6 MB / `pivottable_excel.min.js` 947 KB / `pivottable.min.js` 29 KB / `pivottable_ploty.min.js` 3 KB — grep 全站 0 處 `pivotUI` 或 `.pivot()` 呼叫，全部無用 → **整批刪除**
    - `summernote-lite.min.js` 164 KB + `.css` 30 KB → 只有 send_mail.html / mail template form 用到，移過去
    - `orgChart.js` 83 KB + `.css` 24 KB → 只有組織圖 org_chart.html 用，移過去
    - `driver.js` 18 KB + `driver.min.css` 6 KB → 只 dashboard / settings 的新手導覽用，移過去
    - `https://cdn.jsdelivr.net/npm/chart.js` CDN → 各 dashboard template 早已自己 include，base 不需要
    - `https://cdnjs.cloudflare.com/.../moment-with-locales.min.js` CDN → 拿掉，本地 `build/js/moment.js` 已足夠
  - **減量**: 每頁少載 ~4.9 MB JS + ~60 KB CSS + 8-9 個 HTTP request
  - **量測後（warm）**: 一般頁面 < 100ms server time、47-72 query、66-105 KB HTML
  - 修改檔案：`templates/index.html`（移除 6 個 link/script + 加註解）、`templates/dashboard.html` + `templates/settings.html`（補上 driver.js）、`employee/templates/organisation_chart/org_chart.html`（補上 orgChart）、`employee/templates/employee/send_mail.html` + `base/templates/mail/htmx/form.html`（補上 summernote）
- 2026-05-27 全站頁面切換速度大改善：
  - **Root cause**: `base/horilla_company_manager.py:HorillaCompanyManager.get_queryset()` 每次都跑 `queryset.count() != queryset.distinct().count()` 偵測重複（兩條 COUNT），HorillaCompanyManager 又被廣泛使用，造成單一 request 就有 60+ 條多餘 SQL。
  - **Fix**: distinct 偵測結果 cache 在 process-wide dict（`_T4U_DISTINCT_CACHE`，key = (model_label, selected_company)），因為 `company_filter` 是 class attribute、跨 request 穩定。
  - **N+1 修正**: `think4u/org_views.py:dept_manage / position_manage` 原本對每個部門 / 職位再跑 `EmployeeWorkInformation.objects.filter(...).count()`，改用 `annotate(Count(..., distinct=True))` 一次撈完。
  - **View 瘦身**: `employee/views.py:employee_view_new` 移除沒用到的 `work_form / bank_form / EmployeeFilter`，cold 9.63s → 0.79s。
  - **量測結果**（warm，db 內 4 員工）:
    - 首頁 114 query → 58 query / 46ms
    - 新增員工 95 → 47 query / 42ms
    - 部門管理 124 → 50 query / 41ms
    - 職位管理 146 → 52 query / 47ms
  - 整體 query 數降 40–65%，warm 回應時間都壓到 < 100ms。
- 2026-05-27 Plan B 職位預設角色 + 審核關卡架構：
  - **Phase 1**: `JobPosition.default_role` FK→Group（migration `base.0009`）；職位管理頁加角色下拉（建立 / 改名同步）；員工編輯頁 JS 監聽 job_position 變更呼叫 `/think4u/api/position-default-role/` API 自動帶角色；`EmployeeWorkInformationForm` / `UpdateForm.sync_groups()` fallback 到 `job_position.default_role`。
  - **Phase 2**: 新 model `ApprovalWorkflow(job_position, request_type)` + `ApprovalStep(workflow, order, approver_type, approver_role|approver_employee)`（migration `think4u.0003`）；approver_type 五選：直屬主管 / 部門主管 / 指定角色 / 指定員工 / HR。
  - **Phase 3**: `/think4u/approval-workflow/` 管理頁（superuser-only）；每個 (職位 × 請假|加班) 一張卡片，動態加 / 刪 / 改關卡、整批儲存；配置 sidebar 加「審核關卡管理」入口。
  - **Phase 4（未做）**: 整合到 WP-04 加班 + 請假審核流程（取代寫死的 direct manager → HR），後續另做。
