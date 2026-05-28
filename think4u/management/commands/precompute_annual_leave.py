"""
Think4U: 一次性 precompute 每位員工往後 N 年的特休配給。

Model B（週年獲假 + 歷年使用）：
  每個 anniversary 拆 2 筆 LeaveAllocation：
    - anniv_small: anniv ~ 該年 12/31 可用
    - anniv_big  : anniv+1 年 1/1 ~ 12/31 可用

小段天數：floor(tier × 剩餘天數/年總天數 × 2) / 2  （0.5 精度向下取）
大段天數：tier - 小段

執行完會：
1. 寫入 LeaveAllocation rows（idempotent，已有的不重複建）
2. 同步「今日可用」總和 → AvailableLeave.available_days（給 UI 看用）

用法：
    python manage.py precompute_annual_leave              # 預設 20 年
    python manage.py precompute_annual_leave --years 25
    python manage.py precompute_annual_leave --emp 12     # 只算一位
    python manage.py precompute_annual_leave --reset      # 先刪舊的再重算
"""
import math
from calendar import isleap
from datetime import date

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.db import models as dj_models
from django.db import transaction

from employee.models import Employee
from leave.models import AvailableLeave, LeaveType
from think4u.models import LeaveAllocation
from think4u.services.annual_leave_calculator import days_by_full_years


def floor_half(x: float) -> float:
    """向下取 0.5 精度"""
    return math.floor(x * 2) / 2.0


def project_grants(hire_date: date, num_years: int = 20):
    """產生未來 num_years 個 anniversary 的 (small, big) grant pairs"""
    grants = []
    hm, hd = hire_date.month, hire_date.day
    today = date.today()
    for off in range(num_years + 1):  # +1 含今年 anniv
        anniv_year = today.year + off
        sy = anniv_year - hire_date.year
        if sy < 1:
            continue
        try:
            anniv = date(anniv_year, hm, hd)
        except ValueError:
            # Feb 29 邊界
            anniv = date(anniv_year, hm, 28)
        tier = days_by_full_years(sy)
        ye = date(anniv_year, 12, 31)
        remaining_days = (ye - anniv).days + 1
        year_total = 366 if isleap(anniv_year) else 365
        small = floor_half(tier * remaining_days / year_total)
        big = tier - small
        grants.append({
            "service_years": sy,
            "anniv": anniv,
            "tier_days": tier,
            "small_days": small,
            "small_start": anniv,
            "small_end": ye,
            "big_days": big,
            "big_start": date(anniv_year + 1, 1, 1),
            "big_end": date(anniv_year + 1, 12, 31),
        })
    # 也要回填過去 anniversaries（為了「目前可用」能涵蓋）
    # 從 hire_date 起算到 today 的 anniversaries 都加上
    for sy in range(1, today.year - hire_date.year + 1):
        anniv_year = hire_date.year + sy
        if anniv_year >= today.year:
            continue  # 上面 future loop 已涵蓋 anniv_year >= today.year
        try:
            anniv = date(anniv_year, hm, hd)
        except ValueError:
            anniv = date(anniv_year, hm, 28)
        tier = days_by_full_years(sy)
        ye = date(anniv_year, 12, 31)
        remaining_days = (ye - anniv).days + 1
        year_total = 366 if isleap(anniv_year) else 365
        small = floor_half(tier * remaining_days / year_total)
        big = tier - small
        # 只保留 big_end >= today - 1 年（即可能還在遞延期）的
        big_end = date(anniv_year + 1, 12, 31)
        if big_end >= today.replace(year=today.year - 1):
            grants.append({
                "service_years": sy,
                "anniv": anniv,
                "tier_days": tier,
                "small_days": small,
                "small_start": anniv,
                "small_end": ye,
                "big_days": big,
                "big_start": date(anniv_year + 1, 1, 1),
                "big_end": big_end,
            })
    # 按 anniv 排序
    grants.sort(key=lambda g: g["anniv"])
    return grants


class Command(BaseCommand):
    help = "一次性 precompute 員工往後 N 年的特休配給（Model B：週年 + 歷年）"

    def add_arguments(self, parser):
        parser.add_argument("--years", type=int, default=20, help="往後算幾年（預設 20）")
        parser.add_argument("--emp", type=int, default=None, help="只算指定 employee id")
        parser.add_argument("--reset", action="store_true", help="先刪除該員工的舊 LeaveAllocation 再重算")

    def handle(self, *args, **opts):
        LeaveAllocation.save = dj_models.Model.save
        AvailableLeave.save = dj_models.Model.save

        years = opts["years"]
        lt = LeaveType.objects.get(name="特休假")
        today = date.today()

        emps = Employee.objects.filter(is_active=True)
        if opts["emp"]:
            emps = emps.filter(id=opts["emp"])

        total_alloc_created = 0
        total_employees = 0
        for e in emps:
            info = getattr(e, "employee_work_info", None)
            dj = info.date_joining if info else None
            if not dj:
                self.stdout.write(f"  跳過 {e}：無到職日")
                continue

            with transaction.atomic():
                if opts["reset"]:
                    LeaveAllocation.objects.filter(employee=e, leave_type=lt).delete()

                grants = project_grants(dj, years)
                created = 0
                for g in grants:
                    # small
                    _, c1 = LeaveAllocation.objects.update_or_create(
                        employee=e,
                        leave_type=lt,
                        anniversary_date=g["anniv"],
                        grant_type="anniv_small",
                        defaults=dict(
                            service_years=g["service_years"],
                            tier_days=g["tier_days"],
                            days_granted=g["small_days"],
                            start_date=g["small_start"],
                            end_date=g["small_end"],
                            note=f"滿{g['service_years']}年 小段",
                        ),
                    )
                    # big
                    _, c2 = LeaveAllocation.objects.update_or_create(
                        employee=e,
                        leave_type=lt,
                        anniversary_date=g["anniv"],
                        grant_type="anniv_big",
                        defaults=dict(
                            service_years=g["service_years"],
                            tier_days=g["tier_days"],
                            days_granted=g["big_days"],
                            start_date=g["big_start"],
                            end_date=g["big_end"],
                            note=f"滿{g['service_years']}年 大段",
                        ),
                    )
                    if c1:
                        created += 1
                    if c2:
                        created += 1

                # 同步 AvailableLeave.available_days = sum of currently-active allocations
                active = LeaveAllocation.objects.filter(
                    employee=e, leave_type=lt,
                    start_date__lte=today, end_date__gte=today,
                )
                current_avail = sum(
                    float(a.days_granted) - float(a.days_used) for a in active
                )
                # 找最近一個 active 的 start，最遠一個 active 的 end
                if active:
                    earliest = min(a.start_date for a in active)
                    latest = max(a.end_date for a in active)
                else:
                    earliest = today
                    latest = None

                al, _ = AvailableLeave.objects.get_or_create(
                    employee_id=e, leave_type_id=lt,
                    defaults={"available_days": 0, "carryforward_days": 0},
                )
                al.available_days = current_avail
                al.assigned_date = earliest
                al.expired_date = latest
                al.save()

                self.stdout.write(
                    f"  ✓ {e.employee_first_name.strip():<12} 到職 {dj} → "
                    f"{len(grants)} anniv × 2 = {len(grants)*2} allocations; "
                    f"今日可用 {current_avail} 天 ({earliest} ~ {latest or '—'})"
                )
                total_alloc_created += created
                total_employees += 1

        self.stdout.write(self.style.SUCCESS(
            f"完成：{total_employees} 員工，新建 {total_alloc_created} 筆 LeaveAllocation"
        ))
