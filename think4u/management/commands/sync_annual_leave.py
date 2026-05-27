"""
think4u/management/commands/sync_annual_leave.py

每年 1/1 執行：為所有在職員工建立當年度 AnnualLeaveRecord。

用法：
    python manage.py sync_annual_leave              # 給今年
    python manage.py sync_annual_leave --year 2026  # 指定年度
    python manage.py sync_annual_leave --dry-run    # 模擬，不寫入
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from employee.models import Employee
from leave.models import AvailableLeave, LeaveType
from think4u.models import AnnualLeaveRecord
from think4u.services.annual_leave_calculator import calculate_jan1_allocation


class Command(BaseCommand):
    help = "每年 1/1 重置全公司特休（歷年制）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--year", type=int, default=None, help="重置年度（預設今年）"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="模擬模式，僅列印不寫入"
        )

    def handle(self, *args, **opts):
        year = opts["year"] or date.today().year
        dry = opts["dry_run"]
        self.stdout.write(f"=== sync_annual_leave for {year} (dry-run={dry}) ===")

        # 取「特休假」這個 LeaveType
        leave_type = LeaveType.objects.filter(name__in=["特休假", "特休", "Annual Leave"]).first()
        if not leave_type:
            self.stdout.write(self.style.ERROR("找不到「特休假」LeaveType，請先設定"))
            return

        granted = 0
        skipped = 0
        carried = 0
        for emp in Employee.objects.filter(is_active=True):
            wi = getattr(emp, "employee_work_info", None)
            hire_date = wi.date_joining if wi else None
            if not hire_date:
                skipped += 1
                self.stdout.write(f"  SKIP {emp}（無到職日）")
                continue

            result = calculate_jan1_allocation(hire_date, year)
            days = result["days"]
            note = result["note"]

            # 1. 計算遞延（去年的 AnnualLeaveRecord 剩餘 → 本年的 carry_over）
            prev_records = AnnualLeaveRecord.objects.filter(
                employee=emp, year=year - 1
            )
            prev_remaining = sum(float(r.remaining) for r in prev_records)
            if prev_remaining > 0:
                carry_expire = date(year, 12, 31)
                if not dry:
                    AnnualLeaveRecord.objects.update_or_create(
                        employee=emp,
                        year=year,
                        source="carry_over",
                        defaults={
                            "allocated_days": Decimal(str(round(prev_remaining, 1))),
                            "used_days": 0,
                            "carried_over": Decimal(str(round(prev_remaining, 1))),
                            "carry_over_expire": carry_expire,
                            "note": f"遞延自 {year - 1}",
                        },
                    )
                self.stdout.write(
                    f"  {emp} ← 遞延 {prev_remaining} 天 (expire {carry_expire})"
                )
                carried += 1

            # 2. 本年度新給
            if not dry:
                AnnualLeaveRecord.objects.update_or_create(
                    employee=emp,
                    year=year,
                    source="annual_reset",
                    defaults={
                        "allocated_days": Decimal(str(days)),
                        "used_days": 0,
                        "carried_over": 0,
                        "carry_over_expire": None,
                        "note": note,
                    },
                )
                # 同步至 leave.AvailableLeave，讓員工請假總覽即時反映
                total = days + (prev_remaining if prev_remaining > 0 else 0)
                AvailableLeave.objects.update_or_create(
                    employee_id=emp,
                    leave_type_id=leave_type,
                    defaults={
                        "available_days": total,
                        "carryforward_days": prev_remaining or 0,
                        "total_leave_days": days,
                        "assigned_date": date(year, 1, 1),
                        "expired_date": date(year, 12, 31),
                    },
                )
            self.stdout.write(f"  {emp} → {days} 天｜{note}")
            granted += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"完成：給假 {granted} 人、遞延 {carried} 人、略過 {skipped} 人"
            )
        )
