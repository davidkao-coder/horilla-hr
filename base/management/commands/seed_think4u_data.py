"""
seed_think4u_data — 為Think4U Tech (Think4U) 客製化 HRMS 載入示範資料。

用法：
    docker compose exec server python manage.py seed_think4u_data
    docker compose exec server python manage.py seed_think4u_data --reset  # 先清掉再灌

載入內容：
- 1 家公司（Think4U Tech）
- 4 部門（技術部 / 業務部 / 行政部 / 人資部）
- 8 個職位
- 2 種工作型態（正職 / 約聘）
- 2 種員工類型（全職 / 兼職）
- 1 個標準班別（9–18）
- 5 種請假類型（特休 / 事假 / 病假 / 婚假 / 喪假）
- 台灣 2026 國定假日
- 週六、週日為公司假
- 4 個 Auth Group（系統管理員 / 人資 HR / 部門主管 / 一般員工）
- 10 位員工（含主管 / HR / 員工，皆密碼 admin）

執行後 admin/admin 仍可登入。
"""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import models as dj_models, transaction

# Base 模型
from base.models import (
    Company,
    CompanyLeaves,
    Department,
    EmployeeShift,
    EmployeeShiftDay,
    EmployeeShiftSchedule,
    EmployeeType,
    Holidays,
    JobPosition,
    WorkType,
)
from employee.models import Employee, EmployeeWorkInformation
from leave.models import AvailableLeave, LeaveType


COMPANY = {
    "company": "Think4U Tech",
    "address": "台北市內湖區瑞光路 100 號",
    "country": "Taiwan",
    "state": "Taipei",
    "city": "Taipei",
    "zip": "11491",
    "hq": True,
    "date_format": "YYYY-MM-DD",
    "time_format": "HH:mm",
}

DEPARTMENTS = ["技術部", "業務部", "行政部", "人資部"]

JOB_POSITIONS = [
    ("技術部", "後端工程師"),
    ("技術部", "前端工程師"),
    ("技術部", "DevOps 工程師"),
    ("技術部", "技術主管"),
    ("業務部", "業務代表"),
    ("業務部", "業務主管"),
    ("行政部", "行政專員"),
    ("人資部", "人資專員"),
]

WORK_TYPES = ["正職", "約聘"]
EMPLOYEE_TYPES = ["全職", "兼職"]

# 標準班別 9:00–18:00（含 12:00–13:00 午休 = 8h 工時）
SHIFT_NAME = "標準班 09–18"
SHIFT_WEEKLY = "40:00"
SHIFT_FULL = "160:00"

LEAVE_TYPES = [
    # 依《勞工請假規則》/ 《性別工作平等法》規劃
    # exclude_holiday/company_leave：是否排除國定假日 / 週末（True = 不計入請假天數）
    # 特休（年資算）
    {"name": "特休假", "total_days": 7, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#39c0ed"},
    # 事假（不給薪，年 14 日）
    {"name": "事假", "total_days": 14, "is_paid": False, "exclude_holiday": True, "exclude_company_leave": True, "color": "#a0a0a0"},
    # 病假（半薪，未住院年 30 日）
    {"name": "病假", "total_days": 30, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#fb6d3a"},
    # 公傷病假（全薪）
    {"name": "公傷病假", "total_days": 365, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#dc3545"},
    # 生理假（性平法 §14：每月 1 日，全年 12 日）
    {"name": "生理假", "total_days": 12, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#ff66b3"},
    # 婚假（8 日連續含例假，3 個月內請完）
    {"name": "婚假", "total_days": 8, "is_paid": True, "exclude_holiday": False, "exclude_company_leave": False, "color": "#e83e8c"},
    # 喪假三檔（勞工請假規則 §3）
    {"name": "喪假（父母/配偶）", "total_days": 8, "is_paid": True, "exclude_holiday": False, "exclude_company_leave": False, "color": "#343a40"},
    {"name": "喪假（祖父母/子女/配偶父母）", "total_days": 6, "is_paid": True, "exclude_holiday": False, "exclude_company_leave": False, "color": "#495057"},
    {"name": "喪假（曾祖父母/兄弟姊妹/配偶祖父母）", "total_days": 3, "is_paid": True, "exclude_holiday": False, "exclude_company_leave": False, "color": "#6c757d"},
    # 產假（性平法 §15：連續 8 週 = 56 日）
    {"name": "產假", "total_days": 56, "is_paid": True, "exclude_holiday": False, "exclude_company_leave": False, "color": "#fd7e14"},
    # 產檢假（性平法 §15：7 日）
    {"name": "產檢假", "total_days": 7, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#ffa94d"},
    # 陪產假（性平法 §15：7 日）
    {"name": "陪產假", "total_days": 7, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#74b9ff"},
    # 公假（依政府公告）
    {"name": "公假", "total_days": 30, "is_paid": True, "exclude_holiday": True, "exclude_company_leave": True, "color": "#20c997"},
]

# 台灣 2026 國定假日（雇主必依勞基法給予的假）
HOLIDAYS_2026 = [
    ("元旦", "2026-01-01", "2026-01-01"),
    ("農曆除夕至初三", "2026-02-16", "2026-02-19"),
    ("228 和平紀念日", "2026-02-28", "2026-03-02"),  # 含補假
    ("兒童節 / 清明節", "2026-04-03", "2026-04-06"),
    ("勞動節", "2026-05-01", "2026-05-01"),
    ("端午節", "2026-06-19", "2026-06-19"),
    ("中秋節", "2026-09-25", "2026-09-25"),
    ("國慶日", "2026-10-09", "2026-10-12"),  # 含補假
]

# 週六、週日皆為公司假（搭配 LeaveType.exclude_company_leave=yes 自動扣除）
COMPANY_LEAVE_DAYS = [("6", "all"), ("0", "all")]  # 週六、週日；based_on_week 留空 = 每週

GROUPS = ["系統管理員", "人資 HR", "部門主管", "一般員工"]

# 員工種子（10 位）：(username, first, last, gender, hire_date, dept, position, work_type, employee_type, group, is_manager)
EMPLOYEES = [
    ("alice",   "Alice",   "Wang",  "female", "2022-01-15", "技術部", "技術主管",   "正職", "全職", "部門主管", True),
    ("brian",   "Brian",   "Chen",  "male",   "2023-03-01", "技術部", "後端工程師",  "正職", "全職", "一般員工", False),
    ("carol",   "Carol",   "Lin",   "female", "2024-07-10", "技術部", "前端工程師",  "正職", "全職", "一般員工", False),
    ("david",   "David",   "Liu",   "male",   "2025-01-20", "技術部", "DevOps 工程師", "正職", "全職", "一般員工", False),
    ("eric",    "Eric",    "Yang",  "male",   "2020-08-01", "業務部", "業務主管",    "正職", "全職", "部門主管", True),
    ("fiona",   "Fiona",   "Hsu",   "female", "2023-09-15", "業務部", "業務代表",    "正職", "全職", "一般員工", False),
    ("george",  "George",  "Tsai",  "male",   "2025-09-15", "業務部", "業務代表",    "約聘", "兼職", "一般員工", False),
    ("hannah",  "Hannah",  "Wu",    "female", "2021-06-01", "行政部", "行政專員",    "正職", "全職", "一般員工", False),
    ("ivy",     "Ivy",     "Kao",   "female", "2019-04-01", "人資部", "人資專員",    "正職", "全職", "人資 HR",  False),
    ("jack",    "Jack",    "Wei",   "male",   "2024-11-10", "人資部", "人資專員",    "正職", "全職", "人資 HR",  False),
]


class Command(BaseCommand):
    help = "Seed Think4U HRMS demo data."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="先清除示範資料再灌新的")

    @transaction.atomic
    def handle(self, *args, **opts):
        # Horilla 多個 base 模型的 save() 把 kwargs 丟給不收參數的 clean()，
        # 與 Django get_or_create / update_or_create 不相容。臨時還原為標準 save。
        for M in (Company, Department, JobPosition, WorkType, EmployeeType, EmployeeShift, LeaveType, Holidays, CompanyLeaves, Employee, EmployeeWorkInformation, AvailableLeave):
            M.save = dj_models.Model.save  # type: ignore[assignment]

        if opts["reset"]:
            self.stdout.write("⏳ 清除舊資料…")
            EmployeeWorkInformation.objects.filter(employee_id__employee_first_name__in=[e[1] for e in EMPLOYEES]).delete()
            Employee.objects.filter(employee_first_name__in=[e[1] for e in EMPLOYEES]).delete()
            User.objects.filter(username__in=[e[0] for e in EMPLOYEES]).delete()

        company = self._seed_company()
        depts = self._seed_departments(company)
        positions = self._seed_positions(depts, company)
        work_types = self._seed_work_types(company)
        emp_types = self._seed_employee_types(company)
        shift = self._seed_shift(company)
        self._seed_leave_types(company)
        self._seed_holidays(company)
        self._seed_company_leaves(company)
        groups = self._seed_groups()
        self._seed_employees(company, depts, positions, work_types, emp_types, shift, groups)
        self._seed_available_leaves()
        self._reset_admin_password()

        self.stdout.write(self.style.SUCCESS("✅ 種子資料載入完成。admin/admin 可繼續登入。"))

    # ---- helpers ----
    def _seed_company(self):
        c, created = Company.objects.get_or_create(
            company=COMPANY["company"],
            address=COMPANY["address"],
            defaults={k: v for k, v in COMPANY.items() if k not in ("company", "address")},
        )
        self.stdout.write(f"  公司：{c} ({'新增' if created else '已存在'})")
        return c

    def _seed_departments(self, company):
        out = {}
        for name in DEPARTMENTS:
            d, _ = Department.objects.get_or_create(department=name)
            d.company_id.add(company)
            out[name] = d
        self.stdout.write(f"  部門：{len(out)} 個")
        return out

    def _seed_positions(self, depts, company):
        out = {}
        for dept_name, pos_name in JOB_POSITIONS:
            p, _ = JobPosition.objects.get_or_create(
                job_position=pos_name, department_id=depts[dept_name]
            )
            p.company_id.add(company)
            out[(dept_name, pos_name)] = p
        self.stdout.write(f"  職位：{len(out)} 個")
        return out

    def _seed_work_types(self, company):
        out = {}
        for name in WORK_TYPES:
            w, _ = WorkType.objects.get_or_create(work_type=name)
            w.company_id.add(company)
            out[name] = w
        self.stdout.write(f"  工作型態：{len(out)} 個")
        return out

    def _seed_employee_types(self, company):
        out = {}
        for name in EMPLOYEE_TYPES:
            e, _ = EmployeeType.objects.get_or_create(employee_type=name)
            e.company_id.add(company)
            out[name] = e
        self.stdout.write(f"  員工類型：{len(out)} 個")
        return out

    def _seed_shift(self, company):
        shift, _ = EmployeeShift.objects.get_or_create(
            employee_shift=SHIFT_NAME,
            defaults={"weekly_full_time": SHIFT_WEEKLY, "full_time": SHIFT_FULL},
        )
        shift.company_id.add(company)

        # 週一到週五的工作時間設定
        weekday_names = [
            ("monday", "Monday"),
            ("tuesday", "Tuesday"),
            ("wednesday", "Wednesday"),
            ("thursday", "Thursday"),
            ("friday", "Friday"),
        ]
        for code, label in weekday_names:
            day, _ = EmployeeShiftDay.objects.get_or_create(day=code)
            EmployeeShiftSchedule.objects.get_or_create(
                day=day,
                shift_id=shift,
                defaults={
                    "minimum_working_hour": "08:00",
                    "start_time": time(9, 0),
                    "end_time": time(18, 0),
                },
            )
        self.stdout.write(f"  班別：{SHIFT_NAME}")
        return shift

    def _seed_leave_types(self, company):
        for lt in LEAVE_TYPES:
            obj, _ = LeaveType.objects.get_or_create(
                name=lt["name"],
                defaults={
                    "color": lt["color"],
                    "payment": "paid" if lt["is_paid"] else "unpaid",
                    "total_days": lt["total_days"],
                    "exclude_holiday": "yes" if lt["exclude_holiday"] else "no",
                    "exclude_company_leave": "yes" if lt["exclude_company_leave"] else "no",
                    "company_id": company,
                },
            )
        self.stdout.write(f"  請假類型：{len(LEAVE_TYPES)} 個")

    def _seed_holidays(self, company):
        for name, s, e in HOLIDAYS_2026:
            Holidays.objects.get_or_create(
                name=name,
                start_date=date.fromisoformat(s),
                end_date=date.fromisoformat(e),
                defaults={"recurring": False, "company_id": company},
            )
        self.stdout.write(f"  國定假日 (2026)：{len(HOLIDAYS_2026)} 筆")

    def _seed_company_leaves(self, company):
        for day, week in COMPANY_LEAVE_DAYS:
            CompanyLeaves.objects.get_or_create(
                based_on_week_day=day,
                based_on_week=None,  # None / 留空 = 每週都放
                defaults={"company_id": company},
            )
        self.stdout.write("  公司假：週六、週日（每週）")

    def _seed_groups(self):
        out = {}
        for name in GROUPS:
            g, _ = Group.objects.get_or_create(name=name)
            out[name] = g
        self.stdout.write(f"  Auth Groups：{len(out)} 個")
        return out

    def _seed_employees(self, company, depts, positions, work_types, emp_types, shift, groups):
        manager_lookup = {}  # dept_name -> Employee instance
        # 第一輪：建主管
        for u, fn, ln, gender, hire, dept, pos, wt, et, grp, is_mgr in EMPLOYEES:
            if not is_mgr:
                continue
            emp = self._make_employee(u, fn, ln, gender, hire, dept, pos, wt, et, shift, depts, positions, work_types, emp_types, groups, grp)
            manager_lookup[dept] = emp
        # 第二輪：建一般員工，掛 reporting_manager
        for u, fn, ln, gender, hire, dept, pos, wt, et, grp, is_mgr in EMPLOYEES:
            if is_mgr:
                continue
            self._make_employee(u, fn, ln, gender, hire, dept, pos, wt, et, shift, depts, positions, work_types, emp_types, groups, grp, manager=manager_lookup.get(dept))
        self.stdout.write(f"  員工：{len(EMPLOYEES)} 位（含 {len(manager_lookup)} 位主管）")

    def _make_employee(self, u, fn, ln, gender, hire, dept, pos, wt, et, shift, depts, positions, work_types, emp_types, groups, group_name, manager=None):
        user, _ = User.objects.get_or_create(username=u, defaults={"email": f"{u}@think4u.example", "first_name": fn, "last_name": ln})
        user.set_password("admin")  # 都用 admin 方便測試
        user.save()
        groups[group_name].user_set.add(user)
        emp, _ = Employee.objects.get_or_create(
            employee_user_id=user,
            defaults={
                "employee_first_name": fn,
                "employee_last_name": ln,
                "email": user.email,
                "gender": gender,
                "phone": "0900-000-000",
            },
        )
        EmployeeWorkInformation.objects.update_or_create(
            employee_id=emp,
            defaults={
                "department_id": depts[dept],
                "job_position_id": positions[(dept, pos)],
                "shift_id": shift,
                "work_type_id": work_types[wt],
                "employee_type_id": emp_types[et],
                "date_joining": date.fromisoformat(hire),
                "company_id": Company.objects.first(),
                "reporting_manager_id": manager,
                "email": user.email,
                "mobile": "0900-000-000",
                "basic_salary": 50000,
                "salary_hour": 250,
            },
        )
        return emp

    def _seed_available_leaves(self):
        """為每位員工 × 每個請假類型建立 AvailableLeave 紀錄"""
        year_start = date(date.today().year, 1, 1)
        year_end = date(date.today().year, 12, 31)
        count = 0
        for emp in Employee.objects.filter(is_active=True):
            for lt in LeaveType.objects.all():
                AvailableLeave.objects.update_or_create(
                    employee_id=emp,
                    leave_type_id=lt,
                    defaults={
                        "available_days": lt.total_days,
                        "carryforward_days": 0,
                        "total_leave_days": lt.total_days,
                        "assigned_date": year_start,
                        "expired_date": year_end,
                    },
                )
                count += 1
        self.stdout.write(f"  AvailableLeave：{count} 筆（員工 × 假別）")

    def _reset_admin_password(self):
        admin = User.objects.filter(username="admin").first()
        if admin:
            admin.set_password("admin")
            admin.is_superuser = True
            admin.is_staff = True
            admin.save()
            self.stdout.write("  admin 密碼已重設為 admin")
