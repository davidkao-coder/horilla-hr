"""
Think4U: 從 Excel 匯入 出勤 + 請假 紀錄。

支援單檔 或 整個資料夾（每位員工一檔，檔名格式為
  (公司)出勤_請假_加班_員工：<EnglishName>(中文名).xlsx）

每檔包含 sheet '01_出勤明細表'，欄位（固定 index）：
  col 2 = 出勤日期
  col 4 = 上班時間
  col 5 = 下班時間
  col 7 = 異常
  col 9 = 核准假別（請假時填）

用法：
  # 1. 預設清掉 2026 年 attendance + leave 再匯整個資料夾
  python manage.py import_attendance --folder /app/import_data

  # 2. 單檔
  python manage.py import_attendance --file /app/import_data/xxx.xlsx

  # 3. 不清舊資料（增量；同日重複會跳過）
  python manage.py import_attendance --folder ... --no-purge

  # 4. 預覽不寫入
  python manage.py import_attendance --folder ... --dry-run

  # 5. 限定年份（預設今年）
  python manage.py import_attendance --folder ... --year 2026
"""
import os
import re
from datetime import date, datetime, time

from django.core.management.base import BaseCommand
from django.db import models as dj_models
from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceActivity, WorkRecords
from employee.models import Employee
from leave.models import LeaveRequest, LeaveType
from think4u.models import OvertimeApplication

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


# 出勤明細表的欄位 index（0-based）
COL_DATE = 2
COL_IN = 4
COL_OUT = 5
COL_ABNORMAL = 7
COL_LEAVE_TYPE_APPROVED = 9      # 核准假別
COL_LEAVE_HOURS_APPROVED = 10    # 核准請假時數
COL_OT_HOURS = 11                # 核准加班時數
COL_LEAVE_APPLICATION = 13       # 請假申請（員工原始申請）
COL_LEAVE_PERIOD = 14            # 起/迄時間 例 09:30~18:30
COL_LEAVE_HOURS = 15             # 請假時數
COL_LEAVE_REASON = 16            # 請假原因
COL_OT_PERIOD = 24               # 加班 起/迄
COL_OT_REASON = 23               # 加班申請原因

# 假別名稱對應 (excel) → LeaveType.name (DB)
LEAVE_TYPE_MAP = {
    "特休": "特休假",
    "事假": "事假",
    "病假": "病假",
    "公假": "公假",
    "婚假": "婚假",
    "生理假": "生理假",
    "產假": "產假",
    "陪產假": "陪產假",
    "產檢假": "產檢假",
    "補休": "補休",
}


def _coerce_time(val):
    """把 datetime.time / datetime.datetime / 字串 / None 統一成 datetime.time"""
    if val is None or val == "":
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, datetime):
        return val.time()
    s = str(val).strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*([AaPp][Mm])?$", s)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        se = int(m.group(3)) if m.group(3) else 0
        ampm = m.group(4)
        if ampm:
            if ampm.lower() == "pm" and h < 12:
                h += 12
            elif ampm.lower() == "am" and h == 12:
                h = 0
        try:
            return time(h, mi, se)
        except ValueError:
            return None
    return None


def _parse_period(s: str):
    """從 '19:00~20:30' 之類的字串解出 (start_time, end_time)"""
    if not s:
        return None, None
    s = str(s).strip()
    # 統一分隔符
    for sep in ("~", "～", "-", "—", "至"):
        if sep in s:
            parts = s.split(sep, 1)
            if len(parts) == 2:
                return _coerce_time(parts[0].strip()), _coerce_time(parts[1].strip())
    return None, None


def _extract_english_name(filename: str) -> "str|None":
    """從檔名抓 English name，例：(宏思)出勤_請假_加班_員工：Bill(黃麒能).xlsx → Bill"""
    # 抓「員工：」後到 ( 之前
    m = re.search(r"員工：([A-Za-z]+)", filename)
    if m:
        return m.group(1).strip()
    return None


def _build_employee_index():
    idx = {}
    for e in Employee.objects.filter(is_active=True):
        n = (e.employee_first_name or "").strip().lower()
        if n:
            idx[n] = e
    return idx


def _build_leave_type_index():
    idx = {}
    for lt in LeaveType.objects.filter(is_active=True):
        idx[lt.name.strip()] = lt
    return idx


class Command(BaseCommand):
    help = "從 Excel 匯入 2026 年的 出勤 + 請假 紀錄"

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group(required=True)
        g.add_argument("--file", type=str, help="單個 .xlsx")
        g.add_argument("--folder", type=str, help="資料夾（內含多個 .xlsx）")
        parser.add_argument("--year", type=int, default=None, help="限定 / 清除哪一年（預設今年）")
        parser.add_argument("--no-purge", action="store_true", help="不要先清除該年資料")
        parser.add_argument("--dry-run", action="store_true", help="預覽不寫入")

    def handle(self, *args, **opts):
        if load_workbook is None:
            self.stderr.write("缺套件：openpyxl")
            return

        target_year = opts["year"] or timezone.localdate().year
        do_purge = not opts["no_purge"]
        dry_run = opts["dry_run"]

        files = []
        if opts["file"]:
            files = [opts["file"]]
        else:
            folder = opts["folder"]
            files = sorted(
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.endswith(".xlsx") and not f.startswith("~")
            )
        self.stdout.write(f"檔案數：{len(files)}，目標年份：{target_year}，"
                         f"purge={do_purge}, dry_run={dry_run}")

        emp_idx = _build_employee_index()
        lt_idx = _build_leave_type_index()
        self.stdout.write(f"員工索引：{len(emp_idx)} / 假別索引：{len(lt_idx)}")

        # 累計待匯資料
        all_attendance = []  # (emp, date, in_t, out_t, abnormal)
        all_leave = []       # (emp, date, leave_type_excel, abnormal)
        all_overtime = []    # (emp, date, hours, period, reason)
        skipped_employees = []
        warnings = []

        for path in files:
            fname = os.path.basename(path)
            en_name = _extract_english_name(fname)
            if not en_name:
                warnings.append(f"  {fname}: 抓不出 English name")
                continue
            emp = emp_idx.get(en_name.lower())
            if not emp:
                skipped_employees.append(en_name)
                warnings.append(f"  {fname}: DB 無 {en_name}")
                continue

            wb = load_workbook(path, data_only=True)
            if "01_出勤明細表" not in wb.sheetnames:
                warnings.append(f"  {fname}: 找不到 sheet")
                continue
            ws = wb["01_出勤明細表"]

            n_att = n_lv = n_ot = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                d = row[COL_DATE]
                if not d:
                    continue
                if isinstance(d, datetime):
                    d = d.date()
                if d.year != target_year:
                    continue
                in_t = _coerce_time(row[COL_IN])
                out_t = _coerce_time(row[COL_OUT])
                abnormal = row[COL_ABNORMAL]

                # 打卡
                if in_t or out_t:
                    all_attendance.append((emp, d, in_t, out_t, abnormal))
                    n_att += 1

                # 請假：優先讀 col 13（請假申請），fallback 到 col 9（核准假別）
                lv_app = row[COL_LEAVE_APPLICATION]
                lv_approved = row[COL_LEAVE_TYPE_APPROVED]
                lv_name = None
                if lv_app and str(lv_app).strip() not in ("", "請選擇", "None"):
                    lv_name = str(lv_app).strip()
                elif lv_approved:
                    lv_name = str(lv_approved).strip()

                if lv_name:
                    lv_hours = row[COL_LEAVE_HOURS] or row[COL_LEAVE_HOURS_APPROVED] or 0
                    try:
                        lv_hours = float(lv_hours)
                    except (TypeError, ValueError):
                        lv_hours = 0
                    if lv_hours <= 0:
                        # 沒填時數但有假別 → 預設 8 小時（一整天）
                        lv_hours = 8.0
                    lv_period = row[COL_LEAVE_PERIOD]
                    lv_reason = row[COL_LEAVE_REASON]
                    all_leave.append((emp, d, lv_name, lv_hours,
                                     str(lv_period or "").strip(),
                                     str(lv_reason or "").strip(),
                                     abnormal))
                    n_lv += 1

                # 加班
                ot_hours = row[COL_OT_HOURS]
                if ot_hours and float(ot_hours) > 0:
                    all_overtime.append((emp, d, float(ot_hours),
                                         str(row[COL_OT_PERIOD] or "").strip(),
                                         str(row[COL_OT_REASON] or "").strip()))
                    n_ot += 1

            self.stdout.write(f"  ✓ {fname}: {n_att} 打卡 / {n_lv} 請假 / {n_ot} 加班")

        self.stdout.write(f"\n累計：打卡 {len(all_attendance)} / 請假 {len(all_leave)} / 加班 {len(all_overtime)} / 警告 {len(warnings)}")
        for w in warnings[:10]:
            self.stdout.write(self.style.WARNING(w))

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — 不寫入"))
            return

        AttendanceActivity.save = dj_models.Model.save
        LeaveRequest.save = dj_models.Model.save

        with transaction.atomic():
            if do_purge:
                att_qs = AttendanceActivity.objects.filter(attendance_date__year=target_year)
                n_att = att_qs.count()
                att_qs.delete()
                lr_qs = LeaveRequest.objects.filter(start_date__year=target_year)
                n_lr = lr_qs.count()
                lr_qs.delete()
                ot_qs = OvertimeApplication.objects.filter(overtime_date__year=target_year)
                n_ot = ot_qs.count()
                ot_qs.delete()
                self.stdout.write(self.style.WARNING(
                    f"已清除：{n_att} 筆 AttendanceActivity / {n_lr} 筆 LeaveRequest / {n_ot} 筆 OvertimeApplication（{target_year} 年）"
                ))

            # 寫入 AttendanceActivity（datetime 加上 tz）
            # clock_in 是 NOT NULL，若只有 out 沒有 in，視為異常列跳過
            n_created_att = 0
            n_skipped_att = 0
            for emp, d, in_t, out_t, abnormal in all_attendance:
                if not in_t:
                    n_skipped_att += 1
                    continue
                in_dt = timezone.make_aware(datetime.combine(d, in_t))
                out_dt = timezone.make_aware(datetime.combine(d, out_t)) if out_t else None
                AttendanceActivity.objects.create(
                    employee_id=emp,
                    attendance_date=d,
                    clock_in_date=d,
                    clock_in=in_t,
                    in_datetime=in_dt,
                    clock_out_date=d if out_t else None,
                    clock_out=out_t,
                    out_datetime=out_dt,
                    attendance_type="office",
                    field_reason=str(abnormal)[:200] if abnormal else None,
                )
                n_created_att += 1
            if n_skipped_att:
                self.stdout.write(self.style.WARNING(f"  跳過 {n_skipped_att} 筆 只有下班沒上班的紀錄"))

            # 寫入 LeaveRequest（精度到 0.5 小時，requested_days = hours/8）
            n_created_lv = 0
            n_skipped_lv = 0
            for emp, d, lv_name, lv_hours, lv_period, lv_reason, abnormal in all_leave:
                db_lt_name = LEAVE_TYPE_MAP.get(lv_name, lv_name)
                if db_lt_name is None:
                    n_skipped_lv += 1
                    continue
                lt = lt_idx.get(db_lt_name)
                if not lt:
                    n_skipped_lv += 1
                    continue

                days = round((lv_hours / 8.0) * 16) / 16.0  # 對齊到 0.5 小時 = 0.0625 day
                # breakdown：≤4h half day，>4h full day
                if lv_hours >= 8:
                    breakdown = "full_day"
                else:
                    breakdown = "first_half" if lv_hours <= 4 else "full_day"

                desc_parts = [f"匯入 {lv_name} {lv_hours} 小時"]
                if lv_period:
                    desc_parts.append(f"時段 {lv_period}")
                if lv_reason:
                    desc_parts.append(f"原因：{lv_reason}")
                if abnormal:
                    desc_parts.append(f"異常：{abnormal}")

                LeaveRequest.objects.create(
                    employee_id=emp,
                    leave_type_id=lt,
                    start_date=d,
                    end_date=d,
                    requested_days=days,
                    start_date_breakdown=breakdown,
                    end_date_breakdown=breakdown,
                    description=" | ".join(desc_parts),
                    status="approved",
                )
                n_created_lv += 1

            # 寫入 OvertimeApplication（員工自主申請，狀態 approved）
            from django.contrib.auth.models import User
            sys_user = User.objects.filter(is_superuser=True).first()
            n_created_ot = 0
            for emp, d, hours, period, reason in all_overtime:
                # period 例 "19:00~20:30"；parse 起迄時間
                start_t, end_t = _parse_period(period) if period else (None, None)
                if not start_t or not end_t:
                    # fallback：用 18:30 + hours
                    start_t = time(18, 30)
                    h, m = divmod(int(hours * 60), 60)
                    end_h = (start_t.hour + h) % 24
                    end_m = (start_t.minute + m) % 60
                    end_t = time(end_h, end_m)
                OvertimeApplication.objects.create(
                    employee=emp,
                    overtime_date=d,
                    start_time=start_t,
                    end_time=end_t,
                    reason=reason or f"匯入：{hours} 小時",
                    status="approved",
                )
                n_created_ot += 1

            self.stdout.write(self.style.SUCCESS(
                f"\n✓ 完成：AttendanceActivity {n_created_att} 筆，"
                f"LeaveRequest {n_created_lv} 筆（跳過 {n_skipped_lv} 筆），"
                f"OvertimeApplication {n_created_ot} 筆"
            ))

            # 生成 WorkRecords（給「工作記錄」頁顯示用）
            WorkRecords.objects.filter(date__year=target_year).delete()
            wr_created = 0
            # collect (emp, date) from attendance + leave
            att_set = {(a[0].id, a[1]): a for a in all_attendance if a[2]}  # 有 in
            lv_set = {}
            for emp, d, lv_name, lv_hours, _, _, _ in all_leave:
                key = (emp.id, d)
                lv_set.setdefault(key, []).append((lv_name, lv_hours))
            all_keys = set(att_set.keys()) | set(lv_set.keys())
            for emp_id, d in all_keys:
                has_att = (emp_id, d) in att_set
                lvs = lv_set.get((emp_id, d), [])
                # 有打卡 → FDP（出勤），同時有請假時 is_leave_record=True 會在 template
                #   顯示橘色「請假+有打卡」；不再用 CONF（衝突）
                if has_att:
                    wt = "FDP"
                elif lvs:
                    wt = "ABS"
                else:
                    continue
                WorkRecords.objects.create(
                    employee_id_id=emp_id,
                    date=d,
                    work_record_type=wt,
                    is_attendance_record=has_att,
                    is_leave_record=bool(lvs),
                    note=("匯入：" + ", ".join(f"{n} {h}h" for n, h in lvs)) if lvs else "匯入",
                )
                wr_created += 1
            self.stdout.write(self.style.SUCCESS(f"✓ WorkRecord 同步：{wr_created} 筆"))
