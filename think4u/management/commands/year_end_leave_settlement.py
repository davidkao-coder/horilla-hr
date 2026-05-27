"""
think4u/management/commands/year_end_leave_settlement.py

每年 12/31 23:59 執行：
1. 把當年剩餘特休標記為「遞延 1 年」並記錄
2. 把去年遞延、今年仍未休完的部分清零，產出折現清單（xlsx）供 HR 計薪
"""

import io
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

from employee.models import Employee
from think4u.models import AnnualLeaveRecord


class Command(BaseCommand):
    help = "每年 12/31 結算：未休遞延 + 上一年遞延未休折現"

    def add_arguments(self, parser):
        parser.add_argument(
            "--year", type=int, default=None, help="結算年度（預設今年）"
        )
        parser.add_argument(
            "--output-dir", type=str, default="/tmp", help="xlsx 輸出目錄"
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        year = opts["year"] or date.today().year
        out_dir = Path(opts["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        dry = opts["dry_run"]
        self.stdout.write(f"=== year_end_settlement {year} (dry={dry}) ===")

        # 1. 標記本年未休 → 隔年的遞延（資訊性，實際遞延由 sync_annual_leave 寫入）
        unused_rows = []
        for emp in Employee.objects.filter(is_active=True):
            records = AnnualLeaveRecord.objects.filter(
                employee=emp, year=year, source__in=("annual_reset", "six_month_grant")
            )
            unused = sum(float(r.remaining) for r in records)
            if unused > 0:
                unused_rows.append(
                    {
                        "employee": str(emp),
                        "department": (
                            emp.employee_work_info.department_id.department
                            if emp.employee_work_info
                            and emp.employee_work_info.department_id
                            else "—"
                        ),
                        "unused_days": round(unused, 1),
                    }
                )

        # 2. 找出去年遞延但今年到期未休的部分 → 歸零並列入折現
        cashout_rows = []
        carry_records = AnnualLeaveRecord.objects.filter(
            year=year, source="carry_over", carry_over_expire=date(year, 12, 31)
        )
        for r in carry_records:
            remaining = float(r.remaining)
            if remaining > 0:
                cashout_rows.append(
                    {
                        "employee": str(r.employee),
                        "department": (
                            r.employee.employee_work_info.department_id.department
                            if r.employee.employee_work_info
                            and r.employee.employee_work_info.department_id
                            else "—"
                        ),
                        "carried_from": year - 1,
                        "expired_remaining": round(remaining, 1),
                    }
                )
                if not dry:
                    # 將 used = allocated（視為到期作廢）
                    r.used_days = r.allocated_days
                    r.note = (r.note or "") + " | 已到期，折現"
                    r.save()

        self.stdout.write(f"未休清單：{len(unused_rows)} 人")
        self.stdout.write(f"折現清單：{len(cashout_rows)} 人")

        # 寫 xlsx
        if Workbook is None:
            self.stdout.write(self.style.WARNING("openpyxl 未安裝，跳過 xlsx 輸出"))
            return

        if unused_rows:
            wb = Workbook()
            ws = wb.active
            ws.title = f"{year} 未休特休"
            ws.append(["員工", "部門", "未休天數"])
            for r in unused_rows:
                ws.append([r["employee"], r["department"], r["unused_days"]])
            path = out_dir / f"{year}_unused_annual_leave.xlsx"
            wb.save(str(path))
            self.stdout.write(f"  → {path}")

        if cashout_rows:
            wb = Workbook()
            ws = wb.active
            ws.title = f"{year} 遞延到期折現"
            ws.append(["員工", "部門", "原年度", "到期未休天數"])
            for r in cashout_rows:
                ws.append(
                    [
                        r["employee"],
                        r["department"],
                        r["carried_from"],
                        r["expired_remaining"],
                    ]
                )
            path = out_dir / f"{year}_carry_over_expired.xlsx"
            wb.save(str(path))
            self.stdout.write(f"  → {path}")

        self.stdout.write(self.style.SUCCESS("year-end settlement 完成"))
