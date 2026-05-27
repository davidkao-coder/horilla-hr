"""
think4u/management/commands/grant_six_month_leave.py

每日 cron 執行：偵測員工今日剛滿 6 個月（到職滿半年），補給 3 天特休。
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from employee.models import Employee
from leave.models import AvailableLeave, LeaveType
from think4u.models import AnnualLeaveRecord
from think4u.services.annual_leave_calculator import calculate_six_month_grant


class Command(BaseCommand):
    help = "每日 cron：到職滿 6 個月當天補給 3 天特休"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date", type=str, default=None, help="模擬日期 (YYYY-MM-DD)"
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        today = (
            date.fromisoformat(opts["date"]) if opts["date"] else date.today()
        )
        dry = opts["dry_run"]
        year = today.year
        self.stdout.write(f"=== grant_six_month_leave {today} (dry-run={dry}) ===")

        leave_type = LeaveType.objects.filter(
            name__in=["特休假", "特休", "Annual Leave"]
        ).first()
        if not leave_type:
            self.stdout.write(self.style.ERROR("找不到「特休假」LeaveType"))
            return

        granted = 0
        for emp in Employee.objects.filter(is_active=True):
            wi = getattr(emp, "employee_work_info", None)
            hire_date = wi.date_joining if wi else None
            if not hire_date:
                continue

            result = calculate_six_month_grant(hire_date, today)
            if not result["should_grant"]:
                continue

            self.stdout.write(f"  {emp}：{result['note']}")
            if dry:
                granted += 1
                continue

            # 寫入 AnnualLeaveRecord
            AnnualLeaveRecord.objects.update_or_create(
                employee=emp,
                year=year,
                source="six_month_grant",
                defaults={
                    "allocated_days": Decimal("3.0"),
                    "used_days": 0,
                    "carried_over": 0,
                    "carry_over_expire": None,
                    "note": result["note"],
                },
            )
            # 累加到 AvailableLeave
            avail, _ = AvailableLeave.objects.get_or_create(
                employee_id=emp,
                leave_type_id=leave_type,
                defaults={
                    "available_days": 3,
                    "total_leave_days": 3,
                    "carryforward_days": 0,
                    "assigned_date": today,
                    "expired_date": date(year, 12, 31),
                },
            )
            if avail.assigned_date is None or avail.assigned_date > today:
                avail.assigned_date = today
            avail.available_days = float(avail.available_days) + 3
            avail.total_leave_days = float(avail.total_leave_days) + 3
            avail.save()
            granted += 1
        self.stdout.write(self.style.SUCCESS(f"完成：補給 {granted} 人"))
