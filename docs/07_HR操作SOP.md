# 07 HR 操作 SOP（Think4U HRMS）

> 給接手「系統管理／HR 業務」的人。不需要會寫程式，但幾個步驟需要在伺服器跑指令
> （可請 IT 代跑；指令都可直接複製）。正式機指令前置見 docs/04 §1 的 `dc` alias。

## 1. 新人入職（每位新人都要做，缺一不可）
1. **建員工**：後台 → 員工 → 新增。填 Email（**Email 即登入帳號**）、性別（影響生理假）。
2. **工作資訊**：部門、職位（會自動帶預設角色）、員工類型（全職/兼職）、**到職日**（影響特休與計薪！）。
3. **薪資/計薪方式** 區塊：月薪制填本薪+津貼+加給；時薪制填時薪；勞/健保投保級距（下拉，0=沿用全薪）。健保眷屬在同頁「健保眷屬」區維護。
4. **跑兩個指令**（伺服器）：
   ```bash
   dc exec -T server python manage.py precompute_annual_leave --emp <員工id>
   dc exec -T server python manage.py seed_default_leaves --emp <員工id>
   ```
   （特休依到職日自動排 20 年；預設假別：事假 14/病假 30/生理假 12 女）
5. 告知員工帳號（Email）與初始密碼，請其登入後修改；或直接用 Google 公司帳號登入（SSO）。

> 員工 id 查法：後台員工頁網址列 `employee-view/<id>/`，或問 IT。

## 2. 離職
1. 員工檔案 → 封存（is_active off）——登入即被擋。
2. ⚠️ 離職當月薪資按日比例**系統尚未支援**，該月薪資需人工調整（docs/06 C5）。

## 3. 每月薪務流程
1. 後台 → 出勤 → **月度出勤統計**：檢查全月出勤（缺勤/異常先處理補打卡或請假）。
2. 同頁薪資試算表：
   - 填「其他（每月變動）」：加班費、禮金、全勤、代墊…（改完自動儲存）
   - 確認請假扣薪明細與眷屬數
   - 時薪制員工確認工時與時薪
3. **匯出 Excel** 存檔（含計算式，作為發薪依據）。
4. 規則說明：金額一律無條件進位到元；到職當月按在職天數比例；詳見 docs/03。

## 4. 出勤 Excel 匯入（歷史/批次補資料）
1. 檔名必須含 `員工：EnglishName`（例：`(宏思)出勤_請假_加班_員工：Bill(黃麒能).xlsx`），EnglishName 需與系統員工英文名一致。
2. 檔案放到專案 `import_data/` 資料夾。
3. 逐年匯入（伺服器或開發機）：
   ```bash
   dc exec -T server python manage.py import_attendance --folder /app/import_data --year 2026 --dry-run   # 先預覽
   dc exec -T server python manage.py import_attendance --folder /app/import_data --year 2026            # 正式
   ```
4. ⚠️ **匯入會先清掉該年度「全公司」的出勤/請假/加班再重建**——凡是沒回寫進 Excel 的系統內手動修改都會消失。要保留手動資料就先把它補進 Excel。

## 5. 帳號與密碼
- **重設某人密碼**（伺服器）：
  ```bash
  dc exec -T server python manage.py shell -c "
  from django.contrib.auth.models import User
  u=User.objects.get(username='帳號email'); u.set_password('新密碼'); u.save(); print('ok')"
  ```
- Google SSO：員工用公司 Google 帳號登入即可（Email 必須已存在系統；不會自動開帳號）。
- 忘記密碼自助重設：需先設定 SMTP（docs/06 A3）。

## 6. 假別與審核
- **給假審核**（婚/產/喪/公假等）：審核專區 → HR — 給假審核；核發天數可調整。
- **請假審核**：主管在「審核專區」核第一層，HR 核第二層。
- **加班**：主管於「主管 — 指派加班」建立 → 員工前台確認 → HR 核准。
- **補打卡**：員工前台申請 → 「補打卡審核」多關卡核准後自動寫入出勤。
- 假別總量設定：後台 → 假期 → 休假類型（法定假別勿隨意改天數，見 docs/03）。

## 7. 系統設定常用位置
| 要改什麼 | 去哪裡 |
|---|---|
| 角色能看哪些頁 | 配置 → 角色頁面可見性 |
| 誰能進後台 / 強制後台 | 配置 →（AdminAccessGroup；目前需 IT 從 admin 後台調）|
| 審核關卡（設定用，尚未生效）| 配置 → 審核關卡管理 |
| 郵件自動化 | 配置 → 郵件自動化（先選「資料模型」才會出現收件人選項）|
| 稽核紀錄（誰改了什麼）| 配置 → 稽核紀錄（superuser）|
| 部門/職位/組織圖 | 組織 → 部門管理/職位管理/組織結構圖 |
| GPS 打卡座標 | 程式常數，需 IT 改（`think4u/portal_views.py`）|

## 8. 求救順序
1. 先查 docs/04 §6 故障排除表（常見問題都有解法）。
2. 看伺服器 log：`dc logs --tail=50 server`。
3. 帶著「做了什麼步驟 + 完整錯誤訊息/截圖」找開發接手人。
