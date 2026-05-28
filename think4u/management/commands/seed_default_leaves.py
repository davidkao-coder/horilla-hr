"""
Think4U: 給所有 active 員工建立預設假別配額（特休 / 事假 / 病假 / 生理假）。

可重跑（idempotent）— 已存在的 AvailableLeave 不會覆蓋；不在預設 4 種內的多餘 row 會
被刪除（避免之前 seed 把 13 種全發給每個人）。

用法：
    python manage.py seed_default_leaves          # 全部 active 員工
    python manage.py seed_default_leaves --emp 5  # 只給某員工
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import models as dj_models

from employee.models import Employee
from leave.models import AvailableLeave, LeaveType
from think4u.models import DEFAULT_LEAVE_TYPE_NAMES, FEMALE_ONLY_LEAVE_TYPES

# 預設天數（依台灣法規）
DEFAULT_QUOTAS = {
    "特休假": 7,    # 滿 1 年；不滿 1 年由 WP-05 特休 calculator 算
    "事假": 14,     # 全年
    "病假": 30,     # 普通病假全年 30 天
    "生理假": 12,   # 每月 1 天 × 12
}


class Command(BaseCommand):
    help = "為員工建立預設假別配額（4 種或女員工 4 種）"

    def add_arguments(self, parser):
        parser.add_argument("--emp", type=int, default=None, help="只給指定員工 id")
        parser.add_argument("--purge-others", action="store_true", help="同時刪除非預設假別的 AvailableLeave")

    def handle(self, *args, **opts):
        AvailableLeave.save = dj_models.Model.save  # 繞 Horilla bug

        targets = Employee.objects.filter(is_active=True)
        if opts.get("emp"):
            targets = targets.filter(id=opts["emp"])

        leave_types = {lt.name: lt for lt in LeaveType.objects.filter(is_active=True)}

        n_created = 0
        n_skipped = 0
        n_purged = 0

        for emp in targets:
            names = list(DEFAULT_LEAVE_TYPE_NAMES)
            if getattr(emp, "gender", None) != "female":
                names = [n for n in names if n not in FEMALE_ONLY_LEAVE_TYPES]

            for name in names:
                lt = leave_types.get(name)
                if not lt:
                    self.stdout.write(self.style.WARNING(f"  ⚠ LeaveType '{name}' 不存在，跳過"))
                    continue
                existing = AvailableLeave.objects.filter(employee_id=emp, leave_type_id=lt).first()
                if existing:
                    n_skipped += 1
                else:
                    AvailableLeave.objects.create(
                        employee_id=emp,
                        leave_type_id=lt,
                        available_days=DEFAULT_QUOTAS.get(name, 0),
                        carryforward_days=0,
                    )
                    n_created += 1

            if opts.get("purge_others"):
                # 刪掉非預設假別的 AvailableLeave（保留管理員手動 grant 過的不影響，因為這指令本就是 reset）
                purged_qs = AvailableLeave.objects.filter(employee_id=emp).exclude(
                    leave_type_id__name__in=names
                )
                purged_qs_count = purged_qs.count()
                purged_qs.delete()
                n_purged += purged_qs_count

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：新建 {n_created} 筆 / 跳過 {n_skipped} 筆 / 清掉 {n_purged} 筆"
            )
        )
